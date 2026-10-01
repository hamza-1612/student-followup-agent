# Student Follow-up Agent — runnable first version

Standalone prototype for the Agents at Work hackathon. It reviews **fictional**
attendance, assessment, and follow-up data. `BRIEF.md` records project decisions;
`AGENT.md` records intended agent behavior. No Academix connection or UI is needed.

## Run the deterministic analyzer (Windows PowerShell)

From this folder with Python 3.10 or newer installed:

```powershell
python -m student_followup --data data/fictional_school.json --start 2026-09-07 --end 2026-09-11
python -m unittest discover -s tests -v
```

Use `py` in place of `python` if that is how Python is installed. The analyzer
needs no Python packages and no API key. On macOS/Linux, use `python3`.
`python scripts/generate_demo.py` regenerates the same fictional input.
Errors appear on stderr with exit code 2. The default output is a concise
Arabic report listing **all** candidates and unresolved cases. For complete
machine-readable output, add `--json` to the analysis command.

Expected counts for the included sample: 30 students; 150 dated attendance
records; 3 review candidates (S-002, S-003, S-006); one unresolved case
(S-004). These are fixture checks, **not educational effectiveness claims**.
S-004's unrecorded attendance is not counted as absence. Every candidate has
observed facts, a source, and follow-ups recorded through the period end.

## Run with Hermes (once installed and configured)

Hermes supports project-local plugins, but requires an explicit trust opt-in.
In PowerShell, while in this folder:

```powershell
$env:HERMES_ENABLE_PROJECT_PLUGINS = "true"
hermes chat --toolsets student_followup -q "Use student_followup_analyze on data/fictional_school.json for 2026-09-07 through 2026-09-11. Explain the recorded evidence, distinguish missing attendance, check previous follow-ups, and propose a human-reviewed next step for each case."
```

Hermes selects its configured model/provider; this project does not choose one
or store credentials. The plugin registers one **read-only** tool, and permits
JSON inputs only inside `data/`. It performs analysis in the same tested Python
module as the CLI. `AGENTS.md` instructs Hermes to follow `BRIEF.md` and
`AGENT.md`. Tool registration and the handler were tested with a simulated
Hermes context; a live Hermes/model run has **not** yet been verified here.

If the local plugin is not loaded, check that Hermes was launched from this
folder and that the environment variable was set in the same PowerShell
session. Do not enable project plugins for untrusted repositories.

## Input JSON contract

All four top-level arrays are required:

| Array | Required fields | Meaning |
| --- | --- | --- |
| `students` | `student_id`, `alias` | Unique ID and fictional display name. |
| `attendance` | `student_id`, `date`, `status` | One row per student and date; `status` is `present`, `absent`, or `unrecorded`. |
| `assessments` | `student_id`, `subject`, `date`, `score`, `max_score` | Raw score and positive maximum; compare percentages within the same subject to the preceding dated assessment. |
| `followups` | `id`, `student_id`, `date`, `topic`, `outcome` | Previous action/outcome; IDs unique. An empty list means none supplied. |

Dates use `YYYY-MM-DD`. `--start` and `--end` are inclusive. All referenced
students must exist. Duplicate/conflicting attendance, duplicate assessments,
invalid dates, and bad scores stop analysis instead of silently repairing data.
Absence of a row is **not** proof of absence; a supplied `unrecorded` row is
reported separately. A student with no attendance rows in the selected period
requires verification; the analyzer does not infer every expected school day.

An observed recorded absence or a lower comparable score creates a **review
candidate**. This is a deliberately broad descriptive selection, not a risk
level, alert threshold, or approved ordering. `priority` remains `needs_review`.
The agent should ask for any missing fact necessary to decide the next action,
then present a draft for human approval. The current tool does not persist
review decisions, send messages, or alter school records.

## Demo and measurement

1. Show the input for S-002 (recorded absence and a prior check-in), S-003
   (lower Mathematics score), and S-004 (`unrecorded`).
2. Run the CLI, then use Hermes to explain the evidence and propose a draft
   follow-up. The human chooses whether any proposed action is appropriate.
3. For a time claim, ask an administrator to review the **same frozen input**
   manually and with the agent. Record start/end times, review time, corrections,
   and the dataset SHA-256 in `measurement/template.csv` or a copy. Count model
   calls/tokens from provider or Hermes usage logs if available. Report actual
   values only; blank fields mean not measured. Repeat trials if making a
   general performance claim. See `measurement/README.md`.

## Status and next decisions

Implemented: JSON validation, descriptive analysis, prior-follow-up lookup,
read-only Hermes plugin, fictional fixture, and executable tests. Open:
approved alert rules/priorities, model/provider, reviewer feedback storage,
and live Hermes integration verification. No real student data or secrets should
be committed. `.gitignore` excludes local credentials and private logs.
