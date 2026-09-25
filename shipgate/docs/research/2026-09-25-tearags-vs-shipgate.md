---
title: TeaRAGs vs shipgate — codebase intelligence without an index
date: 2026-09-25
status: research note — informs a PRD/ADR, decides nothing by itself
sources:
  - https://habr.com/ru/articles/1084028/
  - https://github.com/artk0de/TeaRAGs-MCP
---

# TeaRAGs vs shipgate

## What TeaRAGs is

An MCP server (`tea-rags`, MIT, npm) that indexes **one** repo into three representations
and exposes ~23 tools and 23 ranking presets, plus a Claude Code skill layer.

| Axis | Storage | Answers |
|---|---|---|
| Semantic — tree-sitter AST chunks (method-level) → dense embeddings + BM25 | embedded Qdrant | "find code about X" across synonym gaps (`hybrid_search`, `find_symbol`) |
| Structural — call graph, fan-in/out, PageRank, cycles, transitive impact | DuckDB | `get_callers`, `get_callees`, `trace_path`, `find_cycles` → blast radius |
| Historical — churn, bug-fix rate, age, ownership; per-repo relative thresholds | git | presets `proven`, `hotspots`, `bugHunt`, `blastRadius`, `techDebt`, … |

The skill layer (`explore`, `bug-hunt`, `data-driven-generation`, `risk-assessment`,
`mr-review`) exists mainly as a **search cascade**: a decision table telling the agent when
to call which tool, because agents otherwise ignore the index and fall back to grep.

Cost of admission: Node 22+, Ollama/ONNX embeddings (or a cloud key), ~1 GB disk and ~1 GB
RAM per repo, ~22 min full index on 3.5M LoC with a GPU, single-repo only, deep call graph
only for TS/JS/Ruby/Python. The author states that **no benchmark** exists for the
trajectory + graph contribution; the "40 s vs 10 min" bug-localization figure is anecdote.

## Where shipgate stands per axis

- **Semantic:** none. `code-explorer` (Glob/Grep/Read) is the semantic layer — an LLM doing
  synonym expansion over grep. `implement`'s reuse step is "grep before writing", which is
  exactly where the synonym gap bites (`retry` vs `backoff`).
- **Structural:** *declared*, not computed. `route-and-map` derives the impact map from
  CLAUDE.md routing rules; the explorer traces control flow by reading. `config-template.md`
  already anticipates an LSP (`findReferences`) under `## Code tooling`, but nothing
  computes fan-in or transitive importers.
- **Historical:** point-wise only — `structured-debug` uses `git log -S` / `blame` /
  `bisect` for one known defect. No repo-wide churn or fix-rate signal; `review` does not
  rank a diff's files by risk; `design` cannot tell a proven precedent from a fragile one.

Gap ranking: **historical (largest, cheapest to close) > structural (medium) > semantic
(smallest gap, most expensive to close properly).**

## Same intelligence without TeaRAGs

Zero-dependency (git + python stdlib) — shipgate's contract is "no hard dependencies; hooks
no-op when not applicable", so a Qdrant + Ollama daemon is a philosophy violation, not just
a cost.

1. **Historical → a bundled `scripts/trajectory.py`** (like `journal.py`). One
   `git log --numstat` pass, file-level, seconds on any repo: commits in window, fix-rate
   (share of touching commits matching `fix|bug|hotfix|revert`), age, distinct authors /
   ownership concentration, LOC. Emit **relative** labels (percentile within this repo).
   Recovers `hotspots`, `proven`, `abandonedHotspots`, `fragileSilo`, `bugHunt` at file
   granularity; loses method-level resolution. Consumers: `route-and-map` (risk per touched
   module), `review` (reviewer attention and refuter budget ordered by hotspot score),
   `structured-debug` (suspect list = high fix-rate ∩ recently changed ∩ near the trace),
   `design` (which precedent is battle-tested).
2. **Structural → import graph + LSP, not a call graph.** A per-language import scanner
   (TS/JS, Python, Go, Ruby) gives file-level fan-in/fan-out and transitive importers of
   `git diff --name-only` = blast radius. Symbol-level callers come from the already-planned
   LSP slot on demand. Skip cycles / PageRank / `trace_path`.
3. **Semantic → do not rebuild embeddings.** (a) Treat the synonym gap as *captured
   knowledge*: a domain glossary (term → code names) captured by `knowledge-base` and
   recalled at Route & Map. (b) Put a symbol inventory (`ctags`/`rg`-derived exported
   symbols for the touched modules) in explorer briefs. (c) Explorer brief line: "enumerate
   5 domain synonyms before grepping."
4. **Cascade → already exists.** shipgate's phases are the cascade; wire signal consumption
   into the phase that needs it rather than adding search skills.

Rough size: two scripts (~400–500 lines with tests), touches to 4–5 skill files, one config
section. No index, no daemon, no GPU; works on umbrella checkouts (TeaRAGs is single-repo).

## Where they diverge

| | TeaRAGs | shipgate |
|---|---|---|
| Kind of intelligence | computed — what code and history say | declared — what the team decided (CLAUDE.md, ADRs, PRDs, journal) |
| Unit of memory | the index, rebuilt from the repo | the flow: gate decisions, verdicts, who decided |
| Shape | retrieval layer; "provides data, doesn't prescribe" | process layer with gates; no retrieval |
| Dependencies | Node, Ollama/ONNX, Qdrant, DuckDB, ~1 GB | none |
| Scope | single repo | repo or umbrella |
| Skill overlap | explore / bug-hunt / data-driven-generation / mr-review / risk-assessment | Explore / structured-debug / implement reuse step / review / route-and-map |
| Review | rank diff hunks by risk | lens reviewers + evidence-required refuters + AC check |
| Reuse | "find the proven pattern" via presets | grep before writing + architect precedent |
| Evidence for claims | none (stated by the author) | journal `stats`, verify-run evidence |

Complements, not rivals. The right posture is the one shipgate already takes with LSP,
library docs and thinking-skills: an **optional, config-named integration**
(`## Code tooling → Code signals`) — `route-and-map` → `trace_path`/`get_callers`,
`review` → `rank_chunks blastRadius`, `structured-debug` → `bugHunt`, `implement` →
`proven`; absent → the bundled git-trajectory script.

## Evaluating custom vs TeaRAGs

Ground truth is in git history of any OSS repo. Three arms — shipgate alone / + trajectory
script / + TeaRAGs MCP — as two `claude plugin eval --ablation with-without` suites. Cases,
each with a verifiable outcome grader:

1. **Bug localization** — historical bug report → name the file(s); grader: regex on the
   files the real fix commit touched.
2. **Reuse detection** — "add retry to X" where a differently-named helper exists; grader:
   `not_contains` a new implementation + `contains` the existing helper's name.
3. **Blast radius** — given a diff, list affected modules; grader: overlap with the
   transitive-importer set computed offline.
4. **Risk-ranked review** — rank a real commit's files by risk; ground truth: which of them
   received a `fix` commit in the following N weeks. The only case where the historical
   axis can prove itself — and the one TeaRAGs never ran.
5. **Negative** — a one-line typo fix that must not trigger an index round-trip.

Side channels: latency, cost, tool-call count, and a fixed **setup cost** column (index
time, disk, deps).

Prediction to falsify: the script closes most of Δ on 1, 4, 5; TeaRAGs wins 2 and wins 3 on
DSL-heavy Ruby; the setup column makes it unjustifiable as a default.

## Recommendation

1. Build the git-trajectory + import-graph signals into shipgate (zero deps). Full flow:
   PRD + one ADR (computed signals vs declared knowledge; bundled script vs MCP dependency).
2. Integrate, don't depend: TeaRAGs as an optional `Code tooling` entry, falling back to (1).
3. Run the eval before shipping (2); it also decides whether (1) is enough.
