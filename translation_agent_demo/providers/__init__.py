"""Adapters to outside services: chat models, embeddings and podcast sources.

Chat models: every adapter implements the same interface (protocol.py), so the coach and the
evaluation never depend on a provider. chat_model picks the adapter from the settings
(LLM_PROVIDER in .env: "openai", the default, or "anthropic"):

    openai_compatible.py   OpenAI-compatible Chat Completions (strict JSON Schema via response_format)
    anthropic_chat.py      Claude Messages API (the same schema sent as output_config.format)
"""

from ..config import Settings
from .protocol import ObservedChatModel


def chat_model(settings: Settings, *, max_output_tokens: int | None = None) -> ObservedChatModel:
    """The chat model for settings.provider. max_output_tokens: the reply cap (provider default when None)."""
    if settings.provider == "anthropic":
        from .anthropic_chat import AnthropicChatModel  # the SDK is only needed when Claude is used
        return AnthropicChatModel(settings, max_tokens=max_output_tokens)
    from .openai_compatible import OpenAICompatibleChatModel
    return OpenAICompatibleChatModel(settings, max_completion_tokens=max_output_tokens)
