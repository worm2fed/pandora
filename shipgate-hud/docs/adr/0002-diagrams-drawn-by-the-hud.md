---
type: adr
title: "0002. Diagrams drawn by the HUD from a Mermaid flowchart subset"
created: 2026-10-14
updated: 2026-10-14
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-14
issue: none / ad-hoc
related:
  - "../prd/hud.md"
  - "./0001-sibling-plugin-fed-by-the-journal-cli.md"
---

# 0002. Diagrams drawn by the HUD from a Mermaid flowchart subset

> The HUD parses a worklog's fenced `mermaid` flowchart itself and lays it out as an SVG on
> desktop and as box-and-arrow text in the terminal. No push tool, no renderer process, no
> network.

## Context

Slice 3 draws the worklog's diagrams in the Design tab. A worklog carries them as fenced
blocks: ```` ```svg ```` is ready to draw; ```` ```mermaid ```` is source that needs a
renderer. Three facts shape the choice:

1. The hooks module runs with no DOM and no Node. The Mermaid library needs both, so it
   cannot run inside the HUD.
2. The rule for this plugin is that nothing under `shipgate/` changes. A push tool that the
   design skill calls with a rendered SVG would need the skill to render and call it.
3. The plugin's hooks run on every user's machine. A renderer process (`mmdc`, which is not
   installed here) or a network renderer would spawn a browser or send design text out.
   Both are new surface in a security-sensitive area, for a picture.

The worklog template's diagrams are data flows: boxes and arrows. Those are the `flowchart`
/ `graph` subset of Mermaid, which a few hundred lines of pure TypeScript can parse and lay
out.

## Decision

The HUD renders diagrams itself. A pure module `hooks/diagram.ts` parses the flowchart subset
(`flowchart` / `graph` with a direction; node shapes `[ ]`, `( )`, `{ }`, `(( ))`; edges
`-->`, `---`, `-.->`, `==>` with `|label|` or `-- label -->`; `subgraph` flattened; `%%`
comments) into nodes and edges, assigns layers by longest path from the sources, and emits
two forms: an SVG document (rounded rectangles, straight or elbowed lines with arrowheads,
labels), and a text form (one line per layer, `[A] ──► [B]` with the edge label inside the
arrow). The Design tab splits a section at its `mermaid` and `svg` fences: prose stays
Markdown; an `svg` block is `Svg` where the surface has it and `Code` in the terminal; a
flowchart is `Svg` from the HUD's layout where the surface has it and the text form in the
terminal; any other Mermaid kind is `Code` with language `mermaid`.

## Alternatives considered

- **A push tool from the design skill** (`$.tool.register('hud_diagram', …)` called by the
  skill with an SVG). Rejected: it needs changes under `shipgate/`, it couples the skill to
  the mod, and the skill would still have to render Mermaid somewhere. ADR 0001 kept the
  push tool as the escape hatch for transient data; a diagram is not transient, it is in
  the worklog.
- **An external renderer** (`mmdc` through `$.process.run`, or an HTTP renderer through
  `$.fetch`). Rejected: a browser spawn or a network call on every user's machine, from a
  hooks module, for a drawing; the design text would leave the machine in the network case.
- **Code only** (draw the fence as `Code` everywhere). The fallback kept for every Mermaid
  kind outside the subset, not the answer for data flows.

## Consequences

- Easy: no new process or network call; the parser and layout are pure and tested like
  `position.ts`; the terminal gets a readable text form for free from the same parse.
- Hard: the layout is simple (layered, left to right or top to bottom); a dense graph with
  many back edges will look worse than Mermaid's. Sequence, class and state diagrams stay
  code.
- Follow-up: when a mods release lets a surface render Mermaid in `Markdown`, the HUD can
  pass the fence through and drop the layout.
