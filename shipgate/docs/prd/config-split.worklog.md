---
type: worklog
title: "Worklog: Split the config — settings in shipgate.json, behaviour in shipgate.md"
created: 2026-11-23
updated: 2026-11-23
tags:
  - worklog
  - shipgate
  - config
status: designing
prd: "./config-split.md"
issue: "#60 (shipgate), child of #37"
related:
  - "../adr/0028-settings-live-in-shipgate-json-and-layer-per-key.md"
  - "../adr/0018-config-layers-resolve-per-section-nearest-first.md"
  - "../adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md"
---

# Worklog: Split the config — settings in shipgate.json, behaviour in shipgate.md

> Design + build plan companion to `./config-split.md` (issue #60). ADR 0028 holds the
> decisions, the reader inventory with file:line, and the options the user chose from.

---

# Design

## Approach

One approach was left after the user's seven answers, so no architect fan ran. Settings
move into `.claude/shipgate.json` (the project settings file) and
`$CLAUDE_CONFIG_DIR/shipgate.settings.json` (the user settings file). One schema checks
them. One resolver in `scripts/_config.py` layers them per key and still reads the legacy
lines in `shipgate.md` until the grace date. The trade-off: three PRs and a dual read for
at least 60 days, in exchange for no behaviour change on the first run after the update.

The terms are the PRD's: **setting**, **settings file**, **config** (`shipgate.md`),
**legacy line**, **grace date**.

## Architecture

```
settings.schema.json ──► scripts/_config.py ─────────────────────────────┐
  (keys, types, sets,      load_schema · user_settings_path ·            │
   defaults, scope,        resolve_settings → Resolved{settings,         │
   x-legacy, x-version,      problems, legacy, legacy_until}             │
   x-legacy-until)         legacy_lines (shared with lean_config)        │
                                   ▲                                      │
        ┌──────────────┬───────────┼─────────────┬──────────────┐         │
   signals.py     _journal/settings.py   _journal/handoff.py  _journal/closeout.py
   code_signals,  `journal.py config`,   nudge threshold,     forge
   code_graph     status line, doctor    autonomy line
                  settings report

hooks/_common.py  — reads only the project settings file: db (null → no project),
                    artifact_homes, enforce. Never the user settings file.
shipgate-hud      — reads only the project settings file: version, db (null → Off),
                    artifact_homes.
lean_config.py    — --move-settings: legacy lines → settings files, diff first.
```

- **`shipgate/settings.schema.json`** (new). JSON Schema 2020-12, with `x-` annotations.
  Top level: `x-version: 2` (the one version number) and `x-legacy-until` (the grace
  date, `null` until the migration release). One property per setting with `type` or
  `enum`, `minimum`/`maximum` where they apply, `default`, `x-scope` (`project` or
  `any`), `x-since` (the release that added it) and, for a key with a legacy line,
  `x-legacy: {section, key}`. A `default` of `null` means the reader's built-in value (the
  Code signals fix pattern and excludes stay in `signals.py`).
- **`scripts/_config.py`** (extended). It stays the one config module, loaded by path. New:
  `load_schema()`, `user_settings_path()` (the same rule as `user_config_path()`, with the
  name `shipgate.settings.json`), a small validator for the schema subset in use, the
  legacy reader, and `resolve_settings(project_file, md_files, user_file)`. The resolver
  never exits and never raises on a bad value: it returns the default with a `Problem`.
  The caller decides strictness: `Resolved.require(key)` raises `SettingsError`, and the
  strict callers turn that into exit 2.
- **`scripts/_journal/settings.py`** (new module, placed after `project.py` in the layer
  order of ADR 0027). `cmd_config`, the status settings lines, and the `doctor` settings
  report. `journal.py config` runs without a database, beside `vocab` in `cli.py:954`.
- **Hooks** change in PR 2 only: `load_project` returns no project when `db` is null,
  `SIDECAR_VERSION` becomes 2, `SIDECAR_KEYS` goes, and `artifact_globs` survives a
  non-object.
- **HUD** changes in PR 2 only: it knows version 2, and `db: null` means no project.

## Data flow

1. A caller finds the project settings file: `journaled_root` (hooks, `signals.py`) or
   `find_sidecar` (`journal.py`). The walk is unchanged.
2. The caller builds the markdown layer list as today (`_journal/project.config_candidates`
   or `signals._config_candidates`) and reads it with `_config.read_layers`.
3. `resolve_settings` takes, per key, the first of: the project settings file, a
   project-side legacy line, the user settings file, a user legacy line, the default. A
   legacy line comes from ADR 0018's per-section owner, then its bullet, parsed by the
   key's legacy rule (Code signals: backticked values as `signals.parse_code_signals`
   does; Code graph; the handoff grammar; Forge as `closeout.forge_from_config`, with
   `gh` → `github` and `glab` → `gitlab`). A `project`-scope key in the user settings file
   is skipped and reported; a legacy line has no scope rule.
4. Objects (`orchestration`, `enforce`, `code_signals`, `artifact_homes`) resolve per leaf
   key.
5. Strict callers (`journal.py config`, `signals.py`, `handoff`, `closeout`, `sweep`) call
   `require` for each key they use. Hook-path callers (`status`, `nudge`, `append`) read
   the value, which is the default on a problem, and `status` names the problem.

Nothing in this flow writes. Only `setup`, through `lean_config.py --move-settings
--apply`, writes a settings file.

## Data model / schema

The project settings file after the migration, for this repo:

```json
{
  "version": 2,
  "db": ".claude/shipgate.db",
  "ledger": "docs/ledger.md",
  "artifact_homes": {"prd": "*/docs/prd/*.md", "adr": "*/docs/adr/*.md",
                     "worklog": "*/docs/prd/*.worklog.md"},
  "enforce": {"stop_gate": true, "auto_capture": true},
  "orchestration": {"review": "workflow", "explore": "workflow"},
  "code_signals": {"window_months": 12, "exclude": ["shipgate/evals/"]},
  "forge": "github"
}
```

The user settings file of a user with `Docs: ste-80` and `Mode: executive` today:

```json
{"version": 2, "writing_style": "ste-80", "autonomy": "executive"}
```

| Key | Values | Default | Scope | Legacy line |
| --- | --- | --- | --- | --- |
| `version` | integer | 2 | project | — |
| `db` | path, or `null` (no journal) | `.claude/shipgate.db` | project | — (the config's Journal section is removed) |
| `ledger` | path | `docs/ledger.md` | project | — |
| `artifact_homes` | object of globs | `docs/prd/*.md`, `docs/adr/*.md`, `docs/prd/*.worklog.md` | project | — |
| `enforce.stop_gate`, `.auto_capture`, `.command_gate` | boolean | `true` | project | — |
| `autonomy` | `ask`, `executive` | `ask` | any | Autonomy / Mode |
| `orchestration.review`, `.explore` | `agents`, `workflow` | `agents` | any | Orchestration / review, explore |
| `writing_style` | `plain`, `ste-80` | `plain` | any | Writing style / Docs |
| `code_graph` | `auto`, `off`, `root` | `auto` | any | Code tooling / Code graph |
| `code_signals.window_months` | integer 1 to 1200 | 12 | project | Code signals / Window |
| `code_signals.fix_pattern` | regex | built-in | project | Code signals / Fix pattern |
| `code_signals.exclude` | list of globs, added to the built-ins | `[]` | project | Code signals / Exclude |
| `code_signals.ranking_exclude` | list of globs, replaces the built-ins; `[]` turns them off | built-in | project | Code signals / Ranking exclude |
| `handoff` | `off`, a token count, or `500k` / `1m` / `1.5m` | `500k` | any | Session / Handoff |
| `forge` | `github`, `gitlab` | none (the PR URL host) | project | Forge & tracker / Forge |

The journal database schema does not change.

## API / contract changes

- **New command:** `journal.py config [KEY ...] [--json] [--start DIR]`. Text form, one
  line per key: `orchestration.review = workflow  (project .claude/shipgate.json)`.
  Sources: `project <path>`, `user <path>`, `legacy <path> ## <Section>`, `default`. A
  `KEY` may be a group (`orchestration`). Exit 0; exit 2 when a printed key has a bad
  value (stderr: `journal.py: <file>: <key> = <value> is not one of: <allowed>`) or the
  key is unknown; exit 1 when a settings file is not valid JSON. Warnings (unknown key in
  a file, a `project` key in the user file, a newer version, a bad legacy line) go to
  stderr and keep exit 0. `--json` prints `{settings: {key: {value, source, path}},
  problems: [...], legacy: {count, until, ended}}`.
- **Status brief** (`journal.py status`, text and `--json`): one settings line, and a
  legacy line while legacy lines exist and `x-legacy-until` is set. Example:

  ```
  settings: autonomy executive (user) · review workflow (project) · explore workflow (project) · writing ste-80 (user) · graph auto
  settings: 3 legacy lines in shipgate.md are still read until 2027-01-24 — /shipgate:setup moves them
  ```

  After the date: `... legacy lines in shipgate.md: the grace ended 2027-01-24, and the
  next shipgate release stops reading them — /shipgate:setup moves them`. A bad value
  shows as `autonomy ask (default: .claude/shipgate.json holds "exec")`. `--json` gains
  `settings` and `legacy`. The HUD golden file changes; the HUD decoders must ignore the
  new keys (T046 checks).
- **`journal.py doctor`**: the `config` block (drift) goes. A `settings` block replaces it:
  `problems`, `legacy` (each line: file, section, key, value), `nested_files`, `grace`.
  `stray_keys` becomes the unknown keys by the schema. The exit code is unchanged.
- **`signals.py --json`**: `config.source` labels gain `shipgate.json` and `user
  settings` for values from settings files. A legacy value keeps `shipgate.md` or `user
  shipgate.md`, as today.
- **Hook contract (PR 2):** a settings file with `"db": null` makes every hook act as in an
  un-journaled project. This is a change to what makes a hook act: full
  `/security-review`, separate merge question.
- **Settings file version 2.** An older shipgate warns once ("declares version 2") and
  reads the keys it knows. It reads `"db": null` as the default database.

## Reference implementation

- Layering and sources: `scripts/signals.py:326` (`load_config_layers`) over
  `scripts/_config.py:350` (`read_layers`) and `:390` (`section_owner`). They are the
  proven layer reader (ADR 0018), and their source labels are what `signals.py --json`
  already prints.
- The validator and its messages: `scripts/_journal/shapes.py:171` (`_validate_shape`),
  `:281` (`_json_word`), `:286` (`_json_got`). It is the journal's own check of a typed
  payload against a declared shape, and its errors already name the key, the value and
  the allowed set.
- A command with no database: `cmd_vocab` (`scripts/_journal/cli.py:558`) and its dispatch
  at `cli.py:954`.
- The hook fast path: `hooks/_common.py:335` (`load_project`). The J2 change is one more
  `return None` there, after the parse it already does.
- Diff first, then `--apply`: `scripts/lean_config.py` (ADR 0019), with its temp-file
  write and its exit codes.

## Pre-authorized deltas (this is a migration)

Every other difference from today's behaviour is unauthorized.

- A legacy `Code graph` value outside `auto`, `off`, `root` no longer stops `signals.py`
  with a usage error. It is ignored, named on stderr and in `doctor`, and the next layer
  applies. The test that pins the refusal changes.
- A value outside its set in a **settings file** stops `signals.py`, `journal.py config`,
  `handoff`, `closeout` and `sweep` with exit 2. Before, a bad Code signals or Handoff
  value fell back to the default with no message. This applies only to the settings
  file, never to a legacy line.
- `journal.py handoff` prints the resolved `autonomy` and its source above the quoted
  Autonomy section.
- `journal.py doctor` drops the `config` block and its drift lines, and adds `settings`.
- `journal.py status` adds the settings line, and the legacy line once `x-legacy-until`
  is set.
- `"db": null` declares no journal (PR 2). Before, it meant the default database.
- A Code signals or Code graph section in a nested repo's config moves to the project
  settings file when `setup` migrates it, and then applies to every repo.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/` (scripts, hooks, skills, docs); `shipgate-hud/` in PR 2 only.
- Hooks are a security-sensitive area (project config). PR 2 changes `hooks/_common.py`
  and `shipgate-hud/hooks/`: full `/security-review`, and the no-op path of a project
  with no shipgate files keeps its tests. PR 1 and PR 3 change no hook file.
- Reads outside the plugin directory: the user settings file. One fixed path, read only,
  never by a hook script. `journal.py nudge`, which the PostToolUse hook runs, resolves
  `handoff` through the resolver, the user settings file included, as it reads the user
  `shipgate.md` today. The user accepted this on 2026-11-23 (review round 1, F12).
- Public repo: no private project name, path or handle in any file, fixture, test or
  commit message. Grep each diff before review (root `CLAUDE.md`).
- Each PR bumps shipgate's version in `shipgate/.claude-plugin/plugin.json` and in
  `.claude-plugin/marketplace.json`, with a CHANGELOG entry, and gets its tag
  (`claude plugin tag --push` in `shipgate/` once the commit is on `main`).
- Python 3.9 compatible, stdlib only; tests run with
  `python3 -m unittest discover -s shipgate/tests` from the repo root, never `-t .`.

## Risk ranking (signals, source `graph`)

The files of the plan with a `top` label: `shipgate/README.md` (churn top),
`shipgate-hud/hooks/register.tsx` (churn top, fix top), `shipgate/scripts/signals.py`
(churn top), `shipgate/config-template.md` (churn top), `shipgate/skills/setup/SKILL.md`
(churn top). A task that changes `register.tsx` or `signals.py` starts from a green pin of
today's behaviour (T001, T024).

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.
A task line is a `-` or `*` bullet, a box, then the id: `T` and digits, bare (`T001`) or
bold (`**T001**` or `**T001:**`). The title follows, after an optional dash or colon:
`- [ ] T001 — title`, `- [ ] **T001** title`, `- [ ] **T001**: title`. A line in any other
form is not a task, so the HUD's Plan tab and the Stop gate both skip it.

## How to run this plan

The build ships in three PRs, one after the other. Each one is reviewed, published and
closed out before the next starts. Line numbers below are as of `44e7e3e`; grep again
before an edit.

1. **PR 1 — the reader** (T001-T012). Branch and stream `feat/60-config-split`, this
   stream. Start a fresh session with `journal.py handoff --stream feat/60-config-split`.
   This PR also carries the PRD, ADR 0028 and this worklog. No hook file, no skill text.
   shipgate: next minor.
2. **PR 2 — the journal marker and the HUD** (T020-T027). After PR 1 is merged and closed
   out, branch `feat/60-journal-marker` from `origin/main`. It changes hook files: full
   `/security-review`, and a separate merge question. shipgate: next minor.
   shipgate-hud: next minor, and its dependency becomes `shipgate >=` that shipgate
   version, so the HUD never shows a project as journal-less while the hooks treat it as
   journaled.
3. **PR 3 — the migration and the model** (T040-T052). After PR 2 is merged and closed
   out, branch `feat/60-settings-migration` from `origin/main`. Skill text, `setup`, docs
   and evals switch together, because a project that `setup` migrated must not be read
   by skills that still look in `shipgate.md`. This release sets the grace date. No hook
   file. shipgate: next minor.
4. **The removal** is not in this plan. T052 opens its issue.

A new stream for PR 2 or PR 3 opens with this one batch (tested on a scratch journal).
Replace the branch and the request; the lead and its command come from the handoff
brief's `report to`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream feat/60-journal-marker --batch <<'EOF'
{"type": "flow-started", "data": {"request": "#60 PR 2 of 3: the journal marker and the HUD release (worklog: shipgate/docs/prd/config-split.worklog.md)", "report_to": "<the lead and its command>"}}
{"type": "phase-entered", "data": {"phase": "workspace"}}
{"type": "phase-entered", "data": {"phase": "design", "skipped": ["route-and-map", "explore", "clarify"], "note": "design shared with feat/60-config-split"}}
{"type": "design-committed", "data": {"issue": "#60", "worklog": "shipgate/docs/prd/config-split.worklog.md", "adrs": ["shipgate/docs/adr/0028-settings-live-in-shipgate-json-and-layer-per-key.md"]}}
EOF
```

Then `journal.py handoff --stream <the new branch>` names this worklog, and the session
works the tasks of its PR. Each `task-done` goes on the stream of the PR that did it.

**Model tiers.** The orchestrator dispatches workers on Opus or above (`model-tiers`). Each
worker brief carries the root `CLAUDE.md` "Public repo" section verbatim and the
project's security-sensitive areas.

**Both session models.** PR 1 and PR 2 change no prompt or skill text. PR 3 does, and
T050 judges it on Opus and on Fable.

## PR 1 — the reader (shipgate next minor; no hook file; no skill text)

- [x] T001 — Baseline and pins — file(s): none to edit; `shipgate/tests/test_signals.py`,
  `test_codegraph.py`, `test_journal_handoff.py`, `test_closeout.py` read — done when:
  the full suite runs green and its count is in Deviations below, and the tests that the
  pre-authorized deltas change are listed by name (the Code graph refusal test among
  them).
- [x] T002 — The schema — file(s): `shipgate/settings.schema.json` (new) — done when: it
  holds every key of the Data model table with its type or set, default, `x-scope`,
  `x-since`, `x-legacy` where the table names one, `x-version: 2` and
  `x-legacy-until: null`; and a test in `shipgate/tests/test_settings.py` loads it with
  `json` and checks that its defaults equal `_journal/vocab.DEFAULT_ARTIFACT_HOMES`,
  `DEFAULT_LEDGER`, `handoff.DEFAULT_HANDOFF_TOKENS`, `signals.GRAPH_MODES` and
  `signals.MAX_WINDOW_MONTHS`.
- [x] T003 — Resolver tests first — file(s): `shipgate/tests/test_settings.py` — done
  when: they fail for the missing code and cover: per-key order (project file, project
  legacy, user file, user legacy, default); per-leaf merge of objects; the scope rule; a
  legacy line by the per-section owner, with an umbrella config and `Inherit: none`; a bad
  value in a settings file (default plus a `bad-value` problem; `require` raises); a bad
  legacy value (ignored, a problem, the next layer applies); an unknown key; a version
  above 2; `user_settings_path` with `CLAUDE_CONFIG_DIR` set, unset and set to an empty
  string; `"db": null` resolves to `None` with source `project`; a settings file that is
  not JSON. The test environment's `CLAUDE_CONFIG_DIR` holds no settings file (ADR 0018's
  isolation rule).
- [x] T004 — The resolver — file(s): `shipgate/scripts/_config.py` — done when: T003
  passes, and `_config.py` still imports nothing outside the standard library and is
  still loadable by path from `signals.py`, `lean_config.py` and `_journal/plugin.py`.
- [x] T005 — `journal.py config` tests first — file(s): `shipgate/tests/test_settings.py`
  — done when: they fail, and cover the text and `--json` forms, a group key, an unknown
  key (exit 2), a bad value (exit 2 and the message names file, key, value and the
  allowed values), a warning (exit 0, stderr), a project with no journal database and no
  settings file (the defaults, exit 0), and `--start` inside a nested repo.
- [x] T006 — `journal.py config` — file(s): `shipgate/scripts/_journal/settings.py` (new),
  `shipgate/scripts/_journal/cli.py`, `shipgate/scripts/_journal/__init__.py` (its module
  list, in layer order) — done when: T005 passes and `test_journal_layout.py` (the
  module layer order of ADR 0027) passes with the new module in place.
- [x] T007 [P] — `signals.py` reads `code_signals` and `code_graph` through the resolver —
  file(s): `shipgate/scripts/signals.py` (`load_config_layers` at `:326`,
  `effective_config` at `:393`), `shipgate/tests/test_signals.py`,
  `shipgate/tests/test_codegraph.py` — done when: the existing config tests pass
  unchanged except the Code graph refusal (now a warning, per the deltas); new tests show
  a settings-file value beats a legacy section, the flags still win, a bad settings value
  exits 2, and `config.source` reads `shipgate.json` or `user settings` for a settings
  value.
- [x] T008 [P] — The handoff threshold and the handoff brief — file(s):
  `shipgate/scripts/_journal/handoff.py` (`handoff_threshold` at `:347`, `handoff_rules`
  at `:174`), `shipgate/tests/test_journal_handoff.py` — done when: the threshold comes
  from the resolver, a bad `handoff` never makes `nudge` exit 2 (the default applies),
  the brief prints `Autonomy mode: <value> (<source>)` above the quoted Autonomy lines,
  and the existing handoff tests pass.
- [x] T009 [P] — `forge` for the close-out and the sweep — file(s):
  `shipgate/scripts/_journal/closeout.py` (`configured_forge` at `:482`,
  `forge_from_config` at `:334` moves into the legacy reader),
  `shipgate/tests/test_closeout.py` — done when: a `forge` setting gives `gh` or `glab`,
  the legacy Forge prose still does, a bad `forge` makes `closeout` and `sweep` exit 2,
  and the existing close-out tests pass.
- [x] T010 [P] — `ledger` and `artifact_homes` through the resolver — file(s):
  `shipgate/scripts/_journal/project.py` (`ledger_summary` at `:147`, `artifact_homes` at
  `:186`), `shipgate/tests/test_journal_status.py` — done when: the values are the same
  as today on every existing test, and the defaults come from the schema.
- [x] T011 — Verify PR 1 — file(s): none — done when: the full shipgate suite passes, the
  HUD tests pass (`claude plugin test` in `shipgate-hud/`, no HUD file changed), and a run
  of `journal.py config` in this repo prints today's values with `legacy` sources for
  `orchestration` and `code_signals`.
- [x] T012 — Release PR 1 — file(s): `shipgate/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `shipgate/CHANGELOG.md` — done when: shipgate is at
  its next minor in both files, and the CHANGELOG entry names the new command, the schema
  and the Code graph delta. Then review, the user's publish go, and the tag after merge.

## PR 2 — the journal marker and the HUD (hooks: full `/security-review`, separate merge question)

- [x] T020 — Hook tests first — file(s): `shipgate/tests/test_hooks.py` — done when: they
  fail, and show that with a settings file holding `"db": null` each hook (SessionStart,
  Stop, UserPromptSubmit, PostToolUse on Write and on Bash, PostToolUse on
  AskUserQuestion, FileChanged, PreToolUse on `git commit`) exits 0, prints nothing, runs
  no journal command and creates no file; that a version-2 file adds no version note;
  that an `artifact_homes` string captures nothing and raises nothing; and that a user
  settings file at `$CLAUDE_CONFIG_DIR/shipgate.settings.json` never makes a project
  journaled. The existing no-op tests (`test_hooks.py:2346`, `:4640`) stay green.
- [x] T021 — The hook change — file(s): `shipgate/hooks/_common.py` (`load_project` at
  `:335`, `SIDECAR_VERSION` and `SIDECAR_KEYS` at `:44`-`45`, `artifact_globs` at `:305`)
  — done when: T020 passes; `SIDECAR_KEYS` and its test at `test_hooks.py:522` are gone;
  the no-op path still imports nothing before the sidecar is found.
- [x] T022 — `"db": null` in the journal CLI — file(s):
  `shipgate/scripts/_journal/project.py` (`resolve_db` at `:93`, `sidecar_db_path` at
  `:138`), `shipgate/scripts/_journal/doctor.py` (`stray_keys` at `:41`),
  `shipgate/tests/test_journal.py`, `shipgate/tests/test_journal_doctor.py` — done when: a
  command that needs a journal exits 1 with `this project declares no journal ("db": null
  in <path>)`; `vocab`, `session` and `config` still run; `doctor`'s `stray_keys` are the
  keys the schema does not name; tests cover each.
- [x] T023 — One version, pinned — file(s): `shipgate/tests/test_hud_contract.py` — done
  when: a test reads `settings.schema.json` and checks that `x-version` equals
  `hooks/_common.SIDECAR_VERSION` and the HUD's `KNOWN_SIDECAR_VERSION`
  (`shipgate-hud/hooks/journal.ts:958`, read as text), and that the schema's default homes
  equal `vocab.DEFAULT_ARTIFACT_HOMES` and the HUD's table (`journal.ts:237`).
- [x] T024 — HUD pins first — file(s): `shipgate-hud/tests/register.test.ts`,
  `shipgate-hud/tests/journal.test.ts` — done when: tests pin today's `readSidecar`
  (`register.tsx:446`) and the view for a found sidecar, and new failing tests show that a
  sidecar with `"db": null` gives the Off view and no journal run, and that version 2
  gives no warning.
- [x] T025 — The HUD change — file(s): `shipgate-hud/hooks/journal.ts`
  (`KNOWN_SIDECAR_VERSION`, a `db` decoder), `shipgate-hud/hooks/register.tsx`
  (`readSidecar`, the detect path at `:866`) — done when: T024 passes with the full HUD
  suite, and T023 passes.
- [x] T026 — Security review — file(s): the PR 2 diff — done when: the `review` skill's
  security pass ran on the uncommitted diff (hooks and the HUD hooks), and the built-in
  `/security-review` runs on the commit before the push, per this repo's flow.
- [x] T027 — Release PR 2 — file(s): `shipgate/.claude-plugin/plugin.json`,
  `shipgate-hud/.claude-plugin/plugin.json` (version, and `dependencies` → `shipgate >=`
  the new shipgate version), `.claude-plugin/marketplace.json` (both entries),
  `shipgate/CHANGELOG.md`, `shipgate-hud/CHANGELOG.md` — done when: both versions are
  bumped in lockstep with the marketplace, and the CHANGELOGs name the `"db": null`
  meaning and version 2. A separate merge question (hook change), then the shipgate tag.

## PR 3 — the migration and the model (no hook file; skill text: Opus and Fable)

- [ ] T040 — Grace and status tests first — file(s): `shipgate/tests/test_settings.py`,
  `shipgate/tests/test_journal_status.py` — done when: they fail, and show, with a clock
  the test sets: the settings line; a bad value marked in it; the legacy line with the
  date before it; the "grace ended" line after it; the same resolved values on both sides
  of the date (PRD SC-008); no legacy line while `x-legacy-until` is null.
- [ ] T041 — The status lines — file(s): `shipgate/scripts/_journal/settings.py`,
  `shipgate/scripts/_journal/status.py` (`build_status` at `:42`, `render_status` at
  `:293`) — done when: T040 passes; the lines resolve from the project root; `status`
  never exits non-zero on a setting.
- [ ] T042 — The HUD contract — file(s): `shipgate-hud/tests/fixtures.journal.ts`
  (regenerated with `SHIPGATE_REGEN_GOLDEN=1`) — done when: the contract test passes and
  the HUD suite passes with no HUD code change; if a HUD decoder refuses the new keys,
  stop and report to the lead (the HUD would need a release here).
- [ ] T043 — `doctor`'s settings report — file(s): `shipgate/scripts/_journal/doctor.py`
  (`config_report` at `:121` and its render at `:236` go),
  `shipgate/scripts/_journal/settings.py`, `shipgate/tests/test_journal_doctor.py` — done
  when: the 16 config-report tests (`:125` to `:372`) are replaced by tests of the
  `settings` block (problems, legacy lines, nested settings files, the grace date, the
  text form, the exit code unchanged).
- [ ] T044 — Move-settings tests first — file(s): `shipgate/tests/test_lean_config.py` —
  done when: they fail, and cover: the diff of the config and of the settings file before
  any write; `--apply` writes both through temp files; a project-side, a nested and a user
  legacy line each land in the right settings file by scope; a user-file `project` key
  goes to the project settings file with a note; a nested value carries the "applies to
  every repo" note; a line that does not parse stays and is named; a second run finds
  nothing; `ledger` and home bullets are removed only after their difference from the
  settings file is shown.
- [ ] T045 — `lean_config.py --move-settings` — file(s): `shipgate/scripts/lean_config.py`
  — done when: T044 passes and the legacy parse comes from `_config.legacy_lines`, the
  resolver's own reader.
- [ ] T046 — `setup` — file(s): `shipgate/skills/setup/SKILL.md` — done when: a fresh run
  writes a version-2 settings file and a prose-only config; a declined journal writes
  `"db": null` only when a project setting was chosen; the user-file offer writes the
  personal settings (`autonomy`, `writing_style`, `code_graph`, `handoff`,
  `orchestration`) to the user settings file and the personal prose (Library docs, the
  promotion target) to the user config; update mode reads `doctor`'s `settings` block,
  runs `--move-settings` with the diff and a yes, and stops on a version above 2.
- [ ] T047 — The skill text — file(s): the 11 files with the config callout (10
  `shipgate/skills/*/SKILL.md` and `shipgate/commands/shipgate.md`), and each reader in
  ADR 0028 "Readers today" (find them with `grep -rn -E 'Mode:
  executive|\*\*Autonomy\*\*|review: workflow|explore: workflow|Docs: |ste-80|Code
  graph|\*\*Journal\*\*|Journal section|PRD home|Ledger' shipgate/skills shipgate/commands
  shipgate/agents`) — done when: the callout says that settings come from the brief's
  settings line or `journal.py config <key>`, that exit 2 means "show the message and
  stop", and, in one sentence, the python3-missing fallback; each reader names its setting
  key; the journaled test reads "the status brief, or a `db` that is not null";
  `model-tiers` pastes `writing_style` into worker briefs from the command.
- [ ] T048 — Prose tests — file(s): `shipgate/tests/test_prose.py` (`CONFIG_CALLOUT` at
  `:116`, the Writing style tests at `:89`-`:115`) — done when: the new callout is pinned
  in all 11 files, and a new test finds no instruction to read a moved setting from the
  config (PRD SC-001).
- [ ] T049 [P] — Docs — file(s): `shipgate/config-template.md`, `shipgate/README.md`
  (Configuration), `shipgate/docs/glossary.md`, this repo's `.claude/shipgate.md` and
  `.claude/shipgate.json` — done when: the template loses the Journal, Orchestration,
  Writing style, Code signals and Session sections and the moved bullets; the README's
  Configuration section has the settings table (from the schema), the per-key layering,
  the scope rule, the user settings file, `journal.py config` and the grace date; the
  glossary defines setting, settings file and legacy line and drops sidecar and switch;
  this repo's config is moved with `--move-settings` (PRD SC-005), and its diff is in the
  PR.
- [ ] T050 — Evals on both session models — file(s): the 20 fixtures
  (`shipgate/evals/{15,16,17,51,52,54,55}*/fixture.sh`,
  `shipgate/evals/{58..67}*/fixture.sh`, `74-review-canon-lens`, `75-graph-past-route`,
  `two-turn`) and `shipgate/evals/fixtures/bigshop.py` — done when: each fixture writes a
  settings file in place of its legacy lines (the seven with no journal write
  `"db": null`); with the `run-evals` skill (`.claude/skills/run-evals`), these 20 cases
  plus 18, 19 and 53 (the `ask`-path controls) run on Opus and on Fable; each case scores
  no lower than its baseline row, and for a model with no baseline row the same case on
  `origin/main` is the baseline. Results, as counts, go in Deviations.
- [ ] T051 — Verify PR 3 — file(s): none — done when: the full shipgate suite and the HUD
  suite pass, and the diff grep for private names, tracker ids and paths is clean.
- [ ] T052 — Release PR 3 — file(s): `shipgate/settings.schema.json` (`x-legacy-until` =
  release day + 60 days), `shipgate/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `shipgate/CHANGELOG.md` — done when: the date is set
  in the version-bump commit; the CHANGELOG names the date and the migration; a follow-up
  issue is open: "shipgate: remove the legacy config read after <date>", which names what
  goes (the legacy read in `resolve_settings`, its tests, the legacy line in the brief)
  and what stays (`doctor`'s legacy detection, `--move-settings`).

## Traceability
- FR-001 → T004, T047, T052 (the removal issue)
- FR-002 → T002, T004
- FR-003 → T003, T004
- FR-004 → T003, T020, T021
- FR-005 → T002, T003, T005, T007, T008, T009
- FR-006 → T008, T020, T040, T041
- FR-007 → T005, T006, T040, T041
- FR-008 → T047, T048
- FR-009 → T046
- FR-010 → T044, T045, T046
- FR-011 → T003, T040, T041, T052
- FR-012 → T043
- FR-013 → T020, T021, T022, T024, T025
- FR-014 → T023, T024, T025, T027
- FR-015 → T008
- SC-001 → T048
- SC-002 → T003, T005
- SC-003 → T020
- SC-004 → T005, T007, T020, T040
- SC-005 → T044, T049
- SC-006 → T050
- SC-007 → T011, T023, T051
- SC-008 → T040

## Deviations & notes (filled during implementation)

- 2026-11-23 — design: ADR 0028 was drafted as `proposed` before `clarify-passed`; the
  seven forks were the clarify escalations (journal: deviation, seq 2692).
- 2026-11-23 — T001 baseline at `44e7e3e`: the full suite ran 1715 tests, OK, 2 skipped,
  in 599 s. The run started before the first edit; later edits to `_config.py` were
  additive. The pre-authorized deltas change these existing tests in PR 1:
  `test_codegraph.TestCodeGraphConfig.test_an_invalid_value_is_a_usage_error` (a legacy
  Code graph refusal becomes a warning), and any exact-output pin of the handoff brief
  near the quoted Autonomy section (the new `Autonomy mode:` line). The 16 doctor
  config-report tests change in PR 3 (T043), not here.
- 2026-11-23 — T002: `x-since` of the keys older than the schema is the release whose
  changelog first names them (`db`, `artifact_homes`, `enforce` 0.8.0; `version`,
  `ledger` 0.22.0; `enforce.command_gate` 0.28.0). The new keys say 0.31.0.
- 2026-11-23 — T004: a value outside its set in a settings file gives the default, not
  the next layer (Data flow, FR-006). `minLength` counts characters as written, and the
  artifact homes have none, so a blank ledger and an empty home keep today's values.
- 2026-11-23 — T006: the shared helpers `project_settings`, `require_setting` and
  `setting_source` live in `_journal/project.py`, because `handoff.py` and
  `closeout.py` need them and `settings.py` holds only the `config` command.
- 2026-11-23 — T007: `signals.py` names a settings file that is not a JSON object on
  stderr and goes on, because it never read the sidecar before and a broken one did not
  stop it. A bad legacy Code signals line stays silent, as before. Only the bad legacy
  Code graph line gets the new stderr warning (the pre-authorized delta).
- 2026-11-23 — T008: the handoff brief prints `Autonomy mode: <value> (<source>)` above
  the `Autonomy (<file>):` header, or above `Autonomy: none configured`. `PIN_HANDOFF`
  in `test_journal.py` gains that one line.
- 2026-11-23 — T009: `closeout` reads `forge` before the PR URL, so a bad setting stops
  every close-out. `forge_from_config` and `FORGE_SECTION` are gone; the legacy parse is
  `_config.forge_cli`.
- 2026-11-23 — T010: `ledger` and `artifact_homes` resolve from the sidecar file alone
  (no config layers, no user file): both are project settings with no legacy line, so
  the result is the same, and `status` reads no markdown on the hook path.
- 2026-11-23 — `load_schema` raises OSError for a missing or broken schema, so every
  command reports an incomplete install with exit 1, never a traceback.
- 2026-11-23 — Notes for new issues. (a) `journal.py status` exits 1 with a traceback on
  a sidecar that is not UTF-8 or is nested too deep. The fault is in `find_sidecar` and
  `_load_sidecar`, and it is the same at `44e7e3e`. (b) Until PR 2 raises
  `SIDECAR_VERSION`, `journal.py` warns "declares version 2" on a version-2 settings
  file. No release writes one before PR 3.
- 2026-11-23 — Lesson: a text replace of `- [ ] T001 —` also matches the example of the
  task-line grammar in "Build Plan". Tick a task by its own line, anchored to the line
  start and the title.
- 2026-11-23 — T011: the first full run failed one test,
  `test_hooks.TestPrintedGoRequestsRunAsPrinted.test_the_recorder_failure_lines_print_commands_that_run`.
  Its fixture copies only `hooks/` and `scripts/` into a fake plugin cache, so the copied
  `journal.py status` found no `settings.schema.json`. The fixture now copies the schema
  too. A real install ships the whole plugin directory. No hook file changed.

## Review round 1

The `workflow` fan (run `wf_3f14582e-f96`) ran 3 lenses: 32 findings, 27 after dedupe,
16 above the floor of 60, 2 refuters, 16 survivors, 0 killed. A briefed security review
read all 23 changed files and found nothing at confidence 8 or more. The parity gate
probed about 90 config cases against `44e7e3e` and found two differences that no delta
covers (F2 and F4 below).

- F1 HIGH `shipgate/scripts/_config.py:963` — a bad value in the user settings file
  replaced a valid value of a nearer layer with the default. Fixed: the walk stops at
  the first layer that decides a key, and `require` refuses only for that layer.
- F1 MEDIUM `shipgate/scripts/_config.py:957` — the same defect, reported by two other
  lenses. Fixed with F1.
- F2 MEDIUM `shipgate/scripts/_config.py:924` — a legacy `Handoff: 300 k` lost the
  space that the old parser allowed, and fell to 500k. Fixed: the schema pattern takes
  `\s*` before the unit.
- F2 MEDIUM `shipgate/settings.schema.json:236` — the same defect. Fixed with F2.
- F2 MEDIUM `shipgate/settings.schema.json:256` — the same defect, as two grammars.
  Fixed with F2.
- F3 MEDIUM `shipgate/scripts/_config.py:688` — a settings file that is not UTF-8
  raised an uncaught error. Fixed: it is a `not-json` problem.
- F4 MEDIUM `shipgate/scripts/_config.py:528` — a broken user settings file stopped every
  strict read, `forge` too. Fixed: the walk skips a broken file, and only a key whose
  walk reached it carries the `not-json` refusal (exit 1).
- F5 MEDIUM `shipgate/docs/prd/config-split.worklog.md:306` — T001 was not ticked; the
  tick had landed on the grammar example at line 255. Fixed: both lines restored.
- F6 LOW `shipgate/scripts/_config.py:737` — a dead copy of the handoff regex. Fixed:
  removed.
- F7 LOW `shipgate/scripts/signals.py:226` — `parse_code_graph` kept a second Code graph
  parser. Fixed: it calls `_config.legacy_code_graph`.
- F8 LOW `shipgate/scripts/_journal/settings.py:69` — `config` exited 0 for a bad extra
  artifact kind. Fixed: `require` refuses it with its group.
- F9 LOW `shipgate/scripts/_journal/project.py:186` — the schema was read on every
  resolve. Fixed: `load_schema` reads it once per process. A fallback for a missing
  schema is not added: a missing schema is an incomplete install, as a missing
  `_config.py` is.
- F10 LOW `shipgate/scripts/_config.py:411` — two names for one path. Fixed: a test pins
  `SETTINGS_RELPATH` to the hooks' `SIDECAR_RELPATH` (`_config.py` stays standalone).
- F11 LOW `shipgate/scripts/_config.py:697` — `x-scope` compared with a file role.
  Fixed: `SCOPE_PROJECT` and `SCOPE_ANY`.
- F12 LOW `shipgate/scripts/_journal/handoff.py:375` — the hook-run `nudge` reads the user
  settings file, while the worklog said "never by a hook". The user accepted it on
  2026-11-23: no hook script reads the file, and `journal.py nudge` resolves `handoff`
  with it. ADR 0028 decision 6 and FR-004 now say so.
- Hardening from the security review (below its threshold): `config` prints each value
  and source on one line, and an unknown key's name goes out JSON-encoded.

### Rejected findings

- `shipgate/scripts/_config.py:986` (LOW 60): `legacy_lines` runs on every resolve. Kept:
  `config --json` reads the count today, the PR 3 status line reads it on the hook path,
  and the work is a few section walks of small files.
- `shipgate/scripts/_config.py:786` (LOW 55): a bad legacy Forge line falls to the user
  layers. The parity probes show the same result as `44e7e3e`: the section owner hides the
  user line, and the user settings file cannot set `forge`.
- `shipgate/scripts/_config.py:918` (LOW 45): a bad legacy line in the section owner hides
  a user `shipgate.md` line. That is ADR 0018's per-section rule, kept on purpose (gate
  decision, design).
- `shipgate/README.md:193` (LOW 30): no `config` row in the README command table. The
  README's settings documentation is T049 (PR 3).
- `shipgate/scripts/_journal/handoff.py:327`, `shipgate/scripts/_journal/project.py:241`,
  `shipgate/scripts/_journal/settings.py:53`, `shipgate/scripts/_journal/settings.py:75`,
  `shipgate/scripts/_config.py:622`, `shipgate/scripts/_config.py:845` (LOW 30 to 55):
  style notes, or a double version warning for a file above version 2 that PR 2 settles.

## Review round 2

One fresh reviewer re-reviewed the fix diff with all three lenses. It closed F1 to F11
and the security hardening on evidence, with 19 resolver probes and a rerun of the parity
probes (67 cases the same as `44e7e3e`; the 4 that differ are the Code graph delta). It
found three new LOW findings. The orchestrator fixed them and checked that small fix
alone (two files, three hunks, one test each).

- F13 LOW `shipgate/scripts/_config.py:656` — the name of a bad extra artifact kind went
  into the message raw, so a line break in it added a line to stderr. Fixed: a key that
  is no plain name is JSON-encoded.
- F14 LOW `shipgate/scripts/_config.py:677` — a settings file nested too deep raised
  RecursionError on the hook-run `nudge`. Fixed: it is a `not-json` problem.
- F15 LOW `shipgate/scripts/signals.py:324` — `signals.py` named a broken settings file
  that no key it reads reached. Fixed: it names a broken file only when the walk of
  `code_signals` or `code_graph` reached it.

## PR 2 — notes, deviations and measurements

- 2026-11-23 — Baselines at `9bd8121`: the shipgate suite, run on a scratch copy of
  `origin/main`, ran 1825 tests, 15 skipped, in 648 s. Its one failure,
  `test_closeout.TestThisRepoConfig`, reads this repo's `.claude/shipgate.md`, which the
  scratch copy lacks. The HUD suite passed 1001 tests.
- 2026-11-23 — The rule (gate decision): only a settings file that parses as a JSON object
  with its own `db` key set to `null` declares no journal. A `db` of another type keeps the
  default journal, so a malformed value never turns a gate off. A file the hooks cannot
  read keeps failing open, as before.
- 2026-11-23 — Deviation: the pin of the HUD's rule to the hooks' rule is a new generated
  file, `shipgate-hud/tests/fixtures.sidecar.ts`. `test_hud_contract.py` writes the hooks'
  verdict on 29 settings texts into it, and the HUD's tests check every row. The lead asked
  for this pin; the Build Plan did not name the file.
- 2026-11-23 — Deviation: T025 names `readSidecar`, but the check lives in
  `locateProject`, which `detect`, the refresh and the publish gate all reach.
  `readSidecar` is unchanged. A journaled project's detection and refresh read the
  settings file twice.
- 2026-11-23 — Deviation: files outside T027's list changed. `shipgate-hud/README.md`
  (the dependency floor, the version-2 warning, the `"db": null` behaviour) and the `/hud`
  text in `register.tsx` for a project with no journal: both were wrong for a `"db": null`
  project.
- 2026-11-23 — A deeply nested settings file depends on the Python: 3.9's json gives up
  (the hooks fail open, as before), and 3.15's json reads it (the project is journaled,
  its gates on). The test accepts both and checks exit 0 and no traceback.
  `load_project` does not catch `RecursionError`, so nothing changes from today.
- 2026-11-23 — In a linked worktree, a main checkout whose settings file says
  `"db": null` still gives the location of the worktree's relative journal (the default
  path there), as before. The worktree's own file decides whether it has a journal.
- 2026-11-23 — T026 order: the review skill's security pass runs after T027, as the
  session brief says. The built-in `/security-review` runs on the commit before the push.
- 2026-11-23 — Deviation: T025 names "a `db` decoder" for the HUD. The HUD gets a boolean
  predicate, `declaresNoJournal`, because the HUD needs only the yes or no; it reads no
  other use of `db`.
- 2026-11-23 — Only a file in strict JSON declares no journal (review round 1, F1).
  Python's json reads `NaN`, `Infinity` and `-Infinity`; the HUD's `JSON.parse` refuses
  them. `_common.parse_sidecar` marks such a file, and the hooks and `journal.py` then keep
  its journal, so all three readers agree. A settings file over 4 MiB is a third state:
  the engine's `fs.read` refuses it, so the HUD keeps the project and shows `journal.py`'s
  answer, while the hooks read it. Nobody writes such a file; the HUD then holds more,
  never less.
- 2026-11-23 — T026 is ticked on the briefed security pass of the uncommitted diff (21 of
  21 changed files read, no finding at confidence 8 or more). Its second half, the
  built-in `/security-review` on the commit, runs after the commit and before the push.
- 2026-11-23 — Accepted by the user, through the lead: shipgate 0.32.0 and shipgate-hud
  0.12.0; the rejected finding `post_tool_use.py:364` (the session's own directory
  decides); and the HUD's Off view for a `"db": null` file with a byte order mark or bytes
  that are not UTF-8. Open for the merge question: FR-006 asks the SessionStart brief to
  name each bad key once, but the PR 3 settings line (T040, T041) names only `autonomy`,
  `orchestration`, `writing_style` and `code_graph`; a bad `db`, `enforce` or
  `artifact_homes` is named nowhere. That is PR 3 scope.
- 2026-11-23 — Raw U+FEFF characters stand in source on `main` already, at
  `shipgate/hooks/pre_tool_use.py:950` and `shipgate/tests/test_journal.py:894`. This
  change leaves them as they are.
- 2026-11-23 — Notes for new issues. (1) `handoff` and `position` count only the stream's
  own `task-done`. On a plan that several PRs share, this stream's brief shows T001-T012 as
  "ticked with no task-done", and the HUD's Plan tab shows them as unrecorded, while the
  Stop gate (`check.py`) counts every stream that owns the worklog. (2) `journal.py config`
  prints a version-above-2 warning twice (`find_sidecar` and the resolver); the same in
  0.31.0. (3) `journal.py` prints a traceback for a settings file that is not UTF-8
  (`project._load_sidecar`); the same in 0.31.0 (PR 1's note (a)). (4) The HUD's walk uses
  `fs.exists` and the hooks' walk uses `isfile`, so a directory or a FIFO named
  `.claude/shipgate.json` stops only the HUD; the same in 0.11.1. (5) A settings file
  changed to `"db": null` during a session: the HUD shows `journal.py`'s failure until the
  next detection; the publish gate detects first, so it passes correctly.
- 2026-11-23 — Lessons. A backslash-u escape typed into an Edit argument landed as the raw
  character again (a BOM in a test string); the fix went through Python with `chr()`, and
  a byte scan against `origin/main` checked every changed file. Python 3.15's json reads
  100 000 levels of nesting that 3.9 to 3.11 refuse, so a hostile-form test must accept
  both outcomes. On a migration, the parity gate confirmed two lens findings with probes
  and found a third case (the BOM decode) that the lens fan missed.

### No-op path, before and after

Each hook run 20 times on this machine (Python 3.15.2), before (`origin/main`) and after,
interleaved. "No settings file" is the no-op path. Files opened: outside the standard
library and the hook script itself.

| Event | No settings file, before | No settings file, after | `"db": null`, before | `"db": null`, after |
| --- | --- | --- | --- | --- |
| SessionStart | 31.0 / 33.5 ms | 31.0 / 33.1 ms | 193.7 / 201.5 ms | 32.4 / 34.8 ms |
| Stop | 24.1 / 26.9 | 24.1 / 26.5 | 110.3 / 115.2 | 31.5 / 35.1 |
| UserPromptSubmit | 24.4 / 26.3 | 24.7 / 26.6 | 109.5 / 116.5 | 31.7 / 33.8 |
| PostToolUse Write | 25.5 / 28.1 | 24.8 / 28.0 | 32.0 / 34.4 | 32.1 / 34.7 |
| PostToolUse Bash | 24.9 / 27.0 | 24.8 / 27.3 | 33.4 / 35.9 | 32.3 / 34.7 |
| PostToolUse AskUserQuestion | 24.3 / 26.6 | 24.4 / 27.1 | 109.5 / 117.0 | 31.5 / 34.8 |
| FileChanged | 23.4 / 25.7 | 23.7 / 25.2 | 31.3 / 33.4 | 30.2 / 32.3 |
| PreToolUse `git commit` | 39.0 / 42.1 | 39.5 / 43.4 | 55.4 / 60.6 | 38.1 / 40.1 |

Median / worst. Files opened with no settings file: 1 before and 1 after for each hook
(`hooks/_common`'s compiled module). With `"db": null`: before, 2 to 5 different files
(the settings file, `.git`, `/dev/null` from git, the transcript, the hook modules) and
`journal.py` runs; after, 2 (the settings file and the module), and 3 on PostToolUse Bash
after a boundary append (the nudge module too), with no `journal.py` run. Every run exited
0. With no settings file, every run printed nothing before and after. With `"db": null`,
before, SessionStart printed a failed-journal notice and FileChanged printed a watch list;
after, every hook printed nothing. No run wrote a file.

After the fix round of review round 1 (which changed `_common.py`), an interleaved re-run of
the no-op path gave medians within 0.5 ms of `origin/main` for every event, with one file
opened. A `"db": null` project still printed nothing and wrote nothing on every event.

### Review round 1 (PR 2)

The `workflow` fan (run `wf_754a97ff-bd5`) ran 3 lenses: 16 findings, 13 after dedupe, 6
above the floor of 60, 0 refuters (no BLOCKER or HIGH), 6 survivors, 0 killed. The briefed
security review read all 21 changed files and found nothing at confidence 8 or more. The
parity gate made about 2,580 comparisons against `9bd8121` and found 3 LOW differences (F1,
F6 and the decode case below).

- F1 MEDIUM `shipgate/hooks/_common.py:346` — a `"db": null` file that also holds `NaN` or
  `Infinity` made the hooks inert, while the HUD could not parse it and held publishing.
  Fixed: only a file in strict JSON declares no journal, in the hooks and in `journal.py`;
  two golden rows pin it.
- F2 MEDIUM `shipgate/README.md:234` — the README still said version 1 and listed the old
  stray keys. Fixed: version 2, the schema's keys, and one paragraph on `"db": null`.
- F3 LOW `shipgate/docs/prd/config-split.worklog.md:710` — a 116-column line. Fixed:
  rewrapped.
- F4 LOW `shipgate/tests/test_hooks.py:995` — the stub of a failed status still took
  version 2 as the newer version. Fixed: version 3.
- F6 LOW `shipgate/scripts/_journal/doctor.py:43` — `doctor` exited 1 when the schema file
  was missing, where 0.31.0 printed its report. Fixed: it reports the stray keys as unknown.
- F7 LOW `shipgate-hud/hooks/journal.ts:966` — T025's "`db` decoder" became a predicate with
  no worklog line. Fixed: the deviation line above.
- F8 LOW `shipgate/README.md:299` — the command gate's pass cases did not name a `"db": null`
  sidecar. Fixed, and the `pre_tool_use.py` docstring too.

#### Rejected findings

- `shipgate/hooks/post_tool_use.py:364` (LOW 70): a Write into another journaled project
  from a session whose own directory says `"db": null` is not captured. In the common case
  a session with no settings file captures nothing either, because `likely_journaled` stops
  it; only a session whose `CLAUDE_PROJECT_DIR` is journaled and whose cwd sits in a
  `"db": null` project differs. The session's own directory decides, as in
  `resolve_project`. The user accepted this on 2026-11-23.
- `shipgate-hud/hooks/register.tsx:312` (LOW 50): a `"db": null` file with a byte order
  mark or bytes that are not UTF-8 may turn the HUD Off if the engine decodes it. Accepted
  as an improvement (gate decision): the hooks already read that file as no project, and
  the file says `"db": null`. The user accepted this on 2026-11-23.
- `shipgate-hud/hooks/register.tsx:297` (LOW 55): the HUD's walk uses `fs.exists`, the
  hooks' walk `isfile`, so a directory named `.claude/shipgate.json` stops only the HUD.
  The same in 0.11.1; a note for a new issue.
- `shipgate/hooks/_common.py:310` (LOW 30): a non-object `artifact_homes` captures nothing
  in the hooks but gives the defaults in `journal.py`. The design and T020 ask for exactly
  this.
- `shipgate/hooks/_common.py:362` (LOW 30): `declares_no_journal` checks `isinstance`
  again. Kept: `journal.py` calls it too.
- `shipgate/hooks/_common.py:340` (LOW 25): `read_sidecar` keeps the term "sidecar". The
  hooks use it throughout; the glossary change is T049 (PR 3).
- `shipgate/skills/setup/SKILL.md:130` (LOW 25): `setup` still writes `"version": 1`. A
  version-1 file is known and silent; `setup` is T046 (PR 3).

### Review round 2 (PR 2)

One fresh reviewer re-reviewed the fix diff with all lenses, the security criteria
included. It confirmed F1 to F8 fixed on evidence: the code lines and the tests that pin
them. It confirmed the reasoning of the rejected `post_tool_use.py:364` finding. It probed
`parse_sidecar` against `json.load` on 8 inputs (values, errors, a BOM, `1e400`, a long
integer, deep nesting) and found no change for a file without the three constants. It
found three new LOW findings, all in prose. The orchestrator fixed them and checked the
three lines alone, because they change no code.

- F9 LOW `shipgate/docs/prd/config-split.worklog.md:669` — the row count said 27; the
  golden file holds 29 rows. Fixed, and the same count in the HUD CHANGELOG.
- F10 LOW `shipgate/README.md:199` — the command table still defined `stray_keys` as the
  keys no shipgate reader uses. Fixed: the keys that `settings.schema.json` does not name.
- F11 LOW `shipgate/README.md:244` — the README did not say that a file holding `NaN` or
  `Infinity` keeps its journal. Fixed: one sentence.
