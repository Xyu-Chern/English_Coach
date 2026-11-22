"""Store time anchors from the inline timestamp markers already inside parsed transcripts.

Reads every ready corpus build of one processing version (the searchable one by default),
counts characters over its cue texts exactly as the audio estimate does, derives the anchors
(storage/time_anchors.document_anchors: inline markers, plus segment start/end anchors around
marker-only Break/Outro/Jingle cues) and makes transcript_time_anchors hold exactly those
anchors for the document (migration 013). Local only: no publisher, audio or LLM requests. Idempotent: a rerun
writes nothing when the anchors are unchanged. Prints counts only, never transcript text.

    python -m translation_agent_demo.jobs.extract_time_anchors [--dry-run] [--processing-version V]
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from psycopg import Connection, Error as PsycopgError

from ..corpus.chunking import ChunkingSettings
from ..storage.postgres import CorpusStorageError, PostgresSettings, connect_database
from ..storage.time_anchors import (
    SOURCE_INLINE_MARKER, SOURCE_SEGMENT_END, SOURCE_SEGMENT_START, SOURCES, Anchor, document_anchors,
    replace_document_anchors,
)

BATCH = 50


@dataclass
class AnchorRunResult:
    status: str = "ok"
    processing_version: str = ""
    dry_run: bool = False
    builds_scanned: int = 0
    documents_with_anchors: int = 0
    anchors: int = 0
    inline_markers: int = 0
    segment_starts: int = 0
    segment_end_estimates: int = 0
    documents_written: int = 0
    documents_cleared: int = 0
    documents_unchanged: int = 0


def _document_cues(conn: Connection, build_ids: Sequence[UUID]) -> list[tuple[UUID, UUID, list]]:
    """(build_id, document_id, [[text, speaker], ...] in cue order); offsets count over the texts."""
    return conn.execute(
        """
        SELECT b.build_id, b.document_id,
               coalesce((SELECT jsonb_agg(jsonb_build_array(q.value ->> 'text', q.value ->> 'speaker') ORDER BY q.n)
                         FROM jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)), '[]'::jsonb)
        FROM public.corpus_builds AS b
        WHERE b.build_id = ANY(%s::uuid[])
        ORDER BY b.document_id
        """,
        (list(build_ids),),
    ).fetchall()


def _stored(conn: Connection, document_ids: Sequence[UUID]) -> dict[UUID, set[tuple[int, int, str, UUID]]]:
    rows = conn.execute(
        "SELECT document_id, char_offset, time_ms, source, build_id FROM public.transcript_time_anchors "
        "WHERE document_id = ANY(%s::uuid[])",
        (list(document_ids),),
    ).fetchall()
    stored: dict[UUID, set[tuple[int, int, str, UUID]]] = {}
    for document_id, char, ms, source, build_id in rows:
        stored.setdefault(document_id, set()).add((int(char), int(ms), source, build_id))
    return stored


def extract_time_anchors(conn: Connection, *, processing_version: str, dry_run: bool = False) -> AnchorRunResult:
    """Scan all ready builds of `processing_version`; write only documents whose anchors changed."""
    result = AnchorRunResult(processing_version=processing_version, dry_run=dry_run)
    has_table = conn.execute("SELECT to_regclass('public.transcript_time_anchors') IS NOT NULL").fetchone()[0]
    if not has_table and not dry_run:
        raise CorpusStorageError("Apply migration 013_transcript_time_anchors.sql first.")
    build_ids = [row[0] for row in conn.execute(
        "SELECT build_id FROM public.corpus_builds WHERE processing_version = %s AND status = 'ready' "
        "ORDER BY document_id",
        (processing_version,),
    ).fetchall()]
    for start in range(0, len(build_ids), BATCH):
        batch = _document_cues(conn, build_ids[start:start + BATCH])
        stored = _stored(conn, [document_id for _, document_id, _ in batch]) if has_table else {}
        for build_id, document_id, cues in batch:
            result.builds_scanned += 1
            anchors: list[Anchor] = document_anchors([(text or "", speaker) for text, speaker in cues])
            sources = [anchor.source for anchor in anchors]
            result.anchors += len(anchors)
            result.inline_markers += sources.count(SOURCE_INLINE_MARKER)
            result.segment_starts += sources.count(SOURCE_SEGMENT_START)
            result.segment_end_estimates += sources.count(SOURCE_SEGMENT_END)
            result.documents_with_anchors += bool(anchors)
            wanted = {(a.char_offset, a.time_ms, a.source, build_id) for a in anchors}
            replaced = {row for row in stored.get(document_id, set()) if row[2] in SOURCES or row[3] != build_id}
            if replaced == wanted:
                result.documents_unchanged += 1
                continue
            if anchors:
                result.documents_written += 1
            else:
                result.documents_cleared += 1
            if not dry_run:
                replace_document_anchors(conn, document_id, build_id, anchors)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Extract and count; do not write the DB")
    parser.add_argument("--processing-version", default=ChunkingSettings().processing_version,
                        help="Corpus build version whose cue texts define the offsets (default: the searchable one)")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args(argv)
    try:
        with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
            result = extract_time_anchors(conn, processing_version=args.processing_version, dry_run=args.dry_run)
    except CorpusStorageError as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    except PsycopgError:
        print(json.dumps({"status": "failed", "error": "Time anchor database operation failed."}))
        return 1
    print(json.dumps(asdict(result), sort_keys=True))  # Counts only; never transcript text or credentials.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
