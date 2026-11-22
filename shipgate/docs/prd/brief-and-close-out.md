---
type: prd
title: "PRD: shipgate 0.30.0 — a smaller status brief and automatic stream close-out"
created: 2026-11-20
updated: 2026-11-20
tags:
  - prd
  - shipgate
  - journal
status: clarified
issue: "#31 (shipgate), batch 2 of #37"
worklog: "./brief-and-close-out.worklog.md"
related:
  - ../research/2026-11-15-agent-harness-audit.md
  - ../adr/0009-the-journal-computes-the-hud-position.md
  - ../adr/0021-the-handoff-brief-is-computed-not-written.md
---

# PRD: shipgate 0.30.0 — a smaller status brief and automatic stream close-out

> The SessionStart brief shows the work this session drives in full and counts the rest.
> One command computes the close-out of a merged stream, and the flow runs it when the user
> says "merged". A sweep closes the streams nobody closed. The brief marks a stream that
> another session wrote a short time ago.

## Problem

The SessionStart hook prints the status brief at every session start, `/clear`, `/compact`
and resume. The brief is model input, so every later turn reads it again. It lists every
open stream, and streams stay open after their PR merges.

The research note `shipgate/docs/research/2026-11-15-agent-harness-audit.md` (finding 12)
counted:

- The brief was injected 173 times at a median of 7,266 characters (about 1.8k tokens).
- On one journal, 22 of 31 open streams were idle for 38 to 87 days. `flow-abandoned` was
  never used there.
- The user typed "merged" in 39 messages across 24 sessions. Asks to close a stream, clean
  a worktree or retire a teammate add 20 messages in 16 sessions.
- 32 of 74 streams were written by more than one session, and `status` does not show it.

A copy of a production project's journal, measured on 2026-11-20 with the 0.27.0 code:

| Measure | Value |
| --- | --- |
| Brief, no stream bound (integration branch) | 95 lines, 7,400 characters; 7,556 with the hook's header |
| Brief, a worktree that binds the newest live stream | 96 lines, 7,705 characters; 7,861 with the header |
| Open streams in the brief | 26: 6 live (full blocks), 20 dormant, idle 7 or more days (one line each) |
| Finished streams hidden | 67 |
| Characters in the 6 live full blocks | 5,360 (72% of the brief) |
| Characters in the 20 dormant lines | 1,992 |
| Idle ages | 8 to 91 days; 16 streams idle over 30 days |
| Work streams written by more than one session | 40 of 84 |
| Open streams written by two sessions in the last 2 hours | 1 |

So the dormant lines are not the main cost. The full blocks of live streams that this session
does not drive are.

After a merge, nothing in the plugin acts. `feature` and `knowledge-base` close a stream
with `flow-completed` only "once nothing is owed on it", and an open PR is owed. No skill
text handles the word "merged". In a lead-and-teammate setup the lead did these steps by
hand after each merge: tag the version-bump commit, fast-forward the main checkout, tick
the child in the tracking issue, tell the teammate to append `flow-completed`, retire the
teammate, remove the worktree, delete the local branch.

## Goals & non-goals

**Goals**
- The brief costs a fixed small amount, whatever the number of open or finished streams.
- The work this session drives stays in the brief in full, so a fresh session (after
  `/clear` or `/compact`) still routes from it.
- After "merged", the flow closes the stream in one step: it checks the merge, runs the
  residual capture, records `flow-completed`, and cleans the local branch and worktree.
- The steps that publish or edit something outside the machine wait for the user's go.
- A sweep proposes a close for each dormant stream, from evidence, and the user confirms once.
- The brief shows when another session wrote a stream a short time ago.

**Non-goals**
- Retiring a teammate session. The plugin has no teammate concept; the close-out reports to
  the stream's `report_to`, and the lead acts.
- A gate on the merge itself. The user or the forge merges.
- A watcher. A project that declares one keeps it; its `merged` event is one more trigger.
- A change to `handoff`'s content beyond the close-out pointer (ADR 0021 stands).
- A change to shipgate-hud. `status --json` stays the HUD's input, with additive keys only.
- Any change to the approval path of #22 other than what a question below decides.

## Users & stories

- As the user, I type "merged", answer one question about the tag and the issue, and the
  stream is closed, the worktree and branch are gone, and the release is tagged.
- As a lead, I get one report from the teammate that the stream is closed, and I retire it.
- As a session that starts on the integration branch, I see in one line how many streams
  are live, dormant and finished, and the command that lists them.
- As a session that resumes a stream after `/clear`, I see that stream in full, as today.
- As the user, I run one sweep, read the proposals, and close twenty stale streams with one
  answer.
- As a session about to drive a stream, I see that another session wrote it 12 minutes ago.

## Functional requirements

**Brief**

- **FR-001** — The brief prints a stream in full only when this session drives it (the
  session match) or the checkout names it (the branch or nested-branch match). The full
  block keeps today's fields.
- **FR-002** — The brief prints no other stream, not even as one line. (User, Q1.)
- **FR-003** — The brief ends with one count line for the streams it does not print: live,
  dormant and finished counts, with the command that lists them (`journal.py streams --open`)
  and the command that closes the dormant ones (`journal.py sweep`). A count of zero is left
  out; with nothing to count, the line is left out.
- **FR-004** — `status --all` prints every stream in full, finished ones included, as today.
  `status --feature <name>` prints that stream in full, as today.
- **FR-005** — `status --json` keeps every open stream in `features` with today's keys. New
  keys are additive.
- **FR-006** — `journal.py streams --open` lists each open stream: its name, lifecycle
  (live or dormant), phase, last event, idle days, the ownership mark of FR-007, and the PR URL
  when `mr-opened` recorded one. `--dormant` lists only the dormant ones. Plain `streams` keeps
  today's output.

**Ownership hint**

- **FR-007** — A stream that another session wrote within the last 30 minutes carries a
  mark on its full block in the brief and on its line in `streams --open`: "another session
  wrote this Nm ago". Hook-written events do not count. Events of this session do not
  count. The count line of FR-003 says how many of the streams it counts carry the mark.
- **FR-008** — `status --json` gives each stream its last writing session and the time of
  that write.

**Close-out**

- **FR-009** — `journal.py closeout --stream <s>` prints the close-out plan for a stream,
  computed from the journal, the config and the artifacts. It writes nothing. It acts only
  on the branch named exactly as the stream, and on the recorded PR or one with that exact
  head; any other stream exits 4 and names the sweep. (The user's ruling in review round
  3, ADR 0025 amendment.)
- **FR-010** — The plan starts with the merge check: the command that observes the merge,
  and the evidence that counts. It never takes the user's word alone as the evidence.
- **FR-011** — The plan lists, in order: residual capture (only when the ledger holds
  entries), `flow-completed` with the merge evidence, the update of the local integration
  branch, the project's own post-merge steps, the report to the stream's `report_to`, and
  last the removal of the worktree followed by the deletion of the local branch. git
  refuses to delete a branch that a worktree has checked out (probed: exit 1), so the
  branch goes after its worktree.
- **FR-012** — Each step in the plan is marked as one the flow runs without a question or
  one that waits for the user's go. Once the merge is observed, every local step runs
  without a question: `flow-completed`, `git branch -d`, the fast-forward of the
  integration branch where it is checked out and clean, and the worktree removal last.
  (User, Q3.) The worktree removal waits for the one question when the worktree holds an
  ignored or untracked file, or its files were not observed: git deletes ignored files
  with the worktree. The question lists the files. (The user's ruling on F60, ADR 0026
  amendment.)
- **FR-013** — A tag, a push and an issue edit always wait for the user's go. The flow asks
  one question that lists each external step of the plan. It records the answer as the
  user's `gate-decision` at gate `close-out`, and runs only the steps the user chose. No
  hook guards these steps. (User, Q4.)
- **FR-014** — No step uses a force flag. A step that git refuses (a dirty worktree, an
  unmerged branch, a non-fast-forward) stops that step, and the plan says what to do.
- **FR-015** — A project can declare its own post-merge steps (for example: tag the
  version-bump commit) in its config. Each one waits for the user's go. (Changed by the
  user's ruling in review round 2, ADR 0026 amendment: no step says it needs no go.)
- **FR-016** — The user's "merged", or a watcher's `merged` event for the stream's PR,
  starts the close-out. No hook reads the word. The `feature` skill routes both to the
  close-out. (User, Q2.)
- **FR-017** — After `mr-opened`, the brief's full block and `handoff` print one line that
  names the close-out command.

**Sweep**

- **FR-018** — `journal.py sweep` lists each dormant stream (idle 7 or more days) and proposes
  one of: `flow-completed` (its PR merged), `flow-abandoned` (its PR closed unmerged),
  `unknown` (no branch and no PR of the stream's exact name, and no recorded PR: the user
  decides, and the line shows what the sweep looked for), or keep (anything else). It
  writes nothing. It guesses no branch and no PR by a slug or a suffix. (The user's ruling
  in review round 4, ADR 0025 second amendment.)
- **FR-019** — The sweep takes the PR states from one forge query that the flow runs. With
  no forge CLI, it falls back to git evidence and says so per stream.
- **FR-020** — After one confirmation, `journal.py sweep --apply` appends the proposed
  terminal events, each with its reason and evidence. It does not touch git.

**Payloads**

- **FR-021** — `flow-completed` and `flow-abandoned` accept `reason`, `evidence` and `url`.
  None is required, so an old append still works.

## Success criteria

- **SC-001** — On the production journal copy, the brief with the hook's header is at most
  500 characters on the integration branch (today 7,556) and at most 1,700 characters in a
  worktree that binds the newest live stream (today 7,861). Measured with
  `render_status(build_status(...))` on the copy, before and after. A prototype of the
  chosen shape measured 298 and 1,396.
- **SC-002** — With 100 open streams in a fixture journal, the brief on the integration
  branch is no longer than with 10 (plus the count line's digits).
- **SC-003** — For a bound stream, the full block is byte-identical to 0.27.0's, except the
  new lines of FR-007 and FR-017. The `handoff` text of a stream with no `mr-opened` is
  byte-identical to 0.27.0's.
- **SC-004** — `status --json` on the production copy lists the same streams in `features`
  as 0.27.0, and the HUD contract test passes.
- **SC-005** — After "merged" on a stream whose PR merged, the flow ends with the stream
  terminal, its local branch and worktree gone, and at most one question put to the user.
  After a squash merge, `git branch -d` refuses (probed: exit 1), so the branch goes only
  when the user picks its guarded deletion in that same question. This holds for a stream
  whose branch and PR head carry the stream's exact name. Any other stream exits 4 and
  stays open; once it is dormant, the sweep lists it for the user (amended after the user's
  round-3 ruling, ADR 0025 amendments).
- **SC-006** — On a stream whose PR did not merge, the close-out appends nothing and
  removes nothing. Tested.
- **SC-007** — A dirty worktree and a branch git calls unmerged survive the close-out.
  Tested with a scratch repo.
- **SC-008** — On the production copy, `sweep` proposes a disposition for 20 of 20 dormant
  streams, from one forge query.
- **SC-009** — The ownership mark appears when another session wrote the stream within 30
  minutes, and not otherwise. Tested.
- **SC-010** — The SessionStart hook's no-op path (not a journaled project) is unchanged.
  Tested.

## Constraints & assumptions

- Scripts and hooks stay Python 3.9 compatible and stdlib only.
- `journal.py` runs no subprocess today. The design keeps that unless a decision says
  otherwise.
- Issue #22 (0.28.0) merges first. This work rebases onto it and ships as 0.30.0, after
  #40 took 0.29.0. #22 touches `journal.py` next to `build_status`, moves `current_branch`
  from `session_start.py` to `hooks/_common.py`, and rewrites the publish text in `feature`
  and `review`.
- #22 adds a `UserPromptSubmit` hook (`hooks/reply.py`) that reads short replies for the
  words of the commit and publish gates. Its PRD leaves "merged" and the tag to this issue,
  and says no hook reads free language.
- Under #22, a publish go lasts until the stream's next `task-done`. A tag push from the
  work branch after the merge could pass the command gate on the PR's old go. To be checked
  after the rebase. (Risky.)
- git facts, probed on git 2.56 in a scratch repo: `git worktree remove` without `--force`
  refuses a worktree with untracked files (exit 128); it succeeds when run from inside that
  worktree (exit 0), which leaves the session without a working directory; `git branch -d`
  refuses a squash-merged branch (exit 1).
- The stream records no worktree path and no tracking issue as fields. The worktree comes
  from `git worktree list`; the tracking issue comes from the issue text.

## Assumptions (executive)

- One release or two? → One release, 0.30.0 (designed as 0.29.0), one PR — the four parts share `build_status`
  and the brief text, so splitting them doubles the rebase onto #22.
- The idle threshold? → Keep `DORMANT_DAYS = 7` — it also drives the nested-branch rule and
  the HUD's `lifecycle`, so a new value would change both.
- The ownership window? → 30 minutes, a constant — the data shows one concurrent stream in
  two hours, so the mark is rare and a config knob is not worth its surface.
- Where the ownership data comes from? → The last non-hook event's session per stream
  (`event_session`) — it is already computed for `session_stream` and `stats`.
- Who queries the forge? → The flow runs one forge CLI query and passes its JSON to
  `journal.py` — the journal stays free of subprocess and network calls.
- What counts as merge evidence? → The forge's merged state first; git ancestry of the
  branch tip in the remote integration branch as the fallback — a squash merge is visible
  only to the forge.
- Where project post-merge steps live? → A new optional config section, `Close-out` — the
  tag rule is project-specific, and today it lives only in this repo's CLAUDE.md.
- Who retires a teammate? → The lead — the plan's last report goes to `report_to`
  (`flow-started` already records it).
- When does residual capture run? → Only when the ledger holds entries; a stream with no
  `capture-done` runs the full Capture first.
- Where does the worktree removal run? → Last, after the report — run from inside the
  worktree it ends the session's working directory.

## Decisions (user)

The user answered four questions through the lead on 2026-11-20. Each is a `gate-decision`
with `raised_by: user` on the stream.

- Q1 What does the brief print for an open stream this session does not drive? → Nothing
  but the count line. The recommendation was one line per live stream, at most five; the
  user chose the issue's form.
- Q2 Does a hook read "merged"? → No. The skill routes it, and the brief and `handoff`
  print the close-out command after `mr-opened`.
- Q3 Which local steps run without a question? → All of them, never with a force flag. A
  step git refuses stops and asks.
- Q4 How is the go for a tag, a push and an issue edit asked and recorded? → One question,
  recorded as the user's decision at gate `close-out`. No new hook guard. The stale
  publish-go risk is checked after #22 merges.

## Open questions

None.
