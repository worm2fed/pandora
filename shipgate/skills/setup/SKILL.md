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
  orchestrator answers routine gate questions itself and records them. It escalates only the
  cases in `feature`'s executive contract, plus the config's **Extra escalations**.
- **Worker guardrails** — any hard rules for this repo that a worker must never compress.
  Examples: a build script that belongs to CI, a generated directory never edited by hand, a
  schema dump refreshed by one command, the read-only lint gate to use instead of a fixer.
  The built-in worker discipline in `model-tiers` already covers staging, `--no-verify`,
  repo-wide formatters, spend limits and comments, so don't repeat those. Write one
  imperative line each into the config's **Worker guardrails** section. Worker briefs paste
  that section verbatim. A rule that lives only in the user's head is a rule no worker will
  ever see.
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

**Then offer the user file, once per setup run, on a machine with no user file.** The user
file is `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set and not empty, else
`~/.claude/shipgate.md`. Check that it exists; this check needs existence only, not its
content. The existence check is the only memory of the offer: a declined offer leaves no
file, so a later `setup` run offers again. When there is no user file, offer once in this run
to write it with the answers that are personal:

- the Writing style section;
- the Library docs line of the Code tooling section;
- the Autonomy mode and its Extra escalations;
- the ledger's promotion target for preferences.

The user accepts or declines. On a yes, write those answers to the user file in the lean form
of Step 3, and leave them out of the project file. Never copy a user-file section into the
project file. The layering rule in `config-template.md`'s header makes the user file apply
under every project config.

## Step 3 — Write

Order matters. Never leave a sidecar pointing at a database that was not created.

1. **`.claude/shipgate.md`** — a lean file, with the section names and keys of
   `${CLAUDE_PLUGIN_ROOT}/config-template.md`:
   - a one-line title: `# shipgate configuration — <project>`;
   - the sections the interview filled, and no others. **Delete the sections that don't
     apply** rather than leaving them empty;
   - `- Key: value` bullets only. No template comments, and no prose that explains the
     plugin;
   - the Journal section as `- Database: <path>` only.

   The template's comments and the README are the homes of the explanations, so the config
   does not repeat them. No `<angle-bracket placeholder>` may survive into the written file,
   because the skills will follow a placeholder literally as an instruction.
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
     "ledger": "docs/ledger.md",
     "artifact_homes": { "prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                         "worklog": "docs/prd/*.worklog.md" },
     "enforce": { "stop_gate": true, "auto_capture": true }
   }
   ```
   Paths mirror the interview answers. `ledger` is optional: it is the path that the
   config's `## Knowledge base` `Ledger:` line names. Leave it out when that line is absent,
   and `status` then counts `docs/ledger.md`. Both `enforce` flags default to true. Tell the
   user this file is **generated and never hand-edited**. To change it, the user re-runs
   setup.
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
   including hand-written sections the template doesn't know about. Item 2 is the one
   exception to this rule.
2. **Strip the boilerplate.** A config written from the template, or by an earlier setup,
   carries text that explains the plugin (ADR 0019). Run the recogniser on it. Add
   `--user <user file>` when a user file exists. In a nested repo inside an umbrella
   checkout, also add `--umbrella <umbrella config path>`, once per umbrella config:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lean_config.py" .claude/shipgate.md [--user <user file>] [--umbrella <path> …]
   ```

   The umbrella config paths come from `config.files` in the output of
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --json`. The entries with
   role `umbrella` are the paths.

   The script prints a summary line and the removals as a unified diff, and writes nothing.
   Show the user the diff and ask. On a yes, run the same command with `--apply`. A line the
   script does not recognise stays, always. The script removes a block only when every
   sentence in it is boilerplate it knows. A block that also holds a project sentence stays
   whole, and the script reports it as `mixed`, for the user to split by hand.

   **Then handle the mixed blocks.** The summary counts them (`, M mixed block(s) kept`), and
   the script prints one `mixed:` line for each, with its lines, its anchor and a hint. The
   `mixed:` lines printed after an `--apply` run give the line numbers of the written file.
   Name each mixed block to the user with its hint. Then offer the fix that fits it:
   - A mixed `Executive contract` bullet names project-specific cases. Offer to add the extra
     cases to an `Extra escalations` line, then delete the bullet. The same run may have
     removed a placeholder `Extra escalations` bullet, so the line may need creating. On a
     yes, make that edit by hand.
   - A mixed prose block holds a project sentence beside the boilerplate. Offer to move the
     project sentences to their own paragraph. On a yes, make that edit. Then run the script
     again, show that diff, and on a yes run it with `--apply`. The gate repeats: a run
     without `--apply` writes nothing.

   **Then offer to drop the sections equal to the user file's.** With `--user`, the summary
   reports each section whose body equals the user file's section. A section that an
   umbrella config also holds is reported as shadowed: it must stay, because dropping it
   would hand the section to the umbrella, not to the user file. When the summary reports
   equal sections that are not shadowed, preview their removal with the same flags, without
   `--apply`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lean_config.py" .claude/shipgate.md --user <user file> --only-equal --drop-equal [--umbrella <path> …]
   ```

   `--only-equal` marks only the equal sections, so this run never carries the boilerplate
   removal. Show that diff, name the equal sections that are not shadowed, and ask whether to
   remove them from the project file. On a yes, run the same command with `--apply`.

   The two offers are separate: each one applies only the diff it showed. A yes to one is
   never a yes to the other.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" doctor --json`. Apply any pending
   schema migration with `init` (idempotent, safe to re-run). When a migration actually ran,
   append `--type schema-migrated` to the `shipgate` stream with the from/to schema versions.
   Read two more facts from its `sidecar` object:
   - `version` as an integer higher than 1 means a newer shipgate wrote the sidecar. Stop.
     Tell the user to update shipgate, then re-run setup. Never rewrite a newer sidecar down
     to this version.
   - `stray_keys` lists the sidecar's keys that the sidecar shape in Step 3 — Write
     (item 3) does not name. Item 5 below drops them.

   Then read its `config` object. `config.drift` lists each disagreement between the
   config's `Ledger:`, `PRD home:`, `ADR home:` and `Worklog home:` lines and the sidecar,
   one line each. A ledger that the config names and the sidecar lacks is the common case.
   `config.ledger` and `config.homes` give the value on each side.
4. **Reconcile drift.** The config's `## Journal` database path and the sidecar's `db` may
   disagree. Then surface both and ask which is right. Fix the loser. Do the same for artifact
   homes that no longer exist on disk. Don't guess. The sidecar drives the hooks, the prose
   drives the model, and a silent mismatch makes capture look broken. For each
   `config.drift` line, the config wins: it is the prose the model and the user read, and
   the sidecar is generated. Item 5 fixes the sidecar from the config.
5. Regenerate the sidecar from the settled answers and the config's Knowledge base values,
   with the keys of the sidecar shape in Step 3 — Write (item 3) only: `version`, `db`,
   `ledger` (when the config names one), `artifact_homes` and `enforce`. When `doctor`
   reported `stray_keys`, tell the user which keys you dropped, one line. Append
   `setup-completed` with `"mode":"update"`.

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

Report the files written, the user file if you wrote one, and whether the boilerplate pass
stripped anything. Report the journal path (or why there is none), what got gitignored, and
the autonomy mode. Confirm nothing was staged. Then hand back. Setup does not start a flow;
the user runs `/shipgate` when they're ready.
