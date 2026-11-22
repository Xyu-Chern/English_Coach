"""Where a cited passage plays in the publisher's audio: speech recognition aligns its chunk (PR⑥ v2).

Few transcripts carry timing (SRT: 1 feed of 27), so a citation's audio offset is usually estimated from
its character position (translation_agent_demo/storage/episode_audio.py) and often plays the wrong minute.
This module finds the chunk in the audio itself, once per chunk, and keeps the result:

    align_chunk(source, decode, transcribe) -> Alignment | None
        decode the estimate's centre +-150 s of the remote enclosure (PyAV seeks there; only that part is
        fetched and nothing is written to disk), recognise its words with times (faster-whisper), match
        them to the chunk's own words (difflib) and give every chunk word a time. When the chunk is not
        (all) inside the window, it decodes once more on the side(s) that need it, then gives up (None).
    stored_alignment(source)  a chunk whose transcript has cue timing (SRT) needs no audio: method "stored".
    answer(row, quote)        GET /api/audio/alignment's ready answer: the quote's place from the saved
                              word times and the lines (cues) around it, about 30-40 s.

    AudioAlignments           the API's state for frontend/server.py: chunk_audio_alignment (migration 011)
                              as the cache, a background queue run by two threads (the server adds the
                              examples it has just shown, an asked-for chunk goes first) and the answers:
        ready        the saved alignment (method "asr" or "stored"), or, until one exists, lines timed from
                     the transcript's time markers (anchored_alignment: method "anchored", or "estimated"
                     outside the markers; "confidence"; the quote's span widened ~3 s on each side;
                     "refining": true while recognition runs, and the client keeps asking to replace them)
        pending      queued or running without markers; the client asks again every 1-2 s (about 40 s at most)
        unavailable  no alignment (none possible, failed in the last 10 minutes, or aligning is off):
                     the estimate when the database knows it, else nulls (the client keeps its own)

COACH_AUDIO_ALIGN=on|off: on is the local server's default and runs the recogniser (needs faster-whisper,
translation_agent_demo/requirements-local.txt, and the database); the Vercel function is off and only
reads the saved alignments the package put in corpus/alignments.json (frontend/vercel/package.py).
COACH_ALIGN_MODEL picks the faster-whisper model (default base.en; tiny is smaller and faster).

    python -m frontend.audio_align <chunk_id>... [--ids-file FILE] [--quote TEXT]
        align and save chunks now (for a snapshot), one JSON line each.
"""

import argparse
import importlib.util
import itertools
import json
import os
import queue
import re
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "translation_agent_demo/storage/migrations/011_chunk_audio_alignment.sql"
SNAPSHOT = ROOT / "corpus" / "alignments.json"  # in the Vercel bundle, beside passages.json
SETTING_CHOICES = ("on", "off")
DEFAULT_MODEL = "base.en"
SAMPLE_RATE = 16_000
REACH_MS = 150_000  # the first window: the estimate's centre +- this much, at least...
MARGIN_MS = 75_000  # ...and this much beyond the chunk's estimated ends
WIDEN_MS = 210_000  # the one retry decodes this much more on each side that needs it
EDGE_MS = 5_000  # a chunk guessed to start (end) this close to a window edge may lie beyond it
MIN_COVERAGE = 0.35  # the share of the chunk's words that must match recognised words
MS_PER_WORD = 350  # speech rate when there is nothing to measure it from
MAX_LINE_WORDS = 16
MIN_CLIP_MS, MAX_CLIP_MS = 30_000, 40_000
WORKERS = 2  # alignments running at once
MAX_JOBS = 24  # queued and running; more pre-alignments are dropped
FAILED_SECONDS = 600.0  # a failed chunk answers unavailable this long before it is tried again
DECODE_SECONDS = 45.0  # the most one window's fetch and decode may take
REMEMBERED = 512  # alignments and sources kept in memory

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+")
_BREAK = re.compile(r"[,;:—–]\s+")


# ------------------------------------------------------------------ words
def words_of(text: str) -> list[tuple[str, int, int]]:
    """(word, start char, end char) of each word: letters and digits, with inner apostrophes."""
    return [(m.group(), m.start(), m.end()) for m in _WORD.finditer(text)]


def word_key(word: str) -> str:
    """How a word compares: lower case, without apostrophes ("Don't" and "dont" match)."""
    return word.lower().replace("’", "").replace("'", "")


def heard_tokens(words: Iterable[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Recognised (word, start_ms, end_ms) as comparable tokens; a word with several parts ("five-way")
    shares its time evenly between them."""
    tokens = []
    for text, start, end in words:
        parts = [word_key(m.group()) for m in _WORD.finditer(text)]
        step = (end - start) / max(1, len(parts))
        tokens += [(part, round(start + k * step), round(start + (k + 1) * step)) for k, part in enumerate(parts)]
    return tokens


def match_words(chunk_keys: Sequence[str], heard_keys: Sequence[str]) -> list[tuple[int, int]]:
    """(chunk word, recognised token) pairs, in order: difflib's matching runs of 2+ words, kept from the
    longest outwards. A run of 4+ words always stays (an ad break may sit between two); a shorter one
    stays only where the words skipped on both sides are about as many, not a jump."""
    blocks = [b for b in SequenceMatcher(None, chunk_keys, heard_keys, autojunk=False).get_matching_blocks()
              if b.size >= 2]
    if not blocks:
        return []
    seed = max(range(len(blocks)), key=lambda k: blocks[k].size)

    def plausible(before, after) -> bool:
        gap_a, gap_b = after.a - before.a - before.size, after.b - before.b - before.size
        return min(before.size, after.size) >= 4 or abs(gap_a - gap_b) <= 12 + max(gap_a, gap_b) // 2

    kept = [blocks[seed]]
    for block in blocks[seed + 1:]:
        if plausible(kept[-1], block):
            kept.append(block)
    for block in reversed(blocks[:seed]):
        if plausible(block, kept[0]):
            kept.insert(0, block)
    return [(b.a + k, b.b + k) for b in kept for k in range(b.size)]


def word_times(count: int, pairs: Sequence[tuple[int, int]],
               heard: Sequence[tuple[str, int, int]]) -> list[tuple[int, int]]:
    """A (start_ms, end_ms) for each of `count` chunk words: matched words take the recognised times,
    words between two matches share the gap, words before the first (after the last) match continue
    at the measured speech rate. Times never go backwards."""
    times: list[tuple[float, float] | None] = [None] * count
    for i, j in pairs:
        times[i] = (heard[j][1], heard[j][2])
    anchors = [i for i in range(count) if times[i] is not None]
    first, last = anchors[0], anchors[-1]
    rate = (times[last][1] - times[first][0]) / (last - first + 1) if last > first else MS_PER_WORD
    rate = min(max(rate, 150.0), 800.0)
    for i in range(first - 1, -1, -1):
        times[i] = (max(0.0, times[i + 1][0] - rate), times[i + 1][0])
    for i in range(last + 1, count):
        times[i] = (times[i - 1][1], times[i - 1][1] + rate)
    for a, b in zip(anchors, anchors[1:]):
        if b > a + 1:
            low, high = times[a][1], max(times[a][1], times[b][0])
            step = (high - low) / (b - a - 1)
            for k in range(b - a - 1):
                times[a + 1 + k] = (low + k * step, low + (k + 1) * step)
    result, floor = [], 0.0
    for start, end in times:
        start = max(start, floor)
        end = max(end, start)
        result.append((round(start), round(end)))
        floor = start
    return result


# ------------------------------------------------------------------ lines
def line_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) chars of the lines shown with the audio: sentences, a long one split at the comma
    (or the word) nearest its middle until each has at most MAX_LINE_WORDS words."""
    bounds = [0, *(m.end() for m in _SENTENCE_END.finditer(text)), len(text)]
    spans: list[tuple[int, int]] = []
    for a, b in zip(bounds, bounds[1:]):
        spans += _split(text, *_trim(text, a, b))
    return [(a, b) for a, b in spans if a < b]


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


def _split(text: str, a: int, b: int) -> list[tuple[int, int]]:
    words = list(_WORD.finditer(text, a, b))
    if len(words) <= MAX_LINE_WORDS:
        return [(a, b)]
    middle = words[len(words) // 2].start()
    low, high = words[len(words) // 4].start(), words[3 * len(words) // 4].start()
    breaks = [m.end() for m in _BREAK.finditer(text, a, b) if low <= m.end() <= high]
    cut = min(breaks, key=lambda p: abs(p - middle)) if breaks else middle
    return _split(text, *_trim(text, a, cut)) + _split(text, *_trim(text, cut, b))


def cue_lines(text: str, tokens: Sequence[tuple[str, int, int]], times: Sequence[tuple[int, int]]) -> list[dict]:
    """The chunk's lines with the times of their first and last words."""
    cues, k = [], 0
    for start, end in line_spans(text):
        while k < len(tokens) and tokens[k][1] < start:
            k += 1
        inside = []
        while k < len(tokens) and tokens[k][1] < end:
            inside.append(k)
            k += 1
        if inside:
            cues.append({"text": text[start:end], "start_ms": times[inside[0]][0], "end_ms": times[inside[-1]][1]})
    return cues


# ------------------------------------------------------------------ one chunk
@dataclass(frozen=True)
class ChunkSource:
    """What aligning a chunk needs. estimate: (start_ms, end_ms) from the character position, without the
    early start; spans: (start_char, end_char, cue_start_ms, cue_end_ms, cue_length) per transcript cue the
    chunk text is made of (its slices, joined with spaces); clip: the citation's estimated audio fields."""

    chunk_id: UUID
    text: str
    audio_url: str
    duration_ms: int | None
    estimate: tuple[int, int] | None
    spans: tuple[tuple, ...] = ()
    clip: tuple[int | None, int | None] = (None, None)
    # The transcript's time markers (time_anchors.load_anchors, the chunk's build) and what maps chunk
    # characters to their document offsets: (cue_index, start_char, end_char, cue's document offset) per span.
    anchors: tuple[tuple[int, int], ...] = ()
    doc_spans: tuple[tuple[int, int, int, int], ...] = ()
    char_total: int | None = None


@dataclass(frozen=True)
class Alignment:
    chunk_id: UUID
    audio_url: str
    window_start_ms: int
    words: tuple[dict, ...]  # {"w", "s", "e"}: the chunk's words in order, ms
    cues: tuple[dict, ...]  # {"text", "start_ms", "end_ms"}
    method: str  # "asr" | "stored"
    model: str | None = None
    coverage: float | None = None  # matched share of the chunk's words (asr), not saved

    def row(self) -> dict:
        return {"audio_url": self.audio_url, "window_start_ms": self.window_start_ms, "words": list(self.words),
                "cues": list(self.cues), "method": self.method, "model": self.model}


def first_window(source: ChunkSource) -> tuple[int, int]:
    start, end = source.estimate
    centre, reach = (start + end) // 2, max(REACH_MS, (end - start) // 2 + MARGIN_MS)
    high = centre + reach if source.duration_ms is None else min(source.duration_ms, centre + reach)
    return max(0, centre - reach), max(high, 1)


def _sides(count: int, pairs, heard, window: tuple[int, int], duration_ms: int | None) -> tuple[bool, bool]:
    """Whether to decode more before / after the window: the chunk was not found well enough, or it is
    guessed (at MS_PER_WORD for the words beyond the matches) to reach past that edge."""
    low, high = window
    can_left, can_right = low > 0, duration_ms is None or high < duration_ms
    if len(pairs) < MIN_COVERAGE * count:
        return can_left, can_right
    (i0, j0), (i1, j1) = pairs[0], pairs[-1]
    starts_before = heard[j0][1] - i0 * MS_PER_WORD < low + EDGE_MS
    ends_after = heard[j1][2] + (count - 1 - i1) * MS_PER_WORD > high - EDGE_MS
    return can_left and starts_before, can_right and ends_after


def align_chunk(source: ChunkSource, decode, transcribe, *, model: str | None = None) -> Alignment | None:
    """The chunk's words and lines with times from speech recognition, or None when it was not found.

    decode(url, start_ms, end_ms) -> (16 kHz mono float32 samples, start_ms of the first sample);
    transcribe(samples) -> [(word, start_ms, end_ms)] relative to the samples."""
    tokens = words_of(source.text)
    if not tokens or source.estimate is None:
        return None
    keys = [word_key(t[0]) for t in tokens]

    def hear(low: int, high: int) -> list[tuple[str, int, int]]:
        samples, offset = decode(source.audio_url, low, high)
        return [(w, s + offset, e + offset) for w, s, e in heard_tokens(transcribe(samples))] if len(samples) else []

    low, high = first_window(source)
    heard = hear(low, high)
    pairs = match_words(keys, [h[0] for h in heard])
    left, right = _sides(len(keys), pairs, heard, (low, high), source.duration_ms)
    if left or right:
        extra = []
        if left:
            extra += hear(max(0, low - WIDEN_MS), low)
            low = max(0, low - WIDEN_MS)
        if right:
            wider = high + WIDEN_MS if source.duration_ms is None else min(source.duration_ms, high + WIDEN_MS)
            extra += hear(high, wider)
            high = wider
        heard = sorted(heard + extra, key=lambda h: h[1])
        pairs = match_words(keys, [h[0] for h in heard])
    coverage = len(pairs) / len(keys)
    if not pairs or coverage < MIN_COVERAGE:
        return None
    times = word_times(len(keys), pairs, heard)
    words = tuple({"w": t[0], "s": s, "e": e} for t, (s, e) in zip(tokens, times))
    return Alignment(source.chunk_id, source.audio_url, low, words, tuple(cue_lines(source.text, tokens, times)),
                     "asr", model, round(coverage, 3))


def stored_alignment(source: ChunkSource) -> Alignment | None:
    """From the transcript's own cue timing when every cue of the chunk has it: a word's time is its
    character position inside its cue's time. None otherwise."""
    spans = source.spans
    if not spans or any(not isinstance(s[2], int) or not isinstance(s[3], int) or not s[4] for s in spans):
        return None
    tokens = words_of(source.text)
    if not tokens:
        return None
    pieces, offset = [], 0  # (chunk char where the slice starts, start_char, end_char, cue start, cue end, length)
    for start_char, end_char, cue_start, cue_end, length in spans:
        pieces.append((offset, start_char, cue_start, max(cue_start, cue_end), length))
        offset += end_char - start_char + 1

    def at(char: int) -> int:
        piece = next((p for p in reversed(pieces) if p[0] <= char), pieces[0])
        within = piece[1] + char - piece[0]
        return round(piece[2] + (piece[3] - piece[2]) * min(max(within / piece[4], 0.0), 1.0))

    times = word_times(len(tokens), [(i, i) for i in range(len(tokens))],
                       [(t[0], at(t[1]), at(t[2])) for t in tokens])
    words = tuple({"w": t[0], "s": s, "e": e} for t, (s, e) in zip(tokens, times))
    return Alignment(source.chunk_id, source.audio_url, times[0][0], words,
                     tuple(cue_lines(source.text, tokens, times)), "stored")


def anchored_alignment(source: ChunkSource) -> tuple[Alignment, str] | None:
    """Without audio or recognition: every chunk word's time interpolated between the publisher's time
    markers (time_anchors.interpolate), and the confidence ("anchored" when the whole chunk lies between
    markers, else "extrapolated"). Method "anchored" or "estimated"; never saved. None without markers."""
    from translation_agent_demo.storage.time_anchors import chunk_to_document_offset, interpolate

    if not source.anchors or not source.doc_spans:
        return None
    tokens = words_of(source.text)
    if not tokens:
        return None
    spans = [(k, a, b) for k, a, b, _ in source.doc_spans]
    starts = {k: start for k, _, _, start in source.doc_spans}

    def at(char: int):
        return interpolate(source.anchors, chunk_to_document_offset(spans, starts, char),
                           doc_length=source.char_total, duration_ms=source.duration_ms)

    marks = [(at(t[1]), at(t[2])) for t in tokens]
    if any(s.time_ms is None or e.time_ms is None for s, e in marks):
        return None
    confidence = "anchored" if all(s.confidence == e.confidence == "anchored" for s, e in marks) else "extrapolated"
    times = word_times(len(tokens), [(i, i) for i in range(len(tokens))],
                       [(t[0], s.time_ms, e.time_ms) for t, (s, e) in zip(tokens, marks)])
    words = tuple({"w": t[0], "s": s, "e": e} for t, (s, e) in zip(tokens, times))
    method = "anchored" if confidence == "anchored" else "estimated"
    return Alignment(source.chunk_id, source.audio_url, times[0][0], words,
                     tuple(cue_lines(source.text, tokens, times)), method), confidence


# ------------------------------------------------------------------ the quote
def quote_span(words: Sequence[dict], quote: str) -> tuple[int, int] | None:
    """First and last word index of the quote among the chunk's words: the exact words, else the most
    similar run of as many words (at least 60% alike)."""
    wanted = [word_key(w) for w, _, _ in words_of(quote)]
    keys = [word_key(w["w"]) for w in words]
    n = len(wanted)
    if not n or not keys:
        return None
    for i in range(len(keys) - n + 1):
        if keys[i:i + n] == wanted:
            return i, i + n - 1
    best, where = 0.0, 0
    for i in range(max(1, len(keys) - n + 1)):
        ratio = SequenceMatcher(None, wanted, keys[i:i + n], autojunk=False).ratio()
        if ratio > best:
            best, where = ratio, i
    return (where, min(len(keys), where + n) - 1) if best >= 0.6 else None


def clip_cues(cues: Sequence[dict], start: int, end: int) -> list[dict]:
    """The lines from start to end, then one more before, one after, ... while the clip is under
    MIN_CLIP_MS and stays within MAX_CLIP_MS (the quote's own lines always stay)."""
    inside = [k for k, c in enumerate(cues) if c["end_ms"] > start and c["start_ms"] < end]
    if not inside:
        inside = [min(range(len(cues)), key=lambda k: abs(cues[k]["start_ms"] - start))]
    a, b = inside[0], inside[-1]

    def span(a: int, b: int) -> int:
        return cues[b]["end_ms"] - cues[a]["start_ms"]

    turn = 0
    while span(a, b) < MIN_CLIP_MS:
        options = [o for o in ((a - 1, b) if a > 0 else None, (a, b + 1) if b < len(cues) - 1 else None)
                   if o is not None and span(*o) <= MAX_CLIP_MS]
        if not options:
            break
        a, b = options[turn % len(options)]
        turn += 1
    return [dict(c) for c in cues[a:b + 1]]


def answer(row: dict, quote: str) -> dict:
    """A ready answer from a saved alignment row."""
    words, cues = row["words"], row["cues"]
    span = quote_span(words, quote)
    if span:
        quote_start, quote_end = words[span[0]]["s"], words[span[1]]["e"]
        lines = clip_cues(cues, quote_start, quote_end)
    else:
        quote_start = quote_end = None
        lines = clip_cues(cues, cues[0]["start_ms"], cues[0]["end_ms"])
    clip_start = min(lines[0]["start_ms"], quote_start if quote_start is not None else lines[0]["start_ms"])
    clip_end = max(lines[-1]["end_ms"], quote_end if quote_end is not None else lines[-1]["end_ms"])
    return {"status": "ready", "method": row["method"], "audio_url": row["audio_url"], "clip_start_ms": clip_start,
            "clip_end_ms": clip_end, "quote_start_ms": quote_start, "quote_end_ms": quote_end, "cues": lines}


def rough_answer(source: ChunkSource, quote: str, *, refining: bool) -> dict | None:
    """A ready answer timed from the transcript's markers (anchored_alignment), or None without them.
    The quote's span starts ROUGH_LEAD_MS early and ends ROUGH_TAIL_MS late (marker error: median 3.3 s),
    so the player's default loop (the quote) still holds the whole quote. "confidence": "anchored" (between
    markers) or "extrapolated"; "refining": recognition is running and may replace the answer."""
    from translation_agent_demo.storage.episode_audio import ANCHORED_LEAD_IN_MS, ANCHORED_TAIL_MS

    rough = anchored_alignment(source)
    if rough is None:
        return None
    alignment, confidence = rough
    body = answer(alignment.row(), quote)
    if body["quote_start_ms"] is not None:
        start = max(0, body["quote_start_ms"] - ANCHORED_LEAD_IN_MS)
        end = body["quote_end_ms"] + ANCHORED_TAIL_MS
        end = min(end, source.duration_ms) if source.duration_ms else end
        body.update(quote_start_ms=start, quote_end_ms=max(start, end), clip_start_ms=min(body["clip_start_ms"], start),
                    clip_end_ms=max(body["clip_end_ms"], end))
    return {**body, "confidence": confidence, "refining": refining}


def not_ready(status: str, source: ChunkSource | None) -> dict:
    """pending or unavailable: the estimate when it is known (method "estimated"), else nulls."""
    start, end = source.clip if source else (None, None)
    return {"status": status, "method": "estimated", "audio_url": source.audio_url if source else None,
            "clip_start_ms": start, "clip_end_ms": end, "quote_start_ms": None, "quote_end_ms": None, "cues": []}


# ------------------------------------------------------------------ audio and speech
def decode_window(url: str, start_ms: int, end_ms: int, *, seconds: float = DECODE_SECONDS):
    """16 kHz mono float32 samples of the remote audio from start_ms to end_ms, and where they start.
    PyAV (FFmpeg) seeks by time, so only about that part of the file is fetched; nothing is written."""
    import av
    import numpy as np

    deadline, pieces, first = time.monotonic() + seconds, [], None
    with av.open(url, timeout=(10.0, 15.0), options={"protocol_whitelist": "http,https,tcp,tls"}) as container:
        stream = container.streams.audio[0]
        if start_ms > 0:
            container.seek(start_ms * 1000, backward=True, any_frame=False)  # AV_TIME_BASE: microseconds
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            if frame.time * 1000 >= end_ms:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("decoding the audio window took too long")
            first = frame.time if first is None else first
            pieces += [p.to_ndarray().reshape(-1) for p in resampler.resample(frame)]
        pieces += [p.to_ndarray().reshape(-1) for p in resampler.resample(None)]
    if first is None or not pieces:
        return np.zeros(0, dtype=np.float32), start_ms
    return np.concatenate(pieces).astype(np.float32) / 32768.0, max(0, round(first * 1000))


class WhisperTranscriber:
    """faster-whisper on the CPU (int8), loaded on first use; COACH_ALIGN_MODEL names the model."""

    def __init__(self, model: str | None = None, *, threads: int = 3, workers: int = WORKERS):
        self.name = model or os.environ.get("COACH_ALIGN_MODEL", "").strip() or DEFAULT_MODEL
        self.threads, self.workers = threads, workers
        self._model, self._lock = None, threading.Lock()

    def model(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.name, device="cpu", compute_type="int8",
                                           cpu_threads=self.threads, num_workers=self.workers)
            return self._model

    def __call__(self, samples) -> list[tuple[str, int, int]]:
        import numpy as np

        with np.errstate(all="ignore"):  # NumPy's matmul on macOS warns spuriously in the feature extractor
            segments, _ = self.model().transcribe(samples, language="en", beam_size=1, word_timestamps=True,
                                                  condition_on_previous_text=False)
            return [(w.word, round(w.start * 1000), round(w.end * 1000))
                    for segment in segments for w in (segment.words or ())]


def can_align() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("faster_whisper", "av", "numpy"))


# ------------------------------------------------------------------ the database
_APPROVED = """
    JOIN public.corpus_builds AS b USING (build_id)
    JOIN public.podcast_transcripts AS d USING (document_id)
    JOIN public.podcast_sources AS s USING (source_key)
    JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
"""
_APPROVED_WHERE = """
    AND b.status = 'ready' AND s.rights_status = 'approved' AND r.status = 'approved'
    AND public.transcript_url_matches_review_scope(d.download_url, r.transcript_url_prefix)
"""
_SOURCE_SQL = f"""
    SELECT c.text, c.start_ms, c.end_ms, a.enclosure_url, a.duration_s, pos.char_start, pos.char_end,
           pos.char_total, cue.timing, c.build_id, cue.doc_spans
    FROM public.corpus_chunks AS c {_APPROVED}
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
    CROSS JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_array((sp ->> 'start_char')::int, (sp ->> 'end_char')::int,
                   b.cues -> ((sp ->> 'cue_index')::int) -> 'start_ms',
                   b.cues -> ((sp ->> 'cue_index')::int) -> 'end_ms',
                   length(b.cues -> ((sp ->> 'cue_index')::int) ->> 'text')) ORDER BY t.n) AS timing,
               jsonb_agg(jsonb_build_array((sp ->> 'cue_index')::int, (sp ->> 'start_char')::int,
                   (sp ->> 'end_char')::int,
                   (SELECT coalesce(sum(length(q.value ->> 'text')), 0)
                    FROM jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)
                    WHERE q.n - 1 < (sp ->> 'cue_index')::int)) ORDER BY t.n) AS doc_spans
        FROM jsonb_array_elements(c.spans) WITH ORDINALITY AS t(sp, n)
    ) AS cue
    WHERE c.chunk_id = %s AND s.source_key LIKE 'podcast_index:%%' {_APPROVED_WHERE}
"""
_ROW_SQL = f"""
    SELECT al.audio_url, al.window_start_ms, al.words, al.cues, al.method, al.model
    FROM public.chunk_audio_alignment AS al
    JOIN public.corpus_chunks AS c USING (chunk_id) {_APPROVED}
    WHERE al.chunk_id = %s {_APPROVED_WHERE}
"""


def load_source(conn, chunk_id: UUID) -> ChunkSource | None:
    """An approved chunk with publisher audio, or None."""
    from translation_agent_demo.storage.episode_audio import anchors_for_builds, estimate_clip
    from translation_agent_demo.storage.retrieval import _display_url
    from translation_agent_demo.storage.time_anchors import interpolate

    row = conn.execute(_SOURCE_SQL, (chunk_id,)).fetchone()
    if row is None:
        return None
    text, start_ms, end_ms, url, duration_s, char_start, char_end, char_total, timing, build_id, doc_spans = row
    url = _display_url(url)
    if url is None:
        return None
    anchors = tuple(anchors_for_builds(conn, [build_id]).get(build_id, ())) if start_ms is None else ()
    duration_ms = duration_s * 1000 if duration_s else None
    clip = estimate_clip(url, start_ms=start_ms, end_ms=end_ms, char_start=char_start, char_end=char_end,
                         char_total=char_total, duration_s=duration_s, anchors=anchors)
    estimate = None
    if start_ms is not None and end_ms is not None:
        estimate = (int(start_ms), int(end_ms))
    elif anchors:  # the asr window centres on the markers' estimate
        first, last = (interpolate(anchors, char, doc_length=char_total, duration_ms=duration_ms).time_ms
                       for char in (char_start, char_end))
        estimate = (first, max(first, last)) if first is not None and last is not None else None
    elif clip.audio_start_ms is not None and duration_s and char_total:
        estimate = (round(char_start / char_total * duration_s * 1000), round(char_end / char_total * duration_s * 1000))
    spans = tuple(tuple(span) for span in timing or ())
    return ChunkSource(chunk_id, text, url, duration_ms, estimate, spans,
                       (clip.audio_start_ms, clip.audio_end_ms), anchors,
                       tuple(tuple(int(v) for v in span) for span in doc_spans or ()), char_total)


def read_row(conn, chunk_id: UUID) -> dict | None:
    row = conn.execute(_ROW_SQL, (chunk_id,)).fetchone()
    if row is None:
        return None
    url, window_start_ms, words, cues, method, model = row
    return {"audio_url": url, "window_start_ms": window_start_ms, "words": words, "cues": cues,
            "method": method, "model": model}


def save_alignment(conn, alignment: Alignment) -> None:
    from psycopg.types.json import Jsonb

    with conn.transaction():
        conn.execute(
            """INSERT INTO public.chunk_audio_alignment
                   (chunk_id, audio_url, window_start_ms, words, cues, method, model)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (chunk_id) DO UPDATE SET audio_url = EXCLUDED.audio_url,
                   window_start_ms = EXCLUDED.window_start_ms, words = EXCLUDED.words, cues = EXCLUDED.cues,
                   method = EXCLUDED.method, model = EXCLUDED.model, created_at = now()""",
            (alignment.chunk_id, alignment.audio_url, alignment.window_start_ms, Jsonb(list(alignment.words)),
             Jsonb(list(alignment.cues)), alignment.method, alignment.model))


def ensure_table(conn) -> None:
    conn.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)


# ------------------------------------------------------------------ the service
class _Memory(OrderedDict):
    """A small least-recently-used map."""

    def remember(self, key, value) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > REMEMBERED:
            self.popitem(last=False)


class AudioAlignments:
    """GET /api/audio/alignment's answers and the background alignment queue (frontend/server.py).

    database: PostgresSettings for the cache table and the chunk sources (None: no database);
    align: run the recogniser (needs the database); snapshot: a JSON file {"alignments": {chunk_id: row}}
    read when there is no database (the Vercel bundle). Nothing connects or starts before the first use."""

    def __init__(self, *, database=None, align: bool = False, snapshot: Path | None = None,
                 transcriber: Callable | None = None, decode: Callable = decode_window,
                 workers: int = WORKERS, clock: Callable[[], float] = time.monotonic, log=None):
        self.database, self.snapshot, self.clock = database, snapshot, clock
        self.aligning = bool(align and database is not None)
        self.decode, self.workers = decode, workers
        self.transcriber = transcriber if transcriber is not None else (WhisperTranscriber() if self.aligning else None)
        self.log = log or (lambda line: print(line, flush=True))
        self._lock = threading.Lock()
        self._rows, self._sources = _Memory(), _Memory()
        self._state: dict[UUID, object] = {}  # "queued" | "running" | when it failed (clock)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._order = itertools.count()
        self._threads: list[threading.Thread] = []
        self._ensured, self._ensure_lock = False, threading.Lock()
        self._saved: dict[str, dict] | None = None

    @classmethod
    def from_environment(cls, *, local: bool, environ=None, database=None, log=None) -> "AudioAlignments":
        """COACH_AUDIO_ALIGN (default on for the local server, off otherwise; any other value stops the start).
        The local server reads the database's settings; aligning also needs faster-whisper installed."""
        environ = os.environ if environ is None else environ
        raw = environ.get("COACH_AUDIO_ALIGN")
        setting = (raw or "").strip().lower() or ("on" if local else "off")
        if setting not in SETTING_CHOICES:
            raise ValueError(f"COACH_AUDIO_ALIGN must be on or off; got {raw!r}.")
        if local and database is None:
            from translation_agent_demo.storage.postgres import CorpusStorageError, PostgresSettings
            try:
                database = PostgresSettings.from_environment()
            except CorpusStorageError:
                database = None
        return cls(database=database, align=setting == "on" and can_align(), log=log,
                   snapshot=None if local else SNAPSHOT)

    def describe(self) -> str:
        if self.aligning:
            return f"on (speech recognition, model {self.transcriber.name}; saved in chunk_audio_alignment)"
        if self.database is not None:
            return "saved alignments only (COACH_AUDIO_ALIGN=off or faster-whisper missing)"
        return "snapshot alignments only" if self.snapshot else "off"

    # ------------------------------------------------------- answers
    def lookup(self, chunk_id: UUID, quote: str) -> dict:
        row = self._row(chunk_id)
        if row is not None:
            return answer(row, quote)
        source = self._source(chunk_id)
        status = "unavailable"
        if self.aligning and source is not None:
            with self._lock:
                state = self._state.get(chunk_id)
                failed = isinstance(state, float) and self.clock() - state < FAILED_SECONDS
            if not failed and (state == "running"
                               or self._submit(chunk_id, priority=0, limit=MAX_JOBS + WORKERS * 4)):
                status = "pending"
        # Lines timed from the transcript's markers play at once; "refining": recognition may replace them.
        rough = rough_answer(source, quote, refining=status == "pending") if source is not None else None
        return rough if rough is not None else not_ready(status, source)

    def prefetch(self, chunk_ids: Iterable[UUID]) -> None:
        """Start aligning chunks the learner has just been shown, behind any asked-for chunk."""
        if not self.aligning:
            return
        for chunk_id in dict.fromkeys(chunk_ids):
            if chunk_id not in self._rows:
                self._submit(chunk_id, priority=1, limit=MAX_JOBS)

    # ------------------------------------------------------- the queue
    def _submit(self, chunk_id: UUID, *, priority: int, limit: int) -> bool:
        with self._lock:
            state = self._state.get(chunk_id)
            if state == "running" or (isinstance(state, float) and self.clock() - state < FAILED_SECONDS):
                return False
            busy = sum(1 for value in self._state.values() if value in ("queued", "running"))
            if state != "queued" and busy >= limit:
                return False
            self._state[chunk_id] = "queued"
            self._queue.put((priority, next(self._order), chunk_id))  # a repeat raises its priority
            while len(self._threads) < self.workers:
                thread = threading.Thread(target=self._work, name="audio-align", daemon=True)
                self._threads.append(thread)
                thread.start()
        return True

    def _work(self) -> None:
        while True:
            _, _, chunk_id = self._queue.get()
            with self._lock:
                if self._state.get(chunk_id) != "queued":
                    continue
                self._state[chunk_id] = "running"
            started, row, detail = self.clock(), None, {}
            try:
                row, detail = self._align(chunk_id)
            except Exception as exc:  # one chunk's failure never stops the queue
                detail = {"error": type(exc).__name__}
            with self._lock:
                if row is not None:
                    self._rows.remember(chunk_id, row)
                    self._state.pop(chunk_id, None)
                else:
                    self._state[chunk_id] = self.clock()
            self.log(json.dumps({"event": "audio_alignment", "chunk_id": str(chunk_id),
                                 "status": "ready" if row else "failed", **detail,
                                 "ms": round((self.clock() - started) * 1000)}))

    def _align(self, chunk_id: UUID) -> tuple[dict | None, dict]:
        from translation_agent_demo.storage.postgres import connect_database

        saved = self._read(lambda conn: read_row(conn, chunk_id))  # aligned by another process meanwhile
        if saved is not None:
            return saved, {"method": saved["method"], "saved": True}
        source = self._source(chunk_id, fresh=True)
        if source is None:
            return None, {"error": "no_source"}
        alignment = stored_alignment(source) or align_chunk(source, self.decode, self.transcriber,
                                                           model=getattr(self.transcriber, "name", None))
        if alignment is None:
            return None, {"error": "not_found"}
        with connect_database(self.database) as conn:
            self._ensure(conn)
            save_alignment(conn, alignment)
        return alignment.row(), {"method": alignment.method, "coverage": alignment.coverage}

    # ------------------------------------------------------- reading
    def _ensure(self, conn) -> None:
        with self._ensure_lock:
            if not self._ensured:
                ensure_table(conn)
                self._ensured = True

    def _row(self, chunk_id: UUID) -> dict | None:
        with self._lock:
            if chunk_id in self._rows:
                return self._rows[chunk_id]
        row = None
        if self.database is not None:
            row = self._read(lambda conn: read_row(conn, chunk_id))
        elif self.snapshot is not None:
            row = self._snapshot().get(str(chunk_id))
        if row is not None:
            with self._lock:
                self._rows.remember(chunk_id, row)
        return row

    def _source(self, chunk_id: UUID, *, fresh: bool = False) -> ChunkSource | None:
        if self.database is None:
            return None
        with self._lock:
            if not fresh and chunk_id in self._sources:
                return self._sources[chunk_id]
        source = self._read(lambda conn: load_source(conn, chunk_id))
        with self._lock:
            self._sources.remember(chunk_id, source)
        return source

    def _read(self, query):
        """One query on a fresh connection; None when the database (or the table) is not there."""
        import psycopg
        from translation_agent_demo.storage.postgres import CorpusStorageError, connect_database

        try:
            with connect_database(self.database) as conn:
                try:
                    return query(conn)
                except psycopg.errors.UndefinedTable:
                    if self._ensured:
                        return None
                    self._ensure(conn)
                    return query(conn)
        except (CorpusStorageError, psycopg.Error, OSError):
            return None

    def _snapshot(self) -> dict:
        if self._saved is None:
            try:
                payload = json.loads(self.snapshot.read_text(encoding="utf-8"))
                saved = payload.get("alignments") if isinstance(payload, dict) else None
                self._saved = saved if isinstance(saved, dict) else {}
            except (OSError, ValueError):
                self._saved = {}
        return self._saved


# ------------------------------------------------------------------ precompute
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m frontend.audio_align", description=__doc__.split("\n\n")[0])
    parser.add_argument("chunk_ids", nargs="*", type=UUID)
    parser.add_argument("--ids-file", type=Path, help="one chunk id per line")
    parser.add_argument("--quote", help="also answer GET /api/audio/alignment for this quote (one chunk)")
    parser.add_argument("--model", help=f"faster-whisper model (default COACH_ALIGN_MODEL, else {DEFAULT_MODEL})")
    args = parser.parse_args(argv)
    ids = list(args.chunk_ids)
    if args.ids_file:
        ids += [UUID(line.strip()) for line in args.ids_file.read_text().splitlines() if line.strip()]
    if not ids:
        parser.error("give chunk ids")
    if not can_align():
        parser.error("install faster-whisper (translation_agent_demo/requirements-local.txt)")
    from translation_agent_demo.storage.postgres import PostgresSettings, connect_database

    database = PostgresSettings.from_environment()
    transcriber = WhisperTranscriber(args.model, threads=6, workers=1)
    with connect_database(database) as conn:
        ensure_table(conn)
    failed = 0
    for chunk_id in dict.fromkeys(ids):
        started = time.monotonic()
        with connect_database(database) as conn:
            source = load_source(conn, chunk_id)
        alignment = None
        if source is not None:
            alignment = stored_alignment(source) or align_chunk(source, decode_window, transcriber,
                                                               model=transcriber.name)
        if alignment is not None:
            with connect_database(database) as conn:
                save_alignment(conn, alignment)
        failed += alignment is None
        line = {"chunk_id": str(chunk_id), "status": "ready" if alignment else "failed",
                "method": alignment and alignment.method, "coverage": alignment and alignment.coverage,
                "ms": round((time.monotonic() - started) * 1000)}
        if alignment is not None and args.quote:
            line["answer"] = answer(alignment.row(), args.quote)
        print(json.dumps(line, ensure_ascii=False), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
