---
type: worklog
title: "Worklog: shipgate 0.27.0 — hand off to a fresh session at a phase gate"
created: 2026-11-20
updated: 2026-11-20
tags:
  - worklog
  - shipgate
status: review
prd: "./phase-handoff.md"
issue: "#23"
related:
  - ../adr/0021-the-handoff-brief-is-computed-not-written.md
  - ../adr/0022-the-context-nudge-rides-the-posttooluse-bash-hook.md
---

# Worklog: shipgate 0.27.0 — hand off to a fresh session at a phase gate

> Design + build plan companion to `./phase-handoff.md`. Issue #23.

---

# Design

## Approach

Designed inline, no architect fan: the brief has one viable home (`journal.py`, beside
`position`), and the nudge's one real fork goes to the user as ADR 0022. The work runs in
two parts. The parts with no hook change come first: the `handoff` command and the skill
text. The nudge is built only after the user answers ADR 0022.

## Architecture

**`journal.py handoff --stream <s>`** (ADR 0021). A read-only subcommand.

- `build_handoff(conn, stream, project_dir, homes, now=None, start=None)` calls
  `build_position` and adds: `request` (first `flow-started`), `report_to` (newest event
  with a string `report_to`), `next_task` (first Build Plan task not done), `next_phase`,
  `open_gates`, the last five `decisions` and `rules` (config excerpts).
- `render_handoff(doc)` prints the text. Every value goes through `_one_line` / `_clip`,
  as in the status brief, so a payload cannot add lines.
- The next phase: `PHASE_ORDER` after the current one, with two exceptions. In `implement`
  with tasks left, it stays `implement`. In `review` after a `not-ready` verdict, it is
  `implement` (fix round).
- The open gates, each from a fact:
  - an ADR in the last `design-committed`'s `open` list whose file still says
    `status: proposed` (or cannot be read);
  - a finding in state `fixing` (`dispositions`);
  - a last verdict `not-ready`;
  - a task ticked in the worklog with no `task-done` (the Stop gate blocks on it);
  - a last `verify-run` that failed;
  - the publish gate: held, or authorized by which event.
- The rules: the **Autonomy** and **Security-sensitive areas** sections, from the nearest
  config file that holds each (`config_candidates`: the repo's files from the working
  directory up, then the umbrella's up to the journal's root; then the user file;
  `_config.read_layers` and `section_owner`). Each section prints its lines with HTML comments removed,
  at most 10 lines, then `… N more lines in <file>`. One fixed line says that the repo's
  `CLAUDE.md` files load at session start and stay binding.
- `flow-started`'s shape gains `report_to` as an optional string.

**Skill text.** `design` Step 5: once `design-committed` lands, run `handoff`, show it and
recommend `/clear`, then `/shipgate`. `review` Step 6: before a fix round, the same when the
session already ran an earlier phase or the nudge fired. `feature` (detect state): on a
resume past design, run `handoff` and route from it.

**The nudge** (ADR 0022, accepted with the user's three choices). `post_tool_use.py`
checks a Bash call's stdout for the two event names (`NUDGE_WORDS`). Only on a hit it
imports `hooks/_nudge.py`: `boundary_append` reads the append's own output (JSON or the
text summary) for the event, the stream and the seq; `context_tokens` reads the transcript
tail; `context_nudge` runs `journal.py nudge`. `nudge_line` speaks only when the seq is the
stream's newest event of that type, a verdict is `not-ready`, and the tokens reach the
`## Session` `Handoff:` threshold (default 500k). The hook prints the line as
`systemMessage` and `additionalContext` and never blocks.

## Data flow

`handoff` reads only: the journal (`read_events`), the worklog and ADR files the events
name (relative, safe refs only, as `position`), and the config files. It writes nothing.

## Data model / schema

No schema change. One optional payload key: `report_to` (string) on `flow-started`.

## API / contract changes

- New subcommand `journal.py handoff --stream <s>`. Exit 1 for a stream with no events,
  as `position`.
- `flow-started` accepts `report_to`. An old journal reads the same; an old `journal.py`
  ignores the key.
- No hook change in T001 to T005.

## Reference implementation

`build_position` / `_render_position` in `shipgate/scripts/journal.py`: the same read path,
the same safe-ref rule and the same one-line rendering. `config_report` shows how a script
reads a config section through `_config`.

Risk ranking of the files the plan changes (`signals.py hotspots`, source graph):
`shipgate/README.md` (churn top, fix high), `skills/feature/SKILL.md` (churn top, fix high),
`shipgate/scripts/journal.py` (churn top, fix high), `skills/review/SKILL.md` (churn top,
fix mid), `skills/design/SKILL.md` (churn top, fix low). `journal.py` gets tests that pin
`position` before `handoff` reuses it; the `TestPosition` suite already does.

## CLAUDE.md / impact-map compliance

- Primary home: the `shipgate` plugin. One plugin, one version bump (0.27.0) in
  `plugin.json` and `marketplace.json`, one CHANGELOG entry.
- Public repo: fixtures use `feature/demo`, `#1234`, `user@alice`. Grep the diff before the
  report.
- Python 3.9 compatible, standard library only.
- Hooks: no change before the user approves ADR 0022.

---

# Build Plan

## Handoff brief (no hook change)
- [x] T001 — `journal.py handoff`: `build_handoff`, `render_handoff`, the subparser, `report_to` in the `flow-started` shape — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests for each FR-001 to FR-010 item fail first, then pass; SC-002 (≤ 60 lines) and SC-003 (same bytes twice) pass
- [x] T002 — config excerpts in the brief: Autonomy and Security-sensitive areas through the layers, comments dropped, 10-line cap — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests for the project file, the user file, a section in neither, and the cap pass
- [x] T003 — skill text: `design` prints the brief at `design-committed` and recommends `/clear` then `/shipgate`; `review` before a fix round; `feature` runs `handoff` on a resume past design — file(s): `shipgate/skills/design/SKILL.md`, `shipgate/skills/review/SKILL.md`, `shipgate/skills/feature/SKILL.md`, `shipgate/tests/test_prose.py` — done when: a prose test checks each of FR-011 to FR-013
- [x] T004 — docs: README journal commands, glossary if it lists commands — file(s): `shipgate/README.md`, `shipgate/docs/glossary.md` — done when: `handoff` is documented once, the README links the changelog and copies no entry
- [x] T005 — probe SC-004: one `claude -p` run on a model other than the writer's, given only the brief of a fixture stream — file(s): this worklog — done when: the answer names the next task, the first file to open and one binding rule; result recorded below

## Context nudge (after the user answers ADR 0022)
- [x] T006 — the nudge as the user approved it: boundary detection, transcript usage read, threshold through the config layers, one line of context — file(s): `shipgate/hooks/post_tool_use.py`, `shipgate/hooks/_nudge.py`, `shipgate/scripts/journal.py`, `shipgate/scripts/lean_config.py`, `shipgate/config-template.md`, `shipgate/README.md`, `shipgate/tests/test_hooks.py`, `shipgate/tests/test_journal.py` — done when: SC-006 tests pass; SC-007 measured under 1 ms on a non-boundary call; ADR 0022 accepted

## Release
- [x] T007 — version 0.27.0 in `shipgate/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, CHANGELOG entry — file(s): those three — done when: both versions read 0.27.0 and the entry lists every change
- [x] T008 — full suite and the security review brief on the working-tree diff — file(s): none — done when: `python3 -m unittest discover -s shipgate/tests` passes; the reviewer's findings are triaged

# Log

- 2026-11-20 — design committed. ADR 0022 is `proposed`; the nudge design went to the lead
  as a question for the user.
- 2026-11-20 — T001, T002 done. The brief adds one fixed rule line beside the CLAUDE.md
  line: commit only when the user asks (the `implement` skill's rule). The config reader
  gained `_config.section_lines`, because `section_bullets` reads only `Key: value`
  bullets and the Security-sensitive areas section is prose bullets. In `implement` with
  a task left, the next phase prints as `implement (the next task)`.
- 2026-11-20 — T003, T004 done. T005 probe (SC-004): one `claude -p --model sonnet
  --max-turns 1` run in an empty directory, no tools, given only the brief of a fixture
  stream (`feat/1234-export-filters`: 1 of 4 tasks done, one ADR `proposed`, `report_to`
  set). The writer runs on Opus. The answer named the next task (T002), the PRD as the
  first file, the security rule with the test it requires, the lead as the report target,
  and five things not to do yet: the `proposed` ADR's tasks, the escalated CLI flag, an
  MR/PR without a ready verdict, a commit without the user's go. Cost 0.11 USD.
- 2026-11-20 — The user answered ADR 0022 through the lead: default 500k in `## Session`
  as `Handoff:`, the line goes to the user (`systemMessage`) and to the model
  (`additionalContext`), and it fires after `design-committed` and after a `not-ready`
  verdict only. ADR 0022 is accepted. T006 done. Deviation: the nudge code moved to a new
  `hooks/_nudge.py`, imported only after a boundary match. Inline, it added 0.7 ms of
  script compile to every Bash call; split, the hook compiles in 2.32 ms against 2.29 ms
  for 0.26.0. The stdout check costs 1.6 µs on 2 KB and 89 µs on 200 KB (SC-007). A
  boundary call takes about 234 ms in all. The template's new comment sentences joined
  `lean_config.py`'s boilerplate catalogue, so `setup` strips them as before.

# Review

## Review round 1

Review Workflow `wf_6860cadb-361`: three lenses (correctness, conventions + design,
simplicity + security), Opus finders. 23 found, 20 after dedupe, 11 above the floor of 60,
0 refuters (no BLOCKER or HIGH), 11 survivors, 9 below the floor. A separate reviewer ran
the built-in `/security-review` criteria on the working-tree diff (the command itself reads
only a committed diff, #40): no finding at confidence 0.8 or more. Verdict: not ready.

- F1 MEDIUM `hooks/_nudge.py:55` — a refused `append --json` and a quoted old append line counted as a boundary append; fixed by the seq rule.
- F2 MEDIUM `scripts/_config.py:169` — `section_lines` was a second section walker with another fence rule; fixed by `_walk_section`.
- F3 MEDIUM `scripts/journal.py:4028` — the handoff rules and threshold skipped the umbrella layer of ADR 0018; fixed by `config_candidates`.
- F4 MEDIUM `scripts/journal.py:3890` — the ADR status read was case-sensitive, front matter only and unbounded; fixed.
- F5 LOW `scripts/_config.py:168` — a bullet ending in a colon was dropped as a placeholder; fixed.
- F6 LOW `scripts/journal.py:3917` — `_newest_string` had an unused parameter; removed.
- F7 LOW `hooks/post_tool_use.py:324` — the two event names lived in three places; a test now holds them equal.
- F8 LOW `skills/setup/SKILL.md:94` — setup did not offer the Session threshold for the user file; added.
- F9 LOW `prd/phase-handoff.worklog.md:9` — the worklog status said designing; now review.
- F10 LOW `prd/phase-handoff.worklog.md:34` — the worklog design named stale functions and a proposed nudge; updated.
- F11 LOW `prd/phase-handoff.md:159` — the PRD's open questions still named the nudge; updated.
- F12 LOW `hooks/_nudge.py:63` — a stdout that quotes an old append summary fired the nudge again; fixed with F1.
- F13 LOW `scripts/journal.py:3956` — `_adr_status` read a ref with no regular-file check or size cap; fixed with F4.
- F14 LOW `scripts/journal.py:4205` — thresholds of a million printed as `1000k`; now `1m`.
- F15 LOW `scripts/journal.py:4110` — the default report target said "in this session", wrong for the reader; now "the user".
- F16 LOW `scripts/journal.py:4224` — the suggested commands did not shell-quote the stream; now `--stream=` with `shlex.quote`.

### Rejected findings

- `scripts/journal.py:4002` (LOW 50): the publish gate is listed at every phase; FR-006 lists it on purpose, so a fresh session never guesses it.
- `skills/feature/SKILL.md:180` (LOW 45): `<stream>` against `<branch>` as the placeholder; the stream name is the branch name, so both read right.
- `scripts/journal.py:4036` (LOW 35): the handoff rules use a line-based presence rule; ADR 0018's bullet rule would read a prose section as absent.

## Review round 2

One reviewer with all lenses on the round-1 fixes. F1 to F16 confirmed fixed in the code;
F3 only for `handoff`, its rest is F17. New findings, all fixed except F24. Verdict: not
ready, for F17.

- F17 MEDIUM `scripts/journal.py:5573` — the hook runs `journal.py nudge` at the project root, so a nested repo's `## Session` was never read; the hook now passes the session's `cwd` as `--start`.
- F18 LOW `hooks/_nudge.py:58` — a batch kept only its last boundary event, so a later ready verdict hid a design commit; the newest `design-committed` now wins.
- F19 LOW `scripts/journal.py:3891` — a list item under a `## Status` heading read as `-`, and `## Status: Accepted` was not read; both forms read now.
- F20 LOW `scripts/journal.py:4258` — 999,600 tokens printed as `1000k`; the label rounds first.
- F21 LOW `scripts/_config.py:139` — the shared walker no longer narrowed a section at a heading that repeats its name; the old rule is back and pinned.
- F22 LOW `scripts/journal.py:4061` — `config_candidates` read the directories between a nested repo's parent and the root; it now reads the parent and the root, as `signals.py` does.
- F23 LOW `scripts/_config.py:203` — a fence under a placeholder bullet was quoted alone; it now belongs to the bullet.

### Rejected findings

- `hooks/_nudge.py:69` (LOW 40): a stdout that quotes the newest append line again repeats the advice while that row is the newest; a state file in a hook costs more than one repeated line.

## Review round 3

The orchestrator checked the round-2 fix diff alone: three files and their tests, each
finding pinned by a test that failed first. The security reviewer re-checked the hook delta
with the `/security-review` criteria: no finding at confidence 0.8 or more. Below that bar
it found one real defect, fixed here:

- F25 LOW `scripts/journal.py:3892` — the ADR status regex backtracked exponentially on a `## Status` heading followed by many blank lines, so `handoff` could hang; every blank is now `[ \t]` with explicit line breaks, and a test with 2,000 blank lines runs in under a second (0.8 ms measured).


Verdict: ready. Full suite after the last code change: 1,327 tests, OK, 2 skipped. The five
test files the diff reaches, after the last task-done: 886 tests, OK. 29 findings closed,
0 open.
