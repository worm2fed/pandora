---
type: prd
title: "PRD: STE-80 writing principles, scoped by audience"
created: 2026-10-12
updated: 2026-10-12
tags:
  - prd
  - shipgate
status: clarified
issue: "none / ad-hoc"
worklog: "./ste-writing-style.worklog.md"
related:
  - "../glossary.md"
  - "https://max.nardit.com/articles/karpathy-understanding-llm-outputs"
  - "https://gu-log.vercel.app/en/posts/en-mp-317-20261002-karpathy-llm-output-format-ladder/"
---

# PRD: STE-80 writing principles, scoped by audience

> Make what shipgate writes for people easier to read: short sentences, common words, one
> term per concept, one action per step. Keep every fact. Apply it by audience, never force
> it on another project's docs.

## Problem

shipgate's output is read by people under time pressure: review findings before a push,
verify results after a fix, debug hypotheses during an incident, gate summaries at a phase
boundary. Long sentences with several clauses bury the fact that decides the next action.
Karpathy's advice is to ask the model for prose "about 80% of the way to ASD-STE100"
(Simplified Technical English). It is an output-readability technique, and the "80%" matters:
strict STE prompting dropped about 47% of the facts in one informal test, and models produce
STE-flavoured English, not compliant STE. So the plugin adopts the principles, with a guard
that no fact is dropped, and only for the audiences that benefit.

Three audiences read what shipgate writes, and they need different treatment:

1. The person driving the flow reads the orchestrator's and subagents' reports. This is the
   readability case. Default on.
2. Teammates read the documents shipgate writes into their repo or forge (PRD, ADR, worklog,
   ledger, MR/PR body, tracker comments). shipgate runs in other people's repos and must not
   impose a prose style on them. Opt-in.
3. The model reads the skill bodies. Here the win is "one term per concept" and "one action
   per step", not the sentence budget. A terminology audit already shipped in v0.14.1
   (`docs/glossary.md`); this change finishes it and applies the remaining principles.

The skill frontmatter `description:` fields are a fourth surface and are out of scope: they
are tuned for triggering on users' natural phrasing and measured by the evals.

## Goals & non-goals

**Goals**
- Every human-read report shipgate produces follows the STE-80 principles by default and
  keeps every fact it carried before.
- A project can opt its repo-side documents into the same style with one config line, and
  gets plain prose when it says nothing.
- Skill and agent bodies use one term per concept throughout, with shorter sentences and one
  action per step, without losing any instruction, number, path or contract name.
- An eval grades fact retention on a report-style case, so the known failure of STE
  prompting is measured, not assumed.

**Non-goals**
- No change to any skill's frontmatter `description:` (byte-identical before and after).
- No restriction of vocabulary to the STE dictionary, no approved-word lists, no noun-cluster
  limits. Principles, not the spec.
- No change to hooks, `journal.py`, `signals.py` or the Workflow scripts' behaviour.
- No rewrite of the README, the config template or the CHANGELOG for style; they take the
  terminology pass only, plus the lines this change adds.
- No style rule for the journal's event payloads (pointer, not prose, already).

## Functional requirements

- **FR-001** — Every surface where a skill or agent prescribes a report for a person carries
  the same output-style rule: sentences of about 20 words with one idea each, common words,
  the glossary's term for each concept, one action per step, active voice. The rule states the
  guard in the same breath: shorter sentences, not fewer facts, and names the facts that must
  survive (file:line, severity, confidence, failure scenario, the command, its exit code,
  counts, the verdict). Surfaces: the reviewer's findings template, the explorer's and
  architect's return formats, review's filter-and-rank output and verdict, verify's report,
  structured-debug's observed-vs-expected statement, hypotheses and root-cause report, the
  clarify and design phase summaries, implement's completion summary, the orchestrator's
  phase summaries and next-phase proposal.
- **FR-002** — A new config section declares the style for repo-side documents. Absent, or a
  placeholder, means plain. The section is in the config template with its default noted, in
  the README's config table, and offered by `setup`'s interview. The skills that write a PRD,
  ADR, worklog, ledger line, MR/PR body or tracker comment read it, and worker briefs that
  write any of those carry the excerpt. `plain` changes nothing about today's behaviour.
- **FR-003** — Residual synonyms in the prose the model reads are unified against
  `docs/glossary.md`, and the glossary gains any term the unification needs. This lands as its
  own commit before any style rewrite.
- **FR-004** — The bodies of the 12 skills, the 3 agents and the command apply the principles:
  shorter sentences, one action per numbered step, one term per concept. Every instruction,
  number, path, event name, flag and backticked token present before is present after.
- **FR-005** — A new eval case grades a report-style answer for fact retention: a planted diff
  with at least three distinct findings, each with its own file:line, severity and failure
  scenario, graded per fact, plus a readability check. The case is recorded in
  `evals/baseline.json`.
- **FR-006** — The affected evals run before and after the body rewrites with the same
  graders. Triggering cases keep their skill-fired result; no case loses more than the judge
  noise floor.
- **FR-007** — The plugin version, the marketplace entry and the CHANGELOG move together in
  the same change.

## Success criteria

- **SC-001** — The frontmatter of every `skills/*/SKILL.md` and `agents/*.md` is byte-identical
  before and after (an extracted-frontmatter diff is empty).
- **SC-002** — On the new fact-retention case, every planted fact is present in the with-arm
  answer in 3 of 3 runs.
- **SC-003** — On the affected eval subset, no case's with-arm score drops below its baseline
  by more than 0.10, and every negative case stays at zero skill-fired.
- **SC-004** — A grep for the residual synonym list returns zero hits in the prose the model
  reads, outside contract names and the glossary's "not to be confused with" column.
- **SC-005** — For each rewritten file, the set of backticked tokens and the set of numbers
  present before is a subset of the set present after, and the file's mean sentence length is
  lower than before.
- **SC-006** — A project config without the new section produces the same PRD, ADR, worklog
  and ledger prose rules as v0.14.7: the skills read "plain" and add no style instruction.

## Constraints & assumptions

- This repo is public: no private project names, paths or tracker ids in any fixture, doc or
  commit (root `CLAUDE.md`).
- Rewrites must not regress the triggering baselines in `evals/baseline.json`; descriptions
  are the whole triggering surface and stay untouched.
- Eval runs cost about $1 per case per tree; the subset is chosen, not the full 69.
- Hooks are a security-sensitive area and are not touched.

## Assumptions (executive)

- Version? → `0.15.0` — a new config section and a default output-style change are behaviour,
  not a patch.
- Config section name and shape? → `## Writing style` with one key, `Docs: plain | ste-80`,
  default `plain`; separate from the existing `## Style` section, which names a code-style
  skill. Matches the request's wording.
- Do MR/PR bodies and tracker comments follow the key or the human-read default? → the key.
  Teammates read them in the forge and never opted in.
- Do subagent reports to the orchestrator carry the rule? → yes, for the reviewer, explorer and
  architect templates: their findings reach the person nearly verbatim, and the template's
  fields are the facts to keep.
- Which principles are "the 80%"? → short sentences (about 20 words, one idea), active voice,
  common words, one term per concept, one action per step, no clause chains with dashes or
  parentheses. Not adopted: the STE dictionary, approved-word lists, noun-cluster limits.
- Which evals run before and after? → about 20 cases: the report-style ones (04, 10, 14, 22,
  24, 26, 44, 45, 47, 58, 62), one positive and the negative per touched skill (02/07, 05/06,
  18/20, 29/34, 36/41, 53/56), and the new case. Three runs, both arms. Roughly $40–60 across
  both passes. The full 69 would cost about three times that for little extra signal.
- Does pandora's own config opt in? → yes, `Docs: ste-80` in `.claude/shipgate.md`, since the
  maintainer's global instructions already ask for this style.
- README, config template, CHANGELOG? → terminology pass only, plus the lines this change
  adds. They are user docs, and the request scopes the style rewrite to skill bodies.
- Where does the terminology audit stand? → a delta pass: v0.14.1 did the full audit. The
  residual groups found at explore: unqualified "the brief", bare "MR" beside "MR/PR",
  "knowledge-base" outside the skill name, "defect" and "problem" beside "finding", "stage",
  "pipeline", "spec" for PRD, and a `## Workflow` heading that collides with the Workflow tool.

## Open questions

None.
