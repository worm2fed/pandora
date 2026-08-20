---
name: setup
description: Bootstrap a project for shipgate — detect its shape, interview with recommended defaults, then write `.claude/shipgate.md`, the generated `.claude/shipgate.json` sidecar, and initialize the flow journal. Use when asked to set up, bootstrap, or configure shipgate in a repo, when `/shipgate:setup` is invoked, when changing artifact homes or the journal location later (re-running enters update mode), or when the orchestrator hits a project with no config and no journal.
---

# Setup

One pass that turns an un-bootstrapped checkout into a shipgate project: the prose config the
skills read, the sidecar the hooks read, and the journal both write to. The alternative is what
users do today — copy `config-template.md` by hand, fill in placeholders they can't evaluate
yet, and never create a journal at all.

**Detect first, ask second.** Everything you can read from the repo, read — then show the user
what you found so they only have to *correct* it. A setup that interrogates the user about
things `git remote get-url origin` already answers is a worse setup.

## Step 1 — Detect

Run these before asking anything, and report the findings as a short list:

- **Git root** — `git rev-parse --show-toplevel`. Not a git repo? Say so and stop; shipgate's
  branching, forge, and artifact conventions all assume one.
- **Umbrella layout** — nested repos (`ls -d */.git source/*/.git packages/*/.git 2>/dev/null`).
  If nested repos exist, this is an umbrella: config and journal belong at the **umbrella root**
  (features span services), branches never do. Flag it — it decides what "the repo" means for
  the rest of setup.
- **Forge** — `git remote get-url origin`: `github.com` → GitHub / `gh` / PRs, `gitlab` → GitLab
  / `glab` / MRs. Anything else, or no remote, is a question.
- **Default branch** — `git symbolic-ref --short refs/remotes/origin/HEAD`, falling back to
  `git remote show origin`. **Never assume `main`** — plenty of repos are on `master`.
- **Existing config** — `.claude/shipgate.md` and `.claude/shipgate.json`. Either present ⇒
  **update mode** (Step 4), not a fresh write.
- **Python 3** — `python3 --version`. Required for the journal; absent is not fatal (see
  Degradation).
- **Existing artifact homes** — does `docs/prd/`, `docs/adr/`, `docs/`, or a wiki/vault dir
  already exist and hold pages? An existing convention beats the default; propose what's there.

## Step 2 — Interview

Use `AskUserQuestion`, batching related questions, each option carrying your recommendation and
one line of reasoning. Keep it short enough that accepting every default is a valid path through.
Cover only what the config actually needs and detection could not settle:

- **Artifact homes** — PRDs (default `docs/prd/`), ADRs (default `docs/adr/`), worklogs beside
  the PRD as `<name>.worklog.md`. Pre-fill from what you found on disk.
- **Journal** — on (recommended) or off, and where:
  - `.claude/shipgate.db` *(default)* — travels with the checkout, disposable, gitignored.
  - `~/.local/share/shipgate/<project>.db` — survives a re-clone, one place to back up.
  - a custom path — for anything else. Never inside a container bind mount (SQLite corrupts).
- **Autonomy** — `ask` *(default)*: every gate question goes to the user. `executive`: the
  orchestrator answers routine gate questions itself and records them, escalating only one-way
  doors, scope changes, and security-sensitive areas.
- **Anything detection flagged as ambiguous** — umbrella layout confirmation, a tracker living
  in a different project than the code, an unrecognized forge.

**Do not walk the user through every template section.** Sections nobody cares about get a
sensible default or get deleted — an absent section *means* the built-in default, which is the
whole point of the template. Watcher, style skill, debug sources, epic workflow and the rest can
be added later by editing the file.

## Step 3 — Write

Order matters: never leave a sidecar pointing at a database that was not created.

1. **`.claude/shipgate.md`** — a filled-in copy of `${CLAUDE_PLUGIN_ROOT}/config-template.md`.
   Keep the section comments; fill the sections the interview settled; **delete the sections that
   don't apply** rather than leaving them empty. No `<angle-bracket placeholder>` may survive into
   the written file — a placeholder is an instruction the skills will follow literally.
2. **Initialize the journal** (skip if declined or no `python3`):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" --db <chosen-path> init
   ```
   Create the parent directory first for a global/custom path. Confirm the file exists before
   continuing; if `init` fails, stop and report — do not write a sidecar.
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
   Paths mirror the interview answers; `enforce` flags both default true. Tell the user this file
   is **generated and never hand-edited** — to change it, re-run setup.
4. **Gitignore.** The db always: `shipgate.db*` (the glob covers `-wal`/`-shm`) at the path you
   chose — nothing to ignore when it lives in a global dir. Check `git check-ignore -v` first;
   many repos already ignore `.claude/`, and a duplicate rule is noise. **The sidecar:** commit it
   when the artifact homes are the team's shared convention and the db path is repo-relative
   (then it's reproducible for every teammate); ignore it when the db path is absolute or the
   homes are your personal layout — a machine-specific path in git is a bug waiting for someone
   else's clone. Recommend accordingly, and let the user choose.
5. **Record it** — append the meta event:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream shipgate \
     --type setup-completed --data '{"db":"<path>","mode":"create"}'
   ```
6. **Leave everything unstaged.** Write the files; the user reviews and commits. Never `git add`.

Then print what was created (one line each) and the one-line **what changes now**: this project
is journaled — phase is recorded rather than guessed, artifact writes are auto-captured, and a
session won't end with a lifecycle event missing.

## Step 4 — Update mode

Config and/or sidecar already present. **Never clobber.**

1. Show what exists — the current artifact homes, journal path, autonomy mode — and ask what the
   user wants to change. Edit those lines **in place**; leave the rest of the file alone,
   including hand-written sections the template doesn't know about.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" doctor`. Apply any pending schema
   migration with `init` (idempotent, safe to re-run). When a migration actually ran, append
   `--type schema-migrated` to the `shipgate` stream with the from/to schema versions.
3. **Reconcile drift.** If the prose config's `## Journal` database path and the sidecar's `db`
   disagree, surface both and ask which is right — then fix the loser. Same for artifact homes
   that no longer exist on disk. Don't guess: the sidecar drives the hooks, the prose drives the
   model, and a silent mismatch makes capture look broken.
4. Regenerate the sidecar from the settled answers and append `setup-completed` with
   `"mode":"update"`.

## Degradation

- **No `python3`** — configure *without* a journal: omit the `## Journal` section, write no
  sidecar, and say plainly that the flow will run in legacy mode (phase inferred from artifact
  shape, exactly as shipgate has always worked). Setup succeeds; it does not fail on this.
- **User declines the journal** — same outcome: no `## Journal` section, no sidecar. Every hook
  then exits immediately in this project, which is the intended no-op.
- **Abandoned halfway** — safe by construction if you keep Step 3's order. A config without a
  sidecar is legacy mode; a db without a sidecar is an unused file. A sidecar pointing at a db
  that doesn't exist is the one broken state — never write it.
- **`init` or `doctor` fails** (locked, corrupt, unwritable path) — report the actual error, leave
  the project in whatever consistent state it was in, and offer a different journal location.

## Output

Report: the files written, the journal path (or why there is none), what got gitignored, and the
autonomy mode. Confirm nothing was staged. Then hand back — setup does not start a flow; the user
runs `/shipgate` when they're ready.
