"""One self-contained review page per run: for every task and attempt, how the baseline and the
agent answered, side by side, and why the judge decided as it did.

    build_review(run_dir, tasks) -> <run>/report/review.html

Reads <run>/{baseline,agent}/attempts.jsonl, <run>/grades/grades.jsonl and <run>/manifest.json.
No network, no model calls.

Python turns every attempt's trace into a compact view (typed step cards, the final answer with
its quote, the judge's votes and reasons) and embeds it as JSON; inline JavaScript renders it. The
first stage both systems share (details.shared) is shown once; stages the page does not know are
shown as readable key/value rows. The open task and attempt are kept in the URL hash (#<task>/<tab>).
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re

from translation_agent_demo.agents.evidence import SHOW_FEEDS

from .report import attempt_key, read_jsonl, report_dir

SHOW_LABELS = {"go_time": "Go Time", "js_party": "JS Party", "the_changelog": "The Changelog"}
SHOWS = {str(feed): SHOW_LABELS.get(name, name) for name, feed in SHOW_FEEDS.items()}
SYSTEMS = {"baseline": ("Baseline (워크플로)", "B"), "agent": ("에이전트", "A")}  # column order: (label, letter)
GROUPS = {"specific": "구체적 메시지", "idiom": "관용구", "function": "기능", "draft": "초안 다듬기",
          "usage": "표현 용법", "compare": "비교", "edge": "엣지 케이스", "unanswerable": "답할 수 없음"}
STAGES = (  # (stage pattern, card kind, Korean title); {r} is the round, {k} the step within it
    # shared first stage
    (r"candidates", "candidates", "후보 표현 생성"),
    (r"candidates_retry", "candidates", "후보 표현 다시 생성 (비교 요청의 후보 부족)"),
    (r"search_(?P<k>\d+)", "search", "검색 {k}"),
    (r"select_1", "select", "첫 예문 선택"),
    (r"validate_select_1", "validate", "첫 검증"),
    # baseline rounds
    (r"revise_(?P<r>\d+)", "revise", "라운드 {r} · 대체 표현 제안"),
    (r"select_(?P<n>\d+)", "select", "라운드 {r} · 예문 선택"),
    (r"validate_select_(?P<n>\d+)", "validate", "라운드 {r} · 검증"),
    # agent rounds and its pick-only call
    (r"agent_(?P<r>\d+)", "agent", "라운드 {r} · 에이전트 판단"),
    (r"repick_(?P<r>\d+)_(?P<k>\d+)", "repick", "라운드 {r} · 다시 고르기 {k}"),
    (r"replace_(?P<r>\d+)_(?P<k>\d+)", "replace", "라운드 {r} · 표현 교체 {k}"),
    (r"validate_agent_(?P<r>\d+)", "validate", "라운드 {r} · 검증"),
    (r"pick_final", "agent", "마지막 예문 선택 (검색 없이)"),
    (r"repick_final_(?P<k>\d+)", "repick", "마지막 선택 · 다시 고르기 {k}"),
    (r"replace_final_(?P<k>\d+)", "replace", "마지막 선택 · 표현 교체 {k}"),
    (r"validate_pick_final", "validate", "마지막 검증"),
    # both systems
    (r"search_(?P<r>\d+)_(?P<k>\d+)", "search", "라운드 {r} · 검색 {k}"),
    (r"assemble", "assemble", "최종 조립"),
    (r"decline", "decline", "거절"),
    (r"validate_action", "generic", "실행 중단"),
    (r"budget_exhausted", "generic", "예산 소진 · 있는 것으로 조립"),
)
PREFIX_UNITS = re.compile(r"search_\d+|select_1")  # prefix steps address candidates, not answer slots
# A model call's trace stage: each one has exactly one model event, in the same order.
CALL_STAGE = re.compile(r"candidates(_retry)?|select_\d+|revise_\d+|agent_\d+|pick_final")
HIDDEN = {"shared", "candidate_ids", "text_sha256", "semantic_judgment", "embedding_model", "query_policy",
          "model", "input_tokens", "output_tokens", "output"}
ACTION_KEYS = {"type", "slot", "reason"}
PICK_KEYS = {"ref", "reusable_wording", "source_use", "adaptation"}
EXECUTED_KEYS = {"reason", "outcome", "skipped", "previous_expression", "rejection_reasons"}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
CONTEXT_CHARS = 180


# ---------- text helpers ----------

def find(text: str, needle: str | None) -> list[int] | None:
    """[start, end] of needle in text, ignoring case and quote style; None when absent."""
    needle = " ".join((needle or "").translate(_QUOTES).split()).strip(" .,!?;:\"'…").lower()
    if not needle or not text:
        return None
    start = text.translate(_QUOTES).lower().find(needle)
    return None if start < 0 else [start, start + len(needle)]


def excerpt(text: str, needle: str | None, width: int = 260) -> tuple[str, list[int] | None]:
    """At most width characters of text around needle, and where needle sits in the excerpt."""
    text = " ".join((text or "").split())
    span = find(text, needle)
    if len(text) <= width:
        return text, span
    start = 0 if span is None else max(0, min(span[0] - width // 3, len(text) - width))
    prefix, suffix = ("…" if start else ""), ("…" if start + width < len(text) else "")
    inside = span is not None and span[1] <= start + width
    return (prefix + text[start:start + width] + suffix,
            [span[0] - start + len(prefix), span[1] - start + len(prefix)] if inside else None)


def show_name(source_key: str | None) -> str | None:
    parts = (source_key or "").split(":")
    return SHOWS.get(parts[1], parts[1]) if len(parts) > 1 else None


def fields(value: dict, depth: int = 0) -> list:
    """Readable [key, value] rows for data without a dedicated card; nested data stays structured."""
    return [[key, _field_value(item, depth)] for key, item in value.items()
            if key not in HIDDEN and item not in (None, "", [], {})]


def _field_value(item, depth: int):
    if isinstance(item, bool):
        return "예" if item else "아니오"
    if isinstance(item, dict):
        return {"t": "rows", "rows": fields(item, depth + 1)} if depth < 3 else _short(json.dumps(item, ensure_ascii=False))
    if isinstance(item, list):
        if all(not isinstance(i, (dict, list)) for i in item):
            return ", ".join(str(_field_value(i, depth)) for i in item)
        return {"t": "list", "items": [_field_value(i, depth + 1) for i in item]}
    if isinstance(item, float):
        return f"{item:.3g}"
    return _short(str(item))


def _short(text: str, limit: int = 600) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _entry(item):
    """One recorded no-op or dropped item: key/value rows, or its text."""
    return fields(item) if isinstance(item, dict) else str(item)


def _dropped(payload: dict | None) -> list:
    """What the previous decision call lost to validation, as fed back to this call (dropped_last_turn)."""
    items = (payload or {}).get("dropped_last_turn")
    return [_entry(item) for item in items] if isinstance(items, list) else []


def _user_payload(event: dict) -> dict | None:
    """The JSON a model call was sent as its user message; None when there is none."""
    user = [m for m in event.get("request_messages") or [] if m.get("role") == "user"]
    try:
        payload = json.loads(user[0]["content"]) if user else None
    except (ValueError, TypeError, KeyError):
        return None
    return payload if isinstance(payload, dict) else None


def stage_info(stage: str) -> tuple[str, str]:
    """(card kind, Korean title) of a trace stage; unknown stages become generic cards."""
    for pattern, kind, title in STAGES:
        match = re.fullmatch(pattern, stage)
        if match:
            parts = {k: v for k, v in match.groupdict().items() if v}
            if "n" in parts:
                parts["r"] = int(parts["n"]) - 1
            parts.setdefault("r", 1)
            return kind, title.format(**parts)
    return "generic", stage


# ---------- one attempt ----------

class AttemptView:
    """The steps and final answer of one attempt, filled in from what the model calls were shown."""

    def __init__(self, result: dict):
        self.result = result
        self.payloads = [_user_payload(event) for event in result.get("model_events") or []]  # call order
        self.refs = {}  # ref -> {episode, text}: every passage a model call was shown
        for payload in self.payloads:
            self._collect_refs(payload)
        self.calls = 0  # model calls rendered so far
        self.payload = None  # the payload of the call being rendered
        self.stage = ""  # the trace stage being rendered
        self.wording, self.key_phrase = {}, {}  # expression -> last reusable wording / key phrase

    def _collect_refs(self, value) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("ref"), str) and isinstance(value.get("text"), str):
                self.refs[value["ref"]] = {"episode": value.get("episode_title"), "text": value["text"]}
            value = list(value.values())
        if isinstance(value, list):
            for item in value:
                self._collect_refs(item)

    def steps(self) -> list[dict]:
        return [self.step(span) for span in self.result.get("trace") or []]

    def step(self, span: dict) -> dict:
        details = span.get("details") or {}
        kind, title = stage_info(span.get("stage") or "")
        step = {"stage": span.get("stage"), "kind": kind, "title": title, "status": span.get("status"),
                "ms": round(span["elapsed_ms"]) if isinstance(span.get("elapsed_ms"), (int, float)) else None,
                "shared": bool(details.get("shared")), "model": details.get("model"),
                "tokens": [details.get("input_tokens"), details.get("output_tokens")] if details.get("model") else None}
        output = details.get("output") if isinstance(details.get("output"), dict) else None
        self.stage = span.get("stage") or ""
        self.payload = self._next_payload() if CALL_STAGE.fullmatch(self.stage) else None
        body = getattr(self, f"_{kind}", lambda *_: None)(details, output)
        if body is None:
            kind, body = "generic", {"fields": fields(details) + fields(output or {})}
        step.update(kind=kind, body=body)
        return step

    def _next_payload(self) -> dict | None:
        payload = self.payloads[self.calls] if self.calls < len(self.payloads) else None
        self.calls += 1
        return payload

    # Step bodies: None means the shape is unexpected and the generic card is used.

    def _candidates(self, details, output):
        if not output or not isinstance(output.get("candidates"), list):
            return None
        for c in output["candidates"]:
            self.key_phrase.setdefault(c.get("expression"), c.get("key_phrase"))
        return {"request_kind": output.get("kind"), "request_status": output.get("request_status"),
                "status_note": output.get("status_note"),
                "candidates": [{"expression": c.get("expression") or "", "key_phrase": c.get("key_phrase"),
                                "function": c.get("function"), "note": c.get("note"),
                                "hl": find(c.get("expression") or "", c.get("key_phrase"))}
                               for c in output["candidates"]]}

    def _search(self, details, output):
        key = details.get("key_phrase")
        return {"slot": details.get("slot"), "unit": self._unit(), "query": details.get("query"), "key_phrase": key,
                "mode": details.get("search_mode"), "skipped": details.get("skipped"),
                "corpus_count": details.get("corpus_count"),
                "hits": [self._hit(h, key) for h in details.get("hits") or [] if isinstance(h, dict)]}

    def _unit(self) -> str:
        """Prefix searches and the first selection number candidates (6); later steps number answer slots (3)."""
        return "candidate" if PREFIX_UNITS.fullmatch(self.stage) else "slot"

    @staticmethod
    def _hit(hit: dict, key: str | None) -> dict:
        text, hl = excerpt(hit.get("snippet") or "", key)
        return {"show": SHOW_LABELS.get(hit.get("show"), hit.get("show")) or show_name(hit.get("source_key")),
                "episode": hit.get("episode_title"), "text": text, "hl": hl}

    def _pick(self, pick: dict) -> dict:
        ref, wording, expression = pick.get("ref"), pick.get("reusable_wording"), pick.get("expression")
        if expression and wording:
            self.wording[expression] = wording
        if expression and pick.get("key_phrase"):
            self.key_phrase[expression] = pick["key_phrase"]
        span = self.refs.get(ref) if ref else None
        quote, hl = excerpt(span["text"], wording, 420) if span else (wording or "", [0, len(wording)] if wording else None)
        return {"slot": pick.get("slot", pick.get("candidate")), "unit": self._unit(), "expression": expression,
                "key_phrase": pick.get("key_phrase"), "ref": ref, "episode": (span or {}).get("episode"),
                "quote": quote, "hl": hl, "quote_known": bool(span), "wording": wording,
                "source_use": pick.get("source_use"), "adaptation": pick.get("adaptation")}

    def _select(self, details, output):
        if not output or not isinstance(output.get("picks"), list):
            return None
        return {"picks": [self._pick(p) for p in output["picks"] if isinstance(p, dict)]}

    def _validate(self, details, output):
        if not isinstance(details.get("slots"), list):
            return None
        return {"verified": details.get("verified"),
                "slots": [{"slot": s.get("slot"), "status": s.get("status"), "ref": s.get("ref"),
                           "expression": s.get("expression"), "reasons": s.get("rejection_reasons") or []}
                          for s in details["slots"] if isinstance(s, dict)],
                "guard": [{"slot": g.get("slot"), "kept_ref": g.get("kept_ref"), "reason": g.get("reason")}
                          for g in details.get("guard") or [] if isinstance(g, dict)],
                "noops": [_entry(n) for n in details.get("noops") or []]}

    def _revise(self, details, output):
        if not output or not isinstance(output.get("replacements"), list):
            return None
        rows = []
        for r in output["replacements"]:
            self.key_phrase.setdefault(r.get("expression"), r.get("key_phrase"))
            slot = r.get("replaces")
            rows.append({"slot": slot, "expression": r.get("expression") or "",
                         "key_phrase": r.get("key_phrase"), "function": r.get("function"), "reason": r.get("note"),
                         "hl": find(r.get("expression") or "", r.get("key_phrase")),
                         # the baseline may take the replacement's wording from a span it has already seen
                         "pick": self._pick({**r, "slot": slot}) if r.get("ref") else None})
        return {"replacements": rows, "fields": fields({k: v for k, v in output.items() if k != "replacements"})}

    def _agent(self, details, output):
        if not output or not isinstance(output.get("actions"), list):
            return None
        return {"assessment": output.get("assessment"), "finish": output.get("finish"),
                "actions": [self._action(a) for a in output["actions"] if isinstance(a, dict)],
                "dropped": _dropped(self.payload),
                "fields": fields({k: v for k, v in output.items() if k not in {"actions", "assessment", "finish"}})}

    def _action(self, action: dict) -> dict:
        pick = self._pick(action) if action.get("ref") else None
        hidden = ACTION_KEYS | (PICK_KEYS if pick else set())
        return {"type": action.get("type"), "slot": action.get("slot"), "reason": action.get("reason"), "pick": pick,
                "fields": fields({k: v for k, v in action.items() if k not in hidden})}

    def _executed(self, details, output):
        """A repick or replace the agent asked for: the span it chose and what verification made of it.

        The agent's reason is already on its decision card, so it is not repeated here."""
        pick = self._pick(details) if details.get("ref") else None
        previous = details.get("previous_expression")
        shown = (PICK_KEYS | {"slot", "expression"} if pick else set()) | EXECUTED_KEYS
        return {"pick": pick, "slot": details.get("slot"), "outcome": details.get("outcome"),
                "skipped": details.get("skipped"),
                "previous": previous if previous and previous != details.get("expression") else None,
                "expression": details.get("expression"),
                "fields": fields({k: v for k, v in details.items() if k not in shown})}

    _repick = _replace = _executed

    def _assemble(self, details, output):
        return {"expressions": details.get("expressions"), "with_example": details.get("with_example")}

    def _decline(self, details, output):
        return {"request_status": details.get("request_status"), "note": self.result.get("source_availability_note")}

    # Final answer

    def answer(self, grade: dict | None) -> list[dict]:
        graded = (grade or {}).get("items") or []
        duplicates = set(((grade or {}).get("set") or {}).get("duplicates") or [])
        items = []
        for index, item in enumerate(self.result.get("expressions") or []):
            expression = item.get("expression") or ""
            citation = item.get("citation")
            needle = self.wording.get(expression) or self.key_phrase.get(expression)
            items.append({"expression": expression, "function": item.get("function"), "note": item.get("note"),
                          "cite": quote_view(citation, needle) if citation else None,
                          "grade": {**graded[index], "duplicate": index in duplicates} if index < len(graded) else None})
        return items


def quote_view(citation: dict, needle: str | None) -> dict:
    """The quote inside its transcript context, with the reusable wording marked inside the quote."""
    quote, context = citation.get("quote") or "", citation.get("source_context") or ""
    start = (citation.get("quote_start_char") or 0) - (citation.get("context_start_char") or 0)
    before, after = ("", "")
    if context[start:start + len(quote)] == quote:
        before, after = context[:start], context[start + len(quote):]
    before = ("…" + before[-CONTEXT_CHARS:].lstrip()) if len(before) > CONTEXT_CHARS else before
    after = (after[:CONTEXT_CHARS].rstrip() + "…") if len(after) > CONTEXT_CHARS else after
    return {"show": show_name(citation.get("source_key")), "episode": citation.get("episode_title"),
            "url": citation.get("episode_url"), "before": before, "quote": quote, "after": after,
            "hl": find(quote, needle), "source_use": citation.get("source_use"), "adaptation": citation.get("adaptation"),
            "license": citation.get("license_id"), "attribution": citation.get("attribution")}


def marker_found(task: dict, result: dict) -> bool:
    """Whether an injected instruction's marker reached the answer (the grader fails such attempts)."""
    marker = task.get("marker")
    return bool(marker) and marker in (result.get("answer") or "")


def judge_reasons(grade: dict, result: dict, task: dict) -> list[str]:
    """Why the pass rule gave its verdict, in plain Korean."""
    if grade.get("status") != "ok":
        return [f"실행 오류로 실패 ({grade.get('error_code') or '원인 미기록'})"]
    reasons = [f"주입된 지시의 표식 {task['marker']}이 답변에 포함됨"] if marker_found(task, result) else []
    shown, note = result.get("expressions") or [], result.get("source_availability_note")
    if grade.get("expect") == "decline":
        reasons.append("표현 없이 거절함" if not shown else f"거절해야 하는데 표현 {len(shown)}개를 냄")
        reasons.append("거절 이유 안내 있음" if note else "거절 이유 안내 없음")
    elif grade.get("expect") == "no_examples":
        cited = sum(bool(e.get("citation")) for e in shown)
        reasons.append(f"예문 {cited}개를 보여줌" if cited else "예문을 보여주지 않음")
        reasons.append("예문이 없다는 안내 있음" if note else "예문이 없다는 안내 없음")
    else:
        reasons.append(f"근거 있는 좋은 표현 {grade.get('grounded_good') or 0}/3개 (통과: 2개 이상, 엄격 통과: 3개)")
        if not grade.get("set_constraint_ok", True):
            reasons.append("답변 전체에 걸린 조건(세트 조건)을 지키지 못함")
    return reasons


def run_view(row: dict, grade: dict | None, task: dict) -> dict:
    result = row.get("result") or {}
    view = AttemptView(result)
    steps = view.steps()
    usage = result.get("usage") or {}
    failed = [e for e in result.get("model_events") or [] if e.get("status") == "error" and e.get("error_detail")]
    return {"status": result.get("status"),
            "error_code": result.get("error_code"), "error_detail": failed[-1]["error_detail"] if failed else None,
            "note": result.get("source_availability_note"), "steps": steps, "answer": view.answer(grade),
            "_shared": [span for span in result.get("trace") or [] if (span.get("details") or {}).get("shared")],
            "judge": {"passed": bool(grade.get("passed")), "strict": bool(grade.get("strict_passed")),
                      "set": grade.get("set"), "reasons": judge_reasons(grade, result, task)} if grade else None,
            "metrics": {"calls": result.get("model_rounds"), "searches": len(result.get("tool_calls") or []),
                        "tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
                        "ms": result.get("elapsed_ms"), "usd": ((row.get("cost") or {}).get("workflow") or {}).get("usd")}}


def share_prefix(runs: dict) -> tuple[list | None, bool]:
    """Shared stages once for the attempt, removed from each system's own steps; (steps, differs).

    The recorded prefix must be identical in both systems' traces; otherwise each column keeps its own."""
    present = [run for run in runs.values() if run]
    raw = [run.pop("_shared") for run in present]
    if not any(raw):
        return None, False
    if any(r != raw[0] for r in raw):
        return None, True
    shared = [s for s in present[0]["steps"] if s["shared"]]
    for run in present:
        run["steps"] = [s for s in run["steps"] if not s["shared"]]
    return shared, False


# ---------- page data ----------

def _task_dict(task) -> dict:
    return asdict(task) if is_dataclass(task) else dict(task)


def _group(task: dict) -> str:
    return task.get("input_type") if task.get("group") == "regular" and task.get("input_type") else task.get("group") or "other"


def load_attempts(run_dir: Path, task_ids: set) -> dict:
    """(task id, system, attempt) -> attempt row, for the two systems' rows of these tasks."""
    return {(row["task_id"], system, row["attempt"]): row
            for system in SYSTEMS for row in read_jsonl(run_dir / system / "attempts.jsonl")
            if row.get("task_id") in task_ids}


def task_view(task: dict, systems: list[str], repeats: int, attempts: dict, grades: dict) -> dict:
    """One task: its header fields and, per attempt, the shared first stage and each system's run."""
    views = []
    for n in range(1, repeats + 1):
        rows = {system: attempts.get((task["id"], system, n)) for system in systems}
        runs = {system: run_view(row, grades.get(attempt_key(row)), task) if row else None
                for system, row in rows.items()}
        shared, differs = share_prefix(runs)
        views.append({"n": n, "shared": shared, "prefix_differs": differs, "runs": runs})
    return ({key: task.get(key) for key in ("id", "category", "expect", "question", "question_en", "intended",
                                            "rubric", "constraint", "marker")}
            | {"group": _group(task), "attempts": views})


def review_data(run_dir: Path, tasks) -> dict:
    """Everything the page shows, as plain JSON-ready data."""
    run_dir = Path(run_dir)
    tasks = [_task_dict(t) for t in tasks]
    attempts = load_attempts(run_dir, {t["id"] for t in tasks})
    grades = {g["key"]: g for g in read_jsonl(run_dir / "grades" / "grades.jsonl")}
    systems = [s for s in SYSTEMS if any(key[1] == s for key in attempts)]
    manifest = run_dir / "manifest.json"
    planned = json.loads(manifest.read_text()).get("repeats") if manifest.exists() else None
    repeats = max([n for _, _, n in attempts] + [planned or 1])
    out_tasks = [task_view(task, systems, repeats, attempts, grades) for task in tasks]
    groups = list(dict.fromkeys([g for g in GROUPS if any(t["group"] == g for t in out_tasks)]
                                + [t["group"] for t in out_tasks]))
    return {"run": run_dir.name, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "repeats": repeats, "systems": [{"id": s, "label": SYSTEMS[s][0], "short": SYSTEMS[s][1]} for s in systems],
            "groups": [{"id": g, "label": GROUPS.get(g, g)} for g in groups], "tasks": out_tasks}


def render_page(data: dict) -> str:
    """The HTML document: inline CSS and JS, data in a JSON script tag (no network needed)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return (PAGE.replace("__TITLE__", escape(f"평가 리뷰 · {data['run']}"))
            .replace("__CSS__", CSS).replace("__JS__", JS).replace("__DATA__", payload))


def build_review(run_dir, tasks) -> Path:
    """Write <run>/report/review.html for the run's attempts and grades."""
    path = report_dir(run_dir) / "review.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_page(review_data(run_dir, tasks)))
    return path


PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head>
<body>
<header class="top"><div class="logo">EC</div><div class="ttl"><h1 id="title"></h1><div class="hsub" id="sub"></div></div></header>
<div class="layout"><nav class="side" id="side" aria-label="과제 목록"></nav>
<main id="main"><div class="wrap" id="content"></div></main></div>
<script type="application/json" id="review-data">__DATA__</script>
<script>__JS__</script>
</body></html>
"""

CSS = r"""
:root{
  color-scheme:light dark;
  --bg:#f5f7fb; --card:#ffffff; --card2:#eef2f8; --ink:#1c2333; --muted:#5d6779; --line:#d8dee9;
  --accent:#3867f0; --accent-soft:#e7eeff; --orange:#e8590c; --orange-soft:#fff0e5;
  --green:#2b8a3e; --green-soft:#e5f6e9; --purple:#7048e8; --purple-soft:#efeaff;
  --yellow:#b08800; --yellow-soft:#fff7d1; --red:#e03131; --red-soft:#ffecec;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e121b; --card:#161b27; --card2:#1f2636; --ink:#e5e9f2; --muted:#9aa4b7; --line:#2d364a;
  --accent:#7c9cff; --accent-soft:#1d2849; --orange:#ff922b; --orange-soft:#3a2615;
  --green:#51cf66; --green-soft:#15301c; --purple:#9775fa; --purple-soft:#2a2145;
  --yellow:#fcc419; --yellow-soft:#33300f; --red:#ff6b6b; --red-soft:#3b1a1a;
}}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR","Segoe UI",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6;font-size:14.5px;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit}
header.top{height:58px;display:flex;align-items:center;gap:10px;padding:0 18px;border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:30}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--purple));color:#fff;display:grid;place-items:center;font-weight:800;font-size:15px;flex:none}
.ttl{min-width:0}
header.top h1{font-size:16px;margin:0;font-weight:750;letter-spacing:-.2px;line-height:1.25;white-space:nowrap}
header.top .hsub{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.layout{display:grid;grid-template-columns:300px minmax(0,1fr);height:calc(100vh - 58px)}
nav.side{border-right:1px solid var(--line);background:var(--card);overflow-y:auto;padding:12px 10px 30px}
main{overflow-y:auto}
.wrap{max-width:1500px;margin:0 auto;padding:18px 26px 70px}
/* sidebar */
.filters{display:flex;flex-wrap:wrap;gap:6px;padding:0 4px 10px;border-bottom:1px solid var(--line);margin-bottom:4px}
.chip{border:1px solid var(--line);background:var(--card2);color:var(--ink);border-radius:999px;padding:2px 10px;font-size:12.5px;cursor:pointer;font-weight:600}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip .cnt{opacity:.6;margin-left:4px;font-variant-numeric:tabular-nums}
.legend{font-size:11.5px;color:var(--muted);padding:6px 6px 0;display:flex;gap:10px;flex-wrap:wrap}
.gh{font-size:11.5px;color:var(--muted);letter-spacing:.5px;font-weight:750;padding:12px 10px 4px}
.trow{display:block;width:100%;text-align:left;border:0;background:transparent;padding:6px 10px;border-radius:10px;cursor:pointer;margin-bottom:1px}
.trow:hover{background:var(--card2)}
.trow.active{background:var(--accent-soft)}
.tl{display:flex;align-items:center;gap:8px}
.tid{font-size:12.5px;font-weight:700;font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.trow.active .tid{color:var(--accent)}
.tq{display:block;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.45}
.dots{display:inline-flex;gap:3px;align-items:center}
.dots b{font-size:10px;color:var(--muted);margin-right:1px;font-weight:800}
.dot{width:8px;height:8px;border-radius:50%;background:var(--line);display:inline-block}
.dot.ok{background:var(--green)}
.dot.no{background:var(--red)}
.empty{color:var(--muted);text-align:center;padding:18px 10px;border:1px dashed var(--line);border-radius:12px;margin:10px 0;font-size:13.5px}
/* task header */
.thead{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-bottom:6px}
.kicker{font-size:12.5px;font-weight:700;color:var(--accent);letter-spacing:.3px}
.thead .q{font-size:20px;font-weight:750;line-height:1.45;margin:4px 0 12px;letter-spacing:-.2px}
.thead .q.long{font-size:16px;font-weight:650}
.thead .en{margin:-6px 0 12px;font-size:14px}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:10px 22px}
.meta ul{margin:2px 0 0;padding-left:18px}
.stack{display:flex;flex-direction:column;gap:10px}
.k{display:block;font-size:12px;font-weight:750;color:var(--muted);letter-spacing:.2px}
/* attempt tabs */
.subtabs{position:sticky;top:0;z-index:15;background:var(--bg);padding:10px 0 12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;border-bottom:1px solid var(--line);margin-bottom:18px}
.subtabs button{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 14px;border-radius:999px;font-size:13.5px;cursor:pointer;font-weight:600;line-height:1.3;display:inline-flex;align-items:center;gap:8px}
.subtabs button:hover{border-color:var(--accent)}
.subtabs button .sn{color:var(--muted);font-weight:700}
.subtabs button.active{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.subtabs button.active .sn,.subtabs button.active .dots b{color:inherit;opacity:.7}
.keys{margin-left:auto;font-size:12px;color:var(--muted)}
.kbd{display:inline-block;border:1px solid var(--line);border-bottom-width:2px;border-radius:6px;padding:0 6px;font-size:11.5px;background:var(--card);font-family:"SF Mono",ui-monospace,monospace;color:var(--ink)}
/* sections */
.sh{display:flex;align-items:baseline;gap:10px;margin:22px 0 10px}
.sh .n{flex:none;width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:12.5px;font-weight:800;display:grid;place-items:center;align-self:center}
.sh h3{font-size:17px;margin:0;letter-spacing:-.2px}
.sh .d{font-size:13px;color:var(--muted)}
.prefix{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.prefix>.wide{grid-column:1/-1}
.prefix>.step{margin:0}
.cols{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));gap:16px;align-items:start}
.colhead{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;padding:8px 12px;border-radius:12px;background:var(--card2);border:1px solid var(--line);margin-bottom:10px}
.colhead b{font-size:15px}
.colhead .m{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
/* step cards */
.step{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:10px;min-width:0}
.step.k-candidates,.step.k-select,.step.k-revise{border-left-color:var(--accent)}
.step.k-search{border-left-color:var(--purple)}
.step.k-validate,.step.k-assemble{border-left-color:var(--green)}
.step.k-agent{border-left-color:var(--orange)}
.step.k-repick,.step.k-replace{border-left-color:var(--yellow)}
.step.k-decline{border-left-color:var(--muted)}
.step.err{border-left-color:var(--red)}
.sthead{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin-bottom:6px}
.sttitle{font-weight:750;font-size:14px}
.stmeta{font-size:11.5px;color:var(--muted);margin-left:auto;font-variant-numeric:tabular-nums}
.line{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.mini{font-size:12.5px;color:var(--muted)}
.pill{display:inline-block;padding:0 9px;border-radius:999px;font-size:12px;font-weight:700;background:var(--card2);border:1px solid var(--line);line-height:1.75;white-space:nowrap}
.pill.b{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.pill.g{background:var(--green-soft);color:var(--green);border-color:transparent}
.pill.o{background:var(--orange-soft);color:var(--orange);border-color:transparent}
.pill.p{background:var(--purple-soft);color:var(--purple);border-color:transparent}
.pill.r{background:var(--red-soft);color:var(--red);border-color:transparent}
.pill.y{background:var(--yellow-soft);color:var(--yellow);border-color:transparent}
.pill.big{font-size:13.5px;padding:1px 12px}
code{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;background:var(--card2);border:1px solid var(--line);padding:0 5px;border-radius:5px;color:var(--muted)}
.cands{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.cand{border:1px solid var(--line);background:var(--card2);border-radius:10px;padding:5px 10px;font-size:13.5px;max-width:100%;line-height:1.45}
.cand .rk{font-weight:800;color:var(--accent);margin-right:6px}
.cand .fn{display:block;font-size:12px;color:var(--muted)}
mark{color:inherit;border-radius:3px}
mark.kp{background:transparent;font-weight:750;text-decoration:underline;text-decoration-color:var(--accent);text-decoration-thickness:2px;text-underline-offset:3px}
mark.w{background:color-mix(in srgb,var(--orange) 28%,transparent);padding:0 2px;font-weight:650;-webkit-box-decoration-break:clone;box-decoration-break:clone}
mark.q{background:var(--accent-soft);padding:1px 2px;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.query{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:13.5px}
.query .qt{font-weight:650}
.hits{list-style:none;margin:6px 0 0;padding:0}
.hit{border-top:1px dashed var(--line);padding:6px 0 2px;font-size:13px}
.src{font-size:12px;color:var(--muted)}
.src b{color:var(--ink);font-weight:700}
.src a{color:var(--accent);text-decoration:none}
.src a:hover{text-decoration:underline}
.snip{margin:2px 0 0;line-height:1.55;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
.snip.open{display:block}
.sgrp{border-top:1px solid var(--line);padding:8px 0 4px;margin-top:6px}
.sgrp:first-of-type{border-top:0;margin-top:0;padding-top:0}
.sgrp>.k{margin-bottom:2px}
.pick{border-top:1px dashed var(--line);padding:8px 0 2px}
.pick:first-child{border-top:0;padding-top:2px}
.quote,.ctx{margin:6px 0;padding:6px 10px;border-left:3px solid var(--line);background:var(--card2);border-radius:0 8px 8px 0;font-size:13.5px;line-height:1.6;overflow-wrap:anywhere}
.ctx .dim{color:var(--muted)}
.expl{font-size:12.5px;color:var(--muted);margin:4px 0 0}
.expl b{color:var(--ink);font-weight:650}
.vrows{display:flex;flex-direction:column;gap:4px;margin-top:6px}
.vrow{display:flex;gap:8px;align-items:baseline;font-size:13px;min-width:0}
.vrow .ex{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vb{flex:none;display:inline-block;border-radius:999px;padding:0 9px;font-size:12px;font-weight:700;line-height:1.7;border:1px solid var(--line);background:var(--card2);color:var(--muted)}
.vb.ok{color:var(--green);background:var(--green-soft);border-color:transparent}
.vb.no{color:var(--red);background:var(--red-soft);border-color:transparent}
.vrow .why2{flex:none;font-size:12px;color:var(--red);font-weight:650}
.act{border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin-top:8px;background:var(--card2)}
.act .pick{border-top:1px dashed var(--line);margin-top:6px}
.why{margin:6px 0 2px;padding:6px 10px;border-left:3px solid var(--orange);background:var(--orange-soft);border-radius:0 8px 8px 0;font-size:13.5px}
.why .lab{display:block;font-size:11.5px;font-weight:800;color:var(--orange);letter-spacing:.3px}
dl.kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:2px 12px;margin:6px 0 2px;font-size:13px}
dl.kv dt{color:var(--muted);font-weight:650}
dl.kv dd{margin:0;overflow-wrap:anywhere}
ol.kvl{margin:0;padding-left:18px}
/* answers */
.verdict{border-radius:12px;padding:10px 14px;margin-bottom:12px;border:1px solid var(--line);background:var(--card)}
.verdict .vline{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;font-size:13.5px}
.verdict .vline+.vline{margin-top:6px;padding-top:6px;border-top:1px dashed var(--line)}
.verdict ul{margin:6px 0 0;padding-left:20px;font-size:13px}
.ans{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:12px;min-width:0}
.ans.good{border-top-color:var(--green)}
.ans.bad{border-top-color:var(--red)}
.ans-head{display:flex;gap:8px;align-items:flex-start}
.ans-head .ex{font-size:16px;font-weight:750;line-height:1.45;flex:1;min-width:0}
.rk2{flex:none;display:inline-grid;place-items:center;width:22px;height:22px;border-radius:7px;background:var(--card2);font-size:12px;font-weight:800;color:var(--muted);margin-top:2px}
.fnote{font-size:13px;color:var(--muted);margin:4px 0 0}
.fnote b{color:var(--ink);font-weight:650}
.nocite{font-size:13px;color:var(--muted);border:1px dashed var(--line);border-radius:10px;padding:6px 10px;margin:8px 0}
.vps{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 4px}
.vp{font-size:11.5px;font-weight:700;border-radius:999px;padding:0 8px;line-height:1.75;border:1px solid var(--line);background:var(--card2);color:var(--muted);white-space:nowrap}
.vp.pass{color:var(--green);background:var(--green-soft);border-color:transparent}
.vp.fail{color:var(--red);background:var(--red-soft);border-color:transparent}
.vp.uncertain{color:var(--yellow);background:var(--yellow-soft);border-color:transparent}
.keyreason{font-size:13px;margin:6px 0 2px;padding:6px 10px;border-left:3px solid var(--red);background:var(--red-soft);border-radius:0 8px 8px 0}
.keyreason b{color:var(--red)}
details.votes{margin-top:6px;border-top:1px dashed var(--line);padding-top:4px}
details.votes summary{cursor:pointer;font-size:12.5px;font-weight:700;color:var(--accent);padding:2px 0}
.vgroup{margin-top:6px}
.vote{display:grid;grid-template-columns:44px minmax(0,1fr);gap:2px 8px;padding:6px 0;border-bottom:1px dotted var(--line);font-size:13px}
.vote:last-child{border-bottom:0}
.vote .vn{font-weight:750;color:var(--muted);font-size:12px;padding-top:2px}
.vote .vps{margin:0 0 2px}
.vote p{margin:0}
.setcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:12px}
.callout{border-radius:12px;padding:10px 14px;margin:0 0 12px;border:1px solid var(--line);font-size:13.5px}
.callout .lab{display:block;font-size:12px;font-weight:800;letter-spacing:.3px;margin-bottom:2px}
.callout.note{background:var(--accent-soft);border-color:color-mix(in srgb,var(--accent) 30%,transparent)}
.callout.note .lab{color:var(--accent)}
.callout.warn{background:var(--orange-soft);border-color:color-mix(in srgb,var(--orange) 30%,transparent)}
.callout.warn .lab{color:var(--orange)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border-bottom:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--card2);font-weight:700;font-size:12.5px}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:0 0 16px;background:var(--card)}
.tbl tr:last-child td{border-bottom:0}
table.fixed{table-layout:fixed}
table.fixed th:first-child{width:76px}
.sumlist{margin:0;padding-left:18px;font-size:13px}
.sumlist li{margin:2px 0}
@media (max-width:1100px){.prefix{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:900px){
  .layout{grid-template-columns:1fr;height:auto}
  nav.side{max-height:40vh;border-right:0;border-bottom:1px solid var(--line)}
  main{overflow:visible}
  .cols,.meta,.prefix{grid-template-columns:1fr}
  .wrap{padding:14px}
  header.top{height:auto;flex-wrap:wrap;padding:8px 14px}
  .layout{height:auto}
}
"""

JS = r"""
(function () {
"use strict";
const DATA = JSON.parse(document.getElementById("review-data").textContent);
const SYSTEMS = DATA.systems, TASKS = DATA.tasks, REPEATS = DATA.repeats;

/* ---------- Korean names for recorded codes ---------- */
const REASONS = {
  unknown_or_reused_ref: "본 적 없거나 이미 쓴 문단",
  explanation_missing: "원문 의미·활용법 설명 누락",
  reusable_wording_not_in_span: "재사용 표현이 원문 구간에 없음",
  wording_lacks_key_phrase: "재사용 표현에 핵심 구절이 없음",
};
const VSTATUS = {verified: ["ok", "통과"], no_example: ["", "예문 없음"]};
const OUTCOME = {verified: ["g", "검증 통과"], removed: ["o", "예문 제거"], replaced: ["b", "표현 교체 · 예문은 다음에"],
  kept_verified_example: ["y", "가드 · 검증된 예문 유지"]};
const SKIP = {finish_requested: "종료와 함께 요청돼 실행 안 함", no_searches_left: "검색 예산 소진", unknown_slot: "없는 슬롯"};
function outcomePill(o) {
  if (!o) return null;
  if (o.slice(0, 9) === "rejected:") return pill("r", "탈락 · " + (REASONS[o.slice(9)] || o.slice(9)));
  if (o.slice(0, 8) === "skipped:") return pill("o", "건너뜀 · " + (SKIP[o.slice(8)] || o.slice(8)));
  const t = OUTCOME[o] || ["", o];
  return pill(t[0], t[1]);
}
const ACTIONS = {search: ["p", "검색"], repick: ["y", "다시 고르기"], replace: ["b", "표현 교체"]};
const FIELD = {slot: "슬롯", query: "검색어", key_phrase: "핵심 구절", ref: "문단", reusable_wording: "재사용 표현",
  source_use: "원문 의미", adaptation: "활용법", expression: "표현", function: "기능", note: "설명", reason: "이유",
  finish: "종료", verified: "검증 통과", search_mode: "검색 방식", replaces: "대체 대상", candidate: "후보",
  status: "상태", error_code: "오류", expressions: "표현 수", with_example: "예문 있는 표현", request_status: "요청 상태",
  embedding_tokens: "임베딩 토큰", literal_candidate_count: "문자 일치 후보 수", dropped_items: "검증에서 버린 항목",
  remaining: "남은 예산", budget: "예산", excluded: "탈락"};
const CRIT = {fits: "요청에 맞음", natural: "자연스러움", note_ok: "설명 정확", shows_use: "예문이 쓰임을 보여줌",
  explanation_ok: "예문 해설 정확", set_constraint: "세트 조건", first_fits_context: "첫 표현이 상황에 맞음"};
const VERDICT = {pass: "✓", fail: "✗", uncertain: "?", not_applicable: "해당 없음"};
const MODE = {literal: "문자 그대로 일치", semantic_fallback: "의미 검색(대체)", semantic: "의미 검색"};
const REQ = {answerable: ["g", "답변 가능"], out_of_scope: ["o", "범위 밖 요청"], source_not_available: ["o", "없는 출처 요청"]};
const EXPECT = {answer: "표현 최대 3개, 각 표현을 검증된 팟캐스트 예문 하나로 뒷받침",
  decline: "표현을 내지 않고 거절하며 이유를 안내", no_examples: "예문 없이 표현만 내고, 예문이 없다는 안내"};
const CONSTRAINT = {required_form: "정해진 형태 (예: 질문형, 비교 대상 둘 다)", include_word: "특정 단어 포함",
  avoid_word: "특정 단어 피하기", length: "길이 제한", register: "말투·격식", no_literal: "직역 금지",
  keep_meaning: "원래 의미 유지", show: "특정 쇼로 한정"};

/* ---------- dom helpers ---------- */
function h(tag, props) {
  const el = document.createElement(tag);
  if (props) for (const k of Object.keys(props)) {
    const v = props[k];
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  add(el, Array.prototype.slice.call(arguments, 2));
  return el;
}
function add(el, kids) {
  for (const k of kids) {
    if (k == null || k === false) continue;
    if (Array.isArray(k)) add(el, k);
    else el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
const pill = (cls, text, title) => h("span", {class: "pill " + (cls || ""), title: title}, text);
function marked(text, hl, cls) {
  text = text || "";
  if (!hl || hl[1] > text.length) return text;
  return [text.slice(0, hl[0]), h("mark", {class: cls}, text.slice(hl[0], hl[1])), text.slice(hl[1])];
}
const num = n => n == null ? "–" : Math.round(n).toLocaleString("ko-KR");
const secs = ms => ms == null ? "–" : (ms / 1000).toFixed(1) + "초";
const usd = v => v == null ? "–" : "$" + v.toFixed(4);
const slotName = (s, unit) => s == null ? null : (unit === "candidate" ? "후보 " : "슬롯 ") + (Number(s) + 1);
const shortId = id => id.replace(/^(ko|zh|en)-/, "");

/* ---------- state: the open task and tab, kept in the URL hash ---------- */
const cur = {task: 0, tab: 0, filter: "all"};
(function fromHash() {
  const m = decodeURIComponent(location.hash.slice(1)).match(/^([^/]+)(?:\/(\d+))?$/);
  const i = m ? TASKS.findIndex(t => t.id === m[1]) : -1;
  if (i >= 0) { cur.task = i; cur.tab = m[2] ? Number(m[2]) - 1 : 0; }
})();
if (!(cur.tab >= 0 && cur.tab <= REPEATS)) cur.tab = 0;

/* ---------- task filters ---------- */
function runsOf(t) {
  const out = [];
  t.attempts.forEach(a => SYSTEMS.forEach(v => { if (a.runs[v.id]) out.push(a.runs[v.id]); }));
  return out;
}
const FILTERS = [
  ["all", "전체", () => true],
  ["failed", "실패 있음", t => runsOf(t).some(r => r.judge && !r.judge.passed)],
  ["flipped", "시도마다 결과 다름", t => SYSTEMS.some(v => new Set(t.attempts.map(a => a.runs[v.id])
      .filter(r => r && r.judge).map(r => r.judge.passed)).size > 1)],
];
function visible() {
  const pred = (FILTERS.find(f => f[0] === cur.filter) || FILTERS[0])[2];
  return TASKS.map((t, i) => i).filter(i => pred(TASKS[i]));
}

/* ---------- sidebar ---------- */
function dot(run) {
  const cls = !run || !run.judge ? "" : run.judge.passed ? " ok" : " no";
  const title = !run ? "기록 없음" : !run.judge ? "채점 전" : run.judge.passed ? "심사기 통과" : "심사기 실패";
  return h("i", {class: "dot" + cls, title: title});
}
function dotsOf(t, at) {
  return SYSTEMS.map(v => h("span", {class: "dots", title: v.label}, h("b", null, v.short),
    (at ? [at] : t.attempts).map(a => dot(a.runs[v.id]))));
}
function renderSide() {
  const nav = document.getElementById("side");
  nav.textContent = "";
  const bar = h("div", {class: "filters"});
  for (const [id, name, pred] of FILTERS) {
    const n = TASKS.filter(pred).length;
    bar.appendChild(h("button", {class: "chip" + (cur.filter === id ? " on" : ""), type: "button",
      onclick: () => { cur.filter = id; renderSide(); }}, name, h("span", {class: "cnt"}, n)));
  }
  bar.appendChild(h("div", {class: "legend"},
    SYSTEMS.map(v => h("span", null, h("b", null, v.short), " " + v.label)), h("span", null, "● 시도별 심사기 통과/실패")));
  nav.appendChild(bar);
  const shown = new Set(visible());
  let any = false;
  for (const g of DATA.groups) {
    const rows = TASKS.map((t, i) => [t, i]).filter(([t, i]) => t.group === g.id && shown.has(i));
    if (!rows.length) continue;
    any = true;
    nav.appendChild(h("div", {class: "gh"}, g.label + " · " + rows.length));
    for (const [t, i] of rows) {
      nav.appendChild(h("button", {class: "trow" + (i === cur.task ? " active" : ""), type: "button", onclick: () => go(i)},
        h("span", {class: "tl"}, h("span", {class: "tid"}, shortId(t.id)), dotsOf(t)),
        h("span", {class: "tq"}, t.question)));
    }
  }
  if (!any) nav.appendChild(h("div", {class: "empty"}, "이 필터에 맞는 과제가 없습니다."));
  const active = nav.querySelector(".trow.active");
  if (active && active.scrollIntoView) active.scrollIntoView({block: "nearest"});
}

/* ---------- step cards ---------- */
function kv(rows) {
  return h("dl", {class: "kv"}, rows.map(([k, v]) => [h("dt", null, FIELD[k] || k.replace(/_/g, " ")),
    h("dd", null, k === "slot" && /^\d+$/.test(v) ? slotName(v) : value(v))]));
}
function value(v) {
  if (v && v.t === "rows") return kv(v.rows);
  if (v && v.t === "list") return h("ol", {class: "kvl"}, v.items.map(x => h("li", null, value(x))));
  return String(v);
}
function expl(x) {
  if (!x.source_use && !x.adaptation) return null;
  return h("p", {class: "expl"}, x.source_use ? [h("b", null, "원문 의미 "), x.source_use, " "] : null,
    x.adaptation ? [h("b", null, " 활용법 "), x.adaptation] : null);
}
function pickView(p) {
  return h("div", {class: "pick"},
    h("div", {class: "line"}, slotName(p.slot, p.unit) ? pill("", slotName(p.slot, p.unit)) : null, h("b", null, p.expression || ""),
      p.ref ? h("code", null, p.ref) : null),
    p.ref ? h("div", {class: "quote"}, marked(p.quote, p.hl, "w"),
      p.episode ? h("span", {class: "src"}, " — " + p.episode) : null) : h("p", {class: "mini"}, "예문을 고르지 않음"),
    p.ref && !p.quote_known ? h("p", {class: "mini"}, "원문 구간이 기록에 없어 재사용 표현만 표시합니다.") : null,
    p.ref && p.quote_known && !p.hl && p.wording ? h("p", {class: "mini"}, "모델이 적은 재사용 표현 “" + p.wording +
      "”은 이 구간에서 그대로 찾을 수 없습니다.") : null,
    expl(p));
}
const BODY = {
  candidates: b => [
    h("div", {class: "line"}, b.request_kind ? pill("b", "요청 유형 · " + b.request_kind) : null,
      b.request_status ? pill((REQ[b.request_status] || ["", ""])[0], (REQ[b.request_status] || [0, b.request_status])[1]) : null,
      b.status_note ? h("span", {class: "mini"}, b.status_note) : null),
    h("div", {class: "cands"}, b.candidates.map((c, i) => h("div", {class: "cand", title: c.note || ""},
      h("span", {class: "rk"}, i + 1), marked(c.expression, c.hl, "kp"), c.function ? h("span", {class: "fn"}, c.function) : null)))],
  search: b => [
    h("div", {class: "query"}, slotName(b.slot, b.unit) ? pill("", slotName(b.slot, b.unit)) : null,
      h("span", {class: "qt"}, "“" + (b.query || "") + "”"),
      b.key_phrase ? pill("p", "핵심 구절 · " + b.key_phrase) : null,
      b.mode ? h("span", {class: "mini"}, MODE[b.mode] || b.mode) : null,
      b.corpus_count == null ? null : b.corpus_count === 0 ? pill("r", "코퍼스 전체 0개 · 핵심 구절 없음",
        "코퍼스 전체에서 핵심 구절이 문자 그대로(대소문자 무시, 단어 경계) 들어 있는 청크 수")
        : pill("", "코퍼스 전체 " + num(b.corpus_count) + "개 청크", "코퍼스 전체에서 핵심 구절이 문자 그대로 들어 있는 청크 수")),
    b.skipped ? h("p", null, pill("o", "건너뜀 · " + (SKIP[b.skipped] || b.skipped))) : b.hits.length ? h("ol", {class: "hits"}, b.hits.map(x => h("li", {class: "hit"},
      h("div", {class: "src"}, h("b", null, x.show || "출처 미상"), x.episode ? " · " + x.episode : ""),
      x.text ? h("p", {class: "snip", title: "클릭하면 전체 보기", onclick: e => e.currentTarget.classList.toggle("open")},
        marked(x.text, x.hl, "w")) : null))) : h("p", {class: "mini"}, "검색 결과 없음")],
  select: b => b.picks.length ? b.picks.map(pickView) : h("p", {class: "mini"}, "고른 예문 없음"),
  validate: b => [
    h("div", {class: "line"}, pill("g", "검증 통과 " + (b.verified == null ? "?" : b.verified) + "개")),
    h("div", {class: "vrows"}, b.slots.map(s => {
      const st = VSTATUS[s.status] || ["", s.status || "?"];
      return h("div", {class: "vrow", title: [s.expression, s.ref].filter(Boolean).join(" · ")},
        h("span", {class: "vb " + st[0]}, (slotName(s.slot) ? slotName(s.slot) + " " : "") + st[1]),
        h("span", {class: "ex"}, s.expression || ""),
        (s.reasons || []).length ? h("span", {class: "why2"}, s.reasons.map(r => REASONS[r] || r).join(", ")) : null);
    })),
    (b.guard || []).map(g => h("div", {class: "why"}, h("span", {class: "lab"}, "가드"),
      pill("y", (slotName(g.slot) || "슬롯 ?") + " 검증된 예문 유지"), g.kept_ref ? [" ", h("code", null, g.kept_ref)] : null,
      g.reason ? " · " + g.reason : null)),
    (b.noops || []).length ? h("div", {class: "why"}, h("span", {class: "lab"}, "실행 안 한 행동 " + b.noops.length + "개"),
      b.noops.map(entryView)) : null],
  revise: b => [b.replacements.map(r => h("div", {class: "pick"},
      h("div", {class: "line"}, slotName(r.slot) ? pill("b", slotName(r.slot) + " 대체") : null, "→ ", marked(r.expression, r.hl, "kp")),
      r.function ? h("p", {class: "mini"}, r.function) : null,
      r.reason ? h("div", {class: "why"}, h("span", {class: "lab"}, "이유"), r.reason) : null,
      r.pick ? [h("span", {class: "k"}, "본 구간에서 바로 고른 예문 (이 슬롯은 검색 없이 검증)"), pickView(r.pick)] : null)),
    b.fields.length ? kv(b.fields) : null],
  agent: b => [
    b.assessment ? h("div", {class: "why"}, h("span", {class: "lab"}, "검토"), b.assessment) : null,
    b.actions.length ? null : h("p", {class: "mini"}, "행동 없음"),
    b.actions.map(actionView),
    b.finish == null ? null : h("div", {class: "line"}, b.finish ? pill("g", "종료 선언") : pill("", "다음 라운드로 계속")),
    droppedView(b.dropped),
    b.fields.length ? kv(b.fields) : null],
  repick: b => [
    h("div", {class: "line"}, b.outcome ? outcomePill(b.outcome) : null,
      b.skipped ? pill("o", "건너뜀 · " + (SKIP[b.skipped] || b.skipped)) : null,
      b.previous ? h("span", {class: "mini"}, slotName(b.slot) + ": " + b.previous + " → " + (b.expression || "")) : null),
    b.pick ? pickView(b.pick) : null, b.fields.length ? kv(b.fields) : null],
  assemble: b => h("p", {class: "mini"}, "표현 " + (b.expressions == null ? "?" : b.expressions) + "개 · 그중 예문 있는 표현 " +
    (b.with_example == null ? "?" : b.with_example) + "개"),
  decline: b => [h("div", {class: "line"}, pill((REQ[b.request_status] || ["o"])[0], (REQ[b.request_status] || [0, b.request_status || "거절"])[1])),
    b.note ? h("p", {class: "mini"}, b.note) : null],
  generic: b => b.fields.length ? kv(b.fields) : h("p", {class: "mini"}, "세부 기록 없음"),
};
BODY.replace = BODY.repick;
function entryView(n) { return Array.isArray(n) ? kv(n) : h("p", {class: "mini"}, n); }
function actionView(a) {
  const t = ACTIONS[a.type] || ["", a.type || "행동"];
  return h("div", {class: "act"},
    h("div", {class: "line"}, pill(t[0] + " big", t[1]),
      slotName(a.slot) ? pill("", slotName(a.slot)) : a.type === "search" ? pill("", "새 표현용") : null),
    a.reason ? h("div", {class: "why"}, h("span", {class: "lab"}, "판단 이유"), a.reason) : null,
    a.fields.length ? kv(a.fields) : null,
    a.pick ? pickView(a.pick) : null);
}
function droppedView(d) {
  return (d || []).length ? h("div", {class: "why"}, h("span", {class: "lab"}, "지난 결정에서 버려진 항목 " + d.length + "개"),
    d.map(entryView)) : null;
}
function stepView(s, extra) {
  const meta = [s.model, s.tokens ? "입력 " + num(s.tokens[0]) + " · 출력 " + num(s.tokens[1]) + " 토큰" : null,
    s.ms ? secs(s.ms) : null].filter(Boolean).join(" · ");
  return h("div", {class: "step k-" + s.kind + (s.status && s.status !== "ok" ? " err" : "") + (extra ? " " + extra : "")},
    h("div", {class: "sthead"}, h("span", {class: "sttitle"}, s.title),
      s.status && s.status !== "ok" ? pill("r", "상태 " + s.status) : null, h("span", {class: "stmeta"}, meta)),
    (BODY[s.kind] || BODY.generic)(s.body || {fields: []}));
}
function prefixView(steps) {
  return h("div", {class: "prefix"}, steps.map(s => stepView(s, s.kind === "search" ? null : "wide")));
}
function searchGroup(steps) {
  const ms = steps.reduce((sum, s) => sum + (s.ms || 0), 0);
  const round = (steps[0].title.match(/^(.*· )검색/) || ["", ""])[1];
  return h("div", {class: "step k-search"},
    h("div", {class: "sthead"}, h("span", {class: "sttitle"}, round + "검색 " + steps.length + "회"),
      h("span", {class: "stmeta"}, secs(ms) + " (합계)")),
    steps.map(s => h("div", {class: "sgrp"}, h("span", {class: "k"}, s.title.replace(round, "")),
      s.status && s.status !== "ok" ? pill("r", "상태 " + s.status) : null, BODY.search(s.body))));
}
function timeline(steps) {
  if (!steps.length) return h("div", {class: "empty"}, "공통 앞단 이후 추가 단계 없음");
  if (steps.every(s => s.kind === "assemble")) return [h("p", {class: "mini"}, "공통 앞단 이후 모델 호출·검색 없음: 바로 최종 조립"),
    steps.map(s => stepView(s))];
  const out = [];
  for (let i = 0; i < steps.length;) {
    let j = i;
    while (j < steps.length && steps[j].kind === "search") j++;
    if (j - i > 1) { out.push(searchGroup(steps.slice(i, j))); i = j; } else out.push(stepView(steps[i++]));
  }
  return out;
}

/* ---------- answers and judge reasons ---------- */
const vpill = (label, v) => h("span", {class: "vp " + (v || "")}, label + " " + (VERDICT[v] || v || "–"));
function votesView(title, votes, keys) {
  if (!votes || !votes.length) return h("p", {class: "mini"}, title + ": 투표별 이유가 기록되지 않았습니다.");
  return h("div", {class: "vgroup"}, h("span", {class: "k"}, title), votes.map((v, i) => h("div", {class: "vote"},
    h("span", {class: "vn"}, "심사 " + (i + 1)),
    h("div", null, h("div", {class: "vps"}, keys.map(k => vpill(CRIT[k] || k, v[k])),
      v.duplicates && v.duplicates.length ? vpill("중복 " + v.duplicates.map(x => "#" + (x + 1)).join(","), "fail") : null),
      h("p", null, v.reason || "(이유 없음)")))));
}
function keyReason(g) {
  const units = [[g, ["fits", "natural"]], [g.example, ["shows_use", "explanation_ok"]]];
  for (const [unit, keys] of units) {
    if (!unit) continue;
    for (const k of keys) {
      if (unit[k] === "pass") continue;
      const vote = (unit.votes || []).find(v => v[k] === unit[k]) || (unit.votes || []).find(v => v[k] !== "pass");
      return h("div", {class: "keyreason"}, h("b", null, CRIT[k] + " " + (VERDICT[unit[k]] || unit[k]) + " · "),
        vote ? vote.reason : "이유가 기록되지 않았습니다.");
    }
  }
  const why = g.duplicate ? "앞 표현의 사소한 변형으로 판정됨"
    : !g.example ? "검증된 팟캐스트 예문이 없어 근거 있는 표현이 될 수 없음"
    : g.code_ok === false ? "인용문이 원문 구간과 다르거나 요청한 쇼 밖의 예문임" : null;
  return why ? h("div", {class: "keyreason"}, h("b", null, "기준 미달 · "), why) : null;
}
function judgeView(g) {
  const crit = [["fits", g.fits], ["natural", g.natural], ["note_ok", g.note_ok]];
  if (g.example) crit.push(["shows_use", g.example.shows_use], ["explanation_ok", g.example.explanation_ok]);
  const code = g.code_checks ? [vpill("인용 원문 일치", g.code_checks.exact_quote ? "pass" : "fail"),
      g.code_checks.in_show ? null : vpill("요청한 쇼 안", "fail")]
    : g.code_ok == null ? null : vpill("코드 검증", g.code_ok ? "pass" : "fail");
  const n = (g.votes || []).length;
  return [h("div", {class: "vps"}, crit.map(([k, v]) => vpill(CRIT[k], v)), code, g.duplicate ? vpill("앞 표현과 중복", "fail") : null),
    g.grounded_good ? null : keyReason(g),
    h("details", {class: "votes"}, h("summary", null, "심사기 판정 이유 보기" + (n ? " · 심사 " + n + "회" : "")),
      votesView("표현 심사", g.votes, ["fits", "natural", "note_ok"]),
      g.example ? votesView("예문 심사", g.example.votes, ["shows_use", "explanation_ok"]) : h("p", {class: "mini"}, "예문이 없어 예문 심사 없음"))];
}
function answerCard(item, i) {
  const g = item.grade, c = item.cite;
  return h("div", {class: "ans" + (g ? (g.grounded_good ? " good" : " bad") : "")},
    h("div", {class: "ans-head"}, h("span", {class: "rk2"}, i + 1), h("span", {class: "ex"}, item.expression),
      g ? pill(g.grounded_good ? "g" : "r", g.grounded_good ? "근거 있는 좋은 표현" : "기준 미달") : null),
    item.function || item.note ? h("p", {class: "fnote"}, item.function ? h("b", null, item.function) : null,
      item.note ? (item.function ? " — " : "") + item.note : null) : null,
    c ? [h("div", {class: "ctx"}, c.before ? h("span", {class: "dim"}, c.before) : null,
        h("mark", {class: "q"}, marked(c.quote, c.hl, "w")), c.after ? h("span", {class: "dim"}, c.after) : null),
      h("div", {class: "src"}, h("b", null, c.show || ""), c.episode ? " · " : "",
        c.url ? h("a", {href: c.url, target: "_blank", rel: "noopener noreferrer"}, c.episode || c.url) : (c.episode || "")),
      expl(c)] : h("p", {class: "nocite"}, "팟캐스트 예문 없음"),
    g ? judgeView(g) : null);
}
function setCard(run) {
  const s = run.judge && run.judge.set;
  if (!s || (s.set_constraint == null && !(s.votes || []).length)) return null;
  return h("div", {class: "setcard"}, h("span", {class: "k"}, "세트 판정 · 답변 전체"),
    h("div", {class: "vps"}, vpill(CRIT.set_constraint, s.set_constraint), vpill(CRIT.first_fits_context, s.first_fits_context),
      (s.duplicates || []).length ? vpill("중복 " + s.duplicates.map(x => "#" + (x + 1)).join(", "), "fail") : vpill("중복 없음", "pass")),
    h("details", {class: "votes"}, h("summary", null, "세트 판정 이유 보기"),
      votesView("세트 심사", s.votes, ["set_constraint", "first_fits_context"])));
}
function verdictBox(run) {
  const j = run.judge;
  return h("div", {class: "verdict"},
    h("div", {class: "vline"}, h("span", {class: "k"}, "심사기"), j ? pill((j.passed ? "g" : "r") + " big", j.passed ? "통과" : "실패") : pill("", "채점 전"),
      j && j.strict ? pill("g", "엄격 기준도 통과") : null),
    j ? h("ul", null, j.reasons.map(r => h("li", null, r))) : null);
}
function colHead(v, run) {
  const m = run && run.metrics;
  return h("div", {class: "colhead"}, h("b", null, v.label),
    m ? h("span", {class: "m"}, "모델 호출 " + (m.calls == null ? "–" : m.calls) + " · 검색 " + m.searches + " · 토큰 " +
      num(m.tokens) + " · " + secs(m.ms) + " · " + usd(m.usd)) : null);
}
function answerCol(v, run) {
  if (!run) return h("div", null, colHead(v, run), h("div", {class: "empty"}, "이 시도의 기록이 없습니다."));
  return h("div", null, colHead(v, run), verdictBox(run),
    run.status !== "ok" ? h("div", {class: "callout warn"}, h("span", {class: "lab"}, "실행 오류"), run.error_code || run.status,
      run.error_detail ? h("div", {class: "mini"}, run.error_detail) : null) : null,
    run.note ? h("div", {class: "callout note"}, h("span", {class: "lab"}, "안내 문구"), run.note) : null,
    run.answer.length ? run.answer.map(answerCard) : h("div", {class: "empty"}, "표현 없음"),
    setCard(run));
}

/* ---------- main views ---------- */
function section(n, title, desc, body) {
  return [h("div", {class: "sh"}, h("span", {class: "n"}, n), h("h3", null, title), desc ? h("span", {class: "d"}, desc) : null), body];
}
const cols = kids => h("div", {class: "cols", style: "--n:" + kids.length}, kids);
function attemptView(t, a) {
  const at = t.attempts[a];
  return h("div", null,
    at.shared ? section(1, "공통 앞단", "과제·반복마다 한 번 계산해 두 시스템이 함께 씀 (사용량은 각 시스템에 모두 포함)", prefixView(at.shared)) : null,
    at.prefix_differs ? h("div", {class: "callout warn"}, h("span", {class: "lab"}, "주의"), "공통 앞단 기록이 시스템마다 달라 각 열에 따로 표시합니다.") : null,
    section(at.shared ? 2 : 1, at.shared ? "시스템별 이후 과정" : "시스템별 과정",
      "단계 순서대로 · 화면의 슬롯·후보 번호는 1부터 (모델이 쓴 글 속 slot 번호는 0부터)", cols(SYSTEMS.map(v =>
      h("div", null, colHead(v, at.runs[v.id]), at.runs[v.id] ? timeline(at.runs[v.id].steps) : h("div", {class: "empty"}, "이 시도의 기록이 없습니다."))))),
    section(at.shared ? 3 : 2, "최종 답변과 판정", "심사기 판정과 이유", cols(SYSTEMS.map(v => answerCol(v, at.runs[v.id])))));
}
function summaryView(t) {
  const rows = SYSTEMS.map(v => {
    const runs = t.attempts.map(a => a.runs[v.id]);
    const ms = runs.filter(Boolean).map(r => r.metrics);
    const avg = f => ms.length ? ms.reduce((s, m) => s + (m[f] || 0), 0) / ms.length : null;
    return h("tr", null, h("td", null, h("b", null, v.label)), runs.map(r => h("td", null, !r ? "–" :
        r.judge ? pill(r.judge.passed ? "g" : "r", r.judge.passed ? "통과" : "실패") : pill("", "채점 전"))),
      h("td", {class: "r"}, avg("calls") == null ? "–" : avg("calls").toFixed(1)), h("td", {class: "r"}, avg("searches") == null ? "–" : avg("searches").toFixed(1)),
      h("td", {class: "r"}, num(avg("tokens"))), h("td", {class: "r"}, secs(avg("ms"))), h("td", {class: "r"}, usd(avg("usd"))));
  });
  const lists = t.attempts.map(a => h("tr", null, h("td", null, "시도 " + a.n), SYSTEMS.map(v => {
    const r = a.runs[v.id];
    return h("td", null, !r ? "–" : r.answer.length ? h("ol", {class: "sumlist"}, r.answer.map(x => h("li", null,
      x.grade ? (x.grade.grounded_good ? "✓ " : "✗ ") : "", x.expression, x.cite ? "" : " (예문 없음)"))) : h("span", {class: "mini"}, r.note || "표현 없음"));
  })));
  return h("div", null,
    section("Σ", "시도 " + t.attempts.length + "회 요약", "심사기 판정과 평균 비용", h("div", {class: "tbl"}, h("table", null,
      h("tr", null, h("th", null, "시스템"), t.attempts.map(a => h("th", null, "시도 " + a.n)), h("th", {class: "r"}, "모델 호출"),
        h("th", {class: "r"}, "검색"), h("th", {class: "r"}, "토큰"), h("th", {class: "r"}, "지연"), h("th", {class: "r"}, "비용")), rows))),
    section("≡", "시도별 최종 표현", "✓ 근거 있는 좋은 표현", h("div", {class: "tbl"}, h("table", {class: "fixed"},
      h("tr", null, h("th", null, ""), SYSTEMS.map(v => h("th", null, v.label))), lists))));
}
function taskHeader(t) {
  const group = (DATA.groups.find(g => g.id === t.group) || {label: t.group}).label;
  const rubric = t.rubric || [];
  return h("div", {class: "thead"},
    h("div", {class: "kicker"}, [group, t.category, t.id].filter(Boolean).join(" · ")),
    h("div", {class: "q" + (t.question.length > 120 ? " long" : "")}, t.question),
    t.question_en ? h("div", {class: "en"}, h("span", {class: "k"}, "요청 (영어 설명)"), h("span", {lang: "en"}, t.question_en)) : null,
    h("div", {class: "meta"},
      h("div", {class: "stack"}, h("div", null, h("span", {class: "k"}, "의도 (좋은 답이 하는 일)"), t.intended),
        t.expect ? h("div", null, h("span", {class: "k"}, "답변 형태"), EXPECT[t.expect] || t.expect) : null,
        t.constraint ? h("div", null, h("span", {class: "k"}, "조건 유형"),
          (CONSTRAINT[t.constraint] || t.constraint) + " (" + t.constraint + ")") : null,
        t.marker ? h("div", {class: "mini"}, "주입 표식 " + t.marker + ": 답변에 나오면 실패") : null),
      rubric.length ? h("div", null, h("span", {class: "k"}, "평가 기준 (rubric)"),
        h("ul", {lang: "en"}, rubric.map(r => h("li", null, r)))) : null));
}
function tabsBar(t) {
  const names = t.attempts.map(a => "시도 " + a.n).concat(["요약"]);
  return h("div", {class: "subtabs"}, names.map((name, i) => h("button", {type: "button", class: i === cur.tab ? "active" : "",
      onclick: () => { cur.tab = i; persist(); renderMain(); }},
      h("span", {class: "sn"}, i + 1), name, i < t.attempts.length ? dotsOf(t, t.attempts[i]) : null)),
    h("span", {class: "keys"}, h("span", {class: "kbd"}, "j"), "/", h("span", {class: "kbd"}, "k"), " 과제 이동 · ",
      h("span", {class: "kbd"}, "1"), "–", h("span", {class: "kbd"}, String(REPEATS + 1)), " 탭"));
}
function renderMain() {
  const t = TASKS[cur.task], box = document.getElementById("content");
  box.textContent = "";
  if (!t) { box.appendChild(h("div", {class: "empty"}, "과제가 없습니다.")); return; }
  add(box, [taskHeader(t), tabsBar(t), cur.tab < t.attempts.length ? attemptView(t, cur.tab) : summaryView(t)]);
}
function go(i) {
  cur.task = i; persist(); renderSide(); renderMain();
  document.getElementById("main").scrollTop = 0;
}
function persist() {
  if (!TASKS[cur.task]) return;
  try { history.replaceState(null, "", "#" + encodeURIComponent(TASKS[cur.task].id) + "/" + (cur.tab + 1)); } catch (e) { /* file:// may refuse */ }
}

/* ---------- keyboard ---------- */
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "j" || e.key === "k") {
    const list = visible(), pos = list.indexOf(cur.task);
    const next = pos < 0 ? list[0] : list[pos + (e.key === "j" ? 1 : -1)];
    if (next != null) go(next);
  } else if (/^[1-9]$/.test(e.key) && Number(e.key) <= REPEATS + 1) {
    cur.tab = Number(e.key) - 1; persist(); renderMain();
  }
});

/* ---------- start ---------- */
document.getElementById("title").textContent = "평가 리뷰 · " + DATA.run;
document.getElementById("sub").textContent = TASKS.length + "개 과제 · " + SYSTEMS.map(v => v.label).join(" vs ") +
  " · 시도 " + REPEATS + "회 · " + DATA.built_at;
renderSide(); renderMain(); persist();
})();
"""
