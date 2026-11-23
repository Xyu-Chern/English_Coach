"""What every reply model shares: item-by-item validation of its lists, and the key phrase rule."""

import json
from typing import ClassVar, get_args

from annotated_types import MaxLen

from ..evidence import key_phrase_contiguous
from ..results import FrozenModel
from ..structured import keep_valid


def _require_contiguous(key_phrase: str | None, expression: str | None) -> None:
    if key_phrase is not None and not key_phrase_contiguous(key_phrase, expression or ""):
        raise ValueError("key_phrase_not_contiguous")


class ItemListReply(FrozenModel):
    """A reply whose list items are validated one at a time (each list named in items_fields)."""

    items_fields: ClassVar[tuple[str, ...]]

    @classmethod
    def parse_items(cls, data: dict):
        lists, dropped = {}, []
        for name in cls.items_fields:
            field = cls.model_fields[name]
            item = field.annotation.__args__[0]  # tuple[Item, ...]
            limit = next((m.max_length for m in field.metadata if isinstance(m, MaxLen)), None)
            lists[name], lost = keep_valid(data.get(name), get_args(item) or (item,), limit)
            dropped += [{"list": name, **entry} for entry in lost]
        return cls.model_validate_json(json.dumps({**data, **lists})), dropped
