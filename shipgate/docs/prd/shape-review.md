---
type: prd
title: "PRD: The review raises shape findings, and astrolabe states the shape rules"
created: 2026-11-27
updated: 2026-11-27
tags:
  - prd
  - shipgate
  - astrolabe
status: clarified
issue: "#87 (https://github.com/worm2fed/pandora/issues/87); refs #33, #37"
worklog: "./shape-review.worklog.md"
related:
  - ../research/2026-11-27-shape-review.md
  - ../adr/0012-the-canon-reviewer-loads-the-style-skill-itself.md
  - ../adr/0037-a-shape-lens-reviews-the-type-surface-and-proposes-the-shape.md
  - ../adr/0038-the-shape-rules-stay-in-astrolabe-and-shipgate-owns-the-review-contract.md
---

# PRD: The review raises shape findings, and astrolabe states the shape rules

> shipgate's review finds and keeps findings about the shape of code: type design, ownership,
> placement, duplicates and abstractions. astrolabe states the rules that keep such code from
> being written. The two plugins ship as separate deliverables.

## Problem

On a production project with a typed functional codebase, a team's pre-review skill finds a
class of findings that shipgate's review does not raise. It found them on changes that
shipgate had already passed as ready. The class is the shape of the code, not its
correctness.

The evidence is in the research note (`../research/2026-11-27-shape-review.md`), as counts
only:

- Three saved runs of that skill, all on changes that shipgate had passed as ready. Two runs
  finished, on 4 units of work. They raised 34 findings that are not notes: 23 shape and 11
  other. The author accepted 21 of 34, and 15 of the 23 shape findings.
- Shape findings by category, raised and accepted: type design 9 and 5, duplicates 8 and 6,
  ownership 3 and 1, placement 2 and 2, abstractions 1 and 1.
- 6 of the 23 shape findings had a shipgate counterpart at the same site or concept. The
  orchestrator's filter rejected 3 of them with the argument "the values cannot differ" or
  "the function exists to absorb them". 2 were closed with a comment in place of a type
  change. 1 was fixed in another way.
- 9 of the 23 fall under a rule that astrolabe states. 14 fall under rules that astrolabe
  does not state, or states only for a narrow case.
- astrolabe did load. On those three changes, every worker whose brief named it (25 of 25)
  and every canon reviewer (12 of 12) loaded it. Across the project, 216 of 219 code-writing workers whose brief
  named it loaded it before their first code edit. Only 8 of 33 main sessions that edited
  code loaded it, and the design phase never does.
- shipgate's declarations-first round (the types round) ran in 0 of 85 worklogs on that
  project and in 0 of 28 in this repository.

So two things fail. The review does not look for shape, and when a lens sees it, the filter
and the fix field let it go. astrolabe misses rules for the most frequent accepted classes,
and it does not reach the design phase or the orchestrator's own edits.

## Goals & non-goals

**Goals**
- The review raises shape findings on changes that add or change a declaration, and keeps
  them through the filter unless evidence shows the named state cannot be built.
- A shape finding gives the author a proposed shape as code, ready to apply or decline.
- astrolabe states the shape rules that today cover none of the accepted findings, in a form
  that applies when any signature or shared constant is written.
- The style skill reaches the places where shapes are decided: design, and the
  orchestrator's own code edits.
- Each part is measured: deterministic tests first, one eval case where a model run is
  needed.

**Non-goals**
- No change to which plugin owns the style rules beyond what ADR 0038 decides. Moving
  astrolabe into shipgate is a fork in that ADR, not a goal.
- No multi-repository review family, no note posted to a forge, no data-access or flag rulings:
  those parts of the other review are local to its project.
- No serial review round. No blind rerun of the whole review after fixes.
- No change to the journal's disposition schema. A rejection reason is #33's work; this
  feature uses the do-not-flag list that exists.
- No new rule for code that is not typed. Projects with no style skill get only
  language-neutral shape questions.

## Users & stories

- As an author of a change, I want the review to show me where a type admits an illegal state
  and the type that forbids it, so that I fix the class of bug and not one instance.
- As an author, I want a declined point on a pre-existing type to stay declined in the next
  round, so that the review does not ask me again.
- As an orchestrator, I want a shape finding to carry its proof (the current type, the
  illegal state, the proposal), so that I can keep or kill it on evidence and not on whether
  the code works today.
- As a worker writing code in a typed-FP project, I want the shape rules in the style skill's
  always-on core, so that I apply them to a service parameter and not only to a new domain
  type.
- As a maintainer of a project that is not typed-FP, I want the review to cost nothing extra
  on a change with no type surface.

## Functional requirements

**Detection (shipgate)**

- **FR-001** — On a change that adds or changes a declaration, the review raises shape
  findings. A declaration is a type, an interface, a schema, an exported signature or a
  constant that more than one module reads. The categories are type design, ownership,
  placement, duplicates and abstractions.
- **FR-002** — Shape scope covers three sets: the declarations the change adds or edits;
  the pre-existing declarations the change only uses or passes on; and the type on the other
  side of a module or service boundary the change crosses, when that type is in the reviewed
  repository. A declaration the change edits is in the first set, with full severity. A
  pre-existing declaration the change only uses or passes on is capped at MEDIUM and may be
  declined.
- **FR-003** — Each shape finding quotes the current type. It names the illegal state the
  type admits, or the second definition, the wrong owner or the wrong place. It gives the
  proposed shape as code. It states the self-check of the proposal: the named state cannot be
  built in the proposal, and the proposal admits no new illegal state.
- **FR-004** — The filter kills a shape finding only on one of two kinds of evidence: the
  current type already forbids the named state, or the proposal does not remove it. "No
  caller builds it today" and "the two values cannot differ" are no evidence. A comment is
  no fix for a shape finding.
- **FR-005** — The review reports, per run, the declarations it checked and found sound.
- **FR-006** — A shape finding on a pre-existing type can be declined. A declined or rejected
  finding is recorded with its reason, and a later round on the same stream does not raise it
  again.
- **FR-007** — When a correctness finding is a consequence of a shape finding, the report
  lists it under the shape finding. A consequence is a bug that the proposed shape makes
  impossible to write. The shape finding then takes the consequence's severity when that is
  higher.
- **FR-008** — On a project whose config names a style skill, the shape review applies that
  skill's rules. On a project with none, it applies a short list of language-neutral shape
  questions.
- **FR-009** — A change with no type surface (documentation, configuration, CI or migrations
  only) costs nothing extra for shape review.

**Prevention (shipgate)**

- **FR-010** — The design phase applies the configured style skill before it decides a shape:
  a new type, a changed signature, or a declarations task in the build plan.
- **FR-011** — The orchestrator applies the configured style skill before its own code edits,
  fix rounds included, as a worker does.
- **FR-012** — The declarations-first round reviews declarations with the same shape contract
  as FR-001 to FR-005.

**Prevention (astrolabe)**

- **FR-013** — astrolabe states rules for: one owner per value or constant; one definition per
  concept (a derived value, a predicate, a constant, a vocabulary); a signature that asks for no
  more than its body uses, with callers that conform; the common tells of an illegal
  state; parsing at a boundary, where an annotation on an untyped value counts as a cast and a
  comment never excuses a type gap; and a self-check for a proposed shape.
- **FR-014** — astrolabe's always-on core carries the shape rules in short form, so that they
  apply with no reference read. Its routing table sends a writer of any signature or shared
  constant to the full rules.
- **FR-015** — Each new astrolabe rule states the principle in language-portable terms, with
  one TypeScript example written for this repository.

**Measurement**

- **FR-016** — Deterministic tests pin the shape review contract (the lens definition, the
  finder and refuter text, the finding fields, the return shape, the trigger) and the
  astrolabe rule anchors.
- **FR-017** — One eval case with planted shape defects and one sound decoy measures the
  shape review on both session models.

## Success criteria

- **SC-001** — On the eval fixture, with 4 planted shape defects (one each of type design,
  ownership, duplicates and placement) and 1 sound decoy, the review reports at least 3 of
  the 4 defects in each of 3 runs. Each reported defect names its illegal state and gives a
  proposed shape as code. The decoy is a finding in no run. This holds on an Opus 5.5 session
  and on a Fable 5.2 session.
- **SC-002** — On the same fixture, the decoy is in the checked-and-sound list in at least 2
  of 3 runs on each session model.
- **SC-003** — A script computes from the diff whether it has type surface, per language
  family, and a diff of documentation, configuration, CI or migrations only comes out with
  none. A deterministic test pins one fixture per family. The review skill names no shape
  finder for such a diff, on the workflow path and on the agents path, and a prose test pins
  that rule.
- **SC-004** — On the eval fixture, the shape finder's median cost is at most 2.50 USD per
  review, and the review adds no serial step: the shape finder runs in the same parallel
  phase as the other lenses.
- **SC-005** — A rejected or deferred shape finding of round N appears in round N+1's
  do-not-flag list. A deterministic test proves that the list reaches the shape finder's
  prompt, and a prose test pins the step that builds it.
- **SC-006** — Each of the 14 shape findings that today fall under no astrolabe rule, or
  under a rule stated only for a narrow case, maps to a rule in astrolabe 0.5.0. The research note's mapping table shows
  the rule for each one, and the review of the astrolabe deliverable checks the table.
- **SC-007** — The deterministic suites pass: shipgate's three foreground runs and
  astrolabe's new tests, with no private name in any changed file.
- **SC-008** — Measured within 30 days after release, on a project whose config names a style
  skill: at least 80% of the main sessions that edit code load it before their first code
  edit (24% today), and the design phase loads it in at least 80% of the streams that reach
  design.

## Constraints & assumptions

- The repository is public. No text of the other skill enters it, and no name of the
  project, its people, trackers, branches or paths. Evidence enters as counts and categories
  only. [source: CLAUDE.md, issue #87]
- astrolabe and shipgate ship separately, each with its own version and its own entry in
  `.claude-plugin/marketplace.json`. [source: CLAUDE.md]
- Review finders run on Opus on both session models: the worker tier is one below the
  session and never below Opus. So the shape finder costs the same on an Opus and a Fable
  session. Only the orchestrator's own reading of the findings is priced by the session
  model. [source: `skills/review/SKILL.md` Step 1, `skills/model-tiers/SKILL.md`]
- Measured medians per finder on Opus 5.5, with cache writes priced at 1.25 times input:
  canon 0.85 USD, correctness 1.25 USD, conventions and design 1.31 USD, simplicity and
  security 0.65 USD, refuter 0.22 USD. The other review's shape agent: 2.15 USD and 4.9 min.
  [source: the research note]
- One-way doors went to the lead as forks: the new lens that every review with type surface
  pays for, the change to the review workflow's contract, and where the style rules live.
  The user chose the recommended option of each on 2026-11-27, and the lead took the
  measurement fork. ADR 0037 and ADR 0038 hold them, both accepted. [source: the lead's
  messages of 2026-11-27]

## Assumptions (executive)

- [behaviour] [source: issue #87; research note, run C] Does the shape review cover pre-existing types the change touches? → yes, at most MEDIUM, and the author may decline them — run C put 5 of its 10 findings there, and both pre-existing findings in runs A and B were declined
- [behaviour] [no source found in the issue, the review skill and ADR 0012] What severity does a shape finding with no consequence get? → MEDIUM, and with a verified consequence in the diff the consequence's severity — the canon lens already sets MEDIUM as its floor, and the other review tiers a shape with no symptom one step below a shape with one [kept by the user]
- [behaviour] [source: issue #87 comment of 2026-11-27] What does a project with no style skill get? → a short list of language-neutral shape questions in the lens brief; the full rules stay in the style skill — shape rules that every project pays for must be language-neutral
- [technical] [source: research note, cost section] When does the shape finder run? → only when the diff changes a declaration; never on a docs, config, CI or migration-only diff — the other review skips such units too, and it keeps the cost off diffs with no type surface
- [technical] [source: `agents/code-reviewer.md`, `review-workflow.js`] Does "wrong abstractions" stay with the simplicity and security lens? → no, it moves to the shape lens; that lens keeps needless complexity and security — one owner per finding class keeps the dedupe small
- [technical] [blindspot] [no source found in the review skill] Does the re-review after a fix round carry the shape lens? → yes, when the fix diff changes a declaration — a fix that rewrites a type is where a new illegal state appears [kept by the user]
- [technical] [blindspot] [source: `agents/code-reviewer.md` frontmatter] At what effort does the shape finder run? → the agent's default, medium; raise it only on a measured gain in the eval case — a higher effort on every review is a cost that needs evidence [kept by the user]
- [technical] [source: CLAUDE.md "Working here"] Where do astrolabe's tests live? → `astrolabe/tests/`, run with `python3 -m unittest discover -s astrolabe/tests` — the plugins are independent, and shipgate's suite must not load astrolabe's files
- [technical] [source: `.claude/shipgate.md` Knowledge base] Where do the PRD and the worklog live? → one PRD and one worklog in `shipgate/docs/prd/`, with the build plan split into an astrolabe deliverable and a shipgate deliverable — astrolabe has no docs home, and the review is the larger part
