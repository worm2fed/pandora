---
type: adr
title: "0008. Artifact authorship is resolved when the journal is read"
created: 2026-10-20
updated: 2026-10-20
tags:
  - adr
  - shipgate
status: accepted
date: 2026-10-20
issue: none / ad-hoc
related:
  - "0003-session-attribution-via-current-session.md"
  - "0005-session-label-from-the-shell-environment.md"
  - "../../../shipgate-hud/docs/prd/session-stream-attribution.worklog.md"
---

# 0008. Artifact authorship is resolved when the journal is read

> Hooks record claims about who wrote an artifact. `journal.py` decides the author when it
> reads them: the best evidence wins, and a tie names no author.

## Context

Every session arms FileChanged on the same artifact homes. A FileChanged payload names the
session whose watcher saw the change, not the one that wrote the file. `file_changed.py`
recorded that observer as `session`. The 5 s dedupe compared path and mtime only, so
whichever hook landed first owned the row, and the writer's own `source: tool` record was
dropped. The Stop gate (rules A and B) and `stats` read those rows by session. With
parallel sessions on one journal, a bystander could be blocked at Stop for another session's
PRD, and the writer went free.

The journal is append-only, so a wrong row cannot be corrected in place. Bash writes
(heredocs, `sed`) reach no file-tool hook. Claude Code's PostToolUse for Bash carries
`duration_ms`, and in some modes `tool_response.bashEditDiff.changedFiles`, a best-effort
beta list of the files the call changed.

## Decision

Hooks record three kinds of claim for one write, keyed by path and mtime:
- `tool`, from PostToolUse on Write, Edit and NotebookEdit, with `session`;
- `bash`, from PostToolUse on Bash, with `session` and `evidence: diff` (the file is in
  `bashEditDiff.changedFiles`) or `evidence: window` (the mtime falls inside the call's
  `duration_ms` and the command writes to the file: a redirect target, `tee`, `sed -i`,
  `perl -i`, or the destination of `mv`, `cp` or `install`);
- `disk`, from FileChanged, with `observed_by`, never `session`.

At append, a `disk` row is dropped when any row for the same path and mtime landed in the last
5 s. An authored row is dropped only when the same session already claimed that write.

At read, one fold resolves each write's author. `tool` beats `bash/diff`, which beats
`bash/window`. Two different sessions with the same best evidence give no author. The Stop
gate and `stats` read authors only from this fold. A legacy `disk` row that still carries
`session` counts as observed.

## Alternatives considered

- **Writer-only attribution, no Bash claim (3A alone).** It is simpler, with no new hook.
  But an artifact written by a Bash heredoc names no session, so the Stop gate stops seeing
  it, even in a one-session project where today's attribution is right.
- **Keep `session` on disk rows when only one session is open.** Crashed sessions never
  record `session-ended`, so "one session open" cannot be known reliably.
- **PreToolUse plus PostToolUse on Bash, with a start marker.** `duration_ms` gives the
  same window without a second hook and without state files.
- **Decide authorship at append.** The append-only journal cannot revise an early wrong
  row when better evidence arrives later. A read-time fold can.

## Consequences

- A session is never blocked for a write it only observed.
- Every Bash call in every project now starts the PostToolUse hook. The non-journaled path
  stays the `likely_journaled` stat walk. In a journaled project, the hook spawns
  `journal.py` only when it has a claim.
- A background Bash command claims nothing, so its writes stay observed only.
- Two concurrent Bash calls that both name the same file give no author. The fold prefers
  silence to a wrong blame.
- `bashEditDiff` is best effort and may change shape. It is evidence, not policy. A wrong
  entry can at worst tie with the true writer.
