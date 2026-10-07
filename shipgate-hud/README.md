# shipgate-hud

A Claude Code **mod** for [shipgate](../shipgate): it draws where a flow stands, in the
interface, from the journal shipgate already keeps.

- **Band above the prompt** — `feat/x · implement · tasks 3/11 · verify pass 12:30 · 2 to veto`,
  and a `hud` button that opens the pane. A band narrower than the summary wraps it onto more
  rows at the ` · ` separators rather than cutting it.
- **Pane** (`/hud`, or opened at session start in a wide terminal) with the phase timeline
  `WS ✓ MAP ✓ EXP ✓ CLR ✓ DSN ✓ IMP ● REV · CAP ·` and three tabs:
  - **Flow** — the stream's gate decisions, newest first, with who raised each one. A
    decision the orchestrator took on its own (`raised_by: orchestrator`, `mode: executive`)
    carries a **Veto** button; pressing it submits a prompt that names that decision (stream,
    gate, timestamp) and asks the orchestrator to read it from the journal and revisit it.
    The prompt never carries the journal's own text.
  - **Plan** — a progress bar and the worklog's Build Plan under its section headers, one line
    per task, cross-checked against the journal: `✓` done with a `task-done` event and the last
    verify that covered it, `✗` when that last verify failed, `◐` ticked in the worklog but never
    recorded (what the Stop hook will block on), `○` to do.
  - **Design** — the ADRs the design committed to, one line each, and the worklog's Design
    section as collapsible `##` sections, one open at a time (prose reflowed to the pane's width).
- The pane opens on the tab that matches the phase: Plan in `implement`, Design in `design`,
  Flow otherwise. The active tab and the current phase are drawn inverted. Hotkeys `1` `2` `3`
  switch, `r` refreshes, while the pane has focus. Long text is truncated to the pane's width;
  the artifacts hold the full text.

The position refreshes when the orchestrator appends to the journal, when a file in one of
the sidecar's artifact homes is written, after `/clear` or `/resume`, and once a minute
otherwise. A request that arrives during a refresh queues one trailing refresh.

## What it needs

- Claude Code **2.1.290 or newer** (the mods API; early access, so a release may move it).
- **shipgate** installed from the same marketplace, and a project that ran `/shipgate:setup`
  with a journal: the HUD keys off the `.claude/shipgate.json` sidecar.

In a project **without** that sidecar the mod draws nothing, opens no pane and runs no
process. `/hud` still exists and says so.

## Install

```
/plugin marketplace add worm2fed/pandora
/plugin install shipgate-hud@pandora
```

Or, for development, from a checkout: `claude --plugin-dir ./shipgate-hud`.

## How it reads the position

The hooks module runs with no Node and no SQLite, so it never opens the journal database.
One refresh is `git rev-parse --abbrev-ref HEAD`, then shipgate's own CLI —
`journal.py status --json --branch=<current>` and `journal.py log --stream <s> --json` —
then bounded reads of the worklog and ADR files those events point at (relative paths
inside the project only). Only the stream of the checked-out branch is shown; on a branch
with no stream the band is empty and the pane says so. In an umbrella checkout (the
session directory is a plain folder or a repo of its own, the real repos one level down,
in `source/` or in `packages/`) the session directory's branch carries no stream, so the
HUD then asks each nested repo for its branch (`git -C <repo> rev-parse --abbrev-ref HEAD`),
probes each distinct branch once, and shows the most recently active stream among the
matches (several nested repos may sit on branches with streams, one live, the rest dormant).
Dot-directories and `node_modules` are not looked into. When the events name no worklog yet,
the HUD looks in the sidecar's worklog home for a `*.worklog.md` whose name carries the
stream's slug (`feat/x-y` → `x-y`) and otherwise shows no plan. It writes nothing: a veto
goes through the prompt, and the orchestrator records the outcome.

`journal.py` is looked for, in order: the `journalScript` option; beside this plugin in a
marketplace checkout (`../shipgate/scripts/journal.py`, the plugin folder resolved through a
symbolic link); beside it in the plugin cache (`cache/<marketplace>/shipgate/<newest
version>/scripts/journal.py`); the plugin cache of the Claude config directory
(`$CLAUDE_CONFIG_DIR`, then `~/.claude`), any marketplace. Never a path taken from the
project. When none is found the pane says so and the band stays empty.

| Option (`/config` → shipgate-hud) | Default | Meaning |
| --- | --- | --- |
| `journalScript` | empty | Absolute path to `shipgate/scripts/journal.py`, when the lookup above fails |

## Layout

```
shipgate-hud/
  .claude-plugin/plugin.json   manifest (types, userConfig)
  hooks/hooks.json             { "modules": ["./register.tsx"] }
  hooks/register.tsx           the hooks and the side effects (locate, run, read)
  hooks/position.ts            pure: status / log / worklog / ADR → Position
  hooks/views.tsx              pure: Position → band and pane trees
  types/index.d.ts             the $.state contract
  tests/                       claude plugin test — the world beneath the plugin mocked
  docs/prd, docs/adr           PRD, worklog and ADRs for this plugin
```

`claude plugin validate shipgate-hud` and `claude plugin test shipgate-hud` are the checks.
Nothing under `shipgate/` changes for this plugin to work.

## Roadmap

Later slices, each its own PRD section: a Review findings board fed from the review
workflow's return; holding `gh pr create` / `git push` until the stream holds a
`review-verdict: ready`; the Explore essential-files tracker; a Route & Map risk heat grid;
a compaction-safe one-line position attached to every prompt; SVG diagrams on desktop.
