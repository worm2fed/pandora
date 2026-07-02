# shipgate

A lean, gate-driven feature-development plugin for Claude Code. It's the synthesis of three
systems — Anthropic's **feature-dev** (the parallel-subagent engine + gates), GitHub's
**spec-kit** (numbered requirements, the clarify scan, CLAUDE.md-as-constitution), and
**ai-devkit** (evidence-based `verify`, memory discipline, breaking-change rules) — with the
ceremony stripped out. Routing rules aren't hardcoded: they live in the target repo's
`CLAUDE.md` files and the plugin _reads_ them, so it works in any repo and enforces whatever
discipline that repo declares.

## The flow

```
Workspace → Route & Map → Explore → Clarify (gate) → Design → Implement → Review → Capture
```

Ceremony scales to the change: a one-line bugfix goes Workspace → Route → fix → verify; a real
feature runs the whole flow. Backward transitions (review → implement, design → clarify) are normal.

Start or resume work with **`/shipgate [description]`**, or just describe a feature/bug and the
`feature` orchestrator will route it.

## What's inside

**Command**

- `/shipgate` — entry point; drives the `feature` orchestrator.

**Skills**

- `feature` — orchestrator: detects phase from artifacts, routes, owns escape hatches.
- `workspace` — Phase 0: get onto the right branch (`<type>/<issue-id>-<slug>`, issue-id optional) off a clean base before any work; never builds on the wrong checkout.
- `route-and-map` — reads CLAUDE.md (root + each touched module), emits an impact map.
- `clarify` — the hard gate: coverage scan, prioritized questions, writes the PRD (FR-###/SC-###).
- `design` — parallel architects → recommendation → ADR(s) + worklog (Design + Build Plan).
- `implement` — reuse-first execution, breaking-change discipline, per-task `verify`.
- `review` — parallel reviewers (≥80 confidence), CLAUDE.md compliance, final `verify`.
- `verify` _(cross-cutting)_ — no "done" without fresh command evidence.
- `knowledge-base` _(cross-cutting)_ — recall/capture durable knowledge, routed by type: engineering to the repo (docs/adr, CLAUDE.md), general findings and project status to the personal vault. Named to avoid colliding with Claude's built-in session memory.
- `structured-debug` — on-demand: evidence-first debugging for bugs, regressions, incidents.

Security, simplification, and test-first are folded into the flow rather than living as
separate skills: the `code-reviewer` agent carries a security + simplicity lens, `implement`
writes the failing test first, and Claude Code's built-in `/security-review` and `/simplify`
cover dedicated audits/cleanups.

**Subagents** (the engine, run in parallel)

- `code-explorer` — grounded exploration, file:line, essential-files list.
- `code-architect` _(opus)_ — one committed design philosophy per instance.
- `code-reviewer` — confidence-filtered findings, file:line.

## Artifacts (3 per feature, in the target repo)

- `docs/prd/<name>.md` — PRD: what & why (FR-###, SC-###). No implementation.
- `docs/adr/NNNN-<title>.md` — one ADR per genuine decision fork. Immutable; supersede.
- `docs/prd/<name>.worklog.md` — one working doc next to its PRD: **Design** section +
  **Build Plan** section (tasks with tests, `[P]` markers, progress). Tests are tasks, never
  a separate doc.

## Memory

`knowledge-base` routes durable knowledge **by type** to its natural home, rather than dumping
everything in one store:

- **Engineering** — decisions, specs, conventions, gotchas, root causes → the **repo**
  (`docs/adr/`, `docs/prd/`, `CLAUDE.md`). Lives with the code, versioned and reviewed with it.
- **General findings / project status** → the **personal Obsidian vault** via the
  `obsidian-vault` MCP — sparingly, and never project-dev specifics.

No npx/SQLite dependency; everything is git-visible or in the vault. Recall mirrors the split
and degrades gracefully if a store isn't reachable.

## Install

shipgate is published through the **`worm2fed-plugins`** marketplace (manifest at the repo
root, `.claude-plugin/marketplace.json`). From a local clone or the git remote:

```
/plugin marketplace add ~/workspace/plugins
/plugin install shipgate@worm2fed-plugins
```

Then drive it with `/shipgate [description]`. Updating the marketplace (`/plugin marketplace
update worm2fed-plugins`) picks up new versions when the entry's `version` bumps.

## Dependencies & integrations

shipgate has **no hard dependencies** — install it and it works. Every integration below is
consulted only "if available," so a missing one never breaks the flow; it just falls back.
(Claude Code has no enforced plugin-dependency mechanism, so this list is the source of truth
for what to install to get the full experience.)

**Required:** Claude Code. That's it.

**Optional integrations** (each enhances one part of the flow):

| Integration                                                            | Kind                  | Unlocks                                                                                                                                                            | Without it                                         |
| ---------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| [`thinking-skills`](https://github.com/tjboudreaux/cc-thinking-skills) | plugin                | structured lenses in Clarify (JTBD), Design (reversibility, pre-mortem), Review (red-team), Debug (Occam/Kepner-Tregoe/5-whys), + `thinking-model-router` fallback | the skills apply the idea inline, unaided          |
| `obsidian-vault` MCP                                                   | MCP                   | general/project-status memory — recall & store in the personal vault                                                                                               | memory falls back to repo docs (`CLAUDE.md`, ADRs) |
| `gh` CLI (GitHub repos)                                                | CLI                   | `clarify` seeds the PRD from the issue; `review` opens the PR and checks its acceptance criteria                                                                   | capture the issue link manually; push by hand      |
| `chrome-devtools-mcp`                                                  | MCP/skill             | frontend/browser evidence in `structured-debug`                                                                                                                    | use other evidence sources                         |
| `/security-review`, `/simplify`                                        | Claude Code built-ins | deep security audit / standalone cleanup                                                                                                                           | ship with Claude Code already                      |

The plugin also expects the repo to carry **`CLAUDE.md`** files (root + nested where relevant) —
that's how `route-and-map` decides where code belongs. Repos without them still work; routing is
just less informed.

## Status

v0.2.0 — personal fork of the original work plugin, made tracker-agnostic and stack-agnostic.
