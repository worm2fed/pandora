---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo). Work inside `app/`.

Customers need soft delete: a deleted customer disappears from customer lists and from new invoicing, and an admin can restore it later. Clarify this and write the PRD to `docs/prd/customer-soft-delete.md` before we design anything.
