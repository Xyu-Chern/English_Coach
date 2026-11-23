"""Serve the learner clients and adapt the staged coach (frontend/staged.py) to a small HTTP API; the wire
formats and log fields are in frontend/README.md.

POST /api/search {question, context} -> one JSON reply {"expressions", "note"}, or with Accept:
application/x-ndjson one line per event: quick (optional, only first, within 3 s; a generated suggestion),
first (verified examples only; pending=false ends), final (after a first: its items, then only the examples
verified later), error (timeout | coach_unavailable | <coach code>). Refusals are HTTP errors before any line;
a failure after verified examples keeps them. GET /api/audio/alignment: where a cited quote plays.

The coach runs in its own thread until the deadline (280 s, inside Vercel's 300 s; locally --deadline) or the
client leaves; one request per process (coach_busy otherwise), its slot returned only once the work has stopped.
COACH_DAILY_LIMIT caps the requests of a day for everyone (frontend/request_log.py DailyLimit): one count per
request that got the slot, before any model call; over the cap 429 daily_limit, no countable database 503
daily_limit_unavailable; X-Coach-Daily-Limit / -Remaining headers. Each request past the access checks is one
log line and, with a database (frontend/request_log.py), one row after the response. GET /admin/ serves the
admin page and data.json; GET /admin/requests.json, GET/POST /admin/mode (X-Admin-Token when COACH_ADMIN_TOKEN
is set; on Vercel, without it, no change at all) read the request log and switch the mode (DB > COACH_SYSTEM >
agent, cached 10 s).
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
from uuid import UUID, uuid4

import anyio
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from translation_agent_demo.agents.session import stage_observer, announce
from frontend.audio_align import AudioAlignments
from frontend.request_log import (MAX_LIMIT, MODE_CACHE_SECONDS, MODES, DailyLimit, ModeSwitch, RequestStore,
                                  StoreError)
from frontend.staged import (QUICK_SECONDS, CoachMode, Failed, Final, First, Guard, Quick, StagedCoach,
                             _environment_answerer, environment_quick, is_terminal)
from translation_agent_demo.agents import CoachDependencies, SessionLimits
from translation_agent_demo.agents.coach import _valid_input
from translation_agent_demo.agents.results import SourceCitation
from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.batched_embeddings import PrefetchedEmbeddings
from translation_agent_demo.providers.embeddings import embedding_client
from translation_agent_demo.storage.postgres import PostgresSettings, connect_database
from translation_agent_demo.tools.search_corpus import query_text, search_corpus

WEB = Path(__file__).with_name("web")
ADMIN = Path(__file__).with_name("admin")
ROOT = Path(__file__).resolve().parents[1]
ADMIN_DATA_FILES = ("data.json", "data-traces.json")  # what an /admin page fetches (frontend/admin_data.py)
NDJSON = "application/x-ndjson"
DEADLINE_SECONDS = 280.0  # Vercel stops the function at maxDuration 300 s; stop the work first
MAX_DEADLINE_SECONDS = 3600.0  # the most the local server's --deadline / COACH_DEADLINE_SECONDS may ask for
NOINDEX = {"X-Robots-Tag": "noindex"}  # /admin is open to anyone with the address (D4), not to search engines
DAILY_HEADERS = ("X-Coach-Daily-Limit", "X-Coach-Daily-Remaining")  # sent with a COACH_DAILY_LIMIT; CORS exposes
POLL_SECONDS = 0.05  # how often a stream checks for the coach's next event
QUESTION_HEAD_CHARS = 40  # how much of the request the log line keeps (D2, D5)
SEARCH_WORKERS = 6  # the first stage's searches at once (COACH_SEARCH_WORKERS, 1-9)
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


class StageEvent(BaseModel):
    stage: str


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


def warm_up() -> None:
    """Load in the background what the local index's first request would wait for (the clients, tiktoken's
    tokenizer, the quick model); a failure is left for the request to report."""
    try:
        dependencies()
        import tiktoken
        tiktoken.get_encoding("cl100k_base")
    except Exception:
        pass
    try:
        _environment_answerer()
    except Exception:
        pass


def search_workers(environ=os.environ) -> int:
    """COACH_SEARCH_WORKERS: a step's independent searches at once, 1-9; another value stops the start."""
    value = environ.get("COACH_SEARCH_WORKERS", "").strip() or str(SEARCH_WORKERS)
    if not value.isdigit() or not 1 <= int(value) <= 9:
        raise ValueError(f"COACH_SEARCH_WORKERS must be 1 to 9, not {value!r}.")
    return int(value)


class _Connections:
    """One request's PostgreSQL connections, one per search running at once; the first opens at once (no
    database: no model call). One still in use at close() closes when its search returns. prepare(searches)
    embeds their queries in one provider call (session.prefetching calls it)."""

    def __init__(self, db, encoder):
        self.encoder = PrefetchedEmbeddings(encoder)
        self.db, self._lock, self._closed = db, threading.Lock(), False
        self._idle = [connect_database(db)]

    def prepare(self, searches) -> None:
        self.encoder.prefetch([query_text(args) for args in searches])

    def __call__(self, args):  # the coach's search tool: this object, so session.prefetching finds prepare
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
    """The local deployment: the PostgreSQL transcript index."""
    model, encoder, db = dependencies()
    connections = _Connections(db, encoder)
    try:
        coach = StagedCoach(CoachDependencies(model, connections, search_workers=workers), mode)
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
            if media == NDJSON and float(weight) > 0:
                return True
        except ValueError:
            pass
    return False


def log_record(mode: CoachMode, transport: str, question: str, mode_source: str = "env") -> dict:
    """The log line's fields before anything happened: of the request only the question's head, never the
    context or the answer (D2, D5). mode_source: "db" (coach_settings) or "env" (COACH_SYSTEM or default)."""
    return {"event": "coach_request", "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request_id": str(uuid4()), "mode": mode.system, "mode_source": mode_source,
            "continuation_setting": mode.continuation_setting, "first_stage": mode.first_stage.label(),
            "transport": transport, "status": None, "error_code": None, "verified_first": None,
            "added_final": None, "verified_final": None, "continuation": None, "invariant_ok": None,
            "quick_ms": None, "first_ms": None, "total_ms": 0,
            "llm_calls": 0, "searches": 0, "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
            "disconnected": False, "question_head": question[:QUESTION_HEAD_CHARS]}


class Exchange:
    """One answered POST: the coach works in its own thread; the request reads its events until the deadline.

    Log fields shared with frontend/admin_data.py: added_final counts examples verified after a first answer
    (0 without one), verified_final those the learner ends with. first_ms (when the first answer was sent) and
    quick_ms (when the quick line was) exist only for a stream: a JSON client sees nothing before total_ms."""

    def __init__(self, stream, question: str, mode: CoachMode, record: dict, *, clock, deadline_seconds: float,
                 release, log, quick=None, quick_seconds: float = QUICK_SECONDS, save=None, prefetch=None,
                 record_run=None, progress=False):
        self.clock, self.record, self.log, self._release = clock, record, log, release
        self.record_run = record_run
        self.progress = progress
        self.run_id = None
        self.save, self.prefetch = save, prefetch  # save(record, result): the row; prefetch(chunk_ids): audio
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

    def _once(self, flag: str) -> bool:  # True the first time only
        with self._lock:
            done = getattr(self, flag)
            setattr(self, flag, True)
            return not done

    def _quick(self, quick, question: str, seconds: float) -> None:  # queued only in time and while on
        try:
            answer = None if self.guard.stopped else quick(question)
        except Exception:
            answer = None
        if isinstance(answer, Quick) and not self.guard.stopped and self.clock() - self.started <= seconds:
            self.events.put(answer)

    def _work(self, stream, question: str, mode: CoachMode) -> None:
        events = None
        observe = self.streaming and self.progress and self.record_run is not None
        token = stage_observer.set((lambda stage: self.events.put(StageEvent(stage=stage))) if observe else None)
        try:
            announce("prepare")
            events = iter(stream(question, mode, self.guard))
            for event in events:
                if is_terminal(event):  # the coach's last step: no call follows it
                    self.release()
                    result = getattr(event, "result", None)
                    if self.record_run and result is not None:
                        try:
                            if self.record_run(result):
                                self.run_id = str(result.request_id)
                        except Exception:
                            pass  # Optional telemetry cannot discard a learner's answer.
                self.events.put(event)
                if is_terminal(event) or self.guard.stopped:
                    break
        except Exception:
            self.release()
            self.events.put(Failed("coach_unavailable"))
        finally:
            try:
                getattr(events, "close", lambda: None)()
            except Exception:
                pass
            self.release()
            stage_observer.reset(token)
            self.events.put(_DONE)

    def release(self) -> None:
        """Return the request slot once, when the work has stopped, before the event that ends it is queued (a
        learner who asks again at once finds the slot free). A request that ends first (the deadline, a client
        that left) only stops the work: the call under way finishes before the next request can run."""
        if self._once("_released"):
            self._release()

    def elapsed_ms(self) -> int:
        return round((self.clock() - self.started) * 1000)

    def wire(self, event) -> BaseModel | None:
        """The line for one event (a coach event, _DONE or the quick answer), recorded for the log. None: a
        quick answer that would no longer be the first line."""
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
            self.first, sent = event, len(event.expressions)
            self.record.update(first_ms=self.elapsed_ms() if self.streaming else None, verified_first=sent)
            if not event.pending:
                self.record.update(status="ok", continuation=event.continuation, added_final=0, verified_final=sent,
                                   invariant_ok=True)
            self.align_later(event.expressions)
            return FirstEvent(expressions=learner(event.expressions), pending=event.pending, note=event.note)
        if isinstance(event, Final):
            expressions, added = event.expressions, list(event.added)
            if self.first is None:
                self.record.update(verified_first=event.verified_first, added_final=0,
                                   verified_final=sum(1 for item in expressions if item.citation is not None))
            else:
                sent = len(self.first.expressions)
                self.record.update(added_final=len(added), verified_final=sent + len(added))
                if self.streaming:  # after a first: the sent items, then only what was verified later (D1)
                    expressions = (*expressions[:sent], *(expressions[i] for i in added))
                    added = list(range(sent, len(expressions)))
            self.record.update(status="declined" if event.declined else "ok", continuation=event.continuation,
                               invariant_ok=event.kept_first)
            self.align_later(expressions if self.first is None else [expressions[i] for i in added])
            return FinalEvent(expressions=learner(expressions), added=added, note=event.note)
        return self.fail("timeout" if self.guard.expired else event.code, event.continuation)

    def align_later(self, items) -> None:
        """Align the cited examples a stream sends before the learner presses play; never fails the stream."""
        if self.prefetch is None or not self.streaming:
            return
        try:
            self.prefetch([i.citation.chunk_id for i in items if i.citation is not None and i.citation.audio_url])
        except Exception:
            pass

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
                if isinstance(event, Quick):  # never asked for here
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
                    if isinstance(event, StageEvent):
                        yield event.model_dump_json() + "\n"
                        continue
                    line = self.wire(event)
                    if line is None:
                        continue
                    finished = not isinstance(event, Quick) and (event is _DONE or is_terminal(event))
                if not isinstance(line, QuickEvent):
                    self.sent = True
                payload = line.model_dump(mode="json")
                if finished and self.progress and self.record_run:
                    # Earlier mobile clients read the terminal answer envelope; newer ones use type.
                    if isinstance(line, (FirstEvent, FinalEvent)):
                        payload["run_id"] = self.run_id
                        payload["answer"] = {"run_id": self.run_id, "expressions": payload["expressions"],
                                             "note": line.note}
                    elif isinstance(line, ErrorEvent):
                        payload["error"] = line.code
                yield json.dumps(payload, ensure_ascii=False) + "\n"
        finally:
            self.close(left=not finished)

    def close(self, *, left: bool = False) -> None:
        """Stop the work and print the log line, once (the work's thread returns the slot when it ends). left:
        the client went away before the stream's last line (or its first: StagedResponse closes an exchange
        whose body never ran)."""
        if not self._once("_closed"):
            return
        if left:
            self.record.update(disconnected=True, status="disconnected", continuation="ran" if self.first else "none")
        self.guard.stop()
        self.record.update(total_ms=self.elapsed_ms(), **self.guard.usage())
        if self.record["status"] is None:
            self.record["status"] = "error"
        self.log(json.dumps(self.record, ensure_ascii=False))

    def persist(self) -> None:
        """Write the database row once, after close(); never raises."""
        if self.save is None or not self._closed or not self._once("_persisted"):
            return
        try:
            self.save(self.record, self.result)
        except Exception:
            pass


class StagedResponse(StreamingResponse):
    """The NDJSON response of one exchange, which is closed however the response ends: a client that leaves
    before the body starts never runs lines() on either ASGI disconnect path (spec 2.3: Starlette cancels the
    body; 2.4: the first send fails). Then the row is written, shielded from the cancellation."""

    def __init__(self, exchange: Exchange, headers: dict | None = None):
        super().__init__(exchange.lines(), media_type=NDJSON,
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", **(headers or {})})
        self.exchange = exchange

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.exchange.close(left=True)  # nothing when the stream already closed it
            if self.exchange.save is not None:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(self.exchange.persist)


# ------------------------------------------------------------------ the admin page
def admin_folders(environ=os.environ) -> tuple[Path, Path] | None:
    """(page folder, data folder): COACH_ADMIN_DIR / COACH_ADMIN_DATA when set, else frontend/admin for both;
    None without a page. ValueError for a missing folder or a data folder without data.json."""
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
    """Adds X-Robots-Tag: noindex to every response of the ASGI app it wraps."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_marked(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-robots-tag", b"noindex")]}
            await send(message)
        await self.app(scope, receive, send_marked)


def serve_admin(app: FastAPI, page: Path, data: Path) -> None:
    """GET /admin/ from the page folder and /admin/<data file> from the data folder, open (D4) and noindex like
    the deployment's. Pages fetch their data relatively, so /admin redirects to /admin/."""
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
def mode_locked(environ=os.environ) -> bool:
    """A public deployment (Vercel sets VERCEL) without COACH_ADMIN_TOKEN: nobody may switch the mode there.
    A local server without a token stays open."""
    return bool(environ.get("VERCEL", "").strip()) and not environ.get("COACH_ADMIN_TOKEN", "")


def serve_live_admin(app: FastAPI, store: RequestStore, switch: ModeSwitch, fallback: str, origin: str) -> None:
    """GET /admin/requests.json and GET/POST /admin/mode, registered before the /admin static mount."""
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
        return {"mode": current, "source": source, "updated_at": updated_at,
                "writable": store.enabled and not mode_locked(),
                "token_required": bool(os.environ.get("COACH_ADMIN_TOKEN", "")), "history": history}

    def check_token(value: str):
        if mode_locked():
            refuse(403, "admin_token_required")
        token = os.environ.get("COACH_ADMIN_TOKEN", "")
        if token and not hmac.compare_digest(token.encode(), value.encode()):
            refuse(401, "token_required")

    @app.get("/admin/requests.json", include_in_schema=False)
    def admin_requests(limit: int = Query(300, ge=1, le=MAX_LIMIT), x_admin_token: str = Header(default="")):
        check_token(x_admin_token)
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
        check_token(x_admin_token)
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
             mode_cache_seconds: float = MODE_CACHE_SECONDS, alignments: AudioAlignments | None = None,
             daily: DailyLimit | None = None, record_run=None):
    """stream(question, mode, guard) -> events (the staged coach) answers, else answer(question) -> RunResult as
    one final answer, else the local PostgreSQL index, which also gets environment_quick as quick(question) ->
    Quick | None for its streams. Read now, a wrong value stops the start: mode (CoachMode.from_environment),
    COACH_SEARCH_WORKERS for the local index, COACH_ADMIN_DIR / _DATA with serve_ui, COACH_AUDIO_ALIGN,
    COACH_DAILY_LIMIT / _TZ. store: the request log, mode switch and daily count; its tables are ensured now (a
    database that is down stops nothing), and without one nothing is written and every request runs in
    mode.system. daily: the cap (default DailyLimit.from_environment over store; with a cap and no database
    every request is refused). alignments: GET /api/audio/alignment and the stream's prefetch (default
    AudioAlignments.from_environment, local with the local index)."""
    mode = mode or CoachMode.from_environment()
    admin = admin_folders() if serve_ui else None
    if alignments is None:
        alignments = AudioAlignments.from_environment(local=stream is None and answer is None)
    if quick is None and stream is None and answer is None:
        quick = environment_quick
    if stream is None and answer is None:  # the local index: load its clients before the first request
        threading.Thread(target=warm_up, name="coach-warm-up", daemon=True).start()
    stream = stream or (answering(answer) if answer is not None else partial(local_stream, workers=search_workers()))
    log = log or (lambda line: print(line, flush=True))
    store = store or RequestStore(None)
    daily = daily or DailyLimit.from_environment(store)
    if store.enabled:
        store.ensure()
    switch = ModeSwitch(store, mode.system, ttl=mode_cache_seconds)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    origin = os.environ.get("COACH_WEB_ORIGIN", "").strip()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost", *([origin] if origin else [])],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Coach-Code"],
                       expose_headers=[*DAILY_HEADERS, "X-Coach-Run"], allow_private_network=bool(origin))
    slot = threading.BoundedSemaphore(1)
    limits = SessionLimits()

    @app.post("/api/search", response_model=Reply)
    def search(body: Question, request: Request, response: Response, background: BackgroundTasks,
               x_coach_code: str = Header(default=""), accept: str = Header(default="")):
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
        # the row keeps the question only, never the context
        save = (lambda row, result=None: store.save(row, body.question, result)) if store.enabled else None

        def refused(status: int, code: str, state: str, headers: dict | None = None):
            """An error before (or instead of) the coach: its log line, then its row."""
            row = {**record, "status": state, "error_code": code}
            log(json.dumps(row, ensure_ascii=False))
            return JSONResponse({"detail": code}, status, headers=headers,
                                background=BackgroundTask(save, row) if save else None)

        if not _valid_input(q, limits):
            return refused(422, "invalid_input", "invalid_input")
        if not slot.acquire(blocking=False):
            return refused(429, "coach_busy", "busy")
        quota = {}  # the daily cap's headers: this request is counted once, here, before any model call
        if daily.enabled:
            quota[DAILY_HEADERS[0]] = str(daily.limit)
            try:
                allowed, left = daily.take()
            except StoreError:  # never unmetered: no count, no coach
                slot.release()
                return refused(503, "daily_limit_unavailable", "error", quota)
            quota[DAILY_HEADERS[1]] = str(left)
            if not allowed:
                slot.release()
                return refused(429, "daily_limit", "daily_limit", quota)
        try:
            exchange = Exchange(stream, q, request_mode, record, clock=clock, deadline_seconds=deadline_seconds,
                                release=slot.release, log=log, quick=quick, quick_seconds=quick_seconds, save=save,
                                prefetch=alignments.prefetch if alignments.aligning else None, record_run=record_run,
                                progress="progress=1" in accept or accept.strip() == NDJSON + ", application/json")
        except Exception:
            slot.release()
            return refused(503, "coach_unavailable", "error", quota)
        if streaming:
            return StagedResponse(exchange, quota)
        after = BackgroundTask(exchange.persist) if save else None
        try:
            reply = exchange.reply()
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, exc.status_code, headers=quota, background=after)
        except Exception:
            return JSONResponse({"detail": "coach_unavailable"}, 503, headers=quota, background=after)
        if save:
            background.add_task(exchange.persist)
        if exchange.run_id:
            response.headers['X-Coach-Run'] = exchange.run_id
        response.headers.update(quota)
        return reply

    @app.get("/api/audio/alignment")
    def audio_alignment(request: Request, chunk_id: UUID, quote: str = Query(min_length=1, max_length=800),
                        x_coach_code: str = Header(default="")):
        """The same access rules as /api/search (it may start a local alignment); never an error for an
        unknown chunk."""
        if not public_access:
            code = os.environ.get("COACH_PAIR_CODE", "")
            if code and not hmac.compare_digest(code.encode(), x_coach_code.encode()):
                raise HTTPException(401, "pairing_required")
            if not code and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise HTTPException(403, "pairing_required")
        if cross_site(request, origin):
            raise HTTPException(403, "origin_denied")
        return JSONResponse(alignments.lookup(chunk_id, quote), headers={"Cache-Control": "no-store"})

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
    app.state.alignments = alignments
    app.state.daily = daily
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
    """The local server's options; a relay or a slow provider may need a deadline over 280 s (the relay
    connector waits up to 1750 s; the web app gives up at 300 s)."""
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
    request_store = RequestStore.from_environment(env_file=ROOT / "translation_agent_demo" / ".env")
    try:
        application = make_app(deadline_seconds=args.deadline, store=request_store)
    except ValueError as exc:  # an unknown COACH_SYSTEM, COACH_CONTINUATION or COACH_DAILY_*, a missing admin folder
        parser.error(str(exc))
    print(f"request log: {'on (PostgreSQL)' if request_store.enabled else 'off (no database URL)'}", flush=True)
    print(f"daily limit: {application.state.daily.describe()}"
          + (" - no database URL: every request is refused" if application.state.daily.enabled
             and not request_store.enabled else ""), flush=True)
    print(f"audio alignment: {application.state.alignments.describe()}", flush=True)
    if args.deadline != DEADLINE_SECONDS:
        print(f"deadline: {args.deadline:g} s per request", flush=True)
    if application.state.admin:
        page, data = application.state.admin
        print(f"admin: http://{args.host}:{args.port}/admin/ (page {page}, data {data})", flush=True)
    uvicorn.run(application, host=args.host, port=args.port, access_log=False, proxy_headers=False)
