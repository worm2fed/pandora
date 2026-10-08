---
type: adr
title: "0005. The session label comes from the appending shell; status --session"
created: 2026-10-08
updated: 2026-10-08
tags:
  - adr
status: accepted
date: 2026-10-08
issue: "none / ad-hoc"
related: ["0003-session-attribution-via-current-session.md", "../../../shipgate-hud/docs/adr/0001-sibling-plugin-fed-by-the-journal-cli.md"]
---

# 0005. The session label comes from the appending shell; status --session

> `append` labels an unlabelled actor with `CLAUDE_CODE_SESSION_ID` from its own environment,
> falling back to `meta.current_session`. `status --session ID` marks the live stream that
> session last wrote to itself (`session_match`) and renders it first, ahead of the branch's.

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
   unchanged.
2. **The session's position.** `status --session ID` finds the newest event whose
   `event_session()` is `ID` and whose role is not `hook`, across work streams; its stream is the
   session's unless that stream is finished, in which case nothing matches and the branch
   decides. Hook events are excluded because the hook files an artifact write under the
   checked-out branch's stream: that says where a file landed, not what the session drives.
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
keeps ADR 0003's behaviour.
