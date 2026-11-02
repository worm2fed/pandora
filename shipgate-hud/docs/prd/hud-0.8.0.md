---
type: prd
title: "PRD: HUD 0.8.0 — position carries the trace, live dispositions, a review without a board"
created: 2026-11-02
updated: 2026-11-02
tags:
  - prd
  - shipgate-hud
  - shipgate
status: clarified
issue: "#8, #5, HUD ADR 0007 follow-up"
worklog: "./hud-0.8.0.worklog.md"
related:
  - ../adr/0007-the-trace-is-read-from-the-event-log.md
  - ../adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../../../shipgate/docs/adr/0009-the-journal-computes-the-hud-position.md
  - ../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
---

# PRD: HUD 0.8.0 — position carries the trace, live dispositions, a review without a board

> shipgate 0.21.0 prints the trace and each finding's current disposition in `position
> --json`, and records a disposition when it is decided. shipgate-hud 0.8.0 reads them from
> `position`, draws a review round from the verdict when no board exists, and detects the
> project again without `classic.SessionStart`.

## Problem

Four gaps, all visible in the HUD:

1. **Stale after `/clear` (#8).** An organization-managed session skips `classic.*` hooks
   for user mods. The HUD detects the project again after `/clear`, `/resume` and `/branch`
   only in a `classic.SessionStart` handler. So in such a session the band and pane stay
   stale or empty until the person runs `/hud`.
2. **Empty Review tab for an agent fan (#5).** A project with `review: agents` never
   produces a review board. The Review tab says "No review captured" even after the journal
   records a `ready` verdict.
3. **A second process per refresh (HUD ADR 0007).** `position --json` does not print the
   risk rankings or the `signals-missing` deviations, so each bound refresh also runs
   `log --stream <s> --json`. The log grows with the stream.
4. **The `fixed` label appears unpredictably (addendum).** The only source of a finding's
   state is `review-verdict.dispositions`, written once at the end of a round. Mid-round a
   card shows nothing. A key matches a card only by `<path>:<line>`, so a moved line never
   matches.

## Goals & non-goals

**Goals**
- `position --json` carries every value the HUD draws. The HUD runs no `log`.
- A finding's state is visible as soon as the orchestrator decides it.
- The HUD recovers after `/clear`, `/resume` and `/branch` on any event that reaches user
  mods.
- An agent-fan review shows a round in the Review tab.

**Non-goals**
- No change to how a Workflow board is captured or folded.
- No new HUD control: the HUD still writes nothing.
- No change to `review-verdict`'s shape: its `dispositions` stay closed states.

## Functional requirements

shipgate 0.21.0:
- **FR-001** — `position --json` prints a `trace` object: the newest `review-verdict` that
  carries `ranking` and the newest `design-committed` that carries `ranking` (each as seq,
  time and the ranking verbatim, or null), and every `deviation` of kind `signals-missing`
  (seq and time), oldest first.
- **FR-002** — `position --json`'s `verdict` also prints the verdict's `note` (text or null)
  and its `round`: how many verdicts in the vocabulary the stream holds up to and including
  this one.
- **FR-003** — A new event type, `review-disposition`, takes `dispositions` (a map from
  `<path>:<line|?>` to `fixing`, `fixed`, `rejected` or `deferred`), `round` (a non-negative integer; the
  `review` skill counts rounds from 1)
  and an optional `note`. `append` refuses another value, a missing key or a non-integer
  round. `vocab --shape review-disposition` prints the shape.
- **FR-004** — `review-disposition` implies no phase.
- **FR-005** — `position --json` prints `dispositions`: per finding key, the current state
  with the seq and time of the event that decided it. The fold reads every
  `review-disposition` and the newest verdict's `dispositions`, in seq order; the latest
  event wins per key. A leading `./` is dropped from a key.
- **FR-006** — The `review` skill appends `review-disposition` as each decision is made:
  `fixing` when a fix is dispatched, the closed state when it is confirmed. The verdict's
  map stays the final word.
- **FR-007** — No existing key of `position --json` is renamed or removed.

shipgate-hud 0.8.0:
- **FR-008** — The HUD detects the project again on the next 60 s tick, `tool.call` or
  `prompt.submit` after a session change: the session id differs from the last
  detection's and `$.state` holds no detected project (the view reads `Off`). The event
  passes on at once; the detection runs after it.
  The `classic.SessionStart` handler stays as a fast path.
- **FR-009** — The HUD reads the trace from `position`'s `trace` and runs no `log` call.
- **FR-010** — A finding card shows the folded state from `position`: `fixing`, `fixed`,
  `rejected` or `deferred`; Accept and Kill when no state. A state recorded before the
  board was captured is not drawn on it.
- **FR-011** — A card's key match is tolerant, in order: exact `<path>:<line>`, the short
  location, `<path>:?`, a path tail with the same line, then a path tail with any line. A
  key that matched one card exactly is not reused by a line-agnostic match on another.
- **FR-012** — With no board for the stream and a verdict or a folded disposition, the
  Review tab draws a round: `round N · verdict <ready|not-ready> · <time>` (or `round 1 ·
  in progress` with no verdict yet), the verdict's note, one line per folded disposition,
  then the SC checklist. A board, when present, wins.
- **FR-013** — The band counts a `fixing` finding as open.
- **FR-014** — The dependency is shipgate `>=0.21.0`. A `journal.py` whose `position --json`
  has no `trace` key is outdated: the pane names 0.21.0, as it names the floor today.
- **FR-015** — A risk-ranking line (READ FIRST, RISK RANKING) puts the legend `fix · churn ·
  fan-in` in its header and draws each file as the path and three bare buckets. The buckets,
  a disposition line's state and a card's state tag are never cut: at a narrow width the
  buckets wrap onto an indented second line, and the path's head is cut first (lead
  addendum 2).

## Success criteria

- **SC-001** — `position --json` on the golden script prints `trace`, the verdict's `note`
  and `round`, and the folded `dispositions`, and every key it printed in 0.20.0.
- **SC-002** — `append` accepts a valid `review-disposition` and refuses an out-of-vocabulary
  state, a missing `round` and a non-integer `round`; the stream's phase does not move.
- **SC-003** — A stream with two interim dispositions and a verdict that closes one of them
  folds to the verdict's state for that key and the interim state for the other.
- **SC-004** — With `$.state` reset and no `classic.SessionStart`, the next tick,
  `tool.call` or `prompt.submit` detects the project and draws the position again; a
  project with no sidecar runs no process on those events.
- **SC-005** — A bound refresh runs `status` and `position` only: no `log` run.
- **SC-006** — The Review tab draws a verdict-only round; a stream with neither shows the
  empty-state line; a stream with a board shows the board.
- **SC-007** — A card shows each of the four states, and a disposition keyed on another
  line of the same file reaches the card.
- **SC-008** — Every check is green: shipgate's unit tests, `claude plugin validate` for
  both plugins, `claude plugin test shipgate-hud`, `tsc`.
- **SC-009** — At a narrow and a wide width, every ranking line, disposition line and
  card shows its buckets or its state whole.

## Constraints & assumptions

- Public repo: nothing employer- or customer-specific (root `CLAUDE.md`).
- shipgate's scripts stay Python 3.9 compatible.
- `hooks/` is a security-sensitive area: a hook that runs on every `tool.call` and
  `prompt.submit` must no-op cheaply in a project with no sidecar.

## Assumptions (executive)

- Key names → `trace.{review_ranking, design_ranking, signals_missing}` with `seq`/`at`,
  top-level `dispositions`, `verdict.note`, `verdict.round` — `at` matches every other time
  key `position` prints; `trace` mirrors the HUD's own `Trace`.
- Read floor → raised to 0.21.0 — the HUD drops `log`, so an older `journal.py` cannot give
  the trace; drawing nothing would read as "none recorded". An older `journal.py` is
  `Outdated`, as one older than 0.18.0 is today.
- Does `review-disposition` imply review? → no phase — `fixing` is appended in the fix
  round, while the flow is back in implement; implying review would flip the phase on every
  dispatch.
- What marks a session change for #8? → `$.session.id()` differs from the id the last
  detection ran for — `/clear`, `/resume` and `/branch` each move the process to another
  session id, the same moment `$.state` resets.
- Is `fixing` open? → yes, for the band count; the card shows the tag instead of the buttons.
- Which dispositions does a verdict-only round list? → every folded key, in key order — the
  fold already holds only the latest state per key.
- `round` validation → a new `integers` rule kind (a non-negative integer, not a boolean).

## Open questions

None.
