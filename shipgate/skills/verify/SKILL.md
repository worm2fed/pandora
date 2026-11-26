---
name: verify
description: Load this at the start of any task that ends in a status the user will act on — "fix whatever fails and confirm we're good to go", "rename X and tell me when it's done", "add validation with a test and confirm the tests pass", "get lint and tests green, then tell me", "add a docstring and confirm the suite still passes" — and at the start of any ask that pastes a test run or CI result, because that output describes the code before the edit and the question is about the code after it. The size of the change does not matter: a one-line edit plus "confirm the tests still pass" is the canonical case, not an exception, since a trivial edit is exactly when the unverified claim slips through. What it adds is the checklist of ways a green report lies — the proving run predates the last edit, the runner discovered 0 tests, the pasted or remembered result is stale, one report bundles several claims (lint *and* tests are two commands), the wording hedges ("should pass") — and the gate itself: run the one command that proves each exact claim in the current session, read the whole output (exit code, counted passes and failures), state the result with the evidence. Not for explaining how code behaves, for a one-shot "run X and tell me the result" where that run is itself the evidence, or for re-running a command whose fresh output already settled the claim in the same state.
---

# Verify

A claim of success without fresh evidence is a guess wearing a confident voice. This skill
exists because the most expensive bugs are the ones reported as "done." Before you tell the
user something works, prove it. Prove it in this session, with output you just saw.

## The rule

**Do not claim completion without fresh terminal evidence from the current session.**

Cached output, output from earlier in the conversation, "I ran this before," and "CI will
catch it" are all disqualified. State changes. The only evidence that counts is the command
you just ran.

**This gate is about evidence, not repetition.** Run the proving command once and read it. A
claim you just evidenced this way is settled. Don't re-verify it again later in the same
state. Don't follow a green proving run with ad-hoc spot checks of the same behaviour; the
next action after the proving output is the report. Don't spawn subagents to double-check
your own fresh output. Current models self-verify while working. The failure mode this skill
exists for is the *unevidenced* claim, not the under-repeated one. Independent fresh-context
review (the `review` phase) is a different thing and stays. A reviewer without your
accumulated context catches what you are blind to.

These words in a completion claim are a red flag that you're asserting, not verifying. If
you're about to write one, stop and run the command instead:

> "should", "should be", "probably", "seems to", "looks like it", "I believe", "I think it
> works", "this will fix it"

## The gate (run for every claim)

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

1. **Identify** — What exact command proves this specific claim? Multiple claims ("tests
   pass and it builds") = multiple commands = multiple gates.
2. **Run** — Execute the full command now. No partial runs. No "I'll just check the
   relevant test" when the claim is about the suite.
3. **Read** — Read the complete output. Check the exit code. Count passes and failures.
   Don't infer them from the absence of red text.
4. **Confirm** — Does the output prove the *exact* claim? "It compiled" does not prove "the
   feature works." "0 failures" with "0 tests run" proves nothing. Neither does "no
   finding" from a review or a scan whose input was empty.
5. **Report** — State the result. Cite the command, the exit code, and the key line of
   output. Let the user see the evidence, not just your conclusion.

## Claim → evidence

| Claim | What proves it |
|-------|----------------|
| Tests pass | Test command run, exit 0, explicit pass count, 0 failures |
| Build succeeds | Build command run, exit 0 |
| Lint clean | Linter run, 0 errors |
| Review or scan found nothing | Files read > 0, and every changed file read; a review of an empty diff proves nothing |
| Bug is fixed | Reproduce first (must fail), apply fix, reproduce again (now passes) |
| Phase complete | Each acceptance criterion verified individually, not as a bundle |
| Feature works | An end-to-end run or a concrete manual walkthrough, not "the code looks right" |
| UI task done (the project sets `ui.globs`) | A registered screenshot for every width in `ui.widths` (`journal.py screens --list`), read by the one who took it, or a `screens-waived` deviation with the reason |
| No regressions in shared code | The affected suite run **before** the change (baseline) and after — zero *new* failures; "pre-existing" is a claim to check, not to assume (it may be your own branch's earlier debt) |

## Bug fixes: prove the test catches the bug

A test that has never failed proves nothing. For a fix:

1. Write/identify the test for the bug.
2. Run it against the **un**fixed code. It must **fail**; this proves the test detects the
   bug.
3. Apply the fix.
4. Run it again. It must **pass**.

If you can't make it fail before the fix, you don't yet know the test is testing the bug.

## Rationalizations to reject

- "It's a trivial change." Trivial changes break builds constantly.
- "I ran something like it earlier." Earlier ≠ now. Re-run.
- "The failing test is flaky." Maybe, but prove it's flaky. Don't assume it.
- "It compiles, so it works." Compilation is not behavior.
- "The subagent said it was done." Require the *evidence* in its report: real command
  output, not "tests pass". Accept a report with evidence. For a report without it, run the
  command; don't trust the claim. Don't re-derive work the evidence already proves.

## Record the evidence (journaled projects)

Fresh evidence is worth nothing tomorrow if only your conclusion survives. On a journaled
project (the status brief is present, or `.claude/shipgate.json` exists and
`journal.py config db` prints a `db` that is not null), append a passing gate as a
`verify-run` event against its stream. The event carries the command, its exit code, and a
trimmed head/tail of the output:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type verify-run \
  --data '{"outcome":"pass","task_ids":["T010"],"commands":[{"cmd":"yarn test","exit":0,"tail":"42 passed"}]}'
```

This record is not three things. First, it is not a substitute for *running* the command;
the gate above is unchanged. Second, it is not a place to paste whole logs. Trim to the
lines that prove the claim, because the journal refuses a payload over 1 KB. Third, it is
not optional bookkeeping. `task-done` will not append without a passing `verify-run` that
names that task. So an unrecorded verify blocks the very completion it was meant to prove.
The two land together, so send them as one `append --batch` (JSONL on stdin) rather than
two calls:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream <branch> --batch <<'EOF'
{"type":"verify-run","data":{"outcome":"pass","task_ids":["T010"],"commands":[{"cmd":"yarn test","exit":0,"tail":"42 passed"}]}}
{"type":"task-done","data":{"task_id":"T010"}}
EOF
```

`journal.py vocab --shape verify-run` prints the payload if you need it.

**Cite each command exactly as you ran it.** The Bash hooks log every foreground run in this
session, a subagent's and a Workflow agent's included: a hash of the command and its exit
code, no text and no output. At append, the journal looks up each `cmd` in that log. It
stores `observed: true` when every command ran here with the `exit` the row names, and
`observed: false` when one did not. So:

- Copy `cmd` character for character from the command you ran: the same flags, pipes and
  redirects. A shortened or retyped command does not match. A leading `cd <dir> && ` does
  not count when `<dir>` holds no space and no shell operator: the journal leaves it out,
  because Claude Code removes `cd <cwd> && ` before the hooks see the command.
- A pipe ends with the exit code of its last command: `pytest | tail -5` exits 0 when the
  tests fail. Run the command that proves the claim without such a pipe, or start it with
  `set -o pipefail;`, so its exit code is the result.
- Run it in this session and in the foreground. A background run is never observed, because
  no hook sees its exit code. A run that must count runs in the foreground. A foreground run
  that passes the Bash tool's time limit moves to the background, so it is not observed
  either: give it a longer timeout, or run a narrower command in the foreground.
- You may leave out `outcome`. The journal derives it from the exit codes: `pass` when every
  one is 0, else `fail`. It refuses an `outcome` that disagrees with them.
- A check that is no Bash command (a manual UI check, an MCP tool, a read of a file) sends an
  empty list, `"commands":[]`, with `outcome` and the check in `scope`. The row is stored
  `observed: false`, because there was nothing to observe.
- The journal owns `observed` and `contradicted`. It replaces any value you send.
- A `not observed:` line after `appended` names a command the log does not show ending with
  that exit code, and the cause: no session id in the shell, no log for this session under
  the runs root, no foreground run of the command in the log, or another exit code. Run the
  command again in the foreground and cite it as you typed it, or fix the citation. The row
  is stored all the same, and it still counts for `task-done`.

Record failures too, with `"outcome":"fail"`. A gate that caught something is the most
useful entry in the log. It is what lets a later session see that the fix was proven rather
than assumed.

**A UI task also needs its screenshots.** When the project sets `ui.globs`, the journal
computes which tasks are UI tasks from the paths on their Build Plan lines. The handoff marks
the next one `[UI]`, and `journal.py screens --stream <branch> --list` lists them all. A UI
task's command can pass while its screen is wrong. So its `task-done` also needs a
screenshot for each width of `ui.widths`. Take one per width with the browser tool you have:
set the viewport to that width in CSS pixels, and save a PNG file. Then register the files:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" screens \
  --stream <branch> --task T010 --file <png> [--file <png> ...]
```

The command stores them in the evidence root, outside every repository, and prints the
widths still missing. With `ui.capture` set,
`screens --stream <branch> --task T010 --url <url>` prints one capture command per width
instead. Each one writes its screenshot straight into the evidence root, so run them and skip
the register step. Read each screenshot and compare it with the reference that the PRD
names. You took it, so you can see a wrong screen before the user does. Then send the
`verify-run` and `task-done` batch above. When you cannot take the screenshots, for example
with no browser tool, the `task-done` refusal prints the waiver command. Write the real reason
in its `note`, because the user reads it at the publish gate.

## When verification fails

Report the failure honestly with the output. A failed check caught now is the skill
working, not a setback. The failure may reveal a reusable trap (a command that lies, a test
that needs a flag). If so, and the `knowledge-base` skill is available, note the trap so the
pattern is captured. Then fix and re-run the gate.
