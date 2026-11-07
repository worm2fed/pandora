---
type: adr
title: "0008. The Review tab reads the folded dispositions, and draws a round from the verdict"
created: 2026-11-02
updated: 2026-11-06
tags:
  - adr
  - shipgate-hud
status: accepted (amended 2026-11-04, shipgate-hud 0.9.0; amended 2026-11-06, shipgate-hud 0.10.0)
date: 2026-11-02
issue: "#5"
related:
  - "0007-the-trace-is-read-from-the-event-log.md"
  - "../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md"
---

# 0008. The Review tab reads the folded dispositions, and draws a round from the verdict

> A card's state comes from `position`'s folded `dispositions` (shipgate ADR 0014), matched
> to the card by a tolerant key. With no board, the tab draws a round from the last verdict
> and the same folded state.

> **Amended 2026-11-04 (shipgate-hud 0.9.0, #13):** pass 1 gains a case-folded tier after
> the exact and short-location tiers: a key labels every card whose location (path and line)
> is the same once case is folded. The path-tail tiers of pass 1 and pass 2 compare folded
> paths too. Pass 2 still gives each key one card. The verdict-only round also prints one
> line of finding text per key, read from the worklog (HUD ADR 0009).

> **Amended 2026-11-06 (shipgate-hud 0.10.0):** a folded `fixing` older than the newest
> verdict, when that verdict is `ready`, is stale: a legacy journal recorded the fix and
> never its closure. A card and the verdict-only round draw it dim as `fixing?`, never in
> the live `fixing` colour, and no count treats it as open (the band, a board's open
> count). From shipgate 0.23.0 `append` refuses such a verdict, so only older journals
> hold one.

## Context

A card showed a disposition only from the last verdict's map, and only when the key named
the card's exact line or a path tail with the same line. A project with `review: agents`
never has a board, so its Review tab stayed empty (#5).

## Decision

1. **State source.** A card reads `position.dispositions`. An entry whose time is before
   the board's capture is not drawn on that board: it judged an earlier round. `fixing`
   draws a tag in place of Accept and Kill, and counts as open in the band.
2. **The key match, per board.** Pass 1 gives each card the first of: exact
   `<path>:<line>`, the short location, a path tail with the same line (longest path wins).
   A `<path>:?` key matches in pass 1 only a card with no line. Pass 2 gives a card still
   without a state a path-tail match with any line, over the keys no card took in pass 1:
   longest path first, then the nearest line (a `?` line is the farthest, so the last
   choice). Each pass-2 key reaches one card only. So a moved line still matches, and a key
   that named one card is never drawn on another.
3. **A round without a board.** No board for the stream, and a verdict or a folded
   disposition: the tab draws `round N · verdict <v> · <time>` (N is `verdict.round`), or
   `round 1 · in progress` with no verdict, then the verdict's note, one line per folded
   key (`<key>  <state>`, in key order), then the SC checklist. A board wins.

## Alternatives considered

- **Match by line-agnostic tail alone, per card.** Simpler, but a `fixed` on line 10 would
  show on every other finding of the file: the unpredictable label the user reported.
- **Draw a verdict-only round from the verdict's own map.** Misses interim states, which
  are the point of shipgate ADR 0014.

## Consequences

- The match is a board-level pass, so `dispositionIn` becomes `dispositionsFor`, a function
  over the board's findings.
- A verdict-only round lists every key the stream ever recorded, each at its latest state.
