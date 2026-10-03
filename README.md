# Student Follow-up Agent — runnable first version

Standalone prototype for the Agents at Work hackathon. It reviews **fictional**
attendance, assessment, and follow-up data, asks guided questions, and supports
audited local actions. `BRIEF.md` records project decisions;
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

Expected counts for the included sample: 50 fictional students with Arabic
names; 250 dated attendance records; 7 review candidates and 10 unresolved
cases (11 students have an unrecorded attendance day, including one candidate). These are fixture checks, **not educational effectiveness claims**.
For 2026-09-07 through 2026-09-09, the actual present counts are 48, 43,
and 48 by day. There are 150 attendance **records** in that period;
five are `absent` and six are `unrecorded`.
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
`http://127.0.0.1:8000` in your browser. On the first run, this command uses
`hermes config set` to save a random `API_SERVER_KEY` and turn on
`API_SERVER_ENABLED` in the local Hermes profile. Later runs reuse that key, so
the profile-scoped gateway can read it. It starts a local gateway via
`hermes gateway run` when port 8642 is free, and stops that child process when
you press Ctrl+C. The key stays on the local machine and never goes to the
browser. The interface and Hermes API bind to `127.0.0.1` only.
If Hermes is unavailable or its project plugin is not enabled, the dashboard
and review form still work, while the chat panel explains the connection issue.
If the chat remains offline, read the status pill and the PowerShell output;
an early gateway exit code or an occupied port is reported explicitly. Wait
for gateway startup before trying the chat.
To intentionally use only the dashboard, run `python -m web_app --no-hermes`.
If Hermes already serves the API on port 8642, the interface uses the profile's
configured key to connect. The included dataset has no recipient email addresses,
so no real message can be sent with the fixture.
If a Hermes gateway is running in the background but port 8642 is not open,
stop the UI, run `& "$env:LOCALAPPDATA\hermes\bin\hermes.exe" gateway stop`,
then run `python -m web_app` again. This temporarily stops Hermes's background
messaging and scheduled jobs; `hermes gateway start` restores it later.

The interface is a small Python standard-library HTTP server and static
HTML/CSS/JavaScript, with a server-side bridge to Hermes' local Responses API.
It uses the same deterministic analyzer and reviewer log as the CLI. Chat
history for the current browser session is kept in memory by the local bridge;
the reviewer log remains in the ignored `outputs/reviews.jsonl` file. The
included data are fictional. This is a local demo, without verified user accounts
or shared-school deployment. The operator name is an audit label, not authentication.

### Guided review, reports, actions, and learning

- Pick any start and end dates. A period with no known school dates returns no
  observed attendance; it does not invent absences. The `school_days` calendar
  catches an entire day with no attendance rows. The dashboard lists each
  student and date with `unrecorded` attendance or a missing row.
- Ask about a student or select a case; the assistant offers relevant next
  steps without a separate review-start button. A whole-period review can
  still begin with a concrete question about a pending follow-up.
  Buttons labeled **سجّل** explicitly update the local attendance or follow-up
  overlay and write an audit entry under an unverified chat-user label. Other
  answers only save review context. A separate free-text question does not
  accidentally answer the open review question.
- Enter a purpose under **تقارير حسب الطلب** to save an on-demand daily or
  range report in ignored `outputs/reports.jsonl`. The report includes actual
  attendance and the list needing completion. The Hermes report tool lets the
  model phrase the report for the requested school purpose.
- In **إجراءات المتابعة**, explicitly select an action and enter the operator,
  student, date or message details. Attendance and follow-up edits use an
  ignored overlay in `outputs/datasets/`; the committed fixture stays intact.
  Each action gets an audit entry in `outputs/actions.jsonl`. Register a new
  school day before adding attendance on it. The chat drafts contact to the
  guardian, student, or teacher and waits for the user to choose **إرسال الرسالة**.
  On successful append to `outputs/actions.jsonl`, the state is `sent_demo` and
  the exact text appears in the student's local communication history. This
  is a simulated send, not delivery to an external person. The same explicit
  request needs no second approval for attendance or follow-up edits.
  In chat, the tool uses an honest unverified operator label when no name is
  supplied, and an explicit request runs without another operator-name prompt.
  A real send still requires an address and a configured transport; the demo
  does not silently report real delivery.
- Actual email requires `guardian_email` or `student_email` in the student row,
  and `STUDENT_FOLLOWUP_SMTP_HOST`, `STUDENT_FOLLOWUP_SMTP_USER`,
  `STUDENT_FOLLOWUP_SMTP_PASSWORD`, `STUDENT_FOLLOWUP_SMTP_FROM` (optionally
  `STUDENT_FOLLOWUP_SMTP_PORT`, default 465) in the local process environment.
  SMTP uses TLS. An attempted send is audited; state `sent` means the SMTP
  server accepted it, not that a person read it. The fictional fixture has no
  email addresses. There is no SMS or WhatsApp adapter yet.
- Label a case **المؤشر صحيح**, **إنذار غير صحيح**, or **حالة فاتت الوكيل**
  with a reason and student ID. Feedback
  persists in `outputs/feedback.jsonl`. After at least eight distinct labeled
  case/period examples, including three of each class, a deterministic score
  checks threshold candidates and automatically promotes a version with at
  least 0.1 greater balanced accuracy. The active thresholds are saved in
  `outputs/rules.json` and changes in `outputs/policy_history.jsonl`. This
  adjusts rules, not model weights or source code. The initial rules remain
  until enough evidence exists. Missing attendance never becomes an absence.

These actions are a **single-operator local demo**. Before connecting real
student records, add school identity/permissions, a secure data source, contact
verification, and the school's actual communication channel. The local tool
does not modify Academix. To reset the local demo records and see the updated fixture, stop the app and remove
`outputs/datasets/fictional_school.json`. This discards local changes to the
student records. The audit logs under `outputs/` stay in place; clear them
separately only if you also want to reset the demonstration history. Do not
commit `outputs/`.

Hermes selects its configured model/provider; this project does not choose one
or store credentials. The plugin registers six tools:
`student_followup_info` finds available JSON datasets, counts students, and
shows recorded attendance date ranges without requiring a period;
`student_followup_analyze` applies the active review rules to a chosen period;
`student_followup_report` produces an on-demand report;
`student_followup_action` executes only named operations;
`student_followup_feedback` saves a label and can update the rule version.
`student_followup_context` retrieves persistent case action/feedback/answer
history across conversations. It includes the reviewed text of simulated demo
messages; it omits external email bodies and addresses.
JSON inputs are confined to `data/`. The analysis uses the same tested Python
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

Four top-level arrays are required; `school_days` is an optional calendar:

| Array | Required fields | Meaning |
| --- | --- | --- |
| `students` | `student_id`, `alias` | Unique ID and fictional display name. |
| `attendance` | `student_id`, `date`, `status` | One row per student and date; `status` is `present`, `absent`, or `unrecorded`. |
| `assessments` | `student_id`, `subject`, `date`, `score`, `max_score` | Raw score and positive maximum; compare percentages within the same subject to the preceding dated assessment. |
| `followups` | `id`, `student_id`, `date`, `topic`, `outcome` | Previous action/outcome; IDs unique. An empty list means none supplied. |
| `school_days` | ISO date strings | Expected school dates, including a day with zero attendance rows. Recommended to detect complete-day gaps. |

Dates use `YYYY-MM-DD`. `--start` and `--end` are inclusive. All referenced
students must exist. Duplicate/conflicting attendance, duplicate assessments,
invalid dates, and bad scores stop analysis instead of silently repairing data.
Absence of a row is **not** proof of absence; a supplied `unrecorded` row is
reported separately. When `school_days` is present, it defines the expected
school dates, even when no student has a row on a date. Without it, dates present
in any attendance row define the known roster; an entirely absent day cannot be
inferred. A student missing rows on known school dates requires verification.

`summary.data_quality_issues` counts cases with attendance gaps (explicit
`unrecorded` or an omitted row), and `summary.data_quality_details` lists each
affected student and the dates needing verification. It is not a count of
duplicate assessments or proof that equal scores across students are incorrect.
`summary.attendance.by_date` separates `present`, `absent`, `unrecorded`, and
missing rows for each supplied date in the selected period. Its distinct
student totals distinguish presence at least once from presence on every
recorded school day. `attendance_records_in_period` counts rows, not students
who attended.

The initial **demo review thresholds** are two recorded absences within any
five consecutive school dates, or a drop of at least 15 percentage points
from the preceding dated assessment in the same subject. The explicit calendar,
or attendance dates when absent, defines school days; no weekday pattern is
assumed. Fewer than five supplied dates cannot trigger the absence
rule. The score rule compares percentages before rounding. A case with both
signals has `high` priority, a case with one has `standard` priority; higher
priority appears first. These are review priorities, not educational diagnoses.
Recorded absence and a lower score below the thresholds are descriptive facts,
not alerts. Missing attendance remains a verification case and is never counted
as absence; a flagged case can also carry missing-information warnings. The
local feedback loop can change these thresholds in the UI and Hermes plugin;
the standalone CLI keeps the original defaults unless explicitly extended.

The agent asks for a missing fact when needed. Analysis or saving a review
decision never sends a message or alters records. An explicit action request
uses the separate audited action tool; it does not need a second approval in
this local demo.

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

Implemented: JSON validation, versioned alert rules and priority order, explicit
school calendar, missing-attendance list, reports, audited local record edits,
simulated communication history/optional SMTP, automated feedback threshold
tuning, case-specific choice buttons, reviewer log, Hermes plugin, fictional fixture, browser UI,
and executable tests. Open: live browser-to-Hermes verification on Windows,
actual contact configuration and authentication for real deployments, measured
time and tokens, demonstration feedback, and video/slides. No real student data or secrets should
be committed. `.gitignore` excludes local credentials and private logs.
