---
name: design
description: Turn a clarified PRD into a committed design and a build plan. Runs code-architect subagents in parallel to compare approaches, recommends one, lets the user pick, records genuine decision forks as ADRs, and writes the working doc (Design + Build Plan sections). Use after the Clarify gate passes and before implementation.
---

# Design

Design is where you decide *how*, with real alternatives, before committing the team's time
to building. The output is two things: a **design** the implementer can follow, and a
**build plan** they can execute task by task. Both live in one working doc.

## Step 1 — Explore design options in parallel

First, **recall prior decisions** (`knowledge-base`): skim the repo's `docs/adr/` for forks
already settled in this area, so you extend past decisions rather than re-litigate them. Give
the architects any relevant ADR as context.

Then dispatch **three `code-architect` subagents at once**, one per philosophy:
`minimal-change`, `clean-architecture`, `pragmatic-balance`. Give each the PRD, the impact
map from `route-and-map`, the essential files surfaced during exploration, and any relevant
prior ADRs. Running them in parallel with committed, distinct philosophies is what surfaces
the genuine trade-off — a single "balanced" design hides the choice you're actually making.

## Step 2 — Synthesize and recommend

Read all three blueprints. Then **read the key files they cite yourself** — don't design off
their summaries alone; the coordinator reading the actual code is what keeps the design
honest. Present to the user:

- A short summary of each approach and its core trade-off.
- The concrete differences that matter (files touched, new abstractions, risk).
- **Your recommendation, with reasoning** grounded in this codebase and the impact map.
- Then ask which they want. Make a real recommendation — "here are three options, you
  decide" wastes the analysis you just did.

Before you commit to the recommendation, run two quick lenses on the leading approach (use the
`thinking-skills` plugin if available; otherwise just apply the idea):
- **reversibility** — is this a one-way door (schema migration, public API, shared write path)
  or easily undone? One-way doors deserve more deliberation *and* an ADR; reversible choices
  can move fast. This directly informs what you record in Step 3.
- **pre-mortem** — "assume this design shipped and caused an incident — why?" Surface the top
  failure mode now, while changing the design is free, and fold the mitigation into the plan.

## Step 3 — Record decision forks as ADRs

For each genuine either/or the team will want to remember *why* it went one way (not every
detail — real forks: a data model, a sync vs async boundary, a build-vs-reuse call), write
an ADR at `docs/adr/NNNN-<title>.md` in the target repo (a plain Markdown file) using
`references/adr-template.md`. Number sequentially.
ADRs are immutable once accepted — to change a decision, write a new ADR that supersedes the
old one. The ADR in the repo *is* the record; only if the decision has genuinely general or
project-status significance, also capture it via `knowledge-base` with a link back to the ADR.

Carry the `Issue:` reference from the PRD header into every ADR and the worklog — each
artifact should stand alone so a reader (or `grep #ID`) finds the whole trail without hopping.

## Step 4 — Write the working doc

Create `docs/prd/<feature-kebab>.worklog.md` in the target repo (a plain Markdown file, next
to its PRD) from `references/worklog-template.md`. It has
two sections with different lifecycles:

- **Design** — the *how*: architecture, components, data flow, API/contract changes, data
  model. This is stable once agreed; treat edits as deliberate.
- **Build Plan** — ordered tasks, **with tests as tasks** (never a separate doc). Mark a task
  `[P]` when it's independent of its siblings and could be done in parallel. Each task names
  the file(s) it touches and what "done" means. This section is *living* — implementation
  ticks the boxes and logs deviations here.

Order the build plan so dependencies are respected: setup/shared foundations first, then the
feature slices, then polish. Verify every PRD requirement (FR-###) and success criterion
(SC-###) maps to at least one task — a requirement with no task is a requirement you'll
forget to build.

## Guardrails

- **Honor the impact map and CLAUDE.md.** The design must respect where code belongs and
  whatever obligations the impact map flagged. Call out explicitly any task that
  touches a shared write path, a migration, or a public API — those carry breaking-change
  obligations the implementer must handle deliberately.
- **Don't gold-plate.** Design for the PRD, not for an imagined future. The minimal-change
  architect exists to keep the others honest.
- **Stop after the plan.** Hand off to `implement`; don't start coding here.
