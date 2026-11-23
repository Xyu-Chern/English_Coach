"""Read a single recorded workflow and render its shareable timeline."""
import json
import os
from pathlib import Path

import psycopg


def read_trace(run_id):
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as db:
        row = db.execute(
            "SELECT recorded_at, metrics FROM public.coach_workflow_runs WHERE request_id = %s",
            (run_id,),
        ).fetchone()
    if row is not None:
        return {"id": str(run_id), "recorded_at": row[0].isoformat(), "metrics": row[1]}


def render_trace(data):
    template = Path(__file__).with_name("workflow_report.html").read_text(encoding="utf8")
    labels = (Path(__file__).resolve().parents[1] / "web/workflow.js").read_text(encoding="utf8")
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    return template.replace("__WORKFLOW_JS__", labels).replace("__RUN_JSON__", payload)
