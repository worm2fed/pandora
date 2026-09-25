---
type: prd
title: "PRD: Code signals — git trajectory and import-graph risk signals for the flow"
created: 2026-09-25
updated: 2026-09-25
tags:
  - prd
  - shipgate
status: clarified
issue: "none / ad-hoc"
worklog: "./code-signals.worklog.md"
related:
  - ../research/2026-09-25-tearags-vs-shipgate.md
---

# PRD: Code signals

> Give every phase of the flow computed, per-repo risk signals — which files are hot,
> fragile, abandoned or load-bearing, and what a change reaches — from git and the import
> structure alone, with no index, daemon or dependency.

## Problem

shipgate's intelligence is *declared*: CLAUDE.md routing rules, ADRs, PRDs, the journal.
Nothing in the flow knows what the code and its history say about themselves. Consequences
seen in practice and in the comparison note (`docs/research/2026-09-25-tearags-vs-shipgate.md`):

- `route-and-map` estimates blast radius from routing rules and reading; it cannot say
  "this module is imported by 40 others" or "this file has been bug-fixed 6 times this year".
- `review` treats every changed file alike; reviewer attention and the refuter budget are
  spent uniformly instead of on the files most likely to regress.
- `structured-debug` starts hypothesis formation from the report and the stack trace; it
  has no ranked list of historically fragile files near the symptom.
- `implement`'s reuse step and `design`'s precedent choice cannot distinguish a proven,
  stable helper from a fragile one that happens to match first.

Tools that provide these signals (TeaRAGs and similar) do so via an indexed retrieval layer
with a daemon, an embedding runtime and ~1 GB of state per repo — incompatible with the
plugin's no-dependencies contract and single-repo by design. The signals themselves, at
file granularity, are cheap: one pass over `git log` and one over import statements.

## Goals & non-goals

**Goals**

- Every phase that reads code can obtain, on demand and in seconds, per-file **trajectory**
  signals (churn, fix rate, age, ownership concentration) and **structural** signals
  (fan-in, fan-out, transitive importers of a set of files), labelled *relative to this
  repo*.
- The consuming phases actually change behaviour on those signals: the impact map shows
  risk, review orders its attention, debugging starts from a suspect list, reuse prefers
  proven code.
- Zero new dependencies; the no-git / shallow-clone / unsupported-language cases degrade to
  today's behaviour silently.

**Non-goals** (explicitly out of scope — decided by the user, 2026-09-25)

- The **semantic axis**: no embeddings, no BM25 index, no glossary or symbol inventory
  this round. Synonym-gap navigation stays with the explorers as today.
- **TeaRAGs (or any external signal provider) integration**: no adapter, no config slot
  for one. The eval compares shipgate alone against shipgate with these signals.
- Method-level granularity, call graphs, cycle detection, PageRank, path tracing.
- A persistent cache or index of any kind.

## Users & stories

- As the orchestrator at Route & Map, I want the impact map to carry computed risk per
  touched module so that the design and the reviewers are warned about hot and
  load-bearing code without anyone remembering it.
- As a reviewer (agent or workflow), I want the diff's files ranked by regression risk so
  that the refuter budget and my reading time go to the files most likely to break.
- As the debugger, I want a suspect list ranked by fix history and recency near the
  symptom so that hypothesis formation starts from evidence, not from the first grep hit.
- As an implementer choosing a precedent, I want to know which of two matching helpers is
  old, widely used and rarely fixed so that I copy the proven one.
- As a user, I want to run the same signals from the terminal to sanity-check what the flow
  is reacting to.

## Functional requirements

**Signals**

- **FR-001** — Given a repository path and an optional file/directory set, produce per-file
  trajectory signals: commit count in a window, fix-rate (share of touching commits whose
  subject matches a fix pattern), age (days since first commit), staleness (days since
  last commit), distinct-author count, and top-author share.
- **FR-002** — The fix pattern and the window have defaults (conventional-commit `fix`
  types and common fix/bug/hotfix/revert/regression words; twelve months) and are
  overridable per project in `.claude/shipgate.md`.
- **FR-003** — Every numeric signal is also emitted as a **relative label** computed within
  the analysed repo (e.g. quartile → `low | mid | high | top`), so "high churn" means high
  *for this repo*.
- **FR-004** — Given a repository path, produce per-file structural signals for supported
  languages: fan-in (files importing it), fan-out (files it imports), and, for a given file
  set, the **transitive importer set** (blast radius) with its size. Supported in v1:
  TypeScript/JavaScript, Python, Go. Unsupported files report `structure: unknown`, never
  a wrong number.
- **FR-005** — Signals can be aggregated to a directory/module level (sum of counts, max of
  labels, union of importer sets) so the impact map can speak at module granularity.
- **FR-006** — Output is available as machine-readable JSON and as a compact human table;
  both are stable enough for skills and workflow scripts to consume.
- **FR-007** — Author identity never appears in output by default — only counts and shares.
- **FR-008** — Excluded paths: vendored, generated and lockfile patterns are skipped by
  default, extendable per project.

**Consumption**

- **FR-009** — `route-and-map`'s impact map gains a *Risk signals* section: per touched
  module, the trajectory labels and fan-in, and the blast-radius size of the touched set;
  the `phase-entered route-and-map` journal event carries the essentials (labels and sizes,
  not tables).
- **FR-010** — `review` briefs (Agent fan and Workflow script alike) carry the diff's
  per-file signals, and the refuter budget is spent on findings in the highest-risk files
  first; the coordinator's ranking treats a finding in a `top`-churn / `top`-fix-rate file
  as higher priority at equal confidence.
- **FR-011** — `structured-debug` produces a ranked suspect list (fix-rate × recency ×
  proximity to the symptom's files) before hypothesis formation, and cites it as evidence.
- **FR-012** — `implement`'s reuse step and `design`'s precedent selection prefer, when
  several candidates match, the one with lower fix-rate, higher age and higher fan-in, and
  say so in the choice.
- **FR-013** — Explorer and worker briefs may include the signal table for the area they
  are dispatched into; the orchestrator decides per dispatch.
- **FR-014** — A user-facing CLI exposes the same computations (hotspots for a path,
  blast radius for a file set) so the numbers the flow reacts to can be inspected.

**Degradation**

- **FR-015** — No git repository, a shallow clone, an empty history, or a language with no
  adapter: the consuming phase emits its usual output without the signals section and a
  one-line note of why; no error, no prompt to install anything.
- **FR-016** — The feature writes nothing outside the process (no cache, no state under
  `.claude/` or elsewhere) in v1.

## Success criteria

- **SC-001** — Trajectory signals for a repository of ≥ 300k lines and ≥ 20k commits
  complete in under 15 s; the import graph for the same repository in under 10 s; both on
  a developer laptop, measured and recorded in the worklog.
- **SC-002** — Running any consuming skill on a directory with no git history yields the
  same artifact structure as before this feature minus the signals section, with no
  surfaced error (verified by test).
- **SC-003** — An eval suite under `evals/` covers: bug localization from a historical
  report, blast radius of a diff, risk-ranked review of a real commit (ground truth: files
  of that commit fixed again within the following 8 weeks), and a negative one-line change.
  The suite runs under `claude plugin eval . --ablation with-without`.
- **SC-004** — On the risk-ranked review case, precision@3 of the with-signals ranking is
  at least 2× the base rate (share of the commit's files that were later fixed), across
  three runs.
- **SC-005** — On the bug-localization and blast-radius cases, the with-plugin score of this
  version is not lower than v0.12.1's on the same suite, and the Δ (with − without) is
  reported in the worklog with cost and latency side-channels.
- **SC-006** — No test fixture, doc or example contains a real repository's name, path,
  tracker id or author identity; fixtures are generated by the tests themselves.
- **SC-007** — The relative labels are reproducible: two runs on the same repository state
  yield identical output.

## Constraints & assumptions

- Python 3 standard library only, same as `scripts/journal.py`; invoked via
  `${CLAUDE_PLUGIN_ROOT}/scripts/…` so it resolves after a marketplace install.
- No hook changes. The feature is invoked by skills and by the user, never on session
  start — it stays out of the configured security-sensitive area for `hooks/`.
- Reads only. The repository is the user's; nothing is transmitted or persisted.
- Umbrella checkouts: signals are per repository; the orchestrator runs them per touched
  repo. Cross-repo import edges are not modelled (risky assumption for umbrellas — noted
  for design).
- Renames: file identity follows git's rename detection at the commit level; history before
  a rename is attributed to the new path when git reports it (assumption; verify cost).
- A behaviour change bumps the plugin version (minor) in `shipgate/.claude-plugin/plugin.json`
  and the marketplace entry, in the same PR.

## Assumptions (executive)

- Window for trajectory → 12 months, configurable — long enough for fix-rate to be
  meaningful, short enough that dead history does not dominate.
- Fix detection → commit subject only, conventional-commit `fix` types plus a word list;
  no diff heuristics — subjects are cheap and good enough; false negatives are tolerable.
- Relative labels → quartiles within the whole repository (or an explicit scope); a
  path filter or a diff only selects which rows are shown — corrected at design (ADR
  0004): quartiles over a three-file diff carry no meaning.
- Granularity → file, aggregated to directory on request; no method-level — the note's
  estimate is that file-level carries most of the ranking signal at a fraction of the cost.
- Languages for structure in v1 → TS/JS, Python, Go — import syntax is regular; Ruby
  (Zeitwerk naming) and Java deferred to a follow-up.
- Ownership output → counts and top-author share only, never names — privacy by default,
  and consistent with the public-repo rule.
- Persistence → none in v1 — recomputation is seconds; a cache would be a write outside
  the plugin directory and a freshness problem.
- Review integration → signals delivered as brief content and as `args` to the review
  workflow; the workflow's refuter selection is the one place that changes behaviour
  mechanically.
- Delivery → one PR for scripts + tests + skill wiring + config section + version bump,
  since the wiring is what makes the scripts worth having.
- Eval baseline → v0.12.1 run on the same suite before the change lands, so SC-005 has a
  number to compare against.

## Open questions

None — gate passed 2026-09-25.
