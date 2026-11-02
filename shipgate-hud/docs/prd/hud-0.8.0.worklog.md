---
type: worklog
title: "Worklog: HUD 0.8.0 — position carries the trace, live dispositions, a review without a board"
created: 2026-11-02
updated: 2026-11-02
tags:
  - worklog
  - shipgate-hud
  - shipgate
status: reviewed
prd: "./hud-0.8.0.md"
related:
  - ../adr/0007-the-trace-is-read-from-the-event-log.md
  - ../adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
---

# Worklog: HUD 0.8.0

> Design + build plan companion to `./hud-0.8.0.md`. Two plugins, two releases: shipgate
> 0.21.0 first (the HUD depends on it), then shipgate-hud 0.8.0.

---

# Design

## Approach

Minimal change on both sides. journal.py computes every new value (shipgate ADR 0009); the
HUD decodes and draws. The decisions with real alternatives are in shipgate ADR 0014 and
HUD ADR 0008; the HUD ADR 0007 amendment records the read floor.

## The new `position --json` keys (shipgate 0.21.0)

```json
{
  "trace": {
    "review_ranking": {"seq": 4, "at": "…", "ranking": {"source": "graph", "files": []}},
    "design_ranking": null,
    "signals_missing": [{"seq": 3, "at": "…"}]
  },
  "dispositions": {"src/a.py:12": {"state": "fixing", "seq": 9, "at": "…"}},
  "verdict": {"…": "every 0.20.0 key", "note": null, "round": 2}
}
```

- `trace.*_ranking.ranking` is the recorded value, verbatim (not validated again).
- `dispositions` folds every `review-disposition` and the newest verdict's map, in seq
  order; the latest event wins per key; `./` dropped; out-of-vocabulary values dropped.
- `verdict.round` counts the verdicts in the vocabulary up to and including the last one.

## `review-disposition` (shipgate 0.21.0)

`{"dispositions": {"<path>:<line|?>": "fixing|fixed|rejected|deferred"}, "round": N,
"note"?: "…"}`. A new `integers` rule kind checks `round` (a non-negative integer, a boolean
refused). Not in `PHASE_OF_EVENT`: it implies no phase.

## The HUD (0.8.0)

- **#8, lazy detection.** A module variable holds the session id the last detection ran
  for. Every detection records it: `session.start`, `classic.SessionStart`, `/hud`, the
  publish gate and the lazy path. On a clock tick, any `tool.call` and any `prompt.submit`,
  the HUD compares `$.session.id()` with it first. When the id differs and the `view` atom
  reads `Off` (a `/clear`, `/resume` or `/branch` moved the process to another session, and
  `$.state` reset with it), the HUD schedules a detection with `$.clock.after(0, …)` and
  passes the event on at once; the detection refreshes when it finds a project. When the id
  differs and the view is not `Off`, it records the id and does nothing else. A project with
  no sidecar runs one directory walk per session change and no process. The clock is started
  once per module load, by whichever path finds the project first.
- **Trace.** Decoded from `position`'s `trace`; `traceRun`, `decodeLog`, `traceOf`,
  `LogEvent`, `CUT_LOG_TRACE` and the "trace was not read" lines go. `Trace` loses
  `isLogCut`, so the stored view's shape tag moves to `shipgate-hud.view-v5`.
- **Read floor.** `position --json` with no `trace` key is `Outdated` (a new sign,
  `MissingTrace`); `MIN_SHIPGATE_VERSION` is `0.21.0`.
- **Cards and the verdict-only round.** HUD ADR 0008.

## CLAUDE.md / impact-map compliance

- Public repo: generic names only in fixtures and docs.
- `hooks/` is security-sensitive: the new `tool.call` / `prompt.submit` listeners must
  no-op in a project with no sidecar and in a session with no surface.
- Two version bumps, each in its `plugin.json` and in `.claude-plugin/marketplace.json`.

---

# Build Plan

## shipgate 0.21.0
- [x] T001 — `review-disposition` event: vocabulary, shape, `integers` rule kind, no implied phase, tests — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py`
- [x] T002 — `position --json`: `trace`, folded `dispositions`, `verdict.note` and `verdict.round`, tests — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py`
- [x] T003 — golden contract: a dispositions stream, `position` prints the trace, the `log` runs dropped, fixture regenerated — file(s): `shipgate/tests/test_hud_contract.py`, `shipgate-hud/tests/fixtures.journal.ts`
- [x] T004 — the `review` skill records each disposition; README, CHANGELOG, version 0.21.0 — file(s): `shipgate/skills/review/SKILL.md`, `shipgate/README.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

## shipgate-hud 0.8.0
- [x] T005 — decoders: trace, dispositions, verdict note and round from `position`; `log` decoder gone; read floor 0.21.0 — file(s): `shipgate-hud/hooks/journal.ts`, `shipgate-hud/hooks/position.ts`, `shipgate-hud/types/index.d.ts`, `shipgate-hud/tests/journal.test.ts`
- [x] T006 — register: no `log` run; lazy detection on a session change (#8) — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts`
- [x] T007 — Review tab: card states with the tolerant board-level match; a round from the verdict (#5) — file(s): `shipgate-hud/hooks/review.ts`, `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/review.test.ts`, `shipgate-hud/tests/views.test.tsx`
- [x] T008 — README, CHANGELOG, version 0.8.0, dependency `>=0.21.0` — file(s): `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`, `shipgate-hud/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- [x] T009 — ranking lines and state cells are never cut: the legend in the header, bare buckets, a wrapped second line at a narrow width, the path's head cut first (lead addendum 2) — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx`, `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`
- [x] T010 — a state reset under the same session id detects again: `Detection` records whether it found a project (lead hardening fix) — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts`, `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`
- [x] T011 — `position --json` folds every verdict's map, not only the newest (lead's call on the dogfooding finding) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py`, `shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md`, `shipgate/README.md`, `shipgate/CHANGELOG.md`

# Review round 1

Workflow run `wf_bb615e28-78e`, three lenses (correctness, conventions+design,
simplicity+security). Counts: 29 found, 27 after dedupe, 7 candidates, 7 survivors, 0
killed, 0 refuters (no BLOCKER or HIGH), 20 below the floor. Verdict: not ready.

Fixed in round 1:
- F1 MEDIUM `shipgate-hud/hooks/register.tsx:1373` — the lazy `tool.call` and `prompt.submit`
  listeners awaited a detection and a refresh before `next(e)`. The detection now runs
  through `$.clock.after(0, …)`, off the event path.
- F2 LOW `shipgate-hud/hooks/register.tsx:899` — the session id is compared first. A
  detection also needs the `view` atom to read `Off`, which is the brief's "state holds no
  detected project". An id change under a live view records the id only.
- F3 LOW `shipgate-hud/docs/adr/0007-the-trace-is-read-from-the-event-log.md:9` — the status
  line and the callout follow the repo's amendment form ("amended by shipgate ADR 0014").
- F4 LOW `shipgate/skills/review/SKILL.md:497` — `round` has one contract: `append` takes a
  non-negative integer, and the skill counts rounds from 1 (skill, PRD FR-003, ADR 0014).
- F5 LOW `shipgate-hud/hooks/journal.ts:745` — one `decodeStamp` decoder for seq and time.
- F6 MEDIUM (promoted from below the floor) `shipgate-hud/hooks/views.tsx:144` — with no
  board, the band counts only the `fixing` entries recorded after the last verdict. A
  `fixing` entry the newest verdict did not name is stale.
- F7 LOW (promoted) `shipgate-hud/hooks/review.ts:629` — a `<path>:?` key labelled every
  card of the file in pass 1. It now matches a line-less card exactly, and is otherwise a
  pass-2 candidate that reaches one card.
- F8 LOW `shipgate-hud/README.md:179` and docs — the README no longer says the HUD computes
  no rule; ADR 0008 names `dispositionsFor`; the plugin descriptions name the verdict round.

## Rejected findings

- `shipgate-hud/hooks/review.ts:659` (MEDIUM 45): pass 2 can draw a key that names no card
  on another finding of the same file. This is the line-agnostic match the addendum asks
  for; pass 2 consumes each key once, so it reaches one card at most (HUD ADR 0008).
- `shipgate-hud/hooks/views.tsx:1035` (LOW 55): the verdict-only header names the last
  verdict's round during a later fix. The header names the last verdict on purpose; the
  lines below it show the current state.
- `shipgate-hud/hooks/register.tsx:873` (LOW 55): the clock starts once per module load.
  This is the 0.7.0 behaviour, unchanged.
- `shipgate-hud/hooks/views.tsx:153` (LOW 45): an older board draws later states. A later
  state is the finding's current state; the old verdict-map rule behaved the same way.
- `shipgate-hud/hooks/register.tsx:851` (LOW 45): a cut detection restores an older note.
  This needs two sessions in one module at once; a cut only makes the next event try again.
- `shipgate/skills/review/SKILL.md:500` (LOW 40): single-quoted `--data` in the example. The
  verdict example uses the same form; a path with a quote is out of scope.
- `shipgate-hud/hooks/journal.ts:725` (LOW 40): the unused `verdict.dispositions` is still
  decoded strictly. A strict decode is the HUD's contract (README, ADR 0006).
- `shipgate-hud/hooks/register.tsx:856` (LOW 35): no retry after a failed refresh. The
  detection succeeded; the failed refresh shows in the pane, and the next tick retries.
- `shipgate-hud/hooks/review.ts:676` (LOW 30): a redelivered return. This behaviour comes
  from before 0.8.0 and is unchanged.
- `shipgate-hud/hooks/register.tsx:898` (LOW 25): a speculative id flip under a subagent.
  F2's view check makes it cost nothing.
- Deferred: `shipgate-hud/hooks/views.tsx:1056` (LOW 35), control characters in a verdict
  note or a key are drawn raw. The engine's `Text` draws plain text; a sanitizer is a
  follow-up.
- The other below-floor items (wording, duplicate copies of a Map, empty maps) were
  checked and dropped: no defect.

# Review round 2

Scope: the fix diff of round 1 (F1–F8) and T009 (lead addendum 2: ranking lines, disposition
lines and card states are never cut). The orchestrator ran the pass alone. It read each changed
function: `detectionDue`, `scheduleDueDetection`, `liveFixing`, `namedKey`,
`dispositionsFor`, `cutHead` and `rankedFileLines`. A separate security review of the hooks
diff found nothing at confidence 8 or above. Every round-1 finding is closed on code and a
pinning test. No new finding. Verdict: ready (journal seq 1192).

# Review round 3

Lead hardening fix after the round-2 verdict. `detectionDue` treated a detection as done for
a session id. So a `$.state` reset that kept the id (the id change at `/clear` comes from the
engine's docs, not from an observed pane) would never detect again, and the HUD would stay
stale until `/hud`. Fix (T010): `Detection` now records `found`. With the same id, a last
detection that found a project, no refresh running and the view reading `Off`, a detection
is due, and it is noted at once so a second event does not schedule another. With the same
id and a last detection that found nothing, the check stays quiet, so a project with no
journal still costs one `$.session.id()` call per event. Tests at
`shipgate-hud/tests/register.test.ts`: same id + found + view `Off` on a tool call, a prompt
and a tick give one detection each; two events give one; same id + not found + view `Off`
give no walk and no process. The id-change cases are unchanged. The orchestrator reviewed the
fix alone (one function, a few lines). Verdict: ready.

# Review round 4

Dogfooding finding after round 3 (journal `deviation` seq 1204): the fold read only the
newest verdict's map, so the round-3 verdict, which named only its own finding, dropped the
round-2 closures, and 8 round-1 `fixing` keys read open again. The lead's call: fold every
`review-disposition` and every verdict's `dispositions`, in seq order, the latest event
winning per key. Fix (T011): `_position_dispositions` in `shipgate/scripts/journal.py` takes
every verdict in the vocabulary. ADR 0014 decision 3, the `build_position` docstring, the
README `position` row and the `v0.21.0` CHANGELOG entry say "every verdict". Tests in
`shipgate/tests/test_journal.py`: a round-3 verdict that names a third key leaves the two
round-2 closures in place, with 0 open; an older verdict's closure holds until a later event
changes it. The golden contract output did not change (each golden stream has one verdict),
so the fixture was not regenerated. The live stream now folds to 17 keys, 0 open. Verdict:
ready.

# Deviations & notes

- Explore ran without the explorer fan: the brief named every file.
- Lead addendum 1 (live dispositions) was folded in at clarify; lead addendum 2 (ranking
  lines never cut) came in during review and became T009, FR-015 and SC-009.
- The round-1 verdict (seq 1172) carried a ranking built by hand; a `deviation` (seq 1180)
  records it, and the round-2 verdict copies the Step 1 ranking.
