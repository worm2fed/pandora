---
type: prd
title: "PRD: Clarify surfaces the user's unknowns before the build"
created: 2026-11-24
updated: 2026-11-24
tags:
  - prd
  - shipgate
  - clarify
  - executive
status: clarified
issue: "#24 (shipgate), child of #37"
worklog: "./clarify-unknowns.worklog.md"
related:
  - "../adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
  - "../adr/0028-settings-live-in-shipgate-json-and-layer-per-key.md"
  - "../adr/0026-the-close-out-runs-local-steps-and-asks-once.md"
  - "../research/2026-11-15-agent-harness-audit.md"
  - "./code-signals.md"
---

# PRD: Clarify surfaces the user's unknowns before the build

> In `executive` mode, clarify still answers its own questions. It then shows the user the
> few answers that are most likely wrong, with the evidence behind each, in one dialog
> before design starts.

## Terms

- **Assumption**: a clarify answer that the orchestrator took alone in `executive` mode.
  The PRD's "Assumptions (executive)" list holds one line per assumption.
- **Class**: the kind of an assumption: `domain` (a domain rule or a tool fact), `data` (the
  data model), `behaviour` (what a user sees, including user-visible names such as labels,
  commands and setting keys) or `technical` (everything else, tests included).
- **Source**: a file, an issue or a knowledge-base entry that states the answer. It is
  quoted in one line with its path or reference.
- **Risky assumption**: an assumption of class `domain`, `data` or `behaviour` that has no
  source.
- **Confirm batch**: the risky assumptions, plus the blindspot and UI candidates, that
  clarify puts to the user in one dialog. (Candidates joined the batch in the build's
  review round 1; a candidate exists to be put to the user, whatever its source.)
- **Own share**: of the in-window commits that touch a directory, the share that the
  current git identity authored. It is a number. No name or email is in it.
- **Unfamiliar area**: a touched directory with an own share below 0.10, or with no commits
  in the window.
- **Blindspot pass**: a short read of an unfamiliar area that asks what its owners would
  expect this change to decide, which the request does not mention.

## Problem

In `executive` mode the orchestrator answers every routine clarify question itself. That
clears the questions it can see. It cannot know what the user would recognise on sight but
never wrote down. Nothing asks what the user has not thought of. These unknowns surface in
implement and review, where a change costs most.

Evidence (research note, counts from seven flow journals and 148 main-session transcripts,
2026-08-20 to 2026-11-15):

- 52% of the user's gate decisions (150 of 289, publish and commit excluded) arrive in
  implement, review or capture. `clarify-passed` occurs in 19% of streams.
- Of 772 questions with a recommended option, the user overrode 23%. Domain questions: 26%.
  Naming and docs: 35%. Tests: 10%.
- 12 corrections were wrong assumptions about a domain rule or a tool fact.
- Two journals hold 355 executive gate decisions, all taken without the user. The note
  lists "questions that executive mode answered without asking" as not measured: they
  leave no question record.
- 0 user messages ask what they are missing.
- References for UI work arrived after a defect in 10 sessions.

Today's skill text already has two halves of the fix as prose. "Recall before asking" is a
guardrail with no step, no store list and no quote rule. No step follows the documents an
issue links. The Assumptions list exists, but it carries no class and no source, so nothing
can rank it.

## Goals & non-goals

**Goals**

- The user sees the few executive answers most likely to be wrong before design starts,
  at the cost of at most one dialog per clarify run.
- Each such answer shows what it was based on, or that nothing was found.
- In an area the user does not know, clarify asks what nobody has asked yet.
- The override rate of executive answers becomes measurable from the journal.
- A project can turn the dialog off and keep the rest.

**Non-goals**

- No change to who answers routine questions in `ask` mode: the user still answers all.
- No change to the escalation bar of the executive contract (one-way doors, scope,
  security-sensitive areas, true 50/50, Extra escalations).
- No new dialog for technical detail or tests.
- No design variants for UI work: they move to #26 with visual evidence.
- No digest at the publish gate: #25 owns it. This PRD only gives #25 a list it can read.
- No hook file changes: the model records the answers.

## Users & stories

- As a user in `executive` mode, I want to see the 3 or 4 answers the orchestrator was
  least sure of, so that I can correct a domain rule before the build, not in review.
- As a user, I want each question to quote what the orchestrator found, so that I judge
  the evidence, not a guess.
- As a user who works in an area I rarely touch, I want clarify to name what the area's
  owners would expect me to decide, so that I do not learn it from a reviewer.
- As a lead that runs teammate sessions, I want the batch in the teammate's report, so
  that I can relay it to the user without a dialog in a pane nobody watches.
- As a user who gave a fully specified issue, I want no dialog at all.
- As a user who wants an executive flow with no stop in one project, I want to turn the
  dialog off there and keep the ranked list in the summary.

## Functional requirements

**The assumption line**

- **FR-001** — Each line of "Assumptions (executive)" carries its class and its source, or
  "no source found in <what was searched>".
- **FR-002** — Before clarify answers or asks a `domain`, `data` or `behaviour` question,
  it searches the evidence once for the whole run: knowledge-base recall, the issue with
  its comments, and the documents the issue links, one level deep, at most 3, only those
  the session can read.
- **FR-003** — An answer that a source states is a constraint, not an assumption. It goes
  under "Constraints & assumptions" with its source, and it never enters the confirm batch.
  A candidate is the exception: a blindspot candidate is always in the batch, and a UI
  candidate exists only when the request or the issue names no reference (FR-018).

**The confirm batch**

- **FR-004** — In `executive` mode, at the end of clarify and before design, clarify puts
  the risky assumptions and the blindspot and UI candidates to the user as one confirm
  batch, ordered by how much a wrong answer would change the design.
- **FR-005** — The batch is one `AskUserQuestion` with one question per item, at most 4.
  Each question states the answer taken and quotes its source or says none was found. Its
  first option keeps the answer and is the recommended one; one or two alternatives from
  the coverage scan follow; "Other" takes free text.
- **FR-006** — With no risky assumption and no candidate, there is no batch and no dialog. A clarify run
  that a fully specified issue answers asks nothing. Work too small for clarify (a one-line
  fix) never reaches it.
- **FR-007** — An escalation of the same clarify run shares the dialog with the batch and
  comes first. A clarify run opens at most one dialog, unless its escalations alone fill
  it.
- **FR-008** — When the stream names a lead (`report_to`), the batch goes to the lead in
  one message, not to a dialog. With no question tool and no lead, the batch is the last
  block of the reply, and the flow continues.
- **FR-009** — A confirm item is not an open clarification marker. Markers stay for
  escalations, so the rule for `clarify-passed` does not change.
- **FR-010** — The model records each answer once. In the PRD, the line ends with the tag
  `[kept by the user]`, `[changed by the user, was: <old answer>]` or `[unconfirmed]`. In
  the journal,
  each asked item is one `gate-decision` (`gate: clarify`, `mode: ask`, `--actor user`):
  `raised_by: orchestrator` when kept, `raised_by: user` when changed. A dismissed dialog
  leaves every item unconfirmed and is one `gate-decision` with `mode: executive`; the
  flow goes on.
- **FR-011** — A change to an assumption after `design-committed` is a `deviation`, and the
  design parts that depend on it are re-checked before the build.

**The `clarify_confirm` setting**

- **FR-012** — The settings schema has the key `clarify_confirm`: `risky` (the default) or
  `off`, scope `any`. It is not on the status line; clarify reads it with
  `journal.py config clarify_confirm` in `executive` mode only.
- **FR-013** — With `off`, clarify opens no dialog and makes no stop for the batch, and
  sends no batch to a lead. Every line still gets its class and source. The phase summary
  lists the risky lines first, as today's veto list. Escalations still go to the user, as
  the executive contract says. In `ask` mode the key has no effect.

**Own share and the blindspot pass**

- **FR-014** — `signals.py hotspots --by-dir` gives each directory row `own_share` and
  `unfamiliar`. `own_share` is the current identity's share of the row's in-window commits,
  0.0 when the row has none. `unfamiliar` is true when `own_share` is below 0.10. With no
  identity or no history, both are null, and a top-level `own_reason` says why. The output
  never holds a name or an email.
- **FR-015** — The identity is git's own `user.email`, mapped through `.mailmap`, compared
  in memory.
- **FR-016** — Clarify reads `unfamiliar` from the impact map. With no map, it runs one
  `signals.py hotspots <dirs> --by-dir 2 --json` call itself.
- **FR-017** — When a touched directory is unfamiliar or unknown, clarify runs the
  blindspot pass and says why in one line. The pass reads the area's `CLAUDE.md` or
  `README`, the subjects of its last 20 commits (no authors) and its top fix-rate files. It
  adds at most two candidates, marked as blindspot, to the same list as the other
  questions. It opens no dialog of its own.

**UI**

- **FR-018** — When the impact map tags a touched module `UI` and the request or the issue
  names no
  reference, the list gets one candidate: the reference implementation or screenshot that
  the work should follow, with the nearest existing screen as the recommended answer. When
  the request or the issue names the reference, there is no candidate: the reference is a
  sourced line,
  and it opens no dialog (the user's rule, after the build's review round 2).

**Mode and checks**

- **FR-019** — In `ask` mode the user still answers every question. Sources (FR-001 to
  FR-003), blindspot candidates (FR-017) and the UI candidate (FR-018) apply inside the
  existing cap of about 5 questions.
- **FR-020** — Every rule a script can check is a unit test or a prose test. An eval case
  judges only what needs a model run.

## Success criteria

Deterministic, checked by `python3 -m unittest discover -s shipgate/tests`:

- **SC-001** — On a two-author repository, `own_share` and `unfamiliar` match hand-derived
  values for an owned directory, a foreign one, one with no in-window commits, and a share
  of exactly 0.10 (not unfamiliar). With no identity, both are null and `own_reason` is
  `no-identity`. A `.mailmap` entry maps the identity.
- **SC-002** — No output form of `signals.py` (JSON, table; `hotspots`, `blast`,
  `suspects`) holds an author name or email, with a repo-local identity configured: 0
  matches.
- **SC-003** — `journal.py config clarify_confirm` prints `risky` from the default and
  `off` from a project file; a bad value exits 2. The README lists the key with its values,
  default and scope.
- **SC-004** — The journal accepts the three recording forms of FR-010.
- **SC-005** — Prose tests pin the required sentences: clarify names `clarify_confirm` and
  what `off` does, the cap of 4, "no source found", the three PRD end words, `report_to`,
  `unfamiliar`; the PRD template shows the line format; the executive contract names the
  confirm batch; route-and-map's map names `unfamiliar`.

Model runs, eval cases on Opus and Fable:

- **SC-006** — In the confirm-batch case, the linked policy document is read, its rule is a
  sourced constraint and stays out of the batch, the batch items are `domain`, `data` or
  `behaviour`, a blindspot item names the rule planted in the unfamiliar area's history,
  and no author identity appears. The case scores at least 0.8 on each model.
- **SC-007** — In the UI case, the list asks for a reference or names the screen to mirror.
- **SC-008** — For a fully specified request in `executive` mode, the reply asks the user
  nothing and the PRD has no open marker.
- **SC-009** — Case 16 still escalates the one-way doors as open markers, with a score of at
  least 0.8 on each model.

After the release:

- **SC-010** — One month after the release, the journal can count executive clarify items
  asked and changed (`gate: clarify`, `mode: ask`, by `raised_by`), so the override rate of
  executive answers has a number.

## Constraints & assumptions

- `AskUserQuestion` takes 1 to 4 questions per call and 2 to 4 options per question, adds
  "Other" by itself, and limits a header to 12 characters. One dialog holds at most 4
  questions.
- Eval sessions have no `AskUserQuestion` tool. A case can judge what the agent would ask:
  its reply, the PRD and the tool trace. The harness loads the installed plugin, which is
  the main checkout: the baseline runs before the merge, the PR tree after the merge and
  before the tag.
- FR-007 of the code-signals PRD: author identity never appears in output, only counts and
  shares. `signals.py` keeps author emails in memory only (`_Acc.authors`).
- `signals.py` stays Python 3.9 compatible and stdlib only.
- The repo is public. Fixtures use `example.com` identities and generic names.
- Skill text describes the ask and the computed capability and explains why, for Opus and
  Fable alike. #32 will diet the skill bodies, so the added text stays small.
- In this repo one author wrote all 159 commits of the last 12 months. The blindspot pass
  never runs here; the eval fixture is the only model-run test of it.
- The reply recorder (`hooks/reply.py`) records only answers under a `commit` or `publish`
  header, so a clarify answer passes it as a witness at most. No hook file changes.

## Assumptions (executive)

- How is the design produced? → inline, with no architect fan — `technical` — the open
  space is product behaviour, which went to the user as forks; the code part is one field
  in `signals.py`. Source: no source found in the ADR home.
- Do parts 2, 3 and 4 get their own pass or dialog? → no; they feed the one assumption list
  (in `executive` mode) or the one question list (in `ask` mode) — `behaviour` — one
  mechanism instead of four keeps the dialog count at one. Source: ADR 0026. Kept by the
  user (no veto of the frame, 2026-11-24).
- Which classes may enter the batch? → `domain`, `data`, `behaviour`; user-visible names
  count as `behaviour` — `behaviour` — the override rates are highest there (26% domain,
  35% naming), lowest for tests (10%); code-internal names are a design matter. Source:
  issue #24 Evidence.
- How is the batch ordered? → by how much a wrong answer would change the design, the rule
  clarify already uses — `behaviour` — a second score for "likely to change" would be a
  guess with no data behind it. Source: `clarify/SKILL.md` Step 2.
- Does an escalation open a second dialog? → no; it shares the dialog and comes first —
  `behaviour` — the user asked for fewer dialogs. Source: no source found.
- Where does a teammate's batch go? → to its lead in one message — `behaviour` — a dialog
  in a teammate pane blocks with nobody to answer. Source: `flow-started.report_to`.
- Is a confirm item an open clarification marker? → no — `technical` — a marker would
  block `clarify-passed` in sessions with no question tool. Source: `clarify/SKILL.md`
  Record the gate.
- How is the current identity found? → `git config user.email`, mapped through
  `git check-mailmap`, compared in memory — `data` — `%aE` in the trajectory scan is
  already mailmap-applied, so both sides match. Source: `signals.py` `scan_trajectory`.
- Does `ask` mode change? → only through sources, blindspot and UI candidates, inside its
  existing cap — `behaviour` — the user already answers everything there. Source: no
  source found.
- Is `clarify_confirm` on the status line? → no — `technical` — the line costs tokens at
  every session start, and only an executive clarify run reads the key. Source: ADR 0028
  M2.
- Where does the 0.10 threshold live? → a constant in `signals.py`, which computes
  `unfamiliar` itself — `technical` — the skill then reads a boolean, not a number to
  compare, and a unit test pins the constant; a key can follow after a month of data.
  Source: F3-B names one key only.
- Which rows carry the own share? → the `--by-dir` rows, plus a top-level `own_reason`; file
  rows and the table stay as they are — `technical` — clarify and route-and-map read
  directory rows only, and the pinned file-row keys need no change. Source: `test_signals.py`
  file-row key test.
- Does `setup` ask about `clarify_confirm`? → no — `behaviour` — the default fits, and a
  question at setup is one more dialog; the README documents the key. Source: no source
  found.
- Where does the old "Recall before asking" guardrail go? → it is removed; the evidence
  step of Step 1 replaces it — `technical` — one rule, not two. Source: `clarify/SKILL.md`
  Guardrails.
- Which version? → 0.34.0, one PR, no hook file — `technical` — a behaviour change and a new
  signals field. Source: root `CLAUDE.md`.

## Decisions (the user, through the lead, 2026-11-24)

The eight escalated forks. ADR 0029 holds the options and their costs.

- **F1** — option A: the batch reaches the user at the end of clarify, before design
  (FR-004).
- **F2** — option A: one question per item, at most 4, keep first; a dismissed dialog
  leaves the answers unconfirmed; no dialog when nothing qualifies (FR-005, FR-006,
  FR-010).
- **F3** — option B, against the design session's recommendation: the key
  `clarify_confirm`, `risky` or `off`, scope `any` — the user wants a per-project way out,
  as for orchestration (FR-012, FR-013).
- **F4** — option A: own share below 0.10 at depth 2, or no commits; with no signals or no
  identity the pass runs and says why (FR-014 to FR-017).
- **F5** — option A: one search per clarify run (FR-002).
- **F6** — option A: the reference ask stays in #24; design variants move to #26 (FR-018).
- **F7** — option A: the model records; no hook file changes (FR-010).
- **F8** — option A as the budget, about 70 USD, under two later rules from the user:
  measure only what a fall would change, and check deterministically whatever a script can
  check (FR-020). The worklog's eval plan applies both.
