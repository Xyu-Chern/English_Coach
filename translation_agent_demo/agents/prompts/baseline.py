"""The baseline's prompt: REVISE_PROMPT, once per round."""

from .shared import DROPPED_LAST_TURN, SHOWS_EXPRESSION, _PARITY, _UNTRUSTED

# ---------------------------------------------------------------------------
# 3. REVISE_PROMPT: the baseline's fixed rule, once per round (at most 3 rounds),
#    replacing every slot without a verified example.
#
# In:  {"question", "replacements_allowed", "unsupported_slots": [{"slot", "expression",
#      "key_phrase", "function", "note", "rejection_reasons", "tried", "corpus_count",
#      "spans"}], "verified_slots": [{"slot", "expression"}], "span_pool" (every span seen
#      so far, deduplicated, with refs), "alternatives" (unused candidates),
#      "dropped_last_turn"}.
# Out: Revision: at most replacements_allowed replacements (never more than three). A
#      replacement may carry a ref: its wording then comes from a seen span, goes through
#      the same verifier, and spends no search when it verifies. Any other replacement is
#      searched once and passed to a selection.
# Why these rules:
# - "tried" lists the slot's earlier expressions, so a later round does not propose
#   wording that already found no example.
# - function, note, rejection_reasons and verified_slots back the shared rules (keep the
#   slot's purpose, read the verifier's reasons, no near-duplicate), as the agent's draft does.
# - span_pool and alternatives give the baseline the same information the agent sees; only
#   the flow stays fixed (every unsupported slot, verified slots untouched, no early stop).
_REVISE_HEAD = """Some places (slots) in an answer for an English learner still have no podcast
example. """ + _UNTRUSTED + """
For each such slot you see its expression, its key_phrase, its function and note (the
slot's purpose), the rejection_reasons of its last rejected pick, the expressions already
tried for it, and its last search's corpus_count and spans. verified_slots lists the slots
that already have an example; they stay as they are. Real speakers often say the same
thing differently. Propose at most replacements_allowed replacements, one per slot you
replace (replaces is the slot number), each likely to occur in podcast speech: prefer a
variant whose wording you can see in the spans, otherwise a more common phrasing; never
an expression already tried.
""" + _PARITY

_REVISE_FIELDS = """Give each replacement a key_phrase (the shortest reusable chunk, 1-6 words, one
contiguous piece of the expression), a function label of at most 60 characters and a note
of at most 200 characters."""

REVISE_PROMPT = _REVISE_HEAD + """
You also see span_pool, every span seen so far (deduplicated, with refs and the search
that found it), and alternatives, candidate expressions not in the answer.
""" + _REVISE_FIELDS + """
A replacement may take its wording from a span_pool span: give that ref, reusable_wording
copied character for character from the span (at most 200 characters, containing the key
phrase), source_use (what the speaker communicates there, at most 300 characters) and
adaptation (how the learner reuses it, at most 400 characters). It is verified like any
pick and needs no search. Otherwise set ref, reusable_wording, source_use and adaptation
to null and the replacement is searched next.
""" + SHOWS_EXPRESSION + "\n" + DROPPED_LAST_TURN + """
Return ONLY JSON: {"replacements": [{"replaces": 0, "expression": "...", "key_phrase": "...",
"function": "...", "note": "...", "ref": "..." | null, "reusable_wording": "..." | null,
"source_use": "..." | null, "adaptation": "..." | null}]}"""
