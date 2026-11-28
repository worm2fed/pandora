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
| Does the skill fire on this prompt, and do the named calls stay at 0? | `scripts/probe.sh`: plain `claude -p --plugin-dir`, judged by `shipgate/evals/probe.py` against the case's `probe.json` | about $0.15 a run on Opus, $0.30 on Fable (measured; see **Cost**) |
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
$S/run-set.sh --max-cost-usd 31 --bare --model claude-fable-5-2 shipgate ablation-32   # a set, one case at a time
$S/probe.sh --model claude-opus-5-5 shipgate 11        # one probe case, 3 runs
$S/probe.sh --model claude-opus-5-5 shipgate probes    # the probes set
python3 $S/summarize.py shipgate/evals/results/<timestamp>          # or the results/ root
python3 shipgate/evals/compare.py shipgate/evals/results/<timestamp>  # against baseline.json
```

The options of `run-case.sh` (`--config-dir`, `--no-codegraph`, the mode and `--model`) go
before `<plugin-dir>`. `run-case.sh` refuses a mode or model flag among the extra eval
flags, and `--output-dir` (exit 64), because it sets the results dir itself. The options
of `run-set.sh` are `--config-dir`, `--sets`, `--shard`, `--max-cost-usd`, the mode and
`--model`; it takes no `--no-codegraph`.

`run-case.sh` runs:

```
claude plugin eval <plugin-dir | bare stub> --runs 3 --ablation <with-without|none> --scaffold \
  --judge-model sonnet --no-publish --allow-tools Bash Edit Write --model <M> --keep-temp \
  --output-dir <plugin-dir>/evals/results/<stamp>-<pid> \
  --case 'NN-*' [extra flags]       # or --case <full case dir name>
```

- **Modes.** `with-without` runs both arms; Δ comes from the harness. `none` runs the with
  arm only. `--bare` runs the bare arm only: it builds a stub plugin `<name>-bare` with no
  component and a copy of the real evals dir, runs it under `none`, and writes
  `bare.json` into the results dir. `compare.py` pairs a `bare` and a `none` result of one
  case and model into one `bare+none` row.
- **Before the run** it calls `shipgate/evals/evalrun.py config-check`: a plugin of the
  same name installed (any scope) or enabled in the paying config dir stops the run (exit 1).
  So does an enable in the platform's managed settings (macOS
  `/Library/Application Support/ClaudeCode/managed-settings.json`, Linux and WSL
  `/etc/claude-code/managed-settings.json`, plus `managed-settings.d/*.json` beside it): a managed enable loads
  the plugin in every config dir, beside the bare stub too. The message names the install
  or the file and the fix. The check never changes the config dir or the managed file.
- **After the run** it calls `evalrun.py post-run`: `shadow.json` (which plugin loaded in
  each run, from the trace's init record), `script-graders.json` (when a case has
  `script-graders/*.py`), then it removes the kept sandboxes. Pass `--keep-temp` yourself
  to keep them. The signal grader runs before the clean-up. The results dir is the
  script's own: a new dir under `evals/results/` that it passes as `--output-dir`. A run
  that leaves no `aggregate-result.json` there has no result, and no post-run step runs;
  any kept sandboxes stay on disk at the paths the harness printed.
- `--scaffold` is mandatory: without it every case scores 0 in both arms.
- `--judge-model sonnet`: the default haiku judge mis-grades ranked answers.
- `--case` accepts only `NN-*` globs (no braces or brackets), so it is one invocation per
  case. `run-case.sh` also takes the full name of an eval case (a dir that holds
  `prompt.md` or `case.yaml`) in place of `NN`; then the filter is that name alone. It
  refuses any other dir under `evals/` (a probe or fixture case, `results`) with exit 64.
  `run-set.sh` runs the cases of a named set by their full names ("Running many cases").
- Exit 1 is normal: the default `--threshold` is 1.0. Exit 2 means `--max-cost-usd` was hit.

`probe.sh` needs `--model`, runs `config-check` too, and checks every `probe.json`
(`probe.py check`) before it spends. A probe case holds `probe.md` (the prompt) and
`probe.json`; a case with only `prompt.md` runs count-only. A probe passes when all its
runs pass (3 of 3); a run that stops on the turn cap is judged by its counts up to the
cap (`stopped: max_turns`), any other error fails it. One miss is a finding to read
before the description changes. Results
go to `shipgate/evals/results/probes/<stamp>/<case>.json` with model, turns, cost and time
per run.

## Machine gotchas (checklist, in the order they bite)

1. **git shim.** The agent sandbox blocks `/usr/bin/git` (Xcode shim → xcrun cache).
   `which -a git` must list `/opt/homebrew/bin/git` first; the scripts refuse otherwise.
2. **Credential-store symlinks.** The harness refuses Bash-granting runs while a store
   under `$HOME` (`~/.docker`, `~/.aws`, …) contains a symlink; Docker Desktop puts them
   in `~/.docker/bin` and `~/.docker/cli-plugins`. The error names `DOCKER_CONFIG`, but
   setting it does not help and there is no flag. Workaround (built into the scripts): run
   under a scratch `HOME` with no credential store, with `CLAUDE_CONFIG_DIR` pointing at
   the real config dir. On macOS the scratch `HOME` links `~/Library/Keychains` and
   `~/Library/Preferences/com.apple.security.plist` when they exist: an account whose
   login lives in the keychain is "Not logged in" without them. Nothing else is linked.
   No `claude setup-token` needed.
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
   without arm loaded it too. A plugin that the machine's managed settings enable loads
   the same way in every config dir. `config-check` refuses both before any spend, and
   `post-run` marks a run whose init record shows another copy as shadowed in
   `shadow.json`; `compare.py` refuses a shadowed results dir. For an install, use a
   config dir without the plugin. For a managed enable, a fresh config dir does not help:
   disable the plugin in the managed file for the length of the runs (admin rights).
   Eval sessions also have no `AskUserQuestion` tool, so a flow that asks the user
   cannot be judged in the harness; `shipgate/evals/two-turn/` drives one interactive
   session instead, after the merge, against the installed copy.

## Reading results

Results land in `<plugin>/evals/results/<timestamp>-<pid>/aggregate-result.json` +
`report.html` (gitignored), with the sidecar files `shadow.json`, `bare.json` (bare runs)
and `script-graders.json`. JSON: `suite` (`ablation`, `modelOverride` = the model,
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

Measured costs per case, model and arm (the re-baseline of #28, 2026-11-26 and 27,
harness 2.1.332) are the cost table of
[shipgate/evals/README.md](../../../shipgate/evals/README.md) ("Cost (measured ...)").
In sum, 3 runs per case, from the unrounded costs: the kept set's bare arm 14.70 USD on
Opus and 29.78 on Fable, its with arm 25.60 and 52.65, the guards' with arm 2.50 and
5.33, all 19 probes 8.51 and 17.50. A Fable run costs about 1.98 times an Opus run. About 0.70 USD of eval spend moves
the account's 5-hour window by one percent, so a full set on both models side by side can
fill it: count the window before you start a set.
Set `--max-cost-usd` on every run.

## Running many cases

`run-set.sh` runs the cases of a set from `sets.json` one after another, by their full
case names. It keeps the stdout of each case in a log dir that it prints. `--max-cost-usd
C` is required. Before each case the script sums the spend of the cases so far, and it
stops at C with exit 2. Each case gets what is left of C as its own `--max-cost-usd`, and
a case that hits it (exit 2) stops the set with exit 2. A case that leaves no results dir
stops the set with exit 1, because its spend is unknown. Ctrl-C stops the running case
with its `claude` child, and no further case starts.

To run a set faster, start shards side by side, one per terminal, each with its own
ceiling. Shard K/N runs the cases whose place in the set is K modulo N:

```bash
$S/run-set.sh --shard 1/3 --max-cost-usd 15 --ablation with-without --model M shipgate kept
$S/run-set.sh --shard 2/3 --max-cost-usd 15 --ablation with-without --model M shipgate kept
$S/run-set.sh --shard 3/3 --max-cost-usd 15 --ablation with-without --model M shipgate kept
```

Stop a shard with Ctrl-C in its terminal. A signal to the script's PID alone does not
reach the running case: send it to the process group (`kill -INT -<pgid>`).

Two limits bite: the account's 5-hour session limit (4 runs at once exhausted it twice in
one afternoon; every run after that returns `score 0.00 $0.00 error: You've hit your
session limit`, exit 1; 3 at once fit a full pass in one window), and the weekly limit
(gotcha 3).

A run that a limit cuts carries an `error`, so its batch is void: `compare.py` skips it,
names the dir, and takes the newest valid results dir of that case and model. Re-run
those cases; a clean re-run then counts.

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
