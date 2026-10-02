"""Read-only command-line entry point; Python standard library only."""

import argparse
import json
import sys
from pathlib import Path

from .core import DataError, analyze
from .reviews import DEFAULT_OUTPUT, attach_reviews, dataset_hash, load_latest


def format_report(result):
    summary = result["summary"]
    period = result["period"]
    lines = [
        f"متابعة الطلاب | {period['start']} إلى {period['end']}",
        f"الطلاب: {summary['students']} | سجلات الحضور: {summary['attendance_records_in_period']}",
        f"حالات للمراجعة: {summary['candidates']} | حالات تحتاج استكمال بيانات: {summary['unresolved']}",
        "",
        "الإنذارات التجريبية (الأولوية الأعلى أولًا):",
    ]
    if not result["candidates"]:
        lines.append("لا توجد حالات بلغت عتبة الإنذار ضمن الفترة.")
    for case in result["candidates"]:
        level = "أعلى" if case["priority"] == "high" else "عادية"
        lines.append(f"- {case['student_id']} ({case['alias']}) | أولوية {level}")
        for item in case["observations"]:
            if item["type"] == "recorded_absence":
                lines.append(f"  غياب مسجل: {item['count']} يوم؛ التواريخ: {', '.join(item['dates'])}؛ المصدر: attendance")
            elif item["type"] == "lower_comparable_score":
                previous, current = item["previous"], item["current"]
                lines.append(f"  انخفاض علامة {item['subject']}: {previous['percent']}% ({previous['date']}) إلى {current['percent']}% ({current['date']})؛ المصدر: assessments")
        for followup in case["previous_followups"]:
            lines.append(f"  متابعة مسجلة: {followup['date']} | {followup['topic']} | {followup['outcome']}")
        if not case["previous_followups"]:
            lines.append("  لا توجد متابعة سابقة في الملف.")
        if case["attendance"]["unrecorded"]:
            lines.append(f"  حضور غير مسجل (ليس غيابًا): {', '.join(case['attendance']['explicit_unrecorded_dates'])}")
        if case["attendance"]["missing_record_dates"]:
            lines.append(f"  سجل حضور مفقود (ليس غيابًا): {', '.join(case['attendance']['missing_record_dates'])}")
        if case.get("review"):
            lines.append(f"  قرار المراجع: {case['review']['decision']} | {case['review']['note']}")

    lines.extend(["", "حالات تحتاج استكمال بيانات:"])
    if not result["unresolved"]:
        lines.append("لا توجد حالات غير محسومة.")
    for case in result["unresolved"]:
        attendance = case["attendance"]
        missing = []
        if not (attendance["present"] or attendance["absent"] or attendance["unrecorded"]):
            missing.append("لا توجد سجلات حضور في الفترة")
        if attendance["explicit_unrecorded_dates"]:
            missing.append("حضور غير مسجل في " + ", ".join(attendance["explicit_unrecorded_dates"]))
        if attendance["missing_record_dates"]:
            missing.append("سجل حضور مفقود في " + ", ".join(attendance["missing_record_dates"]))
        lines.append(f"- {case['student_id']} ({case['alias']}): {'؛ '.join(missing)}")
        lines.append("  هذا ليس غيابًا مسجلًا.")
        if case.get("review"):
            lines.append(f"  قرار المراجع: {case['review']['decision']} | {case['review']['note']}")
    lines.extend(["", "عتبات تجريبية للمراجعة: غياب مسجل يومان ضمن خمسة أيام دراسية، أو نزول 15 نقطة مئوية في المادة نفسها؛ اجتماع المؤشرين أولوية أعلى. الحضور غير المسجل ليس غيابًا. لم تُرسل رسائل أو تُعدّل سجلات."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review fictional student follow-up records")
    parser.add_argument("--data", required=True, help="JSON input file")
    parser.add_argument("--start", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="print full machine-readable JSON instead of a concise report")
    parser.add_argument("--reviews", type=Path, default=DEFAULT_OUTPUT,
                        help="local JSONL reviewer decisions (default: outputs/reviews.jsonl)")
    args = parser.parse_args(argv)
    try:
        data_bytes = Path(args.data).read_bytes()
        payload = json.loads(data_bytes)
        result = analyze(payload, args.start, args.end)
        attach_reviews(result, load_latest(args.reviews, dataset_hash(data_bytes), args.start, args.end))
    except (DataError, OSError, ValueError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
