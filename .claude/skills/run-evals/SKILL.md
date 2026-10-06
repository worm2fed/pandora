---
name: run-evals
description: Use whenever asked to run, re-run, summarize or debug the plugin evals / `claude plugin eval` in this marketplace, check whether a skill triggers on a case, or when an eval run errors, scores 0.00, refuses to start (git shim, credential-store symlink, weekly limit) or bills the wrong account. Encodes the working command, this machine's workarounds and the cost rule of thumb.
---

# Run the plugin evals

Every plugin's cases live in `<plugin>/evals/NN-*/`; how a case is written (prompt.md,
graders, `fixture.sh` scaffold) is in [shipgate/evals/README.md](../../../shipgate/evals/README.md).
This skill is about *running* them on this machine. Scripts live in `scripts/` next to
this file; paths below are relative to the repo root.

## Two tools, two questions

| question | tool | cost |
|---|---|---|
| Does the skill fire on this prompt? (iterating on a description) | `scripts/probe.sh` — plain `claude -p --plugin-dir`, counts `Skill` tool_use in the stream | ~$0.10/run |
| Is the answer better with the plugin? (the gate) | `scripts/run-case.sh` — `claude plugin eval` with graders + with/without ablation | ~$1 per case per tree (with+without, 3 runs) |

The probe measures triggering only, never answer quality. Ship on harness numbers.
In the probe's session (`claude -p --plugin-dir <plugin> --setting-sources "" --strict-mcp-config`)
the plugin's skill descriptions (`<plugin>:<skill>` + description, capped at 1,536 chars) are the
whole triggering surface — no README, no hooks output — so a description is all there is to tune.

## Commands

```bash
S=.claude/skills/run-evals/scripts
$S/probe.sh shipgate 05 3            # 3 runs, max 4 turns each; prints skill=[...] per run
$S/run-case.sh shipgate 05           # full tree for case 05; prints the results dir
$S/run-case.sh shipgate 10 --runs 1 -j 3 --keep-temp --max-cost-usd 2   # extra flags pass through
python3 $S/summarize.py shipgate/evals/results/<timestamp>              # or the results/ root
```

`run-case.sh` runs exactly:

```
claude plugin eval <plugin-dir> --runs 3 --ablation with-without --scaffold --judge-model sonnet \
  --no-publish --allow-tools Bash Edit Write --case 'NN-*' [extra flags]
```

- `--scaffold` is mandatory: without it every case scores 0 in both arms.
- `--judge-model sonnet`: the default haiku judge mis-grades ranked answers.
- `--case` accepts only `NN-*` globs (no braces or brackets), so it is one invocation per
  case. Run several cases as separate parallel jobs; `-j <n>` parallelizes the runs
  *within* one invocation (all on one credential, one rate limit).
- Useful extras: `--max-cost-usd <usd>` ceiling (exit 2 when hit), `--keep-temp` keeps the
  sandbox and `trace.jsonl`, `--json <path>` writes the full result, `--runs 1` for a
  cheap look.
- Exit 1 is normal: the default `--threshold` is 1.0.

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
   shell profile may map `CLAUDE_CONFIG_DIR` to one whose weekly limit is exhausted — the
   symptom is the child `claude` printing `You've hit your weekly limit · resets <time>`
   and a run with cost 0. Bill evals to the account that should pay: pass
   `--config-dir DIR` or set `EVAL_CONFIG_DIR` in your shell profile; without either, the
   scripts fall back to `$CLAUDE_CONFIG_DIR`, then `~/.claude`. No account path is written
   down in this repo (public).
4. **Nested claude.** Inside a Claude Code session, launch the child with
   `env -u CLAUDECODE` (the scripts do).
5. **zsh.** The Bash tool's shell is zsh: never start an unquoted word with `=`
   (`echo ===` fails with "== not found").

## Reading results

Results land in `<plugin>/evals/results/<timestamp>/aggregate-result.json` + `report.html`
(gitignored). JSON: `cases[]` → `name`, `graders[]`, `arms.with[]` / `arms.without[]`
(per run: `score`, `passed`, `turns`, `costUsd`, `tracePath`, `error`, `graders[]`) and
`aggregates` (`score`, `scoreWithout`, `passRate`, `delta`). Under `--ablation
with-without` a `tool_used: Skill` grader (`skill-fired`) is display-only unless the case
scores it (`min`/`max` set). `summarize.py` prints per case: with score, without score,
delta, per-run turns per arm, and `skill-fired k/n` for the with arm (from the run's
graders, else the trace if kept, else `n/a`).

Cost rule of thumb (measured 2026-10-06, 69 cases, 3 runs per arm): $1.46 per case per
with+without tree — small cases ~$1.40, the large journaled fixtures (58–67) ~$1.80, the design
fan (51) $4 — so the whole suite is ~$100 and ~95 min on 3 parallel lanes. Probes are ~$0.10 a
run. Set `--max-cost-usd` when exploring.

## Running many cases

One `run-case.sh` per case, a few in parallel. Two limits bite: the account's 5-hour session
limit (4 lanes exhausted it twice in one afternoon — every run after that returns `score 0.00
$0.00 error: You've hit your session limit`, exit 1; 3 lanes fit a full pass in one window),
and macOS `xargs -I{}`, whose replacement string is capped at 255 bytes ("command line cannot
be assembled, too long"). Export a function instead:

```bash
export S=.claude/skills/run-evals/scripts CFG=<config-dir> L=<log-dir>
run_one() { "$S/run-case.sh" --config-dir "$CFG" shipgate "$1" > "$L/$1.log" 2>&1; echo "$1 exit=$?" >> "$L/progress.txt"; }
export -f run_one
ls shipgate/evals | grep -E '^[0-9]{2}-' | cut -c1-2 | xargs -P 3 -n 1 bash -c 'run_one "$0"'
```

Afterwards grep each log for `hit your session limit` before trusting its score, and re-run
those cases: `compare.py` takes the latest results dir per case, so a clean re-run supersedes
a limit-hit one.

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
