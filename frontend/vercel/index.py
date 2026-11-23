"""Vercel Python Function; the model secret is configured only in production."""

import os
from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

os.environ.update(
    LLM_PROVIDER="responses",
    RESPONSES_BASE_URL="https://apikey.casa/v1",
    LLM_MODEL="gpt-6.1-sol",
    EMBEDDING_PROVIDER="local",
)
os.environ["COACH_LOCAL_MODEL_DIR"] = str(
    Path(__file__).resolve().parents[1] / "encoder"
)
from frontend.request_log import RequestStore
from frontend.server import make_app
from frontend.staged import environment_quick
from frontend.vercel.coach import stream
from frontend.vercel.traces import record_run
from frontend.vercel.replay import read_trace, render_trace

# Mode: coach_settings (POST /admin/mode) > COACH_SYSTEM > agent; an unknown COACH_* value fails at start. The
# request log needs COACH_LOG_DATABASE_URL > DATABASE_URL > POSTGRES_URL. Quick line: COACH_QUICK_MODEL/_PROVIDER.
app = make_app(stream=stream, quick=environment_quick, serve_ui=False, public_access=True,
               store=RequestStore.from_environment(), record_run=record_run)


@app.get("/api/search", response_class=HTMLResponse)
def view_workflow(run_id: UUID):
    try:
        data = read_trace(run_id)
    except (psycopg.Error, KeyError):
        raise HTTPException(503, "workflow_storage_unavailable") from None
    if data is None:
        raise HTTPException(404, "workflow_not_found")
    return HTMLResponse(render_trace(data), headers={"Cache-Control": "private, no-store",
                        "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"})
