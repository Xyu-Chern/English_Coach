"""What both systems share after the first stage: the same ceilings and the same shape.

    answer(draft) = improve(draft)   each system's own loop (baseline.py, agent.py)
                    then assemble    the same final step for both (tools.assemble)

A spent budget ends the improvement, never the request: what exists is assembled.

The verified-slot lock (D1): the examples the first stage verified are shown to the learner at
once and never change afterwards; the continuation only fills the slots without one. So when the
first stage verified every slot there is nothing left to do, and neither system improves the
draft: no model call, no search, the first stage's answer is assembled as it is. The baseline
never changes a verified slot anyway; the agent keeps the submission behaviour (it may review and
change verified examples, and runs even when all are verified) only as AgentPipeline(locked=False).
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from ..draft import Draft
from ..results import ExpressionItem
from ..session import BUDGET_ERRORS, Budget, CoachError, RequestSession
from ..tools import assemble

ROUNDS = 3  # rounds (baseline) or turns (agent) after the first stage
CONTINUATION_BUDGET = Budget(model_calls=6, searches=9)  # the same ceilings for both systems


def locked_slots(draft: Draft) -> frozenset[int]:
    """The slots with a verified example now; read before the continuation, they are what the learner was shown."""
    return frozenset(i for i, slot in enumerate(draft.slots) if slot.citation is not None)


class ExpressionPipeline(ABC):
    """What happens after the first stage. A system only decides how the draft is improved (improve).

    Pipelines are shared by concurrent requests, so per-request state lives in locals only."""

    name: ClassVar[str]
    locked: bool = True  # the verified-slot lock (D1); only AgentPipeline(locked=False) turns it off

    def answer(self, session: RequestSession, draft: Draft) -> tuple[list[ExpressionItem], str | None]:
        """Improve the draft (unless the request was declined or nothing is left to fill) and assemble;
        returns expressions and the note."""
        if draft.decline is None and not self.skips_continuation(draft):
            try:
                self.improve(session, draft)
            except CoachError as exc:
                if exc.code not in BUDGET_ERRORS:
                    raise
                session.record("budget_exhausted", code=exc.code)
        return assemble(session, draft), draft.decline

    def skips_continuation(self, draft: Draft) -> bool:
        """Under the lock, a draft whose every slot is verified is final: nothing runs after the first stage."""
        return self.locked and bool(draft.slots) and len(locked_slots(draft)) == len(draft.slots)

    @abstractmethod
    def improve(self, session: RequestSession, draft: Draft) -> None:
        """Change the draft in place within the session's budget."""
