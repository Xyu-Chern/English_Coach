# English Coach evaluation

The Chinese and Korean cohorts contain 50 questions each. Each system attempted every question three times, giving 600 recorded attempts across both cohorts.

[Open the comparison](index.html) · [Chinese replay](zh.html) · [Korean replay](ko.html) · [100 evaluation tasks](../../dataset/original-100/tasks.jsonl)

| Cohort | System | Passing attempts | Accuracy | pass@3 | pass^3 |
|---|---|---:|---:|---:|---:|
| Chinese set | Agent | 91/150 | 60.7% | 43/50 | 19/50 |
| Chinese set | Baseline | 96/150 | 64.0% | 43/50 | 21/50 |
| Korean set | Agent | 138/150 | 92.0% | 48/50 | 43/50 |
| Korean set | Baseline | 133/150 | 88.7% | 48/50 | 39/50 |
| Combined | Agent | 229/300 | 76.3% | 91/100 | 62/100 |
| Combined | Baseline | 229/300 | 76.3% | 91/100 | 60/100 |

Accuracy counts individual attempts. A question contributes to pass@3 when at least one attempt passes and to pass^3 when all three pass.

## How to interpret the comparison

Within each cohort the baseline and agent share the first draft, retrieval results and initial quote checks. The baseline follows a fixed revision workflow. The agent chooses its next action after inspecting the available evidence. An ordinary answer needs at least two suitable expressions with verified quotes that demonstrate their use. Code checks quote provenance, and model votes judge semantic fit. Special tasks use their own pass conditions.

- **Chinese set.** Generation used `gpt-6.1-sol`, judging used `gpt-6.1-sol`, and the corpus was `phrase-room-coach`. Current agent keeps verified examples and can fill remaining slots.
- **Korean set.** Generation used `claude-haiku-5-5`, judging used `gpt-5.4-mini-2026-03-17`, and the corpus was `corpus-20261116-full-v2`. Submission agent can revise previously verified examples.

The pooled counts summarize two experiments conducted under different configurations. Use the within-cohort comparisons to interpret system differences. The historical Korean cohort includes one English-language edge case.

## A traced failure

On the second attempt at `zh-for-instance`, the learner asked how to introduce an example with “for example” and requested quotes exclusively from *The Changelog*. The model correctly identified the request as answerable and selected the requested show, then returned an empty list of candidate expressions. Both systems reuse that first model response. The validator requires at least three candidates, so it stopped both runs with `invalid_model_output` before either system searched the transcripts. The trace places the failure in candidate generation. A targeted change to test would be to request candidates once more when an answerable usage question produces an empty list. [Replay this attempt](zh.html#zh-for-instance/2).

[Detailed Chinese results and changing verdicts](chinese-results.md) · [Summary metrics](results.json) · [All 600 attempt records](attempts.jsonl)
