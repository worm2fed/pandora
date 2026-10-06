---
type: worklog
title: "Worklog: Thinking lenses inlined into the phase skills"
created: 2026-10-06
updated: 2026-10-06
tags:
  - worklog
  - shipgate
status: review
prd: "./thinking-lenses.md"
related: []
---

# Worklog: Thinking lenses inlined into the phase skills

> Design + build plan companion to `./thinking-lenses.md`.

---

# Design

## Approach

Minimal-change, no fork: each lens becomes one bullet (or one short paragraph) in the section
of the phase skill that already holds that skill's lenses or stop-rules, in the existing voice
(`- **lens-name** — idea; when it applies.`). No new skills, no frontmatter change, no script
or hook change. The source text is condensed from the original `SKILL.md` files (read in
full before condensing), not copied.

## Placement

| Lens | File | Anchor |
|---|---|---|
| steel-manning, second-order, via-negativa, TRIZ, margin-of-safety | `skills/design/SKILL.md` | Step 2, "run two quick lenses" list (becomes "a few") |
| map-territory, OODA, systems | `skills/structured-debug/SKILL.md` | step 3 lens list |
| Cynefin | `skills/feature/SKILL.md` | "Scale ceremony to the change" |
| first-principles | `skills/clarify/SKILL.md` | Step 1, after the JTBD paragraph |
| sunk-cost, bounded-rationality | `skills/implement/SKILL.md` | "When to stop and reconsider" |
| steel-manning (pushback) | `skills/review/SKILL.md` | review-feedback cycle |
| circle-of-competence | `skills/knowledge-base/SKILL.md` | Recall — replaces "an empty search is fine" |

## Evals

- `68-design-steel-man`: case 53's billing fixture (ask mode: agree the approach before the
  worklog) + the user arrives set on synchronous in-request rendering. Graded on the final
  message: it builds and answers the strongest case for the queue / stored-file alternative
  (llm rubric + a regex over the lens vocabulary) and still makes one recommendation; no
  worklog yet.
- `69-debug-map-territory`: README, docstring and a green test all describe discount-before-tax
  and are right about `pricing.quote()`; the live `checkout.charge_total` stopped calling it in
  a "one pass" perf commit that scales the discount back out of the taxed gross (110.00, not
  108.00). Pass = names the live path, says what the green test does and does not cover,
  shows a repro, names the perf commit, proposes rather than applies the fix.

Both reuse the existing fixture shape (`fixture.sh` builds `app/`, regex + llm graders,
`skill-fired` display-only).

---

# Build Plan

- [x] **T001** — `design`: add the five lens bullets (FR-001). Verify: frontmatter diff empty; size delta noted.
- [x] **T002** — `structured-debug`: add the three lens bullets (FR-002). Verify: as T001.
- [x] **T003** — `feature`: Cynefin paragraph in "Scale ceremony" (FR-003). Verify: as T001.
- [x] **T004** — `clarify`: first-principles line in Step 1 (FR-004). Verify: as T001.
- [x] **T005** — `implement`: sunk-cost + bounded-rationality bullets (FR-005). Verify: as T001.
- [x] **T006** — `review`: steel-manning on pushback (FR-006). Verify: as T001.
- [x] **T007** — `knowledge-base`: circle-of-competence in Recall (FR-007). Verify: as T001.
- [x] **T008** — `NOTICE` + README credit + integrations row (FR-008). Verify: NOTICE names source/licence/copyright.
- [x] **T009** [P] — eval cases 68 and 69: fixture, prompt, graders; run `run-case.sh` for both; record in `baseline.json` (FR-009, SC-003).
- [x] **T010** — version 0.14.0 in plugin.json + marketplace.json; CHANGELOG entry with per-skill size deltas (FR-010).
- [x] **T011** — final checks: frontmatter unchanged across all skills (SC-001); private-data grep over the diff (SC-004).
