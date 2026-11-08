---
type: worklog
title: "Worklog: shipgate 0.24.0 and shipgate-hud 0.11.0"
created: 2026-11-07
updated: 2026-11-07
tags:
  - worklog
  - shipgate
  - shipgate-hud
status: reviewed
prd: "./shipgate-0.24.0.md"
issue: "#7; the review board after /clear, /resume, /branch"
related:
  - ../adr/0007-codegraph-as-detected-structure-provider.md
  - ../adr/0016-the-signal-grader-runs-outside-the-harness.md
  - ../adr/0017-re-export-edges-are-added-beside-the-graph.md
  - ../../../shipgate-hud/docs/adr/0009-the-verdict-only-round-reads-the-worklog.md
  - ../../../shipgate-hud/docs/adr/0011-the-review-board-is-kept-in-the-store.md
---

# Worklog: shipgate 0.24.0 and shipgate-hud 0.11.0

# Design

## Approach

Minimal change, designed inline: the brief fixes the shape of both items, and each has one
real fork, recorded in ADR 0017 (shipgate) and HUD ADR 0011. The re-export pass is a
function in `signals.py` beside the regex scanner, run after the index read, and the
`FileGraph` gets the extra edges. The HUD saves one store key per stream and loads it on
the re-detection that already exists.

## The codegraph finding (item 1.1)

Measured on 2026-11-07 with codegraph 1.6.2 on the case 72 fixture
(`.codegraph/codegraph.db`, schema version 11), with a read-only SQLite query:

- Edge kinds in the index: `calls` 601, `contains` 1054, `imports` 637. Node kinds: `file`
  468, `function` 416, `import` 638.
- `packages/money/src/index.ts` and `packages/notify/src/index.ts`: one `file` node each,
  no `import` node, **no out edge of any kind** (the join on `edges` over both `source`
  and `target` with any `kind`), and no in edge.
- 12 files hold `export * from`; 0 of them have a cross-file out edge.
- `packages/core/src/config/scanRebateSet.ts` has `imports` and `calls` edges to
  `renderWindowView.ts` and to `packages/notify/src/hooks/parseVoucher.ts`, the file that
  defines the name it imports from `@app/notify`. It has no edge to the package entry
  `packages/notify/src/index.ts`. 371 files import an `@app/*` name; 0 have an edge to a
  package entry.

So the gap is in the index, not in `EDGE_QUERY`: there is no edge under any kind the query
could keep. The fix is the pass, not the query.

The chain the fixture counts: the hub `money/src/rounding/halfEven.ts` ← `money/src/index.ts`
(`export *`) and ← `notify/src/email/mergeShardMap.ts` (a deep import) ←
`notify/src/index.ts` (`export *`) ← `core/src/config/scanRebateSet.ts`
(`import { parseVoucher } from "@app/notify"`). Re-export edges reach both barrels. The
last file needs the edge to the entry (ADR 0017 §2).

## shipgate 0.24.0

- **The pass (ADR 0017).** `reexport_edges(root, files, tracked)` in `signals.py`, next to
  the regex scanner. Inputs: the graph's kept files, the tracked set for `GraphContext`
  (`frozenset(tracked)`, `_ts_aliases`). For each TS/JS file of `files`: read once with
  `_read_text` (None → skip). Lines through `_lines` (comment lines dropped), joined back,
  then one regex with DOTALL over `export` forms: `\bexport\s+(?:\*(?:\s+as\s+[\w$]+)?|
  type\s*\{[^}]*\}|\{[^}]*\})\s*from\s*['"]([^'"]+)['"]`. Each specifier → `_resolve_ts`;
  a set result gives edges to targets in `files`. Then the bare package imports: the
  `from '<name>'`, bare `import '<name>'` and `require('<name>')` specifiers of
  `_extract_ts(text)` whose text equals a workspace package name (no `/` after the name
  beyond the scope) → `file -> entry`. The workspace map: root `package.json`
  `workspaces` (a list, or `{packages: [...]}`), patterns `dir/*` expanded over the
  tracked `package.json` files one level under `dir`, and literal directories; each
  package's `name` and entry per ADR 0017 §2, probed with `_probe_ts`. Edges to the file
  itself are dropped. `graph_structure` merges: `out[a].add(b)`, `inn[b].add(a)`, counts
  the new pairs, and puts the count in the `structure.graph` block as `reexport_edges`
  (the regex arm's block carries `reexport_edges: null`, like `outside_repo`).
- **The grader.** `score_trace` walks the calls from the last and scores the last call
  whose `blast` holds a `files` list. `blast_objects` is unchanged; the filter is in
  `score_trace`. The docstring's `trace` bullet and the evals README's `trace` bullet say
  so.
- **Tests.** `test_codegraph.py`: a `TestReexportEdges(ShimSignalsCase)` with a fixture
  repo: `packages/money/src/hub.ts`, `packages/money/src/index.ts` (`export * from
  "./hub"`), `packages/notify/src/leaf.ts` (`import { hub } from "@app/money/hub"`),
  `packages/notify/src/index.ts` (`export { leaf } from "./leaf"`),
  `packages/core/src/use.ts` (`import { leaf } from "@app/notify"`), root `package.json`
  with `workspaces: ["packages/*"]`, each package's `package.json` with `name` and
  `exports: {".": "./src/index.ts"}`. `SHIM_EDGES` models codegraph: `leaf -> hub`,
  `use -> leaf`, nothing from a barrel, nothing to a barrel. Assert `blast hub.ts` on the
  graph arm lists the two barrels and `use.ts`, `source` is `graph`,
  `structure.graph.reexport_edges` is 3, and `--graph off` lists the money barrel only
  (the regex scanner resolves the relative `export *` but no workspace name, and that
  stays; the notify package names its entry with `main`, so both entry rules run). A second test: a barrel over
  `MAX_SCAN_BYTES` adds no edge. `test_signal_grader.py`: a trace whose last call holds
  `blast.files: null` scores the earlier call.
- **Record.** The before and after numbers below, the changelog entry naming #7, the
  README table row.

## shipgate-hud 0.11.0

- **The store codec (`review.ts`).** `STORE_SHAPE = 'shipgate-hud.review-board-v1'`,
  `storeKeyOf(root, stream)`, `encodeStoredBoards(root, stream, boards, savedAt)` and
  `decodeStoredBoards(raw): Result<ShapeError, StoredBoards>` reusing `decodeStoredBoard`
  (a board that fails is dropped as the atom's decoder drops it). `STORE_LIMIT = 20`.
- **The effects (`register.tsx`).** `saveBoards($, stream)`: after `captureBoard` and
  `markFinding` write the atom, read it back, take `boardsFor(boards, stream)` (the
  stream's own; a null-stream board is not saved), `$.store.set`, then `pruneStore($)`:
  `$.store.keys()`, decode each `review-board:` key, sort by `savedAt`, delete past 20.
  `restoreBoards($, position)`: in `detectAndRefresh` after a `Bound` refresh. `terminal`
  → `$.store.delete(key)`. Else read the key; decode; `root` and `stream` must match; when
  the atom holds no board of the stream, write `{ ...state, boards: [...stored.boards,
  ...state.boards], open: { kind: 'newest' } }`. Every store call through `settle`; a
  rejection ends the step. `refresh` returns the `Refreshed`, so the stream and the
  lifecycle come from its `position`, not from the atom.
- **Tests (`register.test.ts`).** `mock.store(on, entries)` beneath the world. A store
  watch like `reviewWatch` on `store.set` / `store.delete`. Cases: a capture writes the key
  with the board and the mark after `accept-0`; `reset()` then `session.start` draws the
  board again (the SC-002 test, rewritten); a key seeded for another stream is not drawn;
  a position with `lifecycle: terminal` deletes the key and draws no board; 20 seeded keys
  plus one capture leaves 20 and the oldest is gone; a `store.get` that denies draws the
  verdict-only round and no error. `review.test.ts`: the codec round-trips, refuses another
  shape tag.
- **Docs.** ADR 0009 gets an amendment note at its head and in §3; README's Review tab
  paragraph on `$.state` becomes the store paragraph; CHANGELOG 0.11.0; `plugin.json`
  0.11.0 with shipgate `>=0.23.0`; `marketplace.json`.

## Reference implementation

- The pass mirrors `scan_structure` (`signals.py`): `_read_text`, `_lines`, `_resolve_ts`,
  `GraphContext`. The merge mirrors `graph_structure`'s existing block build.
- The HUD codec mirrors `decodeReviewState` and `decodeStoredBoard` (`review.ts`); the
  effects mirror `captureBoard` and `recordApproval` (`register.tsx`): every `$` call
  through `settle`, decoding in `review.ts`, no cast.

## Risk ranking (design)

`hotspots` over the plan's files, source `graph`: `shipgate-hud/tests/register.test.ts`
(top · top · low), `shipgate-hud/hooks/register.tsx` (top · top · low),
`shipgate/scripts/signals.py` (high · mid · low), `shipgate-hud/hooks/review.ts` (high ·
low · top), `shipgate-hud/tests/review.test.ts` (high · low · low). `register.tsx` and
`signals.py` get their tests before the change: the existing suites pin them (the SC-002
test is rewritten on purpose, as the behaviour changes).

## CLAUDE.md / impact-map compliance

- Public repo: generic names only; the diff is grepped before review.
- shipgate's `hooks/` are untouched. shipgate-hud's `hooks/` is the mod; its no-op path (no
  sidecar) runs no store call: the restore runs only after a `Bound` refresh.
- Python 3.9: no `match`, no runtime `X | Y`.
- Two version bumps in lockstep with `marketplace.json`; release notes only in the
  changelogs.

## Offline numbers (case 72, `fixture --arm graph`, codegraph 1.6.2)

| when | `blast.files` P / R | tp / got / truth | missed |
|---|---|---|---|
| before (0.23.0) | 1.00 / 0.95 | 56 / 56 / 59 | `money/src/index.ts`, `notify/src/index.ts`, `core/src/config/scanRebateSet.ts` |
| after (0.24.0) | 1.00 / 1.00 | 59 / 59 / 59 | none |

`blast.tests` is 1.00 / 1.00 (15 of 15) on both. The regex arm stays at 1.00 / 0.03 (2 of
59). Case 13 stays at 1.00 / 1.00 on the graph arm.

## Upstream (for the maintainer to report to codegraph)

Three files, generic names, on codegraph 1.6.2:

```
src/a.ts      export const a = 1;
src/index.ts  export * from "./a";
src/b.ts      import { a } from "./index"; export const b = a + 1;
```

After `codegraph init -y .`, the cross-file edges in `.codegraph/codegraph.db` are
`src/b.ts -> src/a.ts (imports)` and `src/b.ts -> src/index.ts (imports)`. `src/index.ts`
has one `file` node, no `import` node and no out edge: `export * from "./a"` records
nothing. `codegraph node src/index.ts` prints `0 symbols · used by 1 file`.

A second case: in a workspace (`workspaces: ["packages/*"]`, package `@app/x` with
`exports: {".": "./src/index.ts"}`), `import { y } from "@app/x"` records an edge to the
file that defines `y` and none to `packages/x/src/index.ts`.

# Build Plan

## shipgate 0.24.0

- [x] T001 — signals.py: the re-export pass (`export … from`, bare workspace imports, the
  workspace map, the 1 MiB cap), the merge in `graph_structure`, `reexport_edges` in the
  graph block; shim tests with the two-hop barrel chain. — files:
  `shipgate/scripts/signals.py`, `shipgate/tests/test_codegraph.py` — done when: the new
  tests fail before the pass and pass after; the full suite is green.
- [x] T002 — grader: the last call whose `blast.files` is a list; docstring; README bullet;
  test. — files: `shipgate/evals/signal_grader.py`, `shipgate/tests/test_signal_grader.py`,
  `shipgate/evals/README.md` — done when: the new test fails before and passes after.
- [x] T003 — the offline proof on case 72 (recall 1.00, precision 1.00), the numbers in this
  worklog and the README table, CHANGELOG 0.24.0 naming #7, `plugin.json` and
  `marketplace.json` 0.24.0. — files: `shipgate/docs/prd/shipgate-0.24.0.worklog.md`,
  `shipgate/evals/README.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json` — done when: the grader prints 1.00 / 1.00.

## shipgate-hud 0.11.0

- [x] T004 — the store codec in `review.ts`; save on capture and on a mark, the newest-20
  cut, the restore on re-detection, the delete of a completed stream, the ignored failed
  read, in `register.tsx`; tests. — files: `shipgate-hud/hooks/review.ts`,
  `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts`,
  `shipgate-hud/tests/review.test.ts` — done when: the new tests fail before and pass
  after; `claude plugin test shipgate-hud`, `claude plugin validate shipgate-hud` and `tsc`
  are green.
- [x] T005 — ADR 0009 amended, README Review tab paragraph, CHANGELOG 0.11.0, `plugin.json`
  0.11.0, `marketplace.json`. — files: `shipgate-hud/docs/adr/0009-*.md`,
  `shipgate-hud/README.md`, `shipgate-hud/CHANGELOG.md`,
  `shipgate-hud/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done
  when: validate passes and the private-data grep is clean.

## Traceability
- FR-001, FR-002, FR-003, FR-004, FR-005 → T001
- FR-006 → T002
- FR-007, FR-008, FR-016 → T003, T005
- FR-009 … FR-014 → T004
- FR-015 → T005
- SC-001 → T003; SC-002 → T001; SC-003 → T002; SC-004 → T004; SC-005 → review

## Deviations & notes (filled during implementation)

- 2026-11-07 — T001: `test_signals.py` changed by one line, outside the task's file list:
  `test_json_shape` compares the regex arm's graph block as an exact dict, so the additive
  `reexport_edges: null` key is in its expected value now. Impact: none on behaviour.
- 2026-11-07 — T001: the 1 MiB cap test uses a three-file fixture, not the workspace chain:
  in the chain the bare-import edge to the entry is still added when the barrels are too
  large, so the count is 1 there, not 0. Impact: the cap is pinned on a barrel alone.
- 2026-11-07 — T001: the entry rules take two more forms Node reads: a string `exports`
  (read as `"."`), and an `exports` object with no `"."` key (read as the conditions
  object). A package that names no entry is probed at `<dir>/index`, never at `<dir>`
  itself, so a sibling `<dir>.ts` is never taken. Impact: none on the eval fixture.
- 2026-11-07 — T004: the test kit refuses a second unfiltered hook on one event, so the
  store and state watches in the tests carry key filters. The unreadable-store test refuses
  `store.get` and `store.set` but not `store.keys` (no key filter exists for it; with `set`
  refused the prune never runs). Impact: none on the plugin.
- 2026-11-07 — T004: `captureBoard` now awaits the history read, the save and the prune
  before the notification prompt passes on: one `get` of the stream's key when the atom
  holds no board of the stream (round 1 F2), one `keys`, no prune `get` up to 20 board
  keys and one per board key above that (F6), and the deletes past the limit; all in
  memory. `markFinding`'s atom write runs under `settle`, so a rejected write is caught
  where before it was an unhandled `void` promise. Impact: a stricter path, no new error
  shown.

# Review

## Review round 1

Review Workflow run `wf_c0360df0-680`: three lenses (correctness, conventions+design,
simplicity+security), Opus finders, `verify: high-only`, risk-ordered. Counts: 27 found,
24 after dedupe, 11 candidates over the floor of 60, 0 refuters (no BLOCKER or HIGH), 11
survivors, 0 killed, 13 below the floor. The orchestrator read every survivor's code and
took all 11 as fixes. Verdict: not ready.

- F1 MEDIUM `shipgate/scripts/signals.py:1194` — `_REEXPORT_RE` backtracks to the end of the file on every unclosed `export {` under DOTALL, so a file of many unclosed lists makes the pass quadratic; `export type * from` (TS 5.0) is not matched.
- F2 MEDIUM `shipgate-hud/hooks/register.tsx:1238` — a review return that arrives after `/clear` and before the lazy re-detection saves one round over the stream's stored history, and the restore then skips.
- F3 LOW `shipgate-hud/docs/adr/0009-the-verdict-only-round-reads-the-worklog.md:61` — §3 carried no inline note, so a reader who jumps there sees the old decision as current.
- F4 LOW `shipgate/docs/prd/shipgate-0.24.0.worklog.md:90` — the test plan said the regex arm lists nothing, but it lists the money barrel through its relative re-export.
- F5 LOW `shipgate-hud/hooks/register.tsx:1257` — `boardsFor` followed by a stream filter makes the first call do nothing.
- F6 LOW `shipgate-hud/hooks/register.tsx:1284` — `pruneStore` reads every board key on every capture and every mark.
- F7 LOW `shipgate/scripts/signals.py:1229` — a deeply nested `package.json` raises `RecursionError`, which `load()` does not catch, and the graph arm crashes.
- F8 LOW `shipgate/evals/README.md:193` — the README and the grader docstring say only a null `blast.files` is skipped; the code skips anything that is not a list.
- F9 LOW `shipgate-hud/tests/register.test.ts:?` — no test restores a board through the lazy detection path FR-011 names.
- F10 LOW `shipgate/docs/adr/0016-the-signal-grader-runs-outside-the-harness.md:37` — §2 still says the grader reads the last blast result; the narrower rule was not recorded.
- F11 LOW `shipgate/evals/README.md:51` — the case 72 row said the graph missed only re-export hops; one of the three misses needed the package-entry edge.

### Rejected findings

- `shipgate-hud/hooks/review.ts:1011` (LOW 55): a key whose value never decodes is kept on purpose; it may be a newer HUD's (ADR 0011 §5).
- `shipgate-hud/hooks/register.tsx:1312` (LOW 50): the pre-read of `holdsStream` avoids a state write; the check inside `withRestored` keeps the pure function total.
- `shipgate/scripts/signals.py:1286` (LOW 50): a re-export form inside a string literal is the regex scanner's known limit too; the pass shares its reader.
- `shipgate-hud/hooks/register.tsx:1260` and `:1252` (LOW 45): two quick marks, or two sessions on one stream, end with the last save; ADR 0011 says so now.
- `shipgate-hud/hooks/review.ts:1030` (LOW 40): a null-stream board sits behind the restored rounds by design; the newest round opens on a restore.
- `shipgate-hud/hooks/review.ts:973` and `:972` (LOW 40, 30): git refuses `:` in a branch name, and a project root with `:` is not a POSIX path the HUD meets; the key is compared whole.
- `shipgate/scripts/signals.py:1252` (LOW 35): a negated workspace pattern is skipped, so an excluded package still gets an entry edge; an over-approximation at file level, as ADR 0017 accepts.
- `shipgate/scripts/signals.py:1201` (LOW 30): `types` and `source` entries are out of scope by ADR 0017 §2.
- `shipgate-hud/README.md:353` and `:254` (LOW 55, 35): taken as doc edits in this round (the Layout line and the no-sidecar sentence), not as findings.
- `shipgate/docs/adr/0007-codegraph-as-detected-structure-provider.md:60` (LOW 50): taken; ADR 0007 carries an amendment note to ADR 0017.

## Review round 2

One reviewer with all lenses on the fix diff (Opus). It confirmed F1 to F11 fixed on
evidence (F8 left one function docstring behind), ran `test_codegraph.py` (130 tests, OK),
`test_signal_grader.py` (24, OK) and `claude plugin test shipgate-hud` (999 pass), and read
every changed function whole. Seven new LOW notes, none a regression. Verdict: not ready,
for the three code notes below; the orchestrator gates round 3 itself, because the fix
diff is a regex, one except tuple, one docstring and two tests.

- N1 LOW `shipgate/scripts/signals.py:1197` — the `{0,4096}` bound drops a generated barrel with a list over 4096 characters, and `[^{}]` alone keeps the scan linear (10 to 20 ms on 1 MB of adversarial input); the bound goes.
- N2 LOW `shipgate/scripts/signals.py:1092` — `_ts_aliases` catches no `RecursionError`, and the pass now runs it on the graph arm; a deeply nested `tsconfig.json` crashes the run.
- N3 LOW `shipgate/evals/signal_grader.py:231` — the `score_trace` docstring still says "null or absent".
- N4 LOW `shipgate/docs/prd/shipgate-0.24.0.worklog.md:238` — the store-call count was stale after F2 and F6; fixed in the note.
- N5 LOW `shipgate/CHANGELOG.md:13` — the docs did not list `export type * from`; added to the changelog, ADR 0017 §2 and FR-001.

### Rejected findings

- `shipgate/scripts/signals.py:1197` (LOW 60, N6): a brace inside an inline comment within a re-export list ends the match; a known limit, now stated in ADR 0017 §2.
- `shipgate-hud/hooks/register.tsx:1236` (LOW 40, N7): a return that lands after `/clear` on a stream that completed meanwhile rewrites its key once; the next detection deletes it again. Short-lived and unverified in practice; accepted.

## Review round 3

The orchestrator gated the N1 to N3 fix diff itself: the regex is `\{[^{}]*\}` with a
comment that credits the brace-free class (N1), `_ts_aliases` catches `RecursionError`
(N2), the `score_trace` docstring says "null, absent or not a list" (N3), and two tests
pin N1 and N2 (`test_a_brace_list_over_4096_characters_counts`,
`test_a_deeply_nested_tsconfig_is_ignored`). Fresh runs after the last edit:
`test_codegraph.py` 132 tests OK (1 skipped), `test_signals.py` 100 OK (1 skipped),
`test_signal_grader.py` 24 OK, the Python 3.9 syntax check exit 0, case 72 graph arm
1.00 / 1.00, `claude plugin test shipgate-hud` 999 pass, both `claude plugin validate`
runs pass, `tsc` clean, the private-data grep over the diff and the untracked files hits
only the marketplace owner fields already on `main`. The full suite ran once more after
the last edit (its line is in the `verify-run` event). Verdict: ready.
