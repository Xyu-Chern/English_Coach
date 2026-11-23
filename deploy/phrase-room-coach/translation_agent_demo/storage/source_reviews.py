"""Record explicit reuse reviews for a feed or one transcript URL directory.

This is a persistence boundary, not a license detector. An episode-specific
permission or an RSS license tag alone must not be promoted to a feed review.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .postgres import CorpusStorageError


@dataclass(frozen=True)
class ReviewedFeed:
    """An explicit review decision covering the feed's selected transcript source.

    review_note must explicitly explain this transcript-source scope and
    its evidence. A general site/audio license may not cover its transcripts.
    A null transcript_url_prefix explicitly asserts coverage of the entire feed.
    """

    feed_id: int
    status: Literal["approved", "revoked"]
    license_id: str
    review_url: str
    review_note: str = field(repr=False)
    license_evidence: dict[str, Any] = field(repr=False)
    reviewed_at: datetime
    transcript_url_prefix: str | None = None


def _identity(feed_id: int) -> None:
    if type(feed_id) is not int or not 0 < feed_id < 2**63:
        raise ValueError("feed_id must be a positive bigint integer.")


def _text(value: str, label: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must contain 1 to {maximum} nonblank characters.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"{label} must be valid UTF-8.") from None


def _validate_review(review: ReviewedFeed) -> None:
    if not isinstance(review, ReviewedFeed):
        raise ValueError("review must be a ReviewedFeed.")
    _identity(review.feed_id)
    if not isinstance(review.status, str) or review.status not in {"approved", "revoked"}:
        raise ValueError("A feed review must be approved or revoked.")
    _text(review.license_id, "license_id", 128)
    _text(review.review_note, "review_note", 4096)
    _text(review.review_url, "review_url", 2048)
    if review.transcript_url_prefix is not None:
        prefix = review.transcript_url_prefix
        _text(prefix, "transcript_url_prefix", 2048)
        try:
            parsed_prefix = urlsplit(prefix)
            parsed_prefix.port
            if (
                re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9/_.~!$&'()*+,;=:@-]*", prefix) is None
                or not prefix.endswith("/") or not parsed_prefix.hostname
                or re.search(r"(^|/)\.{1,2}(/|$)", parsed_prefix.path) is not None
            ):
                raise ValueError
        except ValueError:
            raise ValueError("transcript_url_prefix must be a canonical HTTPS directory URL ending in /.") from None
    try:
        parsed = urlsplit(review.review_url)
        parsed.port
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(character.isspace() for character in review.review_url)
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 or character == "\\"
                   for character in unquote(review.review_url))
        ):
            raise ValueError
    except ValueError:
        raise ValueError("review_url must be an HTTP(S) link without credentials or control characters.") from None
    if (
        not isinstance(review.reviewed_at, datetime)
        or review.reviewed_at.tzinfo is None or review.reviewed_at.utcoffset() is None
    ):
        raise ValueError("reviewed_at must be a timezone-aware datetime.")
    try:
        if not isinstance(review.license_evidence, dict):
            raise ValueError
        encoded = json.dumps(review.license_evidence, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65536 or "\\u0000" in encoded:
            raise ValueError
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ValueError("License evidence must be valid JSON of at most 64 KiB without null characters.") from None


def _lock_feed_review(conn: psycopg.Connection, feed_id: int, *, shared: bool) -> None:
    """Serialize review creation too: a missing row cannot be locked FOR SHARE."""
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    conn.execute(
        f"SELECT {function}(hashtextextended('podcast_feed_review:' || %s::text, 0))",
        (feed_id,),
    )


def _read_feed_review(conn: psycopg.Connection, feed_id: int) -> ReviewedFeed | None:
    """Read under the caller's transaction, before locking or writing a source."""
    _lock_feed_review(conn, feed_id, shared=True)
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            SELECT feed_id, status, license_id, review_url, review_note, license_evidence,
                   reviewed_at, transcript_url_prefix
            FROM public.podcast_feed_reviews WHERE feed_id = %s FOR SHARE
            """,
            (feed_id,),
        ).fetchone()
    return ReviewedFeed(**row) if row is not None else None


def _source_evidence(review: ReviewedFeed) -> Jsonb:
    return Jsonb({"feed_review": {
        "feed_id": review.feed_id,
        "scope": "url_prefix" if review.transcript_url_prefix is not None else "all_transcripts",
        "transcript_url_prefix": review.transcript_url_prefix,
        "status": review.status,
        "license_id": review.license_id,
        "review_url": review.review_url,
        "reviewed_at": review.reviewed_at.isoformat(),
        "evidence": review.license_evidence,
    }})


def record_feed_review(conn: psycopg.Connection, review: ReviewedFeed) -> None:
    """Persist a scoped transcript decision and update the affected stored sources.

    A null prefix explicitly means all transcripts; otherwise only canonical URLs
    below that directory qualify. The evidence and review_note must support that
    scope; this function does not infer it from episode/RSS metadata.
    Re-approval preserves every already-revoked source. A revoked feed withdraws
    its currently approved sources. No network or metadata discovery happens here.
    """
    _validate_review(review)
    evidence = _source_evidence(review)
    try:
        with conn.transaction():
            _lock_feed_review(conn, review.feed_id, shared=False)
            conn.execute(
                """
                INSERT INTO public.podcast_feed_reviews
                    (feed_id, status, license_id, review_url, review_note, license_evidence,
                     reviewed_at, transcript_url_prefix)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (feed_id) DO UPDATE SET
                    status = EXCLUDED.status, license_id = EXCLUDED.license_id,
                    review_url = EXCLUDED.review_url, review_note = EXCLUDED.review_note,
                    license_evidence = EXCLUDED.license_evidence, reviewed_at = EXCLUDED.reviewed_at,
                    transcript_url_prefix = EXCLUDED.transcript_url_prefix
                """,
                (review.feed_id, review.status, review.license_id, review.review_url,
                 review.review_note, Jsonb(review.license_evidence), review.reviewed_at,
                 review.transcript_url_prefix),
            )
            conn.execute(
                """
                SELECT source_key FROM public.podcast_sources
                WHERE feed_id = %s ORDER BY source_key FOR UPDATE
                """,
                (review.feed_id,),
            ).fetchall()
            conn.execute(
                """
                UPDATE public.podcast_sources
                SET rights_status = CASE
                        WHEN %s = 'revoked' THEN 'revoked'
                        WHEN public.transcript_url_matches_review_scope(last_download_url, %s)
                            THEN 'approved' ELSE 'unverified' END,
                    review_note = %s, review_url = %s, reviewed_at = %s,
                    license_evidence = license_evidence || %s::jsonb, updated_at = now()
                WHERE feed_id = %s AND (
                    (%s = 'approved' AND rights_status IN ('unverified', 'approved'))
                    OR (%s = 'revoked' AND rights_status = 'approved')
                )
                """,
                (review.status, review.transcript_url_prefix, review.review_note, review.review_url, review.reviewed_at,
                 evidence, review.feed_id, review.status, review.status),
            )
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not store the feed review; the write was rolled back.") from None


def transcript_url_is_approved(conn: psycopg.Connection, feed_id: int, url: str) -> bool:
    """Check current feed permission and the exact URL scope before an HTTP call.

    This does not authorize redirect destinations; callers must constrain those
    separately. Storage and retrieval use the same database scope predicate.
    """
    _identity(feed_id)
    _text(url, "url", 2048)
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM public.podcast_feed_reviews
                    WHERE feed_id = %s AND status = 'approved'
                      AND public.transcript_url_matches_review_scope(%s, transcript_url_prefix)
                ) AS approved
                """,
                (feed_id, url),
            ).fetchone()
        return bool(row["approved"])
    except psycopg.Error:
        raise CorpusStorageError("Could not check the transcript URL review scope.") from None


def approved_feed_ids(
    conn: psycopg.Connection, configured_ids: tuple[int, ...],
) -> tuple[int, ...]:
    """Return only approved configured feeds, preserving configuration order."""
    if not isinstance(configured_ids, tuple) or len(configured_ids) > 30:
        raise ValueError("configured_ids must be a tuple containing at most 30 feed IDs.")
    for feed_id in configured_ids:
        _identity(feed_id)
    if len(set(configured_ids)) != len(configured_ids):
        raise ValueError("configured_ids cannot contain duplicate feed IDs.")
    if not configured_ids:
        return ()
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                "SELECT feed_id FROM public.podcast_feed_reviews "
                "WHERE feed_id = ANY(%s::bigint[]) AND status = 'approved'",
                (list(configured_ids),),
            ).fetchall()
        approved = {row["feed_id"] for row in rows}
        return tuple(feed_id for feed_id in configured_ids if feed_id in approved)
    except psycopg.Error:
        raise CorpusStorageError("Could not read the approved podcast feeds.") from None
