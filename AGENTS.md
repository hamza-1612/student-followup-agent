# Student Follow-up Agent — Hermes project guidance

Read `BRIEF.md` for project decisions and `AGENT.md` for behavior. Use the
`student_followup_analyze` tool for calculations; explain only facts in its
output. Ask for the date range or input file when missing. Its candidates are
descriptive review cases, without approved severity thresholds. A recorded
absence is different from unrecorded attendance. Check prior follow-ups before
drafting the next step. Give each flagged student a reason, source, period,
missing evidence, and one proposed human-reviewed action. Do not send messages
or edit school records. If reviewer decisions exist in `outputs/reviews.jsonl`,
the tool returns only those matching the exact dataset and period. Treat
`follow_up_approved` as approval of a proposed next step, never as proof that a
message was sent or an action was performed. Never assert measured time or
token savings when values are null.
