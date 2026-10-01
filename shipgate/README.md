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
| MR watcher | a project skill that watches open MRs/PRs + the command to register a blocker/follow-up on its watch list | no watcher — the flow ends at "MR/PR opened" |
| Code tooling | the library-docs tool/MCP to consult for a dependency's current API, and the LSP tool for symbol navigation | training knowledge / WebFetch; grep-and-read |
| Code signals | window, fix-commit pattern and extra excludes for the bundled risk signals (the one section a script reads, not the model) | 12-month window, built-in fix pattern and excludes |
| Worker guardrails | the project's hard rules, pasted verbatim into every worker brief | only the built-in worker discipline (branch check, no staging, evidence) |
| Orchestration | whether Review / Explore fan out via bundled `Workflow` scripts or `Agent` subagents | `agents` for both |
| Thinking lenses | which lens skills to actually invoke at which phase | no lens skills invoked — the phase skills apply each lens's idea inline |
| Autonomy | `ask` vs `executive` — whether the orchestrator answers routine gate questions itself (and records them) | `ask` — every gate question goes to the user |

## What's inside

**Command**

- `/shipgate` — entry point; drives the `feature` orchestrator.

**Skills**

- `feature` — orchestrator: detects phase from artifacts, routes, owns escape hatches, drives epics issue-by-issue.
- `setup` — bootstrap: detects the repo's shape, interviews with recommended defaults, writes `.claude/shipgate.md` + its generated `.claude/shipgate.json` sidecar, and initializes the flow journal. Re-run to update.
- `workspace` — Phase 0: get onto the right branch (`<type>/<issue-id>-<slug>`) off a clean base before any work; never builds on the wrong checkout — and never on an umbrella repo.
- `route-and-map` — reads CLAUDE.md (root + each touched module) + the knowledge base, emits an impact map. Also answers a standalone "what does this change affect?".
- `clarify` — the hard gate: coverage scan, prioritized questions, writes the PRD (FR-###/SC-###).
- `design` — parallel architects → recommendation → ADR(s) + worklog (Design + Build Plan).
- `implement` — reuse-first execution, breaking-change discipline, per-task `verify`.
- `review` — parallel reviewers report everything scored (coverage over self-filtering); a separate coordinator pass filters at ≥80 confidence. Plus CLAUDE.md compliance, acceptance-criteria check, final `verify`. Also answers a standalone "rank the changed files by risk", and the re-review after a round of fixes ("I've addressed F1 and F2 — good to push?"), scoped to the fix diff.
- `verify` _(cross-cutting)_ — no "done" without fresh command evidence.
- `model-tiers` _(cross-cutting)_ — the master session orchestrates only; implementation goes to worker subagents, mechanical sub-work sinks to the cheapest capable tier.
- `knowledge-base` _(cross-cutting)_ — recall/capture durable knowledge, routed by type to the stores the project config declares (default: repo docs). Named to avoid colliding with Claude's built-in session memory.
- `structured-debug` — on-demand: evidence-first debugging for bugs, regressions, incidents — a pasted stack trace with no repo access included, and a report that says "just fix it" (the fix still waits for an approved plan). Also answers a standalone "which file has the defect?".

Security, simplification, and test-first are folded into the flow rather than living as
separate skills: the `code-reviewer` agent carries a security + simplicity lens, `implement`
writes the failing test first, and Claude Code's built-in `/security-review` and `/simplify`
cover dedicated audits/cleanups.

**Subagents** (the engine, run in parallel)

- `code-explorer` — grounded exploration, file:line, essential-files list.
- `code-architect` _(opus)_ — one committed design philosophy per instance.
- `code-reviewer` — every finding scored (confidence + severity), file:line; the coordinator filters.

**Scripts** (Python 3 stdlib)

- `scripts/journal.py` — the flow journal CLI; `scripts/signals.py` — per-file risk signals, read by `route-and-map`, `review` and `structured-debug` (see [Code signals](#code-signals)).

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

Between recall and capture sits the **ledger** (`docs/ledger.md` by default): one dated line
per learning, appended the moment it surfaces — `structured-debug` at the confirmed root
cause, `implement` at each task tick, `review` while ranking findings — and triaged at
Capture, where each line is promoted to its home or dropped.

## Flow journal

On a journaled project (`/shipgate:setup` writes the config and creates the database) position
is an append-only event stream — **one stream per issue, named for its branch** — rather than
something re-inferred from artifacts every session. The session-start hook injects the brief;
`scripts/journal.py` is the whole interface:

| Command | Does |
| --- | --- |
| `status [--branch B] [--feature SLUG] [--all]` | the position brief: the checked-out branch's stream first and in full, dormant streams as one line, completed ones hidden unless `--all` |
| `append --stream S --type T --data '{…}' [--actor R] [--expect N] [--batch]` | record one event — or a JSONL batch on stdin, so a phase boundary costs one call |
| `vocab [--shape T]` | the event vocabulary, and the canonical payload for one type |
| `check --session ID` | what the flow still owes (the Stop hook's source) |
| `stats [--since ISO] [--stream S] [--json]` | events by actor, gate decisions by mode × who raised them, deviations, verifies per task, review rounds |
| `log`, `streams`, `session --set/--get`, `init`, `doctor`, `export`, `import` | plumbing: the raw event log, the streams and their versions, current session id, schema, health, portability |

`append` is where the gates live. It validates the payload against its type's shape
(normalizing known aliases), records the `phase-entered` a phase-owning event implies — which
is why such an append can advance the stream's version by two, and why a chain of `--expect N`
must read each new version back from the output instead of assuming +1 — refuses a payload over
1 KB (prose belongs in the worklog — the event carries `refs`), and refuses `mr-opened` until
the stream holds, after its last `task-done`, either a `review-verdict` with `verdict=ready` or
a `gate-decision` with `gate=publish`, `raised_by=user` and `decision=publish`. `actor` is `role[@label]` with role ∈ `orchestrator |
worker | user | hook | watcher`; omit it and the append is attributed to the orchestrator plus
the current session. A stream ends with `flow-completed` and leaves the brief.

## Code signals

Per-file risk computed from the code and its history, on demand, by
`scripts/signals.py` — no index, no cache, nothing written. One `git log` pass gives each
file's **trajectory** over the window: commits, fix-rate (share of commits whose subject
matches the fix pattern), age, staleness, author count and top-author share. One import scan
gives **structure** for TS/JS, Python and Go: fan-in, fan-out and the blast radius
(transitive importers) of a file set; other languages report `structure: unknown`, never a
wrong number. Every number carries a label — `low | mid | high | top`, quartiles over *this*
repository (or `--scope`), so `top` means top here; paths and `--diff` only filter the rows.

| Command | Does |
| --- | --- |
| `hotspots [PATH…] [--diff REV] [--by-dir DEPTH] [--blast] [--top N]` | ranked per-file signals, optionally rolled up to modules and with the selection's blast radius |
| `blast FILE… [--diff REV] [--limit N]` | transitive importers of a file set — structure only, no log pass |
| `suspects FILE… [--top N]` | files near a symptom ranked by fix-rate × recency × proximity, for debugging |

Common flags: `--repo`, `--scope`, `--window`, `--fix-pattern`, `--exclude`, `--json`; they
override the `## Code signals` config section. Consumers: `route-and-map` (a **Risk signals**
block in the impact map, essentials in the journal), `review` (a per-file risk table in the
brief, and `fileRisk` for the workflow's refuter ordering), `structured-debug` (a suspect
list cited as `[signals]` evidence), `implement` and `design` (prefer the proven precedent),
and optionally explorer and worker briefs. No git, a shallow clone, an empty history or no
adapter → one line saying why, exit 0, the phase runs as before. Output carries counts and
shares, never author names.

## Install

shipgate is published through the **`pandora`** marketplace (manifest at the repo
root, `.claude-plugin/marketplace.json`):

```
/plugin marketplace add worm2fed/pandora
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

**Required:** Claude Code. That's it — the bundled scripts (the journal, the code signals)
are Python 3 standard library only, and the signals skip themselves where there is no git.

**Optional integrations** (each enhances one part of the flow):

| Integration                                                            | Kind                  | Unlocks                                                                                                                                                            | Without it                                         |
| ---------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| [`thinking-skills`](https://github.com/tjboudreaux/cc-thinking-skills) | plugin                | structured lenses in Clarify (JTBD), Design (reversibility, pre-mortem), Review (red-team), Debug (Occam/Kepner-Tregoe/5-whys), + `thinking-model-router` fallback | the skills apply the idea inline, unaided          |
| a knowledge-base MCP (named in config)                                 | MCP                   | team/product memory — recall & store in a wiki/vault                                                                                                               | memory falls back to repo docs (`CLAUDE.md`, ADRs) |
| forge CLI + tracker MCP (`gh` / `glab`, named in config)               | CLI/MCP               | `clarify` seeds the PRD from the issue; `review` opens the MR/PR and checks its acceptance criteria                                                                | capture the issue link manually; push by hand      |
| a log-query skill (named in config)                                    | skill                 | prod/QA log evidence in `structured-debug`                                                                                                                         | use `docker logs` / local sources                  |
| `chrome-devtools-mcp`                                                  | MCP/skill             | frontend/browser evidence in `structured-debug`                                                                                                                    | use other evidence sources                         |
| `/security-review`, `/simplify`                                        | Claude Code built-ins | deep security audit / standalone cleanup                                                                                                                           | ship with Claude Code already                      |
| the `Workflow` tool (Claude Code built-in; config `## Orchestration`)  | Claude Code built-in  | Review and Explore fans run as bundled scripts: schema-typed findings, in-script dedupe, evidence-required refuters on review's top findings                       | the `Agent` fan, as before                         |
| an MR/PR-watcher skill (named in config)                               | skill                 | `review` registers blockers/follow-ups on the watch list; watcher events resume the flow at the phase they unlock                                                  | flow ends at "MR/PR opened"; resume manually       |

The plugin also expects the repo to carry **`CLAUDE.md`** files (root + nested where relevant) —
that's how `route-and-map` decides where code belongs. Repos without them still work; routing is
just less informed.

## Status

v0.13.0 — code signals. The flow's intelligence was all *declared* (CLAUDE.md, ADRs, the
journal); nothing computed what the code and its history say. **Signals**: a second bundled
stdlib script, `scripts/signals.py` (`hotspots`, `blast`, `suspects`), computes per-file git
trajectory (commits, fix-rate, age, staleness, author count and top share) and, for TS/JS,
Python and Go, import-graph fan-in/out and blast radius, each labelled by quartile over the
whole repository so `top` means top *here*; "now" is HEAD's commit time, so two runs on one
state are byte-identical, and nothing persists (ADR 0004). A new `## Code signals` config
section (window, fix pattern, extra excludes) is the first one a script reads itself, so the
terminal and the flow compute the same numbers. **Wiring**: `route-and-map`'s impact map
gains a **Risk signals** block and the journal entry its labels and sizes; `review` briefs
carry the diff's risk table, and `review-workflow.js` takes an optional `fileRisk` that
tie-breaks ranking after severity and confidence and spends the refuter budget severity →
risk → confidence — risk never overrides severity, and absent it the output is byte-identical;
`structured-debug` starts hypotheses from a ranked suspect list; `implement` and `design`
prefer the precedent with the lower fix-rate, greater age and higher fan-in; explorer and
worker briefs may carry the table. No git, a shallow clone, an empty history or no adapter
degrades to one line and the phase as before. **Honesty**: fan-in is a lower bound in
alias-heavy or dynamically-imported code (the output marks `partial` / `unresolved`; risk is
a tie-break within a severity band only, so an undercount can cost a file its refuter slot in
that band but never changes a severity or drops a finding); granularity is the file, not the method,
and the semantic axis (embeddings, BM25, a glossary) is out of scope by decision. An indexed
retrieval layer (TeaRAGs-style: daemon, embedding runtime, ~1 GB per repo) was evaluated and
rejected as a dependency — see `docs/research/2026-09-25-tearags-vs-shipgate.md`. Evals
08–11 (bug localization from history, blast radius of a diff, risk-ranked review, a negative
one-line change) cover the new behaviour under `--ablation with-without`.

v0.12.0 — orchestration by workflow, config-selected. A new `## Orchestration` config
section (`review: agents | workflow`, `explore: agents | workflow`, default `agents`) lets
a project run the Review fan and the Explore fan as `Workflow` scripts bundled with the
skills instead of hand-driven `Agent` fans. **Review**: `review-workflow.js` runs the lens
finders (`shipgate:code-reviewer`, schema-typed findings, do-not-flag and pre-rulings
passed as `args`), dedupes across lenses in script, then spends a capped refuter budget
(`verify: none | high-only | all`, defaulting to `high-only` with `maxRefuters: 6`) on the
BLOCKER/HIGH candidates: a refutation counts only when it cites the `file:line` that
disproves the finding, and a finding dies only on a full quorum — every requested refuter
reported and every one of them refuted with evidence — so an uncertain, uncited or dead
refuter leaves it standing. The return is compact — ranked survivors carrying `verification`
and `quorum`, the killed list with its evidence, one-line below-floor entries, counts and
run-level `coverage` — so the coordinator's filtering pass starts from data, the raw
reviewer reports never enter its context, and the run id lands in
`review-verdict.data.workflow_run_id`. **Explore**: `explore-workflow.js` runs the lenses
as `shipgate:code-explorer` agents and merges their essential files, capped at 25; the
orchestrator still reads those files itself. Scripts always receive an explicit `model`
(one tier below the session — the tool would otherwise inherit the session model), and the
bundled-file references in `clarify`, `design`, `review` and `feature` now go through
`${CLAUDE_PLUGIN_ROOT}` so they resolve after a marketplace install. The cost is honest:
the finders cost what the `Agent` fan costs, so the gain is structure, dedupe and context
hygiene rather than fewer tokens, and full verification (`verify: all`) is worth it only on
high-stakes diffs. Implement stays on `Agent` workers (mid-flight `SendMessage`, warm reuse,
environment repair and the shared working tree have no workflow equivalent). A host without
the tool keeps the `agents` path and records a `deviation`.

v0.11.0 — the flow journal made cheap and trustworthy, from two weeks of its own data.
**Cost**: the session brief drops finished work (a stream now ends with `flow-completed`, and a
`capture-done` left alone for 48 h reads terminal; `--all` still shows everything), collapses
streams dormant over a week to one line, caps each stream at its last three gate decisions
(five on the checked-out branch's stream), and puts the checked-out branch's stream first
(`status --branch`, passed by the SessionStart hook); semantic events go up as one `append
--batch` per phase boundary, and a payload over 1 KB is refused so the prose stays in the
worklog and the event carries `refs`. **Position reliability**: a phase-owning event records
the `phase-entered` it implies instead of leaving the brief's headline field to memory (ADR
0002), `append` validates each type's payload against a canonical shape and normalizes the
aliases that had been drifting silently past the gates (`chosen→decision`, `kind→gate`,
`result→outcome`, `tasks→task_ids`, verdict `pass→ready`), and `actor` becomes `role[@label]`
over a closed set of roles, labelled by default from the session id the SessionStart hook
records (ADR 0003) — so who decided, and whether they were asked or were correcting
(`gate-decision.raised_by`), is finally queryable, via the new `stats`. **New gates**:
`mr-opened` is refused unless a `ready` verdict or the user's own `gate=publish` /
`decision=publish` call stands after the last `task-done` — "start the next item" cannot
publish; duplicate `artifact-written` rows (same path, same mtime, under 5 s apart) collapse;
and the Stop hook records its own blocks as `gate-blocked`. **Process**: the config template
gains a `## Worker guardrails` section that `model-tiers` requires pasted word-for-word into
every worker brief (every worker incident so far started as a compressed brief), and streams
are one per issue, named for the branch.

v0.10.0 — gates learned from a colleague's fleet-orchestration process. **Types round**:
design plans a declarations-only task for any slice introducing domain shapes; implement
delivers types with `unimplemented` bodies, gates on a test-inclusive type-check, reviews
the declarations alone, and freezes reviewed signatures (changes escalate + land as
`deviation`). **Parity gate** for ports/migrations: design declares pre-authorized deltas;
review adds a fresh adversarial pass hunting unauthorized behavioral differences across the
whole source artifact. **Review arbitration**: reviewer briefs carry do-not-flag lists and
pre-rulings, killed findings are recorded so they aren't re-litigated, trivial diffs may be
coordinator-gated (recorded as `gate-decision`), and the internal not-ready→fix loop caps
at two rounds before surfacing. **Worker discipline** (model-tiers): self-sufficient
follow-up dispatches, amnesia symptoms → cold-spawn, environment repair is orchestrator
work, briefs point at source artifacts (the artifact outranks the digest) and name a vetted
reference implementation, validation via workspace-level scripts with a baseline run on
shared code. All new gates reuse the existing journal vocabulary — no new event types.

Full history: [CHANGELOG.md](CHANGELOG.md)
