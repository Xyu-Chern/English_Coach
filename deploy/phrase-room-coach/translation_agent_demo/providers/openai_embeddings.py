"""Bounded OpenAI embeddings adapter for the fixed corpus/search profile."""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import tiktoken

from ..config import _read_env_file
from .embedding_protocol import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EmbeddingBatch,
    EmbeddingError,
    validate_embedding,
)

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_ENDPOINT = _OPENAI_BASE_URL + "/embeddings"
MAX_BATCH_TEXTS = 32
MAX_INPUT_TOKENS = 8191
MAX_BATCH_TOKENS = 32768
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class OpenAIEmbeddingSettings:
    api_key: str = field(repr=False)
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key
            or any(ord(char) < 33 or ord(char) > 126 for char in self.api_key)
        ):
            raise EmbeddingError("OpenAI embedding API key must contain printable ASCII without whitespace.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 60
        ):
            raise EmbeddingError("OpenAI embedding timeout must be greater than zero and at most 60 seconds.")

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> "OpenAIEmbeddingSettings":
        path = env_file if env_file is not None else Path(__file__).resolve().parents[1] / ".env"
        try:
            values = _read_env_file(path)
        except (OSError, UnicodeError):
            raise EmbeddingError("Could not read the OpenAI embedding environment file.") from None
        values.update(os.environ)

        api_key = values.get("OPENAI_EMBEDDING_API_KEY", "").strip()
        api_key = api_key or values.get("OPENAI_API_KEY", "").strip()
        llm_base_url = values.get("LLM_BASE_URL", _OPENAI_BASE_URL).strip().rstrip("/")
        if not api_key and llm_base_url == _OPENAI_BASE_URL:
            # Reuse the translation key only when its configured provider is OpenAI.
            api_key = values.get("LLM_API_KEY", "").strip()
        if not api_key:
            raise EmbeddingError("Set OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY for OpenAI embeddings.")
        try:
            timeout = float(values.get("OPENAI_EMBEDDING_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise EmbeddingError("OPENAI_EMBEDDING_TIMEOUT_SECONDS must be a number.") from None
        return cls(api_key=api_key, timeout_seconds=timeout)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Credentials stay at the fixed official endpoint.


class OpenAIEmbeddingClient:
    """Make one bounded embedding request without retries or alternate endpoints."""

    model = EMBEDDING_MODEL
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, settings: OpenAIEmbeddingSettings) -> None:
        self._settings = settings

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed 1–32 texts; vectors are returned in the same order as the texts."""
        inputs = self._validate_inputs(texts)
        body = json.dumps({
            "model": self.model,
            "input": inputs,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            _ENDPOINT,
            data=body,
            headers={
                "Authorization": "Bearer " + self._settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=self._settings.timeout_seconds,
            ) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise EmbeddingError(
                f"OpenAI embeddings returned HTTP {code}; no retry was made.", status_code=code,
            ) from None
        except (URLError, OSError, HTTPException):
            raise EmbeddingError("Could not read the OpenAI embedding response; no retry was made.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise EmbeddingError("OpenAI embedding response exceeded the 8 MiB limit.")
        return self._decode_batch(raw, len(inputs))

    @staticmethod
    def _validate_inputs(texts: Sequence[str]) -> list[str]:
        if (
            not isinstance(texts, Sequence)
            or isinstance(texts, (str, bytes, bytearray))
            or not 1 <= len(texts) <= MAX_BATCH_TEXTS
        ):
            raise ValueError("Provide between 1 and 32 texts to embed.")
        inputs = list(texts)
        for text in inputs:
            if not isinstance(text, str) or not text.strip() or "\x00" in text:
                raise ValueError("Embedding texts must be nonblank strings without NUL characters.")
            try:
                text.encode("utf-8")
            except UnicodeError:
                raise ValueError("Embedding texts must be valid UTF-8.") from None
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except (OSError, RuntimeError, ValueError):
            raise EmbeddingError("The OpenAI embedding tokenizer is unavailable.") from None
        total_tokens = 0
        for text in inputs:
            # Literal special-token spellings in transcript text remain ordinary text.
            count = len(encoding.encode_ordinary(text))
            if count > MAX_INPUT_TOKENS:
                raise ValueError("An embedding text exceeded the 8191-token limit.")
            total_tokens += count
            if total_tokens > MAX_BATCH_TOKENS:
                raise ValueError("Embedding texts exceeded the 32768-token batch limit.")
        return inputs

    def _decode_batch(self, raw: bytes, count: int) -> EmbeddingBatch:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise EmbeddingError("OpenAI embeddings returned invalid JSON.") from None
        if not isinstance(payload, dict) or payload.get("model") != self.model:
            raise EmbeddingError("OpenAI embeddings returned an unexpected model or response envelope.")
        records = payload.get("data")
        usage = payload.get("usage")
        if not isinstance(records, list) or len(records) != count or not isinstance(usage, dict):
            raise EmbeddingError("OpenAI embeddings returned invalid data or usage metadata.")
        input_tokens = usage.get("prompt_tokens")
        if type(input_tokens) is not int or not 0 <= input_tokens <= MAX_BATCH_TOKENS:
            raise EmbeddingError("OpenAI embeddings returned invalid token usage.")

        vectors: dict[int, tuple[float, ...]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise EmbeddingError("OpenAI embeddings returned an invalid embedding record.")
            index = record.get("index")
            if type(index) is not int or not 0 <= index < count or index in vectors:
                raise EmbeddingError("OpenAI embeddings returned invalid or duplicate input indexes.")
            try:
                vectors[index] = validate_embedding(record.get("embedding"), dimensions=self.dimensions)
            except ValueError:
                raise EmbeddingError("OpenAI embeddings returned an invalid vector.") from None
        return EmbeddingBatch(
            model=self.model,
            dimensions=self.dimensions,
            vectors=tuple(vectors[index] for index in range(count)),
            input_tokens=input_tokens,
        )
