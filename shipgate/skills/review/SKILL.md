---
name: review
description: Final pre-push review of a change against its design and the repo's rules. Runs code-reviewer subagents in parallel, surfaces only high-confidence findings (≥80) with file:line, checks CLAUDE.md compliance (whatever rules the repo's CLAUDE.md declares), verifies the acceptance criteria are demonstrably met (not just that tasks are done), and runs a final verify. Use when implementation is complete and before opening a PR or pushing.
---

# Review

The last gate before the change leaves your hands. The goal is to catch what matters —
real bugs, drift from the agreed design, repo-rule violations — without burying the author
in nitpicks. Quality of findings over quantity.

## Step 1 — Review in parallel, three lenses

Dispatch **three `code-reviewer` subagents at once**:
- **correctness** — logic, null/undefined, races, edge cases, error handling.
- **conventions + design-alignment** — matches repo patterns and the agreed design/worklog;
  flags drift from the chosen approach.
- **simplicity + security** — needless complexity / wrong abstractions, plus OWASP-class
  issues and (if relevant) prompt injection.

Give each the diff, the worklog (design + build plan), the PRD, and the impact map.

This security lens is a routine sweep, not a full audit. For changes that touch auth,
secrets, money, or PII, or before a release, escalate to the built-in
`/security-review` for a dedicated OWASP-depth pass.

## Step 2 — Confidence filtering

Subagents only return issues at **confidence ≥ 80** (security may surface a severe
unconfirmed item flagged as such). Trust that filter — don't re-inflate the list with the
maybes they dropped. Consolidate by file, dedupe, and order by severity
(BLOCKER → HIGH → MEDIUM). Every finding must carry a `file:line` and a concrete fix.

## Step 3 — Repo-rule & design compliance

Independently confirm the change honors the rules that the impact map flagged. Pull these
from CLAUDE.md / the impact map, not from memory:

- New logic landed in the **right place** per the repo's routing rules.
- Migrations follow the repo's rules, **including any follow-up obligations** it declares.
- If the project uses feature flags → the flag is **registered where the repo requires**.
- Write path didn't get **forked**; cut-over is deliberate.
- Public/external API change → parallel-change + deprecation, not a hard break.
- Tests cover the changed behavior; FR-### / SC-### are satisfied.

## Step 4 — Acceptance-criteria check (the issue's, not just the tasks)

"My build-plan tasks are all checked" is **not** the same as "the issue's acceptance criteria
are met" — you can finish exactly the code you planned and still leave an AC unsatisfied. So
before the verdict, pull the **acceptance criteria from the tracker issue** if one exists
(`gh issue view <n>` on GitHub); otherwise the PRD's SC-### *are* the acceptance criteria.
Walk them one by one: for each criterion, point
to the **concrete evidence** it's satisfied — a test, a manual walkthrough, a screenshot — not an
assertion that it "should" be. Any criterion you can't demonstrate is **unfinished work on this
issue**, not a follow-up — route back to `implement`. Only when *every* AC is demonstrably met
does the issue earn a Ready verdict. (This applies to every issue, epic child or standalone.)

## Step 5 — Verify, then verdict

Run the `verify` gate on the suite/build/lint for the touched code — fresh output, exit
codes, real pass counts. Then give a clear verdict:

- **Ready** — no blockers, rules satisfied, evidence attached. Safe to PR/push.
- **Not ready** — list blockers; route back to `implement` (code wrong) or `design`
  (approach wrong). Don't soften a blocker into a suggestion.

## Opening the PR (on the user's go-ahead)

Applies when the repo has a GitHub remote and `gh` is available; with no tracker/remote, stop
at "Ready, evidence attached" and let the user handle pushing.

**Use the repo's PR template if it has one** (`.github/PULL_REQUEST_TEMPLATE.md` or
`.github/pull_request_template.md`) — read it, don't invent a body. Otherwise structure the
body as **Summary / Trade-offs & risks / Verification**. Either way, fill it from what this
flow already produced — you don't reverse-engineer any of it:
- **Summary** ← the PRD / worklog (what changed and why).
- **Trade-offs / risks** ← the impact map (data obligations, write-path, public API);
  write "none" only if there genuinely are none.
- **Verification** ← the `verify`-gate evidence (state "tests added/passing" etc.
  only for lines that are actually true).

Open it with `gh pr create`, and link the issue with `Closes #NN` when one exists.

Capture anything reusable from the review (a recurring mistake, a convention worth recording)
via `knowledge-base`. State plainly what you verified and what you did not — coverage honesty is
part of the review.
