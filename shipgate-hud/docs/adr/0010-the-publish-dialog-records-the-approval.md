---
type: adr
title: "0010. The publish dialog records the user's approval"
created: 2026-11-06
updated: 2026-11-06
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-11-06
issue: "#1"
related:
  - "0005-the-publish-gate-checks-the-published-branch.md"
  - "../../../shipgate/docs/adr/0015-the-user-approves-a-publish-outside-the-model-tools.md"
---

# 0010. The publish dialog records the user's approval

> The publish dialog gets a third answer, "Approve publishing". It records one marked
> publish `gate-decision` per held stream, then lets the line through. "Let it through
> once" keeps its meaning and records nothing.

## Context

From shipgate 0.23.0, a user publish decision authorizes only with the marker
`source: dialog` or `source: shell`, and shipgate's PreToolUse hook refuses the marker from
the model (shipgate ADR 0015). The HUD's dialog is where the user's word is taken, but it
recorded nothing: the gate "writes nothing and remembers nothing". So after a "Let it through
once" the flow's `mr-opened` was still refused, and the next push asked again.

## Decision

1. **Three answers.** `Refuse`, `Let it through once` and `Approve publishing`. The third
   appears only when at least one hold is `Unreviewed`; an unreadable journal has no stream
   to record on.
2. **The record.** For each distinct `Unreviewed` stream, in textual order, one
   `journal.py append --stream <s> --type gate-decision --actor user` with
   `gate: publish`, `decision: publish`, `raised_by: user`, `mode: ask`,
   `source: dialog` and a short `question` naming the held command. The HUD runs it with
   `$.process.run`, which is no tool call, so no PreToolUse hook sees it.
3. **A failed record still passes.** The user answered "approve"; the line goes through,
   as for "Let it through once". The next publish asks again.

## Alternatives considered

- **"Let it through once" records.** The label would then lie: the record authorizes every
  later publish of the stream until its next `task-done`.
- **Record only on the `!` path.** The user would leave the dialog to type a JSON payload.

## Consequences

- The HUD now writes to the journal, one event per approval. The README says so.
- An approval lasts until the stream's next `task-done`, as every publish authorization
  does.
- With a shipgate older than 0.23.0 the record carries a key that journal.py does not check,
  and the old rule authorizes it as before.
