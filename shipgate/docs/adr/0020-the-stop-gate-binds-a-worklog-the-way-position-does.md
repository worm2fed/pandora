---
type: adr
title: "0020. The Stop gate binds a worklog the way position does"
created: 2026-11-19
updated: 2026-11-23
tags:
  - adr
  - shipgate
  - journal
  - hooks
status: accepted
date: 2026-11-19
issue: "#21"
related:
  - "0008-artifact-authorship-resolved-at-read-time.md"
  - "0009-the-journal-computes-the-hud-position.md"
  - "0010-a-user-row-records-its-writing-session.md"
  - "../prd/stop-gate-binding.worklog.md"
---

# 0020. The Stop gate binds a worklog the way position does

> `journal.py check` finds the flow behind a worklog through the binding that `position`
> already uses: the stream whose own events name the worklog, else the stream whose slug
> names it. A `deviation` of kind `gate-waived` clears the boxes it names. The rule that
> gated a PRD written in clarify is retired. The user chose the block with a waiver, the
> retirement and the version; the other choices are executive and the user can veto them.

## Context

The Stop hook runs `journal.py check`. Rule A blocks a session that ticked Build Plan boxes
with its own write and recorded no `task-done`. In real use the gate never blocked: 0
`gate-blocked` rows in 9,449 events of seven journals, across 3,171 hook runs.

The cause is one lookup. Rule A looked for the flow on a stream named
`feature/<worklog file name>`, or on the stream that holds the `artifact-written` row. The
hooks file every such row on the tool's own stream. Since v0.11 the skills name a stream for
its branch (`feat/x`, `fix/1290-date-off-by-one`). So the guard "only gate a flow the
journal tracks" never passed, and the rule skipped with no finding. Rule B (a PRD written in
clarify with no `gate-decision`) used the same lookup and was dead the same way.

The hook tests named their fixture stream `feature/<worklog name>`, the one shape that
works, so the suite stayed green. The guard skips silently by design, so a dead rule looked
like full compliance.

Two more defects sat behind the first one:

- The block text told the session to record a `deviation` when a finding was not
  warranted. `check` read no deviation, so the same block came back on the next turn.
- Rule C (a `task-done` with no passing `verify-run` before it) can be reached only by a
  forced `task-done`, because `append` refuses the plain one. Its finding could never be
  cleared: a `verify-run` recorded afterwards did not count.

## Decision

1. **One binding.** A stream owns a worklog in one of three ways, tried in this order:
   - `event`: the stream's last worklog ref names it. The refs are those of
     `design-committed`, `design-queued`, `task-done`, `verify-run`, `review-verdict` and
     `gate-decision`, exactly as `position` reads them (ADR 0009);
   - `name`: the stream has no worklog ref, and the worklog is the one `position` would
     show for it: the newest file named for the stream's slug that no other live stream's
     events name;
   - `legacy`: the stream has no worklog ref and is named `feature/<worklog file name>`.
     This keeps a journal from before v0.11 gated.

   The most exact binding wins. A stream whose events name the worklog, live or finished,
   leaves nothing to a name. Among names, `<slug>.worklog.md` beats a prefix match, then
   the longer slug wins. So a parent stream `epic/auth` does not take the child's
   `auth-login.worklog.md`. A stream with no flow event owns nothing.

   Rule A reads `task-done` rows from the streams that own the worklog. The gate and the
   HUD's Plan tab therefore show the same tasks against the same stream. The gate is
   narrower in one case: `position` still shows a parent stream the child worklog that its
   slug prefixes, and the gate leaves that worklog to the more exact owner.
2. **No fallback to the session's stream.** A worklog that no stream owns stays ungated. A
   legacy worklog, or one a sync pulled in, cannot block a session.
3. **A finished stream is not gated.** A worklog owned only by terminal streams is skipped.
   A later edit of a closed flow's worklog must not reopen its bookkeeping.
4. **A skip is reported.** `check --json` carries `skipped`: each worklog the session wrote
   that the gate did not judge, with the reason. Exit codes do not change.
5. **A waiver clears a finding.** A `deviation` with `kind: gate-waived` and `task_ids` on
   an owning stream waives those boxes for rule A, and those `task-done` rows for rule C.
   `check --json` carries `waivers`: one command per stream. The Stop hook prints them in
   place of the old advice. The command holds a placeholder note. `append` refuses a
   waiver with no task ids, with an empty note or with a `<...>` placeholder note.
   `--force` does not skip that check, and `check` reads a waiver with no reason as
   none. So a waiver always records a reason. A printed command uses `--stream=<name>`.
   A stream name that holds a line break, or another character that does not print on
   one line, gets no command.
6. **Rule C can be cleared.** A passing `verify-run` that names the task counts wherever it
   sits in the stream, before or after the forced `task-done`.
7. **Rule B is retired.** No event names a PRD before `clarify-passed`, so this binding
   cannot reach it, and a binding by "the stream this session drives" can block a clean
   session. A replacement is decided later with data.
8. **The gate leaves a trace.** `check --record` overwrites one `meta` value,
   `last_check`: the time, the session, the finding count and the skip count. The Stop hook
   passes the flag. `doctor` prints that value and the last `gate-blocked` row. No event
   row is written per stop.

## Alternatives considered

- **Bind by the stream the session drives.** It needs no refs, so it also covers a worklog
  ticked before `design-committed`. It blocks a session that edits a worklog no flow owns,
  which is the false block the guard exists to prevent. Rejected.
- **File `artifact-written` rows on the branch's stream.** The hook would have to map a
  session to a stream at write time. ADR 0008 moved that decision to read time for a reason:
  every session's watcher sees every write. Rejected.
- **Gate only boxes ticked after the update.** It needs a recorded baseline per worklog.
  The waiver gives the same exit with no new state. Rejected by the user in favour of the
  waiver.
- **Keep rule B, bound by the session's stream.** In executive mode the decisions also live
  in the PRD, so a clean session could be blocked. Rejected by the user.

## Consequences

- A gate that never blocked can now block. After the update, a session that writes a
  worklog whose live stream lacks `task-done` rows for ticked boxes is blocked for all of
  them. The exits are the `task-done` rows or one waiver.
- `check` reads the worklog homes once more for the name binding, only for worklogs the
  session wrote. On a journal of 1,500 events the whole check stays near 0.1 s.
- A worklog ticked before any event names it, on a stream whose slug does not name it, is
  not gated until `design-committed` lands. `skipped` shows it.
- The name binding gives a stream one worklog: the newest file its slug names, as
  `position` shows it. An older slug-named file has no owner until an event names it.
- The Stop hook writes one `meta` value per stop. A failed write is ignored: the check
  result does not depend on it.
- The hook tests now run each rule on branch-named streams. The stream name
  `feature/<worklog name>` is one case among them, no longer the only one.

## Amendment (2026-11-23, #43): the slug without its issue id

A stream named for its branch often keeps the issue id in its slug: `fix/1290-date-off-by-one`
has the slug `1290-date-off-by-one`, which does not name `date-off-by-one.worklog.md`. Such a
stream had no worklog in `position`, and the Stop gate skipped its ticks as `no-stream`, until
an event named the worklog. A scaled-down flow with a worklog and no `design-committed` stayed
ungated.

So the name binding has a second, weaker slug: the slug without one leading issue id of ASCII
digits and a dash. `_stream_slugs` in `_journal/artifacts.py` gives both, most exact first,
and `position` and `check` both read it. `position` tries the slug without the id only when
the full slug leaves no free worklog. Among names, the rank is now: `<slug>.worklog.md` beats
a prefix match, the longer slug beats the shorter, and the full slug beats the slug without
its issue id. So `feat/demo` keeps `demo.worklog.md` when `fix/1290-demo` is live too.

This widens what the Stop gate can block. No hook file changed: the hook runs `check`. The
rejected alternative was skill text alone: the `workspace` and `design` skills would tell
a session to name the worklog for the full slug. It leaves every existing stream of that
form ungated.
