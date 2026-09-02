---
type: worklog
title: "Worklog: Workflow orchestration (slice 2)"
created: 2026-09-02
updated: 2026-09-02
tags:
  - worklog
status: done
prd: "./journal-cost-and-workflows.md"
related: ["./journal-cost-precision.worklog.md", "../adr/0002-implied-phase-transitions.md"]
---

# Worklog: Workflow orchestration (slice 2)

> Design + build plan for FR-017…FR-021 of `./journal-cost-and-workflows.md`. Branch
> `feat/workflow-orchestration`; ships as v0.12.0 after slice 1.

---

# Design

## Approach

Pragmatic-balance: two bundled Workflow scripts (review, explore) selected by a new config
section, with the existing `Agent` fan kept as the default and the fallback. The scripts
are data-in/data-out: they return schema-typed findings; every journal write and every
user-facing judgment stays in the orchestrator.

## Architecture

- `config-template.md` gains `## Orchestration`: `review: agents | workflow`,
  `explore: agents | workflow` (default `agents`). `setup` asks one question for it.
- `skills/review/references/review-workflow.js` — phases Find → Verify.
  `args = {lenses[], finderBrief, doNotFlag[], preRulings[], confidenceFloor, model,
  effortVerify}`. Find: `parallel` over lenses, `agent(..., {agentType:
  'shipgate:code-reviewer', schema: FINDINGS, model})` — a barrier is correct here because
  dedupe needs every lens's output. Dedupe in script by `file:line` then by normalized
  summary prefix. Verify: `parallel` over candidates ≥ floor, one refuter per finding
  (`schema: VERDICT`, prompt "try to refute; default refuted when uncertain"); findings
  with severity BLOCKER/HIGH get two refuters, survive on 1-of-2 kill only if both refute.
  Return `{survivors[] ranked by severity then confidence, killed[] with reasons, counts,
  lensesRun}`. `log()` what was dropped below the floor (no silent caps).
- `skills/feature/references/explore-workflow.js` — one phase, `parallel` over lenses,
  `agent(..., {agentType: 'shipgate:code-explorer', schema: EXPLORE})`; merge
  `essential_files` (dedupe, keep the union with per-lens reasons) and return
  `{lenses: [{lens, findings[]}], essentialFiles[]}`.
- `review` skill Step 1–2: when config says `workflow`, build the finder brief exactly as
  today (diff ref, worklog, PRD, impact map, do-not-flag, pre-rulings), call `Workflow`
  with the script text inline (`script`; `scriptPath` is refused outside the working
  directory — found in the T108 trial) and `args`; the
  coordinator's Step 2 then runs on `survivors` and records `killed` under **Rejected
  findings**. Steps 3–6 unchanged. `review-verdict.data.workflow_run_id` carries the runId.
- `feature` skill Explore: when config says `workflow`, same shape; the orchestrator still
  reads the essential files itself (the rule that keeps Clarify honest is unchanged).
- `model-tiers`: Workflow agents inherit the session model by default — shipgate always
  passes `model` (one tier below the session) and `effort: 'low'` only for mechanical
  stages; verify/judge stages keep default effort.
- Degradation: Workflow tool absent or refused → run the `agents` path and record a
  `deviation {note: "workflow unavailable, agents fallback"}`.

## Data flow

Orchestrator builds brief → Workflow(script, args) → finders (background) → in-script
dedupe → refuters → return object → orchestrator Step 2 → verdict + journal.

## API / contract changes

None to the journal. New config keys read by skills only (no sidecar change).

## Reference implementation

The `review-changes` pipeline in the Workflow tool's own description (find → verify) and
the review skill's Step 1 brief contents. Scripts are plain JS: no TS syntax, no
`Date.now()`, `meta` a pure literal.

## CLAUDE.md / impact-map compliance

Single plugin; no hooks touched (no security-review trigger). Public repo: no project data
in prompts or examples.

---

# Build Plan

## Setup / foundations
- [x] T101 — `## Orchestration` config section + `setup` interview question — file(s):
  `config-template.md`, `skills/setup/SKILL.md` — done when: section documented with
  defaults; setup writes it.

## Feature
- [x] T102 — `review-workflow.js` — file(s): `skills/review/references/review-workflow.js`
  — done when: meta literal, FINDINGS/VERDICT schemas, dedupe + two-refuter rule, return
  shape as designed; `node --check` passes where node exists (else manual read).
- [x] T103 [P] — `explore-workflow.js` — file(s): `skills/feature/references/explore-workflow.js`
  — done when: EXPLORE schema, merge rule, return shape.
- [x] T104 — Review skill wiring — file(s): `skills/review/SKILL.md` — done when: Step 1–2
  describe the workflow path, args list, Rejected-findings from `killed`, runId in verdict,
  fallback deviation.
- [x] T105 [P] — Explore wiring — file(s): `skills/feature/SKILL.md` — done when: Explore
  section names the workflow path and the read-the-files rule.
- [x] T106 [P] — Model/effort rule for Workflow agents — file(s):
  `skills/model-tiers/SKILL.md` — done when: explicit `model`, effort guidance stated.
- [x] T107 — README, CHANGELOG v0.12.0, version bump (plugin.json + marketplace.json).
- [x] T108 — Live trial (SC-006): run the review workflow on this slice's own diff and the
  explore workflow on this plugin (pandora is a real project); evidence as `verify-run`
  (counts only: findings found / killed / accepted; size of the returned object vs the
  three raw reviewer reports it replaces).
- [x] T109 — Script tests — file(s): `tests/test_workflow_scripts.py` — done when: a node stub
  harness runs both script bodies under `unittest` (skipped without node) covering dedupe
  cases, quorum, cap, aborted, guards; discovered by the suite.

## Traceability
- FR-017 → T101; FR-018 → T102, T104, T109; FR-019 → T103, T105, T109; FR-020 → T106;
  FR-021 → T104 (design fan untouched); SC-006 → T108.

## Deviations & notes (filled during implementation)
- 2026-09-02 — T108 trial: the `Workflow` tool refuses `scriptPath` for any file outside the
  session's working directory or an added directory; "already read" does not help. Bundled
  scripts are therefore passed inline as `script` (the tool persists a copy whose path works
  for `scriptPath` on re-runs). Skill wording corrected; ~3k tokens of script text enter the
  orchestrator's context per invocation — still far below the three raw reports it replaces.
- 2026-09-02 — T102: merge keeps the strongest severity and confidence regardless of order;
  a concrete line survives a merge with a file-only finding; unknown lens names are used as
  their own definition; missing `args.model`/empty `lenses` throw before any spend; a finding
  with no surviving refuter is kept and logged.
- 2026-09-02 — T108 review trial (design revision): the per-finding refuter fan ran 48
  refuters on 45 candidates (51 agents, ~3.5M tokens, 22 min) and returned 183 KB — roughly
  seven times the three-reviewer `Agent` fan and larger than the reports it replaces; the
  "default refuted when uncertain" rule killed 33 findings, 8 of which the coordinator
  revived on evidence. Design amended: refuters only for BLOCKER/HIGH, capped by
  `maxRefuters` (default 6), given the brief, required to cite the disproving line;
  uncertain means kept. Return is compact (`why`/`fix` ≤ 300 chars, refuter reasons ≤ 200,
  `belowFloor` as one-line entries). Cost floor is the finders themselves (≈ the Agent fan);
  the gain is structure, dedupe and context hygiene, not fewer tokens.
- 2026-09-02 — T108 review re-run in `high-only` mode after the redesign: 9 agents (3 finders
  + 6 refuters), ~640k subagent tokens, 9.5 min, 32 KB return — on par with the three-reviewer
  Agent fan (SC-006 cost met). It surfaced a still-chaining location merge, refuters without
  `agentType`, and a quorum that degraded when a refuter died; fixed in round 2 with the
  script tests (T109) added so these paths are no longer verified by live runs only.
- 2026-09-02 — T108 explore trial (2 lenses, 2 agents, ~132k subagent tokens, 3 min) found
  that `${CLAUDE_PLUGIN_ROOT}` is the only path form the host expands inside skill content;
  the two script references and the three template references (`clarify`, `design`) now use
  it instead of prose or bare-relative paths. Its return object was large (~21 KB): explorer
  `detail` fields are unbounded — a prompt-level "one paragraph per finding" cap is worth
  adding to the explore brief in `feature`.


## Rejected findings

Round 2 (2026-09-02, redesigned review-workflow), killed on evidence by the coordinator:
- Lens definitions duplicated between the review skill and the script — the script must be
  self-contained (agents cannot read skills); the skill keeps them for the Agent path.
- `.js` for an ESM-shaped script — the Workflow tool reads the file as text; the extension
  is cosmetic.
- Orchestration section "carries rationale into every copied config" — the template's other
  sections do the same; users delete what they do not need.
- `phase('Verify')` entered for `verify: none` — fixed anyway as part of the guards.

Round 1 (2026-09-02, review-workflow trial), killed on evidence by the coordinator:
- "v0.12.0 versioned while T108 was open" — the version bump belongs to the change that earns
  it (repo rule); the release paragraph is rewritten with the amended design, not withheld.
- "FINDINGS schema discards the reviewer agent's repo-rule and verified-clean sections" — by
  design: the coordinator runs Step 3 itself; the script carries findings only.
- "explore merge drops the explorer's ranking" — order of first appearance is kept and the
  list is capped; ranking across lenses is the orchestrator's read-the-files step.
- "refuter labels collide" / "`why` reused with a different type" — folded into the
  redesign (unique labels; `why` becomes `[{lens, why}]` and is documented as such).
Of the 33 findings the refuters killed, 8 were revived on evidence and fixed (unbounded
verify fan-out, refuters without `agentType`, unguarded `finderBrief`, lens validation,
transitive merge chaining, lost losing-finding text, duplicated reasons, `effortVerify`
wording) — the trial's own run demonstrated the first two.

