"""One shared first stage, then two systems: baseline (a fixed workflow) and agent."""

import time
import unittest

from translation_agent_demo.agents import CoachDependencies, ExpressionCoach, answer_pair, prompts, system_for
from translation_agent_demo.agents.evidence import SHOW_FEEDS
from translation_agent_demo.agents.systems.base import CONTINUATION_BUDGET
from translation_agent_demo.agents.systems.first_stage import DECLINE_NOTES, FIRST_STAGE_BUDGET, run_first_stage
from translation_agent_demo.agents.session import Budget, RequestSession
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel, ScriptedSearch, make_hit, search_result

NAMES = ("baseline", "agent")
QUESTION = "<fixture request>"
CANDIDATES = (("Let's table this for now.", "table this"), ("Can we park that idea?", "park that"),
              ("I'd rather hold off on it.", "hold off on"), ("We should revisit it later.", "revisit it"),
              ("We can pick this up later.", "pick this up"), ("Let's put a pin in it.", "put a pin in"))
TEXTS = ("Okay, let's table this for now and move on.", "We talked about databases all day.",
         "I hold off on lunch when I'm busy. We should hold off on it until the review.",
         "We should revisit it after the release.", "Nothing relevant here at all.",
         "Let's put a pin in it, we're out of time.")
PREFIX_STAGES = ["candidates", *(f"search_{i}" for i in range(1, 7)), "select_1", "validate_select_1"]


# ------------------------------------------------------------------ replies
def candidates(n=6, **fields):
    return {"request_status": "answerable", "status_note": None, "kind": "function", "source_show": None, **fields,
            "candidates": [{"expression": e, "key_phrase": k, "function": "defer", "note": "Use in meetings."}
                           for e, k in CANDIDATES[:n]]}


def pick(candidate, ref, wording, expression=None):
    return {"candidate": candidate, "ref": ref, "expression": expression or CANDIDATES[candidate][0],
            "key_phrase": None, "reusable_wording": wording, "source_use": "s", "adaptation": "a"}


# After narrowing: slot 0 = c0 and slot 1 = c2 verified, slot 2 = c1 ("park that") without an example.
TWO_VERIFIED = {"picks": [pick(0, "c0h1s1", "let's table this for now"), pick(1, "c1h1s1", "not in the span"),
                          pick(2, "c2h1s1", "I hold off on lunch")]}
THREE_VERIFIED = {"picks": [pick(0, "c0h1s1", "let's table this for now"), pick(2, "c2h1s1", "I hold off on lunch"),
                            pick(5, "c5h1s1", "Let's put a pin in it")]}


def revision(*items):
    return {"replacements": list(items)}


def replacement(slot, expression, key_phrase, ref=None, wording=None):
    return {"replaces": slot, "expression": expression, "key_phrase": key_phrase, "function": "f", "note": "n",
            "ref": ref, "reusable_wording": wording, "source_use": "s" if ref else None,
            "adaptation": "a" if ref else None}


def decision(*actions, finish=True):
    """An agent turn."""
    return {"assessment": "Reviewed the draft.", "actions": list(actions), "finish": finish}


def search_action(query, key_phrase, slot=None):
    return {"type": "search", "slot": slot, "query": query, "key_phrase": key_phrase, "reason": "find a usage"}


def repick(slot, ref, wording, expression=None, key_phrase=None, reason="the quote shows another sense"):
    return {"type": "repick", "slot": slot, "ref": ref, "reusable_wording": wording, "source_use": "s",
            "adaptation": "a", "reason": reason, "expression": expression, "key_phrase": key_phrase}


def replace(slot, expression, key_phrase, ref, wording):
    return {"type": "replace", "slot": slot, "expression": expression, "key_phrase": key_phrase, "function": "f",
            "note": "n", "ref": ref, "reusable_wording": wording, "source_use": "s", "adaptation": "a",
            "reason": "the request needs a question form"}


# ------------------------------------------------------------------ running
def searches(*texts, feed_id=SHOW_FEEDS["go_time"], corpus_count=None):
    return ScriptedSearch(*(search_result(make_hit(i + 1, text, feed_id=feed_id), corpus_count=corpus_count)
                            for i, text in enumerate(texts)))


def run_systems(selection=None, *, replies=None, texts=None, first=None, clock=None, concurrent=False,
             corpus_count=None):
    """Both systems on QUESTION; returns (results, {system: (model, search)}, prefix model, prefix search).

    The agent given no replies gets one finishing turn; the baseline given none ends with
    model_unavailable once it needs a call, which no test here checks."""
    replies, texts = replies or {}, texts or {}
    prefix_search = searches(*TEXTS, corpus_count=corpus_count)
    first = first if isinstance(first, list) else [first or candidates()]
    prefix_model = ScriptedModel(*first, *([selection] if selection else []), clock=clock)

    def scripted(name):
        return replies.get(name, [decision()] if name == "agent" else [])

    systems = {name: (ScriptedModel(*scripted(name), clock=clock),
                     searches(*texts.get(name, ()))) for name in NAMES}
    continuations = {name: CoachDependencies(model, search, clock or time.perf_counter)
                     for name, (model, search) in systems.items()}
    results = answer_pair(CoachDependencies(prefix_model, prefix_search, clock or time.perf_counter), QUESTION,
                          continuations=continuations, concurrent=concurrent)
    return results, systems, prefix_model, prefix_search


def stages(result, start=len(PREFIX_STAGES)):
    return [span.stage for span in result.trace[start:]]


def step(result, stage):
    return next(span for span in result.trace if span.stage == stage)


def shown(result):
    return [(item.expression, item.citation is not None) for item in result.expressions]


def payloads(systems, name):
    return [payload for _, payload in systems[name][0].prompts]


class SystemTests(unittest.TestCase):
    def test_the_prefix_runs_once_and_each_system_continues_from_its_own_copy(self):
        come_back = [revision(replacement(2, "Let's come back to it.", "come back to")),
                     {"picks": [pick(2, "r1k1h1s1", "come back to it later", "Let's come back to it.")]}]
        for concurrent in (False, True):
            with self.subTest(concurrent=concurrent):
                results, systems, prefix_model, prefix_search = run_systems(
                    TWO_VERIFIED, concurrent=concurrent, replies={"baseline": come_back},
                    texts={"baseline": ["Can we come back to it later today?"]})
                self.assertEqual((len(prefix_model.prompts), len(prefix_search.args)), (2, 6))
                self.assertEqual(list(results), list(NAMES))
                prompts_seen = {name: [p[0] for p in systems[name][0].prompts] for name in NAMES}
                self.assertEqual(prompts_seen, {"baseline": [prompts.REVISE_PROMPT, prompts.SELECT_PROMPT],
                                                "agent": [prompts.AGENT_PROMPT]})
                # The baseline replaced slot 2 in its copy; the agent's copy is untouched.
                draft = payloads(systems, "agent")[0]["draft"]
                self.assertEqual([(s["expression"], s["example"] is not None) for s in draft],
                                 [(CANDIDATES[0][0], True), (CANDIDATES[2][0], True), (CANDIDATES[1][0], False)])
                self.assertEqual(shown(results["agent"]), [(s["expression"], s["example"] is not None) for s in draft])
                self.assertEqual(shown(results["baseline"]), [(CANDIDATES[0][0], True), (CANDIDATES[2][0], True),
                                                              ("Let's come back to it.", True)])
                self.assertEqual(stages(results["baseline"]), ["revise_1", "search_1_1", "select_2",
                                                               "validate_select_2", "assemble"])
                for result in results.values():
                    self.assertEqual(stages(result, 0)[:len(PREFIX_STAGES)], PREFIX_STAGES)
                    self.assertTrue(all(s.details["shared"] for s in result.trace[:len(PREFIX_STAGES)]))
                    self.assertFalse(any("shared" in s.details for s in result.trace[len(PREFIX_STAGES):]))

    def test_both_systems_have_the_same_ceilings_and_reach_the_search_ceiling(self):
        self.assertEqual((FIRST_STAGE_BUDGET.model_calls, FIRST_STAGE_BUDGET.searches), (3, 6))
        self.assertEqual((CONTINUATION_BUDGET.model_calls, CONTINUATION_BUDGET.searches), (6, 9))

        def rounds(r):
            return [revision(*(replacement(slot, f"Option {r}{slot}.", f"option {r}{slot}") for slot in (0, 1, 2))),
                    {"picks": []}]

        def busy(turn):
            return decision(*(search_action(f"query {turn}{i}", None) for i in range(4)), finish=False)

        final = {"assessment": "Last pick.", "actions": []}
        results, _, _, _ = run_systems({"picks": []}, texts={name: ["Unrelated."] * 9 for name in NAMES},
                                    replies={"baseline": [r for n in (1, 2, 3) for r in rounds(n)],
                                             "agent": [busy(1), busy(2), busy(3), final]})
        for name, calls in (("baseline", 6), ("agent", 4)):
            r = results[name]
            self.assertEqual((r.status, r.model_rounds - 2, len(r.tool_calls) - 6), ("ok", calls, 9), name)
            self.assertLessEqual(calls, CONTINUATION_BUDGET.model_calls)

    def test_a_spent_budget_assembles_what_exists_instead_of_failing(self):
        deps = CoachDependencies(ScriptedModel(candidates(), TWO_VERIFIED), searches(*TEXTS))
        draft = run_first_stage(RequestSession(deps, FIRST_STAGE_BUDGET), QUESTION)
        model = ScriptedModel(revision(replacement(2, "Let's come back to it.", "come back to")))
        session = RequestSession(CoachDependencies(model, searches("Unrelated.")), Budget(1, 1))
        expressions, _ = system_for("baseline").answer(session, draft)
        result = session.result("baseline", "ok", expressions=expressions)
        self.assertEqual([s.stage for s in result.trace], ["revise_1", "search_1_1", "budget_exhausted", "assemble"])
        self.assertEqual(result.trace[2].details["code"], "model_budget_exhausted")
        self.assertEqual(len(expressions), 3)

    def test_usage_and_latency_count_the_prefix_in_both_systems(self):
        clock = FakeClock()  # every model call takes one second
        results, _, _, _ = run_systems(TWO_VERIFIED, clock=clock, replies={"baseline": [
            revision(replacement(2, "Let's come back to it.", "come back to")),
            {"picks": [pick(2, "r1k1h1s1", "come back to it later", "Let's come back to it.")]}]},
            texts={"baseline": ["Can we come back to it later today?"]})
        r = results["baseline"]
        self.assertEqual((r.model_rounds, len(r.tool_calls), r.elapsed_ms), (4, 7, 4000.0))
        self.assertEqual((r.usage.input_tokens, r.usage.output_tokens, r.usage.embedding_tokens), (40, 20, 28))
        r = results["agent"]
        self.assertEqual((r.model_rounds, len(r.tool_calls), r.elapsed_ms), (3, 6, 3000.0))
        self.assertEqual((r.usage.input_tokens, r.usage.output_tokens, r.usage.embedding_tokens), (30, 15, 24))

    def test_a_requested_show_limits_every_search(self):
        search = searches(*TEXTS, "Shall we pause here?", feed_id=SHOW_FEEDS["js_party"])
        model = ScriptedModel(candidates(source_show="js_party"), THREE_VERIFIED,
                              decision(search_action("Shall we pause here?", "pause here"), finish=False),
                              decision())
        ExpressionCoach(CoachDependencies(model, search), "agent").answer(QUESTION)
        self.assertEqual([a.feed_ids for a in search.args], [[SHOW_FEEDS["js_party"]]] * 7)


class CompareRetryTests(unittest.TestCase):
    """A comparison with fewer than 3 valid candidates gets the candidates call once more."""

    def test_a_short_comparison_is_asked_once_more(self):
        short = candidates(2, kind="compare")
        results, systems, prefix_model, _ = run_systems(THREE_VERIFIED, first=[short, candidates(kind="compare")])
        self.assertEqual([p[0] for p in prefix_model.prompts],
                         [prompts.CANDIDATES_PROMPT, prompts.CANDIDATES_PROMPT, prompts.SELECT_PROMPT])
        self.assertEqual(prefix_model.prompts[1][1]["retry"], {"valid_candidates": 2, "needed": 3,
                                                               "dropped_last_turn": []})
        for name in NAMES:
            self.assertEqual(stages(results[name], 0)[:3], ["candidates", "candidates_retry", "search_1"])
            self.assertEqual(results[name].status, "ok")

    def test_a_retry_that_is_still_short_fails_and_other_kinds_never_retry(self):
        for first, calls in (([candidates(2, kind="compare"), candidates(1, kind="compare")], 2),
                             ([candidates(2)], 1)):
            results, _, prefix_model, _ = run_systems(first=first)
            self.assertEqual(len(prefix_model.prompts), calls)
            self.assertEqual({(r.status, r.error_code) for r in results.values()}, {("error", "invalid_model_output")})
            self.assertEqual(results["agent"].trace[-1].stage, "validate_action")


class DiagnosticsTests(unittest.TestCase):
    """Every decision call sees corpus_count per search and has_key_phrase per span, in one format."""

    def test_select_revise_and_agent_calls_see_the_same_diagnostics(self):
        results, systems, prefix_model, _ = run_systems(
            TWO_VERIFIED, corpus_count=4, replies={"baseline": [revision(replacement(2, CANDIDATES[3][0],
                                                                                     "revisit it"))]},
            texts={"baseline": ["Unrelated."]})
        selected = prefix_model.prompts[1][1]["candidates"][0]
        self.assertEqual((selected["corpus_count"], selected["spans"][0]["has_key_phrase"]), (4, True))
        span_keys = {"ref", "text", "has_key_phrase", "episode_title"}
        self.assertEqual(set(selected["spans"][0]), span_keys)
        revise = payloads(systems, "baseline")[0]
        slot = revise["unsupported_slots"][0]
        self.assertEqual(set(slot), {"slot", "expression", "key_phrase", "function", "note", "rejection_reasons",
                                     "tried", "corpus_count", "spans"})
        self.assertEqual((slot["slot"], slot["corpus_count"], slot["spans"][0]["has_key_phrase"]), (2, 4, False))
        self.assertEqual(revise["verified_slots"],
                         [{"slot": 0, "expression": CANDIDATES[0][0]}, {"slot": 1, "expression": CANDIDATES[2][0]}])
        view = payloads(systems, "agent")[0]
        self.assertEqual(set(view), {"question", "final_pick", "remaining", "draft", "other_candidates", "passages",
                                     "earlier_actions", "dropped_last_turn"})
        passage = view["passages"][0]
        self.assertEqual(set(passage), {"search", "query", "key_phrase", "corpus_count", "spans"})
        self.assertEqual((passage["corpus_count"], set(passage["spans"][0])), (4, span_keys))


class BaselineTests(unittest.TestCase):
    def test_nothing_more_runs_when_every_slot_has_a_verified_example(self):
        results, systems, _, _ = run_systems(THREE_VERIFIED)
        self.assertEqual(systems["baseline"][0].prompts, [])
        self.assertEqual(stages(results["baseline"]), ["assemble"])

    def test_revises_unsupported_slots_for_at_most_three_rounds(self):
        def rounds(r):
            return [revision(*(replacement(slot, f"Option {r}{slot}.", f"option {r}{slot}") for slot in (0, 1, 2))),
                    {"picks": []}]

        results, systems, _, _ = run_systems({"picks": []}, replies={"baseline": [x for r in (1, 2, 3)
                                                                                for x in rounds(r)]},
                                          texts={"baseline": ["Unrelated."] * 9})
        self.assertEqual(stages(results["baseline"]), [stage for r in (1, 2, 3) for stage in (
            f"revise_{r}", f"search_{r}_1", f"search_{r}_2", f"search_{r}_3", f"select_{r + 1}",
            f"validate_select_{r + 1}")] + ["assemble"])
        round_3 = payloads(systems, "baseline")[4]["unsupported_slots"][0]
        self.assertEqual((round_3["expression"], round_3["tried"]), ("Option 20.", [CANDIDATES[0][0], "Option 10."]))

    def test_stops_when_a_revision_offers_no_usable_replacement(self):
        results, _, _, _ = run_systems(TWO_VERIFIED, replies={"baseline": [revision(replacement(0, "x", "x"))]})
        self.assertEqual(stages(results["baseline"]), ["revise_1", "assemble"])  # slot 0 already has an example

    def test_adopts_a_seen_span_without_spending_a_search(self):
        adopt = revision(replacement(2, CANDIDATES[3][0], "revisit it", "c3h1s1", "We should revisit it"))
        results, systems, _, _ = run_systems(TWO_VERIFIED, replies={"baseline": [adopt]})
        payload = payloads(systems, "baseline")[0]
        pool = {span["ref"]: span for span in payload["span_pool"]}
        self.assertEqual((pool["c3h1s1"]["search"], pool["c3h1s1"]["has_key_phrase"]), ("search_4", True))
        self.assertEqual(payload["alternatives"], [{"expression": e, "key_phrase": k, "function": "defer"}
                                                   for e, k in CANDIDATES[3:]])
        self.assertEqual(payload["dropped_last_turn"], [])
        baseline = results["baseline"]
        self.assertEqual(stages(baseline), ["revise_1", "validate_select_2", "assemble"])
        self.assertEqual((baseline.model_rounds, len(baseline.tool_calls)), (3, 6))
        self.assertEqual(baseline.expressions[2].citation.quote, TEXTS[3])

    def test_searches_a_replacement_whose_ref_does_not_verify(self):
        adopt = revision(replacement(2, CANDIDATES[3][0], "revisit it", "c3h1s1", "not in the span"))
        results, _, _, _ = run_systems(TWO_VERIFIED, replies={"baseline": [adopt, {"picks": []}, revision()]},
                                    texts={"baseline": ["Unrelated."]})
        baseline = results["baseline"]
        self.assertEqual(stages(baseline), ["revise_1", "search_1_1", "select_2", "validate_select_2", "revise_2",
                                            "assemble"])
        self.assertEqual(step(baseline, "validate_select_2").details["excluded"],
                         [{"slot": 2, "ref": "c3h1s1", "reason": "reusable_wording_not_in_span"}])


class AgentTests(unittest.TestCase):
    def test_reviews_even_three_verified_examples_and_repicks_a_wrong_one(self):
        turn = decision(repick(1, "c2h1s2", "We should hold off on it until the review"))
        results, systems, _, _ = run_systems(THREE_VERIFIED, replies={"agent": [turn]})
        seen = payloads(systems, "agent")[0]
        self.assertEqual([s["example"]["ref"] for s in seen["draft"]], ["c0h1s1", "c2h1s1", "c5h1s1"])
        self.assertEqual(seen["remaining"], {"turns_after_this": 2, "searches": 9,
                                             "pick_call_follows_if_you_search": False})
        agent = results["agent"]
        self.assertEqual(stages(agent), ["agent_1", "repick_1_1", "validate_agent_1", "assemble"])
        self.assertEqual(agent.expressions[1].citation.quote, "We should hold off on it until the review.")
        self.assertEqual({k: step(agent, "validate_agent_1").details[k] for k in ("guard", "noops")},
                         {"guard": [], "noops": []})

    def test_targets_a_missing_constraint_with_a_search_then_a_replace(self):
        turns = [decision(search_action("Shall we pause here?", "pause here", slot=2), finish=False),
                 decision(replace(2, "Shall we pause here?", "pause here", "a1k1h1s1", "Shall we pause here"))]
        results, systems, _, _ = run_systems(THREE_VERIFIED, replies={"agent": turns},
                                          texts={"agent": ["Shall we pause here and regroup?"]})
        self.assertEqual(systems["agent"][1].args[0].literal_phrase, "pause here")
        second = payloads(systems, "agent")[1]
        self.assertEqual(second["passages"][-1]["spans"][0]["ref"], "a1k1h1s1")
        self.assertEqual(second["earlier_actions"], [{"turn": "1", "type": "search", "slot": 2,
                                                      "step": "search_1_1", "outcome": "searched"}])
        self.assertEqual(stages(results["agent"]), ["agent_1", "search_1_1", "validate_agent_1", "agent_2",
                                                    "replace_2_1", "validate_agent_2", "assemble"])
        self.assertEqual(shown(results["agent"])[2], ("Shall we pause here?", True))

    def test_a_last_turn_that_searched_gets_one_pick_only_call(self):
        def busy(turn):
            return decision(*(search_action(f"query {turn}{i}", None) for i in range(4)), finish=False)

        final = {"assessment": "Last pick.", "actions": [repick(0, "a3k1h1s1", "Let's table this")]}
        results, systems, _, _ = run_systems({"picks": []}, replies={"agent": [busy(1), busy(2), busy(3), final]},
                                          texts={"agent": ["Unrelated."] * 8 + ["Let's table this one."]})
        agent, model = results["agent"], systems["agent"][0]
        self.assertEqual((agent.model_rounds, len(agent.tool_calls)), (2 + 4, 6 + 9))
        self.assertEqual(stages(agent)[-4:], ["pick_final", "repick_final_1", "validate_pick_final", "assemble"])
        self.assertEqual([s.details["skipped"] for s in agent.trace if "skipped" in s.details],
                         ["no_searches_left"] * 3)
        self.assertEqual([p["remaining"]["pick_call_follows_if_you_search"] for p in payloads(systems, "agent")],
                         [False, False, True, False])
        self.assertEqual(model.formats[-1]["json_schema"]["name"], "FinalPick")
        self.assertEqual(shown(agent)[0], (CANDIDATES[0][0], True))

    def test_a_finishing_turn_runs_no_search(self):
        finishing = decision(search_action("more", "more"))
        results, systems, _, _ = run_systems(THREE_VERIFIED, replies={"agent": [finishing]})
        self.assertEqual(systems["agent"][1].args, [])
        self.assertEqual(step(results["agent"], "search_1_1").details["skipped"], "finish_requested")

    def test_the_agent_may_finish_without_a_verified_example(self):
        """Nothing forces another turn: an early finish with an empty draft is the agent's choice."""
        results, _, _, _ = run_systems({"picks": []}, replies={"agent": [decision()]})
        self.assertEqual(stages(results["agent"]), ["agent_1", "validate_agent_1", "assemble"])


class GuardTests(unittest.TestCase):
    """G1 and no-op recording."""

    def test_g1_keeps_a_verified_example_a_failed_change_would_lose(self):
        turn = decision(repick(1, None, None),  # removal of a verified example, for its meaning
                        replace(0, "Let's shelve this.", "shelve this", "c4h1s1", "Nothing relevant"))
        agent = run_systems(THREE_VERIFIED, replies={"agent": [turn]})[0]["agent"]
        self.assertEqual(shown(agent), [(CANDIDATES[0][0], True), (CANDIDATES[5][0], True),
                                        (CANDIDATES[2][0], True)])
        validated = step(agent, "validate_agent_1").details
        self.assertEqual(validated["guard"], [
            {"slot": 1, "kept_ref": "c2h1s1", "reason": "repick_without_example", "moved_to_end": True},
            {"slot": 0, "kept_ref": "c0h1s1", "reason": "replace_rejected:wording_lacks_key_phrase",
             "moved_to_end": False}])
        self.assertEqual(step(agent, "replace_1_2").details["outcome"], "kept_verified_example")

    def test_a_doubted_example_moves_to_the_end_only_for_a_meaning_problem(self):
        for reason, moved in (("a shorter quote would read better", False), ("the quote uses another sense", True)):
            with self.subTest(reason=reason):
                turn = decision(repick(1, None, None, reason=reason))
                agent = run_systems(THREE_VERIFIED, replies={"agent": [turn]})[0]["agent"]
                self.assertEqual(step(agent, "validate_agent_1").details["guard"][0]["moved_to_end"], moved)

    def test_a_ref_less_replace_of_a_verified_example_keeps_the_example(self):
        shelve = replace(0, "Let's shelve this.", "shelve this", None, None)
        agent = run_systems(TWO_VERIFIED, replies={"agent": [decision(shelve)]})[0]["agent"]
        self.assertEqual(step(agent, "replace_1_1").details["outcome"], "kept_verified_example")

    def test_a_kept_example_still_holds_its_span(self):
        turn = decision(repick(1, None, None), repick(0, "c2h1s1", "I hold off on lunch"))
        agent = run_systems(THREE_VERIFIED, replies={"agent": [turn]})[0]["agent"]
        self.assertEqual(step(agent, "repick_1_2").details["rejection_reasons"], ["unknown_or_reused_ref"])
        self.assertEqual([i.citation.quote for i in agent.expressions],
                         [TEXTS[5], TEXTS[0], "I hold off on lunch when I'm busy."])

    def test_a_repick_may_carry_a_variant_expression(self):
        turn = decision(repick(2, "c3h1s1", "We should revisit it", "We should revisit it.", "revisit it"))
        agent = run_systems(TWO_VERIFIED, replies={"agent": [turn]})[0]["agent"]
        self.assertEqual(step(agent, "repick_1_1").details["outcome"], "verified")
        self.assertEqual((agent.expressions[2].expression, agent.expressions[2].key_phrase),
                         ("We should revisit it.", "revisit it"))

    def test_noops_are_recorded_not_run_and_an_identical_search_spends_nothing(self):
        turns = [decision(search_action(CANDIDATES[0][0], "Table this"), repick(2, None, None), finish=False),
                 decision()]
        results, systems, _, _ = run_systems(TWO_VERIFIED, replies={"agent": turns})
        agent = results["agent"]
        self.assertEqual((systems["agent"][1].args, len(agent.tool_calls)), ([], 6))
        self.assertEqual(step(agent, "validate_agent_1").details["noops"],
                         [{"step": "search_1_1", "slot": None, "reason": "identical_search"},
                          {"step": "repick_1_2", "slot": 2, "reason": "nothing_to_remove"}])
        second = payloads(systems, "agent")[1]
        self.assertEqual([(a["outcome"], a.get("noop")) for a in second["earlier_actions"]],
                         [("noop:identical_search", True), ("noop:nothing_to_remove", True)])


class DroppedFeedbackTests(unittest.TestCase):
    """What validation dropped from a reply reaches the system's next decision call."""

    def test_both_systems_tell_their_next_decision_call_what_was_dropped(self):
        gapped_revision = replacement(2, "Let's treat it as done.", "treat ... as")
        gapped_action = replace(2, "Let's treat it as done.", "treat ... as", None, None)
        _, systems, _, _ = run_systems(TWO_VERIFIED, replies={
            "baseline": [revision(gapped_revision, replacement(2, "Let's shelve it.", "shelve it")), {"picks": []},
                         revision()],
            "agent": [decision(gapped_action, finish=False), decision()]},
            texts={"baseline": ["Unrelated."]})
        expected = {"baseline": ("revise_1", "replacements", 0, 2, 2), "agent": ("agent_1", "actions", 0, 2, 1)}
        for name, (stage, items, index, slot, call) in expected.items():
            with self.subTest(system=name):
                first, later = payloads(systems, name)[0], payloads(systems, name)[call]
                self.assertEqual(first.get("dropped_last_turn"), [])
                dropped = later["dropped_last_turn"]
                self.assertEqual(len(dropped), 1)
                self.assertEqual((dropped[0]["step"], dropped[0]["list"], dropped[0]["index"], dropped[0]["slot"]),
                                 (stage, items, index, slot))
                self.assertTrue(dropped[0]["reason"].endswith("key_phrase_not_contiguous"))


class DeclineTests(unittest.TestCase):
    def test_a_source_outside_the_corpus_or_an_out_of_scope_request_gets_no_expressions(self):
        for status in ("source_not_available", "out_of_scope"):
            with self.subTest(status=status):
                first = candidates(3, request_status=status)  # candidates given anyway are never shown
                results, systems, _, prefix_search = run_systems(first=first)
                self.assertEqual(prefix_search.args, [])
                self.assertEqual(list(results), list(NAMES))
                for name, result in results.items():
                    self.assertEqual((result.status, result.expressions, result.model_rounds), ("ok", [], 1))
                    self.assertEqual(result.source_availability_note, DECLINE_NOTES[status])
                    self.assertEqual(stages(result, 0), ["candidates", "decline", "assemble"])
                    self.assertEqual(systems[name][0].prompts, [])


class TraceContractTests(unittest.TestCase):
    def test_steps_carry_what_the_viewer_renders(self):
        turns = [decision(search_action("Shall we pause here?", "pause here", slot=2), finish=False),
                 decision(replace(2, "Shall we pause here?", "pause here", "a1k1h1s1", "Shall we pause here"))]
        agent = run_systems(TWO_VERIFIED, replies={"agent": turns},
                         texts={"agent": ["Shall we pause here and regroup?"]})[0]["agent"]
        model_step = step(agent, "agent_1").details
        self.assertLessEqual({"model", "input_tokens", "output_tokens", "output"}, set(model_step))
        self.assertEqual(model_step["output"]["actions"][0]["reason"], "find a usage")
        search = step(agent, "search_1").details
        self.assertEqual((search["slot"], search["query"], search["key_phrase"], search["ref_prefix"]),
                         (0, CANDIDATES[0][0], "table this", "c0"))
        self.assertIn("corpus_count", search)
        self.assertEqual(search["hits"][0], {"chunk_id": "00000000-0000-0000-0000-000000000001",
                                             "source_key": f"podcast_index:{SHOW_FEEDS['go_time']}:1",
                                             "show": "go_time", "episode_title": "Authored test fixture",
                                             "snippet": TEXTS[0]})
        first = step(agent, "validate_select_1").details
        self.assertEqual([(s["slot"], s["candidate"], s["status"], s["rejection_reasons"]) for s in first["slots"]],
                         [(0, 0, "verified", []), (1, 2, "verified", []),
                          (2, 1, "no_example", ["reusable_wording_not_in_span"])])
        self.assertEqual(first["alternatives"], [c[0] for c in CANDIDATES[3:]])
        replaced = step(agent, "replace_2_1").details
        self.assertEqual((replaced["previous_expression"], replaced["expression"], replaced["outcome"]),
                         (CANDIDATES[1][0], "Shall we pause here?", "verified"))
        self.assertEqual(step(agent, "validate_agent_2").details["slots"][2]["quote"],
                         "Shall we pause here and regroup?")


class CoachTests(unittest.TestCase):
    def test_rejects_invalid_input_before_any_call(self):
        model = ScriptedModel()
        for question in ("", "   ", "x" * 4001, "a\x00b"):
            with self.subTest(question=question[:5]):
                results = answer_pair(CoachDependencies(model, ScriptedSearch()), question)
                self.assertEqual(list(results), list(NAMES))
                self.assertEqual({r.error_code for r in results.values()}, {"invalid_input"})
        self.assertEqual(model.prompts, [])

    def test_arms_can_be_chosen(self):
        model = ScriptedModel(candidates(), THREE_VERIFIED)
        results = answer_pair(CoachDependencies(model, searches(*TEXTS)), QUESTION, systems=["baseline"])
        self.assertEqual((list(results), results["baseline"].status), (["baseline"], "ok"))

    def test_one_arm_runs_alone_without_shared_marks(self):
        search = searches(*TEXTS)
        result = ExpressionCoach(CoachDependencies(ScriptedModel(candidates(), THREE_VERIFIED), search),
                                 "baseline").answer(QUESTION)
        self.assertEqual((result.variant, result.status, result.model_rounds), ("baseline", "ok", 2))
        self.assertFalse(any("shared" in span.details for span in result.trace))
        with self.assertRaises(ValueError):
            ExpressionCoach(CoachDependencies(ScriptedModel(), search), "multi_agent")


if __name__ == "__main__":
    unittest.main()
