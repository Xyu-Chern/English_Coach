"""Admin data: the one JSON file every /admin page reads, built from an evaluation run.

    python -m frontend.admin_data --results evaluation/results --run <run> \\
        --tasks evaluation/data/tasks.jsonl --out frontend/admin \\
        [--systems baseline,agent] [--coach-system baseline|agent] [--max-bytes 4000000] \\
        [--split-traces auto|always|never]

Reads   <results>/<run>/manifest.json, <run>/<system>/attempts.jsonl for each system, <run>/grades/grades.jsonl
        (+ grades/manifest.json), <run>/unit-starts.jsonl (optional) and the task file.
Writes  <out>/data.json, plus <out>/data-traces.json when the traces are split out (data.json over --max-bytes,
        or --split-traces always). Pages fetch both with relative URLs: fetch("data.json"), then
        meta.files.traces when data.traces is null.

One request here is one recorded attempt (task x attempt x system), not a learner request: the deployment keeps
no request store. The first stage is the spans marked details.shared (else the spans up to validate_select_1 or
decline) and verified_first is validate_select_1.details.verified. Records made before the verified-slot lock
stay as recorded; meta.lock says, from the traces themselves, whether the lock was applied. Pass marks are the
LLM judge's (3-vote majority), not human labels. No model, network or database calls.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluation.report import mean, nearest_rank, read_jsonl
from evaluation.viewer import show_name, stage_info

SCHEMA_VERSION = 1
DATA_FILE, TRACES_FILE = "data.json", "data-traces.json"
MAX_BYTES = 4_000_000  # data.json size target; above it the traces move to TRACES_FILE
SPLIT_CHOICES = ("auto", "always", "never")
MODES = ("baseline", "agent")
MODE_ENV, DEFAULT_MODE = "COACH_SYSTEM", "agent"
FINAL_TURN = 4  # pick_final and its steps come after the agent's 3 turns
RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
TEXT, NOTE, ASSESSMENT, QUOTE, SNIPPET = 120, 200, 240, 220, 160  # characters kept in compact details
NO_WORK = {"assemble", "continuation_skipped", "budget_exhausted"}  # after the first stage, not continuation work

MODE_TEXT = {
    "baseline": ("Baseline · 고정 워크플로",
                 "첫 단계 뒤 검증 예문이 없는 빈 슬롯만, 코드가 정한 순서(대체 표현 제안 → 검색 → 예문 선택 → 검증, "
                 "최대 3라운드)로 다시 찾는다. 검증된 슬롯은 건드리지 않고, 3개 모두 검증되면 후속을 실행하지 않는다."),
    "agent": ("Agent · 잠금",
              "첫 단계 뒤 모델이 매 턴 초안을 검토해 검색·예문 재선택·표현 교체를 고른다(최대 3턴 + 마지막 선택). "
              "잠금 규칙: 첫 단계에서 검증된 슬롯은 고정되어 그 슬롯의 repick/replace는 noop(locked)로 기록되고 "
              "예산을 쓰지 않으며, 3개 모두 검증되면 후속을 실행하지 않는다."),
}
CHANGE_HINT = ("어드민에서는 모드를 바꿀 수 없습니다. 배포 환경변수 COACH_SYSTEM을 baseline 또는 agent로 바꾸고 "
               "재배포하면 적용됩니다(기본 agent). 여기 표시된 값은 이 data.json을 만든 시점의 값입니다.")
OUTCOME_KO = {"verified": "검증 통과", "replaced": "표현만 바뀜(예문 없음)", "removed": "예문 제거",
              "kept_verified_example": "기존 검증 예문 유지(가드)"}
EXAMPLE_RULES = {
    "baseline": "examples.agent와 같은 평가 단위(task_id, attempt)의 baseline 요청.",
    "agent": "두 모드가 모두 정상(ok)이고, 첫 단계 검증이 1~2개이며, 두 모드 모두 후속을 실행해 빈 자리를 1개 이상 채웠고"
             "(added_final ≥ 1), agent가 먼저 보낸 예문을 잃지 않은(lost_first = 0) 단위 중 min(두 모드 added_final)이 "
             "가장 큰 단위, 같으면 합이 큰 단위, 그래도 같으면 과제 파일 순서·회차가 앞선 단위. 없으면 조건을 "
             "(첫 단계 1~2개·두 모드 후속 실행) → (두 모드 정상) 순으로 줄인다.",
    "skipped": "첫 단계에서 3개 모두 검증되어 후속을 생략한(continuation = skipped) 정상 요청 중 과제 파일 순서·회차가 "
               "가장 앞선 agent 요청. agent에 없으면(잠금 전 기록) 같은 규칙의 baseline 요청.",
}


# ---------- the contract (typed; validated before anything is written) ----------

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Tokens(Model):
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    total: int = Field(ge=0)


class Span(Model):
    id: str
    stage: str
    label: str
    kind: Literal["llm", "search", "verify", "decision", "assemble", "decline", "budget", "noop"]
    phase: Literal["first", "continuation"]
    turn: int | None
    start_ms: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    status: Literal["ok", "error", "skipped", "noop"]
    locked: bool
    tokens: Tokens | None
    summary: str
    detail: dict[str, Any]


class Request(Model):
    id: str
    key: str
    task_id: str
    attempt: int
    category: str | None
    language: str | None
    expect: str | None
    question: str | None
    mode: Literal["baseline", "agent"]
    system: str
    status: Literal["ok", "declined", "error"]
    error_code: str | None
    error_phase: Literal["first", "continuation"] | None
    decline_note: str | None
    started_at: str | None
    recorded_at: str | None
    first_stage_ms: int | None
    first_response_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)
    background_ms: int = Field(ge=0)
    tokens: Tokens
    llm_calls: int = Field(ge=0)
    searches: int = Field(ge=0)
    verified_first: int | None
    verified_final: int | None
    added_final: int = Field(ge=0)
    lost_first: int = Field(ge=0)
    continuation: Literal["skipped", "ran", "none"]
    locked_noops: int = Field(ge=0)
    passed: bool | None
    strict_passed: bool | None
    grounded_good: int | None
    cost_usd: float | None


class FirstItem(Model):
    slot: int
    status: str
    verified: bool
    in_final: bool
    expression: str
    key_phrase: str | None
    note: str | None
    quote: str | None
    episode: str | None


class FinalItem(Model):
    expression: str
    key_phrase: str | None
    note: str | None
    quote: str | None
    episode: str | None
    show: str | None
    verified: bool
    added: bool
    from_first: bool


class Answer(Model):
    first: list[FirstItem]
    final: list[FinalItem]


class Dist(Model):
    n: int
    mean: float | None
    p50: int | None
    p95: int | None
    p99: int | None
    min: int | None
    max: int | None


class Rate(Model):
    passed: int
    n: int
    rate: float | None


class ModeAggregate(Model):
    requests: int
    status: dict[str, int]
    continuation: dict[str, int]
    verified_first: dict[str, int]
    first_response_ms: Dist
    first_stage_ms: Dist
    total_ms: Dist
    background_ms: Dist
    tokens_total: Dist
    cost_usd_total: float | None
    passed: Rate
    strict_passed: Rate
    added_final_total: int
    lost_first_requests: int
    locked_noops: int


class Aggregates(Model):
    rule: str
    by_mode: dict[str, ModeAggregate]


class ModeDescription(Model):
    label: str
    description: str


class ModeInfo(Model):
    current: Literal["baseline", "agent"]
    source: Literal["env", "cli", "default"]
    env_var: str
    allowed: list[str]
    default: str
    change_hint: str
    modes: dict[str, ModeDescription]


class RunInfo(Model):
    id: str
    date: str | None
    started_at: str | None
    finished_at: str | None
    model: str | None
    effort: str | None
    embedding_model: str | None
    embedding_dimensions: int | None
    snapshot_id: str | None
    tasks: int
    repeats: int | None
    systems: list[str]
    requests: int
    judge_model: str | None
    judge_protocol: str | None
    judge_votes: int | None
    commit: str | None
    derived_from: str | None
    pricing_as_of: str | None


class LockInfo(Model):
    applied: bool | None
    basis: Literal["trace", "manifest", "none"]
    note: str
    agent_requests: int
    locked_noops: int
    continuation_skipped: int
    ran_with_all_verified: int
    lost_first_requests: int


class Files(Model):
    data: str
    traces: str | None


class Meta(Model):
    schema_version: Literal[1]
    generated_at: str
    generator: str
    source: str
    run: RunInfo
    lock: LockInfo
    files: Files
    answers_scope: Literal["all"]
    example_rules: dict[str, str]
    notes: list[str]
    warnings: list[str]
    inputs: dict[str, str]


class Examples(Model):
    baseline: str | None
    agent: str | None
    skipped: str | None


class AdminData(Model):
    meta: Meta
    mode: ModeInfo
    requests: list[Request]
    traces: dict[str, list[Span]] | None
    answers: dict[str, Answer]
    examples: Examples
    aggregates: Aggregates


class TracesFile(Model):
    schema_version: Literal[1]
    run: str
    traces: dict[str, list[Span]]


# ---------- small helpers ----------

def short(text, n: int) -> str | None:
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def ms(value) -> int:
    return max(0, int(round(value or 0)))


def compact(detail: dict) -> dict:
    """Keys without a value are left out: details stay small."""
    return {k: v for k, v in detail.items() if v is not None}


def mode_of(system: str) -> str:
    if system == "baseline":
        return "baseline"
    if system.startswith("agent"):
        return "agent"
    raise ValueError(f"Unknown system {system!r}: expected baseline or agent*")


def resolve_mode(cli_value: str | None, environ=os.environ) -> tuple[str, str]:
    """(current mode, where it came from): --coach-system, else COACH_SYSTEM, else the default."""
    if cli_value is not None:
        value, source = cli_value.strip(), "cli"
    elif (environ.get(MODE_ENV) or "").strip():
        value, source = environ[MODE_ENV].strip(), "env"
    else:
        return DEFAULT_MODE, "default"
    if value not in MODES:
        raise ValueError(f"{MODE_ENV} must be one of {', '.join(MODES)}, not {value!r}")
    return value, source


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def details(span: dict) -> dict:
    value = span.get("details")
    return value if isinstance(value, dict) else {}


# ---------- one attempt ----------

def first_count(trace: list[dict]) -> int:
    """How many leading spans form the first stage: those marked shared, else up to validate_select_1/decline/an error."""
    flags = [bool(details(s).get("shared")) for s in trace]
    if any(flags):
        return next((i for i, flag in enumerate(flags) if not flag), len(flags))
    for i, span in enumerate(trace):
        if span.get("stage") in ("validate_select_1", "decline") or span.get("status") == "error":
            return i + 1
    return len(trace)


def is_locked(d: dict) -> bool:
    return d.get("noop") == "locked" or d.get("locked") is True


def kind_of(stage: str, d: dict) -> str:
    if stage == "continuation_skipped" or "noop" in d:
        return "noop"
    if stage.startswith(("agent_", "pick_final", "repick_", "replace_")):
        return "decision"
    if stage.startswith("validate"):
        return "verify"
    if stage.startswith(("candidates", "select_", "revise_")):
        return "llm"
    if stage.startswith("search_"):
        return "search"
    return {"assemble": "assemble", "decline": "decline", "budget_exhausted": "budget"}.get(stage, "decision")


def turn_of(stage: str, first: bool) -> int | None:
    """None in the first stage; the round (baseline) or turn (agent) after it; FINAL_TURN for pick_final."""
    if first:
        return None
    if "final" in stage:
        return FINAL_TURN
    match = (re.match(r"(agent|revise)_(\d+)$", stage)
             or re.match(r"(search|repick|replace|validate_agent)_(\d+)", stage))
    if match:
        return int(match.group(2))
    match = re.match(r"(select|validate_select)_(\d+)$", stage)
    return int(match.group(2)) - 1 if match else None


def label_of(stage: str) -> str:
    if stage == "continuation_skipped":
        return "후속 단계 생략"
    return stage_info(stage, "ko")[1]


def outcome_ko(outcome) -> str:
    if outcome is None:
        return "결과 없음"
    outcome = str(outcome)
    if outcome.startswith("rejected:"):
        return "거부: " + outcome.split(":", 1)[1]
    return OUTCOME_KO.get(outcome, outcome)


def summarize(stage: str, status: str, d: dict, first: bool) -> str:
    """One Korean line per span, from the recorded details only."""
    output = d.get("output") if isinstance(d.get("output"), dict) else {}
    if status == "error":
        return f"오류로 중단: {d.get('error_code') or '오류 코드 없음'}"
    if is_locked(d):
        return "고정된 슬롯이라 건너뜀 (잠금 규칙)"
    if stage == "continuation_skipped":
        return "첫 단계에서 3개 모두 검증되어 후속 단계 생략"
    if "noop" in d:
        return f"변화 없는 행동이라 건너뜀 ({d['noop']})"
    if "skipped" in d:
        return f"건너뜀 ({d['skipped']})"
    if stage.startswith("candidates"):
        if output.get("request_status") != "answerable":
            return f"요청 판정: {output.get('request_status')} → 거절 경로"
        return f"후보 표현 {len(output.get('candidates') or [])}개 생성 (유형 {output.get('kind')})"
    if stage == "decline":
        return f"거절 안내 반환 ({d.get('request_status')})"
    if stage.startswith("search_"):
        slot = d.get("slot")
        where = ("후보 검색" if first else "추가 검색") + (f" 슬롯 {slot}" if slot is not None else "")
        count = d.get("corpus_count")
        return (f"{where} '{short(d.get('key_phrase'), 40)}': 결과 {len(d.get('hits') or [])}건, "
                f"코퍼스 일치 {'-' if count is None else count}건 ({d.get('search_mode') or '-'})")
    if stage.startswith("validate"):
        slots = d.get("slots") or []
        rejected = sum(len(s.get("rejection_reasons") or []) for s in slots) + len(d.get("excluded") or [])
        return (f"코드 검증: 검증 예문 {d.get('verified')}/{len(slots)}" + (f", 거부 {rejected}건" if rejected else "")
                + (f", 가드 {len(d['guard'])}건" if d.get("guard") else "")
                + (f", 건너뛴 행동 {len(d['noops'])}건" if d.get("noops") else ""))
    if stage.startswith("select_"):
        picks = output.get("picks") or []
        with_ref = sum(1 for p in picks if p.get("ref"))
        if stage == "select_1":
            return f"예문 선택: 후보 {len(picks)}개 중 {with_ref}개에 인용 구간 지정"
        return f"교체 표현 {len(picks)}개에 예문 선택 ({with_ref}개 인용 지정)"
    if stage.startswith("revise_"):
        replacements = output.get("replacements") or []
        with_ref = sum(1 for r in replacements if r.get("ref"))
        return f"미검증 슬롯 대체 표현 {len(replacements)}개 제안" + (f" (기존 구간 바로 지정 {with_ref}개)" if with_ref else "")
    if stage.startswith("agent_") or stage == "pick_final":
        counts = Counter(a.get("type") for a in output.get("actions") or [])
        what = ", ".join(f"{k} {v}" for k, v in counts.items()) or "행동 없음"
        if stage == "pick_final":
            return f"마지막 선택 호출: {what}"
        return f"에이전트 판단: {what} → {'종료' if output.get('finish') else '계속'}"
    if stage.startswith("repick_"):
        return f"슬롯 {d.get('slot')} 예문 재선택 → {outcome_ko(d.get('outcome'))}"
    if stage.startswith("replace_"):
        return f"슬롯 {d.get('slot')} 표현 교체 '{short(d.get('expression'), 40)}' → {outcome_ko(d.get('outcome'))}"
    if stage == "assemble":
        return f"최종 답 구성: 표현 {d.get('expressions')}개, 예문 {d.get('with_example')}개"
    if stage == "budget_exhausted":
        return f"예산 소진({d.get('code')}) → 현재 초안으로 마무리"
    return stage


def detail_of(stage: str, d: dict, *, rich: bool, locked_slots: list[int] | None) -> dict:
    """A small detail per span; rich (the example requests only) keeps the model's full reasoning and the hits."""
    output = d.get("output") if isinstance(d.get("output"), dict) else {}
    out: dict[str, Any] = {"error_code": d.get("error_code")}
    if stage.startswith("candidates"):
        candidates = output.get("candidates") or []
        out.update(model=d.get("model"), request_status=output.get("request_status"), kind=output.get("kind"),
                   source_show=output.get("source_show"), status_note=short(output.get("status_note"), NOTE),
                   candidates=[compact({k: c.get(k) for k in ("expression", "key_phrase", "function")})
                               for c in candidates] if rich else [c.get("key_phrase") for c in candidates])
    elif stage == "decline":
        out.update(request_status=d.get("request_status"), note=short(d.get("note"), NOTE))
    elif stage.startswith("search_"):
        out.update(slot=d.get("slot"), query=short(d.get("query"), TEXT), key_phrase=d.get("key_phrase"),
                   hits=len(d.get("hits") or []), corpus_count=d.get("corpus_count"), search_mode=d.get("search_mode"),
                   query_policy=d.get("query_policy"), reason=d.get("reason") if rich else short(d.get("reason"), TEXT),
                   skipped=d.get("skipped"), noop=d.get("noop"))
        if rich:
            out["hit_list"] = [compact({"episode": h.get("episode_title"), "show": show_name(h.get("source_key")),
                                        "snippet": short(h.get("snippet"), SNIPPET)}) for h in d.get("hits") or []]
    elif stage.startswith("validate"):
        locked = set(locked_slots or [])
        out.update(verified=d.get("verified"),
                   slots=[compact({"slot": s.get("slot"), "status": s.get("status"), "key_phrase": s.get("key_phrase"),
                                   "rejection_reasons": s.get("rejection_reasons") or [],
                                   "locked": True if s.get("slot") in locked else None,
                                   "moved_to_end": s.get("moved_to_end"),
                                   **({"expression": s.get("expression"), "ref": s.get("ref"),
                                       "quote": short(s.get("quote"), QUOTE), "episode": s.get("episode_title")}
                                      if rich else {})})
                          for s in d.get("slots") or []],
                   excluded=len(d["excluded"]) if d.get("excluded") else None,
                   guard=len(d["guard"]) if d.get("guard") else None,
                   noops=len(d["noops"]) if d.get("noops") else None)
    elif stage.startswith("select_"):
        picks = output.get("picks") or []
        out.update(model=d.get("model"), picks=len(picks), picks_with_ref=sum(1 for p in picks if p.get("ref")))
        if rich:
            out["pick_list"] = [compact({k: p.get(k) for k in ("candidate", "ref", "expression", "key_phrase")})
                                for p in picks]
    elif stage.startswith("revise_"):
        out.update(model=d.get("model"), replacements=[
            compact({"replaces": r.get("replaces"), "key_phrase": r.get("key_phrase"), "ref": r.get("ref"),
                     **({"expression": r.get("expression")} if rich else {})})
            for r in output.get("replacements") or []])
    elif stage.startswith("agent_") or stage == "pick_final":
        assessment = output.get("assessment")
        out.update(model=d.get("model"), assessment=assessment if rich else short(assessment, ASSESSMENT),
                   finish=output.get("finish"), locked_slots=locked_slots,
                   actions=[compact({"type": a.get("type"), "slot": a.get("slot"), "key_phrase": a.get("key_phrase"),
                                     "ref": a.get("ref"),
                                     **({"query": a.get("query"), "expression": a.get("expression"),
                                         "reason": a.get("reason")} if rich else {})})
                            for a in output.get("actions") or []])
    elif stage.startswith(("repick_", "replace_")):
        out.update(action=stage.split("_", 1)[0], slot=d.get("slot"), ref=d.get("ref"), outcome=d.get("outcome"),
                   expression=short(d.get("expression"), TEXT), reason=d.get("reason") if rich else short(d.get("reason"), TEXT),
                   noop=d.get("noop"), skipped=d.get("skipped"), locked=True if is_locked(d) else None)
        if rich:
            out.update(previous_expression=d.get("previous_expression"), rejection_reasons=d.get("rejection_reasons"))
    elif stage == "assemble":
        out.update(expressions=d.get("expressions"), with_example=d.get("with_example"))
    else:
        out.update({k: v for k, v in d.items() if k != "shared" and not isinstance(v, (dict, list))})
    return compact(out)


def convert_trace(trace: list[dict], n_first: int, *, rich: bool, locked_slots: list[int] | None) -> list[dict]:
    """Spans in order; start_ms is the running sum of the rounded elapsed times (gaps between spans are not recorded)."""
    spans, clock = [], 0
    for i, span in enumerate(trace):
        stage, d, first = span.get("stage") or "?", details(span), i < n_first
        status = ("error" if span.get("status") == "error" else
                  "noop" if stage == "continuation_skipped" or "noop" in d else "skipped" if "skipped" in d else "ok")
        elapsed = ms(span.get("elapsed_ms"))
        llm = "input_tokens" in d or "output_tokens" in d
        tin, tout = d.get("input_tokens") or 0, d.get("output_tokens") or 0
        spans.append({"id": f"s{i + 1:02d}", "stage": stage, "label": label_of(stage), "kind": kind_of(stage, d),
                      "phase": "first" if first else "continuation", "turn": turn_of(stage, first),
                      "start_ms": clock, "elapsed_ms": elapsed, "status": status, "locked": is_locked(d),
                      "tokens": {"input": tin, "output": tout, "total": tin + tout} if llm else None,
                      "summary": summarize(stage, status, d, first),
                      "detail": detail_of(stage, d, rich=rich, locked_slots=None if first else locked_slots)})
        clock += elapsed
    return spans


def pair(expression, quote) -> tuple[str, str]:
    return (" ".join(str(expression or "").split()), " ".join(str(quote or "").split()))


def attempt_facts(row: dict) -> dict:
    """Everything one request row and its answers need, from one attempt record."""
    result = row.get("result") or {}
    trace = [s for s in result.get("trace") or [] if isinstance(s, dict)]
    n_first = first_count(trace)
    first, rest = trace[:n_first], trace[n_first:]
    declined = next((s for s in first if s.get("stage") == "decline"), None)
    status = "error" if result.get("status") != "ok" else "declined" if declined else "ok"
    first_validate = next((s for s in first if s.get("stage") == "validate_select_1"), None)
    verified_first = details(first_validate).get("verified") if first_validate else None
    verified_first = verified_first if isinstance(verified_first, int) else None
    first_slots = details(first_validate).get("slots") or [] if first_validate else []
    error_phase = None
    if status == "error":
        failed_first = not trace or any(s.get("status") == "error" for s in first) or first_validate is None
        error_phase = "first" if failed_first else "continuation"
    if status == "ok" or (status == "error" and error_phase == "continuation"):
        continuation = "ran" if any(s.get("stage") not in NO_WORK for s in rest) else "skipped"
    else:
        continuation = "none"

    expressions = (result.get("expressions") or []) if status == "ok" else []
    first_verified = {pair(s.get("expression"), s.get("quote")) for s in first_slots if s.get("status") == "verified"}
    final_verified = {pair(e.get("expression"), (e.get("citation") or {}).get("quote"))
                      for e in expressions if e.get("citation")}
    sent_first = status in ("ok", "error") and bool(verified_first) and error_phase != "first"
    total = ms(result.get("elapsed_ms"))
    first_stage_ms = sum(ms(s.get("elapsed_ms")) for s in first) if first else None
    first_response = min(total, first_stage_ms) if sent_first and first_stage_ms is not None else total
    usage = result.get("usage") or {}
    tin, tout = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    cost = ((row.get("cost") or {}).get("workflow") or {}).get("usd")
    candidates = next((details(s).get("output") for s in reversed(first)
                       if (s.get("stage") or "").startswith("candidates") and isinstance(details(s).get("output"), dict)),
                      None) or {}
    notes = [c.get("note") for c in candidates.get("candidates") or []]
    return {
        "trace": trace, "n_first": n_first, "status": status, "error_phase": error_phase,
        "error_code": result.get("error_code") if status == "error" else None,
        "decline_note": (details(declined).get("note") or result.get("source_availability_note")) if declined else None,
        "verified_first": verified_first, "continuation": continuation,
        "verified_final": len(final_verified) if status == "ok" else None,
        "added_final": len(final_verified - first_verified) if status == "ok" and verified_first else 0,
        "lost_first": len(first_verified - final_verified) if status == "ok" and verified_first else 0,
        "first_stage_ms": first_stage_ms, "first_response_ms": first_response, "total_ms": total,
        "background_ms": max(0, total - first_response),
        "tokens": {"input": tin, "output": tout, "total": tin + tout},
        "llm_calls": usage.get("total_chat_calls") if usage.get("total_chat_calls") is not None
        else (result.get("model_rounds") or 0),
        "searches": len(result.get("tool_calls") or []),
        "locked_noops": sum(1 for s in trace if is_locked(details(s))),  # the spans marked locked
        "cost_usd": None if cost is None else round(float(cost), 6),
        "locked_slots": sorted(s.get("slot") for s in first_slots if s.get("status") == "verified"),
        "first_items": [{
            "slot": s.get("slot") if isinstance(s.get("slot"), int) else i, "status": s.get("status") or "unknown",
            "verified": s.get("status") == "verified",
            "in_final": s.get("status") == "verified" and pair(s.get("expression"), s.get("quote")) in final_verified,
            "expression": s.get("expression") or "", "key_phrase": s.get("key_phrase"),
            "note": notes[s["candidate"]] if isinstance(s.get("candidate"), int) and s["candidate"] < len(notes) else None,
            "quote": s.get("quote"), "episode": s.get("episode_title")} for i, s in enumerate(first_slots)],
        "final_items": [{
            "expression": e.get("expression") or "", "key_phrase": e.get("key_phrase"), "note": e.get("note"),
            "quote": (e.get("citation") or {}).get("quote"), "episode": (e.get("citation") or {}).get("episode_title"),
            "show": show_name((e.get("citation") or {}).get("source_key")), "verified": bool(e.get("citation")),
            "added": bool(e.get("citation")) and bool(verified_first)
            and pair(e.get("expression"), e["citation"].get("quote")) not in first_verified,
            "from_first": bool(e.get("citation"))
            and pair(e.get("expression"), e["citation"].get("quote")) in first_verified} for e in expressions],
    }


# ---------- the run ----------

def lock_info(requests: list[dict], systems: list[str], manifest: dict) -> dict:
    """Whether the agent records follow the verified-slot lock, read from the records (the code that ran)."""
    agent = [r for r in requests if r["mode"] == "agent"]
    noops = sum(r["locked_noops"] for r in agent)
    skipped = sum(r["continuation"] == "skipped" for r in agent)
    ran_all = sum(r["status"] == "ok" and r["verified_first"] == 3 and r["continuation"] == "ran" for r in agent)
    lost = sum(r["lost_first"] > 0 for r in agent)
    declared = any("lock" in s for s in systems) or bool((manifest.get("environment") or {}).get("lock_verified"))
    if ran_all or lost:
        applied, basis = False, "trace"
        note = (f"잠금 전 기록: 첫 단계 검증이 3개인 agent 요청 {ran_all}건이 후속을 실행했고, {lost}건에서 먼저 보낸 "
                "검증 예문이 최종 답에서 빠졌다. continuation·added_final·lost_first는 기록 그대로다.")
        if declared:
            note += " 실행 기록은 잠금을 선언했지만 trace가 규칙과 맞지 않는다(확인 필요)."
    elif noops or skipped:
        applied, basis = True, "trace"
        note = (f"잠금 적용: agent의 잠긴 슬롯 대상 행동 {noops}건이 noop(locked)로 기록됐고, 3개 검증 요청 {skipped}건이 "
                "후속을 생략했다. 먼저 보낸 검증 예문이 최종에서 빠진 요청은 없다.")
    elif declared:
        applied, basis = True, "manifest"
        note = "실행 기록이 잠금 agent를 선언했다. trace에는 잠금이 작동할 상황(첫 단계 검증 1개 이상)이 없었다."
    else:
        applied, basis = None, "none"
        note = "agent 기록에 잠금 적용 여부를 판단할 근거가 없다."
    return {"applied": applied, "basis": basis, "note": note, "agent_requests": len(agent), "locked_noops": noops,
            "continuation_skipped": skipped, "ran_with_all_verified": ran_all, "lost_first_requests": lost}


def dist(values: list) -> dict:
    xs = [v for v in values if v is not None]
    if not xs:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "p99": None, "min": None, "max": None}
    return {"n": len(xs), "mean": round(mean(xs), 1), "p50": nearest_rank(xs, 0.5), "p95": nearest_rank(xs, 0.95),
            "p99": nearest_rank(xs, 0.99), "min": min(xs), "max": max(xs)}


def rate(rows: list[dict], field: str) -> dict:
    graded = [r for r in rows if r[field] is not None]
    passed = sum(bool(r[field]) for r in graded)
    return {"passed": passed, "n": len(graded), "rate": round(passed / len(graded), 4) if graded else None}


def aggregates(requests: list[dict]) -> dict:
    out = {}
    for mode in MODES:
        rows = [r for r in requests if r["mode"] == mode]
        if not rows:
            continue
        ok = [r for r in rows if r["status"] == "ok"]
        costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
        out[mode] = {
            "requests": len(rows),
            "status": {s: sum(r["status"] == s for r in rows) for s in ("ok", "declined", "error")},
            "continuation": {c: sum(r["continuation"] == c for r in rows) for c in ("skipped", "ran", "none")},
            "verified_first": {str(k): sum(r["verified_first"] == k for r in ok) for k in range(4)},
            "first_response_ms": dist([r["first_response_ms"] for r in ok]),
            "first_stage_ms": dist([r["first_stage_ms"] for r in ok]),
            "total_ms": dist([r["total_ms"] for r in ok]),
            "background_ms": dist([r["background_ms"] for r in ok if r["verified_first"] in (1, 2)]),
            "tokens_total": dist([r["tokens"]["total"] for r in ok]),
            "cost_usd_total": round(sum(costs), 6) if costs else None,
            "passed": rate(rows, "passed"), "strict_passed": rate(rows, "strict_passed"),
            "added_final_total": sum(r["added_final"] for r in rows),
            "lost_first_requests": sum(r["lost_first"] > 0 for r in rows),
            "locked_noops": sum(r["locked_noops"] for r in rows),
        }
    return {"rule": ("모드별. 시간·토큰 분포는 status = ok 요청만(거절·오류는 status 건수로만), nearest-rank 퍼센타일, "
                     "단위 ms·토큰. background_ms 분포는 첫 단계 검증 1~2개(공지가 뜨는) 정상 요청만. "
                     "verified_first 분포는 정상 요청만. passed·strict_passed는 심사된 요청 전체(거절 과제 포함)."),
            "by_mode": out}


def choose_examples(requests: list[dict], order: dict) -> dict:
    units = defaultdict(dict)
    for r in requests:
        units[(r["task_id"], r["attempt"])][r["mode"]] = r
    ordered = sorted(units, key=lambda u: (order.get(u[0], len(order)), u[0], u[1]))

    def full(b, a):
        return (b["verified_first"] in (1, 2) and b["continuation"] == "ran" and a["continuation"] == "ran"
                and b["added_final"] >= 1 and a["added_final"] >= 1 and a["lost_first"] == 0)

    def ran(b, a):
        return b["verified_first"] in (1, 2) and b["continuation"] == "ran" and a["continuation"] == "ran"

    out = {"baseline": None, "agent": None, "skipped": None}
    for condition in (full, ran, lambda b, a: True):
        pairs = [(units[u]["baseline"], units[u]["agent"]) for u in ordered
                 if {"baseline", "agent"} <= set(units[u]) and all(x["status"] == "ok" for x in units[u].values())
                 and condition(units[u]["baseline"], units[u]["agent"])]
        if pairs:
            b, a = max(pairs, key=lambda p: (min(p[0]["added_final"], p[1]["added_final"]),
                                             p[0]["added_final"] + p[1]["added_final"]))
            out["baseline"], out["agent"] = b["id"], a["id"]
            break
    for mode in MODES:  # a run without both systems: the first normal request of each
        if out[mode] is None:
            out[mode] = next((units[u][mode]["id"] for u in ordered
                              if mode in units[u] and units[u][mode]["status"] == "ok"), None)
    for mode in ("agent", "baseline"):
        found = next((units[u][mode]["id"] for u in ordered if mode in units[u]
                      and units[u][mode]["status"] == "ok" and units[u][mode]["continuation"] == "skipped"), None)
        if found:
            out["skipped"] = found
            break
    return out


def notes_for(env: dict) -> list[str]:
    return [
        "각 요청은 평가 실행의 시도 1건(과제 × 회차 × 시스템)이다. 실제 학습자 요청이 아니며, 배포는 요청을 저장하지 않는다"
        "(요청당 구조화 로그 한 줄만 남긴다).",
        "첫 단계 = details.shared 스팬(없으면 validate_select_1·decline까지). verified_first = "
        "validate_select_1.details.verified. 평가에서는 두 시스템이 같은 단위의 첫 단계를 공유했다.",
        "first_stage_ms = 첫 단계 스팬 elapsed 합(스팬 사이 오버헤드 제외). first_response_ms = 첫 단계 검증 예문이 "
        "1개 이상이면 first_stage_ms(그때 검증된 표현+예문만 먼저 보냄, D1), 0개·거절·첫 단계 오류면 total_ms"
        "(끝까지 기다려 한 번에 보냄). background_ms = total_ms − first_response_ms.",
        "total_ms = 기록된 요청 소요(result.elapsed_ms = 첫 단계 + 후속 세션). 평가 때 두 시스템의 후속은 동시에, "
        "여러 단위가 병렬 worker로 실행돼 지연에 경합이 섞였을 수 있다.",
        "continuation: ran = 첫 단계 뒤 모델 호출·검색·결정 스팬이 하나라도 있음, skipped = 첫 단계에서 끝남"
        "(assemble·continuation_skipped만), none = 거절·첫 단계 오류.",
        "added_final = 먼저 보낸 뒤(첫 단계 검증 ≥ 1) 최종 답에 새로 생긴 검증 예문 수(표현+인용 쌍 기준, '팟캐스트' 탭 "
        "추가분). lost_first = 먼저 보낸 검증 예문 중 최종 답에서 빠진 수(잠금이 적용되면 0). 검증 0개 요청은 한 번에 "
        "보내므로 added_final = 0.",
        "tokens = 채팅 모델 입력+출력(임베딩 제외). llm_calls = 채팅 모델 호출 수, searches = 검색 도구 호출 수. "
        "cost_usd = 공시 가격 기준 추정(meta.run.pricing_as_of).",
        "passed·strict_passed·grounded_good = LLM 심사 3표 다수결(사람 정답 아님). 심사가 없으면 null.",
        "trace의 start_ms = 같은 요청 안 스팬 elapsed(반올림 ms)의 순차 누적. 스팬 사이 오버헤드는 빠져 있어 마지막 스팬 "
        "끝 ≤ total_ms(반올림 오차 범위). detail에서 값이 없는 키는 생략했다.",
        f"평가 환경({env.get('model') or '-'} + {env.get('embedding_model') or '-'}, 스냅샷 "
        f"{env.get('snapshot_id') or '-'})은 배포 환경과 달라 절대 시간·토큰은 다를 수 있다.",
        "question은 과제 파일 원문 그대로다(D2). 어드민은 원문·trace를 textContent로만 그린다.",
    ]


def build(run_dir: Path, tasks_path: Path, *, mode: tuple[str, str] = (DEFAULT_MODE, "default"),
          systems: list[str] | None = None, generated_at: datetime | None = None) -> dict:
    """The whole payload (traces inline). Pure apart from reading the run and task files."""
    run_dir, tasks_path = Path(run_dir), Path(tasks_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    grades_manifest_path = run_dir / "grades" / "manifest.json"
    judge = json.loads(grades_manifest_path.read_text(encoding="utf-8")) if grades_manifest_path.exists() else {}
    systems = list(systems or manifest.get("systems") or
                   sorted((p.parent.name for p in run_dir.glob("*/attempts.jsonl")), key=lambda s: s != "baseline"))
    if not systems:
        raise ValueError(f"No <system>/attempts.jsonl in run {run_dir.name!r}")
    modes = Counter(mode_of(system) for system in systems)
    if any(n > 1 for n in modes.values()):
        raise ValueError(f"Systems {systems} give one mode twice; choose one per mode with --systems")
    for system in systems:
        if not (run_dir / system / "attempts.jsonl").is_file():
            raise ValueError(f"Missing {system}/attempts.jsonl in run {run_dir.name!r}")
    tasks = read_jsonl(tasks_path)
    by_id = {t["id"]: t for t in tasks}
    order = {t["id"]: i for i, t in enumerate(tasks)}
    grades = {g["key"]: g for g in read_jsonl(run_dir / "grades" / "grades.jsonl")}
    starts = {(s["task_id"], s["attempt"]): s.get("started_at") for s in read_jsonl(run_dir / "unit-starts.jsonl")}
    inputs = {f"{s}/attempts.jsonl": sha256(run_dir / s / "attempts.jsonl") for s in systems}
    for name in ("manifest.json", "grades/grades.jsonl", "grades/manifest.json", "unit-starts.jsonl"):
        if (run_dir / name).is_file():
            inputs[name] = sha256(run_dir / name)
    inputs[f"tasks:{tasks_path.name}"] = sha256(tasks_path)
    warnings = []
    if manifest.get("tasks_sha256") and manifest["tasks_sha256"] != inputs[f"tasks:{tasks_path.name}"]:
        warnings.append("과제 파일 해시가 실행 manifest의 tasks_sha256과 다르다(질문 원문은 과제 파일 기준).")

    rows = [row for system in systems for row in read_jsonl(run_dir / system / "attempts.jsonl")]
    rows.sort(key=lambda r: (order.get(r["task_id"], len(order)), r["task_id"], r["attempt"],
                             systems.index(r["variant"]) if r.get("variant") in systems else len(systems)))
    requests, facts, seen = [], {}, set()
    for row in rows:
        system = row.get("variant")
        if system not in systems:
            continue
        key = f"{row['task_id']}/{system}/{row['attempt']}"
        result = row.get("result") or {}
        request_id = str(result.get("request_id") or key)
        if request_id in seen:
            raise ValueError(f"Duplicate request id {request_id!r} ({key})")
        seen.add(request_id)
        f = attempt_facts(row)
        task, grade = by_id.get(row["task_id"]) or {}, grades.get(key) or {}
        requests.append({
            "id": request_id, "key": key, "task_id": row["task_id"], "attempt": row["attempt"],
            "category": row.get("category") or task.get("category"), "language": task.get("language"),
            "expect": task.get("expect") or grade.get("expect"), "question": task.get("question"),
            "mode": mode_of(system), "system": system, "status": f["status"], "error_code": f["error_code"],
            "error_phase": f["error_phase"], "decline_note": f["decline_note"],
            "started_at": starts.get((row["task_id"], row["attempt"])), "recorded_at": row.get("recorded_at"),
            **{k: f[k] for k in ("first_stage_ms", "first_response_ms", "total_ms", "background_ms", "tokens",
                                 "llm_calls", "searches", "verified_first", "verified_final", "added_final",
                                 "lost_first", "continuation", "locked_noops")},
            "passed": grade.get("passed"), "strict_passed": grade.get("strict_passed"),
            "grounded_good": grade.get("grounded_good"), "cost_usd": f["cost_usd"]})
        facts[request_id] = f
    if not requests:
        raise ValueError(f"No attempts recorded in run {run_dir.name!r}")
    missing_tasks = sorted({r["task_id"] for r in requests if r["task_id"] not in by_id})
    if missing_tasks:
        warnings.append(f"과제 파일에 없는 task_id {len(missing_tasks)}개: question = null.")
    ungraded = sum(r["passed"] is None for r in requests)
    if ungraded:
        warnings.append(f"심사 기록이 없는 요청 {ungraded}건: passed·strict_passed = null.")

    lock = lock_info(requests, systems, manifest)
    examples = choose_examples(requests, order)
    rich = {v for v in examples.values() if v}
    traces = {}
    for r in requests:
        f = facts[r["id"]]
        locked = f["locked_slots"] if lock["applied"] and r["mode"] == "agent" else None
        traces[r["id"]] = convert_trace(f["trace"], f["n_first"], rich=r["id"] in rich, locked_slots=locked)
    answers = {r["id"]: {"first": facts[r["id"]]["first_items"], "final": facts[r["id"]]["final_items"]}
               for r in requests}

    env = manifest.get("environment") or {}
    times = sorted(t for t in [*starts.values(), *(r["recorded_at"] for r in requests)] if t)
    first_cost = next((row.get("cost") for row in rows if row.get("cost")), None) or {}
    derived = manifest.get("derived_from") or {}
    run = {
        "id": run_dir.name, "date": times[0][:10] if times else None,
        "started_at": times[0] if times else None, "finished_at": times[-1] if times else None,
        "model": env.get("model"), "effort": env.get("effort"), "embedding_model": env.get("embedding_model"),
        "embedding_dimensions": env.get("embedding_dimensions"), "snapshot_id": env.get("snapshot_id"),
        "tasks": len({r["task_id"] for r in requests}), "repeats": manifest.get("repeats"), "systems": systems,
        "requests": len(requests), "judge_model": judge.get("model") or (manifest.get("judge") or {}).get("model"),
        "judge_protocol": judge.get("protocol"), "judge_votes": judge.get("votes"),
        "commit": (manifest.get("git") or {}).get("commit"), "derived_from": derived.get("run"),
        "pricing_as_of": (first_cost.get("workflow") or {}).get("pricing_as_of"),
    }
    source = (f"평가 실행 기록 '{run['id']}'({run['date'] or '날짜 미상'}, {run['tasks']}과제 × "
              f"{run['repeats'] or '?'}회, {' · '.join(systems)}, {run['model'] or '-'} + "
              f"{run['embedding_model'] or '-'}, 스냅샷 {run['snapshot_id'] or '-'}, 심사 {run['judge_model'] or '-'})의 "
              "attempts.jsonl·grades.jsonl을 frontend/admin_data.py가 변환했다. 실제 학습자 요청이 아니다.")
    current, origin = mode
    payload = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "generator": "frontend.admin_data", "source": source, "run": run, "lock": lock,
            "files": {"data": DATA_FILE, "traces": None}, "answers_scope": "all", "example_rules": EXAMPLE_RULES,
            "notes": notes_for(env), "warnings": warnings, "inputs": inputs,
        },
        "mode": {"current": current, "source": origin, "env_var": MODE_ENV, "allowed": list(MODES),
                 "default": DEFAULT_MODE, "change_hint": CHANGE_HINT,
                 "modes": {m: {"label": MODE_TEXT[m][0], "description": MODE_TEXT[m][1]} for m in MODES}},
        "requests": requests, "traces": traces, "answers": answers, "examples": examples,
        "aggregates": aggregates(requests),
    }
    return AdminData.model_validate(payload).model_dump(mode="json")


# ---------- live requests (frontend/request_log.py rows, for GET /admin/requests.json) ----------

LIVE_STATUS = {"ok": "ok", "declined": "declined"}  # everything else (timeout, busy, disconnected...) is an error
LIVE_CONTINUATION = {"ran": "ran", "skipped": "skipped", "off": "skipped"}  # off: nothing ran after the first stage


class LiveRequest(Request):
    """A live request: data.json's request shape plus what only the server's log row has (the admin page
    shows them in the live list and detail)."""
    transport: Literal["json", "ndjson"] | None
    mode_source: Literal["db", "env"] | None
    quick_ms: int | None


def live_language(text: str | None) -> str | None:
    """ko (Hangul), zh (CJK) or en (Latin letters) by the first such character; None without one."""
    for ch in text or "":
        if "가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" or "㄰" <= ch <= "㆏":
            return "ko"
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            return "zh"
        if ch.isascii() and ch.isalpha():
            return "en"
    return None


def live_request(row: dict) -> tuple[dict, list[dict], dict]:
    """(request, spans, answer) for one coach_request_log row, in data.json's shapes (validated; the request
    adds the row's transport, mode_source and quick_ms, LiveRequest).

    Times, counts and tokens are the server's measures (first_response_ms = the stream's first_ms, else
    total_ms); the trace, answers, lost_first and locked_noops come from the stored RunResult, as for an
    evaluation attempt. Not graded: passed, strict_passed, grounded_good and cost_usd are null."""
    from datetime import timedelta
    rid = f"live-{row['id']}"
    mode = row.get("mode") if row.get("mode") in MODES else DEFAULT_MODE
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    f = attempt_facts({"result": result})
    status = LIVE_STATUS.get(row.get("status"), "error")
    continuation = LIVE_CONTINUATION.get(row.get("continuation"), "none")
    total = ms(row.get("total_ms"))
    first_response = min(total, ms(row["first_ms"])) if row.get("first_ms") is not None else total
    created = row.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    recorded_at = created.astimezone(timezone.utc).isoformat(timespec="milliseconds") if created else None
    started_at = ((created - timedelta(milliseconds=total)).astimezone(timezone.utc).isoformat(timespec="milliseconds")
                  if created else None)
    tin, tout = int(row.get("input_tokens") or 0), int(row.get("output_tokens") or 0)
    question = row.get("question")
    request = {
        "id": rid, "key": f"live/{mode}/{row['id']}", "task_id": rid, "attempt": 1, "category": None,
        "language": live_language(question), "expect": None, "question": question, "mode": mode, "system": mode,
        "status": status,
        "error_code": (row.get("error_code") or row.get("status") or "error") if status == "error" else None,
        "error_phase": (("continuation" if continuation == "ran" or (row.get("verified_first") or 0) > 0 else "first")
                        if status == "error" else None),
        "decline_note": (f["decline_note"] or result.get("source_availability_note")) if status == "declined" else None,
        "started_at": started_at, "recorded_at": recorded_at,
        "first_stage_ms": f["first_stage_ms"], "first_response_ms": first_response, "total_ms": total,
        "background_ms": max(0, total - first_response),
        "tokens": {"input": tin, "output": tout, "total": tin + tout},
        "llm_calls": int(row.get("llm_calls") or 0), "searches": int(row.get("searches") or 0),
        "verified_first": row.get("verified_first"),
        "verified_final": row.get("verified_final") if status == "ok" else None,
        "added_final": int(row.get("added_final") or 0), "lost_first": f["lost_first"],
        "continuation": continuation, "locked_noops": f["locked_noops"],
        "passed": None, "strict_passed": None, "grounded_good": None, "cost_usd": None,
        "transport": row.get("transport") if row.get("transport") in ("json", "ndjson") else None,
        "mode_source": row.get("mode_source") if row.get("mode_source") in ("db", "env") else None,
        "quick_ms": row["quick_ms"] if isinstance(row.get("quick_ms"), int) else None,
    }
    spans = convert_trace(f["trace"], f["n_first"], rich=False,
                          locked_slots=f["locked_slots"] if mode == "agent" else None)
    answer = {"first": f["first_items"], "final": f["final_items"]}
    return (LiveRequest.model_validate(request).model_dump(mode="json"),
            [Span.model_validate(s).model_dump(mode="json") for s in spans],
            Answer.model_validate(answer).model_dump(mode="json"))


def live_payload(rows: list[dict]) -> dict:
    """{"requests", "traces", "answers"} for rows in their order (newest first); a row that cannot be
    converted is left out rather than failing the page."""
    requests, traces, answers = [], {}, {}
    for row in rows:
        try:
            request, spans, answer = live_request(row)
        except Exception:
            continue
        requests.append(request)
        traces[request["id"]], answers[request["id"]] = spans, answer
    return {"requests": requests, "traces": traces, "answers": answers}


# ---------- writing ----------

def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_atomic(path: Path, text: str) -> int:
    data = text.encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return len(data)


def write(payload: dict, out: Path, *, max_bytes: int = MAX_BYTES, split: str = "auto") -> dict[str, int]:
    """Write data.json (and data-traces.json when split); returns {file name: bytes}. data.json must fit max_bytes."""
    if split not in SPLIT_CHOICES:
        raise ValueError(f"split must be one of {', '.join(SPLIT_CHOICES)}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    inline = dumps(payload)
    if split == "always" or (split == "auto" and len(inline.encode("utf-8")) > max_bytes):
        traces = TracesFile.model_validate({"schema_version": SCHEMA_VERSION, "run": payload["meta"]["run"]["id"],
                                            "traces": payload["traces"]}).model_dump(mode="json")
        main = {**payload, "traces": None,
                "meta": {**payload["meta"], "files": {"data": DATA_FILE, "traces": TRACES_FILE}}}
        text = dumps(AdminData.model_validate(main).model_dump(mode="json"))
        if len(text.encode("utf-8")) > max_bytes:
            raise ValueError(f"{DATA_FILE} is {len(text.encode('utf-8'))} bytes even without traces (limit {max_bytes})")
        sizes = {TRACES_FILE: write_atomic(out / TRACES_FILE, dumps(traces))}
        sizes[DATA_FILE] = write_atomic(out / DATA_FILE, text)
        return sizes
    if len(inline.encode("utf-8")) > max_bytes:
        raise ValueError(f"{DATA_FILE} is {len(inline.encode('utf-8'))} bytes (limit {max_bytes}); "
                         "use --split-traces auto or always")
    return {DATA_FILE: write_atomic(out / DATA_FILE, inline)}


# ---------- command line ----------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m frontend.admin_data",
                                     description="Build the /admin data file from an evaluation run.")
    parser.add_argument("--results", type=Path, required=True, help="the results root (e.g. evaluation/results)")
    parser.add_argument("--run", required=True, help="the run directory name under --results")
    parser.add_argument("--tasks", type=Path, required=True, help="the task file (evaluation/data/tasks.jsonl)")
    parser.add_argument("--out", type=Path, required=True, help="output folder (frontend/admin)")
    parser.add_argument("--systems", help="comma-separated systems (default: the manifest's)")
    parser.add_argument("--coach-system", choices=MODES, help=f"the deployed mode (default: ${MODE_ENV}, else agent)")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES, help="data.json size limit in bytes")
    parser.add_argument("--split-traces", choices=SPLIT_CHOICES, default="auto",
                        help="auto: move traces to data-traces.json only when data.json would exceed --max-bytes")
    args = parser.parse_args(argv)
    if not RUN_NAME.fullmatch(args.run) or args.run in (".", ".."):
        parser.error("--run must be one directory name (letters, digits, '.', '_', '-')")
    if not (args.results / args.run).is_dir():
        parser.error(f"run directory not found: {args.results / args.run}")
    if not args.tasks.is_file():
        parser.error(f"task file not found: {args.tasks}")
    if args.max_bytes <= 0:
        parser.error("--max-bytes must be positive")
    if args.systems is not None:
        args.systems = [s.strip() for s in args.systems.split(",") if s.strip()]
        if not args.systems:
            parser.error("--systems is empty")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        payload = build(args.results / args.run, args.tasks, mode=resolve_mode(args.coach_system),
                        systems=args.systems)
        sizes = write(payload, args.out, max_bytes=args.max_bytes, split=args.split_traces)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    lock = payload["meta"]["lock"]
    print(f"{len(payload['requests'])} requests from run {args.run!r}; mode {payload['mode']['current']} "
          f"({payload['mode']['source']}); lock applied: {lock['applied']} ({lock['basis']})")
    for name, size in sizes.items():
        print(f"  {args.out / name}: {size} bytes")
    for warning in payload["meta"]["warnings"]:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
