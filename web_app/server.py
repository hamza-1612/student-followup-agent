"""Small localhost-only HTTP bridge for the demo UI and Hermes API server."""

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from student_followup import DataError, analyze
from student_followup.reviews import attach_reviews, dataset_hash, load_latest, record_review


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
REVIEWS = ROOT / "outputs" / "reviews.jsonl"
HERMES_URL = "http://127.0.0.1:8642"
INSTRUCTIONS = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + (
    "\nThis local interface only handles the fictional school dataset. "
    "Use student_followup_info and student_followup_analyze for dataset facts. "
    "Do not use terminal, file editing, web, or unrelated tools. "
    "A chat answer does not save a reviewer decision."
)
_sessions = {}
_sessions_lock = threading.Lock()


def dataset_path(name):
    if not isinstance(name, str) or not name.startswith("data/"):
        raise DataError("اختر ملف JSON من مجلد data")
    target = (ROOT / name).resolve()
    folder = (ROOT / "data").resolve()
    if not target.is_relative_to(folder) or target.suffix.lower() != ".json":
        raise DataError("اختر ملف JSON من مجلد data")
    return target


def dataset_catalog():
    datasets = []
    folder = (ROOT / "data").resolve()
    for path in sorted(folder.glob("*.json")):
        if not path.resolve().is_relative_to(folder):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        result = analyze(data, "0001-01-01", "9999-12-31")
        days = result["summary"]["attendance"]["by_date"]
        datasets.append({
            "data_file": path.relative_to(ROOT).as_posix(),
            "students": result["summary"]["students"],
            "period": {"start": days[0]["date"], "end": days[-1]["date"]} if days else None,
        })
    return datasets


def report(name, start, end):
    path = dataset_path(name)
    raw = path.read_bytes()
    result = analyze(json.loads(raw), start, end)
    return attach_reviews(result, load_latest(REVIEWS, dataset_hash(raw), start, end))


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
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("تعذّر الاتصال بخادم Hermes المحلي. تأكد أنه يعمل وأن الإضافة مفعّلة.") from exc


def hermes_status():
    if not os.environ.get("API_SERVER_KEY"):
        return {"ready": False, "message": "Hermes غير متصل؛ التحليل والمراجعة متاحان."}
    try:
        toolsets = hermes_request("/v1/toolsets", timeout=2)
        ready = isinstance(toolsets, list) and any(
            item.get("name") == "student_followup" and item.get("enabled", True)
            and {"student_followup_info", "student_followup_analyze"} <= set(item.get("tools", []))
            for item in toolsets if isinstance(item, dict)
        )
        return {"ready": ready, "message": "Hermes جاهز للمحادثة" if ready else
                "Hermes متصل، لكن أدوات متابعة الطلاب غير مفعّلة. فعّل student-followup وأعد التشغيل."}
    except RuntimeError:
        return {"ready": False, "message": "Hermes غير متصل؛ التحليل والمراجعة متاحان."}


def chat(message, session_id=None):
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise DataError("اكتب رسالة من 1 إلى 4000 حرف")
    status = hermes_status()
    if not status["ready"]:
        raise RuntimeError(status["message"])
    with _sessions_lock:
        known = session_id if isinstance(session_id, str) and session_id in _sessions else None
        previous = _sessions.get(known) if known else None
    body = {"model": "hermes-agent", "input": message.strip(), "instructions": INSTRUCTIONS, "store": True}
    if previous:
        body["previous_response_id"] = previous
    response = hermes_request("/v1/responses", body, timeout=120)
    answer = "\n".join(
        content.get("text", "")
        for item in response.get("output", []) if item.get("type") == "message"
        for content in item.get("content", []) if content.get("type") == "output_text"
    ).strip()
    if not answer:
        raise RuntimeError("Hermes لم يُرجع ردًا نصيًا. حاول مرة ثانية.")
    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise RuntimeError("Hermes لم يُرجع معرف المحادثة. حاول مرة ثانية.")
    with _sessions_lock:
        if not known:
            known = uuid.uuid4().hex
        if len(_sessions) >= 100:
            _sessions.pop(next(iter(_sessions)))
        _sessions[known] = response_id
    return {"answer": answer, "session_id": known}


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
            if route.path == "/api/status":
                return self._json(200, hermes_status())
            if route.path == "/api/analysis":
                def required(key):
                    value = query.get(key, [""])[0]
                    if not value:
                        raise DataError("حدد الملف وتاريخ البداية والنهاية")
                    return value
                return self._json(200, report(required("data_file"), required("start"), required("end")))
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
                path = dataset_path(body.get("data_file"))
                row = record_review(path.read_bytes(), body.get("start"), body.get("end"),
                                    body.get("student_id"), body.get("decision"),
                                    body.get("note"), REVIEWS)
                return self._json(200, {"review": row})
            if self.path == "/api/chat":
                return self._json(200, chat(body.get("message"), body.get("session_id")))
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
