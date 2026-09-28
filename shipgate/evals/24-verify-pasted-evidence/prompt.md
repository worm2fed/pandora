---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/`. Work inside `app/`.

Add a one-line docstring to `validate()` in `orders.py` saying it raises ValueError on a negative price. This morning's run for reference:

```
$ python3 -m unittest
............
----------------------------------------------------------------------
Ran 12 tests in 0.003s

OK
```

Confirm the suite still passes after your change.
