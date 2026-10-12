---
name: implement
description: Execute the build plan task by task, reuse-first, with evidence-based completion. Works tasks in dependency order, greps for existing code before writing new, handles breaking changes deliberately, writes the failing test first, and runs the verify gate before marking any task done. Use when a design + build plan exists and it's time to build the planned tasks.
---

# Implement

Execution discipline is what separates a plan that ships from a plan that rots. Work the
build plan one task at a time. Prove each task is done before you move on. Keep the worklog
honest about what actually happened.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present. If its Style section names a style skill,
> invoke that skill before writing code — and put the same instruction in every worker brief
> (see `model-tiers`).

## Who types the code

Check the `model-tiers` skill first. When the build is big enough to dispatch, the
orchestrator does not work tasks inline. Each coherent unit goes to a worker with a
self-contained worker brief. The orchestrator reviews the worker's diff against the design
before anything is staged. Workers delegate mechanical sub-work to Sonnet subagents. Every
brief carries the config's **Worker guardrails** section pasted verbatim (see `model-tiers`),
because the project's hard rules are not yours to compress. For small builds, work the tasks
directly. Either way, the loop below is what "done" means for each task, whoever executes it.

## The loop (per task)

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
the worklog lines and ledger lines this loop writes (ticks, deviations, notes, jots); absent,
a placeholder, or `plain`, write them as before.

1. **Take the next task** in dependency order from the Build Plan. Respect `[P]` only as a
   signal that tasks are independent. Do not start a task whose prerequisites are unchecked.

2. **Reuse before writing.** Grep the codebase for an existing utility, helper, or pattern
   that already does this. When you integrate a dependency, **read its API surface first**.
   Libraries usually ship the combinator for their own domain (timers, retries, interceptor
   lifecycles). A sibling function in the same module that uses that dependency is the
   template to match. Consult the library-docs integration that the config's **Code
   tooling** section names (if any), rather than trusting memory of the API. For symbol
   navigation in typed code (who calls this, where is it defined), prefer the LSP tool the
   config names over grep-and-read. When several existing candidates match, compare them
   with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <candidate-files> --json`.
   Prefer the proven one: lower `fix_rate`, higher `age_days`, higher `fan_in`. Say so in
   the choice. If the signals are unavailable (see the JSON's `reason`, `trajectory.reason`,
   `structure.reason`), choose on reading alone and say so. The cheapest correct code is the
   code you don't add. Only write new code when nothing fits cleanly. Do not force-fit a
   near-match, but do not reinvent either.

3. **Match the conventions** that exploration surfaced: error handling, validation, DI, the
   stack idioms, naming. New code should look like it was always there. For internal
   anatomy, **mirror the vetted reference implementation the design names**. The nearest
   sibling is not automatically a pattern source, because scaffolds and stubs encode
   garbage. A previous slice's output is a source only for the surfaces that were actually
   reviewed.

4. **Write the test first when there's real behavior.** Whether you add logic or fix a bug,
   write the failing test before the production code. Watch it fail for the right reason: it
   must actually exercise the new behavior or reproduce the bug. Then write the minimum code
   to make it pass. A test that never failed proves nothing; that is the regression guarantee
   in the `verify` skill. For pure mechanical changes (rename, move, config) this is
   overkill; use judgment.

5. **Handle breaking changes deliberately.** If a change alters a signature, schema, or
   contract:
   - In-repo callers: update them atomically in the same change.
   - Public/external APIs: use parallel-change + deprecation, not a hard break.
   - Schema change: run any downstream refresh obligations that the impact map or CLAUDE.md
     names (e.g. regenerating dependent services' schema dumps). Don't leave them stale.

6. **Verify before you check the box.** Invoke the `verify` skill. Run the actual command
   (test, build, lint) for this task. Read the output. Confirm that it proves the task's
   "done when" criterion. No "should work."

7. **Update the worklog — and the ledger.** Tick the task. If you diverged from the design,
   log it in *Deviations & notes* with the reason and impact. A silent divergence is how the
   design and the code drift apart. Then, before the next task, record any learning from
   this task that outlives the feature. Examples: a trap (a default that silently disables a
   feature, a breaking change nothing flagged), a convention you found by grep rather than
   in the docs, a style call you made. Each one is one dated line in the project **ledger**.
   The ledger is the path the config declares, or `docs/ledger.md` when that file already
   exists. Append the line in this step; do not recall it from memory at Capture:

   ```bash
   printf -- '- %s — <gotcha|style|decision>: <one line>\n' "$(date +%F)" >> docs/ledger.md
   ```

   There is no quality gate here, because Capture triages the ledger (see `knowledge-base`).
   Do not write to `CLAUDE.md`. Do not create a new ledger file in a project that has none;
   note the learning in the worklog instead.

## Types round (declarations-first slices)

The design plans a **declarations task** for any slice that introduces new domain shapes.
When the build plan carries one, the slice runs "type, define, refine":

1. **Declare only.** Write types, interfaces, function signatures and table shapes. Bodies
   are `throw new Error('unimplemented')`. No behavior yet.
2. **Gate on the type-check.** The task's `verify` gate is a full, test-inclusive type-check
   that passes. Declarations are verifiable code, not a design document.
3. **Review the declarations alone** before any body task starts. Review them against the
   style skill(s) the config names. A typed-FP canon usually carries a type-review
   checklist: closed vocabularies as unions, totality, no representable invalid
   combinations, branded ids, unconsumed types deleted. The orchestrator can gate a small
   slice directly. A shape-heavy slice gets a reviewer pass.
4. **Reviewed signatures are frozen.** A body task that needs a reviewed signature to change
   escalates back to the orchestrator/design. It does not silently reshape the signature.
   The change lands as a worklog deviation (journaled projects: a `deviation` event). The
   freeze is what makes this a gate rather than a decoration.

Skip this round for slices that only use existing shapes. The round exists for new domain
vocabulary, not for every task.

## Record each task (journaled projects)

On a project whose config declares a **Journal**, step 7 has a second half. Append the task
the moment you tick it, not in a sweep at the end of the plan:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type task-done --data '{"task_id":"T012"}'
```

`task-done` is gate-validated. The journal refuses it unless a passing `verify-run` that
names that task already exists. So the order is: verify, record the verify (see `verify`),
then record the task done. Put both in one `append --batch`, because they close the same
boundary (for the stdin form, see `verify`). A divergence gets its own `deviation` {note}
event beside the worklog line. The event is a pointer and a sentence; the prose stays in
the worklog. The journal refuses a payload over 1 KB to keep it that way. A missing or
unreadable database is an infrastructure failure, not a reason to skip the append. Surface
it loudly. Continue un-journaled only with the user's acknowledgement.

## When to stop and reconsider

- If a task reveals the design was wrong (not just incomplete), stop. Route back to
  `design` rather than improvising a different architecture mid-build.
- If a task reveals a requirements gap, route back to `clarify`.
- If you're tempted to "while I'm here" refactor something unrelated, don't. Note it as a
  follow-up. Keep the change scoped to the plan.
- **Sunk cost**: the same approach has failed twice → stop; no third variant. Ask "would I
  choose this path starting fresh, ignoring the work already done?" If not, route back to
  `design` with what the two attempts proved.
- **Bounded rationality**: before an open-ended search starts (greps, candidate libraries,
  places to hook in), state a "good enough" bar. Stop at the first option that clears it.
  Never use this for a correctness gate: a test, a security check or "did the fix work"
  needs the right answer, not a sufficient-looking one. Never use it for an irreversible
  pick either (a new dependency, a schema).

## Committing

- **Don't commit unless the user asks.** Default to leaving the change for them to review.
  The repo may be dirty in unrelated areas, so the user, not the plugin, decides when a
  commit happens.
- **Stage only the files you actually changed.** Never use `git add -A` / `git add .` here,
  because you'll sweep up someone else's in-flight work. Add explicit paths.
- **Keep commits atomic.** Each commit is one complete, self-contained change that builds
  and passes on its own. It does one logical thing fully, with nothing half-finished and
  nothing unrelated bundled in. This scales by itself. A trivial feature is a single atomic
  commit. A large one is several (per task or group of tasks). Let the size of the change
  decide the count, not a fixed rule.
- **Only commit verified code.** Don't commit a task whose `verify` gate hasn't passed. A
  red commit is a landmine for the next person (and for `git bisect`).
- **Follow the repo's commit conventions.** When a tracker issue exists, reference it
  (`#ID`) the way the repo does. The reference ties the commit back to the
  PRD/worklog/branch trail.
- **Never bypass hooks or signing** (`--no-verify`, unsigned). Hooks are part of how the
  repo stays correct. Routing around them defeats the point of this whole flow.

## On completion

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

When the Build Plan is fully checked and verified, summarize what was built: completed,
skipped, newly discovered, blocked. Confirm that every FR-### / SC-### has been satisfied.
Hand off to `review`. Consider what is worth capturing via `knowledge-base`: a gotcha, a
reusable fix, a convention you had to discover.
