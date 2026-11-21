"""Serve the learner clients and adapt the existing coach to a small HTTP API."""
import argparse
import hmac
import ipaddress
import os
import threading
from functools import lru_cache, partial
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from translation_agent_demo.agents import CoachDependencies, ExpressionCoach
from translation_agent_demo.agents.results import SourceCitation
from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.embeddings import embedding_client
from translation_agent_demo.storage.postgres import PostgresSettings, connect_database
from translation_agent_demo.tools.search_corpus import search_corpus

WEB = Path(__file__).with_name("web")


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


@lru_cache(maxsize=1)
def dependencies():
    return chat_model(Settings.from_environment()), embedding_client(), PostgresSettings.from_environment()


def ask_coach(question):
    model, encoder, db = dependencies()
    with connect_database(db) as conn:
        coach = ExpressionCoach(CoachDependencies(model, partial(search_corpus, conn=conn, embeddings=encoder)))
        return coach.answer(question)


def make_app(answer=ask_coach, *, serve_ui=True):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    origin = os.environ.get("COACH_WEB_ORIGIN", "").strip()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost", *([origin] if origin else [])],
                       allow_methods=["POST"], allow_headers=["Content-Type", "X-Coach-Code"],
                       allow_private_network=bool(origin))
    slot = threading.BoundedSemaphore(1)

    @app.post("/api/search", response_model=Reply)
    def search(body: Question, request: Request, x_coach_code: str = Header(default="")):
        code = os.environ.get("COACH_PAIR_CODE", "")
        if code and not hmac.compare_digest(code.encode(), x_coach_code.encode()):
            raise HTTPException(401, "pairing_required")
        if not code:
            host = request.url.hostname
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise HTTPException(403, "pairing_required")
        browser_origin = request.headers.get("origin")
        if browser_origin and (urlsplit(browser_origin).netloc != request.headers.get("host")
                               and browser_origin not in {"http://localhost", origin}):
            raise HTTPException(403, "origin_denied")
        if not slot.acquire(blocking=False):
            raise HTTPException(429, "coach_busy")
        try:
            q = body.question + ("\n" + body.context if body.context else "")
            result = answer(q)
            if result.status != "ok":
                raise HTTPException(422 if result.status == "invalid_input" else 503, result.error_code or "unavailable")
            return Reply(expressions=[item.model_dump(include={"expression", "key_phrase", "note", "citation"})
                                      for item in result.expressions or []], note=result.source_availability_note)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "coach_unavailable") from None
        finally:
            slot.release()

    @app.get("/downloads/PhraseRoom.apk")
    def android_package():
        apk = WEB.parent / "android" / "build" / "PhraseRoom.apk"
        if not apk.is_file():
            raise HTTPException(404, "apk_not_built")
        return FileResponse(apk, filename=apk.name, media_type="application/vnd.android.package-archive")

    if serve_ui:
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8787, type=int)
    args = parser.parse_args()
    if args.host != "localhost" and not ipaddress.ip_address(args.host).is_loopback and not os.environ.get("COACH_PAIR_CODE"):
        parser.error("Set COACH_PAIR_CODE before listening on a network interface.")
    uvicorn.run(make_app(), host=args.host, port=args.port, access_log=False, proxy_headers=False)
