# Changelog

All notable changes to the **shipgate** plugin, newest first.

v0.13.1 — skill triggering on natural prompts. The v0.13.0 signals only reached users who
typed `/shipgate`: on naturally phrased asks ("which file most likely has the defect?", "what
could the change at HEAD affect?", "rank the changed files by regression risk") no shipgate
skill fired in any of ~60 eval runs, because each description said where the skill sits in the
flow ("first step of any feature", "final pre-push review", "agree a fix before changing code")
rather than what a user asks for, and none named the capability a plain read cannot give. The
`structured-debug`, `route-and-map` and `review` descriptions are rewritten around the asks
and the computed signals, with a negative trigger for trivial one-line edits; each skill body
gains a short **Standalone asks** note so an invoked skill answers the question and stops (no
branch, no fix plan, no reviewer fan); `feature`'s description sends standalone questions to the
phase skill instead of the orchestrator. Evals 08–11 are the regression test; no script or hook
changed.

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

v0.12.1 — hooks file cleanup. `hooks/filechanged.json` carried its explanatory note under a
`_comment` key, which Claude Code's hooks loader reports at every session start as
`hooks.json: unknown key "_comment" ignored`. The note now lives under `description`, the
documented top-level field for a plugin hooks file. No behaviour change.

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

v0.9.0 — config-declared tooling: new **Code tooling** section (a library-docs
tool/MCP for dependency APIs + an LSP tool for symbol navigation — wired into implement's
reuse step, structured-debug's evidence sources, and worker briefs) and new **Thinking
lenses** section (map phases to lens skills to actually invoke; default remains
apply-the-idea-inline). Hardcoded `thinking-skills` plugin references removed — the two
review/design agents can't invoke skills, so their lens guidance is now inline; main-session
lens invocation is config-routed.

v0.8.0 — project bootstrap: the `setup` skill (interview → writes `.claude/shipgate.md`,
a generated `.claude/shipgate.json` sidecar, and initializes the flow journal) and the
flow journal itself — the authoritative per-branch position (phase, tasks, verifies, gate
decisions) that the orchestrator routes from instead of rescanning worklogs.

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
