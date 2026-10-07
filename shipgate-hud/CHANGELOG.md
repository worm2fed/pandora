# Changelog

All notable changes to the **shipgate-hud** plugin, newest first.

v0.1.0 — first slice. A Claude Code mod (function hooks) that draws a shipgate flow's
position: a band above the prompt with stream, phase, tasks done, last verify and the count
of orchestrator decisions open to veto; a pane (`/hud`, or opened at session start) with the
phase timeline and three tabs — Flow (gate decisions, newest first, one-press Veto on the
orchestrator's), Plan (the worklog's Build Plan cross-checked against `task-done` and
`verify-run` events, unrecorded ticks flagged), Design (committed ADRs, the worklog's Design
section as Markdown). Reads the position through `journal.py status/log --json` and the
artifact files; writes nothing. Refreshes on journal appends, artifact writes, `/clear`
and `/resume`, and once a minute. Shows only the checked-out branch's stream; artifact homes
come from the sidecar. No-op in a project without `.claude/shipgate.json` and in a session
with no surface.
