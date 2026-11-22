"""What the model receives is pinned: the five prompts and the five reply schemas.

A change to a prompt, or to a reply schema (its fields, constraints or docstrings, which become
schema descriptions), changes what both systems send to the model. These hashes make such a
change deliberate: update them together with a note on what changed and why.

AGENT_PROMPT is still the submitted evaluation's agent prompt (AgentPipeline(locked=False)).
AGENT_LOCKED_PROMPT (2026-11-21, the verified-slot lock D1) is AGENT_PROMPT with one paragraph
added after the guard paragraph: locked slots are final, and actions naming them are noops.
2026-11-22: the paragraph now matches D1 exactly. Only a repick or replace naming a locked slot is
a noop (named "locked"); a search naming one still runs and spends a search.
"""

import hashlib
import json
import unittest

from translation_agent_demo.agents.prompts import (AGENT_LOCKED_PROMPT, AGENT_PROMPT, CANDIDATES_PROMPT, REVISE_PROMPT,
                                                   SELECT_PROMPT)
from translation_agent_demo.agents.schemas.agent import AgentDecision, FinalPick
from translation_agent_demo.agents.schemas.baseline import Revision
from translation_agent_demo.agents.schemas.prefix import CandidateSet, Selection
from translation_agent_demo.agents.structured import strict_schema

PROMPTS = {
    "CANDIDATES_PROMPT": (CANDIDATES_PROMPT, "f845f066db0646082abaa763e4f498d3202c4187d3f08d7c084bd094e78e8fc8"),
    "SELECT_PROMPT": (SELECT_PROMPT, "fe211d6522da4424bcd14831c0ce0b0878b4e2e1a52f8cb4289b1ec36e420f27"),
    "REVISE_PROMPT": (REVISE_PROMPT, "1afe23636138ebe291a7364c89c4e119c5ea141aa8491c67e9a31ee80d899f4b"),
    "AGENT_PROMPT": (AGENT_PROMPT, "951e2e5fda16636f0db78965b6c44111baf851f8fe8d55edfe065ddb69e89f98"),
    "AGENT_LOCKED_PROMPT": (AGENT_LOCKED_PROMPT,
                            "69fb0ffbdfd357d191c159e11be573eeb5ea9845e3847eac2c25e20f9eab16c0"),
}
REPLIES = {
    CandidateSet: "ac8d55f4bcb2a37b94138e1c3f4c9e039f9b51f3125efa0a4c5503686a665ec2",
    Selection: "efc6bcbb213ce67a57065cc9275f33d80898ef1598e273d774a106c83eac3083",
    Revision: "033c18f4e7024475ab0f5e125cbe63d9315cd17a316159d99ced16127eb9a0a2",
    AgentDecision: "c0aca1db5c1c0ada0a113b1cb664374f3b38a8b5818e7397ee65b06472d97ddf",
    FinalPick: "2ea7317bb0c57f23059e5dfdaa84cae3a9a00ddf592122eceaf6bd82f27a171e",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FrozenTests(unittest.TestCase):
    def test_prompts_are_the_ones_the_runs_used(self):
        for name, (text, expected) in PROMPTS.items():
            with self.subTest(prompt=name):
                self.assertEqual(sha(text), expected)

    def test_reply_schemas_are_the_ones_the_runs_used(self):
        for model, expected in REPLIES.items():
            with self.subTest(reply=model.__name__):
                self.assertEqual(sha(json.dumps(strict_schema(model), sort_keys=True)), expected)


if __name__ == "__main__":
    unittest.main()
