// Generic fixtures: a public repository, so stream names, task titles and questions are
// invented, never copied from a private project.

export const FEATURE = {
  age_days: 0,
  branch_match: true,
  dormant: false,
  feature: 'feat/example-stream',
  gate_decision_count: 3,
  gate_decisions: [
    {
      decision: 'no PRD; executive assumptions in the worklog',
      gate: 'clarify',
      mode: 'executive',
      question: 'PRD for a prose-only fix?',
      raised_by: 'orchestrator',
      ts: '2026-10-01T08:00:00+00:00',
    },
    {
      decision: 'yes, both',
      gate: 'clarify',
      mode: 'ask',
      question: 'Both widgets, or one?',
      raised_by: 'orchestrator',
      ts: '2026-10-01T08:30:00+00:00',
    },
    {
      decision: 'publish',
      gate: 'publish',
      mode: 'ask',
      question: 'How does it land?',
      raised_by: 'user',
      ts: '2026-10-01T09:00:00+00:00',
    },
  ],
  implied_phase: false,
  last_event: { seq: 42, ts: '2026-10-01T09:30:00+00:00', type: 'task-done' },
  last_verify: {
    outcome: 'pass',
    scope: null,
    task_ids: ['T001', 'T010'],
    ts: '2026-10-01T09:20:00+00:00',
  },
  open_designs: [],
  phase: 'implement',
  phase_entered_at: '2026-10-01T09:10:00+00:00',
  stream: 'feat/example-stream',
  task_ids: ['T001', 'T010'],
  tasks_done: 2,
  terminal: false,
  version: 12,
}

export const STATUS = {
  branch_match: 'feat/example-stream',
  features: [FEATURE],
  hidden_terminal: 3,
  ledger: { entries: 0, exists: true, nudge: false, path: 'docs/ledger.md' },
}

export const LOG = {
  events: [
    { seq: 30, type: 'flow-started', ts: '2026-10-01T07:00:00+00:00', data: { request: 'x' } },
    { seq: 31, type: 'phase-entered', ts: '2026-10-01T07:01:00+00:00', data: { phase: 'workspace' } },
    { seq: 32, type: 'phase-entered', ts: '2026-10-01T07:02:00+00:00', data: { phase: 'route-and-map' } },
    { seq: 33, type: 'phase-entered', ts: '2026-10-01T07:03:00+00:00', data: { phase: 'clarify', implied: true } },
    { seq: 34, type: 'clarify-passed', ts: '2026-10-01T08:00:00+00:00', data: { prd: 'docs/prd/example.md' } },
    {
      seq: 35,
      type: 'design-committed',
      ts: '2026-10-01T08:30:00+00:00',
      data: {
        worklog: 'docs/prd/example.worklog.md',
        adrs: ['docs/adr/0007-example-decision.md'],
        refs: ['docs/prd/example.worklog.md#design'],
      },
    },
    { seq: 36, type: 'phase-entered', ts: '2026-10-01T09:10:00+00:00', data: { phase: 'implement' } },
    { seq: 40, type: 'verify-run', ts: '2026-10-01T09:20:00+00:00', data: { outcome: 'pass', task_ids: ['T001', 'T010'] } },
    { seq: 41, type: 'task-done', ts: '2026-10-01T09:21:00+00:00', data: { task_id: 'T001' } },
    { seq: 42, type: 'task-done', ts: '2026-10-01T09:30:00+00:00', data: { task_id: 'T010' } },
    { seq: 43, type: 'verify-run', ts: '2026-10-01T09:40:00+00:00', data: { outcome: 'fail', task_ids: ['T010'] } },
    // an absolute ref and a parent-traversal ref: the HUD must never read these
    { seq: 44, type: 'deviation', ts: '2026-10-01T09:41:00+00:00', data: { refs: ['/etc/evil.worklog.md', '../../outside/adr/0001-x.md'] } },
  ],
}

/** The same stream named with the `feature/` prefix the journal folds into a bare slug. */
export const FEATURE_PREFIXED = {
  ...FEATURE,
  feature: 'example-stream',
  stream: 'feature/example-stream',
}

export const SIDECAR = {
  version: 1,
  db: '.claude/shipgate.db',
  ledger: 'docs/ledger.md',
  artifact_homes: {
    worklog: '*/docs/prd/*.worklog.md',
    prd: '*/docs/prd/*.md',
    adr: '*/docs/adr/*.md',
  },
}

export const WORKLOG = `---
type: worklog
title: "Worklog: Example"
status: implementing
---

# Worklog: Example

# Design

## Approach

Minimal change: one module, one test.

## Architecture

- parser
- view

# Build Plan

## Setup
- [x] T001 — add the widget — file(s): \`src/widget.ts\` — done when: compiles
- [ ] T002 — wire the widget — file(s): \`src/app.ts\` — done when: used

## Feature
- [x] T010 [P] — parse the input — file(s): \`src/parse.ts\` — done when: T011 passes
- [x] T011 — tests for T010 — file(s): \`tests/parse.test.ts\` — done when: fails first, then passes

## Traceability
- FR-001 → T010
`

export const ADR = `---
type: adr
title: "0007. Example decision"
status: accepted
---

# 0007. Example decision

> One line.
`
