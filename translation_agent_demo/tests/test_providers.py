"""chat_model picks the adapter from the settings; both implement the same interface."""

import unittest

from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.anthropic_chat import AnthropicChatModel
from translation_agent_demo.providers.openai_compatible import OpenAICompatibleChatModel

OPENAI = {"LLM_API_KEY": "test-key", "LLM_MODEL": "gpt-5.4-mini"}
CLAUDE = {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key", "LLM_MODEL": "claude-haiku-5-5"}


class ChatModelTests(unittest.TestCase):
    def test_the_provider_setting_picks_the_adapter(self):
        for values, adapter in ((OPENAI, OpenAICompatibleChatModel), (CLAUDE, AnthropicChatModel)):
            with self.subTest(provider=values.get("LLM_PROVIDER", "openai")):
                model = chat_model(Settings.from_values(values))
                self.assertIsInstance(model, adapter)
                self.assertTrue(callable(model.complete_with_usage))

    def test_the_reply_cap_reaches_each_adapter(self):
        self.assertEqual(chat_model(Settings.from_values(OPENAI), max_output_tokens=1200)._max_completion_tokens, 1200)
        self.assertEqual(chat_model(Settings.from_values(CLAUDE), max_output_tokens=16000)._max_tokens, 16000)


if __name__ == "__main__":
    unittest.main()
