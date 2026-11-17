"""Claude Messages adapter with the same contract as the OpenAI-compatible adapter.

Callers pass the OpenAI-style strict response_format that agents/structured.py builds. It is
sent as output_config.format after the SDK's own schema transform: Claude's JSON Schema
subset has no numeric, string-length or maxItems constraints, so those move into field
descriptions, and Pydantic still enforces them after decoding.

Current Claude models reject non-default sampling parameters, so temperature is never sent.
Thinking stays adaptive (the model default) and counts toward max_tokens, which is why the
default cap is generous. Settings.effort, when set, becomes output_config.effort.
"""

import anthropic

from ..config import Settings
from ..errors import ConfigurationError, ModelProviderError
from .protocol import ChatCompletion, ModelUsage

DEFAULT_MAX_TOKENS = 16000
DETAIL_CHARS = 300  # API error text kept for diagnosis; it describes the request's problem, not its content
_TRUNCATED = {"max_tokens", "model_context_window_exceeded"}


class ClaudeCallError(ModelProviderError):
    """A failed Claude call with a stable code.

    model_unavailable is an infrastructure failure (rate limit, overload, 5xx, network, or a
    rejected request). model_refused, model_output_truncated and invalid_model_output mean the
    model answered but the answer cannot be used. For an HTTP error the API's own message,
    status and request id are kept, so a bad model id, a missing credit or a rejected schema
    can be told apart from a rate limit without rerunning anything."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.code, self.status_code, self.request_id = code, status_code, request_id


def output_format(response_format: dict | None) -> dict | None:
    """OpenAI response_format -> Claude output_config.format; JSON mode has no Claude equivalent."""
    if response_format is None or response_format.get("type") == "json_object":
        return None
    if response_format.get("type") != "json_schema":
        raise ValueError("Only json_schema response formats can be sent to Claude.")
    return {"type": "json_schema", "schema": anthropic.transform_schema(response_format["json_schema"]["schema"])}


class AnthropicChatModel:
    """One Messages API call per completion, through the official SDK (which owns the retries)."""

    def __init__(self, settings: Settings, *, max_tokens: int | None = None, client=None) -> None:
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
            raise ValueError("max_tokens must be a positive integer.")
        if client is None:
            if not settings.api_key:
                raise ConfigurationError("Set ANTHROPIC_API_KEY to use a Claude model.")
            client = anthropic.Anthropic(api_key=settings.api_key, base_url=settings.base_url,
                                         timeout=settings.timeout_seconds, max_retries=settings.max_retries)
        self._settings, self._client = settings, client
        self._max_tokens = max_tokens or DEFAULT_MAX_TOKENS

    def complete(self, *, system_prompt: str, user_payload: str) -> str:
        return self.complete_with_usage(system_prompt=system_prompt, user_payload=user_payload).content

    def complete_with_usage(self, *, system_prompt: str, user_payload: str,
                            response_format: dict | None = None) -> ChatCompletion:
        request = self._request(system_prompt, user_payload, response_format)
        try:
            message = self._client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise _status_error(exc) from exc
        except anthropic.APIError as exc:  # connection, timeout or an unreadable response
            raise ClaudeCallError("model_unavailable", f"Could not reach the Claude API ({type(exc).__name__}).") from exc
        return self._completion(message)

    def _request(self, system_prompt: str, user_payload: str, response_format: dict | None) -> dict:
        request = {"model": self._settings.model, "max_tokens": self._max_tokens, "system": system_prompt,
                   "messages": [{"role": "user", "content": user_payload}]}
        output_config = {}
        schema_format = output_format(response_format)
        if schema_format:
            output_config["format"] = schema_format
        if self._settings.effort:
            output_config["effort"] = self._settings.effort
        if output_config:
            request["output_config"] = output_config
        return request

    def _completion(self, message) -> ChatCompletion:
        """Branch on stop_reason before reading content: a refusal or a cut-off reply may not match the schema."""
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) or "unspecified"
            raise ClaudeCallError("model_refused", f"Claude declined the request (category: {category}).")
        if message.stop_reason in _TRUNCATED:
            raise ClaudeCallError("model_output_truncated",
                                  f"Claude stopped at {message.stop_reason} (max_tokens={self._max_tokens}).")
        # Adaptive thinking can put thinking blocks first; the answer is the first text block.
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise ClaudeCallError("invalid_model_output", "Claude returned no text block.")
        model = getattr(message, "model", None)
        return ChatCompletion(content=text, usage=_usage(getattr(message, "usage", None)),
                              model=model if isinstance(model, str) else self._settings.model)


def _status_error(exc: anthropic.APIStatusError) -> ClaudeCallError:
    """HTTP status, error type, the API's message (shortened) and the request id, all in one line."""
    kind = getattr(exc, "type", None) or "error"
    detail = " ".join(str(getattr(exc, "api_message", None) or "").split())[:DETAIL_CHARS]
    request_id = getattr(exc, "request_id", None)
    text = f"Claude API returned HTTP {exc.status_code} ({kind})" + (f": {detail}" if detail else "")
    return ClaudeCallError("model_unavailable", text + (f" [request_id {request_id}]" if request_id else "") + ".",
                           status_code=exc.status_code, request_id=request_id)


def _usage(usage) -> ModelUsage:
    """Claude's input_tokens excludes cache reads and writes; ModelUsage counts the whole prompt.

    Cache reads are the cached share. No request sets cache_control, so cache writes stay zero;
    if any appear they are counted as ordinary input."""

    def count(name: str) -> int | None:
        value = getattr(usage, name, None)
        return value if type(value) is int and value >= 0 else None

    fresh, output = count("input_tokens"), count("output_tokens")
    if fresh is None:
        return ModelUsage(output_tokens=output)
    read, written = count("cache_read_input_tokens") or 0, count("cache_creation_input_tokens") or 0
    return ModelUsage(input_tokens=fresh + read + written, output_tokens=output, cached_input_tokens=read)
