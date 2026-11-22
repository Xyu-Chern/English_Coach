"""Small, read-only Podcast Index adapter; independent of the translation model.

Each method makes one bounded request: up to ten search results, 200 recent
episodes, or an explicitly requested 1000-episode archive. No pagination or retries.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from math import ceil
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..config import _read_env_file

BASE_URL = "https://api.podcastindex.org/api/1.0"  # Send credentials only to this API.
MAX_RESULTS = 10  # Local exploration limit, not the upstream API's maximum.
MAX_EPISODE_RESULTS = 200  # A bounded page from one explicitly selected feed.
MAX_ARCHIVE_RESULTS = 1000  # Upstream /episodes/byfeedid maximum; explicit backfill only.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # Bound memory used by an external response.
TIMEOUT_SECONDS = 15  # Timeout for blocking network operations; not an overall deadline.


class PodcastIndexError(Exception):
    """A safe error message with no credentials or upstream response body."""

    def __init__(
        self, message: str, *, status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def parse_retry_after_seconds(value: str | None) -> int | None:
    """Read a bounded Retry-After delay/date; do not sleep or retry here."""
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    value = value.strip()
    if not value or any(ord(char) < 32 or ord(char) > 126 for char in value):
        return None
    if value.isdecimal():
        if len(value) > 10:  # Do not parse arbitrarily large upstream integers.
            return None
        seconds = int(value)
    else:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)  # HTTP dates use GMT.
            seconds = max(0, ceil(retry_at.timestamp() - time.time()))
        except (ValueError, TypeError, IndexError, OverflowError, OSError):
            return None
    return seconds if 0 <= seconds <= 2**31 - 1 else None


@dataclass(frozen=True)
class PodcastIndexCredentials:
    api_key: str = field(repr=False)  # Keep keys out of the generated repr.
    api_secret: str = field(repr=False)  # Keep secrets out of the generated repr.

    def __post_init__(self) -> None:
        for value in (self.api_key, self.api_secret):
            if not isinstance(value, str) or not value or not value.isascii():
                raise PodcastIndexError("Podcast Index credentials must be nonempty ASCII strings.")
            if any(ord(char) < 33 or ord(char) > 126 for char in value):
                raise PodcastIndexError("Podcast Index credentials cannot contain whitespace or controls.")

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> "PodcastIndexCredentials":
        # Reuse the demo's KEY=VALUE reader without requiring any LLM settings.
        path = env_file if env_file is not None else Path(__file__).resolve().parents[1] / ".env"
        try:
            values = _read_env_file(path)
        except (OSError, UnicodeError):
            raise PodcastIndexError("Could not read the Podcast Index environment file.") from None
        values.update(os.environ)  # Process environment takes precedence over .env.
        names = ("PODCAST_INDEX_API_KEY", "PODCAST_INDEX_API_SECRET")
        missing = [name for name in names if not values.get(name, "").strip()]
        if missing:
            raise PodcastIndexError("Set " + " and ".join(missing) + ".")
        return cls(*(values[name].strip() for name in names))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward signed headers or make a second request.


class PodcastIndexClient:
    """Fetch metadata for explicitly chosen searches or a single feed.

    Results retain the provider's JSON field names, including transcript URLs
    and any rights metadata. They are untrusted metadata, not reuse permission.
    This adapter does not implement the translation-specific ChatModel protocol.
    """

    def __init__(self, credentials: PodcastIndexCredentials) -> None:
        self._credentials = credentials

    def search_podcasts(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        """Search show metadata, not transcript content; perform one GET."""
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
            raise ValueError("query must contain 1 to 200 nonblank characters.")
        self._validate_limit(limit)
        return self._get("/search/byterm", {"q": query.strip(), "max": limit}, "feeds")

    def episodes_by_feed_id(
        self, feed_id: int, *, limit: int = 5, since: int | None = None,
    ) -> dict[str, Any]:
        """Fetch one bounded episode page, optionally filtered by Unix epoch seconds."""
        if type(feed_id) is not int or feed_id <= 0:
            raise ValueError("feed_id must be one positive integer.")
        self._validate_limit(limit, maximum=MAX_EPISODE_RESULTS)
        if since is not None and (type(since) is not int or since < 0):
            raise ValueError("since must be a nonnegative integer Unix timestamp or None.")
        params = {"id": feed_id, "max": limit}
        if since is not None:
            params["since"] = since
        return self._get("/episodes/byfeedid", params, "items")

    @staticmethod
    def _validate_limit(limit: int, *, maximum: int = MAX_RESULTS) -> None:
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ValueError(f"limit must be an integer from 1 to {maximum}.")

    def episode_by_id(self, episode_id: int) -> dict[str, Any]:
        """Fetch one episode's metadata (enclosure URL, duration) by its Podcast Index ID."""
        if type(episode_id) is not int or episode_id <= 0:
            raise ValueError("episode_id must be one positive integer.")
        return self._get("/episodes/byid", {"id": episode_id}, "episode")

    def historical_episodes_by_feed_id(self, feed_id: int, *, limit: int = 1000) -> dict[str, Any]:
        """Request one archive page; no cursor or guarantee of complete older history.

        The official API spec permits max <=1000 and only a `since` filter:
        https://podcastindex-org.github.io/docs-api/pi_api.json
        Keep ordinary refreshes at their smaller response/request limits.
        """
        if type(feed_id) is not int or feed_id <= 0:
            raise ValueError("feed_id must be one positive integer.")
        self._validate_limit(limit, maximum=MAX_ARCHIVE_RESULTS)
        return self._get("/episodes/byfeedid", {"id": feed_id, "max": limit}, "items",
                         max_response_bytes=8 * 1024 * 1024)

    def _get(
        self, endpoint: str, params: dict[str, str | int], records_key: str,
        *, max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        timestamp = str(int(time.time()))  # UTC Unix seconds, generated for each request.
        credentials = self._credentials
        material = credentials.api_key + credentials.api_secret + timestamp
        signature = hashlib.sha1(material.encode("utf-8")).hexdigest()  # Required by this API.
        request = Request(
            BASE_URL + endpoint + "?" + urlencode(params),  # Encode search text as data.
            headers={
                "User-Agent": "EnglishCoach-PodcastMetadata/0.1",
                "X-Auth-Key": credentials.api_key,
                "X-Auth-Date": timestamp,
                "Authorization": signature,  # The secret itself is never sent as a header.
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(max_response_bytes + 1)  # One extra byte detects overflow.
        except HTTPError as exc:
            # No retry, including 401/403/429; don't expose upstream text or request headers.
            code = exc.code
            retry_after = parse_retry_after_seconds((exc.headers or {}).get("Retry-After"))
            exc.close()
            raise PodcastIndexError(
                f"Podcast Index returned HTTP {code}; no retry was made.",
                status_code=code, retry_after_seconds=retry_after,
            ) from None
        except (URLError, OSError, HTTPException):
            raise PodcastIndexError("Could not read the Podcast Index response; no retry was made.") from None
        if len(raw) > max_response_bytes:
            raise PodcastIndexError("Podcast Index response exceeded its bounded size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise PodcastIndexError("Podcast Index returned invalid JSON.") from None
        # Check the envelope and record identities while retaining optional source fields.
        if not isinstance(payload, dict):
            raise PodcastIndexError("Podcast Index returned an invalid response envelope.")
        status = payload.get("status")
        if status is not True and status != "true":
            raise PodcastIndexError("Podcast Index did not report a successful request.")
        records = payload.get(records_key)
        if records_key == "episode":  # /episodes/byid returns one object, not a list.
            if not isinstance(records, dict) or records.get("id") != params["id"]:
                raise PodcastIndexError("Podcast Index returned an unexpected episode.")
            records = [records]
        if not isinstance(records, list) or len(records) > params.get("max", 1):
            raise PodcastIndexError("Podcast Index returned an invalid or oversized record list.")
        for record in records:
            if (
                not isinstance(record, dict)
                or type(record.get("id")) is not int
                or record["id"] <= 0
                or not isinstance(record.get("title"), str)
            ):
                raise PodcastIndexError("Podcast Index returned a record with invalid identity fields.")
            if records_key == "items" and record.get("feedId") != params["id"]:
                raise PodcastIndexError("Podcast Index returned an episode from an unexpected feed.")
        return payload  # No transcript body, URL traversal, storage, or LLM call follows.
