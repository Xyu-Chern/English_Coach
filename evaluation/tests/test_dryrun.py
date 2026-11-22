"""Offline end to end: eval run, grade, report and review on the authored tasks for both systems
(baseline and agent), with no network or database."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from evaluation import eval as cli
from evaluation.report import read_jsonl, write_report
from evaluation.runner import SYSTEMS
from evaluation.tasks import load_tasks
from evaluation.tests.offline import CHAT_MODEL, SCENARIOS, OfflineCorpus, OfflineJudge, dry_run
from evaluation.viewer import build_review

TASKS = sorted(t.id for t in load_tasks() if t.id in SCENARIOS)


def _shared(row: dict) -> list[dict]:
    return [s for s in row["result"]["trace"] if s.get("details", {}).get("shared")]


def _own(row: dict) -> list[str]:
    """The stages of the system's own steps, after the shared first stage."""
    return [s["stage"] for s in row["result"]["trace"] if not s.get("details", {}).get("shared")]


def _rows(run_dir: Path) -> dict:
    return {system: {r["task_id"]: r for r in read_jsonl(run_dir / system / "attempts.jsonl")} for system in SYSTEMS}


class DryRunTests(unittest.TestCase):
    """The authored scenarios with the submitted evaluation's agent (no verified-slot lock)."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.run_dir = dry_run(Path(cls.directory.name), run="dryrun", repeats=1, locked=False)
        cls.grades = {g["key"]: g for g in read_jsonl(cls.run_dir / "grades" / "grades.jsonl")}
        cls.rows = _rows(cls.run_dir)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_every_unit_is_run_graded_and_priced_for_both_systems(self):
        self.assertEqual(SYSTEMS, ("baseline", "agent"))
        self.assertEqual(len(self.grades), len(SYSTEMS) * len(TASKS))
        manifest = json.loads((self.run_dir / "manifest.json").read_text())
        self.assertEqual((manifest["repeats"], sorted(manifest["tasks"]), manifest["systems"]), (1, TASKS, list(SYSTEMS)))
        for system in SYSTEMS:
            self.assertEqual(sorted(self.rows[system]), TASKS)
            for row in self.rows[system].values():
                self.assertEqual(row["result"]["status"], "ok")
                self.assertEqual(row["cost"]["workflow"]["status"], "list_price_estimate")
        self.assertTrue((self.run_dir / "code.diff").exists())

    def test_both_systems_start_from_the_same_prefix(self):
        for task in self.rows["agent"]:
            prefixes = {json.dumps(_shared(self.rows[system][task]), sort_keys=True, default=str) for system in SYSTEMS}
            self.assertEqual(len(prefixes), 1, task)

    def test_the_baseline_revises_only_slots_without_a_verified_example(self):
        for task in ("ko-spec-ctx-1", "ko-usage-con-1"):  # three verified examples: nothing to revise
            self.assertEqual(_own(self.rows["baseline"][task]), ["assemble"], task)
        # a rejected pick: one revision adopts a seen span for a reserve expression, so no search follows
        self.assertEqual(_own(self.rows["baseline"]["ko-spec-idiom-ctx-1"]),
                         ["revise_1", "validate_select_2", "assemble"])

    def test_the_agent_reviews_the_draft_and_acts_on_it(self):
        own = {task: _own(self.rows["agent"][task]) for task in TASKS}
        self.assertEqual(own["ko-spec-ctx-1"], ["agent_1", "repick_1_1", "repick_1_2", "validate_agent_1", "assemble"])
        self.assertEqual(own["ko-usage-con-1"], ["agent_1", "search_1_1", "validate_agent_1", "agent_2",
                                                 "replace_2_1", "validate_agent_2", "assemble"])
        self.assertEqual(own["ko-spec-idiom-ctx-1"], ["agent_1", "repick_1_1", "validate_agent_1", "assemble"])
        for task in ("ko-unans-source_other_show", "ko-unans-injection"):  # a declined request has no turn
            self.assertEqual(own[task], ["assemble"])
        schemas = [e["response_schema"] for e in self.rows["agent"]["ko-usage-con-1"]["result"]["model_events"]
                   if not e.get("shared")]
        self.assertEqual(schemas, ["AgentDecision", "AgentDecision"])

    def test_the_scenarios_separate_the_systems(self):
        passed = {key: (g["passed"], g["strict_passed"]) for key, g in self.grades.items()}
        self.assertEqual(passed["ko-spec-ctx-1/baseline/1"], (False, False))  # both wrong quotes kept
        self.assertEqual(passed["ko-usage-con-1/baseline/1"], (False, False))  # no question form
        for task in ("ko-spec-ctx-1", "ko-usage-con-1", "ko-spec-idiom-ctx-1"):
            self.assertEqual(passed[f"{task}/agent/1"], (True, True), task)
        self.assertEqual(passed["ko-spec-idiom-ctx-1/baseline/1"], (True, True))
        for task in ("ko-unans-source_other_show", "ko-unans-injection"):
            for system in SYSTEMS:
                self.assertEqual(self.grades[f"{task}/{system}/1"]["with_example"], 0)
                self.assertTrue(self.grades[f"{task}/{system}/1"]["passed"])

    def test_grading_a_finished_run_again_reuses_every_vote(self):
        before = (self.run_dir / "grades" / "grades.jsonl").read_bytes()

        class NoCalls(OfflineJudge):
            def __call__(self, kind, payload):
                raise AssertionError("a cached vote was judged again")

        with patch.dict(os.environ, {"LLM_MODEL": CHAT_MODEL}), patch("evaluation.judging.Judge", NoCalls), \
                redirect_stdout(io.StringIO()) as output:
            cli.grade(self.run_dir, 4, True, corpus=OfflineCorpus())
            cli.grade(self.run_dir, 4, False, corpus=OfflineCorpus())
        self.assertEqual(json.loads(output.getvalue().splitlines()[0])["missing_votes"], 0)
        self.assertEqual((self.run_dir / "grades" / "grades.jsonl").read_bytes(), before)

    def test_the_report_and_the_review_page_cover_the_run_plan(self):
        planned = cli.planned_tasks(self.run_dir)
        self.assertEqual(sorted(t.id for t in planned), TASKS)  # the run's own plan, not the whole file
        payload = write_report([asdict(t) for t in planned], self.run_dir)
        self.assertEqual({s: payload["coverage"][s]["graded"] for s in SYSTEMS}, dict.fromkeys(SYSTEMS, len(TASKS)))
        self.assertTrue(build_review(self.run_dir, planned).exists())

    def test_the_report_writes_one_compact_log_per_system(self):
        order = [t.id for t in cli.planned_tasks(self.run_dir)]
        for system in SYSTEMS:
            lines = read_jsonl(self.run_dir / "report" / "logs" / f"{system}.jsonl")
            self.assertEqual([line["task_id"] for line in lines], order)  # task order, one line per attempt
            for line in lines:
                grade = self.grades[f"{line['task_id']}/{system}/{line['run']}"]
                self.assertEqual((line["system"], line["passed"], line["strict_passed"]),
                                 (system, grade["passed"], grade["strict_passed"]))
                self.assertEqual([s["stage"] for s in line["steps"]],
                                 [s["stage"] for s in self.rows[system][line["task_id"]]["result"]["trace"]])
                self.assertTrue(all(s["summary"] for s in line["steps"]))
                self.assertNotIn("model_events", json.dumps(line))
        agent = {line["task_id"]: line for line in read_jsonl(self.run_dir / "report" / "logs" / "agent.jsonl")}
        steps = {s["stage"]: s["summary"] for s in agent["ko-usage-con-1"]["steps"]}
        self.assertIn("search", steps["agent_1"])
        self.assertEqual(steps["validate_agent_2"], "3/3 slots verified")
        self.assertTrue(all(e["verified"] and e["quote"] for e in agent["ko-spec-ctx-1"]["expressions"]))
        self.assertEqual(agent["ko-unans-injection"]["expressions"], [])


class LockedDryRunTests(unittest.TestCase):
    """The same scenarios with the registered agent, which keeps the verified-slot lock (D1)."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.run_dir = dry_run(Path(cls.directory.name), run="dryrun-locked", repeats=1)
        cls.grades = {g["key"]: g for g in read_jsonl(cls.run_dir / "grades" / "grades.jsonl")}
        cls.rows = _rows(cls.run_dir)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_three_verified_examples_end_both_systems_after_the_first_stage(self):
        for task in ("ko-spec-ctx-1", "ko-usage-con-1"):
            with self.subTest(task=task):
                agent, baseline = self.rows["agent"][task]["result"], self.rows["baseline"][task]["result"]
                self.assertEqual(_own(self.rows["agent"][task]), ["assemble"])
                self.assertTrue(all(e.get("shared") for e in agent["model_events"]))  # no call of its own
                self.assertEqual(agent["expressions"], baseline["expressions"])
                self.assertEqual(self.grades[f"{task}/agent/1"]["passed"], self.grades[f"{task}/baseline/1"]["passed"])

    def test_the_agent_still_fills_a_slot_without_a_verified_example(self):
        self.assertEqual(_own(self.rows["agent"]["ko-spec-idiom-ctx-1"]),
                         ["agent_1", "repick_1_1", "validate_agent_1", "assemble"])
        self.assertEqual(self.grades["ko-spec-idiom-ctx-1/agent/1"]["passed"], True)

    def test_every_example_verified_first_leads_the_final_answer_unchanged(self):
        for system in SYSTEMS:
            for task, row in self.rows[system].items():
                with self.subTest(system=system, task=task):
                    first = next((s for s in row["result"]["trace"] if s["stage"] == "validate_select_1"), None)
                    shown = [(s["expression"], s["quote"]) for s in (first or {}).get("details", {}).get("slots", [])
                             if s["status"] == "verified"]
                    final = [(e["expression"], (e.get("citation") or {}).get("quote"))
                             for e in row["result"]["expressions"] or []]
                    self.assertEqual(final[:len(shown)], shown)


if __name__ == "__main__":
    unittest.main()
