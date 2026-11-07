---
type: adr
title: "0014. A finding's disposition is recorded when it is decided, and position folds it"
created: 2026-11-02
updated: 2026-11-06
tags:
  - adr
  - shipgate
status: accepted (amended 2026-11-04, shipgate 0.22.0; amended 2026-11-06, shipgate 0.23.0)
date: 2026-11-02
issue: "#5, HUD ADR 0007 follow-up"
related:
  - "0009-the-journal-computes-the-hud-position.md"
  - "0013-signals-emits-the-ranking-the-journal-carries.md"
  - "../../../shipgate-hud/docs/adr/0007-the-trace-is-read-from-the-event-log.md"
  - "../../../shipgate-hud/docs/adr/0008-the-review-tab-reads-folded-dispositions.md"
---

# 0014. A finding's disposition is recorded when it is decided, and position folds it

> A new event, `review-disposition`, records a finding's state the moment the orchestrator
> decides it: `fixing`, `fixed`, `rejected` or `deferred`. `position --json` prints the
> folded state per finding key, and the trace the HUD read from `log` until now.

> **Amended 2026-11-04 (shipgate 0.22.0, #12):** `review-disposition` takes an optional
> `labels`, a map from a finding key to a short non-empty name, checked by a new
> `string_maps` rule kind. The key stays the finding's `<path>:<line|?>`; the label is how a
> human name travels beside it, never in its place. `position --json` adds `label` to each
> folded entry: the newest label a `review-disposition` gave that key, or null. A later event
> without a label keeps the earlier one.

> **Amended 2026-11-06 (shipgate 0.23.0):** two refusals close what a fix round opens.
> Every key of `review-disposition.dispositions`, `review-disposition.labels` and
> `review-verdict.dispositions` must be a location `<path>:<line|?>`, read as the HUD's
> `parseLocation` reads it; `append` refuses another key, `--force` included. And `append`
> refuses a `ready` verdict while the fold holds a `fixing` key that the verdict's own map
> does not close; the message lists the keys and the `review-disposition` row that closes
> them, and `--force` overrides it only with `--force-reason`. Measured on a production
> journal: 5 of 10 streams ended with 37 of about 200 keys at `fixing`, from a closure
> never recorded and from free labels on one side of the fold.

## Context

`review-verdict.dispositions` is the only record of what happened to a review finding. The
orchestrator writes it once, at the end of a round. So in the middle of a round the HUD
shows no state, and the person watching cannot tell a finding being fixed from one nobody
looked at. The HUD also ran `log --stream <s> --json` on every refresh to pick the risk
rankings and the `signals-missing` deviations (HUD ADR 0007), because `position` did not
print them.

## Decision

1. **`review-disposition`.** Payload: `dispositions` (required, a map from
   `<path>:<line|?>` to `fixing`, `fixed`, `rejected` or `deferred`, closed by
   `map_enums`), `round` (required, a non-negative integer, checked by a new `integers`
   rule kind; the `review` skill counts rounds from 1) and `note` (optional text).
   `fixing` means a fix is in progress; it exists only on this event.
   `review-verdict.dispositions` keeps its three closed states.
2. **No implied phase.** `review-disposition` is not in `PHASE_OF_EVENT`. The orchestrator
   appends `fixing` in the fix round, after it went back to implement; an implied review
   would move the phase on every dispatch.
3. **The fold.** `position --json` prints `dispositions`: per key, `{state, seq, at}`. It
   reads every `review-disposition` and every `review-verdict`'s `dispositions`, in seq
   order, and the latest event wins per key. A later round's verdict that names only its
   own findings leaves the earlier closures in place, and a later `fixing` still reopens a
   key. A leading `./` is dropped from a key, as for `verdict.dispositions`. A value
   outside the vocabulary is dropped. (Amended before release: the first draft read only
   the newest verdict's map, so a round-3 verdict reopened every key round 2 had closed.)
4. **The trace.** `position --json` prints `trace`: `review_ranking` and
   `design_ranking` (the newest `review-verdict` / `design-committed` that carries
   `ranking`, as `{seq, at, ranking}` with the ranking verbatim, or null) and
   `signals_missing` (every `deviation` of kind `signals-missing`, as `{seq, at}`, oldest
   first).
5. **The verdict.** `position --json`'s `verdict` adds `note` (text or null) and `round`
   (the number of verdicts in the vocabulary up to and including it).

Every addition is a new key. No key `position` printed in 0.20.0 is renamed or removed.

## Alternatives considered

- **A `fixing` value on `review-verdict.dispositions`.** One event type fewer, but a
  verdict is a round's conclusion; writing one per decision would make every interim state
  a verdict, and `publish` reads the last verdict.
- **Imply `review`.** Keeps the event inside its phase on paper, but flips the phase back
  and forth during a fix round.
- **Leave the fold to the HUD.** The HUD would need `log` again, and ADR 0009 keeps every
  rule in `journal.py`.

## Consequences

- It amends HUD ADR 0007: the HUD reads the trace from `position` and runs no `log`.
- The `review` skill appends `review-disposition` in Step 2 and in the fix round, and the
  verdict still states the final word.
- `position --json` grows with the number of finding keys a stream ever recorded, not with
  its events.
- "Latest event wins" means a later interim state overrides an earlier verdict for that
  key. That is the point: a round-2 `fixing` on a finding round 1 deferred is the current
  state.
