import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from web_app import server as web
from web_app import __main__ as launcher
from student_followup import storage, learning


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_reviews = web.REVIEWS
        web.REVIEWS = Path(self.temp.name) / "reviews.jsonl"
        web._sessions.clear()
        self.storage_patch = patch.object(storage, "OUTPUT", Path(self.temp.name))
        self.learning_patch = patch.object(learning, "OUTPUT", Path(self.temp.name))
        self.storage_patch.start()
        self.learning_patch.start()

    def tearDown(self):
        web.REVIEWS = self.old_reviews
        self.learning_patch.stop()
        self.storage_patch.stop()
        self.temp.cleanup()

    def fetch(self, path, body=None, origin=None):
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_dashboard_and_deterministic_api(self):
        status, headers, page = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("مرصد الطلاب".encode(), page)
        self.assertEqual(headers["Content-Security-Policy"].split(";")[0], "default-src 'self'")
        self.assertEqual(self.fetch("/static/app.js")[0], 200)
        datasets = json.loads(self.fetch("/api/datasets")[2])
        self.assertEqual(datasets["datasets"][0]["students"], 30)
        query = urllib.parse.urlencode({"data_file": "data/fictional_school.json",
                                        "start": "2026-09-07", "end": "2026-09-09"})
        report = json.loads(self.fetch("/api/analysis?" + query)[2])
        self.assertEqual(report["summary"]["attendance"]["by_date"][1]["present"], 28)
        self.assertEqual(self.fetch("/api/analysis?data_file=../other.json&start=2026-09-07&end=2026-09-09")[0], 400)

    def test_reviewer_decision_is_saved_only_for_case(self):
        review = {"data_file": "data/fictional_school.json", "start": "2026-09-07",
                  "end": "2026-09-11", "student_id": "S-002", "decision": "verify_data",
                  "note": "Ask about F-001"}
        status, _, payload = self.fetch("/api/reviews", review)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(payload)["review"]["executed"])
        self.assertEqual(len(web.REVIEWS.read_text(encoding="utf-8").splitlines()), 1)
        query = urllib.parse.urlencode({"data_file": review["data_file"], "start": review["start"], "end": review["end"]})
        result = json.loads(self.fetch("/api/analysis?" + query)[2])
        case = next(case for case in result["candidates"] if case["student_id"] == "S-002")
        self.assertEqual(case["review"]["decision"], "verify_data")
        self.assertEqual(self.fetch("/api/reviews", dict(review, student_id="S-001"))[0], 400)
        self.assertEqual(self.fetch("/api/reviews", review, origin="https://example.com")[0], 403)

    def test_chat_proxies_to_hermes_without_exposing_key_and_keeps_context(self):
        calls = []

        def fake_hermes(path, body=None, timeout=3):
            calls.append((path, body))
            if path == "/v1/toolsets":
                return [{"name": "student_followup", "enabled": True,
                         "tools": ["student_followup_info", "student_followup_analyze"]}]
            return {"id": f"resp-{len(calls)}", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "30 طالبًا"}]}]}

        with patch.dict(os.environ, {"API_SERVER_KEY": "test-local-secret"}), patch.object(web, "hermes_request", side_effect=fake_hermes):
            status, _, payload = self.fetch("/api/chat", {"message": "كم طالب في الملف؟"})
            self.assertEqual(status, 200)
            first = json.loads(payload)
            self.assertEqual(first["answer"], "30 طالبًا")
            self.assertNotIn("test-local-secret", payload.decode())
            status, _, payload = self.fetch("/api/chat", {"message": "وماذا عن الحضور؟", "session_id": first["session_id"]})
            self.assertEqual(status, 200)
            self.assertEqual(calls[-1][1]["previous_response_id"], "resp-2")
            self.assertIn("student_followup_analyze", calls[-1][1]["instructions"])
        with patch.dict(os.environ, {"API_SERVER_KEY": ""}):
            self.assertEqual(self.fetch("/api/chat", {"message": "كم طالب؟"})[0], 503)

    def test_agent_prompts_with_clickable_question_and_advances_on_answer(self):
        calls = []

        def fake_hermes(path, body=None, timeout=3):
            calls.append(path)
            if path == "/v1/toolsets":
                return [{"name": "student_followup", "tools": ["student_followup_info", "student_followup_analyze"]}]
            return {"id": f"resp-{len(calls)}", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "وجدت ثلاث حالات للمراجعة."}]}]}

        context = {"guided": True, "data_file": "data/fictional_school.json",
                   "start": "2026-09-07", "end": "2026-09-11"}
        with patch.dict(os.environ, {"API_SERVER_KEY": "test-local-secret"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            first = json.loads(self.fetch("/api/chat", {**context, "message": "ابدأ المراجعة"})[2])
            self.assertEqual(first["question"]["id"], "followup:F-001")
            self.assertEqual(len(first["question"]["options"]), 4)
            second = json.loads(self.fetch("/api/chat", {**context, "message": "لم تتم بعد",
                "session_id": first["session_id"], "answer_to": "followup:F-001"})[2])
            self.assertTrue(second["question"]["id"].startswith("attendance:"))
            self.assertEqual(len(storage.events("dialogue.jsonl")), 1)

    def test_report_feedback_and_local_action_http_flow(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-10", "end": "2026-09-10"}
        status, _, payload = self.fetch("/api/report", {**context, "purpose": "تقرير الغياب اليومي"})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(payload)["report"]["missing_attendance"]), 1)
        feedback = {**context, "start": "2026-09-07", "end": "2026-09-11",
                    "student_id": "S-006", "label": "confirmed", "note": "Teacher confirmed score drop"}
        self.assertEqual(self.fetch("/api/feedback", feedback)[0], 200)
        self.assertEqual(len(storage.events("feedback.jsonl")), 1)
        action = {"data_file": context["data_file"], "action": "record_attendance", "actor": "Teacher",
                  "student_id": "S-004", "day": "2026-09-10", "status": "present"}
        self.assertEqual(self.fetch("/api/actions", action)[0], 200)
        self.assertEqual(json.loads(self.fetch("/api/report", {**context, "purpose": "تقرير الغياب اليومي"})[2])
                         ["report"]["missing_attendance"], [])

    def test_launcher_starts_and_stops_local_gateway(self):
        class Child:
            def __init__(self):
                self.environment = None
                self.stopped = False

            def poll(self):
                return None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout):
                return 0

        child = Child()

        def spawn(command, cwd, env):
            self.assertEqual(command, ["hermes.exe", "gateway"])
            self.assertEqual(cwd, web.ROOT)
            child.environment = env
            return child

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(launcher, "hermes_executable", return_value="hermes.exe"), \
             patch.object(launcher, "port_open", return_value=False), \
             patch.object(launcher.subprocess, "Popen", side_effect=spawn), \
             patch.object(launcher, "serve", side_effect=KeyboardInterrupt):
            launcher.main([])
            self.assertTrue(child.stopped)
            self.assertEqual(child.environment["HERMES_ENABLE_PROJECT_PLUGINS"], "true")
            self.assertEqual(child.environment["API_SERVER_ENABLED"], "true")
            self.assertEqual(os.environ["API_SERVER_KEY"], child.environment["API_SERVER_KEY"])


if __name__ == "__main__":
    unittest.main()
