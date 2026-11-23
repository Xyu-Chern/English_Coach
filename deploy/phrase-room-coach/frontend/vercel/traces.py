"""Store operational metrics without user input, generated text or provider payloads."""
import logging
import os

import psycopg
from psycopg.types.json import Jsonb


def record_run(result):
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    steps = []
    for span in result.trace:
        details = span.details
        step = span.model_dump(exclude={"details"})
        step["start_ms"] = details.get("started_ms", 0)
        for key in ("input_tokens", "output_tokens", "verified", "with_example", "expressions"):
            if isinstance(details.get(key), int):
                step[key] = details[key]
        if "hits" in details:
            step["hit_count"] = len(details["hits"])
        if "skipped" in details:
            step["skipped"] = True
        steps.append(step)
    items = result.expressions or []
    metrics = dict(variant=result.variant, status=result.status, error_code=result.error_code,
                   elapsed_ms=result.elapsed_ms, model_rounds=result.model_rounds,
                   searches=len(result.tool_calls), expressions=len(items),
                   verified=sum(item.citation is not None for item in items),
                   usage=result.usage.model_dump(), steps=steps)
    try:
        with psycopg.connect(url, connect_timeout=3) as db:
            db.execute("SET LOCAL statement_timeout = '3s'")
            db.execute("INSERT INTO public.coach_workflow_runs (request_id, metrics) VALUES (%s,%s) "
                       "ON CONFLICT (request_id) DO NOTHING", (result.request_id, Jsonb(metrics)))
        return True
    except psycopg.Error as error:
        logging.getLogger(__name__).warning("Workflow metrics unavailable (%s)", type(error).__name__)
        return False
