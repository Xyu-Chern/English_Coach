"""Paid-run dependencies: the configured chat model, query embeddings and a verified snapshot.

Nothing here imports or changes a snapshot or a source permission. Before any paid call
the snapshot files are verified against their manifest, the imported database copy is
verified, and today's source rights are re-checked.

The chat model is OpenAI's pinned snapshot by default; LLM_PROVIDER=anthropic runs Claude
with LLM_MODEL as given (Claude ids such as claude-haiku-5-5 are complete without a date).
Query embeddings stay on OpenAI either way: the frozen corpus vectors were made with them.
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.openai_embeddings import OpenAIEmbeddingClient, OpenAIEmbeddingSettings
from translation_agent_demo.storage.postgres import PostgresSettings, connect_database

from .freeze import verify_snapshot
from .snapshot_store import SnapshotStore

MODEL, MODEL_SNAPSHOT, PROVIDER = "gpt-5.4-mini", "gpt-5.4-mini-2026-03-17", "https://api.openai.com/v1"
MAX_COMPLETION_TOKENS = 1200
CLAUDE_MAX_TOKENS = 16000  # adaptive thinking counts toward max_tokens, so OpenAI's 1200 would cut replies off
SNAPSHOT_DIR = Path(__file__).resolve().parent / ".local/snapshots/corpus-20261116-full-v2"
SNAPSHOT_SCHEMA = "evaluation_snapshot_v2"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class LiveEnvironment:
    snapshot_dir: Path = SNAPSHOT_DIR
    schema: str = SNAPSHOT_SCHEMA

    def __post_init__(self):
        self.manifest = json.loads((self.snapshot_dir / "manifest.json").read_text())
        self.settings = Settings.from_environment()
        self.database = None

    @property
    def claude(self) -> bool:
        return self.settings.provider == "anthropic"

    def identity(self) -> dict:
        """What a run manifest records about the chat model and the corpus (no secrets).

        The judge is not part of it: it changes no attempt, so the run manifest records it
        separately and grading checks it (grader.check_judge)."""
        if self.claude:  # no temperature is sent; effort None means the model's default
            chat = {"provider": "anthropic", "base_url": self.settings.base_url, "model": self.settings.model,
                    "effort": self.settings.effort, "temperature": None, "max_completion_tokens": CLAUDE_MAX_TOKENS,
                    "max_retries": self.settings.max_retries}
        else:
            chat = {"provider": "openai", "base_url": PROVIDER, "model": MODEL_SNAPSHOT, "effort": None,
                    "temperature": 0, "max_completion_tokens": MAX_COMPLETION_TOKENS, "max_retries": 0}
        return {**chat, "timeout_seconds": self.settings.timeout_seconds,
                "snapshot_id": self.manifest["snapshot_id"], "snapshot_schema": self.schema,
                "snapshot_manifest_sha256": file_sha256(self.snapshot_dir / "manifest.json"),
                "corpus_sha256": self.manifest["files"]["corpus.json.gz"]["sha256"],
                "embedding_model": self.manifest["profile"]["model"],
                "embedding_dimensions": self.manifest["profile"]["dimensions"]}

    def check(self) -> None:
        """Refuse to start a paid run unless the provider and the snapshot are exactly as expected."""
        if self.claude:
            if not self.settings.model.startswith("claude-") or not self.settings.api_key:
                raise SystemExit("Set LLM_MODEL to a Claude model id (e.g. claude-haiku-5-5) and ANTHROPIC_API_KEY.")
        elif self.settings.model != MODEL or self.settings.base_url != PROVIDER or not self.settings.api_key:
            raise SystemExit(f"Set the OpenAI provider with LLM_MODEL={MODEL} and an API key.")
        self.embeddings()  # fails here, before any paid call, when no OpenAI embedding key is configured
        self.database = PostgresSettings.from_environment()
        with connect_database(self.database) as connection:
            verified = verify_snapshot(self.snapshot_dir, live_conn=connection)
            store = SnapshotStore(connection, self.manifest["snapshot_id"], schema=self.schema,
                                  expected_manifest_sha256=verified["manifest_sha256"])
            store.verify(check_live_rights=True)

    def chat_model(self):
        """Both systems' chat model: Claude as configured, or the pinned OpenAI snapshot."""
        if self.claude:
            return chat_model(self.settings, max_output_tokens=CLAUDE_MAX_TOKENS)
        return chat_model(replace(self.settings, model=MODEL_SNAPSHOT), max_output_tokens=MAX_COMPLETION_TOKENS)

    def embeddings(self) -> OpenAIEmbeddingClient:
        return OpenAIEmbeddingClient(OpenAIEmbeddingSettings.from_environment())

    @contextmanager
    def store(self):
        """A fresh database connection per attempt, so parallel attempts never share one."""
        with connect_database(self.database or PostgresSettings.from_environment()) as connection:
            yield SnapshotStore(connection, self.manifest["snapshot_id"], schema=self.schema,
                                expected_manifest_sha256=file_sha256(self.snapshot_dir / "manifest.json"))
