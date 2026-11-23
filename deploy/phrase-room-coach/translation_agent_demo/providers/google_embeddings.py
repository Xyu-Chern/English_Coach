"""Google Gemini's synchronous text embedding endpoint, at the corpus dimension."""

import json
from collections.abc import Sequence
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .embedding_protocol import EMBEDDING_DIMENSIONS, EmbeddingBatch, EmbeddingError, validate_embedding
from .openai_embeddings import MAX_RESPONSE_BYTES, _NoRedirect


class GoogleEmbeddingClient:
    model = "gemini-embedding-2"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, api_key: str):
        if not api_key or not api_key.isascii() or not all(33 <= ord(c) <= 126 for c in api_key):
            raise EmbeddingError("Set a valid GEMINI_API_KEY for Google embeddings.")
        self._key = api_key

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        if isinstance(texts, (str, bytes)) or not 1 <= len(texts) <= 32:
            raise ValueError("Provide 1 to 32 texts.")
        requests = []
        for text in texts:
            if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text.encode()) > 32768:
                raise ValueError("Expected nonblank UTF-8 text of at most 32 KiB.")
            requests.append({"model": "models/" + self.model, "content": {"parts": [{"text": text}]},
                             "outputDimensionality": self.dimensions})
        request = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
                          data=json.dumps({"requests": requests}).encode(),
                          headers={"Content-Type": "application/json", "x-goog-api-key": self._key})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            raise EmbeddingError(f"Google embeddings returned HTTP {exc.code}.", status_code=exc.code) from None
        except (URLError, OSError, HTTPException):
            raise EmbeddingError("Could not reach Google embeddings.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise EmbeddingError("Oversized Google embeddings response.")
        try:
            records = json.loads(raw)["embeddings"]
            if not isinstance(records, list) or len(records) != len(requests):
                raise ValueError
            vectors = tuple(validate_embedding(r["values"], dimensions=self.dimensions) for r in records)
        except (KeyError, TypeError, ValueError, RecursionError):
            raise EmbeddingError("Invalid Google embeddings response.") from None
        # batchEmbedContents does not guarantee an input token count.
        return EmbeddingBatch(self.model, self.dimensions, vectors, None)
