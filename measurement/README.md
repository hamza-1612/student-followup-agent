# Measuring the demo

Freeze one dataset before either workflow. Compute its hash with
`Get-FileHash data/fictional_school.json -Algorithm SHA256` in PowerShell.
Make a copy of `template.csv` for each trial; fill actual values only.

`manual_seconds`: start when the reviewer receives the input, end after they
produce cases and draft actions. `agent_seconds`: start at launch, end when
the draft report is visible. `human_review_seconds`: time to verify and correct
the agent report. Compare manual time with agent + human review time. Record
the number of cases confirmed/corrected by a human, the same dataset hash for
both workflows, and any tool/model failures. Empty token fields mean unknown.
One timed example is a demo measurement, not evidence that all schools save
the same amount of time. Do not use illustrative 60/15-minute numbers as a
result without a real timed trial.
