"""Results for the two systems, the baseline workflow and the agent, on the same tasks, k runs each.

Reads   <run>/manifest.json, <run>/<system>/attempts.jsonl, <run>/grades/grades.jsonl (with
        grades/manifest.json)
Writes  <run>/report/results.md and results.json, and <run>/report/logs/<system>.jsonl: one compact
        line per attempt (answer, verdict and one short summary per trace step), small enough to commit

Every quality and cost number comes from grade rows (LLM judge, majority of 3 votes); attempts
without a grade are listed, never guessed. Decision rounds, prefix states and failing steps come
from each attempt's trace. No model, network or database calls.
"""

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random
import re

SYSTEMS = {"baseline": "Baseline", "agent": "Agent"}  # report order: the fixed workflow, then the LLM agent
REPEATS = 3
INFRASTRUCTURE_ERRORS = {"model_unavailable", "search_unavailable", "storage_unavailable", "embedding_unavailable",
                         "corpus_not_ready", "exception"}
ROUND_STAGE = re.compile(r"(agent|revise)_\d+")  # one decision round after the shared first stage
REVIEW_VERIFIED = 3  # prefix state: all 3 answer slots verified (review) vs fewer (recovery)
BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES = 7, 4000
PASS_MARGIN = -0.05  # pass non-inferiority: the CI lower bound of agent - baseline is above -5 pp
EMPTY_LIMIT = 0.03  # empty-answer rate difference (point estimate) at most +3 pp
UNGRADED_SHOWN = 20
LOG_TEXT = 100  # characters kept of a query, an expression or an assessment in a log step
TODO = ("> **TODO (human):** write one paragraph of failure analysis here: pick one failure from the candidates "
        "below, say which step went wrong and why. Intentionally left blank; not generated.")


# ---------- reading ----------

def read_jsonl(path: Path) -> list[dict]:
    """Complete lines only: while a run is in progress the last line may still be half written."""
    if not path.exists():
        return []
    text = path.read_text()
    complete = text[:text.rfind("\n") + 1]
    return [json.loads(line) for line in complete.splitlines() if line.strip()]


def attempt_key(row: dict) -> str:
    """The key the grader writes: <task>/<system>/<attempt>."""
    return f"{row['task_id']}/{row['variant']}/{row['attempt']}"


def marker_found(task: dict | None, result: dict | None) -> bool:
    """Whether an injected instruction's marker reached the answer (fails every expectation)."""
    marker = (task or {}).get("marker")
    return bool(marker) and marker in ((result or {}).get("answer") or "")


def group(category: str) -> str:
    """Regular categories stay as they are; every edge/* and unanswerable/* task forms one group."""
    kind = category.split("/", 1)[0]
    return kind if kind in ("edge", "unanswerable") else category


# ---------- statistics ----------

def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def nearest_rank(values, q: float):
    """Nearest-rank percentile: the ceil(q * n)-th smallest value (no interpolation)."""
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    rank = max(1, math.ceil(round(q * len(ordered), 9)))
    return ordered[rank - 1]


def rate(rows: list[dict], field: str = "passed") -> dict:
    passed = sum(bool(r.get(field)) for r in rows)
    return {"passed": passed, "n": len(rows), "rate": passed / len(rows) if rows else None}


def by_task(grades: list[dict], system: str) -> dict:
    """{task_id: {attempt: grade}} for one system."""
    tasks = defaultdict(dict)
    for g in grades:
        if g["variant"] == system:
            tasks[g["task_id"]][g["attempt"]] = g
    return tasks


def pattern(attempts: dict, repeats: int = REPEATS) -> str:
    """Pass marks in run order, e.g. 'P F P'; '·' marks a run without a grade."""
    return " ".join("·" if a not in attempts else "P" if attempts[a]["passed"] else "F"
                    for a in range(1, repeats + 1))


def pass_k(grades: list[dict], system: str, repeats: int = REPEATS) -> dict:
    """pass@k (any run passes) and pass^k (all runs pass), over tasks with all k runs graded."""
    complete = [[attempts[a]["passed"] for a in range(1, repeats + 1)]
                for attempts in by_task(grades, system).values()
                if all(a in attempts for a in range(1, repeats + 1))]
    n, any_pass, all_pass = len(complete), sum(map(any, complete)), sum(map(all, complete))
    return {"tasks": n, "any_pass": any_pass, "all_pass": all_pass,
            "pass_at_k": any_pass / n if n else None, "pass_hat_k": all_pass / n if n else None}


def flips(grades: list[dict], system: str, order: dict, repeats: int = REPEATS) -> list[dict]:
    """Tasks whose graded runs disagree on pass/fail, in task-file order."""
    rows = []
    for task_id, attempts in by_task(grades, system).items():
        if len({bool(g["passed"]) for g in attempts.values()}) > 1:
            category = next(iter(attempts.values()))["category"]
            rows.append({"task_id": task_id, "category": category, "pattern": pattern(attempts, repeats)})
    return sorted(rows, key=lambda r: (order.get(r["task_id"], len(order)), r["task_id"]))


def trace_metrics(row: dict) -> dict:
    """What the system did after the shared first stage, from one attempt's trace, model events and cost.

    Steps marked details.shared are the prefix; everything else is the system's own continuation.
    A continuation search is wasted when no span it showed backs an example in the final answer
    (its ref_prefix starts no verified ref of the last validation)."""
    result, cost = row.get("result") or {}, row.get("cost") or {}
    trace = result.get("trace") or []
    prefix_steps = [span for span in trace if (span.get("details") or {}).get("shared")]
    own = [span for span in trace if not (span.get("details") or {}).get("shared")]
    searches = [span for span in own if span.get("stage", "").startswith("search_")
                and not (span.get("details") or {}).get("skipped")]
    validations = [span for span in trace if span.get("stage", "").startswith("validate_")]
    final_refs = [slot["ref"] for slot in ((validations[-1].get("details") or {}).get("slots") or [])
                  if slot.get("status") == "verified" and slot.get("ref")] if validations else []
    events = result.get("model_events") or []

    def tokens(shared: bool):
        usage = [e.get("usage") or {} for e in events if bool(e.get("shared")) == shared]
        return sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in usage)

    workflow, prefix = (cost.get("workflow") or {}).get("usd"), (cost.get("shared_prefix") or {}).get("usd")
    return {"rounds": sum(bool(ROUND_STAGE.fullmatch(span.get("stage", ""))) for span in own),
            "continuation_calls": sum(not e.get("shared") for e in events),
            "continuation_searches": len(searches),
            "wasted_searches": sum(not any(ref.startswith(f"{(span.get('details') or {}).get('ref_prefix')}h")
                                           for ref in final_refs) for span in searches),
            "prefix_tokens": tokens(True), "continuation_tokens": tokens(False),
            "prefix_ms": sum(span.get("elapsed_ms") or 0 for span in prefix_steps),
            "continuation_ms": sum(span.get("elapsed_ms") or 0 for span in own),
            "prefix_usd": prefix, "continuation_usd": None if workflow is None or prefix is None else workflow - prefix}


def empty_rate(grades: list[dict]) -> dict:
    """Share of graded expect=answer attempts with no grounded-good expression (the learner gets nothing usable)."""
    answer = [g for g in grades if g["expect"] == "answer"]
    empty = sum(not g.get("grounded_good") for g in answer)
    return {"passed": empty, "n": len(answer), "rate": empty / len(answer) if answer else None}


def system_metrics(grades: list[dict], attempts: dict | None = None) -> dict:
    """One system's numbers over its graded attempts; attempts (by key) add the trace metrics."""
    latency = [g["latency_ms"] / 1000 for g in grades if g.get("latency_ms") is not None]
    traced = [trace_metrics(attempts[g["key"]]) for g in grades if g["key"] in (attempts or {})]
    return {
        "graded": len(grades),
        "accuracy": rate(grades),
        "strict": rate(grades, "strict_passed"),
        "empty_answer": empty_rate(grades),
        "turns_mean": mean(g.get("model_calls") for g in grades),
        "rounds_mean": mean(t["rounds"] for t in traced),
        "latency_mean_s": mean(latency),
        "latency_p95_s": nearest_rank(latency, 0.95),
        "tokens_mean": mean(g.get("tokens") for g in grades),
        "cost_mean_usd": mean(g.get("workflow_cost") for g in grades),
        "traced": len(traced),
        "after_prefix": {f"{name}_mean": mean(t[name] for t in traced) for name in (
            "continuation_calls", "continuation_searches", "wasted_searches", "prefix_tokens", "continuation_tokens",
            "prefix_ms", "continuation_ms", "prefix_usd", "continuation_usd")},
    }


def subset(grades: list[dict], name: str, ids: set) -> dict:
    """Pass and strict per system over the graded attempts of these tasks."""
    own = [g for g in grades if g["task_id"] in ids]
    return {"name": name, "tasks": len(ids), **{s: {"pass": rate([g for g in own if g["variant"] == s]),
                                                   "strict": rate([g for g in own if g["variant"] == s], "strict_passed")}
                                               for s in SYSTEMS}}


def breakdown(grades: list[dict], tasks: list[dict], key) -> list[dict]:
    """subset() for each value of key(task), in task-file order."""
    return [subset(grades, name, {t["id"] for t in tasks if key(t) == name}) for name in dict.fromkeys(map(key, tasks))]


def expect_groups(grades: list[dict], tasks: list[dict]) -> list[dict]:
    """Answerable tasks (expect=answer), and the edge and unanswerable groups by category; empty groups left out."""
    ids = {"answer": {t["id"] for t in tasks if t["expect"] == "answer"},
           **{name: {t["id"] for t in tasks if group(t["category"]) == name} for name in ("edge", "unanswerable")}}
    return [subset(grades, name, members) for name, members in ids.items() if members]


def task_means(grades: list[dict], system: str, task_ids: set, field: str = "passed",
               numeric: bool = False) -> dict:
    """Per task: mean of passed (or another boolean field; numeric: a count) over that system's graded attempts."""
    def value(g):
        return float(g.get(field) or 0) if numeric else float(bool(g.get(field)))

    return {task_id: mean(value(g) for g in attempts.values())
            for task_id, attempts in by_task(grades, system).items() if task_id in task_ids}


def infrastructure_units(grades: list[dict], systems) -> list[str]:
    """Units '<task>/<attempt>' in which any of these systems ended with an infrastructure failure."""
    return sorted({f"{g['task_id']}/{g['attempt']}" for g in grades
                   if g["variant"] in systems and g.get("error_code") in INFRASTRUCTURE_ERRORS})


def comparison(grades: list[dict], a: str, b: str, task_ids: set, field: str = "passed",
               resamples: int = BOOTSTRAP_RESAMPLES, numeric: bool = False) -> dict:
    """The paired estimate: units with an infrastructure failure in either system are left out of both
    (a one-sided outage says nothing about who decides better); all units shown beside it."""
    excluded = infrastructure_units(grades, (a, b))
    kept = [g for g in grades if f"{g['task_id']}/{g['attempt']}" not in set(excluded)]
    return {**paired_bootstrap(kept, a, b, task_ids, field=field, resamples=resamples, numeric=numeric),
            "excluded_units": excluded,
            "all_units": paired_bootstrap(grades, a, b, task_ids, field=field, resamples=resamples, numeric=numeric)}


def paired_bootstrap(grades: list[dict], a: str, b: str, task_ids: set, seed: int = BOOTSTRAP_SEED,
                     resamples: int = BOOTSTRAP_RESAMPLES, field: str = "passed", numeric: bool = False) -> dict:
    """Rate a - b (passed, or field) over tasks graded in both; 95% CI by task-cluster percentile bootstrap."""
    left = task_means(grades, a, task_ids, field, numeric)
    right = task_means(grades, b, task_ids, field, numeric)
    diffs = [left[t] - right[t] for t in sorted(set(left) & set(right))]
    result = {"a": a, "b": b, "tasks": len(diffs), "difference": None, "ci95": None,
              "seed": seed, "resamples": resamples}
    if not diffs:
        return result
    rng, n = random.Random(seed), len(diffs)
    means = [sum(rng.choices(diffs, k=n)) / n for _ in range(resamples)]
    result.update(difference=sum(diffs) / n, ci95=[nearest_rank(means, 0.025), nearest_rank(means, 0.975)])
    return result


def agent_vs_baseline(grades: list[dict], answer_ids: set, metrics: dict) -> dict:
    """Agent - baseline over the answerable tasks (pass, strict) and the three decision lines, each stated alone."""
    pass_, strict = (comparison(grades, "agent", "baseline", answer_ids, field=f) for f in ("passed", "strict_passed"))
    empty = [metrics[s]["empty_answer"]["rate"] for s in ("agent", "baseline")]
    empty_difference = None if None in empty else empty[0] - empty[1]
    return {"pass": pass_, "strict": strict, "empty_difference": empty_difference,
            "checks": {"pass_non_inferiority": None if pass_["ci95"] is None else pass_["ci95"][0] > PASS_MARGIN,
                       "strict_superiority": None if strict["ci95"] is None else strict["ci95"][0] > 0,
                       "empty_answers": None if empty_difference is None else empty_difference <= EMPTY_LIMIT},
            "pass_margin": PASS_MARGIN, "empty_limit": EMPTY_LIMIT}


# ---------- prefix state ----------

def prefix_verified(row: dict) -> int | None:
    """Verified answer slots after the shared first stage (validate_select_1), from one attempt's trace."""
    for span in (row.get("result") or {}).get("trace") or []:
        if span.get("stage") == "validate_select_1":
            verified = (span.get("details") or {}).get("verified")
            return verified if isinstance(verified, int) else None
    return None


def prefix_states(attempts: dict) -> dict:
    """'<task>/<attempt>' -> 'review' (3 verified) or 'recovery' (< 3), read from either system (the first stage is shared)."""
    states = {}
    for row in attempts.values():
        verified = prefix_verified(row)
        if verified is not None:
            states.setdefault(f"{row['task_id']}/{row['attempt']}",
                              "review" if verified >= REVIEW_VERIFIED else "recovery")
    return states


def subgroups(grades: list[dict], states: dict, systems) -> dict:
    """Pass and strict per system within the review and recovery units (expect=answer only)."""
    out = {}
    for state in ("review", "recovery"):
        units = {u for u, s in states.items() if s == state}
        rows = {v: [g for g in grades if g["variant"] == v and g["expect"] == "answer"
                    and f"{g['task_id']}/{g['attempt']}" in units] for v in systems}
        out[state] = {"units": len(units), **{v: {"pass": rate(r), "strict": rate(r, "strict_passed")}
                                             for v, r in rows.items()}}
    return out


# ---------- failures and coverage ----------

def item_problems(grade: dict) -> list[str]:
    """Why each displayed expression is not grounded-good, e.g. '#2 no example'."""
    duplicates = set((grade.get("set") or {}).get("duplicates") or [])
    items, out = grade.get("items") or [], []
    for index, item in enumerate(items):
        if item.get("grounded_good"):
            continue
        problems = [f"{f}={item.get(f)}" for f in ("fits", "natural") if item.get(f) != "pass"]
        if index in duplicates:
            problems.append("duplicate")
        example = item.get("example")
        if example is None:
            problems.append("no example")
        else:
            if item.get("code_ok") is False:
                problems.append("quote not verified")
            problems += [f"{f}={example.get(f)}" for f in ("shows_use", "explanation_ok") if example.get(f) != "pass"]
        out.append(f"#{index + 1} " + ", ".join(problems or ["not grounded"]))
    if len(items) < REPEATS:
        out.append(f"{len(items)} of 3 expressions shown")
    return out


def failure_reason(grade: dict, attempt: dict | None = None, task: dict | None = None) -> str:
    """Why one non-passing attempt failed the pass rule, from the grade (plus the attempt when needed)."""
    if grade.get("status") != "ok":
        return f"status {grade.get('status')}: {grade.get('error_code') or 'no error code'}"
    result = (attempt or {}).get("result") or {}
    if grade["expect"] != "answer":
        if not result:
            return f"{grade['expect']} rule not met (attempt row unavailable)"
        expressions = result.get("expressions") or []
        reasons = [f"{len(expressions)} expressions returned instead of declining"] if expressions else []
        if not result.get("source_availability_note"):
            reasons.append("no availability note")
        return "; ".join(reasons) or f"{grade['expect']} rule not met"
    reasons = []
    if marker_found(task, result):
        reasons.append(f"injected marker {task['marker']} in answer")
    if not grade.get("set_constraint_ok", True):
        reasons.append("set constraint failed")
    if (grade.get("grounded_good") or 0) < 2:
        reasons.append(f"grounded-good {grade.get('grounded_good') or 0}/3")
        reasons += item_problems(grade)
    return "; ".join(reasons) or "unexplained; check the grade row"


def failing_step(row: dict | None) -> str:
    """Where in the trace to look: a step that errored, a decline, or verified slots before and after the decisions."""
    result = (row or {}).get("result")
    if not result:
        return "no trace (attempt row unavailable)"
    trace = result.get("trace") or []
    for span in trace:
        if span.get("status") not in (None, "ok"):
            details = span.get("details") or {}
            return f"{span.get('stage')}: {details.get('error_code') or span.get('status')}"
    declined = next((span for span in trace if span.get("stage") == "decline"), None)
    if declined:
        return f"candidates: request judged {(declined.get('details') or {}).get('request_status')}, declined"
    validations = [span for span in trace if (span.get("stage") or "").startswith("validate_")]
    final = (validations[-1].get("details") or {}).get("verified") if validations else None
    rounds = trace_metrics(row)["rounds"]
    first = prefix_verified(row)
    return (f"verified slots: first stage {'?' if first is None else first}/3 → final {'?' if final is None else final}/3 "
            f"after {rounds} round{'' if rounds == 1 else 's'}")


def candidate_failures(grades: list[dict], attempts: dict, tasks: dict, order: dict) -> list[dict]:
    """Every non-passing attempt of either system with its failing step and reason (input for the failure analysis)."""
    rows = [{"system": g["variant"], "task_id": g["task_id"], "attempt": g["attempt"], "category": g["category"],
             "step": failing_step(attempts.get(g["key"])),
             "reason": failure_reason(g, attempts.get(g["key"]), tasks.get(g["task_id"]))}
            for g in grades if not g["passed"]]
    systems = list(SYSTEMS)
    return sorted(rows, key=lambda r: (systems.index(r["system"]), order.get(r["task_id"], len(order)),
                                       r["task_id"], r["attempt"]))


def coverage(task_ids: list[str], attempts: dict, grades: dict, repeats: int = REPEATS) -> dict:
    """Per system: expected, recorded and graded attempts, recorded attempts without a grade, and error codes."""
    out = {}
    for system in SYSTEMS:
        recorded = {k for k, row in attempts.items() if row["variant"] == system}
        graded = recorded & {k for k, row in grades.items() if row["variant"] == system}
        codes = Counter(grades[k].get("error_code") for k in graded if grades[k].get("error_code"))
        out[system] = {"expected": len(task_ids) * repeats, "recorded": len(recorded), "graded": len(graded),
                       "ungraded": sorted(recorded - graded),
                       "infrastructure_failures": sum(n for c, n in codes.items() if c in INFRASTRUCTURE_ERRORS),
                       "error_codes": dict(sorted(codes.items()))}
    return out


# ---------- assembly ----------

def run_info(run: dict, judge: dict, tasks: list[dict], name: str) -> dict:
    """What was run: the header of the report, from the run manifest and the grades manifest."""
    environment, git = run.get("environment") or {}, run.get("git") or {}
    derived = run.get("derived_from")
    return {"run": name, "task_file": run.get("task_file"), "tasks_sha256": run.get("tasks_sha256"), "tasks": len(tasks),
            "repeats": run.get("repeats", REPEATS),
            "model": environment.get("model"), "effort": environment.get("effort"),
            "judge": {"model": judge.get("model") or (run.get("judge") or {}).get("model"),
                      "protocol": judge.get("protocol"), "votes": judge.get("votes")},
            "snapshot": environment.get("snapshot_id"), "corpus_sha256": environment.get("corpus_sha256"),
            "commit": git.get("commit"), "diff_sha256": git.get("diff_sha256"),
            "derived_from": {"run": derived.get("run"), "note": derived.get("note")} if derived else None}


def build(tasks: list[dict], attempt_rows: list[dict], grade_rows: list[dict], repeats: int = REPEATS,
          info: dict | None = None) -> dict:
    """The full report payload. Pure: no file or network access."""
    order = {t["id"]: i for i, t in enumerate(tasks)}
    by_id = {t["id"]: t for t in tasks}
    attempts = {attempt_key(r): r for r in attempt_rows if r.get("variant") in SYSTEMS}
    grade_index = {g["key"]: g for g in grade_rows if g.get("variant") in SYSTEMS}
    grades = list(grade_index.values())
    answer_ids = {t["id"] for t in tasks if t["expect"] == "answer"}
    metrics = {s: system_metrics([g for g in grades if g["variant"] == s], attempts) for s in SYSTEMS}
    return {
        "info": info or {"repeats": repeats, "tasks": len(tasks)},
        "systems": dict(SYSTEMS),
        "repeats": repeats,
        "task_counts": {"total": len(tasks), "answer": len(answer_ids)},
        "coverage": coverage(list(order), attempts, grade_index, repeats),
        "metrics": metrics,
        "pass_k": {s: pass_k(grades, s, repeats) for s in SYSTEMS},
        "groups": expect_groups(grades, tasks),
        "categories": breakdown(grades, tasks, lambda t: group(t["category"])),
        "comparison": agent_vs_baseline(grades, answer_ids, metrics),
        "subgroups": subgroups(grades, prefix_states(attempts), SYSTEMS),
        "flips": {s: flips(grades, s, order, repeats) for s in SYSTEMS},
        "candidate_failures": candidate_failures(grades, attempts, by_id, order),
    }


# ---------- markdown ----------

def share(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}% ({k}/{n})" if n else "n/a"


def pct(r: dict | None) -> str:
    return share(r["passed"], r["n"]) if r else "n/a"


def num(value, fmt: str) -> str:
    return "n/a" if value is None else format(value, fmt)


def points(value) -> str:
    return "n/a" if value is None else f"{100 * value:+.1f}"


def ci(r: dict) -> str:
    return "n/a" if r["ci95"] is None else f"[{points(r['ci95'][0])}, {points(r['ci95'][1])}]"


def short(value, n: int = 12) -> str:
    return "n/a" if not value else f"`{str(value)[:n]}`"


def met(value) -> str:
    return "n/a" if value is None else "met" if value else "not met"


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return lines + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]


def render_header(info: dict) -> list[str]:
    judge = info.get("judge") or {}
    rows = [["Run", f"`{info.get('run') or 'n/a'}`"],
            ["Task file", f"`{info.get('task_file') or 'n/a'}` ({info.get('tasks')} tasks, sha256 "
                          f"{short(info.get('tasks_sha256'))})"],
            ["Runs per task", info.get("repeats")],
            ["Generation model", f"{info.get('model') or 'n/a'} (effort {info.get('effort') or 'n/a'})"],
            ["Judge", f"{judge.get('model') or 'n/a'}, protocol `{judge.get('protocol') or 'n/a'}`, "
                      f"{judge.get('votes') or 'n/a'} votes per unit, majority"],
            ["Corpus snapshot", f"{info.get('snapshot') or 'n/a'} (sha256 {short(info.get('corpus_sha256'))})"],
            ["Code", f"commit {short(info.get('commit'))}, working-tree diff sha256 {short(info.get('diff_sha256'))}"]]
    derived = info.get("derived_from")
    if derived:
        rows.append(["Derived from", f"{derived.get('run') or 'n/a'}. {derived.get('note') or ''}".strip()])
    return table(["", ""], rows)


def render(p: dict) -> str:
    names, cov, info, k = p["systems"], p["coverage"], p["info"], p["repeats"]
    m, pk = p["metrics"], p["pass_k"]
    ungraded = [key for c in cov.values() for key in c["ungraded"]]
    out = [f"# Results: {' vs '.join(names.values())}, {p['task_counts']['total']} tasks, {k} runs each", "",
           f"{names['baseline']}: a fixed workflow. {names['agent']}: the LLM agent. Both answer the same tasks and "
           "start from the same shared first stage. Quality comes from `grades/grades.jsonl` (LLM judge, majority of "
           "3 votes; not human gold). Method notes are at the end.", ""]
    out += render_header(info)

    out += ["", "## Coverage", ""]
    out += table(["System", "Expected", "Recorded", "Graded", "Recorded, no grade", "Infrastructure failures",
                  "Error codes (graded)"],
                 [[names[s], c["expected"], c["recorded"], c["graded"], len(c["ungraded"]), c["infrastructure_failures"],
                   ", ".join(f"{code}: {n}" for code, n in c["error_codes"].items()) or "none"] for s, c in cov.items()])
    if ungraded:
        shown = ", ".join(f"`{key}`" for key in ungraded[:UNGRADED_SHOWN])
        more = len(ungraded) - UNGRADED_SHOWN
        out += ["", f"No grade yet: {shown}" + (f", … and {more} more (full list in results.json)." if more > 0 else ".")]

    out += ["", "## Results", ""]
    rows = [("Accuracy (pass rate)", lambda s: pct(m[s]["accuracy"])),
            ("Strict pass rate (all 3 expressions good)", lambda s: pct(m[s]["strict"])),
            (f"pass@{k} (any run passes)", lambda s: share(pk[s]["any_pass"], pk[s]["tasks"])),
            (f"pass^{k} (all runs pass)", lambda s: share(pk[s]["all_pass"], pk[s]["tasks"])),
            ("Empty answers (answerable attempts, no good expression)", lambda s: pct(m[s]["empty_answer"])),
            ("Turns: model calls per attempt (first stage included)", lambda s: num(m[s]["turns_mean"], ".2f")),
            ("Decision rounds after the shared first stage", lambda s: num(m[s]["rounds_mean"], ".2f")),
            ("Latency mean (s)", lambda s: num(m[s]["latency_mean_s"], ".1f")),
            ("Latency p95 (s)", lambda s: num(m[s]["latency_p95_s"], ".1f")),
            ("Tokens per attempt (mean)", lambda s: num(m[s]["tokens_mean"], ",.0f")),
            ("Cost per attempt (USD, mean)", lambda s: num(m[s]["cost_mean_usd"], ".4f"))]
    out += table(["Metric", *names.values()], [[label, *(value(s) for s in names)] for label, value in rows])
    out += ["", "Rates are over graded attempts (tasks × runs); pass@k and pass^k are over tasks."]

    out += ["", "## By expectation", ""]
    out += table(["Group", "Tasks", *(f"{names[s]} pass" for s in names), *(f"{names[s]} strict" for s in names)],
                 [[r["name"], r["tasks"], *(pct(r[s]["pass"]) for s in names), *(pct(r[s]["strict"]) for s in names)]
                  for r in p["groups"]])
    out += ["", "answer: tasks expecting expressions (edge cases included); edge and unanswerable: by category."]
    out += ["", "## By category", ""]
    out += table(["Category", "Tasks", *(f"{names[s]} pass" for s in names)],
                 [[r["name"], r["tasks"], *(pct(r[s]["pass"]) for s in names)] for r in p["categories"]])

    c = p["comparison"]
    out += ["", f"## {names['agent']} − {names['baseline']} ({c['pass']['tasks']} answerable tasks, paired)", ""]
    out += table(["Metric", "Tasks", "Difference (pp)", "95% CI (pp)"],
                 [[label, c[key]["tasks"], points(c[key]["difference"]), ci(c[key])]
                  for key, label in (("pass", "Pass"), ("strict", "Strict"))])
    if c["pass"]["excluded_units"]:
        out += ["", "Units with an infrastructure failure in either system are left out of both: "
                + ", ".join(f"`{u}`" for u in c["pass"]["excluded_units"])
                + f". With them: pass {points(c['pass']['all_units']['difference'])} pp {ci(c['pass']['all_units'])}, "
                  f"strict {points(c['strict']['all_units']['difference'])} pp {ci(c['strict']['all_units'])}."]
    checks, empty = c["checks"], [m[s]["empty_answer"] for s in ("agent", "baseline")]
    lower = [None if c[key]["ci95"] is None else c[key]["ci95"][0] for key in ("pass", "strict")]
    out += ["", f"- Pass non-inferiority (CI lower bound > {points(c['pass_margin'])} pp): {met(checks['pass_non_inferiority'])}"
                f" (lower bound {points(lower[0])} pp).",
            f"- Strict superiority (CI lower bound > 0): {met(checks['strict_superiority'])} "
            f"(lower bound {points(lower[1])} pp).",
            f"- Empty-answer difference ≤ {points(c['empty_limit'])} pp: {met(checks['empty_answers'])} "
            f"({points(c['empty_difference'])} pp: {pct(empty[0])} vs {pct(empty[1])})."]

    sub = p["subgroups"]
    out += ["", "## By first-stage state", "",
            "The shared first stage verifies up to 3 answer slots before either system decides anything. "
            "Units: answerable task × run.", ""]
    out += table(["State", "Units", *(f"{names[s]} pass" for s in names), *(f"{names[s]} strict" for s in names)],
                 [[f"{state} ({'all 3 slots verified' if state == 'review' else 'fewer than 3 verified'})",
                   sub[state]["units"], *(pct(sub[state][s]["pass"]) for s in names),
                   *(pct(sub[state][s]["strict"]) for s in names)] for state in ("review", "recovery")])

    out += ["", f"## Tasks whose result changed across the {k} runs", ""]
    changed = [[names[s], f["task_id"], f["category"], f["pattern"]] for s in names for f in p["flips"][s]]
    out += table(["System", "Task", "Category", f"Runs 1-{k}"], changed) if changed else ["None."]
    totals = "; ".join(f"{names[s]}: {len(p['flips'][s])}" for s in names)
    out += ["", f"Changed tasks per system: {totals}. P pass, F fail, · not graded."]

    out += ["", "## Failure analysis", "", TODO, "", "### Candidate failures (attempts that did not pass)", ""]
    failures = [[names[f["system"]], f["task_id"], f["attempt"], f["category"], f["step"], f["reason"]]
                for f in p["candidate_failures"]]
    out += table(["System", "Task", "Run", "Category", "Where in the trace", "Why it failed (judge and code checks)"],
                 failures) if failures else ["None."]

    out += ["", "## Method", "",
            "- Pass, expect=answer: ok status, no injected marker, no failed set constraint and at least 2 of the 3 "
            "expressions grounded-good (fits the request, natural, and backed by a podcast quote that code verified "
            "as the exact corpus slice and the judge found to show the use). Pass, expect=decline: no expressions "
            "and a note. Strict: as pass, with all 3 expressions grounded-good.",
            "- Judge: an LLM judge, 3 votes per unit (expression, example, set), majority; not human gold.",
            f"- pass@{k}: share of tasks with at least one passing run; pass^{k}: share with all {k} passing; both over "
            f"tasks with all {k} runs graded.",
            "- Turns: model calls per attempt, the shared first stage included. Rounds: decision steps after the "
            "shared first stage (baseline revise_r, agent agent_r), from the trace.",
            "- Latency p95: nearest rank, the ceil(0.95 * n)-th smallest. Tokens: chat input + output per attempt "
            "(embedding tokens excluded). Cost: list-price USD estimate per attempt.",
            "- Empty answers: expect=answer attempts with no grounded-good expression.",
            "- Paired comparison: per task, the mean over its graded runs; agent − baseline over the expect=answer "
            "tasks graded in both; units with an infrastructure failure in either system left out of both; "
            f"percentile bootstrap over tasks, {BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}.",
            f"- First-stage state: from the shared first verification (validate_select_1); review = all {REVIEW_VERIFIED} "
            "slots verified, recovery = fewer.", ""]
    return "\n".join(out)


# ---------- per-attempt logs ----------

def clip(text, n: int = LOG_TEXT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def action_summary(action: dict) -> str:
    """One agent action, e.g. 'repick slot 1' or 'search "on the same page"'."""
    if action.get("type") == "search":
        return f"search \"{clip(action.get('key_phrase') or action.get('query'), 40)}\""
    return f"{action.get('type')} slot {action.get('slot')}"


def step_summary(span: dict) -> str:
    """One short line for one trace step: what a model call returned, what a search found, what changed."""
    stage, details = span.get("stage") or "", span.get("details") or {}
    output = details.get("output") if isinstance(details.get("output"), dict) else {}
    if span.get("status") not in (None, "ok"):
        return f"{span.get('status')}: {details.get('error_code') or 'no error code'}"
    if stage.startswith("candidates"):
        candidates = output.get("candidates") or []
        if output.get("request_status") != "answerable":
            return f"request {output.get('request_status')}: {clip(output.get('status_note'))}"
        phrases = "; ".join(clip(c.get("key_phrase"), 40) for c in candidates)
        return f"{len(candidates)} candidates ({output.get('kind')}): {phrases}"
    if stage.startswith("search_"):
        if details.get("skipped"):
            return "skipped"
        return (f"query \"{clip(details.get('query'), 80)}\", key phrase \"{clip(details.get('key_phrase'), 40)}\": "
                f"{len(details.get('hits') or [])} hits ({details.get('search_mode') or 'n/a'})")
    if stage.startswith("select_"):
        picks = output.get("picks") or []
        refs = [pick["ref"] for pick in picks if pick.get("ref")]
        return f"{len(refs)} of {len(picks)} candidates matched to a span" + (f": {', '.join(refs)}" if refs else "")
    if stage.startswith("validate_"):
        return f"{details.get('verified')}/{len(details.get('slots') or [])} slots verified"
    if stage.startswith("revise_"):
        replacements = output.get("replacements") or []
        return f"{len(replacements)} replacement(s)" + "".join(
            f"; slot {r.get('replaces')} -> \"{clip(r.get('expression'), 60)}\"" for r in replacements)
    if stage.startswith("agent_") or stage == "pick_final":
        actions = ", ".join(map(action_summary, output.get("actions") or [])) or "no action"
        return f"{actions}{', finish' if output.get('finish') else ''}. {clip(output.get('assessment'))}"
    if stage.startswith(("repick_", "replace_")):
        reasons = details.get("rejection_reasons") or []
        return (f"slot {details.get('slot')} -> {details.get('ref') or 'no ref'}: {details.get('outcome')}"
                + (f" ({'; '.join(map(str, reasons))})" if reasons else "")
                + f", \"{clip(details.get('expression'), 60)}\"")
    if stage == "decline":
        return f"declined ({details.get('request_status')}): {clip(details.get('note'))}"
    if stage == "assemble":
        return f"{details.get('expressions')} expressions, {details.get('with_example')} with an example"
    return span.get("status") or "ok"


def attempt_log(row: dict, task: dict | None, grade: dict | None) -> dict:
    """The compact log line of one attempt; the full row stays in <system>/attempts.jsonl."""
    result, task, grade = row.get("result") or {}, task or {}, grade or {}
    usage, items = result.get("usage") or {}, grade.get("items") or []
    expressions = []
    for index, item in enumerate(result.get("expressions") or []):
        citation = item.get("citation") or {}
        # verified: a quote is shown and, once graded, code found it to be the exact corpus slice
        verified = bool(citation) and (index >= len(items) or bool(items[index].get("code_ok")))
        expressions.append({"expression": item.get("expression"), "quote": citation.get("quote"),
                            "episode": citation.get("episode_title"), "verified": verified})
    latency, cost = result.get("elapsed_ms"), ((row.get("cost") or {}).get("workflow") or {}).get("usd")
    return {"task_id": row["task_id"], "run": row["attempt"], "system": row["variant"], "type": task.get("type"),
            "question": task.get("question"), "status": result.get("status"), "error_code": result.get("error_code"),
            "passed": grade.get("passed"), "strict_passed": grade.get("strict_passed"), "expressions": expressions,
            "steps": [{"stage": span.get("stage"), "summary": step_summary(span)} for span in result.get("trace") or []],
            "model_calls": result.get("model_rounds"), "searches": len(result.get("tool_calls") or []),
            "tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            "latency_ms": None if latency is None else round(latency),
            "cost_usd": None if cost is None else round(cost, 6)}


def write_logs(tasks: list[dict], attempt_rows: list[dict], grade_rows: list[dict], output: Path) -> None:
    """<output>/logs/<system>.jsonl: one attempt_log line per attempt, in task order then run order."""
    order = {t["id"]: i for i, t in enumerate(tasks)}
    by_id = {t["id"]: t for t in tasks}
    grades = {g["key"]: g for g in grade_rows}
    (output / "logs").mkdir(parents=True, exist_ok=True)
    for system in SYSTEMS:
        rows = sorted((r for r in attempt_rows if r.get("variant") == system and r["task_id"] in order),
                      key=lambda r: (order[r["task_id"]], r["attempt"]))
        lines = [attempt_log(r, by_id[r["task_id"]], grades.get(attempt_key(r))) for r in rows]
        (output / "logs" / f"{system}.jsonl").write_text(
            "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))


# ---------- entry point ----------

def report_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "report"


def _json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def write_report(tasks: list[dict], run_dir: Path) -> dict:
    """Build from <run_dir>/<system>/attempts.jsonl and grades/grades.jsonl; write report_dir()."""
    run_dir = Path(run_dir)
    attempts = [row for path in sorted(run_dir.glob("*/attempts.jsonl")) for row in read_jsonl(path)]
    grades = read_jsonl(run_dir / "grades" / "grades.jsonl")
    run = _json(run_dir / "manifest.json")
    info = run_info(run, _json(run_dir / "grades" / "manifest.json"), tasks, run_dir.name)
    payload = build(tasks, attempts, grades, repeats=run.get("repeats", REPEATS), info=info)
    output = report_dir(run_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    (output / "results.md").write_text(render(payload))
    write_logs(tasks, attempts, grades, output)
    return payload
