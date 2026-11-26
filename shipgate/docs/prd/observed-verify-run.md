---
type: prd
title: "PRD: verify-run records an observed run, not a claim"
created: 2026-11-25
updated: 2026-11-25
tags:
  - prd
  - shipgate
  - verify
  - hooks
status: clarified
issue: "#27 (shipgate), child of #37"
worklog: "./observed-verify-run.worklog.md"
related:
  - "../adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "../adr/0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "../adr/0022-the-context-nudge-rides-the-posttooluse-bash-hook.md"
  - "../adr/0010-a-user-row-records-its-writing-session.md"
  - "../adr/0008-artifact-authorship-resolved-at-read-time.md"
  - "../research/2026-11-15-agent-harness-audit.md"
---

# PRD: verify-run records an observed run, not a claim

> The hooks see each Bash run end. The journal keeps a fingerprint of the command and its
> exit status for the session. A `verify-run` names its commands, and the journal stores
> whether it saw each of them end with the exit status the row claims.

## Problem

The model types the `verify-run` payload itself. The shape requires only `outcome` and
`task_ids`. `task-done` and the ready verdict accept any such row, and no hook sees the test
run. A worker's evidence is the text of its report.

Evidence from issue #27 and the research note (counts from 7 flow journals, 9,449 events,
2026-08-20 to 2026-11-15):

- All seven journals: 935 `verify-run` rows pass and 9 fail.
- The main journal: 602 rows. 591 pass, 2 fail, 9 carry no outcome. 30 carry an exit code.
- Every one of 1,320 `task-done` ids has a passing `verify-run`. The row works as a key to
  the gate, not as evidence.
- `verify` says "record failures too". The data shows that nobody follows this prose rule.

Evidence from this design session (this repository's own journal, 351 `verify-run` rows):

- 108 rows carry a `commands` list. 263 command strings have a median of 46 characters, a
  90th percentile of 83 and a maximum of 257.
- A payload has a median of 273 bytes and a maximum of 807. The cap is 1,024 bytes.

## Goals & non-goals

**Goals**

- A `verify-run` row says whether the journal saw each command it names end with the exit
  status it claims, in the same session.
- A failing run leaves a trace, even when nobody records it.
- A worker's run counts as evidence for the orchestrator without a relay of report text.
- `stats` shows how many `verify-run` rows rest on an observed run, so the #37 retro can
  measure the share.
- A project that is not journaled pays nothing, and a journaled one pays a few milliseconds.

**Non-goals**

- No gate changes. `task-done` and the ready verdict accept the rows they accept today. A
  gate on `observed` waits for one month of data, as #42 does for the Stop gate.
- No defence against a model that sets out to forge a run with its shell. The model can
  write any file the hooks write. The forgery net is parked until about 2026-12-22 (#37).
- No proof of what a command proves. A run of `pytest | tail -5` ends with the exit status
  of `tail`. The verify skill covers that.
- No proof of where a command ran. The fingerprint covers the command text only.
- No observation of background runs. Their exit status reaches no hook.
- No change to rows already in a journal, and no new eval case.

## Users & stories

- As the user, I want to see how many verify runs the journal actually saw, so that I know
  how far to trust a "done".
- As the orchestrator, I want the journal to confirm my evidence, so that a stale or
  mistyped command shows up at once and not in review.
- As the orchestrator, I want to cite a worker's test run, so that I do not re-run it or
  copy its report text.
- As a user of shipgate in another project, I want my Bash calls to stay as fast as before,
  and nothing written when the project does not use shipgate.

## Functional requirements

- **FR-001** — In a journaled project, each foreground Bash run that ends with a known exit
  status is recorded for its session. The record holds a fingerprint of the command as the
  model typed it and the exit status. It holds no command text and no output.
- **FR-002** — A run whose exit status is unknown is recorded as started only, and matches
  no citation: a background run, an interrupted run, a run the user denied, and a run that
  Claude Code reports with an interpretation and no code (`grep`, `diff` or `test` with exit
  status 1).
- **FR-003** — A subagent's run, a worker's included, is recorded under the session that
  started the subagent.
- **FR-004** — In a project that is not journaled, or that declares no journal, the hooks
  record nothing and open no project file. A failure to record never changes a Bash call's
  result and never prints.
- **FR-005** — A `verify-run` carries a `commands` list. Each item names a command as the
  model typed it (`cmd`) and its exit status (`exit`). A row without the list is refused.
- **FR-006** — A check that is no Bash command (a manual UI check, an MCP tool, a read of a
  file) has a named way out: an empty `commands` list, with `outcome` and the check in
  `scope`. Such a row is stored `observed: false`, because nothing could be observed.
- **FR-007** — `outcome` may be left out when `commands` has items. The journal then
  derives it: `pass` when every exit status is 0, else `fail`. An `outcome` that disagrees
  with the exit statuses of its own payload is refused. With an empty list, `outcome` is
  required.
- **FR-008** — At append, the journal decides for each named command whether the appending
  session ran it with the named exit status. It stores `observed: true` on the row when every
  command matches, and `observed: false` otherwise. A value the caller sends is replaced.
- **FR-009** — A row whose commands do not all match is stored, not refused. The append
  prints one line per unmatched command that names it and says how to make it match.
- **FR-010** — A command whose newest run in the session ended with another exit status
  than the one named is contradicted. The row is stored `observed: false` with a mark that
  `stats` counts. It is not refused, and it still satisfies the gates that a passing row
  satisfies today. A gate on this mark is decided in the December review, with #42.
- **FR-011** — The record of one session has a size bound. The journal deletes old records
  at moments it already prunes, and `doctor` reports what is kept.
- **FR-012** — `journal.py stats` shows, per stream and in total, the `verify-run` rows
  stored as observed, the rows stored as not observed, the contradicted rows among them,
  the rows from before this release, and the observed share.
- **FR-013** — The `verify` skill says how to name a command so that it matches: the exact
  text, in this session, in the foreground. It says that a background run is never
  observed, so a run that must count runs in the foreground. It names the way out of
  FR-006. The `implement` and `model-tiers` skills say how a worker reports its command and
  how the orchestrator cites it.
- **FR-014** — Rows without `observed` stay valid. No reader treats a missing value as
  false.
- **FR-015** — A run that the record cannot tie to the appending session counts as not
  observed, never as observed. This covers a run before a new session id (a `/clear`, a
  fork, a new session) and a run of an agent whose hooks carry another session id. `stats`
  shows such a row under "not observed".
- **FR-016** — No shipgate-hud file changes. A follow-up issue decides on the HUD with one
  month of data; capture files it.

## Success criteria

- **SC-001** — Tests drive the hooks with the payloads the probe recorded. A passing run, a
  run that exits 3, a timed-out run (143) and a subagent's run each give a citable record. A
  background run, an interrupted run and an interpreted run give none.
- **SC-002** — In a project with no settings file, an audit-hook test shows that the
  PreToolUse and PostToolUse hooks open no file outside the Python standard library and the
  plugin. The median wall time of each hook on a plain Bash call rises by at most 1 ms there,
  and by at most 3 ms in a journaled project. The worklog records the numbers measured
  before and after the change.
- **SC-003** — A command that another PreToolUse hook rewrote before it ran still matches
  the command as the model typed it.
- **SC-004** — A `verify-run` that cites an observed command is stored `observed: true`. One
  that cites a command the session did not run is stored `observed: false` with a one-line
  notice. One whose cited command ran last with another exit status is stored
  `observed: false` and marked contradicted. A caller's own `observed` never survives. A row
  with no `commands` key, or with an `outcome` that disagrees with its exit statuses, is
  refused.
- **SC-005** — The record of one session never passes 512 KB on disk. A record older than 7
  days is deleted at the next `flow-started` or terminal append in any project. `doctor`
  lists the count, the size and what the next prune deletes.
- **SC-006** — `journal.py stats` and `stats --json` show the observed, not observed,
  contradicted and not recorded counts and the share for each stream and in total.
- **SC-007** — The full suite passes. Prose tests pin the new skill text. The full
  `/security-review` and the release check for a hook change pass.

## Constraints & assumptions

- The probe of 2026-11-25 (Claude Code 2.1.332, nested `claude -p` on Haiku, scratch
  logging hooks) showed: [source: probe 2026-11-25]
  - A run with exit status 0 fires PostToolUse. `tool_response` holds `stdout`, `stderr`,
    `interrupted`, `isImage` and `noOutputExpected`, and no exit code.
  - A run with exit status N fires PostToolUseFailure with no `tool_response`. Its `error`
    is `Exit code N`, then the output. A timed-out run gives `Exit code 143`. Exit 127
    (command not found) is the same form.
  - `grep` with no match, `diff` of two different files and a false `test` exit 1 but fire
    PostToolUse with `returnCodeInterpretation` and no exit code.
  - A background run fires PostToolUse at launch with `backgroundTaskId`. Its exit status
    reaches only the model, through the task notification. No hook fires at its end.
  - A subagent's Bash hooks carry the parent's `session_id`, in the payload and in
    `CLAUDE_CODE_SESSION_ID`, plus `agent_id` and `agent_type`.
  - A run the permission check denies fires neither PostToolUse nor PostToolUseFailure.
  - When a PreToolUse hook rewrites a command (`updatedInput`), PostToolUse sees the
    rewritten text. A PreToolUse hook that runs beside it sees the text the model typed.
- A command rewrite is common. A rewrite hook in use on the maintainer's machine changes
  41 of the 420 commands cited in this repository's journal. It also changes most test
  runners of other languages: `pytest`, `cargo test`, `go test`, `make test`, `vitest`,
  `jest`, `rspec` and `gradlew test`. [source: probe 2026-11-25]
- Hook cost today, median of 15 runs on a plain Bash call: PreToolUse 44 ms, PostToolUse
  28 ms without a journal and 37 ms with one, a bare Python start 24 ms. Importing `hashlib`
  costs 5.2 ms. Importing `_blake2` alone costs 1.0 ms. [source: bench 2026-11-25]
- The PreToolUse hook reads no file on its fast path today, and a test pins that
  (`shipgate/tests/test_hooks.py:3539`). [source: repo]
- Issue #27 proposes "stored, not refused" for a row with no observed run, and asks for
  `commands[].cmd` and `commands[].exit` as required fields. [source: issue #27]
- Journals in use hold 935 rows with no citation. Older plugin versions keep writing the old
  shape through their own `journal.py`. [source: issue #27, lead brief]
- The 1 KB cap applies to the normalized payload of a work stream, before the journal adds
  its own keys (`shipgate/scripts/_journal/append.py:169-178`). [source: repo]
- Hooks are a security-sensitive area. A hook change takes the full `/security-review` and
  the release check. Issue #48 already tracks a compile on every Bash call; this change adds
  no compile there. Scripts stay Python 3.9 compatible. [source: CLAUDE.md, issue #37]
- A test that runs a hook or `journal.py` in a subprocess gives it a temporary
  `CLAUDE_CONFIG_DIR`. [source: CLAUDE.md]
- The user's decisions of 2026-11-25, relayed by the lead: [source: the user, via the lead]
  - Hook contract: the PreToolUse hook records the run's `tool_use_id` with a hash of the
    command the model typed. PostToolUse and a newly registered PostToolUseFailure record
    the `tool_use_id` with the exit status. The journal joins them.
  - Event shape: `commands` with `cmd` and `exit` is required, and `outcome` is derived from
    the exit statuses. An `outcome` that disagrees with them is refused. A pass that the
    newest observed run contradicts is stored `observed: false`, marked for `stats`, and
    measured for one month. The reason: a refusal is a new gate, and it misfires after a
    failed run, a fix and a background re-run, because no hook sees a background run end.
  - Scope: no shipgate-hud change. `journal.py stats` shows the counts and the share.
    Capture files a follow-up issue for the HUD.
  - Citation: the exact command text as typed, plus its exit status. The record holds
    hashes only.
- The lead's design points of 2026-11-25: a check that is no Bash command needs a named
  way out; the skill text says that a background run is never observed; the PRD names
  what `stats` shows for Workflow agents and for a new session id, which the probe did not
  cover; the PreToolUse write stays off the path of #48's compile cost, and the hook is
  measured before and after. [source: the lead]

## Assumptions (executive)

- [behaviour] [no source found in the issue, its comments and the skills] How does a verify-run cite an observed run? → by the exact command text the model typed and its exit status; the journal finds the newest run of that command in the appending session, and there is no run id to copy — a run id never reaches the model, and the text is what the model already has [kept by the user]
- [behaviour] [no source found in the skills] How does a worker's run reach the orchestrator? → the worker reports the exact command string and its exit status, and the orchestrator cites them in its own `verify-run`; the subagent's run is already in the session's record — no relay of output, and the journal checks the citation [kept by the user]
- [data] [no source found in the journal code] How do stats and readers treat rows written before this release? → as "not recorded", counted apart, never as "not observed" — an old row did not fail a check, it predates it [kept by the user]
- [behaviour] [no source found in the settings schema] Which setting turns the observation off? → the existing `enforce.auto_capture`, with no new setting — observation is one more thing the hooks capture [kept by the user]
- [technical] [source: shipgate/scripts/_journal/screens.py:54] Where does the record live? → under the Claude config directory, outside every repository, one file per session — the evidence root of ADR 0031 set the pattern, and a cloned repository cannot plant a file there [kept by the user]
- [technical] [no source found in the hook code] What does one record hold? → the run's `tool_use_id` with a 64-bit fingerprint of the command when it starts, and the `tool_use_id` with the exit status when it ends; no time, no agent id, no text — the join needs nothing more [kept by the user]
- [technical] [no source found in the issue and the ADRs] How large may a session's record grow, and how long does it stay? → 256 KB per file with one older file kept, deleted after 7 days — a session uses its record only while it runs [kept by the user]
- [technical] [source: shipgate/tests/test_hooks.py:48] How do hook tests avoid the developer's real config directory? → `run_hook` gives each hook a temporary `CLAUDE_CONFIG_DIR` by default — the hooks now write there [kept by the user]
- [technical] [no source found in the issue and the hook code] Does the fingerprint cover the working directory? → no, the command text only — a `cd` inside the command is part of the text, and a stricter key adds a silent failure [kept by the user]
- [technical] [no source found in the issue and the eval suite] Is an eval case needed? → no; unit and prose tests cover the mechanism, and `stats` measures the citation behaviour in real use on both models [kept by the user]

## Open questions

None. The user answered the three escalations through the lead on 2026-11-25; the
decisions are under Constraints & assumptions.
