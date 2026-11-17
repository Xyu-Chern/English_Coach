"""Results report: pass@3/pass^3, flips, nearest-rank p95, trace metrics, breakdowns, the paired bootstrap and its
decision lines, prefix states, failure candidates, missing grades, the run header and the per-system logs."""

import json
from pathlib import Path
import tempfile
import unittest

from evaluation import report as mr


def task(task_id, category="function/context", expect="answer", marker=None):
    return {"id": task_id, "category": category, "expect": expect, "marker": marker}


def grade(task_id, system, attempt, passed, category="function/context", expect="answer", **extra):
    row = {"key": f"{task_id}/{system}/{attempt}", "task_id": task_id, "variant": system,
           "attempt": attempt, "category": category, "expect": expect, "passed": passed,
           "strict_passed": passed, "grounded_good": 3 if passed else 1, "good_expressions": 3,
           "with_example": 3, "set_constraint_ok": True, "tokens": 1000, "model_calls": 2, "searches": 6,
           "workflow_cost": 0.01, "latency_ms": 2000.0, "items": [],
           "set": {"duplicates": [], "set_constraint": "not_applicable", "first_fits_context": "pass"},
           "status": "ok", "error_code": None}
    row.update(extra)
    return row


def attempt(task_id, system, number, trace=None, **result):
    return {"task_id": task_id, "variant": system, "attempt": number,
            "result": {"status": "ok", "expressions": [], "answer": "", "source_availability_note": None,
                       "trace": trace or [], **result}}


def from_patterns(system, patterns, categories=None):
    """Grades from marks like 'PFP'; '·' leaves that attempt ungraded."""
    rows = []
    for task_id, marks in patterns.items():
        for number, mark in enumerate(marks, 1):
            if mark != "·":
                rows.append(grade(task_id, system, number, mark == "P",
                                  category=(categories or {}).get(task_id, "function/context")))
    return rows


def span(stage, ms=0, shared=False, **details):
    return {"stage": stage, "status": "ok", "elapsed_ms": ms, "details": {**details, **({"shared": True} if shared else {})}}


def prefix(verified):
    return [span("candidates", shared=True), span("search_1", shared=True), span("select_1", shared=True),
            span("validate_select_1", shared=True, verified=verified, slots=[])]


class PassKTests(unittest.TestCase):
    patterns = {"a": "PPP", "b": "PFP", "c": "FFF", "d": "PP·", "e": "FP·"}

    def test_pass_at_3_and_pass_hat_3_use_tasks_with_all_three_graded(self):
        result = mr.pass_k(from_patterns("agent", self.patterns), "agent")
        self.assertEqual((result["tasks"], result["any_pass"], result["all_pass"]), (3, 2, 1))
        self.assertAlmostEqual(result["pass_at_k"], 2 / 3)
        self.assertAlmostEqual(result["pass_hat_k"], 1 / 3)

    def test_no_grades_gives_no_rate(self):
        self.assertEqual(mr.pass_k([], "agent"), {"tasks": 0, "any_pass": 0, "all_pass": 0,
                                                  "pass_at_k": None, "pass_hat_k": None})

    def test_flip_list_keeps_task_order_and_pattern(self):
        grades = from_patterns("agent", self.patterns) + from_patterns("baseline", {"a": "FPF"})
        order = {name: i for i, name in enumerate("edcba")}
        flips = mr.flips(grades, "agent", order)
        self.assertEqual([(f["task_id"], f["pattern"]) for f in flips], [("e", "F P ·"), ("b", "P F P")])
        self.assertEqual([f["pattern"] for f in mr.flips(grades, "baseline", order)], ["F P F"])


class StatisticsTests(unittest.TestCase):
    def test_p95_is_nearest_rank(self):
        self.assertEqual(mr.nearest_rank(range(1, 21), 0.95), 19)    # ceil(19.0) = 19th
        self.assertEqual(mr.nearest_rank(range(1, 11), 0.95), 10)    # ceil(9.5) = 10th
        self.assertEqual(mr.nearest_rank(range(150, 0, -1), 0.95), 143)  # ceil(142.5), order-independent
        self.assertEqual(mr.nearest_rank([4.2], 0.95), 4.2)
        self.assertIsNone(mr.nearest_rank([], 0.95))

    def test_system_metrics(self):
        grades = [grade(f"t{i}", "agent", 1, i != 1, latency_ms=1000.0 * i,
                        grounded_good=0 if i == 1 else 3) for i in range(1, 21)]
        grades.append(grade("u", "agent", 1, True, category="unanswerable/source_tv", expect="decline",
                            grounded_good=0, latency_ms=None))
        metrics = mr.system_metrics(grades)
        self.assertEqual(metrics["latency_p95_s"], 19.0)
        self.assertAlmostEqual(metrics["latency_mean_s"], 10.5)
        self.assertEqual(metrics["turns_mean"], 2)
        self.assertEqual(metrics["accuracy"], {"passed": 20, "n": 21, "rate": 20 / 21})
        self.assertEqual(metrics["empty_answer"], {"passed": 1, "n": 20, "rate": 0.05})  # decline tasks left out
        self.assertIsNone(metrics["rounds_mean"])  # no attempt rows, no trace


class TraceTests(unittest.TestCase):
    """Rounds and the after-prefix split come from the trace: shared steps are the prefix, the rest the system's own."""

    def test_rounds_searches_wasted_searches_and_the_prefix_split(self):
        verified = [{"status": "verified", "ref": "c0h1s1"}, {"status": "verified", "ref": "a1k1h2s1"},
                    {"status": "no_example", "ref": None}]
        trace = [span("candidates", 900, True), span("search_1", 100, True, ref_prefix="c0"),
                 span("select_1", 800, True), span("validate_select_1", 0, True, slots=[]),
                 span("agent_1", 1500), span("search_1_1", 200, ref_prefix="a1k1"),
                 span("search_1_2", 0, skipped="finish_requested"), span("validate_agent_1", 0, slots=[]),
                 span("agent_2", 1000), span("search_2_1", 300, ref_prefix="a2k1"),
                 span("validate_agent_2", 0, slots=verified), span("assemble", 0)]
        usage = {"input_tokens": 100, "output_tokens": 10}
        events = [{"shared": True, "usage": usage}] * 2 + [{"usage": usage}, {"usage": None}]
        row = {"result": {"trace": trace, "model_events": events},
               "cost": {"workflow": {"usd": 0.03}, "shared_prefix": {"usd": 0.01}}}
        metrics = mr.trace_metrics(row)
        self.assertEqual({k: metrics[k] for k in ("rounds", "continuation_calls", "continuation_searches",
                                                  "wasted_searches", "prefix_tokens", "continuation_tokens",
                                                  "prefix_ms", "continuation_ms")},
                         {"rounds": 2, "continuation_calls": 2, "continuation_searches": 2, "wasted_searches": 1,
                          "prefix_tokens": 220, "continuation_tokens": 110, "prefix_ms": 1800, "continuation_ms": 3000})
        self.assertAlmostEqual(metrics["continuation_usd"], 0.02)
        metrics = mr.system_metrics([grade("t", "agent", 1, True)], {"t/agent/1": row})
        self.assertEqual((metrics["traced"], metrics["rounds_mean"], metrics["after_prefix"]["wasted_searches_mean"]),
                         (1, 2, 1))

    def test_baseline_revise_rounds_count(self):
        row = attempt("t", "baseline", 1, prefix(1) + [span("revise_1"), span("search_1_1"), span("select_2"),
                                                       span("validate_select_2", slots=[]), span("revise_2"),
                                                       span("assemble")])
        self.assertEqual(mr.trace_metrics(row)["rounds"], 2)

    def test_prefix_states_come_from_the_shared_first_verification(self):
        attempts = {"t/baseline/1": attempt("t", "baseline", 1, prefix(3)),
                    "t/agent/1": attempt("t", "agent", 1, prefix(3)),
                    "t/agent/2": attempt("t", "agent", 2, prefix(1)),
                    "u/agent/1": attempt("u", "agent", 1, [span("candidates", shared=True), span("decline")])}
        states = mr.prefix_states(attempts)
        self.assertEqual(states, {"t/1": "review", "t/2": "recovery"})
        grades = (from_patterns("baseline", {"t": "FP"}) + from_patterns("agent", {"t": "PP"}))
        sub = mr.subgroups(grades, states, ("baseline", "agent"))
        self.assertEqual((sub["review"]["units"], sub["recovery"]["units"]), (1, 1))
        self.assertEqual(sub["review"]["baseline"]["pass"]["passed"], 0)
        self.assertEqual(sub["recovery"]["agent"]["pass"], {"passed": 1, "n": 1, "rate": 1.0})


class BreakdownTests(unittest.TestCase):
    tasks = [task("f"), task("e1", "edge/injection"), task("e2", "edge/one_word"),
             task("u", "unanswerable/source_tv", expect="decline")]
    grades = (from_patterns("agent", {"f": "PPF", "e1": "PPP", "e2": "FFF", "u": "PPP"},
                            {"e1": "edge/injection", "e2": "edge/one_word", "u": "unanswerable/source_tv"})
              + from_patterns("baseline", {"f": "FFF", "e1": "FFF", "e2": "FFF", "u": "PFP"},
                              {"e1": "edge/injection", "e2": "edge/one_word", "u": "unanswerable/source_tv"}))

    def test_edge_and_unanswerable_conditions_collapse_into_one_category_each(self):
        rows = {r["name"]: r for r in mr.breakdown(self.grades, self.tasks, lambda t: mr.group(t["category"]))}
        self.assertEqual(list(rows), ["function/context", "edge", "unanswerable"])
        self.assertEqual(rows["edge"]["tasks"], 2)
        self.assertEqual((rows["edge"]["agent"]["pass"]["passed"], rows["edge"]["agent"]["pass"]["n"]), (3, 6))
        self.assertEqual(rows["function/context"]["agent"]["pass"]["passed"], 2)
        self.assertEqual(rows["unanswerable"]["baseline"]["pass"]["passed"], 2)

    def test_expect_groups_count_edge_tasks_as_answerable_too(self):
        groups = mr.expect_groups(self.grades, self.tasks)
        self.assertEqual([(g["name"], g["tasks"]) for g in groups], [("answer", 3), ("edge", 2), ("unanswerable", 1)])
        self.assertEqual(groups[0]["agent"]["pass"], {"passed": 5, "n": 9, "rate": 5 / 9})
        only_answer = mr.expect_groups(from_patterns("agent", {"f": "PPP"}), [task("f")])
        self.assertEqual([g["name"] for g in only_answer], ["answer"])  # empty groups are left out


class BootstrapTests(unittest.TestCase):
    def grades(self):
        agent = {f"t{i}": ("PPP" if i % 3 else "PFF") for i in range(10)}
        baseline = {f"t{i}": ("PFF" if i % 2 else "FFF") for i in range(10)}
        unanswerable = [grade("u", s, a, s == "agent", category="unanswerable/source_tv", expect="decline")
                        for s in ("agent", "baseline") for a in (1, 2, 3)]
        return from_patterns("agent", agent) + from_patterns("baseline", baseline) + unanswerable

    def test_ci_shape_and_determinism(self):
        answer_ids = {f"t{i}" for i in range(10)}
        result = mr.paired_bootstrap(self.grades(), "agent", "baseline", answer_ids)
        self.assertEqual(result["tasks"], 10)
        low, high = result["ci95"]
        self.assertLessEqual(low, result["difference"])
        self.assertLessEqual(result["difference"], high)
        self.assertLess(low, high)
        self.assertTrue(-1 <= low and high <= 1)
        self.assertEqual((result["seed"], result["resamples"]), (7, 4000))
        self.assertEqual(result, mr.paired_bootstrap(self.grades(), "agent", "baseline", answer_ids))

    def test_attempts_are_averaged_within_each_task_first(self):
        grades = from_patterns("agent", {"t": "PPF"}) + from_patterns("baseline", {"t": "FFF"})
        result = mr.paired_bootstrap(grades, "agent", "baseline", {"t"})
        self.assertAlmostEqual(result["difference"], 2 / 3)
        self.assertEqual(result["ci95"], [result["difference"]] * 2)

    def test_units_with_an_infrastructure_failure_are_left_out_of_both_systems(self):
        grades = from_patterns("agent", {"t": "PPP", "s": "PPP"}) + from_patterns("baseline", {"t": "PPP", "s": "FFF"})
        outage = next(g for g in grades if (g["variant"], g["task_id"], g["attempt"]) == ("agent", "t", 2))
        outage.update(passed=False, strict_passed=False, status="error", error_code="model_unavailable")
        result = mr.comparison(grades, "agent", "baseline", {"t", "s"})
        self.assertEqual(result["excluded_units"], ["t/2"])
        self.assertAlmostEqual(result["difference"], 0.5)  # t: 0 (two units left), s: +1
        self.assertAlmostEqual(result["all_units"]["difference"], (-1 / 3 + 1) / 2)
        payload = mr.build([task("t"), task("s")], [attempt(g["task_id"], g["variant"], g["attempt"]) for g in grades],
                           grades)
        self.assertEqual(payload["coverage"]["agent"]["infrastructure_failures"], 1)
        self.assertEqual(payload["coverage"]["agent"]["error_codes"], {"model_unavailable": 1})
        markdown = mr.render(payload)
        self.assertIn("| Pass | 2 | +50.0 |", markdown)
        self.assertIn("left out of both: `t/2`", markdown)

    def test_no_shared_tasks(self):
        result = mr.paired_bootstrap([], "agent", "baseline", {"t"})
        self.assertEqual((result["tasks"], result["difference"], result["ci95"]), (0, None, None))

    def test_decision_lines_are_each_stated_on_their_own(self):
        answer_ids = {f"t{i}" for i in range(10)}
        grades = self.grades()
        metrics = {s: mr.system_metrics([g for g in grades if g["variant"] == s]) for s in mr.SYSTEMS}
        result = mr.agent_vs_baseline(grades, answer_ids, metrics)
        self.assertEqual(result["checks"], {"pass_non_inferiority": result["pass"]["ci95"][0] > -0.05,
                                            "strict_superiority": result["strict"]["ci95"][0] > 0,
                                            "empty_answers": result["empty_difference"] <= 0.03})
        self.assertEqual(result["checks"]["pass_non_inferiority"], True)
        self.assertAlmostEqual(result["empty_difference"], 0.0)  # grounded_good is 1 or 3 here: no empty answers
        empty = mr.agent_vs_baseline([], set(), {s: mr.system_metrics([]) for s in mr.SYSTEMS})
        self.assertEqual(empty["checks"], {"pass_non_inferiority": None, "strict_superiority": None,
                                           "empty_answers": None})


class FailureTests(unittest.TestCase):
    def test_answer_failure_names_failing_items(self):
        items = [{"fits": "pass", "natural": "pass", "example": {"shows_use": "pass", "explanation_ok": "pass"},
                  "code_ok": True, "grounded_good": True},
                 {"fits": "fail", "natural": "pass", "example": None, "code_ok": None, "grounded_good": False},
                 {"fits": "pass", "natural": "pass", "example": {"shows_use": "fail", "explanation_ok": "pass"},
                  "code_ok": False, "grounded_good": False}]
        row = grade("t", "agent", 1, False, grounded_good=1, items=items, set_constraint_ok=False,
                    set={"duplicates": [2], "set_constraint": "fail", "first_fits_context": "pass"})
        reason = mr.failure_reason(row)
        self.assertIn("set constraint failed", reason)
        self.assertIn("grounded-good 1/3", reason)
        self.assertIn("#2 fits=fail, no example", reason)
        self.assertIn("#3 duplicate, quote not verified, shows_use=fail", reason)
        self.assertNotIn("#1", reason)

    def test_error_marker_and_decline_reasons(self):
        self.assertEqual(mr.failure_reason(grade("t", "agent", 1, False, status="error",
                                                 error_code="invalid_model_output")),
                         "status error: invalid_model_output")
        marked = attempt("t", "agent", 1, answer="... INJECTION_OK ...")
        self.assertIn("injected marker INJECTION_OK",
                      mr.failure_reason(grade("t", "agent", 1, False, grounded_good=3), marked,
                                        task("t", "edge/injection", marker="INJECTION_OK")))
        answered = attempt("u", "agent", 1, expressions=[{"expression": "x"}])
        reason = mr.failure_reason(grade("u", "agent", 1, False, expect="decline"), answered)
        self.assertEqual(reason, "1 expressions returned instead of declining; no availability note")

    def test_failing_step_points_into_the_trace(self):
        rounds = attempt("t", "agent", 1, prefix(1) + [span("agent_1"), span("validate_agent_1", verified=2, slots=[]),
                                                       span("agent_2"), span("validate_agent_2", verified=2, slots=[]),
                                                       span("assemble")])
        self.assertEqual(mr.failing_step(rounds), "verified slots: first stage 1/3 → final 2/3 after 2 rounds")
        broken = attempt("t", "agent", 2, [span("candidates", shared=True),
                                           {"stage": "validate_action", "status": "error",
                                            "details": {"error_code": "invalid_model_output", "shared": True}}])
        self.assertEqual(mr.failing_step(broken), "validate_action: invalid_model_output")
        declined = attempt("t", "agent", 3, [span("candidates", shared=True),
                                             span("decline", shared=True, request_status="out_of_scope")])
        self.assertEqual(mr.failing_step(declined), "candidates: request judged out_of_scope, declined")
        self.assertEqual(mr.failing_step(None), "no trace (attempt row unavailable)")

    def test_candidates_cover_both_systems_in_order(self):
        grades = from_patterns("agent", {"a": "PFP"}) + from_patterns("baseline", {"a": "FFP", "b": "PPF"})
        rows = mr.candidate_failures(grades, {}, {}, {"a": 0, "b": 1})
        self.assertEqual([(r["system"], r["task_id"], r["attempt"]) for r in rows],
                         [("baseline", "a", 1), ("baseline", "a", 2), ("baseline", "b", 3), ("agent", "a", 2)])


class ReadTests(unittest.TestCase):
    def test_half_written_last_line_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.jsonl"
            path.write_text('{"a": 1}\n{"a": 2}\n{"a": 3, "res')
            self.assertEqual(mr.read_jsonl(path), [{"a": 1}, {"a": 2}])
            self.assertEqual(mr.read_jsonl(Path(directory) / "missing.jsonl"), [])
        self.assertEqual(mr.attempt_key({"task_id": "t", "variant": "agent", "attempt": 2}), "t/agent/2")


class ReportTests(unittest.TestCase):
    tasks = [task("a"), task("e", "edge/injection", marker="INJECTION_OK"),
             task("u", "unanswerable/source_tv", expect="decline")]

    def grades(self):
        return [grade(t["id"], s, n, n != 2, category=t["category"], expect=t["expect"])
                for t in self.tasks for s in mr.SYSTEMS for n in (1, 2, 3)]

    def test_missing_grades_are_reported_not_guessed(self):
        attempts = [attempt(t["id"], "agent", n) for t in self.tasks for n in (1, 2, 3)]
        grades = [grade("a", "agent", 1, True), grade("zz", "agent", 1, True), grade("a", "other", 1, True)]
        payload = mr.build(self.tasks, attempts, grades)
        self.assertEqual(list(payload["coverage"]), ["baseline", "agent"])  # other system names are ignored
        coverage = payload["coverage"]["agent"]
        self.assertEqual((coverage["expected"], coverage["recorded"], coverage["graded"]), (9, 9, 1))
        self.assertEqual(len(coverage["ungraded"]), 8)
        self.assertIn("u/agent/3", coverage["ungraded"])
        self.assertEqual(payload["coverage"]["baseline"]["recorded"], 0)
        markdown = mr.render(payload)
        self.assertIn("| Agent | 9 | 9 | 1 | 8 | 0 | none |", markdown)
        self.assertIn("`a/agent/2`", markdown)

    def test_empty_inputs_render(self):
        markdown = mr.render(mr.build(self.tasks, [], []))
        self.assertIn("| Accuracy (pass rate) | n/a | n/a |", markdown)
        self.assertIn("- Pass non-inferiority (CI lower bound > -5.0 pp): n/a", markdown)
        self.assertIn("TODO (human)", markdown)

    def test_layout_numbers_and_files(self):
        payload = mr.build(self.tasks, [], self.grades())
        self.assertEqual(payload["task_counts"], {"total": 3, "answer": 2})
        self.assertEqual([g["name"] for g in payload["groups"]], ["answer", "edge", "unanswerable"])
        self.assertEqual([r["name"] for r in payload["categories"]], ["function/context", "edge", "unanswerable"])
        self.assertEqual(payload["comparison"]["pass"]["tasks"], 2)
        self.assertEqual([f["pattern"] for f in payload["flips"]["agent"]], ["P F P"] * 3)
        markdown = mr.render(payload)
        for text in ("| Metric | Baseline | Agent |",
                     "| Accuracy (pass rate) | 66.7% (6/9) | 66.7% (6/9) |",
                     "| pass@3 (any run passes) | 100.0% (3/3) | 100.0% (3/3) |",
                     "| pass^3 (all runs pass) | 0.0% (0/3) | 0.0% (0/3) |",
                     "| Turns: model calls per attempt (first stage included) | 2.00 | 2.00 |",
                     "| Latency p95 (s) | 2.0 | 2.0 |",
                     "| Tokens per attempt (mean) | 1,000 | 1,000 |",
                     "| Cost per attempt (USD, mean) | 0.0100 | 0.0100 |",
                     "## Agent − Baseline (2 answerable tasks, paired)",
                     "| Pass | 2 | +0.0 | [+0.0, +0.0] |",
                     "## By first-stage state", "| System | Task | Category | Runs 1-3 |", "| Agent | a | function/context | P F P |",
                     "## Failure analysis", "| Agent | a | 2 | function/context |", "## Method"):
            self.assertIn(text, markdown)
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run1"
            (run_dir / "grades").mkdir(parents=True)
            (run_dir / "agent").mkdir()
            (run_dir / "agent" / "attempts.jsonl").write_text("")
            (run_dir / "grades" / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in self.grades()))
            written = mr.write_report(self.tasks, run_dir)
            self.assertEqual(mr.report_dir(run_dir), run_dir / "report")
            self.assertEqual(written["coverage"]["agent"]["graded"], 0)  # grades without a recorded attempt
            self.assertEqual(json.loads((run_dir / "report" / "results.json").read_text())["metrics"],
                             written["metrics"])
            self.assertTrue((run_dir / "report" / "results.md").read_text().startswith("# Results: Baseline vs Agent"))

    def test_header_comes_from_the_manifests(self):
        run = {"task_file": "evaluation/data/tasks.jsonl", "tasks_sha256": "d994d5b9195796f4" * 4,
               "repeats": 3, "environment": {"model": "claude-haiku-5-5", "effort": "medium",
                                             "snapshot_id": "corpus-x", "corpus_sha256": "c" * 64},
               "git": {"commit": "173cbedfa449" + "0" * 28, "diff_sha256": "d" * 64},
               "derived_from": {"run": "evaluation run of 2026-11-17", "manifest_sha256": "3a4b" * 16,
                                "note": "Copied rows."}}
        judge = {"protocol": "multi-expression-grader-v2", "votes": 3, "model": "gpt-5.4-mini-2026-03-17"}
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "submission"
            (run_dir / "grades").mkdir(parents=True)
            (run_dir / "manifest.json").write_text(json.dumps(run))
            (run_dir / "grades" / "manifest.json").write_text(json.dumps(judge))
            payload = mr.write_report(self.tasks, run_dir)
            markdown = (run_dir / "report" / "results.md").read_text()
        self.assertEqual(payload["info"]["derived_from"], {"run": "evaluation run of 2026-11-17", "note": "Copied rows."})
        for text in ("| Run | `submission` |", "| Task file | `evaluation/data/tasks.jsonl` (3 tasks, sha256 "
                     "`d994d5b91957`) |", "| Generation model | claude-haiku-5-5 (effort medium) |",
                     "| Judge | gpt-5.4-mini-2026-03-17, protocol `multi-expression-grader-v2`, 3 votes per unit, "
                     "majority |", "| Corpus snapshot | corpus-x (sha256 `cccccccccccc`) |",
                     "| Code | commit `173cbedfa449`, working-tree diff sha256 `dddddddddddd` |",
                     "| Derived from | evaluation run of 2026-11-17. Copied rows. |"):
            self.assertIn(text, markdown)
        self.assertNotIn("3a4b3a4b", markdown)


class LogTests(unittest.TestCase):
    def test_one_compact_line_per_attempt_in_task_order(self):
        tasks = [task("a"), task("u", "unanswerable/source_tv", expect="decline")]
        citation = {"quote": "We don't know that yet.", "episode_title": "Restic"}
        trace = [{"stage": "candidates", "status": "ok", "details": {"shared": True, "output": {
                      "request_status": "answerable", "kind": "specific",
                      "candidates": [{"key_phrase": "don't know"}, {"key_phrase": "a theory"}]}}},
                 {"stage": "search_1", "status": "ok", "details": {"shared": True, "query": "We don't know yet.",
                                                                   "key_phrase": "don't know", "hits": [{}, {}],
                                                                   "search_mode": "literal"}},
                 {"stage": "validate_select_1", "status": "ok", "details": {"verified": 1, "slots": [{}, {}, {}]}},
                 {"stage": "agent_1", "status": "ok", "details": {"output": {
                      "assessment": "Slot 1 has no example.", "finish": False,
                      "actions": [{"type": "repick", "slot": 1}, {"type": "search", "key_phrase": "a theory"}]}}},
                 {"stage": "repick_1_1", "status": "ok", "details": {"slot": 1, "ref": "c0h1s1", "outcome": "rejected",
                                                                     "rejection_reasons": ["wording not copied"],
                                                                     "expression": "Just a theory."}},
                 {"stage": "search_1_2", "status": "error", "details": {"error_code": "search_unavailable"}}]
        rows = [attempt("u", "agent", 1), attempt("a", "agent", 2), attempt("a", "baseline", 1),
                attempt("a", "agent", 1, trace=trace, expressions=[
                    {"expression": "We don't know that yet.", "citation": citation},
                    {"expression": "Just a theory.", "citation": None}], model_rounds=3,
                    tool_calls=[{}, {}], usage={"input_tokens": 900, "output_tokens": 100}, elapsed_ms=1234.5)]
        rows[3]["cost"] = {"workflow": {"usd": 0.0123456789}}
        grades = [grade("a", "agent", 1, True, items=[{"code_ok": True}, {"code_ok": None}])]
        with tempfile.TemporaryDirectory() as directory:
            mr.write_logs(tasks, rows, grades, Path(directory))
            agent = mr.read_jsonl(Path(directory) / "logs" / "agent.jsonl")
            self.assertEqual(len(mr.read_jsonl(Path(directory) / "logs" / "baseline.jsonl")), 1)
        self.assertEqual([(line["task_id"], line["run"]) for line in agent], [("a", 1), ("a", 2), ("u", 1)])
        first = agent[0]
        self.assertEqual({k: first[k] for k in ("system", "status", "passed", "strict_passed", "model_calls", "searches",
                                                 "tokens", "latency_ms", "cost_usd")},
                         {"system": "agent", "status": "ok", "passed": True, "strict_passed": True, "model_calls": 3,
                          "searches": 2, "tokens": 1000, "latency_ms": 1234, "cost_usd": 0.012346})
        self.assertEqual(first["expressions"], [
            {"expression": "We don't know that yet.", "quote": "We don't know that yet.", "episode": "Restic",
             "verified": True},
            {"expression": "Just a theory.", "quote": None, "episode": None, "verified": False}])
        self.assertEqual([s["summary"] for s in first["steps"]], [
            "2 candidates (specific): don't know; a theory",
            'query "We don\'t know yet.", key phrase "don\'t know": 2 hits (literal)',
            "1/3 slots verified",
            'repick slot 1, search "a theory". Slot 1 has no example.',
            'slot 1 -> c0h1s1: rejected (wording not copied), "Just a theory."',
            "error: search_unavailable"])
        self.assertEqual((agent[1]["passed"], agent[1]["steps"]), (None, []))  # not graded yet


if __name__ == "__main__":
    unittest.main()
