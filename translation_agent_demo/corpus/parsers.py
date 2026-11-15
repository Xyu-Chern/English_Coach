"""Parse acquired HTML/SRT/Markdown without rewriting publisher wording."""

import json
import re
from html import unescape
from html.parser import HTMLParser

from .models import CorpusParseError, Cue, ParsedTranscript

PARSER_VERSION = "html-srt-markdown-v3"

_TIME = r"\d{1,6}:[0-5]\d(?::[0-5]\d)?(?:[.,]\d{1,3})?"
_BRACKET_TIME = re.compile(rf"\[({_TIME})\]")
_NAMED_TIME = re.compile(rf"^(.{{1,100}}?)\s+\(({_TIME})\):?$")
_TIME_LABEL = re.compile(rf"^\[({_TIME})\](?:\s*[-–—]\s*(.{{1,100}}))?$")
_SRT_TIME = r"\d{2,6}:[0-5]\d:[0-5]\d[,.]\d{3}"
_SRT_TIMING = re.compile(rf"^({_SRT_TIME})\s*-->\s*({_SRT_TIME})$")
_SRT_SIGNATURE = re.compile(rf"^{_SRT_TIME}\s*-->", re.MULTILINE)
_HTML_SIGNATURE = re.compile(r"</?(?:html|body|p|div|cite|time|h[1-6]|article|section|br|span)\b", re.I)
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_SRT_TYPES = {"application/x-subrip", "application/srt", "text/srt", "text/x-srt"}
_MARKDOWN_SPEAKER = re.compile(r"^\*\*([^*:\r\n]{1,100}):\*\*[ \t]*")
_MARKDOWN_TIME = re.compile(r"^\[(\d{2,6}:[0-5]\d:[0-5]\d(?:\.\d{3})?)\](?=\s|$)")
_PAGE_ERROR = re.compile(
    r"^(?:(?:403|404|410|429|500|502|503|504)\b|access denied\b|forbidden\b|"
    r"not found\b|page not found\b|internal server error\b|bad gateway\b|"
    r"service unavailable\b|just a moment\b|attention required\b|"
    r"verify (?:you are|that you are) human\b|sign in required\b)", re.I,
)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _milliseconds(value: str) -> int:
    whole, _, fraction = value.replace(",", ".").partition(".")
    parts = [int(part) for part in whole.split(":")]
    seconds = parts[-1] + 60 * parts[-2]
    if len(parts) == 3:
        seconds += 3600 * parts[0]
    return seconds * 1000 + int(fraction.ljust(3, "0") or "0")


class _HTMLBlocks(HTMLParser):
    """Retain paragraphs/headings and explicit metadata, excluding page chrome."""

    _SKIP = {"head", "script", "style", "nav", "footer", "header", "form", "button",
             "svg", "canvas", "iframe", "object", "noscript", "template", "aside"}
    _BLOCK = {"p", "div", "li", "ul", "ol", "section", "article", "blockquote", "pre",
              "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, int | None]] = []
        self.parts: list[str] = []
        self.title: list[str] = []
        self.in_title = False
        self.skipped: str | None = None
        self.skip_depth = 0
        self.kind = "text"
        self.start_ms: int | None = None
        self.double_quote_open = False
        self.capture: tuple[str, str, list[str]] | None = None
        self.capture_depth = 0

    def flush(self) -> None:
        text = "".join(self.parts)
        if text.strip():
            self.blocks.append((self.kind, text, self.start_ms))
        self.parts = []
        self.start_ms = None
        self.double_quote_open = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if self.skipped:
            if tag == self.skipped:
                self.skip_depth += 1
            return
        if tag in self._SKIP:
            self.flush()
            self.skipped, self.skip_depth = tag, 1
            return
        if self.capture:
            if tag == self.capture[0]:
                self.capture_depth += 1
            if tag == "br":
                self.capture[2].append(" ")
            return
        if tag in self._BLOCK:
            self.flush()
            self.kind = "heading" if re.fullmatch(r"h[1-6]", tag) else "text"
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"cite", "time"} and not _clean("".join(self.parts)):
            self.capture = (tag, tag, [])
            self.capture_depth = 1
        elif tag == "span" and "data-t" in dict(attrs):
            value = dict(attrs)["data-t"] or ""
            if self.start_ms is None and re.fullmatch(r"\d{1,9}(?:\.\d{1,3})?", value):
                seconds, _, fraction = value.partition(".")
                self.start_ms = int(seconds) * 1000 + int(fraction.ljust(3, "0") or "0")
            self.capture = (tag, "word", [])
            self.capture_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if self.skipped:
            if tag == self.skipped:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skipped = None
            return
        if self.capture:
            if tag == self.capture[0]:
                self.capture_depth -= 1
                if self.capture_depth == 0:
                    self._finish_capture()
            return
        if tag in self._BLOCK:
            self.flush()
            self.kind = "text"

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        if self.skipped:
            return
        # HTML source formatting is whitespace; only <br> makes a literal line break.
        data = data.replace("\n", " ")
        if self.capture:
            self.capture[2].append(data)
        else:
            self.parts.append(data)

    def _finish_capture(self) -> None:
        assert self.capture is not None
        _, kind, parts = self.capture
        self.capture = None
        text = _clean("".join(parts))
        if not text:
            return
        if kind == "cite":
            self.blocks.append(("cite", text.rstrip(":"), None))
        elif kind == "time" and re.fullmatch(_TIME, text):
            self.blocks.append(("time", "", _milliseconds(text)))
        elif kind == "word":
            # Word spans may touch in HTML or be separated by formatting newlines.
            while self.parts and not self.parts[-1].rstrip():
                self.parts.pop()
            if self.parts:
                self.parts[-1] = self.parts[-1].rstrip()
                previous = self.parts[-1][-1:]
                closes = text[0] in ",.;:!?)]}”’" or re.match(r"'(?:s|m|re|ve|ll|d|t)\b", text)
                closes = closes or (text.startswith('"') and self.double_quote_open)
                opens = previous in "([{“‘" or (previous == '"' and self.double_quote_open)
                if not closes and not opens:
                    self.parts.append(" ")
            self.parts.append(text)
            if text.count('"') % 2:
                self.double_quote_open = not self.double_quote_open
        else:
            self.parts.append("".join(parts))

    def finish(self) -> list[tuple[str, str, int | None]]:
        self.close()
        if self.capture:
            # An unclosed presentation tag must not silently discard its body.
            self._finish_capture()
        self.flush()
        return self.blocks


def _parse_html(text: str) -> ParsedTranscript:
    parser = _HTMLBlocks()
    if re.search(r"</?[A-Za-z][^>]*>|<!DOCTYPE\b", text, re.I):
        parser.feed(text)
        blocks = parser.finish()
    else:
        blocks = [("text", unescape(text), None)]  # Some publishers label plain text as HTML.
    first_heading = next((value for kind, value, _ in blocks if kind == "heading"), "")
    first_text = next((value for kind, value, _ in blocks if kind == "text"), "")
    if any(_PAGE_ERROR.match(_clean(value)) for value in ("".join(parser.title), first_heading, first_text)):
        raise CorpusParseError("invalid_format")

    cues: list[Cue] = []
    speaker: str | None = None
    pending_start: int | None = None
    cite_only = False

    def emit(value: str) -> None:
        nonlocal pending_start
        value = _clean(value)
        if value:
            cues.append(Cue(len(cues), value, start_ms=pending_start, speaker=speaker))
            pending_start = None

    def paragraph(lines: list[str]) -> None:
        nonlocal pending_start
        value = " ".join(lines)
        offset = 0
        for match in _BRACKET_TIME.finditer(value):
            emit(value[offset:match.start()])
            pending_start = _milliseconds(match[1])
            offset = match.end()
        emit(value[offset:])

    for kind, value, start in blocks:
        if kind == "cite":
            speaker, cite_only = value, kind == "cite"
            continue
        if kind == "time":
            pending_start = start
            continue
        if kind == "heading":
            if _clean(value):
                cues.append(Cue(len(cues), _clean(value)))
            continue
        if pending_start is None:
            pending_start = start
        lines: list[str] = []
        for line in value.splitlines():
            line = _clean(line)
            named_time, time_label = _NAMED_TIME.fullmatch(line), _TIME_LABEL.fullmatch(line)
            if not line or named_time or time_label:
                paragraph(lines)
                lines = []
                if named_time:
                    speaker, pending_start = named_time[1], _milliseconds(named_time[2])
                elif time_label:
                    pending_start = _milliseconds(time_label[1])
                    if time_label[2]:
                        speaker = time_label[2]
            else:
                lines.append(line)
        paragraph(lines)
        if cite_only:
            speaker, cite_only = None, False
    if not cues:
        raise CorpusParseError("empty_transcript")
    return ParsedTranscript("html", tuple(cues))


def _parse_srt(text: str) -> ParsedTranscript:
    cues: list[Cue] = []
    for block in re.split(r"\n[ \t]*\n", text.strip()):
        if not block.strip():
            continue
        lines = block.strip().splitlines()
        if len(lines) < 3 or not re.fullmatch(r"[0-9]+", lines[0].strip()):
            raise CorpusParseError("invalid_format")
        timing = _SRT_TIMING.fullmatch(lines[1].strip())
        if timing is None or any(_SRT_SIGNATURE.match(line.strip()) for line in lines[2:]):
            raise CorpusParseError("invalid_format")
        start, end = _milliseconds(timing[1]), _milliseconds(timing[2])
        body = re.sub(r"</?(?:i|b|u|font)\b[^>]*>", "", " ".join(lines[2:]), flags=re.I)
        body = _clean(unescape(re.sub(r"<br\s*/?>", " ", body, flags=re.I)))
        if end < start or not body:
            raise CorpusParseError("invalid_format")
        cues.append(Cue(len(cues), body, start_ms=start, end_ms=end))
    if not cues:
        raise CorpusParseError("empty_transcript")
    return ParsedTranscript("srt", tuple(cues))


def _parse_markdown(text: str) -> ParsedTranscript:
    """Parse transcript paragraphs, not arbitrary Markdown presentation.

    Only a paragraph's leading **Speaker:** is metadata; unlabelled paragraphs
    have no inferred speaker. Bracket escapes are rendered as literal brackets.
    Other markup and all timestamp text stay in the cue. A leading explicit
    [HH:MM:SS] or [HH:MM:SS.mmm] also supplies start_ms; no end time is inferred.
    In particular, MM:SS remains text without being guessed as a cue timestamp.
    """
    cues: list[Cue] = []
    for paragraph in re.split(r"\n[ \t]*\n", text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        body, speaker = paragraph, None
        label = _MARKDOWN_SPEAKER.match(paragraph)
        if label and _clean(label[1]) and paragraph[label.end():].strip():
            speaker = _clean(label[1])
            body = paragraph[label.end():]
        # The publisher escapes brackets in timestamps and stage directions.
        # Rendering these escapes does not remove the enclosed source wording.
        body = _clean(re.sub(r"\\([\[\]])", r"\1", body))
        timing = _MARKDOWN_TIME.match(body)
        cues.append(Cue(
            len(cues), body, speaker=speaker,
            start_ms=_milliseconds(timing[1]) if timing else None,
        ))
    if not cues:
        raise CorpusParseError("empty_transcript")
    return ParsedTranscript("markdown", tuple(cues))


def parse_transcript(
    text: str, *, declared_type: str | None = None, content_type: str | None = None,
) -> ParsedTranscript:
    """Accept HTML/SRT/Markdown evidence and declared text served as plain text.

    Markdown requires an explicit text/markdown MIME declaration; its syntax is
    never inferred from unknown plain text. JSON and WebVTT remain unsupported.
    Malformed SRT fails as a document rather than dropping nonempty blocks.
    Headings and unrecognized prose remain attributable source text.
    """
    if not isinstance(text, str) or any(value is not None and not isinstance(value, str)
                                        for value in (declared_type, content_type)):
        raise CorpusParseError("invalid_format")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise CorpusParseError("empty_transcript")
    declared, actual = ((value or "").split(";", 1)[0].strip().lower()
                        for value in (declared_type, content_type))
    types = {declared, actual}
    if text.lstrip().startswith("WEBVTT") or any(value == "text/vtt" or value.endswith("/json") or value.endswith("+json")
                                               for value in types):
        raise CorpusParseError("unsupported_format")
    if text.lstrip().startswith(("{", "[")):
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            pass
        else:
            raise CorpusParseError("unsupported_format")
    if "text/markdown" in types:
        if actual not in {"", "text/plain", "text/markdown"} or declared not in {"", "text/plain", "text/markdown"}:
            raise CorpusParseError("invalid_format")
        return _parse_markdown(text)
    if types & _SRT_TYPES or _SRT_SIGNATURE.search(text):
        return _parse_srt(text)
    if types & _HTML_TYPES or _HTML_SIGNATURE.search(text):
        return _parse_html(text)
    raise CorpusParseError("unsupported_format")
