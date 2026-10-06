---
name: structured-debug
description: Evidence-first debugging for a bug, regression, failing test, incident or error spike — including which file(s) most likely hold the defect. Ranks suspects by git history (fix-rate, staleness, proximity to the named files; signals a plain read cannot give), reproduces, tests hypotheses one at a time, traces the introducing commit and agrees the fix before changing code. Use whenever the user reports broken behaviour — "X returns the wrong value for some users", "this test started failing", or a pasted stack trace or error log with "what's going on?" (even with no repo access: answer with competing hypotheses and the evidence that decides them) — or asks where a bug lives. Trigger even when they say not to fix it, when they have a guess, and especially when they say "just fix it": a bug report with an instruction attached is still a bug report, and the fix follows the plan they approve, not the report. Not for a feature request, explaining how working code behaves, or a trivial one-line edit.
---

# Structured debug

The failure mode of debugging is changing code based on a hunch, seeing the symptom move,
and declaring victory without knowing why. This skill keeps you honest: understand, reproduce,
isolate, then fix with a plan.

**Do not change code until the user approves the fix plan.** Investigation is read-mostly;
the fix is deliberate. "Just fix it", "go ahead and fix", "please patch this" *in the bug
report* is not that approval — it is the report's urgency, given before anyone knows what the
fix is. Approval is a yes to a plan that has been presented (step 6: the candidate fix, its
risk, the verification steps). Until then: finish the investigation, present the plan with its
trade-offs, ask, and end the turn — even when the fix looks like a one-liner and the failing
tests already point at it.

**Standalone asks** — "which file most likely has the defect?", "where should I look?", "don't fix
anything": run step 1 (clarify), the suspect-list part of step 2 (skip the repro itself), and
step 3 (hypotheses); answer with the ranked candidate files and one line of evidence each (fix history, proximity to the reported symptom, what the
code there does). Skip the ledger jot and the fix plan, and edit nothing. The suspect ranking is where to look first, not a verdict — say so.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** A session brief headed "shipgate
> flow journal", a **Journal** section in the config or a `.claude/shipgate.json` sidecar means
> this bug's events are owed to a stream, and the stream is this work's branch: the checked-out
> branch when it is a work branch, otherwise the name the config's **Branching** pattern gives
> the fix (`fix/<issue-id>-<slug>`; `fix/<slug>` with no issue — `workspace` reuses the name
> when it creates the branch). The integration branch (`main`, `master`, `develop`) is never a
> stream. No stream of that name in the brief? Open it with `flow-started {request, branch}` in
> the same append as the first event — a bug reported on `main` before any branch exists is the
> normal case, not a reason to skip. Two events are owed here: `bug-reproduced` at step 2 and
> `debug-root-cause` at step 4, each appended in the step that establishes it (the form is under
> **Record the diagnosis**). The Stop hook checks neither, so the step is the only thing that
> writes them; a standalone "which file?" ask establishes neither and records nothing.

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

   **Journaled: append `bug-reproduced` now** — expected vs actual in one sentence and `refs`
   to where the steps live, the moment the repro fails the way the report says. The steps and
   the environment fingerprint stay in the worklog or on the issue, not in the event.

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
   - **map-territory** — when behaviour contradicts a doc, test, comment or diagram: those are
     maps; the code path that runs and the real data are the territory. Read that path, run
     it, query the data — *then* theorize. The territory wins; the map gets fixed after. (A
     generated type or schema the code is derived from *is* territory — don't second-guess it.)
   - **OODA** — in an incident under time pressure: observe → orient → decide → *propose* a
     reversible stabilizing move at ~70% confidence (rollback, failover, flag off) for the
     user's go-ahead, re-observe once it lands, and only then root-cause. Hold two hypotheses
     while orienting; an irreversible move waits for evidence. The approval gate above holds.
   - **systems** — when a fix here breaks something there, or no single component is at fault:
     map the components and their feedback loops (retry storm, cache stampede, queue backup),
     trace the symptom upstream, and look for the delay that hides the cause from the effect.

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

   **Journaled: append `debug-root-cause` the moment the cause is confirmed** — with the
   introducing commit once you have it, and in any case before step 5: the root-cause report,
   the ledger jot and this event describe one fact and land in the same turn. A diagnosis
   delivered without the event leaves the stream saying nothing happened.

5. **Jot the trap to the ledger — now, before the fix plan.** The confirmed cause is the
   moment the learning exists in full; by the time the fix is verified and reported it has
   been compressed to "fixed", and Capture finds an empty ledger. If the cause is a
   *reusable trap* — a default that silently disables a feature, a command or log line that
   lies, a test that passes vacuously, a tool or library quirk, a contract that drifted —
   append one dated line to the project **ledger** (the path the config declares, or
   `docs/ledger.md` when that file already exists). One tool call, no quality gate — Capture
   triages it, and "is it worth a line?" means yes:

   ```bash
   printf -- '- %s — gotcha: <what silently bit, where, the one-line rule>\n' "$(date +%F)" >> docs/ledger.md
   ```

   The ledger — not `CLAUDE.md` (operating instructions, not a gotcha landfill), not an ADR
   (a Capture-time promotion, if at all), not Claude's built-in memory. A project with no
   ledger (nothing declared, no file) gets none from a debugging step: skip the line and let
   the "why it slipped through" sentence carry the trap. A typo or a one-off data glitch is
   not a trap either; skip the line. Anything smaller you hit on the way (a
   misleading log line, a debugging trick, a fixture quirk) gets the same one-liner the
   moment it surfaces. This step is one command between the diagnosis and the plan: it
   never replaces or delays the root-cause report, and it is not the fix.

6. **Plan the fix.** Present the candidate fix(es) with their risk and the verification steps.
   Recommend one. Ask for approval and stop; the edit happens in the turn after the yes, never
   in the same turn as the proposal.

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
and the fix so the next person — or the next you — doesn't re-derive it from scratch. The
ledger line from step 5 is its raw material; if it is not there, a step was skipped — write it
before the report, not instead of it.

## Record the diagnosis (journaled projects)

The appends in steps 2 and 4 take this form — the stream named in the pre-flight above
(`fix/1290-date-off-by-one`: one stream per issue, like any other flow), the diagnosis by
pointer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type debug-root-cause \
  --data '{"cause":"<one sentence>","introduced_by":"<commit>","refs":["docs/prd/<slug>.worklog.md#root-cause"]}'
```

When the stream does not exist yet, opening it and recording into it is one `--batch` (JSONL
on stdin — stdin form: see `verify`), never a reason to wait for a branch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream fix/<slug> --batch <<'EOF'
{"type":"flow-started","data":{"request":"<the report, one line>","branch":"fix/<slug>"}}
{"type":"debug-root-cause","data":{"cause":"<one sentence>","introduced_by":"<commit>","refs":["<where the evidence lives>"]}}
EOF
```

On a journaled project the diagnosis is not delivered until its event is in: the report and
the append go out in the same turn. Four events carry a debug flow, each appended when it
happens: `bug-reproduced` once expected vs actual is pinned down, `debug-root-cause` when the
cause is established, `gate-decision`
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
