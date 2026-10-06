---
type: prd
title: "PRD: Thinking lenses inlined into the phase skills"
created: 2026-10-06
updated: 2026-10-06
tags:
  - prd
  - shipgate
status: clarified
issue: "none / ad-hoc"
worklog: "./thinking-lenses.worklog.md"
related:
  - "https://github.com/tjboudreaux/cc-thinking-skills"
---

# PRD: Thinking lenses inlined into the phase skills

> Absorb the useful remaining `cc-thinking-skills` lenses into shipgate's phase skill bodies so
> the standalone 39-skill plugin can be dropped.

## Problem

A standalone thinking-skills plugin lists 39 skills. The session skill listing has a budget of
about 1% of context, so most of those descriptions are truncated and the skills never fire — in
practice only the 4 whose descriptions survived ever triggered. shipgate already applies lenses
better: inlined into the phase skill that needs them (design: reversibility, pre-mortem;
structured-debug: occam, kepner-tregoe, five-whys-plus; code-reviewer: red-team), they fire
deterministically at the right phase and cost nothing in the listing.

## Goals & non-goals

**Goals**
- Each lens in the mapping below applies by default at its phase, as a few lines plus the
  condition under which it applies.
- The standalone plugin becomes unnecessary for the engineering flow.
- The adapted text is credited (MIT, © 2025 TJ Boudreaux).

**Non-goals**
- No new skills; no frontmatter `description` changes (descriptions are tuned for triggering
  and measured by the evals — this change is body-only).
- Lenses outside the engineering flow (regret-minimization, effectuation, archetypes,
  leverage-points, feedback-loops, lindy, fermi, probabilistic, opportunity-cost,
  thought-experiment, model-router/selection/combination) stay out.
- Lenses already covered are not duplicated: reversibility, pre-mortem, occam, kepner-tregoe,
  five-whys-plus, red-team/inversion, JTBD (config hook), socratic (= clarify), dual-process
  (= verify).

## Functional requirements

- **FR-001** — `design` Step 2 lens list gains steel-manning (state the runner-up's strongest
  case before recommending), second-order ("and then what?" across scale / teams / ops),
  via-negativa (does the problem go away by removing something?), TRIZ (separate conflicting
  requirements in time / space / condition / level instead of compromising), margin-of-safety
  (when the design sets a timeout, limit or capacity).
- **FR-002** — `structured-debug` step 3 lens list gains map-territory (behaviour contradicts a
  doc, test or comment → read and run the real code path before theorizing; the territory wins),
  OODA (incident under time pressure → propose a reversible stabilizing move for the go-ahead,
  then root cause), systems (a fix in one place breaks another, or no single component is at
  fault → map the components, feedback loops and delays).
- **FR-003** — `feature` "Scale ceremony" gains a Cynefin classifier: scale ceremony by the
  cause→effect relationship as well as size — clear → runbook; complicated → analyse and
  design; complex → spike / probe first; chaotic → stabilize first.
- **FR-004** — `clarify` Step 1 gains first-principles: a constraint stated as fixed is
  checked — physics / cost / regulation, or convention?
- **FR-005** — `implement` "When to stop and reconsider" gains sunk-cost (the same approach
  failed twice → stop and re-plan; would you choose this path starting fresh?) and
  bounded-rationality (an open-ended search gets a stated "good enough" and stops at the
  first option that clears it; never for correctness gates).
- **FR-006** — `review` gains steel-manning for pushback: when the user or a reviewer disputes
  a finding, state the strongest case for their position before conceding or holding.
- **FR-007** — `knowledge-base` Recall: an empty recall is reported as empty (or fetched) —
  never filled with a plausible-sounding answer.
- **FR-008** — Attribution lands in the repo: `shipgate/NOTICE` (travels with the installed
  plugin) and a credit line in `shipgate/README.md`; the README integrations row for
  `thinking-skills` says what the inline lenses now cover.
- **FR-009** — Eval cases for the two lenses most likely to change behaviour: design
  steel-manning and debug map-territory; both run on the harness with ablation.
- **FR-010** — Version bump (plugin.json + marketplace.json in lockstep) and a CHANGELOG entry
  that reports the per-skill body size delta.

## Success criteria

- **SC-001** — `git diff` of every `skills/*/SKILL.md` shows no change to the frontmatter
  (`---` block), only to the body.
- **SC-002** — Each added lens is two to five lines as a bullet, or one short paragraph (Cynefin),
  and names when it applies.
- **SC-003** — The two new eval cases run on the harness (3 runs, with/without); the with arm
  scores at or above the without arm on each, and `evals/baseline.json` records them.
- **SC-004** — No private project name, path or tracker id in the diff (`CLAUDE.md` rule).
- **SC-005** — `shipgate/NOTICE` exists and names the source, licence and copyright.

## Assumptions (executive)

- via-negativa and first-principles already appear as *architect* philosophies
  (`agents/code-architect.md`). The design coordinator still gets a one-line via-negativa
  check because the coordinator, not the architect, commits to the recommendation across all
  three blueprints; first-principles moves to clarify as the brief proposes (constraints are
  a clarify concern). Rationale: no duplication at the same level, no gap at the other.
- OODA lives in the structured-debug lens list with an explicit "incident under time pressure"
  condition rather than as a new top-level step — the lens list is the established style.
- The Cynefin lens is a paragraph in the orchestrator's "Scale ceremony" section, not a new
  phase: it informs how much ceremony, which is what that section already decides.
- Attribution: `shipgate/NOTICE` rather than a repo-root `NOTICE`, because the plugin is the
  deliverable that carries the adapted text; the root `LICENSE` stays as-is.
- Two eval cases (design steel-manning, debug map-territory), numbered 68 and 69; a
  knowledge-base "empty recall" case is a follow-up, not in scope.
- Version: `0.14.0` — new default behaviour in every phase skill is a minor bump, not a
  patch. The bump and how it lands (PR vs direct merge) are escalated at publish per the
  config's Autonomy section.
- No ADR: the mapping is given by the brief and the trims above are recorded here and in the
  CHANGELOG; there is no either/or a future reader would need to re-derive.
