import copy
import importlib.util
import json
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
        candidates = {c["student_id"]: c for c in result["candidates"]}
        self.assertEqual(set(candidates), {"S-002", "S-003", "S-006"})
        self.assertEqual(candidates["S-002"]["observations"][0]["dates"], ["2026-09-08", "2026-09-10"])
        self.assertEqual(len(candidates["S-002"]["previous_followups"]), 1)
        self.assertEqual(candidates["S-003"]["observations"][0]["current"]["percent"], 62)
        self.assertEqual(result["unresolved"][0]["student_id"], "S-004")
        self.assertEqual(result["unresolved"][0]["attendance"]["absent"], 0)
        self.assertEqual(candidates["S-006"]["attendance"]["unrecorded"], 1)
        self.assertIsNone(result["summary"]["tokens_used"])

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
                                {"student_id": "S-A", "subject": "Math", "date": "2026-10-01", "score": 7, "max_score": 10}],
                "followups": []}
        result = analyze(data, "2026-10-01", "2026-10-01")
        self.assertEqual(result["summary"]["candidates"], 1)
        self.assertEqual(result["candidates"][0]["attendance"]["absent"], 0)
        self.assertEqual(result["candidates"][0]["observations"][0]["type"], "lower_comparable_score")

    def test_plugin_exposes_read_only_tool_and_confines_input(self):
        spec = importlib.util.spec_from_file_location("demo_plugin", ROOT / ".hermes/plugins/student-followup/__init__.py")
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)

        class Context:
            def register_tool(self, **kwargs):
                self.registration = kwargs

        ctx = Context()
        plugin.register(ctx)
        self.assertEqual(ctx.registration["name"], "student_followup_analyze")
        tool = ctx.registration["handler"]
        result = json.loads(tool({"data_file": "data/fictional_school.json", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["summary"]["candidates"], 3)
        rejected = json.loads(tool({"data_file": "../project_sources/01-BRIEF.md", "period_start": "2026-09-07", "period_end": "2026-09-11"}))
        self.assertFalse(rejected["success"])


if __name__ == "__main__":
    unittest.main()
