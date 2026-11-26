---
type: adr
title: "0034. A baseline row is per case and model, and names its mode and scoring rule"
created: 2026-11-25
updated: 2026-11-25
tags:
  - adr
  - shipgate
  - evals
status: accepted
date: 2026-11-25
issue: "#28 (shipgate), with #49; child of #37"
related:
  - "../prd/eval-measurement.md"
  - "../research/2026-11-25-eval-suite-audit.md"
  - "./0016-the-signal-grader-runs-outside-the-harness.md"
---

# 0034. A baseline row is per case and model, and names its mode and scoring rule

> `baseline.json` keys each row by case and then by model. A row records the ablation mode,
> the scoring rule, the tested plugin version, and the cost and time per arm. Compare never
> crosses a model, a mode or a rule. It scores a pair of separate runs under the both-arm
> rule.

Executive decision (the `autonomy` setting is `executive`). The user can veto it.

## Context

- The rows today hold scores only. 2,302 of 2,553 saved runs record no model, so a score
  cannot be tied to a model (audit, 2026-11-25).
- The epic's definition of done asks for a row per session model, with cost and time (#37).
- The same grader results score 0.87 under `--ablation none` and 0.78 under `with-without`
  on case 77, because `none` scores the `skill-fired` grader (#28, second comment).
- D1 of the user (2026-11-25) runs the bare arm and the with arm of the #32 set as two
  separate runs. The harness computes Δ only inside one `with-without` run.
- `--record` stamps the version of the tree at record time, not the version the run tested.

## Decision

- `baseline.json` holds `cases: {<case>: {<model>: <row>}}`. The model key is the
  harness's `--model` value. Rows written before this change move under the key
  `unrecorded`, unchanged, and keep `mode: with-without`.
- A row records: `model`, `mode` (`with-without`, `none` or `bare`), `rule` (`both-arm` or
  `all`), `version` (from the result's `suite.plugins`), `claude`, `judge`, `runs`,
  `results`, `with`, `without`, `delta`, `cost` and `seconds` per arm (mean per run, judge
  excluded), and `judge_cost` (mean per run).
- The **both-arm rule** scores a run over the graders that score in both arms of
  `with-without`: it leaves out a grader with `arm: with-only`, and a `tool_used` grader
  for `Skill` whose config has no `arm: both`. (Corrected during the build: the first text
  said "with no `min` or `max`"; the saved results show the harness's rule as stated
  here.) A `with-without` result is already scored by this
  rule. Compare recomputes it from the per-run grader results for a `none` or `bare` run.
- Compare refuses a compare across models, modes or rules. It refuses `--record` for a run
  with no model and for a shadowed run (ADR 0036).
- Compare pairs a `bare` result and a `none` result of one case and one model into one row,
  both under the both-arm rule, with `mode: bare+none`.
- Compare flags an efficiency regression: the with-arm cost above 1.5 times the bare-arm
  cost per run, at |Δ| within the noise floor of 0.10.

## Alternatives considered

- **Flat rows with a `model` field** (`rows: [{case, model, …}]`). It is as expressive,
  but every lookup scans, and a duplicate pair of case and model is possible. The nested
  form makes the pair a key.
- **Separate baseline files per model.** It doubles the files that compare reads and that
  tests pin, and it hides the drift between models of one case. Rejected.
- **Compare raw scores across modes, with a warning.** The 0.87 against 0.78 on case 77
  shows that the raw scores differ on the same answers. A warning gets read as noise.
- **Run stage 2 as a full `with-without` run.** Δ then comes from the harness, but the bare
  arm runs twice. D1 of the user rules that out: the with arm runs alone.

## Consequences

- Every reader of `baseline.json` changes: `compare.py`, `test_compare.py`, and the evals
  README. One migration moves the 75 rows under `unrecorded`.
- A score now carries its rule, so a later harness change in what counts is visible.
- The October rows stay as the Opus-tier reference of the #32 set (D1). They never claim a
  model.
- `compare.py` reads the case's grader configs from the result file to apply the rule. A
  harness change to that config shape breaks the recompute; a unit test pins the shape.
