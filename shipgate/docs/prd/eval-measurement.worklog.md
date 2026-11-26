---
type: worklog
title: "Worklog: Evals measure only what a decision needs, per model, with cost and time"
created: 2026-11-25
updated: 2026-11-25
tags:
  - worklog
  - shipgate
  - evals
status: designed
prd: "./eval-measurement.md"
issue: "#28 (shipgate), with #49; child of #37"
related:
  - "../research/2026-11-25-eval-suite-audit.md"
  - "../adr/0034-a-baseline-row-is-per-case-and-model-and-names-its-mode-and-rule.md"
  - "../adr/0035-the-bare-arm-runs-alone-through-an-empty-stub-plugin.md"
  - "../adr/0036-post-run-checks-read-the-kept-trace-and-probes-leave-the-harness.md"
---

# Worklog: Evals measure only what a decision needs, per model, with cost and time

> Design + build plan companion to `./eval-measurement.md`.

## Handoff for a fresh session

This section is complete on its own. A session with none of the design context starts here.

**Where you are.** Issue #28 with #49 folded in, a child of the epic #37. The branch and the
journal stream are both `feat/28-eval-measurement`, in the worktree of that name. Run
`journal.py handoff --stream feat/28-eval-measurement` first. You are a teammate of the epic's
lead. Report to the lead with `hc send t2p "<text>"`, never to the user in your pane. When
`hc send` exits 9, the lead's pane shows a dialog: wait and retry, never `--force`.

**Read, in this order.**

1. `../research/2026-11-25-eval-suite-audit.md`: the audit of the 78 cases. Its per-case
   table is the verdict table that PR 2 applies. Its findings explain each repair.
2. `./eval-measurement.md`: the PRD (33 FR, 13 SC, clarified).
3. ADR 0034 (the baseline row), ADR 0035 (the bare arm through a stub plugin) and ADR 0036
   (post-run checks, probe and fixture-only cases, `sets.json`). All three are accepted.
4. This worklog: the Design, the re-baseline plan and the Build Plan below.

**The user's decisions (2026-11-25; journal seq 3586 to 3593 and 3621 to 3623).**

- D1, the 17 cases of the #32 set: staged, bare Fable first. Stage 1 runs only the Fable bare
  arm, 3 runs. A case at 1.00 bare has no lift to show; #32 cuts it together with its
  decision on the skill text. The Fable with arm runs only where the bare arm falls. Opus
  rests on the October rows (`unrecorded`).
- D2, phase events: prose tests of the record steps, and the retro's count over real
  journals. With-only journal graders stay only in 58 and 74.
- D3, the 16 negatives become trigger probes on both models. The probe counts named Bash,
  Agent, Edit and Write calls and records its cost.
- D4, case 77: the computed `ui` flag is the first output line of `hotspots`, unit-tested.
- D5, repair 73 and cut 71. D6, skip 78 until #74. D8, cut 37 and 64.
- D7, the 15 test helpers that start `journal.py` with the inherited environment: the lead
  files a separate issue. They are not part of #28.
- The whole verdict table of the audit is accepted.
- Clarify answers: (1) a bare score below 1.00 from one grader in one run of three gets 3
  more bare runs; it counts as 1.00 only when that grader passes in all 3 new runs; any
  other shortfall is a fall. (2) The run script refuses to start when the paying config dir
  has a plugin of the same name, names the install and the fix, and never edits a Claude
  config dir. (3) A trigger probe passes when all 3 runs match; one miss is a finding to read
  before a description changes.

**The lead's decisions (2026-11-25; journal seq 3645 and 3646).** ADR 0035 is accepted, with a
proof run of case 24 before stage 1 (see the plan). The three PRs below are accepted. #27
builds in parallel and also bumps the shipgate version from 0.36.0, so the lead assigns PR
2's version number at publish time. #27 uses ADR 0032 and 0033; 0034 to 0036 stay.

**Spend rules.**

- PR 1 and PR 2 spend 0 USD. Their tests run a stub `claude` on `PATH` and a fake config
  dir. No eval, no probe and no nested `claude` session.
- PR 3 spends only after the user's go on the re-baseline plan, relayed by the lead and
  recorded in the journal (T040). Each stage runs under its ceiling: the projected cost plus
  25%, from the stage before's measured numbers where they exist.
- The saved results of past runs live in the main checkout's `shipgate/evals/results/`
  (ignored by git). They are private: counts and costs may go into the repo, raw content
  may not.

**What PR 1 must not touch.**

- No case directory (`shipgate/evals/NN-*/`), no `sets.json`, no fixture: PR 2 changes the
  suite.
- No file under `shipgate/scripts/`, `shipgate/skills/`, `shipgate/hooks/` or
  `shipgate/agents/`, no `plugin.json`, no `marketplace.json` and no `CHANGELOG.md`: PR 1
  ships no behaviour and bumps no version.
- No value in `baseline.json`: PR 1 moves the 75 rows under `unrecorded` and changes nothing
  else in them.
- No test helper's environment (D7), and no real Claude config dir in a test.
- No commit, push or PR before a ready review verdict and the user's go for that step,
  relayed by the lead.

**Rules that bind every PR** (root `CLAUDE.md`): the repo is public, so grep the diff for
private names, ids and paths before review; tests run with
`python3 -m unittest discover -s shipgate/tests` from the repo root; scripts stay Python 3.9
compatible; a test that starts `journal.py` gives it a temporary `CLAUDE_CONFIG_DIR`; a
journal append writes its type and payload literally (`--data '{...}'` or a quoted heredoc),
because the command hook refuses a variable or a file there.

**Open elsewhere.** #74 decides case 78. #32 deletes the #32-set cases that score 1.00 bare.
The 15 test helpers: the lead's separate issue.

---

# Design

## Approach

Designed inline, with no architect fan. The harness's limits leave one viable approach for
each part: it has no bare-only mode, no script grader type, and one case glob per call, and
its tag syntax is undocumented. The one real fork, how to run the bare arm alone, is ADR
0035. The lead accepted it, and the PR split, on 2026-11-25.

Core trade-off: the work moves logic out of the harness into small Python modules beside
`compare.py` and `signal_grader.py`. Every new rule is then testable at no cost, and the
harness is only the runner.

## Architecture

| Component | Home | Role |
| --- | --- | --- |
| `compare.py` | `shipgate/evals/` | Reads results, scores under a named rule, compares per case and model, flags efficiency, records rows (ADR 0034). |
| `baseline.json` | `shipgate/evals/` | `cases → model → row`. The 75 old rows sit under `unrecorded`. |
| `evalrun.py` (new) | `shipgate/evals/` | `config-check`: refuses a same-name plugin in the paying config dir, or one that the machine's managed settings enable (T053–T055). `post-run`: the shadow check and the script graders over the kept traces (ADR 0036). `bare-stub`: builds the stub plugin (ADR 0035). |
| `probe.py` (new) | `shipgate/evals/` | Counts skills and named calls in a stream, judges against `probe.json`, saves the result with model, turns, cost and time. |
| `sets.json` (new) | `shipgate/evals/` | The named sets: `kept`, `guards`, `ablation-32`, `probes`, `parked`. |
| `run-case.sh` | `.claude/skills/run-evals/scripts/` | Requires `--ablation` (or `--bare`) and `--model`. Calls `evalrun.py config-check` before the run, `post-run` after it. |
| `run-set.sh` | `.claude/skills/run-evals/scripts/` | Runs a set from `sets.json` serially, one `run-case.sh` after another, under one ceiling per invocation; `--shard k/n` lets a caller start several invocations side by side. Taken out of PR 1 (round 4); task group "Set runner" below. |
| `probe.sh` | `.claude/skills/run-evals/scripts/` | Thin wrapper: scaffold, `claude -p`, then `probe.py`. Takes `--model`. Runs one probe case or the `probes` set. |
| `summarize.py` | `.claude/skills/run-evals/scripts/` | Adds model, mode, cost and time per arm, the shadow mark and the script graders. |
| `signals.py` | `shipgate/scripts/` | `hotspots` puts the `ui` flag first in the JSON and on the first line of the table (FR-025). The only shipped behaviour change. |

The Python modules stay Python 3.9 compatible and use the standard library only.

## Data flow

```
run-set.sh (serial, --shard k/n) (--ablation X | --bare) --model M --max-cost-usd C <plugin-dir> <set>
  └─ per case: run-case.sh (--ablation X | --bare) --model M
       ├─ evalrun.py config-check   → exit 1 before any spend on a same-name install or managed enable
       ├─ [--bare] evalrun.py bare-stub → scratch stub dir; writes bare.json after the run
       ├─ claude plugin eval … --model M --keep-temp --output-dir <own dir> [--max-cost-usd C]
       ├─ evalrun.py post-run <results dir> → shadow.json, script-graders.json
       └─ removes kept scaffold dirs (unless --keep-temp was asked)
compare.py <results…> [--record]
  └─ reads aggregate-result.json + bare.json + shadow.json + script-graders.json
     → scores under the both-arm rule, refuses a cross-model/mode/rule compare,
       flags efficiency and script-grader falls, records rows per case and model
probe.sh --model M <plugin-dir> <NN|probes> → probe.py → results/probes/<stamp>/<case>.json
```

## Data model / schema

`baseline.json` (ADR 0034):

```json
{
  "cases": {
    "02-selective-bug": {
      "unrecorded": {"mode": "with-without", "rule": "both-arm", "with": 0.89, "without": 0.44,
                     "delta": 0.44, "version": "0.15.0", "claude": "2.1.296", "judge": "sonnet",
                     "runs": 3, "results": "2026-10-12T12-01-23-167Z"},
      "claude-fable-5-2": {"mode": "with-without", "rule": "both-arm", "with": 0.0, "without": 0.0,
                           "delta": 0.0, "version": "<tested version>", "claude": "…", "judge": "sonnet",
                           "runs": 3, "results": "…",
                           "cost": {"with": 0.0, "without": 0.0},
                           "seconds": {"with": 0, "without": 0}, "judge_cost": 0.0}
    }
  },
  "note": "…", "updated": "…"
}
```

The values above show the shape only. `probe.json` (per probe case):

```json
{"skill": "structured-debug", "fires": false,
 "zero": {"bash": ["signals\\.py", "codegraph"], "agent": true, "edit": ["docs/", "CLAUDE\\.md"], "write": []}}
```

`fires: true` for the firing probes of 08, 09 and 10. `zero` lists the calls that must not
happen; an empty list means "any call of this tool".

## API / contract changes

- `signals.py hotspots --json`: the key order changes (`ui` first). Parsed JSON is equal.
  The table output gains one first line, `ui: <n> files match ui.globs (<sample>)`, only
  when `ui` is not null. Shipped behaviour: a version bump, with its CHANGELOG entry and
  its tag after the merge.
- `baseline.json`: a new shape, read only inside this repo. No external consumer.
- `run-case.sh`: no default mode and a required model. Every caller in the run-evals skill
  and the README changes with it.

## Reference implementation

`shipgate/evals/signal_grader.py` and its tests (`shipgate/tests/test_signal_grader.py`).
It is the reviewed precedent for a script that reads saved results and traces outside the
harness (ADR 0016): subcommands, `--json`, canned traces in tests, a status that never
changes the harness's. `evalrun.py`, `probe.py` and the script graders mirror its anatomy.
`compare.py` keeps its own structure; `test_compare.py` is the pattern for its new tests.

## Risk ranking of the files the plan changes

From `signals.py hotspots … --json` (source `graph`). `shipgate/evals/` is excluded from
code signals by the repo's setting, so `compare.py` and `signal_grader.py` carry no row.

| File | fix | churn | fan-in |
| --- | --- | --- | --- |
| `shipgate/tests/test_prose.py` | mid | top | low |
| `shipgate/scripts/signals.py` | low | top | low |
| `shipgate/tests/test_signals.py` | low | top | top |
| `.claude/skills/run-evals/scripts/run-case.sh` | mid | high | — |
| `.claude/skills/run-evals/scripts/_common.sh` | low | mid | — |

`signals.py` and `run-case.sh` get a test that pins today's behaviour before they change
(T020, T004).

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/evals/` and `.claude/skills/run-evals/`. One shipped file changes:
  `shipgate/scripts/signals.py`.
- No hook changes. No `/security-review` beyond the routine pass; `evalrun.py` reads the
  paying config dir (read-only, never writes it), which is "reads outside the plugin's own
  directory" in the config's security-sensitive list, so review checks that path.
- Version bump: only for the `signals.py` output (FR-025), in `plugin.json` and
  `marketplace.json`, in the PR that changes it.
- Public repo: results stay ignored. The plan below holds costs only.
- ADR numbers: #27 uses 0032 and 0033; 0034 to 0036 stay (the lead, 2026-11-25).

## PR split (accepted by the lead, 2026-11-25)

1. **PR 1, harness and scripts.** ADR 0034, 0035 and 0036; `compare.py`, `baseline.json`
   migration, `evalrun.py`, `probe.py`, `run-case.sh`, `probe.sh`,
   `summarize.py`, the README and run-evals skill text; their tests. No shipped behaviour
   change, so no version bump.
2. **PR 2, suite changes with their deterministic checks.** The verdict table: cuts, merges,
   repairs, probe and fixture conversions, journal graders, prose tests, fixture dates and
   identity, case 73 and 76, script graders of 22 and 70, `sets.json`; and the `signals.py`
   UI flag with the version bump.
3. **PR 3, the re-baseline.** After the user's go on the plan: the stage runs, `baseline.json`
   rows, the cost table in the README, and the note for #32. No code.

## Re-baseline plan (FR-030; needs the user's go before any spend)

Costs are 3 runs per arm, judge included, in USD. A Fable with-arm cost is measured for 15,
16, 18, 19, 51, 52, 76 and 77, and an Opus with-arm cost for those and for 74. Every other
cost is projected: the default-model cost stands for Opus, and Fable is Opus times 2.08. The
first stage measures what it runs, and the next stage's ceiling uses the measured numbers.

Stages and ceilings (projected cost plus 25%, FR-033):

| Stage | What runs | Projected | Ceiling |
| --- | --- | --- | --- |
| 0 | proof run: case 24, Fable bare arm (`--bare`), 1 run; the set starts only when the trace lists no `shipgate` plugin and no shipgate skill fired | 0.26 | 0.32 |
| 1 | `ablation-32` set, Fable bare arm (`--bare`), 3 runs | 24.83 | 31.04 |
| 1b | each dip case of stage 1: 3 more bare runs (the user's rule) | about 1.46 per case | per case |
| 2 | Fable with arm (`none`) on the cases whose bare arm fell | up to 36.84 (all 17) | from stage 1's list |
| 3 | `kept` set both arms and `guards` with arm, Opus | 43.72 | 54.65 |
| 3 | the same, Fable | 87.77 | 109.71 |
| 4 | `probes` set, 3 runs, Opus then Fable | about 5.70 + 11.90 (not measured) | 7.13 + 14.88 |

Stage 4 starts with three probes per model, measured, before the rest. Case 78 does not run.
The Opus side of the #32 set rests on the `unrecorded` rows (D1).

Per case:

| Case | Set | Decision a fall changes | Arms and mode | Opus | Fable |
| --- | --- | --- | --- | --- | --- |
| 02 | kept | D1, D2 | both arms (`with-without`) | 1.42 | 2.86 |
| 03 | kept | D1, D2 | both arms (`with-without`) | 1.25 | 2.55 |
| 04 | kept | D1, D2 | both arms (`with-without`) | 1.13 | 2.27 |
| 05 | kept | D1, D2 | both arms (`with-without`) | 1.13 | 2.32 |
| 15 | kept (repaired) | D1, D2 | both arms (`with-without`) | 2.32 | 4.73 |
| 16 | kept | D1, D2 | both arms (`with-without`) | 2.57 | 5.08 |
| 17 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.67 |
| 18 | kept | D1, D2 | both arms (`with-without`) | 1.74 | 3.46 |
| 19 | kept | D1, D2 | both arms (`with-without`) | 1.92 | 3.69 |
| 22 | kept | D1, D2 | both arms (`with-without`) | 2.69 | 4.78 |
| 23 | kept | D1, D2 | both arms (`with-without`) | 0.96 | 2.01 |
| 24 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 0.77 |
| 25 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 0.91 |
| 26 | kept | D1, D2 | both arms (`with-without`) | 1.03 | 2.15 |
| 29 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.15 |
| 30 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.22 |
| 31 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.00 |
| 32 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.13 |
| 33 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.29 |
| 36 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.13 |
| 38 | kept | D1, D2 | both arms (`with-without`) | 0.90 | 1.88 |
| 39 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.26 |
| 40 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 0.85 |
| 43 | kept | D1, D2 | both arms (`with-without`) | 1.23 | 2.55 |
| 45 | kept | D1, D2 | both arms (`with-without`) | 1.51 | 3.06 |
| 46 | kept | D1, D2 | both arms (`with-without`) | 1.54 | 3.14 |
| 47 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.08 |
| 48 | guard | D1 (over-spawning is a plugin-only risk) | with only (`none`) | 0.83 | 1.73 |
| 51 | kept | D1, D2 | both arms (`with-without`) | 4.00 | 8.29 |
| 52 | guard | D1 (over-fanning) | with only (`none`) | 1.46 | 3.19 |
| 53 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.07 |
| 54 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.93 |
| 55 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.76 |
| 58 | kept (repaired) | D1, D2 | both arms (`with-without`) | 1.69 | 3.43 |
| 68 | kept | D1, D2 | both arms (`with-without`) | 1.48 | 2.99 |
| 69 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 1.05 |
| 70 | kept (repaired) | D1, D2 | both arms (`with-without`) | 1.98 | 3.92 |
| 73 | kept (repaired) | D2 | both arms (`with-without`) | 2.17 | 4.46 |
| 74 | #32 set | D2 (#32: cut the case and decide the text when the bare arm scores 1.00) | stage 1: Fable bare arm only | — (October row) | 5.58 |
| 76 | kept (repaired) | D1, D2 | both arms (`with-without`) | 4.19 | 7.95 |
| 77 | kept | D1, D2 | both arms (`with-without`) | 2.56 | 5.28 |
| **sum** | | | | **43.70** | **112.62** |

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## PR 1 — harness and scripts

- [x] T001 — Pin today's compare: tests for a `with-without` result against a flat row (score, Δ, the `~` drift mark) — file(s): `shipgate/tests/test_compare.py` — done when: the tests pass on today's `compare.py`
- [x] T002 — Tests first for ADR 0034: row per case and model; migration of flat rows to `unrecorded`; refusal across model, mode and rule (SC-002); efficiency flag at 1.6/0.05, none at 1.4 or |Δ| 0.20 (SC-003); both-arm recompute of a `none` and a `bare` result from grader configs; pairing `bare` + `none` into `mode: bare+none`; recorded version from `suite.plugins`; refusal of a model-less or shadowed run (SC-005) — file(s): `shipgate/tests/test_compare.py` — done when: the new tests fail on today's code
- [x] T003 — Implement ADR 0034 in compare and migrate the 75 rows — file(s): `shipgate/evals/compare.py`, `shipgate/evals/baseline.json` — done when: T001 and T002 pass, and `compare.py` on a saved results dir prints the model and mode columns
- [x] T004 — Pin today's `run-case.sh`: a test with a stub `claude` on `PATH` that records its argv — file(s): `shipgate/tests/test_evalrun.py` — done when: it passes on today's script
- [x] T005 [P] — Tests first for `evalrun.py config-check` (same-name install in `plugins/installed_plugins.json` of any scope, or `enabledPlugins` in `settings.json`; message names the install and the fix; never writes the dir) and `post-run` (shadow from a canned trace's init record, for the with arm and a bare run; script graders run over a canned trace, exit 0/1, results file) — file(s): `shipgate/tests/test_evalrun.py` — done when: the tests fail first
- [x] T006 — Implement `evalrun.py` (`config-check`, `post-run`, `bare-stub`) — file(s): `shipgate/evals/evalrun.py` — done when: T005 passes
- [x] T007 — `run-case.sh`: require `--ablation` or `--bare`, require `--model`, call `config-check` before and `post-run` after, always `--keep-temp` and clean up after, `--bare` through the stub (ADR 0035), print the mode and model; SC-004 tests (no mode, no model, a same-name install: each exits non-zero before the stub `claude` runs) — file(s): `.claude/skills/run-evals/scripts/run-case.sh`, `.claude/skills/run-evals/scripts/_common.sh`, `shipgate/tests/test_evalrun.py` — done when: T004 and the SC-004 tests pass
- [x] T008 [P] — Tests first for `probe.py`: counts of skills, Bash by pattern, Agent, Edit and Write (by path) on a canned stream; judge against a `probe.json` for a negative and a firing probe; saved result with model, turns, cost, time (SC-006) — file(s): `shipgate/tests/test_probe.py` — done when: the tests fail first
- [x] T009 — Implement `probe.py`; `probe.sh` calls it, takes `--model`, runs one probe case or the `probes` set, saves under `results/probes/` — file(s): `shipgate/evals/probe.py`, `.claude/skills/run-evals/scripts/probe.sh` — done when: T008 passes
- [x] T010 — moved out of PR 1 in review round 4 (the user's decision, 2026-11-26): the lane-based `run-set.sh` was built and reviewed, then removed; its regressions came from the lanes and how they stop. The serial runner is task group "Set runner" (T050–T052). The removed script and its tests are kept outside the repo as input, not as a base.
- [x] T011 — Compare shows script-grader pass rates per arm and flags a fall against the row (FR-015); tests — file(s): `shipgate/evals/compare.py`, `shipgate/tests/test_compare.py` — done when: the test passes
- [x] T012 [P] — `summarize.py`: model, mode, cost and time per arm, the shadow mark, script graders — file(s): `.claude/skills/run-evals/scripts/summarize.py` — done when: it prints them on a canned results dir
- [x] T013 — Docs: evals README (modes, bare arm, sets, three case forms, shadow guard, script graders, probes; the run command) and the run-evals skill (commands, gotcha 6 now a guard, the cost rule of thumb replaced by the plan's table until PR 3 measures it) — file(s): `shipgate/evals/README.md`, `.claude/skills/run-evals/SKILL.md` — done when: every command in them matches the scripts
- [x] T014 — Verify PR 1: the full suite — file(s): none — done when: `python3 -m unittest discover -s shipgate/tests` passes

## PR 2 — suite changes with their deterministic checks

- [x] T020 — Pin today's `hotspots` output: the parsed JSON and the table of a small repo with `ui.globs` — file(s): `shipgate/tests/test_signals.py` — done when: it passes on today's `signals.py`
- [x] T021 — Tests first, then the UI flag first in the `hotspots` JSON (first key) and as the first table line when `ui` is not null (SC-010); parsed JSON unchanged; a version bump to the next free version in `plugin.json` and `marketplace.json`, with a CHANGELOG entry (the lead assigns the number at publish time; #27 also bumps from 0.36.0) — file(s): `shipgate/scripts/signals.py`, `shipgate/tests/test_signals.py`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `shipgate/CHANGELOG.md` — done when: T020 and the new tests pass
- [x] T022 [P] — Fixture tests that take over the moved claims: fixture 08 `signals.py suspects src/reports/exportReport.ts --json` ranks `monthRange.ts` first; fixture 10 `hotspots --diff HEAD~1 --json` ranks `promo.ts` and `calendar.ts` first and second; fixture 72 `signal_grader.py fixture --arm graph` gives 59 of 59, skipped without codegraph — file(s): `shipgate/tests/test_eval_fixtures.py` — done when: they pass on the fixtures as they are
- [x] T023 [P] — Prose tests of the record steps (FR-022): clarify's `clarify-passed`, design's `design-committed`, review's `review-verdict` with `ranking` — file(s): `shipgate/tests/test_prose.py` — done when: they pass on today's skills
- [x] T024 — Cuts (D8): delete 37, 64 and 71 — file(s): `shipgate/evals/37-*`, `shipgate/evals/64-*`, `shipgate/evals/71-*` — done when: the directories are gone
- [x] T025 — Merges, checked by scenario: 01 into 58 (a one-claim LLM grader "says why it slipped through"); 44 into 70 (a recorded INFO-logging deviation with a revisit date 30 days ahead, as 46 does, and 44's `deviation-not-relitigated` regex) and 46; delete 01, 44, 59, 60, 61, 62, 63, 65 and 66 — file(s): `shipgate/evals/58-*`, `shipgate/evals/70-*`, the deleted directories — done when: the grader files exist and the directories are gone
- [x] T026 — Probe conversion: the 16 negatives and 08, 09 and 10 keep `fixture.sh`, get `probe.md` (the prompt) and `probe.json` (from their old `tool_used` and file graders: 41 counts Edit and Write on repo docs; 34 Bash `signals.py`; 42 Edit and Write; 50 Agent; 57 Edit; 11 Bash `signals.py` and `codegraph`; 27 Bash; 28 Bash `unittest`; 49 Agent; 67 Bash `journal.py`), and lose `prompt.md`, `case.yaml` and `graders/`; a test checks every `probe.json` against that table — file(s): the 19 probe directories, `shipgate/tests/test_eval_fixtures.py` — done when: the test passes and the harness's case list holds none of them
- [x] T027 — Fixture-only conversion: 13 and 72 keep `fixture.sh` and `expected.json` only; delete 12, 14 and 75 — file(s): those directories — done when: `test_signal_grader.py` and T022 still pass
- [x] T028 [P] — Journal graders (FR-021): 58 drops `journal-any-event-appended` and `journal-no-invented-types`, its phase-event grader becomes `(debug-root-cause|bug-reproduced)` with `arm: with-only`; 74's `journal-verdict-appended` gets `arm: with-only`; tests of both in `test_eval_graders.py` — file(s): `shipgate/evals/58-*/graders/`, `shipgate/evals/74-*/graders/`, `shipgate/tests/test_eval_graders.py` — done when: the tests pass
- [x] T029 [P] — Fixture dates (FR-023): the revisit date of `fixtures/bigshop.py` and its embedded copies in 58 and 67 computed 30 days ahead at scaffold time; a test fails on a literal deadline date (`revisit|until|expires|deadline` before a `YYYY-MM-DD`) in any fixture — file(s): `shipgate/evals/fixtures/bigshop.py`, `shipgate/evals/58-*/fixture.sh`, `shipgate/evals/67-*/fixture.sh`, `shipgate/tests/test_eval_fixtures.py` — done when: the test passes
- [x] T030 [P] — Git identity (FR-024): 15, 17, 18 and 19 set a repo-local `user.name` and `user.email`; a test checks every clarify-case fixture — file(s): those four `fixture.sh`, `shipgate/tests/test_eval_fixtures.py` — done when: the test passes
- [x] T031 [P] — Case 73 (FR-026): remove the giveaways (commit subjects about policies and flaky upstreams, the doc comment on the doubling pause, the word `attempts`, the two callers of `withPolicy`); the fixture asserts over file text and commit subjects; a test scaffolds it offline and greps for `retry|backoff|exponential|attempt|flak|5xx` — file(s): `shipgate/evals/73-*/fixture.sh`, `shipgate/tests/test_eval_fixtures.py` — done when: the test passes
- [x] T032 [P] — Case 76 (FR-027): split `batch-items-risky` into one grader per claim and drop "at most 4" — file(s): `shipgate/evals/76-*/graders/` — done when: two grader files replace one
- [x] T033 [P] — Case 15: `exec-hygiene` becomes regex graders (the "Assumptions (executive)" heading with an item line holding `→`; a non-empty non-goals section), tested in `test_eval_graders.py` — file(s): `shipgate/evals/15-*/graders/`, `shipgate/tests/test_eval_graders.py` — done when: the tests pass
- [x] T034 [P] — Script graders: 22's "last test run after the last edit of `pricing.py`" over the trace replaces its trace LLM judge; 70's "no sentence over 40 words" replaces claim 1 of `readable`, and a regex for inline code replaces claim 3; `readable` goes; tests with canned traces — file(s): `shipgate/evals/22-*/script-graders/`, `shipgate/evals/70-*/script-graders/`, `shipgate/evals/70-*/graders/`, `shipgate/tests/test_eval_graders.py` — done when: the tests pass
- [x] T035 — `sets.json` and its test (SC-007): `kept` (17 + 5 repaired), `guards` (48, 52), `ablation-32` (17), `probes` (19), `parked` (78); the eval sets cover exactly the harness's 42 cases and do not overlap — file(s): `shipgate/evals/sets.json`, `shipgate/tests/test_eval_fixtures.py` — done when: the test passes
- [x] T036 — Evals README: the "What the cases measure" table and the code-graph section follow the new suite — file(s): `shipgate/evals/README.md` — done when: every case it names exists
- [x] T037 — Verify PR 2: the full suite (SC-008) — file(s): none — done when: `python3 -m unittest discover -s shipgate/tests` passes

## Set runner — a later PR, before PR 3's paid stages

Taken out of PR 1 in review round 4. The lane version regressed three rounds in a row, every
time in how lanes stop. This one has no lanes.

- [x] T050 — Tests first, with the stub `claude`: `run-set.sh` runs the cases of a set from a sets file one after another (one `run-case.sh` at a time, in the foreground), passes the mode, `--model` and the full case name, requires `--max-cost-usd C` (one ceiling per invocation: before each case it sums the spend so far and stops at C), refuses the `parked` set through `evalrun.py set-cases`, and with `--shard k/n` runs only the cases whose index in the set is k modulo n — file(s): `shipgate/tests/test_evalrun.py` — done when: the tests fail first
- [x] T051 — Implement the serial `run-set.sh`: no lanes, no trap, no process group, no background job, so a Ctrl-C stops the running case whole with its `claude` child; the spend sum is the smallest helper that the tests need — file(s): `.claude/skills/run-evals/scripts/run-set.sh`, `shipgate/evals/evalrun.py` — done when: T050 passes
- [x] T052 — Docs: README and the run-evals skill show the serial form and the shards (a caller starts `--shard 1/3`, `--shard 2/3` and `--shard 3/3` side by side, each with its own ceiling) — file(s): `shipgate/evals/README.md`, `.claude/skills/run-evals/SKILL.md` — done when: every command in them matches the script

## Managed-settings guard — found by stage 0, before any spend (the lead's brief, 2026-11-26)

Stage 0 stopped at the pre-run check. Every local config dir has shipgate installed, and the
machine's managed settings enable it for every config dir. `config-check` did not read the
managed settings, so a fresh config dir would have passed it and every run would have been
shadowed.

- [x] T053 — Tests first: `config-check` refuses a plugin of the tested name that the managed settings enable (`managed-settings.json`, then `managed-settings.d/*.json` in name order, no hidden file; a later file wins), names the file and the fix, never writes it, and takes the path from `--managed-settings` or `EVALRUN_MANAGED_SETTINGS` (never the real file in a test); the platform paths; `run-case.sh` refuses in every mode, `--bare` included — file(s): `shipgate/tests/test_evalrun.py` — done when: the tests fail first
- [x] T054 — Implement it in `evalrun.py` — file(s): `shipgate/evals/evalrun.py` — done when: T053 passes
- [x] T056 — Tests first, then `make_scratch_home` links `~/Library/Keychains` and the security plist into the scratch HOME when they exist, and nothing else, so a keychain-backed login authenticates (the eval-only config dir of the user's choice is one); docs in the README and gotcha 2 of the run-evals skill — file(s): `.claude/skills/run-evals/scripts/_common.sh`, `shipgate/tests/test_evalrun.py`, `shipgate/evals/README.md`, `.claude/skills/run-evals/SKILL.md` — done when: the tests pass
- [x] T057 — Tests first, then `run-case.sh --bare` passes `--trust-plugin`, and no other mode does (the lead's choice after the first stage-0 attempt); one README line says why; ADR 0035 and the PR 1 Deviations line corrected — file(s): `.claude/skills/run-evals/scripts/run-case.sh`, `shipgate/tests/test_evalrun.py`, `shipgate/evals/README.md`, ADR 0035 — done when: `test_evalrun.py` passes
- [x] T058 — Tests first, then the bare stub holds a copy of the evals dir (no `results/`, no `__pycache__`) in place of a link, which the harness refuses; a link in evals stays a link only when it is relative and stays inside, else the stub is refused with the link named; the test plugin copies `evalrun.py` in place of linking it; ADR 0035, the README and the skill say copy — file(s): `shipgate/evals/evalrun.py`, `shipgate/tests/test_evalrun.py`, ADR 0035, `shipgate/evals/README.md`, `.claude/skills/run-evals/SKILL.md` — done when: `test_evalrun.py` passes
- [x] T059 — Tests first, then post-run's clean-up removes a sealed kept sandbox (the harness keeps it read-only, 500, with a `sealed/` dir at 000; `rmtree(ignore_errors=True)` removed nothing and still counted it) and names any sandbox it could not remove — file(s): `shipgate/evals/evalrun.py`, `shipgate/tests/test_evalrun.py` — done when: `test_evalrun.py` passes
- [x] T055 — Docs: the README's shadow guard, the run-evals skill (the config-check line and gotcha 6) and the headers of `run-case.sh` and `probe.sh` say that a managed enable shadows every config dir — file(s): `shipgate/evals/README.md`, `.claude/skills/run-evals/SKILL.md`, `.claude/skills/run-evals/scripts/run-case.sh`, `.claude/skills/run-evals/scripts/probe.sh` — done when: the full suite passes

## PR 3 — the re-baseline (only after the user's go on the plan)

- [ ] T040 — Put the plan above to the user through the lead with the measured numbers of PR 1 and 2; record the go — file(s): none — done when: the journal holds the user's go (SC-011)
- [x] T041 — Stage 0, the proof run of case 24 (`run-case.sh --bare --model claude-fable-5-2`, 1 run): the trace lists no `shipgate` plugin and no shipgate skill fired; `report.html` and `aggregate-result.json` land in the `--output-dir` that `run-case.sh` passed, and post-run finds the kept traces from it (`shadow.json` holds no `null` run); only then stage 1 and 1b, the serial `run-set.sh --bare --model claude-fable-5-2 --max-cost-usd C shipgate ablation-32` (T050–T052; up to 3 shards side by side, each with its share of the ceiling), and the dip rule — file(s): none — done when: the proof held, the stage list of fallen cases exists, and stage 1 stayed under its ceiling (SC-013)
- [ ] T042 — Stage 2 on the fallen cases, with the serial `run-set.sh` (`--ablation none`) or one `run-case.sh` per case — file(s): none — done when: each has a `bare+none` row
- [ ] T043 — Stage 3, the `kept` and `guards` sets on Opus and on Fable, with the serial `run-set.sh` in shards — file(s): none — done when: both models ran under their ceilings
- [ ] T044 — Stage 4, the `probes` set on both models; three probes per model first, to measure — file(s): none — done when: every probe has a saved result per model
- [ ] T045 — Record: `compare.py --record` per model; the README's cost table from the measured numbers; an addendum to the audit note for #32 (the cases at 1.00 bare, the cases with a Δ) — file(s): `shipgate/evals/baseline.json`, `shipgate/evals/README.md`, `shipgate/docs/research/2026-11-25-eval-suite-audit.md` — done when: SC-001 and SC-012 hold

## Traceability

- FR-001, FR-002, FR-003 → T002, T003
- FR-004, FR-005, FR-006, FR-007 → T002, T003
- FR-008, FR-009 → T004, T007
- FR-010 → T005, T006, T007, T053, T054, T055
- FR-011 → T005, T006, T007, T002
- FR-012 → T006, T007 (ADR 0035)
- FR-013 → T050, T051, T035 (T010 moved out of PR 1)
- FR-014 → T005, T006, T034
- FR-015 → T011
- FR-016, FR-017, FR-018 → T008, T009, T026
- FR-019 → T024, T025, T026, T027, T032
- FR-020 → T022, T023, T026, T027, T033, T034
- FR-021 → T028
- FR-022 → T023
- FR-023 → T029, T025
- FR-024 → T030
- FR-025 → T020, T021
- FR-026 → T031
- FR-027 → T032
- FR-028 → T035
- FR-029 → T013, T036
- FR-030 → this plan, T040
- FR-031, FR-032 → T041, T042, T043, T044, T045
- FR-033 → T041, T043, T044
- SC-001, SC-012 → T045
- SC-002, SC-003, SC-005 → T002
- SC-004 → T007
- SC-006 → T008
- SC-007 → T035
- SC-008 → T037
- SC-009 → T029
- SC-010 → T021
- SC-011 → T040
- SC-013 → T041, T043, T044

## What changed

- `signals.py hotspots` shows the UI flag first: the first key of `--json`, and the first table line when `ui.globs` is set (shipgate 0.38.0).
- The eval suite has 42 harness cases in named sets (`evals/sets.json`), 19 trigger probes and 2 fixture cases; cuts and merges removed 15 cases.
- Claims that a script can judge moved out of the paid runs (the signals rankings, the record steps, case 15's assumptions, case 22's run order, case 70's sentence length); no fixture date can expire, the clarify fixtures set their own git identity, and case 73 no longer gives its helper away.
- `run-set.sh` runs the cases of a named set one after another under one required cost ceiling per invocation; `--shard K/N` splits a set into invocations side by side, and Ctrl-C stops the running case with its `claude` child and starts no further case.
- `run-case.sh` makes its own results dir and passes it as `--output-dir`, so runs side by side never read or clean another run's results; it refuses to start, before any spend, when the machine's managed settings enable the plugin under test, because that enable shadows every config dir.

## Deviations & notes (filled during implementation)

- 2026-11-25, PR 1, the with-only rule (journal seq 3652). ADR 0034 said the both-arm rule
  leaves out "a `tool_used` grader for `Skill` with no `min` or `max`". The saved results
  show another rule. The harness marks a grader with-only when its config has
  `arm: with-only`, or when it is a `tool_used` grader for `Skill` and its config has no
  `arm: both`. `min` and `max` do not matter. The build uses the observed rule, and ADR
  0034 now states it.
- 2026-11-25, PR 1, `--trust-plugin`. ADR 0035's bare command names `--trust-plugin`.
  `run-case.sh --bare` does not pass it: no run may check the flag at no cost, and the
  with-without runs work without it. The proof run of case 24 (T041) shows whether the
  stub needs it. Pass it as an extra eval flag there; then fix the script or the ADR in
  one line. Settled 2026-11-26: the first stage-0 attempt was refused as an untrusted
  plugin dir before any agent ran (0 USD), so `run-case.sh --bare` now passes
  `--trust-plugin`, and only in that mode (the lead's choice (b); pinned by a test).
  The second attempt was refused too: the harness refuses an `evals` link that points
  outside the plugin, so the stub now holds a copy (T058, the lead's choice (b')). It also
  showed that the harness seals kept sandboxes, which post-run's clean-up could not remove
  (T059).
- 2026-11-25, PR 1, additions beyond the plan: `evalrun.py set-cases` (the set rules get
  unit tests; it refuses `parked`, a set that holds a parked case, an empty set and an
  unknown set), `evalrun.py spent` (the ceiling sum of `run-set.sh`; removed with it in
  round 4), and `post-run --script-timeout`. `run-case.sh` refuses a mode or model flag among the extra
  eval flags, so the recorded mode is the one that ran.
- 2026-11-25, PR 1, probe additions: `probe.py check` validates every `probe.json` before
  any spend, and `probe.sh` takes its flags in any position. `probe.sh` keeps today's
  `--allowedTools` list, which holds no `Agent`. So `zero.agent` counts attempted Agent
  calls. PR 2 decides for the probes of 49 and 50 whether `Agent` joins the list.
- 2026-11-25, PR 1, compare. `--against MODEL` is the way to ask for another model's row,
  and compare refuses it (SC-002, model side). A result with no recorded model is refused,
  so every result saved before this change is refused. `--record` writes the rows that are
  not refused and still exits 3. A one-arm row (`none`, `bare`) keeps the other arm as
  null, and its ΔΔ reads the score of that one arm. A paired row's `runs` is the smaller
  run count of the two results. The baseline `note` now describes the row shape.
- 2026-11-25, PR 1, a fix found by the T013 doc check. When the harness printed no
  `Report:` line, `run-case.sh` exited 1 with no message: its `grep` failed under
  `pipefail`, and `set -e` stopped the script. That predates PR 1. It skipped the fallback
  listing, the post-run checks and the clean-up, and it hid the harness's own status. Two
  tests pin the fix (an aborted harness keeps its status; no `Report:` line falls back to
  the listing).
- 2026-11-26, set runner, two stops the plan did not name. (1) On macOS bash 3.2 a
  serial loop starts the next case after Ctrl-C when the child catches SIGINT and exits
  130: bash then takes the signal as handled. So a case that exits above 128 stops the
  set with its status. A test pins it with a stub that exits 130 on SIGINT. (2) A case
  that leaves no results dir stops the set with exit 1, because the ceiling cannot count
  its spend. Neither is a trap. `evalrun.py spent` is back as the ceiling sum. The set
  runner does no config check of its own: each `run-case.sh` makes it.
- 2026-11-26, set runner, the lead's change by removal. `run-case.sh` no longer takes a
  results dir from a before/after listing of the results root when the harness prints no
  `Report:` line. With shards side by side, that listing could pick another shard's dir.
  Now a run with no `Report:` line has no results dir: the script says so with the harness
  status, and `run-set.sh` stops the set. This reverses the round 1 rejection of
  `run-set.sh:125`. Four tests pin it, and each fails on the old script.
- 2026-11-26, set runner, option (b) built (the user's choice "Pass --output-dir",
  relayed by the lead; journal seq 3920). `run-case.sh` owns its results dir: a new dir
  under `evals/results/`, named by the UTC time with milliseconds (the harness's own form,
  so `compare.py`'s order by name holds) and the script's process id. It passes the dir as
  `--output-dir` and refuses a caller's own. The `Report:` line parse, the `--report`
  refusal and the bare-run path mapping are gone, and so is the README's same-millisecond
  note. `mkdir` makes the dir before the run and fails on an existing name. The harness
  refuses only an existing default dir; a dir given with `--output-dir` it writes into
  (read from the harness 2.1.332 bundle, round 4). Stage 0 checks the layout (T041).
- 2026-11-26, set runner, deferred (R4-8, the lead's decision): `run-case.sh` does not
  refuse an extra `--eval-dir`. The harness would then read cases from another dir while
  the script checks the case and writes results under `evals/`. No refusal is added now.

### PR 2 — the merges, checked by scenario (T025)

The orchestrator read the prompt and every grader of both sides of each merge. Each pair
judges the same scenario. The table names what moved, what is lost, and what keeps the claim.

| Merged | Into | Moved | Lost | Who keeps the claim |
| --- | --- | --- | --- | --- |
| 01 | 58 | the claim "says why it slipped through", as the one-claim LLM grader `says-why-it-slipped-through` | the small-repo variant of the same regression | 58 judges every other claim of 01 |
| 44 | 70, 46 | a recorded INFO-logging deviation with a revisit date 30 days ahead (46's mechanism), `log.info` in the export at HEAD, the DEBUG rule in CLAUDE.md, 44's `deviation-not-relitigated` regex, and its claim "does not raise the deviation" as the one-claim judge `deviation-not-raised` (review round 1, F3) | nothing more | 70 keeps the two planted bugs of 44 (CSV quoting, SQL interpolation); 46's LLM judge `no-invented-findings` keeps the claim in a clean diff |
| 59 | 02 | nothing | `cites-adr-0006` (passes in both arms), the large-repo variant | 02 (stronger: the fx red herring, the credit note); 58 keeps the debug event |
| 60 | 29 | nothing | `cites-adr-0005` (passes in both arms), the route-and-map journal event | 29; the record step: `TestRecordSteps` in `test_prose.py` |
| 61 | 32 | nothing | the route-and-map journal event | 32; `TestRecordSteps` |
| 62 | 70 | nothing beyond 44's deviation | the unknown-order finding (an empty row raises IndexError, not a 404), the review-verdict journal event | 70 keeps the SQL interpolation; 48 keeps a crash-on-missing-input finding; 74 keeps the verdict event; `TestRecordSteps` |
| 63 | 47 | nothing | the large-repo variant, the review-verdict journal event | 47 (the same header regression in a fix commit); `TestRecordSteps` |
| 65 | 17 | nothing | `delivery-via-worker` (passes in both arms), `no-due-date-rebuild` (a regex form of the claim that 17's LLM judge `grounded-in-existing-code` holds), `journal-fr-count`, the clarify-passed event | 17; `TestRecordSteps` |
| 66 | 54 | nothing | `reuses-is-overdue` (passes in both arms), the design-committed event | 54 (`cites-adr-0002` is the same claim as 66's `cites-adr-0003`); 51 keeps `tests-as-tasks`; `TestRecordSteps` |

- T029 covers five more fixtures than the plan named: 45, 47, 48, 49 and 50 carried the
  same expired "revisit 2026-10-05" as 44. FR-023 asks for no such date in any eval fixture,
  so they now compute the date 30 days ahead, as 46 does. `fixtures/bigshop.py` is no
  generator: 58 and 67 embed a verbatim copy, and all three got the same edit.
- T030's test covers the clarify cases with a `prompt.md` (15 to 19 and 76 to 78). The
  negatives 20 and 21 become trigger probes, where no clarify pass runs.
- T031: `withPolicy` has no caller now, and the field `attempts` is `calls`. Its body still
  loops with a doubling pause, so a reader of the code finds it.
- T028: the seeds hold no debug event in 58 and no review-verdict in 74, so the date-free
  patterns match only a row the run appends. Tests run each real fixture offline and check it.
- T032: 76's judge became three one-claim judges (`batch-put-to-user`,
  `batch-items-user-facing`, `batch-items-alternative`), each at the default weight 1.
- T033: 15's regex graders ask for at least one answered item with a reason
  (`assumptions-answered`), not for each item: one regex cannot read every item. The
  non-goals regex also reads the template's bold `**Non-goals**` label.
- T034: 22's script grader `last-test-after-last-edit` fails a run with no test run. 70's
  `no-sentence-over-40-words` drops the judge's softer "mostly about 20 words" target.
  70's `locations-inline-code` asks for the three file names in code form; commands and
  error text in code form are lost, because a regex cannot tell them from prose.
- T026, the probe table. `probe.json` can only ask that a count is 0. So 28 keeps "verify
  does not fire" and loses "exactly one `unittest` run" (the plan's line names `unittest`).
  67 keeps `route-and-map` only; 20's probe keeps clarify on a one-line change. Five old
  file claims became zero counts the plan did not list: 35 Edit; Write under
  `app/docs/prd/` in 20 and 21, `app/docs/adr/` in 56, `app/docs/` in 57. 41 counts Edit
  and Write on `app/docs/` and `app/CLAUDE.md` only, so a note in the user's own memory is
  no false fail. The answer-text and file-content graders of the 19 cases are gone by D3.
  `probe.sh` keeps its tool list with no `Agent`, so 49 and 50 count attempted Agent calls.
- T022 pins 08 and 10 with `--graph off`: with codegraph the order is the same, and the
  test then needs no index. The 72 test skips without codegraph on `PATH`.
- Open, outside PR 2: `signal_grader.py fixture` fails on a relative case dir (the README
  form); its docstring still names the prompts of 13 and 72; `baseline.json` keeps the
  `unrecorded` rows of removed, probe and fixture cases until PR 3; `run-case.sh` keeps its
  `expected.json` branch, which no eval case reaches now.
- 70's `facts-retained` names `export.py` line 18, not 16: the new import and `log.info`
  line move the f-string row down two lines. A scaffold of the fixture shows it.
- FR-022 says a route-and-map record-step test exists. No test pinned it, so
  `TestRecordSteps` pins route-and-map too.
- 2026-11-26, managed-settings guard (T053–T055, the lead's brief after stage 0 stopped).
  `config-check` now also reads the platform's managed settings file and the `*.json`
  files of `managed-settings.d/` beside it. A managed enable loads the plugin in every
  config dir, so the fix there is not "a config dir without the plugin", as clarify
  answer (2) says. The fix is to disable the plugin in the managed file, which needs
  admin rights; the check never edits the file. MDM profiles, the Windows registry and
  server-managed settings are not read; post-run's shadow check still sees what they load.
- 2026-11-26, stages 0, 1 and 1b (T041), Fable bare arm, the user's go of seq 4018.
  Stage 0 held on the third attempt (0.41 USD; the first two were refused at 0 USD, see
  T057 and T058). Stage 1: 17 cases, 3 runs each, 3 shards, 22.12 USD against a 31.04
  ceiling (projected 24.85, ratio 0.89). Stage 1b: 29 and 55, 3.43 USD against 12.00. At
  1.00 bare: 17, 25, 29 (after 1b), 30, 31, 32, 33, 36, 39, 40, 54, 69. Fell: 24, 47, 53,
  55 (the dip grader failed again in 1b) and 74. These five go to stage 2.
- 2026-11-26, plan change for stage 3 (the user's go "Both models, bare", relayed by the
  lead). The bare arm of the `kept` set runs on both models first, through `run-set.sh
  --bare`; the with arm (`none`) follows on a later go. Each kept row is then a `bare+none`
  pair (ADR 0034), not one `with-without` run: the same arms, the same cost, the same
  information, and the bare half does not depend on the plugin version.
- 2026-11-26, a candidate, not built: a post-run flag for a run whose graded last message
  is far shorter than an earlier assistant message of the same run (case 74, run 3). It is
  a flag to read, never a verdict. Until it exists, every result table carries that count
  per case, from the kept traces where a run kept them.
- 2026-11-26, a T045 rule for the stage-1b cases (29, 55). `compare.py` takes the newest
  results dir per case, model and mode, so it reads only the 3 runs of the 1b dir. Pooling
  the two dirs needs a marker that tells an extension from a rerun that supersedes, and a
  merge of the run lists: about 40 lines in `run-case.sh` and `compare.py` plus tests, so it
  is a rule, not a fix. Rule: T045 records a 1b case from its 1b dir (3 runs). That row is
  the verdict of the user's rule (1.00 only when the dip grader passes all 3 new runs). The
  audit addendum names both dirs and the pooled 6-run mean: 29 0.97, 55 0.89.

## Review round 1 (PR 1)

Workflow run `wf_fd27b536-7cd`, 3 lenses on Opus: 38 found, 35 after dedupe, 12 above the
floor of 60, 0 BLOCKER or HIGH, so no refuter ran. The orchestrator read each survivor's
code. A briefed security reviewer read all 21 changed files and found nothing. Verdict:
not ready. The fix round takes F1 to F9.

- F1 MEDIUM `shipgate/evals/evalrun.py:223` — A script grader that crashes exits 1, so post-run records a fail, not an error.
- F2 MEDIUM `.claude/skills/run-evals/scripts/probe.sh:53` — probe.sh parses the probes set with its own Python instead of `evalrun.py set-cases`, so it skips the parked, empty and unknown-set refusals.
- F3 MEDIUM `shipgate/evals/compare.py:152` — compare and `--record` accept a results dir with no shadow.json, and a bare run whose post-run never ran is recorded as a with-arm `none` row.
- F4 MEDIUM `.claude/skills/run-evals/scripts/run-set.sh:138` — A killed run-set.sh leaves its background lanes running, and they keep spending.
- F5 MEDIUM `.claude/skills/run-evals/scripts/run-set.sh:120` — run-set.sh runs a whole set with no ceiling when `--max-cost-usd` is left out (promoted from below the floor; FR-033 asks for a ceiling on every stage).
- F6 LOW `shipgate/evals/evalrun.py:369` — set-cases accepts a case listed twice, so run-set.sh runs and pays for it twice.
- F7 LOW `.claude/skills/run-evals/scripts/probe.sh:131` — probe.sh does not check `runs` and `max-turns`; `runs=0` crashes on an empty array under bash 3.2.
- F8 LOW `.claude/skills/run-evals/scripts/run-set.sh:135` — run-set.sh passes only the NN prefix, so two case dirs with one prefix both run (FR-013).
- F9 LOW `shipgate/evals/compare.py:88` — The both-arm recompute scores an errored run 0, but the harness scores it from its graders.
- D1 LOW `.claude/skills/run-evals/scripts/run-set.sh:36` — run-set.sh repeats run-case.sh's mode and model parsing (deferred: run-case.sh refuses on its own as well, so a drift costs no spend).

### Rejected findings

- `.claude/skills/run-evals/scripts/probe.sh:51` (LOW 75): the same claim as F2, merged into it.
- `shipgate/evals/evalrun.py:130` (LOW 60): exit codes differ from signal_grader.py; every caller stops on any non-zero code, and the docstring states each code, so a change buys nothing.

## Review round 2 (PR 1)

One Opus reviewer with all lenses re-read the fixes. F1 to F9 are confirmed fixed, each
pinned by a named test. The orchestrator closed one F1 gap (a top-level `SyntaxError`) with
a test first. The fixes opened two MEDIUM regressions, and the round found 12 LOW findings.
Verdict: not ready. The round found more than it fixed, so the open list went to the lead
(the two-round cap).

- R2-1 MEDIUM `.claude/skills/run-evals/scripts/run-set.sh:138` — Under `set -m` (F4) each lane is its own process group, so SIGHUP or a group kill of the script leaves the lanes running and spending.
- R2-2 MEDIUM `shipgate/evals/compare.py:164` — `--record` replaces a `bare+none` row with a half `bare` row when the partner dir of the pair is refused (no shadow.json, F3, or shadowed).
- R2-3 LOW `shipgate/evals/evalrun.py:232` — A top-level IndentationError or TabError in a script grader still counts as a fail with an empty reason.
- R2-4 LOW `shipgate/evals/evalrun.py:229` — A grader that ends with `sys.exit("message")` is a fail with an empty reason; the reason sits on stderr.
- R2-5 LOW `shipgate/evals/compare.py:153` — Without `--record`, a bare run whose post-run never ran still shows as a `none` row; the warning does not say the mode may be wrong.
- R2-6 LOW `.claude/skills/run-evals/scripts/run-case.sh:69` — An empty `<NN>`, `.`, `..` or `results` passes the full-name rule (F8); an empty one gives `--case ""`.
- R2-7 LOW `.claude/skills/run-evals/scripts/run-set.sh:146` — Between batches a signal can pair the new case names with the reaped PIDs of the last batch.
- R2-8 LOW `.claude/skills/run-evals/scripts/run-set.sh:135` — A signal after the last batch prints a negative "not started" count.
- R2-9 LOW `.claude/skills/run-evals/scripts/run-case.sh:100` — A stopped lane leaves its kept sandboxes in the temp dir, and the stop message does not say so.
- R2-10 LOW `.claude/skills/run-evals/scripts/run-set.sh:140` — Ctrl-Z stops only the script; the lanes keep running.
- R2-11 LOW `.claude/skills/run-evals/scripts/probe.sh:64` — probe.sh does not take a full case name, but run-case.sh does now.
- R2-12 LOW `shipgate/evals/README.md:184` — The README and the worklog data flow show `run-set.sh` with no ceiling, which now exits 64.
- R2-13 LOW `shipgate/evals/evalrun.py:25` — One docstring line is over the wrap width.
- R2-14 LOW `shipgate/evals/compare.py:164` — Every results dir from before this change has no shadow.json, so `--record <results root>` refuses each old dir and exits 3, and plain compare prints one warning per old dir.

## Review round 3 (PR 1)

The user chose "round 3 by removal" (relayed by the lead, 2026-11-26). One worker removed
the process-group stop, made `--record` skip every key with a refusal, set the script-grader
contract (exit 1 needs a stdout reason to be a fail), tightened the full-name rule to the
eval-case form, and made compare report a flawed results dir only when it would use it. The
orchestrator marked the two shadowed case-77 dirs and corrected the audit note, the PRD and
the cost line. One Opus reviewer read the fix diff only. It confirmed every spec item, and
found 3 new MEDIUM findings and 8 LOW. Verdict: not ready. Under the lead's rule (a new MEDIUM
in round 3), the list went to the lead with no further fix. Deferred from round 2: R2-5 (the
unchecked-dir warning does not say the mode may be wrong), R2-9 (a stopped lane leaves its
sandboxes) and R2-11 (probe.sh takes no full case name).

- F1 MEDIUM `.claude/skills/run-evals/scripts/run-case.sh:99` — A stopped lane's EXIT trap removes its scratch HOME and bare stub at once, while its `claude` child runs on; post-run never runs, so the results dir has no shadow.json and, in bare mode, the results may be lost.
- F2 MEDIUM `shipgate/evals/README.md:127` — The docs say a crash is always an error, but a grader that prints a line and then crashes is a fail under the contract; the test that showed it lost its print.
- F3 MEDIUM `shipgate/docs/research/2026-11-25-eval-suite-audit.md:337` — The note says 4 Fable without runs of case 77; there are 2 (the old "2/4" counted grader passes).
- F4 LOW `shipgate/evals/compare.py:264` — A model-less dir is skipped when any newer pick of its case exists, of any model; the docstring and the docs say "same case and model".
- F5 LOW `shipgate/docs/research/2026-11-25-eval-suite-audit.md:351` — The addendum calls the loaded copy both the tree under test and the installed copy; the trace shows the installed marketplace copy, whose path is the tree.
- F6 LOW `.claude/skills/run-evals/SKILL.md:141` — Three new prose lines break the wrap width (SKILL.md:141 and :154, README.md:72).
- F7 LOW `shipgate/evals/compare.py:171` — The "no trace to check" warning still prints for an old dir that compare does not use.
- F8 LOW `.claude/skills/run-evals/scripts/run-set.sh:167` — A signal between a lane's launch and its `pids+=` leaves that lane unstopped and counted as not started.
- F9 LOW `.claude/skills/run-evals/scripts/run-set.sh:137` — On a real hangup a failed `printf` under `set -e` can end the trap with exit 1, not 129.
- F10 LOW `.claude/skills/run-evals/scripts/run-set.sh:24` — The ceiling bounds one invocation; an orphaned `claude` of a stopped set spends outside the next set's ceiling.
- F11 LOW `shipgate/tests/test_compare.py:372` — No test covers a model-less partner under `--record`.

## Review round 4 (PR 1)

The user chose "Take run-set.sh out" (relayed by the lead, 2026-11-26): every code regression
of rounds 1 to 3 but one came from the lanes and how they stop. One worker removed
`run-set.sh`, its tests and `evalrun.py spent`, and fixed F2, F4, F6, F7 and F11. Nothing in
`run-case.sh` was lane-only, so it stays a plain foreground pipeline, and F1 has no path
left. The orchestrator fixed F3 and F5 in the audit note, planned the serial runner (task
group "Set runner", T050 to T052, named by PR 3's stages), and marked T010 moved. F8, F9 and
F10 lived in `run-set.sh` and close with its removal. One Opus reviewer read the fix diff
only: every spec item holds, no BLOCKER, HIGH or MEDIUM, and 9 LOW. The orchestrator fixed
seven of them; two are rejected below. Verdict: ready. The fresh full suite ran in three
parts: 759 + 1111 + 636 = 2506 tests, OK, 2 skipped.

- L1 LOW `shipgate/evals/evalrun.py:23` — The docs gave the wrong reason why a print before a crash survives (Python flushes stdout at exit, after the traceback); fixed in the docstring and the README.
- L2 LOW `shipgate/docs/research/2026-11-25-eval-suite-audit.md:351` — New prose lines over the wrap width (the audit note, ADR 0036, the worklog); rewrapped.
- L3 LOW `shipgate/docs/research/2026-11-25-eval-suite-audit.md:353` — Two "So" sentences in a row; joined.
- L4 LOW `shipgate/docs/prd/eval-measurement.worklog.md:331` — The moved T010 line had no box; it is `- [x]` again, with its task-done on record.
- L6 LOW `shipgate/docs/adr/0036-post-run-checks-read-the-kept-trace-and-probes-leave-the-harness.md:60` — The ADR described the removed runner in the present tense; reworded as the later serial runner.
- L7 LOW `shipgate/docs/prd/eval-measurement.worklog.md:139` — The data flow dropped the mode from the run-set line, and T041 said "with the ceiling" twice; fixed.
- L10 LOW `shipgate/tests/test_compare.py:446` — Blank-line layout around the new F11 test; fixed.

### Rejected findings (round 4)

- `shipgate/evals/compare.py:264` (LOW 40): the no-trace warning still prints for a picked entry that `main()` refuses later; the no-shadow.json warning has always done the same, and the docs say "uses", which a pick is.
- `shipgate/docs/research/2026-11-25-eval-suite-audit.md:250` (LOW 30): "on 3 lanes" in a dated projection; it still reads true as three runs side by side.

## Review round 1 (PR 2)

Workflow run `wf_db102f54-b04`, 3 lenses on Opus: 27 found, 24 after dedupe, 11 above the
floor of 60, 0 BLOCKER or HIGH, so no refuter ran. The orchestrator read the code of each
survivor. A briefed security reviewer read all 77 changed files and found nothing. Verdict:
not ready. The fix round takes F1 to F9.

- F1 MEDIUM `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:41` — The sed and perl write pattern reads past `&&`, `;` and `|`, so `sed -n 1p pricing.py && grep -in x pricing.py` counts as an edit and fails a good run.
- F2 MEDIUM `shipgate/evals/70-review-fact-retention/script-graders/no-sentence-over-40-words.py:41` — A sentence that ends in `.**`, `.)` or `."` does not end, so a bold verdict line joins the next sentence and fails a short report.
- F3 MEDIUM `shipgate/evals/70-review-fact-retention/graders/deviation-not-relitigated.md:8` — 44's regex stops at the first period, and every report in 70 names `export.py`, so it misses the usual way a review raises the deviation; 70 needs the claim as a judge too.
- F4 MEDIUM `shipgate/tests/test_eval_graders.py:176` — The clean-environment scaffold helper is written twice, here and in `test_eval_fixtures.py`.
- F5 LOW `shipgate/tests/test_eval_fixtures.py:214` — The test's giveaway regex has `backoff`, and the fixture's has `back-?off`.
- F6 LOW `shipgate/evals/70-review-fact-retention/script-graders/no-sentence-over-40-words.py:16` — One docstring line is not wrapped.
- F7 LOW `shipgate/CHANGELOG.md:15` — The eval-suite sentence joins the bold paragraph about `hotspots`.
- F8 LOW `shipgate/tests/test_eval_fixtures.py:166` — Only 58's computed revisit date is scaffolded and checked; 45, 47 to 50, 67 and 70 are not.
- F9 LOW `shipgate/evals/fixtures/bigshop.py:1` — The docstring still calls the tree deterministic, but the revisit date now changes every day.

### Rejected findings

- `shipgate/scripts/signals.py:1691` (LOW 60): `emit()` reorders any payload with a `ui` key; only `hotspots` builds one, and a parameter for one caller adds a rule without a defect.
- `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:97` (LOW 60): any Bash call that names `unittest` or `pytest` counts as a run; that is the rule of the LLM judge it replaces, and a narrower pattern would miss test runs the judge counted.

## Review round 2 (PR 2)

One Opus reviewer with all lenses read the fix diff. F1 to F9 are fixed, each pinned by a
test or a cited line; the fix-scope modules pass (55 and 26 tests, also on Python 3.9). The
F1 fix opened a regression, which the orchestrator reproduced. Verdict: not ready. Under the
two-round cap, the list went to the lead with no further fix.

- R2-1 HIGH `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:42` — `_ONE_COMMAND` takes a quote only as a whole quoted string, so `sed -i 's/a/b/' "pricing.py"` and `perl -pi -e '…' "app/pricing.py"` no longer count as writes; a run that edits a quoted path after its last test run now passes.
- R2-2 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:38` — An unquoted sed script with an escaped `\;` or `\&` no longer counts as a write.
- R2-3 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:42` — The flag pattern `-[a-zA-Z]*i` matches perl's `-Mstrict` and `-Ilib`, so a perl read counts as a write (it did before PR 2's fix too).
- R2-4 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:36` — The path prefix misses `$PWD/`, `~/` and a path with a space (it did before too).
- R2-5 LOW `shipgate/tests/test_eval_graders.py:503` — WRITES has no quoted-file form and no `|` in a quoted script, so no test caught R2-1.
- R2-6 LOW `shipgate/tests/test_eval_graders.py:202` — `JournalGrader.setUpClass` leaks its temp dir when the scaffold fails.
- R2-7 LOW `shipgate/tests/test_eval_fixtures.py:176` — The revisit-date test does not check that the date lands before the commit (`git status` clean).
- R2-8 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:13` — The docstring does not state the one-command boundary.

## Review round 3 (PR 2)

The user chose "Count tool edits only" (relayed by the lead, 2026-11-26): round 3 removes the
net of shell-write patterns instead of fixing it.

- Case 22's script grader counts an edit of `pricing.py` only as an Edit, Write, MultiEdit
  or NotebookEdit call whose result is no error. It reads no Bash command for writes. An
  edit made through a shell command is out of scope, and a test pins that limit
  (`test_a_bash_write_is_not_an_edit`).
- A test run is a Bash call with the fixture's one test command, `python3 -m unittest`
  (also `python` or `python3.N`, with any arguments). `pytest` no longer counts; the old
  judge also counted it.
- This closes R2-1 to R2-5 and R2-8. R2-6: `JournalGrader` registers its temp-dir cleanup
  right after `mkdtemp()`. R2-7: the revisit-date test also asserts a clean `git status`
  in each scaffolded repo.
- No saved trace of case 22 holds tool calls. The main checkout's results hold 7 result
  files with 34 runs of case 22. Each run names a trace path, and none of the 34 trace
  files still exists; the result files hold no tool calls. So no count of Bash edits
  against tool edits exists.
- The round-1 rejection of `last-test-after-last-edit.py:97` argued that a narrower test-run
  pattern would miss runs the judge counted. The user's decision replaces that argument.

One Opus reviewer read the round-3 diff: R2-1 to R2-8 are closed, by removal or by a fix; no
BLOCKER, HIGH or MEDIUM; 8 LOW. The orchestrator fixed R3-1, R3-2 and R3-8 (test data, a
test name, this worklog note) and defers the rest.

- R3-1 LOW `shipgate/tests/test_eval_graders.py:574` — `test_no_test_run_fails` used `python3 test_pricing.py`, which runs the tests; it now uses `python3 -c "import pricing"`, and `test_only_the_fixture_command_counts` pins that a direct run and `pytest` do not count.
- R3-2 LOW `shipgate/tests/test_eval_graders.py:514` — `pytest -q` sat in the "only names a runner" list; it moved to that new test.
- R3-3 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:35` — A command that only quotes `python3 -m unittest` (a grep, an echo) counts as a run.
- R3-4 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:35` — `python3 -u -m unittest` and `python3 -munittest` do not count as a run.
- R3-5 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:41` — A non-string tool input or a bad byte crashes the grader, which `evalrun` records as an error, not a fail.
- R3-6 LOW `shipgate/evals/22-verify-stale-after-fix/script-graders/last-test-after-last-edit.py:69` — "Bash call N" numbers all tool calls, not Bash calls.
- R3-7 LOW `shipgate/tests/test_eval_fixtures.py:176` — The clean-tree check covers each repo root, not the dated file itself.
- R3-8 LOW `shipgate/docs/prd/eval-measurement.worklog.md:627` — The round-1 rejection about a narrower pattern now contradicts round 3; the note above answers it.

Deferred: R3-3 to R3-7. Each is a rare edge of a grader that only reads text; R3-5 already
ends as an error, never as a wrong verdict. The PR 3 runs keep their traces, so the first
measured traces of case 22 show whether any edge occurs.

## Review round 1 (Set runner)

The workflow review (run wf_71bf14f1-035) used two Opus finders, correctness and
conventions plus design. It found 16 findings: 6 at or above the confidence floor, 10
below it. None was BLOCKER or HIGH, so no refuter ran. The orchestrator read each one
against the code. It fixed the 6 and rejected the 10 below. The fix diff is two blocks of
`run-set.sh` and four doc lines. The orchestrator checked it alone: two new tests pin the
exit-2 stop, and the doc check runs every documented `run-set.sh` command with the stub
`claude`. The fresh full suite ran in three parts: 821 + 1188 + 640 = 2649 tests, OK, 2
skipped. Verdict: ready.

- S1 MEDIUM `shipgate/docs/adr/0036-post-run-checks-read-the-kept-trace-and-probes-leave-the-harness.md:60` — The ADR still called `run-set.sh` a later PR; fixed.
- S2 MEDIUM `.claude/skills/run-evals/SKILL.md:44` — The options line read as true for `run-set.sh`, which takes no `--no-codegraph`; the line now names the options of each script.
- S3 MEDIUM `.claude/skills/run-evals/scripts/run-set.sh:121` — A case that hit its ceiling (exit 2) did not stop the set, and on the last case the set exited 0; it now stops the set with exit 2, pinned by two tests.
- S4 LOW `.claude/skills/run-evals/scripts/_common.sh:2` — The header did not name `run-set.sh` as a user; fixed.
- S5 LOW `.claude/skills/run-evals/scripts/run-set.sh:134` — A failed final spend sum printed an empty value and exited 0; it now stops with exit 1.
- S6 LOW `.claude/skills/run-evals/scripts/run-set.sh:119` — The docs said the log keeps each case's output, but it keeps stdout; the docs now say stdout.

### Rejected findings (Set runner round 1)

- `.claude/skills/run-evals/scripts/run-set.sh:125` (MEDIUM 50): with no `Report:` line, the listing fallback of `run-case.sh` can pick another shard's dir; that fallback is in `run-case.sh` and holds for any two runs side by side.
- `.claude/skills/run-evals/scripts/run-set.sh:44` (LOW 55): the mode and model parsing repeats `run-case.sh`; the set needs it to refuse a usage error with exit 64 before any case.
- `.claude/skills/run-evals/scripts/run-set.sh:113` (LOW 50): the ceiling stop prints to stdout and the error stops to stderr; the ceiling is a planned stop, not an error.
- `shipgate/evals/evalrun.py:380` (LOW 45): `spent` reads only per-run costs; a cut run now also stops the set through exit 2.
- `.claude/skills/run-evals/scripts/run-set.sh:64` (LOW 45): an extra `--case` or `--config-dir` is not refused; `run-case.sh` refuses neither among its extras either.
- `.claude/skills/run-evals/scripts/run-set.sh:91` (LOW 45): the set-time case check exits 1; a set that names a missing case is a data error, not a usage error.
- `.claude/skills/run-evals/scripts/run-set.sh:111` (LOW 40): the remainder rounds down to the cent; the difference is below one cent.
- `docs/ledger.md:5` (LOW 40): the ledger line names no home; the ledger takes one dated line, and Capture routes it.
- `.claude/skills/run-evals/SKILL.md:3` (LOW 35): the skill description already triggers on any ask to run the evals.
- `.claude/skills/run-evals/SKILL.md:173` (LOW 30): the shard ceilings are an example with a placeholder model, not a plan value.

## Review round 2 (Set runner)

The lead reopened the round 1 rejection of `run-set.sh:125` and asked for the listing
fallback of `run-case.sh` to go. One Opus reviewer with all lenses read the fix diff only.
It confirmed that no path picks a results dir by a listing. It confirmed that the earlier
fix holds: with no `Report:` line the exit status is still the harness's. It found that the
four new tests fail on the old script. `test_evalrun.py`: 79 tests, OK. It found one new
MEDIUM and four LOW. Verdict: not ready. Under the lead's rule (a new MEDIUM stops the
round), the list went to the lead with no further fix.

- R2-1 MEDIUM `.claude/skills/run-evals/scripts/run-case.sh:151` — A harness that writes its results but prints no `Report:` line (it can fail to build the HTML report) now leaves the kept sandboxes in the temp dir and the dir with no `shadow.json`; the message does not say so or give the manual `post-run` step.
- R2-2 LOW `.claude/skills/run-evals/scripts/run-case.sh:123` — An extra `--report <path>` can make the `Report:` line name a dir that is not the results dir; it predates the fix, but the line is now the only source.
- R2-3 LOW `shipgate/docs/prd/eval-measurement.worklog.md:577` — The worklog did not record the removal; fixed by the dated Deviations line of 2026-11-26.
- R2-4 LOW `.claude/skills/run-evals/scripts/run-case.sh:151` — The new message drops the hint of the old one and gives no next step.
- R2-5 LOW `shipgate/tests/test_evalrun.py:?` — `test_the_report_line_wins_over_a_newer_foreign_dir` passes with or without the fix; it guards the order, it does not prove the fix.

## Review round 3 (Set runner)

The lead rated R2-1 LOW (it fails closed, and compare refuses a dir with no
`shadow.json`) and chose the fix: the message names what stays on disk and the command
by hand, and `run-case.sh` refuses `--report`. R2-5 is rejected: that test guards the
order by design. One Opus reviewer with all lenses read the fix diff only. It confirmed
R2-1 (message) and R2-2 fixed, ran the printed command by hand on a path with a space and
a quote, and found that both new tests fail without the fix. `test_evalrun.py`: 81 tests,
OK. It found one new MEDIUM and six LOW. Verdict: not ready. Under the lead's rule (a
MEDIUM that is more than a one-line doc fix stops the round), the list went to the lead.

- R3-1 MEDIUM `.claude/skills/run-evals/scripts/run-case.sh:63` — `--json` makes the harness quiet, so a run with it likely prints no `Report:` line and has no results dir; the README still recommends `--json` for runs side by side (README:246) and says the `Report:` line always names the results dir.
- R3-2 LOW `.claude/skills/run-evals/scripts/run-set.sh:73` — `run-set.sh` does not refuse `--report` itself; the first case exits 64 and the set reports "left no results dir" with exit 1.
- R3-3 LOW `shipgate/tests/test_evalrun.py:?` — The test does not pin the `%q` quoting of the printed command.
- R3-4 LOW `.claude/skills/run-evals/scripts/run-case.sh:150` — The Report-line branch prints its post-run command without `%q`.
- R3-5 LOW `.claude/skills/run-evals/scripts/run-case.sh:154` — The message does not say where the sandboxes are or how to pick the dir; "stay on disk" overclaims after an abort before any run.
- R3-6 LOW `.claude/skills/run-evals/scripts/run-case.sh:21` — The usage header does not name the `--report` refusal.
- R3-7 LOW `.claude/skills/run-evals/scripts/run-case.sh:67` — "do not move the report" assumes what `--report` does.

## Review round 4 (Set runner)

The user chose "Pass --output-dir" (relayed by the lead): `run-case.sh` owns its results
dir, and the `Report:` line parse goes. The findings of round 3 that lived in the removed
code close with it: R3-1 (`--json` hides the `Report:` line), R3-2 (`run-set.sh` and
`--report`), R3-5 (the by-hand message) and R3-7 (the `--report` wording). R3-3 and R3-4
are fixed: the post-run echo quotes with `%q`, and a test runs it on a path with a space.
R3-6 is fixed: the usage header names the `--output-dir` refusal. One Opus reviewer with
all lenses read the round 4 diff. It found that every new or changed test fails on the
HEAD script, that nothing still depends on the `Report:` line, and that `--bare`,
`--keep-temp`, `--report` and `--json` work. `test_evalrun.py`: 81 tests, OK. It found two
new MEDIUM and six LOW. Verdict: not ready. Under the lead's rule (a MEDIUM stops the
round), the list went to the lead with no further fix.

- R4-1 MEDIUM `.claude/skills/run-evals/scripts/run-case.sh:109` — The `rmdir` rests on a false premise: the harness bundle refuses only a default results dir that exists, and with `--output-dir` it makes the dir recursively; the comment, the Deviations line and the stub's refusal of an existing dir are wrong.
- R4-2 MEDIUM `.claude/skills/run-evals/SKILL.md:51` — The "`run-case.sh` runs:" command block leaves out `--output-dir`.
- R4-3 LOW `.claude/skills/run-evals/scripts/run-case.sh:135` — The printed summarize and signal-grader commands are not quoted with `%q`.
- R4-4 LOW `.claude/skills/run-evals/scripts/run-case.sh:114` — A failed `mkdir -p` of the results root or a failed stamp exits 1 with no `run-evals:` line.
- R4-5 LOW `.claude/skills/run-evals/scripts/run-case.sh:153` — A dir with files but no `aggregate-result.json` stays on disk, and the message does not say so.
- R4-6 LOW `.claude/skills/run-evals/scripts/run-case.sh:122` — An explicit `--output-dir` turns off the harness's warning and ownership check for results written inside the plugin.
- R4-7 LOW `.claude/skills/run-evals/scripts/run-case.sh:115` — Within one millisecond a script dir sorts before a default dir; rare.
- R4-8 LOW `.claude/skills/run-evals/scripts/run-case.sh:65` — An extra `--eval-dir` is not refused, and the old hint that named it is gone.

## Review round 5 (Set runner)

The last fix round, by the lead's decisions: R4-1 the lead's plan as written (the script
makes the dir and keeps it), R4-2 the command block, R4-3 the quoted echo lines, R4-4 a
`run-evals:` line on each failed setup step, R4-5 the "stays" message, R4-6 one README
line. R4-7: no fix. R4-8: deferred (Deviations). Each code change had its test first. One
Opus reviewer with all lenses read the fix diff: all six are fixed, each new test fails on
the round 4 script, `test_evalrun.py` 85 tests OK. No BLOCKER, HIGH or MEDIUM; six LOW,
all deferred below. Verdict: ready.

- R5-1 LOW `shipgate/tests/test_evalrun.py:?` — The read-only subtest of `test_a_results_dir_that_cannot_be_made_stops_before_any_spend` fails when the tests run as root; deferred.
- R5-2 LOW `shipgate/tests/test_evalrun.py:?` — Both subtests match any "cannot make" message, not the step that failed; deferred.
- R5-3 LOW `.claude/skills/run-evals/scripts/run-set.sh:127` — "left no results dir" follows a "stays" line for a dir with files and no aggregate; deferred.
- R5-4 LOW `.claude/skills/run-evals/scripts/run-case.sh:155` — The "stays" message prints for any `rmdir` failure, also when the dir is gone; deferred.
- R5-5 LOW `.claude/skills/run-evals/scripts/run-case.sh:118` — A run stopped by Ctrl-C leaves its empty results dir; compare and summarize skip it; deferred.
- R5-6 LOW `.claude/skills/run-evals/SKILL.md:40` — The summarize example says `<timestamp>`, the command block `<stamp>-<pid>`; deferred.

## Rejected findings

## Review round 1 (Managed-settings guard)

The workflow review (run wf_85135642-0e3) used two Opus finders, correctness and
conventions plus design. It found 13 findings: 6 at or above the confidence floor, 7 below
it. The one HIGH went to two refuters, and both failed to refute it. The orchestrator fixed
all 6, plus two cheap ones from below the floor (the Linux path in the skill, the
traceability line), and pinned the drop-in read error with a test. The fix pass and T056
(added after the round, when the eval-only config dir turned out to need the keychain)
were checked by the orchestrator alone: four files, each fix read against its finding, and
T056 pinned by three tests that failed first. The fresh suite ran in parts: 651 + 1188 +
418 tests, OK, 2 skipped. Verdict: ready.

- G1 HIGH `shipgate/tests/test_probe.py:331` — The probe.sh tests ran the real config-check with no `EVALRUN_MANAGED_SETTINGS`, so they read the machine's managed file; fixed.
- G2 MEDIUM `.claude/skills/run-evals/SKILL.md:120` — Gotcha 6 still ended with one fix for both cases; it now gives the install fix and the managed fix apart; fixed.
- G3 MEDIUM `shipgate/docs/prd/eval-measurement.worklog.md:125` — The Architecture and Data-flow lines described a config-dir-only check; updated, and a Deviations line records the new scope; fixed.
- G4 LOW `shipgate/docs/prd/eval-measurement.worklog.md:431` — The What changed edit dropped the `--output-dir` fact; restored; fixed.
- G5 LOW `.claude/skills/run-evals/scripts/probe.sh:18` — Header lines past the wrap width in probe.sh and run-case.sh; reflowed; fixed.
- G6 LOW `shipgate/evals/evalrun.py:160` — An unreadable `managed-settings.d` escaped as a traceback with exit 1; it is now a usage error, exit 2; fixed.

### Rejected findings (Managed-settings guard round 1)

None. Five below-floor findings stay open as LOW notes: the `EVALRUN_` prefix of the new
variable, the skill description's triggers, a truthy enable value that is not `true`, the
order of drop-ins with mixed-case names, and an unreadable managed file.

## Review round 1 (Stage fixes T053-T059)

The lead asked for one review of T053 to T059 as one change, with the focus on T057 to T059
and on security. The workflow review (run wf_81e57438-58f) used two Opus finders,
correctness and simplicity plus security. It found 14 findings, 11 after dedupe, 7 above the
floor (no BLOCKER or HIGH, so no refuter ran) and 4 below it. The orchestrator fixed the 5
distinct ones, test-first where a test could fail first.

- S1 MEDIUM `shipgate/evals/evalrun.py:436` — `links_leaving` compared link targets lexically, so a chain of relative links could leave evals while each text stayed inside; it now resolves the whole chain with `realpath`; fixed.
- S2 LOW `.claude/skills/run-evals/scripts/run-case.sh:124` — The comment and the log line still called the stub's evals a link; fixed.
- S3 LOW `shipgate/evals/evalrun.py:354` — No test pinned the "could not remove it" branch of the clean-up; pinned; fixed.
- S4 LOW `.claude/skills/run-evals/scripts/_common.sh:59` — A failed link step leaked the scratch HOME with its keychain link before the caller's trap was set; it now removes the dir first; fixed.
- S5 LOW `shipgate/evals/evalrun.py:361` — `unseal` checked for a link and then called a chmod that follows links; it now uses `follow_symlinks=False` where the platform has it; fixed.

### Rejected findings (Stage fixes round 1)

- `.claude/skills/run-evals/scripts/_common.sh:62` (LOW 55): the keychain link reaches the agent through HOME; the harness gives the agent its own home inside the sandbox, so the scratch HOME is the harness's, and the trap removes only the link.
- `.claude/skills/run-evals/scripts/run-case.sh:126` (LOW 50): `--trust-plugin` could persist for a reused mktemp path; unverified, and the stub path is new on every run.
- `.claude/skills/run-evals/scripts/_common.sh:63` (LOW 45): the same keychain point as the first line.
- `shipgate/evals/evalrun.py:318` (LOW 40): speculative; removal stays limited to an `e-*` dir under a temp root that a trace path names.

## Review round 2 (Stage fixes T053-T059)

One Opus reviewer that carries all lenses re-read the fix hunks and ran `test_evalrun.py`
(108 OK). S1 to S4 are fixed on evidence. S5 is fixed on macOS; on Linux the code falls
back to the old check-then-chmod. Three new LOW findings, deferred. No link of these kinds
exists in the repo's evals, and the cap is two rounds. The fresh verify ran
`test_evalrun.py` and `test_probe.py`: 309 tests OK. Verdict: ready.

- S6 LOW `shipgate/evals/evalrun.py:442` — A relative link that climbs above evals by name and comes back through the plugin dir's own name passes the check, but in the stub's copy it points outside and dangles; deferred.
- S7 LOW `shipgate/evals/evalrun.py:425` — A link into the skipped top-level `results/` passes the check and dangles in the copy; deferred.
- S8 LOW `shipgate/evals/evalrun.py:363` — On Linux (no lchmod) `unseal` keeps the check-then-chmod race, and no test forces that branch; deferred.
