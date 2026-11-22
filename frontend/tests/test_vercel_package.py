"""The Vercel package's /admin (D4, D5): the page and an evaluation run's data as static files beside the app.

Builds preview packages (--skip-apk --skip-search-data: no Android SDK, database or encoder needed) into a
temporary folder, then serves one the way Vercel does, in a fresh interpreter that sees only the package.
"""
from contextlib import redirect_stderr, redirect_stdout
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

from frontend import admin_data
from frontend.admin_data import AdminData, build, write
from frontend.tests.test_admin_data import grade, pre_lock_rows, write_run
from frontend.vercel import coach, package

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


if __name__ == "__main__":
    unittest.main()
