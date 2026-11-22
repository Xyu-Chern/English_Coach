"""Spans shown to the model and verification of the examples it picks."""

import json
import unittest

from translation_agent_demo.agents.results import SourceCitation
from translation_agent_demo.agents.evidence import (FULL_VIEW, ExampleVerifier, SpanCatalog, SpanView, contains_phrase,
                                                    covers, cut_span, hit_summary, key_phrase_contiguous,
                                                    make_citation, matches_phrase, normalize_for_match,
                                                    normalize_phrase, phrase_at, quote_spans)
from translation_agent_demo.tests.fakes import make_hit

TEXT = "We talked about databases. Honestly, I'd push back on that a little. Let's ship it."


class CompactViewTests(unittest.TestCase):
    """The fast first stage's compact span view: fewer spans, ranked by the key phrase's words, cut around it."""

    LONG = ("so we went back and forth on the schema for most of the afternoon and in the end I said look I'd push "
            "back on that a little because the migration is risky and nobody has tested the rollback path at all")

    def test_a_long_span_is_cut_around_the_key_phrase_at_spaces(self):
        start, end = cut_span(self.LONG, 0, len(self.LONG), 120, "push back on")
        piece = self.LONG[start:end]
        self.assertLessEqual(len(piece), 120)
        self.assertIn("push back on", piece)
        self.assertTrue(start == 0 or self.LONG[start - 1] == " ")
        self.assertTrue(end == len(self.LONG) or self.LONG[end] == " ")
        self.assertEqual(cut_span(TEXT, 0, 26, 120, "push back"), (0, 26))  # short enough: whole
        start, end = cut_span(self.LONG, 0, len(self.LONG), 120, "rollback plan")  # no phrase: its longest word
        self.assertIn("rollback", self.LONG[start:end])
        self.assertEqual(phrase_at("I’d  Push back", "i'd push"), (0, 9))

    def test_the_compact_view_ranks_shows_fewer_and_quotes_what_it_shows(self):
        text = "Nothing here. The back door was open. We push on. I'd push back on that. Fine."
        catalog = SpanCatalog()
        shown = catalog.present([make_hit(1, text)], "c0", "push back on", SpanView(per_passage=3))
        self.assertEqual([s["text"] for s in shown],
                         ["I'd push back on that.", "We push on.", "The back door was open."])
        self.assertEqual(catalog.get(shown[0]["ref"]).text, shown[0]["text"])
        cut = SpanCatalog().present([make_hit(1, self.LONG)], "c0", "push back on", SpanView(per_passage=1, chars=120))
        self.assertEqual(len(cut), 1)
        self.assertLessEqual(len(cut[0]["text"]), 120)
        self.assertTrue(cut[0]["has_key_phrase"])
        self.assertFalse(FULL_VIEW.compact)
        for bad in ({"per_passage": 0}, {"per_passage": 13}, {"chars": 100}, {"chars": 801}):
            with self.subTest(view=bad), self.assertRaises(ValueError):
                SpanView(**bad)


class EvidenceTests(unittest.TestCase):
    def test_quote_spans_are_sentences(self):
        self.assertEqual([TEXT[s:e] for s, e in quote_spans(TEXT)],
                         ["We talked about databases.", "Honestly, I'd push back on that a little.", "Let's ship it."])

    def test_catalog_numbers_spans_and_puts_the_key_phrase_first(self):
        catalog = SpanCatalog()
        shown = catalog.present([make_hit(1, TEXT)], "c0", normalize_phrase("“push back on”"))
        self.assertEqual([(s["ref"], s["text"][:8]) for s in shown],
                         [("c0h1s1", "Honestly"), ("c0h1s2", "We talke"), ("c0h1s3", "Let's sh")])
        self.assertEqual(catalog.get("c0h1s1").text, "Honestly, I'd push back on that a little.")
        self.assertEqual([s["has_key_phrase"] for s in shown], [True, False, False])
        self.assertEqual(set(shown[0]), {"ref", "text", "has_key_phrase", "episode_title"})

    def test_literal_phrase_checks_use_word_boundaries_and_reject_gaps(self):
        self.assertTrue(contains_phrase("I’d  PUSH back on it", "push back"))
        self.assertFalse(contains_phrase("pushback on it", "push back"))
        self.assertFalse(contains_phrase("unpin it", "pin"))
        self.assertTrue(key_phrase_contiguous("treat it as", "Let's treat it as a draft."))
        self.assertFalse(key_phrase_contiguous("treat ... as", "Let's treat it as a draft."))
        self.assertFalse(key_phrase_contiguous("regard as", "Let's treat it as a draft."))

    def test_one_normalisation_for_hyphens_dashes_case_and_outer_punctuation(self):
        """whack-a-mole / whack a mole and trade-off / trade off match both ways."""
        self.assertEqual(normalize_for_match("  “Whack-a-Mole”!  "), "whack a mole")
        self.assertEqual(normalize_for_match("a trade—off, really"), "a trade off, really")
        self.assertTrue(key_phrase_contiguous("whack-a-mole", "Stop playing whack a mole."))
        self.assertTrue(key_phrase_contiguous("whack a mole", "Stop playing whack-a-mole."))
        self.assertTrue(key_phrase_contiguous("trade-off", "It's a real trade off."))
        self.assertTrue(key_phrase_contiguous("trade off", "It's a real trade–off."))
        self.assertFalse(key_phrase_contiguous("trade off", "It's a tradeoff."))
        self.assertTrue(matches_phrase("we keep playing whack-a-mole here", "whack a mole"))
        self.assertTrue(covers("trade-off", "the trade off is real"))
        self.assertTrue(covers("whack a mole", "it's whack-a-mole all day"))

    def test_verifier_coverage_ignores_hyphens(self):
        text = "It's whack-a-mole with these bugs."
        catalog = SpanCatalog()
        catalog.present([make_hit(1, text)], "c0", "whack-a-mole")
        citation = ExampleVerifier(catalog).verify("c0h1s1", wording="whack-a-mole with these bugs",
                                                   expression="It's like playing whack a mole.",
                                                   key_phrase="whack a mole", source_use="s", adaptation="a")
        self.assertEqual(citation.quote, text)

    def test_verifier_accepts_only_shown_verbatim_wording_with_the_key_phrase_once(self):
        catalog = SpanCatalog()
        catalog.present([make_hit(1, TEXT)], "c0", "push back on")
        verify = ExampleVerifier(catalog).verify
        args = {"source_use": "s", "adaptation": "a", "expression": "I'd push back on that.", "key_phrase": "push back on"}
        self.assertIsNone(verify("c9h9s9", wording="push back", **args))
        self.assertIsNone(verify("c0h1s2", wording="push back", **args))  # not in that span
        self.assertIsNone(verify("c0h1s1", wording="a little", **args))   # lacks the key phrase
        citation = verify("c0h1s1", wording="I’d PUSH back on that", **args)
        self.assertEqual(citation.quote, "Honestly, I'd push back on that a little.")
        self.assertIsNone(verify("c0h1s1", wording="push back on that", **args))  # already used
        verifier = ExampleVerifier(catalog)
        verifier.verify("c9h9s9", slot=2, wording="x", **args)
        self.assertEqual(verifier.take_rejections(), [{"slot": 2, "ref": "c9h9s9", "reason": "unknown_or_reused_ref"}])
        self.assertEqual(verifier.take_rejections(), [])

    def test_a_released_example_frees_its_span(self):
        catalog = SpanCatalog()
        catalog.present([make_hit(1, TEXT)], "c0", "push back on")
        verifier = ExampleVerifier(catalog)
        args = {"wording": "push back on that", "source_use": "s", "adaptation": "a", "expression": "push back on it",
                "key_phrase": "push back on"}
        citation = verifier.verify("c0h1s1", **args)
        self.assertIsNone(verifier.verify("c0h1s1", **args))
        verifier.release(citation)
        self.assertIsNotNone(verifier.verify("c0h1s1", **args))

    def test_hit_summary_shows_the_show_and_a_snippet_around_the_key_phrase(self):
        hit = make_hit(1, "x" * 300 + " push back on that " + "y" * 300, feed_id=218840)
        summary = hit_summary(hit, "push back on")
        self.assertEqual((summary["show"], len(summary["snippet"]) <= 160), ("go_time", True))
        self.assertIn("push back on that", summary["snippet"])
        self.assertIsNone(hit_summary(make_hit(1), None)["show"])

    def test_citation_copies_exact_quote_and_bounded_context(self):
        hit = make_hit(1, "x" * 300 + " Quote here. " + "y" * 300)
        citation = make_citation(hit, 301, 312, "s", "a")
        self.assertEqual(citation.quote, "Quote here.")
        self.assertEqual((citation.context_start_char, citation.context_end_char), (101, 512))

    def test_citation_carries_the_audio_clip_and_old_records_stay_valid(self):
        hit = make_hit(1, "x" * 300 + " Quote here. " + "y" * 300).model_copy(update={
            "audio_url": "https://cdn.example.org/ep.mp3", "audio_start_ms": 85_000, "audio_end_ms": 120_000,
            "audio_estimated": True})
        citation = make_citation(hit, 301, 312, "s", "a")
        self.assertEqual((citation.audio_url, citation.audio_start_ms, citation.audio_end_ms, citation.audio_estimated),
                         ("https://cdn.example.org/ep.mp3", 85_000, 120_000, True))
        old = make_citation(make_hit(1, "Quote here."), 0, 11, "s", "a").model_dump(mode="json")
        for name in ("audio_url", "audio_start_ms", "audio_end_ms", "audio_estimated"):
            old.pop(name)
        restored = SourceCitation.model_validate_json(json.dumps(old))
        self.assertEqual((restored.audio_url, restored.audio_estimated), (None, False))


if __name__ == "__main__":
    unittest.main()
