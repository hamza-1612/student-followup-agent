"""Persistent, scoped case memory for later agent conversations."""

from .core import DataError
from .storage import dataset_path, events, read_data


def case_context(data_file, student_id=None, limit=25):
    dataset_path(data_file)
    if student_id is not None:
        if student_id not in {row["student_id"] for row in read_data(data_file)["students"]}:
            raise DataError("unknown student_id")
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise DataError("limit must be between 1 and 50")
    rows = []
    for entry in events("actions.jsonl"):
        if entry.get("data_file") != data_file or entry.get("state") == "sending":
            continue
        details = {key: value for key, value in entry.get("details", {}).items()
                   if key not in ("message", "recipient")}
        if student_id is None or details.get("student_id") == student_id:
            rows.append({"type": "action", "at": entry["at"], "action": entry["action"],
                         "state": entry["state"], "details": details})
    for entry in events("feedback.jsonl"):
        if entry.get("data_file") == data_file and (student_id is None or entry.get("student_id") == student_id):
            rows.append({"type": "feedback", "at": entry["at"], "student_id": entry["student_id"],
                         "label": entry["label"], "note": entry["note"]})
    for entry in events("reviews.jsonl"):
        if student_id is None or entry.get("student_id") == student_id:
            rows.append({"type": "review", "at": entry["recorded_at"],
                         "student_id": entry["student_id"], "period": entry["period"],
                         "decision": entry["decision"], "note": entry["note"],
                         "dataset_sha256": entry["dataset_sha256"]})
    for entry in events("dialogue.jsonl"):
        question_id = entry.get("question_id", "")
        if entry.get("data_file") == data_file and (student_id is None or entry.get("student_id") == student_id):
            rows.append({"type": "answer", "at": entry["at"], "question_id": question_id,
                         "answer": entry["answer"]})
    return sorted(rows, key=lambda item: item["at"], reverse=True)[:limit]
