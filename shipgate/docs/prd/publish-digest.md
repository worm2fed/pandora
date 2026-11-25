---
type: prd
title: "PRD: The publish gate shows what changed and what was decided alone"
created: 2026-11-25
updated: 2026-11-25
tags:
  - prd
  - shipgate
  - review
  - publish
status: clarified
issue: "#25 (shipgate), child of #37"
worklog: "./publish-digest.worklog.md"
related:
  - "../adr/0030-the-publish-digest-is-computed-and-rides-the-publish-question.md"
  - "../adr/0013-signals-emits-the-ranking-the-journal-carries.md"
  - "../adr/0015-the-user-approves-a-publish-outside-the-model-tools.md"
  - "../adr/0021-the-handoff-brief-is-computed-not-written.md"
  - "../adr/0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "../adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
  - "./clarify-unknowns.md"
  - "../research/2026-11-15-agent-harness-audit.md"
---

# PRD: The publish gate shows what changed and what was decided alone

> Before the user approves a publish, one short block shows what the change does, which
> decisions the orchestrator took alone, where the build left the plan, and which files to
> read first. A script builds the block from the journal and the artifacts.

## Terms

- **Digest**: the block this feature adds. A script computes it. It never writes.
- **Decided alone**: an answer or a choice that the orchestrator took in `executive` mode and
  that the user has not confirmed.
- **Deviation**: a place where the build left the committed design.
- **Publish question**: the `AskUserQuestion` with the header `Publish` that the review asks
  after a ready verdict (`review/SKILL.md:643-663`). The user's answer to it is the publish go.
- **Hold dialog**: the shipgate-hud dialog with "Approve publishing". It opens only when a push
  has neither a ready verdict nor a publish go (`shipgate-hud/hooks/publish.ts:1103-1109`).
- **Slot**: the number of item lines one part of the digest may print.

## Problem

A ready verdict reports findings and evidence. It does not say what the change does, which
decisions the orchestrator took alone, or where the build left the plan. The user must
remember to ask, and the user does not ask. The issue's evidence, from seven flow journals
(9,449 events) and 148 main-session transcripts:

- 0 of 190 user messages after a finished task ask for a summary or for "what changed".
- The user found 18 design or code-quality issues late, by asking "why X?".
- The agent's text mentions deviations in 45 of 119 sessions. The user asked about them once.
- Two journals hold 355 executive decisions.

This repo's own journal, measured on 2026-11-25:

- 280 executive `gate-decision` rows over 51 streams: a median of 3 a stream, 13 at the
  90th percentile, 29 at most. 107 of them are at the clarify gate, 71 at design and 41 at
  implement.
- 110 `deviation` rows. 56 carry no `kind`. Their notes have a median of 185 characters and
  at most 429. A stream holds a median of 2 such rows and at most 11.
- 66 of 127 review verdicts carry a risk ranking. 58 of those hold exactly 3 files.
- Every PRD in `shipgate/docs/prd/` that has an "Assumptions (executive)" section predates the
  strict line form of #24. `journal.py assumptions` refuses each one at its first item.
- The "Deviations & notes" section of one worklog here holds 71 list lines and prose besides.

The gate the user answers is the publish question. The hold dialog does not open in the
normal flow, because a ready verdict lets the push through it.

## Goals & non-goals

**Goals**
- The user reads what was decided alone before approving a publish, without asking.
- A script computes every part a script can compute. A unit test pins each part.
- The digest adds no stop and no question to the flow.

**Non-goals**
- The digest does not change who approves a publish. Only the user's go publishes.
- No hook file changes. The command gate, the recorder and `mr-opened` read the same events.
- No shipgate-hud change. The hold dialog stays as it is (F1).
- No publish quiz (F4). The digest gives the same facts with no question.
- The digest is no review. It does not judge the change.
- The digest has no slot for the screenshot evidence of #26. #26 adds its own part in its
  own change.

## Users & stories

- As the user, I want to see the decisions taken alone at the moment I approve, so that I
  can ask "why X?" before the change leaves, not after.
- As the user, I want the digest to stay short, so that I read it.
- As a lead that asks the user on behalf of a teammate, I want the same digest the teammate's
  review prints, so that the user decides on the same facts.

## Functional requirements

- **FR-001** — A `journal.py` command prints the digest of one stream. It reads the journal
  and the artifact files that the stream's events name. It writes nothing and runs no git. A
  stream with no events exits 1, as `position` does.
- **FR-002** — The digest is one markdown table, its only text form. Its header row names the
  stream, the newest review verdict with its round, and the state of the user's publish go
  (held or authorized).
- **FR-003** — "What changed" comes from a `## What changed` section of the stream's worklog:
  1 to 5 list items of one line each. The review writes the section before its verdict (F2).
  The digest accepts only that form, and the table shows the first 3 items. With no section, the digest says so and names the
  worklog. With a malformed section, it prints the worklog's path, the line number and the
  reason.
- **FR-004** — "Decided alone" lists two kinds of item (F3):
  - the PRD's "Assumptions (executive)" items with no end tag or with `[unconfirmed]`, read
    with the parser of #24 and its strict section rule;
  - the executive `gate-decision` rows that the orchestrator recorded after the stream's
    last `clarify-passed`, or every such row when the stream has none.
  The risky PRD items come first (the rule of #24's confirm batch), then the gate decisions
  in the order they were recorded, then the other PRD items. A PRD the parser refuses gives
  one line with the PRD's path, the line number and the reason.
- **FR-005** — "Deviations" lists the `deviation` events recorded after the stream's last
  `design-committed`, or every one when the stream has none (F5). Bookkeeping rows are left
  out: those of kind `signals-missing`, `style-missing` or `gate-waived`, and every row that
  carries `report_to`. The digest does not parse the worklog's "Deviations & notes" section.
- **FR-006** — "Look first" names the first 3 files of the newest risk ranking that the
  stream carries (ADR 0013): the ranking of the newest review verdict that has one, else the
  ranking of the newest `design-committed` that has one. With no ranking, or with a ranking
  whose source is `none`, one line says so.
- **FR-007** — Each part has a fixed slot of rows (F6, as amended): what changed 3, decided
  alone 2, deviations 2, look first 1. With the header row and the separator, the digest
  prints at most 10 lines. The first cell of a part names it on its first row only, and a
  part over its slot names its full count there. An unused slot is not given to another
  part.
- **FR-008** — Every value is collapsed to one line and clipped at 160 characters, as the
  status brief and the handoff brief do (#39). A character that is not printable is
  replaced. Each character of a fixed set that markdown gives meaning to in a table cell
  gets a backslash, so a value cannot add a row, a column, a link that hides its target, an image, HTML or
  emphasis. A ref that is absolute or holds a `..` segment
  is dropped, as `position` drops it. The digest prints no rationale, no source tag and no
  event field other than those this PRD names.
- **FR-009** — A malformed section prints its file, its line and the reason in place of its
  part. The command still exits 0, because the digest is a view and never a gate.
- **FR-010** — `--all` prints every item of every part in the same table, each row still
  clipped. `--json`
  prints the digest's data for a program and for the tests.
- **FR-011** — The review prints the digest with a ready verdict (F1).
- **FR-012** — The session prints the digest of each stream it asks about as a chat message
  right before the publish question (F1, as amended). The `Publish` option carries no
  preview.
- **FR-013** — A teammate whose review is ready sends its lead the stream name and the path
  of its worktree, not the digest text (F7). The lead runs the digest with that worktree as
  its working directory and prints the output as its own message, then asks.
- **FR-014** — The publish authorization is unchanged: the command gate, the recorder, the
  hold dialog's rule and `mr-opened` read the same events as before. A missing or a malformed
  digest part never holds a publish.
- **FR-015** — The MR/PR body's Summary starts from the worklog's "What changed" section.

## Success criteria

- **SC-001** — On a fixture stream with more items than each slot, the digest prints at most
  the slot's number of rows per part and at most 10 lines in all. Each part over its
  slot prints its full count. A unit test pins both numbers.
- **SC-002** — On a fixture PRD in the form before #24, the digest prints one line with
  `<prd>:<line>` and the parser's reason, and exits 0.
- **SC-003** — No file under `shipgate/hooks/` or `shipgate-hud/` changes. `git diff --stat`
  on the build shows none.
- **SC-004** — The review skill names the digest command at the ready verdict and at the
  publish question, and defines the "What changed" section. A prose test pins each.
- **SC-005** — The digest of the build's own stream renders at its review with no error line,
  and the review quotes it.
- **SC-006** — On the largest stream of this repo's journal, the command finishes in under
  1 second.
- **SC-007** — Every line the digest prints is at most 160 characters and holds no newline,
  for any payload, and every value cell is inert markdown. Unit tests feed payloads with
  newlines, long text and markdown in every part.

## Constraints & assumptions

- The journal refuses a payload over 1 KB on a work stream. A review verdict already carries
  `criteria`, `dispositions` and `ranking`, and the review skill tells the model what to drop
  when it does not fit (`review/SKILL.md:553-562`). So "what changed" cannot ride the verdict.
  [source: `review/SKILL.md`]
- The eval harness has no question dialog, so no eval case can see the publish question.
  [source: #49]
- The digest reaches the user as a chat message. It writes nothing into the repo.

## Assumptions (executive)

- [technical] [source: shipgate/scripts/_journal/position.py] Which recorded ranking feeds "look here first"? → the newest `review-verdict` that carries `ranking`, else the newest `design-committed` that carries one — the reviewers were dispatched from the verdict's ranking, and position already exposes both as `trace`
- [behaviour] [source: shipgate/skills/implement/SKILL.md] Which deviation events count? → those after the stream's last `design-committed`, or all of them when there is none — a deviation is a divergence from the design, and the earlier rows record process notes
- [technical] [no source found in the journal package and the review skill] Does a malformed part fail the command? → no; the part prints `<file>:<line>: <reason>` and the command exits 0 — the digest is a view, and the error then reaches the user in the dialog
- [technical] [no source found in the journal package] Does the digest run git? → no; it reads the journal and the files the events name — the ranking already names the files, and a git call adds a failure mode in the dialog path
- [behaviour] [no source found in the settings schema and ADR 0028] Does the digest get a setting? → no — it adds no stop and no question, so a switch would only add one more key to document
- [technical] [source: shipgate/scripts/_journal/position.py] Is there a machine form? → yes, `--json`, as `position` has — the tests read the data, and a later HUD view needs no second renderer

## Decisions (the user, through the lead, 2026-11-25)

The eight forks. ADR 0030 holds the options and their costs. The user took the design
session's recommendation on each.

- **F1** — option A: the review prints the digest with the ready verdict, and the publish
  question carries it as the `preview` of its `Publish` option. No shipgate-hud change
  (FR-011, FR-012). Amended the same day, after the first real dialog: the user found the
  preview hard to read, so the digest is a chat message right before the question, and the
  option carries no preview (ADR 0030, amendment).
- **F2** — option A: the review writes a strict `## What changed` worklog section, 1 to 5
  one-line items, before the verdict (FR-003, FR-015).
- **F3** — option B: the unconfirmed PRD items plus the executive gate decisions after
  `clarify-passed` (FR-004).
- **F4** — option A: the publish quiz is dropped.
- **F5** — option A: `deviation` events only; the worklog section is named, not parsed
  (FR-005).
- **F6** — option A: fixed slots, at most 16 lines of at most 160 characters (FR-007,
  FR-008). Amended after the second dialog: the user found 16 lines too long and the
  line form hard to read, so the digest is one markdown table with slots 3, 2 and 2 and a
  Look first row (ADR 0030, second amendment).
- **F7** — option A: the teammate sends its stream name and worktree path; the lead runs the
  digest (FR-013).
- **F8** — option A: no new eval case; unit tests and prose tests cover the change.

The lead added three rules for the build:

- The worklog template (`design/references/worklog-template.md`) stays as it is. The review
  skill defines the "What changed" section, so the design changes of #26 do not collide.
- #25 ships first and has no part for #26. The worklog says where a part is added and how
  the line cap grows.
- This change takes ADR 0030; #26 takes 0031.
