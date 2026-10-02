"""Local reviewer decisions for a fictional demo; no external actions."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import DataError, analyze


DECISIONS = ("follow_up_approved", "verify_data", "no_action")
DEFAULT_OUTPUT = Path("outputs/reviews.jsonl")


def dataset_hash(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()


def load_latest(path, data_hash, start, end):
    """Return the last recorded decision per student for this exact dataset/period."""
    latest = {}
    if not path.exists():
        return latest
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not all(key in row for key in
                ("student_id", "decision", "note", "dataset_sha256", "period")):
                raise ValueError("missing fields")
        except (json.JSONDecodeError, ValueError) as exc:
            raise DataError(f"{path}:{number}: invalid review record ({exc})") from None
        if (row["dataset_sha256"] == data_hash and row["period"] ==
            {"start": start, "end": end}):
            latest[row["student_id"]] = {"decision": row["decision"], "note": row["note"],
                                          "recorded_at": row.get("recorded_at")}
    return latest


def attach_reviews(result, latest):
    for case in result["candidates"] + result["unresolved"]:
        if case["student_id"] in latest:
            case["review"] = latest[case["student_id"]]
    return result


def record_review(data_bytes, start, end, student_id, decision, note, output):
    if decision not in DECISIONS:
        raise DataError("invalid review decision")
    if not isinstance(note, str) or not note.strip():
        raise DataError("review note cannot be empty")
    try:
        data = json.loads(data_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataError(f"invalid JSON input: {exc}") from None
    result = analyze(data, start, end)
    if student_id not in {case["student_id"] for case in result["candidates"] + result["unresolved"]}:
        raise DataError(f"{student_id}: no review case in the selected period")
    row = {"recorded_at": datetime.now(timezone.utc).isoformat(),
           "dataset_sha256": dataset_hash(data_bytes), "period": result["period"],
           "student_id": student_id, "decision": decision, "note": note.strip(),
           "executed": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record an explicit human review decision locally")
    parser.add_argument("--data", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--decision", choices=DECISIONS, required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        row = record_review(Path(args.data).read_bytes(), args.start, args.end,
                            args.student_id, args.decision, args.note, args.output)
    except (DataError, OSError) as exc:
        print(f"Review error: {exc}", file=sys.stderr)
        return 2
    print(f"سُجّل قرار {row['student_id']} في {args.output}. لم تُرسل رسالة ولم يُنفذ إجراء خارجي.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
