---
name: feature
description: Orchestrator for lean, gate-driven feature and bug work — detects which phase a piece of work is in (from the flow journal, or the PRD/ADR/worklog present), proposes the next phase, and routes to the right phase skill. Use when starting a feature or bug, asking "what's next", resuming work, or invoking /shipgate. For a standalone question — which file has the bug, what does this change affect, rank the changed files by risk — go straight to structured-debug, route-and-map or review rather than through the orchestrator. Scales ceremony to the size of the change, and drives epics issue-by-issue — each child issue a separate deliverable with its own flow and a stop between them.
---

# Feature orchestrator

You coordinate the lean feature flow. You don't do the deep work yourself — you figure out
*where the work stands*, *what should happen next*, and *route to the phase skill that does
it*. Think of yourself as the tech lead who keeps the work moving through the right gates,
not the engineer heads-down in one file.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

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
explorer brief. A brief may also carry the risk-signal table for the area it dispatches into
(`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <area> --by-dir 2`) — decide per
dispatch; it is context about which code is hot or load-bearing, not an instruction to rank
findings by it. The same goes for the workflow path's `brief`. Unavailable (see the JSON's
`reason`, `trajectory.reason`, `structure.reason`) → leave the table out.

A lens that must read code other than the working tree — `origin/<integration>` for a
staleness check of a dormant design, another branch, the history of a file — names the ref in
its prompt, and you run `git fetch` **before** dispatching: explorers read refs with read-only
git (`git show <ref>:<path>`, `log`, `diff`, `grep`) and never fetch or check out themselves.

Scale it: a one-service change may need one light explorer or none; a cross-cutting feature
warrants the full 2-3.

When the config's **Orchestration** section says `explore: workflow`, run that fan through
the `Workflow` tool instead: Read `${CLAUDE_PLUGIN_ROOT}/skills/feature/references/explore-workflow.js`
and pass its full text as `script` (bundled files are outside the working directory, so
`scriptPath` is refused) with `args = {lenses: [{name, prompt}], brief, model}` — one entry per
lens you'd have dispatched, `brief` **required** (it is the only context the explorers get, so
the script throws on an empty one) and carrying the config excerpts and recall pointers each
explorer needs plus "one paragraph per finding, refs as file:line" (explorer detail is
unbounded otherwise and the return object grows past what you want in context), and
`model` **required** (one tier below the session, per `model-tiers`). It returns
`{lenses: [{lens, findings}], essentialFiles}`, where each essential file lists why every lens
flagged it — capped at 25 files in order of first mention and 20 findings per lens (both drops
are logged), and a lens entry missing its `name` or `prompt` throws before any agent runs. A
return carrying `aborted` means every lens explorer died and the run explored nothing — treat
it as the degradation case, not as "there was nothing to find". Step 2 is unchanged and
non-negotiable: **you still read those files yourself** — the workflow locates, you build the
understanding. A lens prompt that reads another ref follows the fetch-first rule above. `Workflow` unavailable or the call refused → run the explorer fan above and
record a `deviation`.

## Detect state, then route

Don't assume the work is starting fresh — establish where the work stands before doing
anything else.

**Journaled projects** (the config declares a **Journal**): read the position, don't guess it.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" status [--branch <branch>] [--feature <slug>] [--all]
```

That status brief is the authoritative position — the phase, the gate decisions on record, the last
verify, any queued designs. Route from it and then open only the artifacts it names. Do not
reconstruct position by scanning worklog checkboxes; the journal exists precisely so nobody
has to. Completed streams are hidden and long-dormant ones collapse to a line; `--all` shows
everything. The SessionStart hook usually hands you this status brief before you ask, in which case
use what you already have rather than re-running the command.

Three rules follow from the journal being the position of record:

- **One stream per issue, named for its branch.** The stream name *is* the branch name, so
  the hook's `--branch` lookup finds it. An epic's children are separate branches and
  therefore separate streams. Never carry two issues in one stream: its phase, gate history
  and verdict would then describe no single deliverable.
- **A missing event is a stuck flow, not a fallback.** If the journal says `design` and the
  worklog is clearly further along, do NOT quietly route to the later phase. Say what the
  journal says, say what the artifacts show, and record the resolution as an event
  (`deviation`, or the phase event that was missed) before moving. Silent reinterpretation
  is the failure mode the journal removes.
- **Journal unavailable ≠ journal empty.** If the database is missing or unreadable while the
  config declares one, that is an infrastructure problem: surface it, offer
  `journal.py doctor`, and only fall back to artifact inference for the session with the
  user's explicit acknowledgement.

**Un-journaled projects** (no Journal section): infer position from what exists,
using the same semantics. Offer `/shipgate:setup` once, briefly, if the project looks like it
would benefit; don't nag.

The phase semantics — what each position means and where it goes next — are the same either way:

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
  triage the ledger and route the rest to their configured homes. Never leave it to ambient
  "remember this" — that hits Claude's built-in session memory, not the knowledge base.
  **Not gated on the MR/PR merging or on a further user go-ahead.** Then done — and on a
  journaled project the stream is closed with `flow-completed` once nothing is owed on it,
  which is what makes it leave every later session's status brief.
- An **MR-watcher event** (if the config declares a watcher) naming an issue is a valid resume
  signal for that issue — enter at the phase the event unlocks, not at the start: reviewer
  comments → the review-feedback cycle (defined in `review`: re-enter implement for the
  fixes, re-verify the changed scope, reply and resolve threads); own MR/PR merged → *residual*
  capture only — triage whatever the review-feedback cycle added to the ledger since the
  main Capture, which already ran when review passed (then the next child issue, if any);
  watched MR/PR merged → resume the held work per its watch-list note; conflicts / failed CI →
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

Size is one axis. The other is how cause relates to effect in this work (**Cynefin**):
**clear** (obvious to anyone) → the known pattern, don't over-engineer; **complicated**
(knowable with analysis) → the flow above; **complex** (only visible in hindsight — new domain,
emergent behaviour, unknown load) → a spike or probe *before* the PRD, then clarify from what
it showed, because planning harder won't help; **chaotic** (an active incident) → stabilize
first (`structured-debug`'s OODA thinking lens), understand after. A medium change in a complex domain
earns a spike; a large one in a clear domain may be mostly typing. Re-check as you go — domains
shift.

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
  tracker expresses, e.g. blocked-by links). Run the near-full flow for *that issue*: Workspace
  (branch named for that issue's id) → Route & Map → Explore (as needed) → Implement → Review
  **including its acceptance-criteria check** → its own MR/PR.
- **Pipeline the rounds — don't idle while workers build.** While workers implement issue N,
  the orchestrator's context is free and cheapest to use: run Route & Map / Explore / Clarify /
  Design for issue **N+1** with the user, so a fully specced design is queued when N lands.
  Default depth: **1-2 issues ahead** (the config's Epic workflow section may declare a
  `Design-ahead depth` to go deeper). Track queued designs as normal worklogs; mark them
  queued, not started. **Staleness rule:** review feedback or a merged MR/PR can change the
  ground a queued design assumed — at each round boundary, re-validate the next queued design
  against what actually merged before implementing it, and re-open its design if the
  assumptions broke.
- **The stop gates merge-and-build, not design.** Each issue is reviewed/merged independently —
  report it done and **wait for the go-ahead** before *merging it or starting to implement*
  the next issue. Don't silently roll implementation from one issue into the next. And
  **"start the next item" is never publish authorization for this one**: an MR/PR goes up
  only once this issue's `review-verdict` {verdict: ready} is recorded, or the user's
  explicit `gate-decision` {gate: publish, raised_by: user, decision: publish} is, appended
  with `--actor user` — journaled projects refuse `mr-opened` without one.
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
- **Record as you go, on journaled projects.** Every phase you enter, every gate decision
  you make (especially in `executive` mode), every verdict — append it when it happens, not
  in a sweep at the end. The phase skills say which events are theirs, and
  `journal.py vocab --shape <type>` prints the payload each one takes, so no skill has to
  quote it. Five rules keep the recording cheap and honest:
  - **The stream exists before the first event.** The stream is the branch the work takes
    (the config's **Branching** pattern), whether or not that branch exists yet; when the status brief
    lists no stream of that name, the first phase skill to run opens it with `flow-started` in
    the same append as its own event — on `main`, before `workspace` has made the branch, is
    the normal case. The integration branch is never a stream, and "there is no stream yet" is
    never a reason to skip an event.
  - **Pointer, not prose.** The worklog / PRD / ADR holds the text; the event holds `refs`
    (paths, section anchors, seq numbers) and one sentence. A payload over 1 KB on a work
    stream is refused for exactly this reason.
  - **A phase-owning event records its own phase.** `clarify-passed`, `design-committed`,
    `verify-run`, `task-done`, `review-verdict` and `capture-done` imply their
    `phase-entered`, so don't type it around them. You still append `phase-entered` for the
    phases no event owns — workspace, route-and-map, explore — and whenever you skip a
    phase, naming the skipped ones in `skipped`.
  - **One batch per phase boundary.** `append --batch` takes JSONL on stdin, so a boundary
    that produces two or three events (verify-run + task-done, phase-entered +
    gate-decision) costs one Bash call rather than three (stdin form: see `verify`). Chaining `--expect <version>`
    across separate appends, read the new `version` back from each append's output rather
    than assuming +1: a phase-owning event may write its implied `phase-entered` too, and
    that transition moves the version as well.
  - **Say who decided.** A `gate-decision` carries `raised_by`: `user` when the user raised
    or corrected the point, `orchestrator` when you asked it or decided it yourself. Pass
    `--actor user` for a decision the user made, `--actor orchestrator` (or nothing)
    otherwise; a worker that appends passes `--actor worker`. The form is `role[@label]` —
    omit the label and `append` fills in the current session.

  Hooks capture what the harness can see — artifact writes, session start and end — and the
  Stop hook blocks a session that ticked build-plan boxes without `task-done`, recorded
  `task-done` without a passing `verify-run`, or wrote a PRD in clarify with no
  `gate-decision`. Nothing checks the phase events (`phase-entered`, `bug-reproduced`,
  `debug-root-cause`, `design-committed`, `review-verdict`): the phase skill's own step writes
  them, in the turn the fact is established, or they are never written.
- **Match model tier to the work** (`model-tiers`) — when the work is big enough to
  dispatch, the orchestrator does not type product code: Implement-phase code changes go to
  worker subagents with self-contained briefs, and mechanical sub-work sinks to Sonnet.
  See `model-tiers` for the worker-brief format and delegation rules.
- **Test-first on real behavior** — adding logic or fixing a bug, write the failing test
  before the code (see `implement` / `verify`).
- **Use `structured-debug`** when the work is a bug, regression, or incident rather than a
  clean feature.
- **For a deep security audit** (changes touching auth, secrets, or any configured
  security-sensitive area) or a release check, fire the built-in `/security-review` — the
  in-flow reviewer security lens is a routine sweep, not a full audit. Built-in `/simplify` is
  there for standalone cleanup.
- **Structured thinking where it pays**: each phase describes its thinking lens inline and applies
  the idea by default; the config's **Thinking lenses** section may map phases to actual
  lens skills to invoke (typically the early, judgment-dense phases — clarify, design).
  Don't force a thinking lens on routine or trivial work.
