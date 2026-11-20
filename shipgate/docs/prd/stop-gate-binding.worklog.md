---
type: worklog
title: "Worklog: the Stop gate binds a worklog to its stream"
created: 2026-11-19
updated: 2026-11-19
tags:
  - worklog
  - shipgate
  - journal
  - hooks
status: done
prd: none — bug fix (#21); the issue and ADR 0020 carry the requirements
related:
  - ../adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md
---

# Worklog: the Stop gate binds a worklog to its stream

Issue #21: the Stop gate has never blocked a session. This worklog covers the issue's steps
1 to 3. Step 4, the retarget of the gate, becomes its own issue after one month of data.

---

# Root cause

Rules A and B of `journal.py check` looked for the flow on a stream named
`feature/<artifact file name>`, or on the stream of the `artifact-written` row, which is
always the tool's own stream. Since v0.11 a stream is named for its branch. So the
tracked-flow guard never passed, and both rules skipped with no finding.

- Reproduced end to end with SessionStart, the Edit capture and the Stop hook, in throwaway
  projects. Stream `feature/feat`: `check` exits 5 and the hook blocks. Streams `feat/feat`
  and `fix/1290-date-off-by-one`: `check` exits 0 and the hook prints no decision.
- This repo's journal: 40 work streams, 0 named `feature/*`, 0 `gate-blocked` rows.
- Introducing commit: `a3e13f5` (v0.11). It moved every skill from
  `--stream feature/<slug>` to `--stream <branch>`. The rule code did not change.
- Why it slipped: the hook tests named their fixture stream `feature/<worklog name>`, the
  one shape that works, and the guard skips silently.
- Ruled out, each tested alone: authorship through a Bash edit, a linked git worktree, a
  swallowed `gate-blocked` append.

# Design

## Approach

ADR 0020. Rule A finds the streams that own a worklog through `position`'s binding (the
last worklog ref of a stream's events, else the slug-named worklog), with the old
`feature/<file name>` name as a fallback. A `deviation` of kind `gate-waived` clears the
boxes it names. Rule B is retired. Rule C stays and accepts a later `verify-run`.
`check --record` leaves a trace that `doctor` prints.

## Decisions

- The user: block old ticked boxes, with the waiver as the exit; retire rule B now;
  version 0.26.0.
- Executive, open to veto: keep rule C; no fallback to the stream the session drives; a
  worklog owned only by finished streams is skipped; scope is the issue's steps 1 to 3.

## API / contract changes

- `check --json` gains `skipped` and `waivers` beside `findings`. Exit codes do not change.
- `check --record` writes `meta.last_check`. Plain `check` stays read-only.
- `doctor --json` gains `stop_gate`: `last_check` and `last_block`.
- The `deviation` shape gains the list `task_ids`.
- The Stop hook's block text names the waiver commands in place of the old advice.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/scripts/journal.py` (`check`, `doctor`) and `shipgate/hooks/stop.py`.
- Hooks are a security-sensitive area: full security review before the verdict.
- A behaviour change: 0.26.0 in `plugin.json` and `marketplace.json`, and a CHANGELOG entry.
- Scripts stay Python 3.9 compatible.

---

# Build Plan

- [x] T001 — rule A binds through `position`'s binding; `skipped` in the check output — file(s): `scripts/journal.py`, `tests/test_journal.py`, `tests/test_hooks.py` — done when: the Stop hook blocks on `feat/x` (name binding) and on `fix/1290-date-off-by-one` (event binding), a worklog no stream owns is skipped and reported, and a finished stream is skipped
- [x] T002 — the waiver, and a rule C that can be cleared — file(s): `scripts/journal.py`, `hooks/stop.py`, tests — done when: a `gate-waived` deviation clears only the ids it names, the block text prints the waiver command, and a later `verify-run` clears rule C
- [x] T003 — retire rule B — file(s): `scripts/journal.py`, `skills/feature/SKILL.md`, `skills/clarify/SKILL.md`, `README.md`, tests — done when: a PRD written in clarify with no `gate-decision` does not block, and no skill or README line says it does
- [x] T004 — `check --record` and the `doctor` trace — file(s): `scripts/journal.py`, `hooks/stop.py`, tests — done when: `doctor` prints the last check and the last block, and plain `check` writes nothing
- [x] T005 — release: 0.26.0, CHANGELOG, README — file(s): `.claude-plugin/plugin.json`, `../.claude-plugin/marketplace.json`, `CHANGELOG.md`, `README.md` — done when: both version files say 0.26.0 and the full suite passes

## Deviations & notes (filled during implementation)

- Timing, `check` on this repo's journal (1,540 events): 0.10 s before the change, 0.09 s
  after. `run_check` alone takes 0.01 s (median over 12 sessions) and 0.02 s at most.
- The new `check` over the 12 sessions of this repo's journal that wrote an artifact: 0
  findings, 16 skips, all `finished`.
- The security review of the working tree found no vulnerability. It named two hardening
  points, both fixed here: a stream name that starts with `-` broke every printed command
  (now `--stream=<name>`), and a stream name with a line break reached the block text raw
  (now no command, and one line per finding).
- Three existing tests proved authorship through rule B. They now use the worklog and
  rule A: `TestTwoSessionsWatchOneArtifact`, `TestCheckReadsTheFold`, and the pinned Stop
  hook arguments in `TestProjectResolution`.

## Review round 1

Two lenses (correctness, conventions and design) through the review workflow: 20 found, 13
above the confidence floor, no BLOCKER or HIGH. A security review of the working tree ran
beside it: no vulnerability, two hardening points (H1, H2). All fixed in this change.

- F1 MEDIUM `shipgate/scripts/journal.py:2876` — A fourth binding that the ADR did not name: any work stream that held the capture row owned the worklog, and the legacy name overrode an event ref.
- F2 MEDIUM `shipgate/scripts/journal.py:2889` — A parent stream whose slug prefixes a child's worklog took that worklog, also when the child was finished.
- F3 MEDIUM `shipgate/README.md:243` — The README listed three of the six event types whose worklog refs bind a stream.
- F4 MEDIUM `shipgate/skills/feature/SKILL.md:356` — The skill said the gate checks a worklog "its stream owns" and that the waiver covers boxes only.
- F5 LOW `shipgate/scripts/journal.py:2714` — The `artifact_authors` docstring still named rules A and B.
- F6 LOW `shipgate/hooks/stop.py:103` — A findings list with no dict in it blocked with an empty reason.
- F7 LOW `shipgate/scripts/journal.py:3016` — The "record a verify-run first" hint read every owner stream, but the command appends to one.
- F8 LOW `shipgate/README.md:238` — The README's hook command left out `--json`.
- F9 LOW `shipgate/docs/adr/0010-a-user-row-records-its-writing-session.md:72` — ADR 0010 still described rule B and the old rule C, with no amendment note.
- F10 LOW `shipgate/skills/feature/SKILL.md:363` — An edited line ran past the paragraph's width.
- F11 LOW `shipgate/scripts/journal.py:4385` — `doctor` printed `None` for a stored last check of the wrong shape, and a bool passed as a count.
- F12 LOW `shipgate/scripts/journal.py:3075` — The printed waiver command cleared every finding with its placeholder note unchanged.
- F13 LOW `docs/ledger.md:5` — The two ledger lines describe a defect this change fixes. Triage removed them: ADR 0020, the CHANGELOG and the probe tests hold both traps.
- H1 LOW `shipgate/scripts/journal.py:2784` — A stream name that starts with `-` broke every printed command.
- H2 LOW `shipgate/hooks/stop.py:48` — A stream name with a line break reached the block text raw.

Below the floor, also fixed: the probe tests' capture helper now proves the hook recorded a
row; the two `doctor` lines use one shape; a probe docstring claimed too much; the timing
claim in the ADR now has its measurement above.

## Review round 2

One reviewer on the fix round: every round-1 item is fixed in the code. It found 3 new
items and 2 below the floor. All are closed. The orchestrator checked the round-2 fixes
alone: they touch two functions and three docs.

- G1 MEDIUM `shipgate/scripts/journal.py:1881` — `append --force` skipped the waiver check, so a forced waiver with the placeholder note cleared findings. `--force` no longer skips it, and `check` reads a waiver with no reason as none.
- G2 LOW `shipgate/scripts/journal.py:2811` — The stand-in text said "control character", but the test is `str.isprintable`, and a db path that does not print got the same text. The whole command is tested now, and the text says what the test is.
- G3 LOW `shipgate/scripts/journal.py:2937` — The name binding gives a stream only its newest slug-named file, and the skip detail did not say so. The detail and the ADR now do.
- G4 LOW `shipgate/scripts/journal.py:1647` — The waiver check refuses any `<...>` note, which is wider than "the placeholder" the docs named. The docs now say `<...>` placeholder.

## Rejected findings

- `shipgate/scripts/journal.py:2938` (LOW 50): The name binding compares paths exactly while the event binding accepts a tail. Rejected: both paths are relative to the project by construction, and `worklog_owners` makes an absolute path under the project relative first.
