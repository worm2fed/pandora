---
type: adr
title: "0006. The output-style rule is one callout repeated per surface, pinned by a test"
created: 2026-10-12
updated: 2026-10-12
tags:
  - adr
status: accepted
date: 2026-10-12
issue: "none / ad-hoc"
related: ["../prd/ste-writing-style.md", "../glossary.md"]
---

# 0006. The output-style rule is one callout repeated per surface, pinned by a test

> The "Writing for people" rule is a short blockquote with identical text in every skill and
> agent that prescribes a report for a person, and in the two skills that hand the rule on. A
> contract test fails when any copy drifts.

## Context

Ten surfaces prescribe prose a person reads: the reviewer's findings template, the explorer's
and architect's return formats, review's rank-and-verdict output, verify's report,
structured-debug's statements, the clarify, design and implement summaries, and the
orchestrator's phase summaries. Two more skills hand the rule on without prescribing a report:
`model-tiers` pastes it into worker briefs, and `knowledge-base` applies it to ledger lines
and captured pages under `ste-80`. Each phase skill also runs standalone, so no single skill
is always loaded. Agent definition files are the whole system prompt of a subagent, so an
agent cannot follow a pointer to a rule elsewhere. The rule must therefore reach each surface
on its own, and it must say the same thing everywhere, or two surfaces will report in two
styles.

## Decision

Write the rule once, as a six-line blockquote headed **Writing for people**, and paste it
verbatim into each of those surfaces and the two hand-on skills, the way the **Project
config** callout is already repeated in every skill. `tests/test_prose.py` reads every copy
and asserts they are identical and that each listed surface carries one. Executive decision;
reversible.

## Alternatives considered

- **One reference file the skills point at** (`skills/feature/references/output-style.md`,
  read on demand). One source, no drift. Rejected: it costs a tool call per phase, a skill
  that skips the read reports in the old style with no signal, and agents cannot read it at
  all before they start.
- **Rule in `feature` and the agents only, pointers elsewhere.** Fewer copies. Rejected: the
  phase skills run standalone ("review this before I push") without `feature` loaded, and
  those standalone answers are the reports people read most.

## Consequences

Twelve identical copies, about 70 words each, in files the model reads on every invocation.
Any change to the rule is a twelve-file edit, which the test turns from a risk into a
checklist. The config's `Writing style` key extends the same callout to repo-side documents,
so there is one rule in the plugin, not two.
