"""POST /api/search with the staged coach: the JSON reply as before, NDJSON on request, the deadline,
the request slot and the log line. No paid provider: a scripted model and search."""
import asyncio
import importlib
import json
import os
import sys
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx
import uvicorn
from fastapi.testclient import TestClient

from frontend.server import DEADLINE_SECONDS, NDJSON, arguments, make_app
from frontend.staged import CoachMode, StagedCoach
from frontend.tests.test_staged import QUESTION, dependencies
from translation_agent_demo.agents import prompts
from translation_agent_demo.agents.systems.first_stage import DECLINE_NOTES

STREAM = {"Accept": NDJSON}
LEARNER_KEYS = {"expression", "key_phrase", "note", "citation"}
# The variables make_app reads when it starts, cleared so a shell's settings cannot change a test.
CLEAN_ENV = {"COACH_PAIR_CODE": "", "COACH_WEB_ORIGIN": "", "COACH_SYSTEM": "", "COACH_CONTINUATION": "",
             "COACH_DEADLINE_SECONDS": ""}


class Gate:
    """Wraps a scripted model; its call number `at` waits until the test opens the gate."""

    def __init__(self, at):
        self.at, self.calls, self.model = at, 0, None
        self.entered, self.opened = threading.Event(), threading.Event()

    def complete_with_usage(self, **kwargs):
        self.calls += 1
        if self.calls == self.at:
            self.entered.set()
            self.opened.wait(10)
        return self.model.complete_with_usage(**kwargs)


def scripted(name, gate=None):
    """A stream(question, mode, guard) that runs the scenario with fresh fakes; runs lists (question, mode, model, search)."""
    runs = []

    def stream(question, mode, guard):
        deps, model, search = dependencies(name, mode.system)
        if gate is not None:
            gate.model = model
            deps = replace(deps, model=gate)
        runs.append((question, mode, model, search))
        return StagedCoach(deps, mode).stream(question, guard)
    return stream, runs


def lines(response):
    return [json.loads(line) for line in response.text.splitlines()]


def wait_for_workers(seconds=5.0):
    for thread in threading.enumerate():
        if thread.name == "coach-request":
            thread.join(seconds)


class StreamApiTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.logs = []

    def client(self, name, system="agent", *, continuation=True, gate=None, deadline=280.0):
        stream, runs = scripted(name, gate)
        app = make_app(stream=stream, mode=CoachMode(system, continuation), log=self.logs.append,
                       deadline_seconds=deadline)
        return TestClient(app, base_url="http://localhost"), runs

    def log(self, index=-1):
        return json.loads(self.logs[index])

    def ask(self, client, *, stream=False, question=QUESTION, context=""):
        return client.post("/api/search", headers=STREAM if stream else {},
                           json={"question": question, "context": context})

    # ------------------------------------------------------------ order and content
    def test_some_verified_stream_first_then_final_and_json_gets_the_final(self):
        for system in ("agent", "baseline"):
            with self.subTest(system=system):
                client, runs = self.client("two_verified_filled", system)
                response = self.ask(client, stream=True)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers["content-type"].startswith(NDJSON))
                self.assertEqual(response.headers["cache-control"], "no-store")
                first, final = lines(response)
                self.assertEqual(set(first), {"type", "expressions", "pending", "note"})
                self.assertEqual(set(final), {"type", "expressions", "added", "note"})
                self.assertEqual((first["type"], first["pending"], final["type"], final["added"]),
                                 ("first", True, "final", [2]))
                self.assertEqual(len(first["expressions"]), 2)
                self.assertTrue(all(item["citation"] for item in first["expressions"]))
                self.assertEqual(final["expressions"][:2], first["expressions"])
                self.assertTrue(all(set(item) == LEARNER_KEYS for item in final["expressions"]))
                reply = self.ask(client)
                self.assertEqual(reply.status_code, 200)
                self.assertTrue(reply.headers["content-type"].startswith("application/json"))
                self.assertEqual(reply.json(), {"expressions": final["expressions"], "note": None})
                self.assertEqual(len(runs), 2)

    def test_after_a_first_the_stream_never_sends_an_unverified_candidate_but_json_keeps_the_whole_answer(self):
        for system in ("agent", "baseline"):
            with self.subTest(system=system):
                client, _ = self.client("two_verified_unfilled", system)
                first, final = lines(self.ask(client, stream=True))
                self.assertEqual((first["pending"], final["added"]), (True, []))
                self.assertEqual(final["expressions"], first["expressions"])  # the unfilled slot is not sent
                reply = self.ask(client).json()  # an old client gets the answer as before, candidate included
                self.assertEqual(reply["expressions"][:2], first["expressions"])
                self.assertEqual((len(reply["expressions"]), reply["expressions"][2]["citation"]), (3, None))
                stream_log, json_log = self.log(-2), self.log(-1)
                for record in (stream_log, json_log):
                    self.assertEqual((record["verified_first"], record["added_final"], record["verified_final"]),
                                     (2, 0, 2))
                self.assertIsInstance(stream_log["first_ms"], int)
                self.assertIsNone(json_log["first_ms"])  # a JSON client sees its first answer at total_ms

    def test_every_slot_verified_is_one_first_line(self):
        client, runs = self.client("three_verified")
        (first,) = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], len(first["expressions"])), ("first", False, 3))
        self.assertEqual(self.ask(client).json()["expressions"], first["expressions"])
        self.assertEqual(len(runs[0][2].prompts), 2)  # no call after the first stage

    def test_none_verified_or_declined_is_one_final_line(self):
        client, _ = self.client("none_verified_filled")
        (final,) = lines(self.ask(client, stream=True))
        self.assertEqual((final["type"], final["added"], len(final["expressions"])), ("final", [0], 3))
        client, _ = self.client("declined")
        (final,) = lines(self.ask(client, stream=True))
        self.assertEqual(final, {"type": "final", "expressions": [], "added": [],
                                 "note": DECLINE_NOTES["out_of_scope"]})
        self.assertEqual(self.ask(client).json(), {"expressions": [], "note": DECLINE_NOTES["out_of_scope"]})

    def test_errors_before_and_after_the_first_answer(self):
        client, _ = self.client("first_stage_error")
        self.assertEqual(lines(self.ask(client, stream=True)), [{"type": "error", "code": "model_unavailable"}])
        reply = self.ask(client)
        self.assertEqual((reply.status_code, reply.json()), (503, {"detail": "model_unavailable"}))
        client, _ = self.client("continuation_error")
        first, error = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], error), ("first", True,
                                                                     {"type": "error", "code": "model_unavailable"}))
        reply = self.ask(client)  # what was verified first is final: the JSON reply keeps it
        self.assertEqual((reply.status_code, reply.json()["expressions"]), (200, first["expressions"]))

    def test_refusals_come_as_http_errors_before_any_line(self):
        client, runs = self.client("two_verified_filled")
        for stream in (False, True):
            response = self.ask(client, stream=stream, question="bad\x00input")
            self.assertEqual((response.status_code, response.json()), (422, {"detail": "invalid_input"}))
            response = client.post("/api/search", headers={**STREAM, "Origin": "https://other.invalid"},
                                   json={"question": "hello"})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(runs, [])
        self.assertEqual([self.log(i)["status"] for i in range(len(self.logs))], ["invalid_input"] * 2)

    def test_an_accept_header_without_ndjson_or_with_q_zero_gets_json(self):
        client, _ = self.client("three_verified")
        for accept, kind in (("application/json", "application/json"), (f"{NDJSON};q=0", "application/json"),
                             (f"text/html, {NDJSON};q=0.5", NDJSON)):
            with self.subTest(accept=accept):
                response = client.post("/api/search", headers={"Accept": accept}, json={"question": "hello"})
                self.assertTrue(response.headers["content-type"].startswith(kind))

    # ------------------------------------------------------------ deadline and slot
    def test_the_deadline_ends_the_stream_with_timeout_and_keeps_the_first_answer(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                gate = Gate(at=3)  # the first call after the first stage
                client, runs = self.client("two_verified_filled", gate=gate, deadline=0.5)
                started = time.monotonic()
                response = self.ask(client, stream=stream)
                self.assertLess(time.monotonic() - started, 5)
                if stream:
                    first, error = lines(response)
                    self.assertEqual((first["type"], error), ("first", {"type": "error", "code": "timeout"}))
                else:
                    self.assertEqual((response.status_code, len(response.json()["expressions"])), (200, 2))
                record = self.log()
                self.assertEqual((record["status"], record["error_code"], record["continuation"]),
                                 ("timeout", "timeout", "ran"))
                self.assertEqual((record["verified_first"], record["added_final"]), (2, None))
                if stream:
                    self.assertLessEqual(record["first_ms"], record["total_ms"])
                else:
                    self.assertIsNone(record["first_ms"])
                # the slot is free at once; the abandoned work stops at its next call
                gate.opened.set()
                wait_for_workers()
                self.assertEqual(len(runs[0][3].args), 6)  # its next step, a search, was refused
                self.assertEqual(self.ask(client, stream=stream).status_code, 200)

    def test_a_deadline_before_the_first_answer_is_a_timeout_only(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                gate = Gate(at=1)
                client, _ = self.client("two_verified_filled", gate=gate, deadline=0.3)
                response = self.ask(client, stream=stream)
                if stream:
                    self.assertEqual(lines(response), [{"type": "error", "code": "timeout"}])
                else:
                    self.assertEqual((response.status_code, response.json()), (503, {"detail": "timeout"}))
                self.assertEqual((self.log()["status"], self.log()["continuation"], self.log()["first_ms"]),
                                 ("timeout", "none", None))
                gate.opened.set()

    def test_one_request_at_a_time_and_the_slot_returns_when_it_ends(self):
        gate = Gate(at=3)
        client, _ = self.client("two_verified_filled", gate=gate)
        answered = {}
        worker = threading.Thread(target=lambda: answered.update(r=self.ask(client, stream=True)))
        worker.start()
        self.assertTrue(gate.entered.wait(5))
        for stream in (False, True):
            busy = self.ask(client, stream=stream)
            self.assertEqual((busy.status_code, busy.json()), (429, {"detail": "coach_busy"}))
        gate.opened.set()
        worker.join(5)
        self.assertEqual([line["type"] for line in lines(answered["r"])], ["first", "final"])
        self.assertEqual(self.ask(client).status_code, 200)
        self.assertEqual([json.loads(line)["status"] for line in self.logs], ["busy", "busy", "ok", "ok"])

    # ------------------------------------------------------------ log line and mode
    def test_one_log_line_per_request_without_the_answer_or_the_context(self):
        client, _ = self.client("two_verified_filled")
        question = "我想礼貌地建议先把这个话题放一放，等会议结束后再讨论，应该怎么说才自然？请给我几个说法"
        self.ask(client, stream=True, question=question, context="SECRET-CONTEXT")
        self.assertEqual(len(self.logs), 1)
        record = self.log()
        self.assertEqual({k: record[k] for k in ("event", "mode", "continuation_setting", "transport", "status",
                                                 "error_code", "verified_first", "added_final", "verified_final",
                                                 "continuation", "invariant_ok", "llm_calls", "searches",
                                                 "input_tokens", "output_tokens", "disconnected")},
                         {"event": "coach_request", "mode": "agent", "continuation_setting": "on",
                          "transport": "ndjson", "status": "ok", "error_code": None, "verified_first": 2,
                          "added_final": 1, "verified_final": 3, "continuation": "ran", "invariant_ok": True,
                          "llm_calls": 4, "searches": 7, "input_tokens": 40, "output_tokens": 20,
                          "disconnected": False})
        self.assertEqual(record["question_head"], question[:40])
        self.assertLessEqual(record["first_ms"], record["total_ms"])
        self.assertNotIn("SECRET-CONTEXT", self.logs[0])
        self.assertNotIn("Shall we pause here", self.logs[0])  # no answer text
        self.assertLess(len(self.logs[0].encode()), 1024)
        # added_final: 0 without a first answer; verified_final: what the learner ends with
        for name, status, continuation, first, added, final in (("three_verified", "ok", "skipped", 3, 0, 3),
                                                                ("declined", "declined", "none", None, 0, 0),
                                                                ("none_verified_filled", "ok", "ran", 0, 0, 1)):
            with self.subTest(scenario=name):
                client, _ = self.client(name)
                self.ask(client)
                record = self.log()
                self.assertEqual((record["transport"], record["status"], record["continuation"],
                                  record["verified_first"], record["added_final"], record["verified_final"],
                                  record["first_ms"]), ("json", status, continuation, first, added, final, None))

    def test_the_mode_comes_from_the_environment_and_a_wrong_value_stops_the_start(self):
        stream, runs = scripted("two_verified_filled")
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline", "COACH_CONTINUATION": "off"}):
            client = TestClient(make_app(stream=stream, log=self.logs.append), base_url="http://localhost")
        (first,) = lines(self.ask(client, stream=True))
        self.assertEqual((first["type"], first["pending"], len(first["expressions"])), ("first", False, 2))
        self.assertEqual(runs[0][1], CoachMode("baseline", False))
        record = self.log()
        self.assertEqual((record["mode"], record["continuation_setting"], record["continuation"]),
                         ("baseline", "off", "off"))
        for env in ({"COACH_SYSTEM": "agent_locked"}, {"COACH_CONTINUATION": "maybe"}):
            with self.subTest(env=env), patch.dict(os.environ, env), self.assertRaises(ValueError):
                make_app(stream=stream)

    def test_the_vercel_function_follows_the_same_settings(self):
        def load():
            sys.modules.pop("frontend.vercel.index", None)
            return importlib.import_module("frontend.vercel.index")

        with patch.dict(os.environ, {"COACH_SYSTEM": "nonsense"}), self.assertRaises(ValueError):
            load()
        deps, model, search = dependencies("two_verified_unfilled", "baseline")
        with patch.dict(os.environ, {"COACH_SYSTEM": "baseline"}):
            index = load()
            with patch("frontend.vercel.coach.dependencies", return_value=(model, None, None)), \
                    patch("frontend.vercel.coach.SnapshotSearch", return_value=search), \
                    patch("builtins.print", side_effect=lambda line, **_: self.logs.append(line)):
                response = TestClient(index.app, base_url="https://coach.example").post(
                    "/api/search", headers=STREAM, json={"question": QUESTION})
        self.assertEqual([line["type"] for line in lines(response)], ["first", "final"])
        self.assertEqual([p[0] for p in model.prompts][2:], [prompts.REVISE_PROMPT])  # the baseline continued
        self.assertEqual(self.log()["mode"], "baseline")
        sys.modules.pop("frontend.vercel.index", None)


class LiveStreamTests(unittest.TestCase):
    """Through a real uvicorn server: lines arrive while the coach is still working, and a client that
    leaves stops the work."""

    def setUp(self):
        env = patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.logs = []
        self.gate = Gate(at=3)
        stream, self.runs = scripted("two_verified_filled", self.gate)
        app = make_app(stream=stream, mode=CoachMode(), log=self.logs.append, serve_ui=False)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error",
                                                    lifespan="off", access_log=False))
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, self.server, "should_exit", True)
        self.addCleanup(wait_for_workers)
        self.addCleanup(self.gate.opened.set)
        deadline = time.monotonic() + 5
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/api/search"

    def test_the_first_line_arrives_before_the_continuation_ends(self):
        with httpx.Client(timeout=10) as http, \
                http.stream("POST", self.url, headers=STREAM, json={"question": QUESTION}) as response:
            received = response.iter_lines()
            first = json.loads(next(received))
            self.assertEqual((first["type"], first["pending"]), ("first", True))
            self.assertTrue(self.gate.entered.is_set())
            self.assertFalse(self.gate.opened.is_set())  # the continuation is still waiting on the model
            self.gate.opened.set()
            final = json.loads(next(received))
            self.assertEqual((final["type"], final["added"]), ("final", [2]))

    def test_a_client_that_leaves_stops_the_work(self):
        with httpx.Client(timeout=10) as http, \
                http.stream("POST", self.url, headers=STREAM, json={"question": QUESTION}) as response:
            self.assertEqual(json.loads(next(response.iter_lines()))["type"], "first")
        deadline = time.monotonic() + 5
        while not self.logs and time.monotonic() < deadline:
            time.sleep(0.02)
        record = json.loads(self.logs[0])
        self.assertEqual((record["status"], record["disconnected"], record["continuation"]),
                         ("disconnected", True, "ran"))
        self.gate.opened.set()
        wait_for_workers()
        self.assertEqual(len(self.runs[0][3].args), 6)  # the agent's search after the gate was refused


class EarlyDisconnectTests(unittest.TestCase):
    """Raw ASGI: a client gone before the stream's first line still gets its log line, and its work stops
    at its next call, on both of Starlette's disconnect paths."""

    def setUp(self):
        env = patch.dict(os.environ, CLEAN_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(wait_for_workers)
        self.logs = []
        self.gate = Gate(at=1)  # the first model call waits: nothing is ready before the client leaves
        self.addCleanup(self.gate.opened.set)
        stream, self.runs = scripted("two_verified_filled", self.gate)
        self.app = make_app(stream=stream, mode=CoachMode(), log=self.logs.append, serve_ui=False)

    def call(self, spec_version, send):
        body = json.dumps({"question": QUESTION}).encode()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": spec_version}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/api/search", "raw_path": b"/api/search",
                 "query_string": b"", "root_path": "", "server": ("localhost", 80), "client": ("127.0.0.1", 1),
                 "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"),
                             (b"accept", NDJSON.encode()), (b"content-length", str(len(body)).encode())]}
        messages = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            await asyncio.sleep(0)
            return messages.pop(0) if messages else {"type": "http.disconnect"}  # gone at once

        async def run():
            try:
                await self.app(scope, receive, send)
            except Exception:  # spec 2.4: the failed send surfaces as ClientDisconnect
                pass
        asyncio.run(run())

    def check_closed(self):
        self.assertEqual(len(self.logs), 1)  # logged when the response ended, not at the deadline
        record = json.loads(self.logs[0])
        self.assertEqual((record["status"], record["disconnected"], record["continuation"], record["first_ms"]),
                         ("disconnected", True, "none", None))
        self.gate.opened.set()
        wait_for_workers()
        # at most the model call under way when the client left; every later call and search was refused
        self.assertLessEqual(self.gate.calls, 1)
        self.assertEqual(len(self.runs[0][3].args), 0)
        self.assertEqual(len(self.logs), 1)

    def test_spec_2_3_the_body_is_cancelled_before_its_first_line(self):
        sent = []

        async def send(message):
            sent.append(message["type"])
            await asyncio.sleep(0)
        self.call("2.3", send)
        self.assertNotIn("http.response.body", sent)
        self.check_closed()

    def test_spec_2_4_the_first_send_fails(self):
        async def send(message):
            raise OSError("client gone")
        self.call("2.4", send)
        self.check_closed()


class DeadlineOptionTests(unittest.TestCase):
    def test_the_local_server_takes_its_deadline_from_the_option_or_the_environment(self):
        self.assertEqual(arguments([], {}).deadline, DEADLINE_SECONDS)
        self.assertEqual(arguments([], {"COACH_DEADLINE_SECONDS": " 1700 "}).deadline, 1700.0)
        self.assertEqual(arguments(["--deadline", "900"], {"COACH_DEADLINE_SECONDS": "1700"}).deadline, 900.0)
        for argv, env in ((["--deadline", "0"], {}), (["--deadline", "soon"], {}),
                          ([], {"COACH_DEADLINE_SECONDS": "7200"})):
            with self.subTest(argv=argv, env=env), patch("sys.stderr"), self.assertRaises(SystemExit):
                arguments(argv, env)


if __name__ == "__main__":
    unittest.main()
