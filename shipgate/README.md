# shipgate

A lean, gate-driven feature-development plugin for Claude Code, built for anything from a
single repo to a multi-service umbrella. It's the synthesis of three systems — Anthropic's
**feature-dev** (the parallel-subagent engine + gates), GitHub's **spec-kit** (numbered
requirements, the clarify scan, CLAUDE.md-as-constitution), and **ai-devkit** (evidence-based
`verify`, memory discipline, breaking-change rules) — with the ceremony stripped out.

Nothing project-specific is hardcoded. Two files adapt the plugin to a project:

- the repo's **`CLAUDE.md`** files — routing and code conventions (where code belongs,
  build/test commands); the plugin *reads* them and enforces whatever they declare.
- an optional **`.claude/shipgate.md`** — process tooling (see **Configuration** below).

## The flow

```
Workspace → Route & Map → Explore → Clarify (gate) → Design → Implement → Review → Capture
```

Ceremony scales to the change: a one-line bugfix goes Workspace → Route → fix → verify; a real
feature runs the whole flow. Backward transitions (review → implement, design → clarify) are normal.

Start or resume work with **`/shipgate [description]`**, or just describe a feature/bug and the
`feature` orchestrator will route it.

## Configuration

Run **`/shipgate:setup`** in a project and it does this for you: detects the repo's shape,
asks a handful of questions with recommended defaults, writes `.claude/shipgate.md`, and —
if you want one — initializes the flow journal. Re-running it enters update mode rather
than clobbering what's there.

Or do it by hand: copy `config-template.md` from this plugin into your project as
**`.claude/shipgate.md`** and fill in what applies. Skills read it at the start of a flow and treat it as overriding
their defaults; subagents get the relevant excerpts pasted into their dispatch briefs.
Every section is optional — with no config at all, shipgate still works on sensible
defaults (in-repo `docs/prd|adr/`, forge auto-detected from the git remote).

What the sections configure:

| Section | Configures | Default without it |
| --- | --- | --- |
| Knowledge base | where PRDs/ADRs/worklogs and captured knowledge live (in-repo paths or an MCP-backed wiki), page conventions | `docs/prd/`, `docs/adr/`, capture to repo docs |
| Journal | the append-only flow journal's database path (written by `/shipgate:setup`) | no journal — phase inferred from artifact shape |
| Forge & tracker | GitLab/GitHub, CLI, MR/PR template + fetch command, issue-link form, AC source | auto-detect from `git remote` (`gh`/PR, `glab`/MR) |
| Branching | branch naming pattern + examples | `<type>/<issue-id>-<slug>` |
| Repo layout | umbrella / nested-repo checkouts, where the real repos live | working dir is the repo |
| Style | a project style skill to invoke before writing/reviewing code | match surrounding code |
| Security-sensitive areas | domains that trigger the full `/security-review` | auth, secrets, payments |
| Debug evidence sources | prod/QA log-query skill, CI-log integration | local logs, tests, debugger |
| Epic workflow | epic decomposition command, ordering, delivery rules | issue-by-issue, manual decomposition |

## What's inside

**Command**

- `/shipgate` — entry point; drives the `feature` orchestrator.

**Skills**

- `feature` — orchestrator: detects phase from artifacts, routes, owns escape hatches, drives epics issue-by-issue.
- `workspace` — Phase 0: get onto the right branch (`<type>/<issue-id>-<slug>`) off a clean base before any work; never builds on the wrong checkout — and never on an umbrella repo.
- `route-and-map` — reads CLAUDE.md (root + each touched module) + the knowledge base, emits an impact map.
- `clarify` — the hard gate: coverage scan, prioritized questions, writes the PRD (FR-###/SC-###).
- `design` — parallel architects → recommendation → ADR(s) + worklog (Design + Build Plan).
- `implement` — reuse-first execution, breaking-change discipline, per-task `verify`.
- `review` — parallel reviewers (≥80 confidence), CLAUDE.md compliance, acceptance-criteria check, final `verify`.
- `verify` _(cross-cutting)_ — no "done" without fresh command evidence.
- `model-tiers` _(cross-cutting)_ — the master session orchestrates only; implementation goes to worker subagents, mechanical sub-work sinks to the cheapest capable tier.
- `knowledge-base` _(cross-cutting)_ — recall/capture durable knowledge, routed by type to the stores the project config declares (default: repo docs). Named to avoid colliding with Claude's built-in session memory.
- `structured-debug` — on-demand: evidence-first debugging for bugs, regressions, incidents.

Security, simplification, and test-first are folded into the flow rather than living as
separate skills: the `code-reviewer` agent carries a security + simplicity lens, `implement`
writes the failing test first, and Claude Code's built-in `/security-review` and `/simplify`
cover dedicated audits/cleanups.

**Subagents** (the engine, run in parallel)

- `code-explorer` — grounded exploration, file:line, essential-files list.
- `code-architect` _(opus)_ — one committed design philosophy per instance.
- `code-reviewer` — confidence-filtered findings, file:line.

## Artifacts (3 per feature)

Homes are set by the config's Knowledge base section; defaults shown:

- `docs/prd/<name>.md` — PRD: what & why (FR-###, SC-###). No implementation.
- `docs/adr/NNNN-<title>.md` — one ADR per genuine decision fork. Immutable; supersede.
- `docs/prd/<name>.worklog.md` — one working doc next to its PRD: **Design** section +
  **Build Plan** section (tasks with tests, `[P]` markers, progress). Tests are tasks, never
  a separate doc.

## Memory

`knowledge-base` routes durable knowledge **by type** to its natural home, rather than dumping
everything in one store. The stores themselves come from the project config — a team wiki
over MCP, in-repo docs, or both; without config:

- **Engineering** — decisions, specs, conventions, gotchas, root causes → the **repo**
  (`docs/adr/`, `docs/prd/`, `CLAUDE.md`). Lives with the code, versioned and reviewed with it.
- **Product/domain insight** → a vault MCP if one is available — sparingly; otherwise the repo.

No npx/SQLite dependency; everything is git-visible or in a store you chose. Recall mirrors
the split and degrades gracefully if a store isn't reachable.

## Install

shipgate is published through the **`pandora`** marketplace (manifest at the repo
root, `.claude-plugin/marketplace.json`). From a local clone or the git remote:

```
/plugin marketplace add ~/workspace/plugins
/plugin install shipgate@pandora
```

Then drive it with `/shipgate [description]`. Updating the marketplace (`/plugin marketplace
update pandora`) picks up new versions when the entry's `version` bumps.

## Dependencies & integrations

shipgate has **no hard dependencies** — install it and it works. Every integration below is
consulted only "if available" or when the project config names it, so a missing one never
breaks the flow; it just falls back. (Claude Code has no enforced plugin-dependency
mechanism, so this list is the source of truth for what to install to get the full
experience.)

**Required:** Claude Code. That's it.

**Optional integrations** (each enhances one part of the flow):

| Integration                                                            | Kind                  | Unlocks                                                                                                                                                            | Without it                                         |
| ---------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| [`thinking-skills`](https://github.com/tjboudreaux/cc-thinking-skills) | plugin                | structured lenses in Clarify (JTBD), Design (reversibility, pre-mortem), Review (red-team), Debug (Occam/Kepner-Tregoe/5-whys), + `thinking-model-router` fallback | the skills apply the idea inline, unaided          |
| a knowledge-base MCP (named in config)                                 | MCP                   | team/product memory — recall & store in a wiki/vault                                                                                                               | memory falls back to repo docs (`CLAUDE.md`, ADRs) |
| forge CLI + tracker MCP (`gh` / `glab`, named in config)               | CLI/MCP               | `clarify` seeds the PRD from the issue; `review` opens the MR/PR and checks its acceptance criteria                                                                | capture the issue link manually; push by hand      |
| a log-query skill (named in config)                                    | skill                 | prod/QA log evidence in `structured-debug`                                                                                                                         | use `docker logs` / local sources                  |
| `chrome-devtools-mcp`                                                  | MCP/skill             | frontend/browser evidence in `structured-debug`                                                                                                                    | use other evidence sources                         |
| `/security-review`, `/simplify`                                        | Claude Code built-ins | deep security audit / standalone cleanup                                                                                                                           | ship with Claude Code already                      |
| an MR/PR-watcher skill (named in config)                               | skill                 | `review` registers blockers/follow-ups on the watch list; watcher events resume the flow at the phase they unlock                                                  | flow ends at "MR opened"; resume manually          |

The plugin also expects the repo to carry **`CLAUDE.md`** files (root + nested where relevant) —
that's how `route-and-map` decides where code belongs. Repos without them still work; routing is
just less informed.

## Status

v0.7.1 — implement's reuse-before-writing step now also checks the dependency's own API
surface and same-module siblings before hand-rolling integration plumbing (pairs with
astrolabe v0.3.0's reuse ladder).

v0.7.0 — orchestration throughput: **design-ahead pipelining** (while workers implement
issue N, the orchestrator specs N+1 with the user — epic mode's stop now gates merge+build,
not design; queued designs are re-validated against what actually merged); **executive
autonomy mode** (config-declared, default `ask` — in `executive` the orchestrator makes and
records routine gate decisions, escalating only one-way doors, scope changes,
security-sensitive areas, and true 50/50s); **the ledger** (a project-wide, append-cheap
staging inbox for mid-flow learnings, triaged at Capture into config-declared promotion
targets — wiki pages, skills, CLAUDE.md, ADRs, personal memory — or dropped; Capture now
fires when review passes, never waiting on the merge); and **worker lifecycle** (reuse warm
workers via SendMessage for same-context follow-ups, spawn cold for different context,
retire degraded workers ~400k tokens / 4-6 rounds in and brief a fresh finisher off the
worktree state).

v0.6.0 — bug provenance: `structured-debug` gains a "trace the provenance" step — find
the commit that introduced the defect (`log -S` / `blame` / `bisect run` with the repro),
prove it counterfactually (repro fails at the commit, passes at its parent), name why it
slipped through, and report all of it in a comment on the tracker issue. New optional
**Bug provenance** line in the config's Forge & tracker section says where those comments
go (default: the bug's issue, via the forge CLI).

v0.5.0 — re-tuned for current-generation models (per Anthropic's Opus 5 prompting
guidance): review is coverage-first (reviewers report every finding scored with
confidence + severity; a separate coordinator pass filters — generation-time severity
floors made models silently drop real bugs); the verify gate is scoped to evidence, not
repetition (fresh command output per claim stays, re-check choreography goes — independent
fresh-context review remains a distinct, kept discipline); delegation is disciplined (one
agent when one suffices, fan-outs scale to the task, tiers phrased relative to the
orchestrator's model instead of hardcoding "opus = mid"); `effort` added as the second
cost lever (agent frontmatter + Workflow `opts.effort`, mechanical work at `low`); and
written deliverables (PRD/ADR/worklog/MR body) carry explicit length calibration.

v0.4.1 — docs/wording only, no behavior change: the review-feedback cycle is now defined
(in `review` — a loop between Review and Implement), the MR watcher is called an
integration rather than a hook (no Claude Code hook is involved), and the project-config
preamble duplicated across skills was slimmed to one canonical form.

v0.4.0 — optional **MR watcher** integration: a project-declared skill watches open MRs/PRs;
`review` registers blockers/follow-ups with it, and its events resume the flow at the
phase they unlock (comments → review-feedback, merge → capture, blocker merged → held work).

v0.3.0 — merged the work-fork's evolution back (model-tiers, richer workspace/epic/review
discipline) and made every project specific a `.claude/shipgate.md` config concern.
