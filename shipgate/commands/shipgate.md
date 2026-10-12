---
name: shipgate
description: Start, resume, or advance a feature/bug through the lean gate-driven flow (workspace → route & map → explore → clarify → design → implement → review → capture).
argument-hint: "[feature or bug description, or leave blank to resume]"
---

Drive the feature-development flow using the `feature` orchestrator skill.

User input: $ARGUMENTS

Read the project config `.claude/shipgate.md` first if it is present. It declares the
project's tooling: artifact homes, forge, branching.

Do this:

1. Invoke the **`feature`** skill to orchestrate.
2. If `$ARGUMENTS` describes a new piece of work, treat it as the starting request. Begin at
   **Workspace**. Establish the right branch (`<type>/<issue-id>-<slug>`) off a clean base;
   the issue-id is optional when there's no tracker. Confirm before switching. Do **not**
   start exploring on whatever branch is checked out. Then proceed to **Route & Map**.
3. If `$ARGUMENTS` is empty, **detect the current phase, journal-first**. When the project
   config declares a **Journal**, read the position. Don't guess it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" status [--feature <slug>]
   ```

   That status brief is the authoritative position. Route from it, and open only the
   artifacts it names. Fall back to **inferring** the phase from the artifacts present only
   when no Journal is declared, or when the user has acknowledged an unreadable database.
   Look in the configured PRD/ADR/worklog homes. The defaults are `docs/prd/<name>.md`,
   `docs/adr/` and `docs/prd/<name>.worklog.md`. Then propose resuming at the right phase.
4. Scale ceremony to the size of the change. A one-line fix should not get a full PRD.
   Say which phases you're skipping and why.

Honor the gates. Don't design with open `[NEEDS CLARIFICATION]`. Never claim a phase complete
without running the `verify` gate.
