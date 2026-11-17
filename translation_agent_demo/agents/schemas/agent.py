"""The agent's replies: AgentDecision (each turn) and FinalPick (the pick-only call).

Their actions are the tools' argument models (tools/search.py, tools/change.py).
"""

from typing import ClassVar, Union

from pydantic import Field

from ..tools.change import ReplaceAction, RepickAction
from ..tools.search import SearchAction
from .base import ItemListReply


class AgentDecision(ItemListReply):
    """One agent turn: its review of the draft, actions on the slots, and whether it is done."""

    items_fields: ClassVar[tuple[str, ...]] = ("actions",)
    assessment: str
    actions: tuple[Union[SearchAction, RepickAction, ReplaceAction], ...] = Field(max_length=6)
    finish: bool


class FinalPick(ItemListReply):
    """The pick-only call after a last turn that searched: no search, nothing after it."""

    items_fields: ClassVar[tuple[str, ...]] = ("actions",)
    assessment: str
    actions: tuple[Union[RepickAction, ReplaceAction], ...] = Field(max_length=6)
