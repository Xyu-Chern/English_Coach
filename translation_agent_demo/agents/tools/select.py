"""Tool: pick examples. One model call picks at most one span per slot; code verifies every pick.

Used by the shared first stage and by each baseline round (the agent picks through repick/replace).
The app's fast first stage selects in the compact shape (compact=True): SELECT_COMPACT_PROMPT, which asks
only for the picks with short explanations, spans without their episode title, and a pick whose quote
belongs to another span of the same candidate moved to that span (repaired_ref).
"""

from ..draft import Draft
from ..evidence import occurs_in
from ..prompts.prefix import SELECT_COMPACT_PROMPT, SELECT_PROMPT
from ..schemas.prefix import Selection
from ..session import RequestSession

COMPACT_SPAN_FIELDS = ("ref", "text", "has_key_phrase")  # what a compact selection shows of each span


def select(session: RequestSession, draft: Draft, stage: str, indices: list[int], *, compact: bool = False) -> None:
    """One model call picks at most one span per slot from its latest search; code verifies each pick."""
    def spans(index: int) -> list[dict]:
        shown = draft.spans_of(draft.slots[index])
        return [{key: span[key] for key in COMPACT_SPAN_FIELDS} for span in shown] if compact else shown

    shown = [{"candidate": i, "expression": draft.slots[i].expression, "key_phrase": draft.slots[i].key_phrase,
              "corpus_count": draft.corpus_count_of(draft.slots[i]), "spans": spans(i)}
             for i in indices]
    prompt = SELECT_COMPACT_PROMPT if compact else SELECT_PROMPT
    selection = session.ask(stage, prompt, {"question": draft.question, "candidates": shown}, Selection)
    for pick in selection.picks:
        if pick.candidate not in indices or draft.slots[pick.candidate].citation is not None:
            continue
        ref = repaired_ref(draft, pick.candidate, pick.ref, pick.reusable_wording) if compact else pick.ref
        draft.attach(pick.candidate, ref, expression=pick.expression,
                     key_phrase=pick.key_phrase or draft.slots[pick.candidate].key_phrase,
                     wording=pick.reusable_wording, source_use=pick.source_use, adaptation=pick.adaptation)


def repaired_ref(draft: Draft, index: int, ref: str | None, wording: str | None) -> str | None:
    """Compact selections only: a pick whose wording is not in its ref's span, but is in exactly one other span
    shown for the same candidate, names that span instead. Models sometimes copy the quote of the next passage
    (both say "I'm honored to be here"); the verifier still checks every rule against the span it gets."""
    if not ref or not wording:
        return ref
    span = draft.catalog.get(ref)
    if span is not None and occurs_in(wording, span.text):
        return ref
    others = [shown["ref"] for shown in draft.spans_of(draft.slots[index]) if occurs_in(wording, shown["text"])]
    return others[0] if len(others) == 1 else ref
