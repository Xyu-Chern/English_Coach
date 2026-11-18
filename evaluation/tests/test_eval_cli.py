"""Command line: the manifest records tasks.jsonl and its sha256, grade/report/review refuse a run made
with another version of the file, a run is reported against its own plan; default repeats 3."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from evaluation import eval as cli
from evaluation.runner import file_sha256
from evaluation.tasks import TASKS, load_tasks
from evaluation.tests.offline import OfflineEnvironment


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name) / "run"

    def tearDown(self):
        self.directory.cleanup()

    def prepare(self, tasks, systems=None):
        with redirect_stdout(io.StringIO()) as output:
            cli.run(self.run_dir, tasks, repeats=cli.DEFAULT_REPEATS, workers=1, max_new=None, prepare_only=True,
                    environment=OfflineEnvironment(), systems=systems)
        return json.loads(output.getvalue().strip().splitlines()[-1])

    def test_the_manifest_records_the_task_file_its_sha_and_three_repeats(self):
        tasks = cli.select_tasks("ko-spec-ctx-1,ko-unans-injection")
        status = self.prepare(tasks)
        self.assertEqual((status["pending_units"], status["systems"]), (2 * 3, ["baseline", "agent"]))
        manifest = json.loads((self.run_dir / "manifest.json").read_text())
        self.assertEqual((manifest["repeats"], manifest["systems"]), (3, ["baseline", "agent"]))
        self.assertEqual((manifest["task_file"], manifest["tasks_sha256"]),
                         ("evaluation/data/tasks.jsonl", file_sha256(TASKS)))
        self.assertEqual([t.id for t in cli.planned_tasks(self.run_dir)], [t.id for t in tasks])

    def test_a_run_made_with_another_task_file_is_refused(self):
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "manifest.json").write_text(json.dumps({"tasks_sha256": "0" * 64, "tasks": None}))
        for command in (cli.planned_tasks, cli.report, cli.review):
            with self.assertRaises(SystemExit):
                command(self.run_dir)

    def test_a_run_without_a_manifest_uses_every_task(self):
        self.assertEqual([t.id for t in cli.planned_tasks(self.run_dir)], [t.id for t in load_tasks()])

    def test_named_tasks_come_in_file_order_and_unknown_ones_are_refused(self):
        ids = [t.id for t in load_tasks()]
        self.assertEqual([t.id for t in cli.select_tasks(f"{ids[2]},{ids[0]}")], [ids[0], ids[2]])
        with self.assertRaises(SystemExit):
            cli.select_tasks("no-such-task")

    def test_one_system_can_be_named_and_an_unknown_one_is_refused(self):
        self.assertEqual(cli.select_systems(None), ("baseline", "agent"))
        self.assertEqual(cli.select_systems("agent"), ("agent",))
        self.assertEqual(self.prepare(cli.select_tasks("ko-spec-ctx-1"), ("agent",))["systems"], ["agent"])
        with self.assertRaises(SystemExit):
            cli.select_systems("no_such_system")


if __name__ == "__main__":
    unittest.main()
