---
type: worklog
title: "Worklog: STE-80 writing principles, scoped by audience"
created: 2026-10-12
updated: 2026-10-12
tags:
  - worklog
  - shipgate
status: designing
prd: "./ste-writing-style.md"
related:
  - "../adr/0006-output-style-rule-as-a-repeated-callout.md"
  - "../glossary.md"
---

# Worklog: STE-80 writing principles, scoped by audience

> Design + build plan companion to `./ste-writing-style.md`. Issue: none / ad-hoc.

---

# Design

## Approach

Inline design, no architect fan: a prose-only change with one real fork, recorded in ADR
0006. Minimal change wins everywhere else: follow the v0.9.0 precedent for a config key, the
case 44 precedent for the eval, the v0.14.1 precedent for the terminology pass.

## The rule (the one text every surface carries)

```
> **Writing for people.** A report a person reads follows the STE-80 principles: sentences
> of about 20 words with one idea each, common words, the glossary's term for each concept,
> one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure
> scenario, command, exit code, count and verdict the report carried stays in it. Code,
> commands and error text go in fenced blocks, not in prose.
```

Placed as a blockquote directly above the output format it governs, in: `agents/code-reviewer.md`
(above "## Findings"), `agents/code-explorer.md` and `agents/code-architect.md` (above their
return format), `skills/review/SKILL.md` (Step 2), `skills/verify/SKILL.md` (above "The gate"),
`skills/structured-debug/SKILL.md` (above step 1), `skills/clarify/SKILL.md` (Executive mode
summary), `skills/design/SKILL.md` (Step 2), `skills/implement/SKILL.md` (On completion),
`skills/feature/SKILL.md` (Always-on disciplines). `tests/test_prose.py` pins the copies.

## Config key

`shipgate/config-template.md` gains, after `## Style`:

```
## Writing style

<!-- Default when absent: plain — the documents shipgate writes into this repo and forge
     (PRD, ADR, worklog, ledger lines, MR/PR body, tracker comments) keep the prose style
     they have today. `ste-80` applies the same "Writing for people" rule the reports
     already follow. Reports to the person driving the flow follow it regardless. -->

- Docs: <plain | ste-80>
```

Reading sentence, one per artifact-writing step, in the skill's own words but the same
meaning: "The config's **Writing style** section (`Docs: ste-80`) applies the Writing for
people rule to this document; absent, a placeholder, or `plain`, write it as before."
Steps: clarify Step 3 (PRD), design Steps 3 and 4 (ADR, worklog), implement's deviation
notes, knowledge-base ledger jot and capture, review "Opening the MR/PR" and the
review-feedback cycle replies, structured-debug's provenance comment. `model-tiers`'s worker
brief format gains the excerpt line for workers that write any of those. README config table
gains the row; `setup`'s interview gains the section in its list of sections to settle.
pandora's own `.claude/shipgate.md` gets `## Writing style` / `- Docs: ste-80`.

## Terminology delta (FR-003)

Unify against `docs/glossary.md`, contract names untouched:

| residual | canonical | note |
|---|---|---|
| bare "the brief" for a subagent's instructions | worker brief / reviewer brief / explorer brief | glossary: always qualified |
| bare "MR" / "PR" in prose | MR/PR | contract `mr-opened`, `MR watcher` stay |
| "knowledge-base" outside the skill name | knowledge base | `knowledge-base` skill name stays |
| "defect", "problem" for a reviewer's finding | finding | "defect" stays for the bug itself in structured-debug |
| "stage" (implement) | step or phase, by meaning | |
| "pipeline" for the flow | flow | |
| "spec" for the PRD | PRD | |
| `## Workflow` heading in structured-debug | `## Steps` | collides with the Workflow tool |

Glossary gains: **Writing for people** (the rule), **report** (prose a person reads: findings,
verify result, summary, verdict), and any term the pass needs.

## Skill-body rewrite (FR-004)

Per file, body only, frontmatter untouched. Principles: split sentences over ~25 words where
a split loses nothing, one action per numbered step, glossary terms, active voice. Not
touched: code blocks, tables' contract cells, backticked tokens, numbers, event names, paths,
the `description:` frontmatter. A fact-parity script (`scratchpad/parity.py`, not in the repo)
reports per file: backticked-token set and number set before ⊆ after, mean sentence length
before vs after, word count delta. Rewrite order: the four heaviest-read files first (feature,
review, implement, structured-debug), then the rest.

## Eval case 70 (FR-005)

`evals/70-review-fact-retention/`: case 44's shape (billing repo, review the commit at HEAD
before the PR). The diff plants three findings of different severity, each in its own file
with its own failure scenario: a BLOCKER (parameterised-SQL rule broken in `db.py`), a HIGH
(quoting bug in `export.py`, a comma in a customer name adds columns), a MEDIUM (money
formatted outside `money.fmt()` in `report.py`, rounding drift on a half-cent). Graders:
three regex graders, one per file:line (`db\.py:\d+`, `export\.py:\d+`, `report\.py:\d+`);
one llm rubric listing the three facts (file, severity, scenario) that passes only when all
three are present; one llm rubric for readability at weight 0.5 (short sentences, one idea
each, facts in fenced blocks or lists; presence, not order); `verdict-not-ready` regex;
`skill-fired` display-only. Prompt and fixture synthetic. Recorded with `compare.py --record`.

## Eval runs (FR-006)

Subset, 3 runs, both arms, via `.claude/skills/run-evals/scripts/run-case.sh shipgate NN
--config-dir <the paying account's config dir>`: 02 04 05 06 07 10 14 18 20 22 24 26 29 34 36
41 44 45 47 53 56 58 62. Before: on the branch at T001, before any prose edit. After: at T007.
Compare with `compare.py`; a |ΔΔ| over 0.10 is read in the transcript before it is believed.

## Reference implementation

- Config key: commit `43ba7e3` (v0.9.0, Code tooling + Thinking lenses) — the last config
  section added with its README row, template block and skill reading sentences.
- Terminology: commit `e9abce6` (v0.14.1) — the glossary and the prose unification.
- Eval case: `evals/44-review-planted-diff/` — fixture, prompt, grader kinds; `68` for a
  behaviour rubric paired with a regex.
- Contract test: `tests/test_workflow_scripts.py` — the test file shape.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/`; nothing under `hooks/`, no script behaviour change.
- Public repo: fixture text synthetic; the diff grepped for private names before review.
- Version bump in the same change as the behaviour (root `CLAUDE.md`).

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings.

## Setup / foundations
- [ ] T001 — Before-run of the eval subset on this branch, no prose edit yet — file(s): `evals/results/<ts>/` — done when: the 23 cases have 3-run with/without results and `compare.py` shows no row beyond noise against baseline.
- [x] T002 — Terminology delta pass + glossary update, own commit — file(s): `skills/*/SKILL.md` bodies, `agents/*.md`, `README.md`, `config-template.md`, `commands/shipgate.md`, `docs/glossary.md` — done when: the residual grep (SC-004) is zero outside contract names and the glossary; frontmatter diff empty; committed as `docs(shipgate): terminology delta`.

## Feature
- [x] T003 — The Writing for people callout in the ten surfaces + `tests/test_prose.py` — file(s): the ten files above, `tests/test_prose.py` — done when: the test fails on a deliberately altered copy and passes on the tree.
- [x] T004 — Config key: template section, README row, setup interview, reading sentences in clarify/design/implement/knowledge-base/review/structured-debug, worker-brief excerpt line in model-tiers, pandora opt-in — file(s): `config-template.md`, `README.md`, `skills/setup/SKILL.md`, the six skills, `skills/model-tiers/SKILL.md`, `.claude/shipgate.md` — done when: every artifact-writing step names the key and the default; `test_prose.py` asserts the template section exists with `Docs:`.
- [x] T005 — Skill-body rewrite, workers one tier down, four groups: (a) feature + review, (b) implement + structured-debug + verify, (c) clarify + design + route-and-map + workspace, (d) knowledge-base + model-tiers + setup + command + agents — file(s): those — done when: parity script passes per file (SC-005), frontmatter diff empty (SC-001), orchestrator has read each diff.
- [ ] T006 [P] — Eval case 70: fixture, prompt, graders; run; record — file(s): `evals/70-review-fact-retention/*`, `evals/baseline.json`, `evals/README.md` table row — done when: with-arm keeps all three facts 3/3 (SC-002) and the row is recorded.

## Polish
- [ ] T007 — After-run of the subset; `compare.py`; read any |ΔΔ| > 0.10 transcript; fix and re-run that case — done when: SC-003 holds.
- [ ] T008 — Version 0.15.0 in `.claude-plugin/plugin.json` and `../.claude-plugin/marketplace.json`; CHANGELOG entry; README glossary pointer mentions the rule — done when: both files say 0.15.0 and the entry names the three audiences and the eval result.
- [ ] T009 — Public-repo grep of the full diff for private names, paths, tracker ids — done when: zero hits.

## Traceability
- FR-001 → T003, T005
- FR-002 → T004
- FR-003 → T002
- FR-004 → T005
- FR-005 → T006
- FR-006 → T001, T007
- FR-007 → T008
- SC-001 → T002, T005 (frontmatter diff)
- SC-002 → T006
- SC-003 → T007
- SC-004 → T002
- SC-005 → T005 (parity script)
- SC-006 → T004 (reading sentences state the default)

## Deviations & notes (filled during implementation)
- 2026-10-12 — explore: the Workflow call was refused by the permission classifier; the orchestrator ran the three lenses itself (journal `deviation`).

## Rejected findings
