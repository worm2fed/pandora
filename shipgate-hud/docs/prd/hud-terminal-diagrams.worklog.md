---
type: worklog
title: "Worklog: Design tab diagrams drawn in the terminal"
created: 2026-10-15
updated: 2026-10-15
tags:
  - worklog
  - shipgate-hud
status: reviewed
prd: "./hud-terminal-diagrams.md"
related:
  - "../adr/0003-terminal-diagrams-as-a-box-drawing-grid.md"
---

# Worklog: Design tab diagrams drawn in the terminal

> Design + build plan companion to `./hud-terminal-diagrams.md`.

---

# Design

## Approach

Minimal change. One new pure function, `flowchartGrid`, beside `flowchartText` in
`hooks/diagram.ts`. It reuses `layoutFlowchart`'s layers. `diagramOf` in `hooks/views.tsx`
draws its rows in the terminal and keeps `flowchartText` as the fallback. The trade-off: the
grid router is the largest pure module in the plugin, in exchange for no new element, no
process and no change on desktop.

## Architecture

- `hooks/diagram.ts` — `flowchartGrid(chart, direction?)` → `{ rows: string[]; backEdges: FlowEdge[]; width: number } | null`.
  `null` when the chart has more than 60 nodes. `direction` overrides the chart's, for the
  TD retry. Internals: a cell grid (`string[][]`, one code point per cell), a connectivity
  mask per line cell (N, S, E, W bits plus the style) resolved to a glyph at the end, so
  crossings and junctions compose.
- `hooks/views.tsx` — `diagramOf` in the terminal: grid in the chart's direction; if
  `width > columns` and the direction is horizontal, grid in `TD`; if that is still wider, or
  the grid is `null`, the old `flowchartText` under a dim note. Rows are `<Box key><Text
  wrap="truncate-end">` as today. Back edges follow the picture, one line each, in the
  `flowchartText` edge form.

## Grid layout (LR; TD is the transpose, RL / BT the mirror)

- A node box is 3 rows high and `label + 4` cells wide: `┌─────┐` / `│ label │` / `└─────┘`.
  Corners by shape: rect `┌ ┐ └ ┘`; round and circle `╭ ╮ ╰ ╯`; diamond `╱ ╲ ╲ ╱`
  (top-left `╱`, top-right `╲`, bottom-left `╲`, bottom-right `╱`).
- Layers are columns left to right. Within a layer, boxes stack top to bottom with one blank
  row between, in the layer's order, and the layer is centred on the cross axis as the SVG
  layout is.
- Long edges (target more than one layer ahead) get a pass-through slot in each layer in
  between: a 1-row slot appended under that layer's boxes, with a blank row before it. The
  edge runs straight through the slot as a line.
- A gap between two layers holds, left to right: a 1-cell stub, the channel columns, the
  label run, the arrowhead cell. Each source node with an edge in the gap owns one channel
  column (its edges share it), ordered by the source's row. The label run is as wide as the
  gap's longest label plus 2, or 1 when the gap has no labels. An edge on one row from stub
  to head draws straight.
- An edge draws: stub `─` from the source's right wall at its middle row; vertical run in its
  channel column from the source row to the target row; horizontal run to the head cell;
  the label centred on the horizontal run after the channel; the head `►` in the cell before
  the target's left wall (`◄` for RL, `▼` for TD, `▲` for BT). An open edge draws a line cell
  instead of the head.
- Glyphs from the mask: `─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼`. Dotted straight cells `┄` / `┆`; thick
  `═` / `║` with corners `╔ ╗ ╚ ╝`. A cell where styles mix takes the solid glyph.
- A line cell never lands on a box or a label cell; the gap sizing guarantees it.
- The old `cutLabel` (24 cells) applies to node and edge labels.

Pinned example, `flowchart LR\n a --> b\n a --> c` (exact rows are the test's oracle):

```
         ┌───┐
      ┌─►│ b │
┌───┐ │  └───┘
│ a │─┤
└───┘ │  ┌───┐
      └─►│ c │
         └───┘
```

and `flowchart LR\n api --> queue -->|push| store`:

```
┌─────┐   ┌───────┐          ┌───────┐
│ api │──►│ queue │───push──►│ store │
└─────┘   └───────┘          └───────┘
```

## Data flow

worklog section → `splitFences` → `parseFlowchart` → `layoutFlowchart` (layers) →
`flowchartGrid` (rows) → `diagramOf` (Text rows, fallback chain) → pane.

## Reference implementation

`hooks/diagram.ts` `flowchartSvg` / `flowchartText`: pure, typed exports with a doc comment
that states the drawing in one sentence; `tests/diagram.test.ts` pins exact strings.

## CLAUDE.md / impact-map compliance

- Public repo: no private names in fixtures or docs.
- No file under `hooks/*.json` changes; no change under `shipgate/`.
- Version bump in `shipgate-hud/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` together.

---

# Build Plan

## Feature
- [x] T001 — grid tests first — file(s): `shipgate-hud/tests/diagram.test.ts` — done when: tests exist for the two pinned examples, each direction, each edge style, each shape, a multi-layer edge, a crossing, a back edge, an edge label, the 60-node `null`, and they fail against the stub
- [x] T002 — `flowchartGrid` — file(s): `shipgate-hud/hooks/diagram.ts` — done when: T001 passes and the existing diagram tests still pass
- [x] T003 — terminal `diagramOf` draws the grid with the fallback chain — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx` — done when: the terminal test asserts box rows (`│ label │`) and heads, a narrow-pane test asserts the TD retry, a too-wide test asserts the text form under the note, the big-chain test still passes

## Polish
- [x] T004 — docs and version — file(s): `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`, `shipgate-hud/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: 0.5.0 in both manifests, changelog entry first, README diagram paragraph and file table updated
- [x] T005 — verify — done when: `claude plugin validate shipgate-hud` and `claude plugin test shipgate-hud` pass in one fresh run

## Review round 1 fixes
- [x] T006 — size and edge caps in `flowchartGrid`, a tagged skip result, `GRID_NODE_LIMIT` exported — file(s): `shipgate-hud/hooks/diagram.ts`, `shipgate-hud/tests/diagram.test.ts` — done when: a chart with over 200 forward legs or a projected grid over 40,000 cells returns a skip before any cell array is allocated; the skip says why; tests pin both
- [x] T007 — `terminalDiagram` fallback chain: retry TD after a throw too, treat a grid as fitting only when its width fits the real room (no 40-cell floor on the fit) and its height is at most 200 rows, build the note from the skip reason — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx` — done when: tests pin the throw→TD retry, the height gate, and a 38-column room
- [x] T008 — control characters stripped from node and edge labels in `cleanLabel` — file(s): `shipgate-hud/hooks/diagram.ts`, `shipgate-hud/tests/diagram.test.ts` — done when: a label with `\u001b[2J` draws without it
- [x] T009 — docs: `flowchartGrid` doc comment names the throw; `diagramOf` doc comment names the text form for an oversized SVG; ADR 0002 status `accepted (terminal form amended by 0003)`; PRD FR-009 says the note names the reason — file(s): `shipgate-hud/hooks/diagram.ts`, `shipgate-hud/hooks/views.tsx`, `shipgate-hud/docs/adr/0002-diagrams-drawn-by-the-hud.md`, `shipgate-hud/docs/prd/hud-terminal-diagrams.md`

## Traceability
- FR-001..FR-008, FR-010 → T001, T002
- FR-009, FR-011 → T003
- SC-001 → T003
- SC-002, SC-003 → T005
- SC-004 → T004

## Deviations & notes (filled during implementation)
- 2026-10-15 — T002: a gap's label run is the longest label + 4, not + 2; the pinned example 2 forces a 10-cell gap for `push`. Impact: none, the pinned rows are the oracle.
- 2026-10-15 — T002: a source owns a channel column only when one of its edges changes row; a straight edge draws stub-line-head in 3 cells. Impact: narrower gaps.
- 2026-10-15 — T002: channel order is by source row, except that a source whose line ends at its channel goes before a source whose edge ends on that row (else `a-->b, a-->c, d-->b` read as d→c). A two-way swap still draws an ambiguous junction.
- 2026-10-15 — T002: in TD/BT every labelled target gets its own row in the run; labels are written horizontally and the grid widens to fit them. A wide label can overwrite one cell of another vertical line on its row.
- 2026-10-15 — T002: boxes are left-aligned in an LR layer; a box's centre is `floor((w-1)/2)` so a TD chain of mixed widths stays straight. A jog of one cell remains between boxes of different parity.
- 2026-10-15 — T002: each long edge gets its own slot row per layer it passes; labels that meet at one target join with ` / ` and are cut to 24 cells; a long edge's label sits on its last leg; thick junctions use `╠ ╣ ╦ ╩ ╬`.
- 2026-10-15 — T002: `flowchartGrid` throws when a box or label would land on a line or another box; `terminalDiagram` catches it and draws the text form under `diagram could not be drawn as a picture`.
- 2026-10-15 — T003: the width note's N is the narrower of the two pictures tried; M is `max(40, columns)`.
- 2026-10-15 — T003: `edgeLine(chart, e)` is a new export; `flowchartText` uses it, so the back-edge lines under a picture match the text form.
- Not covered by a test: an RL picture with a label; BT with a bend.
- 2026-10-15 — T006/T007: limits chosen: 60 nodes, 200 forward legs (an edge counts once per layer it spans), 40,000 cells (width × height, checked before any cell array is made), 200 rows (checked by the pane). A 25-node chart with an edge from each node to every later one has 2,600 legs; a TD fan of 59 labelled edges is 1,592 × 70 cells. Identical edges are drawn once. T008 also removes a whole CSI escape sequence, so `\u001b[2J` leaves no `[2J`.

## Review round 1 (2026-10-15, workflow run wf_8bfc93d9-5fd)

Three lenses, 25 found, 21 after dedupe, 13 candidates, 13 survivors, 0 killed. Two refuters
on the HIGH; both held it. Security review (built-in): no findings. Verdict: **not ready**.

Must fix (→ T006–T009):
- `hooks/diagram.ts:457` HIGH 85, held 0/2 — nodes are capped at 60 but edges, legs and the grid size are not; a dense chart allocates four width × height arrays and stalls the render.
- `hooks/views.tsx:419` MEDIUM 60 — no height bound; a TD retry trades width for height and the tree bound can be hit.
- `hooks/views.tsx:427` MEDIUM 85 and `:426` LOW 85 — the limit 60 is repeated in the caller and the null is overloaded (limit vs. throw).
- `hooks/diagram.ts:462` MEDIUM 60 — control characters in labels reach `Text`; `review.ts` strips them, the diagram path does not.
- `hooks/views.tsx:418` LOW 85 — a throw in the LR grid skips the TD retry.
- `hooks/views.tsx:379` LOW 70 — the fit check floors the room at 40 while the section is indented by 2; a 38-cell room passes a 40-cell grid.
- `hooks/diagram.ts:447` LOW 75, `hooks/views.tsx:361` LOW 65 — two doc comments disagree with the code (the throw; the oversized SVG form).
- `docs/adr/0002:9` LOW 70 — the status field does not carry the amendment, so the Design tab does not show it.

## Review round 2 (2026-10-15, fix diff, orchestrator pass)

Scope: the fix diff of T006–T009 (two hook files, two test files, docs). One pass by the
orchestrator, all lenses, since the fix diff is two code files.

Each round-1 finding, checked on the code:
- edge/size cap — closed: `hooks/diagram.ts` returns `{skip:'legs'}` once `forward` is built and `{skip:'size'}` before any cell array; identical edges are drawn once; tests pin 2,600 legs, a 1,592 × 70 size skip, and a duplicate edge.
- height bound — closed: `terminalDiagram` fits a grid only at `rows.length <= GRID_ROW_LIMIT`; a 46-node LR chain draws the text form under `diagram is 274 rows tall; the pane draws up to 200`.
- TD retry after a throw — closed: the retry runs whenever the first attempt does not fit, except a `nodes` skip. No test: 600,000 fuzzed charts never made the grid throw, so the `failed` path has no deterministic trigger.
- limit duplicated — closed: four exported constants, every note built from them.
- control characters — closed: `cleanLabel` strips a whole CSI sequence and then the C0/DEL/C1 class; `a["x\u001b[2Jy"]` draws `xy`.
- width floor — closed: the room is `max(1, columns)`; a 39-wide grid at 40 body columns draws the text form, at 41 the picture. A mutation (the old floor put back) failed the test.
- doc comments, ADR 0002 status, PRD FR-009 — closed.

What the fixes changed beyond the findings: duplicate back edges are listed once under a
picture while the text form lists each (accepted); `cleanLabel` strips more than the review
module's class, so an escape sequence leaves no `[2J` behind (accepted).

Verify: `claude plugin validate shipgate-hud` passed; `claude plugin test shipgate-hud` 328
pass, 0 fail across 6 files; `tsc -p shipgate-hud --noEmit` no errors. Verdict: **ready**.

## Rejected findings
- `hooks/diagram.ts:463` LOW 80, wide glyphs (emoji, CJK) misalign boxes — deferred, not fixed here: the text form and the SVG measure code points the same way today, and a width table is its own change. Ledger entry.
- `hooks/diagram.ts:216` LOW 75, recursive DFS overflows at 8,000 nodes — pre-existing, outside this change; a worklog never holds such a chart. Ledger entry.
- `hooks/diagram.ts:456` alsoReported, `flowchartGrid` takes no `layout` parameter — the grid lays out its own cells; the SVG layout's pixels are of no use to it.
- below floor: bare `catch` in `gridIn` (the throw is the grid's own invariant; T006 narrows the null), `edgeLine` linear find (a chart has at most 60 nodes), STE-80 nits in README (left as written), T005 unticked (verify is the last task by design).
