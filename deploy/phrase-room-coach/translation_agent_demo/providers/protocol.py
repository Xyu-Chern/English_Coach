"""The chat-model interface every provider adapter implements.

It is defined next to the coach (agents/protocol.py, agents/contracts.py), which depends only on
it; this module gives the adapters in providers/ one place to import it from.

    ObservedChatModel.complete_with_usage(system_prompt, user_payload, response_format) -> ChatCompletion
    ChatModel.complete(system_prompt, user_payload) -> str     (the translation demo)
"""

from translation_agent_demo.agents.contracts import ChatCompletion, ModelUsage
from translation_agent_demo.agents.protocol import ChatModel, ObservedChatModel

__all__ = ["ChatCompletion", "ChatModel", "ModelUsage", "ObservedChatModel"]
