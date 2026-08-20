---
type: prd
title: "PRD: Flow journal + setup bootstrap"
created: 2026-08-20
updated: 2026-08-20
tags:
  - prd
status: clarified
issue: "none / ad-hoc"
worklog: "./journal.worklog.md"
related: []
---

# PRD: Flow journal + setup bootstrap

> Record shipgate's operational state in an append-only SQLite journal instead of
> re-inferring it from artifact shape, and ship a `/shipgate:setup` skill that
> bootstraps a project (config + journal) interactively.

## Problem

Shipgate currently *infers* everything and *records* nothing:

- **Phase is re-derived on every resume** from artifact shape — checkbox counts in the
  worklog, `[NEEDS CLARIFICATION]` markers in the PRD. There is no authoritative "we are
  here" pointer; ambiguous artifact states (partially edited worklog, PRD/worklog in
  conflicting phases) have no defined resolution.
- **Gate decisions are ephemeral.** Executive-mode decisions land as prose lists inside
  the PRD/ADR; verify evidence exists only as this-session command output — once the
  session ends, only the `- [x]` tick survives, decoupled from the proof.
- **The MR-watcher keeps a single-generation snapshot** (`state.json` overwritten every
  tick); the printed diff survives nowhere, and "reset" means deleting all history.
- **Concurrent sessions have no collision detection** — two sessions advancing the same
  feature discover it only by clobbering each other's artifacts.

Separately, **bootstrapping a project is manual**: the user copies `config-template.md`
to `.claude/shipgate.md` and edits it by hand. There is no guided setup, which is also
the natural home for creating the journal database.

## Goals & non-goals

**Goals**
- An append-only, per-project SQLite journal of flow events: phase transitions, gate
  decisions, verify evidence, review verdicts, watcher observations.
- Resume routes from the journal alone; artifact inference survives only as legacy mode
  on projects that were never bootstrapped.
- A `/shipgate:setup` skill that interviews the user, writes `.claude/shipgate.md`, and
  initializes the journal at the user's preferred location.
- **Capture that cannot be silently skipped**: on a journaled project, a missing event
  is either recorded automatically, refused at the gate, or blocks the session from
  ending — never a silent fallback to guessing.
- Legacy mode preserved: a project without config/journal behaves exactly as today (the
  plugin's published contract: "integrations degrade gracefully").

**Non-goals**
- No server dependency of any kind (KurrentDB/NATS/Postgres explicitly evaluated and
  rejected for this scale — see ADR 0001).
- Not a replacement for PRD/ADR/worklog files — those remain the human-readable content
  authority; the journal stores state and evidence pointers, never document content.
- Not a cross-machine sync mechanism — the journal is local and gitignored by default
  (export/import exists as an escape hatch, not a sync protocol).
- Not solving the knowledge-vault bisync conflict problem (separate concern, different
  layer).
- Patching any concrete watcher implementation (e.g. voyager's `babysit-mrs`) — this PRD
  only defines the integration contract a watcher can adopt.

## Users & stories

- As the shipgate orchestrator, I want to read "where is this feature" from a durable
  record so that resume is exact instead of inferred.
- As a user resuming weeks later, I want the journal to tell me what was decided, by
  whom (me vs executive mode), and what verify actually proved.
- As a user running two sessions, I want the second writer to be *told* it collided
  instead of silently clobbering state.
- As a new shipgate adopter, I want one command that sets up my project — config
  questions with sane defaults, journal created where I choose.

## Functional requirements

- **FR-001** — The plugin ships a dependency-free script (`scripts/journal.py`,
  Python 3 stdlib only) exposing: `init`, `append` (with optional expected-version
  conditional append), `log`, `status`, `streams`, `doctor`, `export`, `import`.
- **FR-002** — Events are append-only: `(stream, version)` unique, versions contiguous
  per stream, global order preserved. No update/delete surface exists in the CLI.
- **FR-003** — A conditional append with a stale expected version fails with a distinct
  exit code and reports the current version; nothing is written.
- **FR-004** — `status` renders a resume brief per feature stream: current phase, last
  event, open gate decisions, queued designs — consumable by the orchestrator without
  reading raw events.
- **FR-005** — The config template gains a `Journal` section declaring the database
  path; every phase skill appends its lifecycle events when (and only when) the config
  declares a journal, and the hook layer enforces that they do (FR-012/FR-013).
  Infrastructure failure is distinct from forgetting: if the db itself is unavailable
  (corrupt, locked), the flow surfaces it loudly and continues in legacy mode for the
  session only with the user's acknowledgement.
- **FR-006** — Verify evidence (commands run, exit codes, trimmed output) is persisted
  as `verify-run` events, size-capped per event.
- **FR-007** — On journaled projects the journal is the **sole routing source**: the
  `feature` orchestrator routes from `status`, never from artifact scanning. Artifact
  writes are auto-captured (FR-012), so journal/artifact drift is mechanically visible;
  disagreements are surfaced to the user (artifacts win for content, journal for
  operational position) and the resolution is recorded as an event. Artifact inference
  survives only as legacy mode on never-bootstrapped projects.
- **FR-008** — `/shipgate:setup` detects project shape (git root, umbrella layout,
  forge remote), interviews the user with recommended defaults, writes
  `.claude/shipgate.md`, initializes the journal at the chosen location, and gitignores
  the db files. Re-running enters update mode (edit config sections, run schema
  migrations) instead of overwriting.
- **FR-009** — A project with no `.claude/shipgate.md` or no journal db behaves exactly
  as the plugin does today; no skill hard-requires the journal.
- **FR-010** — The config template's MR-watcher section documents an optional contract:
  a watcher may append watch events to `watch/<ref>` streams via the same script, making
  tick history durable and diffs reconstructable.
- **FR-011** — `export`/`import` round-trip the journal as JSONL; import is idempotent
  (merges by stream/version, conflicts reported, never overwritten).
- **FR-012** — The plugin ships hooks that auto-capture harness-observable events with
  no model involvement: changes to files under the configured artifact homes append
  `artifact-written` events, captured by watching the **disk** (so writes made through
  Bash, not just Write/Edit, are seen); a session-start hook injects the `status` brief
  so resume is journal-first by construction. Hooks fast-path no-op when the project
  has no sidecar (FR-014), so non-shipgate projects pay nothing — required because
  user-scope plugin hooks fire in every project.
- **FR-013** — A Stop hook runs a deterministic consistency check for the ending
  session: semantic events missing against observed artifact changes (a worklog task
  ticked with no `task-done`, a PRD written at clarify with no `gate-decision`) block
  the stop, naming the missing appends, until the model records them. Findings must be
  satisfiable in a single round — every missing event is named at once, and the hook
  stands down when the harness signals it is already re-entrant.
- **FR-014** — `setup` also writes a machine-readable sidecar (`.claude/shipgate.json`:
  db path + artifact-home globs) for hooks and scripts. The prose config remains the
  model-facing authority; the sidecar is regenerated by `setup`, never hand-edited.
- **FR-015** — `journal.py` validates gate transitions on append and refuses invalid
  ones with a distinct exit code: `clarify-passed` while the PRD contains
  `[NEEDS CLARIFICATION]` markers; `task-done` without a prior passing `verify-run`
  naming the task; `phase-entered` out of order. `--force` overrides are permitted but
  recorded inside the event — audited, not silent.

## Success criteria

- **SC-001** — Resuming a feature in a fresh session yields the correct phase from
  `status` alone, with zero artifact scanning, on a journaled project.
- **SC-002** — Two concurrent appends to one stream with the same expected version:
  exactly one succeeds; the loser exits non-zero with the current version.
- **SC-003** — After a completed flow, the journal answers: every phase entered (with
  timestamps), every executive gate decision (with rationale), and what verify ran for
  each completed task — without consulting session transcripts.
- **SC-004** — On a project never touched by `setup`, all shipgate skills run with
  today's exact behavior (verified by absence of journal references in their output).
- **SC-005** — `setup` on a clean project produces a working config + journal in one
  pass; `doctor` passes; the db files never appear in `git status`.
- **SC-006** — `export | import` into an empty db reproduces identical `status` output.
- **SC-007** — Ticking a Build Plan checkbox without appending `task-done` cannot end
  the session: the Stop hook blocks and names the missing event.
- **SC-008** — `append --type clarify-passed` against a PRD still containing
  `[NEEDS CLARIFICATION]` exits with the gate-violation code and writes nothing.

## Constraints & assumptions

- Python 3 must be on PATH (macOS and Linux ship it; the plugin already assumes a
  POSIX-ish environment). If missing, setup says so and configures without a journal.
- SQLite in WAL mode is sufficient for the concurrency model: multiple local Claude
  Code sessions on one machine. Multi-machine concurrency is out of scope by design.
- Assumptions (executive):
  - Journal db default location is `.claude/shipgate.db` (per project, gitignored);
    global (`~/.local/share/shipgate/`) offered as an alternative during setup.
  - The journal is machine-local operational state; artifacts (in git/vault) remain
    the durable, portable content. A machine switch degrades to artifact inference —
    accepted, that is today's behavior.
  - Event payloads reference artifact paths; they never duplicate document content.
  - Capture is enforced, not requested — three layers: journal-as-sole-routing-source
    (a missed append reads as a stuck flow at the next routing decision), hooks
    (auto-capture + Stop-gate consistency check), and script-side transition
    validation. The un-enforceable residue is payload *quality* (a rationale string
    can be lazy) — presence is mechanical, prose quality stays a human-review concern.

## Open questions

None — clarified 2026-08-20 in session; decisions recorded above and in ADR 0001.
