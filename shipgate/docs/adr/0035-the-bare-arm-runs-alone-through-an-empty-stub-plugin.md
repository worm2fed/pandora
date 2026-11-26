---
type: adr
title: "0035. The bare arm runs alone through an empty stub plugin"
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
  - "./0034-a-baseline-row-is-per-case-and-model-and-names-its-mode-and-rule.md"
  - "./0036-post-run-checks-read-the-kept-trace-and-probes-leave-the-harness.md"
---

# 0035. The bare arm runs alone through an empty stub plugin

> Stage 1 of the re-baseline needs the bare arm alone. The harness cannot do that. The run
> script builds a stub plugin with no component, points it at the real evals directory, and
> runs it with `--ablation none`.

Accepted on 2026-11-25 by the lead, under the executive contract (no one-way door). The
user sees it in the lead's report and can veto it.

## Context

- D1 of the user: stage 1 runs only the Fable bare arm of the 17 cases of the #32 set,
  3 runs. The with arm runs only where the bare arm falls.
- The harness takes `--ablation none` or `with-without`. `none` runs only the with arm.
  `with-without` runs both. There is no bare-only mode (`claude plugin eval --help`).
- The harness picks `none` when no plugin resolves, but the behaviour for a target with no
  plugin manifest is not documented.
- Stage 1 projects to 24.83 USD. The with arm of the same 17 cases on Fable projects to
  36.84 USD more.

## Decision

`run-case.sh --bare` builds a stub plugin in a scratch directory:

- `.claude-plugin/plugin.json` with the name `<plugin>-bare` and the tested plugin's
  version, and no skill, agent, hook, command or MCP server;
- `evals`, a symbolic link to the real evals directory, so cases, fixtures, graders and the
  results directory are the real ones.

It runs `claude plugin eval <stub> --ablation none --model <m> --trust-plugin`, with the
same scaffold, judge and tool grants as any run. The run script writes `bare.json` into the
results directory. Compare reads the run as `mode: bare` and scores it under the both-arm
rule (ADR 0034). The shadow check (ADR 0036) must see no plugin named `<plugin>` in the
trace's init record; else the run is shadowed.

**Proof run (the lead's rule).** Before stage 1 runs the set, one bare run of the cheapest
case, 24, proves the stub. The proof holds when the trace's init record lists no plugin
named `<plugin>`, and no skill of `<plugin>` fired in the run. The set starts only after the
proof holds. If it fails, stage 1 stops, and the run goes back to the lead.

## Alternatives considered

- **Full `with-without` on Fable for the 17 cases.** It needs no new mechanism, and the
  harness computes Δ itself. It costs about 61.67 USD instead of 24.83 USD, and it pays for
  the with arm on every case that stage 1 would cut. D1 rejects that spend.
- **A target directory with only `evals/`.** The harness may pick `none` with no plugin.
  The behaviour is undocumented. A first run would show it, but a failed guess costs a run.
- **`--disallow-tools Skill` on the real plugin.** The hooks still run, and the skill
  descriptions may stay in the prompt. It is not the bare model.

## Consequences

- The proof run of case 24 proves the stub before any other stage-1 spend. A harness that
  refuses a plugin with no component fails before any agent starts, at no cost.
- In `none` mode the harness scores `skill-fired`, which fails in a bare run. The raw score
  of a bare run is therefore low. Only the both-arm score counts, and compare shows only
  that.
- The stub's results land in the real results directory through the link. `bare.json` is
  what tells compare and summarize the arm.
- If the user vetoes this ADR, stage 1 runs as full `with-without`, and the plan's stage-1
  ceiling becomes 61.67 USD plus 25%.
