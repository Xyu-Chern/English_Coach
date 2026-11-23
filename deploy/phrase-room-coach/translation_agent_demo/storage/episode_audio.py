"""Where a citation plays in the publisher's audio: enclosures, transcript time markers and clip estimates.

Enclosure rows (podcast_episode_audio, migration 010) keep the Podcast Index URL and duration; audio is never
downloaded. A chunk with stored cue timing plays from it; else its offset is interpolated between the publisher's
time markers (transcript_time_anchors, migration 013), ~3 s early; else it is the character position times the
duration, 15 s early. Markers such as "[08:24]" or "[01:04:02.14]" give the time where the next paragraph starts.
A marker-only cue labelled "Break", "Outro" or "Jingle" starts untranscribed audio of unknown length, so it becomes
a segment_start at the end of the preceding speech and a segment_end_estimate where the next speech starts,
estimated back from the next anchor at the document's speech rate. Document offsets count over one build's
"".join(cue["text"] for cue in corpus_builds.cues); chunk_to_document_offset maps chunk-relative offsets there.
"""

import re
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Literal, NamedTuple
from uuid import UUID

import psycopg

from .postgres import CorpusStorageError
from .retrieval import _display_url

LEAD_IN_MS, TAIL_MS = 15_000, 5_000  # a character-position estimate starts early: it is only a proxy
ANCHORED_LEAD_IN_MS = ANCHORED_TAIL_MS = 3_000  # between two markers the error is seconds (median 3.3 s)
MAX_DURATION_S = 48 * 60 * 60  # larger upstream values are treated as unknown
MAX_CHUNKS, MAX_SAVE, MAX_LOAD = 50, 1000, 200
SOURCES = SOURCE_INLINE_MARKER, SOURCE_SEGMENT_START, SOURCE_SEGMENT_END = (
    "inline_marker", "segment_start", "segment_end_estimate")
# ms of audio per transcript character, calibrated on 19,216 local marker intervals (2026-11): p1 50, median 63,
# p95 115; the top 1% span breaks. Rates are clamped so a break or a mistyped marker cannot stretch an estimate.
MIN_MS_PER_CHAR, MAX_MS_PER_CHAR, DEFAULT_MS_PER_CHAR = 45, 120, 63
MIN_RATE_SPAN_CHARS = 500  # two anchors closer than this give no speech rate
MIN_SEGMENT_TEXT_CHARS = 50  # a segment followed this closely by a marker needs no estimate
# Optional escapes and hours, minutes, 2-digit seconds, 1-3 digit fraction; "[00:00:00:00]" and "[1.5]" do not match.
_MARKER = re.compile(r"\\?\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\\?\]")
_SPACES = re.compile(r"\s*")
# Shared with frontend/audio_align.py: the enclosure (a) of a chunk's episode and the chunk's document offsets (pos).
AUDIO_POSITION_SQL = """
    JOIN public.podcast_episode_audio AS a
      ON a.episode_id = s.episode_id AND (a.feed_id IS NULL OR a.feed_id = s.feed_id)
    CROSS JOIN LATERAL (
        SELECT coalesce(sum(length(q.value ->> 'text')) FILTER (WHERE q.n - 1 < (c.spans -> 0 ->> 'cue_index')::int),
                        0) + (c.spans -> 0 ->> 'start_char')::int AS char_start,
               coalesce(sum(length(q.value ->> 'text')) FILTER (WHERE q.n - 1 < (c.spans -> -1 ->> 'cue_index')::int),
                        0) + (c.spans -> -1 ->> 'end_char')::int AS char_end,
               coalesce(sum(length(q.value ->> 'text')), 0) AS char_total
        FROM jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)) AS pos"""
_TRANSCRIBED = """public.podcast_sources AS s WHERE s.source_key LIKE 'podcast_index:%%'
              AND EXISTS (SELECT 1 FROM public.podcast_transcripts AS t WHERE t.source_key = s.source_key)"""


@dataclass(frozen=True)
class EpisodeAudio:
    episode_id: int
    feed_id: int | None
    enclosure_url: str
    duration_s: int | None


@dataclass(frozen=True)
class AudioClip:
    """Citation audio fields; the defaults mean no known audio."""

    audio_url: str | None = None
    audio_start_ms: int | None = None
    audio_end_ms: int | None = None
    audio_estimated: bool = False

    def as_fields(self) -> dict[str, Any]:
        return asdict(self)


NO_AUDIO = AudioClip()


class Anchor(NamedTuple):
    char_offset: int
    time_ms: int
    source: str = SOURCE_INLINE_MARKER


class TimeEstimate(NamedTuple):
    """confidence "anchored" (between or on anchors), "extrapolated" (outside them), "proportional" (no anchors)
    or "none" (time_ms None); gap_ms: the surrounding anchors' gap (0 on one), the distance from the nearest
    anchor, the whole duration, or None."""

    time_ms: int | None
    confidence: Literal["anchored", "extrapolated", "proportional", "none"]
    gap_ms: int | None


def _marker_ms(match: re.Match) -> int | None:
    hours, minutes, seconds, fraction = match.groups()
    h, m, s = int(hours or 0), int(minutes), int(seconds)
    if s >= 60 or (hours is not None and m >= 60):
        return None
    return ((h * 60 + m) * 60 + s) * 1000 + (int(fraction.ljust(3, "0")) if fraction else 0)


def extract_inline_markers(text: str) -> list[tuple[int, int]]:
    """(char_offset, time_ms) of every well-formed marker in text order; the offset is the first non-space
    character after it. Order is not checked (see monotonic)."""
    return [(_SPACES.match(text, m.end()).end(), ms) for m in _MARKER.finditer(text)
            if (ms := _marker_ms(m)) is not None]


def monotonic(anchors: Iterable[Sequence]) -> list:
    """The longest subsequence with strictly increasing offsets and non-decreasing times. Items
    (char_offset, time_ms, ...) come back unchanged; one mistyped marker drops only itself."""
    items = sorted(anchors, key=lambda item: (item[0], item[1]))
    items = [item for i, item in enumerate(items) if i == 0 or item[0] != items[i - 1][0]]
    tails, tail_times, previous = [], [], [-1] * len(items)  # tails[k]: the run of length k+1 ending lowest
    for i, item in enumerate(items):
        k = bisect_left(tail_times, item[1] + 1)  # equal times extend a run
        previous[i] = tails[k - 1] if k else -1
        if k == len(tails):
            tails.append(i)
            tail_times.append(item[1])
        else:
            tails[k], tail_times[k] = i, item[1]
    result, i = [], tails[-1] if tails else -1
    while i >= 0:
        result.append(items[i])
        i = previous[i]
    return result[::-1]


def _clamp_rate(rate: float) -> float:
    return min(max(rate, MIN_MS_PER_CHAR), MAX_MS_PER_CHAR)


def document_anchors(cues: Sequence[tuple[str, str | None]]) -> list[Anchor]:
    """All anchors of one build from its cues' (text, speaker), in document offsets; out-of-order markers are
    dropped before segment ends are estimated."""
    found: list[tuple[int, int, str, int]] = []  # (offset, ms, source, segment end offset)
    base = 0
    for text, speaker in cues:
        whole = _MARKER.fullmatch(text.strip())
        if whole is not None and speaker:
            if (time_ms := _marker_ms(whole)) is not None:
                found.append((base + len(text) - len(text.lstrip()), time_ms, SOURCE_SEGMENT_START, base + len(text)))
        else:
            found += [(base + offset, ms, SOURCE_INLINE_MARKER, 0) for offset, ms in extract_inline_markers(text)]
        base += len(text)
    kept = monotonic(found)
    rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(kept, kept[1:])
             if a[2] == SOURCE_INLINE_MARKER and b[0] - a[0] >= MIN_RATE_SPAN_CHARS]
    rate = _clamp_rate(median(rates)) if rates else DEFAULT_MS_PER_CHAR
    anchors = [Anchor(offset, ms, source) for offset, ms, source, _ in kept]
    for (_, ms, source, end), (next_offset, next_ms, _, _) in zip(kept, kept[1:]):
        if source == SOURCE_SEGMENT_START and next_offset - end >= MIN_SEGMENT_TEXT_CHARS:
            anchors.append(Anchor(end, max(ms, round(next_ms - (next_offset - end) * rate)), SOURCE_SEGMENT_END))
    return sorted(anchors)


def interpolate(anchors: Sequence[Sequence[int]], char_offset: int, *,
                doc_length: int | None, duration_ms: int | None) -> TimeEstimate:
    """Audio time of a document offset from (char_offset, time_ms, ...) anchors of the same build: linear between
    anchors; outside them the nearest anchor plus the rate to the nearest other anchor at least MIN_RATE_SPAN_CHARS
    away on that side, else duration_ms / doc_length, else DEFAULT_MS_PER_CHAR, clamped to [MIN, MAX]_MS_PER_CHAR;
    no anchors: that share of the duration. Results stay in [0, duration_ms]."""
    points = sorted((int(point[0]), int(point[1])) for point in anchors)
    offset = max(0, char_offset)
    if doc_length is not None and doc_length > 0:
        offset = min(offset, doc_length)
    overall = duration_ms / doc_length if doc_length and duration_ms and doc_length > 0 and duration_ms > 0 else None

    def clamp(value: float) -> int:
        value = max(0.0, value)
        return round(min(value, float(duration_ms)) if duration_ms and duration_ms > 0 else value)

    if not points:
        return (TimeEstimate(clamp(offset * overall), "proportional", duration_ms) if overall
                else TimeEstimate(None, "none", None))
    offsets = [point[0] for point in points]
    i = bisect_left(offsets, offset)
    if i < len(points) and offsets[i] == offset:
        return TimeEstimate(clamp(points[i][1]), "anchored", 0)
    if 0 < i < len(points):
        (left_char, left_ms), (right_char, right_ms) = points[i - 1], points[i]
        share = (offset - left_char) / (right_char - left_char)
        return TimeEstimate(clamp(left_ms + share * (right_ms - left_ms)), "anchored", right_ms - left_ms)
    side = points if i == 0 else points[::-1]
    near_char, near_ms = side[0]
    other = next((p for p in side[1:] if abs(p[0] - near_char) >= MIN_RATE_SPAN_CHARS), None)
    rate = abs(other[1] - near_ms) / abs(other[0] - near_char) if other else overall or DEFAULT_MS_PER_CHAR
    estimate = clamp(near_ms + (offset - near_char) * _clamp_rate(rate))
    return TimeEstimate(estimate, "extrapolated", abs(estimate - near_ms))


def chunk_to_document_offset(spans: Sequence[Mapping | Sequence], cue_starts: Mapping[int, int] | Sequence[int],
                             chunk_char: int) -> int:
    """A chunk-text offset as a document offset. spans: corpus_chunks.spans in order (dicts or (cue_index,
    start_char, end_char)), whose slices joined by single spaces are the chunk text; cue_starts[cue_index]: the
    cue's document offset. A joining space maps to the end of the slice before it (right for exclusive ends);
    offsets past the end clamp to the end of the last slice."""
    if not spans:
        raise ValueError("A chunk has at least one span.")
    position, chunk_char = 0, max(0, chunk_char)
    for span in spans:
        cue, start, end = ((span["cue_index"], span["start_char"], span["end_char"])
                           if isinstance(span, Mapping) else span)
        cue, start, end = int(cue), int(start), int(end)
        if chunk_char <= position + end - start:
            return cue_starts[cue] + start + chunk_char - position
        position += end - start + 1  # the joining space
    return cue_starts[cue] + end


def estimate_clip(audio_url: str | None, *, start_ms: int | None, end_ms: int | None, char_start: int | None,
                  char_end: int | None, char_total: int | None, duration_s: int | None,
                  anchors: Sequence[Sequence[int]] | None = None) -> AudioClip:
    """Stored cue timing wins; else the transcript's markers (anchors of the same build), ~3 s early;
    else character ratio x duration, 15 s early."""
    if audio_url is None:
        return NO_AUDIO
    if start_ms is not None:
        return AudioClip(audio_url, start_ms, end_ms, False)
    duration = duration_s * 1000 if duration_s else None
    if anchors and char_start is not None and char_end is not None:
        first, last = (interpolate(anchors, char, doc_length=char_total, duration_ms=duration)
                       for char in (char_start, char_end))
        if first.time_ms is not None and last.time_ms is not None:
            close = first.confidence == last.confidence == "anchored"
            start = max(0, first.time_ms - (ANCHORED_LEAD_IN_MS if close else LEAD_IN_MS))
            end = last.time_ms + (ANCHORED_TAIL_MS if close else TAIL_MS)
            return AudioClip(audio_url, start, max(start, min(duration, end) if duration else end), True)
    if not duration or not char_total or char_start is None or char_end is None:
        return AudioClip(audio_url)
    start, end = (round(min(max(char / char_total, 0.0), 1.0) * duration) for char in (char_start, char_end))
    start, end = max(0, start - LEAD_IN_MS), min(duration, end + TAIL_MS)
    return AudioClip(audio_url, start, max(start, end), True)


def audio_from_episode(episode: Any) -> EpisodeAudio | None:
    """enclosureUrl/duration of one Podcast Index episode dict; None if unusable."""
    if not isinstance(episode, dict):
        return None
    episode_id, url = _positive_int(episode.get("id")), episode.get("enclosureUrl")
    url = _display_url(url.strip()) if isinstance(url, str) else None
    if episode_id is None or url is None:
        return None
    return EpisodeAudio(episode_id, _positive_int(episode.get("feedId")), url,
                        _positive_int(episode.get("duration"), MAX_DURATION_S))


def _positive_int(value: Any, maximum: int = 2**63 - 1) -> int | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if type(value) is int and 0 < value <= maximum else None


@contextmanager
def _storage(message: str):
    """psycopg errors as CorpusStorageError(message), without the driver's details."""
    try:
        yield
    except psycopg.Error:
        raise CorpusStorageError(message) from None


def save_episode_audio(conn: psycopg.Connection, records: Iterable[EpisodeAudio]) -> int:
    """Upsert up to MAX_SAVE enclosure records in one transaction; returns rows written."""
    rows = [(r.episode_id, r.feed_id, r.enclosure_url, r.duration_s) for r in records]
    if len(rows) > MAX_SAVE:
        raise ValueError(f"Save at most {MAX_SAVE} audio records at once.")
    if rows:
        with _storage("Could not save episode audio records."), conn.transaction(), conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO public.podcast_episode_audio (episode_id, feed_id, enclosure_url, duration_s)
                VALUES (%s, %s, %s, %s) ON CONFLICT (episode_id) DO UPDATE SET
                    feed_id = coalesce(EXCLUDED.feed_id, podcast_episode_audio.feed_id),
                    enclosure_url = EXCLUDED.enclosure_url, fetched_at = now(),
                    duration_s = coalesce(EXCLUDED.duration_s, podcast_episode_audio.duration_s)""", rows)
    return len(rows)


def episodes_missing_audio(conn: psycopg.Connection, *, feed_ids: Sequence[int] | None = None) -> list[tuple[int, int]]:
    """(feed_id, episode_id) of stored Podcast Index transcripts that have no audio row."""
    feeds = list(feed_ids) if feed_ids is not None else None
    with _storage("Could not list episodes without audio."):
        rows = conn.execute(f"""
            SELECT DISTINCT s.feed_id, s.episode_id FROM {_TRANSCRIBED}
              AND NOT EXISTS (SELECT 1 FROM public.podcast_episode_audio AS a WHERE a.episode_id = s.episode_id)
              AND (%s::bigint[] IS NULL OR s.feed_id = ANY(%s::bigint[])) ORDER BY s.feed_id, s.episode_id""",
                            (feeds, feeds)).fetchall()
    return [(int(feed), int(episode)) for feed, episode in rows]


def audio_coverage(conn: psycopg.Connection) -> tuple[int, int]:
    """(episodes with audio, stored Podcast Index transcript episodes)."""
    with _storage("Could not count episode audio coverage."):
        row = conn.execute(f"""
            SELECT count(*) FILTER (WHERE a.episode_id IS NOT NULL), count(*)
            FROM (SELECT DISTINCT s.episode_id FROM {_TRANSCRIBED}) AS e
            LEFT JOIN public.podcast_episode_audio AS a USING (episode_id)""").fetchone()
    return int(row[0]), int(row[1])


def audio_clips_for_chunks(conn: psycopg.Connection, chunk_ids: Sequence[UUID]) -> dict[UUID, AudioClip]:
    """Playable clips of retrieved chunks; chunks without audio are absent: clips.get(chunk_id, NO_AUDIO)."""
    ids = list(dict.fromkeys(chunk_ids))
    if len(ids) > MAX_CHUNKS or any(not isinstance(value, UUID) for value in ids):
        raise ValueError(f"chunk_ids must contain at most {MAX_CHUNKS} UUIDs.")
    if not ids:
        return {}
    with _storage("Could not read episode audio for chunks."):
        rows = conn.execute(f"""
            SELECT c.chunk_id, c.start_ms, c.end_ms, a.enclosure_url, a.duration_s,
                   pos.char_start, pos.char_end, pos.char_total, c.build_id
            FROM public.corpus_chunks AS c JOIN public.corpus_builds AS b USING (build_id)
            JOIN public.podcast_transcripts AS d USING (document_id)
            JOIN public.podcast_sources AS s USING (source_key) {AUDIO_POSITION_SQL}
            WHERE c.chunk_id = ANY(%s::uuid[]) AND s.source_key LIKE 'podcast_index:%%'""", (ids,)).fetchall()
    anchors = anchors_for_builds(conn, [row[8] for row in rows if row[1] is None])
    clips = {}
    for chunk_id, start_ms, end_ms, url, duration_s, char_start, char_end, char_total, build_id in rows:
        if (url := _display_url(url)) is not None:
            clips[chunk_id] = estimate_clip(url, start_ms=start_ms, end_ms=end_ms, char_start=char_start,
                                            char_end=char_end, char_total=char_total, duration_s=duration_s,
                                            anchors=anchors.get(build_id))
    return clips


def anchors_for_builds(conn: psycopg.Connection, build_ids: Sequence[UUID]) -> Mapping[UUID, list[tuple[int, int]]]:
    """build_id -> monotonic (char_offset, time_ms) markers in its document offsets. Builds without markers are
    absent, and all are when the table (migration 013) is missing or unreadable or over MAX_LOAD builds are asked."""
    ids = [value for value in dict.fromkeys(build_ids) if isinstance(value, UUID)]
    if not ids or len(ids) > MAX_LOAD:
        return {}
    try:
        exists = conn.execute("SELECT to_regclass('public.transcript_time_anchors') IS NOT NULL").fetchone()
        rows = conn.execute("SELECT build_id, char_offset, time_ms FROM public.transcript_time_anchors "
                            "WHERE build_id = ANY(%s::uuid[]) ORDER BY build_id, char_offset",
                            (ids,)).fetchall() if exists and exists[0] else []
    except psycopg.Error:
        return {}
    grouped: dict[UUID, list[tuple[int, int]]] = {}
    for build_id, char, ms in rows:
        grouped.setdefault(build_id, []).append((int(char), int(ms)))
    return {build_id: monotonic(points) for build_id, points in grouped.items()}


def replace_document_anchors(conn: psycopg.Connection, document_id: UUID, build_id: UUID,
                             anchors: Sequence[Anchor]) -> int:
    """In one transaction, delete the document's rows of these SOURCES and of any other build (stale offsets),
    then insert `anchors` (build_id's offsets). Returns rows written."""
    rows = [(document_id, int(a.char_offset), int(a.time_ms), a.source, build_id) for a in anchors]
    with _storage("Could not save transcript time anchors."), conn.transaction(), conn.cursor() as cursor:
        cursor.execute("DELETE FROM public.transcript_time_anchors WHERE document_id = %s "
                       "AND (source = ANY(%s) OR build_id <> %s)", (document_id, list(SOURCES), build_id))
        if rows:
            cursor.executemany("INSERT INTO public.transcript_time_anchors (document_id, char_offset, time_ms, "
                               "source, build_id) VALUES (%s, %s, %s, %s, %s)", rows)
    return len(rows)
