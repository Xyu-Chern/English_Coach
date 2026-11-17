"""Scripted stand-ins for the chat model and the corpus search tool."""

import json
from copy import deepcopy
from uuid import UUID

from translation_agent_demo.agents.contracts import (ChatCompletion, CorpusSearchHit, ModelUsage,
                                                     SearchCorpusResult)


class FakeClock:
    """A clock that only moves when a fake call moves it."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ScriptedModel:
    """Returns the given replies in order and records every (system prompt, payload) it receives.

    With a clock, every call takes one second of it."""

    def __init__(self, *replies, usage=ModelUsage(10, 5, 0), clock=None):
        self.replies, self.prompts, self.formats, self.usage, self.clock = list(replies), [], [], usage, clock

    def complete_with_usage(self, *, system_prompt, user_payload, response_format=None):
        self.prompts.append((system_prompt, json.loads(user_payload)))
        self.formats.append(response_format)
        if self.clock:
            self.clock.now += 1.0
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatCompletion(reply if isinstance(reply, str) else json.dumps(deepcopy(reply)),
                              usage=self.usage, model="fixture-chat")


class ScriptedSearch:
    """Returns the given results in order and records every argument it receives."""

    def __init__(self, *results):
        self.results, self.args = list(results), []

    def __call__(self, args):
        self.args.append(args)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_hit(number=1, text="Before we finish, let me make one thing clear.", feed_id=1):
    return CorpusSearchHit(
        chunk_id=UUID(int=number), document_id=UUID(int=101), build_id=UUID(int=201),
        source_key=f"podcast_index:{feed_id}:1", feed_id=feed_id, episode_id=1, episode_title="Authored test fixture",
        episode_url="https://example.test/episode", transcript_url="https://example.test/transcript",
        language="en", text=text, similarity=0.4, start_ms=0, end_ms=10000,
        speakers=(), spans=(), rights_status="approved", rights_review_url=None,
        license_id="test-fixture", license_url=None, attribution="Authored test content",
    )


def search_result(*hits, status="ok", corpus_count=None):
    return SearchCorpusResult(status=status, model="fixture-embedding", dimensions=2,
                              processing_version="fixture-v1", input_tokens=4 if status == "ok" else 0, hits=hits,
                              literal_corpus_count=corpus_count)
