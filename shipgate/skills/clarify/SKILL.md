---
name: clarify
description: The hard gate before design — drive ambiguity out of a feature and capture it as a PRD. Runs a coverage scan, asks a few prioritized questions (each leading with a recommended answer), and writes docs/prd/<name>.md with numbered requirements (FR-###) and success criteria (SC-###). Use after exploration and before design; don't skip it.
---

# Clarify

This is the cheapest place in the whole flow to prevent wasted work. Designing and building
against a wrong assumption costs hours; asking a question costs a sentence. The gate runs
*after* exploration (so your questions are informed by what the code actually does) and
*before* design (so the expensive work starts from solid ground).

**Do not skip this, and do not proceed to design with open clarifications.** If the user is
in a hurry, the move is to *answer fast*, not to skip — surface the questions with
recommendations so they can one-tap them.

## Step 1 — Coverage scan

First, anchor the *why*: what job is the user actually hiring this feature to do? The stated
feature is often a proposed solution, not the real need — naming the underlying job keeps the
PRD focused on the outcome and sharpens the success criteria. If the `thinking-skills` plugin
is available, `thinking-jobs-to-be-done` does this directly; otherwise just ask "what progress
is the user trying to make, and how will they know it worked?"

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
8. Done-criteria (how we'll know it's complete and correct)
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

## Step 3 — Write the PRD

Create or update `docs/prd/<feature-kebab>.md` in the target repo (a plain Markdown file —
the *what & why*, never the *how*). Use the template at `references/prd-template.md`. Number
things so later phases can trace them:

- **FR-###** — functional requirements
- **SC-###** — success criteria (measurable, technology-agnostic)

A success criterion that can't be measured isn't done-criteria, it's a wish — push back on
"fast", "intuitive", "robust" until they're observable.

**Capture the issue.** Record the tracker issue in the PRD header (`Issue:`). If the repo has
a GitHub remote and the user gave an issue number or URL, pull it (`gh issue view <n>`) and use
its description and discussion to seed the PRD and inform your questions — don't make the user
re-type what's already on the ticket. If there's no tracker or no issue, mark it "none /
ad-hoc" — that's fine. When an issue id exists, it also feeds the branch name downstream, so
getting it here saves work later.

## Guardrails

- **Keep the PRD free of implementation.** "Display a filterable list with full-text search"
  belongs here; "use Elasticsearch" does not — that's design.
- **Recall before asking.** The PRD is about *what & why*, so recall **project/domain
  context** via `knowledge-base` first — don't ask the user something the knowledge base
  (or the linked issue) already answers.
- **Stop at the gate.** When the PRD is complete and marker-free, summarize it and hand off
  to `design`. Don't start designing inside this skill.
