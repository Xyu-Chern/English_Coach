"""The first stage both systems share: run once per request; each system continues from its own copy.

    candidates          one model call: 6 ranked candidates with key phrases, or a decline
                        (source not in the corpus / out of scope): then no expressions, a note,
                        and nothing else runs. A key phrase must be one contiguous piece of its
                        expression (schemas.py drops a candidate whose is not)
    candidates_retry    a compare request with fewer than 3 valid candidates: the call once more
    search_1..6         one search per candidate: passages containing its key phrase first (with
                        search_workers > 1 all at once, session.prefetching; recorded in order)
    select_1            one model call picks at most one span per candidate
    validate_select_1   code verifies each pick (evidence.py); the 3 answer slots are the
                        verified candidates first in rank order, then unsupported ones

FULL_FIRST_STAGE (the default, the only one the evaluation runs) is the above with the frozen prompts. The app
runs FAST_FIRST_STAGE unless COACH_FIRST_STAGE=full (frontend/staged.py): `candidates` (3) with the compact prompts
and spans (`view`), a retry for any request kind, each candidate searched and selected on its own
(parallel_first_stage.py; parallel=False: these steps, one selection for all).
"""

from dataclasses import dataclass, field

from ..draft import ANSWER_SIZE, Draft, Slot
from ..evidence import FULL_VIEW, SHOW_FEEDS, SpanView
from ..prompts.prefix import CANDIDATES_PROMPT, compact_candidates_prompt
from ..schemas.prefix import CandidateSet
from ..session import Budget, CoachError, RequestSession
from ..tools import search_slot, select, slot_searches, validate

FIRST_STAGE_BUDGET = Budget(model_calls=3, searches=6)  # candidates, one retry of them, select
DECLINE_NOTES = {
    "source_not_available": "The requested source is not in the approved podcast corpus, so no expressions "
                            "or examples are shown in place of it.",
    "out_of_scope": "This request is outside what this coach does: finding natural English expressions "
                    "with podcast examples.",
}


@dataclass(frozen=True)
class FirstStageSettings:
    """The first stage's shape. compact=False is the evaluated one: 6 candidates, FULL_VIEW, never parallel.
    parallel: `grace` seconds after the first verified example the stage ends (parallel_first_stage.py)."""

    candidates: int = 6
    compact: bool = False
    view: SpanView = field(default=FULL_VIEW)
    parallel: bool = True
    grace: float = 0.4

    def __post_init__(self):
        if not self.compact and (self.candidates != 6 or self.view != FULL_VIEW):
            raise ValueError("Only the compact first stage changes the number of candidates or the span view.")
        if self.compact:
            compact_candidates_prompt(self.candidates)  # 3 to 6, else ValueError
        else:
            object.__setattr__(self, "parallel", False)
        if not 0 <= self.grace <= 3:
            raise ValueError("grace must be 0 to 3 seconds.")

    @property
    def candidates_prompt(self) -> str:
        return compact_candidates_prompt(self.candidates) if self.compact else CANDIDATES_PROMPT

    @property
    def budget(self) -> Budget:
        """FIRST_STAGE_BUDGET, or the parallel stage's: candidates, a retry, a selection and two searches each."""
        return Budget(min(6, 2 + self.candidates), min(9, 2 * self.candidates)) if self.parallel else FIRST_STAGE_BUDGET

    def label(self) -> str:
        """For logs: "full", or "fast" with its candidates, spans per passage and span length ("/p": parallel)."""
        shape = f"fast/{self.candidates}c/{self.view.per_passage}s/{self.view.chars or 'whole'}"
        return shape + ("/p" if self.parallel else "") if self.compact else "full"


FULL_FIRST_STAGE = FirstStageSettings()
FAST_FIRST_STAGE = FirstStageSettings(candidates=3, compact=True, view=SpanView(per_passage=3, chars=300))


def run_first_stage(session: RequestSession, question: str,
                    settings: FirstStageSettings = FULL_FIRST_STAGE) -> Draft:
    """Candidates, one search each, one selection, verification: the state both systems start from."""
    if settings.parallel:
        from .parallel_first_stage import run_parallel_first_stage
        return run_parallel_first_stage(session, question, settings)
    prompt = settings.candidates_prompt
    generated = session.ask("candidates", prompt, {"question": question}, CandidateSet)
    if (generated.request_status == "answerable" and len(generated.candidates) < ANSWER_SIZE
            and (settings.compact or generated.kind == "compare")):  # 3 are needed: ask once more
        retry = {"question": question, "retry": {"valid_candidates": len(generated.candidates),
                                                 "needed": ANSWER_SIZE, "dropped_last_turn": session.take_dropped()}}
        generated = session.ask("candidates_retry", prompt, retry, CandidateSet)
    if generated.request_status != "answerable":
        note = generated.status_note or DECLINE_NOTES[generated.request_status]
        session.record("decline", request_status=generated.request_status, note=note)
        return Draft(question, [], decline=note)
    if len(generated.candidates) < ANSWER_SIZE:
        raise CoachError("invalid_model_output")
    chosen = generated.candidates[:settings.candidates]
    draft = Draft(question, [Slot(candidate, rank) for rank, candidate in enumerate(chosen)],
                  feeds=[SHOW_FEEDS[generated.source_show]] if generated.source_show else None)
    indices = list(range(len(draft.slots)))
    with session.prefetching(slot_searches(draft, indices)):
        for index in indices:
            search_slot(session, draft, index, stage=f"search_{index + 1}", ref_prefix=f"c{index}",
                        view=settings.view)
    select(session, draft, "select_1", list(range(len(draft.slots))), compact=settings.compact)
    draft.narrow()
    validate(session, draft, "validate_select_1", alternatives=[c.expression for c in draft.alternatives])
    return draft
