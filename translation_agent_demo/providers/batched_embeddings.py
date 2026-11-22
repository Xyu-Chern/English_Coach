"""One request's embedding provider that embeds a sequential first stage's queries in one call ahead (prefetch, via
session.prefetching; the parallel stage and the evaluation never prefetch) and serves each held text once. Anything
else goes to the provider as before; the batch's input tokens are reported by the first search served from it."""

import threading
from collections.abc import Sequence

from .embedding_protocol import EmbeddingBatch, EmbeddingProvider


class PrefetchedEmbeddings:
    def __init__(self, provider: EmbeddingProvider):
        self.provider, self._lock = provider, threading.Lock()
        self._held: dict[str, tuple[tuple[float, ...], int | None]] = {}  # text -> (vector, tokens not yet reported)

    model = property(lambda self: self.provider.model)
    dimensions = property(lambda self: self.provider.dimensions)

    def prefetch(self, texts: Sequence[str]) -> None:
        """Embed the texts not held yet in one provider call; raises what the provider raises."""
        with self._lock:
            wanted = list(dict.fromkeys(text for text in texts if text not in self._held))
        if not wanted:
            return
        batch = self.provider.embed_texts(tuple(wanted))
        if batch.model != self.model or batch.dimensions != self.dimensions or len(batch.vectors) != len(wanted):
            return  # an inconsistent batch is not kept
        with self._lock:
            for position, (text, vector) in enumerate(zip(wanted, batch.vectors)):
                tokens = batch.input_tokens if position == 0 or batch.input_tokens is None else 0
                self._held.setdefault(text, (vector, tokens))

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not isinstance(texts, (str, bytes)) and len(texts) == 1:
            with self._lock:
                held = self._held.get(texts[0])
                if held is not None:
                    vector, tokens = held
                    self._held[texts[0]] = (vector, 0 if tokens is not None else None)  # reported once
                    return EmbeddingBatch(self.model, self.dimensions, (vector,), tokens)
        return self.provider.embed_texts(texts)
