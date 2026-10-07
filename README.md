# pandora

Personal [Claude Code](https://claude.com/claude-code) plugin marketplace.

## Install

```
/plugin marketplace add worm2fed/pandora
/plugin install <plugin>@pandora
```

## Plugins

| Plugin | What it does |
|---|---|
| [**shipgate**](./shipgate) | Lean, gate-driven feature development: workspace → route → explore → clarify → design → implement → review → capture. Routes by CLAUDE.md, explores in parallel, never claims done without evidence, orchestrates by model tier, captures learnings to a configurable knowledge base. Per-project setup via `.claude/shipgate.md`; integrations (forge CLI, knowledge-base MCP, MR watcher) degrade gracefully. |
| [**shipgate-hud**](./shipgate-hud) | A Claude Code mod for shipgate: the flow's position drawn in the interface — a band above the prompt (stream, phase, tasks, last verify, decisions to veto) and a phase-aware pane with the gate decisions (one-press veto), the Build Plan cross-checked against the journal, and the committed design. Reads the journal through shipgate's CLI; draws nothing without a shipgate journal. |
| [**astrolabe**](./astrolabe) | Typed functional code style: types first, immutability, smart constructors, illegal states unrepresentable, side effects at the top of the stack. Examples in TypeScript (fp-ts, ts-pattern, newtype-ts, fast-check); principles language-portable. Designed to pair with a per-project style skill — and with shipgate's config Style section. |
| [**bpmn**](./bpmn) | BPMN 2.0 diagrams from plain language: Claude writes the semantic XML; bundled tooling auto-layouts (pools, lanes, boundary events), validates with bpmnlint, and renders a self-contained HTML preview. |

Each plugin has its own README with details and configuration.

## Why "pandora"

The box everything ships out of. The plugins keep the theme: **shipgate** is the
gate the work passes through; **astrolabe** is the instrument you navigate code by.

## Layout

```
pandora/
├── .claude-plugin/marketplace.json   ← the marketplace manifest
├── shipgate/                         ← one directory per plugin
├── shipgate-hud/
├── astrolabe/
├── bpmn/
└── herdr/
```

## License

MIT (`LICENSE`) — except `herdr/`, which redistributes the upstream Herdr skill under
Apache-2.0 and carries its own `LICENSE` and `NOTICE`.
