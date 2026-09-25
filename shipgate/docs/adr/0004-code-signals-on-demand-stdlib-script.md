---
type: adr
title: "0004. Code signals: on-demand stdlib script, no index, labels relative to the repo"
created: 2026-09-25
updated: 2026-09-25
tags:
  - adr
status: accepted
date: 2026-09-25
issue: "none / ad-hoc"
related: ["../prd/code-signals.md", "../research/2026-09-25-tearags-vs-shipgate.md", "./0001-sqlite-flow-journal.md"]
---

# 0004. Code signals: on-demand stdlib script, no index, labels relative to the repo

> Per-file risk signals (git trajectory + import graph) come from one bundled, stdlib-only
> script that recomputes on demand, reads its three settings from the `## Code signals`
> section of `.claude/shipgate.md`, labels every number by quartile within the whole
> repository, and writes nothing. Consumers are skill prose plus one optional, inert-when-
> absent argument to the review workflow. No index, daemon, cache or external provider.

## Context

The flow's intelligence is declared (CLAUDE.md, ADRs, journal); nothing computes what the
code and its history say. Tools that do (TeaRAGs-style retrieval layers) require a daemon,
an embedding runtime and ~1 GB of state per repo — incompatible with shipgate's
no-dependencies contract and single-repo by design. The user scoped this round to the
historical and structural axes only; the semantic axis and any external provider are out
(gate decisions, 2026-09-25). Four forks had to be settled: where configuration is read,
what population the relative labels are computed over, whether results persist, and how
the review workflow consumes risk. Decided in executive mode from two architect blueprints
(minimal-change, pragmatic-balance); the user can veto.

## Decision

1. **One script, `scripts/signals.py`, stdlib only**, in the mould of `scripts/journal.py`
   (argparse subcommands, `--json`, typed exit codes 0/1/2). Subcommands `hotspots`,
   `blast`, `suspects`. Language support is a small adapter table (extensions, extract,
   resolve) — TS/JS, Python, Go in v1 — not a class hierarchy.
2. **The script reads its own config.** It parses only the `## Code signals` section of
   `.claude/shipgate.md` (three backticked bullets: window, fix pattern, extra excludes;
   `<placeholder>` counts as absent; flags override) and echoes the effective values and
   their source in the JSON. This is the first script to read the prose config — ADR 0001
   kept hooks off prose for the session-start no-op path; this script runs on demand, and
   the alternative (skills translating config into flags) makes the terminal and the flow
   disagree, defeating FR-014.
3. **Labels are quartiles over the whole repository** (or an explicit `--scope`), never
   over the rows being printed. Positional paths and `--diff` filter output only. This
   corrects the PRD's "analysed set" assumption: quartiles over a three-file diff carry no
   meaning, and the full-history pass is needed for age anyway.
4. **"Now" is HEAD's committer time**, not the wall clock, so two runs on the same state are
   byte-identical (SC-007) and fixtures are deterministic.
5. **No persistence.** Recomputation is a single streamed `git log --name-status -M` pass
   plus one import scan; a cache would be a write outside the plugin directory and a
   freshness problem. If a repository misses the SC-001 bound, the escape hatch is dropping
   rename following, not adding a cache.
6. **Review consumes risk through one optional argument.** `review-workflow.js` gains
   `args.fileRisk` (`{path: low|mid|high|top}`); the finding comparator tie-breaks on risk
   after severity and confidence, and the refuter budget is spent severity → risk →
   confidence. Risk never overrides severity. With the argument absent the output is
   byte-identical to today. Every other consumer (route-and-map, structured-debug,
   implement, design, briefs) is prose.
7. **Output shape is versioned** (`"version": 1`); author identity never appears (counts
   and top-author share only); unsupported files report `structure: unknown` with null
   counts, unresolved relative imports mark a file `partial`.

## Alternatives considered

- **Skills pass config as flags; script is config-blind** (minimal-change). One fewer parser
  and no prose-reading precedent, but a user running the CLI by hand silently gets defaults
  while the flow uses the project's values. Rejected for FR-014.
- **Config via the `.claude/shipgate.json` sidecar.** Machine-readable and already read by
  `journal.py`, but the sidecar exists only on journaled projects and FR-002 requires
  overrides everywhere; it would also pull `setup` into the change. Rejected.
- **Labels relative to the analysed (filtered) set** (PRD assumption). Cheaper to explain,
  meaningless for small sets. Rejected.
- **A persistent index / cache** (TeaRAGs-style, or a lighter `.claude/` cache). Faster on
  huge repos, but state to keep fresh, a write outside the plugin, and the dependency
  profile the plugin exists to avoid. Rejected; revisit only if SC-001 fails on real repos.
- **Method-level granularity via tree-sitter.** Better ranking on god-files; a native
  dependency. Out of scope by the PRD.

## Consequences

- Any project gets risk signals with no install step; umbrella checkouts run the script per
  touched repo (cross-repo import edges are not modelled).
- Import fan-in is a lower bound in alias-heavy or dynamically-imported code; the output
  says so (`partial`, `unresolved`) and the review ordering treats risk as a tie-break within
  a severity band only, so an undercount can cost a file its place in the refuter budget
  within its band but never changes a severity or drops a finding.
- A hand-edit of `## Code signals` that drops the backticks falls back to defaults; the
  echoed `config.source` is the guard, and a skill-prose drift test keeps every
  `signals.py …` invocation in the skills parseable.
- The full-history pass grows linearly with commit count; SC-001 is measured on a
  generated 20k-commit repository and by hand on a large public one, both recorded in the
  worklog before the skills are wired.
- Labels: zeros are always `low`; quartiles run over the non-zero population, so a single
  commit in a dormant repo is not `top`.
- Supersedes nothing; extends ADR 0001's "stdlib script, no server" rule to a second
  script and relaxes its "no prose parsing" to "not on the session-start path".
