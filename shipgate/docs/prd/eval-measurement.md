---
type: prd
title: "PRD: Evals measure only what a decision needs, per model, with cost and time"
created: 2026-11-25
updated: 2026-11-25
tags:
  - prd
  - shipgate
  - evals
  - executive
status: clarified
issue: "#28 (shipgate), with #49 folded in; child of #37"
worklog: "./eval-measurement.worklog.md"
related:
  - "../research/2026-11-25-eval-suite-audit.md"
  - "../research/2026-11-15-agent-harness-audit.md"
  - "../adr/0016-the-signal-grader-runs-outside-the-harness.md"
---

# PRD: Evals measure only what a decision needs, per model, with cost and time

> The eval suite keeps only the cases whose score changes a decision. Every score records
> the model, the ablation mode, the cost and the time. Deterministic checks take over what
> they can judge. The re-baseline spends money only on a plan that the user approved.

## Terms

- **Arm**: one side of a case run. The **with arm** loads the plugin. The **bare arm** (the
  harness calls it "without") loads no plugin.
- **Ablation mode**: the harness's `--ablation` value, `with-without` or `none`.
- **Scoring rule**: which graders count in a score. Under `with-without`, the harness leaves
  the with-only graders (the `tool_used: Skill` grader among them) out of the score. Under
  `none`, it counts them. The **both-arm rule** counts only the graders that score in both
  arms of `with-without`.
- **Δ**: the with-arm score minus the bare-arm score, under one scoring rule.
- **Kept suite**: the 24 cases of the audit that run at every re-baseline (17 keep, 2 guards,
  5 repaired).
- **#32 set**: the 17 cases of the audit marked "keep until #32".
- **Probe set**: the 16 negative cases, and the firing of the natural prompts of 08, 09 and 10.
- **Shadowed run**: a run in which the plugin that loaded is not the tree under test (#49).
- **Efficiency regression**: the with arm costs more than 1.5 times the bare arm per run,
  while |Δ| is within the noise floor of 0.10.
- **Moved claim**: a grader claim that a deterministic check takes over. The case or grader
  goes; the named test stays.

## Problem

The suite has 78 cases. A full run on both session models costs about 411 USD. The audit of
2026-11-25 found:

- 28 of 59 positive cases show no lift. The bare model passes them.
- Nothing records the model: 2,302 of 2,553 saved runs have none.
- The baseline holds scores only, mostly from plugin 0.15.0.
- The journal graders of the large cases are broken: two match October 2026 dates only, and
  two pass in both arms by construction.
- With-arm-only claims inflate Δ: case 75's whole +0.60 comes from journal graders that the
  bare arm cannot pass.
- An installed plugin can shadow the tree under test, and nothing stops such a run (#49).
- A forgotten `--ablation none` once doubled a run's cost.

So the suite spends money on cases that decide nothing, and a score cannot be tied to a
model or a cost. #32 (the skill diet) needs per-model data before it may cut skill text.

## Goals & non-goals

**Goals**
- Every score carries its model, its mode, its scoring rule, and its cost and time per arm.
- The suite holds only cases whose fall changes a named decision (D1 to D4 of the audit).
- Each claim that a deterministic check can judge moves to that check.
- A run that would measure the wrong plugin, the wrong mode or no model does not start.
- The re-baseline spends only on a plan with a measured cost per case and model, after the
  user's go.

**Non-goals**
- No change to the harness (`claude plugin eval`) itself. `AskUserQuestion` and a second
  turn in an eval session stay outside (accepted in the audit).
- No skill text is cut. #32 decides that with the data this issue produces.
- The 15 test helpers that start `journal.py` with the inherited environment: a separate
  issue, filed by the lead.
- No retro tooling. The count of phase events in real journals belongs to the retro (#35
  or the epic's retro).
- No new case for `feature`, `workspace`, `model-tiers` or `setup`.
- Case 78 is not redefined. #74 decides its batch rule first.

## Users & stories

- As the maintainer, I want each baseline row to name its model and cost, so that I can tell
  a model change from a plugin change and see what a skill costs.
- As the maintainer, I want a run that would load the installed plugin to refuse to start,
  so that I never pay for a score of the wrong tree.
- As the maintainer, I want compare to flag a case that costs more for no lift, so that #32
  has its list.
- As the user who pays, I want to approve a plan with a cost per case and model before any
  run, so that the suite never spends on what no decision needs.

## Functional requirements

### Baseline row and compare

- **FR-001** — A baseline row belongs to one case and one session model. It records the
  model, the ablation mode, the scoring rule, the plugin version the run tested, the harness
  version, the judge model, the runs per arm, the results directory, the score per arm, Δ,
  the mean cost and the mean time of one run per arm, and the judge cost.
- **FR-002** — A row written before this change keeps its values and states that its model
  was not recorded. It never names a model it did not record.
- **FR-003** — The recorded plugin version is the version that the run tested, taken from the
  result, not the version of the tree at record time.
- **FR-004** — Compare refuses to compare a result with a baseline row of another model,
  another ablation mode or another scoring rule. The refusal names both sides.
- **FR-005** — Compare flags an efficiency regression per case.
- **FR-006** — Compare and record refuse a shadowed run and a run with no recorded model.
- **FR-007** — Compare can score a case under the both-arm rule from the per-run grader
  results. Then a bare-arm run and a with-arm run of one case on one model compare under one
  rule, also when they come from two runs. Each such score names its rule.

### Run script

- **FR-008** — The run script has no default ablation mode. A call without an explicit mode
  does not start. The results record the mode that ran.
- **FR-009** — The run script requires a model and passes it to the harness.
- **FR-010** — The run script refuses to start when the paying config dir has a plugin of
  the same name installed or enabled. The message names the install and the fix.
- **FR-011** — After a run, the run script checks which plugin loaded in each run, by path
  and version. A run whose loaded plugin is not the tree under test is marked shadowed in
  the results directory. Summarize and compare read the mark.
- **FR-012** — The run script can run the bare arm alone for a set of cases, with the same
  scaffold, graders and judge as the harness's without arm. The results record it as the
  bare arm.
- **FR-013** — The run script runs a named set of cases (the kept suite, the guards, the #32
  set) in one call, and the harness runs nothing outside that set.

### Script graders

- **FR-014** — A case can carry script graders. After a run, a script grader reads each
  run's final answer or kept trace and records pass or fail per run. Its result sits beside
  the harness score, never inside it (as for the signal grader, ADR 0016).
- **FR-015** — Compare shows the script-grader pass rate per arm and flags a fall against
  the baseline row.

### Trigger probe

- **FR-016** — The trigger probe counts, per run: the skills that fired, the Bash calls that
  match a named pattern, and the Agent, Edit and Write calls (Edit and Write optionally on a
  path pattern). It records the model, the turns, the cost and the time per run.
- **FR-017** — Each probe case states its expectation in a file that the probe reads: the
  skill that must or must not fire, and the counts that must be 0. The probe prints pass or
  fail per run and saves its results like eval results.
- **FR-018** — The probe takes a model and runs on both session models.

### Suite changes

- **FR-019** — The suite matches the audit's verdict table as the user decided it (D1 to D8):
  - a cut case is deleted;
  - a merged case is deleted after the claims that its row names move into the target;
  - a moved case leaves the eval set after the named check exists and passes;
  - a repaired case gets the repair that its row names.
- **FR-020** — Each moved claim names the test that takes it over:

  | Case | Moved claim | Test that takes it over |
  | --- | --- | --- |
  | 08, 12 | the suspect ranking puts `monthRange.ts` first | a new fixture test of `signals.py suspects` on fixture 08 |
  | 10, 14 | the hotspots ranking puts `promo.ts` and `calendar.ts` first | a new fixture test of `signals.py hotspots --diff` on fixture 10 |
  | 09, 13 | the blast radius of the change at HEAD | `test_signal_grader.py` (`TestFixture.test_case_13_regex_arm`, exists) |
  | 72 | the blast radius in the large workspace | a new unit test of `signal_grader.py fixture 72 --arm graph`, skipped without codegraph |
  | 75 | the graph ranking reaches the review verdict | the `signals.py` ranking tests (exist) and a new prose test of review's record step |
  | 08, 09, 10 | the skill fires on the natural prompt | the probe set |
  | 16 negatives | the skill does not fire; the named calls are 0 | the probe set |
  | 76 | the batch holds at most 4 items | `test_journal_assumptions.py` (`test_the_cap_is_four`, exists) |
  | 15 | the executive section is present, with answers and reasons, and non-goals exist | a regex grader, tested in `test_eval_graders.py` |
  | 22 | the last test run comes after the last edit | a script grader over the trace |
  | 70 | sentences are short; code is in code form | a script grader and a regex grader |
  | 59–66 | the skill records its phase event | new prose tests of the record steps (D2) |

- **FR-021** — Journal graders (D2): 58 keeps one phase-event grader, date-free and with-only,
  and drops `journal-any-event-appended` and `journal-no-invented-types`. 74 marks
  `journal-verdict-appended` with-only. No other case keeps a journal grader.
- **FR-022** — Prose tests pin the record step of each phase skill that loses its journal
  grader: clarify (`clarify-passed`), design (`design-committed`), review (`review-verdict`
  with its `ranking`) and route-and-map (exists).
- **FR-023** — No eval fixture holds an absolute date that can expire. A date that a model
  reads as a deadline is computed at scaffold time, 30 days ahead, as case 46 does. A unit
  test fails on a literal deadline date in a fixture.
- **FR-024** — The fixtures of 15, 17, 18 and 19 set a repo-local git identity. A unit test
  checks it for every clarify case.
- **FR-025** — `signals.py hotspots` shows the computed UI flag in the first lines of its
  output, in the JSON and the table form, so that an agent that reads only the head sees it.
  A unit test pins it. The shipgate version goes up in `plugin.json` and `marketplace.json`.
- **FR-026** — Case 73's fixture gives the helper away nowhere: no commit subject, comment or
  caller names the retry idea. The fixture asserts this over the file text and the commit
  subjects. A unit test scaffolds it offline and checks it.
- **FR-027** — Case 76's `batch-items-risky` becomes one grader per claim, without the claim
  "at most 4 items".
- **FR-028** — Case 78 stays on disk and stays out of every run set until #74 decides.
- **FR-029** — The evals README and the run-evals skill describe the sets, the modes, the
  bare arm, the shadow guard, the script graders and the probe. They replace the cost rule of
  thumb with the measured cost table.

### Re-baseline plan and spend

- **FR-030** — Before any spend, a plan names per case: its set, the decision a fall changes,
  the arms and the mode per model, the runs, and the cost per model (measured, or projected
  and marked so). The user's go on that plan is recorded before the first run.
- **FR-031** — The plan runs in stages:
  1. the #32 set's bare arm on Fable, 3 runs;
  2. the with arm on Fable, 3 runs, only for the #32-set cases whose bare arm falls;
  3. the kept suite on Opus and on Fable: both arms, and the with arm only for the guards;
  4. the probe set on Opus and on Fable, 3 runs.
  Opus rests on the October rows for the #32 set. Case 78 does not run.
- **FR-032** — A #32-set case whose bare arm scores 1.00 has no lift to show. Its result goes
  into the baseline and into a note for #32. #32 deletes the case together with its decision
  on the skill text.
- **FR-033** — Each stage runs with a cost ceiling at its projected cost plus 25%.

## Success criteria

- **SC-001** — Every baseline row that the re-baseline writes names its model, mode, scoring
  rule, tested version, and cost and time per arm.
- **SC-002** — Compare exits non-zero and names both sides for a compare across models,
  modes or scoring rules. A unit test pins each of the three.
- **SC-003** — Compare flags a case with a cost ratio of 1.6 and |Δ| of 0.05. It flags no
  case with a ratio of 1.4, and none with |Δ| of 0.20. A unit test pins all three.
- **SC-004** — The run script exits non-zero before any spend in each of these cases: no
  mode, no model, or a same-name plugin in the paying config dir. A test runs it with a stub
  `claude` on `PATH` and a fake config dir.
- **SC-005** — A results directory whose kept trace shows another plugin path is marked
  shadowed, and record refuses it. A unit test uses a canned trace.
- **SC-006** — The probe's counts match a canned stream for each named tool, and the saved
  result holds the cost per run. A unit test pins it.
- **SC-007** — The harness's case list holds exactly 42 cases: 17 keep, 2 guards, 17 in the
  #32 set, 5 repaired, and 78.
- **SC-008** — Every test that FR-020 names exists and passes in
  `python3 -m unittest discover -s shipgate/tests`.
- **SC-009** — No fixture holds a literal deadline date. A unit test pins it.
- **SC-010** — The `hotspots` JSON and table outputs show the UI flag in their first 3 lines
  when `ui.globs` is set. A unit test pins it.
- **SC-011** — The worklog holds the re-baseline plan with a cost per case and model. The
  journal records the user's go before the first run.
- **SC-012** — After the re-baseline, `baseline.json` holds an Opus row and a Fable row for
  each case of the kept suite (#37's definition of done).
- **SC-013** — No stage spends more than its projected cost plus 25%.

## Constraints & assumptions

- Scripts stay Python 3.9 compatible. Tests run with
  `python3 -m unittest discover -s shipgate/tests`. A test that starts `journal.py` gives it
  a temporary `CLAUDE_CONFIG_DIR` (root `CLAUDE.md`).
- The repo is public. Results directories stay ignored. Measurements from them go in as
  counts and costs only (root `CLAUDE.md`).
- This session runs no eval, no probe and no nested `claude` session. The first spend needs
  the user's go on the plan (the lead's message of 2026-11-25, rule 1).
- The harness has no bare-only mode: `--ablation` takes `none` or `with-without` (the
  harness's `--help`). FR-012 needs another way to run the bare arm alone.
- In `none` mode, the harness scores the `skill-fired` grader. In `with-without` it does not.
  The same grader results gave 0.87 and 0.78 on case 77 (#28, second comment).
- The projected stage-1 cost is 24.83 USD: the default-model bare cost of each of the 17
  cases times 2.08, the median Fable-to-Opus cost ratio of 15 measured cases. No bare-arm
  ratio is measured: the without arm of case 77 loaded the installed plugin (shadowed; the
  audit note's addendum of 2026-11-26).

## Assumptions (executive)

- [domain] [no source found in #28, its comments, #49, the audit note or the lead's message] When a bare score is below 1.00 because one grader failed in one run of three, what happens? → run the bare arm of that case 3 more times; it counts as 1.00 only when that grader passes in all 3 new runs, and any other shortfall is a fall — one run in three is within noise, and 3 more bare runs cost about two thirds of the 3 with-arm runs that a fall would buy [kept by the user]
- [behaviour] [no source found in #49, the run-evals skill or the evals README] When the paying config dir has the plugin installed, does the run script refuse or work around it? → it refuses and names the install and the fix (a config dir without the plugin); it never edits a config dir — the script must not change the user's Claude setup, and a copied config dir may not authenticate [kept by the user]
- [domain] [no source found in the run-evals skill or the probe script] When does a trigger probe pass? → when all 3 runs match the expectation; one miss in three is a finding to read before the description changes — the graders it replaces demanded 3 of 3 [kept by the user]
- [data] [source: #37, Definition of done] Is a baseline row per case, or per case and model? → per case and model — the definition of done asks for a row per session model
- [data] [source: the lead's message of 2026-11-25, D1] What happens to the rows written before this change? → they stay, with the model "not recorded"; for the #32 set they are the Opus-tier reference; the re-baseline replaces them for the kept suite; a deleted case loses its row — Opus rests on the October rows
- [behaviour] [source: #28, the proposal] When does compare flag an efficiency regression? → a with-arm cost above 1.5 times the bare-arm cost per run, at |Δ| within the noise floor of 0.10 — the issue states the ratio; the floor is compare's existing one
- [domain] [source: #28, second comment] How does a score from a `none` run compare with a `with-without` one? → never as raw scores; a Δ across two runs uses the both-arm rule and names it — the raw scores differ by mode on the same grader results
- [domain] [source: the lead's message of 2026-11-25, D1] Does stage 2 repeat the bare arm? → no; the with arm runs alone on the fallen cases, and Δ uses the both-arm rule
- [behaviour] [source: the lead's message of 2026-11-25, D4 and rule 5] Where does the computed UI flag go, and does that bump the version? → into the first lines of the `hotspots` output, unit-tested, with a shipgate version bump — a changed script output is a behaviour change
- [technical] [source: ADR 0016] Does a script grader's result enter the harness score? → no; it sits beside the score, and compare shows it and flags its fall — the signal grader set that pattern
- [technical] [source: the lead's message of 2026-11-25, D2] Does #28 build the count of phase events over real journals? → no; #28 adds the prose tests, and the count belongs to the retro — D2 names both, and the retro is its own work
- [technical] [source: the lead's message of 2026-11-25, rule 3; case 46's fixture] How does a fixture hold a deadline date? → computed at scaffold time, 30 days ahead — case 46 met the expired date on 2026-10-06
- [technical] [source: the lead's message of 2026-11-25, D1] Who deletes a #32-set case that scores 1.00 bare? → #32, together with its decision on the text; #28 records the result and a note — "cut with its #32 decision"
