---
type: prd
title: "PRD: Split the config — settings in shipgate.json, behaviour in shipgate.md"
created: 2026-11-23
updated: 2026-11-23
tags:
  - prd
  - shipgate
  - config
status: clarified
issue: "#60 (shipgate), child of #37"
worklog: "./config-split.worklog.md"
related:
  - "../adr/0018-config-layers-resolve-per-section-nearest-first.md"
  - "../adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md"
  - "../adr/0028-settings-live-in-shipgate-json-and-layer-per-key.md"
---

# PRD: Split the config — settings in shipgate.json, behaviour in shipgate.md

> Each project file gets one role. `shipgate.json` holds the settings: values from fixed
> sets that scripts, hooks and skills read. `shipgate.md` holds behaviour in words that the
> model reads.

## Terms

- **Setting**: one key of a settings file, with a value from a fixed set (a word from a
  list, a number in a range, a path, a glob, a regex).
- **Settings file**: `.claude/shipgate.json` at a project root, or the user settings file
  `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else `~/.claude/shipgate.settings.json`).
- **Config**: `.claude/shipgate.md` and the user's `shipgate.md`. Prose only, after this
  change.
- **Legacy line**: a setting that an existing config still writes as a `- Key: value`
  bullet in `shipgate.md`.
- **Grace date**: the last day on which a release reads legacy lines without saying that
  the grace has ended. It is release day of the migration plus 60 days.

## Problem

shipgate reads its project configuration from two files, and their roles overlap.

- `shipgate.md` is the source of truth for the model. Six of its sections are settings
  that the model must read out of prose: Autonomy `Mode`, Orchestration, Writing style,
  Code graph, Code signals and Session `Handoff`. Scripts parse four of them out of the
  markdown too: Code signals, Code graph, Session `Handoff` and the Forge CLI.
- `shipgate.json` is a sidecar that `setup` generates. Hooks and scripts read its journal
  path, ledger, artifact homes and `enforce` switches. `journal.py doctor` compares the
  ledger and the artifact homes with the markdown and reports drift.
- Each new feature adds one more setting to the prose. A script that needs the value must
  parse markdown through the section layers of ADR 0018. #25 plans a `Publish quiz`
  setting, and the HUD (TypeScript) would need it too.
- The readers disagree on a wrong value. `signals.py` refuses a bad `Code graph`. It drops a
  bad `Window` silently. The handoff threshold falls back to its default. A hook reads an
  `enforce` value that is not `false` as on. No skill says what an unknown word means.

The full reader inventory, with file and line, is in ADR 0028 ("Readers today").

## Goals & non-goals

**Goals**
- One home per setting. No setting is read from both files.
- Settings layer per key, across the project and the user.
- A versioned schema that names each setting, its allowed values, its default and its
  scope.
- One command that prints a setting's resolved value and the file it came from.
- An existing project keeps its behaviour across the update.

**Non-goals**
- No change to the prose sections or to their per-section layering (ADR 0018).
- No change to the journal schema or the event vocabulary.
- No new enforcement. `enforce` keeps its three switches and their defaults.
- No `config set` command. The settings file is edited by hand or by `setup`.
- No settings file below a project root. A nested repo in an umbrella takes the
  umbrella's settings.

## Users & stories

- As a user, I set my personal settings once, in one user settings file, and every
  project applies them unless the project sets its own value.
- As a user, I change one setting in a project without copying the rest of its group.
- As a user of a project with no journal, I still keep project settings in a settings
  file that declares no journal.
- As a skill author, I add a setting with one schema entry and one reader call, with no
  markdown parser.
- As a user with an installed project, I update shipgate and my flows behave the same.
  `setup` then moves my settings for me and shows the diff first.
- As the model, I learn a setting's value and its source from the status brief or one
  command, not from two files.

## Functional requirements

- **FR-001** — Every setting has exactly one home: the settings files. After the grace
  period of FR-011, no release reads a setting from `shipgate.md`.
- **FR-002** — These values become settings: `autonomy`, `orchestration.review`,
  `orchestration.explore`, `writing_style`, `code_graph`, `code_signals`
  (`window_months`, `fix_pattern`, `exclude`, `ranking_exclude`), `handoff`, `forge`, and
  the keys the settings file holds today: `version`, `db`, `ledger`, `artifact_homes`,
  `enforce`. Every section that describes behaviour in words stays in `shipgate.md`
  (Assumptions).
- **FR-003** — Settings resolve per key, nearest first: the project settings file, then
  the user settings file, then the built-in default. A layer that does not set a key lets
  the next layer show through. Objects merge per leaf key. A `project`-scope key (`db`,
  `ledger`, `artifact_homes`, `enforce`, `code_signals`, `forge`) is read from the project
  settings file only: in the user settings file it is ignored and reported. `Inherit:
  none` stays in the config's title and governs the prose layers only.
- **FR-004** — The user settings file never marks a project as journaled. Its name is one
  that no walk for `.claude/shipgate.json` finds. No hook script reads it. `journal.py
  nudge`, which the PostToolUse hook runs, resolves `handoff` through the resolver, the
  user settings file included (the user accepted this on 2026-11-23). A hook in a project
  with no project settings file reads no JSON.
- **FR-005** — One schema names every setting: its key, type, allowed values or range,
  default, scope and the release that added it. The settings file carries `version: 2`.
  A value outside its set, in a settings file, stops each command and script that reads
  it: exit 2, with the file, the key, the value and the allowed values. An unknown key is
  a warning, never a refusal. A `version` above 2 is a warning, and the known keys are
  still read.
- **FR-006** — A hook never fails a session because of a setting. On a bad value it uses
  the key's default, and every `enforce` switch stays on. The SessionStart brief names
  each bad key once. The journal commands that a hook runs (`status`, `nudge`, `append`)
  follow the same rule.
- **FR-007** — `journal.py config [KEY ...] [--json]` prints the resolved value of one
  setting, or of all, with its source: the file path, `legacy` with its file, or
  `default`. It needs no journal database. The SessionStart status brief carries one
  settings line: `autonomy`, `orchestration`, `writing_style` and `code_graph`, each with
  its source.
- **FR-008** — Every skill, agent and command reads a setting from the brief's settings
  line or through `journal.py config`. No skill text tells the model to read a setting
  from `shipgate.md` or from a settings file directly, except the python3-missing
  fallback (Assumptions).
- **FR-009** — `setup` writes the settings file on a fresh run. It asks only for the
  settings that detection cannot settle, as today. A project that declines the journal
  gets a settings file with `"db": null` when it sets a project setting, and no settings
  file otherwise.
- **FR-010** — `setup` in update mode moves each legacy line out of the project config,
  the umbrella's and nested configs, and the user's `shipgate.md`, into the matching
  settings file. It shows the diff of every file it would change and writes nothing
  before the user says yes. A legacy line that does not parse stays where it is, and
  `setup` names it. A value from a nested config is named as one that will apply to every
  repo of the project.
- **FR-011** — Legacy lines keep working until the grace date, and after it until the
  release that removes the legacy read. The first release after the grace date removes
  it. The grace date is one constant in the shipgate code, set by the release that ships
  the migration. On the first run after that release, every setting resolves as before.
  The SessionStart brief of a project with legacy lines carries one line: their count, the
  grace date and `/shipgate:setup` to move them. After the grace date the line says that
  the grace has ended. No value changes on a calendar day.
- **FR-012** — `journal.py doctor` drops the config-against-sidecar drift check. Its
  settings report names each value outside its set, each unknown key, each
  `project`-scope key in the user settings file, each legacy line, each settings file
  below a project root, and the grace date.
- **FR-013** — A `.claude/shipgate.json` marks its directory as the project root, as
  today. `"db": null` declares that the project has no journal: every hook then acts as
  in an un-journaled project, and the HUD shows no journal view. A settings file without
  a `db` key keeps today's default database.
- **FR-014** — `shipgate-hud` reads `version`, `db` and `artifact_homes` from the same
  settings file. It knows version 2 and shows no "newer version" warning on a file this
  shipgate release writes. Its release declares the shipgate release that reads
  `"db": null`.
- **FR-015** — The handoff brief prints the resolved `autonomy` with its source beside the
  prose Autonomy section (the extra escalations), so a fresh session still knows both.

## Success criteria

- **SC-001** — A test reads every skill, agent and command file and finds no instruction
  to read a setting from `shipgate.md`. A second test finds the config callout, in its
  new form, in each of the 11 files that carry it today.
- **SC-002** — For each schema key, a test resolves the value from each layer and from the
  default, and checks the printed source.
- **SC-003** — A project with no shipgate files: each hook reads no JSON file and imports
  no module beyond what it does today. The existing no-op tests stay green. A new test
  puts a user settings file in place and shows that the project stays un-journaled. A
  project whose settings file says `"db": null`: each hook exits 0, prints nothing and
  runs no journal command.
- **SC-004** — A value outside its set: `journal.py config`, `signals.py` and every other
  reader of the key exit 2, and the message names the file, the key, the value and the
  allowed values. A hook with the same file exits 0, and the SessionStart brief names the
  key once.
- **SC-005** — This repo's own config, a user file with `Docs: ste-80` and `Mode:
  executive`, and one fixture per old section form resolve to the same values before and
  after the update, through the legacy read and again after `setup` moves them.
- **SC-006** — The eval cases that set a setting (20 fixtures today) run with a settings
  file on Opus and on Fable. Each case scores no lower than its row in the baseline.
- **SC-007** — The shipgate and shipgate-hud test suites pass. A test pins the schema's
  version and default homes to the copies in the hooks, the journal and the HUD.
- **SC-008** — With the grace date in the past, a test shows the same resolved values as
  the day before, and the brief line says that the grace has ended.

## Constraints & assumptions

- shipgate's scripts stay Python 3.9 compatible and stdlib only. No `jsonschema` package.
- Hooks run in every project a user opens. The no-op path for a project with no shipgate
  files is a correctness requirement (root `CLAUDE.md`, project config).
- The migration changes what an installed plugin does on someone else's machine, an extra
  escalation in this repo's config. The user decided it (Decisions).
- FR-013 changes what makes a hook act. The PR that ships it takes the full
  `/security-review` and a separate merge question.
- The HUD declares a shipgate range and resolves it against the `shipgate--v*` tags. Its
  release that knows version 2 ships with the shipgate release that reads `"db": null`.
- A project with no journal and a settings file pays `import json` and one parse, about
  9 ms, on each hook event. A project with no settings file pays nothing new.

## Assumptions (executive)

- Which terms name the two files and a value? → setting, settings file, config (see
  Terms) — one term per concept; "sidecar" and "switch" stop fitting once the JSON holds
  user choices.
- Is the settings file hand-editable? → yes, validated on read; `setup` still writes it;
  no `config set` command — a write command would be a second way to edit the file.
- Which sections stay prose? → Extra escalations, Security-sensitive areas, Worker
  guardrails, Close-out steps, Style, Thinking lenses, Branching, Repo layout, Debug
  evidence sources, Epic workflow, MR watcher, the Forge & tracker prose, Library docs,
  Code navigation, and the Knowledge base's Stores, Page conventions and promotion
  targets — the issue keeps every behaviour-in-words section.
- What does a skill do when python3 is missing? → it reads the project and user settings
  files itself, nearest first per key; one sentence in the config callout — a project
  with no python3 has a working config today and keeps one.
- Where do the settings that #24 and #25 plan land? → in the settings file with a schema
  entry, each in its own PR — that is why #60 runs before batch 3 of #37.
- Does a setting carry a comment field for its reason? → no; a reason stays in a prose
  section of the config where one remains, else in the commit message — stdlib `json`
  has no comments, and a comment key is one more rule.

## Decisions (the user, through the lead, 2026-11-23)

The seven escalated forks. ADR 0028 holds the options and their costs.

- **J** — option J2: a settings file marks the project root; `"db": null` declares no
  journal (FR-013).
- **G** — a grace date, not a release count: legacy lines are read for at least 60 days
  after the migration release; the first release after the date removes the read; the
  brief line names the date (FR-011).
- **K** — option K2: the issue's list plus `forge` (FR-002).
- **L** — option L1: per key, scoped, user file `shipgate.settings.json` (FR-003, FR-004).
- **S** — option S1: version 2; commands and scripts exit 2; hooks use the default
  (FR-005, FR-006).
- **M** — option M2: `journal.py config` plus one settings line in the brief (FR-007).
- **D** — option D1: delete the drift check; `doctor` reports settings problems (FR-012).
