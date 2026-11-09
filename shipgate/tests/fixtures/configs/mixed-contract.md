# shipgate — a production project

## Knowledge base

<!-- Default when absent: PRDs to docs/prd/, ADRs to docs/adr/, worklogs beside the PRD
     as <name>.worklog.md — plain markdown committed to the repo; knowledge capture to
     repo docs; no wiki. -->

- PRD home: `docs/prd/`
- ADR home: <path>

## Autonomy

- Mode: executive
- Executive contract: the orchestrator makes and RECORDS routine decisions itself —
  clarify answers land in the PRD's "Assumptions (executive)" list, design choices in the
  ADR, small calls in the ledger — and reports them in each phase summary so they can be
  vetoed. It still escalates: one-way doors, user-visible scope changes, any change to
  system-wide settings, a new launch agent, and any paid tool.
- Extra escalations: <decisions that must always go to the user, if any>
