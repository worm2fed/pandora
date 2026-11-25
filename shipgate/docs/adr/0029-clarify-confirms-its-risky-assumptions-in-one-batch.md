---
type: adr
title: "0029. Clarify confirms its risky assumptions in one batch"
created: 2026-11-24
updated: 2026-11-24
tags:
  - adr
  - shipgate
  - clarify
  - executive
status: accepted
date: 2026-11-24
issue: "#24 (shipgate), child of #37"
related:
  - "../prd/clarify-unknowns.md"
  - "./0026-the-close-out-runs-local-steps-and-asks-once.md"
  - "./0028-settings-live-in-shipgate-json-and-layer-per-key.md"
  - "./0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "./0027-journal-py-is-an-entry-point-over-a-package.md"
  - "../prd/clarify-unknowns.worklog.md"
---

# 0029. Clarify confirms its risky assumptions in one batch

> In `executive` mode, clarify keeps answering alone. Every answer carries a class and a
> source. The risky ones without a source go to the user in one dialog before design, unless
> the `clarify_confirm` setting is `off`. Evidence search, the blindspot pass and the UI
> reference feed that one list; none opens a dialog of its own.

## Context

The executive contract (`feature/SKILL.md`) lets the orchestrator answer routine gate
questions and report them for a veto. The research note for #37 shows the veto does not
happen: 355 executive decisions in two journals, none reviewed by the user, and 52% of the
user's decisions arrive in implement or later. Where the user does answer a question with a
recommended option, the override rate is 26% for domain rules and 35% for naming, against
10% for tests.

Three facts shape every option below:

- `AskUserQuestion` holds at most 4 questions with 2 to 4 options each. One dialog is at
  most 4 items.
- The user has asked for fewer dialogs. ADR 0026 set the pattern: one question, items as
  options, recorded by skill text, no hook.
- A skill-facing setting touches no hook file (ADR 0028, item 6). A new header in the
  reply recorder (`hooks/reply.py`) does.

With a 26% override rate per item, a batch of 4 domain items changes at least one answer
about 70% of the time (1 − 0.74⁴). So the batch is expected to change something in most
runs, which favours asking before design.

## Decision

The user answered the eight forks on 2026-11-24, through the lead: F1-A, F2-A, F3-B, F4-A,
F5-A, F6-A, F7-A and F8-A. F3-B went against the design session's recommendation: the user
wants a per-project way out, as for orchestration.

1. One list. The PRD's "Assumptions (executive)" line gains a class (`domain`, `data`,
   `behaviour`, `technical`) and a source, or "no source found in <what was searched>".
   One search per clarify run fills the sources (F5-A).
2. An answer a source states outright is a constraint and leaves the list; a derived one
   keeps its `[source: <ref>]` tag in the list, and a blindspot candidate always stays.
3. The risky lines (`domain`, `data`, `behaviour` with no source) and the blindspot and UI
   candidates (whatever their source; added in the build's review round 1) form the confirm
   batch, ordered by how much a wrong answer would change the design.
4. At the end of clarify, before design (F1-A), the batch is one `AskUserQuestion`: one
   question per item, at most 4, "Keep" first and recommended (F2-A). Escalations of the run
   share the dialog and come first. Nothing risky and no candidate means no dialog. A lead gets the batch in
   one message; a session with no question tool and no lead prints it.
5. The model records each answer once: the PRD line's end word and one `gate-decision` per
   item. No hook file changes (F7-A).
6. The key `clarify_confirm` (`risky` default, `off`; scope `any`; not on the status line)
   turns the dialog off (F3-B). With `off` there is no dialog, no stop and no batch to a
   lead; the lines keep their class and source; the phase summary lists the risky lines
   first. Escalations still go to the user.
7. `signals.py` computes `own_share` and `unfamiliar` per directory row, with the 0.10
   threshold as a code constant. An unfamiliar or unknown area gets the blindspot pass,
   which adds at most two candidates to the list (F4-A).
8. A module the impact map tags `UI` adds one candidate, the reference to follow, unless
   the request or the issue names the reference: then it is a sourced line and opens no
   dialog. Design
   variants move to #26 (F6-A).
9. Whatever a script can check is a unit or prose test; eval cases judge only what needs a
   model run (F8-A, with the user's two later rules).

## Forks and options

### F1 — When the batch reaches the user

- **F1-A (recommended)** — at the end of clarify, before design. One new stop in an
  executive flow; a changed answer costs nothing downstream.
- **F1-B** — at the design → implement handoff stop that #23 already makes. No new stop; a
  changed answer re-opens design, whose architect fan is the costliest phase before the
  build.
- **F1-C** — clarify and design assumptions together at the handoff. No new stop and design
  choices are covered too; the largest redo risk.

### F2 — The form of the dialog

- **F2-A (recommended)** — one `AskUserQuestion`, one question per item, at most 4. Each
  question puts "Keep: <answer>" first as the recommended option, then one or two
  alternatives from the coverage scan; "Other" takes free text. A dismissed dialog leaves
  the answers in place, marked unconfirmed, and the flow goes on. Up to 4 questions to
  read.
- **F2-B** — one multi-select question, "Which should change?", with up to 4 options. One
  click when all is fine; a change needs a second question, so about 70% of runs get two
  dialogs.
- **F2-C** — no dialog: a ranked, sourced list in the phase summary. Zero stops; the data
  says this veto is not used.

### F3 — Settings

- **F3-A (recommended)** — no new key. The batch is part of `executive` mode. Thresholds are
  constants in code, reviewed with a month of journal data. Every executive user of the
  public plugin gets the dialog, with no opt-out short of `ask` mode.
- **F3-B** — one key `clarify_confirm`: `risky` (default) or `off`, scope `any`, not on the
  status line. Costs a schema entry, a README row and two pinned tests; read once per
  clarify run through `journal.py config`.
- **F3-C** — a third `autonomy` value `confirm`, between `ask` and `executive`; `executive`
  keeps today's behaviour. Opt-in, so no existing user sees a change; every skill check of
  `executive` (feature, clarify, design, setup) must also accept `confirm`, and the schema
  enum, the README and the setup interview grow by one value.

### F4 — The blindspot trigger

- **F4-A (recommended)** — any touched directory at depth 2 with an own share below 0.10 of
  its in-window commits (window: `code_signals.window_months`, default 12). A directory with
  no in-window commits counts as 0, so a new or dormant directory triggers. With the signals
  unavailable or no git identity, the pass runs and says why. Costs one field in
  `signals.py` with tests; adds at most 2 candidates, no dialog.
- **F4-B** — zero own commits in the touched set. Same code; misses an area where the user
  wrote 2 of 200 commits.
- **F4-C** — always run the pass, no trigger. No `signals.py` change; noise in every
  familiar area.
- **F4-D** — drop part 3. No cost; the blind spots of an unfamiliar area stay unasked.

### F5 — Evidence first

- **F5-A (recommended)** — one search per clarify run, not per question: knowledge-base
  recall, the issue with its comments, and the issue's links one level deep (at most 3, only
  what the session can read). The result fills each line's source. About 3 to 8 tool calls
  per run; the batch shrinks.
- **F5-B** — a search before each domain question, quoted in the dialog text. About 2 to 3
  calls per question; longer dialogs.
- **F5-C** — keep today's guardrail ("recall before asking") only. No cost; links are not
  followed and nothing is quoted.

### F6 — Part 4 and #26

- **F6-A (recommended)** — #24 keeps the reference ask as one candidate when the impact map
  tags a module `UI`. Design variants move to #26, which configures the browser tool.
- **F6-B** — all of part 4 moves to #26. #24 is smaller; references keep arriving after a
  defect until #26 lands.
- **F6-C** — #24 keeps both. Variants need a browser tool that only #26 configures.
- **F6-D** — keep the reference ask in #24 and drop variants from both issues.

### F7 — Who records the answers

- **F7-A (recommended)** — the model. It marks each PRD line kept, changed or unconfirmed and
  appends one `gate-decision` per asked item: kept is `raised_by: orchestrator` with
  `--actor user`; changed is `raised_by: user` with `--actor user`. No hook file changes.
  The record is a claim, not an observed answer.
- **F7-B** — the reply recorder. `hooks/reply.py` records answers under a new header. An
  observed record; a hook change, so the full `/security-review` and a separate merge
  question.

### F8 — Evals and their cost

Six new cases: the confirm batch, evidence first, the blindspot pass in an unfamiliar area,
its familiar twin, the UI reference, and an executive run on a fully specified request. Cost
per case per tree (3 runs, with arm): about 1.3 USD on Opus, 2.6 USD on Fable.

- **F8-A (recommended)** — the six new cases plus 15 to 17, both models, baseline on `main`
  and the PR tree after the merge: 9 × 2 × 3.9 ≈ 70 USD.
- **F8-B** — the six plus 15 to 19: 11 × 2 × 3.9 ≈ 86 USD.
- **F8-C** — the six only: 6 × 2 × 3.9 ≈ 47 USD; no regression check on 15 to 17.

## Alternatives considered

- **Four mechanisms, one per part of the issue.** Each part with its own pass and its own
  question. Rejected in the frame: up to four dialogs per run, against the user's ask for
  fewer.
- **A likelihood score per assumption.** The issue asks to order by how likely the user is to
  change an answer. No data predicts that per item; the class filter uses the measured rates
  and the order reuses clarify's design-impact rule.

## Consequences

- The override rate of executive answers becomes a number in `journal.py stats`, which the
  research note lists as not measured.
- #25's digest can read the PRD list and show only the lines decided alone.
- `signals.py` gains one field; FR-007 of the code-signals PRD still holds: shares, never
  names.
- The dialog itself cannot be tested in the eval harness. The two-turn driver could test it
  after the merge; that belongs with #49.
- The cap, the class filter and the line format are computed: the user accepted option P
  of the worklog on 2026-11-24, after this decision. `journal.py assumptions` parses the
  list, names a malformed line (exit 2) and gives the batch with `--risky`. The line
  format is now a contract; #25's digest reuses the parser. The section holds only
  assumption lines, never prose or a code block, and its heading appears once (the user's
  decisions after review rounds 4 and 5: the examples moved to clarify's SKILL.md). For a
  PRD the script cannot
  read (a wiki home), the model applies the same rule. The build added two rules from its
  review: a blindspot or UI candidate is always in the batch, whatever its source (the user
  then ruled that a UI candidate exists only when the request or the issue names no
  reference), and
  `--cap N` leaves room for the escalations that share the dialog.
- Every executive user of the public plugin gets the dialog after the upgrade. The
  changelog says so and names `clarify_confirm: off` as the way out.
