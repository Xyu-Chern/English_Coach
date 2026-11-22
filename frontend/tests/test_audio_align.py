"""Audio alignment (frontend/audio_align.py) with made-up recognition results: matching, widening, lines,
the quote's place, the background queue and GET /api/audio/alignment. No audio, model or database."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from frontend import audio_align as al
from frontend.server import NDJSON, make_app
from frontend.staged import CoachMode, First
from translation_agent_demo.agents.evidence import make_citation
from translation_agent_demo.agents.results import ExpressionItem
from translation_agent_demo.tests.fakes import make_hit
from translation_agent_demo.tests.test_pipelines import QUESTION

URL = "https://cdn.example.org/episode.mp3"
SENTENCES = ["Thanks for having me on the show today.", "I am honored to be your very first guest this year.",
             "We talked about shipping small changes every single week.", "That habit really changed how our team works.",
             "Honestly it felt like we lucked out with the timing.", "Customers noticed the difference within a month.",
             "So we kept going and never looked back after that.", "Anyway that is the story of how it started."]
TEXT = " ".join(SENTENCES)
WORDS = [w for w, _, _ in al.words_of(TEXT)]
NOISE = "and so um yeah right okay well you know like basically".split()
STEP = 300  # ms per recognised word


def timeline(chunk_start_ms, *, ad_after=None, ad_words=0, garble=()):
    """Recognised words (word, start, end) of a long stretch of audio: noise, the chunk spoken from
    chunk_start_ms (a few words misheard), optionally an ad break inside it, then noise."""
    words, t = [], max(0, chunk_start_ms - 400 * STEP)
    while t < chunk_start_ms:
        words.append((NOISE[len(words) % len(NOISE)], t, t + STEP))
        t += STEP
    for i, word in enumerate(WORDS):
        if i == ad_after:
            for k in range(ad_words):
                words.append((NOISE[k % len(NOISE)], t, t + STEP))
                t += STEP
        words.append(("mumble" if i in garble else f" {word},", t, t + STEP))
        t += STEP
    for k in range(400):
        words.append((NOISE[k % len(NOISE)], t, t + STEP))
        t += STEP
    return words


class FakeAudio:
    """decode(url, low, high) and transcribe(samples) over a fixed timeline; records the windows decoded."""

    def __init__(self, words):
        self.words, self.windows = words, []

    def decode(self, url, low, high):
        self.windows.append((low, high))
        return [low, high], low

    def transcribe(self, samples):
        low, high = samples
        return [(w, s - low, e - low) for w, s, e in self.words if low <= s < high]


def source(estimate, duration_ms=3_600_000, **extra):
    return al.ChunkSource(UUID(int=7), TEXT, URL, duration_ms, estimate, clip=(estimate[0], estimate[1]), **extra)


class MatchingTests(unittest.TestCase):
    def test_the_chunk_is_found_inside_the_first_window_and_misheard_words_are_interpolated(self):
        start = 1_000_000
        audio = FakeAudio(timeline(start, garble={3, 10, 11}))
        alignment = al.align_chunk(source((start - 20_000, start + 10_000)), audio.decode, audio.transcribe, model="fake")
        self.assertEqual(len(audio.windows), 1)
        self.assertEqual((alignment.method, alignment.model, len(alignment.words)), ("asr", "fake", len(WORDS)))
        self.assertGreater(alignment.coverage, 0.9)
        self.assertEqual([w["s"] for w in alignment.words[:5]], [start + k * STEP for k in range(5)])
        self.assertEqual(alignment.words[10]["s"], start + 10 * STEP)  # misheard: between its neighbours
        self.assertEqual(alignment.cues[0], {"text": SENTENCES[0], "start_ms": start, "end_ms": start + 8 * STEP})

    def test_a_chunk_that_starts_before_the_window_widens_it_once_on_that_side(self):
        start = 2_000_000
        audio = FakeAudio(timeline(start))
        estimate = (start + 145_000, start + 175_000)  # so late that the window starts mid-chunk
        alignment = al.align_chunk(source(estimate), audio.decode, audio.transcribe)
        low, high = al.first_window(source(estimate))
        self.assertEqual(audio.windows, [(low, high), (low - al.WIDEN_MS, low)])
        self.assertEqual(alignment.words[0]["s"], start)
        self.assertEqual(alignment.window_start_ms, low - al.WIDEN_MS)

    def test_words_that_are_not_there_give_up_after_one_wider_try(self):
        audio = FakeAudio([(NOISE[k % len(NOISE)], k * STEP, (k + 1) * STEP) for k in range(20_000)])
        self.assertIsNone(al.align_chunk(source((1_000_000, 1_030_000)), audio.decode, audio.transcribe))
        low, high = al.first_window(source((1_000_000, 1_030_000)))
        self.assertEqual(audio.windows, [(low, high), (low - al.WIDEN_MS, low), (high, high + al.WIDEN_MS)])

    def test_an_ad_break_inside_the_chunk_keeps_both_halves(self):
        start = 600_000
        audio = FakeAudio(timeline(start, ad_after=40, ad_words=150))
        alignment = al.align_chunk(source((start, start + 30_000)), audio.decode, audio.transcribe)
        self.assertEqual(alignment.words[39]["s"], start + 39 * STEP)
        self.assertEqual(alignment.words[40]["s"], start + (40 + 150) * STEP)

    def test_transcript_cue_timing_needs_no_audio(self):
        half = len(SENTENCES[0]) + 1 + len(SENTENCES[1])
        first, second = TEXT[:half], TEXT[half + 1:]
        stored = al.stored_alignment(source((0, 1), spans=(
            (0, len(first), 10_000, 14_000, len(first)), (0, len(second), 20_000, 50_000, len(second)))))
        self.assertEqual((stored.method, stored.words[0]["s"]), ("stored", 10_000))
        self.assertTrue(49_000 < stored.words[-1]["e"] <= 50_000)
        self.assertEqual(stored.words[len(al.words_of(first))]["s"], 20_000)
        self.assertIsNone(al.stored_alignment(source((0, 1), spans=((0, 5, None, None, 5),))))


class AnswerTests(unittest.TestCase):
    def setUp(self):
        audio = FakeAudio(timeline(1_000_000))
        self.row = al.align_chunk(source((1_000_000, 1_030_000)), audio.decode, audio.transcribe).row()

    def test_a_ready_answer_places_the_quote_and_shows_the_lines_around_it(self):
        reply = al.answer(self.row, "it felt like we lucked out")
        start = 1_000_000 + WORDS.index("felt") * STEP - STEP  # "it" comes just before "felt"
        self.assertEqual((reply["status"], reply["method"], reply["audio_url"]), ("ready", "asr", URL))
        self.assertEqual((reply["quote_start_ms"], reply["quote_end_ms"]), (start, start + 6 * STEP))
        self.assertTrue(reply["clip_start_ms"] <= reply["quote_start_ms"] < reply["quote_end_ms"] <= reply["clip_end_ms"])
        self.assertLessEqual(reply["clip_end_ms"] - reply["clip_start_ms"], al.MAX_CLIP_MS)
        self.assertIn(SENTENCES[4], [cue["text"] for cue in reply["cues"]])
        self.assertEqual(al.answer(self.row, "Honestly, it felt like we LUCKED out!")["quote_start_ms"],
                         start - STEP)

    def test_a_nearly_matching_quote_is_still_placed_and_an_unknown_one_is_not(self):
        near = al.answer(self.row, "customers noticed a difference within the month")
        self.assertEqual(near["quote_start_ms"], 1_000_000 + WORDS.index("Customers") * STEP)
        missing = al.answer(self.row, "completely unrelated words appear here")
        self.assertIsNone(missing["quote_start_ms"])
        self.assertEqual(missing["status"], "ready")

    def test_long_sentences_are_split_into_short_lines(self):
        text = "one two three four five six seven eight nine ten, eleven twelve thirteen fourteen fifteen " \
               "sixteen seventeen eighteen nineteen twenty."
        lines = [text[a:b] for a, b in al.line_spans(text)]
        self.assertEqual(lines, ["one two three four five six seven eight nine ten,",
                                 "eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty."])


class ServiceTests(unittest.TestCase):
    def test_off_reads_only_the_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "alignments.json"
            row = {**FakeRow.ROW, "method": "stored"}
            snapshot.write_text(json.dumps({"alignments": {str(UUID(int=7)): row}}))
            service = al.AudioAlignments(snapshot=snapshot)
            self.assertFalse(service.aligning)
            self.assertEqual(service.lookup(UUID(int=7), "lucked out")["method"], "stored")
            self.assertEqual(service.lookup(UUID(int=8), "x"), al.not_ready("unavailable", None))
            service.prefetch([UUID(int=8)])
            self.assertEqual(service._threads, [])

    def test_the_setting(self):
        self.assertFalse(al.AudioAlignments.from_environment(local=False, environ={}).aligning)
        with patch.object(al, "can_align", return_value=True):
            self.assertTrue(al.AudioAlignments.from_environment(local=True, environ={}, database=object()).aligning)
            self.assertFalse(al.AudioAlignments.from_environment(
                local=True, environ={"COACH_AUDIO_ALIGN": "off"}, database=object()).aligning)
        with self.assertRaises(ValueError):
            al.AudioAlignments.from_environment(local=True, environ={"COACH_AUDIO_ALIGN": "maybe"}, database=object())

    def test_a_chunk_is_pending_until_aligned_then_ready_and_a_failure_is_unavailable(self):
        service = FakeRow()
        first = service.lookup(UUID(int=7), "lucked out")
        self.assertEqual((first["status"], first["method"], first["clip_start_ms"]), ("pending", "estimated", 1_000_000))
        service.release.set()
        self.assertEqual(wait_for(lambda: service.lookup(UUID(int=7), "lucked out")["status"]), "ready")
        self.assertEqual(service.aligned, [UUID(int=7)])
        service.fail = True
        service.lookup(UUID(int=9), "x")
        self.assertEqual(wait_for(lambda: service.lookup(UUID(int=9), "x")["status"], "unavailable"), "unavailable")
        self.assertEqual(json.loads(service.lines[-1])["status"], "failed")

    def test_time_markers_answer_at_once_with_a_widened_quote_until_recognition_replaces_them(self):
        # One cue holds the chunk (document offset 0); markers at its start and end: 60 ms per character.
        marked = source((1_000_000, 1_030_000), anchors=((0, 1_000_000), (len(TEXT), 1_000_000 + 60 * len(TEXT))),
                        doc_spans=((0, 0, len(TEXT), 0),), char_total=len(TEXT))
        service = FakeRow()
        service._source = lambda chunk_id, fresh=False: marked
        quote = "it felt like we lucked out"
        at = TEXT.index("it felt")
        rough = service.lookup(UUID(int=7), quote)
        self.assertEqual((rough["status"], rough["method"], rough["confidence"], rough["refining"]),
                         ("ready", "anchored", "anchored", True))
        self.assertEqual(rough["quote_start_ms"], 1_000_000 + 60 * at - 3_000)  # ~3 s early, not 15 s
        self.assertEqual(rough["quote_end_ms"], 1_000_000 + 60 * (at + len(quote)) + 3_000)
        self.assertTrue(rough["clip_start_ms"] <= rough["quote_start_ms"] < rough["quote_end_ms"] <= rough["clip_end_ms"])
        self.assertIn(SENTENCES[4], [cue["text"] for cue in rough["cues"]])
        service.release.set()
        self.assertEqual(wait_for(lambda: service.lookup(UUID(int=7), quote)["method"], "asr"), "asr")
        off = al.AudioAlignments(database=object())  # no recogniser: the markers' answer, not refining
        off._read, off._source = (lambda query: None), (lambda chunk_id, fresh=False: marked)
        self.assertEqual({k: off.lookup(UUID(int=7), quote)[k] for k in ("status", "method", "refining")},
                         {"status": "ready", "method": "anchored", "refining": False})
        bare = al.AudioAlignments(database=object())
        bare._read, bare._source = (lambda query: None), (lambda chunk_id, fresh=False: source((1_000_000, 1_030_000)))
        self.assertEqual(bare.lookup(UUID(int=7), quote)["method"], "estimated")  # no markers: the old estimate

    def test_prefetch_queues_behind_an_asked_for_chunk_and_skips_aligned_ones(self):
        service = FakeRow(workers=1)
        service.prefetch([UUID(int=1), UUID(int=2), UUID(int=1)])
        wait_for(lambda: service._state.get(UUID(int=1)), "running")
        service.lookup(UUID(int=3), "x")  # asked for while the first prefetch runs: it goes next
        service.release.set()
        wait_for(lambda: len(service.aligned) == 3 or None, True)
        self.assertEqual(service.aligned, [UUID(int=1), UUID(int=3), UUID(int=2)])
        service.prefetch([UUID(int=1)])
        time.sleep(0.05)
        self.assertEqual(len(service.aligned), 3)


class FakeRow(al.AudioAlignments):
    """An aligning service whose database and recogniser are replaced: each alignment waits for release."""

    ROW = {"audio_url": URL, "window_start_ms": 0, "method": "asr", "model": "fake",
           "words": [{"w": w, "s": 1_000_000 + i * STEP, "e": 1_000_000 + (i + 1) * STEP} for i, w in enumerate(WORDS)],
           "cues": [{"text": TEXT, "start_ms": 1_000_000, "end_ms": 1_000_000 + len(WORDS) * STEP}]}

    def __init__(self, workers=2):
        self.lines = []
        super().__init__(database=object(), align=True, transcriber=lambda samples: [], workers=workers,
                         log=self.lines.append)
        self.release, self.aligned, self.fail = threading.Event(), [], False

    def _read(self, query):
        return None

    def _source(self, chunk_id, *, fresh=False):
        return source((1_000_000, 1_030_000))

    def _align(self, chunk_id):
        self.release.wait(5)
        self.aligned.append(chunk_id)
        return (None, {"error": "not_found"}) if self.fail else (dict(self.ROW), {"method": "asr"})


class SnapshotExportTests(unittest.TestCase):
    def test_the_vercel_package_ships_saved_alignments_and_no_recogniser(self):
        from frontend.vercel import package

        row = {"chunk_id": str(UUID(int=7)), **FakeRow.ROW}

        def psql(sql):
            return "t\n" if "to_regclass" in sql else json.dumps(row) + "\n"
        with tempfile.TemporaryDirectory() as folder, patch.object(package, "psql", psql):
            self.assertEqual(package.export_alignments(Path(folder)), 1)
            service = al.AudioAlignments(snapshot=Path(folder) / "alignments.json")
            self.assertEqual(service.lookup(UUID(int=7), "lucked out")["status"], "ready")
        self.assertIn("faster-whisper==", package.LOCAL_ONLY_REQUIREMENTS)
        self.assertIn("frontend/audio_align.py", package.FUNCTION_FILES)
        self.assertIn("/api/audio/alignment", {r["source"] for r in package.vercel_config()["rewrites"]})


def wait_for(read, until="ready", seconds=3.0):
    deadline = time.monotonic() + seconds
    while True:
        value = read()
        if value == until or time.monotonic() > deadline:
            return value
        time.sleep(0.01)


class ApiTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"COACH_PAIR_CODE": "", "COACH_WEB_ORIGIN": "", "COACH_SYSTEM": "",
                                      "COACH_CONTINUATION": "", "COACH_ADMIN_DIR": "", "COACH_ADMIN_DATA": ""})
        env.start()
        self.addCleanup(env.stop)
        self.service = Recorder()
        text, quote = "Before that, honestly it felt like we lucked out with the timing.", "we lucked out"
        hit = make_hit(5, text).model_copy(
            update={"audio_url": URL, "audio_start_ms": 0, "audio_end_ms": 9000, "audio_estimated": True})
        item = ExpressionItem(expression="We lucked out.", function="luck", note="n",
                              citation=make_citation(hit, text.index(quote), text.index(quote) + len(quote), "s", "a"))
        plain = ExpressionItem(expression="Plain.", function="f", note="n")
        stream = lambda question, mode, guard: iter([First((item, plain), False, continuation="skipped")])
        self.app = make_app(stream=stream, mode=CoachMode(), log=lambda line: None, alignments=self.service)

    def test_the_alignment_answer_and_its_access_rules(self):
        client = TestClient(self.app, base_url="http://localhost")
        reply = client.get("/api/audio/alignment", params={"chunk_id": str(UUID(int=5)), "quote": "lucked out"})
        self.assertEqual((reply.status_code, reply.json()["status"], reply.headers["cache-control"]),
                         (200, "pending", "no-store"))
        self.assertEqual(self.service.asked, [(UUID(int=5), "lucked out")])
        self.assertEqual(client.get("/api/audio/alignment", params={"chunk_id": "nope", "quote": "x"}).status_code, 422)
        self.assertEqual(client.get("/api/audio/alignment", params={"chunk_id": str(UUID(int=5))}).status_code, 422)
        remote = TestClient(self.app, base_url="https://coach.example")
        self.assertEqual(remote.get("/api/audio/alignment",
                                    params={"chunk_id": str(UUID(int=5)), "quote": "x"}).status_code, 403)

    def test_a_stream_aligns_the_cited_examples_it_sent_and_a_json_reply_does_not(self):
        client = TestClient(self.app, base_url="http://localhost")
        client.post("/api/search", json={"question": QUESTION}, headers={"Accept": NDJSON})
        self.assertEqual(self.service.prefetched, [[UUID(int=5)]])
        client.post("/api/search", json={"question": QUESTION})
        self.assertEqual(len(self.service.prefetched), 1)


class Recorder:
    aligning = True

    def __init__(self):
        self.asked, self.prefetched = [], []

    def lookup(self, chunk_id, quote):
        self.asked.append((chunk_id, quote))
        return al.not_ready("pending", None)

    def prefetch(self, chunk_ids):
        self.prefetched.append(list(chunk_ids))


if __name__ == "__main__":
    unittest.main()
