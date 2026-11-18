"""Snapshot failure boundaries; no live database is mutated by these tests."""
from array import array
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation.freeze import (
    DATA_FILES, DEFAULT_PROCESSING_VERSION, _json_bytes, _manifest, _profile,
    create_snapshot, verify_snapshot,
)


def fixture(stage: Path):
    profile = _profile("text-embedding-3-small", 1536, DEFAULT_PROCESSING_VERSION)
    text = "Hello world."
    document = {
        "document_id": "doc", "build_id": "build", "source_key": "podcast_index:1:2",
        "feed_id": 1, "episode_id": 2, "title": "Test", "episode_url": "https://example.org/2",
        "transcript_url": "https://example.org/transcripts/2.md", "raw_text_bytes": len(text.encode()),
        "processing_version": profile["processing_version"], "rights_status": "approved",
        "cues": [{"index": 0, "text": text}], "license_id": "CC-BY-SA-4.0",
        "current_review_url": "https://example.org/license", "current_reviewed_at": "2026-11-15T00:00:00+00:00",
        "current_license_evidence": {"attribution": "Test author"},
        "transcript_url_prefix": "https://example.org/transcripts/",
    }
    chunk = {k: document[k] for k in ("document_id", "build_id", "source_key", "feed_id", "episode_id", "transcript_url", "rights_status")}
    chunk.update({"chunk_id": "chunk", "chunk_index": 0, "text": text,
                  "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                  "spans": [{"cue_index": 0, "start_char": 0, "end_char": len(text)}]})
    corpus = {"profile": profile, "documents": [document], "chunks": [chunk]}
    (stage / DATA_FILES[0]).write_bytes(gzip.compress(_json_bytes(corpus), mtime=0))
    (stage / DATA_FILES[1]).write_bytes(gzip.compress(array("f", [1.] + [0.] * 1535).tobytes(), mtime=0))
    metadata = {"origin": {"read_only": "on", "isolation": "repeatable read"}, "live_metrics": {}}
    return corpus, metadata


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.stage = self.base / "stage"
        self.stage.mkdir()
        self.corpus, self.metadata = fixture(self.stage)
        self.save_manifest()

    def save_manifest(self):
        manifest = _manifest("test-snapshot", self.corpus, self.metadata, self.stage)
        (self.stage / "manifest.json").write_bytes(_json_bytes(manifest))

    def save_corpus(self):
        (self.stage / DATA_FILES[0]).write_bytes(gzip.compress(_json_bytes(self.corpus), mtime=0))
        self.save_manifest()

    def test_round_trip_vectors_and_counts(self):
        report = verify_snapshot(self.stage)
        self.assertEqual(report["counts"]["vector_float32_bytes"], 6144)
        self.assertEqual(report["counts"]["documents"], 1)
        self.assertFalse(report["live_rights_checked"])

    def test_corrupt_compressed_file_is_rejected(self):
        with (self.stage / DATA_FILES[1]).open("ab") as handle:
            handle.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "integrity"):
            verify_snapshot(self.stage)

    def test_short_vector_fails_even_when_file_hashes_match(self):
        (self.stage / DATA_FILES[1]).write_bytes(gzip.compress(b"1234", mtime=0))
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "byte length"):
            verify_snapshot(self.stage)

    def test_wrong_reference_or_profile_fails_even_with_new_file_hashes(self):
        self.corpus["chunks"][0]["build_id"] = "different-build"
        self.save_corpus()
        with self.assertRaisesRegex(ValueError, "references"):
            verify_snapshot(self.stage)
        self.corpus["chunks"][0]["build_id"] = "build"
        self.corpus["documents"][0]["processing_version"] = "different-profile"
        self.save_corpus()
        with self.assertRaisesRegex(ValueError, "profile"):
            verify_snapshot(self.stage)

    def test_changed_cue_cannot_pass_with_valid_quote_hash(self):
        self.corpus["documents"][0]["cues"][0]["text"] = "Other words."
        self.save_corpus()
        with self.assertRaisesRegex(ValueError, "cue spans"):
            verify_snapshot(self.stage)

    def test_manifest_cannot_relabel_the_captured_license(self):
        path = self.stage / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["licenses"][0]["license_id"] = "different-license"
        path.write_bytes(_json_bytes(manifest))
        with self.assertRaisesRegex(ValueError, "license evidence"):
            verify_snapshot(self.stage)

    def test_create_refuses_overwrite_and_copies_exact_manifest(self):
        root, manifests = self.base / "snapshots", self.base / "manifests"
        with patch("evaluation.freeze._capture", side_effect=lambda conn, stage, profile: fixture(stage)) as capture:
            result = create_snapshot(None, "test-snapshot", root=root, manifests=manifests)
            self.assertTrue(result["verified"])
            self.assertEqual((root / "test-snapshot/manifest.json").read_bytes(), (manifests / "test-snapshot.json").read_bytes())
            with self.assertRaises(FileExistsError):
                create_snapshot(None, "test-snapshot", root=root, manifests=manifests)
            self.assertEqual(capture.call_count, 1)

    def test_failed_capture_publishes_nothing_and_releases_lock(self):
        root, manifests = self.base / "snapshots", self.base / "manifests"
        with patch("evaluation.freeze._capture", side_effect=ValueError("incomplete vectors")):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                create_snapshot(None, "failed-snapshot", root=root, manifests=manifests)
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(list(manifests.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
