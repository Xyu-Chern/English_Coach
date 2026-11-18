"""Review page: one self-contained HTML file for a run of the baseline and the agent."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from evaluation.viewer import build_review

SPAN = "Honestly, I think we should wait and see before we decide anything big."


def task(task_id, expect="answer", **extra):
    return {"id": task_id, "language": "ko", "group": "regular" if expect == "answer" else "unanswerable",
            "input_type": "function" if expect == "answer" else None, "condition": "context",
            "category": "function/context" if expect == "answer" else "unanswerable/source_tv",
            "constraint": None, "show": None, "expect": expect, "marker": None,
            "type": "rubric" if expect == "answer" else "unanswerable",
            "question": "질문", "question_en": "The question.", "intended": "의도",
            "rubric": ["Offers a way to delay a decision."] if expect == "answer" else [], **extra}


def span(stage, ms=10.0, **details):
    return {"stage": stage, "status": "ok", "elapsed_ms": ms, "details": details}


def model(stage, output, shared=False):
    return span(stage, 900.0, model="claude-haiku-5-5", input_tokens=100, output_tokens=20, output=output,
                **({"shared": True} if shared else {}))


def prefix():
    hits = [{"chunk_id": "c1", "source_key": "podcast_index:218840:1", "show": "go_time", "episode_title": "Episode A",
             "snippet": "So " + SPAN + " That was it."}]
    picks = [{"candidate": 0, "ref": "c0h1s1", "expression": "Let's wait and see.", "key_phrase": "wait and see",
              "reusable_wording": "wait and see", "source_use": "s", "adaptation": "a"},
             {"candidate": 1, "ref": "c1h1s1", "expression": "Let's hold off.", "key_phrase": "hold off",
              "reusable_wording": "hold off", "source_use": "s", "adaptation": "a"}]
    return [model("candidates", {"kind": "function", "request_status": "answerable", "status_note": None,
                                 "candidates": [{"expression": "Let's wait and see.", "key_phrase": "wait and see",
                                                 "function": "delay", "note": "n"}]}, shared=True),
            span("search_1", query="Let's wait and see.", key_phrase="wait and see", slot=0, hits=hits,
                 corpus_count=4, shared=True),
            model("select_1", {"picks": picks}, shared=True),
            span("validate_select_1", shared=True, verified=1, slots=[
                {"slot": 0, "status": "verified", "ref": "c0h1s1", "rejection_reasons": []},
                {"slot": 1, "status": "no_example", "ref": None, "rejection_reasons": ["wording_lacks_key_phrase"]}])]


def baseline_steps():
    return [model("revise_1", {"replacements": [{"replaces": 1, "expression": "Let's pause on this.",
                                                 "key_phrase": "pause on", "function": "delay", "note": "less vague",
                                                 "ref": "c0h1s1", "reusable_wording": "wait and see",
                                                 "source_use": "s", "adaptation": "a"}]}),
            span("search_1_1", query="Let's pause on this.", key_phrase="pause on", slot=1, hits=[], corpus_count=0),
            span("assemble", expressions=1, with_example=1)]


def agent_steps():
    return [model("agent_1", {"assessment": "Slot 1 lacks an example.", "finish": False, "actions": [
                {"type": "repick", "slot": 1, "reason": "The quote does not show holding off.",
                 "ref": "c0h1s1", "reusable_wording": "wait and see", "source_use": "s", "adaptation": "a"},
                {"type": "search", "slot": 2, "reason": "The set lacks a question form.",
                 "query": "Should we wait?", "key_phrase": "should we wait"}]}),
            span("repick_1_1", slot=1, ref="c0h1s1", outcome="kept_verified_example", expression="Let's hold off.",
                 previous_expression="Let's hold off.", rejection_reasons=["wording_lacks_key_phrase"],
                 reason="The quote does not show holding off."),
            span("search_1_2", query="Should we wait?", key_phrase="should we wait", slot=2, skipped="no_searches_left"),
            span("validate_agent_1", verified=1, slots=[], noops=[],
                 guard=[{"slot": 1, "kept_ref": "c1h1s1", "reason": "repick_rejected:wording_lacks_key_phrase",
                         "moved_to_end": False}]),
            span("budget_check", remaining={"calls": 5, "searches": 8}),
            span("assemble", expressions=1, with_example=1)]


def attempt(system, trace, expressions, note=None, task_id="t1", payloads=()):
    shown = {"candidates": [{"candidate": 0, "expression": "Let's wait and see.",
                             "spans": [{"ref": "c0h1s1", "episode_title": "Episode A", "text": SPAN}]}]}
    events = [{"request_messages": [{"role": "user", "content": json.dumps(p)}]} for p in ({}, shown, *payloads)]
    return {"task_id": task_id, "variant": system, "attempt": 1, "result": {
        "status": "ok", "answer": "", "expressions": expressions, "source_availability_note": note,
        "model_rounds": 4, "tool_calls": [{}] * 2, "trace": trace, "elapsed_ms": 4000.0, "model_events": events,
        "usage": {"input_tokens": 300, "output_tokens": 60}}, "cost": {"workflow": {"usd": 0.002}}}


def cited(expression="Let's wait and see.", quote=SPAN):
    return {"expression": expression, "function": "delay", "note": "n", "citation": {
        "chunk_id": "c1", "source_key": "podcast_index:218840:1", "episode_title": "Episode A",
        "episode_url": "https://example.org/a", "quote": quote, "quote_start_char": 3, "quote_end_char": 3 + len(quote),
        "source_context": "So " + quote + " That was it.", "context_start_char": 0, "context_end_char": 99,
        "source_use": "s", "adaptation": "a"}}


def vote(reason, **verdicts):
    return {**verdicts, "reason": reason}


def grade(system, passed, task_id="t1", expect="answer"):
    item = {"fits": "pass", "natural": "pass", "note_ok": "pass",
            "votes": [vote(f"{system} fits {i}", fits="pass", natural="pass", note_ok="pass") for i in range(3)],
            "example": {"shows_use": "fail", "explanation_ok": "pass",
                        "votes": [vote("only topic words", shows_use="fail", explanation_ok="pass")] * 3},
            "code_ok": True, "code_checks": {"exact_quote": True, "in_show": True},
            "good_expression": True, "grounded_good": passed}
    return {"key": f"{task_id}/{system}/1", "task_id": task_id, "variant": system, "attempt": 1, "expect": expect,
            "category": "function/context", "status": "ok", "passed": passed, "strict_passed": False,
            "grounded_good": int(passed), "set_constraint_ok": True, "items": [item] if expect == "answer" else [],
            "set": {"duplicates": [], "set_constraint": "not_applicable", "first_fits_context": "pass",
                    "votes": [vote("fine", duplicates=[], set_constraint="not_applicable", first_fits_context="pass")]}}


def write_run(run_dir: Path) -> list[dict]:
    """Two tasks, one attempt each: an answer (shared first stage, then each system's own steps) and a decline."""
    dropped = {"dropped_last_turn": [{"step": "agent_0", "slot": 2, "reason": "key_phrase_not_contiguous"}]}
    own = {"baseline": (baseline_steps(), ()), "agent": (agent_steps(), (dropped,))}
    decline = [model("candidates", {"kind": "usage", "request_status": "source_not_available", "status_note": "no",
                                    "candidates": []}, shared=True),
               span("decline", request_status="source_not_available", shared=True)]
    for system, (steps, payloads) in own.items():
        (run_dir / system).mkdir(parents=True)
        rows = [attempt(system, prefix() + steps, [cited()], payloads=payloads),
                attempt(system, decline, [], "Not in the corpus.", task_id="u1")]
        (run_dir / system / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run_dir / "grades").mkdir()
    grades = [grade("baseline", False), grade("agent", True), grade("baseline", True, "u1", "decline"),
              grade("agent", True, "u1", "decline")]
    (run_dir / "grades" / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in grades))
    return [task("t1"), task("u1", "decline")]


def page_data(path: Path) -> dict:
    html = path.read_text()
    return json.loads(html.split('<script type="application/json" id="review-data">')[1].split("</script>")[0])


class ReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.directory.name) / "run"
        self.tasks = write_run(self.run_dir)

    def tearDown(self):
        self.directory.cleanup()

    def attempt(self):
        return page_data(build_review(self.run_dir, self.tasks))["tasks"][0]["attempts"][0]

    def test_page_is_one_offline_file(self):
        path = build_review(self.run_dir, self.tasks)
        self.assertEqual(path, self.run_dir / "report" / "review.html")
        html = path.read_text()
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        self.assertEqual(html.count("<script"), 2)

    def test_the_two_systems_in_order_and_nothing_else(self):
        (self.run_dir / "agent_old").mkdir()
        shutil.copy(self.run_dir / "agent" / "attempts.jsonl", self.run_dir / "agent_old" / "attempts.jsonl")
        data = page_data(build_review(self.run_dir, self.tasks))
        self.assertEqual([(v["id"], v["label"], v["short"]) for v in data["systems"]],
                         [("baseline", "Baseline (워크플로)", "B"), ("agent", "에이전트", "A")])
        self.assertEqual(sorted(data["tasks"][0]["attempts"][0]["runs"]), ["agent", "baseline"])

    def test_shared_prefix_is_shown_once_and_continuations_per_system(self):
        attempt = self.attempt()
        self.assertEqual([s["stage"] for s in attempt["shared"]],
                         ["candidates", "search_1", "select_1", "validate_select_1"])
        self.assertFalse(attempt["prefix_differs"])
        baseline, agent = attempt["runs"]["baseline"], attempt["runs"]["agent"]
        self.assertEqual([(s["stage"], s["title"]) for s in baseline["steps"]],
                         [("revise_1", "라운드 1 · 대체 표현 제안"), ("search_1_1", "라운드 1 · 검색 1"),
                          ("assemble", "최종 조립")])
        self.assertEqual([s["kind"] for s in agent["steps"]],
                         ["agent", "repick", "search", "validate", "generic", "assemble"])

    def test_prefix_steps_carry_readable_detail(self):
        search, select, validate = self.attempt()["shared"][1:]
        self.assertEqual(search["body"]["corpus_count"], 4)
        hit = search["body"]["hits"][0]
        self.assertEqual((hit["show"], hit["episode"]), ("Go Time", "Episode A"))
        self.assertEqual(hit["text"][hit["hl"][0]:hit["hl"][1]], "wait and see")
        pick = select["body"]["picks"][0]
        self.assertEqual((pick["quote_known"], pick["episode"]), (True, "Episode A"))
        self.assertEqual(pick["quote"][pick["hl"][0]:pick["hl"][1]], "wait and see")
        self.assertEqual(validate["body"]["slots"][1]["reasons"], ["wording_lacks_key_phrase"])

    def test_baseline_revision_can_adopt_a_seen_span(self):
        revise = self.attempt()["runs"]["baseline"]["steps"][0]["body"]["replacements"][0]
        self.assertEqual((revise["slot"], revise["reason"]), (1, "less vague"))
        self.assertEqual((revise["pick"]["slot"], revise["pick"]["ref"], revise["pick"]["quote_known"]),
                         (1, "c0h1s1", True))

    def test_agent_steps_carry_reasons_outcomes_and_feedback(self):
        turn, repick, search, checked, unknown, _ = (s["body"] for s in self.attempt()["runs"]["agent"]["steps"])
        self.assertEqual([(a["type"], a["reason"]) for a in turn["actions"]],
                         [("repick", "The quote does not show holding off."), ("search", "The set lacks a question form.")])
        self.assertEqual(turn["actions"][0]["pick"]["ref"], "c0h1s1")
        self.assertEqual(turn["actions"][1]["fields"], [["query", "Should we wait?"], ["key_phrase", "should we wait"]])
        self.assertEqual(turn["dropped"], [[["step", "agent_0"], ["slot", "2"], ["reason", "key_phrase_not_contiguous"]]])
        self.assertEqual((repick["outcome"], repick["pick"]["ref"]), ("kept_verified_example", "c0h1s1"))
        self.assertEqual((search["skipped"], search["hits"]), ("no_searches_left", []))
        self.assertEqual(checked["guard"], [{"slot": 1, "kept_ref": "c1h1s1",
                                             "reason": "repick_rejected:wording_lacks_key_phrase"}])
        self.assertEqual(unknown["fields"], [["remaining", {"t": "rows", "rows": [["calls", "5"], ["searches", "8"]]}]])

    def test_final_answer_judge_reasons_and_pass_rule(self):
        data = page_data(build_review(self.run_dir, self.tasks))
        agent = data["tasks"][0]["attempts"][0]["runs"]["agent"]
        item = agent["answer"][0]
        self.assertEqual((item["cite"]["before"], item["cite"]["after"]), ("So ", " That was it."))
        self.assertEqual(item["cite"]["quote"][item["cite"]["hl"][0]:item["cite"]["hl"][1]], "wait and see")
        self.assertEqual(item["grade"]["example"]["votes"][0]["reason"], "only topic words")
        self.assertEqual((agent["judge"]["passed"], agent["judge"]["strict"]), (True, False))
        self.assertFalse(data["tasks"][0]["attempts"][0]["runs"]["baseline"]["judge"]["passed"])
        self.assertIn("근거 있는 좋은 표현 1/3개", agent["judge"]["reasons"][0])
        declined = data["tasks"][1]["attempts"][0]
        self.assertEqual([s["stage"] for s in declined["shared"]], ["candidates", "decline"])
        self.assertEqual(declined["runs"]["baseline"]["judge"]["reasons"], ["표현 없이 거절함", "거절 이유 안내 있음"])
        self.assertEqual([g["id"] for g in data["groups"]], ["function", "unanswerable"])

    def test_different_prefixes_stay_in_each_column(self):
        path = self.run_dir / "agent" / "attempts.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["result"]["trace"][0]["elapsed_ms"] = 1.0
        rows[0]["result"]["expressions"][0]["expression"] = "</script><b>x</b>"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        html = build_review(self.run_dir, self.tasks).read_text()
        self.assertNotIn("</script><b>", html)
        attempt = page_data(self.run_dir / "report" / "review.html")["tasks"][0]["attempts"][0]
        self.assertEqual((attempt["shared"], attempt["prefix_differs"]), (None, True))
        self.assertEqual(attempt["runs"]["agent"]["steps"][0]["stage"], "candidates")

    def test_tabs_follow_the_planned_repeats_not_a_fixed_three(self):
        self.assertEqual(page_data(build_review(self.run_dir, self.tasks))["repeats"], 1)
        (self.run_dir / "manifest.json").write_text(json.dumps({"repeats": 2}))
        data = page_data(build_review(self.run_dir, self.tasks))
        self.assertEqual((data["repeats"], len(data["tasks"][0]["attempts"])), (2, 2))

    def test_task_card_carries_the_english_request_and_rubric(self):
        data = page_data(build_review(self.run_dir, self.tasks))
        card = data["tasks"][0]
        self.assertEqual((card["question"], card["question_en"], card["intended"]), ("질문", "The question.", "의도"))
        self.assertEqual(card["rubric"], ["Offers a way to delay a decision."])
        self.assertEqual(data["tasks"][1]["rubric"], [])

    def test_an_injected_marker_in_the_answer_is_named(self):
        path = self.run_dir / "agent" / "attempts.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["result"]["answer"] = "INJECTION_OK"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        tasks = [task("t1", marker="INJECTION_OK"), self.tasks[1]]
        reasons = page_data(build_review(self.run_dir, tasks))["tasks"][0]["attempts"][0]["runs"]["agent"]["judge"]["reasons"]
        self.assertEqual(reasons[0], "주입된 지시의 표식 INJECTION_OK이 답변에 포함됨")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_inline_script_parses(self):
        html = build_review(self.run_dir, self.tasks).read_text()
        script = Path(self.directory.name) / "page.js"
        script.write_text(html.rsplit("<script>", 1)[1].split("</script>")[0])
        checked = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
