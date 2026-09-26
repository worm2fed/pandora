---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo with history). Work inside `app/`.

The nightly order sync (`python3 sync.py`) crashes with `TypeError: 'NoneType' object is not subscriptable` on the `customer["id"]` line in `order_sync.py`. I think we just need a null check there — can you confirm?
