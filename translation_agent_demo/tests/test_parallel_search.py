"""Parallel searches (search_workers > 1): the same answer, trace and budgets as one after another, sooner."""

import threading
import time
import unittest

from translation_agent_demo.agents import Budget, CoachDependencies, CoachError, ExpressionCoach, RequestSession
from translation_agent_demo.agents.contracts import SearchCorpusArgs, SearchCorpusError
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel, ScriptedSearch, make_hit, search_result
from translation_agent_demo.tests.test_pipelines import (CANDIDATES, PREFIX_STAGES, QUESTION, TEXTS, candidates, pick,
                                                         replacement, revision)

NEW = {"Let's circle back to it.": "We can circle back to it next week.",
       "Let's shelve it for now.": "Let's shelve it for now and keep going."}
# The first stage verifies nothing; revise_1 adopts one replacement by its ref (no search) and
# searches for two others; select_2 verifies both, so the baseline stops after one round.
REPLIES = (candidates(), {"picks": []},
           revision(replacement(0, "Let's put a pin in it.", "put a pin in", ref="c5h1s1", wording="Let's put a pin in it"),
                    replacement(1, "Let's circle back to it.", "circle back"),
                    replacement(2, "Let's shelve it for now.", "shelve it")),
           {"picks": [pick(1, "r1k1h1s1", "circle back to it", expression="Let's circle back to it."),
                      pick(2, "r1k2h1s1", "shelve it for now", expression="Let's shelve it for now.")]})


class KeyedSearch:
    """Safe to call from many threads: each query has a fixed passage (or fails); each call takes a little while."""

    def __init__(self, delay=0.05, fail=()):
        self.passages = {**{expression: text for (expression, _), text in zip(CANDIDATES, TEXTS)}, **NEW}
        self.numbers = {query: n for n, query in enumerate(self.passages, 1)}
        self.delay, self.fail, self.lock = delay, set(fail), threading.Lock()
        self.queries, self.running, self.peak = [], 0, 0

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


def run(workers, search):
    deps = CoachDependencies(ScriptedModel(*REPLIES), search, search_workers=workers)
    return ExpressionCoach(deps, "baseline").answer(QUESTION)


def comparable(result):
    """The result without what timing or chance decides (ids, durations, start offsets)."""
    data = result.model_dump(mode="json")
    del data["request_id"], data["elapsed_ms"]
    for span in data["trace"]:
        del span["elapsed_ms"], span["details"]["started_ms"]
    return data


def overlaps(result, first, second):
    spans = {span.stage: span for span in result.trace}
    a, b = spans[first], spans[second]
    return b.details["started_ms"] < a.details["started_ms"] + a.elapsed_ms


class ParallelSearchTests(unittest.TestCase):
    def test_parallel_runs_give_the_sequential_answer_and_trace(self):
        sequential_search, parallel_search = KeyedSearch(), KeyedSearch()
        sequential, parallel = run(1, sequential_search), run(6, parallel_search)
        self.assertEqual((sequential.status, len(sequential.expressions)), ("ok", 3))
        self.assertTrue(all(item.citation for item in sequential.expressions))
        self.assertEqual([span.stage for span in parallel.trace],
                         [*PREFIX_STAGES, "revise_1", "search_1_1", "search_1_2", "select_2", "validate_select_2",
                          "assemble"])
        self.assertEqual(comparable(parallel), comparable(sequential))
        self.assertEqual(sorted(parallel_search.queries), sorted(sequential_search.queries))
        self.assertEqual((sequential_search.peak, parallel_search.peak), (1, 6))
        self.assertTrue(overlaps(parallel, "search_1", "search_6"))  # the first stage's six at once
        self.assertTrue(overlaps(parallel, "search_1_1", "search_1_2"))  # and a baseline round's
        self.assertFalse(overlaps(sequential, "search_1", "search_2"))

    def test_a_failed_search_ends_the_request_at_the_same_step(self):
        sequential_search = KeyedSearch(fail={CANDIDATES[2][0]})
        sequential, parallel = run(1, sequential_search), run(6, KeyedSearch(fail={CANDIDATES[2][0]}))
        self.assertEqual((parallel.status, parallel.error_code), ("error", "storage_unavailable"))
        self.assertEqual([span.stage for span in parallel.trace], ["candidates", "search_1", "search_2", "search_3"])
        self.assertEqual(comparable(parallel), comparable(sequential))
        self.assertEqual(len(sequential_search.queries), 3)  # one after another: nothing after the failure runs

    def test_prefetching_starts_no_more_than_the_budget_allows(self):
        search = KeyedSearch()
        session = RequestSession(CoachDependencies(ScriptedModel(), search, search_workers=3), Budget(1, 2))
        queries = [SearchCorpusArgs(query=query, limit=3) for query, _ in CANDIDATES[:3]]
        with session.prefetching(queries):
            self.assertEqual([len(session.search(args, policy="p").hits) for args in queries[:2]], [1, 1])
            with self.assertRaises(CoachError) as spent:
                session.search(queries[2], policy="p")
        self.assertEqual(spent.exception.code, "search_budget_exhausted")
        self.assertEqual(sorted(search.queries), sorted(q.query for q in queries[:2]))
        self.assertEqual([span.stage for span in session.trace], ["search_1", "search_2"])

    def test_one_worker_never_searches_ahead(self):
        search = ScriptedSearch(search_result(make_hit(1)))
        session = RequestSession(CoachDependencies(ScriptedModel(), search), Budget(1, 2))
        with session.prefetching([SearchCorpusArgs(query="a", limit=1), SearchCorpusArgs(query="b", limit=1)]):
            self.assertEqual(search.args, [])

    def test_started_ms_counts_from_the_request_start_across_the_carried_prefix(self):
        clock = FakeClock()
        prefix = RequestSession(CoachDependencies(ScriptedModel(), ScriptedSearch(), clock=clock), Budget(1, 1))
        prefix.record("first")
        clock.now += 0.25
        prefix.record("second")
        carried = prefix.snapshot(shared=True)
        clock.now += 5  # time spent before the continuation started is not part of the request's timeline
        later = RequestSession(CoachDependencies(ScriptedModel(), ScriptedSearch(), clock=clock), Budget(1, 1),
                               prefix=carried)
        clock.now += 0.5
        later.record("third")
        result = later.result("baseline", "ok", expressions=[])
        self.assertEqual([span.details["started_ms"] for span in result.trace], [0.0, 250.0, 750.0])

    def test_search_workers_are_bounded(self):
        for workers in (0, 10, True):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                CoachDependencies(ScriptedModel(), ScriptedSearch(), search_workers=workers)


if __name__ == "__main__":
    unittest.main()
