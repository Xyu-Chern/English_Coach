"""Staged answers (D1): the first stage's verified examples at once, then the whole final answer.

    StagedCoach(dependencies, mode).stream(question, guard) -> events, in this order:

      First(expressions, pending)  the examples the first stage verified, and only those. They are
                                   final: the continuation fills only the other slots (the verified-
                                   slot lock). pending=False: nothing follows.
      Final(expressions, added)    the whole final answer. It starts with First's items, unchanged;
                                   added = indexes of the examples verified after the first stage.
      Failed(code)                 the request ended without (more of) an answer.

    first stage verified           continuation on                      continuation off
    every slot                     First(pending=False), nothing runs    First(pending=False)
    1-2 slots                      First(pending=True), Final | Failed   First(pending=False)
    none, or declined              Final | Failed, as one answer         Final (the first stage's)

With the continuation on, the run is ExpressionCoach(dependencies, mode.system).answer(question):
the same sessions, steps, trace and result; only the events are new. A terminal event carries
that RunResult. Unverified candidates never reach First.

Mode (D5): COACH_SYSTEM = agent (default, the locked agent) | baseline and COACH_CONTINUATION =
on (default) | off, read once when the app starts; any other value stops the start. Changing
them takes a restart (a new deployment on Vercel).

Guard: one request's stop switch, deadline and meter. The dependencies it wraps refuse every
model call and search after stop() or the deadline, so work the transport gave up on ends at its
next call; it also counts calls and reported tokens for the request log.

This module is outside translation_agent_demo/ on purpose: the evaluation hashes that code, and
staging changes when the learner sees an answer, not what the answer is.
"""

import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace

from translation_agent_demo.agents.coach import _attempt, _valid_input
from translation_agent_demo.agents.draft import ANSWER_SIZE, Draft, expression_key
from translation_agent_demo.agents.results import ExpressionItem, RunResult
from translation_agent_demo.agents.session import CoachDependencies, RequestSession, SessionLimits
from translation_agent_demo.agents.systems import (CONTINUATION_BUDGET, FIRST_STAGE_BUDGET, SYSTEMS, run_first_stage,
                                                   system_for)
from translation_agent_demo.agents.tools import assemble

SYSTEM_CHOICES = ("agent", "baseline")  # the first is the default
CONTINUATION_CHOICES = ("on", "off")


# ------------------------------------------------------------------ mode
@dataclass(frozen=True)
class CoachMode:
    """Which system answers and whether anything runs after the first stage."""

    system: str = SYSTEM_CHOICES[0]
    continuation: bool = True

    def __post_init__(self):
        if self.system not in SYSTEMS:
            raise ValueError(f"Unknown system {self.system!r}; choose one of {sorted(SYSTEMS)}.")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "CoachMode":
        """COACH_SYSTEM and COACH_CONTINUATION; unset or empty means the default, anything else unknown fails."""
        environ = os.environ if environ is None else environ
        return cls(_setting(environ, "COACH_SYSTEM", SYSTEM_CHOICES),
                   _setting(environ, "COACH_CONTINUATION", CONTINUATION_CHOICES) == "on")

    @property
    def continuation_setting(self) -> str:
        return "on" if self.continuation else "off"


def _setting(environ: Mapping[str, str], name: str, choices: tuple[str, ...]) -> str:
    raw = environ.get(name)
    value = (raw or "").strip().lower() or choices[0]
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}; got {raw!r}.")
    return value


# ------------------------------------------------------------------ events
@dataclass(frozen=True)
class First:
    """The first stage's verified examples. pending=False ends the request (continuation skipped or off)."""

    expressions: tuple[ExpressionItem, ...]
    pending: bool
    note: str | None = None
    result: RunResult | None = None  # set when pending is False
    continuation: str | None = None  # "skipped" or "off" when pending is False


@dataclass(frozen=True)
class Final:
    """The whole final answer; its first items are First's, unchanged."""

    expressions: tuple[ExpressionItem, ...]
    added: tuple[int, ...]  # indexes of examples verified after the first stage
    note: str | None
    result: RunResult | None
    verified_first: int | None  # None for a declined request
    continuation: str  # "ran", "off", or "none" (declined)
    declined: bool = False
    kept_first: bool = True  # False: the answer had changed a sent example, which was put back


@dataclass(frozen=True)
class Failed:
    """No (more) answer: an error code, as the JSON API reports it."""

    code: str
    result: RunResult | None = None
    continuation: str = "none"  # "ran" when the continuation failed


Event = First | Final | Failed


def is_terminal(event: Event) -> bool:
    return not (isinstance(event, First) and event.pending)


# ------------------------------------------------------------------ guard
class Stopped(Exception):
    """A guarded dependency was called after the request was stopped or passed its deadline."""

    code = "stopped"  # not a model answer error: the session records it as unavailable


class Guard:
    """One request's stop switch, deadline and meter, shared by the transport and the coach's dependencies."""

    def __init__(self, deadline: float | None = None, clock: Callable[[], float] = time.monotonic):
        self.deadline, self.clock = deadline, clock
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self.llm_calls = self.searches = 0
        self.input_tokens = self.output_tokens = self.cached_input_tokens = 0

    def stop(self) -> None:
        self._stopped.set()

    @property
    def expired(self) -> bool:
        return self.deadline is not None and self.clock() >= self.deadline

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set() or self.expired

    def check(self) -> None:
        if self.stopped:
            raise Stopped()

    def wrap(self, dependencies: CoachDependencies) -> CoachDependencies:
        """The same dependencies, refusing work once stopped and counting what they do."""
        model = dependencies.model
        guarded = (_ObservedModel if callable(getattr(model, "complete_with_usage", None)) else _PlainModel)(model, self)
        return replace(dependencies, model=guarded, search=_GuardedSearch(dependencies.search, self))

    def count(self, *, calls: int = 0, searches: int = 0, usage=None) -> None:
        """Add attempted calls or searches, or the tokens a provider reported (ModelUsage) for one call."""
        with self._lock:
            self.llm_calls += calls
            self.searches += searches
            if usage is not None:
                self.input_tokens += usage.input_tokens or 0
                self.output_tokens += usage.output_tokens or 0
                self.cached_input_tokens += usage.cached_input_tokens or 0

    def usage(self) -> dict:
        """Calls and searches attempted, and the tokens providers reported (unreported counts add nothing)."""
        with self._lock:
            return {"llm_calls": self.llm_calls, "searches": self.searches, "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens, "cached_input_tokens": self.cached_input_tokens}


class _ObservedModel:
    def __init__(self, model, guard: Guard):
        self.model, self.guard = model, guard

    def complete_with_usage(self, *, system_prompt: str, user_payload: str, response_format: dict | None = None):
        self.guard.check()
        self.guard.count(calls=1)
        response = self.model.complete_with_usage(system_prompt=system_prompt, user_payload=user_payload,
                                                  response_format=response_format)
        self.guard.count(usage=getattr(response, "usage", None))
        return response


class _PlainModel:
    def __init__(self, model, guard: Guard):
        self.model, self.guard = model, guard

    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        self.guard.check()
        self.guard.count(calls=1)
        return self.model.complete(system_prompt=system_prompt, user_payload=user_payload)


class _GuardedSearch:
    def __init__(self, search, guard: Guard):
        self.search, self.guard = search, guard

    def __call__(self, args):
        self.guard.check()
        self.guard.count(searches=1)
        return self.search(args)


# ------------------------------------------------------------------ coach
class StagedCoach:
    """Answers one request in stages with one locked system; each stream gets fresh sessions."""

    def __init__(self, dependencies: CoachDependencies, mode: CoachMode | None = None,
                 limits: SessionLimits | None = None):
        self.dependencies = dependencies
        self.mode = mode or CoachMode()
        self.pipeline = system_for(self.mode.system)
        if not self.pipeline.locked:
            raise ValueError("Sending the first stage's examples at once needs the verified-slot lock.")
        self.limits = limits or SessionLimits()

    def stream(self, question: str, guard: Guard | None = None) -> Iterator[Event]:
        """The events of one request; the last one is terminal (is_terminal)."""
        deps = guard.wrap(self.dependencies) if guard else self.dependencies
        name, limits = self.pipeline.name, self.limits
        # The same sessions, in the same order, as ExpressionCoach.answer (coach._answer).
        prefix = RequestSession(deps, FIRST_STAGE_BUDGET, limits)
        if not _valid_input(question, limits):
            yield Failed("invalid_input", prefix.result(name, "invalid_input", error_code="invalid_input"))
            return
        draft, error = _attempt(prefix, lambda: run_first_stage(prefix, question))
        session = RequestSession(deps, CONTINUATION_BUDGET, limits, prefix=prefix.snapshot(shared=False))
        if error:
            yield Failed(error, session.result(name, "error", error_code=error))
            return
        first = verified_items(draft)  # read before anything can change the draft
        declined = draft.decline is not None
        if first and not declined:
            if not self.mode.continuation:
                expressions = assemble(session, draft)
                yield First(first, False, result=session.result(name, "ok", expressions=expressions),
                            continuation="off")
                return
            if self.pipeline.skips_continuation(draft):
                answer, error = _attempt(session, lambda: self.pipeline.answer(session, draft))
                if error:  # assembling cannot fail in practice; what was verified is still final
                    yield First(first, False, result=session.result(name, "error", error_code=error),
                                continuation="skipped")
                    return
                expressions, note = answer
                yield First(first, False, result=session.result(name, "ok", expressions=expressions, note=note),
                            continuation="skipped")
                return
            yield First(first, True)
        if self.mode.continuation:
            answer, error = _attempt(session, lambda: self.pipeline.answer(session, draft))
        else:
            answer, error = (assemble(session, draft), draft.decline), None
        if error:
            yield Failed(error, session.result(name, "error", error_code=error),
                         continuation="none" if declined else "ran")
            return
        expressions, note = answer
        result = session.result(name, "ok", expressions=expressions, note=note)
        final, kept = keep_first(first, expressions)
        added = tuple(i for i in range(len(first), len(final)) if final[i].citation is not None)
        yield Final(final, added, note, result, verified_first=None if declined else len(first),
                    continuation="none" if declined else "ran" if self.mode.continuation else "off",
                    declined=declined, kept_first=kept)


class _Unrecorded:
    """assemble's session for the first answer: it is built from the draft without a trace step."""

    @staticmethod
    def record(*args, **details) -> None:
        return None


def verified_items(draft: Draft) -> tuple[ExpressionItem, ...]:
    """The draft's verified expressions, in the order the final answer will show them first."""
    return tuple(item for item in assemble(_Unrecorded, draft) if item.citation is not None)


def keep_first(first: tuple[ExpressionItem, ...],
               expressions: list[ExpressionItem]) -> tuple[tuple[ExpressionItem, ...], bool]:
    """The final answer with the sent items first and unchanged; False if that had to be enforced."""
    if tuple(expressions[:len(first)]) == first:
        return tuple(expressions), True
    sent = {expression_key(item.expression) for item in first}
    rest = [item for item in expressions if expression_key(item.expression) not in sent]
    return (*first, *rest)[:max(ANSWER_SIZE, len(first))], False
