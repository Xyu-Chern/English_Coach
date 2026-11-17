"""From retrieved passages to verified examples.

The model only ever sees numbered sentence spans (refs) of retrieved passages and
answers with a ref plus the wording it claims the learner can reuse. Code then:
- copies the exact quote and up to 200 characters of context on each side,
- checks the reusable wording occurs verbatim in that span,
- checks the wording and the expression share the expression's key phrase,
- lets each span back at most one expression (even if it was shown under two refs).
Each span shown says whether it contains the search's key phrase (has_key_phrase), the
same literal test the corpus count uses, so every decision call reads the same evidence.

Whether a key phrase is one contiguous piece of an expression, and whether a wording covers
it, are checked on normalize_for_match text: case, hyphens and dashes ("whack-a-mole"
and "whack a mole", "trade-off" and "trade off") and outer punctuation do not matter.
"""

import re
from dataclasses import dataclass, field

from .contracts import CorpusSearchHit
from .results import SourceCitation

SPANS_PER_PASSAGE = 12  # Keeps each passage's share of the prompt small.
SNIPPET_CHARS = 160  # A trace shows this much of each hit, enough to recognise it.
# Approved shows a learner may restrict examples to (Podcast Index feed IDs in the corpus).
SHOW_FEEDS = {"go_time": 218840, "js_party": 403674, "the_changelog": 542376}
SHOW_NAMES = {feed: name for name, feed in SHOW_FEEDS.items()}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_DASHES = re.compile(r"[-‐‑‒–—―]")
_OUTER_PUNCTUATION = " .,!?;:\"'…()[]{}"


def source_length(hit: CorpusSearchHit) -> int:
    """How much of the passage text is citable source (appended test material is not)."""
    value = hit.source_text_length
    if value is None:
        return len(hit.text)
    if type(value) is not int or not 0 <= value <= len(hit.text):
        raise ValueError("Invalid trusted source boundary.")
    return value


def quote_spans(text: str) -> list[tuple[int, int]]:
    """Sentence-like slices of at most 800 characters (a display heuristic, at most 64)."""
    spans: list[tuple[int, int]] = []
    boundaries = [0, *(match.end() for match in re.finditer(r"(?<=[.!?])[ \t]+|\n+", text)), len(text)]
    for start, end in zip(boundaries, boundaries[1:]):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        while start < end:
            stop = min(end, start + 800)
            if stop < end:
                space = text.rfind(" ", start + 1, stop + 1)
                if space > start:
                    stop = space
            if (start, stop) not in spans:
                spans.append((start, stop))
            if len(spans) >= 64:
                return spans
            start = stop
            while start < end and text[start].isspace():
                start += 1
    return spans


def hit_summary(hit: CorpusSearchHit, phrase: str | None) -> dict:
    """What a trace keeps of one search hit: its identity, show and a snippet around the key phrase."""
    text = hit.text[:source_length(hit)]
    at = text.translate(_QUOTES).casefold().find(phrase.casefold()) if phrase else -1
    start = max(0, at - SNIPPET_CHARS // 4) if at >= 0 else 0
    return {"chunk_id": str(hit.chunk_id), "source_key": hit.source_key, "show": SHOW_NAMES.get(hit.feed_id),
            "episode_title": hit.episode_title, "snippet": " ".join(text[start:start + SNIPPET_CHARS].split())}


def make_citation(hit: CorpusSearchHit, start: int, end: int, source_use: str, adaptation: str) -> SourceCitation:
    """Code copies the exact quote, +-200 characters of context and the provenance."""
    length = source_length(hit)
    context_start, context_end = max(0, start - 200), min(length, end + 200)
    return SourceCitation(
        chunk_id=hit.chunk_id, document_id=hit.document_id, build_id=hit.build_id,
        source_key=hit.source_key, episode_title=hit.episode_title,
        episode_url=hit.episode_url, transcript_url=hit.transcript_url,
        quote=hit.text[start:end], quote_start_char=start, quote_end_char=end,
        source_context=hit.text[context_start:context_end],
        context_start_char=context_start, context_end_char=context_end,
        source_use=source_use, adaptation=adaptation,
        chunk_start_ms=hit.start_ms, chunk_end_ms=hit.end_ms, rights_status=hit.rights_status,
        rights_review_url=hit.rights_review_url, license_id=hit.license_id,
        license_url=hit.license_url, attribution=hit.attribution,
    )


def normalize_phrase(phrase: str | None) -> str | None:
    """A key phrase as searched: straight quotes, no surrounding punctuation; None if empty."""
    return (phrase or "").translate(_QUOTES).strip(" .,!?;:\"'…") or None


def _fold(text: str) -> str:
    return " ".join(text.translate(_QUOTES).casefold().split())


def contains_phrase(text: str, phrase: str | None) -> bool:
    """The phrase occurs literally: ignoring case, quote style and spacing, on word boundaries."""
    needle = _fold(phrase or "")
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", _fold(text)) is not None


def normalize_for_match(text: str | None) -> str:
    """Text as key-phrase checks compare it: casefolded, straight quotes, hyphens and dashes as
    spaces, outer punctuation trimmed, whitespace collapsed."""
    folded = _DASHES.sub(" ", (text or "").translate(_QUOTES).casefold())
    return " ".join(folded.split()).strip(_OUTER_PUNCTUATION)


def matches_phrase(text: str, phrase: str | None) -> bool:
    """contains_phrase on normalize_for_match text: the phrase occurs on word boundaries."""
    needle = normalize_for_match(phrase)
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", normalize_for_match(text)) is not None


def key_phrase_contiguous(key_phrase: str, expression: str) -> bool:
    """A key phrase is one contiguous piece of its expression, never gapped like "treat ... as"."""
    return matches_phrase(expression, key_phrase)


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", normalize_for_match(text)))


def covers(key_phrase: str, text: str) -> bool:
    """At least 60% of the key phrase's words occur in the text."""
    key_words = words(key_phrase)
    return bool(key_words) and len(key_words & words(text)) >= 0.6 * len(key_words)


def occurs_in(wording: str, span_text: str) -> bool:
    """Verbatim containment, ignoring case, quote style and whitespace; must contain a letter."""
    def normalized(text: str) -> str:
        return " ".join(text.translate(_QUOTES).casefold().split())

    return normalized(wording) in normalized(span_text) and re.search(r"[^\W\d_]", wording) is not None


@dataclass(frozen=True)
class Span:
    hit: CorpusSearchHit
    start: int
    end: int

    @property
    def text(self) -> str:
        return self.hit.text[self.start:self.end]

    @property
    def key(self) -> tuple:
        return (self.hit.chunk_id, self.start, self.end)


class SpanCatalog:
    """Every span shown to the model in one request, addressable by its ref."""

    def __init__(self):
        self.spans: dict[str, Span] = {}

    def present(self, hits: list[CorpusSearchHit], prefix: str, key_phrase: str | None = None) -> list[dict]:
        """Number the spans of each passage; spans containing the key phrase come first and say so."""
        shown = []
        for rank, hit in enumerate(hits, 1):
            spans = [(start, end, contains_phrase(hit.text[start:end], key_phrase))
                     for start, end in quote_spans(hit.text[:source_length(hit)])]
            spans.sort(key=lambda span: not span[2])  # stable: text order within each group
            for number, (start, end, has_key_phrase) in enumerate(spans[:SPANS_PER_PASSAGE], 1):
                ref = f"{prefix}h{rank}s{number}"
                self.spans[ref] = Span(hit, start, end)
                shown.append({"ref": ref, "text": hit.text[start:end], "has_key_phrase": has_key_phrase,
                              "episode_title": hit.episode_title})
        return shown

    def get(self, ref: str) -> Span | None:
        return self.spans.get(ref)


@dataclass
class ExampleVerifier:
    """Turns a model's pick into a citation, or records why it was rejected."""

    catalog: SpanCatalog
    used: set[tuple] = field(default_factory=set)  # (chunk_id, start, end) of spans already cited
    rejected: list[dict] = field(default_factory=list)

    def verify(self, ref: str | None, *, slot: int | None = None, wording: str | None, expression: str,
               key_phrase: str | None, source_use: str | None, adaptation: str | None) -> SourceCitation | None:
        """slot only labels a rejection, so a trace can show which place in the answer it concerned."""
        if ref is None:
            return None
        span = self.catalog.get(ref)
        if span is None or span.key in self.used:  # the same span can be shown under several refs
            return self._reject(slot, ref, "unknown_or_reused_ref")
        if not (source_use and source_use.strip() and adaptation and adaptation.strip()):
            return self._reject(slot, ref, "explanation_missing")
        if not (wording and occurs_in(wording, span.text)):
            return self._reject(slot, ref, "reusable_wording_not_in_span")
        if not (key_phrase and covers(key_phrase, wording) and covers(key_phrase, expression)):
            return self._reject(slot, ref, "wording_lacks_key_phrase")
        self.used.add(span.key)
        return make_citation(span.hit, span.start, span.end, source_use, adaptation)

    def release(self, citation: SourceCitation) -> None:
        """A dropped example frees its span, so another place in the answer may cite it."""
        self.used.discard((citation.chunk_id, citation.quote_start_char, citation.quote_end_char))

    def claim(self, citation: SourceCitation) -> None:
        """A restored example takes its span back, so no other place may cite it."""
        self.used.add((citation.chunk_id, citation.quote_start_char, citation.quote_end_char))

    def take_rejections(self) -> list[dict]:
        rejected, self.rejected = self.rejected, []
        return rejected

    def _reject(self, slot: int | None, ref: str, reason: str) -> None:
        self.rejected.append({"slot": slot, "ref": ref, "reason": reason})
        return None
