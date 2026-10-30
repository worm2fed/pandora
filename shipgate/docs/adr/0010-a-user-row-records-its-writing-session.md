---
type: adr
title: "0010. A user row records the session that wrote it"
created: 2026-10-30
updated: 2026-10-30
tags:
  - adr
  - shipgate
status: accepted
date: 2026-10-30
issue: "#9"
related: ["0003-session-attribution-via-current-session.md", "0005-session-label-from-the-shell-environment.md"]
---

# 0010. A user row records the session that wrote it

> `append` keeps a `user` actor bare and writes the appending session into the payload as
> `data.recorded_by`. `event_session` reads it on a `user` row after `data.session`, and
> never reads the label of a sessionless role. Amends ADR 0005, decisions 1 and 2.

## Context

ADR 0005 binds a session to the stream it last wrote to itself. `event_session` finds the
session of a row from `data.session` or from the actor label. `user` and `watcher` are
sessionless roles: `append` never labels them, because a `user` label names a person and the
watcher runs outside any session.

The `feature` skill records the user's own decisions with `--actor user`. A session that
opens a stream and records only user decisions so far has no row that names it. In an
umbrella checkout whose nested branches name two live streams, the branch rule binds nothing.
The session's own writes are then the only signal, and `status --session` finds none, so the
HUD says the session drives no stream. The Stop gate's rule B has the same gap: a session
that wrote a PRD and recorded only user gate decisions is blocked for "no gate-decision".

## Decision

1. **The actor stays `user`.** The role says who decided. The label, when given, still names
   a person.
2. **The payload names the writing session.** For a `user` row, `append` writes
   `data.recorded_by`: `CLAUDE_CODE_SESSION_ID`, else `meta.current_session`, the same source
   ADR 0005 uses for a machine label. The journal owns the key: `append` drops any value
   the caller passed, on every role, so a payload cannot name another session. A row
   appended with no session at all gets no key. The implied `phase-entered` row gets the
   same value. The key is not `raised_by`: a gate decision's `raised_by: user` says a person
   raised the point, and `recorded_by` names the session that wrote the row.
3. **`event_session` reads it.** The order is `data.session`, then `data.recorded_by` on a
   `user` row only, then the actor label of a machine role. The label of a `user` or
   `watcher` actor is never read: it names a person or a watcher. So `status --session`
   (`session_match`), `check --session` and `stats` count the session that recorded a user
   decision, and none of them counts a `user@` or `watcher@` label.
4. **The watcher stays sessionless.** It has no session to record.
5. **The key is outside the payload cap.** `append` adds it after the 1 KB check, so it never
   refuses a payload the caller kept inside the cap.

## Alternatives considered

- **A `recorded_by` column.** It needs schema migration 2, a wider `Event`, and export and
  import changes, for one optional string. Hook rows already carry their session in the
  payload, so the payload is the precedent.
- **Label a bare `user` with the session.** `user@<session id>` would claim a person is a
  session, and the `stats` rule that drops `user` labels would then drop real sessions too.
- **Count `user` rows by actor label in the HUD.** The binding rule lives in `journal.py`
  (ADR 0005); a consumer holds no policy.

## Consequences

A session whose only writes are user decisions binds to its stream, and the HUD shows it with
no HUD change, because the HUD already reads `session_match`. Rows written before this change
carry no key and stay sessionless. A `user` payload grows by about 60 bytes. A `log` reader
sees the key in `data`.

The Stop gate now reads a session's `user` rows. Rule B accepts a user gate decision the
session recorded. Rule C checks a `task-done` the session recorded for the user: a forced one
with no passing `verify-run` before it blocks that session, as an orchestrator's always did.

A `user@<session id>` or `watcher@<label>` actor no longer binds or counts a session. Before,
`stats` counted a `watcher@` label as a session, and `status --session` matched a `user@`
label as if it were a session id.
