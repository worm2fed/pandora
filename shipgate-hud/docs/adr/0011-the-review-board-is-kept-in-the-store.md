---
type: adr
title: "0011. The review board is kept in the store, one key per stream"
created: 2026-11-07
updated: 2026-11-07
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-11-07
issue: "the review board after /clear, /resume, /branch (no issue yet)"
related:
  - "0008-the-review-tab-reads-folded-dispositions.md"
  - "0009-the-verdict-only-round-reads-the-worklog.md"
  - "../../../shipgate/docs/prd/shipgate-0.24.0.md"
---

# 0011. The review board is kept in the store, one key per stream

> The HUD saves a stream's review boards and marks in `$.store` under one key per project
> root and stream, keeps the newest 20 keys, and loads the key back into the `review` atom
> on the re-detection that runs after `/clear`, `/resume`, `/branch` and at session start.
> This supersedes HUD ADR 0009 §3. Decided in executive mode; the user can veto.

## Context

The board lives in the `review` atom of `$.state`. `/clear`, `/resume` and `/branch` reset
`$.state`, and so does a new process. The user then sees the verdict-only round instead of
the board with its cards and Accept / Kill buttons, although the stream is the same. HUD
ADR 0009 kept the board in `$.state` because the HUD wrote nothing then and a board from
another session needed a staleness rule. Since 0.10.0 the HUD writes one journal event, and
the staleness rule now exists: a board belongs to a stream, and a completed stream's board
is dead.

The engine's store is a JSON file of the plugin's own under the user's configuration
directory, kept between sessions and hot reloads, 4 MiB in all. A fixture round is about
3 KB of JSON. A real round with 20 findings is about 10 KB, and a stream keeps 5 rounds, so
a stream's entry stays near 50 KB.

## Decision

1. **One key per stream.** The key is `review-board:<project root>:<stream>`. The value is
   `{ shape: "shipgate-hud.review-board-v1", root, stream, savedAt, boards }`: the stream's
   boards as the atom holds them (`ReviewBoard[]`, newest first, marks included). The ticks
   stay in `$.state` only.
2. **Saved when set.** `captureBoard` and `markFinding` write the atom, then save the
   stream's boards. A board captured under no stream is not saved. After each save the HUD
   lists its keys, decodes each `review-board:` value, orders them by `savedAt`, and deletes
   every one past the newest 20. Twenty streams of five rounds stay near 1 MiB.
3. **Restored on re-detection.** `detectAndRefresh` runs after `classic.SessionStart` with
   source `clear`, `resume` or `fork`, after the lazy detection, and at `session.start`.
   When its refresh binds a stream, the HUD reads that stream's key. A value that decodes
   and whose `root` and `stream` match is loaded into the atom when the atom holds no board
   of that stream, before `detectAndRefresh` returns. The newest round opens. A board of
   another stream is never loaded.
4. **A completed stream's board is deleted.** When the bound position's `lifecycle` is
   `terminal`, the key is deleted and nothing is restored. A `dormant` stream restores: the
   flow can resume.
5. **A failed read is ignored.** A store call that rejects, a value of another shape or
   another version, and a value whose `root` or `stream` does not match are ignored; the
   HUD draws as today. Such a value is never deleted: it may be a newer HUD's.

## Alternatives considered

- **One key for every board.** One blob is one write and one read, but every save rewrites
  every stream and the 4 MiB cap bites the whole HUD at once. Rejected: a key per stream
  makes a delete one call and the cut a key listing.
- **Re-read the task output file.** The path lives in module state, which a reload loses,
  and the file carries no marks. Rejected (ADR 0009 already did).
- **Keep the board in `$.state`.** Today's limit. Rejected: the stream is the same and the
  user's marks are theirs.

## Consequences

- The HUD now writes a file under the user's configuration directory. The README says so.
  The file holds the findings' text and the project root, as the atom does in memory.
- Two sessions on one project and stream save to one key: the last save wins. A value
  that never decodes stays until its HUD version deletes it; the cut never counts it.
- A board restored after `/clear` draws its cards with the marks the user made, and the
  dispositions the journal folds since the capture still label them (ADR 0008).
- The test that pinned "a reset drops the board" now pins the restore.
- The `review` atom's shape tag stays `shipgate-hud.review-v2`; the stored entry has its own
  tag, so the two evolve apart.
