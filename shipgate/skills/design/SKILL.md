---
name: design
description: Turn a clarified PRD into a committed design and a build plan. Runs code-architect subagents in parallel to compare approaches, recommends one, lets the user pick, records genuine decision forks as ADRs, and writes the working doc (Design + Build Plan sections). Use after the Clarify gate passes and before implementation.
---

# Design

Design is where you decide *how*, with real alternatives, before committing the team's time
to building. The output is two things: a **design** the implementer can follow, and a
**build plan** they can execute task by task. Both live in one working doc.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## Step 1 — Explore design options in parallel

First, **recall prior decisions** (`knowledge-base`): skim the configured ADR home (default the
repo's `docs/adr/`) for forks already settled in this area, so you extend past decisions rather
than re-litigate them. Give the architects any relevant ADR as context. Subagents don't read the
project config themselves, so each dispatch brief must include the relevant config excerpts —
the knowledge-base recall pointers and any store/page conventions they'd otherwise miss.

Then dispatch **`code-architect` subagents scaled to how open the solution space is**. When
the design has a genuine fork, run the full fan of three at once, one per philosophy:
`minimal-change`, `clean-architecture`, `pragmatic-balance` — committed, distinct
philosophies are what surface the real trade-off; a single "balanced" design hides the
choice you're actually making. When constraints leave essentially one viable approach, one
architect (or designing inline) suffices — don't fan out to manufacture alternatives that
don't exist. Give each the PRD, the impact map from `route-and-map`, the essential files
surfaced during exploration, and any relevant prior ADRs.

## Step 2 — Synthesize and recommend

Read all three blueprints. Then **read the key files they cite yourself** — don't design off
their summaries alone; the coordinator reading the actual code is what keeps the design
honest. Present to the user:

- A short summary of each approach and its core trade-off.
- The concrete differences that matter (files touched, new abstractions, risk).
- **Your recommendation, with reasoning** grounded in this codebase and the impact map.
- Then ask which they want. Make a real recommendation — "here are three options, you
  decide" wastes the analysis you just did.

**Executive mode** (config Autonomy: `executive`): don't ask — **commit to your
recommendation and record it** (the ADR in Step 3 is the record; note it was an executive
decision). Escalate to the user only when the reversibility lens says one-way door, when
the choice changes user-visible scope, or when you genuinely can't rank the approaches.
Present the committed choice and its rationale in the phase summary so the user can veto.

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
an ADR at the configured ADR home (default `docs/adr/NNNN-<title>.md`, following any page
conventions the project config declares) using `references/adr-template.md`. Number
sequentially.
ADRs are immutable once accepted — to change a decision, write a new ADR that supersedes the
old one. The ADR *is* the record; only if the decision carries product-significant weight, note
it in the knowledge base (via `knowledge-base`) with a link back to the ADR.

Carry the `Issue:` reference from the PRD header into every ADR and the worklog — each
artifact should stand alone so a reader (or `grep #ID`) finds the whole trail without hopping.

## Step 4 — Write the working doc

Create the working doc at the configured worklog home (default
`docs/prd/<feature-kebab>.worklog.md`, next to its PRD, following any page conventions the
project config declares) from `references/worklog-template.md`. It has two sections with
different lifecycles:

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

## Record the commit (journaled projects)

On a project whose config declares a **Journal**, append `design-committed` as the working doc
lands — artifacts by path, so a later session knows exactly what to open:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream feature/<slug> --type design-committed \
  --data '{"issue":"<issue-id>","worklog":"docs/prd/<slug>.worklog.md",
           "adrs":["docs/adr/0007-async-export.md"]}'
```

Designing ahead in epic mode uses the epic stream: `design-queued` {issue, assumes} on
`epic/<slug>` when a design is parked for a later child, and `design-invalidated` {issue, reason}
at the round boundary where a merge breaks what it assumed — each when it happens, never batched.
Carry `issue` on all three: `status` drains a queued design by matching that key, so a
`design-committed` without it leaves the design listed as queued forever.
A missing or unreadable database is an infrastructure failure, not a reason to skip the append:
surface it loudly and continue in legacy mode only with the user's acknowledgement.

## Guardrails

- **Honor the impact map and CLAUDE.md.** The design must respect where code belongs and
  whatever obligations the impact map flagged. Call out explicitly any task that
  touches a shared write path, a migration, or a public API — those carry breaking-change
  obligations the implementer must handle deliberately.
- **Don't gold-plate.** Design for the PRD, not for an imagined future. The minimal-change
  architect exists to keep the others honest.
- **Stop after the plan.** Hand off to `implement`; don't start coding here.
