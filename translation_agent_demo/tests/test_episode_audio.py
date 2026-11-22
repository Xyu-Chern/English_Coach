"""Episode audio parsing, offset estimates, backfill flow, and one real-DB lookup.

The DB case creates and drops its own disposable database (like test_corpus_storage).
"""

from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg import sql

from translation_agent_demo.corpus.models import CorpusChunk, Cue, CueSpan, ParsedTranscript
from translation_agent_demo.jobs.podcast_audio_backfill import backfill_audio
from translation_agent_demo.providers.podcast_index import PodcastIndexError
from translation_agent_demo.providers.podcast_transcripts import PodcastTranscript
from translation_agent_demo.storage.chunks import save_chunks
from translation_agent_demo.storage.corpus import save_transcript
from translation_agent_demo.storage.episode_audio import (
    LEAD_IN_MS, NO_AUDIO, AudioClip, EpisodeAudio, audio_clips_for_chunks, audio_coverage,
    audio_from_episode, episodes_missing_audio, estimate_clip, save_episode_audio,
)
from translation_agent_demo.storage.postgres import PostgresSettings, initialize_schema
from translation_agent_demo.storage.source_reviews import ReviewedFeed, record_feed_review

URL = "https://cdn.example.org/ep.mp3"
JOB = "translation_agent_demo.jobs.podcast_audio_backfill"


class ParseAndEstimateTests(unittest.TestCase):
    def test_episode_parsing_keeps_only_http_enclosures(self):
        audio = audio_from_episode({"id": 7, "feedId": 3, "enclosureUrl": URL, "duration": 1800})
        self.assertEqual(audio, EpisodeAudio(7, 3, URL, 1800))
        self.assertEqual(audio_from_episode({"id": 7, "enclosureUrl": URL, "duration": 0}).duration_s, None)
        for bad in ({"id": 7, "enclosureUrl": "javascript:alert(1)"}, {"id": 7, "enclosureUrl": ""},
                    {"id": 0, "enclosureUrl": URL}, {"id": 7}, None):
            with self.subTest(bad=bad):
                self.assertIsNone(audio_from_episode(bad))

    def test_stored_timing_is_exact_and_untimed_chunks_are_estimated_early(self):
        exact = estimate_clip(URL, start_ms=5000, end_ms=9000, char_start=0, char_end=10,
                              char_total=100, duration_s=100)
        self.assertEqual(exact, AudioClip(URL, 5000, 9000, False))
        guess = estimate_clip(URL, start_ms=None, end_ms=None, char_start=500, char_end=600,
                              char_total=1000, duration_s=600)
        self.assertTrue(guess.audio_estimated)
        self.assertEqual(guess.audio_start_ms, 300_000 - LEAD_IN_MS)
        self.assertGreater(guess.audio_end_ms, 360_000)
        start = estimate_clip(URL, start_ms=None, end_ms=None, char_start=0, char_end=10,
                              char_total=1000, duration_s=600)
        self.assertEqual(start.audio_start_ms, 0)
        self.assertEqual(estimate_clip(URL, start_ms=None, end_ms=None, char_start=0, char_end=1,
                                       char_total=1, duration_s=None), AudioClip(URL))
        self.assertEqual(NO_AUDIO.as_fields(), {"audio_url": None, "audio_start_ms": None,
                                                "audio_end_ms": None, "audio_estimated": False})


class BackfillFlowTests(unittest.TestCase):
    def test_feed_page_then_single_lookups_and_failures_are_skipped(self):
        missing = [(1, 10), (1, 11), (1, 12), (2, 20), (2, 21)]
        client = Mock()
        client.historical_episodes_by_feed_id.return_value = {"items": [
            {"id": 10, "feedId": 1, "enclosureUrl": URL, "duration": 60},
            {"id": 11, "feedId": 1, "enclosureUrl": URL, "duration": 60},
        ]}
        client.episode_by_id.side_effect = [
            {"episode": {"id": 12, "feedId": 1, "enclosureUrl": URL}},
            PodcastIndexError("x", status_code=500),
            {"episode": {"id": 21, "feedId": 2, "enclosureUrl": URL}},
        ]
        sleeps = []
        with patch(f"{JOB}.episodes_missing_audio", return_value=missing), \
             patch(f"{JOB}.save_episode_audio", side_effect=lambda conn, rows: len(rows)) as save, \
             patch(f"{JOB}.audio_coverage", return_value=(4, 5)):
            result = backfill_audio(Mock(), client, interval=0.25, sleep=sleeps.append)
        client.historical_episodes_by_feed_id.assert_called_once_with(1)
        self.assertEqual([call.args[0] for call in client.episode_by_id.call_args_list], [12, 20, 21])
        self.assertEqual((result.status, result.saved, result.failed), ("ok", 4, 1))
        self.assertEqual(sleeps, [0.25, 0.25, 0.25])
        self.assertEqual(save.call_count, 3)

    def test_auth_failure_stops_the_run(self):
        client = Mock()
        client.episode_by_id.side_effect = PodcastIndexError("x", status_code=401)
        with patch(f"{JOB}.episodes_missing_audio", return_value=[(1, 10), (2, 20)]), \
             patch(f"{JOB}.audio_coverage", return_value=(0, 2)):
            result = backfill_audio(Mock(), client, sleep=lambda _: None)
        self.assertEqual((result.status, client.episode_by_id.call_count), ("auth_failed", 1))


class EpisodeAudioStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = PostgresSettings.from_environment()
        options = {"autocommit": True, "connect_timeout": settings.connect_timeout_seconds}
        if settings.password is not None:
            options["password"] = settings.password
        admin = psycopg.connect(settings.database_url, dbname="postgres", **options)
        cls.addClassCleanup(admin.close)
        name = "english_coach_test_" + uuid4().hex
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        cls.addClassCleanup(admin.execute, sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        cls.conn = psycopg.connect(settings.database_url, dbname=name, **options)
        cls.addClassCleanup(cls.conn.close)
        initialize_schema(cls.conn)
        migration = Path(__file__).resolve().parents[1] / "storage/migrations/010_episode_audio.sql"
        cls.conn.execute(migration.read_text(encoding="utf-8"), prepare=False)  # Idempotent.

    def test_chunk_lookup_uses_timing_or_character_estimate(self):
        feed = 900000002
        prefix = "https://example.org/transcripts/"
        record_feed_review(self.conn, ReviewedFeed(
            feed_id=feed, status="approved", license_id="self-authored", review_url="https://example.org/terms",
            review_note="Self-authored audio fixture.", license_evidence={},
            reviewed_at=datetime.now(timezone.utc), transcript_url_prefix=prefix,
        ))
        cues = (Cue(0, "a" * 50), Cue(1, "b" * 50, 40_000, 50_000))
        saved = save_transcript(self.conn, PodcastTranscript(
            feed_id=feed, episode_id=77, episode_title="Fixture", episode_url=None,
            transcript_url=prefix + "77.html", declared_type="text/html", content_type="text/html",
            text="<p>a</p><p>b</p>",
        ), language="en")
        chunks = (CorpusChunk(0, cues[0].text, 1, (CueSpan(0, 0, 50),)),
                  CorpusChunk(1, cues[1].text, 1, (CueSpan(1, 0, 50),), 40_000, 50_000))
        build = save_chunks(self.conn, saved.document_id, "audio-fixture-v1", ParsedTranscript("html", cues), chunks)
        ids = [row[0] for row in self.conn.execute(
            "SELECT chunk_id FROM corpus_chunks WHERE build_id=%s ORDER BY chunk_index", (build.build_id,))]
        self.assertEqual(episodes_missing_audio(self.conn), [(feed, 77)])
        self.assertEqual(audio_clips_for_chunks(self.conn, ids), {})
        save_episode_audio(self.conn, [EpisodeAudio(77, feed, URL, 100)])
        self.assertEqual(episodes_missing_audio(self.conn), [])
        self.assertEqual(audio_coverage(self.conn), (1, 1))
        clips = audio_clips_for_chunks(self.conn, ids)
        self.assertEqual(clips[ids[0]], AudioClip(URL, 0, 55_000, True))
        self.assertEqual(clips[ids[1]], AudioClip(URL, 40_000, 50_000, False))


if __name__ == "__main__":
    unittest.main()
