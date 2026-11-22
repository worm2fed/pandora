---
type: worklog
title: "Worklog: the security review sees the change before and after the commit"
created: 2026-11-21
updated: 2026-11-22
tags:
  - worklog
  - shipgate
  - review
  - journal
status: done
prd: none — scoped change (#40); the issue body holds the four proposals
related: []
---

# Worklog: the security review sees the change before and after the commit

Issue #40, a child of #37. `feature` and `review` fire the built-in `/security-review` for a
change in a security-sensitive area. Review runs before the commit, and the built-in command
reads only commits, so its diff is empty there and it reports no finding on no code.

---

# Design

## Approach

Accepted by the user (relayed by the lead): the review runs in two passes, and the verdict
names the pass that ran.

- **Before the commit:** one briefed reviewer with the built-in command's criteria reads the
  working-tree diff and every untracked file the change adds. The reviewer reports the files
  it read; the orchestrator checks that count against the changed files.
- **After the commit, before the push:** the built-in command runs on the commit. A finding
  is a not-ready verdict and a fix round.
- **The record:** `review-verdict` takes `security_review {kind, files, ref}`. The built-in
  run on the commit is a second verdict.

The briefed pass touches no git state. It does not mark new files with `git add -N`, detach
another worktree at a commit, or make a commit for the review. There is no state-free way to
give the built-in command a diff before the commit: its FILES MODIFIED, COMMITS and DIFF
CONTENT sections are taken from the branch's commits against `origin/HEAD`. So the built-in
run waits for the commit.

Observations behind it, as counts: in four flows of this epic the built-in capture was empty
before the commit each time. Each flow then briefed one reviewer on `git diff origin/main`
and reran the built-in command on the commit. Twice that rerun found something the briefed
reviewer had not. The command, loaded on this branch for its criteria, showed the same empty
sections a fifth time.

## Data model / schema

`review-verdict` gains an optional object `security_review`:

| key | type | meaning |
|-----|------|---------|
| `kind` | `builtin`, `briefed` or `none` | required: which security review ran |
| `files` | non-negative integer | the files it read; required, and at least 1, for `builtin` and `briefed` |
| `ref` | string | the commit the built-in command read |

`append` refuses `builtin` or `briefed` without `files` or with `files: 0`: a review that
read nothing is not a review. Like the shape, `--force` does not waive the check. Rows
written before this release carry no `security_review` and stay valid.

## API / contract changes

One optional verdict key, and one publish-rule change (T007, F1/F3, the user's choice):
`publish_authorization` reads the newest verdict after the last `task-done`, skipping a
forced ready, so a later `not-ready` holds `mr-opened` and the `publish` value of `status`,
`position` and the HUD. The user's publish go is unchanged. No hook, hook contract or event
type changes. The user chose no hook change (Q3): the command gate does not hold a push until a
built-in record exists. A follow-up issue for that is filed with the PR, after the user's go.

## CLAUDE.md / impact-map compliance

- Plugin: shipgate only. Version 0.29.0, the next free above 0.28.2 (#22 0.28.0, #52
  0.28.1, #55 0.28.2 merged first); `plugin.json` and `marketplace.json` in lockstep.
- No hooks touched, so the configured security-sensitive area is not in the diff.
- Public repo: no private names, paths or tracker ids in any file.

---

# Build Plan

## Feature
- [x] T001 — `security_review` on `review-verdict`: the sub-shape, the files-0 refusal, the payload TypedDict — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: the new tests fail first, then pass
- [x] T002 — `review` names the two passes, the input-count check and the record — file(s): `shipgate/skills/review/SKILL.md` — done when: the text names the briefed pass, the count check, the built-in run on the commit before the push, and the `security_review` key
- [x] T003 [P] — `verify` lists the empty-input case — file(s): `shipgate/skills/verify/SKILL.md` — done when: the claim table and gate step 4 name a review that read 0 files; the description is unchanged
- [x] T004 [P] — `feature` points at the two passes — file(s): `shipgate/skills/feature/SKILL.md` — done when: the security-review bullet says the diff is empty before the commit and points at `review`

## Polish
- [x] T005 — CHANGELOG entry and the 0.29.0 bump after the rebase onto `origin/main` — file(s): `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: both versions read 0.29.0 and `claude plugin validate` passes
- [x] T007 — the publish rule reads the newest `review-verdict` after the last `task-done`, so a later `not-ready` holds publishing (F1, the user's choice); written after the rebase onto #22, which rewrites `publish_authorization` — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py`, `shipgate/README.md`, `shipgate/CHANGELOG.md` — done when: a ready, then not-ready, then `mr-opened` test fails first, then passes; the CHANGELOG names the publish-gate change
- [x] T006 — full suite — file(s): none — done when: `python3 -m unittest discover -s shipgate/tests` passes

## Traceability
- Issue proposal 1 (review: check the diff, brief a reviewer, say so) → T002
- Issue proposal 2 (built-in on the commit before the MR/PR) → T002, T004
- Issue proposal 3 (verdict records kind and files) → T001, T002
- Issue proposal 4 (verify: the empty-input case) → T003

## Deviations & notes (filled during implementation)

- 2026-11-21 — #22 (0.28.0) is still open, so T005 holds the CHANGELOG entry only; the
  rebase and the 0.29.0 bump wait for it.

## Review round 1

Workflow run `wf_138a3ff6-dd4`, lenses correctness and conventions+design, refuters on
HIGH only: 21 found, 18 after dedupe, 7 above the floor of 60, 6 refuters, 0 killed. No
security review was owed: the diff touches no hook and nothing outside the plugin.

- F1 HIGH `shipgate/skills/review/SKILL.md:183` — a `not-ready` verdict from the built-in run on the commit does not hold publishing: `publish_authorization` takes the first ready verdict after the last `task-done`, so the earlier ready still authorizes `mr-opened` and the HUD shows publish as authorized. The fix changes the released publish gate; the user chose "the newest verdict decides": fixed by T007 after the rebase onto #22, with four tests that failed first.
- F3 HIGH `shipgate/skills/review/SKILL.md:182` — the same gap, reported by the second lens; merged with F1.
- F2 HIGH `shipgate/skills/review/SKILL.md:556` — the second verdict, as the example showed it, carried no `criteria` or `dispositions`, and the HUD draws the newest verdict only. Fixed: the second verdict copies `criteria`, `dispositions` and `ranking`, and the text says it counts as a review round.
- F4 MEDIUM `shipgate/skills/review/SKILL.md:180` — the built-in run on the commit was named only in Step 1. Fixed: **Opening the MR/PR** names it.
- F5 MEDIUM `shipgate/skills/review/SKILL.md:181` — nothing said how the fix round after a built-in finding lands. Fixed: push nothing until the fix round ends; the fix is a new commit on the user's commit go, and the command runs again on it.
- F6 LOW `shipgate/scripts/journal.py:250` — a `builtin` review without `ref` was accepted. Fixed: `check_security_review` refuses it; the test failed first (3 failures), then passed.
- F7 LOW `shipgate/skills/review/SKILL.md:548` — the text did not say when to leave `security_review` out and when to record `none`. Fixed: a change that owed none leaves the key out; `none` records an owed review that did not run.
- Below the floor, taken: deleted files left the count (`--diff-filter=d`); "This security lens" under the new heading reads "The security lens above"; the run on the commit is named an audit, not a second self-check; the CHANGELOG says "the number of files"; the verify row is one short fragment; the feature sentence is split; the docstring names the import case.

## Review round 2

One code-reviewer with every lens, on the round-1 fixes, the merge with #22 (0.28.0) and
T007. Every round-1 finding is confirmed fixed on evidence: F1/F3 by T007 and its four tests,
F2 at the second-verdict paragraph, F4 under **Opening the MR/PR**, F5 in step 3, F6 by
`test_a_builtin_security_review_names_its_commit`, F7 at the `security_review` list, and the
below-floor items. The suite parts it ran passed: 53 tests.

- R1 MEDIUM `shipgate/scripts/journal.py:1524` — the newest-verdict rule let a forced ready hide an earlier ready one, against ADR 0023 §17 ("skips a forced verdict"). Fixed: the newest verdict skips a forced ready, and a not-ready holds whether forced or not; `test_the_newest_verdict_rule_skips_a_forced_ready_verdict` failed first, then passed.
- R2 MEDIUM `shipgate/skills/review/SKILL.md:183` — a publish go asked before the built-in run still covers the push after a finding, so "holds publishing again" overclaimed. Fixed: a new step 4 asks the commit go before the commit and the publish go only after the built-in run's ready verdict; the fix commit takes a new commit go; the publish paragraph names the go exception.
- R3 LOW `shipgate/skills/review/SKILL.md:567` — the second verdict could collide with the two-round cap. Fixed: it counts for `round` numbering, not for the cap.
- R4 LOW `shipgate/skills/feature/SKILL.md:301` — the publish rule there lacked "newest". Fixed.
- R5 LOW `shipgate-hud/hooks/publish.ts:1104` — the HUD's hold text and README still describe a missing ready verdict after a ready then not-ready. Its behaviour follows `publish` from journal.py. Deferred to the hook follow-up issue, filed with the PR: a hook text change bumps shipgate-hud.
- R6 LOW `shipgate/docs/prd/security-review-diff.worklog.md:?` — the design section said no rule changes. Fixed.
- R7 LOW `shipgate/README.md:212` — wrap width in README, feature and the refusal string. Fixed.

## Review round 3

The orchestrator alone, because the round-2 fix diff is a few lines in five files: R1 is
pinned by its new test, R2 to R4 and R6 to R7 read right at the cited lines, and R5 is
deferred to the hook follow-up issue. The full suite passed on origin/main 420c329 with the
fixes: 1517 tests OK, 2 skipped. Verdict: ready. #52 (0.28.1) still merges before the
commit, so one more rebase and suite run come before it.

## Rebase onto 0.28.2 and review round 4

Moved onto `origin/main` 2d7c587 (0.28.2) by the stash route the lead approved: a scratchpad
backup of 10 files, a tagged stash, a fast-forward, the stash applied by its sha, the index
restored, and only that stash entry dropped. Five files conflicted:

- `plugin.json`, `marketplace.json`: kept 0.29.0.
- `CHANGELOG.md`: v0.29.0 above v0.28.2, every earlier entry intact.
- `journal.py` `MR_OPENED_REFUSAL`: #55's text, with the newest-verdict wording.
- `feature/SKILL.md`: #52's confirming-question text, with the newest-verdict wording.

One code-reviewer with every lens checked the five resolutions against `origin/main` and the
#40 steps against #52's go flow: the rebase is clean, nothing of #52 or #55 is lost, and no
#40 text assumes the removed read go. Three LOW findings, all fixed:

- L1 LOW `shipgate/README.md:204` — the #40 lines of the journal paragraph broke the wrap width again. Fixed.
- L2 LOW `shipgate/scripts/journal.py:1486` — "a newest review-verdict" read badly in the refusal and in `feature`. Fixed: "the newest review-verdict, with verdict=ready and not forced".
- L3 LOW `shipgate/docs/prd/security-review-diff.worklog.md:76` — no entry for this rebase, and the version line named 0.28.0. Fixed by this entry.

## Rejected findings

- `shipgate/scripts/journal.py:1455` (LOW 45): `check_security_review` hardcodes the kinds instead of a data table. One verdict key with two rules does not earn a table like `LOCATION_KEYED_MAPS`.
- `shipgate/scripts/journal.py:250` (LOW 60, part of F6): a `none` review with `files` above 0 is accepted. Harmless: no gate reads `files` on `none`.
