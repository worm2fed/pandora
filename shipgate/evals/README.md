# shipgate evals

Cases for `claude plugin eval`, one directory each. Every case builds its own synthetic
repository in `fixture.sh` (run by the harness **outside** the agent sandbox via
`case.yaml` → `context.scaffold_script`), so nothing here depends on a real project and
nothing private can leak in.

`two-turn/` is no case: it drives one interactive session for SC-010 of the approval path,
which the harness cannot run (one prompt, no `AskUserQuestion`). Its README says when and how.

## Run

Run cases through the run-evals scripts (`.claude/skills/run-evals/`), not through the
harness directly. Each run names its mode and its model; there is no default.

```
S=.claude/skills/run-evals/scripts
$S/run-case.sh --ablation with-without --model claude-opus-5-5 shipgate 05
$S/probe.sh --model claude-opus-5-5 shipgate 11
```

`run-case.sh` calls `claude plugin eval <target> --runs 3 --ablation <mode> --scaffold
--judge-model sonnet --no-publish --allow-tools Bash Edit Write --model <M> --keep-temp
--output-dir <dir> --case 'NN-*'`, or `--case <name>` when you pass the full name of an
eval case in place of `NN`. An eval case is a dir under `evals/` that holds `prompt.md` or
`case.yaml`; `run-case.sh` refuses any other dir there (a probe or fixture case,
`results`) with exit 64. `run-case.sh` sets the results dir itself: a new dir under
`evals/results/`, named by the UTC time and the script's process id, so runs side by side
never share one. It passes the dir as `--output-dir` and refuses a caller's own
`--output-dir` (exit 64). A run that leaves no `aggregate-result.json` there has no
result: `run-case.sh` says so with the harness status, removes the dir when it is empty,
and runs no post-run check, grade or clean-up. An extra `--report <path>` puts the HTML
report where you name it. With an explicit `--output-dir` the harness skips two checks it
makes on its default dir: the warning that results under `<plugin>/evals` may load as
plugin components, and its ownership check. The dir is where its default dir was.

- `--scaffold` is required — without it the fixture repos are never built and every case
  scores 0 in both arms.
- `--judge-model sonnet`: the default judge is a small model and mis-grades ranked answers.
- `--case '10-*'` filters; only `NN-*`-style globs work (no braces, no brackets).
- Bash-granting cases need `--allow-tools Bash Edit Write`.

### Modes and arms

The **with arm** loads the plugin; the **bare arm** (the harness calls it "without") loads
none.

| mode | flag | arms that run |
|---|---|---|
| `with-without` | `--ablation with-without` | both; the harness computes Δ |
| `none` | `--ablation none` | the with arm only |
| `bare` | `--bare` | the bare arm only (ADR 0035) |

The harness has no bare-only mode. `--bare` builds a stub plugin `<name>-bare` with no
skill, agent, hook, command or MCP server, and a copy of this directory without
`results/` and `__pycache__` (the harness refuses an `evals` link that leaves the plugin;
a link inside this directory must be relative and stay inside, or the stub is refused). It runs
the stub under `none` with `--trust-plugin` and writes `bare.json` into the results dir.
The flag is safe there: the stub is a fresh dir the script made, it holds no component,
and its `evals` is a copy of this directory, which a normal run already trusts. `compare.py` pairs a
`bare` result and a `none` result of one case and model into one `bare+none` row.

A grader is **with-only** when its config says `arm: with-only`, or when it is a
`tool_used: Skill` grader without `arm: both`. Under `with-without` the harness leaves it
out of the score; under `none` it counts it. So the raw scores of the two modes differ on
the same answers. `compare.py` scores every row under the **both-arm rule** (the
with-only graders left out), and recomputes it from the per-run grader results of a `none`
or `bare` run.

### The shadow guard (#49)

An installed plugin of the same name loads in place of the tree under test, in both arms.
Two checks stop that:

- before the run, `evalrun.py config-check` refuses a paying config dir that has a plugin
  of the same name installed (any scope) or enabled. It also refuses when the platform's
  managed settings enable that plugin (`managed-settings.json` and the `*.json` files of
  `managed-settings.d/` beside it): a managed enable loads the plugin in every config dir,
  the bare stub's run too, and no config dir can turn it off. Then the fix is to disable it
  in the managed file for the length of the runs, which needs admin rights. The check
  names the install or the file and the fix, and never changes either. MDM profiles, the
  Windows registry and server-managed settings are not read; post-run still sees what they
  load;
- after the run, `evalrun.py post-run` reads each run's kept trace. The init record must
  name the tree under test in a with run, and no plugin of that name in a bare run. It
  writes `shadow.json`. `compare.py` refuses a shadowed results dir. It warns on a
  results dir with no `shadow.json`, and `--record` refuses that dir. A dir with no
  `shadow.json` or a shadowed run counts only in one "skipped N older results dirs" line
  when compare uses a newer result of the same case and model. A dir with no recorded
  model counts only in that line when it is older than the newest pick of its case, any
  model; else compare refuses it. A run with no trace to check gives a warning only when
  compare uses its dir. `--record` skips every case and model that has a refusal in the
  run, so a refused partner never turns a `bare+none` row into a half row. A case whose
  runs in a dir carry an `error` (a limit hit, an interrupt, a failed scaffold) is a void
  batch: compare never compares or records it, names it in a line `skipped <dir>: void
  batch of <case> <model>, ...`, and takes the newest valid dir of that case and model.

### Script graders

A case can hold `script-graders/<name>.py`, beside `graders/`. After the run,
`evalrun.py post-run` runs each script per run as `python3 <script> <trace.jsonl>`. Exit 0
is a pass. Exit 1 with a line on stdout is a fail, whether the script crashed or not:
Python flushes stdout at exit, after the traceback, so a printed line survives (a hard
kill or `os._exit` loses it). Exit 1 with an empty stdout is an
error (a crash before any print, `sys.exit("message")`, a syntax error), and so is any
other exit, a timeout or a missing trace. An error has `passed: null`. The reason of a
pass or a fail is the first stdout line. The reason of an error is the last stderr line,
or "exited N" when stderr is empty. So print a line on stdout only when the script
decides to fail, or just before exit 0. The results go into `script-graders.json`,
beside the harness score and never inside it (as for the signal grader, ADR 0016).
`compare.py` shows the pass rate per arm and flags a fall against the baseline row. Test a
script grader with a canned trace; it costs nothing.

A script grader judges tool calls, not shell text. The trace records an Edit, Write,
MultiEdit or NotebookEdit call exactly, so count an edit only from those, and state that an
edit made through a shell command is out of scope. A net of patterns over Bash commands
(`sed -i`, `>`, `cp`) misses quoted paths and reads past command separators: in #28 such a
net in case 22 failed review twice, and the user chose tool edits only.

### Three case forms

The file names of a case directory decide what it is (ADR 0036):

| form | files | run by |
|---|---|---|
| eval case | `prompt.md` + `graders/*.md` (or `case.yaml`), `fixture.sh`, optional `script-graders/` | the harness |
| probe case | `fixture.sh`, `probe.md` (the prompt), `probe.json` (the expectation) | `probe.sh` |
| fixture case | `fixture.sh`, `expected.json` | unit tests and `signal_grader.py fixture` |

The harness never runs a probe or fixture case: it holds no `prompt.md` and no `graders/`.
`probe.json` names the skill that must or must not fire and the calls that must stay at 0:

```json
{"skill": "structured-debug", "fires": false,
 "zero": {"bash": ["signals\\.py", "codegraph"], "agent": true, "edit": ["docs/"], "write": []}}
```

An empty pattern list counts every call of that tool. A probe passes when all its runs
pass (3 of 3). A run that stops on the turn cap (`error_max_turns`) is judged by the
counts of its stream up to the cap, and the result file marks it `stopped: max_turns`;
any other error fails the run.

### Sets

`sets.json` (from PR 2 of #28) names the sets: `kept`, `guards`, `ablation-32`, `probes`
and `parked`. Each lists case directory names. `probe.sh --model M shipgate probes` runs
the probe set. `run-set.sh --max-cost-usd C --ablation X --model M shipgate kept` runs an
eval set one case at a time under one ceiling; `--shard K/N` splits it across
invocations side by side (the run-evals skill, "Running many cases"). The `parked` set
never runs.

### Baseline

`baseline.json` holds one row per case and model (ADR 0034): the mode, the scoring rule,
the version the run tested, the harness and judge, the runs, the results dir, the score
per arm, Δ, the mean cost and time of one run per arm, the judge cost, and the
script-grader rates. Rows recorded before the model was recorded sit under the key
`unrecorded`. `compare.py` never crosses a model, a mode or a rule, and refuses a result
with no recorded model.

### Cost (measured 2026-11-26 and 2026-11-27, harness 2.1.332, judge sonnet)

USD for one batch of 3 runs, agent and judge, from the newest valid results dir of each
case, model and arm (the re-baseline of #28). "bare" is `--bare`, "with" is
`--ablation none`; a `with-without` run costs about the sum of the two. A dash: that arm
did not run for that model. A Fable run costs about 1.98 times an Opus run of the same
case (median of 24 cases, with arm; 1.97 over 22 cases, bare arm). The sum row adds the
unrounded costs, so it can differ from the sum of the printed cells by 0.01 or 0.02.

| Case | Set | Opus bare | Opus with | Fable bare | Fable with |
| --- | --- | --- | --- | --- | --- |
| 02 | kept | 0.57 | 0.94 | 1.18 | 1.85 |
| 03 | kept | 0.43 | 0.89 | 1.02 | 1.58 |
| 04 | kept | 0.42 | 0.75 | 0.98 | 1.46 |
| 05 | kept | 0.44 | 0.83 | 0.85 | 1.61 |
| 15 | kept | 0.86 | 1.47 | 2.03 | 3.24 |
| 16 | kept | 0.77 | 1.60 | 1.81 | 3.06 |
| 17 | ablation-32 | — | — | 1.71 | — |
| 18 | kept | 0.73 | 1.21 | 1.57 | 2.48 |
| 19 | kept | 0.84 | 1.24 | 1.37 | 2.42 |
| 22 | kept | 0.54 | 0.77 | 1.03 | 1.51 |
| 23 | kept | 0.32 | 0.64 | 0.80 | 1.36 |
| 24 | ablation-32 | — | — | 0.84 | 1.22 |
| 25 | ablation-32 | — | — | 0.92 | — |
| 26 | kept | 0.44 | 0.68 | 0.81 | 1.30 |
| 29 | ablation-32 | — | — | 1.23 | — |
| 30 | ablation-32 | — | — | 1.08 | — |
| 31 | ablation-32 | — | — | 1.24 | — |
| 32 | ablation-32 | — | — | 1.70 | — |
| 33 | ablation-32 | — | — | 1.36 | — |
| 36 | ablation-32 | — | — | 1.08 | — |
| 38 | kept | 0.38 | 0.52 | 0.72 | 0.80 |
| 39 | ablation-32 | — | — | 1.24 | — |
| 40 | ablation-32 | — | — | 0.90 | — |
| 43 | kept | 0.47 | 0.54 | 1.09 | 1.60 |
| 45 | kept | 0.55 | 1.14 | 1.06 | 3.08 |
| 46 | kept | 0.55 | 1.54 | 0.99 | 3.55 |
| 47 | ablation-32 | — | — | 1.04 | 2.38 |
| 48 | guards | — | 1.02 | — | 2.16 |
| 51 | kept | 0.90 | 1.73 | 2.24 | 3.83 |
| 52 | guards | — | 1.47 | — | 3.16 |
| 53 | ablation-32 | — | — | 1.16 | 2.16 |
| 54 | ablation-32 | — | — | 1.92 | — |
| 55 | ablation-32 | — | — | 2.20 | 3.60 |
| 58 | kept | 0.75 | 1.26 | 1.32 | 2.19 |
| 68 | kept | 0.62 | 0.96 | 1.40 | 2.46 |
| 69 | ablation-32 | — | — | 1.04 | — |
| 70 | kept | 0.72 | 1.98 | 1.26 | 3.57 |
| 73 | kept | 1.09 | 1.32 | 1.77 | 2.64 |
| 74 | ablation-32 | — | — | 1.31 | — |
| 76 | kept | 1.48 | 2.22 | 2.84 | 4.33 |
| 77 | kept | 0.82 | 1.36 | 1.64 | 2.73 |
| **sum** | | 14.70 | 28.09 | 51.73 | 67.34 |

Probes, 3 runs each with `--max-turns 4`: all 19 cost 8.51 USD on Opus and 17.50 USD on
Fable. A negative probe costs 0.35 to 0.52 USD on Opus and 0.71 to 1.19 USD on Fable;
the three probes whose skill fires (08, 09, 10) cost 0.57 to 0.83 USD on Opus and 1.18 to
1.67 USD on Fable.

The account's 5-hour window: in one afternoon of these runs, about 0.70 USD of eval spend
moved the window by one percent (about 70 USD for a full window), so an Opus case (0.52 to
2.22 USD, with arm) is about 1 to 3% and a Fable case (0.80 to 4.33 USD) about 1 to 6%. A
candidate, not built: a quota gate in `run-set.sh` that reads the status line's rate-limit
data before each case and waits while the 5-hour window is at 80% or more. The status data
can hold several accounts, so such a gate must read the paying account's own observation,
and the reading lags.

### What the harness does to a run (2.1.332)

Found in the first paid runs of #28:

- It keeps each sandbox read-only (mode 500) with a `sealed/` dir at 000. `post-run --clean`
  unseals a sandbox before it removes it, and names any it could not remove.
- A grader that reads `last_message` sees only the final assistant message. When the agent
  starts a background task, the run can end with a short follow-up after the task
  finishes, and the answer sits in an earlier message. Such a run scores low with nothing
  wrong in the answer (case 74, run 3: 1 turn, 501 s, a 337-character follow-up). Read a
  low run's report, and compare its last message with the other runs, before you call the
  fall behaviour.
- The init record of a bare run lists no plugin at all, not the stub.

## macOS notes

- The agent sandbox blocks the Xcode git shim (`/usr/bin/git` → `xcrun` cache under
  `/var/folders`). Put a real git first on `PATH` (`brew install git`) or every run that
  touches history dies with "Operation not permitted". A 0.00 score with a cheap run is
  almost always this — read the run's final message before believing it.
- The harness refuses Bash-granting runs while a credential store under `~` (`~/.aws`,
  `~/.docker`, …) contains a symlink, and there is no flag (`DOCKER_CONFIG` does not bypass
  it). Workaround: run under a scratch `HOME` with no credential store, with
  `CLAUDE_CONFIG_DIR` pointing at the real config dir of the account to bill. On macOS the
  scratch `HOME` links the login keychain (`~/Library/Keychains` and the security plist),
  because a keychain-backed login is "Not logged in" without it. No `claude setup-token`
  needed. Nested inside a Claude Code session, drop `CLAUDECODE` from
  the env (`env -u CLAUDECODE`).

## What the cases measure

| case | ask | what it tells you |
|---|---|---|
| 02 selective bug | "EU invoices are wrong, US fine" | the approval gate: propose with trade-offs, don't patch |
| 03 suggested quick fix | "I think we just need a null check — confirm?" | does the skill resist the user's own guess |
| 04 pasted stack trace | prod traceback + log lines, no repo access | triggering on pasted evidence; the answer is hypotheses + the evidence that decides them |
| 05 fix-it wording | "off by one for some users. Just fix it." | triggering on a report with an instruction attached, and that the instruction is not plan approval |
| 06, 07 negative (probe) | add a CSV export; explain how the retry/backoff works | `structured-debug` must not fire |
| 08 bug localization (probe) | "which file has the defect?" | `structured-debug` fires on the natural prompt; the ranking itself is a fixture test of `signals.py suspects` (`monthRange.ts` first) |
| 09 blast radius (probe) | "what does the change at HEAD affect?" | `route-and-map` fires; the blast radius is the fixture of 13 |
| 10 risk ranking (probe) | "rank the changed files by regression risk" | `review` fires; the ranking is a fixture test of `hotspots --diff` (`promo.ts`, then `calendar.ts`) |
| 11 negative (probe) | one-line README typo | `route-and-map` must not fire, and no Bash call names `signals.py` or `codegraph` |
| 13 blast radius (fixture) | — | `test_signal_grader.py` scores the offline `signals.py blast` of its fixture against `expected.json` |
| 58 regression, large journaled repo | "the pricing tests started failing this month, what's going on?" | names the cause and the commit, says why the regression slipped through, holds the fix back; the with arm records its debug event (with-only) |
| 70 fact retention | review the change at HEAD; three planted findings in three files, and an authorised INFO-logging deviation | the report keeps every planted fact (file:line, severity, failing input), does not raise the recorded deviation, has no sentence over 40 words (a script grader) and names the files in code form |
| 72 blast radius, large (fixture) | — | a generated 484-file npm workspace (`@app/*` package imports, barrel re-exports, `require`, a `__tests__/` tree); `test_eval_fixtures.py` runs `signal_grader.py fixture --arm graph` offline when codegraph is on `PATH` (44 importers, 15 tests); the regex scanner does not resolve workspace package names (2 of 59 files); the graph alone missed the re-export and package-entry hops (56 of 59), and from shipgate 0.24.0 the re-export pass reaches all 59 |
| 73 reuse, hidden helper | add retry with exponential delay to `fetchInvoice`, in a generated 290-file workspace; prompt names `implement` | whether the reuse step finds `withPolicy` in `packages/platform/src/net/resilience/` when no name, comment, caller or commit subject gives it away (the fixture asserts it) |
| 74 canon lens | review the change at HEAD in a journaled TS repo whose config's Style section names a project skill, `typed-canon` | whether the review names both canon violations (a `switch` over a closed union; an unbranded id in a domain type) as must-fix findings before its verdict, and records `style` on the review entry (#11) |

The table shows the cases this section explains, not every case: `sets.json` lists them
all. Before #28, the natural prompts of 08–10 fired no shipgate skill in any run, so their Δ
measured **triggering**, not the signals. They are trigger probes now. The explicit twins
12–14 (12 and 14 removed in #28) showed the signals' contribution: with `signals.py`, the
two files with the worst fix history ranked #1/#2 in 6/6 runs of 14; the same `review`
skill without signals managed 2/6, no plugin 3/6.

Graders are outcome checks (regex over the answer, LLM rubrics for evidence quality);
`skill-fired` is display-only under ablation.

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
  Since #28 case 70 has no rubric: a script grader checks the sentence length, and a regex
  checks the file names in code form.
- `baseline.json` drifts with the harness. On 2026-10-12, 5 of 23 rows moved by more than
  0.10 against the 2026-10-06 baseline on the unchanged tree, mostly in the without arm, and
  the full suite was re-recorded that day. Each row now carries the harness (`claude`) and
  `judge` that produced it, and `compare.py` marks a row recorded under a different harness
  with `~` and prints the count. A flag on a `~` row is a question, not a verdict: re-run
  the case once on the unchanged tree the same day, compare the after-run with that
  before-run, then `--record` the after-run. After a harness update, re-record the kept
  suite per model rather than reading every `~` row one by one: `run-set.sh
  --max-cost-usd C --ablation with-without --model M shipgate kept`, in shards when it is
  long. The cost per model is in the run-evals skill, "Cost".
- A grader that reads `.claude/shipgate.db` reads the SQLite record as text. In the
  `events` row the `type` column comes directly before the `data` column. `journal.py`
  writes `data` with `json.dumps(sort_keys=True)` and the default `", "` and `": "`
  separators. So match an event's payload from its type, with no NUL byte between:
  `review-verdict\{[^\x00]{0,1000}"ranking": \{"files": …`. Keys come in sorted order,
  never in the order the skill wrote them.

## Code-graph arm

The harness's `--ablation with-without` turns the plugin on and off. It does not turn
codegraph on and off. The code-graph ablation (PRD `code-graph`, SC-007) is two separate
runs of the same cases. Since #28 it has one eval case, 73: 08–10 are trigger probes, 13 and
72 are fixture cases that run offline (`signal_grader.py fixture`, `test_eval_fixtures.py`),
and 12, 14 and 71 are removed. The results below ran on the suite before #28. Cases 72 and
73 exist for this ablation: their workspaces are too large to read whole in 30 turns, so a
score depends on what the signals find.

- **Graph arm.** Run the case as usual with `codegraph` on `PATH`. The agent sandbox sees
  `PATH`, so `signals.py` builds the index in `app/` and prints `"source": "graph"`.
- **Regex arm.** Take `codegraph` off `PATH`. `run-case.sh --no-codegraph` removes every
  `PATH` directory that holds a `codegraph` executable and calls `claude` by its resolved
  path, because both often live in `~/.local/bin`. `signals.py` then prints
  `"source": "regex"` and the one-line install advisory.

```
S=.claude/skills/run-evals/scripts
$S/run-case.sh --ablation none --model M shipgate 73                  # graph arm
$S/run-case.sh --no-codegraph --ablation none --model M shipgate 73   # regex arm
```

Do not use `SHIPGATE_CODEGRAPH_BIN=/nonexistent` for the regex arm. The harness removes
unknown variables from the agent's environment, so the agent still finds codegraph.
A `case.yaml` can set only `EVAL_*` variables. Confirm each arm from a kept trace
(`--keep-temp`): look for `"source": "graph"` or `"source": "regex"` in a `signals.py`
result. Record the graph arm with `compare.py --record`; keep the regex arm out of
`baseline.json`. Also move the regex arm's results dirs out of `evals/results/` after the
run. `compare.py` takes the newest valid dir per case, so a regex-arm dir there replaces the
graph arm in every later compare.

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
arm scored 1.00: `git log` named the helper's commit ("call policies for flaky
upstreams"), and a grep for `attempt` found `attempts` in `policy.ts`. #28 removed both
giveaways and the helper's two callers.

The probe of case 11 grades the negative side: it fails on any Bash call that names
`signals.py` or `codegraph`.

## Signal grader

The harness grades the agent's answer. `signal_grader.py` grades the signal that the agent
read: the `blast` object of `signals.py blast --json` or `signals.py hotspots --blast
--json`. On case 72 the two arms give the same answer score, but the signals differ by a
factor of 28. The grader shows that difference (ADR 0016, #6).

It reads the case's `expected.json`. Only the fixture cases 13 and 72 have one, and since
#28 the harness runs neither. Case 09 is a trigger probe.

The grader gives two numbers for each of two lists:

- **Precision** = true files in the list / files in the list. An empty list or a `null`
  list gives 1.0.
- **Recall** = true files in the list / true files. An empty truth gives 1.0.

| list | truth |
|---|---|
| `blast.files` | `importers` and `tests` of `expected.json` |
| `blast.tests` | `tests` of `expected.json` |

The changed file itself (`hub`) is not in the truth, because `signals.py` does not list a
seed as its own importer. The grader drops a leading `./` before it compares paths. It also
prints the counts (true positives, got, truth), the missed and the extra files, and the
structure source (`graph` or `regex`). `blast.truncated: true` means that `--limit` cut the
list. The grader then reports the cut, and the recall is a lower bound.

Three ways to run it:

```
G=shipgate/evals/signal_grader.py
python3 $G fixture shipgate/evals/72-graph-blast-radius-large --arm graph   # or --arm regex
python3 $G trace <run>/trace.jsonl shipgate/evals/72-graph-blast-radius-large/expected.json
python3 $G results shipgate/evals/results/<timestamp>
```

- `fixture` runs offline and costs nothing. It scaffolds `fixture.sh` into a temp dir and
  runs `signals.py blast --diff HEAD~1 --json` in `app/`. The graph arm uses `--graph auto`
  (codegraph must be on `PATH`), the regex arm `--graph off`. The prompts ask about "the
  change at HEAD", so the seeds are the files that HEAD changes. In case 72 HEAD also
  changes a script that nothing imports; that seed adds no files.
- `trace` reads a kept `trace.jsonl`. It scores the last Bash call that runs `signals.py`
  with `blast` (or `hotspots --blast`) and `--json` and whose result holds the JSON. The
  JSON's `blast.files` must be a list. A call whose `blast.files` is null, absent or not a
  list is skipped, and the grader takes the call before it. It ignores other output in the
  same result, such as an advisory line. With no such call it prints "no signals result in
  the trace" and exits 3.
- `results` runs `trace` for each run of each case with an `expected.json`. It prints one
  row per run: case, arm, run, files P/R, tests P/R and source. `run-case.sh` runs it after
  each such case, in both arms (also with `--no-codegraph`), before it removes the kept
  sandboxes. Since #28 no eval case has an `expected.json`, so this path runs only for a
  results dir from before. A harness run without `--keep-temp` keeps no trace; the row then says
  "trace gone".

Every subcommand takes `--json`. The grader adds nothing to the harness score or to
`baseline.json`, and `compare.py` does not track it (ADR 0016).

`expected.json` of case 72 comes from `fixture.sh --expected`. The one of case 13 comes from
a read of the imports in `fixture.sh`. HEAD changes only `src/util/round.ts`. `currency.ts`
and `percent.ts` import it, `lineItem.ts` and `tax.ts` import those, `invoice.ts` imports
both, and `pdfSummary.ts` imports `invoice.ts`. The case has no test files.

Offline result on 2026-11-07 (`fixture`, codegraph 1.6.2, shipgate 0.24.0):

| case | arm | `blast.files` P / R | tp / got / truth | `blast.tests` P / R | tp / got / truth |
|---|---|---|---|---|---|
| 72 | graph | 1.00 / 1.00 | 59 / 59 / 59 | 1.00 / 1.00 | 15 / 15 / 15 |
| 72 | regex | 1.00 / 0.03 | 2 / 2 / 59 | 1.00 / 0.00 | 0 / null / 15 |
| 13 | graph | 1.00 / 1.00 | 6 / 6 / 6 | 1.00 / 1.00 | 0 / 0 / 0 |
| 13 | regex | 1.00 / 1.00 | 6 / 6 / 6 | 1.00 / 1.00 | 0 / null / 0 |

Before 0.24.0 (2026-11-06, the same fixture) the graph arm of 72 gave 1.00 / 0.95 (56 of
59). It missed the two barrels `money/src/index.ts` and `notify/src/index.ts`, and
`core/src/config/scanRebateSet.ts`, which only a second barrel reaches: codegraph records
no edge for `export * from`, and none from a bare `@app/<name>` import to the package
entry (#7, ADR 0017). The re-export pass in `signals.py` adds those edges on the graph
arm. The regex scanner does not resolve the `@app/*` package names, and it finds no tests
(`null`); it is unchanged.

## Backlog

- **Multi-turn flows** — `feature` (start path: branch + confirm), `workspace`, `implement`,
  `setup`, `model-tiers`. A single-prompt eval only measures "did it ask the right first
  question"; testing them properly needs a scripted multi-turn harness (a pre-answered second
  turn: "yes, that branch", an answered clarify question, a worker brief observed). Not
  started; recorded 2026-10-01 after suites 01–57 covered every single-prompt-observable skill.
