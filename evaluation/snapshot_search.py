"""The coach's search tool, served from the frozen snapshot instead of the live corpus.

Each call embeds the query (the only paid part), searches the imported snapshot
(literal phrase first, meaning-similarity fallback), counts whole-word literal
occurrences across the whole snapshot, and keeps an observation of the
ranked passages so an attempt can be replayed and audited later.
"""

import hashlib
import time

from translation_agent_demo.agents.contracts import SearchCorpusArgs, SearchCorpusError, SearchCorpusResult
from translation_agent_demo.providers.embedding_protocol import EmbeddingError
from translation_agent_demo.storage.postgres import CorpusStorageError


class SnapshotSearch:
    """One instance per attempt: observations belong to that attempt."""

    def __init__(self, store, embeddings):
        self.store, self.embeddings = store, embeddings
        self.observations: list[dict] = []

    def __call__(self, args: SearchCorpusArgs) -> SearchCorpusResult:
        started = time.perf_counter()
        observation = {"query": args.query, "context": args.context, "literal_phrase": args.literal_phrase,
                       "feed_ids": args.feed_ids, "input_tokens": None, "search_mode": None,
                       "literal_candidate_count": None, "literal_corpus_count": None, "status": "error", "ranked_candidates": []}
        self.observations.append(observation)
        text = args.query if args.context is None else f"Expression or meaning: {args.query}\nContext: {args.context}"
        try:
            batch = self.embeddings.embed_texts((text,))
            observation["input_tokens"] = batch.input_tokens
            profile = self.store.profile
            if batch.model != profile["model"] or batch.dimensions != profile["dimensions"] or len(batch.vectors) != 1:
                raise SearchCorpusError("embedding_unavailable", "Query embedding profile does not match the snapshot.")
            options = {"limit": args.limit, "min_similarity": args.min_similarity, "language": args.language,
                       "feed_ids": args.feed_ids, "document_ids": args.document_ids}
            hits, mode = (), "semantic"
            if args.literal_phrase is not None:
                hits = self.store.search(batch.vectors[0], **options, literal_phrase=args.literal_phrase)
                observation["literal_candidate_count"] = len(hits)
                observation["literal_corpus_count"] = self.store.count_literal(
                    args.literal_phrase, language=args.language, feed_ids=args.feed_ids, document_ids=args.document_ids)
                mode = "literal" if hits else "semantic_fallback"
            if not hits:
                hits = self.store.search(batch.vectors[0], **options)
            observation.update(search_mode=mode, status="ok", ranked_candidates=[
                {"rank": rank, "chunk_id": str(hit.chunk_id), "document_id": str(hit.document_id),
                 "source_key": hit.source_key, "similarity": hit.similarity,
                 "text_sha256": hashlib.sha256(hit.text.encode()).hexdigest()}
                for rank, hit in enumerate(hits, 1)])
            return SearchCorpusResult(status="ok", model=batch.model, dimensions=batch.dimensions,
                                      processing_version=profile["processing_version"], input_tokens=batch.input_tokens,
                                      hits=tuple(hits), search_mode=mode,
                                      literal_candidate_count=observation["literal_candidate_count"],
                                      literal_corpus_count=observation["literal_corpus_count"])
        except EmbeddingError:
            observation["error_code"] = "embedding_unavailable"
            raise SearchCorpusError("embedding_unavailable", "The query embedding provider is unavailable.") from None
        except CorpusStorageError:
            observation["error_code"] = "storage_unavailable"
            raise SearchCorpusError("storage_unavailable", "The pinned snapshot could not be searched.") from None
        except SearchCorpusError as exc:
            observation["error_code"] = exc.code
            raise
        finally:
            observation["elapsed_ms"] = (time.perf_counter() - started) * 1000
