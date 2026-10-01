"""Project-local Hermes tool; analysis stays in the testable core."""

import json
from pathlib import Path


def register(ctx):
    schema = {
        "name": "student_followup_analyze",
        "description": "Validate fictional school JSON and return recorded absences, lower comparable scores, missing attendance and prior follow-ups. Read-only. No alert thresholds or messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_file": {"type": "string", "description": "Path to a JSON file inside this project's data directory"},
                "period_start": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
                "period_end": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
            },
            "required": ["data_file", "period_start", "period_end"],
        },
    }

    def handler(params, **kwargs):
        del kwargs
        try:
            from student_followup import DataError, analyze

            project = Path(__file__).resolve().parents[3]
            data_dir = (project / "data").resolve()
            target = (project / params["data_file"]).resolve()
            if not target.is_relative_to(data_dir) or target.suffix.lower() != ".json":
                raise DataError("data_file must be a JSON file inside the project data directory")
            payload = json.loads(target.read_text(encoding="utf-8"))
            result = analyze(payload, params["period_start"], params["period_end"])
            return json.dumps({"success": True, "result": result}, ensure_ascii=False, allow_nan=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    ctx.register_tool(name="student_followup_analyze", toolset="student_followup", schema=schema, handler=handler)
