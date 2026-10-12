---
name: setup
description: Bootstrap a project for shipgate — detect its shape, interview with recommended defaults, then write `.claude/shipgate.md`, the generated `.claude/shipgate.json` sidecar, and initialize the flow journal. Use when asked to set up, bootstrap, or configure shipgate in a repo, when `/shipgate:setup` is invoked, when changing artifact homes or the journal location later (re-running enters update mode), or when the orchestrator hits a project with no config and no journal.
---

# Setup

One pass turns an un-bootstrapped checkout into a shipgate project. It writes the config the
skills read, the sidecar the hooks read, and the journal both write to. The alternative is
what users do today. They copy `config-template.md` by hand, fill in placeholders they can't
evaluate yet, and never create a journal at all.

**Detect first, ask second.** Read everything you can read from the repo. Then show the user
what you found, so they only have to *correct* it. A setup that interrogates the user about
things `git remote get-url origin` already answers is a worse setup.

## Step 1 — Detect

Run these before asking anything. Report the findings as a short list:

- **Git root** — `git rev-parse --show-toplevel`. Not a git repo? That alone is no reason to
  stop, because an umbrella root is often a plain folder (next bullet). Stop, and say so, only
  when the directory is no git repo **and** holds no nested repos. shipgate's branching, forge,
  and artifact conventions all assume one.
- **Umbrella layout** — nested repos (`ls -d */.git source/*/.git packages/*/.git 2>/dev/null`).
  If nested repos exist, this is an umbrella, whether or not the umbrella root is itself a git
  repo. Config, sidecar and journal belong at the **umbrella root**, because features span
  services. Branches never belong there. Flag the umbrella: it decides what "the repo" means
  for the rest of setup. In a plain-folder umbrella, the forge and integration-branch
  detection below run inside a nested repo, not at the root. The scripts use the sidecar at the
  root to find the umbrella's config from inside a nested repo.
- **Forge** — `git remote get-url origin`. `github.com` → GitHub / `gh` / PRs. `gitlab` →
  GitLab / `glab` / MRs. Anything else, or no remote, is a question.
- **Integration branch** — git's default branch:
  `git symbolic-ref --short refs/remotes/origin/HEAD`, falling back to
  `git remote show origin`. **Never assume `main`**. Plenty of repos are on `master`.
- **Existing config** — `.claude/shipgate.md` and `.claude/shipgate.json`. Either present ⇒
  **update mode** (Step 4), not a fresh write.
- **Python 3** — `python3 --version`. The journal requires it. Its absence is not fatal (see
  Degradation).
- **Existing artifact homes** — does `docs/prd/`, `docs/adr/`, `docs/`, or a wiki/vault dir
  already exist and hold pages? An existing convention beats the default. Propose what's there.

## Step 2 — Interview

Use `AskUserQuestion`, and batch related questions. Give each option your recommendation and
one line of reasoning. Keep it short enough that accepting every default is a valid path
through. Cover only what the config actually needs and detection could not settle:

- **Artifact homes** — PRDs (default `docs/prd/`), ADRs (default `docs/adr/`), worklogs beside
  the PRD as `<name>.worklog.md`. Pre-fill from what you found on disk.
- **Journal** — on (recommended) or off, and where:
  - `.claude/shipgate.db` *(default)* — travels with the checkout, disposable, gitignored.
  - `~/.local/share/shipgate/<project>.db` — survives a re-clone, one place to back up.
  - a custom path — for anything else. Never put it inside a container bind mount, because
    SQLite corrupts there.
- **Autonomy** — `ask` *(default)*: every gate question goes to the user. `executive`: the
  orchestrator answers routine gate questions itself and records them. It escalates only
  one-way doors, scope changes, and security-sensitive areas.
- **Worker guardrails** — any hard rules a worker must never compress. Examples: formatters or
  linters that rewrite files (and the read-only gate to use instead), build scripts, staging
  conventions, spend limits. Write one imperative line each into the config's
  **Worker guardrails** section. Worker briefs paste that section verbatim. A rule that lives
  only in the user's head is a rule no worker will ever see.
- **Orchestration** — how the Review and Explore fans run. `agents` *(default)* is the
  hand-driven Agent fan. `workflow` runs the fan through the `Workflow` tool and a bundled
  script. With `workflow`, findings come back schema-typed and verified, and the raw reports do
  not enter the session's context. Recommend `workflow` for Review when the `Workflow` tool
  appears in the session's tool list, because that fan is the one that pays off. Leave Explore
  on `agents` unless the user wants both. Either way, the phase falls back to `agents` when
  the tool is absent.
- **Writing style** — `plain` *(default)*: the PRD, ADR, worklog, ledger lines, MR/PR body and
  tracker comments keep the prose style the project has today. `ste-80`: they follow the same
  "Writing for people" rule the reports already do (short sentences, common words, one term
  per concept, every fact kept). Offer it. Never recommend it over a team's own style.
- **Anything detection flagged as ambiguous** — umbrella layout confirmation, a tracker living
  in a different project than the code, an unrecognized forge.

**Do not walk the user through every template section.** Sections nobody cares about get a
sensible default or get deleted. An absent section *means* the built-in default, which is the
whole point of the template. The user can add the watcher, style skill, debug sources, epic
workflow and the rest later by editing the file.

## Step 3 — Write

Order matters. Never leave a sidecar pointing at a database that was not created.

1. **`.claude/shipgate.md`** — a filled-in copy of `${CLAUDE_PLUGIN_ROOT}/config-template.md`.
   Keep the section comments. Fill the sections the interview settled. **Delete the sections
   that don't apply** rather than leaving them empty. No `<angle-bracket placeholder>` may
   survive into the written file, because the skills will follow a placeholder literally as an
   instruction.
2. **Initialize the journal** (skip if declined or no `python3`):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" --db <chosen-path> init
   ```
   For a global/custom path, create the parent directory first. Confirm the file exists before
   continuing. If `init` fails, stop and report. Do not write a sidecar.
3. **`.claude/shipgate.json`** — the generated sidecar, exactly this shape:
   ```json
   {
     "version": 1,
     "db": ".claude/shipgate.db",
     "artifact_homes": { "prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                         "worklog": "docs/prd/*.worklog.md" },
     "enforce": { "stop_gate": true, "auto_capture": true }
   }
   ```
   Paths mirror the interview answers. Both `enforce` flags default to true. Tell the user this
   file is **generated and never hand-edited**. To change it, the user re-runs setup.
4. **Gitignore.** Always ignore the db: `shipgate.db*` at the path you chose (the glob covers
   `-wal`/`-shm`). There is nothing to ignore when the db lives in a global dir. Check
   `git check-ignore -v` first. Many repos already ignore `.claude/`, and a duplicate rule is
   noise. **The sidecar:** commit it when the artifact homes are the team's shared convention
   and the db path is repo-relative. Then it is reproducible for every teammate. Ignore it when
   the db path is absolute or the homes are your personal layout. A machine-specific path in
   git is a bug waiting for someone else's clone. Recommend accordingly, and let the user
   choose.
5. **Record it** — append the meta event:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream shipgate \
     --type setup-completed --data '{"db":"<path>","mode":"create"}'
   ```
6. **Leave everything unstaged.** Write the files. The user reviews and commits. Never
   `git add`.

Then print what was created, one line each. Add the one-line **what changes now**: this
project is journaled. The phase is recorded rather than guessed, artifact writes are
auto-captured, and a session won't end with a lifecycle event missing. Say the stream rule
while you are there: **one stream per issue, named for its branch**. An epic's children are
separate branches, so they are separate streams. This rule lets the SessionStart hook put the
checked-out branch's stream first and drop the finished ones.

## Step 4 — Update mode

Config and/or sidecar already present. **Never clobber.**

1. Show what exists: the current artifact homes, journal path, autonomy mode. Ask what the
   user wants to change. Edit those lines **in place**. Leave the rest of the file alone,
   including hand-written sections the template doesn't know about.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" doctor`. Apply any pending schema
   migration with `init` (idempotent, safe to re-run). When a migration actually ran, append
   `--type schema-migrated` to the `shipgate` stream with the from/to schema versions.
3. **Reconcile drift.** The config's `## Journal` database path and the sidecar's `db` may
   disagree. Then surface both and ask which is right. Fix the loser. Do the same for artifact
   homes that no longer exist on disk. Don't guess. The sidecar drives the hooks, the prose
   drives the model, and a silent mismatch makes capture look broken.
4. Regenerate the sidecar from the settled answers. Append `setup-completed` with
   `"mode":"update"`.

## Degradation

- **No `python3`** — configure *without* a journal. Omit the `## Journal` section and write no
  sidecar. Say plainly that the flow will run un-journaled. The phase is then inferred from
  artifact shape, exactly as shipgate has always worked. Setup succeeds; it does not fail on
  this.
- **User declines the journal** — same outcome: no `## Journal` section, no sidecar. Every
  hook then exits immediately in this project, which is the intended no-op.
- **Abandoned halfway** — safe by construction if you keep Step 3's order. A config without a
  sidecar is un-journaled. A db without a sidecar is an unused file. A sidecar pointing at a
  db that doesn't exist is the one broken state. Never write it.
- **`init` or `doctor` fails** (locked, corrupt, unwritable path) — report the actual error.
  Leave the project in whatever consistent state it was in. Offer a different journal
  location.

## Output

Report the files written, the journal path (or why there is none), what got gitignored, and
the autonomy mode. Confirm nothing was staged. Then hand back. Setup does not start a flow;
the user runs `/shipgate` when they're ready.
