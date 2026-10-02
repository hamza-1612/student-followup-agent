"""Project-local Hermes tool; analysis stays in the testable core."""

import json
import sys
from pathlib import Path


def register(ctx):
    schema = {
        "name": "student_followup_analyze",
        "description": "Validate fictional school JSON and apply approved demo review alerts: 2 recorded absences in 5 supplied school dates or a 15-point score drop in the same subject. Missing attendance is separate. Read-only; no messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_file": {"type": "string", "description": "Path to a JSON file inside this project's data directory"},
                "period_start": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
                "period_end": {"type": "string", "description": "Inclusive YYYY-MM-DD"},
                "reviews_file": {"type": "string", "description": "Optional reviewer JSONL file inside outputs/; defaults to outputs/reviews.jsonl if present"},
            },
            "required": ["data_file", "period_start", "period_end"],
        },
    }

    def handler(params, **kwargs):
        del kwargs
        try:
            project = Path(__file__).resolve().parents[3]
            # Hermes' Windows console launcher can omit the working directory
            # from sys.path. Import this project's package from the plugin's
            # own location instead of relying on the launcher environment.
            if str(project) not in sys.path:
                sys.path.insert(0, str(project))
            from student_followup import DataError, analyze
            from student_followup.reviews import attach_reviews, dataset_hash, load_latest

            data_dir = (project / "data").resolve()
            target = (project / params["data_file"]).resolve()
            if not target.is_relative_to(data_dir) or target.suffix.lower() != ".json":
                raise DataError("data_file must be a JSON file inside the project data directory")
            data_bytes = target.read_bytes()
            payload = json.loads(data_bytes)
            result = analyze(payload, params["period_start"], params["period_end"])
            reviews_dir = (project / "outputs").resolve()
            reviews = (project / params.get("reviews_file", "outputs/reviews.jsonl")).resolve()
            if not reviews.is_relative_to(reviews_dir) or reviews.suffix.lower() != ".jsonl":
                raise DataError("reviews_file must be a JSONL file inside outputs/")
            attach_reviews(result, load_latest(reviews, dataset_hash(data_bytes),
                                               params["period_start"], params["period_end"]))
            return json.dumps({"success": True, "result": result}, ensure_ascii=False, allow_nan=False)
        except (KeyError, ValueError, OSError) as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    ctx.register_tool(name="student_followup_analyze", toolset="student_followup", schema=schema, handler=handler)
