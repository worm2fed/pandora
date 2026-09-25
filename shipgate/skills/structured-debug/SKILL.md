---
name: structured-debug
description: Evidence-first debugging — clarify expected vs actual, reproduce, form and test hypotheses, trace the commit that introduced the defect, then agree a fix before changing code. Use when asked to debug a bug, investigate a regression, triage an incident, diagnose failing behavior or a failing test, analyze a production error spike, or do root-cause analysis. Trigger before reaching for a fix; the discipline is what stops you from "fixing" the wrong thing.
---

# Structured debug

The failure mode of debugging is changing code based on a hunch, seeing the symptom move,
and declaring victory without knowing why. This skill keeps you honest: understand, reproduce,
isolate, then fix with a plan.

**Do not change code until the user approves the fix plan.** Investigation is read-mostly;
the fix is deliberate.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## Workflow

1. **Clarify.** State observed vs expected behavior as one concise diff. Confirm scope and
   what "fixed" means. Recall prior context (`knowledge-base`) — past root causes and gotchas live
   in the repo's `CLAUDE.md` / the configured ADR home, and domain context (what the behavior
   *should* be, business-rule-wise) in the configured knowledge base. This bug may already have a
   known cause.

2. **Reproduce.** Capture the minimal steps that trigger it and the environment fingerprint
   (runtime, versions, config, data sample, platform). A bug you can't reproduce, you can't
   confirm you fixed. If you can't reproduce it, say so and narrow until you can.

   **Observe the real system — don't guess. Match the evidence source to the layer** (use
   whichever are available; a backend null-deref needs no browser, a CSS bug needs no logs):
   - Frontend / browser behavior → the `chrome-devtools-mcp` skill (console, network, DOM,
     perf traces).
   - Service logs, prod/QA error spikes → the log-query skill the config's **Debug evidence
     sources** section names (if any).
   - Local service behavior → the container's logs (`docker logs` / compose logs).
   - CI failures → the configured CI integration (default: the forge CLI, e.g.
     `gh run view --log` / `glab ci trace`).
   - Logic-level → run the failing test in isolation; add targeted logging or a
     `--inspect`/debugger session.
   - Symbol-level (who calls this, what's this type, where is it defined) → the LSP tool
     when the config's **Code tooling** section names one — `findReferences`/
     `goToDefinition`/`hover` beat grep-plus-read in typed code.
   - A dependency's actual behavior/API → the library-docs integration the config's
     **Code tooling** section names (if any), before trusting memory of the API.

   **Pull the suspect list** before forming hypotheses, seeded with the files the stack trace
   or the report names:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" suspects <symptom-files> --json
   ```

   Carry the top entries into the hypothesis table as `[signals]` evidence — fix-rate,
   staleness, proximity to the symptom. It ranks where to look first, not what is wrong: a
   suspect is still tested one variable at a time, and it is no more guilty for ranking high.
   Unavailable (`no-git`, `shallow`, `empty-history` — suspects needs the history) → note
   `Risk signals: unavailable (<reason>)` in one line and form hypotheses as before.

3. **Hypothesize and test — one variable at a time.** For each hypothesis, write down: what
   evidence you'd see if it's true, what you'd see if it's false, and the exact command/check
   that distinguishes them. Run it. Let the evidence kill hypotheses; don't pattern-match to
   the first plausible cause. Change one thing per test so you know what moved the result.

   This step *is* the scientific method; a few lenses sharpen it (invoke the lens skills
   the config's **Thinking lenses** section maps to debugging, if any; else apply the idea):
   - **occam's-razor** — test the fewest-assumption hypothesis first; escalate to exotic causes
     only when the simple ones are ruled out.
   - **kepner-tregoe** — when the bug is *selective* (some endpoints/users/regions/times, not
     all), map what IS vs IS-NOT affected; the boundary points at the cause.
   - **five-whys-plus** — once you have the proximate cause, chain "why" (with evidence at each
     step) to reach the systemic root, not just the surface trigger.

4. **Trace the provenance.** Once the root cause is confirmed, find the commit that
   introduced it — this is part of the root cause, not an optional extra:
   - `git log -S'<defect pattern>'` / `-G` on the faulty code, or `git blame` on the exact
     lines, gets you there cheaply when the defect is textual.
   - When it isn't (emergent behavior, interaction bugs), `git bisect run` with the repro
     from step 2 as the test.
   - **Prove it counterfactually**: the repro fails at the suspect commit and passes at its
     parent. A commit that merely *touched* the file is not the introducing commit.

   Then name *why it slipped through* — no test covered the path, the review missed it, the
   spec was ambiguous, a cross-repo contract drifted, a migration went unrefreshed. That one
   line is what turns a fixed bug into a pattern the team can act on.

5. **Plan the fix.** Present the candidate fix(es) with their risk and the verification steps.
   Recommend one. Get approval.

## Validate the fix

- Confirm a **failing signal existed before** the fix (you reproduced it).
- Apply the fix; confirm success via `verify`, including the regression pattern for bugs:
  the test fails on the unfixed code and passes on the fixed code.
- Summarize residual risk and any follow-ups.

**Report the provenance on the tracker issue.** When the bug has a tracker issue and the
config declares a forge, post a root-cause comment (on the user's go-ahead, like any
outward-facing post): the root cause in a sentence, the introducing commit (hash + one line
on what it changed), and why it slipped through. This is how the team maps *where and why*
bugs enter the development cycle — a fix without the provenance comment loses that signal.

When you land the root cause, capture it via `knowledge-base`: a root cause + fix is **technical**
knowledge, so it routes to the store configured for engineering knowledge (default: an ADR if it
changed a decision, otherwise a repo docs note), not a product/domain store. Capture the diagnosis
and the fix so the next person — or the next you — doesn't re-derive it from scratch. Smaller
learnings surfaced along the way (a misleading log line, a tool quirk, a debugging trick) go to
the project **ledger** as one-liners the moment you hit them (see `knowledge-base`).

## Record the diagnosis (journaled projects)

On a project whose config declares a **Journal**, a bug flow records the same way a feature
does — the stream is this work's branch (`fix/1290-date-off-by-one`), one stream per issue like
any other flow:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type debug-root-cause \
  --data '{"cause":"<one sentence>","introduced_by":"<commit>","refs":["docs/prd/<slug>.worklog.md#root-cause"]}'
```

Four events carry a debug flow, each appended when it happens: `bug-reproduced` once expected
vs actual is pinned down, `debug-root-cause` when the cause is established, `gate-decision`
for every fork you settle on the way to the fix — *that is the event for a decision*, whatever
you would naturally call it, and it carries `raised_by` (`user` when the user raised or
corrected the point, `orchestrator` when you asked or decided it, plus `--actor user` for the
user's own calls) — and `verify-run` for the evidence the fix holds, which is exactly what the
failing-test-first run produces.

**`bug-reproduced` and `debug-root-cause` are the two that bloat — pointer, not prose.** The
repro steps, the environment fingerprint, the hypothesis table and the evidence trail live in
the worklog or on the tracker issue; the event carries one sentence plus `refs` naming the
section that holds them. A payload over 1 KB is refused for exactly that reason: a diagnosis
pasted into the journal is a diagnosis nobody can search, review or reuse.

**Use the canonical names and shapes.** `journal.py vocab` lists the types and
`vocab --shape <type>` prints the payload each one takes; `append` refuses anything else —
an event named something plausible-but-unlisted is inert: it records, and no gate or report
ever reads it, which looks like success. If a debug flow genuinely needs a concept the
vocabulary lacks, mint it deliberately with `--new-type` rather than inventing a near-miss of a
name that already exists. A missing or unreadable database is an infrastructure failure, not a
reason to skip the append: surface it loudly and continue in legacy mode only with the user's
acknowledgement.
