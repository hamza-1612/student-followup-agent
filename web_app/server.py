"""Small localhost-only HTTP bridge for the demo UI and Hermes API server."""

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from student_followup import DataError, analyze, storage
from student_followup.actions import execute
from student_followup.context import case_context
from student_followup.learning import policy, record_feedback
from student_followup.reports import create_report
from student_followup.reviews import attach_reviews, dataset_hash, load_latest, record_review
from student_followup.storage import append_event, dataset_path, read_bytes, read_data


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
REVIEWS = ROOT / "outputs" / "reviews.jsonl"
HERMES_URL = "http://127.0.0.1:8642"
INSTRUCTIONS = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + (
    "\nThis local interface only handles the fictional school dataset. "
    "Use student_followup tools for facts, reports, explicit actions and feedback. "
    "Do not use terminal, file editing, web, or unrelated tools. "
    "A chat answer does not save a reviewer decision. "
    "Reply in natural Arabic, usually one to three short sentences. Answer the "
    "latest request without repeating the entire case list or numeric thresholds unless asked. "
    "For an explicit action, call student_followup_action and state the actual result. "
    "The tool supplies an unverified local chat actor when no name was given; "
    "do not ask for an operator name solely to use it. For a contact request, "
    "show a draft and let the person choose whether to send it. "
    "A sent_demo state means saved to the student's communication history. "
    "Confirm it with the exact phrase تم الإرسال. Do not mention the storage destination in user-facing replies. "
    "Never imply external delivery. Do not describe recorded messages as trials or simulations. Do not volunteer implementation details. "
    "After a case answer or a saved follow-up outcome, decide from the latest "
    "evidence whether a next step is useful. If so, provide one contextual "
    "[QUESTION] block with short choices; otherwise do not add a question. "
    "Do not repeat a completed contact merely because it is a default option."
)
_sessions = {}
_sessions_lock = threading.Lock()
gateway_process = None
gateway_problem = None
CHAT_ACTOR = "مستخدم المحادثة (هوية غير موثقة)"


def dataset_catalog():
    datasets = []
    folder = (ROOT / "data").resolve()
    for path in sorted(folder.glob("*.json")):
        if not path.resolve().is_relative_to(folder):
            continue
        data = read_data(path.relative_to(ROOT).as_posix())
        result = analyze(data, "0001-01-01", "9999-12-31")
        days = sorted(data.get("school_days", {row["date"] for row in data["attendance"]}))
        datasets.append({
            "data_file": path.relative_to(ROOT).as_posix(),
            "students": result["summary"]["students"],
            "period": {"start": days[0], "end": days[-1]} if days else None,
        })
    return datasets


def report(name, start, end):
    raw = read_bytes(name)
    result = analyze(json.loads(raw), start, end, policy())
    return attach_reviews(result, load_latest(REVIEWS, dataset_hash(raw), start, end))


def page_revision(data_file):
    """A cheap marker for student records and the local decision logs."""
    paths = (storage.active_path(data_file), storage.OUTPUT / "actions.jsonl",
             REVIEWS, storage.OUTPUT / "feedback.jsonl")
    return "|".join(
        f"{path.stat().st_mtime_ns:x}:{path.stat().st_size:x}" if path.exists() else "0:0"
        for path in paths
    )


def guided_question(result, answered):
    for case in result["candidates"] + result["unresolved"]:
        for followup in case["previous_followups"]:
            key = "followup:" + followup["id"]
            if "pending" in followup["outcome"].lower() and key not in answered:
                return {"id": key, "student_id": case["student_id"],
                        "text": f"المعلم طلب متابعة {case['alias']} يوم {followup['date']}. هل تمت؟",
                        "options": ["سجّل أنها تمّت واكتب النتيجة", "سجّل أنها لم تتم بعد", "لا أعرف", "تفصيل آخر"]}
    for item in result["summary"]["missing_attendance"]:
        key = "attendance:" + item["student_id"] + ":" + item["date"]
        if key not in answered:
            return {"id": key, "student_id": item["student_id"],
                    "text": f"ما حالة حضور {item['alias']} في {item['date']}؟",
                    "options": ["سجّل حاضر", "سجّل غائب", "ما زال غير معروف", "تفصيل آخر"]}
    return None


def review_opening(result):
    summary = result["summary"]
    flagged = "، ".join(case["alias"] for case in result["candidates"]) or "لا أحد"
    return (f"راجعت {summary['students']} طالبًا للفترة {result['period']['start']} إلى "
            f"{result['period']['end']}. طلاب يحتاجون متابعة: {flagged}. "
            f"هناك {len(summary['missing_attendance'])} سجلات حضور تحتاج استكمالًا.")


def case_by_id(result, data_file, student_id):
    for case in result["candidates"] + result["unresolved"]:
        if case["student_id"] == student_id:
            return case
    data = read_data(data_file)
    person = next((row for row in data["students"] if row["student_id"] == student_id), None)
    if not person:
        return None
    days = {row["date"] for row in result["summary"]["attendance"]["by_date"]}
    records = [row for row in data["attendance"] if row["student_id"] == student_id and row["date"] in days]
    return {"student_id": student_id, "alias": person["alias"], "alerts": [],
            "attendance": {"present": sum(row["status"] == "present" for row in records),
                           "absent": sum(row["status"] == "absent" for row in records),
                           "unrecorded": sum(row["status"] == "unrecorded" for row in records),
                           "missing_record_dates": sorted(days - {row["date"] for row in records})},
            "previous_followups": [row for row in data["followups"]
                                   if row["student_id"] == student_id and row["date"] <= result["period"]["end"]]}


def mentioned_case(message, result, data_file):
    students = read_data(data_file)["students"]
    for person in students:
        if person["student_id"].lower() in message.lower() or person["alias"] in message:
            return case_by_id(result, data_file, person["student_id"])
    first_name_matches = [person for person in students if re.search(
        rf"(?<!\w){re.escape(person['alias'].split()[0])}(?!\w)", message)]
    if len(first_name_matches) == 1:
        return case_by_id(result, data_file, first_name_matches[0]["student_id"])
    if len(first_name_matches) > 1:
        raise DataError("يوجد أكثر من طالب بهذا الاسم؛ اكتب الاسم الكامل")
    return None


def contact_target(message):
    if any(word in message for word in ("ولي", "أبو", "ابو", "أهل", "الاهل", "الوالد")):
        return "guardian"
    if any(word in message for word in ("معلم", "مدرس", "الأستاذ", "الاستاذ")):
        return "teacher"
    if "طالب" in message or "الطالبة" in message:
        return "student"
    return None


def contact_draft(case, recipient):
    name = case["alias"]
    if recipient == "student":
        return f"مرحبًا {name}، نود الاطمئنان على سير دراستك ومناقشة ما قد يساعدك. هل يمكنك التواصل مع المدرسة؟"
    if recipient == "teacher":
        return f"مرحبًا، نرجو مراجعة وضع الطالب {name} وإفادتنا بما لاحظته وما تقترحه للمتابعة. شكرًا لتعاونك."
    return f"مرحبًا، نود متابعة الوضع الدراسي للطالب {name} والاطمئنان عليه. نرجو التواصل مع المدرسة في الوقت المناسب. شكرًا لتعاونكم."


def send_question(case, recipient, draft=None):
    label = {"guardian": "ولي الأمر", "student": "الطالب", "teacher": "المعلم"}[recipient]
    draft = draft or contact_draft(case, recipient)
    return {"id": f"send:{case['student_id']}:{recipient}", "student_id": case["student_id"],
            "recipient_type": recipient, "draft": draft,
            "text": f"رسالة إلى {label} بشأن {case['alias']}:\n{draft}",
            "options": ["إرسال الرسالة", "تعديل الرسالة", "إلغاء"]}


def structured_question(answer):
    match = re.search(r"\[QUESTION\](.*?)\[/QUESTION\]", answer, re.DOTALL)
    if not match:
        return answer, None
    try:
        question = json.loads(match.group(1))
        if (not isinstance(question["text"], str) or
            not isinstance(question["options"], list) or
            not 2 <= len(question["options"]) <= 6 or
            any(not isinstance(option, str) or not option.strip() or len(option) > 100
                for option in question["options"])):
            raise ValueError("invalid question")
        return (answer[:match.start()] + answer[match.end():]).strip(), {
            "text": question["text"][:240], "options": question["options"],
            "action": question.get("action")}
    except (KeyError, ValueError, TypeError):
        return answer, None


def model_question(question, case=None, result=None):
    if not question:
        return None
    if not case and result:
        named = [row for row in result["candidates"] + result["unresolved"]
                 if row["alias"] in question["text"]]
        if len(named) == 1:
            case = named[0]
    action = question.pop("action", None)
    if isinstance(action, dict) and result:
        sid = action.get("student_id")
        if action.get("type") == "resolve_followup" and any(
            f["id"] == action.get("followup_id") and "pending" in f["outcome"].lower()
            for row in result["candidates"] + result["unresolved"]
            if row["student_id"] == sid for f in row["previous_followups"]):
            return {**question, "id": "followup:" + action["followup_id"], "student_id": sid}
        if action.get("type") == "record_attendance" and any(
            row["student_id"] == sid and row["date"] == action.get("date")
            for row in result["summary"]["missing_attendance"]):
            return {**question, "id": f"attendance:{sid}:{action['date']}", "student_id": sid}
    if case and result and "حضور" in question["text"] and any(
        attendance_answer(option) for option in question["options"]):
        missing = [row for row in result["summary"]["missing_attendance"]
                   if row["student_id"] == case["student_id"]]
        if len(missing) == 1:
            return {**question, "id": f"attendance:{case['student_id']}:{missing[0]['date']}",
                    "student_id": case["student_id"]}
    if any(option.startswith("سجّل") for option in question["options"]):
        return None  # Do not show a save button without a validated target record.
    return {**question, "id": "model:" + uuid.uuid4().hex,
            "student_id": case["student_id"] if case else None}


def attendance_answer(message):
    plain = re.sub(r"[\u064b-\u065f\u0670]", "", message.strip())
    if re.fullmatch(r"(?:كان|كانت)?\s*حاضر(?:ا|ة)?", plain):
        return "present"
    if re.fullmatch(r"(?:كان|كانت)?\s*غائب(?:ا|ة)?", plain):
        return "absent"
    return None


def model_response(message, previous=None, context_note=""):
    body = {"model": "hermes-agent", "input": message.strip() + context_note,
            "instructions": INSTRUCTIONS, "store": True}
    if previous:
        body["previous_response_id"] = previous
    response = hermes_request("/v1/responses", body, timeout=120)
    answer = "\n".join(
        content.get("text", "")
        for item in response.get("output", []) if item.get("type") == "message"
        for content in item.get("content", []) if content.get("type") == "output_text"
    ).strip()
    answer, question = structured_question(answer)
    if not answer:
        raise RuntimeError("Hermes لم يُرجع ردًا نصيًا. حاول مرة ثانية.")
    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise RuntimeError("Hermes لم يُرجع معرف المحادثة. حاول مرة ثانية.")
    return answer, question, response_id


def case_evidence(case, data_file):
    if not case:
        return ""
    details = {key: case.get(key) for key in
               ("alias", "attendance", "alerts", "previous_followups")}
    details["recent_actions"] = case_context(data_file, case["student_id"], limit=8)
    return json.dumps(details, ensure_ascii=False)


def hermes_request(path, body=None, timeout=3):
    key = os.environ.get("API_SERVER_KEY", "")
    if not key:
        raise RuntimeError("مفتاح Hermes API غير متاح. شغّل الواجهة بالأمر python -m web_app")
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    request = urllib.request.Request(
        HERMES_URL + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("خادم Hermes ردّ برفض المفتاح؛ قد يكون على المنفذ 8642 خادم آخر بمفتاح مختلف.") from exc
        raise RuntimeError(f"خادم Hermes ردّ بخطأ HTTP {exc.code} على {path}.") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("تعذّر الاتصال بخادم Hermes المحلي على 127.0.0.1:8642؛ راجع مخرجات PowerShell.") from exc


def hermes_status():
    if gateway_process is not None and gateway_process.poll() is not None:
        return {"ready": False, "message": f"توقف Hermes gateway run برمز {gateway_process.returncode}؛ راجع مخرجات PowerShell."}
    if gateway_problem:
        return {"ready": False, "message": gateway_problem}
    if not os.environ.get("API_SERVER_KEY"):
        return {"ready": False, "message": "Hermes غير متصل؛ التحليل والمراجعة متاحان."}
    try:
        payload = hermes_request("/v1/toolsets", timeout=2)
        toolsets = payload.get("data", []) if isinstance(payload, dict) else payload
        ready = isinstance(toolsets, list) and any(
            item.get("name") == "student_followup" and item.get("enabled", True)
            and {"student_followup_info", "student_followup_analyze"} <= set(item.get("tools", []))
            for item in toolsets if isinstance(item, dict)
        )
        return {"ready": ready, "message": "المساعد جاهز" if ready else
                "المساعد غير جاهز حاليًا؛ راجع إعدادات التشغيل."}
    except RuntimeError as exc:
        return {"ready": False, "message": str(exc)}


def chat(message, session_id=None, guided=False, data_file=None, start=None, end=None,
         answer_to=None, save_answer=False):
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise DataError("اكتب رسالة من 1 إلى 4000 حرف")
    context = (data_file, start, end)
    with _sessions_lock:
        known = session_id if isinstance(session_id, str) and session_id in _sessions else None
        session = dict(_sessions[known]) if known else None
    if session and session.get("context") != context:
        raise DataError("تغيّر الملف أو الفترة؛ ابدأ محادثة جديدة للمراجعة")
    choice_case_id = None
    if answer_to and answer_to.startswith("confirm_attendance:"):
        pending = session.get("pending") if session else None
        if not pending or pending.get("id") != answer_to:
            raise DataError("هذا السؤال لم يعد نشطًا؛ اطلب مراجعة الحالة مرة أخرى")
        if message not in pending["options"]:
            raise DataError("اختر تسجيل الحضور أو ترك السجل كما هو")
        result = report(data_file, start, end)
        case = case_by_id(result, data_file, pending["student_id"])
        name = case["alias"]
        day = pending["day"]
        status = pending["status"]
        if message == "نعم، سجّلها":
            missing = any(row["student_id"] == pending["student_id"] and row["date"] == day
                          for row in result["summary"]["missing_attendance"])
            if not missing:
                raise DataError("تغيّر سجل الحضور لهذا اليوم؛ راجعه مرة أخرى قبل التعديل")
            action = execute(data_file, "record_attendance", CHAT_ACTOR, pending["student_id"],
                             day=day, status=status,
                             request_id=uuid.uuid5(uuid.NAMESPACE_URL, known + ":" + answer_to).hex)
            reply = f"سجّلت {name} {'حاضرًا' if status == 'present' else 'غائبًا'} يوم {day}."
        else:
            action = None
            reply = f"تمام، تركت سجل حضور {name} ليوم {day} دون تعديل."
        append_event("dialogue.jsonl", {"session_id": known, "question_id": answer_to,
            "student_id": pending["student_id"], "answer": message,
            "data_file": data_file, "period": {"start": start, "end": end}})
        with _sessions_lock:
            _sessions[known]["pending"] = None
            _sessions[known]["history"] = session.get("history", []) + [
                {"question": pending["text"], "answer": message}]
        return {"answer": reply, "session_id": known, "question": None,
                "changed": bool(action)}
    if answer_to and session and (session.get("pending") or {}).get("id") == answer_to and answer_to.startswith("send:"):
        result = report(data_file, start, end)
        sid = session["pending"]["student_id"]
        case = case_by_id(result, data_file, sid)
        if not case:
            raise DataError("تغيّرت حالة الطالب؛ اطلب مراجعتها مرة أخرى")
        pending = session["pending"]
        changed = False
        if message == "إرسال الرسالة":
            action = execute(data_file, "send_demo", CHAT_ACTOR, sid,
                             recipient_type=pending["recipient_type"],
                             subject=f"متابعة {case['alias']}", message=pending["draft"],
                             request_id=uuid.uuid5(uuid.NAMESPACE_URL, known + ":" + answer_to + ":" + pending["draft"]).hex)
            changed = True
            question = None
            reply = "تم الإرسال."
        elif message == "إلغاء":
            question, reply = None, "ألغيت الرسالة ولم أغيّر السجل."
        elif save_answer is True and message.strip():
            question = send_question(case, pending["recipient_type"], message.strip())
            reply = "حدّثت صيغة الرسالة. راجعها ثم اختر إرسال."
        else:
            raise DataError("اختر إرسال الرسالة أو تعديلها أو إلغاءها")
        with _sessions_lock:
            _sessions[known]["pending"] = question
        return {"answer": reply, "session_id": known, "question": question, "changed": changed}
    if answer_to and answer_to.startswith("model:"):
        pending = session.get("pending") if session else None
        if not pending or pending.get("id") != answer_to:
            raise DataError("هذا السؤال لم يعد نشطًا؛ اطلب مراجعة الحالة مرة أخرى")
        if message.strip() not in pending["options"] and not save_answer:
            raise DataError("اختر خطوة من الخيارات المعروضة")
        choice_case_id = pending.get("student_id")
        session["history"] = session.get("history", []) + [
            {"question": pending["text"], "answer": message.strip()}]
        session["pending"] = None
        with _sessions_lock:
            _sessions[known]["pending"] = None
            _sessions[known]["history"] = session["history"]
        answer_to = None
    if guided and not session:
        result = report(data_file, start, end)
        known = uuid.uuid4().hex
        question = guided_question(result, [])
        with _sessions_lock:
            if len(_sessions) >= 100:
                _sessions.pop(next(iter(_sessions)))
            _sessions[known] = {"context": context, "response_id": None,
                                "answered": [], "history": [], "pending": question}
        return {"answer": review_opening(result), "session_id": known, "question": question}
    if answer_to:
        pending = session.get("pending") if session else None
        if not pending or answer_to != pending["id"]:
            raise DataError("هذا السؤال لم يعد نشطًا؛ ابدأ مراجعة جديدة")
        result = report(data_file, start, end)
        if answer_to.startswith("attendance:") and message in pending.get("options", []):
            status = attendance_answer(message)
            if status:
                day = answer_to.rsplit(":", 1)[1]
                case = case_by_id(result, data_file, pending["student_id"])
                if not any(row["student_id"] == pending["student_id"] and row["date"] == day
                           for row in result["summary"]["missing_attendance"]):
                    raise DataError("تغيّر سجل الحضور لهذا اليوم؛ راجعه مرة أخرى")
                question = {"id": f"confirm_attendance:{pending['student_id']}:{day}:{status}",
                            "student_id": pending["student_id"], "day": day, "status": status,
                            "text": f"هل تريد تسجيل {case['alias']} {'حاضرًا' if status == 'present' else 'غائبًا'} يوم {day} في السجل؟",
                            "options": ["نعم، سجّلها", "لا، اترك السجل كما هو"]}
                append_event("dialogue.jsonl", {"session_id": known, "question_id": answer_to,
                    "student_id": pending["student_id"], "answer": message.strip(),
                    "data_file": data_file, "period": {"start": start, "end": end}})
                with _sessions_lock:
                    _sessions[known]["pending"] = question
                return {"answer": "فهمت إجابتك، ولسه ما عدّلت سجل الحضور.",
                        "session_id": known, "question": question, "changed": False}
        action = None
        request_id = uuid.uuid5(uuid.NAMESPACE_URL, known + ":" + answer_to).hex
        if answer_to.startswith("attendance:") and message in ("سجّل حاضر", "سجّل غائب"):
            action = execute(data_file, "record_attendance", CHAT_ACTOR, pending["student_id"],
                day=answer_to.rsplit(":", 1)[1],
                status="present" if message == "سجّل حاضر" else "absent", request_id=request_id)
        elif answer_to.startswith("followup:") and message == "سجّل أنها لم تتم بعد":
            action = execute(data_file, "resolve_followup", CHAT_ACTOR, pending["student_id"],
                followup_id=answer_to.split(":", 1)[1], outcome="لم تتم بعد", request_id=request_id)
        elif answer_to.startswith("followup:") and save_answer is True:
            action = execute(data_file, "resolve_followup", CHAT_ACTOR, pending["student_id"],
                followup_id=answer_to.split(":", 1)[1],
                outcome="تمّت المتابعة: " + message.strip(), request_id=request_id)
        append_event("dialogue.jsonl", {"session_id": known, "question_id": answer_to,
            "student_id": pending["student_id"], "answer": message.strip(),
            "data_file": data_file, "period": {"start": start, "end": end}})
        answered = session["answered"] + [answer_to]
        history = session["history"] + [{"question": pending["text"], "answer": message.strip()}]
        current_case = case_by_id(result, data_file, pending["student_id"])
        if action:
            result = report(data_file, start, end)
            current_case = case_by_id(result, data_file, pending["student_id"])
            detail = action["details"]
            if action["action"] == "record_attendance":
                reply = f"سجّلت حضور {current_case['alias'] if current_case else pending['student_id']} في {detail['day']} كـ{'حاضر' if detail['after'] == 'present' else 'غائب'}."
            else:
                reply = f"حدّثت متابعة {current_case['alias'] if current_case else pending['student_id']} إلى: {detail['after']}."
        else:
            reply = "دوّنت إجابتك في المراجعة. لم أعدّل سجل الطالب."
        question = guided_question(result, answered) if guided else None
        response_id = session.get("response_id")
        if not guided and current_case and os.environ.get("API_SERVER_KEY"):
            update_note = ("The requested record change was saved. " if action else
                           "The user answered a question; no student record was changed. "
                           "An unrecorded attendance day is still unknown in the register. ")
            note = ("\n" + update_note +
                    "This is the current, authoritative case state: "
                    + case_evidence(current_case, data_file)
                    + "\nDecide whether a DIFFERENT useful step or missing fact now needs attention. "
                    "A completed guardian follow-up is not a reason to propose the same contact again. "
                    "Respond briefly in Arabic. Add a [QUESTION] block only if a concrete next choice helps; "
                    "otherwise say no further step is needed now. Do not execute another action.")
            try:
                advice, suggested, response_id = model_response(
                    f"نتيجة المتابعة الجديدة: {message.strip()}", response_id, note)
                reply += " " + advice
                question = model_question(suggested, current_case, result)
            except RuntimeError:
                pass  # The saved action stands even if the conversational suggestion is unavailable.
        if not question:
            if guided:
                reply += " انتهت الأسئلة الحالية؛ يمكنك طلب إجراء أو تقرير من المحادثة."
        with _sessions_lock:
            _sessions[known].update(answered=answered, history=history, pending=question,
                                    response_id=response_id)
        return {"answer": reply, "session_id": known, "question": question, "changed": bool(action)}

    case_result = report(data_file, start, end) if all(context) else None
    case = mentioned_case(message, case_result, data_file) if case_result else None
    if not case and session and case_result:
        sid = choice_case_id or (session.get("pending") or {}).get("student_id")
        case = case_by_id(case_result, data_file, sid)
    recipient = contact_target(message) if case else None
    if case and recipient and any(term in message for term in ("ابعت", "ابعث", "أرسل", "ارسل", "رسالة", "مراسلة", "تواصل")):
        question = send_question(case, recipient)
        if not known:
            known = uuid.uuid4().hex
        with _sessions_lock:
            _sessions[known] = {"context": context, "response_id": session.get("response_id") if session else None,
                                "answered": session.get("answered", []) if session else [],
                                "history": session.get("history", []) if session else [],
                                "pending": question}
        return {"answer": "جهّزت الرسالة للمراجعة. اختر إرسالها أو تعديلها.",
                "session_id": known, "question": question}
    status = hermes_status()
    if not status["ready"]:
        raise RuntimeError(status["message"])
    previous = session.get("response_id") if session else None
    pending = session.get("pending") if session else None
    context_note = ""
    if case_result:
        context_note = f"\nDataset: {data_file}; dates: {start} to {end}. "
        if case:
            context_note += "Current case state: " + case_evidence(case, data_file) + ". "
        if session and session.get("history"):
            context_note += "Review answers so far: " + json.dumps(session["history"][-8:], ensure_ascii=False) + ". "
        if pending:
            context_note += f"The open UI question is '{pending['text']}', but this message is a separate question or request, not an answer to it. "
        context_note += ("Respond to the latest request briefly. Decide whether a relevant "
                         "next question is useful; do not default to a contact menu or repeat "
                         "a completed follow-up. Give no choices if there is nothing to decide.")
    answer, suggested, response_id = model_response(message, previous, context_note)
    question = model_question(suggested, case, case_result)
    with _sessions_lock:
        if not known:
            known = uuid.uuid4().hex
        if len(_sessions) >= 100:
            _sessions.pop(next(iter(_sessions)))
        _sessions[known] = {"context": context, "response_id": response_id,
                            "answered": session.get("answered", []) if session else [],
                            "history": session.get("history", []) if session else [], "pending": question}
    return {"answer": answer, "session_id": known, "question": question}


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _file(self, path, kind):
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        route = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(route.query)
        try:
            if route.path == "/":
                return self._file(STATIC / "index.html", "text/html; charset=utf-8")
            if route.path == "/static/app.css":
                return self._file(STATIC / "app.css", "text/css; charset=utf-8")
            if route.path == "/static/app.js":
                return self._file(STATIC / "app.js", "text/javascript; charset=utf-8")
            if route.path == "/api/datasets":
                return self._json(200, {"datasets": dataset_catalog()})
            if route.path == "/api/students":
                students = read_data(query.get("data_file", [""])[0])["students"]
                return self._json(200, {"students": [{"student_id": row["student_id"],
                                                       "name": row["alias"]} for row in students]})
            if route.path == "/api/status":
                return self._json(200, hermes_status())
            if route.path == "/api/revision":
                return self._json(200, {"revision": page_revision(query.get("data_file", [""])[0])})
            if route.path == "/api/context":
                return self._json(200, {"events": case_context(query.get("data_file", [""])[0],
                    query.get("student_id", [None])[0])})
            if route.path == "/api/analysis":
                def required(key):
                    value = query.get(key, [""])[0]
                    if not value:
                        raise DataError("حدد الملف وتاريخ البداية والنهاية")
                    return value
                name = required("data_file")
                result = report(name, required("start"), required("end"))
                result["revision"] = page_revision(name)
                return self._json(200, result)
            self._json(404, {"error": "العنوان غير موجود"})
        except (DataError, ValueError, OSError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self):
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            return self._json(403, {"error": "طلب من مصدر غير مسموح"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get_content_type() != "application/json":
                raise DataError("أرسل JSON بحجم لا يتجاوز 64 كيلوبايت")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise DataError("صيغة الطلب غير صحيحة")
            if self.path == "/api/reviews":
                raw = read_bytes(body.get("data_file"))
                row = record_review(raw, body.get("start"), body.get("end"),
                                    body.get("student_id"), body.get("decision"),
                                    body.get("note"), REVIEWS, policy())
                return self._json(200, {"review": row})
            if self.path == "/api/chat":
                name = body.get("data_file")
                before = page_revision(name) if name else None
                result = chat(body.get("message"), body.get("session_id"),
                    body.get("guided", False), name, body.get("start"),
                    body.get("end"), body.get("answer_to"), body.get("save_answer", False))
                after = page_revision(name) if name else None
                result["changed"] = bool(result.get("changed")) or before != after
                return self._json(200, result)
            if self.path == "/api/report":
                item = create_report(read_data(body.get("data_file")), body.get("start"),
                                     body.get("end"), body.get("purpose"), policy())
                append_event("reports.jsonl", {"data_file": body.get("data_file"), "report": item})
                return self._json(200, {"report": item})
            if self.path == "/api/actions":
                return self._json(200, {"action": execute(**body)})
            if self.path == "/api/feedback":
                name = body.get("data_file")
                result = record_feedback(name, read_data(name), body.get("start"), body.get("end"),
                                         body.get("student_id"), body.get("label"), body.get("note"))
                return self._json(200, result)
            self._json(404, {"error": "العنوان غير موجود"})
        except (DataError, ValueError, TypeError, KeyError, OSError) as exc:
            self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(503, {"error": str(exc)})


def serve(port=8000):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Student Follow-up UI: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
