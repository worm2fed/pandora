---
type: worklog
title: "Worklog: Session-to-stream attribution"
created: 2026-10-20
updated: 2026-10-20
tags:
  - worklog
  - shipgate-hud
  - shipgate
status: reviewed
prd: ""
related:
  - "../../../shipgate/docs/adr/0003-session-attribution-via-current-session.md"
  - "../../../shipgate/docs/adr/0005-session-label-from-the-shell-environment.md"
---

# Worklog: Session-to-stream attribution

> A bug investigation across two plugins. No PRD: the report is the requirement. Problems 1
> and 2 live in shipgate-hud. Problem 3 lives in shipgate's hooks and `journal.py`.

---

# Root cause

## Setup that shows it

- An umbrella checkout. The session root is a repo on its default branch, which has no
  stream. The real repos are nested under `source/<repo>`.
- Some nested repos have per-repo worktrees at `source/<repo>/.worktrees/<slug>`, on feature
  branches with live streams.
- An issue worktree of the umbrella sits at `<umbrella>/.worktrees/<name>/`. It is a detached
  worktree of the umbrella. It holds `source/<repo>` worktrees on the issue's branch.
- Several sessions run at once against one journal. One session at the umbrella root wrote
  to no stream.

## Problem 1: the HUD shows a stream the session does not drive

Expected: a session that wrote to no stream, at a root whose branch has no stream, shows no
stream (or one it can claim). Actual: the band names the most recently active stream among
the nested branches. The label moves when unrelated streams move.

Cause, in `shipgate-hud/hooks/register.tsx`:

- `streamOfCheckout` (line 473) asks `status --session=<id> --branch=<own>`. journal.py
  marks no `session_match` and no `branch_match`.
- It then walks `nestedRepos` (line 302), probes each distinct nested branch with its own
  `status --branch=<b>` run, and keeps the match with the newest `last_event`
  (line 506).
- Nothing ties the nested branches to this session. They are shared checkouts that other
  sessions drive.
- The walk enters `<root>/.worktrees/` one level only. `.worktrees/<name>` is a detached
  worktree of the umbrella, so `git rev-parse --abbrev-ref HEAD` answers `HEAD` and the walk
  takes no branch from it. It never looks into `.worktrees/<name>/source/<repo>`. So the
  newest stream in the observed case was not a candidate. (The report said the probe does
  not enter dot-directories at the root. It does enter `.worktrees/`, but stops one level
  down.)

shipgate's SessionStart hook has the same walk (`nested_branches` in
`shipgate/hooks/session_start.py`) and passes the branches as `--nested-branch`.
`nested_branch_match` in `journal.py` (line 1393) then puts the newest match first in the
brief, in full. Same guess, lower stakes: the brief still lists every stream.

Introduced by `643e7f5` (shipgate-hud 0.2.0, umbrella roots). Kept by `36dcec1` (0.2.4, the
session probe first): that change made the session the first signal, but left the nested
guess as the fallback for a session with no events.

Why it slipped through: the 0.2.0 test models one live stream beside a dormant one. No test
had two live nested streams, or a session that did no work.

## Problem 2: the publish gate uses the guessed stream

Expected: a publish command is held against the stream of the branch it publishes, or against
no stream when that branch has none. Actual: it is held against the stream the HUD shows,
whatever repo the command targets.

Cause: the `tool.check` hook (`register.tsx` line 799) refreshes, then reads the `position`
atom. That atom is the output of `streamOfCheckout`, the guess from problem 1. The gate never
looks at the command's target directory or branch. `git -C source/svc-d push` is held over
stream A's review state.

This also affects a session that does drive a stream. A session bound to stream S that
pushes another repo's branch is held against S.

Introduced by `3226b5e` (shipgate-hud 0.3.0, the publish gate). It reused the band's position
as the gate's position.

Why it slipped through: every gate test runs in a single-repo world, where the band's stream
and the pushed branch are the same thing.

## Problem 3: `artifact-written` names the wrong session

Expected: an `artifact-written` event names the session that wrote the file, or no session
when that is unknown. Actual: it names the session whose hook landed first.

Cause, in two parts:

1. **FileChanged names the observer.** Every session arms FileChanged on the same artifact
   homes (`watch_paths` in `shipgate/hooks/_common.py`). When one session writes a PRD, the
   hook fires in every session. `file_changed.py` (line 68) records
   `session: payload.session_id`, which is the session that observed the change, not the
   one that made it.
2. **The dedupe keeps the first row, whoever wrote it.** `_recent_duplicate_artifact` in
   `journal.py` (line 1075) folds a second `artifact-written` for the same path and mtime
   within 5 s into the first row. It compares path and mtime only. So when an observer's
   FileChanged lands before the writer's PostToolUse, the writer's own `source: tool` record
   is dropped.

Effect beyond the label: the Stop gate (`run_check`, rules A and B) reads a session's
`artifact-written` events to find the worklogs and PRDs it wrote. The bystander session gets
the finding and is blocked at Stop. The writer gets no finding and goes free. `stats`
counts the bystander as a session that touched the stream.

The HUD's session binding ignores hook-written events (`session_stream` skips actor `hook`),
so this is not the cause of problem 1.

Introduced by `c7b2844` (FileChanged records `session`) and `046c758` (the path-and-mtime
dedupe). Each was sound for one session per project. Parallel sessions on one journal made
the pair wrong.

Why it slipped through: the hook tests run one session. The dedupe was written for "two hooks
of one session see one write", which is true only with one session.

## Repro tests (pin current behaviour; the fix inverts them)

- `shipgate-hud/tests/register.test.ts`, describe `repro: an umbrella session that drives no
  stream`:
  - `problem 1`: four nested checkouts on live streams, a detached issue worktree holding the
    newest stream, a session that wrote to none. The band names stream A. Stream B moves, and
    the next refresh relabels the session as B. The issue worktree's repo is never probed.
  - `problem 2`: `git -C source/svc-d push` is held, and the dialog names stream A.
- `shipgate/tests/test_hooks.py`, class `TestTwoSessionsWatchOneArtifact`:
  - observer first: one row, owned by the observer. The observer's Stop is blocked over the
    PRD; the writer's Stop is clean.
  - writer first: one row, owned by the writer. The outcome is a race.

Runs: `claude plugin test shipgate-hud` 338 pass, 0 fail.
`python3 -m unittest discover -s shipgate/tests` 648 tests OK (2 skipped).

---

# Design

## Decisions (the user's, journal seq 922–927)

- **1B.** A session that wrote to no stream binds through nested repos only when every nested
  match names one live stream. Two or more live matches bind nothing, and the pane says why.
  The rule lives in `journal.py`, so the status brief and the HUD agree. Teammates run as
  separate sessions, so subagents that share the lead's id are out of scope.
- **2B.** The publish gate checks the stream of the branch the command publishes. When that
  branch has no stream, or the command cannot be resolved, it checks the session's bound
  stream.
- **3A + 3B.** An `artifact-written` event names a session only as an author. Bash writes are
  attributed by the Bash call's own evidence.
- **Types first.** The touched HUD code gets a declarations task before its bodies. A
  read-only astrolabe audit of the whole HUD runs first, so the fix lands on the agreed type
  model.
- **Release.** One branch. shipgate and shipgate-hud both bump.

## shipgate: attribution is resolved when it is read

The journal is append-only. So the hooks record facts, and `journal.py` decides authorship
when it reads them. Three kinds of claim exist for one write, identified by path and mtime:

| Source | Hook | Meaning | Session field |
|---|---|---|---|
| `tool` | PostToolUse on Write, Edit, NotebookEdit | the session wrote it with a file tool | `session` |
| `bash` | PostToolUse on Bash (new) | the session's Bash call changed it | `session`, plus `evidence: diff` or `window` |
| `disk` | FileChanged | a session's watcher saw it change | `observed_by` (was `session`) |

- **Append time.** A `disk` row is dropped when any row for the same path and mtime landed in
  the last 5 s (today's rule). An authored row (`tool`, `bash`) is dropped only when the same
  session already claimed the same path and mtime. So an observer that lands first can no
  longer swallow the writer's claim.
- **Read time.** One fold resolves the author of each write: `tool` beats `bash/diff`, which
  beats `bash/window`. Two different sessions with the same best evidence give no author.
  The Stop gate's rules A and B, and `stats`, read authors from this fold, never from raw
  rows. A `disk` row has no author. A legacy `disk` row that still carries `session` counts
  as observed.
- **`parse_actor`.** An event whose payload names `observed_by` keeps the bare `hook` role.
  Without that, the hook's environment would label the row with the observer's id again.

### The Bash claim (3B)

PostToolUse matcher becomes `Write|Edit|NotebookEdit|Bash`. For Bash, after the usual fast
path (`likely_journaled`, then the sidecar):

1. **Diff evidence.** `tool_response.bashEditDiff.changedFiles` lists the files the call
   changed (Claude Code 2.1.269+, in auto and bypass modes, or with `bashEditDiffEnabled`).
   Each listed file inside an artifact home becomes a `bash` claim with `evidence: diff`.
   The docs call the list best effort and beta, so it is evidence, not policy: a wrong entry
   can at worst tie with the true writer, and a tie gives no author.
2. **Window evidence.** No usable diff (`unavailable`, `skipped`, absent): the call ran for
   `duration_ms`. An artifact whose mtime falls in that window, and whose file name the
   command text mentions, becomes a `bash` claim with `evidence: window`. The name check
   keeps a concurrent session's unrelated Bash call from claiming the write.
3. **Nothing else.** A background command (`run_in_background`) has no diff and no real
   duration, so it claims nothing. Its writes stay observed only.

Cost: every Bash call in every project now starts this hook. The non-journaled path stays
the `likely_journaled` stat walk and exits. In a journaled project the hook globs the
artifact homes and spawns `journal.py` only when a claim exists.

## shipgate: the nested-branch rule (1B)

`nested_branch_match` returns a stream only when the live streams that the nested branches
name are exactly one. Dormant and finished streams do not count. `status --json` gains
`nested_matches`: the live streams the nested branches name, newest first, present when
nested branches were passed. The SessionStart hook needs no change.

## Scope widened by the audit (journal seq 929–932)

The astrolabe audit (`../research/2026-10-20-hud-type-model-audit.md`) found defects D1–D14.
The user chose to fix all of them in this branch. The journal owns every fact the HUD
draws (shipgate ADR 0009), so the HUD keeps only decoding, display parsing of markdown, and
drawing. The ADRs:
- shipgate 0008: artifact authorship is resolved at read time;
- shipgate 0009: the journal computes the HUD's position;
- HUD 0004: a session binds to a stream only on evidence;
- HUD 0005: the publish gate checks the published branch;
- HUD 0006: the type model follows astrolabe, adapted to a mod.

## shipgate: the `position` contract

`status --json`:
- **Per stream it gains:**
  - `publish`, either `{kind: held}` or `{kind: authorized, by, seq, at}`;
  - `lifecycle`, one of `live`, `dormant` or `terminal`;
  - `current`, either `{phase, entered_at, implied}` or null.
- **At the top level it gains** `nested_matches`.
- **`branch_match` from nested branches** follows the 1B rule.

`position --stream <s> --json`, one object:
- `stream`, `version`, `lifecycle`, `current`, `publish`;
- `phases`: a mark for each of the 8 phases, one of `done`, `skipped`, `current`,
  `revisited` or `todo`;
- `artifacts`: `{worklog, prd, adrs}`, classified with the configured homes. Only the
  events that commit or work an artifact count, which is today's HUD rule moved into
  Python;
- `tasks`: `[{id, title, section, ticked, done, last_verify}]`, parsed from the worklog
  with `check`'s grammar. The fields are null when there is no worklog;
- `decisions`: `[{seq, gate, question, decision, raised_by, mode, at}]`;
- `verdict`: `{seq, at, verdict, criteria, dispositions}`, or null.

Payload rules:
- `gate-decision.decision` must be a string.
- `review-verdict` declares `criteria` (`met`, `unmet`) and `dispositions` (`fixed`,
  `rejected`, `deferred`).
- `_matches_glob` strips the `./` prefix, not a character set.

## shipgate-hud: the type model

The declarations follow the research note's target model. These are the modules:
- **`json.ts`.** `Result`, `Brand`, `absurd`, and the narrowing helpers. The helpers return
  `| null`, never a fallback.
- **`journal.ts`** (new, pure). The boundary types for `status` and `position`, plus
  `decodeStatus`, `decodePosition` and `decodeSidecarHomes`. This is the only place
  journal.py's JSON is cast.
- **`position.ts`.** It maps a decoded position to `Position`, the stored view, and keeps
  the markdown parsing for display: ADR title and status, design sections, criteria. It
  loses `phaseMarks`, `parseBuildPlan`, `publishAuthorization` and `artifactRefs`.
- **The refresh trigger keeps a glob check.** `matchesHome` stays only as the trigger that
  decides whether a Write needs a refresh. It is not a fact the HUD draws, and a false
  match costs one extra refresh.
- **The journal owns the worklog fallback.** `position` returns `artifacts.worklog` from the
  events, or else the slug-named worklog that no other live stream claims, with
  `worklog_from: event | name`. So `worklogForStream` and `claimedWorklogs` leave the HUD,
  together with their one `log` run per sibling stream.
- **`publish.ts`.** `scanCommand` returns a `CommandScan`, and the pure, total
  `gateVerdict` decides. The hold and deny texts take a `Hold`.
- **`review.ts`.**
  - A finding is one of three variants: survivor, killed or below-floor.
  - `decodeReviewReturn` and `decodeReviewState` decode the workflow return and the stored
    state.
  - `OpenRound` is a union, and marks are stored on their board.
- **`register.tsx`.**
  - Effects: `Run`, `RunFailure`, `runJournal` and `classifyRejection`.
  - State: `ScriptLookup` and `RefreshSlot`.
  - Binding: `Binding` and `Refreshed`.
  - Gate: `resolveTarget`.
  - Storage: one `view: HudView` atom replaces `position` and `lastError`, with a shape tag.
- **`views.tsx`.** It draws through total tables (`TAB_VIEW`, `MARK_VIEW`, `PHASE_GLYPH`,
  `SEVERITY_COLOR`, `DEFAULT_TAB`) and dispatches on `HudView`.
- **`types/index.d.ts`.** The `$.state` contract: `HudView`, `Position` v2 and
  `ReviewState` v2, both as `type`, with brands where validate accepts them.

## Reference implementation

- **Total tables:** `PHASE_SHORT`, and in `diagram.ts` `RADIUS`, `CORNERS`, `ARROW` and
  `HEAD`.
- **Tagged union:** `Fence`.
- **Guard plus typed filter:** `TickOverride` with `isTickOverride` and `ticksOf`.
- **Stored-state migration and its tests:** `reviewStateOf`.
- **Python side:** `fold_stream` and `build_status` for new status fields, and the
  `test_journal.py` CLI helpers for tests.

## Risks

- **The gate is a security-relevant hook.**
  - Every change ends with the full `/security-review`.
  - The project config treats the no-op path of shipgate's hooks as a correctness
    requirement.
- **The contract changes.** Installed HUD 0.5.x with the new shipgate keeps working: status
  only gains keys. The new HUD with an old shipgate gets an error and a minimum-version
  message.
- **Stored state.** Shape-tag bumps drop old values. The next refresh re-derives them.

---

# Build Plan

Types first: the declarations tasks (T001, T002) are reviewed on their own before any body
lands. Tests ride with each task. Each task names its files and its "done".

## Declarations
- [x] T001 — shipgate JSON contract: `TypedDict`s for the status additions, `position`, the payload rules — file(s): `shipgate/scripts/journal.py` — done when: declared, `py_compile` passes, declarations reviewed
- [x] T002 — HUD declarations: `json.ts` kernel, `journal.ts` boundary types and decoder signatures, `publish.ts` scan and gate types, `review.ts` variants, register's `Run`/`Binding`/`Refreshed`/`ScriptLookup`/`RefreshSlot`, `types/index.d.ts` v2 contract; bodies `throw new Error('unimplemented')` — file(s): `shipgate-hud/hooks/*.ts`, `shipgate-hud/types/index.d.ts` — done when: `tsc` (tests included) and `claude plugin validate shipgate-hud` pass, declarations reviewed

## shipgate
- [x] T010 — the publish helper shared by `_validate_mr_opened` and the status output; `decision` must be a string — file(s): `journal.py`, `tests/test_journal.py` — done when: tests for list, whitespace and order cases pass
- [x] T011 [P] — `lifecycle`, `current`, phase marks with `skipped` and `revisited` in the fold — file(s): `journal.py`, `tests/test_journal.py` — done when: a stream with only `flow-started` gives `current: null`; an implied jump marks its skipped phases
- [x] T012 [P] — the 1B nested rule and `nested_matches` — file(s): `journal.py`, `tests/test_journal.py` — done when: two live nested matches bind none; one live plus one dormant binds the live one
- [x] T013 — `position --stream --json`: artifacts with the configured homes, tasks with `check`'s grammar, decisions with `seq`, the verdict — file(s): `journal.py`, `tests/test_journal.py` — done when: tests for each field pass, including `* [x]` bullets, nested headings and a custom ADR home
- [x] T014 — attribution: `observed_by`, the append dedupe by source and session, the read-time author fold for `check` and `stats`, `parse_actor`, legacy rows — file(s): `journal.py`, `tests/test_journal.py` — done when: the fold's tie, precedence and legacy cases pass
- [x] T015 — hooks: `file_changed.py` writes `observed_by`; `post_tool_use.py` makes Bash claims (diff, window, background); the `core.json` matcher — file(s): `shipgate/hooks/*`, `tests/test_hooks.py` — done when: `TestTwoSessionsWatchOneArtifact` is inverted and passes in both orders, the Bash cases pass, and the no-op path makes no `journal.py` run in an un-journaled project
- [x] T016 [P] — `review-verdict` vocabularies in `EVENT_SHAPES`; the `_matches_glob` prefix fix — file(s): `journal.py`, `tests/test_journal.py` — done when: a bad spelling is refused at append; `.notes/*` homes match as the HUD expects
- [x] T017 — golden contract: `tests/test_hud_contract.py` generates `shipgate-hud/tests/fixtures.journal.ts` from a scripted journal; an env flag regenerates it — file(s): `shipgate/tests/test_hud_contract.py`, `shipgate-hud/tests/fixtures.journal.ts` — done when: the test passes and fails on a renamed key

## shipgate-hud
- [x] T020 — `json.ts` and `journal.ts` decoders, tested against the golden file — file(s): `hooks/json.ts`, `hooks/journal.ts`, `tests/journal.test.ts` — done when: the golden file decodes; a renamed key is a decode error, not a default
- [x] T021 — the effect boundary: `runJournal`, `classifyRejection` (exit 2 only with argparse's text), `ScriptLookup` (re-check on a failed run), `RefreshSlot`, `HudView` atom with shape tag — file(s): `hooks/register.tsx`, `tests/register.test.ts` — done when: D1, D3 and D4 each have a failing-first test that passes
- [x] T022 — binding: `Session`, `Branch` or `Unbound{nearby}` from one status call plus one nested call; the pane's unbound text — file(s): `hooks/register.tsx`, `hooks/views.tsx`, tests — done when: repro problem 1 is inverted and passes, and an issue-worktree session binds its one stream
- [x] T023 — the position mapping from `decodePosition`; views draw `current: null`, `skipped`, `revisited` and lifecycle; the TypeScript copies are removed — file(s): `hooks/position.ts`, `hooks/views.tsx`, tests — done when: D6–D10 and D13 each have a failing-first test that passes
- [x] T024 — `scanCommand` (`-C`, leading `cd`, refspec, `--head`, `--source-branch`, opaque) and `gateVerdict` — file(s): `hooks/publish.ts`, `tests/publish.test.ts` — done when: a table covers every `GateInputs` kind and every refspec form
- [x] T025 — the gate: `resolveTarget`, `GateInputs`, `$.session.surfaces()` — file(s): `hooks/register.tsx`, tests — done when: repro problem 2 is inverted and passes; D2, D5 and D14 each have a failing-first test that passes
- [x] T026 — review: decoders, the finding variants, `OpenRound`, marks on the board, the stored-state shape tag — file(s): `hooks/review.ts`, `hooks/views.tsx`, tests — done when: D11 and D12 each have a failing-first test that passes, and the migration tests take `unknown`
- [x] T027 — pure-module hygiene: total tables (`TAB_VIEW`, `MARK_VIEW`, `PHASE_GLYPH`, `SEVERITY_COLOR`, `DEFAULT_TAB`), the `parseCriteria` fold, a `GridResult` union, no mid-pipeline casts, `readonly` — file(s): `hooks/views.tsx`, `hooks/review.ts`, `hooks/diagram.ts` — done when: no `as` outside declared boundaries (checked by grep), suite green
- [x] T028 [P] — property tests: `tests/arbitrary.ts`, laws for band width, grid rows, `pushBoard`, tick cycling and the command scan — file(s): `tests/arbitrary.ts`, `tests/*.test.ts` — done when: each law runs 500 seeded cases and prints the seed when it fails
- [x] T029 — fixtures: derive `FEATURE`, `STATUS` and `LOG` from the golden file, or mark variants `satisfies`; remove the test casts — file(s): `tests/fixtures*.ts`, `tests/world.ts` — done when: no hand-written journal JSON is left untyped

## Release
- [x] T030 — READMEs and CHANGELOGs for both plugins; shipgate 0.18.0, shipgate-hud 0.6.0, `marketplace.json`; the minimum shipgate version in the HUD README — file(s): `*/README.md`, `*/CHANGELOG.md`, `*/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: versions are in lockstep and the docs describe the new behaviour
- [x] T031 — the full verify: the Python suite, `claude plugin test` and `validate`, `tsc`, the timing of the hook's no-op path — done when: every command passes and its output is recorded

## Traceability
- Problem 1 → T012, T022 · problem 2 → T024, T025 · problem 3 → T014, T015
- D1, D3, D4 → T021 · D2, D5, D14 → T025 · D6 → T010, T023 · D7–D10, D13 → T011, T013, T023
- D11, D12 → T026 · fixtures drift → T017, T029 · the shipgate defects → T010, T016

---

# Deviations & notes

- 2026-10-20 — T002's type-check leaves out the tests. The v1 tests describe the old shapes,
  and each body task rewrites the tests for its area. The suite is expected to fail between
  T002 and the HUD body tasks. T031 runs the full, test-inclusive type-check.
- 2026-10-20 — `matchesHome` stays in the HUD as the refresh trigger for Writes. It is not
  a fact the HUD draws. The journal owns the worklog fallback (`worklog_from: name`), so
  `worklogForStream` and `claimedWorklogs` leave the HUD.
- 2026-10-20 — The declarations review froze T001 and T002 with these rulings (journal seq
  943–945). The workers apply them as fix-ups before any body task.
  - **Contract between the two sides:**
    - R1: `position` prints `last_verify`.
    - R2: a task with no title prints null, never `''`.
    - R3: `status` always prints `nested_matches` as a list.
    - R4: `position` on an unknown stream exits 1. Only argparse's exit 2 means "older
      journal.py".
    - R5: `position` drops unsafe refs.
    - R6: one task per id, and the first line wins. Values outside the vocabulary are
      dropped.
    - R7: the worklog fallback uses the stream's last path segment.
  - **HUD types:**
    - H1: the top-level match names decide, so the per-stream match booleans go.
    - H2: `TargetBinding` splits into `NoStream{branch}` and `Unresolved{why}`.
    - H3: `Position.plan` holds the worklog, its source and its tasks, or is null.
    - H4: criteria are keyed by `CriterionId`.
    - H5: the `isJournaled` atom goes.
    - H6: `HudView.Failed` stores the typed failure.
    - H7: `confidence` is `number | null`, and `quorum` is structured.
    - H8: tick overrides are stored as entries.
    - H9: ADR 0006 is amended. `Brand` lives in the contract, and `parseJson` is the second
      `try` site.
  - **Phase marks:** an earlier phase that was never entered is `skipped`. `revisited` is a
    later phase that was entered before the stream moved back.
  - **1B:** a nested branch is matched against live streams only.
- 2026-10-20 — T024 reshaped the frozen `PublishCommand` (journal seq 954–955). The worker
  found that `{dir: string | null, refspec: string | null}` has no faithful value for an
  unresolved target. Two examples are `git push --all` and `cd $X && git push`. The new
  shape is `{head, dir: Shell | Path | Unreadable, ref: Head | Branch | Unresolved}`.
  - A named branch is still checked when its directory is unreadable.
  - A literal `sh -c '…'` string is scanned recursively.
  - The scan normalizes a refspec to a branch name.
  - ADR 0005 is amended to match.
- 2026-10-20 — T015 also gives window evidence to watched artifacts that a usable diff does
  not list. Claude Code's diff never lists a file that git ignores or a file in a
  submodule. The paths are compared by `realpath`. The Stop gate now reads only the fold,
  so a write by an external editor or a sync is observed only and gates no session. The
  READMEs (T030) must say so. A Bash call that fails claims nothing, because PostToolUse
  fires only on success.
- 2026-10-20 — The HUD's remaining work is split into H3a and H3b. H3a covers the pure side:
  T020, T023, the band law and the pure part of T027. H3b covers the effects side after it:
  T021, T022, T025, T029, and the rest of T027.

---

# Review round 1

Verdict: **Not ready**. The review workflow is `wf_dd097a66-b0b`.
- **Lenses:** correctness, conventions+design and simplicity+security.
- **Counts:** 22 found, 21 after dedupe, 8 candidates, 6 refuters, 8 survivors, 0 killed.
- **Security:** the full `/security-review` found no vulnerabilities.

## Findings to fix

- **R1-F1 (HIGH, held 0/2, all three lenses)** at `shipgate-hud/hooks/publish.ts:44`, `:122`
  and `:876`.
  - **Defect:** the scan returns only the first publish command in a line, so the gate checks
    one target. In `git push origin a && git push origin b`, branch `b` is never checked.
  - **Why it is new:** before 0.6.0, every publish was held against one stream. This is a
    regression the target-based gate introduced.
  - **Fix:** `CommandScan.publishes` carries every publish command (a non-empty list). The gate
    resolves each target and holds when any target holds or cannot be read.
- **R1-F2 (MEDIUM, 60)** at `shipgate/hooks/post_tool_use.py:98`.
  - **Defect:** a window claim cannot tell a read from a write. A session whose Bash call names
    an artifact can claim an external editor's concurrent write, and that session is then
    blocked at Stop.
  - **Fix:** window evidence needs a write shape for the named file: a redirect target, `tee`,
    `sed -i`, `perl -i`, or the destination of `mv`, `cp` or `install`. A read never claims.
- **R1-F3 (LOW, 75)** at `shipgate/README.md:150`: the README cites ADR 0009 for the 1B rule.
  It should cite shipgate-hud ADR 0004.
- **R1-F4 (LOW, 70)** at `shipgate-hud/hooks/register.tsx:218`: `normalizePath` returns `..`
  for an absolute path that climbs above `/`, so `git -C ..` reads the wrong repository. Fix:
  stop at `/`, as POSIX does.
- **R1-F5 (LOW, 70)** at `shipgate/hooks/session_start.py:182`: the docstrings still call the
  nested branches an "ordering hint". They now decide the binding (1B).
- **R1-F6 (LOW, 60)** at `shipgate-hud/hooks/position.ts:206`: `matchesHome` and
  `globToRegExp` differ from `fnmatch`. Fix: strip exactly `./`, and treat `^` at the start of
  a class as a literal.
- **R1-F7 (LOW, 55, below floor, checked)** at
  `shipgate-hud/docs/adr/0004-a-session-binds-to-a-stream-only-on-evidence.md:18`: the summary
  says every nested repo names the stream. The Decision and the code require only that the
  live streams named are exactly one.

## Rejected findings

- **A malformed status row fails the whole brief** (`journal.ts:440`, MEDIUM 50). This is by
  design: strict decoding fails closed, journal.py controls the output shape, and the golden
  file pins it. A failed read holds the gate instead of guessing.
- **A diff claim names another session's concurrent write** (`post_tool_use.py:131`, MEDIUM
  40). This is the consequence ADR 0008 documents: a wrong entry can at worst tie with the true
  writer. A tool claim still wins.
- **`vetoText` passes the free-text `gate` unstripped** (`register.tsx:903`, LOW 50). This is
  not new: v1 did the same, and the security review found nothing here.
- **`json_extract` needs JSON1** (`journal.py:1282`, LOW 40). The schema already uses
  `CHECK (json_valid(data))` (`_migrate_to_1`), so JSON1 is already required.
- **A multi-branch push in an unbound session passes** (`publish.ts:363`, LOW 40). This is by
  design: ADR 0005 says such a push falls back to the bound stream, and an unbound session
  passes.
- **`session_stream` binds a dormant stream** (`journal.py:1722`, LOW 35). This is not new in
  this change.
- **A bare `git push` with a push config that publishes other branches** (`register.tsx:1013`,
  LOW 35). It is an edge case. It joins the known limits in the README.
- **`_is_safe_ref` follows symlinks** (`journal.py:2650`, LOW 30). The pattern is already on
  `main` (`run_check`), the text stays local, and the security review found nothing.
- **A failed batch line stops the later claims** (`_common.py:344`, LOW 30). The hook builds
  every claim itself, so the lines are valid. The impact is low.
- **The `isSafeRef` re-export, and the `roundId` cast** (LOW 30 and 20). Style only.
  `roundId` is that brand's one smart constructor, which ADR 0006 allows.

## Fixes for round 1

- **R1-F1:** fixed in `hooks/publish.ts` (`PublishCommands`, `PublishTarget`, `gateVerdict`
  with `lineVerdict`, and a `scanFrom` that collects every publish) and in
  `hooks/register.tsx` (`targetsOf`, `resolveTarget` reusing one `status --branch` read per
  branch).
  - The list of targets can never be empty.
  - A line where every command passes reports `Authorized` when any command was authorized,
    and `NoStream` otherwise.
  - ADR 0005, the README and the CHANGELOG are amended.
- **R1-F2:** fixed in `shipgate/hooks/post_tool_use.py` `writes_file`. A window claim needs a
  write shape. The tests cover 19 write shapes and 10 read-only commands.
- **R1-F3** and **R1-F7:** doc fixes.
- **R1-F4:** fixed in `hooks/register.tsx` `normalizePath`. An absolute `-C` path is passed to
  git unchanged, so git resolves it on disk, the same way the real command does.
- **R1-F5:** docstrings in `shipgate/hooks/session_start.py`.
- **R1-F6:** fixed in `hooks/position.ts` (`classBody`, and exactly one `./` stripped).
  Three differences from fnmatch remain in the refresh trigger only: `]` as the first member
  of a class, `*` matching a newline, and `\` treated as `/`.
- **Evidence:** `claude plugin test shipgate-hud` gives 786 pass and 0 fail. The Python suite
  gives 814 OK (skipped=2). `tsc` and `validate` are clean.

# Review round 2

This round re-reviewed the fix diff: one reviewer, all three lenses.
- **Round 1 findings:** R1-F1 to R1-F7 are each confirmed fixed, on evidence. The fix lines
  and tests are cited in the review. Every new R1 test fails on the unfixed code. The scan
  probes cover the directory state after a publishing segment, through `||`, `&`, `|`,
  subshells, heredocs, substitutions, functions and compounds. The fnmatch rows agree with
  `journal._matches_glob`.

New findings:
- **R2-N1 (MEDIUM, 60)** at `shipgate-hud/hooks/register.tsx:1241` and
  `shipgate-hud/hooks/publish.ts:106`.
  - **Defect:** one "Let it through once" passes every held command on the line, but the
    dialog names only the first held command. For `git push origin a && git push origin b`
    with both streams unreviewed, the user sees stream a only.
  - **Not new:** v0.5 also let the whole line through under one held stream.
  - **Fix:** `Hold` carries every hold on the line, and the dialog and the deny text list each
    held head with its stream or failure.
- **R2-N2 (LOW, 85)** at `shipgate/hooks/post_tool_use.py:141` and `:181`.
  - **Defect:** a window write target is matched by its file name only. So
    `cp docs/prd/feat.md /tmp/feat.md` and `cat docs/prd/feat.md > /tmp/feat.md` claim the
    artifact. That is the R1-F2 failure mode again.
  - **Fix:** match the artifact's project-relative path as a `/`-boundary suffix, or its
    absolute path.
- **R2-N3 (LOW, 85)** in `post_tool_use.py`.
  - **Defect:** the window misses common write shapes: `env A=1 sed -i …`, `command cp …`,
    `\cp …`, `perl -wpi …`, `git mv … f` and `gsed -i …`. A miss costs only a claim.
  - **Fix:** skip `env`, `command` and a leading `\` in the scan, extend the perl flags, and
    treat `git mv` like `mv`.
- **R2-N4 (LOW, 70)** in ADR 0005's Consequences: the cost line still says "one `git
  rev-parse` and one `status` run".
  - **Fix:** say one `status` per distinct branch, and one `rev-parse` per HEAD push.
- **R2-N5 (LOW, 55)** at `publish.ts:1045`: a heredoc body's publishes are listed after the
  rest of the owner's line. This is textual order. It changes only which stream a hold names.
  - **Fix:** say "textual order" in the `CommandScan` doc.

Rejected:
- **R2-N6 (LOW, 45):** the relative branch of `normalizePath` is unreachable from today's
  callers. Keep it. A relative input must never be read as absolute.

Checks that passed:
- versions are in lockstep;
- the release notes live only in each CHANGELOG;
- Python 3.9 compatibility;
- the hook's no-op path;
- ADR 0005 and the README match the code;
- the public-repo grep.

## Fixes for round 2 (round 3, approved by the user, journal seq 989)

- **R2-N1:** fixed. `GateVerdict.Hold` carries `holds` (a non-empty list, in textual
  order). `lineVerdict` collects every hold. `holdReason` and `denyReason` name each held
  command with its stream or failure. A single hold keeps its old wording, and a test pins
  that wording.
- **R2-N2:** fixed in `post_tool_use.py`. `_names_artifact` matches the artifact by its
  project path (a `/`-boundary suffix) or by its absolute path or realpath, never by its file
  name alone.
- **R2-N3:** fixed in `post_tool_use.py`. `_program` skips `env`, `command`, `sudo` and a
  leading `\`. It also accepts `perl -wpi`/`-Wi`, `git mv`, and `gsed`.
- **R2-N4:** fixed. ADR 0005's cost line is reworded.
- **R2-N5:** fixed. The scan's docs say "textual order".
- **Review of round 3:** the orchestrator did it alone. Each fix is two files, and both
  workers saw their tests fail first.
- **Test evidence:**
  - the HUD tests: 797 pass;
  - the Python suite: 815 OK (skipped=2), as the workers reported it;
  - a fresh run of the full gate follows below.

# Verdict

**Ready** (round 3, journal seq 993). The fresh gate after the last edit:
- **Python suite:** `python3 -m unittest discover -s shipgate/tests` ran 815 tests, OK
  (skipped=2).
- **HUD tests:** `claude plugin test shipgate-hud` gave 797 pass and 0 fail, over 7 files.
- **Type-check:** `tsc -p shipgate-hud --noEmit`, with the tests included, exited 0.
- **Validation:** `claude plugin validate shipgate-hud` and `claude plugin validate shipgate`
  both passed.
- **Compile:** `py_compile` passed under Python 3.15 and 3.9.
- **Security:** the full `/security-review` found no vulnerabilities.
- **Public repo:** the grep of the diff found no private name, path or tracker id.

Acceptance criteria:
- **Problem 1:** the umbrella repro is inverted in `register.test.ts` and passes. The
  session is Unbound, the pane names the nearby streams, and a moved stream changes nothing.
  An issue-worktree session binds its one stream.
- **Problem 2:** the repro is inverted and passes. `git -C source/svc-d push` is held for
  stream D, never stream A.
- **Problem 3:** `TestTwoSessionsWatchOneArtifact` is inverted and passes in both orders,
  and a Bash heredoc case is added. The writer is the author, and the observer's Stop is
  clean.
- **D1–D14:** each has a test that failed first and now passes. The worker reports cite the
  tests.
- **The user's decisions:** 1B, 2B, 3A+3B, one branch, the journal owning the facts, and the
  fixes for rounds 2 and 3 are all honoured.
