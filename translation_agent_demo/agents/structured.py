"""Structured outputs: the provider decodes against the same Pydantic models the code validates.

Strict decoding accepts only a subset of JSON Schema: every object closed and every property
required, no string lengths, defaults or titles. Pydantic's own schema has all of those, so
strict_schema rewrites it, and response_format wraps it in the OpenAI shape that every call
passes to its chat model (session.ask). OpenAI receives it as response_format; the Claude
adapter (providers/anthropic_chat.py) sends the same schema as output_config.format, through
anthropic.transform_schema. The provider then guarantees the shape: every key present, no
unknown keys, enum values only, the right branch of a union. OpenAI's strict mode also
enforces list sizes; Claude's does not (the SDK moves maxItems into a description).

Checks that remain for code after decoding, because not every provider can express them:
- string lengths (stripped from the schema for strict mode),
- list sizes: items past a list's maximum are dropped and reported, and
- anything else a model can still get wrong inside a list item.
A reply with list items is therefore validated item by item: an invalid or surplus item
is dropped and reported, the rest of the reply is kept, so one provider's looser decoding
cannot fail a whole step. A list of several item kinds (a union) is told apart by each
item's "type" field, so a dropped item reports its own kind's error. A dropped item also
names the slot it was for (its "slot", "replaces" or "candidate"), so the next decision call
can be told what was lost (dropped_last_turn).
"""

import json
from typing import get_args

from pydantic import BaseModel, ValidationError

# Keywords strict mode rejects (string lengths) or does not need (annotations, defaults).
_STRIPPED = ("minLength", "maxLength", "default", "title")


def strict_schema(model: type[BaseModel]) -> dict:
    """The model's JSON Schema in the subset strict mode accepts: every object closed and fully required."""
    return _strict(model.model_json_schema())


def response_format(model: type[BaseModel]) -> dict:
    return {"type": "json_schema", "json_schema": {"name": model.__name__, "strict": True,
                                                   "schema": strict_schema(model)}}


def keep_valid(items, item_models: tuple[type[BaseModel], ...],
               limit: int | None = None) -> tuple[list[dict], list[dict]]:
    """Validate list items one by one; returns the valid ones (as JSON data) and why others were dropped.

    With several item models, each item is validated by the one whose "type" it names. Once
    limit items are kept, the rest are dropped as too_many_items: the first ones are the
    model's own priority, and a provider that does not enforce maxItems must not fail the reply."""
    kept, dropped = [], []
    for index, item in enumerate(items if isinstance(items, list) else []):
        slot = {"slot": _slot_of(item)}
        if limit is not None and len(kept) >= limit:
            dropped.append({"index": index, "field": "items", "error": "too_many_items", **slot})
            continue
        model = _model_for(item, item_models)
        if model is None:
            dropped.append({"index": index, "field": "type", "error": "unknown_type", **slot})
            continue
        problem = validation_error(model, item)
        if problem:
            dropped.append({"index": index, **problem, **slot})
        else:
            kept.append(model.model_validate_json(json.dumps(item)).model_dump(mode="json"))
    return kept, dropped


def validation_error(model: type[BaseModel], data) -> dict | None:
    """The first reason data fails the model, as {field, error}; None when it is valid.

    A validator's ValueError names its own code (for example key_phrase_not_contiguous)."""
    try:
        model.model_validate_json(json.dumps(data))
    except ValidationError as exc:
        error = exc.errors()[0]
        code = str(error.get("ctx", {}).get("error", "")) if error["type"] == "value_error" else ""
        return {"field": ".".join(str(part) for part in error["loc"]), "error": code or error["type"]}
    return None


def drop_reason(dropped: dict) -> str:
    """One dropped item as the next decision call reads it: field:error, or the error alone."""
    return f"{dropped['field']}:{dropped['error']}" if dropped.get("field") else dropped["error"]


def parse_reply(model: type[BaseModel], content: str):
    """(validated reply, dropped items). Models with list items validate them one by one."""
    tolerant = getattr(model, "parse_items", None)
    if tolerant is None:
        return model.model_validate_json(content), []
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("The reply must be a JSON object.")
    return tolerant(data)


def _slot_of(item) -> int | None:
    if not isinstance(item, dict):
        return None
    slot = next((item[key] for key in ("slot", "replaces", "candidate") if key in item), None)
    return slot if type(slot) is int else None


def _model_for(item, models: tuple[type[BaseModel], ...]) -> type[BaseModel] | None:
    if len(models) == 1:
        return models[0]
    kind = item.get("type") if isinstance(item, dict) else None
    return next((m for m in models if kind in get_args(m.model_fields["type"].annotation)), None)


def _strict(node):
    """Recurse through schema nodes; property and definition names are kept as they are."""
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key in ("properties", "$defs"):
            result[key] = {name: _strict(schema) for name, schema in value.items()}
        elif key not in _STRIPPED:
            result[key] = _strict(value)
    if "properties" in result:
        result["required"] = list(result["properties"])
        result["additionalProperties"] = False
    return result
