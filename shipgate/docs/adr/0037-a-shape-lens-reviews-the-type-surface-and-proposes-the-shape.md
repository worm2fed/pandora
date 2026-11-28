---
type: adr
title: "0037. A shape lens reviews the type surface and proposes the shape"
created: 2026-11-27
updated: 2026-11-27
tags:
  - adr
  - shipgate
status: accepted
date: 2026-11-27
issue: "#87 (https://github.com/worm2fed/pandora/issues/87); refs #33"
related:
  - 0012-the-canon-reviewer-loads-the-style-skill-itself.md
  - 0014-a-finding-disposition-is-recorded-when-it-is-decided.md
  - 0038-the-shape-rules-stay-in-astrolabe-and-shipgate-owns-the-review-contract.md
  - ../prd/shape-review.md
  - ../research/2026-11-27-shape-review.md
---

# 0037. A shape lens reviews the type surface and proposes the shape

> The review fan gains a fifth lens, `shape`, that runs in the same parallel phase when the
> diff changes a declaration. Its findings carry the current type, the illegal state and the
> proposed shape as code. A shape finding dies only on evidence that the named state cannot
> be built, or that the proposal does not remove it.

**Status: accepted, 2026-11-27.** Every review with type surface pays for one more finder, and
the review workflow's finding schema and return change. Both are one-way doors. The user chose
this option in the lead's question dialog (forks F1, F2 and F4 of #87).

## Context

A team's pre-review on a production project raised 23 shape findings on 4 units of work that
shipgate had passed as ready. The author accepted 15 (research note, section 2). shipgate's
four lenses saw 6 of the 23 and lost them at three points:

- the Step 2 filter killed 3 on correctness arguments ("the two values cannot differ");
- one of those 3 sat at confidence 55, under the floor of 60, because the finder scored the
  chance of a bug and not whether the type admits the state;
- 2 were closed with a comment in place of a type change, and the `fix` field allowed it.

No lens owns the class. "Wrong abstractions" is one clause of the simplicity + security lens.
The scope of every lens is the diff, so a pre-existing type the change propagates, and the
type on the other side of a boundary, are never read. The workflow schema drops the agent's
"verified clean" section, so nobody sees what was checked.

The canon lens (ADR 0012) reviews the change against the style skill's rules. It runs only
when the config names a style skill, and its attention goes to convention violations: the
`switch`, the missing `readonly`, the bare id.

## Decision

Add a `shape` lens to the review workflow script, to the `code-reviewer` agent's lens table
and to the review skill.

- **Trigger, computed.** `signals.py hotspots --diff` already runs in Step 1. Its JSON gains
  `type_surface`: per changed file, the language family and whether an added or removed line
  declares something (a type, an interface, an enum, a class, a schema, an exported function
  or constant), from one regex set per language family; an untracked code file counts in
  full. The top-level value is `true` when any file has type surface, `false` when every
  file is documentation, configuration, CI, SQL or a migration, and `null` when a changed
  file belongs to no known family. The orchestrator names `shape` on `true` and on `null`
  (the review errs toward looking), and on `false` it names no shape finder. The re-review
  after a fix round reads the same key over the fix diff. With the signals unavailable, the
  orchestrator names `shape` and says why in one line.
- **Rules.** When `styleSkills` is given, the shape finder loads each skill with the `Skill`
  tool before it reads the diff, as the canon finder does. It also carries a list of
  language-neutral shape questions, at most 10 lines, so a project with no style skill still
  gets a shape review. A prose test counts the lines.
- **Scope.** The declarations the change adds or edits; the pre-existing declarations it only
  uses or passes on, tagged `pre_existing`; the type on the other side of a boundary the
  change crosses, when that type is in the repository. A declaration the change edits is in
  the first set, with full severity. A pre-existing declaration the change only uses or
  passes on is capped at MEDIUM and may be declined.
- **Format.** The finding schema gains an optional `shape` object: `current`,
  `illegal_state`, `proposed`, `self_check`, `pre_existing`. Each finder may also return a
  short `clean` list. A survivor keeps `shape.proposed` unclipped; the return carries `clean`
  per lens.
- **Scoring.** Confidence scores whether the current type admits the named state. A shape
  finding with no consequence is MEDIUM; with a verified consequence in the diff it takes the
  consequence's severity.
- **Refutation.** A refuter of a shape-lens finding, and the orchestrator in Step 2, kill it
  only by citing the type or constructor that already forbids the named state, or by showing
  that the proposal still admits it. "No caller builds it today" and "the two values cannot
  differ" are no refutation. The sentence "A comment is no fix for a shape finding." is the
  same in the script, the agent and the review skill's Step 2, and a prose test keeps the
  copies identical. astrolabe states the code side in its own cast rule; neither plugin
  quotes the other.
- **The confidence floor.** A shape-lens finding whose `shape` quotes the current type and
  names the state goes to the candidates whatever its confidence. Reading the type checks it,
  so the floor of 60 must not hide it (one counterpart was lost at 55).
- **Declines.** A decline is a `deferred` disposition with its reason. Before the next round
  on the same stream, the orchestrator puts every rejected or deferred finding of the earlier
  rounds into `doNotFlag`, with the reason.
- **Ownership.** "Wrong abstractions" moves from the simplicity + security lens to `shape`.

The finder runs on the worker tier like every finder: Opus on an Opus session and on a Fable
session. It keeps the agent's default effort (medium) until the eval case measures a gain at
high.

## Alternatives considered

- **A shape-first serial round.** The shape finder runs alone; the other lenses read its
  findings and point their bugs at a shape. It costs the same tokens plus about 5 min of
  wall time per review (median; 7.5 min at p90). Step 2 can merge a bug under its shape from
  parallel results, so the serial step buys little for its time.
- **Widen the canon lens.** No new finder. But canon runs only with a style skill, and a lens
  with mixed duties is where the 6 counterparts were lost. The canon brief would also have to
  hold two scoring rules.
- **Widen the simplicity + security lens.** No new finder, and it already names "wrong
  abstraction". It would carry security, complexity and shape in one attention budget, and
  the finder brief would hold three refutation rules.
- **Fold the shape into `why` and `fix`.** No schema change. But both fields are clipped to
  300 characters in a survivor, so the proposal arrives cut, and nothing marks a comment as
  no fix.

## Consequences

- A review with type surface costs one more finder: 0.9 to 2.2 USD (measured medians: the
  canon finder 0.85 USD, the other review's shape agent 2.15 USD), the same on an Opus and a
  Fable session. Step 2 reads 3 to 6 more findings: about +0.05 to 0.25 USD on Opus 5.5 and
  +0.10 to 0.50 USD on Fable 5.2.
- A review with no type surface costs what it costs today.
- The workflow script's return gains optional fields (`shape` on a finding, `clean` per
  lens). An orchestrator that ignores them works as before. The HUD reads the worklog and the
  journal, not the return, so it does not change.
- Step 2 gains one rule for a class of finding, beside the canon rule. A shape finding killed
  against that rule is a defect of the review, not a ruling.
- The declarations-first round can run the same lens alone (`lenses: ['shape']`), so the
  prevention round and the final review share one contract.
- #33's rejection-reason enum gets one constraint from here: "not a bug" is no valid reason
  for a shape finding.
- Deterministic tests pin the lens text, the schema and the return. One eval case with four
  planted shape defects and one sound decoy measures it on both session models (about 15 to
  21 USD for 3 runs each), only on the lead's word.
