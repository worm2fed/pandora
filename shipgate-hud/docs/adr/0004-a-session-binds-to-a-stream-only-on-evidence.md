---
type: adr
title: "0004. A session binds to a stream only on evidence"
created: 2026-10-20
updated: 2026-10-20
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-20
issue: none / ad-hoc
related:
  - "../prd/session-stream-attribution.worklog.md"
  - "0005-the-publish-gate-checks-the-published-branch.md"
---

# 0004. A session binds to a stream only on evidence

> The HUD shows a stream as the session's own only when the session wrote to it, the
> session root's branch carries it, or the live streams the nested repos name are exactly one.

## Context

The HUD took the newest stream among the umbrella's nested branches for a session that wrote
to no stream. Those nested checkouts are shared by other sessions. So an idle session at an
umbrella root showed another session's work, and the label moved whenever an unrelated
stream moved. The publish gate trusted that guess. A failed probe also came back as "no
stream", and the gate passed it.

## Decision

The binding is a closed union: `Session`, `Branch` or `Unbound` (with the nearby live
streams). A failed probe is a `Failed` refresh, never `Unbound`.
1. **Session.** journal.py's `session_match`: the live stream this session last wrote to.
2. **Branch.** The session root's own branch matches a stream.
3. **Nested.** The HUD passes all nested branches in one `status` call. journal.py binds
   only when the live streams they name are exactly one. Dormant and finished streams do
   not count.
4. **Unbound.** No band. The pane names the nearby live streams and says that this session
   drives none.

The walk does not look below `.worktrees/<name>`. A session opened inside an issue worktree
finds that worktree's repos as its own nested repos.

## Alternatives considered

- **No nested fallback.** Never wrong, but a teammate session opened in an issue worktree
  (a detached root with every repo on one branch) shows nothing until its first write.
- **Keep the guess but draw it dim.** The label would still move with unrelated streams,
  and the UI would need more work.

## Consequences

- An umbrella root with several live nested streams shows no band until the session writes
  its first event. After `/clear` (a new session id) the same applies.
- An umbrella root with exactly one live nested stream still binds to it.
- The SessionStart brief and the HUD agree, because journal.py owns the rule.
- Subagents share their parent's session id. Their writes move the parent's binding. That
  is out of scope here.
