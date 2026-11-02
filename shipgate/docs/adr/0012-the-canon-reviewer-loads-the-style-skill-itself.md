---
type: adr
title: "0012. The canon reviewer loads the style skill itself"
created: 2026-11-02
updated: 2026-11-02
tags:
  - adr
  - shipgate
status: accepted
date: 2026-11-02
issue: "#11"
related: ["0006-output-style-rule-as-a-repeated-callout.md"]
---

# 0012. The canon reviewer loads the style skill itself

> The `code-reviewer` agent gets the `Skill` tool. A `canon` lens reviewer loads each style
> skill the config names before it reads the diff, and a refuter of a canon finding loads
> them too.

## Context

Issue #11: the review fan has no lens that holds the style canon. A reviewer that does not
hold the canon treats its rules as taste. One recorded verdict declined a branded type as
"a prose convention". The `code-reviewer` agent has `Glob, Grep, Read, Bash, WebFetch,
WebSearch`, so it cannot load a skill. The canon lives in a project or plugin skill, which
can be large and can change between releases.

## Decision

Add `Skill` to the `code-reviewer` agent's tools. Add a `canon` lens to the agent's lens
table, to the review skill, and to the review Workflow script. The script takes
`styleSkills`, a list of skill names, and refuses a `canon` lens without it. The canon
finder's prompt names the skills to load first, and says that a finding cites the canon
rule it breaks and is scored on whether the code breaks it, never on taste. A refuter of a
finding the `canon` lens reported gets the same instruction, and "a matter of taste" does
not count as a refutation.

## Alternatives considered

- **Paste the canon into the brief.** It needs no new tool, but a canon skill can be large,
  it would be copied into every finder and refuter prompt, and the copy drifts from the
  skill. The orchestrator would also have to find and read the skill's files itself.
- **A new `canon-reviewer` agent.** It isolates the change, but it duplicates the scoring
  rules and the report format of `code-reviewer`, and the Workflow script would need a
  second agent type for one lens.

## Consequences

- Every `code-reviewer` instance can now load skills. The prompt limits the canon lens to
  the named skills; other lenses have no reason to load one.
- A canon that is not installed in the reviewer's environment fails visibly: the reviewer
  reports that the skill did not load.
- The canon lens costs one more finder per review when the config names a style skill.
