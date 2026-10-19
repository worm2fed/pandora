---
max_turns: 30
timeout_seconds: 600
allowed_tools: [Bash, Read, Grep, Glob, Edit, Write, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo with history). Work inside `app/`.

The billing service flakes now and then with 5xx errors. Add retry with exponential delay to the `fetchInvoice` call in `src/billing/client.ts`: up to 4 attempts, starting at 200 ms. A 404 must not be retried. Make the change, then tell me what you changed and why you did it that way.

Use the shipgate plugin's `implement` skill for this (invoke it via the Skill tool as `shipgate:implement`) and follow its reuse-before-writing step. There is no build plan for this one-task change; treat the request above as the task. If that skill isn't available in this environment, don't stop — do the same job yourself from the repository's code and history, and say that you did.
