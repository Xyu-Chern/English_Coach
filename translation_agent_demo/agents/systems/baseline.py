"""The baseline: a fixed workflow. Code decides every next step.

    while a slot has no verified example (at most 3 rounds):
      revise_r            one call proposes replacements for the unsupported slots; it sees every
                          span seen so far and the candidates outside the answer
      (a replacement whose ref verifies is adopted at once and spends no search)
      search_r_k          one search per other replacement (at most 3; with search_workers > 1 they
                          run at once, recorded in replacement order)
      select_{r+1}        one call picks examples for them; code verifies
      validate_select_{r+1}
    it stops early only when a revision offers nothing new. Verified slots are never touched, so the
    baseline always keeps the verified-slot lock; when the first stage verified every slot it does not
    run at all (base.py skips it before the first round).
"""

from collections.abc import Callable
from copy import deepcopy

from ..contracts import SearchCorpusArgs
from ..draft import Draft
from ..prompts.baseline import REVISE_PROMPT
from ..schemas.baseline import Revision
from ..session import RequestSession
from ..tools import as_candidate, search_slot, select, slot_searches, validate
from .base import ROUNDS, ExpressionPipeline

SEARCHES_PER_REVISION = 3


class BaselinePipeline(ExpressionPipeline):
    """The baseline, a fixed workflow: while a slot lacks a verified example, revise, search and select again."""

    name = "baseline"

    def improve(self, session: RequestSession, draft: Draft) -> None:
        for round_ in range(1, ROUNDS + 1):
            missing = [i for i, slot in enumerate(draft.slots) if slot.citation is None]
            if not missing:
                return
            replaced, searched = self.revise(session, draft, round_, missing)
            if not replaced:  # nothing new, so another round could only repeat this one
                return
            if searched:
                select(session, draft, f"select_{round_ + 1}", searched)
            validate(session, draft, f"validate_select_{round_ + 1}")

    @staticmethod
    def unsupported(draft: Draft, index: int) -> dict:
        """An unsupported slot as REVISE sees it: its purpose, what it tried and its last search."""
        slot = draft.slots[index]
        return {"slot": index, "expression": slot.expression, "key_phrase": slot.key_phrase,
                "function": slot.candidate.function, "note": slot.candidate.note,
                "rejection_reasons": list(slot.rejections), "tried": slot.tried,
                "corpus_count": draft.corpus_count_of(slot), "spans": draft.spans_of(slot)}

    def revise(self, session: RequestSession, draft: Draft, round_: int,
               missing: list[int]) -> tuple[list[int], list[int]]:
        """One call proposes replacements for unsupported slots; returns (slots replaced, slots searched).

        A replacement with a ref that verifies needs no search; any other is searched once."""
        allowed = min(SEARCHES_PER_REVISION, len(missing))
        verified = [{"slot": i, "expression": slot.expression} for i, slot in enumerate(draft.slots)
                    if slot.citation is not None]
        payload = {"question": draft.question, "replacements_allowed": allowed,
                   "unsupported_slots": [self.unsupported(draft, i) for i in missing], "verified_slots": verified,
                   "span_pool": draft.span_pool(),
                   "alternatives": [{"expression": c.expression, "key_phrase": c.key_phrase, "function": c.function}
                                    for c in draft.alternatives],
                   "dropped_last_turn": session.take_dropped()}
        revision = session.ask(f"revise_{round_}", REVISE_PROMPT, payload, Revision)
        # The round's searches are independent of each other: with search_workers > 1 they start at
        # once. Which slots need one is found by applying the revision to a copy first; the real pass
        # below asks for them in the same order (a search the copy did not foresee simply runs then).
        planned = self.planned_searches(draft, revision, missing, allowed) if session.parallel_searches else []
        with session.prefetching(planned):
            return self.apply(draft, revision, missing, allowed, lambda index, k: search_slot(
                session, draft, index, stage=f"search_{round_}_{k}", ref_prefix=f"r{round_}k{k}"))

    @classmethod
    def planned_searches(cls, draft: Draft, revision: Revision, missing: list[int],
                         allowed: int) -> list[SearchCorpusArgs]:
        """The searches apply() will run, in order, found on a copy of the draft (nothing is searched)."""
        trial, planned = deepcopy(draft), []
        cls.apply(trial, revision, missing, allowed, lambda index, k: planned.extend(slot_searches(trial, [index])))
        return planned

    @staticmethod
    def apply(draft: Draft, revision: Revision, missing: list[int], allowed: int,
              search: Callable[[int, int], object]) -> tuple[list[int], list[int]]:
        """Adopt the replacements in order; search(slot, k) for each whose ref does not verify."""
        replaced: list[int] = []
        searched: list[int] = []
        for replacement in revision.replacements:
            index = replacement.replaces
            if len(replaced) == allowed or index not in missing or index in replaced:
                continue
            draft.replace(index, as_candidate(replacement))
            replaced.append(index)
            if replacement.ref is not None:
                draft.attach(index, replacement.ref, expression=replacement.expression,
                             key_phrase=replacement.key_phrase, wording=replacement.reusable_wording,
                             source_use=replacement.source_use, adaptation=replacement.adaptation)
                if draft.slots[index].citation is not None:
                    continue
            search(index, len(searched) + 1)
            searched.append(index)
        return replaced, searched
