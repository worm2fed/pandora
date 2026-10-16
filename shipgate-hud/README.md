# shipgate-hud

A Claude Code **mod** for [shipgate](../shipgate): it draws where a flow stands, in the
interface, from the journal shipgate already keeps.

- **Band above the prompt** — `feat/x · implement · tasks 3/11 · verify pass 12:30 · 2 to veto`,
  and a `hud` button that opens the pane. A band narrower than the summary wraps it onto more
  rows at the ` · ` separators rather than cutting it.
- **Pane** (`/hud`, or opened at session start in a wide terminal) with the phase timeline
  `WS ✓ MAP ✓ EXP ✓ CLR ✓ DSN ✓ IMP ● REV · CAP ·` and four tabs:
  - **Flow** — the stream's gate decisions, newest first, with who raised each one. A
    decision the orchestrator took on its own (`raised_by: orchestrator`, `mode: executive`)
    carries a **Veto** button; pressing it submits a prompt that names that decision (stream,
    gate, timestamp) and asks the orchestrator to read it from the journal and revisit it.
    The prompt never carries the journal's own text.
  - **Plan** — a progress bar and the worklog's Build Plan under its section headers, one line
    per task, cross-checked against the journal: `✓` done with a `task-done` event and the last
    verify that covered it, `✗` when that last verify failed, `◐` ticked in the worklog but never
    recorded (what the Stop hook will block on), `○` to do.
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
  the subcommand. The command waits until the stream may publish. The stream may publish when
  the journal holds a `review-verdict` of `ready` after its last `task-done`. The user's own
  publish `gate-decision` after the last `task-done` also lets it publish. This is the rule
  journal.py applies to `mr-opened`.

  The gate finds the command anywhere in the shell line. It looks after `&&`, `;` or a
  newline. It looks behind shell words such as `if`, `do` or `{`. It looks behind wrappers
  such as `env`, `sudo` or `timeout`. Quoted text is one word and never a command. So a `grep`
  for the verb is not held. A heredoc body counts only when it is fed to a shell such as
  `bash`.

  Before it decides, the gate refreshes the position once. A stream that is not reviewed
  opens the engine's dialog with **Refuse** and **Let it through once**. A journal that cannot
  be read opens the same dialog. Any other answer refuses. The model then reads what the
  stream still needs: a review verdict to record, or a question for the user. It is never
  told to record the user's decision itself.

  The gate passes the command in these cases: the stream is reviewed, the session has no
  stream, the project has no sidecar, no `journal.py` is found, or the session has no surface
  (`claude -p`). It writes nothing and remembers nothing. The next publish command asks
  again. The gate trusts the journal. So it is a net for a forgetful model, not a boundary
  against a deliberate one.
  Known limits: the gate does not hold `"$(…)"` inside double quotes, `sh -c '…'`,
  `eval "…"`, `… | bash`, `ssh host git push` or `find -exec`.

The position refreshes when the orchestrator appends to the journal, when a file in one of
the sidecar's artifact homes is written, after `/clear` or `/resume`, and once a minute
otherwise. A request that arrives during a refresh queues one trailing refresh.

## What it needs

- Claude Code **2.1.290 or newer** (the mods API; early access, so a release may move it).
- **shipgate** installed from the same marketplace, and a project that ran `/shipgate:setup`
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

The hooks module runs with no Node and no SQLite, so it never opens the journal database.
One refresh is `git rev-parse --abbrev-ref HEAD`, then shipgate's own CLI —
`journal.py status --json --session=<id> --branch=<current>` and `journal.py log --stream <s> --json` —
then bounded reads of the worklog and ADR files those events point at (relative paths
inside the project only). The stream shown is the one **this session drives**: the status
call carries `--session=<$.session.id()>` and journal.py marks the live stream this session
last wrote to itself (hook-written events do not count). That stream may have no branch (an
epic's planning stream), and several sessions open on one project each see their own. A
session that has written to no live stream yet sees the stream of the checked-out branch; on a
branch with no stream the band is empty and the pane says so. A `journal.py` older than
`--session` refuses the flag, and the HUD then asks by branch alone. In an umbrella checkout (the
session directory is a plain folder or a repo of its own, the real repos one level down,
in `source/` or in `packages/`, and worktrees under `.worktrees/` beside the repos or inside
one) the session directory's branch carries no stream, so the HUD then asks each nested repo
and worktree for its branch (`git -C <repo> rev-parse --abbrev-ref HEAD`),
probes each distinct branch once, and shows the most recently active stream among the
matches (several nested repos may sit on branches with streams, one live, the rest dormant).
Dot-directories and `node_modules` are not looked into. When the events name no worklog yet,
the HUD looks in the sidecar's worklog home for a `*.worklog.md` whose name carries the
stream's slug (`feat/x-y` → `x-y`) and otherwise shows no plan. A worklog that another live
stream's events name belongs to that stream, so the HUD leaves it alone (`epic/x` next to a
child whose worklog is `x.worklog.md`); that check reads each sibling stream's log, and only
once a slug-named worklog was found. It writes nothing: a veto goes through the prompt, and
the orchestrator records the outcome.

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
  hooks/position.ts            pure: status / log / worklog / ADR → Position
  hooks/publish.ts             pure: which shell lines publish, and the hold's text
  hooks/review.ts              pure: task-notification → review board, Accept / Kill prompts, SC criteria
  hooks/diagram.ts             pure: mermaid flowchart subset → layout, SVG, terminal grid and text form
  hooks/views.tsx              pure: Position → band and pane trees
  types/index.d.ts             the $.state contract
  tests/                       claude plugin test — the world beneath the plugin mocked
  docs/prd, docs/adr           PRD, worklog and ADRs for this plugin
```

`claude plugin validate shipgate-hud` and `claude plugin test shipgate-hud` are the checks.
Nothing under `shipgate/` changes for this plugin to work.

## Roadmap

Later slices, each its own PRD section: the Explore essential-files tracker; a Route & Map
risk heat grid; a compaction-safe one-line position attached to every prompt.

Release notes: [CHANGELOG.md](./CHANGELOG.md).
