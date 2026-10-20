---
type: adr
title: "0009. The journal computes the HUD's position"
created: 2026-10-20
updated: 2026-10-20
tags:
  - adr
  - shipgate
  - shipgate-hud
status: accepted
date: 2026-10-20
issue: none / ad-hoc
related:
  - "../../../shipgate-hud/docs/adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
  - "../../../shipgate-hud/docs/research/2026-10-20-hud-type-model-audit.md"
---

# 0009. The journal computes the HUD's position

> `journal.py position --stream <s> --json` prints every fact the HUD draws. The HUD
> decodes that JSON and keeps only the parsing of markdown for display.

## Context

HUD ADR 0001 chose the journal CLI as the HUD's only source and rejected re-implementing
status logic in TypeScript. Over 0.2–0.5 the HUD copied several journal rules anyway. An
audit found these copies, several of which disagree today:
- the publish rule: a list-valued `decision` authorizes in TypeScript and is refused by
  `mr-opened`;
- the phase when none was entered;
- skipped and implied phases;
- the Build Plan grammar that the Stop gate's rule A uses;
- artifact classification with a custom ADR home;
- the stream lifecycle.

Each copy needs a twin change whenever the journal changes a rule, and no test ties them
together.

## Decision

The journal prints the facts, and the HUD decodes them.
- `status --json` gains, per stream: `publish` (computed by the same helper as
  `_validate_mr_opened`), `lifecycle` (`live`, `dormant` or `terminal`), and `current`
  (phase, entered at, implied, or null). The top level gains `nested_matches`.
- A new `position --stream <s> --json` adds the facts that need the stream's events and
  artifacts:
  - phase marks per phase: `done`, `skipped`, `current`, `revisited` or `todo`;
  - the artifacts, classified with the configured homes;
  - the Build Plan tasks, parsed with the grammar `check` uses, with their journal state;
  - gate decisions with their real `seq`;
  - the last review verdict.
- `gate-decision.decision` must be a string. `review-verdict` declares `criteria` and
  `dispositions` with closed vocabularies.

A Python test generates a golden file of both outputs into the HUD's tests. The HUD
decodes that file in its own tests.

## Alternatives considered

- **Keep the TypeScript fold, fix each copy, add parity tests.** No new CLI contract. But
  every future rule change needs a TypeScript twin and a parity row, and the copies are
  where the drift came from.
- **The HUD reads SQLite directly.** The mods runtime has no SQLite. ADR 0001 rejected it.

## Consequences

- One grammar and one fold, tested once, and the HUD's drawn position equals the journal's.
- `position` is a public CLI contract between two plugins that ship together. The golden
  file fails the build when either side drifts.
- A refresh runs `status`, then `position`, instead of `status`, `log` and TypeScript
  parsing.
- An older shipgate without `position` is a version mismatch. The HUD reports it as an
  error and does not guess. The HUD README states the minimum shipgate version.
