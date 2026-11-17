"""Judge and chat provider selection; every provider call is mocked."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import anthropic
import httpx2

from evaluation.grader import PROMPTS, SCHEMAS, check_judge
from evaluation.judging import JUDGE_MODEL, Judge, JudgeConfig, judge_config, make_unit, sha
from evaluation.live import CLAUDE_MAX_TOKENS, LiveEnvironment
from translation_agent_demo.config import Settings
from translation_agent_demo.errors import ConfigurationError
from translation_agent_demo.providers.anthropic_chat import AnthropicChatModel, output_format
from translation_agent_demo.providers.openai_compatible import OpenAICompatibleChatModel
from translation_agent_demo.tests.test_anthropic_chat import assert_claude_schema

CLAUDE_CHAT = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-haiku-5-5", "LLM_EFFORT": "medium",
               "ANTHROPIC_API_KEY": "claude-key", "OPENAI_API_KEY": "openai-key"}
OPENAI_CHAT = {"LLM_MODEL": "gpt-5.4-mini", "LLM_API_KEY": "openai-key"}
SONNET = JudgeConfig("anthropic", "claude-sonnet-5-5", "low")
VERDICT = {"fits": "pass", "natural": "pass", "note_ok": "pass", "reason": "short"}


class JudgeConfigTests(unittest.TestCase):
    def test_default_judge_is_the_pinned_openai_snapshot_and_its_unit_ids_name_only_the_model(self):
        self.assertEqual(judge_config({}), JudgeConfig("openai", "gpt-5.4-mini-2026-03-17", None))
        self.assertEqual(judge_config({"JUDGE_EFFORT": "high"}).effort, None)  # effort is Claude-only
        payload = {"expression": "placeholder"}
        expected = sha(["set", sha("prompt"), sha({"type": "object"}), payload, JUDGE_MODEL])
        self.assertEqual(make_unit("set", "prompt", {"type": "object"}, payload, judge_config({}))["id"], expected)

    def test_a_claude_judge_is_chosen_only_by_environment_and_changes_every_unit_id(self):
        config = judge_config({"JUDGE_PROVIDER": "Anthropic", "JUDGE_MODEL": "claude-sonnet-5-5", "JUDGE_EFFORT": "low"})
        self.assertEqual(config, SONNET)
        ids = {make_unit("set", "prompt", {}, {}, judge)["id"]
               for judge in (JudgeConfig(), config, JudgeConfig("anthropic", "claude-sonnet-5-5"))}
        self.assertEqual(len(ids), 3)
        for bad in ({"JUDGE_PROVIDER": "anthropic"}, {"JUDGE_PROVIDER": "gemini"},
                    {"JUDGE_PROVIDER": "anthropic", "JUDGE_MODEL": "claude-sonnet-5-5", "JUDGE_EFFORT": "huge"}):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                judge_config(bad)

    def test_every_judge_schema_is_accepted_by_claude_structured_outputs(self):
        for kind, schema in SCHEMAS.items():
            with self.subTest(kind=kind):
                sent = output_format({"type": "json_schema", "json_schema": {"name": kind, "schema": schema}})
                assert_claude_schema(self, sent["schema"])


class JudgeProviderTests(unittest.TestCase):
    def test_openai_judge_uses_the_openai_key_and_url_while_chat_runs_on_claude(self):
        judge = Judge(Settings.from_values(CLAUDE_CHAT), PROMPTS, SCHEMAS, config=JudgeConfig(), values=CLAUDE_CHAT)
        reply = {"model": JUDGE_MODEL, "choices": [{"message": {"content": json.dumps(VERDICT)}}],
                 "usage": {"prompt_tokens": 50, "completion_tokens": 9}}
        with patch("translation_agent_demo.providers.openai_compatible.urlopen",
                   return_value=io.BytesIO(json.dumps(reply).encode())) as send:
            vote = judge("expression", {"expression": "placeholder"})
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer openai-key")
        self.assertEqual((body["model"], body["temperature"], body["max_completion_tokens"]), (JUDGE_MODEL, 0, 1600))
        self.assertEqual(body["response_format"]["json_schema"]["schema"], SCHEMAS["expression"])
        self.assertEqual((json.loads(vote["content"]), vote["model"], vote["usage"]["input_tokens"]), (VERDICT, JUDGE_MODEL, 50))

    def test_claude_judge_sends_the_judge_schema_effort_and_its_own_key(self):
        bodies, keys = [], []

        def transport(request):
            bodies.append(json.loads(request.content))
            keys.append(request.headers.get("x-api-key") or request.headers.get("authorization"))
            return httpx2.Response(200, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                            {"type": "text", "text": json.dumps(VERDICT)}],
                "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 70, "output_tokens": 30}})

        real_client = anthropic.Anthropic

        def client(**options):
            return real_client(**options, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(transport)))

        with patch("translation_agent_demo.providers.anthropic_chat.anthropic.Anthropic", side_effect=client):
            judge = Judge(Settings.from_values(OPENAI_CHAT), PROMPTS, SCHEMAS, config=SONNET,
                          values={**OPENAI_CHAT, "ANTHROPIC_API_KEY": "claude-key"})
            vote = judge("expression", {"expression": "placeholder"})
        self.assertIsInstance(judge.model, AnthropicChatModel)
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].endswith("claude-key"))
        self.assertEqual((bodies[0]["model"], bodies[0]["output_config"]["effort"]), ("claude-sonnet-5-5", "low"))
        self.assertEqual(bodies[0]["output_config"]["format"]["schema"]["properties"].keys(),
                         SCHEMAS["expression"]["properties"].keys())
        self.assertEqual((json.loads(vote["content"]), vote["model"], vote["usage"]["output_tokens"]),
                         (VERDICT, "claude-sonnet-5-5", 30))


class LiveWiringTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.snapshot = Path(directory.name)
        (self.snapshot / "manifest.json").write_text(json.dumps({
            "snapshot_id": "snap", "files": {"corpus.json.gz": {"sha256": "c"}},
            "profile": {"model": "text-embedding-3-small", "dimensions": 1536}}))

    def environment(self, values: dict) -> LiveEnvironment:
        with patch("translation_agent_demo.config.environment_values", return_value=values):
            return LiveEnvironment(snapshot_dir=self.snapshot)

    def test_claude_chat_records_provider_model_effort_and_timeout_without_secrets(self):
        environment = self.environment(CLAUDE_CHAT)
        identity = environment.identity()
        self.assertEqual({k: identity[k] for k in ("provider", "model", "effort", "temperature", "max_completion_tokens",
                                                   "timeout_seconds")},
                         {"provider": "anthropic", "model": "claude-haiku-5-5", "effort": "medium", "temperature": None,
                          "max_completion_tokens": CLAUDE_MAX_TOKENS, "timeout_seconds": 120.0})
        self.assertFalse({"claude-key", "openai-key"} & set(json.dumps(identity).split('"')))
        self.assertFalse(any(key.startswith("judge") for key in identity))  # the judge changes no attempt
        self.assertIsInstance(environment.chat_model(), AnthropicChatModel)

    def test_openai_chat_stays_pinned_to_the_snapshot(self):
        environment = self.environment(OPENAI_CHAT)
        identity = environment.identity()
        self.assertEqual((identity["provider"], identity["model"], identity["temperature"], identity["timeout_seconds"]),
                         ("openai", "gpt-5.4-mini-2026-03-17", 0, 30.0))
        self.assertIsInstance(environment.chat_model(), OpenAICompatibleChatModel)


class JudgeIdentityTests(unittest.TestCase):
    """The judge is outside the run's resume identity, but grading never switches judges silently."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.run_dir = Path(directory.name)
        (self.run_dir / "manifest.json").write_text(json.dumps({"judge": asdict(JudgeConfig())}))

    def test_a_judge_change_after_grading_is_refused(self):
        (self.run_dir / "grades").mkdir()
        (self.run_dir / "grades" / "manifest.json").write_text(json.dumps({"model": JUDGE_MODEL}))  # no provider: openai
        check_judge(self.run_dir, JudgeConfig())  # the same judge regrades
        with self.assertRaises(SystemExit):
            check_judge(self.run_dir, SONNET)

    def test_a_judge_other_than_the_one_at_run_start_is_reported(self):
        with redirect_stdout(io.StringIO()) as output:
            check_judge(self.run_dir, SONNET)
        self.assertEqual(json.loads(output.getvalue())["grading_with"]["model"], "claude-sonnet-5-5")


if __name__ == "__main__":
    unittest.main()
