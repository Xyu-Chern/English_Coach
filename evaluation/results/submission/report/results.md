# Results: Baseline vs Agent, 50 tasks, 3 runs each

Baseline: a fixed workflow. Agent: the LLM agent. Both answer the same tasks and start from the same shared first stage. Quality comes from `grades/grades.jsonl` (LLM judge, majority of 3 votes; not human gold). Method notes are at the end.

|  |  |
|---|---|
| Run | `submission` |
| Task file | `evaluation/data/tasks.jsonl` (50 tasks, sha256 `7bc659a9374e`) |
| Runs per task | 3 |
| Generation model | claude-haiku-5-5 (effort medium) |
| Judge | gpt-5.4-mini-2026-03-17, protocol `multi-expression-grader-v2`, 3 votes per unit, majority |
| Corpus snapshot | corpus-20261116-full-v2 (sha256 `c2357ddebdbf`) |
| Code | commit `173cbedfa449`, working-tree diff sha256 `d30366bb179a` |
| Derived from | evaluation run of 2026-11-17 (50 tasks x 3 runs, baseline and agent). Attempts and grades were recorded by the evaluation run of 2026-11-17 and copied here unchanged except for the system names. That run used the same baseline and agent logic as this code: replaying every attempt through this code gives the same prompts, user messages, schema structure, steps, answers and token counts. Two later edits did not change what the systems or the judge read: the task file gained type, question_en and rubric (question and intended are byte-identical), and three reply-schema descriptions were shortened (internal names removed). |

## Coverage

| System | Expected | Recorded | Graded | Recorded, no grade | Infrastructure failures | Error codes (graded) |
|---|---|---|---|---|---|---|
| Baseline | 150 | 150 | 150 | 0 | 0 | none |
| Agent | 150 | 150 | 150 | 0 | 0 | none |

## Results

| Metric | Baseline | Agent |
|---|---|---|
| Accuracy (pass rate) | 88.7% (133/150) | 92.0% (138/150) |
| Strict pass rate (all 3 expressions good) | 61.3% (92/150) | 69.3% (104/150) |
| pass@3 (any run passes) | 96.0% (48/50) | 96.0% (48/50) |
| pass^3 (all runs pass) | 78.0% (39/50) | 86.0% (43/50) |
| Empty answers (answerable attempts, no good expression) | 1.6% (2/129) | 2.3% (3/129) |
| Turns: model calls per attempt (first stage included) | 3.25 | 3.42 |
| Decision rounds after the shared first stage | 0.75 | 1.50 |
| Latency mean (s) | 26.1 | 33.4 |
| Latency p95 (s) | 51.7 | 60.5 |
| Tokens per attempt (mean) | 40,332 | 58,608 |
| Cost per attempt (USD, mean) | 0.0055 | 0.0080 |

Rates are over graded attempts (tasks × runs); pass@k and pass^k are over tasks.

## By expectation

| Group | Tasks | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| answer | 43 | 86.8% (112/129) | 90.7% (117/129) | 55.0% (71/129) | 64.3% (83/129) |
| edge | 6 | 77.8% (14/18) | 88.9% (16/18) | 27.8% (5/18) | 50.0% (9/18) |
| unanswerable | 7 | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |

answer: tasks expecting expressions (edge cases included); edge and unanswerable: by category.

## By category

| Category | Tasks | Baseline pass | Agent pass |
|---|---|---|---|
| specific/context | 6 | 88.9% (16/18) | 88.9% (16/18) |
| specific/constraint | 4 | 100.0% (12/12) | 100.0% (12/12) |
| function/context | 3 | 100.0% (9/9) | 100.0% (9/9) |
| function/constraint | 3 | 77.8% (7/9) | 100.0% (9/9) |
| draft/context | 3 | 100.0% (9/9) | 100.0% (9/9) |
| draft/constraint | 3 | 55.6% (5/9) | 66.7% (6/9) |
| usage/plain | 3 | 100.0% (9/9) | 100.0% (9/9) |
| usage/context | 3 | 88.9% (8/9) | 100.0% (9/9) |
| usage/constraint | 3 | 66.7% (6/9) | 66.7% (6/9) |
| compare/context | 3 | 100.0% (9/9) | 100.0% (9/9) |
| compare/constraint | 3 | 88.9% (8/9) | 77.8% (7/9) |
| edge | 6 | 77.8% (14/18) | 88.9% (16/18) |
| unanswerable | 7 | 100.0% (21/21) | 100.0% (21/21) |

## Agent − Baseline (43 answerable tasks, paired)

| Metric | Tasks | Difference (pp) | 95% CI (pp) |
|---|---|---|---|
| Pass | 43 | +3.9 | [-0.8, +9.3] |
| Strict | 43 | +9.3 | [+3.1, +16.3] |

- Pass non-inferiority (CI lower bound > -5.0 pp): met (lower bound -0.8 pp).
- Strict superiority (CI lower bound > 0): met (lower bound +3.1 pp).
- Empty-answer difference ≤ +3.0 pp: met (+0.8 pp: 2.3% (3/129) vs 1.6% (2/129)).

## By first-stage state

The shared first stage verifies up to 3 answer slots before either system decides anything. Units: answerable task × run.

| State | Units | Baseline pass | Agent pass | Baseline strict | Agent strict |
|---|---|---|---|---|---|
| review (all 3 slots verified) | 82 | 96.3% (79/82) | 96.3% (79/82) | 69.5% (57/82) | 69.5% (57/82) |
| recovery (fewer than 3 verified) | 47 | 70.2% (33/47) | 80.9% (38/47) | 29.8% (14/47) | 55.3% (26/47) |

## Tasks whose result changed across the 3 runs

| System | Task | Category | Runs 1-3 |
|---|---|---|---|
| Baseline | ko-spec-idiom-ctx-2 | specific/context | F P P |
| Baseline | ko-spec-idiom-ctx-3 | specific/context | P P F |
| Baseline | ko-func-con-2 | function/constraint | P F F |
| Baseline | ko-draft-con-2 | draft/constraint | P F P |
| Baseline | ko-usage-ctx-3 | usage/context | F P P |
| Baseline | ko-cmp-con-1 | compare/constraint | P P F |
| Baseline | ko-edge-typo_keys | edge/typo_keys | F P P |
| Baseline | ko-edge-code_switching | edge/code_switching | F P F |
| Baseline | ko-edge-english_only | edge/english_only | P P F |
| Agent | ko-spec-ctx-1 | specific/context | P P F |
| Agent | ko-spec-idiom-ctx-3 | specific/context | F P P |
| Agent | ko-cmp-con-1 | compare/constraint | P F F |
| Agent | ko-edge-code_switching | edge/code_switching | F P P |
| Agent | ko-edge-english_only | edge/english_only | P P F |

Changed tasks per system: Baseline: 9; Agent: 5. P pass, F fail, · not graded.

## Failure analysis

> **TODO (human):** write one paragraph of failure analysis here: pick one failure from the candidates below, say which step went wrong and why. Intentionally left blank; not generated.

### Candidate failures (attempts that did not pass)

| System | Task | Run | Category | Where in the trace | Why it failed (judge and code checks) |
|---|---|---|---|---|---|
| Baseline | ko-spec-idiom-ctx-2 | 1 | specific/context | verified slots: first stage 1/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail, explanation_ok=fail; #3 no example |
| Baseline | ko-spec-idiom-ctx-3 | 3 | specific/context | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 no example; #3 no example |
| Baseline | ko-func-con-2 | 2 | function/constraint | verified slots: first stage 1/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail; #3 no example |
| Baseline | ko-func-con-2 | 3 | function/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 explanation_ok=fail; #3 no example |
| Baseline | ko-draft-con-1 | 1 | draft/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 shows_use=fail; #3 no example |
| Baseline | ko-draft-con-1 | 2 | draft/constraint | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 fits=fail, natural=fail, shows_use=fail; #2 no example; #3 no example |
| Baseline | ko-draft-con-1 | 3 | draft/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail, explanation_ok=fail; #3 no example |
| Baseline | ko-draft-con-2 | 2 | draft/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Baseline | ko-usage-ctx-3 | 1 | usage/context | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 fits=fail; #3 no example |
| Baseline | ko-usage-con-4 | 1 | usage/constraint | verified slots: first stage 1/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 fits=fail; #3 no example |
| Baseline | ko-usage-con-4 | 2 | usage/constraint | verified slots: first stage 0/3 → final 1/3 after 3 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail, explanation_ok=fail; #2 fits=fail, no example; #3 no example |
| Baseline | ko-usage-con-4 | 3 | usage/constraint | verified slots: first stage 0/3 → final 1/3 after 3 rounds | grounded-good 1/3; #2 fits=fail, no example; #3 fits=fail, no example |
| Baseline | ko-cmp-con-1 | 3 | compare/constraint | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #2 explanation_ok=fail; #3 explanation_ok=fail |
| Baseline | ko-edge-typo_keys | 1 | edge/typo_keys | verified slots: first stage 1/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail; #2 shows_use=fail |
| Baseline | ko-edge-code_switching | 1 | edge/code_switching | verified slots: first stage 2/3 → final 3/3 after 1 round | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #2 shows_use=fail, explanation_ok=fail |
| Baseline | ko-edge-code_switching | 3 | edge/code_switching | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #3 no example |
| Baseline | ko-edge-english_only | 3 | edge/english_only | verified slots: first stage 3/3 → final 3/3 after 0 rounds | grounded-good 1/3; #1 shows_use=fail; #3 explanation_ok=fail |
| Agent | ko-spec-ctx-1 | 3 | specific/context | verified slots: first stage 1/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #3 shows_use=fail |
| Agent | ko-spec-idiom-ctx-3 | 1 | specific/context | verified slots: first stage 0/3 → final 1/3 after 1 round | grounded-good 1/3; #2 no example; #3 no example |
| Agent | ko-draft-con-1 | 1 | draft/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #1 shows_use=fail; #3 no example |
| Agent | ko-draft-con-1 | 2 | draft/constraint | verified slots: first stage 1/3 → final 1/3 after 3 rounds | grounded-good 0/3; #1 fits=fail, natural=fail, shows_use=fail; #2 no example; #3 no example |
| Agent | ko-draft-con-1 | 3 | draft/constraint | verified slots: first stage 2/3 → final 2/3 after 3 rounds | grounded-good 1/3; #2 shows_use=fail, explanation_ok=fail; #3 no example |
| Agent | ko-usage-con-4 | 1 | usage/constraint | verified slots: first stage 1/3 → final 3/3 after 3 rounds | grounded-good 1/3; #2 fits=fail; #3 fits=fail |
| Agent | ko-usage-con-4 | 2 | usage/constraint | verified slots: first stage 0/3 → final 3/3 after 3 rounds | set constraint failed; grounded-good 0/3; #1 fits=fail; #2 fits=fail, natural=fail; #3 fits=fail, explanation_ok=fail |
| Agent | ko-usage-con-4 | 3 | usage/constraint | verified slots: first stage 0/3 → final 3/3 after 3 rounds | grounded-good 0/3; #1 fits=fail, explanation_ok=fail; #2 explanation_ok=fail; #3 fits=fail, explanation_ok=fail |
| Agent | ko-cmp-con-1 | 2 | compare/constraint | verified slots: first stage 3/3 → final 3/3 after 1 round | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #3 fits=fail, explanation_ok=fail |
| Agent | ko-cmp-con-1 | 3 | compare/constraint | verified slots: first stage 3/3 → final 3/3 after 2 rounds | grounded-good 1/3; #2 explanation_ok=fail; #3 explanation_ok=fail |
| Agent | ko-edge-code_switching | 1 | edge/code_switching | verified slots: first stage 2/3 → final 3/3 after 1 round | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #2 shows_use=fail, explanation_ok=fail |
| Agent | ko-edge-english_only | 3 | edge/english_only | verified slots: first stage 3/3 → final 3/3 after 2 rounds | grounded-good 1/3; #1 shows_use=fail, explanation_ok=fail; #3 explanation_ok=fail |

## Method

- Pass, expect=answer: ok status, no injected marker, no failed set constraint and at least 2 of the 3 expressions grounded-good (fits the request, natural, and backed by a podcast quote that code verified as the exact corpus slice and the judge found to show the use). Pass, expect=decline: no expressions and a note. Strict: as pass, with all 3 expressions grounded-good.
- Judge: an LLM judge, 3 votes per unit (expression, example, set), majority; not human gold.
- pass@3: share of tasks with at least one passing run; pass^3: share with all 3 passing; both over tasks with all 3 runs graded.
- Turns: model calls per attempt, the shared first stage included. Rounds: decision steps after the shared first stage (baseline revise_r, agent agent_r), from the trace.
- Latency p95: nearest rank, the ceil(0.95 * n)-th smallest. Tokens: chat input + output per attempt (embedding tokens excluded). Cost: list-price USD estimate per attempt.
- Empty answers: expect=answer attempts with no grounded-good expression.
- Paired comparison: per task, the mean over its graded runs; agent − baseline over the expect=answer tasks graded in both; units with an infrastructure failure in either system left out of both; percentile bootstrap over tasks, 4000 resamples, seed 7.
- First-stage state: from the shared first verification (validate_select_1); review = all 3 slots verified, recovery = fewer.
