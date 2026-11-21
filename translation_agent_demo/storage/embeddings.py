"""Persist resumable embedding batches without making partial builds searchable."""

import json
from dataclasses import dataclass, field
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ..providers.embedding_protocol import (
    EMBEDDING_DIMENSIONS,
    EmbeddingBatch,
    validate_embedding,
)
from .postgres import CorpusStorageError


@dataclass(frozen=True)
class EmbeddingChunk:
    chunk_id: UUID
    build_id: UUID
    text: str = field(repr=False)
    token_count: int


@dataclass(frozen=True)
class SaveEmbeddingsResult:
    inserted: int
    completed_builds: int


def _bounded_text(value: str, label: str, maximum: int) -> None:
    if (
        not isinstance(value, str) or not value.strip()
        or len(value) > maximum or "\x00" in value
    ):
        raise ValueError(f"{label} must contain 1 to {maximum} nonblank characters.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"{label} must be valid UTF-8.") from None


def _validate_profile(model: str, dimensions: int) -> None:
    _bounded_text(model, "model", 100)
    if type(dimensions) is not int or dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError("This corpus requires 1536-dimensional embeddings.")


def pending_embedding_chunks(
    conn: psycopg.Connection,
    *,
    model: str,
    dimensions: int,
    processing_version: str,
    limit: int = 32,
) -> tuple[EmbeddingChunk, ...]:
    """Read missing vectors from the latest observed ready revision of approved sources.

    A bounded read is not a claim: a job should serialize provider work to avoid
    duplicate API costs. Existing vectors are retained if a later batch fails.
    """
    _validate_profile(model, dimensions)
    _bounded_text(processing_version, "processing_version", 128)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("limit must be an integer between 1 and 32.")
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """
                WITH latest_ready AS (
                    SELECT DISTINCT ON (s.source_key)
                           b.build_id, d.last_observed_at, d.document_id
                    FROM public.podcast_sources AS s
                    JOIN public.podcast_transcripts AS d USING (source_key)
                    JOIN public.corpus_builds AS b USING (document_id)
                    JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
                    WHERE s.rights_status = 'approved'
                      AND r.status = 'approved'
                      AND public.transcript_url_matches_review_scope(d.download_url, r.transcript_url_prefix)
                      AND b.status = 'ready' AND b.processing_version = %s
                    ORDER BY s.source_key, d.last_observed_at DESC, d.document_id DESC
                )
                SELECT c.chunk_id, c.build_id, c.text, c.token_count
                FROM latest_ready AS b
                JOIN public.corpus_chunks AS c USING (build_id)
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.corpus_embeddings AS e
                    WHERE e.chunk_id = c.chunk_id AND e.model = %s AND e.dimensions = %s
                )
                ORDER BY b.last_observed_at, b.document_id, c.chunk_index
                LIMIT %s
                """,
                (processing_version, model, dimensions, limit),
            ).fetchall()
        return tuple(EmbeddingChunk(**row) for row in rows)
    except psycopg.Error:
        raise CorpusStorageError("Could not select pending corpus embeddings.") from None


def save_embeddings(
    conn: psycopg.Connection,
    chunks: tuple[EmbeddingChunk, ...],
    batch: EmbeddingBatch,
) -> SaveEmbeddingsResult:
    """Store immutable vectors and mark builds complete only after their last chunk.

    Finish provider calls before entering this short transaction. A source whose
    approval was withdrawn meanwhile is skipped. Other approved sources in the
    batch can still be stored. Counts cover newly inserted rows and markers.
    """
    if not isinstance(chunks, tuple) or not 1 <= len(chunks) <= 32:
        raise ValueError("chunks must be a tuple containing 1 to 32 records.")
    if not isinstance(batch, EmbeddingBatch):
        raise ValueError("batch must be an EmbeddingBatch.")
    _validate_profile(batch.model, batch.dimensions)
    if not isinstance(batch.vectors, tuple) or len(batch.vectors) != len(chunks):
        raise ValueError("The embedding batch must contain one vector per chunk.")
    if batch.input_tokens is not None and (type(batch.input_tokens) is not int or batch.input_tokens < 0):
        raise ValueError("Embedding input_tokens must be a nonnegative integer.")
    for chunk in chunks:
        if (
            not isinstance(chunk, EmbeddingChunk)
            or not isinstance(chunk.chunk_id, UUID) or not isinstance(chunk.build_id, UUID)
        ):
            raise ValueError("Each chunk must identify a stored chunk and build by UUID.")
        _bounded_text(chunk.text, "Chunk text", 2_097_152)
        if type(chunk.token_count) is not int or not 0 < chunk.token_count < 2**31:
            raise ValueError("Chunk token_count must be a positive integer.")
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("An embedding batch cannot repeat a chunk.")
    build_ids = sorted({chunk.build_id for chunk in chunks})
    # Serialize only validated finite float32 values, before acquiring any locks.
    vectors = tuple(
        json.dumps(validate_embedding(vector, dimensions=batch.dimensions), allow_nan=False)
        for vector in batch.vectors
    )
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
            # Approval updates wait until this write finishes. Lock in a stable order.
            cursor.execute(
                """
                SELECT s.source_key FROM public.podcast_sources AS s
                WHERE s.source_key IN (
                    SELECT d.source_key FROM public.podcast_transcripts AS d
                    JOIN public.corpus_builds AS b USING (document_id)
                    JOIN public.corpus_chunks AS c USING (build_id)
                    WHERE c.chunk_id = ANY(%s::uuid[])
                )
                ORDER BY s.source_key FOR SHARE OF s
                """,
                (chunk_ids,),
            ).fetchall()
            # Serializing each build prevents concurrent final batches from both
            # missing the other's committed vectors when checking completeness.
            cursor.execute(
                """
                SELECT build_id FROM public.corpus_builds
                WHERE build_id = ANY(%s::uuid[]) ORDER BY build_id FOR UPDATE
                """,
                (build_ids,),
            ).fetchall()
            stored = cursor.execute(
                """
                SELECT c.chunk_id, c.build_id, c.text, c.token_count,
                       b.status, s.rights_status, r.status AS feed_review_status,
                       public.transcript_url_matches_review_scope(
                           d.download_url, r.transcript_url_prefix
                       ) AS in_review_scope
                FROM public.corpus_chunks AS c
                JOIN public.corpus_builds AS b USING (build_id)
                JOIN public.podcast_transcripts AS d USING (document_id)
                JOIN public.podcast_sources AS s USING (source_key)
                LEFT JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
                WHERE c.chunk_id = ANY(%s::uuid[])
                ORDER BY c.chunk_id FOR SHARE OF c
                """,
                (chunk_ids,),
            ).fetchall()
            records = {row["chunk_id"]: row for row in stored}
            if len(records) != len(chunks):
                raise ValueError("Every embedding must reference an existing corpus chunk.")
            rows = []
            approved_builds = set()
            for chunk, vector in zip(chunks, vectors, strict=True):
                row = records[chunk.chunk_id]
                if (
                    row["build_id"] != chunk.build_id or row["text"] != chunk.text
                    or row["token_count"] != chunk.token_count or row["status"] != "ready"
                ):
                    raise ValueError("Embedding input must exactly match its stored ready chunk.")
                if (row["rights_status"] == "approved"
                        and row["feed_review_status"] == "approved" and row["in_review_scope"]):
                    rows.append((chunk.chunk_id, batch.model, batch.dimensions, vector))
                    approved_builds.add(chunk.build_id)
            if not rows:
                return SaveEmbeddingsResult(inserted=0, completed_builds=0)
            cursor.executemany(
                """
                INSERT INTO public.corpus_embeddings (chunk_id, model, dimensions, embedding)
                VALUES (%s, %s, %s, %s::public.vector)
                ON CONFLICT (chunk_id, model) DO NOTHING
                """,
                rows,
            )
            inserted = cursor.rowcount
            cursor.execute(
                """
                INSERT INTO public.corpus_embedding_builds (build_id, model, dimensions)
                SELECT b.build_id, %s, %s FROM public.corpus_builds AS b
                WHERE b.build_id = ANY(%s::uuid[]) AND b.status = 'ready'
                  AND EXISTS (
                      SELECT 1 FROM public.corpus_chunks AS c WHERE c.build_id = b.build_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM public.corpus_chunks AS c
                      WHERE c.build_id = b.build_id AND NOT EXISTS (
                          SELECT 1 FROM public.corpus_embeddings AS e
                          WHERE e.chunk_id = c.chunk_id AND e.model = %s AND e.dimensions = %s
                      )
                  )
                ON CONFLICT (build_id, model) DO NOTHING
                """,
                (batch.model, batch.dimensions, sorted(approved_builds), batch.model, batch.dimensions),
            )
            result = SaveEmbeddingsResult(inserted, completed_builds=cursor.rowcount)
        return result
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not store corpus embeddings; the write was rolled back.") from None
