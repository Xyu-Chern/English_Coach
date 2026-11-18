"""Record every model call of an attempt (messages in, content out), never headers or secrets.

A failed call keeps the provider's error text (shortened) and request id, so a failed
smoke run can be diagnosed from model_events alone; provider errors carry no key or header."""

import hashlib
import json
import time
from dataclasses import asdict

from translation_agent_demo.agents.contracts import ChatCompletion

DETAIL_CHARS = 400


class RecordingModel:
    """Wraps a chat model and keeps one event per call, so an attempt can be replayed later."""

    def __init__(self, model, clock=time.perf_counter):
        self.model, self.clock = model, clock
        self.events: list[dict] = []

    def complete_with_usage(self, *, system_prompt: str, user_payload: str,
                            response_format: dict | None = None) -> ChatCompletion:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_payload}]
        event = {"call_index": len(self.events) + 1, "request_messages": messages,
                 "request_sha256": _sha(json.dumps(messages, ensure_ascii=False, separators=(",", ":"))),
                 "response_schema": (response_format or {}).get("json_schema", {}).get("name"),
                 "response_schema_sha256": _sha(json.dumps(response_format, sort_keys=True)) if response_format else None}
        started = self.clock()
        try:
            response = self.model.complete_with_usage(system_prompt=system_prompt, user_payload=user_payload,
                                                      response_format=response_format)
            if not isinstance(response, ChatCompletion) or not isinstance(response.content, str):
                raise TypeError("Invalid chat response contract.")
        except Exception as exc:  # a provider code (e.g. model_refused) says the model answered but unusably
            self.events.append({**event, "status": "error", "error_code": getattr(exc, "code", "model_unavailable"),
                                "error_detail": str(exc)[:DETAIL_CHARS], "request_id": getattr(exc, "request_id", None),
                                "response_content": None, "model": None, "usage": None,
                                "elapsed_ms": (self.clock() - started) * 1000})
            raise
        self.events.append({**event, "status": "ok", "error_code": None, "response_content": response.content,
                            "response_sha256": _sha(response.content), "model": response.model,
                            "usage": asdict(response.usage), "elapsed_ms": (self.clock() - started) * 1000})
        return response


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
