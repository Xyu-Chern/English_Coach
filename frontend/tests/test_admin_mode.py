"""GET and POST /admin/mode: the database's mode over COACH_SYSTEM, the optional admin token, and the next
request running in the new mode. Database tests use their own schema on the local PostgreSQL."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from frontend.request_log import ModeSwitch, RequestStore
from frontend.server import make_app
from frontend.tests.test_request_log import DOWN_URL, QUESTION, database_store
from frontend.tests.test_stream import CLEAN_ENV, scripted, wait_for_workers


class AdminModeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {**CLEAN_ENV, "COACH_ADMIN_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.logs = []

    def app(self, store=None, **kwargs):
        stream, self.runs = scripted("two_verified_filled")
        return TestClient(make_app(stream=stream, store=store, log=self.logs.append, serve_ui=False, **kwargs),
                          base_url="http://localhost")

    def test_without_a_database_the_mode_is_the_environments_and_cannot_change(self):
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline"}):
            client = self.app()
        view = client.get("/admin/mode")
        self.assertEqual(view.json(), {"mode": "baseline", "source": "env", "updated_at": None, "writable": False,
                                       "token_required": False, "history": []})
        self.assertEqual(view.headers["x-robots-tag"], "noindex")
        self.assertEqual(client.post("/admin/mode", json={"mode": "agent"}).status_code, 409)
        self.assertEqual(client.post("/admin/mode", json={"mode": "agent"}).json(), {"detail": "no_database"})
        for body in ({"mode": "agent_locked"}, {"mode": 1}, {}, ["agent"]):
            with self.subTest(body=body):
                refused = client.post("/admin/mode", json=body)
                self.assertEqual((refused.status_code, refused.json()), (400, {"detail": "invalid_mode"}))
        self.assertEqual(client.post("/admin/mode", content=b"not json").status_code, 400)
        self.assertEqual(client.post("/admin/mode", headers={"Origin": "https://other.invalid"},
                                     json={"mode": "agent"}).status_code, 403)

    def test_the_token_is_needed_only_when_it_is_set(self):
        with patch.dict(os.environ, {"COACH_ADMIN_TOKEN": "s3cret"}):
            client = self.app()
            self.assertTrue(client.get("/admin/mode").json()["token_required"])
            for headers in ({}, {"X-Admin-Token": "wrong"}):
                refused = client.post("/admin/mode", headers=headers, json={"mode": "baseline"})
                self.assertEqual((refused.status_code, refused.json()), (401, {"detail": "token_required"}))
            # the right token passes the check; without a database the change is refused after it
            passed = client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"}, json={"mode": "baseline"})
            self.assertEqual(passed.status_code, 409)
            self.assertEqual(client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"},
                                         json={"mode": "x"}).status_code, 400)

    def test_a_database_error_falls_back_to_the_environment(self):
        client = self.app(RequestStore(DOWN_URL, log=lambda _: None))
        view = client.get("/admin/mode").json()
        self.assertEqual((view["mode"], view["source"], view["writable"], view["history"]), ("agent", "env", True, []))
        self.assertEqual(client.post("/admin/mode", json={"mode": "baseline"}).status_code, 503)
        self.assertEqual(client.post("/api/search", json={"question": QUESTION}).status_code, 200)

    def test_a_change_applies_to_the_next_request_and_is_kept_in_the_history(self):
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
            self.assertEqual(client.post("/admin/mode", json={"mode": "agent"}).status_code, 401)
            ok = client.post("/admin/mode", headers={"X-Admin-Token": "s3cret"}, json={"mode": "agent"})
            self.assertEqual((ok.status_code, ok.json()["mode"], ok.json()["token_required"]), (200, "agent", True))


if __name__ == "__main__":
    unittest.main()
