"""The JSON each prompt must return.

The provider decodes against these models' strict JSON Schema (structured.py), so keys,
enums and union branches are guaranteed. Pydantic then checks what a provider may not
(string lengths; list sizes on Claude). Replies with lists validate each item on its own:
an invalid item, or one past the list's maximum, is dropped and reported instead of
rejecting the whole reply.

A key phrase must be one contiguous piece of its expression: it drives the literal search
and the verifier's coverage check, and a gapped one like "treat ... as" finds nothing. An
item whose key phrase is not is dropped like any other invalid item.

Free text (assessment, reason) is not length-checked, so an over-long explanation never costs
an action. Code reads reason only to tell whether a change was for a meaning problem
(agents/systems/agent.py, MEANING_REASON).

A reply model's docstring becomes the description in its JSON Schema, which the provider
receives with every call: those docstrings are part of what the model reads, like the prompts
(tests/test_frozen.py pins both).

    base.py       ItemListReply (lists validated item by item) and the key phrase rule
    prefix.py     CandidateSet, Selection: the first stage's replies
    baseline.py   Revision: the baseline's reply
    agent.py      AgentDecision, FinalPick: the agent's replies; their actions are the tools'
                  argument models (tools/search.py, tools/change.py)

Import each model from its module (e.g. schemas.prefix.CandidateSet): this package re-exports
nothing, so the tools can define their action models without an import cycle.
"""
