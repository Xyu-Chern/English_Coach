"""The two systems and the first stage they share.

    first_stage.py   run once per request: candidates -> search each -> select -> verify
    base.py          what both share afterwards: the same ceilings and the verified-slot lock;
                     improve (skipped when the first stage verified every slot), then assemble
    baseline.py      a fixed workflow: code decides each next step
    agent.py         each turn the model reviews the draft and decides the next step

Both registered systems keep the verified-slot lock (D1). The agent of the submitted evaluation
is AgentPipeline(locked=False); it is not registered, so it runs only when passed explicitly
(ExpressionCoach(dependencies, AgentPipeline(locked=False))).
"""

from .agent import AgentPipeline
from .base import CONTINUATION_BUDGET, ExpressionPipeline, locked_slots
from .baseline import BaselinePipeline
from .first_stage import (FAST_FIRST_STAGE, FIRST_STAGE_BUDGET, FULL_FIRST_STAGE, FirstStageSettings,
                          run_first_stage)

# The two systems, in the order results are reported; the agent is the locked one.
SYSTEMS: dict[str, ExpressionPipeline] = {p.name: p for p in (BaselinePipeline(), AgentPipeline())}


def system_for(name: str) -> ExpressionPipeline:
    if name not in SYSTEMS:
        raise ValueError(f"Unknown system {name!r}; choose one of {sorted(SYSTEMS)}.")
    return SYSTEMS[name]


__all__ = ["SYSTEMS", "system_for", "ExpressionPipeline", "BaselinePipeline", "AgentPipeline", "run_first_stage",
           "FIRST_STAGE_BUDGET", "CONTINUATION_BUDGET", "locked_slots", "FirstStageSettings", "FULL_FIRST_STAGE",
           "FAST_FIRST_STAGE"]
