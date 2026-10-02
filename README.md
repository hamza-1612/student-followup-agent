# Student Follow-up Agent — runnable first version

Standalone prototype for the Agents at Work hackathon. It reviews **fictional**
attendance, assessment, and follow-up data. `BRIEF.md` records project decisions;
`AGENT.md` records intended agent behavior. No Academix connection is needed.

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
For 2026-09-07 through 2026-09-09, the actual present counts are 30, 28,
and 30 by day; 30 distinct students were present at least once, and 28 were
present on all three dates. There are 90 attendance **records** in that period,
but two of those records are marked `absent`.
S-004's unrecorded attendance is not counted as absence. Every candidate has
observed facts, a source, and follow-ups recorded through the period end.
The fixture uses repeated baseline scores across students by design; equal
scores between different students do not indicate duplicate records.

## Record a human review decision

After looking at the evidence, the reviewer can record one decision, for example:

```powershell
python -m student_followup.reviews --data data/fictional_school.json --start 2026-09-07 --end 2026-09-11 --student-id S-002 --decision verify_data --note "Check with teacher before contacting family"
```

Choices: `follow_up_approved` (approve a proposed next step), `verify_data`
(request verification), and `no_action` (close this review case). This saves an
append-only entry to `outputs/reviews.jsonl`; the folder is ignored by Git.
Running the analyzer again shows the latest decision for that exact input file
and period. Different data or dates will not reuse a stale decision. This
records the **reviewer's decision**, never an executed follow-up. It does not
send a message or modify the input file. Use fictional notes for the demo.

## Run with Hermes (once installed and configured)

Hermes supports project-local plugins, but requires two explicit opt-ins:
discover project plugins and allow the plugin by its manifest name. In some
Hermes releases, `hermes plugins list` and `hermes plugins enable` do not scan
project-local plugins, even though the agent loader does. In PowerShell, while
in this folder, preserve existing enabled plugins and add this one through the
configuration command:

```powershell
$env:HERMES_ENABLE_PROJECT_PLUGINS = "true"
$enabledJson = hermes config get plugins.enabled --json 2>$null
$enabled = if ($LASTEXITCODE -eq 0) { @($enabledJson | ConvertFrom-Json) } else { @() }
$enabled = @($enabled | Where-Object { $_ })
if ("student-followup" -notin $enabled) { $enabled += "student-followup" }
hermes config set plugins.enabled (ConvertTo-Json -InputObject $enabled -Compress)
hermes chat --toolsets student_followup -q "Use student_followup_analyze on data/fictional_school.json for 2026-09-07 through 2026-09-11. Explain the recorded evidence, distinguish missing attendance, check previous follow-ups, and propose a human-reviewed next step for each case."
```

To watch the agent ask the reviewer a question in an interactive chat, start
a **new** session from this folder (with the same plugin opt-ins):

```powershell
& "$env:LOCALAPPDATA\hermes\bin\hermes.exe" chat --toolsets student_followup -q "Start an interactive student follow-up review. Discover the existing dataset and its whole attendance period, analyze it, summarize the evidence, then ask me one specific question needed for a human decision. Wait for my answer."
```

The expected first question concerns the pending F-001 teacher check-in for
S-002. You can answer in the chat; the conversation does not save a reviewer
decision or send a message. Use the review CLI above to persist a decision.

## Local browser interface (Windows)

The optional Arabic dashboard shows the analysis, daily attendance, evidence,
previous follow-ups, and a human review form. It also has a Hermes chat panel.
No extra Python packages or cloud hosting are needed. From PowerShell in this
repository, after configuring Hermes and enabling the project plugin as above:

```powershell
git pull --ff-only
python -m web_app
```

Use `py -m web_app` if Python is exposed as `py`. Open
`http://127.0.0.1:8000` in your browser. This command starts a local Hermes
gateway with a temporary API key when it finds Hermes, and stops that child
process when you press Ctrl+C. The key stays in the local processes and never
goes to the browser. The interface and Hermes API bind to `127.0.0.1` only.
If Hermes is unavailable or its project plugin is not enabled, the dashboard
and review form still work, while the chat panel explains the connection issue.
To intentionally use only the dashboard, run `python -m web_app --no-hermes`.
If another Hermes API gateway is already using port 8642, close it before
starting the one-command interface, or provide its matching `API_SERVER_KEY`
as an environment variable. No external messages or school records are edited.

The interface is a small Python standard-library HTTP server and static
HTML/CSS/JavaScript, with a server-side bridge to Hermes' local Responses API.
It uses the same deterministic analyzer and reviewer log as the CLI. Chat
history for the current browser session is kept in memory by the local bridge;
the reviewer log remains in the ignored `outputs/reviews.jsonl` file. The
included data are fictional. This is a local demo, without user accounts or
shared-school deployment.

Hermes selects its configured model/provider; this project does not choose one
or store credentials. The plugin registers two **read-only** tools:
`student_followup_info` finds available JSON datasets, counts students, and
shows recorded attendance date ranges without requiring a period;
`student_followup_analyze` applies the review rules to a chosen period. JSON
inputs are confined to `data/`. The analysis uses the same tested Python
module as the CLI. For "the existing file" and "the whole period," Hermes
should discover the dataset and use its full recorded attendance date range.
`AGENTS.md` instructs Hermes to follow `BRIEF.md` and
`AGENT.md`, including the school-only conversation scope. Start a fresh chat
after pulling instruction changes; an existing chat may keep its old context.
For example, a request for a cooking recipe should receive a brief school-scope
reply without a recipe. This is a model instruction, not a guaranteed hard
filter on every possible prompt; an enforced boundary would require a separate
application gate around Hermes. A live Hermes run on Windows with the Nous
`space-bunny-alpha` model successfully invoked the tool and reported three
candidates and one unresolved case on the included fictional fixture. That run
does not measure educational effectiveness or time savings.

If Hermes says `Unknown toolsets: student_followup` or displays `0 tools`,
check that it was launched from this folder, the environment variable was set
in the same PowerShell session, and `hermes config get plugins.enabled --json`
includes `student-followup`. `plugins list` may omit project plugins in affected
Hermes releases. If `hermes` is missing from PATH on Windows after installation,
open a new PowerShell window or invoke
`& "$env:LOCALAPPDATA\hermes\bin\hermes.exe"` in place of `hermes`.
Do not enable project plugins for untrusted repositories.

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
reported separately. For this demo, dates present in any attendance row define
the shared school-day roster; a missing row for one student on one of those
dates is reported as missing information. The analyzer does not infer additional
school days outside that roster. A student with no attendance rows in the
selected period requires verification.

`summary.data_quality_issues` counts cases with attendance gaps (explicit
`unrecorded` or an omitted row), and `summary.data_quality_details` lists each
affected student and the dates needing verification. It is not a count of
duplicate assessments or proof that equal scores across students are incorrect.
`summary.attendance.by_date` separates `present`, `absent`, `unrecorded`, and
missing rows for each supplied date in the selected period. Its distinct
student totals distinguish presence at least once from presence on every
recorded school day. `attendance_records_in_period` counts rows, not students
who attended.

The approved **demo review thresholds** are two recorded absences within any
five consecutive supplied school dates, or a drop of at least 15 percentage
points from the preceding dated assessment in the same subject. Attendance
dates in the input define school days for the demo; the code does not assume a
weekday calendar. Fewer than five supplied dates cannot trigger the absence
rule. The score rule compares percentages before rounding. A case with both
signals has `high` priority, a case with one has `standard` priority; higher
priority appears first. These are review priorities, not educational diagnoses.
Recorded absence and a lower score below the thresholds are descriptive facts,
not alerts. Missing attendance remains a verification case and is never counted
as absence; a flagged case can also carry missing-information warnings.

The agent should ask for any missing fact necessary to decide the next action,
then present a draft for human approval. Review decisions can be logged locally;
neither analysis nor a review decision sends messages or alters school records.

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

Implemented: JSON validation, demo alert rules and priority order, prior-follow-up lookup,
local reviewer decision log, read-only Hermes plugin, fictional fixture, local
browser interface, executable tests, and a live Hermes CLI run with the project
plugin. Open: live browser-to-Hermes verification on Windows, measured time and
tokens, reviewer decisions for the demonstration, and video/slides. No real student data or secrets should
be committed. `.gitignore` excludes local credentials and private logs.
