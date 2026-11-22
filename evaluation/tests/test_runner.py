"""Runner: one unit per (task, repeat), both systems' rows together, resumable, refuses unknown paid outcomes."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from evaluation import runner
from evaluation.runner import ROOT, SYSTEMS, UNIT_TRIES, Runner, PairAttempt, RunPlan, git_state
from evaluation.tasks import load_tasks
from evaluation.tests.offline import OfflineChat, OfflineEnvironment, submission_agent

PRICING = json.loads((ROOT / "evaluation/data/pricing.json").read_text())


def pair(status="ok", error_code=None, systems=SYSTEMS):
    """A stub attempt: one result per system, no model or database."""
    def attempt(task):
        return {s: ({"status": status, "variant": s, "error_code": error_code, "expressions": []},
                    {"workflow": {"usd": 0.01}}) for s in systems}
    return attempt


def rows(run_dir: Path, system: str) -> list[dict]:
    path = run_dir / system / "attempts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.plan = RunPlan(load_tasks()[:2], repeats=3, workers=2)
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name) / "run"
        no_wait = mock.patch.object(runner, "RETRY_WAIT_SECONDS", (0.0, 0.0))
        no_wait.start()
        self.addCleanup(no_wait.stop)

    def tearDown(self):
        self.directory.cleanup()

    def test_schedule_has_every_task_and_repeat_once_in_a_fixed_order(self):
        schedule = [(task.id, attempt) for task, attempt in self.plan.schedule()]
        self.assertEqual(len(set(schedule)), 6)
        self.assertEqual(schedule, [(task.id, attempt) for task, attempt in self.plan.schedule()])

    def test_default_repeats_and_the_task_file_is_a_hashed_source(self):
        from evaluation.runner import SOURCES, source_hashes

        self.assertEqual(RunPlan([]).repeats, 3)
        self.assertIn("evaluation/data/tasks.jsonl", SOURCES)
        self.assertEqual(sorted(source_hashes()), SOURCES)  # every source exists
        # the coach's subpackages too: a change to the agent, its lock or its prompt changes the manifest
        self.assertLessEqual({"translation_agent_demo/agents/systems/agent.py",
                              "translation_agent_demo/agents/systems/base.py",
                              "translation_agent_demo/agents/prompts/agent.py",
                              "translation_agent_demo/agents/schemas/agent.py"}, set(SOURCES))

    def test_resume_runs_each_unit_once_with_a_row_per_system(self):
        self.assertEqual(Runner(self.plan, self.run_dir, pair(), {"v": 1}).run(max_new=2)["agent/ok"], 2)
        statuses = Runner(self.plan, self.run_dir, pair(), {"v": 1}).run()
        self.assertEqual({statuses[f"{system}/ok"] for system in SYSTEMS}, {4})
        for system in SYSTEMS:
            keys = [(r["task_id"], r["attempt"]) for r in rows(self.run_dir, system)]
            self.assertEqual((len(keys), len(set(keys))), (6, 6))
            self.assertTrue(all(r["variant"] == system for r in rows(self.run_dir, system)))
        self.assertEqual(json.loads((self.run_dir / "manifest.json").read_text())["systems"], list(SYSTEMS))

    def test_one_system_writes_only_its_rows_and_a_resume_with_both_is_refused(self):
        systems = ("agent",)
        Runner(self.plan, self.run_dir, pair(systems=systems), {}, systems=systems).run(max_new=1)
        self.assertEqual(json.loads((self.run_dir / "manifest.json").read_text())["systems"], ["agent"])
        self.assertEqual([p.name for p in self.run_dir.iterdir() if p.is_dir()], ["agent"])
        with self.assertRaises(SystemExit):
            Runner(self.plan, self.run_dir, pair(), {}).run()
        with self.assertRaises(ValueError):
            Runner(self.plan, self.run_dir, pair(), {}, systems=("no_such_system",))

    def test_an_attempt_missing_a_system_becomes_an_error_row_for_both(self):
        Runner(RunPlan(load_tasks()[:1], repeats=1, workers=1), self.run_dir,
                         pair(systems=SYSTEMS[:-1]), {}).run()
        for system in SYSTEMS:
            row = rows(self.run_dir, system)[0]
            self.assertEqual((row["result"]["error_code"], row["unit_tries"]), ("exception", UNIT_TRIES))

    def test_refuses_a_changed_manifest_but_not_a_new_worker_count_git_state_or_judge(self):
        first = {"v": 1, "git": {"commit": "a"}, "judge": {"model": "judge-a"}}
        Runner(self.plan, self.run_dir, pair(), first).run(max_new=1)
        with self.assertRaises(SystemExit):
            Runner(self.plan, self.run_dir, pair(), {**first, "v": 2}).run()
        resumed = RunPlan(self.plan.tasks, repeats=3, workers=4)
        later = {"v": 1, "git": {"commit": "b"}, "judge": {"model": "judge-b"}}  # the judge changes no attempt
        statuses = Runner(resumed, self.run_dir, pair(), later).run()
        self.assertEqual(statuses["agent/ok"], 5)

    def test_refuses_a_unit_that_started_without_a_row_for_every_system(self):
        Runner(self.plan, self.run_dir, pair(), {}).run(max_new=1)
        task, attempt = next(u for u in self.plan.schedule() if (u[0].id, u[1]) not in
                             {(r["task_id"], r["attempt"]) for r in rows(self.run_dir, "agent")})
        with (self.run_dir / "baseline" / "attempts.jsonl").open("a") as stream:  # a crash after one system's row
            stream.write(json.dumps({"task_id": task.id, "attempt": attempt, "variant": "baseline"}) + "\n")
        with self.assertRaises(SystemExit):
            Runner(self.plan, self.run_dir, pair(), {}).run()

    def test_an_exception_becomes_an_error_row_for_every_system(self):
        def broken(task):
            raise ConnectionError("database down")
        Runner(self.plan, self.run_dir, broken, {}).run(max_new=1)
        for system in SYSTEMS:
            result = rows(self.run_dir, system)[0]["result"]
            self.assertEqual((result["variant"], result["error_code"], result["exception"]),
                             (system, "exception", "ConnectionError"))

    def test_an_infrastructure_failure_reruns_the_whole_unit_and_keeps_the_discarded_try(self):
        calls = []

        def flaky(task):  # the agent hits a rate limit on the first try of each unit only
            calls.append(task.id)
            first = calls.count(task.id) == 1
            return {s: ({"status": "error" if first and s == "agent" else "ok", "variant": s, "expressions": [],
                         "error_code": "model_unavailable" if first and s == "agent" else None},
                        {"workflow": {"usd": 0.01}}) for s in SYSTEMS}
        plan = RunPlan(load_tasks()[:1], repeats=1, workers=1)
        statuses = Runner(plan, self.run_dir, flaky, {}).run()
        self.assertEqual((statuses["baseline/ok"], statuses["agent/ok"], len(calls)), (1, 1, 2))
        for system in SYSTEMS:
            row = rows(self.run_dir, system)[0]
            self.assertEqual(row["unit_tries"], 2)
            self.assertEqual(row["discarded_tries"][0]["error_codes"], {"agent": "model_unavailable"})
            self.assertEqual(set(row["discarded_tries"][0]["cost"]), set(SYSTEMS))

    def test_a_model_error_that_is_not_infrastructure_is_never_retried(self):
        calls = []

        def refused(task):
            calls.append(task.id)
            return pair("error", "model_refused")(task)
        Runner(RunPlan(load_tasks()[:1], repeats=1, workers=1), self.run_dir, refused, {}).run()
        self.assertEqual((len(calls), rows(self.run_dir, "agent")[0]["unit_tries"]), (1, 1))

    def test_five_units_in_a_row_with_an_infrastructure_failure_stop_the_run(self):
        plan = RunPlan(load_tasks()[:4], repeats=3, workers=1)
        with self.assertRaises(SystemExit):
            Runner(plan, self.run_dir, pair("error", "model_unavailable"), {}).run()
        agent_rows = rows(self.run_dir, "agent")
        self.assertEqual(len(agent_rows), 5)  # the other seven units never start
        self.assertTrue(all(r["unit_tries"] == UNIT_TRIES for r in agent_rows))  # each was retried before counting

    def test_git_state_describes_the_working_tree(self):
        record, diff = git_state()
        self.assertRegex(record["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(len(record["diff_sha256"]), 64)
        self.assertTrue(all(re.fullmatch(r"(evaluation|translation_agent_demo)/.+", p)
                            for p in record["untracked_sha256"]))
        self.assertNotIn(".env", " ".join(record["untracked_sha256"]))


class PairAttemptTests(unittest.TestCase):
    """The live attempt wiring over the offline world: real systems, recorder, search and pricing."""

    def setUp(self):
        self.tasks = {t.id: t for t in load_tasks()}

    def test_the_prefix_is_recorded_once_per_unit_and_counted_in_both_systems(self):
        with submission_agent():  # the submitted evaluation's agent: its review turn runs on three verified examples
            outcome = PairAttempt(OfflineEnvironment(), PRICING)(self.tasks["ko-usage-con-1"])
        self.assertEqual(tuple(outcome), SYSTEMS)
        for result, cost in outcome.values():
            shared = [e for e in result["model_events"] if e.get("shared")]
            self.assertEqual([e["response_schema"] for e in shared], ["CandidateSet", "Selection"])
            self.assertEqual([e["call_index"] for e in result["model_events"]],
                             list(range(1, len(result["model_events"]) + 1)))
            self.assertEqual(sum(o.get("shared", False) for o in result["retrieval_observations"]), 6)
            self.assertEqual(result["usage"]["embedding_tokens"],
                             sum(o["input_tokens"] for o in result["retrieval_observations"]))
            self.assertEqual(cost["shared_prefix"], outcome["baseline"][1]["shared_prefix"])
        result, cost = outcome["baseline"]  # three verified examples: the baseline has nothing to revise
        self.assertEqual(result["model_rounds"], 2)
        self.assertEqual(cost["workflow"]["usd"], cost["shared_prefix"]["usd"])
        result, cost = outcome["agent"]  # the agent always gets its review turn; here it searches, then replaces
        self.assertEqual([e["response_schema"] for e in result["model_events"][2:]], ["AgentDecision"] * 2)
        self.assertGreater(cost["workflow"]["usd"], cost["shared_prefix"]["usd"])

    def test_a_subset_of_systems_runs_only_those_systems(self):
        outcome = PairAttempt(OfflineEnvironment(), PRICING, systems=("agent", "baseline"))(self.tasks["ko-usage-con-1"])
        self.assertEqual(tuple(outcome), ("baseline", "agent"))
        self.assertEqual([e["response_schema"] for e in outcome["baseline"][0]["model_events"]],
                         ["CandidateSet", "Selection"])  # no other system's calls leaked into the prefix record

    def test_a_refusal_keeps_its_code_and_is_not_an_infrastructure_failure(self):
        class Refusal(Exception):
            code = "model_refused"

        class RefusingChat(OfflineChat):
            def complete_with_usage(self, **call):
                raise Refusal("declined")

        class RefusingEnvironment(OfflineEnvironment):
            def chat_model(self):
                return RefusingChat()

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            plan = RunPlan([self.tasks["ko-spec-ctx-1"]], repeats=6, workers=1)
            statuses = Runner(plan, run_dir, PairAttempt(RefusingEnvironment(), PRICING), {}).run()
            self.assertEqual(statuses["agent/error"], 6)  # six refusals in a row, and the run did not stop
            row = rows(run_dir, "agent")[0]
            self.assertEqual(row["result"]["error_code"], "model_refused")
            self.assertEqual(row["result"]["model_events"][0]["error_code"], "model_refused")
            self.assertEqual(row["result"]["model_events"][0]["error_detail"], "declined")  # the provider's own text


if __name__ == "__main__":
    unittest.main()
