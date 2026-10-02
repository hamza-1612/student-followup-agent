"""Purpose-specific reports grounded in deterministic analysis."""

from .core import DataError, analyze


def create_report(data, start, end, purpose="daily", rules=None):
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 160:
        raise DataError("describe the report purpose in 1 to 160 characters")
    result = analyze(data, start, end, rules)
    summary = result["summary"]
    return {"purpose": purpose.strip(), "period": result["period"],
            "students": summary["students"], "attendance_by_date": summary["attendance"]["by_date"],
            "present_at_least_once": summary["attendance"]["students_present_at_least_once"],
            "present_every_school_day": summary["attendance"]["students_present_every_recorded_school_day"],
            "cases": [{"student_id": case["student_id"], "priority": case["priority"],
                       "alerts": case["alerts"]} for case in result["candidates"]],
            "missing_attendance": summary["missing_attendance"],
            "calendar_source": summary["calendar_source"], "rules": summary["rules"]}
