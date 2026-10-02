"""Project-local Hermes tool; analysis stays in the testable core."""

import json
import sys
from pathlib import Path


def _project_package():
    project = Path(__file__).resolve().parents[3]
    # The Windows launcher may omit the project from sys.path.
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    return project


def register(ctx):
    info_schema = {
        "name": "student_followup_info",
        "description": "List available project JSON datasets, student counts, and recorded attendance date ranges. Use for 'how many students', 'existing data file', or 'whole period' before analysis. Read-only; no date range needed.",
        "parameters": {"type": "object", "properties": {}},
    }

    def info_handler(params, **kwargs):
        del params, kwargs
        try:
            project = _project_package()
            from student_followup import analyze

            data_dir = (project / "data").resolve()
            datasets = []
            for path in sorted(data_dir.glob("*.json")):
                if not path.resolve().is_relative_to(data_dir):
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                # Reuse full validation; do not report a student count from bad data.
                result = analyze(payload, "0001-01-01", "9999-12-31")
                attendance_dates = sorted({row["date"] for row in payload["attendance"]})
                datasets.append({
                    "data_file": path.relative_to(project).as_posix(),
                    "students": result["summary"]["students"],
                    "attendance_records": len(payload["attendance"]),
                    "assessment_records": len(payload["assessments"]),
                    "followup_records": len(payload["followups"]),
                    "attendance_period": {"start": attendance_dates[0], "end": attendance_dates[-1]}
                    if attendance_dates else None,
                })
            return json.dumps({"success": True, "datasets": datasets}, ensure_ascii=False)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    schema = {
        "name": "student_followup_analyze",
        "description": "Validate fictional school JSON and apply demo review alerts: 2 recorded absences in 5 supplied school dates or a 15-point score drop in the same subject. The summary lists attendance gaps in data_quality_details; equal scores between different students are not duplicate records. Read-only; no messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_file": {"type": "string", "description": "Path to a JSON file inside this project's data directory"},
                "period_start": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
                "period_end": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
                "reviews_file": {"type": "string", "description": "Optional reviewer JSONL file inside outputs/; defaults to outputs/reviews.jsonl if present"},
            },
            "required": ["data_file", "period_start", "period_end"],
        },
    }

    def handler(params, **kwargs):
        del kwargs
        try:
            project = _project_package()
            from student_followup import DataError, analyze
            from student_followup.reviews import attach_reviews, dataset_hash, load_latest

            data_dir = (project / "data").resolve()
            target = (project / params["data_file"]).resolve()
            if not target.is_relative_to(data_dir) or target.suffix.lower() != ".json":
                raise DataError("data_file must be a JSON file inside the project data directory")
            data_bytes = target.read_bytes()
            payload = json.loads(data_bytes)
            result = analyze(payload, params["period_start"], params["period_end"])
            reviews_dir = (project / "outputs").resolve()
            reviews = (project / params.get("reviews_file", "outputs/reviews.jsonl")).resolve()
            if not reviews.is_relative_to(reviews_dir) or reviews.suffix.lower() != ".jsonl":
                raise DataError("reviews_file must be a JSONL file inside outputs/")
            attach_reviews(result, load_latest(reviews, dataset_hash(data_bytes),
                                               params["period_start"], params["period_end"]))
            return json.dumps({"success": True, "result": result}, ensure_ascii=False, allow_nan=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    ctx.register_tool(name="student_followup_info", toolset="student_followup", schema=info_schema, handler=info_handler)
    ctx.register_tool(name="student_followup_analyze", toolset="student_followup", schema=schema, handler=handler)
