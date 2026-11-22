"""The live request log and the coach mode switch, kept in PostgreSQL (Neon on Vercel, Docker locally).

    database   COACH_LOG_DATABASE_URL > DATABASE_URL > POSTGRES_URL; none: no rows are written and the mode
               comes from the environment only. The local server also reads translation_agent_demo/.env.
    tables     frontend/sql/request_log.sql, run when the server starts (CREATE TABLE IF NOT EXISTS)
    mode       coach_settings['coach_system'] > COACH_SYSTEM > agent, cached 10 s per process; a database
               error falls back to the environment's value for the next 10 s

Every call opens one short connection (connect 3 s, statements 3 s, no retry). Writing a log row never
raises: a failure prints one line with the error's type only (no URL, no learner text), and the learner's
answer is already sent when a row is written (frontend/server.py).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

URL_VARIABLES = ("COACH_LOG_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL")
SQL_FILE = Path(__file__).with_name("sql") / "request_log.sql"
MODES = ("baseline", "agent")
MODE_KEY = "coach_system"
MODE_CACHE_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 3  # libpq treats anything under 2 as 2
STATEMENT_TIMEOUT = "3s"
ENSURE_RETRY_SECONDS = 30.0  # after a failed table check, how long requests skip the database
HISTORY_LIMIT = 20
MAX_LIMIT = 1000
LOG_COLUMNS = ("mode", "mode_source", "transport", "status", "error_code", "question", "quick_ms", "first_ms",
               "total_ms", "llm_calls", "searches", "input_tokens", "output_tokens", "verified_first",
               "added_final", "verified_final", "continuation", "result")
ZERO_DEFAULTS = ("total_ms", "llm_calls", "searches", "input_tokens", "output_tokens", "added_final")
RESULT_EXCLUDE = {"answer", "tool_calls"}  # the rendered answer repeats the expressions; the log counts searches


class StoreError(Exception):
    """A database failure; the message is a short code or an exception type, never the URL or a query."""


def database_url(environ: Mapping[str, str]) -> str | None:
    for name in URL_VARIABLES:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return None


def _iso(value) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if isinstance(value, datetime) else None


def result_json(result) -> dict | None:
    """What the admin conversion needs of a RunResult (trace, expressions, usage, status...); None otherwise."""
    dump = getattr(result, "model_dump", None)
    if not callable(dump):
        return None
    try:
        return dump(mode="json", exclude=RESULT_EXCLUDE)
    except Exception:
        return None


class RequestStore:
    """The three tables behind one database URL; disabled (url None) when no database is configured."""

    def __init__(self, url: str | None = None, *, password: str | None = None, schema: str | None = None,
                 log: Callable[[str], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.url, self.password, self.schema = url, password, schema
        self.log = log or (lambda line: print(line, flush=True))
        self.clock = clock
        self._lock = threading.Lock()
        self._ready = False
        self._retry_at = 0.0

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None, env_file: Path | None = None,
                         **kwargs) -> "RequestStore":
        """The URL from URL_VARIABLES (os.environ, over env_file's values when one is given). A URL without a
        password takes PGPASSWORD or POSTGRES_PASSWORD, like translation_agent_demo/storage/postgres.py."""
        values: dict[str, str] = {}
        if env_file is not None:
            try:
                from translation_agent_demo.config import _read_env_file
                values.update(_read_env_file(env_file))
            except Exception:
                pass
        values.update(os.environ if environ is None else environ)
        url = database_url(values)
        if url is None:
            return cls(None, **kwargs)
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ("postgres", "postgresql") and "\x00" not in url
            embedded = parsed.password
        except ValueError:
            valid, embedded = False, None
        store = cls(url if valid else None,
                    password=None if embedded is not None else (values.get("PGPASSWORD") or values.get("POSTGRES_PASSWORD") or None),
                    **kwargs)
        if not valid:
            store.log(json.dumps({"event": "coach_request_log_disabled", "reason": "invalid_database_url"}))
        return store

    @property
    def enabled(self) -> bool:
        return self.url is not None

    # ------------------------------------------------------------ connections
    def _transaction(self, work):
        """work(conn) in one transaction with a statement timeout; StoreError on any failure."""
        if not self.enabled:
            raise StoreError("no_database")
        kwargs = {"password": self.password} if self.password else {}
        try:
            with psycopg.connect(self.url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS,
                                 prepare_threshold=None, row_factory=dict_row, **kwargs) as conn:
                with conn.transaction():
                    # SET LOCAL, not a startup option: Neon's pooled endpoint refuses startup options
                    conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                    if self.schema:
                        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
                    return work(conn)
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(type(exc).__name__) from None

    def ensure(self) -> bool:
        """Create the tables once per process (frontend/sql/request_log.sql); False while that fails."""
        if not self.enabled:
            return False
        with self._lock:
            if self._ready:
                return True
            if self.clock() < self._retry_at:
                return False
            try:
                script = SQL_FILE.read_text(encoding="utf-8")
                self._transaction(lambda conn: conn.execute(script))
            except (OSError, StoreError) as exc:
                self._retry_at = self.clock() + ENSURE_RETRY_SECONDS
                self.log(json.dumps({"event": "coach_request_log_error", "step": "ensure",
                                     "error": str(exc) if isinstance(exc, StoreError) else type(exc).__name__}))
                return False
            self._ready = True
            return True

    def _ready_or_raise(self) -> None:
        if not self.ensure():
            raise StoreError("no_database" if not self.enabled else "unavailable")

    # ------------------------------------------------------------ the request log
    def row(self, record: Mapping, question: str | None, result) -> dict:
        """One coach_request_log row from the server's log record (frontend/server.py log_record)."""
        row = {name: record.get(name) for name in LOG_COLUMNS}
        if isinstance(question, str):
            question = question.replace("\x00", "")  # PostgreSQL text cannot hold NUL (an invalid_input request may)
        row.update(question=question, result=result_json(result))
        for name in ZERO_DEFAULTS:
            row[name] = row[name] or 0
        return row

    def save(self, record: Mapping, question: str | None, result=None) -> bool:
        """Insert one row; never raises. False when there is no database or the insert failed."""
        if not self.enabled:
            return False
        try:
            row = self.row(record, question, result)
            row["result"] = None if row["result"] is None else Jsonb(row["result"])
            self._ready_or_raise()
            columns = sql.SQL(", ").join(map(sql.Identifier, LOG_COLUMNS))
            values = sql.SQL(", ").join(sql.Placeholder(name) for name in LOG_COLUMNS)
            query = sql.SQL("INSERT INTO coach_request_log ({}) VALUES ({})").format(columns, values)
            self._transaction(lambda conn: conn.execute(query, row))
            return True
        except Exception as exc:
            self.log(json.dumps({"event": "coach_request_log_error", "step": "insert",
                                 "error": str(exc) if isinstance(exc, StoreError) else type(exc).__name__}))
            return False

    def recent(self, limit: int = 300) -> list[dict]:
        """The newest rows first (StoreError on failure)."""
        self._ready_or_raise()
        limit = max(1, min(int(limit), MAX_LIMIT))
        return self._transaction(lambda conn: conn.execute(
            "SELECT id, created_at, " + ", ".join(LOG_COLUMNS) + " FROM coach_request_log "
            "ORDER BY created_at DESC, id DESC LIMIT %s", (limit,)).fetchall())

    # ------------------------------------------------------------ the mode switch
    def mode_setting(self) -> tuple[str, datetime] | None:
        """(value, updated_at) of coach_settings['coach_system'], None when unset (StoreError on failure)."""
        self._ready_or_raise()
        row = self._transaction(lambda conn: conn.execute(
            "SELECT value, updated_at FROM coach_settings WHERE key = %s", (MODE_KEY,)).fetchone())
        return None if row is None else (row["value"], row["updated_at"])

    def set_mode(self, mode: str, fallback: str) -> None:
        """Store the mode and, when it changes, one coach_mode_changes row (from = the mode in effect)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        self._ready_or_raise()

        def work(conn):
            row = conn.execute("SELECT value FROM coach_settings WHERE key = %s FOR UPDATE", (MODE_KEY,)).fetchone()
            previous = row["value"] if row and row["value"] in MODES else fallback
            conn.execute("INSERT INTO coach_settings (key, value, updated_at) VALUES (%s, %s, now()) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                         (MODE_KEY, mode))
            if previous != mode:
                conn.execute("INSERT INTO coach_mode_changes (from_mode, to_mode) VALUES (%s, %s)", (previous, mode))
        self._transaction(work)

    def history(self, limit: int = HISTORY_LIMIT) -> list[dict]:
        """The newest mode changes first: [{"at", "from", "to"}] (StoreError on failure)."""
        self._ready_or_raise()
        rows = self._transaction(lambda conn: conn.execute(
            "SELECT at, from_mode, to_mode FROM coach_mode_changes ORDER BY at DESC, id DESC LIMIT %s",
            (limit,)).fetchall())
        return [{"at": _iso(r["at"]), "from": r["from_mode"], "to": r["to_mode"]} for r in rows]


class ModeSwitch:
    """The mode a request runs in: the database's setting, else the environment's (COACH_SYSTEM > agent)."""

    def __init__(self, store: RequestStore, fallback: str, *, ttl: float = MODE_CACHE_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.store, self.fallback, self.ttl, self.clock = store, fallback, ttl, clock
        self._lock = threading.Lock()
        self._cached: tuple[float, tuple[str, str, str | None]] | None = None

    def current(self, *, fresh: bool = False) -> tuple[str, str, str | None]:
        """(mode, "db" | "env", updated_at); read again when older than ttl or when fresh."""
        with self._lock:
            if not fresh and self._cached and self.clock() - self._cached[0] < self.ttl:
                return self._cached[1]
        value = (self.fallback, "env", None)
        if self.store.enabled:
            try:
                setting = self.store.mode_setting()
                if setting and setting[0] in MODES:
                    value = (setting[0], "db", _iso(setting[1]))
            except StoreError:
                pass
        with self._lock:
            self._cached = (self.clock(), value)
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
