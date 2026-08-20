---
name: knowledge-base
description: The durable knowledge layer, routed by type — recall before non-trivial work, append quick learnings to the project ledger as they happen, and capture/promote after, sending each finding to the store the project config declares for its type (repo docs by default). Use to pull prior context before routing/design/debugging, to jot a mid-flow learning, or to record something a future session would re-derive. Prefer this over Claude's built-in session memory for any feature, domain, or convention learning. Triggers: "what do we know about X", "capture this for the team", "log this to the knowledge base", "triage the ledger", end of a feature.
---

# Knowledge base

The durable knowledge layer. Two jobs: **recall** before you work (so you don't re-derive what's
already known) and **capture** after (so the next session inherits it). The key judgment is *which
store* a piece of knowledge belongs in — the wrong home pollutes a store that has a different job.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Not Claude's built-in session memory.** The harness has its own personal/session memory
> feature; this is different and takes precedence for anything a *teammate or future session*
> would reuse — domain rules, conventions, decisions. Route those through here (to the store the
> config maps for their type), **not** into the personal session-memory store, or team knowledge
> never accumulates where the team can find it. The `feature` orchestrator invokes this skill
> explicitly at the Capture phase — don't rely on ambient "I should remember this," which summons
> the built-in instead.

## Route by knowledge type — the core decision

The **project config's Knowledge base section declares the stores** — each as purpose → transport
(MCP server name or in-repo path) → paths → who may write. Route by matching the knowledge type in
front of you to the store whose *purpose* fits it. Read that section first; it, not this table, is
authoritative for a configured project.

When no config exists, use these defaults — everything durable lives in the target repo, with an
optional vault for anything that genuinely transcends the project:

| Knowledge | Home | Notes |
|-----------|------|-------|
| **Product / domain insight** — a business rule, why a feature exists, what a customer needs, a domain definition | Target repo — **`docs/adr/`** for a decision that turned on it, **`docs/prd/`** for feature specs, longer notes under `docs/` | The product *why*, kept next to the code it shapes. |
| **Engineering knowledge** — decisions, feature specs, gotchas, reusable fixes, root causes, conventions | Target repo — decisions to **`docs/adr/`** (numbered `NNNN-<title>.md`), feature specs to **`docs/prd/`** (`<name>.md` + `<name>.worklog.md`), operating rules Claude must read in-context to **`CLAUDE.md`**, longer notes under `docs/` | The HOW-WE-RUN layer. |

If an Obsidian-type vault MCP is available (e.g. `obsidian-vault`), it can also take *general,
transferable* findings or short *project-status* notes — a technique useful beyond this project, or
where the project stands. Never put project-dev specifics (bug details, code paths, repo
conventions) in a vault; those belong in the repo.

Quick test: anything a contributor to *this repo* needs → the repo (or the store the config maps).
Something *you* would want while working on a different project entirely → the vault. When in
doubt, the repo. A repo's own `CLAUDE.md` is for operating instructions Claude must read in-context
(build/test commands, routing rules); it is **not** a knowledge-capture target — don't dump gotchas
or history there.

## Transport

Repo knowledge is written as plain files (Write/Edit). Vault or MCP-backed stores are written
through their MCP (typically `search_notes`, `read_note`, `write_note`, `patch_note`), following
whatever page conventions the config declares (frontmatter shape, filename rules, link style, where
templates live). Prefer patching an existing note over creating a new one; create only when clearly
warranted. The config MAY also declare store-specific skills to prefer for reading or writing a
store — use them when it does.

If a target store isn't reachable, say so and flag it rather than silently dropping the knowledge —
fall back to the repo so nothing is lost.

## Recall (before work)

Pull the right context from the right store — match the question to the store's purpose:

- **Domain / product context** — *why* this feature exists, the business rules, the customer
  need → the store the config maps for product/domain insight; by default the repo's `docs/`,
  `docs/adr/`, `docs/prd/`, plus a vault search if one is available.
- **Engineering / operational context** — *how* this area was decided, prior ADRs, known
  gotchas, feature specs → the repo's `docs/adr/`, `docs/prd/`, `CLAUDE.md`, `docs/` (or the
  config's mapped store).

Cite what you recall by file path (repo) or as "[wiki] …" (a vault/MCP store) so it's clear it came
from the knowledge base, not fresh derivation. An empty search is fine — proceed, and consider
capturing what you learn.

## Ledger — the staging inbox

Learnings evaporate between "noticed mid-implement" and "curated capture at the end of the
flow" — by Capture time the context is deep and half the small insights are gone. The
**ledger** is the fix: one project-wide, append-cheap staging file (config-declared path;
default `docs/ledger.md` in the repo) that any phase writes to the moment something worth
keeping surfaces.

- **Appending is free of ceremony.** One dated line per entry, optional rough type tag
  (`style:`, `gotcha:`, `decision:`, `pref:`), optional one-line context. **No quality gate
  at append time** — the capture gate below applies at *promotion*, not here. If you
  hesitated whether it's worth an entry, it was.
- **Promotion (triage) is where curation happens.** Walk the entries; route each through the
  type-routing above to its durable home — including any **promotion targets the config
  declares**, which may be unconventional stores: a style skill's SKILL.md, specific wiki
  pages, a repo `CLAUDE.md`, an ADR, or the harness's built-in personal memory (the one
  place routing *may* target it: personal workflow preferences) — or **drop it**; most raw
  entries don't survive triage, and that's healthy. Apply the capture quality gate to each
  promotion.
- **Promoted and dropped entries are removed from the ledger.** It is an inbox, not a
  landfill — a ledger that only grows has failed.
- **Triage triggers:** the flow's Capture phase; the user asking ("triage the ledger");
  and proactively nudge when you notice ~15+ unpromoted entries.

## Capture (after work) — pass the quality gate first

Storing junk is worse than storing nothing; it pollutes recall. Before you write anything,
ALL of these must hold:

1. **Reusable** — a future session is genuinely likely to need it.
2. **Verified** — backed by code, a test, command output, an ADR, or an explicit user
   statement. Not speculation.
3. **Non-obvious** — not trivially visible in the nearest file. (Exception: capture it anyway
   if it's a mistake that keeps getting repeated.)
4. **Not already covered** — you checked the target store and it doesn't already say this. If
   an entry exists but is stale, **update** it instead of duplicating.
5. **Right home + narrowly scoped** — routed to the store whose purpose fits, filed under the
   right service/domain, not a catch-all.
6. **Safe** — no secrets, credentials, customer PII, personal data, or raw logs. (Customer
   *use cases* and business rules are fine to capture; customer *data* is not.)

### Worth capturing
Business/domain rules and customer use cases; engineering decisions (→ `docs/adr/`); service
conventions, setup gotchas, reusable fixes, root causes, non-obvious constraints like "schema lives
in one service; refresh dumps after migrations"; feature specs (→ `docs/prd/`); genuinely general
techniques or short project-status notes (→ a vault, if one is configured).

### Not worth capturing
Task progress, transcripts, generic programming facts, raw errors without a diagnosis,
anything the user didn't intend to persist, anything the code already makes obvious.

Shape each entry to be useful out of context: what it applies to, the guidance, the evidence
(file/command/ADR), and when it does *not* apply. In a store that supports links, connect related
notes per that store's conventions so the knowledge base stays connected.

## Record the capture (journaled projects)

On a project whose config declares a **Journal**, close the Capture phase once the ledger is
walked and every entry is promoted or dropped — append it then, not at some later tidy-up:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream feature/<slug> --type capture-done \
  --data '{"promoted":["docs/adr/0007-async-export.md","CLAUDE.md"],"dropped":4}'
```

Promotions are recorded as **destinations** — the paths or store names written to, never the
knowledge itself, which now lives in those stores. A missing or unreadable database is an
infrastructure failure, not a reason to skip the append: surface it loudly and continue in legacy
mode only with the user's acknowledgement.
