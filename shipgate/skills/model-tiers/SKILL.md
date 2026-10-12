---
name: model-tiers
description: Use when starting implementation as the orchestrator, when a task is big enough to split across workers, when writing a worker brief, or when asked to "dispatch this to workers", "orchestrate the implementation", "delegate the coding", or "spawn workers for this". Matches model cost to judgment density — the orchestrator does the judgment work (analysis, design, review, dispatch) instead of typing product code, implementation goes to worker subagents one tier below the session's model, and workers hand mechanical sub-work down (cheaper model, or low effort).
---

# Model tiers — orchestrate, don't type

The orchestrator's context is the most expensive context in the run. Spend it on judgment
(analysis, design, review, verification), not keystrokes. Push the typing down to cheaper
tiers. The roles are relative. They are not tied to specific model names, because those
rotate with subscriptions. The *orchestrator* directs. *Workers* one tier down implement. The
cheapest capable tier does the mechanical grind.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

| Role | Who | Does | Never does |
|------|-----|------|------------|
| **Orchestrator** | the session running the flow | analysis, design, review, tracker and knowledge base writes, dispatching workers, checking their evidence | edit product code (when workers are in play) |
| **Worker** | subagents on the strongest model *below the orchestrator's tier* (a session on the top available tier dispatches workers one tier down (e.g. `model: "opus"`); a session already on Opus dispatches `model: "sonnet"` — or same-tier workers where isolation, not cost, is the point) | design-sensitive coding: seams, encodings, debugging, anything where a wrong call is expensive | grind through bulk mechanical edits itself |
| **Mechanic** | subagents on the cheapest capable tier (`model: "sonnet"`, or `haiku` for the truly trivial) | bulk migrations, repetitive multi-file edits, long test-output collection | make design decisions |

**Effort is the second lever, alongside model.** Agent definitions take an `effort:`
frontmatter field (`low`–`max`). When the field is omitted, the agent inherits the session's
level. Workflow scripts take `opts.effort` per agent call. Mechanical dispatches run at `low`.
On current models, a strong model at low effort often beats a weaker model at high effort. So
before you sink work a tier down, consider sinking the *effort* instead. Keep default/high
effort for design-sensitive work and verification.

**Workflow agents need the model passed explicitly.** A `Workflow` script's `agent()` call
inherits the *session's* model when `opts.model` is omitted. That puts workers on the
orchestrator's tier and quietly breaks the table above. So every shipgate script takes
`model` in its `args` and passes it to each `agent()` call. Every skill that invokes a script
sets `model` to one tier below the session. Effort follows the same split as anywhere else.
Use `effort: 'low'` for mechanical stages. Use default effort for the verify and judge stages,
where the whole point is judgment.

Two invariants survive any model lineup:

1. **The orchestrator does not type product code.** Once work is big enough to dispatch, the
   session doing the thinking does not also do the typing.
2. **Trivial work sinks to Sonnet.** Mechanical, judgment-free sub-work never occupies an
   expensive context. Whoever holds it delegates it down.

The session itself may already run on the same tier as its workers would. Then dispatch is
about parallelism and context isolation, not cost. Apply it when the task splits well, and
skip it when it doesn't. The sink-to-Sonnet rule still applies either way.

## Orchestrator rules

- **Don't edit product code yourself** while orchestrating. Analysis, design artifacts
  (ADR/worklog), tracker and knowledge base writes, and review are yours. Every product-code
  change goes through a worker.
- **Dispatch implementation via the Agent tool** with an explicit `model`, per the tier table
  above. Dispatch one worker per coherent unit of the build plan. Independent units can go to
  parallel workers. But **delegation multiplies cost**: each worker re-establishes context,
  and you re-read its report. Use one worker when one suffices. Use parallel workers only for
  genuinely independent, sizeable tracks. Never delegate work you'd finish yourself in a
  handful of tool calls.
- **Send mid-flight course corrections with SendMessage** to the running worker. Don't kill
  and respawn a worker that just needs a directive.
- **Don't idle while workers run.** Their build time is your cheapest design time. Design the
  next round/issue with the user (see the `feature` skill's pipelining rules). Answer
  architecture questions. Triage the ledger. Interact with workers at natural boundaries via
  SendMessage. Never poll them.
- **Environment repair is yours, between rounds.** This covers clean installs, test-DB
  recreation and stale-state suspicion. A worker diagnosing a broken environment burns its run
  on work that was never its task. When a worker's failure smells environmental, take the
  repair yourself and re-dispatch. Don't let the worker debug the harness.
- **Review before anything is staged.** Read the worker's diff against the design artifacts
  (ADR, worklog, PRD). Check the evidence in its report (real command output). Commit to the
  delegation: acceptance-check, and don't re-derive the worker's findings or redo its work.
  Staging/committing stays under the user's explicit go-ahead as always.

## The worker brief — every dispatch includes

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

A worker starts with zero context, so the worker brief must be self-contained:

1. **The design inline** — paste in the relevant ADR/worklog excerpt, not a pointer to "the
   worklog". Workers shouldn't re-derive decisions. Also point at the **source-of-truth
   artifacts** the excerpt digests: the contract, the legacy code, the issue. Invite the
   check. Your digest is a transcription, and the artifact outranks it. A worker that finds
   the brief contradicting the artifact reports the conflict and gets credited, not
   corrected.
2. **Files to read first** (absolute paths) and the conventions that apply: per-service
   CLAUDE.md rules, house style, test commands. If the project config's Style section names a
   style skill, instruct the worker to invoke it before writing code. Tell it to **mirror the
   vetted reference implementation the design names**. The nearest sibling is not
   automatically a pattern source, because scaffolds and stubs encode garbage. A previous
   slice's output is a source only for the surfaces that were actually reviewed. The brief may
   carry the risk-signal table for the dispatched area
   (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <area> --by-dir 2`). That is
   your call per dispatch. The table is context on which files are fragile or load-bearing,
   not an instruction to rank by it. If it is unavailable (see the JSON's `reason`,
   `trajectory.reason`, `structure.reason`), leave it out.
3. **Branch check** — the worker must verify it is on the expected branch before editing, and
   stop if not.
4. **Validation commands** — the exact lint/test/build commands that prove the task done, and
   the instruction to run them and read the output. Use **workspace-level scripts** (the
   repo's `lint:check`-style commands), never per-file tool invocations. Per-file runs miss
   project-context rules that the pre-commit hook will catch. When the task touches shared
   runtime, include a **baseline**: run the affected suite once before changes, and compare
   after. The bar is zero *new* failures. Also name the config's **Code tooling**
   integrations, so workers use them instead of grep-and-memory: the library-docs tool for
   dependency APIs, the LSP tool for symbol navigation.
5. **No commit, no staging** — the worker leaves changes in the working tree for orchestrator
   review.
6. **Report-back format** — evidence (real command output, not "tests pass"), deviations from
   the brief with reasons, and blockers quoted verbatim. A worker that hit a wall reports the
   wall. It does not improvise a different design.
7. **The config's Worker guardrails section, pasted word-for-word.** Do not summarize it, trim
   it to the rules you judge relevant, or rephrase it in your own voice. Compression of a
   guardrail is how every recorded worker incident happened: a repo-wide formatter run over
   unrelated files, a release build where a dev build was meant, a user's staged review
   markers reset. The paste is the mechanism; your paraphrase is the failure. No such section
   in the config ⇒ say so in the brief rather than inventing rules. A section still holding
   the template's `<e.g. …>` placeholders counts as absent. Say that too. Never paste a
   placeholder into a brief as though it were this project's rule.
8. **Writing style excerpt** — when the task writes a PRD, ADR, worklog line, ledger line,
   MR/PR text or tracker comment, paste the config's **Writing style** section
   (`Docs: plain | ste-80`). When it says `ste-80`, also paste the Writing for people
   callout above verbatim, the way item 7 pastes the guardrails: a worker cannot apply a
   rule it never sees. No such section, or a placeholder ⇒ say `plain`.

## Worker rules

- Keep design-sensitive work at your own level: module seams, data encodings, tricky
  debugging. Do it inline, or in a same-tier subagent if it needs isolation.
- **Delegate mechanical sub-work down** (`model: "sonnet"`, or your own model at
  `effort: low`): bulk migrations, repetitive edits across many files, collecting long test
  output. Give each mechanic the same brief discipline, scaled down: exact files, exact
  pattern, validation command.
- Check the mechanic's evidence (its validation-command output) before you fold its work into
  your report. You own the correctness of everything in your diff, whoever typed it. Require
  evidence rather than re-deriving the work.

## Worker lifecycle — warm vs cold

A worker that just finished holds context that a fresh spawn would pay to rebuild. Choose
deliberately:

- **Reuse warm** (SendMessage the existing worker) for a follow-up in the same area, such as a
  review fix-up or the next task in the same module. But only the *same changeset* counts as a
  follow-up. The **next changeset spawns cold**, however convenient reuse looks. Write every
  follow-up **self-sufficiently**: the full fix list inline, plus "re-read the worklog". Then
  the worker's memory is a bonus, never a dependency. A worker that finished a heavy round may
  resume compacted, remembering less than its transcript suggests.
- **Spawn cold** when the task needs *different* context. Also spawn cold when the held
  context would bias the approach: the worker should re-derive from the design, not from its
  own earlier attempt.
- **Retire on degradation** — roughly **~400k tokens or 4-6 rounds**, when thinking stretches
  to minutes and quality drops. Also retire on **amnesia symptoms** at any token count:
  re-litigated decisions, violated constraints the brief restated, re-asked settled facts.
  Then kill the worker. Cold-spawn a **finisher briefed off the worktree state** (the actual
  files + worklog), never off the old transcript. Judge health and liveness by artifacts
  (file mtimes, process state, test output), not by transcript chatter. And split oversized
  rounds *up front*. Two big jobs in one dispatch is how a worker arrives at round 2 already
  compacted.

## When NOT to apply

- The change is smaller than the dispatch overhead (one-file fix, typo, config tweak).
  Briefing a worker for three lines costs more than typing them. Say you're editing directly
  and why.
- The work has no mechanical component. There is nothing to sink, and a single worker context
  handles it end to end.
