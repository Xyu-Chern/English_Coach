"""Build a bounded batch of local raw transcripts; no publisher or LLM requests.

Each document/version is committed atomically. An interruption leaves that document
pending; a deterministic parse failure is recorded and skipped until a new parser
version is deployed. Source rights are never changed by this job.
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from psycopg import Connection, Error as PsycopgError
from psycopg.pq import TransactionStatus

from ..config import _read_env_file
from ..corpus.chunking import ChunkingSettings, chunk_transcript
from ..corpus.models import CorpusParseError
from ..corpus.parsers import parse_transcript
from ..storage.chunks import pending_document_ids, save_build_failure, save_chunks
from ..storage.corpus import get_transcript
from ..storage.postgres import CorpusStorageError, PostgresSettings, connect_database

BUILD_LOCK_ID = 1162036036  # Separate from collection; those jobs may run together.
MAX_DOCUMENTS = 10
RUN_BUDGET_SECONDS = 150


@dataclass
class BuildResult:
    status: Literal["ok", "idle", "partial_failure", "already_running", "disabled"] = "ok"
    processing_version: str = ""
    selected_documents: int = 0
    built: int = 0
    unchanged: int = 0
    unsupported: int = 0
    failed: int = 0
    chunks_written: int = 0
    time_budget_reached: bool = False


def build_corpus(
    conn: Connection,
    *,
    limit: int = MAX_DOCUMENTS,
    settings: ChunkingSettings = ChunkingSettings(),
) -> BuildResult:
    """Process at most ``limit`` unprocessed raw revisions with one worker at a time.

    Use an idle autocommit connection: parsing happens outside transactions, and
    saving all derived rows for one document is a single short transaction.
    Ready means parsed/chunked locally, not approved for search or embedded.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50.")
    if not conn.autocommit or conn.info.transaction_status != TransactionStatus.IDLE:
        raise CorpusStorageError("Corpus builds require an idle autocommit connection.")
    result = BuildResult(processing_version=settings.processing_version)
    started = time.monotonic()
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (BUILD_LOCK_ID,)).fetchone()[0]
    if not locked:
        result.status = "already_running"
        return result
    try:
        document_ids = pending_document_ids(conn, settings.processing_version, limit=limit)
        result.selected_documents = len(document_ids)
        if not document_ids:
            result.status = "idle"
            return result
        for document_id in document_ids:
            if time.monotonic() - started >= RUN_BUDGET_SECONDS:
                result.time_budget_reached = True
                break
            document = get_transcript(conn, document_id)
            if document is None:
                continue  # A separately deleted raw revision has no work to do.
            try:
                parsed = parse_transcript(
                    document.text, declared_type=document.declared_type,
                    content_type=document.content_type,
                )
            except CorpusParseError as error:
                save_build_failure(
                    conn, document_id, settings.processing_version, error_code=error.code,
                )
                if error.code == "unsupported_format":
                    result.unsupported += 1
                else:
                    result.failed += 1
                continue
            chunks = chunk_transcript(parsed, settings)
            saved = save_chunks(conn, document_id, settings.processing_version, parsed, chunks)
            if saved.created:
                result.built += 1
                result.chunks_written += saved.chunk_count
            else:
                result.unchanged += 1
        if result.failed:
            result.status = "partial_failure"
        return result
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (BUILD_LOCK_ID,))


def run_once() -> BuildResult:
    """Cron entry point, using the same PostgreSQL environment as collection."""
    try:
        values = _read_env_file(Path(__file__).resolve().parents[1] / ".env")
    except (OSError, UnicodeError):
        raise CorpusStorageError("Could not read the corpus build environment file.") from None
    enabled = os.environ.get("CORPUS_BUILD_ENABLED", values.get("CORPUS_BUILD_ENABLED", "false")).strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("CORPUS_BUILD_ENABLED must be true or false.")
    if enabled == "false":
        return BuildResult(status="disabled")
    with connect_database(PostgresSettings.from_environment()) as conn:
        return build_corpus(conn)


def _main() -> int:
    try:
        result = run_once()
    except (CorpusStorageError, PsycopgError):
        print(json.dumps({"status": "failed", "error": "Corpus build database operation failed."}))
        return 1
    except (ValueError, OSError):
        print(json.dumps({"status": "failed", "error": "Invalid corpus build settings or processing input."}))
        return 1
    print(json.dumps(asdict(result)))  # Counts only; never transcript text or credentials.
    return int(result.status == "partial_failure")


if __name__ == "__main__":
    raise SystemExit(_main())
