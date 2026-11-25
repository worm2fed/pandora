---
name: setup
description: Bootstrap a project for shipgate — detect its shape, interview with recommended defaults, then write the `.claude/shipgate.json` settings file, the prose config `.claude/shipgate.md`, and initialize the flow journal; in update mode, move the legacy setting lines of an older `shipgate.md` into the settings files, with the diff shown before any write. Use when asked to set up, bootstrap, or configure shipgate in a repo, when `/shipgate:setup` is invoked, when changing a setting such as the artifact homes, the autonomy mode or the journal location later (re-running enters update mode), when the status brief says legacy lines are still read, or when the orchestrator hits a project with no config and no journal. Not for reading a setting's value: `journal.py config <key>` prints it.
---

# Setup

One pass turns an un-bootstrapped checkout into a shipgate project. It writes the settings
file that the hooks, the scripts and the skills read, the prose config the model reads, and
the journal both write to. The alternative is what users do today. They copy
`config-template.md` by hand, fill in placeholders they can't evaluate yet, and never create a
journal at all.

Two files, two roles (ADR 0028). A **setting** is a value from a fixed set (`autonomy`,
`writing_style`, `artifact_homes` and the rest of `${CLAUDE_PLUGIN_ROOT}/settings.schema.json`).
Settings live in the project settings file `.claude/shipgate.json` and in the user settings
file `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else `~/.claude/shipgate.settings.json`).
The config `.claude/shipgate.md` holds behaviour in words only. Setup never writes a setting
into a config. `journal.py config` prints every setting with its source.

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
  repo. Config, settings file and journal belong at the **umbrella root**, because features
  span services. Branches never belong there. Flag the umbrella: it decides what "the repo"
  means for the rest of setup. In a plain-folder umbrella, the forge and integration-branch
  detection below run inside a nested repo, not at the root. The scripts use the settings file
  at the root to find the umbrella's config from inside a nested repo. A settings file inside
  a nested repo would mark a second project root there; setup never writes one.
- **Forge** — `git remote get-url origin`. `github.com` → the `forge` setting `github`
  (`gh`, PRs). `gitlab` → `gitlab` (`glab`, MRs). Anything else, or no remote, is a question.
- **Integration branch** — git's default branch:
  `git symbolic-ref --short refs/remotes/origin/HEAD`, falling back to
  `git remote show origin`. **Never assume `main`**. Plenty of repos are on `master`.
- **Existing config** — `.claude/shipgate.md` and `.claude/shipgate.json`. Either present ⇒
  **update mode** (Step 4), not a fresh write.
- **User files** — does the user settings file exist? Does the user config
  (`$CLAUDE_CONFIG_DIR/shipgate.md`, else `~/.claude/shipgate.md`) exist? Existence only; the
  interview offers to write them (Step 2).
- **Python 3** — `python3 --version`. The journal requires it. Its absence is not fatal (see
  Degradation).
- **Existing artifact homes** — does `docs/prd/`, `docs/adr/`, `docs/`, or a wiki/vault dir
  already exist and hold pages? An existing convention beats the default. Propose what's there.

## Step 2 — Interview

Use `AskUserQuestion`, and batch related questions. Give each option your recommendation and
one line of reasoning. Keep it short enough that accepting every default is a valid path
through. Cover only what detection could not settle. Each answer below names the setting it
fills, or the config section for an answer in words:

- **Artifact homes** (`artifact_homes`, `ledger`) — PRDs (default `docs/prd/`), ADRs (default
  `docs/adr/`), worklogs beside the PRD as `<name>.worklog.md`, the ledger (default
  `docs/ledger.md`). Pre-fill from what you found on disk.
- **Journal** (`db`) — on (recommended) or off, and where:
  - `.claude/shipgate.db` *(default)* — travels with the checkout, disposable, gitignored.
  - `~/.local/share/shipgate/<project>.db` — survives a re-clone, one place to back up.
  - a custom path — for anything else. Never put it inside a container bind mount, because
    SQLite corrupts there.
- **Autonomy** (`autonomy`) — `ask` *(default)*: every gate question goes to the user.
  `executive`: the orchestrator answers routine gate questions itself and records them. It
  escalates only the cases in `feature`'s executive contract, plus the **Extra escalations**
  line of the config's Autonomy section (words, so it stays in the config).
- **Worker guardrails** — any hard rules for this repo that a worker must never compress.
  Examples: a build script that belongs to CI, a generated directory never edited by hand, a
  schema dump refreshed by one command, the read-only lint gate to use instead of a fixer.
  The built-in worker discipline in `model-tiers` already covers staging, `--no-verify`,
  repo-wide formatters, spend limits and comments, so don't repeat those. Write one
  imperative line each into the config's **Worker guardrails** section. Worker briefs paste
  that section verbatim. A rule that lives only in the user's head is a rule no worker will
  ever see.
- **Orchestration** (`orchestration.review`, `orchestration.explore`) — how the Review and
  Explore fans run. `agents` *(default)* is the hand-driven Agent fan. `workflow` runs the fan through the `Workflow` tool and a bundled
  script. With `workflow`, findings come back schema-typed and verified, and the raw reports do
  not enter the session's context. Recommend `workflow` for Review when the `Workflow` tool
  appears in the session's tool list, because that fan is the one that pays off. Leave Explore
  on `agents` unless the user wants both. Either way, the phase falls back to `agents` when
  the tool is absent.
- **Writing style** (`writing_style`) — `plain` *(default)*: the PRD, ADR, worklog, ledger
  lines, MR/PR body and tracker comments keep the prose style the project has today. `ste-80`: they follow the same
  "Writing for people" rule the reports already do (short sentences, common words, one term
  per concept, every fact kept). Offer it. Never recommend it over a team's own style.
- **UI files** (`ui.globs`) — ask only when the project has a web frontend: HTML templates,
  style sheets, or a component framework (React, Vue, Svelte, Angular) in its dependencies.
  Recommend globs for the directories that hold those files, such as `web/templates/*`. A
  bare extension glob also matches files that draw no screen, so prefer directories. With
  globs set, a task that touches a UI file needs a screenshot at each width of `ui.widths`
  before `task-done`, because its tests can pass while its screen is wrong. A project with
  no web frontend gets no question, and the default `[]` keeps the check off.
- **Anything detection flagged as ambiguous** — umbrella layout confirmation, a tracker living
  in a different project than the code, an unrecognized forge.

**Do not walk the user through every template section.** Sections nobody cares about get a
sensible default or get deleted. An absent section or setting *means* the built-in default,
which is the whole point of the template. The user can add the watcher, style skill, debug
sources, epic workflow and the rest later by editing the config.

**Then offer the user files, once per setup run, on a machine with no user settings file.**
Check that the user settings file exists; this check needs existence only, not its content.
The existence check is the only memory of the offer: a declined offer leaves no file, so a
later `setup` run offers again. When there is no user settings file, offer once in this run
to write the answers that are personal:

- to the user settings file: `autonomy`, `writing_style`, `orchestration`, and `code_graph`
  and `handoff` when the user set them;
- to the user config, as words: the Library docs line of the Code tooling section, the
  Extra escalations line of the Autonomy section, and the ledger's promotion target for
  preferences.

The user accepts or declines. On a yes, write those answers to the user files, and leave them
out of the project files. Never copy a user value into a project file. A setting resolves per
key, nearest first: the project settings file, then the user settings file, then the default.
The user settings file never sets a `project`-scope key (`db`, `ledger`, `artifact_homes`,
`enforce`, `code_signals`, `forge`, `ui`); `journal.py config` reports one that it holds and
ignores it. Never create the user config directory: write a user file only where that
directory exists.

## Step 3 — Write

Order matters. Never leave a settings file pointing at a database that was not created.

1. **`.claude/shipgate.md`** — a lean file of behaviour in words, with the section names and
   keys of `${CLAUDE_PLUGIN_ROOT}/config-template.md`:
   - a one-line title: `# shipgate configuration — <project>`;
   - the sections the interview filled with words (Worker guardrails, Extra escalations,
     Branching, the Forge & tracker prose, page conventions, promotion targets), and no
     others. **Delete the sections that don't apply** rather than leaving them empty;
   - `- Key: value` bullets only. No template comments, and no prose that explains the
     plugin;
   - no setting. A value from a fixed set goes into the settings file (item 3).

   The template's comments and the README are the homes of the explanations, so the config
   does not repeat them. No `<angle-bracket placeholder>` may survive into the written file,
   because the skills will follow a placeholder literally as an instruction. When no section
   has words to hold, write no config.
2. **Initialize the journal** (skip if declined or no `python3`):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" --db <chosen-path> init
   ```
   For a global/custom path, create the parent directory first. Confirm the file exists before
   continuing. If `init` fails, stop and report. Do not write a settings file.
3. **`.claude/shipgate.json`** — the project settings file, version 2:
   ```json
   {
     "version": 2,
     "db": ".claude/shipgate.db",
     "ledger": "docs/ledger.md",
     "artifact_homes": { "prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                         "worklog": "docs/prd/*.worklog.md" },
     "enforce": { "stop_gate": true, "auto_capture": true, "command_gate": true },
     "autonomy": "executive",
     "orchestration": { "review": "workflow" },
     "forge": "github"
   }
   ```
   Keys in the order of `settings.schema.json`. Always write `version`, `db`,
   `artifact_homes` and `enforce` in a journaled project: the hooks capture artifacts only
   by the homes this file names. Write `forge` from detection. Write each other setting only
   when its answer differs from the default and from the user settings file; an absent key
   means the user value, else the default. `ledger` is optional: leave it out for
   `docs/ledger.md`. The three `enforce` flags default to true. `command_gate` holds a
   model's `git commit`, `git push` and MR/PR creation until the user's go is recorded (ADR
   0023). Write it `false` only when the user says the project runs unattended, with no
   user to answer.

   **A declined journal** writes `"db": null` in place of a path: the file then marks the
   project root, and every hook acts as in a project with no journal. Write such a file only
   when the user chose a project setting (one that differs from its default and from the
   user settings file, `forge` aside, which only the journal's close-out reads). With no such
   setting, write no settings file at all.

   The file is JSON the user may edit by hand: shipgate checks every value on read. A value
   outside its set stops `journal.py config` and the scripts with exit 2 and a message that
   names the file, the key and the allowed values; the hooks use the default. Check the
   result with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" config`: exit 0, and each
   value you wrote shows source `project`.
4. **Gitignore.** Always ignore the db: `shipgate.db*` at the path you chose (the glob covers
   `-wal`/`-shm`). There is nothing to ignore when the db lives in a global dir. Check
   `git check-ignore -v` first. Many repos already ignore `.claude/`, and a duplicate rule is
   noise. **The settings file:** commit it when the artifact homes are the team's shared
   convention and the db path is repo-relative. Then it is reproducible for every teammate.
   Ignore it when the db path is absolute or the homes are your personal layout. A
   machine-specific path in git is a bug waiting for someone else's clone. Recommend
   accordingly, and let the user choose.
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

Config and/or settings file already present. **Never clobber.**

1. **Show what exists.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" config`.
   It needs no journal, and it prints each setting with its value and its source. Exit 2
   names a value outside its set: show the message, and ask for the right value. Ask what
   the user wants to change. Change a setting by its key in the settings file that holds it
   (`project` or `user` in the source), and keep every other key and its order. Change a
   section of words **in place** in the config. Leave the rest alone, including hand-written
   sections the template doesn't know about.
2. **Read the report.** In a journaled project run `journal.py doctor --json`; with no
   journal (`"db": null`), use `journal.py config --json`. Apply any pending schema
   migration with `init` (idempotent, safe to re-run). When a migration actually ran, append
   `--type schema-migrated` to the `shipgate` stream with the from/to schema versions. Read:
   - A newer settings file: `sidecar.version` (`doctor`) or `settings.version.value`
     (`config --json`) as an integer higher than 2, or a problem of kind `version`, means a
     newer shipgate wrote it. Stop. Tell the user to update shipgate, then re-run setup.
     Never rewrite a newer file down to this version. The move script refuses it too.
   - `settings.problems` (`doctor`) or `problems` (`config --json`): each value outside its
     set (`bad-value`), each legacy line that does not parse (`bad-legacy`), each unknown key
     (`unknown-key`), each `project` key in the user settings file (`scope`), a newer
     version (`version`) and each file that is no JSON object (`not-json`). Name each one to
     the user, with its fix.
   - `settings.legacy` (`doctor`) or `legacy.count` (`config --json`): the legacy lines, the
     settings that an older config still writes as bullets in `shipgate.md`.
   - `settings.nested_files`: a settings file inside a nested repo marks a second project
     root there. Offer to move its keys into the project settings file and delete it; show
     both files' change before the edit.
   - `sidecar.stray_keys`: the keys of the settings file that `settings.schema.json` does not
     name. Tell the user which keys they are and offer to drop them.
3. **Move the legacy lines.** When any exist, preview the move from the project root:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lean_config.py" --move-settings <project root>
   ```

   It reads the project config, each nested repo's config and the user config, and writes
   nothing. It prints a summary, one line per note and a unified diff of every file it would
   change: the configs lose their legacy lines, and the settings files gain the keys. Show
   the user every diff and every note, then ask. On a yes, run the same command with
   `--apply`. The notes the user must see:
   - a value from a nested repo's config now applies to every repo of the project;
   - a pinned value keeps today's result where the per-key rule would change it;
   - a line that does not parse, or that conflicts with another, stays where it is; so do
     all the lines of a key whose value the move would change for a config deeper below the
     root (the note names that config);
   - a `project` setting from the user config is copied into this project only, and stays in
     the user config for the other projects until they move it too;
   - a user-config line that moves to the user settings file now applies, key by key, in
     every other project too, also where a section of that project's config hid it before;
   - the move creates `.claude/shipgate.json` with `"db": null` in a project that has no
     settings file: the project still has no journal;
   - each difference between a removed home, ledger or database bullet and the settings file
     (the settings file already wins), and each home or ledger bullet that stays because it
     differs from the default and the settings file does not set it: offer to set that key
     in the settings file, with the user's yes.

   After the apply, run `journal.py config` again: each value must equal the value before
   the move, and the source is now a settings file. A second preview finds nothing to move.
4. **Strip the boilerplate.** A config written from the template, or by an earlier setup,
   carries text that explains the plugin (ADR 0019). Run the recogniser on it. Add
   `--user <user config>` when a user config exists. In a nested repo inside an umbrella
   checkout, also add `--umbrella <umbrella config path>`, once per umbrella config:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lean_config.py" .claude/shipgate.md [--user <user config>] [--umbrella <path> …]
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

   **Then offer to drop the sections equal to the user config's.** With `--user`, the summary
   reports each section whose body equals the user config's section. A section that an
   umbrella config also holds is reported as shadowed: it must stay, because dropping it
   would hand the section to the umbrella, not to the user config. When the summary reports
   equal sections that are not shadowed, preview their removal with the same flags, without
   `--apply`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lean_config.py" .claude/shipgate.md --user <user config> --only-equal --drop-equal [--umbrella <path> …]
   ```

   `--only-equal` marks only the equal sections, so this run never carries the boilerplate
   removal. Show that diff, name the equal sections that are not shadowed, and ask whether to
   remove them from the project file. On a yes, run the same command with `--apply`.

   Each offer in this step and in item 3 applies only the diff it showed. A yes to one is
   never a yes to another.
5. **Finish.** A settings file of version 1 that the move did not touch: raise its
   `version` to 2, with the user's yes. Drop the stray keys the user agreed to drop. Append
   `setup-completed` with `"mode":"update"`.

## Degradation

- **No `python3`** — configure *without* a journal: the settings file, if Step 3 writes one,
  says `"db": null`. Write it by hand, in the shape of Step 3, and check it is valid JSON. Say
  plainly that the flow will run un-journaled. The phase is then inferred from artifact
  shape, exactly as shipgate has always worked. Update mode cannot move legacy lines without
  `python3`: name them, and the user moves them by hand. Setup succeeds; it does not fail on
  this.
- **User declines the journal** — the same outcome: `"db": null`, or no settings file. Every
  hook then exits immediately in this project, which is the intended no-op.
- **Abandoned halfway** — safe by construction if you keep Step 3's order. A config without a
  settings file is un-journaled. A db without a settings file is an unused file. A settings
  file pointing at a db that doesn't exist is the one broken state. Never write it.
- **`init` or `doctor` fails** (locked, corrupt, unwritable path) — report the actual error.
  Leave the project in whatever consistent state it was in. Offer a different journal
  location.

## Output

Report the files written, the user file if you wrote one, and whether the boilerplate pass
stripped anything. Report the journal path (or why there is none), what got gitignored, and
the autonomy mode. Confirm nothing was staged. Then hand back. Setup does not start a flow;
the user runs `/shipgate` when they're ready.
