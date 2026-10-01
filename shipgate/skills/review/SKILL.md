---
name: review
description: Pre-push review of a change, and the risk ranking that decides where to look hardest. Computes per-file regression risk for the diff from git history and the import graph (fix-rate, churn, fan-in — a ranking a read of the diff cannot produce), then runs code-reviewer subagents in parallel (coverage-first, every finding scored) as a hand-driven Agent fan or the config-selected review Workflow script with evidence-required refuters, filters and ranks findings in a separate coordinator pass, checks CLAUDE.md compliance, verifies the acceptance criteria are demonstrably met, and runs a final verify. Use whenever the user asks to review a change before an MR/PR or push, to rank the changed files by how likely each is to regress, which files in a diff are riskiest, or where to focus review effort — even when they say "just the ranking, not a code review" — and when implementation is complete and before opening an MR/PR. Also the re-review after a round of fixes, however small the fix diff: "I've addressed the review findings F1 and F2 — good to push?", "round 2", "re-review the fix", "here's the follow-up commit", a worklog listing findings as fixed at HEAD. That pass is scoped to the fix diff (one reviewer, not the full fan) and answers two things a glance at the worklog cannot: is each listed finding actually fixed in the code, and what did the fixes break — the new bugs hide there. Not for a trivial one-line edit (a docstring, a comment) or for explaining what a diff does.
---

# Review

The last gate before the change leaves your hands. The goal is to catch what matters —
real bugs, drift from the agreed design, repo-rule violations — without burying the author
in nitpicks. Quality of findings over quantity.

**Standalone asks** — "rank the changed files by how likely each is to regress", "where should I
look hardest?", "not a code review, just the ranking": the risk table *is* the deliverable. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --diff <base> --json` (`HEAD~1` for
the commit at HEAD), keep the JSON's order (risk, then fixes, then commits), and answer with a
numbered list of the changed files and one line of evidence each (fix%, commits, fan-in,
staleness). Dispatch no reviewers and do not review the diff's contents unless asked.

**Re-review after a round of fixes (before the MR/PR is open)** — "I've addressed F1 and F2,
good to push?", a follow-up commit, a worklog whose *Review round N* section marks findings
fixed at HEAD. The pass is scoped to the **fix diff** — HEAD against the base the previous
round reviewed (the commit before the fix, unless the round entry names another) — not the
whole change again, and it is scaled to that diff: one reviewer carrying all lenses, or the
coordinator alone for a fix of a couple of files (say which, and why). Never the three-lens
fan. It answers two questions, in order, and the worklog's "fixed" settles neither:

1. **Is each listed finding actually fixed?** Read the code at HEAD against the finding's
   claim; a finding is closed on evidence (the line that now does it right, or a test that
   pins it), not on the round entry.
2. **What did the fixes break?** A fix that rewrites a function drops behaviour the tests
   never pinned — a boundary row, a default, an ordering, an edge case — so walk the FR/SC the fixed code
   serves, not only the findings, and run the suite on the fix scope.

Then the Step 6 verdict: a new regression is **Not ready** even when every listed finding is
closed, and the round is appended to the worklog (*Review round N+1*: each finding confirmed
or reopened, each new finding with `file:line`). Journaled projects record one
`review-verdict` per round. The round counts toward the two-round cap in Step 6.

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

Give each the diff, the worklog (design + build plan), the PRD, and the impact map — plus
two coordinator lists: **do-not-flag** (deviations already logged and authorized in the
worklog, so reviewers don't spend findings re-litigating settled calls) and any
**pre-rulings** (items you already know are must-fix; reviewers confirm scope rather than
re-discover them).

Add the diff's **per-file risk signals** to the brief, as a compact table (path, commits,
fix%, fan-in, `risk`) rather than raw JSON, so reviewers spend their reading time on the
files most likely to regress — every changed file, since `--diff` mode does not truncate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --diff <base> --json
```

Keep that JSON's `files[].path → risk` for the `workflow` path's `fileRisk`, from the rows
whose `risk` is non-null only. When the top-level `available` or `trajectory.available` is
false (`no-git`, `shallow`, `empty-history` — the reason is `trajectory.reason`, or the top
level's), the brief says `Risk signals: unavailable (<trajectory.reason>)` in one line instead
of the table and the review runs as it always has; structure-only data (fan-in, blast) may
still be mentioned. `no-adapter` arrives in `structure.reason` and only drops the fan-in column.

For a genuinely trivial, pattern-mirroring diff (a config line, a one-file change copying
a vetted shape), the coordinator may gate directly with no reviewer subagent — say you're
doing that and record the ruling (journaled projects: a `gate-decision` event). The
independent-review requirement is for changes with judgment surface, not for every diff.

This security lens is a routine sweep, not a full audit. For changes touching auth, secrets,
or any area the project config lists as security-sensitive (default: auth, secrets, payments),
or before a release, escalate to the built-in `/security-review` for a dedicated OWASP-depth pass.

### When the config says `review: workflow`

The config's **Orchestration** section can route this fan through the `Workflow` tool
instead. Build the brief exactly as above — diff ref, worklog, PRD, impact map, do-not-flag,
pre-rulings — then Read `${CLAUDE_PLUGIN_ROOT}/skills/review/references/review-workflow.js`
and call `Workflow` with its full text as `script` (the tool accepts `scriptPath` only inside
the session's working directory, which a bundled plugin file never is; the tool result names
a persisted copy you can pass as `scriptPath` on a re-run) and `args`:

- `lenses` — 1-3 of `correctness`, `conventions+design`, `simplicity+security`. The script
  runs one finder per lens and holds the lens definitions, so scale by naming **fewer
  lenses** (a small diff gets `lenses: ['correctness']`) — unlike the `agents` path it
  cannot put all three lenses in one reviewer.
- `finderBrief` — the brief you just built, as one string. **Required**: the script throws
  before spending anything without it, because the refuters read it too.
- `doNotFlag`, `preRulings` — your two coordinator lists, one entry per string.
- `confidenceFloor` — a number 0-100, default 60; findings under it come back unverified.
- `model` — **required**, one tier below the session per `model-tiers`.
- `verify` — `'high-only'` (default), `'all'` or `'none'`. `high-only` spends refuters
  on the BLOCKER/HIGH candidates only; `all` refutes every candidate above the floor.
- `maxRefuters` — hard cap on refuter agents for the whole run, default 6. Candidates are
  taken in rank order and the script logs whatever the cap left unverified.
- `fileRisk` — optional `{path: risk}` (`low|mid|high|top`), built from the signals JSON's
  `files[].path → risk` for the rows whose `risk` is non-null (a `null` value is skipped as
  absent; any other unknown label throws). When present, findings tie-break at equal severity and confidence
  by file risk, and the refuter budget is spent severity → risk → confidence, so a capped
  run verifies the risky files first. Absent → exactly today's ordering.
- `effortVerify`, `refutersForHigh` — optional; omitted, `effortVerify` leaves the refuters on
  the tool's default effort, and `refutersForHigh` (default 2) is how many refuters a
  BLOCKER/HIGH gets. `maxRefuters` below `refutersForHigh` throws: no BLOCKER/HIGH could ever
  be verified.

The script fans the finders out and dedupes across lenses: two findings merge when they cite
the same file (compared on its last path segments, so `src/a.js` and `./src/a.js` are one
file) and either the exact same line or the same normalized summary head. A line-less finding
can therefore only merge by wording, and near-but-not-equal lines stay separate.

The picked candidates then go to refuters that must **cite the `file:line` that disproves the
claim**. The quorum is deliberately hard to reach: a BLOCKER/HIGH dies only when **both**
requested refuters report **and both** refute with evidence (at confidence ≥ 70). One dead
refuter keeps the finding alive and marks it `refuters-died`; so does an unevidenced,
uncertain or dissenting vote. Silence never kills.

It returns `{survivors, killed, belowFloor, counts, coverage, lensesRun}` — no reviewer's raw
report enters your context. `counts` carries `found`, `deduped`, `candidates` (above the
floor), `refuters` (agents actually spent), `unverified` (candidates the cap skipped),
`survivors` and `killed`. Every survivor keeps `lenses` (each lens that reported it),
`refuters` (the counted refutations, kept as recorded dissent even though they lost),
`alsoReported` (a merged duplicate's own wording, which sometimes puts it better) and two
verification fields:

- `verification` — `held` (challenged and it survived), `refuters-died` (a refuter or the
  whole verify pass never reported), `unverified-cap` (`maxRefuters` ran out before it) or
  `not-targeted` (the `verify` mode excluded it). Only `held` means an adversary looked.
- `quorum` — `"<counted>/<requested>"`, e.g. `"1/2"` when one of two refuters died. `"0/0"`
  on anything no refuter was requested for.

`coverage` totals that at run level: `{verify, refutersRequested, refutersReported,
unverified}`, where `unverified` counts the survivors that reached you unchallenged. `why`
and `fix` come back clipped to 300 chars, so read the code before acting on one. `killed`
entries carry their `quorum` and their refuters' `{reason, evidence}` once, and `belowFloor`
is one line per finding — a below-floor BLOCKER/HIGH also keeps a clipped `why` and `fix`, so
you can check it rather than guess at it.

Step 2 then runs on `survivors` (the verify pass is adversarial, not a substitute for your
own read: low-confidence high-severity survivors still get checked by you), every `killed`
entry goes under the worklog's **Rejected findings** with its refuter reason and evidence,
and the tool result's `runId` goes into `review-verdict.data.workflow_run_id`.

**What this buys, honestly.** The finders cost the same as the `Agent` fan — the workflow
buys structure, dedupe and context hygiene, not fewer tokens; and full adversarial
verification (`verify: 'all'`) is expensive, so keep it for high-stakes diffs.

**A return carrying `aborted`** means every lens finder died and the run reviewed nothing —
a clean review and a dead run must not be confused. Treat it as the degradation case below.

**Degradation.** `Workflow` unavailable in this host, or the user refuses the call → run the
`agents` path above and record a `deviation` event (journaled projects) noting the fallback.
The fan is not optional; the mechanism is.

## Step 2 — Filter and rank (the coordinator's pass)

Reviewers report **everything** they found, scored with confidence and severity — filtering
at generation time makes models silently drop real bugs, so the filter lives here instead,
as a separate pass. Consolidate by file, dedupe across lenses, then filter:

- **Keep** findings at confidence ≥ 80, and lower-confidence ones whose severity is high
  enough to be worth a check — verify those yourself (read the cited code) and either
  promote or kill them on evidence.
- **Drop** what doesn't survive scrutiny; don't pass speculative noise to the author.

On the `workflow` path this pass starts from the return's `survivors` — already deduped
across lenses, and (under the default `verify`) the BLOCKER/HIGH ones already put to refuters
that had to cite disproving evidence — so the work here is promotion, killing and ranking,
not consolidation. Every survivor whose `verification` is not `held` reached you unchallenged
(`coverage.unverified` counts them): those are yours to check.

Rejections are rulings, not silence: record what you killed and why under the worklog's
**Rejected findings** section (one line each; journaled projects fold them into the
`review-verdict` counts), so a later round doesn't re-raise or re-litigate a finding that
already lost on evidence.

Order by severity (BLOCKER → HIGH → MEDIUM → LOW). At equal severity and confidence, a
finding in a `top`-churn or `top`-fix-rate file outranks one in a `low` file — risk orders
attention, it never changes a finding's severity. The `workflow` path applies this through
`fileRisk`; on the `agents` path, apply it by hand from the brief's signal table. Every
surviving finding must carry a `file:line` and a concrete fix.

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

## Step 5 — Parity gate (ports and migrations only)

When the change ports or migrates existing behavior, one more independent pass before the
verdict: a **fresh** adversarial subagent gets the source-of-truth artifact (legacy code,
contract, flow spec), the implementation, and the worklog's **Pre-authorized deltas
(ports/migrations only)** list (see `design`), prompted to find any *unauthorized*
behavioral difference. It must
parse the whole artifact — trigger config, error paths, transactionality, timeouts,
concurrency — not just the happy path.

The coordinator arbitrates each finding: **accept as an improvement** (add it to that same
worklog section with the reasoning — journaled projects record a
`gate-decision`) or **route back to `implement`**. Silent-failure semantics in the source
(swallow-and-continue flags, bare catches) are usually bugs to fix rather than contracts
to preserve — but that's a ruling to make explicitly, never a default.

Not a port → skip this step silently.

## Step 6 — Verify, then verdict

Run the `verify` gate on the suite/build/lint for the touched code — fresh output, exit
codes, real pass counts. Then give a clear verdict:

- **Ready** — no blockers, rules satisfied, evidence attached. Safe to MR/PR/push.
- **Not ready** — list blockers; route back to `implement` (code wrong) or `design`
  (approach wrong). Don't soften a blocker into a suggestion.

**Cap the internal loop at two rounds.** Not-ready → fix → re-review is normal once; a
second round should close the gap. If blockers still stand after two rounds, surface the
open list to the user instead of looping — a review that can't converge is signalling a
design or requirements problem, not a code problem.

This phase **is** the flow's verification — one independent review plus one evidence gate.
Don't stack further self-check passes on top ("double-check once more", a second verify of
the same claims, a subagent to re-review the review): current models already self-verify
while working, and extra re-checking adds cost without catching more.

## Opening the MR/PR (on the user's go-ahead)

With no tracker/remote, stop at "Ready, evidence attached" and let the user handle pushing.
On a journaled project the verdict (or the user's publish decision) is recorded *before* the
MR/PR goes up — see **Record the outcome** below.

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

**Hand off to the MR watcher.** If the config declares an **MR watcher**: once this change's
MR/PR is open, register any review request this work is blocked on — and any follow-up work
gated on this one merging — with the watcher's watch list, using the registration command the
config names. The note must carry the held work and its next action (e.g. "unblocks #1234 —
rebase + open the request"). Say what you're registering as you do it. No watcher declared →
skip silently.

## The review-feedback cycle (after the MR/PR is open)

Reviewer comments re-enter the flow here. This is a loop between Review and Implement,
not a new phase:

1. **Read every thread** before changing anything. Some comments are questions or
   already-answered concerns — reply, don't code.
2. **Route real changes back to `implement`.** Fold them into the commits they amend if
   the repo's convention says so (e.g. fixup + autosquash) rather than stacking
   "address review" commits.
3. **Re-run the `verify` gate on the changed scope** and re-review what changed — not the
   whole MR/PR again.
4. **Push, reply in each thread** with what changed (or why you disagree), and resolve
   the threads you've addressed.
5. Hand back to the MR watcher (if declared) and wait. Merge → residual ledger triage only
   (the main Capture already ran when the review verdict landed — anything new here came
   from this feedback cycle).

Jot anything reusable from the review to the project **ledger** the moment it shows up — a
finding class that recurred across files, a convention the reviewers had to infer, a check
that would have caught the defect earlier — one dated line each (the path the config
declares, or `docs/ledger.md` when that file already exists; a project with neither gets no
new file from a review), written while ranking the findings, not recalled at Capture:

```bash
printf -- '- %s — <gotcha|style|decision>: <one line>\n' "$(date +%F)" >> docs/ledger.md
```

The Capture phase triages them (see `knowledge-base`). State plainly what you verified and
what you did not — coverage honesty is part of the review.

## Record the outcome (journaled projects)

On a project whose config declares a **Journal**, three moments here are events, each appended
when it happens: the Step 6 verdict, the MR/PR going up, and reviewer feedback landing.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type review-verdict \
  --data '{"verdict":"ready","findings":{"blocker":0,"high":1,"medium":3}}'
```

The verdict is `ready` or `not-ready` — those two spellings and no others, because the
publish gate below reads them. A review run through the `Workflow` tool sets
`review-verdict.data.workflow_run_id` to the tool result's `runId`, so the run's agent
transcripts stay reachable from the record; report its `counts` (`found`, `deduped`,
`candidates`, `refuters`, `unverified`, `survivors`, `killed`) as the finding counts rather
than recounting by hand. A run that returned `aborted` earns no verdict at all — record the
fallback `deviation` and review again. `journal.py vocab --shape <type>` prints the payload
for this and the next two events.

Then `mr-opened` {ref, url} once the MR/PR exists — the event name is historical and covers a
PR just as well — and `review-feedback` {ref, threads} each time comments arrive: counts and
references only, with the finding text and thread bodies left in the request.

**Publishing follows the record, not the momentum.** `mr-opened` is accepted only when the
stream holds, appended after its last `task-done`, either a `review-verdict` with
`verdict: ready`, or the user's own publish decision:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type gate-decision --actor user \
  --data '{"gate":"publish","question":"Open the MR now?","decision":"publish",
           "mode":"ask","raised_by":"user"}'
```

All three of `gate: publish`, `raised_by: user` and `decision: publish` — that literal
word — are required, so a flow cannot authorize its own publish by raising the gate and
answering it itself. An instruction to start the next piece of work authorizes neither route.

A missing or unreadable database is an infrastructure failure, not a reason to skip the append:
surface it loudly and continue in legacy mode only with the user's acknowledgement.
