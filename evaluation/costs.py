"""Dated list-price estimates from provider-reported usage, never invoices.

Every model call is priced by the model that served it (pricing.json "models"). Claude
Haiku 5.5 has a second, higher rate card for a call whose prompt is over 100K tokens, and
that is decided call by call, so a tiered model is never priced from summed usage.
Embeddings are priced separately.
"""

import math

_RATES = ("input", "cached_input", "output")


def estimate_calls(calls, pricing: dict | None, *, embedding_tokens: int | None = None,
                   include_embedding: bool = True) -> dict:
    """Price model calls shaped like RecordingModel events: {"model", "usage": {...}}.

    usage.input_tokens is the whole prompt, cached_input_tokens included (ModelUsage). An
    unknown cached count is priced as uncached, so the total is then an upper bound."""
    if not pricing:
        return {"usd": None, "status": "pricing_missing"}
    total, upper_bound = 0.0, False
    for call in calls:
        usage = call.get("usage") or {}
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
            return {"usd": None, "status": "usage_incomplete"}
        cached = usage.get("cached_input_tokens")
        upper_bound |= cached is None
        cached = 0 if cached is None else cached
        if type(cached) is not int or not 0 <= cached <= usage["input_tokens"]:
            return {"usd": None, "status": "usage_invalid"}
        card = _card(pricing, call.get("model"), usage["input_tokens"])
        if card is None:
            return {"usd": None, "status": "pricing_missing", "model": call.get("model")}
        total += ((usage["input_tokens"] - cached) * card["input"] + cached * card["cached_input"]
                  + usage["output_tokens"] * card["output"])
    if include_embedding:
        if type(embedding_tokens) is not int or embedding_tokens < 0:
            return {"usd": None, "status": "usage_incomplete"}
        total += embedding_tokens * _rate(pricing.get("embedding") or {}, "usd_per_million")
    return {"usd": total / 1_000_000, "status": "uncached_upper_bound" if upper_bound else "list_price_estimate",
            "pricing_as_of": pricing.get("as_of"), "currency": "USD"}


def estimate(usage: dict, pricing: dict | None, *, model: str | None = None, include_embedding: bool = True) -> dict:
    """Summed usage of calls that one model served (for example all judge votes).

    Refused for a model with a prompt-length tier: only per-call usage can say which card applies."""
    if not pricing:
        return {"usd": None, "status": "pricing_missing"}
    if model is None:
        return {"usd": None, "status": "model_unspecified"}
    if "long_prompt" in ((pricing.get("models") or {}).get(model) or {}):
        return {"usd": None, "status": "per_call_usage_required"}
    return estimate_calls([{"model": model, "usage": usage}], pricing,
                          embedding_tokens=usage.get("embedding_tokens"), include_embedding=include_embedding)


def _card(pricing: dict, model: str | None, prompt_tokens: int) -> dict | None:
    """The model's rates for one call; the long-prompt card applies above its threshold."""
    card = (pricing.get("models") or {}).get(model)
    if card is None:
        return None
    long_prompt = card.get("long_prompt")
    if long_prompt and prompt_tokens > long_prompt["above_input_tokens"]:
        card = long_prompt
    return {key: _rate(card, key) for key in _RATES}


def _rate(card: dict, key: str) -> float:
    value = card.get(key)
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Pricing needs finite nonnegative rates.")
    return value
