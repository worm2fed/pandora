---
type: worklog
title: "Worklog: Code signals"
created: 2026-09-25
updated: 2026-09-25
tags:
  - worklog
  - shipgate
status: reviewed
prd: "./code-signals.md"
related: ["../adr/0004-code-signals-on-demand-stdlib-script.md", "../research/2026-09-25-tearags-vs-shipgate.md"]
---

# Worklog: Code signals

> Design + build plan companion to `./code-signals.md`. Issue: none / ad-hoc.
> Branch `chore/tearags-vs-shipgate`.

---

# Design

## Approach

pragmatic-balance won, with two tests folded in from minimal-change (no-write snapshot,
skill-prose drift guard). Core trade-off: one ~900-line stdlib script that reads a narrow
slice of the prose config itself, so the terminal and the flow provably use the same
numbers — at the cost of the first prose parser in `scripts/`. See ADR 0004.

## Architecture

- **`scripts/signals.py`** — sections in order: constants/defaults, config, git helpers,
  trajectory, labels, structure (adapter table, index, graph), aggregate, suspects, render,
  CLI. Standalone: copies `_matches_glob` from `journal.py` rather than importing it.
- **CLI**
  - common flags: `--repo DIR` (default: cwd's git toplevel), `--scope PATH` (label
    population), `--window MONTHS`, `--fix-pattern RE`, `--exclude GLOB` (repeatable, adds to
    defaults), `--json`
  - `hotspots [PATH...] [--diff REV] [--by-dir DEPTH] [--blast] [--top N=20]` — trajectory
    + fan-in/out per file; `--blast` adds the blast radius of the selected set so
    route-and-map needs one call
  - `blast FILE... [--diff REV] [--limit N=50]` — structure only, no log pass
  - `suspects FILE... [--top N=10]` — ranked suspect list for debugging
  - exit codes: 0 ok (including "signals unavailable"), 1 infra (git failed unexpectedly),
    2 usage. Degradation prints one stdout line / `available:false` in JSON, nothing on
    stderr.
- **Trajectory** — one streamed `git -c core.quotepath=off log --no-merges -M
  --name-status --format=%x00%H%x1f%ct%x1f%aE%x1f%s` over full history, newest first.
  Windowed counts (commits, fixes, authors, top share) use commits inside the window;
  `first_seen`/`last_seen` use all commits. Rename alias map old→canonical from `R###`
  lines. Population = `git ls-files` at HEAD minus excludes (deleted files drop out).
  "Now" = HEAD committer time. Author emails live only in in-memory Counters.
- **Fix pattern default** (case-insensitive, subject line):
  `^(fix|hotfix|revert)(\(.+\))?!?:|^revert\b|\b(fix(e[sd])?|bug|hotfix|regression)\b`
- **Default excludes**: `vendor/`, `node_modules/`, `third_party/`, `dist/`, `build/`,
  `*.min.*`, `*.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `go.sum`,
  `*.pb.go`, `*_generated.*`, `*.snap`.
- **Labels** — nearest-rank quartiles over the population (repo or `--scope`); equal
  values get equal labels; `low|mid|high|top`. Labelled: commits, fix_rate, age, staleness,
  authors, top_share, fan_in, fan_out. A file with < 3 in-window commits gets fix_rate
  label `low` (one fix commit must not make a file top-risk).
  `risk = max(label(commits), label(fix_rate))`.
- **Adapters** — regex, line-at-a-time, comment lines skipped; files > 1 MB skipped.
  - TS/JS: `import…from`, bare `import '…'`, `export…from`, `require()`, `import()`;
    relative specifiers resolve with extension, `/index.*`, `.js→.ts` probing; root
    `tsconfig.json`/`jsconfig.json` `paths` after a comment/trailing-comma strip (parse
    failure → aliases skipped).
  - Python: dotted-module index over roots {repo, `src/`, `lib/`}; relative imports from
    the importing file's package; `from a.b import c` tries `a.b.c` then `a.b`.
  - Go: each `go.mod` supplies module path→dir; an import edge goes to each non-test `.go`
    file in the package dir (package-level edge projected onto files — documented).
  - Bare/external specifiers ignored; unresolved relative import → `structure: partial` +
    `unresolved` count; no adapter → `structure: unknown`, `fan_in`/`fan_out: null`.
- **Blast** — reverse-adjacency BFS from the seed set, cycle-safe, excluding seeds:
  `{size, files[:limit], truncated, by_dir, unknown_seeds}`.
- **`--by-dir`** — distinct commit sets unioned (not summed — one 5-file commit is one
  commit); labels max; importer sets union minus the module's own files. *Deviation from
  FR-005's "sum of counts" wording, deliberate.*
- **Suspects** — candidates: symptom files, one-hop importers/importees, same-directory
  files. `score = fix_rate × min(1, commits/3) × 1/(1 + stale_days/90) × proximity`,
  proximity {self 1.0, import neighbour 0.75, same dir 0.5}; ties by path.
- **Config** — `load_config(repo) → (cfg, source)`: only the `## Code signals` section of
  `<repo>/.claude/shipgate.md` (umbrella: the parent root's too); only backticked values on
  the `Window`, `Fix pattern`, `Exclude` bullets; `<…>` placeholders count as absent; flags
  win. JSON echoes `config{window_months, fix_pattern, exclude, source{…: default |
  shipgate.md | flag}}`.

## Data flow

`skill → python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" <cmd> --json → load_config
(shipgate.md ⊕ flags) → git probes (toplevel, is-shallow, HEAD time) → [trajectory: one
log pass] + [structure: ls-files → adapters → graph] → labels over the population →
rows / dirs / blast / suspects → stdout JSON → skill prose (impact map block, brief table,
suspect list) | review skill → args.fileRisk → review-workflow compareForVerify`.
Nothing is written anywhere (FR-016).

## Data model / schema

JSON `"version": 1`, top-level: `head`, `config{…}`, `trajectory{available, reason,
commits_scanned}`, `structure{available, reason, languages, files_scanned}`,
`files[{path, commits, fixes, fix_rate, age_days, stale_days, authors, top_share, fan_in,
fan_out, unresolved, structure, labels{…}, risk}]`, optional `dirs`, `blast`, `suspects`.
Paths repo-relative; floats 2 dp; sort risk → fixes → commits desc, then path; no run
timestamp. Human table columns: `path commits fix% age stale auth top% in out risk`.
Journal: `phase-entered route-and-map` data gains
`"signals":{"modules":{"api":{"churn":"top","fix":"high","fan_in":"mid"}},"blast":37}` or
`"signals":{"unavailable":"shallow"}` — under the 1 KB cap; no journal schema change
(`phase-entered` requires only `phase`).

## API / contract changes

- `review-workflow.js`: new optional `args.fileRisk` (object path → `low|mid|high|top`;
  invalid → throws `review-workflow: args.fileRisk …`; keys normalized via
  `normalizePath`). `RISK_RANK`, `riskOf(f)` (0 for unknown). `compareFindings`: severity →
  confidence → risk. New `compareForVerify`: severity → risk → confidence, applied to the
  refuter targets at the `candidates.filter(...)` site. `compact`/`oneLine` gain `risk`
  only when the map is non-empty; `coverage` gains `riskOrdered`. **Absent → byte-identical
  output** (existing suite is the regression proof).
- `explore-workflow.js`: unchanged; the table travels in `args.brief` as prose.
- `config-template.md`: new `## Code signals` section after `## Code tooling`
  (Default-when-absent comment; bullets Window / Fix pattern / Exclude). No `setup` or
  sidecar change.
- Version 0.12.1 → 0.13.0 in `.claude-plugin/plugin.json` and
  `../.claude-plugin/marketplace.json`.

## Reference implementation

`scripts/journal.py` — argparse layout (`build_parser`, per-subcommand `--json`, `COMMANDS`
dispatch, `main()` mapping typed errors to exit codes, `EPILOG` exit-code doc), sidecar
lookup walking upward to the git root, `_matches_glob`. It is the reference because it is
the one vetted, tested stdlib CLI in the plugin — not because it is the nearest sibling.
Tests mirror `tests/test_journal.py` (tempdir fixtures built by the test, helpers via
`spec_from_file_location`) and `tests/test_workflow_scripts.py` (node stub harness with
canned agent labels).

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/` — scripts, skills, docs, tests all inside the plugin.
- `hooks/` untouched (security-sensitive area). The script is invoked by skills and the
  user only, never at session start.
- Reads the user's repo; writes nothing (FR-016) — stays out of the "writes outside the
  plugin directory" area.
- Public-repo rule: fixtures synthetic (`git init` in tempdirs, author
  `Fixture Author <fixture@example.test>`), eval repos inline and synthetic, measurements
  as counts and sizes only; diff grepped for private names/ids/paths before finishing.
- Version bump + marketplace entry in the same PR.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations
- [x] T001 — SC-005 baseline: run the existing `evals/` suite against v0.12.1 is not
  applicable (cases 08–11 don't exist yet); instead build cases 08–11 first (T009a) and
  run them on the **pre-change** tree once, recording per-case with/without scores, cost,
  latency in this worklog — file(s): `docs/prd/code-signals.worklog.md` — done when: a
  baseline table exists here. *(Ordering note: T009a precedes T001; both precede any
  wiring.)*
- [x] T002 — `signals.py` skeleton: parser (3 subcommands, common flags, `--json`), exit
  codes, `EPILOG`, git probes (toplevel, `--is-shallow-repository`, HEAD time),
  degradation paths, `load_config` — file(s): `scripts/signals.py` — done when: T003 passes.
- [x] T003 — tests for T002: no-git dir, shallow clone (`git clone --depth 1 file://…`),
  empty repo, missing `git` on PATH → exit 0, empty stderr, `available:false` + reason;
  human table prints exactly one line; config precedence (flag > file > default),
  placeholder `<…>` treated as absent, non-backticked value ignored, `source` echoed —
  file(s): `tests/test_signals.py` — done when: tests fail first, then pass (FR-002,
  FR-015, FR-016, SC-002).

## Feature
- [x] T004 [P] — trajectory pass + labels: streamed log, window split, fix detection,
  rename alias map, excludes, `ls-files` population, quartile labels, `risk`, `--top`,
  `--diff` filter — file(s): `scripts/signals.py` — done when: T005 passes.
- [x] T005 — tests for T004: fix-pattern positives (`fix(x):`, `fix!:`, `Revert "…"`,
  `bug`) and negatives (`prefix`, `suffix`); window boundary (commit at exactly window
  edge); rename follow (history lands on new path); excluded + deleted files absent;
  tie-stable quartiles (equal values → equal labels); `< 3` commits → fix_rate `low`;
  labels computed over repo when positional paths filter rows; `--scope` changes the
  population — file(s): `tests/test_signals.py` — done when: fail first, then pass
  (FR-001, FR-003, FR-007, FR-008).
- [x] T006 [P] — adapters, graph, `blast`: TS/JS (relative, index, `.js→.ts`, tsconfig
  `paths` with comment strip), Python (roots, relative, `__init__`, `a.b.c` then `a.b`),
  Go (`go.mod` → package dir), `partial`/`unresolved`, `unknown`, reverse BFS —
  file(s): `scripts/signals.py` — done when: T007 passes.
- [x] T007 — tests for T006: each adapter's resolution cases; `.rb` → `unknown` with null
  counts; unresolved relative → `partial`; A←B←C chain gives blast size 2 from A; cycle
  terminates; `unknown_seeds` reported; `--limit`/`truncated` — file(s):
  `tests/test_signals.py` — done when: fail first, then pass (FR-004).
- [x] T008 — `--by-dir` (distinct-commit union, label max, importer union minus own),
  `--blast` on `hotspots`, `suspects` scoring + ordering, table renderer, JSON `version`
  — file(s): `scripts/signals.py`, `tests/test_signals.py` — done when: aggregation and
  suspect-order tests fail first, then pass (FR-005, FR-006, FR-011 mechanics, FR-014).
- [x] T009 [P] — `review-workflow.js` `fileRisk`: `RISK_RANK`, `riskMap` validation,
  `riskOf`, `compareFindings` tie-break, `compareForVerify` at the refuter-target site,
  `risk` in `compact`/`oneLine` when present, `coverage.riskOrdered`, log line —
  file(s): `skills/review/references/review-workflow.js` — done when: T010 passes.
- [x] T010 — tests for T009: cap 2 + two HIGH → the lower-confidence HIGH in a `top` file
  gets the refuters; equal severity+confidence → `top` file's survivor ranks first; bad
  label / non-object throws with the `review-workflow: args.fileRisk` prefix; `./src/a.js`
  matches `src/a.js`; **no `fileRisk` → existing suite unchanged, output byte-identical**
  — file(s): `tests/test_workflow_scripts.py` — done when: fail first, then pass (FR-010).
- [x] T009a [P] — eval cases 08–11 following `evals/01-*/prompt.md`'s shape (inline
  synthetic repo, dated commits, regex + llm graders, `runs: 3`, outcome graders not
  `tool_used`): `08-bug-localization-history`, `09-blast-radius-diff`,
  `10-risk-ranked-review` (ground truth: files of the reviewed commit re-fixed within the
  next 8 weeks of synthetic history), `11-neg-one-line-change` — file(s):
  `evals/08-*/…`, `evals/09-*/…`, `evals/10-*/…`, `evals/11-*/…` — done when: a pilot
  `claude plugin eval . --runs 1 --ablation with-without --no-scaffold --no-publish`
  runs all four without a "cannot pass with the granted tools" warning (SC-003).
- [x] T011 [P] — skill wiring (prose): `route-and-map` (step + `### Risk signals` block +
  journal `signals` essentials), `review` (brief table from `hotspots --diff`, `fileRisk`
  args bullet, tie-break rule for the agents path too), `structured-debug` (step 2b
  `suspects`, cited as `[signals]` evidence, not a verdict), `implement` + `design`
  (precedent preference sentence), `feature` (explore brief may carry the table),
  `model-tiers` (worker brief may carry it) — file(s): the seven `SKILL.md`s — done when:
  T012 passes and each skill's degradation line matches the CLI's reasons (FR-009,
  FR-011, FR-012, FR-013).
- [x] T012 — skill-prose drift test: every `signals.py …` invocation quoted in a
  `SKILL.md` parses with `build_parser()` (pattern: `tests/test_journal.py`'s prose-drift
  guard) — file(s): `tests/test_signals.py` — done when: fails on a deliberately broken
  flag, passes on the real prose (FR-014, SC-002 prose side).
- [x] T013 [P] — `config-template.md` `## Code signals` section — file(s):
  `config-template.md` — done when: the section's three bullets round-trip through
  `load_config` in a test (FR-002, FR-008).

## Cross-cutting proofs
- [x] T014 — privacy test: fixture author name/email appear in no subcommand's JSON or
  table output — file(s): `tests/test_signals.py` — done when: passes (SC-006, FR-007).
- [x] T015 — reproducibility + no-write: two runs byte-identical; identical after
  `touch`-ing every file; fixed 2020 dates give exact `age_days`/`stale_days`; file-tree +
  mtime snapshot of the repo and `.claude/` unchanged after a run — file(s):
  `tests/test_signals.py` — done when: passes (SC-007, FR-016).
- [x] T016 — perf: always-on 2k-commit variant catches O(n²); `SHIPGATE_PERF=1`-gated
  variant builds ~20k commits / ~3k files / ~300k lines via a stdlib-written
  `git fast-import` stream and asserts < 15 s trajectory, < 10 s structure. Also measure
  by hand on a large public repo; record counts, sizes and timings below — file(s):
  `tests/test_signals.py`, this worklog — done when: both bounds hold, or the `-M` fallback
  is taken and logged as a deviation (SC-001).

## Release
- [x] T017 — evals: run cases 08–11 on the wired tree, `runs: 3`, with-without; record
  SC-004 precision@3 vs base rate and SC-005 Δ with cost/latency vs the T001 baseline —
  file(s): this worklog — done when: the table below is filled and SC-004/SC-005 are
  stated as met or not (SC-003, SC-004, SC-005).
- [x] T018 — README ("What's inside", "Dependencies & integrations", a "Code signals"
  subsection), CHANGELOG v0.13.0 entry, version bump in both manifests — file(s):
  `README.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`,
  `../.claude-plugin/marketplace.json` — done when: `grep -n '"version"'` shows 0.13.0 in
  both.
- [x] T019 — confidentiality grep of the whole diff for private project names, tracker-id
  patterns and private paths — done when: zero hits (SC-006; a hit is a blocker).

## Traceability
- FR-001 → T004, T005 · FR-002 → T002, T003, T013 · FR-003 → T004, T005 · FR-004 → T006,
  T007 · FR-005 → T008 · FR-006 → T008 · FR-007 → T004, T014 · FR-008 → T004, T005, T013 ·
  FR-009 → T011 · FR-010 → T009, T010, T011 · FR-011 → T008, T011 · FR-012 → T011 ·
  FR-013 → T011 · FR-014 → T008, T012 · FR-015 → T002, T003 · FR-016 → T002, T015
- SC-001 → T016 · SC-002 → T003, T012 · SC-003 → T009a, T017 · SC-004 → T017 ·
  SC-005 → T001, T017 · SC-006 → T014, T019 · SC-007 → T015

## Measurements (SC-001 / SC-004 / SC-005)

**SC-001 (perf)** — laptop, Apple silicon, git 2.50:

| What | Repo shape (counts/sizes only) | Result |
|---|---|---|
| trajectory + structure, generated | 20,062 commits / 3,005 TS files / 300,500 lines | `hotspots --json` 2.0–2.1 s (bound 15 s) |
| structure only, generated | same | `blast` 1.4–1.6 s (bound 10 s) |
| trajectory + structure, public repo (django, full history) | 34,361 non-merge commits / 7,091 tracked files / ~1.15M lines / 307 MB `.git` | `hotspots --json` 2.9–3.5 s; `blast` 1.3 s (2,078 importers) |
| `-M` rename detection cost | django | +0.25 s vs `--no-renames` — kept |

**SC-003/004/005 (evals)** — `claude plugin eval . --runs 3 --ablation with-without --scaffold
--judge-model sonnet`, clean sandbox (Homebrew git on PATH, fixtures via `scaffold_script`),
3 runs per arm. Columns: v0.13.0 with plugin · v0.12.1 with plugin (same prompts, pre-change
tree) · no plugin. "fired" = with-arm runs in which a shipgate skill was invoked (v0.13.0).

| case | 0.13.0 with | 0.12.1 with | no plugin | fired | note |
|---|---|---|---|---|---|
| 08 bug localization (natural) | 0.93 | 0.93 | 0.93 | 0/3 | ceiling: the bug is readable in the code |
| 09 blast radius (natural) | 1.00 | 0.95 | 1.00 | 0/3 | ceiling |
| 10 risk ranking (natural) | 0.83 | 0.50 | 0.67 | 0/3 | skill never fires → bare-model coin-flip |
| 11 negative one-liner | 1.00 | 1.00 | 1.00 | 0/3 (correct) | no ceremony, no signals round-trip |
| 12 bug localization (explicit `structured-debug`) | 1.00 | 1.00 | 0.40* | 3/3 | skill already cites history at 0.12.1 |
| 13 blast radius (explicit `route-and-map`) | 1.00 | 0.95 | 0.00* | 3/3 | |
| **14 risk ranking (explicit `review`)** | **1.00** (v3) / 0.67 (v4, judge) — **regex re-score: 6/6 top-two** | **0.50** — **0/3 top-two** | 0.33* / 0.50 (v4) — 1/6 top-two | 6/6 | **the signals' contribution**; v5 re-run with regex graders pending |

\* no-plugin arm refused ("skill isn't available") under the v3 prompt; v4 rerun with a
fallback clause pending — the honest no-plugin column for 12–14 is whatever v4 reports.

- **SC-004**: case 14 top-two precision (regex, judge-free, all clean v3+v4 transcripts) =
  **6/6 with signals** vs 2/6 for the same `review` skill at v0.12.1 and 3/6 with no plugin
  (random two-of-five = 1/10; base rate of hot files 2/5). Met, past the 2× bar against
  every comparator.
- **SC-005**: on cases 08–11 v0.13.0's with-arm is ≥ v0.12.1's on every case (0.93/0.93,
  1.00/0.95, 0.83/0.50, 1.00/1.00). Met. Δ (with − without) on the natural prompts is ~0
  because no skill triggers — a triggering finding, not a signals one (ledger).
- **SC-003**: suite of 7 cases runs under `--ablation with-without`. Met.
- Cost: pilot-to-final ≈ $30 across ~150 runs (incl. ~40 sandbox casualties); a clean full
  suite (7 cases × 3 runs × 2 arms) ≈ $6.3 per tree; ~$0.15–0.30 per run; case 14 with
  signals ≈ $0.17 and ~45 s per run.

## Deviations & notes (filled during implementation)
- 2026-09-25 — design corrects PRD assumption "labels relative to the analysed set" to
  "relative to the repo / `--scope`" (ADR 0004 §3); PRD assumption line updated.
- 2026-09-25 — `--by-dir` counts distinct commits, not summed per-file counts (FR-005
  wording said "sum of counts"); a multi-file commit is one commit.
- 2026-09-25 — T009: `coverage.riskOrdered` is present only when `fileRisk` is non-empty
  (never `false`) — "absent → byte-identical" outranks the "gains `riskOrdered`" line;
  readers test `=== true`. `{}` behaves as absent; duplicate keys keep the higher risk.
- 2026-09-25 — T009a, case 10: ground truth is "the two files hot by prior history"
  (6 fixes each, recent), not "files re-fixed within the next 8 weeks" — with the setup
  script visible in the prompt, future fixes would leak the answer. SC-004's base rate on
  the synthetic case is therefore 2/5; the future-fix form of the metric is only
  measurable by hand on a real repository (T016's public-repo measurement). All four
  cases share the case-01 limitation that commit subjects are readable in the prompt.
- 2026-09-25 — T004: `--diff` uses plumbing (`merge-base` + `diff-tree --name-only`,
  `status --porcelain` under `GIT_OPTIONAL_LOCKS=0`) — porcelain `git diff` rewrites
  `.git/index` on stale stat info and would break FR-016. Untracked files are not part of
  `--diff`. Window = calendar months (UTC), inclusive edge. Config merges per key
  (repo > umbrella > default); invalid regex / non-positive window in the file → default.
- 2026-09-25 — round 2: `allow_abbrev=False` on every parser — argparse prefix matching let
  a renamed `--by-dir` still parse, so the prose-drift guard proved nothing until abbreviations
  were rejected (small user-facing tightening). `structure` has three states `ok | partial |
  unknown`. When trajectory is unavailable (shallow) rows carry `null` trajectory fields and
  `risk: null` (sorts below `low`); structure still works from `ls-files`. Only the root
  `tsconfig.json`/`jsconfig.json` is read (`extends` ignored); an alias whose target is missing
  counts as unresolved. `blast` without FILE and without `--diff` is a usage error. `--by-dir`
  emits `dirs` and an empty `files`; root files group under `.`. `hotspots --blast` seeds are
  the selected rows before `--top`, limit fixed at 50. On docs-heavy repos the table's
  `unknown seeds` line is long (capped at 10 + count) — honest, but a polish candidate.
- 2026-09-25 — review round 1: labels treat zero as always `low` and run the quartiles over
  the non-zero values (fewer than four non-zero: all `mid`) — a zero-heavy population no
  longer makes one commit `top` (ADR 0004 consequences).
- 2026-09-25 — review round 2: a non-zero population with no spread (q1 == q3) labels its
  plateau `mid` (not `low`), matching the fewer-than-four rule; a value above it stays `top`.
- 2026-09-25 — T009a pilot (pre-change tree, 1 run): case 09's two `not_contains` graders
  punished a correct answer that named the ruled-out files — removed; the LLM
  "no false positives" claim carries weight 1. Case 11's `max_turns: 10 / 180 s` timed out
  before the edit (0 in both arms = under-set budget, not a plugin result) — raised to
  20 / 420 s. Case 08 is a ceiling case (both arms 1.00 by reading the code); kept as a
  regression guard. Case 10: both arms exhausted 30 turns / 600 s doing a code review instead of a
  ranking — the ask now says "don't review the diff contents… numbered list, one line of
  evidence each", budget 40 / 900 s. Pilot cost (4 cases × 2 arms × 1 run): $2.83.
  On v0.12.1 no shipgate skill fired in any with-arm (`Skill called 0x` ×4) — the baseline
  tree does not trigger on these prompts; the wired-tree Δ therefore also measures triggering.
  Baseline for 09, 10 and 11 re-run after the change.
- 2026-09-25 — eval harness on this host: (a) it refuses Bash cases while `~/.aws`/`~/.docker`
  hold symlinks (no flag; worked around with a scratch `HOME` + `claude setup-token`, run by
  the user); (b) inline `git init` in the prompt cannot work — the agent sandbox blocks the
  Xcode git shim's `xcrun` cache write, so fixtures moved to `case.yaml` →
  `context.scaffold_script: fixture.sh` (`--scaffold`); (c) the agent's own `git log` dies
  the same way until a non-shim git is on PATH (`brew install git`). 6/24 v2-baseline runs
  and 4/6 wired case-10 runs were such deaths — every 0.00 was checked against its trace
  before being discarded. Judge pinned to sonnet (`--judge-model sonnet`; default is haiku).
- 2026-09-25 — triggering: in ~60 runs on naturally-phrased prompts no shipgate skill fired
  (`Skill called 0x`, with-arm, both v0.12.1 and v0.13.0), so the with-arm never ran
  `signals.py` and Δ on cases 08–10 measures triggering, not the signals. Added
  explicit-invocation variants 12–14 (same fixtures/graders; the prompt names the skill;
  `skill-fired` scored, `min: 1`) so SC-004/005 can be evidenced on the signals path.
  Triggering itself is a follow-up (skill descriptions vs these asks).
- 2026-09-26 — Gate-2 calibration: the `hot-files-top-two` LLM rubric (cases 10/14) failed
  transcripts that ranked promo.ts/calendar.ts #1/#2 (judge votes FAIL ×3 on correct answers,
  inconsistent across identical content). Replaced the decisive claim with two regex graders
  (`rank1-is-hot-file`, `rank2-is-hot-file`: the #1 and #2 list items name a hot file) and
  narrowed the LLM rubric to evidence quality at weight 0.5. Re-scoring every clean v3/v4
  transcript with the regexes: case 14 — v0.13.0 with signals 6/6 top-two correct; v0.12.1
  same skill 2/6; no plugin 3/6 (refusal runs excluded). Case 10 (no skill fires): 3/4 · 3/6 · 1–2/6 (coin-flip).
  Also: explicit prompts 12–14 gained "if that skill isn't available, do it yourself" so the
  no-plugin arm answers instead of refusing (v3 no-plugin 0.40/0.00/0.33 were refusals).
- 2026-09-25 — pre-existing failure on `main`, not this change:
  `test_journal.TestBriefRendering.test_an_imported_event_type_cannot_add_lines_to_the_brief`
  (expected string drifted from the brief renderer). Ledger follow-up; full suite = 1 failure
  before and after.

## Follow-ups (not in this change)

- **Skill triggering on natural prompts** (fixed in v0.13.1, `fix/skill-triggering`) — `structured-debug` / `route-and-map` / `review`
  did not fire in any of ~60 eval runs on "which file has the bug" / "what does this change
  affect" / "rank these files by risk" asks (both v0.12.1 and v0.13.0). The signals only
  reach the user when the flow is invoked explicitly. Needs its own look at the skill
  descriptions (or the `feature` orchestrator's routing); evals 08–10 are the regression test.
- `tests/test_journal.py::TestBriefRendering::test_an_imported_event_type_cannot_add_lines_to_the_brief`
  fails on clean `main` — expected string drifted from the brief renderer.
- `signals.py` clears only `GIT_DIR`/`GIT_WORK_TREE`; `hooks/session_start.py` drops every
  `GIT_*` — align on one convention.
- `signals.py`'s config reader follows a symlinked `.claude/shipgate.md`; `lstat` it like
  `_read_text` does (bounded today: only three backticked, validated values).
- Evals 01–07 (structured-debug suite, separate work) still use inline `git init` in the
  prompt and cannot pass in this harness — convert to `scaffold_script` like 08–14.

## Rejected findings

Round 1 (workflow `wf_061de667-a56`, 3 lenses, 36 → 32 → 22 above floor; refuters killed
none — the HIGH held). Coordinator kills, with reason:

- `review-workflow.js:139` fileRisk keys collide on the last 3 path segments — inherited
  from `dedupe`'s `normalizePath`; documented, higher risk wins on collision; LOW, not fixed.
- `signals.py:672` style drift (function-local imports, trivial wrapper) — cosmetic; ledger.
- `signals.py:161` non-integer `Window` silently defaults — by design (documented, source
  echoed); not a defect.
- `signals.py:263` ReDoS via the project's own fix-pattern regex — the config is the user's
  own repo file; no untrusted input path.
- `signals.py:1213` `indent=2` vs journal.py's compact JSON — deliberate for a CLI humans
  read; not drift.
- below floor: linear rename-alias assumption, fsmonitor side effect, control chars in
  table paths, `GIT_INDEX_FILE` env, worklog size drift — speculative or cosmetic.
- research note URL contains a GitHub handle — it is the public OSS source citation, not a

Round 2 (workflow `wf_0abfbda8-32d`, correctness lens scoped to the round-1 fix sites; 10 → 6
above floor, no HIGH). Six fixed (R1–R6, see Deviations). Coordinator kills:

- `signals.py:380` `_unquote` decodes with `replace` while the stream uses `surrogateescape` —
  with `core.quotepath=off` git quotes only control characters, so a non-UTF-8 path is never
  quoted and the mismatch cannot occur; not a defect.
- `signals.py:877` Windows: no `O_BINARY`, `O_NOFOLLOW`/`O_NONBLOCK` fall back to 0 — the
  `lstat` `S_ISREG` check still guards the read; the plugin's hooks are POSIX-first already.
- `signals.py:207` umbrella lookup may read an enclosing dotfiles repo's config — by the
  design's umbrella definition (parent inside a git work tree); documented, not changed.
- `signals.py:1445` `blast`'s trajectory block says `shallow`/`empty-history` rather than
  `not-requested` when the repo has that state — the more informative value; fine.
  private handle; the public-repo rule targets private-project people.
