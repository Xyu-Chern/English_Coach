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
from frontend.vercel.coach import answer

app = make_app(answer, serve_ui=False, public_access=True)
