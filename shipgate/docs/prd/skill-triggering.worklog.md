---
type: worklog
title: "Worklog: skill triggering on natural prompts"
created: 2026-09-26
updated: 2026-09-26
tags:
  - worklog
  - shipgate
status: done
prd: none — bug fix, executive assumptions below
related:
  - ./code-signals.worklog.md
---

# Worklog: skill triggering on natural prompts

> Bug fix, shipgate v0.13.1. No PRD: one-cause defect in plugin prose; the regression test
> already exists (evals 08–11).

## Impact map

- **Primary home**: `shipgate/skills/{structured-debug,route-and-map,review,feature}/SKILL.md`
  — the `description` frontmatter is the only text the agent sees before deciding to invoke a
  skill (a `--plugin-dir`-only `claude -p` session lists exactly `shipgate:<skill>` + description;
  README, plugin.json and hooks are not shown).
- Touched: `README.md` (per-skill one-liners), `CHANGELOG.md`, `.claude-plugin/plugin.json` +
  `../.claude-plugin/marketplace.json` (0.13.1), `docs/prd/code-signals.worklog.md` (follow-up
  pointer).
- Not touched (out of scope by brief): `scripts/signals.py`, `skills/review/references/review-workflow.js`,
  anything under `hooks/`.
- Risk signals: n/a — prose-only change, no code paths.

## Diagnosis (structured-debug, light)

**Observed vs expected.** With-arm of evals 08/09/10: `Skill` called 0× in ~60 runs (v0.12.1 and
v0.13.0); explicit variants 12–14 fire every run. Reproduced on 2026-09-26 with a cheap probe
(`claude -p` + `--plugin-dir shipgate --setting-sources ""`, fixture scaffolded, 4 turns):
08 `-`, 09 `-`, 10 `-`, 11 `-` (11 is the wanted outcome).

**Cause (confirmed by reading what the agent sees).** Each description states *where in the
flow* the skill sits, not *what a user asks for*:

- `structured-debug` — "clarify … reproduce … agree a fix before changing code. Use when asked
  to debug a bug, investigate a regression …". Case 08 asks *which file most likely holds the
  defect* and says *do not fix anything*: the description reads as a fix pipeline, and the ask
  (localization) is not in its trigger list.
- `route-and-map` — "First step of any feature or bug — decide WHERE the change belongs …
  Use at the start of feature work". Case 09 asks what an *existing* change at HEAD affects,
  before a PR; nothing in the description names impact / blast radius / "what could this break".
- `review` — "Final pre-push review … runs code-reviewer subagents … Use when implementation is
  complete". Case 10 says explicitly *not a code review*, only a regression-risk ranking; the
  description offers nothing but a review, so the model steers away.
- All three omit the capability the bare model lacks (per-file fix history, fan-in, blast
  radius computed from git). Claude undertriggers skills on tasks it thinks it can do itself;
  cases 08/09 are exactly such "ceiling" tasks.
- `feature` — "Use when starting a feature or bug" — would compete for case 08 once the phase
  skills trigger, and routes a read-only question into Workspace/branching.

Rejected: harness/allowed-tools problem (12–14 fire), truncation (limit is 1,536 chars; longest
of the four is 601).

## Assumptions (executive)

- A1. Fix = rewrite the four descriptions around the asks + the computed signals, with explicit
  negative trigger for trivial one-line edits (keeps 11 at 0). Body changes limited to a short
  "Standalone asks" paragraph per phase skill so an invoked skill answers the question and stops
  (no branch, no fix plan, no reviewer fan) — that is what keeps the scores from dropping.
- A2. `signals.py`, `review-workflow.js`, hooks untouched (brief).
- A3. Regression gate = evals 08–11, `--runs 3 --ablation with-without`: skill-fired ≥2/3 on
  08/09/10 in the with-arm, 0/3 on 11, scores not below the v0.13.0 baselines
  (08 0.93 / 09 1.0 / 10 0.83 / 11 1.0, last full runs).
- A4. Descriptions stay well under the 1,536-char cap (target ≤ 900).

## Design

Descriptions follow one shape: *what it computes that a plain read cannot* → *the process* →
*"Use whenever the user asks …" with the natural phrasings from the eval prompts and their
near-synonyms* → *negative trigger*. `feature`'s description redirects standalone questions to
the phase skill. Cheap inner loop: the probe; gate: the harness.

# Build Plan

- [x] T001 — rewrite `structured-debug` description + "Standalone asks" note — file(s):
  `skills/structured-debug/SKILL.md` — done when: probe fires `structured-debug` on 08 ≥2/3
- [x] T002 — rewrite `route-and-map` description + note — file(s): `skills/route-and-map/SKILL.md`
  — done when: probe fires `route-and-map` on 09 ≥2/3, 11 stays 0/3
- [x] T003 — rewrite `review` description + note — file(s): `skills/review/SKILL.md` — done
  when: probe fires `review` on 10 ≥2/3
- [x] T004 — `feature` description redirect for standalone asks — file(s): `skills/feature/SKILL.md`
  — done when: probe on 08/09/10 fires the phase skill, not `feature`
- [x] T005 — README one-liners, CHANGELOG v0.13.1, version bumps in both manifests, follow-up
  pointer in `code-signals.worklog.md` — done when: `grep 0.13.1` hits both manifests
- [x] T006 — regression gate: harness on 08–11 (`--runs 3 --ablation with-without`) under a
  scratch HOME + `CLAUDE_CONFIG_DIR` — done when: A3 holds; results table recorded below
- [x] T007 — public-repo grep of the diff (private names / tracker ids / paths) — done when: no hits

## Traceability
- Goal (08/09/10 fire, 11 does not, scores hold) → T001–T004, T006

## Deviations & notes
- 2026-09-26 — eval harness refuses Bash cases on a machine whose `~/.docker` holds symlinks
  (`DOCKER_CONFIG` does not bypass it). An empty scratch `HOME` plus an explicit
  `CLAUDE_CONFIG_DIR` authenticates without `claude setup-token`; the runner skill
  `.claude/skills/run-evals` encodes this. Nested `claude` calls are launched with
  `env -u CLAUDECODE`.

## Results

Probe (`claude -p` + `--plugin-dir`, 4 turns, 3 runs each, new descriptions): 08 → `structured-debug` 3/3,
09 → `route-and-map` 3/3, 10 → `review` 3/3, 11 → none 3/3 (baseline before the change: 0/1 on each).

Harness (`claude plugin eval`, `--runs 3 --ablation with-without --judge-model sonnet`, 2026-09-26,
via a scratch HOME, $3.86 total):

| case | with | without | skill-fired (with) | v0.13.0 with-arm baseline |
|---|---|---|---|---|
| 08 bug localization | 1.00 | 1.00 | 3/3 `structured-debug` | 0.93, 0/3 |
| 09 blast radius | 1.00 | 1.00 | 3/3 `route-and-map` | 1.00, 0/3 |
| 10 risk ranking | 1.00 | 1.00 | 3/3 `review` | 0.83, 0/3 |
| 11 negative (typo) | 1.00 | 1.00 | 0/3 | 1.00, 0/3 |

Re-runs after the review-round edits (same flags): 08 → 1.00 / 1.00, 3/3 `structured-debug`;
09 → first re-run 0.90 / 1.00 (two answers named the files they had ruled out, which the
prompt forbids — the `route-and-map` note now says "the answer is the affected set and nothing
else"), second re-run 1.00 / 1.00, 3/3 `route-and-map`.

With-arm turns fell (08: 7 vs 6–9; 10: 4 vs 7–10) — the invoked skill goes straight to the
signals instead of exploring. Public-repo grep of the diff: no hits outside the pre-existing
author fields.

## Review round 1 (single reviewer, correctness + conventions)

Fixed: the `route-and-map` standalone note claimed a direct/transitive split and
`partial`/`unresolved` markers that `blast --json` does not produce (HIGH — rewritten to the
actual payload: `by_dir`, flat `files`, `unknown_seeds`, direct importers by grep);
`structured-debug` note's step numbering; blank lines around the three notes; two worklog
slips (description length figure, a location/time detail).

Rejected: "churn" in `review`'s description names no output field — the plugin already uses
churn as the label for commit volume (`route-and-map` body: "churn from `commits`"); kept.
Resolved before the report landed: T006/T007 unchecked — the harness and the diff grep ran
after the reviewer started.
