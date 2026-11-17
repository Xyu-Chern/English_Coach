"""What both systems share after the first stage: the same ceilings and the same shape.

    answer(draft) = improve(draft)   each system's own loop (baseline.py, agent.py)
                    then assemble    the same final step for both (tools.assemble)

A spent budget ends the improvement, never the request: what exists is assembled.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from ..draft import Draft
from ..results import ExpressionItem
from ..session import BUDGET_ERRORS, Budget, CoachError, RequestSession
from ..tools import assemble

ROUNDS = 3  # rounds (baseline) or turns (agent) after the first stage
CONTINUATION_BUDGET = Budget(model_calls=6, searches=9)  # the same ceilings for both systems


class ExpressionPipeline(ABC):
    """What happens after the first stage. A system only decides how the draft is improved (improve).

    Pipelines are shared by concurrent requests, so per-request state lives in locals only."""

    name: ClassVar[str]

    def answer(self, session: RequestSession, draft: Draft) -> tuple[list[ExpressionItem], str | None]:
        """Improve the draft (unless the request was declined) and assemble; returns expressions and the note."""
        if draft.decline is None:
            try:
                self.improve(session, draft)
            except CoachError as exc:
                if exc.code not in BUDGET_ERRORS:
                    raise
                session.record("budget_exhausted", code=exc.code)
        return assemble(session, draft), draft.decline

    @abstractmethod
    def improve(self, session: RequestSession, draft: Draft) -> None:
        """Change the draft in place within the session's budget."""
