---
type: worklog
title: "Worklog: shipgate-hud slice 1 — band + Flow / Plan / Design pane"
created: 2026-10-06
updated: 2026-10-06
tags:
  - worklog
  - shipgate-hud
status: implementing
prd: "./hud.md"
related:
  - "../adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
---

# Worklog: shipgate-hud slice 1 — band + Flow / Plan / Design pane

> Design + build plan companion to `./hud.md`.

---

# Design

## Approach

Pragmatic-balance, one philosophy only: the solution space is narrow once ADR 0001 fixes
the plugin boundary and the data source. The module is split into a pure core (parse →
model → tree) and a thin shell of hooks, so the tests exercise the core without a process
or a file system.

## Architecture

```
shipgate-hud/
  .claude-plugin/plugin.json      name, version, types, userConfig.journalScript
  hooks/hooks.json                { "modules": ["./register.tsx"] }
  hooks/register.tsx              the hooks (session.start, command.run, tool.call,
                                  classic.SessionStart, clock, ui.render ×2) and the
                                  side effects: locate journal.py, run it, read artifacts
  hooks/position.ts               pure: status JSON + log JSON + worklog text → Position
  hooks/views.tsx                 pure: (elements, Position, ui state) → trees
  types/index.d.ts                PluginState contract: position, tab, lastError, isJournaled
  tests/position.test.ts          parsing and derivations
  tests/views.test.tsx            band + pane mounted on terminal and desktop
  README.md, CHANGELOG.md
```

- **register.tsx** owns side effects only: it registers `/hud`, opens the pane, schedules
  the refresh, and writes the `position` atom. Every `ui.render` hook reads atoms and calls
  a view function.
- **position.ts** is where the knowledge of shipgate's shapes lives: the `status --json`
  feature record, the `log --json` events (refs → worklog and ADR paths; `task-done`
  payloads), the worklog's Build Plan lines (`- [x] T001 — title — …`) and its `# Design`
  section, an ADR's frontmatter `title` and `status`.
- **views.tsx**: `bandOf`, `paneOf` with `timelineOf`, `flowTab`, `planTab`, `designTab`.
  Each takes the surface's element table, so the same function draws on terminal and
  desktop; the only surface branch is width.

## Data flow

```
trigger ──► refresh($) ──► process.run(journal.py status --json --branch=B)
                        ──► process.run(journal.py log --stream S --json)
                        ──► fs.read(worklog), fs.read(each ADR)
                        ──► toPosition(...)  ──► update(position atom) ──► redraw
```

The refresh runs `git rev-parse --abbrev-ref HEAD` first and shows only the stream whose
`branch_match` is true; no match → no position. The stream name for `log --stream` is the
feature record's `stream` (the journal folds a `feature/` prefix out of `feature`). Artifact
homes are shipgate's defaults overlaid key by key with the sidecar's `artifact_homes`, read on
every refresh, and matched the way shipgate matches them (`fnmatch`: `*` crosses `/`, anchored,
then a second try under one more `*` segment) against the written path made relative to the
session directory. When the events name no worklog, the fallback is the newest worklog in the
worklog home named for the stream's slug (`<slug>.worklog.md`, or `<slug>-…` / `<slug>.…`), else
none; the fallback lists a literal directory or one with `*` as its first segment only. Refs from
events are read only when relative, in-project and free of `..`.

Triggers: `session.start` (skipped when the session has no surface); `tool.call` on Bash
whose command mentions `journal.py` and `append`, after `next` resolves; `tool.call` on
Write/Edit whose path matches an artifact-home glob, after `next`; `classic.SessionStart`
with source clear/resume/fork; `$.clock.every(60_000)`. A request during a refresh queues one
trailing refresh and every caller awaits the last run.

Veto: a Button in the Flow tab (only for `raised_by: orchestrator` + `mode: executive`)
calls `$.prompt.submit({ text })` with a fixed sentence naming the stream, gate and
timestamp — never the journal's question or decision text, and not as the user's own words.
Nothing is written to the journal by the mod.

## Data model

```ts
type Position = {
  stream: string; phase: Phase; phaseEnteredAt: string | null; version: number
  phases: Record<Phase, 'done' | 'current' | 'todo'>
  decisions: Decision[]           // newest first
  tasks: Task[]                   // worklog order
  lastVerify: { outcome: string; taskIds: string[]; at: string } | null
  design: { adrs: Adr[]; markdown: string }
  worklogPath: string | null
}
type Decision = { seq: number; gate: string; question: string; decision: string;
                  raisedBy: string; mode: string | null; at: string }
type Task = { id: string; title: string; tickedInWorklog: boolean; doneInJournal: boolean;
              lastVerify: { outcome: string; at: string } | null }   // last verify-run, pass or fail
type Adr = { path: string; title: string; status: string }
```

`phases`: every phase before the current one is `done`; the current one is `current`;
the rest `todo`. Journaled `phase-entered` events refine it (a phase entered earlier then
left is `done` even if later than the current one in flow order — backward transitions).

## Locating journal.py

In order: `userConfig.journalScript` when set; for the plugin root and, when it is a link,
where it lands: `<root>/../shipgate/scripts/journal.py` (marketplace checkout) and
`<root>/../../shipgate/<newest>/scripts/journal.py` (plugin cache layout
`cache/<marketplace>/<plugin>/<version>/`); then `<config dir>/plugins/cache/<any
marketplace>/shipgate/<newest>/scripts/journal.py` for `$CLAUDE_CONFIG_DIR` and `~/.claude`.
Newest = numeric segment compare, tags and shas last. Missing → `lastError` atom set, band
draws nothing, pane shows the one line.

- 2026-10-07 — live check: loaded through the dev-mods symlink the root had no `../shipgate`, so the
  pane showed "cannot find journal.py"; fixed by resolving the root through the link and by the
  config-directory cache fallback (both tested).

## Reference implementation

The bundled `pane.tsx` / `band.tsx` examples of the `plugin-authoring` skill — the atom /
read / update pattern, the `AbovePrompt` quiet path (`next(e)` when there is nothing to
show), the `requestId` guard on `Pane`.

## CLAUDE.md / impact-map compliance

- New plugin directory; `.claude-plugin/marketplace.json` gains one entry. Nothing under
  `shipgate/` changes.
- Hooks run on every user's machine: the sidecar existence check is the first thing every
  side-effecting hook does; a project without it costs one `fs.exists`.
- Public repo: test fixtures use `feat/example-stream`, `T001 — add the widget` style names.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).

## Setup / foundations
- [x] T001 — plugin skeleton: `plugin.json` (types, userConfig), `hooks.json`, `types/index.d.ts`, tsconfig — file(s): `shipgate-hud/.claude-plugin/plugin.json`, `shipgate-hud/hooks/hooks.json`, `shipgate-hud/types/index.d.ts` — done when: `claude plugin validate shipgate-hud` passes with an empty `register`
- [x] T002 — marketplace entry for `shipgate-hud` 0.1.0 — file(s): `.claude-plugin/marketplace.json` — done when: `claude plugin validate .claude-plugin/marketplace.json` passes

## Core
- [x] T010 — `position.ts`: parse status / log / worklog / ADR into `Position` — file(s): `shipgate-hud/hooks/position.ts` — done when: T011 passes
- [x] T011 — tests for T010: feature record → phase timeline; decisions newest first with raisedBy; Build Plan lines → tasks with journal cross-check and debt flag; worklog `# Design` extraction; ADR frontmatter — file(s): `shipgate-hud/tests/position.test.ts` — done when: tests fail first, then pass
- [x] T012 — `views.tsx`: `bandOf`, `paneOf` (timeline, Flow, Plan, Design tabs) — file(s): `shipgate-hud/hooks/views.tsx` — done when: T013 passes
- [x] T013 — tests for T012: band text on terminal + desktop; pane default tab by phase; veto button present only for orchestrator decisions; debt badge; mounted via `$.ui.mount` with atoms seeded — file(s): `shipgate-hud/tests/views.test.tsx` — done when: tests fail first, then pass

## Shell
- [x] T020 — `register.tsx`: sidecar guard, locate journal.py, refresh runner, triggers, `/hud`, pane open, render hooks — file(s): `shipgate-hud/hooks/register.tsx` — done when: `claude plugin validate` lists exactly the designed events/calls; T021 passes
- [x] T021 — tests for T020: no sidecar → band passes through and no `process.run`; sidecar present → one status + one log run on session.start; a Bash `journal.py append` call triggers a refresh — file(s): `shipgate-hud/tests/register.test.ts` — done when: tests fail first, then pass

## Polish
- [x] T030 — README + CHANGELOG for shipgate-hud; root README mention — file(s): `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`, `README.md` — done when: install line and the no-journal behaviour are documented
- [x] T031 — live check: load with `--plugin-dir` in this repo, band shows `feat/shipgate-hud`, pane shows this stream's decisions and plan (SC-003) — done when: observed, with the refusal lines (if any) fixed

## Traceability
- FR-001 → T012, T013
- FR-002 → T020, T021
- FR-003 → T020
- FR-004 → T010, T011, T012
- FR-005 → T010, T012, T013
- FR-006 → T010, T011, T012, T013
- FR-007 → T010, T012
- FR-008 → T012, T013
- FR-009 → T020, T021
- FR-010 → T020, T021
- FR-011 → T002 (review: `git diff --stat -- shipgate/` empty)
- SC-001 → T001, T020
- SC-002 → T011, T013, T021
- SC-003 → T031
- SC-004 → T021

## Deviations & notes (filled during implementation)
- 2026-10-07 — `locate.ts` folded into `register.tsx`: `claude plugin validate` follows `$` only into
  functions declared at the top of the same file, never across an import. `position.ts` and `views.tsx`
  stay separate because they never receive `$`.
- 2026-10-07 — the orchestrator typed the mod itself (no worker dispatch): one small module against a
  new API whose declarations had been read in this context.
- 2026-10-07 — `Text` takes no `key`; tests find text by content and keep keys on `Box`, `Button`, `Markdown`.
- 2026-10-07 — the refresh after a journal append is awaited inside the `tool.call` hook (not fire-and-forget)
  so the tool result lands after the pane moved and nothing runs past the test's end.
- 2026-10-07 — `session.start` keeps awaiting the first refresh (≈300 ms) so the pane opens populated; a
  session with no surface skips it entirely.

## Review round 1 (2026-10-07)

Three-lens review workflow (`wf_98aea162-62a`, opus finders, high-only refuters): 34 raw → 31 deduped →
18 above the floor, 0 killed by refuters (both HIGHs held 0/2), 13 below floor. Full `/security-review`
sub-task: no finding ≥ 0.7; one 0.5 candidate (Veto `asUser`) adopted. Fixed at this round:

- F1 HIGH `register.tsx` — `log --stream` got the folded feature slug, not the stream name (`feature/x`
  streams returned no events) → uses `feature.stream`; test with a `feature/`-prefixed fixture.
- F2 HIGH `README.md` — install line not in the repo's form → `/plugin marketplace add` + `install @pandora`.
- F3 MEDIUM `marketplace.json` — re-serialised with `\u` escapes, unrelated bpmn line churned → rewritten
  from `main` with `ensure_ascii=False`; the diff is the added block only.
- F4 MEDIUM `views.tsx` — Veto on every orchestrator-raised decision, including `mode: ask` ones the user
  answered → `isVetoable` = orchestrator **and** executive, applied to the band count too; FR-005 + README.
- F5 MEDIUM `register.tsx` — fallback to an unrelated stream when none matched the branch → matched only.
- F6/F10/F11 MEDIUM — hardcoded `docs/(prd|adr)` trigger and a newest-mtime worklog fallback that could pick
  another feature's worklog → homes from the sidecar's `artifact_homes` globs; fallback tied to the stream slug.
- F7 MEDIUM (+ security candidate) — Veto submitted journal text `asUser` → fixed sentence with identifiers,
  no `asUser`.
- F8/F9 MEDIUM docs — lookup order and "one Python run" wording in ADR/FR-009/FR-010 → match the code.
- F12 MEDIUM — a refresh during a refresh was dropped → one trailing refresh, all callers await the last run.
- F16 LOW — the same marketplace.json churn seen through the simplicity lens; closed by F3.
- F13/F14/F15/F17/F18 LOW — `detect` reuses `exists`, header comment corrected; numeric version compare;
  worklog Architecture/Data model updated; last verify per task wins (fail drawn `✗`); refs limited to safe
  relative paths. Below floor adopted: no process runs when the session has no surface; `isStdoutTruncated`
  refused; tests for the Write/Edit trigger and the `/clear` re-detect.

## Review round 2 (2026-10-07)

Scoped re-review of the fix round, one reviewer (opus): every F1–F18 fix CONFIRMED in the code; validate,
tsc and 26/26 tests re-run by the reviewer. Suggested verdict: ready. Its findings, fixed in this round:

- M1 — `readHomes` replaced shipgate's defaults wholesale → merged key by key over `DEFAULT_ARTIFACT_HOMES`
  as `journal.py artifact_homes()` does.
- M2 — glob rules differed from shipgate's `fnmatch` and an absolute Write path matched at any depth →
  `globToRegExp` now follows `fnmatch` (`*` crosses `/`, `?`, `[...]`, anchored), `matchesHome` adds the
  `*/` second try, and the path is made relative to the session directory first (outside → no match).
- M3 — a `-p` resume could run processes → `hasSurface` set at `session.start` gates the classic hook too.
- L1/L11 — FR-001 and FR-005 wording; L2 — slug = last segment, stem match `<slug>.worklog.md` / `<slug>-…`;
  L3 — numeric versions sort before tags/shas; L5 — a failing refresh writes `lastError`, never rejects;
  L7 — veto prompt names "decision N of M", omits an empty timestamp; L8 — redundant await removed;
  L9 — vacuous assertion fixed; L10 — tests added for coalescing, the worklog fallback, an absolute
  and an outside Write path, the veto text, and a resume without a surface; L12 — F16 accounted for.
- Not changed: L4 (deeper wildcards in the fallback scan — documented as a limit), L6 (hook budget on a
  waiting `/hud` — unverified, the engine stops the clock inside `$` calls), L13 (predates the round; no
  `key` on `Text` remains), L14/L15 (loose `JOURNAL_APPEND` and refresh after an errored tool call — one
  extra refresh at worst).

## User feedback round (2026-10-07, in-session)

The pane rendered but read as a blob, and the active tab was not distinguishable. Reworked
`views.tsx` for scanning: the active tab and the current phase are drawn inverted, a rule under
the tab row; the Plan tab has a progress bar, a one-line-per-task layout with fixed columns
(glyph, id, truncated title, verify outcome + time) under dim Build Plan section headers;
the Flow tab draws each decision as a three-line card (gate · time · who, `Q` and `A` truncated
to the width) with the gate coloured; the Design tab lists ADRs as one line each and folds the
worklog's Design section into one collapsible `##` section at a time (`designOpen` atom, the
first open by default), with hard-wrapped prose reflowed so the pane wraps it to its own width.
Backticks are stripped from task titles. Phases entered before but later in flow order than the
current one draw dim (revisited, not pending).

## Rejected findings
- below-floor `position.ts:152` "decisions recorded with `chosen` show an empty line" — killed: `journal.py
  append` normalizes the `chosen` → `decision` alias on write, so stored rows always carry `decision`.
- below-floor `register.tsx:225` "a committed sidecar makes session.start run git + journal.py in an untrusted
  clone" — killed: the script path never comes from the repo (option, plugin folder, plugin cache only), and
  shipgate's own SessionStart hook already runs the same CLI on the same trigger.
- below-floor `register.tsx:226` "session.start awaits the refresh" — kept as designed (≈300 ms, pane opens
  populated); the no-surface case is now skipped.
- below-floor `views.tsx:24` "PANE_ID lives in the pure module" — style only; the views need the id for tests.
