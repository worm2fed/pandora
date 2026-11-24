---
name: clarify
description: The Clarify gate before design — drive ambiguity out of a feature and capture it as a PRD. Runs a coverage scan, asks a few prioritized questions (each leading with a recommended answer), and writes docs/prd/<name>.md with numbered requirements (FR-###) and success criteria (SC-###). Use after exploration and before design; don't skip it.
---

# Clarify

This gate is the cheapest place in the whole flow to prevent wasted work. Designing and
building against a wrong assumption costs hours. Asking a question costs a sentence. The gate
runs *after* exploration, so your questions come from what the code actually does. It runs
*before* design, so the expensive work starts from solid ground.

**The gate always runs, and design never starts with open clarifications.** What varies is
*who answers it*. In the default `ask` mode, the user answers. If the user is in a hurry, the
move is to answer fast, not to skip. Surface the questions with recommendations so the user
can accept each one with one tap. When the `autonomy` setting is
`executive`, you answer your own questions. See the Executive mode section below.

> **Config:** Read each setting from the `settings:` line of the status brief. For a key that
> line does not show, or with no brief, run
> `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" config <key>`. Exit 2 from it means a
> settings file holds a bad value: show its message and stop. With no `python3`, read
> `.claude/shipgate.json`, then `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else
> `~/.claude/shipgate.settings.json`); the first file that sets a key wins. Behaviour in words
> comes from `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file
> `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`). They layer per section by
> the rule in `config-template.md`'s header and the README's Configuration section; read them
> first if present.

> **Journaled project — name the stream before you start.** A project is journaled when
> the status brief is present, or `.claude/shipgate.json` exists and `journal.py config db`
> prints a `db` that is not null. On such a project this gate is owed to a stream.
> The stream is the branch this feature's work takes. Use the one the status brief lists for
> the issue. Otherwise use the name the config's **Branching** pattern gives it
> (`feat/<issue-id>-<slug>`). If the status brief does not list the stream, open it with
> `flow-started {request, branch}` in the same append as the first decision. This gate owes
> two kinds of event. Append one `gate-decision` per resolved question, as it is decided.
> Append `clarify-passed` when the PRD's last marker goes (Step 3). Append each event in the
> turn where it happens, in the form under **Record the gate**. The Stop hook checks
> neither. So these steps are the only thing that writes them.

## Step 1 — Coverage scan

First, anchor the *why*. Ask what job the user is actually hiring this feature to do. The
stated feature is often a proposed solution, not the real need. Naming the underlying job
keeps the PRD focused on the outcome, and it sharpens the success criteria. The config's
**Thinking lenses** section can map a lens skill to Clarify (e.g. a jobs-to-be-done skill). If
it does, invoke that skill. Otherwise just ask "what progress is the user trying to make, and
how will they know it worked?"

Then apply **first-principles** to anything the request treats as fixed ("must stay on X",
"can't touch the schema", "too expensive"). Ask whether the limit comes from physics, cost or
regulation, or only from convention. Record a verified constraint as a constraint. Turn a
conventional one into a question. Don't re-derive a settled standard or a working pattern.

Then walk these dimensions. Mark each one **Clear / Partial / Missing**, based on the request
and the exploration findings. The marks show you where the real gaps are, so you do not ask
random questions:

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

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

Generate **at most ~5 questions**. Order them by impact: put first the question where a wrong
answer would most change the design. Prefer `AskUserQuestion`. For each question, **lead with
your recommended answer and the reasoning**, then offer alternatives. The user can accept,
pick another, or type a free answer. Ask one question at a time, or one tight batch. That
beats a dump of twenty questions, because it respects the user's attention and gets better
answers.

Use `[NEEDS CLARIFICATION]` markers in the PRD draft for anything still open. Keep the markers
**few and prioritized**, in this order: scope > security/data > UX > technical detail. A
capped list forces real prioritization instead of "flag everything." The gate is passed when
no `[NEEDS CLARIFICATION]` markers remain.

### Executive mode (the `autonomy` setting is `executive`)

The coverage scan runs in full, unchanged. But you do not ask. Instead, **answer each question
yourself with your recommended answer**. Record each answer in the PRD under an
**"Assumptions (executive)"** list. Each entry is one line: the question, the answer taken,
and a one-sentence rationale. Report the list in the phase summary, so the user can veto any
answer after the fact.

In this mode, `[NEEDS CLARIFICATION]` markers are for escalations only. Still ask when a
question hits a case that `feature`'s executive contract escalates. The config's **Extra
escalations** line adds to those cases. Executive mode changes who answers routine questions.
It does not change the bar for the consequential ones.

## Step 3 — Write the PRD

When the `writing_style` setting is `ste-80`, the Writing for people rule applies to
the PRD. When it is `plain`, the default, write it as before.

Create or update the PRD in the PRD home, the directory of the `artifact_homes.prd`
setting. The default is `docs/prd/<feature-kebab>.md`, plain markdown in the repo. A home
outside the repo, such as a wiki, is no setting: when the config's Knowledge base section
names one in words, write the PRD there. The PRD holds the *what & why*, never the *how*. Use the template at
`${CLAUDE_PLUGIN_ROOT}/skills/clarify/references/prd-template.md`. Follow any page conventions
that the config's Knowledge base section declares. Number things so later phases can trace
them:

- **FR-###** — functional requirements
- **SC-###** — success criteria (measurable, technology-agnostic)

A success criterion that can't be measured isn't one. It is a wish. Push back on "fast",
"intuitive" and "robust" until they're observable.

**Capture the issue.** Record the tracker issue in the PRD header (`Issue:`). The user may give
an issue number or URL. If so, pull the issue through the configured tracker integration. The
default is the CLI of the `forge` setting: `gh issue view <n>` / `glab issue view <n>`. Use
the issue's description and discussion to seed the PRD and to inform your questions. Don't
make the user re-type what is already on the issue. If there's no tracker or no issue, mark it
"none / ad-hoc". That's fine. When an issue id exists, it also feeds the branch name
downstream, so getting it here saves work later.

## Record the gate (journaled projects)

On a journaled project (the status brief is present, or `.claude/shipgate.json` exists and
`journal.py config db` prints a `db` that is not null), every resolved ambiguity is a
`gate-decision`. Append it as it is decided. This applies in `ask` and `executive` mode alike;
the mode is just a field:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type gate-decision --actor user \
  --data '{"gate":"clarify","question":"Bulk export in scope?","decision":"single export only",
           "mode":"ask","raised_by":"user","rationale":"no bulk consumer exists yet"}'
```

**Attribute it.** A point the user raised or corrected is `"raised_by":"user"` with
`--actor user`. A question you asked, or answered yourself in `executive` mode, is
`"raised_by":"orchestrator"` (the default). It takes `--actor orchestrator`, or no flag at all.
That distinction is the only way a later review of the flow can tell escalation from
correction. `journal.py vocab --shape gate-decision` prints the payload.

When the last marker is gone, append `clarify-passed` {prd, fr_count}. Pass the PRD by
**path**, never its text (`vocab --shape clarify-passed`). The journal validates that event
against the gate. It refuses the event while the PRD still contains `[NEEDS CLARIFICATION]`.
That refusal is this gate made mechanical, not an obstacle to route around. A missing or
unreadable database is an infrastructure failure, not a reason to skip the append. Surface it
loudly. Continue un-journaled only with the user's acknowledgement.

## Guardrails

- **Keep the PRD free of implementation.** "Display a filterable list with full-text search"
  belongs here. "Use Elasticsearch" does not; that's design.
- **Recall before asking.** The PRD is about *what & why*. So first recall **project/domain
  context** via `knowledge-base`. Don't ask the user something that the knowledge base (or the
  linked issue) already answers.
- **Stop at the gate.** When the PRD is complete and free of markers, summarize it and hand
  off to `design`. Don't start designing inside this skill.
