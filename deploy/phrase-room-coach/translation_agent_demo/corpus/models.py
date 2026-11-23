"""Common records for derived corpus data; the acquired document stays immutable."""

from dataclasses import dataclass, field
from typing import Literal


class CorpusParseError(Exception):
    """A stable failure code, without publisher content in logs."""

    def __init__(self, code: Literal["unsupported_format", "invalid_format", "empty_transcript"]):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Cue:
    """One subtitle cue or HTML/Markdown turn/paragraph in source order.

    Times are explicit publisher timestamps in milliseconds, never inferred from
    the next cue. Missing timing and speaker information stays null.
    """

    index: int
    text: str = field(repr=False)
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


@dataclass(frozen=True)
class ParsedTranscript:
    format: Literal["html", "srt", "markdown"]
    cues: tuple[Cue, ...]


@dataclass(frozen=True)
class CueSpan:
    """A half-open Python character slice in one parsed cue, not the raw HTML."""

    cue_index: int
    start_char: int
    end_char: int


@dataclass(frozen=True)
class CorpusChunk:
    """Adjacent source slices joined by spaces, without generated wording.

    Timing covers the contributing cues; it does not claim word-level alignment
    when a long cue is split. Full speaker/timing detail remains in those cues.
    """

    index: int
    text: str = field(repr=False)
    token_count: int
    spans: tuple[CueSpan, ...]
    start_ms: int | None = None
    end_ms: int | None = None
