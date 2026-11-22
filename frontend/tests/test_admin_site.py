"""The local server's /admin page and data (D4, D5), and the folders COACH_ADMIN_DIR / COACH_ADMIN_DATA swap in."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from frontend import server
from frontend.server import ADMIN_DATA_FILES, admin_folders, make_app

PAGE = "<!doctype html><title>{}</title>"


def answer(question):
    raise AssertionError("the admin page must not ask the coach")


class AdminSiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {"COACH_PAIR_CODE": "", "COACH_WEB_ORIGIN": "", "COACH_ADMIN_DIR": "",
                                      "COACH_ADMIN_DATA": "", "COACH_SYSTEM": "", "COACH_CONTINUATION": ""})
        env.start()
        self.addCleanup(env.stop)
        self.page = self.folder("page", {"index.html": PAGE.format("default page"), "admin.js": "// js",
                                         "data.json": json.dumps({"run": "page"})})
        default = patch.object(server, "ADMIN", self.page)
        default.start()
        self.addCleanup(default.stop)

    def folder(self, name, files):
        folder = self.root / name
        folder.mkdir()
        for file, text in files.items():
            (folder / file).write_text(text, encoding="utf-8")
        return folder

    def client(self, **env):
        with patch.dict(os.environ, env):
            return TestClient(make_app(answer), base_url="http://localhost")

    def test_the_page_and_its_data_are_served_next_to_the_learner_app(self):
        client = self.client()
        redirect = client.get("/admin", follow_redirects=False)
        self.assertEqual((307, "admin/"), (redirect.status_code, redirect.headers["location"]))
        self.assertIn("default page", client.get("/admin").text)  # the redirect lands on the page
        self.assertEqual("// js", client.get("/admin/admin.js").text)
        data = client.get("/admin/data.json")
        self.assertEqual((200, {"run": "page"}), (data.status_code, data.json()))
        self.assertEqual(("application/json", "no-cache"),
                         (data.headers["content-type"], data.headers["cache-control"]))
        missing = client.get("/admin/data-traces.json")
        self.assertEqual((404, "admin_data_missing"), (missing.status_code, missing.json()["detail"]))
        self.assertIn("Phrase Room", client.get("/").text)  # the learner app is unchanged
        self.assertEqual(422, client.post("/api/search", json={"question": " "}).status_code)  # the API is still there
        self.assertEqual((self.page.resolve(), self.page.resolve()),
                         tuple(p.resolve() for p in client.app.state.admin))

    def test_a_preview_swaps_the_page_and_the_data_folders(self):
        design = self.folder("design-b", {"index.html": PAGE.format("design b"), "data.json": "{}"})
        run = self.folder("run-locked", {"data.json": json.dumps({"run": "locked"}),
                                         "data-traces.json": json.dumps({"traces": {}})})
        client = self.client(COACH_ADMIN_DIR=str(design), COACH_ADMIN_DATA=str(run))
        self.assertIn("design b", client.get("/admin/").text)
        self.assertEqual({"run": "locked"}, client.get("/admin/data.json").json())  # not the page folder's
        self.assertEqual({"traces": {}}, client.get("/admin/data-traces.json").json())
        only_data = self.client(COACH_ADMIN_DATA=str(run))
        self.assertIn("default page", only_data.get("/admin/").text)
        self.assertEqual({"run": "locked"}, only_data.get("/admin/data.json").json())

    def test_a_folder_that_is_named_must_exist_and_hold_data(self):
        empty = self.folder("empty", {})
        for env in ({"COACH_ADMIN_DIR": str(self.root / "nope")}, {"COACH_ADMIN_DATA": str(self.root / "nope")},
                    {"COACH_ADMIN_DATA": str(empty)}, {"COACH_ADMIN_DIR": str(self.page / "index.html")}):
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(ValueError):
                make_app(answer)
        self.assertEqual((self.page.resolve(), self.page.resolve()),
                         admin_folders({"COACH_ADMIN_DIR": f" {self.page} "}))

    def test_without_a_page_or_a_ui_there_is_no_admin(self):
        with patch.object(server, "ADMIN", self.root / "missing"):
            client = self.client()
            self.assertIsNone(client.app.state.admin)
            self.assertEqual(404, client.get("/admin/").status_code)
            self.assertEqual(404, client.get("/admin/data.json").status_code)
        with patch.dict(os.environ, {"COACH_ADMIN_DIR": str(self.root / "nope")}):
            function = TestClient(make_app(answer, serve_ui=False, public_access=True), base_url="https://x.example")
        self.assertIsNone(function.app.state.admin)  # the Vercel function: Vercel serves /admin as static files
        self.assertEqual(404, function.get("/admin/").status_code)

    def test_every_admin_response_is_marked_noindex_and_the_api_is_not(self):
        client = self.client()
        for path in ("/admin", "/admin/", "/admin/admin.js", "/admin/data.json", "/admin/data-traces.json"):
            with self.subTest(path=path):
                response = client.get(path, follow_redirects=False)
                self.assertEqual("noindex", response.headers.get("x-robots-tag"))
        self.assertNotIn("x-robots-tag", client.get("/").headers)
        self.assertNotIn("x-robots-tag", client.post("/api/search", json={"question": " "}).headers)

    def test_the_repository_page_reads_its_data_relatively_and_as_text(self):
        folder = Path(server.__file__).with_name("admin")
        html = (folder / "index.html").read_text(encoding="utf-8")
        # The page is index.html plus the ES modules it imports (admin.js loads data.json, i18n.js holds the text).
        code = "\n".join(path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.js")))
        self.assertIn('<meta name="robots" content="noindex', html)
        self.assertIn('<script type="module" src="admin.js">', html)
        self.assertIn("app.noProtection", code)  # D4: open, and the page says so in each language
        for text in ("누구나 볼 수 있음", "知道网址的人都能查看", "anyone with the URL can view"):
            self.assertIn(text, code)
        self.assertIn('fetch("data.json"', code)
        self.assertIn("schema_version !== 1", code)
        for source in (html, code):
            self.assertNotIn('"/admin', source)
            self.assertNotIn("innerHTML", source)
        self.assertEqual(("data.json", "data-traces.json"), ADMIN_DATA_FILES)


if __name__ == "__main__":
    unittest.main()
