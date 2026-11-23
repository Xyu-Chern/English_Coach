"""Pack adjacent source sentences into token-bounded chunks without rewriting.

Sentence punctuation is a boundary hint, not linguistic analysis. A long sentence
falls back to word boundaries, then Unicode character boundaries if necessary.
Only whole trailing units are reused for overlap; overlap is an upper bound.
"""

import re
from dataclasses import dataclass

import tiktoken

from .models import CorpusChunk, Cue, CueSpan, ParsedTranscript
from .parsers import PARSER_VERSION

CHUNKER_VERSION = "sentences-v1"
ENCODING_NAME = "cl100k_base"
_SENTENCE = re.compile(r".+?(?:[.!?][\"'’”)]*(?=\s|$)|$)", re.DOTALL)


@dataclass(frozen=True)
class ChunkingSettings:
    max_tokens: int = 512
    overlap_tokens: int = 64

    def __post_init__(self) -> None:
        if type(self.max_tokens) is not int or not 128 <= self.max_tokens <= 2048:
            raise ValueError("max_tokens must be an integer between 128 and 2048.")
        if type(self.overlap_tokens) is not int or not 0 <= self.overlap_tokens < self.max_tokens // 2:
            raise ValueError("overlap_tokens must be nonnegative and less than half max_tokens.")

    @property
    def processing_version(self) -> str:
        # Any parser, tokenizer, boundary-rule or size change gets a separate build.
        return (
            f"{PARSER_VERSION}/{CHUNKER_VERSION}/{ENCODING_NAME}"
            f"@{tiktoken.__version__}/{self.max_tokens}/{self.overlap_tokens}"
        )


def _trim_span(cue: Cue, start: int, end: int) -> CueSpan | None:
    while start < end and cue.text[start].isspace():
        start += 1
    while end > start and cue.text[end - 1].isspace():
        end -= 1
    return CueSpan(cue.index, start, end) if start < end else None


def _coalesce(spans: list[CueSpan], cues: tuple[Cue, ...]) -> tuple[CueSpan, ...]:
    """Keep contiguous slices of one cue together, including split long words."""
    result: list[CueSpan] = []
    for span in spans:
        if result and result[-1].cue_index == span.cue_index:
            previous = result[-1]
            gap = cues[span.cue_index].text[previous.end_char:span.start_char]
            if previous.end_char <= span.start_char and (not gap or gap.isspace()):
                result[-1] = CueSpan(span.cue_index, previous.start_char, span.end_char)
                continue
        result.append(span)
    return tuple(result)


def _text(spans: list[CueSpan], cues: tuple[Cue, ...]) -> str:
    return " ".join(
        cues[span.cue_index].text[span.start_char:span.end_char]
        for span in _coalesce(spans, cues)
    )


def _bounded_parts(cue: Cue, span: CueSpan, encoding: tiktoken.Encoding, limit: int):
    start = span.start_char
    while start < span.end_char:
        # Bounded windows also avoid tokenizing a huge unbroken string at once.
        end = min(span.end_char, start + limit * 8)
        if len(encoding.encode_ordinary(cue.text[start:end])) > limit:
            low, high = start + 1, end
            best = start
            while low <= high:
                middle = (low + high) // 2
                if len(encoding.encode_ordinary(cue.text[start:middle])) <= limit:
                    best, low = middle, middle + 1
                else:
                    high = middle - 1
            end = best
        if end < span.end_char and not cue.text[end].isspace():
            # Prefer a whole word. A single oversized word still makes progress.
            boundary = next((i for i in range(end - 1, start, -1) if cue.text[i].isspace()), None)
            if boundary is not None:
                end = boundary
        part = _trim_span(cue, start, end)
        if part is not None:
            # Prefix token counts need not be monotone; check the final boundary.
            while len(encoding.encode_ordinary(cue.text[part.start_char:part.end_char])) > limit:
                part = CueSpan(cue.index, part.start_char, part.end_char - 1)
            yield part
            end = part.end_char
        start = end
        while start < span.end_char and cue.text[start].isspace():
            start += 1


def chunk_transcript(
    parsed: ParsedTranscript,
    settings: ChunkingSettings = ChunkingSettings(),
) -> tuple[CorpusChunk, ...]:
    """Return ordered chunks with exact cue-character provenance and token counts.

    ``cl100k_base`` matches the planned OpenAI embedding family. Token counting is
    local; this function never calls the OpenAI API. Literal special-token strings
    in publisher text are counted as ordinary text. Docker preloads tokenizer data.
    """
    if not parsed.cues or any(
        cue.index != index or not cue.text.strip() for index, cue in enumerate(parsed.cues)
    ):
        raise ValueError("Parsed cues must be nonempty and indexed in source order.")
    encoding = tiktoken.get_encoding(ENCODING_NAME)
    cues = parsed.cues
    chunks: list[CorpusChunk] = []
    current: list[CueSpan] = []

    def count(spans: list[CueSpan]) -> int:
        return len(encoding.encode_ordinary(_text(spans, cues)))

    def emit() -> None:
        spans = _coalesce(current, cues)
        text = _text(current, cues)
        selected = [cues[span.cue_index] for span in spans]
        # These are source-cue bounds, not interpolated timestamps for substrings.
        start = min(cue.start_ms for cue in selected) if all(cue.start_ms is not None for cue in selected) else None
        end = max(cue.end_ms for cue in selected) if all(cue.end_ms is not None for cue in selected) else None
        chunks.append(CorpusChunk(len(chunks), text, len(encoding.encode_ordinary(text)), spans, start, end))

    for cue in cues:
        for match in _SENTENCE.finditer(cue.text):
            sentence = _trim_span(cue, match.start(), match.end())
            if sentence is None:
                continue
            for part in _bounded_parts(cue, sentence, encoding, settings.max_tokens):
                if current and count(current + [part]) > settings.max_tokens:
                    emit()
                    overlap: list[CueSpan] = []
                    for previous in reversed(current):
                        if count([previous] + overlap) > settings.overlap_tokens:
                            break
                        overlap.insert(0, previous)
                    current = overlap
                    # A large new unit takes priority over optional overlap.
                    while current and count(current + [part]) > settings.max_tokens:
                        current.pop(0)
                current.append(part)
    if current:
        emit()
    return tuple(chunks)
