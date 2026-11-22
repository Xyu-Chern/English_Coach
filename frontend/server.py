"""Serve the learner clients and adapt the staged coach (frontend/staged.py) to a small HTTP API.

POST /api/search {question, context} answers one request:

    any other Accept                   one JSON reply, as before: {"expressions": [...], "note": ...}
    Accept: application/x-ndjson       one JSON object per line (opt-in), in this order:
      {"type":"quick","text":"<one English expression>","note":"<short note, learner's language>"}
                                       optional, only ever the first line: a generated suggestion from one
                                       fast model call started with the coach (frontend/quick.py), sent when
                                       it answers within 3 s and before any other line; never on failure,
                                       refusal or lateness. Not a verified record; first/final do not change.
      {"type":"first","expressions":[verified only],"pending":true|false,"note":null}
                                       the first stage's verified examples; pending=false ends the stream
      {"type":"final","expressions":[...],"added":[indexes],"note":...}
                                       after a first: the first items unchanged, then only the examples
                                       verified later (added indexes them); unverified candidates are
                                       never sent once a first was. Without a first: the whole answer.
      {"type":"error","code":"timeout"|"coach_unavailable"|<coach error code>}

    every slot verified: first (pending=false) only. 1-2: first, then final or error. None, or a
    declined request: final (or error) only, as one answer. Refusals (401, 403, 422, 429) come as
    plain HTTP errors before any line. The JSON reply is the whole final answer, as before (old
    clients show unverified candidates with their own label); a failure after verified examples
    still returns them (they are final under the lock).

The coach works in its own thread. The request stops it at the deadline (start + 280 s, inside
Vercel's maxDuration of 300 s; the local server takes --deadline / COACH_DEADLINE_SECONDS) or when
the client goes away, even before the stream's first line; its guarded dependencies then refuse the
next model call or search. One request runs per process (coach_busy otherwise); the slot is
returned when the stream ends or the work ends, whichever is first.

Each request that passes the access checks prints one JSON line to stdout (event=coach_request;
fields in frontend/README.md). With a database (frontend/request_log.py: COACH_LOG_DATABASE_URL >
DATABASE_URL > POSTGRES_URL) the same request is also one coach_request_log row, written after the
response has ended (a failed write changes nothing for the learner): the question (not the context),
the log fields and the RunResult's trace and expressions.

The mode a request runs in: coach_settings['coach_system'] > COACH_SYSTEM > agent, cached 10 s.

GET /admin/ serves the admin page (frontend/admin/, open like the deployment's /admin, D4, with
X-Robots-Tag: noindex) and /admin/data.json (+ data-traces.json) its data, built from an evaluation
run by frontend/admin_data.py (D5). COACH_ADMIN_DIR swaps the page folder and COACH_ADMIN_DATA the
data folder, so another design or another run can be previewed on another port. Both deployments add:

    GET  /admin/requests.json?limit=300  the logged requests, newest first, in data.json's request shape:
         {"schema_version":1,"source":"live","enabled":bool,"requests":[...],"traces":{id:[spans]},
          "answers":{id:{first,final}}} (+ "error":"database_unavailable" when the read failed)
    GET  /admin/mode   {"mode","source":"db"|"env","updated_at","writable","token_required","history":[...]}
    POST /admin/mode   {"mode":"baseline"|"agent"}; X-Admin-Token only when COACH_ADMIN_TOKEN is set.
         200 as GET | 400 invalid_mode | 401 token_required | 409 no_database | 503 database_unavailable
"""
import argparse
import asyncio
import hmac
import ipaddress
import json
import os
import queue
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache, partial
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from frontend.quick import QUICK_SECONDS, Quick, environment_quick
from frontend.request_log import MAX_LIMIT, MODE_CACHE_SECONDS, MODES, ModeSwitch, RequestStore, StoreError
from frontend.staged import CoachMode, Failed, Final, First, Guard, StagedCoach, is_terminal
from translation_agent_demo.agents import CoachDependencies, SessionLimits
from translation_agent_demo.agents.coach import _valid_input
from translation_agent_demo.agents.results import SourceCitation
from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.embeddings import embedding_client
from translation_agent_demo.storage.postgres import PostgresSettings, connect_database
from translation_agent_demo.tools.search_corpus import search_corpus

WEB = Path(__file__).with_name("web")
ADMIN = Path(__file__).with_name("admin")
ADMIN_DATA_FILES = ("data.json", "data-traces.json")  # the files an /admin page fetches (frontend/admin_data.py)
NDJSON = "application/x-ndjson"
DEADLINE_SECONDS = 280.0  # Vercel stops the function at maxDuration 300 s; stop the work first
MAX_DEADLINE_SECONDS = 3600.0  # the most the local server's --deadline / COACH_DEADLINE_SECONDS may ask for
NOINDEX = {"X-Robots-Tag": "noindex"}  # /admin is open to anyone with the address (D4), not to search engines
POLL_SECONDS = 0.05  # how often a stream checks for the coach's next event
QUESTION_HEAD_CHARS = 40  # how much of the request the log line keeps (D2, D5)
SEARCH_WORKERS = 6  # the first stage's six searches at once (COACH_SEARCH_WORKERS=1: one after another)
_DONE = object()  # the coach's thread has ended


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1800)
    context: str = Field(default="", max_length=600)


class LearnerExpression(BaseModel):
    expression: str
    key_phrase: str | None
    note: str
    citation: SourceCitation | None


class Reply(BaseModel):
    expressions: list[LearnerExpression]
    note: str | None = None


class QuickEvent(BaseModel):
    type: Literal["quick"] = "quick"
    text: str
    note: str


class FirstEvent(BaseModel):
    type: Literal["first"] = "first"
    expressions: list[LearnerExpression]
    pending: bool
    note: str | None = None


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    expressions: list[LearnerExpression]
    added: list[int]
    note: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str


def learner(items) -> list[LearnerExpression]:
    """What a learner sees of each expression: no function, trace or usage."""
    return [LearnerExpression(expression=i.expression, key_phrase=i.key_phrase, note=i.note, citation=i.citation)
            for i in items]


# ------------------------------------------------------------------ coaches
@lru_cache(maxsize=1)
def dependencies():
    return chat_model(Settings.from_environment()), embedding_client(), PostgresSettings.from_environment()


def search_workers(environ=os.environ) -> int:
    """COACH_SEARCH_WORKERS: how many of a step's independent searches run at once, 1 (one after another) to 9.
    Default SEARCH_WORKERS: the first stage's six together. A value outside 1-9 stops the start."""
    value = environ.get("COACH_SEARCH_WORKERS", "").strip() or str(SEARCH_WORKERS)
    if not value.isdigit() or not 1 <= int(value) <= 9:
        raise ValueError(f"COACH_SEARCH_WORKERS must be 1 to 9, not {value!r}.")
    return int(value)


class _Connections:
    """One request's PostgreSQL connections. A connection runs one query at a time, so searches running at
    once each take an idle one or open another. The first opens at once (no database: no model call).
    close() closes the idle ones; one still in use (a prefetched search) closes when its search returns."""

    def __init__(self, db, encoder):
        self.db, self.encoder, self._lock, self._closed = db, encoder, threading.Lock(), False
        self._idle = [connect_database(db)]

    def search(self, args):
        with self._lock:
            conn = self._idle.pop() if self._idle else None
        conn = conn or connect_database(self.db)
        try:
            return search_corpus(args, conn=conn, embeddings=self.encoder)
        finally:
            with self._lock:
                keep = not self._closed
                if keep:
                    self._idle.append(conn)
            if not keep:
                conn.close()

    def close(self) -> None:
        with self._lock:
            self._closed, idle, self._idle = True, self._idle, []
        for conn in idle:
            conn.close()


def local_stream(question, mode, guard, workers: int = SEARCH_WORKERS):
    """The local deployment: the PostgreSQL transcript index, `workers` searches at once."""
    model, encoder, db = dependencies()
    connections = _Connections(db, encoder)
    try:
        coach = StagedCoach(CoachDependencies(model, connections.search, search_workers=workers), mode)
        yield from coach.stream(question, guard)
    finally:
        connections.close()


def answering(answer):
    """A stream for an answer(question) -> RunResult function: one final answer, no first."""
    def stream(question, mode, guard):
        result = answer(question)
        if result.status != "ok":
            code = result.error_code or ("invalid_input" if result.status == "invalid_input" else "unavailable")
            return [Failed(code, result)]
        expressions, note = tuple(result.expressions or ()), result.source_availability_note
        return [Final(expressions, (), note, result, verified_first=None, continuation="none",
                      declined=not expressions and note is not None)]
    return stream


# ------------------------------------------------------------------ one request
def wants_ndjson(accept: str) -> bool:
    for part in accept.split(","):
        media, *params = (p.strip().lower() for p in part.split(";"))
        weight = next((p[2:].strip() for p in params if p.startswith("q=")), "1")
        try:
            accepted = float(weight) > 0
        except ValueError:
            accepted = False
        if media == NDJSON and accepted:
            return True
    return False


def log_record(mode: CoachMode, transport: str, question: str, mode_source: str = "env") -> dict:
    """The request log line's fields, before anything happened. Of the request it keeps only the
    question's first characters, never the context or the answer (D2, D5). mode_source: "db" when the
    mode came from coach_settings, "env" from COACH_SYSTEM (or its default)."""
    return {"event": "coach_request", "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request_id": str(uuid4()), "mode": mode.system, "mode_source": mode_source,
            "continuation_setting": mode.continuation_setting,
            "transport": transport, "status": None, "error_code": None, "verified_first": None,
            "added_final": None, "verified_final": None, "continuation": None, "invariant_ok": None,
            "quick_ms": None, "first_ms": None, "total_ms": 0,
            "llm_calls": 0, "searches": 0, "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
            "disconnected": False, "question_head": question[:QUESTION_HEAD_CHARS]}


class Exchange:
    """One answered POST: the coach works in its own thread; the request reads its events until the deadline.

    The log fields that compare with the admin data (frontend/admin_data.py) share its definitions:
    added_final counts examples verified after a first answer (0 when there was none), verified_final
    the verified examples the learner ends with. first_ms is when the client received the first answer,
    so only the stream has it: a JSON client sees nothing before total_ms. quick_ms is when the stream
    sent its quick line (None without one); only a stream asks for it."""

    def __init__(self, stream, question: str, mode: CoachMode, record: dict, *, clock, deadline_seconds: float,
                 release, log, quick=None, quick_seconds: float = QUICK_SECONDS, save=None):
        self.clock, self.record, self.log, self._release = clock, record, log, release
        self.save = save  # save(record, result): the database row, written by persist() after the response
        self.streaming = record["transport"] == "ndjson"
        self.started = clock()
        self.deadline = self.started + deadline_seconds
        self.guard = Guard(self.deadline, clock)
        self.events: queue.Queue = queue.Queue()
        self.first: First | None = None  # the first answer, once given
        self.result = None  # the terminal event's RunResult, when there was one
        self.sent = False  # the stream has written a coach line: a quick line comes too late
        self._lock = threading.Lock()
        self._released = self._closed = self._persisted = False
        if quick is not None and self.streaming:  # started with the coach; a JSON reply never shows it
            threading.Thread(target=self._quick, args=(quick, question, quick_seconds), name="coach-quick",
                             daemon=True).start()
        threading.Thread(target=self._work, args=(stream, question, mode), name="coach-request", daemon=True).start()

    # ------------------------------------------------------- the quick answer's thread
    def _quick(self, quick, question: str, seconds: float) -> None:
        """One quick answer, queued only when it came within `seconds` of the start and the request is on."""
        try:
            answer = None if self.guard.stopped else quick(question)
        except Exception:
            answer = None
        if isinstance(answer, Quick) and not self.guard.stopped and self.clock() - self.started <= seconds:
            self.events.put(answer)

    # ------------------------------------------------------- the coach's thread
    def _work(self, stream, question: str, mode: CoachMode) -> None:
        events = None
        try:
            events = iter(stream(question, mode, self.guard))
            for event in events:
                self.events.put(event)
                if is_terminal(event) or self.guard.stopped:
                    break
        except Exception:
            self.events.put(Failed("coach_unavailable"))
        finally:
            try:
                getattr(events, "close", lambda: None)()
            except Exception:
                pass
            self.events.put(_DONE)
            self.release()

    def release(self) -> None:
        """Return the request slot once: when the work ends or the request ends, whichever is first."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release()

    # ------------------------------------------------------- what the learner gets
    def elapsed_ms(self) -> int:
        return round((self.clock() - self.started) * 1000)

    def wire(self, event) -> BaseModel | None:
        """The line for one coach event (or _DONE, or the quick answer); records it for the log. None: a quick
        answer that would no longer be the first line, which is not sent."""
        if isinstance(event, Quick):
            if self.sent or not self.streaming:
                return None
            self.record["quick_ms"] = self.elapsed_ms()
            return QuickEvent(text=event.text, note=event.note)
        if event is _DONE:
            return self.fail("coach_unavailable")
        if getattr(event, "result", None) is not None:
            self.result = event.result
        if isinstance(event, First):
            self.first = event
            sent = len(event.expressions)
            self.record.update(first_ms=self.elapsed_ms() if self.streaming else None, verified_first=sent)
            if not event.pending:
                self.record.update(status="ok", continuation=event.continuation, added_final=0, verified_final=sent,
                                   invariant_ok=True)
            return FirstEvent(expressions=learner(event.expressions), pending=event.pending, note=event.note)
        if isinstance(event, Final):
            expressions, added = event.expressions, list(event.added)
            if self.first is None:
                self.record.update(verified_first=event.verified_first, added_final=0,
                                   verified_final=sum(1 for item in expressions if item.citation is not None))
            else:
                self.record.update(added_final=len(added), verified_final=len(self.first.expressions) + len(added))
                if self.streaming:  # after a first: the sent items, then only what was verified later (D1)
                    sent = len(self.first.expressions)
                    expressions = (*expressions[:sent], *(expressions[i] for i in added))
                    added = list(range(sent, len(expressions)))
            self.record.update(status="declined" if event.declined else "ok", continuation=event.continuation,
                               invariant_ok=event.kept_first)
            return FinalEvent(expressions=learner(expressions), added=added, note=event.note)
        return self.fail("timeout" if self.guard.expired else event.code, event.continuation)

    def fail(self, code: str, continuation: str = "none") -> ErrorEvent:
        status = code if code in ("invalid_input", "timeout") else "error"
        self.record.update(status=status, error_code=code, continuation="ran" if self.first else continuation)
        return ErrorEvent(code=code)

    def reply(self) -> Reply:
        """The JSON transport: wait for the end (or the deadline) and answer once."""
        try:
            while True:
                try:
                    event = self.events.get(timeout=max(0.0, self.deadline - self.clock()))
                except queue.Empty:
                    line = self.fail("timeout")
                    break
                if isinstance(event, Quick):  # never asked for here; the JSON reply is unchanged
                    continue
                line = self.wire(event)
                if event is _DONE or is_terminal(event):
                    break
            if not isinstance(line, ErrorEvent):
                return Reply(expressions=line.expressions, note=line.note)
            if self.first is not None:  # sent examples are final; a later failure does not take them back
                return Reply(expressions=learner(self.first.expressions), note=self.first.note)
            raise HTTPException(422 if line.code == "invalid_input" else 503, line.code)
        finally:
            self.close()

    async def lines(self):
        """The NDJSON transport: each event as soon as the coach has it; an error line at the deadline."""
        finished = False
        try:
            while not finished:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    if self.clock() < self.deadline:
                        await asyncio.sleep(POLL_SECONDS)
                        continue
                    line, finished = self.fail("timeout"), True
                else:
                    line = self.wire(event)
                    if line is None:
                        continue
                    finished = not isinstance(event, Quick) and (event is _DONE or is_terminal(event))
                if not isinstance(line, QuickEvent):
                    self.sent = True
                yield line.model_dump_json() + "\n"
        finally:
            self.close(left=not finished)

    def close(self, *, left: bool = False) -> None:
        """Stop the work, return the slot and print the log line; once. left: the client went away before
        the stream's last line (or before its first: StagedResponse closes an exchange whose body never ran)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if left:
            self.record.update(disconnected=True, status="disconnected", continuation="ran" if self.first else "none")
        self.guard.stop()
        self.release()
        self.record.update(total_ms=self.elapsed_ms(), **self.guard.usage())
        if self.record["status"] is None:
            self.record["status"] = "error"
        self.log(json.dumps(self.record, ensure_ascii=False))

    def persist(self) -> None:
        """Write the database row once, after close(); never raises (RequestStore.save does not)."""
        with self._lock:
            if self._persisted or not self._closed or self.save is None:
                return
            self._persisted = True
        try:
            self.save(self.record, self.result)
        except Exception:
            pass


class StagedResponse(StreamingResponse):
    """The NDJSON response of one exchange. However the response ends, the exchange is closed: a client
    that leaves before the body starts never runs lines(), whose finally would close it, on either ASGI
    disconnect path (spec 2.3: Starlette cancels the body; 2.4: the first send fails). The database row is
    written after that, when the stream has ended (shielded: a cancelled response still writes it)."""

    def __init__(self, exchange: Exchange):
        super().__init__(exchange.lines(), media_type=NDJSON,
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        self.exchange = exchange

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.exchange.close(left=True)  # nothing when the stream already closed it
            if self.exchange.save is not None:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self.exchange.persist)


def _print(line: str) -> None:
    print(line, flush=True)


# ------------------------------------------------------------------ the admin page
def admin_folders(environ=os.environ) -> tuple[Path, Path] | None:
    """The /admin page folder and its data folder: COACH_ADMIN_DIR and COACH_ADMIN_DATA when set (a
    preview of another design or another run), else frontend/admin for both. None when there is no page.
    A folder named by a variable must exist, and a data folder must hold data.json: else ValueError."""
    def chosen(name: str) -> Path | None:
        value = environ.get(name, "").strip()
        if not value:
            return None
        folder = Path(value).expanduser()
        if not folder.is_dir():
            raise ValueError(f"{name} is not a folder: {folder}")
        return folder.resolve()

    page, data = chosen("COACH_ADMIN_DIR"), chosen("COACH_ADMIN_DATA")
    if data is not None and not (data / ADMIN_DATA_FILES[0]).is_file():
        raise ValueError(f"COACH_ADMIN_DATA has no {ADMIN_DATA_FILES[0]}: {data} "
                         "(build it with python -m frontend.admin_data)")
    page = page or (ADMIN if ADMIN.is_dir() else None)
    return None if page is None else (page, data or page)


class _Noindex:
    """An ASGI wrapper that adds X-Robots-Tag: noindex to every response of the app it wraps."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_marked(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-robots-tag", b"noindex")]}
            await send(message)
        await self.app(scope, receive, send_marked)


def serve_admin(app: FastAPI, page: Path, data: Path) -> None:
    """GET /admin/ from the page folder and /admin/<data file> from the data folder. Open, like the
    deployment's /admin (D4), and marked noindex like it (frontend/vercel/package.py). Pages fetch their
    data with relative URLs, so /admin redirects to /admin/."""
    @app.get("/admin", include_in_schema=False)
    def admin_root():
        return RedirectResponse("admin/", status_code=307, headers=NOINDEX)

    def data_file(name: str):
        def serve():
            path = data / name
            if not path.is_file():
                raise HTTPException(404, "admin_data_missing", headers=NOINDEX)
            return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache", **NOINDEX})
        return serve

    for name in ADMIN_DATA_FILES:
        app.add_api_route(f"/admin/{name}", data_file(name), methods=["GET"], include_in_schema=False)
    app.mount("/admin", _Noindex(StaticFiles(directory=page, html=True)), name="admin")


# ------------------------------------------------------------------ live requests and the mode switch
def serve_live_admin(app: FastAPI, store: RequestStore, switch: ModeSwitch, fallback: str, origin: str) -> None:
    """GET /admin/requests.json, GET and POST /admin/mode (frontend/request_log.py). Registered before the
    /admin static mount, so they win over files of the same name."""
    headers = {"Cache-Control": "no-store", **NOINDEX}

    def refuse(status: int, code: str):
        raise HTTPException(status, code, headers=headers)

    def mode_view() -> dict:
        current, source, updated_at = switch.current(fresh=True)
        history = []
        if store.enabled:
            try:
                history = store.history()
            except StoreError:
                pass
        return {"mode": current, "source": source, "updated_at": updated_at, "writable": store.enabled,
                "token_required": bool(os.environ.get("COACH_ADMIN_TOKEN", "")), "history": history}

    @app.get("/admin/requests.json", include_in_schema=False)
    def admin_requests(limit: int = Query(300, ge=1, le=MAX_LIMIT)):
        payload = {"schema_version": 1, "source": "live", "enabled": store.enabled,
                   "requests": [], "traces": {}, "answers": {}}
        if store.enabled:
            try:
                rows = store.recent(limit)
            except StoreError:
                payload["error"] = "database_unavailable"
            else:
                from frontend.admin_data import live_payload  # here: an import problem must not stop the coach
                payload.update(live_payload(rows))
        return JSONResponse(payload, headers=headers)

    @app.get("/admin/mode", include_in_schema=False)
    def admin_mode():
        return JSONResponse(mode_view(), headers=headers)

    @app.post("/admin/mode", include_in_schema=False)
    async def change_mode(request: Request, x_admin_token: str = Header(default="")):
        token = os.environ.get("COACH_ADMIN_TOKEN", "")
        if token and not hmac.compare_digest(token.encode(), x_admin_token.encode()):
            refuse(401, "token_required")
        if cross_site(request, origin):
            refuse(403, "origin_denied")
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            body = None
        value = body.get("mode") if isinstance(body, dict) else None
        if not isinstance(value, str) or value not in MODES:
            refuse(400, "invalid_mode")
        if not store.enabled:
            refuse(409, "no_database")
        try:
            await run_in_threadpool(store.set_mode, value, fallback)
        except StoreError:
            refuse(503, "database_unavailable")
        switch.invalidate()
        return JSONResponse(await run_in_threadpool(mode_view), headers=headers)


def cross_site(request: Request, origin: str) -> bool:
    """A browser request from a page that is neither this host nor an allowed web origin."""
    browser_origin = request.headers.get("origin")
    return bool(browser_origin) and (urlsplit(browser_origin).netloc != request.headers.get("host")
                                     and browser_origin not in {"http://localhost", origin})


# ------------------------------------------------------------------ the app
def make_app(answer=None, *, stream=None, quick=None, mode: CoachMode | None = None, serve_ui=True,
             public_access=False, deadline_seconds: float = DEADLINE_SECONDS, quick_seconds: float = QUICK_SECONDS,
             log=None, clock=time.monotonic, store: RequestStore | None = None,
             mode_cache_seconds: float = MODE_CACHE_SECONDS):
    """stream(question, mode, guard) -> events answers requests (the staged coach); answer(question) ->
    RunResult does instead, as one final answer; with neither, the local PostgreSQL index does.

    quick(question) -> Quick | None gives NDJSON streams their quick line (frontend/quick.py). With neither
    stream nor answer it defaults to the environment's quick model (environment_quick); an injected stream
    or answer has none unless quick is given too.

    mode defaults to COACH_SYSTEM / COACH_CONTINUATION, read now: an unknown value stops the start, as does
    a COACH_SEARCH_WORKERS outside 1-9 for the local index (search_workers). With
    serve_ui, so are COACH_ADMIN_DIR / COACH_ADMIN_DATA (admin_folders). store: the request log and mode
    switch (RequestStore.from_environment() in both deployments); without one nothing is written and every
    request runs in mode.system. Its tables are ensured now; a database that is down stops nothing."""
    mode = mode or CoachMode.from_environment()
    admin = admin_folders() if serve_ui else None
    if quick is None and stream is None and answer is None:
        quick = environment_quick
    stream = stream or (answering(answer) if answer is not None else partial(local_stream, workers=search_workers()))
    log = log or _print
    store = store or RequestStore(None)
    if store.enabled:
        store.ensure()
    switch = ModeSwitch(store, mode.system, ttl=mode_cache_seconds)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    origin = os.environ.get("COACH_WEB_ORIGIN", "").strip()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost", *([origin] if origin else [])],
                       allow_methods=["POST"], allow_headers=["Content-Type", "X-Coach-Code"],
                       allow_private_network=bool(origin))
    slot = threading.BoundedSemaphore(1)
    limits = SessionLimits()

    @app.post("/api/search", response_model=Reply)
    def search(body: Question, request: Request, background: BackgroundTasks, x_coach_code: str = Header(default=""),
               accept: str = Header(default="")):
        if not public_access:
            code = os.environ.get("COACH_PAIR_CODE", "")
            if code and not hmac.compare_digest(code.encode(), x_coach_code.encode()):
                raise HTTPException(401, "pairing_required")
            if not code:
                host = request.url.hostname
                if host not in {"localhost", "127.0.0.1", "::1"}:
                    raise HTTPException(403, "pairing_required")
        if cross_site(request, origin):
            raise HTTPException(403, "origin_denied")
        q = body.question + ("\n" + body.context if body.context else "")
        streaming = wants_ndjson(accept)
        system, source, _ = switch.current()
        request_mode = mode if system == mode.system else replace(mode, system=system)
        record = log_record(request_mode, "ndjson" if streaming else "json", body.question, source)
        def save(row: dict, result=None) -> None:
            store.save(row, body.question, result)  # the question only, never the context

        save = save if store.enabled else None

        def refused(status: int, code: str, state: str):
            """A request answered with an error before (or instead of) the coach: its log line, then its row."""
            row = {**record, "status": state, "error_code": code}
            log(json.dumps(row, ensure_ascii=False))
            return JSONResponse({"detail": code}, status, background=BackgroundTask(save, row) if save else None)

        if not _valid_input(q, limits):
            return refused(422, "invalid_input", "invalid_input")
        if not slot.acquire(blocking=False):
            return refused(429, "coach_busy", "busy")
        try:
            exchange = Exchange(stream, q, request_mode, record, clock=clock, deadline_seconds=deadline_seconds,
                                release=slot.release, log=log, quick=quick, quick_seconds=quick_seconds, save=save)
        except Exception:
            slot.release()
            return refused(503, "coach_unavailable", "error")
        if streaming:
            return StagedResponse(exchange)
        after = BackgroundTask(exchange.persist) if save else None
        try:
            reply = exchange.reply()
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, exc.status_code, background=after)
        except Exception:
            return JSONResponse({"detail": "coach_unavailable"}, 503, background=after)
        if save:
            background.add_task(exchange.persist)
        return reply

    serve_live_admin(app, store, switch, mode.system, origin)

    @app.get("/downloads/PhraseRoom.apk")
    def android_package():
        apk = WEB.parent / "android" / "build" / "PhraseRoom.apk"
        if not apk.is_file():
            raise HTTPException(404, "apk_not_built")
        return FileResponse(apk, filename=apk.name, media_type="application/vnd.android.package-archive")

    if admin is not None:
        serve_admin(app, *admin)
    if serve_ui:
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    app.state.admin = admin
    return app


def deadline_seconds(value: str) -> float:
    """--deadline / COACH_DEADLINE_SECONDS: seconds from a request's start to its timeout, 1 to 3600."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number of seconds: {value!r}") from None
    if not 1 <= seconds <= MAX_DEADLINE_SECONDS:
        raise argparse.ArgumentTypeError(f"choose 1 to {MAX_DEADLINE_SECONDS:g} seconds, not {value!r}")
    return seconds


def arguments(argv=None, environ=os.environ) -> argparse.Namespace:
    """The local server's options. The deadline defaults to the deployment's 280 s; a relay or a slow
    provider may need longer (the relay connector waits up to 1750 s; the web app gives up at 300 s)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    parser.add_argument("--deadline", type=deadline_seconds,
                        default=environ.get("COACH_DEADLINE_SECONDS", "").strip() or str(DEADLINE_SECONDS),
                        help="seconds from a request's start to its timeout (default: COACH_DEADLINE_SECONDS or 280)")
    args = parser.parse_args(argv)
    args.parser = parser
    return args


if __name__ == "__main__":
    import uvicorn
    args = arguments()
    parser = args.parser
    if args.host != "localhost" and not ipaddress.ip_address(args.host).is_loopback and not os.environ.get("COACH_PAIR_CODE"):
        parser.error("Set COACH_PAIR_CODE before listening on a network interface.")
    request_store = RequestStore.from_environment(env_file=Path(__file__).resolve().parents[1] / "translation_agent_demo" / ".env")
    try:
        application = make_app(deadline_seconds=args.deadline, store=request_store)
    except ValueError as exc:  # an unknown COACH_SYSTEM or COACH_CONTINUATION, or a missing admin folder
        parser.error(str(exc))
    print(f"request log: {'on (PostgreSQL)' if request_store.enabled else 'off (no database URL)'}", flush=True)
    if args.deadline != DEADLINE_SECONDS:
        print(f"deadline: {args.deadline:g} s per request", flush=True)
    if application.state.admin:
        page, data = application.state.admin
        print(f"admin: http://{args.host}:{args.port}/admin/ (page {page}, data {data})", flush=True)
    uvicorn.run(application, host=args.host, port=args.port, access_log=False, proxy_headers=False)
