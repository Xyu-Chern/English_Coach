"""The evaluation tasks (data/tasks.jsonl) and the frozen corpus they are run against.

50 tasks for this submission; the harness accepts more (e.g. 200). One line of the file is one
task: one learner request plus what a good answer must do. The coach systems read only
`question`; every other field is for grading and for human readers.

Fields, in file order:

    id           unique task id (scheme below)
    type         "rubric" for a task that should be answered (expect = answer), "unanswerable"
                 for a task the coach must decline (expect = decline or no_examples)
    question     the learner's request, exactly as the systems receive it (Korean; one edge
                 task is English)
    question_en  an English rendering of the request with its situation and every explicit
                 constraint; quoted English phrases are kept as written; for edge tasks it also
                 says what the input looks like (typos, one word, mixed languages, ...)
    rubric       2-4 short English checks a reader can apply to an answer: what each expression
                 must say or do, each explicit constraint, and that each expression has a real
                 podcast quote that shows this use (for unanswerable tasks: decline and why, and
                 offer nothing). A summary of `intended` and the judge's checks; no judge reads it
    language     the language of `question`: "ko" or "en"
    group        regular | edge (unusual input) | unanswerable (must be declined)
    input_type   regular tasks only, what the learner asks for:
                     specific  a specific message to say (idiom tasks are specific too)
                     function  a conversational job, e.g. disagree politely; any valid way works
                     draft     a better version of the learner's own English sentence
                     usage     how a given English phrase is used
                     compare   the difference between two English phrases
    condition    regular tasks: context (a situation is given), constraint (an explicit
                 constraint is given) or plain (neither); edge and unanswerable tasks: the case
    category     "<input_type>/<condition>" for regular tasks, "<group>/<condition>" otherwise
    constraint   the kind of explicit constraint, only when condition = constraint: include_word,
                 avoid_word, length, register, no_literal, keep_meaning, required_form
    show         a show the learner limited the quotes to (no task in this set has one)
    expect       answer        up to three good, quote-backed expressions
                 decline       no expressions and a short note why (source not in the corpus,
                               out of scope, prompt injection, other users' data, ...)
                 no_examples   no quotes and a note that none are available (no task uses it)
    marker       a string an injected instruction asks for; it must never appear in the answer
    intended     Korean: what a good answer does, including every explicit constraint

Grading (evaluation/grader.py). The LLM judge reads `question` and `intended`, never
`question_en` or `rubric`, so these two fields must stay byte-identical: cached judge votes are
keyed on them. Per expression the judge checks that it fits the request and is natural; per
quote, that the verified corpus quote really shows that use; per set, that the set meets the
request's explicit set constraints (e.g. one question-form example). An answer task passes
when at least 2 of its (up to) 3 expressions are good and quote-backed and no set constraint
fails. A decline task passes when the answer offers no expressions and gives a short note.
Any task fails if its `marker` appears in the answer.

Id scheme (the "ko-" prefix names the Korean task set):

    ko-<kind>-<condition>-<n>   regular tasks
        kind:      spec (specific), func (function), draft, usage, cmp (compare);
                   spec-idiom = a specific message given as a Korean idiom
        condition: ctx (context), con (constraint), plain
        n:         the task's number within its kind and condition; gaps (no con-3) are
                   tasks removed before this set was fixed
    ko-edge-<case>              edge input; the case is the condition, e.g. typo_jamo, one_word,
                                english_only (its question is English, language "en")
    ko-unans-<case>             unanswerable; the case is the condition, e.g. injection, source_tv

    Example: ko-spec-ctx-1 = Korean set, a specific message to say, given with a situation,
    task 1 of that kind; ko-spec-idiom-con-2 = an idiom to say, with a constraint, task 2.

"""

import gzip
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DATA = Path(__file__).resolve().parent / "data"
TASKS = DATA / "tasks.jsonl"
GROUPS = ("regular", "edge", "unanswerable")
INPUT_TYPES = ("specific", "function", "draft", "usage", "compare")
CONDITIONS = ("context", "constraint", "plain")
TYPE_OF_EXPECT = {"answer": "rubric", "decline": "unanswerable", "no_examples": "unanswerable"}
MIN_EDGE, MIN_UNANSWERABLE = 3, 2


@dataclass(frozen=True)
class EvalTask:
    id: str
    type: Literal["rubric", "unanswerable"]
    question: str
    question_en: str
    rubric: tuple[str, ...]
    language: Literal["ko", "en"]
    group: Literal["regular", "edge", "unanswerable"]
    input_type: str | None
    condition: str
    category: str
    constraint: str | None
    show: str | None
    expect: Literal["answer", "no_examples", "decline"]
    marker: str | None
    intended: str

    def __post_init__(self):
        def text(value) -> bool:
            return isinstance(value, str) and bool(value.strip())

        if not text(self.id):
            raise ValueError(f"{self.id!r}: the id must be a nonblank string.")
        for name in ("question", "question_en", "intended", "condition", "category"):
            if not text(getattr(self, name)):
                raise ValueError(f"{self.id}: {name} must be a nonblank string.")
        if isinstance(self.rubric, str) or not isinstance(self.rubric, (list, tuple)):
            raise ValueError(f"{self.id}: rubric must be a list of strings.")
        object.__setattr__(self, "rubric", tuple(self.rubric))
        if not self.rubric or not all(text(item) for item in self.rubric):
            raise ValueError(f"{self.id}: rubric must hold at least one nonblank check.")
        if self.language not in ("ko", "en") or self.group not in GROUPS:
            raise ValueError(f"{self.id}: unknown language {self.language!r} or group {self.group!r}.")
        if self.expect not in TYPE_OF_EXPECT:
            raise ValueError(f"{self.id}: unknown expectation {self.expect!r}.")
        if self.type != TYPE_OF_EXPECT[self.expect]:
            raise ValueError(f"{self.id}: expect {self.expect!r} needs type {TYPE_OF_EXPECT[self.expect]!r}, "
                             f"not {self.type!r}.")
        if self.group == "regular":
            if self.input_type not in INPUT_TYPES or self.condition not in CONDITIONS:
                raise ValueError(f"{self.id}: a regular task needs one of {INPUT_TYPES} and of {CONDITIONS}.")
            if (self.constraint is not None) != (self.condition == "constraint"):
                raise ValueError(f"{self.id}: a constraint kind is set exactly when condition is 'constraint'.")
        elif self.input_type is not None or self.constraint is not None:
            raise ValueError(f"{self.id}: only regular tasks have an input_type or a constraint.")
        if self.category != f"{self.input_type if self.group == 'regular' else self.group}/{self.condition}":
            raise ValueError(f"{self.id}: category {self.category!r} does not match group, input_type and condition.")


def load_tasks(path: Path = TASKS) -> list[EvalTask]:
    """Every task in the file, validated; unknown or missing fields and duplicate ids are refused."""
    tasks = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            tasks.append(EvalTask(**json.loads(line)))
        except TypeError as error:  # a missing or unknown field
            raise ValueError(f"{path}:{number}: {error}") from error
    duplicates = sorted(i for i, n in Counter(t.id for t in tasks).items() if n > 1)
    if duplicates:
        raise ValueError(f"{path}: duplicate task ids {duplicates}.")
    return tasks


def summarize(tasks: list[EvalTask]) -> dict:
    """Counts by group, type, expectation and category, and the assignment's checks.

    The task count is reported, not checked (50 for this submission; more is fine).
    Problems: fewer than 3 edge or 2 unanswerable tasks, duplicate ids. Each EvalTask has
    already validated its own fields, including that its type matches its expectation."""
    groups = Counter(t.group for t in tasks)
    problems = []
    if groups["edge"] < MIN_EDGE:
        problems.append(f"at least {MIN_EDGE} edge cases are required, found {groups['edge']}")
    if groups["unanswerable"] < MIN_UNANSWERABLE:
        problems.append(f"at least {MIN_UNANSWERABLE} unanswerable tasks are required, found {groups['unanswerable']}")
    duplicates = sorted(i for i, n in Counter(t.id for t in tasks).items() if n > 1)
    if duplicates:
        problems.append(f"duplicate task ids: {duplicates}")
    return {"tasks": len(tasks), "groups": dict(groups), "types": dict(Counter(t.type for t in tasks)),
            "expect": dict(Counter(t.expect for t in tasks)),
            "categories": dict(Counter(t.category for t in tasks)), "problems": problems}


class Corpus:
    """The frozen transcript snapshot used for grading (chunks and documents by id)."""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        value = json.loads(gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw)
        self.chunks = {str(c["chunk_id"]): c for c in value["chunks"]}
        self.documents = {str(d["document_id"]): d for d in value["documents"]}
        if len(self.chunks) != len(value["chunks"]) or len(self.documents) != len(value["documents"]):
            raise ValueError("Corpus contains duplicate chunk or document IDs.")
