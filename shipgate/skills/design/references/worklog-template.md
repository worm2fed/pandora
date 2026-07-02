---
type: worklog
title: "Worklog: <Feature name>"
created:
updated:
tags:
  - worklog
status: designing
prd: "./<feature-kebab>.md"
related: []
---

# Worklog: <Feature name>

> Design + build plan companion to `./<feature-kebab>.md`.

---

# Design

## Approach

Chosen approach (which architect philosophy won, in one line) and the core trade-off.

## Architecture

Components, responsibilities, and how they fit together. Diagram if it clarifies.

## Data flow

Entry → ... → store → response. Note write→read path and any shared state.

## Data model / schema

New or changed entities, tables, migrations. Note any downstream data obligations.

## API / contract changes

Endpoints, payloads, events, websocket messages. Note breaking changes + the parallel-change/
deprecation plan for any public/external surface.

## CLAUDE.md / impact-map compliance

- <each repo-rule obligation the impact map flagged, and how it's met>

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations
- [ ] T001 — <task> — file(s): `...` — done when: <...>

## Feature
- [ ] T010 [P] — <task> — file(s): `...` — done when: <...>
- [ ] T011 — <test for T010> — file(s): `...` — done when: test fails first, then passes

## Polish
- [ ] T020 — <task>

## Traceability
- FR-001 → T010, T011
- SC-001 → T011, manual walkthrough

## Deviations & notes (filled during implementation)
- <date> — diverged from design at T0NN because <...>; impact: <...>
