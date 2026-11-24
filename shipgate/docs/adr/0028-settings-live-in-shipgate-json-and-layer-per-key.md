---
type: adr
title: "0028. Settings live in shipgate.json and layer per key"
created: 2026-11-23
updated: 2026-11-23
tags:
  - adr
  - shipgate
  - config
status: accepted
date: 2026-11-23
issue: "#60 (shipgate), batch 3 prerequisite of #37"
related:
  - "0018-config-layers-resolve-per-section-nearest-first.md"
  - "0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md"
  - "0022-the-context-nudge-rides-the-posttooluse-bash-hook.md"
  - "0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "../prd/config-split.md"
  - "../prd/config-split.worklog.md"
---

# 0028. Settings live in shipgate.json and layer per key

> Each value from a fixed set moves out of `shipgate.md` into the settings file
> `shipgate.json`. A versioned schema checks it, the layers resolve it per key, and one
> command prints it with its source. `shipgate.md` keeps behaviour in words. Legacy lines
> keep working until a grace date 60 days after the migration release.

The user decided the seven forks through the lead on 2026-11-23: J2, a grace date in
place of G's release counts, K2, L1, S1, M2 and D1. The rest was decided in executive
mode, and the user did not veto it.

## Context

The PRD (`../prd/config-split.md`) states the problem. The terms are the PRD's: a
**setting** is one key of a **settings file** (`shipgate.json`); the **config** is
`shipgate.md`; a **legacy line** is a setting that a config still writes as a bullet.

### Readers today

Each row is one value that this change moves or may move. "Missing" and "Wrong" say what
the reader does today. Skill lines are `SKILL.md` lines of `shipgate/skills/<name>/`.

| Value today | Readers (file:line) | Missing | Wrong | Hook path |
| --- | --- | --- | --- | --- |
| sidecar `db` | `hooks/_common.py:249`-`278` (`sidecar_db_path`), `:289` (`Project.db_path`), `:426` (`run_journal`); `hooks/reply.py:222`; `scripts/_journal/project.py:93` (`resolve_db`), `:138`; `_journal/doctor.py:31` | `.claude/shipgate.db` beside the sidecar | not a string: the default | every event of a journaled project |
| sidecar `ledger` | `_journal/project.py:147` (`ledger_summary`); `_journal/doctor.py:161` | `docs/ledger.md` | not a string: the default | no |
| sidecar `artifact_homes` | `hooks/_common.py:305` (`artifact_globs`), `:323` (`covers`), `:369` (`watch_paths`); `hooks/post_tool_use.py:259`, `:303`, `:367`; `hooks/session_start.py:229`; `hooks/file_changed.py:56`; `_journal/project.py:186`; `_journal/doctor.py:164`; `shipgate-hud/hooks/journal.ts:977`, `register.tsx:446`, `:1104` | hooks: no globs, so nothing is captured; journal and HUD: the defaults, key by key | a home that is not a string is skipped; an `artifact_homes` that is a string raises in the hooks, and `safe_main` turns that into exit 0 | PostToolUse, SessionStart, FileChanged |
| sidecar `enforce` | `hooks/_common.py:310` (`enforces`); `hooks/stop.py:98` (`stop_gate`); `hooks/post_tool_use.py:287`, `:365` and `hooks/file_changed.py:48` (`auto_capture`); `hooks/pre_tool_use.py:1737` (`command_gate`) | on | any value but `false` is on | Stop, PostToolUse, FileChanged, PreToolUse on a gated command |
| sidecar `version` | `hooks/_common.py:80`; `hooks/session_start.py:226`; `_journal/project.py:64`, `:72`; `_journal/doctor.py:39`; `shipgate-hud/hooks/journal.ts:966`, `views.tsx:1266` | silent | an integer above 1: one warning, the known keys are still read | SessionStart |
| Autonomy `Mode` | `feature:29`, `:46`; `clarify:17`, `:87`; `design:77`; `setup:57`; `_journal/handoff.py:29` quotes the whole section | `ask` | not stated; the model guesses | no |
| Orchestration `review`, `explore` | `review:195`, `:289`; `feature:129`, `:150`; `setup:68` | `agents` | any word but `workflow` reads as `agents` | no |
| Writing style `Docs` | `design:115`, `:134`; `clarify:102`; `structured-debug:210`; `knowledge-base:91`, `:137`; `review:428`; `implement:34`; `model-tiers:115`, `:180` | `plain` | not stated; reads as `plain` | no |
| Code tooling `Code graph` | `scripts/signals.py:250`, `:345`-`351`; `route-and-map:101`; `model-tiers:153`; `feature:107` | `auto` | `signals.py` stops with a usage error that names the file | no |
| Code signals (4 keys) | `scripts/signals.py:209`, `:339` | the built-in window, pattern and excludes | dropped with no message: the default applies | no |
| Session `Handoff` | `_journal/handoff.py:329`, `:347`, `:373`, through `journal.py nudge` from `hooks/_nudge.py:172` | 500k | the default, 500k | PostToolUse, only after a phase-boundary append |
| Forge & tracker `Forge` | `_journal/closeout.py:334`, `:482`, `:578`, `:820` | the PR URL's host, else none | none | no |
| Knowledge base homes, `Ledger` | `clarify:105`; `design:31`, `:120`, `:137`; `feature:38`; `commands/shipgate.md:37`; `knowledge-base:97`, `:116`; `implement:110`; `review:497`; `structured-debug:174`; `_journal/doctor.py:121` (drift) | `docs/prd/`, `docs/adr/`, `docs/ledger.md` | prose | no |
| Journal `Database` | 10 skills test only that the section exists (`route-and-map:36` and the others); no script parses it | un-journaled | not read | no |
| `Inherit` | `scripts/_config.py:272`, `:375`; `scripts/signals.py:354`; `scripts/lean_config.py:808`; `_journal/doctor.py:201` | `umbrella` | any word but `none` is `umbrella` | no |

Twenty eval fixtures write a setting into `shipgate.md`: cases 15-17, 51, 52, 54, 55, 58-67,
74, 75 and `two-turn`. Seven of them (15-17, 51, 52, 54, 55) set `Mode: executive` in a
project with no journal. The config callout that cites ADR 0018 stands in 11 files
(10 skills and `commands/shipgate.md`), and `tests/test_prose.py:116` pins it.

### What a hook pays

A hook in a project with no sidecar does one `stat` per directory level and exits. It
reads no file and imports no `json` (`hooks/_common.py:2`-`19`, `:111`). Measured on this
machine: `import json` costs about 9 ms cold, and an open, read and parse of a 276-byte
sidecar costs about 65 µs. A journaled project already pays both on every event.

Two walks find the sidecar: `journaled_root` (`hooks/_common.py:111`) for every Python
hook and script, and `sidecarAbove` (`shipgate-hud/hooks/register.tsx:292`) for the HUD.
Both stop at the first `.claude/shipgate.json` above the working directory. A user
settings file named `$CLAUDE_CONFIG_DIR/shipgate.json`, with the variable unset or set to
`~/.claude`, is on that walk for every project under the home directory. Every such
project would then read as journaled.

## Decision

1. **One home.** A setting lives in the settings files only. `shipgate.md` keeps
   behaviour in words. The settings are `version`, `db`, `ledger`, `artifact_homes`,
   `enforce`, `autonomy`, `orchestration` (`review`, `explore`), `writing_style`,
   `code_graph`, `code_signals` (`window_months`, `fix_pattern`, `exclude`,
   `ranking_exclude`), `handoff` and `forge` (K2).
2. **One schema.** `shipgate/settings.schema.json` names each key with its type, its
   allowed values or range, its default, its scope (`project` or `any`), the release that
   added it and, for a key with a legacy line, the config section and bullet it comes
   from. Its `x-version` is 2, the one version number; a test pins the hooks' and the
   HUD's copies to it. The reader in `scripts/_config.py` checks a value against the
   schema with the standard library only.
3. **One resolver.** `scripts/_config.py` returns each key's value, its source and the
   problems it found. Per key, nearest first: the project settings file, a project-side
   legacy line, the user settings file, a user legacy line, the default (L1). A
   `project`-scope key in the user settings file is ignored and reported. A legacy line
   resolves by ADR 0018's per-section owner, then its bullet, so it gives today's value.
   `journal.py config` prints the result. `signals.py`, `journal.py nudge`, `handoff`,
   `closeout`, `sweep`, `status` and `doctor` call it.
4. **A bad value (S1).** In a settings file, a value outside its set stops `journal.py
   config`, `signals.py`, `handoff`, `closeout` and `sweep` with exit 2, naming the file,
   the key, the value and the allowed values. The commands that a hook runs (`status`,
   `nudge`, `append`) use the default and name the key in the brief. A legacy line with a
   bad value is ignored and named, so the first run after the update still works. An
   unknown key and a newer `version` are warnings.
5. **The journal marker (J2).** A `.claude/shipgate.json` marks the project root, as
   today. `"db": null` declares no journal: `load_project` in the hooks returns no
   project, the journal commands that need a database exit 1 and say why, and the HUD
   shows no journal view. A settings file below a project root is an error that `doctor`
   and `setup` name. A missing `db` key keeps today's default database.
6. **Hooks read the project file only.** They keep reading `db`, `artifact_homes` and
   `enforce` from the nearest settings file. No hook script reads the user settings file,
   `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else `~/.claude/`), whose name no walk
   finds. `journal.py nudge`, which the PostToolUse hook runs, resolves `handoff` through
   the resolver, the user settings file included, as it reads the user `shipgate.md`
   today. The user accepted this on 2026-11-23 (review round 1 of PR 1, F12). The no-op
   path of a project with no shipgate files is unchanged.
7. **What the model is told (M2).** The status brief carries one settings line:
   `autonomy`, `orchestration`, `writing_style` and `code_graph`, each with a short
   source. A skill reads that line, or runs `journal.py config <key>` for any other key,
   or when there is no brief. Exit 2 from the command means: show its message and stop.
8. **The grace date (G).** `x-legacy-until` in the schema is the one constant. It is null
   until the release that ships the migration sets it to that release day plus 60 days.
   While it is null, legacy lines are the normal form, and nothing is said. Once it is
   set, the brief of a project with legacy lines carries one line: their count, the date
   and `/shipgate:setup` to move them. After the date the reads go on, and the line says
   that the grace has ended and that the next release stops reading them. No value
   changes on a calendar day. The first release after the date removes the legacy read.
   `doctor`'s detection of legacy lines and `setup`'s move mode stay, so a late user is
   still told and moved.
9. **The drift check goes (D1).** `doctor`'s settings report replaces it: bad values,
   unknown keys, `project`-scope keys in the user file, legacy lines, settings files below
   a project root, and the grace date.

## Forks the user decided

The options as they went to the user. The chosen one is marked.

### J. What marks a project as journaled

Today the presence of `.claude/shipgate.json` marks a journaled project, and its directory
is the project root for the hooks, the journal and the HUD.

- **J1. Presence stays the marker. No other settings file at project level.** Zero change
  to the hooks and the HUD. Cost: a project with no journal cannot hold project settings.
  Its settings come from the user file and the defaults. The seven eval cases with
  `Mode: executive` and no journal move it into the user settings file of the eval
  sandbox. A nested repo in an umbrella cannot override a setting for itself.
- **J2. Presence marks the project root; `"db": null` declares no journal (recommended,
  chosen).** The walk is unchanged. `load_project` returns no project when `db` is null,
  so every hook exits as on an un-journaled project. Cost: a small change to what makes a
  hook act, so the hooks take the full `/security-review`. A project with no journal and a
  settings file pays `import json` and one parse, about 9 ms, on each hook event. An older
  shipgate reads `"db": null` as the default database, so it treats that project as
  journaled. `doctor` and `setup` refuse a settings file below a project root, because the
  walk would stop there.
- **J3. The marker is a settings file that names a journal.** Both walks read and parse
  each settings file they meet and go on past one with no `db`. A nested repo can then
  hold its own settings. Cost: a hook-contract change in Python and TypeScript, with the
  full `/security-review`. A project whose nearest settings file has no journal pays
  about 9 ms per hook event. In a team with mixed versions, an older shipgate stops at the
  nested file and opens a second journal there.

### G. Migration and the grace period

- **G1. Legacy lines are read for two minor releases after the release that ships the
  migration (recommended; the user chose a date instead, see below).** Per key: a settings
  file beats a legacy line at the same layer, and the nearer layer wins. On the first run
  after the update, every setting resolves as before. `journal.py config` prints the
  source `legacy shipgate.md`. The SessionStart brief of a journaled project adds one
  line: the count of legacy lines and `run /shipgate:setup to move them`. `setup` moves
  them and shows the diff first. Cost: the resolver carries the legacy path for two
  releases, then a release removes it.
- **G2. The same, for one minor release.** Less time in two modes. Cost: a user who
  skips a release loses settings with no warning in the release they skipped to.
- **G3. Hard cut.** The new release ignores legacy lines. Each one falls to its
  default until `setup` runs: `executive` becomes `ask`, `workflow` becomes `agents`,
  `ste-80` becomes `plain`. SessionStart says so in one line. Cost: an installed project
  changes behaviour on its first run after an update. This repo's config lists that as an
  extra escalation.
- **The user's answer (chosen): a grace date.** Release numbers move fast, so the grace
  is time, not a count: legacy lines are read for at least 60 days after the release that
  ships the migration, the first release after that date removes the read, and the
  SessionStart line names the date. The rest of G1 stands. Decision item 8 holds the
  mechanism.

### K. Which values become settings

- **K1. The issue's list.** `autonomy` (Mode), `orchestration.review`,
  `orchestration.explore`, `writing_style`, `code_graph`, `code_signals` (`window_months`,
  `fix_pattern`, `exclude`, `ranking_exclude`), `handoff`, and the keys the sidecar holds
  today: `db`, `ledger`, `artifact_homes`, `enforce`. Cost: `closeout.py:334` keeps a regex
  over the Forge prose.
- **K2. K1 plus `forge` (`github` or `gitlab`) (recommended, chosen).** The close-out and
  the sweep read it from the resolver, and the regex goes. The rest of Forge & tracker
  stays prose. Cost: one more key to migrate; `setup` already detects the forge.
- **K3. K2 plus `design_ahead` (a number).** Only `feature:312` reads it, and no eval sets
  it. Cost: one more key for a hint that the model reads once per epic.

### L. Layering, scope and the user settings file

- **L1. Per key, nearest first, with a scope rule (recommended, chosen).** Layers: the
  project settings file, the user settings file, the default. Objects (`orchestration`,
  `enforce`, `code_signals`, `artifact_homes`) merge per leaf key. A `project`-scope key
  (`db`, `ledger`, `artifact_homes`, `enforce`, `code_signals`, `forge`) in the user file
  is ignored, and `doctor` names it: else one line could switch off the commit gate or
  share one journal across every project. The user file is
  `$CLAUDE_CONFIG_DIR/shipgate.settings.json`, else `~/.claude/shipgate.settings.json`, a
  name no walk finds. `Inherit: none` stays in the config title, for the prose layers
  only. With J3, the umbrella's file is a layer between the two, and `inherit` moves into
  the settings file and governs both stacks.
- **L2. Per group, as ADR 0018 does per section.** A layer that sets any key of
  `orchestration` supplies the whole object. Cost: to change `review` alone, a project
  copies `explore` too.
- **L3. Per key, with no scope rule.** The user file may set any key. Cost: a user file
  with `enforce.command_gate: false` turns off the commit gate in every project.

### S. Schema, version and a value outside the set

- **S1. Version 2; a bad value stops the reader; hooks use the default (recommended,
  chosen).** `journal.py config`, `signals.py` and every journal command that reads the
  key exit 2 and print the file, the key, the value and the allowed values. A hook takes
  the key's default (each `enforce` switch stays on), and SessionStart names the key once.
  An unknown key is a warning, never a refusal, so an older reader survives a newer file.
  A higher version warns and reads the known keys, as today. Cost: a typo stops
  `signals.py` and the commands until it is fixed. The HUD must know version 2 in a
  release that ships with this one, or it shows its "newer version" warning.
- **S2. Version 2; a bad value warns and falls back to the default everywhere.** This is
  how the handoff threshold and Code signals behave today. Cost: a typo such as
  `"autonomy": "exec"` silently runs every gate in `ask` mode.
- **S3. Keep version 1 and add the keys.** No HUD release needed. Cost: an older reader
  ignores the new keys with no warning, and the version says nothing about the file.

### M. What the model is told

- **M1. One command.** `journal.py config [KEY ...] [--json]` prints `key = value
  (source)`. Every skill that reads a setting runs it at the step that needs the value.
  The config callout in 11 files names it. Cost: about one Bash call per phase that reads
  a setting, 3 to 5 per flow.
- **M2. M1 plus one settings line in the status brief (recommended, chosen).**
  SessionStart's brief prints the settings that skills read: `autonomy`, `orchestration`,
  `writing_style`, `code_graph`, each with its source. Skills read the line and run the
  command only for a key the line lacks, or with no brief. Cost: about 30 tokens per
  session start and per `/compact`. A project with no journal gets no brief and uses the
  command.
- **M3. The skills read the settings files themselves.** No command. Cost: each skill
  restates the layering and the scope rule, and the model applies them by hand.

### D. The drift check in `doctor`

- **D1. Delete it (recommended, chosen).** With one home there is nothing to compare.
  `doctor`'s `config` block reports instead: each value outside its set, each unknown key,
  each `project`-scope key in the user file, each legacy line and each settings file below
  a project root. `setup` update mode reads that block in place of `config.drift`. Cost:
  16 config-report tests in `tests/test_journal_doctor.py` (`:125` to `:372`) go, and new
  tests replace them.
- **D2. Keep it through the grace period.** It compares legacy lines with the settings
  file, then goes. Cost: two mechanisms for one release window; D1 already lists every
  legacy line.

## Decided in executive mode

The user can veto any of these.

- The terms: setting, settings file, config, legacy line (PRD, Terms).
- The settings file is hand-editable and validated on read. `setup` still writes it.
  There is no `config set` command.
- The keys that exist today keep their names and shapes: `version`, `db`, `ledger`,
  `artifact_homes`, `enforce`. The HUD and an older shipgate keep reading them.
- The schema is one JSON file in the plugin. The Python reader and the HUD contract test
  read the same file. A key added later, such as #25's publish quiz, is one schema entry.
- `journal.py config` needs no database. It runs in a project with no journal.
- The handoff brief prints the resolved `autonomy` and its source beside the prose
  Autonomy section (PRD FR-015).
- With no `python3`, a skill reads the project and user settings files itself, nearest
  first per key. The config callout says so in one sentence.
- A legacy line with a value outside its set is ignored and named, not refused. Before
  this change, only a bad `Code graph` stopped a reader; now none does on the legacy path.
- The commands a hook runs (`status`, `nudge`, `append`) never exit 2 on a setting.
- A legacy line resolves by ADR 0018's per-section owner, with no scope rule, so a
  section that hid a farther bullet still hides it.
- ~~`ledger` and `artifact_homes` get no legacy read: the settings file holds them already.
  `setup` removes their config bullets after it shows any difference.~~ Corrected by the
  user on 2026-11-24 (PR 3, review round 1, Q1 = B): that holds only where the settings file
  sets them, and a project with no journal has no settings file. So `artifact_homes.prd`,
  `.adr`, `.worklog` and `ledger` get a legacy read for repo paths until the grace date,
  from the `PRD home`, `ADR home`, `Worklog home` and `Ledger` bullets of the config's
  Knowledge base section, below the project settings file like every legacy line. The
  skills (`journal.py config`) then keep the custom home; the hooks and `status` still read
  the settings file only. A home that names no repo path (a wiki) gives no value and stays
  words, and the skills say so in one sentence. `setup` removes a home bullet only when the
  key resolves to the same value without it; for every other one it shows the difference
  and asks.
- The schema file is JSON Schema 2020-12, with `x-` annotations for the scope, the release,
  the legacy source, the version and the grace date. The validator in `_config.py` reads
  the subset it uses, in the style of `_journal/shapes.py:171`.
- `lean_config.py --move-settings` moves legacy lines, with the same diff-then-`--apply`
  gate as the boilerplate pass and the resolver's legacy reader.
- The status brief resolves the settings from the project root, so no hook file changes
  for it. `journal.py config` resolves from the working directory.
- No architect fan ran: the seven answers left one approach.
- Added in the build of PR 1 (review round 1): the walk stops at the first layer that
  decides a key. A value outside its set in a settings file decides it (the default),
  so a bad value in the user settings file never hides a valid project value. A settings
  file that is not a JSON object, or not UTF-8, is skipped. A strict reader refuses
  (exit 1) only a key whose walk reached that file; `signals.py` names it and goes on.

## Alternatives considered

The forks above hold the alternatives for each open choice. Two more were rejected
outright:

- **Generate `shipgate.md` sections from the JSON.** A read-only mirror keeps one source,
  but the model then reads two copies, and the drift check stays. Rejected.
- **Keep markdown and give every script a typed markdown parser.** This removes no reader
  and keeps the per-section rule for values that want a per-key rule. Rejected.

## Consequences

- The build ships in three PRs (worklog, Build Plan): the reader; the journal marker with
  the HUD release that knows version 2; the migration with the skill text and the evals.
  Each is a minor bump of shipgate with its tag. The second also bumps shipgate-hud, which
  declares that shipgate release as its floor, and it takes a separate merge question.
- Every skill that names a setting changes its text, so the build runs the evals of those
  skills on Opus and on Fable.
- The legacy read is dead code after the grace date. The first release after the date
  removes it and its tests; a follow-up issue, opened with the migration release, tracks
  it.
- A nested repo in an umbrella loses its own Code signals and Code graph values: they
  move to the project settings file and apply to every repo.
- An older shipgate reads `"db": null` as the default database. A team with mixed
  versions sees the older hooks treat a journal-less project as journaled.
- Two builders of the markdown layer list exist today (`scripts/signals.py:294` and
  `scripts/_journal/project.py:209`), and they find umbrellas by different rules. This
  change does not merge them. A follow-up issue should.
