---
type: worklog
title: "Worklog: shipgate 0.30.0 — a smaller status brief and automatic stream close-out"
created: 2026-11-20
updated: 2026-11-22
tags:
  - worklog
  - shipgate
  - journal
status: review
prd: "./brief-and-close-out.md"
issue: "#31 (shipgate), batch 2 of #37"
related:
  - ../adr/0024-the-status-brief-prints-the-bound-streams-and-a-count.md
  - ../adr/0025-close-out-and-sweep-are-computed-from-observed-evidence.md
  - ../adr/0026-the-close-out-runs-local-steps-and-asks-once.md
---

# Worklog: shipgate 0.30.0 — a smaller status brief and automatic stream close-out

> Design + build plan companion to `./brief-and-close-out.md`. Issue #31, batch 2 of #37.
> Implement after #22 (0.28.0) merges, on this branch rebased onto the new `main`.

---

# Design

## Approach

Pragmatic balance, with two parts taken from the other blueprints. The journal computes what
must be exact: the brief, the ownership mark, the merge evidence, the close-out plan and
the sweep proposals. The flow runs the forge CLI and git, asks the one question, and runs
the plan. From minimal-change: no hook edit, plain `status` becomes the brief, close-out
tests go in a new test file. From clean-architecture: one `--observed <dir>` input, the
squash-merge prediction, and a plan that skips the steps already done.

The core trade-off: about six pinned tests move to `status --all`, and a session on the
integration branch must run `streams --open` to see live work by name (ADR 0024).

## Architecture

All new code is in `shipgate/scripts/journal.py`. `shipgate/hooks/session_start.py` does
not change: it prints plain `status` (`session_start.py:280-336`).

**Brief (ADR 0024).**
- Constant `OWNERSHIP_MINUTES = 30` beside `DORMANT_DAYS` (`journal.py:492`).
- `fold_stream` (`journal.py:2091`) gains two additive keys:
  - `last_writer`: `{session, ts}` of the newest event with an `event_session`
    (`journal.py:2642`) whose `_actor_role` (`journal.py:4310`) is not `hook`; else null.
    Same rule as `session_stream` (`journal.py:2279`).
  - `pull_request`: `{url, ref, ts}` from the newest `mr-opened`; else null.
- `build_status` (`journal.py:2308`) sets `other_session` on each entry: `{minutes}` when
  `last_writer` is another session than `session` and at most `OWNERSHIP_MINUTES` old;
  else null. With no `session`, it is always null.
- `render_status(status, full=False)` (`journal.py:2527`). `full=False` prints each entry
  with `session_match` or `branch_match` through `_render_feature`, then the count line,
  then `_render_ledger`. `full=True` is today's render, unchanged. `cmd_status`
  (`journal.py:5528`) passes `full=args.show_all or bool(args.feature)`.
- `_render_count_line` replaces `_render_hidden` (`journal.py:2520`) in brief mode.
- `_render_feature` (`journal.py:2464`) gains two lines, each only when set: the ownership
  line after the header line, and the close-out line before the closing blank line, when
  `pull_request` is set and the stream is not terminal. Every other line stays
  byte-identical.
- `build_stats` (`journal.py:4531`) measures the brief with `full=False`; `_stream_stats`
  (`journal.py:4461`) renders one stream with `full=True`.

**Handoff.** `build_handoff` (`journal.py:4112`) adds `pull_request` and `terminal`;
`render_handoff` prints the close-out line after `report to` (`journal.py:4174`) under the
same condition. A stream with no `mr-opened` prints byte-identical text.

**Streams.** `cmd_streams` (`journal.py:5659`) gains `--open` and `--dormant` (exclusive),
both `--json`-able. They call `build_status(conn, session=os.environ.get(SESSION_ENV))`
(`journal.py:487`) and print one line per stream. Plain `streams` is unchanged.

**Evidence (ADR 0025).** Pure functions, placed after `nudge_line` (`journal.py:4294`) to
stay clear of #22's block after `build_status`:
- `observe_script(kind, facts, forge)`: the shell text that fills a fresh directory. Every
  value goes through `shlex.quote`.
- `parse_forge_prs(text)`: gh keys (`state` OPEN/CLOSED/MERGED, `url`, `headRefName`,
  `headRefOid`, `baseRefName`, `mergedAt`, `mergeCommit`) and glab keys (`state`
  opened/closed/merged, `web_url`, `source_branch`, `sha`, `target_branch`, `merged_at`);
  one object or a list.
- `parse_refs(text)`, `parse_merged(text)`, `parse_worktrees(text)` (porcelain; the first
  entry is the main checkout).
- `merge_evidence(facts, prs, refs, merged)` → `{state, source, url, base, head_oid, detail,
  squash}`. `state` ∈ merged | closed | open | gone | unknown; `source` ∈ forge | git |
  none. Match order: the `mr-opened` URL, then `branch_match` on the head branch
  (`journal.py:2216`). A tip equal to the base tip is not evidence.
- `forge_of(url, project_dir, start)`: `github.` host → gh, `gitlab` host → glab, else the
  config's **Forge & tracker** `CLI`, else none.

**Close-out (ADR 0026).**
- `closeout_rules(project_dir, start)`: the optional **Close-out** config section through
  `_config.section_owner` and `section_bullets`, as `handoff_threshold` reads its section
  (`journal.py:4254`). Bullet form `- <Label> (ask|run): <action>`. No marker means ask; an
  action that names `tag`, `push` or `issue` is ask.
- `build_closeout(conn, stream, project_dir, start, observed)` → `{stream, version, state:
  needs-evidence | not-merged | ready, merge, steps, question, report_to}`. Each step is
  `{n, kind: run | ask, title, command, skip}`. A step already done is skipped with its
  reason (terminal event present, branch gone from refs, worktree gone from porcelain), so
  a rerun after a partial failure resumes.
- `render_closeout(plan)`. `cmd_closeout` exits 0 for `ready` and `needs-evidence`, and 4
  (`EXIT_GATE`) for `not-merged`, having written nothing.

**Sweep (ADR 0025).** `build_sweep(conn, observed, now)` covers dormant streams only and
proposes `flow-completed` (merged), `flow-abandoned` (closed unmerged, or git evidence with
no branch left and no PR), or `keep`. Each line names its source. `apply_sweep` recomputes
and appends through `append_event(..., expect=version)` (`journal.py:1836`), skipping and
naming a stream that moved.

**Payloads.** `EVENT_SHAPES` (`journal.py:274`) gains `flow-completed` and `flow-abandoned`
as `{"strings": ["reason", "evidence", "url"]}`, nothing required.

**Skills and config.**
- `feature/SKILL.md`: a **Close-out** section of at most 20 lines (run `closeout`, run the
  observe script, rerun, stop on `not-merged`, ask once, record, run in order, stop on a
  refusal); the route at `:216-232` sends the user's "merged" and a watcher's `merged` to
  it; one rule: with no bound stream, run `streams --open` before opening a stream or
  saying nothing is in flight, then `handoff` for the one to resume; the description adds
  the asks "the PR merged", "close or sweep streams".
- `knowledge-base/SKILL.md:187-191`: after `mr-opened`, `flow-completed` comes from the
  close-out, with its evidence.
- `review/SKILL.md:447-449`: "On merge" points to the close-out.
- `config-template.md`: a `## Close-out` section after **MR watcher**, and the mapping at
  `:158-162` sends "own MR/PR merged" to the close-out. `lean_config.py` catalogues the new
  template sentences.
- This repo's `.claude/shipgate.md` gains a **Close-out** section: the tag rule from the
  root CLAUDE.md (ask) and the tick of the child in its tracking issue (ask).

## Exact text

Count line (zero counts left out; no line when all are zero):

```
not shown: 4 live (1 written by another session in the last 30 min), 20 dormant, 67 finished — list: journal.py streams --open · close dormant: journal.py sweep
```

Lines added to a bound block (the close-out line also goes into `handoff`, with no indent):

```
  ownership    : another session wrote this 12m ago
  close-out    : after the merge, run journal.py closeout --stream=feat/x
```

`streams --open` line:

```
feat/x  live  phase review  last mr-opened 2026-11-20  idle 0d  pr https://forge.invalid/o/r/pull/7  · another session wrote this 12m ago
```

Close-out plan, `ready`:

```
shipgate close-out — feat/x  (v41)
merge        : merged (forge gh: MERGED 2026-11-20T10:02 · head 1a2b3c4 · https://forge.invalid/o/r/pull/7)
ask once     : AskUserQuestion, header "Close-out", multi-select, one option per [ask] step; then
               journal.py append --stream=feat/x --type=gate-decision --actor=user --data='{"gate":"close-out","question":"…","decision":"<chosen>","mode":"ask","raised_by":"user"}'
  1. [run] residual capture: 3 untriaged entries in docs/ledger.md — knowledge-base, then capture-done
  2. [run] journal.py append --stream=feat/x --type=flow-completed --data='{"reason":"merged","evidence":"forge gh: MERGED 2026-11-20T10:02 1a2b3c4","url":"…"}'
  3. [run] test -z "$(git -C /repo status --porcelain)" && git -C /repo merge --ff-only origin/main
  4. [ask] Tag the release: once the version-bump commit is on main, run claude plugin tag --push in shipgate/  (Close-out, .claude/shipgate.md)
  5. [run] report to the user: feat/x closed — merged …; the worktree and the branch go next
  6. [run] last, one Bash call: git -C /repo worktree remove /repo.worktrees/x && git -C /repo branch -d feat/x
No step takes --force, -f or -D. A step git refuses stops: quote git and ask.
```

`not-merged`: `merge : not merged (forge gh: OPEN · <url>) — nothing to close: no step runs, nothing is appended or removed.`

Sweep:

```
  flow-completed  feat/a  dormant 41d  forge gh: MERGED 2026-10-02 · <url>
  flow-abandoned  feat/b  dormant 66d  forge gh: CLOSED 2026-09-12 · <url>
  keep            feat/c  dormant 9d   forge gh: OPEN · <url>
proposed: 12 flow-completed, 5 flow-abandoned, 3 keep — after one confirmation: journal.py sweep --observed=<dir> --apply
```

## Data flow

- **Brief.** SessionStart → `status --branch --session --nested-branch` → `build_status`
  (with `other_session`) → `render_status(full=False)` → hook header → model context.
- **Close-out.** "merged" or a watcher `merged` → `feature` → `closeout` (needs-evidence,
  prints the observe script) → the flow runs it → `closeout --observed <dir>` → plan → one
  question if any `ask` step → `gate-decision` → steps 1-7. Writers: the flow writes
  `gate-decision`, `capture-done`, `flow-completed`; `closeout` writes nothing.
- **Sweep.** `sweep` → observe script (one forge list query) → `sweep --observed <dir>` →
  proposals → one confirmation → `sweep --observed <dir> --apply` → terminal events.

## Data model / schema

No schema change and no migration. New optional payload keys on `flow-completed` and
`flow-abandoned`. New additive keys in `status --json`: per stream `last_writer`,
`pull_request`, `other_session`.

## API / contract changes

- `status` plain text: smaller (ADR 0024, the user's Q1). `--all`, `--feature`, `--json`
  unchanged apart from additive JSON keys. The HUD contract (ADR 0009) holds; the
  shipgate-hud golden file is regenerated, its code does not change.
- New commands `closeout` and `sweep`; new flags `streams --open | --dormant [--json]`.
- `handoff` gains one line after `mr-opened`.
- No hook changes: no new hook event, no change to what a hook blocks or refuses.

## Reference implementation

- `build_handoff` / `render_handoff` (`journal.py:4112-4250`, ADR 0021) for a computed,
  read-only brief for a model: a typed doc, then a render where every value goes through
  `_one_line` / `_clip` and every printed command through `shlex.quote` (`journal.py:4165`).
  `build_closeout` and `build_sweep` mirror it.
- `handoff_threshold` (`journal.py:4254`) for one config section through the layers.
- `append_event` with `expect` (`journal.py:1836`) for `sweep --apply`.
- All three references sit in `journal.py`, so the signals cannot rank them against each
  other; the choice rests on reading: they are the reviewed surfaces of ADRs 0021 and 0001.

## Risk ranking

`signals.py hotspots` over the files the plan changes (source `graph`):

| File | fix | churn | fan-in |
| --- | --- | --- | --- |
| `shipgate/scripts/journal.py` | high | top | low |
| `shipgate/tests/test_hooks.py` | top | top | low |
| `shipgate/README.md` | high | top | — |
| `shipgate/skills/feature/SKILL.md` | mid | top | — |
| `shipgate/skills/review/SKILL.md` | mid | top | — |

`journal.py` is `high` fix: T002 pins the bound block and the handoff text before T005
changes them.

## Pre-mortem

1. **#22's reply recorder takes the close-out answer as a go.** `reply.py` reads
   `AskUserQuestion` answers for gate words, and a header `commit` or `publish`. Mitigation:
   header `Close-out`; the plan's option labels never casefold into #22's gate or general
   words; T019 tests it after the rebase.
2. **A session on the integration branch misses live work** and opens a duplicate stream.
   Mitigation: the count line names `streams --open`; the `feature` rule in T017; the eval
   in T020.
3. **A printed command runs something else.** A stream, branch or path with shell
   metacharacters reaches a command the flow runs. Mitigation: every value through
   `shlex.quote`; T012 and T013 test a hostile branch name.
4. **A squash merge leaves the branch.** Mitigation: the guarded `update-ref -d` step in
   the one question (ADR 0026).

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate`. One plugin, one PR, version 0.30.0 in
  `shipgate/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` together.
- Hooks: no change, so the no-op path stays as it is; T009 still tests it.
- Security-sensitive: the plan drives deletions on the user's machine. Review runs the
  security lens on every printed command; a full `/security-review` is recommended.
- Public repo: fixtures use `forge.invalid` URLs and generic branch names; measurements of
  the production copy go into the worklog as counts only.
- Release: after the merge to `main`, the tag `shipgate--v0.30.0` (`claude plugin tag
  --push` in `shipgate/`) needs the user's go.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings. Tests are tasks.
Test command: `python3 -m unittest discover -s shipgate/tests` from the repo root.

## Setup / foundations

- [x] T001 — Rebase this branch onto `main` after #22 (0.28.0) merges; run the suite; read #22's `fold_stream` `go` key, `event_session` and `binds_session`, `EVENT_SHAPES`, `reply.py` word lists and `GATE_HEADERS`, and what `authorize` does on a terminal stream — file(s): none — done when: the suite passes on the rebased branch and the findings are noted under Deviations.
- [x] T002 — Pin today's output of the risk-top surfaces: the exact bytes of `_render_feature` for a bound stream, and `render_handoff` for a stream with no `mr-opened` — file(s): `shipgate/tests/test_journal.py` — done when: both tests pass on the unchanged code.

## Brief

- [x] T003 [P] — `EVENT_SHAPES` entries for `flow-completed` and `flow-abandoned` (FR-021) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests show an empty payload and string keys pass, a list `reason` is refused.
- [x] T004 — `OWNERSHIP_MINUTES`, `fold_stream` keys `last_writer` and `pull_request`, `build_status` key `other_session` (FR-007, FR-008) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests (written first) show the mark at 29 minutes and not at 31, not for the viewer's own session, not for a hook row, not for a sessionless `user` or `watcher` row, and always null with no `--session`.
- [x] T005 — `render_status(full=False)`, `_render_count_line`, the two `_render_feature` lines, `cmd_status`, `build_stats` (FR-001 to FR-004, FR-017 brief side) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests (written first) cover SC-002 (10 against 100 open streams), the zero-count rules, a count line of at most 160 characters, a stream name with a newline staying on one line, and SC-003 (the T002 bytes plus only the new lines).
- [x] T006 — Move the tests that pin the unbound render to `--all` or the count line: `test_journal.py` near `:2283`, `:2336-2340`, `:2422-2447`, `:2640-2673`, `:5451`; `test_hooks.py:1121-1141` (the unbound stream is absent, the count line is present) — file(s): `shipgate/tests/test_journal.py`, `shipgate/tests/test_hooks.py` — done when: the suite passes and each changed assertion says why in one comment.
- [x] T007 [P] — The close-out line in `handoff` (FR-017) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: a test shows the line after `mr-opened` and none after `flow-completed`; the T002 handoff bytes still match (SC-003).
- [x] T008 [P] — `streams --open` and `streams --dormant`, with `--json` (FR-006) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: tests show one line per open stream with lifecycle, phase, last event, idle days, PR URL and the ownership mark; plain `streams` output is unchanged.
- [x] T009 — HUD contract and hook: regenerate the golden file (`SHIPGATE_REGEN_GOLDEN=1`), run `test_hud_contract.py`, add a SessionStart no-op test if none covers it (FR-005, SC-004, SC-010) — file(s): `shipgate-hud/tests/fixtures.journal.ts`, `shipgate/tests/test_hud_contract.py`, `shipgate/tests/test_hooks.py` — done when: the contract test passes with `features` unchanged and the no-op test passes.
- [x] T010 — Measure SC-001 on a copy of the production journal in the session scratchpad (never the live one): the brief with the hook header on the integration branch and in a worktree that binds the newest live stream, before and after — file(s): this worklog, counts only — done when: both numbers are at most 500 and 1,700 characters and are noted under Deviations.

## Evidence and close-out

- [x] T011 [P] — `parse_forge_prs`, `parse_refs`, `parse_merged`, `parse_worktrees`, `merge_evidence`, `forge_of` — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_closeout.py` (new), `shipgate/tests/fixtures/forge/` (new, synthetic) — done when: tests cover gh and glab in merged, closed and open states, one object and a list, a squash merge, a tip equal to the base tip, garbage input, and a missing file.
- [x] T012 [P] — The **Close-out** config section: `config-template.md` section and the MR-watcher mapping at `:158-162`, `lean_config.py` catalogue, `closeout_rules` (FR-015) — file(s): `shipgate/config-template.md`, `shipgate/scripts/lean_config.py`, `shipgate/scripts/journal.py`, `shipgate/tests/test_closeout.py`, `shipgate/tests/test_lean_config.py` — done when: tests show no marker means ask, `tag`/`push`/`issue` force ask, the layers resolve the nearest file, and the lean catalogue test passes.
- [x] T013 — `observe_script` for close-out and sweep (FR-010, FR-019) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_closeout.py` — done when: tests show the gh, glab and git-only forms, a fresh directory, and a hostile branch name quoted so that `shlex.split` returns it as one word.
- [x] T014 — `build_closeout`, `render_closeout`, `cmd_closeout` (FR-009 to FR-014, SC-006) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_closeout.py` — done when: tests show the step order of ADR 0026, `run`/`ask` kinds, the ledger step only with entries, the full Capture with no `capture-done`, the squash step only after a squash merge, `report_to`, skips on a rerun, no `--force`/`-f`/`-D` anywhere in the output, and `not-merged` exiting 4 with the event count unchanged.
- [x] T015 — Scratch-repo test of the printed git commands (SC-007): a dirty worktree, a squash-merged branch, a clean merged worktree, and the in-place case — file(s): `shipgate/tests/test_closeout.py` — done when: the dirty worktree and the unmerged branch survive, the clean merged ones are gone, and the test skips when `git` is absent.
- [x] T016 — `build_sweep`, `render_sweep`, `apply_sweep`, `cmd_sweep` (FR-018 to FR-020) — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_closeout.py` — done when: tests cover every disposition, the source on each line, only dormant streams, `--apply` rows carrying `reason`/`evidence`/`url`, and a stream that moved between the proposal and `--apply` skipped and named; a 20-stream fixture gets 20 proposals from one list file (SC-008 in shape).

## Skills, config, docs

- [x] T017 — Skill text: `feature/SKILL.md` Close-out section, the merged route, the no-bound-stream rule, the description asks; `knowledge-base/SKILL.md:187-191`; `review/SKILL.md:447-449`; `commands/shipgate.md`; `docs/glossary.md` (bound stream, close-out, sweep, ownership mark) (FR-016) — file(s): those files — done when: `test_prose.py` passes and the Close-out section is at most 20 lines.
- [x] T018 — This repo's `.claude/shipgate.md`: a **Close-out** section with the tag rule (ask) and the tracking-issue tick (ask) — file(s): `.claude/shipgate.md` — done when: `closeout` on a fixture stream in this repo lists both as `[ask]`.
- [x] T019 — Post-rebase checks: the close-out header and option labels against #22's `GATE_HEADERS`, `GATE_WORDS`, `GENERAL_WORDS` (test); what #22's command gate does with a tag push after `flow-completed` (note); whether `/clear` gives a new session id (probe, note) — file(s): `shipgate/tests/test_closeout.py`, this worklog — done when: the test passes and both notes are under Deviations.
- [ ] T020 — Eval probe through `.claude/skills/run-evals`: "merged" routes to the close-out, and a negative case, on both session models (Opus and Fable) — file(s): `shipgate/evals/` — done when: the user approved the spend, and the results are noted. Ask before running: it costs money.
- [x] T021 — Docs and release: ADR statuses checked, README rows (`status`, `handoff`, `streams`, `closeout`, `sweep`, the config table), `CHANGELOG.md` 0.30.0, `plugin.json` and `marketplace.json` to 0.30.0; grep the diff for private names, tracker ids and paths — file(s): `shipgate/README.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: the grep finds nothing and the versions match.
- [x] T022 — Final verify: the full suite, SC-001 numbers from T010 — file(s): none — done when: the suite passes with its counted tests and the numbers hold.

## Traceability

- FR-001, FR-002, FR-003, FR-004 → T005, T006
- FR-005 → T009
- FR-006 → T008
- FR-007, FR-008 → T004, T005, T008
- FR-009 to FR-014 → T013, T014, T015
- FR-015 → T012, T018
- FR-016 → T017, T020
- FR-017 → T005, T007
- FR-018, FR-019, FR-020 → T013, T016
- FR-021 → T003
- SC-001 → T010, T022
- SC-002, SC-003 → T002, T005, T007
- SC-004, SC-010 → T009
- SC-005 → T014, T020, manual walkthrough after the first real merge
- SC-006 → T014
- SC-007 → T015
- SC-008 → T016, and on the production copy with one real list query at T010
- SC-009 → T004

## Decisions owed after the rebase

- T001 may show that #22 changed `event_session` (a `binds_session` filter). Keep
  `event_session` for the ownership mark and record the choice.
- The close-out record carries no `source` key: #22's forgery net refuses a model-written
  `gate-decision` with a source marker at its gates. Confirm at T019.

## Deviations & notes (filled during implementation)

- 2026-11-20 — design corrected the clarified PRD (journal `deviation`): FR-011 order (the
  worktree goes before the branch; git refuses `branch -d` on a worktree's branch, probed
  exit 1), the SC-005 squash case, and the terms (dormant, `--dormant`).
- 2026-11-22 — the release is 0.30.0, not 0.29.0. #40 shipped 0.29.0 and merged first. The
  PRD and worklog now say 0.30.0 (journal `deviation`).
- 2026-11-22 — T001. The branch was fast-forwarded to `origin/main` at 0.28.2 (#22, #46,
  #52, #55), not rebased: it held no commits. The design files were backed up first. The
  suite on a clean checkout of that head: 1507 tests, OK, 2 skipped, exit 0. Findings:
  - The line numbers in this worklog are 0.27.0's. They moved; the names still hold.
  - `fold_stream` gained `go` (`go_answer`). The new keys sit beside it.
  - `event_session` now returns None for a row that does not bind a session
    (`binds_session`: `go-requested`, `reply-witnessed`, a go with the marker `question`,
    `prompt` or `read`). The ownership mark keeps `event_session`, as the design owed:
    a lead that asks the user about a stream does not own it.
  - `EVENT_SHAPES` had no entry for `flow-completed` or `flow-abandoned`.
  - The recorder's gate headers are `commit` and `publish` (`reply.py` `GATE_HEADERS`);
    an answer under any other header only witnesses. `GATE_WORDS` is commit, publish,
    push; `GENERAL_WORDS` is all, yes, y, ok, go, approve. T019 tests the labels.
  - The forgery net (`pre_tool_use.py`) refuses a `gate-decision` with `source` at any
    gate, and a user row at the commit or publish gate. A `close-out` decision with
    `--actor user`, `raised_by: user` and no `source` passes. No source key, as owed.
  - `authorize` on a finished stream answers `pass`, reason `not-live`. The command gate
    matches `git push`, `git subtree push`, `gh pr create` and `glab mr create`; it does
    not match `claude plugin tag --push`. So the tag step runs ungated, as ADR 0026 says.
- 2026-11-22 — T002. The pinned bound block shows a quirk of 0.28.2: `_clip` collapses
  the leading spaces of a decision line and an open-design line, so those lines start at
  column 0. The pin keeps the bytes as they are; fixing it is out of scope (SC-003).
- 2026-11-22 — T005. The count line keeps the design's exact text. The design's own
  example is 160 characters, so larger counts make the line a few characters longer. The
  line is never clipped, because a clip would cut a command. With only finished streams
  to count, the line reads `not shown: N finished — journal.py status --all shows them`
  (F18 of review round 1): `streams --open` lists no finished stream. With no stream at
  all, the brief still reads `No work streams recorded.`
- 2026-11-22 — T006. #55's recorder line for a partial write printed a plain `status`
  command. Under ADR 0024 that prints no unbound stream, and a go row binds no session.
  The journal now prints `status --all` there (`_reply_failure_lines`). No hook file
  changes; `reply.py` still falls back to the words `journal.py status` when the journal
  prints no command, which happens only for a plan with no rows (journal `deviation`).
- 2026-11-22 — T009. The golden file gained 203 lines and lost none. `claude plugin test
  shipgate-hud`: 1001 pass, 0 fail. The SessionStart no-op test already exists
  (`test_hooks.py`, `test_session_start_ignores_the_ambient_project_when_cwd_is_not_journaled`).
- 2026-11-22 — T010, SC-001, on a copy of the production journal in the session
  scratchpad, measured now (26 open streams: 6 live, 20 dormant; 69 finished):

  | Brief, with the hook's header | 0.28.2 | this branch | bound |
  | --- | --- | --- | --- |
  | Integration branch, no stream bound | 7,392 (93 lines) | 266 (1 line) | 500 |
  | Worktree that binds the newest live stream | 7,714 (95 lines) | 1,372 (14 lines) | 1,700 |
- 2026-11-22 — Deviation from ADR 0026 (executive part: the squash step's order). Probed
  on git 2.56.1 in a scratch repo. When `update-ref -d` deletes the ref of a branch that a
  worktree has checked out, that worktree's index shows its files as staged, and `git
  worktree remove` then refuses (exit 128, "contains modified or untracked files"). Only
  `--force` clears it, and the plan never uses it. The other order works: `worktree
  remove` exit 0, then `update-ref -d refs/heads/<b> <oid>` exit 0; a wrong oid still
  refuses (exit 1). So the squash step stays one `[ask]` item in the one question, but
  its command runs in step 7's single Bash call, after the worktree removal, in place of
  `branch -d`. When the user does not choose it, step 7 removes the worktree only and the
  report names the branch that stays (journal `deviation`, reported to the lead).
  2026-11-22 — the lead relayed the user's acceptance: the branch goes only on the user's
  yes, by the exact commit, with no force flag; only the order changes (journal
  `gate-decision`, seq 2168). ADR 0026 carries it as an amendment.
- 2026-11-22 — rebased (fast-forward, no conflict) onto `origin/main` 5b0ad7d, shipgate
  0.29.0 (#40), between T010 and T011. The release stays 0.30.0.
- 2026-11-22 — T014. The plan prints a bare command for the steps whose command is the
  step (`flow-completed`, the integration branch), and `title: command` for the rest, as
  the exact text shows. The squash step prints no command of its own: a flow that runs the
  steps in order would otherwise delete the ref before the worktree goes. The last step
  prints the chosen form on its own line, `when the user chose step N: …`. Every journal
  command prints whole and runnable (`python3 <journal.py> --db <db> …`, #55's form),
  never the short `journal.py` form of the exact text. With no Forge & tracker
  `Integration branch:` line, the base is `main`. (Superseded by F5 of review round 1: the
  observe script reads the base from `origin/HEAD`, else `main`; no config key names it.)
- 2026-11-22 — T015. `git branch -d` checks the branch against the local integration
  branch. So the update of `main` (step 3) must run before the last step, which is the
  plan's order. If step 3 stops on a dirty main checkout, the last step's `branch -d` also
  refuses, and the flow asks.
- 2026-11-22 — T016. Dormant is judged at the time of the evidence (the newest mtime of the
  observed files). The proposal and `--apply` therefore see the same streams, and a stream
  with an event after that time is `moved`: `--apply` skips and names it. `glab mr list`
  reads one page of 100 in the one query; a stream whose MR is older falls back to git.
  (Changed by the user's ruling on F24 in review round 2: the forge answered, so such a
  stream reads `unknown` and the sweep keeps it, or `gone` and the sweep proposes
  `flow-abandoned` when no branch is left; F38 of review round 3.)
- 2026-11-22 — T017. The `feature` Close-out section is 19 non-blank lines with its heading.
- 2026-11-22 — T019. The close-out header `Close-out` is no gate header, so an answer under
  it only witnesses an open go request, and plans nothing with none (tested). An option
  label that reads as a recorder word gets a `Step N: ` prefix (tested). The printed record
  passes `append` as a `user` row at gate `close-out`, with no `source` (tested). After
  `flow-completed`, `authorize` answers `pass`, `not-live`, so a tag push from the work
  branch is not held (tested); `claude plugin tag --push` is no gated command at all.
  `/clear` and the session id: neither journal holds a `session-started` row with source
  `clear` (62 and 276 session starts), so the data cannot say; a live probe needs an
  interactive session and was not run. The `feature` rule covers both cases: with no bound
  stream, run `streams --open`, then `handoff`.
- 2026-11-22 — T011 (F12 of review round 1). The design's `forge_of(url, project_dir,
  start)` became three functions: `forge_from_url` (the `mr-opened` URL's host),
  `forge_from_config` (a `Forge:` value) and the config reader, first `forge_settings` and
  after F5 `configured_forge`. The test class `TestForgeOf` is now `TestForgeChoice`.
- 2026-11-22 — T020 not run, by the lead's rule: an eval on both session models costs quota
  and cannot load the plugin under test over the installed one (#49). The skill text was
  judged by reading against the PRD and the memory rule on descriptions (the ask, the
  computed capability), and by `test_prose.py`. The lead decides on a check after the merge.

# Review round 1

2026-11-22. Workflow run `wf_78ee9421-406`: three lenses (correctness, conventions+design,
simplicity+security) on opus; 33 found, 33 after dedupe, 14 above the floor of 60, 2
refuters, 0 killed, 19 below the floor. The briefed security reviewer read 28 of 28 changed
files and reported no finding at confidence 8 or more, and two LOW points. Verdict:
not-ready (one HIGH). Fixed in the fix round below:

- F1 HIGH `scripts/journal.py:5433` — the git fallback calls a branch with no commits of its own "merged" once `origin/<base>` moved on.
- F2 MEDIUM `scripts/lean_config.py:315` — the new catalogue entries sit apart from their families.
- F3 MEDIUM `scripts/journal.py:5660` — close-out and sweep take the branch to be the stream name, while PR matching accepts other names.
- F4 MEDIUM `scripts/journal.py:538` — `closeout_rules` parses `section_lines` itself instead of `section_bullets`, so a fenced line can become a rule.
- F5 MEDIUM `scripts/journal.py:578` — the base comes from an `Integration branch:` key the template does not define, else `main`.
- F6 MEDIUM `scripts/journal.py:5535` — the ask-word list misses `release`, `publish`, `deploy`, `comment` and forge CLIs, so such a `(run)` step runs unasked.
- F7 MEDIUM `scripts/journal.py:5380` — a PR of another branch with the same slug, or a fork PR, can decide a stream's evidence.
- F8 MEDIUM `scripts/journal.py:5399` — squash is judged against the config base even when the PR merged into another base.
- F9 LOW `docs/glossary.md:30` — the handoff-brief row still calls the status brief "every live stream".
- F10 LOW `scripts/journal.py:6186` — the `brief_bytes` comment describes the old brief.
- F11 LOW `prd/brief-and-close-out.worklog.md:10` — the worklog status said `designing`.
- F12 LOW `scripts/journal.py:427` — the design's `forge_of` became three functions with no worklog note.
- F13 LOW `scripts/journal.py:842` — the sweep picks its forge from the config only, not from the `mr-opened` URLs first.
- F14 LOW `scripts/journal.py:5780` — `append` takes the printed close-out placeholders as the user's decision.
- F15 LOW `scripts/journal.py:5483` — the observe script prints with no one-line check (security reviewer).
- F16 LOW `scripts/journal.py:5503` — a recorded URL that starts with `--` reaches `gh pr view` as a flag (security reviewer).
- F17 LOW `scripts/journal.py:5381` — with no recorded URL, an old merged PR beats a newer open PR of the same branch.
- F18 LOW `scripts/journal.py:3413` — the finished-only count line names `status --all` without `journal.py`.
- F19 LOW `scripts/journal.py:7438` — `streams --open` prints `idle Noned` for an unreadable timestamp.
- F20 LOW `commands/shipgate.md:35` — the edited paragraph is not wrapped like the file.
- F21 LOW `adr/0026-the-close-out-runs-local-steps-and-asks-once.md:10` — the amendment names no issue.
- F22 LOW `scripts/journal.py:5782` — an apostrophe in the user's choice breaks the single-quoted record command.

### Fix plan (for the fix round, in a fresh session)

The fix round runs in a new session from `journal.py handoff --stream=feat/31-brief-and-close-out`
(the lead's decision at the handoff threshold). Every fix stays inside ADRs 0024-0026 and
changes no hook file. Write the failing test first for each code fix.

- **F5, then F1 and F8 (the evidence files).** The closeout and sweep observe scripts stop
  using a config base. In shell they set
  `base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD)`, strip `origin/`, and
  fall back to `main`. They write it to `"$d/base.txt"`, compute `merged.txt` with
  `"--merged=refs/remotes/origin/$base"`, and write
  `git rev-list --first-parent "refs/remotes/origin/$base"` to `"$d/first-parent.txt"`.
  `read_observed` reads both files (same 4 MB cap). `forge_settings` stops reading the
  `Integration branch:` key; the base is the forge's `base`, else `base.txt`, else `main`.
  F1: in `merge_evidence`'s git fallback, a ref is merged only when it is in `merged`, its
  tip is not the base tip, and its tip is not in `first-parent.txt`; a missing
  `first-parent.txt` gives `unknown`. A fast-forward merge is then `unknown` under git alone
  (safe: not-merged); the forge still sees it. Test: a branch cut from an old main commit
  with no commits is `unknown`. F8: compute `squash` only when the PR's base equals
  `base.txt`; otherwise `squash` is False and the last step keeps `branch -d`, which git
  refuses for unmerged work.
- **F3 and F7 (the branch and the PR match).** Add `_branch_names(stream)` =
  `[stream, feature_slug(stream)]` without duplicates. `_matching_pr`'s name fallback takes
  a PR only when `pr["head"]` is in that list (no slug-only match), and skips a fork PR:
  add `isCrossRepository` to `GH_PR_FIELDS` and parse it (gh), and compare
  `source_project_id` with `target_project_id` (glab); `_forge_pr` keeps a `fork` flag.
  `build_closeout` resolves the branch: the matched PR's head, else the first name in
  `_branch_names` that refs.txt holds (local or `origin/`), else the stream. It uses that
  name for the refs lookups, the worktree match, `branch -d` and `update-ref`. Update
  `test_the_branch_match_accepts_a_feature_prefixed_stream` to a head of `7-x` for stream
  `feature/7-x`, and add a slug-only miss and a fork-PR miss.
- **F17.** Rank `open` before `merged` before `closed` in `_PR_STATE_RANK`: an open PR on
  the branch means live work. Test: an old merged PR and a newer open PR give `open`.
- **F4.** `closeout_rules` reads `_config.section_bullets(owner.text, "close-out")` (it
  skips comments and fenced code and joins wrapped lines). The key comes lower-cased: take
  the `(ask|run)` marker off the key, and show the label with its first letter upper-cased.
  Test: a fenced `- X (run): y` line inside the section is no rule.
- **F6.** Widen `_CLOSEOUT_ASK_WORDS` to stems and publishing words:
  `\b(?:tag|push|issue|release|publish|deploy|comment|post)\w*\b`, and also force `ask`
  for an action that names `gh `, `glab ` or `git push`. Tests: `gh release create`,
  `npm publish`, `deploy` are `ask`; `git remote prune origin` stays `run`.
- **F13.** `build_sweep`: when the config names no forge, use the most common
  `forge_from_url` of the dormant streams' `mr-opened` URLs. Test with two github URLs.
- **F14 and F22 (the record).** Print the close-out record as a `--batch` with a quoted
  heredoc (`<<'EOF'` … `EOF`, one JSONL line with `--actor=user`), so the user's words need
  no shell quoting; the hook reads a quoted heredoc. In `append`, refuse a `gate-decision`
  whose `question` or `decision` is still `<the close-out question>` or
  `<the steps the user chose>`. Tests: the verbatim printed record exits 4; a filled one
  with an apostrophe records.
- **F15 and F16 (security reviewer).** `observe_script` returns `NO_COMMAND` when any line
  of the script is not printable (`isprintable`). A recorded URL counts only when it starts
  with `https://`; otherwise the script lists by head, and the gh form is
  `gh pr list --head=<quoted branch>`. Tests: a URL `--repo=x/y` and a stream with a
  newline.
- **F18.** The finished-only count line reads
  `not shown: N finished — journal.py status --all shows them`; update the test, the
  worklog T005 note and the CHANGELOG line if it quotes it.
- **F19.** `render_open_stream` prints `idle ?d` when `idle_days` is None. Test it.
- **F10.** Rewrite the `brief_bytes` comment in `build_stats`: with no stream named it now
  measures the brief of a session that drives nothing on the integration branch (the
  count line).
- **F2.** Move each of the six new `BOILERPLATE_SENTENCES` entries in `lean_config.py` next
  to its family: `Map it:` after the other `Map it:` lines, `Default when absent: the
  close-out…` among the `Default when absent:` lines, the `A step…` lines among the `A …`
  lines, and the `` `journal.py closeout` `` line among the backtick lines.
- **F9.** Glossary, handoff-brief row: "The *status brief* (the bound streams and a count
  line, at every session start)".
- **F11.** Done in round 1: front matter `status: review`, `updated: 2026-11-22`.
- **F12.** Add a note under Deviations: `forge_of` became `forge_from_url`,
  `forge_from_config` and `forge_settings`; rename `TestForgeOf` to `TestForgeChoice`.
- **F20.** Re-wrap the edited paragraph of `commands/shipgate.md` step 3 to the file's
  width.
- **F21.** ADR 0026 amendment heading: "## Amendment (2026-11-22, #31): …".

After the fixes: re-run the close-out, journal, hooks, lean-config and prose modules, then
the full suite (`python3 -m unittest discover -s shipgate/tests`, about 13 minutes; run it on
a snapshot copy if you keep editing meanwhile, because the tests load `journal.py` from
disk), and `claude plugin test shipgate-hud` if `status --json` changes. Close each key with
a `review-disposition` (`fixed`), then a round 2 re-review scoped to the fix diff (one
reviewer that carries all lenses), then the verdict with
`security_review {kind: briefed, files: N}`. On a ready verdict, the commit goes through the
lead (the user's go); the built-in `/security-review` runs on that commit before the push
(review skill, **The security review**). Rebuild the SC-001 numbers with the scratchpad
recipe in the T010 note if `render_status` changes. Two traps from this session: the
PreToolUse hook refuses a journal `--batch` built by a shell loop (write a quoted heredoc),
and it holds a `git commit` in a scratch repo whose path sits in a shell variable (use
literal paths).

### Fix round 1 (2026-11-22, a fresh session from the handoff brief)

Every finding is fixed; none is rejected. Each code fix had its test first, and each new
test failed before its fix. No hook file changed. Journal: one `review-disposition`
(`fixed`) per batch, each after a passing `verify-run`.

- **F1 HIGH.** Reproduced first against real git
  (`test_a_branch_never_committed_to_is_not_merged_when_main_moves_on`): a branch with no
  commit of its own, cut from main before another branch merged, gave `merged`, exit 0,
  and a last step that removed its worktree and deleted the branch. Now the git fallback
  needs the tip off `origin/<base>`'s first-parent line (`first-parent.txt`), and a
  missing file gives `unknown`. A unit test and a sweep test cover it too, and a mutant
  that drops the first-parent check fails them.
- **F5.** The observe script reads the base from `origin/HEAD` (else `main`) into
  `base.txt`, and writes `merged.txt` and `first-parent.txt` against it. `forge_settings`
  is now `configured_forge`: it reads only the `Forge:` bullet. A real-git test sets
  `origin/HEAD` to `trunk` and reads `trunk` back.
- **F8.** `squash` is true only for a PR/MR whose base is the observed base. A mutant
  without that check fails the test.
- **F3, F7, F17.** `_branch_names(stream)` is the stream and its name without `feature/`.
  The name fallback of `_matching_pr` takes an exact head of this repo only (`fork` from
  gh's `isCrossRepository`, glab's project ids); a fork's PR matches by its URL only.
  `resolve_branch` gives the git branch (the PR's head unless a fork, else the first name
  that git holds, else the stream), and `merge_evidence` returns it as `branch`; the
  close-out's refs lookups, worktree match, `branch -d` and `update-ref` use it. Open
  ranks before merged before closed. The forge fixtures gained the fork fields.
- **F4, F6.** `closeout_rules` reads `section_bullets`. The ask rule is
  `_closeout_must_ask`: the word stems tag, push, issue, release, publish, deploy, comment
  and post, or a `gh` or `glab` command. The template sentence that quotes the rule is now
  two sentences, both in the lean-config catalogue; README, CHANGELOG and ADR 0026 step 4
  quote the wider rule.
- **F2.** The six catalogue entries sit in their families, in the frozenset's order.
- **F13.** With no `Forge:` bullet, the sweep uses the forge most dormant streams'
  `mr-opened` URLs name, read when the observe script is printed.
- **F14, F22.** The record prints as `append --stream=<s> --actor=user --batch <<'EOF'`,
  one JSONL line, `EOF`, at column 0. `append` refuses a `gate-decision` whose `question`
  or `decision` still holds a close-out placeholder (exit 4, on the forced path too). A
  test runs the real PreToolUse hook on the filled record (it passes) and on the record
  with a `source` marker (it is denied), so the hook reads the heredoc body.
- **F15, F16.** `observe_script` prints `NO_COMMAND` when a line does not print on one
  line. Only an `https://` URL reaches `gh pr view` or `glab mr view`; else the script
  lists by `--head=<branch>` or `--source-branch=<branch>`.
- **F18, F19.** The finished-only count line names `journal.py status --all`;
  `streams --open` prints `idle ?d` for an unreadable time.
- **F9, F10, F11, F12, F20, F21.** The glossary row, the `brief_bytes` comment, the
  worklog front matter (done in round 1), the T011 note above, the step 3 wrap in
  `commands/shipgate.md`, and the ADR 0026 amendment heading. ADR 0025 and the
  close-out row of README and CHANGELOG now state the first-parent rule and the
  `origin/HEAD` base.

Limits that stay, inside ADRs 0024-0026:

- Git alone cannot tell a branch with no commit of its own from the branch it was cut
  from. A stream branch cut from another branch's tip (not from the base) reads as merged
  once that other branch merges with a merge commit. The forge decides first; the sweep
  shows its evidence and waits for one confirmation; and `worktree remove` still refuses
  a dirty tree.
- A fast-forward merge reads as `unknown` under git alone; the forge sees it.
- `first-parent.txt` over the 4 MB cap (about 100,000 commits) reads as missing, so git
  alone says `unknown`.
- The close-out's observe script lists PRs by the stream name. A `feature/<slug>` stream
  with no recorded URL whose branch is `<slug>` finds its PR only through git.

## Rejected findings

- `scripts/journal.py:5615` (LOW 55): git refuses a branch name that starts with `-` (check-ref-format), and the commands print only refs that refs.txt holds.
- `scripts/journal.py:5494` (LOW 55): the observe directory is a few KB in TMPDIR, and the flow names it; deleting it is the flow's choice.
- `scripts/journal.py:583` (LOW 50): the step shape uses `kind: skip` in place of a `skip` key; the worklog T014 note covers the render.
- `scripts/journal.py:5628` (LOW 50): three near-copies of the quoted-command helper differ in their argument forms; a merge is a refactor outside #31.
- `scripts/journal.py:5761` (LOW 45): when another worktree holds the base, `git switch` refuses and the step stops and asks (FR-014).
- `scripts/journal.py:5730` (LOW 45): a base that starts with `+` cannot come from `origin/HEAD` or a forge base name.
- `scripts/journal.py:5561` (LOW 40): fixed by F4, which reads the bullets through `section_bullets`.
- `scripts/journal.py:7502` (LOW 40): the confirmation is the flow's question by design (ADR 0025); the sweep has no stream to record it on.
- `scripts/journal.py:5638` (LOW 40): the function follows the plan's seven steps in order; splitting it is a refactor.
- `tests/test_closeout.py:1067` (LOW 40): T018's done-when asks for exactly this check of the repo config.
- `scripts/journal.py:5655` (LOW 35): `handoff` and `position` exit 1 on an unknown stream too.
- `scripts/journal.py:5886` (LOW 35): cleared in the F1 rework of `build_sweep`.
- `scripts/journal.py:5319` (LOW 30): `parse_merged` names the file it reads; it costs one line.

# Review round 2

2026-11-22. Re-review of the fix diff: one opus reviewer with all lenses (the exact
`journal.py` fix diff against the round-1 file, rebuilt from the round-1 session's diff and
checked by its blob hash `cf5bfab`; the other files from `git diff origin/main`), and the
briefed security reviewer on the whole working tree (28 of 28 files read, 0 untracked, no
finding at confidence 8 or more). No hook file changed. No public-repo leak. Part A: F1 to
F22 are all confirmed fixed in the code, each with its test. Verdict: not-ready (two
MEDIUM defects the fixes introduced or left, two MEDIUM points from the security
reviewer). This is the second round, so the open list goes to the user (review, Step 6).

- F23 MEDIUM `scripts/journal.py:5432` — F7's exact head match drops the legacy match, so a `feature/<slug>` stream whose PR head is `fix/<slug>` finds no PR and the sweep proposes `flow-abandoned` for an open or merged PR.
- F24 MEDIUM `scripts/journal.py:5514` — a branch with no commit of its own cut from another branch's tip still reads as merged under git once that branch merges, and `gh pr list --head` finds no PR for it, so the close-out plans `flow-completed` and the worktree removal (SC-006 for that input).
- F25 MEDIUM `scripts/journal.py:5679` — a config step marked `(run)` whose action names `-D`, `-f` or `--force` prints as `[run]`, against FR-014 and the plan's own rule line (security reviewer, confidence 6).
- F26 MEDIUM `scripts/journal.py:5645` — the ask word check is free-text matching: `"gh" pr merge`, `git pu\sh`, `twine upload` or `curl -d` in a `(run)` step pass as `run`, and after `flow-completed` no command gate holds the branch; the docs promise "whatever its mark" (security reviewer, confidence 7; reviewer B7).
- F27 LOW `shipgate/README.md:190` — README, CHANGELOG:39 and ADR 0025:56 say a branch with no commit of its own never reads as merged, which F24's input contradicts.
- F28 LOW `shipgate/CHANGELOG.md:40` — two fix-round edits are not wrapped: CHANGELOG:40 (100 columns) and ADR 0025:58 (144).
- F29 LOW `scripts/journal.py:5677` — a Close-out label loses its capitals (`Tick #31 in GitHub` shows `Tick #31 in github`), because `section_bullets` lower-cases the key.
- F30 LOW `prd/brief-and-close-out.worklog.md:?` — SC-008 was not measured again on the journal copy after F1, F7 and F17 changed the sweep's proposals.
- F31 LOW `tests/test_closeout.py:523` — `CLOSEOUT_CONFIG` keeps an `Integration branch:` line that nothing reads after F5.
- F32 LOW `tests/test_closeout.py:200` — the name `test_merged_wins_among_several_prs_of_one_branch` misleads after F17, and no test pins F14's refusal on the forced path.
- F33 LOW `scripts/journal.py:5530` — `forge_from_url` picks `gh` for any `github.*` host, so a recorded URL on another host sends `gh pr view` there, with `GH_ENTERPRISE_TOKEN` when it is set (security reviewer, confidence 3).

Proposed fix round 3 (not started: the two-round cap, and F24 and F26 change released
behaviour beyond the round-1 fix plan):

- F23: for a `feature/` stream only, also take a non-fork PR whose head's last segment is
  the slug, and resolve the branch from a ref that ends in `/<slug>`; turn
  `test_a_slug_alone_matches_no_pr` into a positive test for a `feature/` stream and keep
  a negative one for any other stream.
- F24 (recommended): when the forge answered (`forge.json` parsed) and no PR/MR matched,
  git may say `gone` or `unknown` but never `merged`. Every shipgate stream ships through
  a PR/MR; a project that merges with no PR/MR and has a forge CLI then closes by hand.
  The forge-less case keeps the limit, and F27's wording says so.
- F25: a config step whose action names `-D`, `-f`, `--force` or `--force-with-lease` as
  a word prints as `[skip]`, with the reason "names a force flag (FR-014)".
- F26 (recommended): keep `(run)` for config steps; say in the template, README, CHANGELOG
  and ADR 0026 that the word check is a guard against a mislabeled step, not a security
  boundary, and list the words exactly; add the stems `upload`, `send` and `notify`. The
  other option is every config step `ask`, which reverses the user's Q4 answer.
- F27 to F32: the wording, the wraps, the label case from the raw bullet, the fixture
  line set to `trunk` so the close-out tests prove the key is inert, the test rename and a
  forced-path test. F30 stays deferred: it needs a real forge query (the lead's rule 6).
- F33: deferred. It needs a prior injection into the journal, and the code is round 1's.

## Rejected findings

- `scripts/_config.py:172` (LOW 35): a lazy continuation line at column 0 is not joined; `section_bullets` is the one reader every config section uses, and the template indents its continuation.
- `scripts/journal.py:5831` (LOW 4): `flow-completed` before the config steps turns the command gate off for the branch; ADR 0026 Consequences and the user's Q4 accepted that order (F26 carries the risk it enables).
- `scripts/journal.py:5312` (LOW 3): glab's MR JSON always carries `source_project_id` and `target_project_id`; the damage is bounded by the oid guard and `worktree remove` refusing a dirty tree.
- `scripts/journal.py:5888` (LOW 2): the base is a git branch name (`baseRefName`, `origin/HEAD`), and git refuses a branch name that starts with `-` (round 1 ruled the same).
- `scripts/journal.py:7651` (LOW 2): the sweep's confirmation is the flow's question by design (ADR 0025), and a plain `append` of a terminal event was never gated.

### Fix round 2 (2026-11-22, after the user's three rulings)

The user's rulings, relayed by the lead, are journal `gate-decision` rows: Q1 at gate
`review` (F24), Q2 at gate `review` (F25, F26), Q3 at gate `review-cap` (run round 3). Each
code change had its test first, and each new test failed before its change. No hook file
changed.

- **F24 (Q1, "No PR means never merged").** `merge_evidence`: when the forge answered
  (`forge.json` parsed, even as an empty list) and no PR/MR matches, git may say `gone` or
  `unknown`, never `merged`. With no forge evidence, the first-parent rule of F1 still
  decides. ADR 0025 records the ruling and its cost in Consequences. The T016 note above
  changes with it: a stream whose MR falls off glab's one page is kept.
- **F25, F26 (Q2, "Every config step is asked").** The `(run)` mark, the key regex, the
  word list and the forge-CLI check are gone from `journal.py`. `closeout_rules` returns
  `label`, `action` and `source`; every project step is an `[ask]` step in the one
  question. The config template, its catalogue sentence, README, CHANGELOG, PRD FR-015,
  ADR 0026 (step 4 and a new amendment that records the ruling with F25 and F26 as the
  evidence) and this repo's `.claude/shipgate.md` (no `(ask)` marks) say so.
- **F23.** A `feature/<slug>` stream (the journal's old naming) matches a PR/MR of this
  repo whose head ends in `/<slug>`, after an exact name; it resolves its branch from the
  one branch whose name ends in `/<slug>`; two such branches leave it `unknown`, never
  `gone`. Any other stream still needs an exact name (F7).
- **F27, F28.** README, CHANGELOG and ADR 0025 now say: a stream with no PR/MR on a forge
  that answered is never merged; with git alone, a branch cut from the integration branch
  with no commit of its own never reads as merged. The edited CHANGELOG and ADR 0025 lines
  wrap at the files' width.
- **F29.** `_config.section_bullets` takes `keep_case` (default off, so every other caller
  is unchanged); the Close-out labels show as written.
- **F31, F32.** `CLOSEOUT_CONFIG` names `trunk` as its `Integration branch:`, so the
  close-out tests prove the key is inert. The test is now
  `test_merged_outranks_closed_among_prs_of_one_branch`, and the placeholder refusal is
  tested on the forced path too.
- **F30, F33** stay deferred, for a follow-up issue: the SC-008 re-measure on a journal
  copy needs a real forge query, and the `github.*` host check needs a prior injection
  into the journal.

# Review round 3

2026-11-22. Re-review of fix round 2: one opus reviewer with all lenses on the fix diff (12
files, 870 lines, the round-2 reviewed tree against now), and the briefed security reviewer
on the whole working tree (29 of 29 files read, 7 of them in part: test files, which are a
hard exclusion, and docs grepped for confidentiality; no finding at confidence 8 or more).
No hook file changed. No public-repo leak. Part A: F23, F24, F25, F26, F27, F28, F29, F31,
F32 and the user's rulings Q1 and Q2 are confirmed in the code and the docs, each with its
test. Full suite: 1,679 tests, OK, 2 skipped, exit 0. Verdict: not-ready, two MEDIUM defects
that fix round 2 introduced. The cap the user lifted for round 3 is reached again, so the
open list goes to the user.

- F34 MEDIUM `scripts/journal.py:5640` — with no recorded URL, the close-out asks the forge about `--head=<stream>` only; for a `feature/<slug>` stream whose branch is `<slug>` or `fix/<slug>` the answer is `[]`, so Q1 reads "never merged" (and the detail names a head the forge was never asked about); the close-out exits 4 although the PR merged.
- F35 MEDIUM `scripts/journal.py:5475` — with no forge evidence, a `feature/<slug>` stream whose own branch is gone resolves to the one branch that ends in `/<slug>`, which can be another stream's (`chore/docs` for `feature/docs`); git then reads it as merged and the plan removes that branch's clean worktree and deletes the branch (probed).
- F36 LOW `scripts/journal.py:5444` — any non-fork head that ends in `/<slug>` matches a `feature/<slug>` stream, so a short slug can pick another branch's PR in the sweep (`renovate/npm/docs` for `feature/docs`), and an exact closed PR outranks a slug PR that merged (security reviewer too, confidence 4).
- F37 LOW `scripts/journal.py:5482` — the `merge_evidence` docstring still says git decides without a PR/MR and claims a branch with no commit of its own never reads as merged.
- F38 LOW `scripts/journal.py:5599` — the comment says a stream older than glab's page falls back to git; after Q1 it reads `unknown`, or `gone` (and so `flow-abandoned`) when no branch is left, which the T016 note misses too (security reviewer, confidence 6).
- F39 LOW `scripts/journal.py:5318` — a forge list whose items lost the expected keys parses to `[]`, so after a gh or glab field rename every stream reads "no PR/MR, never merged" instead of falling back to git as ADR 0025 says.
- F40 LOW `scripts/journal.py:5440` — the URL match is exact, so a recorded URL in another form (`.../merge_requests/7/diffs`) misses the one PR a view query returns, and Q1 reads "never merged".
- F41 LOW `adr/0026-the-close-out-runs-local-steps-and-asks-once.md:22` — the ADR 0026 lead paragraph and the `feature` skill description still say only publishing steps wait for the question.
- F42 LOW `tests/test_closeout.py:283` — a new test line is 93 columns.
- F43 LOW `scripts/journal.py:5469` — a recorded URL of another repo's PR makes its head the branch, so the plan could switch away from and `branch -d` the integration branch; no check keeps the branch off the base (security reviewer, confidence 3).

Proposed fix round 4 (not started; it needs the user's go):

- F35: a branch found by its slug alone (not the stream or its `feature/`-less name) may
  make git say `gone` or `unknown`, never `merged`. Test with the `feature/docs` probe.
- F34 (recommended): for a `feature/<slug>` stream with no recorded URL, the close-out
  observes with the sweep's list query, and in the close-out a PR matches by the stream's
  exact names only (`feature/<slug>`, `<slug>`); slug guesses stay in the sweep, which
  only appends journal events after one confirmation. The forge note names the heads it
  matched against. Option: keep the limit, fix only the detail text, and let the sweep
  close such streams.
- F36: in the sweep, a slug match counts only when exactly one non-fork head ends in
  `/<slug>`.
- F37 to F43: the docstring, the comment and the T016 note, `parse_forge_prs` returning
  None for a non-empty list with no usable item, a URL compare cut at the PR/MR number,
  the two wording lines, the wrap, and no branch step when the branch is the base.

## Rejected findings

- `scripts/journal.py:5873` (LOW 3): `fetch origin <base>:<base>` with a base that starts with `-` needs a local `refs/heads/<base>` of that name, and git refuses such a branch name (round 1 and round 2 ruled the same for `switch`).

### Fix round 3 (2026-11-22, after the user's round-3 ruling)

The ruling "Exact names only, no guessing", relayed by the lead, is a journal
`gate-decision` at gate `review-cap` (it also approved this round). Each change had its test
first; the new tests failed before it. No hook file changed. This round deletes more than it
adds: `_branch_names`, `_legacy_slug`, `_ends_in_slug`, `_slug_branches`, `resolve_branch`
and `_matching_pr` are gone, and so are the tests that pinned their guesses in the
close-out.

- **F34, F35 (closed by removal).** `merge_evidence` takes the stream's exact name as the
  branch. Its PR/MR is the recorded one (`_stream_pr`) or one whose head is the stream. In
  the close-out, a recorded PR/MR with another head shows nothing, and no branch of the
  stream's name reads `gone`; both details name `journal.py sweep`, and the close-out exits
  4 with no step. New tests: `test_the_close_out_matches_exact_names_only`,
  `test_a_recorded_pr_with_another_head_closes_nothing`,
  `test_a_stream_whose_branch_has_another_name_exits_4` (no worktree removal, no branch
  deletion, no event).
- **F36.** Only the sweep guesses (`merge_evidence(..., guess=True)`): a recorded PR/MR
  with another head, and for a `feature/<slug>` stream the one PR head or branch that is
  `<slug>` or ends in `/<slug>` (`_slug_names`; none when two do). The detail says
  `guess:`, and a guessed branch never reads as merged (the F35 probe is
  `test_a_guessed_branch_never_reads_as_merged`).
- **F37, F38.** The `merge_evidence` docstring states the rules as they now are; the glab
  page comment and the T016 note say an older stream reads `unknown` (kept), or `gone`
  (abandoned) when no branch is left.
- **F39.** `parse_forge_prs` returns None for a non-empty list with no usable entry, so a
  format drift falls back to git as ADR 0025 says.
- **F40.** `_pr_url_key` cuts a URL at its PR/MR number and lower-cases the host.
- **F41.** ADR 0026's lead paragraph and the `feature` skill description name the
  project's own steps.
- **F42.** The round-2 test line is gone with its test; the one new long line is wrapped.
- **F43.** A stream named as the integration branch reads `unknown`, so the close-out never
  removes or deletes it.
- **Docs.** ADR 0025 has an amendment that records the ruling with F34 and F35 as the
  evidence. PRD FR-009 and FR-018, README and CHANGELOG say the same.

# Review round 4

2026-11-22. Re-review of fix round 3: one opus reviewer with all lenses on the fix diff (9
files, 751 lines), and the briefed security reviewer on the whole working tree (29 of 29
files covered, 21 line by line; no finding at confidence 8 or more). No hook file changed. No
public-repo leak. Part A: F34 to F43 and the four parts of the user's round-3 ruling are
confirmed; no input makes the close-out plan a worktree removal, `branch -d` or `update-ref
-d` for a branch not named exactly as the stream, and no deleted helper is referenced. Full
suite: 1,682 tests, OK, 2 skipped, exit 0. Verdict: not-ready, one MEDIUM defect that F36's
fix introduced, in the sweep only (journal events after one confirmation).

- F44 MEDIUM `scripts/journal.py:5492` — when two PR heads end in `/<slug>`, the sweep takes neither and, with no branch left, reads `gone` with "no PR/MR", so it proposes `flow-abandoned` for a stream whose PR may have merged (probed); two guessed branches read `unknown` instead.
- F45 LOW `scripts/journal.py:5490` — the sweep guesses a slug PR head even when the stream's own branch exists, so another stream's merged PR can propose `flow-completed`.
- F46 LOW `adr/0025-close-out-and-sweep-are-computed-from-observed-evidence.md:116` — the sweep reads a recorded PR/MR with another head without the `guess:` label that the amendment and the worklog promise.
- F47 LOW `prd/brief-and-close-out.md:195` — SC-005 still promises every merged stream ends terminal, which the ruling limits to a branch named as the stream.
- F48 LOW `scripts/journal.py:5479` — a new docstring line is 118 columns.
- F49 LOW `shipgate/CHANGELOG.md:45` — the edited close-out paragraph has a broken wrap.
- F50 LOW `scripts/journal.py:5285` — glab's `locked` state is not mapped, so after F39 a view of a locked MR reads as missing forge evidence.
- F51 LOW `scripts/journal.py:5463` — the close-out's sweep hint promises a close the sweep gives only to `feature/<slug>` streams or a recorded URL.
- F52 LOW `scripts/journal.py:5423` — `_pr_url_key` raises `ValueError` on a malformed URL (`https://[bad/...`), a new crash point beside the old one in `forge_from_url`.
- F53 LOW `scripts/journal.py:5932` — the close-out question shows a project step's label, not its command, so the user approves a name (security reviewer, confidence 4).

Proposed fix round 5 (not started; it needs the user's go): F44, two or more slug heads
read `unknown` with a detail that names them; F45, a slug PR guess only when no ref of the
stream's exact name exists; F46, the recorded-head read says `guess: recorded head <h>`;
F47 to F49, the SC-005 amendment and two wraps; F50, `locked` maps to `open`; F51, the hint
says the sweep can record the stream; F52, a malformed URL compares as itself; F53, the ask
line prints each project step's command beside its label.

## Rejected findings

- `scripts/journal.py:5424` (LOW 30): the URL key keeps the path's case and the scheme; the observe script passes `https://` URLs only, and after the ruling a miss in the close-out only changes the detail (exit 4 either way).
- `scripts/journal.py:5508` (LOW 3): a stream named like the real integration branch while `origin/HEAD` is unset needs a journal stream named as the integration branch, which the skills never open, and `branch -d` keeps its guard.
- `scripts/journal.py:5439` (LOW 3): an old merged PR of a reused branch name is the user's own reuse; the recorded URL wins and an open PR ranks first, and `branch -d` refuses unmerged commits.
- `scripts/journal.py:5434` (LOW 2): a recorded URL of another repo is written by the model behind the publish gate, and git's guards stay.
- `scripts/journal.py:5973` (LOW 2): base and head names in step titles are prose, not commands.
- `scripts/journal.py:5763` (LOW 2): `_option_label` checks the clipped label, and the recorder still needs an open go request under a gate header.

Handoff (2026-11-22): the session that ran fix rounds 1 to 3 reached the handoff threshold
after this verdict. Fix round 5 above waits for the user's go through the lead; a fresh
session runs it from `journal.py handoff --stream=feat/31-brief-and-close-out`. Its fix
diff baseline is the round-4 reviewed tree, saved outside the repo in the old session's
scratchpad (`base4/`).

### Fix round 5 (2026-11-22, a fresh session, after the user's round-4 ruling)

The ruling "One more round, no guessing in the sweep", relayed by the lead, is a journal
`gate-decision` at gate `review-cap` (seq 2311). It replaces the round 5 proposed above:
slug guessing leaves the sweep too, a stream with no branch and no PR/MR of its exact name
gets the proposal `unknown` (the user decides) with the evidence shown, and the rest is
fixed. Each change had its test first; 32 tests errored on the new `sweep` keyword and 5
failed on behaviour before the code changed. No hook file changed. The fix-diff baseline is
the round-4 tree in the old session's scratchpad (`base4/`), which survived.

- **F44, F45, F46 (closed by removal).** `_slug_names`, `_ref_branches` and the `guess`
  path of `merge_evidence` are gone, and so are the three tests that pinned the sweep's
  guesses. The keyword is now `sweep`: the sweep reads the recorded PR/MR whatever its head
  is called (the stream's own evidence, so no `guess:` label), and nothing else differs
  from the close-out. `gone` (no branch and no PR/MR of the exact name) proposes `unknown`,
  which `--apply` skips; `flow-abandoned` comes only from a PR/MR closed unmerged. The "no
  PR/MR" note names the recorded URL too, so the line shows what the sweep looked for. New
  tests: `test_the_sweep_takes_no_slug_head` (the F44 probe, one and two heads),
  `test_the_sweep_ignores_a_slug_head_when_its_branch_exists` (F45),
  `test_the_sweep_takes_no_slug_branch`,
  `test_no_pr_detail_names_the_recorded_url_it_looked_for`,
  `test_no_branch_and_no_pr_of_its_name_is_unknown` (`--apply` appends nothing),
  `test_without_forge_evidence_a_gone_branch_is_unknown`,
  `test_the_recorded_pr_counts_whatever_its_head` (F46).
- **F47.** SC-005 says it holds for a stream whose branch and PR head carry its exact name.
- **F48.** The long docstring line is gone with the rewritten docstring.
- **F49.** The CHANGELOG close-out paragraph is wrapped again.
- **F50.** glab's `locked` maps to `open` (`test_a_locked_glab_mr_is_open`).
- **F51.** The close-out hint says the sweep lists the stream once it is dormant and the
  user decides.
- **F52.** `_pr_url_key` and `forge_from_url` catch urlsplit's `ValueError`: the key is the
  URL itself, and the forge is None (`test_a_malformed_url_compares_as_itself`).
- **F53.** Each `ask` step carries the command the user approves; the `ask once` line
  prints it beside the option label as the option's description, and the squash step shows
  its `update-ref` (`test_each_option_shows_the_command_the_user_approves`).
- **Docs.** ADR 0025 has a second amendment that records the ruling with F44 and F45 as the
  evidence; the first amendment points to it. ADR 0026's round-2 amendment names the
  command beside the label. PRD FR-018 and SC-005, README, CHANGELOG, glossary and the
  `feature` skill say the same.

Deferred, for a follow-up issue: F30 and F33 (review round 2), and T020 (the eval probe).

# Review round 5

2026-11-22. Re-review of fix round 5: one opus reviewer with all lenses on the fix diff (11
files, 830 lines, the round-4 tree against now; agent path, as in rounds 3 and 4), and the
briefed security reviewer on the whole working tree (29 of 29 files read, 13 in full; no
finding at confidence 8 or more). No hook file changed. No public-repo leak. Part A: F44 to
F53 and the user's round-4 ruling are confirmed in the code and the docs, each with its
test; no slug, suffix or legacy-name guess is left in the sweep or the close-out, and the
only caller of the renamed `sweep` keyword is `build_sweep`. Full suite: 1,689 tests, OK, 2
skipped, exit 0 (827 s). Verdict: ready. Six LOW findings remain, none a regression of an
FR or SC; the review cap is reached, so they go with F30 and F33 to a follow-up issue.

- F54 LOW `scripts/journal.py:6074` — an `unknown` sweep line prints no command that records the user's decision, and the `feature` skill names none, so the model writes a `flow-abandoned` or `flow-completed` append by hand (the journal accepts it) or the stream stays dormant; reviewer confidence 65, MEDIUM lowered to LOW because no state goes wrong.
- F55 LOW `scripts/journal.py:5694` — the rule line "No step takes --force, -f or -D" sits beside a project step that the config wrote with `-D`; the step title printed that action since round 2, and F53 now prints it as the command the user approves too.
- F56 LOW `scripts/journal.py:5969` — `unknown` names the merge state that proposes keep and also the disposition that `gone` proposes, two concepts under one term.
- F57 LOW `scripts/journal.py:5944` — the `ask once` line joins options with `; ` and prints commands unquoted, so a project action that holds `; ` splits the option list in the wrong place.
- F58 LOW `prd/brief-and-close-out.md:23` — the PRD (lines 23 and 109), README line 187 and the brief's count line (`journal.py:3428`, "close dormant") still say the sweep closes the dormant streams; an `unknown` or keep stream stays open.
- F59 LOW `skills/feature/SKILL.md:250` — close-out step 3 does not say that each option's description is its command; the printed `ask once` line says it.

## Rejected findings

- `adr/0025-close-out-and-sweep-are-computed-from-observed-evidence.md:65` (LOW 55): the Decision text is the decision as made, and the second amendment supersedes it, as the first did; "one terminal event per proposal" already left out keep before this round.
- `scripts/journal.py:5863` (LOW 2): a PR base that starts with `-` reaches `fetch origin <base>:<base>` only with a local branch of that name, which git refuses to create (rounds 1 to 3 ruled the same).
- `scripts/journal.py:5867` (LOW 2): a project step's action reached the plan before F53, in the step title, through the same `_one_line`; the config is the project's own file and every project step is `[ask]`.
- `scripts/journal.py:5550` (LOW 3): the security reviewer's `gh` token point is F33, deferred.

### Fix round 6 (2026-11-23, after the user's ruling on F60)

The built-in `/security-review` ran on commit 9732a47 and found nothing at its bar. It
noted that `git worktree remove` deletes a worktree's ignored files; a probe in a scratch
repo confirmed it (an ignored `.env`, exit 0, the file gone). That is F60, deferred at first
(`scripts/journal.py:5893`). The user ruled "Hold, make it an asked step" (journal
`gate-decision` at gate `review`, seq 2342). The fix diff is the working tree against
9732a47. Each change had its test first: 7 failures and 2 errors before the code changed.
No hook file changed.

- **F60.** The close-out's observe script runs `git status --porcelain --ignored` in the
  linked worktree whose branch is the stream (found in `worktrees.txt` with `awk`), and
  keeps `worktree-status.txt` only when git succeeds. `parse_worktree_files` keeps the
  `!!` and `??` entries. With any of them, or with no file, the removal is an `[ask]` step:
  the count, the first five files, "deleted with the worktree", and the removal command as
  the option's description. The last step then reads `only when the user chose step N`, a
  squash deletion's line names both steps, and the report names the worktree and the
  branch as kept when the user did not choose the removal. With none, nothing changes. New
  tests: `test_worktree_files`, `test_the_close_out_records_the_stream_worktree_files`,
  `test_an_ignored_file_makes_the_removal_an_ask_step` (in the plan and against real
  git), `test_an_untracked_file_makes_the_removal_an_ask_step`,
  `test_a_worktree_with_no_such_file_is_removed_with_no_question`,
  `test_unobserved_worktree_files_make_the_removal_an_ask_step`,
  `test_the_removal_step_shows_the_count_and_the_first_files`,
  `test_an_asked_removal_and_a_squash_deletion_run_together`; the scratch-repo dirty and
  clean cases assert the new step's presence and absence.
- **Docs.** ADR 0026 has an amendment with F60 as the evidence. PRD FR-012, README,
  CHANGELOG, glossary and the `feature` skill's step 4 say the same.

# Review round 6

2026-11-23. Re-review of fix round 6: one opus reviewer with all lenses on `git diff HEAD`
(HEAD is 9732a47). F60 is confirmed clause by clause for git's default config. Verdict:
not-ready, one HIGH in the fix itself. The full-suite run was stopped, because fix round 7
changes the tree.

- F61 HIGH `scripts/journal.py:5668` — with `status.showUntrackedFiles=no` (repo or user config), `git status --porcelain --ignored` lists no ignored file and exits 0, so the removal runs with no question and deletes the files (probed twice: no output, exit 0; `--untracked-files=normal` lists `!! .env`).
- F62 LOW `scripts/journal.py:5767` — git prints a wholly ignored directory as one entry, so "2 ignored or untracked files" can mean `node_modules/` and `.env`.
- F63 LOW `scripts/journal.py:5913` — the removal option shows `worktree remove` only, but choosing it also runs `git branch -d`.
- F64 LOW `scripts/journal.py:5929` — the report line says "the worktree and the branch go next" and then "name them as kept".
- F65 LOW `shipgate/README.md:190` — README, CHANGELOG and glossary leave out the "files not observed" case, and the ADR amendment does not place the new step in the order.
- F66 LOW `shipgate/CHANGELOG.md:47` — the inserted sentences left a ragged wrap.
- F67 LOW `scripts/journal.py:5909` — a path created after the observation is deleted with no question; deferred: the plan is computed from evidence observed once (ADR 0025).

## Rejected findings

- `scripts/journal.py:5950` (LOW 40): the last step's title says `only when the user chose step N`, a test pins it, and `feature` step 4 names the rule.

### Fix round 7 (2026-11-23)

Within the user's F60 ruling. Each change had its test first: 7 failures before the code
changed, among them the real-git case with `status.showUntrackedFiles=no`. No hook file
changed.

- **F61.** The observe script runs `git status --porcelain --ignored
  --untracked-files=normal` (`test_hidden_untracked_files_still_make_the_removal_an_ask_step`
  against real git, and the observe-script test).
- **F62.** The step counts paths: "it holds 2 ignored or untracked paths (node_modules/,
  .env), deleted with the worktree".
- **F63.** The removal option's description is the whole last command, `branch -d`
  included; `build_closeout` builds that command before it adds the ask steps.
- **F64.** The report reads "the worktree and the branch go next only if the user chose
  step N; else name the worktree … and the branch … as kept".
- **F65, F66.** README, CHANGELOG and glossary name the "files not observed" case; the ADR
  0026 amendment places the step after the project's steps and before the squash deletion,
  and names F61 and F67; the CHANGELOG bullets are wrapped again.

# Review round 7

2026-11-23. Recheck of fix round 7 by the round-6 reviewer on `git diff HEAD` (rounds 6 and
7 on top of 9732a47). F61 to F66 are confirmed in the code, each with its test; the squash
path is unchanged line by line. No hook file changed. Full suite: 1,699 tests, OK, 2
skipped, exit 0 (856 s). Verdict: ready. One LOW remains, mostly older than this round, and
goes with F67 to #62.

- F68 LOW `scripts/journal.py:5937` — with a squash-merged branch, the report says the worktree and the branch go when the user chose the removal step alone; the branch goes only when the squash step is chosen too.
