"""Fetch one selected episode's transcript body, keeping its source metadata.

Bodies remain unparsed UTF-8 text, including timestamps or publisher HTML.
Acquiring a body does not establish permission to reuse it in the corpus.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .podcast_index import _NoRedirect, parse_retry_after_seconds
from .changelog_transcripts import transcript_reference as changelog_transcript_reference

MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 15  # Per blocking network operation, not an overall deadline.


class PodcastTranscriptError(Exception):
    """An acquisition failure without credentials or upstream body in its message."""

    def __init__(
        self, message: str, *, status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class PodcastTranscript:
    feed_id: int
    episode_id: int
    episode_title: str
    episode_url: str | None
    transcript_url: str
    declared_type: str | None  # Podcast Index's format hint, e.g. application/srt.
    content_type: str | None  # Actual HTTP header; sometimes application/octet-stream.
    text: str = field(repr=False)  # Preserve cues/line breaks; avoid printing the full body.


def select_corpus_transcript(
    episode: dict[str, Any], *, published_changelog_episodes: frozenset[int] | None = None,
) -> tuple[str, str | None]:
    """Choose one supported English reference without making any HTTP requests.

    Prefer timed SRT, then explicit Markdown, then HTML. Unknown legacy MIME
    hints may still be sniffed by the parser; explicitly unsupported formats are
    skipped. Changelog uses its separately licensed transcript repository.
    """
    alternate = changelog_transcript_reference(episode, published_numbers=published_changelog_episodes)
    if alternate is not None:
        return alternate
    entries = episode.get("transcripts")
    if not entries:
        return _select_transcript(episode, 0)
    if not isinstance(entries, list):
        raise PodcastTranscriptError("Episode transcripts must be an array or null.")
    ranks = {"application/x-subrip": 0, "application/srt": 0, "text/srt": 0, "text/x-srt": 0,
             "text/markdown": 1, "text/html": 2, "application/xhtml+xml": 2,
             "": 3, "text/plain": 3, "application/octet-stream": 3}
    candidates = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        language = entry.get("language")
        if language is not None and (
            not isinstance(language, str) or language.strip().lower().split("-", 1)[0] != "en"
        ):
            continue
        mime = entry.get("type")
        if mime is not None and not isinstance(mime, str):
            continue
        mime = (mime or "").split(";", 1)[0].strip().lower()
        if mime in ranks and isinstance(entry.get("url"), str) and entry["url"]:
            candidates.append((ranks[mime], index))
    if not candidates:
        raise PodcastTranscriptError("No supported English transcript reference was advertised.")
    return _select_transcript(episode, min(candidates)[1])


def fetch_episode_transcript(
    episode: dict[str, Any], *, transcript_index: int = 0,
) -> PodcastTranscript:
    """Download one transcript from a Podcast Index episode returned in `items`.

    `transcript_index` selects an entry in the episode's `transcripts` array.
    If that array is absent or empty, index 0 uses the legacy `transcriptUrl`.
    The caller chooses the episode and language/format before calling this function.
    Exactly one GET is attempted after validation, without API credentials,
    redirects, retries, or fallback downloads. Only public HTTPS URLs are accepted.

    The result is raw text, not parsed cues or a corpus record. Both MIME hints
    are retained as supplied; neither is proof that the body has a valid format.
    """
    if not isinstance(episode, dict):
        raise ValueError("episode must be a Podcast Index episode object.")
    for key in ("id", "feedId"):
        if type(episode.get(key)) is not int or episode[key] <= 0:
            raise ValueError("episode must have positive integer id and feedId fields.")
    if not isinstance(episode.get("title"), str):
        raise ValueError("episode must have a string title.")
    episode_url = episode.get("link")
    if episode_url is not None and not isinstance(episode_url, str):
        raise ValueError("episode link must be a string or null.")
    if type(transcript_index) is not int or transcript_index < 0:
        raise ValueError("transcript_index must be a nonnegative integer.")

    url, declared_type = _select_transcript(episode, transcript_index)
    text, content_type = _download_transcript(url)
    return PodcastTranscript(
        feed_id=episode["feedId"],
        episode_id=episode["id"],
        episode_title=episode["title"],
        episode_url=episode_url,
        transcript_url=url,
        declared_type=declared_type,
        content_type=content_type,
        text=text,
    )


def _select_transcript(episode: dict[str, Any], index: int) -> tuple[str, str | None]:
    entries = episode.get("transcripts")
    if entries is not None and not isinstance(entries, list):
        raise PodcastTranscriptError("Episode transcripts must be an array or null.")
    if entries:
        if index >= len(entries):
            raise ValueError("transcript_index is outside the episode's transcripts array.")
        entry = entries[index]  # Inspect just the chosen reference; do not fetch the others.
        if not isinstance(entry, dict):
            raise PodcastTranscriptError("Selected transcript metadata must be an object.")
        url, declared_type = entry.get("url"), entry.get("type")
    else:
        if index != 0:
            raise ValueError("Only index 0 is available for a legacy transcriptUrl.")
        url, declared_type = episode.get("transcriptUrl"), None
    if not isinstance(url, str) or not url:
        raise PodcastTranscriptError("The selected episode has no usable transcript URL.")
    if declared_type is not None and not isinstance(declared_type, str):
        raise PodcastTranscriptError("Transcript type must be a string or null.")
    return url, declared_type


def _download_transcript(url: str) -> tuple[str, str | None]:
    try:
        if len(url) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in url):
            raise PodcastTranscriptError("Invalid transcript URL.")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment
        ):
            raise PodcastTranscriptError("Transcript URL must use public HTTPS without credentials or a custom port.")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise PodcastTranscriptError("Transcript host must resolve to public addresses.")

        request = Request(url, headers={
            "User-Agent": "EnglishCoach-Transcript/0.1",
            "Accept": "text/*, application/srt, application/x-subrip, application/json, application/octet-stream",
            "Accept-Encoding": "identity",  # Bound the actual body; do not decompress responses.
        })  # Publisher requests never contain Podcast Index authentication headers.
        with build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise PodcastTranscriptError(
                    "Transcript server did not return a complete HTTP 200 response.",
                    status_code=response.status,
                    retry_after_seconds=parse_retry_after_seconds(response.headers.get("Retry-After")),
                )
            if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
                raise PodcastTranscriptError("Compressed transcript responses are unsupported.")
            content_type = response.headers.get("Content-Type")
            length_header = response.headers.get("Content-Length")
            try:
                expected_length = int(length_header) if length_header is not None else None
            except ValueError:
                raise PodcastTranscriptError("Transcript response has an invalid Content-Length.") from None
            if expected_length is not None and not 0 <= expected_length <= MAX_TRANSCRIPT_BYTES:
                raise PodcastTranscriptError("Transcript response has an invalid or oversized Content-Length.")
            raw = response.read(MAX_TRANSCRIPT_BYTES + 1)  # One extra byte detects overflow.
    except HTTPError as exc:
        code = exc.code
        retry_after = parse_retry_after_seconds((exc.headers or {}).get("Retry-After"))
        exc.close()
        raise PodcastTranscriptError(
            f"Transcript server returned HTTP {code}; no retry was made.",
            status_code=code, retry_after_seconds=retry_after,
        ) from None
    except (URLError, OSError, HTTPException):
        raise PodcastTranscriptError("Could not read the transcript response; no retry was made.") from None
    except ValueError:
        raise PodcastTranscriptError("Invalid transcript URL or address.") from None

    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise PodcastTranscriptError("Transcript exceeded the 2 MiB limit.")
    if expected_length is not None and len(raw) != expected_length:
        raise PodcastTranscriptError("Transcript body length did not match Content-Length.")
    try:
        text = raw.decode("utf-8-sig")  # Accept an optional UTF-8 BOM without altering line breaks.
    except UnicodeError:
        raise PodcastTranscriptError("Transcript is not supported UTF-8 text.") from None
    if not text.strip() or any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise PodcastTranscriptError("Transcript is empty or contains unsupported binary controls.")
    return text, content_type
