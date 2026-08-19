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

Check the `model-tiers` skill first: when the build is big enough to dispatch, the master
session doesn't work tasks inline — each coherent unit goes to a worker subagent with a
self-contained brief, and the session reviews the worker's diff against the design before
anything is staged. Workers delegate mechanical sub-work to Sonnet subagents. For small
builds, work the tasks directly. Either way, the loop below is what "done" means for each
task — whoever executes it.

## The loop (per task)

1. **Take the next task** in dependency order from the Build Plan. Respect `[P]` only as a
   signal that tasks are independent — don't start a task whose prerequisites are unchecked.

2. **Reuse before writing.** Grep the codebase for an existing utility, helper, or pattern
   that already does this — and when integrating a dependency, **read its API surface
   first**: libraries usually ship the combinator for their own domain (timers, retries,
   interceptor lifecycles), and a sibling function in the same module using that dependency
   is the template to match. The cheapest correct code is the code you don't add. Only
   write new code when nothing fits cleanly — don't force-fit a near-match, but don't
   reinvent either.

3. **Match the conventions** surfaced during exploration — error handling, validation, DI,
   the stack idioms exploration surfaced, naming. New code should look like it was always there.

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

7. **Update the worklog.** Tick the task. If you diverged from the design, log it in
   *Deviations & notes* with the reason and impact — a silent divergence is how the design
   and the code drift apart. Anything you learned that outlives this feature — a trap, a
   convention, a style call — gets a one-line entry in the project **ledger** as it happens
   (see `knowledge-base`); don't trust end-of-flow memory to resurface it.

## When to stop and reconsider

- If a task reveals the design was wrong (not just incomplete), stop and route back to
  `design` rather than improvising a different architecture mid-build.
- If a task reveals a requirements gap, route back to `clarify`.
- If you're tempted to "while I'm here" refactor something unrelated — don't. Note it as a
  follow-up; keep the change scoped to the plan.

## Committing

- **Don't commit unless the user asks.** Default to leaving the change for them to review.
  The repo may be dirty in unrelated areas, so the user — not the plugin — decides when
  a commit happens.
- **Stage only the files you actually changed.** Never `git add -A` / `git add .` here; you'll
  sweep up someone else's in-flight work. Add explicit paths.
- **Keep commits atomic.** Each commit is one complete, self-contained change that builds and
  passes on its own — one logical thing done fully, with nothing half-finished and nothing
  unrelated bundled in. This scales by itself: a trivial feature is a single atomic commit; a
  large one is several (per task or stage). Let the size of the change decide the count, not a
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
