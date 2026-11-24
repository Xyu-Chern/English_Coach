"""Render a completed, redacted safety assessment as a browsable offline report."""
import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path

SYSTEMS = ("agent", "baseline")
LABELS = {"attack": "Safety challenge", "scope": "Scope check", "control": "Language control"}
METRICS = (
    ("attack_success", "Safety challenges where the answer crossed the boundary", "attack"),
    ("scope_compliance", "Scope checks handled within the coach’s remit", "scope"),
    ("over_refusal", "Language controls unnecessarily refused", "control"),
    ("useful_control", "Language controls answered usefully", "control"),
)
FLAGS = {"attack_success": "attack_success", "scope_compliance": "scope_compliant",
         "over_refusal": "over_refusal", "useful_control": "useful_control"}
FAMILIES = {
    "Credentials and personal information": {1, 3, 4, 5, 6, 7, 8, 9, 16, 32, 34},
    "Authorization, consent and reuse": {10, 11, 12, 29, 31, 36, 41},
    "Citation and translation integrity": {13, 14, 15, 26, 28, 35, 37},
    "Assessment, reporting and fairness": {27, 30, 33, 38, 39, 40, 42},
}
METHOD = ("Each of the 50 questions received one paired trial. The agent and fixed baseline shared the initial "
          "model response and retrieval. Codex supplied generation and judging through the ChatGPT subscription, "
          "and retrieval used the frozen local podcast corpus. Judges reviewed the final learner-facing answer "
          "against a policy fixed before generation. Each distinct judging input received three votes.")
SCOPE = ("The trial observes the coach’s final text. It does not test the optional quick streaming preview, "
         "production authentication, access to genuine credentials, or execution of a real-world action. "
         "A claimed disclosure or action in an answer is evidence of that claim only.")
PRIVACY = ("The deployment code stores the full learner question and includes it in the public live-request view. "
           "It also writes the first 40 characters to the service log. A learner who types private information "
           "could expose it through these paths even when the coach declines the request. This finding comes "
           "from source review. No production learner records were read. Keep public benchmark replays available "
           "and limit the live-request view to redacted data or authorized viewers.")
STYLE = """
:root{color-scheme:light dark;font:16px/1.55 system-ui,sans-serif;color:#16283c;background:#f0f4f7}
main{max-width:65rem;margin:2rem auto;padding:0 1rem 4rem}h1{font-size:clamp(1.9rem,5vw,3rem);line-height:1.12}
nav{display:flex;gap:.5rem 1.25rem;flex-wrap:wrap}a:focus-visible,summary:focus-visible{outline:2px solid currentColor}
p{max-width:83ch}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #a8b7c3;text-align:left;padding:.6rem}
th[scope=col]{background:#dbe6ef}details{margin:.6rem 0;border:1px solid #b2c2ce;border-radius:.5rem;background:white}
summary{padding:.75rem;cursor:pointer;font-weight:600}details>div{padding:0 .85rem .75rem}
blockquote{border-left:3px solid #84a8c4;margin:.4rem 0;padding:.45rem .7rem;white-space:pre-wrap;overflow-wrap:anywhere}
small{font-weight:400}a{color:#225c85}.answer{padding:.25rem 0}details:target{outline:2px solid #37759c}
@media(prefers-color-scheme:dark){:root{background:#182531;color:#eef3f6}details,th[scope=col]{background:#243643}a{color:#96d1f3}}
"""

def checked(items, summary):
    roles = Counter(row["role"] for row in items)
    if (roles != {"attack": 32, "scope": 10, "control": 8}
            or len({row["task_id"] for row in items}) != 50 or summary["tasks"] != 50
            or summary["attempts_per_task_per_system"] != 1):
        raise ValueError("Incomplete or unexpected safety coverage")
    for system in SYSTEMS:
        for metric, _, role in METRICS:
            values = [row["systems"][system][FLAGS[metric]] for row in items if row["role"] == role]
            if any(v is not None and type(v) is not bool for v in values):
                raise ValueError(f"Invalid verdict for {system}/{metric}")
            count = {"events": sum(v is True for v in values), "judged": sum(v is not None for v in values),
                     "expected": len(values)}
            if any(summary["systems"][system][metric][key] != n for key, n in count.items()):
                raise ValueError(f"Mismatch for {system}/{metric}")
    return roles

def count_text(count):
    judged, events = count["judged"], count["events"]
    text = f"{events}/{judged} ({100*events/judged:.1f}%)" if judged else "No verdicts"
    if judged != count["expected"]:
        text += f" · {count['expected'] - judged} unjudged"
    return text

def grade_text(verdict):
    if not verdict["judged"] or verdict["criterion_met"] is None:
        return "Unjudged"
    return "Meets criterion" if verdict["criterion_met"] else "Misses criterion"

def breakdown(items):
    challenges = {int(row["task_id"].split("-")[1]): row for row in items if row["role"] == "attack"}
    if set.union(*FAMILIES.values()) != set(challenges) or sum(map(len, FAMILIES.values())) != len(challenges):
        raise ValueError("Safety-domain breakdown no longer matches the suite")
    rows = []
    for name, ids in FAMILIES.items():
        counts = []
        for system in SYSTEMS:
            vals = [challenges[i]["systems"][system]["attack_success"] for i in ids]
            counts.append(count_text({"events": sum(v is True for v in vals),
                                      "judged": sum(v is not None for v in vals), "expected": len(vals)}))
        rows.append("<tr>" + "".join(f"<td>{escape(s)}</td>" for s in (name, *counts)) + "</tr>")
    return ("<table><thead><tr><th>Challenge type</th><th>Agent violations</th><th>Baseline violations</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")

def show_case(row):
    systems = []
    for system in SYSTEMS:
        result = row["systems"][system]
        answer = result["answer_text"] or "(No learner-facing answer recorded.)"
        escaped_answer = escape(answer).replace(" \n", "&#32;\n")
        systems.append(f'<section class="answer"><h4>{system.title()} · {grade_text(result)}</h4>'
                       f'<blockquote>{escaped_answer}</blockquote><p>{escape(result["reason"] or "")}</p></section>')
    return (f'<details id="{escape(row["task_id"])}"><summary>{escape(row["question"])} '
            f'<small> · {LABELS[row["role"]]}</small></summary><div><p>{escape(row["pass_behavior"])}</p>'
            + "".join(systems) + "</div></details>")

def findings(items):
    links = []
    for row in items:
        missed = [system.title() for system, result in row["systems"].items()
                  if result["judged"] and result["criterion_met"] is False]
        if missed:
            links.append(f'<li><a href="#{escape(row["task_id"])}">{escape(row["topic"].replace("_", " "))}</a>'
                         f' · {LABELS[row["role"]]} · {", ".join(missed)}</li>')
    if not links:
        return "<p>Neither system missed an applicable criterion among the judged responses.</p>"
    return "<ul>" + "".join(links) + "</ul>"

def render(report):
    result = json.loads((report / "safety-results.json").read_text(encoding="utf8"))
    summary = json.loads((report / "safety-summary.json").read_text(encoding="utf8"))
    items = result["items"]
    checked(items, summary)
    grid = [[label] + [count_text(summary["systems"][s][key]) for s in SYSTEMS] for key,label,_ in METRICS]
    grid.append(["Meets the task criterion"] + [
        count_text(summary["systems"][s]["criterion_met"]) for s in SYSTEMS])
    shared = sum(row["systems"]["agent"]["vote_key"] is not None and
                 row["systems"]["agent"]["vote_key"] == row["systems"]["baseline"]["vote_key"]
                 for row in items)
    metrics = "".join("<tr>" + "".join(f"<td>{escape(s)}</td>" for s in row) + "</tr>" for row in grid)
    sections = []
    for role, name in LABELS.items():
        questions = [row for row in items if row["role"] == role]
        sections.append(f"<section><h2>{name} ({len(questions)})</h2>" + "".join(map(show_case, questions)) + "</section>")
    page = (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<title>English Coach · Safety evaluation</title><style>{STYLE}</style><main>'
            f'<nav aria-label="Report links"><a id="evaluation-home" href="../" hidden>← Evaluation overview</a>'
            f'<a href="safety-summary.json" download>Download summary (JSON)</a>'
            f'<a href="safety-results.json" download>Download all 50 cases (JSON)</a></nav>'
            f'<h1>English Coach safety evaluation</h1><p>{METHOD}</p>'
            f'<table><thead><tr><th scope="col">Observed measure</th><th scope="col">Agent</th>'
            f'<th scope="col">Baseline</th></tr></thead><tbody>{metrics}</tbody></table>'
            f'<p>The systems produced identical judging inputs on {shared} of 50 tasks. Each identical pair '
            f'used the same three votes.</p><p>{SCOPE}</p>'
            f'<h2>Safety challenges by type</h2>{breakdown(items)}<h2>Missed criteria</h2>{findings(items)}'
            f'<h2>Privacy finding from code review</h2><p>{PRIVACY}</p>' + "".join(sections)
            + '<footer><p>Podcast transcript excerpts retain their credited episode and speaker information. '
            '<a href="https://creativecommons.org/licenses/by-sa/4.0/">Transcript license: CC BY-SA 4.0</a>'
            '</p></footer></main>'
            "<script>if(location.protocol==='https:'||location.protocol==='http:'){"
            "document.getElementById('evaluation-home').hidden=false}function reveal(){const d=document.getElementById(location.hash.slice(1));"
            "if(d instanceof HTMLDetailsElement){d.open=true;d.scrollIntoView()}}"
            "addEventListener('hashchange',reveal);reveal()</script></html>")
    (report / "review.html").write_text(page + "\n", encoding="utf8")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    render(parser.parse_args().report)
