---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill, Agent]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

The PRD `docs/prd/monthly-statement-pdf.md` is clarified. My take: render the PDF synchronously inside the API request handler — no worker, no queue, no stored files; it's a few hundred statements a month and that's the simplest thing that works. Design it that way. The working doc goes to `docs/prd/monthly-statement-pdf.worklog.md` once we've agreed the approach.
