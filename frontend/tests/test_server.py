"""Check the user-facing HTTP boundary without calling a paid provider."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from frontend.server import make_app
from translation_agent_demo.agents import ExpressionItem


class CoachApiTests(unittest.TestCase):
    def setUp(self):
        # make_app reads the mode variables when it starts; a shell's settings must not reach it
        env = patch.dict(os.environ, {"COACH_PAIR_CODE": "", "COACH_WEB_ORIGIN": "", "COACH_SYSTEM": "",
                                      "COACH_CONTINUATION": ""})
        env.start()
        self.addCleanup(env.stop)
        self.answer = Mock(return_value=SimpleNamespace(
            status="ok", expressions=[ExpressionItem(expression="Thanks for the heads-up.",
                function="Thanks", note="Acknowledges a warning.")], source_availability_note=None))
        self.client = TestClient(make_app(self.answer), base_url="http://localhost")

    def test_question_and_context_reach_coach_without_leaking_its_trace(self):
        response = self.client.post("/api/search", json={"question": " 谢谢提醒 ", "context": "同事"})
        self.assertEqual(200, response.status_code)
        self.answer.assert_called_once_with("谢谢提醒\n同事")
        item, = response.json()["expressions"]
        self.assertEqual(set(item), {"expression", "note", "key_phrase", "citation"})
        self.assertIsNone(item["citation"])

    def test_invalid_and_untrusted_requests_do_not_call_model(self):
        self.assertEqual(422, self.client.post("/api/search", json={"question":" "}).status_code)
        for key, value in (("Origin", "https://other.invalid"), ("Host", "other.invalid")):
            self.assertEqual(403, self.client.post("/api/search", headers={key:value}, json={"question":"hello"}).status_code)
        self.answer.assert_not_called()

    def test_phone_pairing_and_failure_feedback(self):
        with patch.dict(os.environ, {"COACH_PAIR_CODE":"test-code"}):
            self.assertEqual(401, self.client.post("/api/search", json={"question":"帮帮我"}).status_code)
            self.answer.side_effect = RuntimeError("internal details")
            r = self.client.post("/api/search", headers={"X-Coach-Code":"test-code","Origin":"http://localhost"}, json={"question":"帮帮我"})
            self.assertEqual(503, r.status_code)
            self.assertNotIn("internal details", r.text)
            self.answer.side_effect=None
            self.assertEqual(200, self.client.post("/api/search", headers={"X-Coach-Code":"test-code"}, json={"question":"hello"}).status_code)

    def test_public_deployment_accepts_web_and_android_without_pairing(self):
        with patch.dict(os.environ, {"COACH_PAIR_CODE": "old-private-code"}):
            public = TestClient(make_app(self.answer, public_access=True), base_url="https://coach.example")
            for origin in ("https://coach.example", "http://localhost"):
                response = public.post("/api/search", headers={"Origin": origin}, json={"question": "hello"})
                self.assertEqual(response.status_code, 200)
            refused = public.post("/api/search", headers={"Origin": "https://other.invalid"}, json={"question": "hello"})
            self.assertEqual(refused.status_code, 403)
            self.assertEqual(self.answer.call_count, 2)
