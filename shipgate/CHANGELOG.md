# Changelog

All notable changes to the **shipgate** plugin, newest first.

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
