---
type: prd
title: "PRD: shipgate 0.24.0 and shipgate-hud 0.11.0 — re-export edges in the graph, the grader's last-call rule, a review board that survives /clear"
created: 2026-11-07
updated: 2026-11-07
tags:
  - prd
  - shipgate
  - shipgate-hud
status: clarified
issue: "#7 (shipgate); the review board after /clear, /resume, /branch (no issue yet)"
worklog: "./shipgate-0.24.0.worklog.md"
related:
  - ../adr/0007-codegraph-as-detected-structure-provider.md
  - ../adr/0016-the-signal-grader-runs-outside-the-harness.md
  - ../adr/0017-re-export-edges-are-added-beside-the-graph.md
  - ../../../shipgate-hud/docs/adr/0009-the-verdict-only-round-reads-the-worklog.md
  - ../../../shipgate-hud/docs/adr/0011-the-review-board-is-kept-in-the-store.md
---

# PRD: shipgate 0.24.0 and shipgate-hud 0.11.0

> The code graph reaches a file behind two barrel re-exports. The signal grader scores the
> last `signals.py` call that listed files. The HUD's review board comes back after `/clear`,
> `/resume` and `/branch`.

## Problem

1. **The graph misses a file behind two barrels (#7).** codegraph 1.6.2 records no edge of
   any kind for `export * from "<spec>"`. In the index of eval case 72, 12 files hold such a
   line and none of them has a cross-file out edge. A barrel file holds one `file` node and
   nothing else. So the barrels are not importers in the graph, and a file that reaches the
   hub only through a bare workspace-package import of a second barrel is lost. Offline,
   `signal_grader.py fixture --arm graph` gives `blast.files` recall 0.95 (56 of 59). The
   missed files are the two barrels and the one file behind the second barrel. On the live
   eval the only grader that fails on either arm is the one for that file: 4 of 6 with-arm
   runs miss it.
2. **The grader can score the wrong call.** `signal_grader.py trace` takes the last
   `signals.py` call whose result holds a `blast` object. One live run scored 0.00 because
   the agent's last call carried a `blast` object with no `files` list.
3. **The review board is gone after `/clear`, `/resume` and `/branch`.** The board lives in
   the `review` atom of `$.state`, which those commands reset. The user then sees the
   verdict-only round instead of the board with its cards and Accept / Kill buttons, although
   the stream is the same. HUD ADR 0009 recorded this limit as the engine's.

## Goals & non-goals

**Goals**
- On the graph arm, a barrel is an importer of every file it re-exports, and a file that
  imports a workspace package by its bare name is an importer of that package's entry file.
  Offline on case 72, `blast.files` precision and recall both reach 1.00.
- The grader scores the last call whose `blast.files` is a list, and says so.
- The maintainer has a minimal repro of the missing codegraph edge to report upstream.
- The HUD saves a stream's review board when it is set, and restores it on the re-detection
  that already runs after `/clear`, `/resume`, `/branch` and at session start.

**Non-goals**
- No change to the regex scanner. It stays frozen (ADR 0007 §1), so the regex arm's eval
  numbers stay comparable.
- No eval run in this change. The lead runs evals after merge.
- No upstream report filed by this change. The worklog holds the repro; the maintainer files
  it.
- No new key in the HUD's golden contract with journal.py. The HUD's dependency stays
  shipgate `>=0.23.0`.
- No edit to issue #7's text.

## Functional requirements

**shipgate 0.24.0 — the graph (#7)**
- **FR-001** — On the graph arm, for every indexed TypeScript or JavaScript file of the
  graph, each `export * from "<spec>"`, `export * as <name> from "<spec>"`,
  `export { … } from "<spec>"`, `export type { … } from "<spec>"`,
  `export type * from "<spec>"` and `export type * as <name> from "<spec>"` line whose
  `<spec>` resolves to a file in the graph adds the edge `file -> target`. Relative specifiers
  resolve with the rules the regex scanner uses: extensions, `.js` to `.ts` swaps and
  `index` files.
- **FR-002** — On the graph arm, an `import … from "<name>"` or `require("<name>")` whose
  `<name>` is the bare name of a workspace package (the root `package.json` `workspaces`
  globs, each package's `name`) adds the edge `file -> entry`, where `entry` is the
  package's `exports["."]` target, else its `main`, else its `index` file. A subpath
  import (`<name>/<path>`) adds nothing: codegraph resolves those.
- **FR-003** — The pass reads each file once, reads no file over 1 MiB (the regex scanner's
  cap), never follows a symlink and never leaves the repository. A file it cannot read adds
  no edge and raises no error.
- **FR-004** — `structure.source` stays `graph`. The `structure.graph` block gains one
  additive integer, `reexport_edges`: the number of edges the pass added. No note is
  printed for the pass.
- **FR-005** — The shim's test fixture holds a two-hop barrel chain. The suite proves that
  the file behind two barrels is reached and that the barrels themselves are importers.

**shipgate 0.24.0 — the grader**
- **FR-006** — `signal_grader.py trace` and `results` score the last `signals.py` call
  whose result holds a `blast` object with a `files` list. A call whose `blast.files` is
  `null` or absent is skipped. The docstring and the evals README say so.

**shipgate 0.24.0 — the record**
- **FR-007** — The worklog holds the codegraph finding (the index query and its counts),
  the offline before and after numbers of case 72, and a minimal three-file repro of the
  missing `export *` edge with generic names, plus the bare workspace-import case.
- **FR-008** — The changelog entry names #7 and carries the before and after numbers. The
  evals README's offline table shows the new case 72 graph-arm row.

**shipgate-hud 0.11.0 — the review board**
- **FR-009** — When a board of a stream is set or marked, the HUD saves that stream's
  boards and their marks under one `$.store` key built from the project root and the
  stream. The stored value carries a shape tag with a version.
- **FR-010** — The HUD keeps the newest 20 saved boards, by their save time, and deletes
  the rest.
- **FR-011** — On the re-detection after `/clear`, `/resume` and `/branch`
  (`classic.SessionStart` with source `clear`, `resume` or `fork`, the lazy detection, and
  `session.start`): when the detected position's stream has a saved board and the `review`
  atom holds no board of that stream, the HUD loads it into the atom before the detection
  returns. A board of another stream is not loaded.
- **FR-012** — A saved board of a stream whose position says the flow is completed
  (`lifecycle: terminal`) is not restored, and the HUD deletes it.
- **FR-013** — A store that cannot be read, or a value whose shape the HUD does not know,
  is ignored, and the HUD draws as today. A board of another shape is never deleted.
- **FR-014** — The tick overrides stay in `$.state` only. The HUD saves boards and marks.
- **FR-015** — HUD ADR 0009 is amended where it says the board is session-only. The README's
  Review tab section says what the HUD saves, where, and the limit of 20. The changelog
  carries the entry.

**Releases**
- **FR-016** — shipgate 0.24.0 and shipgate-hud 0.11.0 in each `plugin.json` and in
  `marketplace.json`. The HUD's dependency stays `>=0.23.0`.

## Success criteria

- **SC-001** — `signal_grader.py fixture <case 72> --arm graph` prints `blast.files`
  precision 1.00 and recall 1.00 (59 of 59), `source graph`.
- **SC-002** — A shim test with a two-hop barrel chain proves, on the graph arm, that the
  file behind both barrels and both barrels are in `blast.files` of the hub.
- **SC-003** — A grader test proves that a trailing call with `blast.files: null` is
  skipped and the earlier call with a list is scored.
- **SC-004** — HUD tests prove: a save on capture and on a mark; a restore after a `$.state`
  reset and `session.start` for the same stream; no restore for another stream; no restore
  and a delete for a completed stream; the newest-20 cut; an unreadable store draws as
  today.
- **SC-005** — Every check is green after the last edit: shipgate's unit tests,
  `claude plugin validate` for both plugins, `claude plugin test shipgate-hud`, `tsc`, the
  Python 3.9 syntax check, and the private-data grep over the diff.

## Constraints & assumptions

- Public repo: nothing employer- or customer-specific (root `CLAUDE.md`).
- shipgate's scripts stay Python 3.9 compatible.
- `_codegraph.py` holds codegraph calls only (ADR 0007 §1); the pass lives beside the
  regex scanner in `signals.py`.
- The engine's store holds 4 MiB of JSON in all. A fixture round is about 3 KB; a real round
  with 20 findings is about 10 KB; a stream keeps 5 rounds. Twenty streams stay under about
  1 MiB.

## Assumptions (executive)

- Re-export edges alone reach 58 of 59 on case 72; the file behind the second barrel
  imports that barrel by its bare package name, and codegraph records no edge to the entry
  file → the pass also adds `file -> entry` edges for bare workspace-package imports, on
  the graph arm only — the brief's bar is recall 1.00 and that file is the one it names;
  the regex scanner stays frozen so the regex arm's numbers stay comparable (ADR 0017).
- Where the pass lives → `signals.py`, called from `graph_structure` after
  `read_file_graph` — `_codegraph.py` keeps codegraph knowledge only (ADR 0007 §1).
- Size cap → 1 MiB per file, the regex scanner's `MAX_SCAN_BYTES` — one cap, already
  measured.
- A note for the pass → none; one additive count `structure.graph.reexport_edges` instead —
  a count is checkable in a trace and in a test, a note is prose.
- Grader rule → the last call whose `blast.files` is a list — the only call that can be
  scored.
- Store key → `review-board:<project root>:<stream>`, value tagged
  `shipgate-hud.review-board-v1` with `savedAt` — one key per board, so a delete is one
  call and the cut needs no index.
- N → 20 — twenty streams of five rounds stay near 1 MiB of the 4 MiB store (HUD ADR
  0011).
- Restore point → inside `detectAndRefresh`, after a `Bound` refresh, only when the atom
  holds no board of that stream — a live session's boards are never overwritten.
- Completed → `position.lifecycle === 'terminal'`; `dormant` restores — a dormant flow can
  resume.
- Ticks → stay session-only — the brief names boards and marks.
- The existing test that pins "a reset drops the board" → changes to pin the restore.

## Open questions

None.
