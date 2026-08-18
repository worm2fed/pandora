---
name: bpmn
description: >-
  Create, edit, or render BPMN 2.0 diagrams. Use when the user wants a process
  diagram, workflow diagram, swimlane/pool diagram, service-interaction diagram,
  or a .bpmn file — for business processes, cross-service flows, or
  organizational workflows (e.g. "diagram our dev workflow", "model the order
  lifecycle", "BPMN for how the frontend talks to a backend service"). Also use to
  modify or re-render an existing .bpmn file.
---

# BPMN diagrams

Produce presentation-ready BPMN 2.0 diagrams from a plain-language narrative.
The division of labor is strict and is what makes this work: **you write only
the semantic XML** (elements, flows — what you're good at); **bundled tooling
does layout, validation, and rendering** (what hand-written coordinates ruin).
Never write `<bpmndi:...>` sections by hand. Never guess coordinates.

Bundled tooling lives at `<skill_base>/scripts/` (referred to as `$S` below):

| Command                                   | Does                                                        |
| ----------------------------------------- | ----------------------------------------------------------- |
| `node $S/layout.mjs <f>.bpmn`             | generates all diagram coordinates (pools, lanes, edges)     |
| `node $S/validate.mjs <f>.bpmn`           | schema check + bpmnlint best-practice rules                 |
| `node $S/render.mjs <f>.bpmn`             | self-contained HTML preview (pan/zoom, SVG/.bpmn download)  |

**First run only**: if `<skill_base>/scripts/node_modules` is missing, run
`npm install --prefix <skill_base>/scripts` (needs Node ≥ 18).

Work in the scratchpad directory unless the user names a location. Name the
file after the process in kebab-case: `order-fulfillment.bpmn`.

## Phase 1 — Capture the narrative

Extract from the user's description (or the doc/code they point at):

- **Actors** → lanes or pools (see the structure decision below)
- **Trigger** → start event ("what kicks this off?")
- **Happy-path steps** → tasks, in order, one level of abstraction
- **Decisions as if/then** → gateways with labeled outcomes
- **Handoffs between systems** → message flows
- **Failures, timeouts, cancellations** → boundary events
- **End states** → one end event per distinct outcome

Ask targeted `AskUserQuestion`s **only for real gaps** — an unowned decision, an
unhandled failure path, an ambiguous actor. If the narrative is complete, don't
interrogate; state your structural assumptions in one line and build. The most
important question when actors are involved: *roles within one organization
(lanes) or independent systems exchanging messages (pools)?* — see
`references/modeling-rules.md` for the litmus test.

## Phase 2 — Model the semantics

Read **both** reference files before writing XML the first time in a session:

- `references/element-patterns.md` — copy-paste XML patterns, ID conventions,
  the bpmn.io-compatible element subset
- `references/modeling-rules.md` — naming rules, split/join discipline,
  lanes-vs-pools, scope control, process suites

**Decompose before modeling**: if the narrative implies more than ~20 flow
nodes, split it into a suite of files at phase/cadence boundaries (see
"Process suites" in modeling-rules.md) instead of drawing one long diagram.
Handoffs between files: message end event → message start event with mirrored
names. Never link events across files.

Write the `.bpmn` file(s): semantic elements only, stable human-readable IDs
(`Task_ReviewOrder`, `Gateway_IsApproved`), every node with complete
`incoming`/`outgoing` lists.

## Phase 3 — Layout and validate

```bash
node $S/layout.mjs <file>.bpmn && node $S/validate.mjs <file>.bpmn
```

Fix every finding (errors always; warnings unless the user explicitly waves one
off — e.g. `fake-join` means a missing join gateway, a real modeling defect).
Re-run until clean. Layout is idempotent — it regenerates all coordinates from
semantics on every run.

## Phase 4 — Preview and iterate

```bash
node $S/render.mjs <file>.bpmn                                  # single diagram
node $S/render.mjs <a>.bpmn <b>.bpmn <c>.bpmn -o suite.html     # tabbed suite
```

Send the HTML to the user with `SendUserFile` (display: `render`). Then iterate
in conversation: edit the **semantic** XML (stable IDs make this surgical),
re-run layout → validate → render to the **same paths** so the preview updates.
Don't ask permission per iteration — apply the feedback, re-render, show it.

## Phase 5 — Deliver

When the user is satisfied, ask where the diagram should live (wiki, repo docs,
just the files) — don't assume. Hand over:

- the `.bpmn` file — the source of truth, importable into
  [bpmn.io](https://demo.bpmn.io) / Camunda Modeler for manual polish
- the `.html` preview (self-contained, shareable; has Download SVG / .bpmn
  buttons)

If the user polishes the `.bpmn` manually afterwards, never re-run `layout.mjs`
on it — that discards their layout.

## Editing an existing .bpmn

Read the file, edit semantics only. If it has hand-made or tool-made DI you
should preserve, skip Phase 3's layout step and only validate + render. If the
user asks for a re-layout, warn that existing manual layout will be discarded.
