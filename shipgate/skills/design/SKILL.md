---
name: design
description: Turn a clarified PRD into a committed design and a build plan. Runs code-architect subagents in parallel to compare approaches, recommends one, lets the user pick, records genuine decision forks as ADRs, and writes the worklog (Design + Build Plan sections). Use after the Clarify gate passes and before implementation.
---

# Design

Design is where you decide *how*, with real alternatives, before you commit the team's time
to building. The output is two things. One is a **design** the implementer can follow. The
other is a **build plan** they can execute task by task. Both live in one worklog.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** Three signs mark a journaled
> project: a status brief headed "shipgate flow journal", a **Journal** section in the config,
> or a `.claude/shipgate.json` sidecar. Any one of them means the design is owed to a stream.
> The stream is the branch this PRD's work takes. Use the stream the status brief lists for
> the PRD's `Issue:`. In the normal flow it exists from clarify. Otherwise use the name the
> config's **Branching** pattern gives the issue, whether or not that branch is checked out
> or exists yet. No stream of that name? Open it with `flow-started {request,
> branch}` in the same append. The event owed here is `design-committed`. Append it as the
> worklog is written
> (Step 4), in that turn, whether or not a fork is still awaiting the user. The Stop hook
> does not check it, so Step 4 is the only thing that writes it.

## Step 1 — Explore design options in parallel

First, **recall prior decisions** (`knowledge-base`). Skim the configured ADR home for forks
already settled in this area. The default is the repo's `docs/adr/`. That way you extend past
decisions rather than re-litigate them. Give the architects any relevant ADR as context.
Subagents don't read the project config themselves. So each architect brief must include the
relevant config excerpts: the knowledge base's recall pointers, and any store/page
conventions the architects would otherwise miss.

Then dispatch **`code-architect` subagents scaled to how open the solution space is**. When
the design has a genuine fork, run the full fan of three at once, one per philosophy:
`minimal-change`, `clean-architecture`, `pragmatic-balance`. Committed, distinct
philosophies are what surface the real trade-off. A single "balanced" design hides the
choice you're actually making. When constraints leave essentially one viable approach, one
architect is enough, or you design inline. Don't fan out to manufacture alternatives that
don't exist. Give each architect the PRD, the impact map from `route-and-map`, the essential
files surfaced during exploration, and any relevant prior ADRs.

## Step 2 — Synthesize and recommend

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

Read all three blueprints. Then **read the key files they cite yourself**. Don't design off
their summaries alone. The orchestrator reading the actual code is what keeps the design
honest. Present to the user:

- A short summary of each approach and its core trade-off.
- The concrete differences that matter (files touched, new abstractions, risk).
- **Your recommendation, with reasoning** grounded in this codebase and the impact map.
  Several existing precedents can sometimes serve as the reference implementation. Then
  compare them with
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <candidate-files> --json`.
  Prefer the proven one: lower `fix_rate`, higher `age_days`, higher `fan_in`. State that
  choice in the worklog's **Reference implementation** rationale. The signals can be
  unavailable; the JSON's `reason`, `trajectory.reason` and `structure.reason` say why. Then
  choose on reading alone, and say so.
- Then ask which approach the user wants. Make a real recommendation. "Here are three
  options, you decide" wastes the analysis you just did.

**Executive mode** (config Autonomy: `executive`): don't ask. **Commit to your recommendation
and record it.** The ADR in Step 3 is the record; note that it was an executive decision.
Escalate to the user only in three cases: the reversibility lens says one-way door, the choice
changes user-visible scope, or you genuinely can't rank the approaches. Present the committed
choice and its rationale in the phase summary, so the user can veto it.

Before you commit to the recommendation, run a few quick lenses on the leading approach. If
the config's **Thinking lenses** section maps lens skills to Design, invoke them. Otherwise
just apply the idea. Always run reversibility and pre-mortem. Run the rest when their
condition holds:
- **reversibility** — Is this a one-way door (schema migration, public API, shared write
  path), or is it easily undone? One-way doors deserve more deliberation *and* an ADR.
  Reversible choices can move fast. This lens directly informs what you record in Step 3.
- **pre-mortem** — Ask "assume this design shipped and caused an incident — why?" Surface the
  top failure mode now, while changing the design is free. Fold the mitigation into the plan.
- **steel-manning** — Use it when the runner-up is close, or is the user's own preference.
  State the runner-up's strongest case: the real concern it answers, as its best advocate
  would put it. Then answer *that*. A choice that only beats the weak version is not yet a
  decision. Agreement by reflex is the failure mode. Skip this lens when the choice is
  trivial or cheaply reversible.
- **second-order** — Use it when the change has downstream coupling (not a two-way door). Ask
  "and then what?" at three horizons: the next request, the next deploy (what the team does
  because of this), and 10× scale or adoption. Stop at the first effect that changes the
  decision. Don't invent cascades.
- **via-negativa** — Ask whether the problem goes away if you remove something, or do not add
  it (a layer, a flag, a dependency). Ask it of every blueprint, not only the minimal-change
  one. Never remove a load-bearing guard, test or validation to get there.
- **TRIZ** — Use it when two requirements seem mutually exclusive ("stable AND evolving",
  "fresh AND cached"). Don't take the midpoint. Separate them in time, space, condition or
  level: a versioned contract over an evolving implementation, a TTL, strict only for
  sensitive ops. If one option is plainly better, or a standard pattern already resolves it,
  just pick it. If a cheap measurement would settle which side matters, measure instead.
- **margin-of-safety** — Use it when the design sets a timeout, limit, pool size or capacity.
  Size the buffer to the cost of being wrong, not to the point estimate. Measure before
  padding. Skip the buffer where the value adjusts live at no cost.

## Step 3 — Record decision forks as ADRs

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
each ADR; absent, a placeholder, or `plain`, write it as before.

Write an ADR for each genuine either/or where the team will want to remember *why* it went one
way. Do not write one for every detail. Real forks are things like a data model, a sync vs
async boundary, or a build-vs-reuse call. Write each ADR at the configured ADR home. The
default is `docs/adr/NNNN-<title>.md`. Follow any page conventions the project config
declares. Use `${CLAUDE_PLUGIN_ROOT}/skills/design/references/adr-template.md`. Number the ADRs
sequentially.
ADRs are immutable once accepted. To change a decision, write a new ADR that supersedes the
old one. The ADR *is* the record. Only if the decision carries product-significant weight,
note it in the knowledge base (via `knowledge-base`) with a link back to the ADR.

Carry the `Issue:` reference from the PRD header into every ADR and into the worklog. Each
artifact should stand alone, so a reader (or `grep #ID`) finds the whole trail without
hopping.

## Step 4 — Write the worklog

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
the worklog; absent, a placeholder, or `plain`, write it as before.

Create the worklog at the configured worklog home from
`${CLAUDE_PLUGIN_ROOT}/skills/design/references/worklog-template.md`. The default home is
`docs/prd/<feature-kebab>.worklog.md`, next to its PRD. Follow any page conventions the
project config declares. The worklog has two sections with different lifecycles:

- **Design** — the *how*: architecture, components, data flow, API/contract changes, data
  model. This section is stable once agreed; treat edits as deliberate. Fill the template's
  **Reference implementation** section. New code should mirror the vetted reference
  implementation that the design names. The nearest sibling is not automatically a pattern
  source, because scaffolds and stubs encode garbage. A previous slice's output is a source
  only for the surfaces that were actually reviewed. Template drift compounds slice over
  slice. When the work **ports or migrates existing behavior**, also fill
  **Pre-authorized deltas (ports/migrations only)**. List there every intentional divergence
  from the source-of-truth artifact, declared up front. The review phase's parity gate
  consumes this list. Anything not on it counts as an unauthorized behavioral difference.
- **Build Plan** — ordered tasks, **with tests as tasks** (never a separate doc). Mark a task
  `[P]` when it's independent of its siblings and could be done in parallel. Each task names
  the file(s) it touches and what "done" means. This section is *living*: implementation
  ticks the boxes and logs deviations here. A slice can **introduce new domain shapes**
  (entities, value objects, error unions, command/handler signatures). Then plan a
  **declarations task** ahead of that slice's body tasks. It holds types and signatures only,
  with bodies throwing `unimplemented`. Its "done" is a test-inclusive type-check passing,
  plus a review of the declarations alone (see `implement` — Types round). Scope it to the
  slice, never the whole feature. A feature-wide types round is big design up front wearing a
  functional hat. Keep the declarations task after exploration, because some shapes only
  exist once the wire and DB reality are known.

Order the build plan so dependencies are respected. Put setup/shared foundations first, then
the feature slices, then polish. Verify that every PRD requirement (FR-###) and success
criterion (SC-###) maps to at least one task. A requirement with no task is a requirement
you'll forget to build.

**Journaled: append `design-committed` as the worklog lands.** The form is under **Record the
commit**. The event records that the design and build plan exist at a path. It does not
record that every fork is closed. An escalated one-way door stays `proposed` in its ADR, and
the event's `open` list names it. The user's answer lands later as
`gate-decision {gate: design, raised_by:
user}` (a `deviation` if the user vetoes the design). Do not hold the event back until the
answer. That leaves the status brief at the previous phase with a worklog on disk: the stuck
flow the journal exists to prevent.

## Record the commit (journaled projects)

This is Step 4's append. Append `design-committed` as the worklog lands, with artifacts by
path, so a later session knows exactly what to open:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type design-committed \
  --data '{"issue":"<issue-id>","worklog":"docs/prd/<slug>.worklog.md",
           "adrs":["docs/adr/0007-async-export.md"],"open":["docs/adr/0008-schema-change.md"]}'
```

`open` lists the ADRs still awaiting the user's answer. Omit it when there are none. The
design is committed from your side the moment the worklog exists. If the status brief does not
list the stream, open it in the same `--batch`. Put a `flow-started` line first (for the stdin
form, see `verify`).

Designing ahead in epic mode uses the epic stream. Append `design-queued` {issue, assumes} on
`epic/<slug>` when you park a design for a later child. Append `design-invalidated`
{issue, reason} at the round boundary where a merge breaks what the design assumed. Append
each when it happens, never batched. Carry `issue` on all three events. `status` drains a
queued design by matching that key. So a `design-committed` without it leaves the design
listed as queued forever.
A missing or unreadable database is an infrastructure failure, not a reason to skip the
append. Surface it loudly. Continue un-journaled only with the user's acknowledgement.

## Guardrails

- **Honor the impact map and CLAUDE.md.** The design must respect where code belongs and
  whatever obligations the impact map flagged. Call out explicitly any task that touches a
  shared write path, a migration, or a public API. Those carry breaking-change obligations
  that the implementer must handle deliberately.
- **Don't gold-plate.** Design for the PRD, not for an imagined future. The minimal-change
  architect exists to keep the others honest.
- **Stop after the plan.** Hand off to `implement`; don't start coding here.
