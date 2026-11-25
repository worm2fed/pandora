---
type: worklog
title: "Worklog: The publish gate shows what changed and what was decided alone"
created: 2026-11-25
updated: 2026-11-25
tags:
  - worklog
  - shipgate
  - review
  - publish
status: review
prd: "./publish-digest.md"
issue: "#25 (shipgate), child of #37"
related:
  - "../adr/0030-the-publish-digest-is-computed-and-rides-the-publish-question.md"
---

# Worklog: The publish gate shows what changed and what was decided alone

> Design + build plan companion to `./publish-digest.md`. Issue #25, child of #37.

**Where the build runs.** The worktree `pandora.worktrees/feat-25-publish-digest` (a
sibling of the main checkout), on the branch `feat/25-publish-digest`, cut from `origin/main`
at bdc1b79 (shipgate 0.34.1). The design artifacts are uncommitted there. Start the build
session in that worktree and run `journal.py handoff --stream feat/25-publish-digest`. The
journal database is a link to the main checkout's journal.

**The release.** shipgate 0.35.0, one PR. No file under `shipgate/hooks/` changes, and no
file under `shipgate-hud/` changes, so the publish approval keeps its path (one Publish
dialog for commit, push, PR, merge and tag). After the merge, tag `shipgate--v0.35.0` with
`claude plugin tag --push` in `shipgate/`.

**Evals.** None (F8 A). Unit tests pin every computed part; prose tests pin the review
sentences. The eval harness has no question dialog (#49), so no case could see the publish
question.

---

# Design

## Approach

Inline design, no architect fan: the user's answers to F1 to F8 left one viable approach
(ADR 0030). One new module computes the digest from `build_position`, the PRD parser of #24
and the stream's events. The review skill writes one worklog section and shows the
digest at the verdict and in the publish question. The core trade-off: the digest is fixed
and short, so a part over its slot shows a count, not its items.

## Architecture

**New: `shipgate/scripts/_journal/digest.py`.** Three public functions and a few constants.

- `build_digest(conn, stream, project_dir, homes) -> DigestDoc`. It calls
  `build_position` (which raises `InfraError` for a stream with no events, so the command
  exits 1) and `read_events` for the same stream. It reads two files at most: the worklog
  (`position["artifacts"]["worklog"]`) and the PRD (`position["artifacts"]["prd"]`), each
  with `errors="replace"`, as `build_position` reads the worklog. It runs no git and writes
  nothing. The lists in `DigestDoc` are uncapped; only the renderer caps.
- `render_digest(doc, show_all=False) -> str`: the text in **Exact text** below.
- `parse_what_changed(text) -> List[str]`: the strict "What changed" form. It raises
  `SectionError` with a line.

`DigestDoc` (a `TypedDict`, sorted keys under `--json`):

```text
stream        str
verdict       {"verdict": "ready"|"not-ready", "round": int} | null   ← position["verdict"]
publish       "authorized" | "held"                                   ← position["publish"]["kind"]
worklog       str | null                                              ← position artifacts
prd           str | null
what_changed  {"items": [str], "error": str | null}
decided       {"items": [{"source": "prd"|"journal", "text": str, "risky": bool,
                          "line": int|null, "seq": int|null}],
               "error": str | null}
deviations    {"items": [{"seq": int, "text": str}]}
look_here     {"files": [str], "from": "review-verdict"|"design-committed"|null,
               "unavailable": str | null}
```

The parts, as `build_digest` computes them:

1. **What changed** (FR-003). No worklog: `error` is `no worklog recorded for this stream`.
   An unreadable worklog: `<worklog>: cannot be read`. No section: `no "## What changed"
   section in <worklog>`. A malformed section: `<worklog>:<line>: <reason>`.
2. **Decided alone** (FR-004). From the PRD: `parse_assumptions(text)`, then the items whose
   `end` is `None` or `"unconfirmed"`. `risky` is `is_risky(item)` (below). An item's text
   is `[<class>] <question> → <answer>`, as `render_assumptions` writes it, with no line
   number; `line` keeps it. A `SectionError` gives `error`
   `<prd>:<line>: <reason> — the PRD's assumptions were not read`; an unreadable PRD gives
   `<prd>: cannot be read`. No `clarify-passed` means no PRD: that half is empty, no error.
   From the journal: every `gate-decision` with `seq` above the last `clarify-passed`'s seq
   (every one when there is none), `data.mode == "executive"`, and `data.raised_by`
   `orchestrator` or absent (the shape's default). Its text is `_render_decision(data)` from
   `status.py`, the renderer the status brief and the handoff brief use. Order: risky PRD
   items in file order, then the journal items in seq order, then the other PRD items in
   file order.
3. **Deviations** (FR-005). Every `deviation` with `seq` above the last
   `design-committed`'s seq (every one when there is none), except `kind` in
   `(SIGNALS_MISSING_KIND, "style-missing", GATE_WAIVED)` and except every row whose data
   holds `report_to`. Its text is `data["note"]` when it is a string, else the first string
   of `correction` and `what` (the shape's aliases, for old rows), else `(no note)`. Seq
   order.
4. **Look here first** (FR-006). `position["trace"]["review_ranking"]`, else
   `["design_ranking"]`. From its `ranking`: a dict whose `source` is `none` gives
   `unavailable` = its `unavailable` string (or `none`); else the `path` strings of `files`,
   each through `_safe_ref` (an unsafe one is dropped), the first `LOOK_HERE_FILES`.
   Anything else, or no ranking, gives `files: []` and `from: null`.

**Changed: `shipgate/scripts/_journal/assumptions.py`** (no behaviour change):

- `scan_section(text, heading, title, noun, items_word)` is `_scan` with its four fixed words
  made parameters: the heading pattern, the heading text for the "a second … heading" error,
  the noun of "code block in the … section", and the words of "only … belong in this
  section". It returns the heading's line number (or `None`) and the items. `_scan` becomes a
  call of it with today's words, so every message of `journal.py assumptions` stays the same
  text, and `assumptions_report` still prints `section` as a boolean.
- `SectionError(ValueError)` with `line` and `reason`; `AssumptionError = SectionError`, kept
  as a name for #24's callers and tests.
- `is_risky(item)`: `(class in RISKY_CLASSES and source is None) or kind in
  ASSUMPTION_KINDS`. `risky_batch` keeps its own `end is None` check and calls it.

**The "What changed" form** (`parse_what_changed`): `scan_section` with the heading
`## What changed` (the regex `^## What changed\s*$`), the noun `what changed` and the words
`one-line list items`. So the section has the strict rules of #24: items `- ` or `* ` at
column 0, indented continuation lines joined with a space, blank lines, and nothing else;
a code fence, an indented item, a second heading or any other line is refused at its line.
Then two rules of its own: a section with no item is refused at the heading's line
(`no item in the section`), and a sixth item is refused at its line (`more than 5 items`).
An empty item is refused at its line (`empty item`).

**Changed: `shipgate/scripts/_journal/cli.py`.** A `digest` subcommand beside `handoff`:
`--stream` (required), `--all`, `--json`, `_add_db_flag`. `cmd_digest` mirrors
`cmd_position`: connect, `build_digest(conn, args.stream, resolution.project_dir,
artifact_homes(resolution.sidecar))`, close, then `json.dumps(doc, sort_keys=True)` or
`render_digest(doc, show_all=args.all)`. Exit 0; a stream with no events exits 1.

**Changed: `shipgate/skills/review/SKILL.md`.** Five places, the sentences under **Exact
text**. No other skill changes. The worklog template stays as it is (the lead's rule), so
#26's design changes do not collide.

## Exact text

### The digest (text form)

At most 16 lines, each through `_clip` (one line, at most 160 characters). `<n>` is a
part's full count; `<k>` its slot.

```text
<stream> — verdict <ready|not-ready> (round <r>) · publish <held|authorized>. What changed:
  - <item>                                          (1 to 5 lines)
decided alone (<n>):                                (n ≤ k, or with --all)
decided alone (<n>, <k> shown; --all prints every one):
  - <item>                                          (at most 4 lines)
deviations (<n>; notes in <worklog>):
deviations (<n>, <k> shown; --all prints every one; notes in <worklog>):
  - <note>                                          (at most 3 lines)
look here first: <path> · <path> · <path>
```

- With no verdict, the first line says `verdict —`.
- With a `what_changed.error`, the first line ends `What changed: — <error>` and no item line
  follows.
- A list part with no item is one line: `decided alone: none`, `deviations: none`.
- `decided.error` is the first item line of its part (`  - <error>`) and takes one slot.
- With no worklog, the deviations heading leaves out `; notes in <worklog>`.
- No ranking: `look here first: — no risk ranking recorded`. Source `none`:
  `look here first: — risk signals unavailable (<reason>)`.
- `--all` prints every item; the headings then read `(<n>):`. Lines stay clipped.

### The line cap, and how a part is added (for #26)

The list parts are one ordered tuple in `digest.py`:

```python
LIST_PARTS = (("decided", "decided alone", 4), ("deviations", "deviations", 3))
WHAT_CHANGED_SLOT = 5
LOOK_HERE_FILES = 3
```

`max_lines()` returns `1 + WHAT_CHANGED_SLOT + sum(1 + slot for each list part) + 1`: 16
today. A unit test pins 16. To add a part (the screenshot evidence of #26), add one entry to
`LIST_PARTS`, add its items to `build_digest` and `DigestDoc`, and change the pinned number
in the test: the cap grows by 1 + the new slot. A part with slot 2 makes it 19. #25 ships
with no such part.

### `review/SKILL.md`

**(a) Step 6, after the Ready / Not ready bullets — a new paragraph:**

> **Before a ready verdict, write what changed.** Give the worklog a `## What changed`
> section: 1 to 5 list items, one line each, that say what the change does for the person
> who uses it, not the build steps. The user reads them at the publish question, and the
> MR/PR Summary starts from them. After a fix round that changes what the change does,
> rewrite the section. `journal.py digest` accepts only this form and names the line it
> refuses.

**(b) Step 6, after the paragraph "Journaled: append `review-verdict` as you state the
verdict" — a new paragraph:**

> **Journaled: show the digest with a ready verdict.** After the verdict's append, run
> `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" digest --stream <branch>` and show its
> output under the verdict. The script computes what changed, what you decided alone, the
> deviations and the files to read first from the journal and the artifacts, so you do not
> retell them. A line that names `<file>:<line>` is a section the script could not read:
> fix that section and run it again.

**(c) The user's go, at the end of step 2 — added sentences:**

> For the `publish` gate, run the digest again just before you ask, and put its output, as
> printed, in the `preview` of the `Publish` option. The user may see only the dialog while
> it is open, and the preview shows what they approve. The recorder reads the answer, not
> the preview. A multi-select question has no preview: print each stream's digest above it.

**(d) The user's go, the paragraph "A session that asks the user about another session's
stream …" — added after its first sentence:**

> It runs the digest for that stream with the other session's worktree as its working
> directory (`cd <worktree> && python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" digest
> --stream <stream>`), because the PRD and the worklog are uncommitted there. A session that
> reports to a lead sends, with its ready verdict, its stream name and its worktree path,
> not the digest text.

**(e) Opening the MR/PR, the Summary bullet — replaced:**

> - **Summary** ← the worklog's What changed section, then the PRD for the why.

## Data flow

```text
review Step 6 ── writes ──▶ worklog "## What changed"
              ── appends ─▶ review-verdict (ranking)                  ┐
journal (events) + PRD + worklog ── build_digest ──▶ DigestDoc ──▶ render_digest
                                                                       │
            verdict text (terminal) ◀──────────────────────────────────┤
            Publish option preview (AskUserQuestion) ◀─────────────────┘
                     │ the user's answer
                     ▼
            recorder (hooks/reply.py, unchanged) ──▶ gate-decision go ──▶ push, PR
```

The digest reads only. The go path is the one of ADR 0023; nothing in it reads the digest.

## Data model / schema

No new event, no new event field, no new setting, no schema change. `settings.schema.json`
does not change.

## API / contract changes

- New command: `journal.py digest --stream S [--all] [--json]`. Exit 0 with or without
  content errors; 1 for a stream with no events or an unreadable database; 2 for a usage
  error. `--json` is the contract for programs; the text is for people.
- `assumptions.py`: `scan_section`, `SectionError` and `is_risky` are new names;
  `AssumptionError` stays. `journal.py assumptions` keeps every message and exit code.

## Reference implementation

`shipgate/scripts/_journal/handoff.py` for the build and render split: a `TypedDict` built
from `build_position` and the stream's events, rendered by a function that passes every
value through `_clip` or `_one_line` (ADR 0021, #39). `cmd_position` in `cli.py` for the
`--json` switch. Both precedents are young (2 commits each); `handoff.py` has a fix rate of
0.0 and `position.py` 0.5 at a fan-in of 3, so `handoff.py` is the anatomy to mirror. The
tests mirror `shipgate/tests/test_journal_handoff.py`: a `JournalTestCase` with a temp
database, a sidecar with `artifact_homes`, files written with a `write` helper, and the
command run through `run_journal`.

## Risk ranking

`signals.py hotspots` over the existing files the plan changes (source `graph`):

| file | commits | fix rate | risk |
|------|---------|----------|------|
| `.claude-plugin/marketplace.json` | 77 | 0.43 | top |
| `shipgate/CHANGELOG.md` | 54 | 0.52 | top |
| `shipgate/.claude-plugin/plugin.json` | 55 | 0.47 | top |
| `shipgate/README.md` | 50 | 0.38 | top |
| `shipgate/skills/review/SKILL.md` | 32 | 0.28 | top |
| `shipgate/tests/test_prose.py` | 9 | 0.44 | top |
| `shipgate/scripts/_journal/cli.py` | 5 | 0.20 | high |
| `.claude/shipgate.json` | 2 | 0.00 | mid |
| `shipgate/scripts/_journal/assumptions.py` | 1 | 0.00 | low |

The version files and the changelog are hot because every release edits them; they take no
behaviour. The behaviour files at `top` or `high` are `review/SKILL.md` and `cli.py`: T002
pins their current behaviour before the change. `assumptions.py` is low, but #24's 47 tests
already pin it, and T003 keeps them unchanged.

## Pre-mortem

Assume this shipped and the user approved a publish they should have stopped. Why?

1. **The "What changed" section was stale** from an earlier round. Mitigation: sentence (a)
   tells the review to rewrite it after a fix round; the digest prints whatever is there, so
   the user sees it.
2. **The preview did not render** in the user's client, or a multi-select had none.
   Mitigation: the digest also prints with the verdict (b), and a multi-select prints the
   digests above the question (c).
3. **A planted payload forged lines** in the dialog. Mitigation: every value passes
   `_one_line` and `_clip`; unsafe refs are dropped (SC-007).
4. **The cap hid the item that mattered.** Mitigation: the heading names the full count and
   `--all`; risky PRD items come first.

## What the digest does not show

- No rationale, source tag, kind tag or end tag of an assumption; no event field other than
  those named above; no file content other than the parsed section lines.
- Every value is one line of at most 160 characters. Refs that are absolute or hold `..` are
  dropped. The digest prints into a terminal and a dialog, never into the repo.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/scripts/_journal/` (the journal package, ADR 0027); the skill
  text in `shipgate/skills/review/`.
- Python 3.9: no `match`, no runtime `X | Y`; `from __future__ import annotations` as in the
  other modules.
- Tests: `python3 -m unittest discover -s shipgate/tests` from the repo root, never `-t .`.
- A behaviour change bumps `shipgate/.claude-plugin/plugin.json` and the matching entry in
  `.claude-plugin/marketplace.json` in the same change; release notes live only in
  `shipgate/CHANGELOG.md`.
- Public repo: no private name, path, tracker id or handle in any file, test fixture or
  commit message (root `CLAUDE.md`, "Public repo"). Fixtures use `feature/demo`, `#1234`.
- No schema, no flag, no hook. Security-sensitive areas: none touched (no hook, nothing
  outside the plugin directory is written).

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.
A task line is a `-` or `*` bullet, a box, then the id: `T` and digits, bare (`T001`) or
bold (`**T001**` or `**T001:**`). The title follows, after an optional dash or colon:
`- [ ] T001 — title`, `- [ ] **T001** title`, `- [ ] **T001**: title`. A line in any other
form is not a task, so the HUD's Plan tab and the Stop gate both skip it.

## Setup / foundations

- [x] T001 [P] — The project settings ship the user's `clarify_confirm` choice — file(s): `.claude/shipgate.json` — add `"clarify_confirm": "risky"` after `"forge": "github"` (with the comma), the same line the main checkout holds uncommitted — done when: `journal.py config clarify_confirm` in the worktree prints `risky` from the project file.
- [x] T002 — Pin the behaviour of the top and high files before any edit — file(s): `shipgate/tests/test_prose.py`, `shipgate/tests/test_journal.py` (or the cli tests that exist) — run the full suite first and note its counts; add a prose pin that the review's go steps 1 to 4 and the Summary bullet still read as today, and a cli pin that `journal.py --help` lists today's subcommands, only where no existing test pins them — done when: the suite passes with the pins, before any other change.
- [x] T003 — Extract the section scanner — file(s): `shipgate/scripts/_journal/assumptions.py`, `shipgate/tests/test_journal_assumptions.py` — `scan_section`, `SectionError` with the `AssumptionError` alias, `is_risky` (Design: Architecture) — done when: the 47 existing assumption tests pass unchanged, and new tests run `scan_section` with another heading and see each refusal at its line.

## Feature

- [x] T010 — Tests first for the digest — file(s): `shipgate/tests/test_journal_digest.py` (new) — a `JournalTestCase` as in `test_journal_handoff.py`, covering: the first line (verdict and round, no verdict, publish held and authorized); "What changed" (1 and 5 items, a sixth item, an empty section, a prose line, a code fence, a second heading, no section, no worklog, an unreadable worklog), each error with its `<worklog>:<line>`; "decided alone" (end tags kept and changed left out, `[unconfirmed]` kept, risky first, gate decisions after the last `clarify-passed` only, `mode: ask` and `raised_by: user` left out, no `clarify-passed` gives every executive decision, a PRD in the form before #24 gives one error line and exit 0); "deviations" (the window after the last `design-committed`, the three bookkeeping kinds and `report_to` rows left out, the alias fallback); "look here first" (the verdict's ranking, the design's as fallback, source `none`, no ranking, an unsafe path dropped); the slots and the headings over a slot; `--all`; `--json` keys; `max_lines()` is 16; a stream with no events exits 1; hostile payloads (newlines, 1000 characters) give lines of at most 160 characters and no extra line — done when: the tests fail for the missing command, nothing else.
- [x] T011 — Build the digest and its command — file(s): `shipgate/scripts/_journal/digest.py` (new), `shipgate/scripts/_journal/cli.py` — Design: Architecture and Exact text; the `digest` subcommand's help names the four parts and the exit codes — done when: T010 passes and the full suite passes.
- [x] T012 — Measure the run time — file(s): none (the worklog's Deviations & notes) — run `time python3 shipgate/scripts/journal.py digest --stream <the stream with the most events in this repo's journal>` (find it with `journal.py stats` or a count over `log`) — done when: it finishes in under 1 second, and the worklog records the stream's event count and the time (counts only).

## Skill and docs

- [x] T020 — Prose tests first for the review text — file(s): `shipgate/tests/test_prose.py` — one test each for sentences (a) to (e) of Exact text: the `## What changed` section with "1 to 5", the digest command at the verdict, the `preview` of the `Publish` option, the worktree path a teammate sends, and the Summary bullet — done when: the five tests fail, nothing else.
- [x] T021 — Edit the review skill — file(s): `shipgate/skills/review/SKILL.md` — insert (a) to (e) as written under Exact text, in STE-80 — done when: T020 and T002's pins pass.
- [x] T022 [P] — Docs and version — file(s): `shipgate/README.md` (a `digest --stream S [--all] [--json]` row in the Flow journal command table, after `handoff`), `shipgate/CHANGELOG.md` (a `v0.35.0` entry: the digest, the "What changed" section, the publish question's preview; no hook or HUD change), `shipgate/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (0.35.0) — done when: the versions match, the README row names the parts and the flags, and the changelog holds the only release notes.

## Polish

- [x] T030 — Final checks — file(s): none — the full suite (`python3 -m unittest discover -s shipgate/tests` from the repo root); `git diff --stat -- shipgate/hooks shipgate-hud` prints nothing (SC-003); a grep of the diff for private project names, tracker id patterns and private paths finds none; the new prose reads as STE-80 — done when: all four hold, each with its output in the verify-run.
- [x] T031 — Review round 2: an unusable worklog ref says so — file(s): `shipgate/scripts/_journal/digest.py`, `shipgate/tests/test_journal_digest.py`, `shipgate/CHANGELOG.md` — a worklog ref that `_plain_ref` refuses prints a fixed line, never the ref; a test with a space in a real worklog path; a test of `publish held` after a `task-done` that follows the user's go; one CHANGELOG sentence on the limit — done when: the digest tests pass on both Pythons and the full suite passes.
- [x] T032 — The digest is a chat message, not a preview (the user's decision after the first dialog) — file(s): `shipgate/skills/review/SKILL.md`, `shipgate/tests/test_prose.py`, the PRD, ADR 0030, `shipgate/CHANGELOG.md`, this worklog — the session prints the digest as a message right before the Publish question; the option carries no preview; the preview sentences and the multi-select special case go — done when: the prose tests pass and the full suite passes.
- [x] T033 — The digest is one markdown table with slots 3, 2 and 2 (the user's decisions after the second dialog) — file(s): `shipgate/scripts/_journal/digest.py`, `shipgate/scripts/_journal/cli.py`, `shipgate/tests/test_journal_digest.py`, `shipgate/skills/review/SKILL.md`, `shipgate/tests/test_prose.py`, the PRD, ADR 0030, `shipgate/README.md`, `shipgate/CHANGELOG.md`, this worklog — one renderer (the old line form goes), a fixed set of markdown characters escaped in every cell, hostile values tested in every part, one skill sentence with its pin — done when: the digest and prose tests pass on both Pythons and the full suite passes.
- [x] T034 — Say "no link that hides its target" — file(s): the PRD (FR-008), `shipgate/CHANGELOG.md`, the module docstring of `shipgate/scripts/_journal/digest.py` — a bare URL or an email can still autolink, and its text is the URL itself; three wording lines, no code — done when: the digest and prose tests pass.

## Traceability

- FR-001 → T010, T011
- FR-002 → T010, T011
- FR-003 → T003, T010, T011, T021 (sentence a)
- FR-004 → T003, T010, T011
- FR-005 → T010, T011
- FR-006 → T010, T011
- FR-007 → T010, T011
- FR-008 → T010, T011
- FR-009 → T010, T011
- FR-010 → T010, T011
- FR-011 → T020, T021 (sentence b)
- FR-012 → T020, T021 (sentence c)
- FR-013 → T020, T021 (sentence d)
- FR-014 → T002, T030
- FR-015 → T020, T021 (sentence e)
- SC-001 → T010
- SC-002 → T010
- SC-003 → T030
- SC-004 → T020, T021
- SC-005 → the review of this stream: it writes this worklog's What changed section, runs the digest and quotes it
- SC-006 → T012
- SC-007 → T010

## What changed

- Before a publish, you read one short table: what changed, what was decided alone, the deviations and the files to read first.
- `journal.py digest --stream S` computes it from the journal and the artifacts; `--all` prints every item, `--json` the data.
- The review writes a `## What changed` section of 1 to 5 one-line items and prints the table as a message before the Publish question.

## Deviations & notes (filled during implementation)

- 2026-11-25 — T002: the baseline suite ran 2044 tests, OK (2 skipped), in 887 s. The
  review's go steps 1 to 4 and the MR/PR bullets had no pin; `TestReviewGoPins` adds them.
  `journal.py --help` had no pin of its subcommands; `test_help_lists_the_subcommands` adds
  it.
- 2026-11-25 — T012: `journal.py digest --stream shipgate` (913 events, the largest stream in
  this repo's journal) ran in 0.11 s, three runs, while the full suite ran beside it. A
  work stream of 133 events ran in 0.09 s.
- 2026-11-25 — deviation: `parse_what_changed` returns `None` when the worklog has no
  section, not an empty list. "No section" and "a malformed section" give different error
  text, and an empty section is refused, so the caller must tell the cases apart.
- 2026-11-25 — deviation: the digest prints each value through its own `_line`, not
  `_clip` alone. `_clip` gives 160 characters to the value, so `  - ` plus a clipped item
  was 164. `_line` clips the prefix and the value together. It also replaces each character
  that is still not printable after `_one_line` (ESC, a bidi override) with U+FFFD, so a
  planted terminal sequence cannot move the cursor or reorder a line (SC-007, pre-mortem 3).
  The status and handoff briefs keep `_clip`; their gap goes to the lead as a note.
- 2026-11-25 — deviation: a ranking whose files are all unsafe refs gives `from: null`, the
  same as no ranking, so the line reads `— no risk ranking recorded`. The design named two
  no-file lines only; a third text for a hostile ranking was not worth a form of its own.
- 2026-11-25 — note: the top-level help's exit-code 1 line now names `handoff` and `digest`
  beside `position`. Both exit 1 for a stream with no events; the line named one.
- 2026-11-25 — note: `build_position` reads the worklog with `read_text`, so a worklog ref
  that is a FIFO blocks `position`, `handoff` and `digest`. That is older than this change
  and goes to the lead as a note; the digest reads its two files the same way.
- 2026-11-25 — deviation (review round 1, F3): the first line names the user's publish go
  (`position.go.publish`), not `position.publish`. A ready verdict opens the journal's
  publish gate, so the old source said `publish authorized` at the very question that asks
  for the go. The design's `DigestDoc.publish` line read `position["publish"]["kind"]`.
- 2026-11-25 — deviation (review round 1, F1, F2, F4): the digest takes a ref only when it
  is `_safe_ref` and holds no whitespace and no character that is not printable
  (`_plain_ref`). That applies to the ranking paths, the worklog and the PRD. A
  `clarify-passed` whose PRD ref is not usable gives one error line in "decided alone", so
  the PRD half is never empty without a word.
- 2026-11-25 — deviation (T032, the user's decision after the first real dialog): the digest
  is a chat message right before the Publish question, not the option's preview (ADR 0030,
  amendment). Sentence (c) and FR-012 changed; the multi-select case went. The Exact text,
  the data flow and pre-mortem 2 above still show the first form, as the design was written.
- 2026-11-25 — deviation (T033, the user's decisions after the second dialog): the digest
  is one markdown table with slots 3, 2 and 2 and a Look first row, at most 10 lines (ADR
  0030, second amendment). The old line form is gone. Each cell value is escaped from a
  fixed set of markdown characters. The Deviations part no longer names the worklog.
- 2026-11-25 — note for #26: its Screens part is one more entry in `PARTS` with its own
  slot, and its items in `build_digest` and `DigestDoc`. The cap grows by that slot only,
  since a part has no heading row: a slot of 2 makes it 12. Change the pinned number in
  `test_the_row_cap_is_computed_from_the_slots`.
- 2026-11-25 — judged by reading (no eval, F8 A): sentences (a) to (e) name the command, its
  arguments and the place of the output, and each gives the reason it exists. An Opus or a
  Fable session reads them as steps it can follow; no step depends on a judgment call the
  script could make. The worklog section rule is the one place the model writes text, and
  the script refuses any other form with a line number, so a wrong form costs one rerun.

## Rejected findings

Filled during review: findings the orchestrator killed on evidence, and why — so a
later round doesn't re-litigate them.

## Review round 1

Workflow run `wf_dfff4e15-119`, lenses correctness, conventions+design and
simplicity+security: 25 found, 22 after dedupe, 8 candidates, 2 refuters, 8 survivors, 0
killed, 14 below the floor of 60. The briefed security reviewer read the 17 changed files
and reported no finding at confidence 8 or above.

- F1 HIGH `scripts/_journal/digest.py:225` — a ranking path with leading whitespace, such as ` /home/alice/x.py`, passed `_safe_ref` and printed as an absolute path; fixed by `_plain_ref`.
- F2 MEDIUM `scripts/_journal/digest.py:305` — one ranking path that holds ` · ` printed as several files, absolute ones among them; fixed by `_plain_ref`.
- F3 MEDIUM `scripts/_journal/digest.py:246` — the first line said `publish authorized` after any ready verdict, at the question that asks for the go; it now names the user's publish go.
- F4 MEDIUM `scripts/_journal/digest.py:161` — a `clarify-passed` with an unusable PRD ref emptied the PRD half with no word; it now prints one error line.
- F5 LOW `scripts/_journal/digest.py:120` — an empty bullet line with an indented continuation passed the empty-item rule; it is now refused at its line.
- F6 LOW `scripts/_journal/digest.py:196` — a blank deviation note printed an empty item; a blank note now falls through to the aliases and `(no note)`.
- F7 LOW `prd/publish-digest.worklog.md:11` — the front matter said `status: designing`; it says `review`.

### Deferred

- `_journal/assumptions.py:91` (LOW 65): section line numbers count `str.splitlines` breaks (U+2028, U+0085), not editor lines. The rule is #24's and `journal.py assumptions` shares it; a note goes to the lead.
- `_journal/digest.py:256` (HIGH 50): `_line` does not neutralize markdown, and the preview renders markdown. Every line starts with fixed text, and the security reviewer rated the breakout at 3 of 10 with the renderer unverified; a note goes to the lead.
- `review/SKILL.md:420` (LOW 45): sentence (b) says to fix a section the digest cannot read, and ADR 0030 says PRDs from before #24 are not rewritten. Wording, deferred to #32.
- `_journal/digest.py:36` (LOW 35): a `## What changed` line inside a fence elsewhere counts as a heading. The scanner reads no fence by #24's rule.
- `review/SKILL.md:684` (LOW 25) and `review/SKILL.md:411` (LOW 30): the teammate's worktree path in a shell command, and digest text as tool output with no data label. The same pattern stands in other skill steps.

### Rejected findings

- `_journal/digest.py:230` (MEDIUM 70): a review ranking with no usable file does not fall back to the design ranking. FR-006 and the Design take the newest verdict's ranking when one exists; the line then says no ranking.
- `_journal/digest.py:218` (LOW 40): the same claim as the one above.
- `_journal/digest.py:34` (LOW 50): `style-missing` is a literal. vocab has no constant for it.
- `tests/test_journal.py:264` (LOW 45): the help pin does not list `digest`. It pins 0.34.1's commands; `test_help_names_the_command_its_parts_and_exit_codes` pins `digest`.
- `_journal/digest.py:180` (LOW 45): `_render_decision` can print raw fields of an old row. The Design names `_render_decision`, the renderer of the status and handoff briefs; the line is clipped and filtered.
- `_journal/digest.py:55` (LOW 40): two fields typed `str` for closed sets. No behaviour; the `--json` tests pin the values.
- `_journal/digest.py:239` (LOW 30): two reads outside one transaction. The journal only appends and the digest is a view.
- `_journal/digest.py:262` (LOW 30): `isprintable` replaces ZWJ and other format characters. That is the rule against bidi overrides; the cost is a U+FFFD in an emoji.
- `_journal/digest.py:28` (LOW 25): `LIST_PARTS` is generality for #26. The Design and the lead ask for it.

## Review round 2

The re-review of round 1's fix diff confirmed F1 to F7 fixed, each with a test. It found one
new MEDIUM and four LOW. The lead decided the round (an executive gate-decision): keep the
strict refusal and say why, with no new tolerance.

- F8 MEDIUM `scripts/_journal/digest.py:259` — `_plain_ref` refuses a worklog path with a space, and the digest then said `no worklog recorded for this stream`, which is false; it now prints a fixed line that the ref is not usable, and never the ref (T031).
- F9 LOW `tests/test_journal_digest.py:215` — no test pinned `publish held` after a `task-done` that follows the user's go; the test now does (T031).

### Deferred

- `_journal/digest.py:88` (LOW 70): `--json` `publish` is the user's go in `digest` and the journal's publish gate in `status` and `position`. Deferred to #32 with the line's wording.
- `_journal/digest.py:314` (LOW 60): at the publish question the first line always reads `publish held`. True, and it carries no news there. Deferred to #32.
- `_journal/position.py:401` (LOW 75): `status` and `position` print refs through `_one_line` only, so ` /home/x` prints as an absolute path. Older than this change; a note goes to the lead.

### Re-review of round 2

One fresh reviewer on the round 2 fix diff confirmed F8 and F9 fixed: the fixed line holds
no ref, and the `--json` dump, the `notes in` note and the exit code leak nothing. It found
two LOW, both deferred to #32 with the other wording:

- `_journal/digest.py:155` (LOW 70): the fixed line and the CHANGELOG sentence name "whitespace or a control character", but `_plain_ref` also refuses format, private-use and unassigned characters (U+200B, U+E000). The refusal is right; the stated cause is too narrow.
- `_journal/digest.py:182` (LOW 55): the PRD line gives no cause and the worklog line does. Not false.

## Review round 3

T032, the chat-message follow-up. One fresh reviewer read the diff; the skill text gives one
form for every question, and no preview instruction is left. The lead ruled on the findings
and read the fix himself, so no second reviewer ran.

- F10 MEDIUM `docs/adr/0030-the-publish-digest-is-computed-and-rides-the-publish-question.md:163` — the amendment left the first Consequence and the F2 line false ("in the dialog") and did not name option D; two sentences in the amendment now do both.
- F11 LOW `tests/test_prose.py:664` — the class docstring still said "puts it in the publish question"; fixed.
- F12 LOW `shipgate/CHANGELOG.md:22` — the entry read as if the digest prints twice; fixed.

### Deferred

- `prd/publish-digest.md:180` (LOW 70): two executive assumption lines say "in the dialog". They stay as the record of what was assumed.
- `review/SKILL.md:668` (LOW 35): a chat message renders as markdown, so "as printed" is not exact. Step 6 (b) had the same gap before. Deferred to #32.

## Review round 4

T033, the markdown table. One fresh reviewer with all lenses and the security criteria
could forge no row, column, code span, image, HTML, entity, emphasis, strikethrough, math
or heading with any input. It found no BLOCKER, HIGH or MEDIUM. The eight LOW findings
are deferred, as the lead's rule says:

### Deferred

- `prd/publish-digest.md:131` (LOW 75): FR-008, the CHANGELOG and the module docstring said no link can appear, but a bare URL or email still becomes a link in a GFM renderer. Fixed by the lead's decision in T034: the three now say "no link that hides its target".
- `_journal/digest.py:40` (LOW 30): `\[` and `\]` are display-math delimiters in some renderers. No surface in use renders LaTeX.
- `tests/test_journal_digest.py:602` (LOW 60): no hostile test of the Look first `unavailable` reason or of an error row whose ref holds markdown characters. The code escapes both today.
- `_journal/digest.py:323` (LOW 25): an empty stream name gives two bare backticks.
- `_journal/digest.py:380` (LOW 30): the header's stream room is measured on the state before escaping; the state is a fixed vocabulary today.
- `tests/test_journal_digest.py:727` (LOW 40): `assert_safe` finds the header row by object identity.
- `prd/publish-digest.md:128` (LOW 35): FR-008 says each value is clipped at 160; each line is.
- `review/SKILL.md:419` (LOW 30): an error row shows its path markdown-escaped; `--json` has the raw path.

