"""Tool: pick examples. One model call picks at most one span per slot; code verifies every pick.

Used by the shared first stage and by each baseline round (the agent picks through repick/replace).
"""

from ..draft import Draft
from ..prompts.prefix import SELECT_PROMPT
from ..schemas.prefix import Selection
from ..session import RequestSession


def select(session: RequestSession, draft: Draft, stage: str, indices: list[int]) -> None:
    """One model call picks at most one span per slot from its latest search; code verifies each pick."""
    shown = [{"candidate": i, "expression": draft.slots[i].expression, "key_phrase": draft.slots[i].key_phrase,
              "corpus_count": draft.corpus_count_of(draft.slots[i]), "spans": draft.spans_of(draft.slots[i])}
             for i in indices]
    selection = session.ask(stage, SELECT_PROMPT, {"question": draft.question, "candidates": shown}, Selection)
    for pick in selection.picks:
        if pick.candidate not in indices or draft.slots[pick.candidate].citation is not None:
            continue
        draft.attach(pick.candidate, pick.ref, expression=pick.expression,
                     key_phrase=pick.key_phrase or draft.slots[pick.candidate].key_phrase,
                     wording=pick.reusable_wording, source_use=pick.source_use, adaptation=pick.adaptation)
