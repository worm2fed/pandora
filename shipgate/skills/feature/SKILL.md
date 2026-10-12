---
name: feature
description: Orchestrator for lean, gate-driven feature and bug work — detects which phase a piece of work is in (from the flow journal, or the PRD/ADR/worklog present), proposes the next phase, and routes to the right phase skill. Use when starting a feature or bug, asking "what's next", resuming work, or invoking /shipgate. For a standalone question — which file has the bug, what does this change affect, rank the changed files by risk — go straight to structured-debug, route-and-map or review rather than through the orchestrator. Scales ceremony to the size of the change, and drives epics issue-by-issue — each child issue a separate deliverable with its own flow and a stop between them.
---

# Feature orchestrator

You coordinate the lean feature flow. You don't do the deep work yourself. You find out
*where the work stands* and *what should happen next*, and you *route to the phase skill that
does it*. Think of yourself as the tech lead who keeps the work moving through the right
gates, not the engineer heads-down in one file.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## The flow

```
Workspace → Route & Map → Explore → Clarify (gate) → Design → Implement → Review → Capture
```

Each arrow is a handoff. The gates (Clarify, and verify inside Implement/Review) are where work
may stop and go back. Backward transitions are normal and healthy:
review → implement (code wrong), design → clarify (requirements gap), implement → design
(approach wrong).

Gates honor the config's **Autonomy** section. In `executive` mode the orchestrator answers
gate questions itself and records the decisions. It escalates only what the config's
escalation contract names (see `clarify` / `design`). The default is `ask`.

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

How you explore depends on the work. Don't reach for the explorer fan by reflex:

- **Bug / regression / incident → use `structured-debug`, not the explorer fan.** Debugging
  needs focused reproduction and hypothesis testing on a suspect area, one variable at a time.
  It does not need 2-3 agents that map the codebase broadly: for a defect that is expensive
  and unfocused. If you need to find where the behavior lives, spawn at most a *single*
  explorer first. Then hand over to `structured-debug`.
- **Feature / non-trivial new work → the parallel explorer fan** (below). Here broad,
  multi-lens grounding pays off.

For a feature, do it the feature-dev way:

1. Dispatch **2-3 `code-explorer` agents in parallel**, each with a *different lens*. Example
   lenses: a precedent or similar feature, the architecture and abstractions of the area, the
   current implementation you'll change, the relevant data flow. Distinct lenses find more
   than three explorers that all look the same way.
2. When they return, **read the files they flag yourself**. Don't design or plan from their
   summaries. The explorers locate; you build the real understanding from the actual code.
   This is what keeps Clarify and Design honest.
3. Carry that grounded context (plus the impact map) into Clarify.

Subagents don't read `.claude/shipgate.md` themselves. So paste the config excerpts they need
into each explorer brief (e.g. the knowledge base's stores to recall from, the
security-sensitive areas).

A brief may also carry the risk-signal table for the area it dispatches into
(`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots <area> --by-dir 2`). Decide per
dispatch. The table is context about which code is hot or load-bearing. It is not an
instruction to rank findings by it. The same goes for the workflow path's `brief`. If the
signals are unavailable (see the JSON's `reason`, `trajectory.reason`, `structure.reason`),
leave the table out.

Some lenses must read code other than the working tree. Examples: `origin/<integration>` for a
staleness check of a dormant design, another branch, the history of a file. Such a lens names
the ref in its prompt, and you run `git fetch` **before** you dispatch. Explorers read refs
with read-only git (`git show <ref>:<path>`, `log`, `diff`, `grep`). They never fetch or
check out themselves.

Scale it. A one-service change may need one light explorer or none. A cross-cutting feature
warrants the full 2-3.

When the config's **Orchestration** section says `explore: workflow`, run that fan through
the `Workflow` tool instead:

- Read `${CLAUDE_PLUGIN_ROOT}/skills/feature/references/explore-workflow.js` and pass its full
  text as `script`. Bundled files are outside the working directory, so the tool refuses
  `scriptPath`.
- Pass `args = {lenses: [{name, prompt}], brief, model}`, with one entry per lens you would
  have dispatched.
- `brief` is **required**. It is the only context the explorers get, so the script throws on
  an empty one. It carries the config excerpts and recall pointers each explorer needs. It
  also carries "one paragraph per finding, refs as file:line". Without that line explorer
  detail is unbounded, and the return object grows past what you want in context.
- `model` is **required**: one tier below the session, per `model-tiers`.

The script returns `{lenses: [{lens, findings}], essentialFiles}`. Each essential file lists
why every lens flagged it. The script caps the list at 25 files, in order of first mention,
and at 20 findings per lens; it logs both drops. A lens entry with no `name` or `prompt`
throws before any agent runs.

A return that carries `aborted` means every lens explorer died and the run explored nothing.
Treat it as the degradation case, not as "there was nothing to find".

Step 2 is unchanged and non-negotiable: **you still read those files yourself**. The workflow
locates; you build the understanding. A lens prompt that reads another ref follows the
fetch-first rule above. If `Workflow` is unavailable or the call is refused, run the explorer
fan above and record a `deviation`.

## Detect state, then route

Don't assume the work is starting fresh. Establish where the work stands before you do
anything else.

**Journaled projects** (the config declares a **Journal**): read the position, don't guess it.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" status [--branch <branch>] [--feature <slug>] [--all]
```

That status brief is the authoritative position: the phase, the gate decisions on record, the
last verify, any queued designs. Route from it, then open only the artifacts it names. Do not
reconstruct the position by scanning worklog checkboxes. The journal exists precisely so that
nobody has to.

The status brief hides completed streams and collapses long-dormant ones to a line; `--all`
shows everything. The SessionStart hook usually hands you this status brief before you ask. In
that case use what you already have; don't re-run the command.

Three rules follow because the journal is the position of record:

- **One stream per issue, named for its branch.** The stream name *is* the branch name, so
  the hook's `--branch` lookup finds it. An epic's children are separate branches and
  therefore separate streams. Never carry two issues in one stream. Its phase, gate history
  and verdict would then describe no single deliverable.
- **A missing event is a stuck flow, not a fallback.** Say the journal says `design` and the
  worklog is clearly further along. Do NOT quietly route to the later phase. Say what the
  journal says and what the artifacts show. Record the resolution as an event (`deviation`,
  or the phase event that was missed) before you move on. Silent reinterpretation is the
  failure mode the journal removes.
- **Journal unavailable ≠ journal empty.** The config may declare a database that is missing
  or unreadable. That is an infrastructure problem. Surface it and offer `journal.py doctor`.
  Fall back to artifact inference for the session only with the user's explicit
  acknowledgement.

**Un-journaled projects** (no Journal section): infer the position from what exists, with the
same semantics. If the project looks like it would benefit, offer `/shipgate:setup` once,
briefly. Don't nag.

The phase semantics (what each position means and where it goes next) are the same either
way:

- **Starting new work and not already on this feature's branch → `workspace` FIRST.** Don't
  explore or read code until the branch is established off a clean base. Otherwise you ground
  the whole flow on whatever happened to be checked out. (Already on the right branch? Then
  Workspace is a one-line confirmation.)
- No PRD and no impact map → (after Workspace) start at **Route & Map**.
- Impact map done, no PRD → **Explore** (if needed) then **Clarify**.
- PRD exists with open `[NEEDS CLARIFICATION]` → back to **Clarify**; the gate isn't passed.
- PRD clarified, no worklog → **Design**.
- Worklog with unchecked Build Plan tasks → **Implement** (resume at the next task).
- Build Plan complete → **Review**.
- Review passed → **Capture, immediately**. Explicitly invoke the `knowledge-base` skill.
  Triage the ledger and route the rest to their configured homes. Never leave it to ambient
  "remember this": that goes to Claude's built-in session memory, not the knowledge base.
  **Capture is not gated on the MR/PR merging or on a further user go-ahead.** Then the work
  is done. On a journaled project the stream is closed with `flow-completed` once nothing is
  owed on it. That event makes the stream leave every later session's status brief.
- An **MR-watcher event** (if the config declares a watcher) that names an issue is a valid
  resume signal for that issue. Enter at the phase the event unlocks, not at the start:
  - reviewer comments → the review-feedback cycle (defined in `review`: re-enter implement
    for the fixes, re-verify the changed scope, reply and resolve threads);
  - own MR/PR merged → *residual* capture only. Triage whatever the review-feedback cycle
    added to the ledger since the main Capture. The main Capture already ran when review
    passed. Then take the next child issue, if any;
  - watched MR/PR merged → resume the held work per its watch-list note;
  - conflicts / failed CI → fix them before review continues.

  The watcher only suggests. The user triggers the resume.

Propose the next phase in one line, then proceed. For the heavier phases, proceed once the user
confirms.

## Scale ceremony to the change

The flow is a default, not a toll booth. Match it to the work. Workspace always runs first:
even the smallest fix needs to land on the right branch, though often a one-line confirmation
is enough.

- **One-line bug / typo / config**: Workspace → Route & Map (quick) → fix → `verify`. Skip
  PRD/design/worklog; they'd cost more than the change.
- **Scoped change in one service**: Workspace → Route & Map → light Explore → brief Clarify →
  Implement (worklog optional) → Review.
- **Real feature / cross-service / schema change**: the full flow, with PRD, ADR(s) for forks,
  and the worklog.

Size is one axis. The other is how cause relates to effect in this work (**Cynefin**):

- **clear** (obvious to anyone) → use the known pattern; don't over-engineer.
- **complicated** (knowable with analysis) → use the flow above.
- **complex** (only visible in hindsight: new domain, emergent behaviour, unknown load) → run a
  spike or probe *before* the PRD, then clarify from what it showed. Planning harder won't
  help here.
- **chaotic** (an active incident) → stabilize first (`structured-debug`'s OODA thinking lens),
  understand after.

A medium change in a complex domain earns a spike. A large one in a clear domain may be mostly
typing. Re-check as you go, because domains shift.

When you skip phases, say so and why ("one-file fix, going straight to implement + verify").
Then the user can pull you back if they wanted more rigor.

## Epic mode — one issue at a time

Some work is big enough to be an **epic**: decomposed into child issues (via the
epic-decomposition command the config's **Epic workflow** section names, if any). Do NOT build
the whole epic in one pass. Track the decomposition as a **parent tracking issue with a
task-list checklist of child issues**. Use sub-issues / task lists when the tracker supports
them, and a plain checklist in the epic PRD when it doesn't. **Each child issue is a separate
deliverable**: its own branch, its own MR/PR, its own review. Work them one at a time.

- **Loop, issue by issue.** Take the next child issue. Respect the dependency ordering the
  tracker expresses, e.g. blocked-by links. Run the near-full flow for *that issue*: Workspace
  (branch named for that issue's id) → Route & Map → Explore (as needed) → Implement → Review
  **including its acceptance-criteria check** → its own MR/PR.
- **Pipeline the rounds — don't idle while workers build.** While workers implement issue N,
  the orchestrator's context is free and cheapest to use. Run Route & Map / Explore / Clarify /
  Design for issue **N+1** with the user, so a fully specced design is queued when N lands.
  - Default depth: **1-2 issues ahead**. The config's Epic workflow section may declare a
    `Design-ahead depth` to go deeper.
  - Track queued designs as normal worklogs. Mark them queued, not started.
  - **Staleness rule:** review feedback or a merged MR/PR can change the ground a queued design
    assumed. At each round boundary, re-validate the next queued design against what actually
    merged before you implement it. If the assumptions broke, re-open its design.
- **The stop gates merge-and-build, not design.** Each issue is reviewed and merged
  independently. Report it done and **wait for the go-ahead** before *merging it or starting to
  implement* the next issue. Don't silently roll implementation from one issue into the next.
  - **"Start the next item" is never publish authorization for this one.** An MR/PR goes up
    only once one of two events is recorded: this issue's `review-verdict` {verdict: ready},
    or the user's explicit `gate-decision` {gate: publish, raised_by: user, decision: publish},
    appended with `--actor user`. Journaled projects refuse `mr-opened` without one.
  - Design-ahead work on upcoming issues is explicitly allowed (and encouraged) during that
    wait. The gate exists so the user controls what gets built, not to park the orchestrator.
- **Shared vs per-issue artifacts.** The epic-level PRD and design are shared context, written
  once at the epic level. Each *issue* still gets its own worklog Build Plan and its own MR/PR.
  Never collapse several issues into one branch/MR/PR: that breaks separate-deliverable review
  and traceability.
- **Finishing the epic's issues ≠ finishing the epic.** Each issue meets *its* acceptance
  criteria. The epic is done only when its own Definition of Done is met across all of them.
  Tick each child off the tracking checklist as it merges.

## Always-on disciplines

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, the glossary's term for each concept, one
> action per step, active voice, no clause chains joined by dashes or parentheses. Shorter
> sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

- **Recall early** (`knowledge-base`) at Route & Map and Design. Don't re-derive known
  conventions.
- **Verify before "done"** (`verify`) at every completion claim, not just at Review.
- **Record as you go, on journaled projects.** Append every phase you enter, every gate
  decision you make (especially in `executive` mode) and every verdict when it happens, not in
  a sweep at the end. The phase skills say which events are theirs.
  `journal.py vocab --shape <type>` prints the payload each one takes, so no skill has to
  quote it. Five rules keep the recording cheap and honest:
  - **The stream exists before the first event.** The stream is the branch the work takes
    (the config's **Branching** pattern), whether or not that branch exists yet. When the
    status brief lists no stream of that name, the first phase skill to run opens it. It
    writes `flow-started` in the same append as its own event. The normal case is on `main`,
    before `workspace` has made the branch. The integration branch is never a stream. "There
    is no stream yet" is never a reason to skip an event.
  - **Pointer, not prose.** The worklog / PRD / ADR holds the text. The event holds `refs`
    (paths, section anchors, seq numbers) and one sentence. For exactly this reason, the
    journal refuses a payload over 1 KB on a work stream.
  - **A phase-owning event records its own phase.** `clarify-passed`, `design-committed`,
    `verify-run`, `task-done`, `review-verdict` and `capture-done` imply their
    `phase-entered`, so don't type it around them. You still append `phase-entered` for the
    phases no event owns: workspace, route-and-map, explore. You also append it whenever you
    skip a phase, and name the skipped ones in `skipped`.
  - **One batch per phase boundary.** `append --batch` takes JSONL on stdin. So a boundary
    that produces two or three events (verify-run + task-done, phase-entered +
    gate-decision) costs one Bash call rather than three (stdin form: see `verify`). When you
    chain `--expect <version>` across separate appends, read the new `version` back from each
    append's output. Don't assume +1: a phase-owning event may write its implied
    `phase-entered` too, and that transition moves the version as well.
  - **Say who decided.** A `gate-decision` carries `raised_by`. Use `user` when the user
    raised or corrected the point. Use `orchestrator` when you asked it or decided it
    yourself. Pass `--actor user` for a decision the user made, and `--actor orchestrator`
    (or nothing) otherwise. A worker that appends passes `--actor worker`. The form is
    `role[@label]`; if you omit the label, `append` fills in the current session.

  Hooks capture what the harness can see: artifact writes, session start and end. The Stop
  hook blocks a session that did one of three things:
  - ticked build-plan boxes without `task-done`;
  - recorded `task-done` without a passing `verify-run`;
  - wrote a PRD in clarify with no `gate-decision`.

  Nothing checks the phase events (`phase-entered`, `bug-reproduced`, `debug-root-cause`,
  `design-committed`, `review-verdict`). The phase skill's own step writes them, in the turn
  the fact is established, or nobody ever writes them.
- **Match model tier to the work** (`model-tiers`). When the work is big enough to dispatch,
  the orchestrator does not type product code. Implement-phase code changes go to worker
  subagents with self-contained briefs, and mechanical sub-work sinks to Sonnet. See
  `model-tiers` for the worker-brief format and delegation rules.
- **Test-first on real behavior.** When you add logic or fix a bug, write the failing test
  before the code (see `implement` / `verify`).
- **Use `structured-debug`** when the work is a bug, regression, or incident rather than a
  clean feature.
- **For a deep security audit or a release check, fire the built-in `/security-review`.** A
  deep audit fits changes that touch auth, secrets, or any configured security-sensitive area.
  The in-flow reviewer security lens is a routine sweep, not a full audit. Built-in `/simplify`
  is there for standalone cleanup.
- **Structured thinking where it pays.** Each phase describes its thinking lens inline and
  applies the idea by default. The config's **Thinking lenses** section may map phases to
  actual lens skills to invoke (typically the early, judgment-dense phases: clarify, design).
  Don't force a thinking lens on routine or trivial work.
