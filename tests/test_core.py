import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.generate_demo import build
from student_followup import DataError, analyze
from student_followup import learning, storage
from student_followup.actions import execute
from student_followup import actions
from student_followup.reports import create_report
from student_followup.context import case_context
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class AnalysisTests(unittest.TestCase):
    def test_demo_evidence_and_uncertainty(self):
        result = analyze(build(), "2026-09-07", "2026-09-11")
        self.assertEqual(result["summary"]["students"], 50)
        self.assertEqual(result["summary"]["attendance_records_in_period"], 250)
        self.assertEqual(result["summary"]["candidates"], 7)
        self.assertEqual(result["summary"]["unresolved"], 10)
        self.assertEqual(result["summary"]["data_quality_issues"], 11)
        self.assertEqual({entry["student_id"] for entry in result["summary"]["data_quality_details"]},
                         {"S-004", "S-006", "S-009", "S-014", "S-018", "S-022",
                          "S-027", "S-033", "S-039", "S-044", "S-047"})
        candidates = {c["student_id"]: c for c in result["candidates"]}
        self.assertEqual(set(candidates), {"S-002", "S-003", "S-006", "S-031", "S-032", "S-034", "S-035"})
        self.assertEqual([c["student_id"] for c in result["candidates"]],
                         ["S-006", "S-034", "S-002", "S-003", "S-031", "S-032", "S-035"])
        self.assertEqual(candidates["S-006"]["alias"], "تالا أمجد")
        self.assertEqual(candidates["S-006"]["priority"], "high")
        self.assertEqual(candidates["S-002"]["priority"], "standard")
        self.assertEqual(candidates["S-003"]["priority"], "standard")
        self.assertEqual(candidates["S-002"]["observations"][0]["dates"], ["2026-09-08", "2026-09-10"])
        self.assertEqual(len(candidates["S-002"]["previous_followups"]), 1)
        self.assertEqual(candidates["S-003"]["observations"][0]["current"]["percent"], 62)
        self.assertEqual(result["unresolved"][0]["student_id"], "S-004")
        self.assertEqual(result["unresolved"][0]["attendance"]["absent"], 0)
        self.assertEqual(candidates["S-006"]["attendance"]["unrecorded"], 1)
        self.assertIsNone(result["summary"]["tokens_used"])

    def test_old_local_overlay_keeps_edits_when_demo_roster_expands(self):
        old = build()
        old["students"] = old["students"][:30]
        for section in ("attendance", "assessments", "followups"):
            old[section] = [row for row in old[section] if int(row["student_id"][2:]) <= 30]
        row = next(row for row in old["attendance"] if row["student_id"] == "S-004"
                   and row["date"] == "2026-09-10")
        row["status"] = "absent"
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, "OUTPUT", Path(temp)):
            overlay = Path(temp) / "datasets" / "fictional_school.json"
            overlay.parent.mkdir(parents=True)
            overlay.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
            migrated = storage.read_data("data/fictional_school.json")
            self.assertEqual(len(migrated["students"]), 50)
            self.assertEqual(next(row["status"] for row in migrated["attendance"]
                                  if row["student_id"] == "S-004" and row["date"] == "2026-09-10"), "absent")
            self.assertIn("S-050", {row["student_id"] for row in migrated["students"]})
            self.assertEqual(len(json.loads(storage.read_bytes("data/fictional_school.json"))["students"]), 50)

    def test_missing_attendance_row_is_a_gap_not_an_absence(self):
        data = build()
        data["attendance"] = [row for row in data["attendance"]
                              if not (row["student_id"] == "S-001" and row["date"] == "2026-09-09")]
        result = analyze(data, "2026-09-07", "2026-09-11")
        self.assertEqual(result["summary"]["candidates"], 7)
        unresolved = {case["student_id"]: case for case in result["unresolved"]}
        self.assertEqual(unresolved["S-001"]["attendance"]["absent"], 0)
        self.assertEqual(unresolved["S-001"]["attendance"]["missing_record_dates"], ["2026-09-09"])
        self.assertEqual(result["summary"]["data_quality_issues"], 12)
        self.assertEqual(result["summary"]["attendance"]["by_date"][2]["missing_record"], 1)
        self.assertIn("S-001", {entry["student_id"] for entry in result["summary"]["data_quality_details"]})

    def test_explicit_calendar_catches_day_with_no_attendance_rows_and_arbitrary_period(self):
        data = build()
        data["attendance"] = [row for row in data["attendance"] if row["date"] != "2026-09-09"]
        result = analyze(data, "2026-09-09", "2026-09-09")
        self.assertEqual(result["summary"]["attendance"]["by_date"][0]["missing_record"], 50)
        self.assertEqual(len(result["summary"]["missing_attendance"]), 50)
        self.assertEqual(result["summary"]["candidates"], 0)
        self.assertEqual(result["summary"]["unresolved"], 50)
        item = create_report(data, "2026-09-09", "2026-09-09", "التحقق من اكتمال حضور اليوم")
        self.assertEqual(item["purpose"], "التحقق من اكتمال حضور اليوم")
        self.assertEqual(len(item["missing_attendance"]), 50)
        future = analyze(data, "2026-12-01", "2026-12-31")
        self.assertEqual(future["summary"]["attendance"]["by_date"], [])
        self.assertEqual(future["summary"]["unresolved"], 0)

    def test_present_students_are_not_attendance_record_counts(self):
        result = analyze(build(), "2026-09-07", "2026-09-09")
        self.assertEqual(result["summary"]["attendance_records_in_period"], 150)
        attendance = result["summary"]["attendance"]
        self.assertEqual([(day["present"], day["absent"], day["unrecorded"])
                          for day in attendance["by_date"]],
                         [(48, 0, 2), (43, 5, 2), (48, 0, 2)])
        self.assertEqual(attendance["present_student_days"], 139)
        self.assertEqual(attendance["students_present_at_least_once"], 50)
        self.assertEqual(attendance["students_present_every_recorded_school_day"], 39)

    def test_duplicate_and_conflicting_attendance_stops_analysis(self):
        data = build()
        extra = dict(data["attendance"][0], status="absent")
        data["attendance"].append(extra)
        with self.assertRaisesRegex(DataError, "duplicate or conflicting"):
            analyze(data, "2026-09-07", "2026-09-11")

    def test_missing_and_invalid_data_stop_analysis(self):
        data = build()
        data["attendance"][0]["status"] = "unknown"
        with self.assertRaises(DataError):
            analyze(data, "2026-09-07", "2026-09-11")
        data = build()
        data["assessments"][0]["max_score"] = 0
        with self.assertRaises(DataError):
            analyze(data, "2026-09-07", "2026-09-11")
        data = build()
        data["attendance"][0]["student_id"] = "S-999"
        with self.assertRaises(DataError):
            analyze(data, "2026-09-07", "2026-09-11")

    def test_period_filter_and_score_normalization(self):
        data = {"students": [{"student_id": "S-A", "alias": "A"}],
                "attendance": [{"student_id": "S-A", "date": "2026-09-01", "status": "absent"},
                               {"student_id": "S-A", "date": "2026-10-01", "status": "present"}],
                "assessments": [{"student_id": "S-A", "subject": "Math", "date": "2026-08-01", "score": 8, "max_score": 10},
                                {"student_id": "S-A", "subject": "Math", "date": "2026-10-01", "score": 6, "max_score": 10}],
                "followups": []}
        result = analyze(data, "2026-10-01", "2026-10-01")
        self.assertEqual(result["summary"]["candidates"], 1)
        self.assertEqual(result["candidates"][0]["attendance"]["absent"], 0)
        self.assertEqual(result["candidates"][0]["observations"][0]["type"], "lower_comparable_score")

    def test_demo_threshold_boundaries_and_missing_attendance(self):
        data = build()
        for row in data["attendance"]:
            if row["student_id"] == "S-002" and row["date"] == "2026-09-10":
                row["status"] = "unrecorded"
        for row in data["assessments"]:
            if row["student_id"] == "S-003" and row["date"] == "2026-09-11":
                row["score"] = 66  # a 14-point drop is still descriptive only
        result = analyze(data, "2026-09-07", "2026-09-11")
        self.assertEqual([c["student_id"] for c in result["candidates"]],
                         ["S-006", "S-034", "S-031", "S-032", "S-035"])
        unresolved = {c["student_id"]: c for c in result["unresolved"]}
        self.assertEqual(unresolved["S-002"]["attendance"]["absent"], 1)
        self.assertEqual(unresolved["S-002"]["attendance"]["unrecorded"], 1)
        self.assertNotIn("S-003", unresolved)
        for row in data["assessments"]:
            if row["student_id"] == "S-003" and row["date"] == "2026-09-11":
                row["score"] = 65  # exactly 15 percentage points
        result = analyze(data, "2026-09-07", "2026-09-11")
        self.assertEqual({c["student_id"] for c in result["candidates"]},
                         {"S-003", "S-006", "S-031", "S-032", "S-034", "S-035"})

    def test_absence_requires_two_in_one_full_five_date_window(self):
        data = {"students": [{"student_id": "S-A", "alias": "A"}],
                "attendance": [{"student_id": "S-A", "date": f"2026-09-{day:02}",
                                "status": "absent" if day in (1, 6) else "present"}
                               for day in range(1, 7)],
                "assessments": [], "followups": []}
        result = analyze(data, "2026-09-01", "2026-09-06")
        self.assertEqual(result["summary"]["candidates"], 0)
        data["attendance"][4]["status"] = "absent"
        result = analyze(data, "2026-09-01", "2026-09-06")
        self.assertEqual(result["candidates"][0]["alerts"][0]["count"], 2)
        self.assertEqual(result["candidates"][0]["alerts"][0]["window_dates"],
                         [f"2026-09-{day:02}" for day in range(2, 7)])

    def test_plugin_exposes_read_only_tool_and_confines_input(self):
        spec = importlib.util.spec_from_file_location("demo_plugin", ROOT / ".hermes/plugins/student-followup/__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)

        class Context:
            def register_tool(self, **kwargs):
                self.registrations[kwargs["name"]] = kwargs

            def __init__(self):
                self.registrations = {}

        ctx = Context()
        plugin.register(ctx)
        self.assertEqual(set(ctx.registrations), {"student_followup_info", "student_followup_analyze",
                                                  "student_followup_report", "student_followup_action",
                                                  "student_followup_feedback", "student_followup_context"})
        info = json.loads(ctx.registrations["student_followup_info"]["handler"]({}))
        self.assertTrue(info["success"])
        self.assertEqual(info["datasets"], [{
            "data_file": "data/fictional_school.json", "students": 50,
            "attendance_records": 250, "assessment_records": 100,
            "followup_records": 2,
            "attendance_period": {"start": "2026-09-07", "end": "2026-09-11"},
        }])
        tool = ctx.registrations["student_followup_analyze"]["handler"]
        result = json.loads(tool({"data_file": "data/fictional_school.json", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["summary"]["candidates"], 7)
        rejected = json.loads(tool({"data_file": "../README.md", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertFalse(rejected["success"])
        daily = json.loads(ctx.registrations["student_followup_report"]["handler"]({
            "data_file": "data/fictional_school.json", "period_start": "2026-09-10",
            "period_end": "2026-09-10", "purpose": "فحص حضور اليوم"}))
        self.assertEqual(daily["report"]["missing_attendance"][0]["student_id"], "S-004")
        self.assertNotIn("actor", ctx.registrations["student_followup_action"]["schema"]["parameters"]["required"])
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, "OUTPUT", Path(temp)):
            performed = json.loads(ctx.registrations["student_followup_action"]["handler"]({
                "data_file": "data/fictional_school.json", "action": "record_attendance",
                "student_id": "S-004", "day": "2026-09-10", "status": "present"}))
            self.assertTrue(performed["success"])
            self.assertEqual(performed["action"]["state"], "completed")
            self.assertIn("غير موثقة", performed["action"]["actor"])

    def test_local_actions_edit_overlay_and_audit_without_touching_fixture(self):
        original = (ROOT / "data/fictional_school.json").read_bytes()
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, "OUTPUT", Path(temp)):
            name = "data/fictional_school.json"
            row = execute(name, "record_attendance", "Demo teacher", "S-004",
                          day="2026-09-10", status="present", request_id="req-1")
            self.assertEqual(row["details"]["before"], "unrecorded")
            self.assertEqual(row["state"], "completed")
            self.assertEqual(execute(name, "record_attendance", "Demo teacher", "S-004",
                                     day="2026-09-10", status="present", request_id="req-1"), row)
            with self.assertRaisesRegex(DataError, "different action"):
                execute(name, "record_attendance", "Demo teacher", "S-004",
                        day="2026-09-10", status="absent", request_id="req-1")
            self.assertEqual(analyze(storage.read_data(name), "2026-09-07", "2026-09-11")
                             ["summary"]["missing_attendance"][0]["student_id"], "S-009")
            changed = execute(name, "resolve_followup", "Demo teacher", "S-002",
                              followup_id="F-001", outcome="Teacher met student", request_id="req-2")
            self.assertEqual(changed["details"]["before"], "Teacher requested a check-in; response pending")
            queued = execute(name, "queue_contact", "Demo teacher", "S-002",
                             recipient_type="guardian", subject="Check-in", message="Please call school")
            self.assertEqual(queued["state"], "queued_local")
            memory = case_context(name, "S-002")
            self.assertEqual(len(memory), 2)
            self.assertNotIn("Please call school", json.dumps(memory))
            with self.assertRaisesRegex(DataError, "no verified email"):
                execute(name, "send_email", "Demo teacher", "S-002", recipient_type="guardian",
                        subject="Check-in", message="Please call school")
            self.assertEqual((ROOT / "data/fictional_school.json").read_bytes(), original)

    def test_feedback_can_autonomously_promote_versioned_rule_after_sufficient_labels(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, "OUTPUT", Path(temp)), \
             patch.object(learning, "OUTPUT", Path(temp)):
            for i in range(4):
                storage.append_event("feedback.jsonl", {"data_file": "data/fictional_school.json",
                    "student_id": f"S-P{i}", "period": {"start": "2026-01-01", "end": "2026-01-05"},
                    "label": "confirmed", "features": {"absences_in_five": 1, "score_drop": 0}})
            self.assertIsNone(learning._maybe_tune())
            for i in range(4):
                storage.append_event("feedback.jsonl", {"data_file": "data/fictional_school.json",
                    "student_id": f"S-N{i}", "period": {"start": "2026-01-01", "end": "2026-01-05"},
                    "label": "false_alert", "features": {"absences_in_five": 0, "score_drop": 0}})
            changed = learning._maybe_tune()
            self.assertEqual(changed["version"], 2)
            self.assertEqual(changed["absence_threshold"], 1)
            self.assertEqual(learning.policy(), changed)
            self.assertEqual(len(storage.events("policy_history.jsonl")), 1)
            sample = {"students": [{"student_id": "S-A", "alias": "A"}],
                      "school_days": [f"2026-01-0{i}" for i in range(1, 6)],
                      "attendance": [{"student_id": "S-A", "date": f"2026-01-0{i}",
                                      "status": "absent" if i == 1 else "present"} for i in range(1, 6)],
                      "assessments": [], "followups": []}
            self.assertEqual(analyze(sample, "2026-01-01", "2026-01-05")["summary"]["candidates"], 0)
            self.assertEqual(analyze(sample, "2026-01-01", "2026-01-05", learning.policy())
                             ["summary"]["candidates"], 1)

    def test_email_adapter_requires_dataset_recipient_and_reports_smtp_acceptance(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(storage, "OUTPUT", Path(temp)):
            data = build()
            data["students"][0]["guardian_email"] = "guardian@example.org"
            storage.save_data("data/fictional_school.json", data)
            environment = {"STUDENT_FOLLOWUP_SMTP_HOST": "smtp.example.org",
                           "STUDENT_FOLLOWUP_SMTP_USER": "demo", "STUDENT_FOLLOWUP_SMTP_PASSWORD": "secret",
                           "STUDENT_FOLLOWUP_SMTP_FROM": "school@example.org"}
            with patch.dict("os.environ", environment), patch.object(actions.smtplib, "SMTP_SSL") as smtp:
                row = execute("data/fictional_school.json", "send_email", "Demo teacher", "S-001",
                              recipient_type="guardian", subject="School check-in",
                              message="Please contact the school", request_id="email-1")
                self.assertEqual(row["state"], "sent")
                letter = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertEqual(letter["To"], "guardian@example.org")
                self.assertEqual(execute("data/fictional_school.json", "send_email", "Demo teacher", "S-001",
                                         recipient_type="guardian", subject="School check-in",
                                         message="Please contact the school", request_id="email-1"), row)
                self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 1)

    def test_plugin_imports_project_package_from_isolated_launcher(self):
        plugin_path = ROOT / ".hermes/plugins/student-followup/__init__.py"
        code = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('demo_plugin', sys.argv[1])
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
class Context:
    def register_tool(self, **kwargs):
        self.handlers[kwargs['name']] = kwargs['handler']
    def __init__(self):
        self.handlers = {}
ctx = Context()
plugin.register(ctx)
print(json.dumps({'info': json.loads(ctx.handlers['student_followup_info']({})),
                  'analysis': json.loads(ctx.handlers['student_followup_analyze']({
                      'data_file': 'data/fictional_school.json',
                      'period_start': '2026-09-07', 'period_end': '2026-09-11'}))}))
"""
        with tempfile.TemporaryDirectory() as temp:
            run = subprocess.run([sys.executable, "-I", "-c", code, str(plugin_path)],
                                 cwd=temp, text=True, capture_output=True, check=True)
        response = json.loads(run.stdout)
        self.assertEqual(response["info"]["datasets"][0]["students"], 50)
        self.assertEqual(response["analysis"]["result"]["summary"]["candidates"], 7)

    def test_cli_shows_every_case_and_preserves_json_option(self):
        args = [sys.executable, "-m", "student_followup", "--data", "data/fictional_school.json",
                "--start", "2026-09-07", "--end", "2026-09-11"]
        report = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertIn("حالات للمراجعة: 7 | حالات تحتاج استكمال بيانات: 10", report)
        for sid in ("S-002", "S-003", "S-006", "S-004"):
            self.assertIn(sid, report)
        self.assertIn("حضور غير مسجل (ليس غيابًا)", report)
        machine = subprocess.run(args + ["--json"], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(machine.stdout)["summary"]["candidates"], 7)

    def test_reviewer_decision_is_visible_only_for_matching_data_and_period(self):
        data = ROOT / "data/fictional_school.json"
        original = data.read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            reviews = Path(temp) / "reviews.jsonl"
            record = [sys.executable, "-m", "student_followup.reviews", "--data", str(data),
                      "--start", "2026-09-07", "--end", "2026-09-11", "--student-id", "S-004",
                      "--decision", "verify_data", "--note", "Check attendance register",
                      "--output", str(reviews)]
            subprocess.run(record, cwd=ROOT, text=True, capture_output=True, check=True)
            command = [sys.executable, "-m", "student_followup", "--data", str(data),
                       "--start", "2026-09-07", "--end", "2026-09-11",
                       "--reviews", str(reviews), "--json"]
            report = json.loads(subprocess.run(command, cwd=ROOT, text=True,
                                               capture_output=True, check=True).stdout)
            self.assertEqual(report["unresolved"][0]["review"]["decision"], "verify_data")
            self.assertEqual(report["unresolved"][0]["attendance"]["absent"], 0)
            self.assertFalse(json.loads(reviews.read_text(encoding="utf-8"))["executed"])
            other_period = json.loads(subprocess.run(command[:6] + ["2026-09-10"] + command[7:],
                                                     cwd=ROOT, text=True, capture_output=True, check=True).stdout)
            self.assertFalse(any("review" in case for case in other_period["candidates"] + other_period["unresolved"]))
            invalid = subprocess.run(record[:record.index("S-004")] + ["S-030"] +
                                     record[record.index("S-004") + 1:], cwd=ROOT,
                                     text=True, capture_output=True)
            self.assertEqual(invalid.returncode, 2)
        self.assertEqual(data.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
