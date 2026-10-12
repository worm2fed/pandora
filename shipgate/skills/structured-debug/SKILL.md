---
name: structured-debug
description: Evidence-first debugging for a bug, regression, failing test, incident or error spike — including which file(s) most likely hold the defect. Ranks suspects by git history (fix-rate, staleness, proximity to the named files; signals a plain read cannot give), reproduces, tests hypotheses one at a time, traces the introducing commit and agrees the fix before changing code. Use whenever the user reports broken behaviour — "X returns the wrong value for some users", "this test started failing", or a pasted stack trace or error log with "what's going on?" (even with no repo access: answer with competing hypotheses and the evidence that decides them) — or asks where a bug lives. Trigger even when they say not to fix it, when they have a guess, and especially when they say "just fix it": a bug report with an instruction attached is still a bug report, and the fix follows the plan they approve, not the report. Not for a feature request, explaining how working code behaves, or a trivial one-line edit.
---

# Structured debug

The failure mode of debugging is this: you change code on a hunch, see the symptom move, and
declare victory without knowing why. This skill keeps you honest. Understand, reproduce,
isolate, then fix with a plan.

**Do not change code until the user approves the fix plan.** Investigation is read-mostly.
The fix is deliberate. "Just fix it", "go ahead and fix" or "please patch this" *in the bug
report* is not that approval. It is the report's urgency, given before anyone knows what the
fix is. Approval is a yes to a plan that you have presented (step 6: the candidate fix, its
risk, the verification steps). Until then, finish the investigation. Present the plan with
its trade-offs. Ask, and end the turn. Do this even when the fix looks like a one-liner and
the failing tests already point at it.

**Standalone asks** are questions like "which file most likely has the defect?", "where
should I look?" or "don't fix anything". For these, run step 1 (clarify), the suspect-list
part of step 2 (skip the repro itself), and step 3 (hypotheses). Answer with the ranked
candidate files and one line of evidence each: fix history, proximity to the reported
symptom, what the code there does. Skip the ledger jot and the fix plan, and edit nothing.
The suspect ranking is where to look first, not a verdict. Say so.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** Any one of three signs means this bug's
> events are owed to a stream: a status brief headed "shipgate flow journal", a **Journal**
> section in the config, or a `.claude/shipgate.json` sidecar. The stream is this work's
> branch. That is the checked-out branch when it is a work branch. Otherwise it is the name
> the config's **Branching** pattern gives the fix: `fix/<issue-id>-<slug>`, or `fix/<slug>`
> with no issue. `workspace` reuses the name when it creates the branch. The integration
> branch (`main`, `master`, `develop`) is never a stream. Is there no stream of that name in
> the status brief? Then open it with `flow-started {request, branch}` in the same append as
> the first event. A bug reported on `main` before any branch exists is the normal case, not
> a reason to skip. Two events are owed here: `bug-reproduced` at step 2 and
> `debug-root-cause` at step 4. Append each one in the step that establishes it (the form is
> under **Record the diagnosis**). The Stop hook checks neither, so the step is the only
> thing that writes them. A standalone "which file?" ask establishes neither and records
> nothing.

## Steps

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

1. **Clarify.** State observed vs expected behavior as one concise diff. Confirm scope and
   what "fixed" means. Recall prior context (`knowledge-base`). Past root causes and gotchas
   live in the repo's `CLAUDE.md` / the configured ADR home. Domain context (what the
   behavior *should* be, business-rule-wise) lives in the configured knowledge base. This bug
   may already have a known cause.

2. **Reproduce.** Capture the minimal steps that trigger it. Capture the environment
   fingerprint: runtime, versions, config, data sample, platform. If you can't reproduce a
   bug, you can't confirm you fixed it. If you can't reproduce it, say so and narrow until
   you can.

   **Observe the real system — don't guess. Match the evidence source to the layer.** Use
   whichever sources are available. A backend null-deref needs no browser, and a CSS bug
   needs no logs.
   - Frontend / browser behavior → the `chrome-devtools-mcp` skill (console, network, DOM,
     perf traces).
   - Service logs, prod/QA error spikes → the log-query skill the config's **Debug evidence
     sources** section names (if any).
   - Local service behavior → the container's logs (`docker logs` / compose logs).
   - CI failures → the configured CI integration (default: the forge CLI, e.g.
     `gh run view --log` / `glab ci trace`).
   - Logic-level → run the failing test in isolation. Add targeted logging or a
     `--inspect`/debugger session.
   - Symbol-level (who calls this, what's this type, where is it defined) → the LSP tool
     when the config's **Code tooling** section names one. In typed code,
     `findReferences`/`goToDefinition`/`hover` beat grep-plus-read.
   - A dependency's actual behavior/API → the library-docs integration the config's
     **Code tooling** section names (if any), before you trust memory of the API.

   **Pull the suspect list** before you form hypotheses. Seed it with the files that the
   stack trace or the report names:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" suspects <symptom-files> --json
   ```

   Carry the top entries into the hypothesis table as `[signals]` evidence: fix-rate,
   staleness, proximity to the symptom. The list ranks where to look first, not what is
   wrong. You still test a suspect one variable at a time. A high rank does not make it
   more guilty. If the signals are unavailable (`no-git`, `shallow`, `empty-history`;
   suspects needs the history), note `Risk signals: unavailable (<reason>)` in one line.
   Then form hypotheses as before.

   **Journaled: append `bug-reproduced` now**, the moment the repro fails the way the report
   says. The event carries expected vs actual in one sentence and `refs` to where the steps
   live. The steps and the environment fingerprint stay in the worklog or on the issue, not
   in the event.

3. **Hypothesize and test — one variable at a time.** For each hypothesis, write down three
   things. First, the evidence you'd see if it's true. Second, what you'd see if it's
   false. Third, the exact command/check that distinguishes them. Run it. Let the evidence
   kill hypotheses. Don't pattern-match to the first plausible cause. Change one thing per
   test so you know what moved the result.

   This step *is* the scientific method, and a few lenses sharpen it. Invoke the lens skills
   that the config's **Thinking lenses** section maps to debugging, if any. Otherwise, apply
   the idea:
   - **occam's-razor** — test the fewest-assumption hypothesis first. Escalate to exotic
     causes only when the simple ones are ruled out.
   - **kepner-tregoe** — use it when the bug is *selective*: some endpoints, users, regions
     or times, not all. Map what IS vs IS-NOT affected. The boundary points at the cause.
   - **five-whys-plus** — once you have the proximate cause, chain "why" with evidence at
     each step. This reaches the systemic root, not just the surface trigger.
   - **map-territory** — use it when behaviour contradicts a doc, test, comment or diagram.
     Those are maps. The code path that runs and the real data are the territory. Read that
     path, run it, query the data, and *then* theorize. The territory wins, and the map gets
     fixed after. (A generated type or schema that the code is derived from *is* territory.
     Don't second-guess it.)
   - **OODA** — use it in an incident under time pressure: observe → orient → decide →
     *propose*. Propose a reversible stabilizing move at ~70% confidence (rollback,
     failover, flag off) for the user's go-ahead. Re-observe once it lands, and only then
     root-cause. Hold two hypotheses while you orient. An irreversible move waits for
     evidence. The approval gate above holds.
   - **systems** — use it when a fix here breaks something there, or when no single
     component is at fault. Map the components and their feedback loops (retry storm, cache
     stampede, queue backup). Trace the symptom upstream. Look for the delay that hides the
     cause from the effect.

4. **Trace the provenance.** Once the root cause is confirmed, find the commit that
   introduced it. This is part of the root cause, not an optional extra:
   - When the defect is textual, `git log -S'<defect pattern>'` / `-G` on the faulty code,
     or `git blame` on the exact lines, gets you there cheaply.
   - When it isn't (emergent behavior, interaction bugs), use `git bisect run` with the
     repro from step 2 as the test.
   - **Prove it counterfactually**: the repro fails at the suspect commit and passes at its
     parent. A commit that merely *touched* the file is not the introducing commit.

   Then name *why it slipped through*. Examples: no test covered the path, the review missed
   it, the spec was ambiguous, a cross-repo contract drifted, a migration went unrefreshed.
   That one line turns a fixed bug into a pattern the team can act on.

   **Journaled: append `debug-root-cause` the moment the cause is confirmed.** Include the
   introducing commit once you have it. In any case, append before step 5. The root-cause
   report, the ledger jot and this event describe one fact, and they land in the same turn.
   A diagnosis delivered without the event leaves the stream saying nothing happened.

5. **Jot the trap to the ledger — now, before the fix plan.** The confirmed cause is the
   moment the learning exists in full. By the time the fix is verified and reported, the
   learning has been compressed to "fixed", and Capture finds an empty ledger. The cause may
   be a *reusable trap*: a default that silently disables a feature, a command or log line
   that lies, a test that passes vacuously, a tool or library quirk, a contract that
   drifted. If so, append one dated line to the project **ledger**. The ledger is the path
   the config declares, or `docs/ledger.md` when that file already exists. It is one tool
   call with no quality gate, because Capture triages it. If you ask "is it worth a line?",
   the answer is yes:

   ```bash
   printf -- '- %s — gotcha: <what silently bit, where, the one-line rule>\n' "$(date +%F)" >> docs/ledger.md
   ```

   The line goes in the ledger. It does not go in `CLAUDE.md` (operating instructions, not a
   gotcha landfill). It does not go in an ADR (a Capture-time promotion, if at all). It does
   not go in Claude's built-in memory. A project with no ledger (nothing declared, no file)
   gets none from a debugging step. Skip the line and let the "why it slipped through"
   sentence carry the trap. A typo or a one-off data glitch is not a trap either; skip the
   line. Anything smaller you hit on the way (a misleading log line, a debugging trick, a
   fixture quirk) gets the same one-liner the moment it surfaces. This step is one command
   between the diagnosis and the plan. It never replaces or delays the root-cause report,
   and it is not the fix.

6. **Plan the fix.** Present the candidate fix(es) with their risk and the verification
   steps. Recommend one. Ask for approval and stop. The edit happens in the turn after the
   yes, never in the same turn as the proposal.

## Validate the fix

- Confirm a **failing signal existed before** the fix (you reproduced it).
- Apply the fix. Confirm success via `verify`, including the regression pattern for bugs:
  the test fails on the unfixed code and passes on the fixed code.
- Summarize residual risk and any follow-ups.

**Report the provenance on the tracker issue.** When the bug has a tracker issue and the
config declares a forge, post a root-cause comment. Like any outward-facing post, it needs
the user's go-ahead. The comment carries the root cause in a sentence, the introducing
commit (hash + one line on what it changed), and why it slipped through. This is how the
team maps *where and why* bugs enter the codebase. A fix without the provenance comment
loses that signal.

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
the ledger line and the provenance comment; absent, a placeholder, or `plain`, write them as
before.

When you land the root cause, capture it via `knowledge-base`. A root cause + fix is
**technical** knowledge. So it routes to the store configured for engineering knowledge, not
a product/domain store. The default is an ADR if it changed a decision, otherwise a repo
docs note. Capture the diagnosis and the fix, so the next person (or the next you) doesn't
re-derive it from scratch. The ledger line from step 5 is its raw material. If it is not
there, a step was skipped. Write it before the report, not instead of it.

## Record the diagnosis (journaled projects)

The appends in steps 2 and 4 take this form. The stream is the one named in the pre-flight
above (`fix/1290-date-off-by-one`: one stream per issue, like any other flow). The event
gives the diagnosis by pointer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type debug-root-cause \
  --data '{"cause":"<one sentence>","introduced_by":"<commit>","refs":["docs/prd/<slug>.worklog.md#root-cause"]}'
```

When the stream does not exist yet, open it and record into it in one `--batch` (JSONL on
stdin; for the stdin form, see `verify`). A missing stream is never a reason to wait for a
branch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream fix/<slug> --batch <<'EOF'
{"type":"flow-started","data":{"request":"<the report, one line>","branch":"fix/<slug>"}}
{"type":"debug-root-cause","data":{"cause":"<one sentence>","introduced_by":"<commit>","refs":["<where the evidence lives>"]}}
EOF
```

On a journaled project the diagnosis is not delivered until its event is in. The report and
the append go out in the same turn. Four events carry a debug flow, and you append each one
when it happens:
- `bug-reproduced`, once expected vs actual is pinned down.
- `debug-root-cause`, when the cause is established.
- `gate-decision`, for every fork you settle on the way to the fix. *That is the event for a
  decision*, whatever you would naturally call it. It carries `raised_by`: `user` when the
  user raised or corrected the point, `orchestrator` when you asked or decided it. Add
  `--actor user` for the user's own calls.
- `verify-run`, for the evidence the fix holds. That is exactly what the failing-test-first
  run produces.

**`bug-reproduced` and `debug-root-cause` are the two that bloat — pointer, not prose.** The
repro steps, the environment fingerprint, the hypothesis table and the evidence trail live in
the worklog or on the tracker issue. The event carries one sentence plus `refs` naming the
section that holds them. The journal refuses a payload over 1 KB for exactly that reason. A
diagnosis pasted into the journal is a diagnosis nobody can search, review or reuse.

**Use the canonical names and shapes.** `journal.py vocab` lists the types, and
`vocab --shape <type>` prints the payload each one takes. `append` refuses anything else. An
event named something plausible-but-unlisted is inert: it records, but no gate or report
ever reads it, and that looks like success. If a debug flow genuinely needs a concept the
vocabulary lacks, mint it deliberately with `--new-type`. Do not invent a near-miss of a
name that already exists. A missing or unreadable database is an infrastructure failure,
not a reason to skip the append. Surface it loudly. Continue un-journaled only with the
user's acknowledgement.
