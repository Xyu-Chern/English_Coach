"""The quick answer (PR5): one fast model call beside the coach, sent as the stream's first line when it
answers in time. Fake models only: success, failure, delay and refusal; no paid provider."""
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from frontend import quick as quick_module
from frontend.quick import (QUICK_FORMAT, QUICK_MAX_TOKENS, QUICK_SECONDS, Quick, QuickAnswerer, environment_quick,
                            parse, quick_settings, system_prompt)
from frontend.server import make_app
from frontend.staged import CoachMode
from frontend.tests.test_staged import QUESTION
from frontend.tests.test_stream import CLEAN_ENV, STREAM, Gate, lines, scripted, wait_for_workers
from translation_agent_demo.agents.contracts import ChatCompletion
from translation_agent_demo.errors import ModelProviderError

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
        self.assertIn("in Korean", system_prompt(KOREAN))
        self.assertIn("in Simplified Chinese", system_prompt("我想说这个话题先放一放"))
        self.assertIn("in the same language as the learner's text", system_prompt("hello"))
        self.assertNotIn("{language}", system_prompt("hello"))

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
        self.assertEqual(parse('{"text": "  Let\'s  table it. ", "note": ""}'), Quick("Let's table it.", ""))

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
        quick_module._environment_answerer.cache_clear()
        self.addCleanup(quick_module._environment_answerer.cache_clear)

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
        with patch.object(quick_module, "environment_values", return_value=VALUES), \
                patch.object(quick_module, "chat_model", fake_chat_model):
            self.assertEqual(environment_quick(KOREAN).text, "Can we circle back to this later?")
        self.assertEqual((built[0][0].model, built[0][1]), ("main-model", QUICK_MAX_TOKENS))
        quick_module._environment_answerer.cache_clear()
        for values in ({**VALUES, "COACH_QUICK_PROVIDER": "nope"}, {"LLM_PROVIDER": "openai"}):
            with self.subTest(values=values), patch.object(quick_module, "environment_values", return_value=values):
                self.assertIsNone(environment_quick(KOREAN))  # no exception: the coach still answers


class QuickStreamTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.addCleanup(join_quick)
        self.logs = []

    def client(self, name="two_verified_filled", *, quick=None, gate=None, quick_seconds=QUICK_SECONDS):
        stream, runs = scripted(name, gate)
        app = make_app(stream=stream, quick=quick, mode=CoachMode(), log=self.logs.append, quick_seconds=quick_seconds)
        return TestClient(app, base_url="http://localhost"), runs

    def ask(self, client, *, stream=True):
        return client.post("/api/search", headers=STREAM if stream else {}, json={"question": QUESTION})

    def ask_held(self, client, gate, before_opening=join_quick):
        """Ask with the coach held at its gate; open it once before_opening() returns."""
        answered = {}
        worker = threading.Thread(target=lambda: answered.update(r=self.ask(client)))
        worker.start()
        self.assertTrue(gate.entered.wait(5))
        before_opening()
        gate.opened.set()
        worker.join(5)
        return lines(answered["r"])

    def without_quick(self, name="two_verified_filled", *, stream=True):
        client, _ = self.client(name)
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
        self.assertEqual(self.ask(client, stream=False).json(), self.without_quick(stream=False))
        join_quick()
        self.assertEqual(model.calls, [])
        self.assertIsNone(json.loads(self.logs[-1])["quick_ms"])

    def test_failure_lateness_and_refusal_send_no_quick_line(self):
        for label, model, seconds in (("failure", FakeModel(error=RuntimeError("down")), QUICK_SECONDS),
                                      ("late", FakeModel(delay=0.4), 0.1),
                                      ("refused", FakeModel(error=ModelProviderError("model_refused")), QUICK_SECONDS),
                                      ("declined", FakeModel('{"text": "", "note": ""}'), QUICK_SECONDS)):
            with self.subTest(label):
                gate = Gate(at=1)  # the coach waits until the quick call has ended
                client, _ = self.client(quick=QuickAnswerer(model), gate=gate, quick_seconds=seconds)
                received = self.ask_held(client, gate)
                self.assertEqual(received, self.without_quick())
                self.assertEqual(len(model.calls), 1)
                self.assertIsNone(json.loads(self.logs[-1])["quick_ms"])

    def test_a_quick_answer_after_the_first_line_is_dropped(self):
        gate = Gate(at=3)  # the continuation's first call: the first line is queued before it
        model = FakeModel(wait_for=gate.entered)
        client, _ = self.client(quick=QuickAnswerer(model), gate=gate)
        received = self.ask_held(client, gate)
        self.assertEqual([line["type"] for line in received], ["first", "final"])
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
            self.ask(injected)
            join_quick()
            self.assertEqual(calls, [])
            self.ask(local)
            join_quick()
        self.assertEqual(calls, [QUESTION])


if __name__ == "__main__":
    unittest.main()
