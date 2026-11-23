---
type: worklog
title: "Worklog: journal.py split into a package of modules (#61)"
created: 2026-11-23
updated: 2026-11-23
tags:
  - worklog
  - shipgate
  - journal
status: implementing
prd: none — scoped change (#61); the issue body and the lead's brief hold every requirement
related:
  - "../adr/0027-journal-py-is-an-entry-point-over-a-package.md"
---

# Worklog: journal.py split into a package of modules (#61)

Issue #61, wave 2 of #37; it refers to #48 and does not close it. `shipgate/scripts/journal.py` (7,826 lines at
`9785e1d`) becomes an entry point over the package `shipgate/scripts/_journal/`. The change
is a pure move: every command, option, exit code, output byte and path stays the same, and
no file under `shipgate/hooks/` changes. ADR 0027 holds the layout and its reasons.

A design session wrote this page and a fresh session builds it. Start the build from
`python3 shipgate/scripts/journal.py handoff --stream chore/61-journal-package`. Nothing
else may change `journal.py` or `test_journal.py` while this stream is open.

---

# Design

## Approach

Move each top-level statement of `journal.py`, unedited, into one of 22 modules. The
modules follow a fixed layer order: each one imports only from the modules before it, so
there is no import cycle. `journal.py` keeps its path. It loads the package by path under a
name no other load uses, and copies every top-level name into its own namespace. So the
hooks, the skills, shipgate-hud and the tests see the same script and the same module
attributes as before.

The core trade-off: 22 small modules, against 7 coarse ones. The file's 16 sections call
each other in every direction, so any split must move about 70 shared helpers and constants
down to a common layer. Once they move, most of the file's own sections can stay whole as
modules. That gives files of 64 to 978 lines that a reviewer can scope a change to.

## Clarify: no PRD

The issue and the lead's brief state every requirement and every constraint. Exploration
found no user-visible scope, no schema change and no unknown that only the user can
answer. A PRD would repeat the issue, so this stream has none. Each routine decision is a
`gate-decision` and is listed below. The one escalation is the version, which is a release
to installed copies (config **Autonomy**, extra escalations).

## Decisions made alone (executive, vetoable)

| Decision | Choice | Why |
|---|---|---|
| Explorer fan | none | An AST and `symtable` pass over the file gives the definition list, the reference graph and the names the tests reach, exactly. |
| PRD | none | See above. |
| Package name | `scripts/_journal/` | Private to the scripts, like `_config.py`. A `journal/` directory would shadow `journal.py` for any importer with `scripts/` on its path. |
| Module list | 22 modules, ADR 0027 | Most are one section of the old file; the shared statements move down. |
| Entry mechanism | load by path, fresh per load | Works under `-P` and `-I`; keeps the copy test of `test_hooks.py` green; keeps per-load module state. |
| Edited lines | the four `__file__` readers only | Three gain one `.parent`; `_journal_prefix` names `journal.py` beside the package, so the printed path is unchanged. |
| Test split | second commit of this PR | One freeze of `test_journal.py`, one review, one publish approval. The fallback is below. |
| Two comments in `signals.py` | name the new home | They point a reader at `journal.py` for code that moved. |
| Hook files | none changed | No hook reads code that moves; `_common.run_journal` runs the same path. One comment, `hooks/_nudge.py` line 17, still names "journal.py's NUDGE_EVENTS" (now in `_journal/vocab.py`); a comment-only hook edit is left for a later change (a note to the lead). |
| #48's second idea | not in scope | Starting `pre_tool_use.py` as a module is a hook change; a note goes to the lead (its no-op path: 41.7 ms median, of which 6.6 ms is the compile of its 1,832 lines; bare Python 24.1 ms). |
| No-cache cost | accepted, documented | About +7 ms per journal run where Python cannot write bytecode, against about −28 ms in the default case (the design's estimate; T013 measured about +5 ms and −34 ms); the CHANGELOG names it and `PYTHONPYCACHEPREFIX`. |
| #48 | stays open (the user's ruling, seq 2413–2415) | #61 ships the faster start and refers to #48: the PR body and the CHANGELOG say `Refs #48`, never `Closes` or `Fixes`. After the merge the lead retitles #48 for what remains (see "Release note for the lead"). |

**Test split fallback.** If the build session passes the context nudge before T016, it
stops after T015, files a follow-up issue for the test split, and records a `deviation`.

## Questions for the user (answered)

- **Version.** Answered by the user: 0.30.1 (a patch bump). The shipped file layout changes
  and the start gets faster; no command or output changes.
- **Layout.** Answered by the user: 22 modules, ADR 0027 as written; the no-cache +7 ms
  stays accepted and documented. The design is accepted with no veto.
- **#48.** Answered by the user: it stays open (see the decision table).

## Release note for the lead

After the merge: retitle #48 for what remains (the compile of `hooks/pre_tool_use.py` on
every Bash call, and recorder case 3, which T013 measured at 195.4 ms, under its 200 ms
budget by less than 5 ms), and add a comment to #48 with the T013 numbers from "The start"
below.

**The release check** (the pre-mortem's mitigation): after the tag and the plugin update,
run `python3 <installPath>/scripts/journal.py vocab` from the updated install and expect
exit 0. An install without `_journal/` exits 1, and then every journal run fails. The
release does not count as done before this check passes.

## Architecture

```
scripts/journal.py            entry point: loader, namespace copy, main guard
scripts/_journal/__init__.py  imports the 22 modules in layer order; names()
scripts/_journal/
  vocab  plugin  text                      leaves (vocab is imported by text)
  project  store  sessions  approval
  fold  artifacts  shapes  gates  append
  status  reply  check  position  handoff
  closeout  stats  doctor  transfer  cli   cli imports every command module
```

The module table, with what each module owns, is in ADR 0027. Imports are relative
(`from .store import read_events`). No module has `if __name__ == "__main__"`, and the
package has no `__main__.py`.

## The contract that must not change

- **The CLI.** Every subcommand (19), every option, every exit code (0–6), every byte of
  stdout and stderr, and every path printed in a command (`python3 '<abs>/journal.py' --db
  …`). The hooks, the skills and shipgate-hud depend on these.
- **The module surface.** Each test module loads `journal.py` by path under its own name.
  Every non-dunder attribute of the old module must exist on the new one. The tests reach
  74 of them:
  - `test_attribution.py`: `Event artifact_authors claim_of parse_actor`
  - `test_closeout.py`: `CLOSEOUT_HEADER CloseoutRule GATE_WORDS GENERAL_WORDS NO_COMMAND
    _option_label _pr_url_key closeout_rules forge_from_config forge_from_url
    merge_evidence observe_script parse_base parse_first_parent parse_forge_prs
    parse_merged parse_refs parse_worktree_files parse_worktrees read_observed reply_word`
  - `test_hooks.py`: `Event NUDGE_EVENTS _reply_failure_lines artifact_authors`
  - `test_journal.py`: `DORMANT_DAYS DecisionSource EVENT_SHAPES EVENT_VOCABULARY Event
    LAST_CHECK_KEY NO_COMMAND PAYLOAD_CAP_BYTES PHASE_OF_EVENT PHASE_ORDER TERMINAL_TYPES
    UsageError _ADR_STATUS_RE _matches_glob _render_count_line _render_decision
    _render_feature _set_meta _suggest _tokens_label brief_counts build_handoff
    build_status classify_artifact commit_authorization config_candidates connect
    current_phase event_session get_args is_location_key nested_branch_match
    nested_live_matches parse_build_plan parse_data_argument parse_handoff_threshold
    parse_ticked_tasks phase_marks publish_authorization render_findings render_handoff
    render_open_stream render_status request_session stop_gate_trace stream_lifecycle
    user_go utc_now`
  - `test_signals_trace.py`: `normalize_payload`
- **No patch reaches a moved function through `journal`.** No test assigns, deletes or
  patches an attribute of the loaded module today (AST pass, 2026-11-23). The suite's five
  patches target `_common`, `pre_tool_use`, `sys` and `subprocess`. A future test patches
  the owning module: `J._package.<module>.<name>`.
- **Two copies in one process.** `test_hooks.py` `TestPrintedGoRequestsRunAsPrinted` loads
  a copy of `scripts/` from a path with spaces in the process that already loaded the
  original. The copy must print its own path. A normal `import _journal` fails this.
- **Per-load state.** `_sidecar_version_warned` (the one `global`), `_hooks_common` and
  `_config` are per load today, and stay per load.

## How the build proves "no behaviour change"

Four checks, each run by the build and recorded in the Notes:

1. **The suite, unchanged.** Commit 1 changes no file under `shipgate/tests/`
   (`git diff --stat origin/main -- shipgate/tests` is empty), and the suite passes with
   the same counts as before the move. `test_hud_contract.py` already compares the
   `position --json` output with the HUD's golden file byte for byte.
2. **Moved, not edited** (`moved_check.py`, appendix A). Every top-level statement of the
   old file appears exactly once in the package with identical source text. The only
   edits are the four `__file__` lines, each by its one allowed replacement. A module holds
   nothing else but its docstring, `from __future__ import annotations` and imports. The
   relative-import graph has no cycle. Every non-dunder attribute of the old module exists
   on the new entry module with the same kind; constants compare equal.
   Bytecode equality is not used as proof: the compiler emits a different, equivalent load
   for a name bound by an import statement (`X.search(…)` with `X` imported loads the
   attribute without the method flag). Source equality is the proof.
3. **CLI bytes** (`compare_cli.py`, appendix B). The old script (`git show
   9785e1d:shipgate/scripts/journal.py`, run from a scratch copy of the old `scripts/`) and
   the new one run back to back on fresh copies of one fixture journal, with a fixed
   environment. The cases: `--help` and every subcommand's `--help`, usage errors, `vocab`
   and each `vocab --shape`, `status` in four forms, `streams` in four forms, `log`,
   `stats`, `doctor`, `export`, `session --get`, `sweep`, and per stream `status --branch`,
   `position` (text and JSON), `handoff` (text and JSON), `log --stream`, `closeout`,
   `authorize` for both gates and `nudge`; per session `check`, `status --session` and
   `reply`; and writes (`init`, valid and refused `append`, `append --batch` with a bad
   line, `session --set`, `check --record`) compared by the db's rows with `ts` masked.
   The only substitution: each script's own path becomes `<JOURNAL>`. Zero differences.
4. **Entry cases.** Same bytes as the old script for `vocab` and `status --all` under
   Python 3.9 (`/usr/bin/python3`, 3.9.6), `PYTHONSAFEPATH=1`, `-I`, a cwd outside the
   project, a plugin path with spaces, a symbolic link to `journal.py`, and a read-only
   copy with no `__pycache__`. A copy with no `_journal/` exits 1 with `error: cannot load
   <dir> (shipgate install incomplete): …`. `python3 -m _journal` with `scripts/` on the
   path runs nothing.

## The start (#48)

The four cases of T017 in #22, 20 runs each, wall time of the hook process, measured with
`bench.py` (appendix C) on the build machine, Python 3.15.2. Runs interleave the plugin
copies, so drift hits each copy alike.

Measured by the build session (T013) on 2026-11-23, against the built tree: the old plugin
at `9785e1d` and the new one, each a scratch copy. `python3 -c pass` took 20.3 ms. Median /
worst, ms:

| Case | Budget (median) | Old | Split, warm cache | Split, path with spaces |
|---|---|---|---|---|
| 1 Recorder, project with no sidecar | 60 | 26.9 / 29.8 | 26.6 / 28.5 | 26.8 / 29.3 |
| 2 Recorder, journaled, no marker, long prompt | 60 | 34.3 / 38.2 | 34.8 / 38.2 | 34.7 / 38.9 |
| 3 Recorder, marker and open request (`reply`, then `append --batch`) | 200 | 268.1 / 280.7 | 195.4 / 247.7 | 194.0 / 206.0 |
| 4 Command gate, held `git commit` | 300 | 173.5 / 183.4 | 137.9 / 146.5 | 137.2 / 144.0 |
| `journal.py vocab` | — | 107.1 / 116.6 | 72.7 / 94.1 | 71.8 / 84.1 |
| `journal.py status --all` | — | 110.5 / 116.9 | 75.0 / 85.0 | 74.9 / 82.1 |

A second warm run of old and split alone (`python3 -c pass` 24.4 ms) gave case 3 270.7 /
279.8 → 195.6 / 214.4 and `vocab` 108.8 / 111.5 → 74.5 / 81.6.

The same plugin copies made read-only (`chmod -R a-w`), with no `__pycache__` anywhere, so
Python can write no bytecode (`python3 -c pass` 24.8 ms; still no `__pycache__` after the
runs):

| Case | Old, read-only | Split, read-only |
|---|---|---|
| 1 | 30.4 / 39.4 | 29.4 / 39.8 |
| 2 | 34.9 / 45.0 | 34.7 / 42.1 |
| 3 | 266.7 / 301.5 | 281.3 / 336.4 |
| 4 | 175.0 / 195.5 | 182.7 / 203.2 |
| `vocab` | 108.1 / 120.1 | 113.1 / 129.6 |
| `status --all` | 110.0 / 129.3 | 115.2 / 142.3 |

The design session's prototype numbers (2026-11-23) were within a few ms of these: `vocab`
104.6 → 76.6 ms warm and 109.3 → 116.8 ms read-only; case 3 263.0 → 204.9 ms.

What this shows:

- With a bytecode cache, one journal run starts about 34 ms faster: the compile of the one
  file is gone. Case 3 runs the journal twice and drops about 73 ms; case 4 drops 36 ms.
- Cases 1 and 2 run no journal and change by less than 1 ms: no hook file changed.
- **Case 3 now meets its budget on this machine**: 195.4 and 195.6 ms medians in two runs,
  against 200 ms. The margin is under 5 ms, and the design session's prototype measured
  204.9 ms, so the gap is small either way. A recorder with one journal run instead of two
  (a hook change) or lazy imports per subcommand (an edit of `cli.py`) would widen it;
  neither is in this change.
- **Without a bytecode cache the split is slower**: about 5 ms per journal run (`vocab`
  108.1 → 113.1 ms), and case 3 gains 14.6 ms. Python then compiles 23 files instead of
  one. This applies to a read-only install and to a user who sets
  `PYTHONDONTWRITEBYTECODE=1`. `PYTHONPYCACHEPREFIX` pointing at a writable directory
  restores the gain. The plugin cache and a `directory` marketplace checkout are writable,
  so the default case gets the cache.

**#48 stays open** (the user's ruling). This change ships the faster start and refers to
#48 without closing it. T013 measures the same cases again and records both tables here;
the CHANGELOG gives the numbers and the no-cache cost, with `Refs #48`. The lead then
retitles #48 for the remaining gap (see "Release note for the lead").

## Assignment

The exact module of every top-level statement of `journal.py` at `9785e1d`. Each line is
`<module> <items>`; an item `@a-b` takes every top-level statement that starts in lines
a–b (imports and the module docstring excluded); a name takes the statement that defines
it. A later line overrides an earlier one. The first appearance of a module fixes the
layer order. The final `if __name__ == "__main__"` becomes the entry point's own.

```
vocab @36-636
plugin _load_hooks_common _hooks_common journaled_root SIDECAR_RELPATH DEFAULT_DB_RELPATH _load_config_module _config
text
project @637-815
store @816-1103
sessions parse_actor appending_session recorded_by_for current_session set_current_session
approval @1310-1500
fold @2346-2698
artifacts @3466-3800
shapes @1520-1853
gates @1104-1309
gates @1854-2023
append @2024-2345
status @2699-2783
reply @2784-3212
status @3213-3465
check @3801-4199
position @4200-4846
handoff @4847-5268
closeout @5269-6154
stats @6155-6505
doctor @6506-6774
transfer @6775-6877
cli @6878-7824
text _one_line _clip _short_ts _in_backticks _string_list _string_or_none _normalized_ref _vocabulary_map _printable
store _parse_ts _seconds_since
sessions _actor_role writer_session binds_session request_session event_session _actor_session NON_BINDING_TYPES NON_BINDING_MARKERS USER_MARKERS RETIRED_READ_MARKER _is_seq
plugin plugin_version _journal_prefix _journal_command _suggest _request_command _db_file NO_COMMAND closeout_command CONFIRMING_QUESTION_PLACEHOLDER GATE_QUESTION_PLACEHOLDER
vocab GATE_WAIVED CLOSEOUT_QUESTION_PLACEHOLDER CLOSEOUT_CHOSEN_PLACEHOLDER SIGNALS_MISSING_KIND SIGNALS_MISSING_NOTE
fold folded_phase _last_phase_spelling _position_dispositions _disposition_labels PositionDisposition _finding_key _newest_string
gates _request_command_of MR_OPENED_REFUSAL _validate_mr_opened
artifacts _resolve_artifact _is_safe_ref _safe_ref _committed_refs _event_bound_worklog _GLOB_MAGIC_RE _worklog_home_dirs _free_slug_named_worklog _names_artifact _slug_names_file _has_flow_event worklog_owners _slug_from_artifact POSITION_ARTIFACT_EVENTS
project _config_label config_candidates _config_files
```

Each module file: a one-line docstring (the "Owns" column of ADR 0027), `from __future__
import annotations`, the standard-library imports its statements use, then one `from .<m>
import …` line per module it reads from, in layer order, then its statements in their old
order with the comment lines above each. The four `__file__` edits:

| Old text | New text (in `plugin.py`) |
|---|---|
| `Path(__file__).resolve().parent.parent / "hooks" / "_common.py"` | `Path(__file__).resolve().parent.parent.parent / "hooks" / "_common.py"` |
| `Path(__file__).resolve().parent / "_config.py"` | `Path(__file__).resolve().parent.parent / "_config.py"` |
| `Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"` | `Path(__file__).resolve().parent.parent.parent / ".claude-plugin" / "plugin.json"` |
| `quote(str(Path(__file__).resolve()))` | `quote(str(Path(__file__).resolve().parent.parent / "journal.py"))` |

The design session generated this layout in a scratch copy and ran the whole suite on it
(see the Notes). The resulting files: vocab 574, plugin 142, text 64, project 240, store
227, sessions 187, approval 158, fold 461, artifacts 506, shapes 346, gates 421, append
299, status 318, reply 401, check 320, position 427, handoff 385, closeout 901, stats 360,
doctor 282, transfer 113, cli 978 lines; `__init__.py` 20 and `journal.py` 55 (the prototype's
counts; the build's modules are 2 to 6 lines longer each, `__init__.py` 23 and `journal.py`
50; see the T003–T010 note).

## The entry point

```python
#!/usr/bin/env python3
"""<the old module docstring, unchanged>"""

import os
import sys


def _load_package():
    """The modules of `_journal/`, loaded under a name no other load uses (ADR 0027)."""
    import importlib.util

    directory = os.path.join(os.path.dirname(os.path.realpath(__file__)), "_journal")
    index = 0
    while f"_shipgate_journal_{index}" in sys.modules:
        index += 1
    name = f"_shipgate_journal_{index}"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(directory, "__init__.py"),
        submodule_search_locations=[directory],
    )
    try:
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    except (OSError, ImportError) as exc:
        sys.exit(f"error: cannot load {directory} (shipgate install incomplete): {exc}")
    return package


_package = _load_package()
globals().update(_package.names())


if __name__ == "__main__":
    sys.exit(main())
```

`_journal/__init__.py` imports the modules in layer order (`from . import vocab, plugin,
…, cli`), keeps them in `_LAYERS`, and defines `names()`: the union of `vars(module)` over
`_LAYERS`, dunder names excluded.

## Test split (commit 2)

`test_journal.py` keeps its helpers, `JournalTestCase`, the shared fixtures and the tests
of the store, the append path and the CLI basics. Each new module imports what it needs
from `test_journal` and nothing from another new module. `test_closeout.py` and
`test_trace.py` keep their `from test_journal import …` lines unchanged. Never import a
`TestCase` subclass that has tests into another module: unittest would run it twice.
Same rule format as the assignment above, over `test_journal.py` at `9785e1d`:

```
test_journal @1-200 TestInit TestAppend TestActorCanon TestConcurrentAppend TestArtifactDedupe TestAppendBatch TestPayloadCap TestLogAndStreams TestSidecarVersion TestExportImport TestWorkStreamRecognition TestVocabCommand TestDbResolution
test_journal_shapes TestShapeValidation TestIsLocationKey TestTerminalPayloads
test_journal_gates TestGateClarifyPassed TestGateTaskDone TestGatePhaseEntered TestImpliedPhase TestGateReviewVerdict TestGateMrOpened TestGateMisc
test_journal_approval TestPublishAuthorization TestUserGo TestGoInStatusAndPosition TestApprovalPathPins TestGoRequested TestReplyWitnessed TestGoDoesNotBind TestReadGoIsRetired TestReplyPlan TestAuthorize TestStatsGoMarkers TestRequestMarker TestApprovalRowsNameTheirOwnSession
test_journal_status TestStatus TestTerminalAndDormant TestCurrentPhase TestPhaseMarks TestBriefRendering TestSessionMatch TestSessionlessAppend TestBranchOrdering TestDecisionRendering TestLedgerInStatus TestOwnershipMark TestBoundBrief TestStreamsOpen TestBriefPins
test_journal_check TestCheck TestRenderFindings TestSuggestedCommand TestParseTickedTasks TestMatchesGlob TestParseBuildPlan
test_journal_position POSITION_KEYS_0_20_0 POSITION_VERDICT_KEYS_0_20_0 POSITION_KEYS POSITION_WORKLOG TestPosition
test_journal_handoff TestHandoff TestNudge TestHandoffCloseOut
test_journal_doctor TestDoctor TestStats
test_journal WORKLOG_TEMPLATE PIN_NOW PIN_STREAM _pin_rows PIN_BLOCK PIN_HANDOFF _PinStream _StreamRows HANDOFF_WORKLOG HANDOFF_CONFIG ADR_PROPOSED ADR_ACCEPTED
```

Test counts: test_journal 150, shapes 58, gates 89, approval 93, status 164, check 71,
position 51, handoff 46, doctor 49; 771 in all. The relative graph has no cycle (every new
module reads only `test_journal`).

## Files touched

- New: `shipgate/scripts/_journal/__init__.py` and 22 modules.
- Rewritten: `shipgate/scripts/journal.py` (entry point, 50 lines).
- Comments only: `shipgate/scripts/signals.py` lines 59 and 446 name
  `_journal/plugin.py` and `_journal/artifacts.py`.
- Docs and release: `shipgate/README.md` line 141 (one clause: the code lives in
  `scripts/_journal/`, ADR 0027), `shipgate/CHANGELOG.md` (0.30.1),
  `shipgate/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (0.30.1,
  pending the user's answer), this worklog, ADR 0027.
- Commit 2: `shipgate/tests/test_journal.py` split into 9 files, and the new
  `shipgate/tests/test_journal_layout.py`.
- Not touched: anything under `shipgate/hooks/`, `shipgate/skills/`, `shipgate-hud/`.

## Risk ranking and the pre-mortem

`signals.py hotspots` over the files the plan changes (source `graph`): `README.md` churn
top, fix high; `journal.py` churn top, fix high, fan-in low; `test_journal.py` churn top,
fix high, fan-in high; `signals.py` churn top, fix low. The tests that pin `journal.py`'s
behaviour before the change are the unchanged suite and `compare_cli.py`; `test_journal.py`
moves only in commit 2, after commit 1 is proven with it unchanged.

Pre-mortem: "this shipped and caused an incident — why?" The likeliest cause is an
installed copy that lacks `_journal/`. Every journal run would exit 1, the recorder would
record no go, and the command gate would hold every commit. Mitigations: the entry point
names the missing directory (T011); the test copies of `scripts/` in `test_hooks.py`
already copy the whole directory; and **the lead's release check** runs `python3
<installPath>/scripts/journal.py vocab` from the updated install and expects exit 0 before
the release counts as done.

## CLAUDE.md compliance

- Python 3.9 compatible, standard library only; the entry point uses nothing newer.
- Tests run with `python3 -m unittest discover -s shipgate/tests` from the repo root,
  never `-t .`.
- No hook file changes, so one publish approval covers commit, push, PR, merge and tag.
- Version in `plugin.json` and `marketplace.json` in the same change; release notes only
  in the CHANGELOG; tag `shipgate--v0.30.1` after the merge (the lead).
- Public repo: grep the diff for the private project names, tracker ids and paths before
  finishing; a hit is a blocker.

---

# Build Plan

Tasks are ordered by dependency. Each code task leaves the suite green and is checked as
"moved, not edited" by `moved_check.py` in its incremental form: the statements of the
package plus the statements still in `journal.py` equal the old file's statements. Keep
the old file and the tools in the session scratchpad, never in the repo.

"The suite passes" means the whole suite at T003, T010, T015 and T019. T004–T009 may run
only the seven test modules that load `journal.py` (see the Notes), since a full run takes
11 to 14 minutes.

Two commits, made only after the review's ready verdict and the user's go: commit 1 holds
everything except `shipgate/tests/` (T003–T015); commit 2 holds the test files
(T016–T019). Commit 1's tree is the one T015 proved.

## Setup

- [x] T001 — Baseline: write the old file and the old `scripts/` to the scratchpad (`git show 9785e1d:…`); run the suite and record `Ran N`, skips and failures; copy the repo's journal into the scratchpad with SQLite's backup API as the fixture for `compare_cli.py`; run `bench.py` on a copy of the old plugin — file(s): this worklog (Notes) — done when: the suite counts and the baseline table are in the Notes.
- [x] T002 — Tools: write `moved_check.py`, `compare_cli.py` and `bench.py` from the appendices into the scratchpad; give `moved_check.py` its incremental form (count the remaining non-header statements of `journal.py` as moved, ignore the loader lines) — file(s): scratchpad only — done when: `moved_check.py` on the untouched tree reports every statement in place and no failure.
- [x] T003 — Skeleton: `_journal/__init__.py` with an empty `_LAYERS` and `names()`; in `journal.py`, the loader block after its imports (`_package = _load_package()`, `globals().update(_package.names())`) — file(s): `shipgate/scripts/journal.py`, `shipgate/scripts/_journal/__init__.py` — done when: the suite passes with the T001 counts.

## The move (commit 1), in layer order

Each task: create the modules from the Assignment, delete their statements from
`journal.py`, add them to `__init__.py` and `_LAYERS`, run `moved_check.py`, run the suite.

- [x] T004 — `vocab`, `plugin`, `text`; the four `__file__` edits land here — file(s): `_journal/{vocab,plugin,text}.py`, `journal.py` — done when: `moved_check.py` OK (4 edits) and the suite passes.
- [x] T005 — `project`, `store`, `sessions` — done when: `moved_check.py` OK and the suite passes.
- [x] T006 — `approval`, `fold`, `artifacts` — done when: `moved_check.py` OK and the suite passes.
- [x] T007 — `shapes`, `gates`, `append` — done when: `moved_check.py` OK and the suite passes.
- [x] T008 — `status`, `reply`, `check` — done when: `moved_check.py` OK and the suite passes.
- [x] T009 — `position`, `handoff`, `closeout` — done when: `moved_check.py` OK and the suite passes.
- [x] T010 — `stats`, `doctor`, `transfer`, `cli`; `journal.py` becomes the entry point of the Design section (its old imports go) — done when: `moved_check.py` OK in its final form (no statement left in `journal.py`; extra names only `_load_package`, `_package`) and the suite passes.

## Proof and measurement

- [x] T011 — Entry cases of check 4 (3.9.6, `PYTHONSAFEPATH=1`, `-I`, cwd elsewhere, spaces, symbolic link, read-only copy, no `_journal/`, `python3 -m _journal`) — file(s): Notes — done when: each case gives the recorded result.
- [x] T012 — `compare_cli.py` old against new on the fixture journal — file(s): Notes — done when: 0 differing cases, with the case and stream counts in the Notes.
- [x] T013 — `bench.py`, 20 runs, old against new with warm caches, then both read-only (copies with `chmod -R a-w` and no `__pycache__`) — file(s): this worklog (The start), ADR 0027 (Consequences) — done when: both tables in "The start" are replaced by the build's numbers (measure and record only; #48 stays open, so no close rule and no `gate-decision` about closing it).

## Docs and release

- [x] T014 — `signals.py` comments (lines 59, 446); `README.md` line 141; `CHANGELOG.md` 0.30.1 entry (the move, the numbers of T013, the no-cache cost and `PYTHONPYCACHEPREFIX`, no command or output change, no hook change, `Refs #48`, never `Closes` or `Fixes`); version 0.30.1 in `plugin.json` and `marketplace.json` (the user's answer) — done when: `test_prose.py` passes and the privacy grep finds nothing.
- [x] T015 — Commit-1 verify: the suite with the T001 counts; `git diff --stat origin/main -- shipgate/tests` empty; `moved_check.py` OK; `compare_cli.py` 0 differing — done when: all four hold in one fresh run, recorded as one `verify-run`.

## The test split (commit 2)

- [x] T016 — Split `test_journal.py` by the Test split table — file(s): `shipgate/tests/test_journal*.py` — done when: the suite passes.
- [x] T017 — Prove the test split: the same set of `Class.method` test ids as at T015, the same `Ran`/skip counts, and the source check of `moved_check.py`, adapted to compare the old `test_journal.py` with the 9 new files (imports excluded) — done when: all three hold.
- [x] T018 — `shipgate/tests/test_journal_layout.py`: each module's relative imports name only modules earlier in `_LAYERS`; no absolute `_journal` import; no `__main__` guard and no `__main__.py`; every `.py` file of `_journal/` is in `_LAYERS` — done when: it fails on a scratch copy with an injected backward import, and passes on the tree.
- [x] T019 — Final verify: the full suite (T015 count plus T018's tests), `moved_check.py`, `compare_cli.py` — done when: one fresh run passes, recorded as `verify-run`.

## Review round 1 fixes

- [x] T020 — Fix the round-1 findings: `import unittest` in the four split test files whose main guard needs it; the docstrings of the eight split test files wrapped to 92 columns; `test_journal_layout.py` also checks that `__init__.py` loads the modules in `_LAYERS` order; the docs (CHANGELOG `__file__` wording, ADR 0027 line counts and decision 5, the worklog decision table, line counts and the release check in "Release note for the lead") — file(s): `shipgate/tests/test_journal_*.py`, `shipgate/CHANGELOG.md`, ADR 0027, this worklog — done when: the full suite passes, `tests_moved_check.py` OK, and no unresolved global name in the split test files.

## Traceability

- #61 "pure move, suite passes unchanged" → T003–T010, T015
- #61 "journal.py stays the entry point; hooks and skills change nothing" → T010, T011, T012
- #61 "read-only install, no bytecode write needed" → T011, T013
- #61 "test file split along the same lines" → T016–T018
- #48 (refers to, stays open) "T017 cases measured again" → T013; `Refs #48` in the CHANGELOG → T014
- ADR 0027 import direction → T004–T010, T018

## Deviations & notes

- 2026-11-23 — Design session. Prototype: the Assignment generated in a scratch copy of the
  tree; `moved_check.py` OK (461 statements, 4 `__file__` edits, 22 modules, 489 names
  compared, extra names `_load_package`, `_package`). The whole suite on the prototype and
  on an unchanged copy of the tree, from the repo root of each copy: `Ran 1699 tests`, `OK
  (skipped=15)` on both, with no test file changed. A full run takes 11 to 14 minutes on
  the build machine under load, so T004–T009 may run the seven test modules that load
  `journal.py` (`test_journal`, `test_closeout`, `test_attribution`, `test_hooks`,
  `test_trace`, `test_signals_trace`, `test_hud_contract`), and T003, T010, T015 and T019
  run the whole suite.
- 2026-11-23 — Design session. `compare_cli.py` on the prototype against the unchanged
  tree, on a copy of this repo's own journal (2,385 events, 49 streams): 596 cases, 0
  differing. Negative control: one added space in the count line of `status.py` showed as
  a difference; the write case compared all 2,386 rows.
- 2026-11-23 — Design session. Entry cases on the prototype: `vocab` gave the same bytes
  as the old script under `/usr/bin/python3` (3.9.6), `PYTHONSAFEPATH=1`, `-I`, a plugin
  path with spaces and a read-only copy. Apple's 3.9.6 writes its bytecode under
  `sys.pycache_prefix`, not beside the source.
- 2026-11-23 — The one `ResourceWarning: unclosed database` in the suite output appears
  on the unchanged tree too; it predates this change (a note to the lead, not fixed here).
- 2026-11-23 — Build session, T001. Baseline on the unchanged tree, from the repo root:
  `Ran 1699 tests in 869.464s`, `OK (skipped=2)`. The design session saw 15 skips in its
  environment; 2 is the count this build compares against. The two `ResourceWarning` lines
  appear here too. Fixture: a copy of this repo's journal made with SQLite's backup API,
  2,427 events, 49 streams. `bench.py` on a copy of the old plugin, Python 3.15.2, median /
  worst ms: case 1 29.0 / 47.7, case 2 37.5 / 63.3, case 3 286.5 / 426.6, case 4 180.8 /
  292.0, `vocab` 111.7 / 160.2, `status --all` 114.7 / 195.1; `python3 -c pass` 25.7 ms.
- 2026-11-23 — Build session, T002. The tools are rebuilt in the session scratchpad from
  appendices A–C, by extraction from this page, not by retyping. A generator writes the
  modules from the Assignment, so the build types no moved code (a `gate-decision`: no
  workers). `moved_check.py` gains the incremental form: a statement still in `journal.py`
  counts as moved unedited, the loader lines are ignored, and the edit count must be 4
  only when `journal.py` holds no statement. On the untouched tree: 461 statements, 461
  still in `journal.py`, OK. On a dry run of the full move: 461 statements, 4 edits, 22
  modules, 489 objects compared, extra names `_load_package`, `_package`, OK; one injected
  line in `status.py` fails it.
- 2026-11-23 — Build session, T003–T010. Each task ran the generator for the next modules
  of the layer order, then `moved_check.py`, then a test run. T003 and T010 ran the whole
  suite: `Ran 1699 tests`, `OK (skipped=2)` both times. T004–T009 ran the seven test
  modules that load `journal.py`, one process each, in parallel: 771 + 127 + 38 + 244 +
  43 + 18 + 6 = 1,247 tests, OK at every step, the same counts as on the T003 tree.
  `moved_check.py` statements still in `journal.py` after each task: 461, 356, 308, 242,
  199, 155, 59, 0; the 4 `__file__` edits from T004 on. The final form: 461 statements, 4
  edits, 22 modules, 489 objects compared, extra names `_load_package`, `_package`. The
  generated files have 8,214 lines, headers included; each module is 2 to 6 lines longer
  than the prototype's count, from the blank lines between imports. A `symtable` pass
  finds no unused import and no unbound global name in the 22 modules. The one
  backward-looking name the generator saw, `main` in `closeout.py`, is a local variable
  of `build_closeout`, not `cli.main`.
- 2026-11-23 — Build session, T011. All entry cases give the same bytes as the old script
  for `vocab` and `status --all` on the fixture: `/usr/bin/python3` 3.9.6 (cwd in a
  scratch directory and in the project), `PYTHONSAFEPATH=1`, `-I`, `-P` (3.15.2), cwd `/`,
  a plugin path with spaces, a symbolic link to `journal.py`, and read-only copies with no
  `__pycache__`, with and without `PYTHONDONTWRITEBYTECODE=1`, on 3.9.6 and 3.15.2. The
  read-only copies still hold no `__pycache__` afterwards. A copy with no `_journal/`
  exits 1 with `error: cannot load <dir> (shipgate install incomplete): …` and no stdout.
  `python3 -m _journal` with `scripts/` on the path exits 1 with `No module named
  _journal.__main__` and runs no command.
- 2026-11-23 — Build session, T012. `compare_cli.py` on a copy of the built tree against
  the old script: 596 cases, 49 streams, 0 differing. Negative control: one added space in
  the count line of `status.py` made 58 cases differ.
- 2026-11-23 — Build session, T013. The tables in "The start" are the build's numbers.
  Case 3 now measures 195.4 and 195.6 ms in two runs, under its 200 ms budget by less
  than 5 ms; the prototype measured 204.9 ms. #48 stays open (the user's ruling); this is
  a note to the lead, who retitles #48 after the merge. The no-cache cost measures about
  5 ms per journal run, not the 7 ms the design recorded; the CHANGELOG gives the build's
  number.
- 2026-11-23 — Build session, T014. The CHANGELOG entry mentions the test split, which
  lands in commit 2 of the same PR: the entry describes the release, not one commit.
- 2026-11-23 — Build session, T016. The generator splits `test_journal.py` by the Test
  split table; each new file has a shebang, a docstring, `from __future__ import
  annotations`, the imports its statements use, its statements, and the main guard of
  the old file. `import re` is dropped from `test_journal.py`: no statement left there
  uses it (an import, outside the source check). Line counts: test_journal 1,671, shapes
  534, gates 769, approval 1,237, status 1,517, check 787, position 644, handoff 529,
  doctor 631.
- 2026-11-23 — Build session, T017–T018. The split keeps the 1,699 `Class.method` test ids
  of the old tree, with no duplicate, and the counts `Ran 1699`, `skipped=2`. The source
  check over the old `test_journal.py` and the nine files: 94 statements, OK.
  `test_journal_layout.py` reads the package with `ast` and imports nothing. It has three
  tests: the tree holds the rules, `_LAYERS` names each module file once, and a scratch
  copy with each rule broken reports each break. On a scratch copy of the tree with `from
  .handoff import render_handoff` added to `store.py`, it fails with `store: imports
  handoff, which is not earlier`.

## Review round 1

Run `wf_83ca04b0-f69`: three lenses (correctness, conventions+design, simplicity+security),
`verify: high-only`. Counts: 20 found, 18 after dedupe, 8 candidates, 0 refuters (no
BLOCKER or HIGH), 8 survivors, 0 killed. The briefed security review read 41 of 41
changed files and found nothing. Verdict: not ready.

- F1 MEDIUM `shipgate/tests/test_journal_position.py:644` — four split test files (doctor, gates, handoff, position) call `unittest.main()` in their main guard without `import unittest`; fixed in T020 (the generator now reads the main guard's names).
- F2 MEDIUM `shipgate/tests/test_journal_status.py:2` — the new docstrings of the eight split test files ran past 92 columns; fixed in T020.
- F3 MEDIUM `shipgate/docs/adr/0027-journal-py-is-an-entry-point-over-a-package.md:176` — the pre-mortem's release check had no durable home; fixed in T020: "Release note for the lead" now holds it.
- F4 LOW `shipgate/CHANGELOG.md:16` — the CHANGELOG said each `__file__` line gained one `.parent`, but `_journal_prefix` gained two and a path segment; fixed in T020, with the ADR and the worklog.
- F5 LOW `shipgate/docs/adr/0027-journal-py-is-an-entry-point-over-a-package.md:105` — the ADR and the worklog gave the entry point as 55 lines and `__init__.py` as 20; the built files are 50 and 23; fixed in T020.
- F6 LOW `shipgate/docs/prd/journal-package.worklog.md:67` — the decision table gave only the design's no-cache numbers; fixed in T020: it names the T013 measurement too.
- F7 LOW `shipgate/tests/test_journal_layout.py:22` — the layout test never compared `_LAYERS` with the `from . import` order that runs (below the floor, promoted); fixed in T020.
- F8 LOW `shipgate/docs/prd/journal-package.worklog.md:65` — the worklog said no hook file names moved code, but a comment in `hooks/_nudge.py` names `journal.py`'s `NUDGE_EVENTS` (below the floor, promoted); fixed in T020: the row says so, and the comment is a note to the lead.
- F9 LOW `shipgate/docs/prd/journal-package.worklog.md:?` — `moved_check.py` (Appendix A) does not prove that every global name resolves in its new module; deferred: a `symtable` pass proved it for this move (notes, T003–T010), and a permanent test of it is a note to the lead for a new issue.

### Rejected findings

- `shipgate/scripts/journal.py:40` (LOW 60): the loader maps every `ImportError` to "install incomplete"; the entry point is the accepted design, the message form is the hooks' loader's, and a partial install raises `ImportError` too, so the message fits the case it is for.
- `shipgate/scripts/journal.py:46` (LOW 55): a patch on the loaded entry module no longer reaches the moved code; ADR 0027 decision 6 states it, and no test patches.
- `shipgate/scripts/_journal/__init__.py:16` (LOW 55): `names()` lets a later module win a collision; the security review found no name bound to two objects.
- `shipgate/scripts/_journal/plugin.py:130` (LOW 35): moved docstrings still say "this script"; moved text stays unedited.
- `shipgate/scripts/_journal/cli.py:?` (LOW 30): a crash traceback now names a module file; a traceback is no output contract, and the suite and `compare_cli.py` show no change.
- `shipgate/scripts/_journal/__init__.py:7` (LOW 30): the module list appears twice; the layout test now holds the two equal.
- `shipgate/docs/adr/0027-journal-py-is-an-entry-point-over-a-package.md:?` (LOW 25): the package gives a route to journal writes that does not name `journal.py`; ADR 0027 Consequences covers it, and the security review found no new runnable entry.


## Review round 2

One reviewer on the fix diff of T020, all three lenses. Each round-1 finding F1–F8 is
confirmed fixed on evidence: the four `import unittest` lines, the docstrings at 92 columns
or less, the release check in "Release note for the lead", the `__file__` wording against
`_journal/plugin.py`, the line counts against `wc -l`, the T013 numbers, the order check in
`test_journal_layout.py` (a reordered and an extended `from . import` both fail it), and the
`hooks/_nudge.py` row. `tests_moved_check.py` still passes, and each regenerated test file
differs from its pre-fix copy only in the docstring and the `import unittest` line. No code
regression. New findings, all LOW and in the docs except R2-3:

- R2-1 LOW `shipgate/docs/prd/journal-package.worklog.md:68` — the #48 decision row still said case 3 is over 200 ms; fixed in T020: it points to "Release note for the lead".
- R2-2 LOW `shipgate/docs/prd/journal-package.worklog.md:576` — round-1 finding paths mixed repo-root and plugin bases, and F9 named a scratchpad file; fixed in T020: every path starts at the repo root, and F9 names Appendix A.
- R2-3 LOW `shipgate/tests/test_journal_layout.py:84` — no committed negative case proves the order check; deferred: two scratch mutations proved it (round 2), and the self-test is a note to the lead with F9.
- R2-4 LOW `shipgate/docs/prd/journal-package.worklog.md:296` — the module line counts read as the build's; fixed in T020: the text says they are the prototype's.
- R2-5 LOW `shipgate/docs/adr/0027-journal-py-is-an-entry-point-over-a-package.md:176` — the ADR timed the release check "before the tag"; fixed in T020: it runs after the tag, from the updated install.

---

# Appendix A — moved_check.py

The proof of check 2, as the design session ran it on the prototype (final form: no statement left in `journal.py`). T002 adds the incremental form.

```python
#!/usr/bin/env python3
"""Prove a split of journal.py is a pure move (ADR 0027).

usage: moved_check.py OLD_JOURNAL_PY NEW_SCRIPTS_DIR

1. Source: every top-level statement of the old file appears exactly once in the package,
   with identical text; the only edited statements are the four `__file__` lines, each by
   the one allowed replacement. A module holds nothing else but its docstring,
   `from __future__ import annotations` and import statements.
2. Imports: the `from .x import` graph has no cycle, and no module imports `_journal`
   absolutely.
3. Surface: every attribute of the old module exists on the new entry module, and is the
   same kind of object; constants compare equal.
   (Not bytecode: the compiler emits a different, equivalent load for a name bound by an
   import statement, so bytecode equality is no proof. Source equality is.)
Exit 0 when all hold; prints each failure otherwise.
"""
import ast
import importlib.util
import os
import sys
import types

ALLOWED_EDITS = [
    ('Path(__file__).resolve().parent.parent / "hooks" / "_common.py"',
     'Path(__file__).resolve().parent.parent.parent / "hooks" / "_common.py"'),
    ('Path(__file__).resolve().parent / "_config.py"',
     'Path(__file__).resolve().parent.parent / "_config.py"'),
    ('Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"',
     'Path(__file__).resolve().parent.parent.parent / ".claude-plugin" / "plugin.json"'),
    ('quote(str(Path(__file__).resolve()))',
     'quote(str(Path(__file__).resolve().parent.parent / "journal.py"))'),
]
failures = []


def statements(path):
    text = open(path, encoding="utf-8").read()
    tree = ast.parse(text)
    out = []
    for node in tree.body:
        seg = ast.get_source_segment(text, node)
        if getattr(node, "decorator_list", None):
            first = min(d.lineno for d in node.decorator_list)
            lines = text.splitlines(keepends=True)
            seg = "".join(lines[first - 1:node.end_lineno])
            seg = seg[seg.index("@"):] if "@" in seg else seg
        out.append((node, seg))
    return out


def is_header(node, index):
    if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return True
    return isinstance(node, (ast.Import, ast.ImportFrom))


old_path, new_dir = sys.argv[1], sys.argv[2]
pkg_dir = os.path.join(new_dir, "_journal")

# 1. source
old = [seg for i, (n, seg) in enumerate(statements(old_path)) if not is_header(n, i)]
old = [s for s in old if not s.startswith('if __name__ == "__main__"')]
new = {}
edges = {}
for fname in sorted(os.listdir(pkg_dir)):
    if not fname.endswith(".py") or fname == "__init__.py":
        continue
    mod = fname[:-3]
    edges[mod] = set()
    for i, (node, seg) in enumerate(statements(os.path.join(pkg_dir, fname))):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            edges[mod].add(node.module)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            if any(x.split(".")[0] == "_journal" for x in names) or (
                    isinstance(node, ast.ImportFrom) and node.level == 0
                    and (node.module or "").startswith("_journal")):
                failures.append(f"{mod}: absolute import of _journal")
            continue
        if is_header(node, i):
            continue
        new.setdefault(seg, []).append(mod)

edited = 0
for seg in old:
    want = seg
    for a, b in ALLOWED_EDITS:
        if a in want:
            want = want.replace(a, b)
            edited += 1
    where = new.pop(want, None)
    if where is None:
        failures.append(f"missing or edited: {seg.splitlines()[0][:90]}")
    elif len(where) > 1:
        failures.append(f"duplicated in {where}: {seg.splitlines()[0][:90]}")
for seg, where in new.items():
    failures.append(f"added in {where}: {seg.splitlines()[0][:90]}")
if edited != len(ALLOWED_EDITS):
    failures.append(f"expected {len(ALLOWED_EDITS)} __file__ edits, applied {edited}")

# 2. imports: cycles
index, low, stack, on, counter = {}, {}, [], set(), [0]


def strong(v):
    index[v] = low[v] = counter[0]
    counter[0] += 1
    stack.append(v)
    on.add(v)
    for w in edges.get(v, ()):
        if w not in index:
            strong(w)
            low[v] = min(low[v], low[w])
        elif w in on:
            low[v] = min(low[v], index[w])
    if low[v] == index[v]:
        comp = []
        while True:
            w = stack.pop()
            on.discard(w)
            comp.append(w)
            if w == v:
                break
        if len(comp) > 1:
            failures.append(f"import cycle: {sorted(comp)}")


for v in edges:
    if v not in index:
        strong(v)


# 3 + 4. surface and bytecode
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IGNORED = {"co_filename", "co_firstlineno", "co_lnotab", "co_linetable", "co_positions",
           "co_lines", "co_exceptiontable", "co_qualname"}


def same_code(a, b):
    if a.co_code != b.co_code or a.co_names != b.co_names or a.co_varnames != b.co_varnames \
            or a.co_freevars != b.co_freevars or a.co_cellvars != b.co_cellvars:
        return False
    if len(a.co_consts) != len(b.co_consts):
        return False
    for x, y in zip(a.co_consts, b.co_consts):
        if isinstance(x, types.CodeType):
            if not (isinstance(y, types.CodeType) and same_code(x, y)):
                return False
        elif type(x) is not type(y) or x != y:
            return False
    return True


def same_value(a, b):
    """Equal values; a function compares by its qualified name, since each module load
    makes its own function objects."""
    import typing
    if isinstance(a, (types.FunctionType, type)):
        return type(b) is type(a) and a.__qualname__ == b.__qualname__
    if typing.get_origin(a) is not None:
        return typing.get_origin(a) is typing.get_origin(b) and same_value(
            typing.get_args(a), typing.get_args(b))
    if isinstance(a, (tuple, list)):
        return type(a) is type(b) and len(a) == len(b) and all(map(same_value, a, b))
    if isinstance(a, dict):
        return type(b) is dict and list(a) == list(b) and all(same_value(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


o = load(old_path, "old_journal_for_check")
n = load(os.path.join(new_dir, "journal.py"), "new_journal_for_check")
public = lambda m: {k for k in dir(m) if not (k.startswith("__") and k.endswith("__"))}
missing = sorted(public(o) - public(n))
if missing:
    failures.append(f"names gone from the entry module: {missing}")
extra = sorted(public(n) - public(o))
compared = 0
for name in sorted(public(o) & public(n)):
    a, b = getattr(o, name), getattr(n, name)
    kind = lambda v: ("function" if isinstance(v, types.FunctionType) else "class"
                      if isinstance(v, type) else "module" if isinstance(v, types.ModuleType)
                      else type(v).__name__)
    if kind(a) != kind(b):
        failures.append(f"{name}: {kind(a)} became {kind(b)}")
    elif isinstance(a, (types.FunctionType, type)):
        if a.__qualname__ != b.__qualname__:
            failures.append(f"{name}: qualified name differs")
    elif isinstance(a, types.ModuleType):
        if a.__name__ != b.__name__ and not name.startswith("_"):
            failures.append(f"{name}: a different module")
    elif not same_value(a, b):
        failures.append(f"{name}: value differs")
    compared += 1

print(f"statements moved: {len(old)}, __file__ edits: {edited}, modules: {len(edges)}, "
      f"objects compared: {compared}, extra names on the entry module: {extra}")
if failures:
    print("FAILURES:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("pure move: OK")
```

# Appendix B — compare_cli.py

Check 3. OLD_SCRIPT sits in a full copy of the old plugin (`hooks/` beside `scripts/`); PROJECT_DIR is a copy of the tree without `.git`, so `handoff` and `position` find the worklogs. The fixture db is a copy of this repo's journal made with SQLite's backup API.

```python
#!/usr/bin/env python3
"""Byte comparison of journal.py's CLI before and after the split (ADR 0027).

usage: compare_cli.py OLD_SCRIPT NEW_SCRIPT FIXTURE_DB PROJECT_DIR

Runs every case on the old and the new script back to back, each on a fresh copy of
FIXTURE_DB placed in PROJECT_DIR/.claude/, with cwd PROJECT_DIR and a fixed environment.
Compares exit code, stdout and stderr byte for byte after one substitution: each script's
own path becomes <JOURNAL>. A write case also compares the export of the db after the run,
with each row's `ts` masked. A case that differs is run once more (a minute boundary can
move an idle count); a second difference is a failure.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys

old_script, new_script, fixture, project = sys.argv[1:5]
DB = os.path.join(project, ".claude", "shipgate.db")
ENV = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
ENV.update({"COLUMNS": "100", "LC_ALL": "C.UTF-8", "TZ": "UTC",
            "CLAUDE_CODE_SESSION_ID": "cmp-session-1"})


def fresh_db():
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except FileNotFoundError:
            pass
    src = sqlite3.connect(fixture)
    dst = sqlite3.connect(DB)
    src.backup(dst)
    src.close()
    dst.close()


def dump():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT * FROM events ORDER BY seq").fetchall()
    meta = con.execute("SELECT * FROM meta ORDER BY 1").fetchall()
    con.close()
    masked = [tuple("<TS>" if isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+(\+00:00|Z)?", v) else v
                    for v in r) for r in rows]
    meta = [m for m in meta if m[0] not in ("last_check",)]
    return masked, meta


def run(script, args, stdin, write):
    fresh_db()
    r = subprocess.run([sys.executable, script, *args], input=stdin, capture_output=True,
                       cwd=project, env=ENV)
    out = r.stdout.replace(script.encode(), b"<JOURNAL>")
    err = r.stderr.replace(script.encode(), b"<JOURNAL>")
    return (r.returncode, out, err, dump() if write else None)


streams = [s for (s,) in sqlite3.connect(fixture).execute(
    "SELECT DISTINCT stream FROM events ORDER BY stream")]
sessions = [s for (s,) in sqlite3.connect(fixture).execute(
    "SELECT DISTINCT json_extract(data, '$.session') FROM events "
    "WHERE json_extract(data, '$.session') IS NOT NULL LIMIT 5")]
types = json.loads(subprocess.run([sys.executable, old_script, "vocab", "--json"],
                                  capture_output=True, text=True).stdout)
type_names = sorted(types) if isinstance(types, dict) else sorted(t["type"] if isinstance(t, dict) else t for t in types)

SUBS = ["init", "append", "vocab", "session", "authorize", "reply", "status", "position",
        "handoff", "nudge", "stats", "check", "log", "streams", "closeout", "sweep",
        "doctor", "export", "import"]
cases = [(["--help"], None, False), (["nosuch"], None, False), (["status", "--bogus"], None, False),
         ([], None, False)]
cases += [([s, "--help"], None, False) for s in SUBS]
cases += [(["vocab"], None, False), (["vocab", "--json"], None, False)]
cases += [(["vocab", "--shape", t], None, False) for t in type_names]
db = ["--db", DB]
for flags in ([], ["--all"], ["--json"], ["--all", "--json"]):
    cases.append((db + ["status", *flags], None, False))
for flags in (["--open"], ["--dormant"], ["--json"], ["--open", "--json"]):
    cases.append((db + ["streams", *flags], None, False))
cases += [(db + ["log", "--limit", "40"], None, False), (db + ["log", "--json", "--limit", "40"], None, False),
          (db + ["stats"], None, False), (db + ["stats", "--json"], None, False),
          (db + ["doctor"], None, False), (db + ["doctor", "--json"], None, False),
          (db + ["export"], None, False), (db + ["session", "--get"], None, False),
          (db + ["sweep"], None, False)]
for s in streams:
    cases += [(db + ["status", "--branch", s], None, False),
              (db + ["position", "--stream", s, "--json"], None, False),
              (db + ["position", "--stream", s], None, False),
              (db + ["handoff", "--stream", s], None, False),
              (db + ["handoff", "--stream", s, "--json"], None, False),
              (db + ["log", "--stream", s], None, False),
              (db + ["closeout", "--stream", s], None, False),
              (db + ["authorize", "--gate", "commit", "--branch", s, "--json"], None, False),
              (db + ["authorize", "--gate", "publish", "--branch", s], None, False),
              (db + ["nudge", "--stream", s, "--event", "design-committed", "--tokens", "600000", "--seq", "1"], None, False)]
for sess in sessions + ["cmp-session-1"]:
    cases += [(db + ["check", "--session", sess, "--json"], None, False),
              (db + ["status", "--session", sess], None, False),
              (db + ["reply", "--session", sess, "--json"], json.dumps({"prompt": "it can go"}).encode(), False)]
# writes
w = "feat/cmp-1"
cases += [(db + ["init"], None, True),
          (db + ["append", "--stream", w, "--type", "flow-started", "--data", '{"request":"x"}'], None, True),
          (db + ["append", "--stream", w, "--type", "nosuch", "--data", "{}"], None, True),
          (db + ["append", "--stream", w, "--type", "task-done", "--data", '{"task":"T1"}'], None, True),
          (db + ["append", "--stream", w, "--type", "gate-decision", "--actor", "user",
                 "--data", '{"gate":"commit","question":"q","decision":"commit","mode":"ask"}'], None, True),
          (db + ["append", "--stream", w, "--batch", "--json"],
           b'{"type":"flow-started","data":{"request":"x"}}\n{"type":"phase-entered","data":{"phase":"workspace"}}\n{"type":"bad"}\n', True),
          (db + ["session", "--set", "cmp-session-2"], None, True),
          (db + ["check", "--session", "cmp-session-1", "--record"], None, True)]

failures = 0
for args, stdin, write in cases:
    a = run(old_script, args, stdin, write)
    b = run(new_script, args, stdin, write)
    if a != b:
        a = run(old_script, args, stdin, write)
        b = run(new_script, args, stdin, write)
    if a != b:
        failures += 1
        print("DIFF:", " ".join(args)[:120])
        for i, label in enumerate(("exit", "stdout", "stderr", "db")):
            if a[i] != b[i]:
                print(f"  {label}: old={repr(a[i])[:200]}\n  {' ' * len(label)}  new={repr(b[i])[:200]}")
print(f"cases: {len(cases)}, streams: {len(streams)}, differing: {failures}")
sys.exit(1 if failures else 0)
```

# Appendix C — bench.py

The four T017 cases of #22 and two direct journal runs. Pass each plugin copy as `LABEL=PATH`; a copy holds `hooks/`, `scripts/` and `.claude-plugin/`.

```python
#!/usr/bin/env python3
"""T017 of #22, measured again (#48): wall time of the hook process, N runs per case.

usage: bench.py [--runs N] [--env K=V ...] LABEL=PLUGIN_ROOT [LABEL=PLUGIN_ROOT ...]

PLUGIN_ROOT holds hooks/ and scripts/. Runs are interleaved across the plugin roots, so
machine drift hits every root alike. Each case builds its own fixture project once per
root. Prints median and worst per case and root, in ms.

Cases (the four T017 cases, then two direct journal runs):
  1 recorder, project with no sidecar             (budget median 60 ms)
  2 recorder, journaled, no marker, long prompt   (budget median 60 ms)
  3 recorder, marker and an open request          (budget median 200 ms; reply + append)
  4 command gate, held `git commit`               (budget median 300 ms)
  5 journal.py vocab (no db)                      (the start of one journal run)
  6 journal.py status on the fixture journal
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SESSION = "bench-session-1"
BRANCH = "feat/1-x"


def git_init(path):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    for cmd in (["git", "init", "-q"], ["git", "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}"],
                ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
                 "--allow-empty", "-m", "init"]):
        subprocess.run(cmd, cwd=str(path), check=True, capture_output=True, env=env)


def journaled_project(root, plugin):
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "shipgate.json").write_text(json.dumps({
        "version": 1, "db": ".claude/shipgate.db",
        "artifact_homes": {"worklog": "docs/prd/*.worklog.md", "prd": "docs/prd/*.md",
                           "adr": "docs/adr/*.md"},
        "enforce": {"stop_gate": True, "auto_capture": True}}), encoding="utf-8")
    db = root / ".claude" / "shipgate.db"
    journal(plugin, db, "init")
    git_init(root)
    journal(plugin, db, "append", "--stream", BRANCH, "--type", "flow-started",
            "--data", '{"request":"x"}')
    return db


def journal(plugin, db, *args, env=None):
    r = subprocess.run([sys.executable, str(plugin / "scripts" / "journal.py"), "--db", str(db),
                        *args], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise SystemExit(f"journal {args} failed: {r.stderr}")
    return r


def hook(plugin, name, payload, cwd, extra_env):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    env["CLAUDE_PROJECT_DIR"] = str(cwd)
    env.update(extra_env)
    start = time.perf_counter()
    r = subprocess.run([sys.executable, str(plugin / "hooks" / f"{name}.py")],
                       input=json.dumps(payload), capture_output=True, text=True,
                       cwd=str(cwd), env=env)
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed, r


def question(header, answer):
    q = "the question"
    return {"tool_input": {"questions": [{"question": q, "header": header, "multiSelect": False,
                                          "options": [{"label": answer, "description": "d"},
                                                      {"label": "Not yet", "description": "d"}]}]},
            "tool_response": {"answers": {q: answer}}}


class Root:
    def __init__(self, label, plugin, tmp, extra_env):
        self.label, self.plugin, self.env = label, Path(plugin), extra_env
        base = Path(tmp) / label
        self.bare = base / "bare"
        self.bare.mkdir(parents=True)
        self.proj = base / "proj"
        self.db = journaled_project(self.proj, self.plugin)
        self.gate_proj = base / "gate"
        journaled_project(self.gate_proj, self.plugin)

    def case1(self):
        return hook(self.plugin, "reply", {"hook_event_name": "UserPromptSubmit",
                                           "session_id": SESSION, "cwd": str(self.bare),
                                           "prompt": "hello"}, self.bare, self.env)

    def case2(self):
        return hook(self.plugin, "reply", {
            "hook_event_name": "UserPromptSubmit", "session_id": SESSION, "cwd": str(self.proj),
            "prompt": "please carry on with the next task of the build plan now"},
            self.proj, self.env)

    def case3(self):
        env = {**os.environ, "CLAUDE_CODE_SESSION_ID": SESSION}
        journal(self.plugin, self.db, "append", "--stream", BRANCH, "--type", "go-requested",
                "--data", json.dumps({"gate": "commit", "question": "Commit T001?"}), env=env)
        marker = Path(str(self.db) + ".requests") / SESSION
        assert marker.is_file(), "no request marker"
        t, r = hook(self.plugin, "reply", {
            "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
            "session_id": SESSION, "tool_use_id": "t-1", "cwd": str(self.proj),
            **question("Commit", "Commit")}, self.proj, self.env)
        assert r.returncode == 0 and not marker.exists(), (r.returncode, r.stderr, r.stdout)
        return t, r

    def case4(self):
        t, r = hook(self.plugin, "pre_tool_use", {
            "session_id": SESSION, "cwd": str(self.gate_proj), "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"}}, self.gate_proj, self.env)
        assert '"deny"' in r.stdout, (r.stdout, r.stderr)
        return t, r

    def _direct(self, *args):
        env = {**os.environ, **self.env}
        start = time.perf_counter()
        r = subprocess.run([sys.executable, str(self.plugin / "scripts" / "journal.py"), *args],
                           capture_output=True, text=True, env=env, cwd=str(self.proj))
        return (time.perf_counter() - start) * 1000, r

    def case5(self):
        return self._direct("vocab")

    def case6(self):
        return self._direct("--db", str(self.db), "status", "--all")


def main():
    args = sys.argv[1:]
    runs = 20
    extra = {}
    roots = []
    while args:
        a = args.pop(0)
        if a == "--runs":
            runs = int(args.pop(0))
        elif a == "--env":
            k, v = args.pop(0).split("=", 1)
            extra[k] = v
        else:
            label, path = a.split("=", 1)
            roots.append((label, path))
    with tempfile.TemporaryDirectory(prefix="bench ") as tmp:
        objs = [Root(label, path, tmp, extra) for label, path in roots]
        cases = ["case1", "case2", "case3", "case4", "case5", "case6"]
        times = {(o.label, c): [] for o in objs for c in cases}
        for o in objs:  # one warm-up run per case, so bytecode caches exist where writable
            for c in cases:
                getattr(o, c)()
        for _ in range(runs):
            for c in cases:
                for o in objs:
                    t, _ = getattr(o, c)()
                    times[(o.label, c)].append(t)
        print(f"python {sys.version.split()[0]}, {runs} runs per case, env {extra or '{}'}")
        print(f"{'case':6} " + " ".join(f"{o.label:>22}" for o in objs))
        for c in cases:
            cells = []
            for o in objs:
                ts = times[(o.label, c)]
                cells.append(f"{statistics.median(ts):7.1f} / {max(ts):6.1f} ms")
            print(f"{c:6} " + " ".join(f"{x:>22}" for x in cells))
        bare = []
        for _ in range(runs):
            s = time.perf_counter()
            subprocess.run([sys.executable, "-c", "pass"])
            bare.append((time.perf_counter() - s) * 1000)
        print(f"python3 -c pass: {statistics.median(bare):.1f} / {max(bare):.1f} ms")


if __name__ == "__main__":
    main()
```
