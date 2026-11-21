"""Store acquired podcast text and inherit only applicable explicit reuse reviews.

Without a review, bodies remain unverified for local inspection. Metadata never
grants permission, and explicitly revoked episode sources remain revoked.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..providers.podcast_transcripts import MAX_TRANSCRIPT_BYTES, PodcastTranscript
from .postgres import CorpusStorageError
from .source_reviews import _read_feed_review, _source_evidence


@dataclass(frozen=True)
class SaveTranscriptResult:
    document_id: UUID
    created: bool


@dataclass(frozen=True)
class StoredTranscript(PodcastTranscript):
    document_id: UUID
    source_key: str
    content_sha256: str
    fetched_at: datetime
    last_observed_at: datetime
    rights_status: Literal["unverified", "approved", "revoked"]
    language: str | None
    license_evidence: dict[str, Any] = field(repr=False)


def _source_key(feed_id: int, episode_id: int, namespace: str = "podcast_index") -> str:
    for value in (feed_id, episode_id):
        if type(value) is not int or not 0 < value < 2**63:
            raise ValueError("feed_id and episode_id must be positive bigint integers.")
    if namespace not in {"podcast_index", "changelog"}:
        raise ValueError("Unknown episode ID namespace.")
    return f"{namespace}:{feed_id}:{episode_id}"


def save_transcript(
    conn: psycopg.Connection,
    transcript: PodcastTranscript,
    *,
    language: str | None = None,
    license_evidence: dict[str, Any] | None = None,
    id_namespace: Literal["podcast_index", "changelog"] = "podcast_index",
) -> SaveTranscriptResult:
    """Upsert source metadata and retain one immutable version per distinct text.

    Identical text returns the existing document ID and advances its observation
    time, preserving the acquired body and fetched_at. Missing optional metadata
    preserves the previous value. New/unverified sources inherit an explicit
    approved transcript review whose URL scope matches; revocations are preserved.
    A new URL outside that scope withdraws an existing source approval.
    The caller must finish HTTP work before invoking this short transaction.
    """
    if not isinstance(transcript, PodcastTranscript):
        raise ValueError("transcript must be a PodcastTranscript.")
    source_key = _source_key(transcript.feed_id, transcript.episode_id, id_namespace)
    if not isinstance(transcript.episode_title, str):
        raise ValueError("Transcript episode title must be a string.")
    if not isinstance(transcript.transcript_url, str) or not 1 <= len(transcript.transcript_url) <= 2048:
        raise ValueError("Transcript URL must contain 1 to 2048 characters.")
    for value in (transcript.episode_url, transcript.declared_type, transcript.content_type):
        if value is not None and not isinstance(value, str):
            raise ValueError("Transcript optional source fields must be strings or null.")
    if language is not None and (not isinstance(language, str) or not 1 <= len(language.strip()) <= 64):
        raise ValueError("language must contain 1 to 64 nonblank characters or be null.")
    if not isinstance(transcript.text, str) or not transcript.text.strip():
        raise ValueError("Transcript text must be nonblank.")
    if any("\x00" in value for value in (
        transcript.text, transcript.episode_title, transcript.transcript_url,
        transcript.episode_url or "", transcript.declared_type or "", transcript.content_type or "",
        language or "",
    )):
        raise ValueError("Transcript fields cannot contain null characters.")
    try:
        raw = transcript.text.encode("utf-8")
    except UnicodeError:
        raise ValueError("Transcript text must be valid UTF-8.") from None
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Transcript text exceeds the 2 MiB limit.")
    if license_evidence is not None:
        if not isinstance(license_evidence, dict):
            raise ValueError("license_evidence must be an object or null.")
        try:
            encoded_evidence = json.dumps(license_evidence, allow_nan=False)
            if len(encoded_evidence.encode("utf-8")) > 65536:
                raise ValueError
        except (TypeError, ValueError, RecursionError, UnicodeError):
            raise ValueError("License evidence must be valid JSON of at most 64 KiB.") from None

    content_hash = hashlib.sha256(raw).hexdigest()
    evidence = Jsonb(license_evidence) if license_evidence is not None else None
    try:
        with conn.transaction():
            # Lock before the source, including when no review row exists yet.
            # Review changes cannot race this decision or its source insert.
            review = _read_feed_review(conn, transcript.feed_id)
            # Updating the source serializes simultaneous imports for this episode.
            conn.execute(
                """
                INSERT INTO public.podcast_sources
                    (source_key, feed_id, episode_id, title, episode_url, language,
                     license_evidence, last_download_url)
                VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s::jsonb, '{}'::jsonb), %s)
                ON CONFLICT (source_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    episode_url = COALESCE(EXCLUDED.episode_url, podcast_sources.episode_url),
                    language = COALESCE(EXCLUDED.language, podcast_sources.language),
                    license_evidence = CASE WHEN podcast_sources.rights_status <> 'unverified'
                        THEN podcast_sources.license_evidence
                        ELSE COALESCE(%s::jsonb, podcast_sources.license_evidence) END,
                    last_download_url = EXCLUDED.last_download_url,
                    updated_at = now()
                """,
                (source_key, transcript.feed_id, transcript.episode_id,
                 transcript.episode_title, transcript.episode_url,
                 language.strip() if language is not None else None,
                 evidence, transcript.transcript_url, evidence),
            )
            if review is not None and review.status == "approved":
                conn.execute(
                    """
                    UPDATE public.podcast_sources
                    SET rights_status = CASE
                            WHEN public.transcript_url_matches_review_scope(last_download_url, %s)
                                THEN 'approved' ELSE 'unverified' END,
                        review_note = %s, review_url = %s,
                        reviewed_at = %s, license_evidence = license_evidence || %s::jsonb,
                        updated_at = now()
                    WHERE source_key = %s AND rights_status IN ('unverified', 'approved')
                    """,
                    (review.transcript_url_prefix, review.review_note, review.review_url, review.reviewed_at,
                     _source_evidence(review), source_key),
                )
            # The source lock serializes observations. Advancing beyond its latest
            # timestamp also handles a clock adjustment or equal clock readings.
            observed_at = conn.execute(
                """
                SELECT GREATEST(clock_timestamp(), max(last_observed_at) + interval '1 microsecond')
                FROM public.podcast_transcripts WHERE source_key = %s
                """,
                (source_key,),
            ).fetchone()[0]
            row = conn.execute(
                """
                INSERT INTO public.podcast_transcripts
                    (document_id, source_key, download_url, declared_type,
                     content_type, content_sha256, raw_text, last_observed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_key, content_sha256) DO NOTHING
                RETURNING document_id
                """,
                (uuid4(), source_key, transcript.transcript_url, transcript.declared_type,
                 transcript.content_type, content_hash, transcript.text, observed_at),
            ).fetchone()
            if row is not None:
                result = SaveTranscriptResult(row[0], created=True)
            else:
                row = conn.execute(
                    "UPDATE public.podcast_transcripts SET last_observed_at = %s "
                    "WHERE source_key = %s AND content_sha256 = %s RETURNING document_id",
                    (observed_at, source_key, content_hash),
                ).fetchone()
                if row is None:
                    raise CorpusStorageError("Could not resolve the existing transcript version.")
                result = SaveTranscriptResult(row[0], created=False)
        return result  # With the default autocommit connection, this write is now committed.
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not store the transcript; the write was rolled back.") from None


def get_transcript(conn: psycopg.Connection, document_id: UUID | str) -> StoredTranscript | None:
    """Read a captured body for inspection/processing, not as a retrieval result."""
    if not isinstance(document_id, (UUID, str)):
        raise ValueError("document_id must be a UUID.")
    try:
        document_id = UUID(str(document_id))
    except ValueError:
        raise ValueError("document_id must be a UUID.") from None
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT s.feed_id, s.episode_id, s.title AS episode_title, s.episode_url,
                       d.download_url AS transcript_url, d.declared_type, d.content_type,
                       d.raw_text AS text, d.document_id, d.source_key, d.content_sha256,
                       d.fetched_at, d.last_observed_at, s.rights_status, s.language, s.license_evidence
                FROM public.podcast_transcripts d
                JOIN public.podcast_sources s USING (source_key)
                WHERE d.document_id = %s
                """,
                (document_id,),
            ).fetchone()
    except psycopg.Error:
        raise CorpusStorageError("Could not read the stored transcript.") from None
    return StoredTranscript(**row) if row is not None else None


def has_transcript(
    conn: psycopg.Connection, feed_id: int, episode_id: int, transcript_url: str,
) -> bool:
    """Check if this episode's selected URL has already been captured.

    This avoids repeated downloads, but cannot detect publisher edits at the same
    URL. A future explicit refresh can call save_transcript with a newly read body.
    """
    source_key = _source_key(feed_id, episode_id)
    if not isinstance(transcript_url, str) or not 1 <= len(transcript_url) <= 2048:
        raise ValueError("Transcript URL must contain 1 to 2048 characters.")
    try:
        row = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM public.podcast_transcripts d
                JOIN public.podcast_sources s USING (source_key)
                WHERE s.source_key = %s
                  AND (s.last_download_url = %s OR d.download_url = %s)
            )
            """,
            (source_key, transcript_url, transcript_url),
        ).fetchone()
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not check the captured transcript URL.") from None
    return bool(row[0])
