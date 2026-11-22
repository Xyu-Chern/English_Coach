"""The live request log (frontend/request_log.py) behind POST /api/search and GET /admin/requests.json.

With the local PostgreSQL (translation_agent_demo/.env DATABASE_URL) each test works in its own schema,
dropped afterwards; without one those tests are skipped. No paid provider: the scripted staged coach."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import sql

from frontend import request_log
from frontend.admin_data import Answer, LiveRequest, Span
from frontend.request_log import RequestStore
from frontend.server import NDJSON, make_app
from frontend.tests.test_stream import CLEAN_ENV, lines, scripted, wait_for_workers
from frontend.vercel import package

QUESTION = "我想礼貌地建议先把这个话题放一放，应该怎么说？"  # the scripted coach answers any question the same way
ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "translation_agent_demo" / ".env"
DOWN_URL = "postgresql://coach@127.0.0.1:1/coach"  # nothing listens on port 1


def database_store(test: unittest.TestCase) -> RequestStore:
    """A store on the local database in a fresh schema (dropped at cleanup); skips the test without one."""
    schema = f"coach_log_test_{uuid4().hex[:10]}"
    store = RequestStore.from_environment(env_file=ENV_FILE, schema=schema, log=lambda line: None)
    if not store.enabled:
        test.skipTest("no database URL")
    try:
        store._transaction(lambda c: c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))))
    except request_log.StoreError:
        test.skipTest("local PostgreSQL is not running")
    test.addCleanup(store._transaction,
                    lambda c: c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))))
    return store


class RequestLogTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {**CLEAN_ENV, "COACH_ADMIN_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.logs = []

    def app(self, store=None, name="two_verified_filled"):
        stream, self.runs = scripted(name)
        return TestClient(make_app(stream=stream, store=store, log=self.logs.append, serve_ui=False),
                          base_url="http://localhost")

    def test_the_database_url_order_and_no_database(self):
        environ = {"POSTGRES_URL": "postgresql://p@h/db", "DATABASE_URL": "postgresql://d@h/db"}
        self.assertEqual(request_log.database_url(environ), "postgresql://d@h/db")
        self.assertEqual(request_log.database_url({**environ, "COACH_LOG_DATABASE_URL": "postgresql://c@h/db"}),
                         "postgresql://c@h/db")
        self.assertEqual(request_log.database_url({"POSTGRES_URL": "postgresql://p@h/db"}), "postgresql://p@h/db")
        self.assertFalse(RequestStore.from_environment({}).enabled)
        self.assertFalse(RequestStore.from_environment({"DATABASE_URL": "mysql://x@h/db"}, log=lambda _: None).enabled)
        # no store: the learner's answer as before, nothing written, the admin list says it is off
        client = self.app()
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)
        listing = client.get("/admin/requests.json")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), {"schema_version": 1, "source": "live", "enabled": False,
                                          "requests": [], "traces": {}, "answers": {}})
        self.assertEqual(listing.headers["x-robots-tag"], "noindex")

    def test_a_database_that_is_down_changes_nothing_for_the_learner(self):
        errors = []
        store = RequestStore(DOWN_URL, log=errors.append)
        client = self.app(store)
        response = client.post("/api/search", headers={"Accept": NDJSON}, json={"question": QUESTION})
        self.assertEqual([line["type"] for line in lines(response)], ["first", "final"])
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)
        self.assertEqual(self.runs[0][1].system, "agent")  # the environment's mode
        listing = client.get("/admin/requests.json").json()
        self.assertEqual((listing["enabled"], listing["requests"], listing["error"]), (True, [], "database_unavailable"))
        self.assertTrue(errors and all(DOWN_URL not in line and QUESTION not in line for line in errors))

    def test_each_request_is_one_row_and_the_admin_list_shows_it(self):
        store = database_store(self)
        client = self.app(store)
        self.assertTrue(store.ensure())
        streamed = client.post("/api/search", headers={"Accept": NDJSON},
                               json={"question": QUESTION, "context": "SECRET-CONTEXT"})
        self.assertEqual([line["type"] for line in lines(streamed)], ["first", "final"])
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)
        self.assertEqual(client.post("/api/search", json={"question": "x" * 1801}).status_code, 422)  # pydantic
        self.assertEqual(client.post("/api/search", json={"question": "a\u0000b"}).status_code, 422)  # invalid_input
        rows = store.recent(10)
        self.assertEqual([(r["transport"], r["status"]) for r in rows],
                         [("json", "invalid_input"), ("json", "ok"), ("ndjson", "ok")])
        json_row, stream_row = rows[1], rows[2]
        self.assertEqual({k: stream_row[k] for k in ("mode", "mode_source", "verified_first", "added_final",
                                                     "verified_final", "continuation", "llm_calls", "searches")},
                         {"mode": "agent", "mode_source": "env", "verified_first": 2, "added_final": 1,
                          "verified_final": 3, "continuation": "ran", "llm_calls": 4, "searches": 7})
        self.assertEqual(stream_row["question"], QUESTION)
        self.assertNotIn("SECRET-CONTEXT", json.dumps(stream_row, default=str))
        self.assertIsNotNone(stream_row["first_ms"])
        self.assertIsNone(json_row["first_ms"])
        self.assertTrue(stream_row["result"]["trace"] and stream_row["result"]["expressions"])
        self.assertNotIn("answer", stream_row["result"])

        listing = client.get("/admin/requests.json?limit=2")
        self.assertEqual(listing.headers["cache-control"], "no-store")
        data = listing.json()
        self.assertEqual((data["schema_version"], data["source"], data["enabled"]), (1, "live", True))
        newest, older = data["requests"]
        self.assertEqual((newest["status"], newest["error_code"], older["status"]), ("error", "invalid_input", "ok"))
        for request in data["requests"]:
            LiveRequest.model_validate(request)
            Answer.model_validate(data["answers"][request["id"]])
            [Span.model_validate(span) for span in data["traces"][request["id"]]]
        self.assertEqual(older["first_response_ms"], older["total_ms"])  # a JSON client gets all at once
        self.assertEqual((older["transport"], older["mode_source"], older["quick_ms"]), ("json", "env", None))
        self.assertEqual((older["verified_first"], older["added_final"], older["verified_final"], older["mode"],
                          older["language"]), (2, 1, 3, "agent", "zh"))
        self.assertTrue(data["traces"][older["id"]])
        self.assertEqual(len(data["answers"][older["id"]]["final"]), 3)
        self.assertEqual(client.get("/admin/requests.json?limit=0").status_code, 422)

    def test_the_sql_file_is_what_the_server_runs_and_the_vercel_bundle_has_it(self):
        script = request_log.SQL_FILE.read_text(encoding="utf-8")
        for table in ("coach_request_log", "coach_settings", "coach_mode_changes"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", script)
        for column in request_log.LOG_COLUMNS:
            self.assertIn(f"\n    {column} ", script)
        for name in package.FUNCTION_FILES:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertTrue({"frontend/request_log.py", "frontend/sql/request_log.sql",
                         "frontend/admin_data.py"} <= set(package.FUNCTION_FILES))
        rewrites = package.vercel_config()["rewrites"]
        self.assertEqual({r["source"] for r in rewrites},
                         {"/admin/requests.json", "/admin/mode", "/api/audio/alignment"})
        self.assertTrue(all(r["destination"] == "/api/search" for r in rewrites))
        with tempfile.TemporaryDirectory() as temporary, patch("sys.stdout"), patch("sys.stderr"), \
                patch.dict(os.environ, {"COACH_ADMIN_RUN": "", "COACH_SYSTEM": ""}):
            package.main(["--out", temporary, "--skip-apk", "--skip-search-data"])
            requirements = (Path(temporary) / "requirements.txt").read_text()
            self.assertIn("psycopg[binary]==", requirements)
            self.assertTrue((Path(temporary) / "frontend/sql/request_log.sql").is_file())


if __name__ == "__main__":
    unittest.main()
