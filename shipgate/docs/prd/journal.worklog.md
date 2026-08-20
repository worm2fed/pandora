---
type: worklog
title: "Worklog: Flow journal + setup bootstrap"
created: 2026-08-20
updated: 2026-08-20
tags:
  - worklog
status: built
prd: "./journal.md"
related: ["../adr/0001-sqlite-flow-journal.md"]
---

# Worklog: Flow journal + setup bootstrap

> Design + build plan companion to `./journal.md`.

---

# Design

## Approach

Enforced capture, bolted *beside* the existing artifact flow rather than restructuring
it. Two halves: (a) the journal is the **sole routing source** on journaled projects, so
a missed append surfaces immediately as a stuck flow instead of degrading silently;
(b) a **hook layer** records what the harness can observe deterministically and refuses
to let a session end with semantic events missing. Un-bootstrapped projects are
byte-identical to today (legacy mode). Core trade-off: more moving parts (hooks +
generated sidecar) in exchange for a journal trustworthy enough to route from.

## Architecture

```
scripts/journal.py          ← the only reader/writer (python3 stdlib)
        ▲  Bash calls              ▲ hook calls
skills/*/SKILL.md           hooks/{core,filechanged}.json + hooks/*.py
   semantic events            ← auto-capture, resume injection, stop gate
skills/setup/SKILL.md       ← NEW: bootstrap — interview, config, sidecar, db
config-template.md          ← NEW: ## Journal section + watcher contract
.claude/shipgate.md         ← prose config, model-facing (declares journal)
.claude/shipgate.json       ← generated sidecar, machine-facing (hooks read this)
.claude/shipgate.db         ← per-project journal (gitignored; -wal/-shm too)
```

**The enforcement split — who records what:**

| Layer | Records | Enforcement |
|---|---|---|
| Hooks (deterministic) | `artifact-written`, session start/end | Automatic — no model involvement, cannot be forgotten |
| Skills (semantic) | phase transitions, gate decisions, verify evidence, verdicts | Stop hook blocks session end when an expected event is missing against observed artifact changes |
| `journal.py` (validation) | — | Refuses invalid gate transitions; `--force` is recorded in the event |
| Orchestrator | — | Routes from `status` only; a missed append reads as "still in previous phase" |

Responsibilities:
- **`journal.py`** owns schema, appends (conditional + gate-validated), derived views
  (`status`), integrity (`doctor`), portability (`export`/`import`), and the
  `check` subcommand the Stop hook calls. No prose-config parsing — callers pass
  `--db`, or the script resolves it from the sidecar.
- **Hooks** are thin: resolve sidecar (absent ⇒ exit 0 immediately), shell out to
  `journal.py`. All policy lives in the script, so hooks need no updating as the event
  taxonomy grows.
- **Phase skills** each gain a short `### Journal` block naming the events they must
  append and when.
- **`feature` orchestrator** routes journal-first from `status`; artifact inference
  exists only when no sidecar is present.
- **`setup`** is the only component that *creates* config, sidecar, and db.

## Data flow

**Semantic append** (skill-driven): skill reaches a lifecycle moment → Bash:
`python3 "$PLUGIN_ROOT/scripts/journal.py" append --stream feature/<slug>
--type phase-entered --data '{"phase":"design"}' [--expect N]`
→ script resolves db from sidecar (or `--db`), opens WAL, `BEGIN IMMEDIATE`, next
version = `MAX(version)+1` (checked against `--expect` when given), validates the gate
transition, inserts, prints `seq`/`version`. Version conflict → exit 3 + current
version; gate violation → exit 4 + the unmet precondition. Nothing written on either.

**Automatic capture** (hook-driven): an artifact file changes on disk → `FileChanged`
hook (armed by `watchPaths` at session start) → sidecar present? (no ⇒ exit 0) →
`journal.py append --type artifact-written --data '{"path":…,"source":…}'`. A
`PostToolUse` hook on `Write|Edit` is a second, faster source for the common case,
deduped by path+mtime. Watching the *disk* rather than only the tool is what makes this
airtight: a PRD written via a Bash heredoc is invisible to `PostToolUse`. No model
involvement either way, so capture cannot be forgotten or misremembered.

**Resume** (hook-driven): SessionStart → hook → `journal.py status` → brief injected
into context. The orchestrator therefore starts *holding* the position rather than
having to think to ask for it; it routes from that brief and reads only the artifacts
the brief names.

**Stop gate**: session tries to end → Stop hook → `stop_hook_active` true? (⇒ exit 0) →
`journal.py check --session <id> --json` → script compares observed `artifact-written`
events against expected semantic events (worklog checkbox delta with no `task-done`;
PRD written during clarify with no `gate-decision`; implementation edits with no
`verify-run`) → clean ⇒ exit 0 with no `decision` field; missing ⇒ top-level
`decision: block` whose `reason` names **every** missing append in one message, so the
model can satisfy the gate in a single round.

## Data model / schema

```sql
PRAGMA journal_mode=WAL;
CREATE TABLE events (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,   -- global order
  stream  TEXT    NOT NULL,                    -- see naming below
  version INTEGER NOT NULL,                    -- per-stream, contiguous from 1
  type    TEXT    NOT NULL,
  data    TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(data)),
  ts      TEXT    NOT NULL,                    -- UTC ISO-8601, written by the script
  actor   TEXT,                                -- free label: session/agent/watcher
  UNIQUE (stream, version)
);
CREATE INDEX idx_events_stream ON events(stream, seq);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- meta: schema_version=1, created_at, plugin_version
```

**Stream naming**: `feature/<slug>` (one per PRD slug; epics: `epic/<slug>` for the
tracking checklist + design-ahead queue, children are ordinary feature streams),
`watch/<project>!<iid>` (watcher contract), `shipgate` (setup/migration meta-events).

**Event taxonomy v1** (extensible via `data`; unknown types are legal):
`artifact-written` {path, tool, session} — hook-written, never by a skill ·
`session-started` / `session-ended` {session, source} — hook-written ·
`flow-started` {request, branch} · `phase-entered` {phase} · `gate-decision`
{gate, question, decision, mode: ask|executive, rationale} · `clarify-passed`
{prd, fr_count} · `design-committed` {issue, worklog, adrs[]} · `design-queued` /
`design-invalidated` {issue, assumes} · `task-done` {task_id} · `deviation` {note} ·
`verify-run` {scope, commands: [{cmd, exit, head, tail}], outcome, task_ids[]} —
output trimmed, event capped ~4 KB · `review-verdict` {verdict, findings, mr} ·
`mr-opened` {ref, url} · `review-feedback` {ref, threads} · `capture-done`
{promoted, dropped} · `flow-suspended` / `flow-resumed` / `flow-abandoned` {reason}.
Watch streams: `baseline`, `pipeline-flip`, `comments-added`, `merge-status`,
`conflicts`, `approved`, `merged`, `closed`. Meta: `setup-completed`,
`schema-migrated`, `imported`.

## API / contract changes

`journal.py` CLI (db resolved from the sidecar unless `--db PATH` is given):
- `init` — create schema, stamp meta. Idempotent.
- `append --stream S --type T [--data JSON] [--expect N] [--actor A] [--force]` —
  exit 0 = written (prints version); **exit 3** = version conflict (prints current
  version); **exit 4** = gate violation (prints the unmet precondition); exit 1 =
  infrastructure failure. `--force` bypasses gate validation only, and stamps
  `{"forced": true, "force_reason": …}` into the event (`force_reason`, not `reason` —
  too generic a key to be collision-proof inside an arbitrary `data` payload).
- `status [--feature SLUG]` — resume brief (all features, or one).
- `check --session ID` — the Stop-hook gate; exit 0 clean, exit 5 + a list of missing
  semantic events (machine-readable with `--json`).
- `log --stream S [--limit N] [--json]` · `streams` — raw inspection.
- `doctor` — integrity_check, WAL mode, schema version, pending migrations, sidecar
  agreement with the prose config.
- `export [--stream S]` / `import FILE` — JSONL round-trip; import merges by
  (stream, version), reports conflicts, never overwrites.

These are *script* exit codes for skills reading them via Bash; they are **not** hook
exit codes. Hook wrappers translate: a `check` exit 5 becomes block-JSON, and every
other outcome becomes exit 0 (see the hook contract below).

**Gate validation rules v1** (enforced on `append`, overridable only by `--force`):
`clarify-passed` requires the PRD at the recorded path to contain no
`[NEEDS CLARIFICATION]`; `task-done` requires a prior `verify-run` with
`outcome=pass` naming that task id; `phase-entered` must follow the declared phase
order (backward transitions are legal — review→implement is normal — but skipping
forward past an unpassed gate is not); `review-verdict=pass` requires a `verify-run`
after the last `task-done`.

Config contract (new template section):
```
## Journal
- Database: .claude/shipgate.db   <!-- set by /shipgate:setup; omit section = no journal -->
```

Sidecar contract — `.claude/shipgate.json`, generated by `setup`, read by hooks and by
`journal.py` for db resolution:
```json
{
  "version": 1,
  "db": ".claude/shipgate.db",
  "artifact_homes": { "prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                      "worklog": "docs/prd/*.worklog.md" },
  "enforce": { "stop_gate": true, "auto_capture": true }
}
```
`enforce` flags exist so a user can dial enforcement down without hand-editing hooks;
both default true. Absent sidecar ⇒ every hook exits 0 immediately ⇒ legacy mode.

### Hook contract (verified against the harness docs, 2026-08-20)

`hooks/hooks.json` at the plugin root is auto-discovered (no manifest entry). Commands
reference `${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py`; use **exec form** (`command` +
`args`) so paths with spaces need no shell quoting.

| Hook | Matcher | Output contract |
|---|---|---|
| `SessionStart` | `startup\|resume\|fork` | `hookSpecificOutput.additionalContext` = the `status` brief, plus `watchPaths` arming `FileChanged`. |
| `FileChanged` | **omitted** | appends `artifact-written`; re-returns `watchPaths`. **Primary** capture path. |
| `PostToolUse` | `Write\|Edit\|NotebookEdit` | appends `artifact-written` (deduped against `FileChanged` by path+mtime). Strictly after-the-fact — cannot block, and does not need to. |
| `Stop` | — | clean ⇒ exit 0, no `decision` field at all. Unmet ⇒ **top-level** `{"decision":"block","reason":…}` (NOT nested in `hookSpecificOutput` — that nesting is silently ignored for Stop). |

`watchPaths` is a list of **literal absolute file paths, not globs**, and each return
replaces the whole dynamic list. So the sidecar's globs are expanded at session start and
re-expanded on every `FileChanged` fire. Residual gap, accepted: an artifact *created* by
a Bash heredoc in a session where no other watched file changes stays unwatched until the
next expansion — `PostToolUse` covers the ordinary create-via-Write case. A `FileChanged`
matcher would not help; it registers literal filenames in the cwd rather than matching
paths, which is why it is omitted.

`FileChanged` ships in its own `hooks/filechanged.json`, listed alongside
`hooks/core.json` in `plugin.json`'s `hooks` array. The event landed in Claude Code
v2.1.83 and the handling of an unrecognized event name by an older build is undocumented;
isolating it bounds that worst case to "disk capture missing" instead of "the Stop gate
silently vanished". Neither file is named `hooks.json`, so plugin auto-discovery cannot
also register them and double-fire every hook.

Three verified constraints the implementation must respect:

- **`FileChanged` is required, not a nicety.** `PostToolUse` on `Write|Edit` never fires
  for a file written by a Bash heredoc or `sed`, and skills do write that way. A
  disk-watching hook closes that hole; `PostToolUse` stays as a fast second source.
- **Exit 1 is not special.** Only **exit 2** blocks (stderr becomes the reason). A hook
  that exits 1 is treated as a non-blocking error and the session proceeds — so the
  Stop hook must emit block-JSON on exit 0, or exit 2, and never exit 1.
- **`stop_hook_active` must be honored.** When true, the session is already continuing
  because of a prior block; the hook exits 0 immediately. The harness hard-overrides a
  Stop hook after **8 consecutive blocks** anyway, so `check` findings must be
  *satisfiable in one round* — block once, name every missing event at once, pass on
  the next stop. Never emit a finding the model cannot resolve by appending.

Known enforcement gaps, accepted and documented rather than engineered around:
a user interrupt (Ctrl-C) does not fire `Stop`, so a deliberately abandoned turn
escapes the gate; and plugin hooks installed at **user scope run in every project**,
which is why the no-sidecar fast path is a correctness requirement (cheapest possible
check first — `test -f` on the sidecar, then exit 0).
Watcher contract (addition to the MR-watcher template section): a watcher MAY append
watch events via the same CLI; when it does, its snapshot file becomes a cache and tick
history is reconstructable from the journal. Suggestion only — no watcher is patched
by this feature.

Breaking changes: none. Absent config section ⇒ absent behavior (FR-009).

## CLAUDE.md / impact-map compliance

- Primary home: the `shipgate` plugin (pandora repo) — single-repo change.
- No schema/downstream obligations outside the plugin; voyager's `babysit-mrs` dual-write
  is a separate, later deliverable in the voyager repo.
- Version bump: 0.7.1 → 0.8.0 in `.claude-plugin/marketplace.json` (new skill + hooks).
- New blast radius to respect: **hooks fire in every project the user opens**, not just
  shipgate ones. The no-sidecar fast path is therefore a correctness requirement, not an
  optimization — T031/T033 verify it explicitly.
- The journal is host-local by construction: never mount it into a container (macOS
  bind-mount SQLite corruption, per ADR 0001 consequences).

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations
- [x] T001 — `scripts/journal.py`: schema + `init`/`append` (incl. `--expect`
  conditional append + exit-code contract) — done when: two racing `--expect` appends
  yield exactly one winner (SC-002).
- [x] T002 — `tests/test_journal.py` (stdlib `unittest`, run
  `python3 -m unittest discover shipgate/tests`): failing tests first for T001's
  contract — done when: red → green on append/conditional/ordering/json-validity.
- [x] T003 — `journal.py`: `status`/`log`/`streams` derived views — done when: a
  seeded fixture stream renders the resume brief with correct phase and open gates
  (SC-001 shape).
- [x] T004 [P] — `journal.py`: `doctor` + `export`/`import` (idempotent merge) — done
  when: export→import into empty db reproduces identical `status` (SC-006).
- [x] T005 — `journal.py`: gate validation on append (rules v1) + `--force` audit
  stamp — done when: `clarify-passed` against a PRD holding `[NEEDS CLARIFICATION]`
  exits 4 and writes nothing (SC-008); `--force` writes with `forced:true`.
- [x] T006 — tests for T005: each rule red-first, plus force-override — done when:
  every rule in "Gate validation rules v1" has a passing negative test.
- [x] T007 — `journal.py`: `check` subcommand (missing-semantic-event detection from
  `artifact-written` deltas) + sidecar db resolution — done when: a fixture db with a
  ticked checkbox and no `task-done` exits 5 naming that task.

## Feature
- [x] T010 — `config-template.md`: `## Journal` section + watcher-contract note — done
  when: template documents path, sidecar, gitignore expectation, legacy-mode rule.
- [x] T011 — `skills/setup/SKILL.md`: detection (git root, umbrella, forge remote),
  interview with recommended defaults, write `.claude/shipgate.md` **and the sidecar**,
  `init` db at chosen location (project `.claude/` default, global dir or custom as
  alternates), gitignore `shipgate.db*`, append `setup-completed`; re-run = update mode
  + migrations — done when: clean-project walkthrough yields working config + sidecar +
  db, `doctor` passes, db invisible to `git status` (SC-005).
- [x] T012 — `skills/feature/SKILL.md`: journal-as-sole-routing-source (status → route;
  artifact inference only when no sidecar; drift surfaced and recorded) — done when:
  resume on a journaled fixture routes without artifact scanning (SC-001).
- [x] T013 — phase-skill Journal blocks: `workspace` (flow-started), `route-and-map`
  (phase-entered), `clarify` (gate-decisions, clarify-passed), `design`
  (design-committed, design-queued/invalidated), `implement` (task-done, deviation),
  `review` (review-verdict, mr-opened, review-feedback), `knowledge-base`
  (capture-done); each states its events + the infra-failure rule (db unavailable ⇒
  surface loudly, legacy mode only with user acknowledgement) — done when: every
  semantic event in the taxonomy has exactly one appending skill, and no skill claims
  a hook-written event.
- [x] T014 — `skills/verify/SKILL.md`: persist evidence as `verify-run` events
  (trimmed, capped) — done when: a verify pass leaves a queryable evidence event and
  unblocks the `task-done` gate (SC-003).

## Enforcement layer
- [x] T030 — `hooks/hooks.json` (exec form, `${CLAUDE_PLUGIN_ROOT}` paths) +
  `hooks/session_start.py`: emit the `status` brief on stdout and `watchPaths` for the
  artifact homes — done when: a fresh session on a journaled fixture opens already
  holding the position with no tool call, and `FileChanged` is armed.
- [x] T031 — `hooks/file_changed.py` (primary) + `hooks/post_tool_use.py` (secondary,
  deduped by path+mtime): append `artifact-written`; sidecar `test -f` fast path first
  — done when: a worklog edited via **Bash heredoc** is captured (the `PostToolUse`
  blind spot), a duplicate tool-write yields one event, and an unrelated repo records
  nothing.
- [x] T032 — `hooks/stop.py`: exit 0 immediately when `stop_hook_active`; else run
  `check` and emit **top-level** `{"decision":"block","reason":…}` listing every
  missing event at once; never exit 1 — done when: ticking a checkbox without
  `task-done` blocks the stop and names it (SC-007), the next stop after the append
  passes, and a seeded multi-finding case resolves in one round (no second block).
- [x] T033 — hook integration test: scripted session fixture exercising
  capture → block → append → clean stop — done when: green end to end; the same
  fixture without a sidecar produces zero journal activity (SC-004); and a forced
  8-block scenario cannot occur (findings are always satisfiable).

## Polish
- [x] T020 — `README.md`: Journal + setup + enforcement docs (incl. how to dial
  `enforce` flags down); `commands/shipgate.md` mentions setup for un-bootstrapped
  projects.
- [x] T021 — marketplace.json 0.8.0; sweep all skills for legacy-mode wording (SC-004).

## Traceability
- FR-001/002/003 → T001, T002 · FR-004 → T003 · FR-011 → T004
- FR-005 → T010, T013 · FR-006 → T014 · FR-007 → T012 · FR-008 → T011
- FR-009 → T010, T013, T031, T033, T021 · FR-010 → T010
- FR-012 → T030, T031 · FR-013 → T007, T032 · FR-014 → T011, T007 · FR-015 → T005, T006
- SC-001 → T003, T012, T030 · SC-002 → T002 · SC-003 → T013, T014 · SC-004 → T021, T033 ·
  SC-005 → T011 · SC-006 → T004 · SC-007 → T032 · SC-008 → T005, T006

## Deviations & notes (filled during implementation)
- 2026-08-20 — **`watchPaths` is literal absolute paths, not globs** (verified against the
  harness docs). Sidecar globs are expanded at session start and re-expanded on every
  `FileChanged` fire. Residual gap accepted and documented: an artifact *created* by a
  Bash heredoc in a session where nothing else changes stays unwatched until the next
  expansion. A `FileChanged` matcher can't close it — matchers there register literal
  filenames in the cwd rather than matching paths — so the matcher is omitted.
- 2026-08-20 — **`FileChanged` split into `hooks/filechanged.json`**, with `core.json`
  holding the enforcement hooks and both listed in `plugin.json`'s `hooks` array. The
  event needs Claude Code ≥ v2.1.83 and an older build's handling of an unknown event
  name is undocumented; isolating it bounds the worst case to "disk capture missing"
  rather than "the Stop gate silently vanished". Neither file is named `hooks.json`, so
  auto-discovery cannot also register them and double-fire everything.
- 2026-08-20 — **Hook fast path rewritten against measurements**, not intuition.
  `subprocess` (~10ms) and `pathlib` (~7ms) were the entire per-invocation overhead, so
  both are imported lazily and the sidecar check now runs before stdin is parsed.
  Measured on this machine: 51ms → 35ms per invocation, which is exactly the bare
  `python3` startup cost — the hook itself is no longer measurable. This matters because
  `PostToolUse` fires on every edit in *every* project, journaled or not. A POSIX `sh`
  guard would cut the remaining 35ms to ~8ms; rejected for now as it trades portability
  (Windows has no `sh`) for a saving that is already below noticeable, but it is the
  obvious next step if the latency is ever felt.
- 2026-08-20 — **The event vocabulary is now closed, after a real bug flow exposed why
  it had to be.** First live use journalled diligently — 10 events — and was invisible to
  every gate and report, because it used its own names: `decision` (×5) for
  `gate-decision`, `verify-passed` for `verify-run`, `workspace-ready` for
  `flow-started`. The taxonomy was open by design ("unknown types are always allowed"),
  so all of it was accepted silently. Nobody noticed until the human did — the exact
  failure this layer exists to prevent, in a worse form than forgetting, because it
  reads as success.
  My first instinct — reject only *near misses* by string similarity — was wrong, and the
  data proves it: `workspace-ready` shares no substring with `flow-started`. It is a
  semantic miss, and similarity matching would have let a third of the drift through.
  So: `EVENT_VOCABULARY` in `journal.py` is the single source of truth, `append` refuses
  anything unlisted (exit 4) naming the closest candidates, `--new-type` mints a genuinely
  new concept deliberately and stamps `new_type` on it, `journal.py vocab` lists the set,
  and `doctor` reports off-vocabulary events already recorded. `--force` deliberately does
  NOT waive it: force skips a gate precondition, whereas an unreadable event is not a
  precondition problem. A test asserts every `--type` the skills document is appendable,
  so prose and code cannot drift apart again.
  Root cause of the whole episode was mine: **`structured-debug` had no Journal block.**
  T013 listed the seven feature-path skills and missed that the bug path is a peer entry
  point, so on a bug flow the model had no canonical names to copy and invented sensible
  ones. Block added, including `bug-reproduced` and `debug-root-cause` as first-class
  types.
- 2026-08-20 — **Work streams are defined by exclusion, not by a `feature/` prefix.** The
  same flow named its stream after its branch (`fix/8744-vessel-rate-escalating-tier`),
  which is arguably better than `feature/<slug>` since it ties the journal to the branch —
  but `status` filtered on the prefix and reported "No feature streams recorded" while
  holding ten events. Now anything that is not the `shipgate` meta stream or a `watch/`
  stream is work, and `--feature` matches a bare slug, a full stream name, or a substring.
- 2026-08-20 — **`status` renders decisions from whatever keys they carry.** The fold
  normalized every `gate-decision` to canonical keys, so four real decisions recorded
  under a `chosen` payload printed as `None -> None (None)` — real history looking like
  corruption. The fold now starts from the event's own payload and overlays canonical
  keys; the renderer falls back to the payload's contents rather than to placeholders.
- 2026-08-20 — **Sidecar gained a `ledger` path, and `status` reports untriaged
  entries.** Raised as "isn't the ledger a first-class feature — why isn't its path
  declared?", and the answer was yes: every other path a machine needs was in the
  sidecar, the ledger's lived only in prose. Rather than add a vestigial field, it earns
  its place — the `knowledge-base` skill already asks for a nudge past ~15 unpromoted
  entries, which is a count a script gets right every time and a model notices
  erratically. `status` (which the session-start hook injects) now carries
  `{path, exists, entries, nudge}` and prints one line **only when the ledger is
  non-empty**, since an empty ledger is the healthy steady state and saying so every
  session would be noise. Deliberately *not* a gate: entries legitimately sit across
  sessions until triage, so blocking on them would be wrong. Seven tests. The obvious
  follow-up, not built: a rule firing only when `review-verdict=pass` lands with a
  non-empty ledger and no `capture-done` after it — that is the documented
  "review passed → capture immediately" discipline, and it would change when sessions
  block, so it needs a deliberate decision rather than a drive-by.
- 2026-08-20 — **Rule A now gates only flows the journal is tracking.** Found while
  bootstrapping Voyager, whose artifacts live in a Drive-bisynced vault: a sync pulling
  a teammate's edit is indistinguishable from the user writing the file, and every one
  of the 29 existing worklogs has ticked boxes with no journal history, so the gate
  would have blocked sessions over work the user never touched. Rule A therefore skips
  a worklog unless its feature stream holds at least one event that is not
  `artifact-written` — capture is the hook's own footprint, so counting it would mark
  every observed file as tracked and defeat the check. Rules B and C already required a
  tracked stream (B needs a recorded phase, C only inspects deliberate appends), so
  neither changed. Three journal tests plus one end-to-end hook test cover it; two
  existing fixtures had to establish a real flow first, which makes them more
  representative rather than less. Generic fix, not a Voyager workaround — legacy
  artifacts predate the journal in every repo that adopts it.
- 2026-08-20 — **WAL warning moved to where it will be read.** A parallel session
  measuring the junge fleet pointed out that WAL is a property of the database *file*,
  not the connection: one open from inside a container over a bind mount fails with
  "disk I/O error" and leaves the file broken after the container exits, until
  `PRAGMA journal_mode=DELETE` is run from the host. The ADR already carried the
  boundary, but whoever breaks it will be reading `journal.py`, so the explanation and
  the recovery step now sit at the pragma. `doctor` reports `journal_mode`, verified.
- 2026-08-20 — **Not machine-verified, deliberately**: the `setup` interview and the
  orchestrator's routing *judgement* are prose instructions to a model, so no test
  covers them. What is covered is everything mechanical underneath — the sidecar shape
  setup emits, `init`/`doctor` on a fresh project, and the `status` brief the routing
  reads — exercised by the integration fixture. Treat the first real `/shipgate:setup`
  run as the acceptance test for the interview itself.
- 2026-08-20 — Caught during verification: `stop.py` called `json.loads` after its import
  was removed in the refactor. It compiled fine, and `safe_main` would have converted the
  `NameError` into exit 0 — i.e. the Stop gate would have silently never blocked, the
  exact failure class this feature exists to prevent. Fixed, and a static unbound-name
  check over `hooks/*.py` now guards the pattern; `py_compile` alone does not catch it.
