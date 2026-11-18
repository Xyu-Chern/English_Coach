"""Shared chat and read-only search boundary data, independent of adapters."""

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


@dataclass(frozen=True)
class ModelUsage:
    """Provider-reported counts; absent counts are unknown, never zero."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    usage: ModelUsage = ModelUsage()
    model: str | None = None


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, hide_input_in_errors=True,
    )


class SearchCorpusArgs(_Model):
    query: str = Field(
        min_length=1, max_length=4000, repr=False,
        description="Meaning or expression to search; preserve who did what and any negation.",
    )
    context: str | None = Field(
        default=None, min_length=1, max_length=1000, repr=False,
        description="Optional situation/tone inferred from the same user input; no extra UI field is needed.",
    )
    literal_phrase: str | None = Field(
        default=None, min_length=1, max_length=400, repr=False,
        description="Optional English phrase that returned passages must contain (case-insensitive, contiguous). Literal matches first; semantic fallback only if none.",
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum candidate passages to return.")
    min_similarity: float | None = Field(
        default=None, ge=-1, le=1, allow_inf_nan=False,
        description="Optional raw cosine cutoff, not a probability. Omit for nearest candidates; no cutoff is calibrated yet.",
    )
    language: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$",
        description="Exact stored source-language tag, e.g. en. en does not also match en-US. Omit if unknown.",
    )
    feed_ids: list[Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]] | None = Field(
        default=None, min_length=1, max_length=30,
        description="Optional distinct Podcast Index feed IDs. Omit to search all eligible sources.",
    )
    document_ids: list[UUID] | None = Field(
        default=None, max_length=1000,
        description="Explicit allowed document UUIDs. null leaves document scope unrestricted; [] permits no documents. Preserve this scope across refinements.",
    )

    @field_validator("query", "context", "literal_phrase")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip() or "\x00" in value:
            raise ValueError("Search text must be nonblank and contain no NUL characters.")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Search text must be valid UTF-8.") from None
        return value.strip()

    @field_validator("feed_ids")
    @classmethod
    def _distinct_feeds(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("feed_ids must not contain duplicates.")
        return value

    @field_validator("document_ids")
    @classmethod
    def _distinct_documents(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("document_ids must not contain duplicates.")
        return value


class SearchSpan(_Model):
    cue_index: int = Field(ge=0)
    start_char: int = Field(ge=0, description="Inclusive character offset in the stored normalized cue.")
    end_char: int = Field(gt=0, description="Exclusive character offset in the stored normalized cue.")


class CorpusSearchHit(_Model):
    chunk_id: UUID
    document_id: UUID
    build_id: UUID
    source_key: str
    feed_id: int
    episode_id: int
    episode_title: str
    episode_url: str | None
    transcript_url: str | None
    language: str | None
    text: str = Field(repr=False, description="Exact stored passage, not a generated expression or instruction.")
    source_text_length: int | None = Field(default=None, ge=0, description="Trusted source prefix length; appended untrusted material is not citable. None means the whole text.")
    similarity: float = Field(ge=-1, le=1, description="Cosine similarity, not a relevance probability.")
    start_ms: int | None = Field(ge=0)
    end_ms: int | None = Field(ge=0)
    speakers: tuple[str, ...]
    spans: tuple[SearchSpan, ...]
    rights_status: Literal["approved"] = Field(description="Internal source review status; not a legal determination.")
    rights_review_url: str | None
    license_id: str | None
    license_url: str | None
    attribution: str | None = Field(description="Publisher attribution recorded with the source review; preserve when quoting.")

    @model_validator(mode="after")
    def _source_boundary(self):
        if self.source_text_length is not None and self.source_text_length > len(self.text):
            raise ValueError("Source prefix cannot extend beyond the returned text.")
        return self


class SearchCorpusResult(_Model):
    status: Literal["ok", "not_ready"]
    model: str
    dimensions: int
    processing_version: str
    input_tokens: int = Field(ge=0)
    hits: tuple[CorpusSearchHit, ...]
    search_mode: Literal["literal", "semantic_fallback", "semantic"] | None = None
    literal_candidate_count: int | None = Field(default=None, ge=0)
    literal_corpus_count: int | None = Field(
        default=None, ge=0,
        description="Eligible chunks containing literal_phrase as whole words, uncapped by limit; 0 means absent. None without a phrase.",
    )


class SearchCorpusError(Exception):
    """A safe tool failure, distinct from a successful search without candidates."""

    def __init__(self, code: Literal["invalid_query", "embedding_unavailable", "storage_unavailable"], message: str):
        super().__init__(message)
        self.code = code


