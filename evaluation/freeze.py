"""Freeze only complete, currently approved retrieval records into local artifacts.

create uses one READ ONLY REPEATABLE READ transaction; verify is offline unless
--check-live-rights is supplied. Rights approval is time-specific.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from translation_agent_demo.storage.postgres import CorpusStorageError, PostgresSettings, connect_database

DEFAULT_ROOT = Path(__file__).resolve().parent / ".local" / "snapshots"
DEFAULT_MANIFESTS = Path(__file__).resolve().parent / "manifests"
DEFAULT_PROCESSING_VERSION = "html-srt-markdown-v3/sentences-v1/cl100k_base@0.14.0/512/64"
DATA_FILES = ("corpus.json.gz", "vectors.f32le.gz")

# Match the production latest-complete rule, including an actual vector coverage
# check. An older complete revision remains usable while a new revision embeds.
_READY = """
    WITH eligible_ready AS (
        SELECT b.build_id, b.document_id, s.source_key, d.last_observed_at
        FROM public.corpus_builds b
        JOIN public.podcast_transcripts d USING(document_id)
        JOIN public.podcast_sources s USING(source_key)
        JOIN public.podcast_feed_reviews r USING(feed_id)
        WHERE b.status='ready' AND b.processing_version=%(processing_version)s
          AND s.rights_status='approved' AND r.status='approved'
          AND public.transcript_url_matches_review_scope(d.download_url, r.transcript_url_prefix)
    )
"""
_LATEST = _READY + """
    , latest_complete AS (
        SELECT DISTINCT ON (v.source_key) v.build_id,v.source_key AS ordering_source_key FROM eligible_ready v
        JOIN public.corpus_embedding_builds e USING(build_id)
        WHERE e.model=%(model)s AND e.dimensions=%(dimensions)s
          AND EXISTS (SELECT 1 FROM public.corpus_chunks c WHERE c.build_id=v.build_id)
          AND NOT EXISTS (
              SELECT 1 FROM public.corpus_chunks c
              LEFT JOIN public.corpus_embeddings x ON x.chunk_id=c.chunk_id
                AND x.model=%(model)s AND x.dimensions=%(dimensions)s
              WHERE c.build_id=v.build_id AND x.chunk_id IS NULL
          )
        ORDER BY v.source_key, v.last_observed_at DESC, v.document_id DESC
    )
"""


def _json_default(value):
    if isinstance(value, (UUID, datetime)):
        return str(value)
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default).encode("utf-8")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profile(model: str, dimensions: int, processing_version: str) -> dict:
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 100:
        raise ValueError("A nonblank embedding model is required.")
    if type(dimensions) is not int or dimensions != 1536:
        raise ValueError("The stored corpus requires 1536-dimensional vectors.")
    if not isinstance(processing_version, str) or not 1 <= len(processing_version.strip()) <= 128:
        raise ValueError("A nonblank processing version is required.")
    return {"model": model, "dimensions": dimensions, "processing_version": processing_version,
            "language": None, "feed_ids": None}


def _snapshot_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", value) is None:
        raise ValueError("Snapshot ID must be 1–80 letters, digits, dots, underscores or hyphens.")
    return value


def _live_metrics(cur, profile: dict) -> dict:
    metrics = cur.execute("""
        SELECT pg_database_size(current_database()) AS database_bytes,
          (SELECT count(*) FROM public.podcast_transcripts) AS raw_revisions,
          (SELECT coalesce(sum(octet_length(raw_text)),0) FROM public.podcast_transcripts) AS raw_text_bytes,
          (SELECT count(*) FROM public.corpus_chunks) AS chunks,
          (SELECT count(*) FROM public.corpus_embeddings) AS vectors,
          (SELECT coalesce(sum(dimensions::bigint*4),0)::bigint FROM public.corpus_embeddings) AS vector_float32_bytes,
          pg_total_relation_size('public.corpus_embeddings') AS vector_relation_bytes
    """).fetchone()
    state = cur.execute(_READY + """
        , latest_ready AS (
          SELECT DISTINCT ON (source_key) * FROM eligible_ready
          ORDER BY source_key,last_observed_at DESC,document_id DESC
        ), coverage AS (
          SELECT b.build_id,count(c.chunk_id) AS chunks,count(e.chunk_id) AS vectors,
            EXISTS (SELECT 1 FROM public.corpus_embedding_builds x WHERE x.build_id=b.build_id
              AND x.model=%(model)s AND x.dimensions=%(dimensions)s) AS completion_marker
          FROM latest_ready b JOIN public.corpus_chunks c USING(build_id)
          LEFT JOIN public.corpus_embeddings e ON e.chunk_id=c.chunk_id
            AND e.model=%(model)s AND e.dimensions=%(dimensions)s
          GROUP BY b.build_id
        )
        SELECT count(*) AS latest_ready_documents,
          count(*) FILTER (WHERE completion_marker AND vectors=chunks) AS latest_ready_complete,
          count(*) FILTER (WHERE vectors>0 AND vectors<chunks) AS latest_ready_partial,
          count(*) FILTER (WHERE vectors=0) AS latest_ready_not_embedded,
          count(*) FILTER (WHERE vectors=chunks AND NOT completion_marker) AS complete_vectors_without_marker
        FROM coverage
    """, profile).fetchone()
    return {**metrics, **state}


def _capture(conn, stage: Path, profile: dict) -> tuple[dict, dict]:
    if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("Freeze requires an idle autocommit connection.")
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with conn.cursor(row_factory=dict_row) as cur:
            origin = cur.execute("""
                SELECT current_database() AS database_name, pg_current_snapshot()::text AS snapshot_id,
                  transaction_timestamp() AT TIME ZONE 'UTC' AS captured_at_utc,
                  current_setting('transaction_isolation') AS isolation,
                  current_setting('transaction_read_only') AS read_only
            """).fetchone()
            origin["captured_at_utc"] = origin["captured_at_utc"].replace(tzinfo=timezone.utc).isoformat()
            live_metrics = _live_metrics(cur, profile)
            documents = cur.execute(_LATEST + """
                SELECT b.build_id,b.document_id,b.processing_version,b.cues,s.source_key,s.feed_id,s.episode_id,
                  s.title,s.episode_url,s.language,d.download_url AS transcript_url,d.content_sha256,
                  octet_length(d.raw_text) AS raw_text_bytes,d.fetched_at,d.last_observed_at,
                  s.rights_status,s.review_url,s.license_evidence,
                  r.license_id,r.review_url AS current_review_url,r.reviewed_at AS current_reviewed_at,
                  r.license_evidence AS current_license_evidence,r.transcript_url_prefix
                FROM latest_complete l JOIN public.corpus_builds b USING(build_id)
                JOIN public.podcast_transcripts d USING(document_id)
                JOIN public.podcast_sources s USING(source_key)
                JOIN public.podcast_feed_reviews r USING(feed_id)
                ORDER BY s.source_key
            """, profile).fetchall()
            if not documents:
                raise ValueError("No complete approved corpus matches the requested profile.")
            chunks = cur.execute(_LATEST + """
                SELECT c.chunk_id,c.build_id,c.chunk_index,c.text,c.token_count,c.spans,c.start_ms,c.end_ms,
                  d.document_id,d.download_url AS transcript_url,s.source_key,s.feed_id,s.episode_id,
                  s.title AS episode_title,s.episode_url,s.language,s.rights_status,s.review_url,s.license_evidence
                FROM latest_complete l JOIN public.corpus_builds b USING(build_id)
                JOIN public.corpus_chunks c USING(build_id)
                JOIN public.podcast_transcripts d USING(document_id)
                JOIN public.podcast_sources s USING(source_key)
                ORDER BY s.source_key,c.chunk_index,c.chunk_id
            """, profile).fetchall()
            for chunk in chunks:
                chunk["text_sha256"] = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
            corpus = {"profile": profile, "documents": documents, "chunks": chunks}
            with (stage / DATA_FILES[0]).open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
                for part in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                             allow_nan=False, default=_json_default).iterencode(corpus):
                    zipped.write(part.encode("utf-8"))
        count = 0
        with conn.cursor(name="freeze_vectors", row_factory=dict_row) as cur:
            cur.execute(_LATEST + """
                SELECT c.chunk_id,e.embedding::text AS vector
                FROM latest_complete l JOIN public.corpus_chunks c USING(build_id)
                JOIN public.corpus_embeddings e USING(chunk_id)
                WHERE e.model=%(model)s AND e.dimensions=%(dimensions)s
                ORDER BY l.ordering_source_key,c.chunk_index,c.chunk_id
            """, profile)
            with (stage / DATA_FILES[1]).open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
                for row in cur:
                    if count >= len(chunks) or str(row["chunk_id"]) != str(chunks[count]["chunk_id"]):
                        raise ValueError("Vector ordering differs from the pinned chunk ordering.")
                    vector = json.loads(row["vector"])
                    if len(vector) != profile["dimensions"] or not all(math.isfinite(v) for v in vector):
                        raise ValueError("Stored vector has invalid length or non-finite values.")
                    values = array("f", vector)
                    if sys.byteorder != "little":
                        values.byteswap()
                    zipped.write(values.tobytes())
                    count += 1
        if count != len(chunks):
            raise ValueError("A complete build is missing a vector; refusing a partial snapshot.")
    return corpus, {"origin": origin, "live_metrics": live_metrics}


def _manifest(snapshot_id: str, corpus: dict, metadata: dict, stage: Path) -> dict:
    chunks, documents = corpus["chunks"], corpus["documents"]
    license_rows = {d["feed_id"]: {"feed_id": d["feed_id"], "license_id": d["license_id"],
                    "review_url": d["current_review_url"], "reviewed_at": d["current_reviewed_at"],
                    "transcript_url_prefix": d["transcript_url_prefix"], "evidence": d["current_license_evidence"]}
                    for d in documents}
    return {"schema_version": 1, "snapshot_id": snapshot_id, "profile": corpus["profile"], **metadata,
            "counts": {"documents": len(documents), "sources": len({d["source_key"] for d in documents}),
                       "chunks": len(chunks), "vectors": len(chunks),
                       "raw_text_bytes": sum(d["raw_text_bytes"] for d in documents),
                       "chunk_text_bytes": sum(len(c["text"].encode("utf-8")) for c in chunks),
                       "vector_float32_bytes": len(chunks) * corpus["profile"]["dimensions"] * 4,
                       "documents_by_feed": dict(sorted(Counter(str(d["feed_id"]) for d in documents).items()))},
            "vectors": {"format": "float32-le", "order": "corpus.chunks array order",
                        "ordered_chunk_ids_sha256": hashlib.sha256(_json_bytes([str(c["chunk_id"]) for c in chunks])).hexdigest()},
            "licenses": [license_rows[k] for k in sorted(license_rows)],
            "rights": {"live_recheck_required_for_use": True, "approval_is_human_label_review": False,
                       "note": "Approval reflects the captured transaction only. Recheck live source rights before later use."},
            "files": {name: {"bytes": (stage / name).stat().st_size, "sha256": _sha(stage / name),
                              "artifact": f"evaluation/.local/snapshots/{snapshot_id}/{name}"} for name in DATA_FILES}}


def verify_snapshot(directory: Path, *, live_conn=None) -> dict:
    """Verify immutable artifact integrity; optionally recheck today's source rights."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or set(manifest.get("files", {})) != set(DATA_FILES):
        raise ValueError("Unsupported snapshot manifest or artifact list.")
    _snapshot_id(manifest["snapshot_id"])
    profile = manifest["profile"]
    if profile != _profile(profile["model"], profile["dimensions"], profile["processing_version"]):
        raise ValueError("Snapshot profile has unexpected filters or fields.")
    for name in DATA_FILES:
        path = directory / name
        if path.is_symlink() or path.stat().st_size != manifest["files"][name]["bytes"] or _sha(path) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Artifact integrity check failed: {name}")
    with gzip.open(directory / DATA_FILES[0], "rt", encoding="utf-8") as handle:
        corpus = json.load(handle)
    if corpus["profile"] != profile:
        raise ValueError("Corpus and manifest profiles differ.")
    docs = {d["document_id"]: d for d in corpus["documents"]}
    chunks = corpus["chunks"]
    counts = manifest["counts"]
    if len(docs) != len(corpus["documents"]) or len(docs) != counts["documents"] or not docs:
        raise ValueError("Document count or identity check failed.")
    if len(chunks) != counts["chunks"] or len({c["chunk_id"] for c in chunks}) != len(chunks) or not chunks:
        raise ValueError("Chunk count or identity check failed.")
    sources = {d["source_key"] for d in docs.values()}
    if len(sources) != len(docs) or len(sources) != counts["sources"]:
        raise ValueError("Snapshot must contain one complete revision per source.")
    if chunks != sorted(chunks, key=lambda c: (c["source_key"], c["chunk_index"], c["chunk_id"])):
        raise ValueError("Chunks are not in the declared stable order.")
    if hashlib.sha256(_json_bytes([c["chunk_id"] for c in chunks])).hexdigest() != manifest["vectors"]["ordered_chunk_ids_sha256"]:
        raise ValueError("Vector-to-chunk ordering checksum differs.")
    if manifest["vectors"].get("format") != "float32-le" or manifest["vectors"].get("order") != "corpus.chunks array order":
        raise ValueError("Unsupported vector representation or mapping.")
    by_document = Counter()
    for chunk in chunks:
        doc = docs.get(chunk["document_id"])
        if not doc or any(chunk[k] != doc[k] for k in ("build_id", "source_key", "transcript_url", "feed_id", "episode_id")):
            raise ValueError("Chunk references a different document, build or source.")
        if chunk["rights_status"] != "approved" or hashlib.sha256(chunk["text"].encode()).hexdigest() != chunk["text_sha256"]:
            raise ValueError("Chunk text or approval check failed.")
        if chunk["chunk_index"] != by_document[doc["document_id"]]:
            raise ValueError("A document has missing or repeated chunk indices.")
        by_document[doc["document_id"]] += 1
        fragments = []
        for span in chunk["spans"]:
            index, start, end = (span[k] for k in ("cue_index", "start_char", "end_char"))
            if any(type(v) is not int for v in (index, start, end)) or not 0 <= index < len(doc["cues"]):
                raise ValueError("Chunk references an invalid cue.")
            text = doc["cues"][index]["text"]
            if not 0 <= start < end <= len(text):
                raise ValueError("Chunk span is outside the stored cue.")
            fragments.append(text[start:end])
        if " ".join(fragments) != chunk["text"]:
            raise ValueError("Chunk text does not reproduce its stored cue spans.")
    for doc in docs.values():
        if not by_document[doc["document_id"]] or doc["processing_version"] != profile["processing_version"] or doc["rights_status"] != "approved":
            raise ValueError("Invalid document profile, coverage or approval.")
        if not doc.get("license_id") or not doc.get("current_review_url") or not doc.get("current_license_evidence"):
            raise ValueError("A document is missing current license evidence.")
        if any(cue.get("index") != index for index, cue in enumerate(doc["cues"])):
            raise ValueError("Document cue indices are invalid.")
    if dict(Counter(str(d["feed_id"]) for d in docs.values())) != counts["documents_by_feed"]:
        raise ValueError("Per-feed document counts differ from the manifest.")
    licenses = {d["feed_id"]: {"feed_id": d["feed_id"], "license_id": d["license_id"],
                "review_url": d["current_review_url"], "reviewed_at": d["current_reviewed_at"],
                "transcript_url_prefix": d["transcript_url_prefix"], "evidence": d["current_license_evidence"]}
                for d in docs.values()}
    if [licenses[key] for key in sorted(licenses)] != manifest["licenses"]:
        raise ValueError("Manifest license evidence differs from the documents.")
    dimensions = profile["dimensions"]
    byte_count = 0
    vector_count = 0
    with gzip.open(directory / DATA_FILES[1], "rb") as handle:
        while vector := handle.read(dimensions * 4):
            if len(vector) != dimensions * 4:
                raise ValueError("A vector has an invalid byte length.")
            values = struct.unpack(f"<{dimensions}f", vector)
            if not all(math.isfinite(v) for v in values) or not any(values):
                raise ValueError("Vector contains non-finite values or has zero norm.")
            vector_count += 1
            byte_count += len(vector)
    if vector_count != len(chunks) or vector_count != counts["vectors"] or byte_count != counts["vector_float32_bytes"]:
        raise ValueError("Vector count/length does not match the complete chunk set.")
    if sum(d["raw_text_bytes"] for d in docs.values()) != counts["raw_text_bytes"] or sum(len(c["text"].encode()) for c in chunks) != counts["chunk_text_bytes"]:
        raise ValueError("Text byte counts differ from the manifest.")
    if live_conn is not None:
        verify_live_rights(live_conn, list(docs.values()))
    return {"snapshot_id": manifest["snapshot_id"], "verified": True, "counts": counts,
            "compressed_data_bytes": sum(v["bytes"] for v in manifest["files"].values()),
            "manifest_sha256": _sha(directory / "manifest.json"), "live_rights_checked": live_conn is not None}


def verify_live_rights(conn, documents: list[dict]) -> None:
    """A stored snapshot cannot override a later withdrawal of source permission."""
    if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("Rights checks require an idle autocommit connection.")
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        missing = conn.execute("""
            SELECT count(*) FROM jsonb_to_recordset(%s::jsonb)
                AS frozen(source_key text, transcript_url text, license_id text)
            WHERE NOT EXISTS (
              SELECT 1 FROM public.podcast_sources s JOIN public.podcast_feed_reviews r USING(feed_id)
              WHERE s.source_key=frozen.source_key AND s.rights_status='approved' AND r.status='approved'
                AND r.license_id=frozen.license_id
                AND public.transcript_url_matches_review_scope(frozen.transcript_url,r.transcript_url_prefix)
            )
        """, (_json_bytes([{k: d[k] for k in ("source_key", "transcript_url", "license_id")} for d in documents]).decode(),)).fetchone()[0]
        if missing:
            raise ValueError(f"Live rights no longer authorize {missing} frozen sources; snapshot use refused.")


def create_snapshot(conn, snapshot_id: str, *, root: Path = DEFAULT_ROOT,
                    manifests: Path = DEFAULT_MANIFESTS, model: str = "text-embedding-3-small",
                    dimensions: int = 1536, processing_version: str = DEFAULT_PROCESSING_VERSION) -> dict:
    snapshot_id = _snapshot_id(snapshot_id)
    profile = _profile(model, dimensions, processing_version)
    root, manifests = Path(root), Path(manifests)
    root.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    destination, portable = root / snapshot_id, manifests / f"{snapshot_id}.json"
    if destination.exists() or portable.exists():
        raise FileExistsError("Snapshot ID or portable manifest already exists; choose a new ID.")
    lock = root / f".{snapshot_id}.lock"
    lock.mkdir()  # Exclusive among concurrent creators, including before rename.
    stage = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.tmp-", dir=root))
    try:
        if destination.exists() or portable.exists():
            raise FileExistsError("Snapshot ID already exists; no artifact was overwritten.")
        corpus, metadata = _capture(conn, stage, profile)
        manifest = _manifest(snapshot_id, corpus, metadata, stage)
        encoded = _json_bytes(manifest) + b"\n"
        (stage / "manifest.json").write_bytes(encoded)
        result = verify_snapshot(stage)
        for file in stage.iterdir():
            file.chmod(0o444)
        if destination.exists():
            raise FileExistsError("Snapshot destination appeared during capture; no overwrite performed.")
        stage.rename(destination)
        with portable.open("xb") as handle:
            handle.write(encoded)
        portable.chmod(0o444)
        result["directory"] = str(destination)
        result["portable_manifest"] = str(portable)
        result["live_metrics"] = metadata["live_metrics"]
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        lock.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    verify = sub.add_parser("verify")
    for command in (create, verify):
        command.add_argument("--snapshot-id", required=True)
        command.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        command.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / "translation_agent_demo" / ".env")
    create.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
    create.add_argument("--model", help="default: model selected by EMBEDDING_PROVIDER")
    create.add_argument("--dimensions", type=int, default=1536)
    create.add_argument("--processing-version", default=DEFAULT_PROCESSING_VERSION)
    verify.add_argument("--check-live-rights", action="store_true")
    args = parser.parse_args()
    try:
        _snapshot_id(args.snapshot_id)
        if args.command == "create":
            from translation_agent_demo.providers.embeddings import embedding_model
            with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
                result = create_snapshot(conn, args.snapshot_id, root=args.root, manifests=args.manifests,
                                         model=args.model or embedding_model(args.env_file), dimensions=args.dimensions,
                                         processing_version=args.processing_version)
        elif args.check_live_rights:
            with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
                result = verify_snapshot(args.root / args.snapshot_id, live_conn=conn)
        else:
            result = verify_snapshot(args.root / args.snapshot_id)
    except (OSError, ValueError, KeyError, TypeError, CorpusStorageError, psycopg.Error) as error:
        # Never render connection strings or raw database errors.
        message = str(error) if not isinstance(error, psycopg.Error) else "Database read failed; no snapshot was published."
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
