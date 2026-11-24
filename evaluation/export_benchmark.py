"""Export one graded eval run to the shared Vercel admin's static scorecard."""

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from evaluation.report import REPEATS, SYSTEMS, attempt_key, mean, pass_k, rate, read_jsonl
from frontend.admin_data import RUN_NAME, attempt_facts, check_leaks

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deploy/phrase-room-coach/public/admin/benchmark.json"
System = Literal["baseline", "agent"]
Label = Annotated[str, Field(min_length=1, max_length=160)]


class SafetyPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: Label
    kind: Literal["attack", "benign"]
    surface: Label
    criterion: Label
    verdicts: dict[System, Literal["safe", "unsafe"] | None]  # relative to the criterion


class SafetyResults(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    run: Label | None = None
    prompts: list[SafetyPrompt] = Field(default_factory=list)
    over_refusals: dict[str, bool | None] = Field(default_factory=dict)
    failure: Label | None = None


def index_rows(rows, expected, source):
    indexed = {}
    for row in rows:
        key = attempt_key(row)
        if type(row["attempt"]) is not int or key not in expected or key in indexed:
            raise ValueError(f"{source}: unexpected or duplicate attempt {key!r}")
        indexed[key] = row
    if missing := expected - indexed.keys():
        raise ValueError(f"{source}: missing {len(missing)} attempts (first: {min(missing)!r})")
    return indexed


def load_benchmark(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    judge = json.loads((run_dir / "grades/manifest.json").read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    systems = manifest["systems"]
    if manifest["repeats"] != REPEATS or not isinstance(systems, list) or sorted(systems) != sorted(SYSTEMS):
        raise ValueError("the run must contain exactly three planned attempts for baseline and agent")
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("the run manifest has no task records")
    if not judge.get("protocol") or type(judge.get("votes")) is not int or judge["votes"] < 1:
        raise ValueError("the grading manifest must identify the judge protocol and vote count")
    expected = {f"{task}/{system}/{attempt}" for task in tasks for system in SYSTEMS
                for attempt in range(1, REPEATS + 1)}
    grades = index_rows(read_jsonl(run_dir / "grades/grades.jsonl"), expected, "grades")
    rows = []
    for system in SYSTEMS:
        attempts = index_rows(read_jsonl(run_dir / system / "attempts.jsonl"),
                              {key for key in expected if key.rsplit("/", 2)[1] == system}, system)
        for key, attempt in attempts.items():
            grade = grades[key]
            task = tasks[grade["task_id"]]
            result = attempt["result"]
            status = result["status"]
            expect = task["expect"]
            if (grade["key"] != key or type(grade["passed"]) is not bool or grade["expect"] != expect
                    or expect not in ("answer", "decline", "no_examples") or grade["status"] != status
                    or (status != "ok" and grade["passed"])):
                raise ValueError(f"{key}: grade and recorded attempt disagree")
            facts = attempt_facts(attempt)
            usage = result.get("usage") or {}
            tokens = [usage.get(k) for k in ("input_tokens", "output_tokens")]
            calls = usage.get("total_chat_calls")
            if calls is None:
                calls = grade.get("model_calls")
            if any(x is not None and (type(x) is not int or x < 0) for x in [calls, *tokens]):
                raise ValueError(f"{key}: invalid model usage")
            rows.append({
                **{k: grade[k] for k in ("key", "task_id", "variant", "attempt", "passed", "expect")},
                **{k: facts[k] for k in ("status", "error_code", "verified_first", "verified_final")},
                "grounded_good": grade.get("grounded_good"),
                "model_calls": calls, "tokens": sum(tokens) if None not in tokens else None,
            })
    env = manifest.get("environment") or {}
    return {
        "id": run_dir.name, "tasks": len(tasks), "repeats": REPEATS,
        "model": env.get("model"), "corpus": env.get("snapshot_id"),
        "judge_protocol": judge["protocol"], "judge_votes": judge["votes"],
    }, rows


def count_outcomes(verdicts, event) -> dict:
    return {"events": verdicts.count(event), "judged": sum(v is not None for v in verdicts), "expected": len(verdicts)}


def usage_summary(rows, field) -> dict:
    values = [row[field] for row in rows if row[field] is not None]
    return {"mean": mean(values), "n": len(values)}


def scorecard(run: dict, rows: list[dict], safety: SafetyResults) -> dict:
    attack_prompts = [p for p in safety.prompts if p.kind == "attack"]
    if len({p.id for p in safety.prompts}) != len(safety.prompts):
        raise ValueError("duplicate safety prompt ID")
    declined = {row["key"] for row in rows if row["expect"] == "answer" and row["status"] == "declined"}
    if unrelated := safety.over_refusals.keys() - declined:
        raise ValueError(f"over_refusals contains a key outside this run's answer-expected declines: {min(unrelated)!r}")

    systems = {}
    for system in SYSTEMS:
        own = [row for row in rows if row["variant"] == system]
        k = pass_k(own, system, REPEATS)
        systems[system] = {
            "accuracy": rate(own),
            "pass3": {"passed": k["all_pass"], "n": k["tasks"]},
            "pass_at3": {"passed": k["any_pass"], "n": k["tasks"]},
            "model_calls": usage_summary(own, "model_calls"),
            "tokens": usage_summary(own, "tokens"),
            "attack_success": count_outcomes([p.verdicts.get(system) for p in attack_prompts], "unsafe"),
            "over_refusal": count_outcomes([safety.over_refusals.get(r["key"]) if r["key"] in declined else False
                                           for r in own if r["expect"] == "answer"], True),
        }

    failure = next((r for r in rows if not r["passed"] and r["key"] == safety.failure), None)
    if safety.failure and failure is None:
        raise ValueError("failure must identify a failed attempt in this run")
    if failure is None:
        failure = next((r for r in rows if not r["passed"] and r["variant"] == "agent"
                        and r["expect"] == "answer" and r["status"] == "ok"), None)
    if failure is None:
        failure = next((r for r in rows if not r["passed"]), None)
    return {
        "schema_version": 1, "run": run, "systems": systems,
        "safety_prompts": len(safety.prompts), "attack_prompts": len(attack_prompts),
        "failure": {k: failure[k] for k in ("task_id", "variant", "attempt", "expect", "status", "error_code",
                                           "verified_first", "verified_final", "grounded_good")} if failure else None,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run folder name under --results")
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation/results")
    parser.add_argument("--safety", type=Path, help="JSON judgments for this run (otherwise safety is pending where unjudged)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"static JSON path (default {DEFAULT_OUT.relative_to(ROOT)})")
    args = parser.parse_args(argv)
    if not RUN_NAME.fullmatch(args.run):
        parser.error("--run must be a single folder name")
    try:
        run, rows = load_benchmark(args.results / args.run)
        safety = SafetyResults.model_validate_json(args.safety.read_bytes()) if args.safety else SafetyResults()
        if args.safety and safety.run != args.run:
            raise ValueError("the safety file's run must match --run")
        payload = scorecard(run, rows, safety)
        text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        check_leaks(text)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=args.out.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(text.encode("utf-8"))
                handle.close()
                os.replace(temporary, args.out)
            finally:
                temporary.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"{args.run}: {run['tasks']} tasks × {REPEATS} × {len(SYSTEMS)}, "
          f"{payload['attack_prompts']} attack prompts → {args.out}")


if __name__ == "__main__":
    main()
