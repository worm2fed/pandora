---
type: worklog
title: "Worklog: an append with no session id records no session"
created: 2026-11-20
updated: 2026-11-21
tags:
  - worklog
  - shipgate
  - shipgate-hud
  - journal
status: done
prd: none — bug fix (#46); the issue and the ADR 0005 amendment carry the requirements
related:
  - ../adr/0005-session-label-from-the-shell-environment.md
  - ../adr/0010-a-user-row-records-its-writing-session.md
  - ../../../shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md
---

# Worklog: an append with no session id records no session

Issue #46, a child of #37: an append from a shell with no `CLAUDE_CODE_SESSION_ID` borrows
another session's id, and the status brief binds the wrong stream.

---

# Root cause

`appending_session` (`scripts/journal.py`) returned `CLAUDE_CODE_SESSION_ID`, else
`meta.current_session`. That key is one row for the whole journal, and every SessionStart
hook overwrites it. So a shell with no variable labelled its row, or a `user` row's
`recorded_by`, with the id of the session that started last. `session_stream` then bound
that session to the row's stream.

- Reproduced in a scratch journal: sessions A and B start in that order. A's sessionless
  `gate-decision` on `feat/a` got the actor `orchestrator@B`. A sessionless `user` row got
  `recorded_by` B. `status --session B --json` put `session_match` on `feat/a`, and `stats`
  counted two sessions on `feat/a`.
- Introducing commits: `046c758` (ADR 0003) made `meta.current_session` the label. `36dcec1`
  (ADR 0005) added the `status --session` binding and kept the key as the fallback. The
  repro binds the wrong stream at `36dcec1`; its parent has no `--session`. `d27a1da`
  (ADR 0010) fed the same fallback into `recorded_by`.
- Why it slipped: ADR 0005 named only "a manual run outside Claude Code" as a shell with no
  variable, and no test had two sessions with one sessionless append.

## Launch paths (probed on Claude Code 2.1.329)

| Path | `CLAUDE_CODE_SESSION_ID` |
|---|---|
| The Bash tool, `bash -c`, `zsh -c`, `sh -lc`, a Python subprocess, a background shell | the session's own id |
| A subagent's Bash | the parent session's id |
| Every hook (SessionStart, PreToolUse, PostToolUse, SessionEnd) | the payload's `session_id` |
| A `!` line, and a shell nested under it | the session's own id |
| A mod's `$.process.run` child | the host's own value: none, or the id of the session whose shell started this one (a teammate started from its lead's shell); `$.session.id()` returns the right id |
| A client older than 2.1.132 | none in the Bash tool (the changelog adds it in 2.1.132) |
| A shell outside Claude Code, or `env -i` | none |

A nested `claude -p` gets its own new id since 2.1.317. In six other journals, all six
dialog approvals carry `recorded_by`; three name a session that never wrote that stream.

# Design

## Decisions

- The user: an append with no session id records no session and binds nothing; it is not
  refused ("No session"). The HUD passes its session id to the approval run, as
  shipgate-hud 0.11.1 in the same PR ("Yes, in the same PR").
- The lead: `meta.current_session` and the hook's `session --set` stay as diagnostic
  plumbing; a follow-up issue retires them after #22 merges. Rows already written under a
  borrowed id stay as written; no repair event.

## API / contract changes

- `append` from a shell with no `CLAUDE_CODE_SESSION_ID`: a machine role stays bare, and a
  `user` row gets no `recorded_by`. An explicit `role@label` is unchanged.
- The HUD's approval run sets `CLAUDE_CODE_SESSION_ID` to `$.session.id()`, or blank when
  the engine gives no id.
- No hook, schema or output-shape change.

## CLAUDE.md / impact-map compliance

- Primary homes: `shipgate/scripts/journal.py` and `shipgate-hud/hooks/register.tsx`.
- No change under `hooks/` of shipgate; the HUD's `hooks/` is a mod module, reviewed by the
  fan.
- Version bumps: shipgate patch above `origin/main` at commit time, shipgate-hud 0.11.1,
  each in its `plugin.json` and `marketplace.json`.

---

# Build Plan

- [x] T001 — tests first: a sessionless append records no session — file(s): `tests/test_journal.py` — done when: new tests fail on the unfixed code (bare machine label, no `recorded_by`, B's brief does not bind A's stream, `check --session B` ignores a sessionless forced `task-done`, `stats` counts one session) and the three fallback tests are inverted
- [x] T002 — the fix: `appending_session` reads the environment only — file(s): `scripts/journal.py` — done when: T001's tests pass and `test_journal`, `test_hooks`, `test_attribution` and `test_hud_contract` pass
- [x] T003 — the HUD passes its session id to the approval run — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/publish.test.ts` or `register.test.ts` — done when: a test sees `env.CLAUDE_CODE_SESSION_ID` on the approval's `process.run`, blank when the engine gives a blank or empty id, and `claude plugin test` plus `tsc` pass
- [x] T004 — docs and versions — file(s): ADR 0005 amendment, ADR 0003 and 0010 status notes, HUD ADR 0010 note, `README.md`, both `CHANGELOG.md`, both `plugin.json`, `marketplace.json` — done when: no doc says an append falls back to `meta.current_session`, and the versions match in both places
- T005 moved to #22 by the user's ruling (2026-11-21, "Ship #46 first, as 0.27.1"): #46 ships first as 0.27.1 on `main` at 0.27.0; #22 rebases onto it and adds the test that a sessionless read go is refused even when `meta.current_session` names the witness's session.

## #22 interplay, proved before the rebase

In a scratch copy of #22's working tree, a new `TestReadGo` test stores session A, writes a
witness of session A, and appends a read go from a shell with no session id. On #22 as it is,
the append exits 0: the label borrows A from `meta.current_session`, and the witness check
passes. With this fix's one-line change to `appending_session`, the same read go is refused
("another session"), for the default actor and for `--actor user`. `TestReadGo` and
`TestApprovalRowsNameTheirOwnSession` pass: 14 tests. #22 adds this test when it rebases
onto #46.

---

# Review

## Review round 1

Workflow run `wf_a7bcd645-59d`: three lenses (correctness, conventions+design,
simplicity+security) on Opus, `verify: high-only`. Counts: found 16, deduped 15, candidates
1, refuters 0, unverified 0, survivors 1, killed 0. No BLOCKER or HIGH. The orchestrator read
each below-floor finding and promoted one on a live probe. A separate reviewer applied the
built-in security review's criteria to `git diff origin/main`, because the diff touches
`shipgate-hud/hooks/`: no finding at confidence 8 or above.

- F1 MEDIUM `shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md:9` — the amendment did not follow the repo's form (version in the status, an amendment line under the summary); fixed.
- F2 MEDIUM `shipgate-hud/hooks/register.tsx:1546` — with no id from the engine the approval run set no variable, so its child inherited the host's value, which a live probe showed can be a parent session's id; fixed: the run always sets the variable, blank when there is no id.
- F3 LOW `shipgate/docs/adr/0005-session-label-from-the-shell-environment.md:8` — the status and the summary line named no version; fixed.
- F4 LOW `shipgate/docs/adr/0010-a-user-row-records-its-writing-session.md:4` — ADR 0003 and 0010 changed without an `updated:` bump; fixed in both.
- F5 LOW `shipgate/scripts/journal.py:5533` — the `session` command's text output still said "current session" after its help text changed; fixed.
- F6 LOW `shipgate-hud/hooks/publish.ts:1283` — the `approvalEnv` comment cited the wrong ADR; fixed.
- F7 LOW `shipgate-hud/CHANGELOG.md:5` — the entry had no dependency or tests paragraph, unlike recent HUD entries; fixed.
- F8 LOW `shipgate/docs/prd/append-borrows-session.worklog.md:93` — T003's done-when named a null id that the test did not reach; fixed with F2's wording.

### Rejected findings

- `shipgate/tests/test_journal.py:2961` (LOW 50): a third per-class helper for an append with a session; each helper binds its own class's stream and type, and a shared one would need more parameters than it saves.
- `shipgate/tests/test_journal.py:786` (LOW 40): neighbouring test names keep "current_session"; they test that the variable wins over the stored value, which stays true.
- `shipgate/scripts/journal.py:873` (LOW 30): the label trusts one environment variable; the environment is trusted, and an explicit `role@label` was never authenticated either.
- `shipgate-hud/hooks/register.tsx:1541` (LOW 25): the HUD tests cannot tell a replaced environment from a merged one; the live probe can, and the run with `env` still found `python3` and wrote its row.
- `shipgate-hud/hooks/publish.ts:1286` (LOW 20): the variable name is written in two languages; the name is Claude Code's, and the live probe pins it.
- `shipgate-hud/tests/register.test.ts:1578` (LOW 15): no test for a `$.session.id()` that throws; `sessionIdOf` maps a rejection and a blank id to the same null, which the blank and empty cases reach.

### Deferred

- `shipgate/skills/feature/SKILL.md:355` (LOW 45): the skill says an omitted label takes "the current session". That is true in every shell Claude Code starts. A skill text change is judged on both session models (#37), so it goes to the follow-up issue that retires `meta.current_session`.
