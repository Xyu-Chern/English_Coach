"""The staged coach (D1): verified examples first, then the final answer, with the same result as answer()."""
import unittest
from unittest.mock import patch

from frontend.staged import (CONTINUATION_CHOICES, SYSTEM_CHOICES, CoachMode, Failed, Final, First, Guard,
                             StagedCoach, is_terminal, keep_first)
from translation_agent_demo.agents import SYSTEMS, AgentPipeline, BaselinePipeline, CoachDependencies, ExpressionCoach
from translation_agent_demo.agents.systems.first_stage import DECLINE_NOTES
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel
from translation_agent_demo.tests.test_pipelines import (CANDIDATES, QUESTION, TEXTS, THREE_VERIFIED, TWO_VERIFIED,
                                                         candidates, decision, pick, replace, replacement, revision,
                                                         search_action, searches)

ONE_VERIFIED = {"picks": [pick(0, "c0h1s1", "let's table this for now")]}
NONE_VERIFIED = {"picks": []}
NOTHING_MORE = {"baseline": [revision()], "agent": [decision()]}  # each system gives up at once
PAUSE = "Shall we pause here and regroup?"


def fill_slot(slot):
    """Each system fills one empty slot with a verified example: (replies, continuation search texts).
    The baseline's last revision (offering nothing) ends its loop when other slots stay empty."""
    return {"baseline": ([revision(replacement(slot, "Let's come back to it.", "come back to")),
                          {"picks": [pick(slot, "r1k1h1s1", "come back to it later", "Let's come back to it.")]},
                          revision()],
                         ["Can we come back to it later today?"]),
            "agent": ([decision(search_action("Shall we pause here?", "pause here", slot=slot), finish=False),
                       decision(replace(slot, "Shall we pause here?", "pause here", "a1k1h1s1", "Shall we pause here"))],
                      [PAUSE])}


# name -> (first-stage replies, {system: (continuation replies, continuation search texts)})
SCENARIOS = {
    "three_verified": ([candidates(), THREE_VERIFIED], {s: ([], []) for s in SYSTEM_CHOICES}),
    "two_verified_filled": ([candidates(), TWO_VERIFIED], fill_slot(2)),
    "two_verified_unfilled": ([candidates(), TWO_VERIFIED], {s: (r, []) for s, r in NOTHING_MORE.items()}),
    "one_verified": ([candidates(), ONE_VERIFIED], {s: (r, []) for s, r in NOTHING_MORE.items()}),
    "none_verified_filled": ([candidates(), NONE_VERIFIED], fill_slot(2)),
    "declined": ([candidates(3, request_status="out_of_scope")], {s: ([], []) for s in SYSTEM_CHOICES}),
    "first_stage_error": ([RuntimeError("provider down")], {s: ([], []) for s in SYSTEM_CHOICES}),
    "continuation_error": ([candidates(), TWO_VERIFIED], {s: ([RuntimeError("provider down")], [])
                                                          for s in SYSTEM_CHOICES}),
}


def dependencies(name, system):
    first, continuations = SCENARIOS[name]
    replies, texts = continuations[system]
    clock = FakeClock()
    model = ScriptedModel(*first, *replies, clock=clock)
    search = searches(*([] if name in ("declined", "first_stage_error") else TEXTS), *texts)
    return CoachDependencies(model, search, clock), model, search


def staged(name, system, continuation=True, guard=None, question=QUESTION):
    deps, model, search = dependencies(name, system)
    return list(StagedCoach(deps, CoachMode(system, continuation)).stream(question, guard)), model, search


def comparable(result):
    return result.model_dump(mode="json", exclude={"request_id"})


def quotes(items):
    return [item.citation.quote if item.citation else None for item in items]


class ParityTests(unittest.TestCase):
    def test_the_staged_result_is_the_answer_of_the_same_system(self):
        for name in SCENARIOS:
            for system in SYSTEM_CHOICES:
                with self.subTest(scenario=name, system=system):
                    deps, _, _ = dependencies(name, system)
                    expected = ExpressionCoach(deps, system).answer(QUESTION)
                    events, _, _ = staged(name, system, guard=Guard())  # the guard changes nothing on its way
                    self.assertTrue(is_terminal(events[-1]))
                    self.assertFalse(any(is_terminal(e) for e in events[:-1]))
                    self.assertEqual(comparable(events[-1].result), comparable(expected))
                    self.assertEqual(expected.status, "error" if name.endswith("_error") else "ok")

    def test_invalid_input_matches_too_and_calls_nothing(self):
        deps, model, _ = dependencies("two_verified_filled", "agent")
        expected = ExpressionCoach(deps, "agent").answer("bad\x00input")
        (event,), model, search = staged("two_verified_filled", "agent", question="bad\x00input")
        self.assertEqual((type(event), event.code), (Failed, "invalid_input"))
        self.assertEqual(comparable(event.result), comparable(expected))
        self.assertEqual((model.prompts, search.args), ([], []))


class EventTests(unittest.TestCase):
    def test_every_slot_verified_sends_one_first_and_runs_nothing_more(self):
        for system in SYSTEM_CHOICES:
            with self.subTest(system=system):
                (event,), model, search = staged("three_verified", system)
                self.assertEqual((type(event), event.pending, event.continuation), (First, False, "skipped"))
                self.assertEqual(quotes(event.expressions), [TEXTS[0], "I hold off on lunch when I'm busy.", TEXTS[5]])
                self.assertEqual(list(event.expressions), event.result.expressions)
                self.assertEqual((len(model.prompts), len(search.args)), (2, 6))  # the first stage only

    def test_some_verified_sends_them_first_then_the_final_that_keeps_them(self):
        for system in SYSTEM_CHOICES:
            with self.subTest(system=system):
                (first, final), _, _ = staged("two_verified_filled", system)
                self.assertEqual((type(first), first.pending, first.result), (First, True, None))
                self.assertEqual([i.expression for i in first.expressions], [CANDIDATES[0][0], CANDIDATES[2][0]])
                self.assertTrue(all(i.citation for i in first.expressions))  # never an unverified candidate
                self.assertIsInstance(final, Final)
                self.assertEqual(final.expressions[:2], first.expressions)
                self.assertEqual((final.added, final.verified_first, final.continuation, final.kept_first),
                                 ((2,), 2, "ran", True))
                self.assertIsNotNone(final.expressions[2].citation)

    def test_a_slot_left_empty_is_in_the_final_without_an_example_and_not_added(self):
        for name, count in (("two_verified_unfilled", 2), ("one_verified", 1)):
            for system in SYSTEM_CHOICES:
                with self.subTest(scenario=name, system=system):
                    (first, final), _, _ = staged(name, system)
                    self.assertEqual((len(first.expressions), first.pending), (count, True))
                    self.assertEqual(final.expressions[:count], first.expressions)
                    self.assertEqual((final.added, len(final.expressions)), ((), 3))
                    self.assertTrue(all(i.citation is None for i in final.expressions[count:]))

    def test_none_verified_sends_only_the_final_with_what_was_found_later(self):
        for system in SYSTEM_CHOICES:
            with self.subTest(system=system):
                (final,), _, _ = staged("none_verified_filled", system)
                self.assertIsInstance(final, Final)
                self.assertEqual((final.verified_first, final.continuation), (0, "ran"))
                self.assertEqual(final.added, (0,))  # verified items come first in the answer
                self.assertIsNotNone(final.expressions[0].citation)

    def test_a_declined_request_is_one_final_with_its_note(self):
        (final,), model, search = staged("declined", "agent")
        self.assertEqual((final.expressions, final.added, final.declined), ((), (), True))
        self.assertEqual((final.note, final.verified_first, final.continuation),
                         (DECLINE_NOTES["out_of_scope"], None, "none"))
        self.assertEqual((len(model.prompts), search.args), (1, []))

    def test_failures_before_and_after_the_first_answer(self):
        (failed,), _, _ = staged("first_stage_error", "agent")
        self.assertEqual((type(failed), failed.code, failed.continuation), (Failed, "model_unavailable", "none"))
        for system in SYSTEM_CHOICES:
            with self.subTest(system=system):
                (first, failed), _, _ = staged("continuation_error", system)
                self.assertEqual((type(first), first.pending, len(first.expressions)), (First, True, 2))
                self.assertEqual((type(failed), failed.code, failed.continuation), (Failed, "model_unavailable", "ran"))

    def test_with_the_continuation_off_only_the_first_stage_runs(self):
        for system in SYSTEM_CHOICES:
            with self.subTest(system=system):
                (first,), model, search = staged("two_verified_filled", system, continuation=False)
                self.assertEqual((type(first), first.pending, first.continuation), (First, False, "off"))
                self.assertEqual(len(first.expressions), 2)
                self.assertEqual((len(model.prompts), len(search.args)), (2, 6))
                self.assertEqual(first.result.status, "ok")
                (final,), model, _ = staged("none_verified_filled", system, continuation=False)
                self.assertEqual((type(final), final.continuation, final.added), (Final, "off", ()))
                self.assertEqual([i.expression for i in final.expressions], [c for c, _ in CANDIDATES[:3]])
                self.assertEqual(len(model.prompts), 2)

    def test_a_changed_sent_example_is_put_back(self):
        def reorder(session, draft):  # a bug that would move the second verified slot to the front
            draft.slots[0], draft.slots[1] = draft.slots[1], draft.slots[0]

        with patch.object(BaselinePipeline, "improve", side_effect=reorder):
            (first, final), _, _ = staged("two_verified_unfilled", "baseline")
        self.assertFalse(final.kept_first)
        self.assertEqual(final.expressions[:2], first.expressions)
        self.assertEqual([i.expression for i in final.result.expressions][:2], [CANDIDATES[2][0], CANDIDATES[0][0]])
        self.assertEqual(keep_first(first.expressions, list(first.expressions)), (first.expressions, True))


class GuardTests(unittest.TestCase):
    def test_a_stopped_request_makes_no_call(self):
        guard = Guard()
        guard.stop()
        (failed,), model, search = staged("two_verified_filled", "agent", guard=guard)
        self.assertEqual((failed.code, model.prompts, search.args), ("model_unavailable", [], []))

    def test_the_deadline_stops_the_continuation_at_its_next_call(self):
        deps, model, search = dependencies("two_verified_filled", "agent")
        guard = Guard(deadline=1.5, clock=deps.clock)  # each fake model call takes one second
        first, failed = StagedCoach(deps, CoachMode("agent")).stream(QUESTION, guard)
        self.assertEqual((first.pending, failed.code, failed.continuation), (True, "model_unavailable", "ran"))
        self.assertEqual((len(model.prompts), len(search.args)), (2, 6))

    def test_the_meter_counts_what_the_result_counts(self):
        guard = Guard()
        (_, final), _, _ = staged("two_verified_filled", "agent", guard=guard)
        result = final.result
        self.assertEqual(guard.usage(), {"llm_calls": result.model_rounds, "searches": len(result.tool_calls),
                                         "input_tokens": result.usage.input_tokens,
                                         "output_tokens": result.usage.output_tokens,
                                         "cached_input_tokens": result.usage.cached_input_tokens})


class ModeTests(unittest.TestCase):
    def test_defaults_valid_values_and_refusals(self):
        self.assertEqual(set(SYSTEM_CHOICES), set(SYSTEMS))
        self.assertEqual(CONTINUATION_CHOICES, ("on", "off"))
        self.assertEqual(CoachMode.from_environment({}), CoachMode("agent", True))
        self.assertEqual(CoachMode.from_environment({"COACH_SYSTEM": "", "COACH_CONTINUATION": ""}),
                         CoachMode("agent", True))
        self.assertEqual(CoachMode.from_environment({"COACH_SYSTEM": " Baseline\n", "COACH_CONTINUATION": "OFF"}),
                         CoachMode("baseline", False))
        for env in ({"COACH_SYSTEM": "agent_locked"}, {"COACH_SYSTEM": "both"}, {"COACH_CONTINUATION": "true"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                CoachMode.from_environment(env)
        with self.assertRaises(ValueError):
            CoachMode("submission")

    def test_the_registered_agent_is_locked_and_an_unlocked_one_is_refused(self):
        deps, _, _ = dependencies("three_verified", "agent")
        self.assertTrue(StagedCoach(deps, CoachMode("agent")).pipeline.locked)
        with patch.dict(SYSTEMS, {"agent": AgentPipeline(locked=False)}), self.assertRaises(ValueError):
            StagedCoach(deps, CoachMode("agent"))


if __name__ == "__main__":
    unittest.main()
