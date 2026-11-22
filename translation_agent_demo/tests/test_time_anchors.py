"""Time anchors from inline transcript markers: extraction, segment anchors, interpolation, offsets.

Pure functions only; no database or network.
"""

import unittest

from translation_agent_demo.storage.time_anchors import (
    DEFAULT_MS_PER_CHAR, MAX_MS_PER_CHAR, MIN_MS_PER_CHAR, SOURCE_INLINE_MARKER, SOURCE_SEGMENT_END,
    SOURCE_SEGMENT_START, Anchor, TimeEstimate, chunk_to_document_offset, document_anchors,
    extract_inline_markers, interpolate, monotonic,
)


def ms(h=0, m=0, s=0, frac=0):
    return ((h * 60 + m) * 60 + s) * 1000 + frac


class ExtractTests(unittest.TestCase):
    def test_unescaped_and_escaped_markers_point_at_the_paragraph(self):
        text = "Intro. [00:12:06.15] Yeah. So it's \\[00:13:00.25\\]   Next."
        anchors = extract_inline_markers(text)
        self.assertEqual([time for _, time in anchors], [ms(0, 12, 6, 150), ms(0, 13, 0, 250)])
        self.assertEqual([text[offset:offset + 4] for offset, _ in anchors], ["Yeah", "Next"])

    def test_fractions_of_one_to_three_digits(self):
        for marker, expected in (("[00:00:01.5]", 1500), ("[00:00:01.15]", 1150), ("[00:00:01.153]", 1153),
                                 ("[00:00:01]", 1000)):
            with self.subTest(marker=marker):
                self.assertEqual(extract_inline_markers(marker + " x"), [(len(marker) + 1, expected)])

    def test_hours_above_one_and_minute_second_markers(self):
        cases = {"[02:03:04.5]": ms(2, 3, 4, 500), "[11:59:59.99]": ms(11, 59, 59, 990),
                 "[1:04:02]": ms(1, 4, 2), "[08:24]": ms(0, 8, 24), "\\[59:59\\]": ms(0, 59, 59), "[7:05]": ms(0, 7, 5)}
        for marker, expected in cases.items():
            with self.subTest(marker=marker):
                self.assertEqual([time for _, time in extract_inline_markers(f"a {marker} b")], [expected])

    def test_malformed_markers_are_ignored(self):
        for text in ("[00:61:00]", "[00:00:60]", "[00:00:00:00]", "[1.5]", "[12:3]", "[00:00:01.1234]",
                     "[laughs]", "12:30", "[123:00:00]"):
            with self.subTest(text=text):
                self.assertEqual(extract_inline_markers(text), [])

    def test_marker_at_the_end_points_past_the_text(self):
        self.assertEqual(extract_inline_markers("done [00:10] "), [(13, 10_000)])


class MonotonicTests(unittest.TestCase):
    def test_a_single_typo_drops_only_itself(self):
        anchors = [(10, 1000), (20, 3_540_000), (30, 3000), (40, 4000), (50, 5000)]
        self.assertEqual(monotonic(anchors), [(10, 1000), (30, 3000), (40, 4000), (50, 5000)])

    def test_equal_times_and_extra_fields_are_kept(self):
        self.assertEqual(monotonic([(20, 5, "b"), (10, 5, "a")]), [(10, 5, "a"), (20, 5, "b")])
        self.assertEqual(monotonic([]), [])


class DocumentAnchorTests(unittest.TestCase):
    def test_offsets_count_over_cue_texts_without_separators(self):
        cues = [("Hello there.", "A"), ("[00:30] Second turn.", "B"), ("More [01:00] text.", None)]
        anchors = document_anchors(cues)
        joined = "".join(text for text, _ in cues)
        self.assertEqual([(a.time_ms, a.source) for a in anchors],
                         [(30_000, SOURCE_INLINE_MARKER), (60_000, SOURCE_INLINE_MARKER)])
        self.assertEqual([joined[a.char_offset:a.char_offset + 4] for a in anchors], ["Seco", "text"])

    def test_labelled_marker_only_cue_starts_an_untranscribed_segment(self):
        before = "x" * 1000 + "."
        after = "y" * 2000
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
        segment_end = [a for a in anchors if a.source == SOURCE_SEGMENT_END]
        self.assertEqual([a.time_ms for a in segment_end], [600_000])  # clamped up to the segment start
        self.assertEqual(anchors[-1].source, SOURCE_SEGMENT_START)  # trailing Outro: no later anchor, no estimate

    def test_unlabelled_marker_only_cue_and_break_ranges_are_plain_markers(self):
        cues = [("[03:00]", None), ("*A played clip.*", None), ("[44:44] to [46:37]", "Break"), ("Back.", "A")]
        anchors = document_anchors(cues)
        self.assertEqual([(a.time_ms, a.source) for a in anchors],
                         [(180_000, SOURCE_INLINE_MARKER), (ms(0, 44, 44), SOURCE_INLINE_MARKER),
                          (ms(0, 46, 37), SOURCE_INLINE_MARKER)])
        self.assertEqual(anchors[0].char_offset, len("[03:00]"))

    def test_no_markers_no_anchors(self):
        self.assertEqual(document_anchors([("Just speech.", "A")]), [])


class InterpolateTests(unittest.TestCase):
    ANCHORS = [(1000, 60_000), (2000, 120_000), (3000, 150_000)]

    def test_linear_between_anchors_with_the_gap(self):
        self.assertEqual(interpolate(self.ANCHORS, 1500, doc_length=4000, duration_ms=300_000),
                         TimeEstimate(90_000, "anchored", 60_000))
        self.assertEqual(interpolate(self.ANCHORS, 2500, doc_length=4000, duration_ms=300_000),
                         TimeEstimate(135_000, "anchored", 30_000))

    def test_exactly_on_an_anchor(self):
        self.assertEqual(interpolate(self.ANCHORS, 2000, doc_length=4000, duration_ms=None),
                         TimeEstimate(120_000, "anchored", 0))

    def test_extrapolation_uses_the_nearest_two_anchors_rate(self):
        after = interpolate(self.ANCHORS, 3500, doc_length=4000, duration_ms=None)
        self.assertEqual(after, TimeEstimate(150_000 + 500 * 45, "extrapolated", 500 * 45))  # 30 ms/char -> 45
        before = interpolate(self.ANCHORS, 500, doc_length=4000, duration_ms=None)
        self.assertEqual(before, TimeEstimate(60_000 - 500 * 60, "extrapolated", 500 * 60))

    def test_extrapolation_rate_is_clamped_and_skips_close_pairs(self):
        # The last two anchors straddle a break (60 s over 10 characters): not a speech rate.
        anchors = [(0, 0), (2000, 126_000), (2010, 136_000)]
        estimate = interpolate(anchors, 3010, doc_length=None, duration_ms=None)
        self.assertEqual(estimate.time_ms, 136_000 + round(1000 * 136_000 / 2010))
        steep = [(0, 0), (1000, 900_000)]
        self.assertEqual(interpolate(steep, 1100, doc_length=None, duration_ms=None).time_ms,
                         900_000 + 100 * MAX_MS_PER_CHAR)

    def test_single_anchor_uses_the_global_rate_or_the_default(self):
        self.assertEqual(interpolate([(1000, 50_000)], 2000, doc_length=10_000, duration_ms=700_000).time_ms,
                         50_000 + 1000 * 70)
        self.assertEqual(interpolate([(1000, 50_000)], 2000, doc_length=None, duration_ms=None).time_ms,
                         50_000 + 1000 * DEFAULT_MS_PER_CHAR)

    def test_no_anchors_falls_back_to_proportion_or_nothing(self):
        self.assertEqual(interpolate([], 2500, doc_length=10_000, duration_ms=600_000),
                         TimeEstimate(150_000, "proportional", 600_000))
        self.assertEqual(interpolate([], 2500, doc_length=None, duration_ms=600_000), TimeEstimate(None, "none", None))
        self.assertEqual(interpolate([], 2500, doc_length=10_000, duration_ms=None), TimeEstimate(None, "none", None))

    def test_results_stay_inside_the_episode(self):
        self.assertEqual(interpolate(self.ANCHORS, 9000, doc_length=None, duration_ms=160_000).time_ms, 160_000)
        self.assertEqual(interpolate([(5000, 10_000), (6000, 70_000)], 0, doc_length=None, duration_ms=None).time_ms, 0)
        self.assertEqual(interpolate(self.ANCHORS, 9000, doc_length=3200, duration_ms=None).time_ms, 150_000 + 200 * 45)

    def test_accepts_stored_anchor_tuples(self):
        anchors = [Anchor(0, 0), Anchor(100, 6000, SOURCE_SEGMENT_START), Anchor(107, 80_000, SOURCE_SEGMENT_END)]
        self.assertEqual(interpolate(anchors, 107, doc_length=None, duration_ms=None).time_ms, 80_000)


class ChunkOffsetTests(unittest.TestCase):
    CUES = ["[00:00] Hello world. Second sentence.", "Next cue here.", "Third cue."]
    STARTS = [0, len(CUES[0]), len(CUES[0]) + len(CUES[1])]

    def test_chunk_offsets_map_back_to_the_same_characters(self):
        spans = [{"cue_index": 0, "start_char": 21, "end_char": 37}, {"cue_index": 1, "start_char": 0, "end_char": 14},
                 (2, 0, 5)]
        chunk_text = " ".join(self.CUES[c][s:e] for c, s, e in
                              [(x["cue_index"], x["start_char"], x["end_char"]) if isinstance(x, dict) else x
                               for x in spans])
        document = "".join(self.CUES)
        joins = {16, 31}  # the spaces chunking puts between slices
        self.assertEqual({i for i in joins if chunk_text[i] == " "}, joins)
        for i, char in enumerate(chunk_text):
            if i not in joins:
                with self.subTest(i=i):
                    self.assertEqual(document[chunk_to_document_offset(spans, self.STARTS, i)], char)
        self.assertEqual(chunk_to_document_offset(spans, self.STARTS, 17), self.STARTS[1])
        self.assertEqual(chunk_to_document_offset(spans, self.STARTS, 16), 37)  # exclusive end of slice 1
        self.assertEqual(chunk_to_document_offset(spans, self.STARTS, 10_000), self.STARTS[2] + 5)

    def test_a_chunk_needs_spans(self):
        with self.assertRaises(ValueError):
            chunk_to_document_offset([], [0], 0)


if __name__ == "__main__":
    unittest.main()
