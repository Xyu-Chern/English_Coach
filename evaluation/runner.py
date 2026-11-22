"""Run both systems on every task N times (3 by default), each time from one shared first stage.

Flow
    Runner.run()     every pending unit (task, repeat), in a fixed shuffled order, in a thread pool
    Runner.unit()    record the unit's start, try it, then append one row per system at once
    PairAttempt()    the shared first stage (the prefix) once: candidates, 6 searches, first selection, verification;
                     then the baseline and the agent concurrently, each from its own deep copy of the
                     draft with its own call recorder and database connection; every call is priced

Files
    <run_dir>/manifest.json            what this run is (tasks, systems, code, models, corpus)
    <run_dir>/code.diff                the working-tree diff against the recorded commit
    <run_dir>/unit-starts.jsonl        one line per (task, repeat), written before any paid call
    <run_dir>/<system>/attempts.jsonl  each system's finished attempt: answer, trace, replay data, cost

A system's latency (result.elapsed_ms) is the prefix plus its own continuation; wall_elapsed_ms
is the whole unit. Both rows of a unit are serialized first and then appended under one lock, so a
unit is either complete (a row for every system) or was interrupted.

A unit that hits an infrastructure failure in its prefix or either system (a rate limit that
outlasted the SDK's retries, a database or embedding outage) is rerun whole, up to UNIT_TRIES
times, so the systems stay matched; the row keeps the discarded tries and their cost. A run
resumes where it stopped: complete units are skipped and units never started run. It refuses to
continue if the code, tasks, models or corpus changed, or if a unit started without a row for
every system: its paid outcome is unknown, so it is never silently repeated.
"""

import fcntl
import hashlib
import json
import os
import random
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from translation_agent_demo.agents import SYSTEMS as CODE_SYSTEMS, CoachDependencies, answer_pair

from .costs import estimate_calls
from .recording import RecordingModel
from .snapshot_search import SnapshotSearch
from .tasks import EvalTask

ROOT = Path(__file__).resolve().parent.parent
SYSTEMS = tuple(CODE_SYSTEMS)  # ("baseline", "agent"), in the order results are reported
# Every file that can change an answer or its cost; a run refuses to resume if any of them changed.
# The coach's modules are listed recursively: its systems, tools, prompts and schemas live in subpackages.
SOURCES = sorted([*(str(p.relative_to(ROOT)) for p in (ROOT / "translation_agent_demo/agents").rglob("*.py")),
                  *(f"evaluation/{name}.py" for name in ("runner", "live", "snapshot_search", "snapshot_store",
                                                         "recording", "freeze", "tasks", "costs")),
                  "evaluation/data/tasks.jsonl", "evaluation/data/pricing.json", "translation_agent_demo/config.py",
                  "translation_agent_demo/providers/anthropic_chat.py",
                  "translation_agent_demo/providers/google_chat.py",
                  "translation_agent_demo/providers/responses.py",
                  "translation_agent_demo/providers/local_embeddings.py",
                  "translation_agent_demo/providers/openai_compatible.py",
                  "translation_agent_demo/providers/openai_embeddings.py",
                  "translation_agent_demo/providers/embeddings.py", "translation_agent_demo/providers/google_embeddings.py",
                  "translation_agent_demo/storage/postgres.py", "translation_agent_demo/storage/retrieval.py",
                  "translation_agent_demo/tools/search_corpus.py"])
CODE_PATHS = ("translation_agent_demo", "evaluation")  # what code.diff and the untracked hashes cover
# Manifest keys a resume may differ in: the first session's code record and worker count, and
# the judge configured at the start (it changes no attempt; grading checks it, grader.check_judge).
UNCHECKED = {"git", "workers", "judge"}
# Failures of the environment, not of a system's output. Five units in a row stop the run.
INFRASTRUCTURE_ERRORS = {"model_unavailable", "search_unavailable", "storage_unavailable", "embedding_unavailable",
                         "corpus_not_ready", "exception"}
STOP_AFTER_CONSECUTIVE_INFRASTRUCTURE_ERRORS = 5
# A unit whose prefix or either system ends with an infrastructure failure is rerun whole (a fresh
# prefix and both systems, so they stay matched) after a short wait, at most this many times in
# all. Refusals and other model errors are a system's own result and are never retried.
UNIT_TRIES = 3
RETRY_WAIT_SECONDS = (15.0, 45.0)

Outcome = dict[str, tuple[dict, dict]]  # system -> (result, cost)


@dataclass(frozen=True)
class RunPlan:
    tasks: list[EvalTask]
    repeats: int = 3  # pass@3 and pass^3
    seed: int = 20261116
    workers: int = 6  # units in flight; each runs both systems side by side

    def schedule(self) -> list[tuple[EvalTask, int]]:
        """Every (task, repeat), shuffled so the repeats of a task do not run back to back."""
        units = [(task, attempt) for task in self.tasks for attempt in range(1, self.repeats + 1)]
        random.Random(self.seed).shuffle(units)
        return units


class Runner:
    """One run directory: its manifest, its lock and the rows of every unit."""

    def __init__(self, plan: RunPlan, run_dir: Path, attempt: Callable[[EvalTask], Outcome] | None, manifest: dict,
                 *, code_diff: str = "", systems: tuple[str, ...] = SYSTEMS):
        """attempt runs one unit (PairAttempt; None when only preparing). code_diff is written as code.diff
        when the run is created. systems: what this directory holds; a resume with others is refused."""
        self.plan, self.run_dir, self.attempt, self.code_diff = plan, run_dir, attempt, code_diff
        self.systems = _known(systems)
        manifest = {**manifest, "systems": list(self.systems), "repeats": plan.repeats, "seed": plan.seed,
                    "workers": plan.workers, "tasks": {t.id: asdict(t) for t in plan.tasks}}
        self.manifest = json.loads(json.dumps(manifest))  # as stored on disk (tuples become lists), so a resume compares equal
        self.starts = run_dir / "unit-starts.jsonl"
        self.outputs = {system: run_dir / system / "attempts.jsonl" for system in self.systems}
        self.write_lock = threading.Lock()
        self.stop, self.streak = threading.Event(), 0  # consecutive units with an infrastructure failure

    def run(self, max_new: int | None = None) -> Counter:
        """Run pending units in a thread pool; returns row counts as '<system>/<status>' (and not_started units)."""
        self.prepare()
        try:
            pending = self.pending(max_new)
            print(json.dumps({"units": len(self.plan.schedule()), "pending": len(pending),
                              "workers": self.plan.workers}), flush=True)
            statuses = self._run_pool(pending)
            if self.stop.is_set():
                raise SystemExit(f"Stopped after {STOP_AFTER_CONSECUTIVE_INFRASTRUCTURE_ERRORS} units in a row with "
                                 f"an infrastructure failure; {statuses.get('not_started', 0)} units were not started.")
            return statuses
        finally:
            self.close()

    def prepare(self) -> None:
        """Create the run directory and lock it; refuse if an existing run had a different manifest."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock = (self.run_dir / ".lock").open("w")
        fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = self.run_dir / "manifest.json"
        if path.exists():
            if _checked(json.loads(path.read_text())) != _checked(self.manifest):
                self.close()
                raise SystemExit("The code, tasks, models or corpus changed since this run started; "
                                 "use a new run directory.")
            return
        (self.run_dir / "code.diff").write_text(self.code_diff)
        path.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n")

    def pending(self, max_new: int | None = None) -> list[tuple[EvalTask, int]]:
        """Units not yet complete; refuses if any unit started without a row for every system."""
        rows = [_keys(path) for path in self.outputs.values()]
        done = set.intersection(*rows)
        unfinished = sorted((_keys(self.starts) | set.union(*rows)) - done)
        if unfinished:
            raise SystemExit(f"{len(unfinished)} unit(s) started without a row for every system, e.g. "
                             f"{unfinished[0]}: their paid outcome is unknown, so they are not repeated. "
                             "Continue in a new run directory.")
        return [(task, attempt) for task, attempt in self.plan.schedule() if (task.id, attempt) not in done][:max_new]

    def close(self) -> None:
        """Release the run-directory lock."""
        if getattr(self, "_lock", None):
            self._lock.close()
            self._lock = None

    def unit(self, task: EvalTask, attempt: int) -> dict[str, str]:
        """One unit: record its start, run it (retrying infrastructure failures), append both rows. Returns statuses."""
        if self.stop.is_set():
            return {}
        with self.write_lock:
            _append(self.starts, {"task_id": task.id, "attempt": attempt, "started_at": _now()})
        outcome, discarded, elapsed_ms = self._tries(task, attempt)
        unit = {"task_id": task.id, "attempt": attempt, "category": task.category, "recorded_at": _now(),
                "wall_elapsed_ms": elapsed_ms, "unit_tries": len(discarded) + 1, "discarded_tries": discarded}
        self._write_rows(unit, outcome)
        for system in self.systems:  # say why at once: a bad key, a rejected schema and a rate limit look alike
            result = outcome[system][0]
            if result.get("error_code"):
                print(json.dumps({"unit": f"{task.id}/{attempt}", "system": system, "error_code": result["error_code"],
                                  "detail": _failure_detail(result)}), flush=True)
        return {system: outcome[system][0].get("status", "error") for system in self.systems}

    def _run_pool(self, pending: list[tuple[EvalTask, int]]) -> Counter:
        statuses, finished = Counter(), 0
        pool = ThreadPoolExecutor(self.plan.workers)
        try:
            for future in as_completed([pool.submit(self.unit, *unit) for unit in pending]):
                outcome = future.result()
                statuses.update([f"{system}/{status}" for system, status in outcome.items()] or ["not_started"])
                finished += 1
                if finished % 10 == 0:
                    print(json.dumps({"units_done": finished, "status": dict(statuses)}), flush=True)
        except BaseException:  # Ctrl-C or a crash: running units finish and are written; queued ones never start
            self.stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown(wait=True)
        return statuses

    def _tries(self, task: EvalTask, attempt: int) -> tuple[Outcome, list[dict], float]:
        """The unit's last try, the discarded ones (with their cost) and the last try's wall time in ms."""
        discarded: list[dict] = []
        for try_ in range(1, UNIT_TRIES + 1):
            begin = time.monotonic()
            outcome = self._try(task)
            failing = _infrastructure_codes(outcome)
            if not failing or try_ == UNIT_TRIES or self.stop.is_set():
                break
            discarded.append({"try": try_, "error_codes": failing,
                              "detail": {s: _failure_detail(outcome[s][0]) for s in failing},
                              "cost": {s: outcome[s][1] for s in self.systems}})
            print(json.dumps({"unit": f"{task.id}/{attempt}", "retry": try_, "error_codes": failing}), flush=True)
            time.sleep(RETRY_WAIT_SECONDS[min(try_, len(RETRY_WAIT_SECONDS)) - 1])
        return outcome, discarded, (time.monotonic() - begin) * 1000

    def _try(self, task: EvalTask) -> Outcome:
        """One run of the unit; an exception (or a missing system) becomes an infrastructure failure in every system."""
        try:
            outcome = self.attempt(task)
            if set(outcome) != set(self.systems):
                raise RuntimeError(f"attempt returned systems {sorted(outcome)}, expected {sorted(self.systems)}")
            return outcome
        except Exception as exc:
            failed = {"status": "error", "error_code": "exception", "exception": type(exc).__name__,
                      "trace": [], "usage": {}}
            return {s: ({**failed, "variant": s}, {"workflow": {"usd": None, "status": "unknown"}})
                    for s in self.systems}

    def _write_rows(self, unit: dict, outcome: Outcome) -> None:
        """Every system's row, serialized before any is written so a bad row cannot leave the unit half written."""
        lines = {system: _line({**unit, "variant": system, "result": outcome[system][0], "cost": outcome[system][1]})
                 for system in self.systems}
        with self.write_lock:
            for system, line in lines.items():
                _append_line(self.outputs[system], line)
            self.streak = self.streak + 1 if _infrastructure_codes(outcome) else 0
            if self.streak >= STOP_AFTER_CONSECUTIVE_INFRASTRUCTURE_ERRORS:
                self.stop.set()


class PairAttempt:
    """One unit against the configured model and the verified snapshot, recorded for replay.

    The prefix and each system get their own call recorder and their own search with its own
    database connection, so the continuations share no mutable state when run concurrently.
    The chat and embedding clients are stateless per call and shared."""

    def __init__(self, environment, pricing: dict, systems: tuple[str, ...] = SYSTEMS):
        self.environment, self.pricing, self.systems = environment, pricing, _known(systems)
        self.model, self.embeddings = environment.chat_model(), environment.embeddings()

    def __call__(self, task: EvalTask) -> Outcome:
        parts = ("prefix", *self.systems)
        with ExitStack() as stack:
            searches = {p: SnapshotSearch(stack.enter_context(self.environment.store()), self.embeddings) for p in parts}
            models = {p: RecordingModel(self.model) for p in parts}
            deps = {p: CoachDependencies(models[p], searches[p]) for p in parts}
            results = answer_pair(deps["prefix"], task.question, continuations={s: deps[s] for s in self.systems},
                                  concurrent=getattr(self.environment, "parallel_continuations", True))
        if set(results) != set(self.systems):  # a system without its own recorder would mix into the prefix's record
            raise RuntimeError(f"answer_pair returned {sorted(results)}, expected {sorted(self.systems)}")
        prefix = (_shared(models["prefix"].events), _shared(searches["prefix"].observations))
        return {name: self.record(result.model_dump(mode="json"), prefix, models[name].events,
                                  searches[name].observations) for name, result in results.items()}

    def record(self, result: dict, prefix: tuple[list, list], events: list, observations: list) -> tuple[dict, dict]:
        """Attach the replay data (the prefix's calls and searches first, marked shared) and price it."""
        events = [{**event, "call_index": i} for i, event in enumerate([*prefix[0], *events], 1)]
        observations = [*prefix[1], *observations]
        result["usage"]["embedding_tokens"] = _embedding_tokens(observations)  # paid even if the database failed
        result["retrieval_observations"], result["model_events"] = observations, events
        cost = {"workflow": self.price(events, observations), "shared_prefix": self.price(*prefix)}
        return result, cost

    def price(self, events: list, observations: list) -> dict:
        return estimate_calls(events, self.pricing, embedding_tokens=_embedding_tokens(observations))


# ------------------------------------------------------------------ manifest
def source_hashes() -> dict:
    return {name: file_sha256(ROOT / name) for name in SOURCES}


def git_state() -> tuple[dict, str]:
    """The code a run used: (record, diff). A run does not need a clean tree.

    The record holds the commit, the sha256 of `git diff HEAD` over the code paths (saved as
    code.diff) and the sha256 of every untracked, not ignored file there, so the exact code
    can be checked or rebuilt later."""

    def git(*args) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout

    diff = git("diff", "HEAD", "--", *CODE_PATHS)
    untracked = git("ls-files", "--others", "--exclude-standard", "--", *CODE_PATHS).splitlines()
    record = {"commit": git("rev-parse", "HEAD").strip(), "diff_sha256": _sha256(diff.encode()),
              "untracked_sha256": {path: file_sha256(ROOT / path) for path in sorted(untracked)}}
    return record, diff


def file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


# ------------------------------------------------------------------ helpers
def _known(systems) -> tuple[str, ...]:
    """The requested systems in report order; an unknown or empty selection is refused before any call."""
    systems = tuple(systems)
    unknown = set(systems) - set(SYSTEMS)
    if unknown or not systems:
        raise ValueError(f"Unknown or empty systems {sorted(unknown)}; choose from {list(SYSTEMS)}.")
    return tuple(s for s in SYSTEMS if s in systems)


def _infrastructure_codes(outcome: Outcome) -> dict[str, str]:
    """system -> error code, for the systems that ended with an infrastructure failure."""
    return {s: r["error_code"] for s, (r, _) in outcome.items() if r.get("error_code") in INFRASTRUCTURE_ERRORS}


def _failure_detail(result: dict) -> str | None:
    """The provider's own error text of the last failed model call, or the exception's type."""
    failed = [e for e in result.get("model_events") or [] if e.get("status") == "error"]
    return (failed[-1].get("error_detail") if failed else None) or result.get("exception")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked(manifest: dict) -> dict:
    return {key: value for key, value in manifest.items() if key not in UNCHECKED}


def _shared(rows: list[dict]) -> list[dict]:
    return [{**row, "shared": True} for row in rows]


def _embedding_tokens(observations: list[dict]) -> int | None:
    tokens = [o["input_tokens"] for o in observations]
    return None if None in tokens else sum(tokens)


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False) + "\n"


def _append(path: Path, row: dict) -> None:
    _append_line(path, _line(row))


def _append_line(path: Path, line: str) -> None:
    """One write and an fsync per line, so a crash leaves at most a cut-off last line (ignored by _keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def _keys(path: Path) -> set[tuple[str, int]]:
    """(task, repeat) of every complete line; a line cut off by a crash is ignored."""
    if not path.exists():
        return set()
    text = path.read_text()
    return {(r["task_id"], r["attempt"]) for r in map(json.loads, text[:text.rfind("\n") + 1].splitlines())}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
