---
type: adr
title: "0003. Terminal diagrams drawn as a box-drawing grid"
created: 2026-10-15
updated: 2026-10-15
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-15
issue: none / ad-hoc
related:
  - "../prd/hud-terminal-diagrams.md"
  - "./0002-diagrams-drawn-by-the-hud.md"
---

# 0003. Terminal diagrams drawn as a box-drawing grid

> In the terminal the HUD lays a flowchart out on a character grid: boxes of box-drawing
> glyphs, lines with arrowheads between them. It amends the terminal half of ADR 0002.

## Context

ADR 0002 gave the terminal a text form: one line per layer, one line per edge. It is a list,
and the maintainer reads the Design tab in the terminal. The mods API offers three terminal
elements that could carry a picture:

1. `Text` rows. Every terminal shows them. The pane cuts each row to its width.
2. `Image`. Pixels over a box of cells, drawn only by kitty and Ghostty; every other terminal
   draws the `alt`. The HUD would also need its own rasterizer and a bitmap font, since the
   module has no DOM. Measured on 2026-10-15 with a probe mod drawing one `Image` in a pane: Ghostty
   showed the picture; the same session inside a terminal multiplexer (herdr) showed the
   `alt`. The multiplexer itself passes kitty graphics and answers the protocol's capability
   query, reports real pixel sizes, and answers the shared-memory query the same way Ghostty
   does. The only replies that differ are the identity ones: XTVERSION `libghostty` against
   `ghostty 1.3.1`, and the DA1 / DA2 attributes. So the engine gates pictures on the
   terminal's self-reported identity, and a picture form of the diagram would show its alt
   under that multiplexer until the engine changes.
3. `Raster`. A fixed cell grid with a colour per cell, terminal only. The site clips it as a
   block; a row-by-row cut and the theme's colours do not apply.

## Decision

The terminal form becomes a two-dimensional grid of width-1 box-drawing characters, drawn as
`Text` rows like the old text form. A pure function in `hooks/diagram.ts` turns the layered
layout into the grid: boxes with the label inside, lines with arrowheads, labels on the
lines, pass-through slots for edges that span layers, crossing glyphs where lines cross.
Back edges stay out of the grid and are listed under it in the old one-line form. When the
grid does not fit the pane, the HUD tries the top-to-bottom layout, then falls back to the
old text form under a note.

## Alternatives considered

- **`Image` with a PNG the HUD rasterizes.** Rejected: a bitmap font and a PNG encoder in the
  module for a picture that only kitty and Ghostty show; everyone else sees the `alt`.
- **`Raster`.** Rejected for now: no row cut, no theme colours, and the grid gains nothing
  from colour that glyph styles do not give. A follow-up if coloured edges are wanted.
- **Keep the list form.** Rejected: it is the problem.

## Consequences

- Easy: no new element on desktop; the grid is tested like the SVG; the old text form stays
  as the fallback, so nothing is lost on a narrow pane.
- Hard: routing on a grid is the largest piece of pure code in the plugin. Dense graphs will
  still read worse than Mermaid's own layout.
