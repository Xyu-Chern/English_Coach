"""Replies of the shared first stage: CandidateSet (CANDIDATES_PROMPT) and Selection (SELECT_PROMPT)."""

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from ..results import FrozenModel
from .base import ItemListReply, _require_contiguous

RequestKind = Literal["specific", "function", "idiom", "draft", "usage", "compare"]
Show = Literal["go_time", "js_party", "the_changelog"]


class Candidate(FrozenModel):
    expression: str = Field(min_length=1, max_length=300)
    key_phrase: str = Field(min_length=1, max_length=80)  # reusable core; drives literal-first search
    function: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _contiguous_key_phrase(self):
        _require_contiguous(self.key_phrase, self.expression)
        return self


class CandidateSet(ItemListReply):
    """request_status is decoded first: a declined request needs no kind-specific candidates."""

    items_fields: ClassVar[tuple[str, ...]] = ("candidates",)
    request_status: Literal["answerable", "source_not_available", "out_of_scope"] = "answerable"
    status_note: str | None = Field(default=None, max_length=300)
    kind: RequestKind
    source_show: Show | None = None
    candidates: tuple[Candidate, ...] = Field(max_length=6)


class Pick(FrozenModel):
    """ref null means no span qualified; the text fields are then null too."""

    candidate: int = Field(ge=0, le=20)
    ref: str | None = Field(default=None, max_length=40)
    expression: str = Field(min_length=1, max_length=300)
    key_phrase: str | None = Field(default=None, max_length=80)
    reusable_wording: str | None = Field(default=None, max_length=200)
    source_use: str | None = Field(default=None, max_length=300)
    adaptation: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _contiguous_key_phrase(self):
        _require_contiguous(self.key_phrase, self.expression)
        return self


class Selection(ItemListReply):
    items_fields: ClassVar[tuple[str, ...]] = ("picks",)
    picks: tuple[Pick, ...] = Field(max_length=6)
