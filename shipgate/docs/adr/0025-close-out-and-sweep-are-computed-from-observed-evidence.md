---
type: adr
title: "0025. Close-out and sweep are computed from observed evidence"
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
  - "0021-the-handoff-brief-is-computed-not-written.md"
  - "0026-the-close-out-runs-local-steps-and-asks-once.md"
  - "../prd/brief-and-close-out.md"
  - "../prd/brief-and-close-out.worklog.md"
---

# 0025. Close-out and sweep are computed from observed evidence

> `journal.py closeout` and `journal.py sweep` compute their plan from the journal, the
> config and evidence files that the flow writes with the forge CLI and git. The journal
> parses the evidence and runs no subprocess. The user's word is not evidence.

## Context

A close-out must know whether the PR merged, which branch and worktree the stream used,
where the integration branch is checked out, and whether the ledger holds entries. A sweep
must know the PR state of every dormant stream. Only the forge knows a squash merge; git
ancestry does not show it (probed: `git branch -d` refuses a squash-merged branch, exit 1).

`journal.py` runs no subprocess today. The only git runner in the scripts is
`signals.py`'s read-only `run_git`. ADR 0021 set the pattern for a computed brief: the
journal computes, the flow acts, and the text is for a model.

## Decision

Two read commands, both text for a model:

- `journal.py closeout --stream <s> [--observed <dir>]`
- `journal.py sweep [--observed <dir>] [--apply]`

Without `--observed`, each prints one observe script and the rerun line. The script makes a
fresh directory and writes the forge state into it (`gh pr view` or `gh pr list`, `glab mr
view` or `glab mr list`), then `git fetch --prune`, the integration branch git names
(`origin/HEAD`, else `main`), the local refs, the refs merged into the remote integration
branch, its first-parent line, and `git worktree list --porcelain`. The forge CLI comes from
the host of the URL that `mr-opened` recorded, else the config's **Forge & tracker**
section, else none; with none, the script writes git evidence only. Every value the script
or the plan prints is shell-quoted.

With `--observed`, pure functions parse the files and decide. Forge evidence wins. When
the forge answered and holds no PR/MR for the stream, git may say gone or unknown, never
merged (the user's ruling on F24 of review round 2). With no forge evidence, git ancestry
is the fallback: a branch tip in the merged refs counts as merged only when it is off the
integration branch's first-parent line, where a merge commit puts it. A branch cut from
the integration branch with no commit of its own sits on that line, and so does the
integration branch tip; they never count (fix round 1, F1). The forge saying merged into
the observed integration branch while the tip is not in the merged refs marks a squash
merge. A missing or unreadable file degrades to the next source, and the plan says which
source it used.

`closeout` writes nothing. `sweep` writes nothing; `sweep --apply` recomputes from the same
directory and appends one terminal event per proposal through `append_event` with
`expect=<version>`, so a stream that moved since the proposal is skipped and named. Each
terminal event carries `reason`, `evidence` and `url`. The user's one confirmation of a
sweep is the question the skill asks; the sweep has no stream of its own to record it on.
This was an executive decision; the user can veto it.

## Alternatives considered

- **`journal.py` runs gh, glab and git itself.** One call fewer for the flow. Rejected: it
  would be the first subprocess and the first network call in the journal, with a `PATH`
  lookup, timeouts and a CLI named in free-text config. That is a security-sensitive area
  in this repo, and it moves the forge's failures into the journal's exit codes.
- **One `--evidence -` input on stdin.** Simpler for a single forge answer. Rejected: a
  close-out needs four inputs (forge, refs, merged refs, worktrees), and four flags or four
  pipes cost more than one directory.
- **Skill text only.** No new command. Rejected: the step order, the evidence rules and the
  refusal rule would live in prose that each session derives again. That is the failure
  ADR 0021 removed for the handoff brief.
- **A `--json` form.** Rejected for `closeout` and `sweep`, as in ADR 0021: the only reader
  is a model, and the tests call the build functions. `streams --open` keeps `--json`,
  because plain `streams` has it.

## Consequences

- A close-out costs two extra Bash calls: the observe script and the rerun.
- The parsers depend on the field names of `gh` and `glab` JSON. Synthetic fixtures pin
  them; a format drift falls back to git evidence, and the plan says so.
- Git evidence alone cannot see a squash merge, so a sweep without a forge CLI proposes
  `keep` for those streams.
- With a forge CLI, a stream that merged with no PR/MR never reads as merged: the project
  closes it by hand. With no forge CLI, a branch cut from another branch's tip with no
  commit of its own still reads as merged once that branch merges with a merge commit;
  git cannot tell the two branches apart.
- `journal.py` stays free of subprocess and network calls.

## Amendment (2026-11-22, #31): exact names only, no guessing

The user's ruling in review round 3, relayed by the lead: "Exact names only, no guessing".
Fix round 2 had taught the evidence to guess a stream's branch: the stream's name without
`feature/`, and for an old `feature/<slug>` stream any branch or PR head that ends in
`/<slug>`. Review round 3 showed what that costs. F35: with no forge evidence, an old
`feature/docs` stream whose own branch was gone resolved to another stream's branch
`chore/docs`, git read it as merged, and the plan removed that clean worktree and deleted
the branch. F34: the close-out asked the forge about `--head=<stream>` only, so a stream
whose branch has another name read "never merged" with a detail that named a head the
forge was never asked about.

So the close-out acts only on the branch named exactly as the stream, and on the recorded
PR/MR or one whose head is the stream exactly. A recorded PR/MR with another head, or no
branch of the stream's name, exits 4; the detail says so and names `journal.py sweep`. The
close-out plans no worktree removal and no branch deletion then. A stream named as the
integration branch is never closed. Only the sweep guesses, because it writes nothing
but journal events after the user's one confirmation: it may read a recorded PR/MR with
another head, and for an old `feature/<slug>` stream it may take the one PR head or branch
that is `<slug>` or ends in `/<slug>` (none when two do). The proposal says `guess:`, and
a guessed branch never reads as merged. The next amendment takes these guesses out of the
sweep. Two fixes of the same round: a forge list whose entries all lost the expected keys
reads as missing evidence, not as "no PR/MR" (F39), and a recorded URL matches the PR/MR
when both agree up to its number (F40).

## Amendment (2026-11-22, #31): no guessing in the sweep

The user's ruling in review round 4, relayed by the lead: "One more round, no guessing in
the sweep". Review round 4 showed what the sweep's slug guess costs. F44: two PR heads
ended in `/<slug>`, so the sweep took neither. With no branch left it read `gone` and "no
PR/MR", and it proposed `flow-abandoned` for a stream whose PR may have merged (probed).
F45: the sweep took a slug PR head even when the stream's own branch existed, so another
stream's merged PR could propose `flow-completed`.

So the sweep guesses nothing either. It judges a stream by the branch of its exact name,
by a PR/MR whose head is that name, and by the recorded PR/MR. The recorded PR/MR is the
stream's own evidence, not a guess, so the sweep reads it whatever its head is called (F46
asked for a `guess:` label there; with no guess, no label). With none of the three, the
sweep proposes `unknown`: the user decides, the line shows what the sweep looked for (the
stream's name, and the recorded URL when there is one), and `--apply` appends nothing for
it. The sweep proposes `flow-abandoned` only for a PR/MR that closed unmerged, and never
on a guess. The close-out keeps its rules from the first amendment, and its detail now
says that the sweep lists the stream once it is dormant. Two fixes of the same round:
glab's `locked` state, an MR in the middle of its merge, reads as open (F50), and a URL
that `urlsplit` refuses compares as itself instead of stopping the command (F52).
