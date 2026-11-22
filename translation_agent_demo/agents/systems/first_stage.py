"""The first stage both systems share: run once per request; each system continues from its own copy.

    candidates          one model call: 6 ranked candidates with key phrases, or a decline
                        (source not in the corpus / out of scope): then no expressions, a note,
                        and nothing else runs. A key phrase must be one contiguous piece of its
                        expression (schemas.py drops a candidate whose is not)
    candidates_retry    a compare request with fewer than 3 valid candidates: the call once more
    search_1..6         one search per candidate: passages containing its key phrase first. With
                        search_workers > 1 the six run at once (session.prefetching); they are
                        still recorded and applied in candidate order, as if run one by one
    select_1            one model call picks at most one span per candidate
    validate_select_1   code verifies each pick (evidence.py); the 3 answer slots are the
                        verified candidates first in rank order, then unsupported ones
"""

from ..draft import ANSWER_SIZE, Draft, Slot
from ..evidence import SHOW_FEEDS
from ..prompts.prefix import CANDIDATES_PROMPT
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


def run_first_stage(session: RequestSession, question: str) -> Draft:
    """Candidates, one search each, one selection, verification: the state both systems start from."""
    generated = session.ask("candidates", CANDIDATES_PROMPT, {"question": question}, CandidateSet)
    if (generated.request_status == "answerable" and generated.kind == "compare"
            and len(generated.candidates) < ANSWER_SIZE):  # a comparison needs 3 candidates: ask once more
        retry = {"question": question, "retry": {"valid_candidates": len(generated.candidates),
                                                 "needed": ANSWER_SIZE, "dropped_last_turn": session.take_dropped()}}
        generated = session.ask("candidates_retry", CANDIDATES_PROMPT, retry, CandidateSet)
    if generated.request_status != "answerable":
        note = generated.status_note or DECLINE_NOTES[generated.request_status]
        session.record("decline", request_status=generated.request_status, note=note)
        return Draft(question, [], decline=note)
    if len(generated.candidates) < ANSWER_SIZE:
        raise CoachError("invalid_model_output")
    draft = Draft(question, [Slot(candidate, rank) for rank, candidate in enumerate(generated.candidates)],
                  feeds=[SHOW_FEEDS[generated.source_show]] if generated.source_show else None)
    indices = list(range(len(draft.slots)))
    with session.prefetching(slot_searches(draft, indices)):
        for index in indices:
            search_slot(session, draft, index, stage=f"search_{index + 1}", ref_prefix=f"c{index}")
    select(session, draft, "select_1", list(range(len(draft.slots))))
    draft.narrow()
    validate(session, draft, "validate_select_1", alternatives=[c.expression for c in draft.alternatives])
    return draft
