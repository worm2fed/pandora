---
title: shipgate-hud type model — an astrolabe audit
date: 2026-10-20
status: research note — informs the session-stream-attribution design and its follow-ups; decides nothing by itself
related:
  - "../prd/session-stream-attribution.worklog.md"
  - "../adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
---

# shipgate-hud type model — an astrolabe audit

Three read-only reviews, each through one lens: the domain model and state machine, the
effects boundary (`register.tsx`), and the pure modules with their tests. The yardstick is
astrolabe (`astrolabe/skills/astrolabe/SKILL.md`, the domain-modeling Type review
checklist). Line numbers are at commit `ef193b7`.

## Verdict

The HUD was built behaviour-first. It has thorough example tests (338) and a sound split:
pure modules under a thin `$` shell. It was not built types-first, and astrolabe was never
applied. `types/index.d.ts` is the `$.state` storage contract, not a domain model. No type
describes journal.py's JSON. So each call site narrows it by hand, absence turns into
`''`, `'?'` or `0`, and several journal rules are copied into TypeScript. Some copies
disagree today.

The type gaps are not cosmetic. Five of them let the publish gate pass a command it should
hold, and three show the user a wrong position.

## Behaviour defects the type gaps cause

Ranked by effect. Each one has a confirmed code path. "Reproduced" means an auditor ran it.

| # | Defect | Where | Effect |
|---|---|---|---|
| D1 | A failed probe becomes "no stream". Every failed nested `status` run is skipped, and exit 2 is read as "journal.py too old for `--session`". python3 also exits 2 for a missing script file, for example after a plugin-cache update. | `register.tsx:484-488`, `:495-507` | The refresh stores `{position: null, error: null}`, and the gate passes at `:812`. Fail-open. |
| D2 | The gate reads the band's position, not the command's target. | `register.tsx:799-820`, `publish.ts:201` | Problem 2 of the worklog. |
| D3 | A cut during `locateJournal` reads as "journal.py not found". | `register.tsx:136-156`, `:804` | The gate passes. |
| D4 | The gate reads `position` and `lastError` in two separate awaits. A parallel refresh can write between them. | `register.tsx:805-807`, `:639-640` | A torn read can pass an unreviewed stream. |
| D5 | `hasSurface` starts `false`, and only `session.start` sets it. | `register.tsx:610`, `:753`, `:801` | After a plugin reload, the gate is open until the next session start. |
| D6 | The publish rule is copied. The journal accepts `decision: ["publish"]`. Python's `str()` gives `"['publish']"`, so journal.py refuses `mr-opened`. JS's `String()` gives `"publish"`, so the HUD authorizes. The trim sets also differ. | `position.ts:223-237` vs `journal.py:832-866` | Reproduced. The HUD passes a publish that the journal would refuse. |
| D7 | A stream with no phase yet (`phase: null`) shows as `workspace`. | `position.ts:287` | Reproduced. |
| D8 | Skipped and implied phases show as done. `PhaseMark` has no `skipped`. | `position.ts:35-44` | The timeline says clarify and design passed when the journal says they were skipped. |
| D9 | The Build Plan grammar is copied and differs in four ways: heading level, region end, `*` bullets, task-id form. | `position.ts:46-74` vs `journal.py:259-260`, `:1686-1704` | Reproduced. A `* [x] T002` line blocks the Stop gate, and the HUD does not list T002. |
| D10 | A finished stream that matches the branch is drawn as live. The HUD drops `terminal` and `dormant`. | `position.ts`, `journal.py:1489` | The band and the gate judge a closed stream as live. |
| D11 | Stored review boards are cast, not decoded. | `review.ts:244-245`, `:298-303` | After an upgrade that adds a finding field, an old board can throw in the render path on every band render. |
| D12 | A review return with junk survivors passes `isReviewReturn`. | `review.ts:89-111` | Cards for findings that do not exist, with live Accept and Kill buttons. |
| D13 | The ADR home is hardcoded as `/adr/`. | `position.ts:206-207` | Reproduced. ADRs in a custom home are dropped. |
| D14 | A refresh error is dropped from the hold text when a stale position exists. | `publish.ts:317-318` | The model is told to record a verdict when the real cause is an unreadable journal. |

Two defects sit in shipgate itself:
- `gate-decision.decision` accepts any JSON value (`journal.py:160-168`).
- `_matches_glob` uses `lstrip("./")` (`journal.py:1729`). That strips a character set, not the `./` prefix.

## Journal rules the HUD re-derives

| Rule | journal.py | HUD | Agree today? |
|---|---|---|---|
| Phase order | `73-82` | `index.d.ts:4-12`, `position.ts:9-29` | Yes. Nothing links them at compile time. |
| Phase when none was entered | `None` | `'workspace'` | No (D7) |
| Skipped and implied phases | `793-813`, `1113-1125` | all marked `done` | No (D8) |
| Publish authorization | `832-866` | `position.ts:223-237`, prose in `publish.ts:313` | No (D6) |
| Ticked Build Plan tasks, Stop rule A | `1686-1704`, `1787-1861` | `position.ts:46-74`, `views.tsx:291` | No (D9) |
| Home glob matching | `1722-1729` | `position.ts:366-389` | Yes on the default homes; no on edge cases |
| Artifact classification | `1732-1748` | `position.ts:206-207` | No for a custom ADR home (D13) |
| Stream slug | `1257-1260`, `1370` | `position.ts:357-360` | Half: matches the branch slug, not `feature_slug` |
| Nested-branch choice | `1393-1409` | `register.tsx:494-507` | Yes. The HUD runs one `status` per branch instead of passing `--nested-branch`. |
| Lifecycle (terminal, dormant) | `206-230`, `1350` | dropped | No (D10) |

ADR 0001 rejected re-implementing status logic in TypeScript for exactly this reason.
The fix is the same in each row: the journal computes the fact and prints it, and the HUD
decodes it.

## Type-model gaps (astrolabe checklist)

- **No declared boundary for journal.py JSON.** There is no input type. `register.tsx`
  casts at `:331`, `:348`, `:433`, `:457` and `:518`. `Array.isArray(unknown)` narrows to
  `any[]`. `json.ts` turns absence into `''`, `{}` and `[]`.
- **The binding is not a type.** Session-driven, branch, nested guess and none all come
  back as `Checkout | null` (`register.tsx:341-353`).
- **Failure is thrown, then sorted by string matching.** `RunFailed`, plain `Error` and
  `SyntaxError` are thrown. A regex on the engine's message text then decides what was a
  cut. Five catch sites apply five policies.
- **Invalid states can be represented:**
  - `Refreshed {position, error, aborted?}`;
  - `PublishAuthorization {authorized, by, at: ''}`;
  - `ReviewState.open` with the magic value `'none'`;
  - the four verdict fields spread across `Position`;
  - `script: string | null` with three meanings.
- **Closed vocabularies typed `string`:** `Phase | string`, `Severity | string`,
  `raisedBy`, `mode`, `outcome`, criteria status, dispositions, `counts`.
- **Non-exhaustive dispatch:** `Tab`, `ReviewMark`, `defaultTab`, the phase glyph, and
  `SEVERITY_COLOR: Record<string, …>`.
- **Mutation in pure code:** `parseCriteria` aliases an element that it already pushed,
  and the code has several `push` accumulators.
- **No property tests,** although the code documents laws: band width, grid rows, at most
  five rounds, glyph cycling.
- **Fixtures drift from journal.py.** `FEATURE.last_verify` says pass while `LOG` ends in a
  failing run. `STATUS` has no `session_match`. Events carry no `stream`, `version` or
  `actor`. Review risk labels use `medium`, which the workflow never emits. No test ties
  the fixtures to journal.py.

What to keep as the pattern: the `$`-free pure modules, `json.ts` as the one narrowing
kernel, total records over unions (`PHASE_SHORT`, the diagram tables), `Fence` as a tagged
union, `TickOverride` with its guard, required `| null` fields, the defensive text
handling, table-driven tests, golden grid pictures and migration tests.

## The canon adapted to a mod

The mod imports only `claude-code`: no fp-ts, ts-pattern, newtype-ts or fast-check.
`$.state` must be JSON.

| Canon | Here |
|---|---|
| `Option` | a required `T \| null`, never `?:` (JSON drops `undefined`) |
| `Either` | `Result<E, A> = { ok: true; value: A } \| { ok: false; error: E }` in `json.ts` |
| `match().exhaustive()` | a total `Readonly<Record<Union, X>>` table first; else `switch` with `default: return absurd(x)` |
| newtype | `string & { readonly [brand]: 'X' }`, one smart constructor per brand, the one commented cast |
| fast-check | `tests/arbitrary.ts`: a seeded PRNG, small generators, `forAll(seed, runs, gen, law)` |
| casts | only at declared boundaries: process stdout, `$.state` reads, `ui.resolve`, test-kit events |
| `try`/`catch` | only in `runJournal` and `classifyRejection` in `register.tsx` |
| `$.state` | tagged unions, a `version` field, one decoder at the read |

Two engine checks come before the declarations land. First, check that
`claude plugin validate` accepts branded intersections and `readonly` arrays in the
`PluginState` contract. If it does not, keep the brands on the hook-side types and keep the
contract plain. Second, check whether `atom(…, { shape })` exists for versioning stored
values.

## Target model (declarations only)

```ts
// json.ts — the narrowing kernel
type Result<E, A> = { readonly ok: true; readonly value: A } | { readonly ok: false; readonly error: E }
declare function absurd(value: never): never

// journal.ts — pure; the one boundary for journal.py JSON, never stored in $.state
type StreamName = Brand<string, 'StreamName'>
type BranchName = Brand<string, 'BranchName'>
type EventSeq = Brand<number, 'EventSeq'>
type IsoTime = Brand<string, 'IsoTime'>
type Lifecycle = 'live' | 'dormant' | 'terminal'
interface CurrentPhase { readonly phase: Phase; readonly enteredAt: IsoTime; readonly isImplied: boolean }
type PublishAuthorization =
  | { readonly kind: 'held' }
  | { readonly kind: 'authorized'; readonly by: 'review-verdict' | 'gate-decision'; readonly seq: EventSeq; readonly at: IsoTime }
interface StatusFeature {
  readonly stream: StreamName
  readonly current: CurrentPhase | null
  readonly lifecycle: Lifecycle
  readonly isSessionMatch: boolean
  readonly isBranchMatch: boolean
  readonly lastEventAt: IsoTime | null
  /** Computed by journal.py, the same helper `mr-opened` uses. */
  readonly publish: PublishAuthorization
}
interface StatusBrief {
  readonly features: readonly StatusFeature[]
  readonly sessionMatch: StreamName | null
  readonly branchMatch: StreamName | null
  /** Live streams the nested branches name; present when nested branches were passed. */
  readonly nestedMatches: readonly StreamName[]
}
type JournalShapeError = { readonly path: string; readonly expected: string }
declare function decodeStatus(raw: unknown): Result<JournalShapeError, StatusBrief>
declare function decodeLog(raw: unknown): Result<JournalShapeError, readonly JournalEvent[]>

// register.tsx — the effect boundary
type RunFailure =
  | { readonly kind: 'Cut' }
  | { readonly kind: 'CannotStart'; readonly message: string }
  | { readonly kind: 'Exited'; readonly exitCode: number; readonly stderr: string }
  | { readonly kind: 'UnknownFlag'; readonly flag: string } // exit 2 AND argparse's text
  | { readonly kind: 'Truncated' }
  | { readonly kind: 'BadShape'; readonly error: JournalShapeError }
type Run<A> = Result<RunFailure, A>
type ScriptLookup = { readonly kind: 'NotSearched' } | { readonly kind: 'Found'; readonly path: string } | { readonly kind: 'NotFound' }
type Binding =
  | { readonly kind: 'Session'; readonly feature: StatusFeature }
  | { readonly kind: 'Branch'; readonly branch: BranchName; readonly feature: StatusFeature }
  | { readonly kind: 'Unbound'; readonly nearby: readonly StreamName[] }
type Refreshed =
  | { readonly kind: 'NoProject' }
  | { readonly kind: 'NoJournalScript' }
  | { readonly kind: 'Cut' }
  | { readonly kind: 'Failed'; readonly failure: RunFailure }
  | { readonly kind: 'Unbound'; readonly nearby: readonly StreamName[] }
  | { readonly kind: 'Bound'; readonly via: 'Session' | 'Branch'; readonly position: Position }

// types/index.d.ts — one stored view replaces the position and lastError atoms
type HudView =
  | { readonly kind: 'Off' }
  | { readonly kind: 'Unbound'; readonly nearby: readonly string[] }
  | { readonly kind: 'Bound'; readonly via: 'Session' | 'Branch'; readonly position: Position }
  | { readonly kind: 'Failed'; readonly message: string; readonly stale: Position | null }

// publish.ts — pure and total
interface PublishCommand { readonly head: PublishHead; readonly dir: string | null; readonly refspec: string | null }
type CommandScan = { readonly kind: 'publishes'; readonly command: PublishCommand } | { readonly kind: 'clear' } | { readonly kind: 'opaque'; readonly why: string }
type TargetBinding =
  | { readonly kind: 'Stream'; readonly branch: BranchName; readonly stream: StreamName; readonly publish: PublishAuthorization }
  | { readonly kind: 'NoStream'; readonly branch: BranchName | null }
  | { readonly kind: 'Unknown'; readonly failure: RunFailure }
type Hold =
  | { readonly kind: 'Unreviewed'; readonly head: PublishHead; readonly stream: StreamName }
  | { readonly kind: 'Unreadable'; readonly head: PublishHead; readonly failure: RunFailure }
type GateVerdict =
  | { readonly kind: 'Pass'; readonly why: 'NotPublish' | 'NoSurface' | 'NoProject' | 'NoJournalScript' | 'Authorized' | 'NoStream' }
  | { readonly kind: 'Hold'; readonly hold: Hold }
declare function gateVerdict(inputs: GateInputs): GateVerdict
```

The later slices extend `Position`:
- `schema`, `lifecycle` and `current: CurrentPhase | null`;
- `PhaseMark` gains `skipped` and `revisited`;
- `Decision` gets a real `seq`, plus `RaisedBy` and `GateMode`;
- one `lastVerdict: Verdict | null`, with `CriterionStatus` and `Disposition` unions;
- `TaskId`.

The review state changes too:
- `ReviewFinding` splits into survivor, killed and below-floor variants;
- `OpenRound` becomes a union;
- marks are stored on their board.

## Contract test

1. **The producer owns a golden file.** A Python test builds a scripted journal through the
   CLI. It runs `status --json` and `log --json`, normalises `ts`, `age_days` and
   `dormant`, and compares the result with a generated `shipgate-hud/tests/fixtures.journal.ts`
   (header: "generated — do not edit"). An environment flag regenerates the file. The test
   skips when `shipgate-hud/` is absent.
2. **The consumer decodes the golden file.** A HUD test runs it through `decodeStatus`,
   `decodeLog` and `toPosition`, and asserts the result. The hand-written variants are
   checked with `satisfies` against the boundary types, so a variant cannot invent keys.
3. **A differential test** covers each rule that stays duplicated until the journal owns
   it. It uses one table of event sequences, run through both copies.
4. **Close the vocabularies at the source.** `EVENT_SHAPES['review-verdict']` declares
   `criteria` and `dispositions` with enums. `gate-decision.decision` must be a string.
