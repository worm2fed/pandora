---
type: adr
title: "0021. The handoff brief is computed, not written"
created: 2026-11-20
updated: 2026-11-20
tags:
  - adr
  - shipgate
  - journal
status: accepted
date: 2026-11-20
issue: "#23"
related:
  - "0009-the-journal-computes-the-hud-position.md"
  - "0018-config-layers-resolve-per-section-nearest-first.md"
  - "../prd/phase-handoff.md"
  - "../prd/phase-handoff.worklog.md"
---

# 0021. The handoff brief is computed, not written

> `journal.py handoff --stream <s>` builds the brief from the journal, the artifacts its
> events name and the project config. The session that hands off prints it; the session
> that takes over builds the same brief again with the same command.

## Context

Issue #23 asks the flow to move to a fresh session at the design → implement gate. The
fresh session has zero context and may run on a different model. Today 43% of sessions
already start from a brief, but the agent writes each one from its memory of the
conversation. What the writer forgets never reaches the reader, and nothing checks the
brief.

The journal already holds the position (`position`, ADR 0009): phase, artifacts, Build Plan
tasks, decisions, verdict, dispositions, publish gate. The config layers (ADR 0018) hold the
rules that bind a session. Only the request, the reporting target and the reading order are
not yet in one place.

## Decision

A new read-only subcommand, `journal.py handoff --stream <s>`, prints the brief. It reuses
`build_position` for the stream's facts and adds four things: the request from
`flow-started`, the next task and the next phase, the open gates, and the **Autonomy** and
**Security-sensitive areas** config sections resolved through the layers of ADR 0018: the
repo's files from the working directory up, then the umbrella's, then the user file. A
section counts as present when it holds a line that is not a placeholder, because a prose
section holds no `Key: value` bullet. The reporting
target is an optional `report_to` key on the stream's events, newest wins, else the user.
The output is text for a model, at most 60 lines on a typical stream. Nothing in it comes
from the session that runs it, so `/shipgate` in the fresh session runs the same command.
This was an executive decision; the user can veto it.

## Alternatives considered

- **A template the writing session fills in.** Cheap, and it can carry nuance the journal
  lacks. Rejected: the failure is the writer's memory, and a template keeps it.
- **Extend `status` with a `--handoff` flag.** One command fewer. Rejected: `status` is the
  short brief every session start pays for (#31 wants it smaller), and the handoff brief
  answers a different question for one stream.
- **A `--json` form beside the text.** Rejected for now: the only reader is a model, and the
  HUD part of #23 is a separate change. A JSON form would be a second contract.

## Consequences

- **Positive:** the brief is the same in both sessions and on both models. A test can check
  each item. The skills shrink to "run `handoff`, show it, recommend `/clear`".
- **Negative:** what is not in the journal or the artifacts is not in the brief. A nuance
  that lives only in the conversation must reach the worklog first.
- **Follow-ups:** shipgate-hud can show the brief once it has a JSON form (#23, HUD part).
