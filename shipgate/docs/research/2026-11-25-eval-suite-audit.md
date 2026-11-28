---
title: eval suite audit — what each case decides, what it costs, what stays
date: 2026-11-25
status: draft research note — the Explore phase of #28 (with #49); informs Clarify and Design, decides nothing by itself
---

# Eval suite audit

## Why this note

Issue #28 makes the evals record the model, the cost and the time, and re-baselines them per
model. Before any money goes into a re-baseline, the suite itself gets an audit. Three rulings
of the user (2026-11-24) bind it:

1. We do not measure, and spend on, what we do not need. Each case names the behaviour it
   judges and the decision that a fall of its score would change. A case with no such
   decision, or one that repeats another case, is cut or merged.
2. If a check can be deterministic, it must be. A unit test, a prose test, a regex or script
   grader, or a trigger probe takes over what it can judge. An eval case stays only for
   behaviour that needs a model run.
3. Costs are measured per case and per model. Every score carries its ablation mode. Scores
   from different modes are never compared.

This audit spent 0 USD. It ran no eval, no probe and no nested session.

## Method

| Input | Size |
| --- | --- |
| Case files read in full: `prompt.md`, `case.yaml`, every grader | 78 cases, 451 graders: 253 regex, 104 tool_used, 62 LLM judge, 32 file_exists |
| `baseline.json` | 75 rows; 63 from plugin 0.15.0; none for 76–78 |
| Saved result directories of the maintainer's checkout (ignored by git) | 450 directories, 523 result files, 2,553 runs, 224 of them errored |
| Offline checks of a fixture with `signals.py` | cases 08 and 10, 0 USD |

- The saved runs cost 724.00 USD in total. The judge took 25.80 USD of it. The 224 errored
  runs cost 4.54 USD: 167 hit the session limit, 44 hit the credential-store refusal, 13
  others.
- Only 251 runs, in 15 cases, record a model: 127 Opus and 124 Fable. They are runs with
  `--model`, all from 2026-11-24 or later. The other 2,302 runs record no model. They ran on
  the account default.
- The default-model costs match the Opus costs. On the 12 cases that have both, the
  default-model with arm costs 0.92 times the Opus with arm (median; range 0.75 to 1.52). The
  Fable with arm costs 2.08 times the Opus with arm (median of 15 cases; range 1.51 to 2.26)
  and runs 1.23 times as long. So this note treats a default-model run as an Opus-tier run.
  That is an inference from cost, not a record.
- A baseline score below is the recorded row: with arm, without arm, delta (Δ), the plugin
  version, and the age in days on 2026-11-25. Every baseline row ran in the
  `with-without` mode.
- A cost below is the mean cost and the mean time of one run of one arm, from the run that
  the baseline row names, and from the newest runs per model where they exist. The judge cost
  is not in it.
- No raw answer, trace or path of a private project is in this note. All fixtures are
  synthetic.

## Verdicts and decisions

### The decisions a score informs

| Id | Decision | Which score | Arms it needs |
| --- | --- | --- | --- |
| D1 | A skill edit broke a behaviour: fix or revert the edit before the release | the with arm falls | with |
| D2 | A skill section shows no lift: shorten or cut its text (#32) | Δ is 0 on both session models | with and without |
| D3 | A new model release: decide D2 again for that model | Δ moves on the new model | with and without |
| D4 | The skill fires where it must not, or does not fire where it must: tune the description | the firing count | trigger probe |

### The verdicts

- **keep**: only a model run can judge the behaviour, and a fall changes a decision above.
  Either Δ is above 0, or the case guards a risk that only the plugin brings (a "with-arm
  guard", run in the `none` mode).
- **keep until #32**: Δ is 0 on the recorded model, or rests on one run of three, and the
  case is the only one for its skill behaviour. It is the instrument for #32's ablation. It runs once per model. If Δ is 0
  on both models, #32 decides on its text, and the case is cut with that text.
- **merge into N**: case N judges the same scenario or the same mechanism. Anything unique
  moves to N.
- **move**: a deterministic check judges the claim: a fixture test of a plugin script, a
  trigger probe, or the retro's count over real journals.
- **cut**: the score informs no decision.
- **repair**: the case is needed, but a grader or the fixture is broken. The row says what to
  repair. After the repair, the case is kept.

### Counts per verdict

| Verdict | Cases | Count |
| --- | --- | --- |
| keep | 02 03 04 05 16 18 19 22 23 26 38 43 45 46 51 68 77 | 17 |
| keep as a with-arm guard (`--ablation none`) | 48 52 | 2 |
| keep until #32 | 17 24 25 29 30 31 32 33 36 39 40 47 53 54 55 69 74 | 17 |
| repair, then keep | 15 58 70 73 76 | 5 |
| repair after #74 (skip until then) | 78 | 1 |
| merge into another case | 01 44 59 60 61 62 63 65 66 | 9 |
| move to a fixture test or the retro count | 08 09 10 12 13 14 72 75 | 8 |
| move to a trigger probe | 06 07 11 20 21 27 28 34 35 41 42 49 50 56 57 67 | 16 |
| cut | 37 64 71 | 3 |
| **total** | | **78** |

After the verdicts, 24 cases run at every re-baseline (keep, guards, repaired), and 17 run
once for #32. Each merge row names what the merge loses. Every lost grader passes in both
arms, except the journal events (decision 2) and two findings named in rows 62 and 01.

## Per-case table

Legend:

- Graders: `rx` regex, `llm` LLM judge, `tu` tool_used, `fe` file_exists. "(d)" means
  display-only under `with-without` (the `skill-fired` grader). "w 2/3, wo 0/3" counts the
  runs where the grader passed in the with arm and in the without arm of the baseline run.
  "Det" names a deterministic check that judges the same claim. "Pinned" names a test that
  already pins it.
- Cost: "default" is the account default model (not recorded); the mode follows the version.

| # | Skill: behaviour judged | Decision a fall informs | Graders | Baseline w / wo / Δ · version · age | Measured cost/time per run | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | structured-debug: diagnose a failing test, name the commit, say why it slipped through, hold the fix | D1, D2 | llm (5 claims), rx ×2, tu (d). All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.27/63s, wo $0.16/43s | merge into 58: the same regression (`ROUND_DOWN`, a failing pricing test). 58's judge lacks the claim "says why it slipped through"; it moves to 58 as a one-claim llm grader |
| 02 | structured-debug: use the EU-vs-US contrast to find the cause; hold the fix | D1, D2 | llm (6 claims) w 2/3, wo 0/3; rx fix kept (wo 1/3); rx double VAT; tu (d) | 0.89 / 0.44 / +0.44 · 0.15.0 · 44d | default w $0.28/52s, wo $0.17/37s | keep |
| 03 | structured-debug: do not confirm the user's null-check guess | D1, D2 | llm (4 claims) wo 0/3; rx lookup kept (wo 0/3); rx no null check; rx normalisation (0.5); tu (d) | 1.00 / 0.43 / +0.57 · 0.15.0 · 44d | default w $0.27/61s, wo $0.13/26s | keep |
| 04 | structured-debug: a pasted trace with no repo gives hypotheses and the evidence that decides each | D1, D2 | llm (6 claims) wo 1/3; rx provider B (0.5, passes both); tu (d) | 1.00 / 0.56 / +0.44 · 0.15.0 · 44d | default w $0.22/34s, wo $0.13/28s | keep |
| 05 | structured-debug: "just fix it" is not plan approval | D1, D2 | llm (4 claims) wo 0/3; rx fix kept (wo 0/3); rx UTC; tu (d) | 1.00 / 0.33 / +0.67 · 0.15.0 · 44d | default w $0.24/30s, wo $0.13/26s | keep |
| 06 | structured-debug negative: a feature request does not fire it | D4 | tu skill-not-fired; rx no debug words; llm 1. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.18/25s, wo $0.15/24s | move: trigger probe |
| 07 | structured-debug negative: an explain question does not fire it | D4 | tu, rx, llm. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.16/23s, wo $0.13/23s | move: trigger probe |
| 08 | structured-debug: rank suspect files by fix history (natural prompt) | D2, D4 | rx true file; rx fix kept; llm ranking (0.5); tu (d). All pass in both arms. Det: `signals.py suspects` on the fixture ranks `monthRange.ts` first (run offline, 0 USD) | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.26/39s, wo $0.14/31s | move: a fixture test of `signals.py suspects`; firing goes to the probe set |
| 09 | route-and-map: list the direct and transitive importers (natural prompt) | D2, D4 | rx ×6 file names; llm 1; tu (d). All pass in both arms. Det: the fixture is the one of 13, which `signal_grader.py fixture` scores P/R 1.00 offline | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.24/42s, wo $0.15/33s | move: into the fixture check of 13; firing goes to the probe set |
| 10 | review: rank the changed files by regression risk (natural prompt) | D2, D4 | rx list, rank 1, rank 2; llm evidence (0.5); tu (d). All pass in both arms. Det: `signals.py hotspots --diff HEAD~1` ranks `promo.ts` and `calendar.ts` first (run offline, 0 USD) | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.24/21s, wo $0.17/71s | move: a fixture test of the hotspots ranking; firing goes to the probe set |
| 11 | route-and-map negative: a README typo gets no impact analysis and no codegraph run | D4 | tu skill-not-fired; tu no codegraph Bash; llm 1; rx ×2 on the file. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.14/13s, wo $0.10/15s | move: trigger probe that also counts `signals.py` and `codegraph` Bash calls |
| 12 | structured-debug explicit: as 08, the prompt names the skill | D1 | as 08, with skill-fired scored. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.27/40s, wo $0.16/33s | move: into the fixture test of 08 |
| 13 | route-and-map explicit: the impact map from the computed importers | D1 | as 09, with skill-fired scored. All pass in both arms. Pinned: `test_signal_grader.py` already runs the offline fixture of 13 (regex arm, P/R 1.00/1.00) | 1.00 / 1.00 / +0.00 · 0.23.0 · 18d | default w $0.26/39s, wo $0.27/97s | move: done; the unit test exists, so the eval case goes |
| 14 | review explicit: as 10, the prompt names the skill | D1 | as 10, with skill-fired scored. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.24/19s, wo $0.15/79s | move: into the fixture test of 10 |
| 15 | clarify executive: a PRD from a ticket keeps design out of the requirements and records its assumptions | D1, D2 | rx ×7 (4 restatements pass both; no design wo 0/3; no implementation leak wo 0/3); llm exec-hygiene (wo 1/3); tu (d). Det: exec-hygiene's claims (section, answer, rationale, non-goals) fit the assumptions parser and a regex | 0.94 / 0.56 / +0.39 · 0.15.0 · 44d | default w $0.40/76s, wo $0.31/75s; Opus 0.33.0 (`none`) w $0.41/73s; Fable 0.33.0 (`none`) w $0.87/93s | repair: replace exec-hygiene with a parser and regex check; add a repo-local git identity to the fixture; then keep |
| 16 | clarify executive: a schema or public-API one-way door stays under a `NEEDS CLARIFICATION` marker | D1, D2 | rx api-escalated (replaced an llm judge in 0.34.1; pinned by `test_eval_graders.py`); rx open marker (wo 0/3); llm hands decisions to the user (passes both) | 1.00 / 0.53 / +0.47 · 0.15.0 · 44d | default w $0.38/74s, wo $0.27/67s; Opus 0.34.0 (`none`) w $0.51/93s; Fable 0.34.0 (`none`) w $1.04/112s | keep; the baseline row describes the old llm grader |
| 17 | clarify executive: catch the request's stale assumption and reuse the existing due-date helper | D2 | rx ×3, llm 1. All pass in both arms; Opus and Fable with arm 3/3 | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.35/64s, wo $0.26/56s; Opus 0.33.0 (`none`) w $0.38/63s; Fable 0.33.0 (`none`) w $0.80/78s | keep until #32; add a repo-local git identity to the fixture |
| 18 | clarify ask: a vague request gets at most 5 questions, scope first, each with a recommended answer | D1, D2 | fe ×2; rx ×3 (open items wo 0/3); llm recommendation-first (w 1/3, wo 1/3; Opus 2/3, Fable 3/3); llm scope-first (passes both) | 0.90 / 0.72 / +0.18 · 0.15.0 · 44d | default w $0.33/57s, wo $0.21/46s; Opus 0.33.0 (`none`) w $0.34/54s; Fable 0.33.0 (`none`) w $0.69/63s | keep; add a repo-local git identity to the fixture |
| 19 | clarify ask: a fully specified request gets at most 2 questions and none re-asked | D1, D2 | llm few-questions (wo 2/3); rx ×10 (8 restatements pass both; no design w 2/3, wo 0/3) | 0.92 / 0.75 / +0.17 · 0.15.0 · 44d | default w $0.34/59s, wo $0.27/63s; Opus 0.33.0 (`none`) w $0.36/64s; Fable 0.33.0 (`none`) w $0.66/58s | keep; add a repo-local git identity to the fixture |
| 20 | clarify negative: a one-line typo gets no PRD and no questions | D4 | tu, fe, rx ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.15/10s, wo $0.11/9s | move: trigger probe |
| 21 | clarify negative: an explain question gets no PRD | D4 | tu, fe, rx ×4. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.16/18s, wo $0.13/22s | move: trigger probe |
| 22 | verify: fix, run again after the last edit, report the status the run shows | D1, D2 | llm status (wo 1/3); llm over the trace, last run after the last edit (passes both); rx command (wo 2/3), hedge words (wo 2/3), result | 1.00 / 0.71 / +0.29 · 0.15.0 · 44d | default w $0.36/47s, wo $0.28/47s | keep; the trace judge is an order check that a trace script can do |
| 23 | verify: a rename with "tell me when it's done" still cites a test run | D1, D2 | rx ×5 (command named wo 1/3; the rest pass both) | 1.00 / 0.89 / +0.11 · 0.15.0 · 44d | default w $0.21/19s, wo $0.12/12s | keep |
| 24 | verify: a pasted green run is stale, and the fresh run fails | D2 | rx ×6 (fresh run cited wo 2/3; the rest pass both) | 1.00 / 0.96 / +0.04 · 0.15.0 · 44d | default w $0.17/14s, wo $0.12/21s | keep until #32 |
| 25 | verify: the runner discovered 0 tests | D2 | rx ×5. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.22/22s, wo $0.15/19s | keep until #32 |
| 26 | verify: lint and tests are two claims and two commands | D1, D2 | rx ×4 (test result cited wo 0/3) | 1.00 / 0.71 / +0.29 · 0.15.0 · 44d | default w $0.20/18s, wo $0.14/22s | keep |
| 27 | verify negative: an explain question runs no command | D4 | tu no Bash; tu skill-not-fired; llm 1. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.15/16s, wo $0.11/17s | move: trigger probe that also counts Bash calls |
| 28 | verify negative: "run once" runs the suite once | D4 | tu exactly one run (wo 2/3; the skill fired in 0 of 3 with runs); rx ×3 | 1.00 / 0.87 / +0.13 · 0.15.0 · 44d | default w $0.14/11s, wo $0.10/10s | move: trigger probe that also counts `unittest` calls |
| 29 | route-and-map: a nested CLAUDE.md rule sends a reporting endpoint to `reports/` | D2 | llm, rx, tu Edit (wo 2/3), fe | 1.00 / 0.94 / +0.06 · 0.15.0 · 44d | default w $0.27/41s, wo $0.18/33s | keep until #32 |
| 30 | route-and-map: ADR 0002 splits an SMS change across api and worker | D2 | rx ×2, llm, tu. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.29/47s, wo $0.19/36s | keep until #32 |
| 31 | route-and-map: a schema change names the snapshot obligation | D2 | rx ×3, llm, tu. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.28/40s, wo $0.16/31s | keep until #32 |
| 32 | route-and-map: two rules collide; surface the conflict or split the work | D2 | llm, rx, tu. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.27/43s, wo $0.18/33s | keep until #32 |
| 33 | route-and-map: the rule wins over a hot file's risk signal | D1, D2 | rx ×2, llm, tu. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.30/51s, wo $0.20/59s | keep until #32 |
| 34 | route-and-map negative: a one-line config change gets no map | D4 | rx ×2; tu skill-not-fired; tu no `signals.py` Bash. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.14/13s, wo $0.11/13s | move: trigger probe that also counts `signals.py` Bash calls |
| 35 | route-and-map negative: an explain question gets no map | D4 | llm, rx, tu ×2. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.20/29s, wo $0.17/37s | move: trigger probe |
| 36 | knowledge-base: "what do we know about X" answers from the ADRs | D2 | llm, rx, fe. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.25/31s, wo $0.18/31s | keep until #32 |
| 37 | knowledge-base: a request that contradicts ADR 0003 is answered within the ADR or with a supersede | none: the skill fired in 0 of 3 with runs, and the bare model passes | rx, fe, tu, llm. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.21/36s, wo $0.16/34s | cut. No other case judges a request that contradicts a recorded ADR; no plugin text earns this pass (decision 8) |
| 38 | knowledge-base: "note for later" becomes a dated ledger line | D1, D2 | rx ×3 (ledger note wo 0/3, dated line wo 0/3), fe ×2 | 1.00 / 0.62 / +0.38 · 0.15.0 · 44d | default w $0.18/14s, wo $0.12/14s | keep |
| 39 | knowledge-base: triage the ledger, keep a secret out | D2 | llm, rx ×3, fe. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.29/49s, wo $0.20/44s | keep until #32 |
| 40 | knowledge-base: a capture updates the CLAUDE.md rule, not the ledger | D2 | rx ×3, fe. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.22/24s, wo $0.14/19s | keep until #32 |
| 41 | knowledge-base negative: a personal preference stays out of the repo | D4 | llm; rx ×2 and fe on the repo docs; tu skill-fired (d). All pass in both arms; the skill fired in 0 of 3 | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.15/15s, wo $0.10/13s | move: trigger probe that counts Write and Edit calls on repo docs, not only Skill calls |
| 42 | knowledge-base negative: a code question writes nothing | D4 | rx; tu skill-not-fired; tu no Edit; tu no Write. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.13/9s, wo $0.09/8s | move: trigger probe that also counts Edit and Write calls |
| 43 | knowledge-base: a gotcha found during a fix is jotted unprompted | D1, D2 | rx ×4 (jotted wo 1/3). The skill fired in 0 of 3 with runs, so another part of the plugin gives the lift | 1.00 / 0.78 / +0.22 · 0.15.0 · 44d | default w $0.27/35s, wo $0.14/21s | keep; Clarify names the part that jots |
| 44 | review: find the planted bugs, do not raise the recorded deviation, verdict not ready | D1, D2 | llm findings-quality failed 6 of 6 runs in both arms; rx ×3 pass both. The deviation's revisit date (2026-10-05) is fixed and has passed; 46 moved to a date 30 days ahead because every model flags an expired deviation, so the expired date is the likely cause | 0.71 / 0.71 / +0.00 · 0.15.0 · 44d | default w $0.38/66s, wo $0.18/41s | merge into 70 (add a recorded deviation with 46's future-date mechanism, and its regex) and 46 |
| 45 | review: an unmet acceptance criterion makes the verdict not ready | D1, D2 | llm (wo 2/3), rx ×2 | 1.00 / 0.87 / +0.13 · 0.15.0 · 44d | default w $0.31/47s, wo $0.17/40s | keep |
| 46 | review: a clean diff with recorded deviations is ready, with no invented findings | D1, D2 | llm, rx ×2 (says ready wo 2/3) | 1.00 / 0.89 / +0.11 · 0.15.0 · 44d | default w $0.32/45s, wo $0.17/35s | keep |
| 47 | review: the re-review reads the fix commit and finds its new regression | D2 | llm, rx ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.33/40s, wo $0.17/37s | keep until #32 |
| 48 | review: a small diff gets at most one reviewer agent | D1 (over-spawning is a plugin-only risk) | tu Agent at most 1 (passes both), rx ×3 | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.28/33s, wo $0.14/31s | keep as a with-arm guard (`--ablation none`) |
| 49 | review negative: "explain the change" gets no verdict and no agents | D4 | tu ×2, rx ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.18/22s, wo $0.14/21s | move: trigger probe that also counts Agent calls |
| 50 | review negative: a trivial change gets no agents and no blocker | D4 | tu skill-not-fired; tu no Agent; rx ×2. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.15/25s, wo $0.11/20s | move: trigger probe that also counts Agent calls |
| 51 | design executive: a real fork gets alternatives, an ADR and a worklog in the template | D1, D2 | fe ×3; rx ×11 (approach heading wo 0/3, `[P]` markers wo 0/3, trade-off wo 0/3, ADR wo 1/3) | 0.98 / 0.57 / +0.41 · 0.15.0 · 44d | default w $1.15/174s, wo $0.32/86s; Opus 0.33.0 (`none`) w $1.01/155s; Fable 0.33.0 (`none`) w $2.09/216s | keep; the most expensive kept case |
| 52 | design executive: no fork means at most one architect agent and a worklog with tasks | D1 (over-fanning) | tu Agent at most 1, fe ×2, rx ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.43/86s, wo $0.30/71s; Opus 0.33.0 (`none`) w $0.49/94s; Fable 0.33.0 (`none`) w $1.06/115s | keep as a with-arm guard (`--ablation none`) |
| 53 | design ask: recommend, name the alternative, wait for the go | D2 | llm, rx, fe ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.27/49s, wo $0.17/37s; Opus 0.33.0 (`none`) w $0.31/49s; Fable 0.33.0 (`none`) w $0.67/69s | keep until #32 |
| 54 | design: a prior ADR (the worker sends) shapes the design | D2 | rx ×4, fe ×2. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.47/103s, wo $0.31/78s; Opus 0.33.0 (`none`) w $0.51/104s; Fable 0.33.0 (`none`) w $1.16/134s | keep until #32 |
| 55 | design executive: a breaking public-API change goes to the user | D1, D2 | llm (Opus 2/3 at 0.33.0), rx ×2, fe | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.86/150s, wo $0.28/72s; Opus 0.33.0 (`none`) w $0.56/125s; Fable 0.33.0 (`none`) w $1.23/148s | keep until #32 |
| 56 | design negative: "implement T1" does not design again | D4 | tu, fe ×2, rx. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.28/41s, wo $0.17/32s | move: trigger probe |
| 57 | design negative: an ADR question writes nothing | D4 | rx; tu design-not-fired; tu no Edit; fe. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.14/11s, wo $0.11/10s | move: trigger probe that also counts Edit calls |
| 58 | structured-debug, large journaled repo: the regression of 01, and the debug event in the journal | D1, D2 | llm (wo 2/3); rx ×6. Of the 3 journal regexes: any-event and phase-event match October 2026 dates only, so both fail in both arms from November; no-invented-types passes in both arms by construction | 1.00 / 0.73 / +0.27 · 0.15.0 · 44d | default w $0.33/75s, wo $0.20/52s | repair: drop any-event and no-invented-types; make phase-event date-free (the seed holds no debug event) and `arm: with-only`; take in 01's claim; then keep |
| 59 | structured-debug, large repo: the selective bug of 02 | D2 | without the journal graders the score is 1.00 / 1.00 | 1.00 / 0.82 / +0.18 · 0.15.0 · 44d | default w $0.35/68s, wo $0.17/41s | merge into 02; the debug event stays in 58. Lost: `cites-adr-0006` (passes in both arms) |
| 60 | route-and-map, large repo: the nested rule of 29 | D2 | without the journal graders 1.00 / 1.00 | 1.00 / 0.80 / +0.20 · 0.15.0 · 44d | default w $0.34/51s, wo $0.24/44s | merge into 29. Lost: `cites-adr-0005` (passes in both arms) and the route-and-map journal event (decision 2) |
| 61 | route-and-map, large repo: the rule conflict of 32 | D2 | without the journal graders 1.00 / 1.00 | 0.95 / 0.71 / +0.24 · 0.15.0 · 44d | default w $0.37/59s, wo $0.24/43s | merge into 32. Lost: the route-and-map journal event (decision 2) |
| 62 | review, large repo: planted bugs, as 44 | D2 | without the journal graders 0.90 / 0.90. Its deviation carries the same expired date (2026-10-05) | 0.93 / 0.73 / +0.20 · 0.15.0 · 44d | default w $0.58/108s, wo $0.26/59s | merge into 70. Lost: the unknown-order finding (an empty row raises IndexError, not a 404); 48 keeps a similar crash-on-missing-input finding |
| 63 | review, large repo: the re-review of 47 | D2 | without the journal graders 1.00 / 1.00 | 1.00 / 0.80 / +0.20 · 0.15.0 · 44d | default w $0.35/49s, wo $0.18/44s | merge into 47 |
| 64 | knowledge-base, large repo: the implicit recall of 37 | none: the skill fired in 0 of 3 with runs | rx, fe, tu, llm. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.33/49s, wo $0.21/47s | cut |
| 65 | clarify, large repo: the stale assumption of 17 | D2 | without the journal graders 1.00 / 0.89 (one regex, one run); `journal-fr-count` passes on the seeded events | 1.00 / 0.80 / +0.20 · 0.15.0 · 44d | default w $0.58/119s, wo $0.42/88s | merge into 17. Lost: `delivery-via-worker` (passes in both arms) and the clarify-passed journal event (decision 2) |
| 66 | design, large repo: the prior ADR of 54 | D2 | without the journal graders 0.93 / 1.00 | 0.94 / 0.83 / +0.11 · 0.15.0 · 44d | default w $2.12/335s, wo $0.58/133s | merge into 54. Lost: `reuses-is-overdue` (passes in both arms), the design-committed journal event (decision 2); 51 keeps `tests-as-tasks` |
| 67 | negative, large journaled repo: a one-line change gets no flow, with the status brief in context | D4 | tu ×3 (no clarify, no route, no `journal.py`), rx ×2. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.14/14s, wo $0.12/18s | move: trigger probe in this fixture that also counts `journal.py` calls |
| 68 | design: state the strongest case for the approach not recommended | D1, D2 | llm steel-man (w 1/3, wo 0/3); rx strongest case (wo 1/3); rx recommend (wo 0/3); fe ×2 | 0.85 / 0.48 / +0.37 · 0.15.0 · 44d | default w $0.29/54s, wo $0.18/36s | keep |
| 69 | structured-debug: the running code wins over the docs and the green tests | D2 | llm, rx ×3. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.15.0 · 44d | default w $0.28/50s, wo $0.16/37s | keep until #32 |
| 70 | review: three planted facts survive the writing-for-people rule; verdict not ready | D1, D2 | llm facts (passes both); llm readable failed 6 of 6 runs in both arms; rx ×6 (verdict wo 0/3, export line wo 1/3) | 0.96 / 0.69 / +0.27 · 0.15.0 · 44d | default w $0.40/65s, wo $0.20/48s | repair: replace `readable` with a sentence-length script (its claim 1) and a regex for inline code (its claim 3); its claim 2 is in `facts-retained` and `no-hedges`; take in the deviation of 44; then keep |
| 71 | implement: reuse `withBackoff` (explicit prompt) | none: both arms 1.00, and 73 is the harder twin | rx ×2, llm. All pass in both arms | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.34/65s, wo $0.22/51s | cut |
| 72 | route-and-map: the blast radius in a 484-file workspace | D1 (signals) | llm impact list, rx ×5 sentinels (wo 5/6 on one), tu ×2 (d). Det: `signal_grader.py fixture 72 --arm graph` gives 59 of 59 offline | 1.00 / 0.97 / +0.03 · 0.24.0 · 17d | default w $0.42/71s, wo $0.58/172s | move: run the offline signal grader of 72 as a unit test that skips without codegraph. Lost: the answer's precision against the decoys and the 13-of-15 tests claim, both passing in both arms |
| 73 | implement: reuse a helper whose name and path say nothing | D2 | rx ×2, llm. All pass in both arms. The fixture gives the helper away: three commit subjects say "call policy" or "flaky upstreams", the doc comment describes the doubling pause, the word `attempts` appears five times, and two callers already use `withPolicy` | 1.00 / 1.00 / +0.00 · 0.17.0 · 37d | default w $0.40/79s, wo $0.30/66s | repair: remove the giveaways, and extend the fixture's assert to the commit subjects; prove offline that a grep finds nothing; then keep (decision 5) |
| 74 | review: the config's canon skill gives two must-fix findings; the verdict records `style` | D2 | rx ×3, llm pass both; rx journal verdict (wo 0/3 because the bare arm has no journal); rx style (already with-only) | 1.00 / 0.89 / +0.11 · 0.20.0 · 23d | default w $0.98/116s, wo $0.89/117s; Opus 0.33.0 (`none`) w $1.11/125s; Fable 0.33.0 (`none`) w $1.68/139s | keep until #32; mark `journal-verdict-appended` `arm: with-only` |
| 75 | review: the graph ranking reaches the review verdict (#10) | D1 | llm hot file first passes both; 2 journal regexes give the whole +0.60 (the bare arm cannot write the journal); tu `hotspots --diff` (with-only) | 1.00 / 0.40 / +0.60 · 0.20.0 · 23d | default w $0.57/108s, wo $0.58/109s; Opus 0.33.0 (`none`) w $0.72/126s; Fable 0.33.0 (`none`) w $1.35/151s | move: `signals.py` computes the ranking (unit-tested). That review runs it and records it is model behaviour; the retro counts it in real journals, after a release (decision 2) |
| 76 | clarify executive: one confirm batch of risky assumptions, the blindspot from git history, the policy file as a source | D1, D2 | llm ×5 (batch-items-risky 0 of 12; blindspot 12 of 12); rx ×3; tu parser ran. Pinned: the cap of 4 by `test_the_cap_is_four` in `test_journal_assumptions.py` | none | Opus 0.34.1 (`none`) w $0.60/126s; Fable 0.34.1 (`none`) w $1.20/155s | repair: split batch-items-risky and drop its "at most 4" claim; then keep |
| 77 | clarify: a UI change asks for a visual reference | D1, D2 | llm reference asked (Opus w 4/6; Fable w 6/6); rx reference in PRD. The without arm is shadowed: every without run loaded the installed `shipgate` (addendum below), so it has no bare number | none | Opus 0.36.0 (`with-without`) w $0.44/78s; Fable 0.36.0 (`with-without`) w $0.94/88s; no bare cost | keep; decision 4 |
| 78 | clarify executive: a fully specified request asks nothing | D1 | llm asks-nothing 0 of 12; rx no-batch-lines 0 of 12 (pinned by `test_eval_graders.py`) | none | Opus 0.34.1 (`none`) w $0.45/73s; Fable 0.34.1 (`none`) w $0.95/100s | repair after #74. It failed 12 of 12 runs; the #28 comment says the model always finds another unsourced detail. Skip it until #74 decides the batch rule |

## Findings across the suite

1. **The big journaled cases show lift only through their journal graders.** Without the
   journal graders, the without arm of 59, 60, 61 and 63 scores 1.00, as the with arm does.
   Case 64 has no journal grader and scores 1.00 in both arms. In 66 the without arm scores
   higher (1.00 against 0.93). Only 58 (0.90) and 65 (0.89) keep a small Δ, from one grader
   in one run.
2. **Four journal graders are broken by construction.**
   - `journal-any-event-appended` (58–63, 65, 66) matches any row dated October 2026. In an
     October run, the `session-started` row that the SessionStart hook writes was enough to
     pass it, so it judged that the hook ran (`test_hooks.py` already pins that). From
     November on, it fails in both arms.
   - `journal-phase-event-appended` (58–63, 65, 66) also matches October 2026 dates only, and
     fails in both arms from November. The seed holds no debug event, so 58's grader can drop
     the date. The seed holds `route-and-map`, `clarify-passed`, `design-committed` and
     `review-verdict` rows, so the graders of 60–63, 65 and 66 need a date filter.
   - `journal-no-invented-types` (58–63, 65, 66) and `journal-fr-count` (65) pass in both
     arms. `append` refuses a type outside the vocabulary, and the fixture already seeds a
     `clarify-passed` row with `fr_count`.
3. **With-arm-only claims inflate Δ.** A journal grader scored in both arms gives the bare
   arm a sure 0, so Δ counts the presence of the plugin. Case 75's whole Δ of +0.60 comes from
   its two journal graders. Case 74's +0.11 comes from one. The harness already has
   `arm: with-only`; 74 uses it for one grader only.
4. **Three LLM judges fail in every run of both arms.** Case 44's `findings-quality` failed
   6 of 6. Its likely cause is a fixture date: the recorded deviation says "revisit
   2026-10-05", and every model flags an expired deviation (case 46 met this on 2026-10-06
   and moved to a date 30 days ahead). The large fixture of 58–67 carries the same expired
   date. Case 70's `readable` failed 6 of 6. Case 76's `batch-items-risky` failed 12 of 12
   on 0.34.1. A grader that fails in both arms adds noise and judge cost, and no signal.
5. **The bare model matches the plugin in 28 of the 59 positive cases.** Their Δ is 0, and
   in 27 of them both arms score 1.00. In 22 of the 31 cases with Δ above 0, the Δ rests on
   one or two graders. In 45 and 46 it rests on one run of three.
   With three runs, a one-run difference is within noise. A decision that rests on it needs
   more runs first.
6. **Three natural-prompt cases are triggering checks in disguise.** In 08, 09 and 10 the
   answer is at the ceiling in both arms. The plugin's contribution is the `signals.py`
   ranking, and a fixture test reproduces it at 0 USD. The offline run of
   `signals.py suspects src/reports/exportReport.ts` on fixture 08 ranks `monthRange.ts`
   first. `signals.py hotspots --diff HEAD~1` on fixture 10 ranks `promo.ts` and
   `calendar.ts` first and second. What is left is whether the skill fires, which a probe
   judges.
7. **Four clarify fixtures have no repo-local git identity.** Cases 15, 17, 18 and 19 pass
   the identity with `git -c` only, so the blindspot pass of 0.34.1 runs in them. Cases 16
   and 76–78 set a local identity.
8. **The baseline does not describe the files on disk.** After the baseline run, 22 cases
   changed their fixture (the settings moved to `shipgate.json`), and case 16 replaced its
   LLM judge with a regex. The re-baseline fixes this.

## Projected cost of one re-baseline of the kept suite

Method: per case and arm, the newest measured run on that model. Without one, the
default-model baseline run stands for Opus, and Fable is Opus times 2.08 (time times 1.23).
The judge cost is included. Three runs per arm. Case 76 has no without arm yet; its
projection uses its with arm, which overstates it.

| Set | Cases | Opus | Fable |
| --- | --- | --- | --- |
| Kept suite: keep (both arms), guards (`none`), repaired (both arms) | 24 | 43.72 USD, 2.07 h serial, 0.69 h on 3 lanes | 87.77 USD, 2.53 h serial, 0.84 h on 3 lanes |
| Once, for #32: both arms | 17 | 30.76 USD, 1.40 h | 61.67 USD, 1.71 h |
| Once, for #32: Opus with arm only, Fable both arms | 17 | 18.60 USD | 61.67 USD |
| Trigger probes: 16 negatives and the firing of 08, 09 and 10, 3 runs | 19 | about 5.70 USD | about 11.90 USD |
| For comparison: all 78 cases, both arms | 78 | 135.93 USD | 275.33 USD |

- One re-baseline of the kept suite on both models costs 131.49 USD. The full suite costs
  411.26 USD, so the kept suite costs 68% less.
- The probe figure is not measured. It is the run-evals skill's figure of 0.10 USD a run,
  times 2.08 for Fable. No saved result holds a probe's cost. The first probe run records it.
- The deterministic checks cost 0 USD a run.

## Skills with no eval

`feature`, `workspace`, `model-tiers` and `setup` have no case. `implement` has two (71 and
73), both with a prompt that names the skill. After the verdicts, `implement` has 73 only, if
it is repaired.

| Skill | What a model run could judge | Recommendation |
| --- | --- | --- |
| feature | the phase it routes to, the scale of the ceremony, the executive contract | No case. `journal.py status` and `handoff` compute the routing, and unit tests pin them. Cases 16 and 55 judge the executive contract in clarify and design. The rest needs a second turn, which the harness cannot give. |
| workspace | a branch off a clean base, a confirm before the switch | No case. The git state is computed. The confirm needs a second turn or `AskUserQuestion`. |
| model-tiers | the model of each dispatched worker | No case now. #29 redesigns the dispatch and decides with the transcript data (686 dispatches in the harness audit). A `tu` grader on the Agent input could judge the model later. |
| setup | the interview and the files it writes | No case. The files are unit-tested (`test_settings.py`, `test_config.py`). The interview needs turns. |
| implement | the reuse step | Repair 73 (decision 5). Its fixture gives the helper away today, so its Δ of 0 says nothing about the step. |

## Harness findings and where each goes

| Finding | Where | Reason |
| --- | --- | --- |
| The harness has no script grader | fix inside #28 | Add a post-run script step beside the harness score, as `signal_grader.py` does (ADR 0016). It reads the saved answer or the kept trace. First users: 22's trace-order judge, 70's sentence length, 15's assumptions section. |
| A `tool_used` grader for Read misses a read with `cat` | accept | No current case grades Read. The same gap exists for edits: 29–33, 35, 37, 57, 60, 61 and 64 count Edit only, not Write or a shell edit. A claim about a file grades the file, with `rx` or `fe`. |
| An installed plugin shadows the tree under test (#49) | fix inside #28 | `run-case.sh` refuses to start when the paying config dir has a plugin of the same name installed, and `summarize.py` marks a run whose trace `init` record names another plugin path. Both are deterministic. |
| No `AskUserQuestion` and no second turn in an eval session (#49) | accept; ask upstream | The harness is not ours. Cases 16, 18, 53, 68 and 76 judge the text fallback. The two-turn driver stays the release check for the approval path. |
| A forgotten `--ablation none` doubles the cost | fix inside #28 | `run-case.sh` takes no default mode and records the mode it ran. `compare.py` refuses a compare across modes. |
| 15 test helpers start `journal.py` with the inherited environment | fix elsewhere | It is test hygiene, not an eval matter. One suite-wide guard in its own small issue, before the next hook change. |
| 2,302 of 2,553 saved runs record no model | fix inside #28 | `run-case.sh` always passes `--model`, and the baseline row records it. |
| The journal graders of 58–66 are date-bound, hook-only or always true (finding 2) | fix inside #28 | Repair them in the cases that stay, as the table says. |
| With-arm-only claims are scored in both arms (finding 3) | fix inside #28 | Mark them `arm: with-only`, so Δ stops counting the plugin's presence. |

## Decisions for the user

Each decision gives the recommendation first.

1. **The 17 cases at Δ 0 ("keep until #32").**
   Recommended: run them once at the re-baseline, Opus with arm only and Fable with both
   arms (80.27 USD). Then cut each case whose Δ is 0 on Fable too, together with the #32
   decision on its text.
   Other: both arms on both models (92.43 USD). Or cut them now on the October data (0 USD);
   #32 then has no Fable data, and #37's rule "no skill text is cut before an ablation on
   both session models" blocks it.
2. **The claim that a skill records its phase event.**
   Recommended: move it out of the evals. Prose tests pin the record steps, and the retro
   counts the events in real journals. Keep the repaired, with-only journal graders only in
   cases kept for another reason: 58 (the debug event) and 74 (`review-verdict`). The
   `route-and-map`, `clarify-passed` and `design-committed` events and 75's recorded
   ranking then have no eval check; the retro sees a lost step only after a release.
   Other: keep one with-arm guard case per phase skill, at 0.33 to 0.58 USD per run on the
   default model. This catches a lost record step before the release, not after it.
3. **The 16 negative cases.**
   Recommended: move them to trigger probes on both models. Extend `probe.sh` to count the
   named Bash and Agent calls, and to record the cost per run.
   Other: keep them as evals in the `none` mode. The without arm adds nothing to a negative
   case, because the bare model has no skill to fire.
4. **Case 77 judges the UI setting the agent reads, not the computed `ui` flag.**
   Recommended: make the computed flag reach the agent in a form that `head` cannot cut (its
   first line), pin that with a unit test, and keep the case for the ask itself.
   Other: accept that the case judges the setting.
5. **`implement` coverage.**
   Recommended: repair 73 (remove the two giveaways, and prove offline that a grep for
   retry, backoff or attempt finds nothing), and cut 71.
   Other: cut both; `implement` then has no eval.
6. **Case 78.**
   Recommended: skip it until #74 decides the batch rule. Today it cannot pass in any run.
7. **The 15 test helpers with the inherited environment.**
   Recommended: a separate small issue, outside #28.
   Other: fold the guard into #28.
8. **The three cuts (37, 64, 71) and the coverage they lose.**
   Recommended: cut them. 71 is the easier twin of 73. 37 and 64 are the only cases where a
   request contradicts a recorded ADR, but `knowledge-base` fired in 0 of 6 with runs and
   the bare model passes, so no plugin text earns the pass.
   Other: keep 37 until #32 (about 0.37 USD a run pair on the default model) to keep that
   behaviour under watch.

## Not measured

- The model of the 2,302 default-model runs. The note infers the Opus tier from cost.
- A without arm on Fable. The 2 without runs of case 77 on Fable are shadowed (addendum
  below).
- The cost of a trigger probe.
- Whether a stronger model passes where a weaker one passes. On the with arm, Fable passed
  at least as often as Opus in 14 of 15 cases. No bare run on either model is measured: the
  without arm of case 77 is shadowed (addendum below).

## What this note decides

Nothing. The lead relays the decisions above to the user. Clarify and Design of #28 (the
baseline row, `compare.py`, the #49 fixes, the re-baseline plan) start from the answers.

## Addendum, 2026-11-26: the without arm of case 77 is shadowed

The two paid runs of case 77 on 2026-11-25 (`with-without`, one on Opus, one on Fable) kept
their traces. The init record of every without run lists the plugin `shipgate` 0.36.0: 3 of
3 runs on Opus, 2 of 2 on Fable. It is the installed copy from the local marketplace, and
that copy's path is the checkout under test. So the plugin loaded in the arm that should run
bare (#49), and those runs measure no bare model. `evalrun.py post-run` now marks both
results dirs shadowed (`shadow.json`), and `compare.py` refuses them. The
corrections above remove the without counts and costs of case 77, and the claim that the
bare Fable did worse than the bare Opus. The ratio of 2.03 between the Fable and the Opus
without-arm cost of case 77 is not a bare-arm ratio either. The plan's Fable projection uses
the with-arm ratio of 2.08, which these runs do not touch.

## Addendum, 2026-11-27: the re-baseline numbers for #32

The re-baseline of #28 ran every kept and guard case on both models and the `ablation-32`
set on Fable (harness 2.1.332, judge sonnet, 3 runs per arm). A score is the mean of the
both-arm score over the runs (`compare.py`). Δ is the with arm (`--ablation none`) minus the
bare arm (`--bare`). A lift is Δ above +0.10, the 0.10 that `compare.py` uses as its noise
threshold. The `ablation-32` set on Opus did not run: it rests on the October rows (decision
D1).

**Fable.**

- Bare 1.00, so the plugin has no lift to show. Cut together with #32's decision on the
  skill text: 17, 25, 29 (after the 1b rule), 30, 31, 32, 33, 36, 39, 40, 54, 69, 74 (the
  rerun scored 1.00 in 3 of 3; the first batch fell on a grading artifact). Also at bare
  1.00 in the kept set, to read at #32: 45 (with 0.87, Δ −0.13), 46 (with 0.56, Δ −0.44),
  73 (with 1.00, Δ 0.00).
- A lift, keep: 02 (+0.33), 03 (+0.38), 04 (+0.44), 05 (+0.67), 15 (+0.50), 16 (+0.60),
  18 (+0.38), 19 (+0.13), 23 (+0.22), 43 (+0.17), 51 (+0.43), 53 (+0.17), 76 (+0.46),
  77 (+0.78).
- No clear lift or negative, to read at #32: 22 (−0.27), 24 (+0.07), 26 (−0.10), 38 (0.00),
  47 (+0.05), 55 (−0.11), 58 (0.00), 68 (+0.07), 70 (+0.02).

**Opus** (the kept set).

- Bare 1.00: 22 (with 0.87, Δ −0.13), 46 (Δ 0.00), 58 (with 0.93, Δ −0.07), 73 (Δ 0.00).
- A lift, keep: 02 (+0.44), 03 (+0.57), 04 (+0.44), 05 (+0.44), 15 (+0.42), 16 (+0.27),
  18 (+0.33), 19 (+0.25), 23 (+0.17), 38 (+0.25), 51 (+0.36), 68 (+0.26), 70 (+0.16),
  76 (+0.39), 77 (+1.00).
- No clear lift or negative: 26 (+0.10), 43 (−0.17), 45 (+0.07).

**Both models.** The guards 48 and 52 scored 1.00 in 3 of 3 runs. The negative Δ of 46 on
Fable comes from two runs that failed `no-invented-findings` and `not-not-ready`, and of 22
on Fable from `status-matches-evidence` in all three runs: these are the first texts to
read at #32.

**Probes.** All 19 probes ran 3 times on each model. By the counts of each stream (the
turn-cap rule of T061), each probe matched its expectation in 3 of 3 runs on both models.
A side fire: probe 56 ("already designed", `design` must not fire) fired
`shipgate:implement` in 1 Opus run and in 3 Fable runs. The probe does not check
`implement`, so this is information for #32 and for the trigger work, not a failure.
