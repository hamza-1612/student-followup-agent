"""Local demo data overlay and append-only event log.

Source fixtures remain unchanged. Local edits live under ignored outputs/.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .core import DataError, analyze


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "outputs"
_lock = threading.RLock()


def dataset_path(name):
    if not isinstance(name, str) or not name.startswith("data/"):
        raise DataError("choose a JSON file inside data/")
    path = (ROOT / name).resolve()
    if not path.is_relative_to(DATA.resolve()) or path.parent != DATA.resolve() or path.suffix != ".json":
        raise DataError("choose a JSON file inside data/")
    if not path.is_file():
        raise DataError("dataset does not exist")
    return path


def active_path(name):
    source = dataset_path(name)
    overlay = OUTPUT / "datasets" / source.name
    return overlay if overlay.exists() else source


def read_data(name):
    source = dataset_path(name)
    overlay = OUTPUT / "datasets" / source.name
    if not overlay.exists():
        return json.loads(source.read_text(encoding="utf-8"))
    local = json.loads(overlay.read_text(encoding="utf-8"))
    fixture = json.loads(source.read_text(encoding="utf-8"))
    local_ids = {row["student_id"] for row in local["students"]}
    fixture_ids = {row["student_id"] for row in fixture["students"]}
    if local_ids == fixture_ids:
        return local
    if not local_ids < fixture_ids:
        raise DataError("local dataset differs from the demo roster; review it before upgrading")
    # Preserve the operator's edits while importing new fictional students.
    local_people = {row["student_id"]: row for row in local["students"]}
    fixture["students"] = [{**row, **{key: value for key, value in local_people.get(row["student_id"], {}).items()
                                   if key not in ("alias", "student_id")}} for row in fixture["students"]]
    for section, key_fields in (("attendance", ("student_id", "date")),
                                ("assessments", ("student_id", "subject", "date")),
                                ("followups", ("id",))):
        by_key = {tuple(row[key] for key in key_fields): row for row in fixture[section]}
        by_key.update({tuple(row[key] for key in key_fields): row for row in local[section]})
        fixture[section] = list(by_key.values())
    fixture["school_days"] = sorted(set(fixture.get("school_days", [])) | set(local.get("school_days", [])))
    save_data(name, fixture)
    return fixture


def read_bytes(name):
    read_data(name)  # Migrates a prior demo overlay before computing its hash.
    return active_path(name).read_bytes()


def save_data(name, data):
    # Validate the complete document before replacing the active copy.
    analyze(data, "0001-01-01", "9999-12-31")
    path = OUTPUT / "datasets" / dataset_path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def append_event(filename, entry):
    path = OUTPUT / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), **entry}
    with _lock, path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return row


def events(filename):
    path = OUTPUT / filename
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
