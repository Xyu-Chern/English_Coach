"""Tool: change a slot. Agent actions: repick (another span for the slot) and replace (another expression).

    change_slot   drop or replace the slot's example or expression, then verify the new pick.
                  The guard (G1): a verified example is lost only if the new pick verifies;
                  otherwise the slot is restored, and when the change was for a meaning
                  problem the kept example moves to the end of the answer.
    as_candidate  a replacement's candidate part (used by both systems)
"""

from typing import Literal

from pydantic import Field, model_validator

from ..draft import Draft
from ..results import FrozenModel
from ..schemas.base import _require_contiguous
from ..schemas.prefix import Candidate
from ..session import RequestSession

CANDIDATE_FIELDS = set(Candidate.model_fields)

# An action names its kind in "type", listed first so the decoder commits to the kind before
# its fields. reason is shown in the trace and not length-checked: an over-long explanation
# should not cost an action (the prompt states the lengths). A model's docstring is the
# description in its JSON Schema and reaches the model, so it is frozen with the prompt.


# repick: back a slot with another span already shown; ref null removes a wrong example.
class RepickAction(FrozenModel):
    """A repick may name the variant the span shows, as SELECT picks can (both null: keep the slot's)."""

    type: Literal["repick"]
    slot: int = Field(ge=0, le=20)
    ref: str | None = Field(default=None, max_length=40)
    reusable_wording: str | None = Field(default=None, max_length=200)
    source_use: str | None = Field(default=None, max_length=300)
    adaptation: str | None = Field(default=None, max_length=400)
    reason: str = ""
    expression: str | None = Field(default=None, min_length=1, max_length=300)
    key_phrase: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _whole_variant(self):
        if (self.expression is None) != (self.key_phrase is None):
            raise ValueError("variant_incomplete")
        _require_contiguous(self.key_phrase, self.expression)
        return self


class ReplaceAction(FrozenModel):
    """Put another expression in a slot, with an already-shown span or (ref null) none yet."""

    type: Literal["replace"]
    slot: int = Field(ge=0, le=20)
    expression: str = Field(min_length=1, max_length=300)
    key_phrase: str = Field(min_length=1, max_length=80)
    function: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=300)
    ref: str | None = Field(default=None, max_length=40)
    reusable_wording: str | None = Field(default=None, max_length=200)
    source_use: str | None = Field(default=None, max_length=300)
    adaptation: str | None = Field(default=None, max_length=400)
    reason: str = ""

    @model_validator(mode="after")
    def _contiguous_key_phrase(self):
        _require_contiguous(self.key_phrase, self.expression)
        return self


def as_candidate(item) -> Candidate:
    """A replacement's candidate part (expression, key_phrase, function, note)."""
    return Candidate(**item.model_dump(include=CANDIDATE_FIELDS))


def change_slot(session: RequestSession, draft: Draft, stage: str, index: int, log: dict, *, ref: str | None,
                wording: str | None, source_use: str | None, adaptation: str | None,
                candidate: Candidate | None = None, variant: tuple[str, str] | None = None, meaning: bool = False,
                **details) -> str:
    """Repick a slot's example (candidate None) or replace its expression, then verify the new pick.

    The guard (G1): a verified example is lost only if the new pick verifies. Otherwise the slot is restored
    (a guard event in log) and, when the change was for a meaning problem, moves to the end."""
    slot, before = draft.slots[index], draft.slots[index].expression
    saved = draft.checkpoint(index) if slot.citation is not None else None
    if candidate is not None:
        draft.replace(index, candidate)
    else:
        draft.drop_example(index)
    expression, key_phrase = variant or (slot.expression, slot.key_phrase)
    draft.attach(index, ref, expression=expression, key_phrase=key_phrase, wording=wording, source_use=source_use,
                 adaptation=adaptation)
    kind = "repick" if candidate is None else "replace"
    outcome = ("verified" if slot.citation else f"rejected:{slot.rejections[0]}" if slot.rejections
               else "removed" if candidate is None else "replaced")
    rejections, guard = list(slot.rejections), None
    if saved is not None and slot.citation is None:
        slot = draft.restore(index, saved)
        slot.rejections = rejections
        slot.moved_to_end = slot.moved_to_end or meaning
        why = f"rejected:{rejections[0]}" if rejections else "without_example"
        guard = {"slot": index, "kept_ref": slot.ref, "reason": f"{kind}_{why}", "moved_to_end": slot.moved_to_end}
        log["guard"].append(guard)
        outcome = "kept_verified_example"
    session.record(stage, slot=index, ref=ref, outcome=outcome, expression=slot.expression,
                   previous_expression=before, rejection_reasons=rejections, **({"guard": guard} if guard else {}),
                   **details)
    return outcome
