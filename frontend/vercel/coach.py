"""Read the small published transcript snapshot from the function bundle."""

from functools import lru_cache
import gzip
from pathlib import Path
import re

import numpy as np
from pydantic import BaseModel
from evaluation.snapshot_search import SnapshotSearch
from frontend.server import search_workers
from frontend.staged import StagedCoach
from translation_agent_demo.agents import CoachDependencies
from translation_agent_demo.agents.contracts import CorpusSearchHit
from translation_agent_demo.config import Settings
from translation_agent_demo.providers import chat_model
from translation_agent_demo.providers.batched_embeddings import PrefetchedEmbeddings
from translation_agent_demo.providers.local_embeddings import local_client
from translation_agent_demo.tools.search_corpus import query_text

DATA = Path(__file__).resolve().parents[2] / "corpus"
WORKERS = search_workers()  # COACH_SEARCH_WORKERS, read when the function starts; a wrong value stops it


class _Published(BaseModel):
    profile: dict
    hits: tuple[CorpusSearchHit, ...]


class PublishedCorpus:
    """passages.json from frontend.vercel.package; hits of an older snapshot without audio fields have no audio."""

    def __init__(self, directory=None):
        if directory is None:
            directory = DATA
        # One pass from the JSON text to the records, without a dict per hit first: a 36k-passage snapshot then
        # peaks near its final size instead of about twice it (Vercel's function has 2 GB).
        packed = directory / "passages.json.gz"  # own_snapshot.py gzips it; frontend.vercel.package writes plain JSON
        raw = gzip.decompress(packed.read_bytes()) if packed.is_file() else (directory / "passages.json").read_bytes()
        payload = _Published.model_validate_json(raw)
        self.profile = payload.profile
        self.hits = payload.hits
        # Narrower vectors (own_snapshot.py: float16, MiniLM's 384) omit the encoder's zero padding to the profile's
        # width; search reads only that many query columns, which gives the padded cosine.
        vectors = np.asarray(np.load(directory / "vectors.npy", allow_pickle=False), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(self.hits) or not 0 < vectors.shape[1] <= self.profile["dimensions"]:
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
        scores = np.clip(self.vectors @ (v[: self.vectors.shape[1]] / np.linalg.norm(v)), -1, 1)
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


class PreparedSearch:
    """One request's snapshot search; prepare (session.prefetching) embeds its queries in one MiniLM pass."""

    def __init__(self, corpus, encoder):
        self.encoder = PrefetchedEmbeddings(encoder)
        self.search = SnapshotSearch(corpus, self.encoder)

    def __call__(self, args):
        return self.search(args)

    def prepare(self, searches) -> None:
        self.encoder.prefetch([query_text(args) for args in searches])


def stream(question, mode, guard):
    """The staged coach (frontend/staged.py) over the bundled snapshot, in the app's mode."""
    model, encoder, corpus = dependencies()
    return StagedCoach(  # the snapshot and the encoder are read-only: the first-stage searches run at once
        CoachDependencies(model, PreparedSearch(corpus, encoder), search_workers=WORKERS), mode
    ).stream(question, guard)
