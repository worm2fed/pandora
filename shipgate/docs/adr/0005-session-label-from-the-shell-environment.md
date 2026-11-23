---
type: adr
title: "0005. The session label comes from the appending shell; status --session"
created: 2026-10-08
updated: 2026-11-23
tags:
  - adr
status: accepted (decisions 1 and 2 amended by 0010; amended 2026-11-20, shipgate 0.27.1; amended 2026-11-23, shipgate 0.30.3)
date: 2026-10-08
issue: "none / ad-hoc"
related: ["0003-session-attribution-via-current-session.md", "../../../shipgate-hud/docs/adr/0001-sibling-plugin-fed-by-the-journal-cli.md"]
---

# 0005. The session label comes from the appending shell; status --session

> `append` labels an unlabelled actor with `CLAUDE_CODE_SESSION_ID` from its own environment.
> `status --session ID` marks the live stream that session last wrote to itself
> (`session_match`) and renders it first, ahead of the branch's.
>
> **Amended 2026-11-20 (shipgate 0.27.1, #46):** the fallback to `meta.current_session` is retired. An append
> from a shell with no `CLAUDE_CODE_SESSION_ID` records no session. See the Amendment
> section.
>
> **Amended 2026-11-23 (shipgate 0.30.3, #51):** the hook no longer stores the session, and
> `journal.py session` is a no-op for one release. See the second amendment.

## Context

ADR 0003 took the label from `meta.current_session`, which the SessionStart hook overwrites
on every start: with two sessions open on one project, the later starter's id labels the
other's appends. That was tolerable while nothing read the label but the Stop gate. The HUD
then needed "which stream is this session driving", and keyed it off the checked-out branch —
wrong whenever the stream has no branch (an epic's planning stream; a stream opened on `main`
before `workspace` makes its branch) and, in an umbrella, wrong in a way that shows another
session's stream. Claude Code sets `CLAUDE_CODE_SESSION_ID` in every shell it starts, and a
subagent's shell carries its parent's id, so a worker's append still belongs to the session
that dispatched it.

## Decision

1. **Label source.** Explicit `role@label` first, then `data.session` (hook events keep the bare
   role), then `CLAUDE_CODE_SESSION_ID`, then `meta.current_session`. `SESSIONLESS_ROLES` are
   unchanged. *Amended by ADR 0010:* a `user` row stays unlabelled and records the same
   session as `data.recorded_by` instead. *Amended 2026-11-20 (#46):* the last source,
   `meta.current_session`, is retired; with no variable the row records no session.
2. **The session's position.** `status --session ID` finds the newest event whose
   `event_session()` is `ID` and whose role is not `hook`, across work streams; its stream is the
   session's unless that stream is finished, in which case nothing matches and the branch
   decides. Hook events are excluded because the hook files an artifact write under the
   checked-out branch's stream: that says where a file landed, not what the session drives.
   *Amended by ADR 0010:* `event_session()` reads a `user` row's `data.recorded_by`, and
   never reads the label of a `user` or `watcher` actor.
3. **Policy in journal.py.** The HUD passes its own `$.session.id()` and picks `session_match`,
   then `branch_match` — as with `--nested-branch`, a consumer holds no policy.

## Alternatives considered

- **The HUD reads `log --json` and finds its session's events itself** — puts the rule in a
  consumer and fetches every event per refresh.
- **The session declares its stream (a `meta` key per session, or an event)** — one more thing
  every phase skill must remember to write; the appends already say it.
- **Keep branch-only and document the limit** — leaves the HUD wrong for epic planning, and for
  every parallel session in an umbrella.

## Consequences

Parallel sessions on one project each see their own stream, and `check --session` stops
crediting one session's events to another. A session that has written nothing yet (a fresh
start, or after `/clear`, which starts a new id) still sees the checkout's stream until its
first append. A `journal.py` older than `--session` refuses the flag; the HUD then asks by
branch alone. An append from a shell outside Claude Code (a manual run) has no variable and
keeps ADR 0003's behaviour. *Amended 2026-11-20 (#46):* such an append now records no
session.

## Amendment (2026-11-20, #46): an append with no session id records no session

### Context

`meta.current_session` is one row for the whole journal. Every SessionStart hook overwrites
it, and since 0.25.1 the hook also runs on `/clear` and on a compaction. So the key names the
session that started last. A shell with no `CLAUDE_CODE_SESSION_ID` labelled its row with
that id, and decision 2 then bound that session to the row's stream. In a scratch journal,
sessions A and B started in that order. A's append from such a shell got the actor
`orchestrator@B`, and B's brief led with A's stream. A `user` row got `recorded_by` B, by
the same fallback (ADR 0010). One real journal had two sessions on 40 of its 84 work streams.

Which shells have no variable was probed on Claude Code 2.1.329:

| Launch path | `CLAUDE_CODE_SESSION_ID` |
|---|---|
| The Bash tool, `bash -c`, `zsh -c`, `sh -lc`, a Python subprocess, a background shell | the session's own id |
| A subagent's Bash | the parent session's id |
| Every hook (SessionStart, PreToolUse, PostToolUse, SessionEnd) | the payload's `session_id` |
| A `!` line, and a shell nested under it | the session's own id |
| A mod's `$.process.run` child | the host process's own value: none, or the id of the session whose shell started this one (a teammate started from its lead's shell); `$.session.id()` returns the right id |
| A client older than 2.1.132 | none in the Bash tool (2.1.132 added the variable) |
| A shell outside Claude Code, or `env -i` | none |

A nested `claude -p` gets its own new id since 2.1.317. shipgate-hud's "Approve publishing"
append ran in a mod's `$.process.run` child. So a dialog approval took the stored id, or,
in a session started from another session's shell, that parent session's id. In
six other journals, three of six dialog approvals named a session that never wrote that
stream.

### Decision

1. **The label source.** Explicit `role@label` first, then `data.session`, then
   `CLAUDE_CODE_SESSION_ID`. A blank variable counts as none. `meta.current_session` is
   never read as the appending session.
2. **A row with no session.** A machine role stays bare (`orchestrator`, `worker`). A
   `user` row gets no `recorded_by`. The implied `phase-entered` and the automatic
   `deviation` of the same append follow. `event_session` returns None for such a row, so
   `status --session`, `check` and `stats` count it for no session. The append is not
   refused: a manual run, a mod's run and an older client still record.
3. **`meta.current_session` stays as a diagnostic.** The SessionStart hook still writes it,
   and `session --get` still prints it: the session that started last. A follow-up issue
   retires the key and the hook call after #22 merges.
4. **Rows already written stay as written.** No repair event. Nothing marks a label that
   came from the fallback, so a repair would be a claim, not a computed fact. An event that
   moves a row to a session would also be a way to forge one. The binding heals: it is the
   session's newest own row, so the session's next own append moves it back, and a finished
   stream releases it.
5. **The HUD names its session.** shipgate-hud 0.11.1 runs the approval append with
   `CLAUDE_CODE_SESSION_ID` set to `$.session.id()`, or blank when the engine gives no id
   (HUD ADR 0010). So a dialog approval records the session that approved, as ADR 0010
   says, and never an id the mod's child inherited.

### Consequences

Two sessions on one journal no longer label each other's rows, whatever starts last. A row
from a shell with no variable binds no stream, and the session's brief falls back to the
branch until it writes a row of its own. Rule C of the Stop gate does not see a forced
`task-done` with no session; before, it blamed the session that started last. A go of the
approval path (ADR 0023) appended with no session names no session, so it can never match a
witness through a borrowed id. `stats` and `check` counts on rows written before this change
stay as written.

## Amendment (2026-11-23, #51): the stored session is retired

### Context

Decision 3 of the amendment above kept `meta.current_session` as a diagnostic: the
SessionStart hook wrote it, and `session --get` printed it. Since #46 no append reads it.
The hook still ran `journal.py session --set` on every start. That was one subprocess per
start for a value that nothing reads. When the call failed, the hook told the session that
its appends "will carry no session label", which was no longer true. The Bash tool's shell
carries `CLAUDE_CODE_SESSION_ID` since Claude Code 2.1.132, so no skill needs the stored
value either.

### Decision

1. **The hook stops storing the session.** The SessionStart hook no longer runs
   `session --set` and no longer adds the attribution notice. It still passes the session
   id to `status --session`.
2. **`journal.py session` stays one release as a no-op.** It accepts `--set ID`, `--get`
   and `--json` as before. It reads no sidecar, opens no journal, writes nothing and
   exits 0. It prints that it is retired; with `--json` it prints
   `{"current_session": null, "retired": true}`. A later release removes it. A removal
   now would change the CLI contract: a user's script that still calls the command would
   fail with a usage error. In this repository only the hook
   called it: shipgate-hud, the skills and the evals never did.
3. **Old journals keep the row.** Nothing reads or writes `meta.current_session`, so no
   migration removes it. The tests that prove such a row never labels an append write it
   with SQL.

### Consequences

A session start costs one journal run less. A journal created from now on holds no
`current_session` row. Decision 3 of the amendment of 2026-11-20 is retired; the rest of
this ADR stands.
