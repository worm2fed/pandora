---
type: worklog
title: "Worklog: The review raises shape findings, and astrolabe states the shape rules"
created: 2026-11-27
updated: 2026-11-27
tags:
  - worklog
  - shipgate
  - astrolabe
status: designed
prd: "./shape-review.md"
issue: "#87 (https://github.com/worm2fed/pandora/issues/87)"
related:
  - ../research/2026-11-27-shape-review.md
  - ../adr/0037-a-shape-lens-reviews-the-type-surface-and-proposes-the-shape.md
  - ../adr/0038-the-shape-rules-stay-in-astrolabe-and-shipgate-owns-the-review-contract.md
---

# Worklog: The review raises shape findings, and astrolabe states the shape rules

> Design + build plan companion to `./shape-review.md` (#87). Three deliverables: D1
> astrolabe 0.5.0, D2 shipgate 0.39.0, D3 the paid eval run. D1 and D2 are separate branches,
> PRs and version bumps. D1 ships first and is usable before D2 exists.

---

# Design

## Approach

The user chose the recommended option of each fork on 2026-11-27, through the lead:

- **Detection (ADR 0037, accepted):** a fifth review lens, `shape`, in the same parallel Find
  phase. It runs when a script finds type surface in the diff. It reuses the canon lens's way
  of loading style skills (ADR 0012), adds a finding format that carries its proof, and adds
  a refutation rule that a "works today" argument cannot meet.
- **Prevention (ADR 0038, accepted):** astrolabe stays separate and gains the rules it lacks.
  shipgate loads the style skill in design and before the orchestrator's own code edits.
- **Scope:** pre-existing types the change touches are in, at most MEDIUM, and the author may
  decline them; a decline is recorded and not raised again.
- **Measurement (the lead, executive):** deterministic tests first, a test home for
  astrolabe, and the eval case planned; its paid run waits for the user's go with the cost.

The core trade-off: one more finder on every review with type surface (0.9 to 2.2 USD, the
same on an Opus and a Fable session) against 15 accepted shape findings per 4 units of work
that today reach the author only from another tool.

No architect fan ran. The issue named the three detection options, the maintainer named the
three homes for the rules, and the research note compares them on measured counts and costs.

## Architecture

**D1 — astrolabe 0.5.0.** Text, plus a first test home.

| File | Change |
| --- | --- |
| `astrolabe/skills/astrolabe/SKILL.md` | the non-negotiables gain a short shape group: a closed set is a union in every signature; one owner per value and one definition per concept; a signature asks for no more than its body uses; parse at a boundary. Non-negotiable 1 says a comment names the cause of a boundary cast and never stands in for the fix of a type gap. The routing table gains a row: "writing or changing any signature, or a constant that more than one module reads" → the shape sections |
| `astrolabe/skills/astrolabe/references/domain-modeling.md` | new sections: the tells of an illegal state; one owner per value; one definition per concept; signatures. The type review checklist gains items for ownership, duplicates, signature width and a matching return type, points to non-negotiable 1 for casts instead of restating it, and ends with a self-check for a proposed shape |
| `astrolabe/skills/astrolabe/references/fp-functional.md` | "When NOT to abstract" gains a guard: a domain predicate, derived value or constant spelled twice is a definition, not an abstraction, and gets one named home |
| `astrolabe/skills/astrolabe/references/architecture-and-testing.md` | the "helpers require non-nullable arguments" line moves to the signature section (a pointer stays); validation at the boundary says that an annotation on an untyped value counts as a cast and that a boundary receiving a known shape parses it |
| `astrolabe/tests/test_rules.py` | new: pins every new rule anchor, the routing row, the core's shape group, the checklist items, the self-check, and the private-name check |
| `astrolabe/README.md` | the Status section gets the 0.5.0 entry (astrolabe keeps its release notes there; it has no CHANGELOG) |
| `astrolabe/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.4.0 → 0.5.0, in lockstep |
| `CLAUDE.md` (root) | "Working here" names astrolabe's test command |

**D2 — shipgate 0.39.0.**

| File | Change |
| --- | --- |
| `scripts/signals.py` | `hotspots --diff` gains `type_surface` in its JSON (below) |
| `skills/review/references/review-workflow.js` | `LENS_DEFINITIONS.shape`; `shapeFinderBlock()` (scope, the 9 questions, format, scoring, self-check, the style-skill line when `styleSkills` is given) and `shapeRefuterBlock()`; the `FINDINGS` schema gains an optional `shape` object per finding and an optional top-level `clean` list; a shape-lens finding whose `shape` quotes the type and names the state skips the confidence floor; a survivor keeps `shape` with `proposed` unclipped and the other fields at 600 characters; the return gains `clean` per lens; `styleSkills` with only `shape` no longer logs "no reviewer loads them" |
| `agents/code-reviewer.md` | the lens table gains `shape`; "wrong abstraction" leaves the simplicity + security row; a shape paragraph beside the canon paragraph; the description names the lens |
| `skills/review/SKILL.md` | Step 1: the trigger from `type_surface`, the workflow `lenses` value, the re-review rule, the `doNotFlag` step from earlier rounds; Step 2: the sentences below; Step 6: the fix round points to implement's style rule |
| `skills/design/SKILL.md` | load the configured style skills before deciding a new type, a changed signature or a declarations task; a declarations task also covers a slice that changes an exported signature |
| `skills/implement/SKILL.md` | the style callout covers the orchestrator's own code edits, fix rounds included; the types round's review of the declarations runs `lenses: ['shape']` |
| `tests/test_signals.py`, `tests/test_workflow_scripts.py`, `tests/test_prose.py` | the tests below |
| `evals/79-review-shape-lens/`, `evals/sets.json` | the planned eval case, in `parked` |
| `docs/glossary.md` | "shape finding", "type surface" |
| `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.38.1 → 0.39.0 |

## Type surface, computed (the lead's point 1)

Step 1 already runs `signals.py hotspots --diff <base> --blast --json`. That call computes the
flag too, so the review spends no extra call. `signals.py` reads the diff once more with
`git diff -U0` over the same range (committed and uncommitted changes) and reads each
untracked code file in full. It skips blank lines and comment lines. A changed line is an
added or a removed line. For each file it records the family and whether a changed line
declares something:

| Family | Files | A changed line counts when it declares |
| --- | --- | --- |
| TypeScript and JavaScript | `.ts .tsx .mts .cts .js .jsx .mjs .cjs .vue .svelte`; a `.d.ts` file counts in full | an interface, type, enum, class or namespace; an exported function, const or let; a schema builder (`object`, `union`, `enum`, `literal`, `discriminatedUnion` on a zod, io-ts, yup, joi or typebox namespace); `defineProps` or `defineEmits` with a type |
| Python | `.py .pyi` | a class; a public `def` (name without a leading `_`); a module-level UPPER_CASE constant; `TypeAlias`, `TypedDict`, `NamedTuple`, `Protocol`, `Literal[`, `Enum`, `@dataclass` |
| Go | `.go` | a `type`; an exported func or method; an exported const or var |
| Rust | `.rs` | a struct, enum, trait, type or union; a `pub` fn, const or static |
| JVM and .NET | `.java .kt .kts .scala .cs .fs .swift` | a class, interface, enum, record, struct, object, trait or protocol; a public or protected method signature |
| Interface definitions | `.proto .graphql .gql .thrift .avsc .avdl`, `*.schema.json`, `openapi.*`, `swagger.*` | any changed line |
| No type surface | `.md .rst .txt .adoc`; `.json .yml .yaml .toml .ini .cfg .lock .env*`; CI paths (`.github/`, `.gitlab-ci.yml`, `.circleci/`); `.sql` and files under a `migrations` directory; `.css .scss .html`; images and fonts; `.sh .bash .zsh .ps1` | nothing |
| Unknown | any other file | `null` |

The interface-definition patterns are checked before the "no type surface" row, because a
schema file is JSON or YAML.

The JSON gains `type_surface: {"value": true|false|null, "files": [{"path", "family",
"surface"}]}`. `value` is `true` when any file has type surface, `null` when none has and one
is unknown, `false` when every file has none. The review skill reads it:

- `true` → name the `shape` lens;
- `null` → name it too, and say which unknown files made it run: the review errs toward
  looking;
- `false` → no shape finder;
- signals unavailable → name it, and say why in one line.

The rule list lives in `signals.py` only. The review skill names the key and the three values,
not the patterns, so the two cannot drift. `test_signals.py` pins one fixture repository per
family, an untracked file, a removed declaration, a comment-only change, a docs-only diff and
an unknown extension. The scripts stay Python 3.9 compatible.

## Step 2: the sentences that change (the lead's point 2)

Three shipgate changes close the three places where shipgate's lenses lost shape findings.

1. **The keep rule.** `skills/review/SKILL.md`, Step 2, first bullet, today: "**Keep** findings
   at confidence ≥ 80. Also keep lower-confidence ones whose severity is high enough to be
   worth a check. Verify those yourself (read the cited code), then promote or kill each one
   on evidence." One sentence is added at its end: "Keep every shape-lens finding that quotes
   the current type, whatever its confidence: reading the type checks it."
2. **The kill rule.** A new paragraph right after the canon paragraph ("A canon-lens finding is
   a convention violation, not a matter of taste. Kill one only on evidence that the code
   meets the rule or that the rule does not cover it, the same bar as any other finding."):

   > A shape-lens finding names a state that its type allows. Kill one only on evidence that
   > the type or a constructor already forbids that state, or that the proposed shape still
   > admits it. "No caller builds it today" and "the two values cannot differ" are no
   > evidence. A comment is no fix for a shape finding.

3. **The floor, in the script.** On the workflow path, a shape-lens finding whose `shape`
   carries `current` and `illegal_state` goes to the candidates whatever its confidence. A
   `test_workflow_scripts.py` case feeds one at confidence 55 and asserts it survives.

Both session models read Step 2 (the orchestrator runs on the session model). The paragraph
stays four sentences with no list, because Fable 5.2 does worse with long prescriptive lists,
and it quotes the two arguments word for word, so Opus and Fable both match them when they
appear. `test_prose.py` pins the added sentence, the paragraph's first two sentences and the
two quoted arguments.

## "A comment is no fix": two homes, no copy (the lead's point 3)

- **The review rule** (how a finding closes) lives in shipgate. Its sentence is "A comment is
  no fix for a shape finding." It appears word for word in the script's shape finder and
  refuter blocks, in the agent's shape paragraph and in Step 2. `test_prose.py` asserts the
  four copies are identical, as it does for the Writing-for-people callout.
- **The code rule** (how a cast is written) lives in astrolabe's non-negotiable 1: a boundary
  cast carries a comment that names its cause, and the comment never stands in for the fix of
  a type gap one layer up. The type review checklist points to non-negotiable 1 instead of
  restating it. `astrolabe/tests/test_rules.py` pins it.
- Neither plugin quotes the other. astrolabe works without shipgate, and shipgate reviews
  projects that do not install astrolabe, so a pointer across plugins would point at nothing
  on some machines. The two sentences say different things (one closes a finding, one writes
  a cast), so there is no copy to drift; each plugin's tests pin its own sentence.

## The orchestrator's own edits load the style skill (the lead's point 4)

- **Where.** One home: `skills/implement/SKILL.md`, the style callout under the config
  callout. It gains: "This covers your own code edits too, a review fix round included: invoke
  the skill once per session, before your first code edit." `skills/review/SKILL.md` Step 6,
  "Before a fix round", gains one pointer sentence: "The fix round is implement work: its
  style rule applies before the first code edit." The review-feedback cycle's step 2 already
  routes changes back to implement, so it needs no text.
- **Cost per fix round,** measured from the files: astrolabe's `SKILL.md` is 5,239 characters
  (about 1,300 tokens); with `domain-modeling.md` (18,712 characters today, about 4,700
  tokens; about 5,500 after 0.5.0) a type change reads about 7,000 tokens. The first read is a
  cache write: about 0.01 to 0.04 USD on Opus 5.5 and 0.02 to 0.07 USD on Fable 5.2. Every
  later turn re-reads it from cache at 0.20 USD per million tokens on both: about 0.0003 to
  0.0014 USD a turn, about 0.07 USD over 50 turns at most. So at most about 0.15 USD per fix
  round, once per session.

## The language-neutral questions (the lead's point 5)

The shape finder carries these 9 lines when no style skill is configured, and as a floor when
one is. The cap is 10 lines; `test_prose.py` counts them.

1. Closed sets: is each finite set of values a closed type (a union, an enum, a literal), not a string or a number?
2. States: can the type hold a field combination the domain forbids (all fields optional, a flag with one-branch fields, two ways to say "none")?
3. Meaning: does each type and each field carry one meaning for every reader?
4. Signatures: does each function take the narrowest input its body needs, and does its return type match every branch?
5. Owner: does each value, constant and derived value have one owner that the others read instead of recompute?
6. One definition: is each concept (a type, a predicate, a constant, a derived value) defined once?
7. Place: does each declaration sit in the layer and module that own it?
8. Boundary: is outside input parsed into a type where it enters, not cast or annotated?
9. Purpose: does each new abstraction's name say what it does, and does it remove more than it adds?

## Data flow

A review of a diff with type surface, on the workflow path:

1. Step 1 runs the signals as today; the JSON now carries `type_surface`. The orchestrator
   reads the worklog's Rejected findings and the stream's rejected or deferred dispositions,
   and puts each one into `doNotFlag` with its reason.
2. `Workflow` runs the script with `lenses` that include `shape` (and `canon` when the config
   names a style skill), `styleSkills`, `finderBrief` and `doNotFlag`.
3. The Find phase runs every finder in parallel. The shape finder loads the style skills,
   reads the diff, the pre-existing types it touches and the type across a crossed boundary,
   and returns findings with `shape` objects and a `clean` list.
4. Dedupe merges a shape finding and a canon finding at one line, keeping both lenses. A
   shape-lens finding with its proof skips the floor.
5. The Verify phase sends the BLOCKER/HIGH candidates to refuters; a refuter of a shape-lens
   finding gets the shape refutation rule.
6. The script returns survivors (with `shape`), killed, belowFloor, counts, coverage and
   `clean` per lens.
7. Step 2 keeps and kills by the sentences above, lists each correctness survivor whose bug a
   proposal makes impossible under that shape finding, and ranks.
8. A decline of a pre-existing shape finding is a `review-disposition` with `deferred`; its
   reason goes into the worklog's Rejected findings. The next round's step 1 reads it.

The agents path does the same by hand: one more `code-reviewer` brief for the shape lens.

## API / contract changes

All additions are optional; nothing is removed.

- `signals.py hotspots --diff` JSON: `type_surface` (above). Other keys unchanged.
- Workflow `args.lenses` accepts `shape`.
- `FINDINGS.findings[].shape` (optional): `{current, illegal_state, proposed, self_check,
  pre_existing}`, four strings and one boolean.
- `FINDINGS.clean` (optional): at most 10 strings.
- Return: a survivor may carry `shape`; the return carries `clean: {<lens>: [...]}`.

The journal, the HUD and the disposition keys do not change.

## Reference implementation

The canon lens in `skills/review/references/review-workflow.js`: `canonFinderBlock()`,
`canonRefuterBlock()`, the `styleSkills` guard and the lens-conditional assembly in
`finderPrompt()` and `refuterPrompt()`. It is the one lens with its own loading step and its
own refutation rule, reviewed under ADR 0012 and pinned by `tests/test_workflow_scripts.py`.
The shape lens mirrors its anatomy and does not touch it. For `type_surface`, the reference is
`ui_flag()` in `signals.py`: a per-diff flag the hotspots JSON already carries. For astrolabe,
the reference is the type review checklist's form: a numbered question per rule, "a no is a
finding".

## Pre-mortem and reversibility

- **Failure 1: the lens floods reviews.** Pre-existing types and MEDIUM findings pile up, the
  author declines most, and rounds grow (#33 counts 28 of 62 first verdicts not ready).
  Mitigation: pre-existing findings are at most MEDIUM and can be deferred with no fix round;
  every decline enters the next round's `doNotFlag`.
- **Failure 2: the type-surface rule misfires.** Too wide, and every diff pays for a shape
  finder; too narrow, and a type change gets none. Mitigation: one fixture per family; an
  unknown family runs the lens and says so; `value` counts per verdict can be read from the
  journal later.
- **Failure 3: proposals that do not compile.** Mitigation: the self-check field says whether
  the proposal was type-checked; Step 2 reads the proposal before it reaches the author.
- **Reversibility.** The lens can leave in one release; the schema fields are optional, so a
  consumer that ignores them keeps working; astrolabe's rules are additions. The one-way part
  was the decision itself, now accepted.

## CLAUDE.md / impact-map compliance

- Public repository: no text of the other review, no private name, path, tracker id or person
  in any file, test, fixture or commit message. Every deliverable ends with the grep, and a
  hit is a blocker.
- Version bumps: astrolabe 0.5.0 and shipgate 0.39.0, each with its `marketplace.json` entry
  in the same change. shipgate's release gets the tag `shipgate--v0.39.0` once on `main`.
- Release notes: shipgate's in `CHANGELOG.md` only; astrolabe's in its README Status section.
- No hook changes, so the hook contract and its security review are not touched.
- Tests: shipgate's three foreground runs; astrolabe's own discover run.

## Risk ranking (signals, 2026-11-27, graph source)

| File | Commits | Fix rate | Risk |
| --- | --- | --- | --- |
| `shipgate/skills/review/SKILL.md` | 34 | 26% | top |
| `shipgate/tests/test_prose.py` | 15 | 33% | top |
| `shipgate/skills/implement/SKILL.md` | 23 | 17% | top |
| `shipgate/skills/design/SKILL.md` | 22 | 14% | top |
| `shipgate/agents/code-reviewer.md` | 11 | 27% | top |
| `shipgate/tests/test_workflow_scripts.py` | 5 | 20% | high |
| `shipgate/skills/review/references/review-workflow.js` | 5 | 0% | high |
| `astrolabe/skills/astrolabe/SKILL.md` | 3 | 0% | high |
| `astrolabe/skills/astrolabe/references/domain-modeling.md` | 2 | 0% | mid |

`signals.py` and `test_signals.py` join the plan; they are ranked in the design-committed
event. The review skill and the prose tests are the hottest files, so their tasks come after
the script and its tests, and each starts from a pin of the current text.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings. Tests are tasks. D1
ships first and needs nothing from D2; D2 needs nothing from D1's release.

## D1 — astrolabe 0.5.0

- [x] T001 — astrolabe test home: `astrolabe/tests/test_rules.py` pins the new rule anchors, the routing row, the core's shape group, the checklist items and the self-check, and checks that no file names a private project — file(s): `astrolabe/tests/test_rules.py` — done when: it fails on 0.4.0 for each missing anchor and passes the private-name check
- [x] T002 — domain-modeling: the tells of an illegal state, one owner per value, one definition per concept, signatures; the checklist items, the pointer to non-negotiable 1, the proposal self-check — file(s): `astrolabe/skills/astrolabe/references/domain-modeling.md` — done when: the T001 anchors for this file pass; every rule has one TypeScript example written fresh
- [x] T003 [P] — fp-functional: the "a concept spelled twice is a definition" guard — file(s): `astrolabe/skills/astrolabe/references/fp-functional.md` — done when: its T001 anchor passes
- [x] T004 [P] — architecture-and-testing: the helper-argument line moves to the signature section with a pointer; an annotation on an untyped value counts as a cast — file(s): `astrolabe/skills/astrolabe/references/architecture-and-testing.md` — done when: its T001 anchors pass
- [x] T005 — SKILL.md: the core's shape group, the routing row, non-negotiable 1's comment sentence — file(s): `astrolabe/skills/astrolabe/SKILL.md` — done when: its T001 anchors pass and the core grows by at most 15 lines
- [x] T006 — release: README Status 0.5.0; plugin.json and marketplace.json 0.5.0; root CLAUDE.md names `python3 -m unittest discover -s astrolabe/tests` — file(s): `astrolabe/README.md`, `astrolabe/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CLAUDE.md` — done when: both version strings read 0.5.0
- [x] T007 — verify D1: astrolabe's tests pass; the research note's table names a 0.5.0 rule for each of the 14 kinds (SC-006); the private-name grep over the diff is empty — file(s): `shipgate/docs/research/2026-11-27-shape-review.md` — done when: all three hold, with the commands in a verify-run
- [ ] T008 — STOP after D1: review D1, then ask the user's commit go and publish go for its own PR; D1 is usable by workers and the canon lens as soon as it merges — file(s): none — done when: the user answered

## D2 — shipgate 0.39.0

- [ ] T010 — type-surface tests first: one fixture repository per family, an untracked file, a removed declaration, a comment-only change, a docs-only diff, an unknown extension, and the three top-level values — file(s): `shipgate/tests/test_signals.py` — done when: the new cases fail on 0.38.1
- [ ] T011 — `type_surface` in `hotspots --diff` — file(s): `shipgate/scripts/signals.py` — done when: T010 passes and the existing signals tests still pass, on Python 3.9 syntax
- [ ] T012 — workflow contract tests first: the `shape` definition; the finder prompt carries scope, the 9 questions, format, scoring and the comment sentence, and the style-skill line only with `styleSkills`; the refuter block for a shape-lens finding; a shape finding at confidence 55 with its proof survives; `shape.proposed` unclipped; `clean` per lens; `doNotFlag` reaches the shape finder; a shape and a canon finding at one line merge; `styleSkills` with only `shape` logs no warning — file(s): `shipgate/tests/test_workflow_scripts.py` — done when: the new cases fail on 0.38.1
- [ ] T013 — the script: the lens, the two blocks, the schema fields, the floor rule, the survivor and return fields, the warning fix — file(s): `shipgate/skills/review/references/review-workflow.js` — done when: T012 passes and the existing workflow tests still pass
- [ ] T014 — prose pins first: the review skill's trigger and three values, the re-review rule, the `doNotFlag` step, the Step 2 added sentence and paragraph; the agent's `shape` row; design's style load; implement's own-edit sentence and types-round lens; the four identical copies of "A comment is no fix for a shape finding."; the neutral list at most 10 lines — file(s): `shipgate/tests/test_prose.py` — done when: the new pins fail on 0.38.1
- [ ] T015 — the agent: the `shape` row, the abstraction clause moved, the shape paragraph, the description — file(s): `shipgate/agents/code-reviewer.md` — done when: its T014 pins pass
- [ ] T016 — the review skill: Step 1 trigger and `lenses`, re-review, `doNotFlag` from earlier rounds; Step 2 sentences; Step 6 pointer — file(s): `shipgate/skills/review/SKILL.md` — done when: its T014 pins pass
- [ ] T017 [P] — design: load the style skills before deciding a shape; a declarations task covers a changed exported signature — file(s): `shipgate/skills/design/SKILL.md` — done when: its T014 pins pass
- [ ] T018 [P] — implement: the own-edit sentence in the style callout; the types round runs `lenses: ['shape']` — file(s): `shipgate/skills/implement/SKILL.md` — done when: its T014 pins pass
- [ ] T019 — eval case 79, planned: a TypeScript fixture with four planted defects (type design, ownership, duplicates, placement) and one sound decoy, no style skill in the config; prompt; graders per defect, the decoy, the clean list and the verdict; a script grader that counts no Edit or Write; `parked` in sets.json — file(s): `shipgate/evals/79-review-shape-lens/`, `shipgate/evals/sets.json` — done when: `test_eval_fixtures.py` builds it and `test_eval_graders.py` passes on canned traces; nothing runs it
- [ ] T020 [P] — glossary: "shape finding", "type surface" — file(s): `shipgate/docs/glossary.md` — done when: each term is defined once
- [ ] T021 — release: CHANGELOG 0.39.0; plugin.json and marketplace.json 0.39.0 — file(s): `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: both version strings read 0.39.0
- [ ] T022 — verify D2: the three foreground test runs pass; the private-name grep over the diff is empty — file(s): none — done when: the verify-run names the three commands with exit 0
- [ ] T023 — STOP after D2: review D2, then ask the user's commit go and publish go; after the merge, `claude plugin tag --push` in `shipgate/` — file(s): none — done when: the user answered

## D3 — the paid eval run

- [ ] T030 — STOP: ask the user's go for the paid run of case 79, with case 74's measured cost (1.11 USD a run on Opus, 1.68 on Fable) and the projection (2 to 3 USD on Opus, 3 to 4 on Fable; 15 to 21 USD for 3 runs on each model) — file(s): none — done when: the user answered; nothing runs before the go
- [ ] T031 — after the go: run case 79 on Opus 5.5 and Fable 5.2, 3 runs each, through the run-evals scripts; record the baseline rows; move the case to `kept` if SC-001, SC-002 and SC-004 hold — file(s): `shipgate/evals/baseline.json`, `shipgate/evals/sets.json` — done when: the rows exist with their measured cost
- [ ] T032 — 30 days after the release: re-run the load count on a project that names a style skill (SC-008) — file(s): none — done when: the counts are in a ledger line

## Traceability

- FR-001 → T011, T012, T013, T015, T016
- FR-002 → T012, T013, T015
- FR-003 → T012, T013, T015
- FR-004 → T012, T013, T014, T016
- FR-005 → T012, T013
- FR-006 → T012, T014, T016
- FR-007 → T014, T016
- FR-008 → T012, T013
- FR-009 → T010, T011, T014, T016
- FR-010 → T014, T017
- FR-011 → T014, T016, T018
- FR-012 → T014, T018
- FR-013 → T001, T002, T003, T004
- FR-014 → T001, T005
- FR-015 → T002, T003, T004, T005
- FR-016 → T001, T010, T012, T014
- FR-017 → T019, T030, T031
- SC-001 → T019, T031
- SC-002 → T019, T031
- SC-003 → T010, T014, T016
- SC-004 → T013, T031
- SC-005 → T012, T014, T016
- SC-006 → T002, T007
- SC-007 → T007, T022
- SC-008 → T017, T018, T032

## Deviations & notes (filled during implementation)

- 2026-11-27 — no explorer fan and no architect fan: the orchestrator read every file in
  scope itself, and the issue and the maintainer's comment named the options; the research
  note compares them on counts.
- 2026-11-27 — the lead's six design points are folded into the Design section: the computed
  type surface, the Step 2 sentences, the two homes of the comment rule, the own-edit rule and
  its cost, the 9-line question list, and D1 ahead of D2.
- 2026-11-27 — D1 build: the orchestrator wrote the rule text itself. The text is
  judgment work, and a worker would run on Opus too, so a dispatch saves nothing.
- 2026-11-27 — T001: the journal derives a verify-run's outcome from its exit codes. The
  test-first proof is a grep of the run's summary for the 14 planned failures (exit 0).
- 2026-11-27 — T001: the private-name test checks generic forms (a home path, an email
  other than the author's, a URL, a tracker key, a merge-request reference). Real
  project names come only from the `PANDORA_PRIVATE_NAMES` variable, so no name is
  committed; without it, that one test skips.
- 2026-11-27 — T005/T007: the research note planned "a pointer from the core" for
  placement. Non-negotiable 11 restates it in short form ("each concept one definition,
  beside the type it reads"), with no extra bullet. After review round 1 the core has 101
  lines (cap 102).
- 2026-11-27 — Gap table A's row on pre-existing types ("new code narrows an open
  pre-existing type at its own boundary") was in no D1 task. Round 3 added it as one
  sentence; round 4 removed it on the lead's word, because it needs more than one sentence
  (where the narrowing happens, and that it is a parser, not the re-validation that
  "Validation at exactly two boundaries" forbids). It is a rule for a later astrolabe change.

- 2026-11-28 — Review round 1, security pass: the briefed security reviewer found short
  runs of words in the research note, ADR 0037 and the PRD that match the private review
  skill. They were reworded with the same meaning (the scope list in FR-002, ADR 0037 and
  the note; five phrases in the note's section 1). The reviewer opened the private skill to
  compare, against the lead's rule for this build; its brief did not forbid it. Reported
  to the lead.
- 2026-11-28 — Review round 3, on the lead's go: domain-modeling.md grows by about 1,040
  tokens, to about 5,720 (the design estimated about 800). The two largest examples shrank,
  and the tells, the checklist items and the self-check were cut to their short form.
- 2026-11-28 — The user raised the size cap for domain-modeling.md to about +1,250 tokens
  (gate-decision, actor user). Round 4 restores what the round-3 cut lost: the concrete case
  of three tells, the sentinel in the `Loan` example, the self-check's "must add no new
  illegal state" and "narrow each parameter until the body needs no check of it". The file
  grows by about 1,150 tokens, to about 5,830.
- 2026-11-28 — Review rounds 3 and 4, N5 on the lead's word: FR-002 and ADR 0037 now say
  that a declaration the change edits is in the first set, with full severity, and that a
  pre-existing declaration the change only uses or passes on is capped at MEDIUM and may be
  declined. The lead tells the user.
- 2026-11-28 — Deferred from round 3 on the lead's word, one line each:
  - L1: "an annotation on an untyped value is a cast" also reads on `: unknown`; non-negotiable 1 now lets a cast target `unknown`, so the clash is smaller.
  - L3: item 4 also reads bodies through the return-type tell; the intro names items 7 to 10.
  - L4: `isPast` takes `Instant` first, while "a function's home is decided by the type of its parameter" could point there.
  - L6: the self-check's "the named illegal state" has no antecedent inside astrolabe.
  - L7: the host-name form covers 8 top-level domains; the macOS and Linux home-path branches have no self-test case.

## What changed

- astrolabe states the shape rules for every signature and shared value: a closed set is a
  union, one owner per value, one definition per concept, a signature that asks only for
  what its body uses.
- The core names these rules in non-negotiable 11. A cast may target only `unknown`, or a
  type that a parser then narrows; untrusted input is parsed. A cast's comment never stands
  in for fixing the type.
- The type review checklist asks about owners, duplicates, signature width and return types,
  and ends with a self-check for a proposed shape.
- astrolabe has its own tests: `python3 -m unittest discover -s astrolabe/tests`.

## Review round 1

Workflow run `wf_35fbca74-01a`, three lenses (correctness, conventions + design, simplicity +
security): 40 found, 30 after dedupe, 12 candidates, 2 refuters, 12 survivors, 0 killed. A
briefed security reviewer read 14 of 14 files.

- F1 HIGH `astrolabe/skills/astrolabe/SKILL.md:52` — non-negotiable 1 still allowed a commented cast of a known shape at a boundary; fixed: a cast is allowed only where no schema describes the input.
- F2 MEDIUM `astrolabe/skills/astrolabe/SKILL.md:95` — non-negotiable 11 put a value's owner in the module that owns its type; fixed: the owner stores or computes the value.
- F3 MEDIUM `astrolabe/skills/astrolabe/SKILL.md:92` — the parse bullet pointed to #1 only; fixed: it points to the validation section.
- F4 MEDIUM `astrolabe/skills/astrolabe/references/domain-modeling.md:453` — the good `canBorrow` counted returned loans; fixed: it takes two `LoanCount` values.
- F5 MEDIUM `astrolabe/skills/astrolabe/references/architecture-and-testing.md:75` — the annotation paragraph restated non-negotiable 1; fixed: it states the parse rule and points to #1.
- F6 MEDIUM `astrolabe/skills/astrolabe/references/fp-functional.md:216` — the guard covered any look-alike predicate; fixed: one domain fact only.
- F7 MEDIUM `astrolabe/skills/astrolabe/references/domain-modeling.md:459` — the checklist intro ignored that items 7 to 9 read bodies; fixed.
- F8 MEDIUM `shipgate/docs/research/2026-11-27-shape-review.md:13` — word runs that match the private skill (security pass); fixed, with ADR 0037 and the PRD.
- F9 LOW `astrolabe/tests/test_rules.py:214` — the forms flagged UTF-8 and a version pin; fixed with standard keys and a letter top-level domain.
- F10 LOW `astrolabe/tests/test_rules.py:121` — numbered pointers were not pinned; fixed with a pointer test.
- F11 LOW `astrolabe/tests/test_rules.py:223` — a binary file broke the scan; fixed: text suffixes only.
- F12 LOW `CLAUDE.md:36` — the claim "not wording" was wrong; fixed.
- F13 LOW `astrolabe/tests/test_rules.py:216` — missing forms (`~/`, host names); fixed.
- F14 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:493` — the self-check followed the research note's section 1 too closely (BLOCKER at confidence 40); rewritten as a compile check plus items 1 to 10.
- F15 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:312` — the legacy-map section contradicted one definition per concept; it now names itself the one exception.
- F16 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:442` — the Signatures sentence fought non-negotiable 3; a fact no type carries is now a precondition.
- F17 LOW `astrolabe/skills/astrolabe/references/architecture-and-testing.md:86` — the good parse example was no Either; fixed.
- F18 LOW `shipgate/docs/research/2026-11-27-shape-review.md:156` — the placement cell claimed a pointer; fixed to "restates it in short form".
- F19 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:477` — item 4's fix covered only grouped fields; fixed.
- F20 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:387` — the Loan union used `status`, not the canon's `type` tag; fixed.
- F21 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:489` — item 9 made every projection a finding; fixed.
- F22 LOW `astrolabe/skills/astrolabe/references/architecture-and-testing.md:76` — "an `unknown` argument" does not compile as an annotation; removed.
- F23 LOW `astrolabe/tests/test_rules.py:48` — the helpers read headings inside fenced code; fixed (also `:39`).
- F24 LOW `astrolabe/README.md:57` — two inaccurate sentences in the 0.5.0 note; fixed.
- F25 LOW `astrolabe/tests/test_rules.py:211` — the forms missed `~/` paths and host names; fixed.
- F26 LOW `astrolabe/skills/astrolabe/SKILL.md:55` — three phrasings for "shared value"; now one term.

### Rejected findings

- `astrolabe/tests/test_rules.py:162` (LOW 55): the negative check on item 10 is weak; the new pointer test carries the positive check.
- `astrolabe/skills/astrolabe/SKILL.md:46` (LOW 50): the routing examples are not stale; "Multiple match → read all that match" covers the new row.
- `astrolabe/skills/astrolabe/SKILL.md:91` (LOW 45): non-negotiable 11 restates the shape rules in short form by design (FR-014).

## Review round 2

One reviewer carried all lenses over the fix diff and read only files in this worktree. It
confirmed 24 of the 26 round-1 findings as fixed. F7 is partly reopened (LOW) and F26 is
mostly fixed (LOW). It raised 2 new MEDIUM findings, so the build stops here and the list
goes to the lead (the lead's cap: a new MEDIUM or higher after fixes stops the build).

- F7 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:461` — reopened: item 10 also reads code in bodies, so the intro should say items 7 to 10.
- F26 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:360` — mostly fixed: "a shared constant" still sits beside "shared value".
- N1 MEDIUM `astrolabe/skills/astrolabe/SKILL.md:53` — non-negotiable 1 allows a cast where "no schema describes" the input, and non-negotiable 11 forbids a cast of a "known shape"; a known shape with no schema yet falls between them.
- N2 MEDIUM `astrolabe/skills/astrolabe/references/architecture-and-testing.md:84` — the good parse example calls `response.json()` outside the effect-boundary helper that the same file requires, and its comment claims every bad payload is a typed failure.
- N3 LOW `astrolabe/skills/astrolabe/references/architecture-and-testing.md:75` — the parse paragraph adds a message and a response under "exactly two boundaries" without saying that every inbound edge counts as the first one.
- N4 LOW `astrolabe/skills/astrolabe/SKILL.md:95` — "beside the type it reads" in the core does not match "in the module that owns it" in One definition per concept.
- N5 LOW `shipgate/docs/prd/shape-review.md:106` — the reworded scope ("uses, changes or passes on") puts a changed pre-existing type in two scope sets; "uses or passes on" keeps it in one (also ADR 0037 and the research note).
- N6 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:318` — "the one sanctioned exception" overclaims next to checklist item 2.
- N7 LOW `astrolabe/tests/test_rules.py:254` — the private forms are narrow (8 lowercase top-level domains, no `C:\Users\`, no `.ts` or `.sh`), and the self-test has no case for the email, URL or merge-request form.
- N8 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:454` — the good `canBorrow` takes two `LoanCount` values, which a caller can swap.
- N9 LOW `astrolabe/tests/test_rules.py:92` — some pins are body phrases, not anchors.
- N10 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:360` — lines wider than the file's wrap width (also `:479` and the research note's `:15`, `:59`, `:62`).

## Review round 3

On the lead's go. The fixes, each confirmed by the astrolabe tests where a test can pin it:

- N1 `astrolabe/skills/astrolabe/SKILL.md:53` — one term: a cast only where the input's shape is not known; a known shape is parsed (core, README; checklist 10 points to #1).
- N2 `astrolabe/skills/astrolabe/references/architecture-and-testing.md:84` — the good example reads the body through the effect-boundary helper, then parses it.
- F7 `astrolabe/skills/astrolabe/references/domain-modeling.md:459` — the intro says items 7 to 10.
- F26 and N10 `astrolabe/skills/astrolabe/references/domain-modeling.md:360` — one term, "shared value"; the wide lines are rewrapped (also the research note).
- N3 `astrolabe/skills/astrolabe/references/architecture-and-testing.md:75` — a request, a message and a response each count as the first boundary.
- N4 `astrolabe/skills/astrolabe/SKILL.md:95` — one phrase in both homes: "beside the type it is about".
- N5 `shipgate/docs/prd/shape-review.md:106` — "uses or passes on" in the PRD, ADR 0037 and the research note.
- N6 `astrolabe/skills/astrolabe/references/domain-modeling.md:318` — "a sanctioned exception".
- N7 `astrolabe/tests/test_rules.py:254` — a self-test case per form, `C:\Users\`, and `.ts`, `.js`, `.sh` files.
- N8 `astrolabe/skills/astrolabe/references/domain-modeling.md:454` — `canBorrow` takes one `LoanCount`, so no two arguments can swap.
- N9 `astrolabe/tests/test_rules.py:92` — the docstring says a rule with no heading is pinned by the phrase that states it.

The round-3 re-review (one reviewer, the round-3 diff only, nothing read outside the
worktree) confirmed N1 to N10, F7 and F26 as fixed; N7 keeps a LOW residue. It found the
FR-013 rules all present after the shortening, and the research note's 0.5.0 column still
names real rules. It raised 2 new MEDIUM findings, so the build stops here and the list goes
to the lead, who takes it to the user.

- M1 MEDIUM `astrolabe/skills/astrolabe/references/domain-modeling.md:419` — "narrows it at its own boundary" names an undefined boundary and conflicts with "Validation at exactly two boundaries", which forbids re-validating typed internal data; it also does not say the narrowing is a parser, never a cast.
- M2 MEDIUM `astrolabe/skills/astrolabe/SKILL.md:54` — "a cast only where the input's shape is not known" can read as permission to cast an undocumented payload, the pattern research row 2 set out to close.
- L1 LOW `astrolabe/skills/astrolabe/SKILL.md:57` — "an annotation on an untyped value is a cast" also catches the safe `: unknown` annotation.
- L2 LOW `astrolabe/skills/astrolabe/references/architecture-and-testing.md:85` — the good parse example lets `any` from `response.json()` into the pipeline.
- L3 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:436` — item 4 also reads bodies through the return-type tell; the intro names only items 7 to 10.
- L4 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:410` — `isPast` puts `Instant` first, while "a function's home is decided by the type of its parameter" could send it there.
- L5 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:427` — `canBorrow` compares unwrapped numbers instead of using the value object's `Ord`.
- L6 LOW `astrolabe/skills/astrolabe/references/domain-modeling.md:470` — "the named illegal state" has no antecedent inside astrolabe.
- L7 LOW `astrolabe/tests/test_rules.py:261` — the host-name form lists 8 lowercase top-level domains; the macOS and Linux home-path branches have no self-test case.

## Review round 4

On the lead's word, by removal where possible:

- M1 `astrolabe/skills/astrolabe/references/domain-modeling.md:419` — removed: the pre-existing-type sentence, its pointer in checklist item 9 and its test (see Deviations).
- M2 `astrolabe/skills/astrolabe/SKILL.md:54` — non-negotiable 1 now says a cast may target only `unknown`, or a type that a parser then narrows; untrusted input is parsed. The README, non-negotiable 11, the validation paragraph and the pins use the same words.
- L2 `astrolabe/skills/astrolabe/references/architecture-and-testing.md:85` — the good example reads the body as `unknown` through the effect-boundary helper.
- L5 `astrolabe/skills/astrolabe/references/domain-modeling.md:427` — `canBorrow` compares with `loanCountOrd`.
- L1, L3, L4, L6 and L7 are deferred (see Deviations).

The round-4 check (one reviewer, these edits only, nothing read outside the worktree)
confirmed M1, M2, L2, L5 and the scope wording in FR-002 and ADR 0037. It raised 5 LOW
findings caused by the edits. Four are one-word or one-clause fixes made after the check,
with no further review; one is rejected.

- R1 LOW `astrolabe/README.md:50` — a stray "a" before "untrusted input"; fixed.
- R2 LOW `astrolabe/skills/astrolabe/SKILL.md:101` — non-negotiable 11's "never cast" read against the example's `unknown` annotation; fixed: "never cast to its domain type".
- R3 LOW `shipgate/docs/research/2026-11-27-shape-review.md:236` — the gap-table cell still proposed the removed rule; fixed: it says the rule was left out of 0.5.0.
- R4 LOW `astrolabe/tests/test_rules.py:226` — the test name still said "known shape"; renamed.

### Rejected findings

- `astrolabe/skills/astrolabe/references/architecture-and-testing.md:86` (LOW 40): the `unknown` annotation lacks a cause comment; the example's label comment names the cause.

The restore under the user's cap (see Deviations) and R1 to R4 go to one more check: it
reads only those lines and asks whether they bring back any of the fixed findings N1 to N10
or M2.

The check of the restore confirmed every restored line and R1 to R4; none brings back a fixed
finding.

- R5 LOW `astrolabe/README.md:53` — one line over the wrap width and "untrusted input is parsed" twice in the 0.5.0 entry; fixed by one rewrap.

### Rejected findings

- `astrolabe/skills/astrolabe/references/domain-modeling.md:431` (LOW 25): "each caller proves the narrow type once" might read as re-validation; in context it is a type proof, and the next sentence names the precondition case.
