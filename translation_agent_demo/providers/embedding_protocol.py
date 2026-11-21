"""Shared embedding profile and the small interface used by storage and search."""

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
_FLOAT32_MAX = float.fromhex("0x1.fffffep+127")


class EmbeddingError(Exception):
    """Safe provider failure without credentials, input text, or response bodies."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EmbeddingBatch:
    model: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...] = field(repr=False)
    input_tokens: int | None


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Return one vector for each input, preserving the input order."""


def validate_embedding(
    vector: Sequence[float], *, dimensions: int = EMBEDDING_DIMENSIONS,
) -> tuple[float, ...]:
    """Validate and round a nonzero vector to pgvector's float32 representation."""
    if type(dimensions) is not int or dimensions < 1:
        raise ValueError("Embedding dimensions must be a positive integer.")
    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes, bytearray))
        or len(vector) != dimensions
    ):
        raise ValueError("Embedding vector has an invalid length or type.")

    values: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Embedding values must be finite numbers.")
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise ValueError("Embedding values must fit in float32.") from None
        if not math.isfinite(number) or abs(number) > _FLOAT32_MAX:
            raise ValueError("Embedding values must be finite and fit in float32.")
        # Validate the values PostgreSQL will store, including underflow to zero.
        values.append(struct.unpack("!f", struct.pack("!f", number))[0])
    if not any(values):
        raise ValueError("Embedding vector must not be zero.")
    return tuple(values)
