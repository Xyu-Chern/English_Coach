"""What the coach returns: ranked expressions, verified examples, a trace and usage."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    """Strict, immutable and closed: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class SourceCitation(FrozenModel):
    """An exact quote from an approved transcript, with its context and provenance.

    The quote, context and offsets are copied by code; only source_use and adaptation
    are model-written explanations.
    """

    chunk_id: UUID
    document_id: UUID
    build_id: UUID
    source_key: str
    episode_title: str
    episode_url: str | None
    transcript_url: str | None
    quote: str
    quote_start_char: int
    quote_end_char: int
    source_context: str = Field(min_length=1, max_length=1200)
    context_start_char: int = Field(ge=0)
    context_end_char: int = Field(gt=0)
    source_use: str = Field(min_length=1, max_length=300)
    adaptation: str = Field(min_length=1, max_length=400)
    chunk_start_ms: int | None
    chunk_end_ms: int | None
    rights_status: Literal["approved"]
    rights_review_url: str | None
    license_id: str | None
    license_url: str | None
    attribution: str | None

    @model_validator(mode="after")
    def _quote_inside_context(self):
        start = self.quote_start_char - self.context_start_char
        end = self.quote_end_char - self.context_start_char
        if (not 0 <= self.context_start_char <= self.quote_start_char < self.quote_end_char <= self.context_end_char
                or len(self.source_context) != self.context_end_char - self.context_start_char
                or self.source_context[start:end] != self.quote):
            raise ValueError("The original quote must match its exact context slice.")
        return self


class ExpressionItem(FrozenModel):
    """One of up to three ranked expressions; citation is None when no example was verified."""

    expression: str = Field(min_length=1, max_length=300)
    key_phrase: str | None = Field(default=None, max_length=80)  # the reusable core, shown to the judge
    function: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=300)
    citation: SourceCitation | None = None


class ToolCall(FrozenModel):
    name: Literal["search_corpus"] = "search_corpus"
    args: dict
    status: Literal["ok", "not_ready", "error"]
    error_code: str | None = None


class TraceSpan(FrozenModel):
    stage: str
    status: Literal["ok", "error"]
    elapsed_ms: float
    details: dict = Field(default_factory=dict)


class Usage(FrozenModel):
    """Token counts; None means a provider did not report a count (unknown, not zero)."""

    input_tokens: int | None
    output_tokens: int | None
    embedding_tokens: int | None
    cached_input_tokens: int | None
    reported_chat_calls: int
    total_chat_calls: int


class RunResult(FrozenModel):
    """One answered (or refused, or failed) request."""

    request_id: str
    variant: str  # the system: baseline or agent
    status: Literal["ok", "invalid_input", "error"]
    answer: str
    expressions: list[ExpressionItem] | None
    model_rounds: int
    tool_calls: list[ToolCall]
    trace: list[TraceSpan]
    elapsed_ms: float
    usage: Usage
    error_code: str | None = None
    source_availability_note: str | None = None


def render_answer(expressions: list[ExpressionItem] | None, note: str | None) -> str:
    """Plain-text answer: each expression, its example (or that none was verified), then any note."""
    if expressions is None:
        text = "Unable to answer this request."
    else:
        text = "\n\n".join(
            f"{rank}. {item.expression}  [{item.function}]\n{item.note}\n" + (
                f'Podcast example: “{item.citation.quote}” — {item.citation.episode_title}\n'
                f'Original surrounding context: {item.citation.source_context}\n'
                f'Source use (model explanation): {item.citation.source_use}\n'
                f'How to reuse it (model explanation): {item.citation.adaptation}'
                if item.citation else "No verified podcast example for this expression.")
            for rank, item in enumerate(expressions, 1)) or "No expressions are offered for this request."
    return text + ("\n\n" + note if note else "")
