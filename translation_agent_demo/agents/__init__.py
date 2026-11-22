"""Expression coach: up to three ranked English expressions, each backed by a verified podcast quote.

    from translation_agent_demo.agents import CoachDependencies, ExpressionCoach, answer_pair

    coach = ExpressionCoach(CoachDependencies(model=chat_model, search=search_corpus), "agent")
    result = coach.answer("<the learner's request>")
    both = answer_pair(CoachDependencies(model=chat_model, search=search_corpus), "<request>")
    both["baseline"], both["agent"]   # one first stage, then each system from its own copy

How a request flows:

    first stage (systems/first_stage.py)  candidates -> one search each -> select -> verify
          |                                = a draft of 3 slots; run once, copied to each system
          +-- baseline (systems/baseline.py)  a fixed workflow: code decides each next step
          +-- agent (systems/agent.py)        each turn the model reviews the draft and acts
          |
    assemble (tools/assemble.py)          verified slots first, no duplicates, at most 3

Both systems use the same tools (tools/), ceilings (systems/base.py) and verifier
(evidence.py); they differ only in who decides the next step: code or the model.

Both keep the verified-slot lock (systems/base.py): an example the first stage verified is final,
the continuation only fills slots without one, and a first stage that verified every slot ends the
request. The agent of the submitted evaluation, which could change verified examples, is
AgentPipeline(locked=False): ExpressionCoach(dependencies, AgentPipeline(locked=False)).

Layout:
    coach.py      answer a request: validate input, run the first stage and the system(s)
    systems/      the first stage, the shared base, the baseline and the agent
    tools/        search, select, change (repick/replace, guarded), validate, assemble
    prompts/      each model call's system prompt, by stage (first stage, baseline, agent)
    schemas/      the JSON each model call must return, by the same stages
    draft.py      the answer under construction (Slot, Draft)
    session.py    RequestSession: budgets, model calls, searches, trace; the carried first stage
    evidence.py   spans shown to the model and verification of the examples it picks
    structured.py strict JSON Schemas and item-by-item reply validation
    results.py    what the coach returns
    contracts.py  chat and search boundary types shared with the adapters
"""

from .coach import ExpressionCoach, answer_pair
from .systems import SYSTEMS, AgentPipeline, BaselinePipeline, ExpressionPipeline, system_for
from .protocol import ChatModel, ObservedChatModel, SearchCorpus
from .results import ExpressionItem, RunResult, SourceCitation, TraceSpan, Usage
from .session import Budget, CoachDependencies, CoachError, RequestSession, SessionLimits, SharedPrefix

__all__ = ["ExpressionCoach", "answer_pair", "CoachDependencies", "SessionLimits", "Budget", "RequestSession",
           "SharedPrefix", "CoachError", "ExpressionPipeline", "BaselinePipeline", "AgentPipeline", "SYSTEMS",
           "system_for", "RunResult", "ExpressionItem", "SourceCitation", "TraceSpan", "Usage", "ChatModel",
           "ObservedChatModel", "SearchCorpus"]
