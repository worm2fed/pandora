---
type: adr
title: "0024. The status brief prints the bound streams and a count"
created: 2026-11-20
updated: 2026-11-20
tags:
  - adr
  - shipgate
  - journal
status: accepted
date: 2026-11-20
issue: "#31 (shipgate), batch 2 of #37"
related:
  - "0009-the-journal-computes-the-hud-position.md"
  - "0021-the-handoff-brief-is-computed-not-written.md"
  - "../prd/brief-and-close-out.md"
  - "../prd/brief-and-close-out.worklog.md"
---

# 0024. The status brief prints the bound streams and a count

> Plain `journal.py status` prints in full only the streams this session is bound to. Every
> other stream goes into one count line that names the commands to list and close them.
> `--all`, `--feature` and `--json` keep what they print today.

## Context

The SessionStart hook prints `status` at every start, `/clear`, `/compact` and resume, and
every later turn reads it again. On a copy of a production journal the brief was 95 lines
and 7,400 characters (7,556 with the hook's header). The six live streams that the session
did not drive carried 5,360 characters of it, 72%. The 20 dormant one-liners carried 1,992.

A stream is **bound** when this session drives it (`session_match`, ADR 0021's
`session_stream`) or the checkout names it (`branch_match`, including the nested-branch rule
of `nested_branch_match`). The bound stream is what a fresh session resumes, so it stays in
full.

The user chose the form on 2026-11-20 (PRD question Q1).

## Decision

Plain `status` becomes the brief. It prints each bound stream with `_render_feature`, as
today, plus two optional lines (the ownership mark and the close-out pointer, PRD FR-007 and
FR-017). Then it prints one count line, and nothing else about other streams:

```
not shown: 4 live (1 written by another session in the last 30 min), 20 dormant, 67 finished — list: journal.py streams --open · close dormant: journal.py sweep
```

A zero count is left out, and with nothing to count the line is left out. `status --all`
and `status --feature <s>` print every selected stream in full, as today. `status --json`
keeps every open stream in `features` with today's keys and gains additive keys only
(`last_writer`, `pull_request`, `other_session`). The hook file does not change: it already
prints whatever plain `status` prints. `stats` measures the brief with the same render.

## Alternatives considered

- **One line per live stream, at most five, then the count.** This was the recommendation.
  It measured 822 characters on the integration branch, against 298 for the chosen form,
  and it lets a session on the integration branch see parallel work without a command. The
  user chose the smaller form; `streams --open` lists the same lines on demand.
- **Every live stream in full, the dormant ones counted.** It cuts only 25% (5,644
  characters), because the live blocks are the cost.
- **A `--brief` flag that the hook passes.** Plain `status` would keep today's output. It
  needs a hook edit, and a hook edit is a security-sensitive change in this repo, for no
  gain: no other caller reads the plain text as a contract.
- **A higher `DORMANT_DAYS`.** The threshold also drives the nested-branch rule and the
  HUD's `lifecycle`, and the dormant lines were not the cost.

## Consequences

- The brief on the production copy drops from 7,556 to about 300 characters on the
  integration branch, and from 7,861 to about 1,400 in a bound worktree (prototype
  measures). The size no longer grows with the number of streams.
- A session on the integration branch no longer sees the names of live streams. The
  `feature` skill must run `journal.py streams --open` before it opens a new stream or says
  that nothing is in flight. This is the main failure mode of the decision.
- If Claude Code gives a session a new id on `/clear`, a stream with no branch (an epic's
  planning stream) is no longer bound after `/clear`. The skill's rule above covers it;
  the implementer probes the id behaviour.
- About six tests that pin the unbound render move to `--all`. The shipgate-hud golden file
  is regenerated for the additive keys; the HUD code does not change.
