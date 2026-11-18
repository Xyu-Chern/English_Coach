import json
import math
import unittest
from pathlib import Path

from evaluation.costs import estimate, estimate_calls

PRICING_FILE = Path(__file__).resolve().parents[1] / "data" / "pricing.json"

PRICING = {"as_of": "2026-11-16", "models": {
    "gpt": {"input": .75, "cached_input": .075, "output": 4.5},
    "haiku": {"input": .10, "cached_input": .01, "output": .50,
              "long_prompt": {"above_input_tokens": 100_000, "input": .50, "cached_input": .05, "output": 2.50}},
    "sonnet": {"input": 2, "cached_input": .10, "output": 10}},
    "embedding": {"model": "text-embedding-3-small", "usd_per_million": .02}}


def call(model: str, input_tokens: int, output_tokens: int, cached: int | None = 0) -> dict:
    return {"model": model, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                                      "cached_input_tokens": cached}}


class CostTests(unittest.TestCase):
    def test_cached_tokens_are_not_billed_twice_and_embedding_is_separate(self):
        usage = {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 100, "embedding_tokens": 50}
        self.assertAlmostEqual(estimate(usage, PRICING, model="gpt")["usd"], .000931)
        self.assertAlmostEqual(estimate(usage, PRICING, model="gpt", include_embedding=False)["usd"], .000930)

    def test_each_call_is_priced_by_the_model_that_served_it(self):
        calls = [call("haiku", 10_000, 1_000), call("sonnet", 10_000, 1_000, cached=5_000)]
        cost = estimate_calls(calls, PRICING, embedding_tokens=100)
        self.assertAlmostEqual(cost["usd"], (10_000 * .10 + 1_000 * .50 + 5_000 * 2 + 5_000 * .10 + 1_000 * 10
                                             + 100 * .02) / 1e6)
        self.assertEqual(cost["status"], "list_price_estimate")

    def test_haiku_long_prompt_card_is_chosen_per_call_never_from_summed_usage(self):
        short_calls = [call("haiku", 60_000, 1_000), call("haiku", 60_000, 1_000)]
        self.assertAlmostEqual(estimate_calls(short_calls, PRICING, include_embedding=False)["usd"],
                               2 * (60_000 * .10 + 1_000 * .50) / 1e6)
        long_call = [call("haiku", 100_001, 1_000, cached=1)]
        self.assertAlmostEqual(estimate_calls(long_call, PRICING, include_embedding=False)["usd"],
                               (100_000 * .50 + 1 * .05 + 1_000 * 2.50) / 1e6)
        summed = {"input_tokens": 120_000, "output_tokens": 2_000, "cached_input_tokens": 0}
        self.assertEqual(estimate(summed, PRICING, model="haiku", include_embedding=False)["status"],
                         "per_call_usage_required")

    def test_unknown_usage_model_or_cache_stays_explicit(self):
        usage = {"input_tokens": 10, "output_tokens": 5, "embedding_tokens": 0}
        self.assertEqual(estimate(usage, PRICING, model="gpt")["status"], "uncached_upper_bound")
        self.assertIsNone(estimate({"input_tokens": 10}, PRICING, model="gpt")["usd"])
        self.assertEqual(estimate(usage | {"cached_input_tokens": 11}, PRICING, model="gpt")["status"], "usage_invalid")
        self.assertEqual(estimate(usage, PRICING)["status"], "model_unspecified")
        self.assertEqual(estimate(usage, None, model="gpt")["status"], "pricing_missing")
        self.assertEqual(estimate_calls([call("other", 1, 1)], PRICING, include_embedding=False)["status"],
                         "pricing_missing")
        self.assertEqual(estimate_calls([{"model": "gpt", "usage": None}], PRICING)["status"], "usage_incomplete")
        self.assertEqual(estimate_calls([], PRICING)["status"], "usage_incomplete")  # embedding count unknown

    def test_published_pricing_covers_every_model_used_with_sources(self):
        pricing = json.loads(PRICING_FILE.read_text())
        models = {"gpt-5.4-mini-2026-03-17", "claude-haiku-5-5", "claude-sonnet-5-5"}
        self.assertEqual(set(pricing["models"]), models)
        self.assertEqual(set(pricing["sources"]), models | {pricing["embedding"]["model"]})
        self.assertTrue(pricing["as_of"])
        for model in models:
            cost = estimate_calls([call(model, 200_000, 1_000)], pricing, embedding_tokens=1_000)
            self.assertTrue(math.isfinite(cost["usd"]) and cost["usd"] > 0, model)
        self.assertEqual(pricing["models"]["claude-haiku-5-5"]["long_prompt"]["above_input_tokens"], 100_000)


if __name__ == "__main__":
    unittest.main()
