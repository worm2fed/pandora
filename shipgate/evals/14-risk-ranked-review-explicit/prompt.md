---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Grep, Glob, Skill]
runs: 3
---
The repository for this task is already checked out in `app/` (a git repo with history). Work inside `app/`.

I'm about to review the change at HEAD. Rank its changed files by how likely each is to regress, most risky first, and say what evidence you used. This is a review-risk ranking to decide where I look hardest — not a code review, so don't review the diff contents or list issues in it. Keep the answer short: a numbered list of the changed files with one line of evidence each.

Use the shipgate plugin's `review` skill for this (invoke it via the Skill tool as `shipgate:review`) — I want the ranking to come from the per-file risk signals it computes for the diff, not from reading the code. If that skill isn't available in this environment, don't stop — do the same job yourself from the repository's history and structure, and say that you did.
