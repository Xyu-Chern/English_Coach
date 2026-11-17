"""RequestSession: budgets, validated model replies, checked searches, usage, trace and the carried prefix."""

import unittest
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from translation_agent_demo.agents import Budget, CoachDependencies, CoachError, RequestSession
from translation_agent_demo.agents.contracts import SearchCorpusArgs, SearchCorpusError
from translation_agent_demo.agents.results import FrozenModel
from translation_agent_demo.agents.schemas.base import ItemListReply
from translation_agent_demo.tests.fakes import FakeClock, ScriptedModel, ScriptedSearch, make_hit, search_result


class Reply(FrozenModel):
    word: str = Field(max_length=10)


def session(model=None, search=None, calls=2, searches=1):
    return RequestSession(CoachDependencies(model or ScriptedModel(), search or ScriptedSearch()),
                          Budget(calls, searches))


class SessionTests(unittest.TestCase):
    def test_ask_validates_the_reply_and_counts_usage_within_budget(self):
        s = session(ScriptedModel({"word": "ok"}, {"word": "much too long here"}, {"word": "x"}))
        self.assertEqual(s.ask("one", "prompt", {"q": 1}, Reply).word, "ok")
        with self.assertRaises(CoachError) as invalid:
            s.ask("two", "prompt", {}, Reply)
        self.assertEqual(invalid.exception.code, "invalid_model_output")
        with self.assertRaises(CoachError) as spent:
            s.ask("three", "prompt", {}, Reply)
        self.assertEqual(spent.exception.code, "model_budget_exhausted")
        result = s.result("baseline", "error", error_code="invalid_model_output")
        self.assertEqual((result.model_rounds, result.usage.input_tokens, result.usage.total_chat_calls), (2, 20, 2))
        self.assertEqual([(t.stage, t.status) for t in result.trace], [("one", "ok"), ("two", "error")])

    def test_dropped_items_wait_for_the_next_decision_call(self):
        class Listed(ItemListReply):
            items_fields: ClassVar[tuple[str, ...]] = ("items",)
            items: tuple[Reply, ...] = Field(max_length=2)

        s = session(ScriptedModel({"items": [{"word": "ok"}, {"word": "much too long here", "slot": 1}]}))
        self.assertEqual(len(s.ask("revise_1", "p", {}, Listed).items), 1)
        self.assertEqual(s.trace[-1].details["dropped_items"][0]["field"], "word")
        self.assertEqual(s.take_dropped(), [{"step": "revise_1", "slot": 1, "reason": "word:string_too_long",
                                             "list": "items", "index": 1, "field": "word",
                                             "error": "string_too_long"}])
        self.assertEqual(s.take_dropped(), [])

    def test_provider_failure_is_a_stable_error(self):
        with self.assertRaises(CoachError) as failure:
            session(ScriptedModel(RuntimeError("down"))).ask("one", "p", {}, Reply)
        self.assertEqual(failure.exception.code, "model_unavailable")

    def test_search_checks_results_and_maps_tool_errors(self):
        args = SearchCorpusArgs(query="q", limit=1, feed_ids=[7])
        ok = session(search=ScriptedSearch(search_result(make_hit(1, feed_id=7))))
        self.assertEqual(ok.search(args, policy="p").hits[0].chunk_id, UUID(int=1))
        with self.assertRaises(CoachError) as spent:
            ok.search(args, policy="p")
        self.assertEqual(spent.exception.code, "search_budget_exhausted")
        for result, code in ((search_result(make_hit(1, feed_id=8)), "search_unavailable"),  # outside the show
                             (SearchCorpusError("storage_unavailable", "x"), "storage_unavailable"),
                             (search_result(status="not_ready"), "corpus_not_ready")):
            with self.subTest(code=code), self.assertRaises(CoachError) as failure:
                session(search=ScriptedSearch(result)).search(args, policy="p")
            self.assertEqual(failure.exception.code, code)

    def test_a_continuation_counts_the_carried_prefix_but_not_against_its_budget(self):
        clock = FakeClock()  # every model call takes one second

        def deps(reply, search=None):
            return CoachDependencies(ScriptedModel(reply, clock=clock), search or ScriptedSearch(), clock=clock)

        prefix = RequestSession(deps({"word": "a"}, ScriptedSearch(search_result(make_hit(1), corpus_count=7))),
                                Budget(1, 1))
        prefix.ask("candidates", "p", {}, Reply)
        found = prefix.search(SearchCorpusArgs(query="q", literal_phrase="one thing", limit=1), policy="p",
                              stage="search_1", slot=0)
        self.assertEqual(found.corpus_count, 7)
        carried = prefix.snapshot(shared=True)
        clock.now += 5  # time another system spent first is not charged to this one
        later = RequestSession(deps({"word": "b"}), Budget(1, 1), prefix=carried)
        later.ask("agent_1", "p", {}, Reply)
        self.assertEqual((later.model_calls_left, later.searches_left), (0, 1))
        result = later.result("agent", "ok", expressions=[])
        self.assertEqual([(t.stage, t.details.get("shared")) for t in result.trace],
                         [("candidates", True), ("search_1", True), ("agent_1", None)])
        self.assertEqual((result.model_rounds, len(result.tool_calls), result.usage.input_tokens,
                          result.usage.embedding_tokens, result.elapsed_ms), (2, 1, 20, 4, 2000.0))
        search = result.trace[1].details
        self.assertEqual((search["slot"], search["query"], search["key_phrase"], search["corpus_count"],
                          search["hits"][0]["snippet"]),
                         (0, "q", "one thing", 7, "Before we finish, let me make one thing clear."))

    def test_corpus_count_is_none_without_a_literal_phrase(self):
        s = session(search=ScriptedSearch(search_result(make_hit(1), corpus_count=3)))
        self.assertIsNone(s.search(SearchCorpusArgs(query="q", limit=1), policy="p").corpus_count)
        self.assertIsNone(s.trace[-1].details["corpus_count"])

    def test_budget_bounds(self):
        for calls, searches in ((0, 1), (7, 1), (1, 10)):
            with self.subTest(calls=calls, searches=searches), self.assertRaises(ValueError):
                Budget(calls, searches)


if __name__ == "__main__":
    unittest.main()
