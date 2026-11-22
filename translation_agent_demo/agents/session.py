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

Every trace step says when it started (details.started_ms): milliseconds since the request's first
session started; a continuation counts from the carried prefix's end (prefix.elapsed_ms).

Independent searches can overlap (CoachDependencies.search_workers > 1): prefetching() starts a step's
known searches at once and search() takes each result in the order it is asked, so trace, budgets and
results are the sequential ones. The session's bookkeeping is guarded by a lock (thread-safe).
"""

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Callable, Iterator, TypeVar
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
    search_workers: int = 1  # a step's searches run at once (more than 1: the search tool must be thread-safe)

    def __post_init__(self):
        if type(self.search_workers) is not int or not 1 <= self.search_workers <= 9:
            raise ValueError("search_workers must be 1 to 9.")


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
        self.offset_ms = self.prefix.elapsed_ms if self.prefix else 0.0  # where this session starts in the request
        self.trace: list[TraceSpan] = []
        self.tool_calls: list[ToolCall] = []
        self.chat_usage: list[ModelUsage] = []
        self.embedding_usage: list[int | None] = []  # one entry per search started (its budget is taken then)
        self.dropped: list[dict] = []  # {step, slot, reason, list, index, field, error} not yet shown
        self._lock = threading.RLock()
        self._prefetched: dict[str, list[Future]] = {}  # searches started early, by their arguments

    # ----------------------------------------------------------- budgets
    @property
    def model_calls_used(self) -> int:
        return len(self.chat_usage)

    @property
    def model_calls_left(self) -> int:
        return self.budget.model_calls - self.model_calls_used

    @property
    def searches_used(self) -> int:
        return len(self.embedding_usage)

    @property
    def searches_left(self) -> int:
        return self.budget.searches - self.searches_used

    # ----------------------------------------------------------- tools
    def ask(self, stage: str, prompt: str, payload: dict, schema: type[T]) -> T:
        """One budgeted model call, decoded against the schema (structured outputs) and validated.

        Invalid list items are dropped and recorded; any other mismatch fails the step."""
        with self._lock:
            if self.model_calls_left <= 0:
                raise CoachError("model_budget_exhausted")
            started, position = self.deps.clock(), len(self.chat_usage)
            self.chat_usage.append(ModelUsage())
        try:
            response = self._complete(prompt, json.dumps(payload, ensure_ascii=False), response_format(schema))
            with self._lock:
                self.chat_usage[position] = response.usage
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
        with self._lock:
            self.dropped += [{"step": stage, "slot": item.get("slot"), "reason": drop_reason(item),
                              **{key: item.get(key) for key in ("list", "index", "field", "error")}}
                             for item in dropped]
        self.record(stage, started, model=response.model, input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens, output=parsed.model_dump(mode="json"), **details)
        return parsed

    def take_dropped(self) -> list[dict]:
        """Items dropped since the last take: what the next decision call is told it lost."""
        with self._lock:
            dropped, self.dropped = self.dropped, []
        return dropped

    @contextmanager
    def prefetching(self, searches: list[SearchCorpusArgs]) -> Iterator[None]:
        """Start at most searches_left of these searches at once (with 2+ workers) for search() to take inside
        the block; one not taken by its end is dropped, uncounted. Other searches call the tool as usual. For 2+
        searches a tool's prepare(searches) runs first (the app's: one embedding call); its failure is ignored."""
        searches = list(searches)[:max(0, self.searches_left)]
        prepare = getattr(self.deps.search, "prepare", None)
        if callable(prepare) and len(searches) > 1:
            with suppress(Exception):
                prepare(searches)
        workers = min(self.deps.search_workers, len(searches))
        if workers > 1:
            pool = ThreadPoolExecutor(workers, thread_name_prefix="coach-search")
            with self._lock:
                for args in searches:
                    self._prefetched.setdefault(args.model_dump_json(), []).append(pool.submit(self._call_search, args))
            pool.shutdown(wait=False)  # the submitted searches still run; nothing waits for them here
        try:
            yield
        finally:
            with self._lock:
                self._prefetched.clear()

    def search(self, args: SearchCorpusArgs, *, policy: str, stage: str | None = None,
               **details) -> SearchOutcome:
        """One budgeted corpus search; the result is checked before anyone sees it.

        details (for example the slot it is for) are added to the trace step, with corpus_count:
        the whole-corpus number of chunks containing the literal phrase (0: absent from the corpus)."""
        with self._lock:
            if self.searches_left <= 0:
                raise CoachError("search_budget_exhausted")
            stage, position = stage or f"search_{self.searches_used + 1}", len(self.embedding_usage)
            self.embedding_usage.append(None)
            waiting = self._prefetched.get(args.model_dump_json())
            prefetched = waiting.pop(0) if waiting else None
        details = {**details, "query": args.query, "key_phrase": args.literal_phrase}
        encoded = args.model_dump(mode="json")
        started, ended, result, failure = prefetched.result() if prefetched else self._call_search(args)
        if failure is not None:
            code = failure.code if isinstance(failure, SearchCorpusError) else "search_unavailable"
            with self._lock:
                self.tool_calls.append(ToolCall(args=encoded, status="error", error_code=code))
            self.record(stage, started, ended=ended, error=code, **details)
            raise CoachError(code) from None
        with self._lock:
            self.embedding_usage[position] = result.input_tokens
            self.tool_calls.append(ToolCall(args=encoded, status=result.status))
        if result.status == "not_ready":
            self.record(stage, started, ended=ended, error="corpus_not_ready", **details)
            raise CoachError("corpus_not_ready")
        corpus_count = result.literal_corpus_count if args.literal_phrase else None
        self.record(stage, started, ended=ended, **details,
                    hits=[hit_summary(hit, args.literal_phrase) for hit in result.hits],
                    embedding_tokens=result.input_tokens, embedding_model=result.model,
                    search_mode=result.search_mode, literal_candidate_count=result.literal_candidate_count,
                    corpus_count=corpus_count, query_policy=policy)
        return SearchOutcome(list(result.hits), corpus_count)

    def _call_search(self, args: SearchCorpusArgs) -> tuple[float, float, SearchCorpusResult | None, Exception | None]:
        """The tool call and its check: (started, ended, result, failure); touches no session state."""
        started = self.deps.clock()
        try:
            result = self.deps.search(args)
            _check_search_result(args, result)
        except Exception as exc:
            return started, self.deps.clock(), None, exc
        return started, self.deps.clock(), result, None

    def record(self, stage: str, started: float | None = None, *, ended: float | None = None,
               error: str | None = None, **details) -> None:
        """Append one trace span; started defaults to now (a zero-length step), ended to now.

        details.started_ms: when it started, in milliseconds since the request started (offset_ms)."""
        now = self.deps.clock() if ended is None else ended
        start = now if started is None else started
        if error:
            details["error_code"] = error
        details["started_ms"] = round(self.offset_ms + max(0.0, (start - self.started) * 1000), 1)
        span = TraceSpan(stage=stage, status="error" if error else "ok", elapsed_ms=max(0.0, (now - start) * 1000),
                         details=details)
        with self._lock:
            self.trace.append(span)

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
