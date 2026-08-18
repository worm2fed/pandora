---
name: model-tiers
description: Match model cost to judgment density — the master session orchestrates (analysis, design, review, dispatch) instead of typing product code, implementation goes to worker subagents one tier below the session's model, and workers hand mechanical sub-work down (cheaper model, or low effort). Use when starting implementation in an orchestrating session, when a task is big enough to split across workers, when writing a worker brief, or when asked to "dispatch this to workers", "orchestrate the implementation", "delegate the coding", or "spawn workers for this".
---

# Model tiers — orchestrate, don't type

The master session's context is the most expensive context in the run — spend it on
judgment (analysis, design, review, verification), not keystrokes. Push the typing down to
cheaper tiers. The roles are relative, not tied to specific model names (those rotate with
subscriptions): the *master session* orchestrates, *workers* one tier down implement, and
the cheapest capable tier does the mechanical grind.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

| Role | Who | Does | Never does |
|------|-----|------|------------|
| **Orchestrator** | the master session | analysis, design, review, tracker/knowledge-base writes, dispatching workers, checking their evidence | edit product code (when workers are in play) |
| **Implementer** | worker subagents on the strongest model *below the orchestrator's tier* (a top-tier/Fable session dispatches `model: "opus"` workers; a session already on Opus dispatches `model: "sonnet"` — or same-tier workers where isolation, not cost, is the point) | design-sensitive coding: seams, encodings, debugging, anything where a wrong call is expensive | grind through bulk mechanical edits itself |
| **Mechanic** | subagents on the cheapest capable tier (`model: "sonnet"`, or `haiku` for the truly trivial) | bulk migrations, repetitive multi-file edits, long test-output collection | make design decisions |

**Effort is the second lever, alongside model.** Agent definitions take an `effort:`
frontmatter field (`low`–`max`; inherits the session's level when omitted), and Workflow
scripts take `opts.effort` per agent call. Mechanical dispatches run at `low` — on current
models a strong model at low effort often beats a weaker model at high, so before sinking
work a tier down, consider sinking the *effort* instead. Keep default/high effort for
design-sensitive work and verification.

Two invariants survive any model lineup:

1. **The master session orchestrates.** Once work is big enough to dispatch, the session
   doing the thinking does not also do the typing.
2. **Trivial work sinks to Sonnet.** Mechanical, judgment-free sub-work never occupies an
   expensive context — whoever holds it delegates it down.

If the session itself already runs on the same tier as its workers would, dispatch is about
parallelism and context isolation, not cost — apply it when the task splits well, skip it
when it doesn't; the sink-to-Sonnet rule still applies either way.

## Orchestrator rules (master session)

- **Don't edit product code yourself** while orchestrating. Analysis, design artifacts
  (ADR/worklog), tracker and knowledge-base writes, and review are yours; every product-code
  change goes through a worker.
- **Dispatch implementation via the Agent tool** with an explicit `model` (per the tier
  table above), one worker per coherent unit of the build plan. Independent units →
  parallel workers — but **delegation multiplies cost**: each worker re-establishes
  context, and you re-read its report. One worker when one suffices; parallel workers only
  for genuinely independent, sizeable tracks; never delegate work you'd finish yourself in
  a handful of tool calls.
- **Send mid-flight course corrections with SendMessage** to the running worker — don't
  kill and respawn a worker that just needs a directive.
- **Don't idle while workers run.** Their build time is your cheapest design time: spec the
  next round/issue with the user (see the `feature` skill's pipelining rules), answer
  architecture questions, triage the ledger. Interact with workers at natural boundaries
  via SendMessage — never poll them.
- **Review before anything is staged.** Read the worker's diff against the design
  artifacts (ADR, worklog, PRD) and check the evidence in its report (real command output).
  Commit to the delegation: acceptance-check, don't re-derive the worker's findings or redo
  its work. Staging/committing stays under the user's explicit go-ahead as always.

## The worker brief — every dispatch includes

A worker starts with zero context; the brief must be self-contained:

1. **The design spec inline** — the relevant ADR/worklog excerpt pasted in, not a pointer
   to "the design doc". Workers shouldn't re-derive decisions.
2. **Files to read first** (absolute paths) and the conventions that apply (per-service
   CLAUDE.md rules, house style, test commands). If the project config's Style section names
   a style skill, instruct the worker to invoke it before writing code.
3. **Branch check** — the worker must verify it is on the expected branch before editing,
   and stop if not.
4. **Validation commands** — the exact lint/test/build commands that prove the task done,
   and the instruction to run them and read the output.
5. **No commit, no staging** — the worker leaves changes in the working tree for
   orchestrator review.
6. **Report-back format** — evidence (real command output, not "tests pass"), deviations
   from the brief with reasons, and blockers quoted verbatim. A worker that hit a wall
   reports the wall; it does not improvise a different design.

## Implementer rules (worker)

- Keep design-sensitive work at your own level: module seams, data encodings, tricky
  debugging — inline, or in a same-tier subagent if it needs isolation.
- **Delegate mechanical sub-work down** (`model: "sonnet"`, or your own model at
  `effort: low`): bulk migrations, repetitive edits across many files, collecting long test
  output. Give each the same brief discipline scaled down: exact files, exact pattern,
  validation command.
- Check the mechanic's evidence (its validation-command output) before folding its work into
  your report — you own the correctness of everything in your diff, whoever typed it. Require
  evidence rather than re-deriving the work.

## Worker lifecycle — warm vs cold

A worker that just finished a task holds context (files read, conventions learned, cache
warm) that a fresh spawn would pay to rebuild. Choose deliberately:

- **Reuse warm** (SendMessage the existing worker) when the follow-up task lives in the
  same area and benefits from the context it already holds — a fix-up from review, the next
  task in the same module, a variation on what it just built. Reuse skips re-briefing and
  re-exploration entirely.
- **Spawn cold** when the task needs *different* context, when the held context would bias
  the approach (e.g. it should re-derive from the design, not from its own earlier attempt),
  or when the worker is degraded.
- **Retire on degradation.** Long-lived workers degrade past roughly **~400k tokens or 4-6
  task rounds** — thinking stretches to minutes, output quality drops. Retire the worker and
  spawn a **fresh finisher briefed off the worktree state** (the actual files + worklog),
  never off the old transcript. Judge a worker's health and liveness by artifacts — file
  mtimes, process state, test output — not by its transcript chatter.

## When NOT to apply

- The change is smaller than the dispatch overhead (one-file fix, typo, config tweak) —
  briefing a worker for three lines costs more than typing them. Say you're editing
  directly and why.
- The work has no mechanical component — nothing to sink; a single implementer context
  handles it end to end.
