"""Three-vote LLM judging with a resumable call log.

A judgment unit is (kind, payload). Its id hashes the kind, the prompt, the JSON schema,
the payload and the judge model, so an unchanged unit is never judged twice: every vote is
appended to calls.jsonl and reused on the next run. Votes are combined by majority (2 of 3).

The judge defaults to the pinned OpenAI snapshot; JUDGE_PROVIDER, JUDGE_MODEL and
JUDGE_EFFORT select another one (for example Claude) without touching the chat model.
"""

import hashlib
import json
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from translation_agent_demo.config import EFFORTS, PROVIDERS, choice, environment_values, settings_for
from translation_agent_demo.errors import ConfigurationError
from translation_agent_demo.providers import chat_model

VOTES = 3
ERROR_CHARS = 400  # enough for a provider's own error message and request id


def sha(value) -> str:
    data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


JUDGE_MODEL = "gpt-5.4-mini-2026-03-17"  # default judge: pinned OpenAI snapshot


@dataclass(frozen=True)
class JudgeConfig:
    """Which model judges: JUDGE_PROVIDER, JUDGE_MODEL and optional JUDGE_EFFORT (Claude only)."""

    provider: str = "openai"
    model: str = JUDGE_MODEL
    effort: str | None = None

    @property
    def unit_key(self) -> str:
        """The judge identity inside every unit id: the model, plus the effort when one is set."""
        return self.model if self.effort is None else f"{self.model}@effort={self.effort}"


def judge_config(values: Mapping[str, str]) -> JudgeConfig:
    provider = choice(values, "JUDGE_PROVIDER", PROVIDERS, "openai")
    model = values.get("JUDGE_MODEL", "").strip()
    if provider == "google" and not model:
        raise ConfigurationError("Set JUDGE_MODEL for JUDGE_PROVIDER=google.")
    if provider == "anthropic" and not model:
        raise ConfigurationError("Set JUDGE_MODEL (for example claude-sonnet-5-5) for JUDGE_PROVIDER=anthropic.")
    effort = choice(values, "JUDGE_EFFORT", EFFORTS) if provider == "anthropic" else None
    return JudgeConfig(provider, model or JUDGE_MODEL, effort)


@lru_cache(maxsize=1)
def current_judge() -> JudgeConfig:
    """The judge from the demo .env and os.environ, resolved once so a whole grading run uses one judge."""
    return judge_config(environment_values())


def make_unit(kind: str, prompt: str, schema: dict, payload: dict, judge: JudgeConfig | None = None) -> dict:
    """A cached vote is reused only for the same kind, prompt, schema, payload and judge model."""
    judge = judge or current_judge()
    return {"id": sha([kind, sha(prompt), sha(schema), payload, judge.unit_key]), "kind": kind, "payload": payload}


def majority(values) -> str:
    """The most common verdict if at least two of three votes agree; otherwise uncertain."""
    counts = Counter(v for v in values if v is not None)
    if not counts:
        return "uncertain"
    value, count = counts.most_common(1)[0]
    return value if count >= 2 else "uncertain"


class Judge:
    """The configured judge model with a strict JSON schema per kind and one bounded retry.

    settings are the chat settings; an OpenAI judge reuses their endpoint only when chat is
    on OpenAI too, otherwise it uses the OpenAI key (see config.settings_for)."""

    def __init__(self, settings, prompts: dict, schemas: dict, *, max_completion_tokens: int = 1600,
                 config: JudgeConfig | None = None, values: Mapping[str, str] | None = None):
        self.config = config or current_judge()
        judge_settings = settings_for(settings, self.config.provider, self.config.model,
                                      effort=self.config.effort, values=values)
        # Thinking counts toward Claude's max_tokens, so a Claude judge keeps the provider's larger default cap.
        cap = None if self.config.provider == "anthropic" else max_completion_tokens
        self.model = chat_model(judge_settings, max_output_tokens=cap)
        self.prompts, self.schemas = prompts, schemas

    def __call__(self, kind: str, payload: dict) -> dict:
        response_format = {"type": "json_schema", "json_schema": {
            "name": f"{kind}_verdict", "strict": True, "schema": self.schemas[kind]}}
        error = None
        for _ in range(2):
            try:
                response = self.model.complete_with_usage(
                    system_prompt=self.prompts[kind], user_payload=json.dumps(payload, ensure_ascii=False),
                    response_format=response_format)
                return {"content": response.content, "model": response.model, "usage": vars(response.usage)}
            except Exception as exc:  # transport, HTTP or malformed provider response
                error = str(exc)[:ERROR_CHARS]
        raise RuntimeError(error or "transport_error")


class CallLog:
    """Append-only judge-call cache: one JSON line per (unit, vote) attempt."""

    def __init__(self, path: Path):
        self.path, self.lock = path, threading.Lock()
        self.entries = defaultdict(list)
        if path.exists():
            for line in path.read_text().splitlines():
                entry = json.loads(line)
                self.entries[(entry["unit"], entry["vote"])].append(entry)

    def done(self, unit_id: str, vote: int) -> bool:
        return any(e["status"] == "ok" for e in self.entries[(unit_id, vote)])

    def ok(self, unit_id: str) -> list[dict]:
        return [next(e for e in self.entries[(unit_id, v)] if e["status"] == "ok")
                for v in range(VOTES) if self.done(unit_id, v)]

    def append(self, entry: dict) -> None:
        with self.lock, self.path.open("a") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.entries[(entry["unit"], entry["vote"])].append(entry)

    def missing(self, units: dict) -> int:
        return sum(not self.done(u, v) for u in units for v in range(VOTES))

    def usage(self) -> dict:
        totals = Counter()
        for entries in self.entries.values():
            for entry in entries:
                if entry["status"] == "ok":
                    for key in ("input_tokens", "output_tokens"):
                        totals[key] += entry["usage"].get(key) or 0
        return dict(totals)

    def votes(self, unit: dict, fields) -> list[dict]:
        """Parsed votes for one unit; a vote whose JSON lacks the expected fields is dropped."""
        parsed = []
        for entry in self.ok(unit["id"]):
            try:
                value = json.loads(entry["content"])
                if set(value) == set(fields):
                    parsed.append(value)
            except (ValueError, TypeError):
                pass
        return parsed


def run_units(units: dict, log: CallLog, judge, workers: int) -> Counter:
    """Fill every missing vote; a transport failure stays visible and is retried only on resume."""
    pending = [(u, v) for u in units.values() for v in range(VOTES) if not log.done(u["id"], v)]

    def call(item):
        unit, vote = item
        started = time.monotonic()
        entry = {"unit": unit["id"], "kind": unit["kind"], "vote": vote,
                 "recorded_at": datetime.now(timezone.utc).isoformat()}
        try:
            entry.update(status="ok", **judge(unit["kind"], unit["payload"]))
        except Exception as exc:
            entry.update(status="error", error=str(exc)[:ERROR_CHARS])
        entry["elapsed_ms"] = (time.monotonic() - started) * 1000
        log.append(entry)
        return entry["status"]

    statuses = Counter()
    with ThreadPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(call, item) for item in pending]):
            statuses[future.result()] += 1
            if sum(statuses.values()) % 200 == 0:
                print(json.dumps({"calls": dict(statuses), "scheduled": len(pending)}), flush=True)
    return statuses
