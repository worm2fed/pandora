# shipgate

A lean, gate-driven feature-development plugin for Claude Code, built for anything from a
single repo to a multi-service umbrella. It's the synthesis of three systems — Anthropic's
**feature-dev** (the parallel-subagent engine + gates), GitHub's **spec-kit** (numbered
requirements, the clarify scan, CLAUDE.md-as-constitution), and **ai-devkit** (evidence-based
`verify`, memory discipline, breaking-change rules) — with the ceremony stripped out.

Nothing project-specific is hardcoded. Two files adapt the plugin to a project:

- the repo's **`CLAUDE.md`** files — routing and code conventions (where code belongs,
  build/test commands); the plugin *reads* them and enforces whatever they declare.
- an optional **`.claude/shipgate.md`** — process tooling (see **Configuration** below).

## The flow

```
Workspace → Route & Map → Explore → Clarify (gate) → Design → Implement → Review → Capture
```

Ceremony scales to the change: a one-line bugfix goes Workspace → Route & Map → fix → verify; a real
feature runs the whole flow. Backward transitions (review → implement, design → clarify) are normal.

Start or resume work with **`/shipgate [description]`**, or just describe a feature/bug and the
`feature` orchestrator will route it.

## Configuration

Run **`/shipgate:setup`** in a project and it does this for you: detects the repo's shape,
asks a handful of questions with recommended defaults, writes the settings file
`.claude/shipgate.json` and the config `.claude/shipgate.md`, and — if you want one —
initializes the flow journal. Re-running it enters update mode rather than clobbering what's
there.

shipgate reads two kinds of file (ADR 0028):

- a **settings file** holds the **settings**: values from fixed sets that scripts, hooks and
  skills read, such as `autonomy` or `artifact_homes`. It is JSON.
- the **config** holds behaviour in words that the model reads: the knowledge stores, the
  tracker, branch naming, guardrails, extra escalations. It is markdown.

### Settings

A settings file is one JSON object with `"version": 2`. There are two:

- the **project settings file**, `.claude/shipgate.json` at the project root. It marks the
  project root. `"db": null` in it declares that the project has no journal.
- the **user settings file**, `$CLAUDE_CONFIG_DIR/shipgate.settings.json` when that variable
  is set and not empty, else `~/.claude/shipgate.settings.json`. It holds your personal
  settings for every project. No walk for `.claude/shipgate.json` finds this name, so it never
  marks a project as journaled, and no hook script reads it.

`settings.schema.json` in this plugin names every setting. Edit a settings file by hand or
with `/shipgate:setup`; shipgate checks it on every read.

| Setting | Values | Default | Sets | Scope |
| --- | --- | --- | --- | --- |
| `version` | an integer, 1 or more | `2` | the format of the file; a higher version is a warning, and the known keys are still read | project |
| `db` | a path from the project root, or `null` | `.claude/shipgate.db` | the journal database; `null` declares no journal | project |
| `ledger` | a path from the project root | `docs/ledger.md` | the ledger file | project |
| `artifact_homes.prd` | a glob | `docs/prd/*.md` | the PRD home | project |
| `artifact_homes.adr` | a glob | `docs/adr/*.md` | the ADR home | project |
| `artifact_homes.worklog` | a glob | `docs/prd/*.worklog.md` | the worklog home | project |
| `enforce.stop_gate` | `true`, `false` | `true` | the Stop gate | project |
| `enforce.auto_capture` | `true`, `false` | `true` | the auto-capture of artifact writes | project |
| `enforce.command_gate` | `true`, `false` | `true` | the command gate; `false` lets a model commit, push and open an MR/PR with no go from you, which an unattended project needs | project |
| `autonomy` | `ask`, `executive` | `ask` | who answers routine gate questions: you, or the orchestrator, which records each answer and still asks the cases of the executive contract in the `feature` skill | any |
| `clarify_confirm` | `risky`, `off` | `risky` | in `executive` mode, whether clarify puts its risky assumptions to you in one dialog before design; `off` only lists them in the phase summary | any |
| `ui.globs` | a list of globs on paths from the project root | `[]` | the project's UI files, for visual evidence on UI tasks (ADR 0031); `[]` turns it off | project |
| `ui.widths` | a list of at least one integer from 200 to 4000 | `[390, 1280]` | the CSS widths in pixels that each UI task shows | project |
| `ui.capture` | a command with `{url}`, `{width}` and `{out}` and no quote, backtick or backslash, or `null` | `null` | a capture command that the journal prints, one per width, with the URL and the out path quoted for the shell; it never runs it | project |
| `orchestration.review` | `agents`, `workflow` | `agents` | whether the Review fan runs as `Agent` subagents or as the bundled `Workflow` script | any |
| `orchestration.explore` | `agents`, `workflow` | `agents` | the same for the Explore fan | any |
| `writing_style` | `plain`, `ste-80` | `plain` | whether the documents shipgate writes into the repo and forge (PRD, ADR, worklog, ledger, MR/PR body, tracker comments) follow the STE-80 "Writing for people" rule; reports to you follow it always | any |
| `code_graph` | `auto`, `off`, `root` | `auto` | the code graph (see [Code graph](#code-graph)) | any |
| `code_signals.window_months` | an integer from 1 to 1200 | `12` | the history window of the code signals | project |
| `code_signals.fix_pattern` | a regex over the commit subject | the built-in pattern | which commits count as fixes | project |
| `code_signals.exclude` | a list of globs | `[]` | paths added to the built-in excludes | project |
| `code_signals.ranking_exclude` | a list of globs | the release files | paths the risk ranking leaves out; the list replaces the built-in one, and `[]` turns it off | project |
| `handoff` | `off`, a token count such as `300000`, or a count with `k` or `m` such as `500k` | `500k` | the context size past which the PostToolUse hook recommends a fresh session after a design commit or a not-ready review verdict | any |
| `forge` | `github`, `gitlab` | unset: the host of the PR/MR URL or of the git remote | the forge CLI that the close-out, the sweep and the skills use (`gh` or `glab`) | project |

`artifact_homes` also takes a glob for any other kind of artifact. The PRD, ADR and worklog
homes are the directories of their globs.

**How a setting resolves.** Per key, nearest first:

1. the project settings file;
2. a legacy line in the project's `.claude/shipgate.md` files (the repo's, then the
   umbrella's, by the config's per-section rule below);
3. the user settings file;
4. a legacy line in the user file `shipgate.md`;
5. the default in the table.

A layer that does not set a key lets the next layer show through. Objects merge per leaf
key, so a project can set `orchestration.review` alone. **Scope:** a `project`-scope key in
the user settings file is ignored, and `journal.py doctor` reports it. Else one line there
could turn off the command gate or share one journal across every project. `Inherit: none`
governs the config's layers only.

**`journal.py config [KEY ...] [--json]`** prints each setting with its value and its source:
the settings file, `legacy` with its file, or `default`. A key is a setting
(`orchestration.review`) or a group (`orchestration`); with no key it prints all. It needs no
journal database. It exits 0; 2 for a value outside its set or an unknown key; 1 for a
settings file that is not a JSON object. The SessionStart status brief carries the values of
`autonomy`, `orchestration`, `writing_style` and `code_graph` in one `settings:` line, and
the skills read that line first.

**A bad value.** A value outside its set in a settings file stops each command that reads the
key with exit 2: `journal.py config`, `signals.py`, `handoff`, `closeout` and `sweep`. The
message names the file, the key, the value and the allowed values. The hooks, and the journal
commands that a hook runs (`status`, `nudge`, `append`), use the key's default instead, and
every `enforce` setting stays on. The status brief names each bad key once, the keys the
hooks read (`db`, `enforce`, `artifact_homes`) too. An unknown key and a `version` above 2
are warnings.

**A settings file that cannot be read.** When the project settings file is not a JSON
object (not valid JSON, not UTF-8, a list), the hooks fail open: the project acts as one with
no journal, so every gate is off, and a broken file never blocks a session. The SessionStart
hook then adds one line to the session context. It names the file and `journal.py doctor`,
and it never repeats the file's content. A project with no settings file pays nothing for
this check.

**Legacy lines.** A config written by an older shipgate can still hold a setting as a
`- Key: value` bullet, such as `- Mode: executive` under `## Autonomy`. Such a legacy line is
still read, at its layer in the list above, until 2027-01-23. The status brief counts the
legacy lines and names that date. `/shipgate:setup` moves them into the settings files: it
shows the diff first and writes only on a yes. A legacy line with a value outside its set is
ignored and named. The first release after the date stops reading legacy lines. The
Knowledge base section's `PRD home`, `ADR home`, `Worklog home` and `Ledger` bullets are
legacy lines of `artifact_homes` and `ledger` when they name a repo path: the skills read
them, through `journal.py config`, while the settings file does not set the key; the hooks
and `status` read the settings file only. A home outside the repo, such as a wiki, stays
words in that section. `setup` removes a home bullet only when the settings file already
gives the same home; for any other, it shows the difference and asks.

### The config

`setup` writes a lean file: a one-line title and `- Key: value` bullets, with no template
comments and no prose that explains the plugin. On a machine with no user file, it offers
once per run to write one with your personal answers. In update mode it strips that
boilerplate from an older config with `scripts/lean_config.py` (ADR 0019). A line the script
does not recognise stays. The script removes a block only when every sentence in it is
boilerplate it knows. A block that also holds a project sentence stays whole, and the script
reports it as `mixed`, for you to split by hand. `setup` shows the diff, and the script
writes only on a yes.

Or do it by hand: copy `config-template.md` from this plugin into your project as
**`.claude/shipgate.md`** and fill in what applies. Skills read it at the start of a flow and
treat it as overriding their defaults; subagents get the relevant excerpts pasted into their
briefs. Every section is optional — with no config at all, shipgate still works on sensible
defaults (in-repo `docs/prd|adr/`, forge auto-detected from the git remote). The template's
comments and this section explain each section, so a project's config does not repeat them.

**How the config files layer** (ADR 0018). This section and the header of
`config-template.md` state the rule, and every skill cites them. shipgate reads these files,
nearest first:

1. the repo's `.claude/shipgate.md` files, from the working directory up to the repo root;
2. the umbrella's `.claude/shipgate.md`, in an umbrella checkout;
3. the user file: `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set and not empty,
   else `~/.claude/shipgate.md`.

The built-in defaults come last. The config is resolved per section. For each `##` section,
the nearest file where the section is present supplies the whole section. A section present
in a nearer file replaces the farther one whole, and sections never merge line by line. A
section is present when its heading exists and it holds at least one value that is not an
angle-bracket placeholder. A section with placeholders only, or with no bullets, is absent,
and the next layer shows through.

The user file uses the same section names and keys as a project's config. It holds what is
personal and the same in every project: usually the Library docs line, the Autonomy
section's Extra escalations, and the ledger's promotion target for preferences. A nested
config takes nothing from the umbrella's config when the line `Inherit: none` stands under
its title, before its first section. The user file and the built-in defaults still apply.

What the sections configure:

| Section | Configures | Default without it |
| --- | --- | --- |
| Knowledge base | where captured knowledge lives (in-repo paths or an MCP-backed wiki), page conventions, and the ledger's project promotion targets | capture to repo docs; at triage, personal workflow preferences go to the harness's built-in memory and everything else is dropped |
| Forge & tracker | the tracker, MR/PR template + fetch command, issue-link form, AC source, bug provenance | issue context from whatever CLI/MCP is available |
| Branching | branch naming pattern + examples | `<type>/<issue-id>-<slug>` |
| Repo layout | umbrella / nested-repo checkouts, where the real repos live | working dir is the repo |
| Style | a project style skill to invoke before writing/reviewing code | match surrounding code |
| Security-sensitive areas | domains that trigger the full `/security-review` | auth, secrets, payments |
| Debug evidence sources | prod/QA log-query skill, CI-log integration | local logs, tests, debugger |
| Epic workflow | epic decomposition command, ordering, delivery rules | issue-by-issue, manual decomposition |
| MR watcher | a project skill that watches open MRs/PRs + the command to register a blocker/follow-up on its watch list | no watcher — the flow ends at "MR/PR opened" |
| Close-out | the project's own post-merge steps, `- <Label>: <action>`; each one is an arbitrary command, so each waits for the one close-out question | the close-out's built-in steps only |
| Code tooling | the library-docs tool/MCP to consult for a dependency's current API (an override), and the LSP tool for symbol navigation | library docs from a context7-style MCP when the session has one, else training knowledge / WebFetch; grep-and-read |
| Worker guardrails | the repo's own hard rules, pasted verbatim into every worker brief after the built-in worker discipline | only the built-in worker discipline in `model-tiers`: branch check, no staging, the git index, no `--no-verify`, no repo-wide formatter, stop-and-report, comments, evidence |
| Thinking lenses | which lens *skills* to invoke at which phase, overriding the inline bullet (e.g. one from [cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills)); a large lens plugin costs skill-listing space in every session, so map only what you need | no lens skills invoked — the phase skills apply each lens inline |
| Autonomy | `Extra escalations`: the cases the orchestrator must still ask about in `executive` mode, on top of the executive contract, which lives in the `feature` skill | none beyond the executive contract |

## What's inside

**Command**

- `/shipgate` — entry point; drives the `feature` orchestrator.

**Skills**

- `feature` — orchestrator: detects phase from artifacts, routes, owns escape hatches, drives epics issue-by-issue.
- `setup` — bootstrap: detects the repo's shape, interviews with recommended defaults, writes the settings file `.claude/shipgate.json` and the config `.claude/shipgate.md`, and initializes the flow journal. Re-run to update.
- `workspace` — the first phase: get onto the right branch (`<type>/<issue-id>-<slug>`) off a clean base before any work; never builds on the wrong checkout — and never on an umbrella repo.
- `route-and-map` — reads CLAUDE.md (root + each touched module) + the knowledge base, emits an impact map. Also answers a standalone "what does this change affect?".
- `clarify` — the Clarify gate: coverage scan, prioritized questions, writes the PRD (FR-###/SC-###).
- `design` — parallel architects → recommendation → ADR(s) + worklog (Design + Build Plan).
- `implement` — reuse-first execution, breaking-change discipline, per-task `verify`.
- `review` — parallel reviewers report everything scored (coverage over self-filtering); a separate orchestrator pass filters at ≥80 confidence. A canon lens loads the config's style skills when it names any. Plus CLAUDE.md compliance, acceptance-criteria check, final `verify`. Also answers a standalone "rank the changed files by risk", and the re-review after a round of fixes ("I've addressed F1 and F2 — good to push?"), scoped to the fix diff.
- `verify` _(cross-cutting)_ — no "done" without fresh command evidence. A UI task (the `ui.globs` setting) also needs a registered screenshot at each width of `ui.widths`, read by the one who took it, or a recorded reason why none could be taken (ADR 0031).
- `model-tiers` _(cross-cutting)_ — the orchestrator never types product code; implementation goes to worker subagents one tier below the session but never below Opus, and only very mechanical sub-work sinks to the cheapest capable tier.
- `knowledge-base` _(cross-cutting)_ — recall/capture durable knowledge, routed by type to the stores the project config declares (default: repo docs). Named to avoid colliding with Claude's built-in session memory.
- `structured-debug` — on-demand: evidence-first debugging for bugs, regressions, incidents — a pasted stack trace with no repo access included, and a report that says "just fix it" (the fix still waits for an approved plan). Also answers a standalone "which file has the defect?".

Security, simplification, and test-first are folded into the flow rather than living as
separate skills: the `code-reviewer` agent carries a security + simplicity lens, `implement`
writes the failing test first, and Claude Code's built-in `/security-review` and `/simplify`
cover dedicated audits/cleanups.

**Thinking lenses** are folded in the same way — a few lines in the phase that needs them,
each with the condition under which it applies, so they fire at the right moment and cost
nothing in the skill listing: `design` (reversibility, pre-mortem, steel-manning, second-order,
via-negativa, TRIZ, margin-of-safety), `structured-debug` (occam's-razor, kepner-tregoe,
five-whys-plus, map-territory, OODA, systems), `feature` (Cynefin, to scale ceremony by
uncertainty as well as size), `clarify` (jobs-to-be-done, first-principles), `implement`
(sunk-cost, bounded-rationality), `review` (steel-manning on a disputed finding),
`knowledge-base` (circle-of-competence), and the `code-reviewer` agent (red-team / inversion).
The lens text is condensed from [cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills)
(MIT, © 2025 TJ Boudreaux) — see `NOTICE`.

**Subagents** (the engine, run in parallel)

- `code-explorer` — grounded exploration, file:line, essential-files list; reads refs that are not checked out and the history with read-only git (the orchestrator fetches first).
- `code-architect` _(opus)_ — one committed design philosophy per instance.
- `code-reviewer` _(opus)_ — every finding scored (confidence + severity), file:line; the orchestrator filters. Can load a skill, for the canon lens.

**Scripts** (Python 3 stdlib)

- `scripts/journal.py` — the flow journal CLI, an entry point over the modules of `scripts/_journal/` (ADR 0027); `scripts/signals.py` — per-file risk signals, read by `route-and-map`, `review` and `structured-debug` (see [Code signals](#code-signals)).
- `scripts/lean_config.py` — strips the boilerplate that explains the plugin from a config; prints a diff, and writes only with `--apply` (run by `setup` in update mode; ADR 0019). `--move-settings <project root>` moves the legacy lines of the project's, the nested repos' and the user's configs into the settings files, by scope; it shows every file's diff and its notes first, and writes only with `--apply` (ADR 0028).

**Glossary** — [`docs/glossary.md`](docs/glossary.md): one term per shipgate concept, what it means and what it is not to be confused with. Prose in this plugin uses those terms and no synonyms. Every report a person reads follows the **Writing for people** rule (short sentences, one idea each, every fact kept; ADR 0006); the `writing_style` setting extends it to the documents shipgate writes into your repo.

## Artifacts (3 per feature)

Homes are set by the `artifact_homes` setting; defaults shown:

- `docs/prd/<name>.md` — PRD: what & why (FR-###, SC-###). No implementation.
- `docs/adr/NNNN-<title>.md` — one ADR per genuine decision fork. Immutable; supersede.
- `docs/prd/<name>.worklog.md` — one worklog next to its PRD: **Design** section +
  **Build Plan** section (tasks with tests, `[P]` markers, progress). Tests are tasks, never
  a separate doc.

## Knowledge base

`knowledge-base` routes durable knowledge **by type** to its natural home, rather than dumping
everything in one store. The stores themselves come from the project config — a team wiki
over MCP, in-repo docs, or both; without config:

- **Engineering** — decisions, PRDs, conventions, gotchas, root causes → the **repo**
  (`docs/adr/`, `docs/prd/`, `CLAUDE.md`). Lives with the code, versioned and reviewed with it.
- **Product/domain insight** → a vault MCP if one is available — sparingly; otherwise the repo.

No npx/SQLite dependency; everything is git-visible or in a store you chose. Recall mirrors
the split and degrades gracefully if a store isn't reachable.

Between recall and capture sits the **ledger** (`docs/ledger.md` by default): one dated line
per learning, appended the moment it surfaces — `structured-debug` at the confirmed root
cause, `implement` at each task tick, `review` while ranking findings — and triaged at
Capture, where each line is promoted to its home or dropped.

## Flow journal

On a journaled project (`/shipgate:setup` writes the settings file and creates the database) position
is an append-only event stream — **one stream per issue, named for its branch** — rather than
something re-inferred from artifacts every session. The SessionStart hook injects the status brief
at every session start (`startup`, `resume`, `/clear`, a compaction, a fork). The brief prints
only the **bound** streams in full: the stream this session last wrote to (`--session`,
marked `· this session`: what a compacted or resumed session was driving, branch or no
branch), then the checked-out branch's. Every other stream goes into one count line (ADR
0024). `scripts/journal.py` is the whole interface:

| Command | Does |
| --- | --- |
| `status [--session ID] [--branch B] [--nested-branch B …] [--feature SLUG] [--all] [--json]` | the status brief. The stream the session drives comes first. That is the live stream that session last wrote to itself (`--session`); hook-written events do not count. It may have no branch, and parallel sessions each get their own. The checked-out branch's stream comes next, and both are shown in full. A bound stream that another session wrote within 30 minutes carries an `ownership` line, and one with an `mr-opened` carries a `close-out` line that names the command. Every other stream goes into one count line: live, dormant and finished, with the commands that list them (`streams --open`) and close the dormant ones (`sweep`); a zero count is left out (ADR 0024). `--all` and `--feature` print every selected stream as before: in full, dormant ones in one line, completed ones with `--all` only. In an umbrella, the nested repos' branches (`--nested-branch`, repeatable) stand in when `--branch` names no stream. They bind a stream only when they name exactly one live stream (shipgate-hud ADR 0004). With `--json`, each open stream also carries `publish`, `go` (the user's go per gate, ADR 0023), `lifecycle`, `current`, `last_writer` (`{session, ts}`), `pull_request` (`{url, ref, ts}` of the newest `mr-opened`) and `other_session` (`{minutes}` or null), and the top level carries `nested_matches`. The brief ends with the `settings:` lines (ADR 0028): the values of `autonomy`, `orchestration`, `writing_style` and `code_graph` with their sources, one line per key that a settings file sets to a value outside its set, one line per settings file that cannot be read, and, once the schema names the grace date, the count of legacy lines. `--json` carries them as `settings` (`{key: {value, source, path, section?, problem?}}`) and `legacy` (`{count, until, ended}`) |
| `position --stream S [--json]` | every fact the shipgate HUD draws for one stream (ADR 0009): phase marks (`done`, `skipped`, `current`, `revisited`, `todo`), the artifacts classified with the configured homes, the Build Plan tasks parsed with `check`'s grammar, gate decisions with their `seq`, the last verify, and the last verdict with its `note` and `round` (the verdict's count). `trace` carries the newest review and design `ranking` and every `signals-missing` deviation. `dispositions` carries each review finding's current state (`fixing`, `fixed`, `rejected`, `deferred`), folded from every `review-disposition` and every verdict's map, the latest event winning per key (ADR 0014). Each entry also carries `label`: the newest name a `review-disposition`'s `labels` gave that key, or null. It also carries `go`, as `status --json` does. An unknown stream exits 1 |
| `handoff --stream S` | the brief a fresh session continues one stream from (ADR 0021): its role, the request, the phase and the next one, where to report (the newest `report_to` an event names, else the user), the artifacts to open in reading order, the next Build Plan task, the open gates (an ADR still `proposed`, a `not-ready` verdict, findings still `fixing`, ticked tasks with no `task-done`, a failed verify, the publish gate), the last five gate decisions, the resolved `autonomy` setting with its source, and the config's **Autonomy** and **Security-sensitive areas** sections through the layers. Built from the journal, the files its events name and the config, never from the session; `design` prints it at `design-committed` and `/shipgate` reads it on a resume. After `mr-opened`, on a stream not finished, it names the close-out command. Text for a model, no `--json`. An unknown stream exits 1 |
| `digest --stream S [--all] [--json]` | the table the user reads before the publish question (ADR 0030): one markdown table, its only text form. The header row names the stream, the newest verdict with its round and whether the user's publish go is on record. Then 3 rows of what changed, from the worklog's `## What changed` section (1 to 5 one-line items); 2 of decided alone, the PRD's open assumption lines (risky first) and the executive gate decisions after the last `clarify-passed`; 2 of deviations after the last `design-committed`, without the bookkeeping kinds and without `screens-waived`; for a stream with a UI task, a Screens part (ADR 0031): a row with the stream's evidence directory, then 2 rows of UI tasks with their widths, their waiver reason or what is missing, the missing ones first; and a Look first row with the first 3 files of the newest risk ranking. A part over its slot names its full count; `--all` prints every item. At most 13 lines of at most 160 characters, and every value is escaped for markdown. A section it cannot read prints its file, line and reason, and it still exits 0. It writes nothing and runs no git. `--json` is the contract. An unknown stream exits 1 |
| `screens --stream S --task T --file F [--file F …] [--width W]`, `screens --stream S --task T --url U`, `screens --stream S --list [--json]`, `screens --prune` | the evidence store of UI tasks (ADR 0031). `--file` registers PNG screenshots: it reads each file's pixel width, maps it to a width of `ui.widths` at 1x, 2x or 3x (`--width` settles a width that matches two), and copies the file to `<root>/<project key>/<stream>/T<n>-<w>.png` (then `-2` to `-9`). It refuses a stream with no events or a finished one, a task id that is not `T` and digits, a file that is no PNG, and a width that matches no set width; one bad file refuses the whole call. `--url` prints one `ui.capture` command per width, the out path filled in; it runs none. `--list` prints each UI task of the stream's worklog: the widths present, the waiver reason, or the widths missing. `--file` and `--url` first remove this project's directories of finished or unknown streams and every file over 30 days in the root, as `--prune` does. The root is `$CLAUDE_CONFIG_DIR/shipgate/evidence`, else `~/.claude/shipgate/evidence`; with neither variable it exits 2 |
| `closeout --stream S [--observed DIR]` | the close-out plan of a merged stream (ADR 0025, ADR 0026). Without `--observed` it prints an observe script: the flow runs it, and it writes the forge's PR/MR state (`gh` or `glab`, from the `mr-opened` URL's host, else the `forge` setting), the integration branch git names (`origin/HEAD`), the refs, the refs merged into it, its first-parent line, `git worktree list` and the stream worktree's `git status --porcelain --ignored --untracked-files=normal` into a fresh directory. With it, the forge's state decides, a stream with no PR/MR on a forge that answered is never merged, and with no forge evidence git ancestry is the fallback (a merged tip must sit off the first-parent line, so a branch cut from the integration branch with no commit of its own never reads as merged), and the user's word is never evidence. It acts only on the branch named exactly as the stream, and on the recorded PR/MR or one whose head is the stream; for any other stream it exits 4 and names `journal.py sweep`. A merged stream gets the steps in order, each `[run]`, `[ask]` or `[skip]`: capture, `flow-completed` with `reason`, `evidence` and `url`, the update of the integration branch, the config's **Close-out** steps, the guarded deletion of a squash-merged branch, the report, then the worktree removal and `branch -d` in one Bash call. `[ask]` steps wait for one question that shows each step's command beside its label, recorded as the user's `gate-decision` at gate `close-out`. The worktree removal is an `[ask]` step that lists the paths when the worktree holds an ignored or untracked path, or its files were not observed (git deletes ignored files with the worktree); with none, it runs with no question. No step takes `--force`, `-f` or `-D`. It writes nothing; it exits 4 when the PR/MR did not merge. Text for a model |
| `sweep [--observed DIR] [--apply]` | a disposition for each dormant stream, from one forge list query and git: `flow-completed` (merged), `flow-abandoned` (closed unmerged), `unknown` or keep, each with its source. It guesses nothing: it reads the branch and the PR/MR head of the stream's exact name, and the recorded PR/MR. With none of them the proposal is `unknown`: the user decides, and the line shows what the sweep looked for. `--apply`, after one confirmation, appends the terminal ones with `reason`, `evidence` and `url`, appends nothing for `unknown` or keep, and skips and names a stream that moved after the evidence was observed. It never touches git |
| `append --stream S --type T --data '{…}' [--actor R] [--expect N] [--batch]` | record one event — or a JSONL batch on stdin, so a phase boundary costs one call |
| `vocab [--shape T]` | the event vocabulary, and the canonical payload for one type |
| `assumptions <prd> [--risky [--cap N]] [--json]` | the tagged lines of a PRD's "Assumptions (executive)" list (ADR 0029): class, source, question, answer and end tag of each. Exit 2 names the first malformed line; the section holds only assumption lines (no prose, no code block), and its heading appears once. `--risky` gives the confirm batch: the lines with no end tag that are `domain`, `data` or `behaviour` with no source, or a blindspot or UI candidate, in file order, at most 4 (`--cap N` lowers it for the escalations that share the dialog), with the count over the cap. `--json` also says whether the section exists. Reads one file, never the journal |
| `reply --session ID --json` | the recorder hook's plan for a user's reply on stdin (ADR 0023): the go rows and witnesses to write, and the context line, which after a witness asks for a new go request and one confirming question. It writes nothing; the hook writes the rows with `append --batch` |
| `authorize --gate commit\|publish --branch B [--subagent] --json` | the command gate's answer for a branch: `pass` or `hold`, the reason (`authorized`, `no-go`, `witness-waits` when the user's reply was no exact go and a confirming question is due, `no-stream`, `not-live`) and the refusal text. A ready verdict is no go |
| `check --session ID [--json] [--record]` | what the flow still owes (the Stop hook's source): `findings`, the worklogs it `skipped` and why, and the `waivers` that would clear the findings. `--record` stamps the run as the last check: one `meta` value, no event |
| `stats [--since ISO] [--stream S] [--json]` | events by actor, gate decisions by mode × who raised them, deviations (and by `kind`), verifies per task, review rounds. A trace section says per stream whether the style skills were named at implement and at review (`named`, `none`, `missing`), and which signal source fed route-and-map, design and review (`graph`, `regex`, `none`, `missing`); its totals answer "how often did the graph feed design and review". `go` counts the go records by marker (`dialog`, `shell`, `question`, `prompt`) |
| `streams --open \| --dormant [--json]` | one line per open (or dormant) stream: lifecycle, phase, last event, idle days, the PR/MR URL, and the ownership mark when `CLAUDE_CODE_SESSION_ID` names another session than the last writer |
| `log`, `streams`, `init`, `doctor`, `export`, `import` | plumbing: the raw event log, the streams and their versions, schema, health, portability. `session` is retired: it reads and writes nothing, and a later release removes it. `doctor` also reports the settings file's `version` and its `stray_keys`, the keys that `settings.schema.json` does not name (the JSON key is still `sidecar`), and `settings`: each problem the settings resolver finds, each legacy line (in the project's, the nested repos' and the user's configs), each settings file inside a nested repo, and the grace date. None of them changes the exit code. It also reports `stop_gate`: the last recorded check (time, session, findings, skipped) and the last block, and `evidence`: the evidence root, the size, file count and oldest file of this project and of the whole root, what the next prune would delete, and the entries it refuses. It deletes nothing |

`append` is where the gates live. It validates the payload against its type's shape
(normalizing known aliases), records the `phase-entered` a phase-owning event implies — which
is why such an append can advance the stream's version by two, and why a chain of `--expect N`
must read each new version back from the output instead of assuming +1 — refuses a payload over
1 KB (prose belongs in the worklog — the event carries `refs`), records a `deviation` with
`kind: signals-missing` beside a `route-and-map` entry that carries no `signals` (ADR 0011),
and refuses `mr-opened` until the stream holds, after its last `task-done`, either a
`review-verdict` with `verdict=ready` that was not forced and is the newest verdict, or the
user's publish go (see **The user's go** below; ADR 0015, ADR 0023). `--force` does not waive this. A
`gate-decision`'s `decision` must be a string, and its optional `source` is `question`,
`prompt`, `dialog` or `shell`; `read` is refused, with `--force` too. A `review-verdict`'s optional
`criteria` map takes `met` or `unmet`, and its optional `dispositions` map takes `fixed`,
`rejected` or `deferred`. Its optional `security_review` object names the security review
it rests on: `kind` is `builtin`, `briefed` or `none`, `files` counts the files it read, and
`ref` names the commit the built-in command read. `append` refuses `builtin` or `briefed`
with no file read, and `builtin` with no `ref`, even with `--force`. A `review-disposition`
records one finding's state when it is decided: its `dispositions` map also takes `fixing`,
and its `round` must be a non-negative integer. Its optional `labels` map gives a finding key a short human name. Each name must be
a non-empty string. Every key of these maps must be the finding's location
`<path>:<line|?>`; `append` refuses another key, even with `--force`. `append` also refuses
a `ready` verdict while a finding is still `fixing` and the verdict's own map does not close
it. The message lists the open keys and the `review-disposition` row that closes them.
`--force` overrides it only with `--force-reason`. A `review-disposition` implies no phase.
`status --json` prints the same publish rule per stream as `publish`. `actor` is
`role[@label]` with role ∈ `orchestrator | worker | user | hook | watcher`; omit it and the append is attributed to the orchestrator plus
the appending session — `CLAUDE_CODE_SESSION_ID` from the shell's environment (a subagent's
shell carries its parent's). A shell with no such variable records no session, so its row
binds and counts for no session (ADR 0005). `user` and
`watcher` never take a session label. A `user` event records the appending session as
`data.recorded_by` instead, so `status --session`, `check` and `stats` count the session that
recorded the user's decision (ADR 0010). A stream ends with `flow-completed` and leaves the
status brief.

The project settings file `.claude/shipgate.json` declares its format `version`. This
shipgate knows version 2, the `x-version` of `settings.schema.json`. A settings file with a
higher integer version comes from a newer shipgate. The SessionStart hook then adds one
warning line to the session context, and `journal.py` prints the same line on stderr once
per run. Both keep working with the keys they know. `doctor` reports the raw `version` and
`stray_keys`: the keys that `settings.schema.json` does not name. `setup`'s update mode
stops on a newer version, and it drops stray keys when it writes the settings file again.

A project settings file whose `db` is JSON `null` declares that the project has no journal
(ADR 0028). The file still marks the project root, and every hook acts as in a project with
no settings file: no journal run, no gate, no output. A `journal.py` command that needs a
journal exits 1 and says why. Only `null` counts: a missing `db` keeps the default journal,
and so does a `db` of another type. So does a file that holds `NaN` or `Infinity`, because
shipgate-hud cannot read it. `signals.py` prints no warning for a newer version.

**The database is local, disposable state.** Gitignore it (`shipgate.db*`). The artifacts in
git or your wiki stay the portable record. On a new machine the project reads as
un-journaled unless you carry the journal over with `journal.py export` and `import`. Never
mount the database into a container: the journal runs in SQLite's WAL mode, which needs file
locks that a bind mount does not give, and the damage outlives the container (recover with
`PRAGMA journal_mode=DELETE` from the host). If a bot runs a shipgate phase, it runs it on
the host.

**The journal does not replace the ledger.** The ledger holds prose learnings and empties at
triage. The journal holds operational state and never empties. Triage writes learnings to
the knowledge stores; the journal records only that it happened, as `capture-done`. Do not
park a learning in the journal: it is machine-local and gitignored. `status` counts the
untriaged ledger entries, which is information only.

The three `enforce` settings turn the hooks' enforcement down: `stop_gate`, `auto_capture`
and `command_gate`, each `true` by default (see [Configuration](#configuration)). Run
`journal.py doctor` when anything looks stale.

Each phase skill names its stream before it works — the branch the work takes, per the
config's **Branching** pattern, opened with `flow-started` by whichever skill runs first when
the status brief lists no such stream (`workspace` then continues on it) — and appends its event in the
step that establishes the fact: the map emitted, the defect reproduced, the root cause
confirmed, the worklog written, the verdict stated. Not at the end of the turn, and never
skipped for want of a branch. The Stop hook enforces the build-side gates only (`task-done`,
`verify-run`); the phase events rely on those steps.

**The Stop gate.** The Stop hook runs `check --session ID --json --record` and blocks the stop while
`check` has findings. It has two rules (ADR 0020):

- A Build Plan box is ticked in a worklog this session wrote, and no stream that owns the
  worklog holds its `task-done`. A stream owns a worklog the way `position` shows one: its
  committing events name it (the worklog refs `position` reads, ADR 0009), or it has no
  worklog ref and its slug names the file. Here the slug is the whole last path segment of
  the stream name, issue id included, unlike `<slug>` in the **Branching** pattern. When it
  starts with an issue id, the slug without the id names a file too:
  `fix/1290-date-off-by-one` names `date-off-by-one.worklog.md`. A journal from before
  v0.11 also binds by the stream name `feature/<worklog name>`. The most exact binding
  wins: an event ref beats a name, `<slug>.worklog.md` beats a prefix match, the longer
  slug beats the shorter, and the full slug beats the slug without its issue id.
- The session recorded a forced `task-done` that no passing `verify-run` names. `append`
  refuses the plain one, so only `--force` reaches this rule.

A worklog that no stream owns is not judged, and neither is one that only a finished stream
owns. `check --json` lists each under `skipped` with its reason (`no-stream`, `finished`,
`not-found`), so a skip is visible. A finding that is not warranted takes a waiver: a
`deviation` with `kind: gate-waived`, `task_ids` and the reason in `note`, on the stream.
`check --json` prints one command per stream under `waivers`, and the block text carries it.
The command holds a placeholder note. `append` refuses an empty note or a `<...>` placeholder,
with `--force` too, until the reason replaces it.
`doctor` prints the last recorded check and the last block.

**UI tasks (ADR 0031).** With the `ui.globs` setting, a Build Plan task whose `file(s):`
paths match a glob is a UI task; a script decides, never the model. `design-committed`
refuses a task line that names neither a backticked path nor `file(s): none`, and names the
line. A `ui` value outside its set refuses both appends with exit 2 and names the key.
`task-done` of a UI task needs, for each width of `ui.widths`, a PNG registered with
`screens` after the stream's `design-committed`, or a `deviation` with
`kind: screens-waived`, `task_ids` and the reason in `note`. The refusal prints the register,
capture and waiver commands. A `screens-waived` clears no Stop gate finding. The files live
in the evidence root, outside every repository, and the journal deletes them itself: right
after a stream's `flow-completed` or `flow-abandoned` (that stream's directory), at each
`screens --file` or `--url` (this project's directories of finished or unknown streams), and
in both cases every file older than 30 days in the whole root; right after a `flow-started`
it removes only the files older than 30 days. There is no timer: the 30-day limit applies
at three moments, when a stream ends, when a stream starts (in any project) and when
screenshots are registered, and `doctor` shows what is left. A regular `.DS_Store` file (Finder
writes one when you open a directory) goes with its stream or project directory and never
counts as evidence. A delete follows no symbolic link, removes only the
evidence layout one file at a time, and keeps a stream directory whole when it holds an
entry it refuses. The automatic prunes name only the refusals inside what they target;
`screens --prune` and `doctor` name the rest. A failed delete is a
warning; it never changes an exit code or an event. Another Claude config directory or
another machine keeps its own evidence root.

**The user's go.** Only the user approves a commit or a publish (ADR 0023). A go is a
`gate-decision` at the gate `commit` or `publish` with `decision` equal to the gate,
`raised_by=user` and a `source` marker. A publish go also covers the commit, and one
publish go covers the push and the MR/PR creation. A go lasts until the stream's next
`task-done`. The flow records a `go-requested` event, then asks with `AskUserQuestion`
under the header `Commit` or `Publish`, the gate word as the first option.

- **The recorder hook** (UserPromptSubmit, and PostToolUse on `AskUserQuestion`) writes
  the go as yours when you answer with the gate word, select a stream in a multi-select
  question, or type `commit`, `publish`, `push`, `yes`, `y`, `ok`, `go`, `approve` or `all`
  (`source=question` or `source=prompt`). To any other reply it writes a `reply-witnessed`
  row, which holds no text, and tells the model to record a new go request and ask you one
  confirming question with the same header. Your click on the gate word is the go. The
  model records no go in any form: the journal refuses 0.28.0's `source=read`, with
  `--force` too, and a read go row that 0.28.0 wrote authorizes nothing. A prompt that
  starts with a tag, such as a subagent report, is no reply. `stats` counts the go records
  by marker.
- **shipgate-hud's publish dialog** ("Approve publishing") records `source=dialog`, and
  your own `!` command records `source=shell`, as before.
- **The command gate.** A **PreToolUse hook on Bash** holds a model's `git commit` until
  the stream of the branch holds a commit go, and `git push`, `git subtree push`,
  `gh pr create` and `glab mr create` until it holds a publish go. A ready verdict is no
  go. The hook asks `journal.py authorize` for the branch of the command's directory. It
  does nothing on a project with no project settings file or with one that declares no
  journal (`"db": null`), on a branch with no stream or a finished one, or when the
  `enforce.command_gate` setting is `false` (an unattended project). A
  dry run is held like any commit or push. A failure of git or the journal lets the
  command run.
- **The forgery net.** The same hook refuses a model's command that appends a go as yours:
  a `gate-decision` with any `source` marker, a commit or publish decision that
  names the user (`--actor user`, `user@…`, a JSONL `actor`, or `raised_by: user`), and
  any `reply-witnessed` row. It reads `--data`, `--batch` with a heredoc, a here-string or
  a pipe from `echo`, `printf` or `cat`, abbreviated options, any path to `journal.py`, and
  `sh -c` or `eval` strings. It refuses a payload or a `--type` it cannot read in full.
  It also refuses any `journal.py import` a model runs, because `import` writes rows with
  no check: when you move a journal between machines, run the import yourself with `!`.
  And it refuses a journal write whose line sets or clears `CLAUDE_CODE_SESSION_ID`, since
  a go request counts for the session that appends it, and a command that runs the
  recorder script `hooks/reply.py`, which only Claude Code runs on your reply. A command
  that names that path and runs Python through a path the hook cannot read is refused too;
  a model writes a file that names the script with the Write tool.
  Decisions at other gates pass.

This is a net against a flow that forges your go through its tools. It is no defence
against deliberate circumvention: the model has a shell and can write the SQLite file, run
a copy of the script or call its functions from Python. A user publish decision recorded
before 0.23.0 carries no marker and no longer authorizes; the gate asks again.

The hooks record which session wrote an artifact, and the journal decides it when it reads
them (ADR 0008).
- **PostToolUse on Write, Edit or NotebookEdit** claims the file for its session
  (`source: tool`).
- **PostToolUse on Bash** claims an artifact with `evidence: diff` when Claude Code's diff
  of the call lists it. It claims with `evidence: window` when the file's mtime falls inside
  the call's run time and the command writes to the file: a redirect into it, `tee`,
  `sed -i`, `perl -i`, or the destination of `mv`, `cp` or `install`. A command that only
  reads the file claims nothing.
- **FileChanged** fires in every open session, so it records only who observed the change
  (`observed_by`), never an author.

The best evidence wins: `tool`, then `diff`, then `window`. Two sessions with the same best
evidence give no author. The Stop gate and `stats` read authors only, so a session is never
blocked for a write it only saw.

Some writes have no author:
- a write by an external editor or a sync;
- a background Bash command;
- a Bash call that failed.

These are recorded as observed, and they gate no session.

**The context nudge (ADR 0022).** A flow that runs every phase in one session pays for the
whole context on every later turn. After a Bash call that appended `design-committed`, or
a `review-verdict` that is `not-ready`, the PostToolUse hook reads the session's context
size from the tail of its transcript: input, cache-creation and cache-read tokens of the
last main-thread assistant record. Past the threshold it prints one line, as a
`systemMessage` for you and as context for the model, that recommends a fresh session from
`journal.py handoff`. The threshold is the `handoff` setting (default `500k`, `off` turns
it off). The line is advice: it never blocks. Any other Bash
call pays two substring checks and does not import the nudge's code.

## Code signals

Per-file risk computed from the code and its history, on demand, by
`scripts/signals.py` — no index of its own, no cache. One `git log` pass gives each
file's **trajectory** over the window: commits, fix-rate (share of commits whose subject
matches the fix pattern), age, staleness, author count and top-author share. One import scan
gives **structure** for TS/JS, Python and Go: fan-in, fan-out and the blast radius
(transitive importers) of a file set; other languages report `structure: unknown`, never a
wrong number. Every number carries a label — `low | mid | high | top`, quartiles over *this*
repository (or `--scope`), so `top` means top here; paths and `--diff` only filter the rows.

| Command | Does |
| --- | --- |
| `hotspots [PATH…] [--diff REV] [--by-dir DEPTH] [--blast] [--top N]` | ranked per-file signals, optionally rolled up to modules and with the selection's blast radius |
| `blast FILE… [--diff REV] [--limit N]` | transitive importers of a file set — structure only, no log pass |
| `suspects FILE… [--top N]` | files near a symptom ranked by fix-rate × recency × proximity, for debugging |
| `graph ACTION ARGS…` | one codegraph query: `impact`, `callers`, `callees`, `affected`, `query`, `node` or `explore` (see **Code graph**) |

Common flags: `--repo`, `--scope`, `--window`, `--fix-pattern`, `--exclude`, `--json`; they
override the `code_signals` settings. `--graph auto|off|root` overrides the `code_graph`
setting. Both resolve per key (see [Configuration](#configuration)): `config.source` labels
each value `shipgate.json`, `user settings`, `shipgate.md` or `user shipgate.md` (a legacy
line), `flag` or `default`, and `config.files` and `config.inherit` say which config files
were read.
Consumers: `route-and-map` (a **Risk signals**
block in the impact map, essentials in the journal), `review` (a per-file risk table in the
brief, and `fileRisk` for the workflow's refuter ordering), `structured-debug` (a suspect
list cited as `[signals]` evidence), `implement` and `design` (prefer the proven precedent),
and optionally explorer and worker briefs. No git, a shallow clone, an empty history or no
adapter → one line saying why, exit 0, the phase runs as before. Output carries counts and
shares, never author names.

`hotspots --json` also prints `ranking`: the top 5 files in its own order, each with its
`fix`, `churn` and `fan_in` labels, and the structure `source` (ADR 0013). `design` copies
it into `design-committed` and `review` into `review-verdict`, so the journal shows which
ranking each phase used. The ranking leaves out release files, because every release
changes them: `**/CHANGELOG.md`, `**/.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`. The table and `files` keep them. A pattern is read as a
`code_signals.exclude` glob is, and a leading `**/` is optional. The
`code_signals.ranking_exclude` setting replaces these patterns with its globs. An empty list
(`[]`) turns them off. `config.ranking_exclude` names the patterns in force. A JSON call
that wanted the code graph and did not get it carries `graph_note`: one line that says why
and how to build an index. The table output keeps the advisory-once rule.

### Code graph

When the [codegraph](https://github.com/colbymchenry/codegraph) CLI is on `PATH`, the
structure half comes from its index instead of the regex scanner. Nothing needs to be
configured. The first call on a repository with no index builds one. A repository with more
than 10,000 tracked files is not indexed automatically; one advisory line names the command.
Before each query, shipgate syncs the index, unless a codegraph MCP server already watches
the repository. shipgate finds that server through the `socketPath` in
`.codegraph/daemon.pid`, because codegraph puts the socket in the temp directory when the
project path is long. The JSON says which source ran: `structure.source` is `graph` or
`regex`, and `structure.graph` carries the state and the reason.
`structure.graph.index_root` is relative to the repository: `.`, or `..` in root mode. A
codegraph call that fails gives the regex result, one reason line and exit 0. With codegraph
absent, every phase runs as before, plus one advisory line, once per project.

shipgate uses only a codegraph binary you installed. It skips a `PATH` entry that sits
inside the repository. It skips an entry inside an umbrella root only when the umbrella tracks the `codegraph` file in it, or holds it in its `.git`. It also skips an empty or relative `PATH` entry. After a skipped entry,
shipgate continues along `PATH` and uses the next acceptable install.

shipgate refuses an index that the repository itself supplies, with the reason
`graph-index-untrusted`. That happens in these cases:

- `.codegraph`, `.codegraph/codegraph.db` or `.codegraph/.gitignore` is a symlink, or git tracks it as one.
- `.codegraph` resolves outside the repository.
- git tracks a file under `.codegraph/` other than codegraph's own `.codegraph/.gitignore`.
- A directory spelled like `.codegraph` in another case, such as `.CodeGraph`, exists,
  tracked or not.

To use the code graph again, remove the symlink, untrack those files, or rename or remove
the `.CodeGraph`-style directory. The reason `graph-empty` means the index holds none of the
files this call asks about, after `--scope` and `--exclude`. Both reasons give the regex
result.

What it does not add: a higher eval score. In shipgate's own evals the two arms score the
same, because the model compensates for a weak regex number by writing its own resolver. The
gain is in the signals themselves (56 of 59 true importers from the graph, 2 of 59 from the
regex scanner on a 500-file workspace fixture), in the tests a diff reaches, and in the symbol
queries. The measurement is in `docs/research/2026-10-19-codegraph-vs-signals.md`.

What the code graph adds, per phase:

- `route-and-map`: the tests the diff reaches (`blast.tests`), and `graph impact` for each
  changed exported symbol.
- `review`: the tests the diff reaches, under the risk table. The verify gate runs them.
- `structured-debug`: `graph callers` and `graph callees` from the symptom symbol, cited as
  `[graph]` evidence. `suspects` still ranks by history.
- `implement`: `graph query` for the name and two synonyms, then `graph node` to read the
  best candidate with its callers.
- `design`: `graph callers` shows who already uses each precedent.
- Explorer and worker briefs: `graph explore`, `graph node` and `graph callers` before grep.
  An `explore` or `node` result counts as a Read of the files it prints.
- `workspace`: a new worktree gets a copy of the source checkout's index, and the next
  query syncs it. That took 1.2 s on this repository, less than a fresh build.

Put the shipgate flags before the action, because everything after it goes to codegraph:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" graph --repo <repo> --json impact <symbol> -f <path>
```

With `--json`, the answer is `{version, available, source, command, args, graph, result,
result_text, not_found}`. For `impact`, `callers`, `callees`, `affected` and `query`,
codegraph prints text, not JSON, when it does not know a symbol. That answer is still
`available: true`: `result` is null, the text is in `result_text`, and `not_found` is `true`.
For `node` and `explore`, the answer is always text, so the text is in `result`. Then
`not_found` says whether that text reports a symbol or code that was not found. When the graph is unavailable, the answer is `available: false` with a
reason, and no codegraph call runs.

Measured costs, one machine, one run each:

| Index | Files | Build | Size |
| --- | --- | --- | --- |
| this plugin repository | 104 | 5 s | 8 MB |
| one backend service | 1,469 | 7 s | 125 MB |
| an umbrella root of 28 child repos, nested clones excluded | — | 87 s | 680 MB |

A `sync` takes 0.7–2.4 s per child repository when the index is close to the working tree.
After many changes, for example a branch switch, a rebase or a pull, the sync catches up: 20
s on a repository of about 850 files, 36 s on one of about 1,900. So a sync has its own
timeout of 90 s. A query has 30 s, and a build 120 s. The sync limit stays under the Bash
tool's default of 120 s, which caps the whole `signals.py` call. A sync that times out
loses its work, and the reason is `graph-sync-timeout`: run `codegraph sync` once yourself,
and the next call syncs quickly. In an umbrella, each child repository owns its own
index, and every call names the child with `--repo`.

The only configuration is the `code_graph` setting: `auto`, `off` or `root`. `auto` is the
default. `off` always uses the regex scanner.
`root` uses an index at the umbrella root, which you build yourself with your own
`codegraph.json` and its exclude list for nested clones. shipgate never builds a root index.
**Root mode needs the codegraph MCP server running.** Without it, every call first syncs the
root, and that takes 55–66 s. In `root` mode, the
`graph` passthrough returns codegraph's own output, so its paths are relative to the umbrella
root, not to the child repository. The `--graph` flag overrides the setting for one call.

What shipgate writes, and only when codegraph is involved:

- `.codegraph/`, written by codegraph itself when shipgate builds the index.
- One `/.codegraph/` line in `.git/info/exclude`, only for an index shipgate built.
- Small files under `.git/shipgate/`: the build lock and two advisory markers, so each
  advisory shows once. With codegraph absent, only one advisory marker is written, once.

shipgate never installs codegraph, never writes MCP configuration and never edits
`CLAUDE.md`. Every codegraph call shipgate makes runs with telemetry off
(`CODEGRAPH_TELEMETRY=0`). No hook calls codegraph. ADR 0007 records the design.

## Install

shipgate is published through the **`pandora`** marketplace (manifest at the repo
root, `.claude-plugin/marketplace.json`):

```
/plugin marketplace add worm2fed/pandora
/plugin install shipgate@pandora
```

Then drive it with `/shipgate [description]`. Updating the marketplace (`/plugin marketplace
update pandora`) picks up new versions when the entry's `version` bumps.

## Dependencies & integrations

shipgate has **no hard dependencies** — install it and it works. Every integration below is
consulted only "if available" or when the project config names it, so a missing one never
breaks the flow; it just falls back. (Claude Code has no enforced plugin-dependency
mechanism, so this list is the source of truth for what to install to get the full
experience.)

**Required:** Claude Code. That's it — the bundled scripts (the journal, the code signals)
are Python 3 standard library only, and the signals skip themselves where there is no git.

**Optional integrations** (each enhances one part of the flow):

| Integration                                                            | Kind                  | Unlocks                                                                                                                                                            | Without it                                         |
| ---------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| a knowledge base MCP (named in config)                                    | MCP                   | team/product knowledge — recall & store in a wiki/vault                                                                                                               | recall falls back to repo docs (`CLAUDE.md`, ADRs) |
| forge CLI + tracker MCP (`gh` / `glab`; the `forge` setting, config)   | CLI/MCP               | `clarify` seeds the PRD from the issue; `review` opens the MR/PR and checks its acceptance criteria                                                                | capture the issue link manually; push by hand      |
| a log-query skill (named in config)                                    | skill                 | prod/QA log evidence in `structured-debug`                                                                                                                         | use `docker logs` / local sources                  |
| `chrome-devtools-mcp`                                                  | MCP/skill             | frontend/browser evidence in `structured-debug`                                                                                                                    | use other evidence sources                         |
| `/security-review`, `/simplify`                                        | Claude Code built-ins | deep security audit / standalone cleanup                                                                                                                           | ship with Claude Code already                      |
| the `Workflow` tool (Claude Code built-in; the `orchestration` setting) | Claude Code built-in  | Review and Explore fans run as bundled scripts: schema-typed findings, in-script dedupe, evidence-required refuters on review's top findings                       | the `Agent` fan, as before                         |
| an MR/PR-watcher skill (named in config)                               | skill                 | `review` registers blockers/follow-ups on the watch list; watcher events resume the flow at the phase they unlock                                                  | flow ends at "MR/PR opened"; resume manually       |
| `codegraph`                                                            | CLI on `PATH`         | symbol-level impact, callers, the tests a diff reaches, `explore` (see **Code graph**)                                                                              | the regex import graph; one advisory line, once    |

The plugin also expects the repo to carry **`CLAUDE.md`** files (root + nested where relevant) —
that's how `route-and-map` decides where code belongs. Repos without them still work; routing is
just less informed.

## Backlog

- **Narrow `code-explorer`'s shell to read-only git.** Since 0.14.6 the agent has plain `Bash`,
  limited to read-only git by its prompt only — a prompt-injected instruction in the repo it
  reads could ask for more, and the user's permission settings are then the only guard (the
  same holds for `code-reviewer`). If agent frontmatter `tools:` accepts permission patterns,
  grant `Bash(git show:*)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Bash(git grep:*)`,
  `Bash(git blame:*)` and `Bash(git ls-tree:*)` instead, and keep the contract test in
  `tests/test_workflow_scripts.py` in step. Raised by the security review of 0.14.7.
  Recorded 2026-10-08.

## Status

Release notes, newest first, live only in [CHANGELOG.md](CHANGELOG.md). The current version
is in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).
