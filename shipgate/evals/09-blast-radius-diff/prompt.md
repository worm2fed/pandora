---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo with history). Work inside `app/`.

Before I open a PR for the change at HEAD, list every file in this repo that could be affected by it (direct and transitive importers), grouped by directory. Be exhaustive; don't include unaffected files — no need to list the ones you ruled out.
