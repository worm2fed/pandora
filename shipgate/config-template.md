# shipgate configuration — template

Copy this file into your project as **`.claude/shipgate.md`** and fill in what applies, or
run `/shipgate:setup`. This is how shipgate adapts to a project without forking the plugin.
The skills read the config at the start of a flow and treat it as overriding their built-in
defaults. It is prose the model reads, not parsed config. Write it the way you would brief a
new teammate.

Every section is **optional**. Delete what you don't need. An absent section falls back to
the next layer below, and in the end to the default noted per section. Keep entries short
and imperative. Each line here is an instruction the skills follow verbatim.

**Settings live in the settings files, not here.** A setting is a value from a fixed set,
such as `autonomy`, `writing_style` or `artifact_homes`. Settings live in
`.claude/shipgate.json` (the project settings file) and in
`$CLAUDE_CONFIG_DIR/shipgate.settings.json`, else `~/.claude/shipgate.settings.json` (the user
settings file). `journal.py config` prints each one with its source, and the README's
Configuration section lists them all. This file holds behaviour in words.

**How the config files layer.** This header and the README's Configuration section are the
two homes of the rule; every skill cites them. The layers, nearest first:

1. the repo's `.claude/shipgate.md` files, from the working directory up to the repo root;
2. the umbrella's `.claude/shipgate.md`, in an umbrella checkout;
3. the user file: `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set and not empty,
   else `~/.claude/shipgate.md`;
4. the built-in defaults noted per section.

The config is resolved per section. For each `##` section, the nearest file where the
section is present supplies the whole section. A section present in a nearer file replaces
the farther one whole. Sections never merge line by line. A section is present when its
heading exists and it holds at least one value that is not an angle-bracket placeholder. A
section with placeholders only, or with no bullets, is absent, and the next layer shows
through.

A nested config can take nothing from the umbrella. To do that, put the line `Inherit: none`
under its title, before the first section (bare or as a bullet, backticks optional, any
case). The user file and the built-in defaults still apply.

The user file uses the same section vocabulary as this template. It holds what is personal
and the same in every project. The sections marked "Usually personal" below belong there.

Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth
for *routing and code conventions*: where code belongs, build and test commands. The config
carries the *process tooling* in words: the knowledge stores, the tracker, branch naming,
which integrations to reach for. Don't duplicate CLAUDE.md content here.

Subagents don't read these files themselves. The dispatching skill pastes the relevant
excerpt into each brief, so write each section to be liftable on its own.

`setup` writes a lean file: a one-line title and `- Key: value` bullets only, with no
comments and no prose that explains the plugin. The comments in this template and the
README explain each section; a project's config does not repeat them.

---

## Knowledge base

<!-- Default when absent: knowledge capture to repo docs; no wiki. The PRD, ADR and
     worklog homes and the ledger path are settings (`artifact_homes`, `ledger`). -->

- Stores: <one line per store: name — purpose — transport (MCP server name, or in-repo
  path) — who may write to it>
- Page conventions: <frontmatter shape, filename rules, link style, where templates live>
- Store-specific skills: <any project/vault skills to prefer for reading/writing the store>
- Promotion targets: <where triage sends ledger entries, by entry type: destinations may be
  stores above, specific wiki pages, a repo CLAUDE.md, an ADR home, or a skill's SKILL.md
  (e.g. a personal code-style skill). List project targets only. The built-in promotion
  defaults in the `knowledge-base` skill cover the rest: personal workflow preferences go to
  the harness's built-in memory, everything else is dropped, and promoted and dropped
  entries are removed. The promotion target for preferences is usually personal: it belongs
  in the user file>

## Forge & tracker

<!-- Default when absent: issue context read via whatever CLI/MCP is available. The forge
     itself is the `forge` setting: `github` (gh, PRs) or `gitlab` (glab, MRs); unset, the
     host of the PR/MR URL or of the git remote decides. -->

- Issue tracker: <where issues live (may be a different repo/project than the code) and
  the MCP/CLI to read them with>
- MR/PR template: <where the canonical template lives + the exact command to fetch it>
- Issue-link form: <how MR/PR bodies and commits must reference issues, e.g. cross-repo
  form `group/project#NNNN`>
- Title/body rules: <conventions the template itself doesn't capture>
- Acceptance criteria source: <where the ACs the review phase must check live>
- Bug provenance: <where root-cause comments go and any format they must follow. Default
  when absent: a comment on the bug's tracker issue via the forge CLI, citing the
  introducing commit — see `structured-debug`>

## MR watcher

<!-- Default when absent: no watcher — the flow ends at "MR/PR opened" and resumes only when
     the user asks. -->

- Watcher: <project skill that watches open MRs/PRs and keeps a watch list, or delete
  this section>
- Register a blocker/follow-up: <the exact command the watcher exposes for adding an
  external MR/PR to its watch list>
- If declared, two skills honor it:
  - **review**, after opening the MR/PR: if this work is now blocked on someone else's
    request, or has follow-up work gated on this one merging, register it with the
    watcher's watch list. The note must name the held work AND its next action (e.g.
    "unblocks #1234 — rebase + open the request"), so the unblock event arrives as an
    instruction, not trivia. Say what you're registering as you do it.
  - **feature**, resume detection: a watcher event naming an issue is a valid resume
    trigger. Map it: reviewer comments → the review-feedback cycle (defined in the
    `review` skill); own MR/PR merged → the close-out (`journal.py closeout`), whose first
    step is the residual ledger triage (then the next child issue, if any); a watched one
    merged → resume the held work per its note; conflicts / failed CI → fix before review
    continues.
- The watcher is strictly read-only. It suggests; the user triggers every resume.
- Optional, on a journaled project: a watcher may append what it observes to
  `watch/<project>!<iid>` streams via the plugin's `journal.py` (`baseline`,
  `pipeline-flip`, `comments-added`, `merge-status`, `conflicts`, `approved`, `merged`,
  `closed`). Watchers typically keep a single overwritten snapshot file, so a missed or
  crashed tick loses the intervening history; journalling makes the snapshot a cache and
  the history reconstructable. Suggestion, not a requirement — a watcher that doesn't do
  this still works exactly as described above.

## Close-out

<!-- Default when absent: the close-out runs its built-in steps only. `journal.py closeout`
     lists these steps after the update of the integration branch and before the report.
     Each step here waits for the user's one answer: a project's steps are arbitrary
     commands, so none runs with no question. -->

- <Label>: <the action, e.g. tag the version-bump commit>

## Branching

<!-- Default when absent: `<type>/<issue-id>-<slug>`, type ∈ feat | fix | chore, branched
     off the detected integration branch. -->

- Pattern: <e.g. `<type>/<issue-id>-<slug>`, prefixes, forbidden elements>
- Examples: <two or three real-shaped but neutral examples>

## Repo layout

<!-- Only needed for umbrella / multi-repo checkouts. Default: the working directory is
     the repo. -->

- <e.g. "this repo is an umbrella — every `source/<service>` is its own git repo; all
  feature branches happen inside the service repos, never on the umbrella itself">

## Style

<!-- Default when absent: match surrounding code; no extra skill invoked. -->

- Style skill(s): <project skill to invoke BEFORE writing or reviewing code — the
  implement/review phases invoke it, every worker brief carries a Style line naming it, the
  review adds a canon lens that loads it, and the journal records it as `style` on the
  implement and review phase entries>

## Security-sensitive areas

<!-- Default when absent: auth, secrets, payments — the built-in judgment. -->

- <domains in this codebase that must trigger the full `/security-review` rather than the
  in-flow security lens, e.g. billing, PII exports>

## Debug evidence sources

<!-- Default when absent: local logs, failing tests, debugger; browser via
     chrome-devtools if present. -->

- Prod/QA logs: <skill or tool to query them>
- CI logs: <integration to pull job logs>
- Local: <how local services log, e.g. compose service names>

## Epic workflow

<!-- Default when absent: epics are driven issue-by-issue with a stop (merge + go-ahead)
     between issues; decomposition is manual; design-ahead depth 1-2. -->

- Decomposition: <command/skill that creates the epic + child issues>
- Ordering: <how dependencies between child issues are expressed, e.g. `blocked_by`>
- Delivery: <e.g. one issue = one branch = one MR/PR, reviewed independently>
- Design-ahead depth: <how many upcoming issues the orchestrator specs while workers
  implement the current one. Default when absent: 1-2 — deeper queues go stale faster
  when review feedback shifts the ground>

## Code tooling

<!-- Usually personal: belongs in the user file. -->

<!-- Default when absent: library docs from a context7-style MCP (resolve a library id,
     then query its docs) when the session has one, else training knowledge / WebFetch; no
     LSP preference (grep/read). The code graph is the `code_graph` setting. The Library
     docs line is the personal one. A project file that declares this section replaces the
     user file's section whole, so repeat the Library docs line there when you add a
     project line. -->

- Library docs: <the docs tool/MCP to consult for a dependency's current API before
  hand-rolling around it or answering from memory. Leave it out to use a context7-style
  MCP when the session has one; this line overrides that default. Used by implement's
  reuse step and structured-debug.>
- Code navigation: <the LSP tool, if one is configured for the language — prefer
  goToDefinition / findReferences / hover over grep-and-read for symbol work in typed
  code; note any workspace quirks (root, server version) here>

## Worker guardrails

<!-- Default when absent: no project-specific guardrails. Every worker brief still carries
     the built-in worker discipline block in the `model-tiers` skill, word for word: branch
     check, no commit or staging, the git index, no --no-verify, no repo-wide formatter,
     stop and report, comments, evidence in the report. This section adds the rules only
     this repo needs. Never repeat a built-in rule here. -->

Hard rules for anyone editing this repo, written to be pasted **verbatim** into every worker
brief — `model-tiers` requires them word-for-word, because a summarized guardrail is a
broken one. One imperative line per rule, no rationale, no grouping:

- <e.g. "Build with `<dev build script>`; the release build script belongs to CI, never to
  a worker">
- <e.g. "Never edit `<generated dir>/` by hand; `<generate command>` writes it">
- <e.g. "Refresh `<schema dump file>` only with `<one command>`; never edit it by hand">
- <e.g. "Recreate the test database with `<one script>`; never migrate it in place">

## Thinking lenses

<!-- Default when absent: no lens skills are invoked — the phase skills apply each
     lens inline (each names it where it's used, with the condition it applies under).
     This section overrides that with a lens *skill* to invoke, e.g. one from
     cc-thinking-skills (https://github.com/tjboudreaux/cc-thinking-skills). A large
     lens plugin costs skill-listing space in every session — descriptions get truncated
     past the listing's budget and stop triggering — so install and map only what you need. -->

- <phase → lens skill(s) to actually invoke at that phase, e.g.
  `clarify → thinking-jobs-to-be-done; design → thinking-pre-mortem`.
  Only the orchestrator can invoke skills — subagents apply lens ideas inline regardless.>

## Autonomy

<!-- Usually personal: belongs in the user file. -->

<!-- Default when absent: no extra escalations. The mode is the `autonomy` setting: `ask`
     (the default) sends every gate question to the user; `executive` lets the orchestrator
     answer routine gate questions itself, record them and escalate the rest, by the
     executive contract in the `feature` skill. The contract is the plugin's, so this
     section never restates it. Extra escalations add cases to it. -->

- Extra escalations: <decisions that must always go to the user, if any>
