"""Episode audio and time markers (storage/episode_audio.py, jobs/podcast_audio.py): parsing, anchors,
interpolation, clip estimates, the backfill flow, and one real-DB lookup in a disposable database."""

from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg import sql

from translation_agent_demo.corpus.models import CorpusChunk, Cue, CueSpan, ParsedTranscript
from translation_agent_demo.jobs import podcast_audio
from translation_agent_demo.providers.podcast_index import PodcastIndexError
from translation_agent_demo.providers.podcast_transcripts import PodcastTranscript
from translation_agent_demo.storage.chunks import save_chunks
from translation_agent_demo.storage.corpus import save_transcript
from translation_agent_demo.storage.episode_audio import (
    DEFAULT_MS_PER_CHAR, LEAD_IN_MS, MAX_MS_PER_CHAR, MIN_MS_PER_CHAR, NO_AUDIO, SOURCE_INLINE_MARKER,
    SOURCE_SEGMENT_END, SOURCE_SEGMENT_START, Anchor, AudioClip, EpisodeAudio, TimeEstimate, audio_clips_for_chunks,
    audio_coverage, audio_from_episode, chunk_to_document_offset, document_anchors, episodes_missing_audio,
    estimate_clip, extract_inline_markers, interpolate, monotonic, save_episode_audio,
)
from translation_agent_demo.storage.postgres import PostgresSettings, initialize_schema
from translation_agent_demo.storage.source_reviews import ReviewedFeed, record_feed_review

URL = "https://cdn.example.org/ep.mp3"
JOB = "translation_agent_demo.jobs.podcast_audio"


def ms(h=0, m=0, s=0, frac=0):
    return ((h * 60 + m) * 60 + s) * 1000 + frac


class MarkerTests(unittest.TestCase):
    def test_unescaped_and_escaped_markers_point_at_the_paragraph(self):
        text = "Intro. [00:12:06.15] Yeah. So it's \\[00:13:00.25\\]   Next."
        anchors = extract_inline_markers(text)
        self.assertEqual([time for _, time in anchors], [ms(0, 12, 6, 150), ms(0, 13, 0, 250)])
        self.assertEqual([text[offset:offset + 4] for offset, _ in anchors], ["Yeah", "Next"])
        self.assertEqual(extract_inline_markers("done [00:10] "), [(13, 10_000)])  # at the end: past the text

    def test_well_formed_and_malformed_markers(self):
        for marker, expected in (("[00:00:01.5]", 1500), ("[00:00:01.15]", 1150), ("[00:00:01.153]", 1153),
                                 ("[00:00:01]", 1000)):
            with self.subTest(marker=marker):
                self.assertEqual(extract_inline_markers(marker + " x"), [(len(marker) + 1, expected)])
        cases = {"[02:03:04.5]": ms(2, 3, 4, 500), "[11:59:59.99]": ms(11, 59, 59, 990),
                 "[1:04:02]": ms(1, 4, 2), "[08:24]": ms(0, 8, 24), "\\[59:59\\]": ms(0, 59, 59), "[7:05]": ms(0, 7, 5)}
        for marker, expected in cases.items():
            with self.subTest(marker=marker):
                self.assertEqual([time for _, time in extract_inline_markers(f"a {marker} b")], [expected])
        for text in ("[00:61:00]", "[00:00:60]", "[00:00:00:00]", "[1.5]", "[12:3]", "[00:00:01.1234]",
                     "[laughs]", "12:30", "[123:00:00]"):
            with self.subTest(text=text):
                self.assertEqual(extract_inline_markers(text), [])

    def test_monotonic_drops_only_a_typo_and_keeps_equal_times_and_extra_fields(self):
        anchors = [(10, 1000), (20, 3_540_000), (30, 3000), (40, 4000), (50, 5000)]
        self.assertEqual(monotonic(anchors), [(10, 1000), (30, 3000), (40, 4000), (50, 5000)])
        self.assertEqual(monotonic([(20, 5, "b"), (10, 5, "a")]), [(10, 5, "a"), (20, 5, "b")])
        self.assertEqual(monotonic([]), [])

    def test_offsets_count_over_cue_texts_without_separators(self):
        cues = [("Hello there.", "A"), ("[00:30] Second turn.", "B"), ("More [01:00] text.", None)]
        anchors = document_anchors(cues)
        joined = "".join(text for text, _ in cues)
        self.assertEqual([(a.time_ms, a.source) for a in anchors],
                         [(30_000, SOURCE_INLINE_MARKER), (60_000, SOURCE_INLINE_MARKER)])
        self.assertEqual([joined[a.char_offset:a.char_offset + 4] for a in anchors], ["Seco", "text"])
        self.assertEqual(document_anchors([("Just speech.", "A")]), [])

    def test_labelled_marker_only_cue_starts_an_untranscribed_segment(self):
        before, after = "x" * 1000 + ".", "y" * 2000
        cues = [("[00:00] " + before, "A"), ("[01:10]", "Break"), (after, "B"), ("[05:00] z", "B")]
        anchors = document_anchors(cues)
        start = next(a for a in anchors if a.source == SOURCE_SEGMENT_START)
        end = next(a for a in anchors if a.source == SOURCE_SEGMENT_END)
        prefix = len(cues[0][0])
        self.assertEqual(start, Anchor(prefix, 70_000, SOURCE_SEGMENT_START))  # end of the preceding speech
        self.assertEqual(end.char_offset, prefix + len("[01:10]"))  # start of the following speech
        # Estimated back from the next marker at the document's speech rate (clamped into range).
        rate = min(max(70_000 / len(before), MIN_MS_PER_CHAR), MAX_MS_PER_CHAR)
        self.assertEqual(end.time_ms, round(300_000 - (len(after) + len("[05:00] ")) * rate))
        self.assertGreater(end.time_ms, start.time_ms)
        self.assertEqual([a.char_offset for a in anchors], sorted(a.char_offset for a in anchors))

    def test_segment_end_is_never_before_its_start_and_needs_a_next_anchor(self):
        cues = [("[00:00] " + "a" * 600, "A"), ("[10:00]", "Break"), ("b" * 600, "B"), ("[10:05] c", "B"),
                ("d" * 100, "B"), ("[20:00]", "Outro"), ("bonus banter", "A")]
        anchors = document_anchors(cues)
        self.assertEqual([a.time_ms for a in anchors if a.source == SOURCE_SEGMENT_END], [600_000])  # clamped up
        self.assertEqual(anchors[-1].source, SOURCE_SEGMENT_START)  # trailing Outro: no later anchor, no estimate

    def test_unlabelled_marker_only_cue_and_break_ranges_are_plain_markers(self):
        cues = [("[03:00]", None), ("*A played clip.*", None), ("[44:44] to [46:37]", "Break"), ("Back.", "A")]
        anchors = document_anchors(cues)
        self.assertEqual([(a.time_ms, a.source) for a in anchors],
                         [(180_000, SOURCE_INLINE_MARKER), (ms(0, 44, 44), SOURCE_INLINE_MARKER),
                          (ms(0, 46, 37), SOURCE_INLINE_MARKER)])
        self.assertEqual(anchors[0].char_offset, len("[03:00]"))


class InterpolateTests(unittest.TestCase):
    def test_interpolation_between_outside_and_without_anchors(self):
        three, segment = [(1000, 60_000), (2000, 120_000), (3000, 150_000)], [
            Anchor(0, 0), Anchor(100, 6000, SOURCE_SEGMENT_START), Anchor(107, 80_000, SOURCE_SEGMENT_END)]
        cases = [  # (anchors, offset, doc_length, duration_ms), TimeEstimate or just its time_ms
            ((three, 1500, 4000, 300_000), TimeEstimate(90_000, "anchored", 60_000)),  # linear, with the gap
            ((three, 2500, 4000, 300_000), TimeEstimate(135_000, "anchored", 30_000)),
            ((three, 2000, 4000, None), TimeEstimate(120_000, "anchored", 0)),  # exactly on an anchor
            # Outside: the nearest two anchors' rate, clamped (30 ms/char -> 45).
            ((three, 3500, 4000, None), TimeEstimate(150_000 + 500 * 45, "extrapolated", 500 * 45)),
            ((three, 500, 4000, None), TimeEstimate(60_000 - 500 * 60, "extrapolated", 500 * 60)),
            # The last two anchors straddle a break (60 s over 10 characters): not a speech rate.
            (([(0, 0), (2000, 126_000), (2010, 136_000)], 3010, None, None), 136_000 + round(1000 * 136_000 / 2010)),
            (([(0, 0), (1000, 900_000)], 1100, None, None), 900_000 + 100 * MAX_MS_PER_CHAR),
            (([(1000, 50_000)], 2000, 10_000, 700_000), 50_000 + 1000 * 70),  # one anchor: the global rate
            (([(1000, 50_000)], 2000, None, None), 50_000 + 1000 * DEFAULT_MS_PER_CHAR),  # ...or the default
            (([], 2500, 10_000, 600_000), TimeEstimate(150_000, "proportional", 600_000)),
            (([], 2500, None, 600_000), TimeEstimate(None, "none", None)),
            (([], 2500, 10_000, None), TimeEstimate(None, "none", None)),
            ((three, 9000, None, 160_000), 160_000),  # results stay inside the episode
            (([(5000, 10_000), (6000, 70_000)], 0, None, None), 0),
            ((three, 9000, 3200, None), 150_000 + 200 * 45),
            ((segment, 107, None, None), 80_000),  # stored anchor tuples
        ]
        for (anchors, offset, length, duration), expected in cases:
            with self.subTest(anchors=anchors, offset=offset):
                estimate = interpolate(anchors, offset, doc_length=length, duration_ms=duration)
                self.assertEqual(estimate if isinstance(expected, TimeEstimate) else estimate.time_ms, expected)

    def test_chunk_offsets_map_back_to_the_same_characters(self):
        cues = ["[00:00] Hello world. Second sentence.", "Next cue here.", "Third cue."]
        starts = [0, len(cues[0]), len(cues[0]) + len(cues[1])]
        spans = [{"cue_index": 0, "start_char": 21, "end_char": 37}, {"cue_index": 1, "start_char": 0, "end_char": 14},
                 (2, 0, 5)]
        chunk_text = " ".join(cues[c][s:e] for c, s, e in [(x["cue_index"], x["start_char"], x["end_char"])
                                                          if isinstance(x, dict) else x for x in spans])
        document, joins = "".join(cues), {16, 31}  # the spaces chunking puts between slices
        self.assertEqual({i for i in joins if chunk_text[i] == " "}, joins)
        for i, char in enumerate(chunk_text):
            if i not in joins:
                with self.subTest(i=i):
                    self.assertEqual(document[chunk_to_document_offset(spans, starts, i)], char)
        self.assertEqual(chunk_to_document_offset(spans, starts, 17), starts[1])
        self.assertEqual(chunk_to_document_offset(spans, starts, 16), 37)  # exclusive end of slice 1
        self.assertEqual(chunk_to_document_offset(spans, starts, 10_000), starts[2] + 5)
        with self.assertRaises(ValueError):
            chunk_to_document_offset([], [0], 0)


class EpisodeAudioTests(unittest.TestCase):
    def test_episode_parsing_keeps_only_http_enclosures(self):
        audio = audio_from_episode({"id": 7, "feedId": 3, "enclosureUrl": URL, "duration": 1800})
        self.assertEqual(audio, EpisodeAudio(7, 3, URL, 1800))
        self.assertEqual(audio_from_episode({"id": 7, "enclosureUrl": URL, "duration": 0}).duration_s, None)
        for bad in ({"id": 7, "enclosureUrl": "javascript:alert(1)"}, {"id": 7, "enclosureUrl": ""},
                    {"id": 0, "enclosureUrl": URL}, {"id": 7}, None):
            with self.subTest(bad=bad):
                self.assertIsNone(audio_from_episode(bad))

    def test_stored_timing_is_exact_and_untimed_chunks_are_estimated_early(self):
        def estimate(start_ms, end_ms, char_start, char_end, char_total, duration_s):
            return estimate_clip(URL, start_ms=start_ms, end_ms=end_ms, char_start=char_start, char_end=char_end,
                                 char_total=char_total, duration_s=duration_s)
        self.assertEqual(estimate(5000, 9000, 0, 10, 100, 100), AudioClip(URL, 5000, 9000, False))
        guess = estimate(None, None, 500, 600, 1000, 600)
        self.assertEqual((guess.audio_estimated, guess.audio_start_ms), (True, 300_000 - LEAD_IN_MS))
        self.assertGreater(guess.audio_end_ms, 360_000)
        self.assertEqual(estimate(None, None, 0, 10, 1000, 600).audio_start_ms, 0)
        self.assertEqual(estimate(None, None, 0, 1, 1, None), AudioClip(URL))
        self.assertEqual(NO_AUDIO.as_fields(), {"audio_url": None, "audio_start_ms": None,
                                                "audio_end_ms": None, "audio_estimated": False})

    def test_feed_page_then_single_lookups_and_failures_are_skipped(self):
        client = Mock()
        client.historical_episodes_by_feed_id.return_value = {"items": [
            {"id": 10, "feedId": 1, "enclosureUrl": URL, "duration": 60},
            {"id": 11, "feedId": 1, "enclosureUrl": URL, "duration": 60}]}
        client.episode_by_id.side_effect = [{"episode": {"id": 12, "feedId": 1, "enclosureUrl": URL}},
                                            PodcastIndexError("x", status_code=500),
                                            {"episode": {"id": 21, "feedId": 2, "enclosureUrl": URL}}]
        sleeps = []
        with patch(f"{JOB}.episodes_missing_audio", return_value=[(1, 10), (1, 11), (1, 12), (2, 20), (2, 21)]), \
             patch(f"{JOB}.save_episode_audio", side_effect=lambda conn, rows: len(rows)) as save, \
             patch(f"{JOB}.audio_coverage", return_value=(4, 5)):
            result = podcast_audio.backfill_audio(Mock(), client, interval=0.25, sleep=sleeps.append)
        client.historical_episodes_by_feed_id.assert_called_once_with(1)
        self.assertEqual([call.args[0] for call in client.episode_by_id.call_args_list], [12, 20, 21])
        self.assertEqual((result.status, result.saved, result.failed, save.call_count), ("ok", 4, 1, 3))
        self.assertEqual(sleeps, [0.25, 0.25, 0.25])

    def test_auth_failure_stops_the_run(self):
        client = Mock()
        client.episode_by_id.side_effect = PodcastIndexError("x", status_code=401)
        with patch(f"{JOB}.episodes_missing_audio", return_value=[(1, 10), (2, 20)]), \
             patch(f"{JOB}.audio_coverage", return_value=(0, 2)):
            result = podcast_audio.backfill_audio(Mock(), client, sleep=lambda _: None)
        self.assertEqual((result.status, client.episode_by_id.call_count), ("auth_failed", 1))

    def test_one_cli_runs_either_job(self):
        names = ("connect_database", "PostgresSettings", "PodcastIndexClient", "PodcastIndexCredentials",
                 "extract_time_anchors", "backfill_audio")
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch(f"{JOB}.{name}")) for name in names}
            stack.enter_context(patch("builtins.print"))
            mocks["extract_time_anchors"].return_value = podcast_audio.AnchorRunResult()
            mocks["backfill_audio"].return_value = podcast_audio.AudioBackfillResult(status="auth_failed")
            self.assertEqual(podcast_audio.main(["anchors", "--dry-run", "--processing-version", "v9"]), 0)
            self.assertEqual(podcast_audio.main(["backfill", "--feed-ids", "1,2", "--interval", "0"]), 1)
        conn = mocks["connect_database"].return_value.__enter__.return_value
        mocks["extract_time_anchors"].assert_called_once_with(conn, processing_version="v9", dry_run=True)
        self.assertEqual(mocks["backfill_audio"].call_args.kwargs["feed_ids"], (1, 2))


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
        feed, prefix = 900000002, "https://example.org/transcripts/"
        record_feed_review(self.conn, ReviewedFeed(
            feed_id=feed, status="approved", license_id="self-authored", review_url="https://example.org/terms",
            review_note="Self-authored audio fixture.", license_evidence={},
            reviewed_at=datetime.now(timezone.utc), transcript_url_prefix=prefix))
        cues = (Cue(0, "a" * 50), Cue(1, "b" * 50, 40_000, 50_000))
        saved = save_transcript(self.conn, PodcastTranscript(
            feed_id=feed, episode_id=77, episode_title="Fixture", episode_url=None, transcript_url=prefix + "77.html",
            declared_type="text/html", content_type="text/html", text="<p>a</p><p>b</p>"), language="en")
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
        self.assertEqual(audio_clips_for_chunks(self.conn, ids),
                         {ids[0]: AudioClip(URL, 0, 55_000, True), ids[1]: AudioClip(URL, 40_000, 50_000, False)})
