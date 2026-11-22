"""Episode audio enclosures and per-chunk playback offsets for citations.

Rows store the publisher's enclosure URL and duration from Podcast Index
metadata; audio bytes are never downloaded or stored. A chunk with stored cue
timing plays from that timing. Otherwise the offset is interpolated between the
publisher's time markers in the transcript (time_anchors.py, migration 013) and
started about 3 s early; without markers it is the chunk's character position
times the episode duration, started 15 s early. Both are `audio_estimated=True`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

import psycopg

from .postgres import CorpusStorageError
from .retrieval import _display_url
from .time_anchors import interpolate, load_anchors

LEAD_IN_MS = 15_000  # Estimated offsets start early; character position is only a proxy.
TAIL_MS = 5_000
ANCHORED_LEAD_IN_MS = 3_000  # Between two time markers the estimate is within seconds (median 3.3 s).
ANCHORED_TAIL_MS = 3_000
MAX_DURATION_S = 48 * 60 * 60  # Larger upstream values are treated as unknown.
MAX_CHUNKS = 50
MAX_SAVE = 1000


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


def _positive_int(value: Any, maximum: int = 2**63 - 1) -> int | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if type(value) is int and 0 < value <= maximum else None


def audio_from_episode(episode: Any) -> EpisodeAudio | None:
    """Read enclosureUrl/duration from one Podcast Index episode dict; None if unusable."""
    if not isinstance(episode, dict):
        return None
    episode_id = _positive_int(episode.get("id"))
    url = episode.get("enclosureUrl")
    url = _display_url(url.strip()) if isinstance(url, str) else None
    if episode_id is None or url is None:
        return None
    return EpisodeAudio(
        episode_id=episode_id,
        feed_id=_positive_int(episode.get("feedId")),
        enclosure_url=url,
        duration_s=_positive_int(episode.get("duration"), MAX_DURATION_S),
    )


def save_episode_audio(conn: psycopg.Connection, records: Iterable[EpisodeAudio]) -> int:
    """Upsert up to 1000 enclosure records in one transaction; returns rows written."""
    rows = [(r.episode_id, r.feed_id, r.enclosure_url, r.duration_s) for r in records]
    if len(rows) > MAX_SAVE:
        raise ValueError(f"Save at most {MAX_SAVE} audio records at once.")
    if not rows:
        return 0
    try:
        with conn.transaction(), conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO public.podcast_episode_audio (episode_id, feed_id, enclosure_url, duration_s)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (episode_id) DO UPDATE SET
                    feed_id = coalesce(EXCLUDED.feed_id, podcast_episode_audio.feed_id),
                    enclosure_url = EXCLUDED.enclosure_url,
                    duration_s = coalesce(EXCLUDED.duration_s, podcast_episode_audio.duration_s),
                    fetched_at = now()
                """,
                rows,
            )
    except psycopg.Error:
        raise CorpusStorageError("Could not save episode audio records.") from None
    return len(rows)


def episodes_missing_audio(
    conn: psycopg.Connection, *, feed_ids: Sequence[int] | None = None,
) -> list[tuple[int, int]]:
    """(feed_id, episode_id) of stored Podcast Index transcripts that have no audio row."""
    feeds = list(feed_ids) if feed_ids is not None else None
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT s.feed_id, s.episode_id
            FROM public.podcast_sources AS s
            WHERE s.source_key LIKE 'podcast_index:%%'
              AND EXISTS (SELECT 1 FROM public.podcast_transcripts AS t WHERE t.source_key = s.source_key)
              AND NOT EXISTS (SELECT 1 FROM public.podcast_episode_audio AS a WHERE a.episode_id = s.episode_id)
              AND (%s::bigint[] IS NULL OR s.feed_id = ANY(%s::bigint[]))
            ORDER BY s.feed_id, s.episode_id
            """,
            (feeds, feeds),
        ).fetchall()
    except psycopg.Error:
        raise CorpusStorageError("Could not list episodes without audio.") from None
    return [(int(feed), int(episode)) for feed, episode in rows]


def audio_coverage(conn: psycopg.Connection) -> tuple[int, int]:
    """(episodes with audio, stored Podcast Index transcript episodes)."""
    try:
        row = conn.execute(
            """
            SELECT count(*) FILTER (WHERE a.episode_id IS NOT NULL), count(*)
            FROM (SELECT DISTINCT s.episode_id FROM public.podcast_sources AS s
                  WHERE s.source_key LIKE 'podcast_index:%%'
                    AND EXISTS (SELECT 1 FROM public.podcast_transcripts AS t
                                WHERE t.source_key = s.source_key)) AS e
            LEFT JOIN public.podcast_episode_audio AS a USING (episode_id)
            """
        ).fetchone()
    except psycopg.Error:
        raise CorpusStorageError("Could not count episode audio coverage.") from None
    return int(row[0]), int(row[1])


def estimate_clip(
    audio_url: str | None, *, start_ms: int | None, end_ms: int | None,
    char_start: int | None, char_end: int | None, char_total: int | None,
    duration_s: int | None, anchors: Sequence[Sequence[int]] | None = None,
) -> AudioClip:
    """Stored cue timing wins; else the transcript's time markers (anchors from load_anchors, same build),
    started ~3 s early; else character ratio x duration, started 15 s early."""
    if audio_url is None:
        return NO_AUDIO
    if start_ms is not None:
        return AudioClip(audio_url, start_ms, end_ms, False)
    if anchors and char_start is not None and char_end is not None:
        duration = duration_s * 1000 if duration_s else None
        first = interpolate(anchors, char_start, doc_length=char_total, duration_ms=duration)
        last = interpolate(anchors, char_end, doc_length=char_total, duration_ms=duration)
        if first.time_ms is not None and last.time_ms is not None:
            close = first.confidence == last.confidence == "anchored"
            start = max(0, first.time_ms - (ANCHORED_LEAD_IN_MS if close else LEAD_IN_MS))
            end = last.time_ms + (ANCHORED_TAIL_MS if close else TAIL_MS)
            end = min(duration, end) if duration else end
            return AudioClip(audio_url, start, max(start, end), True)
    if not duration_s or not char_total or char_start is None or char_end is None:
        return AudioClip(audio_url)
    duration_ms = duration_s * 1000

    def at(chars: int) -> int:
        return round(min(max(chars / char_total, 0.0), 1.0) * duration_ms)

    start = max(0, at(char_start) - LEAD_IN_MS)
    end = min(duration_ms, at(char_end) + TAIL_MS)
    return AudioClip(audio_url, start, max(start, end), True)


def anchors_for_builds(conn: psycopg.Connection, build_ids: Sequence[UUID]) -> Mapping[UUID, list]:
    """Time markers per build; empty when the table (migration 013) is not there or unreadable."""
    ids = [value for value in dict.fromkeys(build_ids) if isinstance(value, UUID)]
    if not ids:
        return {}
    try:
        exists = conn.execute("SELECT to_regclass('public.transcript_time_anchors') IS NOT NULL").fetchone()
        return load_anchors(conn, ids) if exists and exists[0] else {}
    except (CorpusStorageError, psycopg.Error, ValueError):
        return {}


def audio_clips_for_chunks(
    conn: psycopg.Connection, chunk_ids: Sequence[UUID],
) -> dict[UUID, AudioClip]:
    """Map retrieved chunk IDs to playable clips; chunks without audio are absent.

    Use `clips.get(chunk_id, NO_AUDIO).as_fields()` to fill citation fields.
    """
    ids = list(dict.fromkeys(chunk_ids))
    if len(ids) > MAX_CHUNKS or any(not isinstance(value, UUID) for value in ids):
        raise ValueError(f"chunk_ids must contain at most {MAX_CHUNKS} UUIDs.")
    if not ids:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.start_ms, c.end_ms, a.enclosure_url, a.duration_s,
                   pos.char_start, pos.char_end, pos.char_total, c.build_id
            FROM public.corpus_chunks AS c
            JOIN public.corpus_builds AS b USING (build_id)
            JOIN public.podcast_transcripts AS d USING (document_id)
            JOIN public.podcast_sources AS s USING (source_key)
            JOIN public.podcast_episode_audio AS a
              ON a.episode_id = s.episode_id AND (a.feed_id IS NULL OR a.feed_id = s.feed_id)
            CROSS JOIN LATERAL (
                SELECT coalesce(sum(length(q.value ->> 'text'))
                           FILTER (WHERE q.n - 1 < (c.spans -> 0 ->> 'cue_index')::int), 0)
                         + (c.spans -> 0 ->> 'start_char')::int AS char_start,
                       coalesce(sum(length(q.value ->> 'text'))
                           FILTER (WHERE q.n - 1 < (c.spans -> -1 ->> 'cue_index')::int), 0)
                         + (c.spans -> -1 ->> 'end_char')::int AS char_end,
                       coalesce(sum(length(q.value ->> 'text')), 0) AS char_total
                FROM jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)
            ) AS pos
            WHERE c.chunk_id = ANY(%s::uuid[]) AND s.source_key LIKE 'podcast_index:%%'
            """,
            (ids,),
        ).fetchall()
    except psycopg.Error:
        raise CorpusStorageError("Could not read episode audio for chunks.") from None
    anchors = anchors_for_builds(conn, [row[8] for row in rows if row[1] is None])
    clips = {}
    for chunk_id, start_ms, end_ms, url, duration_s, char_start, char_end, char_total, build_id in rows:
        url = _display_url(url)
        if url is not None:
            clips[chunk_id] = estimate_clip(
                url, start_ms=start_ms, end_ms=end_ms, char_start=char_start,
                char_end=char_end, char_total=char_total, duration_s=duration_s,
                anchors=anchors.get(build_id),
            )
    return clips
