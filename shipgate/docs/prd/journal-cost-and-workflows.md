---
type: prd
title: "PRD: Journal-driven cost & precision fixes + workflow orchestration"
created: 2026-09-02
updated: 2026-09-02
tags:
  - prd
status: clarified
issue: "none / ad-hoc"
worklog: "./journal-cost-precision.worklog.md"
related:
  - "./journal-cost-precision.worklog.md"
  - "./journal.md"
  - "../adr/0001-sqlite-flow-journal.md"
---

# PRD: Journal-driven cost & precision fixes + workflow orchestration

> Thirteen days of real journal data from a production project (683 events, 12 work streams plus the tool's own, 36 sessions) show
> where shipgate spends tokens without buying position or evidence, where its recorded
> position drifts from reality, and which fan-outs would be cheaper and sharper as
> `Workflow` scripts than as hand-driven `Agent` fans.

## Problem

The journal (v0.8–v0.10) works: position is read, gates refuse, the Stop hook blocks. But
the first two weeks of production use expose four kinds of waste, all measurable in the
export (a real project's journal, 2026-08-20 → 2026-09-02; the export is private and kept out of this repo):

**Cost**
- The session-start brief is **22.7 KB (~6k tokens) and is injected into every session**
  — 36 sessions ⇒ ~200k tokens in 13 days for orientation alone. It prints all 13 streams
  in full, although at least 8 are finished or dormant for over a week — several with a
  `capture-done` already recorded. There is **no terminal event**,
  so a stream never leaves the brief, and every gate decision it ever recorded (75 total,
  28.6 KB) is reprinted each time.
- Semantic events are appended **one Bash call each** (~400 orchestrator-written events)
  and payloads carry prose that belongs in the worklog: `review-feedback` avg 853 B,
  `debug-root-cause` avg 1.5 KB, `verify-run` avg 442 B, six events over 1.5 KB. The
  journal PRD's own non-goal ("state and evidence pointers, never document content") is
  being violated, at the orchestrator's token expense.
- 51 of 242 `artifact-written` rows are <5 s duplicates of the same path (the tool and
  disk capture paths both fire). No token cost, but noise in every `check`.

**Precision**
- **Recorded phase disagrees with reality** in most streams: one reads `review` with
  five verdicts and two `capture-done`; another reads `review` after `capture-done`; a third
  reads `implement` after `mr-opened` + `capture-done`; a fourth reads `workspace` with
  three MRs open. `phase-entered` is only gated on ordering, not required by the
  phase-owning events (`clarify-passed`, `design-committed`, `verify-run`,
  `review-verdict`, `capture-done`), so the brief's headline field is the least reliable
  one in it.
- **Payload shapes drift**: `gate-decision` has 5+ key sets (`decision`/`chosen`,
  `gate`/`kind`, `mode` missing ×8); `verify-run` has 15 (`outcome`/`result`,
  `task_ids`/`tasks`/`scope`). The fold reads canonical keys only, so 8 verify-runs are
  invisible to the `task-done` gate they were meant to satisfy.
- **Actor is unusable**: 262 NULL, then 8 spellings (`orchestrator`, `fable-orchestrator`,
  `session-… opus-orchestrator`, `claude`, raw session ids). Executive-vs-user attribution
  — the whole point of recording decisions — cannot be queried.
- **Gate mode ratio is unmeasurable**: 62 `ask` vs 10 `executive` in an executive-mode
  project. Whether that is over-escalation or user-raised corrections is unknowable
  because a decision does not say who raised it.
- One stream held **three issues**, against the one-stream-per-issue rule; stream names
  mix `feature/`, `fix/`, bare slugs and `epic-`.

**Process friction** (from the 32 `deviation` rows)
- Worker incidents: a repo-wide formatter run over hundreds of unrelated files, a release
  build where a dev build was meant, workers killed by a spend limit with finished work on
  disk, and user staging markers reset repeatedly across sessions.
- **Over-authorization**: a "start the next item" instruction was read as publish
  authorization and an MR was opened for an unreviewed issue. Nothing in the journal refused it — `mr-opened` has no
  precondition.
- The Stop gate's blocks are not recorded, so its own friction cannot be measured.

**Orchestration shape**
Explore/Design/Review are hand-driven `Agent` fans: the orchestrator reads 2–3 full reports
per phase, then does the dedupe/filter pass itself. Claude Code's `Workflow` tool runs the
same fan deterministically (pipeline, schema-typed returns, adversarial verify, resume
cache) and keeps the raw agent output out of the orchestrator's context.

## Goals & non-goals

**Goals**
- Cut the per-session brief to what the session can act on; let finished streams leave it.
- Make the recorded phase always agree with the latest phase-owning event.
- Make payload shapes and actors canonical at the CLI boundary, not in skill prose.
- Refuse outward actions (`mr-opened`) the journal cannot show were authorized.
- Give the orchestrator cheaper journaling (batching, pointer-not-prose).
- Move the Review fan (and optionally Explore) onto `Workflow`, config-gated, keeping the
  `Agent` path as the default so un-upgraded hosts degrade gracefully.

**Non-goals**
- Not moving Implement onto workflows — it depends on mid-flight `SendMessage`, warm-worker
  reuse, environment repair between rounds and a shared working tree with user staging
  markers; workflow agents cannot be messaged and a killed agent returns `null`.
- Not changing the executive contract itself — first make the ask/executive ratio
  measurable, then tune.
- Not a schema migration of the SQLite journal; every addition reuses the `events` table.
- Not rewriting the reference project's history: the drifted rows stay; new appends get validated.

## Users & stories

- As the orchestrator, I want the brief to name only live work so I don't spend 6k tokens
  per session reading closed streams.
- As the orchestrator, I want `append` to refuse a malformed event with the canonical shape
  printed, so I never learn a payload was invisible to a gate weeks later.
- As the user, I want `mr-opened` refused unless a review verdict or a publish decision
  precedes it, so a "start the next item" instruction can never publish.
- As the user, I want to read `journal.py stats` and see the ask/executive ratio and the
  worker-incident count per stream, so process tuning is evidence-based.
- As the review coordinator, I want a `Workflow` that returns deduped, adversarially
  verified findings so my filtering pass starts from ranked data rather than three essays.

## Functional requirements

Journal — brief
- **FR-001** — A stream is *terminal* once a `flow-completed` or `flow-abandoned` event is
  recorded; `capture-done` followed by no later event for 48 h also renders as terminal.
  Terminal streams are omitted from the default `status` brief (`--all` shows them).
- **FR-002** — Streams whose last event is older than 7 days render as one line
  (name, phase, last event, age); active streams render in full.
- **FR-003** — Per stream the brief lists at most the last 5 gate decisions, each truncated
  to 160 characters, with a count of the rest.
- **FR-004** — `status` accepts `--branch`; the session-start hook passes the current git
  branch of the hook's cwd when one exists, and the matching stream (if any) renders
  first and in full regardless of age.

Journal — precision
- **FR-005** — Appending a phase-owning event (`clarify-passed`→clarify,
  `design-committed`/`design-queued`→design, `verify-run`/`task-done`→implement,
  `review-verdict`→review, `capture-done`→capture) when the folded
  phase differs records the phase transition, so `status.phase` always agrees with the
  latest phase-owning event. Whether that is an auto-inserted `phase-entered
  {implied:true}` or a refusal with the exact command is a design fork (ADR).
- **FR-006** — `append` validates required keys per type and normalizes known aliases
  (`chosen→decision`, `result→outcome`, `tasks→task_ids`, `kind→gate`) before writing;
  a payload missing a required key is refused (exit 4) with the canonical shape printed.
  `vocab --shape <type>` prints that shape.
- **FR-007** — `actor` is canonical: one of `orchestrator | worker | user | hook |
  watcher`, optionally suffixed `@<session-or-model>`; omitted defaults to
  `orchestrator`; other values are refused.
- **FR-008** — `gate-decision` carries `raised_by ∈ {user, orchestrator}` (default
  `orchestrator`) in addition to `mode`, so escalation vs correction is separable.
- **FR-009** — `mr-opened` is refused unless the stream holds, after its last `task-done`,
  either a `review-verdict` with verdict `ready` (`pass` is normalized to it), or a `gate-decision` with
  `gate=publish`. Override only via `--force` with a reason.
- **FR-010** — The Stop hook records a `gate-blocked` event on the `shipgate` stream
  (session, findings count) whenever it blocks.
- **FR-011** — `file_changed.py` skips an `artifact-written` whose path and mtime were
  recorded within the previous 5 seconds.

Journal — cost
- **FR-012** — `append --batch` reads JSONL from stdin and appends each line in order under
  one connection; gate refusals name the line and nothing after the failing line is
  written.
- **FR-013** — A payload over 1 KB is refused unless `--force`; the refusal names the
  worklog as the home for prose and `refs` as the pointer key. Skills say "pointer, not
  prose".
- **FR-014** — `journal.py stats [--since]` prints per-stream: events by actor, gate
  decisions by `mode × raised_by`, deviations, verify-runs per task, review rounds,
  sessions touching the stream, and the rendered brief size.

Skills / config
- **FR-015** — `feature` and `setup` state the stream rule: stream name = branch name,
  one stream per issue (epic children are separate streams).
- **FR-016** — The config template gains a `## Worker guardrails` section; `model-tiers`
  requires it pasted verbatim into every worker brief (every worker incident in the
  reference journal was a brief-compression failure).
- **FR-017** — The config template gains an `## Orchestration` section:
  `review: agents | workflow`, `explore: agents | workflow` (default `agents`).
- **FR-018** — With `review: workflow`, the `review` skill invokes the `Workflow` tool with
  a bundled script: lens finders (`agentType: shipgate:code-reviewer`, schema-typed
  findings, do-not-flag + pre-rulings via `args`) → in-script dedupe by file:line →
  adversarial verify per finding ≥ the confidence floor → ranked return. The coordinator's
  Step 2 starts from that return; `review-verdict` data carries the workflow `runId`.
- **FR-019** — With `explore: workflow`, the Explore phase runs the 2–3 lenses through a
  workflow with schema `{findings[], essential_files[]}` and the orchestrator reads only
  the essential files, as today.
- **FR-020** — Workflow agents always receive an explicit `model` per `model-tiers` (the
  tool's default inherits the session model, which violates the tier rule).
- **FR-021** — Design keeps the architect fan on `Agent` (or a schema-only workflow); no
  judge panel — the orchestrator and user remain the judges.

## Success criteria

- **SC-001** — On the reference export (2026-09-02), the default brief renders
  under 4 KB (from 22.7 KB) with no live stream missing.
- **SC-002** — Re-folding the reference export under FR-005 semantics yields a phase that
  matches the last phase-owning event for all 12 work streams.
- **SC-003** — Every append from a phase skill in one full flow on a test project passes
  validation first time (no `--force`, no alias fallback).
- **SC-004** — `mr-opened` without a preceding ready verdict or publish decision exits 4
  (test).
- **SC-005** — A journaled flow's semantic appends fit in ≤ 1 Bash call per phase
  boundary on average (batching used by the skills).
- **SC-006** — One live review run on a real project with `review: workflow` produces a verdict whose
  findings the user accepts at ≥ the current rate, with the coordinator's filtering pass
  reading only the workflow return.
- **SC-007** — `pytest shipgate/tests` green; hooks still cost nothing on un-journaled
  projects (fast path unchanged).

## Constraints & assumptions

- The journal stays dependency-free Python + SQLite; no schema version bump (all new
  fields live in `data`, new types in the vocabulary).
- Stricter `append` refusals change what already-installed plugins do — per pandora's
  escalation contract this ships as a version bump the user releases explicitly.
- `Workflow` availability: skill-instructed invocation counts as opt-in; hosts without the
  tool keep the `agents` path (graceful degradation is the published contract).
- Risky: FR-005 auto-insertion could mask a genuinely wrong flow; the ADR must weigh it
  against refusal.

## Assumptions (executive)

- Explore for this work = data mining of the export in the main session → no explorer
  fan — the evidence is one table, not a codebase.
- Tune the executive contract now? → No; add `raised_by` and `stats` first, tune on data.
- Move Implement onto workflows? → No (see non-goals); revisit for mechanic-tier bulk
  edits only where the project allows worktrees.
- Rewrite the reference project's drifted history? → No; validation applies to new appends only.
- Design judge panel via workflow? → No; blueprints may be schema-typed but judging stays
  with orchestrator + user.

## Delivery (user decisions, 2026-09-02)

- **Two deliverables.** Slice 1 — journal cost + precision (FR-001…FR-016) on this
  branch, worklog `journal-cost-precision.worklog.md`, testable offline against the
  reference export. Slice 2 — workflow orchestration (FR-017…FR-021) on
  `feat/workflow-orchestration`, worklog `workflow-orchestration.worklog.md`, gated on one
  live review trial.
- **`mr-opened` publish gate (FR-009): adopted.** Ships as a version bump the user
  releases explicitly.
- **Workflow trial scope: Review and Explore both** in slice 2.
- **Confidentiality.** This repo is public. Artifacts here never name the reference
  project, its issue ids, stream names, people or paths; the export stays outside the repo.
