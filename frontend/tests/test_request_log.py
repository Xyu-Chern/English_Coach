"""The live request log, mode switch and daily cap (frontend/request_log.py) behind POST /api/search, GET
/admin/requests.json and GET/POST /admin/mode. With the local PostgreSQL (translation_agent_demo/.env
DATABASE_URL) each database test works in its own schema, dropped afterwards; without one they are skipped."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfoNotFoundError

from fastapi.testclient import TestClient
from psycopg import sql

from frontend import request_log
from frontend.admin_data import Answer, LiveRequest, Span
from frontend.request_log import DailyLimit, ModeSwitch, RequestStore, day_zone
from frontend.server import NDJSON, make_app
from frontend.staged import QuickAnswerer
from frontend.tests.test_staged import CLEAN_ENV, FakeModel, Gate, join_quick, lines, scripted, wait_for_workers

QUESTION = "我想礼貌地建议先把这个话题放一放，应该怎么说？"  # the scripted coach answers any question the same way
ENV_FILE = Path(__file__).resolve().parents[2] / "translation_agent_demo" / ".env"
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

    def test_without_a_database_nothing_is_written_and_the_mode_is_the_environments(self):
        environ = {"POSTGRES_URL": "postgresql://p@h/db", "DATABASE_URL": "postgresql://d@h/db"}
        self.assertEqual(request_log.database_url(environ), "postgresql://d@h/db")
        self.assertEqual(request_log.database_url({**environ, "COACH_LOG_DATABASE_URL": "postgresql://c@h/db"}),
                         "postgresql://c@h/db")
        self.assertEqual(request_log.database_url({"POSTGRES_URL": "postgresql://p@h/db"}), "postgresql://p@h/db")
        self.assertFalse(RequestStore.from_environment({}).enabled)
        self.assertFalse(RequestStore.from_environment({"DATABASE_URL": "mysql://x@h/db"}, log=lambda _: None).enabled)
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline"}):
            client = self.app()
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)
        listing = client.get("/admin/requests.json")
        self.assertEqual((listing.status_code, listing.headers["x-robots-tag"]), (200, "noindex"))
        self.assertEqual(listing.json(), {"schema_version": 1, "source": "live", "enabled": False,
                                          "requests": [], "traces": {}, "answers": {}})
        view = client.get("/admin/mode")
        self.assertEqual(view.json(), {"mode": "baseline", "source": "env", "updated_at": None, "writable": False,
                                       "token_required": False, "history": []})
        self.assertEqual(view.headers["x-robots-tag"], "noindex")
        refused = client.post("/admin/mode", json={"mode": "agent"})
        self.assertEqual((refused.status_code, refused.json()), (409, {"detail": "no_database"}))
        for body in ({"mode": "agent_locked"}, {"mode": 1}, {}, ["agent"]):
            with self.subTest(body=body):
                refused = client.post("/admin/mode", json=body)
                self.assertEqual((refused.status_code, refused.json()), (400, {"detail": "invalid_mode"}))
        self.assertEqual(client.post("/admin/mode", content=b"not json").status_code, 400)
        self.assertEqual(client.post("/admin/mode", headers={"Origin": "https://other.invalid"},
                                     json={"mode": "agent"}).status_code, 403)

    def test_the_admin_token_is_needed_only_when_it_is_set(self):
        with patch.dict(os.environ, {"COACH_ADMIN_TOKEN": "s3cret"}):
            client = self.app()
            self.assertTrue(client.get("/admin/mode").json()["token_required"])
            self.assertEqual(client.get("/admin/requests.json").status_code, 200)  # viewing stays open (D4)
            for headers in ({}, {"X-Admin-Token": "wrong"}):
                refused = client.post("/admin/mode", headers=headers, json={"mode": "baseline"})
                self.assertEqual((refused.status_code, refused.json()), (401, {"detail": "token_required"}))
            # the right token passes the check; without a database the change is refused after it
            passed = client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"}, json={"mode": "baseline"})
            self.assertEqual(passed.status_code, 409)
            self.assertEqual(client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"},
                                         json={"mode": "x"}).status_code, 400)

    def test_a_database_that_is_down_changes_nothing_for_the_learner(self):
        errors = []
        client = self.app(RequestStore(DOWN_URL, log=errors.append))
        response = client.post("/api/search", headers={"Accept": NDJSON}, json={"question": QUESTION})
        self.assertEqual([line["type"] for line in lines(response)], ["first", "final"])
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)
        self.assertEqual(self.runs[0][1].system, "agent")  # the environment's mode
        listing = client.get("/admin/requests.json").json()
        self.assertEqual((listing["enabled"], listing["requests"], listing["error"]), (True, [], "database_unavailable"))
        self.assertTrue(errors and all(DOWN_URL not in line and QUESTION not in line for line in errors))
        view = client.get("/admin/mode").json()
        self.assertEqual((view["mode"], view["source"], view["writable"], view["history"]), ("agent", "env", True, []))
        self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).status_code, 503)

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

    def test_a_mode_change_applies_to_the_next_request_and_is_kept_in_the_history(self):
        store = database_store(self)
        client = self.app(store)
        self.assertEqual(client.get("/admin/mode").json()["source"], "env")
        client.post("/api/search", json={"question": QUESTION})
        changed = client.post("/admin/mode", json={"mode": "baseline"})
        self.assertEqual(changed.status_code, 200)
        view = changed.json()
        self.assertEqual((view["mode"], view["source"], view["writable"]), ("baseline", "db", True))
        self.assertIsNotNone(view["updated_at"])
        self.assertEqual([(h["from"], h["to"]) for h in view["history"]], [("agent", "baseline")])
        client.post("/api/search", json={"question": QUESTION})
        self.assertEqual([run[1].system for run in self.runs], ["agent", "baseline"])
        self.assertEqual([(r["mode"], r["mode_source"]) for r in store.recent(5)], [("baseline", "db"), ("agent", "env")])
        # the same mode again is no change; back to agent is one more
        client.post("/admin/mode", json={"mode": "baseline"})
        back = client.post("/admin/mode", json={"mode": "agent"}).json()
        self.assertEqual([(h["from"], h["to"]) for h in back["history"]], [("baseline", "agent"), ("agent", "baseline")])
        # another process sees the database's value once its cache is older than the TTL
        clock = [0.0]
        other = ModeSwitch(store, "baseline", ttl=10, clock=lambda: clock[0])
        self.assertEqual(other.current()[:2], ("agent", "db"))
        store.set_mode("baseline", "baseline")
        self.assertEqual(other.current()[0], "agent")  # cached
        clock[0] = 10.0
        self.assertEqual(other.current()[0], "baseline")
        with patch.dict(os.environ, {"COACH_ADMIN_TOKEN": "s3cret"}):
            ok = client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"}, json={"mode": "agent"})
            self.assertEqual((ok.status_code, ok.json()["mode"], ok.json()["token_required"]), (200, "agent", True))

    def test_the_sql_file_creates_the_tables_and_every_log_column(self):
        script = request_log.SQL_FILE.read_text(encoding="utf-8")
        for table in ("coach_request_log", "coach_settings", "coach_mode_changes", "coach_daily_usage"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", script)
        for column in request_log.LOG_COLUMNS:
            self.assertIn(f"\n    {column} ", script)

    # ------------------------------------------------------------ the mode switch on a public deployment
    def test_on_vercel_without_a_token_nobody_switches_the_mode(self):
        with patch.dict(os.environ, {"VERCEL": "1"}):
            client = self.app()
            self.assertEqual((client.get("/admin/mode").json()["writable"], client.get("/admin/mode").json()
                              ["token_required"]), (False, False))
            self.assertEqual(client.get("/admin/requests.json").status_code, 200)  # only the switch is locked
            for headers in ({}, {"X-Admin-Token": "anything"}):
                refused = client.post("/admin/mode", headers=headers, json={"mode": "baseline"})
                self.assertEqual((refused.status_code, refused.json()), (403, {"detail": "admin_token_required"}))
                self.assertEqual(refused.headers["x-robots-tag"], "noindex")
            with patch.dict(os.environ, {"COACH_ADMIN_TOKEN": "s3cret"}):  # a token opens it like anywhere
                self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).status_code, 401)
                self.assertEqual(client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"},
                                             json={"mode": "baseline"}).status_code, 409)  # no database here
        # a local server (no VERCEL) without a token stays open: only the missing database refuses
        self.assertEqual(self.app().post("/admin/mode", json={"mode": "baseline"}).status_code, 409)

    def test_on_vercel_with_a_database_the_mode_stays_unless_the_token_is_sent(self):
        store = database_store(self)
        with patch.dict(os.environ, {"VERCEL": "1"}):
            client = self.app(store)
            self.assertFalse(client.get("/admin/mode").json()["writable"])
            self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).status_code, 403)
            self.assertIsNone(store.mode_setting())
            self.assertEqual(store.history(), [])
            with patch.dict(os.environ, {"COACH_ADMIN_TOKEN": "s3cret"}):
                self.assertEqual(client.get("/admin/mode").json()["writable"], True)
                changed = client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"}, json={"mode": "baseline"})
                self.assertEqual((changed.status_code, changed.json()["mode"]), (200, "baseline"))


SEOUL_EVENING = datetime(2026, 11, 22, 14, 59, 59, tzinfo=timezone.utc)  # 23:59:59 in Seoul
LIMIT_HEADERS = ("x-coach-daily-limit", "x-coach-daily-remaining")


class DailyLimitTests(unittest.TestCase):
    """COACH_DAILY_LIMIT: one count per POST /api/search for everyone, before any model call, on both
    transports; fail closed without a database."""

    def setUp(self):
        env = patch.dict(os.environ, {**CLEAN_ENV, "COACH_ADMIN_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.addCleanup(join_quick)
        self.logs = []
        self.now = [SEOUL_EVENING]

    def daily(self, store, limit, zone="Asia/Seoul"):
        return DailyLimit(limit, store, zone=zone, now=lambda: self.now[0])

    def app(self, store, daily=None, quick=None, gate=None):
        stream, runs = scripted("two_verified_filled", gate)
        client = TestClient(make_app(stream=stream, store=store, daily=daily, quick=quick, log=self.logs.append,
                                     serve_ui=False), base_url="http://localhost")
        return client, runs

    def ask(self, client, stream):
        return client.post("/api/search", headers={"Accept": NDJSON} if stream else {}, json={"question": QUESTION})

    def counts(self, store) -> dict:
        return {r["day"]: r["count"] for r in store._fetch("SELECT day, count FROM coach_daily_usage", ())}

    def test_the_settings_and_without_a_limit_nothing_is_counted(self):
        store = RequestStore(None)
        self.assertFalse(DailyLimit.from_environment(store, {}).enabled)
        self.assertFalse(DailyLimit.from_environment(store, {"COACH_DAILY_LIMIT": " "}).enabled)
        daily = DailyLimit.from_environment(store, {"COACH_DAILY_LIMIT": " 10 "})
        self.assertEqual((daily.limit, str(daily.zone)), (10, "Asia/Seoul"))
        self.assertEqual(str(DailyLimit.from_environment(store, {"COACH_DAILY_LIMIT": "0", "COACH_DAILY_TZ": "UTC"})
                             .zone), "UTC")
        for environ in ({"COACH_DAILY_LIMIT": "ten"}, {"COACH_DAILY_LIMIT": "-1"}, {"COACH_DAILY_LIMIT": "1.5"},
                        {"COACH_DAILY_LIMIT": "٣"}, {"COACH_DAILY_LIMIT": "10000001"},
                        {"COACH_DAILY_LIMIT": "10", "COACH_DAILY_TZ": "Mars/Base"}):
            with self.subTest(environ=environ), self.assertRaises(ValueError):
                DailyLimit.from_environment(store, environ)
        with patch.dict(os.environ, {"COACH_DAILY_LIMIT": "many"}), self.assertRaises(ValueError):
            make_app(stream=scripted("three_verified")[0], serve_ui=False)  # a wrong value stops the start
        # no limit: every request runs, nothing is counted and no header is sent
        db = database_store(self)
        client, runs = self.app(db)
        for i in range(4):
            response = self.ask(client, stream=i % 2 == 0)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(set(LIMIT_HEADERS) & set(response.headers))
        self.assertEqual(len(runs), 4)
        self.assertEqual(self.counts(db), {})

    def test_under_at_and_over_the_limit_on_both_transports(self):
        store = database_store(self)
        gate = Gate(at=1)  # the coach's first call waits until the quick line is queued (as in test_staged)
        quick = QuickAnswerer(FakeModel(wait_for=gate.entered))
        client, runs = self.app(store, self.daily(store, 3), quick=quick, gate=gate)
        # one request is one count: its quick line, first answer and continuation do not count apart
        held = {}
        worker = threading.Thread(target=lambda: held.update(r=self.ask(client, True)))
        worker.start()
        self.assertTrue(gate.entered.wait(5))
        join_quick()
        gate.opened.set()
        worker.join(5)
        streamed = held["r"]
        self.assertEqual([line["type"] for line in lines(streamed)], ["quick", "first", "final"])
        self.assertEqual(self.counts(store), {date(2026, 11, 22): 1})
        answered = [streamed, self.ask(client, False), self.ask(client, True)]
        self.assertEqual([(r.status_code, r.headers["x-coach-daily-limit"], r.headers["x-coach-daily-remaining"])
                          for r in answered], [(200, "3", "2"), (200, "3", "1"), (200, "3", "0")])
        self.assertTrue(answered[2].headers["content-type"].startswith(NDJSON))
        for stream in (False, True):  # over the limit: a refusal before any line and without a model call
            with self.subTest(stream=stream):
                refused = self.ask(client, stream)
                self.assertEqual((refused.status_code, refused.json()), (429, {"detail": "daily_limit"}))
                self.assertEqual((refused.headers["x-coach-daily-limit"], refused.headers["x-coach-daily-remaining"]),
                                 ("3", "0"))
        self.assertEqual(len(runs), 3)
        join_quick()
        self.assertLessEqual(len(quick.model.calls), 2)  # at most the two streams that ran; never a refusal
        self.assertEqual([json.loads(line)["status"] for line in self.logs], ["ok"] * 3 + ["daily_limit"] * 2)
        rows = store.recent(10)
        self.assertEqual([(r["status"], r["error_code"]) for r in rows[:2]], [("daily_limit", "daily_limit")] * 2)
        # admin reads and the mode switch are not counted
        client.get("/admin/mode")
        client.get("/admin/requests.json")
        self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).status_code, 200)
        self.assertEqual(self.counts(store), {date(2026, 11, 22): 5})
        # a browser on an allowed origin may read the headers
        browser = client.post("/api/search", headers={"Origin": "http://localhost"}, json={"question": QUESTION})
        exposed = browser.headers["access-control-expose-headers"].lower()
        self.assertTrue(all(name in exposed for name in LIMIT_HEADERS))

    def test_the_day_starts_again_at_midnight_in_its_time_zone(self):
        store = database_store(self)
        client, runs = self.app(store, self.daily(store, 1))
        self.assertEqual(self.ask(client, True).status_code, 200)
        self.assertEqual(self.ask(client, False).status_code, 429)
        self.now[0] = SEOUL_EVENING + timedelta(seconds=1)  # midnight in Seoul, 15:00 UTC
        again = self.ask(client, False)
        self.assertEqual((again.status_code, again.headers["x-coach-daily-remaining"]), (200, "0"))
        self.assertEqual(self.ask(client, True).status_code, 429)
        self.assertEqual(self.counts(store), {date(2026, 11, 22): 2, date(2026, 11, 23): 2})
        self.assertEqual(len(runs), 2)
        # in UTC the same instant is still the 22nd
        self.assertEqual(self.daily(store, 1, "UTC").today(), date(2026, 11, 22))
        # without a time zone database the default zone still works (no daylight saving time in Seoul)
        with patch("frontend.request_log.ZoneInfo", side_effect=ZoneInfoNotFoundError("none")):
            self.assertEqual(SEOUL_EVENING.astimezone(day_zone("Asia/Seoul")).hour, 23)
            with self.assertRaises(ValueError):
                day_zone("Europe/Paris")

    def test_a_limit_without_a_reachable_database_refuses_every_request(self):
        down = RequestStore(DOWN_URL, log=lambda line: None)
        for store in (down, RequestStore(None)):
            client, runs = self.app(store, self.daily(store, 10))
            for stream in (False, True):
                with self.subTest(store=store.url, stream=stream):
                    refused = self.ask(client, stream)
                    self.assertEqual((refused.status_code, refused.json()), (503, {"detail": "daily_limit_unavailable"}))
                    self.assertEqual(refused.headers["x-coach-daily-limit"], "10")
                    self.assertNotIn("x-coach-daily-remaining", refused.headers)
            self.assertEqual(runs, [])  # never unmetered
        self.assertEqual([json.loads(line)["error_code"] for line in self.logs], ["daily_limit_unavailable"] * 4)
        # the same deployment from the environment: COACH_DAILY_LIMIT set, no database URL
        with patch.dict(os.environ, {"COACH_DAILY_LIMIT": "10"}):
            client, runs = self.app(None)
        self.assertEqual(self.ask(client, True).status_code, 503)
        self.assertEqual(runs, [])

    def test_the_vercel_function_reads_the_limit_and_locks_the_mode(self):
        """frontend/vercel/index.py as deployed (VERCEL set) with COACH_DAILY_LIMIT and no database URL."""
        no_database = {name: "" for name in request_log.URL_VARIABLES}
        with patch.dict(os.environ, {**no_database, "VERCEL": "1", "COACH_DAILY_LIMIT": "10"}):
            sys.modules.pop("frontend.vercel.index", None)
            index = importlib.import_module("frontend.vercel.index")
            self.addCleanup(sys.modules.pop, "frontend.vercel.index", None)
            with patch("frontend.vercel.coach.dependencies", side_effect=AssertionError("the coach ran")), \
                    patch("builtins.print"):
                client = TestClient(index.app, base_url="https://coach.example")
                refused = client.post("/api/search", headers={"Accept": NDJSON}, json={"question": QUESTION})
            self.assertEqual((refused.status_code, refused.json()), (503, {"detail": "daily_limit_unavailable"}))
            self.assertEqual(index.app.state.daily.limit, 10)
            self.assertFalse(client.get("/admin/mode").json()["writable"])
            self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).json(),
                             {"detail": "admin_token_required"})

    def test_parallel_counts_are_exact(self):
        store = database_store(self)
        self.assertTrue(store.ensure())
        day = date(2026, 11, 22)
        with ThreadPoolExecutor(max_workers=16) as pool:
            counts = list(pool.map(lambda _: store.count_request(day), range(40)))
        self.assertEqual(sorted(counts), list(range(1, 41)))  # each request its own number
        self.assertEqual(self.counts(store), {day: 40})

    def test_parallel_requests_on_separate_instances_share_one_limit(self):
        """Six processes (each its own slot) against one database and a limit of 4: exactly 4 run."""
        store = database_store(self)
        self.assertTrue(store.ensure())
        apps = [self.app(store, self.daily(store, 4)) for _ in range(6)]
        start = threading.Barrier(len(apps))

        def ask(i):
            client = apps[i][0]
            start.wait(5)
            return self.ask(client, i % 2 == 0)
        with ThreadPoolExecutor(max_workers=len(apps)) as pool:
            responses = list(pool.map(ask, range(len(apps))))
        self.assertEqual(sorted(r.status_code for r in responses), [200] * 4 + [429] * 2)
        self.assertEqual(sorted(r.headers["x-coach-daily-remaining"] for r in responses), ["0", "0", "0", "1", "2", "3"])
        self.assertEqual(sum(len(runs) for _, runs in apps), 4)
        self.assertEqual(self.counts(store), {date(2026, 11, 22): 6})


if __name__ == "__main__":
    unittest.main()
