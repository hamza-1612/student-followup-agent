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
            from student_followup.storage import read_data

            data_dir = (project / "data").resolve()
            datasets = []
            for path in sorted(data_dir.glob("*.json")):
                if not path.resolve().is_relative_to(data_dir):
                    continue
                payload = read_data(path.relative_to(project).as_posix())
                # Reuse full validation; do not report a student count from bad data.
                result = analyze(payload, "0001-01-01", "9999-12-31")
                attendance_dates = sorted(payload.get("school_days", {row["date"] for row in payload["attendance"]}))
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
        "description": "Validate fictional school JSON and apply demo review alerts. Summary.attendance gives actual present/absent/unrecorded counts by date and distinct students present at least once or every recorded school day. Attendance record count is not present-student count. Summary.data_quality_details lists gaps. Read-only; no messages.",
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
            from student_followup.storage import read_bytes
            from student_followup.learning import policy

            data_dir = (project / "data").resolve()
            target = (project / params["data_file"]).resolve()
            if not target.is_relative_to(data_dir) or target.suffix.lower() != ".json":
                raise DataError("data_file must be a JSON file inside the project data directory")
            data_bytes = read_bytes(target.relative_to(project).as_posix())
            payload = json.loads(data_bytes)
            result = analyze(payload, params["period_start"], params["period_end"], policy())
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

    report_schema = {"name": "student_followup_report",
        "description": "Create an on-demand daily or date-range report for the user's stated purpose; include actual attendance and every missing attendance record.",
        "parameters": {"type": "object", "properties": {
            "data_file": {"type": "string"}, "period_start": {"type": "string"},
            "period_end": {"type": "string"}, "purpose": {"type": "string"}},
            "required": ["data_file", "period_start", "period_end", "purpose"]}}

    def report_handler(params, **kwargs):
        del kwargs
        try:
            _project_package()
            from student_followup.storage import read_data
            from student_followup.learning import policy
            from student_followup.reports import create_report
            from student_followup.storage import append_event
            result = create_report(read_data(params["data_file"]), params["period_start"],
                                   params["period_end"], params["purpose"], policy())
            append_event("reports.jsonl", {"data_file": params["data_file"], "report": result})
            return json.dumps({"success": True, "report": result}, ensure_ascii=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    action_schema = {"name": "student_followup_action",
        "description": "Execute an explicitly requested attendance/follow-up change, school-day registration, local contact queue, or email with configured address and SMTP. Call this tool for a specific user command in chat and report its actual state. If actor is omitted, an unverified chat operator label is recorded. Never infer an action from analysis alone; queue_contact is not email delivery.",
        "parameters": {"type": "object", "properties": {
            "data_file": {"type": "string"}, "action": {"type": "string", "enum": ["record_attendance", "resolve_followup", "add_school_day", "queue_contact", "send_email"]},
            "actor": {"type": "string", "description": "Optional operator name; defaults to an unverified local chat user"},
            "student_id": {"type": "string"}, "day": {"type": "string"},
            "status": {"type": "string", "enum": ["present", "absent", "unrecorded"]},
            "followup_id": {"type": "string"}, "outcome": {"type": "string"},
            "recipient_type": {"type": "string", "enum": ["guardian", "student"]},
            "subject": {"type": "string"}, "message": {"type": "string"},
            "request_id": {"type": "string", "description": "Stable ID to prevent duplicate retries"}},
            "required": ["data_file", "action"]}}

    def action_handler(params, **kwargs):
        del kwargs
        try:
            _project_package()
            from student_followup.actions import execute
            request = dict(params)
            request.setdefault("actor", "مستخدم المحادثة (هوية غير موثقة)")
            return json.dumps({"success": True, "action": execute(**request)}, ensure_ascii=False)
        except (TypeError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    feedback_schema = {"name": "student_followup_feedback",
        "description": "Save explicit reviewer evidence that a signal was confirmed, false, or a missed case. The local rules may automatically improve after enough labeled cases; no separate approval is required.",
        "parameters": {"type": "object", "properties": {
            "data_file": {"type": "string"}, "period_start": {"type": "string"},
            "period_end": {"type": "string"}, "student_id": {"type": "string"},
            "label": {"type": "string", "enum": ["confirmed", "false_alert", "missed_case"]},
            "note": {"type": "string"}},
            "required": ["data_file", "period_start", "period_end", "student_id", "label", "note"]}}

    def feedback_handler(params, **kwargs):
        del kwargs
        try:
            _project_package()
            from student_followup.storage import read_data
            from student_followup.learning import record_feedback
            result = record_feedback(params["data_file"], read_data(params["data_file"]),
                params["period_start"], params["period_end"], params["student_id"],
                params["label"], params["note"])
            return json.dumps({"success": True, **result}, ensure_ascii=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    context_schema = {"name": "student_followup_context",
        "description": "Recall persisted actions, reviewer feedback, and answers for this dataset or one student across conversations. Never claim queued messages were sent.",
        "parameters": {"type": "object", "properties": {
            "data_file": {"type": "string"}, "student_id": {"type": "string"}},
            "required": ["data_file"]}}

    def context_handler(params, **kwargs):
        del kwargs
        try:
            _project_package()
            from student_followup.context import case_context
            return json.dumps({"success": True, "events": case_context(params["data_file"],
                params.get("student_id"))}, ensure_ascii=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    for tool in (("student_followup_report", report_schema, report_handler),
                 ("student_followup_action", action_schema, action_handler),
                 ("student_followup_feedback", feedback_schema, feedback_handler),
                 ("student_followup_context", context_schema, context_handler)):
        ctx.register_tool(name=tool[0], toolset="student_followup", schema=tool[1], handler=tool[2])
