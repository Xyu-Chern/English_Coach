# Results: Baseline vs Agent, 50 tasks, 3 runs each

Baseline: a fixed workflow. Agent: the LLM agent. Both answer the same tasks and start from the same shared first stage. Quality comes from `grades/grades.jsonl` (LLM judge, majority of 3 votes; not human gold). Method notes are at the end.

|  |  |
|---|---|
| Run | `zh-sol-local-50-retry` |
| Task file | `evaluation/data/tasks.zh.jsonl` (50 tasks, sha256 `862413e68f9a`) |
| Runs per task | 3 |
| Generation model | gpt-6.1-sol (effort n/a) |
| Judge | gpt-6.1-sol, protocol `multi-expression-grader-v2`, 3 votes per unit, majority |
| Corpus snapshot | zh-six-local-v1 (sha256 `cf59eb7fc3c7`) |
| Code | commit `2e3210360a11`, working-tree diff sha256 `4db5f73c5a5c` |

## Coverage

| System | Expected | Recorded | Graded | Recorded, no grade | Infrastructure failures | Error codes (graded) |
|---|---|---|---|---|---|---|
| Baseline | 150 | 61 | 55 | 6 | 1 | invalid_model_output: 1, model_unavailable: 1 |
| Agent | 150 | 61 | 55 | 6 | 1 | invalid_model_output: 1, model_unavailable: 1 |

No grade yet: `zh-by-the-way/baseline/2`, `zh-cover-shift/baseline/3`, `zh-in-other-words/baseline/1`, `zh-meet-stop/baseline/2`, `zh-water-glass/baseline/1`, `zh-water-glass/baseline/2`, `zh-by-the-way/agent/2`, `zh-cover-shift/agent/3`, `zh-in-other-words/agent/1`, `zh-meet-stop/agent/2`, `zh-water-glass/agent/1`, `zh-water-glass/agent/2`.

## Results

| Metric | Baseline | Agent |
|---|---|---|
| Accuracy (pass rate) | 10.9% (6/55) | 21.8% (12/55) |
| Strict pass rate (all 3 expressions good) | 7.3% (4/55) | 10.9% (6/55) |
| pass@3 (any run passes) | 0.0% (0/3) | 0.0% (0/3) |
| pass^3 (all runs pass) | 0.0% (0/3) | 0.0% (0/3) |
| Empty answers (answerable attempts, no good expression) | 80.0% (40/50) | 78.0% (39/50) |
| Turns: model calls per attempt (first stage included) | 6.89 | 4.00 |
| Decision rounds after the shared first stage | 2.53 | 2.02 |
| Latency mean (s) | 105.2 | 73.9 |
| Latency p95 (s) | 606.1 | 430.7 |
| Tokens per attempt (mean) | 58,757 | 47,521 |
| Cost per attempt (USD, mean) | n/a | n/a |

Rates are over graded attempts (tasks × runs); pass@k and pass^k are over tasks.

## By expectation

| Group | Tasks | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| answer | 43 | 4.0% (2/50) | 16.0% (8/50) | 0.0% (0/50) | 4.0% (2/50) |
| edge | 6 | 0.0% (0/7) | 14.3% (1/7) | 0.0% (0/7) | 0.0% (0/7) |
| unanswerable | 7 | 80.0% (4/5) | 80.0% (4/5) | 80.0% (4/5) | 80.0% (4/5) |

answer: tasks expecting expressions (edge cases included); edge and unanswerable: by category.

## By category

| Category | Tasks | Baseline pass | Agent pass |
|---|---|---|---|
| specific/context | 6 | 12.5% (1/8) | 25.0% (2/8) |
| specific/plain | 1 | 0.0% (0/1) | 0.0% (0/1) |
| specific/constraint | 3 | 0.0% (0/2) | 0.0% (0/2) |
| function/context | 5 | 0.0% (0/10) | 20.0% (2/10) |
| function/constraint | 2 | 0.0% (0/2) | 0.0% (0/2) |
| function/plain | 2 | 33.3% (1/3) | 33.3% (1/3) |
| draft/context | 3 | 0.0% (0/2) | 0.0% (0/2) |
| draft/constraint | 3 | 0.0% (0/3) | 0.0% (0/3) |
| usage/plain | 4 | 0.0% (0/3) | 0.0% (0/3) |
| usage/context | 3 | 0.0% (0/3) | 0.0% (0/3) |
| usage/constraint | 1 | 0.0% (0/1) | 0.0% (0/1) |
| compare/context | 2 | n/a | n/a |
| compare/plain | 1 | 0.0% (0/2) | 100.0% (2/2) |
| compare/constraint | 1 | 0.0% (0/3) | 0.0% (0/3) |
| edge | 6 | 0.0% (0/7) | 14.3% (1/7) |
| unanswerable | 7 | 80.0% (4/5) | 80.0% (4/5) |

## Agent − Baseline (30 answerable tasks, paired)

| Metric | Tasks | Difference (pp) | 95% CI (pp) |
|---|---|---|---|
| Pass | 30 | +15.0 | [+3.3, +28.3] |
| Strict | 30 | +5.0 | [+0.0, +13.3] |

Units with an infrastructure failure in either system are left out of both: `zh-photo-turn/1`. With them: pass +14.5 pp [+3.2, +27.4], strict +4.8 pp [+0.0, +12.9].

- Pass non-inferiority (CI lower bound > -5.0 pp): met (lower bound +3.3 pp).
- Strict superiority (CI lower bound > 0): not met (lower bound +0.0 pp).
- Empty-answer difference ≤ +3.0 pp: met (-2.0 pp: 78.0% (39/50) vs 80.0% (40/50)).

## By first-stage state

The shared first stage verifies up to 3 answer slots before either system decides anything. Units: answerable task × run.

| State | Units | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| review (all 3 slots verified) | 1 | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) |
| recovery (fewer than 3 verified) | 53 | 4.3% (2/46) | 17.4% (8/46) | 0.0% (0/46) | 4.3% (2/46) |

## Tasks whose result changed across the 3 runs

| System | Task | Category | Runs 1-3 |
|---|---|---|---|
| Baseline | zh-borrow-book | specific/context | F P · |

Changed tasks per system: Baseline: 1; Agent: 0. P pass, F fail, · not graded.

## Failure analysis

> **TODO (human):** write one paragraph of failure analysis here: pick one failure from the candidates below, say which step went wrong and why. Intentionally left blank; not generated.

### Candidate failures (attempts that did not pass)

| System | Task | Run | Category | Where in the trace | Why it failed (judge and code checks) |
|---|---|---|---|---|---|
| Baseline | zh-train-door | 3 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-split-bill | 2 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-split-bill | 3 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-photo-turn | 1 | specific/context | candidates: model_unavailable | status error: model_unavailable |
| Baseline | zh-borrow-book | 1 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-known-face | 2 | specific/plain | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-dry-run | 1 | specific/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-dry-run | 2 | specific/context | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-save-seat | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Baseline | zh-miss-point | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-hand-floor | 3 | function/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-back-up | 1 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-back-up | 2 | function/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 no example; 2 of 3 expressions shown |
| Baseline | zh-back-up | 3 | function/context | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 no example; #3 no example |
| Baseline | zh-give-credit | 1 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-exit-call | 1 | function/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail, explanation_ok=fail; #2 no example; #3 no example |
| Baseline | zh-exit-call | 3 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-private-topic | 1 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-private-topic | 2 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-private-topic | 3 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-check-hearing | 1 | function/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-check-hearing | 2 | function/constraint | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-defer-choice | 2 | function/plain | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 duplicate, no example; #3 no example |
| Baseline | zh-defer-choice | 3 | function/plain | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 fits=fail; #2 no example; #3 no example |
| Baseline | zh-spare-charger | 1 | draft/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail, explanation_ok=fail; #2 no example; #3 no example |
| Baseline | zh-spare-charger | 2 | draft/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-sorry-delay | 1 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-mute-mic | 1 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-mute-mic | 3 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-for-instance | 1 | usage/plain | validate_action: invalid_model_output | status error: invalid_model_output |
| Baseline | zh-for-instance | 3 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Baseline | zh-my-bad | 1 | usage/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail, shows_use=fail; #2 fits=fail, no example; #3 fits=fail, no example |
| Baseline | zh-rings-bell | 2 | usage/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail, no example; #2 fits=fail, no example; #3 fits=fail, no example |
| Baseline | zh-rings-bell | 3 | usage/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 fits=fail, no example; #3 fits=fail, no example |
| Baseline | zh-so-far | 3 | usage/constraint | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 duplicate, no example |
| Baseline | zh-in-other-words | 2 | usage/plain | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 fits=fail, shows_use=fail; #2 fits=uncertain, no example; #3 fits=uncertain, no example |
| Baseline | zh-used-to | 2 | compare/plain | verified slots: first stage 2/3 → final 3/3 after 3 rounds | set constraint failed |
| Baseline | zh-used-to | 3 | compare/plain | verified slots: first stage 1/3 → final 2/3 after 2 rounds | set constraint failed |
| Baseline | zh-lend-borrow | 1 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail, no example; #2 fits=fail, no example; #3 duplicate, no example |
| Baseline | zh-lend-borrow | 2 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-lend-borrow | 3 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Baseline | zh-catch-up | 3 | edge/one_word | verified slots: first stage 0/3 → final 3/3 after 2 rounds | grounded-good 1/3; #2 fits=fail; #3 fits=fail, natural=uncertain, shows_use=fail |
| Baseline | zh-loud-phone | 3 | edge/pinyin | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 fits=fail, no example; #3 no example |
| Baseline | zh-lost-thread | 1 | edge/typo | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Baseline | zh-demo-switch | 1 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-demo-switch | 3 | edge/code_switching | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 no example; 2 of 3 expressions shown |
| Baseline | zh-parcel-story | 1 | edge/long_input | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-parcel-story | 2 | edge/long_input | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 no example; #3 no example |
| Baseline | zh-account-plan | 3 | unanswerable/account_action | verified slots: first stage 0/3 → final 2/3 after 3 rounds | 3 expressions returned instead of declining; no availability note |
| Agent | zh-train-door | 3 | specific/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-split-bill | 2 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 fits=uncertain, no example; #3 no example |
| Agent | zh-split-bill | 3 | specific/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-photo-turn | 1 | specific/context | candidates: model_unavailable | status error: model_unavailable |
| Agent | zh-known-face | 2 | specific/plain | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-dry-run | 1 | specific/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 duplicate, no example |
| Agent | zh-dry-run | 2 | specific/context | verified slots: first stage 1/3 → final 1/3 after 1 round | grounded-good 1/3; #2 no example; #3 no example |
| Agent | zh-save-seat | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-miss-point | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Agent | zh-back-up | 1 | function/context | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 fits=fail, explanation_ok=fail; #2 no example; #3 no example |
| Agent | zh-back-up | 2 | function/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-back-up | 3 | function/context | verified slots: first stage 1/3 → final 1/3 after 1 round | grounded-good 0/3; #1 no example; #2 no example; #3 shows_use=fail |
| Agent | zh-exit-call | 1 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-exit-call | 3 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-private-topic | 1 | function/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-private-topic | 2 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-private-topic | 3 | function/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-check-hearing | 1 | function/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-check-hearing | 2 | function/constraint | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 duplicate, no example; #3 no example |
| Agent | zh-defer-choice | 2 | function/plain | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Agent | zh-defer-choice | 3 | function/plain | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-spare-charger | 1 | draft/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 duplicate, no example |
| Agent | zh-spare-charger | 2 | draft/context | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-sorry-delay | 1 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-mute-mic | 1 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 duplicate, no example |
| Agent | zh-mute-mic | 3 | draft/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 duplicate, no example |
| Agent | zh-for-instance | 1 | usage/plain | validate_action: invalid_model_output | status error: invalid_model_output |
| Agent | zh-for-instance | 3 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Agent | zh-my-bad | 1 | usage/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 duplicate, no example |
| Agent | zh-rings-bell | 2 | usage/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-rings-bell | 3 | usage/context | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 duplicate, no example |
| Agent | zh-so-far | 3 | usage/constraint | verified slots: first stage 0/3 → final 1/3 after 2 rounds | grounded-good 0/3; #1 shows_use=fail, explanation_ok=fail; #2 no example; #3 no example |
| Agent | zh-in-other-words | 2 | usage/plain | verified slots: first stage 0/3 → final 0/3 after 1 round | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-lend-borrow | 1 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 1 round | set constraint failed; grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 duplicate, no example |
| Agent | zh-lend-borrow | 2 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 duplicate, no example |
| Agent | zh-lend-borrow | 3 | compare/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Agent | zh-catch-up | 3 | edge/one_word | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 natural=fail, no example |
| Agent | zh-loud-phone | 3 | edge/pinyin | verified slots: first stage 0/3 → final 0/3 after 1 round | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-demo-switch | 1 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 1 round | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-demo-switch | 3 | edge/code_switching | verified slots: first stage 1/3 → final 1/3 after 1 round | grounded-good 0/3; #1 shows_use=fail; #2 no example; #3 no example |
| Agent | zh-parcel-story | 1 | edge/long_input | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-parcel-story | 2 | edge/long_input | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-account-plan | 3 | unanswerable/account_action | verified slots: first stage 0/3 → final 3/3 after 3 rounds | 3 expressions returned instead of declining; no availability note |

## Method

- Pass, expect=answer: ok status, no injected marker, no failed set constraint and at least 2 of the 3 expressions grounded-good (fits the request, natural, and backed by a podcast quote that code verified as the exact corpus slice and the judge found to show the use). Pass, expect=decline: no expressions and a note. Strict: as pass, with all 3 expressions grounded-good.
- Judge: an LLM judge, 3 votes per unit (expression, example, set), majority; not human gold.
- pass@3: share of tasks with at least one passing run; pass^3: share with all 3 passing; both over tasks with all 3 runs graded.
- Turns: model calls per attempt, the shared first stage included. Rounds: decision steps after the shared first stage (baseline revise_r, agent agent_r), from the trace.
- Latency p95: nearest rank, the ceil(0.95 * n)-th smallest. Tokens: chat input + output per attempt (embedding tokens excluded). Cost: list-price USD estimate per attempt.
- Empty answers: expect=answer attempts with no grounded-good expression.
- Paired comparison: per task, the mean over its graded runs; agent − baseline over the expect=answer tasks graded in both; units with an infrastructure failure in either system left out of both; percentile bootstrap over tasks, 4000 resamples, seed 7.
- First-stage state: from the shared first verification (validate_select_1); review = all 3 slots verified, recovery = fewer.
