"""The snapshot search tool: literal phrase first, meaning fallback, one observation per call."""

import unittest
from types import SimpleNamespace

from evaluation.snapshot_search import SnapshotSearch
from translation_agent_demo.agents.contracts import SearchCorpusArgs
from translation_agent_demo.tests.fakes import make_hit


class Embeddings:
    def embed_texts(self, texts):
        return SimpleNamespace(vectors=[[0.0, 1.0]], input_tokens=3, model="m", dimensions=2)


class Store:
    profile = {"model": "m", "dimensions": 2, "processing_version": "p"}

    def __init__(self, literal_hits, corpus_count=0):
        self.literal_hits, self.corpus_count, self.calls, self.counted = literal_hits, corpus_count, [], []

    def search(self, vector, *, literal_phrase=None, **options):
        self.calls.append(literal_phrase)
        return self.literal_hits if literal_phrase else (make_hit(9, "fallback"),)

    def count_literal(self, literal_phrase, **filters):
        self.counted.append((literal_phrase, filters))
        return self.corpus_count


class SnapshotSearchTests(unittest.TestCase):
    def test_literal_matches_first_then_fallback(self):
        found = SnapshotSearch(Store((make_hit(1),)), Embeddings())
        result = found(SearchCorpusArgs(query="q", literal_phrase="make one thing clear", limit=3))
        self.assertEqual((result.search_mode, result.literal_candidate_count, len(result.hits)), ("literal", 1, 1))
        missing = SnapshotSearch(Store(()), Embeddings())
        result = missing(SearchCorpusArgs(query="q", literal_phrase="absent", limit=3))
        self.assertEqual((result.search_mode, result.hits[0].text), ("semantic_fallback", "fallback"))
        self.assertEqual(missing.observations[0]["search_mode"], "semantic_fallback")
        self.assertEqual(missing.observations[0]["input_tokens"], 3)

    def test_literal_corpus_count_is_reported_beyond_the_returned_hits(self):
        store = Store((make_hit(1),), corpus_count=7)
        search = SnapshotSearch(store, Embeddings())
        result = search(SearchCorpusArgs(query="q", literal_phrase="make one thing clear", limit=3, feed_ids=[4]))
        self.assertEqual((result.literal_candidate_count, result.literal_corpus_count), (1, 7))
        self.assertEqual(search.observations[0]["literal_corpus_count"], 7)
        self.assertEqual(store.counted, [("make one thing clear", {"language": None, "feed_ids": [4], "document_ids": None})])
        absent = SnapshotSearch(Store(()), Embeddings())(SearchCorpusArgs(query="q", literal_phrase="absent"))
        self.assertEqual(absent.literal_corpus_count, 0)

    def test_no_literal_phrase_means_no_count(self):
        store = Store(())
        search = SnapshotSearch(store, Embeddings())
        result = search(SearchCorpusArgs(query="q"))
        self.assertIsNone(result.literal_corpus_count)
        self.assertIsNone(search.observations[0]["literal_corpus_count"])
        self.assertEqual(store.counted, [])


if __name__ == "__main__":
    unittest.main()
