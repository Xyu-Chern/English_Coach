"""The same export command that prepares the team's Vercel scorecard."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evaluation.report import REPEATS, SYSTEMS, attempt_key

ROOT = Path(__file__).resolve().parents[2]


class ExportBenchmarkTest(unittest.TestCase):
    def test_exports_completed_pairs_and_preserves_previous_file_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "team-run"
            (run / "grades").mkdir(parents=True)
            (run / "manifest.json").write_text(json.dumps({
                "tasks": {"task-1": {"expect": "answer", "question": "private task text"}},
                "systems": list(SYSTEMS), "repeats": REPEATS, "environment": {"model": "demo"},
            }))
            (run / "grades/manifest.json").write_text(json.dumps({"votes": 3, "protocol": "rubric-v1"}))
            grades = []
            for system in SYSTEMS:
                (run / system).mkdir()
                attempts = []
                for number in range(1, REPEATS + 1):
                    declined = number == 3 and system == "agent"
                    attempt = {"task_id": "task-1", "variant": system, "attempt": number}
                    usage = None if declined else {"input_tokens": 20, "output_tokens": 10, "total_chat_calls": 2}
                    trace = [{"stage": "decline", "details": {"shared": True}}] if declined else []
                    attempts.append({**attempt, "result": {"status": "ok", "usage": usage, "trace": trace}})
                    grades.append({**attempt, "key": attempt_key(attempt), "expect": "answer", "passed": not declined,
                                   "status": "ok", "model_calls": 1 if declined else 2, "grounded_good": 0 if declined else 2})
                (run / system / "attempts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in attempts))
            grade_file = run / "grades/grades.jsonl"
            complete_grades = "".join(json.dumps(row) + "\n" for row in grades)
            grade_file.write_text(complete_grades)
            safety = root / "safety.json"
            safety.write_text(json.dumps({
                "run": "team-run",
                "prompts": [
                    {"id": "s-1", "kind": "attack", "surface": "question", "criterion": "stay in scope",
                     "verdicts": {"baseline": "unsafe", "agent": None}},
                    {"id": "s-2", "kind": "benign", "surface": "question", "criterion": "accept translation",
                     "verdicts": {"baseline": "safe", "agent": "safe"}},
                ],
                "over_refusals": {"task-1/agent/3": True},
                "failure": "task-1/agent/3",
            }))
            output = root / "public/admin/benchmark.json"
            cmd = [sys.executable, "-m", "evaluation.export_benchmark", "--run", run.name, "--results", str(root),
                   "--safety", str(safety), "--out", str(output)]
            subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True)
            original = output.read_text()
            data = json.loads(original)
            self.assertNotIn("private task text", original)
            self.assertEqual(data["safety_prompts"], 2)
            self.assertEqual(data["attack_prompts"], 1)
            self.assertEqual(data["systems"]["baseline"]["pass3"], {"passed": 1, "n": 1})
            agent = data["systems"]["agent"]
            self.assertEqual(agent["accuracy"]["passed"], 2)
            self.assertEqual(agent["pass3"], {"passed": 0, "n": 1})
            self.assertEqual(agent["pass_at3"], {"passed": 1, "n": 1})
            self.assertEqual(agent["tokens"], {"mean": 30, "n": 2})
            self.assertEqual(agent["attack_success"], {"events": 0, "judged": 0, "expected": 1})
            self.assertEqual(agent["over_refusal"], {"events": 1, "judged": 3, "expected": 3})
            self.assertEqual(data["failure"]["attempt"], 3)
            self.assertEqual(data["failure"]["status"], "declined")

            for bad in (complete_grades + json.dumps(grades[0]) + "\n",
                        "".join(json.dumps(row) + "\n" for row in grades[:-1])):
                grade_file.write_text(bad)
                failed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(output.read_text(), original)
