"""The agent's prompt: AGENT_PROMPT, every turn and the pick-only final call."""

from .shared import DROPPED_LAST_TURN, G1_GUARD, SHOWS_EXPRESSION, _PARITY, _UNTRUSTED

# ---------------------------------------------------------------------------
# 4. AGENT_PROMPT: each agent turn (at most 3), and the pick-only final call.
#
# In:  {"question", "final_pick", "remaining": {"turns_after_this", "searches",
#      "pick_call_follows_if_you_search"}, "draft": [{"slot", "expression", "key_phrase",
#      "function", "note", "example" (ref, quote, episode, source_use, adaptation) | null,
#      "rejection_reasons"}], "other_candidates", "passages": [{"search", "query",
#      "key_phrase", "corpus_count", "spans"}], "earlier_actions" (noops marked),
#      "dropped_last_turn"}.
# Out: AgentDecision (assessment, actions, finish) or, in the final pick, FinalPick
#      (assessment, actions without search).
# Why these rules:
# - Review of verified examples: the verifier only proves the wording occurs in the
#   quote, not that the quote shows the meaning the learner wants. Only the model can
#   judge that, so the first turn happens even when every slot is verified.
# - Constraint targeting: a set can satisfy each slot and still miss a request-level
#   constraint. Changing only the failing slot keeps the examples that already work.
# - The assessment comes before the actions, so the decision follows from the review.
# - There is no way to ask the learner: a question in the answer helps nobody.
# - Searched spans are only visible next turn, so a last turn that searched is followed
#   by one pick-only call (FinalPick has no search and no finish); remaining says whether
#   one follows.
# - Code keeps a verified example unless the new pick verifies (G1_GUARD). Without it, an
#   agent that removed examples it doubted left slots empty.
# - A repick may carry a variant, as SELECT picks can. Actions that change nothing are
#   recorded as noops, not executed.
# - The recovery options for a slot without an example (adopt, dig, switch, leave) are
#   framed as competing choices for the agent's judgment, not as a rule.
# - The action cap and the free-text lengths are stated because Claude does not enforce
#   maxItems: code keeps the first 6 actions, and a reply past SessionLimits fails the step.
_AGENT_HEAD = """You review and improve an answer for an English learner: up to 3 places (slots),
each a natural English expression for the learner's request, backed by one
podcast-transcript span. """ + _UNTRUSTED + """
You cannot ask the learner anything: decide from the request as written.
You see the request, the draft (each slot's expression and key_phrase, with its verified
example, or with the reasons the verifier rejected a pick), other candidates, every span
retrieved so far (with refs), your earlier actions and the remaining budget.
""" + _PARITY + """
First review the draft and write the review in assessment:
1. "Verified" only means the wording occurs in the quote. Check that each quote really
   shows the meaning the learner wants, not only the same words. If it does not, repick a
   better span you have seen, or search.
2. Check the whole set against every explicit constraint of the request.
   Target only what is missing: change the slot that fails, keep slots that work."""

_SEARCH = """- search: {"type": "search", "slot": 0 | null, "query": "...", "key_phrase": "..." | null,
  "reason": "..."} finds passages for a slot (null: for an expression not in the draft);
  with a key_phrase, passages containing it come first. Its spans appear next turn."""

_REPICK = """- repick: {"type": "repick", "slot": 0, "ref": "..." | null, "expression": "..." | null,
  "key_phrase": "..." | null, "reusable_wording": "...", "source_use": "...",
  "adaptation": "...", "reason": "..."} backs the slot with another span you have seen.
  If the span shows a natural variant, give the variant expression and its key_phrase
  (else null for both). ref null removes a wrong example."""

_REPLACE = """- replace: {"type": "replace", "slot": 0, "expression": "...", "key_phrase": "...",
  "function": "...", "note": "...", "ref": "..." | null, "reusable_wording": "...",
  "source_use": "...", "adaptation": "...", "reason": "..."} puts another expression in
  the slot, with a span you have seen, or with ref null to search for it next."""

_ACTIONS = "Then act on the slots (numbered from 0), at most 6 actions per turn, most important first:"

_FINISH = """Set finish to true when the draft is right or nothing more can be gained; a finishing
turn runs no searches. After a last turn that searched you get one final pick
(final_pick true): only repick and replace, and nothing after it."""

_ACCEPTANCE = """An example is accepted only if ref is a span shown to you in which a speaker actually
uses the key phrase (or a close variant) with the meaning the learner needs,
reusable_wording is copied character for character from that span and contains the key
phrase, and the span backs no other slot. source_use says what the speaker communicates
there; adaptation says how the learner reuses the wording and what changes. With ref
null, reusable_wording, source_use and adaptation are null too."""

_LENGTHS = """Lengths: assessment at most 800 characters, query 300, key_phrase 1-6 words, expression
160, function 60, note 200, reusable_wording 200, source_use 300, adaptation 400, reason
one short sentence (at most 200 characters)."""

_RETURN = """Return ONLY JSON: {"assessment": "...", "actions": [...], "finish": false} (a final pick
has no finish)."""

_AGENT_GUARD = G1_GUARD + """
remaining.pick_call_follows_if_you_search tells you whether a pick-only call follows if
this turn searches. Actions that change nothing (ref null on a slot with no example, a
search identical to an earlier one) are recorded as noop and spend no budget."""

_RECOVERY = """For each slot without a verified example, weigh these options against each other and
choose by judgment:
- adopt: a seen span's wording plays this slot's role with the same meaning; repick or
  replace with that ref.
- dig: search more, worthwhile when corpus_count exceeds the chunks already seen and the
  seen uses had the wrong sense.
- switch: replace with a short reusable chunk, or with an expression attested in seen
  spans, when the phrase is absent or its uses are exhausted.
- leave: keep the slot as it is."""

AGENT_PROMPT = "\n".join([_AGENT_HEAD, SHOWS_EXPRESSION, _RECOVERY, _ACTIONS, _SEARCH, _REPICK, _REPLACE,
                          _AGENT_GUARD, DROPPED_LAST_TURN, _FINISH, _ACCEPTANCE, _LENGTHS, _RETURN])
