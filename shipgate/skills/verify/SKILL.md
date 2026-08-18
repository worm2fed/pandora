---
name: verify
description: Enforce evidence-based completion claims — require fresh command output from the current session before reporting that anything works, is done, fixed, passes, builds, or is complete. Use whenever about to claim success on a task, bug fix, phase, test run, build, or deploy — even when the change "obviously" works, since that's exactly when unverified claims slip through.
---

# Verify

A claim of success without fresh evidence is a guess wearing a confident voice. This skill
exists because the most expensive bugs are the ones reported as "done." Before you tell the
user something works, prove it — in this session, with output you just saw.

## The rule

**Do not claim completion without fresh terminal evidence from the current session.**

Cached output, output from earlier in the conversation, "I ran this before," and "CI will
catch it" are all disqualified. State changes; the only evidence that counts is the command
you just ran.

**This gate is about evidence, not repetition.** Run the proving command once and read it —
a claim you just evidenced this way is settled; don't re-verify it again later in the same
state, and don't spawn subagents to double-check your own fresh output. Current models
self-verify while working; the failure mode this skill exists for is the *unevidenced*
claim, not the under-repeated one. Independent fresh-context review (the `review` phase) is
a different thing and stays — a reviewer without your accumulated context catches what you
are blind to.

These words in a completion claim are a red flag that you're asserting, not verifying —
if you're about to write one, stop and run the command instead:

> "should", "should be", "probably", "seems to", "looks like it", "I believe", "I think it
> works", "this will fix it"

## The gate (run for every claim)

1. **Identify** — What exact command proves this specific claim? Multiple claims ("tests
   pass and it builds") = multiple commands = multiple gates.
2. **Run** — Execute the full command now. No partial runs, no "I'll just check the
   relevant test" when the claim is about the suite.
3. **Read** — Read the complete output. Check the exit code. Count passes and failures —
   don't infer them from the absence of red text.
4. **Confirm** — Does the output prove the *exact* claim? "It compiled" does not prove "the
   feature works." "0 failures" with "0 tests run" proves nothing.
5. **Report** — State the result, cite the command, the exit code, and the key line of
   output. Let the user see the evidence, not just your conclusion.

## Claim → evidence

| Claim | What proves it |
|-------|----------------|
| Tests pass | Test command run, exit 0, explicit pass count, 0 failures |
| Build succeeds | Build command run, exit 0 |
| Lint clean | Linter run, 0 errors |
| Bug is fixed | Reproduce first (must fail), apply fix, reproduce again (now passes) |
| Phase complete | Each acceptance criterion verified individually, not as a bundle |
| Feature works | An end-to-end run or a concrete manual walkthrough, not "the code looks right" |

## Bug fixes: prove the test catches the bug

A test that has never failed proves nothing. For a fix:

1. Write/identify the test for the bug.
2. Run it against the **un**fixed code — it must **fail** (this proves the test detects the bug).
3. Apply the fix.
4. Run it again — it must **pass**.

If you can't make it fail before the fix, you don't yet know the test is testing the bug.

## Rationalizations to reject

- "It's a trivial change." Trivial changes break builds constantly.
- "I ran something like it earlier." Earlier ≠ now. Re-run.
- "The failing test is flaky." Maybe — but prove it's flaky, don't assume it.
- "It compiles, so it works." Compilation is not behavior.
- "The subagent said it was done." Require the *evidence* in its report — real command
  output, not "tests pass". A report with evidence is accepted; a report without it gets the
  command run, not the claim trusted. Don't re-derive work the evidence already proves.

## When verification fails

Report the failure honestly with the output — a failed check caught now is the skill
working, not a setback. If the `knowledge-base` skill is available and the failure reveals a
reusable trap (a command that lies, a test that needs a flag), note it so the pattern is
captured. Then fix and re-run the gate.
