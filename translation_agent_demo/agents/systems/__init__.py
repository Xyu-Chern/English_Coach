"""The two systems and the first stage they share.

    first_stage.py   run once per request: candidates -> search each -> select -> verify
    base.py          what both share afterwards: the same ceilings; improve, then assemble
    baseline.py      a fixed workflow: code decides each next step
    agent.py         each turn the model reviews the draft and decides the next step
"""

from .agent import AgentPipeline
from .base import CONTINUATION_BUDGET, ExpressionPipeline
from .baseline import BaselinePipeline
from .first_stage import FIRST_STAGE_BUDGET, run_first_stage

# The two systems, in the order results are reported.
SYSTEMS: dict[str, ExpressionPipeline] = {p.name: p for p in (BaselinePipeline(), AgentPipeline())}


def system_for(name: str) -> ExpressionPipeline:
    if name not in SYSTEMS:
        raise ValueError(f"Unknown system {name!r}; choose one of {sorted(SYSTEMS)}.")
    return SYSTEMS[name]


__all__ = ["SYSTEMS", "system_for", "ExpressionPipeline", "BaselinePipeline", "AgentPipeline", "run_first_stage",
           "FIRST_STAGE_BUDGET", "CONTINUATION_BUDGET"]
