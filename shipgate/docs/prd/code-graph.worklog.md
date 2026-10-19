---
type: worklog
title: "Worklog: Code graph"
created: 2026-10-19
updated: 2026-10-19
tags:
  - worklog
status: done
prd: "./code-graph.md"
related:
  - ../adr/0007-codegraph-as-detected-structure-provider.md
  - ../adr/0004-code-signals-on-demand-stdlib-script.md
  - ../research/2026-10-19-codegraph-vs-signals.md
---

# Worklog: Code graph

> Design + build plan companion to `./code-graph.md`. Issue: none / ad-hoc. Branch
> `feat/codegraph-integration`. Target version: shipgate 0.17.0.

---

# Design

## Approach

Minimal-change placement with the clean-architecture seam: the provider swap happens at
the one place `analyse` builds the `Graph`; all codegraph knowledge sits in one private
module. File edges come from a read-only SQLite read (28 ms), tests and symbols from the
CLI. The trade-off is a coupling to codegraph's private schema, bounded by a probe and the
regex fallback. See ADR 0007 for the forks and the measurements.

## Architecture

```
skill ──► signals.py {hotspots|blast|suspects|graph} [--repo R] [--graph auto|off|root]
             │
             ├─ probe(repo) · load_config (Code signals + Code tooling → code_graph)
             │
             ├─ _codegraph.select(repo, mode)            # scripts/_codegraph.py
             │     off ─────────────────────────────► Regex(no advisory)
             │     which/version/status fail ───────► Regex + advise_once()
             │     no index, ≤10k files ────────────► exclude → init -y (lock) → built
             │     no index, >10k files ────────────► Regex + advisory "run codegraph init"
             │     root mode, no umbrella index ────► Regex, reason graph-root-not-indexed
             │     daemon.pid alive ─► query now  ·  else ─► sync -p R
             │     open db ro|immutable · probe schema_versions, columns
             │        └─ fail ───────────────────────► Regex, reason graph-schema|graph-db
             │
             ├─ Graph(source="graph"|"regex")  ──► build_rows · blast_radius · rank_suspects
             │                                        (unchanged)
             ├─ blast.tests  = affected <seeds> -j   (graph only)
             └─ graph ACTION = codegraph ACTION -p R [-j]   (passthrough, same preflight)
```

Components:

- `scripts/_codegraph.py` (new, stdlib): `detect()`, `ensure_index()`, `exclude_index_dir()`,
  `daemon_alive()`, `freshen()`, `read_file_graph()`, `tests_reached()`, `run(action, argv)`,
  `advise_once()`. Raises `GraphUnavailable(reason)`; never exits.
- `scripts/signals.py`: loads the module by path; `Config.code_graph`; provider swap in
  `analyse`; `Graph.source`; `blast.tests`; `structure.graph` block; `advisory`; `graph`
  subcommand; epilog.
- Skill prose: six skills name the new fields and the `graph` actions.
- Tests: a Python `codegraph` shim on a temp `PATH` with modes; recorded JSON and a
  `schema.sql` fixture; a hermetic `run_signals`.

## Data flow

1. A phase runs `signals.py <cmd> --repo <repo>` (an umbrella passes the child repo).
2. `analyse` resolves the repo, reads `code_graph` from the nearest config, applies
   `--graph`.
3. `select` returns a provider. Graph: `Graph` from `read_file_graph` (cross-file edges of
   every kind, keyed by `nodes.file_path`), `source="graph"`. Regex: `scan_structure`.
4. Rows, labels, blast and suspects compute as today on the `Graph`.
5. For `blast` and `hotspots --blast|--diff`, the graph provider adds
   `blast.tests` from `affected <seeds> -j`, and unions those files into `reached`.
6. The envelope gains `structure.source`, `structure.graph {state: present|absent|off|
   failed, reason, version, built {files, seconds, bytes}, sync: daemon|sync|none}` and a
   top-level `advisory` when one is due. Table mode prints the same as one line each.
7. `graph ACTION` runs the same preflight, then `codegraph ACTION -p <repo> … [-j]`, and
   wraps the result in `{version, available, source, command, result}`. Unavailable →
   `available:false, reason`, exit 0.

Database open rule: `file:<db>?mode=ro`; on `unable to open` retry with `?immutable=1`;
never read-write. The WAL `-shm` file is absent when no daemon has run.

## Data model / schema

No shipgate schema. Read from codegraph: `nodes(id, kind, name, qualified_name, file_path,
start_line, end_line, is_exported)`, `edges(source, target, kind)`, `files(path)`,
`schema_versions(version)`. Required columns are probed with `PRAGMA table_info`; the
probe accepts `schema_versions` max ≥ 11 and records the observed value in the envelope.

## API / contract changes

Additive only. `signals.py` JSON gains `structure.source`, `structure.graph`, `blast.tests`,
`advisory`, `config.code_graph`; `OUTPUT_VERSION` stays 1. New subcommand `graph`. New
common flag `--graph`. New config bullet `Code graph:` under `## Code tooling`. No change to
`review-workflow.js` or `explore-workflow.js` (the brief carries the new lines).

## Reference implementation

`shipgate/scripts/signals.py` itself: the `Unavailable` → reason → exit 0 path
(`:127`, `:1072`, `:1542`), `run_git`'s controlled environment (`:396`) for `run`, and
`_load_hooks_common` (`:43`) for loading the private module. Chosen because the 91 tests in
`tests/test_signals.py` already pin this anatomy; `journal.py` is the sibling, not the
reference, because it owns a schema and the signals script must not.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/scripts/`, `shipgate/skills/*/SKILL.md`, `shipgate/tests/`.
- Security-sensitive: writes outside the plugin directory (`.codegraph/` via codegraph,
  `.git/info/exclude`, `.git/shipgate/` marker). Each is bounded and tested (T05, T08). Hooks:
  no change; T09 guards it.
- Public repo: fixtures are recorded on this repository only; measurements from private
  repositories enter the worklog as counts.
- Version bump 0.16.2 → 0.17.0 in `shipgate/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`, same change.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings. Tests are tasks.

## Setup / foundations
- [x] T01 — Record fixtures from codegraph 1.6.2 on this repository — file(s):
  `shipgate/tests/fixtures/codegraph/{version.txt,status-uninit.json,status-indexed.json,
  affected.json,impact.json,callers.json,query.json,node.txt,schema.sql}` — done when: each
  file is the real output on this repo and `schema.sql` holds `.schema` of the index.
- [x] T02 — Hermetic test harness — file(s): `shipgate/tests/test_signals.py:49` — done when:
  `run_signals` strips every `PATH` entry that holds a `codegraph` executable; all 91
  existing tests pass.
- [x] T03 — codegraph shim — file(s): `shipgate/tests/fixtures/codegraph_shim.py`,
  helper `make_codegraph_shim(bin_dir, mode)` in `test_signals.py` — done when: modes
  `ok | uninit | old-version | garbage | kill | hang | corrupt-db | schema-mismatch` replay
  the T01 fixtures, log argv+env as JSONL, and `init` writes `.codegraph/codegraph.db`
  (the minimal schema from `schema.sql`) plus `.codegraph/.gitignore`.

## Feature
- [x] T04 [P] — Config: `Code graph` bullet and `--graph` flag — file(s):
  `signals.py:147-345`, `shipgate/config-template.md:204-214` — done when: tests cover
  `auto|off|root`, bare and backticked, placeholder = absent, invalid = usage error,
  repo config beats umbrella config, `config.code_graph` and its source are echoed, the
  template placeholder test (`:435`) still passes.
- [x] T05 — `_codegraph.py`: detect, exclude, init, lock, freshen, env — file(s):
  `shipgate/scripts/_codegraph.py` (new), `signals.py:43-65` loader — done when tests show:
  FR-001 absent/old/garbage-status → `GraphUnavailable`; FR-002 `init -y` runs once and
  `built` is reported once; FR-003/SC-005 `git status --porcelain` is empty after a build,
  the exclude line is appended once over two runs, and a linked worktree writes to the
  common `info/exclude`; the 10,000-file guard skips the build with an advisory; FR-005 a
  live pid + socket means no `sync` in the log, a dead pid means `sync` runs; FR-016 every
  logged call has `CODEGRAPH_TELEMETRY=0`; FR-013/SC-006 in an umbrella fixture every call
  carries `-p <child>`; `root` with no umbrella index → `graph-root-not-indexed`, no init.
- [x] T06 — Database reader and provider swap — file(s): `_codegraph.py`,
  `signals.py:1016-1100, 1484-1552` — done when: `Graph.source`, `structure.graph` and the
  swap in `analyse` exist; SC-002 fixture (a module loaded by path from two test files)
  gives regex 0 and graph ≥ 2 in `files` and in `tests`; `ro` then `immutable` open order
  is tested; FR-006 trajectory output is byte-identical to before.
- [x] T07 — Fallback paths — file(s): `_codegraph.py`, `signals.py` — done when SC-009
  tests pass: `kill`, `garbage`, `hang` (small timeout), `corrupt-db`, `schema-mismatch`
  each give `source: regex`, one reason line, exit 0, and the regex rows.
- [x] T08 — Advisory once — file(s): `_codegraph.py`, `signals.py:1519-1552` — done when
  SC-003 tests pass: first absent run carries `advisory`, the second does not; `off`
  carries none; table output equals the `--graph off` output plus one line; the marker
  is `<git-common-dir>/shipgate/codegraph-advised` of the outermost git tree (umbrella
  fixture: the umbrella's `.git`); a read-only `.git` is not an error; a second clone
  advises again; `test_writes_nothing` (`:1122`) is split into absent (only the marker,
  once) and present (`.codegraph/`, the exclude line, the marker).
- [x] T09 [P] — Hooks guard — file(s): `shipgate/tests/test_hooks.py` — done when: a test
  fails if any file under `shipgate/hooks/` contains `codegraph` or imports `signals.py`
  (SC-008).
- [x] T10 — `graph` subcommand — file(s): `signals.py:1342-1445, 1649` — done when: each
  of the seven actions passes argv through with `-p` and `-j` where supported, wraps JSON,
  prints text for `node`/`explore`, returns `available:false` when unavailable, and FR-018
  holds (no author field in any output; test greps the fixtures and the wrapper).
- [x] T11 — Skill prose — file(s): `route-and-map/SKILL.md:16,59-73`,
  `review/SKILL.md:16,95-105,300`, `structured-debug/SKILL.md:76-94`,
  `implement/SKILL.md:37-50`, `design/SKILL.md:63`, `feature/SKILL.md:69-74`,
  `model-tiers/SKILL.md:112-126` — done when: Route & Map reports `blast.tests` and runs
  `graph impact <symbol> -f <path>` for each changed exported symbol named from
  `git diff -U0`; Review lists the tests under the risk table and the verify gate runs
  them; debug cites `graph callers` as `[graph]`; implement's reuse step runs
  `graph query <name>` with two synonyms then `graph node`; briefs say an `explore`/`node`
  result counts as a Read; every skill relays `advisory` as one line; skill descriptions
  are not edited; the prose-drift guard (`test_signals.py:1037,1081`) parses every new
  invocation.

## Polish
- [x] T12 [P] — Docs and release — file(s): `shipgate/README.md:176-200,226`,
  `shipgate/config-template.md`, `shipgate/CHANGELOG.md`, `shipgate/docs/glossary.md`,
  `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when:
  README has a Code graph subsection with the measured costs and the root layout (FR-014),
  one Optional-integrations row, the changelog entry for 0.17.0, both versions bumped, and
  the diff grep for private names is empty.
- [x] T13 — Live measurements (manual, counts only) — done when the worklog records:
  SC-002 on this repo (`blast shipgate/hooks/_common.py` ≥ 2 files); SC-004 on a
  1,500-file repo and on the largest umbrella child (sync + query ≤ 5 s / ≤ 10 s);
  SC-006 one definition in a child; SC-005 `git status` clean after a real build.
- [x] T14 — Eval ablation — file(s): `shipgate/evals/71-graph-reuse-detection/`,
  `shipgate/evals/11-neg-one-line-change/graders/no-codegraph-run.md`,
  `shipgate/evals/README.md`, `compare.py` — done when: cases 08/12, 09/13, 10/14, 11 run
  in two arms (`PATH` without codegraph vs with the real binary), case 71 adds reuse
  detection, case 11 fails on any `codegraph` or `graph` call, and SC-007 is recorded.
- [x] T15 — Worktree index seeding — file(s): `shipgate/skills/workspace/SKILL.md` — done
  when: the worktree step says to copy `<source>/.codegraph` into the new worktree when the
  source has an index (daemon files excluded) and to let the preflight `sync` it; the
  exclude line is shared via the git common dir; `test_prose.py` passes. Measured: copy +
  sync 1.2 s on this repo; `status` reports `worktreeMismatch: null` after the copy.

## Traceability
- FR-001, FR-005, FR-016 → T05
- FR-002, FR-003, FR-013, FR-014 → T05, T12
- FR-004 → T07, T08
- FR-006 → T06
- FR-007 → T06
- FR-008, FR-009 → T06, T10, T11
- FR-010, FR-011, FR-012 → T10, T11
- FR-015 → T04, T12
- FR-017 → T05 (only `.codegraph/`, the exclude line, the marker), T08
- FR-018 → T10
- FR-019 → T14
- SC-001 → T11, T13
- SC-002 → T06, T13
- SC-003 → T08
- SC-004 → T13
- SC-005 → T05, T13
- SC-006 → T05, T13
- SC-007 → T14
- SC-008 → T09
- SC-009 → T07
- FR-013 (worktrees) → T15

## Deviations & notes (filled during implementation)
- 2026-10-19 — design: the CLI BFS alternative measured 28 calls / 8.1 s on a 6-file diff
  (1,469-file repo); the database read 28 ms. The graph blast of one TS module matched the
  regex blast file for file (4 files). Recorded here so T13 has a baseline.

- 2026-10-19 — T05: `config.source` gained `code_graph`, so 4 exact-dict assertions in
  `test_signals.py` changed; nothing else reads `config.source`. `Selection` carries a
  `state` field (present|absent|off|failed) for `structure.graph`. Extra reasons:
  `graph-off`, `graph-exclude`, `graph-init`, `graph-sync`, `graph-timeout`.
- 2026-10-19 — root mode without the MCP daemon: `sync` on an umbrella root takes 55–66 s
  and the 30 s call timeout turns it into `graph-timeout` → regex. Intended; T12 documents
  "root mode needs the MCP server running".

- 2026-10-19 — T06: `graph-schema` fires on an empty `edges` table with a non-empty
  `files` table, not on zero cross-file edges (a real index always has `contains` edges;
  a small repo can have no cross-file edge). `blast.tests` is filtered to indexed files in
  `graph_files`; `blast.tests_reason` carries an `affected` failure. `structure.languages`
  uses codegraph's names under the graph (`python`, `typescript`, `tsx`).
- 2026-10-19 — T06 gate failure, fixed: real `status`/`sync`/`init` take the path
  positionally and have no `-p`; only the query commands do. The shim had accepted `-p`
  everywhere. The shim now enforces the real argv contract, and `TestLiveCodegraph`
  (`SHIPGATE_LIVE_CODEGRAPH=1`) runs SC-002 against the real binary.
- 2026-10-19 — FR-003 scope: the exclude line is written only when shipgate builds the
  index. An index the user built keeps codegraph's own `.codegraph/.gitignore` contract
  (commit that one file). Writing into `.git` for an index we did not create is out.
- 2026-10-19 — argv rule for prose: `signals.py graph [--repo R] [--graph M] [--json]
  ACTION ARGS…`; `REMAINDER` sends every later flag to codegraph, so the common flags go
  before ACTION.

- 2026-10-19 — T13 live finding, fix in flight: `codegraph status <child>` on an unindexed
  child under an indexed umbrella root answers for the root (`initialized: true`, root
  `projectPath`, 11–60 s). "Initialized" must be decided by the file
  `<child>/.codegraph/codegraph.db`, never by `status`; the guard runs before any
  path-walking call; `projectPath` is checked after a build.
- 2026-10-19 — T13: on a 1,469-file TS service, a 42-file diff reaches 1,108 files through
  the graph (imports-only: 1,097; calls-only: 325) and 53 through the regex scanner. The
  gap is the regex scanner's resolution of workspace-package imports, not the edge kinds.
  Graph cost for `blast --diff`: 2.0 s; `hotspots --blast`: 2.2 s (SC-004 holds).
  `graph query` is fuzzy: SC-006 counts exact-name hits (1 definition in the child).

- 2026-10-19 — incident during T13: the orchestrator reverted `signals.py` with
  `git checkout --` to drop a probe and lost the uncommitted worker edits (~300 lines).
  Recovered by replaying the six recorded write actions from the worker transcripts onto
  HEAD; the recovered file's disassembly matches the pre-loss bytecode cache, and the
  codegraph (96) and signals (94) suites pass.

- 2026-10-19 — T13 measurements (counts only, one machine, one run each):
  SC-002 this repo: `blast shipgate/hooks/_common.py` → 7 files, 2 tests reached (regex: 0).
  SC-004: 1,469-file service `blast --diff` 2.0 s, `hotspots --blast` 2.2 s; 3,351-file child
  build 22.9 s / 173 MB then 2.2 s per call; 490-file child build 2.2 s / 12 MB then 1.3 s.
  SC-005: `git status --porcelain --untracked-files=all` shows no codegraph entry after the
  automatic build in two child repos; `/.codegraph/` present in each `info/exclude`.
  SC-006: `graph query` in a child returns 1 exact-name definition (the root index returned 4
  before its exclude list). The 10,000-file guard: a 17,023-file child gets the advisory,
  no `.codegraph/`, no init; its marker landed in the umbrella's `.git/shipgate/` (once per
  umbrella, not per repo — review nit).

- 2026-10-19 — T14: two arms × 8 cases × 3 runs, $20.75. Graph arm ≥ regex arm on every
  case (all 1.00), case 11 makes no codegraph call. `"source": "graph"` in 20 of 21
  with-plugin runs of 08–10, 12–14 and 71: 3/3 per case, except case 12 at 2/3 (one run
  of 12 printed no structure block). **SC-007's "higher on 13 and 71" is not shown**: both tie at 1.00 because
  the fixtures sit at the ceiling (9 files, no tests). Proving "higher" needs a fixture
  too large to read whole, a helper whose name does not give it away, and tests a diff
  reaches. Follow-up, not this change. The regex arm is `run-case.sh --no-codegraph`
  (strips codegraph from PATH; the harness drops unknown env vars, so
  `SHIPGATE_CODEGRAPH_BIN` cannot select the arm). `baseline.json` re-recorded (8 rows,
  plugin 0.17.0, incl. new case 71).

## Review round 1 (2026-10-19, workflow wf_0130e83a-4e4)

3 lenses, 41 raw → 38 deduped, 18 above the floor, 2 HIGH held (4 refuters), 0 killed, 20
below floor. Security sub-task: no High/Medium on macOS/Linux; one Windows-only Medium
(0.7). Verdict: **not ready**. Fix list:

- F1 HIGH `_codegraph.py:453` — too-large marker once per umbrella; make it per repository.
- F2 HIGH `_codegraph.py:351` — a tracked `.codegraph` symlink or a git-tracked index makes
  the build write outside the repo / serves a committed graph; refuse with
  `graph-index-untrusted` when `.codegraph` is a symlink, resolves outside the root, or
  `git ls-files -- .codegraph` is non-empty.
- F3 MEDIUM (security, Windows) `_codegraph.py:126` — `shutil.which` searches cwd first on
  Windows; reject a resolved binary inside the repo, any umbrella root, or cwd.
- F4 MEDIUM `_codegraph.py:382` — `daemon.sock` must be a socket (`S_ISSOCK`), a
  `PermissionError` from `os.kill` is not "alive".
- F5 MEDIUM `signals.py:1893` — `graph` with exit 0 and non-JSON output (symbol not found)
  is `available: true`, `result: null`, the text in `result_text`, `not_found: true` when
  the text says so; not `graph unavailable`.
- F6 LOW `signals.py:1176` — a graph that indexed none of the wanted files falls back to
  the regex scanner, not `no-adapter`.
- F7 LOW `_codegraph.py:588` — pass seeds to `affected` via `--stdin`, so a path that
  starts with `-` cannot read as an option.
- F8 LOW `_codegraph.py:145` — strip `GIT_DIR`/`GIT_WORK_TREE` from the codegraph env, as
  `_git_env` does.
- F9 LOW `_codegraph.py:104` — `structure.graph.index_root` is an absolute machine path;
  emit it relative to the repository (FR-018).
- F10 LOW `_codegraph.py:460` — three blank lines (PEP 8).
- F11 MEDIUM docs `adr/0004:8` — add the "amended by 0007" status and inline notes (ADR
  0003 convention).
- F12 MEDIUM docs `adr/0007:66`, PRD FR-001 — "present" is PATH + version; the db file
  decides built; `status` runs only after shipgate's own build; §7 lists the lock and both
  markers.
- F13 LOW docs `CHANGELOG.md:20`, README — eight skills, add the worktree seeding; README
  common-flags sentence names `## Code tooling` for `--graph`; root mode: passthrough
  paths are index-root-relative.
- F14 LOW docs worklog/evals README — reconcile the SC-007 graph-arm counts.
- F15 LOW docs `workspace/SKILL.md:102` — `cp -R` nests when the worktree already has
  `.codegraph/`; copy the contents or check absence first.
- F16 LOW docs research note:21 — "28 child repos", the agreed public wording.

## Review round 2 (2026-10-19, one reviewer, fix scope)

F1–F16: all confirmed on evidence (table in the reviewer's report; F2 and F5 docs reopened).
New findings, all reproduced with codegraph 1.6.2. Verdict: **not ready**.

- R2-1 HIGH `_codegraph.py:266-270` — `check_trusted` refuses an index whose committed
  `.codegraph/.gitignore` (codegraph's own file) is tracked. Regression. Fix: ignore that one
  path; refuse any other tracked path under `.codegraph/`.
- R2-2 HIGH `_codegraph.py:259-270` — case-insensitive bypass: a committed
  `.CodeGraph/codegraph.db` passes, and `sync` modified a tracked file (FR-017). Fix: list with
  `git ls-files -z -- ':(icase).codegraph'` and compare lower-cased.
- R2-3 MEDIUM `_codegraph.py:164-169` — `binary()` refuses a normally installed codegraph
  when cwd is `$HOME` or `/` (the resolved symlink target is under cwd); install advisory
  shown to a user who has it. Fix: judge the PATH directory `which` matched, not the
  resolved target; refuse a repo/umbrella directory; apply the cwd rule only to an empty,
  `.` or relative PATH entry (or on Windows).
- R2-4 MEDIUM `_codegraph.py:435-452` — `daemon_alive` ignores `daemon.pid.socketPath`;
  codegraph binds in TMPDIR when the project path exceeds 100 chars. Fix: read `socketPath`,
  fall back to `.codegraph/daemon.sock`, `S_ISSOCK` that path.
- R2-5 MEDIUM docs — CHANGELOG wrapper list omits `result_text`/`not_found`; README names
  neither them nor `graph-index-untrusted` (with remedy), `graph-empty`, nor the relative
  `index_root`; ADR 0007 §4 lacks the trust step and the socket condition; PRD FR-001 lacks
  the binary-location narrowing.
- R2-6 LOW `signals.py:1898-1907` — `not_found` is always false for `node`/`explore`. Fix:
  regex on the text (`Symbol ".*" not found`, `No relevant code found`).
- R2-7 LOW `_codegraph.py:658-661` — a seed with `\n` splits on `--stdin`. Fix: skip such
  seeds.

Rejected: `DROPPED_ENV` scope (matches `_git_env`; hooks never call this path);
`graph-empty` keeps `index_root`/`sync` in the block (accurate: a sync ran); ADR 0004
`updated:` left as the convention (ADR 0003 precedent).

## Review round 3 (2026-10-19, one reviewer, R2 scope)

R2-1, R2-2, R2-4, R2-6, R2-7 confirmed on evidence (live reproductions re-run; a real
daemon with a TMPDIR socket detected). Verdict: **not ready**, one small round left:

- R3-1 MEDIUM `_codegraph.py:312` — the `.codegraph/.gitignore` allowlist accepts a symlinked
  `.gitignore`; `init` then creates one fixed-content file at a path the repo chooses.
  Fix: refuse a symlink (or git mode 120000) there.
- R3-2 MEDIUM `_codegraph.py:196` — an umbrella root at `$HOME` refuses `~/.local/bin`.
  Fix: refuse an umbrella-root PATH entry only when the umbrella tracks it.
- R3-3 LOW — a refused PATH entry does not fall through to a later valid install.
- R3-4 LOW `_codegraph.py:709` — all seeds dropped → `tests: []` instead of null + reason.
- R3-5 LOW — Windows: drop the bare extensionless candidate in `_which`.
- R3-6 LOW docs — not-found shape for text actions; two untrusted triggers and the
  `.CodeGraph` remedy; `graph-empty` wording; "ignores" → refuses + fall-through.

## Review round 4 (2026-10-19, one reviewer, R3 scope)

R3-1..R3-5 confirmed on evidence (symlinked and mode-120000 `.gitignore` refused, victim
file not created; untracked `~/.local/bin/codegraph` under a dotfiles HOME accepted, a
tracked one refused; PATH walk continues past a refused entry; `graph-affected-seeds`;
PATHEXT split on `;`). `_CHOSEN` cache: keyed by index root and repo, re-detected on every
`select`, no stale path found. Docs matched to the code, plus three clauses added in this
round: the umbrella `.git` skip case, `graph-affected-seeds`, "tracked as a symlink".
Gate: 646 tests OK with the live case; `test_codegraph.py` OK on Python 3.9.6; `test_prose`
OK. Verdict: **ready** (SC-007 partially met, see Acceptance criteria).

Accepted LOWs, not changed: `_umbrella_ships` passes the entry as a glob pathspec (can only
over-refuse, never bypass); `run()`'s `binary(cwd)` fallback has no umbrella check but is
unreachable in production (every `run` follows a `detect` in the same `select`); inserted
doc lines not rewrapped.

## Acceptance criteria (PRD SC-###), with evidence

- SC-001 — route-and-map on this repo with no config: `structure.source: graph`,
  `blast.tests` listed, `graph impact` available; eval traces show `"source": "graph"` in
  20/21 with-plugin runs. Met.
- SC-002 — `blast shipgate/hooks/_common.py`: 7 files, 2 tests reached (regex: 0); live
  test `TestLiveCodegraph`. Met.
- SC-003 — `TestAdvisoryOnce`, `TestWrites`: absent → same rows + one line, once. Met.
- SC-004 — 1,469-file repo: 2.0 s / 2.2 s; 3,351-file child: 2.2 s after the build. Met.
- SC-005 — `git status --porcelain --untracked-files=all` clean after the automatic build
  in two child repos; pinned by `test_git_status_is_clean_after_a_build…`. Met.
- SC-006 — one exact-name definition in the child; `-p <child>` on every call. Met.
- SC-007 — graph arm ≥ regex arm on 8 of 9 cases (72: 0.88 vs 0.92, within noise) and case
  11 makes no codegraph call: met in part. "Higher on blast radius and reuse detection":
  **not met** after the ceiling-breaking fixtures 72/73 (see the T14 fixture-round note).
  Requirement routed back to the user.
- SC-008 — `TestHooksStayOffTheCodeGraph`; hooks untouched. Met.
- SC-009 — `TestFallback` (kill, garbage, hang, corrupt-db, schema-mismatch) → regex, one
  reason line, exit 0. Met.

- 2026-10-19 — T14 fixture round (cases 72, 73; $10.64): the graph arm is **not higher**.
  72 (500-file npm-workspace monorepo, 44 importers + 15 tests behind one hub): graph arm
  0.88 ×3 (43/44 importers, misses one second-hop barrel re-export; codegraph's edge, not
  ours), regex arm 0.88/1.00/0.88 (the agent saw "blast: 2 files", distrusted it and wrote
  its own import resolver in one turn: 59/59 once). Turns 14/10/12 vs 13/10/13; cost $1.48
  vs $1.55. 73 (hidden helper, no "retry"/"backoff" anywhere): 1.00 in every run of both
  arms; `graph query` matches names, not meaning, so codegraph cannot move reuse detection.
  Signals alone differ hugely (graph 56/59 vs regex 2/59 on the same fixture), the end
  answer does not. SC-007 "higher on 13/71" is therefore **not met**, not merely unshown.

## Rejected findings

- S7 MEDIUM 60 `signals.py:1888` (action table lives in signals.py; root-mode paths not
  rebased) — the action table moves to `_codegraph` (F13 covers the root-mode note); the
  rebase is not done: root mode is an opt-in the user builds, and the passthrough returns
  codegraph's own output.
- S10 LOW `signals.py:354` (invalid `Code graph` value exits 2) — kept loud on purpose; a
  typo that silently disables the graph is worse than a usage error on an on-demand call.
- S11 LOW `signals.py:1868` (advisory after the reason; source `regex` when nothing ran) —
  cosmetic; `source: regex` states what would answer, matches `structure.source`.
- S12 LOW `_codegraph.py:445` (a second call during another's `init` gets `graph-sync`) —
  it falls back to regex with exit 0 and the next call works; accepted.
- S18 LOW `_codegraph.py:87` (`available`/`source`/`state` overlap) — three consumers read
  three questions; documented in `Selection`.
- Below floor: `graph query/explore/node` relays repository text to the model — by design
  (the explorers read the same files); `SHIPGATE_CODEGRAPH_BIN` active in production — env
  vars are trusted (precedent); `path_without_codegraph` may drop a shared PATH dir — the
  eval helper resolves `claude` first, documented; `--blast` always passed by review —
  SC-003 is about the regex arm's *rows*, which are unchanged; the rest are style notes.
