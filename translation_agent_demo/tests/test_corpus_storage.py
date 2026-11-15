"""Real pgvector regressions using one disposable database per test run.

Requires the project's PostgreSQL server and DATABASE_URL/password settings.
Only the newly created test database is migrated or cleared; no provider is used.
"""

from dataclasses import replace
from datetime import datetime, timezone
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql

from translation_agent_demo.corpus.models import CorpusChunk, Cue, CueSpan, ParsedTranscript
from translation_agent_demo.providers.embedding_protocol import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EmbeddingBatch,
)
from translation_agent_demo.providers.podcast_transcripts import PodcastTranscript
from translation_agent_demo.storage.chunks import save_chunks
from translation_agent_demo.storage.corpus import get_transcript, save_transcript
from translation_agent_demo.storage.embeddings import (
    EmbeddingChunk, pending_embedding_chunks, save_embeddings,
)
from translation_agent_demo.storage.postgres import PostgresSettings, initialize_schema
from translation_agent_demo.storage.retrieval import has_searchable_corpus, search_chunks
from translation_agent_demo.storage.source_reviews import (
    ReviewedFeed, record_feed_review, transcript_url_is_approved,
)

PROFILE = {"model": EMBEDDING_MODEL, "dimensions": EMBEDDING_DIMENSIONS,
           "processing_version": "storage-regression-fixture-v1"}
VECTOR = (1.0,) + (0.0,) * (EMBEDDING_DIMENSIONS - 1)
FEED_ID = 900000001
REVIEWED_PREFIX = "https://example.org/transcripts/"


class CorpusStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = PostgresSettings.from_environment()
        options = {"autocommit": True, "connect_timeout": settings.connect_timeout_seconds,
                   "options": f"-c statement_timeout={settings.statement_timeout_ms}"}
        if settings.password is not None:
            options["password"] = settings.password
        # Explicit dbname overrides the application's database, including URI query parameters.
        admin = psycopg.connect(settings.database_url, dbname="postgres", **options)
        cls.addClassCleanup(admin.close)
        database_name = "english_coach_test_" + uuid4().hex
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        # Register deletion only after CREATE succeeds; never drop a pre-existing DB.
        cls.addClassCleanup(
            admin.execute, sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)),
        )
        cls.conn = psycopg.connect(settings.database_url, dbname=database_name, **options)
        cls.addClassCleanup(cls.conn.close)  # Class cleanups run in reverse order, even on setup failure.
        if cls.conn.info.dbname != database_name:
            raise RuntimeError("Refusing to initialize a database not created by this test run.")
        initialize_schema(cls.conn)

    def setUp(self):
        # Reuse the isolated schema; these three cases do not require container restarts.
        self.conn.execute("TRUNCATE public.podcast_sources, public.podcast_feed_reviews CASCADE")
        self.review = ReviewedFeed(
            feed_id=FEED_ID, status="approved", license_id="self-authored",
            review_url="https://example.org/terms",
            review_note="Self-authored test transcripts within the explicitly selected directory.",
            license_evidence={}, reviewed_at=datetime.now(timezone.utc),
            transcript_url_prefix=REVIEWED_PREFIX,
        )
        record_feed_review(self.conn, self.review)

    def _store(self, *words, episode_id=1, url=REVIEWED_PREFIX + "1.html"):
        """Seed already-parsed single-token cues; tokenizer/parsing is outside these tests."""
        transcript = PodcastTranscript(
            feed_id=FEED_ID, episode_id=episode_id, episode_title="Self-authored fixture",
            episode_url=None, transcript_url=url, declared_type="text/html", content_type="text/html",
            text="".join(f"<p>{word}</p>" for word in words),
        )
        saved = save_transcript(self.conn, transcript, language="en")
        cues = tuple(Cue(index, word) for index, word in enumerate(words))
        chunks = tuple(CorpusChunk(cue.index, cue.text, 1, (CueSpan(cue.index, 0, len(cue.text)),))
                       for cue in cues)
        build = save_chunks(self.conn, saved.document_id, PROFILE["processing_version"],
                            ParsedTranscript("html", cues), chunks)
        rows = self.conn.execute(
            "SELECT chunk_id, build_id, text, token_count FROM corpus_chunks "
            "WHERE build_id = %s ORDER BY chunk_index", (build.build_id,),
        ).fetchall()
        return saved, tuple(EmbeddingChunk(*row) for row in rows)

    def _embed(self, chunks):
        return save_embeddings(self.conn, chunks, EmbeddingBatch(
            model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS,
            vectors=tuple(VECTOR for _ in chunks), input_tokens=len(chunks),
        ))

    def _hits(self):
        return search_chunks(self.conn, VECTOR, **PROFILE)

    def test_review_scope_excludes_current_and_historical_outside_urls(self):
        # Reproduce a legacy complete index created before its review was narrowed.
        record_feed_review(self.conn, replace(self.review, transcript_url_prefix=None))
        legacy, legacy_chunks = self._store("Hello", url="https://example.org/outside/old.html")
        self._embed(legacy_chunks)
        self.assertEqual({hit.document_id for hit in self._hits()}, {legacy.document_id})

        allowed, allowed_chunks = self._store("World")
        record_feed_review(self.conn, self.review)
        self.assertEqual(get_transcript(self.conn, allowed.document_id).rights_status, "approved")
        self.assertTrue(transcript_url_is_approved(self.conn, FEED_ID, REVIEWED_PREFIX + "1.html"))
        for url in ("https://example.org/outside/1.html", REVIEWED_PREFIX + "../outside.html",
                    REVIEWED_PREFIX + "%2e%2e/outside.html", "https://example.org.evil/transcripts/1.html"):
            with self.subTest(url=url):
                self.assertFalse(transcript_url_is_approved(self.conn, FEED_ID, url))
        self.assertEqual(self._hits(), ())  # The old, complete but out-of-scope version must disappear.
        self.assertFalse(has_searchable_corpus(self.conn, **PROFILE))
        self.assertEqual(pending_embedding_chunks(self.conn, **PROFILE), allowed_chunks)
        self._embed(allowed_chunks)
        self.assertEqual({hit.document_id for hit in self._hits()}, {allowed.document_id})

        rejected, rejected_chunks = self._store("No", episode_id=2, url="https://example.org/outside/2.html")
        self.assertEqual(get_transcript(self.conn, rejected.document_id).rights_status, "unverified")
        self.assertEqual(self._embed(rejected_chunks).inserted, 0)
        self.assertEqual(pending_embedding_chunks(self.conn, **PROFILE), ())

        record_feed_review(self.conn, replace(self.review, status="revoked"))
        self.assertFalse(has_searchable_corpus(self.conn, **PROFILE))
        self.assertEqual(self._hits(), ())

    def test_partial_embedding_stays_hidden_until_all_chunks_are_saved(self):
        saved, chunks = self._store("Hello", "World")
        partial = self._embed(chunks[:1])
        self.assertEqual((partial.inserted, partial.completed_builds), (1, 0))
        self.assertFalse(has_searchable_corpus(self.conn, **PROFILE))
        self.assertEqual(self._hits(), ())
        self.assertEqual(pending_embedding_chunks(self.conn, **PROFILE), chunks[1:])

        complete = self._embed(chunks[1:])
        self.assertEqual((complete.inserted, complete.completed_builds), (1, 1))
        self.assertTrue(has_searchable_corpus(self.conn, **PROFILE))
        hits = self._hits()
        self.assertEqual({hit.chunk_id for hit in hits}, {chunk.chunk_id for chunk in chunks})
        self.assertEqual({hit.document_id for hit in hits}, {saved.document_id})
        self.assertEqual({hit.text for hit in hits}, {"Hello", "World"})
        repeated = self._embed(chunks)
        self.assertEqual((repeated.inserted, repeated.completed_builds), (0, 0))

    def test_latest_complete_revision_can_return_from_b_to_a(self):
        a, a_chunks = self._store("Hello", url=REVIEWED_PREFIX + "a.html")
        self._embed(a_chunks)
        original = get_transcript(self.conn, a.document_id)
        b, b_chunks = self._store("World", url=REVIEWED_PREFIX + "b.html")
        self.assertEqual({hit.document_id for hit in self._hits()}, {a.document_id})
        self.assertEqual(pending_embedding_chunks(self.conn, **PROFILE), b_chunks)
        self._embed(b_chunks)
        self.assertEqual({hit.document_id for hit in self._hits()}, {b.document_id})

        a_again, _ = self._store("Hello", url=REVIEWED_PREFIX + "a-again.html")
        observed_a = get_transcript(self.conn, a.document_id)
        observed_b = get_transcript(self.conn, b.document_id)
        self.assertFalse(a_again.created)
        self.assertEqual(a_again.document_id, a.document_id)
        self.assertEqual((observed_a.text, observed_a.fetched_at), (original.text, original.fetched_at))
        self.assertGreater(observed_a.last_observed_at, observed_b.last_observed_at)
        self.assertEqual({hit.document_id for hit in self._hits()}, {a.document_id})
        self.assertEqual(pending_embedding_chunks(self.conn, **PROFILE), ())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM podcast_transcripts").fetchone()[0], 2)
