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
    decision the orchestrator took on its own (`raised_by: orchestrator`, `mode: executive`)
    carries a **Veto** button; pressing it submits a prompt that names that decision (stream,
    gate, timestamp) and asks the orchestrator to read it from the journal and revisit it.
    The prompt never carries the journal's own text.
  - **Plan** — a progress bar and the worklog's Build Plan under its section headers, one line
    per task, as journal.py parsed it with the Stop gate's grammar. Each task has one state:
    `✗` when the last verify that covered it failed, `✓` done with a `task-done` event, `◐`
    ticked in the worklog but never recorded (what the Stop hook will block on), `○` to do.
    So the counts add up.
  - **Design** — the ADRs the design committed to, one line each, and the worklog's Design
    section as collapsible `##` sections, one open at a time (prose reflowed to the pane's width).
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
    4 MiB). A counts line comes first. Then
    the survivors, grouped by severity, each with confidence, verification, quorum, lenses
    and a short `file:line`. **Accept** and **Kill** submit a plain prompt that names the
    finding by its position, never by its text. The killed and below-floor findings follow,
    one line each. The tab ends with the success criteria of the stream's PRD, as ticks you
    set by hand. The last `review-verdict` gives ticks from the journal:
    `"criteria":{"SC-001":"met"}` shows `☑`, and `unmet` shows `☒`. A press sets your own tick
    over the journal's, until a newer verdict. The same verdict's
    `"dispositions":{"src/a.ts:42":"fixed"}` shows on that card in place of the buttons. The
    band shows `review N open` while findings have neither a mark nor a disposition. Each
    return is a new round. The newest round opens first, and its header folds it. Up to four
    older rounds fold behind a one-line summary, with their marks kept. A board for another
    stream is not drawn.
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
the sidecar's artifact homes is written, after `/clear` or `/resume`, and once a minute
otherwise. A request that arrives during a refresh queues one trailing refresh.

## What it needs

- Claude Code **2.1.290 or newer** (the mods API; early access, so a release may move it).
- **shipgate 0.18.0 or newer** installed from the same marketplace (for `journal.py position`),
  and a project that ran `/shipgate:setup`
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
runs shipgate's own CLI, and journal.py computes every fact the HUD draws (shipgate ADR 0009).
The HUD decodes that JSON strictly. A missing or mistyped key is an error the pane shows,
never a default.

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
   - its artifacts. When no event names a worklog, journal.py finds it by name.
3. **Files.** The HUD reads only the worklog, the ADRs and the PRD that `position` names, to
   draw the design sections and the criteria. It reads only relative paths inside the
   project.

What the pane shows:
- **No binding:** the band stays empty. The pane says that this session drives no stream,
  and names the live streams the checkout's branches name.
- **A failed read:** a failed `journal.py` run never reads as "no stream". The pane shows the
  failure, and the last position read, marked as stale.
- **An older shipgate:** a `journal.py` that does not know `position` gets a pane that names
  the minimum shipgate version (0.18.0).

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

## Roadmap

Later slices, each its own PRD section: the Explore essential-files tracker; a Route & Map
risk heat grid; a compaction-safe one-line position attached to every prompt.

Release notes: [CHANGELOG.md](./CHANGELOG.md).
