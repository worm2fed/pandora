---
name: model-tiers
description: Use when starting implementation in an orchestrating session, when a task is big enough to split across workers, when writing a worker brief, or when asked to "dispatch this to workers", "orchestrate the implementation", "delegate the coding", or "spawn workers for this". Matches model cost to judgment density — the master session orchestrates (analysis, design, review, dispatch) instead of typing product code, implementation goes to worker subagents one tier below the session's model, and workers hand mechanical sub-work down (cheaper model, or low effort).
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
| **Implementer** | worker subagents on the strongest model *below the orchestrator's tier* (a session on the top available tier dispatches workers one tier down (e.g. `model: "opus"`); a session already on Opus dispatches `model: "sonnet"` — or same-tier workers where isolation, not cost, is the point) | design-sensitive coding: seams, encodings, debugging, anything where a wrong call is expensive | grind through bulk mechanical edits itself |
| **Mechanic** | subagents on the cheapest capable tier (`model: "sonnet"`, or `haiku` for the truly trivial) | bulk migrations, repetitive multi-file edits, long test-output collection | make design decisions |

**Effort is the second lever, alongside model.** Agent definitions take an `effort:`
frontmatter field (`low`–`max`; inherits the session's level when omitted), and Workflow
scripts take `opts.effort` per agent call. Mechanical dispatches run at `low` — on current
models a strong model at low effort often beats a weaker model at high, so before sinking
work a tier down, consider sinking the *effort* instead. Keep default/high effort for
design-sensitive work and verification.

**Workflow agents need the model passed explicitly.** A `Workflow` script's `agent()` call
inherits the *session's* model when `opts.model` is omitted — which puts workers on the
orchestrator's tier and quietly breaks the table above. So every shipgate script takes
`model` in its `args` and passes it to each `agent()` call, and every skill that invokes one
sets it to one tier below the session. Effort follows the same split as anywhere else:
`effort: 'low'` for mechanical stages, default effort for the verify and judge stages, where
the whole point is judgment.

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
- **Environment repair is yours, between rounds.** Clean installs, test-DB recreation,
  stale-state suspicion — a worker diagnosing a broken environment burns its run on work
  that was never its task. When a worker's failure smells environmental, take the repair
  yourself and re-dispatch, don't let the worker debug the harness.
- **Review before anything is staged.** Read the worker's diff against the design
  artifacts (ADR, worklog, PRD) and check the evidence in its report (real command output).
  Commit to the delegation: acceptance-check, don't re-derive the worker's findings or redo
  its work. Staging/committing stays under the user's explicit go-ahead as always.

## The worker brief — every dispatch includes

A worker starts with zero context; the brief must be self-contained:

1. **The design spec inline** — the relevant ADR/worklog excerpt pasted in, not a pointer
   to "the design doc". Workers shouldn't re-derive decisions. Also point at the **source
   artifacts** the excerpt digests (the contract, the legacy code, the issue) and invite
   the check: your digest is a transcription, the artifact outranks it — a worker that
   finds the brief contradicting the artifact reports the conflict and gets credited,
   not corrected.
2. **Files to read first** (absolute paths) and the conventions that apply (per-service
   CLAUDE.md rules, house style, test commands). If the project config's Style section names
   a style skill, instruct the worker to invoke it before writing code. Tell it to **mirror
   the vetted reference implementation the design names** — the nearest sibling is not
   automatically a pattern source (scaffolds and stubs encode garbage), and a previous
   slice's output is a source only for the surfaces that were actually reviewed. The brief
   may carry the risk-signal table for the dispatched area
   (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <area> --by-dir 2`) — your
   call per dispatch; it is context on which files are fragile or load-bearing, not an
   instruction to rank by it. Unavailable (see the JSON's `reason`, `trajectory.reason`,
   `structure.reason`) → leave it out.
3. **Branch check** — the worker must verify it is on the expected branch before editing,
   and stop if not.
4. **Validation commands** — the exact lint/test/build commands that prove the task done,
   and the instruction to run them and read the output. Use **workspace-level scripts**
   (the repo's `lint:check`-style commands), never per-file tool invocations — per-file
   runs miss project-context rules the pre-commit hook will catch. When the task touches
   shared runtime, include a **baseline**: run the affected suite once before changes,
   compare after — the bar is zero *new* failures. Also name the config's **Code
   tooling** integrations (the library-docs tool for dependency APIs, the LSP tool for
   symbol navigation) so workers use them instead of grep-and-memory.
5. **No commit, no staging** — the worker leaves changes in the working tree for
   orchestrator review.
6. **Report-back format** — evidence (real command output, not "tests pass"), deviations
   from the brief with reasons, and blockers quoted verbatim. A worker that hit a wall
   reports the wall; it does not improvise a different design.
7. **The config's Worker guardrails section, pasted word-for-word.** Not summarized, not
   trimmed to the rules you judge relevant, not rephrased in your own voice — compression of
   a guardrail is how every recorded worker incident happened (a repo-wide formatter run over
   unrelated files, a release build where a dev build was meant, a user's staged review
   markers reset). The paste is the mechanism; your paraphrase is the failure. No such
   section in the config ⇒ say so in the brief rather than inventing rules. A section still
   holding the template's `<e.g. …>` placeholders counts as absent: say that too, and never
   paste a placeholder into a brief as though it were this project's rule.

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

A worker that just finished holds context a fresh spawn would pay to rebuild. Choose deliberately:

- **Reuse warm** (SendMessage the existing worker) for a follow-up in the same area — a
  review fix-up, the next task in the same module. But only the *same changeset* counts as a
  follow-up: the **next changeset spawns cold**, however convenient reuse looks. Write every
  follow-up **self-sufficiently** — full fix list inline plus "re-read the worklog" — so the
  worker's memory is a bonus, never a dependency: one that finished a heavy round may resume
  compacted, remembering less than its transcript suggests.
- **Spawn cold** when the task needs *different* context, or when the held context would bias
  the approach (it should re-derive from the design, not from its own earlier attempt).
- **Retire on degradation** — roughly **~400k tokens or 4-6 rounds** (thinking stretches to
  minutes, quality drops), *or* on **amnesia symptoms** at any token count: re-litigated
  decisions, violated constraints the brief restated, re-asked settled facts. Then kill it and
  cold-spawn a **finisher briefed off the worktree state** (the actual files + worklog), never
  off the old transcript. Judge health and liveness by artifacts — file mtimes, process state,
  test output — not transcript chatter. And split oversized rounds *up front*: two big jobs in
  one dispatch is how a worker arrives at round 2 already compacted.

## When NOT to apply

- The change is smaller than the dispatch overhead (one-file fix, typo, config tweak) —
  briefing a worker for three lines costs more than typing them. Say you're editing
  directly and why.
- The work has no mechanical component — nothing to sink; a single implementer context
  handles it end to end.
