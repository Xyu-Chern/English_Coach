"""The Claude adapter keeps the chat contract; every call is served by a mocked HTTP transport."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import anthropic
import httpx2
from pydantic import BaseModel, Field

from translation_agent_demo.agents.schemas.agent import AgentDecision, FinalPick
from translation_agent_demo.agents.schemas.baseline import Revision
from translation_agent_demo.agents.schemas.prefix import CandidateSet, Selection
from translation_agent_demo.agents.structured import response_format
from translation_agent_demo.config import Settings, settings_for
from translation_agent_demo.errors import ConfigurationError
from translation_agent_demo.providers.anthropic_chat import (DEFAULT_MAX_TOKENS, AnthropicChatModel, ClaudeCallError,
                                                             output_format)
from translation_agent_demo.providers.openai_embeddings import OpenAIEmbeddingSettings

CLAUDE_ENV = {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-haiku-5-5", "ANTHROPIC_API_KEY": "claude-key"}


class Reply(BaseModel):
    rank: int = Field(ge=0, le=20)
    picks: tuple[str, ...] = Field(max_length=6)


def message(*content, stop_reason="end_turn", usage=None, **extra) -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": list(content), "stop_reason": stop_reason, "stop_sequence": None,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5}, **extra}


def text(value: str) -> dict:
    return {"type": "text", "text": value}


class Transport:
    """Replies in order and keeps every request body the SDK sent."""

    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body, headers = (*reply, {})[:3] if isinstance(reply, tuple) else (200, reply, {})
        return httpx2.Response(status, json=body, headers=headers)


def claude(transport: Transport, **settings) -> AnthropicChatModel:
    client = anthropic.Anthropic(api_key="claude-key", base_url="https://api.anthropic.test", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(transport)))
    return AnthropicChatModel(Settings.from_values({**CLAUDE_ENV, **settings}), client=client)


class AnthropicChatModelTests(unittest.TestCase):
    def test_structured_reply_after_a_thinking_block_maps_content_usage_and_request(self):
        transport = Transport(message({"type": "thinking", "thinking": "", "signature": "sig"}, text('{"ok": true}'),
                                      usage={"input_tokens": 100, "output_tokens": 40,
                                             "cache_read_input_tokens": 30, "cache_creation_input_tokens": 5}))
        model = claude(transport, LLM_EFFORT="low")
        reply = model.complete_with_usage(system_prompt="rules", user_payload='{"q": 1}',
                                          response_format=response_format(Reply))

        self.assertEqual((reply.content, reply.model), ('{"ok": true}', "claude-haiku-5-5"))
        self.assertEqual((reply.usage.input_tokens, reply.usage.output_tokens, reply.usage.cached_input_tokens),
                         (135, 40, 30))
        body = transport.bodies[0]
        self.assertEqual((body["model"], body["max_tokens"], body["system"]), ("claude-haiku-5-5", DEFAULT_MAX_TOKENS, "rules"))
        self.assertEqual(body["messages"], [{"role": "user", "content": '{"q": 1}'}])
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual(body["output_config"]["format"], output_format(response_format(Reply)))
        self.assertFalse({"temperature", "top_p", "top_k", "thinking"} & set(body))

    def test_no_schema_and_no_effort_send_no_output_config(self):
        transport = Transport(message(text("plain")))
        self.assertEqual(claude(transport).complete(system_prompt="s", user_payload="u"), "plain")
        self.assertNotIn("output_config", transport.bodies[0])

    def test_refusal_truncation_and_missing_text_are_model_errors_not_infrastructure(self):
        cases = [(message(text("{"), stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"}),
                  "model_refused", "cyber"),
                 (message(text('{"partial'), stop_reason="max_tokens"), "model_output_truncated", "max_tokens"),
                 (message({"type": "thinking", "thinking": "", "signature": "sig"}), "invalid_model_output", "text")]
        for reply, code, detail in cases:
            with self.subTest(code=code), self.assertRaises(ClaudeCallError) as raised:
                claude(Transport(reply)).complete(system_prompt="s", user_payload="u")
            self.assertEqual(raised.exception.code, code)
            self.assertIn(detail, str(raised.exception))

    def test_rate_limit_overload_and_connection_failures_are_model_unavailable(self):
        error = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
        overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
        for reply, detail in (((429, error), "HTTP 429 (rate_limit_error)"), ((529, overloaded), "HTTP 529"),
                              (httpx2.ConnectError("refused"), "APIConnectionError")):
            with self.subTest(detail=detail), self.assertRaises(ClaudeCallError) as raised:
                claude(Transport(reply)).complete(system_prompt="s", user_payload="u")
            self.assertEqual(raised.exception.code, "model_unavailable")
            self.assertIn(detail, str(raised.exception))

    def test_an_http_error_keeps_the_api_message_status_and_request_id(self):
        """A rejected schema, a bad model id and a rate limit must be distinguishable from the record."""
        error = {"type": "error", "error": {"type": "invalid_request_error",
                                            "message": "Schema is too complex for compilation."}}
        with self.assertRaises(ClaudeCallError) as raised:
            claude(Transport((400, error, {"request-id": "req_123"}))).complete(system_prompt="s", user_payload="u")
        failure = raised.exception
        self.assertEqual((failure.code, failure.status_code, failure.request_id), ("model_unavailable", 400, "req_123"))
        self.assertEqual(str(failure), "Claude API returned HTTP 400 (invalid_request_error): "
                                       "Schema is too complex for compilation. [request_id req_123].")

    def test_client_takes_timeout_and_retries_from_settings_and_requires_its_own_key(self):
        model = AnthropicChatModel(Settings.from_values({**CLAUDE_ENV, "LLM_TIMEOUT_SECONDS": "45",
                                                         "LLM_MAX_RETRIES": "2"}))
        self.assertEqual((model._client.timeout, model._client.max_retries), (45.0, 2))
        with self.assertRaises(ConfigurationError):
            AnthropicChatModel(Settings.from_values({**CLAUDE_ENV, "ANTHROPIC_API_KEY": ""}))


class ClaudeSettingsTests(unittest.TestCase):
    def test_claude_settings_never_reuse_the_openai_endpoint_or_key(self):
        settings = Settings.from_values({**CLAUDE_ENV, "LLM_BASE_URL": "https://api.openai.com/v1",
                                         "LLM_API_KEY": "openai-key", "LLM_EFFORT": "Medium"})
        self.assertEqual((settings.provider, settings.base_url, settings.api_key, settings.effort, settings.max_retries),
                         ("anthropic", "https://api.anthropic.com", "claude-key", "medium", 4))
        for bad in ({"LLM_EFFORT": "extreme"}, {"LLM_PROVIDER": "gemini"}, {"LLM_MAX_RETRIES": "11"}):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                Settings.from_values({**CLAUDE_ENV, **bad})

    def test_claude_gets_a_longer_default_timeout_than_openai(self):
        """Adaptive thinking plus SDK retries: 30 s would abandon (and may still bill) slow agent turns."""
        self.assertEqual(Settings.from_values(CLAUDE_ENV).timeout_seconds, 120.0)
        self.assertEqual(Settings.from_values({**CLAUDE_ENV, "LLM_TIMEOUT_SECONDS": "45"}).timeout_seconds, 45.0)
        openai_chat = {"LLM_MODEL": "gpt-5.4-mini", "LLM_API_KEY": "k", "ANTHROPIC_API_KEY": "claude-key"}
        self.assertEqual(Settings.from_values(openai_chat).timeout_seconds, 30.0)
        judge = settings_for(Settings.from_values(openai_chat), "anthropic", "claude-sonnet-5-5", values=openai_chat)
        self.assertEqual(judge.timeout_seconds, 120.0)

    def test_openai_settings_are_unchanged_and_ignore_effort(self):
        settings = Settings.from_values({"LLM_MODEL": "gpt-5.4-mini", "LLM_API_KEY": "openai-key", "LLM_EFFORT": "high"})
        self.assertEqual(settings, Settings("https://api.openai.com/v1", "gpt-5.4-mini", "openai-key"))

    def test_a_second_provider_gets_its_own_endpoint_and_key(self):
        values = {**CLAUDE_ENV, "OPENAI_API_KEY": "openai-key"}
        judge = settings_for(Settings.from_values(values), "openai", "gpt-5.4-mini-2026-03-17", effort="high",
                             values=values)
        self.assertEqual((judge.provider, judge.base_url, judge.api_key, judge.model, judge.effort),
                         ("openai", "https://api.openai.com/v1", "openai-key", "gpt-5.4-mini-2026-03-17", None))
        openai_chat = {"LLM_MODEL": "gpt-5.4-mini", "LLM_BASE_URL": "https://proxy.test/v1", "LLM_API_KEY": "chat-key",
                       "ANTHROPIC_API_KEY": "claude-key"}
        same = settings_for(Settings.from_values(openai_chat), "openai", "judge-model", values=openai_chat)
        self.assertEqual((same.base_url, same.api_key), ("https://proxy.test/v1", "chat-key"))
        sonnet = settings_for(Settings.from_values(openai_chat), "anthropic", "claude-sonnet-5-5", effort="low",
                              values=openai_chat)
        self.assertEqual((sonnet.base_url, sonnet.api_key, sonnet.effort),
                         ("https://api.anthropic.com", "claude-key", "low"))

    def test_the_translation_cli_refuses_a_claude_environment_instead_of_posting_to_it(self):
        """The demo adapter speaks Chat Completions; with LLM_PROVIDER=anthropic it would get an opaque 404."""
        from translation_agent_demo import cli
        with patch.dict(os.environ, CLAUDE_ENV, clear=True), patch.object(cli, "OpenAICompatibleChatModel") as adapter, \
                patch("sys.stderr") as stderr:
            self.assertEqual(cli.main(["안녕하세요"]), 1)
        adapter.assert_not_called()
        self.assertIn("unset LLM_PROVIDER", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_embeddings_still_find_an_openai_key_when_chat_runs_on_claude(self):
        missing = Path("/nonexistent/.env")
        for extra, key in (({"OPENAI_API_KEY": "openai-key"}, "openai-key"),
                           ({"LLM_API_KEY": "legacy-openai-key"}, "legacy-openai-key")):
            with self.subTest(key=key), patch.dict(os.environ, {**CLAUDE_ENV, **extra}, clear=True):
                self.assertEqual(OpenAIEmbeddingSettings.from_environment(env_file=missing).api_key, key)


# Claude structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
SUPPORTED_KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const", "anyOf",
                      "allOf", "$ref", "$defs", "definitions", "description", "title", "default", "format",
                      "minItems", "pattern"}
SUPPORTED_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
MAX_OPTIONAL_PARAMETERS, MAX_UNION_PARAMETERS = 24, 16


def assert_claude_schema(case: unittest.TestCase, schema: dict) -> None:
    """Fail on anything Claude's JSON Schema subset rejects or the documented complexity limits exceed."""
    counts = {"optional": 0, "union": 0}

    def walk(node: dict, where: str) -> None:
        case.assertFalse(set(node) - SUPPORTED_KEYWORDS, f"{where}: unsupported {set(node) - SUPPORTED_KEYWORDS}")
        if node.get("type") == "object":
            case.assertIs(node.get("additionalProperties"), False, where)
            counts["optional"] += len(set(node.get("properties", {})) - set(node.get("required", [])))
        case.assertIn(node.get("minItems", 0), (0, 1), where)
        case.assertIn(node.get("format", "uuid"), SUPPORTED_FORMATS, where)
        case.assertFalse(any("$ref" in part for part in node.get("allOf", [])), f"{where}: allOf with $ref")
        counts["union"] += "anyOf" in node or isinstance(node.get("type"), list)
        for name, child in {**node.get("properties", {}), **node.get("$defs", {})}.items():
            walk(child, f"{where}.{name}")
        for index, child in enumerate([*node.get("anyOf", []), *node.get("allOf", [])]):
            walk(child, f"{where}[{index}]")
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{where}[]")

    walk(schema, "$")
    case.assertLessEqual(counts["optional"], MAX_OPTIONAL_PARAMETERS)
    case.assertLessEqual(counts["union"], MAX_UNION_PARAMETERS)


class ClaudeSchemaTests(unittest.TestCase):
    def test_every_reply_schema_is_accepted_by_claude_structured_outputs(self):
        for model in (CandidateSet, Selection, Revision, AgentDecision, FinalPick):  # every reply a call asks for
            with self.subTest(model=model.__name__):
                sent = output_format(response_format(model))
                self.assertEqual(sent["type"], "json_schema")
                assert_claude_schema(self, sent["schema"])

    def test_unsupported_constraints_move_into_descriptions(self):
        sent = output_format(response_format(Reply))["schema"]
        rank, picks = sent["properties"]["rank"], sent["properties"]["picks"]
        self.assertEqual(set(rank), {"type", "description"})
        self.assertTrue({"minimum: 0", "maximum: 20"} <= set(rank["description"].strip("{}").split(", ")))
        self.assertEqual(picks["description"], "{maxItems: 6}")
        assert_claude_schema(self, sent)


if __name__ == "__main__":
    unittest.main()
