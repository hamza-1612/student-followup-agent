"""Create a reproducible, entirely fictional 30-student demonstration file."""

import json
from pathlib import Path


def build():
    students = [{"student_id": f"S-{i:03}", "alias": f"Student {i:03}"} for i in range(1, 31)]
    days = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    attendance = []
    for student in students:
        sid = student["student_id"]
        for day in days:
            status = "present"
            if sid in {"S-002", "S-006"} and day in {"2026-09-08", "2026-09-10"}:
                status = "absent"
            if sid == "S-004" and day == "2026-09-10":
                status = "unrecorded"
            if sid == "S-006" and day == "2026-09-11":
                status = "unrecorded"
            attendance.append({"student_id": sid, "date": day, "status": status})
    assessments = []
    for student in students:
        sid = student["student_id"]
        assessments.extend([
            {"student_id": sid, "subject": "Mathematics", "date": "2026-08-28", "score": 80, "max_score": 100},
            {"student_id": sid, "subject": "Mathematics", "date": "2026-09-11", "score": 62 if sid in {"S-003", "S-006"} else 80, "max_score": 100},
        ])
    return {"students": students, "school_days": days, "attendance": attendance, "assessments": assessments,
            "followups": [{"id": "F-001", "student_id": "S-002", "date": "2026-09-09",
                           "topic": "attendance", "outcome": "Teacher requested a check-in; response pending"}]}


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "data" / "fictional_school.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(destination)
