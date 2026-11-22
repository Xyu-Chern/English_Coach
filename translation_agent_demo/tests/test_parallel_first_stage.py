"""The app's fast path: the parallel first stage (streamed candidates, a search and a selection each, a short grace);
parallel searches and the embedding prefetch give the same answer, trace and budgets as one after another."""

import json
import threading
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from frontend.staged import CoachMode, Final, First, Guard, StagedCoach
from translation_agent_demo.agents import Budget, CoachDependencies, CoachError, ExpressionCoach, RequestSession
from translation_agent_demo.agents.contracts import ChatCompletion, ModelUsage, SearchCorpusArgs, SearchCorpusError
from translation_agent_demo.agents.evidence import SpanView
from translation_agent_demo.agents.prompts import SELECT_COMPACT_PROMPT, compact_candidates_prompt
from translation_agent_demo.agents.systems.first_stage import FirstStageSettings
from translation_agent_demo.agents.systems.parallel_first_stage import listening, streamed_candidates
from translation_agent_demo.config import Settings
from translation_agent_demo.providers.anthropic_chat import AnthropicChatModel
from translation_agent_demo.providers.batched_embeddings import PrefetchedEmbeddings
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel, ScriptedSearch, make_hit, search_result
from translation_agent_demo.tests.test_anthropic_chat import CLAUDE_ENV
from translation_agent_demo.tests.test_pipelines import (CANDIDATES, PREFIX_STAGES, QUESTION, TEXTS, candidates,
                                                         decision, pick, replacement, revision, step)
from translation_agent_demo.tests.test_search_corpus import FixedEmbeddings

PARALLEL = FirstStageSettings(3, True, SpanView(3, 300))
WORDING = {0: "let's table this for now", 2: "I hold off on lunch"}  # candidate 1's passage lacks "park that"
NEW = {"Let's circle back to it.": "We can circle back to it next week.",
       "Let's shelve it for now.": "Let's shelve it for now and keep going."}
# The first stage verifies nothing; revise_1 adopts one replacement by its ref (no search) and
# searches for two others; select_2 verifies both, so the baseline stops after one round.
REPLIES = (candidates(), {"picks": []},
           revision(replacement(0, "Let's put a pin in it.", "put a pin in", ref="c5h1s1",
                                wording="Let's put a pin in it"),
                    replacement(1, "Let's circle back to it.", "circle back"),
                    replacement(2, "Let's shelve it for now.", "shelve it")),
           {"picks": [pick(1, "r1k1h1s1", "circle back to it", expression="Let's circle back to it."),
                      pick(2, "r1k2h1s1", "shelve it for now", expression="Let's shelve it for now.")]})


class KeyedModel:
    """Thread-safe: candidates (the given replies, then 3 valid ones) for the candidates prompt, the scripted pick of
    the one candidate a selection shows (after `slow[candidate]` seconds), an agent turn that finishes otherwise."""

    def __init__(self, slow=None, replies=()):
        self.slow, self.replies, self.lock, self.selections = slow or {}, list(replies), threading.Lock(), []

    def complete_with_usage(self, *, system_prompt, user_payload, response_format=None):
        payload = json.loads(user_payload)
        if system_prompt == SELECT_COMPACT_PROMPT:
            (shown,) = payload["candidates"]
            index, number = shown["candidate"], [c[0] for c in CANDIDATES].index(shown["expression"])
            with self.lock:
                self.selections.append(number)
            time.sleep(self.slow.get(number, 0))
            picks = ([pick(index, f"c{index}h1s1", WORDING[number], expression=CANDIDATES[number][0])]
                     if number in WORDING else [])
            reply = {"picks": picks}
        elif system_prompt == compact_candidates_prompt(3):
            reply = self.replies.pop(0) if self.replies else candidates(3)
        else:
            reply = decision()
        return ChatCompletion(json.dumps(reply), usage=ModelUsage(10, 5, 0), model="fixture-chat")


class KeyedSearch:
    """Safe to call from many threads: each query has a fixed passage (or fails); each call takes a little while.
    prepare (an embedding prefetch, session.prefetching) records its queries and raises prepare_error if given."""

    def __init__(self, delay=0.05, fail=(), prepare_error=None):
        self.passages = {**{expression: text for (expression, _), text in zip(CANDIDATES, TEXTS)}, **NEW}
        self.numbers = {query: n for n, query in enumerate(self.passages, 1)}
        self.delay, self.fail, self.lock, self.prepare_error = delay, set(fail), threading.Lock(), prepare_error
        self.queries, self.prepared, self.running, self.peak = [], [], 0, 0

    def prepare(self, searches):
        self.prepared.append([args.query for args in searches])
        if self.prepare_error:
            raise self.prepare_error

    def __call__(self, args):
        with self.lock:
            self.queries.append(args.query)
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(self.delay)
            if args.query in self.fail:
                raise SearchCorpusError("storage_unavailable", "down")
            return search_result(make_hit(self.numbers[args.query], self.passages[args.query]))
        finally:
            with self.lock:
                self.running -= 1


def stream(model, settings=PARALLEL):
    search = KeyedSearch(delay=0.02)
    coach = StagedCoach(CoachDependencies(model, search, search_workers=3), CoachMode("agent", True, settings))
    return list(coach.stream(QUESTION, Guard())), search


def answer(workers, search):
    return ExpressionCoach(CoachDependencies(ScriptedModel(*REPLIES), search, search_workers=workers),
                           "baseline").answer(QUESTION)


def comparable(result):
    """The result without what timing or chance decides (ids, durations, start offsets)."""
    data = result.model_dump(mode="json")
    del data["request_id"], data["elapsed_ms"]
    for span in data["trace"]:
        del span["elapsed_ms"], span["details"]["started_ms"]
    return data


def overlaps(result, first, second):  # started_ms is rounded to 0.1 ms: back-to-back steps are not overlapping
    a, b = step(result, first), step(result, second)
    return b.details["started_ms"] < a.details["started_ms"] + a.elapsed_ms - 0.1


def session_for(search, workers):
    return RequestSession(CoachDependencies(ScriptedModel(), search, search_workers=workers), Budget(1, 2))


QUERIES = [SearchCorpusArgs(query=query, limit=3) for query, _ in CANDIDATES[:3]]


class ParallelFirstStageTests(unittest.TestCase):
    def test_only_complete_candidates_of_an_answerable_reply_with_its_show_first(self):
        whole = json.dumps(candidates(3, source_show="go_time"))
        cut = whole.index('"expression"', whole.index('"expression"') + 1) + 5  # inside the second candidate
        self.assertEqual(streamed_candidates(whole[:cut]), ("go_time", [candidates(3)["candidates"][0]]))
        self.assertEqual(streamed_candidates(whole)[1], candidates(3)["candidates"])
        self.assertEqual(streamed_candidates(json.dumps(candidates(3)))[0], None)
        self.assertEqual(streamed_candidates(json.dumps(candidates(3, request_status="out_of_scope"))), (None, []))
        self.assertEqual(streamed_candidates(whole[:whole.index('"source_show"')]), (None, []))

    def test_each_candidate_gets_its_own_selection_and_the_verified_ones_come_first(self):
        model = KeyedModel()
        (first, final), search = stream(model)
        self.assertEqual((type(first), type(final)), (First, Final))
        self.assertEqual([i.expression for i in first.expressions], [CANDIDATES[0][0], CANDIDATES[2][0]])
        self.assertTrue(first.pending)
        self.assertEqual(sorted(model.selections), [0, 1, 2])  # one call per candidate with spans
        self.assertEqual([s.stage for s in final.result.trace].count("select_1"), 3)
        self.assertEqual(sorted(search.queries[:3]), sorted(c[0] for c in CANDIDATES[:3]))
        validate = step(final.result, "validate_select_1")
        self.assertEqual((validate.details["verified"], validate.details["unfinished"]), (2, []))
        self.assertEqual(final.expressions[:2], first.expressions)  # D1: the sent examples stay

    def test_a_slow_selection_is_left_to_the_continuation_after_the_grace(self):
        started = time.monotonic()
        (first, final), _ = stream(KeyedModel(slow={2: 1.5}), FirstStageSettings(3, True, SpanView(3, 300), grace=0.05))
        self.assertLess(time.monotonic() - started, 1.2)  # did not wait for candidate 2
        self.assertEqual([i.expression for i in first.expressions], [CANDIDATES[0][0]])
        self.assertEqual(step(final.result, "validate_select_1").details["unfinished"], [2])
        self.assertEqual(final.expressions[0], first.expressions[0])

    def test_too_few_valid_candidates_are_asked_for_once_more(self):
        short = candidates(3)
        short["candidates"][1]["key_phrase"] = "not in the expression"
        (first, final), _ = stream(KeyedModel(replies=[short]))
        self.assertIn("candidates_retry", [s.stage for s in final.result.trace])
        self.assertEqual(len(first.expressions), 2)

    def test_a_listening_thread_gets_the_text_so_far_and_the_same_completion(self):
        final = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text='{"a": 1}')],
                                model="claude-haiku-5-5", usage=SimpleNamespace(input_tokens=3, output_tokens=2))
        events, calls = SimpleNamespace(text_stream=iter(['{"a"', ': 1}']), get_final_message=lambda: final), []
        client = SimpleNamespace(messages=SimpleNamespace(
            stream=lambda **request: calls.append("stream") or nullcontext(events),
            create=lambda **request: calls.append("create") or final))
        model = AnthropicChatModel(Settings.from_values(CLAUDE_ENV), client=client)
        heard = []
        with listening(heard.append):
            streamed = model.complete_with_usage(system_prompt="p", user_payload="{}")
        plain = model.complete_with_usage(system_prompt="p", user_payload="{}")
        self.assertEqual(heard, ['{"a"', '{"a": 1}'])
        self.assertEqual(calls, ["stream", "create"])  # not listening: one call as before
        self.assertEqual((streamed.content, plain.content), ('{"a": 1}', '{"a": 1}'))


class ParallelSearchTests(unittest.TestCase):
    def test_parallel_runs_give_the_sequential_answer_and_trace(self):
        sequential_search, parallel_search = KeyedSearch(), KeyedSearch()
        sequential, parallel = answer(1, sequential_search), answer(6, parallel_search)
        self.assertEqual((sequential.status, len(sequential.expressions)), ("ok", 3))
        self.assertTrue(all(item.citation for item in sequential.expressions))
        self.assertEqual([span.stage for span in parallel.trace],
                         [*PREFIX_STAGES, "revise_1", "search_1_1", "search_1_2", "select_2", "validate_select_2",
                          "assemble"])
        self.assertEqual(comparable(parallel), comparable(sequential))
        self.assertEqual(sorted(parallel_search.queries), sorted(sequential_search.queries))
        self.assertEqual((sequential_search.peak, parallel_search.peak), (1, 6))
        self.assertTrue(overlaps(parallel, "search_1", "search_6"))  # the first stage's six at once
        self.assertFalse(overlaps(parallel, "search_1_1", "search_1_2"))  # the baseline still searches one by one
        self.assertFalse(overlaps(sequential, "search_1", "search_2"))

    def test_a_failed_search_ends_the_request_at_the_same_step(self):
        sequential_search = KeyedSearch(fail={CANDIDATES[2][0]})
        sequential, parallel = answer(1, sequential_search), answer(6, KeyedSearch(fail={CANDIDATES[2][0]}))
        self.assertEqual((parallel.status, parallel.error_code), ("error", "storage_unavailable"))
        self.assertEqual([span.stage for span in parallel.trace], ["candidates", "search_1", "search_2", "search_3"])
        self.assertEqual(comparable(parallel), comparable(sequential))
        self.assertEqual(len(sequential_search.queries), 3)  # one after another: nothing after the failure runs

    def test_prefetching_stays_within_the_budget_and_prepares_once_and_a_failed_prepare_changes_nothing(self):
        for workers, error in ((1, None), (3, RuntimeError("embedding provider down"))):
            search = KeyedSearch(delay=0, prepare_error=error)
            session = session_for(search, workers)
            with self.subTest(workers=workers, error=error is not None), session.prefetching(QUERIES):
                if workers == 1:
                    self.assertEqual(search.queries, [])  # one worker never searches ahead
                self.assertEqual([len(session.search(args, policy="p").hits) for args in QUERIES[:2]], [1, 1])
                with self.assertRaises(CoachError) as spent:
                    session.search(QUERIES[2], policy="p")
            self.assertEqual(spent.exception.code, "search_budget_exhausted")
            self.assertEqual(sorted(search.queries), sorted(q.query for q in QUERIES[:2]))  # no more than the budget
            self.assertEqual([span.stage for span in session.trace], ["search_1", "search_2"])
            self.assertEqual(search.prepared, [[q.query for q in QUERIES[:2]]])  # within the budget, once
            with session.prefetching(QUERIES[:1]):  # one search: nothing to batch
                pass
            self.assertEqual(len(search.prepared), 1)

    def test_started_ms_counts_from_the_request_start_across_the_carried_prefix(self):
        clock = FakeClock()
        deps = CoachDependencies(ScriptedModel(), ScriptedSearch(), clock=clock)
        prefix = RequestSession(deps, Budget(1, 1))
        prefix.record("first")
        clock.now += 0.25
        prefix.record("second")
        carried = prefix.snapshot(shared=True)
        clock.now += 5  # time spent before the continuation started is not part of the request's timeline
        later = RequestSession(deps, Budget(1, 1), prefix=carried)
        clock.now += 0.5
        later.record("third")
        result = later.result("baseline", "ok", expressions=[])
        self.assertEqual([span.details["started_ms"] for span in result.trace], [0.0, 250.0, 750.0])

    def test_prefetched_embeddings_serve_each_query_and_report_the_batch_s_tokens_once(self):
        provider = FixedEmbeddings()
        embeddings = PrefetchedEmbeddings(provider)
        embeddings.prefetch(["a", "b", "a"])
        self.assertEqual(provider.calls, 1)
        served = [embeddings.embed_texts((text,)) for text in ("b", "a", "a")]
        self.assertEqual(provider.calls, 1)  # all three from the one batch
        self.assertEqual([batch.input_tokens for batch in served], [0, 2, 0])  # the batch's 2 tokens, once
        self.assertEqual((served[0].model, served[0].dimensions, len(served[0].vectors)),
                         (provider.model, provider.dimensions, 1))
        embeddings.embed_texts(("c",))
        embeddings.embed_texts(("a", "b"))
        self.assertEqual(provider.calls, 3)  # not prefetched, or several at once: the provider as before
        with self.assertRaises(RuntimeError):
            PrefetchedEmbeddings(FixedEmbeddings(RuntimeError("down"))).prefetch(["a", "b"])

    def test_search_workers_are_bounded(self):
        for workers in (0, 10, True):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                CoachDependencies(ScriptedModel(), ScriptedSearch(), search_workers=workers)


if __name__ == "__main__":
    unittest.main()
