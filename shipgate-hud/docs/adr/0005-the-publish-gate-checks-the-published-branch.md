---
type: adr
title: "0005. The publish gate checks the published branch's stream"
created: 2026-10-20
updated: 2026-10-20
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-20
issue: none / ad-hoc
related:
  - "0004-a-session-binds-to-a-stream-only-on-evidence.md"
  - "../prd/session-stream-attribution.worklog.md"
---

# 0005. The publish gate checks the published branch's stream

> The gate resolves which branch a publish command publishes and holds it against that
> branch's stream. It falls back to the session's bound stream only when it cannot resolve
> the target.

## Context

The gate read the band's position, so `git -C source/svc-d push` was held against whatever
stream the band showed. Seven inputs from four places decided the verdict: module state,
two atoms, a boolean and a sentinel string. Several of their combinations passed a command
that should have been held.

## Decision

- `publish.ts` scans the command line into `publishes` (every publish command in the line,
  in order, each `{head, dir, ref}`), `clear` or `opaque`.
  - `dir` is one of three things: the shell's directory; a literal path from `git -C` or a
    leading `cd <dir>`; or `Unreadable`, for `cd -`, `cd $X` or `-C "$(…)"`.
  - `ref` is one of three things:
    - `Head`, the HEAD of `dir`;
    - `Branch`, one named branch, normalized by the scan from a refspec (`+src:dst` gives
      `src`, and `refs/heads/x` gives `x`), from `gh pr create --head` or from
      `glab mr create --source-branch`;
    - `Unresolved`: several refspecs, `--all`, `--branches`, `--mirror`, `--tags` or a
      deletion.
  - A literal string fed to `sh -c`, `bash -c` or `eval` is scanned recursively. Only text
    the scan cannot read is `opaque`, such as `… | bash` or `sh -c "$X"`.
- `register.tsx` resolves the target branch. A named branch is used as named. `Head` is
  resolved in `dir`, against the shell's directory. `Unresolved`, or `Head` in an
  unreadable directory, gives `TargetBinding.Unresolved`. It reads each target's stream and
  `publish` from one `status --branch` call per distinct branch.
- The line holds when any of its publish commands holds, and the hold names the first one
  that does. It passes only when every command passes.
- The gate builds one `GateInputs` value. A pure, total `gateVerdict` returns `Pass` or
  `Hold`.
  - A target that has no stream, or cannot be resolved, falls back to the session's bound
    stream.
  - A failed read is `Hold {Unreadable}`, never a pass.
- The surface is read from `$.session.surfaces()` at the gate, not from a boolean cached at
  session start.

## Alternatives considered

- **Hold only against the bound stream.** It is simple. But a bound session that pushes
  another repo is checked against the wrong stream. And an unbound umbrella session would
  publish with no check.
- **Hold every opaque command (`… | bash`, `sh -c "$X"`).** That would hold far more than
  publishes. Opaque commands stay a documented limit. The scan reports them, so the
  decision is visible and testable. A literal `sh -c '…'` is not opaque: the scan reads it.

## Consequences

- A publish line costs one `status` run per distinct branch it publishes, plus one
  `git rev-parse` per command that publishes the HEAD of its directory.
- A refspec with several branches, `--all`, `--mirror` or a deletion cannot be resolved and
  falls back to the bound stream.
- The gate's decision is a pure function, so a table-driven test can cover it fully.
