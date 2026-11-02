---
type: adr
title: "0007. The trace is read from the event log until position carries it"
created: 2026-11-02
updated: 2026-11-02
tags:
  - adr
  - shipgate-hud
status: accepted (decision amended by shipgate ADR 0014)
date: 2026-11-02
issue: "#10, #11"
related:
  - "../../../shipgate/docs/adr/0009-the-journal-computes-the-hud-position.md"
  - "../../../shipgate/docs/adr/0011-a-map-without-signals-records-its-own-deviation.md"
  - "../../../shipgate/docs/adr/0013-signals-emits-the-ranking-the-journal-carries.md"
---

# 0007. The trace is read from the event log until position carries it

> For a bound stream, one refresh also runs `journal.py log --stream <s> --json`. The HUD
> takes three recorded values from it, verbatim: the newest `review-verdict.ranking`, the
> newest `design-committed.ranking`, and the `deviation` rows of `kind: signals-missing`.

> **Amended by shipgate ADR 0014 (2026-11-02, shipgate 0.21.0, shipgate-hud 0.8.0):** the follow-up below is
> done. `position --json` prints the three values as `trace.review_ranking`,
> `trace.design_ranking` and `trace.signals_missing` (shipgate ADR 0014). The HUD reads them
> from `position` and runs no `log` call; `decodeLog`, `traceOf` and the cut-log trace are
> gone. The selection rule stays as written here, and journal.py now computes it. The
> ranking is still decoded to journal.py's contract and drawn as "ranking unreadable" when
> it breaks it. **The read floor moves to 0.21.0:** a `journal.py` whose `position --json`
> has no `trace` key cannot give the trace, so the HUD treats it as outdated and names
> 0.21.0, as it names the floor for one older than 0.18.0. The dependency is shipgate
> `>=0.21.0`.

## Context

shipgate 0.20.0 records a risk ranking on `design-committed` and `review-verdict`, and
`append` writes a `signals-missing` deviation beside a map without signals. The HUD should
draw all three. `position --json` (shipgate ADR 0009) does not print them: its verdict
carries only `verdict`, `criteria` and `dispositions`, and it prints no deviation and no
design event. The change that adds them to `position` is a `journal.py` change, and
`journal.py` is frozen for this release (eval runs read it).

## Decision

`refreshPosition` runs `log --stream <s> --json` after `position`, for the bound stream
only. `decodeLog` decodes the envelope strictly: a list of events, each with a `seq`, a
`type`, a `ts` and a `data` object. A malformed envelope is a `BadShape`, as for any
other run. One failure is different: when the engine cuts the output (a long stream's log
past one answer), the trace is marked cut and the position is still drawn. The log holds
every event, so its size grows with the stream, and a cut must not hide the position. The HUD then picks values, it computes no rule:
- the newest `review-verdict` and the newest `design-committed` that carry a `ranking`
  key. The value is decoded to journal.py's contract and drawn as recorded. A `ranking`
  that breaks the contract (a row written before 0.20.0 validated it) is `Unreadable`, with
  the event's `seq`, never a refresh failure. When the verdict ranking is older than the
  verdict `position` names, the Review tab says so;
- every `deviation` whose `data.kind` is `signals-missing`, with its `seq` and time.

A journal.py from 0.18.0 or 0.19.0 prints the same `log` envelope, and its events carry no
ranking and no such deviation. So the read floor stays 0.18.0.

## Alternatives considered

- **Add the facts to `position --json`.** It keeps ADR 0009 whole: the journal computes,
  the HUD draws. It is the right end state, but it changes `journal.py`, which this release
  may not touch. Recorded as the follow-up below.
- **Draw nothing until `position` has them.** The values are recorded today, and the gap
  they show (a skipped signals block, a review not dispatched from the ranking) is what
  #10 asks to make visible.
- **Read the database directly.** The hooks module has no SQLite, and ADR 0001 keeps the
  HUD on the CLI.

## Consequences

- One more process per bound refresh. The `log` answer holds every event of the stream,
  so a long stream costs a larger read; it is still one call.
- "Newest event that carries `ranking`" is a selection, not a rule. It matches what
  `journal.py stats` reads for its trace, but nothing ties the two together.
- Follow-up (shipgate): print `ranking` on `position.verdict`, a `design` block with its
  `ranking`, and the `signals-missing` deviations in `position --json`; then drop the
  `log` call and this ADR's decoder.
