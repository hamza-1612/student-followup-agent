"""Versioned, automatic tuning from explicit reviewer labels.

No model weights or source code are changed. Core data invariants stay fixed.
"""

import json
import os
from collections import Counter

from .core import DataError, analyze
from .storage import OUTPUT, _lock, append_event, events


DEFAULT = {"absence_threshold": 2, "score_drop_threshold": 15}
CHOICES = [(absence, score) for absence in (1, 2, 3) for score in (10, 15, 20)]


def policy():
    path = OUTPUT / "rules.json"
    if not path.exists():
        return {"version": 1, **DEFAULT}
    data = json.loads(path.read_text(encoding="utf-8"))
    analyze({"students": [], "attendance": [], "assessments": [], "followups": []},
            "2026-01-01", "2026-01-01", data)
    return data


def _features(data, start, end, student_id):
    if student_id not in {row["student_id"] for row in data["students"]}:
        raise DataError("unknown student_id")
    result = analyze(data, start, end, {"absence_threshold": 1, "score_drop_threshold": 1})
    case = next((case for case in result["candidates"] + result["unresolved"]
                 if case["student_id"] == student_id), None)
    if case is None:
        return {"absences_in_five": 0, "score_drop": 0}
    absence = max((item["count"] for item in case["alerts"]
                   if item["type"] == "absence_in_five_school_days"), default=0)
    score = max((item["drop_percentage_points"] for item in case["observations"]
                 if item["type"] == "lower_comparable_score"), default=0)
    return {"absences_in_five": absence, "score_drop": score}


def _predict(row, pair):
    return row["features"]["absences_in_five"] >= pair[0] or row["features"]["score_drop"] >= pair[1]


def _balanced_accuracy(rows, pair):
    positive = [row for row in rows if row["label"] in ("confirmed", "missed_case")]
    negative = [row for row in rows if row["label"] == "false_alert"]
    return (sum(_predict(row, pair) for row in positive) / len(positive)
            + sum(not _predict(row, pair) for row in negative) / len(negative)) / 2


def _maybe_tune():
    latest = {}
    for row in events("feedback.jsonl"):
        latest[(row["data_file"], row["student_id"], row["period"]["start"],
                row["period"]["end"])] = row
    rows = list(latest.values())
    counts = Counter(row["label"] for row in rows)
    if len(rows) < 8 or counts["confirmed"] + counts["missed_case"] < 3 or counts["false_alert"] < 3:
        return None
    current = policy()
    old_pair = (current["absence_threshold"], current["score_drop_threshold"])
    baseline = _balanced_accuracy(rows, old_pair)
    best = max(CHOICES, key=lambda pair: (_balanced_accuracy(rows, pair),
                                          -abs(pair[0] - old_pair[0]) - abs(pair[1] - old_pair[1])))
    score = _balanced_accuracy(rows, best)
    if best == old_pair or score < baseline + 0.1:
        return None
    updated = {"version": current["version"] + 1, "absence_threshold": best[0],
               "score_drop_threshold": best[1]}
    path = OUTPUT / "rules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    append_event("policy_history.jsonl", {"before": current, "after": updated,
                 "labels": dict(counts), "balanced_accuracy_before": round(baseline, 3),
                 "balanced_accuracy_after": round(score, 3)})
    return updated


def record_feedback(data_file, data, start, end, student_id, label, note):
    if label not in ("confirmed", "false_alert", "missed_case"):
        raise DataError("label must be confirmed, false_alert, or missed_case")
    if not isinstance(note, str) or not note.strip() or len(note) > 500:
        raise DataError("feedback note must be 1 to 500 characters")
    with _lock:
        result = analyze(data, start, end, policy())
        flagged = {case["student_id"] for case in result["candidates"]}
        if label == "missed_case" and student_id in flagged:
            raise DataError("student is already a candidate; use confirmed or false_alert")
        if label != "missed_case" and student_id not in flagged:
            raise DataError("student has no alert in this period; use missed_case if a case was missed")
        features = _features(data, start, end, student_id)
        row = append_event("feedback.jsonl", {"data_file": data_file,
                           "period": {"start": start, "end": end}, "student_id": student_id,
                           "label": label, "note": note.strip(), "features": features})
        changed = _maybe_tune()
        return {"feedback": row, "policy": policy(), "policy_changed": changed is not None}
