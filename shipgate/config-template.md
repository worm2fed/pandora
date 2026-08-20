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

## Journal

<!-- Default when absent: no journal — phase is inferred from artifact shape (checkbox
     state, [NEEDS CLARIFICATION] markers) exactly as shipgate has always worked. This
     section is written by `/shipgate:setup`; you rarely hand-write it. -->

- Database: <path, e.g. `.claude/shipgate.db` — where the append-only flow journal lives>

When this section is present the project is **journaled**, and three things change:

- **Position is recorded, not guessed.** Phase transitions, gate decisions, verify
  evidence, and review verdicts are appended as events; `feature` routes from the
  journal alone. Artifact inference is not a fallback here — a missing event reads as
  "still in the previous phase" until it is recorded.
- **Capture is enforced by the plugin's hooks**, not by remembering: artifact writes are
  recorded automatically, and a session cannot end while an expected event is missing.
  The hooks read `.claude/shipgate.json` (a generated sidecar holding the database path,
  the artifact-home globs, and the ledger path) — `setup` writes it; never hand-edit it,
  re-run `setup` instead. If that sidecar is absent, every hook exits immediately and the project
  behaves as un-journaled.
- **The database is local, disposable state.** Gitignore it (`shipgate.db*`); the
  artifacts in git or your wiki remain the portable record. Moving machines degrades to
  un-journaled behavior unless you carry it over with `journal.py export` / `import`.
  Never mount it into a container: the journal runs in SQLite's WAL mode, which needs
  filesystem locks a bind mount doesn't provide, and because WAL is a property of the
  file the breakage outlives the container (recover with `PRAGMA journal_mode=DELETE`
  from the host). If a bot runs a shipgate phase, it runs it on the host.

**The journal does not replace the ledger.** The ledger holds *prose learnings* mid-flow
and is deliberately lossy — entries are promoted to a durable home or dropped at triage,
then removed, so an empty ledger is the healthy steady state. The journal holds
*operational state* and is never emptied. Triage still writes learnings to the stores
above; the journal only records **that** it happened, as a `capture-done` event. Don't
park a learning in the journal — it is machine-local and gitignored, so anything durable
left there is lost to your teammates and to your next machine. The sidecar does carry the
ledger's path, so `status` can report how many untriaged entries are waiting; that is the
`knowledge-base` skill's ~15-entry nudge made mechanical, and it is information only —
the ledger never gates a session.

**Event names are a fixed vocabulary.** `journal.py vocab` lists them and `append` refuses
anything else, because an event named something plausible-but-unlisted is inert — it
records, and no gate or report ever reads it, which looks like success. Pass `--new-type`
to mint a genuinely new concept on purpose. Stream names are free: `feature/<slug>` or the
branch (`fix/8744-vessel-rate`) both work. `journal.py doctor` reports any off-vocabulary
events already in a journal.

Dial enforcement down by setting `enforce.stop_gate` or `enforce.auto_capture` to false
in the sidecar (both default true). Run `journal.py doctor` when anything looks stale.

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
- Optional, when a **Journal** is configured: a watcher may append what it observes to
  `watch/<project>!<iid>` streams via the plugin's `journal.py` (`baseline`,
  `pipeline-flip`, `comments-added`, `merge-status`, `conflicts`, `approved`, `merged`,
  `closed`). Watchers typically keep a single overwritten snapshot file, so a missed or
  crashed tick loses the intervening history; journalling makes the snapshot a cache and
  the history reconstructable. Suggestion, not a requirement — a watcher that doesn't do
  this still works exactly as described above.

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
