"""The agent: each turn the model reviews the whole draft and chooses what to do. Code only runs it.

    agent_r               one call: a written review (assessment), then actions, and/or finish
      search_r_k            search: find passages for a slot or a new expression (seen next turn)
      repick_r_k            repick: back a slot with another span already seen (or a variant it shows)
      replace_r_k           replace: put another expression in a slot, with a seen span or none yet
    validate_agent_r      where the draft stands after the turn
    pick_final            after a last turn that searched: one call, repick/replace only

At most 3 turns. Unlike the baseline it re-reads verified examples and may change them; the guard (G1,
tools/change.py) keeps a verified example unless the new pick verifies. Actions that would
change nothing are recorded as noops and spend no budget.
"""

import re

from ..draft import Draft
from ..prompts.agent import AGENT_PROMPT
from ..schemas.agent import AgentDecision, FinalPick
from ..session import RequestSession
from ..tools import as_candidate, change_slot, identical_search, new_log, search, validate
from .base import ROUNDS, ExpressionPipeline

# A change whose stated reason names a meaning problem; the guard then moves the kept example to the end.
MEANING_REASON = re.compile(r"(different|another|other|wrong)[ _-]sense|partial[ _-]chunk|meaning", re.IGNORECASE)


def decision_view(session: RequestSession, draft: Draft, turn: int | None, history: list[dict]) -> dict:
    """What every agent call sees: the request, the draft, every span seen so far, what remains,
    earlier actions and what the last turn lost to validation."""
    final = turn is None
    remaining = {"turns_after_this": 0 if final else ROUNDS - turn, "searches": 0 if final else session.searches_left,
                 "pick_call_follows_if_you_search": not final and turn == ROUNDS}
    return {"question": draft.question, "final_pick": final, "remaining": remaining,
            "draft": [slot.view(i) for i, slot in enumerate(draft.slots)],
            "other_candidates": [c.model_dump(mode="json") for c in draft.alternatives],
            "passages": [o.view() for o in draft.searches.values()],
            "earlier_actions": history, "dropped_last_turn": session.take_dropped()}


class AgentPipeline(ExpressionPipeline):
    """The agent: each turn the model reviews the draft and acts on it, or finishes."""

    name = "agent"

    def improve(self, session: RequestSession, draft: Draft) -> None:
        history: list[dict] = []  # earlier actions and their outcomes, shown every turn
        searched = False
        for turn in range(1, ROUNDS + 1):
            decision = session.ask(f"agent_{turn}", AGENT_PROMPT, decision_view(session, draft, turn, history),
                                   AgentDecision)
            log = new_log()
            searched = self.act(session, draft, str(turn), decision.actions, history, log, finishing=decision.finish)
            validate(session, draft, f"validate_agent_{turn}", **log)
            if decision.finish:
                return
        if searched and session.model_calls_left > 0:  # the last turn's spans are unseen: one pick-only call
            pick = session.ask("pick_final", AGENT_PROMPT, decision_view(session, draft, None, history), FinalPick)
            log = new_log()
            self.act(session, draft, "final", pick.actions, history, log, finishing=True)
            validate(session, draft, "validate_pick_final", **log)

    def act(self, session: RequestSession, draft: Draft, turn: str, actions, history: list[dict], log: dict, *,
            finishing: bool) -> bool:
        """Run the actions in order, each its own trace step; returns whether any search ran."""
        searched = False
        for k, action in enumerate(actions, 1):
            stage = f"{action.type}_{turn}_{k}"
            noop = self.noop(draft, action)
            if noop:
                session.record(stage, noop=noop, slot=action.slot, reason=action.reason)
                log["noops"].append({"step": stage, "slot": action.slot, "reason": noop})
                outcome = f"noop:{noop}"
            elif action.type == "search":
                outcome = self.search_step(session, draft, stage, action, finishing, ref_prefix=f"a{turn}k{k}")
                searched = searched or outcome == "searched"
            else:
                outcome = self.pick_step(session, draft, stage, action, log)
            entry = {"turn": turn, "type": action.type, "slot": action.slot, "step": stage, "outcome": outcome}
            history.append({**entry, "noop": True} if noop else entry)
        return searched

    @staticmethod
    def noop(draft: Draft, action) -> str | None:
        """Why an action would change nothing: a search already run, or removing an example that is not there."""
        if action.type == "search":
            return "identical_search" if identical_search(draft, action.query, action.key_phrase) else None
        if (action.type == "repick" and action.ref is None and action.slot < len(draft.slots)
                and draft.slots[action.slot].citation is None):
            return "nothing_to_remove"
        return None

    @staticmethod
    def search_step(session: RequestSession, draft: Draft, stage: str, action, finishing: bool,
                    ref_prefix: str) -> str:
        """A search runs unless the turn finishes, the budget is spent or the slot does not exist."""
        skipped = ("finish_requested" if finishing else "no_searches_left" if session.searches_left <= 0
                   else "unknown_slot" if action.slot is not None and action.slot >= len(draft.slots) else None)
        if skipped:
            session.record(stage, skipped=skipped, slot=action.slot, query=action.query, key_phrase=action.key_phrase,
                           reason=action.reason)
            return f"skipped:{skipped}"
        search(session, draft, stage=stage, ref_prefix=ref_prefix, query=action.query, key_phrase=action.key_phrase,
               slot=action.slot, policy="agent_query", reason=action.reason)
        return "searched"

    @staticmethod
    def pick_step(session: RequestSession, draft: Draft, stage: str, action, log: dict) -> str:
        """repick: the slot's example becomes the named span (or none), optionally with the variant it
        shows; replace: a new expression, maybe with a span. G1 guards both (change_slot)."""
        if action.slot >= len(draft.slots):
            session.record(stage, skipped="unknown_slot", slot=action.slot, ref=action.ref, reason=action.reason)
            return "skipped:unknown_slot"
        replacing = action.type == "replace"
        candidate = as_candidate(action) if replacing else None
        variant = (action.expression, action.key_phrase) if not replacing and action.expression is not None else None
        return change_slot(session, draft, stage, action.slot, log, ref=action.ref, wording=action.reusable_wording,
                           source_use=action.source_use, adaptation=action.adaptation, candidate=candidate,
                           variant=variant, meaning=MEANING_REASON.search(action.reason) is not None,
                           reason=action.reason)
