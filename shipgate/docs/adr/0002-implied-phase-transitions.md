---
type: adr
title: "0002. Phase-owning events imply the phase; append records the transition"
created: 2026-09-02
updated: 2026-09-02
tags:
  - adr
status: accepted
date: 2026-09-02
issue: "none / ad-hoc"
related: ["../prd/journal-cost-and-workflows.md", "0001-sqlite-flow-journal.md"]
---

# 0002. Phase-owning events imply the phase; append records the transition

> When an event that can only happen inside one phase is appended while the stream's folded
> phase differs, `append` writes the `phase-entered` itself, in the same transaction,
> flagged `implied: true`, and says so on stdout. It does not refuse.

## Context

`status.phase` is the brief's headline field and, on the reference export, the least
reliable one: most streams read a phase two or three steps behind the events that follow
it, because `phase-entered` is only gated on *ordering* while nothing requires it to
exist. The orchestrator forgot it roughly four times out of five relative to the events
that imply a phase (`clarify-passed`, `design-committed`, `verify-run`, `task-done`,
`review-verdict`, `capture-done`). Every other precondition in the journal *refuses* the
append (task-done without a passing verify, review-verdict=ready without fresh evidence),
so the obvious shape is a new refusal. The failure mode here is different: it is omission
of a bookkeeping event, not a false claim of evidence, and a refusal just costs one more
tool call to type what the journal already knows.

## Decision

`append` derives the phase from the event type (a fixed table in `journal.py`), compares
it with the stream's folded phase, and when they differ inserts `phase-entered
{phase, implied: true, implied_by: <type>}` immediately before the event, inside the same
`BEGIN IMMEDIATE` transaction. Forward jumps that skip phases are recorded with the
intervening phases in `skipped` (the implied transition has no one to ask). The append's
output names the transition; the brief marks an implied phase `(implied)`; `stats` counts
implied transitions per stream so a flow that never records its own phases is visible.
Backward transitions (a `task-done` after a `review-verdict`) are implied the same way —
they are the review-feedback loop, and the brief should show it.

## Alternatives considered

- **Refuse, like the other gates** — consistent, but the observed failure is forgetting,
  not lying; refusing converts an omission into friction on every phase boundary, and
  the orchestrator would answer it by typing the event the journal could have written.
- **Fold-time inference only (leave the log as is, compute phase from the latest
  phase-owning event when rendering)** — no write, but the log then disagrees with the
  brief, `phase-entered` becomes decorative, and the ordering gate loses its subject.

## Consequences

Position becomes reliable without new orchestrator work. The risk is masking: an event
appended to the *wrong* stream now also moves that stream's phase. Mitigations are the
stdout echo, the `(implied)` marker in the brief, and the `stats` count. `import` stays
gate-free, so historical rows are neither rewritten nor back-filled.
