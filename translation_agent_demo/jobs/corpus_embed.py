"""Embed a bounded batch of reviewed corpus chunks; resume missing vectors later."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from psycopg import Connection, Error as PsycopgError
from psycopg.pq import TransactionStatus

from ..config import _read_env_file
from ..corpus.chunking import ChunkingSettings
from ..providers.embedding_protocol import EmbeddingError, EmbeddingProvider
from ..providers.openai_embeddings import OpenAIEmbeddingClient, OpenAIEmbeddingSettings
from ..storage.embeddings import pending_embedding_chunks, save_embeddings
from ..storage.postgres import CorpusStorageError, PostgresSettings, connect_database

EMBED_LOCK_ID = 1162036037
MAX_CHUNKS = 32


@dataclass
class EmbedResult:
    status: Literal["ok", "idle", "already_running", "disabled"] = "ok"
    selected_chunks: int = 0
    inserted: int = 0
    completed_builds: int = 0
    input_tokens: int = 0


def embed_corpus(
    conn: Connection,
    embeddings: EmbeddingProvider,
    *,
    limit: int = MAX_CHUNKS,
    settings: ChunkingSettings = ChunkingSettings(),
) -> EmbedResult:
    """Perform at most one provider request, outside database transactions.

    The session lock prevents overlapping cron workers spending on the same
    chunks. Already stored batches survive an interruption; partially embedded
    documents stay out of search. An empty selection makes no provider request.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_CHUNKS:
        raise ValueError("limit must be an integer between 1 and 32.")
    if not conn.autocommit or conn.info.transaction_status != TransactionStatus.IDLE:
        raise CorpusStorageError("Corpus embedding requires an idle autocommit connection.")
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (EMBED_LOCK_ID,)).fetchone()[0]
    if not locked:
        return EmbedResult(status="already_running")
    try:
        chunks = pending_embedding_chunks(
            conn, model=embeddings.model, dimensions=embeddings.dimensions,
            processing_version=settings.processing_version, limit=limit,
        )
        if not chunks:
            return EmbedResult(status="idle")
        batch = embeddings.embed_texts(tuple(chunk.text for chunk in chunks))
        if batch.model != embeddings.model or batch.dimensions != embeddings.dimensions:
            raise EmbeddingError("The corpus embedding provider returned an inconsistent profile.")
        saved = save_embeddings(conn, chunks, batch)
        return EmbedResult(selected_chunks=len(chunks), inserted=saved.inserted,
                           completed_builds=saved.completed_builds, input_tokens=batch.input_tokens)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (EMBED_LOCK_ID,))


def run_once() -> EmbedResult:
    """Cron entry point; paid embedding work is explicitly enabled in settings."""
    try:
        values = _read_env_file(Path(__file__).resolve().parents[1] / ".env")
    except (OSError, UnicodeError):
        raise EmbeddingError("Could not read the corpus embedding environment file.") from None
    enabled = os.environ.get("CORPUS_EMBED_ENABLED", values.get("CORPUS_EMBED_ENABLED", "false")).strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("CORPUS_EMBED_ENABLED must be true or false.")
    if enabled == "false":
        return EmbedResult(status="disabled")
    embeddings = OpenAIEmbeddingClient(OpenAIEmbeddingSettings.from_environment())
    with connect_database(PostgresSettings.from_environment()) as conn:
        return embed_corpus(conn, embeddings)


def _main() -> int:
    try:
        result = run_once()
    except EmbeddingError:
        print(json.dumps({"status": "failed", "error": "Corpus embedding provider is unavailable."}))
        return 1
    except (CorpusStorageError, PsycopgError):
        print(json.dumps({"status": "failed", "error": "Corpus embedding database operation failed."}))
        return 1
    except (ValueError, OSError):
        print(json.dumps({"status": "failed", "error": "Invalid corpus embedding settings or input."}))
        return 1
    print(json.dumps(asdict(result)))  # Counts only; no transcript text, vectors or keys.
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
