# BPMN modeling rules

How to model well — independent of XML mechanics. Apply these while turning a
narrative into elements, and when reviewing a draft with the user.

## Choosing the structure (first decision, get it right)

| Situation                                                        | Structure                        |
| ---------------------------------------------------------------- | -------------------------------- |
| One actor, or actors don't matter for the story                  | single process, no lanes         |
| Multiple **roles inside one organization** sharing one flow      | one process with **lanes**       |
| Independent **organizations/systems** that only exchange messages | **collaboration** with pools     |
| Services calling each other's APIs / emitting events              | collaboration; pools = services  |

Litmus test: if two actors hand work to each other *within the same transaction
of control*, they're lanes. If they communicate by requests/messages and each
runs its own logic, they're pools. Mixing these up is the most common modeling
error — a frontend and a backend service are pools, not lanes.

## Naming

- **Tasks**: verb + object, active voice — "Review order", "Persist order".
  Never a noun phrase ("Order review") or a state ("Order reviewed").
- **Gateways (splits)**: a question — "Approved?", "Amount > $10k?". Label every
  outgoing flow with the answer ("yes" / "no" / "above" / "below").
- **Events**: a state or occurrence, past tense — "Order received",
  "3 days elapsed", "Merged". Start events name the trigger, end events name
  the outcome.
- **Pools**: the organization/system name. **Lanes**: the role name.
- Distinct end events for distinct outcomes ("Merged" vs "Abandoned") — don't
  funnel success and failure into one "End".

## Flow discipline

- Decisions expressed **as if/then** map 1:1 to exclusive gateways. If the
  narrative says "depending on X", make the condition explicit before modeling.
- **Split/join symmetry**: re-merge branches through a join gateway of the same
  kind as the split. Two flows entering a task = `fake-join` warning — the
  semantics ("wait for both" vs "whichever arrives") are ambiguous.
- One start event per process unless there are genuinely alternative triggers.
- Every path must reach an end event — no dangling tasks.
- Exceptions and timeouts are **boundary events** on the task where they occur,
  not downstream "Did it fail?" gateways. Gateway-checking-for-error is the #2
  modeling smell.
- Loops (rework, retries) go **backwards to the earliest affected step** through
  a join gateway, not by duplicating tasks.

## Scope control

- Target **≤ 20 flow nodes per diagram**. Past that, collapse detail into a
  subprocess or split into a process suite (below).

## Process suites (splitting a long process)

When one process runs past ~20 nodes, split it into **multiple .bpmn files at
phase/cadence boundaries** — where ownership, trigger, or rhythm changes
(e.g. a dev flow might split into Planning / Execution / Activation because
planning is monthly, execution is continuous, activation is time-triggered).

Handoff conventions between files:

- **Mainline + exception handoffs: message end event (sender) → message start
  event (receiver)**, with mirrored names — sender `"Item ready (to Execution)"`,
  receiver `"Item pulled (from Planning)"`. The envelope icon reads as
  "comes from / goes elsewhere", and typed starts avoid the
  `single-blank-start-event` lint rule when a process has several entries.
- **Do NOT use link events across files** — links are intra-process by spec, and
  bpmnlint's `link-event` rule errors on an unpaired link name. Links are for
  page-jump shortcuts *within one diagram* only.
- A time-triggered phase gets a **timer start event** instead of an incoming
  handoff (e.g. a monthly activation window) — this also encodes decoupling
  ("deployment ≠ activation": the upstream process just ends).
- Number the process names for tab ordering: `name="1 · Planning"`, `"2 · …"`.
- Each file still needs ≥1 start and ≥1 end event (lint rules) and goes through
  layout → validate individually; render all files together into one tabbed
  preview: `render.mjs planning.bpmn execution.bpmn activation.bpmn -o suite.html`.
- Model the happy path first, at one consistent level of abstraction; add
  exception paths in a second pass. Don't mix "click the button" granularity
  with "fulfill the order" granularity in one diagram.
- Not every conversation detail becomes an element. If it doesn't change what
  happens next, it's a name or an annotation, not a task.

## Layout-tooling constraints (this skill's pipeline)

- Auto-layout reads `incoming`/`outgoing` on every node — keep them complete.
- Lane order / pool order in the XML controls top-to-bottom placement; reorder
  in the XML, not by editing coordinates.
- Expanded subprocesses combined with lanes/pools may need a manual nudge in
  bpmn.io afterwards; everything else should come out clean.
- Layout is regenerated from scratch on every run — never hand-edit DI
  coordinates; if the user manually polished a diagram in bpmn.io, stop
  re-running `layout.mjs` on that file (it would discard their polish).
