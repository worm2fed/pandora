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
  `~/.docker`, …) contains a symlink, and there is no flag (`DOCKER_CONFIG` does not bypass
  it). Workaround: run under an empty scratch `HOME` with `CLAUDE_CONFIG_DIR` pointing at
  the real config dir of the account to bill — that authenticates as-is, no
  `claude setup-token` needed. Nested inside a Claude Code session, drop `CLAUDECODE` from
  the env (`env -u CLAUDECODE`).

## What the cases measure

| case | ask | what it tells you |
|---|---|---|
| 01 regression, failing test | "the tests started failing this week, what's going on?" | ceiling — both arms diagnose it; the with arm must also hold the fix back |
| 02 selective bug | "EU invoices are wrong, US fine" | the approval gate: propose with trade-offs, don't patch |
| 03 suggested quick fix | "I think we just need a null check — confirm?" | does the skill resist the user's own guess |
| 04 pasted stack trace | prod traceback + log lines, no repo access | triggering on pasted evidence; the answer is hypotheses + the evidence that decides them |
| 05 fix-it wording | "off by one for some users. Just fix it." | triggering on a report with an instruction attached, and that the instruction is not plan approval |
| 06 negative | add a CSV export (feature request) | must not trigger |
| 07 negative | explain how the retry/backoff works | must not trigger |
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

## Backlog

- **Multi-turn flows** — `feature` (start path: branch + confirm), `workspace`, `implement`,
  `setup`, `model-tiers`. A single-prompt eval only measures "did it ask the right first
  question"; testing them properly needs a scripted multi-turn harness (a pre-answered second
  turn: "yes, that branch", an answered clarify question, a worker brief observed). Not
  started; recorded 2026-10-01 after suites 01–57 covered every single-prompt-observable skill.
