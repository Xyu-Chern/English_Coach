"""Chat-model interface over the official Python SDK's Responses API."""

import time

import openai

from ..errors import ModelProviderError
from .protocol import ChatCompletion, ModelUsage


class RetryableGatewayError(ModelProviderError):
    """The gateway reports a temporary failure for this model call."""


TRANSIENT_CODES = {"gateway_concurrency_limit", "upstream_error", "server_error"}


class ResponsesModel:
    def __init__(self, settings, *, max_output_tokens=None):
        self.model = settings.model
        self.cap = max_output_tokens
        if not settings.api_key:
            raise ValueError("Set RESPONSES_API_KEY.")
        self.client = openai.OpenAI(
            api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_seconds,
            max_retries=0, http_client=openai.DefaultHttpxClient(follow_redirects=False),
        )

    def complete(self, *, system_prompt, user_payload):
        return self.complete_with_usage(system_prompt=system_prompt, user_payload=user_payload).content

    def complete_with_usage(self, *, system_prompt, user_payload, response_format=None):
        for delay in (0, 30, 60):
            if delay:
                time.sleep(delay)
            try:
                return self._request(system_prompt, user_payload, response_format)
            except RetryableGatewayError:
                if delay == 60:
                    raise

    def _request(self, system_prompt, user_payload, response_format):
        fmt = response_format or {"type": "json_object"}
        if fmt["type"] == "json_schema":
            fmt = {"type": "json_schema", **fmt["json_schema"]}
        options = {"max_output_tokens": self.cap} if self.cap is not None else {}
        try:
            with self.client.responses.create(
                model=self.model, instructions=system_prompt, input=user_payload, store=False,
                text={"format": fmt}, stream=True, **options,
            ) as stream:
                result = None
                for event in stream:
                    if event.type in {"response.completed", "response.failed", "response.incomplete"}:
                        result = event.response
                        break
                    if event.type == "error":
                        if event.code in TRANSIENT_CODES:
                            raise RetryableGatewayError(f"Responses stream error ({event.code}).")
                        raise ModelProviderError(f"Responses stream error ({event.code}).")
        except openai.APIStatusError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            error = body.get("error")
            code = body.get("code") or (error.get("code") if isinstance(error, dict) else None)
            if code in TRANSIENT_CODES or exc.status_code in {502, 503, 504, 524}:
                raise RetryableGatewayError(f"Responses HTTP {exc.status_code} ({code or 'gateway unavailable'}).") from exc
            raise ModelProviderError(f"Responses HTTP {exc.status_code} ({code or 'no error code'}).") from exc
        except openai.APIConnectionError as exc:
            raise ModelProviderError(f"Responses connection failed ({type(exc).__name__}).") from exc
        if result is None:
            raise ModelProviderError("Responses stream ended without a final status.")
        if result.status != "completed" or not result.output_text.strip():
            reason = getattr(result.error, "code", None) or getattr(result.incomplete_details, "reason", None)
            if reason in TRANSIENT_CODES:
                raise RetryableGatewayError(f"Responses returned {result.status} ({reason}).")
            raise ModelProviderError(f"Responses returned {result.status} ({reason or 'no usable text'}).")
        usage = result.usage
        counts = ModelUsage(
            usage.input_tokens, usage.output_tokens, getattr(usage.input_tokens_details, "cached_tokens", None)
        ) if usage else ModelUsage()
        return ChatCompletion(result.output_text, counts, result.model or self.model)
