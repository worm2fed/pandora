---
type: adr
title: "0036. Post-run checks read the kept trace, and probe and fixture cases leave the harness"
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
  - "./0016-the-signal-grader-runs-outside-the-harness.md"
  - "./0034-a-baseline-row-is-per-case-and-model-and-names-its-mode-and-rule.md"
---

# 0036. Post-run checks read the kept trace, and probe and fixture cases leave the harness

> After each run, the run script reads every run's kept trace. It marks a shadowed run and
> runs the case's script graders, beside the harness score. A probe case or a fixture-only
> case holds no `prompt.md` and no `graders/`, so the harness never runs it. Named sets live
> in one file.

Executive decision (the `autonomy` setting is `executive`). The user can veto it. It extends
ADR 0016, which put the signal grader outside the harness.

## Context

- The harness has four grader types: regex, LLM judge, `tool_used` and `file_exists`. It
  has no script grader.
- #49: an installed plugin of the same name can load in place of the tree under test. The
  trace's init record names the plugin path and version that loaded. The result file names
  only the target.
- The harness discovers a case by `case.yaml`, or by `prompt.md` with `graders/*.md`, under
  the evals directory. `--case` takes one glob per call. `--tag` exists, but no case uses
  tags, and their syntax is not documented.
- The audit moves 16 negatives and the firing of 08, 09 and 10 to trigger probes, and keeps
  the fixtures of 08, 10, 13 and 72 for fixture tests.

## Decision

- The run script always passes `--keep-temp`. After the run, `evalrun.py` reads each run's
  trace:
  - **shadow check**: the init record's plugin list must name the tree under test for the
    with arm, and no plugin of that name for a bare run. It writes `shadow.json` into the
    results directory. A shadowed run is refused by `--record`.
  - **script graders**: for each case with `script-graders/*.py`, each script gets the
    run's trace path and exits 0 (pass) or 1 (fail) with one line of reason. The results
    go into `script-graders.json`. Compare shows them per arm beside the score and flags a
    fall. They never enter the harness score.
  Then the run script removes the kept scaffold directories, unless the caller asked to keep
  them.
- A probe case keeps `fixture.sh`, the prompt as `probe.md`, and its expectation as
  `probe.json`. A fixture-only case keeps `fixture.sh` and `expected.json`. Neither holds
  `prompt.md` or `graders/`.
- `evals/sets.json` names the sets: `kept`, `guards`, `ablation-32`, `probes`, `parked`. A
  unit test checks that the eval sets cover exactly the harness's case list, and that no
  case is in two sets. A set runner (`run-set.sh`) runs a set serially, one harness call
  per case; `--shard k/n` gives parallel work as several invocations side by side.
  (Changed during the build: a version with lanes left PR 1 in review round 4.)
- `probe.py` replaces the inline counter of `probe.sh`. It reads the stream, counts the
  skills that fired and the named calls, judges the run against `probe.json`, and saves a
  result with model, turns, cost and time.

## Alternatives considered

- **Script graders as `graders/*.py` beside the `.md` graders.** The harness reads
  `graders/*.md`; how it treats another file there is not documented. A separate directory
  is safe.
- **Tags in `case.yaml` and `--tag`.** One harness call per set would be cheaper to type.
  The tag syntax is undocumented, and a wrong guess runs the whole suite. A sets file is
  plain data that a unit test checks for free.
- **Probe cases in a directory outside `evals/`.** The fixtures belong with the plugin's
  evals, and the cases keep their numbers. A file name decides what the harness sees.
- **Shadow check from the result file.** `suite.plugins` names the target, not what loaded,
  so it cannot see the shadow.

## Consequences

- Every run keeps its traces until the post-run step ends. Disk use grows for the length of
  one run.
- A script grader is plain Python, tested with a canned trace at no cost.
- A case directory's file names now decide whether it is an eval case, a probe case or a
  fixture. The evals README states the three forms.
- `summarize.py` and `compare.py` read `shadow.json`, `bare.json` and
  `script-graders.json`.
