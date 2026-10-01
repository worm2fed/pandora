---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill, Agent]
runs: 3
---
The repository for this task is the current working directory (a journaled monorepo with git history; see README.md and the CLAUDE.md files).

Payment reminders (#470): email the customer 7 days before an invoice is due and again 1 day before. We'll need to compute the due window per invoice. Clarify this and write the PRD to `docs/prd/payment-reminders.md`.
