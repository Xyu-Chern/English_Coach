import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import Settings
from ..errors import ModelProviderError
from .protocol import ChatCompletion, ModelUsage


class OpenAICompatibleChatModel:
    """Minimal Chat Completions adapter using only Python's standard library."""

    def __init__(self, settings: Settings, *, max_completion_tokens: int | None = None) -> None:
        if max_completion_tokens is not None and (
            type(max_completion_tokens) is not int or max_completion_tokens < 1
        ):
            raise ValueError("max_completion_tokens must be a positive integer.")
        self._settings = settings
        self._max_completion_tokens = max_completion_tokens

    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        return self.complete_with_usage(system_prompt=system_prompt, user_payload=user_payload).content

    def complete_with_usage(self, *, system_prompt: str, user_payload: str,
                            response_format: dict | None = None) -> ChatCompletion:
        """response_format defaults to JSON mode; evaluation judges may pass a strict JSON schema."""
        url = f"{self._settings.base_url}/chat/completions"
        body = {
            "model": self._settings.model,
            "temperature": 0,
            "response_format": response_format or {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
        if self._max_completion_tokens is not None:
            body["max_completion_tokens"] = self._max_completion_tokens
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"

        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._settings.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise ModelProviderError(f"Model provider returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ModelProviderError("Could not connect to the model provider.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("Model provider returned an invalid response.") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("Model provider response is missing message content.") from exc

        if isinstance(content, str):
            return self._completion(content, payload)
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            combined = "".join(text_parts)
            if combined:
                return self._completion(combined, payload)

        raise ModelProviderError("Model provider returned unsupported message content.")

    def _completion(self, content: str, payload: dict) -> ChatCompletion:
        usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}

        def count(value: object) -> int | None:
            return value if type(value) is int and value >= 0 else None

        input_tokens = count(usage.get("prompt_tokens"))
        cached_tokens = count(details.get("cached_tokens"))
        if input_tokens is None or cached_tokens is not None and cached_tokens > input_tokens:
            cached_tokens = None
        model = payload.get("model")
        return ChatCompletion(
            content=content,
            usage=ModelUsage(input_tokens, count(usage.get("completion_tokens")), cached_tokens),
            model=model if isinstance(model, str) else self._settings.model,
        )
