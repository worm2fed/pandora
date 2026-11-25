---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

Here's the ticket we're picking up next:

> **#431 — Late fee on overdue invoices**
>
> When an invoice goes overdue, add the late fee to the customer's balance and send an overdue notice that shows it.
>
> Policy: `docs/finance/late-fees.md`.

Clarify this and write the PRD to `docs/prd/late-fees.md` first.
