---
name: design
description: Turn a clarified PRD into a committed design and a build plan. Runs code-architect subagents in parallel to compare approaches, recommends one, lets the user pick, records genuine decision forks as ADRs, and writes the worklog (Design + Build Plan sections). Use after the Clarify gate passes and before implementation.
---

# Design

Design is where you decide *how*, with real alternatives, before committing the team's time
to building. The output is two things: a **design** the implementer can follow, and a
**build plan** they can execute task by task. Both live in one worklog.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** A status brief headed "shipgate
> flow journal", a **Journal** section in the config or a `.claude/shipgate.json` sidecar means
> the design is owed to a stream, and the stream is the branch this PRD's work takes: the stream
> the status brief lists for the PRD's `Issue:` (it exists from clarify in the normal flow), otherwise
> the name the config's **Branching** pattern gives the issue — whether or not that branch is
> checked out, or exists yet. No stream of that name? Open it with `flow-started {request,
> branch}` in the same append. The event owed here is `design-committed`, appended as the
> worklog is written (Step 4), in that turn, whether or not a fork is still awaiting the
> user. The Stop hook does not check it, so Step 4 is the only thing that writes it.

## Step 1 — Explore design options in parallel

First, **recall prior decisions** (`knowledge-base`): skim the configured ADR home (default the
repo's `docs/adr/`) for forks already settled in this area, so you extend past decisions rather
than re-litigate them. Give the architects any relevant ADR as context. Subagents don't read the
project config themselves, so each brief must include the relevant config excerpts —
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
their summaries alone; the orchestrator reading the actual code is what keeps the design
honest. Present to the user:

- A short summary of each approach and its core trade-off.
- The concrete differences that matter (files touched, new abstractions, risk).
- **Your recommendation, with reasoning** grounded in this codebase and the impact map.
  When several existing precedents could serve as the reference implementation, compare
  them with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <candidate-files> --json`
  and prefer the proven one — lower `fix_rate`, higher `age_days`, higher `fan_in` — stating
  that in the worklog's **Reference implementation** rationale (signals unavailable — see
  the JSON's `reason`, `trajectory.reason`, `structure.reason` — means choosing on reading
  alone, and saying so).
- Then ask which they want. Make a real recommendation — "here are three options, you
  decide" wastes the analysis you just did.

**Executive mode** (config Autonomy: `executive`): don't ask — **commit to your
recommendation and record it** (the ADR in Step 3 is the record; note it was an executive
decision). Escalate to the user only when the reversibility lens says one-way door, when
the choice changes user-visible scope, or when you genuinely can't rank the approaches.
Present the committed choice and its rationale in the phase summary so the user can veto.

Before you commit to the recommendation, run a few quick lenses on the leading approach
(invoke the lens skills the config's **Thinking lenses** section maps to Design, if any;
otherwise just apply the idea). Reversibility and pre-mortem always; the rest when their
condition holds:
- **reversibility** — is this a one-way door (schema migration, public API, shared write path)
  or easily undone? One-way doors deserve more deliberation *and* an ADR; reversible choices
  can move fast. This directly informs what you record in Step 3.
- **pre-mortem** — "assume this design shipped and caused an incident — why?" Surface the top
  failure mode now, while changing the design is free, and fold the mitigation into the plan.
- **steel-manning** — when the runner-up is close, or is the user's own preference: state its
  strongest case (the real concern it answers, as its best advocate would put it) and answer
  *that*. A choice that only beats the weak version is not yet a decision; agreement by reflex
  is the failure mode. Skip when the choice is trivial or cheaply reversible.
- **second-order** — when the change has downstream coupling (not a two-way door): "and then
  what?" at three horizons — the next request, the next deploy (what the team does because of
  this), 10× scale or adoption. Stop at the first effect that changes the decision; don't
  invent cascades.
- **via-negativa** — does the problem go away by removing or not adding something (a layer, a
  flag, a dependency)? Ask it of every blueprint, not only the minimal-change one; never
  remove a load-bearing guard, test or validation to get there.
- **TRIZ** — when two requirements seem mutually exclusive ("stable AND evolving", "fresh AND
  cached"), don't take the midpoint: separate them in time, space, condition or level
  (versioned contract over an evolving implementation; TTL; strict only for sensitive ops).
  If one option is plainly better, or a standard pattern already resolves it, just pick it; if
  a cheap measurement would settle which side matters, measure instead.
- **margin-of-safety** — when the design sets a timeout, limit, pool size or capacity: size
  the buffer to the cost of being wrong, not to the point estimate. Measure before padding,
  and skip the buffer where the value adjusts live at no cost.

## Step 3 — Record decision forks as ADRs

For each genuine either/or the team will want to remember *why* it went one way (not every
detail — real forks: a data model, a sync vs async boundary, a build-vs-reuse call), write
an ADR at the configured ADR home (default `docs/adr/NNNN-<title>.md`, following any page
conventions the project config declares) using `${CLAUDE_PLUGIN_ROOT}/skills/design/references/adr-template.md`. Number
sequentially.
ADRs are immutable once accepted — to change a decision, write a new ADR that supersedes the
old one. The ADR *is* the record; only if the decision carries product-significant weight, note
it in the knowledge base (via `knowledge-base`) with a link back to the ADR.

Carry the `Issue:` reference from the PRD header into every ADR and the worklog — each
artifact should stand alone so a reader (or `grep #ID`) finds the whole trail without hopping.

## Step 4 — Write the worklog

Create the worklog at the configured worklog home (default
`docs/prd/<feature-kebab>.worklog.md`, next to its PRD, following any page conventions the
project config declares) from `${CLAUDE_PLUGIN_ROOT}/skills/design/references/worklog-template.md`. It has two sections with
different lifecycles:

- **Design** — the *how*: architecture, components, data flow, API/contract changes, data
  model. This is stable once agreed; treat edits as deliberate. Fill the template's
  **Reference implementation** section: new code should mirror the vetted reference
  implementation the design names — the nearest sibling is not automatically a pattern
  source (scaffolds and stubs encode garbage), and a previous slice's output is a source
  only for the surfaces that were actually reviewed; template drift compounds slice over
  slice. When the work **ports or migrates existing behavior**, also fill
  **Pre-authorized deltas (ports/migrations only)** — every intentional
  divergence from the source-of-truth artifact, declared up front; the review phase's
  parity gate consumes this list, and anything not on it counts as an unauthorized
  behavioral difference.
- **Build Plan** — ordered tasks, **with tests as tasks** (never a separate doc). Mark a task
  `[P]` when it's independent of its siblings and could be done in parallel. Each task names
  the file(s) it touches and what "done" means. This section is *living* — implementation
  ticks the boxes and logs deviations here. When a slice **introduces new domain shapes**
  (entities, value objects, error unions, command/handler signatures), plan a
  **declarations task** ahead of that slice's body tasks: types and signatures only, bodies
  throwing `unimplemented`, "done" = a test-inclusive type-check passing plus a review of
  the declarations alone (see `implement` — Types round). Scope it to the slice, never the
  whole feature — a feature-wide types round is big design up front wearing a functional
  hat — and keep it after exploration: some shapes only exist once the wire and DB reality
  are known.

Order the build plan so dependencies are respected: setup/shared foundations first, then the
feature slices, then polish. Verify every PRD requirement (FR-###) and success criterion
(SC-###) maps to at least one task — a requirement with no task is a requirement you'll
forget to build.

**Journaled: append `design-committed` as the worklog lands** (the form is under **Record
the commit**). It records that the design and build plan exist at a path, not that every fork
is closed: an escalated one-way door stays `proposed` in its ADR and is named in the event's
`open` list, and the user's answer lands later as `gate-decision {gate: design, raised_by:
user}` (a `deviation` if they veto the design). Holding the event back until the answer leaves
the status brief at the previous phase with a worklog on disk — the stuck flow the journal exists to
prevent.

## Record the commit (journaled projects)

Step 4's append — `design-committed` as the worklog lands, artifacts by path, so a later
session knows exactly what to open:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type design-committed \
  --data '{"issue":"<issue-id>","worklog":"docs/prd/<slug>.worklog.md",
           "adrs":["docs/adr/0007-async-export.md"],"open":["docs/adr/0008-schema-change.md"]}'
```

`open` lists the ADRs still awaiting the user's answer (omit it when there are none); the
design is committed from your side the moment the worklog exists. A stream the status brief does not
list is opened in the same `--batch` (a `flow-started` line first — stdin form: see `verify`).

Designing ahead in epic mode uses the epic stream: `design-queued` {issue, assumes} on
`epic/<slug>` when a design is parked for a later child, and `design-invalidated` {issue, reason}
at the round boundary where a merge breaks what it assumed — each when it happens, never batched.
Carry `issue` on all three: `status` drains a queued design by matching that key, so a
`design-committed` without it leaves the design listed as queued forever.
A missing or unreadable database is an infrastructure failure, not a reason to skip the append:
surface it loudly and continue un-journaled only with the user's acknowledgement.

## Guardrails

- **Honor the impact map and CLAUDE.md.** The design must respect where code belongs and
  whatever obligations the impact map flagged. Call out explicitly any task that
  touches a shared write path, a migration, or a public API — those carry breaking-change
  obligations the implementer must handle deliberately.
- **Don't gold-plate.** Design for the PRD, not for an imagined future. The minimal-change
  architect exists to keep the others honest.
- **Stop after the plan.** Hand off to `implement`; don't start coding here.
