"""Explicit local school actions; external email requires real configuration."""

import os
import hashlib
import json
import smtplib
import ssl
import uuid
from email.message import EmailMessage

from .core import DataError, _day
from .storage import _lock, append_event, events, read_data, save_data


def execute(data_file, action, actor, student_id=None, day=None, status=None,
            followup_id=None, outcome=None, recipient_type=None, subject=None,
            message=None, request_id=None):
    if action not in ("record_attendance", "resolve_followup", "queue_contact", "send_email", "add_school_day"):
        raise DataError("unsupported action")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
        raise DataError("enter the local operator name")
    if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 100):
        raise DataError("invalid request_id")
    request_id = request_id or uuid.uuid4().hex
    fingerprint = hashlib.sha256(json.dumps({"data_file": data_file, "action": action,
        "actor": actor, "student_id": student_id, "day": day, "status": status,
        "followup_id": followup_id, "outcome": outcome, "recipient_type": recipient_type,
        "subject": subject, "message": message}, sort_keys=True).encode("utf-8")).hexdigest()
    with _lock:
        for prior in reversed(events("actions.jsonl")):
            if prior["request_id"] == request_id:
                if prior.get("fingerprint") != fingerprint:
                    raise DataError("request_id already belongs to a different action")
                return prior
        data = read_data(data_file)
        students = {row["student_id"]: row for row in data["students"]}
        if action != "add_school_day" and student_id not in students:
            raise DataError("unknown student_id")
        details = {}
        if action == "add_school_day":
            school_day = _day(day, "day").isoformat()
            dates = data.setdefault("school_days", sorted({row["date"] for row in data["attendance"]}))
            if school_day in dates:
                raise DataError("day already belongs to the school calendar")
            dates.append(school_day)
            dates.sort()
            save_data(data_file, data)
            details = {"day": school_day}
        elif action == "record_attendance":
            school_day = _day(day, "day").isoformat()
            if school_day not in data.get("school_days", {row["date"] for row in data["attendance"]}):
                raise DataError("register the school day first")
            if status not in ("present", "absent", "unrecorded"):
                raise DataError("status must be present, absent, or unrecorded")
            current = next((row for row in data["attendance"] if row["student_id"] == student_id
                            and row["date"] == school_day), None)
            before = current["status"] if current else None
            if current:
                current["status"] = status
            else:
                data["attendance"].append({"student_id": student_id, "date": school_day, "status": status})
            save_data(data_file, data)
            details = {"student_id": student_id, "day": school_day, "before": before, "after": status}
        elif action == "resolve_followup":
            if not isinstance(outcome, str) or not outcome.strip() or len(outcome) > 500:
                raise DataError("enter a follow-up outcome")
            current = next((row for row in data["followups"] if row["id"] == followup_id
                            and row["student_id"] == student_id), None)
            if not current:
                raise DataError("follow-up does not belong to this student")
            before = current["outcome"]
            current["outcome"] = outcome.strip()
            save_data(data_file, data)
            details = {"student_id": student_id, "followup_id": followup_id,
                       "before": before, "after": outcome.strip()}
        else:
            if recipient_type not in ("guardian", "student"):
                raise DataError("recipient_type must be guardian or student")
            if not isinstance(message, str) or not message.strip() or len(message) > 2000:
                raise DataError("message must be 1 to 2000 characters")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 160:
                raise DataError("subject must be 1 to 160 characters")
            email = students[student_id].get(recipient_type + "_email")
            if action == "send_email":
                if not isinstance(email, str) or "@" not in email or email.endswith(".invalid"):
                    raise DataError("no verified email address for this recipient in the dataset")
                required = ("STUDENT_FOLLOWUP_SMTP_HOST", "STUDENT_FOLLOWUP_SMTP_USER",
                            "STUDENT_FOLLOWUP_SMTP_PASSWORD", "STUDENT_FOLLOWUP_SMTP_FROM")
                if not all(os.environ.get(key) for key in required):
                    raise DataError("SMTP is not configured; message was not sent")
                details = {"student_id": student_id, "recipient_type": recipient_type,
                           "recipient": email, "subject": subject.strip(), "message": message.strip()}
                append_event("actions.jsonl", {"request_id": request_id, "fingerprint": fingerprint,
                             "actor": actor.strip(),
                             "action": action, "data_file": data_file, "state": "sending", "details": details})
                letter = EmailMessage()
                letter["From"] = os.environ["STUDENT_FOLLOWUP_SMTP_FROM"]
                letter["To"] = email
                letter["Subject"] = subject.strip()
                letter.set_content(message.strip())
                try:
                    with smtplib.SMTP_SSL(os.environ["STUDENT_FOLLOWUP_SMTP_HOST"],
                                          int(os.environ.get("STUDENT_FOLLOWUP_SMTP_PORT", "465")),
                                          context=ssl.create_default_context(), timeout=15) as smtp:
                        smtp.login(os.environ["STUDENT_FOLLOWUP_SMTP_USER"],
                                   os.environ["STUDENT_FOLLOWUP_SMTP_PASSWORD"])
                        smtp.send_message(letter)
                except (OSError, smtplib.SMTPException, ValueError) as exc:
                    append_event("actions.jsonl", {"request_id": request_id, "fingerprint": fingerprint,
                                 "actor": actor.strip(),
                                 "action": action, "data_file": data_file, "state": "failed_or_unknown",
                                 "details": details})
                    raise DataError("Email delivery was not confirmed; check the provider before retrying") from exc
            else:
                details = {"student_id": student_id, "recipient_type": recipient_type,
                           "recipient": email, "subject": subject.strip(), "message": message.strip()}
        state = "sent" if action == "send_email" else "queued_local" if action == "queue_contact" else "completed"
        return append_event("actions.jsonl", {"request_id": request_id, "fingerprint": fingerprint,
                            "actor": actor.strip(),
                            "action": action, "data_file": data_file, "state": state, "details": details})
