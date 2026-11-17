"""The coach: answer a learner request with one system, or with both for the evaluation.

    ExpressionCoach(dependencies, "agent").answer(question) -> RunResult   one system (e.g. an app)
    answer_pair(dependencies, question) -> {"baseline": ..., "agent": ...}   both, from one first stage

Each request: validate the input, run the first stage once in its own session, then each system
in a continuation session that carries a frozen snapshot of the first stage (its own budget,
trace and usage; the first stage is counted again in each result). Failures become error codes.
"""

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from pydantic import ValidationError

from .results import RunResult
from .session import CoachDependencies, CoachError, RequestSession, SessionLimits
from .systems import CONTINUATION_BUDGET, FIRST_STAGE_BUDGET, SYSTEMS, ExpressionPipeline, run_first_stage, system_for


class ExpressionCoach:
    """Answers one learner request at a time with one system.

    Each answer gets fresh sessions (own budgets, trace and usage), so one coach can serve
    concurrent requests.
    """

    def __init__(self, dependencies: CoachDependencies, pipeline: ExpressionPipeline | str = "agent",
                 limits: SessionLimits | None = None):
        self.dependencies = dependencies
        self.pipeline = system_for(pipeline) if isinstance(pipeline, str) else pipeline
        self.limits = limits or SessionLimits()

    def answer(self, question: str) -> RunResult:
        systems = {self.pipeline.name: (self.pipeline, self.dependencies)}
        return _answer(self.dependencies, question, systems, self.limits, shared=False, concurrent=False)[
            self.pipeline.name]


def answer_pair(dependencies: CoachDependencies, question: str, *,
                continuations: Mapping[str, CoachDependencies] | None = None, limits: SessionLimits | None = None,
                concurrent: bool = True, systems: Iterable[str] | None = None) -> dict[str, RunResult]:
    """Run the first stage once, then each system, each from its own deep copy of its state.

    The systems are those named by systems, else those continuations names, else both; a caller
    that records calls per system (the runner) never gets an unnamed one whose calls would land
    in the first stage's recorder. They run in SYSTEMS order. dependencies serve the first stage,
    and each system unless continuations names its own. With concurrent=True the continuations
    run in one thread each; dependencies they share must then be safe to call from all of them.
    First-stage steps are marked details.shared = true in every trace."""
    continuations = continuations or {}
    named = set(systems or continuations or SYSTEMS)
    unknown = named - set(SYSTEMS)
    if unknown:
        raise ValueError(f"Unknown systems: {sorted(unknown)}")
    chosen = {name: (system_for(name), continuations.get(name, dependencies)) for name in SYSTEMS if name in named}
    return _answer(dependencies, question, chosen, limits or SessionLimits(), shared=True, concurrent=concurrent)


def _answer(dependencies: CoachDependencies, question: str,
            systems: dict[str, tuple[ExpressionPipeline, CoachDependencies]], limits: SessionLimits, *,
            shared: bool, concurrent: bool) -> dict[str, RunResult]:
    prefix = RequestSession(dependencies, FIRST_STAGE_BUDGET, limits)
    if not _valid_input(question, limits):
        return {name: prefix.result(name, "invalid_input", error_code="invalid_input") for name in systems}
    draft, prefix_error = _attempt(prefix, lambda: run_first_stage(prefix, question))
    carried = prefix.snapshot(shared=shared)  # frozen now, so a system that starts later is not charged for waiting
    drafts = {name: deepcopy(draft) for name in systems}  # copied before either mutates its own: nothing shared

    def run(name: str) -> RunResult:
        pipeline, deps = systems[name]
        session = RequestSession(deps, CONTINUATION_BUDGET, limits, prefix=carried)
        if prefix_error:
            return session.result(name, "error", error_code=prefix_error)
        answer, error = _attempt(session, lambda: pipeline.answer(session, drafts[name]))
        if error:
            return session.result(name, "error", error_code=error)
        expressions, note = answer
        return session.result(name, "ok", expressions=expressions, note=note)

    if concurrent and len(systems) > 1:
        with ThreadPoolExecutor(len(systems)) as pool:
            return dict(zip(systems, pool.map(run, systems)))
    return {name: run(name) for name in systems}


def _attempt(session: RequestSession, work):
    """(value, None), or (None, error code) after recording the failure as the session's last step."""
    try:
        return work(), None
    except (ValidationError, UnicodeError):
        session.record("validate_action", error="invalid_model_output")
        return None, "invalid_model_output"
    except CoachError as exc:
        if not session.trace or session.trace[-1].status != "error":
            session.record("validate_action", error=exc.code, **exc.details)
        return None, exc.code


def _valid_input(question: str, limits: SessionLimits) -> bool:
    if not isinstance(question, str) or not question.strip() or len(question) > limits.max_input_chars:
        return False
    if "\x00" in question:
        return False
    try:
        question.encode("utf-8")
    except UnicodeError:
        return False
    return True
