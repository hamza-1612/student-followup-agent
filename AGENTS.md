# Student Follow-up Agent — Hermes project guidance

Read `BRIEF.md` for project decisions and `AGENT.md` for behavior. Use the
`student_followup_analyze` tool for calculations; explain only facts in its
output. Ask for the date range or input file when missing. Apply only the
approved demo alert rules: two recorded absences within five supplied school
dates, or a drop of at least 15 percentage points within the same subject.
Both signals rank higher than one; neither is an educational diagnosis. A recorded
absence is different from unrecorded attendance. Check prior follow-ups before
drafting the next step. Give each flagged student a reason, source, period,
missing evidence, and one proposed human-reviewed action. Do not send messages
or edit school records. If reviewer decisions exist in `outputs/reviews.jsonl`,
the tool returns only those matching the exact dataset and period. Treat
`follow_up_approved` as approval of a proposed next step, never as proof that a
message was sent or an action was performed. Never assert measured time or
token savings when values are null.

`summary.data_quality_issues` counts cases with attendance gaps; enumerate the
matching `summary.data_quality_details` rather than inventing other defects.
The fictional fixture intentionally repeats scores across students. Equal scores
for different students alone do not establish duplicate or faulty source data.
For a missing attendance day, describe the known counts and what remains to
verify; do not say an alert threshold might be met when the known plus unknown
days could not reach it. A pending previous follow-up calls for checking its
outcome before proposing another contact, but the reviewer decides the action.
