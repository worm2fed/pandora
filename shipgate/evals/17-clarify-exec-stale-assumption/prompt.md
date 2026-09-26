---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

Payment reminders: email the customer 7 days before an invoice is due and again 1 day before. We'll need to compute the due window per invoice. Clarify this and write the PRD to `docs/prd/payment-reminders.md`.
