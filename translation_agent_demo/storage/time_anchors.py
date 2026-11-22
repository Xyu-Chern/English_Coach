"""Time anchors: transcript positions whose audio time the publisher wrote into the text.

Changelog-style transcripts carry inline markers such as "[08:24]" (minutes:seconds, used in
the first hour) and "[01:04:02.14]" (hours:minutes:seconds.fraction); raw Markdown escapes
them as "\\[08:24\\]". A marker is the audio time at which the following paragraph starts.
The parser keeps them as plain text inside the cues, so they are read back without reparsing.

One exception: a cue that is only a marker under a label such as "Break", "Outro" or "Jingle"
starts audio that is not transcribed (a sponsor break, music). The text after it starts later
by that segment's unknown length (79 s in one spot check), so such a marker becomes two anchors:
"segment_start" at the end of the preceding speech (the publisher's time), and
"segment_end_estimate" at the start of the following speech, estimated back from the next
anchor at the document's speech rate (never before the segment start). Linear interpolation
between those two anchors is then the untranscribed segment itself.

Coordinate system (document offset): a character position in the concatenation of one build's
cue texts with no separator, "".join(cue["text"] for cue in corpus_builds.cues). This is the
char_start/char_end/char_total that episode_audio.audio_clips_for_chunks computes for the
audio estimate. A quote's offsets (SourceCitation.quote_start_char) are relative to its chunk
text; chunk_to_document_offset maps them into this system.

Pure: extract_inline_markers, monotonic, document_anchors, interpolate, chunk_to_document_offset.
DB I/O: replace_document_anchors, load_anchors (table transcript_time_anchors, migration 013).
"""

import re
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from statistics import median
from typing import Literal, NamedTuple
from uuid import UUID

import psycopg

from .postgres import CorpusStorageError

SOURCE_INLINE_MARKER = "inline_marker"
SOURCE_SEGMENT_START = "segment_start"
SOURCE_SEGMENT_END = "segment_end_estimate"
SOURCES = (SOURCE_INLINE_MARKER, SOURCE_SEGMENT_START, SOURCE_SEGMENT_END)
# ms of audio per transcript character. Calibrated on the local corpus (19,216 marker intervals,
# 2026-11): p1 50, p5 54, median 63, p95 115; the top 1% (>1,000) span untranscribed breaks.
# Every rate used to extrapolate or to estimate a segment end is clamped to [MIN, MAX], so an
# interval that spans a break or a mistyped marker cannot stretch an estimate.
MIN_MS_PER_CHAR = 45
MAX_MS_PER_CHAR = 120
DEFAULT_MS_PER_CHAR = 63  # The corpus median, used when no local or global rate exists.
MIN_RATE_SPAN_CHARS = 500  # Two anchors closer than this (e.g. around one marker) give no speech rate.
MIN_SEGMENT_TEXT_CHARS = 50  # A segment followed this closely by a marker needs no estimate.
MAX_LOAD = 200

# Optional backslash escapes, optional 1-2 digit hours, 1-2 digit minutes, 2 digit seconds,
# optional 1-3 digit fraction. "[00:00:00:00]" (frames) and "[1.5]" do not match.
_MARKER = re.compile(r"\\?\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\\?\]")

Confidence = Literal["anchored", "extrapolated", "proportional", "none"]


class Anchor(NamedTuple):
    char_offset: int
    time_ms: int
    source: str = SOURCE_INLINE_MARKER


class TimeEstimate(NamedTuple):
    """Where a document offset plays, and how far the evidence is from it.

    time_ms     the estimate, or None when nothing is known (no anchors and no duration)
    confidence  "anchored": between two anchors (or exactly on one); "extrapolated": before
                the first or after the last anchor; "proportional": no anchors, offset share
                of the duration (the old estimate); "none": time_ms is None
    gap_ms      precision hint: anchored = time between the surrounding anchors (0 on an
                anchor); extrapolated = distance from the nearest anchor's time;
                proportional = the whole duration; none = None
    """

    time_ms: int | None
    confidence: Confidence
    gap_ms: int | None


def _marker_ms(match: re.Match) -> int | None:
    hours, minutes, seconds, fraction = match.groups()
    h, m, s = int(hours or 0), int(minutes), int(seconds)
    if s >= 60 or (hours is not None and m >= 60):
        return None
    return ((h * 60 + m) * 60 + s) * 1000 + (int(fraction.ljust(3, "0")) if fraction else 0)


def extract_inline_markers(text: str) -> list[tuple[int, int]]:
    """(char_offset, time_ms) for every well-formed marker, in text order.

    char_offset is the first non-space character after the marker, i.e. where the timed
    paragraph starts in `text`. Minutes and seconds must be below 60 when hours are given;
    seconds always below 60. Order is not checked here; see monotonic().
    """
    anchors: list[tuple[int, int]] = []
    length = len(text)
    for match in _MARKER.finditer(text):
        time_ms = _marker_ms(match)
        if time_ms is None:
            continue
        offset = match.end()
        while offset < length and text[offset].isspace():
            offset += 1
        anchors.append((offset, time_ms))
    return anchors


def monotonic(anchors: Iterable[Sequence]) -> list:
    """The longest subsequence whose offsets strictly increase and times never decrease.

    Items are (char_offset, time_ms, ...) tuples and come back unchanged. A single mistyped
    marker (e.g. "[59:00]" early in an episode) drops itself, not every marker after it.
    """
    items = sorted(anchors, key=lambda item: (item[0], item[1]))
    items = [item for i, item in enumerate(items) if i == 0 or item[0] != items[i - 1][0]]
    tails: list[int] = []  # tails[k]: index of the run of length k+1 with the smallest last time
    tail_times: list[int] = []
    previous = [-1] * len(items)
    for i, item in enumerate(items):
        k = bisect_left(tail_times, item[1] + 1)  # non-decreasing: equal times extend a run
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
    """All anchors of one build from its cues' (text, speaker), in document coordinates.

    A cue whose whole text is one marker and which has a speaker label ("Break", "Outro",
    "Jingle", ...) starts an untranscribed segment; see the module docstring. Every other
    marker is an inline_marker at the first character after it. Out-of-order publisher
    markers are dropped (monotonic) before segment ends are estimated.
    """
    found: list[tuple[int, int, str, int]] = []  # (offset, ms, source, segment end offset)
    base = 0
    for text, speaker in cues:
        whole = _MARKER.fullmatch(text.strip())
        if whole is not None and speaker:
            time_ms = _marker_ms(whole)
            if time_ms is not None:
                found.append((base + len(text) - len(text.lstrip()), time_ms, SOURCE_SEGMENT_START,
                              base + len(text)))
        else:
            found += [(base + offset, ms, SOURCE_INLINE_MARKER, 0) for offset, ms in extract_inline_markers(text)]
        base += len(text)
    kept = monotonic(found)
    rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(kept, kept[1:])
             if a[2] == SOURCE_INLINE_MARKER and b[0] - a[0] >= MIN_RATE_SPAN_CHARS]
    rate = _clamp_rate(median(rates)) if rates else DEFAULT_MS_PER_CHAR
    anchors = [Anchor(offset, ms, source) for offset, ms, source, _ in kept]
    for i, (offset, ms, source, end) in enumerate(kept):
        if source != SOURCE_SEGMENT_START or i + 1 == len(kept):
            continue
        next_offset, next_ms = kept[i + 1][0], kept[i + 1][1]
        if next_offset - end < MIN_SEGMENT_TEXT_CHARS:
            continue
        anchors.append(Anchor(end, max(ms, round(next_ms - (next_offset - end) * rate)), SOURCE_SEGMENT_END))
    return sorted(anchors)


def _global_rate(doc_length: int | None, duration_ms: int | None) -> float | None:
    if doc_length and duration_ms and doc_length > 0 and duration_ms > 0:
        return duration_ms / doc_length
    return None


def interpolate(
    anchors: Sequence[Sequence[int]], char_offset: int, *,
    doc_length: int | None, duration_ms: int | None,
) -> TimeEstimate:
    """Audio time of a document offset from (char_offset, time_ms, ...) anchors of the same build.

    Between two anchors: linear. Before the first or after the last: the nearest anchor plus
    the local rate (ms per character) of it and the nearest other anchor at least
    MIN_RATE_SPAN_CHARS away on the same side; else the global rate duration_ms / doc_length;
    else DEFAULT_MS_PER_CHAR; always clamped to [MIN_MS_PER_CHAR, MAX_MS_PER_CHAR]. No anchors:
    the global proportion char_offset / doc_length * duration_ms. Results are clamped to
    [0, duration_ms] when the duration is known. Pass anchors from load_anchors().
    """
    points = sorted((int(point[0]), int(point[1])) for point in anchors)
    offset = max(0, char_offset)
    if doc_length is not None and doc_length > 0:
        offset = min(offset, doc_length)

    def clamp(value: float) -> int:
        value = max(0.0, value)
        if duration_ms and duration_ms > 0:
            value = min(value, float(duration_ms))
        return round(value)

    if not points:
        rate = _global_rate(doc_length, duration_ms)
        if rate is None:
            return TimeEstimate(None, "none", None)
        return TimeEstimate(clamp(offset * rate), "proportional", duration_ms)
    offsets = [point[0] for point in points]
    i = bisect_left(offsets, offset)
    if i < len(points) and offsets[i] == offset:
        return TimeEstimate(clamp(points[i][1]), "anchored", 0)
    if 0 < i < len(points):
        (left_char, left_ms), (right_char, right_ms) = points[i - 1], points[i]
        share = (offset - left_char) / (right_char - left_char)
        return TimeEstimate(clamp(left_ms + share * (right_ms - left_ms)), "anchored", right_ms - left_ms)
    near_char, near_ms = points[0] if i == 0 else points[-1]
    side = points if i == 0 else points[::-1]
    other = next((p for p in side[1:] if abs(p[0] - near_char) >= MIN_RATE_SPAN_CHARS), None)
    if other is not None:
        rate = abs(other[1] - near_ms) / abs(other[0] - near_char)
    else:
        rate = _global_rate(doc_length, duration_ms) or DEFAULT_MS_PER_CHAR
    estimate = clamp(near_ms + (offset - near_char) * _clamp_rate(rate))
    return TimeEstimate(estimate, "extrapolated", abs(estimate - near_ms))


def _span(span: Mapping | Sequence) -> tuple[int, int, int]:
    if isinstance(span, Mapping):
        return int(span["cue_index"]), int(span["start_char"]), int(span["end_char"])
    cue_index, start, end = span
    return int(cue_index), int(start), int(end)


def chunk_to_document_offset(
    spans: Sequence[Mapping | Sequence], cue_starts: Mapping[int, int] | Sequence[int], chunk_char: int,
) -> int:
    """Map an offset in chunk text (e.g. SourceCitation.quote_start_char) to a document offset.

    spans: the chunk's corpus_chunks.spans in order ({"cue_index", "start_char", "end_char"}
    dicts or (cue_index, start_char, end_char) tuples); the chunk text is their cue slices
    joined by single spaces (corpus/chunking.py). cue_starts[cue_index]: the document offset of
    that cue, i.e. the summed text length of all earlier cues of the build. An offset on a
    joining space maps to the end of the slice before it (right for exclusive end offsets such
    as quote_end_char); offsets past the end clamp to the end of the last slice.
    """
    if not spans:
        raise ValueError("A chunk has at least one span.")
    position, chunk_char, last = 0, max(0, chunk_char), None
    for span in spans:
        cue_index, start, end = _span(span)
        width = end - start
        if chunk_char <= position + width:
            return cue_starts[cue_index] + start + max(0, chunk_char - position)
        position += width + 1  # the joining space
        last = (cue_index, end)
    return cue_starts[last[0]] + last[1]


# ------------------------------------------------------------------ the database
def replace_document_anchors(
    conn: psycopg.Connection, document_id: UUID, build_id: UUID, anchors: Sequence[Anchor],
) -> int:
    """Make the document's anchors from this module's sources exactly `anchors` (build_id's coordinates).

    One transaction: rows of these sources, and rows of any source from another build (stale
    coordinates), are deleted, then the new rows inserted. Returns rows written.
    """
    rows = [(document_id, int(a.char_offset), int(a.time_ms), a.source, build_id) for a in anchors]
    try:
        with conn.transaction(), conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM public.transcript_time_anchors WHERE document_id = %s "
                "AND (source = ANY(%s) OR build_id <> %s)",
                (document_id, list(SOURCES), build_id),
            )
            if rows:
                cursor.executemany(
                    "INSERT INTO public.transcript_time_anchors "
                    "(document_id, char_offset, time_ms, source, build_id) VALUES (%s, %s, %s, %s, %s)",
                    rows,
                )
    except psycopg.Error:
        raise CorpusStorageError("Could not save transcript time anchors.") from None
    return len(rows)


def load_anchors(conn: psycopg.Connection, build_ids: Sequence[UUID]) -> dict[UUID, list[tuple[int, int]]]:
    """build_id -> monotonic (char_offset, time_ms) anchors in that build's document coordinates.

    Builds without anchors are absent; pass the value (or []) to interpolate().
    """
    ids = list(dict.fromkeys(build_ids))
    if len(ids) > MAX_LOAD or any(not isinstance(value, UUID) for value in ids):
        raise ValueError(f"build_ids must contain at most {MAX_LOAD} UUIDs.")
    if not ids:
        return {}
    try:
        rows = conn.execute(
            "SELECT build_id, char_offset, time_ms FROM public.transcript_time_anchors "
            "WHERE build_id = ANY(%s::uuid[]) ORDER BY build_id, char_offset",
            (ids,),
        ).fetchall()
    except psycopg.Error:
        raise CorpusStorageError("Could not read transcript time anchors.") from None
    grouped: dict[UUID, list[tuple[int, int]]] = {}
    for build_id, char, ms in rows:
        grouped.setdefault(build_id, []).append((int(char), int(ms)))
    return {build_id: monotonic(points) for build_id, points in grouped.items()}
