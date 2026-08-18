# shipgate configuration — template

Copy this file into your project as **`.claude/shipgate.md`** and fill in what applies.
This is how shipgate adapts to a project without forking the plugin: the skills read this
file at the start of a flow and treat it as overriding their built-in defaults. It's prose
read by the model, not parsed config — write it the way you'd brief a new teammate.

Every section is **optional**. Delete what you don't need; anything absent falls back to
the defaults noted per section. Keep entries short and imperative — each line here is an
instruction the skills will follow verbatim.

Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth
for *routing and code conventions* (where code belongs, build/test commands); this file
carries the *process tooling* — where artifacts live, which forge/tracker, branch naming,
which integrations to reach for. Don't duplicate CLAUDE.md content here.

Subagents don't read this file themselves — the dispatching skill pastes the relevant
excerpt into each brief. So write sections to be liftable on their own.

---

## Knowledge base

<!-- Default when absent: PRDs to docs/prd/, ADRs to docs/adr/, worklogs beside the PRD
     as <name>.worklog.md — plain markdown committed to the repo; knowledge capture to
     repo docs; no wiki. -->

- Stores: <one line per store: name — purpose — transport (MCP server name, or in-repo
  path) — who may write to it>
- PRD home: <path, e.g. `docs/prd/` or a wiki path>
- ADR home: <path>
- Worklog home: <path — usually beside the PRD as `<name>.worklog.md`>
- Page conventions: <frontmatter shape, filename rules, link style, where templates live>
- Store-specific skills: <any project/vault skills to prefer for reading/writing the store>
- Ledger: <path of the project's append-cheap staging inbox for mid-flow learnings.
  Default when absent: `docs/ledger.md`. Optionally map promotion targets by entry type —
  destinations may be stores above, specific wiki pages, a repo CLAUDE.md, an ADR home, a
  skill's SKILL.md (e.g. a personal code-style skill), or the harness's personal memory
  for workflow preferences. Entries are promoted or dropped at triage and then removed —
  see the `knowledge-base` skill>

## Forge & tracker

<!-- Default when absent: detect from `git remote get-url origin` — github.com → gh + PRs,
     gitlab → glab + MRs. Issue context read via whatever CLI/MCP is available. -->

- Forge: <GitHub | GitLab | …> — CLI: <gh | glab | …>
- Issue tracker: <where issues live (may be a different repo/project than the code) and
  the MCP/CLI to read them with>
- MR/PR template: <where the canonical template lives + the exact command to fetch it>
- Issue-link form: <how MR/PR bodies and commits must reference issues, e.g. cross-repo
  form `group/project#NNNN`>
- Title/body rules: <conventions the template itself doesn't capture>
- Acceptance criteria source: <where the ACs the review phase must check live>
- Bug provenance: <where root-cause comments go and any format they must follow. Default
  when absent: a comment on the bug's tracker issue via the forge CLI, citing the
  introducing commit — see `structured-debug`>

## MR watcher

<!-- Default when absent: no watcher — the flow ends at "MR opened" and resumes only when
     the user asks. -->

- Watcher: <project skill that watches open MRs/PRs and keeps a watch list, or delete
  this section>
- Register a blocker/follow-up: <the exact command the watcher exposes for adding an
  external MR to its watch list>
- If declared, two skills honor it:
  - **review**, after opening the MR: if this work is now blocked on someone else's MR,
    or has follow-up work gated on this MR merging, register it with the watcher's watch
    list. The note must name the held work AND its next action (e.g. "unblocks #8311 —
    rebase + open MR"), so the unblock event arrives as an instruction, not trivia.
    Say what you're registering as you do it.
  - **feature**, resume detection: a watcher event naming an issue is a valid resume
    trigger. Map it: reviewer comments → the review-feedback cycle (defined in the
    `review` skill); own MR merged → residual ledger triage only — the main capture
    already ran when review passed (then next epic child, if any); watched MR merged →
    resume the held work per its note; conflicts / failed CI → fix before review continues.
- The watcher is strictly read-only. It suggests; the user triggers every resume.

## Branching

<!-- Default when absent: `<type>/<issue-id>-<slug>`, type ∈ feat | fix | chore, branched
     off the detected integration branch. -->

- Pattern: <e.g. `<type>/<issue-id>-<slug>`, prefixes, forbidden elements>
- Examples: <two or three real-shaped but neutral examples>

## Repo layout

<!-- Only needed for umbrella / multi-repo checkouts. Default: the working directory is
     the repo. -->

- <e.g. "this repo is an umbrella — every `source/<service>` is its own git repo; all
  feature branches happen inside the service repos, never on the umbrella itself">

## Style

<!-- Default when absent: match surrounding code; no extra skill invoked. -->

- Style skill(s): <project skill to invoke BEFORE writing or reviewing code — the
  implement/review phases invoke it, and every worker brief must instruct it too>

## Security-sensitive areas

<!-- Default when absent: auth, secrets, payments — the built-in judgment. -->

- <domains in this codebase that must trigger the full `/security-review` rather than the
  in-flow security lens, e.g. billing, PII exports>

## Debug evidence sources

<!-- Default when absent: local logs, failing tests, debugger; browser via
     chrome-devtools if present. -->

- Prod/QA logs: <skill or tool to query them>
- CI logs: <integration to pull job logs>
- Local: <how local services log, e.g. compose service names>

## Epic workflow

<!-- Default when absent: epics are driven issue-by-issue with a stop (merge + go-ahead)
     between issues; decomposition is manual; design-ahead depth 1-2. -->

- Decomposition: <command/skill that creates the epic + child issues>
- Ordering: <how dependencies between child issues are expressed, e.g. `blocked_by`>
- Delivery: <e.g. one issue = one branch = one MR, reviewed independently>
- Design-ahead depth: <how many upcoming issues the orchestrator specs while workers
  implement the current one. Default when absent: 1-2 — deeper queues go stale faster
  when review feedback shifts the ground>

## Autonomy

<!-- Default when absent: `ask` — every gate question goes to the user, exactly the
     skills' built-in behavior. -->

- Mode: <ask | executive>
- Executive contract (applies only when mode is `executive`): the orchestrator makes and
  RECORDS routine decisions itself — clarify answers land in the PRD's "Assumptions
  (executive)" list, design choices in the ADR, small calls in the ledger — and reports
  them in each phase summary so the user can veto. It still escalates: one-way doors
  (schema, public API, shared write paths, data migrations), user-visible scope changes,
  anything in Security-sensitive areas, and genuine 50/50s where it cannot form a
  recommendation.
- Extra escalations: <project-specific decisions that must always go to the user, if any>
