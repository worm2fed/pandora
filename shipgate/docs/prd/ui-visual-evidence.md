---
type: prd
title: "PRD: A UI task is done with screenshots"
created: 2026-11-25
updated: 2026-11-25
tags:
  - prd
  - shipgate
  - verify
  - ui
status: clarified
issue: "#26 (shipgate), child of #37"
worklog: "./ui-visual-evidence.worklog.md"
related:
  - "../adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "../adr/0030-the-publish-digest-is-computed-and-rides-the-publish-question.md"
  - "../adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
  - "../adr/0028-settings-live-in-shipgate-json-and-layer-per-key.md"
  - "../adr/0025-close-out-and-sweep-are-computed-from-observed-evidence.md"
  - "../adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md"
  - "../research/2026-11-15-agent-harness-audit.md"
  - "./clarify-unknowns.md"
  - "./publish-digest.md"
---

# PRD: A UI task is done with screenshots

> When a task changes a screen, the task is done only when screenshots of that screen exist
> at the set widths, or when a recorded reason says why none could be taken. The files live
> outside every repository, and the journal's own commands delete them.

## Problem

`verify` proves a task with a command. For UI work the command passes while the screen is
wrong. The user then finds the defect by eye, takes a screenshot and sends it back.

Evidence from issue #26 and the research note (counts from 7 flow journals and 148 main
sessions, 2026-08-20 to 2026-11-15):

- Defects the user found are 30% of all corrections (29 of 96). Most of them are UI.
- The user sent 25 screenshots in 13 sessions to show a defect.
- Pushback opens 15% of the user's messages in the implement phase, the highest share of
  any phase.

Evidence from this design session (counts only, 3,155 transcript files, 2026-08-20 to
2026-11-25):

- A browser tool was called in 64 files: 23 main sessions and 41 subagents.
- The user pasted 37 images in 22 sessions. In 15 of those 22 sessions the model never
  called a browser tool.
- 5,660 of 6,042 images in tool results came from a `Read` of an image file. The models
  mostly save a screenshot to a file and then read it.

Today nothing marks a task as UI. The impact map's `UI` tag is model text
(`route-and-map/SKILL.md:140`), no script computes it, and no journal field records it.

## Goals & non-goals

**Goals**

- A UI task shows the screen it changed at the set widths before its `task-done`.
- A script decides which task is UI. The model does not.
- A missing browser tool leaves a recorded reason. It never passes silently.
- The user sees the screenshots, or the reasons, in the publish digest, without running
  the app.
- No screenshot file stays on disk for long after its stream ends, and no step needs a
  person to remember the cleanup.
- No new dialog. No file under `shipgate/hooks/` or `shipgate-hud/` changes.

**Non-goals**

- A script that judges whether a screen is right (a pixel diff against a baseline).
- Starting the app. The model or the project's own run skill does that.
- Screens that a browser cannot show (native or terminal apps).
- The observed-run work of #27 on `verify-run.commands`.
- Design variants before the plan. The user dropped them (F6); the #35 retro may reopen
  them with data.
- Sharing screenshots between Claude config directories or between machines.

## Users & stories

- As the user, I want a UI task to come back with screenshots, so that I do not find a
  broken layout myself after "done".
- As the user, I want the publish digest to list the screenshots and any skipped ones with a
  reason, so that I can check the screens without starting the app.
- As the user, I want old screenshots deleted by the flow itself, so that no folder grows
  for months.
- As the orchestrator, I want a script to tell me which tasks are UI, so that I do not
  judge it task by task.
- As a worker, I want one command that registers my screenshots, so that the evidence has
  one form whatever tool took it.

## Functional requirements

**Which task is UI**

- **FR-001** — A project names its UI files with globs in the `ui.globs` setting. The
  default is an empty list. With no globs, no task is UI, and no requirement below except
  FR-004's absence applies.
- **FR-002** — A task is UI when a path that its Build Plan line names matches a glob. One
  function computes this. The `task-done` gate, the handoff brief, the publish digest and
  the impact map use the same function.
- **FR-003** — When the project has UI globs, `design-committed` refuses a worklog with a
  Build Plan task line that names neither a path in backticks after `file(s):` nor
  `file(s): none`. The refusal gives the line number and the task id.
- **FR-004** — The impact map records the computed UI flag of the touched paths. Clarify's
  reference ask (FR-018 of `clarify-unknowns.md`) reads that flag. The model's `UI` tag
  goes. With no globs, the flag is absent and clarify asks for no reference.

**Taking and registering screenshots**

- **FR-005** — A project can name a capture command in `ui.capture`, with the placeholders
  `{url}`, `{width}` and `{out}`. The journal prints the filled commands, one per width. It
  never runs them.
- **FR-006** — One command registers the screenshot files of a task. It reads the pixel
  width of each file from the file itself. A PNG counts for a set width when its width is
  that width times 1, 2 or 3. The command stores the file under a name made of the task id
  and the set width. It refuses a file that is not a PNG, a width that matches no set width,
  and a width that matches two.
- **FR-007** — The screenshot files live outside every repository, in an evidence root
  under the Claude config directory, with one directory per project and one per stream.

**The gate**

- **FR-008** — `task-done` of a UI task is refused unless, for every set width, a
  registered screenshot of that task exists that is newer than the stream's newest
  `design-committed`, or a `deviation` of kind `screens-waived` names the task and gives a
  reason.
- **FR-009** — The refusal names the missing widths and prints the register command, the
  capture command when `ui.capture` is set, and the waiver command.
- **FR-010** — A project with no UI globs, and a task that is not UI, see no change in any
  gate. A `screens-waived` deviation clears no Stop-gate finding.

**Who looks at the screenshots**

- **FR-011** — The one who took the screenshots reads them before `task-done` and compares
  them with the reference that the PRD names.
- **FR-012** — The publish digest of #25 gets a part for the screenshots: one row per UI
  task, with its widths, its waiver reason or what is missing, and the stream's evidence
  directory in the part's first row. The part shows only for a stream with a UI task.

**Cleanup**

- **FR-013** — When a terminal event (`flow-completed`, `flow-abandoned`) is committed for a
  stream, the journal deletes that stream's evidence directory, and every screenshot file
  older than 30 days in the evidence root. This covers the close-out, `journal.py sweep
  --apply` and a stream closed by hand. There is no timer.
- **FR-014** — Each time screenshots are registered or capture commands are printed, the
  journal deletes the evidence directories of this project whose stream is finished or
  unknown to the journal, and every screenshot file older than 30 days in the evidence
  root.
- **FR-020** — When a `flow-started` is committed, the journal deletes every screenshot file
  older than 30 days in the evidence root (added after review round 2, the user's decision).
  So there is no timer: the 30-day limit applies when a stream ends, when a stream starts
  and when screenshots are registered.
- **FR-015** — A delete touches only the expected layout under the evidence root. It
  follows no symbolic link, refuses any other entry, and prints what it removed and what it
  refused. A failed delete prints a warning and never changes the exit code or the
  recorded event.
- **FR-016** — `journal.py doctor` reports the evidence root, and for this project and for
  the whole root the size, the file count and the oldest file. It also counts the
  directories and files that the next cleanup would delete and the entries it refuses. It
  says that
  another Claude config directory or another machine keeps its own evidence root.

**Skill text and settings**

- **FR-017** — `verify`, `implement`, `design`, `route-and-map`, `clarify`, `setup` and the
  worker brief in `model-tiers` carry the rule, the reason for it and the commands.
- **FR-018** — The handoff brief marks the next task when it is UI and prints the rule for
  it.
- **FR-019** — The settings `ui.globs`, `ui.widths` and `ui.capture` land in
  `shipgate/settings.schema.json` with their type, default and project scope.
  `journal.py config` prints each one with its source.

## Success criteria

- **SC-001** — Unit tests show the UI function over globs and Build Plan lines. A `.tsx`
  file outside the project's globs is not UI.
- **SC-002** — Unit tests show the gate: it refuses a UI `task-done` with no files; it
  accepts one with a file for every set width at scale 1 or 2; it accepts one with a
  waiver; it ignores a task that is not UI; it ignores a project with no globs.
- **SC-003** — Unit tests show each refusal of the register command: a file that is not a
  PNG, a missing file, a width that matches no set width, a width that matches two. A PNG
  older than `design-committed` does not count for the gate.
- **SC-004** — Unit tests show the cleanup: a `flow-completed` and a `flow-abandoned` append
  delete the stream's directory; `sweep --apply` does too; registering screens deletes the
  directories of finished and unknown streams and the files older than 30 days; a symbolic
  link, an unexpected file and a path outside the root are never deleted; a failed delete
  leaves the exit code at 0 and the event recorded.
- **SC-005** — Unit tests show the doctor lines for a root with files, an empty root and a
  missing root.
- **SC-006** — Unit tests show the digest part: one row per UI task, at most 2 task rows
  after the directory row, the full count over the slot, absent with no UI task, and at most
  13 lines in all.
- **SC-007** — No file under `shipgate/hooks/` or `shipgate-hud/` changes, and the full suite
  passes: `python3 -m unittest discover -s shipgate/tests`.
- **SC-008** — `journal.py config` prints each new setting with its source. A bad value exits
  2 with the key and the allowed values.
- **SC-009** — Prose tests pin the skill sentences of FR-011 and FR-017.
- **SC-010** — After the merge, eval case 77 runs once on each session model with `ui.globs`
  in its fixture. A fall changes clarify's UI sentence.
- **SC-011** — One month after the release, the #35 retro counts, for projects with UI
  globs, the images the user pasted in the implement phase, and compares the count with the
  month before (counts only).

## Constraints & assumptions

- If a check can be deterministic, it must be. A script computes and checks; a skill
  sentence only tells the model to call it. [source: the user's rule for this epic, issue
  #37 plan]
- A switch or a value is a setting in the schema, not prose. The issue's "Config: the
  browser tool goes under `Debug evidence sources`" becomes `ui.capture`. [source: ADR 0028]
- A feature that adds a stop or a question says when it is skipped. This one adds no
  dialog. [source: the user's ask for fewer dialogs, issue #37]
- No screenshot file may stay for long: the cleanup is deterministic, unit-tested, needs no
  person to remember a step, and runs at no hook. [source: the user's condition on F5,
  through the lead, 2026-11-25]
- The files live under the Claude config directory, outside every repository. [source: the
  user's answer F5-A, 2026-11-25]
- This repo is public. No private screen, path or name enters a fixture. Tests build their
  PNG files in code. [source: root `CLAUDE.md`, Public repo]
- Files under `shipgate/hooks/` are security-sensitive. This change touches none.
  [source: `.claude/shipgate.md`]
- #25 ships first as 0.35.0 with the digest; this change is 0.36.0 and adds the digest's
  screenshot part. ADR 0030 is #25's; this change takes ADR 0031. [source: the lead's
  decisions, 2026-11-25]
- One image in the context costs about 1.3k tokens up to 800 px wide, 2.5k at 801 to 1,400
  px and 3.8k at 1,401 to 2,000 px. A screenshot call takes 1.9 s at the median and 7 s at
  p90. [source: this session's transcript count, 336 clean pairs and 688 calls]
- The browser tools in use: a DevTools-style MCP server (688 screenshot calls over two
  servers), the Chrome extension's `computer` tool (194 calls), and Playwright from Bash
  (in 52 sessions). [source: this session's transcript count]
- A stream is dormant after 7 days without an event. [source: `vocab.py:480`
  `DORMANT_DAYS`]
- The `verify-run` shape requires only `outcome` and `task_ids`; other keys are stored and
  no reader takes them. [source: `vocab.py:284`, `fold.py:208`]

## Assumptions (executive)

- [behaviour] [no source found in the journal package and the settings schema] How old may a screenshot file get before the cleanup deletes it, and is the limit a setting? → 30 days, a constant beside `DORMANT_DAYS`, not a setting — the evidence root holds every project of one config directory, so one project's value must not decide another project's files; 30 days is four times the dormancy limit, and the gate counts only files newer than `design-committed` anyway
- [behaviour] [no source found in the journal package] Where does the cleanup of a finished stream run? → in `append`, right after a terminal event commits, like the go-request marker after a `go-requested`, and the same moment applies the 30-day limit to the whole root — one place covers the close-out, the sweep and a stream closed by hand, no printed step can be skipped, and with no timer a stream that ends sweeps the root (the age pass was added in the build)
- [data] [no source found in the journal package] How is a screenshot of a high-density screen matched to a set width? → a PNG counts for width w when its pixel width is w, 2w or 3w; a width that matches two set widths is refused with a request for `--width` — the tools in use take 2x screenshots on a high-density display
- [data] [no source found in the journal package] Can a task have more than one screenshot per width? → yes, the second and later ones get a suffix `-2` to `-9` — a task can change two screens, and the gate needs one per width
- [behaviour] [source: ADR 0030 Consequences] Where does the screenshot part sit in the digest, and how big is it? → after the deviations and before the Look first row: a row **Screens** with the evidence directory, then 2 task rows, shown only for a stream with a UI task — the cap grows from 10 to 13 rows (changed in the build: #25 shipped the digest as a table after this design)
- [technical] [source: issue #26] How many widths by default? → two, 390 px and 1,280 px — the issue allows 2 or 3; two widths cost about 3.8k tokens to read, three about 5.1k
- [technical] [no source found in the settings schema] Which scope do the new settings take? → project, as one `ui` group — the globs, the capture command and the widths are facts of one project's app
- [technical] [no source found in the journal package] Which image format does the register command take? → PNG only — its width sits at a fixed place in the header, so a stdlib read gives it; one exact form refuses the rest
- [technical] [source: `.claude/shipgate.md` Security-sensitive areas] Does the journal run the capture command? → no, it prints it — a command run inside `journal.py` is hidden from the permission prompt and from the auto-mode review
- [technical] [source: `worklog-template.md:79`] Where does a task line name its paths? → in backticks after `file(s):`, or `file(s): none` — the template's form, read as one exact form
- [technical] [source: ADR 0020] How is a missing screenshot waived? → a `deviation` with `kind: screens-waived`, `task_ids` and a reason in `note` — the waiver form the Stop gate already uses, with its own kind so it clears nothing else
- [technical] [no source found in the journal package] What does the gate do when the stream's worklog cannot be read? → no task is UI, and `design-committed` prints a warning when the project has globs — the other gates do not depend on the worklog either
- [technical] [no source found in the journal package] How is a project's evidence directory named? → the first 12 hex digits of the SHA-256 of the journal database's path as SQLite reports it, which is its real path — worktrees whose database links to the main checkout share one directory (changed in the build from `realpath`, which costs a file system call)
- [technical] [source: `artifacts.py:233`, `signals.py:457`] Where does the UI function live? → a small stdlib module `scripts/_ui.py` that `signals.py` and the journal package both import, with the glob rule of the artifact homes — one function for every caller
- [technical] [source: `shapes.py:245`] How does the route-and-map entry record the flag? → `ui: true` or `false`, closed by a new `booleans` shape rule kind — an enum would accept 1 and 0, since 1 == True in Python (changed in the build)
