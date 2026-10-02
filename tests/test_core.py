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


ROOT = Path(__file__).resolve().parents[1]


class AnalysisTests(unittest.TestCase):
    def test_demo_evidence_and_uncertainty(self):
        result = analyze(build(), "2026-09-07", "2026-09-11")
        self.assertEqual(result["summary"]["students"], 30)
        self.assertEqual(result["summary"]["attendance_records_in_period"], 150)
        self.assertEqual(result["summary"]["candidates"], 3)
        self.assertEqual(result["summary"]["unresolved"], 1)
        self.assertEqual(result["summary"]["data_quality_issues"], 2)
        self.assertEqual({entry["student_id"] for entry in result["summary"]["data_quality_details"]},
                         {"S-004", "S-006"})
        candidates = {c["student_id"]: c for c in result["candidates"]}
        self.assertEqual(set(candidates), {"S-002", "S-003", "S-006"})
        self.assertEqual([c["student_id"] for c in result["candidates"]], ["S-006", "S-002", "S-003"])
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

    def test_missing_attendance_row_is_a_gap_not_an_absence(self):
        data = build()
        data["attendance"] = [row for row in data["attendance"]
                              if not (row["student_id"] == "S-001" and row["date"] == "2026-09-09")]
        result = analyze(data, "2026-09-07", "2026-09-11")
        self.assertEqual(result["summary"]["candidates"], 3)
        unresolved = {case["student_id"]: case for case in result["unresolved"]}
        self.assertEqual(unresolved["S-001"]["attendance"]["absent"], 0)
        self.assertEqual(unresolved["S-001"]["attendance"]["missing_record_dates"], ["2026-09-09"])
        self.assertEqual(result["summary"]["data_quality_issues"], 3)
        self.assertEqual(result["summary"]["attendance"]["by_date"][2]["missing_record"], 1)
        self.assertIn("S-001", {entry["student_id"] for entry in result["summary"]["data_quality_details"]})

    def test_present_students_are_not_attendance_record_counts(self):
        result = analyze(build(), "2026-09-07", "2026-09-09")
        self.assertEqual(result["summary"]["attendance_records_in_period"], 90)
        attendance = result["summary"]["attendance"]
        self.assertEqual([(day["present"], day["absent"], day["unrecorded"])
                          for day in attendance["by_date"]],
                         [(30, 0, 0), (28, 2, 0), (30, 0, 0)])
        self.assertEqual(attendance["present_student_days"], 88)
        self.assertEqual(attendance["students_present_at_least_once"], 30)
        self.assertEqual(attendance["students_present_every_recorded_school_day"], 28)

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
        self.assertEqual([c["student_id"] for c in result["candidates"]], ["S-006"])
        unresolved = {c["student_id"]: c for c in result["unresolved"]}
        self.assertEqual(unresolved["S-002"]["attendance"]["absent"], 1)
        self.assertEqual(unresolved["S-002"]["attendance"]["unrecorded"], 1)
        self.assertNotIn("S-003", unresolved)
        for row in data["assessments"]:
            if row["student_id"] == "S-003" and row["date"] == "2026-09-11":
                row["score"] = 65  # exactly 15 percentage points
        result = analyze(data, "2026-09-07", "2026-09-11")
        self.assertEqual({c["student_id"] for c in result["candidates"]}, {"S-003", "S-006"})

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
        self.assertEqual(set(ctx.registrations), {"student_followup_info", "student_followup_analyze"})
        info = json.loads(ctx.registrations["student_followup_info"]["handler"]({}))
        self.assertTrue(info["success"])
        self.assertEqual(info["datasets"], [{
            "data_file": "data/fictional_school.json", "students": 30,
            "attendance_records": 150, "assessment_records": 60,
            "followup_records": 1,
            "attendance_period": {"start": "2026-09-07", "end": "2026-09-11"},
        }])
        tool = ctx.registrations["student_followup_analyze"]["handler"]
        result = json.loads(tool({"data_file": "data/fictional_school.json", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["summary"]["candidates"], 3)
        rejected = json.loads(tool({"data_file": "../project_sources/01-BRIEF.md", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertFalse(rejected["success"])

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
        self.assertEqual(response["info"]["datasets"][0]["students"], 30)
        self.assertEqual(response["analysis"]["result"]["summary"]["candidates"], 3)

    def test_cli_shows_every_case_and_preserves_json_option(self):
        args = [sys.executable, "-m", "student_followup", "--data", "data/fictional_school.json",
                "--start", "2026-09-07", "--end", "2026-09-11"]
        report = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertIn("حالات للمراجعة: 3 | حالات تحتاج استكمال بيانات: 1", report)
        for sid in ("S-002", "S-003", "S-006", "S-004"):
            self.assertIn(sid, report)
        self.assertIn("حضور غير مسجل (ليس غيابًا)", report)
        machine = subprocess.run(args + ["--json"], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(machine.stdout)["summary"]["candidates"], 3)

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
