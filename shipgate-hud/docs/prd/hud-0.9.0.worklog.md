---
type: worklog
title: "Worklog: HUD 0.9.0 and shipgate 0.22.0"
created: 2026-11-04
updated: 2026-11-04
tags:
  - worklog
  - shipgate-hud
  - shipgate
status: reviewed
prd: "./hud-0.9.0.md"
issue: "#12, #13"
related:
  - ../adr/0009-the-verdict-only-round-reads-the-worklog.md
  - ../adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../../../shipgate/docs/adr/0013-signals-emits-the-ranking-the-journal-carries.md
  - ../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
---

# Worklog: HUD 0.9.0 and shipgate 0.22.0

# Design

## Approach

Minimal change on both sides. Every payload change is additive. journal.py computes the
label fold, as it computes the state fold (shipgate ADR 0009, 0014). The HUD parses the
worklog's review section for display, as it parses the Design sections (HUD ADR 0009).

## shipgate 0.22.0

- **`labels` (ADR 0014 amended).** `review-disposition` gains an optional `labels` map. A
  new rule kind, `string_maps`, refuses a value that is not an object and an entry that is
  not a non-empty string. The fold in `_position_dispositions` keeps the newest label per
  folded key (after `./` is dropped) and writes `label` (string or null) on every entry.
  The text form of `position` is unchanged but for the count line.
- **Golden contract.** One interim row of the `dispositions` stream gains `labels`, so the
  regenerated `shipgate-hud/tests/fixtures.journal.ts` carries a label and a null label.
- **Case fold (#13).** `review-workflow.js` gets `pathKey(file)`, `normalizePath` lower
  cased, for the dedupe maps and the `fileRisk` map and lookup. A merge never rewrites
  `file`, so the first finder's spelling stays.
- **Ranking exclude (ADR 0013 amended).** `DEFAULT_RANKING_EXCLUDES` in `signals.py`.
  `_CONFIG_KEYS` learns `ranking exclude`; an empty backticked value parses to `[]`.
  `Config` gains `ranking_exclude`, and `config.ranking_exclude` prints it. `cmd_hotspots`
  filters the rows it hands `ranking()` with `is_excluded`, each pattern with a leading
  `**/` dropped. `files`, `dirs` and the table are unchanged.
- **Sidecar version.** `_common.SIDECAR_VERSION = 1` and `sidecar_version_note(sidecar)`:
  a one-line warning for an integer `version` higher than 1, else None. `session_start.py`
  appends it to the context it already emits. `journal.py`'s `_load_sidecar` prints it once
  per run on stderr. `doctor` reports `sidecar.version` and `sidecar.stray_keys` (keys
  outside `version`, `db`, `artifact_homes`, `enforce`). `setup`'s update mode reads them,
  rewrites the sidecar without the stray keys and names them.
- **Skills.** `review`: the key is the finding's `<path>:<line|?>`, never an invented
  label; `labels` carries a human name. `setup`: the stray-key step.

## shipgate-hud 0.9.0

- **Decode.** `FoldedDisposition` gains `label: string | null`. An absent `label` is null
  (a 0.21.0 journal.py prints none); a present one must be a string or null. The read floor
  stays 0.21.0; the dependency becomes `>=0.22.0`.
- **Review notes (HUD ADR 0009).** `parseReviewNotes(worklog)` in `position.ts` gives
  `ReviewNote {location: {path, line} | null, text}` for each list item under a
  `Review round …` or `Rejected findings` heading. `Position.reviewNotes` holds them; the
  view's shape tag moves to `shipgate-hud.view-v6`.
- **Note match.** `noteFor(key, label, notes)` in `review.ts`: exact key, then a case-folded
  path tail on the same line, then the label as a whole word. The verdict-only round prints
  `<key> · <label>` and the state, then the note's first sentence dim and indented.
- **Case-folded tier (HUD ADR 0008 amended).** `namedKey` looks up a folded map after the
  exact and short-location lookups; the tail tiers fold both paths.
- **Sidecar warning.** `decodeSidecar` returns the homes and the version. A version higher
  than 1 is kept in a new `sidecarVersion` atom (`number | null`), and the pane draws one
  warning line above the tabs.
- **Reload.** A register test captures a board, resets the module's view of the session as
  a reload does (state kept), runs `session.start` again and finds the board drawn.

## CLAUDE.md / impact-map compliance

- Public repo: generic paths only (`src/widget/...`, `src/a.ts`).
- `hooks/`: `session_start.py` and `_common.py` change. The warning is computed only after
  the sidecar is found, so the no-sidecar path does no more work.
- Versions bump in lockstep: shipgate 0.22.0, shipgate-hud 0.9.0, each in its `plugin.json`
  and its `marketplace.json` entry.

# Build Plan

## shipgate 0.22.0

- [x] T001 — journal.py: `string_maps` rule kind, `labels` on `review-disposition`, `label`
  in the fold, `doctor` sidecar version and stray keys, the stderr warning; tests; golden
  contract row with a label and the fixture regenerated.
- [x] T002 — hooks: `SIDECAR_VERSION`, `sidecar_version_note`, the SessionStart line; tests.
- [x] T003 — review-workflow.js: case-folded dedupe and `fileRisk`; workflow tests.
- [x] T004 — signals.py: release files out of `ranking`, `Ranking exclude:`; config template
  and README; tests.
- [x] T005 — skills (`review` key format and labels, `setup` stray keys), CHANGELOG 0.22.0,
  `plugin.json` 0.22.0.

## shipgate-hud 0.9.0

- [x] T006 — journal.ts and types: `label` on `FoldedDisposition`, `decodeSidecar` with the
  version; tests.
- [x] T007 — review notes: `parseReviewNotes`, `noteFor`, the verdict-only round's text and
  label lines, view shape v6; tests in `views.test.tsx`, `position.test.ts`,
  `review.test.ts`.
- [x] T008 — `dispositionsFor` case-folded tier; tests in `review.test.ts`.
- [x] T009 — register.tsx: the sidecar warning atom and pane line; the reload test.
- [x] T010 — README, CHANGELOG 0.9.0, `plugin.json` 0.9.0 with `shipgate >=0.22.0`,
  both `marketplace.json` entries.

- [x] T011 — review round 1 fixes F1 to F20 (see *Review round 1*).

# Review round 1

Workflow run `wf_0e481424-19c`, three lenses (correctness, conventions+design,
simplicity+security). Counts: 34 found, 33 after dedupe, 17 candidates, 17 survivors, 0
killed, 0 refuters (no BLOCKER or HIGH), 16 below the floor. Verdict: not ready.

To fix in round 1:
- F1 MEDIUM `shipgate/hooks/_common.py:32` — `SIDECAR_KEYS` leaves out `ledger`, a key journal.py reads. So `doctor` calls it stray and setup's update mode would drop it.
- F2 MEDIUM `shipgate/README.md:168` — the README does not name `labels`, the folded `label`, or the doctor's `version` and `stray_keys`.
- F3 MEDIUM `shipgate-hud/tests/register.test.ts:1970` — the reload test cannot reset module state. SC-002 and HUD ADR 0009 must state the claim the test proves.
- F4 MEDIUM `shipgate-hud/docs/prd/hud-0.9.0.worklog.md:109` — the deviations from the Design are not logged.
- F5 MEDIUM `shipgate/skills/review/SKILL.md:48` — the review skill does not state the worklog grammar the HUD parses.
- F6 MEDIUM `shipgate-hud/hooks/position.ts:217` — a review note keeps its control characters, and the pane draws them.
- F7 LOW `shipgate-hud/hooks/position.ts:132` — a nested review heading resets the section level. A later sibling heading then closes the outer section early.
- F8 LOW `shipgate/hooks/session_start.py:289` — on the status-failure path the version warning reaches the context twice.
- F9 LOW `shipgate-hud/hooks/position.ts:139` — the fence toggle ignores the marker type.
- F10 LOW `shipgate/scripts/signals.py:1517` — one `--help` epilog line is 102 characters wide.
- F11 LOW `shipgate-hud/hooks/position.ts:181` — the same control-character gap as F6, for `body`.
- F12 LOW `shipgate/skills/setup/SKILL.md:148` — "Step 3 template" and "Step 4 drops them" are ambiguous inside Step 4.
- F13 LOW `shipgate-hud/docs/prd/hud-0.9.0.worklog.md:1` — the frontmatter has no `status` and no `related`.
- F14 LOW `shipgate-hud/hooks/position.ts:180` — the separator strip leaves a leading comma or period in a sentence.
- F15 LOW `shipgate-hud/hooks/register.tsx:1022` — `sidecarVersion` is not updated when journal.py is not found.
- F16 LOW `shipgate-hud/hooks/position.ts:155` — a second parser of the `<path>:<line|?>` grammar beside `parseKey`.
- F17 LOW `shipgate-hud/hooks/views.tsx:1123` — the key drawn beside the clean label keeps its control characters.
- F18 LOW (promoted from below the floor) `shipgate-hud/hooks/journal.ts:760` — `decodeCleanText` copies `stripControl` from review.ts.
- F19 LOW (promoted) `shipgate/README.md:247` — a re-wrap left a short broken line in the ranking paragraph.

- F20 LOW (raised by the user) `shipgate-hud/hooks/review.ts:465` — `isReviewLaunch` misses a `Workflow` launch by `scriptPath`, so the board has no run id and its header reads `run ?`.

## Rejected findings

- `shipgate-hud/hooks/review.ts:465` (LOW 55): `noteFor` takes the first note in worklog order. That is the round that first described the finding, which is the text a reader needs (HUD ADR 0009).
- `shipgate-hud/hooks/journal.ts:964` (LOW 50): a `"version": 2.0` sidecar warns in the HUD only. setup writes an integer, so a float version is hand-made and out of scope.
- `shipgate-hud/hooks/register.tsx:767` (LOW 30): `sidecarVersion` has no shape tag. A plain `number | null` atom needs none, as `tab` needs none.
- `shipgate-hud/hooks/register.tsx:314` (LOW 35): the same claim as the line above.
- `shipgate-hud/hooks/review.ts:373` (LOW 55): `fold` names case folding next to the disposition fold. The helper is local and documented, so this is naming taste.
- `shipgate-hud/hooks/position.ts:169` (LOW 50): "note" has three meanings. The type is `ReviewNote` everywhere it is used.
- `shipgate-hud/hooks/review.ts:496` (LOW 40): `hasWholeWord` builds a RegExp per note. A review section holds tens of notes, and a draw is rare.
- `shipgate/scripts/signals.py:525` (LOW 40): the mixed `**/` prefixes are deliberate. `marketplace.json` lives at the root only.
- `shipgate/skills/design/references/worklog-template.md:98` (LOW 40): the template's placeholder bullet parses as a note. Only a label that names its words could match it.
- `shipgate/scripts/journal.py:482` (LOW 30): `doctor` prints the raw `version` and the stray key names. They are JSON values from the project's own sidecar, which the model reads anyway.

# Review round 2

The orchestrator's pass over the fix diff, alone: each fix is local and carries its own test,
so one reader of the changed code is enough. Each finding is closed on the line or the test
named here.

- F1 `shipgate/hooks/_common.py:33` — `SIDECAR_KEYS` names `ledger`; `test_a_ledger_key_is_no_stray_key` pins it, and setup's sidecar shape names the key.
- F2 `shipgate/README.md:168` — the README names `labels`, the folded `label`, the sidecar version check, `version` and `stray_keys`.
- F3 `shipgate-hud/tests/register.test.ts:1970` — SC-002 and HUD ADR 0009 state what the reload test proves.
- F4 `shipgate-hud/docs/prd/hud-0.9.0.worklog.md:109` — the deviations are logged below.
- F5 `shipgate/skills/review/SKILL.md:48` — the skill states the worklog grammar the HUD parses.
- F6 `shipgate-hud/hooks/position.ts:217` — `noteOf` strips control characters first; the F6/F11 test pins it.
- F7 `shipgate-hud/hooks/position.ts:132` — a nested review heading keeps the outer level; the F7 test pins it.
- F8 `shipgate/hooks/session_start.py:289` — the failure path drops journal.py's copy of the note; `test_the_note_appears_once_and_the_real_error_stays` pins it.
- F9 `shipgate-hud/hooks/position.ts:139` — a fence closes on its own marker only; the F9 test pins it.
- F10 `shipgate/scripts/signals.py:1517` — the epilog is wrapped under 80 columns.
- F11 `shipgate-hud/hooks/position.ts:181` — closed with F6.
- F12 `shipgate/skills/setup/SKILL.md:148` — Step 4 names "the sidecar shape in Step 3 — Write (item 3)" and "item 4 below".
- F13 `shipgate-hud/docs/prd/hud-0.9.0.worklog.md:1` — the frontmatter carries `status` and `related`.
- F14 `shipgate-hud/hooks/position.ts:180` — leading `,` `;` `.` go, and a sentence with no letter or digit is empty; the F14 test pins it.
- F15 `shipgate-hud/hooks/register.tsx:1022` — the sidecar is read before the journal.py lookup; the F15 test pins it.
- F16 `shipgate-hud/hooks/position.ts:155` — `noteOf` uses `parseLocation` from review.ts, the one reader of the grammar.
- F17 `shipgate-hud/hooks/views.tsx:1123` — the drawn key loses its control characters; the F17 test pins it.
- F18 `shipgate-hud/hooks/journal.ts:760` — one `stripControl`, in json.ts.
- F19 `shipgate/README.md:247` — the ranking paragraph is wrapped again.
- F20 `shipgate-hud/hooks/review.ts:465` — a `scriptPath` launch of `review-workflow.js` is noted, so the board carries its run id; the F20 review and register tests pin it.

No new regression. Final gate: shipgate suite 963 OK (skipped=2), `claude plugin test
shipgate-hud` 958 pass 0 fail, both validate runs passed, `tsc` exit 0, the four changed
scripts compile under Python 3.9.6. Verdict: ready.

# Deviations & notes

- 2026-11-04 — `ReviewNote` is `{location, sentence, body}`, not `{location, text}`.
  `sentence` is the first sentence after the location, drawn under the key. `body` is the
  whole item, which the label tier searches.
- 2026-11-04 — `decodeSidecarHomes` is unchanged. A separate pure `sidecarVersionOf` reads
  the version, and `readSidecar` in register.tsx reads the file once for both.
- 2026-11-04 — `parseReviewNotes` ends an item at a blank line, an unindented line, a fence
  line or any heading. A nested list item is a note of its own.
- 2026-11-04 — the session_start note also reaches the journal-unreachable context, so all
  three emit paths of the SessionStart hook carry it.
- 2026-11-04 — `doctor` prints the sidecar version and stray keys only when a sidecar is
  found.
- 2026-11-04 — the reload test (T009) keeps module state as it is, because the test kit
  cannot reload the module. SC-002 and HUD ADR 0009 now state that claim (F3).
- 2026-11-04 — `marketplace.json` was bumped by the orchestrator, not by the T010 worker.
