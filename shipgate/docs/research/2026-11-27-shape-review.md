---
title: shape review — what a team's pre-review finds that shipgate's review does not, and why
date: 2026-11-27
status: research note — Route & Map and Explore of #87; the forks it raised were decided on 2026-11-27 (ADRs 0037 and 0038, accepted)
---

# Shape review

## Why this note

Issue #87: on a production project with a typed functional codebase, a team's own pre-review
skill finds findings that shipgate's review does not raise. It finds them on changes that
shipgate had already passed as ready. The class is the shape of the code: how a type is
designed, the layer a value belongs to, the module a declaration lives in, a concept written
in two places, and an abstraction that earns nothing. astrolabe, the style skill that
should keep such code from being written, did not prevent them.

A comment on the issue (2026-11-27) adds a second question. Maybe the cause is not the rules
but their reach: the config names astrolabe as the style skill, and that path may not load it
when types are written. Then better rules in astrolabe change little, and the rules might
belong inside shipgate.

This note answers both questions with counts. It spent 0 USD on model runs: no eval, no
probe, no nested session, no comparison run of the other review.

## Method

The other review is an employer's internal work. This note describes its mechanism in this
repository's own words and copies none of its text. The private project enters as counts and
categories only.

| Input | Size | How it was read |
| --- | --- | --- |
| The other review's skill: its main file, 8 reference files, 2 scripts | about 1,850 lines | in place, read-only |
| Its saved runs | 3 runs: 2 finished (4 units of work), 1 stopped after its first round (3 units) | in place, read-only |
| shipgate's journal of the private project | the review rows and dispositions of the same 3 changes; the `style` key of every implement and review entry | read-only SQLite (`mode=ro`) |
| The private project's worklogs | the review rounds and rejected findings of the same changes; 85 worklogs for the types-round count | read-only |
| The private project's session transcripts | 96 main sessions, 740 subagents, 400 workflow agents | a scratchpad script, counts only |
| This repository's journal and 28 worklogs | the `style` key; the types-round count | read-only |

The mining scripts stayed in the session scratchpad. They print counts and nothing else.

## 1. How the other review works

### The mechanism

- **Two reviewer rounds per unit of work, then a verifying synthesis.** One unit is the work in
  one repository. The units are reviewed in parallel; the rounds run in series.
- **Round 1 reviews shape only.** Its brief forbids correctness, security and convention
  findings, even ones the reviewer notices. When the reviewer sees a bug that a shape has
  already produced, it gives the line, and round 2 checks it.
- **Round 2 reviews correctness.** It reads the shape log before the diff and does not raise a
  shape finding again. It closes each finding by naming the shape finding whose proposed
  type would rule the bug out, or says that there is none. A shape finding
  it thinks wrong goes into a list of disputed findings, with evidence.
- **Shape scope is wider than the diff.** It covers every declaration the change adds or
  changes; every existing type that the change uses, changes or passes on, marked as
  existing; and, when the change crosses a service boundary, the matching type in the other
  service, read at that service's latest version. When one side keeps a closed set and the
  other receives it as free text, the side that opened it up gets the finding.
- **A checklist of tells, run over each type, value and helper that the scope holds.** This
  note sums it up in five groups, in its own words:
  - *closed sets*: a finite set of values typed as free text;
  - *illegal states*: one type that admits combinations the domain forbids, for example
    optional fields that really encode distinct variants, or several meanings of "none" in
    one field;
  - *signatures*: an input wider than the function uses, so the body checks it again;
  - *ownership, placement and duplicates*: every new value has one owning layer, sits where
    that layer keeps such things, and exists once; the finding names the owner or the
    definition that stays;
  - *masking*: casts and comments that hide a type gap, and abstractions with no evident
    purpose.
- **The finding format carries its proof.** Each finding quotes the current type, names the
  illegal state concretely, writes the proposed shape as code, tags a pre-existing type, and,
  when the change already shows a bug that comes from the shape, names that bug.
- **A self-check of the proposal.** The reviewer applies its own tells to each proposal
  before it reports it: the proposal must rule out the named state and must not open a new
  one. The brief warns about proposals that only look like fixes, such as widening a literal
  type back to free text, or trading one optional field for another. An unchecked proposal is
  marked as unchecked.
- **A clean list.** Each round lists the types it checked and found sound.
- **A verifying synthesis.** One agent re-reads every shape finding and every consequence at
  the head of the change. It checks every proposal against the tells, replaces a proposal
  that fails, and merges each bug under the shape that caused it. A shape with a verified
  blocking consequence is blocking; a shape with no symptom is "should fix".
- **Standing rulings.** A rulings file holds the team's tier policy and its list of things
  that are not findings. Every reviewer and the synthesis apply it without re-arguing it. It
  ranks shape findings above bug findings, and it reduces volume by grouping bugs under the
  shape that caused them, never by dropping a shape finding.
- **Declines and reruns.** The author declines a finding with a reason, and the reason goes
  into a note posted to the merge request. A rerun is blind: its reviewers get no earlier
  findings. After the rerun, the orchestrator compares old and new findings by file and
  problem, and marks each old finding as gone, or as unresolved with the code unchanged.
- **The reviewer persona.** A separate file sets how the reviewer judges, with no process in
  it. In short: read a type for what it allows, not for what it lists; treat a function that
  first converts its own arguments as a sign that its parameters are wrong; accept an
  abstraction only when it saves more than it costs; and do not take a neighbouring file as a
  precedent without checking it.

### Essential and local

| Part | Essential or local | Why |
| --- | --- | --- |
| The dedicated shape round, with correctness forbidden | essential | the shape reviewer spends its whole attention on shape; bugs are found by any pass |
| The scope rule: pre-existing types and the other side of a boundary | essential, with a cap | it finds the open types the change propagates; the evidence below shows such findings get declined more often |
| The format: current type, illegal state, proposal as code | essential | a finding with its proof survives a filter that asks "can this fail?" |
| The self-check of the proposal | essential | a proposal that still admits the state is a second defect |
| The rule that bugs merge under their shape | essential | one fix per class, and the shape takes the higher tier |
| The clean list | essential | coverage is visible; a sound type is not re-reviewed by the reader |
| Standing rulings applied without re-argument | essential in kind | shipgate's equivalent is the do-not-flag list and the canon lens's "not taste" rule |
| Multi-repository family discovery from the forge | local | shipgate reviews one repository's working tree |
| The note posted to the merge request and its checker | local | shipgate records dispositions in its journal and worklog |
| Data-access, feature-flag and sizing-query rulings | local | project policy |
| The house writing standard | local | shipgate has its own (ADR 0006) |

## 2. Evidence

All three saved runs reviewed changes that shipgate had passed as ready. On two changes the
run came after the last ready verdict and before the merge request; on one it came after the
merge request was open.

### Counts

| | Run A | Run B | Total (finished) | Run C (stopped after round 1) |
| --- | --- | --- | --- | --- |
| Units of work | 1 | 3 | 4 | 3 |
| Findings that are not notes | 13 | 21 | 34 | 10, unverified |
| Shape findings | 8 | 15 | 23 | 9 |
| Other findings (correctness, tests, description) | 5 | 6 | 11 | 1 |
| Accepted by the author | 7 | 14 | 21 | not recorded yet |
| Shape findings accepted | 5 | 10 | 15 | not recorded yet |
| Blocking findings | 0 | 2, both fixed | 2 | none tiered yet |
| Shape findings on pre-existing types | 0 | 2, both declined | 2 | 5 |

Accepted means the author fixed it before the merge, from the journal's dispositions and
gate decisions and the worklog's notes. A finding outside the author's recorded fix scope
counts as not accepted.

### Shape findings by kind

The kinds below are this note's own grouping. The last two columns say whether astrolabe
0.4.0 states a rule that covers the kind, and which astrolabe 0.5.0 rule covers it ("Shape
rules" is the new section of `domain-modeling.md`; "checklist" is its type review checklist).

| Category | Kind | Raised | Accepted | shipgate counterpart | astrolabe 0.4.0 | astrolabe 0.5.0 |
| --- | --- | --- | --- | --- | --- | --- |
| type design | a closed set passed as an optional string | 1 | 1 | none | stated (type review checklist, naming) | non-negotiable 11: a closed set is a union, in every signature; Shape rules, the tells: a closed set typed as `string` or `number` |
| type design | untrusted input absorbed by wide types or a type annotation, with no parse at the boundary | 2 | 1 | 2: one rejected below the confidence floor, one closed with a comment | stated, with a loophole: a cast with a cause-naming comment is allowed | non-negotiable 1: the comment never stands in for the fix of a type gap, and an annotation on an untyped value is a cast; a cast may target only `unknown`, or a type that a parser then narrows; `architecture-and-testing.md`, validation: untrusted input is parsed where it enters; checklist 10 |
| type design | "none" or "every" encoded as a sentinel value of an id field | 2 | 0, both pre-existing and declined | none | stated (absence is a typed value) | Shape rules, the tells: a sentinel |
| type design | a return type that does not match what the function returns | 1 | 1 | none | missing | Shape rules, the tells: a return type that claims more than the body returns; non-negotiable 11; checklist 9 |
| type design | one type that carries two meanings, read by its caller as the wrong one | 1 | 1, blocking | the design phase had accepted this shape | narrow (the checklist asks about two fields, not two meanings) | Shape rules, the tells: one type, two meanings; checklist 4 |
| type design | a parameter wider than its body needs | 2 | 1 | 1 closed with a comment | missing (one narrow line under persistence rules) | Shape rules, Signatures: a function asks for no more than its body uses, and its callers conform (the persistence line moved here); non-negotiable 11; checklist 9 |
| ownership | one value taken from two sources, or recomputed where the stored result exists | 3 | 1 | 2: one rejected, one fixed in another way | missing | Shape rules, One owner per value: other sites read the owner, never a second source or a recomputation; non-negotiable 11; checklist 7 |
| duplicates | one field group or vocabulary declared twice | 1 | 1 | none | stated (type review checklist item 2) | unchanged (checklist 2) |
| duplicates | a derived value, a predicate or a constant spelled in several places | 7 | 5 | 1 rejected ("the two cannot differ") | missing: the abstraction rules cover duplicated plumbing, not a concept spelled twice | Shape rules, One definition per concept; the guard after "When NOT to abstract" in `fp-functional.md`; non-negotiable 11; checklist 8 |
| placement | a declaration in a module that does not own it | 2 | 2 | none | stated | unchanged; non-negotiable 11 restates it in short form: each concept's one definition sits beside the type it is about |
| abstractions | a helper whose name no longer says what it does | 1 | 1 | none | stated (name by intent) | unchanged (non-negotiable 6) |
| **Total** | | **23** | **15** | **6** | **9 stated, 14 missing or narrow** | **a rule for each of the 14** |

Run C's round 1, unverified: type design 6, duplicates 2, ownership 1, other 1.

### What the counterparts show

shipgate's lenses saw 6 of the 23 shape findings, at the same site or on the same concept.
They lost them at three points:

- **The Step 2 filter.** The orchestrator rejected 3 on correctness arguments: "the two
  computations cannot differ", "the function exists to absorb those values", and a third of
  the same kind. Each argument is true and beside the point. A shape
  finding has no failing input today; it names a state the type allows.
- **The confidence floor.** One of the 3 came back at confidence 55, under the floor of 60.
  The finder scored how sure it was of a bug, not how sure it was that the type allows the
  state. Reading the type settles the second question.
- **The fix field.** 2 were closed with a comment that names the cause, in place of a type
  change. astrolabe's non-negotiable 1 allows a cast at a declared boundary with a
  cause-naming comment, so the canon permitted that fix.

One more: the blocking shape in run B came from a shape that shipgate's own design phase had
accepted in its first round. The design phase does not load the style skill.

### Why it matters for the design

Most of the class is not invisible to shipgate. It is lost in scoring, in the filter and in
the fix field. A new lens that reports into the same filter, with the same fields, would lose
the same findings. The finding format and the refutation rule matter as much as the lens.

## 3. Does the style skill load

The private project's config names astrolabe as its style skill and asks for it in every
worker brief. The counts come from every transcript of the project; "before" means before the
transcript's first edit of a code file.

| Who | Count | Loaded astrolabe | Loaded it before the first code edit |
| --- | --- | --- | --- |
| Subagents that edited code | 295 | 250 | 247 (84%) |
| of those, with astrolabe named in the brief | 219 | 216 | 216 (99%) |
| of those, with no astrolabe in the brief | 76 | 34 | |
| Canon reviewers (agents path and workflow) | 88 | 75 (85%); since 2026-11-15, 33 of 33 | |
| Main sessions that edited code | 33 | 8 (24%) | 8 |
| The design phase | every stream | never: the design skill names no style skill | |

On the three changes the other review checked, 25 of the 27 code-writing subagents loaded
astrolabe before their first code edit: all 25 whose brief named it. Every canon reviewer
loaded it (12 of 12). The shape defects passed anyway.

The journal's `style` key records what the orchestrator named, not what loaded: astrolabe on
29 implement and 43 review entries of the private project. This repository's config names no
style skill (`style: []` on 26 implement and 45 review entries), so its own flows say nothing
about astrolabe.

The declarations-first round (the types round, shipgate 0.10.0) ran in 0 of 85 worklogs of
the private project and in 0 of 28 of this repository. Its trigger is "a slice introduces new
domain shapes". The shape defects above sit in changes to existing code: a new parameter, a
helper, a derived value. The trigger never fires there.

**Conclusion.** Where shipgate tells a subagent to load the style skill, it loads (99%). The
leaks are the orchestrator's own code edits (24%), briefs with no Style line (26% of
code-writing subagents), and the design phase (never). On the changes in question, loading
was complete and the defects passed. The larger causes are rule coverage (14 of 23 under no
rule), the review contract (the filter, the floor, the fix field) and the unused types round.
Moving astrolabe into shipgate would fix none of those three.

## 4. Gap table A — astrolabe, prevention

| Shape rule | astrolabe 0.4.0 | Followed in practice | Proposed change |
| --- | --- | --- | --- |
| A closed vocabulary is a union, never a string | stated: type review checklist 1, naming section | not followed in 1 accepted finding, by a worker that had loaded astrolabe: the rule sits in the review checklist and in "new types", and a service parameter is no new type | add to the always-on core, for every signature |
| Illegal states unrepresentable: the common tells | partly: checklist 4 (two fields), "one way to say no value", entity lifecycle | 2 findings under tells it lacks (two meanings in one type, a return type that lies) | a short list of tells with one example each, in domain-modeling |
| A signature asks for no more than its body uses; callers conform | missing; "helpers require non-nullable arguments" sits under persistence rules | 2 findings, plus a widened list inside an ownership finding | a signature section; move the persistence line there |
| One owner per value or constant | missing; ownership is stated for types across contexts and for functions by parameter type | 3 findings | an ownership rule for values, constants and derived values: derive once, read the stored result |
| One definition per concept | stated for vocabularies (checklist 2) and for duplicated plumbing (the abstraction rules); the "when not to abstract" list can excuse a predicate spelled five times | 8 findings, 6 accepted: the largest accepted kind | a rule that a domain predicate, derived value or constant spelled twice is a definition, not an abstraction, and gets one named home |
| Placement by layer and context | stated | 2 findings, both accepted | none beyond a pointer from the core |
| Parse at a boundary | stated (two boundaries), with a loophole: a cast with a cause-naming comment | 2 findings; 2 shipgate fixes were comments | an annotation on an untyped value counts as a cast; a boundary that receives a known shape parses it; a comment never excuses a type gap |
| Abstraction names | stated | 1 finding, accepted | none |
| A proposed shape passes its own check | missing | not measurable here | a self-check at the end of the type review checklist |
| Pre-existing types the change reads | stated the other way: "a new-code convention, not a retrofit" | 2 findings, both declined | keep prevention at new code; add that new code narrows an open pre-existing type at its own boundary instead of passing it on (left out of 0.5.0 in review round 4: it needs more than one sentence; a later astrolabe change) |

**Where astrolabe loads when types are written.**

| Phase | Loads today | Proposed |
| --- | --- | --- |
| Clarify | no; it writes no types | no change |
| Design | no; the design skill names no style skill, and design decides shapes | load the style skill before deciding a new type, a changed signature or a declarations task |
| Implement, worker | yes, through the brief's Style line (99% when present) | no change |
| Implement, orchestrator's own edits and fix rounds | rarely (24%) | the same rule as a worker: load before the first code edit of the session |
| Types round | never runs | trigger it on a changed exported signature too, and review the declarations with the shape lens |
| Review | the canon lens (85%; 100% since 2026-11-15) | the shape lens loads it the same way |

## 5. Gap table B — the review, detection

| What the class needs | correctness | conventions + design | simplicity + security | canon | Can the fan see it today? |
| --- | --- | --- | --- | --- | --- |
| A state the type allows, with no failing input | asks "can this fail?" and answers no | no | no | only what the canon states | no: the filter kills it on "cannot differ" |
| A concept spelled twice | no | "reuse of existing utilities", for helpers | "duplication", next to security | the canon's vocabulary rule only | partly, for helpers |
| Ownership of a value across layers | no | no | no | no | no |
| Placement | no | repo routing rules | no | stated canon rules | partly |
| Wrong or orphan abstractions | no | "abstractions" | "wrong abstraction", one clause of a lens that also carries security | the canon's abstraction rules | partly |
| Pre-existing types the change touches | no: scope is the diff | no | no | no | no |
| The other side of a boundary | no | no | no | no | no |
| A proposal as code with a self-check | `fix` field, clipped to 300 characters | same | same | same | no: a comment passes as a fix |
| The list of what was checked and sound | the agent's text format has one; the workflow schema drops it | same | same | same | no |

### Options

| Option | What it is | Cost per review with type surface | For | Against |
| --- | --- | --- | --- | --- |
| **A. A fifth lens `shape`** (recommended) | one more finder in the same parallel Find phase; runs only when the diff changes a declaration; loads the configured style skills like canon; carries a short language-neutral question list for projects with none | 0.9 to 2.2 USD (between the canon finder and the other review's shape agent); no added wall time | dedicated attention; one owner for the class; reuses the canon mechanism (ADR 0012) | a new finder that every review with type surface pays for |
| B. A shape-first serial round | the shape finder runs alone first; the other lenses read its findings | the same tokens, plus about 5 min median (7.5 min p90) of wall time | consequences can point at a shape finding | Step 2 can merge consequences from parallel results; the serial step buys little for its time |
| C. Widen an existing lens | the canon brief takes the shape contract; or simplicity + security takes it | no new finder | cheapest | canon runs only with a style skill; one lens with mixed duties is where the counterparts were lost |

### The contract (with option A)

- **Trigger.** The orchestrator adds `shape` when the diff adds or changes a declaration. A
  docs, config, CI or migration-only diff gets no shape finder. A fix-round re-review adds it
  when the fix diff changes a declaration.
- **Scope.** The declarations the change adds or changes; the pre-existing types it uses or
  passes on, tagged pre-existing and at most MEDIUM; the type
  on the other side of a boundary the change crosses, when that type is in the repository.
- **Finding format.** The workflow's finding schema gains an optional `shape` object:
  `current` (the type quoted), `illegal_state` (named concretely), `proposed` (the shape as
  code), `self_check` (one sentence: the state is impossible in the proposal, no new one
  appears, type-checked or not), `pre_existing` (boolean). A survivor keeps `shape.proposed`
  unclipped, so the orchestrator reads the proposal and not a 300-character stub.
- **Scoring.** Confidence scores whether the current type admits the named state, which
  reading the type settles. A shape finding with no consequence is MEDIUM. With a verified
  consequence in the diff, it takes the consequence's severity.
- **Refutation.** A refuter, and the orchestrator in Step 2, kill a shape finding only by
  citing the type or constructor that already forbids the named state, or by showing that the
  proposal still admits it. "No caller builds it today" and "the two values cannot differ" are
  no refutation. A comment is no fix. This mirrors the canon rule that taste is no refutation.
- **The clean list.** Each finder may return `clean`, a short list of what it checked and
  found sound. The return carries it per lens.
- **Declines.** A shape finding on a pre-existing type can be declined. The orchestrator
  records it as `deferred` with its reason in the worklog's Rejected findings. Before the next
  round on the same stream, it puts every rejected or deferred finding of earlier rounds into
  `doNotFlag`, with the reason. This is where #87 meets #33: #33 adds a reason enum to the
  disposition; this feature uses the list that exists, and adds one rule for the enum: "not a
  bug" is no valid reason to reject a shape finding.
- **Consequences.** In Step 2, a correctness survivor whose bug the proposed shape makes
  impossible to write is listed under that shape finding, and the shape finding takes its
  severity when that is higher.
- **"Wrong abstractions"** moves from the simplicity + security lens to the shape lens.

### Cost per review, on each session model

Measured medians per finder on Opus 5.5, from the workflow agents of the private project and
this repository. Prices: 4 USD per million input tokens, 20 USD output, 0.20 USD cache read;
cache writes taken at 1.25 times input.

| Agent | Runs | Fresh input + cache write | Cache read | Output | USD | Wall time |
| --- | --- | --- | --- | --- | --- | --- |
| canon finder | 42 | 86k | 0.85M | 12.5k | 0.85 | 2.1 min |
| correctness finder | 88 | 105k | 1.78M | 18.7k | 1.25 | 4.3 min |
| conventions + design finder | 77 | 118k | 2.00M | 16.0k | 1.31 | 3.3 min |
| simplicity + security finder | 57 | 67k | 0.66M | 9.2k | 0.65 | 2.0 min |
| refuter | 66 | 32k | 0.12M | 1.7k | 0.22 | |
| the other review's shape agent | 7 | 161k | 3.58M | 31.0k | 2.15 | 4.9 min |

- The four lenses cost about 4.10 USD of finders, about 5.40 USD with 6 refuters.
- A shape finder: 0.9 to 2.2 USD per review with type surface, about +20% to +55% on the
  finders. It is the same on an Opus session and a Fable session: finders run one tier below
  the session and never below Opus, so they run on Opus on both.
- The session model prices only the orchestrator's Step 2 reading of the extra survivors
  (3 to 6 findings, 10k to 30k tokens of cited code): about +0.05 to 0.25 USD on Opus 5.5 and
  +0.10 to 0.50 USD on Fable 5.2.
- Option B adds about 5 min of wall time per review; option C adds no finder.

### Prompt text, on both session models

The finder and refuter briefs are read by Opus on both session models, so they can be
concrete: a short list of tells with one example each, and the format as schema fields, not
prose. The review skill's Step 2 rule is read by the session model. Fable 5.2 does worse with
long prescriptive lists, so that rule stays one paragraph: the two kinds of evidence that kill
a shape finding, and the two that do not. astrolabe's text is read by both models when they
write code: each rule is a principle and one example, with no stacked "always" and "never".

## 6. Where the shape rules live

| Option | What changes | Cost | Risk | A project that is not typed-FP | Users with astrolabe installed | The canon lens (ADR 0012) |
| --- | --- | --- | --- | --- | --- | --- |
| **(a) astrolabe stays separate; shipgate loads it where shapes are decided** (recommended) | astrolabe 0.5.0 gains the missing rules; shipgate loads the style skill in design and before the orchestrator's own edits; shipgate owns the shape review contract, not the rules | two small deliverables; prose tests in both plugins | the rules depend on a project naming a style skill; mitigated by the lens's language-neutral questions | pays nothing unless the diff has type surface; then gets the neutral questions, no TypeScript rules | no migration; they get the new rules on update | unchanged; the shape lens reuses its mechanism |
| (b) shipgate bundles language-neutral shape rules as a reference of design, implement and review | a new shipgate reference read by three skills | every phase of every project reads it (2k to 3k tokens per read) | two homes for shape rules when astrolabe is also installed; they drift | gets the neutral rules everywhere, needed or not | two sources; the config's Style line still names astrolabe | the canon lens and the reference overlap; dedupe merges the findings, not the rules |
| (c) astrolabe moves into shipgate whole | shipgate ships the typed-FP skill; the astrolabe plugin is deprecated | a migration release of both plugins | shipgate takes on TypeScript and fp-ts opinions; astrolabe stops working without shipgate; a skill name collision while both are installed | the skill's description loads into every session; its rules apply only where it triggers | a deprecation path; configs that name `astrolabe` must change, or resolve to the moved skill | loads the moved skill by its new name; every config's Style line changes |

The evidence in section 3 says loading is not the main cause. Options (b) and (c) answer a
reach problem that the counts show only for the design phase and the orchestrator's own
edits, and option (a) closes both.

## 7. Measurement

Deterministic first (0 USD):

- `test_workflow_scripts.py`: the `shape` lens has a definition; its finder prompt carries the
  scope, format and refutation block, and the style-skill line when `styleSkills` is given; a
  refuter of a shape-lens finding carries the refutation rule; `shape.proposed` survives
  unclipped; `clean` comes back per lens; `doNotFlag` reaches the shape finder; a shape and a
  canon finding at one line merge with both lenses.
- `test_prose.py`: the review skill names the trigger, the Step 2 kill rule and the
  doNotFlag step; the code-reviewer agent's lens table has the `shape` row; implement's types
  round points at the shape lens; design loads the style skill before it decides a shape.
- `astrolabe/tests/` (new): every rule section exists; the routing table names them; the
  core carries the short rules; the type review checklist has its new items and the
  self-check; no private name in any file.

One eval case, where a model run is needed: a TypeScript fixture whose diff plants four shape
defects (a closed set passed as a string where a union exists; a bag of optional fields that
encodes two variants; one predicate spelled in two modules; a domain type declared in an entry
point) and one sound discriminated union as a decoy.

- Graders: per defect, a regex or LLM claim that it is a finding with the illegal state named
  and a proposal as code; a claim that the decoy is no finding; a claim that the decoy is in
  the clean list; the verdict is not ready.
- What a fall would change: a missed defect in 2 of 3 runs rewords the brief or raises the
  finder's effort to high; a reported decoy tightens the refutation rule and the clean-list
  step; defects reported with no proposal move the proposal into a required schema field.
- Cost: case 74 (the canon lens) costs 1.11 USD a run on Opus and 1.68 USD on Fable (with
  arm, `none` mode). Adding a shape finder projects 2 to 3 USD a run on Opus and 3 to 4 USD on
  Fable; 3 runs on each model, about 15 to 21 USD. It runs only on the lead's word.

## 8. Forks

1. The review mechanism: a fifth lens (A), a serial round (B) or a wider existing lens (C).
   Recommendation: A.
2. The workflow contract: an optional `shape` object and a `clean` list in the finding schema,
   with the refutation rule; or the shape folded into `why` and `fix`. Recommendation: the
   schema fields.
3. Where the rules live: (a), (b) or (c) in section 6. Recommendation: (a).
4. Pre-existing scope: in, capped at MEDIUM and decline-able; or changed declarations only.
   Recommendation: in, capped.
5. Measurement: the deterministic tests and one eval case, run only on the lead's word.

Decided on 2026-11-27: the user chose the recommendation of forks 1 to 4 in the lead's question
dialog, and the lead took fork 5 (deterministic tests first; the eval case planned, its paid
run on the user's later go). ADR 0037 and ADR 0038 record them.
