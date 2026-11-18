"""The baseline's reply: Revision (REVISE_PROMPT)."""

from typing import ClassVar

from pydantic import Field

from .base import ItemListReply
from .prefix import Candidate


class Replacement(Candidate):
    """ref names a seen span whose wording backs the replacement (verified, then no search)."""

    replaces: int = Field(ge=0, le=20)  # the slot whose expression this replaces
    ref: str | None = Field(default=None, max_length=40)
    reusable_wording: str | None = Field(default=None, max_length=200)
    source_use: str | None = Field(default=None, max_length=300)
    adaptation: str | None = Field(default=None, max_length=400)


class Revision(ItemListReply):
    items_fields: ClassVar[tuple[str, ...]] = ("replacements",)
    replacements: tuple[Replacement, ...] = Field(max_length=3)
