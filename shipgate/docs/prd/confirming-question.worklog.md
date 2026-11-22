---
type: worklog
title: "Worklog: a confirming question replaces the read go"
created: 2026-11-21
updated: 2026-11-21
tags:
  - worklog
  - shipgate
  - hooks
  - journal
status: review
prd: "./approval-path.md"
issue: "#52 (child of #37)"
related:
  - ../adr/0023-the-users-go-is-recorded-where-the-user-answers.md
  - ./approval-path.worklog.md
---

# Worklog: a confirming question replaces the read go

> Design + build plan for #52, a scoped fix of the approval path (`./approval-path.md`,
> ruling 14; ADR 0023, amendment). Target release: shipgate 0.28.1. 0.28.0 gets no tag.

---

# Design

## Approach

A scoped change on the design of #22. The user's ruling fixes the shape: an exact word
stays a go at once, any other reply leads to one confirming question, and the hook records
the click. No architect fan: the ruling leaves no open fork, and every touched function
was read in full before the plan.

## What changes

- **Journal (`scripts/journal.py`).** `DecisionSource` loses `read`. An append of a
  `gate-decision` whose `source` folds to `read` is refused before the payload check, with
  `--force` too, and the refusal names the confirming question. The read-go code goes:
  `_validate_read_go`, `witness_fault`, `_witness_holds`, the read branch of
  `_user_go_events` and of `_validate_own_session`, `_read_go_command`, the `witness` and
  `words` keys of the shape. `NON_BINDING_MARKERS` keeps `read`, so an old read row still
  binds no session.
- **Reply plan.** A witness's context line says: the reply is no exact go; record a new go
  request (the command is in the line) and ask one confirming question with the gate
  header and the gate word first; when it answered a confirming question, the user did not
  confirm. No witness seq, no placeholder.
- **Hold message.** `witness-waits` asks for a new go request and one confirming question.
- **Recorder (`hooks/reply.py`).** The `<seq:N>` replacement goes; the rest is unchanged.
- **PreToolUse (`hooks/pre_tool_use.py`).** `judge_event` refuses every `source`. The
  refusal texts drop the read go, and the recorder refusal names the Write tool. "The line
  names the recorder" stays the raw-text rule of origin/main: a note exemption was built,
  reviewed in four rounds and rejected (ADR 0023, A6). A program-word skip in `wrapped`
  was dropped as well (the fifth recheck forged a go through `env -vS`).
- **Flow text.** `review` ("The user's go", step 4 and the closing paragraph) and
  `feature` (epic stop, recording rules).
- **Two-turn driver.** The pass: go request, the gate question, the reply "it can go", a
  confirming question with the header `Commit`, a click on the go option, a `question` go
  in the journal, and the commit.

## Old rows

A read row that 0.28.0 wrote stays and is inert (ADR 0023, A4). The journal opens, the row
authorizes nothing, `stats` does not count it as a go, and it binds no session. A test
writes such a row and checks all four.

## Reproduction of the false refusal (before the fix)

`inspect()` of the worktree's hook, by a scratch probe:

```
cat > "$SP/note.md" <<'EOF' … shipgate/hooks/<recorder> … EOF; python3 "$SP/other.py"  -> recorder
echo 'see hooks/<recorder>' > n.txt && python3 "$SP/other.py"                        -> recorder
rtk proxy grep -n "a\|<recorder>\|b" file                                            -> recorder
cat > note.md <<'EOF' … EOF; python3 other.py (literal script word)                  -> None
```

The installed 0.28.0 hook refused two of this session's own calls the same way: a journal
batch in a heredoc that named the path, run by `python3 "$SP/…"`, and the `rtk` search.

---

# Build Plan

- [x] T001 — Retire the `read` marker in the journal: refusal with `--force` too, the
  read-go code removed, an old read row inert — file(s): `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py` — done when: the new tests fail first, then pass.
- [x] T002 — The reply plan and the hold ask for one confirming question; the `mr-opened`
  refusal lists four markers — file(s): `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py` — done when: the tests pin the new lines.
- [x] T003 — The recorder drops the placeholder; the context line reaches the model on a
  typed prompt and on a free-text question answer — file(s): `shipgate/hooks/reply.py`,
  `shipgate/tests/test_hooks.py` — done when: both paths are tested.
- [x] T004 — The forgery net refuses every `source` marker; the refusal texts name the
  confirming question — file(s): `shipgate/hooks/pre_tool_use.py`,
  `shipgate/tests/test_hooks.py` — done when: a model's read go is refused.
- [x] T005 — The false refusal: the recorder named in data does not count as a run —
  file(s): `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py` — done when:
  the repro cases pass and every run of the recorder stays refused.
- [x] T006 — Flow text: `review` and `feature` describe the confirming question — file(s):
  `shipgate/skills/review/SKILL.md`, `shipgate/skills/feature/SKILL.md` — done when: no
  skill names the read go.
- [x] T007 — The two-turn driver's new pass — file(s): `shipgate/evals/two-turn/` — done
  when: the driver compiles and its checks name the confirming question and the click.
- [x] T008 — Docs and release: README, glossary, CHANGELOG 0.28.1, both version files —
  file(s): `shipgate/README.md`, `shipgate/docs/glossary.md`, `shipgate/CHANGELOG.md`,
  `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when:
  the prose and contract tests pass.
- [x] T009 — The full suite and the public-repo grep of the diff — done when: the suite
  exits 0 and the grep finds nothing.
- [x] T011 — Reverse the note exemption (the lead's decision after four review rounds):
  the recorder rule of `pre_tool_use.py` returns to origin/main, the refusal names the
  Write tool, the false-refusal test pins the refusal — file(s):
  `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py`, ADR 0023, CHANGELOG,
  README, PRD — done when: the hook diff against origin/main holds only the read-marker
  and refusal-text changes, and the full suite exits 0.
- [x] T010 — Close the three note-exemption gaps the built-in security review of 4d29bb9
  listed: a pipe that ends a line keeps its link to the next command, and `case`,
  `esac`, `foreach` and `end` join the fail-safe checks — file(s):
  `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py` — done when: one test
  per gap fails first, then passes, and the full suite exits 0.

---

# Review

## Review round 1

The review workflow ran three lenses with Opus finders (run `wf_0f3fb39a-470`): 21
found, 20 after dedupe, 7 candidates, 2 refuters, 0 killed. A separate reviewer ran the
built-in security review's criteria on `git diff origin/main`. Both found F1. The security
reviewer reproduced it end to end: the worktree hook passed
`echo "${R:=…/hooks/reply.py}" >/dev/null; python3 "$R" <<'EOF' …`, and the recorder
wrote a `prompt` go as the user's.

- F1 HIGH `shipgate/hooks/pre_tool_use.py:1200` — `names_recorder` read every word and stdin of a text-only command as data, so an assignment in `${R:=…}`, `read R < <(echo …)` or a pipe into `read` filled the unread script word; the rule now subtracts and exempts only a note (fixed).
- F2 MEDIUM `shipgate/hooks/pre_tool_use.py:1211` — a text-only producer piped into `read` counted as data; same fix as F1 (fixed).
- F3 LOW `shipgate/tests/test_hooks.py:2834` — a test docstring still said a read go counts for its session (fixed).
- F4 LOW `shipgate/docs/adr/0023-the-users-go-is-recorded-where-the-user-answers.md:91` — decisions 2, 8 and 18 ran to 128-148 columns (fixed).
- F5 LOW `shipgate/scripts/journal.py:3294` — a docstring line ran to 95 columns (fixed).
- F6 LOW `shipgate/docs/glossary.md:37` — an italic *read go* pointed to a deleted row (fixed).
- F7 LOW `shipgate/docs/prd/approval-path.md:13` — the frontmatter did not name this worklog (fixed).
- F8 LOW `shipgate/tests/test_hooks.py:2791` — the false-refusal test did not cite SC-019 (fixed).
- D1 LOW `shipgate/hooks/pre_tool_use.py:166` — `git` aliases with `!` and `rg --pre` run programs although `TEXT_ONLY` reads them as text; the same on origin/main, listed in the ADR's limits for a follow-up (deferred).
- D2 LOW `shipgate/hooks/pre_tool_use.py:1254` — the recorder as a Python program on stdin, `bash <(…)`, `source <(…)` and a quote-split name pass; the same on origin/main (deferred).

### Rejected findings

- `shipgate/scripts/journal.py:2900` (LOW 55): the hold already says "Unless it refused" and "If the user refused or did not confirm, wait for the user".
- `shipgate/hooks/pre_tool_use.py:1193` (LOW 55): the raw test in `stdin_events` is live, because `REASON_RECORDER` is an event reason, and it reads the stdin of a command that is not text-only, where the raw test is the safe reading.
- `shipgate/scripts/journal.py:2796` (LOW 45): a go request with the placeholder question authorizes nothing, and the click still records the go.
- `shipgate/evals/two-turn/two_turn.py:279` (LOW 45): with no new go request the click records no go in the fixture, so `question_go_after_the_witness` already fails.
- `shipgate/evals/two-turn/two_turn.py:246` (LOW 30): the screen mark is taken before each pump, and the logging hook fires before the dialog renders.
- `shipgate/scripts/journal.py:1837` (LOW 30): `casefold` covers `lower` for this check.
- `shipgate/scripts/journal.py:1826` (LOW 30): the second refusal is deliberate: it names the confirming question and folds case.

## Review round 2

The security reviewer re-checked the round-1 fix. Every row its first probe refused on
origin/main is refused again, and the round-1 tests pass. It found that a note could still
reach a variable, each shape checked in bash or zsh with a dummy script.

- F9 MEDIUM `shipgate/hooks/pre_tool_use.py:1244` — a counted note masked a reachable name: a builtin's unquoted body that expands `${R:=…}`, a note sent to a coprocess or through `exec >&p`, a note captured from a function body, and a `$[1<<2]` that the lexer reads as a heredoc; a note now needs literal words and an as-written body, and a line with a coprocess, `exec`, a function, `$[`, `((`, a process substitution or a dup to a computed fd gets no note (fixed).
- D3 MEDIUM `shipgate/hooks/pre_tool_use.py:615` — the lexer does not read a `$( )` inside an unquoted heredoc body, or a heredoc opened inside `$(` on its operator line, so a run of the recorder there passes; the same on origin/main, in the ADR's limits for a follow-up (deferred).
- D4 LOW `shipgate/hooks/pre_tool_use.py:167` — a text-only command whose output feeds a shell through `>(bash)` or a coprocess passes a run in its heredoc; the same on origin/main (deferred).

## Review round 3

The built-in `/security-review` ran on commit 4d29bb9 and found no finding at or above its
bar. It listed three gaps below the bar that are new on the commit: in each, a note masked
a later run through an unread script path that origin/main refuses. The lead ruled to fix
them on PR #53 before the merge; D3 and D4 went to issue #54.

- F10 LOW `shipgate/hooks/pre_tool_use.py:377` — a `|` at the end of a line lost its link to the next line's command, so the heredoc of `cat <<'EOF' |` counted as a note that feeds no pipe; the lexer now keeps the link across the newline (fixed).
- F11 LOW `shipgate/hooks/pre_tool_use.py:1224` — in `R=$(case x in x) … ;; esac)` the lexer read the pattern's `)` as the end of `$(`, so the `cat` inside counted as not nested; `case` and `esac` now cancel every note on the line (fixed).
- F12 LOW `shipgate/hooks/pre_tool_use.py:1218` — a zsh `foreach … end | read` fed a pipe from a compound end the rule did not know; `end` is a compound end and `foreach` cancels every note (fixed).

The reviewer's recheck of that delta found that the fix for F10 opened a path:

- F13 MEDIUM `shipgate/hooks/pre_tool_use.py:369` — a command after a line-ending `|` that holds only a redirection (`| 2>/dev/null`) also kept the link, so a `--batch` append on the next line was judged on the echo's text while it read a group's heredoc; a forged go landed in a scratch journal. A command now records that it took a redirection, and only a bare one keeps the link (fixed).
- D5 LOW `shipgate/hooks/pre_tool_use.py:552` — `balanced` ignores a `"` inside `${…}`, so after `"${X:-"}"}"` the lexer reads the next line as quoted text; the same on origin/main (deferred, a candidate for #54).

## The note exemption is rejected

The lead ruled to take the exemption out of 0.28.1 (journal deviation, seq 2075). Four
rounds had each found a bypass that origin/main refuses, and the benefit is small: only a
session that writes text naming the recorder script meets the false refusal. The recorder
rule of `pre_tool_use.py` is origin/main's again, with no note exemption and none of the
lexer additions it needed. The recorder refusal adds one sentence: a command that only
writes text naming the script should write the file with the Write tool. The false-refusal
test now pins that refusal and that sentence. The bypass shapes of rounds 1 to 3 stay as
tests that the rule of origin/main refuses (ADR 0023, A6).

## Review round 4

The reviewer rechecked the whole hook diff against origin/main.

- F14 MEDIUM `shipgate/hooks/pre_tool_use.py:1336` — the program-word skip in `wrapped()` trusted `command_name`, which misreads an option cluster such as `env -vS '<line>'`, and `env` runs that value as a command line; a forged go landed in a scratch journal, so the skip is dropped and its false refusal goes to #54 (fixed).

After the drop, the hook equals origin/main on every row of the reviewer's probe table,
except the read go, which is now refused (`marker`).
