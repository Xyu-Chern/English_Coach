# English Coach evaluation

200 distinct tasks, three paired attempts per system, 1,200 graded answers. Pooled counts span multiple models, judging configurations and corpus snapshots.

| Cohort | System | Accuracy | pass@3 | pass^3 | Flips | Mean turns | Mean / p95 latency (s) | Mean tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| original/ko | agent | 138/150 (92.0%) | 48/50 | 43/50 | 5 | 3.42 | 33.4 / 60.5 | 58,608 |
| original/ko | baseline | 133/150 (88.7%) | 48/50 | 39/50 | 9 | 3.25 | 26.1 / 51.7 | 40,332 |
| original/zh | agent | 91/150 (60.7%) | 43/50 | 19/50 | 24 | 2.66 | 94.4 / 251.2 | 27,866 |
| original/zh | baseline | 96/150 (64.0%) | 43/50 | 21/50 | 22 | 3.33 | 105.4 / 303.8 | 27,884 |
| original | agent | 229/300 (76.3%) | 91/100 | 62/100 | 29 | 3.04 | 63.9 / 172.1 | 43,237 |
| original | baseline | 229/300 (76.3%) | 91/100 | 60/100 | 31 | 3.29 | 65.8 / 226.5 | 34,108 |
| expansion/ko | agent | 117/150 (78.0%) | 46/50 | 30/50 | 16 | 2.97 | 356.0 / 1176.2 | 55,873 |
| expansion/ko | baseline | 125/150 (83.3%) | 47/50 | 36/50 | 11 | 3.61 | 375.6 / 1215.8 | 54,920 |
| expansion/zh | agent | 107/150 (71.3%) | 45/50 | 25/50 | 20 | 3.33 | 400.8 / 1109.2 | 65,247 |
| expansion/zh | baseline | 104/150 (69.3%) | 44/50 | 25/50 | 19 | 4.28 | 428.2 / 1295.0 | 67,898 |
| expansion | agent | 224/300 (74.7%) | 91/100 | 55/100 | 36 | 3.15 | 378.4 / 1152.7 | 60,560 |
| expansion | baseline | 229/300 (76.3%) | 91/100 | 61/100 | 30 | 3.95 | 401.9 / 1224.3 | 61,409 |
| all | agent | 453/600 (75.5%) | 182/200 | 117/200 | 65 | 3.10 | 221.1 / 1030.8 | 51,898 |
| all | baseline | 458/600 (76.3%) | 182/200 | 121/200 | 61 | 3.62 | 233.8 / 1032.1 | 47,758 |

Accuracy counts individual attempts. pass@3 counts tasks passing at least once, and pass^3 counts tasks passing every time. Flips count tasks with both passing and failing attempts. Turns count model calls including the shared first stage. Each system's latency measures its recorded time in the experiment, including any scheduling waits.

[All 200 tasks and their six verdicts](combined-200.tsv)

## Evidence

[Evaluation report (PDF)](report.pdf) · [Expansion replay, 100 tasks](expansion.html) · [Original Chinese replay, 50 tasks](https://phrase-room-coach.vercel.app/admin/evaluation/zh.html) · [Original Korean replay, 50 tasks](https://phrase-room-coach.vercel.app/admin/evaluation/ko.html) · [Machine-readable results](combined-200.json)

The 100 expansion tasks used the ChatGPT subscription through Codex with the local transcript corpus. Provider usage fields for this cohort count subscription-reported tokens, which can include harness context. Its observed latency includes waiting during parallel evaluation. Absolute token and latency figures are therefore best interpreted within each cohort.

## A traced failure

A learner carrying boxes wanted to ask someone to hold a door. On [attempt 1 of zh-ext-hold-door](expansion.html#zh-ext-hold-door/1), both systems started with one supported expression. The agent then searched for broad requests such as “could you.” At `repick_2_1` it paired a door-holding request with a speaker asking for five minutes of someone's time. At `replace_final_1` it chose a passage about helping someone who was stuck. All three quotes came from the transcripts, so `validate_pick_final` reported 3/3 verified. The semantic judge accepted only one as demonstrating the suggested use, below the two-expression threshold. The baseline revised one suggestion around “help me with,” finished with two accepted examples, and passed. The agent lost this attempt at quote selection: matching a general request for help left the specific teaching claim unsupported.
