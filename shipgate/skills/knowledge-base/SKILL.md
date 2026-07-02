---
name: knowledge-base
description: Durable knowledge layer, routed by type — recall before non-trivial work and capture learnings after, keeping engineering knowledge (decisions, specs, gotchas, conventions) in the target repo and sending only general findings or project status to the personal vault. Use to pull prior context before routing/design/debugging, or to record something a future session would re-derive. Prefer this over Claude's built-in session memory for any feature, domain, or convention learning. Triggers — "what do we know about X", "capture this", "log this to the knowledge base", end of a feature.
---

# Knowledge base

The durable knowledge layer. Two jobs: **recall** before you work (so you don't re-derive what's
already known) and **capture** after (so the next session inherits it). The key judgment is *where*
a piece of knowledge belongs — the wrong home pollutes a store that has a different job.

> **Not Claude's built-in session memory.** The harness has its own personal/session memory
> feature; this is different and takes precedence for anything a *future session* would reuse —
> domain rules, conventions, decisions. Route those through here (per the table below), **not**
> into the personal session-memory store, or project knowledge never accumulates where it can be
> found. The `feature` orchestrator invokes this skill explicitly at the Capture phase — don't
> rely on ambient "I should remember this," which summons the built-in instead.

## Route by knowledge type — the core decision

The **target repo is the primary home** for everything engineering. The personal vault (Obsidian,
exposed via the `obsidian-vault` MCP) is a life wiki, not a dev log — it gets only *general,
transferable findings* or *project-status updates*, sparingly.

| Knowledge | Home | Notes |
|-----------|------|-------|
| **Engineering decisions** — why an approach was chosen, trade-offs | **`docs/adr/`** in the target repo (numbered `NNNN-<title>.md`) | The durable *how we decided* record. |
| **Feature specs / worklogs** | **`docs/prd/`** in the target repo (`<name>.md` + `<name>.worklog.md`) | Written by the clarify/design phases. |
| **Conventions, gotchas, root causes, non-obvious constraints** | Target repo — **`CLAUDE.md`** for operating rules Claude must read in-context; `docs/` for longer notes | Keeps the knowledge next to the code it describes. |
| **General / transferable findings** — a technique, pattern, or insight useful beyond this project | Personal vault, `wiki/learning/<Topic>.md` | Only if it genuinely transcends the project. |
| **Project status** — where a project stands, major milestones, direction | Personal vault, `wiki/projects/<Project>.md` | A short status note, not a dev log. |

Quick test: anything a contributor to *this repo* needs → the repo. Something *you* would want to
know while working on a different project entirely → the vault. When in doubt, the repo. Never put
project-dev specifics (bug details, code paths, repo conventions) in the vault.

## Transport

Repo knowledge is written as plain files (Write/Edit). Vault writes go through the
**`obsidian-vault` MCP** (`search_notes`, `read_note`, `write_note`, `patch_note`) and must follow
the vault's own `CLAUDE.md` conventions — flat Title Case notes (e.g. `wiki/projects/My App.md`,
`wiki/learning/Domain-Driven Design.md`). Prefer patching an existing note over creating a new
one; create only when clearly warranted.

If the vault MCP isn't reachable, fall back to the repo and say so rather than silently dropping
the knowledge.

## Recall (before work)

Pull the right context from the right store:

- **Engineering context** — prior ADRs, feature specs, known gotchas → read the target repo's
  `docs/adr/`, `docs/prd/`, `CLAUDE.md`, `docs/`.
- **Project / domain context** — where the project stands, general background → if the
  `obsidian-vault` MCP is available, `search_notes` for the project or topic; skip silently if not.

Cite what you recall as "[wiki] …" (vault) or by file path (repo) so it's clear it came from the
knowledge base, not fresh derivation. An empty search is fine — proceed, and consider capturing
what you learn.

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
5. **Right home + narrowly scoped** — routed by the table above, filed under the right
   project/topic, not a catch-all.
6. **Safe** — no secrets, credentials, PII, personal data, or raw logs.

### Worth capturing
Engineering decisions (→ `docs/adr/`); feature specs (→ `docs/prd/`); project conventions, setup
gotchas, reusable fixes, root causes, non-obvious constraints (→ `CLAUDE.md` or `docs/`);
genuinely general techniques or insights (→ vault `wiki/learning/`); project-status milestones
(→ vault `wiki/projects/`).

### Not worth capturing
Task progress, transcripts, generic programming facts, raw errors without a diagnosis,
anything the user didn't intend to persist, anything the code already makes obvious —
and in the vault specifically: any project-dev detail.

Shape each entry to be useful out of context: what it applies to, the guidance, the evidence
(file/command/ADR), and when it does *not* apply. In the vault, link related notes per the vault's
own conventions so it stays connected.
