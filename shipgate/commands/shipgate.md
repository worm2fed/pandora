---
name: shipgate
description: Start, resume, or advance a feature/bug through the lean gate-driven flow (workspace → route & map → explore → clarify → design → implement → review → capture).
argument-hint: "[feature or bug description, or leave blank to resume]"
---

Drive the feature-development flow using the `feature` orchestrator skill.

User input: $ARGUMENTS

> **Config:** Read each setting from the `settings:` line of the status brief. For a key that
> line does not show, or with no brief, run
> `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" config <key>`. Exit 2 from it means a
> settings file holds a bad value: show its message and stop. With no `python3`, read
> `.claude/shipgate.json`, then `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else
> `~/.claude/shipgate.settings.json`); the first file that sets a key wins. Behaviour in words
> comes from `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file
> `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`). They layer per section by
> the rule in `config-template.md`'s header and the README's Configuration section; read them
> first if present.

The settings name the artifact homes and the forge. The config declares the rest of the
project's tooling in words, such as the branching pattern.

Do this:

1. Invoke the **`feature`** skill to orchestrate.
2. If `$ARGUMENTS` describes a new piece of work, treat it as the starting request. Begin at
   **Workspace**. Establish the right branch (`<type>/<issue-id>-<slug>`) off a clean base;
   the issue-id is optional when there's no tracker. Confirm before switching. Do **not**
   start exploring on whatever branch is checked out. Then proceed to **Route & Map**.
3. If `$ARGUMENTS` is empty, **detect the current phase, journal-first**. On a journaled project
   (the status brief is present, or `.claude/shipgate.json` exists and `journal.py config db`
   prints a `db` that is not null), read the position. Don't guess it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" status [--feature <slug>]
   ```

   That status brief is the authoritative position. Route from it, and open only the
   artifacts it names. It prints only the bound streams; with none bound, run
   `journal.py streams --open` before you open a new stream. When the user says the PR/MR
   merged, route to `feature`'s **Close-out**. Fall back to **inferring** the phase from
   the artifacts present only when the project is not journaled, or when the user has
   acknowledged an unreadable database. Look in the PRD, ADR and worklog homes: the
   `artifact_homes.prd`, `.adr` and `.worklog` settings. The defaults are
   `docs/prd/<name>.md`, `docs/adr/` and `docs/prd/<name>.worklog.md`. Then propose resuming
   at the right phase.
4. Scale ceremony to the size of the change. A one-line fix should not get a full PRD.
   Say which phases you're skipping and why.

Honor the gates. Don't design with open `[NEEDS CLARIFICATION]`. Never claim a phase complete
without running the `verify` gate.
