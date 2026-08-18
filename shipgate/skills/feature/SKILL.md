---
name: feature
description: Orchestrator for lean, gate-driven feature and bug work — detects which phase a piece of work is in (from the PRD/ADR/worklog present), proposes the next step, and routes to the right phase skill. Use when starting a feature or bug, asking "what's next", resuming work, or invoking /shipgate. Scales ceremony to the size of the change, and drives epics issue-by-issue — each child issue a separate deliverable with its own cycle and a stop between them.
---

# Feature orchestrator

You coordinate the lean feature flow. You don't do the deep work yourself — you figure out
*where the work stands*, *what should happen next*, and *route to the phase skill that does
it*. Think of yourself as the tech lead who keeps the work moving through the right gates,
not the engineer heads-down in one file.

> **Project config:** before applying the defaults below, read `.claude/shipgate.md` from
> the project root (in an umbrella checkout, also check the umbrella root). If present, its
> instructions override this skill's defaults.

## The flow

```
Workspace → Route & Map → Explore → Clarify (gate) → Design → Implement → Review → Capture
```

Each arrow is a handoff; the gates (Clarify, and verify inside Implement/Review) are where
work is allowed to stop and back up. Backward transitions are normal and healthy:
review → implement (code wrong), design → clarify (requirements gap), implement → design
(approach wrong). Gates honor the config's **Autonomy** section: in `executive` mode the
orchestrator answers gate questions itself and records the decisions, escalating only what
the config's escalation contract names (see `clarify` / `design`); default is `ask`.

| Phase | Skill | Produces |
|-------|-------|----------|
| Workspace | `workspace` | right branch off a clean base (or confirmed worktree) |
| Route & Map | `route-and-map` | impact map (modules/services touched, write/read path, data obligations) |
| Explore | dispatch `code-explorer` ×2-3 | grounded context, essential files |
| Clarify *(gate)* | `clarify` | PRD in the configured PRD home (default `docs/prd/`), FR-###/SC-### |
| Design | `design` | ADR(s) + worklog (Design + Build Plan) |
| Implement | `implement` | code + ticked Build Plan |
| Review | `review` | verdict + verified evidence |
| Capture | `knowledge-base` (invoke it explicitly) | ledger triaged + durable learnings, routed by type (see `knowledge-base`) |

## Running the Explore phase

How you explore depends on the work — don't reach for the explorer fan by reflex:

- **Bug / regression / incident → use `structured-debug`, not the explorer fan.** Debugging
  needs focused reproduction and one-variable-at-a-time hypothesis testing on a suspect area —
  not 2-3 agents broadly mapping the codebase (that's expensive and unfocused for a defect). At
  most spawn a *single* explorer first if you need to locate where the behavior lives, then hand
  to `structured-debug`.
- **Feature / non-trivial new work → the parallel explorer fan** (below). This is where broad,
  multi-lens grounding pays off.

For a feature, do it the feature-dev way:

1. Dispatch **2-3 `code-explorer` agents in parallel**, each with a *different lens* — e.g. a
   precedent/similar feature, the architecture and abstractions of the area, the current
   implementation you'll change, the relevant data flow. Distinct lenses find more than three
   explorers all looking the same way.
2. When they return, **read the files they flag yourself** — don't design or plan off their
   summaries. The explorers locate; you build the real understanding from the actual code.
   This is what keeps Clarify and Design honest.
3. Carry that grounded context (plus the impact map) into Clarify.

Subagents don't read `.claude/shipgate.md` themselves, so paste the config excerpts they need
(e.g. the knowledge-base stores to recall from, the security-sensitive areas) into each
explorer brief.

Scale it: a one-service change may need one light explorer or none; a cross-cutting feature
warrants the full 2-3.

## Detect state, then route

Don't assume the work is starting fresh. Infer the current phase from what exists:

- **Starting new work and not already on this feature's branch → `workspace` FIRST.** Don't
  explore or read code until the branch is established off a clean base — otherwise you ground
  the whole flow on whatever happened to be checked out. (Already on the right branch? Workspace
  is a one-line confirmation.)
- No PRD and no impact map → (after Workspace) start at **Route & Map**.
- Impact map done, no PRD → **Explore** (if needed) then **Clarify**.
- PRD exists with open `[NEEDS CLARIFICATION]` → back to **Clarify**; the gate isn't passed.
- PRD clarified, no worklog → **Design**.
- Worklog with unchecked Build Plan tasks → **Implement** (resume at the next task).
- Build Plan complete → **Review**.
- Review passed → **Capture, immediately** — explicitly invoke the `knowledge-base` skill:
  triage the ledger (promote or drop its entries) and route any remaining learnings to their
  configured homes (don't leave it to ambient "remember this" — that triggers Claude's
  built-in session memory instead, and the knowledge never lands where a future session finds
  it). **Capture is not gated on the MR merging or on a further user go-ahead** — the
  learnings exist the moment review passes, and knowledge must never sit hostage to an
  external event. Then done.
- An **MR-watcher event** (if the config declares a watcher) naming an issue is a valid resume
  signal for that issue — enter at the phase the event unlocks, not at the start: reviewer
  comments → the review-feedback cycle (defined in `review`: re-enter implement for the
  fixes, re-verify the changed scope, reply and resolve threads); own MR merged → *residual*
  capture only — triage whatever the review-feedback cycle added to the ledger since the
  main Capture, which already ran when review passed (then the next epic child, if any);
  watched MR merged → resume the held work per its watch-list note; conflicts / failed CI →
  fix before review continues. The watcher only suggests — the user triggers the resume.

Propose the next phase in one line, then proceed (or do it once the user confirms for the
heavier phases).

## Scale ceremony to the change

The flow is a default, not a toll booth. Match it to the work (Workspace always runs first —
even the smallest fix needs to land on the right branch, though it's often a one-line confirm):

- **One-line bug / typo / config**: Workspace → Route & Map (quick) → fix → `verify`. Skip
  PRD/design/worklog; they'd cost more than the change.
- **Scoped change in one service**: Workspace → Route & Map → light Explore → brief Clarify →
  Implement (worklog optional) → Review.
- **Real feature / cross-service / schema change**: the full flow, with PRD, ADR(s) for forks,
  and the worklog.

When you skip phases, say so and why ("one-file fix, going straight to implement + verify")
so the user can pull you back if they wanted more rigor.

## Epic mode — one issue at a time

When the work is big enough to be an **epic** — decomposed into child issues (via the
epic-decomposition command the config's **Epic workflow** section names, if any) — do NOT build
the whole epic in one pass. Track the decomposition as a **parent tracking issue with a
task-list checklist of child issues** (sub-issues / task lists when the tracker supports them;
a plain checklist in the epic PRD when it doesn't). **Each child issue is a separate
deliverable**: its own branch, its own MR/PR, its own review. Work them one at a time.

- **Loop, issue by issue.** Take the next child issue (respect the dependency ordering the
  tracker expresses, e.g. blocked-by links). Run the near-full cycle for *that issue*: Workspace
  (branch named for that issue's id) → Route & Map → Explore (as needed) → Implement → Review
  **including its acceptance-criteria check** → its own MR/PR.
- **Pipeline the rounds — don't idle while workers build.** While workers implement issue N,
  the orchestrator's context is free and cheapest to use: run Route & Map / Explore / Clarify /
  Design for issue **N+1** with the user, so a fully specced design is queued when N lands.
  Default depth: **1-2 issues ahead** (the config's Epic workflow section may declare a
  `Design-ahead depth` to go deeper). Track queued designs as normal worklogs; mark them
  queued, not started. **Staleness rule:** review feedback or a merged MR can change the
  ground a queued design assumed — at each round boundary, re-validate the next queued design
  against what actually merged before implementing it, and re-open its design if the
  assumptions broke.
- **The stop gates merge-and-build, not design.** Each issue is reviewed/merged independently —
  report it done and **wait for the go-ahead** before *merging it or starting to implement*
  the next issue. Don't silently roll implementation from one issue into the next.
  Design-ahead work on upcoming issues is explicitly allowed (and encouraged) during that
  wait — the gate exists so the user controls what gets built, not to park the orchestrator.
- **Shared vs per-issue artifacts.** The epic-level PRD and design are shared context, written
  once at the epic level; each *issue* still gets its own worklog Build Plan and its own MR/PR.
  Never collapse several issues into one branch/MR/PR — that breaks separate-deliverable review
  and traceability.
- **Finishing the epic's issues ≠ finishing the epic.** Each issue meets *its* acceptance
  criteria; the epic is only done when its own Definition of Done is met across all of them —
  tick each child off the tracking checklist as it merges.

## Always-on disciplines

- **Recall early** (`knowledge-base`) at Route & Map and Design — don't re-derive known
  conventions.
- **Verify before "done"** (`verify`) at every completion claim, not just at Review.
- **Match model tier to the work** (`model-tiers`) — when the work is big enough to
  dispatch, the master session orchestrates only: Implement-phase code changes go to
  worker subagents with self-contained briefs, and mechanical sub-work sinks to Sonnet.
  See `model-tiers` for the brief format and delegation rules.
- **Test-first on real behavior** — adding logic or fixing a bug, write the failing test
  before the code (see `implement` / `verify`).
- **Use `structured-debug`** when the work is a bug, regression, or incident rather than a
  clean feature.
- **For a deep security audit** (changes touching auth, secrets, or any configured
  security-sensitive area) or a release check, fire the built-in `/security-review` — the
  in-flow reviewer security lens is a routine sweep, not a full audit. Built-in `/simplify` is
  there for standalone cleanup.
- **Structured thinking where it pays** (if the `thinking-skills` plugin is installed): the
  phases already name their lens; for any *other* hard fork where the right lens isn't obvious,
  start at `thinking-model-router`. Don't force a model on routine or trivial work.
