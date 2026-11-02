---
type: prd
title: "PRD: The style canon and the code graph leave a trace"
created: 2026-11-02
updated: 2026-11-02
tags:
  - prd
  - shipgate
status: clarified
issue: "#11, #10"
worklog: "./style-and-graph-trace.worklog.md"
related:
  - ../adr/0011-a-map-without-signals-records-its-own-deviation.md
  - ../adr/0012-the-canon-reviewer-loads-the-style-skill-itself.md
  - ../adr/0013-signals-emits-the-ranking-the-journal-carries.md
  - ./code-graph.md
  - ./code-signals.md
---

# PRD: The style canon and the code graph leave a trace

> The flow records which style skills it named and which risk ranking it used, the review
> runs a canon lens, and `stats` reports both per stream.

## Problem

A config can name style skills in its **Style** section. On a production project's journal
(3961 events, 57 streams), 0 events mention the style skill. The review fan has no lens that
holds the canon. A reviewer without the canon treats its rules as taste and declines them.
So the user finds canon violations after a `ready` verdict, and each one costs a rework
round (#11).

The code signals have the same gap (#10). `route-and-map` computes them, and nothing carries
them further. 6 of 37 explicit `route-and-map` entries carry `signals`. 0 of 34
`design-committed` events and 2 of 96 `review-verdict` events carry a risk ranking. A
`blast` count from the regex scanner and one from the graph look the same in the journal,
because 3 of the 6 signal payloads name no source. A repository without a graph index gets
one advisory line once per project, and then nothing.

## Goals & non-goals

**Goals**
- The journal tells "the style skill was named" from "it was never named", per phase.
- The review holds the canon in one reviewer and scores its findings as rule violations.
- The journal carries the risk ranking from `route-and-map` through `design` and `review`.
- A map without signals leaves a recorded deviation.
- `journal.py stats` answers both questions from the journal alone.

**Non-goals**
- No hook change. Hooks cannot see a worker brief, and the hook contract is an escalation.
- No HUD change in part 1. Superseded by part 2 of the batch: shipgate-hud 0.7.0 draws the
  new keys (HUD ADR 0007; worklog, Part 2).
- No grading of `signals.py blast` against ground truth (#6 covers that).
- No refusal of an existing payload. Old callers keep working.

## Users & stories

- As a maintainer tuning the flow, I want `stats` to say per stream whether the style skill
  was named at implement and at review, so that I can find where the canon was skipped.
- As a user with a typed-FP canon, I want the review to catch canon violations before the
  verdict, so that a `ready` verdict means no canon rework.
- As a maintainer, I want `stats` to say how often the graph fed design and review, so that
  I can tell whether the code graph earns its cost.

## Functional requirements

- **FR-001** — The `implement` and `review` `phase-entered` payloads carry `style`: the
  list of style skills the config's Style section names, or `[]` when it names none.
- **FR-002** — The `model-tiers` worker brief has a required **Style** line. The flow
  records a `deviation` with `kind: style-missing` for a brief dispatched without it.
- **FR-003** — When the config's Style section names a skill, the review adds a `canon`
  lens: one reviewer that loads the skill before it reads the diff. It scores each finding
  as a violation of a named canon rule, never as taste. The finding takes a disposition in
  `review-verdict.dispositions` like any other.
- **FR-004** — The review Workflow script accepts the `canon` lens and the style skills to
  load. It refuses a `canon` lens with no skills named. A refuter of a canon finding loads
  the same skills.
- **FR-005** — Every `route-and-map` `phase-entered` carries `signals` with `source` set to
  `graph`, `regex` or `none`. `append` refuses a `signals` block with another `source`.
- **FR-006** — A `route-and-map` `phase-entered` without `signals` makes `append` record a
  `deviation` with `kind: signals-missing` in the same transaction.
- **FR-007** — `signals.py` prints a `graph_note` line on every call where a repository has
  no usable graph index. The line says why and how to build one. The map relays it.
- **FR-008** — `signals.py hotspots --json` carries `ranking`: the structure source and the
  top files with their `fix`, `churn` and `fan_in` labels, small enough for a journal event.
- **FR-009** — `design-committed` and `review-verdict` carry the `ranking` the phase used.
  The review builds its reviewer briefs from that ranking.
- **FR-010** — `append` validates `style`, `signals` and `ranking`, and `vocab --shape`
  prints the rules for each one.
- **FR-011** — `journal.py stats` reports per stream: the style state at implement and at
  review, the signal source at route-and-map, and the ranking source at design and at
  review. Its totals say how many streams had each one.
- **FR-012** — Two eval cases: a canon review case and a graph-past-route case, with
  graders. They are written, not run.

## Success criteria

- **SC-001** — An `implement` or `review` `phase-entered` with `style` appends, and
  `stats --json` reports `named`, `none` or `missing` for it.
- **SC-002** — `append` of a `route-and-map` `phase-entered` without `signals` writes a
  `deviation` row with `kind: signals-missing`. One with `signals.source: graph` writes no
  deviation. One with `signals.source: maybe` exits 4.
- **SC-003** — `signals.py hotspots --json` prints `ranking` with at most 5 files and
  `source`. A repository with no graph index prints `graph_note`.
- **SC-004** — The review Workflow script runs a `canon` finder whose prompt names the
  style skills. It throws when `canon` comes without `styleSkills`.
- **SC-005** — `stats` prints a trace section, and its totals count the streams where the
  graph fed design and review.
- **SC-006** — The review skill, the `code-reviewer` agent and the `model-tiers` brief name
  the canon lens and the Style line. The `code-reviewer` agent can load a skill.
- **SC-007** — Eval cases 74 and 75 exist with a fixture, a prompt and graders.
- **SC-008** — The full shipgate suite passes, and `claude plugin validate shipgate`
  passes.

## Constraints & assumptions

- Payload keys are added, never renamed or removed. The HUD decodes them.
- Every new payload stays under the 1 KB cap on a work stream.
- Python 3.9, standard library only.
- Nothing from a private project goes into the repo: counts only.

## Assumptions (executive)

- Does `style: []` mean "none named"? → yes, and a missing key means "missing" — the
  journal must tell "none configured" from "not recorded".
- Should `append` refuse a map without signals? → no, it records a deviation — ADR 0011.
- How does the canon reviewer hold the canon? → it loads the skill itself through the
  `Skill` tool — ADR 0012.
- Who builds the ranking payload? → `signals.py`, so it is never hand-copied — ADR 0013.
- Should a phase-entered without `style` also auto-record a deviation? → no — an implied
  `implement` or `review` entry has no `style`, so it would fire on every fix round; `stats`
  reports it as `missing` instead.
- A sibling report or `stats`? → `stats`, with a trace section, because one command already
  answers "what did the flow do".
- How many ranking files? → 5, each path cut to its last 3 segments, the form the review
  dispositions already use.
