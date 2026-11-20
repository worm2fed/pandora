---
type: prd
title: "PRD: shipgate 0.27.0 — hand off to a fresh session at a phase gate"
created: 2026-11-20
updated: 2026-11-20
tags:
  - prd
  - shipgate
  - journal
status: clarified
issue: "#23 (shipgate), batch 2 of #37"
worklog: "./phase-handoff.worklog.md"
related:
  - ../research/2026-11-15-agent-harness-audit.md
  - ../adr/0009-the-journal-computes-the-hud-position.md
---

# PRD: shipgate 0.27.0 — hand off to a fresh session at a phase gate

> The journal prints a handoff brief for a stream. A session with no context can continue
> the flow from that brief alone. `design` and `review` print it at the gate and recommend
> a fresh session. A hook adds one line when the context is past a threshold.

## Problem

A flow usually runs clarify, design, implement and review in one session. The context grows
to several hundred thousand tokens, and every later turn reads it again. No skill mentions a
new session, `/clear` or `/compact`.

The research note `shipgate/docs/research/2026-11-15-agent-harness-audit.md` (finding 4)
measured the cost:

- Session cost tracks the maximum context size (Spearman 0.97). Cache reads are 96% of all
  tokens.
- 22 sessions ran three or more phases in one thread. They carry about 41% of the cost, at a
  median maximum context of 702k tokens.
- 25 compactions happened at a median of about 850k tokens. 5 sessions hit "Prompt is too
  long".
- Only 6 of 36 streams moved to a new session between `design-committed` and the first
  `task-done`.
- 43% of sessions already start from an agent-written brief. So the artifacts can carry the
  state, but each brief today is written by hand from the writer's memory.

A brief from memory is the weak point. The reader has zero context and can run on a
different model than the writer. Whatever the writer forgets, the reader never learns.

## Goals & non-goals

**Goals**
- One command prints a handoff brief for a stream, built from the journal, the artifacts it
  names and the project config. Never from the conversation.
- The brief is enough for a session with zero context to take the next step correctly.
- The flow recommends a fresh session at the design → implement gate, and before a review
  fix round in a large context.
- A measured nudge: past a context threshold, the flow says so at a phase boundary.

**Non-goals**
- The shipgate-hud display of the context size against the threshold (a separate change).
- Clearing or compacting the session automatically. Only the user runs `/clear`.
- A change to the SessionStart hook. Issue #20 already brings the status brief back after
  `/clear`.
- A JSON form of the brief. The HUD part is out of scope, so the brief has one reader: a
  model.

## Users & stories

- As the user of a long flow, I want the agent to tell me when to start a fresh session, so
  that I stop paying for a context that the next phase does not need.
- As a fresh session, I want one brief that tells me my role, where the work stands, which
  files to open and which rules bind me, so that I continue without guessing.
- As a lead who dispatched a teammate, I want the brief to say where the teammate reports,
  so that a fresh teammate session still reports to me.

## Functional requirements

- **FR-001** — `journal.py handoff --stream <s>` prints a brief for one stream. A stream with
  no events exits 1, as `position` does.
- **FR-002** — The brief names the reader's role and the command that resumes the flow.
- **FR-003** — The brief names the stream, the request it started from, the current phase
  and the phase that comes next.
- **FR-004** — The brief lists the artifact paths to open, in reading order: PRD, worklog,
  ADRs. Each path comes from the journal events or the configured homes.
- **FR-005** — The brief names the next Build Plan task (id and title) and the task count
  done against the total. With no worklog it says so.
- **FR-006** — The brief lists the open gates: ADRs still `proposed`, review findings still
  `fixing`, a last verdict that is `not-ready`, ticked tasks with no `task-done`, a last
  verify that failed, and the publish gate (held, or authorized by which event).
- **FR-007** — The brief lists the latest gate decisions, so that the reader does not decide
  them again.
- **FR-008** — The brief quotes the rules that still bind from the project config:
  the **Autonomy** and **Security-sensitive areas** sections, resolved through the config
  layers. It says that the repo's `CLAUDE.md` files stay binding.
- **FR-009** — The brief says where to report: the target the stream's events name
  (`report_to`), else the user.
- **FR-010** — The brief is the same for the same journal, files and config. Nothing in it
  comes from the session that runs the command.
- **FR-011** — The `design` skill prints the brief once `design-committed` lands, and
  recommends a fresh session: `/clear`, then `/shipgate`.
- **FR-012** — The `review` skill prints the brief and recommends a fresh session before a
  fix round, when the session already ran an earlier phase or the context nudge fired.
- **FR-013** — The `feature` skill, on a resume past design, runs the handoff command and
  routes from the brief.
- **FR-014** — The context nudge: after a `design-committed` and after a `not-ready`
  review verdict, past a configured threshold of context tokens, the flow adds one line
  that recommends the handoff, for the user and for the model. Config key
  `Handoff: <tokens | off>` in the `## Session` section, default 500k, `off` disables it.
  (The user chose the default, the triggers and the audience; ADR 0022.)
- **FR-015** — The nudge never blocks and never refuses. On a project with no journal it
  costs nothing beyond what the hooks already cost.

## Success criteria

- **SC-001** — On a stream at `design-committed`, the brief holds every item of FR-002 to
  FR-009. A test checks each item by its content.
- **SC-002** — The brief is at most 60 lines on a stream with 8 tasks, 5 decisions and both
  config sections present.
- **SC-003** — Two runs of `handoff` on the same journal and files print the same bytes.
- **SC-004** — A fresh `claude -p` session on a different model than the writer, given only
  the brief of a fixture stream, names the next task, the first file to open and one rule
  that binds it. One probe run, recorded in the worklog.
- **SC-005** — The `design`, `review` and `feature` skill texts carry FR-011 to FR-013. A prose
  test checks each.
- **SC-006** — The nudge prints its line past the threshold and nothing below it, nothing
  with `off`, nothing after a `ready` verdict, and nothing on a Bash call that is not a
  phase boundary. Unit tests check each.
- **SC-007** — The added cost on a Bash call that is not a phase boundary is under 1 ms,
  measured.
- **SC-008** — The full test suite passes.

## Constraints & assumptions

- Python 3.9 compatible, standard library only (CLAUDE.md).
- Hooks run on every user's machine in every project. The no-op path is a correctness
  requirement (CLAUDE.md, config Security-sensitive areas).
- A change to the hook contract (which events fire, what can block) is the user's decision
  (config Extra escalations). FR-014 and FR-015 are built only after the user approves the
  nudge design.
- The public-repo rule applies to every fixture and example.

## Assumptions (executive)

- Which command name? → `handoff`, a new `journal.py` subcommand — the issue names it, and
  `journal.py` already owns `status` and `position`.
- Does the brief take `--json`? → No — its only reader is a model; the HUD part is out of
  scope, and a JSON form would be a second contract to keep.
- Where does the brief get the rules that bind? → The config's Autonomy and
  Security-sensitive areas sections, plus a pointer to `CLAUDE.md` — these two sections hold
  the escalations and the confidentiality rule; CLAUDE.md loads in every session anyway.
- Where does "where to report" come from? → An optional `report_to` key on any event of the
  stream, newest wins, else the user — the journal is the only memory that survives `/clear`.
- How does the fresh session get the brief after `/clear`? → `/shipgate` runs `handoff`
  itself (FR-013) — the brief is built from files, so the new session builds the same one.
- How long may the brief be? → 60 lines at most on a typical stream — the status brief is
  already 107 lines per start (#31); the handoff brief must not add another long block.
- Which decisions does it list? → The last 5, with a count of the earlier ones — the same
  cut the status brief uses.

## Open questions

None. The user answered the nudge design (ADR 0022, accepted 2026-11-20).
