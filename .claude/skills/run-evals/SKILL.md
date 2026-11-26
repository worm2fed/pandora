---
name: run-evals
description: Use whenever asked to run, re-run, summarize, compare or debug the plugin evals / `claude plugin eval` in this marketplace, run the bare arm alone, check whether a skill triggers on a case (trigger probe), or when an eval run errors, scores 0.00, refuses to start (no mode, no model, a same-name installed plugin, git shim, credential-store symlink, weekly limit) or bills the wrong account. Encodes the working commands, this machine's workarounds and the cost plan.
---

# Run the plugin evals

Every plugin's cases live in `<plugin>/evals/NN-*/`. How a case is written (prompt.md,
graders, `fixture.sh` scaffold, the three case forms) is in
[shipgate/evals/README.md](../../../shipgate/evals/README.md). This skill is about
*running* them on this machine. Scripts live in `scripts/` next to this file; paths below
are relative to the repo root.

## Two tools, two questions

| question | tool | cost |
|---|---|---|
| Does the skill fire on this prompt, and do the named calls stay at 0? | `scripts/probe.sh`: plain `claude -p --plugin-dir`, judged by `shipgate/evals/probe.py` against the case's `probe.json` | about $0.10 per run (not yet measured per model) |
| Is the answer better with the plugin? (the gate) | `scripts/run-case.sh`: `claude plugin eval` with graders | see **Cost** |

The probe measures triggering only, never answer quality. Ship on harness numbers.
In the probe's session (`claude -p --plugin-dir <plugin> --setting-sources "" --strict-mcp-config`)
the plugin's skill descriptions (`<plugin>:<skill>` + description, capped at 1,536 chars) are the
whole triggering surface (no README, no hooks output), so a description is all there is to tune.

## Commands

Every run names its mode and its model. There is no default: a call without them does not
start (exit 64), and nothing is spent.

```bash
S=.claude/skills/run-evals/scripts
$S/run-case.sh --ablation with-without --model claude-opus-5-5 shipgate 05   # both arms
$S/run-case.sh --ablation none --model claude-fable-5-2 shipgate 48          # with arm only
$S/run-case.sh --bare --model claude-fable-5-2 shipgate 24                   # bare arm only (ADR 0035)
$S/run-case.sh --ablation none --model M shipgate 02 --runs 1 -j 3 --max-cost-usd 2   # extras pass through
$S/probe.sh --model claude-opus-5-5 shipgate 11        # one probe case, 3 runs
$S/probe.sh --model claude-opus-5-5 shipgate probes    # the probes set
python3 $S/summarize.py shipgate/evals/results/<timestamp>          # or the results/ root
python3 shipgate/evals/compare.py shipgate/evals/results/<timestamp>  # against baseline.json
```

The options (`--config-dir`, `--no-codegraph`, the mode and `--model`) go before
`<plugin-dir>`. `run-case.sh` refuses a mode or model flag among the extra eval flags.

`run-case.sh` runs:

```
claude plugin eval <plugin-dir | bare stub> --runs 3 --ablation <with-without|none> --scaffold \
  --judge-model sonnet --no-publish --allow-tools Bash Edit Write --model <M> --keep-temp \
  --case 'NN-*' [extra flags]       # or --case <full case dir name>
```

- **Modes.** `with-without` runs both arms; Δ comes from the harness. `none` runs the with
  arm only. `--bare` runs the bare arm only: it builds a stub plugin `<name>-bare` with no
  component and an `evals` link to the real evals dir, runs it under `none`, and writes
  `bare.json` into the results dir. `compare.py` pairs a `bare` and a `none` result of one
  case and model into one `bare+none` row.
- **Before the run** it calls `shipgate/evals/evalrun.py config-check`: a plugin of the
  same name installed (any scope) or enabled in the paying config dir stops the run (exit 1).
  The message names the install and the fix. The check never changes the config dir.
- **After the run** it calls `evalrun.py post-run`: `shadow.json` (which plugin loaded in
  each run, from the trace's init record), `script-graders.json` (when a case has
  `script-graders/*.py`), then it removes the kept sandboxes. Pass `--keep-temp` yourself
  to keep them. The signal grader runs before the clean-up.
- `--scaffold` is mandatory: without it every case scores 0 in both arms.
- `--judge-model sonnet`: the default haiku judge mis-grades ranked answers.
- `--case` accepts only `NN-*` globs (no braces or brackets), so it is one invocation per
  case. `run-case.sh` also takes the full name of an eval case (a dir that holds
  `prompt.md` or `case.yaml`) in place of `NN`; then the filter is that name alone. It
  refuses any other dir under `evals/` (a probe or fixture case, `results`) with exit 64.
  A serial set runner comes in a later PR; until then run one `run-case.sh` per case.
- Exit 1 is normal: the default `--threshold` is 1.0. Exit 2 means `--max-cost-usd` was hit.

`probe.sh` needs `--model`, runs `config-check` too, and checks every `probe.json`
(`probe.py check`) before it spends. A probe case holds `probe.md` (the prompt) and
`probe.json`; a case with only `prompt.md` runs count-only. A probe passes when all its
runs pass (3 of 3). One miss is a finding to read before the description changes. Results
go to `shipgate/evals/results/probes/<stamp>/<case>.json` with model, turns, cost and time
per run.

## Machine gotchas (checklist, in the order they bite)

1. **git shim.** The agent sandbox blocks `/usr/bin/git` (Xcode shim → xcrun cache).
   `which -a git` must list `/opt/homebrew/bin/git` first; the scripts refuse otherwise.
2. **Credential-store symlinks.** The harness refuses Bash-granting runs while a store
   under `$HOME` (`~/.docker`, `~/.aws`, …) contains a symlink; Docker Desktop puts them
   in `~/.docker/bin` and `~/.docker/cli-plugins`. The error names `DOCKER_CONFIG`, but
   setting it does not help and there is no flag. Workaround (built into the scripts): run
   under an empty scratch `HOME` with `CLAUDE_CONFIG_DIR` pointing at the real config dir.
   This authenticates normally; no `claude setup-token` needed.
3. **Which account pays.** With more than one Claude account configured on the machine, the
   shell profile may map `CLAUDE_CONFIG_DIR` to one whose weekly limit is exhausted. The
   symptom is the child `claude` printing `You've hit your weekly limit · resets <time>`
   and a run with cost 0. Bill evals to the account that should pay: pass
   `--config-dir DIR` or set `EVAL_CONFIG_DIR` in your shell profile; without either, the
   scripts fall back to `$CLAUDE_CONFIG_DIR`, then `~/.claude`. No account path is written
   down in this repo (public).
4. **Nested claude.** Inside a Claude Code session, launch the child with
   `env -u CLAUDECODE` (the scripts do).
5. **zsh.** The Bash tool's shell is zsh: never start an unquoted word with `=`
   (`echo ===` fails with "== not found").
6. **An installed plugin shadows the one under test (#49) — now a guard.** When the paying
   config dir has a plugin of the same name (`shipgate@<marketplace>`), both arms and a
   `claude --plugin-dir` session load that copy, not the tree under test; in one run the
   without arm loaded it too. `config-check` refuses such a config dir before any spend,
   and `post-run` marks a run whose init record shows another copy as shadowed in
   `shadow.json`; `compare.py` refuses a shadowed results dir. Use a config dir without the
   plugin. Eval sessions also have no `AskUserQuestion` tool, so a flow that asks the user
   cannot be judged in the harness; `shipgate/evals/two-turn/` drives one interactive
   session instead, after the merge, against the installed copy.

## Reading results

Results land in `<plugin>/evals/results/<timestamp>/aggregate-result.json` + `report.html`
(gitignored), with the sidecar files `shadow.json`, `bare.json` (bare runs) and
`script-graders.json`. JSON: `suite` (`ablation`, `modelOverride` = the model,
`plugins[0].version` = the tested version, `judgeModel`), `cases[]` → `name`, `graders[]`,
`arms.with[]` / `arms.without[]` (per run: `score`, `passed`, `turns`, `costUsd` (agent
only), `judgeCostUsd`, `durationSeconds`, `tracePath`, `error`, `graders[]`) and
`aggregates`. A grader is with-only when its config says `arm: with-only`, or when it is a
`tool_used: Skill` grader without `arm: both`; under `with-without` the harness leaves it
out of the score, under `none` it counts it.

- `summarize.py` prints the model, the mode, and per case: the harness score per arm, Δ,
  per-run turns, `skill-fired k/n`, the mean cost and time per run per arm, the judge
  cost, the shadow mark and the script-grader pass rates.
- `compare.py` prints one row per case and model against `baseline.json` (ADR 0034): the
  scores under the both-arm rule, ΔΔ (◀ above 0.10), `~` for a row from another harness
  or judge, and `$` for an efficiency regression (with arm above 1.5 times the bare arm's
  cost per run at |Δ| ≤ 0.10). It refuses (exit 3) a compare across models (`--against`),
  modes or rules, a result with no recorded model, and a shadowed run. A results dir with
  no `shadow.json` gets a warning, and `--record` refuses it. A dir with no `shadow.json`
  or a shadowed run only counts in one "skipped N older results dirs" line when compare
  uses a newer result of the same case and model. A dir with no recorded model counts
  only in that line when it is older than the newest pick of its case, any model; else
  compare refuses it. A run with no trace to check gives a warning only when compare uses
  its dir. `--record` writes the rows that are not refused, with the version the run
  tested. It skips every case and model that has a refusal in the run, so a refused
  partner never turns a `bare+none` row into a half row.

When the case holds an `expected.json`, `run-case.sh` then runs
`shipgate/evals/signal_grader.py results <dir>`: one row per run with the precision and
recall of the `signals.py` blast result the agent read. The grader's exit status never
changes the script's. Since #28 no eval case has one: 13 and 72 are fixture cases, scored
offline by `signal_grader.py fixture`. See the evals README, "Signal grader".

## Cost

Measured costs, 3 runs per arm, judge included (audit of 2026-11-25): a Fable run costs
about 2.08 times an Opus run of the same case (median of 15 cases, with arm). No bare-arm
ratio is measured yet: the without arm of the case-77 runs was shadowed. Until the
re-baseline (PR 3 of #28) measures every case per model, the cost per case and model is
the table of the re-baseline plan in
[shipgate/docs/prd/eval-measurement.worklog.md](../../../shipgate/docs/prd/eval-measurement.worklog.md):
the kept suite projects to 43.72 USD on Opus and 87.77 USD on Fable, the bare arm of the
#32 set to 24.83 USD on Fable. Probes are about $0.10 a run, not yet measured per model.
Set `--max-cost-usd` on every run.

## Running many cases

A serial set runner comes in a later PR; until then run one `run-case.sh` per case, by
its full case name, and keep each run's output in a log file. Two limits bite: the
account's 5-hour session limit (4 runs at once exhausted it twice in one afternoon; every
run after that returns `score 0.00 $0.00 error: You've hit your session limit`, exit 1; 3
at once fit a full pass in one window), and the weekly limit (gotcha 3).

Afterwards grep each run's log for `hit your session limit` before trusting its score,
and re-run those cases: `compare.py` takes the latest results dir per case and model, so
a clean re-run supersedes a limit-hit one.

## When a run scores 0.00

1. Cost near zero and 1–2 turns → the git shim (gotcha 1) or the weekly limit (gotcha 3).
   Read the run's trace or `report.html` final message before believing the score.
2. Both arms 0 on every case → `--scaffold` missing, or `fixture.sh` failed (run it by
   hand in an empty dir; it must create `app/`).
3. `error` set on the run → read it: the credential-store refusal (gotcha 2) aborts before
   the agent starts.
4. With arm fine, without arm 0 (or vice versa) with normal cost → a grader problem: check
   the grader's regex/rubric against the `evidence` field, and that the judge is sonnet.
5. Only `skill-fired` failing while outcome graders pass → triggering, not the skill body:
   iterate on the description with `probe.sh`, then re-run the harness.
6. A bare run's raw harness score is low → expected: `none` scores `skill-fired`, which
   fails without the plugin. `summarize.py` shows that raw score; read the both-arm score
   in `compare.py`.
