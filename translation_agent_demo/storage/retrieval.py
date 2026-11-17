"""Exact cosine retrieval over complete, currently approved corpus revisions."""

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ..corpus.models import CueSpan
from ..providers.embedding_protocol import validate_embedding
from .embeddings import _bounded_text, _validate_profile
from .postgres import CorpusStorageError


@dataclass(frozen=True)
class RetrievedChunk:
    """Stored wording and provenance; cosine similarity is not a probability."""

    chunk_id: UUID
    document_id: UUID
    build_id: UUID
    source_key: str
    feed_id: int
    episode_id: int
    episode_title: str
    episode_url: str | None
    transcript_url: str | None
    language: str | None
    text: str = field(repr=False)
    similarity: float
    start_ms: int | None
    end_ms: int | None
    speakers: tuple[str, ...]
    spans: tuple[CueSpan, ...]
    rights_status: Literal["approved"]
    rights_review_url: str | None
    license_id: str | None
    license_url: str | None
    attribution: str | None


# Select the latest observed *complete* revision. An unfinished revision therefore
# does not hide the previous searchable one. Recheck current rights, not a copy
# of the permission at embedding time. Both public reads use this same CTE.
_LATEST_COMPLETE = """
    WITH latest_complete AS (
        SELECT DISTINCT ON (s.source_key) b.build_id, b.document_id
        FROM public.corpus_builds AS b
        JOIN public.corpus_embedding_builds AS completed USING (build_id)
        JOIN public.podcast_transcripts AS d USING (document_id)
        JOIN public.podcast_sources AS s USING (source_key)
        JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
        WHERE b.status = 'ready' AND b.processing_version = %s
          AND completed.model = %s AND completed.dimensions = %s
          AND s.rights_status = 'approved'
          AND r.status = 'approved'
          AND public.transcript_url_matches_review_scope(d.download_url, r.transcript_url_prefix)
          AND (%s::text IS NULL OR s.language = %s)
          AND (%s::bigint[] IS NULL OR s.feed_id = ANY(%s::bigint[]))
        ORDER BY s.source_key, d.last_observed_at DESC, d.document_id DESC
    )
"""


def _search_parameters(
    model: str,
    dimensions: int,
    processing_version: str,
    language: str | None,
    feed_ids: tuple[int, ...] | None,
) -> tuple:
    _validate_profile(model, dimensions)
    _bounded_text(processing_version, "processing_version", 128)
    if language is not None:
        _bounded_text(language, "language", 64)
        if re.fullmatch(r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*", language) is None:
            raise ValueError("language must be an exact language tag such as en or en-US.")
    if feed_ids is not None:
        if (
            not isinstance(feed_ids, tuple) or not 1 <= len(feed_ids) <= 30
            or any(type(value) is not int or not 0 < value < 2**63 for value in feed_ids)
            or len(set(feed_ids)) != len(feed_ids)
        ):
            raise ValueError("feed_ids must contain 1 to 30 distinct positive bigint IDs.")
    feeds = list(feed_ids) if feed_ids is not None else None
    return (processing_version, model, dimensions, language, language, feeds, feeds)


def _document_scope(document_ids: tuple[UUID, ...] | None) -> list[UUID] | None:
    if document_ids is None:
        return None
    if (not isinstance(document_ids, tuple) or len(document_ids) > 1000
            or any(not isinstance(value, UUID) for value in document_ids)
            or len(set(document_ids)) != len(document_ids)):
        raise ValueError("document_ids must contain at most 1000 distinct UUIDs; empty means no permitted documents.")
    return list(document_ids)


_REGEX_SPECIAL = re.compile(r"([\\^$.|?*+()\[\]{}])")


def literal_word_pattern(phrase: str) -> str:
    """PostgreSQL ARE for a whole-word, case-insensitive (with ~*) phrase match.

    Metacharacters are escaped so the phrase is matched as text. \\m/\\M are
    added only next to word characters: a phrase ending in "." has no word end.
    """
    _bounded_text(phrase, "literal_phrase", 400)
    pattern = _REGEX_SPECIAL.sub(r"\\\1", phrase)
    if re.match(r"\w", phrase):
        pattern = r"\m" + pattern
    if re.search(r"\w$", phrase):
        pattern += r"\M"
    return pattern


def count_literal_chunks(
    conn: psycopg.Connection,
    literal_phrase: str,
    *,
    model: str,
    dimensions: int,
    processing_version: str,
    language: str | None = None,
    feed_ids: tuple[int, ...] | None = None,
    document_ids: tuple[UUID, ...] | None = None,
) -> int:
    """Count searchable chunks containing the phrase as whole words.

    Unlike a search, this is not capped by limit, so 0 tells the caller the
    phrase is absent from the eligible corpus, not merely outranked.
    """
    parameters = _search_parameters(model, dimensions, processing_version, language, feed_ids)
    documents = _document_scope(document_ids)
    pattern = literal_word_pattern(literal_phrase)
    try:
        row = conn.execute(
            _LATEST_COMPLETE + """
            SELECT count(DISTINCT c.chunk_id) FROM latest_complete AS b
            JOIN public.corpus_chunks AS c USING (build_id)
            JOIN public.corpus_embeddings AS e USING (chunk_id)
            WHERE e.model = %s AND e.dimensions = %s
              AND (%s::uuid[] IS NULL OR b.document_id = ANY(%s::uuid[]))
              AND c.text ~* %s
            """,
            parameters + (model, dimensions, documents, documents, pattern),
        ).fetchone()
        return int(row[0])
    except psycopg.Error:
        raise CorpusStorageError("Could not count literal matches in the stored corpus.") from None


def has_searchable_corpus(
    conn: psycopg.Connection,
    *,
    model: str,
    dimensions: int,
    processing_version: str,
    language: str | None = None,
    feed_ids: tuple[int, ...] | None = None,
    document_ids: tuple[UUID, ...] | None = None,
) -> bool:
    """Check readiness before spending a query embedding request.

    This is a snapshot, not a reservation. The search independently checks the
    same approval and completion conditions after the provider call finishes.
    """
    parameters = _search_parameters(model, dimensions, processing_version, language, feed_ids)
    documents = _document_scope(document_ids)
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                _LATEST_COMPLETE + """
                SELECT EXISTS (
                    SELECT 1 FROM latest_complete AS b
                    JOIN public.corpus_chunks AS c USING (build_id)
                    JOIN public.corpus_embeddings AS e USING (chunk_id)
                    WHERE e.model = %s AND e.dimensions = %s
                      AND (%s::uuid[] IS NULL OR b.document_id = ANY(%s::uuid[]))
                ) AS ready
                """,
                parameters + (model, dimensions, documents, documents),
            ).fetchone()
        return bool(row["ready"])
    except psycopg.Error:
        raise CorpusStorageError("Could not inspect the searchable corpus.") from None


def _display_url(value: str | None) -> str | None:
    """Keep safe publisher links for display; this function never fetches URLs."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return None
    decoded = unquote(value)
    if any(character.isspace() for character in value) or any(
        ord(character) < 32 or 127 <= ord(character) <= 159 or character == "\\"
        for character in decoded
    ):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
        ):
            return None
        parsed.port
        value.encode("utf-8")
    except (ValueError, UnicodeError):
        return None
    return value


def _retrieved_chunk(row: dict) -> RetrievedChunk:
    try:
        spans = tuple(CueSpan(**value) for value in row.pop("spans"))
        if not spans or any(
            any(type(value) is not int for value in (span.cue_index, span.start_char, span.end_char))
            or span.cue_index < 0 or not 0 <= span.start_char < span.end_char
            for span in spans
        ):
            raise ValueError
        speakers = row.pop("speakers")
        if any(speaker is not None and not isinstance(speaker, str) for speaker in speakers):
            raise ValueError
        similarity = float(row["similarity"])
        if not math.isfinite(similarity) or not -1 <= similarity <= 1:
            raise ValueError
        row["similarity"] = similarity
        row["speakers"] = tuple(dict.fromkeys(speaker for speaker in speakers if speaker))
        row["spans"] = spans
        for name in ("episode_url", "transcript_url", "rights_review_url", "license_url"):
            row[name] = _display_url(row[name])
        return RetrievedChunk(**row)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise CorpusStorageError("The stored retrieval record has invalid provenance.") from None


def search_chunks(
    conn: psycopg.Connection,
    vector: Sequence[float],
    *,
    model: str,
    dimensions: int,
    processing_version: str,
    limit: int = 5,
    min_similarity: float | None = None,
    language: str | None = None,
    feed_ids: tuple[int, ...] | None = None,
    literal_phrase: str | None = None,
    document_ids: tuple[UUID, ...] | None = None,
) -> tuple[RetrievedChunk, ...]:
    """Return stored chunks ordered by exact cosine similarity.

    With no minimum, these are nearest candidates, not verified semantic
    matches. Model, dimensions and processing version must exactly match the
    stored profile. Permissions are checked again on every call. A literal
    phrase restricts candidates to case-insensitive, contiguous text matches;
    it does not change cosine scores or perform semantic fallback itself.
    """
    parameters = _search_parameters(model, dimensions, processing_version, language, feed_ids)
    documents = _document_scope(document_ids)
    if literal_phrase is not None:
        _bounded_text(literal_phrase, "literal_phrase", 400)
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer between 1 and 10.")
    if min_similarity is not None and (
        isinstance(min_similarity, bool) or not isinstance(min_similarity, (int, float))
        or not -1 <= min_similarity <= 1
    ):
        raise ValueError("min_similarity must be a finite number between -1 and 1 or null.")
    encoded_vector = json.dumps(validate_embedding(vector, dimensions=dimensions), allow_nan=False)
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                _LATEST_COMPLETE + """
                , ranked AS (
                    SELECT c.*, 1.0 - (e.embedding <=> %s::public.vector) AS similarity
                    FROM latest_complete AS b
                    JOIN public.corpus_chunks AS c USING (build_id)
                    JOIN public.corpus_embeddings AS e USING (chunk_id)
                    WHERE e.model = %s AND e.dimensions = %s
                      AND (%s::uuid[] IS NULL OR b.document_id = ANY(%s::uuid[]))
                      AND (%s::text IS NULL OR strpos(lower(c.text), lower(%s::text)) > 0)
                    ORDER BY similarity DESC, c.chunk_id
                    LIMIT %s
                )
                SELECT r.chunk_id, d.document_id, r.build_id, s.source_key,
                       s.feed_id, s.episode_id, s.title AS episode_title, s.episode_url,
                       d.download_url AS transcript_url, s.language, r.text, r.similarity,
                       r.start_ms, r.end_ms, r.spans, s.rights_status,
                       s.review_url AS rights_review_url,
                       s.license_evidence #>> '{feed_review,license_id}' AS license_id,
                       s.license_evidence #>> '{feed_review,evidence,license_url}' AS license_url,
                       s.license_evidence #>> '{feed_review,evidence,attribution}' AS attribution,
                       ARRAY(
                           SELECT b.cues -> (span ->> 'cue_index')::integer ->> 'speaker'
                           FROM jsonb_array_elements(r.spans) WITH ORDINALITY AS item(span, ordinal)
                           ORDER BY ordinal
                       ) AS speakers
                FROM ranked AS r
                JOIN public.corpus_builds AS b USING (build_id)
                JOIN public.podcast_transcripts AS d USING (document_id)
                JOIN public.podcast_sources AS s USING (source_key)
                WHERE (%s::double precision IS NULL OR r.similarity >= %s)
                ORDER BY r.similarity DESC, r.chunk_id
                """,
                parameters + (encoded_vector, model, dimensions, documents, documents, literal_phrase, literal_phrase,
                              limit, min_similarity, min_similarity),
            ).fetchall()
        return tuple(_retrieved_chunk(row) for row in rows)
    except psycopg.Error:
        raise CorpusStorageError("Could not search the stored corpus.") from None
