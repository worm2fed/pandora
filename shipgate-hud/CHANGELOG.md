# Changelog

All notable changes to the **shipgate-hud** plugin, newest first.

v0.5.0 — diagrams drawn in the terminal. The Design tab drew a flowchart in the terminal as a
list: one line per layer, one line per edge. It now draws the chart as a picture made of
box-drawing characters (ADR 0003). Each node is a box with its label inside: square corners
for a rectangle, rounded for a round node or a circle, slanted for a diamond. Each edge is a
line from its source box to its target box with an arrowhead at the target: `─` for a solid
edge, `┄` for a dotted one, `═` for a thick one, no head for an open one. The edge label sits
on the line. The layers run left to right for `LR` (`RL` mirrored) and top to bottom for `TD`
(`BT` mirrored). An edge that spans more than one layer passes between the boxes of the layers
in between. Two lines that cross draw `┼`. A back edge that closes a cycle is not routed; it is
listed under the picture as `[b] ──► [a]`. A picture wider than the pane is drawn top to bottom
instead. When that is wider too, or the chart has more than 60 nodes, the old text form is
drawn under a dim note. The HUD also draws the text form when the picture is taller than 200
rows, has more than 200 edge legs, or has more than 40,000 cells; the note names the reason.
Desktop, mobile and vscode still get the SVG.

v0.4.1 — the Review board reads the verdict. **Accept** and **Kill** are now dim bracketed
buttons, like **Veto**. The card header is one line of three cells. The severity sits in a
fixed cell, one cell wider than `▎ BLOCKER`, so a gap always follows it. The meta text is cut
to the room left. The state comes last: the user's mark, the orchestrator's disposition, or
the two buttons. Under the header, the card has two full-width lines. The short `file:line`
comes first, dim, cut only when wider than the pane. The summary follows, wrapped. Killed and
below-floor findings use the same two lines under a dim head. The counts line packs at its
` · ` separators, so no line starts with one.

The tab keeps review rounds. Each captured return is a new round of its stream, numbered from
1. A stream keeps its five newest rounds. The rounds fold like the Design tab's sections. The
newest is open: a `▾ round N · run … · HH:MM` header over the full board. An older round is
one line, `▸ round N · run … · HH:MM · N survivors`. A press opens it and folds the other.
The open round's header is a button too. A press on it folds every round, and the criteria
stay. The next captured return opens the newest round again.
A round is known by its stream and its number, so a round with no stream never shares a key
with a stream's round. A mark stays with its round. A dropped round takes its marks with it.
The Accept and Kill prompt names the round. The band reads the newest round. Each round's
counts line ends with its own `open N`. The criteria follow once, after the rounds. Marks
stored by 0.4.0 are remapped onto the round that held them. Ticks set by 0.4.0 are not kept.
A return delivered again, with the same stream and run id, replaces its round in place and
keeps its marks.

Each success criterion is now a row. A tick button sits in a fixed cell. The bold id and the
whole text follow, and the text wraps to the pane width. Nothing cuts it.

The last `review-verdict` of the stream may record the criteria and the findings. The
orchestrator writes them as
`journal.py append --type review-verdict --data '{"verdict":"ready","criteria":{"SC-001":"met"},"dispositions":{"src/a.ts:42":"fixed"}}'`.
A `met` criterion shows `☑`. An `unmet` one shows `☒`. Any other status shows `☐`. A press
toggles the user's own tick over the journal's status. Each press changes the glyph. A press
that lands on the journal's status drops the override. A tick holds against the verdict it
was made on. A newer verdict shows its own status again. A disposition is keyed by the
finding's full or short `file:line`; a leading `./` is dropped. A key also matches by path
suffix on the same line: `hooks/register.tsx:573` matches a finding the workflow reports at
`/abs/root/shipgate-hud/hooks/register.tsx:573`. The card shows `fixed` in
green, `rejected` in red and any other value dim, in place of the buttons. The value is drawn
at most 12 cells wide. A board captured after the verdict ignores its dispositions. A finding
with a mark or a disposition is not open.

Tests cover the criteria status and the dispositions from the last verdict, the tick
overrides, the glyphs and the press on each status. They cover the wrapped text, the button
style, a disposed card and the cut header on a narrow pane. They cover the rounds: the fold,
a mark per round, the cap of five, the band and the round in the prompt. They cover the
round keys, the pruned marks, the remapped old marks, a stale tick and a late board. They
cover the folded header and a cut refresh.

A refresh that the person cut is no error now. A denied or interrupted Bash call can cut the
journal run that the HUD makes inside it. The pane showed `$.process.run(python3) aborted`
until the next refresh. Now the HUD keeps the position and shows nothing. Only the engine's
own rejection counts as cut: an `AbortError`, or a message that ends in `) aborted`. A
journal.py run that exits non-zero is always an error, whatever its message says. The publish
gate never passes on a position that a cut refresh left behind. It asks, and the dialog says
the refresh was cut. Any other failure still shows.

v0.4.0 — the Review board and the Design diagrams. The review workflow's return arrived once
in the transcript and then scrolled away. The worklog's diagrams showed as grey code.

The pane has a new **Review** tab. Hotkey `4` opens it. It is the default tab in the `review`
phase. A `tool.call` hook on `Workflow` notes each launch of the shipgate review workflow. It
keeps the call's tool-use id, the run id from the result and the stream shown at launch. A
`prompt.submit` hook reads each task-notification prompt. It takes the notification's
tool-use id, status, result and output file. A long return is cut in the notification text.
The HUD then reads the task's output file that the notification names. That must be an
absolute `…/tasks/*.output` path, at most 4 MiB. A failed stat, read or parse stores nothing
and shows no error. Only a result with the return's shape becomes the board. A
failed or killed run is not stored. When the tool-use id matches a noted launch, the board
gets that launch's run id and stream. Otherwise it goes under the current stream. The hook
never drops the prompt and never changes it. Any other notification passes untouched. A
session with no surface stores nothing.

The board starts with a counts line: found, deduped, candidates, survivors, killed, below
floor, refuters requested and reported, and unverified. The survivors follow, grouped by
severity: BLOCKER, HIGH, MEDIUM, LOW. Each survivor is one card. The card shows the severity,
the confidence, the verification and quorum, and the lenses. It shows `file:line`, with the
path cut to its last three segments, beside the summary. Each card has **Accept** and
**Kill** buttons. A press submits a plain prompt, not as the user. The prompt names the
finding by its position, severity, `file:line` and lens. It never carries the finding's text.
Accept asks the orchestrator to fix the finding. Kill asks it to record the finding as
rejected, with the user's reason. The card then shows the mark. Killed findings and findings
below the confidence floor follow, one line each. A dim line under the counts shows the run
id and the capture time. A return that names an `aborted` reason shows it as a warning there.

The tab ends with the PRD's success criteria as a checklist. The PRD is the one the stream's
`clarify-passed` event names. The ref must be relative and inside the project, with no `..`.
A press ticks or unticks a criterion. A tick holds for its stream only. The ticks and the
marks stay in the session only. `/clear` resets the pane state, the board included; the next
review run fills it again. A board stored for another stream is not drawn. The band adds
`review N open` while a board for the stream is held. N counts the survivors with no mark.
For an aborted run the band says `review aborted`.

The Design tab now draws diagrams (ADR 0002). A fenced `svg` block is drawn as `Svg` where
the surface draws one: desktop, mobile and vscode. The terminal shows it as `xml` code. The
HUD parses a fenced `mermaid` flowchart itself. The subset is `flowchart` or `graph` with a
direction and the node shapes `[ ]`, `( )`, `{ }` and `(( ))`. Edges are `-->`, `---`,
`-.->` and `==>`, with `|label|` or `-- label -->`. A `subgraph` is flattened. A `%%` comment
line is skipped. A doubled shape such as `[[ ]]` or `{{ }}` maps to the nearest supported
shape. A statement the HUD cannot read makes the whole block fall back to `mermaid` code. On
those surfaces the HUD lays the chart out into an SVG. In the terminal it
draws the chart as box-and-arrow text, one line per layer. Other Mermaid kinds show as
`mermaid` code. The prose around a block stays Markdown. The HUD starts no renderer process
and makes no network call.

Tests cover the review module (22), the capture hooks and the buttons (23) and the Review tab
on terminal and desktop (5). They cover the PRD criteria (3), the diagram module (20) and the
Design tab's diagrams on both surfaces (5).

v0.3.0 — the publish gate. shipgate lets an MR/PR go up only after a `review-verdict` of
`ready`, or after the user's own publish `gate-decision`. That record must come after the last
`task-done`. journal.py checks this rule on the `mr-opened` event. That event is written after
the command ran, so nothing stopped `git push` itself.

A new `tool.check` hook on `Bash` now holds `git push`, `git subtree push`, `gh pr create`,
`gh pr new`, `glab mr create` and `glab mr new`. It accepts git's, gh's and glab's global
options before the subcommand. It accepts a program named by its path (`/usr/bin/git`). The
hook reads the line in one quote-aware pass. Outside quotes, a command starts after `&&`, `||`,
`;`, `|`, `&`, a newline, `(` or `)`. An unquoted `$(…)` or backtick run is read as a
command line too. A redirection ends a word, so `git push>/dev/null` is held. A command may
sit behind a `VAR=value` or a redirection. It may sit behind the shell words `if`, `then`,
`do`, `while`, `{`, `!`, `coproc`, `function <name>` and their kin. It may sit behind wrappers such as `env`, `sudo`, `timeout`, `nice`,
`xargs` or `eval`. Quoted text is one word and never a command. So a `grep` for the verb, or a
commit message that names it, is not held. A heredoc body counts only when it is fed to a
shell such as `bash` or `sh`. `command -v` only looks a name up and is not held.

The hook refreshes the position once. Then it applies journal.py's rule to the stream's
events. A reviewed stream passes. These cases pass too: a project without the sidecar, no
`journal.py` found, a session with no stream, and a session with no surface. An unreviewed
stream opens the engine's dialog with two choices: **Refuse** and **Let it through once**. A
journal that cannot be read opens the same dialog. A stored position does not pass while the
last refresh failed. Any other answer refuses the call. A dismissed dialog or a failed ask also
refuses it. The deny reason tells the model to record the review verdict, or to stop and ask
the user. It never tells the model to record the user's decision itself. The user decides at
the dialog. "Let it through once" covers that one call only. A worker subagent's publish
command is held in the same way. The hook writes nothing to the journal or the transcript. A
failure in the hook refuses a publish command through `.catch`. A failure passes any other
command.

The gate trusts the journal. journal.py has no actor authentication. So a verdict or a user
decision that the model appends itself still authorizes a publish. The gate is a net for a
forgetful model. It is not a boundary against a deliberate one.

Known limits: the gate does not hold `"$(…)"` inside double quotes, `sh -c '…'`, `eval "…"`,
`… | bash`, `ssh host git push` or `find -exec`.

Tests cover the command matcher on each spelling that must match. They also cover spellings
that must not match: `git pull`, `git pushd`, `gh pr list`, `gh pr view`, `glab mr list`,
`git stash push`, `command -v`, quoted text and a heredoc fed to `cat`. They cover the
authorization rule in the order journal.py applies it. They cover the hook with each answer, a
reviewed stream, no sidecar, no `journal.py`, no surface, a worker's call, no stream and a
failing journal.

v0.2.5 — a context ref is not the stream's worklog. A `flow-started` (or `phase-entered`,
`deviation`) event often cites an older slice's PRD and worklog as context; the HUD took any
`.worklog.md` ref from any event as this stream's worklog, so a new stream showed the previous
slice's Build Plan with every task unrecorded. Refs now count only from the events that commit
or work the artifact: `design-committed`, `design-queued`, `task-done`, `verify-run`,
`review-verdict`, `gate-decision`. A stream with no committed worklog shows no plan until
its design lands.

v0.2.4 — the HUD shows the stream this session drives, per session. It showed only the stream of
the checked-out branch, so a session driving a stream with no branch (an epic's planning stream)
saw whatever stream the checkout carried — in an umbrella, another session's work at another
phase. The status call now carries `--session=<$.session.id()>` and the HUD takes the stream
journal.py marks `session_match` (shipgate 0.14.5: the live stream this session last wrote to
itself), then the branch's as before; parallel sessions on one project each see their own. Still
one status call for a single repo. A `journal.py` older than `--session` refuses the flag as a
usage error (exit 2) and the HUD then asks by branch alone; any other failure is shown, not
papered over. Five tests; the umbrella test expects the session probe first.

v0.2.3 — anchored on the session root. The HUD took the session's directory from
`$.session.cwd()`, which follows the shell's `cd`: a turn that stepped into a nested repo moved
the sidecar lookup, the journal run and the branch along with it, and the pane then reported
"journal database not found" under that repo. Everything now hangs off `$.session.root()` —
where the session started, unmoved by a shell `cd` — the same anchor shipgate's hooks use;
only a relative path a tool was given still resolves where the tool resolved it. A refresh
with no project located yet (module state is empty after a plugin reload, while the stored
position and error survive it) now locates the project again and clears a stale error instead
of leaving an older module's message on screen. One test.

v0.2.2 — a stream checked out in a git worktree is found. The umbrella scan (0.2.0) skipped
dot-directories, so a branch checked out in a worktree under `.worktrees/` — where shipgate's
`workspace` skill puts one, beside the repos or inside one — was never probed and the pane said
there was no stream for exactly the work in progress. The scan now looks into each parent's and
each nested repo's `.worktrees/` (a repo, then its own worktrees, then the parent's). One test
extended.

v0.2.1 — a session opened inside a nested repo of an umbrella. The HUD looked for the
`.claude/shipgate.json` sidecar in the session directory only, so a session started in one
of an umbrella's service repos got the status brief from shipgate's hooks (which walk up to
the umbrella root) but a HUD that said there was no journal. The HUD now finds the sidecar
the way the hooks do — the session directory, then each directory above it — runs
`journal.py` in that project root (where it finds the sidecar and the database by itself),
reads the worklog and ADRs under it, and matches artifact writes against it (a path written
relative to the nested session directory, `../` included, is normalised first). In a plain
project nothing changes. Two tests.

v0.2.0 — umbrella checkouts. The branch came from `git rev-parse` in the session directory
only, so in an umbrella — a plain folder or a repo of its own with the real repos one level
down — the HUD found no branch (or the umbrella's own, which carries no stream) and drew
nothing. Now, when the session directory's branch matches no stream, the refresh asks each
nested repo (`*/.git`, `source/*/.git`, `packages/*/.git`, where setup looks; dot-directories
and `node_modules` skipped) for its branch, probes each distinct branch once, and shows the
most recently active stream among the matches — several nested repos may sit on branches
with streams, one live and the rest dormant. A single repo on a branch with a stream still
costs one status call. Also: the band's summary was cut with an ellipsis once it outgrew
the band's width, which on a normal terminal lost the verify time and the veto count; it
now wraps onto further rows at its ` · ` separators, no segment split, the `h: hud` button
staying on the first row.

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
