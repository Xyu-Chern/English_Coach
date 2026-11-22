"""An offline world for dry runs: scripted model replies, an in-memory snapshot and a rule-based judge.

Nothing here calls a network, a database or a paid API. The chat model answers every call
type of both systems (candidates and their retry, selection, the baseline's revision, the
agent's turns and its pick-only call) from the payload alone, so the real prefix, systems,
verifier, recorder, runner, grader, report and review page run unchanged.
Five tasks have authored scenarios:

    ko-spec-ctx-1               two verified quotes are wrong: one shows only part of the meaning
                                (partial_chunk), one another sense. The baseline keeps both; the
                                agent re-picks them in its review
    ko-usage-con-1              the set misses a required question form: the baseline has three
                                verified examples and stops; the agent searches, then replaces one slot
    ko-spec-idiom-ctx-1         a pick is rejected (wording not copied): the baseline adopts a seen span
                                for a reserve expression, the agent re-picks with the exact wording
    ko-unans-source_other_show  declined: source not in the corpus
    ko-unans-injection          declined: out of scope

The agent parts above describe the agent of the submitted evaluation (submission_agent(),
AgentPipeline(locked=False)). The registered agent keeps the verified-slot lock: in the first two
scenarios the first stage verifies every slot, so it ends there like the baseline; in the third it
still re-picks the rejected slot.

    dry_run(results_dir, repeats=1) -> the run directory, with attempts, grades, report and review.html
    dry_run(results_dir, locked=False) -> the same with the submission agent
"""

import hashlib
import io
import json
import os
import re
from contextlib import contextmanager, nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from translation_agent_demo.agents import SYSTEMS as CODE_SYSTEMS, AgentPipeline
from translation_agent_demo.agents.contracts import ChatCompletion, CorpusSearchHit, ModelUsage
from translation_agent_demo.agents.evidence import SHOW_FEEDS
from translation_agent_demo.providers.embedding_protocol import EmbeddingBatch

from evaluation.tasks import load_tasks

CHAT_MODEL = "claude-haiku-5-5"  # priced as Haiku so the cost path runs; the replies are scripted
JUDGE_MODEL = "offline-judge"
PROFILE = {"model": "offline-embedding", "dimensions": 2, "processing_version": "offline"}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
PARTIAL, OTHER_SENSE = "partial_chunk", "different_sense"

# (show, episode, text, what the speaker communicates, (verdict, why the judge rejects it as an example) or None)
PASSAGES = (
    ("go_time", "Debugging production at 3am",
     "The root cause of my love for Go is the tooling, honestly. Everything else came later.",
     "The speaker jokes about why they like Go.",
     (OTHER_SENSE, "Here 'root cause' is a joke about liking Go; it does not say that an incident's cause is still "
                   "unknown.")),
    ("the_changelog", "Incident reviews that actually help",
     "We still don't know the root cause yet, so let's not guess in the incident channel. "
     "We'll post an update once we have the logs.",
     "The speaker says the cause is unconfirmed and asks people not to guess.", None),
    ("the_changelog", "Hot takes and outages", "People jump to conclusions on social media all the time.",
     "The speaker observes that people online decide too quickly.",
     (PARTIAL, "The quote has 'jump to conclusions' but only describes other people; it does not show asking a "
               "team not to decide before the evidence is in.")),
    ("js_party", "Postmortems without blame",
     "Let's not jump to conclusions before we see the logs. It could be the cache or it could be the network.",
     "The speaker warns against deciding the cause before seeing the evidence.", None),
    ("go_time", "Observability in practice",
     "Let's stick to what we actually know and update the doc as we learn more.",
     "The speaker asks the team to state only confirmed facts.", None),
    ("the_changelog", "Shipping under pressure", "Okay, that's still just a theory until we reproduce it.",
     "The speaker says an explanation is unproven until it is reproduced.", None),
    ("js_party", "Planning the next release",
     "We need to get on the same page about what done means for this release.",
     "The speaker asks the team to agree on a shared definition.", None),
    ("go_time", "Remote team rituals", "Let's make sure we're all on the same page before the demo.",
     "The speaker checks that everyone shares the same understanding.", None),
    ("the_changelog", "API design reviews", "Just so we're on the same page, the API freeze is on Friday.",
     "The speaker states a fact so that everyone has the same understanding.", None),
    ("js_party", "Disagreeing well", "I don't think we're on the same page here, honestly.",
     "The speaker says the two sides understand the issue differently.", None),
    ("go_time", "Migrations without downtime",
     "Are we all on the same page about the migration plan? If not, now is the time to say so.",
     "The speaker asks whether everyone agrees on the plan.", None),
    ("the_changelog", "Fundraising for open source", "We shouldn't count our chickens before the funding closes.",
     "The speaker warns against relying on money that has not arrived.", None),
    ("js_party", "Startup engineering", "Let's not get ahead of ourselves, we haven't shipped anything yet.",
     "The speaker tells the team not to plan for success too early.", None),
    ("go_time", "Hiring your first engineers",
     "Hiring before product-market fit is putting the cart before the horse.",
     "The speaker says the steps are in the wrong order.", None),
    ("the_changelog", "Build systems", "First things first, let's get the build green again.",
     "The speaker sets the first priority.", None),
)


def _candidates(*pairs, function="", note="") -> list[dict]:
    return [{"expression": e, "key_phrase": k, "function": function, "note": note} for e, k in pairs]


SCENARIOS = {
    "ko-spec-ctx-1": {
        "kind": "specific",
        "candidates": _candidates(
            ("Let's not jump to conclusions.", "jump to conclusions"),
            ("We don't know the root cause yet.", "root cause"),
            ("Let's stick to what we actually know.", "what we actually know"),
            ("That's still just a theory.", "just a theory"),
            ("Let's not treat a guess as a fact.", "guess as a fact"),
            ("We need more data before we say that.", "more data"),
            function="ask for caution in an incident call", note="Neutral; fine with seniors in a meeting.")},
    "ko-usage-con-1": {
        "kind": "usage",
        "candidates": _candidates(
            ("We need to get on the same page about the release.", "on the same page"),
            ("Let's make sure we're all on the same page.", "make sure we're all on the same page"),
            ("Just so we're on the same page, the deadline is Friday.", "so we're on the same page"),
            ("We're not on the same page here.", "not on the same page"),
            ("Glad we're on the same page.", "glad we're on the same page"),
            ("Get everyone on the same page.", "everyone on the same page"),
            function="check shared understanding", note="Common in planning meetings."),
        "question_form": {"expression": "Are we all on the same page?", "key_phrase": "are we all on the same page",
                          "function": "ask whether everyone agrees", "note": "A direct check at the end of a plan."}},
    "ko-spec-idiom-ctx-1": {
        "kind": "idiom",
        "candidates": _candidates(
            ("Let's not count our chickens before they hatch.", "count our chickens"),
            ("Let's not get ahead of ourselves.", "get ahead of ourselves"),
            ("It's a bit premature to plan hiring.", "a bit premature"),
            ("First things first.", "first things first"),
            ("Don't put the cart before the horse.", "put the cart before the horse"),
            ("Let's not jump the gun.", "jump the gun"),
            function="warn against planning too early", note="Light and friendly; fine between teammates."),
        "paraphrased": {"get ahead of ourselves": "let's not get too far ahead of ourselves"},
        # the baseline finds the first in its span pool and adopts it with no search
        "reserve": _candidates(("We haven't shipped anything yet.", "haven't shipped anything yet"),
                               ("That's putting the cart before the horse.", "putting the cart before the horse"),
                               function="say the plan is premature", note="Plain and friendly; fine between teammates.")},
    "ko-unans-source_other_show": {"decline": "source_not_available",
                                   "note": "That podcast is not in the approved corpus, so no examples can be shown."},
    "ko-unans-injection": {"decline": "out_of_scope",
                           "note": "The request asks for a fixed output instead of English expressions."},
}


def _hit(number: int, show: str, episode: str, text: str) -> CorpusSearchHit:
    feed = SHOW_FEEDS[show]
    return CorpusSearchHit(
        chunk_id=UUID(int=1000 + number), document_id=UUID(int=2000 + number), build_id=UUID(int=3000),
        source_key=f"podcast_index:{feed}:{number}", feed_id=feed, episode_id=number, episode_title=episode,
        episode_url=f"https://example.test/{show}/{number}", transcript_url=None, language="en", text=text,
        similarity=0.5, start_ms=0, end_ms=30000, speakers=(), spans=(), rights_status="approved",
        rights_review_url=None, license_id="offline-fixture", license_url=None, attribution="Authored test content")


HITS = tuple(_hit(n, show, episode, text) for n, (show, episode, text, _, _) in enumerate(PASSAGES, 1))
USES = {text: use for _, _, text, use, _ in PASSAGES}
BAD = {text: problem for _, _, text, _, problem in PASSAGES if problem}  # text -> (verdict, why)
# Found only by its exact phrase: a meaning search never ranks it in the top 3, so the agent has
# to search for the missing question form instead of finding it among the prefix's spans.
LITERAL_ONLY = {"Are we all on the same page about the migration plan? If not, now is the time to say so."}


def _fold(text: str) -> str:
    return (text or "").translate(_QUOTES).casefold()


def _has_words(text: str, phrase: str) -> bool:
    """Whole-word, case-insensitive containment: the Python twin of the snapshot's literal count."""
    return re.search(r"(?<!\w)" + re.escape(_fold(phrase)) + r"(?!\w)", _fold(text)) is not None


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:6], 16)


def _scenarios_by_question() -> dict[str, dict]:
    return {t.question: SCENARIOS[t.id] for t in load_tasks() if t.id in SCENARIOS}


def _passage_of(text: str) -> str | None:
    return next((p for p in USES if text and text in p), None)


# ------------------------------------------------------------------ search
class OfflineEmbeddings:
    """A two-number 'embedding': the first number seeds which passages a meaning search returns."""

    def embed_texts(self, texts) -> EmbeddingBatch:
        return EmbeddingBatch(PROFILE["model"], PROFILE["dimensions"],
                              tuple((float(_seed(t) % 997), 1.0) for t in texts), sum(max(1, len(t) // 4) for t in texts))


class OfflineStore:
    """The SnapshotStore interface over PASSAGES: literal matches in order, else a seeded rotation."""

    profile = PROFILE

    def search(self, vector, *, limit=5, min_similarity=None, language=None, feed_ids=None, literal_phrase=None,
               document_ids=None) -> tuple[CorpusSearchHit, ...]:
        pool = [hit for hit in HITS if feed_ids is None or hit.feed_id in feed_ids]
        if literal_phrase is not None:
            return tuple(hit for hit in pool if _fold(literal_phrase) in _fold(hit.text))[:limit]
        pool = [hit for hit in pool if hit.text not in LITERAL_ONLY]
        start = int(vector[0]) % len(pool)
        return tuple((pool[start:] + pool[:start])[:limit])

    def count_literal(self, phrase, *, language=None, feed_ids=None, document_ids=None) -> int:
        """The whole-corpus literal count, not capped by any search limit."""
        return sum(1 for hit in HITS if (feed_ids is None or hit.feed_id in feed_ids) and _has_words(hit.text, phrase))


# ------------------------------------------------------------------ chat
def _spans(passages) -> list[dict]:
    return [span for passage in passages for span in passage["spans"]]


def _find(spans: list[dict], key_phrase: str | None, exclude=(), *, reads_meaning=True) -> tuple[dict, str] | None:
    """The first span containing the key phrase, and the phrase as written there.

    A selection only matches words (reads_meaning=False), so it can pick a quote that shows only
    part of the meaning or another sense; a review reads the meaning and skips those."""
    for span in spans:
        at = _fold(span["text"]).find(_fold(key_phrase)) if key_phrase else -1
        wrong = reads_meaning and _passage_of(span["text"]) in BAD
        if at >= 0 and span["ref"] not in exclude and not wrong:
            return span, span["text"][at:at + len(key_phrase)]
    return None


def _explained(span: dict, wording: str) -> dict:
    return {"source_use": USES.get(_passage_of(span["text"]), "The speaker uses the wording in conversation."),
            "adaptation": f"Say \"{wording}\" as it is, and swap the topic words for your own situation."}


def _problem(slot: dict) -> tuple[str, str] | None:
    """(verdict, why) when the slot's verified quote does not show the expression's meaning."""
    example = slot["example"]
    return BAD.get(_passage_of(example["quote"])) if example else None


class OfflineChat:
    """Answers each structured call from its payload; stateless, so both systems may call it at once."""

    def __init__(self):
        self.scenarios = _scenarios_by_question()

    def complete_with_usage(self, *, system_prompt: str, user_payload: str, response_format=None) -> ChatCompletion:
        payload = json.loads(user_payload)
        name = response_format["json_schema"]["name"]
        reply = getattr(self, f"_{name}")(payload, self.scenarios[payload["question"]])
        content = json.dumps(reply, ensure_ascii=False)
        usage = ModelUsage(len(system_prompt + user_payload) // 4, len(content) // 4 + 40, 0)
        return ChatCompletion(content, usage=usage, model=CHAT_MODEL)

    # ---------------------------------------------------------- prefix and baseline
    @staticmethod
    def _CandidateSet(payload: dict, scenario: dict) -> dict:
        if "decline" in scenario:
            return {"request_status": scenario["decline"], "status_note": scenario["note"], "kind": "specific",
                    "source_show": None, "candidates": []}
        return {"request_status": "answerable", "status_note": None, "kind": scenario["kind"], "source_show": None,
                "candidates": scenario["candidates"]}

    @staticmethod
    def _Selection(payload: dict, scenario: dict) -> dict:
        picks = []
        for shown in payload["candidates"]:
            found = _find(shown["spans"], shown["key_phrase"], reads_meaning=False)
            pick = {"candidate": shown["candidate"], "ref": None, "expression": shown["expression"], "key_phrase": None,
                    "reusable_wording": None, "source_use": None, "adaptation": None}
            if found:
                span, wording = found
                wording = scenario.get("paraphrased", {}).get(shown["key_phrase"], wording)
                pick.update(ref=span["ref"], key_phrase=shown["key_phrase"], reusable_wording=wording,
                            **_explained(span, wording))
            picks.append(pick)
        return {"picks": picks}

    @staticmethod
    def _Revision(payload: dict, scenario: dict) -> dict:
        """The baseline: the next reserve expression, backed by a seen span when one shows it."""
        reserve = list(scenario.get("reserve", []))
        pool = payload.get("span_pool") or []
        replacements = []
        for slot in payload["unsupported_slots"][:payload["replacements_allowed"]]:
            fresh = [c for c in reserve if c["expression"] not in (slot["tried"] + [slot["expression"]])]
            if fresh:
                reserve.remove(fresh[0])
                item = {"replaces": slot["slot"], **fresh[0], "ref": None, "reusable_wording": None,
                        "source_use": None, "adaptation": None}
                found = _find(pool, fresh[0]["key_phrase"])
                if found:
                    span, wording = found
                    item.update(ref=span["ref"], reusable_wording=wording, **_explained(span, wording))
                replacements.append(item)
        return {"replacements": replacements}

    # ---------------------------------------------------------- agent
    def _AgentDecision(self, payload: dict, scenario: dict) -> dict:
        assessment, actions = self.review(payload, scenario)
        return {"assessment": assessment, "actions": actions,
                "finish": not any(a["type"] == "search" for a in actions)}

    def _FinalPick(self, payload: dict, scenario: dict) -> dict:
        """The agent's pick-only call after a last turn that searched."""
        assessment, actions = self.review(payload, scenario)
        return {"assessment": assessment, "actions": [a for a in actions if a["type"] != "search"]}

    @staticmethod
    def review(payload: dict, scenario: dict) -> tuple[str, list[dict]]:
        """Re-check verified quotes, repair rejected picks, then the request's explicit constraint.

        A repick of a rejected pick also names the expression and key phrase it backs."""
        spans, draft = _spans(payload["passages"]), payload["draft"]
        used = {slot["example"]["ref"] for slot in draft if slot["example"]}
        searched = {_fold(p["key_phrase"]) for p in payload["passages"] if p["key_phrase"]}
        notes, actions = [], []
        for slot in draft:
            example, index, key = slot["example"], slot["slot"], slot["key_phrase"]
            problem = _problem(slot)
            if problem:
                found = _find(spans, key, exclude=used)
                notes.append(f"Slot {index} is verified, but its quote is a {problem[0].replace('_', ' ')}: "
                             f"{problem[1]}")
                if found:
                    span, wording = found
                    actions.append({"type": "repick", "slot": index, "ref": span["ref"], "reusable_wording": wording,
                                    **_explained(span, wording), "expression": None, "key_phrase": None,
                                    "reason": f"{span['ref']} uses '{key}' with the meaning the learner needs "
                                              f"(the old quote is a {problem[0].replace('_', ' ')})."})
            elif not example:
                found = _find(spans, key, exclude=used)
                if found:
                    span, wording = found
                    notes.append(f"Slot {index} was rejected ({', '.join(slot['rejection_reasons'])}); "
                                 f"its span does contain '{key}'.")
                    actions.append({"type": "repick", "slot": index, "ref": span["ref"], "reusable_wording": wording,
                                    **_explained(span, wording), "expression": slot["expression"], "key_phrase": key,
                                    "reason": "Copy the wording exactly from the span this time."})
        form = scenario.get("question_form")
        if form and not any(slot["expression"].rstrip().endswith("?") for slot in draft):
            notes.append("The request asks for one question, and no expression is a question.")
            found = _find(spans, form["key_phrase"], exclude=used)
            if found:
                span, wording = found
                actions.append({"type": "replace", "slot": len(draft) - 1, **form, "ref": span["ref"],
                                "reusable_wording": wording, **_explained(span, wording),
                                "reason": "Only the last slot changes; the other two already work."})
            elif _fold(form["key_phrase"]) not in searched and payload["remaining"]["searches"] > 0:
                actions.append({"type": "search", "slot": None, "query": form["expression"],
                                "key_phrase": form["key_phrase"], "reason": "Find a question-form example."})
        return " ".join(notes) or "Every quote shows the intended meaning and the set meets the request.", actions


# ------------------------------------------------------------------ judge and corpus
class OfflineJudge:
    """The grader's Judge interface with rules instead of a model; every vote of a unit agrees."""

    def __init__(self, settings=None, prompts=None, schemas=None, **_):
        self.scenarios = _scenarios_by_question()

    def __call__(self, kind: str, payload: dict) -> dict:
        vote = getattr(self, kind)(payload)
        content = json.dumps(vote, ensure_ascii=False)
        return {"content": content, "model": JUDGE_MODEL,
                "usage": {"input_tokens": len(json.dumps(payload)) // 4, "output_tokens": len(content) // 4,
                          "cached_input_tokens": 0}}

    @staticmethod
    def expression(payload: dict) -> dict:
        return {"fits": "pass", "natural": "pass", "note_ok": "pass",
                "reason": f"'{payload['expression']}' does what the learner asks and sounds natural."}

    @staticmethod
    def example(payload: dict) -> dict:
        problem = BAD.get(_passage_of(payload["displayed_quote"]))
        return {"shows_use": "fail" if problem else "pass", "explanation_ok": "pass",
                "reason": problem[1] if problem else
                "The speaker uses the expression's key wording with the meaning the learner needs."}

    def set(self, payload: dict) -> dict:
        needs_question = "question_form" in self.scenarios.get(payload["learner_request"], {})
        asks = any(e["expression"].rstrip().endswith("?") for e in payload["expressions"])
        verdict = ("pass" if asks else "fail") if needs_question else "not_applicable"
        reason = ("One expression is a question, as the request requires." if verdict == "pass" else
                  "The request asks for one question example, but none of the expressions is a question."
                  if verdict == "fail" else "No set-level constraint; the expressions are distinct.")
        return {"duplicates": [], "set_constraint": verdict, "first_fits_context": "pass", "reason": reason}


class OfflineCorpus:
    """The grader's Corpus interface: chunk text by id, for the exact-quote check."""

    chunks = {str(hit.chunk_id): {"text": hit.text} for hit in HITS}


class OfflineEnvironment:
    """The LiveEnvironment interface over the offline world."""

    def identity(self) -> dict:
        return {"provider": "offline", "model": CHAT_MODEL, "effort": None, "snapshot_id": "offline-world",
                "embedding_model": PROFILE["model"]}

    def check(self) -> None:
        """Nothing to verify offline."""

    def chat_model(self) -> OfflineChat:
        return OfflineChat()

    def embeddings(self) -> OfflineEmbeddings:
        return OfflineEmbeddings()

    @contextmanager
    def store(self):
        yield OfflineStore()


@contextmanager
def submission_agent():
    """Run the submitted evaluation's agent (AgentPipeline(locked=False)) as "agent" instead of the locked one."""
    with patch.dict(CODE_SYSTEMS, {"agent": AgentPipeline(locked=False)}):
        yield


def dry_run(results: Path, *, run: str = "dryrun", repeats: int = 1, workers: int = 2, locked: bool = True) -> Path:
    """run, grade, report and review through evaluation.eval, offline; returns the run directory.

    locked=False runs the submission agent (submission_agent()) in place of the registered, locked one."""
    from evaluation import eval as cli

    run_dir = Path(results) / run
    tasks = [t for t in load_tasks() if t.id in SCENARIOS]
    with patch.dict(os.environ, {"LLM_MODEL": CHAT_MODEL}), patch("evaluation.judging.Judge", OfflineJudge), \
            (nullcontext() if locked else submission_agent()), redirect_stdout(io.StringIO()):
        cli.run(run_dir, tasks, repeats=repeats, workers=workers, max_new=None, prepare_only=False,
                environment=OfflineEnvironment())
        cli.grade(run_dir, 4, False, corpus=OfflineCorpus())
        cli.report(run_dir)
        cli.review(run_dir)
    return run_dir
