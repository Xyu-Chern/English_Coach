"""Small synchronous PostgreSQL connection boundary, independent of LLM settings."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from ..config import _read_env_file


class CorpusStorageError(Exception):
    """A storage failure whose message contains no connection secrets or body text."""


@dataclass(frozen=True)
class PostgresSettings:
    database_url: str = field(repr=False)
    password: str | None = field(default=None, repr=False)
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 10_000

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise CorpusStorageError("Set DATABASE_URL to a PostgreSQL connection URL.")
        try:
            parsed = urlsplit(self.database_url)
            if parsed.scheme not in {"postgres", "postgresql"} or not parsed.path.strip("/"):
                raise ValueError
            parsed.port  # Validate a supplied port without including the URL in errors.
        except ValueError:
            raise CorpusStorageError("DATABASE_URL must identify a PostgreSQL database.") from None
        if "\x00" in self.database_url or (
            self.password is not None and (not isinstance(self.password, str) or "\x00" in self.password)
        ):
            raise CorpusStorageError("Invalid PostgreSQL connection settings.")
        if (
            type(self.connect_timeout_seconds) is not int or self.connect_timeout_seconds <= 0
            or type(self.statement_timeout_ms) is not int or self.statement_timeout_ms <= 0
        ):
            raise CorpusStorageError("PostgreSQL timeouts must be positive integers.")

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> "PostgresSettings":
        path = env_file if env_file is not None else Path(__file__).resolve().parents[1] / ".env"
        try:
            values = _read_env_file(path)
        except (OSError, UnicodeError):
            raise CorpusStorageError("Could not read the PostgreSQL environment file.") from None
        values.update(os.environ)
        database_url = values.get("DATABASE_URL", "").strip()
        try:
            embedded_password = urlsplit(database_url).password
        except ValueError:
            raise CorpusStorageError("Invalid DATABASE_URL.") from None
        # A password in the URI wins. Otherwise support Docker's separate secret value
        # and libpq's PGPASSWORD without embedding the password into a printable URL.
        password = None if embedded_password is not None else (
            values.get("PGPASSWORD") or values.get("POSTGRES_PASSWORD") or None
        )
        return cls(database_url=database_url, password=password)


@dataclass(frozen=True)
class DatabaseInfo:
    database_name: str
    server_version: str
    vector_version: str


def connect_database(settings: PostgresSettings) -> psycopg.Connection:
    """Open one connection; the caller closes it using `with connect_database(...)`.

    Reads do not leave an implicit transaction open. Repository writes explicitly
    use `conn.transaction()`. There are no automatic retries or schema changes.
    """
    kwargs = {"password": settings.password} if settings.password is not None else {}
    try:
        return psycopg.connect(
            settings.database_url,
            autocommit=True,
            connect_timeout=settings.connect_timeout_seconds,
            options=f"-c statement_timeout={settings.statement_timeout_ms}",
            **kwargs,
        )
    except (psycopg.Error, ValueError, UnicodeError):
        raise CorpusStorageError("Could not connect to PostgreSQL; no retry was made.") from None


def check_database(conn: psycopg.Connection) -> DatabaseInfo:
    """Confirm the database connection and its installed pgvector extension."""
    try:
        row = conn.execute(
            "SELECT current_database(), current_setting('server_version'), "
            "(SELECT extversion FROM pg_extension WHERE extname = 'vector')"
        ).fetchone()
    except psycopg.Error:
        raise CorpusStorageError("Could not inspect PostgreSQL.") from None
    if row is None or row[2] is None:
        raise CorpusStorageError("The connected database does not have the vector extension.")
    return DatabaseInfo(*row)


def initialize_schema(conn: psycopg.Connection) -> None:
    """Explicitly apply initial migrations to a fresh DB with a setup account.

    Docker applies the same files through its standard initialization directory.
    Each file owns BEGIN/COMMIT, so use an idle autocommit connection here.
    """
    if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise CorpusStorageError("Schema initialization requires an idle autocommit connection.")
    try:
        directory = Path(__file__).parent / "migrations"
        migrations = [
            (directory / name).read_text(encoding="utf-8")
            for name in (
                "001_transcripts.sql", "002_podcast_sync.sql", "003_corpus_chunks.sql",
                "004_corpus_embeddings.sql", "005_podcast_feed_reviews.sql",
                "006_corpus_observations.sql", "007_corpus_markdown.sql",
                "008_transcript_review_scope.sql",
            )
        ]
        for sql in migrations:
            conn.execute(sql, prepare=False)
    except (OSError, UnicodeError, psycopg.Error):
        try:
            conn.rollback()
        except psycopg.Error:
            pass
        raise CorpusStorageError("Could not initialize the PostgreSQL schema.") from None
