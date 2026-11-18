"""The task file: assignment minimums, field order and validation, English fields, id scheme."""

import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from evaluation.tasks import INPUT_TYPES, TASKS, EvalTask, load_tasks, summarize

ORDER = ["id", "type", "question", "question_en", "rubric", "language", "group", "input_type", "condition",
         "category", "constraint", "show", "expect", "marker", "intended"]
QUOTE_CHECK = "each expression comes with a real podcast quote that shows this use"
KINDS = {"spec": "specific", "func": "function", "draft": "draft", "usage": "usage", "cmp": "compare"}
CONDITIONS = {"ctx": "context", "con": "constraint", "plain": "plain"}
REGULAR_ID = re.compile(r"ko-(spec|func|draft|usage|cmp)(-idiom)?-(ctx|con|plain)-([1-9][0-9]*)")
# A run of ASCII text in a Korean request: a quoted English phrase, a draft, a name, a marker.
ASCII_RUN = re.compile(r"[A-Za-z][ -~]*[A-Za-z0-9.?!]|[A-Za-z]")


def rows() -> list[dict]:
    return [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]


def write(directory: str, *lines: dict) -> Path:
    path = Path(directory) / "tasks.jsonl"
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
    return path


class TaskFileTests(unittest.TestCase):
    def test_the_submission_file_meets_the_assignment_minimums(self):
        summary = summarize(load_tasks())
        self.assertEqual(summary["problems"], [])
        self.assertEqual(summary["tasks"], 50)
        self.assertEqual(summary["groups"], {"regular": 37, "edge": 6, "unanswerable": 7})
        self.assertEqual(summary["types"], {"rubric": 43, "unanswerable": 7})

    def test_every_row_has_the_documented_fields_in_order(self):
        for row in rows():
            with self.subTest(id=row["id"]):
                self.assertEqual(list(row), ORDER)

    def test_regular_tasks_cover_every_input_type(self):
        regular = [t for t in load_tasks() if t.group == "regular"]
        self.assertEqual({t.input_type for t in regular}, set(INPUT_TYPES))
        self.assertEqual({(t.input_type, t.condition) for t in regular if t.condition == "plain"}, {("usage", "plain")})
        self.assertTrue(all(t.show is None for t in regular))

    def test_unanswerable_tasks_decline_and_the_injection_has_a_marker(self):
        tasks = load_tasks()
        unanswerable = [t for t in tasks if t.group == "unanswerable"]
        self.assertEqual({(t.expect, t.type) for t in unanswerable}, {("decline", "unanswerable")})
        self.assertEqual({(t.expect, t.type) for t in tasks if t.group != "unanswerable"}, {("answer", "rubric")})
        self.assertEqual([t.marker for t in unanswerable if t.marker], ["INJECTION_OK"])

    def test_ids_follow_the_documented_scheme(self):
        for task in load_tasks():
            with self.subTest(id=task.id):
                if task.group == "regular":
                    match = REGULAR_ID.fullmatch(task.id)
                    self.assertIsNotNone(match)
                    kind, idiom, condition, _ = match.groups()
                    self.assertEqual((KINDS[kind], CONDITIONS[condition]), (task.input_type, task.condition))
                    self.assertTrue(idiom is None or kind == "spec")
                else:
                    prefix = {"edge": "ko-edge-", "unanswerable": "ko-unans-"}[task.group]
                    self.assertEqual(task.id, prefix + task.condition)
                self.assertEqual(task.language, "en" if task.id == "ko-edge-english_only" else "ko")


class EnglishFieldTests(unittest.TestCase):
    def test_question_en_keeps_every_english_phrase_of_the_question(self):
        for task in load_tasks():
            with self.subTest(id=task.id):
                for phrase in ASCII_RUN.findall(task.question):
                    self.assertIn(phrase, task.question_en)

    def test_the_rubric_has_two_to_four_checks_and_answer_tasks_require_a_quote(self):
        for task in load_tasks():
            with self.subTest(id=task.id):
                self.assertTrue(2 <= len(task.rubric) <= 4)
                self.assertEqual(len(set(task.rubric)), len(task.rubric))
                if task.type == "rubric":
                    self.assertEqual(task.rubric[-1], QUOTE_CHECK)
                else:
                    self.assertNotIn(QUOTE_CHECK, task.rubric)
                    self.assertTrue(any("no expressions" in check for check in task.rubric))

    def test_explicit_word_constraints_appear_in_the_rubric(self):
        tasks = {t.id: t for t in load_tasks()}
        for task_id, phrase in {"ko-spec-con-1": "'keep up'", "ko-spec-idiom-con-2": "'spilled'",
                                "ko-func-con-1": "'maybe'", "ko-draft-con-2": "'useful'",
                                "ko-usage-con-4": "'bikeshed'", "ko-unans-injection": "INJECTION_OK"}.items():
            with self.subTest(id=task_id):
                self.assertTrue(any(phrase in check for check in tasks[task_id].rubric))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.row = rows()[0]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_rubric_is_a_tuple_and_list_input_is_accepted(self):
        task = EvalTask(**self.row)
        self.assertIsInstance(task.rubric, tuple)
        self.assertEqual(list(task.rubric), self.row["rubric"])

    def test_bad_rows_are_refused(self):
        bad = {
            "blank question_en": {**self.row, "question_en": "  "},
            "empty rubric": {**self.row, "rubric": []},
            "blank rubric item": {**self.row, "rubric": ["fits", ""]},
            "rubric as a string": {**self.row, "rubric": "fits"},
            "type does not match expect": {**self.row, "type": "unanswerable"},
            "decline typed as rubric": {**self.row, "expect": "decline"},
            "constraint without the constraint condition": {**self.row, "constraint": "length"},
            "category mismatch": {**self.row, "category": "draft/context"},
            "unknown field": {**self.row, "notes": "x"},
            "missing field": {k: v for k, v in self.row.items() if k != "question_en"},
        }
        for name, row in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    load_tasks(write(self.directory.name, row))

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            load_tasks(write(self.directory.name, self.row, self.row))


class SummaryTests(unittest.TestCase):
    def test_the_count_is_reported_not_required(self):
        tasks = load_tasks()
        larger = tasks + [replace(t, id=f"{t.id}-copy{n}") for n in range(3) for t in tasks]
        summary = summarize(larger)
        self.assertEqual((summary["tasks"], summary["problems"]), (200, []))
        self.assertEqual(summary["groups"], {"regular": 148, "edge": 24, "unanswerable": 28})

    def test_minimums_and_unique_ids_are_checked(self):
        tasks = load_tasks()
        few = [t for t in tasks if t.group == "regular"] + [t for t in tasks if t.group == "edge"][:2] \
            + [t for t in tasks if t.group == "unanswerable"][:1]
        self.assertEqual(summarize(few)["problems"], ["at least 3 edge cases are required, found 2",
                                                     "at least 2 unanswerable tasks are required, found 1"])
        self.assertEqual(summarize(tasks + tasks[:1])["problems"], ["duplicate task ids: ['ko-spec-ctx-1']"])


if __name__ == "__main__":
    unittest.main()
