# bpmn

BPMN 2.0 diagrams from plain language, without the manual layout fixup loop.

## Why

The common "Claude writes BPMN XML → import into bpmn.io → fix the layout by
hand" workflow fails at a predictable spot: LLMs are good at process
*semantics* and bad at hand-computing diagram coordinates. This plugin splits
the work accordingly:

1. **Claude writes semantic-only XML** — processes, tasks, gateways, message
   flows. No `bpmndi` section, ever.
2. **`layout.mjs`** generates all coordinates — [bpmn-auto-layout] for single
   processes, plus custom passes for what it doesn't support: lane banding and
   multi-pool collaboration stacking with message-flow routing.
3. **`validate.mjs`** runs a bpmn-moddle schema check + [bpmnlint]
   (`bpmnlint:recommended`) so modeling defects (dead ends, fake joins,
   unlabeled gateways) are caught before anyone looks at the diagram.
4. **`render.mjs`** produces a fully self-contained HTML preview ([bpmn-js]
   inlined, no CDN/network) with pan/zoom and SVG/.bpmn download buttons.

Iteration happens in conversation: describe a change, Claude edits the
semantics, re-layouts, re-renders. The final `.bpmn` imports cleanly into
[bpmn.io](https://demo.bpmn.io) / Camunda Modeler for optional manual polish.

## Usage

Ask for a diagram in natural language, or invoke the skill directly:

```
/bpmn model our code-review workflow: developer opens MR, reviewer approves
or requests changes, 3-day idle timeout pings reviewers
```

Requirements: Node ≥ 18. Dependencies install on first use
(`npm install` inside `skills/bpmn/scripts/`).

[bpmn-auto-layout]: https://github.com/bpmn-io/bpmn-auto-layout
[bpmnlint]: https://github.com/bpmn-io/bpmnlint
[bpmn-js]: https://github.com/bpmn-io/bpmn-js
