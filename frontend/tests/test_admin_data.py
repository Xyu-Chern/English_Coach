"""The /admin data file, built from small fake evaluation runs (no model, network or database)."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from frontend import admin_data
from frontend.admin_data import AdminData, TracesFile, build, resolve_mode, write

QUESTION = "회의에서 <script>alert(1)</script> 라고 말하고 싶어요"
CANDIDATES = {"request_status": "answerable", "kind": "specific", "source_show": None, "status_note": None,
              "candidates": [{"expression": f"E{i}", "key_phrase": f"E{i}", "function": "f", "note": f"note {i}"}
                             for i in range(4)]}


def span(stage, ms, shared=False, status="ok", **details):
    if shared:
        details["shared"] = True
    return {"stage": stage, "status": status, "elapsed_ms": ms, "details": details}


def llm(stage, ms, output, shared=False, tokens=(100, 10)):
    return span(stage, ms, shared, model="fake-model", input_tokens=tokens[0], output_tokens=tokens[1], output=output)


def search(stage, ms, slot, shared=False, **extra):
    return span(stage, ms, shared, slot=slot, query=f"query {slot}", key_phrase=f"E{slot}", corpus_count=1,
                hits=[{"chunk_id": "c1", "source_key": "podcast_index:218840:1", "episode_title": "Ep", "snippet": "s"}],
                search_mode="literal", query_policy="candidate_expression", ref_prefix=f"c{slot}", **extra)


def slot(i, expression, quote=None):
    return {"slot": i, "candidate": i, "expression": expression, "key_phrase": expression,
            "status": "verified" if quote else "no_example", "ref": f"c{i}h1s1" if quote else None, "quote": quote,
            "episode_title": "Ep" if quote else None, "rejection_reasons": []}


def validate(stage, slots, shared=False):
    return span(stage, 0, shared, verified=sum(s["status"] == "verified" for s in slots), slots=slots, excluded=[],
                semantic_judgment="model_reported_not_human_verified")


def first_stage(verified):
    slots = [slot(i, f"E{i}", f"quote {i}" if i < verified else None) for i in range(3)]
    return [llm("candidates", 1000, CANDIDATES, True), search("search_1", 500, 0, True),
            search("search_2", 500, 1, True), llm("select_1", 2000, {"picks": [{"candidate": 0, "ref": "c0h1s1"}]}, True),
            validate("validate_select_1", slots, True)]


def item(expression, quote=None):
    citation = {"quote": quote, "episode_title": "Ep", "source_key": "podcast_index:218840:1"} if quote else None
    return {"expression": expression, "key_phrase": expression, "function": "f", "note": f"note {expression}",
            "citation": citation}


def row(task, system, trace, *, elapsed, status="ok", expressions=None, error_code=None, calls=3, searches=2):
    return {"task_id": task, "attempt": 1, "category": "specific/context", "variant": system,
            "recorded_at": "2026-11-20T10:00:30+00:00", "wall_elapsed_ms": elapsed, "unit_tries": 1,
            "discarded_tries": [],
            "result": {"request_id": f"{task}-{system}", "variant": system, "status": status, "answer": "",
                       "expressions": expressions, "model_rounds": calls,
                       "tool_calls": [{"name": "search_corpus"}] * searches, "trace": trace, "elapsed_ms": elapsed,
                       "usage": {"input_tokens": 1000, "output_tokens": 100, "embedding_tokens": 5,
                                 "cached_input_tokens": 0, "reported_chat_calls": calls, "total_chat_calls": calls},
                       "error_code": error_code, "source_availability_note": None},
            "cost": {"workflow": {"usd": 0.0012345678, "status": "list_price_estimate",
                                  "pricing_as_of": "2026-11-16 UTC", "currency": "USD"}}}


def agent_turn(turn, actions, finish=False):
    return llm(f"agent_{turn}", 3000, {"assessment": "A" * 400, "actions": actions, "finish": finish}, tokens=(200, 20))


def pre_lock_rows():
    """baseline + agent as recorded before the lock: the agent replaces a verified example and runs after 3 verified."""
    declined = [llm("candidates", 900, {**CANDIDATES, "request_status": "out_of_scope", "candidates": []}, True),
                span("decline", 0, True, request_status="out_of_scope", note="Outside what this coach does.")]
    failed = [llm("candidates", 1000, CANDIDATES, True),
              span("search_1", 700, True, status="error", slot=0, error_code="search_unavailable")]
    return {
        "baseline": [
            row("t-one", "baseline", [*first_stage(1), llm("revise_1", 1500, {"replacements": [{"replaces": 1}]}),
                                      search("search_1_1", 400, 1),
                                      llm("select_2", 1200, {"picks": [{"candidate": 1, "ref": "r1k1h1s1"}]}),
                                      validate("validate_select_2", [slot(0, "E0", "quote 0"), slot(1, "X1", "quote x1"),
                                                                     slot(2, "E2")]),
                                      span("assemble", 0, expressions=3, with_example=2)],
                elapsed=9000, expressions=[item("E0", "quote 0"), item("X1", "quote x1"), item("E2")]),
            row("t-three", "baseline", [*first_stage(3), span("assemble", 0, expressions=3, with_example=3)],
                elapsed=4100, expressions=[item(f"E{i}", f"quote {i}") for i in range(3)]),
            row("t-decline", "baseline", [*declined, span("assemble", 0, expressions=0, with_example=0)],
                elapsed=950, expressions=[]),
            row("t-error", "baseline", failed, elapsed=1800, status="error", error_code="search_unavailable"),
        ],
        "agent": [
            row("t-one", "agent", [*first_stage(1), agent_turn(1, [{"type": "replace", "slot": 0}]),
                                   span("replace_1_1", 0, slot=0, ref="c3h1s1", outcome="verified", expression="Y0",
                                        previous_expression="E0", rejection_reasons=[], reason="better fit"),
                                   validate("validate_agent_1", [slot(0, "Y0", "quote y0"), slot(1, "X1", "quote x1"),
                                                                 slot(2, "E2")]),
                                   span("assemble", 0, expressions=3, with_example=2)],
                elapsed=8000, expressions=[item("Y0", "quote y0"), item("X1", "quote x1"), item("E2")]),
            row("t-three", "agent", [*first_stage(3), agent_turn(1, [], finish=True),
                                     validate("validate_agent_1", [slot(i, f"E{i}", f"quote {i}") for i in range(3)]),
                                     span("assemble", 0, expressions=3, with_example=3)],
                elapsed=7100, expressions=[item(f"E{i}", f"quote {i}") for i in range(3)]),
            row("t-decline", "agent", [*declined, span("assemble", 0, expressions=0, with_example=0)],
                elapsed=960, expressions=[]),
            row("t-error", "agent", [*first_stage(2), span("agent_1", 2500, status="error", error_code="model_unavailable")],
                elapsed=6600, status="error", error_code="model_unavailable"),
        ],
    }


def locked_rows():
    """A run of the locked agent: an action on a locked slot is a noop, 3 verified skips the continuation."""
    rows = pre_lock_rows()
    return {
        "baseline": rows["baseline"][:2],
        "agent_locked": [
            row("t-one", "agent_locked", [*first_stage(1),
                                          agent_turn(1, [{"type": "repick", "slot": 0}, {"type": "search", "slot": 1}]),
                                          span("repick_1_1", 0, noop="locked", slot=0, reason="try another"),
                                          search("search_1_2", 400, 1, reason="fill slot 1"),
                                          validate("validate_agent_1", [slot(0, "E0", "quote 0"),
                                                                        slot(1, "Z1", "quote z1"), slot(2, "E2")],
                                                   ),
                                          span("assemble", 0, expressions=3, with_example=2)],
                elapsed=8800, expressions=[item("E0", "quote 0"), item("Z1", "quote z1"), item("E2")]),
            row("t-three", "agent_locked", [*first_stage(3), span("continuation_skipped", 0, verified=3),
                                            span("assemble", 0, expressions=3, with_example=3)],
                elapsed=4150, expressions=[item(f"E{i}", f"quote {i}") for i in range(3)], calls=2),
        ],
    }


def write_run(root: Path, name: str, systems: dict, grades: list[dict]) -> tuple[Path, Path]:
    run = root / name
    for system, rows in systems.items():
        (run / system).mkdir(parents=True)
        (run / system / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (run / "grades").mkdir()
    (run / "grades" / "grades.jsonl").write_text("".join(json.dumps(g) + "\n" for g in grades), encoding="utf-8")
    (run / "grades" / "manifest.json").write_text(json.dumps({"model": "fake-judge", "protocol": "p", "votes": 3}))
    (run / "unit-starts.jsonl").write_text(json.dumps({"task_id": "t-one", "attempt": 1,
                                                       "started_at": "2026-11-20T10:00:00+00:00"}) + "\n")
    (run / "manifest.json").write_text(json.dumps({
        "environment": {"model": "fake-model", "effort": "medium", "embedding_model": "fake-embed",
                        "embedding_dimensions": 8, "snapshot_id": "snap-1"},
        "systems": list(systems), "repeats": 1, "tasks_sha256": "not-the-task-file", "git": {"commit": "abc"}}))
    tasks = root / "tasks.jsonl"
    if not tasks.exists():
        lines = [{"id": "t-one", "question": QUESTION, "language": "ko", "expect": "answer", "category": "specific/context"},
                 {"id": "t-three", "question": "세 개 다 찾는 질문", "language": "ko", "expect": "answer",
                  "category": "specific/context"},
                 {"id": "t-decline", "question": "날씨 알려줘", "language": "ko", "expect": "decline",
                  "category": "unanswerable/out_of_scope"},
                 {"id": "t-error", "question": "检索失败的问题", "language": "zh", "expect": "answer",
                  "category": "specific/plain"}]
        tasks.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in lines), encoding="utf-8")
    return run, tasks


def grade(task, system, passed, strict=False, good=2):
    return {"key": f"{task}/{system}/1", "task_id": task, "variant": system, "attempt": 1, "expect": "answer",
            "passed": passed, "strict_passed": strict, "grounded_good": good}


class AdminDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        grades = [grade("t-one", "baseline", True), grade("t-one", "agent", False, good=1),
                  grade("t-three", "baseline", True, True, 3), grade("t-decline", "baseline", True),
                  grade("t-decline", "agent", True), grade("t-error", "baseline", False, good=0),
                  grade("t-error", "agent", False, good=0)]  # t-three/agent left ungraded on purpose
        self.run, self.tasks = write_run(self.root, "pre", pre_lock_rows(), grades)
        self.data = build(self.run, self.tasks, generated_at=datetime(2026, 11, 21, tzinfo=timezone.utc))
        self.by_key = {r["key"]: r for r in self.data["requests"]}

    def locked(self):
        run, tasks = write_run(self.root, "locked", locked_rows(), [grade("t-one", "agent_locked", True)])
        return build(run, tasks)

    def test_payload_matches_the_contract(self):
        AdminData.model_validate(self.data)
        ids = [r["id"] for r in self.data["requests"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(self.data["traces"]))
        self.assertEqual(set(ids), set(self.data["answers"]))
        self.assertEqual(1, self.data["meta"]["schema_version"])
        self.assertEqual({"data": "data.json", "traces": None}, self.data["meta"]["files"])
        self.assertEqual("2026-11-21T00:00:00+00:00", self.data["meta"]["generated_at"])
        run = self.data["meta"]["run"]
        self.assertEqual(("pre", "2026-11-20", "fake-model", "fake-embed", "snap-1", 4, 1, "fake-judge", 8),
                         (run["id"], run["date"], run["model"], run["embedding_model"], run["snapshot_id"],
                          run["tasks"], run["repeats"], run["judge_model"], run["requests"]))
        self.assertEqual(["t-one/baseline/1", "t-one/agent/1", "t-three/baseline/1"], list(self.by_key)[:3])
        warnings = " ".join(self.data["meta"]["warnings"])
        self.assertIn("tasks_sha256", warnings)
        self.assertIn("심사 기록이 없는 요청 1건", warnings)

    def test_first_stage_and_continuation_numbers(self):
        b, a = self.by_key["t-one/baseline/1"], self.by_key["t-one/agent/1"]
        for r in (b, a):  # first stage = the shared spans: 1000 + 500 + 500 + 2000 + 0
            self.assertEqual((4000, 4000, 1, "ran"),
                             (r["first_stage_ms"], r["first_response_ms"], r["verified_first"], r["continuation"]))
        self.assertEqual((9000, 5000, 2, 1, 0), (b["total_ms"], b["background_ms"], b["verified_final"],
                                                 b["added_final"], b["lost_first"]))
        self.assertEqual((8000, 4000, 2, 2, 1), (a["total_ms"], a["background_ms"], a["verified_final"],
                                                 a["added_final"], a["lost_first"]))
        self.assertEqual(({"input": 1000, "output": 100, "total": 1100}, 3, 2, 0.001235),
                         (b["tokens"], b["llm_calls"], b["searches"], b["cost_usd"]))
        self.assertEqual((True, False, 2), (b["passed"], b["strict_passed"], b["grounded_good"]))
        self.assertEqual(("2026-11-20T10:00:00+00:00", "baseline", "agent"), (b["started_at"], b["mode"], a["mode"]))
        three_b, three_a = self.by_key["t-three/baseline/1"], self.by_key["t-three/agent/1"]
        self.assertEqual(("skipped", 0, 3), (three_b["continuation"], three_b["added_final"], three_b["verified_final"]))
        self.assertEqual(("ran", None), (three_a["continuation"], three_a["passed"]))

    def test_declines_and_errors(self):
        declined = self.by_key["t-decline/agent/1"]
        self.assertEqual(("declined", "none", None, None, 960, 960, 0),
                         (declined["status"], declined["continuation"], declined["verified_first"],
                          declined["verified_final"], declined["first_response_ms"], declined["total_ms"],
                          declined["background_ms"]))
        self.assertEqual("Outside what this coach does.", declined["decline_note"])
        first_error = self.by_key["t-error/baseline/1"]
        self.assertEqual(("error", "search_unavailable", "first", "none", 1800),
                         (first_error["status"], first_error["error_code"], first_error["error_phase"],
                          first_error["continuation"], first_error["first_response_ms"]))
        late_error = self.by_key["t-error/agent/1"]  # the verified examples were already sent
        self.assertEqual(("error", "continuation", "ran", 2, 4000, 2600, None),
                         (late_error["status"], late_error["error_phase"], late_error["continuation"],
                          late_error["verified_first"], late_error["first_response_ms"], late_error["background_ms"],
                          late_error["verified_final"]))
        failed_span = self.data["traces"][late_error["id"]][-1]
        self.assertEqual(("error", "continuation", "오류로 중단: model_unavailable"),
                         (failed_span["status"], failed_span["phase"], failed_span["summary"]))

    def test_lock_is_read_from_the_records(self):
        lock = self.data["meta"]["lock"]
        self.assertEqual((False, "trace", 1, 1, 0), (lock["applied"], lock["basis"], lock["ran_with_all_verified"],
                                                     lock["lost_first_requests"], lock["locked_noops"]))
        self.assertIn("잠금 전 기록", lock["note"])
        locked = self.locked()
        lock = locked["meta"]["lock"]
        self.assertEqual((True, "trace", 1, 1, 0, 0), (lock["applied"], lock["basis"], lock["locked_noops"],
                                                        lock["continuation_skipped"], lock["ran_with_all_verified"],
                                                        lock["lost_first_requests"]))
        rows = {r["key"]: r for r in locked["requests"]}
        one, three = rows["t-one/agent_locked/1"], rows["t-three/agent_locked/1"]
        self.assertEqual(("agent", "agent_locked", 1, 1, 0), (one["mode"], one["system"], one["locked_noops"],
                                                              one["added_final"], one["lost_first"]))
        self.assertEqual(("skipped", 4000, 150), (three["continuation"], three["first_response_ms"],
                                                  three["background_ms"]))
        spans = {s["stage"]: s for s in locked["traces"][one["id"]]}
        noop = spans["repick_1_1"]
        self.assertEqual(("noop", "noop", True), (noop["kind"], noop["status"], noop["locked"]))
        self.assertIn("잠금", noop["summary"])
        self.assertEqual([0], spans["agent_1"]["detail"]["locked_slots"])
        self.assertEqual([True, None, None], [s.get("locked") for s in spans["validate_agent_1"]["detail"]["slots"]])
        self.assertNotIn("locked", spans["validate_select_1"]["detail"]["slots"][0])  # the first stage is not marked
        skip = next(s for s in locked["traces"][three["id"]] if s["stage"] == "continuation_skipped")
        self.assertEqual(("noop", "noop", "후속 단계 생략"), (skip["kind"], skip["status"], skip["label"]))
        self.assertEqual({"baseline": one["id"].replace("agent_locked", "baseline"), "agent": one["id"],
                          "skipped": three["id"]}, locked["examples"])

    def test_lock_as_the_locked_agent_records_it(self):
        """AgentPipeline(locked=True) writes noop "locked" with locked=true for a repick or replace naming a
        locked slot (D1), and a fully verified first stage ends with assemble alone."""
        one = row("t-one", "agent", [*first_stage(1), agent_turn(1, [{"type": "repick", "slot": 0},
                                                                     {"type": "replace", "slot": 0}]),
                                     span("repick_1_1", 0, noop="locked", slot=0, reason="try", locked=True),
                                     span("replace_1_2", 0, noop="locked", slot=0, reason="swap", locked=True),
                                     validate("validate_agent_1", [slot(0, "E0", "quote 0"), slot(1, "E1"),
                                                                   slot(2, "E2")]),
                                     span("assemble", 0, expressions=3, with_example=1)],
                  elapsed=7100, expressions=[item("E0", "quote 0"), item("E1"), item("E2")])
        three = row("t-three", "agent", [*first_stage(3), span("assemble", 0, expressions=3, with_example=3)],
                    elapsed=4050, expressions=[item(f"E{i}", f"quote {i}") for i in range(3)], calls=2)
        run, tasks = write_run(self.root, "recorded", {"agent": [one, three]}, [])
        data = build(run, tasks)
        lock = data["meta"]["lock"]
        self.assertEqual((True, "trace", 2, 1, 0, 0), (lock["applied"], lock["basis"], lock["locked_noops"],
                                                        lock["continuation_skipped"], lock["ran_with_all_verified"],
                                                        lock["lost_first_requests"]))
        rows = {r["task_id"]: r for r in data["requests"]}
        self.assertEqual((2, "ran"), (rows["t-one"]["locked_noops"], rows["t-one"]["continuation"]))
        self.assertEqual((0, "skipped"), (rows["t-three"]["locked_noops"], rows["t-three"]["continuation"]))
        spans = {s["stage"]: s for s in data["traces"][rows["t-one"]["id"]]}
        for stage in ("repick_1_1", "replace_1_2"):
            self.assertEqual(("noop", True, "고정된 슬롯이라 건너뜀 (잠금 규칙)"),
                             (spans[stage]["kind"], spans[stage]["locked"], spans[stage]["summary"]))

    def test_traces_are_ordered_and_typed(self):
        agent = self.by_key["t-one/agent/1"]
        spans = self.data["traces"][agent["id"]]
        self.assertEqual([f"s{i:02d}" for i in range(1, len(spans) + 1)], [s["id"] for s in spans])
        self.assertEqual(["first"] * 5 + ["continuation"] * 4, [s["phase"] for s in spans])
        self.assertEqual([0, 1000, 1500, 2000, 4000, 4000, 7000, 7000, 7000], [s["start_ms"] for s in spans])
        self.assertEqual(["llm", "search", "search", "llm", "verify", "decision", "decision", "verify", "assemble"],
                         [s["kind"] for s in spans])
        self.assertEqual([None] * 5 + [1, 1, 1, None], [s["turn"] for s in spans])
        self.assertEqual({"input": 200, "output": 20, "total": 220}, spans[5]["tokens"])
        self.assertIsNone(spans[1]["tokens"])
        self.assertEqual("후보 검색 슬롯 0 'E0': 결과 1건, 코퍼스 일치 1건 (literal)", spans[1]["summary"])
        self.assertEqual("에이전트 판단: replace 1 → 계속", spans[5]["summary"])
        self.assertEqual("라운드 1 · 에이전트 판단", spans[5]["label"])
        self.assertEqual(1, spans[1]["detail"]["hits"])
        rich = agent["id"] == self.data["examples"]["agent"]
        self.assertTrue(rich)  # the example request keeps the full assessment and the hit list
        self.assertEqual(400, len(spans[5]["detail"]["assessment"]))
        self.assertEqual([{"episode": "Ep", "show": "Go Time", "snippet": "s"}], spans[1]["detail"]["hit_list"])
        plain = self.data["traces"][self.by_key["t-three/agent/1"]["id"]]
        self.assertEqual(admin_data.ASSESSMENT, len(plain[5]["detail"]["assessment"]))
        self.assertNotIn("hit_list", plain[1]["detail"])

    def test_answers_mark_what_was_sent_first_and_added(self):
        answer = self.data["answers"][self.by_key["t-one/agent/1"]["id"]]
        self.assertEqual([(0, True, False, "note 0"), (1, False, False, "note 1"), (2, False, False, "note 2")],
                         [(i["slot"], i["verified"], i["in_final"], i["note"]) for i in answer["first"]])
        self.assertEqual([("Y0", True, True, False, "Go Time"), ("X1", True, True, False, "Go Time"),
                          ("E2", False, False, False, None)],
                         [(i["expression"], i["verified"], i["added"], i["from_first"], i["show"])
                          for i in answer["final"]])
        baseline = self.data["answers"][self.by_key["t-one/baseline/1"]["id"]]
        self.assertEqual([(True, False), (False, True), (False, False)],
                         [(i["from_first"], i["added"]) for i in baseline["final"]])
        self.assertEqual({"first": [], "final": []}, self.data["answers"][self.by_key["t-decline/agent/1"]["id"]])

    def test_examples_and_aggregates(self):
        self.assertEqual({"baseline": "t-one-baseline", "agent": "t-one-agent", "skipped": "t-three-baseline"},
                         self.data["examples"])
        agent = self.data["aggregates"]["by_mode"]["agent"]
        self.assertEqual({"ok": 2, "declined": 1, "error": 1}, agent["status"])
        self.assertEqual({"skipped": 0, "ran": 3, "none": 1}, agent["continuation"])
        self.assertEqual({"0": 0, "1": 1, "2": 0, "3": 1}, agent["verified_first"])
        self.assertEqual({"n": 2, "mean": 7550.0, "p50": 7100, "p95": 8000, "p99": 8000, "min": 7100, "max": 8000},
                         agent["total_ms"])
        self.assertEqual(1, agent["background_ms"]["n"])  # only first-stage 1-2 verified requests
        self.assertEqual({"passed": 1, "n": 3, "rate": 0.3333}, agent["passed"])
        self.assertEqual(1, agent["lost_first_requests"])

    def test_mode_comes_from_the_flag_the_environment_or_the_default(self):
        self.assertEqual(("agent", "default"), resolve_mode(None, {}))
        self.assertEqual(("baseline", "env"), resolve_mode(None, {"COACH_SYSTEM": " baseline "}))
        self.assertEqual(("agent", "cli"), resolve_mode("agent", {"COACH_SYSTEM": "baseline"}))
        with self.assertRaises(ValueError):
            resolve_mode(None, {"COACH_SYSTEM": "agent_locked"})
        data = build(self.run, self.tasks, mode=resolve_mode(None, {"COACH_SYSTEM": "baseline"}))
        self.assertEqual(("baseline", "env", "COACH_SYSTEM"), (data["mode"]["current"], data["mode"]["source"],
                                                               data["mode"]["env_var"]))
        self.assertEqual({"baseline", "agent"}, set(data["mode"]["modes"]))

    def test_question_is_kept_verbatim(self):
        self.assertEqual(QUESTION, self.by_key["t-one/agent/1"]["question"])
        self.assertEqual("检索失败的问题", self.by_key["t-error/agent/1"]["question"])

    def test_write_inline_or_split_by_size(self):
        out = self.root / "out"
        sizes = write(self.data, out)
        self.assertEqual({"data.json"}, set(sizes))
        on_disk = json.loads((out / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(self.data, on_disk)
        self.assertEqual(sizes["data.json"], (out / "data.json").stat().st_size)
        inline = len(json.dumps(self.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        split = self.root / "split"
        sizes = write(self.data, split, max_bytes=inline - 1)  # auto: over the limit, so the traces move out
        self.assertEqual({"data.json", "data-traces.json"}, set(sizes))
        main = AdminData.model_validate_json((split / "data.json").read_text(encoding="utf-8"))
        traces = TracesFile.model_validate_json((split / "data-traces.json").read_text(encoding="utf-8"))
        self.assertIsNone(main.traces)
        self.assertEqual("data-traces.json", main.meta.files.traces)
        self.assertEqual(set(self.data["traces"]), set(traces.traces))
        self.assertEqual(self.data["traces"], traces.model_dump(mode="json")["traces"])
        self.assertEqual({"data.json", "data-traces.json"}, set(write(self.data, self.root / "always", split="always")))
        with self.assertRaises(ValueError):
            write(self.data, self.root / "never", max_bytes=inline - 1, split="never")
        with self.assertRaises(ValueError):
            write(self.data, self.root / "tiny", max_bytes=100)

    def test_command_line(self):
        out = self.root / "cli"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = admin_data.main(["--results", str(self.root), "--run", "pre", "--tasks", str(self.tasks),
                                    "--out", str(out), "--coach-system", "baseline"])
        self.assertEqual(0, code)
        self.assertIn("8 requests", stdout.getvalue())
        data = json.loads((out / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(("baseline", "cli"), (data["mode"]["current"], data["mode"]["source"]))
        base = {"--results": str(self.root), "--run": "pre", "--tasks": str(self.tasks), "--out": str(out)}
        for override in ({"--run": "../pre"}, {"--run": "missing"}, {"--max-bytes": "0"}, {"--systems": " , "},
                         {"--coach-system": "agent_locked"}):
            args = [part for option, value in {**base, **override}.items() for part in (option, value)]
            with self.subTest(override=override), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                admin_data.main(args)
        for systems in ("baseline,other", "agent,agent_locked", "baseline,missing_agent"):
            with self.subTest(systems=systems), redirect_stderr(io.StringIO()):
                self.assertEqual(2, admin_data.main(["--results", str(self.root), "--run", "pre", "--tasks",
                                                     str(self.tasks), "--out", str(out), "--systems", systems]))


if __name__ == "__main__":
    unittest.main()
