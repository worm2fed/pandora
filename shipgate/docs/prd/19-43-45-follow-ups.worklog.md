---
type: worklog
title: "Worklog: three follow-ups — the sync timeout, the issue id in a slug, the lead of a stream"
created: 2026-11-23
updated: 2026-11-23
tags:
  - worklog
  - shipgate
  - journal
  - codegraph
status: done
prd: none — three scoped fixes (#19, #43, #45); the issues and the Requirements below carry them
related:
  - ../adr/0007-codegraph-as-detected-structure-provider.md
  - ../adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md
  - ../adr/0021-the-handoff-brief-is-computed-not-written.md
---

# Worklog: three follow-ups

One stream and one PR carry three issues of the tracking issue #37. The user decided that
they ship together.

- #19: `codegraph sync` shares the 30 s call timeout, so a catch-up sync never finishes.
- #43: a slug with an issue id names no worklog, so `position` and the Stop gate miss it.
- #45: a teammate's stream does not record its lead, so the handoff brief reports to the
  user.

---

# Requirements

Executive Clarify. Each answer is a `gate-decision` on the stream, open to veto.

## #19 — the sync timeout

- **FR-001.** `freshen` runs `codegraph sync` under `SYNC_TIMEOUT`, 90 s. The query calls
  keep `CALL_TIMEOUT`, 30 s. The limit stays under the Bash tool's default of 120 s,
  which caps the whole `signals.py` call (review round 1, F8; the first draft said 120 s).
- **FR-002.** A sync that times out gives the reason `graph-sync-timeout`, not
  `graph-timeout`. Its graph note tells the reader to run `codegraph sync` once by hand.
  A hung query or build still gives `graph-timeout`.
- **FR-003.** `SHIPGATE_CODEGRAPH_TIMEOUT` still sets one timeout for every call, the sync
  included. The tests use it to make a hang fail fast.

## #43 — the issue id in a slug

- **FR-004.** A stream with no worklog ref owns the worklog that its slug names. When the
  slug starts with an issue id (`<digits>-`), the slug without that id is a second,
  weaker name. `fix/1290-date-off-by-one` names `1290-date-off-by-one*.worklog.md` first,
  then `date-off-by-one*.worklog.md`. Only ASCII digits count, and only one id is
  removed. One function gives the slugs; `position` and `check` both use it.
- **FR-005.** The most exact binding wins. An event ref beats a name. Among names,
  `<x>.worklog.md` beats a prefix match, then the longer slug wins, then the full slug
  beats the slug without its id.
- **FR-006.** No file under `shipgate/hooks/` changes. The Stop hook runs `journal.py
  check`, so the wider binding reaches it through `check`.

## #45 — the lead of a stream

- **FR-007.** The journal side is built (0.27.0, ADR 0021): `flow-started` and `deviation`
  take `report_to`, and `handoff` prints the newest one as `report to`. What is missing
  is the instruction. The `feature` skill tells a session that a lead's brief started to
  put the lead and the command to reach it in `flow-started`'s `report_to`, or in a
  `deviation` when the stream already exists.

## Release

- **FR-008.** Version 0.30.2 in `shipgate/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`, one `CHANGELOG.md` entry. The README paragraphs on
  the code graph timeouts and on the Stop gate's binding say the new rules. ADR 0020 gets
  an amendment for #43.

## Success criteria

- **SC-001.** With no override, `sync` runs with a 90 s timeout and a query with 30 s.
- **SC-002.** A hung sync gives `graph-sync-timeout` and its note; a hung build still
  gives `graph-timeout`.
- **SC-003.** `position` shows `feat.worklog.md` for `fix/1290-feat` with
  `worklog_from: name`; the file the full slug names wins over it.
- **SC-004.** The Stop gate blocks a tick in `feat.worklog.md` on the stream
  `fix/1290-feat`. With `feat/feat` live too, `feat/feat` owns it.
- **SC-005.** A test holds the `feature` skill's `report_to` instruction.
- **SC-006.** `git diff --stat` shows no file under `shipgate/hooks/`.

---

# Design

## Approach

**#19.** A new constant `SYNC_TIMEOUT = 90.0` in `_codegraph.py`. `freshen` passes
it to `run`, and turns that one call's `graph-timeout` into `graph-sync-timeout`. `run`
keeps its contract: a timeout is `graph-timeout` whatever the step. `GRAPH_NOTES` gets the
new reason. A killed sync still loses its work, but a catch-up of up to 90 s
finishes now. The two measured catch-ups in the issue took 35.7 s and 19.7 s.

**#43.** A new helper `_stream_slugs(stream)` in `_journal/artifacts.py` returns the slugs,
most exact first. `_free_slug_named_worklog` (the `position` side) tries each slug in
order and returns the first free match. `worklog_owners` (the `check` side) takes the
first slug that names the file and ranks the owner by (exact name, slug length, full
slug). The first slug that names a file always has the best rank of the stream's slugs:
a full slug that only prefixes the file and a stripped slug that names it exactly cannot
both match. `owns` still requires that `position` would pick the same file, so the two
sides stay one rule.

**#45.** Four short sentences in `feature`'s "The stream exists before the first event"
bullet. No code.

## Decisions

- Executive, open to veto: 90 s for sync (the issue suggested 120 s; review round 1, F8,
  showed that 120 s meets the Bash tool's default limit); a separate reason
  `graph-sync-timeout` (the issue's optional item, cheap, and it tells a slow catch-up
  from a hung query); the env override still covers sync.
- Executive, open to veto: #43 takes the code fix the issue proposes, not the skill-only
  alternative. The alternative leaves every journal with existing `fix/<id>-<slug>`
  streams ungated. Only `<digits>-` is removed; no other id form is guessed.
- Executive, open to veto: #45 gets skill text and a test, no new journal field. The field
  exists and holds free text, so the command to reach the lead fits in it.
- The widening of what the Stop gate can block is named in #43 and in the lead's brief.
  The user confirms it with the publish approval. It takes the full security review.
- No ADR: no real fork. ADR 0020 gets an amendment section for #43, as ADR 0025 did.

## Skill text on both session models

The #45 text is four short sentences. The first names the condition: "A session that a
lead's brief started reports to that lead, not to the user." The others name the event and
the field (`flow-started`'s `report_to`, or a `deviation` with `report_to` on a stream that
exists), what goes in it (the lead and the command the brief gives to reach it), and why
(`handoff` prints it after a `/clear`). It adds no step and no judgment call beyond reading
the brief. Judged by reading, on both session models: Opus and Fable both follow a literal
"put X in field Y" instruction. The risk is that a model writes a lead where none exists,
and the condition in the first sentence guards it. This stream's own `flow-started`
followed the text and `handoff` printed the target. The skill's description and trigger
words do not change, so no trigger eval is needed.

## API / contract changes

- `signals.py` JSON: a new reason value `graph-sync-timeout` under `structure.graph`. Its
  readers treat a reason as an opaque string; `graph_note` has a line for it.
- Journal: `position.artifacts.worklog` may now name a worklog for a stream whose slug
  starts with an issue id. No key changes.
- The Stop gate can block on such a stream. The hook contract (events, rules, exits) is
  the same.

---

# Build Plan

- [x] T001 — #19: failing tests for the sync timeout and its reason, then the fix — file(s): `shipgate/tests/test_codegraph.py`, `shipgate/scripts/_codegraph.py`, `shipgate/README.md` — done when: SC-001 and SC-002 pass and `test_codegraph` is green
- [x] T002 — #43: failing tests for the slug without its issue id, then the fix — file(s): `shipgate/tests/test_journal_position.py`, `shipgate/tests/test_journal_check.py`, `shipgate/tests/test_hooks.py`, `shipgate/scripts/_journal/artifacts.py`, `shipgate/scripts/_journal/position.py`, `shipgate/scripts/_journal/check.py`, `shipgate/README.md`, `shipgate/docs/adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md` — done when: SC-003 and SC-004 pass and the journal and hook tests are green
- [x] T003 — #45: failing test for the `feature` skill's `report_to` instruction, then the text — file(s): `shipgate/tests/test_prose.py`, `shipgate/skills/feature/SKILL.md` — done when: SC-005 passes
- [x] T004 — release 0.30.2: version in both manifests, one CHANGELOG entry — file(s): `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `shipgate/CHANGELOG.md` — done when: the full suite passes and SC-006 holds

## Traceability

- FR-001, FR-002, FR-003 → T001
- FR-004, FR-005, FR-006 → T002
- FR-007 → T003
- FR-008 → T001, T002, T004

## Deviations & notes (filled during implementation)

- 2026-11-23 — T002: `check.py` needed no change. Its skip text ("the newest worklog that
  a stream's slug names") holds for both slugs. The file stays in the task line as read,
  not edited.
- 2026-11-23 — T001: the README sentence on `root` mode no longer says that the 30 s
  limit stops a root sync. A root sync of 55–66 s now fits in 90 s, but each call waits
  for it, so root mode still needs the codegraph MCP server.
- 2026-11-23 — T002: `_ISSUE_ID_RE` has no `re.DOTALL`. A slug with a line break after
  the id gets no second slug, which is the safer side.
- 2026-11-23 — review round 1, F8: `SYNC_TIMEOUT` is 90 s, not the 120 s the issue
  suggested. No skill sets a Bash timeout for `signals.py`, so the Bash tool's default of
  120 s caps the whole call. FR-001, SC-001 and the Decisions say 90 s.
- 2026-11-23 — the user's publish go (journal seq 2586) accepted three points: version
  0.30.2, the 90 s sync limit, and the wider set of worklogs the Stop gate can judge
  (#43).
- 2026-11-23 — notes for new issues, found in this stream:
  - Review F3: `position`'s name fallback ignores the name bindings of other live
    streams, so `position` and `check` can show different owners for one worklog. It
    exists since ADR 0020 for a prefix and an exact name; #43 adds the slug without its
    issue id.
  - `INIT_TIMEOUT` is 120 s, the same as the Bash tool's default limit. A slow first
    build kills the `signals.py` call before its regex fallback runs (the cause of F8,
    for the build).
  - For #34: `clarify-passed` refuses a `prd` ref that ends in a `#fragment` ("PRD not
    found"), so a worklog-only flow must pass the bare path.

---

# Review

## Review round 1

The `review` Workflow (run `wf_1b3ee0ad-d25`) ran three lenses: correctness,
conventions+design, simplicity+security. Counts: 20 found, 18 after dedupe, 7 above the
floor of 60, 0 refuters (no BLOCKER or HIGH), 7 survivors, 0 killed, 11 below the floor.
The orchestrator read the code for each survivor and each below-floor MEDIUM. The briefed
security review read all 15 changed files and reported no finding at confidence 8 or
above. Verdict: not ready.

- F1 MEDIUM `docs/prd/19-43-45-follow-ups.worklog.md:128` — the design text on #45 (one sentence, an example value, starts with the condition) does not match the four sentences that shipped. Fix: the worklog describes the shipped text.
- F2 MEDIUM `shipgate/README.md:258` — the new README text defines "slug" as the whole last path segment, but the Branching row calls only the part after the issue id the slug. Fix: say once that here the slug includes the issue id.
- F3 MEDIUM `scripts/_journal/artifacts.py:532` — with `fix/1290-demo` and `feat/demo` both live and no worklog ref, `position` shows `demo.worklog.md` for both, while `check` gives it to `feat/demo`. Deferred: the same split exists since ADR 0020 for a prefix and an exact name (`epic/auth` and `feat/auth-login`), because `position` leaves out only the worklogs that events name. A new issue takes it.
- F4 LOW `tests/test_journal_position.py:261` — the test reaches `_stream_slugs` through `_package.artifacts`; the suite reads a helper from the flat namespace. Fix: `load_journal_module()._stream_slugs`.
- F5 LOW `shipgate/README.md:478` — "every other codegraph call has 30 s" is wrong: a build has 120 s. The CHANGELOG says the same. Fix: "a query has 30 s".
- F8 MEDIUM `scripts/_codegraph.py:54` — promoted from below the floor (50). No skill sets a Bash timeout for `signals.py`, so the Bash tool's default of 120 s caps the whole call. A sync of 120 s kills the call before the regex fallback runs; before this change a slow sync fell back after 30 s. Fix: `SYNC_TIMEOUT = 90.0`, which keeps 30 s for the rest of the call and still covers the measured 20–36 s catch-ups and the 55–66 s root sync.
- F9 LOW `adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md:146` — promoted from below the floor (50). The parenthesis on the rejected alternative reads as a fact about the skills today. Fix: word it as the alternative.
- F10 LOW `scripts/_journal/artifacts.py:476` — promoted from below the floor (40). The new docstring summary of `_free_slug_named_worklog` is a chain of relative clauses. Fix: two short sentences.

### Rejected findings

- `scripts/_codegraph.py:617` (LOW 60): a `timeout_reason` keyword on `run()` would replace the try/except in `freshen`. Rejected: the design keeps `run()`'s signature for its other callers, and the rename lives in the one caller that needs it (worklog Design, #19).
- `tests/test_journal_check.py:351` (LOW 60): the `test_19_`, `test_43_` and `test_45_` prefixes break the naming convention. Rejected: the suite already prefixes tests with a reference, for example `test_r2_4_the_socket_path_comes_from_the_pid_file` and `test_r3_4_only_unsendable_seeds_is_a_reason_not_no_tests` in `test_codegraph.py`.
- `scripts/_journal/artifacts.py:296` (MEDIUM 55) and `scripts/_journal/artifacts.py:295` (MEDIUM 55): a short slug without its issue id prefix-matches unrelated worklogs, so the Stop gate can block over one. Rejected: that is the widening #43 asks for, and `feat/<short>` binds the same files today. The gate judges only worklogs this session wrote, a worklog that any stream's events name is left to that stream, and a waiver clears a block.
- `adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md:123` (LOW 55): the ADR body still states the one-slug rule. Rejected: an amendment section is the repo's form, as in ADR 0025, and `updated` moved.
- `scripts/_journal/artifacts.py:361` (LOW 50): the "first slug that names the file" pick appears in both functions. Rejected: one line each, over the one shared helper.
- `skills/feature/SKILL.md:361` (LOW 45): the #45 text sits in the bullet on opening a stream. Rejected: `report_to` is written in the `flow-started` that this bullet opens.
- `scripts/_journal/artifacts.py:366` (LOW 40): `worklog_owners` calls `_free_slug_named_worklog` for more streams. Rejected: only for a stream whose second slug names a worklog this session wrote.
- `scripts/_journal/artifacts.py:284` (LOW 40): a leading year or version (`feat/2024-report`) also counts as an issue id. Rejected: the full slug still wins, and the issue asks for `<digits>-` exactly; no other form is guessed.
- `adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md:138` (LOW 30): the second slug may conflict with the "no guessing" rulings of ADR 0025. Rejected: the rule is one fixed pattern on the stream's own name; ADR 0025's rulings are about matching other branches by a suffix.

## Review round 2

Scoped to the fix diff. The orchestrator did the pass alone: the fixes are one constant
with its test, and wording in six other files. Each finding was checked at its line. The
full suite ran after the fixes: 1714 tests OK, 2 skipped. No file under `shipgate/hooks/`
changed. Verdict: ready.

- F1 MEDIUM `docs/prd/19-43-45-follow-ups.worklog.md:128` — fixed: the Design and "Skill text on both session models" describe the four sentences that shipped.
- F2 MEDIUM `shipgate/README.md:258` — fixed: the README says that here the slug is the whole last path segment, issue id included, unlike `<slug>` in the Branching pattern.
- F3 MEDIUM `scripts/_journal/artifacts.py:532` — deferred to a new issue, as round 1 says.
- F4 LOW `tests/test_journal_position.py:261` — fixed: the test reads `load_journal_module()._stream_slugs`.
- F5 LOW `shipgate/README.md:478` — fixed: the README and the CHANGELOG say a query has 30 s and a build 120 s.
- F8 MEDIUM `scripts/_codegraph.py:54` — fixed: `SYNC_TIMEOUT = 90.0`; the test pins 90 s and that a sync plus one call stays within 120 s.
- F9 LOW `adr/0020-the-stop-gate-binds-a-worklog-the-way-position-does.md:146` — fixed: the amendment words the rejected alternative as one.
- F10 LOW `scripts/_journal/artifacts.py:476` — fixed: the docstring summary is two short sentences.

What the fixes could break: `SYNC_TIMEOUT` has one reader, `freshen`. 90 s still covers the
measured catch-ups (20–36 s) and the root sync (55–66 s). The rest is wording.
