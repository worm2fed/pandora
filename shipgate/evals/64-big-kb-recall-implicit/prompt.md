---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill, Agent]
runs: 3
---
The repository for this task is the current working directory (a journaled monorepo with git history; see README.md and the CLAUDE.md files).

Failed notification emails should retry with exponential backoff. Propose how we'd do it.
