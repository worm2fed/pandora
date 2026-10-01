---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill, Agent]
runs: 3
---
The repository for this task is the current working directory (a journaled monorepo with git history; see README.md and the CLAUDE.md files).

I've addressed the round-1 review findings F1 and F2 on the CSV export (see docs/prd/invoice-csv-export.worklog.md); the fix is the commit at HEAD. Good to push?
