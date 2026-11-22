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
from frontend.server import make_app
from frontend.vercel.coach import stream

# The mode comes from the project's COACH_SYSTEM (agent | baseline) and COACH_CONTINUATION (on | off);
# an unknown value fails here, when the function starts. A change applies from the next deployment.
app = make_app(stream=stream, serve_ui=False, public_access=True)
