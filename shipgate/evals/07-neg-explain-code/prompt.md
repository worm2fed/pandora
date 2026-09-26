---
max_turns: 10
timeout_seconds: 180
allowed_tools: [Bash, Read, Grep, Glob, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo with history). Work inside `app/`.

Explain how the retry/backoff in `http_client.py` works — when does it retry, how long does it wait, and when does it give up?
