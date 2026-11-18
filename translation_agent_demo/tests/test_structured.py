"""Strict JSON Schemas built from the reply models, and item-by-item validation."""

import json
import unittest

from translation_agent_demo.agents.schemas.agent import AgentDecision, FinalPick
from translation_agent_demo.agents.schemas.baseline import Revision
from translation_agent_demo.agents.schemas.prefix import CandidateSet, Selection
from translation_agent_demo.agents.structured import parse_reply, response_format, strict_schema

REPLIES = (CandidateSet, Selection, Revision, AgentDecision, FinalPick)


def nodes(schema):
    """Every schema node (not property names)."""
    yield schema
    for key, value in schema.items():
        children = value.values() if key in ("properties", "$defs") else value if isinstance(value, list) else [value]
        for child in children:
            if isinstance(child, dict):
                yield from nodes(child)


class StrictSchemaTests(unittest.TestCase):
    def test_every_object_is_closed_and_fully_required_without_unsupported_keywords(self):
        for model in REPLIES:
            schema = strict_schema(model)
            self.assertEqual(schema["type"], "object")  # the root may not be anyOf
            for node in nodes(schema):
                self.assertFalse({"minLength", "maxLength", "default", "title"} & set(node), model.__name__)
                if "properties" in node:
                    self.assertEqual(node["required"], list(node["properties"]))
                    self.assertIs(node["additionalProperties"], False)

    def test_list_sizes_enums_and_union_branches_are_kept(self):
        revision = strict_schema(Revision)
        self.assertEqual(revision["properties"]["replacements"]["maxItems"], 3)
        for reply, kinds in ((AgentDecision, {"search", "repick", "replace"}), (FinalPick, {"repick", "replace"})):
            schema = strict_schema(reply)
            self.assertEqual(len(schema["properties"]["actions"]["items"]["anyOf"]), len(kinds))
            self.assertEqual({node["const"] for node in nodes(schema) if "const" in node}, kinds)
            self.assertTrue(all(list(d["properties"])[0] == "type" for d in schema["$defs"].values()))
        self.assertEqual(response_format(Selection)["json_schema"]["strict"], True)


class ItemValidationTests(unittest.TestCase):
    def test_an_invalid_item_is_dropped_and_the_rest_kept(self):
        good = {"candidate": 0, "ref": "c0h1s1", "expression": "E k", "key_phrase": "k", "reusable_wording": "w",
                "source_use": "s", "adaptation": "a"}
        too_long = {**good, "candidate": 1, "reusable_wording": "x" * 201}
        selection, dropped = parse_reply(Selection, json.dumps({"picks": [good, too_long]}))
        self.assertEqual([p.candidate for p in selection.picks], [0])
        self.assertEqual(dropped, [{"list": "picks", "index": 1, "field": "reusable_wording",
                                    "error": "string_too_long", "slot": 1}])

    def test_actions_are_validated_by_their_own_kind(self):
        search = {"type": "search", "slot": None, "query": "q", "key_phrase": None, "reason": "r"}
        repick = {"type": "repick", "slot": 0, "ref": "c0h1s1", "reusable_wording": "x" * 201, "source_use": "s",
                  "adaptation": "a", "reason": "r"}
        reply = {"assessment": "a", "actions": [search, repick, {**search, "type": "ask_user"}], "finish": False}
        decision, dropped = parse_reply(AgentDecision, json.dumps(reply))
        self.assertEqual([action.type for action in decision.actions], ["search"])
        self.assertEqual(dropped, [{"list": "actions", "index": 1, "field": "reusable_wording",
                                    "error": "string_too_long", "slot": 0},
                                   {"list": "actions", "index": 2, "field": "type", "error": "unknown_type",
                                    "slot": None}])

    def test_items_past_the_list_maximum_are_dropped_not_fatal(self):
        """Claude does not enforce maxItems, so a 7th action must not cost the whole turn."""
        search = {"type": "search", "slot": 0, "query": "q", "key_phrase": None, "reason": "r"}
        reply = {"assessment": "a", "actions": [{**search, "query": f"q{i}"} for i in range(8)], "finish": False}
        decision, dropped = parse_reply(AgentDecision, json.dumps(reply))
        self.assertEqual([action.query for action in decision.actions], [f"q{i}" for i in range(6)])
        self.assertEqual(dropped, [{"list": "actions", "index": i, "field": "items", "error": "too_many_items",
                                    "slot": 0} for i in (6, 7)])

    def test_a_gapped_or_absent_key_phrase_drops_the_item(self):
        """A key phrase is one contiguous piece of its expression, in every reply that names one."""
        candidate = {"expression": "Let's treat it as a draft.", "key_phrase": "treat it as", "function": "f",
                     "note": "n"}
        reply = {"request_status": "answerable", "status_note": None, "kind": "function", "source_show": None,
                 "candidates": [candidate, {**candidate, "key_phrase": "treat ... as"},
                                {**candidate, "key_phrase": "regard as"}]}
        generated, dropped = parse_reply(CandidateSet, json.dumps(reply))
        self.assertEqual([c.key_phrase for c in generated.candidates], ["treat it as"])
        self.assertEqual([(d["index"], d["error"]) for d in dropped],
                         [(1, "key_phrase_not_contiguous"), (2, "key_phrase_not_contiguous")])

    def test_a_hyphen_or_dash_does_not_break_contiguity(self):
        candidate = {"expression": "It's a real trade off.", "key_phrase": "trade-off", "function": "f", "note": "n"}
        reply = {"request_status": "answerable", "status_note": None, "kind": "function", "source_show": None,
                 "candidates": [candidate, {**candidate, "expression": "Stop playing whack-a-mole.",
                                            "key_phrase": "whack a mole"}]}
        self.assertEqual(len(parse_reply(CandidateSet, json.dumps(reply))[0].candidates), 2)

    def test_a_repick_variant_needs_both_fields(self):
        repick = {"type": "repick", "slot": 0, "ref": "c0h1s1", "reusable_wording": "w", "source_use": "s",
                  "adaptation": "a", "reason": "r"}
        variant = {**repick, "expression": "Hold off for now.", "key_phrase": "hold off"}
        reply = {"assessment": "a", "actions": [variant, {**variant, "key_phrase": None}], "finish": False}
        decision, dropped = parse_reply(AgentDecision, json.dumps(reply))
        self.assertEqual([a.expression for a in decision.actions], ["Hold off for now."])
        self.assertEqual([d["error"] for d in dropped], ["variant_incomplete"])


class ShapeTests(unittest.TestCase):
    def test_shape_errors_outside_items_still_fail(self):
        with self.assertRaises(ValueError):
            parse_reply(Selection, json.dumps({"picks": [], "extra": 1}))


if __name__ == "__main__":
    unittest.main()
