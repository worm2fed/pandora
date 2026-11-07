---
type: prd
title: "PRD: shipgate 0.23.0 and shipgate-hud 0.10.0 — the user's publish approval, closed findings, a signal grader"
created: 2026-11-06
updated: 2026-11-06
tags:
  - prd
  - shipgate
  - shipgate-hud
status: clarified
issue: "#1, #6, review findings stuck at fixing (no issue yet)"
worklog: "./shipgate-0.23.0.worklog.md"
related:
  - ../adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
  - ../adr/0015-the-user-approves-a-publish-outside-the-model-tools.md
  - ../adr/0016-the-signal-grader-runs-outside-the-harness.md
  - ../../../shipgate-hud/docs/adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../../../shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md
---

# PRD: shipgate 0.23.0 and shipgate-hud 0.10.0

> A flow cannot record the user's publish approval through its own tools. A finding key is
> always a location, and a `ready` verdict closes every finding in a fix. A script grades
> the blast-radius signal against the ground truth of the eval fixtures.

## Problem

1. **A flow can authorize its own publish (#1).** `journal.py append --actor user` takes the
   actor from the flag alone, and `raised_by: user` is free text. So the model can append a
   publish `gate-decision` "by the user". That satisfies the `mr-opened` rule, and the HUD's
   publish gate reads the same rule.
2. **Review findings stay at `fixing`.** On a production project's journal (counts only),
   10 streams used `review-disposition`. 5 of them ended with keys still at `fixing`: 37 of
   about 200 keys. There are two causes:
   - The closure was never recorded. A fix round appended `fixing`, then the `ready`
     verdict carried an empty `dispositions` map, and no `review-disposition` closed the
     keys.
   - Key drift. `fixing` was recorded under `<path>:<line>`, and the closure under free
     labels (`F21`), or both sides used free labels for different findings. The fold never
     meets.
3. **The code-graph eval cannot show the graph's effect (#6).** On case 72 the graph reaches
   56 of 59 true files and the regex scanner 2. The answer graders tie, because a strong
   model writes its own resolver when the regex count looks wrong.
4. **A first reload after a release can fail.** `/reload-plugins` can load the HUD before
   the new shipgate, and the dependency check then fails. A second reload loads it. The HUD
   README does not say so.

## Goals & non-goals

**Goals**
- No normal tool path of the model records a publish approval that the gate counts as the
  user's. The HUD's dialog and the user's own `!` command still can.
- Both READMEs state the boundary honestly.
- A `ready` verdict never leaves a finding at `fixing`, and every disposition key is a
  location.
- The HUD never draws a legacy stale `fixing` as live.
- A script reports precision and recall of `blast.files` and `blast.tests` per arm.

**Non-goals**
- No defence against deliberate circumvention. The model has a shell and can write the
  SQLite file directly.
- No new harness grader type. The eval harness has none that runs a script.
- No eval run in this change. The lead runs evals after merge.
- No rewrite of journals: old rows stay as they are.

## Functional requirements

**shipgate 0.23.0 — the publish approval (#1)**
- **FR-001** — A new PreToolUse hook (matcher `Bash`) refuses a command that appends a
  `gate-decision` that carries the dialog marker, on any gate. It also refuses one at the
  publish gate (`gate` or its alias `kind`) that names the user: `--actor user`,
  `user@…`, a JSONL `actor` of that role, or `raised_by: user`. Decisions at other gates
  stay allowed with every actor.
- **FR-002** — The hook reads every spelling the CLI accepts: `--data` (also `--data=`),
  `--batch` with stdin from a heredoc, a here-string or a pipe from `echo`, `printf` or
  `cat`, `--type` and the JSONL `type`, a unique abbreviation of a long option, a JSONL
  `actor`, `journal.py` at any path, and a literal command line given to `sh -c`,
  `bash -c`, `zsh -c` or `eval`.
- **FR-003** — The hook fails closed when it cannot read an append's payload. A payload
  that comes from a variable, a command substitution, a redirected file it cannot read or
  another command's output is refused, with a hint to write it literally. An append whose
  `--type` names another event type is not affected.
- **FR-004** — The refusal tells the model to ask the user to approve in the HUD's publish
  dialog, or to run the append themselves with `!`.
- **FR-005** — The not-applicable path stays a no-op: a tool other than Bash, or a command
  with no `journal.py` or no `append`, prints nothing and exits 0 with no file read.
- **FR-006** — `gate-decision` takes an optional `source`, one of `dialog` or `shell`.
  `vocab --shape gate-decision` prints it.
- **FR-007** — A `gate-decision` authorizes a publish only with `gate: publish`,
  `raised_by: user`, `decision: publish`, a `source` marker and an actor of role `user`.
  `mr-opened`, `status --json` and `position --json` read this one rule.
- **FR-008** — An older unmarked user publish decision no longer authorizes. The gate asks
  again.

**shipgate 0.23.0 — closed findings**
- **FR-009** — A disposition key must be a location `<path>:<line|?>`: the text split at its
  last `:`, a non-empty path after `./` is dropped, a line of digits or `?`. This holds for
  `review-disposition.dispositions`, `review-disposition.labels` and
  `review-verdict.dispositions`. `append` refuses another key, with a hint to put the name
  in `labels`. `--force` does not waive it.
- **FR-010** — `append` refuses a `ready` verdict while the fold holds a `fixing` key that
  the verdict's own map does not close. The message lists the keys and shows the
  `review-disposition` row that closes them. `--force` overrides it only with
  `--force-reason`.
- **FR-011** — The `review` skill says the fix round closes every `fixing` key (`fixed`,
  `rejected` or `deferred`) before the verdict. Its "Keep the keys compact" paragraph takes
  the ledger line on closing about 20 findings with `review-disposition` rows. The line
  leaves the ledger.
- **FR-012** — Every skill and message that told the model to record the user's publish
  decision itself now sends it to the user (HUD dialog or `!`).

**shipgate-hud 0.10.0**
- **FR-013** — The publish dialog adds a third answer that approves publishing. It records
  one `gate-decision` per held stream with the marker `source: dialog`, `raised_by: user`
  and `--actor user`, then lets the line through. "Let it through once" stays and records
  nothing.
- **FR-014** — A folded `fixing` older than the newest verdict, when that verdict is
  `ready`, is stale. A card and the verdict-only round draw it dim as `fixing?`. No count
  treats it as open: not the band, not a board's open count.
- **FR-015** — The README's "After a shipgate release" says a first `/reload-plugins` can
  load the HUD before the new shipgate, and a second reload loads it. Both READMEs describe
  the publish boundary in one honest paragraph.
- **FR-016** — The dependency is shipgate `>=0.23.0`. The read floor stays 0.21.0.

**Evals (#6)**
- **FR-017** — `shipgate/evals/signal_grader.py` scores a `signals.py blast --json` (or
  `hotspots --blast --json`) result against a case's `expected.json`. It reports precision
  and recall for `blast.files` (truth: importers and tests) and `blast.tests` (truth:
  tests). It reads the result from a run's trace, or runs `signals.py` in the scaffolded
  fixture (graph or regex arm).
- **FR-018** — Cases 13 and 72 each have an `expected.json`, and `run-case.sh` runs the
  grader after a run of a case that has one, in both arms.
- **FR-019** — `shipgate/evals/README.md` documents the grader and its two numbers.

## Success criteria

- **SC-001** — The hook refuses each forged spelling of FR-001 and FR-002 and each opaque
  payload of FR-003, and allows a clarify decision by the user, a publish decision by the
  orchestrator and every other event (hook tests).
- **SC-002** — The hook prints nothing and exits 0 for a non-Bash tool and for a command
  without `journal.py` or `append` (hook tests).
- **SC-003** — `mr-opened` accepts a marked user publish decision and refuses an unmarked
  one, one with the marker but another actor, and one with the marker but
  `raised_by: orchestrator` (journal tests).
- **SC-004** — `append` refuses a free-label key in all three maps and a `ready` verdict
  over an open `fixing` key; `--force` without a reason is refused; the closing row is in
  the message (journal tests).
- **SC-005** — The HUD dialog's approve answer records a marked decision per held stream
  and passes the line (register test).
- **SC-006** — A stale `fixing` draws as `fixing?` on a card and in the verdict-only round,
  and the band and the open count leave it out (view tests).
- **SC-007** — Offline on the fixtures, the grader gives case 72 a graph-arm `blast.files`
  recall of about 0.95 and a regex-arm recall of about 0.03, and case 13 a high recall on
  both arms.
- **SC-008** — Every check is green: shipgate's unit tests, `claude plugin validate` for
  both plugins, `claude plugin test shipgate-hud`, `tsc`; the full `/security-review` of
  the hooks diff has no unresolved finding.

## Constraints & assumptions

- Public repo: nothing employer- or customer-specific (root `CLAUDE.md`).
- shipgate's scripts and hooks stay Python 3.9 compatible.
- `hooks/` is a security-sensitive area: the full `/security-review` runs on the hooks
  diff, and the no-op path is a correctness requirement.
- Payload shapes change additively, except the two refusals of FR-009 and FR-010 and the
  publish rule of FR-007, each named in the changelogs.

## Assumptions (executive)

- Marker name → `source`, one of `dialog` (the HUD) or `shell` (the user's `!` command).
  An honest value for each writer; both count. ADR 0015.
- A `!` command → never reaches PreToolUse, so the user can type the marker. The README
  shows the command.
- Old unmarked publish decisions → no longer authorize; the gate asks again (brief's
  recommendation).
- The rule also checks the actor role → yes; the HUD and `!` both pass `--actor user`.
- The hook's applicability → the words `journal.py` and `append` in the command; no
  journal-existence probe. A refused forgery in a project with no journal changes nothing,
  and a probe adds file reads to every Bash call.
- A hook failure → fails open (exit 0), except a crash on a command that names
  `journal.py`, `append` and `publish`, which is refused.
- Location grammar → the HUD's `parseLocation` exactly, so both sides agree on one
  grammar.
- The `ready` refusal's override → `--force` with `--force-reason`, as the payload cap's.
- The dialog → three answers; "Let it through once" keeps its meaning. HUD ADR 0010.
- Stale `fixing` → older than the newest verdict when that verdict is `ready`.
  `position` prints only the last verdict, and the new journal rule keeps new journals
  from writing one.
- The grader → a stdlib script outside the harness: the harness grades pass/fail with no
  script type. ADR 0016.
- `blast.files` truth → importers and tests (the README's "59 true files"); a `null`
  `blast.tests` counts as empty.

## Open questions

None.
