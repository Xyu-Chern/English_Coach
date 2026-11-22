"""The prompts the expression coach sends, in the order a request uses them.

Each prompt is the system message of one step; the learner's message and retrieved
passages always travel separately as JSON in the user message and are treated as
untrusted data. Every reply is decoded against a strict JSON Schema built from the
Pydantic models in schemas.py (structured outputs), so the JSON shapes written below are
guaranteed; the prose states the limits the schema cannot express (string lengths).
The prompts hold no wording, idiom or situation from the evaluation tasks: rules are
stated in general terms, so a score cannot come from text the prompt already contains.

    prefix.py     CANDIDATES_PROMPT, SELECT_PROMPT (the shared first stage; SELECT also in baseline rounds)
    baseline.py   REVISE_PROMPT: one fixed revision per round
    agent.py      AGENT_LOCKED_PROMPT (the default agent, verified-slot lock) and AGENT_PROMPT
                  (the submission agent, locked=False): every turn, and the pick-only final call
    shared.py     paragraphs both systems' prompts use word for word

tests/test_frozen.py pins every prompt, so a change to what the model reads is always deliberate.
"""


from .agent import AGENT_LOCKED_PROMPT, AGENT_PROMPT
from .baseline import REVISE_PROMPT
from .prefix import CANDIDATES_PROMPT, SELECT_PROMPT

__all__ = ["CANDIDATES_PROMPT", "SELECT_PROMPT", "REVISE_PROMPT", "AGENT_PROMPT", "AGENT_LOCKED_PROMPT"]
