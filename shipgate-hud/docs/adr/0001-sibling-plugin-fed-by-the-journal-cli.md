---
type: adr
title: "0001. A sibling plugin fed by the journal CLI"
created: 2026-10-06
updated: 2026-10-06
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-06
issue: none / ad-hoc
related:
  - "../prd/hud.md"
---

# 0001. A sibling plugin fed by the journal CLI

> The HUD is its own plugin in the marketplace, and it reads shipgate's position through
> `journal.py` and the artifact files — never through shipgate's internals.

## Context

Claude Code mods (function hooks) can draw the flow position in the interface. Two
questions decide the shape of everything after them:

1. **Where does the module live?** A `hooks/hooks.json` may carry both settings hooks and a
   `modules` entry, so the module could sit inside `shipgate/` and ship with it. Or it is a
   second plugin in the same marketplace.
2. **How does it read the position?** The journal is SQLite. The hooks module runs in an
   environment with no Node and no DOM, so it cannot open the database. It can run processes
   and read files.

Forces: the mods API is explicitly early access and "may change between releases without
notice". shipgate's hooks run on every user's machine in every project; the project config
names anything that changes what an installed plugin does as an escalation. `journal.py
status --json` already computes the phase, the implied transitions, the gate decisions and
the last verify, and is covered by the shipgate test suite.

## Decision

`shipgate-hud` is a sibling plugin under `shipgate-hud/` with its own version and
marketplace entry. It depends on shipgate being present on the machine but never imports
or modifies it. It reads the position by running `python3 <shipgate>/scripts/journal.py
status --json --branch=<current>` and `log --stream <s> --json`, and reads the worklog and
ADR files named by those events (relative, in-project paths only). It locates `journal.py`
from the `journalScript` option when set, else beside itself
(`$.plugin.root/../shipgate/scripts/journal.py`, the marketplace layout, the root resolved
through a link), else under the plugin cache beside it, else under the config directory's
plugin cache (`$CLAUDE_CONFIG_DIR/plugins/cache/<marketplace>/shipgate/<newest version>/`).

## Alternatives considered

- **A `modules` entry in shipgate's own `hooks/hooks.json`.** One install, one version.
  Rejected: a module that fails to load or a hook that times out would land in the plugin
  that owns the Stop gate; and the module needs a Claude Code version newer than shipgate
  requires, so shipgate would inherit a floor it does not need.
- **Read the SQLite file directly.** No process spawn, no dependency on the script's
  location. Rejected: no sqlite in the runtime, and reimplementing `status` (implied
  phases, gate decision folding, verify scope) in TypeScript duplicates logic the shipgate
  tests already guard.
- **A push tool the orchestrator calls** (`$.tool.register('hud_show', …)`) so skills send
  the pane what to draw. Rejected for slice 1: it couples every skill to the mod. Kept as
  the escape hatch for transient data the journal does not hold (architect comparisons,
  review findings before the worklog records them).

## Consequences

- Easy: shipgate's test suite and Stop gate are untouched; the HUD can break and be fixed
  on its own cadence; the marketplace shows it as an optional add-on.
- Hard: locating `journal.py` is a heuristic with two fallbacks behind the config option;
  a refresh costs one `git` and two Python processes (under 300 ms together) and is
  coalesced while one is in flight.
- Follow-up: when the mods API stabilises, revisit whether a push tool is worth adding
  for the Review board.
