"""Gemini's Chat Completions endpoint with optional per-process pacing."""

import threading
import time

from ..config import ConfigurationError, environment_values
from .openai_compatible import OpenAICompatibleChatModel


class GoogleChatModel(OpenAICompatibleChatModel):
    def __init__(self, settings, *, max_completion_tokens=None):
        super().__init__(settings, max_completion_tokens=max_completion_tokens)
        try:
            rpm = int(environment_values().get("GEMINI_CHAT_RPM") or 0)
        except ValueError:
            raise ConfigurationError("GEMINI_CHAT_RPM must be a nonnegative integer.") from None
        if rpm < 0:
            raise ConfigurationError("GEMINI_CHAT_RPM must be a nonnegative integer.")
        self.interval = 60 / rpm if rpm else 0
        self.next_call = 0.0
        self.lock = threading.Lock()

    def complete_with_usage(self, **kwargs):
        if self.interval:
            with self.lock:
                now = time.monotonic()
                start = max(now, self.next_call)
                self.next_call = start + self.interval
            time.sleep(start - now)
        return super().complete_with_usage(**kwargs)
