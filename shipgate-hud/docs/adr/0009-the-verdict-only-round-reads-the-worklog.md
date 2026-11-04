---
type: adr
title: "0009. The verdict-only round reads finding text from the worklog, and the board stays in $.state"
created: 2026-11-04
updated: 2026-11-04
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-11-04
issue: "#12"
related:
  - "0008-the-review-tab-reads-folded-dispositions.md"
  - "../../../shipgate/docs/adr/0009-the-journal-computes-the-hud-position.md"
  - "../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md"
---

# 0009. The verdict-only round reads finding text from the worklog, and the board stays in $.state

> The HUD parses the worklog's review section and prints one line of finding text under
> each key of the verdict-only round. The review board stays in its `$.state` atom, which
> the engine keeps across `/reload-plugins`.

## Context

A verdict-only round (HUD ADR 0008) draws `<key>  <state>` lines and nothing else. The
journal carries keys and states only, by design: the 1 KB cap and the "pointer, not prose"
rule keep finding text out of it. The text is in the worklog's review section, which the
`review` skill writes, and the HUD already reads the worklog for the Plan and Design tabs.

The issue also reports a board gone after a plugin reload. The board is in a `$.state` atom
under the shape tag `shipgate-hud.review-v2` since 0.6.0, and its stored decoder is the same
in 0.6.0, 0.7.0 and 0.8.0. The engine's contract: a reload runs `register` and
`session.start` again, keeps `$.state` for the session and `$.store` across sessions, and
starts the module's own variables over.

## Decision

1. **The HUD parses the review section.** `position.ts` reads every list item under a
   heading whose text starts with `Review round` or is `Rejected findings` (any level), up to
   the next heading at the same or a higher level. An item gives its first backticked
   `<path>:<line|?>` location (null when it names none), the first sentence after that
   location (`sentence`) and the whole item (`body`). The result is `Position.reviewNotes`.
2. **The match, per key.** First the exact key (`./` dropped). Then a path tail on the same
   line, case folded: the key's path ends the item's path at a `/`, or the item's path ends
   the key's. Then the label: the key's `label` from `position`, or the key itself when it is
   no `<path>:<line|?>`, as a whole word of the item's text, case folded. The first item in
   worklog order wins in each tier. A key with no match draws no text line.
3. **The board stays in `$.state`.** No `$.store` copy and no re-read of the task output
   file. A test pins the reload: the stored board, `$.state` kept, `session.start` run
   again, the board drawn. The test kit cannot reload the module, so module state stays as
   it is in the test; the board is read from `$.state` alone, never from module state.

## Alternatives considered

- **`position --json` carries the worklog text.** journal.py already reads the worklog for
  the Build Plan. But finding text is display, not a rule: shipgate ADR 0009 keeps rules in
  journal.py, and the Design sections are parsed by the HUD for the same reason. It would
  also put prose into a contract the publish gate and the tests read.
- **Keep the board in `$.store`.** It would survive `/clear` and a new process too. It
  writes a file under the user's Claude configuration directory, kept across sessions, and
  the HUD writes nothing today. A board from another session would also need its own
  staleness rule.
- **Re-read the Workflow's task output file after a reload.** The file path comes from the
  task notification, and the HUD holds it only in module state, which a reload loses. To
  keep the path, it would need `$.state` or `$.store` anyway.

## Consequences

- A worklog whose review section uses another grammar gives no text. The key stays bare,
  as before.
- The match is display: a wrong line under a key misleads the reader but changes no state.
  The tiers run from the strongest evidence to the weakest for that reason.
- `/clear`, `/resume`, `/branch` and a new process still reset `$.state`, so a board
  captured before them is gone, and the verdict-only round with its text is what the tab
  draws. That limit is the engine's, and the README says so.
- The view's shape tag moves to `shipgate-hud.view-v6`: a stored `Position` without
  `reviewNotes` reads as absent, and the next refresh derives it again.
