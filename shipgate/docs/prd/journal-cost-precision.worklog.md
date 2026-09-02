---
type: worklog
title: "Worklog: Journal cost & precision (slice 1)"
created: 2026-09-02
updated: 2026-09-02
tags:
  - worklog
status: done
prd: "./journal-cost-and-workflows.md"
related: ["../adr/0002-implied-phase-transitions.md", "../adr/0003-session-attribution-via-current-session.md"]
---

# Worklog: Journal cost & precision (slice 1)

> Design + build plan for FR-001…FR-016 of `./journal-cost-and-workflows.md`. Slice 2
> (workflow orchestration, FR-017…FR-021) has its own worklog on its own branch.

---

# Design

## Approach

Minimal-change, designed inline (executive): every requirement is an addition to
`scripts/journal.py`, the four hooks, or skill prose, and the solution space had two real
forks — both recorded as ADRs (0002 implied phases, 0003 actor/session). No schema
migration: new event types join the vocabulary, new fields live in `data`, process state
in `meta`.

## Architecture

`journal.py` gains four internal tables that replace prose in the skills:

- `EVENT_SHAPES` — per type: required keys, per-key enums, alias map, default values.
  Applied by `append` before the gates: aliases rewritten to canonical keys, defaults
  filled (`gate-decision.raised_by=orchestrator`, `mode` required), then required keys
  checked; a violation prints the canonical shape. `vocab --shape <type>` prints the same.
- `PHASE_OF_EVENT` — `clarify-passed→clarify`, `design-committed|design-queued→design`,
  `verify-run|task-done→implement`, `review-verdict→review`, `capture-done→capture`.
  Drives the implied `phase-entered` (ADR 0002). `mr-opened` implies nothing; it is gated.
- `ACTOR_ROLES` — `orchestrator|worker|user|hook|watcher`; `parse_actor()` splits
  `role@label`, defaults the label from `meta.current_session` (ADR 0003).
- `TERMINAL_TYPES` — `flow-completed|flow-abandoned`; plus the derived rule
  "`capture-done` is the last event and is older than 48 h".

Gates added to `validate_gate`: `mr-opened` (a `review-verdict verdict=ready` or a
`gate-decision gate=publish` after the last `task-done`); payload size (> 1024 bytes of
`json.dumps(data)` on work streams, waived by `--force`); `artifact-written` dedupe (same
path, same mtime, within 5 s of the previous one → returns the existing seq, writes
nothing). `review-verdict` canonical `verdict ∈ {ready, not-ready}` with `pass→ready`,
`fail→not-ready` aliases; the existing evidence precondition keys off `ready` (today it
keys off `pass`, which the review skill never writes — the gate has been inert).

`fold_stream` adds `terminal`, `dormant` (last event > 7 days), `implied_phase`,
`gate_decision_count`. `build_status` orders: branch-matched stream first, active
streams in full, dormant streams as one line, terminal streams hidden with a count
(`--all` shows everything). Per stream the renderer prints the last 5 decisions,
each cut to 160 chars, plus "+N earlier".

New commands: `append --batch` (JSONL on stdin, sequential in one connection, first
failure stops, output names the line); `stats [--since ISO] [--json]`.

Hooks: `session_start.py` writes `meta.current_session` (via a new `journal.py session
--set <id>` subcommand, so hooks keep holding no policy) and passes `--branch $(git
rev-parse --abbrev-ref HEAD)` when cwd is a git checkout. `stop.py` appends
`gate-blocked {session, findings}` to the meta stream before emitting the block.
`file_changed.py`/`post_tool_use.py` are unchanged — dedupe lives in `append`.

## Data flow

Skill → `journal.py append` → parse actor → normalize shape → validate gate → implied
phase-entered (same txn) → INSERT → stdout names seq/version (+ implied transition).
Hook SessionStart → `session --set` → `status --branch` → brief. Hook Stop → `check` →
(findings) → `gate-blocked` → block JSON.

## Data model / schema

No schema change. Vocabulary: `+flow-completed`, `+gate-blocked`. `meta`: `+current_session`.
Payload additions: `phase-entered.implied/implied_by`, `gate-decision.raised_by`.

## API / contract changes

Stricter refusals on installed machines: unknown actor role (exit 2), missing required
keys (exit 4), oversized payload (exit 4), unauthorized `mr-opened` (exit 4). Alias
normalization keeps every shape the skills currently emit valid. `import` stays gate-free.
Ships as shipgate **v0.11.0** — released by the user, per pandora's escalation contract.

## Reference implementation

`_validate_task_done` + `TestGateTaskDone` (`tests/test_journal.py`) — the shape every new
gate and its test mirror: read events by type, decide, raise `GateViolation` with the
exact fix in the message. `_render_decision` is the reference for shape-tolerant
rendering (show what is there, never `None -> None`).

## CLAUDE.md / impact-map compliance

- Single plugin (`shipgate/`); no other pandora plugin touched.
- Hooks are a security-sensitive area (config): `stop.py`/`session_start.py` changes get
  the built-in `/security-review` at Review; fast path on un-journaled projects must stay
  byte-for-byte (tests in `test_hooks.py`).
- Public repo: tests use synthetic streams only; the reference export stays outside.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations
- [x] T001 — Vocabulary + shape tables — file(s): `scripts/journal.py` — done when:
  `flow-completed`, `gate-blocked` in `EVENT_VOCABULARY`; `EVENT_SHAPES`, `PHASE_OF_EVENT`,
  `ACTOR_ROLES`, `TERMINAL_TYPES` defined; `vocab --shape <type>` prints a shape; tests in
  `tests/test_journal.py::TestVocabCommand` fail first, then pass.
- [x] T002 — Actor canon + session default (ADR 0003) — file(s): `scripts/journal.py`,
  `hooks/session_start.py`, `tests/test_journal.py`, `tests/test_hooks.py` — done when:
  `session --set/--get` subcommand exists; `append` refuses unknown roles (exit 2), defaults
  `orchestrator@<current_session>`; `event_session` reads the suffix; SessionStart sets
  `meta.current_session`; `check` rule B sees a skill-written gate-decision (regression
  test).

## Precision
- [x] T010 — Shape validation + alias normalization — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: `gate-decision` (gate, question, decision, mode;
  `chosen→decision`, `kind→gate`; `raised_by` default), `verify-run` (outcome∈pass|fail,
  task_ids list; `result→outcome`, `tasks→task_ids`), `deviation` (note;
  `correction|what→note`), `capture-done` (promoted, dropped), `design-committed`
  (worklog), `flow-started` (request) enforced; stored payload is canonical; `import`
  bypasses shapes (test).
- [x] T011 — Implied phase-entered (ADR 0002) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: appending a phase-owning event with a differing
  folded phase inserts `phase-entered {implied:true, implied_by}` in the same transaction
  (version N, event N+1), forward jumps fill `skipped`, backward moves recorded, stdout
  names the transition; `--json` output includes `implied_phase`.
- [x] T012 — Review verdict canon — file(s): `scripts/journal.py`, `skills/review/SKILL.md`,
  `tests/test_journal.py` — done when: `verdict∈{ready,not-ready}`, `pass→ready`,
  `fail→not-ready`; `_validate_review_verdict` gates on `ready` and a test proves
  `ready` without fresh evidence exits 4.
- [x] T013 — `mr-opened` publish gate (FR-009) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: refused (exit 4) without a `ready` verdict or
  `gate=publish` decision after the last `task-done`; accepted with either; `--force`
  waives with reason.
- [x] T014 — `artifact-written` dedupe in append (FR-011) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: same path + same mtime within 5 s returns the
  existing seq and writes no row; different mtime writes.
- [x] T015 [P] — `gate-blocked` from the Stop hook (FR-010) — file(s): `hooks/stop.py`,
  `tests/test_hooks.py` — done when: a blocking Stop appends `gate-blocked {session,
  findings}` to `shipgate`; a non-blocking Stop appends nothing; un-journaled fast path
  unchanged.

## Cost
- [x] T020 — Terminal/dormant folding + brief rendering (FR-001…FR-003) — file(s):
  `scripts/journal.py`, `tests/test_journal.py` — done when: terminal streams hidden with
  a count line (`--all` shows), dormant (>7 d) streams one line, active streams full with
  last-5 decisions cut to 160 chars and "+N earlier"; `(implied)` marker on phase.
- [x] T021 — `--branch` ordering + hook wiring (FR-004) — file(s): `scripts/journal.py`,
  `hooks/session_start.py`, `tests/test_journal.py`, `tests/test_hooks.py` — done when:
  a stream equal to the branch (or `feature/<branch-slug>`) renders first and in full
  regardless of age; hook passes the branch only when `git rev-parse` succeeds.
- [x] T022 [P] — Payload cap (FR-013) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: >1024 B on a work stream exits 4 naming the
  worklog + `refs`; `--force` waives; `watch/` and `shipgate` streams exempt.
- [x] T023 [P] — `append --batch` (FR-012) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: JSONL on stdin appended in order in one
  connection; a failing line stops the batch, names the line, nothing after it written;
  `--json` lists results.
- [x] T024 [P] — `stats` command (FR-014) — file(s): `scripts/journal.py`,
  `tests/test_journal.py` — done when: per-stream events by role, decisions by
  `mode × raised_by`, deviations, verify-runs/task and re-verified tasks, review rounds,
  sessions touching, implied phases, rendered brief bytes; `--since`, `--json`.

## Skills, config, docs
- [x] T030 — Skill + config text — file(s): `skills/feature/SKILL.md`,
  `skills/setup/SKILL.md`, `skills/knowledge-base/SKILL.md`, `skills/verify/SKILL.md`,
  `skills/implement/SKILL.md`, `skills/model-tiers/SKILL.md`, `config-template.md`,
  `README.md` — done when: stream rule (name = branch, one stream per issue) stated;
  `flow-completed` appended after `capture-done`; batch + "pointer, not prose" guidance;
  `## Worker guardrails` section in the template and required verbatim in every brief;
  actor `role@label` documented; no skill quotes a payload shape the CLI now prints.
- [x] T031 — Release notes + version — file(s): `CHANGELOG.md`, `.claude-plugin/plugin.json`,
  `../.claude-plugin/marketplace.json` — done when: v0.11.0 entry; both versions in
  lockstep.
- [x] T032 — Reference-export check (SC-001, SC-002) — file(s): none in repo — done when:
  `status` against the private export renders < 4 KB with every active stream present,
  and re-folding it under `PHASE_OF_EVENT` matches the last phase-owning event for all 12
  work streams; evidence recorded as a `verify-run` (sizes and counts only, no stream names).

## Traceability
- FR-001, FR-002, FR-003 → T001, T020
- FR-004 → T021
- FR-005 → T001, T011
- FR-006 → T001, T010, T012
- FR-007 → T002
- FR-008 → T010
- FR-009 → T013
- FR-010 → T015
- FR-011 → T014
- FR-012 → T023
- FR-013 → T022
- FR-014 → T024
- FR-015, FR-016 → T030
- SC-001, SC-002 → T032
- SC-003 → T010, T011, T030
- SC-004 → T013
- SC-005 → T023, T030
- SC-007 → every test task; hooks fast path in T002/T015/T021

## Deviations & notes (filled during implementation)
- 2026-09-02 — T001/T010: `EVENT_SHAPES` gained a `lists` key (list-typed fields) and
  `value_aliases` (verdict `pass→ready`, `fail→not-ready`); `vocab --json` keeps its
  name→purpose map, whole-table shapes are `vocab --shape` with no argument. Impact: none
  on callers; README documents the final form.
- 2026-09-02 — T011: `append_event` returns `AppendResult(seq, version, implied_phase,
  duplicate)`; `--json` always carries both fields. Only `cmd_append` consumed the tuple.
- 2026-09-02 — T002: `parse_actor` keeps a bare role for ANY event whose `data.session`
  is set (not only `hook`) — one rule instead of a role carve-out.
- 2026-09-02 — T030 sweep: prose made forge-neutral (MR/PR) at the user's request; the
  event name `mr-opened` stays as a contract. Two watcher examples carried an external
  issue id — replaced with `#1234`.

- 2026-09-02 — T023: `--expect` with `--batch` is a usage error (a version can hold for
  one line only); an empty batch too. Every line is parsed before any append.
- 2026-09-02 — T020/T021: `fold_stream` also returns `age_days` and `branch_match`;
  terminal streams under `--all` sort after dormant ones. `stats` totals report
  `brief_bytes` as the real rendered brief (never time-sliced); per-stream
  `stream_render_bytes` honours `--since`/`--stream`.
- 2026-09-02 — T021: `current_branch()` lives in `session_start.py` (single consumer), not
  `_common.py`; hook and `--branch` flag ship in lockstep — never release one without the
  other (a hook passing `--branch` to an older journal reads as "journal unreachable").
- 2026-09-02 — SC-001 first measurement: 4933 B (from 22695). Renderer tightened: 3
  decisions on non-branch active streams (5 on the branch match), task ids capped to the
  last 5, human timestamps to minutes. Second measurement: 4022 B (SC-001 met). Render-only;
  `--json` unchanged. Next trims if ever needed: clip `open designs` assumes text, shorten
  the `last verify` line.
- 2026-09-02 — T032 evidence (counts only): 11/12 work streams shown, 7 dormant
  one-liners, 1 completed hidden; before FR-005 6/12 streams had a stale recorded phase;
  re-folding the export with `PHASE_OF_EVENT` applied, all 12 match their last
  phase-owning event (SC-002 met). The PRD's "13 streams" counted the tool's own stream.
- 2026-09-02 — FR-005: `mr-opened` implies no phase (design line "it is gated"); the
  publish gate already forces a `review-verdict` or publish decision, which do imply one.
  PRD amended.
- 2026-09-02 — T020: reopen rule `REVIVING_TYPES` — a `flow-resumed`, `phase-entered` or
  any phase-owning event after a terminal event makes the stream active again; hook and
  bookkeeping events (`artifact-written`, `deviation`) do not.
- 2026-09-02 — T024: `stats` also counts `review-feedback` (`fb` column), not in FR-014.
- 2026-09-02 — FR-009: the gate accepts `ready` only; `pass` is normalized to `ready` on
  new appends, and pre-0.11 imported rows keep `pass`, so a legacy stream needs `--force`
  to open its MR/PR. Accepted: the export shows one such stream. PRD amended.

- 2026-09-02 — Review round 1 fixes: alias collisions refused; `flow-started` revives a
  completed stream; artifact dedupe is window-based (5 s, bounded below); publish
  authorization = user-raised `gate=publish` with `decision=publish`; brief lines are
  whitespace-collapsed; `--json` append reports `version_before`; `stats` counts distinct
  tasks and excludes `user@` labels from sessions; hooks pass `--branch=`/`--set=` forms,
  scrub `GIT_*`, warn when session attribution fails; the journal db is never a watched
  path; `--force` over the payload cap needs `--force-reason`.
- 2026-09-02 — Confidentiality sweep: a private tracker id found in five pre-existing test
  fixtures and one config-template example (at HEAD) replaced with `#4242` / `#1234`; root `CLAUDE.md` added with the public-repo rule.

- 2026-09-02 — Review round 2 fixes: every rendered brief field passes `_one_line`
  (stream, event type, outcome, timestamps, open designs); `user` joins
  `SESSIONLESS_ROLES`; hooks resolve the project from the payload cwd first and fall back
  to the ambient dirs only when cwd is missing (`resolve_project`, shared by SessionStart
  and Stop); NaN/Infinity in `--data` is a usage error; Stop block reasons are one-line.
  Accepted as documented: the fast path cannot see the payload cwd; `--force` does not
  bypass the artifact dedupe.

## Rejected findings

Round 2 (2026-09-02), killed on evidence:
- `stop.py` `format_reason` interpolates `finding.detail` raw — the detail is built from task
  ids (regex `T\d+`) and artifact paths; neither can carry a newline in practice, and the
  hooks hold no rendering policy. Journal-side `render_findings` is sanitized.
- Open-designs lines render flush-left after `_clip` — matches the gate-decision lines,
  which have done so since round 1; cosmetic.
- Staged copies of four files still carry the pre-fix ids — the index is the user's review
  marker set, restaged at commit time; the working tree is clean.

Round 1 (2026-09-02), killed on evidence:
- Gates re-check keys the shape already requires (`_validate_task_done` etc.) — defence in
  depth, harmless; the gate keeps the type assertion.
- Recency sort compares ISO strings — every appended `ts` is `utc_now()` with `+00:00`;
  imported non-UTC stamps are a corner not worth a parser in the hot path.
- Four near-identical `backdate` test helpers — test-only churn; left for a later tidy.
- Payload cap evadable by naming a stream `watch/…` — the journal is a discipline tool for
  a cooperating agent, not an authorization boundary; documented, not enforced.
- Stale `meta.current_session` can misattribute a second concurrent session — accepted
  consequence in ADR 0003; an explicit `@label` overrides.
- `mr-opened` gate is self-satisfiable — narrowed instead (publish decision must be
  user-raised and literally `publish`), recorded as a review gate-decision.
