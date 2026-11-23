"""The Vercel package's /admin (D4, D5): the page and an evaluation run's data as static files beside the app.

Builds preview packages (--skip-apk --skip-search-data: no Android SDK, database or encoder needed) into a
temporary folder, then serves one the way Vercel does, in a fresh interpreter that sees only the package.
"""
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

import numpy as np

from frontend import admin_data
from frontend.admin_data import AdminData, build, write
from frontend.tests.test_admin_data import grade, pre_lock_rows, write_run
from frontend.vercel import coach, own_snapshot, package
from translation_agent_demo.providers.embedding_protocol import EmbeddingBatch

# Run inside the package folder: import the function entry as Vercel would, then serve public/ as static
# files, vercel.json's redirects, and the packaged server's /api/search with a fake answer.
SERVE_LIKE_VERCEL = r"""
import json, runpy, sys
from pathlib import Path
from types import SimpleNamespace
pkg = Path.cwd().resolve()
sys.path.insert(0, str(pkg))
function = runpy.run_path(str(pkg / "api/search.py"))["app"]
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
import frontend.server as packaged
from translation_agent_demo.agents import ExpressionItem
def answer(question):
    item = ExpressionItem(expression="Thanks for the heads-up.", function="Thanks", note="Acknowledges a warning.")
    return SimpleNamespace(status="ok", expressions=[item], source_availability_note=None)
def redirect(target):
    return lambda: RedirectResponse(target, 307)
app = packaged.make_app(answer, serve_ui=False, public_access=True)
for rule in json.loads((pkg / "vercel.json").read_text())["redirects"]:
    app.add_api_route(rule["source"], redirect(rule["destination"]), methods=["GET"])
app.mount("/", StaticFiles(directory=pkg / "public", html=True))
client = TestClient(app, base_url="https://coach.example")
redirect = client.get("/admin", follow_redirects=False)
data = client.get("/admin/data.json")
print(json.dumps({
    "server_file": str(Path(packaged.__file__).resolve().relative_to(pkg)),
    "function_routes": sorted(getattr(r, "path", "") for r in function.routes),
    "redirect": [redirect.status_code, redirect.headers.get("location")],
    "admin": [client.get("/admin/").status_code, "Phrase Room 어드민" in client.get("/admin/").text],
    "data": [data.status_code, data.json()["meta"]["schema_version"], len(data.json()["requests"])],
    "web": "Phrase Room" in client.get("/").text,
    "search": client.post("/api/search", json={"question": "thanks"}).json(),
}, ensure_ascii=False))
"""


class VercelPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {"COACH_ADMIN_RUN": "", "COACH_ADMIN_RESULTS": "", "COACH_SYSTEM": ""})
        env.start()
        self.addCleanup(env.stop)
        grades = [grade("t-one", "baseline", True), grade("t-one", "agent", False)]
        self.run, self.tasks = write_run(self.root / "results", "pre", pre_lock_rows(), grades)
        self.out = self.root / "pkg"

    def package(self, *extra, run="pre"):
        argv = ["--out", str(self.out), "--skip-apk", "--skip-search-data", "--admin-results",
                str(self.root / "results"), "--admin-tasks", str(self.tasks), *extra]
        argv += ["--admin-run", run] if run else []
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            package.main(argv)
        return stdout.getvalue()

    def admin_file(self, name):
        return self.out / "public/admin" / name

    def test_a_preview_ships_the_admin_page_and_the_run_data_as_static_files(self):
        printed = self.package("--coach-system", "baseline")
        self.assertIn("admin data: run 'pre'", printed)
        self.assertIn("public/admin:", printed)
        self.assertEqual((package.ADMIN / "index.html").read_bytes(), self.admin_file("index.html").read_bytes())
        data = AdminData.model_validate_json(self.admin_file("data.json").read_text(encoding="utf-8"))
        self.assertEqual(("pre", "baseline", "cli", 8), (data.meta.run.id, data.mode.current, data.mode.source,
                                                         len(data.requests)))
        self.assertFalse(self.admin_file("data-traces.json").exists())
        self.assertTrue((self.out / "public/index.html").is_file())
        self.assertTrue((self.out / "api/search.py").is_file())
        for absent in ("corpus", "encoder", "public/downloads", "frontend/admin"):
            self.assertFalse((self.out / absent).exists(), absent)  # the admin is not in the function's files
        config = json.loads((self.out / "vercel.json").read_text())
        self.assertEqual([{"source": "/admin", "destination": "/admin/", "permanent": False}], config["redirects"])
        noindex = [{"key": "X-Robots-Tag", "value": "noindex"}]
        self.assertEqual([{"source": "/admin", "headers": noindex}, {"source": "/admin/(.*)", "headers": noindex}],
                         config["headers"])
        include = config["functions"]["api/search.py"]["includeFiles"]
        self.assertEqual("{corpus,encoder,translation_agent_demo,frontend,evaluation}/**", include)
        # the live admin routes and the audio alignments are the function's; it has the files and driver they need
        self.assertEqual([{"source": source, "destination": "/api/search"} for source in
                          ("/admin/requests.json", "/admin/mode", "/api/audio/alignment")], config["rewrites"])
        for name in package.FUNCTION_FILES:
            self.assertTrue((package.ROOT / name).is_file() and (self.out / name).is_file(), name)
        self.assertTrue({"frontend/request_log.py", "frontend/sql/request_log.sql", "frontend/admin_data.py",
                         "frontend/staged.py"} <= set(package.FUNCTION_FILES))
        self.assertIn("psycopg[binary]==", (self.out / "requirements.txt").read_text())
        sizes = package.size_report(self.out)
        self.assertEqual(sizes["public/admin"], package.size(self.out / "public/admin"))
        self.assertGreater(sizes["public/admin"], self.admin_file("data.json").stat().st_size)
        self.assertEqual(0, sizes["function/corpus"] + sizes["function/encoder"])

    def test_without_a_run_the_committed_data_or_none_is_shipped_and_old_data_never_stays(self):
        self.package()
        self.assertTrue(self.admin_file("data.json").is_file())
        admin = self.root / "admin"
        admin.mkdir()
        (admin / "index.html").write_text("<!doctype html><title>page</title>", encoding="utf-8")
        with patch.object(package, "ADMIN", admin):
            printed = self.package(run=None)
            self.assertIn("admin data: none", printed)
            self.assertFalse(self.admin_file("data.json").exists())  # the earlier run's data is gone
            self.assertIn("<title>page</title>", self.admin_file("index.html").read_text(encoding="utf-8"))
            write(build(self.run, self.tasks), admin, split="always")
            printed = self.package("--coach-system", "baseline", run=None)
        self.assertIn("run 'pre'", printed)
        self.assertIn("built for mode 'agent'", printed)  # the deployed mode differs: rebuild advised
        for name in package.DATA_FILES:
            self.assertEqual((admin / name).read_bytes(), self.admin_file(name).read_bytes())

    def test_a_bad_run_or_a_preview_in_the_deploy_folder_stops_the_package(self):
        for argv in (["--skip-apk"], ["--skip-search-data", "--out", str(package.DEFAULT_OUT)]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                package.main(argv)
        for run in ("../pre", "missing"):
            with self.subTest(run=run), self.assertRaises(SystemExit):
                self.package(run=run)
        self.assertEqual(package.DEFAULT_OUT, package.ROOT / "frontend/.local/vercel-phrase-room")

    def test_the_package_serves_admin_data_and_the_api_like_vercel(self):
        self.package()
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, "-P", "-c", SERVE_LIKE_VERCEL], cwd=self.out, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr[-2000:])
        result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual("frontend/server.py", result["server_file"])  # the package's copy, not the repository's
        self.assertIn("/api/search", result["function_routes"])
        self.assertNotIn("/admin", result["function_routes"])
        self.assertEqual([307, "/admin/"], result["redirect"])
        self.assertEqual([200, True], result["admin"])
        self.assertEqual([200, admin_data.SCHEMA_VERSION, 8], result["data"])
        self.assertTrue(result["web"])
        self.assertEqual("Thanks for the heads-up.", result["search"]["expressions"][0]["expression"])


AUDIO_URL = "https://audio.example/episode.mp3"
NO_AUDIO = {"audio_url": None, "audio_start_ms": None, "audio_end_ms": None, "audio_estimated": False}


def snapshot_row(n, episode, spans, start_ms=None, end_ms=None):
    """One export row as psql prints it: the deploy schema (evaluation_zh_local_v1) is not on this machine."""
    cues = [{"index": i, "text": text, "speaker": None} for i, text in enumerate(("a" * 100, "b" * 100, "c" * 200))]
    chunk = {"chunk_id": str(UUID(int=n)), "document_id": str(UUID(int=100 + episode)), "build_id": str(UUID(int=9)),
             "source_key": f"podcast_index:{episode}", "feed_id": 7, "episode_id": episode, "episode_title": "Episode",
             "episode_url": None, "transcript_url": "https://feed.example/t.vtt", "language": "en",
             "text": "Thanks for the heads-up.", "start_ms": start_ms, "end_ms": end_ms, "spans": spans}
    document = {"cues": cues, "current_license_evidence": {"license_url": None, "attribution": "Publisher"},
                "current_review_url": None, "license_id": "cc-by-4.0"}
    profile = {"model": "local", "dimensions": 3, "processing_version": "v1"}
    return {"chunk": chunk, "document": document, "vector": "[1,0,0]", "profile": profile, "approved": True}


class SnapshotAudioTests(unittest.TestCase):
    """passages.json carries each passage's audio fields; PublishedCorpus reads them back (PR 6)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.corpus = Path(temporary.name) / "corpus"
        last_cue = [{"cue_index": 2, "start_char": 0, "end_char": 200}]
        self.rows = [snapshot_row(1, 1, last_cue, 12_000, 15_000),  # stored cue timing
                     snapshot_row(2, 1, last_cue),  # estimated from the character position
                     snapshot_row(3, 2, last_cue),  # no audio row
                     snapshot_row(4, 3, last_cue),  # audio row of another feed
                     snapshot_row(5, 4, last_cue)]  # no duration: the URL without offsets
        self.audio = [{"episode_id": 1, "feed_id": 7, "enclosure_url": AUDIO_URL, "duration_s": 400},
                      {"episode_id": 3, "feed_id": 8, "enclosure_url": AUDIO_URL, "duration_s": 400},
                      {"episode_id": 4, "feed_id": None, "enclosure_url": AUDIO_URL, "duration_s": None}]

    def export(self, table=True):
        def psql(sql):
            if "to_regclass" in sql:
                return "t\n" if table else "f\n"
            rows = self.audio if "podcast_episode_audio" in sql else self.rows
            return "".join(json.dumps(r) + "\n" for r in rows)
        with patch.object(package, "psql", psql):
            package.export_corpus(self.corpus)
        with patch.object(coach, "DATA", self.corpus):
            return coach.PublishedCorpus()

    def clips(self, corpus):
        return [{k: getattr(h, k) for k in NO_AUDIO} for h in corpus.hits]

    def test_the_snapshot_ships_stored_or_estimated_audio_and_null_without_it(self):
        corpus = self.export()
        stored = {"audio_url": AUDIO_URL, "audio_start_ms": 12_000, "audio_end_ms": 15_000, "audio_estimated": False}
        # Characters 200..400 of 400 in a 400 s episode: 200 s, started 15 s early, ended 5 s late (capped).
        estimated = {"audio_url": AUDIO_URL, "audio_start_ms": 185_000, "audio_end_ms": 400_000,
                     "audio_estimated": True}
        url_only = dict(NO_AUDIO, audio_url=AUDIO_URL)
        self.assertEqual([stored, estimated, NO_AUDIO, NO_AUDIO, url_only], self.clips(corpus))
        found = corpus.search([1, 0, 0], limit=5, min_similarity=None, language=None, feed_ids=None,
                              document_ids=None)
        self.assertEqual(self.clips(corpus), [{k: getattr(h, k) for k in NO_AUDIO} for h in found])

    def test_without_the_audio_table_or_in_an_older_snapshot_there_is_no_audio(self):
        self.assertEqual([NO_AUDIO] * 5, self.clips(self.export(table=False)))
        passages = self.corpus / "passages.json"
        payload = json.loads(passages.read_text(encoding="utf8"))
        for hit in payload["hits"]:
            for key in NO_AUDIO:
                del hit[key]
        passages.write_text(json.dumps(payload), encoding="utf8")
        with patch.object(coach, "DATA", self.corpus):
            self.assertEqual([NO_AUDIO] * 5, self.clips(coach.PublishedCorpus()))



# --- our own package (frontend/vercel/own_snapshot.py), beside package.py's unchanged default --------------------

class FakeEncoder:
    """LocalEmbeddings' shape: MODEL, 1536 columns of which the last 1152 are zero, unit length."""

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
            vector = np.random.default_rng(seed).standard_normal(1536).astype(np.float32)
            vector[384:] = 0
            rows.append(tuple((vector / np.linalg.norm(vector)).tolist()))
        return EmbeddingBatch(own_snapshot.MODEL, 1536, tuple(rows), 0)


OWN_AUDIO = "https://cdn.example/changelog-1.mp3"


def own_row(n, episode, build, *, text=None, license_id="CC-BY-SA-4.0", review_license="CC-BY-SA-4.0", published=0):
    return {"chunk_id": UUID(int=n), "build_id": build, "document_id": UUID(int=500 + episode),
            "source_key": f"podcast_index:218840:{episode}", "feed_id": 218840, "episode_id": episode,
            "episode_title": f"Episode {episode}", "episode_url": f"https://changelog.com/podcast/{episode}",
            "transcript_url": f"https://raw.githubusercontent.com/thechangelog/transcripts/master/{episode}.md",
            "language": "en-us", "text": text or f"Passage {n}: that is a really good point, honestly.",
            "start_ms": None, "end_ms": None, "spans": [{"cue_index": 2, "start_char": 0, "end_char": 200}],
            "rights_review_url": "https://github.com/thechangelog/transcripts#license--copyright",
            "license_id": license_id, "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "attribution": "Changelog Media LLC", "review_license_id": review_license, "rights_status": "approved",
            "review_status": "approved", "published": published}


def own_corpus():
    """load_corpus's values: episode 1 has time markers, 2 only a duration, 3 no audio; 4's license differs."""
    builds = {episode: UUID(int=900 + episode) for episode in (1, 2, 3, 4)}
    rows = [own_row(1, 1, builds[1], published=100), own_row(2, 1, builds[1], published=100),
            own_row(3, 2, builds[2], published=300), own_row(4, 3, builds[3], published=200),
            own_row(5, 4, builds[4], license_id="CC-BY-4.0")]
    word_row = {"audio_url": OWN_AUDIO, "window_start_ms": 190_000, "method": "asr", "model": "base.en",
                "words": [{"w": "that", "s": 200_000, "e": 200_300}, {"w": "is", "s": 200_300, "e": 200_500}],
                "cues": [{"text": "that is", "start_ms": 200_000, "end_ms": 200_500}]}
    return {
        "processing_version": "html-srt-markdown-v3/test",
        "rows": rows,
        "cues": {build: ([100, 100, 200], ["Adam", None, "Jerod"]) for build in builds.values()},
        "audio": {1: {"feed_id": 218840, "enclosure_url": OWN_AUDIO, "duration_s": 400},
                  2: {"feed_id": None, "enclosure_url": OWN_AUDIO, "duration_s": 400}},
        "anchors": {builds[1]: [(0, 0), (400, 400_000)]},
        "alignments": {UUID(int=1): word_row, UUID(int=3): dict(word_row, audio_url="https://other.example/a.mp3")},
    }


def write_attempts(run: Path, cited: dict[str, int]) -> None:
    for system in ("baseline", "agent"):
        (run / system).mkdir(parents=True)
        lines = []
        for chunk, times in cited.items():
            for _ in range(times):
                lines.append({"result": {"expressions": [{"citation": {"chunk_id": chunk}}, {"citation": None}]}})
        lines.append({"result": None})
        (run / system / "attempts.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


class OwnSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus_dir = self.root / "corpus"

    def export(self, budget=None, cited=None, encoder=None):
        return own_snapshot.export(self.corpus_dir, own_corpus(), cited=cited or Counter(), budget=budget,
                                   encoder=encoder or FakeEncoder(), cache=self.root / "cache", log=lambda line: None)

    def published(self):
        with patch.object(coach, "DATA", self.corpus_dir):
            return coach.PublishedCorpus()

    def test_the_export_keeps_rights_attribution_and_each_chunks_audio_position(self):
        manifest = self.export()
        corpus = self.published()
        self.assertEqual([str(UUID(int=n)) for n in (1, 2, 3, 4)], [str(h.chunk_id) for h in corpus.hits])
        # the CC-BY-4.0 row (a license unlike its feed review's) is refused; every approved one is exported
        self.assertEqual((4, 1, True), (manifest["exported_chunks"], manifest["refused_rows"], manifest["complete"]))
        for hit in corpus.hits:
            self.assertEqual(("approved", "CC-BY-SA-4.0", "Changelog Media LLC"),
                             (hit.rights_status, hit.license_id, hit.attribution))
            self.assertEqual("https://creativecommons.org/licenses/by-sa/4.0/", hit.license_url)
            self.assertEqual(("Jerod",), hit.speakers)
        clips = [(h.audio_url, h.audio_start_ms, h.audio_end_ms, h.audio_estimated) for h in corpus.hits]
        # Characters 200..400 of 400: between the markers 0 s and 400 s, 3 s early; by duration, 15 s early.
        self.assertEqual([(OWN_AUDIO, 197_000, 400_000, True)] * 2 + [(OWN_AUDIO, 185_000, 400_000, True),
                                                                     (None, None, None, False)], clips)
        self.assertEqual({"asr": 1, "anchors": 1, "duration": 1, "none": 1}, manifest["positions"])
        self.assertEqual(corpus.profile, {"model": own_snapshot.MODEL, "dimensions": 1536,
                                          "processing_version": "html-srt-markdown-v3/test"})
        saved = json.loads((self.corpus_dir / "alignments.json").read_text())["alignments"]
        self.assertEqual([str(UUID(int=1))], list(saved))  # chunk 3's alignment is of other audio: dropped
        with patch("frontend.audio_align.SNAPSHOT", self.corpus_dir / "alignments.json"):
            from frontend.audio_align import AudioAlignments
            answer = AudioAlignments.from_environment(local=False, environ={}).lookup(UUID(int=1), "that is")
        self.assertEqual(("ready", "asr", 200_000, 200_500), (answer["status"], answer["method"],
                                                              answer["quote_start_ms"], answer["quote_end_ms"]))

    def test_vectors_are_float16_minilm_columns_and_search_like_the_padded_ones(self):
        encoder = FakeEncoder()
        self.export(encoder=encoder)
        stored = np.load(self.corpus_dir / "vectors.npy")
        self.assertEqual(((4, 384), np.float16), (stored.shape, stored.dtype))
        corpus = self.published()
        query = np.asarray(encoder.embed_texts(("a really good point",)).vectors[0], dtype=np.float32)
        found = corpus.search(query, limit=4, min_similarity=None, language=None, feed_ids=None, document_ids=None)
        padded = np.pad(stored.astype(np.float32), ((0, 0), (0, 1152)))
        padded /= np.linalg.norm(padded, axis=1, keepdims=True)
        expected = padded @ (query / np.linalg.norm(query))
        by_id = {str(h.chunk_id): i for i, h in enumerate(corpus.hits)}
        for hit in found:
            self.assertAlmostEqual(expected[by_id[str(hit.chunk_id)]], hit.similarity, places=5)
        self.assertEqual(sorted(expected, reverse=True), [h.similarity for h in found])
        calls = encoder.calls
        self.export(encoder=encoder)  # a rerun reads the cache: no texts are embedded again
        self.assertEqual(calls, encoder.calls)
        self.assertTrue(np.array_equal(stored, np.load(self.corpus_dir / "vectors.npy")))

    def test_over_the_budget_whole_episodes_are_kept_most_cited_then_newest(self):
        hits = [own_snapshot.build_hit(row, own_corpus())[0] for row in own_corpus()["rows"][:4]]
        published = {1: 100, 2: 300, 3: 200}
        cited = Counter({str(UUID(int=4)): 2})  # episode 3
        size = {e: sum(own_snapshot.hit_bytes(h) for h in hits if h["episode_id"] == e) for e in (1, 2, 3)}
        self.assertEqual([3, 2, 1], own_snapshot.episode_order(hits, published, cited))
        for budget, kept in ((None, [3, 2, 1]), (size[3] + size[2], [3, 2]), (size[3] + size[2] + size[1] - 1, [3, 2]),
                             (size[3] - 1, [])):
            with self.subTest(budget=budget):
                chosen, episodes, used = own_snapshot.select(hits, published, cited, budget)
                self.assertEqual(kept, episodes)
                self.assertEqual(sum(size[e] for e in kept), used)
                self.assertEqual(sorted(h["chunk_id"] for h in hits if h["episode_id"] in kept),
                                 [h["chunk_id"] for h in chosen])
        manifest = self.export(budget=size[3] + 100, cited=cited)
        self.assertEqual((1, 1, 1), (manifest["exported_chunks"], manifest["cited_chunks_exported"],
                                     manifest["exported_episodes"]))
        with self.assertRaises(SystemExit):
            self.export(budget=10)

    def test_the_runs_citations_are_counted_and_ordered(self):
        run = self.root / "run"
        write_attempts(run, {str(UUID(int=2)): 1, str(UUID(int=1)): 3, str(UUID(int=3)): 1})
        counts = own_snapshot.cited_chunks([run])
        self.assertEqual({str(UUID(int=1)): 6, str(UUID(int=2)): 2, str(UUID(int=3)): 2}, dict(counts))
        self.assertEqual([str(UUID(int=n)) for n in (1, 2, 3)], own_snapshot.by_citation(counts))


class OwnPackageTests(unittest.TestCase):
    """The own package folder, built from an exported corpus without the database, served from a fresh interpreter."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {"COACH_ADMIN_RUN": "", "COACH_ADMIN_RESULTS": "", "COACH_SYSTEM": ""})
        env.start()
        self.addCleanup(env.stop)
        own_snapshot.export(self.root / "corpus", own_corpus(), cited=Counter(), budget=None, encoder=FakeEncoder(),
                            cache=None, log=lambda line: None)
        self.encoder = self.root / "encoder"
        (self.encoder / "onnx").mkdir(parents=True)
        (self.encoder / "tokenizer.json").write_text("{}")
        (self.encoder / "onnx/model.onnx").write_bytes(b"onnx")
        grades = [grade("t-one", "baseline", True), grade("t-one", "agent", False)]
        run, tasks = write_run(self.root / "results", "pre", pre_lock_rows(), grades)
        write(build(run, tasks), self.root / "admin-data", split="never")
        self.out = self.root / "own"

    def package(self, *extra):
        argv = ["package", "--out", str(self.out), "--corpus-from", str(self.root / "corpus"), "--encoder-dir",
                str(self.encoder), "--deps-mb", "206", "--admin-data", str(self.root / "admin-data/data.json"), *extra]
        lines = []
        own_snapshot.build_package(own_snapshot.parse_args(argv), log=lines.append)
        return lines

    def test_the_package_has_our_entry_corpus_admin_and_config_but_no_apk(self):
        printed = self.package()
        self.assertEqual((package.ROOT / own_snapshot.ENTRY).read_text(), (self.out / "api/search.py").read_text())
        requirements = (self.out / "requirements.txt").read_text()
        self.assertIn("anthropic==", requirements)
        for absent in ("openai==", "faster-whisper==", "huggingface-hub==", "-r "):
            self.assertNotIn(absent, requirements)
        self.assertEqual(package.vercel_config(), json.loads((self.out / "vercel.json").read_text()))
        self.assertEqual(300, package.vercel_config()["functions"]["api/search.py"]["maxDuration"])
        for name in (*package.FUNCTION_FILES, "corpus/passages.json.gz", "corpus/vectors.npy", "corpus/alignments.json",
                     "encoder/tokenizer.json", "encoder/onnx/model.onnx", "public/index.html",
                     "public/admin/index.html", "public/admin/data.json", ".python-version", ".vercelignore"):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertFalse((self.out / "public/downloads").exists())
        data = AdminData.model_validate_json((self.out / "public/admin/data.json").read_text(encoding="utf-8"))
        self.assertEqual("pre", data.meta.run.id)
        self.assertTrue(any(line.startswith("  function total: ") for line in printed))
        self.assertTrue(any("passages: 4 of 4 approved chunks" in line for line in printed))
        with self.assertRaises(SystemExit):  # over the limit
            self.package("--max-mb", "100")
        with self.assertRaises(SystemExit):  # never package.py's default folder
            own_snapshot.build_package(own_snapshot.parse_args(["package", "--out", str(package.DEFAULT_OUT)]))
        self.assertNotEqual(package.DEFAULT_OUT, own_snapshot.DEFAULT_OUT)

    def test_the_packaged_function_answers_from_the_bundled_files(self):
        self.package()
        env = {k: v for k, v in os.environ.items()
               if k != "PYTHONPATH" and not k.startswith(("COACH_", "LLM_", "DATABASE_URL", "POSTGRES_"))}
        done = subprocess.run([sys.executable, "-P", "-c", SERVE_OWN_PACKAGE, str(UUID(int=1))], cwd=self.out, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr[-2000:])
        result = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual("frontend/server.py", result["server_file"])
        self.assertEqual(["anthropic", "claude-haiku-5-5", "local"], result["settings"])
        self.assertTrue(result["encoder_dir"].endswith("/encoder"))
        self.assertIn("/api/search", result["routes"])
        self.assertEqual([200, "ready", "asr", 200_000], result["alignment"])
        self.assertEqual([200, "unavailable"], result["not_aligned"])
        self.assertEqual(4, result["hits"])


SERVE_OWN_PACKAGE = r"""
import json, os, runpy, sys
from pathlib import Path
pkg = Path.cwd().resolve()
sys.path.insert(0, str(pkg))
app = runpy.run_path(str(pkg / "api/search.py"))["app"]
from fastapi.testclient import TestClient
import frontend.server as packaged
from frontend.vercel.coach import PublishedCorpus
client = TestClient(app, base_url="https://coach.example")
ready = client.get("/api/audio/alignment", params={"chunk_id": sys.argv[1], "quote": "that is"})
other = client.get("/api/audio/alignment", params={"chunk_id": "00000000-0000-0000-0000-000000000002", "quote": "x"})
print(json.dumps({
    "server_file": str(Path(packaged.__file__).resolve().relative_to(pkg)),
    "settings": [os.environ["LLM_PROVIDER"], os.environ["LLM_MODEL"], os.environ["EMBEDDING_PROVIDER"]],
    "encoder_dir": os.environ["COACH_LOCAL_MODEL_DIR"],
    "routes": sorted(getattr(r, "path", "") for r in app.routes),
    "alignment": [ready.status_code, ready.json()["status"], ready.json()["method"], ready.json()["quote_start_ms"]],
    "not_aligned": [other.status_code, other.json()["status"]],
    "hits": len(PublishedCorpus().hits),
}))
"""


if __name__ == "__main__":
    unittest.main()
