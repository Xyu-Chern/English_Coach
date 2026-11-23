"""Evaluate the expression coach: the baseline (a fixed workflow) and the agent, 3 runs per task.

Flow
    tasks    check evaluation/data/tasks.jsonl                                       no calls
    run      every task x run: one shared first stage, then both systems from it     PAID, resumable
    grade    three judge votes per answer unit (cached in grades/calls.jsonl)        PAID, resumable
    report   results tables, pass@3 and pass^3 per system, one log per system        no calls
    review   report/review.html, to read every answer side by side                   no calls
    all      run, grade, report, review                                              PAID

    python -m evaluation.eval run --prepare-only    what run (or grade) would do, without any paid call

Inputs   evaluation/data/tasks.jsonl (the 50 tasks) and pricing.json; the frozen corpus snapshot
         evaluation/.local/snapshots/corpus-20261116-full-v2, imported into PostgreSQL for run
         (freeze.py, snapshot_store.py); models from translation_agent_demo/.env or the environment:
         LLM_PROVIDER, LLM_MODEL, LLM_EFFORT (both systems), JUDGE_PROVIDER, JUDGE_MODEL, JUDGE_EFFORT (grade).
Outputs  evaluation/results/<run>/manifest.json, code.diff, unit-starts.jsonl
         evaluation/results/<run>/{baseline,agent}/attempts.jsonl
         evaluation/results/<run>/grades/{calls.jsonl,grades.jsonl,manifest.json}
         evaluation/results/<run>/report/ (results.md, results.json, logs/<system>.jsonl, review.html)

The manifest records the sha256 of tasks.jsonl; grade, report and review refuse a run made with
another version of the file.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .tasks import DATA, TASKS, Corpus, EvalTask, load_tasks, summarize

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"
PRICING = DATA / "pricing.json"
DEFAULT_RUN = "submission"
DEFAULT_REPEATS = 3  # pass@3 and pass^3
DEFAULT_WORKERS = 6  # units in flight; each runs both systems side by side
DEFAULT_JUDGE_WORKERS = 16


def main() -> None:
    args = arguments().parse_args()
    run_dir = args.results / args.run
    if args.command == "tasks":
        raise SystemExit(0 if check_tasks(args.task_file) else 1)
    if args.command in ("run", "all"):
        run(run_dir, select_tasks(args.tasks, args.task_file), repeats=args.repeats, workers=args.workers,
            max_new=args.max_new, prepare_only=args.prepare_only, systems=select_systems(args.systems),
            task_file=args.task_file)
    if args.command in ("grade", "all"):
        grade(run_dir, args.judge_workers, args.prepare_only)
    if args.prepare_only:
        return
    if args.command in ("report", "all"):
        report(run_dir)
    if args.command in ("review", "all"):
        review(run_dir)


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("tasks", "run", "grade", "report", "review", "all"))
    parser.add_argument("--run", default=DEFAULT_RUN, help=f"run directory under --results (default {DEFAULT_RUN})")
    parser.add_argument("--results", type=Path, default=RESULTS, help="results root (default evaluation/results)")
    parser.add_argument("--tasks", help="run only these task ids (comma-separated)")
    parser.add_argument("--task-file", type=Path, default=TASKS,
                        help="JSONL for tasks/run/all; later stages read the path from the run manifest")
    parser.add_argument("--systems", help="run only these systems (comma-separated: baseline, agent; default both)")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="runs per task (default 3)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="units run in parallel (default 6)")
    parser.add_argument("--max-new", type=int, help="run at most this many new units")
    parser.add_argument("--judge-workers", type=int, default=DEFAULT_JUDGE_WORKERS,
                        help="parallel judge calls (default 16)")
    parser.add_argument("--prepare-only", action="store_true",
                        help="run, grade: print pending units or missing votes and stop, with no paid call")
    return parser


# ------------------------------------------------------------------ commands, in flow order
def check_tasks(task_file: Path = TASKS) -> bool:
    """tasks.jsonl meets the assignment's minimums."""
    summary = summarize(load_tasks(task_file))
    print(json.dumps({"file": task_file.name, **summary}, ensure_ascii=False))
    return not summary["problems"]


def run(run_dir: Path, tasks: list[EvalTask], *, repeats: int, workers: int, max_new: int | None,
        prepare_only: bool, environment=None, systems: tuple[str, ...] | None = None, task_file: Path = TASKS) -> None:
    """Every pending unit in one process. environment defaults to the live models and snapshot."""
    from .live import LiveEnvironment
    from .runner import PairAttempt, RunPlan, Runner, git_state

    if environment is None:
        from .published import configured_bundle, PublishedEnvironment
        bundle = configured_bundle()
        environment = PublishedEnvironment(bundle) if bundle else LiveEnvironment()
    systems = systems or select_systems(None)
    git, diff = git_state()
    plan = RunPlan(tasks, repeats=repeats, workers=workers)
    manifest = run_manifest(environment, git, task_file)
    if prepare_only:
        runner = Runner(plan, run_dir, None, manifest, code_diff=diff, systems=systems)
        runner.prepare()
        try:
            print(json.dumps({"run": run_dir.name, "systems": list(systems),
                              "pending_units": len(runner.pending(max_new))}))
        finally:
            runner.close()
        return
    environment.check()
    attempt = PairAttempt(environment, json.loads(PRICING.read_text()), systems)
    runner = Runner(plan, run_dir, attempt, manifest, code_diff=diff, systems=systems)
    print(json.dumps({"run": run_dir.name, "status": dict(runner.run(max_new))}))


def grade(run_dir: Path, workers: int, prepare_only: bool, corpus: Corpus | None = None) -> None:
    """Judge every attempt of the run into <run>/grades and print the judge's list-price cost."""
    from translation_agent_demo.config import Settings
    from .grader import grade_run
    from .live import configured_snapshot_dir

    tasks = {t.id: t for t in planned_tasks(run_dir)}
    if corpus is None:
        manifest = json.loads((run_dir / "manifest.json").read_text())
        if manifest["environment"].get("snapshot_schema") == "published_bundle":
            from .published import configured_bundle, grading_corpus
            corpus = grading_corpus(configured_bundle())
        else:
            corpus = Corpus(configured_snapshot_dir() / "corpus.json.gz")
        if corpus.sha256 != manifest["environment"]["corpus_sha256"]:
            raise SystemExit("The selected corpus differs from the snapshot used for this run.")
    settings = None if prepare_only else Settings.from_environment()  # only a judge call needs the chat settings
    summary = grade_run(run_dir, tasks, corpus, settings, workers=workers, prepare_only=prepare_only)
    if summary:
        print(json.dumps({**summary, "judge_cost": judge_cost(summary["judge_usage"])}))


def report(run_dir: Path) -> None:
    from .report import report_dir, write_report

    payload = write_report([asdict(t) for t in planned_tasks(run_dir)], run_dir)
    graded = sum(c["graded"] for c in payload["coverage"].values())
    print(json.dumps({"graded": graded, "wrote": str(report_dir(run_dir))}))


def review(run_dir: Path) -> None:
    from .viewer import build_review

    print(json.dumps({"wrote": str(build_review(run_dir, planned_tasks(run_dir)))}))


# ------------------------------------------------------------------ helpers
def select_tasks(ids: str | None, task_file: Path = TASKS) -> list[EvalTask]:
    """All tasks, or the named ones in file order."""
    tasks = load_tasks(task_file)
    if not ids:
        return tasks
    wanted = {i.strip() for i in ids.split(",") if i.strip()}
    unknown = wanted - {t.id for t in tasks}
    if unknown:
        raise SystemExit(f"Unknown task ids: {sorted(unknown)}")
    return [t for t in tasks if t.id in wanted]


def select_systems(names: str | None) -> tuple[str, ...]:
    """Both systems, or the named ones in report order."""
    from .runner import SYSTEMS

    wanted = [n.strip() for n in (names or "").split(",") if n.strip()]
    unknown = set(wanted) - set(SYSTEMS)
    if unknown:
        raise SystemExit(f"Unknown systems: {sorted(unknown)}; choose from {list(SYSTEMS)}.")
    return tuple(s for s in SYSTEMS if s in wanted) if wanted else SYSTEMS


def run_manifest(environment, git: dict, task_file: Path = TASKS) -> dict:
    """What a run is made of: the models and corpus, the judge, the code and the task file's sha256.

    The runner adds the systems, repeats, seed, workers and the tasks themselves."""
    from .judging import current_judge
    from .runner import file_sha256, source_hashes

    path = task_file.resolve()
    label = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    return {"environment": environment.identity(), "judge": asdict(current_judge()), "git": git,
            "sources": source_hashes(), "task_file": label, "tasks_sha256": file_sha256(path)}


def planned_tasks(run_dir: Path) -> list[EvalTask]:
    """The tasks a run was planned for, so a partial run is reported against its own plan.

    Refused when tasks.jsonl changed since the run: its grades would be read against other tasks."""
    from .runner import file_sha256

    path = run_dir / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    recorded = manifest.get("tasks_sha256")
    task_file = ROOT / manifest.get("task_file", TASKS)
    if recorded and recorded != file_sha256(task_file):
        raise SystemExit(f"{task_file.name} changed since this run was made (sha256 {recorded[:12]} in its manifest); "
                         "restore the file or make a new run.")
    tasks = load_tasks(task_file)
    planned = manifest.get("tasks")
    return [t for t in tasks if t.id in planned] if planned else tasks


def judge_cost(usage: dict) -> dict:
    """List-price estimate of the judge calls; the cached share is unknown, so it is priced as uncached."""
    from .costs import estimate
    from .judging import current_judge

    return estimate({**usage, "cached_input_tokens": None}, json.loads(PRICING.read_text()),
                    model=current_judge().model, include_embedding=False)


if __name__ == "__main__":
    main()
