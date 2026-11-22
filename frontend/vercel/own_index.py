"""Our own Vercel deployment's function; python -m frontend.vercel.own_snapshot package copies it to api/search.py.

Unlike index.py, the chat model comes from the project's environment variables (LLM_PROVIDER, LLM_MODEL and the
provider's key, such as ANTHROPIC_API_KEY; default anthropic and claude-haiku-5-5). Search always reads the bundled
snapshot with the bundled MiniLM encoder.
"""

import os
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "anthropic")
os.environ.setdefault("LLM_MODEL", "claude-haiku-5-5")
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["COACH_LOCAL_MODEL_DIR"] = str(Path(__file__).resolve().parents[1] / "encoder")
from frontend.request_log import RequestStore
from frontend.server import make_app
from frontend.staged import environment_quick
from frontend.vercel.coach import stream

# As index.py: mode coach_settings > COACH_SYSTEM > agent; the request log, mode switch and COACH_DAILY_LIMIT need
# COACH_LOG_DATABASE_URL > DATABASE_URL > POSTGRES_URL; COACH_ADMIN_TOKEN guards POST /admin/mode.
app = make_app(stream=stream, quick=environment_quick, serve_ui=False, public_access=True,
               store=RequestStore.from_environment())
