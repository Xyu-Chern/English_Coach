"""Join two completed 50-task cohorts and retain each run's generation and judging settings."""

import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path

from .tasks import DATA, load_tasks


def read_cohort(name, tasks_path, report):
    tasks = load_tasks(tasks_path)
    if len(tasks) != 50:
        raise ValueError(f"{name}: expected 50 tasks")
    by_id = {task.id: task for task in tasks}
    metadata = json.loads((report / "results.json").read_text(encoding="utf-8"))
    if metadata["repeats"] != 3:
        raise ValueError(f"{name}: expected three repeats")
    expected = {(task.id, attempt) for task in tasks for attempt in (1, 2, 3)}
    rows = []
    for system in ("agent", "baseline"):
        seen = set()
        for line in (report / "logs" / f"{system}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = row["task_id"], row["run"]
            if (key not in expected or key in seen or row["system"] != system or
                    row["question"] != by_id[key[0]].question or type(row["passed"]) is not bool):
                raise ValueError(f"{name}/{system}: unexpected, duplicate or ungraded attempt {key}")
            rows.append({"cohort": name, **row})
            seen.add(key)
        if seen != expected:
            raise ValueError(f"{name}/{system}: missing {len(expected-seen)} attempts")
    return metadata["info"], rows


def metrics(rows):
    passes = Counter()
    for row in rows:
        passes[row["task_id"]] += int(row["passed"])
    return {"tasks": len(passes), "attempts": len(rows), "passed_attempts": sum(passes.values()),
            "pass@3": sum(n >= 1 for n in passes.values()), "pass^3": sum(n == 3 for n in passes.values()),
            "flips": sorted(task for task, n in passes.items() if n in (1, 2))}


def merge(korean, chinese, output):
    cohorts = (("Korean set", DATA / "tasks.jsonl", korean),
               ("Chinese set", DATA / "tasks.zh.jsonl", chinese))
    info, rows = {}, []
    for name, tasks, report in cohorts:
        info[name], records = read_cohort(name, tasks, report)
        rows.extend(records)
    if len({r["task_id"] for r in rows}) != 100:
        raise ValueError("Task IDs overlap between cohorts")
    summary = {name: {s: metrics([r for r in rows if r["system"] == s and
                                 (name == "Combined" or r["cohort"] == name)])
                      for s in ("agent", "baseline")} for name in (*info, "Combined")}
    output.mkdir(parents=True, exist_ok=True)
    policies = {"Korean set": "Submission agent can revise previously verified examples.",
                "Chinese set": "Current agent keeps verified examples and can fill remaining slots."}
    (output / "results.json").write_text(json.dumps({"source_runs": info, "agent_policies": policies, "summary": summary},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "attempts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
    table = []
    for name, systems in summary.items():
        for system, m in systems.items():
            table.append(f"<tr><td>{name}</td><td>{system}</td><td>{m['passed_attempts']}/{m['attempts']}</td>"
                         f"<td>{m['pass@3']}/{m['tasks']}</td><td>{m['pass^3']}/{m['tasks']}</td></tr>")
    links = []
    for name, _, report in cohorts:
        local_review = output / ("ko.html" if name == "Korean set" else "zh.html")
        local_review.write_bytes((report / "review.html").read_bytes())
        run = info[name]
        links.append(f'<p><a href="{local_review.name}">{name} · replay 50 tasks</a><br>'
                     f'Model {escape(run["model"])} · Judge {escape(run["judge"]["model"])} · '
                     f'Corpus {escape(run["snapshot"])}<br>{escape(policies[name])}</p>')
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>English Coach · 100 tasks</title>
<style>body{font:17px/1.55 system-ui;background:#f4f7fa;color:#1f3042;max-width:920px;
margin:6vh auto;padding:0 16px}table{border-collapse:collapse;width:100%;background:white}
th,td{text-align:left;padding:.55em;border-bottom:1px solid #d6e0ea}a{color:#175597}</style>
<h1>English Coach · 100 tasks</h1><p>Each system answered each task three times.
The combined counts describe two experiments with different agent policies, models, judges and corpora.
Compare the two systems within each set.</p>
<table><tr><th>Set</th><th>System</th><th>Passing attempts</th><th>At least once</th><th>All three</th></tr>"""
    (output / "index.html").write_text(page + "".join(table) + "</table>" + "".join(links), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("korean_report", "chinese_report", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    merge(args.korean_report, args.chinese_report, args.output)
