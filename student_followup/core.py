"""Validate fictional records and apply the approved demo review thresholds."""

from collections import Counter, defaultdict
from datetime import date
from math import isfinite


class DataError(ValueError):
    """Invalid input; analysis must not continue on ambiguous evidence."""


def _fields(obj, required, where):
    if not isinstance(obj, dict) or not set(required) <= set(obj):
        raise DataError(f"{where}: required fields: {', '.join(required)}")


def _day(value, where):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise DataError(f"{where}: expected ISO date YYYY-MM-DD") from None


def analyze(data, period_start, period_end):
    """Return JSON-serializable facts. Never treat a missing record as an absence."""
    start, end = _day(period_start, "period_start"), _day(period_end, "period_end")
    if start > end:
        raise DataError("period_start must be on or before period_end")
    _fields(data, ("students", "attendance", "assessments", "followups"), "data")
    for name in ("students", "attendance", "assessments", "followups"):
        if not isinstance(data[name], list):
            raise DataError(f"{name}: expected a list")

    students = {}
    for idx, row in enumerate(data["students"], 1):
        _fields(row, ("student_id", "alias"), f"students[{idx}]")
        sid, alias = row["student_id"], row["alias"]
        if not isinstance(sid, str) or not sid.strip() or not isinstance(alias, str) or not alias.strip():
            raise DataError(f"students[{idx}]: student_id and alias must be nonempty strings")
        if sid in students:
            raise DataError(f"students[{idx}]: duplicate student_id {sid}")
        students[sid] = alias

    def check_sid(row, label):
        sid = row["student_id"]
        if sid not in students:
            raise DataError(f"{label}: unknown student_id {sid!r}")
        return sid

    attendance = defaultdict(list)
    attendance_keys = set()
    school_dates = set()
    for idx, row in enumerate(data["attendance"], 1):
        label = f"attendance[{idx}]"
        _fields(row, ("student_id", "date", "status"), label)
        sid = check_sid(row, label)
        day = _day(row["date"], label)
        if row["status"] not in ("present", "absent", "unrecorded"):
            raise DataError(f"{label}: status must be present, absent, or unrecorded")
        key = (sid, day)
        if key in attendance_keys:
            raise DataError(f"{label}: duplicate or conflicting attendance for {sid} on {day}")
        attendance_keys.add(key)
        if start <= day <= end:
            school_dates.add(day.isoformat())
            attendance[sid].append({"date": day.isoformat(), "status": row["status"]})

    # Attendance dates in the input define school days for this fictional demo.
    # A full window is required; never infer absence from an omitted row.
    days = sorted(school_dates)
    windows = [set(days[i:i + 5]) for i in range(max(0, len(days) - 4))]

    assessments = defaultdict(lambda: defaultdict(dict))
    for idx, row in enumerate(data["assessments"], 1):
        label = f"assessments[{idx}]"
        _fields(row, ("student_id", "subject", "date", "score", "max_score"), label)
        sid = check_sid(row, label)
        day = _day(row["date"], label)
        subject, score, maximum = row["subject"], row["score"], row["max_score"]
        if not isinstance(subject, str) or not subject.strip():
            raise DataError(f"{label}: subject must be a nonempty string")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in (score, maximum)) or maximum <= 0 or not 0 <= score <= maximum:
            raise DataError(f"{label}: score must be numeric between 0 and positive max_score")
        key = (subject, day)
        if key in assessments[sid][subject]:
            raise DataError(f"{label}: duplicate assessment for {sid}, {subject}, {day}")
        assessments[sid][subject][key] = (day, score, maximum)

    followups = defaultdict(list)
    followup_keys = set()
    for idx, row in enumerate(data["followups"], 1):
        label = f"followups[{idx}]"
        _fields(row, ("id", "student_id", "date", "topic", "outcome"), label)
        sid = check_sid(row, label)
        day = _day(row["date"], label)
        if not isinstance(row["id"], str) or not row["id"].strip() or row["id"] in followup_keys:
            raise DataError(f"{label}: id must be a unique nonempty string")
        followup_keys.add(row["id"])
        if any(not isinstance(row[field], str) or not row[field].strip() for field in ("topic", "outcome")):
            raise DataError(f"{label}: topic and outcome must be nonempty strings")
        if day <= end:
            followups[sid].append({field: row[field] for field in ("id", "date", "topic", "outcome")})

    candidates, unresolved = [], []
    for sid, alias in students.items():
        records = sorted(attendance[sid], key=lambda r: r["date"])
        counts = Counter(r["status"] for r in records)
        absences = [r["date"] for r in records if r["status"] == "absent"]
        unknown = [r["date"] for r in records if r["status"] == "unrecorded"]
        observations = []
        alerts = []
        if absences:
            observations.append({"type": "recorded_absence", "count": len(absences), "dates": absences, "source": "attendance"})
        qualifying = []
        for window in windows:
            window_absences = [day for day in absences if day in window]
            if len(window_absences) >= 2:
                qualifying.append((len(window_absences), sorted(window), window_absences))
        if qualifying:
            count, window_days, dates = max(qualifying, key=lambda item: (item[0], item[1]))
            alerts.append({"type": "absence_in_five_school_days", "count": count,
                           "threshold": 2, "window_dates": window_days, "dates": dates,
                           "source": "attendance"})
        for subject, by_date in sorted(assessments[sid].items()):
            within = sorted((item for item in by_date.values() if start <= item[0] <= end), key=lambda v: v[0])
            history = sorted(by_date.values(), key=lambda v: v[0])
            for current in within:
                previous = next((item for item in reversed(history) if item[0] < current[0]), None)
                if previous is None:
                    continue
                old_pct = round(100 * previous[1] / previous[2], 2)
                new_pct = round(100 * current[1] / current[2], 2)
                drop = 100 * (previous[1] / previous[2] - current[1] / current[2])
                if drop > 0:
                    observation = {"type": "lower_comparable_score", "subject": subject,
                                   "previous": {"date": previous[0].isoformat(), "score": previous[1], "max_score": previous[2], "percent": old_pct},
                                   "current": {"date": current[0].isoformat(), "score": current[1], "max_score": current[2], "percent": new_pct},
                                   "drop_percentage_points": round(drop, 2), "source": "assessments"}
                    observations.append(observation)
                    if drop >= 15:
                        alerts.append({"type": "score_drop", "subject": subject,
                                       "drop_percentage_points": round(drop, 2), "threshold": 15,
                                       "previous": observation["previous"], "current": observation["current"],
                                       "source": "assessments"})
        prior = sorted(followups[sid], key=lambda r: (r["date"], r["id"]), reverse=True)
        kinds = {item["type"] for item in alerts}
        priority = "high" if len(kinds) == 2 else "standard" if alerts else "needs_verification"
        case = {"student_id": sid, "alias": alias, "priority": priority,
                "alerts": alerts, "observations": observations,
                "attendance": {"present": counts["present"], "absent": counts["absent"], "unrecorded": counts["unrecorded"], "explicit_unrecorded_dates": unknown},
                "previous_followups": prior, "missing_information": (["No attendance records in selected period"] if not records else []) + (["Attendance unrecorded on: " + ", ".join(unknown)] if unknown else [])}
        if alerts:
            candidates.append(case)
        elif case["missing_information"]:
            unresolved.append(case)
    candidates.sort(key=lambda case: (case["priority"] != "high", case["student_id"]))
    return {"period": {"start": period_start, "end": period_end}, "summary": {
        "students": len(students), "attendance_records_in_period": sum(len(v) for v in attendance.values()),
        "assessment_records": len(data["assessments"]), "followup_records": len(data["followups"]),
        "candidates": len(candidates), "unresolved": len(unresolved),
        "data_quality_issues": sum(1 for c in candidates + unresolved if c["missing_information"]),
        "time_saved": None, "model_calls": None, "tokens_used": None},
        "candidates": candidates, "unresolved": unresolved,
        "policy_note": "Demo review rules: 2 recorded absences within 5 supplied school dates, or a 15 percentage-point score drop in the same subject. Both signals rank higher. Missing attendance is not absence. These are not educational diagnoses. No messages sent or records changed."}
