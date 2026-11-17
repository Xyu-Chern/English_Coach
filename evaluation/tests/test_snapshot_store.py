"""Focused isolated-schema checks. Set EVALUATION_STORE_TESTS=1 for local DB tests.

The integration tests create and drop only random evaluation_store_test_* schemas.
They never modify production corpus tables or existing evaluation snapshots.
"""
import gzip
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql

from evaluation.freeze import DEFAULT_ROOT, _json_bytes, _manifest
from evaluation.snapshot_store import SnapshotStore, _schema_name, _vector_values, import_snapshot
from translation_agent_demo.storage.postgres import CorpusStorageError, PostgresSettings, connect_database
from translation_agent_demo.storage.retrieval import _document_scope, has_searchable_corpus, search_chunks


SNAPSHOT, SCHEMA = "corpus-20261116-full-v2", "evaluation_snapshot_v2"  # the frozen corpus of the evaluation


class SnapshotStoreUnitTests(unittest.TestCase):
    def test_document_scope_preserves_empty_and_rejects_invalid_or_duplicate_ids(self):
        self.assertIsNone(_document_scope(None))
        self.assertEqual(_document_scope(()), [])
        identifier = uuid4()
        self.assertEqual(_document_scope((identifier,)), [identifier])
        for values in ((str(identifier),), (identifier, identifier), tuple(uuid4() for _ in range(1001))):
            with self.assertRaises(ValueError):
                _document_scope(values)

    def test_schema_scope_rejects_production_and_sql_fragments(self):
        for name in ("public", "english_coach", "evaluation_x;drop schema public", "evaluation_../x", "EVALUATION_test"):
            with self.assertRaises(ValueError):
                _schema_name(name)
        self.assertEqual(_schema_name("evaluation_snapshot"), "evaluation_snapshot")

    def test_vector_mapping_rejects_trailing_or_short_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vectors.gz"
            for payload in (b"short", struct.pack("<3f", 1., 2., 3.)):
                path.write_bytes(gzip.compress(payload))
                with self.assertRaises(ValueError):
                    list(_vector_values(path, 2, 1))


@unittest.skipUnless(os.environ.get("EVALUATION_STORE_READ_TESTS") == "1", "Explicit existing-snapshot read-only test opt-in is required")
class SnapshotLiteralReadOnlyTests(unittest.TestCase):
    def test_literal_search_over_real_frozen_and_live_corpus_is_bounded_and_filtered(self):
        """Use existing vectors and approved records; no writes or provider calls."""
        with gzip.open(DEFAULT_ROOT / SNAPSHOT / "vectors.f32le.gz", "rb") as handle:
            vector = struct.unpack("<1536f", handle.read(1536 * 4))
        with connect_database(PostgresSettings.from_environment()) as conn:
            if conn.execute("SELECT current_database()").fetchone()[0] != "english_coach":
                self.skipTest("Run against the authorized local english_coach database")
            store = SnapshotStore(conn, SNAPSHOT, schema=SCHEMA)
            phrase = "I'M SO EXCITED TO BE HERE."
            frozen = store.search(vector, literal_phrase=phrase, limit=3)
            self.assertTrue(frozen)
            self.assertLessEqual(len(frozen), 3)
            self.assertTrue(all(phrase.lower() in hit.text.lower() for hit in frozen))
            self.assertTrue(all(hit.rights_status == "approved" and hit.license_id for hit in frozen))
            repeated = store.search(vector, literal_phrase=phrase, limit=3)
            self.assertEqual([hit.chunk_id for hit in frozen], [hit.chunk_id for hit in repeated])
            self.assertEqual(store.search(vector, literal_phrase=phrase, feed_ids=(999999999,)), ())
            self.assertEqual(store.search(vector, literal_phrase="%__absent_literal_017ed27__%"), ())
            for literal in (None, phrase):
                scoped = store.search(vector, literal_phrase=literal, document_ids=(frozen[0].document_id,))
                self.assertTrue(scoped)
                self.assertTrue(all(hit.document_id == frozen[0].document_id for hit in scoped))
                self.assertEqual(store.search(vector, literal_phrase=literal, document_ids=[]), ())
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                profile = {key: store.profile[key] for key in ("model", "dimensions", "processing_version")}
                live = search_chunks(conn, vector, **profile, literal_phrase=phrase, limit=3)
                self.assertTrue(live)
                self.assertTrue(all(phrase.lower() in hit.text.lower() for hit in live))
                self.assertEqual(search_chunks(conn, vector, **profile, literal_phrase=phrase,
                                                feed_ids=(999999999,)), ())
                self.assertEqual(search_chunks(conn, vector, **profile,
                                                literal_phrase="%__absent_literal_017ed27__%"), ())
                for literal in (None, phrase):
                    scoped = search_chunks(conn, vector, **profile, literal_phrase=literal, document_ids=(live[0].document_id,))
                    self.assertTrue(scoped)
                    self.assertTrue(all(hit.document_id == live[0].document_id for hit in scoped))
                    self.assertEqual(search_chunks(conn, vector, **profile, literal_phrase=literal, document_ids=()), ())
                self.assertFalse(has_searchable_corpus(conn, **profile, document_ids=()))


@unittest.skipUnless(os.environ.get("EVALUATION_STORE_TESTS") == "1", "Explicit local isolated-schema test opt-in is required")
class SnapshotStoreDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = connect_database(PostgresSettings.from_environment())
        if cls.conn.execute("SELECT current_database()").fetchone()[0] != "english_coach":
            cls.conn.close()
            raise unittest.SkipTest("Run these tests only against the authorized local english_coach DB")
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        # Small test artifact from real approved sources; identical vectors explicitly
        # exercise tie handling. This temporary fixture is never published as a corpus.
        with gzip.open(DEFAULT_ROOT / SNAPSHOT / "corpus.json.gz", "rt", encoding="utf-8") as handle:
            full = json.load(handle)
        cls.corpus = {"profile": full["profile"], "documents": full["documents"][:1], "chunks": full["chunks"][:2]}
        assert all(c["document_id"] == cls.corpus["documents"][0]["document_id"] for c in cls.corpus["chunks"])
        del full
        with gzip.open(DEFAULT_ROOT / SNAPSHOT / "vectors.f32le.gz", "rb") as handle:
            raw = handle.read(1536 * 4)
        cls.vector = struct.unpack("<1536f", raw)
        (cls.directory / "corpus.json.gz").write_bytes(gzip.compress(_json_bytes(cls.corpus), mtime=0))
        (cls.directory / "vectors.f32le.gz").write_bytes(gzip.compress(raw + raw, mtime=0))
        cls.manifest = _manifest("store-test", cls.corpus, {"origin": {}, "live_metrics": {}}, cls.directory)
        cls.manifest_bytes = _json_bytes(cls.manifest)
        (cls.directory / "manifest.json").write_bytes(cls.manifest_bytes)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.temp.cleanup()

    def setUp(self):
        self.schema = "evaluation_store_test_" + uuid4().hex[:12]
        (self.directory / "manifest.json").write_bytes(self.manifest_bytes)
        self.addCleanup(self.drop_schema)

    def drop_schema(self):
        self.conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema)))

    def test_atomic_import_idempotence_and_exact_tie_order(self):
        first = import_snapshot(self.conn, self.directory, schema=self.schema)
        second = import_snapshot(self.conn, self.directory, schema=self.schema)
        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["status"], "already_imported")
        self.assertEqual(second["counts"], {"documents": 1, "chunks": 2, "vectors": 2})
        store = SnapshotStore(self.conn, "store-test", schema=self.schema,
                              expected_manifest_sha256=first["manifest_sha256"])
        self.assertTrue(store.verify()["live_rights_checked"])
        hits = store.search(self.vector, limit=2, min_similarity=.999)
        self.assertEqual([str(h.chunk_id) for h in hits], sorted(c["chunk_id"] for c in self.corpus["chunks"]))
        self.assertTrue(all(h.license_id == "CC-BY-SA-4.0" and h.attribution == "Changelog Media LLC" for h in hits))
        self.assertEqual(store.search(self.vector, feed_ids=(999999999,)), ())

    def test_conflicting_snapshot_does_not_replace_existing_rows(self):
        import_snapshot(self.conn, self.directory, schema=self.schema)
        changed = dict(self.manifest, snapshot_id="different-snapshot")
        (self.directory / "manifest.json").write_bytes(_json_bytes(changed))
        with self.assertRaisesRegex(ValueError, "different snapshot"):
            import_snapshot(self.conn, self.directory, schema=self.schema)
        store = SnapshotStore(self.conn, "store-test", schema=self.schema)
        self.assertEqual(store.verify()["counts"]["chunks"], 2)

    def test_mid_copy_failure_rolls_back_schema_and_rows(self):
        def broken(*args):
            yield self.vector
            raise ValueError("interrupted copy")
        with patch("evaluation.snapshot_store._vector_values", side_effect=broken):
            with self.assertRaisesRegex(ValueError, "interrupted copy"):
                import_snapshot(self.conn, self.directory, schema=self.schema)
        self.assertFalse(self.conn.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)", (self.schema,)).fetchone()[0])

    def test_permission_mismatch_blocks_search_without_silently_filtering(self):
        import_snapshot(self.conn, self.directory, schema=self.schema)
        store = SnapshotStore(self.conn, "store-test", schema=self.schema)
        self.conn.execute(sql.SQL("UPDATE {}.documents SET license_id='withdrawn-test-license'").format(sql.Identifier(self.schema)))
        with self.assertRaisesRegex(CorpusStorageError, "rights changed"):
            store.search(self.vector)


if __name__ == "__main__":
    unittest.main()
