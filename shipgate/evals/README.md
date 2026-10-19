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
| 70 fact retention | review the change at HEAD; three planted findings in three files | the with arm's report keeps every planted fact (file:line, severity, failing input) while following the Writing for people rule; readability rubric at weight 0.25, paired with a hedge-word regex |
| 71 reuse detection | add retry with exponential delay to `fetchInvoice`; prompt names `implement` | the reuse step finds `withBackoff`, a helper whose name does not say "retry", and wraps the call in it instead of writing a new loop |
| 72 blast radius, large | the change at HEAD in a generated 484-file npm workspace (`@app/*` package imports, barrel re-exports, `require`, a `__tests__/` tree); prompt names `route-and-map` | recall and precision against the generated truth (44 importers, 15 tests); the regex scanner does not resolve workspace package names (2 of 59 files), the graph misses only re-export hops (56 of 59) |
| 73 reuse, hidden helper | as 71, in a generated 290-file workspace; the helper `withPolicy` sits in `packages/platform/src/net/resilience/` and no file says "retry" or "backoff" | whether the reuse step still finds the helper when its name and path give nothing away |

On naturally phrased prompts (08–10) no shipgate skill has fired in any run so far, so their
Δ measures **triggering**, not the signals. Case 14 is the one that shows the signals'
contribution: with `signals.py`, the two files with the worst fix history rank #1/#2 in 6/6
runs; the same `review` skill without signals manages 2/6, no plugin 3/6.

Graders are outcome checks (regex over the answer, LLM rubrics for evidence quality);
`skill-fired` is display-only under ablation except in 12–14, where it is scored.

Writing graders for a *behaviour* (a lens applied, a stance taken, rather than a fact found):

- Pair the LLM rubric with one short regex over the behaviour's vocabulary and read the with-arm
  transcripts before trusting either. In case 68 a five-claim conjunctive Sonnet rubric failed
  2 of 3 with-runs that visibly steel-manned, while a regex (`strongest case|best case for|
  steel-man…`) split 2/3 vs 0/3; the judge is the noisier signal on behaviour.
- Never grade sentence *order* ("states the case against before agreeing"). Answers that open
  "I agree" and then build and answer the opposing case are correct; grade presence and
  engagement.
- Any edit to a grader's text — rubric or regex — invalidates the recorded run: re-run the
  case and `compare.py --record` before committing, so `baseline.json` always describes the
  graders on disk.
- A readability or style rubric is the extreme case. On case 70 a four-claim and then a
  three-claim rubric failed 6/6 runs in both arms on a report that a direct Sonnet judge passes
  on every claim; the harness judge split 2/3 at best. Keep such a rubric at a low weight
  (0.25) and pair it with a deterministic regex for the part that can be matched (hedge
  words, fenced blocks). Grade the facts with their own regexes; they are the signal.
- `baseline.json` drifts with the harness. On 2026-10-12, 5 of 23 rows moved by more than
  0.10 against the 2026-10-06 baseline on the unchanged tree, mostly in the without arm, and
  the full suite was re-recorded that day. Each row now carries the harness (`claude`) and
  `judge` that produced it, and `compare.py` marks a row recorded under a different harness
  with `~` and prints the count. A flag on a `~` row is a question, not a verdict: re-run
  the case once on the unchanged tree the same day, compare the after-run with that
  before-run, then `--record` the after-run. After a harness update, re-record the whole
  suite (about $100 and 95 minutes on 3 lanes) rather than reading 70 `~` rows one by one.

## Code-graph arm

The harness's `--ablation with-without` turns the plugin on and off. It does not turn
codegraph on and off. The code-graph ablation (PRD `code-graph`, SC-007) is two separate
runs of the same cases: 08–14 and 71–73. Cases 72 and 73 exist for this ablation: their
workspaces are too large to read whole in 30 turns, so a score depends on what the signals find.

- **Graph arm.** Run the case as usual with `codegraph` on `PATH`. The agent sandbox sees
  `PATH`, so `signals.py` builds the index in `app/` and prints `"source": "graph"`.
- **Regex arm.** Take `codegraph` off `PATH`. `run-case.sh --no-codegraph` removes every
  `PATH` directory that holds a `codegraph` executable and calls `claude` by its resolved
  path, because both often live in `~/.local/bin`. `signals.py` then prints
  `"source": "regex"` and the one-line install advisory.

```
S=.claude/skills/run-evals/scripts
$S/run-case.sh shipgate 13                  # graph arm
$S/run-case.sh --no-codegraph shipgate 13   # regex arm
```

Do not use `SHIPGATE_CODEGRAPH_BIN=/nonexistent` for the regex arm. The harness removes
unknown variables from the agent's environment, so the agent still finds codegraph.
A `case.yaml` can set only `EVAL_*` variables. Confirm each arm from a kept trace
(`--keep-temp`): look for `"source": "graph"` or `"source": "regex"` in a `signals.py`
result. Record the graph arm with `compare.py --record`; keep the regex arm out of
`baseline.json`. Also keep the regex arm's results dirs out of `evals/results/` (pass
`--output-dir <scratch dir>`, or move them after the run). `compare.py` takes the newest
dir per case, so a regex-arm dir there replaces the graph arm in every later compare.

Runs that start in the same millisecond get the same default results dir. The second
run then refuses to write it ("already existed"), and only its `--json` file keeps the
result. Start parallel lanes with `--output-dir` or `--json`.

Result on 2026-10-19 (plugin 0.17.0, 3 runs per arm): every case scored 1.00 with and
without the plugin in both arms. The graph arm read `"source": "graph"` in 20 of 21
with-plugin runs of 08–10, 12–14 and 71: 3/3 per case, except case 12 at 2/3 (one run of 12
printed no structure block). The
regex arm read `"source": "regex"` and the advisory in all 21. Case 11 made no codegraph
call in either arm. The fixtures are too small to separate the arms: in case 71 the agent
lists and reads all 9 files before it searches, and 09/13 have no test files, so
`blast.tests` stays empty.

Cases 72 and 73 (same day, claude 2.1.304) did not separate the arms either. In 72,
`signals.py blast` reaches 56 of the 59 true files through the graph and 2 through the regex
scanner. The regex-arm agent saw the low count, wrote its own import resolver in one turn
and listed 43–44 of 44 importers and 15 of 15 tests. The graph-arm agent trusted the
graph, which misses one file reached only through a second barrel. With-plugin scores:
graph 0.88/0.88/0.88, regex 0.88/1.00/0.88 (3 runs each, `--ablation none`). In 73 every
arm scored 1.00: `git log` names the helper's commit ("call policies for flaky
upstreams"), and a grep for `attempt` finds `attempts` in `policy.ts`.

Case 11 grades the negative side: `no-codegraph-run` fails on any Bash call that names
`codegraph` or runs `signals.py graph`, in both arms.

## Backlog

- **Multi-turn flows** — `feature` (start path: branch + confirm), `workspace`, `implement`,
  `setup`, `model-tiers`. A single-prompt eval only measures "did it ask the right first
  question"; testing them properly needs a scripted multi-turn harness (a pre-answered second
  turn: "yes, that branch", an answered clarify question, a worker brief observed). Not
  started; recorded 2026-10-01 after suites 01–57 covered every single-prompt-observable skill.
