# Results: Baseline vs Agent, 50 tasks, 3 runs each

Baseline: a fixed workflow. Agent: the LLM agent. Both answer the same tasks and start from the same shared first stage. Quality comes from `grades/grades.jsonl` (LLM judge, majority of 3 votes; not human gold). Method notes are at the end.

|  |  |
|---|---|
| Run | `original-zh50-casa` |
| Task file | `evaluation/data/tasks.zh.jsonl` (50 tasks, sha256 `862413e68f9a`) |
| Runs per task | 3 |
| Generation model | gpt-6.1-sol (effort n/a) |
| Judge | gpt-6.1-sol, protocol `multi-expression-grader-v2`, 3 votes per unit, majority |
| Corpus snapshot | phrase-room-coach (sha256 `c858b5ae99b6`) |
| Code | commit `eebfb1fbb1a8`, working-tree diff sha256 `e3b0c44298fc` |

## Coverage

| System | Expected | Recorded | Graded | Recorded, no grade | Infrastructure failures | Error codes (graded) |
|---|---|---|---|---|---|---|
| Baseline | 150 | 150 | 150 | 0 | 0 | invalid_model_output: 1 |
| Agent | 150 | 150 | 150 | 0 | 0 | invalid_model_output: 1 |

## Results

| Metric | Baseline | Agent |
|---|---|---|
| Accuracy (pass rate) | 64.0% (96/150) | 60.7% (91/150) |
| Strict pass rate (all 3 expressions good) | 43.3% (65/150) | 42.0% (63/150) |
| pass@3 (any run passes) | 86.0% (43/50) | 86.0% (43/50) |
| pass^3 (all runs pass) | 42.0% (21/50) | 38.0% (19/50) |
| Empty answers (answerable attempts, no good expression) | 16.3% (21/129) | 17.8% (23/129) |
| Turns: model calls per attempt (first stage included) | 3.33 | 2.66 |
| Decision rounds after the shared first stage | 0.77 | 0.77 |
| Latency mean (s) | 105.4 | 94.4 |
| Latency p95 (s) | 303.8 | 251.2 |
| Tokens per attempt (mean) | 27,884 | 27,866 |
| Cost per attempt (USD, mean) | n/a | n/a |

Rates are over graded attempts (tasks × runs); pass@k and pass^k are over tasks.

## By expectation

| Group | Tasks | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| answer | 43 | 60.5% (78/129) | 56.6% (73/129) | 36.4% (47/129) | 34.9% (45/129) |
| edge | 6 | 50.0% (9/18) | 61.1% (11/18) | 27.8% (5/18) | 27.8% (5/18) |
| unanswerable | 7 | 85.7% (18/21) | 85.7% (18/21) | 85.7% (18/21) | 85.7% (18/21) |

answer: tasks expecting expressions (edge cases included); edge and unanswerable: by category.

## By category

| Category | Tasks | Baseline pass | Agent pass |
|---|---|---|---|
| specific/context | 6 | 55.6% (10/18) | 55.6% (10/18) |
| specific/plain | 1 | 100.0% (3/3) | 100.0% (3/3) |
| specific/constraint | 3 | 55.6% (5/9) | 33.3% (3/9) |
| function/context | 5 | 73.3% (11/15) | 73.3% (11/15) |
| function/constraint | 2 | 66.7% (4/6) | 33.3% (2/6) |
| function/plain | 2 | 83.3% (5/6) | 83.3% (5/6) |
| draft/context | 3 | 66.7% (6/9) | 33.3% (3/9) |
| draft/constraint | 3 | 77.8% (7/9) | 77.8% (7/9) |
| usage/plain | 4 | 25.0% (3/12) | 25.0% (3/12) |
| usage/context | 3 | 66.7% (6/9) | 66.7% (6/9) |
| usage/constraint | 1 | 0.0% (0/3) | 0.0% (0/3) |
| compare/context | 2 | 66.7% (4/6) | 83.3% (5/6) |
| compare/plain | 1 | 100.0% (3/3) | 100.0% (3/3) |
| compare/constraint | 1 | 66.7% (2/3) | 33.3% (1/3) |
| edge | 6 | 50.0% (9/18) | 61.1% (11/18) |
| unanswerable | 7 | 85.7% (18/21) | 85.7% (18/21) |

## Agent − Baseline (43 answerable tasks, paired)

| Metric | Tasks | Difference (pp) | 95% CI (pp) |
|---|---|---|---|
| Pass | 43 | -3.9 | [-9.3, +1.6] |
| Strict | 43 | -1.6 | [-7.0, +3.9] |

- Pass non-inferiority (CI lower bound > -5.0 pp): not met (lower bound -9.3 pp).
- Strict superiority (CI lower bound > 0): not met (lower bound -7.0 pp).
- Empty-answer difference ≤ +3.0 pp: met (+1.6 pp: 17.8% (23/129) vs 16.3% (21/129)).

## By first-stage state

The shared first stage verifies up to 3 answer slots before either system decides anything. Units: answerable task × run.

| State | Units | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| review (all 3 slots verified) | 76 | 63.2% (48/76) | 63.2% (48/76) | 42.1% (32/76) | 42.1% (32/76) |
| recovery (fewer than 3 verified) | 53 | 60.0% (30/50) | 50.0% (25/50) | 30.0% (15/50) | 26.0% (13/50) |

## Tasks whose result changed across the 3 runs

| System | Task | Category | Runs 1-3 |
|---|---|---|---|
| Baseline | zh-train-door | specific/context | P F F |
| Baseline | zh-split-bill | specific/context | F F P |
| Baseline | zh-photo-turn | specific/context | F P P |
| Baseline | zh-cover-shift | specific/context | F P P |
| Baseline | zh-borrow-book | specific/context | F P F |
| Baseline | zh-miss-point | specific/constraint | P F P |
| Baseline | zh-hand-floor | function/context | P P F |
| Baseline | zh-back-up | function/context | F P F |
| Baseline | zh-private-topic | function/context | F P P |
| Baseline | zh-check-hearing | function/constraint | F P P |
| Baseline | zh-ask-ride | function/constraint | F P P |
| Baseline | zh-ask-demo | function/plain | P P F |
| Baseline | zh-spare-charger | draft/context | P F P |
| Baseline | zh-meet-stop | draft/context | F P F |
| Baseline | zh-sorry-delay | draft/constraint | F F P |
| Baseline | zh-my-bad | usage/context | F F P |
| Baseline | zh-good-point | usage/context | P P F |
| Baseline | zh-bring-take | compare/context | P F F |
| Baseline | zh-lend-borrow | compare/constraint | P P F |
| Baseline | zh-leftovers | edge/traditional | F P F |
| Baseline | zh-demo-switch | edge/code_switching | F P F |
| Baseline | zh-parcel-story | edge/long_input | F F P |
| Agent | zh-train-door | specific/context | F F P |
| Agent | zh-split-bill | specific/context | F F P |
| Agent | zh-photo-turn | specific/context | F P P |
| Agent | zh-cover-shift | specific/context | P F P |
| Agent | zh-borrow-book | specific/context | F P F |
| Agent | zh-no-rush | specific/constraint | P P F |
| Agent | zh-miss-point | specific/constraint | P F F |
| Agent | zh-hand-floor | function/context | P P F |
| Agent | zh-back-up | function/context | F F P |
| Agent | zh-private-topic | function/context | F P P |
| Agent | zh-check-hearing | function/constraint | F P F |
| Agent | zh-ask-ride | function/constraint | F P F |
| Agent | zh-ask-demo | function/plain | P P F |
| Agent | zh-arrive-home | draft/context | F F P |
| Agent | zh-spare-charger | draft/context | P F P |
| Agent | zh-sorry-delay | draft/constraint | F F P |
| Agent | zh-my-bad | usage/context | F F P |
| Agent | zh-good-point | usage/context | P P F |
| Agent | zh-bring-take | compare/context | P F P |
| Agent | zh-lend-borrow | compare/constraint | F P F |
| Agent | zh-loud-phone | edge/pinyin | F P F |
| Agent | zh-leftovers | edge/traditional | F P P |
| Agent | zh-demo-switch | edge/code_switching | F P F |
| Agent | zh-parcel-story | edge/long_input | F F P |

Changed tasks per system: Baseline: 22; Agent: 24. P pass, F fail, · not graded.

## Failure analysis

On the second attempt at `zh-for-instance`, the learner asked how to introduce an example with “for example” and requested quotes exclusively from *The Changelog*. The model correctly identified the request as answerable and selected the requested show, then returned an empty list of candidate expressions. Both systems reuse that first model response. The validator requires at least three candidates, so it stopped both runs with `invalid_model_output` before either system searched the transcripts. The trace places the failure in candidate generation. A targeted change to test would be to request candidates once more when an answerable usage question produces an empty list. [Replay this attempt](zh.html#zh-for-instance/2).

### Candidate failures (attempts that did not pass)

| System | Task | Run | Category | Where in the trace | Why it failed (judge and code checks) |
|---|---|---|---|---|---|
| Baseline | zh-train-door | 2 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-train-door | 3 | specific/context | verified slots: first stage 0/3 → final 3/3 after 2 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-split-bill | 1 | specific/context | verified slots: first stage 0/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 fits=fail, shows_use=fail; #3 no example |
| Baseline | zh-split-bill | 2 | specific/context | verified slots: first stage 0/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 shows_use=fail; #3 no example |
| Baseline | zh-photo-turn | 1 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 natural=fail, shows_use=fail |
| Baseline | zh-cover-shift | 1 | specific/context | verified slots: first stage 0/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 fits=fail; #3 no example |
| Baseline | zh-borrow-book | 1 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 duplicate |
| Baseline | zh-borrow-book | 3 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-save-seat | 1 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 fits=fail, no example |
| Baseline | zh-save-seat | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-save-seat | 3 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-miss-point | 2 | specific/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-hand-floor | 3 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-back-up | 1 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-back-up | 3 | function/context | verified slots: first stage 2/3 → final 3/3 after 1 round | grounded-good 1/3; #1 shows_use=fail; #3 fits=fail, shows_use=fail, explanation_ok=fail |
| Baseline | zh-private-topic | 1 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Baseline | zh-check-hearing | 1 | function/constraint | verified slots: first stage 2/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-ask-ride | 1 | function/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 no example |
| Baseline | zh-ask-demo | 3 | function/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Baseline | zh-spare-charger | 2 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Baseline | zh-meet-stop | 1 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Baseline | zh-meet-stop | 3 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate, shows_use=fail |
| Baseline | zh-sorry-delay | 1 | draft/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-sorry-delay | 2 | draft/constraint | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-by-the-way | 1 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=uncertain; #2 fits=uncertain; #3 fits=uncertain |
| Baseline | zh-by-the-way | 2 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=uncertain; #2 fits=uncertain; #3 fits=uncertain |
| Baseline | zh-by-the-way | 3 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=uncertain; #3 fits=uncertain |
| Baseline | zh-turns-out | 1 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Baseline | zh-turns-out | 2 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Baseline | zh-turns-out | 3 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Baseline | zh-for-instance | 1 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Baseline | zh-for-instance | 2 | usage/plain | validate_action: invalid_model_output | status error: invalid_model_output |
| Baseline | zh-for-instance | 3 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Baseline | zh-my-bad | 1 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate, explanation_ok=fail |
| Baseline | zh-my-bad | 2 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Baseline | zh-good-point | 3 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-so-far | 1 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-so-far | 2 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-so-far | 3 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-bring-take | 2 | compare/context | verified slots: first stage 1/3 → final 2/3 after 2 rounds | grounded-good 1/3; #1 fits=fail, shows_use=fail, explanation_ok=fail; #3 no example |
| Baseline | zh-bring-take | 3 | compare/context | verified slots: first stage 2/3 → final 3/3 after 1 round | grounded-good 1/3; #1 shows_use=fail; #3 explanation_ok=fail |
| Baseline | zh-lend-borrow | 3 | compare/constraint | verified slots: first stage 2/3 → final 3/3 after 1 round | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail, explanation_ok=fail |
| Baseline | zh-loud-phone | 1 | edge/pinyin | verified slots: first stage 1/3 → final 2/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 no example |
| Baseline | zh-loud-phone | 2 | edge/pinyin | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 fits=fail, shows_use=fail; #3 no example |
| Baseline | zh-loud-phone | 3 | edge/pinyin | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Baseline | zh-leftovers | 1 | edge/traditional | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-leftovers | 3 | edge/traditional | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | zh-demo-switch | 1 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 duplicate, shows_use=fail |
| Baseline | zh-demo-switch | 3 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 duplicate, shows_use=fail; #3 duplicate, shows_use=fail |
| Baseline | zh-parcel-story | 1 | edge/long_input | verified slots: first stage 2/3 → final 3/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-parcel-story | 2 | edge/long_input | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Baseline | zh-account-plan | 1 | unanswerable/account_action | verified slots: first stage 1/3 → final 3/3 after 2 rounds | 3 expressions returned instead of declining; no availability note |
| Baseline | zh-account-plan | 2 | unanswerable/account_action | verified slots: first stage 1/3 → final 2/3 after 3 rounds | 3 expressions returned instead of declining; no availability note |
| Baseline | zh-account-plan | 3 | unanswerable/account_action | verified slots: first stage 1/3 → final 2/3 after 3 rounds | 3 expressions returned instead of declining; no availability note |
| Agent | zh-train-door | 1 | specific/context | verified slots: first stage 1/3 → final 3/3 after 3 rounds | grounded-good 1/3; #2 explanation_ok=fail; #3 fits=fail |
| Agent | zh-train-door | 2 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Agent | zh-split-bill | 1 | specific/context | verified slots: first stage 0/3 → final 1/3 after 2 rounds | grounded-good 0/3; #1 fits=fail, shows_use=fail; #2 no example; #3 no example |
| Agent | zh-split-bill | 2 | specific/context | verified slots: first stage 0/3 → final 1/3 after 2 rounds | grounded-good 0/3; #1 fits=fail; #2 no example; #3 no example |
| Agent | zh-photo-turn | 1 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 natural=fail, shows_use=fail |
| Agent | zh-cover-shift | 2 | specific/context | verified slots: first stage 0/3 → final 1/3 after 2 rounds | grounded-good 1/3; 1 of 3 expressions shown |
| Agent | zh-borrow-book | 1 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 duplicate |
| Agent | zh-borrow-book | 3 | specific/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-save-seat | 1 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-save-seat | 2 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-save-seat | 3 | specific/constraint | verified slots: first stage 0/3 → final 0/3 after 2 rounds | grounded-good 0/3; #1 no example; #2 duplicate, no example; #3 no example |
| Agent | zh-no-rush | 3 | specific/constraint | verified slots: first stage 1/3 → final 2/3 after 1 round | set constraint failed |
| Agent | zh-miss-point | 2 | specific/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Agent | zh-miss-point | 3 | specific/constraint | verified slots: first stage 1/3 → final 1/3 after 1 round | grounded-good 1/3; #2 no example; #3 no example |
| Agent | zh-hand-floor | 3 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-back-up | 1 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-back-up | 2 | function/context | verified slots: first stage 1/3 → final 3/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail, explanation_ok=fail |
| Agent | zh-private-topic | 1 | function/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Agent | zh-check-hearing | 1 | function/constraint | verified slots: first stage 2/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail; #3 duplicate |
| Agent | zh-check-hearing | 3 | function/constraint | verified slots: first stage 0/3 → final 3/3 after 3 rounds | grounded-good 1/3; #1 shows_use=fail; #2 fits=fail |
| Agent | zh-ask-ride | 1 | function/constraint | verified slots: first stage 2/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Agent | zh-ask-ride | 3 | function/constraint | verified slots: first stage 0/3 → final 0/3 after 1 round | grounded-good 0/3; #1 no example; #2 no example; #3 no example |
| Agent | zh-ask-demo | 3 | function/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Agent | zh-arrive-home | 1 | draft/context | verified slots: first stage 2/3 → final 3/3 after 3 rounds | grounded-good 1/3; #2 duplicate; #3 fits=fail |
| Agent | zh-arrive-home | 2 | draft/context | verified slots: first stage 1/3 → final 2/3 after 1 round | grounded-good 1/3; #2 duplicate; #3 no example |
| Agent | zh-spare-charger | 2 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Agent | zh-meet-stop | 1 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Agent | zh-meet-stop | 2 | draft/context | verified slots: first stage 2/3 → final 3/3 after 2 rounds | grounded-good 1/3; #2 duplicate, shows_use=fail; #3 shows_use=fail |
| Agent | zh-meet-stop | 3 | draft/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate, shows_use=fail |
| Agent | zh-sorry-delay | 1 | draft/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 shows_use=fail |
| Agent | zh-sorry-delay | 2 | draft/constraint | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Agent | zh-by-the-way | 1 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=uncertain; #2 fits=uncertain; #3 fits=uncertain |
| Agent | zh-by-the-way | 2 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=uncertain; #2 fits=uncertain; #3 fits=uncertain |
| Agent | zh-by-the-way | 3 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=uncertain; #3 fits=uncertain |
| Agent | zh-turns-out | 1 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Agent | zh-turns-out | 2 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Agent | zh-turns-out | 3 | usage/plain | verified slots: first stage 3/3 → final 3/3 after 0 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail; #3 fits=fail |
| Agent | zh-for-instance | 1 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Agent | zh-for-instance | 2 | usage/plain | validate_action: invalid_model_output | status error: invalid_model_output |
| Agent | zh-for-instance | 3 | usage/plain | candidates: request judged source_not_available, declined | grounded-good 0/3; 0 of 3 expressions shown |
| Agent | zh-my-bad | 1 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate, explanation_ok=fail |
| Agent | zh-my-bad | 2 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 duplicate; #3 duplicate |
| Agent | zh-good-point | 3 | usage/context | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-so-far | 1 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-so-far | 2 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-so-far | 3 | usage/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-bring-take | 2 | compare/context | verified slots: first stage 1/3 → final 1/3 after 2 rounds | grounded-good 0/3; #1 fits=fail, shows_use=fail, explanation_ok=fail; #2 no example; #3 no example |
| Agent | zh-lend-borrow | 1 | compare/constraint | verified slots: first stage 2/3 → final 2/3 after 1 round | grounded-good 1/3; #1 shows_use=fail; #3 no example |
| Agent | zh-lend-borrow | 3 | compare/constraint | verified slots: first stage 2/3 → final 2/3 after 1 round | grounded-good 1/3; #2 shows_use=fail; #3 fits=fail, no example |
| Agent | zh-loud-phone | 1 | edge/pinyin | verified slots: first stage 1/3 → final 2/3 after 3 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 no example |
| Agent | zh-loud-phone | 3 | edge/pinyin | verified slots: first stage 0/3 → final 0/3 after 3 rounds | grounded-good 0/3; #1 no example; #2 no example; #3 duplicate, no example |
| Agent | zh-leftovers | 1 | edge/traditional | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Agent | zh-demo-switch | 1 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 shows_use=fail; #3 duplicate, shows_use=fail |
| Agent | zh-demo-switch | 3 | edge/code_switching | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 0/3; #1 shows_use=fail; #2 duplicate, shows_use=fail; #3 duplicate, shows_use=fail |
| Agent | zh-parcel-story | 1 | edge/long_input | verified slots: first stage 2/3 → final 3/3 after 2 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-parcel-story | 2 | edge/long_input | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 shows_use=fail; #3 shows_use=fail |
| Agent | zh-account-plan | 1 | unanswerable/account_action | verified slots: first stage 1/3 → final 3/3 after 2 rounds | 3 expressions returned instead of declining; no availability note |
| Agent | zh-account-plan | 2 | unanswerable/account_action | verified slots: first stage 1/3 → final 3/3 after 2 rounds | 3 expressions returned instead of declining; no availability note |
| Agent | zh-account-plan | 3 | unanswerable/account_action | verified slots: first stage 1/3 → final 3/3 after 3 rounds | 3 expressions returned instead of declining; no availability note |

## Method

- Pass, expect=answer: ok status, no injected marker, no failed set constraint and at least 2 of the 3 expressions grounded-good (fits the request, natural, and backed by a podcast quote that code verified as the exact corpus slice and the judge found to show the use). Pass, expect=decline: no expressions and a note. Strict: as pass, with all 3 expressions grounded-good.
- Judge: an LLM judge, 3 votes per unit (expression, example, set), majority; not human gold.
- pass@3: share of tasks with at least one passing run; pass^3: share with all 3 passing; both over tasks with all 3 runs graded.
- Turns: model calls per attempt, the shared first stage included. Rounds: decision steps after the shared first stage (baseline revise_r, agent agent_r), from the trace.
- Latency p95: nearest rank, the ceil(0.95 * n)-th smallest. Tokens: chat input + output per attempt (embedding tokens excluded). Cost: list-price USD estimate per attempt.
- Empty answers: expect=answer attempts with no grounded-good expression.
- Paired comparison: per task, the mean over its graded runs; agent − baseline over the expect=answer tasks graded in both; units with an infrastructure failure in either system left out of both; percentile bootstrap over tasks, 4000 resamples, seed 7.
- First-stage state: from the shared first verification (validate_select_1); review = all 3 slots verified, recovery = fewer.
