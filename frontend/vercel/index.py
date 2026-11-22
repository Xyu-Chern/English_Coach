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
from frontend.quick import environment_quick
from frontend.request_log import RequestStore
from frontend.server import make_app
from frontend.vercel.coach import stream

# The mode: the database's coach_settings['coach_system'] (set from /admin, POST /admin/mode; read again
# every 10 s) > the project's COACH_SYSTEM (agent | baseline) > agent. COACH_CONTINUATION (on | off) comes
# from the project only; an unknown value fails here, when the function starts.
# The database (Neon): COACH_LOG_DATABASE_URL > DATABASE_URL > POSTGRES_URL; without one the function keeps
# no request rows and /admin/mode cannot change the mode. vercel.json routes /admin/requests.json and
# /admin/mode here.
# Streams get the quick line from COACH_QUICK_MODEL / COACH_QUICK_PROVIDER (default: the model above).
app = make_app(stream=stream, quick=environment_quick, serve_ui=False, public_access=True,
               store=RequestStore.from_environment())
