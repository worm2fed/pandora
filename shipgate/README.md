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

Ceremony scales to the change: a one-line bugfix goes Workspace → Route & Map → fix → verify; a real
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
their defaults; subagents get the relevant excerpts pasted into their briefs.
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
| Writing style | whether the documents shipgate writes into the repo and forge (PRD, ADR, worklog, ledger, MR/PR body, tracker comments) follow the STE-80 "Writing for people" rule (`ste-80`) or keep plain prose; reports to the person driving the flow follow the rule regardless | `plain` |
| Security-sensitive areas | domains that trigger the full `/security-review` | auth, secrets, payments |
| Debug evidence sources | prod/QA log-query skill, CI-log integration | local logs, tests, debugger |
| Epic workflow | epic decomposition command, ordering, delivery rules | issue-by-issue, manual decomposition |
| MR watcher | a project skill that watches open MRs/PRs + the command to register a blocker/follow-up on its watch list | no watcher — the flow ends at "MR/PR opened" |
| Code tooling | the library-docs tool/MCP to consult for a dependency's current API, and the LSP tool for symbol navigation | training knowledge / WebFetch; grep-and-read |
| Code signals | window, fix-commit pattern and extra excludes for the bundled risk signals (the one section a script reads, not the model) | 12-month window, built-in fix pattern and excludes |
| Worker guardrails | the project's hard rules, pasted verbatim into every worker brief | only the built-in worker discipline (branch check, no staging, evidence) |
| Orchestration | whether Review / Explore fan out via bundled `Workflow` scripts or `Agent` subagents | `agents` for both |
| Thinking lenses | which lens *skills* to invoke at which phase, overriding the inline bullet (e.g. one from [cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills)); a large lens plugin costs skill-listing space in every session, so map only what you need | no lens skills invoked — the phase skills apply each lens inline |
| Autonomy | `ask` vs `executive` — whether the orchestrator answers routine gate questions itself (and records them) | `ask` — every gate question goes to the user |

## What's inside

**Command**

- `/shipgate` — entry point; drives the `feature` orchestrator.

**Skills**

- `feature` — orchestrator: detects phase from artifacts, routes, owns escape hatches, drives epics issue-by-issue.
- `setup` — bootstrap: detects the repo's shape, interviews with recommended defaults, writes `.claude/shipgate.md` + its generated `.claude/shipgate.json` sidecar, and initializes the flow journal. Re-run to update.
- `workspace` — the first phase: get onto the right branch (`<type>/<issue-id>-<slug>`) off a clean base before any work; never builds on the wrong checkout — and never on an umbrella repo.
- `route-and-map` — reads CLAUDE.md (root + each touched module) + the knowledge base, emits an impact map. Also answers a standalone "what does this change affect?".
- `clarify` — the Clarify gate: coverage scan, prioritized questions, writes the PRD (FR-###/SC-###).
- `design` — parallel architects → recommendation → ADR(s) + worklog (Design + Build Plan).
- `implement` — reuse-first execution, breaking-change discipline, per-task `verify`.
- `review` — parallel reviewers report everything scored (coverage over self-filtering); a separate orchestrator pass filters at ≥80 confidence. Plus CLAUDE.md compliance, acceptance-criteria check, final `verify`. Also answers a standalone "rank the changed files by risk", and the re-review after a round of fixes ("I've addressed F1 and F2 — good to push?"), scoped to the fix diff.
- `verify` _(cross-cutting)_ — no "done" without fresh command evidence.
- `model-tiers` _(cross-cutting)_ — the orchestrator never types product code; implementation goes to worker subagents one tier below the session but never below Opus, and only very mechanical sub-work sinks to the cheapest capable tier.
- `knowledge-base` _(cross-cutting)_ — recall/capture durable knowledge, routed by type to the stores the project config declares (default: repo docs). Named to avoid colliding with Claude's built-in session memory.
- `structured-debug` — on-demand: evidence-first debugging for bugs, regressions, incidents — a pasted stack trace with no repo access included, and a report that says "just fix it" (the fix still waits for an approved plan). Also answers a standalone "which file has the defect?".

Security, simplification, and test-first are folded into the flow rather than living as
separate skills: the `code-reviewer` agent carries a security + simplicity lens, `implement`
writes the failing test first, and Claude Code's built-in `/security-review` and `/simplify`
cover dedicated audits/cleanups.

**Thinking lenses** are folded in the same way — a few lines in the phase that needs them,
each with the condition under which it applies, so they fire at the right moment and cost
nothing in the skill listing: `design` (reversibility, pre-mortem, steel-manning, second-order,
via-negativa, TRIZ, margin-of-safety), `structured-debug` (occam's-razor, kepner-tregoe,
five-whys-plus, map-territory, OODA, systems), `feature` (Cynefin, to scale ceremony by
uncertainty as well as size), `clarify` (jobs-to-be-done, first-principles), `implement`
(sunk-cost, bounded-rationality), `review` (steel-manning on a disputed finding),
`knowledge-base` (circle-of-competence), and the `code-reviewer` agent (red-team / inversion).
The lens text is condensed from [cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills)
(MIT, © 2025 TJ Boudreaux) — see `NOTICE`.

**Subagents** (the engine, run in parallel)

- `code-explorer` — grounded exploration, file:line, essential-files list; reads refs that are not checked out and the history with read-only git (the orchestrator fetches first).
- `code-architect` _(opus)_ — one committed design philosophy per instance.
- `code-reviewer` _(opus)_ — every finding scored (confidence + severity), file:line; the orchestrator filters.

**Scripts** (Python 3 stdlib)

- `scripts/journal.py` — the flow journal CLI; `scripts/signals.py` — per-file risk signals, read by `route-and-map`, `review` and `structured-debug` (see [Code signals](#code-signals)).

**Glossary** — [`docs/glossary.md`](docs/glossary.md): one term per shipgate concept, what it means and what it is not to be confused with. Prose in this plugin uses those terms and no synonyms. Every report a person reads follows the **Writing for people** rule (short sentences, one idea each, every fact kept; ADR 0006); the `Writing style` config section extends it to the documents shipgate writes into your repo.

## Artifacts (3 per feature)

Homes are set by the config's Knowledge base section; defaults shown:

- `docs/prd/<name>.md` — PRD: what & why (FR-###, SC-###). No implementation.
- `docs/adr/NNNN-<title>.md` — one ADR per genuine decision fork. Immutable; supersede.
- `docs/prd/<name>.worklog.md` — one worklog next to its PRD: **Design** section +
  **Build Plan** section (tasks with tests, `[P]` markers, progress). Tests are tasks, never
  a separate doc.

## Knowledge base

`knowledge-base` routes durable knowledge **by type** to its natural home, rather than dumping
everything in one store. The stores themselves come from the project config — a team wiki
over MCP, in-repo docs, or both; without config:

- **Engineering** — decisions, PRDs, conventions, gotchas, root causes → the **repo**
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
something re-inferred from artifacts every session. The SessionStart hook injects the status brief —
led by the stream this session last wrote to (`--session`, marked `· this session`: what a
compacted or resumed session was driving, branch or no branch), then the checked-out branch's;
`scripts/journal.py` is the whole interface:

| Command | Does |
| --- | --- |
| `status [--session ID] [--branch B] [--nested-branch B …] [--feature SLUG] [--all]` | the status brief: the stream the session drives first (`--session`: the live stream that session last wrote to itself, hook-written events not counted — it may have no branch, and parallel sessions each get their own), then the checked-out branch's, both in full; dormant streams as one line, completed ones hidden unless `--all`; in an umbrella the nested repos' branches (`--nested-branch`, repeatable) stand in when `--branch` names no stream, the most recently active match first |
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
the appending session — `CLAUDE_CODE_SESSION_ID` from the shell's environment (a subagent's shell
carries its parent's), else the session that started last (ADR 0005). A stream ends with `flow-completed` and leaves the status brief.

Each phase skill names its stream before it works — the branch the work takes, per the
config's **Branching** pattern, opened with `flow-started` by whichever skill runs first when
the status brief lists no such stream (`workspace` then continues on it) — and appends its event in the
step that establishes the fact: the map emitted, the defect reproduced, the root cause
confirmed, the worklog written, the verdict stated. Not at the end of the turn, and never
skipped for want of a branch. The Stop hook enforces the build-side gates only (`task-done`,
`verify-run`, clarify's `gate-decision`); the phase events rely on those steps.

## Code signals

Per-file risk computed from the code and its history, on demand, by
`scripts/signals.py` — no index of its own, no cache. One `git log` pass gives each
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
| `graph ACTION ARGS…` | one codegraph query: `impact`, `callers`, `callees`, `affected`, `query`, `node` or `explore` (see **Code graph**) |

Common flags: `--repo`, `--scope`, `--window`, `--fix-pattern`, `--exclude`, `--json`; they
override the `## Code signals` config section. `--graph auto|off|root` overrides the
`Code graph` bullet under `## Code tooling`. Consumers: `route-and-map` (a **Risk signals**
block in the impact map, essentials in the journal), `review` (a per-file risk table in the
brief, and `fileRisk` for the workflow's refuter ordering), `structured-debug` (a suspect
list cited as `[signals]` evidence), `implement` and `design` (prefer the proven precedent),
and optionally explorer and worker briefs. No git, a shallow clone, an empty history or no
adapter → one line saying why, exit 0, the phase runs as before. Output carries counts and
shares, never author names.

### Code graph

When the [codegraph](https://github.com/colbymchenry/codegraph) CLI is on `PATH`, the
structure half comes from its index instead of the regex scanner. Nothing needs to be
configured. The first call on a repository with no index builds one. A repository with more
than 10,000 tracked files is not indexed automatically; one advisory line names the command.
Before each query, shipgate syncs the index, unless a codegraph MCP server already watches
the repository. shipgate finds that server through the `socketPath` in
`.codegraph/daemon.pid`, because codegraph puts the socket in the temp directory when the
project path is long. The JSON says which source ran: `structure.source` is `graph` or
`regex`, and `structure.graph` carries the state and the reason.
`structure.graph.index_root` is relative to the repository: `.`, or `..` in root mode. A
codegraph call that fails gives the regex result, one reason line and exit 0. With codegraph
absent, every phase runs as before, plus one advisory line, once per project.

shipgate uses only a codegraph binary you installed. It skips a `PATH` entry that sits
inside the repository. It skips an entry inside an umbrella root only when the umbrella tracks the `codegraph` file in it, or holds it in its `.git`. It also skips an empty or relative `PATH` entry. After a skipped entry,
shipgate continues along `PATH` and uses the next acceptable install.

shipgate refuses an index that the repository itself supplies, with the reason
`graph-index-untrusted`. That happens in these cases:

- `.codegraph`, `.codegraph/codegraph.db` or `.codegraph/.gitignore` is a symlink, or git tracks it as one.
- `.codegraph` resolves outside the repository.
- git tracks a file under `.codegraph/` other than codegraph's own `.codegraph/.gitignore`.
- A directory spelled like `.codegraph` in another case, such as `.CodeGraph`, exists,
  tracked or not.

To use the code graph again, remove the symlink, untrack those files, or rename or remove
the `.CodeGraph`-style directory. The reason `graph-empty` means the index holds none of the
files this call asks about, after `--scope` and `--exclude`. Both reasons give the regex
result.

What it does not add: a higher eval score. In shipgate's own evals the two arms score the
same, because the model compensates for a weak regex number by writing its own resolver. The
gain is in the signals themselves (56 of 59 true importers from the graph, 2 of 59 from the
regex scanner on a 500-file workspace fixture), in the tests a diff reaches, and in the symbol
queries. The measurement is in `docs/research/2026-10-19-codegraph-vs-signals.md`.

What the code graph adds, per phase:

- `route-and-map`: the tests the diff reaches (`blast.tests`), and `graph impact` for each
  changed exported symbol.
- `review`: the tests the diff reaches, under the risk table. The verify gate runs them.
- `structured-debug`: `graph callers` and `graph callees` from the symptom symbol, cited as
  `[graph]` evidence. `suspects` still ranks by history.
- `implement`: `graph query` for the name and two synonyms, then `graph node` to read the
  best candidate with its callers.
- `design`: `graph callers` shows who already uses each precedent.
- Explorer and worker briefs: `graph explore`, `graph node` and `graph callers` before grep.
  An `explore` or `node` result counts as a Read of the files it prints.
- `workspace`: a new worktree gets a copy of the source checkout's index, and the next
  query syncs it. That took 1.2 s on this repository, less than a fresh build.

Put the shipgate flags before the action, because everything after it goes to codegraph:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" graph --repo <repo> --json impact <symbol> -f <path>
```

With `--json`, the answer is `{version, available, source, command, args, graph, result,
result_text, not_found}`. For `impact`, `callers`, `callees`, `affected` and `query`,
codegraph prints text, not JSON, when it does not know a symbol. That answer is still
`available: true`: `result` is null, the text is in `result_text`, and `not_found` is `true`.
For `node` and `explore`, the answer is always text, so the text is in `result`. Then
`not_found` says whether that text reports a symbol or code that was not found. When the graph is unavailable, the answer is `available: false` with a
reason, and no codegraph call runs.

Measured costs, one machine, one run each:

| Index | Files | Build | Size |
| --- | --- | --- | --- |
| this plugin repository | 104 | 5 s | 8 MB |
| one backend service | 1,469 | 7 s | 125 MB |
| an umbrella root of 28 child repos, nested clones excluded | — | 87 s | 680 MB |

A `sync` takes 0.7–2.4 s per child repository. In an umbrella, each child repository owns its
own index, and every call names the child with `--repo`.

The only configuration is one optional bullet under `## Code tooling`:
`Code graph: auto | off | root`. `auto` is the default. `off` always uses the regex scanner.
`root` uses an index at the umbrella root, which you build yourself with your own
`codegraph.json` and its exclude list for nested clones. shipgate never builds a root index.
**Root mode needs the codegraph MCP server running.** Without it, a `sync` on the root takes
55–66 s, the 30 s call timeout stops it, and the regex scanner runs. In `root` mode, the
`graph` passthrough returns codegraph's own output, so its paths are relative to the umbrella
root, not to the child repository. The `--graph` flag overrides the bullet for one call.

What shipgate writes, and only when codegraph is involved:

- `.codegraph/`, written by codegraph itself when shipgate builds the index.
- One `/.codegraph/` line in `.git/info/exclude`, only for an index shipgate built.
- Small files under `.git/shipgate/`: the build lock and two advisory markers, so each
  advisory shows once. With codegraph absent, only one advisory marker is written, once.

shipgate never installs codegraph, never writes MCP configuration and never edits
`CLAUDE.md`. Every codegraph call shipgate makes runs with telemetry off
(`CODEGRAPH_TELEMETRY=0`). No hook calls codegraph. ADR 0007 records the design.

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
| a knowledge base MCP (named in config)                                    | MCP                   | team/product knowledge — recall & store in a wiki/vault                                                                                                               | recall falls back to repo docs (`CLAUDE.md`, ADRs) |
| forge CLI + tracker MCP (`gh` / `glab`, named in config)               | CLI/MCP               | `clarify` seeds the PRD from the issue; `review` opens the MR/PR and checks its acceptance criteria                                                                | capture the issue link manually; push by hand      |
| a log-query skill (named in config)                                    | skill                 | prod/QA log evidence in `structured-debug`                                                                                                                         | use `docker logs` / local sources                  |
| `chrome-devtools-mcp`                                                  | MCP/skill             | frontend/browser evidence in `structured-debug`                                                                                                                    | use other evidence sources                         |
| `/security-review`, `/simplify`                                        | Claude Code built-ins | deep security audit / standalone cleanup                                                                                                                           | ship with Claude Code already                      |
| the `Workflow` tool (Claude Code built-in; config `## Orchestration`)  | Claude Code built-in  | Review and Explore fans run as bundled scripts: schema-typed findings, in-script dedupe, evidence-required refuters on review's top findings                       | the `Agent` fan, as before                         |
| an MR/PR-watcher skill (named in config)                               | skill                 | `review` registers blockers/follow-ups on the watch list; watcher events resume the flow at the phase they unlock                                                  | flow ends at "MR/PR opened"; resume manually       |
| `codegraph`                                                            | CLI on `PATH`         | symbol-level impact, callers, the tests a diff reaches, `explore` (see **Code graph**)                                                                              | the regex import graph; one advisory line, once    |

The plugin also expects the repo to carry **`CLAUDE.md`** files (root + nested where relevant) —
that's how `route-and-map` decides where code belongs. Repos without them still work; routing is
just less informed.

## Backlog

- **Narrow `code-explorer`'s shell to read-only git.** Since 0.14.6 the agent has plain `Bash`,
  limited to read-only git by its prompt only — a prompt-injected instruction in the repo it
  reads could ask for more, and the user's permission settings are then the only guard (the
  same holds for `code-reviewer`). If agent frontmatter `tools:` accepts permission patterns,
  grant `Bash(git show:*)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Bash(git grep:*)`,
  `Bash(git blame:*)` and `Bash(git ls-tree:*)` instead, and keep the contract test in
  `tests/test_workflow_scripts.py` in step. Raised by the security review of 0.14.7.
  Recorded 2026-10-08.

## Status

Release notes, newest first, live only in [CHANGELOG.md](CHANGELOG.md). The current version
is in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).
