---
name: shipgate
description: Start, resume, or advance a feature/bug through the lean gate-driven flow (workspace → route → explore → clarify → design → implement → review → capture).
argument-hint: "[feature or bug description, or leave blank to resume]"
---

Drive the feature-development flow using the `feature` orchestrator skill.

User input: $ARGUMENTS

Read the project config `.claude/shipgate.md` first if present — it declares the project's
tooling (artifact homes, forge, branching).

Do this:

1. Invoke the **`feature`** skill to orchestrate.
2. If `$ARGUMENTS` describes a new piece of work, treat it as the starting request and begin
   at **Workspace** — establish the right branch (`<type>/<issue-id>-<slug>`, issue-id optional
   when there's no tracker) off a clean base
   and confirm before switching; do **not** start exploring on whatever branch is checked out.
   Then proceed to **Route & Map**.
3. If `$ARGUMENTS` is empty, **detect the current phase** from the artifacts present
   (the configured PRD/ADR/worklog homes — default `docs/prd/<name>.md`, `docs/adr/`,
   `docs/prd/<name>.worklog.md`) and propose resuming at the right phase.
4. Scale ceremony to the size of the change — a one-line fix should not get a full PRD.
   Say which phases you're skipping and why.

Honor the gates: don't design with open `[NEEDS CLARIFICATION]`, and never claim a phase
complete without running the `verify` gate.
