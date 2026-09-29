---
max_turns: 15
timeout_seconds: 300
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a monorepo with git history). Work inside `app/`.

Note for later: the test DB needs `PRAGMA foreign_keys=ON` or the cascade tests pass vacuously.
