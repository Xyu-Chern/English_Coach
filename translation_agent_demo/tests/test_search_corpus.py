"""Tool contract checks without PostgreSQL or external provider requests."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from psycopg.pq import TransactionStatus
from pydantic import ValidationError

from translation_agent_demo.providers.embedding_protocol import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EmbeddingBatch, EmbeddingError,
)
from translation_agent_demo.storage.postgres import CorpusStorageError
import translation_agent_demo.tools.search_corpus as tool


class FixedEmbeddings:
    """Implement our small provider boundary, without imitating an upstream API response."""

    model = EMBEDDING_MODEL
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        if self.error is not None:
            raise self.error
        vector = (1.0,) + (0.0,) * (self.dimensions - 1)
        return EmbeddingBatch(self.model, self.dimensions, tuple(vector for _ in texts), len(texts))


class SearchCorpusTests(unittest.TestCase):
    def setUp(self):
        # Repository functions are patched; the Tool only reads idle connection metadata.
        self.conn = SimpleNamespace(autocommit=True, info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        self.embeddings = FixedEmbeddings()
        self.args = tool.SearchCorpusArgs(query="I did not mean that.")

    def test_tool_rejects_invalid_input_and_permission_overrides(self):
        cases = ({"query": " "}, {"query": "hello", "limit": 11},
                 {"query": "hello", "feed_ids": [1, 1]},
                 {"query": "hello", "rights_status": "approved"})
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                tool.SearchCorpusArgs.model_validate(data)

    def test_unready_corpus_does_not_spend_an_embedding_request(self):
        with patch.object(tool, "has_searchable_corpus", return_value=False), \
                patch.object(tool, "search_chunks") as search:
            result = tool.search_corpus(self.args, conn=self.conn, embeddings=self.embeddings)
        self.assertEqual((result.status, result.hits, result.input_tokens), ("not_ready", (), 0))
        self.assertEqual(self.embeddings.calls, 0)
        search.assert_not_called()

    def test_empty_search_is_a_successful_result(self):
        with patch.object(tool, "has_searchable_corpus", return_value=True), \
                patch.object(tool, "search_chunks", return_value=()):
            result = tool.search_corpus(self.args, conn=self.conn, embeddings=self.embeddings)
        self.assertEqual((result.status, result.hits), ("ok", ()))
        self.assertEqual(self.embeddings.calls, 1)

    def test_embedding_failures_are_not_reported_as_empty_results(self):
        cases = ((EmbeddingError("Provider unavailable"), "embedding_unavailable"),
                 (ValueError("Input token limit exceeded"), "invalid_query"))
        for error, code in cases:
            embeddings = FixedEmbeddings(error)
            with self.subTest(code=code), \
                    patch.object(tool, "has_searchable_corpus", return_value=True), \
                    patch.object(tool, "search_chunks") as search:
                with self.assertRaises(tool.SearchCorpusError) as raised:
                    tool.search_corpus(self.args, conn=self.conn, embeddings=embeddings)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(embeddings.calls, 1)
                search.assert_not_called()

    def test_storage_failures_are_not_reported_as_empty_results(self):
        for stage in ("has_searchable_corpus", "search_chunks"):
            embeddings = FixedEmbeddings()
            with self.subTest(stage=stage), \
                    patch.object(tool, "has_searchable_corpus", return_value=True), \
                    patch.object(tool, "search_chunks", return_value=()), \
                    patch.object(tool, stage, side_effect=CorpusStorageError("Storage unavailable")):
                with self.assertRaises(tool.SearchCorpusError) as raised:
                    tool.search_corpus(self.args, conn=self.conn, embeddings=embeddings)
                self.assertEqual(raised.exception.code, "storage_unavailable")
                self.assertEqual(embeddings.calls, int(stage == "search_chunks"))
