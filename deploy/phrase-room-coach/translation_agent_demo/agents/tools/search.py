"""Tool: search the corpus. Agent action: search.

    search          one budgeted corpus search: passages containing the key phrase first
                    (meaning-similarity fallback); the spans are shown with refs
    search_slot     search for a slot's own expression; its spans feed the next selection
    slot_searches   the searches search_slot would run for some slots, for session.prefetching
    identical_search  whether the same query and key phrase were searched before
"""

from typing import Literal

from pydantic import Field

from ..contracts import SearchCorpusArgs
from ..draft import Draft, Observation, expression_key
from ..evidence import FULL_VIEW, SpanView, normalize_phrase
from ..results import FrozenModel
from ..session import RequestSession

PASSAGES_PER_SEARCH = 3

# An action names its kind in "type", listed first so the decoder commits to the kind before
# its fields. reason is shown in the trace and not length-checked: an over-long explanation
# should not cost an action (the prompt states the lengths). A model's docstring is the
# description in its JSON Schema and reaches the model, so it is frozen with the prompt.


class SearchAction(FrozenModel):
    """Look for passages for a slot (or, with slot null, for an expression not in the draft)."""

    type: Literal["search"]
    slot: int | None = Field(default=None, ge=0, le=20)
    query: str = Field(min_length=1, max_length=300)
    key_phrase: str | None = Field(default=None, max_length=80)
    reason: str = ""


def search_args(draft: Draft, query: str, key_phrase: str | None) -> SearchCorpusArgs:
    """The corpus search for a query and key phrase in this draft (its show, if the request named one)."""
    return SearchCorpusArgs(query=query, literal_phrase=normalize_phrase(key_phrase), limit=PASSAGES_PER_SEARCH,
                            feed_ids=draft.feeds)


def search(session: RequestSession, draft: Draft, *, stage: str, ref_prefix: str, query: str,
           key_phrase: str | None, slot: int | None, policy: str, view: SpanView = FULL_VIEW,
           **details) -> Observation:
    """Passages containing the key phrase first (meaning-similarity fallback); spans shown with refs, as many
    and as long as the view allows (the fast first stage's compact view, else all of them)."""
    args = search_args(draft, query, key_phrase)
    phrase = args.literal_phrase
    found = session.search(args, policy=policy, stage=stage, slot=slot, ref_prefix=ref_prefix, **details)
    observation = Observation(stage, query, phrase, found.corpus_count,
                              draft.catalog.present(found.hits, ref_prefix, phrase, view))
    draft.searches[stage] = observation
    return observation


def slot_searches(draft: Draft, indices: list[int]) -> list[SearchCorpusArgs]:
    """The searches search_slot would run for these slots now, in order: what a session can prefetch."""
    return [search_args(draft, draft.slots[i].expression, draft.slots[i].key_phrase) for i in indices]


def search_slot(session: RequestSession, draft: Draft, index: int, *, stage: str, ref_prefix: str,
                view: SpanView = FULL_VIEW) -> None:
    """Search for a slot's own expression; its spans are what the next selection sees for it."""
    slot = draft.slots[index]
    search(session, draft, stage=stage, ref_prefix=ref_prefix, query=slot.expression, key_phrase=slot.key_phrase,
           slot=index, policy="candidate_expression", view=view)
    slot.search = stage


def identical_search(draft: Draft, query: str, key_phrase: str | None) -> bool:
    """The same query and key phrase were searched before: the same spans would come back."""
    wanted = (expression_key(query), (normalize_phrase(key_phrase) or "").casefold())
    return any((expression_key(o.query), (o.key_phrase or "").casefold()) == wanted for o in draft.searches.values())
