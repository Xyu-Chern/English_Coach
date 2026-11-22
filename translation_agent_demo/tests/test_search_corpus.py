"""Tool contract checks without PostgreSQL or external provider requests."""

from dataclasses import asdict
from types import SimpleNamespace
import json
from uuid import UUID
import unittest
from unittest.mock import patch

from psycopg.pq import TransactionStatus
from pydantic import ValidationError

from translation_agent_demo.providers.embedding_protocol import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EmbeddingBatch, EmbeddingError,
)
from translation_agent_demo.storage.episode_audio import AudioClip
from translation_agent_demo.storage.postgres import CorpusStorageError
from translation_agent_demo.storage.retrieval import RetrievedChunk
from translation_agent_demo.corpus.models import CueSpan
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
        audio = patch.object(tool, "audio_clips_for_chunks", return_value={})
        self.audio = audio.start()
        self.addCleanup(audio.stop)

    def _row(self, chunk_id=1, start_ms=None):
        return RetrievedChunk(
            chunk_id=UUID(int=chunk_id), document_id=UUID(int=2), build_id=UUID(int=3),
            source_key="podcast_index:1:1", feed_id=1, episode_id=1, episode_title="Source",
            episode_url=None, transcript_url=None, language="en", text="Thanks for inviting me.",
            similarity=.6, start_ms=start_ms, end_ms=None if start_ms is None else start_ms + 2000, speakers=(),
            spans=(CueSpan(cue_index=0, start_char=0, end_char=23),), rights_status="approved",
            rights_review_url=None, license_id="CC-BY-SA-4.0", license_url=None, attribution="Publisher",
        )

    def test_hits_carry_publisher_audio_clips_and_default_to_no_audio(self):
        url = "https://cdn.example.org/ep.mp3"
        self.audio.return_value = {UUID(int=1): AudioClip(url, 4000, 6000, False),
                                   UUID(int=2): AudioClip(url, 85_000, 120_000, True)}
        rows = (self._row(1, start_ms=4000), self._row(2), self._row(3))
        with patch.object(tool, "has_searchable_corpus", return_value=True), \
                patch.object(tool, "search_chunks", return_value=rows):
            result = tool.search_corpus(self.args, conn=self.conn, embeddings=self.embeddings)
        self.audio.assert_called_once_with(self.conn, [UUID(int=1), UUID(int=2), UUID(int=3)])
        self.assertEqual([(h.audio_url, h.audio_start_ms, h.audio_end_ms, h.audio_estimated) for h in result.hits],
                         [(url, 4000, 6000, False), (url, 85_000, 120_000, True), (None, None, None, False)])

    def test_missing_audio_table_never_fails_a_search(self):
        for error in (CorpusStorageError("no table"), ValueError("bad ids")):
            self.audio.side_effect = error
            with self.subTest(error=type(error).__name__), patch.object(tool, "has_searchable_corpus", return_value=True), \
                    patch.object(tool, "search_chunks", return_value=(self._row(),)):
                result = tool.search_corpus(self.args, conn=self.conn, embeddings=self.embeddings)
            self.assertEqual((result.status, result.hits[0].audio_url, result.hits[0].audio_estimated),
                             ("ok", None, False))

    def test_audio_fields_need_a_url_and_an_ordered_clip(self):
        hit = tool.CorpusSearchHit.model_validate(asdict(self._row()))
        self.assertEqual((hit.audio_url, hit.audio_start_ms, hit.audio_end_ms, hit.audio_estimated),
                         (None, None, None, False))
        for audio in ({"audio_start_ms": 5}, {"audio_estimated": True},
                      {"audio_url": "https://a.test/x.mp3", "audio_start_ms": 9, "audio_end_ms": 3}):
            with self.subTest(audio=audio), self.assertRaises(ValidationError):
                tool.CorpusSearchHit.model_validate({**asdict(self._row()), **audio})

    def test_tool_rejects_invalid_input_and_permission_overrides(self):
        cases = ({"query": " "}, {"query": "hello", "limit": 11},
                 {"query": "hello", "feed_ids": [1, 1]},
                 {"query": "hello", "rights_status": "approved"},
                 {"query": "hello", "literal_phrase": " "},
                 {"query": "hello", "literal_phrase": "x" * 401},
                 {"query": "hello", "literal_phrase": "bad\x00phrase"})
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

    def test_document_scope_boundary_is_unique_bounded_uuid_data(self):
        value = str(UUID(int=2))
        parsed = tool.SearchCorpusArgs.model_validate_json(json.dumps({"query": "thanks", "document_ids": [value]}))
        self.assertEqual(parsed.document_ids, [UUID(int=2)])
        for ids in ([value, value], ["not-a-uuid"], [str(UUID(int=i)) for i in range(1001)]):
            with self.subTest(count=len(ids)), self.assertRaises(ValidationError):
                tool.SearchCorpusArgs.model_validate_json(json.dumps({"query": "thanks", "document_ids": ids}))

    def test_empty_document_scope_never_widens_or_spends_embedding_tokens(self):
        for literal in (None, "Thanks for inviting me."):
            args = tool.SearchCorpusArgs(query="thanks", literal_phrase=literal, document_ids=[])
            with self.subTest(literal=literal), patch.object(tool, "has_searchable_corpus") as ready, \
                    patch.object(tool, "search_chunks") as search:
                result = tool.search_corpus(args, conn=self.conn, embeddings=self.embeddings)
            self.assertEqual((result.status, result.hits, result.input_tokens), ("ok", (), 0))
            ready.assert_not_called()
            search.assert_not_called()
        self.assertEqual(self.embeddings.calls, 0)

    def test_empty_search_is_a_successful_result(self):
        with patch.object(tool, "has_searchable_corpus", return_value=True), \
                patch.object(tool, "search_chunks", return_value=()):
            result = tool.search_corpus(self.args, conn=self.conn, embeddings=self.embeddings)
        self.assertEqual((result.status, result.hits), ("ok", ()))
        self.assertEqual(self.embeddings.calls, 1)
        self.assertEqual(result.search_mode, "semantic")
        self.assertIsNone(result.literal_corpus_count)

    def test_literal_preference_and_fallback_share_one_embedding(self):
        row = RetrievedChunk(
            chunk_id=UUID(int=1), document_id=UUID(int=2), build_id=UUID(int=3),
            source_key="fixture:one", feed_id=1, episode_id=1, episode_title="Source",
            episode_url=None, transcript_url=None, language="en", text="Thanks for inviting me.",
            similarity=.6, start_ms=None, end_ms=None, speakers=(),
            spans=(CueSpan(cue_index=0, start_char=0, end_char=23),), rights_status="approved",
            rights_review_url=None, license_id="CC-BY-SA-4.0", license_url=None, attribution="Publisher",
        )
        args = tool.SearchCorpusArgs(query="thank the host", literal_phrase="Thanks for inviting me.",
                                     feed_ids=[1], language="en", min_similarity=.4, limit=3, document_ids=[UUID(int=2)])
        for responses, mode, literal_count, corpus_count in [([(row,)], "literal", 1, 12),
                                                             ([(), (row,)], "semantic_fallback", 0, 0)]:
            embeddings = FixedEmbeddings()
            with self.subTest(mode=mode), patch.object(tool, "has_searchable_corpus", return_value=True), \
                    patch.object(tool, "count_literal_chunks", return_value=corpus_count) as count, \
                    patch.object(tool, "search_chunks", side_effect=responses) as search:
                result = tool.search_corpus(args, conn=self.conn, embeddings=embeddings)
            self.assertEqual((result.search_mode, result.literal_candidate_count, result.literal_corpus_count),
                             (mode, literal_count, corpus_count))
            self.assertEqual(count.call_args.args[1], args.literal_phrase)
            self.assertEqual((count.call_args.kwargs["feed_ids"], count.call_args.kwargs["document_ids"]),
                             ((1,), (UUID(int=2),)))
            self.assertEqual(result.hits[0].similarity, .6)
            self.assertEqual(embeddings.calls, 1)
            self.assertEqual(search.call_count, len(responses))
            first = search.call_args_list[0]
            self.assertEqual(first.kwargs["literal_phrase"], args.literal_phrase)
            self.assertEqual(first.kwargs["document_ids"], (UUID(int=2),))
            if len(responses) == 2:
                second = search.call_args_list[1]
                self.assertIs(first.args[1], second.args[1])
                self.assertEqual({k: v for k, v in first.kwargs.items() if k != "literal_phrase"}, second.kwargs)

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


class LiteralWordPatternTests(unittest.TestCase):
    """The PostgreSQL pattern is checked with Python's re, whose syntax matches for these escapes."""

    @staticmethod
    def _python(pattern: str) -> str:
        return pattern.replace(r"\m", r"\b").replace(r"\M", r"\b")

    def test_whole_words_only_and_metacharacters_are_literal(self):
        import re
        from translation_agent_demo.storage.retrieval import literal_word_pattern
        cases = [("treat", "Treat it well", True), ("treat", "a treatment", False), ("treat", "retreat", False),
                 ("Thanks for inviting me.", "thanks for inviting me. Sure", True),
                 ("Thanks for inviting me.", "thanks for inviting meX", False),
                 ("a (b)*c", "say a (b)*c now", True), ("a (b)*c", "a bbc", False),
                 ("I'm in", "Okay, I'm in!", True), ("1.5", "105", False)]
        for phrase, text, expected in cases:
            with self.subTest(phrase=phrase, text=text):
                found = re.search(self._python(literal_word_pattern(phrase)), text, re.IGNORECASE) is not None
                self.assertEqual(found, expected)
        with self.assertRaises(ValueError):
            literal_word_pattern("")
