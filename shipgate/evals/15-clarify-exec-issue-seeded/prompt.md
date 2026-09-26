---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

Here's the ticket we're picking up next:

> **#412 — Export invoices as CSV**
>
> Finance wants to pull invoices into their spreadsheet instead of copying from the API.
>
> Acceptance criteria:
> 1. The export has a header row and one row per invoice with: number, customer name, issued date, due date, total, status.
> 2. Values containing commas or quotes (e.g. the customer "Globex, Inc.") are quoted so the file opens correctly in a spreadsheet.
> 3. The export can be limited to open invoices, paid invoices, or all.
> 4. Exporting 10,000 invoices completes in under 2 seconds.

We're about to build this. Clarify the requirements and write the PRD to `docs/prd/invoice-csv-export.md` first.
