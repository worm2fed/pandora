---
type: adr
title: "0038. The shape rules stay in astrolabe, and shipgate owns the review contract"
created: 2026-11-27
updated: 2026-11-27
tags:
  - adr
  - shipgate
  - astrolabe
status: accepted
date: 2026-11-27
issue: "#87 (https://github.com/worm2fed/pandora/issues/87)"
related:
  - 0012-the-canon-reviewer-loads-the-style-skill-itself.md
  - 0037-a-shape-lens-reviews-the-type-surface-and-proposes-the-shape.md
  - ../prd/shape-review.md
  - ../research/2026-11-27-shape-review.md
---

# 0038. The shape rules stay in astrolabe, and shipgate owns the review contract

> astrolabe stays a separate plugin and gains the shape rules it lacks. shipgate owns how a
> shape is reviewed (scope, format, refutation) and loads the configured style skill where
> shapes are decided: in design, and before the orchestrator's own code edits.

**Status: accepted, 2026-11-27.** It decides what astrolabe tells every project and what
shipgate loads in every phase, for both plugins: a one-way door. The user chose this option in
the lead's question dialog, after reading the load counts and the three options (fork F3 of
#87, from the maintainer's comment on the issue of 2026-11-27).

## Context

The maintainer asked whether the style rules should move into shipgate, because the config's
Style line may not apply astrolabe reliably. The counts from a project whose config names
astrolabe (research note, section 3):

- 216 of 219 code-writing subagents whose brief named astrolabe loaded it before their first
  code edit. With no Style line in the brief, 34 of 76 did.
- The canon reviewers loaded it in 75 of 88 runs, and in 33 of 33 since 2026-11-15.
- 8 of 33 main sessions that edited code loaded it. The design phase never loads it, and the
  design phase decides shapes: one blocking shape came from a shape the design had accepted.
- On the three changes the team's pre-review checked, every worker whose brief named
  astrolabe and every canon reviewer had loaded it. The shape defects passed anyway.
- 14 of the 23 shape findings fall under rules astrolabe does not state, or states only for a
  narrow case: ownership of a value, one definition per derived value or predicate, a
  signature that asks for no more than its body uses, most tells of an illegal state.

So the reach problem is real in two places, design and the orchestrator's own edits. The
larger causes are the missing rules and the review contract (ADR 0037).

astrolabe is also used on its own, without shipgate. It is typed-FP and TypeScript in its
examples. shipgate serves projects of any language.

## Decision

astrolabe stays a separate plugin. Its 0.5.0 release adds the missing rules, in
language-portable terms with one TypeScript example each, and puts their short form in the
always-on core. shipgate holds no shape rules of its own beyond the shape lens's short list of
language-neutral questions (ADR 0037). shipgate's review contract says how a shape is
reviewed; the style skill says what good shape is.

shipgate closes the two reach gaps. The design skill loads the configured style skills before
it decides a new type, a changed signature or a declarations task. The implement skill's
style rule covers the orchestrator's own code edits, fix rounds included, as it covers a
worker. The declarations-first round reviews declarations with the shape lens.

## Alternatives considered

- **shipgate bundles language-neutral shape rules as a reference of design, implement and
  review.** Every project gets shape rules, and no config line is needed. But every phase of
  every project reads the reference (2k to 3k tokens each time), a project with astrolabe
  installed then has two homes for the rules, and two homes drift. The counts show no reach
  problem where a brief names the skill.
- **astrolabe moves into shipgate whole.** One home, loaded by shipgate where it decides. But
  shipgate takes on TypeScript and fp-ts opinions; astrolabe stops working without shipgate;
  installed users need a deprecation release and a migration; every config's Style line that
  names `astrolabe` must change, and so must the canon lens's skill name (ADR 0012). It fixes
  the two reach gaps that a two-line change to design and implement also fixes, and it does
  not add one missing rule.
- **Leave the rules as they are and only add the shape lens.** The review would find more,
  but the same defects would keep being written: 14 of 23 have no rule to prevent them.

## Consequences

- Two deliverables with their own versions: astrolabe 0.5.0 (rules and its first tests) and
  shipgate 0.39.0 (the shape lens, the design and implement reach, tests and one eval case).
  Neither depends on the other's release: the shape lens loads whatever style skill the
  config names.
- A project that is not typed-FP pays nothing new unless a diff has type surface, and then
  gets only the lens's language-neutral questions.
- Users with astrolabe installed need no migration. They get the new rules on update.
- The canon lens is unchanged. It still loads the configured style skill and reports what
  breaks its rules. Shape findings and canon findings at one line merge in the dedupe.
- Design reads the style skill once per stream that decides shapes: a few thousand tokens on
  the session model.
- The share of main sessions that load the style skill before a code edit becomes a measured
  success criterion (24% today, at least 80% after the release; PRD SC-008).
- astrolabe gains a test home of its own (`astrolabe/tests/`), so its rule anchors are pinned
  the way shipgate's prose is.
