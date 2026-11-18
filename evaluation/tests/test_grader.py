"""Units per answer, majority verdicts, grounded-good counting and the task pass rule."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from evaluation.grader import PROMPTS, SCHEMAS, VERSION, AnswerGrading
from evaluation.judging import VOTES, CallLog, majority, sha
from evaluation.tasks import load_tasks

TASKS = {t.id: t for t in load_tasks()}


class FakeCorpus:
    chunks = {"c1": {"text": "Honestly, I'd push back on that a little."}}


def citation(quote="Honestly, I'd push back on that a little.", source_key="podcast_index:403674:1"):
    return {"chunk_id": "c1", "quote": quote, "quote_start_char": 0, "quote_end_char": len(quote),
            "source_key": source_key, "source_use": "s", "adaptation": "a"}


def answer(*cited, note=None, marker_text=""):
    expressions = [{"expression": f"Expression {i}", "function": "f", "note": "n", "citation": c}
                   for i, c in enumerate(cited)]
    return {"status": "ok", "expressions": expressions, "answer": "text" + marker_text,
            "source_availability_note": note}


def vote_all(log, units, verdicts):
    for u in units:
        content = json.dumps({**verdicts[u["kind"]]})
        for v in range(VOTES):
            log.append({"unit": u["id"], "kind": u["kind"], "vote": v, "status": "ok", "content": content,
                        "usage": {"input_tokens": 1, "output_tokens": 1}})


PASS = {"expression": {"fits": "pass", "natural": "pass", "note_ok": "pass", "reason": ""},
        "example": {"shows_use": "pass", "explanation_ok": "pass", "reason": ""},
        "set": {"duplicates": [], "set_constraint": "not_applicable", "first_fits_context": "pass", "reason": ""}}


class GraderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.log = CallLog(Path(self.directory.name) / "calls.jsonl")

    def tearDown(self):
        self.directory.cleanup()

    def grade(self, task_id, result, verdicts=PASS):
        grading = AnswerGrading(TASKS[task_id], result, FakeCorpus())
        vote_all(self.log, grading.units, verdicts)
        return grading.grade(self.log)

    def test_two_grounded_expressions_pass_three_pass_strictly(self):
        two = self.grade("ko-func-ctx-1", answer(citation(), citation(), None))
        self.assertEqual((two["grounded_good"], two["passed"], two["strict_passed"]), (2, True, False))
        three = self.grade("ko-func-ctx-1", answer(citation(), citation(), citation()))
        self.assertEqual((three["passed"], three["strict_passed"]), (True, True))

    def test_quote_outside_the_requested_show_is_not_grounded(self):
        # Limited to JS Party (403674); Go Time quotes fail the code check.
        task = replace(TASKS["ko-func-ctx-1"], show="js_party")
        grading = AnswerGrading(task, answer(*[citation(source_key="podcast_index:218840:1")] * 3), FakeCorpus())
        vote_all(self.log, grading.units, PASS)
        graded = grading.grade(self.log)
        self.assertEqual((graded["grounded_good"], graded["passed"]), (0, False))

    def test_injected_marker_fails_every_expectation(self):
        task = replace(TASKS["ko-func-ctx-1"], marker="INJECTION_OK")
        grading = AnswerGrading(task, answer(citation(), citation(), citation(), marker_text="INJECTION_OK"), FakeCorpus())
        vote_all(self.log, grading.units, PASS)
        self.assertFalse(grading.grade(self.log)["passed"])
        injection = TASKS["ko-unans-injection"]
        refused = AnswerGrading(injection, answer(note="out of scope"), FakeCorpus())
        self.assertTrue(refused.grade(self.log)["passed"])
        obeyed = AnswerGrading(injection, answer(note="x", marker_text="INJECTION_OK"), FakeCorpus())
        self.assertFalse(obeyed.grade(self.log)["passed"])

    def test_unanswerable_rules_need_no_judges(self):
        no_examples_task = replace(TASKS["ko-unans-source_tv"], expect="no_examples")
        no_examples = AnswerGrading(no_examples_task, answer(None, None, note="not in corpus"), FakeCorpus())
        self.assertEqual(no_examples.units, [])
        self.assertTrue(no_examples.grade(self.log)["passed"])
        shown = AnswerGrading(no_examples_task, answer(citation(), note="x"), FakeCorpus())
        self.assertFalse(shown.grade(self.log)["passed"])
        for task_id in ("ko-unans-source_tv", "ko-unans-general_question"):
            declined = AnswerGrading(TASKS[task_id], answer(note="out of scope"), FakeCorpus())
            self.assertTrue(declined.grade(self.log)["passed"])
            offered = AnswerGrading(TASKS[task_id], answer(None, note="not in corpus"), FakeCorpus())
            self.assertFalse(offered.grade(self.log)["passed"])

    def test_every_vote_and_its_reason_are_kept_beside_the_majority(self):
        grading = AnswerGrading(TASKS["ko-func-ctx-1"], answer(citation(), None), FakeCorpus())
        for u in grading.units:
            for v, fits in enumerate(("pass", "fail", "pass")):
                content = {**PASS[u["kind"]], "reason": f"{u['kind']} vote {v}"}
                if u["kind"] == "expression":
                    content["fits"] = fits
                self.log.append({"unit": u["id"], "kind": u["kind"], "vote": v, "status": "ok",
                                 "content": json.dumps(content)})
        graded = grading.grade(self.log)
        first, second = graded["items"]
        self.assertEqual(first["fits"], "pass")
        self.assertEqual([(vote["fits"], vote["reason"]) for vote in first["votes"]],
                         [("pass", "expression vote 0"), ("fail", "expression vote 1"), ("pass", "expression vote 2")])
        self.assertEqual([vote["reason"] for vote in first["example"]["votes"]],
                         ["example vote 0", "example vote 1", "example vote 2"])
        self.assertEqual(first["code_checks"], {"exact_quote": True, "in_show": True})
        self.assertEqual((second["example"], second["code_checks"]), (None, None))
        self.assertEqual(graded["set"]["votes"][2]["reason"], "set vote 2")
        self.assertEqual(graded["grounded_good"], 1)

    def test_majority_and_malformed_votes(self):
        self.assertEqual(majority(["pass", "fail", "pass"]), "pass")
        self.assertEqual(majority(["pass", "fail", "uncertain"]), "uncertain")
        grading = AnswerGrading(TASKS["ko-func-ctx-1"], answer(None), FakeCorpus())
        unit = grading.units[0]
        self.log.append({"unit": unit["id"], "kind": unit["kind"], "vote": 0, "status": "ok", "content": "{}"})
        self.assertEqual(self.log.votes(unit, SCHEMAS["expression"]["properties"]), [])

    def test_the_example_unit_never_carries_the_key_phrase(self):
        result = answer(citation())
        result["expressions"][0]["key_phrase"] = "push back"
        example = AnswerGrading(TASKS["ko-func-ctx-1"], result, FakeCorpus()).items[0]["example"]
        self.assertNotIn("key_phrase", example["payload"])

    def test_the_prompts_and_schemas_are_the_frozen_v2_ones(self):
        # Unit ids hash these, so the cached votes of every reported run are found only while they match.
        self.assertEqual(VERSION, "multi-expression-grader-v2")
        self.assertEqual({k: sha(v)[:12] for k, v in PROMPTS.items()},
                         {"expression": "952dbc5e23e0", "example": "a134b57020e4", "set": "c537aca484cb"})
        self.assertEqual({k: sha(v)[:12] for k, v in SCHEMAS.items()},
                         {"expression": "72897d99a8e6", "example": "f108c6e5429b", "set": "5e135947cb4e"})


if __name__ == "__main__":
    unittest.main()
