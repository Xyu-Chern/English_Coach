"""Provider usage observation must not change the existing translation contract."""

import io
import json
import unittest
from unittest.mock import patch

from translation_agent_demo.config import Settings
from translation_agent_demo.providers.openai_compatible import OpenAICompatibleChatModel


class ModelUsageTests(unittest.TestCase):
    def test_observed_completion_records_real_counts_and_optional_output_budget(self):
        payload = {"model": "provider-model", "choices": [{"message": {"content": "hello"}}],
                   "usage": {"prompt_tokens": 20, "completion_tokens": 5,
                             "prompt_tokens_details": {"cached_tokens": 10}}}
        model = OpenAICompatibleChatModel(Settings("https://example.test/v1", "configured-model", None),
                                          max_completion_tokens=500)
        with patch("translation_agent_demo.providers.openai_compatible.urlopen",
                   return_value=io.BytesIO(json.dumps(payload).encode())) as send:
            response = model.complete_with_usage(system_prompt="system", user_payload="data")
        self.assertEqual((response.content, response.model), ("hello", "provider-model"))
        self.assertEqual((response.usage.input_tokens, response.usage.output_tokens, response.usage.cached_input_tokens),
                         (20, 5, 10))
        self.assertEqual(json.loads(send.call_args.args[0].data)["max_completion_tokens"], 500)

    def test_legacy_content_and_missing_or_invalid_usage_remain_compatible(self):
        model = OpenAICompatibleChatModel(Settings("https://example.test/v1", "model", None))
        for usage in (None, {"prompt_tokens": True, "completion_tokens": -1}):
            payload = {"choices": [{"message": {"content": [{"text": "hello"}, {"text": " world"}]}}], "usage": usage}
            with self.subTest(usage=usage), patch("translation_agent_demo.providers.openai_compatible.urlopen",
                    return_value=io.BytesIO(json.dumps(payload).encode())) as send:
                response = model.complete_with_usage(system_prompt="system", user_payload="data")
            self.assertEqual(response.content, "hello world")
            self.assertIsNone(response.usage.input_tokens)
            self.assertIsNone(response.usage.output_tokens)
            self.assertNotIn("max_completion_tokens", json.loads(send.call_args.args[0].data))
        with patch("translation_agent_demo.providers.openai_compatible.urlopen",
                   return_value=io.BytesIO(json.dumps(payload).encode())):
            self.assertEqual(model.complete(system_prompt="system", user_payload="data"), "hello world")


if __name__ == "__main__":
    unittest.main()
