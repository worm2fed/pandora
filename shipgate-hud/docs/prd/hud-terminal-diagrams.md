---
type: prd
title: "PRD: Design tab diagrams drawn in the terminal"
created: 2026-10-15
updated: 2026-10-15
tags:
  - prd
  - shipgate-hud
status: clarified
issue: none / ad-hoc
worklog: "./hud-terminal-diagrams.worklog.md"
related:
  - "./hud.md"
  - "../adr/0002-diagrams-drawn-by-the-hud.md"
  - "../adr/0003-terminal-diagrams-as-a-box-drawing-grid.md"
---

# PRD: Design tab diagrams drawn in the terminal

> The Design tab draws a worklog's flowchart as a two-dimensional box-and-line picture in the
> terminal, not as a list of edges.

## Problem

ADR 0002 gave the HUD its own flowchart layout. Desktop and mobile get an SVG. The terminal
gets a text form: one line per layer, then one line per edge, `[A] ──► [B]`. That form is a
list, not a picture. A reader has to rebuild the graph in their head. The maintainer works in
the terminal CLI, so the picture never reaches the surface where it is read most.

## Goals & non-goals

**Goals**
- A terminal reader sees the data flow as boxes and lines, laid out in two dimensions.
- The picture fits a narrow pane where it can, and degrades in a stated order where it cannot.
- Nothing new runs, loads or leaves the machine. The drawing stays pure TypeScript.

**Non-goals** (explicitly out of scope)
- Pixel pictures in the terminal (the `Image` element). It draws only on kitty and Ghostty
  and shows its `alt` elsewhere, so most terminals would see nothing new.
- Colour in the picture (the `Raster` element). A possible follow-up, not this change.
- Mermaid kinds outside the flowchart subset. They stay `Code`.
- Any change to the SVG form, the desktop behaviour, or the parser.

## Users & stories

- As a maintainer in the terminal, I want the Design tab's data flow drawn as a picture, so
  that I read the design without opening the desktop app.

## Functional requirements

- **FR-001** — In the terminal, a flowchart in the subset draws as a grid of box-drawing
  characters. Each node is a box with its label inside. Each forward edge is a line from the
  source box to the target box with an arrowhead at the target.
- **FR-002** — The direction is honoured. `LR` and `RL` lay the layers left to right (`RL`
  reversed). `TD`, `TB` and `BT` lay them top to bottom (`BT` reversed).
- **FR-003** — Edge styles are distinct. Solid draws `─`/`│`, dotted `┄`/`┆`, thick `═`/`║`.
  An open edge has no arrowhead.
- **FR-004** — Node shapes are distinct. `rect` has square corners, `round` and `circle` have
  rounded corners, `diamond` has slanted corners.
- **FR-005** — An edge label sits on the edge's line.
- **FR-006** — A line never overwrites a box or a label. An edge that spans more than one
  layer passes between the boxes of the layers in between. Two lines that cross draw a
  crossing glyph.
- **FR-007** — A back edge (one that closes a cycle) is not routed. It is listed under the
  picture in the existing one-line form, `[B] ──► [A]`.
- **FR-008** — Labels are cut to 24 cells with an ellipsis, as today.
- **FR-009** — Width. A row wider than the pane is cut at its end, as today. When the picture
  of an `LR`/`RL` chart is wider than the pane, the HUD draws the chart top to bottom instead,
  if that fits. When no picture fits, or the chart has more than 60 nodes, the HUD draws the
  existing per-edge text form under a dim note that names the reason (the width, the height, the
  node count, the edge count).
- **FR-010** — The grid form is a pure function in `hooks/diagram.ts` with no `$`, tested
  without a process or a file system.
- **FR-011** — Desktop, mobile and vscode behaviour is unchanged: `Svg` as before.

## Success criteria

- **SC-001** — In the terminal test with the fixture worklog, every node label is inside a
  box and every forward edge is a line with an arrowhead, in rows of a picture, not a list.
- **SC-002** — `claude plugin test shipgate-hud` passes with new tests for: each direction,
  each edge style, each shape, a multi-layer edge, a crossing, a back edge, an edge label,
  the width fallbacks, and the 60-node limit.
- **SC-003** — `claude plugin validate shipgate-hud` passes.
- **SC-004** — The version is 0.5.0 in both manifests, the changelog has the entry, the
  README describes the terminal form, and ADR 0002 names ADR 0003 as its amendment.

## Constraints & assumptions

- The drawing is `Text` rows inside keyed `Box` rows, as the text form is today. `Text` takes
  no key.
- Box-drawing glyphs are width-1 BMP code points, so `cut` and `truncate-end` stay correct.

## Assumptions (executive)

- Text rows, not `Image` or `Raster` → text rows — `Image` draws pixels only on kitty and
  Ghostty; the maintainer's terminal is neither; `Raster` is a fixed box that the pane cannot
  cut row by row and its colours ignore the theme.
- Route back edges or list them → list them — routing around boxes costs the most code for
  the rarest case; a data flow seldom loops.
- Fallback order → LR picture, then TD picture, then the list form — the pane is narrow and
  tall, so a top-to-bottom picture fits where a left-to-right one does not.
- Version → 0.5.0 — a user-visible change in what the terminal draws is a minor bump.
- Node cap → 60 nodes — past that a terminal picture is unreadable and the row count grows
  the tree for nothing.

## Open questions

None.
