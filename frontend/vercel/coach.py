"""Read the small published transcript snapshot from the function bundle."""

from functools import lru_cache
import json
from pathlib import Path
import re

import numpy as np
from evaluation.snapshot_search import SnapshotSearch
from frontend.server import search_workers
from frontend.staged import StagedCoach
from translation_agent_demo.agents import CoachDependencies
from translation_agent_demo.agents.contracts import CorpusSearchHit
from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.local_embeddings import local_client

DATA = Path(__file__).resolve().parents[2] / "corpus"
WORKERS = search_workers()  # COACH_SEARCH_WORKERS, read when the function starts; a wrong value stops it


class PublishedCorpus:
    def __init__(self):
        payload = json.loads((DATA / "passages.json").read_text(encoding="utf8"))
        self.profile = payload["profile"]
        self.hits = tuple(
            CorpusSearchHit.model_validate_json(json.dumps(h)) for h in payload["hits"]
        )
        vectors = np.load(DATA / "vectors.npy", allow_pickle=False)
        if vectors.shape != (len(self.hits), self.profile["dimensions"]):
            raise ValueError("Unexpected published vector shape")
        self.vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def indices(self, language, feed_ids, document_ids):
        return [
            i
            for i, h in enumerate(self.hits)
            if (language is None or language == h.language)
            and (feed_ids is None or h.feed_id in feed_ids)
            and (document_ids is None or h.document_id in document_ids)
        ]

    def search(
        self,
        vector,
        *,
        limit,
        min_similarity,
        language,
        feed_ids,
        document_ids,
        literal_phrase=None,
    ):
        candidates = self.indices(language, feed_ids, document_ids)
        if literal_phrase is not None:
            phrase = literal_phrase.lower()
            candidates = [i for i in candidates if phrase in self.hits[i].text.lower()]
        v = np.asarray(vector, dtype=np.float32)
        scores = np.clip(self.vectors @ (v / np.linalg.norm(v)), -1, 1)
        if min_similarity is not None:
            candidates = [i for i in candidates if scores[i] >= min_similarity]
        candidates.sort(key=lambda i: (-float(scores[i]), self.hits[i].chunk_id))
        return tuple(
            self.hits[i].model_copy(update={"similarity": float(scores[i])})
            for i in candidates[:limit]
        )

    def count_literal(self, literal_phrase, *, language, feed_ids, document_ids):
        left = r"(?<!\w)" if re.match(r"\w", literal_phrase[0]) else ""
        right = r"(?!\w)" if re.match(r"\w", literal_phrase[-1]) else ""
        pattern = re.compile(left + re.escape(literal_phrase) + right, re.IGNORECASE)
        return sum(
            bool(pattern.search(self.hits[i].text))
            for i in self.indices(language, feed_ids, document_ids)
        )


@lru_cache(maxsize=1)
def dependencies():
    return chat_model(Settings.from_environment()), local_client(), PublishedCorpus()


def stream(question, mode, guard):
    """The staged coach (frontend/staged.py) over the bundled snapshot, in the app's mode (COACH_SYSTEM,
    COACH_CONTINUATION, read once by make_app)."""
    model, encoder, corpus = dependencies()
    return StagedCoach(  # the snapshot and the encoder are read-only: the six first-stage searches run at once
        CoachDependencies(model, SnapshotSearch(corpus, encoder), search_workers=WORKERS), mode
    ).stream(question, guard)
