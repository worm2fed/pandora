---
type: prd
title: "PRD: shipgate-hud — the flow position drawn in the interface"
created: 2026-10-06
updated: 2026-10-06
tags:
  - prd
  - shipgate-hud
status: clarified
issue: none / ad-hoc
worklog: "./hud.worklog.md"
related:
  - "../adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
---

# PRD: shipgate-hud — the flow position drawn in the interface

> A Claude Code mod that shows where a shipgate flow stands — stream, phase, tasks,
> verify evidence, gate decisions, design — as a band above the prompt and a phase-aware
> pane, without changing shipgate itself.

## Problem

shipgate records the position of every piece of work in an append-only journal and in
the PRD / ADR / worklog artifacts. Today that position reaches the user only as text: the
status brief injected at SessionStart, and whatever the orchestrator says in its phase
summaries. Three things are hard to see:

- **Where the work is.** After a compaction or a long turn, the phase, the tasks done and
  the last verify are buried in the transcript.
- **What was decided for me.** In `executive` autonomy the orchestrator records gate
  decisions itself; they are listed in the phase summary, but there is no standing surface
  that shows them and lets the user veto one.
- **What the design committed to.** The ADRs and the worklog's Design section exist on
  disk, but reading them means leaving the session.

Claude Code 2.1.29x adds mods: plugins whose hooks module runs inside the engine and can
draw a pane, a band and a status line, see tool calls and their results, and run processes.
That is the right place to draw the position.

## Goals & non-goals

**Goals**
- One glance tells the user the stream, the phase, how many Build Plan tasks are done, the
  last verify outcome, and how many executive decisions are open to veto.
- A pane whose content follows the phase: the gate decisions, the Build Plan with verify
  evidence, the committed design.
- Zero coupling: shipgate's skills, hooks and scripts do not change. The mod reads what
  shipgate already writes.
- Safe everywhere: in a project without a shipgate journal the mod draws nothing and runs
  nothing beyond one existence check.

**Non-goals** (explicitly out of scope for this slice)
- The Review findings board, the publish-gate hold on `gh pr create` / `git push`, the
  Explore essential-files tracker, the Route & Map heat grid, the compaction-safe prompt
  attachment. Each is a later slice with its own PRD section.
- Desktop-only drawing (SVG diagrams). Slice 1 is terminal-first with text that also
  renders on desktop.
- Writing to the journal. The mod never appends events; vetoes go through the prompt.

## Users & stories

- As the developer driving a flow, I want the position in a band above the prompt so that I
  do not re-read the transcript to know what phase I am in.
- As the developer in executive mode, I want each recorded gate decision visible with a
  veto button so that I can overrule one without hunting for it.
- As the developer entering Implement, I want the Build Plan as a board with the verify
  evidence per task so that "done" means what the journal says, not what the checkbox says.
- As the developer reviewing a design, I want the ADRs and the worklog's Design section
  readable in the pane so that I do not leave the session.

## Functional requirements

- **FR-001** — On a journaled project (the `.claude/shipgate.json` sidecar exists), the band
  above the prompt shows: stream name, phase, tasks done / tasks in the plan, last verify
  outcome with its time, and the count of decisions open to veto (raised by the orchestrator in
  executive mode).
- **FR-002** — On a project without the sidecar, the mod draws nothing in the band, opens no
  pane, and runs no process. The `/hud` command still exists and says why there is nothing.
- **FR-003** — `/hud` opens (or focuses) the pane; the pane also opens unasked at session
  start on a journaled project, subject to the engine's width rule.
- **FR-004** — The pane header is the phase timeline: the eight phases in flow order, each
  marked done, current or not yet, from the journal's phase and the recorded transitions.
- **FR-005** — The pane's **Flow** tab lists the stream's gate decisions, newest first, each
  with gate, question, decision and who raised it; a decision the orchestrator took on its own
  (`raised_by: orchestrator` and `mode: executive`) carries a **Veto** button that submits a
  prompt naming that decision (stream, gate, timestamp) and asking the orchestrator to read it
  from the journal and revisit it. The prompt carries no question or decision text from the
  journal and is not submitted as the user's own words.
- **FR-006** — The pane's **Plan** tab lists the worklog's Build Plan tasks with their id and
  title, marks each as done when the journal holds `task-done` for it, shows the last verify
  that covered it (pass or fail), and flags a task ticked in the worklog without `task-done` in
  the journal.
- **FR-007** — The pane's **Design** tab shows the ADRs the design committed to (title and
  status) and the worklog's Design section rendered as Markdown.
- **FR-008** — The pane opens on the tab that matches the phase: Flow by default, Plan in
  `implement`, Design in `design`. The user can switch tabs; the choice holds for the session.
- **FR-009** — The position refreshes when the orchestrator appends to the journal, when a
  file matching one of the sidecar's `artifact_homes` globs is written, after `/clear` or
  `/resume`, and at most once a minute otherwise. A refresh is one `git rev-parse`, one
  `journal.py status --json` and one `journal.py log --json` run plus bounded reads of the
  files the events name; a request during a refresh queues one trailing refresh.
- **FR-010** — All data comes from the shipgate CLI (`journal.py`) and the artifact files.
  The mod locates `journal.py` from the `journalScript` option when set, else beside itself in
  the marketplace checkout (its folder resolved through a link), else in the plugin cache beside
  it, else in the config directory's plugin cache. When it cannot, the pane says so in one
  line and the band stays empty. Only the stream whose branch is checked out is shown; file
  paths taken from journal events are read only when relative, inside the project and free of
  `..` segments.
- **FR-011** — Nothing under `shipgate/` changes. The mod is a sibling plugin in the
  marketplace with its own version.

## Success criteria

- **SC-001** — `claude plugin validate shipgate-hud` passes with no errors; the report lists
  only the events and calls the design names.
- **SC-002** — `claude plugin test shipgate-hud` passes: the pure model (status JSON →
  position, worklog → tasks) and the band and pane drawings on both `terminal` and `desktop`.
- **SC-003** — Loaded with `--plugin-dir` in this repository, the band shows the current
  stream and phase, and the pane shows this feature's own gate decisions and Build Plan.
- **SC-004** — In a directory without `.claude/shipgate.json`, `claude plugin validate`
  reports no process or network calls outside the guarded paths, and the band is empty.

## Constraints & assumptions

- The mods API is early access; the declarations shipped with the installed build are the
  authority (`claude-code.d.ts`, 2.1.292). Breakage between releases is expected and is why
  the mod is a separate plugin.
- The hooks module runs with no Node and no DOM: no sqlite. The journal is read through the
  CLI only.
- `claude plugin test` runs without fs, network or process; tests answer `process.run` and
  `fs.read` from memory by hooking those calls beneath the plugin.
- Public repository: fixtures use generic stream names and generic task titles.

## Assumptions (executive)

- Where does the mod live? → a sibling plugin `shipgate-hud/`, not a module inside
  `shipgate/` — the API moves between releases, a broken module must not take the Stop gate
  with it, and the config escalates any change to what an installed plugin does.
- Data source? → `journal.py status --json` and `journal.py log --json`, plus file reads —
  the CLI is the single source of truth and the runtime has no sqlite.
- Which worklog belongs to the stream? → the worklog path referenced in the stream's
  `design-committed` / `task-done` events; else the newest `*.worklog.md` in the sidecar's
  worklog home whose file name carries the stream's slug; else none (no plan shown). Never
  another stream's worklog.
- What happens in a session with no surface (`claude -p`, the SDK)? → nothing: the mod draws
  nowhere, so it registers `/hud` and runs no process.
- Which tabs in slice 1? → Flow, Plan, Design: they use data the journal already records and
  exercise every primitive the later views need (process, fs, state, buttons, Markdown).
- Terminal or desktop first? → terminal; every drawing is Box/Text/Button/Markdown so it
  renders on desktop unchanged. SVG waits for a later slice.
- Version? → `shipgate-hud` 0.1.0, new marketplace entry; shipgate stays at 0.14.1.

## Open questions

None.
