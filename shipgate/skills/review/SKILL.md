---
name: review
description: Final pre-push review of a change against its design and the repo's rules. Runs code-reviewer subagents in parallel (coverage-first — they report everything scored), filters and ranks findings in a separate coordinator pass, checks CLAUDE.md compliance (whatever rules the repo's CLAUDE.md declares), verifies the acceptance criteria are demonstrably met (not just that tasks are done), and runs a final verify. Use when implementation is complete and before opening an MR/PR or pushing.
---

# Review

The last gate before the change leaves your hands. The goal is to catch what matters —
real bugs, drift from the agreed design, repo-rule violations — without burying the author
in nitpicks. Quality of findings over quantity.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

## Step 1 — Review in parallel, up to three lenses

This review is the flow's **independent verification** — fresh-context reviewers catch what
the context you accumulated while building blinds you to. Dispatch `code-reviewer`
subagents scaled to the change: **one reviewer carrying all lenses for a small, contained
diff; the full three-lens fan only for changes where each lens has real surface**:
- **correctness** — logic, null/undefined, races, edge cases, error handling.
- **conventions + design-alignment** — matches repo patterns and the agreed design/worklog;
  flags drift from the chosen approach.
- **simplicity + security** — needless complexity / wrong abstractions, plus OWASP-class
  issues and (if relevant) prompt injection.

Give each the diff, the worklog (design + build plan), the PRD, and the impact map.

This security lens is a routine sweep, not a full audit. For changes touching auth, secrets,
or any area the project config lists as security-sensitive (default: auth, secrets, payments),
or before a release, escalate to the built-in `/security-review` for a dedicated OWASP-depth pass.

## Step 2 — Filter and rank (the coordinator's pass)

Reviewers report **everything** they found, scored with confidence and severity — filtering
at generation time makes models silently drop real bugs, so the filter lives here instead,
as a separate pass. Consolidate by file, dedupe across lenses, then filter:

- **Keep** findings at confidence ≥ 80, and lower-confidence ones whose severity is high
  enough to be worth a check — verify those yourself (read the cited code) and either
  promote or kill them on evidence.
- **Drop** what doesn't survive scrutiny; don't pass speculative noise to the author.

Order by severity (BLOCKER → HIGH → MEDIUM → LOW). Every surviving finding must carry a
`file:line` and a concrete fix.

## Step 3 — Repo-rule & design compliance

Independently confirm the change honors the rules that the impact map flagged. Pull these
from CLAUDE.md / the impact map, not from memory — the repo-specific ones are conditional
examples; apply only those its CLAUDE.md actually declares:

- New logic landed in the **right place** per the repo's routing rules.
- Schema change → any downstream refresh obligations the CLAUDE.md names (e.g. dump
  refreshes) done.
- New feature flag → registered wherever the repo's flag conventions require.
- Write path didn't get **forked**; cut-over is deliberate.
- Public/external API change → parallel-change + deprecation, not a hard break.
- Tests cover the changed behavior; FR-### / SC-### are satisfied.

## Step 4 — Acceptance-criteria check (the issue's, not just the tasks)

"My build-plan tasks are all checked" is **not** the same as "the issue's acceptance criteria
are met" — you can finish exactly the code you planned and still leave an AC unsatisfied. So
before the verdict, pull the **acceptance criteria from the issue** — from wherever the config's
**Forge & tracker** section says ACs live (default: the issue description) — and walk them one by
one; if there's no tracked issue, the PRD's SC-### *are* the acceptance criteria. For each
criterion, point to the **concrete evidence** it's satisfied — a test, a manual walkthrough, a
screenshot — not an assertion that it "should" be. Any criterion you can't demonstrate is
**unfinished work on this issue**, not a follow-up — route back to `implement`. Only when *every*
AC is demonstrably met does the issue earn a Ready verdict. (This applies to every issue, epic
child or standalone.)

## Step 5 — Verify, then verdict

Run the `verify` gate on the suite/build/lint for the touched code — fresh output, exit
codes, real pass counts. Then give a clear verdict:

- **Ready** — no blockers, rules satisfied, evidence attached. Safe to MR/PR/push.
- **Not ready** — list blockers; route back to `implement` (code wrong) or `design`
  (approach wrong). Don't soften a blocker into a suggestion.

This phase **is** the flow's verification — one independent review plus one evidence gate.
Don't stack further self-check passes on top ("double-check once more", a second verify of
the same claims, a subagent to re-review the review): current models already self-verify
while working, and extra re-checking adds cost without catching more.

## Opening the MR/PR (on the user's go-ahead)

With no tracker/remote, stop at "Ready, evidence attached" and let the user handle pushing.

**Use the canonical template — don't invent a body.** If the config's **Forge & tracker**
section names a template (its location + the exact command to fetch it), read it from there —
it may live in a different repo than the code, and it changes, so the config/repo is the source
of truth. With no config, fall back to the repo's own template
(`.github/PULL_REQUEST_TEMPLATE.md` / `.gitlab/merge_request_templates/default.md`) or the
forge default (**Summary / Trade-offs & risks / Verification**). Either way, fill it from what
this flow already produced — you don't reverse-engineer any of it:
- **Summary** ← the PRD / worklog (what changed and why).
- **Trade-offs / risks** ← the impact map (data obligations, write-path, flags, public API);
  write "none" only if there genuinely are none.
- **Verification** ← the `verify`-gate evidence (tick "tests added/passing", "behind flag", etc.
  only for lines that are actually true).

Match the body's length to what a reviewer needs — cover the substance, no filler sections,
no restating the diff. The same goes for every written deliverable this flow produces.

**Link the issue.** Use the issue-link form the config declares — cross-repo issues need the
project-qualified form, e.g. `group/project#NNNN`, since a bare `#NNNN` resolves to a
non-existent same-repo issue. Default: the forge's native `#NNNN` / `Closes #NNNN`. Honor any
extra title/body rules the config declares.

**Hand off to the MR watcher.** If the config declares an **MR watcher**: after the MR is open,
register any MRs this work is blocked on — and any follow-up work gated on this MR merging —
with the watcher's watch list, using the registration command the config names. The note must
carry the held work and its next action (e.g. "unblocks #8311 — rebase + open MR"). Say what
you're registering as you do it. No watcher declared → skip silently.

## The review-feedback cycle (after the MR/PR is open)

Reviewer comments re-enter the flow here. This is a loop between Review and Implement,
not a new phase:

1. **Read every thread** before changing anything. Some comments are questions or
   already-answered concerns — reply, don't code.
2. **Route real changes back to `implement`.** Fold them into the commits they amend if
   the repo's convention says so (e.g. fixup + autosquash) rather than stacking
   "address review" commits.
3. **Re-run the `verify` gate on the changed scope** and re-review what changed — not the
   whole MR again.
4. **Push, reply in each thread** with what changed (or why you disagree), and resolve
   the threads you've addressed.
5. Hand back to the MR watcher (if declared) and wait. Merge → residual ledger triage only
   (the main Capture already ran when the review verdict landed — anything new here came
   from this feedback cycle).

Capture anything reusable from the review (a recurring mistake, a convention worth recording)
via `knowledge-base` — quick observations go to the project **ledger** as one-liners; the
Capture phase triages them. State plainly what you verified and what you did not — coverage
honesty is part of the review.
