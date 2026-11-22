"""Vercel Python Function; the model secret is configured only in production."""

import os
from pathlib import Path

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

# Mode: coach_settings (POST /admin/mode) > COACH_SYSTEM > agent; an unknown COACH_* value fails at start. The
# request log needs COACH_LOG_DATABASE_URL > DATABASE_URL > POSTGRES_URL. Quick line: COACH_QUICK_MODEL/_PROVIDER.
app = make_app(stream=stream, quick=environment_quick, serve_ui=False, public_access=True,
               store=RequestStore.from_environment())
