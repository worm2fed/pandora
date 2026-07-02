---
name: structured-debug
description: Evidence-first debugging — clarify expected vs actual, reproduce, form and test hypotheses, then agree a fix before changing code. Use when asked to debug a bug, investigate a regression, triage an incident, diagnose failing behavior or a failing test, analyze a production error spike, or do root-cause analysis. Trigger before reaching for a fix; the discipline is what stops you from "fixing" the wrong thing.
---

# Structured debug

The failure mode of debugging is changing code based on a hunch, seeing the symptom move,
and declaring victory without knowing why. This skill keeps you honest: understand, reproduce,
isolate, then fix with a plan.

**Do not change code until the user approves the fix plan.** Investigation is read-mostly;
the fix is deliberate.

## Workflow

1. **Clarify.** State observed vs expected behavior as one concise diff. Confirm scope and
   what "fixed" means. Recall prior context (`knowledge-base`) — past root causes and gotchas live
   in the repo's `CLAUDE.md` / `docs/adr/`, and project/domain context (what the behavior
   *should* be) may be in your vault. This bug may already have a known cause.

2. **Reproduce.** Capture the minimal steps that trigger it and the environment fingerprint
   (runtime, versions, config, data sample, platform). A bug you can't reproduce, you can't
   confirm you fixed. If you can't reproduce it, say so and narrow until you can.

   **Observe the real system — don't guess. Match the evidence source to the layer** (use
   whichever are available; a backend null-deref needs no browser, a CSS bug needs no logs):
   - Frontend / browser behavior → the `chrome-devtools-mcp` skill (console, network, DOM,
     perf traces).
   - Local service behavior → the container's logs (`docker logs` / compose logs) or the
     process's own output.
   - CI failures → the CI provider's job log (`gh run view` on GitHub).
   - Logic-level → run the failing test in isolation; add targeted logging or a
     `--inspect`/debugger session.

3. **Hypothesize and test — one variable at a time.** For each hypothesis, write down: what
   evidence you'd see if it's true, what you'd see if it's false, and the exact command/check
   that distinguishes them. Run it. Let the evidence kill hypotheses; don't pattern-match to
   the first plausible cause. Change one thing per test so you know what moved the result.

   This step *is* the scientific method; a few lenses sharpen it (use the `thinking-skills`
   plugin if available, else apply the idea):
   - **occam's-razor** — test the fewest-assumption hypothesis first; escalate to exotic causes
     only when the simple ones are ruled out.
   - **kepner-tregoe** — when the bug is *selective* (some endpoints/users/regions/times, not
     all), map what IS vs IS-NOT affected; the boundary points at the cause.
   - **five-whys-plus** — once you have the proximate cause, chain "why" (with evidence at each
     step) to reach the systemic root, not just the surface trigger.

4. **Plan the fix.** Present the candidate fix(es) with their risk and the verification steps.
   Recommend one. Get approval.

## Validate the fix

- Confirm a **failing signal existed before** the fix (you reproduced it).
- Apply the fix; confirm success via `verify`, including the regression pattern for bugs:
  the test fails on the unfixed code and passes on the fixed code.
- Summarize residual risk and any follow-ups.

When you land the root cause, capture it via `knowledge-base`: a root cause + fix is **technical**
knowledge, so its home is the repo — the relevant `CLAUDE.md` (or an ADR if it changed a
decision), never the personal vault. Capture the diagnosis and the fix so the next person — or
the next you — doesn't re-derive it from scratch.
