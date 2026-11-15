"""Persist complete corpus builds while retaining exact links to parsed cues.

These derived records do not change the acquired text or its source's rights.
Changing parsing/chunking behavior requires a new processing_version.
"""

from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..corpus.models import CorpusChunk, Cue, CueSpan, ParsedTranscript
from .postgres import CorpusStorageError


@dataclass(frozen=True)
class SaveChunksResult:
    build_id: UUID
    created: bool
    chunk_count: int


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be nonblank text without null characters.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(f"{label} must be valid UTF-8.") from None


def _version(processing_version: str) -> None:
    _text(processing_version, "processing_version")
    if len(processing_version) > 128:
        raise ValueError("processing_version must contain at most 128 characters.")


def _document(document_id: UUID) -> None:
    if not isinstance(document_id, UUID):
        raise ValueError("document_id must be a UUID.")


def _times(start_ms: int | None, end_ms: int | None) -> None:
    for value in (start_ms, end_ms):
        if value is not None and (type(value) is not int or not 0 <= value < 2**63):
            raise ValueError("Timestamps must be nonnegative bigint milliseconds or null.")
    if start_ms is not None and end_ms is not None and end_ms < start_ms:
        raise ValueError("An end timestamp cannot precede its start timestamp.")


def _validate_chunks(parsed: ParsedTranscript, chunks: tuple[CorpusChunk, ...]) -> None:
    if not isinstance(parsed, ParsedTranscript) or parsed.format not in ("html", "srt"):
        raise ValueError("parsed must identify an HTML or SRT transcript.")
    if not isinstance(parsed.cues, tuple) or not parsed.cues:
        raise ValueError("A ready build requires a nonempty cue tuple.")
    for index, cue in enumerate(parsed.cues):
        if not isinstance(cue, Cue) or type(cue.index) is not int or cue.index != index:
            raise ValueError("Cue indices must be consecutive integers starting at zero.")
        _text(cue.text, "Cue text")
        _times(cue.start_ms, cue.end_ms)
        if cue.speaker is not None:
            _text(cue.speaker, "Cue speaker")
    if not isinstance(chunks, tuple) or not chunks:
        raise ValueError("A ready build requires a nonempty chunk tuple.")
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, CorpusChunk) or type(chunk.index) is not int or chunk.index != index:
            raise ValueError("Chunk indices must be consecutive integers starting at zero.")
        _text(chunk.text, "Chunk text")
        _times(chunk.start_ms, chunk.end_ms)
        if type(chunk.token_count) is not int or not 0 < chunk.token_count < 2**31:
            raise ValueError("Chunk token_count must be a positive integer.")
        if not isinstance(chunk.spans, tuple) or not chunk.spans:
            raise ValueError("Each chunk requires a nonempty span tuple.")
        fragments = []
        for span in chunk.spans:
            if not isinstance(span, CueSpan) or any(
                type(value) is not int for value in (span.cue_index, span.start_char, span.end_char)
            ):
                raise ValueError("Span indices must be integers.")
            if not 0 <= span.cue_index < len(parsed.cues):
                raise ValueError("A span must reference an existing cue.")
            cue = parsed.cues[span.cue_index]
            if not 0 <= span.start_char < span.end_char <= len(cue.text):
                raise ValueError("A span must identify a nonempty half-open cue slice.")
            fragment = cue.text[span.start_char:span.end_char]
            if fragment != fragment.strip():
                raise ValueError("Span boundaries must exclude surrounding whitespace.")
            fragments.append(fragment)
        if chunk.text != " ".join(fragments):
            raise ValueError("Chunk text must exactly match its cue slices joined with spaces.")


def pending_document_ids(
    conn: psycopg.Connection, processing_version: str, *, limit: int = 10,
) -> tuple[UUID, ...]:
    """Select old-to-new raw revisions without a terminal build for this version.

    This is a bounded read, not a claim. Concurrent callers may parse the same
    document; the unique build identity makes their eventual writes idempotent.
    """
    _version(processing_version)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50.")
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                """
                SELECT d.document_id FROM public.podcast_transcripts AS d
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.corpus_builds AS b
                    WHERE b.document_id = d.document_id AND b.processing_version = %s
                )
                ORDER BY d.fetched_at, d.document_id
                LIMIT %s
                """,
                (processing_version, limit),
            ).fetchall()
        return tuple(row["document_id"] for row in rows)
    except psycopg.Error:
        raise CorpusStorageError("Could not select pending corpus documents.") from None


def save_chunks(
    conn: psycopg.Connection,
    document_id: UUID,
    processing_version: str,
    parsed: ParsedTranscript,
    chunks: tuple[CorpusChunk, ...],
) -> SaveChunksResult:
    """Atomically store cues and all chunks, or return the existing build result.

    Validation and parsing happen before the short SQL transaction. Even a prior
    failed build is final for its version; use a new version to process it again.
    """
    _document(document_id)
    _version(processing_version)
    _validate_chunks(parsed, chunks)
    build_id = uuid4()
    cues = Jsonb([asdict(cue) for cue in parsed.cues])
    rows = [
        (uuid4(), build_id, chunk.index, chunk.text, chunk.token_count,
         Jsonb([asdict(span) for span in chunk.spans]), chunk.start_ms, chunk.end_ms)
        for chunk in chunks
    ]
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
            created = cursor.execute(
                """
                INSERT INTO public.corpus_builds
                    (build_id, document_id, processing_version, status, parser_format, cues)
                VALUES (%s, %s, %s, 'ready', %s, %s)
                ON CONFLICT (document_id, processing_version) DO NOTHING
                RETURNING build_id
                """,
                (build_id, document_id, processing_version, parsed.format, cues),
            ).fetchone()
            if created is not None:
                cursor.executemany(
                    """
                    INSERT INTO public.corpus_chunks
                        (chunk_id, build_id, chunk_index, text, token_count, spans, start_ms, end_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                result = SaveChunksResult(build_id, created=True, chunk_count=len(chunks))
            else:
                # Read after the conflict has resolved, including another writer's commit.
                existing = cursor.execute(
                    """
                    SELECT b.build_id, count(c.chunk_id) AS chunk_count
                    FROM public.corpus_builds AS b
                    LEFT JOIN public.corpus_chunks AS c USING (build_id)
                    WHERE b.document_id = %s AND b.processing_version = %s
                    GROUP BY b.build_id
                    """,
                    (document_id, processing_version),
                ).fetchone()
                if existing is None:
                    raise CorpusStorageError("Could not resolve the existing corpus build.")
                result = SaveChunksResult(**existing, created=False)
        return result
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not store the corpus build; the write was rolled back.") from None


def save_build_failure(
    conn: psycopg.Connection, document_id: UUID, processing_version: str, *, error_code: str,
) -> None:
    """Record a safe terminal parse failure without replacing any existing build."""
    _document(document_id)
    _version(processing_version)
    if error_code not in ("unsupported_format", "invalid_format", "empty_transcript"):
        raise ValueError("Unsupported corpus failure code.")
    status = "unsupported" if error_code == "unsupported_format" else "failed"
    try:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO public.corpus_builds
                    (build_id, document_id, processing_version, status, error_code)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (document_id, processing_version) DO NOTHING
                """,
                (uuid4(), document_id, processing_version, status, error_code),
            )
    except psycopg.Error:
        raise CorpusStorageError("Could not record the corpus build failure.") from None
