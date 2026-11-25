---
type: worklog
title: "Worklog: A UI task is done with screenshots"
created: 2026-11-25
updated: 2026-11-25
tags:
  - worklog
  - shipgate
  - verify
  - ui
status: in review
prd: "./ui-visual-evidence.md"
issue: "#26 (shipgate), child of #37"
related:
  - "../adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "../adr/0030-the-publish-digest-is-computed-and-rides-the-publish-question.md"
---

# Worklog: A UI task is done with screenshots

> Design + build plan companion to `./ui-visual-evidence.md`. The decision record is
> ADR 0031.

## Start of the build

- **Worktree:** `pandora.worktrees/feat-26-ui-visual-evidence`, branch
  `feat/26-ui-visual-evidence`. Run every command from there.
- **Wait for #25.** #25 ships first as shipgate 0.35.0 with `journal.py digest`. This build
  starts after #25 is merged. T001 rebases this branch on `origin/main` then.
- **The design artifacts are uncommitted.** The PRD, ADR 0031 and this worklog are untracked
  files. `git rebase origin/main` keeps them. Do not stash them, and never run
  `git checkout` on them.
- **Version:** shipgate 0.36.0. No file under `shipgate/hooks/` or `shipgate-hud/` changes,
  so the publish takes one approval.
- **Tests:** `python3 -m unittest discover -s shipgate/tests` from the repo root.

---

# Design

## Approach

Inline design, no architect fan: the open space was product behaviour, and the user
decided its seven forks (ADR 0031). The core trade-off: the files on disk are the record,
so the journal gets no new field and the gate observes the evidence itself; the cost is a
file side effect in `append` after a terminal event, bounded by strict delete rules.

## Architecture

| Part | Where | What it does |
| --- | --- | --- |
| Settings | `settings.schema.json`, `_config.py` | the `ui` group: `globs`, `widths`, `capture`; `_valid` gains `minItems` |
| UI function | `scripts/_ui.py` (new) | `is_ui(path, globs)`, `png_width(path)`, `match_width(px, widths)` |
| Plan paths | `_journal/artifacts.py` | `plan_paths(text)` and `ui_tasks(text, globs)` over the Build Plan region and `_PLAN_TASK_RE` |
| Evidence store | `_journal/screens.py` (new), `cli.py` | the root, the project key, the layout, register, print, list, prune |
| Gates | `_journal/gates.py`, `vocab.py` | the UI branch of `_validate_task_done`; `_validate_design_committed`; `screens-waived` in `_validate_waiver`; `SCREENS_WAIVED`, `EVIDENCE_KEEP_DAYS` |
| Terminal prune | `_journal/append.py` | after `COMMIT` of `flow-completed` or `flow-abandoned`, prune that stream |
| Doctor | `_journal/doctor.py` | the evidence lines |
| Handoff | `_journal/handoff.py` | `[UI]` on the next task and one rule line |
| Map | `signals.py`, `vocab.py` | `ui` in `hotspots --json`; `ui` true or false on `phase-entered` |
| Digest | #25's digest module | the "Screens" part |
| Skill text | 7 skills and the worklog template | the rule, the reason and the commands |

### `scripts/_ui.py`

Stdlib only, Python 3.9.

- `is_ui(path, globs) -> bool`: true when `path` matches a glob by the artifact-home rule:
  `fnmatch(path, glob)` or `fnmatch(path, "*/" + glob)` after a leading `./` is dropped
  (`artifacts.py:233-241`). An empty list gives false.
- `png_width(path) -> int`: reads 24 bytes. The first 8 must be the PNG signature
  `89 50 4E 47 0D 0A 1A 0A`, bytes 12 to 16 must be `IHDR`, and bytes 16 to 20 are the
  width, big-endian. Anything else raises `ValueError` with the reason ("not a PNG",
  "truncated").
- `match_width(px, widths) -> List[int]`: the set widths w with `px` in `{w, 2w, 3w}`.

### Plan paths in `artifacts.py`

- `plan_paths(text) -> List[PlanPaths]`, each `{id, line, paths, error}`. It walks the same
  Build Plan region and `_PLAN_TASK_RE` as `parse_build_plan`, so the grammar stays one.
  On a task line, the `file(s):` part runs from `file(s):` to the next spaced em or en dash
  or the end of the line. `paths` is every backticked token in it. When there is none and
  the part starts with `none`, `paths` is `[]`. When the line has no `file(s):` part, or the
  part has no backticked token and is not `none`, `paths` is null and `error` says which.
  `line` is the 1-based file line.
- `ui_tasks(text, globs) -> Dict[str, bool]`: per task id, whether a path is UI. A
  repeated id takes its first line, as `build_position` does.

### Settings

```json
"ui": {
  "description": "Visual evidence for UI tasks (ADR 0031). An empty globs list turns it off.",
  "type": "object",
  "properties": {
    "globs":   {"type": "array", "items": {"type": "string", "minLength": 1}, "default": []},
    "widths":  {"type": "array", "items": {"type": "integer", "minimum": 200, "maximum": 4000},
                "minItems": 1, "default": [390, 1280]},
    "capture": {"type": ["string", "null"],
                "pattern": "^(?=.*\\{url\\})(?=.*\\{width\\})(?=.*\\{out\\}).+$",
                "default": null,
                "x-allowed": "a command with {url}, {width} and {out}, or null"}
  },
  "x-scope": "project",
  "x-since": "0.36.0"
}
```

`_valid` gains `minItems` for a list. `_allowed` words it ("a list of at least 1 ...").

### The evidence store, `_journal/screens.py`

- **Root:** `$CLAUDE_CONFIG_DIR/shipgate/evidence`, else `$HOME/.claude/shipgate/evidence`.
  With neither variable, there is no root: the register command exits 2 with "no evidence
  root: set CLAUDE_CONFIG_DIR or HOME", and the gate's refusal says the same and offers the
  waiver.
- **Project key:** the first 12 hex digits of `sha256(realpath(db))`. This repo's worktrees
  link `.claude/shipgate.db` to the main checkout's journal, so they share the key.
- **Stream directory:** `urllib.parse.quote(stream, safe="-_.")`. A directory name is valid
  only when it equals `quote(unquote(name), safe="-_.")`.
- **File name:** `T<digits>-<w>.png`, then `T<digits>-<w>-<k>.png` for k from 2 to 9. A
  write goes to `.T<digits>-<w>[-<k>].png.<pid>.tmp` in the same directory and then
  `os.replace`.
- **`screens --stream S --task T --file F [--file F ...] [--width W]`:** refuses a stream
  with no events, a finished stream, a task id that is not `T<digits>`, a missing file, a
  file that is not a PNG, a width that matches no set width, and a width that matches two
  unless `--width` names one of them. On success it prints each stored path with its set
  width and pixel width, then the widths still missing for T, then a note when T is not a
  UI task. It prunes first (moments 2 and 3).
- **`screens --stream S --task T --url U`:** needs `ui.capture`, else exit 2 naming the
  setting. It creates the stream directory and prints one filled command per set width,
  with `{out}` the final file path. It runs nothing. It prunes first.
- **`screens --list [--stream S] [--json]`:** per UI task of the stream's worklog, in plan
  order: `present` (the set widths with a fresh file), `waived` (the reason), `missing`
  (the set widths). Read-only, no prune. The digest and the gate use the same function,
  `screen_state(conn, stream, project_dir)`.
- **`screens --prune`:** runs moments 2 and 3 on demand and prints the result. For a
  person who reads the doctor report; no flow step needs it.

### The cleanup

`prune_evidence(root, project_key, conn, stream=None, now=None) -> PruneReport` is the one
function. With `stream`, it prunes that stream's directory only (moment 1). Without it,
it prunes this project's directories of finished or unknown streams (moment 2) and every
file older than `EVIDENCE_KEEP_DAYS` in the root (moment 3).

The delete rules, each with a test (T009):

1. Resolve the root once with `os.path.realpath`. Work only on paths built under that
   resolved root; never resolve an entry inside it.
2. Read every entry with `os.lstat` (or `DirEntry.is_symlink()` before anything else). A
   symbolic link is refused, never followed and never removed.
3. Remove only the expected layout: a project directory matching `^[0-9a-f]{12}$`; a
   stream directory whose name round-trips the encoding; a regular file matching
   `^T\d+-\d+(-[2-9])?\.png$` or the temporary form `^\.T\d+-\d+(-[2-9])?\.png\.\d+\.tmp$`.
   Any other entry is refused and kept, and its directory then stays.
4. Remove files one by one with `os.unlink`, then empty directories with `os.rmdir`.
   Never `shutil.rmtree`.
5. Print one line per removed directory with its file count, one line per removed old
   file outside a removed directory, and one line per refused entry.
6. Catch `OSError` per entry: one warning line on stderr, then go on. The function never
   raises. Its caller's exit code and recorded event never depend on it.

Moment 1 is called in `append_event` right after `conn.execute("COMMIT")` when the type is
`flow-completed` or `flow-abandoned`, beside `_touch_request_marker` (`append.py:239-241`),
inside a `try` that turns any exception into one stderr line. Its output goes to stderr, so
`append`'s stdout stays as it is.

### The gate

`validate_gate` passes `project_dir` to `_validate_task_done`. After today's check passes:

1. Read `ui.globs` for the project. Empty: return.
2. Find the stream's newest `design-committed` and resolve its `worklog`. No event, or a
   file the script cannot read: return (no task is UI).
3. `ui_tasks` on the worklog. The task is not UI: return.
4. A `deviation` with `kind: screens-waived`, a real reason and the task id in `task_ids`
   exists on the stream: return.
5. For each width w of `ui.widths`: a regular file `T-<w>.png` or `T-<w>-<k>.png` in the
   stream directory, not a link, with an mtime after the `design-committed`'s time, whose
   `png_width` is in `{w, 2w, 3w}`. All present: return.
6. Refuse: the missing widths, the register command, the capture command when `ui.capture`
   is set, and the waiver command, each with the stream and the task filled in.

`_validate_design_committed`, new in `validate_gate`: with `ui.globs` set and the worklog
readable, every `plan_paths` item with an `error` refuses the event with
`<worklog>:<line>: <task> <error>`. An unreadable worklog prints one warning line and
passes.

`_validate_waiver` treats `screens-waived` as it treats `gate-waived`: a non-empty
`task_ids` and a reason that is not empty or a `<...>` placeholder. `check.py` keeps
reading `gate-waived` only, so a `screens-waived` clears no Stop-gate finding.

### Doctor

Under the existing sections, an `evidence` block:

```text
evidence root : <path> (this Claude config directory)
  this project : <key> · <n> streams · <files> files · <size> · oldest <d> days
  whole root   : <projects> projects · <files> files · <size> · oldest <d> days
  next prune   : <n> directories of finished or unknown streams · <n> files over 30 days
  refused      : <n> entries outside the layout (first: <path>)
  note         : another Claude config directory or another machine keeps its own root,
                 which this report does not read
```

With no root on disk: `evidence root : <path> (none yet)`. With no config directory and no
home: `evidence root : none (no CLAUDE_CONFIG_DIR, no HOME)`. Doctor deletes nothing.

### Handoff

When the next task is UI: `next: T004 [UI] — <title>` and one line under the rules that
bind:
`UI task: register screenshots at 390, 1280 before task-done (journal.py screens --stream <s> --task T004 --file ...), or record screens-waived with the reason`.
Nothing changes for a task that is not UI.

### Map

`signals.py hotspots --json` gains a top-level `ui`: null when `ui.globs` is empty;
otherwise `{"files": <n>, "sample": [<up to 3 paths>]}` over the touched files of the
population it already scanned. The `phase-entered` shape gains `"enums": {"ui": [true,
false]}`. Route-and-map records `"ui": true` when `files` is above 0, `false` when it is 0,
and nothing when `ui` is null.

### The digest part

On #25's ordered list of parts, after "Deviations" and before "Look here first":

```text
Screens (<evidence directory>)
  T003 — 390, 1280
  T004 — waived: no browser tool in the worker session
  T005 — missing 1280
```

Slot 3 item lines, plan order. Over the slot, the part names its full count and `--all`.
No UI task: the part is absent. The cap grows from 16 to 20 lines. `--json` gains
`screens`: the `screen_state` list.

### Skill text

Each sentence gives the reason, not one more absolute rule.

- **verify**, the Claim → evidence table: one row, "UI task done (the project sets
  `ui.globs`) | a registered screenshot for every width in `ui.widths`
  (`journal.py screens --list`), read by the one who took it, or a `screens-waived`
  deviation with the reason". In "Record the evidence", one paragraph: a UI task's command
  can pass while its screen is wrong, so its `task-done` also needs the screenshots. Take
  them with the browser tool you have; register them with
  `journal.py screens --stream <s> --task <T> --file <png>...`; read them and compare them
  with the PRD's reference. With `ui.capture` set, `--url <url>` prints the commands to
  run. With no browser tool, the refusal prints the waiver: write the real reason, because
  the user reads it at the publish gate.
- **implement**, step 6: for a task the handoff marks `[UI]`, the verify gate includes the
  screenshots (see `verify`).
- **design**, the Build Plan rule: with `ui.globs` set, each task line names its paths in
  backticks after `file(s):`, or says `file(s): none`. `design-committed` refuses another
  form, because the gate computes a UI task from those paths.
- **worklog-template.md**, the Build Plan paragraph: the same rule in one sentence.
- **model-tiers**, item 4: for a UI task, the brief adds the widths, the register command
  and the step to read the screenshots and compare them with the reference before the
  report; the report lists the registered files.
- **route-and-map**: the map line drops `UI` (`read | write | schema`); a line "UI: <n>
  touched files match `ui.globs`" shows when the JSON's `ui` is not null; the record
  example carries `"ui": true`.
- **clarify**, the UI paragraph: "When the impact map's `ui` is true (computed from the
  `ui.globs` setting)" replaces "When the map tags a touched module `UI`".
- **setup**: when the detected shape has a web frontend (HTML templates, style sheets, or a
  component framework in the dependencies), the interview offers `ui.globs` with the
  matching globs as the recommended answer. A project with no frontend gets no question.

## Data flow

1. Route-and-map: `signals.py hotspots --json` → `ui` → `phase-entered.ui` → clarify's
   reference candidate.
2. Design: the Build Plan's `file(s):` paths → `design-committed` checks the form.
3. Implement: the taker takes PNGs → `journal.py screens --file` → the evidence directory
   → the taker reads them → `verify-run` and `task-done` in one batch → the gate reads the
   worklog, the settings and the files.
4. Review: `journal.py digest` → "Screens" part → the publish question's preview.
5. End: `flow-completed` or `flow-abandoned` → `append` prunes the stream's directory.
   Every register prunes finished and unknown streams and files over 30 days.

## Data model / schema

No journal schema change and no new event type. New: three settings, the waiver kind
`screens-waived`, the `ui` key on `phase-entered`, and the evidence layout on disk
`<root>/<12-hex project key>/<encoded stream>/T<n>-<w>[-<k>].png`.

## API / contract changes

- `journal.py screens` (new subcommand).
- `journal.py digest`: the "Screens" part and the `screens` JSON key; cap 20 lines.
- `journal.py doctor`: the evidence block.
- `journal.py handoff`: `[UI]` and one rule line, only for a UI task.
- `signals.py hotspots --json`: top-level `ui`.
- `append`: `task-done` and `design-committed` refuse more in a project with `ui.globs`;
  a terminal event prunes files. A project without `ui.globs` sees no change.
- The model's `UI` tag in the impact map goes.

## Reference implementation

- **The gate reading an artifact:** `_validate_clarify_passed` (`gates.py:30-50`): it
  resolves the PRD with `_resolve_artifact`, reads it, and refuses with the path. Proven
  since 0.8.0.
- **A strict parser that names the line:** `_journal/assumptions.py` (#24). `plan_paths`
  follows its error form `<file>:<line>: <reason>`.
- **A setting with a project value and a bad value:** `clarify_confirm` in
  `settings.schema.json` and `test_settings.py:1224-1234`.
- **A post-commit side effect:** `_touch_request_marker` in `append_event`
  (`append.py:239-241`).
- **A waiver:** `_validate_waiver` and `_waived_task_ids` (`gates.py:264-282`,
  `check.py:60-68`).
- **A digest part:** the parts of #25's digest module, as #25's worklog names them.

## Risk ranking

`signals.py hotspots` over the existing files the plan changes (source `graph`): the top 5
are `shipgate/README.md` (churn top, fix high), `skills/implement/SKILL.md`,
`skills/model-tiers/SKILL.md`, `skills/design/SKILL.md` (churn top, fix low) and
`skills/clarify/SKILL.md` (churn top, fix mid). T019 and T021 pin the sentences of these
files that stay before they change them. T002 pins the script behaviour this change
touches.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/`. `shipgate-hud/` and `shipgate/hooks/` do not change.
- Public repo: tests build PNG files in code; no fixture holds a real screen, path or name.
  T022 greps the diff.
- A behaviour change bumps `shipgate/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json` to 0.36.0 in the same change, with a `CHANGELOG.md`
  entry; the README links to it and copies no entry.
- Python 3.9: no `match`, no runtime `X | Y`.
- Security-sensitive area: `screens.py` writes and deletes outside the plugin's own
  directory (`.claude/shipgate.md`). No hook file changes, so the approval path stays one
  publish approval, but the review briefs a security reviewer with the six delete rules of
  "The cleanup" and the post-commit call in `append.py`, and treats a delete outside the
  layout as a blocker.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings. Tests are tasks.
Each test task's "done when" means the tests fail first for the right reason; its
implementation task makes them pass.

## Setup

- [x] T001 — After #25 merges: rebase on `origin/main`, run the suite, read #25's digest module, its part list and its worklog note on adding a part — file(s): none — done when: the suite passes on the rebased branch, and the digest module's path, its test file and its part list are noted under Deviations & notes.
- [x] T002 — Pin today's behaviour this change touches: the refusal text of `_validate_task_done`, the handoff `tasks` line, the stdout and stderr of a `flow-completed` append, the doctor report without an evidence root, and the 16-line digest of a stream with no UI task — file(s): `shipgate/tests/test_journal_gates.py`, `shipgate/tests/test_journal_handoff.py`, `shipgate/tests/test_journal.py`, `shipgate/tests/test_journal_doctor.py`, and #25's digest test from T001 — done when: the pins pass on the unchanged code.

## Settings

- [x] T003 — Tests first: the `ui` group — `journal.py config ui` prints three leaves with `(default)`; a project file sets them; a user file gets the scope warning; `ui.widths: []`, a width of 100, and a `ui.capture` without `{out}` each exit 2 naming the key; `TABLE_KEYS`, `PROJECT_SCOPE` and the defaults table — file(s): `shipgate/tests/test_settings.py` — done when: the tests fail on the missing keys.
- [x] T004 — The `ui` group in the schema and `minItems` in `_valid` and `_allowed` — file(s): `shipgate/settings.schema.json`, `shipgate/scripts/_config.py` — done when: T003 passes and `test_settings.py` passes in full.

## UI function and plan paths

- [x] T005 [P] — Tests first: `is_ui` (an exact glob, a `*/` match, an empty list, a `.tsx` outside the globs), `png_width` (PNGs built in code with `zlib` and `struct`, a JPEG header, a truncated file), `match_width` (1x, 2x, 3x, none, two), `plan_paths` (backticked paths, `file(s): none`, no `file(s):` part, a part with no path, line numbers, a bold id) and `ui_tasks` — file(s): `shipgate/tests/test_ui.py` — done when: the tests fail on the missing functions.
- [x] T006 — `scripts/_ui.py` with `is_ui`, `png_width` and `match_width`; `plan_paths` and `ui_tasks` in `artifacts.py` on the Build Plan region and `_PLAN_TASK_RE` — file(s): `shipgate/scripts/_ui.py`, `shipgate/scripts/_journal/artifacts.py` — done when: T005 passes and `parse_build_plan`'s tests still pass.

## Evidence store

- [x] T007 — Tests first: the root (`CLAUDE_CONFIG_DIR`, `HOME`, neither), the project key (a linked database gives the main checkout's key), the stream encoding round trip, `--file` (a 780 px PNG stored as `T003-390.png`, a second as `T003-390-2.png`, each refusal of the design, no temporary file left after a refusal), `--url` (one printed command per width, nothing run, exit 2 without `ui.capture`) and `--list --json` (present, waived, missing) — file(s): `shipgate/tests/test_journal_screens.py` — done when: the tests fail on the missing command.
- [x] T008 — `_journal/screens.py` (root, key, layout, register, print, `screen_state`, list) and the `screens` subcommand — file(s): `shipgate/scripts/_journal/screens.py`, `shipgate/scripts/_journal/cli.py` — done when: T007 passes.

## Cleanup

- [x] T009 — Tests first: the prune removes a finished stream's directory and an unknown stream's directory and keeps a live one; it removes files older than 30 days anywhere in the root (mtime set with `os.utime`) and then the empty directories; it refuses and keeps a link to a file, a link to a directory outside the root, a file with another name and a directory with another name, and their parents stay; with a root that is a link, nothing outside the resolved root changes; an `OSError` on `unlink` prints a warning and returns; each removed directory prints with its count — file(s): `shipgate/tests/test_journal_screens.py` — done when: the tests fail on the missing prune.
- [x] T010 — `prune_evidence` in `screens.py` and `EVIDENCE_KEEP_DAYS = 30` in `vocab.py`; `--file`, `--url` and `--prune` call it — file(s): `shipgate/scripts/_journal/screens.py`, `shipgate/scripts/_journal/vocab.py` — done when: T009 passes.
- [x] T011 — Tests first: a `flow-completed` append removes the stream's directory and prints its line on stderr; a `flow-abandoned` does too; `sweep --apply` on a dormant stream does too; the close-out's printed `flow-completed` command does too; a prune that raises (patched) leaves exit 0 and the event recorded; a non-terminal append touches nothing — file(s): `shipgate/tests/test_closeout.py`, `shipgate/tests/test_journal.py` — done when: the tests fail.
- [x] T012 — The prune after `COMMIT` of a terminal type in `append_event`, beside `_touch_request_marker`, inside a `try` that turns any exception into one stderr line — file(s): `shipgate/scripts/_journal/append.py` — done when: T011 passes and T002's append pin still passes.

## Gates

- [x] T013 — Tests first, on the append CLI with a fixture project that sets `ui.globs` and a worklog with a UI task and a non-UI task: the UI `task-done` is refused with no file, refused with one width only, refused with a file older than the `design-committed`, accepted with 1x and 2x files for both widths, accepted with a `screens-waived`; the non-UI task passes; a `screens-waived` with no task id or a `<...>` note is refused; the Stop gate still reports a ticked box with no `task-done` when only a `screens-waived` names it; `design-committed` refuses a task line with no `file(s):` part (`<worklog>:<line>`), accepts `file(s): none`, warns and passes on an unreadable worklog; a project with no globs matches T002's pins — file(s): `shipgate/tests/test_journal_gates.py`, `shipgate/tests/test_journal_check.py` — done when: the tests fail.
- [x] T014 — `gates.py`: `project_dir` into `_validate_task_done` and its UI branch; `_validate_design_committed`; `screens-waived` in `_validate_waiver`; `SCREENS_WAIVED` in `vocab.py` — file(s): `shipgate/scripts/_journal/gates.py`, `shipgate/scripts/_journal/vocab.py` — done when: T013 passes and the full suite passes.

## Doctor, handoff and map

- [x] T015 [P] — Tests first, then the doctor's evidence block for a root with files, an empty root, a missing root and no config directory, with the other-root note — file(s): `shipgate/tests/test_journal_doctor.py`, `shipgate/scripts/_journal/doctor.py` — done when: the tests pass after failing first, and T002's doctor pin still passes.
- [x] T016 [P] — Tests first, then the handoff's `[UI]` mark and rule line for a UI next task — file(s): `shipgate/tests/test_journal_handoff.py`, `shipgate/scripts/_journal/handoff.py` — done when: the tests pass after failing first, and T002's handoff pin still passes for a task that is not UI.
- [x] T017 [P] — Tests first, then `ui` in `signals.py hotspots --json` (null with no globs; the count and up to 3 sample paths) and `ui` true or false on `phase-entered` — file(s): `shipgate/tests/test_signals.py`, `shipgate/tests/test_journal_shapes.py`, `shipgate/scripts/signals.py`, `shipgate/scripts/_journal/vocab.py` — done when: the tests pass after failing first, and another `ui` value is refused.

## Digest

- [x] T018 — Tests first, then the "Screens" part on #25's digest: its place, the heading with the evidence directory, one line per UI task, 3 item lines and the full count, absent with no UI task, at most 20 lines, and `screens` in `--json` from `screen_state` — file(s): #25's digest module and its test, as T001 notes them — done when: the tests pass after failing first, and T002's 16-line pin still passes.

## Skill text

- [x] T019 — Prose tests first: pin the sentences that stay in each file below, then add the sentences of the Design section's "Skill text" — file(s): `shipgate/tests/test_prose.py`, `shipgate/skills/verify/SKILL.md`, `shipgate/skills/implement/SKILL.md`, `shipgate/skills/design/SKILL.md`, `shipgate/skills/design/references/worklog-template.md`, `shipgate/skills/model-tiers/SKILL.md`, `shipgate/skills/route-and-map/SKILL.md`, `shipgate/skills/clarify/SKILL.md`, `shipgate/skills/setup/SKILL.md` — done when: the new prose tests fail first and then pass, and the pins pass before and after.

## Eval fixture

- [x] T020 [P] — Case 77: `"ui": {"globs": ["web/templates/*", "web/static/*"]}` in the fixture's `.claude/shipgate.json` — file(s): `shipgate/evals/77-clarify-ui-reference/fixture.sh` — done when: `bash fixture.sh` in a scratch directory builds the app, and `journal.py config ui.globs` run in that app prints the two globs from the project file.

## Release

- [x] T021 — README (the settings rows, the `screens` row, the doctor and verify text), `CHANGELOG.md` 0.36.0, the glossary (UI task, evidence root, `screens-waived`), version 0.36.0 in both manifests — file(s): `shipgate/README.md`, `shipgate/CHANGELOG.md`, `shipgate/docs/glossary.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: `test_prose.py` and `test_settings.py` pass, the two versions match, and the README links to the changelog without copying an entry.
- [x] T022 — Final verify and privacy check — file(s): none — done when: the full suite passes; a grep of the diff for private project names, tracker ids and checkout paths finds nothing; `git diff --stat origin/main -- shipgate/hooks shipgate-hud` is empty.

## The user's answers (after review round 2)

- [x] T023 — A regular file `.DS_Store` joins the layout in stream and project directories, and the 30-day pass also runs after `flow-started` — file(s): `shipgate/scripts/_journal/screens.py`, `shipgate/scripts/_journal/append.py`, `shipgate/tests/test_journal_screens.py`, `shipgate/tests/test_journal.py`, `shipgate/tests/test_journal_doctor.py`, `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md`, `shipgate/docs/prd/ui-visual-evidence.md`, `shipgate/README.md`, `shipgate/CHANGELOG.md` — done when: the new tests fail first and then pass, a fresh reviewer finds nothing above LOW, and the full suite passes under the real-root sentinel.

- [x] T024 — Fix review round 3's R1 to R4 (the lead's decision: documents only, no second reviewer) — file(s): `shipgate/CHANGELOG.md`, `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md` — done when: `test_prose` passes and the four sentences read as round 3 asks.

- [x] T025 — Keep the developer's evidence root out of the suite: the `--batch` helpers start `journal.py` with a shared isolated env, and three more modules get the real-root guard — file(s): `shipgate/tests/test_journal.py`, `shipgate/tests/test_journal_status.py`, `shipgate/tests/test_journal_digest.py`, `shipgate/tests/test_trace.py` — done when: each of the four modules leaves a planted sentinel unchanged, the guard fails with one fix reverted, and the full suite passes under the sentinel.

- [x] T026 — What changed item 3 names all three prune moments (the lead's request) — file(s): `shipgate/docs/prd/ui-visual-evidence.worklog.md` — done when: `journal.py digest` parses the section and prints the line.

## After the merge

These are not Build Plan tasks: they run on `main`.

- Tag the release: `claude plugin tag --push` in `shipgate/`.
- Run eval case 77 once on each session model with `.claude/skills/run-evals` (about 3.9 to
  5.4 USD). A fall changes clarify's UI sentence.
- Tick #26 in #37's task list.

## Traceability

- FR-001, FR-019 → T003, T004
- FR-002 → T005, T006, T013, T014, T016, T017, T018
- FR-003 → T005, T006, T013, T014
- FR-004 → T017, T019, T020
- FR-005, FR-006, FR-007 → T007, T008
- FR-008, FR-009, FR-010 → T013, T014
- FR-011, FR-017 → T019
- FR-012 → T018
- FR-013 → T011, T012
- FR-014, FR-015 → T009, T010
- FR-016 → T015
- FR-018 → T016
- FR-020 → T023 (and `.DS_Store` in the layout of FR-015)
- SC-001 → T005; SC-002, SC-003 → T007, T013; SC-004 → T009, T011; SC-005 → T015;
  SC-006 → T018; SC-007 → T022; SC-008 → T003; SC-009 → T019; SC-010 → after the merge;
  SC-011 → the #35 retro

## What changed

- A UI task (its Build Plan paths match the new `ui.globs` setting) is done only with a screenshot at each width, or a reason.
- `journal.py screens` registers the PNG screenshots, prints capture commands it never runs, and lists each UI task's state.
- The screenshots live outside every repository; when a stream starts or ends, or screens are registered, the journal deletes the stale ones.
- The publish digest shows the evidence directory and each UI task's widths or waiver reason; `doctor` reports the evidence root.
- A project without `ui.globs` sees no change, except that clarify asks for no UI reference.

## Deviations & notes (filled during implementation)

- 2026-11-25 — design: ADR number 0031 settled by the lead; #25 takes 0030.
- 2026-11-25 — T001: rebased on `origin/main` (shipgate 0.35.0). The suite ran 2121 tests:
  3 `test_settings` failures came from worker A's `ui` schema key, written while the run was
  going; `test_settings` passes on a clean export of `origin/main` (91 tests). #25's digest:
  module `shipgate/scripts/_journal/digest.py`, test `shipgate/tests/test_journal_digest.py`,
  parts `PARTS = What changed 3, Decided alone 2, Deviations 2` plus the Look first row, cap
  `max_lines()` 10. #25's note: a part is one `PARTS` entry with its slot, its items in
  `build_digest` and `DigestDoc`; the cap grows by the slot; change the pin in
  `test_the_row_cap_is_computed_from_the_slots`.
- 2026-11-25 — T002: the digest pin is the table of 0.35.0 (`TestPinNoUiDigest`), not a
  16-line text: #25 shipped the table form after this design was written.
- 2026-11-25 — deviation (T004): `ui.widths` words its refusal with `x-allowed` ("a list of
  at least one integer from 200 to 4000"), so `_allowed` gets no `minItems` branch; only
  `_valid` checks `minItems`. The README got the three `ui` rows here, because the prose
  test that lists every setting requires them; T021 keeps them.
- 2026-11-25 — deviation (T006): `is_ui` drops a leading `./` from the path and from each
  glob before both matches, and matches with `fnmatchcase`, so the rule is case-sensitive on
  every platform. `file(s): none` needs the word `none` (`none\b`): `file(s): nonexistent`
  is refused. `_build_plan_span` holds the region's offsets, so `plan_paths` counts lines in
  the whole file.
- 2026-11-25 — deviation (T017): `phase-entered` closes `ui` with a new shape rule kind
  `booleans` (`isinstance(value, bool)`), not an enum: in Python `1 == True`, so an enum
  would accept `1` and `0`. `hotspots --json` gives `ui` null when the signals are
  unavailable (no files were ranked, so the answer is unknown), even with globs set. The
  globs match repo-relative paths: in an umbrella, an umbrella-relative glob does not match
  a nested repo's path.
- 2026-11-25 — deviation (T019): setup adds `ui` to its list of project-scope keys (the list
  was out of date without it). Verify says that the files a `--url` capture command writes
  land in the evidence root and need no register step, and it asks for the viewport at the
  width in CSS pixels and a PNG file, because register needs a file. Route-and-map states
  the record rule: `ui` true when `ui.files` is above 0, false at 0, left out when null.
- 2026-11-25 — judged by reading (no eval in this PR): the verify paragraph orders take,
  register, read, then the `task-done` batch, and a prose test pins that order, so a literal
  reader (Fable) cannot read the screenshots after `task-done`. The waiver sentence gives the
  reason (the user reads it at the publish gate) instead of a rule, so an Opus session that
  could waive too easily meets the cost of a thin reason. Route-and-map maps the JSON to the
  record with no judgment call. Clarify keeps the design's words "the impact map's `ui` is
  true"; case 77 after the merge is the check (SC-010).
- 2026-11-25 — deviation (T008): the project key hashes the database path that SQLite
  reports (`PRAGMA database_list`), not `realpath(db)`. SQLite has already resolved it
  (probed through a linked file and a linked parent), and it costs no file system call, so
  the terminal prune costs one `lstat` when the stream has no directory.
- 2026-11-25 — deviation (T008, T010): `screens --file` and `--url` prune after their input
  checks and before their writes, so a refused call has no side effect. `--stream` is
  required with `--file`, `--url` and `--list`, and refused with `--prune`. `--list` refuses
  a stream with no events but not a finished one (it is read-only). The capture template is
  filled in one regex pass, so a `{out}` inside the URL is never filled. `--url` refuses an
  empty URL and a URL or command that does not print on one line.
- 2026-11-25 — deviation (T008, T014): a file counts only when the project directory and the
  stream directory are real directories by `lstat`. A `design-committed` time that cannot
  be parsed counts no file. `quote` keeps `~` unencoded (Python's always-safe set); ADR 0031
  now says so. A removed project directory prints its own `(0 files)` line.
- 2026-11-25 — known limits (T008 to T012), not built: on a case-insensitive file system two
  streams that differ only in case share one directory; two registers at the same moment can
  pick the same name and the last one wins; a Finder `.DS_Store` in a stream or project
  directory is refused at each prune and keeps that directory (the user's open question).
- 2026-11-25 — deviation (T018, the table form): #25 shipped the digest as one markdown
  table (10 lines) after this design was written. The Screens part is rows: a first row
  **Screens** with the evidence directory, then a slot of 2 task rows, missing first, then
  waived, then complete, the full count in parentheses; absent with no UI task; the cap
  grows from 10 to 13. A `screens-waived` shows there and leaves the Deviations part.
  `SCREENS_SLOT` stays out of `PARTS`, because the part has a head row and can be absent.
  ADR 0031 (Who looks), FR-012 and SC-006 now say so.
- 2026-11-25 — deviation (T015, T016): the doctor counts what the next prune would delete
  and names the first refused entry (ADR 0031 and FR-016 now say "counts"); `survey_evidence`
  and the prune share one classification, `layout_refusal`. The handoff marks `[UI]` with
  the gate's own rule (`task_screen_state`), so the mark and the gate cannot disagree; its
  rule prints over three lines so the command is never clipped.
- 2026-11-25 — deviation (the lead's note on the user's condition): the 30-day limit has no
  timer, so moment 1 now also applies it to the whole root: a stream that ends in any
  project sweeps the root. `prune_ended_stream` checks the root with one `lstat` (was: the
  stream's directory); a non-terminal append calls nothing. README, CHANGELOG, ADR 0031 and
  FR-013 say there is no timer and that `doctor` shows what is left.
- 2026-11-25 — fix (worker C's finding): a worklog ref with a NUL byte raised `ValueError`
  in `screens.py` `_read_plan` and in `_validate_design_committed`, so `digest`,
  `screens --list` and `task-done` crashed once `ui.globs` was set. Both now read it as a
  worklog that cannot be read, as `build_position` does.
- 2026-11-25 — deviation (review round 1, F1): moments 1 and 2 remove a stream directory
  whole or not at all. A directory that holds a refused entry (a link, a subdirectory, a
  `.DS_Store`) keeps every file; the age pass still removes its old files one by one and
  names each. The survey counts the same.
- 2026-11-25 — deviation (review round 1, F6): the automatic prunes (after a terminal event,
  before a `--file` or `--url` write) do not name what only the age pass over the whole root
  refused; `screens --prune` and `doctor` name it.
- 2026-11-25 — deviation (review round 1, F5, F7): `ui.capture` may hold no quote, backtick
  or backslash, so a placeholder cannot sit inside shell quotes; the Design's JSON above
  shows the first pattern. The gates read `ui.*` strictly: a bad value refuses `task-done`
  and `design-committed` with exit 2 and names the key. The views (digest, `--list`,
  handoff) stay lenient.
- 2026-11-25 — deviation (T023, the user's two answers after review round 2): a regular file
  named exactly `.DS_Store` joins the layout directly in a stream or project directory; it
  goes only with its directory, never counts as evidence, and stays refused in the root,
  which is never removed, so there it blocks no cleanup. The 30-day pass also runs right
  after a `flow-started` (FR-020), with the same one-`lstat` bound; no hook appends
  `flow-started`.
  A stream named `.DS_Store` names no evidence directory, so a directory of that name
  is refused wherever it sits (the user's rule: a directory named `.DS_Store` stays
  refused). Three tests that used `.DS_Store` as their refused entry now use `Thumbs.db`.
- 2026-11-25 — deviation (T025, found by the sentinel run after T024): T023's 30-day pass
  after `flow-started` reached the inherited evidence root from four test modules. Their
  `--batch` helpers start `journal.py` with a copy of the environment, and `run_journal`
  isolated only a call with no env of its own. A planted file older than 30 days was
  deleted. The fix is in the tests only: `journal_env()` and `isolated_env()` in
  `test_journal.py` point `CLAUDE_CONFIG_DIR` at an empty directory when an env would reach
  the ambient root, and the module guard of `test_journal_screens` now also runs in
  `test_journal`, `test_journal_status` and `test_trace`. The orchestrator did the review
  pass alone (a test-only fix, proven by the sentinel and by the guard failing red).
  Fifteen journal subprocess calls still start `journal.py` with the inherited environment
  or an unisolated copy of it: `test_hooks.py` (7), `test_journal_approval.py` (5),
  `test_journal_doctor.py` (2) and the `journal` helper of `test_attribution.py`. They pass
  the sentinel today because none of them appends `flow-started` or a terminal event. The
  durable fix is a suite-wide guard: every journal subprocess of the suite gets an
  isolated evidence root by default. That is a note for a new issue, not built here.

## Review round 1

Workflow run `wf_120fa2f2-9b8`: three lenses on Opus (correctness, conventions + design,
simplicity + security), verify `high-only`. Counts: 33 found, 32 after dedupe, 17 candidates,
2 refuters, 16 survivors, 1 killed, 15 below the floor of 60. The briefed security reviewer
read all 47 changed files and found no vulnerability at confidence 8 or above; it confirmed
the six delete rules and named one corner case (F17).

- F1 MEDIUM `shipgate/scripts/_journal/screens.py:719` — moments 1 and 2 delete the PNGs of a stream directory they then keep because of a refused entry, and report nothing.
- F2 MEDIUM `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md:195` — the Consequences say a terminal append removes only the ended stream's files, which the age pass made false.
- F3 MEDIUM `shipgate/tests/test_hooks.py:3681` — a hook test appends a terminal event with the inherited environment, so a run prunes the developer's real evidence root.
- F4 MEDIUM `shipgate/tests/test_hooks.py:70` — the hook tests' journal helpers inherit the real `CLAUDE_CONFIG_DIR`.
- F5 MEDIUM `shipgate/scripts/_journal/screens.py:504` — a `ui.capture` template with `{url}` inside double quotes lets `$(...)` in the URL run.
- F6 MEDIUM `shipgate/scripts/_journal/screens.py:822` — every terminal append and register prints every refused entry of the whole root.
- F7 MEDIUM `shipgate/scripts/_journal/gates.py:99` — a bad `ui.globs` value reads as the default and silently turns the gate off.
- F8 LOW `shipgate/scripts/_journal/check.py:22` — `check.py` imports `_waiver_reason` from `gates` after it moved to `text`.
- F9 LOW `shipgate/scripts/_journal/digest.py:250` — a `screens-waived` leaves the digest when the stream has no UI task to show it.
- F10 LOW `shipgate/scripts/_journal/screens.py:560` — `screens --prune` prints its warnings on stdout, not stderr.
- F11 LOW `shipgate/scripts/_journal/closeout.py:883` — `sweep --apply` walks the whole root once per stream it closes (deferred: cost only).
- F12 LOW `shipgate/scripts/_journal/gates.py:121` — the refusal prints a register command that must fail when the stream name cannot name a directory.
- F13 LOW `shipgate/scripts/_journal/vocab.py:530` — a Build Plan id with non-ASCII digits makes a UI task that no register can satisfy.
- F14 LOW `shipgate/scripts/_journal/gates.py:82` — the gate reads `ui.*` through its own resolver, a second read path for one fact.
- F15 LOW `shipgate/docs/prd/ui-visual-evidence.md:241` — four executive assumption lines still state decisions the build changed.
- F16 LOW `shipgate/scripts/_journal/screens.py:928` — the prune and the survey are two walkers (deferred: they share `layout_refusal`, and a test pins that they agree).
- F17 LOW `shipgate/scripts/_journal/screens.py:862` — the warning `print` in `prune_ended_stream` is unguarded, so a broken stderr changes the exit code.

### Rejected findings

- `shipgate/tests/test_journal_screens.py:907` (HIGH 95): the suite was red after the age pass; both refuters showed the test was already updated and passes (quorum 2/2).

## Review round 2

One fresh reviewer, all lenses, on the fix diff of round 1 (17 files). It confirmed F1 to
F10, F12 to F15 and F17 fixed on evidence (each with the line and the test), ran 914 tests of
the touched modules (OK) and found no blocker and nothing above LOW. F11 and F16 stay
deferred. N2 and N3 made a doc statement false, so they were fixed; the other LOWs are
deferred, as the lead's rule says.

- N1 LOW `shipgate/scripts/_journal/digest.py:253` — a waiver leaves Deviations when its task has a Screens row, even when that row does not print the reason (the task later got every width, or the row is past the slot of 2); deferred.
- N2 LOW `shipgate/README.md:416` — the README said every refused entry is reported, which F6 made false for the automatic prunes; fixed.
- N3 LOW `shipgate/docs/glossary.md:21` — the glossary still implied a 30-day timer; fixed.
- N4 LOW `shipgate/scripts/_journal/screens.py:728` — when one unlink fails in moments 1 and 2, the files removed before it are not named in the report; deferred.
- N5 LOW `shipgate/scripts/_journal/screens.py:570` — the prune before a register prints without a guard, so a broken stderr ends `screens --file` with a non-zero exit before the write; deferred.

## Review round 3 (T023)

One fresh reviewer, all lenses and the delete-rule criteria, on the T023 diff (10 files).
Every delete rule passes; 301 tests of the touched modules OK. Verdict not-ready (journal
seq 3526) on one MEDIUM, a false doc sentence:

- R1 MEDIUM `shipgate/CHANGELOG.md:38` — "a non-terminal append costs nothing new" is false since `flow-started` costs one `lstat`; fix: "A terminal append or a `flow-started` with no evidence root on disk costs one `lstat`, and any other append costs nothing new."
- R2 LOW `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md:149` — the list of automatic prunes leaves out the one after `flow-started`.
- R3 LOW `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md:120` — "four moments call it" while item 3 is a pass, not a caller; say "three events call it".
- R4 LOW `shipgate/docs/adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md:141` — the parenthesis gives the wrong reason why no stream directory may be named `.DS_Store` (the name is reserved for the Finder file).

## Handoff (2026-11-25, context past 500k)

Next session starts in the worktree `pandora.worktrees/feat-26-ui-visual-evidence`, branch
`feat/26-ui-visual-evidence`, and runs `journal.py handoff --stream=feat/26-ui-visual-evidence`.
State: T001 to T023 done; nothing committed. The lead was told of R1 and asked to let the
session fix R1 to R4 (docs only). Next steps, once the lead agrees:
1. Fix R1 to R4 with the exact sentences above; record `review-disposition` round 3 (R1 to
   R4 `fixed`); do not re-wrap beyond the changed lines; run `test_prose`.
2. A fresh full suite under the real-root sentinel: the scripts `make_sentinel.sh` and
   `check_sentinel.sh` are in the session scratchpad `worker-f/` folder (plant an old file
   under a scratch `CLAUDE_CONFIG_DIR` and `HOME`, run the suite with both set, compare).
   A run started before R1 to R4 may already be in the scratchpad as `suite-sentinel.log`.
3. Append the passing `verify-run` (after the last `task-done`, T023) and a `ready`
   `review-verdict` (criteria SC-001 to SC-009 met; `security_review` briefed; copy the
   ranking of round 1), print `journal.py digest --stream feat/26-ui-visual-evidence`.
4. Send the lead a SHORT message: what changed in T023 (`.DS_Store` in the layout of stream
   and project directories, removed with its directory; the 30-day pass after
   `flow-started`, one `lstat` with no root, about 5 us per append on 3.9), the reviewer's
   result (delete rules pass, R1 to R4 fixed), the suite counts. Do not commit.
