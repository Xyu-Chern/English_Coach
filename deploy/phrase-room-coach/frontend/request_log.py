"""The live request log, the coach mode switch and the daily request cap in PostgreSQL: COACH_LOG_DATABASE_URL >
DATABASE_URL > POSTGRES_URL (none: no rows; the mode comes from the environment). The tables
(frontend/sql/request_log.sql) are created at start. Mode: coach_settings['coach_system'] > COACH_SYSTEM > agent,
cached 10 s (a database error keeps the environment's). Daily cap (DailyLimit): COACH_DAILY_LIMIT requests a day
for everyone together, counted in coach_daily_usage per COACH_DAILY_TZ day; with a cap and no database every
request is refused. One short connection per call (3 s timeouts, no retry); saving never raises and logs only
the error's type (no URL, no learner text).
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
DAILY_LIMIT_ENV, DAILY_TZ_ENV, DEFAULT_DAILY_TZ = "COACH_DAILY_LIMIT", "COACH_DAILY_TZ", "Asia/Seoul"
MAX_DAILY_LIMIT = 1_000_000
# Zones without daylight saving time, for a runtime without a time zone database (Python has no tzdata built in)
FIXED_ZONES = {"UTC": 0, "Etc/UTC": 0, "Asia/Seoul": 9, "Asia/Tokyo": 9, "Asia/Shanghai": 8}


class StoreError(Exception):
    """A database failure; the message is a short code or an exception type, never the URL or a query."""


def database_url(environ: Mapping[str, str]) -> str | None:
    return next((value for name in URL_VARIABLES if (value := (environ.get(name) or "").strip())), None)


def _iso(value) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if isinstance(value, datetime) else None


class RequestStore:
    """The four tables behind one database URL; disabled (url None) when no database is configured."""

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
        """The URL from os.environ over env_file's values. One without a password takes PGPASSWORD or
        POSTGRES_PASSWORD, like translation_agent_demo/storage/postgres.py."""
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
        password = values.get("PGPASSWORD") or values.get("POSTGRES_PASSWORD") or None
        store = cls(url if valid else None, password=None if embedded is not None else password, **kwargs)
        if not valid:
            store.log(json.dumps({"event": "coach_request_log_disabled", "reason": "invalid_database_url"}))
        return store

    @property
    def enabled(self) -> bool:
        return self.url is not None

    def _error(self, step: str, exc: Exception) -> None:
        self.log(json.dumps({"event": "coach_request_log_error", "step": step,
                             "error": str(exc) if isinstance(exc, StoreError) else type(exc).__name__}))

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
        """Create the tables once per process; False while that fails (retried after ENSURE_RETRY_SECONDS)."""
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
                self._error("ensure", exc)
                return False
            self._ready = True
            return True

    def _ready_or_raise(self) -> None:
        if not self.ensure():
            raise StoreError("no_database" if not self.enabled else "unavailable")

    def _fetch(self, query: str, params: tuple, *, one: bool = False):
        """The rows (or the first row) of one query once the tables exist; StoreError on failure."""
        self._ready_or_raise()

        def work(conn):
            cursor = conn.execute(query, params)
            return cursor.fetchone() if one else cursor.fetchall()
        return self._transaction(work)

    # ------------------------------------------------------------ the request log
    def row(self, record: Mapping, question: str | None, result) -> dict:
        """One coach_request_log row from the server's log record (frontend/server.py log_record) and the
        RunResult (what the admin conversion needs: not its rendered answer, None when it cannot be dumped)."""
        row = {name: record.get(name) for name in LOG_COLUMNS}
        if isinstance(question, str):
            question = question.replace("\x00", "")  # PostgreSQL text cannot hold NUL (an invalid_input request may)
        dump = getattr(result, "model_dump", None)
        try:
            dumped = dump(mode="json", exclude=RESULT_EXCLUDE) if callable(dump) else None
        except Exception:
            dumped = None
        row.update(question=question, result=dumped)
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
            self._error("insert", exc)
            return False

    def recent(self, limit: int = 300) -> list[dict]:
        """The newest rows first (StoreError on failure)."""
        limit = max(1, min(int(limit), MAX_LIMIT))
        return self._fetch(f"SELECT id, created_at, {', '.join(LOG_COLUMNS)} FROM coach_request_log "
                           "ORDER BY created_at DESC, id DESC LIMIT %s", (limit,))

    # ------------------------------------------------------------ the mode switch
    def mode_setting(self) -> tuple[str, datetime] | None:
        """(value, updated_at) of coach_settings['coach_system'], None when unset (StoreError on failure)."""
        row = self._fetch("SELECT value, updated_at FROM coach_settings WHERE key = %s", (MODE_KEY,), one=True)
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
        rows = self._fetch("SELECT at, from_mode, to_mode FROM coach_mode_changes ORDER BY at DESC, id DESC "
                           "LIMIT %s", (limit,))
        return [{"at": _iso(r["at"]), "from": r["from_mode"], "to": r["to_mode"]} for r in rows]

    # ------------------------------------------------------------ the daily cap
    def count_request(self, day: date) -> int:
        """Add one to the day's coach_daily_usage count in one statement and return the new count: parallel
        requests (any process) each get their own number (StoreError on failure)."""
        row = self._fetch("INSERT INTO coach_daily_usage (day, count) VALUES (%s, 1) ON CONFLICT (day) "
                          "DO UPDATE SET count = coach_daily_usage.count + 1 RETURNING count", (day,), one=True)
        return int(row["count"])


def day_zone(name: str) -> tzinfo:
    """The time zone whose midnight starts a new day; ValueError for an unknown name."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        if name in FIXED_ZONES:
            return timezone(timedelta(hours=FIXED_ZONES[name]), name)
        raise ValueError(f"{DAILY_TZ_ENV} must be a time zone name such as {DEFAULT_DAILY_TZ}, not {name!r}") from None


class DailyLimit:
    """At most `limit` POST /api/search requests a day for all learners together, whatever the client sends:
    each request past the access checks and the slot counts once (its quick, first and continuation steps are
    the same request), in coach_daily_usage, the day starting at midnight in `zone`. limit None: no cap and
    nothing counted. take() raises StoreError when the database cannot count: the caller refuses the request."""

    def __init__(self, limit: int | None, store: RequestStore, *, zone: str | tzinfo = DEFAULT_DAILY_TZ,
                 now: Callable[[], datetime] | None = None):
        self.limit, self.store = limit, store
        self.zone = day_zone(zone) if isinstance(zone, str) else zone
        self.now = now or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_environment(cls, store: RequestStore, environ: Mapping[str, str] | None = None,
                         **kwargs) -> "DailyLimit":
        """COACH_DAILY_LIMIT (a whole number; unset or empty: no cap) and COACH_DAILY_TZ (default Asia/Seoul);
        ValueError for another value."""
        environ = os.environ if environ is None else environ
        value = (environ.get(DAILY_LIMIT_ENV) or "").strip()
        if not value:
            return cls(None, store, **kwargs)
        if not (value.isascii() and value.isdigit()) or int(value) > MAX_DAILY_LIMIT:
            raise ValueError(f"{DAILY_LIMIT_ENV} must be a whole number from 0 to {MAX_DAILY_LIMIT}, not {value!r}")
        zone = (environ.get(DAILY_TZ_ENV) or "").strip() or DEFAULT_DAILY_TZ
        return cls(int(value), store, zone=zone, **kwargs)

    @property
    def enabled(self) -> bool:
        return self.limit is not None

    def today(self) -> date:
        return self.now().astimezone(self.zone).date()

    def take(self) -> tuple[bool, int]:
        """Count one request today: (within the cap, requests left after it)."""
        count = self.store.count_request(self.today())
        return count <= self.limit, max(0, self.limit - count)

    def describe(self) -> str:
        return "off" if self.limit is None else f"{self.limit} requests a day ({self.zone})"


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
