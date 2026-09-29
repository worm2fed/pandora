---
max_turns: 15
timeout_seconds: 300
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a monorepo with git history). Work inside `app/`.

Capture this for the team: the api tests must now be run with `python3 -m unittest discover -p 'check_*.py'` — the plain `python3 -m unittest` discovers nothing and reports 0 tests.
