---
name: knowledge-base
description: Use to pull prior context before routing/design/debugging, to jot a mid-flow learning, or to record something a future session would re-derive. Triggers: "what do we know about X", "capture this for the team", "log this to the knowledge base", "triage the ledger", end of a feature. The durable knowledge layer, routed by type — recall before non-trivial work, append quick learnings to the project ledger as they happen, and capture/promote after, sending each learning to the store the project config declares for its type (repo docs by default). Prefer this over Claude's built-in session memory for any feature, domain, or convention learning.
---

# Knowledge base

The durable knowledge layer. It has two jobs. **Recall** before you work, so you don't
re-derive what's already known. **Capture** after, so the next session inherits it. The key
judgment is *which store* a piece of knowledge belongs in. The wrong home pollutes a store
that has a different job.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Not Claude's built-in session memory.** The harness has its own personal/session memory
> feature. This skill is different. It takes precedence for anything a *teammate or future
> session* would reuse: domain rules, conventions, decisions. Route those through here, to the
> store the config maps for their type. Do **not** route them into the personal session-memory
> store, or team knowledge never accumulates where the team can find it. The `feature`
> orchestrator invokes this skill explicitly at the Capture phase. Don't rely on an ambient "I
> should remember this": that thought summons the built-in memory instead.

## Route by knowledge type — the core decision

The **project config's Knowledge base section declares the stores**. It declares each store
as purpose → transport (MCP server name or in-repo path) → paths → who may write. Match the
knowledge type in front of you to the store whose *purpose* fits it. Read that section first.
For a configured project, that section is authoritative, not this table.

When no config exists, use these defaults. Everything durable lives in the target repo. An
optional vault takes anything that genuinely transcends the project:

| Knowledge | Home | Notes |
|-----------|------|-------|
| **Product / domain insight** — a business rule, why a feature exists, what a customer needs, a domain definition | Target repo — **`docs/adr/`** for a decision that turned on it, **`docs/prd/`** for PRDs, longer notes under `docs/` | The product *why*, kept next to the code it shapes. |
| **Engineering knowledge** — decisions, PRDs, gotchas, reusable fixes, root causes, conventions | Target repo — decisions to **`docs/adr/`** (numbered `NNNN-<title>.md`), PRDs and worklogs to **`docs/prd/`** (`<name>.md` + `<name>.worklog.md`), operating rules Claude must read in-context to **`CLAUDE.md`**, longer notes under `docs/` | The HOW-WE-RUN layer. |

An Obsidian-type vault MCP may be available (e.g. `obsidian-vault`). If so, it can also take
*general, transferable* findings or short *project-status* notes. Examples: a technique useful
beyond this project, or where the project stands. Never put project-dev specifics in a vault:
bug details, code paths, repo conventions. Those belong in the repo.

Quick test: anything a contributor to *this repo* needs goes to the repo, or to the store the
config maps. Something *you* would want while working on a different project entirely goes to
the vault. When in doubt, use the repo. A repo's own `CLAUDE.md` is for operating instructions
Claude must read in-context, such as build/test commands and routing rules. It is **not** a
knowledge-capture target. Don't dump gotchas or history there.

## Transport

Write repo knowledge as plain files (Write/Edit). Write vault or MCP-backed stores through
their MCP, typically `search_notes`, `read_note`, `write_note`, `patch_note`. Follow whatever
page conventions the config declares: frontmatter shape, filename rules, link style, where
templates live. Prefer patching an existing note over creating a new one. Create a note only
when it is clearly warranted. The config MAY also declare store-specific skills to prefer for
reading or writing a store. Use them when it does.

If a target store isn't reachable, say so and flag it. Do not silently drop the knowledge.
Fall back to the repo so nothing is lost.

## Recall (before work)

Pull the right context from the right store. Match the question to the store's purpose:

- **Domain / product context** — *why* this feature exists, the business rules, the customer
  need. Look in the store the config maps for product/domain insight. By default that is the
  repo's `docs/`, `docs/adr/`, `docs/prd/`, plus a vault search if one is available.
- **Engineering / operational context** — *how* this area was decided, prior ADRs, known
  gotchas, PRDs. Look in the repo's `docs/adr/`, `docs/prd/`, `CLAUDE.md`, `docs/`, or in the
  config's mapped store.

Cite what you recall by file path (repo) or as "[wiki] …" (a vault/MCP store). The citation
shows that it came from the knowledge base, not from fresh derivation. Report an empty recall
as empty: "nothing recorded on X". Then proceed, and consider capturing what you learn. Never
fill the gap with a plausible-sounding answer (**circle of competence**). What you can cite
from a store is recall. What you cannot cite is a guess, and the user hears which one it is.
Fetch a fact that is cheap to fetch (a file, a command); do not abstain on it.

## Ledger — the staging inbox

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
ledger lines; absent, a placeholder, or `plain`, write them as before.

Learnings evaporate between "noticed mid-implement" and "curated capture at the end of the
flow". By Capture time the context is deep, and half the small insights are gone. The
**ledger** is the fix. It is one project-wide, append-cheap staging file. Its path is
config-declared; the default is `docs/ledger.md` in the repo. Any phase writes to it the moment
something worth keeping surfaces.

- **Appending is free of ceremony.** Write one dated line per entry. A rough type tag is
  optional (`style:`, `gotcha:`, `decision:`, `pref:`), and so is a one-line context. There is
  **no quality gate at append time**. The capture gate below applies at *promotion*, not here.
  If you hesitated whether it's worth an entry, it was.
- **The trigger is a moment, not a phase end.** The phase skills name their triggers: the root
  cause just confirmed (`structured-debug`, before the fix plan), a task just ticked
  (`implement`), a finding class that recurred (`review`). Each skill carries the append
  inline, so it costs one tool call and no skill load:

  ```bash
  printf -- '- %s — gotcha: <what silently bit, where, the one-line rule>\n' "$(date +%F)" >> docs/ledger.md
  ```

  Outside a phase skill the same rule holds: hit a trap, write the line, keep going. The line
  is the deliverable. It is not a `CLAUDE.md` edit, not an ADR, not built-in memory, and not a
  pause to explain the ledger. The ledger exists when the config declares it or when
  `docs/ledger.md` is already there. A project gets one at setup or at its first Capture. It
  never gets one as a side effect of a debugging, build or review step. A new file the user did
  not ask for reads as a change applied, not a learning kept.
- **Promotion (triage) is where curation happens.** Walk the entries. Route each one through
  the type-routing above to its durable home, or **drop it**. The homes include any
  **promotion targets the config declares**. These may be unconventional stores: a style
  skill's SKILL.md, specific wiki pages, a repo `CLAUDE.md`, an ADR, or the harness's built-in
  personal memory. Personal workflow preferences are the one place routing *may* target the
  built-in memory. Most raw entries don't survive triage, and that's healthy. Apply the capture
  quality gate to each promotion.
- **Promoted and dropped entries are removed from the ledger.** It is an inbox, not a landfill.
  A ledger that only grows has failed.
- **Triage triggers:** the flow's Capture phase; the user asking ("triage the ledger"). Also
  nudge proactively when you notice ~15+ unpromoted entries.

## Capture (after work) — pass the quality gate first

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
the pages and lines capture writes; absent, a placeholder, or `plain`, write them as before.

Storing junk is worse than storing nothing, because it pollutes recall. Before you write
anything, ALL of these must hold:

1. **Reusable** — a future session is genuinely likely to need it.
2. **Verified** — backed by code, a test, command output, an ADR, or an explicit user
   statement. Not speculation.
3. **Non-obvious** — not trivially visible in the nearest file. (Exception: capture it anyway
   if it's a mistake that keeps getting repeated.)
4. **Not already covered** — you checked the target store, and it doesn't already say this. If
   an entry exists but is stale, **update** it instead of duplicating it.
5. **Right home + narrowly scoped** — routed to the store whose purpose fits. Filed under the
   right service/domain, not a catch-all.
6. **Safe** — no secrets, credentials, customer PII, personal data, or raw logs. (Customer
   *use cases* and business rules are fine to capture; customer *data* is not.)

### Worth capturing
Business/domain rules and customer use cases. Engineering decisions (→ `docs/adr/`). Service
conventions, setup gotchas, reusable fixes, root causes. Non-obvious constraints like "schema
lives in one service; refresh dumps after migrations". PRDs (→ `docs/prd/`). Genuinely general
techniques or short project-status notes (→ a vault, if one is configured).

### Not worth capturing
Task progress, transcripts, generic programming facts, raw errors without a diagnosis,
anything the user didn't intend to persist, anything the code already makes obvious.

Shape each entry to be useful out of context. State what it applies to, the guidance, the
evidence (file/command/ADR), and when it does *not* apply. In a store that supports links,
connect related notes per that store's conventions, so the knowledge base stays connected.

## Record the capture (journaled projects)

On a project whose config declares a **Journal**, close the Capture phase. Do it once the
ledger is walked and every entry is promoted or dropped. Append the event then, not at some
later tidy-up:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type capture-done \
  --data '{"promoted":["docs/adr/0007-async-export.md","CLAUDE.md"],
           "dropped":["ledger line about the flaky export fixture"]}'
```

Both keys are lists, even when empty (`[]`). `promoted` records **destinations**: the paths or
store names written to. It never records the knowledge itself, which now lives in those
stores. `dropped` records one short line per entry that was let go. A later session can then
tell what was judged not worth keeping.

**Close the stream when nothing is owed on it.** Nothing is owed when there is no open MR/PR,
no residual triage and no next child issue. Then append `flow-completed` {reason} straight
after `capture-done`. Make it the second line of the same `append --batch` (stdin form: see
`verify`). That event lets a finished stream leave every later session's status brief. A
stream nobody closes is read as live work forever.

A missing or unreadable database is an infrastructure failure, not a reason to skip the
append. Surface it loudly. Continue un-journaled only with the user's acknowledgement.
