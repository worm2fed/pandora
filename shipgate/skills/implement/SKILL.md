---
name: implement
description: Execute the build plan task by task, reuse-first, with evidence-based completion. Works tasks in dependency order, greps for existing code before writing new, handles breaking changes deliberately, writes the failing test first, and runs the verify gate before marking any task done. Use when a design + build plan exists and it's time to build the planned tasks.
---

# Implement

Execution discipline is what separates a plan that ships from a plan that rots. Work the
build plan one task at a time, prove each task is done before moving on, and keep the
worklog honest about what actually happened.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present. If its Style section names a style skill,
> invoke that skill before writing code — and put the same instruction in every worker brief
> (see `model-tiers`).

## Who types the code

Check the `model-tiers` skill first: when the build is big enough to dispatch, the orchestrator
doesn't work tasks inline — each coherent unit goes to a worker subagent with a
self-contained brief, and the orchestrator reviews the worker's diff against the design before
anything is staged. Workers delegate mechanical sub-work to Sonnet subagents. Every brief
carries the config's **Worker guardrails** section pasted verbatim (see `model-tiers`) — the
project's hard rules are not yours to compress. For small builds, work the tasks directly.
Either way, the loop below is what "done" means for each task — whoever executes it.

## The loop (per task)

1. **Take the next task** in dependency order from the Build Plan. Respect `[P]` only as a
   signal that tasks are independent — don't start a task whose prerequisites are unchecked.

2. **Reuse before writing.** Grep the codebase for an existing utility, helper, or pattern
   that already does this — and when integrating a dependency, **read its API surface
   first**: libraries usually ship the combinator for their own domain (timers, retries,
   interceptor lifecycles), and a sibling function in the same module using that dependency
   is the template to match. Consult the library-docs integration the config's **Code
   tooling** section names (if any) rather than trusting memory of the API; for symbol
   navigation in typed code (who calls this, where is it defined), prefer the LSP tool the
   config names over grep-and-read. When several existing candidates match, compare them
   with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <candidate-files> --json`
   and prefer the proven one — lower `fix_rate`, higher `age_days`, higher `fan_in` — saying
   so in the choice (signals unavailable — see the JSON's `reason`, `trajectory.reason`,
   `structure.reason` — means choosing on reading alone, and saying so). The
   cheapest correct code is the code you don't add.
   Only write new code when nothing fits cleanly — don't force-fit a near-match, but don't
   reinvent either.

3. **Match the conventions** surfaced during exploration — error handling, validation, DI,
   the stack idioms exploration surfaced, naming. New code should look like it was always
   there. For internal anatomy: **mirror the vetted reference implementation the design
   names** — the nearest sibling is not automatically a pattern source (scaffolds and
   stubs encode garbage), and a previous slice's output is a source only for the surfaces
   that were actually reviewed.

4. **Write the test first when there's real behavior.** Whether you're adding logic or fixing
   a bug, write the failing test before the production code: watch it fail for the right reason
   (it must actually exercise the new behavior / reproduce the bug), then write the minimum code
   to make it pass. A test that never failed proves nothing — that's the regression guarantee in
   the `verify` skill. For pure mechanical changes (rename, move, config) this is overkill; use
   judgment.

5. **Handle breaking changes deliberately.** If a change alters a signature, schema, or
   contract:
   - In-repo callers: update them atomically in the same change.
   - Public/external APIs: parallel-change + deprecation, not a hard break.
   - Schema change: run any downstream refresh obligations the impact map / CLAUDE.md names
     (e.g. regenerating dependent services' schema dumps). Don't leave them stale.

6. **Verify before you check the box.** Invoke the `verify` skill: run the actual command
   (test, build, lint) for this task, read the output, confirm it proves the task's
   "done when" criterion. No "should work."

7. **Update the worklog — and the ledger.** Tick the task. If you diverged from the design,
   log it in *Deviations & notes* with the reason and impact — a silent divergence is how
   the design and the code drift apart. Then, before the next task: anything this task
   taught you that outlives the feature — a trap (a default that silently disables a
   feature, a breaking change nothing flagged), a convention you found by grep rather than
   in the docs, a style call you made — is one dated line in the project **ledger** (the
   path the config declares, or `docs/ledger.md` when that file already exists), appended in
   this step, not recalled from memory at Capture:

   ```bash
   printf -- '- %s — <gotcha|style|decision>: <one line>\n' "$(date +%F)" >> docs/ledger.md
   ```

   No quality gate here — Capture triages it (see `knowledge-base`). Not `CLAUDE.md`, and
   no new ledger file in a project that has none: note the learning in the worklog instead.

## Types round (declarations-first slices)

When the build plan carries a **declarations task** (the design plans one for any slice
introducing new domain shapes), the slice runs "type, define, refine":

1. **Declare only.** Types, interfaces, function signatures, table shapes — bodies are
   `throw new Error('unimplemented')`. No behavior yet.
2. **Gate on the type-check.** The task's `verify` gate is a full, test-inclusive
   type-check passing — declarations are verifiable code, not a design document.
3. **Review the declarations alone** before any body task starts: against the style
   skill(s) the config names (a typed-FP canon usually carries a type-review checklist —
   closed vocabularies as unions, totality, no representable invalid combinations,
   branded ids, unconsumed types deleted). A small slice can be gated by the orchestrator
   directly; a shape-heavy one gets a reviewer pass.
4. **Reviewed signatures are frozen.** A body task that needs a reviewed signature to
   change escalates back to the orchestrator/design instead of silently reshaping it, and
   the change lands as a worklog deviation (journaled projects: a `deviation` event).
   The freeze is what makes this a gate rather than a decoration.

Skip this for slices that only use existing shapes — the round exists for new domain
vocabulary, not for every task.

## Record each task (journaled projects)

On a project whose config declares a **Journal**, step 7 has a second half — append the task the
moment you tick it, not in a sweep at the end of the plan:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type task-done --data '{"task_id":"T012"}'
```

`task-done` is gate-validated: it is refused unless a passing `verify-run` naming that task
already exists, so the order is verify, record the verify (see `verify`), then record the task
done — both in one `append --batch`, since they close the same boundary (stdin form: see
`verify`). A divergence gets its
own `deviation` {note} event beside the worklog line — a pointer and a sentence; the prose
stays in the worklog, and a payload over 1 KB is refused to keep it that way. A missing or
unreadable database is an infrastructure failure, not a reason to skip the append: surface it
loudly and continue un-journaled only with the user's acknowledgement.

## When to stop and reconsider

- If a task reveals the design was wrong (not just incomplete), stop and route back to
  `design` rather than improvising a different architecture mid-build.
- If a task reveals a requirements gap, route back to `clarify`.
- If you're tempted to "while I'm here" refactor something unrelated — don't. Note it as a
  follow-up; keep the change scoped to the plan.
- **Sunk cost**: the same approach has failed twice → stop; no third variant. Ask "would I
  choose this path starting fresh, ignoring the work already done?" — if not, route back to
  `design` with what the two attempts proved.
- **Bounded rationality**: an open-ended search (greps, candidate libraries, places to hook in)
  gets a stated "good enough" before it starts and stops at the first option that clears it.
  Never for a correctness gate — a test, a security check, "did the fix work" need the right
  answer, not a sufficient-looking one — nor for an irreversible pick (a new dependency, a
  schema).

## Committing

- **Don't commit unless the user asks.** Default to leaving the change for them to review.
  The repo may be dirty in unrelated areas, so the user — not the plugin — decides when
  a commit happens.
- **Stage only the files you actually changed.** Never `git add -A` / `git add .` here; you'll
  sweep up someone else's in-flight work. Add explicit paths.
- **Keep commits atomic.** Each commit is one complete, self-contained change that builds and
  passes on its own — one logical thing done fully, with nothing half-finished and nothing
  unrelated bundled in. This scales by itself: a trivial feature is a single atomic commit; a
  large one is several (per task or group of tasks). Let the size of the change decide the count, not a
  fixed rule.
- **Only commit verified code.** Don't commit a task whose `verify` gate hasn't passed; a red
  commit is a landmine for the next person (and for `git bisect`).
- **Follow the repo's commit conventions** and, when a tracker issue exists, reference it
  (`#ID`) the way the repo does — it ties the commit back to the PRD/worklog/branch trail.
- **Never bypass hooks or signing** (`--no-verify`, unsigned). Hooks are part of how the repo
  stays correct; routing around them defeats the point of this whole flow.

## On completion

When the Build Plan is fully checked and verified, summarize what was built (completed,
skipped, newly discovered, blocked), confirm every FR-### / SC-### has been satisfied, and
hand off to `review`. Consider what's worth capturing via `knowledge-base` (a gotcha, a reusable
fix, a convention you had to discover).
