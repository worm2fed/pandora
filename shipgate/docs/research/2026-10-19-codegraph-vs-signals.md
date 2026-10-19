---
title: codegraph vs the bundled code signals — a spike
date: 2026-10-19
status: research note — informs a PRD/ADR, decides nothing by itself
sources:
  - https://github.com/colbymchenry/codegraph
  - ./2026-09-25-tearags-vs-shipgate.md
  - ../prd/code-signals.md
---

# codegraph vs the bundled code signals

## Why this note

The 2026-09-25 note split "code intelligence" into three axes: historical, structural,
semantic. The code-signals PRD then shipped `scripts/signals.py`. It covers the historical
axis in full and the structural axis at file level. Its non-goals parked symbol-level
structure (call graphs, impact) and any external provider.

codegraph is a local code knowledge graph (MIT, tree-sitter, SQLite). This spike measured
it on a plugin repo and on an umbrella of 28 child repos, and compared its answers with
`signals.py` on the same inputs. All numbers below come from one machine, one run each.

## What codegraph is

| Property | Value |
| --- | --- |
| Index | `.codegraph/codegraph.db` (SQLite + FTS5) per project; self-ignoring `.gitignore` inside |
| Parser | tree-sitter, 34 languages; functions, classes, methods; call, import, extends, implements edges; route nodes for web frameworks |
| Sync | file watcher inside the MCP server process (`serve --mcp`); re-indexes a changed file in 36–249 ms (measured); `init`, `sync`, `status`, `query` start no watcher; `codegraph sync` by hand: 0.7–2.4 s per service, 55–66 s at the umbrella root; `CODEGRAPH_NO_DAEMON=1` disables the daemon |
| CLI | `init`, `index`, `sync`, `status`, `query`, `explore`, `node`, `callers`, `callees`, `impact`, `affected`, `files`; every command takes `-p <project>` |
| MCP | `codegraph serve --mcp` (stdio); exposes `codegraph_explore` by default, the rest via `CODEGRAPH_MCP_TOOLS` |
| Config | `codegraph.json`: `include`, `exclude`, `deprioritize`, `extensions`, `includeIgnored` |
| Install footprint | the `install` command writes MCP config and a marker section into `CLAUDE.md`; `init` writes only `.codegraph/` |

## Axis coverage

| Axis | `signals.py` | codegraph |
| --- | --- | --- |
| Historical: churn, fix-rate, age, ownership | yes | no |
| Structural, file level: importers, blast radius | yes, TS/JS/Python/Go by regex | yes, 34 languages, by parse |
| Structural, symbol level: callers, callees, impact | no | yes |
| Tests reached by a diff | no | `affected --stdin` |
| Semantic: find code by meaning | explorers + grep | `query`, `explore` (FTS, no embeddings) |
| Dependencies | none | the CLI, one index per project, a watcher daemon |

The two tools do not overlap on the historical axis. codegraph is a superset on the
structural axis and adds a cheap semantic layer. It does not replace `signals.py`.

## Measurements

### Index cost

| Project | Files | Nodes | Edges | Wall time | Index size |
| --- | --- | --- | --- | --- | --- |
| this plugin repo | 104 | 2,062 | 6,715 | 5 s | 8.3 MB |
| one backend service of the umbrella | 1,469 | 25,703 | 69,215 | 7 s | 125 MB |
| umbrella root, 28 child repos opted in | 36,232 | 465,437 | 1,205,789 | 231 s | 2.0 GB |
| umbrella root, nested clones excluded | — | 165,166 | 448,812 | 87 s | 680 MB |

Queries against the 2.0 GB root index (`query`, `impact`, `affected`, `node`) each took
0.7 s to 0.9 s. Query time does not depend much on index size.

### Answers compared on the same input

1. **A file loaded by path, not by import.** The plugin's hooks load a shared module through
   `importlib` by file path. `signals.py blast` on that module: **0 files**. The regex
   import scanner cannot see the load. `codegraph affected` on the same module: the **2 test
   files** that exercise it. A real gap, closed.
2. **A symbol defined twice.** `codegraph impact` on a helper name that two scripts each
   define returned both definitions, each with its own callers, and flagged the result
   `ambiguous`. `signals.py` has no symbol level.
3. **A plain TS import chain.** `signals.py blast` on one TS module: 4 files, 2 of them
   transitive. codegraph `node` on the same file: the 2 direct dependents. codegraph
   `affected`: the same 2 test files. Same graph, different cut. No disagreement.
4. **Tests reached by a diff.** `git diff --name-only <base> | codegraph affected --stdin`
   returned the one test file the last three commits reach, in under a second. That is the
   shape the review phase needs.
5. **A service file in the umbrella.** `affected` on a feature-flag client module listed 4
   test files; `impact` on its factory function listed 20 affected symbols per definition.

## Umbrella layout

The umbrella's `.gitignore` lists its child repos (`source/**`). codegraph honours
`.gitignore`, so a plain `codegraph init` at the root indexes nothing under `source/`.
`codegraph.json` with `includeIgnored: ["source/"]` opts the children back in. Two layouts
are therefore possible, and the spike ran both.

| | One root index | One index per child repo |
| --- | --- | --- |
| Index | 231 s, 2.0 GB, one watcher over 36k files | 7 s, 125 MB per service; a watcher per service that has one |
| Session at the umbrella root | the MCP server finds the index from `rootUri`; `explore` works with no flag | the MCP server finds no index; every call needs `-p <child>` |
| Cross-repo edges | only where one repo imports another's source; none across HTTP | none |
| Nested clones | **hazard**: a child repo that holds gitignored clones of other services got them indexed too; `includeIgnored` re-includes nested repos at every depth, not only the direct children. One factory function came back with 4 definitions, 3 of them copies. An `exclude` list for those paths fixed it: 1 definition, 65 % fewer nodes, 87 s and 680 MB instead of 231 s and 2.0 GB | not an issue; each repo is its own project |
| Duplicates in answers | `impact` and `query` are `ambiguous` until the clones are excluded | none |

Observations that decide the shape of an integration:

- shipgate already resolves the nested repo for a change (the journal's `--nested-branch`,
  `signals.py --repo`). The same resolution gives codegraph its `-p`. So the **CLI seam
  works in both layouts**; the MCP seam works only with a root index.
- The root index pays 680 MB and a 90-second rebuild (2.0 GB and 4 minutes before the nested clones are excluded) to serve `explore` without a flag. The
  per-service index pays nothing it does not use. A config line can name either.
- Cross-service calls go over HTTP in this umbrella, so neither layout links a client call
  to the route it hits. Route nodes exist per repo; the bridge would be a shipgate
  convention, not a codegraph feature.

## Where each phase would use it

| Phase | Today (`signals.py`) | With codegraph present |
| --- | --- | --- |
| Route & Map | `blast --diff <base>`: file-level transitive importers | plus `impact <symbol>` for the symbols the change touches; `affected --stdin` for the tests it reaches |
| Explore | explorers grep | explorer brief carries `explore <query>` as the first move; the tool returns source grouped by file, so the brief must say "treat it as a Read" |
| structured-debug | `suspects` by fix-rate × recency × proximity | plus `callers <symbol>` to walk from the symptom; `suspects` still ranks, codegraph does not know history |
| Implement (reuse step) | grep before writing | `query <name>` with synonyms; `node <symbol>` to read the proven helper with its callers |
| Review | `hotspots --diff` ranks files; the workflow orders refuters by `fileRisk` | plus `affected --stdin` names the tests the diff must run; `impact` per changed exported symbol |

The historical axis stays with `signals.py` in every row. codegraph adds the symbol and
test columns.

## Contract fit

- **No dependency.** The plugin's contract (ADR 0004) is stdlib-only scripts and hooks
  that no-op when not applicable. codegraph is an install plus a daemon. So it is an
  **optional, config-named integration**, the posture the 2026-09-25 note set for any
  external provider. The no-op path is one test: `.codegraph/codegraph.db` absent in the
  resolved project → the phase runs as today.
- **CLI, not MCP, as the seam.** Scripts, workflow refuters and worker briefs can shell
  out the same way they call `signals.py`; the output is text or `--json`. The MCP server
  stays the user's choice for interactive use. Only `codegraph_explore` is exposed by
  default, and the rest need an environment variable, so a skill cannot assume the MCP
  tools exist.
- **Staleness.** The watcher keeps the index current while the MCP server runs for that
  project; `.codegraph/daemon.pid` names the live process. Without it, a CLI query answers
  from the last index in 0.2 s with no banner (measured). A phase that calls the CLI checks
  for the daemon and runs `sync` only when there is none: 0.7–2.4 s per service.
- **Privacy.** `init` writes only `.codegraph/`. Telemetry is on by default (anonymous
  counts, no paths); `codegraph telemetry off` disables it. The install command writes into
  `CLAUDE.md`; the spike did not run it.

## Open questions for the PRD

1. Which commands are worth a config contract: `affected --stdin` and `impact` are the
   clear wins; `explore` competes with the explorers and needs an eval.
2. Umbrella default: per-child index with `-p` from the resolved repo (cheap, no
   duplicates) or a root index (one `explore` surface). Recommendation: per-child by
   default, root as an opt-in line in `## Code tooling`.
3. Sync policy: `codegraph sync -p <repo>` before each phase call, or trust the daemon.
4. Whether `signals.py` should learn to call codegraph for structure when present, or the
   skills call both. The script already has the repo resolution and the no-op path.
5. The eval: the 2026-09-25 note's five cases still apply; case 3 (blast radius) and case 2
   (reuse detection) are the ones codegraph should move.

## Recommendation

1. Integrate codegraph as an optional `## Code tooling → Code graph` entry. Phases call
   the CLI through the resolved project path; absent index → today's behaviour.
2. Keep `signals.py` for the historical axis and as the structural fallback.
3. Umbrella: per-child indexes by default; document the root layout with its `exclude`
   list for nested clones as the opt-in.
4. Run the eval before the integration ships as a default recommendation.

## Eval result (added 2026-10-19, after the build)

Two arms (codegraph on `PATH` vs removed), three runs each, nine cases, $31 in total.

| Case | Graph arm | Regex arm | Reading |
| --- | --- | --- | --- |
| 08–14, 71 (existing, small fixtures) | 1.00 | 1.00 | at the ceiling; the bare model reads everything |
| 72: 500-file workspace monorepo, 44 importers + 15 tests behind one hub | 0.88 ×3 | 0.88 / 1.00 / 0.88 | graph: 43/44, misses a second-hop barrel re-export; regex arm: the agent distrusts "2 files" and writes its own resolver |
| 73: hidden helper, no "retry"/"backoff" anywhere | 1.00 | 1.00 | `query` matches names, not meaning; nothing for the graph to add |

Turns and cost on 72: 14/10/12 turns, $1.48 (graph) vs 13/10/13 turns, $1.55 (regex).
The signals themselves differ a lot (graph 56/59 files vs regex 2/59 on the same fixture);
the agent's final answer does not. What the code graph buys in shipgate is a correct,
deterministic structural answer in 2 s, the tests a diff reaches, and symbol queries, not
a higher eval score and not fewer turns. Semantic reuse detection stays out of reach for a
name-matching index. The 2026-09-25 prediction ("the setup column makes it unjustifiable as
a default") is half right: the setup cost is small with auto-init, and the answer-quality
gain is absent on these cases.
