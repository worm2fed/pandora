---
type: worklog
title: "Worklog: an honest verify-run is matched to its observed run"
created: 2026-11-26
updated: 2026-11-26
tags:
  - worklog
  - shipgate
  - verify
  - hooks
status: review
issue: "#81 (shipgate), child of #37"
related:
  - "../adr/0032-the-bash-hooks-log-each-observed-run-by-session.md"
  - "../adr/0033-a-verify-run-names-its-commands-and-the-journal-records-what-it-saw.md"
  - "./observed-verify-run.md"
  - "./observed-verify-run.worklog.md"
---

# Worklog: an honest verify-run is matched to its observed run

> Issue #81, a scoped fix to #27. No PRD: the amendments of #81 to ADR 0032 (where the log
> lives, the key) and ADR 0033 (the notice) hold the decisions. This file holds the short
> design, the build plan and the measurements.

---

# Design

## Approach

A probe came first (ADR 0032, amendment of #81, holds its facts). Two causes are fixed in
code, and one stays documentation:

1. **The base.** The hooks read `CLAUDE_CONFIG_DIR` from their own environment. The journal
   read it from the Bash shell, where a shell profile can set it to another directory. Fix:
   the run log's base is `$HOME/.claude`, and `CLAUDE_CONFIG_DIR` is not read for it.
   `HOME` is the same on both sides.
2. **The `cd` prefix.** Claude Code removes one leading `cd <cwd> && ` before PreToolUse
   sees the command. Fix: `run_fingerprint` removes each leading `cd <word> && ` on both
   sides before it hashes.
3. **A run past the time limit** moves to the background, and no hook sees it end. This
   stays documentation. The not-observed notice now names it.

The notice names the cause per command: no session id, no log under the root, or no run.

## Decisions on record

| Fork | Decision | Who | Journal |
| --- | --- | --- | --- |
| F1 base | `$HOME/.claude/shipgate/runs`; evidence root unchanged; tests isolate `HOME` too | user, relayed by the lead | seq 3882 |
| F2 key | drop each leading `cd <word> && ` in `run_fingerprint`, string methods | user, relayed by the lead | seq 3883 |
| settled | cause 3 documentation only; stored rows not rewritten; no gate | user, relayed by the lead | seq 3884 |
| F3 notice | one line per command, the reason names the cause | the lead, executive | seq 3885 |
| F4 doctor | no new check; its runs line names `HOME` | the lead, executive | seq 3886 |

## Files

- `shipgate/hooks/_common.py`: `runs_root()` reads `HOME` only; `run_fingerprint()`
  removes the leading `cd` steps.
- `shipgate/scripts/_journal/runs.py`: `Observation` carries why nothing matched and the
  root; `not_observed_lines` prints the cause.
- `shipgate/scripts/_journal/doctor.py`: the runs line for no root, and the root's label.
- Tests: `test_hooks.py`, `test_journal.py` (helpers), `test_journal_runs.py`,
  `test_journal_doctor.py`, `test_journal_gates.py`, and each other site the suite shows.
- Docs: `README.md`, `skills/verify/SKILL.md`, root `CLAUDE.md`, `CHANGELOG.md`, the plugin
  version in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.

## Measurement

`bench2.py` in the scratchpad: each hook 25 times per case, the base tree (`git archive
HEAD shipgate`) and the changed tree in turn per round, with a temporary `HOME` and
`CLAUDE_CONFIG_DIR`. The Bash command is `cd /some/dir && python3 -m unittest discover -s
shipgate/tests`, so the changed tree pays the prefix removal. Median ms.

Baseline (T001, 2026-11-26, the two trees still the same): base → worktree.

| Hook | No settings file | Journaled |
| --- | --- | --- |
| `pre_tool_use.py` | 42.3 → 42.8 | 45.7 → 45.3 |
| `post_tool_use.py`, PostToolUse | 28.1 → 28.3 | 38.7 → 39.4 |
| `post_tool_use.py`, PostToolUseFailure | 28.2 → 27.9 | 36.6 → 37.3 |

A bare Python start was 23.8 ms. Limit (SC-002 of #27): at most +1 ms with no settings
file, at most +3 ms journaled, per hook.

After the change (T030, 2026-11-26): two runs of `bench2.py`, base tree → changed tree,
median ms. The changed journaled hook removes the `cd` step and writes under the temporary
`HOME`.

| Hook | No settings file | Journaled |
| --- | --- | --- |
| `pre_tool_use.py` | 44.1 → 43.9 (−0.2); 43.0 → 43.4 (+0.4) | 45.3 → 45.8 (+0.5); 44.9 → 44.6 (−0.3) |
| `post_tool_use.py`, PostToolUse | 29.5 → 29.4 (−0.1); 28.7 → 28.9 (+0.2) | 39.9 → 39.6 (−0.3); 38.5 → 38.2 (−0.3) |
| `post_tool_use.py`, PostToolUseFailure | 29.2 → 29.5 (+0.3); 28.5 → 28.0 (−0.5) | 37.7 → 37.5 (−0.2); 36.7 → 37.4 (+0.7) |

A bare Python start was 25.0 / 25.2 ms. The limit holds: every delta is within ±0.7 ms,
which is the noise between two runs. The no-op path is unchanged in code: `runs_root()`
and `run_fingerprint()` run only in a journaled project. The prefix removal is linear: a
command of 20,000 `cd a && ` steps (160 KB) hashes in 4.7 ms.

## Test counts (T031)

Three foreground runs on the final tree, then `test_hooks.py` again after its guard:

| Run | Tests | Result |
| --- | --- | --- |
| `-p 'test_[a-i]*.py'` | 803 | OK, 1 skipped |
| `-p 'test_j*.py'` | 1190 | OK (one `ResourceWarning: unclosed database` printed) |
| `-p 'test_[k-z]*.py'` | 640 | OK, 1 skipped |
| `-p 'test_hooks.py'` (after the guard) | 314 | OK |
| After review round 1's fixes: `test_[a-i]*` / `test_j*` / `test_[k-z]*` | 803 / 1190 / 640 | OK, 1 skipped / OK / OK, 1 skipped |

---

# Build Plan

- [x] T001 — Baseline: run `bench2.py` on the unchanged tree and record the medians here — file(s): `shipgate/docs/prd/observed-run-match.worklog.md` — done when: the table above holds the numbers.
- [x] T002 — Test isolation by `HOME`: every helper that gives a temporary `CLAUDE_CONFIG_DIR` to a hook or a `journal.py` subprocess also gives a temporary `HOME` (`hook_env`, `journal_env` in `test_hooks.py`; `isolated_env`, `journal_env`, `run_journal` in `test_journal.py`; the hand-built envs the suite shows); the root `CLAUDE.md` rule says so — file(s): `shipgate/tests/test_hooks.py`, `shipgate/tests/test_journal.py`, `CLAUDE.md` — done when: the three suite runs leave no file in the real `~/.claude/shipgate/runs` (it does not exist before the runs).
- [x] T010 — The base: `runs_root()` reads `HOME` only (None when unset, empty or not absolute); the pin test becomes "runs_root ignores CLAUDE_CONFIG_DIR"; the runs tests write and read under a temporary `HOME`; a hook with no `HOME` writes nothing — file(s): `shipgate/hooks/_common.py`, `shipgate/tests/test_hooks.py`, `shipgate/tests/test_journal_runs.py`, `shipgate/tests/test_journal_doctor.py`, `shipgate/tests/test_journal_gates.py` — done when: the new tests fail on the old rule and pass on the new one.
- [x] T011 — The key: `run_fingerprint()` removes each leading `cd <word> && ` after the strip, with string methods; unit tests for the removal and for what it keeps; an end-to-end test drives the hooks with the text Claude Code hands them for each probe form (typed `cd <cwd> && x` arrives as `x`; the kept forms arrive as typed; the chain arrives with one step removed) and cites the typed form, and each row is stored `observed: true`; `re` stays unloaded — file(s): `shipgate/hooks/_common.py`, `shipgate/tests/test_hooks.py`, `shipgate/tests/test_journal_runs.py` — done when: the tests fail before the change and pass after.
- [x] T012 — The notice: `observe` records the cause (no session id, no log, or a log), and the root; `not_observed_lines` prints the four lines of ADR 0033's amendment of #81; `doctor`'s runs line names `HOME` — file(s): `shipgate/scripts/_journal/runs.py`, `shipgate/scripts/_journal/doctor.py`, `shipgate/tests/test_journal_runs.py`, `shipgate/tests/test_journal_doctor.py` — done when: a test pins each line and the doctor lines.
- [x] T020 — Docs and version: README's run-log paragraph (the base, the key), the verify skill's citing bullets and its notice bullet, the CHANGELOG entry (with the old logs that can be deleted by hand), the plugin version bumped to the next free version in both manifests — file(s): `shipgate/README.md`, `shipgate/skills/verify/SKILL.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: the prose tests pass and no doc names the old base as current.
- [x] T030 — Measure after: rerun `bench2.py` base tree against changed tree; record the table here — file(s): `shipgate/docs/prd/observed-run-match.worklog.md` — done when: the numbers are here and the limit holds, or a deviation names why not.
- [x] T031 — Full suite: the three foreground runs (`-p 'test_[a-i]*.py'`, `-p 'test_j*.py'`, `-p 'test_[k-z]*.py'`) pass, and the real `~/.claude/shipgate/runs` is still absent — file(s): none — done when: the counts are recorded here.
- [x] T040 — Review: the review skill, full fan and the security pass on the working tree; at most two rounds — file(s): this worklog — done when: a verdict is recorded.

## Traceability

| Cause / decision | Tasks |
| --- | --- |
| Cause 1, F1 | T002, T010, T020 |
| Cause 2, F2 | T011, T020 |
| Cause 3, F3 | T012, T020 |
| F4 | T012 (label only) |
| Hook cost | T001, T030 |

## Deviations & notes (filled during implementation)

- Executive (scale): the build runs inline, with no worker subagents. The change is small,
  and a worker would be on the same tier as this session.
- T010: a test pinned the old key (`cd x && …` unmatched in `test_journal_runs.py`). F2
  reverses it by decision, so the test now pins the new key and its kept forms.
- T010: an intermediate red run (after the root change, before `RunLogCase` moved to
  `HOME`) wrote 9 test logs into the developer's real `~/.claude/shipgate/runs`. They were
  removed, with the directories the run made. A `tearDownModule` guard in `test_hooks.py`
  now fails when a run adds a log whose session part is no UUID to the real root.
- T012: `doctor` changes two labels only (F4 holds): the runs line says `under this HOME`,
  and with no root it says `HOME is unset or not an absolute path`.
- T020: the glossary's **run log** entry named the old base; it now names `$HOME/.claude`.
  The version is 0.38.1, as the lead assigned: PR 2 of #28 takes 0.38.0 and merges first.
- T030/T031: the bench and the suites ran in this session. Each `verify-run` cites the
  suite commands; the bench call holds machine paths, so its row has an empty `commands`
  list with the bench in `scope`.
- The lead's question on subagent runs (2026-11-26): see **Subagent runs** below.

## What changed

- An honest `verify-run` is now stored as observed when a shell profile sets `CLAUDE_CONFIG_DIR` to another directory than the session's: the run log lives under `~/.claude/shipgate/runs`.
- A command cited with a leading `cd <dir> && ` now matches the run the hooks saw, because the hash leaves that step out on both sides.
- Each `not observed:` line now names its cause: no session id, no log for this session under the runs root, no foreground run of the command, or another exit code.
- Logs that 0.37.0 wrote under another config directory are no longer read; the changelog says they can be deleted by hand.

## Subagent runs (the lead's question, 2026-11-26)

A probe (nested `claude -p` on Haiku, one general-purpose subagent, 0.011 USD) showed: a
subagent's hooks carry the parent `session_id` and an `agent_id`; its hooks and its Bash
shell both have the parent's `CLAUDE_CODE_SESSION_ID`; its hooks get the session's config
directory; Claude Code removes its `cd <cwd> && ` as in the main session; and a `cd` out of
the project is reset, so its later payloads keep the project as `cwd`. A worktree-isolated
subagent was not probed: the scratch repository needed a commit, which the commit gate
held.

The four unobserved rows of one stream of 2026-11-26 (counts only), read against that
session's own log:

- 1 row: every command is in the log with exit 0. The append read another config
  directory (cause 1). This fix covers it.
- 2 rows: cited with a leading `cd <worktree> && `; the runs are in the log under the
  key without it (cause 2). This fix covers it.
- 1 row (the worker runs): the worker's runs are in the log under the parent session, but
  the worker ran compound commands (a loop over four test files with redirected output,
  `| tail`, `; echo "exit=$?"`). The orchestrator cited one bare command per file, and no
  run had that text. This fix does not cover it, and must not: `observed` says that the
  exact command ran.

Follow-ups, proposed to the lead and outside the scope of #81:

- The worker brief in `model-tiers` and the citing paragraph in `implement` say that a
  worker runs each proving command alone, with no pipe, loop or `; echo`, in the
  foreground, and reports it as typed. No skill says this today.
- A worktree-isolated subagent is not probed. By the code, its hooks walk up from the
  worktree's `cwd` and find that worktree's committed `.claude/shipgate.json`, so its runs
  are logged when its hooks carry the parent session id, as a plain subagent's do. A probe
  in a scratch repository with one commit would confirm it.
- A working directory whose path holds a space is not probed. If Claude Code removes an
  unquoted `cd <cwd> && ` for such a path, the hook hashes the rest, but the journal keeps
  the step (its word holds a space), so the two keys differ. This is no regression: 0.37.0
  removed no step at all.

## Review round 1

Three lens finders through the review workflow (run `wf_789f0f1f-8a5`): 23 found, 19 after
dedupe, 7 above the confidence floor, 0 refuters (no BLOCKER or HIGH), 12 below the floor.
The briefed security pass read all 19 changed files and reported no finding.

- F1 MEDIUM `tests/test_journal_screens.py:126` — several test helpers ran `journal.py` with the real HOME, so a `flow-started` or terminal append pruned the real `~/.claude/shipgate/runs`; fixed: those helpers in seven modules now go through `isolated_env`.
- F2 MEDIUM `prd/observed-run-match.worklog.md:?` — the worklog named a prose remedy for the worker-run case that the change does not add; fixed: it is now a follow-up proposed to the lead, beside the unprobed worktree case.
- F3 LOW `hooks/_common.py:121` — a `cd` word with a shell operator (`cd x;make && pytest`) dropped a non-`cd` command from the key; fixed: such a word keeps its step, and the key tests pin six forms.
- F4 LOW `_journal/runs.py:223` — the no-session line said "no CLAUDE_CODE_SESSION_ID" for a set id that is no plain token too; fixed: it says "no valid".
- F5 LOW `prd/observed-run-match.worklog.md:184` — the same as F2; fixed with it.
- F6 LOW `_journal/doctor.py:234` — "HOME is not an absolute path" also stood for an unset HOME; fixed in doctor and in the notice: "HOME is unset or not an absolute path".
- F7 LOW `shipgate/README.md:550` — new prose lines broke the wrap width in the README and both ADRs; fixed.
- F8 LOW `_journal/runs.py:168` — the field `Observation.log` held a cause code; fixed: renamed `cause` (below the floor, taken as cheap).
- F9 LOW `verify/SKILL.md:131` — the skill said Claude Code removes any leading `cd <dir> && `; fixed: it removes `cd <cwd> && ` (below the floor).
- F10 LOW `docs/adr/0032-the-bash-hooks-log-each-observed-run-by-session.md:86` — the Decision still said PreToolUse receives the text the model typed; fixed: the note names Claude Code's removal (below the floor).
- F11 LOW `tests/test_hooks.py:102` — three blank lines before `home_env`; fixed (below the floor).

### Rejected findings

- `_journal/runs.py:192` (LOW 55): a log that exists but cannot be read gets the no-log line. The journal refuses a link or an unreadable file in that place, so "no run log" is what it found.
- `_journal/runs.py:190` (LOW 50): `runs_root()` and the session check run twice per append. The cost is two `os.environ` reads, and `read_session_runs` stays self-contained.
- `tests/test_hooks.py:74` (LOW 45): the guard could fail falsely or miss a deletion. It ignores files present before the module and every UUID name, and `test_journal_runs.py` already checks deletions.
- `tests/test_hooks.py:75` (LOW 45): a second guard built differently from the deletion check. The two guard different things: writes here, deletions there.
- `_journal/runs.py:229` (LOW 40): the notice prints the user's home path into the transcript. The transcript holds that path in every tool call already, and the notice reaches no one else.
- `hooks/_runs.py:131` (LOW 40): a user who runs only under `CLAUDE_CONFIG_DIR` gets `~/.claude/shipgate/runs`. Decided in F1 and named in the ADR's consequences.

## Review round 2

One re-reviewer with all lenses, scoped to the round-1 fixes. It confirmed F1 to F11
fixed on evidence and ran 11 test files (all OK). It found no new MEDIUM or higher; the
two-round cap holds.

- N1 LOW `verify/SKILL.md:130` — the skill, the README and the glossary said every leading `cd <dir> && ` is left out, but since F3 a dir with a space or a shell operator keeps its step; fixed: the three say "whose `<dir>` holds no space and no shell operator".
- N2 LOW `hooks/_common.py:126` — a working directory with a space in its path is unprobed; deferred: recorded among the follow-ups above.
- N3 LOW `tests/test_journal_gates.py:1303` — no end-to-end test prints the no-session line for a set id that is no plain token; deferred: `test_journal_runs.py` pins that case at the `observe` level, and the printed line shares the code path.
