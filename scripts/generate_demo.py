"""Create a reproducible, entirely fictional 50-student demonstration file."""

import json
from pathlib import Path


def build():
    names = (
        "آدم خالد|ليان عمر|يوسف سامر|مريم ناصر|سليم فؤاد|تالا أمجد|مالك ياسر|جنى كريم|"
        "محمد باسل|نور حسن|ياسين علي|رزان مؤيد|عمر رائد|سارة مازن|حمزة عادل|لين أحمد|"
        "زيد إبراهيم|هبة وليد|أمير خالد|دانا نائل|إياد يوسف|ملك فارس|أنس هشام|رنا حسام|"
        "كريم أسعد|جود هاني|راشد تامر|جنى منذر|باسل إيهاب|سما علاء|فارس رامي|هدى وسيم|"
        "أحمد سائد|لمى سعيد|تيم حازم|ميس قاسم|سامي طارق|آية أكرم|فادي خليل|رهف جمال|"
        "خالد هيثم|بتول نبيل|علي يزن|ريم ماهر|سيف مجدي|نورا محمود|يزن خالد|فرح زياد|"
        "بلال نادر|ديمة طلال"
    ).split("|")
    students = [{"student_id": f"S-{i:03}", "alias": name,
                 "guardian_name": f"ولي أمر {name}", "teacher_name": "معلم الصف"}
                for i, name in enumerate(names, 1)]
    days = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    attendance = []
    for student in students:
        sid = student["student_id"]
        for day in days:
            status = "present"
            if sid in {"S-002", "S-006", "S-031", "S-034", "S-035"} and day in {"2026-09-08", "2026-09-10"}:
                status = "absent"
            if sid == "S-004" and day == "2026-09-10":
                status = "unrecorded"
            if sid == "S-006" and day == "2026-09-11":
                status = "unrecorded"
            if sid == "S-033" and day == "2026-09-09":
                status = "unrecorded"
            attendance.append({"student_id": sid, "date": day, "status": status})
    assessments = []
    for student in students:
        sid = student["student_id"]
        assessments.extend([
            {"student_id": sid, "subject": "Mathematics", "date": "2026-08-28", "score": 80, "max_score": 100},
            {"student_id": sid, "subject": "Mathematics", "date": "2026-09-11",
             "score": 62 if sid in {"S-003", "S-006", "S-032", "S-034"} else 80, "max_score": 100},
        ])
    return {"students": students, "school_days": days, "attendance": attendance, "assessments": assessments,
            "followups": [{"id": "F-001", "student_id": "S-002", "date": "2026-09-09",
                           "topic": "attendance", "outcome": "Teacher requested a check-in; response pending"},
                          {"id": "F-002", "student_id": "S-035", "date": "2026-09-09",
                           "topic": "attendance", "outcome": "Teacher requested a family check-in; response pending"}]}


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "data" / "fictional_school.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(destination)
