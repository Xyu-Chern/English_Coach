"""Tools that record and finish a draft: validate (a trace step of where it stands) and assemble (the answer)."""

from ..draft import ANSWER_SIZE, Draft, expression_key
from ..results import ExpressionItem
from ..session import RequestSession


def new_log() -> dict:
    """What a validate step reports about a round beyond the draft: guard events and no-ops."""
    return {"guard": [], "noops": []}


def validate(session: RequestSession, draft: Draft, stage: str, **details) -> None:
    """Record where the draft stands: verified count, each slot's status and this step's rejections."""
    session.record(stage, verified=draft.supported, slots=[slot.status(i) for i, slot in enumerate(draft.slots)],
                   excluded=draft.verifier.take_rejections(), semantic_judgment="model_reported_not_human_verified",
                   **details)


def assemble(session: RequestSession, draft: Draft) -> list[ExpressionItem]:
    """Verified first in slot order, then unsupported, then examples the guard kept though doubted; no duplicates;
    at most 3."""
    items, seen = [], set()
    for slot in sorted(draft.slots, key=lambda s: (s.moved_to_end, s.citation is None)):
        if expression_key(slot.expression) in seen:
            continue
        seen.add(expression_key(slot.expression))
        items.append(ExpressionItem(expression=slot.expression, key_phrase=slot.key_phrase or None,
                                    function=slot.candidate.function, note=slot.candidate.note,
                                    citation=slot.citation))
        if len(items) == ANSWER_SIZE:
            break
    session.record("assemble", expressions=len(items), with_example=sum(i.citation is not None for i in items))
    return items
