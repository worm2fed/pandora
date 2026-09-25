# shipgate evals

Cases for `claude plugin eval`, one directory each. Every case builds its own synthetic
repository in `fixture.sh` (run by the harness **outside** the agent sandbox via
`case.yaml` → `context.scaffold_script`), so nothing here depends on a real project and
nothing private can leak in.

## Run

```
claude plugin eval . --runs 3 --ablation with-without --scaffold --judge-model sonnet --no-publish
```

- `--scaffold` is required — without it the fixture repos are never built and every case
  scores 0 in both arms.
- `--judge-model sonnet`: the default judge is a small model and mis-grades ranked answers.
- `--case '10-*'` filters; only `NN-*`-style globs work (no braces, no brackets).
- Bash-granting cases need `--allow-tools Bash Edit Write`.

## macOS notes

- The agent sandbox blocks the Xcode git shim (`/usr/bin/git` → `xcrun` cache under
  `/var/folders`). Put a real git first on `PATH` (`brew install git`) or every run that
  touches history dies with "Operation not permitted". A 0.00 score with a cheap run is
  almost always this — read the run's final message before believing it.
- The harness refuses Bash-granting runs while a credential store under `~` (`~/.aws`,
  `~/.docker`, …) contains a symlink, and there is no flag. Workaround: run under a scratch
  `HOME` with `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`.

## What the cases measure

| case | ask | what it tells you |
|---|---|---|
| 08 bug localization | "which file has the defect?" | ceiling — the bug is readable in the code; both arms ≈0.9 |
| 09 blast radius | "what does the change at HEAD affect?" | ceiling — transitive importers are findable by grep |
| 10 risk ranking | "rank the changed files by regression risk" | bare model ≈ coin-flip on the two hot files |
| 11 negative | one-line README typo | must not trigger the flow or run signals |
| 12–14 explicit | same as 08–10, prompt names the shipgate skill | the signals path itself (`review` + `hotspots --diff`) |

On naturally phrased prompts (08–10) no shipgate skill has fired in any run so far, so their
Δ measures **triggering**, not the signals. Case 14 is the one that shows the signals'
contribution: with `signals.py`, the two files with the worst fix history rank #1/#2 in 6/6
runs; the same `review` skill without signals manages 2/6, no plugin 3/6.

Graders are outcome checks (regex over the answer, LLM rubrics for evidence quality);
`skill-fired` is display-only under ablation except in 12–14, where it is scored.
