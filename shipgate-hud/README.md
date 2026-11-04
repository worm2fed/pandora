# shipgate-hud

A Claude Code **mod** for [shipgate](../shipgate): it draws where a flow stands, in the
interface, from the journal shipgate already keeps.

- **Band above the prompt** — `feat/x · implement · tasks 3/11 · verify pass 12:30 · 2 to veto`,
  and a `hud` button that opens the pane. A band narrower than the summary wraps it onto more
  rows at the ` · ` separators rather than cutting it.
- **Pane** (`/hud`, or opened at session start in a wide terminal) with the phase timeline
  `WS ✓ MAP ✓ EXP ↷ CLR ✓ DSN ✓ IMP ● REV · CAP ·` (`✓` done, `↷` skipped, `●` current, `↺`
  entered again after a move back, `·` to do; journal.py computes the marks) and four tabs:
  - **Flow** — the stream's gate decisions, newest first, with who raised each one. A
    route-and-map entry that recorded no risk signals shows one warning line above them
    (`route-and-map: no risk signals recorded · signals-missing deviation seq N`). A
    decision the orchestrator took on its own (`raised_by: orchestrator`, `mode: executive`)
    carries a **Veto** button; pressing it submits a prompt that names that decision (stream,
    gate, timestamp) and asks the orchestrator to read it from the journal and revisit it.
    The prompt never carries the journal's own text.
  - **Plan** — a progress bar and the worklog's Build Plan under its section headers, one line
    per task, as journal.py parsed it with the Stop gate's grammar. Each task has one state:
    `✗` when the last verify that covered it failed, `✓` done with a `task-done` event, `◐`
    ticked in the worklog but never recorded (what the Stop hook will block on), `○` to do.
    So the counts add up.
  - **Design** — the ADRs the design committed to, one line each, then the design's risk
    ranking when it recorded one (`RISK RANKING · <source> · seq N · fix · churn · fan-in`,
    then one line per file, drawn as READ FIRST draws it), and
    the worklog's Design section as collapsible `##` sections, one open at a time (prose reflowed to the pane's width).
    **Diagrams:** a fenced `svg` block is drawn as a picture on desktop, mobile and vscode, and
    as `xml` code in the terminal. The HUD lays out a fenced `mermaid` flowchart itself (the
    `flowchart` / `graph` subset of ADR 0002). It draws the chart as a picture on those
    surfaces. In the terminal it draws the chart as a grid of box-drawing characters (ADR
    0003): each node a box with its label inside, each edge a line with an arrowhead, the edge
    label on the line, dotted and thick edges with their own glyphs. A back edge that closes a
    cycle is listed under the picture as `[b] ──► [a]`. A picture wider than the pane is drawn
    top to bottom instead; when that is wider too, or the chart has more than 60 nodes, the
    HUD draws the one-line-per-edge text form under a note. The HUD also draws the text form
    when the picture is taller than 200 rows, has more than 200 edge legs, or has more than
    40,000 cells; the note names the reason. Labels are measured in code points, so a wide glyph
    (an emoji, a CJK character) can misalign a box by a cell. Doubled shapes take the nearest
    supported shape. Other Mermaid kinds, and a flowchart with a statement the HUD cannot read,
    stay code. No renderer process, no network.
  - **Review** — up to five rounds of the review workflow's return for this stream. The HUD
    reads each from the task-notification prompt and never changes that prompt. A long return
    that the engine cuts there is read from the task's output file (`…/tasks/*.output`, at most
    4 MiB). A **READ FIRST** block comes before the rounds when the last verdict that carries
    a risk ranking recorded one. Its head line names the source, the seq and the legend once:
    `READ FIRST · graph · seq N · fix · churn · fan-in`. Then the files come in risk order,
    one line each: the path, two spaces, and the three labels as bare words in the legend's
    order (`1. src/a.ts  top · high · -`; `-` is a label with no value). The labels are never
    cut. When a line is too wide for the pane, the HUD cuts the head of the path first
    (`1. …/hooks/register.tsx  top · top · low`). When even `…/` and the file name do not
    fit, the labels go on a second, indented line. A head line that is too wide breaks at
    its ` · ` separators. A counts line comes first in each round. Then
    the survivors, grouped by severity, each with confidence, verification, quorum, lenses
    and a short `file:line`. A finding the canon lens reported carries a `canon` tag: it breaks
    a rule of the project's style canon, so it is not a matter of taste. **Accept** and **Kill** submit a plain prompt that names the
    finding by its position, never by its text. The killed and below-floor findings follow,
    one line each. The tab ends with the success criteria of the stream's PRD, as ticks you
    set by hand. The last `review-verdict` gives ticks from the journal:
    `"criteria":{"SC-001":"met"}` shows `☑`, and `unmet` shows `☒`. A press sets your own tick
    over the journal's, until a newer verdict.

    **Finding states.** A card shows the finding's current state in place of the buttons:
    `fixing` (a fix is in progress), `fixed`, `rejected` or `deferred`. The state comes from
    `position`'s folded `dispositions` (HUD ADR 0008). shipgate's review skill records each
    state with a `review-disposition` event as soon as it decides it, and the verdict's map
    is the final word. journal.py folds them per finding key, and the latest event wins. A
    state recorded before the board was captured is not drawn on that board: it judged an
    earlier round. Your own Accept or Kill mark comes before the state.

    **The key match.** A key is `<path>:<line>` or `<path>:?`. The match runs over the whole
    board, in two passes. Pass 1 gives each card the first of: the exact `file:line`, the
    short `file:line`, the same two with case folded, then a key whose path ends the card's
    file on the same line, case folded (the longest path wins). A `file:?` key matches in
    pass 1 only a card with no line. Pass 2 is **line-agnostic**: a card with no state yet
    takes a key whose path ends its file on **any line**, case folded, from the keys no card
    took in pass 1. The longest path wins, then the nearest line; a `?` key is the farthest,
    so it is the last choice. So a fix that moved the line still reaches its card. A key that
    named one card exactly never labels another card of the same file, and a pass-2 key
    labels one card only.

    **One finding in two cases (#13).** Two lenses can spell one path in two cases
    (`src/widget/widget.test.ts:?` and `src/widget/Widget.test.ts:?`). Then the board shows
    two cards for one finding. In pass 1, a key labels every card whose path and line match
    the key in any case. So one disposition reaches both cards. Pass 2 still gives a key to
    one card only.

    **A round without a board.** A review run as an agent fan (`review: agents`) produces no
    board. With no board for the stream and a verdict or a folded state, the tab draws the
    round from the journal: `round N · verdict <ready|not-ready> · <time>` (or `round 1 · in
    progress` before the first verdict), the verdict's note, one line per folded key with its
    state, then the success criteria. The state is never cut: a key that is too wide loses its
    head first (`…/hooks/register.tsx:12  fixing`). A card's state cell keeps its whole word
    too, and the card's meta text gives way. A board, when held, wins.

    A key line can show the key's label, dim, after the key: `src/a.ts:12 · flush-older-sync`.
    shipgate 0.22.0 records a label with a `review-disposition` event, and `position` prints
    it. The key keeps its room first. The label gets only the room that the key and the state
    leave, and the HUD drops the label when fewer than 4 cells remain.

    Under each key, one dim line tells what the finding was (HUD ADR 0009). The journal holds
    no finding text, so the HUD reads that line from the worklog's review section. The section
    is every list item under a heading that starts with `Review round` or is `Rejected
    findings`, at any level. It ends at the next other heading at the same or a higher level.
    A review heading inside the section keeps the section open at its first level. Fenced
    code is inert. A fence closes only on its own marker character, in a run at least as long
    as the one that opened it. Each item gives its first backticked `<path>:<line|?>` location
    and the first sentence after it. The HUD removes control characters from the item. A
    sentence with no letter or digit counts as no sentence, and the HUD draws no line for it.
    The HUD matches a key to an item in this order:
    1. The exact location. The HUD drops a leading `./` on both sides.
    2. A path tail on the same line, case folded. One path ends the other at a `/`.
    3. The label as a whole word of the item's text, in any case. When the key has no label
       and is no location (a free name such as `flush-older-sync`), the key is the label.

    In each step the first item in worklog order wins. A key with no match has no text line.
    A worklog that uses another grammar gives no text, and the keys stay bare.

    The band shows `review N open` while findings have no mark and no state, or the state
    `fixing`: a finding that is being fixed is still open. With no board, the band shows
    `review N open` only while N folded findings are `fixing` and were recorded after the
    last verdict (all of them before the first verdict). A `fixing` the newest verdict did
    not close is stale, because the verdict is the round's final word; the round's lines
    still show it. Each return is a new round. The
    newest round opens first, and its header folds it. Up to four older rounds fold behind a
    one-line summary, with their marks kept. A board for another stream is not drawn.

    The HUD keeps the boards in `$.state`. `/reload-plugins` keeps `$.state`, so a board
    stays after a reload, and a test pins this. `/clear`, `/resume`, `/branch` and a new
    process reset `$.state`. A board captured before them is gone. The tab then draws the
    round without a board, with the finding text from the worklog.
- The pane opens on the tab that matches the phase: Plan in `implement`, Design in `design`,
  Review in `review`, Flow otherwise. The active tab and the current phase are drawn inverted.
  Hotkeys `1` `2` `3` `4` switch, `r` refreshes, while the pane has focus. Long text is
  truncated to the pane's width, except the success criteria, which wrap. The artifacts hold
  the full text.

- **Publish gate** — the gate holds `git push`, `gh pr create` (or `gh pr new`) and
  `glab mr create` (or `glab mr new`). It accepts git's, gh's and glab's global options before
  the subcommand. The command waits until the stream **of the branch it publishes** may
  publish (ADR 0005). The stream may publish when the journal holds a `review-verdict` of
  `ready` after its last `task-done`. The user's own publish `gate-decision` after the last
  `task-done` also lets it publish. journal.py computes this rule (the one `mr-opened` uses)
  and prints it as `publish`; the HUD does not copy it.

  The gate finds the command anywhere in the shell line. It looks after `&&`, `;`, `||`, `|`
  or a newline. It looks behind shell words such as `if`, `do` or `{`, and behind wrappers
  such as `env`, `sudo` or `timeout`. Quoted text is one word and never a command, so a
  `grep` for the verb is not held. A heredoc body, a here-string, or a literal string given
  to `sh -c`, `bash -c` or `eval` is read as a command line of its own.

  A line may hold several publish commands (`git push origin a && git push origin b`). The gate
  checks each one, and holds the line when any of them holds. The dialog names every held
  command with its stream, because one answer covers the whole line. For each command it finds which
  branch the command publishes:
  - **The directory.** The shell's directory, a `git -C <dir>`, or a `cd <dir>` earlier on the
    line. A directory the scan cannot read (`cd -`, `cd $X`, `git -C "$(…)"`) is unreadable.
  - **The branch.** A refspec names it (`git push origin feat/x`; `+src:dst` gives `src`,
    `refs/heads/x` gives `x`), and so do `gh pr create --head` and `glab mr create
    --source-branch`. Otherwise it is the HEAD of that directory. Several refspecs, `--all`,
    `--branches`, `--mirror`, `--tags` or a deletion name no single branch.
  - **The stream.** One `status --branch` call gives that branch's stream and whether it may
    publish. When the branch has no stream, or the gate cannot resolve the branch, it checks
    the stream the session is bound to instead.

  Before it decides, the gate refreshes the position once. A stream that is not reviewed
  opens the engine's dialog with **Refuse** and **Let it through once**. A journal that cannot
  be read opens the same dialog, and the hold names the failure. Any other answer refuses.
  The model then reads what the stream still needs: a review verdict to record, the journal
  to repair, or a question for the user. It is never told to record the user's decision
  itself.

  The gate passes the command in these cases: the stream may publish; neither the branch
  nor the session has a stream; the project has no sidecar; no `journal.py` is found; or no
  surface is drawing (`claude -p`). A read that fails never passes. The gate writes nothing
  and remembers nothing, so the next publish command asks again. The gate trusts the
  journal. It is a net for a forgetful model, not a boundary against a deliberate one.
  Known limits: the gate does not hold a command it cannot read: `"$(…)"` inside double
  quotes, `… | bash`, `sh -c "$X"`, `ssh host git push` or `find -exec`. It does not see a
  directory change made by a shell function, an alias, a sourced script, `eval 'cd x'` or an
  exported `GIT_DIR`. A bare `git push` is checked as a push of the HEAD branch, even when the
  repository's push settings publish other branches as well.

The position refreshes when the orchestrator appends to the journal, when a file in one of
the sidecar's artifact homes is written, and once a minute otherwise. A request that arrives
during a refresh queues one trailing refresh. `/clear`, `/resume` and `/branch` move the
session to a new id and reset the HUD's state. The HUD then detects the project again on the
next clock tick, tool call or prompt, when the HUD's state holds no project (the view is
`Off`). The check compares the session id first, so it costs one call when nothing changed.
A reset that keeps the session id is caught too: when the last detection found a project and
the view now reads `Off`, the HUD detects again, once.
The detection runs after the tool call or the prompt has passed on, never in its way. This
also works where organization-managed settings skip `classic.*` hooks for user mods. In a
project with no sidecar, that detection is one directory walk per session id, and it runs
no process.

## What it needs

- Claude Code **2.1.290 or newer** (the mods API; early access, so a release may move it).
- **shipgate 0.22.0 or newer.** The HUD's `plugin.json` declares it as a dependency
  (`>=0.22.0`), so installing or updating the HUD brings a matching shipgate. A shipgate
  outside the range keeps the HUD disabled, and `claude plugin list` names the requirement.
  0.22.0 prints a label for each folded finding key in `position --json`. 0.21.0 added the
  trace and the folded finding states, and records a finding's state when the review
  decides it.
- **The read floor stays 0.21.0.** A 0.21.0 `journal.py` prints no label. The HUD reads it,
  and the keys draw with no label. A `journal.py` that lags further behind (a lagging
  project install, a `journalScript` option, a `--plugin-dir` copy) and prints no `trace`
  key in `position --json` is outdated. The band says so, the pane names 0.21.0, and the
  publish gate is off until shipgate is updated. A `journal.py` older than 0.18.0 (no
  `position`) gets the same notice. A failed read of a current shipgate still holds.
- **After a shipgate release.** A session that you opened before the release keeps the old
  shipgate in memory. The HUD's dependency range then refuses to load the HUD. An
  organization-managed PreModelSwitch check can also block `/model` until
  `/reload-plugins`. Update the plugins, then run `/reload-plugins`.
- A project that ran `/shipgate:setup`
  with a journal: the HUD keys off the `.claude/shipgate.json` sidecar, in the session's
  project root (where it started; a shell `cd` does not move it) or any directory above it
  (a session inside a nested repo of an umbrella uses the umbrella's journal, as shipgate's
  hooks do).

In a project **without** that sidecar the mod draws nothing, opens no pane and runs no
process. `/hud` still exists and says so.

## Install

```
/plugin marketplace add worm2fed/pandora
/plugin install shipgate-hud@pandora
```

Or, for development, from a checkout: `claude --plugin-dir ./shipgate-hud`.

## How it reads the position

The hooks module runs with no Node and no SQLite, so it never opens the journal database. It
runs shipgate's own CLI, and journal.py computes every fact of the flow the HUD draws
(shipgate ADR 0009): the phases, the binding, the publish rule, the trace, and the folded
finding states with their labels. The HUD computes no flow rule of its own. It does three
things on the Review tab only (HUD ADR 0008): it matches a recorded finding key to a card,
it leaves out a state recorded before a board was captured, and it counts the open findings.
It also matches a finding key to an item of the worklog's review section, to draw what the
finding was (HUD ADR 0009). That match is display only: it changes no state and no count.
The HUD decodes the CLI's JSON strictly. A missing or mistyped key is an error the pane
shows, never a default. One key is the exception: a folded finding with no `label` key
reads as a finding with no label, because a 0.21.0 `journal.py` prints none. Inside the
trace, one recorded `ranking` that breaks journal.py's contract (a row written before
shipgate validated it) is drawn as "ranking unreadable", not as a failed read.

One refresh does these steps:
1. **Binding** (ADR 0004). `journal.py status --json --session=<id> --branch=<root branch>`
   finds the stream the session is bound to, in this order:
   - **Session:** the live stream this session last wrote to itself. Hook-written events do
     not count. It may have no branch (an epic's planning stream), and parallel sessions each
     see their own.
   - **Branch:** the stream of the branch checked out at the session root.
   - **Nested repos:** in an umbrella checkout (the real repos one level down, in `source/` or
     in `packages/`, plus worktrees under `.worktrees/` beside the repos or inside one), one
     more `status` call passes every nested branch. It binds only when they name exactly
     one live stream. A session opened inside an issue worktree, with every repo on one
     branch, binds that stream before its first write. An umbrella root with several live
     nested streams binds nothing. Dot-directories, `node_modules` and anything below
     `.worktrees/<name>` are not looked into.
2. **Position.** For a bound stream, `journal.py position --stream <s> --json` gives:
   - the phase marks;
   - the Build Plan tasks with their journal state;
   - the decisions with their `seq`;
   - the last verify and the last verdict;
   - whether the stream may publish;
   - its artifacts. When no event names a worklog, journal.py finds it by name;
   - the trace (ADR 0007, amended): the newest `review-verdict` and `design-committed` that
     carry a `ranking`, and every `deviation` of kind `signals-missing`. When the ranking
     comes from a verdict older than the last one, READ FIRST says `from an earlier
     verdict`;
   - the folded finding states (`dispositions`), and the last verdict's note and round.

   The HUD runs no `log` command. A bound refresh runs `status` and `position` only.
3. **Files.** The HUD reads only the worklog, the ADRs and the PRD that `position` names. It
   draws the design sections, the criteria and the finding text of a round without a board
   from them. It reads only relative paths inside the project.

What the pane shows:
- **No binding:** the band stays empty. The pane says that this session drives no stream,
  and names the live streams the checkout's branches name.
- **A failed read:** a failed `journal.py` run never reads as "no stream". The pane shows the
  failure, and the last position read, marked as stale.
- **An older shipgate:** a `journal.py` that does not know `position`, or whose `position`
  prints no `trace` key, gets a pane that names the minimum shipgate version (0.21.0).
- **A newer sidecar:** the sidecar `.claude/shipgate.json` carries a `version`. When that
  version is an integer higher than 1, the pane shows one warning line above everything
  else: `.claude/shipgate.json declares version 2; this HUD knows version 1 and reads only
  the keys it knows`. The refresh still runs with the keys the HUD knows. A newer sidecar is
  never a failed read.

The HUD writes nothing. A veto goes through the prompt, and the orchestrator records the
outcome.

`journal.py` is looked for, in order: the `journalScript` option; beside this plugin in a
marketplace checkout (`../shipgate/scripts/journal.py`, the plugin folder resolved through a
symbolic link); beside it in the plugin cache (`cache/<marketplace>/shipgate/<newest
version>/scripts/journal.py`); the plugin cache of the Claude config directory
(`$CLAUDE_CONFIG_DIR`, then `~/.claude`), any marketplace. Never a path taken from the
project. When none is found the pane says so and the band stays empty.

| Option (`/config` → shipgate-hud) | Default | Meaning |
| --- | --- | --- |
| `journalScript` | empty | Absolute path to `shipgate/scripts/journal.py`, when the lookup above fails |

## Layout

```
shipgate-hud/
  .claude-plugin/plugin.json   manifest (types, userConfig)
  hooks/hooks.json             { "modules": ["./register.tsx"] }
  hooks/register.tsx           the hooks and the side effects (locate, run, read)
  hooks/json.ts                pure: Result, parseJson, absurd, the narrowing and decode helpers
  hooks/journal.ts             pure: the one boundary for journal.py's JSON (decoders, brands)
  hooks/position.ts            pure: decoded position + worklog / ADR / PRD → Position
  hooks/publish.ts             pure: what a shell line publishes, the gate's verdict, the hold's text
  hooks/review.ts              pure: task-notification → review board, Accept / Kill prompts, SC criteria
  hooks/diagram.ts             pure: mermaid flowchart subset → layout, SVG, terminal grid and text form
  hooks/views.tsx              pure: Position → band and pane trees
  types/index.d.ts             the $.state contract
  tests/                       claude plugin test — the world beneath the plugin mocked;
                               fixtures.journal.ts is generated by shipgate's contract test
  docs/prd, docs/adr           PRD, worklog and ADRs for this plugin
```

`claude plugin validate shipgate-hud` and `claude plugin test shipgate-hud` are the checks.
The code follows astrolabe, adapted to a mod with no dependencies (ADR 0006).

Two traps in those checks:
- **`claude plugin test` does not type-check.** A `Position` built without a required key
  still passes. Run `tsc` as well, with a tsconfig that includes the engine's declarations
  in `.claude-plugin/types/`. The engine writes that directory into a plugin checkout it has
  loaded; a fresh git worktree lacks it, so point the tsconfig at the main checkout's copy.
- **A text query matches a substring.** `ui.find({ type: 'Text', text: 'canon' })` also
  finds every line that contains the word. Anchor a tag or a short label with a regex
  (`/^canon$/`).

## Roadmap

Later slices, each its own PRD section: the Explore essential-files tracker; a Route & Map
risk heat grid; a compaction-safe one-line position attached to every prompt.

Release notes: [CHANGELOG.md](./CHANGELOG.md).
