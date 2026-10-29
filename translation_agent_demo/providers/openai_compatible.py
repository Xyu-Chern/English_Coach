import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import Settings
from ..errors import ModelProviderError


class OpenAICompatibleChatModel:
    """Minimal Chat Completions adapter using only Python's standard library."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        url = f"{self._settings.base_url}/chat/completions"
        body = {
            "model": self._settings.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
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
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            combined = "".join(text_parts)
            if combined:
                return combined

        raise ModelProviderError("Model provider returned unsupported message content.")
