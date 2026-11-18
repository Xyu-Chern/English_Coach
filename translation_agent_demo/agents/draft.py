"""The answer under construction: up to three slots, each an expression and, once verified, its example.

    Slot          one place in the answer: expression, key phrase, example (or why the last pick failed)
    Observation   one search and the spans (with refs) it showed the model
    Draft         the slots, the candidates outside the answer, every search so far, and the
                  verifier; each system works on its own deep copy

An example enters a slot only through Draft.attach, which asks the verifier (evidence.py).
"""

from dataclasses import dataclass, field, replace as copy_slot

from .evidence import ExampleVerifier, SpanCatalog
from .results import SourceCitation
from .schemas.prefix import Candidate

ANSWER_SIZE = 3


def expression_key(text: str) -> str:
    """Expressions that differ only in case, spacing or end punctuation are duplicates."""
    return " ".join(text.casefold().split()).strip(" .!?")


@dataclass
class Slot:
    """One place in the answer: an expression and, once verified, its example."""

    candidate: Candidate  # function and note come from here
    origin: int  # the candidate's rank in the first stage
    expression: str = ""  # may become the variant a verified example shows
    key_phrase: str = ""
    citation: SourceCitation | None = None
    ref: str | None = None
    search: str | None = None  # stage of the latest search for this slot's expression
    rejections: list[str] = field(default_factory=list)  # why the latest pick was rejected
    tried: list[str] = field(default_factory=list)  # expressions this slot held before
    moved_to_end: bool = False  # the guard (G1) kept an example doubted for its meaning; it is assembled last

    def __post_init__(self):
        self.expression = self.expression or self.candidate.expression
        self.key_phrase = self.key_phrase or self.candidate.key_phrase

    def status(self, index: int) -> dict:
        """The slot as a trace shows it after each validation."""
        cited = self.citation
        status = {"slot": index, "candidate": self.origin, "expression": self.expression,
                  "key_phrase": self.key_phrase, "status": "verified" if cited else "no_example", "ref": self.ref,
                  "quote": cited.quote if cited else None, "episode_title": cited.episode_title if cited else None,
                  "rejection_reasons": list(self.rejections)}
        return {**status, "moved_to_end": True} if self.moved_to_end else status

    def view(self, index: int) -> dict:
        """The slot as the agent sees it: its example, or why the last pick was rejected."""
        cited = self.citation
        example = {"ref": self.ref, "quote": cited.quote, "episode": cited.episode_title,
                   "source_use": cited.source_use, "adaptation": cited.adaptation} if cited else None
        view = {"slot": index, "expression": self.expression, "key_phrase": self.key_phrase,
                "function": self.candidate.function, "note": self.candidate.note, "example": example,
                "rejection_reasons": list(self.rejections)}
        return {**view, "moved_to_end": True} if self.moved_to_end else view


@dataclass
class Observation:
    """One search and the spans (with refs) it showed the model."""

    stage: str
    query: str
    key_phrase: str | None
    corpus_count: int | None  # whole-corpus chunks containing the key phrase; None without one
    spans: list[dict]

    def view(self) -> dict:
        """One search as every agent turn sees it (passages in decision_view)."""
        return {"search": self.stage, "query": self.query, "key_phrase": self.key_phrase,
                "corpus_count": self.corpus_count, "spans": self.spans}


@dataclass
class Draft:
    """The answer under construction. Each system works on its own deep copy."""

    question: str
    slots: list[Slot]
    feeds: list[int] | None = None
    decline: str | None = None  # the note when the request was declined
    alternatives: list[Candidate] = field(default_factory=list)  # candidates outside the answer
    catalog: SpanCatalog = field(default_factory=SpanCatalog)
    searches: dict[str, Observation] = field(default_factory=dict)

    def __post_init__(self):
        self.verifier = ExampleVerifier(self.catalog)

    @property
    def supported(self) -> int:
        return sum(slot.citation is not None for slot in self.slots)

    def latest(self, slot: Slot) -> Observation | None:
        return self.searches[slot.search] if slot.search else None

    def spans_of(self, slot: Slot) -> list[dict]:
        observation = self.latest(slot)
        return observation.spans if observation else []

    def corpus_count_of(self, slot: Slot) -> int | None:
        observation = self.latest(slot)
        return observation.corpus_count if observation else None

    def span_pool(self) -> list[dict]:
        """Every span seen so far, once each (the first ref that showed it), with the search that found it.

        The baseline's REVISE sees this, so it reads the same evidence the agent's passages hold."""
        pool, seen = [], set()
        for observation in self.searches.values():
            for span in observation.spans:
                key = self.catalog.get(span["ref"]).key
                if key not in seen:
                    seen.add(key)
                    pool.append({**span, "search": observation.stage})
        return pool

    def attach(self, index: int, ref: str | None, *, expression: str, key_phrase: str, wording: str | None,
               source_use: str | None, adaptation: str | None) -> None:
        """Verify a pick for a slot: a verified pick becomes its example, a rejected one leaves its reasons."""
        slot = self.slots[index]
        before = len(self.verifier.rejected)
        citation = self.verifier.verify(ref, slot=index, wording=wording, expression=expression, key_phrase=key_phrase,
                                        source_use=source_use, adaptation=adaptation)
        slot.rejections = [rejection["reason"] for rejection in self.verifier.rejected[before:]]
        if citation is not None:
            slot.citation, slot.ref, slot.expression, slot.key_phrase = citation, ref, expression, key_phrase
            slot.moved_to_end = False  # a newly verified example is no longer the doubted one

    def drop_example(self, index: int) -> None:
        slot = self.slots[index]
        if slot.citation is not None:
            self.verifier.release(slot.citation)
        slot.citation, slot.ref, slot.rejections = None, None, []

    def replace(self, index: int, candidate: Candidate) -> None:
        """A new expression takes the slot's place and rank; the old one is remembered as tried."""
        self.drop_example(index)
        slot = self.slots[index]
        slot.tried.append(slot.expression)
        slot.candidate, slot.expression, slot.key_phrase, slot.search = (candidate, candidate.expression,
                                                                         candidate.key_phrase, None)

    def checkpoint(self, index: int) -> Slot:
        """A copy of the slot as it is, to restore if a change loses its verified example (G1)."""
        slot = self.slots[index]
        return copy_slot(slot, rejections=list(slot.rejections), tried=list(slot.tried))

    def restore(self, index: int, saved: Slot) -> Slot:
        """Put a checkpointed slot back; its example's span is claimed again."""
        current = self.slots[index]
        if current.citation is not None:
            self.verifier.release(current.citation)
        if saved.citation is not None:
            self.verifier.claim(saved.citation)
        self.slots[index] = saved
        return saved

    def narrow(self) -> None:
        """Keep the answer's slots: verified first in rank order, then unsupported, no duplicates.

        The other candidates stay visible as alternatives; their examples' spans are released."""
        kept, seen = [], set()
        for slot in sorted(self.slots, key=lambda s: s.citation is None):  # stable: rank order in each group
            if len(kept) < ANSWER_SIZE and expression_key(slot.expression) not in seen:
                kept.append(slot)
                seen.add(expression_key(slot.expression))
        for slot in self.slots:
            if all(slot is not k for k in kept):
                if slot.citation is not None:
                    self.verifier.release(slot.citation)
                self.alternatives.append(slot.candidate)
        self.slots = kept
