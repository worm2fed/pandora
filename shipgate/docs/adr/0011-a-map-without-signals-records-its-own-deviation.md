---
type: adr
title: "0011. A map without signals records its own deviation"
created: 2026-11-02
updated: 2026-11-02
tags:
  - adr
  - shipgate
status: accepted
date: 2026-11-02
issue: "#10"
related: ["0002-implied-phase-transitions.md", "0004-code-signals-on-demand-stdlib-script.md"]
---

# 0011. A map without signals records its own deviation

> `append` accepts a `route-and-map` `phase-entered` without `signals`, and in the same
> transaction it writes a `deviation` with `kind: signals-missing`.

## Context

Issue #10 asks that a `route-and-map` entry without `signals` be "a recorded deviation, not
a silent pass". On a production journal, 31 of 37 explicit `route-and-map` entries carry no
`signals`. The skill text already asks for them, so more skill text alone does not close the
gap. Something must write the record when the skill is not followed.

## Decision

`append_event` checks a `phase-entered` whose `phase` is `route-and-map`. When the payload
has no `signals` key, it inserts a second row after it, in the same transaction: a
`deviation` with `note`, `kind: signals-missing` and `auto: true`, under the same actor.
ADR 0002 set this pattern for the implied `phase-entered`. The append prints one extra line
for the deviation, and `--json` adds its `seq` under `deviation_seq`. A `signals` block that
is present must name `source` as `graph`, `regex` or `none`, or `append` refuses it.

## Alternatives considered

- **Refuse the append.** It makes the gap impossible, but it breaks every caller that does
  not know the new rule, and a refused phase entry leaves the stream in the wrong phase.
  The issue asks for a record, not a refusal.
- **A Stop-hook rule.** The Stop hook could block a session that entered `route-and-map`
  without signals. That changes the hook contract, which the config escalates, and it
  blocks a session for a fact the journal can simply record.
- **Skill text only.** This is the state the issue measured.

## Consequences

- `stats` and the status brief see the gap with no extra rule: it is a normal `deviation`.
- A batch that opens a stream and enters `route-and-map` without signals moves the version
  by one more. A caller that chains `--expect` already reads the version back (ADR 0002).
- Only an explicit entry can trigger it. No event implies `route-and-map`, so the rule
  never fires on an implied row.
