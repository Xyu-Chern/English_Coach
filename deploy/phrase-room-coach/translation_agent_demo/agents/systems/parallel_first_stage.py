"""The app's parallel first stage (FirstStageSettings.parallel; never evaluated): the compact first stage per candidate.

Each candidate's search starts once the streamed reply holds its complete, valid JSON object (at most search_workers
at once); each search is followed by one select_1 call with that candidate's spans, verified at once. The stage ends
when all are done or `grace` seconds after the first verified example (the rest: details.unfinished). Only this
thread changes the draft. A failed job leaves its candidate unverified; if none is verified, the first failure ends
the request.
"""

import json
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import ValidationError

from ..draft import ANSWER_SIZE, Draft, Observation, Slot, expression_key
from ..evidence import SHOW_FEEDS
from ..prompts.prefix import SELECT_COMPACT_PROMPT
from ..schemas.prefix import Candidate, CandidateSet, Selection
from ..session import CoachError, RequestSession
from ..tools import search_args, validate
from ..tools.select import COMPACT_SPAN_FIELDS, repaired_ref
from .first_stage import DECLINE_NOTES

# This thread's model call listener: a provider that can stream (anthropic_chat.py) passes it the text so far.
TEXT_LISTENER = ContextVar("coach_text_listener", default=None)
_ANSWERABLE = re.compile(r'"request_status"\s*:\s*"answerable"')
_SHOW = re.compile(r'"source_show"\s*:\s*(?:null|"(go_time|js_party|the_changelog)")')
_CANDIDATES = re.compile(r'"candidates"\s*:\s*\[')
_GAP = re.compile(r"[ \t\r\n,]*")


@contextmanager
def listening(callback):
    token = TEXT_LISTENER.set(callback)
    try:
        yield
    finally:
        TEXT_LISTENER.reset(token)


def streamed_candidates(text: str) -> tuple[str | None, list[dict]]:
    """(source_show, the complete candidate objects) in a CandidateSet reply so far; none until the reply has said
    it is answerable and which show it is limited to (both come first)."""
    status, start = _ANSWERABLE.search(text), _CANDIDATES.search(text)
    show = _SHOW.search(text, 0, start.start()) if start else None
    if not (status and start and show) or status.start() > start.start():
        return None, []
    decoder, found, position = json.JSONDecoder(), [], start.end()
    while text.startswith("{", position := _GAP.match(text, position).end()):
        try:
            item, position = decoder.raw_decode(text, position)
        except ValueError:  # not complete yet
            break
        found.append(item)
    return show.group(1), found


def run_parallel_first_stage(session: RequestSession, question: str, settings) -> Draft:
    stage = _ParallelStage(session, question, settings)
    try:
        return stage.run()
    finally:
        stage.pool.shutdown(wait=False, cancel_futures=True)  # running calls finish; their results are ignored


class _ParallelStage:
    def __init__(self, session: RequestSession, question: str, settings):
        self.session, self.question, self.settings = session, question, settings
        self.events, self.draft = queue.Queue(), None
        # started: expression key -> slot; valid: the keys the replies kept; unfinished: slots with a job running
        self.started, self.valid, self.unfinished, self.errors = {}, set(), set(), []
        self.pending, self.retried = 0, False
        self.searches = threading.BoundedSemaphore(session.deps.search_workers)
        self.pool = ThreadPoolExecutor(1 + 2 * settings.candidates, thread_name_prefix="coach-first")

    def run(self) -> Draft:
        self._ask_candidates("candidates", {"question": self.question})
        generated = deadline = None  # deadline: `grace` seconds after the first verified example
        while generated is None or self.pending:
            timeout = None if generated is None or deadline is None else deadline - time.monotonic()
            if timeout is not None and timeout <= 0:
                break
            try:
                event = self.events.get(timeout=timeout)
            except queue.Empty:
                break
            if event[0] == "candidate":
                self._take(*event[1:])
                continue
            kind, index, future = event
            self.pending -= 1
            self.unfinished.discard(index)
            if kind == "candidates":
                generated = self._candidates_done(future.result())  # a failed call ends the request (CoachError)
                if isinstance(generated, Draft):
                    return generated
            elif future.exception() is not None:
                self.errors.append(future.exception())
            elif kind == "search":
                self._searched(index, *future.result())
            elif self._selected(index, future.result()) and deadline is None:
                deadline = time.monotonic() + self.settings.grace
        return self._finish()

    def _finish(self) -> Draft:
        draft = self.draft
        dropped = {index for key, index in self.started.items() if key not in self.valid}
        for index in dropped:  # taken from the stream, then dropped by the reply's own check
            if draft.slots[index].citation is not None:
                draft.verifier.release(draft.slots[index].citation)
        draft.slots = [slot for index, slot in enumerate(draft.slots) if index not in dropped]
        if not draft.supported and self.errors:
            raise self.errors[0]
        draft.narrow()
        validate(self.session, draft, "validate_select_1", alternatives=[c.expression for c in draft.alternatives],
                 unfinished=sorted(self.unfinished - dropped))
        return draft

    def _ask_candidates(self, stage: str, payload: dict) -> None:
        seen = 0

        def listener(text: str) -> None:  # runs in the call's thread: it only reports
            nonlocal seen
            show, found = streamed_candidates(text)
            for item in found[seen:]:
                self.events.put(("candidate", item, show))
            seen = max(seen, len(found))

        def call():
            with listening(listener):
                return self.session.ask(stage, self.settings.candidates_prompt, payload, CandidateSet)

        self._submit("candidates", None, call)

    def _candidates_done(self, generated: CandidateSet) -> CandidateSet | Draft | None:
        """The reply, a decline's draft, or None while a retry runs."""
        if generated.request_status != "answerable":
            note = generated.status_note or DECLINE_NOTES[generated.request_status]
            self.session.record("decline", request_status=generated.request_status, note=note)
            return Draft(self.question, [], decline=note)
        self.valid |= {expression_key(c.expression) for c in generated.candidates}
        for candidate in generated.candidates:  # the ones the stream did not give (or a provider that cannot stream)
            self._take(candidate.model_dump(), generated.source_show)
        if len(self.valid) >= ANSWER_SIZE:
            return generated
        if self.retried:
            raise CoachError("invalid_model_output")
        self.retried = True
        retry = {"valid_candidates": len(self.valid), "needed": ANSWER_SIZE,
                 "dropped_last_turn": self.session.take_dropped()}
        self._ask_candidates("candidates_retry", {"question": self.question, "retry": retry})
        return None

    def _take(self, item: dict, show: str | None) -> None:
        """Start a valid candidate's search, unless it is already taken or the stage has its candidates."""
        if self.draft is None:
            self.draft = Draft(self.question, [], feeds=[SHOW_FEEDS[show]] if show else None)
        try:
            candidate = Candidate.model_validate(item)
        except ValidationError:
            return
        key, index = expression_key(candidate.expression), len(self.draft.slots)
        if key in self.started or index >= self.settings.candidates:
            return
        self.draft.slots.append(Slot(candidate, index))
        self.started[key] = index
        args = search_args(self.draft, candidate.expression, candidate.key_phrase)

        def search():
            with self.searches:
                return args, self.session.search(args, policy="candidate_expression", stage=f"search_{index + 1}",
                                                 slot=index, ref_prefix=f"c{index}")

        self._submit("search", index, search)

    def _searched(self, index: int, args, found) -> None:
        """Show the spans and ask for this candidate's pick, unless there is nothing to choose from."""
        draft, stage, phrase = self.draft, f"search_{index + 1}", args.literal_phrase
        draft.searches[stage] = Observation(stage, args.query, phrase, found.corpus_count,
                                            draft.catalog.present(found.hits, f"c{index}", phrase, self.settings.view))
        slot = draft.slots[index]
        slot.search = stage
        if not (spans := draft.spans_of(slot)):
            return
        shown = {"candidate": index, "expression": slot.expression, "key_phrase": slot.key_phrase,
                 "corpus_count": found.corpus_count, "spans": [{k: s[k] for k in COMPACT_SPAN_FIELDS} for s in spans]}
        payload = {"question": self.question, "candidates": [shown]}
        self._submit("select", index, lambda: self.session.ask("select_1", SELECT_COMPACT_PROMPT, payload, Selection))

    def _selected(self, index: int, selection: Selection) -> bool:
        """Verify the pick (one candidate was shown: every pick is for it); True if the slot is now verified."""
        draft = self.draft
        slot = draft.slots[index]
        for pick in selection.picks:
            if slot.citation is not None:
                break
            draft.attach(index, repaired_ref(draft, index, pick.ref, pick.reusable_wording), expression=pick.expression,
                         key_phrase=pick.key_phrase or slot.key_phrase, wording=pick.reusable_wording,
                         source_use=pick.source_use, adaptation=pick.adaptation)
        return slot.citation is not None

    def _submit(self, kind: str, index: int | None, work) -> None:
        self.pending += 1
        if index is not None:
            self.unfinished.add(index)
        self.pool.submit(work).add_done_callback(lambda done: self.events.put((kind, index, done)))
