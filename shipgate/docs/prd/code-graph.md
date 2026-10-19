---
type: prd
title: "PRD: Code graph — symbol-level structure from codegraph, detected not configured"
created: 2026-10-19
updated: 2026-10-19
tags:
  - prd
  - shipgate
status: clarified
issue: "none / ad-hoc"
worklog: "./code-graph.worklog.md"
related:
  - ../research/2026-10-19-codegraph-vs-signals.md
  - ../research/2026-09-25-tearags-vs-shipgate.md
  - ./code-signals.md
  - ../adr/0004-code-signals-on-demand-stdlib-script.md
---

# PRD: Code graph

> Give every phase symbol-level structure (callers, impact, the tests a diff reaches) from a
> local code graph when one is on the machine, with no configuration, and keep today's
> behaviour when it is not.

## Problem

`signals.py` gives the flow two kinds of signal. The historical half (churn, fix-rate, age,
ownership) is complete. The structural half is a regex import scanner at file level. It
misses what a parser sees, and it stops at files. The spike
(`docs/research/2026-10-19-codegraph-vs-signals.md`) measured the gap:

- A module loaded by path through `importlib`: the scanner reports **0** dependents. A parsed
  graph reports the 2 test files that exercise it.
- A symbol with two definitions: the scanner has no symbols. The graph lists both, each with
  its callers.
- "Which tests does this diff reach?": the scanner cannot answer. The graph answers in under
  a second from `git diff --name-only`.

A second problem is how shipgate gets its quality. Today it comes from a 15 KB
`.claude/shipgate.md`. A repo with a thin config gets a thin flow. codegraph shows the other
model: it works at its best with no config, and a small config file only tweaks. This
feature is the first instance of that model in shipgate. The direction is logged in
`docs/ledger.md` (2026-10-19).

## Goals & non-goals

**Goals**

- When codegraph is installed, every phase that reads structure gets symbol-level answers:
  Route & Map, Explore, structured-debug, Implement's reuse step, Review. No config line is
  needed for this.
- When codegraph is not installed, every phase behaves as today. One advisory line, once
  per project, says what installing it would add.
- One tool per axis: git history stays with `signals.py`; code structure comes from the
  graph when present. No phase learns two structural tools.
- An umbrella checkout works as well as a single repo, from the same detection.

**Non-goals** (out of scope, decided 2026-10-19)

- Installing codegraph, writing its MCP config, or writing its section into `CLAUDE.md`.
  Those stay the user's choice and codegraph's own installer.
- The MCP seam. shipgate calls the CLI (user decision, 2026-10-19).
- Embeddings or any semantic index. `query` and `explore` are used as they are.
- Cross-service edges across HTTP in an umbrella. Neither tool has them.
- Deleting the regex import scanner this round. It stays as the fallback, frozen. Its
  removal is decided after the eval (SC-007).
- Any work inside hooks. Hooks do not call codegraph.

## Users & stories

- As the orchestrator at Route & Map, I want the impact map to name the symbols a change
  touches, their callers and the tests the diff reaches, so that design and review start
  from what the code says and not from what I grep.
- As a reviewer, I want the tests a diff reaches listed next to the risk table, so that the
  verify gate runs the right tests and the refuters know where to look.
- As the debugger, I want to walk callers from the symptom symbol, so that hypothesis
  formation starts from the call path and not from a grep hit.
- As the implementer in the reuse step, I want to find an existing helper by name and read
  it with its callers in one call, so that I copy the proven one instead of writing a new
  one.
- As a user who has not installed codegraph, I want the flow to run exactly as before, and
  to be told once what I would gain.
- As a user of an umbrella, I want the right child repo's graph used without naming it.

## Functional requirements

**Detection and fallback**

- **FR-001** — shipgate treats codegraph as present when the `codegraph` executable is on
  `PATH` and reports a version at or above the floor the design sets. A `PATH` entry inside
  the repository does not count. An entry inside an umbrella root does not count when the umbrella tracks the `codegraph` file in it, or holds it in its `.git`. An empty or relative `PATH` entry does not count. shipgate then
  continues along `PATH` and uses the next acceptable install. With no acceptable install,
  or with a version below the floor, codegraph counts as absent. The file
  `<repo>/.codegraph/codegraph.db` decides whether the resolved repository has an index. `status --json` runs only after shipgate's own build, to check
  that its `projectPath` is the repository. No config line is read for this.
- **FR-002** — When codegraph is present and the resolved repository has no index, the first
  phase that needs structure builds one (`init`) for that repository, reports the file
  count, time and size once, and continues. Nothing asks the user first.
- **FR-003** — The index never appears in the user's `git status`: the build adds the index
  directory to the repository's local exclude list (`.git/info/exclude`), not to a tracked
  file.
- **FR-004** — When codegraph is absent, every phase produces the output it produces today.
  One advisory line, printed once per project and never in a hook, names what installing
  codegraph would add. A failing or unparseable codegraph call degrades the same way, with
  its reason, and never blocks a phase.
- **FR-005** — Before a phase queries the graph it checks for a live codegraph daemon for
  the resolved repository (the MCP server's file watcher, which auto-syncs each change in
  under a second). When one is alive it queries at once. When none is alive it syncs first,
  so answers describe the working tree and not the last index.

**Axis split**

- **FR-006** — Historical signals (commits, fix-rate, age, staleness, author counts,
  `suspects`) come from `signals.py` and git in every case. codegraph does not replace
  them.
- **FR-007** — Structural signals (fan-in, fan-out, blast radius) come from the graph when
  present and from the regex scanner when not. Consumers receive one output shape. The
  output states its source (`graph` or `regex`), so a report can say which it used.

**New capabilities per phase**

- **FR-008** — Route & Map carries, when present: the transitive importers of the diff, the
  impact of each exported symbol the diff changes, and the test files the diff reaches.
- **FR-009** — Review carries the test files the diff reaches, next to the per-file risk
  table, and the verify gate is told to run them.
- **FR-010** — structured-debug may walk callers and callees from a symptom symbol and cite
  the result as `[graph]` evidence, next to the `[signals]` suspect list.
- **FR-011** — Implement's reuse step searches the graph for an existing symbol by name and
  by synonym before writing new code, and reads a candidate with its callers in one call.
- **FR-012** — Explorer and worker briefs name the graph commands available to them, and
  say that an `explore` or `node` result counts as a read of the files it prints.

**Umbrella**

- **FR-013** — In an umbrella, the repository resolved for the change (the same rule the
  journal and `signals.py --repo` use) owns the index. One index per child repository is
  the default. A child without an index is built per FR-002.
- **FR-014** — A root-level index over all children is an opt-in. It needs one config line
  and the user's own `codegraph.json` with the exclude list for nested clones. shipgate
  documents the layout with the measured costs; it does not build it.

**Configuration**

- **FR-015** — The only configuration is one optional line under `## Code tooling`:
  `Code graph: auto | off | root`. `auto` is the default and the behaviour above. `off`
  forces the regex fallback. `root` selects FR-014. The setup skill writes nothing for the
  default.
- **FR-016** — shipgate's own codegraph invocations run with telemetry disabled through the
  environment. The user's own use of codegraph is unaffected.

**Boundaries**

- **FR-017** — shipgate never installs codegraph, writes MCP configuration, or edits
  `CLAUDE.md`, `AGENTS.md` or any tracked file on the user's behalf.
- **FR-018** — Reports and journal events carry paths inside the repository, counts and
  symbol names. They never carry author names (same rule as `signals.py`).
- **FR-019** — The eval suite gains an ablation arm with and without codegraph on the five
  cases of the 2026-09-25 note: bug localization, reuse detection, blast radius,
  risk-ranked review, and the negative one-line case.

## Success criteria

- **SC-001** — On a repository with codegraph on `PATH` and no `## Code tooling` line, Route
  & Map's impact map contains symbol-level impact and the tests the diff reaches, with no
  user action and no question asked.
- **SC-002** — `blast` on a module loaded by path (the hooks' shared module in this repo)
  returns at least the 2 test files that load it. Today it returns 0.
- **SC-003** — With codegraph absent, every phase's output is identical to today's except
  one advisory line, and that line appears at most once per project.
- **SC-004** — The added cost per phase call (sync plus query) is at most 5 s on a
  1,500-file repository and at most 10 s on the largest child of the umbrella, measured.
- **SC-005** — After an automatic index build, `git status --porcelain` in that repository
  shows no new entry.
- **SC-006** — In the umbrella, a change in one child repository is answered from that
  child's index. A symbol defined once in the child returns exactly one definition.
- **SC-007** — *(amended 2026-10-19, user decision after the eval)* In the eval, the
  with-codegraph arm scores at least as high as the without arm on every case within
  noise, every with-plugin run that calls the signals reports `structure.source: graph`,
  `blast.tests` is present on the cases that have tests, and the negative case makes no
  codegraph call. Signal correctness is measured directly: on the 500-file workspace
  fixture the graph reaches 56 of 59 true files, the regex scanner 2 of 59. The original
  clause "higher on blast radius and reuse detection" is withdrawn: the measured eval
  (research note, "Eval result") shows equal end answers, because a strong model writes
  its own resolver when the regex number looks wrong, and a name-matching index cannot
  do semantic reuse detection.
- **SC-008** — No hook's run time changes. No hook calls codegraph.
- **SC-009** — A failing codegraph call (killed binary, corrupt index) leaves the phase
  with the regex output and one reason line, exit 0, in a test.

## Constraints & assumptions

- codegraph is a third-party CLI at v1.6. Only `impact` and `files` have `--json`; other
  commands are text. The design must parse text for `affected` and `node`, or ask upstream
  for `--json`. **Risk:** output format drift between versions. The version floor (FR-001)
  and a parse-failure test (SC-009) bound it.
- codegraph's `status <path>` walks up to an indexed ancestor. Under an umbrella with a root
  index it answers for the root, not for an unindexed child. So `status` never decides
  whether a repository has an index (worklog, deviation "T13 live finding").
- FR-002 and FR-013 build or use only an index that the repository does not supply itself.
  An index is refused with the reason `graph-index-untrusted` when `.codegraph`,
  `.codegraph/codegraph.db` or `.codegraph/.gitignore` is a symlink, when `.codegraph`
  resolves outside the repository, when git tracks a file under it other than
  `.codegraph/.gitignore`, or when a directory spelled like `.codegraph` in another case
  exists, tracked or not. The regex scanner then runs (worklog, Review rounds 1 and 2).
- Measured on one machine: index 5 s / 8 MB (104 files), 7 s / 125 MB (1,469 files),
  87 s / 680 MB (umbrella root with excludes). Sync per child 0.7–2.4 s; umbrella root
  55–66 s. These numbers decided FR-013.
- The file watcher lives in the MCP server process (`codegraph serve --mcp`). While it runs
  for a project, every change is re-indexed in 36–249 ms (measured) and CLI queries see it.
  `init`, `sync`, `status` and `query` start no watcher. A CLI query against a project with
  no live daemon does not sync and does not warn when stale (measured). FR-005 follows:
  daemon alive → query; otherwise sync, then query.
- codegraph honours `.gitignore`. `includeIgnored` re-includes nested repos at every depth,
  so a root index needs an `exclude` list (ledger, 2026-10-19).
- Telemetry is on by default in codegraph (anonymous counts, no paths). FR-016 follows.
- The plugin contract (ADR 0004) stays: stdlib-only scripts, no hard dependency, hooks that
  no-op when not applicable. codegraph is detected, never required.

## Assumptions (executive)

- Which seam, CLI or MCP? → CLI — user decision; the MCP server exposes one tool by default
  and needs a root index in an umbrella.
- Required or optional? → detected, with automatic index build; never required — user
  decision; keeps "Claude Code is all you need" while giving the full flow to anyone with
  the binary.
- Umbrella default, per child or root? → per child — a root sync costs 55–66 s per call
  without the daemon; a child sync costs 0.7–2.4 s.
- Sync policy? → query at once when the project's daemon is alive, else sync first — user
  pointed at the watcher; measured: the watcher runs only inside `serve --mcp`, a stale
  CLI query without it returns in 0.2 s with no warning.
- Keep or delete the regex scanner? → keep as fallback, frozen — delete only after SC-007
  proves the graph covers the eval; the user does not want two structural engines long
  term.
- Who calls codegraph, the skills or `signals.py`? → left to design — the PRD fixes one
  output shape (FR-007); the design picks where the adapter lives.
- Telemetry on shipgate's own calls? → off through the environment — the user did not opt
  into a third party's stats by installing a plugin.
- Does shipgate write the MCP config or the `CLAUDE.md` section? → no — those change what
  other sessions see; the user runs `codegraph install` if they want them.
- Version floor? → 1.6, the version measured; design may raise it if a needed flag is newer.
- Where does "advisory once per project" remember itself? → design decides (journal or a
  marker under the project's `.claude/`); the requirement is only "once".

## Open questions

None. The gate is passed.
