---
type: adr
title: "0016. The signal grader is a script outside the eval harness"
created: 2026-11-06
updated: 2026-11-06
tags:
  - adr
  - shipgate
  - evals
status: accepted
date: 2026-11-06
issue: "#6"
related:
  - "0007-codegraph-as-detected-structure-provider.md"
  - "../research/2026-10-19-codegraph-vs-signals.md"
---

# 0016. The signal grader is a script outside the eval harness

> `shipgate/evals/signal_grader.py` scores a `signals.py` blast result against a case's
> `expected.json` and prints precision and recall. `run-case.sh` runs it after a case that
> has an `expected.json`. It adds no grader to the harness score.

## Context

The code-graph ablation grades only the agent's final answer. On case 72 the graph reaches
56 of 59 true files and the regex scanner 2, but the answers tie (#6). The harness grades
each grader as pass or fail. Its grader types are `regex`, `tool_used`, `tool_order`,
`file_exists`, `llm` and `baseline`; none runs a script, and none computes a ratio.

## Decision

1. **A stdlib script.** `signal_grader.py` (Python 3.9) takes a blast result and an
   `expected.json`. `blast.files` is scored against the importers and the tests together;
   `blast.tests` against the tests. Each gives precision and recall. An empty expected list
   gives a recall of 1.0; an empty or `null` result list gives a precision of 1.0.
2. **Two sources.** `trace <trace.jsonl>` reads the last `signals.py blast --json` or
   `hotspots --blast --json` result the agent obtained. `fixture <case dir> --arm
   graph|regex` scaffolds the case and runs `signals.py blast` on the change at HEAD, with
   `--graph auto` or `--graph off`. `results <dir>` runs `trace` for every run of a case
   with an `expected.json` whose trace still exists.
3. **Wiring.** Cases 13 and 72 hold an `expected.json`. `run-case.sh` runs `results` on the
   new results dir when the case has one, in both arms; the trace exists only with
   `--keep-temp`, and the script says so when it is gone.
4. **No harness grader.** The answer graders and `baseline.json` stay as they are.

## Alternatives considered

- **Regex graders with lookahead counts over the trace.** A pass at a fixed recall
  threshold, not a number, and fragile against the trace's JSON escaping.
- **An `llm` grader that counts.** Paid and unreliable for a count of 59 paths.

## Consequences

- The signal numbers appear beside the harness report, not in it, and `compare.py` does not
  track them.
- A case with no `expected.json` gets no signal grade.
