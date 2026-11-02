---
type: worklog
title: "Worklog: The style canon and the code graph leave a trace"
created: 2026-11-02
updated: 2026-11-02
tags:
  - worklog
  - shipgate
status: implementing
prd: "./style-and-graph-trace.md"
related:
  - ../adr/0011-a-map-without-signals-records-its-own-deviation.md
  - ../adr/0012-the-canon-reviewer-loads-the-style-skill-itself.md
  - ../adr/0013-signals-emits-the-ranking-the-journal-carries.md
---

# Worklog: The style canon and the code graph leave a trace

> Design + build plan companion to `./style-and-graph-trace.md`. One release: shipgate 0.20.0.

---

# Design

## Approach

Minimal change on the existing seams. The journal validates three new optional keys and
records one automatic deviation. `signals.py` emits the payload the journal carries. The
skills write the keys, and `stats` reads them. Three forks, three ADRs (0011, 0012, 0013).

## Architecture

- `scripts/journal.py`
  - Two new shape rule kinds: `objects` (a key whose value is a JSON object that passes a
    sub-shape) and `list_objects` (each item of a JSON list passes the sub-shape). The
    existing rule kinds apply inside the sub-shape.
  - `phase-entered`: `lists: [style]`, `objects: {signals: {required: [source], enums:
    {source: [graph, regex, none]}}}`.
  - `design-committed` and `review-verdict`: `objects: {ranking: {required: [source],
    enums: {source: [...]}, list_objects: {files: {required: [path], enums: {fix, churn,
    fan_in: [low, mid, high, top, null]}}}}}`. A list keeps the order; the journal sorts
    object keys.
  - `append_event`: after a `route-and-map` `phase-entered` without `signals`, insert a
    `deviation` {note, kind: signals-missing, auto: true} in the same transaction
    (ADR 0011). `AppendResult.deviation_seq` reports it.
  - `stats`: per stream `trace` = {style: {implement, review}, graph: {route, design,
    review}}, plus `deviation_kinds`. Totals count streams per state. The text render adds
    a trace section.
- `scripts/signals.py`: `hotspots --json` adds `ranking` (ADR 0013). Every JSON payload that
  ran a graph selection adds `graph_note` when the graph is absent or failed, never when it
  is `off`. JSON only: the table keeps the advisory-once rule (see Deviations).
- `skills/review/references/review-workflow.js`: `canon` lens definition, `styleSkills` arg,
  the canon block in the finder and refuter prompts (ADR 0012).
- `agents/code-reviewer.md`: `Skill` tool, `canon` lens row.
- Skills: `route-and-map` (signals always, `source`, `graph_note` line, the deviation),
  `design` (ranking into `design-committed`), `implement` (`phase-entered` with `style`),
  `model-tiers` (required Style line, `style-missing` deviation), `review` (explicit
  `phase-entered` with `style`, canon lens, briefs from the ranking, `ranking` on the
  verdict).

## Data flow

`signals.py hotspots --json` → `ranking` → copied into `design-committed.ranking` and
`review-verdict.ranking` → `stats` reads `ranking.source`. Config Style section →
orchestrator → `phase-entered.style` (implement, review) → `stats`.

## API / contract changes

All additive. New optional keys: `phase-entered.style`, `phase-entered.signals` (now
validated), `design-committed.ranking`, `review-verdict.ranking`, signals JSON `ranking` and
`graph_note`, append JSON `deviation_seq`, stats JSON `trace`, `deviation_kinds` and
`totals.trace`. One new refusal: a `signals` block whose `source` is missing or unknown.
`status` and `position` are untouched. (Part 2 later extends the golden fixture with
`LOG_GOLDEN`; see Deviations.)

## Reference implementation

- Shape rule kinds: `map_enums` in `normalize_payload` (`journal.py`), added in 0.18.0.
- Same-transaction extra row: the implied `phase-entered` in `append_event` (ADR 0002).
- Workflow arg validation: `fileRisk` / `riskMap` in `review-workflow.js`.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/`. No hook edits. Python 3.9. Version bump in `plugin.json` and
  `marketplace.json` together. Release notes only in `CHANGELOG.md`.

---

# Build Plan

## Journal
- [x] T001 — shape rule kinds `objects` and `list_objects`; `style`, `signals`, `ranking` shapes; vocab prints them — `scripts/journal.py`, `tests/test_trace.py` — done when: tests fail first, then pass
- [x] T002 — auto `deviation` for a `route-and-map` entry without `signals` — `scripts/journal.py`, `tests/test_trace.py`, `tests/test_journal.py` (TestStatus seed) — done when: SC-002 tests pass
- [x] T003 — `stats` trace per stream and in totals, text section — `scripts/journal.py`, `tests/test_trace.py` — done when: SC-001, SC-005 tests pass

## Signals
- [x] T010 [P] — `ranking` in hotspots JSON; `graph_note` — `scripts/signals.py`, `scripts/_codegraph.py`, `tests/test_signals_trace.py` — done when: SC-003 tests pass

## Review canon
- [x] T020 [P] — `canon` lens and `styleSkills` in the review Workflow script; `Skill` on `code-reviewer` — `skills/review/references/review-workflow.js`, `agents/code-reviewer.md`, `tests/test_workflow_scripts.py` — done when: SC-004 tests pass

## Skills and docs
- [x] T030 — skill text: route-and-map, design, implement, model-tiers, review; config template; glossary — done when: SC-006 holds and `test_prose` passes
- [x] T031 — eval cases 74 (canon review) and 75 (graph past route) with graders; evals README rows — done when: SC-007 holds
- [x] T032 — release: 0.20.0 in `plugin.json` and `marketplace.json`, CHANGELOG entry, README journal table — done when: suite and `claude plugin validate shipgate` pass (SC-008)

## Part 2 — shipgate-hud 0.7.0 (HUD ADR 0007)
- [x] T040 — types (`Ranking`, `Trace`, `Position.trace`), `decodeLog` and the trace fold — `shipgate-hud/types/index.d.ts`, `hooks/journal.ts`, `hooks/position.ts`, `tests/journal.test.ts` — done when: decoder tests fail first, then pass
- [x] T041 — the refresh runs `log --stream --json`; the stored view's shape tag moves to v4 — `hooks/register.tsx`, `tests/register.test.ts` — done when: register tests pass
- [x] T042 — Review tab ranking line, Design tab ranking, canon tag on cards, Flow tab signals-missing line — `hooks/views.tsx`, `tests/views.test.tsx` — done when: view tests pass
- [x] T043 — golden contract: a `feature/golden-signals` stream and `log` answers; fixture regenerated — `shipgate/tests/test_hud_contract.py`, `shipgate-hud/tests/fixtures.journal.ts` — done when: the contract test passes and the HUD decodes the new golden answers
- [x] T044 — release: shipgate `>=0.20.0`, 0.7.0 in `plugin.json` and `marketplace.json`, CHANGELOG, README — done when: `claude plugin validate shipgate-hud` and `claude plugin test shipgate-hud` pass

## Traceability
- FR-001 → T030, T003 · FR-002 → T030, T003 · FR-003 → T020, T030 · FR-004 → T020
- FR-005 → T001, T030 · FR-006 → T002 · FR-007 → T010, T030 · FR-008 → T010
- FR-009 → T001, T030 · FR-010 → T001 · FR-011 → T003 · FR-012 → T031
- SC-001 → T003 · SC-002 → T002 · SC-003 → T010 · SC-004 → T020 · SC-005 → T003
- SC-006 → T020, T030 · SC-007 → T031 · SC-008 → T032

## Deviations & notes (filled during implementation)
- 2026-11-02 — T001/T010: `ranking.files` became a list of `{path, fix, churn, fan_in}`
  instead of an object keyed by path. Both `signals.py` and the journal print JSON with
  sorted keys, so an object lost the ranking order (caught by a T010 test). ADR 0013
  amended before acceptance.
- 2026-11-02 — T010: `graph_note` goes in the JSON only. The table output keeps the
  advisory-once rule of the code-graph PRD (FR-004), which its tests pin. The map is built
  from the JSON, so #10's "say it in the map" still holds.
- 2026-11-02 — The orchestrator implements directly: the lead assigned this session as the
  implementer, and it already holds the context of every file.

- 2026-11-02 — T002: `TestStatus.seed` in `tests/test_journal.py` entered route-and-map
  without signals, so the new deviation row moved its version from 12 to 13. The seed now
  carries `signals`, because the test is about status, not signals.
- 2026-11-02 — During implementation, a process outside this session staged 32 changed
  files (the index changed at 10:05:08; no shipgate hook, script or test stages files). The
  index was restored to its clean start state with `git restore --staged`; the working tree
  was not touched.

- 2026-11-02 — T001–T032: the Build Plan boxes were ticked before `verify-run` and
  `task-done` were recorded. The user caught it. The records were then written after a
  fresh full-suite pass (journal seq 1089–1097), and the late recording is journal
  deviation seq 1098 (`kind: record-late`).
- 2026-11-02 — `review-verdict` also takes `style` (`string_lists`), beyond the design
  above. A verdict that enters review by implication (a fix round, or a verdict with no
  explicit phase entry) can still say which style skills the review named; `stats` reads
  it with the phase entries.

- 2026-11-02 — Scope: part 2 of the batch folds shipgate-hud 0.7.0 into this stream (the
  lead's second brief). It reverses the PRD's "No HUD change" non-goal, which now says so.
  `position --json` does not print the new keys, and `journal.py` was frozen for running
  evals, so the HUD reads them from `log --stream --json` (HUD ADR 0007). The golden
  fixture gains `LOG_GOLDEN` and a `feature/golden-signals` stream; every golden seq moves
  up by 7.

## Review round 1 (2026-11-02, Workflow run wf_3a6dc71f-860)

29 found, 17 above the floor, 0 BLOCKER, 0 HIGH, no refuters spent (verify: high-only). All
fixed at the working tree unless listed under Rejected findings.
- F1 `scripts/journal.py:312` — `ReviewVerdictPayload` lacked `style`, `ranking`. Fixed:
  `SignalLabel`, `RankingFile`, `RankingPayload`.
- F2 `scripts/journal.py:186` — `vocab --shape` missed `ranking.unavailable`,
  `signals.unavailable`, `signals.repos`, `deviation.kind`. Fixed in the shapes.
- F3 `scripts/journal.py:3172` — the graph trace read the last event only, so a fix-round
  verdict without `ranking` hid round 1. Fixed: the last event that carries the block; the
  review skill tells a fix round to copy the ranking.
- F4 `scripts/journal.py:1547` — `seq` and `version` name two rows after an auto
  deviation. Fixed by documenting `version` as the stream head (what `--expect` needs).
- F5–F7 `scripts/journal.py:1194` — enum refusals printed `None` and Python reprs. Fixed:
  `null` and JSON for non-string values; strings read as before.
- F8 `skills/review/SKILL.md:37`, `skills/model-tiers/SKILL.md:108`, `README.md` — lines
  past the wrap width. Re-wrapped.
- F9 `skills/review/SKILL.md:73` — Step 1 heading said three lenses. Now "plus canon".
- F10–F11 `scripts/journal.py:232` — `style` items were unchecked. New rule kind
  `string_lists`; `stats` counts `named` only for a non-empty string.
- F12 worklog — the late task records were missing from Deviations. Added.
- F14 `scripts/journal.py:276` — `review-verdict.style` was not in the design. Documented
  above.
- F15 worklog — the Architecture text said the table prints `graph_note`. Fixed.
- F16 `scripts/journal.py:1904` — the deviation hint invited a backward phase entry.
  Reworded: re-append only while still in route-and-map.
- F17 `scripts/signals.py:1720` — two files with one 3-segment tail collapsed. Fixed: the
  later one keeps its full path.

## Review round 2 — shipgate-hud 0.7.0 (2026-11-02, Workflow run wf_6a8cfc43-dce)

Scope: the HUD diff only (two lenses: correctness, conventions+design). 21 found, 19 after
dedupe, 8 above the floor, 0 BLOCKER, 0 HIGH, no refuters spent. All 8 fixed at the working
tree:
- H1 `docs/prd/style-and-graph-trace.md:51` — the PRD said "No HUD change". Amended, and the
  scope change is a dated deviation.
- H2 `shipgate-hud/README.md:151` — "journal.py computes every fact" was no longer true.
  Qualified: the trace is the one place the HUD picks recorded values.
- H3 `shipgate-hud/hooks/journal.ts:805` — journal-valid rankings (no `files`, a missing
  label) decoded as Unreadable. Now decoded to journal.py's contract.
- H4 `shipgate-hud/hooks/register.tsx:691` — a cut `log` output failed the whole refresh.
  Now a cut trace: the position is drawn and the Flow and Review tabs say so.
- H5 `shipgate-hud/hooks/journal.ts:838` — READ FIRST could show an older verdict's ranking
  unmarked. Now marked `from an earlier verdict`.
- H6 `shipgate-hud/hooks/views.tsx:689` — the Design tab JSDoc was orphaned. Moved.
- H7 `shipgate-hud/hooks/journal.ts:797` — an ad-hoc decoder style. Rewritten with the
  file's `Decoder`, `fieldOf` and `Result`.
- H8 `shipgate-hud/CHANGELOG.md:24` — an example seq that carries no ranking. Now `seq N`.
- Below floor, fixed: an empty `unavailable` reason drew `()`.

## Rejected findings

- F13 `scripts/journal.py:1542` (auto deviation takes the caller's actor, so a `user`
  append counts a `user` row) — killed: ADR 0011 chooses the same actor on purpose, as ADR
  0002 does for the implied phase; the row is a fact about that append, and `auto: true`
  marks it for any reader that needs to tell them apart.
- Below floor, `.claude-plugin/plugin.json:3` (version bump without a user publish decision)
  — killed: the lead's brief orders the bump, and nothing is published (no commit, no push,
  no tag).
- Below floor, `review-workflow.js:178` (the canon reviewer loads the skill from the
  working tree under review) — killed: the canon is project config, like CLAUDE.md; a diff
  that edits the canon is visible in the same review.
- Below floor, `review-workflow.js:174` (style skill names are not escaped in prompts) —
  killed: the names come from the user's own config, the same trust level as the brief.
- Round 2, below floor: two snapshots (`position`, then `log`) may straddle an append —
  killed: the next refresh follows any append; a `source: none` ranking reads `· none` —
  kept, it is what was recorded; the Flow line stays after a later map recorded signals —
  kept, the deviation is history; below-floor canon findings carry no tag — killed, the
  return carries no lenses for them; the canon constant sits in views — style; the HUD
  tasks live in shipgate's worklog — the lead's brief puts both parts on one stream.
- Other below-floor items (two message formats, the trace's `route` label, kind strings
  without a constant, `--since` cutting a phase) — killed as style or speculative; no
  failure scenario.

