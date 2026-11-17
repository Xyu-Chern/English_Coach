"""One request's budgets, model calls, searches and trace.

A pipeline never calls the model or the search tool directly: it asks the session,
which enforces the call and search budgets, validates every model reply against a
schema, validates every search result, and records each step in the trace.

A request runs in several sessions: one for the shared first stage, then one per system that
continues from a frozen snapshot of it (SharedPrefix, the "prefix" of the system's run). The
continuation has its own budget; its result counts the first stage's steps, usage and time
again, so each system reports first stage + its own continuation.

Items a reply loses to validation are kept until the system's next decision call takes them
(take_dropped), so that call is told what its last turn lost (dropped_last_turn).
"""

import json
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from .contracts import (ChatCompletion, CorpusSearchHit, ModelUsage, SearchCorpusArgs, SearchCorpusError,
                        SearchCorpusResult)
from .protocol import ChatModel, ObservedChatModel, SearchCorpus
from .evidence import hit_summary, source_length
from .results import ExpressionItem, RunResult, ToolCall, TraceSpan, Usage, render_answer
from .structured import drop_reason, parse_reply, response_format

T = TypeVar("T", bound=BaseModel)
# Provider codes for a model that answered but unusably (refused, cut off, no text). They are
# kept so a run does not count them as infrastructure failures; anything else is model_unavailable.
MODEL_ANSWER_ERRORS = {"model_refused", "model_output_truncated", "invalid_model_output"}
BUDGET_ERRORS = {"model_budget_exhausted", "search_budget_exhausted"}


class CoachError(Exception):
    """A bounded failure that ends the request with a stable error code."""

    def __init__(self, code: str, **details):
        super().__init__(code)
        self.code, self.details = code, details


@dataclass(frozen=True)
class CoachDependencies:
    """Everything external the coach uses; all of it is injected."""

    model: ChatModel | ObservedChatModel
    search: SearchCorpus
    clock: Callable[[], float] = time.perf_counter


@dataclass(frozen=True)
class Budget:
    model_calls: int
    searches: int

    def __post_init__(self):
        if type(self.model_calls) is not int or not 1 <= self.model_calls <= 6:
            raise ValueError("A request may use 1 to 6 model calls.")
        if type(self.searches) is not int or not 1 <= self.searches <= 9:
            raise ValueError("A request may use 1 to 9 searches.")


@dataclass(frozen=True)
class SessionLimits:
    max_input_chars: int = 4000
    max_model_output_chars: int = 16000


@dataclass(frozen=True)
class SharedPrefix:
    """The prefix's steps, usage and time, frozen when it ended and carried into each continuation."""

    trace: tuple[TraceSpan, ...]
    tool_calls: tuple[ToolCall, ...]
    chat_usage: tuple[ModelUsage, ...]
    embedding_usage: tuple[int | None, ...]
    elapsed_ms: float


@dataclass(frozen=True)
class SearchOutcome:
    """A checked search: its hits and how many corpus chunks contain the literal phrase (None without one)."""

    hits: list[CorpusSearchHit]
    corpus_count: int | None


@dataclass
class RequestSession:
    deps: CoachDependencies
    budget: Budget
    limits: SessionLimits = field(default_factory=SessionLimits)
    prefix: SharedPrefix | None = None  # counted in this session's result, not in its budget

    def __post_init__(self):
        self.started = self.deps.clock()
        self.trace: list[TraceSpan] = []
        self.tool_calls: list[ToolCall] = []
        self.chat_usage: list[ModelUsage] = []
        self.embedding_usage: list[int | None] = []
        self.dropped: list[dict] = []  # {step, slot, reason, list, index, field, error} not yet shown

    # ----------------------------------------------------------- budgets
    @property
    def model_calls_used(self) -> int:
        return len(self.chat_usage)

    @property
    def model_calls_left(self) -> int:
        return self.budget.model_calls - self.model_calls_used

    @property
    def searches_used(self) -> int:
        return len(self.tool_calls)

    @property
    def searches_left(self) -> int:
        return self.budget.searches - self.searches_used

    # ----------------------------------------------------------- tools
    def ask(self, stage: str, prompt: str, payload: dict, schema: type[T]) -> T:
        """One budgeted model call, decoded against the schema (structured outputs) and validated.

        Invalid list items are dropped and recorded; any other mismatch fails the step."""
        if self.model_calls_left <= 0:
            raise CoachError("model_budget_exhausted")
        started = self.deps.clock()
        self.chat_usage.append(ModelUsage())
        try:
            response = self._complete(prompt, json.dumps(payload, ensure_ascii=False), response_format(schema))
            self.chat_usage[-1] = response.usage
        except Exception as exc:  # only an unreachable model is an infrastructure failure
            code = getattr(exc, "code", None)
            code = code if code in MODEL_ANSWER_ERRORS else "model_unavailable"
            self.record(stage, started, error=code)
            raise CoachError(code) from None
        try:
            if not isinstance(response.content, str) or len(response.content) > self.limits.max_model_output_chars:
                raise ValueError("Invalid response length.")
            parsed, dropped = parse_reply(schema, response.content)
        except (ValueError, ValidationError):
            self.record(stage, started, error="invalid_model_output")
            raise CoachError("invalid_model_output") from None
        details = {"dropped_items": dropped} if dropped else {}
        self.dropped += [{"step": stage, "slot": item.get("slot"), "reason": drop_reason(item),
                          **{key: item.get(key) for key in ("list", "index", "field", "error")}} for item in dropped]
        self.record(stage, started, model=response.model, input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens, output=parsed.model_dump(mode="json"), **details)
        return parsed

    def take_dropped(self) -> list[dict]:
        """Items dropped since the last take: what the next decision call is told it lost."""
        dropped, self.dropped = self.dropped, []
        return dropped

    def search(self, args: SearchCorpusArgs, *, policy: str, stage: str | None = None,
               **details) -> SearchOutcome:
        """One budgeted corpus search; the result is checked before anyone sees it.

        details (for example the slot it is for) are added to the trace step, with corpus_count:
        the whole-corpus number of chunks containing the literal phrase (0: absent from the corpus)."""
        if self.searches_left <= 0:
            raise CoachError("search_budget_exhausted")
        stage, started = stage or f"search_{self.searches_used + 1}", self.deps.clock()
        details = {**details, "query": args.query, "key_phrase": args.literal_phrase}
        encoded = args.model_dump(mode="json")
        self.embedding_usage.append(None)
        try:
            result = self.deps.search(args)
            _check_search_result(args, result)
        except Exception as exc:
            code = exc.code if isinstance(exc, SearchCorpusError) else "search_unavailable"
            self.tool_calls.append(ToolCall(args=encoded, status="error", error_code=code))
            self.record(stage, started, error=code, **details)
            raise CoachError(code) from None
        self.embedding_usage[-1] = result.input_tokens
        self.tool_calls.append(ToolCall(args=encoded, status=result.status))
        if result.status == "not_ready":
            self.record(stage, started, error="corpus_not_ready", **details)
            raise CoachError("corpus_not_ready")
        corpus_count = result.literal_corpus_count if args.literal_phrase else None
        self.record(stage, started, **details, hits=[hit_summary(hit, args.literal_phrase) for hit in result.hits],
                    embedding_tokens=result.input_tokens, embedding_model=result.model,
                    search_mode=result.search_mode, literal_candidate_count=result.literal_candidate_count,
                    corpus_count=corpus_count, query_policy=policy)
        return SearchOutcome(list(result.hits), corpus_count)

    def record(self, stage: str, started: float | None = None, *, error: str | None = None, **details) -> None:
        """Append one trace span; started defaults to now (a zero-length step)."""
        now = self.deps.clock()
        if error:
            details["error_code"] = error
        self.trace.append(TraceSpan(stage=stage, status="error" if error else "ok",
                                    elapsed_ms=max(0.0, (now - (now if started is None else started)) * 1000),
                                    details=details))

    # ----------------------------------------------------------- outcome
    @property
    def elapsed_ms(self) -> float:
        return max(0.0, (self.deps.clock() - self.started) * 1000)

    def snapshot(self, *, shared: bool) -> SharedPrefix:
        """Freeze this session as the prefix of later sessions; shared marks its steps as counted in both systems."""
        trace = tuple(span.model_copy(update={"details": {**span.details, "shared": True}}) if shared else span
                      for span in self.trace)
        return SharedPrefix(trace, tuple(self.tool_calls), tuple(self.chat_usage), tuple(self.embedding_usage),
                            self.elapsed_ms)

    def result(self, variant: str, status: str, *, error_code: str | None = None,
               expressions: list[ExpressionItem] | None = None, note: str | None = None) -> RunResult:
        """The outcome, counting the carried prefix (if any) before this session's own steps."""
        prefix = self.prefix or SharedPrefix((), (), (), (), 0.0)
        chat_usage = [*prefix.chat_usage, *self.chat_usage]
        return RunResult(
            request_id=str(uuid4()), variant=variant, status=status, answer=render_answer(expressions, note),
            expressions=expressions, model_rounds=len(chat_usage), tool_calls=[*prefix.tool_calls, *self.tool_calls],
            trace=[*prefix.trace, *self.trace], elapsed_ms=prefix.elapsed_ms + self.elapsed_ms,
            usage=Usage(
                input_tokens=_total(u.input_tokens for u in chat_usage),
                output_tokens=_total(u.output_tokens for u in chat_usage),
                embedding_tokens=_total([*prefix.embedding_usage, *self.embedding_usage]),
                cached_input_tokens=_total(u.cached_input_tokens for u in chat_usage),
                reported_chat_calls=sum(u.input_tokens is not None and u.output_tokens is not None
                                        for u in chat_usage),
                total_chat_calls=len(chat_usage),
            ),
            error_code=error_code, source_availability_note=note,
        )

    def _complete(self, prompt: str, payload: str, schema_format: dict) -> ChatCompletion:
        observed = getattr(self.deps.model, "complete_with_usage", None)
        if callable(observed):
            response = observed(system_prompt=prompt, user_payload=payload, response_format=schema_format)
            if not isinstance(response, ChatCompletion):
                raise TypeError("Expected ChatCompletion.")
            return response
        return ChatCompletion(self.deps.model.complete(system_prompt=prompt, user_payload=payload))


def _total(values) -> int | None:
    values = list(values)
    return None if any(value is None for value in values) else sum(values)


def _check_search_result(args: SearchCorpusArgs, result: SearchCorpusResult) -> None:
    if not isinstance(result, SearchCorpusResult) or len(result.hits) > args.limit:
        raise ValueError("Invalid search result.")
    if len({hit.chunk_id for hit in result.hits}) != len(result.hits):
        raise ValueError("Duplicate search result ID.")
    if args.document_ids is not None and any(hit.document_id not in args.document_ids for hit in result.hits):
        raise ValueError("Search returned a document outside the fixed source restriction.")
    if args.feed_ids is not None and any(hit.feed_id not in args.feed_ids for hit in result.hits):
        raise ValueError("Search returned a passage outside the requested show.")
    for hit in result.hits:
        source_length(hit)
