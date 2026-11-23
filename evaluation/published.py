"""Run the same paired harness against the repository's deployed, read-only corpus."""

import gzip
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from translation_agent_demo.config import Settings, environment_values
from .live import LiveEnvironment, file_sha256


def configured_bundle():
    value = environment_values().get("EVAL_PUBLISHED_BUNDLE")
    return Path(value).resolve() if value else None


def grading_corpus(bundle):
    if bundle is None:
        raise ValueError("Set EVAL_PUBLISHED_BUNDLE to the deployment package used for this run.")
    path = bundle / "corpus/passages.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        hits = json.load(stream)["hits"]
    return SimpleNamespace(sha256=file_sha256(path), chunks={str(h["chunk_id"]): h for h in hits})


class PublishedEnvironment(LiveEnvironment):
    def __init__(self, bundle):
        self.bundle = bundle
        self.snapshot_dir = bundle / "corpus"
        self.schema = "published_bundle"
        self.settings = Settings.from_environment()
        self.package = json.loads((self.snapshot_dir / "manifest.json").read_text())
        self.manifest = {
            "snapshot_id": bundle.name,
            "files": {"corpus.json.gz": {"sha256": file_sha256(self.snapshot_dir / "passages.json.gz")}},
            "profile": self.package["profile"],
        }

    def identity(self):
        from frontend.vercel import coach
        return {**super().identity(), "vectors_sha256": file_sha256(self.snapshot_dir / "vectors.npy"),
                "search_code_sha256": file_sha256(Path(coach.__file__)),
                "bundle_adapter_sha256": file_sha256(Path(__file__)),
                "encoder_sha256": file_sha256(self.bundle / "encoder/onnx/model.onnx"),
                "tokenizer_sha256": file_sha256(self.bundle / "encoder/tokenizer.json")}

    def check(self):
        from frontend.vercel.coach import PublishedCorpus
        from translation_agent_demo.providers.local_embeddings import MODEL
        if not self.settings.api_key or self.settings.provider != "responses":
            raise ValueError("Select the Responses provider and set RESPONSES_API_KEY.")
        if not self.settings.base_url.startswith("https://"):
            raise ValueError("The Responses provider requires HTTPS.")
        self.embeddings()
        self.published = PublishedCorpus(self.snapshot_dir)
        if (self.published.profile != self.package["profile"] or self.published.profile["model"] != MODEL
                or not self.package["complete"] or len(self.published.hits) != self.package["approved_chunks"]):
            raise ValueError("Published corpus is incomplete or mismatched.")

    @contextmanager
    def store(self):
        yield self.published
