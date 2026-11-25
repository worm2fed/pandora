---
type: adr
title: "0031. A UI task is done with screenshots on disk"
created: 2026-11-25
updated: 2026-11-25
tags:
  - adr
  - shipgate
  - verify
  - ui
status: accepted
date: 2026-11-25
issue: "#26 (shipgate), child of #37"
related:
  - "../prd/ui-visual-evidence.md"
  - "../prd/ui-visual-evidence.worklog.md"
  - "./0030-the-publish-digest-is-computed-and-rides-the-publish-question.md"
  - "./0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
  - "./0028-settings-live-in-shipgate-json-and-layer-per-key.md"
  - "./0025-close-out-and-sweep-are-computed-from-observed-evidence.md"
  - "./0020-the-stop-gate-binds-a-worklog-the-way-position-does.md"
---

# 0031. A UI task is done with screenshots on disk

> A project names its UI files with globs. A script marks a Build Plan task as UI when a
> path on its line matches. `task-done` of a UI task needs a registered PNG for every set
> width, or a waiver with a reason. The files live outside every repository, and the
> journal deletes them when the stream ends and when screens are registered; files over 30
> days go at those moments, since there is no timer. No hook and no HUD file changes.

## Context

`verify` proves a task with a command (`verify/SKILL.md:58-67`). For UI work the command
passes while the screen is wrong, and the user finds the defect by eye: 29 of 96
corrections, most of them UI, and 25 screenshots sent in 13 sessions (issue #26).

The facts that shape the decision:

- **Nothing marks a task as UI.** The impact map's `UI` tag is model text
  (`route-and-map/SKILL.md:140`). Clarify reads it in prose (`clarify/SKILL.md:103`). No
  script computes it, and no journal field holds it. `signals.py` has no file-kind map; its
  only extension table drives import parsing (`signals.py:1045`).
- **An extension rule has false positives.** This repo's HUD ships three `.tsx` files
  (`shipgate-hud/hooks/register.tsx`, `views.tsx`, `tests/views.test.tsx`), and it draws in
  a terminal.
- **The task line is free text after the id.** One regex reads the box and the id
  (`vocab.py:520`). `_plan_task_title` strips only `[P]` (`artifacts.py:66-72`). The
  template already asks for paths in backticks after `file(s):`
  (`worklog-template.md:79`).
- **The `task-done` gate knows only the journal.** `_validate_task_done`
  (`gates.py:61-74`) returns at the first passing `verify-run` that names the task. It gets
  no project directory (`gates.py:401`), so it reads no worklog and no setting today.
- **`verify-run` keeps only `outcome` and `task_ids`.** The fold keeps `outcome`, `scope`,
  `task_ids` and the time (`fold.py:208-213`). The payload cap is 1,024 bytes
  (`vocab.py:495`).
- **The hooks see no browser tool.** PostToolUse matches `Write|Edit|NotebookEdit|Bash`
  (`core.json:29`), and `post_tool_use.py:357` exits for any other tool.
- **The tools differ.** In the design session's count (3,155 transcript files): a
  DevTools-style MCP server took 688 screenshots, the Chrome extension's `computer` tool ran
  194 times, and Playwright ran from Bash in 52 sessions. 5,660 of 6,042 tool-result images
  came from a `Read` of a file.
- **An image costs tokens.** About 1.3k tokens up to 800 px wide, 2.5k at 801 to 1,400 px,
  3.8k at 1,401 to 2,000 px. A screenshot call takes 1.9 s at the median.
- **A post-commit step already exists.** `append_event` touches the go-request marker
  right after the commit of a `go-requested` (`append.py:239-241`). `sweep --apply` appends
  its terminal events through `append_event` (`closeout.py:883`).
- **The repo is public.** A private project's screen must never reach a fixture, and this
  repo ignores only `.claude/shipgate.db*` (`.gitignore`).

## Decision

The user chose F1-D, F2-A, F3-A, F4-A, F5-A with a cleanup condition, F6-A and F7-A on
2026-11-25, through the lead.

**Settings.** One project-scope group `ui` in `settings.schema.json`:

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `ui.globs` | list of globs | `[]` | the project's UI files; empty turns the feature off |
| `ui.widths` | list of integers, 200 to 4000, at least one | `[390, 1280]` | the CSS widths each UI task shows |
| `ui.capture` | a command with `{url}`, `{width}` and `{out}`, or null | null | the command the journal prints for the model to run |

The settings reader's schema subset gains `minItems`.

**Which task is UI.** `scripts/_ui.py` holds one function: a path is UI when it matches a
glob of `ui.globs`, by the fnmatch rule of the artifact homes (`artifacts.py:233`). A Build
Plan task is UI when a path in backticks after `file(s):` on its line is UI. With globs
set, `design-committed` refuses a task line that names neither a backticked path nor
`file(s): none`, and names the line. `signals.py hotspots --json` reports the UI files of
the touched set; route-and-map records `ui: true|false` in its phase entry; clarify's
reference ask reads it. The model's `UI` tag goes.

**Registering screenshots.** `journal.py screens --stream S --task T --file F ...` reads
each PNG's pixel width and maps it to a set width w when it is w, 2w or 3w. It stores the
file as `T-<w>.png`, then `T-<w>-2.png` up to `-9`, by a temporary file and a rename.
`--width W` settles a width that matches two set widths. A file that is not a PNG, a width
that matches nothing, and a stream the journal does not hold are refused with exit 2. With
`ui.capture` set, `--url U` prints the filled command for each width; the model runs them in
its own Bash call, and the journal never runs a command. `--list [--json]` prints each UI
task's state: the widths present, the waiver reason, or the widths missing.

**The gate.** `_validate_task_done` gets the project directory. With globs set, it finds
the stream's newest `design-committed`, reads its worklog and computes whether the task is
UI. A UI task needs, for every set width, a regular file `T-<w>*.png` in the stream's
evidence directory, newer than that `design-committed`, whose PNG width is w, 2w or 3w. Or
a `deviation` with `kind: screens-waived`, `task_ids` and a reason names the task;
`_validate_waiver` checks it like `gate-waived`, and it clears no Stop-gate finding. The
refusal names the missing widths and prints the register, capture and waiver commands.
`verify-run` gets no new field, and the Stop gate gets no new rule. `--force` skips this
check as it skips every append gate.

**Where the files live.** The evidence root is `$CLAUDE_CONFIG_DIR/shipgate/evidence`,
else `~/.claude/shipgate/evidence`. A project's directory is the first 12 hex digits of the
SHA-256 of the journal database's real path, so worktrees whose database links to the main
checkout share it. A stream's directory is the stream name with every byte but letters,
digits, `-`, `_`, `.` and `~` percent-encoded. With no config directory and no home, the
register command and the gate say there is no evidence root, and the waiver applies.

**Cleanup.** One function prunes; three events call it, and none is a hook:

1. Right after a `flow-completed` or `flow-abandoned` commits, `append_event` prunes that
   stream's directory, then applies moment 3 to the whole root. The close-out's
   `flow-completed` step, `sweep --apply` and a stream closed by hand all pass there. With
   no evidence root on disk it costs one `lstat`.
2. Each `screens` call that writes or prints prunes this project's directories whose stream
   is finished or unknown to the journal.
3. The same calls delete every screenshot file older than `EVIDENCE_KEEP_DAYS = 30` in the
   whole evidence root. The constant sits beside `DORMANT_DAYS` (7) in `vocab.py`.
4. Right after a `flow-started` commits, `append_event` applies moment 3 alone to the whole
   root (added after review round 2, the user's decision), with the same one-`lstat` cost.

There is no timer: the 30-day limit applies at three moments, when a stream ends, when a
stream starts (in any project) and when screens are registered. `doctor` shows what is
left.

The delete rules: the root is resolved once with `realpath`; every entry under it is read
with `lstat` and never followed; the only entries deleted are a 12-hex project directory, a
stream directory whose name round-trips the encoding, a regular file named
`T<digits>-<digits>[-<digit>].png` or its temporary `.tmp` form, and a regular file named
exactly `.DS_Store` directly in a stream or project directory (the file Finder leaves when
the user opens the directory; the name is reserved, so no stream directory may take it),
which goes only with its directory, never counts as
evidence, and stays refused in the root itself; files go one by one with
`unlink`, then empty directories with `rmdir`, never a recursive delete. A symbolic link or
any other entry is refused, left in place and reported, and its directory stays. When the
prune removes a whole stream directory (moments 1 and 2), it removes it whole or not at all:
a directory that holds a refused entry keeps every file. Each prune prints the directories it
removed with their file counts and each refused entry; the automatic prunes (after a
terminal event, after a `flow-started`, before a register) name only the refusals inside
what they target, and
`screens --prune` and `doctor` name the rest. Every
`OSError` becomes a warning line on stderr. The prune never raises, never changes an exit
code, and never undoes the event that called it.

**Doctor.** `journal.py doctor` reports the evidence root and, for this project and for the
whole root, the size, the file count and the oldest file's age. It counts the directories
and files the next prune would delete, and the entries it refuses, with the first one's
path. It ends with one line: another
Claude config directory or another machine keeps its own evidence root, which this report
does not read.

**Who looks.** The one who took the screenshots reads them before `task-done` and compares
them with the PRD's reference. The publish digest of ADR 0030 gets a part "Screens" after
"Deviations" and before "Look first". The digest is one markdown table since ADR 0030's
amendments, so the part is rows: a first row **Screens** with the stream's evidence
directory, then a slot of 2 rows of UI tasks, the ones that miss a width first, then the
waived, then the complete, with the full count in parentheses over the slot. The part is
absent for a stream with no UI task. The digest's cap grows from 10 to 13 lines. A
`screens-waived` shows in this part, not under Deviations.

**Dropped.** Design variants (F6-A). The #35 retro may reopen them with data.

## Alternatives considered

The forks and the options the user did not take:

- **F1** — only the taker reads (B: a fresh reviewer at review, one round later; C: only
  the user, through the digest). The user took the taker plus the digest.
- **F2** — built-in globs on for everyone (false positives such as this repo's terminal
  `.tsx`, and refusals in every public frontend project on the upgrade); globs for tasks but
  the model's tag for clarify (two mechanisms for one fact); the model's tag as a `[UI]`
  task marker (not computed).
- **F3** — a `screens` field on `verify-run` (566 bytes of a 1,024-byte cap, and a contract
  the fold and the HUD ignore); report only (a reminder again); a Stop-gate rule for a
  forced `task-done` (a hook-contract change).
- **F4** — a hook that observes an MCP tool (a hook-contract change, and some tools write
  no file); the journal running the capture command itself (hidden from the permission
  prompt and the auto-mode review); no setting (prose).
- **F5** — inside the repository with an ignore check (a project that commits `.claude/`
  whole is one mistake from a leak); the session scratchpad (gone before the review
  session).
- **F6** — static mock-ups or quick prototypes before the plan: a build per variant and one
  more choice per UI design, for a defect class that #24's reference ask already targets.
- **F7** — no eval run at all, or a new case that needs a browser in the eval sandbox.
- **An age limit as a setting.** One evidence root holds every project of a config
  directory, so a project's value would decide other projects' files. A constant is the
  same for all.
- **A pixel diff against a baseline image.** A new screen has no baseline, and a diff says
  "changed", not "right".

## Consequences

- No file under `shipgate/hooks/` or `shipgate-hud/` changes, so the change takes one
  publish approval. It ships as shipgate 0.36.0, after #25's 0.35.0.
- `append` gains a file side effect after a terminal event: it removes the ended stream's
  directory and every layout file over 30 days in the whole evidence root, in any project.
  The delete rules above bound it.
- Two Claude config directories on one machine keep two evidence roots. A session sees only
  its own: a `task-done` under one config directory does not see screenshots registered
  under the other, so it asks for them again or for a waiver, and the digest shows them as
  missing. A root whose config directory never runs shipgate again keeps its files; its own
  doctor shows them. Two machines keep two journals as well, so nothing crosses.
- A project with no globs sees no change except that clarify asks for no UI reference.
- #27 stays separate: the gate reads the files itself, so the screenshot evidence is
  observed without a hook, and `verify-run.commands` is #27's alone.
- The fnmatch rule now lives in three places (`artifacts.py:233`, `signals.py:457` and
  `_ui.py`). Folding the first two into `_ui.py` is a separate cleanup.
