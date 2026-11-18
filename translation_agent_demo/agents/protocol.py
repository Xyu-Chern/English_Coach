"""Interfaces the coach depends on; adapters (OpenAI, pgvector, snapshots) implement them."""

from typing import Callable, Protocol

from .contracts import ChatCompletion, SearchCorpusArgs, SearchCorpusResult


class ChatModel(Protocol):
    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        """Return the model's raw response content."""


class ObservedChatModel(Protocol):
    def complete_with_usage(self, *, system_prompt: str, user_payload: str,
                            response_format: dict | None = None) -> ChatCompletion:
        """Return content with optional provider-reported usage.

        response_format, when given, is a strict JSON Schema the provider must decode against."""


SearchCorpus = Callable[[SearchCorpusArgs], SearchCorpusResult]
"""The read-only corpus search tool: typed arguments in, ranked passages out."""
