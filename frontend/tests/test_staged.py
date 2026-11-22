"""The staged coach (D1), the quick line (PR5) and POST /api/search over them: verified examples first, then the
final answer with the same result as answer(); the JSON reply as before, NDJSON on request, the deadline, the
request slot and the log line. Scripted models and searches only, no paid provider."""
import asyncio
import importlib
import json
import os
import sys
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx
import uvicorn
from fastapi.testclient import TestClient

from frontend import staged as staged_module
from frontend.server import DEADLINE_SECONDS, NDJSON, arguments, make_app
from frontend.staged import (CONTINUATION_CHOICES, QUICK_FORMAT, QUICK_MAX_TOKENS, QUICK_SECONDS, SYSTEM_CHOICES,
                             CoachMode, Failed, Final, First, Guard, Quick, QuickAnswerer, StagedCoach,
                             environment_quick, fast_model, is_terminal, keep_first, parse_quick, quick_prompt,
                             quick_settings)
from translation_agent_demo.agents import SYSTEMS, AgentPipeline, BaselinePipeline, CoachDependencies, ExpressionCoach
from translation_agent_demo.agents import prompts
from translation_agent_demo.agents.contracts import ChatCompletion
from translation_agent_demo.agents.evidence import SpanView
from translation_agent_demo.agents.prompts import SELECT_COMPACT_PROMPT, compact_candidates_prompt
from translation_agent_demo.agents.schemas.prefix import CandidateSet
from translation_agent_demo.agents.structured import response_format
from translation_agent_demo.agents.systems.first_stage import (DECLINE_NOTES, FAST_FIRST_STAGE, FULL_FIRST_STAGE,
                                                               FirstStageSettings)
from translation_agent_demo.errors import ModelProviderError
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel
from translation_agent_demo.tests.test_anthropic_chat import Transport, claude, message, text
from translation_agent_demo.tests.test_pipelines import (CANDIDATES, QUESTION, TEXTS, THREE_VERIFIED, TWO_VERIFIED,
                                                         candidates, decision, pick, replace as replace_action,
                                                         replacement, revision, search_action, searches)

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
                       decision(replace_action(slot, "Shall we pause here?", "pause here", "a1k1h1s1",
                                                       "Shall we pause here"))],
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
        self.assertEqual(CoachMode.from_environment({}), CoachMode("agent", True, FAST_FIRST_STAGE))
        self.assertEqual(CoachMode.from_environment({"COACH_SYSTEM": "", "COACH_CONTINUATION": ""}),
                         CoachMode("agent", True, FAST_FIRST_STAGE))
        self.assertEqual(CoachMode.from_environment({"COACH_SYSTEM": " Baseline\n", "COACH_CONTINUATION": "OFF",
                                                     "COACH_FIRST_STAGE": "FULL"}),
                         CoachMode("baseline", False))
        for env in ({"COACH_SYSTEM": "agent_locked"}, {"COACH_SYSTEM": "both"}, {"COACH_CONTINUATION": "true"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                CoachMode.from_environment(env)
        with self.assertRaises(ValueError):
            CoachMode("submission")

    def test_the_first_stage_settings(self):
        self.assertEqual(CoachMode().first_stage, FULL_FIRST_STAGE)  # built in code: the evaluated first stage
        self.assertEqual((FAST_FIRST_STAGE.candidates, FAST_FIRST_STAGE.view), (3, SpanView(3, 300)))
        mode = CoachMode.from_environment({"COACH_FIRST_CANDIDATES": "4", "COACH_FIRST_SPANS": "12",
                                           "COACH_FIRST_SPAN_CHARS": " 800 "})
        self.assertEqual(mode.first_stage, FirstStageSettings(4, True, SpanView(12, 800)))
        self.assertEqual(mode.first_stage.label(), "fast/4c/12s/800/p")  # parallel (v2) by default
        self.assertEqual(FirstStageSettings(4, True, SpanView(12, 800), parallel=False).label(), "fast/4c/12s/800")
        self.assertFalse(FULL_FIRST_STAGE.parallel)
        self.assertEqual((FAST_FIRST_STAGE.budget.model_calls, FAST_FIRST_STAGE.budget.searches), (5, 6))
        self.assertEqual(CoachMode.from_environment({"COACH_FIRST_STAGE": "full", "COACH_FIRST_CANDIDATES": "4"})
                         .first_stage.label(), "full")  # the fast settings do not apply to full
        for env in ({"COACH_FIRST_STAGE": "faster"}, {"COACH_FIRST_CANDIDATES": "2"},
                    {"COACH_FIRST_CANDIDATES": "7"}, {"COACH_FIRST_SPANS": "0"}, {"COACH_FIRST_SPAN_CHARS": "100"},
                    {"COACH_FIRST_SPAN_CHARS": "3e2"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                CoachMode.from_environment(env)
        with self.assertRaises(ValueError):  # only the compact first stage may differ from the evaluated one
            FirstStageSettings(candidates=3)

    def test_the_registered_agent_is_locked_and_an_unlocked_one_is_refused(self):
        deps, _, _ = dependencies("three_verified", "agent")
        self.assertTrue(StagedCoach(deps, CoachMode("agent")).pipeline.locked)
        with patch.dict(SYSTEMS, {"agent": AgentPipeline(locked=False)}), self.assertRaises(ValueError):
            StagedCoach(deps, CoachMode("agent"))


# One sentence of more than 300 characters with the first candidate's key phrase ("table this") in the middle.
LONG = ("We spent the whole morning on the build and there was a lot of talk about caching and tests and flaky "
        "runners and release notes and who owns the pipeline so honestly let's table this for now and come back "
        "after lunch because nobody here has the context to decide and the people who do are out until Monday "
        "anyway so there is really no point in going round in circles about it today.")
FAST_LONG = FirstStageSettings(3, True, SpanView(3, 200), parallel=False)  # PR7's one selection for all


class PreparedSearch:
    """A scripted search with an embedding prefetch: records what prepare was given."""

    def __init__(self, search):
        self.search, self.prepared = search, []

    def __call__(self, args):
        return self.search(args)

    def prepare(self, searches):
        self.prepared.append([args.query for args in searches])


class FastFirstStageTests(unittest.TestCase):
    """The app's fast first stage (PR7): 3 candidates, compact prompts, short spans, one embedding prefetch."""

    def run_fast(self, first, replies=(decision(),), texts=TEXTS[:3], system="agent"):
        clock = FakeClock()
        model, search = ScriptedModel(*first, *replies, clock=clock), PreparedSearch(searches(*texts))
        events = list(StagedCoach(CoachDependencies(model, search, clock),
                                  CoachMode(system, True, FAST_LONG)).stream(QUESTION, Guard()))
        return events, model, search

    def test_three_candidates_compact_prompts_and_spans_without_titles(self):
        (first, final), model, search = self.run_fast([candidates(3), TWO_VERIFIED])
        self.assertEqual([p for p, _ in model.prompts][:2], [compact_candidates_prompt(3), SELECT_COMPACT_PROMPT])
        self.assertEqual(model.formats[0], response_format(CandidateSet))  # the same reply schema as the evaluation
        self.assertEqual(len(search.search.args), 3)
        self.assertEqual(search.prepared, [[c[0] for c in CANDIDATES[:3]]])  # one prefetch for the three queries
        shown = model.prompts[1][1]["candidates"]
        self.assertEqual([c["candidate"] for c in shown], [0, 1, 2])
        self.assertTrue(all(set(span) == {"ref", "text", "has_key_phrase"} for c in shown for span in c["spans"]))
        self.assertEqual([i.expression for i in first.expressions], [CANDIDATES[0][0], CANDIDATES[2][0]])
        self.assertTrue(first.pending)
        self.assertEqual((final.expressions[:2], final.continuation), (first.expressions, "ran"))
        self.assertEqual([s.stage for s in final.result.trace][:6],
                         ["candidates", "search_1", "search_2", "search_3", "select_1", "validate_select_1"])

    def test_a_long_span_is_cut_around_its_key_phrase_and_the_cut_is_the_quote(self):
        selection = {"picks": [pick(0, "c0h1s1", "let's table this for now")]}
        (first, _), model, _ = self.run_fast([candidates(3), selection], texts=(LONG, *TEXTS[1:3]))
        span = model.prompts[1][1]["candidates"][0]["spans"][0]
        self.assertLessEqual(len(span["text"]), 200)
        self.assertIn("let's table this for now", span["text"])
        self.assertTrue(span["has_key_phrase"])
        self.assertEqual(first.expressions[0].citation.quote, span["text"])

    def test_a_quote_copied_from_the_neighbouring_span_is_moved_to_that_span_and_verified(self):
        texts = ("Let's table this for now. We should table this later.", *TEXTS[1:3])
        moved = {"picks": [pick(0, "c0h1s2", "let's table this for now")]}  # the wording of s1
        (first, _), _, _ = self.run_fast([candidates(3), moved], texts=texts)
        self.assertEqual(first.expressions[0].citation.quote, "Let's table this for now.")
        wrong = {"picks": [pick(0, "c0h1s2", "table this, I mean")]}  # in no span: still rejected
        (final,), _, _ = self.run_fast([candidates(3), wrong, decision()], texts=texts)
        self.assertEqual((type(final), final.verified_first), (Final, 0))

    def test_fewer_than_three_valid_candidates_are_asked_for_once_more_whatever_the_kind(self):
        short = candidates(3)
        short["candidates"][1]["key_phrase"] = "not in the expression"  # dropped: not one piece of it
        (first, _), model, _ = self.run_fast([short, candidates(3), TWO_VERIFIED])
        retry = model.prompts[1][1]["retry"]
        self.assertEqual((retry["valid_candidates"], retry["needed"]), (2, 3))
        self.assertEqual(retry["dropped_last_turn"][0]["error"], "key_phrase_not_contiguous")
        self.assertEqual(len(first.expressions), 2)
        still_short = candidates(3)
        still_short["candidates"][2]["key_phrase"] = "absent"
        (failed,), _, _ = self.run_fast([still_short, still_short])
        self.assertEqual((type(failed), failed.code), (Failed, "invalid_model_output"))

    def test_claude_haiku_is_called_without_thinking_in_the_fast_first_stage_only(self):
        reply = json.dumps(candidates(3, request_status="out_of_scope"))
        for effort, sent in ((None, None), ("xhigh", "high"), ("low", "low")):
            with self.subTest(effort=effort):
                transport = Transport(message(text(reply)))
                model = fast_model(claude(transport, **({"LLM_EFFORT": effort} if effort else {})))
                model.complete_with_usage(system_prompt="p", user_payload="{}", response_format=response_format(
                    CandidateSet))
                body = transport.bodies[0]
                self.assertEqual(body["thinking"], {"type": "disabled"})
                self.assertEqual(body.get("output_config", {}).get("effort"), sent)
                self.assertIn("format", body["output_config"])  # the schema is still sent
        opus = claude(Transport(), LLM_MODEL="claude-opus-5-5")
        self.assertIs(fast_model(opus), opus)  # Opus 5.5 rejects disabled thinking
        plain = ScriptedModel()
        self.assertIs(fast_model(plain), plain)
        deps = CoachDependencies(claude(Transport()), searches())
        coach = StagedCoach(deps, CoachMode("agent", True, FAST_FIRST_STAGE))
        self.assertIsNot(coach.first_dependencies.model, deps.model)
        self.assertIs(StagedCoach(deps, CoachMode("agent")).first_dependencies, deps)  # full: as configured


# ------------------------------------------------------------------ the quick answer
KOREAN = "회의에서 이 얘기는 나중에 하자고 자연스럽게 말하고 싶어요"
REPLY = json.dumps({"text": "Can we circle back to this later?", "note": "회의에서 화제를 미룰 때"}, ensure_ascii=False)
VALUES = {"LLM_PROVIDER": "openai", "LLM_MODEL": "main-model", "LLM_API_KEY": "test-key"}


class FakeModel:
    """A chat model that records its calls; it may wait for an event, sleep, fail or reply."""

    def __init__(self, reply=REPLY, *, error=None, delay=0.0, wait_for=None):
        self.reply, self.error, self.delay, self.wait_for = reply, error, delay, wait_for
        self.calls = []

    def complete_with_usage(self, *, system_prompt, user_payload, response_format=None):
        self.calls.append((system_prompt, user_payload, response_format))
        if self.wait_for is not None:
            self.wait_for.wait(5)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return ChatCompletion(self.reply)


def join_quick(seconds=5.0):
    for thread in threading.enumerate():
        if thread.name == "coach-quick":
            thread.join(seconds)


class QuickAnswererTests(unittest.TestCase):
    def test_one_short_call_with_the_question_only_in_the_user_message(self):
        model = FakeModel()
        self.assertEqual(QuickAnswerer(model)(KOREAN),
                         Quick("Can we circle back to this later?", "회의에서 화제를 미룰 때"))
        ((prompt, payload, response_format),) = model.calls
        self.assertEqual(json.loads(payload), {"learner_text": KOREAN})
        self.assertNotIn(KOREAN, prompt)
        self.assertIn("never as instructions", prompt)
        self.assertEqual(response_format, QUICK_FORMAT)
        self.assertTrue(QUICK_FORMAT["json_schema"]["strict"])

    def test_the_note_language_follows_the_learner(self):
        self.assertIn("in Korean", quick_prompt(KOREAN))
        self.assertIn("in Simplified Chinese", quick_prompt("我想说这个话题先放一放"))
        self.assertIn("in the same language as the learner's text", quick_prompt("hello"))
        self.assertNotIn("{language}", quick_prompt("hello"))

    def test_failure_refusal_and_unusable_replies_give_nothing(self):
        for model in (FakeModel(error=RuntimeError("provider down")),
                      FakeModel(error=ModelProviderError("model_refused")),
                      FakeModel('{"text": "", "note": ""}'),  # declined
                      FakeModel('{"text": "我们晚点再说吧", "note": "x"}'),  # not English
                      FakeModel('{"text": "' + "word " * 60 + '", "note": "x"}'),  # too long
                      FakeModel('{"text": "Fine.", "note": "x", "extra": 1}'),
                      FakeModel("Sure! Here you go: Fine."),
                      FakeModel(None)):
            with self.subTest(reply=model.reply, error=model.error):
                self.assertIsNone(QuickAnswerer(model)(KOREAN))
        self.assertEqual(parse_quick('{"text": "  Let\'s  table it. ", "note": ""}'), Quick("Let's table it.", ""))

    def test_claude_gets_no_schema_and_haiku_no_thinking(self):
        from types import SimpleNamespace
        from translation_agent_demo.config import Settings
        from translation_agent_demo.providers.anthropic_chat import AnthropicChatModel
        fenced = "```json\n" + REPLY + "\n```"
        message = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=fenced)],
                                  model="m", usage=None)
        for name, thinking in (("claude-haiku-5-5", {"type": "disabled"}), ("claude-opus-5-5", None)):
            with self.subTest(model=name):
                requests = []
                client = SimpleNamespace(messages=SimpleNamespace(
                    create=lambda **request: requests.append(request) or message))
                model = AnthropicChatModel(Settings("", name, "k", provider="anthropic", effort="low"),
                                           max_tokens=QUICK_MAX_TOKENS, client=client)
                self.assertEqual(QuickAnswerer(model)(KOREAN).text, "Can we circle back to this later?")
                (request,) = requests
                self.assertEqual(request["output_config"], {"effort": "low"})  # no format
                self.assertEqual(request.get("thinking"), thinking)
                self.assertNotIn(KOREAN, request["system"])

    def test_the_responses_adapter_gets_one_attempt_without_its_slow_retries(self):
        from translation_agent_demo.config import Settings
        from translation_agent_demo.providers.responses import ResponsesModel, RetryableGatewayError
        model = ResponsesModel(Settings("https://gateway.invalid/v1", "m", "k"), max_output_tokens=QUICK_MAX_TOKENS)
        with patch.object(model, "_request", side_effect=RetryableGatewayError("busy")) as request, \
                patch("translation_agent_demo.providers.responses.time.sleep") as sleep:
            started = time.monotonic()
            self.assertIsNone(QuickAnswerer(model)(KOREAN))
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()
        self.assertLess(time.monotonic() - started, 1)


class QuickSettingsTests(unittest.TestCase):
    def setUp(self):
        staged_module._environment_answerer.cache_clear()
        self.addCleanup(staged_module._environment_answerer.cache_clear)

    def test_the_quick_model_falls_back_to_the_chat_model_with_a_short_timeout_and_no_retries(self):
        settings = quick_settings(VALUES)
        self.assertEqual((settings.provider, settings.model, settings.timeout_seconds, settings.max_retries),
                         ("openai", "main-model", QUICK_SECONDS, 0))
        settings = quick_settings({**VALUES, "COACH_QUICK_MODEL": "fast-model"})
        self.assertEqual((settings.provider, settings.model), ("openai", "fast-model"))
        settings = quick_settings({**VALUES, "COACH_QUICK_PROVIDER": "anthropic", "COACH_QUICK_MODEL": "small",
                                   "ANTHROPIC_API_KEY": "a-key"})
        self.assertEqual((settings.provider, settings.model, settings.api_key, settings.effort, settings.max_retries),
                         ("anthropic", "small", "a-key", "low", 0))

    def test_environment_quick_uses_a_small_output_cap_and_a_wrong_setting_turns_it_off(self):
        built = []

        def fake_chat_model(settings, *, max_output_tokens=None):
            built.append((settings, max_output_tokens))
            return FakeModel()
        with patch.object(staged_module, "environment_values", return_value=VALUES), \
                patch.object(staged_module, "chat_model", fake_chat_model):
            self.assertEqual(environment_quick(KOREAN).text, "Can we circle back to this later?")
        self.assertEqual((built[0][0].model, built[0][1]), ("main-model", QUICK_MAX_TOKENS))
        staged_module._environment_answerer.cache_clear()
        for values in ({**VALUES, "COACH_QUICK_PROVIDER": "nope"}, {"LLM_PROVIDER": "openai"}):
            with self.subTest(values=values), patch.object(staged_module, "environment_values", return_value=values):
                self.assertIsNone(environment_quick(KOREAN))  # no exception: the coach still answers


# ------------------------------------------------------------------ POST /api/search
STREAM = {"Accept": NDJSON}
LEARNER_KEYS = {"expression", "key_phrase", "note", "citation"}
# What make_app reads at start, cleared so a shell's settings cannot change a test. The scenarios answer the
# evaluated first stage (6 candidates); the fast one has FastFirstStageTests.
CLEAN_ENV = {"COACH_PAIR_CODE": "", "COACH_WEB_ORIGIN": "", "COACH_SYSTEM": "", "COACH_CONTINUATION": "",
             "COACH_ADMIN_DIR": "", "COACH_ADMIN_DATA": "", "COACH_DEADLINE_SECONDS": "", "COACH_FIRST_STAGE": "full",
             "COACH_DAILY_LIMIT": "", "COACH_DAILY_TZ": "", "VERCEL": ""}


class Gate:
    """Wraps a scripted model; its call number `at` waits until the test opens the gate."""

    def __init__(self, at):
        self.at, self.calls, self.model = at, 0, None
        self.entered, self.opened = threading.Event(), threading.Event()

    def complete_with_usage(self, **kwargs):
        self.calls += 1
        if self.calls == self.at:
            self.entered.set()
            self.opened.wait(10)
        return self.model.complete_with_usage(**kwargs)


def scripted(name, gate=None):
    """A stream(question, mode, guard) running the scenario with fresh fakes; runs: (question, mode, model, search)."""
    runs = []

    def stream(question, mode, guard):
        deps, model, search = dependencies(name, mode.system)
        if gate is not None:
            gate.model = model
            deps = replace(deps, model=gate)
        runs.append((question, mode, model, search))
        return StagedCoach(deps, mode).stream(question, guard)
    return stream, runs


def lines(response):
    return [json.loads(line) for line in response.text.splitlines()]


def wait_for_workers(seconds=5.0):
    for thread in threading.enumerate():
        if thread.name == "coach-request":
            thread.join(seconds)


class ApiTestCase(unittest.TestCase):
    """make_app over the scripted coach in a clean environment; the coach's threads are joined afterwards."""

    def setUp(self):
        env = patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.logs = []

    def client(self, name="two_verified_filled", system="agent", *, continuation=True, gate=None, deadline=280.0,
               quick=None, quick_seconds=QUICK_SECONDS):
        stream, runs = scripted(name, gate)
        app = make_app(stream=stream, quick=quick, mode=CoachMode(system, continuation), log=self.logs.append,
                       deadline_seconds=deadline, quick_seconds=quick_seconds)
        return TestClient(app, base_url="http://localhost"), runs

    def log(self, index=-1):
        return json.loads(self.logs[index])

    def ask(self, client, *, stream=False, question=QUESTION, context=""):
        return client.post("/api/search", headers=STREAM if stream else {},
                           json={"question": question, "context": context})


class StreamApiTests(ApiTestCase):
    # ------------------------------------------------------------ order and content
    def test_some_verified_stream_first_then_final_and_json_gets_the_final(self):
        for system in ("agent", "baseline"):
            with self.subTest(system=system):
                client, runs = self.client("two_verified_filled", system)
                response = self.ask(client, stream=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers["content-type"].startswith(NDJSON))
                self.assertEqual(response.headers["cache-control"], "no-store")
                first, final = lines(response)
                self.assertEqual(set(first), {"type", "expressions", "pending", "note"})
                self.assertEqual(set(final), {"type", "expressions", "added", "note"})
                self.assertEqual((first["type"], first["pending"], final["type"], final["added"]),
                                 ("first", True, "final", [2]))
                self.assertEqual(len(first["expressions"]), 2)
                self.assertTrue(all(item["citation"] for item in first["expressions"]))
                self.assertEqual(final["expressions"][:2], first["expressions"])
                self.assertTrue(all(set(item) == LEARNER_KEYS for item in final["expressions"]))
                reply = self.ask(client)
                self.assertEqual(reply.status_code, 200)
                self.assertTrue(reply.headers["content-type"].startswith("application/json"))
                self.assertEqual(reply.json(), {"expressions": final["expressions"], "note": None})
                self.assertEqual(len(runs), 2)

    def test_after_a_first_the_stream_never_sends_an_unverified_candidate_but_json_keeps_the_whole_answer(self):
        for system in ("agent", "baseline"):
            with self.subTest(system=system):
                client, _ = self.client("two_verified_unfilled", system)
                first, final = lines(self.ask(client, stream=True))
                self.assertEqual((first["pending"], final["added"]), (True, []))
                self.assertEqual(final["expressions"], first["expressions"])  # the unfilled slot is not sent
                reply = self.ask(client).json()  # an old client gets the answer as before, candidate included
                self.assertEqual(reply["expressions"][:2], first["expressions"])
                self.assertEqual((len(reply["expressions"]), reply["expressions"][2]["citation"]), (3, None))
                stream_log, json_log = self.log(-2), self.log(-1)
                for record in (stream_log, json_log):
                    self.assertEqual((record["verified_first"], record["added_final"], record["verified_final"]),
                                     (2, 0, 2))
                self.assertIsInstance(stream_log["first_ms"], int)
                self.assertIsNone(json_log["first_ms"])  # a JSON client sees its first answer at total_ms

    def test_every_slot_verified_none_verified_or_declined_is_one_line(self):
        client, runs = self.client("three_verified")
        (first,) = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], len(first["expressions"])), ("first", False, 3))
        self.assertEqual(self.ask(client).json()["expressions"], first["expressions"])
        self.assertEqual(len(runs[0][2].prompts), 2)  # no call after the first stage
        client, _ = self.client("none_verified_filled")
        (final,) = lines(self.ask(client, stream=True))
        self.assertEqual((final["type"], final["added"], len(final["expressions"])), ("final", [0], 3))
        client, _ = self.client("declined")
        (final,) = lines(self.ask(client, stream=True))
        self.assertEqual(final, {"type": "final", "expressions": [], "added": [],
                                 "note": DECLINE_NOTES["out_of_scope"]})
        self.assertEqual(self.ask(client).json(), {"expressions": [], "note": DECLINE_NOTES["out_of_scope"]})

    def test_errors_before_and_after_the_first_answer(self):
        client, _ = self.client("first_stage_error")
        self.assertEqual(lines(self.ask(client, stream=True)), [{"type": "error", "code": "model_unavailable"}])
        reply = self.ask(client)
        self.assertEqual((reply.status_code, reply.json()), (503, {"detail": "model_unavailable"}))
        client, _ = self.client("continuation_error")
        first, error = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], error), ("first", True,
                                                                     {"type": "error", "code": "model_unavailable"}))
        reply = self.ask(client)  # what was verified first is final: the JSON reply keeps it
        self.assertEqual((reply.status_code, reply.json()["expressions"]), (200, first["expressions"]))

    def test_refusals_come_as_http_errors_before_any_line(self):
        client, runs = self.client("two_verified_filled")
        for stream in (False, True):
            response = self.ask(client, stream=stream, question="bad\x00input")
            self.assertEqual((response.status_code, response.json()), (422, {"detail": "invalid_input"}))
            response = client.post("/api/search", headers={**STREAM, "Origin": "https://other.invalid"},
                                   json={"question": "hello"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(runs, [])
        self.assertEqual([self.log(i)["status"] for i in range(len(self.logs))], ["invalid_input"] * 2)

    def test_an_accept_header_without_ndjson_or_with_q_zero_gets_json(self):
        client, _ = self.client("three_verified")
        for accept, kind in (("application/json", "application/json"), (f"{NDJSON};q=0", "application/json"),
                             (f"text/html, {NDJSON};q=0.5", NDJSON)):
            with self.subTest(accept=accept):
                response = client.post("/api/search", headers={"Accept": accept}, json={"question": "hello"})
                self.assertTrue(response.headers["content-type"].startswith(kind))

    # ------------------------------------------------------------ deadline and slot
    def test_the_deadline_ends_the_stream_with_timeout_and_keeps_the_first_answer(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                gate = Gate(at=3)  # the first call after the first stage
                client, runs = self.client("two_verified_filled", gate=gate, deadline=0.5)
                started = time.monotonic()
                response = self.ask(client, stream=stream)
                self.assertLess(time.monotonic() - started, 5)
                if stream:
                    first, error = lines(response)
                    self.assertEqual((first["type"], error), ("first", {"type": "error", "code": "timeout"}))
                else:
                    self.assertEqual((response.status_code, len(response.json()["expressions"])), (200, 2))
                record = self.log()
                self.assertEqual((record["status"], record["error_code"], record["continuation"]),
                                 ("timeout", "timeout", "ran"))
                self.assertEqual((record["verified_first"], record["added_final"]), (2, None))
                if stream:
                    self.assertLessEqual(record["first_ms"], record["total_ms"])
                else:
                    self.assertIsNone(record["first_ms"])
                # the slot returns only once the abandoned work has stopped, at its next call
                busy = self.ask(client, stream=stream)
                self.assertEqual((busy.status_code, busy.json()), (429, {"detail": "coach_busy"}))
                gate.opened.set()
                wait_for_workers()
                self.assertEqual(len(runs[0][3].args), 6)  # its next step, a search, was refused
                self.assertEqual(self.ask(client, stream=stream).status_code, 200)

    def test_a_deadline_before_the_first_answer_is_a_timeout_only(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                gate = Gate(at=1)
                client, _ = self.client("two_verified_filled", gate=gate, deadline=0.3)
                response = self.ask(client, stream=stream)
                if stream:
                    self.assertEqual(lines(response), [{"type": "error", "code": "timeout"}])
                else:
                    self.assertEqual((response.status_code, response.json()), (503, {"detail": "timeout"}))
                self.assertEqual((self.log()["status"], self.log()["continuation"], self.log()["first_ms"]),
                                 ("timeout", "none", None))
                gate.opened.set()

    def test_one_request_at_a_time_and_the_slot_returns_when_it_ends(self):
        gate = Gate(at=3)
        client, _ = self.client("two_verified_filled", gate=gate)
        answered = {}
        worker = threading.Thread(target=lambda: answered.update(r=self.ask(client, stream=True)))
        worker.start()
        self.assertTrue(gate.entered.wait(5))
        for stream in (False, True):
            busy = self.ask(client, stream=stream)
            self.assertEqual((busy.status_code, busy.json()), (429, {"detail": "coach_busy"}))
        gate.opened.set()
        worker.join(5)
        self.assertEqual([line["type"] for line in lines(answered["r"])], ["first", "final"])
        self.assertEqual(self.ask(client).status_code, 200)
        self.assertEqual([json.loads(line)["status"] for line in self.logs], ["busy", "busy", "ok", "ok"])

    # ------------------------------------------------------------ log line and mode
    def test_one_log_line_per_request_without_the_answer_or_the_context(self):
        client, _ = self.client("two_verified_filled")
        question = "我想礼貌地建议先把这个话题放一放，等会议结束后再讨论，应该怎么说才自然？请给我几个说法"
        self.ask(client, stream=True, question=question, context="SECRET-CONTEXT")
        self.assertEqual(len(self.logs), 1)
        record = self.log()
        self.assertEqual({k: record[k] for k in ("event", "mode", "continuation_setting", "transport", "status",
                                                 "error_code", "verified_first", "added_final", "verified_final",
                                                 "continuation", "invariant_ok", "llm_calls", "searches",
                                                 "input_tokens", "output_tokens", "disconnected")},
                         {"event": "coach_request", "mode": "agent", "continuation_setting": "on",
                          "transport": "ndjson", "status": "ok", "error_code": None, "verified_first": 2,
                          "added_final": 1, "verified_final": 3, "continuation": "ran", "invariant_ok": True,
                          "llm_calls": 4, "searches": 7, "input_tokens": 40, "output_tokens": 20,
                          "disconnected": False})
        self.assertEqual(record["question_head"], question[:40])
        self.assertLessEqual(record["first_ms"], record["total_ms"])
        self.assertNotIn("SECRET-CONTEXT", self.logs[0])
        self.assertNotIn("Shall we pause here", self.logs[0])  # no answer text
        self.assertLess(len(self.logs[0].encode()), 1024)
        # added_final as in the admin data: 0 without a first answer; verified_final what the learner ends with
        for name, status, continuation, first, added, final in (("three_verified", "ok", "skipped", 3, 0, 3),
                                                                ("declined", "declined", "none", None, 0, 0),
                                                                ("none_verified_filled", "ok", "ran", 0, 0, 1)):
            with self.subTest(scenario=name):
                client, _ = self.client(name)
                self.ask(client)
                record = self.log()
                self.assertEqual((record["transport"], record["status"], record["continuation"],
                                  record["verified_first"], record["added_final"], record["verified_final"],
                                  record["first_ms"]), ("json", status, continuation, first, added, final, None))

    def test_the_mode_comes_from_the_environment_and_a_wrong_value_stops_the_start(self):
        stream, runs = scripted("two_verified_filled")
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline", "COACH_CONTINUATION": "off"}):
            client = TestClient(make_app(stream=stream, log=self.logs.append), base_url="http://localhost")
        (first,) = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], len(first["expressions"])), ("first", False, 2))
        self.assertEqual(runs[0][1], CoachMode("baseline", False))
        record = self.log()
        self.assertEqual((record["mode"], record["continuation_setting"], record["continuation"]),
                         ("baseline", "off", "off"))
        for env in ({"COACH_SYSTEM": "agent_locked"}, {"COACH_CONTINUATION": "maybe"}):
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(ValueError):
                make_app(stream=stream)

    def test_the_vercel_function_follows_the_same_settings(self):
        def load():
            sys.modules.pop("frontend.vercel.index", None)
            return importlib.import_module("frontend.vercel.index")

        with patch.dict(os.environ, {"COACH_SYSTEM": "nonsense"}), self.assertRaises(ValueError):
            load()
        deps, model, search = dependencies("two_verified_unfilled", "baseline")
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline"}):
            index = load()
            with patch("frontend.vercel.coach.dependencies", return_value=(model, None, None)), \
                    patch("frontend.vercel.coach.SnapshotSearch", return_value=search), \
                    patch("builtins.print", side_effect=lambda line, **_: self.logs.append(line)):
                response = TestClient(index.app, base_url="https://coach.example").post(
                    "/api/search", headers=STREAM, json={"question": QUESTION})
        self.assertEqual([line["type"] for line in lines(response)], ["first", "final"])
        self.assertEqual([p[0] for p in model.prompts][2:], [prompts.REVISE_PROMPT])  # the baseline continued
        self.assertEqual(self.log()["mode"], "baseline")
        sys.modules.pop("frontend.vercel.index", None)

    def test_the_local_server_takes_its_deadline_from_the_option_or_the_environment(self):
        self.assertEqual(arguments([], {}).deadline, DEADLINE_SECONDS)
        self.assertEqual(arguments([], {"COACH_DEADLINE_SECONDS": " 1700 "}).deadline, 1700.0)
        self.assertEqual(arguments(["--deadline", "900"], {"COACH_DEADLINE_SECONDS": "1700"}).deadline, 900.0)
        for argv, env in ((["--deadline", "0"], {}), (["--deadline", "soon"], {}),
                          ([], {"COACH_DEADLINE_SECONDS": "7200"})):
            with self.subTest(argv=argv, env=env), patch("sys.stderr"), self.assertRaises(SystemExit):
                arguments(argv, env)


class QuickStreamTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(join_quick)

    def ask_held(self, client, gate, before_opening=join_quick):
        """Ask with the coach held at its gate; open it once before_opening() returns."""
        answered = {}
        worker = threading.Thread(target=lambda: answered.update(r=self.ask(client, stream=True)))
        worker.start()
        self.assertTrue(gate.entered.wait(5))
        before_opening()
        gate.opened.set()
        worker.join(5)
        return lines(answered["r"])

    def without_quick(self, *, stream=True):
        client, _ = self.client()
        response = self.ask(client, stream=stream)
        self.logs.pop()
        return lines(response) if stream else response.json()

    def test_the_quick_line_comes_first_and_the_answer_follows_unchanged(self):
        gate = Gate(at=1)
        # the quick model answers only once the coach is in its first model call: both run at once
        model = FakeModel(wait_for=gate.entered)
        client, runs = self.client(quick=QuickAnswerer(model), gate=gate)
        received = self.ask_held(client, gate)
        self.assertEqual(received[0], {"type": "quick", "text": "Can we circle back to this later?",
                                       "note": "회의에서 화제를 미룰 때"})
        self.assertEqual([line["type"] for line in received[1:]], ["first", "final"])
        self.assertEqual(received[1:], self.without_quick())
        self.assertEqual(json.loads(model.calls[0][1]), {"learner_text": QUESTION})
        record = json.loads(self.logs[-1])
        self.assertIsInstance(record["quick_ms"], int)
        self.assertLessEqual(record["quick_ms"], record["first_ms"])
        self.assertEqual(record["llm_calls"], 4)  # the coach's calls, as before; the quick call is apart

    def test_the_json_reply_never_asks_for_it(self):
        model = FakeModel()
        client, _ = self.client(quick=QuickAnswerer(model))
        self.assertEqual(self.ask(client).json(), self.without_quick(stream=False))
        join_quick()
        self.assertEqual(model.calls, [])
        self.assertIsNone(json.loads(self.logs[-1])["quick_ms"])

    def test_failure_lateness_refusal_and_a_late_line_send_no_quick_line(self):
        for label, model, seconds, at in (("failure", FakeModel(error=RuntimeError("down")), QUICK_SECONDS, 1),
                                          ("late", FakeModel(delay=0.4), 0.1, 1),
                                          ("refused", FakeModel(error=ModelProviderError("model_refused")),
                                           QUICK_SECONDS, 1),
                                          ("declined", FakeModel('{"text": "", "note": ""}'), QUICK_SECONDS, 1),
                                          ("after the first line", None, QUICK_SECONDS, 3)):
            with self.subTest(label):
                gate = Gate(at=at)  # at 1: the coach waits until the quick call has ended; at 3: after the first line
                model = model or FakeModel(wait_for=gate.entered)
                client, _ = self.client(quick=QuickAnswerer(model), gate=gate, quick_seconds=seconds)
                received = self.ask_held(client, gate)
                self.assertEqual(received, self.without_quick())
                self.assertEqual(len(model.calls), 1)
                self.assertIsNone(json.loads(self.logs[-1])["quick_ms"])

    def test_the_local_app_uses_the_environment_quick_model_and_an_injected_stream_does_not(self):
        calls = []

        def fake_quick(question):
            calls.append(question)
            return None
        stream, _ = scripted("three_verified")
        with patch("frontend.server.environment_quick", fake_quick), patch("frontend.server.local_stream", stream):
            local = TestClient(make_app(mode=CoachMode(), log=self.logs.append), base_url="http://localhost")
            injected = TestClient(make_app(stream=stream, mode=CoachMode(), log=self.logs.append),
                                  base_url="http://localhost")
            self.ask(injected, stream=True)
            join_quick()
            self.assertEqual(calls, [])
            self.ask(local, stream=True)
            join_quick()
        self.assertEqual(calls, [QUESTION])


class LiveStreamTests(ApiTestCase):
    """Through a real uvicorn server: lines arrive while the coach is still working, and a client that
    leaves stops the work."""

    def setUp(self):
        super().setUp()
        self.gate = Gate(at=3)
        stream, self.runs = scripted("two_verified_filled", self.gate)
        app = make_app(stream=stream, mode=CoachMode(), log=self.logs.append, serve_ui=False)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error",
                                                    lifespan="off", access_log=False))
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, self.server, "should_exit", True)
        self.addCleanup(wait_for_workers)
        self.addCleanup(self.gate.opened.set)
        deadline = time.monotonic() + 5
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/api/search"

    def test_the_first_line_arrives_before_the_continuation_ends(self):
        with httpx.Client(timeout=10) as http, \
                http.stream("POST", self.url, headers=STREAM, json={"question": QUESTION}) as response:
            received = response.iter_lines()
            first = json.loads(next(received))
            self.assertEqual((first["type"], first["pending"]), ("first", True))
            self.assertTrue(self.gate.entered.is_set())
            self.assertFalse(self.gate.opened.is_set())  # the continuation is still waiting on the model
            self.gate.opened.set()
            final = json.loads(next(received))
            self.assertEqual((final["type"], final["added"]), ("final", [2]))

    def test_a_client_that_leaves_stops_the_work(self):
        with httpx.Client(timeout=10) as http, \
                http.stream("POST", self.url, headers=STREAM, json={"question": QUESTION}) as response:
            self.assertEqual(json.loads(next(response.iter_lines()))["type"], "first")
        deadline = time.monotonic() + 5
        while not self.logs and time.monotonic() < deadline:
            time.sleep(0.02)
        record = json.loads(self.logs[0])
        self.assertEqual((record["status"], record["disconnected"], record["continuation"]),
                         ("disconnected", True, "ran"))
        self.gate.opened.set()
        wait_for_workers()
        self.assertEqual(len(self.runs[0][3].args), 6)  # the agent's search after the gate was refused


class RowStore:
    """The request log's database side in memory: what frontend/request_log.RequestStore.save receives."""
    enabled = True

    def __init__(self):
        self.rows = []

    def ensure(self):
        return True

    def mode_setting(self):
        return None

    def save(self, record, question, result=None):
        self.rows.append({**record, "question": question})
        return True


class EarlyDisconnectTests(ApiTestCase):
    """Raw ASGI: a client gone before the stream's first line still gets its log line and row, its work stops
    at its next call, and the request slot stays taken until then, on both of Starlette's disconnect paths."""

    def setUp(self):
        super().setUp()
        self.gate = Gate(at=1)  # the first model call waits: nothing is ready before the client leaves
        self.addCleanup(self.gate.opened.set)
        stream, self.runs = scripted("two_verified_filled", self.gate)
        self.store = RowStore()
        self.app = make_app(stream=stream, mode=CoachMode(), log=self.logs.append, serve_ui=False, store=self.store)

    def call(self, spec_version, send):
        body = json.dumps({"question": QUESTION}).encode()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": spec_version}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/search", "raw_path": b"/api/search",
                 "query_string": b"", "root_path": "", "server": ("localhost", 80), "client": ("127.0.0.1", 1),
                 "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"),
                             (b"accept", NDJSON.encode()), (b"content-length", str(len(body)).encode())]}
        messages = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            await asyncio.sleep(0)
            return messages.pop(0) if messages else {"type": "http.disconnect"}  # gone at once

        async def run():
            try:
                await self.app(scope, receive, send)
            except Exception:  # spec 2.4: the failed send surfaces as ClientDisconnect
                pass
        asyncio.run(run())

    def check_closed(self):
        self.assertEqual(len(self.logs), 1)  # logged when the response ended, not at the deadline
        record = json.loads(self.logs[0])
        self.assertEqual((record["status"], record["disconnected"], record["continuation"], record["first_ms"]),
                         ("disconnected", True, "none", None))
        self.assertEqual([(row["status"], row["question"]) for row in self.store.rows], [("disconnected", QUESTION)])
        # the model call under way still holds the slot: the next request waits for the work, not the client
        client = TestClient(self.app, base_url="http://localhost")
        busy = client.post("/api/search", headers=STREAM, json={"question": QUESTION})
        self.assertEqual((busy.status_code, busy.json()), (429, {"detail": "coach_busy"}))
        self.gate.opened.set()
        wait_for_workers()
        # at most the model call under way when the client left; every later call and search was refused
        self.assertLessEqual(self.gate.calls, 1)
        self.assertEqual(len(self.runs[0][3].args), 0)
        self.assertEqual([json.loads(line)["status"] for line in self.logs], ["disconnected", "busy"])
        # the work has stopped: the slot is back
        self.assertEqual([line["type"] for line in lines(client.post("/api/search", headers=STREAM,
                                                                      json={"question": QUESTION}))],
                         ["first", "final"])

    def test_spec_2_3_the_body_is_cancelled_before_its_first_line(self):
        sent = []

        async def send(message):
            sent.append(message["type"])
            await asyncio.sleep(0)
        self.call("2.3", send)
        self.assertNotIn("http.response.body", sent)
        self.check_closed()

    def test_spec_2_4_the_first_send_fails(self):
        async def send(message):
            raise OSError("client gone")
        self.call("2.4", send)
        self.check_closed()


if __name__ == "__main__":
    unittest.main()
