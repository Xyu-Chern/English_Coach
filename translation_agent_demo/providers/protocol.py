from typing import Protocol


class ChatModel(Protocol):
    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        """Return the model's raw response content."""
