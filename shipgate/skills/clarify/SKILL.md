---
name: clarify
description: The Clarify gate before design — drive ambiguity out of a feature and capture it as a PRD. Runs a coverage scan, asks a few prioritized questions (each leading with a recommended answer), and writes docs/prd/<name>.md with numbered requirements (FR-###) and success criteria (SC-###). Use after exploration and before design; don't skip it.
---

# Clarify

This is the cheapest place in the whole flow to prevent wasted work. Designing and building
against a wrong assumption costs hours; asking a question costs a sentence. The gate runs
*after* exploration (so your questions are informed by what the code actually does) and
*before* design (so the expensive work starts from solid ground).

**The gate always runs, and design never starts with open clarifications.** What varies is
*who answers it*: in the default `ask` mode, the user does (if they're in a hurry, the move
is to answer fast, not to skip — surface the questions with recommendations so they can
one-tap them). When the config's **Autonomy** section declares `executive`, you answer your
own questions — see the Executive mode section below.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** A status brief headed "shipgate
> flow journal", a **Journal** section in the config or a `.claude/shipgate.json` sidecar means
> this gate is owed to a stream, and the stream is the branch this feature's work takes: the
> one the status brief lists for the issue, otherwise the name the config's **Branching** pattern gives
> it (`feat/<issue-id>-<slug>`); a stream the status brief does not list is opened with `flow-started
> {request, branch}` in the same append as the first decision. The events owed here: one
> `gate-decision` per resolved question, as it is decided, and `clarify-passed` as the PRD's last
> marker goes (Step 3) — each in the turn where it happens, the form under **Record the gate**.
> The Stop hook catches a PRD written with no `gate-decision` behind it and nothing else, so
> Step 3 is the only thing that writes `clarify-passed`.

## Step 1 — Coverage scan

First, anchor the *why*: what job is the user actually hiring this feature to do? The stated
feature is often a proposed solution, not the real need — naming the underlying job keeps the
PRD focused on the outcome and sharpens the success criteria. If the config's **Thinking
lenses** section maps a lens skill to Clarify (e.g. a jobs-to-be-done skill), invoke it;
otherwise just ask "what progress is the user trying to make, and how will they know it
worked?"

Then **first-principles** on anything the request treats as fixed ("must stay on X", "can't
touch the schema", "too expensive"): is it physics, cost or regulation — or convention? A
verified constraint is recorded as one; a conventional one becomes a question. Don't re-derive
a settled standard or a working pattern.

Then walk these dimensions and mark each **Clear / Partial / Missing** based on the request +
exploration findings. This tells you where the real gaps are instead of asking random
questions:

1. Functional scope (what's in, what's explicitly out)
2. Data model / entities affected
3. User flows / UX
4. Edge cases & error handling
5. Non-functional (performance, security, scale, accessibility)
6. Integration points / cross-cutting effects (pull from the impact map)
7. Terminology (domain words used precisely?)
8. Success criteria (how we'll know it's complete and correct)
9. Constraints & assumptions
10. Backward compatibility / migration / rollout
11. Dependencies (other teams, external systems)

## Step 2 — Ask, prioritized and one at a time

Generate **at most ~5 questions**, ordered by impact (a wrong answer here would most change
the design). Prefer using `AskUserQuestion`. For each question, **lead with your recommended
answer and the reasoning**, then offer alternatives — the user can accept, pick another, or
free-type. Asking one at a time (or one tight batch) beats dumping twenty; it respects the
user's attention and gets better answers.

Use `[NEEDS CLARIFICATION]` markers in the PRD draft for anything still open, but keep them
**few and prioritized** (scope > security/data > UX > technical detail). A capped list forces
real prioritization instead of "flag everything." The gate is passed when no
`[NEEDS CLARIFICATION]` markers remain.

### Executive mode (config Autonomy: `executive`)

The coverage scan runs in full, unchanged. But instead of asking, **answer each question
yourself with your recommended answer** and record it in the PRD under an
**"Assumptions (executive)"** list — one line each: the question, the answer taken, the
one-sentence rationale. Report the list in the phase summary so the user can veto any of
them after the fact.

Still ask — `[NEEDS CLARIFICATION]` markers become escalations-only — when a question hits
the escalation contract: a one-way door (schema, public API, shared write path, data
migration), a user-visible scope change, a configured security-sensitive area, or a genuine
50/50 where you cannot form a recommendation. Executive mode changes who answers routine
questions, not the bar for the consequential ones.

## Step 3 — Write the PRD

Create or update the PRD at the configured PRD home (default `docs/prd/<feature-kebab>.md`,
plain markdown in the repo — the *what & why*, never the *how*). Use the template at
`${CLAUDE_PLUGIN_ROOT}/skills/clarify/references/prd-template.md`, and follow any page conventions the config's Knowledge base
section declares. Number things so later phases can trace them:

- **FR-###** — functional requirements
- **SC-###** — success criteria (measurable, technology-agnostic)

A success criterion that can't be measured isn't one, it's a wish — push back on
"fast", "intuitive", "robust" until they're observable.

**Capture the issue.** Record the tracker issue in the PRD header (`Issue:`). If the user gave
an issue number or URL, pull it via the configured tracker integration (default: the forge CLI —
`gh issue view <n>` / `glab issue view <n>`) and use its description and discussion to seed the
PRD and inform your questions — don't make the user re-type what's already on the ticket. If
there's no tracker or no issue, mark it "none / ad-hoc" — that's fine. When an issue id exists,
it also feeds the branch name downstream, so getting it here saves work later.

## Record the gate (journaled projects)

On a project whose config declares a **Journal**, every resolved ambiguity is a `gate-decision`,
appended as it is decided — `ask` and `executive` alike; the mode is just a field:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type gate-decision --actor user \
  --data '{"gate":"clarify","question":"Bulk export in scope?","decision":"single export only",
           "mode":"ask","raised_by":"user","rationale":"no bulk consumer exists yet"}'
```

**Attribute it.** A point the user raised or corrected is `"raised_by":"user"` with
`--actor user`; a question you asked or answered yourself in `executive` mode is
`"raised_by":"orchestrator"` (the default) with `--actor orchestrator`, or no flag at all.
That distinction is the only way a later review of the flow can tell escalation from
correction. `journal.py vocab --shape gate-decision` prints the payload.

When the last marker is gone, append `clarify-passed` {prd, fr_count} — the PRD by **path**,
never its text (`vocab --shape clarify-passed`). That event is gate-validated: it is refused
while the PRD still contains `[NEEDS CLARIFICATION]`, which is this gate made mechanical, not an
obstacle to route around. A missing or unreadable database is an infrastructure failure, not a
reason to skip the append: surface it loudly and continue un-journaled only with the user's
acknowledgement.

## Guardrails

- **Keep the PRD free of implementation.** "Display a filterable list with full-text search"
  belongs here; "use Elasticsearch" does not — that's design.
- **Recall before asking.** The PRD is about *what & why*, so recall **project/domain
  context** via `knowledge-base` first — don't ask the user something the knowledge base
  (or the linked issue) already answers.
- **Stop at the gate.** When the PRD is complete and marker-free, summarize it and hand off
  to `design`. Don't start designing inside this skill.
