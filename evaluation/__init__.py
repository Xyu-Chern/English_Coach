"""Offline evaluation of the expression coach: baseline vs agent (entry point: python -m evaluation.eval).

    eval.py             the command line: tasks, run, grade, report, review, all
    tasks.py            the 50 tasks (data/tasks.jsonl) and the frozen corpus
    runner.py           every task x run, both systems from one shared first stage, resumable, recorded for replay
    live.py             the paid dependencies: chat model, query embeddings, verified snapshot
    snapshot_search.py  the coach's search tool served from the snapshot
    recording.py        records each model call of an attempt
    grader.py           three-vote LLM judging of each answer, and the task pass rule
    judging.py          judge calls, the resumable vote log and majority
    report.py           results tables (accuracy, turns, latency, tokens, pass@3, pass^3) and one log per system
    viewer.py           report/review.html: every attempt side by side
    freeze.py           create and verify a corpus snapshot from the live database
    snapshot_store.py   import a snapshot into an isolated schema and search it
    costs.py            list-price cost estimates from reported usage
"""
