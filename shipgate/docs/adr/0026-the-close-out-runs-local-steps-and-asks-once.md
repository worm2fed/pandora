---
type: adr
title: "0026. The close-out runs local steps and asks once"
created: 2026-11-20
updated: 2026-11-22
tags:
  - adr
  - shipgate
  - journal
status: accepted
date: 2026-11-20
issue: "#31 (shipgate), batch 2 of #37"
related:
  - "0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "0025-close-out-and-sweep-are-computed-from-observed-evidence.md"
  - "../prd/brief-and-close-out.md"
  - "../prd/brief-and-close-out.worklog.md"
---

# 0026. The close-out runs local steps and asks once

> When the user says "merged", the `feature` skill runs the close-out plan. Once the merge is
> observed, the local steps run with no question and no force flag. The project's own
> steps, and a squash-merged branch's deletion, wait for one recorded question.

## Context

The user typed "merged" in 39 messages across 24 sessions, and then expected the close-out.
A lead did the steps by hand after each merge. A tag releases a plugin to installed copies,
so it stays behind the user's go; so do a push and an issue edit. Issue #22 (ADR 0023,
0.28.0) records the user's go for commit and publish, and it leaves a tag, a merge, an issue
edit and the word "merged" to this issue.

The user answered three questions on 2026-11-20 (PRD Q2, Q3, Q4). Git facts, probed on git
2.56: `git worktree remove` without `--force` refuses a worktree with untracked files (exit
128); run from inside the worktree it succeeds and leaves the session with no working
directory; `git branch -d` refuses a branch a worktree has checked out (exit 1) and a
squash-merged branch (exit 1); `git update-ref -d <ref> <oid>` deletes the ref only when it
points at `<oid>` (exit 1 otherwise).

## Decision

**Trigger (user, Q2).** No hook reads "merged". After `mr-opened`, the bound block of the
brief and `handoff` print one line:

```
  close-out    : after the merge, run journal.py closeout --stream=<s>
```

The `feature` skill routes the user's "merged" and a watcher's `merged` event to that
command.

**Steps.** The plan prints them in this order, each marked `run` or `ask`:

1. `run` — residual capture when the ledger holds entries; the full Capture when the stream
   has no `capture-done`.
2. `run` — `flow-completed {reason, evidence, url}`.
3. `run` — update the integration branch: `merge --ff-only` where it is checked out and
   `git status --porcelain` prints nothing; `fetch origin <b>:<b>` where it is not checked
   out.
4. `ask` — each bullet of the config's optional **Close-out** section, `- <Label>:
   <action>`. Every one is `ask`; no mark and no word list decide it (amendment below).
5. `ask` — only after a squash merge: the guarded deletion
   `git update-ref -d refs/heads/<b> <oid>`, where `<oid>` is the head commit the forge
   merged.
6. `run` — report to the stream's `report_to`, else the user.
7. `run` — last, in one Bash call:
   `git -C <main checkout> worktree remove <worktree> && git -C <main checkout> branch -d <b>`.
   With no worktree, the plan switches the checkout to the integration branch first, on a
   clean tree only.

**Authority (user, Q3 and Q4).** Every `run` step runs with no question. No step uses
`--force`, `-f` or `-D`; a step git refuses stops, and the flow quotes git and asks. Before
step 1, the flow asks one `AskUserQuestion` with header `Close-out` that lists the `ask`
steps, multi-select. It records the answer with `--actor user` as
`gate-decision {gate: close-out, mode: ask, raised_by: user}` and runs only the chosen
steps. No hook guards these steps.

**Executive parts**, which the user can veto: step 5 and its guard; the order of step 7,
which puts the branch deletion after the worktree removal because git refuses the other
order; the question's labels, which avoid every word that #22's reply recorder reads as a
go (`commit`, `publish`, `push`, `all`, `yes`, `y`, `ok`, `go`, `approve`).

## Alternatives considered

- **A hook reads "merged"** (#22's `UserPromptSubmit` recorder gains the word). It needs no
  skill routing. The user rejected it: it changes the hook contract, and #22 keeps hooks
  from reading free language.
- **Ask before the local steps too.** Safer by one question. The user rejected it: the
  steps are local, git refuses the destructive cases, and the user already said "merged".
- **A third go gate in #22's machinery** for a tag and an issue edit. The answer would be
  witnessed by a hook. The user rejected it: #22 left a tag ungated on purpose, and #42
  retargets the gates with a month of data.
- **After a squash merge, keep the branch and report it.** No question at all. Rejected:
  every close-out on a squashing forge would leave a branch behind, and the issue counts
  branch deletion as part of the close-out. `git branch -D` is excluded by Q3.
- **A new `close-out` skill.** Its description would trigger on "merged". Rejected: Q2 names
  `feature`, and every skill description costs context in every session (#32).

## Consequences

- One word and at most one question close a merged stream.
- Nothing but skill text makes the flow ask the one question; no hook checks it (Q4).
- After `flow-completed`, #22's command gate treats the branch as having no live stream, so
  a tag push from it is not guarded by any go. That matches Q4. The implementer checks it
  after the rebase.
- The session that runs step 7 from inside the worktree loses its working directory, so
  it reports in step 6, before the removal.
- A watcher's `merged` event lives on a `watch/` stream, not the work stream; only skill
  text connects them.

## Amendment (2026-11-22, #31): the squash step's command runs last

Found in implementation and probed on git 2.56.1. When `update-ref -d` deletes the ref of a
branch that a worktree has checked out, `git worktree remove` then refuses that worktree
(exit 128): its index shows every file as staged. Only `--force` would clear it. So step 5
stays one `ask` item in the one question, but its command runs in step 7's single Bash call,
after the worktree removal, in place of `branch -d`:
`git -C <main checkout> worktree remove <worktree> && git -C <main checkout> update-ref -d
refs/heads/<b> <oid>`. The plan prints no command on step 5 and prints this form on step 7
as `when the user chose step 5`. When the user does not choose it, step 7 removes the
worktree only, and the branch stays. The user accepted the change through the lead; the
ruling stands: the branch goes only on the user's yes, by the exact commit, with no force
flag.

## Amendment (2026-11-22, #31): every project step is asked

The user's ruling in review round 2, relayed by the lead: "Every config step is asked". As
built, a bullet could carry a `(run)` mark, and a word list forced `ask` on a step that
named a tag, a push or a publish. Review round 2 showed both gaps. F25: a `(run)` step
whose action held `git branch -D` printed as `[run]`, against FR-014. F26: the word list is
free-text matching, so `"gh" pr merge`, `twine upload` or `curl -d` passed as `run`, and
after `flow-completed` no command gate holds the branch. A project's steps are arbitrary
commands, so the mark and the word list are gone: each bullet of the **Close-out** section
is an `ask` step in the one question, and the plan shows its label as written. The
question shows each step's command beside its label, so the user approves a command, not a
name (F53, review round 4; the user's round-4 ruling). The built-in local steps (1 to 3, 6
and 7) still run with no question. A project step runs only after the user chose it in that
question, and the flow runs it as the config wrote it.

## Amendment (2026-11-23, #31): the worktree removal is asked when it would delete files

The user's ruling after the built-in security review on the commit, relayed by the lead:
"Hold, make it an asked step". F60: the close-out's last step ran `git worktree remove`
with no question, and git removes a worktree that holds only ignored files. A probe with an
ignored `.env` in the worktree gave exit 0, and the file was gone. Q3 had allowed the
removal with no question because git refuses a dirty worktree; an ignored file does not
make a worktree dirty for git.

So the close-out's observe script also runs `git status --porcelain --ignored
--untracked-files=normal` in the linked worktree whose branch is the stream, and keeps the
output only when git succeeds. `--untracked-files=normal` overrides
`status.showUntrackedFiles=no`, which hides ignored files too (F61, review round 6). When
the worktree holds any ignored (`!!`) or untracked (`??`) path, or its files were not
observed, the removal is an `ask` step in the one question. It sits after the project's
steps and before the squash deletion, so the later steps' numbers in this ADR move by one.
Its line shows the count and the first five paths (git prints a wholly ignored directory as
one path), and says that they are deleted with the worktree; the option shows the whole
last command, the branch deletion included. The last step then runs only when the user
chose that step, and the report names the worktree and the branch as kept when the user did
not. With no such path, the removal runs with no question, as Q3 ruled. No list of harmless
ignored names decides it. A change to a tracked file is not counted: git refuses that
removal itself (SC-007). A path created after the observation is not seen (F67, deferred).
