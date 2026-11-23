"""Find license declarations in a small, explicitly searched RSS sample.

The Podcast Namespace license tag covers audio/video. A declaration is evidence
to review, never an automatic approval to download or reuse transcript text.
"""

import ipaddress
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .podcast_index import PodcastIndexClient, _NoRedirect

PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
MAX_CANDIDATES = 3  # One API search and at most three RSS requests per explicit search.
MAX_RSS_BYTES = 2 * 1024 * 1024
MAX_LICENSE_RECORDS = 100  # Bound returned per-episode declarations in a single feed.


class PodcastLicenseError(Exception):
    """An RSS lookup/parse failure; messages contain no upstream body."""


@dataclass(frozen=True)
class LicenseDeclaration:
    identifier: str  # Preserve the publisher's spelling; do not infer legal permissions.
    url: str | None
    scope: Literal["channel", "episode"]
    episode_guid: str | None = None  # An item declaration applies only to that episode.
    episode_title: str | None = None
    content_scope: Literal["audio_video"] = "audio_video"


@dataclass
class LicenseCheck:
    status: Literal["declared", "not_found", "unavailable"]
    declarations: list[LicenseDeclaration] = field(default_factory=list)
    copyright_notice: str | None = None  # A notice is not treated as a license grant.
    error: str | None = None
    transcript_reuse: Literal["unverified"] = "unverified"


@dataclass
class LicenseCandidate:
    feed_id: int
    title: str
    rss_url: str
    license_check: LicenseCheck


def parse_license_declarations(raw: bytes) -> LicenseCheck:
    """Parse RSS metadata only; match XML namespace URI, not its chosen prefix."""
    if len(raw) > MAX_RSS_BYTES:
        raise PodcastLicenseError("RSS exceeded the 2 MiB limit.")
    try:
        text = raw.decode("utf-8-sig")  # This small adapter supports UTF-8 RSS only.
        # Reject DTD/entities before parsing; they are not needed for license metadata.
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise PodcastLicenseError("RSS with DTD or entity declarations is unsupported.")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError, ValueError):
        raise PodcastLicenseError("RSS is not valid supported UTF-8 XML.") from None
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise PodcastLicenseError("Expected an RSS channel.")

    declarations = []
    # Inspect the selected feed's metadata, without visiting episode or license URLs.
    for scope, parent in [("channel", channel)] + [("episode", item) for item in channel.findall("item")]:
        nodes = parent.findall(f"{{{PODCAST_NAMESPACE}}}license")
        if len(nodes) > 1:
            raise PodcastLicenseError("Multiple license tags in the same scope need review.")
        for node in nodes:
            identifier = (node.text or "").strip()
            if not identifier or len(identifier) > 128 or len(node):
                raise PodcastLicenseError("Invalid license identifier in RSS.")
            license_url = node.get("url")  # Evidence only; never automatically fetched.
            declarations.append(LicenseDeclaration(
                identifier=identifier,
                url=license_url,
                scope=scope,
                episode_guid=parent.findtext("guid") if scope == "episode" else None,
                episode_title=parent.findtext("title") if scope == "episode" else None,
            ))
            if len(declarations) > MAX_LICENSE_RECORDS:
                raise PodcastLicenseError("RSS exceeded the license-record limit.")
    return LicenseCheck(
        status="declared" if declarations else "not_found",
        declarations=declarations,
        copyright_notice=channel.findtext("copyright"),
    )


def inspect_feed_license(rss_url: str) -> LicenseCheck:
    """Read one public HTTPS RSS URL, without credentials, redirects or retries.

    Missing declarations mean unknown rights, not absence of a license. HTTP-only,
    redirected, oversized or malformed feeds remain unavailable for manual review.
    """
    try:
        if not isinstance(rss_url, str) or len(rss_url) > 2048:
            raise PodcastLicenseError("Invalid RSS URL.")
        parsed = urlsplit(rss_url)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment
        ):
            raise PodcastLicenseError("RSS must use public HTTPS without credentials or a custom port.")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise PodcastLicenseError("RSS host must resolve to public addresses.")
        request = Request(rss_url, headers={
            "User-Agent": "EnglishCoach-LicenseMetadata/0.1",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })  # Podcast Index authentication headers are never used for RSS requests.
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(MAX_RSS_BYTES + 1)
        return parse_license_declarations(raw)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return LicenseCheck(status="unavailable", error=f"RSS returned HTTP {code}; no retry was made.")
    except (URLError, OSError, HTTPException):
        return LicenseCheck(status="unavailable", error="Could not read RSS; no retry was made.")
    except PodcastLicenseError as exc:
        return LicenseCheck(status="unavailable", error=str(exc))
    except ValueError:
        return LicenseCheck(status="unavailable", error="Invalid RSS URL or address.")


def find_license_candidates(
    client: PodcastIndexClient, query: str, *, max_candidates: int = 3,
) -> list[LicenseCandidate]:
    """One show search, then one RSS check per distinct candidate (maximum three).

    Return all checked candidates with explicit outcomes, including missing tags
    and failures. A channel declaration and an episode declaration stay separate.
    The search is title/author metadata search; it is not exhaustive license search.
    """
    if type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES:
        raise ValueError("max_candidates must be an integer from 1 to 3.")
    payload = client.search_podcasts(query, limit=max_candidates)
    candidates = []
    checked = {}  # Reuse a check if the selected API sample repeats the same RSS URL.
    for feed in payload["feeds"][:max_candidates]:
        rss_url = feed.get("url", "")
        if not isinstance(rss_url, str):
            rss_url = ""
        if rss_url not in checked:
            checked[rss_url] = inspect_feed_license(rss_url)
        candidates.append(LicenseCandidate(feed["id"], feed["title"], rss_url, checked[rss_url]))
    return candidates
