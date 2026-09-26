---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

Feature: monthly statement PDF.

In scope: a per-customer statement for one calendar month, listing that month's invoices and payments with an opening and closing balance; generated on demand from the customer page; downloadable as PDF.
Out of scope: scheduled or emailed statements, multi-currency, custom branding per customer.
Acceptance: a statement for a customer with up to 500 invoices in the month generates in under 3 seconds; opening + activity = closing balance to the cent; a month with no activity still produces a statement whose opening and closing balances are equal.

Write the PRD to `docs/prd/monthly-statement-pdf.md`. Only ask if something is genuinely missing.
