import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
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
        self.assertNotIn(b'class="suggestions"', page)
        script = self.fetch("/static/app.js")[2]
        self.assertIn("showWelcome();".encode(), script)
        self.assertIn("question-choice-text".encode(), script)
        datasets = json.loads(self.fetch("/api/datasets")[2])
        self.assertEqual(datasets["datasets"][0]["students"], 50)
        names = json.loads(self.fetch("/api/students?data_file=data%2Ffictional_school.json")[2])["students"]
        self.assertEqual(names[5]["name"], "تالا أمجد")
        query = urllib.parse.urlencode({"data_file": "data/fictional_school.json",
                                        "start": "2026-09-07", "end": "2026-09-09"})
        report = json.loads(self.fetch("/api/analysis?" + query)[2])
        self.assertEqual(report["summary"]["attendance"]["by_date"][1]["present"], 43)
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
                return {"object": "list", "platform": "api_server", "data": [
                    {"name": "student_followup", "enabled": True,
                     "tools": ["student_followup_info", "student_followup_analyze"]}]}
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

    def test_model_action_marks_chat_changed_and_revision(self):
        context = {"data_file": "data/fictional_school.json",
                   "start": "2026-09-07", "end": "2026-09-11"}
        url = "/api/revision?data_file=data%2Ffictional_school.json"
        before = json.loads(self.fetch(url)[2])["revision"]

        def fake_hermes(path, body=None, timeout=3):
            if path == "/v1/toolsets":
                return {"data": [{"name": "student_followup", "enabled": True,
                                  "tools": ["student_followup_info", "student_followup_analyze"]}]}
            web.execute(context["data_file"], "record_attendance", "Teacher", "S-033",
                        day="2026-09-09", status="present", request_id="model-write-test")
            return {"id": "resp-action", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "تم تحديث حضور أحمد سائد."}]}]}

        with patch.dict(os.environ, {"API_SERVER_KEY": "local-test"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            status, _, payload = self.fetch("/api/chat", {**context,
                "message": "سجّل حضور أحمد سائد يوم 9 سبتمبر"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(payload)["changed"])
        after = json.loads(self.fetch(url)[2])["revision"]
        self.assertNotEqual(before, after)
        query = urllib.parse.urlencode(context)
        summary = json.loads(self.fetch("/api/analysis?" + query)[2])["summary"]
        self.assertFalse(any(row["student_id"] == "S-033" and row["date"] == "2026-09-09"
                             for row in summary["missing_attendance"]))

    def test_agent_prompts_with_clickable_question_and_advances_on_answer(self):
        calls = []

        def fake_hermes(path, body=None, timeout=3):
            calls.append((path, body))
            if path == "/v1/toolsets":
                return {"object": "list", "platform": "api_server", "data": [
                    {"name": "student_followup", "enabled": True,
                     "tools": ["student_followup_info", "student_followup_analyze"]}]}
            return {"id": f"resp-{len(calls)}", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "وجدت ثلاث حالات للمراجعة."}]}]}

        context = {"guided": True, "data_file": "data/fictional_school.json",
                   "start": "2026-09-07", "end": "2026-09-11"}
        with patch.dict(os.environ, {"API_SERVER_KEY": "test-local-secret"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            first = json.loads(self.fetch("/api/chat", {**context, "message": "ابدأ المراجعة"})[2])
            self.assertEqual(first["question"]["id"], "followup:F-001")
            self.assertIn("ليان عمر", first["question"]["text"])
            self.assertNotIn("S-002", first["question"]["text"])
            self.assertEqual(len(first["question"]["options"]), 4)
            self.assertEqual(calls, [])
            second = json.loads(self.fetch("/api/chat", {**context, "message": "سجّل أنها لم تتم بعد",
                "session_id": first["session_id"], "answer_to": "followup:F-001"})[2])
            self.assertEqual(second["question"]["id"], "followup:F-002")
            self.assertTrue(second["changed"])
            followup = json.loads(self.fetch("/api/chat", {**context, "message": "سجّل أنها لم تتم بعد",
                "session_id": first["session_id"], "answer_to": second["question"]["id"]})[2])
            self.assertEqual(followup["question"]["id"], "attendance:S-009:2026-09-07")
            third = json.loads(self.fetch("/api/chat", {**context, "message": "سجّل غائب",
                "session_id": first["session_id"], "answer_to": followup["question"]["id"]})[2])
            self.assertEqual(third["question"]["id"], "attendance:S-039:2026-09-07")
            self.assertTrue(third["changed"])
            attendance = storage.read_data(context["data_file"])["attendance"]
            self.assertEqual(next(row["status"] for row in attendance if row["student_id"] == "S-009"
                                  and row["date"] == "2026-09-07"), "absent")
            self.assertEqual(len(storage.events("actions.jsonl")), 3)
            question = json.loads(self.fetch("/api/chat", {**context, "message": "ليش S-006؟",
                "session_id": first["session_id"]})[2])
            self.assertIsNone(question["question"])
            self.assertIn("سجّل غائب", calls[-1][1]["input"])
            self.assertNotIn("Summarize relevant evidence", calls[-1][1]["input"])
            self.assertEqual(len(storage.events("dialogue.jsonl")), 3)

    def test_guided_followup_details_are_saved_only_after_explicit_record_choice(self):
        context = {"guided": True, "data_file": "data/fictional_school.json",
                   "start": "2026-09-07", "end": "2026-09-11"}
        first = json.loads(self.fetch("/api/chat", {**context, "message": "ابدأ المراجعة"})[2])
        answer = json.loads(self.fetch("/api/chat", {**context,
            "message": "تواصل المعلم وتم الاتفاق على موعد جديد", "session_id": first["session_id"],
            "answer_to": "followup:F-001", "save_answer": True})[2])
        self.assertTrue(answer["changed"])
        followup = storage.read_data(context["data_file"])["followups"][0]
        self.assertIn("تمّت المتابعة: تواصل المعلم", followup["outcome"])
        self.assertEqual(storage.events("actions.jsonl")[0]["action"], "resolve_followup")

    def test_contact_draft_requires_send_choice_and_persists_in_student_history(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-07", "end": "2026-09-11"}
        first = json.loads(self.fetch("/api/chat", {**context,
            "message": "ابعت رسالة لولي أمر S-006"})[2])
        self.assertEqual(first["question"]["id"], "send:S-006:guardian")
        self.assertIn("تالا أمجد", first["question"]["text"])
        self.assertEqual(storage.events("actions.jsonl"), [])
        changed = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
            "answer_to": first["question"]["id"], "message": "نرجو زيارة المدرسة غدًا.",
            "save_answer": True})[2])
        self.assertEqual(storage.events("actions.jsonl"), [])
        sent = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
            "answer_to": changed["question"]["id"], "message": "إرسال الرسالة"})[2])
        self.assertTrue(sent["changed"])
        self.assertEqual(sent["answer"], "تم الإرسال.")
        self.assertNotIn("سجل التواصل", sent["answer"])
        action = storage.events("actions.jsonl")[0]
        self.assertEqual(action["state"], "sent_demo")
        self.assertEqual(action["details"]["message"], "نرجو زيارة المدرسة غدًا.")
        self.assertEqual(action["details"]["recipient_type"], "guardian")
        self.assertEqual(web.case_context(context["data_file"], "S-006")[0]["details"]["message"],
                         "نرجو زيارة المدرسة غدًا.")
        self.assertEqual(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
            "answer_to": changed["question"]["id"], "message": "إرسال الرسالة"})[0], 400)
        self.assertEqual(len(storage.events("actions.jsonl")), 1)

    def test_case_question_offers_next_steps_without_guided_mode(self):
        def fake_hermes(path, body=None, timeout=3):
            if path == "/v1/toolsets":
                return {"data": [{"name": "student_followup", "enabled": True,
                                  "tools": ["student_followup_info", "student_followup_analyze"]}]}
            choice = ('[QUESTION]{"text":"هل نطلب سياق النتيجة من المعلم؟",'
                      '"options":["مراسلة المعلم","لا إجراء الآن"]}[/QUESTION]'
                      if "تالا" in body["input"] else "")
            return {"id": "resp-demo", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "راجعت الحالة. " + choice}]}]}

        context = {"data_file": "data/fictional_school.json", "start": "2026-09-07", "end": "2026-09-11"}
        with patch.dict(os.environ, {"API_SERVER_KEY": "local-test"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            first = json.loads(self.fetch("/api/chat", {**context, "message": "ما حالة تالا؟"})[2])
            period = json.loads(self.fetch("/api/chat", {**context, "message": "راجع الحالات في الفترة"})[2])
        self.assertEqual(self.fetch("/api/chat", {**context, "message": "ما حالة جنى؟"})[0], 400)
        self.assertTrue(first["question"]["id"].startswith("model:"))
        self.assertIsNone(period["question"])
        self.assertIn("مراسلة المعلم", first["question"]["options"])
        self.assertEqual(storage.events("actions.jsonl"), [])
        second = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
            "answer_to": first["question"]["id"], "message": "مراسلة المعلم"})[2])
        self.assertEqual(second["question"]["id"], "send:S-006:teacher")
        self.assertEqual(storage.events("actions.jsonl"), [])

    def test_recorded_guardian_followup_asks_model_for_new_decision(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-07", "end": "2026-09-11"}
        web._sessions["review-tim"] = {"context": (context["data_file"], context["start"], context["end"]),
            "response_id": "prior", "answered": [], "history": [],
            "pending": {"id": "followup:F-002", "student_id": "S-035",
                        "text": "هل تمت متابعة تيم حازم؟", "options": ["سجّل أنها تمّت واكتب النتيجة"]}}
        calls = []
        def fake_hermes(path, body=None, timeout=3):
            calls.append(body)
            return {"id": "new-response", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "بعد توثيق التواصل، اسأل المعلم عن وضعه الدراسي. "
                  '[QUESTION]{"text":"هل تريد سؤال المعلم عن مستواه؟",'
                  '"options":["مراسلة المعلم","لا إجراء الآن"]}[/QUESTION]'}]}]}
        with patch.dict(os.environ, {"API_SERVER_KEY": "local-test"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            saved = json.loads(self.fetch("/api/chat", {**context, "session_id": "review-tim",
                "answer_to": "followup:F-002", "message": "تم متابعة الحالة مع والده",
                "save_answer": True})[2])
            self.assertEqual(saved["question"]["options"], ["مراسلة المعلم", "لا إجراء الآن"])
            self.assertNotIn("مراسلة ولي الأمر", saved["question"]["options"])
            self.assertIn("تمّت المتابعة: تم متابعة الحالة مع والده", calls[0]["input"])
            self.assertEqual(calls[0]["previous_response_id"], "prior")
            chosen = json.loads(self.fetch("/api/chat", {**context, "session_id": "review-tim",
                "answer_to": saved["question"]["id"], "message": "مراسلة المعلم"})[2])
        self.assertEqual(chosen["question"]["id"], "send:S-035:teacher")
        self.assertEqual(storage.read_data(context["data_file"])["followups"][1]["outcome"],
                         "تمّت المتابعة: تم متابعة الحالة مع والده")
        self.assertEqual(len(storage.events("actions.jsonl")), 1)

    def test_model_can_select_pending_followup_or_no_next_step(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-07", "end": "2026-09-11"}
        def fake_hermes(path, body=None, timeout=3):
            if path == "/v1/toolsets":
                return {"data": [{"name": "student_followup", "enabled": True,
                                  "tools": ["student_followup_info", "student_followup_analyze"]}]}
            if "راجع" in body["input"]:
                answer = ('في متابعة معلقة لتيم. [QUESTION]{"text":"هل تمت متابعة تيم حازم؟",'
                    '"options":["سجّل أنها تمّت واكتب النتيجة","سجّل أنها لم تتم بعد","لا أعرف"],'
                    '"action":{"type":"resolve_followup","student_id":"S-035",'
                    '"followup_id":"F-002"}}[/QUESTION]')
            else:
                answer = "النتيجة محفوظة، ولا توجد خطوة أخرى مطلوبة الآن."
            return {"id": "resp", "output": [{"type": "message", "content": [{"type": "output_text", "text": answer}]}]}
        with patch.dict(os.environ, {"API_SERVER_KEY": "local-test"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            first = json.loads(self.fetch("/api/chat", {**context, "message": "راجع الحالات"})[2])
            self.assertEqual(first["question"]["id"], "followup:F-002")
            saved = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
                "answer_to": "followup:F-002", "message": "تمت مع والده", "save_answer": True})[2])
        self.assertIsNone(saved["question"])
        self.assertEqual(len(storage.events("actions.jsonl")), 1)

    def test_attendance_answer_requires_explicit_record_choice(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-07", "end": "2026-09-11"}
        calls = []
        def fake_hermes(path, body=None, timeout=3):
            if path == "/v1/toolsets":
                return {"data": [{"name": "student_followup", "enabled": True,
                                  "tools": ["student_followup_info", "student_followup_analyze"]}]}
            calls.append(body)
            return {"id": f"resp-{len(calls)}", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": 'حضور أحمد يوم 9 سبتمبر غير مسجل. '
                  '[QUESTION]{"text":"ما حالة حضور أحمد في 9 سبتمبر؟",'
                  '"options":["كان حاضرًا","كان غائبًا","لا أستطيع التحقق"]}[/QUESTION]'}]}]}
        def current_status():
            return next(row["status"] for row in storage.read_data(context["data_file"])["attendance"]
                        if row["student_id"] == "S-033" and row["date"] == "2026-09-09")

        with patch.dict(os.environ, {"API_SERVER_KEY": "local-test"}), \
             patch.object(web, "hermes_request", side_effect=fake_hermes):
            first = json.loads(self.fetch("/api/chat", {**context,
                "message": "ما حالة أحمد سائد وما الخطوة المناسبة؟"})[2])
            self.assertEqual(first["question"]["id"], "attendance:S-033:2026-09-09")
            answer = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
                "answer_to": first["question"]["id"], "message": "كان حاضرًا"})[2])
            self.assertEqual(answer["question"]["options"],
                             ["نعم، سجّلها", "لا، اترك السجل كما هو"])
            self.assertFalse(answer["changed"])
            self.assertEqual(current_status(), "unrecorded")
            self.assertEqual(storage.events("actions.jsonl"), [])
            declined = json.loads(self.fetch("/api/chat", {**context, "session_id": first["session_id"],
                "answer_to": answer["question"]["id"], "message": "لا، اترك السجل كما هو"})[2])
            self.assertFalse(declined["changed"])
            self.assertEqual(current_status(), "unrecorded")

            again = json.loads(self.fetch("/api/chat", {**context,
                "message": "ما حالة أحمد سائد؟"})[2])
            proposed = json.loads(self.fetch("/api/chat", {**context, "session_id": again["session_id"],
                "answer_to": again["question"]["id"], "message": "كان حاضرًا"})[2])
            confirmed = json.loads(self.fetch("/api/chat", {**context, "session_id": again["session_id"],
                "answer_to": proposed["question"]["id"], "message": "نعم، سجّلها"})[2])
            self.assertTrue(confirmed["changed"])
            self.assertIn("سجّلت أحمد سائد حاضرًا", confirmed["answer"])
            self.assertEqual(current_status(), "present")
            self.assertEqual(len(storage.events("actions.jsonl")), 1)
            self.assertEqual(self.fetch("/api/chat", {**context, "session_id": again["session_id"],
                "answer_to": proposed["question"]["id"], "message": "نعم، سجّلها"})[0], 400)
            self.assertEqual(len(calls), 2)

    def test_report_feedback_and_local_action_http_flow(self):
        context = {"data_file": "data/fictional_school.json", "start": "2026-09-10", "end": "2026-09-10"}
        status, _, payload = self.fetch("/api/report", {**context, "purpose": "تقرير الغياب اليومي"})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(payload)["report"]["missing_attendance"]), 3)
        feedback = {**context, "start": "2026-09-07", "end": "2026-09-11",
                    "student_id": "S-006", "label": "confirmed", "note": "Teacher confirmed score drop"}
        self.assertEqual(self.fetch("/api/feedback", feedback)[0], 200)
        self.assertEqual(len(storage.events("feedback.jsonl")), 1)
        action = {"data_file": context["data_file"], "action": "record_attendance", "actor": "Teacher",
                  "student_id": "S-004", "day": "2026-09-10", "status": "present"}
        self.assertEqual(self.fetch("/api/actions", action)[0], 200)
        remaining = json.loads(self.fetch("/api/report", {**context, "purpose": "تقرير الغياب اليومي"})[2])
        self.assertEqual({row["student_id"] for row in remaining["report"]["missing_attendance"]},
                         {"S-022", "S-047"})

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
            self.assertEqual(command, ["hermes.exe", "gateway", "run"])
            self.assertEqual(cwd, web.ROOT)
            child.environment = env
            return child

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(launcher, "hermes_executable", return_value="hermes.exe"), \
             patch.object(launcher, "hermes_api_key", return_value="stored-local-test-key-12345"), \
             patch.object(launcher, "port_open", return_value=False), \
             patch.object(launcher.subprocess, "Popen", side_effect=spawn), \
             patch.object(launcher, "serve", side_effect=KeyboardInterrupt):
            launcher.main([])
            self.assertTrue(child.stopped)
            self.assertEqual(child.environment["HERMES_ENABLE_PROJECT_PLUGINS"], "true")
            self.assertEqual(child.environment["API_SERVER_ENABLED"], "true")
            self.assertEqual(os.environ["API_SERVER_KEY"], child.environment["API_SERVER_KEY"])
            self.assertEqual(child.environment["API_SERVER_KEY"], "stored-local-test-key-12345")

    def test_launcher_saves_key_in_hermes_profile_without_printing_it(self):
        calls = []

        def run(command, **options):
            calls.append(command)
            self.assertTrue(options["capture_output"])
            self.assertNotIn("API_SERVER_KEY", options["env"])
            if command[1:4] == ["config", "get", "API_SERVER_KEY"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="Config key not set")
            if command[1:4] == ["config", "get", "API_SERVER_ENABLED"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="Config key not set")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.dict(os.environ, {"API_SERVER_KEY": "stale-process-key"}), \
             patch.object(launcher.subprocess, "run", side_effect=run):
            key = launcher.hermes_api_key("hermes.exe")
        self.assertGreaterEqual(len(key), 32)
        self.assertIn(["hermes.exe", "config", "set", "API_SERVER_KEY", key], calls)
        self.assertIn(["hermes.exe", "config", "set", "API_SERVER_ENABLED", "true"], calls)

    def test_gateway_exit_and_occupied_port_have_specific_status(self):
        class Stopped:
            returncode = 2

            def poll(self):
                return 2

        with patch.object(web, "gateway_process", Stopped()), patch.object(web, "gateway_problem", None):
            status = web.hermes_status()
            self.assertFalse(status["ready"])
            self.assertIn("gateway run برمز 2", status["message"])
        with patch.object(web, "gateway_process", None), \
             patch.object(web, "gateway_problem", "المنفذ 8642 مستخدم بالفعل"):
            self.assertIn("8642", web.hermes_status()["message"])


if __name__ == "__main__":
    unittest.main()
