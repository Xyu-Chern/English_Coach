"""Locate explicitly indexed Changelog episodes in its licensed transcript repo."""

import json
import re
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .podcast_index import _NoRedirect

CHANGELOG_FEED_ID = 542376
TRANSCRIPT_REPOSITORY = "https://github.com/thechangelog/transcripts"
_DIRECTORY_URL = "https://api.github.com/repos/thechangelog/transcripts/contents/podcast?ref=master"
_MAX_BYTES = 2 * 1024 * 1024


class ChangelogTranscriptCatalogError(Exception):
    """A safe error from one bounded public repository metadata request."""


def published_episode_numbers() -> frozenset[int]:
    """Read one directory listing, without pagination, credentials or raw-body guesses.

    This catalog is refreshed only with the selected feed's metadata refresh.
    It identifies published files; Podcast Index still supplies episode identity.
    """
    request = Request(_DIRECTORY_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "EnglishCoach-TranscriptCatalog/0.1",
    })
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(_MAX_BYTES + 1)
    except HTTPError as error:
        code = error.code
        error.close()
        raise ChangelogTranscriptCatalogError(f"Transcript catalog returned HTTP {code}; no retry was made.") from None
    except (URLError, OSError, HTTPException):
        raise ChangelogTranscriptCatalogError("Could not read the transcript catalog; no retry was made.") from None
    if len(raw) > _MAX_BYTES:
        raise ChangelogTranscriptCatalogError("Transcript catalog exceeded the 2 MiB limit.")
    try:
        entries = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ChangelogTranscriptCatalogError("Transcript catalog returned invalid JSON.") from None
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ChangelogTranscriptCatalogError("Transcript catalog returned an unsupported directory response.")
    numbers = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        name = entry.get("name")
        match = re.fullmatch(r"the-changelog-([1-9][0-9]{0,7})\.md", name) if isinstance(name, str) else None
        if match:
            numbers.add(int(match.group(1)))
    return frozenset(numbers)


def transcript_reference(
    episode: dict[str, Any], *, published_numbers: frozenset[int] | None = None,
) -> tuple[str, str] | None:
    """Map one known episode URL; never enumerate episode numbers or repository files.

    Podcast Index does not currently expose transcript tags for this feed. The
    publisher licenses the transcript repository separately from the website/audio.
    Only a file present in the directory metadata may be selected. A not-yet
    published episode is skipped until a later recent metadata refresh.
    """
    if episode.get("feedId") != CHANGELOG_FEED_ID:
        return None
    link = episode.get("link")
    match = re.fullmatch(r"https://changelog\.com/podcast/([1-9][0-9]{0,7})/?", link) if isinstance(link, str) else None
    if match is None:
        raise ValueError("The Changelog episode must have its official numbered episode URL.")
    number = match.group(1)
    if published_numbers is None or int(number) not in published_numbers:
        raise ValueError("No published Changelog transcript was confirmed for this episode.")
    return (
        "https://raw.githubusercontent.com/thechangelog/transcripts/master/podcast/"
        f"the-changelog-{number}.md",
        "text/markdown",
    )
