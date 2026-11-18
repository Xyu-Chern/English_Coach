"""Load a verified frozen corpus into an isolated PostgreSQL schema and search it.

No model API is called. Existing float32 vectors are imported without changing
production corpus tables. Each schema holds one immutable snapshot identity.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .freeze import DEFAULT_ROOT, _json_bytes, _sha, verify_snapshot
from translation_agent_demo.providers.embedding_protocol import validate_embedding
from translation_agent_demo.storage.postgres import CorpusStorageError, PostgresSettings, connect_database
from translation_agent_demo.storage.retrieval import _document_scope, _search_parameters, literal_word_pattern
from translation_agent_demo.storage.embeddings import _bounded_text
from translation_agent_demo.agents.contracts import CorpusSearchHit, SearchSpan

DEFAULT_SCHEMA = "evaluation_snapshot"


def _schema_name(name: str) -> str:
    if not isinstance(name, str) or re.fullmatch(r"evaluation_[a-z0-9_]{1,40}", name) is None:
        raise ValueError("Snapshot schema must start with evaluation_ and contain only lowercase letters, digits and underscores.")
    return name


def _idle(conn) -> None:
    if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise CorpusStorageError("Snapshot operations require an idle autocommit connection.")


def _exists(conn, schema: str) -> bool:
    return conn.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)", (schema,)).fetchone()[0]


def _metadata(conn, schema: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(sql.SQL("SELECT snapshot_id,manifest_sha256,manifest FROM {}.metadata WHERE singleton").format(sql.Identifier(schema))).fetchone()
    if not row:
        raise CorpusStorageError("The isolated schema has no completed snapshot metadata.")
    return row


def _counts(conn, schema: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(sql.SQL("""
            SELECT (SELECT count(*) FROM {s}.documents) AS documents,
                   count(*) AS chunks, count(embedding) AS vectors,
                   min(ordinal) AS first_ordinal, max(ordinal) AS last_ordinal
            FROM {s}.chunks
        """).format(s=sql.Identifier(schema))).fetchone()
    return row


def _check_counts(conn, schema: str, manifest: dict) -> dict:
    counts = _counts(conn, schema)
    expected = manifest["counts"]
    if any(counts[key] != expected[key] for key in ("documents", "chunks", "vectors")) or counts["first_ordinal"] != 0 or counts["last_ordinal"] != expected["chunks"] - 1:
        raise CorpusStorageError("Stored snapshot counts differ from its verified manifest.")
    chunk_ids = [str(row[0]) for row in conn.execute(sql.SQL("SELECT chunk_id FROM {}.chunks ORDER BY ordinal").format(sql.Identifier(schema))).fetchall()]
    if hashlib.sha256(_json_bytes(chunk_ids)).hexdigest() != manifest["vectors"]["ordered_chunk_ids_sha256"]:
        raise CorpusStorageError("Stored chunk/vector association differs from its verified manifest.")
    return {key: counts[key] for key in ("documents", "chunks", "vectors")}


def _check_rights(conn, schema: str) -> None:
    missing = conn.execute(sql.SQL("""
        SELECT count(*) FROM {s}.documents d
        WHERE NOT EXISTS (
            SELECT 1 FROM public.podcast_sources live
            JOIN public.podcast_feed_reviews review USING(feed_id)
            WHERE live.source_key=d.source_key AND live.rights_status='approved'
              AND review.status='approved' AND review.license_id=d.license_id
              AND public.transcript_url_matches_review_scope(d.transcript_url,review.transcript_url_prefix)
        )
    """).format(s=sql.Identifier(schema))).fetchone()[0]
    if missing:
        raise CorpusStorageError("Current rights changed for frozen sources; the evaluation corpus cannot be silently narrowed.")


def _vector_values(path: Path, dimensions: int, count: int):
    with gzip.open(path, "rb") as handle:
        for _ in range(count):
            raw = handle.read(dimensions * 4)
            if len(raw) != dimensions * 4:
                raise ValueError("Frozen vector file ended before its chunk mapping.")
            values = struct.unpack(f"<{dimensions}f", raw)
            if not all(math.isfinite(v) for v in values) or not any(values):
                raise ValueError("Frozen vector is non-finite or zero.")
            yield values
        if handle.read(1):
            raise ValueError("Frozen vector file has extra rows after its chunk mapping.")


def import_snapshot(conn, directory: Path, *, schema: str = DEFAULT_SCHEMA) -> dict:
    """Verify artifacts/rights, then commit all isolated tables or none.

    Re-import of the identical manifest is read-only and idempotent. A schema
    containing a different snapshot, or arbitrary existing tables, is rejected.
    """
    schema = _schema_name(schema)
    _idle(conn)
    started = time.perf_counter()
    directory = Path(directory)
    verification = verify_snapshot(directory, live_conn=conn)
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_hash != verification["manifest_sha256"]:
        raise ValueError("Snapshot manifest changed after verification.")
    with gzip.open(directory / "corpus.json.gz", "rt", encoding="utf-8") as handle:
        corpus = json.load(handle)
    identifier = sql.Identifier(schema)
    try:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='300s'")
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation_snapshot:" + schema,))
            if _exists(conn, schema):
                stored = _metadata(conn, schema)
                if stored["snapshot_id"] != manifest["snapshot_id"] or stored["manifest_sha256"] != manifest_hash:
                    raise ValueError("This isolated schema already contains a different snapshot. Choose a fresh evaluation_ schema.")
                counts = _check_counts(conn, schema, manifest)
                _check_rights(conn, schema)
                return {"status": "already_imported", "schema": schema, "snapshot_id": manifest["snapshot_id"],
                        "manifest_sha256": manifest_hash, "counts": counts,
                        "elapsed_ms": round((time.perf_counter()-started)*1000, 2)}
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
            conn.execute(sql.SQL("""
                CREATE TABLE {s}.metadata (
                  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                  snapshot_id text NOT NULL, manifest_sha256 text NOT NULL,
                  manifest jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now()
                )
            """).format(s=identifier))
            conn.execute(sql.SQL("""
                CREATE TABLE {s}.documents (
                  document_id uuid PRIMARY KEY, source_key text NOT NULL UNIQUE,
                  feed_id bigint NOT NULL, language text, transcript_url text NOT NULL,
                  license_id text NOT NULL, record jsonb NOT NULL
                )
            """).format(s=identifier))
            conn.execute(sql.SQL("""
                CREATE TABLE {s}.chunks (
                  chunk_id uuid PRIMARY KEY,
                  document_id uuid NOT NULL REFERENCES {s}.documents(document_id),
                  ordinal integer NOT NULL UNIQUE CHECK(ordinal>=0),
                  record jsonb NOT NULL, embedding public.vector(1536) NOT NULL
                )
            """).format(s=identifier))
            with conn.cursor() as cur:
                with cur.copy(sql.SQL("COPY {}.documents(document_id,source_key,feed_id,language,transcript_url,license_id,record) FROM STDIN").format(identifier)) as copy:
                    for document in corpus["documents"]:
                        copy.write_row((document["document_id"], document["source_key"], document["feed_id"],
                                        document.get("language"), document["transcript_url"], document["license_id"], Jsonb(document)))
                with cur.copy(sql.SQL("COPY {}.chunks(chunk_id,document_id,ordinal,record,embedding) FROM STDIN").format(identifier)) as copy:
                    vectors = _vector_values(directory / "vectors.f32le.gz", manifest["profile"]["dimensions"], len(corpus["chunks"]))
                    for ordinal, (chunk, vector) in enumerate(zip(corpus["chunks"], vectors, strict=True)):
                        copy.write_row((chunk["chunk_id"], chunk["document_id"], ordinal, Jsonb(chunk), json.dumps(vector, separators=(",", ":"), allow_nan=False)))
            # Files are immutable by interface; detect accidental changes during a long import too.
            if _sha(directory / "manifest.json") != manifest_hash or any(_sha(directory / name) != entry["sha256"] for name, entry in manifest["files"].items()):
                raise ValueError("Snapshot artifacts changed during import; all imported rows were rolled back.")
            counts = _check_counts(conn, schema, manifest)
            _check_rights(conn, schema)
            conn.execute(sql.SQL("INSERT INTO {}.metadata(snapshot_id,manifest_sha256,manifest) VALUES(%s,%s,%s)").format(identifier),
                         (manifest["snapshot_id"], manifest_hash, Jsonb(manifest)))
        return {"status": "imported", "schema": schema, "snapshot_id": manifest["snapshot_id"],
                "manifest_sha256": manifest_hash, "counts": counts,
                "elapsed_ms": round((time.perf_counter()-started)*1000, 2)}
    except psycopg.Error:
        raise CorpusStorageError("Could not import the isolated snapshot; the transaction was rolled back.") from None


def _hit(chunk: dict, document: dict, similarity: float) -> CorpusSearchHit:
    review = chunk.get("license_evidence", {}).get("feed_review", {})
    evidence = review.get("evidence", document["current_license_evidence"])
    speakers = tuple(dict.fromkeys(document["cues"][span["cue_index"]].get("speaker") for span in chunk["spans"]))
    return CorpusSearchHit(
        chunk_id=UUID(chunk["chunk_id"]), document_id=UUID(chunk["document_id"]), build_id=UUID(chunk["build_id"]),
        source_key=chunk["source_key"], feed_id=chunk["feed_id"], episode_id=chunk["episode_id"],
        episode_title=chunk["episode_title"], episode_url=chunk.get("episode_url"), transcript_url=chunk["transcript_url"],
        language=chunk.get("language"), text=chunk["text"], similarity=max(-1., min(1., similarity)),
        start_ms=chunk.get("start_ms"), end_ms=chunk.get("end_ms"), speakers=tuple(s for s in speakers if s is not None),
        spans=tuple(SearchSpan(**span) for span in chunk["spans"]), rights_status="approved",
        rights_review_url=chunk.get("review_url", document["current_review_url"]),
        license_id=review.get("license_id", document["license_id"]),
        license_url=evidence.get("license_url"), attribution=evidence.get("attribution"),
    )


class SnapshotStore:
    """Exact search over one pinned snapshot; the caller supplies query vectors."""

    def __init__(self, conn, snapshot_id: str, *, schema: str = DEFAULT_SCHEMA,
                 expected_manifest_sha256: str | None = None):
        self.conn, self.schema = conn, _schema_name(schema)
        _idle(conn)
        try:
            stored = _metadata(conn, self.schema)
        except psycopg.Error:
            raise CorpusStorageError("Import the requested snapshot into the isolated schema before search.") from None
        if stored["snapshot_id"] != snapshot_id or (expected_manifest_sha256 is not None and stored["manifest_sha256"] != expected_manifest_sha256):
            raise CorpusStorageError("The imported snapshot identity differs from the evaluation configuration.")
        self.snapshot_id = snapshot_id
        self.manifest_sha256 = stored["manifest_sha256"]
        self.manifest = stored["manifest"]
        self.profile = dict(self.manifest["profile"])

    def verify(self, *, check_live_rights: bool = True) -> dict:
        _idle(self.conn)
        try:
            with self.conn.transaction():
                self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                current = _metadata(self.conn, self.schema)
                if current["snapshot_id"] != self.snapshot_id or current["manifest_sha256"] != self.manifest_sha256:
                    raise CorpusStorageError("The imported snapshot identity changed.")
                counts = _check_counts(self.conn, self.schema, self.manifest)
                if check_live_rights:
                    _check_rights(self.conn, self.schema)
            return {"snapshot_id": self.snapshot_id, "schema": self.schema, "manifest_sha256": self.manifest_sha256,
                    "profile": self.profile, "counts": counts, "live_rights_checked": check_live_rights}
        except psycopg.Error:
            raise CorpusStorageError("Could not verify the isolated snapshot.") from None

    def search(self, vector, *, limit: int = 5, min_similarity: float | None = None,
               language: str | None = None, feed_ids: tuple[int, ...] | list[int] | None = None,
               literal_phrase: str | None = None,
               document_ids: tuple[UUID, ...] | list[UUID] | None = None) -> tuple[CorpusSearchHit, ...]:
        """Rank a literal-only subset, or all candidates, by actual cosine.

        Literal matching is case-insensitive contiguous text, with no wildcard
        interpretation. The caller controls fallback using the same vector.
        """
        _idle(self.conn)
        feeds = tuple(feed_ids) if feed_ids is not None else None
        documents = _document_scope(tuple(document_ids) if document_ids is not None else None)
        _search_parameters(self.profile["model"], self.profile["dimensions"], self.profile["processing_version"], language, feeds)
        if literal_phrase is not None:
            _bounded_text(literal_phrase, "literal_phrase", 400)
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("limit must be an integer from 1 to 10.")
        if min_similarity is not None and (type(min_similarity) not in (int, float) or not math.isfinite(min_similarity) or not -1 <= min_similarity <= 1):
            raise ValueError("min_similarity must be a finite value between -1 and 1.")
        encoded = json.dumps(validate_embedding(vector, dimensions=self.profile["dimensions"]), allow_nan=False)
        try:
            with self.conn.transaction(), self.conn.cursor(row_factory=dict_row) as cur:
                self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                _check_rights(self.conn, self.schema)
                rows = cur.execute(sql.SQL("""
                    WITH ranked AS (
                      SELECT c.chunk_id,c.document_id,1.0-(c.embedding <=> %s::public.vector) AS similarity
                      FROM {s}.chunks c JOIN {s}.documents d USING(document_id)
                      WHERE (%s::text IS NULL OR d.language=%s)
                        AND (%s::bigint[] IS NULL OR d.feed_id=ANY(%s::bigint[]))
                        AND (%s::uuid[] IS NULL OR d.document_id=ANY(%s::uuid[]))
                        AND (%s::text IS NULL OR strpos(lower(c.record->>'text'), lower(%s::text)) > 0)
                      ORDER BY similarity DESC,c.chunk_id LIMIT %s
                    )
                    SELECT c.record AS chunk,d.record AS document,r.similarity
                    FROM ranked r JOIN {s}.chunks c USING(chunk_id)
                    JOIN {s}.documents d ON d.document_id=r.document_id
                    WHERE (%s::double precision IS NULL OR r.similarity>=%s)
                    ORDER BY r.similarity DESC,r.chunk_id
                """).format(s=sql.Identifier(self.schema)),
                    (encoded, language, language, list(feeds) if feeds else None, list(feeds) if feeds else None,
                     documents, documents, literal_phrase, literal_phrase, limit, min_similarity, min_similarity)).fetchall()
            return tuple(_hit(row["chunk"], row["document"], float(row["similarity"])) for row in rows)
        except psycopg.Error:
            raise CorpusStorageError("Could not search the isolated snapshot.") from None


    def count_literal(self, literal_phrase: str, *, language: str | None = None,
                      feed_ids: tuple[int, ...] | list[int] | None = None,
                      document_ids: tuple[UUID, ...] | list[UUID] | None = None) -> int:
        """Count snapshot chunks containing the phrase as whole words, ignoring case.

        Uncapped by search limit, so 0 means the phrase is absent from the frozen
        corpus (under the same filters), not merely outranked.
        """
        _idle(self.conn)
        feeds = tuple(feed_ids) if feed_ids is not None else None
        documents = _document_scope(tuple(document_ids) if document_ids is not None else None)
        _search_parameters(self.profile["model"], self.profile["dimensions"], self.profile["processing_version"], language, feeds)
        pattern = literal_word_pattern(literal_phrase)
        try:
            row = self.conn.execute(sql.SQL("""
                SELECT count(*) FROM {s}.chunks c JOIN {s}.documents d USING(document_id)
                WHERE (%s::text IS NULL OR d.language=%s)
                  AND (%s::bigint[] IS NULL OR d.feed_id=ANY(%s::bigint[]))
                  AND (%s::uuid[] IS NULL OR d.document_id=ANY(%s::uuid[]))
                  AND c.record->>'text' ~* %s
            """).format(s=sql.Identifier(self.schema)),
                (language, language, list(feeds) if feeds else None, list(feeds) if feeds else None,
                 documents, documents, pattern)).fetchone()
            return int(row[0])
        except psycopg.Error:
            raise CorpusStorageError("Could not count literal matches in the isolated snapshot.") from None

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "verify"))
    parser.add_argument("--snapshot-id", default="corpus-20261116-full-v2")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--schema", default="evaluation_snapshot_v2")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / "translation_agent_demo/.env")
    args = parser.parse_args()
    try:
        with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
            if args.command == "import":
                result = import_snapshot(conn, args.root / args.snapshot_id, schema=args.schema)
            else:
                artifact = verify_snapshot(args.root / args.snapshot_id, live_conn=conn)
                result = SnapshotStore(conn, args.snapshot_id, schema=args.schema,
                                       expected_manifest_sha256=artifact["manifest_sha256"]).verify()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (CorpusStorageError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
