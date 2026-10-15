---
type: prd
title: "PRD: shipgate-hud — the flow position drawn in the interface"
created: 2026-10-06
updated: 2026-10-14
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

**Non-goals** (explicitly out of scope for slice 1)
- The Review findings board and the publish-gate hold on `gh pr create` / `git push`
  (slices 2 and 3 below). The Explore essential-files tracker, the Route & Map heat grid,
  the compaction-safe prompt attachment: later slices, each its own PRD section.
- Desktop-only drawing (SVG diagrams): slice 3 below. Slice 1 is terminal-first with text
  that also renders on desktop.
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


---

# Slice 2 — the publish gate on the real command

> A `tool.check` hook holds the commands that publish a branch until the stream's journal
> holds the same evidence `journal.py` demands before `mr-opened`.

## Problem

shipgate's rule is that an MR/PR goes up only after a `review-verdict` of `ready`, or the
user's own publish `gate-decision`, recorded after the last `task-done`. The journal enforces
it on the `mr-opened` event, which is written *after* the command ran. Nothing stands between
the model and `git push` or `gh pr create` itself: a session that forgets the rule, or a worker
that never read it, publishes first and is refused only when it records the fact. The hold
belongs on the command.

## Users & stories

- As the developer driving a flow, I want `git push` / `gh pr create` / `glab mr create` held
  until the stream is reviewed, so that an unreviewed branch never reaches the forge by mistake.
- As the developer, I want the hold to ask me in the engine's own dialog, defaulting to refuse,
  so that I can let one call through on purpose without touching the journal.

## Functional requirements

- **FR-020** — A `tool.check` hook on `Bash` recognises a **publish command** anywhere in the
  shell line. The publish commands are `git push`, `git subtree push`, `gh pr create`,
  `gh pr new`, `glab mr create` and `glab mr new`. `git push` is recognised with git's global
  options before `push` (`git -C <dir> push`, `git --no-pager push`) and with any option after
  it (`-f`, `--force-with-lease`, `-u origin x`, `--dry-run`). `gh pr create` is recognised
  with `gh`'s `-R`/`--repo` before `pr`. `glab mr create` is recognised with `glab`'s
  `-R`/`--repo` before `mr`. A program named by its path or escaped (`/usr/bin/git`, `\git`)
  is recognised.
  - A command starts after `&&`, `;`, `||`, `|`, `&`, a newline, `(` or `)`.
  - A command may sit behind a `VAR=value` or a redirection (`2>/dev/null git push`).
  - A command may sit behind the shell words `if`, `then`, `else`, `elif`, `do`, `while`,
    `until`, `{`, `}`, `!`, `coproc`, or `function <name>`.
  - A command may sit behind the wrappers `env`, `command`, `sudo`, `doas`, `nohup`, `time`,
    `timeout`, `nice`, `ionice`, `stdbuf`, `caffeinate`, `chronic`, `xargs`, `exec`,
    `builtin` and `eval`, with their options.
  - An unquoted `$(…)` or backtick run stays part of its word (`git -C $(pwd) push`). Its
    text is also read as a command line of its own (`echo $(git push)` is held).
  - A redirection ends a word (`git push>/dev/null` is held).
  - A backslash before a newline continues the line. A `#` that starts a word comments out
    the rest of the line.
  - Quoted text is one word and never a command. `grep "git push" f` and
    `git commit -m "git push"` are not held.
  - A heredoc body is a command line only when the command it is fed to is a shell (`bash`,
    `sh`, `zsh`, `dash`, `ksh`, `fish`, `eval`, `source`). `bash <<EOF` with `git push` in
    the body is held. `cat <<EOF` with the same body is not.
  - `git stash push` and `command -v git push` are not publish commands.
- **FR-021** — Before deciding, the hook refreshes the position (one journal round trip, inside
  the hook's budget) and takes the HUD's current stream (session match first, then branch). The
  stream is **publish-authorized** when, after its last `task-done` event, the journal holds a
  `review-verdict` with `verdict: ready` or a `gate-decision` with `gate: publish`,
  `raised_by: user` and `decision: publish` — the rule `journal.py` applies to `mr-opened`,
  computed from the stream's `log --json` events.
- **FR-022** — An authorized stream, no stream for this session, no sidecar, no `journal.py`
  found, or a session with no surface → the hook passes the call on (`next(e)`); the engine's
  own verdict stands. No process runs in a project without the sidecar beyond the existing
  guard.
- **FR-023** — An unauthorized stream, or a refresh that failed (the journal unreadable, the
  stream unknown because of an error) → the hook asks through `$.ui.ask` with the reason (the
  stream, the command head, what is missing) and two choices, **Refuse** and **Let it through
  once**. Any answer other than the exact "Let it through once" label, a dismissed dialog, or a
  rejected ask → `{ decision: 'deny', reason }`. The reason tells the model what the stream
  needs: record the review verdict, or stop and ask the user. It never tells the model to
  record a user decision itself; the user decides at the gate's dialog. "Let it through once"
  → `next(e)` for this call only; nothing is remembered.
- **FR-024** — The hook writes nothing to the journal and nothing to the transcript; the
  dialog is the record. It fails closed: a throw or a budget overrun inside the hook refuses
  the call through `.catch` when the command is a publish command, and passes a non-publish
  command on.
- **FR-025** — The hold applies to every loop: a worker subagent's `git push` is held and the
  question reaches the person in the main dialog.
- **FR-026** — Version 0.3.0: `shipgate-hud/.claude-plugin/plugin.json` and the marketplace
  entry in lockstep; the release note in `CHANGELOG.md` only.

## Success criteria

- **SC-010** — `claude plugin validate shipgate-hud` lists `tool.check{tool=Bash}` as a
  gating hook with `.catch` and no new process or network call outside the guarded paths.
- **SC-011** — `claude plugin test shipgate-hud`: each publish spelling above is recognised and
  each of `ls`, `git pull`, `git pushd`, `gh pr list`, `gh pr view`, `glab mr list` is not; an
  authorized stream passes through; an unauthorized one asks and denies on "Refuse", on free
  text and on a dismissed dialog, and passes on "Let it through once"; no sidecar → no ask, no
  process run; a failing refresh asks.
- **SC-012** — The built-in `/security-review` on the diff reports no finding at or above its
  own medium confidence that is left unaddressed.
- **SC-013** — Live: in this repository, on this stream before its review verdict, `git push`
  is held and "Refuse" denies it with a reason the model repeats.

## Assumptions (executive)

- `--dry-run` is held like any push → "any spelling" wins over a convenience exemption; one
  press lets it through.
- A refresh error holds rather than passes → the gate cannot be shown passed, and a silent
  pass on a broken journal is the failure the hook exists to stop.
- A session with no surface passes through → the HUD runs nothing without a surface (slice 1);
  headless publish policy belongs to shipgate's own hooks, not to a drawn surface. Flagged
  for veto.
- The hold is not remembered → "once" means this call; the next publish command asks again
  unless the journal moved.
- The gate trusts the journal. journal.py has no actor authentication, so a
  `review-verdict` of `ready` or a user publish `gate-decision` that the model appends itself
  authorizes a publish. The gate is a net for a forgetful model. It is not a boundary against
  a deliberate one (security review 2026-10-14).

---

# Slice 3 — the Review board and Design diagrams

> The review workflow's return drawn as a board with accept / kill, the PRD's success
> criteria as a checklist, and the worklog's diagrams drawn as pictures on desktop and as text
> in the terminal.

## Problem

The review phase produces its best evidence as a workflow return (`survivors`, `killed`,
`belowFloor`, counts, coverage) that lands in the transcript once and scrolls away; the
orchestrator's accept / reject calls are typed, not pressed. The design's diagrams live in the
worklog as fenced blocks that the Markdown element draws as grey code.

## Functional requirements

- **FR-030** — A `tool.call` hook on `Workflow` notes a launch of the shipgate review workflow
  (the script text or path names `shipgate-review`, or the tool result names the run id): the
  call's `tool_use_id`, the run id and the time. A `prompt.submit` hook whose origin is
  `task-notification` reads the notification's `<tool-use-id>`, `<status>` and `<result>`. The
  return is stored in the `review` atom only when the result parses as the review return
  shape (`survivors`, `killed`, `belowFloor` arrays and a `counts` object) and the status is
  neither `failed` nor `killed`. A noted launch never creates a board on its own: when the
  tool-use-id matches one, it supplies the run id and the stream shown at launch, and the
  board is filed under that stream; otherwise under the stream shown when the return arrives.
  The board carries the return's `aborted` reason when present. The hook never changes or
  drops the prompt, and stores nothing in a session with no surface. A notification that is
  not a review return passes untouched.
- **FR-031** — A **Review** tab (hotkey `4`, the default tab in the `review` phase) draws the
  board: the counts line (found, deduped, candidates, survivors, killed, below floor, refuters
  requested / reported, unverified), then the survivors grouped by severity in the order
  BLOCKER, HIGH, MEDIUM, LOW, each as one card with severity, confidence, verification and
  quorum, the lenses, `file:line` (the path shortened to its last three segments) and the
  summary; then the killed findings (one line each with the quorum) and the below-floor ones
  (one line each). The user's accept / kill marks are drawn on the card. Under the counts a
  line shows the run id and the capture time; an aborted run shows a warning line and the
  band's segment reads `review aborted`.
- **FR-032** — Each survivor carries **Accept** and **Kill** buttons. A press submits a plain
  prompt (not `asUser`) that names the finding by its position in the board, severity,
  `file:line` and lens, and asks the orchestrator to fix it in the implement round (Accept) or
  to record it under the worklog's Rejected findings with the user's reason (Kill). The prompt
  carries no summary, `why` or `fix` text from the return. The mark is kept in the `review`
  atom for the session.
- **FR-033** — The Review tab ends with the PRD's **SC-### checklist**: the `- **SC-NNN** —`
  lines of the `## Success criteria` section of the PRD the stream's `clarify-passed` event
  names (relative, in-project, no `..`), each with a toggle the user ticks as the orchestrator
  shows the evidence; the ticks live in the `review` atom for the session, keyed by stream,
  and a criterion id repeated across sections counts once. No PRD → one line saying so.
- **FR-034** — With no review stored for the stream, the tab says so and names the phase.
  `/clear` resets the pane state, the board included (the next review run fills it again). A
  stored review for another stream is not drawn.
- **FR-035** — In the **Design** tab a fenced block whose info string is `mermaid` or `svg` is
  drawn as a diagram instead of code. On a surface with `Svg` (desktop, mobile, vscode) an
  `svg` block is drawn as `Svg` with its source and the section title as `alt`; a source over
  the element's limit (131072 characters) is never cut: the non-picture form is drawn under a
  "too large" line; a `mermaid` flowchart (`flowchart` / `graph` with a direction, node shapes
  `[ ]`, `( )`, `{ }`, `(( ))`, edges `-->`, `---`, `-.->`, `==>`, edge labels `|text|` and
  `-- text -->`, doubled shapes mapped to the nearest of those, `subgraph` flattened, `%%`
  comment lines skipped) is laid out by the HUD into an SVG and drawn as `Svg`; a statement
  the HUD cannot read makes the whole block fall back to `Code`. In the terminal a flowchart is drawn as its text form: a layered box-and-arrow
  (`[A] ──► [B]`, edge labels in the arrow), and an `svg` block as `Code`. A mermaid block of
  another kind (sequence, class, state…) is drawn as `Code` with language `mermaid` on every
  surface. The prose around a block keeps rendering as Markdown.
- **FR-036** — The diagram parser and layout are pure (no `$`), live in their own module and are
  tested on the flowchart subset and on the fallbacks.
- **FR-037** — Version 0.4.0: `plugin.json` and the marketplace entry in lockstep; the release
  note in `CHANGELOG.md` only; README features updated, no release notes copied.

## Success criteria

- **SC-020** — `claude plugin test shipgate-hud`: a recorded task-notification of a review run
  (fixture in the public shape, generic paths) fills the board; the Review tab groups survivors
  by severity with lens, confidence, verification and `file:line`; Accept and Kill submit the
  named prompt without `asUser`; the SC checklist lists the PRD's criteria; the tab is the
  default in `review`.
- **SC-021** — `claude plugin test shipgate-hud`: a `mermaid` flowchart in a worklog Design
  section is drawn as `Svg` on desktop and as the box-and-arrow text in the terminal; an `svg`
  block as `Svg` on desktop and `Code` in the terminal; a `sequenceDiagram` block as `Code`
  on both.
- **SC-022** — `claude plugin validate shipgate-hud` lists `tool.call{tool=Workflow}` and
  `prompt.submit` beside the slice 2 hooks, all with `.catch`, and the new `review` state key.
- **SC-023** — The built-in `/security-review` on the slice 3 hook changes reports no
  unaddressed finding at or above its medium confidence.
- **SC-024** — Live: the Design tab of this stream draws this worklog's `mermaid` data-flow
  block as text in the terminal.

## Constraints & assumptions

- The `Workflow` tool returns immediately ("launched in background", a task id and a run id);
  the return object arrives later as a user-turn `<task-notification>` whose `<result>` holds
  the JSON with `<`, `>` and `&` HTML-escaped (observed in this repository's own review runs
  on Claude Code 2.1.29x–2.1.300). The HUD unescapes before parsing. A change in that envelope
  breaks the capture, not the pane: the hook passes the prompt on untouched.
- The hooks module has no DOM and no Node, so the Mermaid library cannot run in it. The HUD
  therefore lays out the flowchart subset itself (ADR 0002). No renderer process and no network
  call: a diagram never leaves the machine.
- `Svg` exists on desktop, mobile and vscode, not in the terminal; the drawing branches on the
  element table the engine resolves, as the views already do for width.

## Assumptions (executive)

- Review return captured at `prompt.submit` (task-notification), launch noted at `tool.call` →
  the tool result is a launch receipt, not the return; the notification is where the return is.
- Shape match accepted without a noted launch → module state is lost on a plugin reload while
  the review may still be running; the shape is specific enough (three arrays and `counts`).
- SC ticks are local (atom, per session) → the review-verdict event carries no per-criterion
  field; the orchestrator's evidence stays in the transcript, the tick is the user's own note.
- Accept / Kill prompts name, never quote → the same rule as Veto: journal and workflow text
  is read by the model from its own context, not re-submitted through the prompt.
- Band gains one segment, `review N open`, only while a board is held for the stream.
- Mermaid subset is flowcharts only → the worklog template's diagrams are data flows; other
  kinds fall back to `Code` and remain readable.

## Open questions

None.
