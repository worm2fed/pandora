---
max_turns: 15
timeout_seconds: 300
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill, Agent]
runs: 3
---
The repository for this task is the current working directory (a journaled monorepo with git history; see README.md and the CLAUDE.md files).

Change the default page size in `services/api/config.py` from 20 to 50.
