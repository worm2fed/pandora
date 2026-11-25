---
type: adr
title: "0030. The publish digest is computed and rides the publish question"
created: 2026-11-25
updated: 2026-11-25
tags:
  - adr
  - shipgate
  - review
  - publish
status: accepted
date: 2026-11-25
issue: "#25 (shipgate), child of #37"
related:
  - "../prd/publish-digest.md"
  - "../prd/publish-digest.worklog.md"
  - "./0013-signals-emits-the-ranking-the-journal-carries.md"
  - "./0015-the-user-approves-a-publish-outside-the-model-tools.md"
  - "./0021-the-handoff-brief-is-computed-not-written.md"
  - "./0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "./0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
---

# 0030. The publish digest is computed and rides the publish question

> `journal.py digest --stream S` computes a block of at most 16 lines from the journal and
> the artifacts: what changed, what was decided alone, the deviations, and the files to read
> first. The review shows it with the ready verdict and puts it into the publish question.
> It adds no dialog, no setting and no hook change, and the approval stays the user's.

## Context

A ready verdict reports findings and evidence. It does not say what the change does or which
decisions the orchestrator took alone. The research note for #37 counts 0 asks for a summary
in 190 user messages after a finished task, 18 design or code-quality issues the user found
late by asking "why X?", and 355 executive decisions in two journals.

Four facts shape every option below:

- The user approves a publish in the publish question: an `AskUserQuestion` with the header
  `Publish` (`review/SKILL.md:643-663`). The shipgate-hud hold dialog opens only when a push
  has neither a ready verdict nor a publish go (`shipgate-hud/hooks/publish.ts:1103-1109`), so
  it does not open in the normal flow.
- A review verdict already fights the 1 KB payload cap (`review/SKILL.md:553-562`).
- Every PRD in this repo with an "Assumptions (executive)" section predates the strict form
  of #24; the parser refuses each one at its first item.
- The implement skill records each divergence twice: a worklog line and a `deviation` event
  (`implement/SKILL.md:110-112`, `178-180`). The worklog section mixes notes and divergences
  and has no strict form.

The user's rules for this epic bind the choice: what a script can compute, a script computes;
fewer dialogs; one mechanism over two; a strict, small contract that refuses with a line
number.

## Decision

A new command, `journal.py digest --stream S`, prints the digest. It reads the journal and
the files the stream's events name, writes nothing and runs no git. It has four parts in a
fixed order, each with a fixed slot:

1. **What changed**, up to 5 lines, from a `## What changed` section of the worklog. The
   review writes the section before its verdict. The digest accepts only one-line list items,
   1 to 5 of them, and names `<worklog>:<line>: <reason>` for anything else.
2. **Decided alone**, up to 4 lines: the PRD's assumption items with no end tag or with
   `[unconfirmed]` (the parser of #24), and the executive `gate-decision` rows the
   orchestrator recorded after the last `clarify-passed`. Risky PRD items come first, then
   the gate decisions in seq order, then the other PRD items.
3. **Deviations**, up to 3 lines: the `deviation` events after the last `design-committed`,
   without the bookkeeping kinds. The part names the worklog for the full notes.
4. **Look here first**, 1 line: the first 3 files of the newest recorded risk ranking.

With its first line and one heading for each list part, the digest prints at most 16 lines
of at most 160 characters. A part over its slot names its count and the `--all` flag. A
malformed section prints its error line in place of the part, and the command exits 0.

The review prints the digest with a ready verdict and puts it, freshly run, into the
`preview` of the publish question's `Publish` option. A lead that asks for a teammate's
stream runs the digest itself, with the teammate's worktree as its working directory. The
digest changes no approval rule and no hook file.

The user took the design session's recommendation on all eight forks (2026-11-25, through
the lead). The design session took six smaller calls alone; the PRD's "Assumptions
(executive)" list holds them, and none was vetoed.

## Forks and options

### F1 — Where the digest is shown

- **A (chosen)** — the review prints it with the ready verdict, and the publish question
  carries it as the `preview` of its `Publish` option. No shipgate-hud change. A multi-select
  question has no preview, so for several streams the digests print before it.
- **B** — A, plus the HUD hold dialog. It needs a shipgate-hud release with its own tag and
  one more `journal.py` run in the hold path, and it reaches the user only on a push with no
  review and no go.
- **C** — A, plus the HUD pane's Review tab: a HUD release for a pane the user may not look
  at when answering.
- **D** — terminal only: the digest can scroll away while the dialog is open.

### F2 — Who writes "what changed"

- **A (chosen)** — the review writes a strict worklog section before the verdict; the MR/PR
  Summary reuses it. When it is missing, the digest says so in the dialog.
- **B** — computed from the titles of the done Build Plan tasks: build steps, not outcomes,
  and a plan often holds 10 to 25 tasks.
- **C** — a `summary` field on `review-verdict`: it does not fit under the 1 KB cap.
- **D** — dropped: the user still would not see what the change does.

### F3 — What "decided alone" covers

- **A** — the unconfirmed PRD items only. It misses the design and implement choices, 112 of
  the 280 executive decisions in this repo's journal.
- **B (chosen)** — A, plus the executive gate decisions after `clarify-passed`. Clarify's own
  rows are skipped, so no item shows twice.
- **C** — gate decisions only, every phase: loses the class and source tags of #24.

### F4 — The publish quiz

- **A (chosen)** — dropped. The digest gives the same facts with no question. A quiz of "3
  to 5 questions" would ask 5 every time, as the #24 run showed for open lists. A quiz in a
  dialog of its own after the go request would also witness that request (`plan_reply`) and
  call for a confirming question.
- **B** — behind a `publish_quiz` setting, default off, inside the publish dialog.
- **C** — a new issue after a month of digest use.

### F5 — The deviation source

- **A (chosen)** — `deviation` events only. A divergence logged only in the worklog does not
  show; implement already asks for the event.
- **B** — events and the worklog section: a second strict parser that would refuse nearly
  every existing worklog, and fuzzy duplicate matching.
- **C** — the worklog section only: it has no strict form.

### F6 — The size

- **A (chosen)** — fixed slots 5, 4, 3 and 1 line, at most 16 lines. An unused slot is not
  given to another part.
- **B** — 12 lines: cuts more than the 90th percentile of executive decisions (13).
- **C** — one byte budget with a cut order across parts: a layout that moves with the
  content.

### F7 — The lead-and-teammate path

- **A (chosen)** — the teammate sends its stream name and worktree path; the lead runs the
  digest there. Run from the main checkout, the digest does not find the uncommitted
  artifacts and says so.
- **B** — the teammate sends the digest text: stale at ask time, and editable on the way.

### F8 — The eval plan

- **A (chosen)** — no new case. Unit tests pin the parts, the slots and the clipping; prose
  tests pin the review sentences. The harness has no question dialog (#49).
- **B** — one case, Opus only, about 1.3 to 1.8 USD: a regex grader on the worklog section.

## Alternatives considered

- **The digest as a field of an event**, written by the model at the verdict. It would put
  the model's words where the journal's facts belong, and the verdict payload has no room.
- **A shared renderer with the handoff brief.** The handoff brief serves a fresh session; the
  digest serves the user at one gate. They share the clipping helpers, not the layout.

## Consequences

- The user sees the decisions taken alone in the dialog where they approve. Nothing new asks
  them a question.
- Clarify's executive answers now matter at two gates: the confirm batch of #24 before design,
  and the digest before publishing.
- The review writes one more section, and the digest shows when it is missing.
- PRDs written before #24 give an error line in the "decided alone" part. They are not
  rewritten.
- A new part, such as the screenshot evidence of #26, is one entry in the ordered list of
  parts; the line cap grows by that part's heading and slot.
- No hook file and no shipgate-hud file changes, so the approval path keeps its review.
