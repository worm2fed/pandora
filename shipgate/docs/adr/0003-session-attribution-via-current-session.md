---
type: adr
title: "0003. Canonical actors; session attribution from the last session-started"
created: 2026-09-02
updated: 2026-09-02
tags:
  - adr
status: accepted (label default amended by 0005)
date: 2026-09-02
issue: "none / ad-hoc"
related: ["../prd/journal-cost-and-workflows.md", "0001-sqlite-flow-journal.md"]
---

# 0003. Canonical actors; session attribution from the last session-started

> `actor` is `role[@label]` with role in `orchestrator | worker | user | hook | watcher`.
> When a skill append omits the label, `append` suffixes the session id the SessionStart
> hook last stored in `meta.current_session`. `check --session` matches events by
> `data.session` or by that suffix.

## Context

`check` only attributes an event to a session through `data.session` (hooks) or the raw
`actor` value (skills), so it expected skills to pass the session id as the actor. They
did not: the reference export has 262 NULL actors and eight spellings, and its Stop-gate
rule "PRD written at clarify with no gate-decision this session" could never see a
skill-written gate-decision. Meanwhile the *role* — who decided, executive or user — is
what the brief and the PRD want, and it was being lost in the same field. The session id
is not visible to the skill's shell, but the SessionStart hook does see it.

## Decision

Two facts, one field: `role@label`. Roles are a closed set, validated by `append` (usage
error otherwise); `orchestrator` is the default. The label is free text; when absent,
`append` reads `meta.current_session` — written by `session_start.py` on every
startup/resume — and suffixes it. `event_session()` returns `data.session` when present,
else the part after `@`. Hook-written events keep `actor=hook` and carry `data.session`
as today. Two roles never receive the session suffix (`SESSIONLESS_ROLES`): `watcher` is a
machine actor with no session, and `user` names a person — a bare `user` stays `user`, and
`stats` does not count `user@<label>` values as sessions.

## Alternatives considered

- **Require the session id explicitly** — the skill cannot see it without a hook handing
  it over through context, which every skill would then have to quote back.
- **Separate `session` column** — a schema migration for something the payload and the
  actor suffix express; `meta` already exists for exactly this class of process state.

## Consequences

Two concurrent sessions on one machine share one `current_session` and the later starter
wins; skill appends from the older session are attributed to the newer one. Acceptable
for a single-user tool, and an explicit `@label` overrides the default. *Amended by ADR 0005:*
the label now comes from the appending shell's `CLAUDE_CODE_SESSION_ID` when it is set, so
concurrent sessions keep their own; `meta.current_session` remains the fallback. Role becomes
queryable (`stats` groups by it), and the Stop gate's rule B starts working for skills.
