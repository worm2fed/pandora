---
name: review
description: Pre-push review of a change, and the risk ranking that decides where to look hardest. Computes per-file regression risk for the diff from git history and the import graph (fix-rate, churn, fan-in — a ranking a read of the diff cannot produce), then runs code-reviewer subagents in parallel (coverage-first, every finding scored) as a hand-driven Agent fan or the config-selected review Workflow script with evidence-required refuters, filters and ranks findings in a separate orchestrator pass, checks CLAUDE.md compliance, verifies the acceptance criteria are demonstrably met, and runs a final verify. Use whenever the user asks to review a change before an MR/PR or push, to rank the changed files by how likely each is to regress, which files in a diff are riskiest, or where to focus review effort — even when they say "just the ranking, not a code review" — and when implementation is complete and before opening an MR/PR. Also the re-review after a round of fixes, however small the fix diff: "I've addressed the review findings F1 and F2 — good to push?", "round 2", "re-review the fix", "here's the follow-up commit", a worklog listing findings as fixed at HEAD. That pass is scoped to the fix diff (one reviewer, not the full fan) and answers two things a glance at the worklog cannot: is each listed finding actually fixed in the code, and what did the fixes break — the new bugs hide there. Not for a trivial one-line edit (a docstring, a comment) or for explaining what a diff does.
---

# Review

Review is the last gate before the change leaves your hands. The goal is to catch what
matters without burying the author in nitpicks: real bugs, drift from the agreed design,
repo-rule violations. Quality of findings over quantity.

**Standalone asks**: "rank the changed files by how likely each is to regress", "where should I
look hardest?", "not a code review, just the ranking". Here the risk table *is* the
deliverable. Do these steps:

- Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --diff <base> --json`
  (`HEAD~1` for the commit at HEAD).
- Keep the JSON's order (risk, then fixes, then commits).
- Answer with a numbered list of the changed files and one line of evidence each (fix%,
  commits, fan-in, staleness).

Dispatch no reviewers. Do not review the diff's contents unless asked.

**Re-review after a round of fixes (before the MR/PR is open)**: "I've addressed F1 and F2,
good to push?", a follow-up commit, a worklog whose *Review round N* section marks findings
fixed at HEAD. The pass is scoped to the **fix diff**, not to the whole change again. The fix
diff is HEAD against the base the previous round reviewed: the commit before the fix, unless
the round entry names another.

Scale the pass to that diff. Use one reviewer that carries all lenses. For a fix of a couple
of files, the orchestrator may do the pass alone; say which, and why. Never use the three-lens
fan. The pass answers two questions, in order, and the worklog's "fixed" settles neither:

1. **Is each listed finding actually fixed?** Read the code at HEAD against the finding's
   claim. A finding is closed on evidence, not on the round entry. Evidence is the line that
   now does it right, or a test that pins it.
2. **What did the fixes break?** A fix that rewrites a function drops behaviour the tests never
   pinned: a boundary row, a default, an ordering, an edge case. So walk the FR/SC the fixed
   code serves, not only the findings. Run the suite on the fix scope.

Then give the Step 6 verdict. A new regression is **Not ready** even when every listed finding
is closed. Append the round to the worklog as *Review round N+1*: each finding confirmed or
reopened, and each new finding with `file:line`. Journaled projects record one
`review-verdict` per round. The round counts toward the two-round cap in Step 6.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** Three signs mark a journaled
> project: a status brief headed "shipgate flow journal", a **Journal** section in the config,
> or a `.claude/shipgate.json` sidecar. On such a project the verdict is owed to a stream. The
> stream is the branch under review:
> - the checked-out branch, when it is a work branch;
> - for a commit reviewed on the integration branch, the branch that the config's
>   **Branching** pattern gives its issue. Example: `feat/455-cancel-order` for a subject
>   ending `(#455 T1)`, and `<type>/<slug>` with no issue.
>
> The integration branch (`main`, `master`, `develop`) is never a stream. If the status brief
> has no stream of that name, open it with `flow-started
> {request, branch}` in the same append as the verdict. To record nothing because the stream
> does not exist is the one wrong answer. The event owed here is `review-verdict`. Append it
> the moment Step 6 states the verdict, in that turn and before the MR/PR question. The Stop
> hook does not check it, so Step 6 is the only thing that writes it. The standalone risk
> ranking reaches no verdict and records nothing.

## Step 1 — Review in parallel, up to three lenses

This review is the flow's **independent verification**. Fresh-context reviewers catch what
your build context blinds you to. Dispatch `code-reviewer` subagents scaled to the change:
**one reviewer that carries all lenses for a small, contained diff; the full three-lens fan
only for changes where each lens has real surface**:
- **correctness**: logic, null/undefined, races, edge cases, error handling.
- **conventions + design-alignment**: matches repo patterns and the agreed design/worklog;
  flags drift from the chosen approach.
- **simplicity + security**: needless complexity / wrong abstractions, plus OWASP-class
  weaknesses and (if relevant) prompt injection.

Give each reviewer the diff, the worklog (design + build plan), the PRD and the impact map.
Also give two orchestrator lists:
- **do-not-flag**: deviations already logged and authorized in the worklog. With this list,
  reviewers don't spend findings to re-litigate settled calls.
- **pre-rulings**: items you already know are must-fix. Reviewers confirm their scope rather
  than re-discover them.

Brief reviewers with the working-tree diff (`git diff <base>`), not a commit made to give them
a stable ref. Commit after the verdict, so the review sees what will land and a fix round does
not stack commits. A commit the user asked for as its own reviewable step is the exception.

Add the diff's **per-file risk signals** to the reviewer brief as a compact table (path,
commits, fix%, fan-in, `risk`), not as raw JSON. Then reviewers spend their reading time on
the files most likely to regress. Include every changed file, since `--diff` mode does not
truncate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --diff <base> --json
```

Keep that JSON's `files[].path → risk` for the `workflow` path's `fileRisk`. Take it from the
rows whose `risk` is non-null only.

The top-level `available` or `trajectory.available` may be false (`no-git`, `shallow`,
`empty-history`; the reason is `trajectory.reason`, or the top level's). Then the brief says
`Risk signals: unavailable (<trajectory.reason>)` in one line instead of the table, and the
review runs as it always has. You may still mention structure-only data (fan-in, blast).
`no-adapter` arrives in `structure.reason` and only drops the fan-in column.

A diff may be genuinely trivial and mirror a pattern: a config line, or a one-file change that
copies a vetted shape. For such a diff the orchestrator may gate directly with no reviewer
subagent. Say that you're doing it, and record the ruling (journaled projects: a
`gate-decision` event). The independent-review requirement is for changes with judgment
surface, not for every diff.

This security lens is a routine sweep, not a full audit. Escalate to the built-in
`/security-review` for a dedicated OWASP-depth pass in two cases. The first is changes that
touch auth, secrets, or any area the project config lists as security-sensitive (default:
auth, secrets, payments). The second is before a release.

### When the config says `review: workflow`

The config's **Orchestration** section can route this fan through the `Workflow` tool
instead. Do these steps:

- Build the brief exactly as above: diff ref, worklog, PRD, impact map, do-not-flag,
  pre-rulings.
- Read `${CLAUDE_PLUGIN_ROOT}/skills/review/references/review-workflow.js`.
- Call `Workflow` with its full text as `script`, and with `args` (below). The tool accepts
  `scriptPath` only inside the session's working directory, and a bundled plugin file never
  is. The tool result names a persisted copy that you can pass as `scriptPath` on a re-run.

The `args`:

- `lenses`: 1-3 of `correctness`, `conventions+design`, `simplicity+security`. The script
  runs one finder per lens and holds the lens definitions. So scale by naming **fewer
  lenses**: a small diff gets `lenses: ['correctness']`. Unlike the `agents` path, the script
  cannot put all three lenses in one reviewer.
- `finderBrief`: the brief you just built, as one string. **Required**: without it the script
  throws before it spends anything, because the refuters read it too.
- `doNotFlag`, `preRulings`: your two orchestrator lists, one entry per string.
- `confidenceFloor`: a number 0-100, default 60. Findings under it come back unverified.
- `model`: **required**, the worker tier per `model-tiers`: one tier below the session,
  never below Opus.
- `verify`: `'high-only'` (default), `'all'` or `'none'`. `high-only` spends refuters on the
  BLOCKER/HIGH candidates only. `all` refutes every candidate above the floor.
- `maxRefuters`: hard cap on refuter agents for the whole run, default 6. The script takes
  candidates in rank order and logs whatever the cap left unverified.
- `fileRisk`: optional `{path: risk}` (`low|mid|high|top`). Build it from the signals JSON's
  `files[].path → risk` for the rows whose `risk` is non-null. The script skips a `null` value
  as absent; any other unknown label throws. When `fileRisk` is present, findings at equal
  severity and confidence tie-break by file risk. The refuter budget is then spent severity →
  risk → confidence, so a capped run verifies the risky files first. Absent → exactly today's
  ordering.
- `effortVerify`, `refutersForHigh`: optional. If you omit `effortVerify`, the refuters stay
  on the tool's default effort. `refutersForHigh` (default 2) is how many refuters a
  BLOCKER/HIGH gets. `maxRefuters` below `refutersForHigh` throws: no BLOCKER/HIGH could ever
  be verified.

The script fans the finders out and dedupes across lenses. Two findings merge when they cite
the same file and either the exact same line or the same normalized summary head. The script
compares files on their last path segments, so `src/a.js` and `./src/a.js` are one file. A
line-less finding can therefore merge only by wording, and near-but-not-equal lines stay
separate.

The script then sends the picked candidates to refuters. A refuter must **cite the
`file:line` that disproves the claim**. The quorum is deliberately hard to reach. A
BLOCKER/HIGH dies only when **both** requested refuters report **and both** refute with
evidence (at confidence ≥ 70). One dead refuter keeps the finding alive and marks it
`refuters-died`. An unevidenced, uncertain or dissenting vote does the same. Silence never
kills.

The script returns `{survivors, killed, belowFloor, counts, coverage, lensesRun}`. No
reviewer's raw report enters your context.

`counts` carries `found`, `deduped`, `candidates` (above the floor), `refuters` (agents
actually spent), `unverified` (candidates the cap skipped), `survivors` and `killed`.

Every survivor keeps these fields:
- `lenses`: each lens that reported it.
- `refuters`: the counted refutations, kept as recorded dissent even though they lost.
- `alsoReported`: a merged duplicate's own wording, which sometimes puts it better.
- `verification`: `held` (challenged and it survived), `refuters-died` (a refuter or the
  whole verify pass never reported), `unverified-cap` (`maxRefuters` ran out before it) or
  `not-targeted` (the `verify` mode excluded it). Only `held` means an adversary looked.
- `quorum`: `"<counted>/<requested>"`, e.g. `"1/2"` when one of two refuters died. `"0/0"`
  on anything no refuter was requested for.

`coverage` totals that at run level: `{verify, refutersRequested, refutersReported,
unverified}`, where `unverified` counts the survivors that reached you unchallenged. `why`
and `fix` come back clipped to 300 chars, so read the code before you act on one.
`killed` entries carry their `quorum` and their refuters' `{reason, evidence}` once.
`belowFloor` is one line per finding. A below-floor BLOCKER/HIGH also keeps a clipped `why`
and `fix`, so you can check it rather than guess at it.

Then do these steps:
- Run Step 2 on `survivors`. The verify pass is adversarial, but it does not replace your own
  read: you still check low-confidence high-severity survivors.
- Put every `killed` entry under the worklog's **Rejected findings** with its refuter reason
  and evidence.
- Put the tool result's `runId` into `review-verdict.data.workflow_run_id`.

**What this buys, honestly.** The finders cost the same as the `Agent` fan. The workflow buys
structure, dedupe and context hygiene, not fewer tokens. Full adversarial verification
(`verify: 'all'`) is expensive, so keep it for high-stakes diffs.

**A return carrying `aborted`** means every lens finder died and the run reviewed nothing. Do
not confuse a clean review with a dead run. Treat it as the degradation case below.

**Degradation.** If `Workflow` is unavailable in this harness, or the user refuses the call,
run the `agents` path above. Record a `deviation` event (journaled projects) that notes the
fallback. The fan is not optional; the mechanism is.

## Step 2 — Filter and rank (the orchestrator's pass)

> **Writing for people.** A report a person reads follows the STE-80 principles: sentences of
> about 20 words with one idea each, common words, one term per concept, the same term every
> time, one action per step, active voice, no clause chains joined by dashes or parentheses.
> Shorter sentences, not fewer facts: every file:line, severity, confidence, failure scenario,
> command, exit code, count and verdict the report carried stays in it. Code, commands and
> error text go in fenced blocks, not in prose.

Reviewers report **everything** they found, scored with confidence and severity. Filtering at
generation time makes models silently drop real bugs. So the filter lives here instead, as a
separate pass. Consolidate by file, dedupe across lenses, then filter:

- **Keep** findings at confidence ≥ 80. Also keep lower-confidence ones whose severity is high
  enough to be worth a check. Verify those yourself (read the cited code), then promote or
  kill each one on evidence.
- **Drop** what doesn't survive scrutiny. Don't pass speculative noise to the author.

On the `workflow` path this pass starts from the return's `survivors`. They are already
deduped across lenses. Under the default `verify`, the BLOCKER/HIGH ones already went to
refuters that had to cite disproving evidence. So the work here is promotion, killing and
ranking, not consolidation. Every survivor whose `verification` is not `held` reached you
unchallenged (`coverage.unverified` counts them). You must check those.

Rejections are rulings, not silence. Record what you killed and why under the worklog's
**Rejected findings** section, one line each. Journaled projects fold them into the
`review-verdict` counts. Then a later round doesn't re-raise or re-litigate a finding that
already lost on evidence.

Order by severity (BLOCKER → HIGH → MEDIUM → LOW). At equal severity and confidence, a
finding in a `top`-churn or `top`-fix-rate file outranks one in a `low` file. Risk orders
attention; it never changes a finding's severity. The `workflow` path applies this through
`fileRisk`. On the `agents` path, apply it by hand from the brief's signal table. Every
surviving finding must carry a `file:line` and a concrete fix.

## Step 3 — Repo-rule & design compliance

Independently confirm that the change honors the rules the impact map flagged. Pull these
from CLAUDE.md / the impact map, not from memory. The repo-specific ones below are conditional
examples: apply only those that the repo's CLAUDE.md actually declares.

- New logic landed in the **right place** per the repo's routing rules.
- Schema change → any downstream refresh obligations the CLAUDE.md names (e.g. dump
  refreshes) done.
- New feature flag → registered wherever the repo's flag conventions require.
- Write path didn't get **forked**; cut-over is deliberate.
- Public/external API change → parallel-change + deprecation, not a hard break.
- Tests cover the changed behavior; FR-### / SC-### are satisfied.

## Step 4 — Acceptance-criteria check (the issue's, not just the tasks)

"My build-plan tasks are all checked" is **not** the same as "the issue's acceptance criteria
are met". You can finish exactly the code you planned and still leave an AC unsatisfied.

So before the verdict, pull the **acceptance criteria from the issue**. Take them from wherever
the config's **Forge & tracker** section says ACs live (default: the issue description). Walk
them one by one. If there's no tracked issue, the PRD's SC-### *are* the acceptance criteria.

For each criterion, point to the **concrete evidence** that it's satisfied: a test, a manual
walkthrough, a screenshot. An assertion that it "should" be satisfied is not evidence. Any
criterion you can't demonstrate is **unfinished work on this issue**, not a follow-up: route
back to `implement`. The issue earns a Ready verdict only when *every* AC is demonstrably met.
(This applies to every issue, child issue or standalone.)

## Step 5 — Parity gate (ports and migrations only)

When the change ports or migrates existing behavior, run one more independent pass before the
verdict. A **fresh** adversarial subagent gets three inputs:
- the source-of-truth artifact (legacy code, contract, flow spec);
- the implementation;
- the worklog's **Pre-authorized deltas (ports/migrations only)** list (see `design`).

Its prompt tells it to find any *unauthorized* behavioral difference. It must parse the whole
artifact, not just the happy path: trigger config, error paths, transactionality, timeouts,
concurrency.

The orchestrator arbitrates each finding in one of two ways:
- **accept as an improvement**: add it to that same worklog section with the reasoning
  (journaled projects record a `gate-decision`);
- **route back to `implement`**.

Silent-failure semantics in the source (swallow-and-continue flags, bare catches) are usually
bugs to fix rather than contracts to preserve. But that is a ruling to make explicitly, never
a default.

Not a port → skip this step silently.

## Step 6 — Verify, then verdict

Run the `verify` gate on the suite/build/lint for the touched code: fresh output, exit codes,
real pass counts. Then give a clear verdict:

- **Ready**: no blockers, rules satisfied, evidence attached. Safe to MR/PR/push.
- **Not ready**: list blockers. Route back to `implement` (code wrong) or `design` (approach
  wrong). Don't soften a blocker into a suggestion.

**Journaled: append `review-verdict` as you state the verdict.** The form is under **Record the
outcome**. Do it in the same turn, before the MR/PR question, for Ready and Not ready alike. A
verdict delivered without the event leaves the stream saying the review never happened.

**Cap the internal loop at two rounds.** Not-ready → fix → re-review is normal once. A second
round should close the gap. If blockers still stand after two rounds, surface the open list
to the user instead of looping. A review that can't converge signals a design or requirements
problem, not a code problem.

This phase **is** the flow's verification: one independent review plus one verify gate. Don't
stack further self-check passes on top ("double-check once more", a second verify of the same
claims, a subagent to re-review the review). Current models already self-verify while working,
and extra re-checking adds cost without catching more.

## Opening the MR/PR (on the user's go-ahead)

The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to
the worklog's round entries and Rejected findings, ledger lines, the MR/PR body and every
reply in the review-feedback cycle; absent, a placeholder, or `plain`, write them as before.

With no tracker/remote, stop at "Ready, evidence attached" and let the user handle pushing.
On a journaled project the verdict (or the user's publish decision) is recorded *before* the
MR/PR goes up. See **Record the outcome** below.

**Use the canonical template. Don't invent a body.** If the config's **Forge & tracker**
section names a template (its location + the exact command to fetch it), read it from there.
It may live in a different repo than the code, and it changes, so the config/repo is the source
of truth. With no config, fall back to the repo's own template
(`.github/PULL_REQUEST_TEMPLATE.md` / `.gitlab/merge_request_templates/default.md`) or the
forge default (**Summary / Trade-offs & risks / Verification**). Either way, fill it from what
this flow already produced. You don't reverse-engineer any of it:
- **Summary** ← the PRD / worklog (what changed and why).
- **Trade-offs / risks** ← the impact map (data obligations, write-path, flags, public API).
  Write "none" only if there genuinely are none.
- **Verification** ← the `verify`-gate evidence. Tick "tests added/passing", "behind flag",
  etc. only for lines that are actually true.

Match the body's length to what a reviewer needs. Cover the substance, with no filler sections
and no restating of the diff. The same goes for every written deliverable this flow produces.

**Link the issue.** Use the issue-link form the config declares. Cross-repo issues need the
project-qualified form, e.g. `group/project#NNNN`, since a bare `#NNNN` resolves to a
non-existent same-repo issue. Default: the forge's native `#NNNN` / `Closes #NNNN`. Honor any
extra title/body rules the config declares.

**Hand off to the MR watcher.** This applies if the config declares an **MR watcher**. Once
this change's MR/PR is open, register two kinds of work with the watcher's watch list, using
the registration command the config names:
- any review request this work is blocked on;
- any follow-up work gated on this one merging.

The note must carry the held work and its next action (e.g. "unblocks #1234 — rebase + open
the request"). Say what you're registering as you do it. No watcher declared → skip silently.

## The review-feedback cycle (after the MR/PR is open)

Reviewer comments re-enter the flow here. This is a loop between Review and Implement, not a
new phase:

1. **Read every thread** before you change anything. Some comments are questions or
   already-answered concerns. Reply to those; don't code.
2. **Route real changes back to `implement`.** If the repo's convention says so (e.g. fixup +
   autosquash), fold them into the commits they amend. Don't stack "address review" commits.
3. **Re-run the `verify` gate on the changed scope** and re-review what changed. Don't
   re-review the whole MR/PR again.
4. **Push, reply in each thread** with what changed (or why you disagree), and resolve the
   threads you've addressed.
5. Hand back to the MR watcher (if declared) and wait. On merge, do residual ledger triage
   only. The main Capture already ran when the review verdict landed, so anything new here
   came from this feedback cycle.

**When a finding is disputed**, by the user before the push or by a reviewer in a thread,
**steel-man** first. State the strongest case for their position: the real concern it
answers. Then hold or concede against *that*. A finding that survives the strong version
stays. A finding that only beat the weak version is withdrawn, and the reply says which.
Settled facts (a failing test, a security anti-pattern, a violated requirement) are corrected,
not debated.

Jot anything reusable from the review to the project **ledger** the moment it shows up.
Examples: a finding class that recurred across files, a convention the reviewers had to infer,
a check that would have caught the defect earlier. Write one dated line each, while you rank
the findings, not recalled at Capture. The ledger path is the one the config declares, or
`docs/ledger.md` when that file already exists. A project with neither gets no new file from a
review:

```bash
printf -- '- %s — <gotcha|style|decision>: <one line>\n' "$(date +%F)" >> docs/ledger.md
```

The Capture phase triages them (see `knowledge-base`). State plainly what you verified and
what you did not. Coverage honesty is part of the review.

## Record the outcome (journaled projects)

On a project whose config declares a **Journal**, three moments here are events. Append each
one when it happens:
- the Step 6 verdict, as it is stated, not after the MR/PR question;
- the MR/PR going up;
- reviewer feedback landing.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type review-verdict \
  --data '{"verdict":"ready","findings":{"blocker":0,"high":1,"medium":3}}'
```

The stream may not exist yet (a commit reviewed on the integration branch). Then opening it
and recording the verdict is one `--batch` (JSONL on stdin; stdin form: see `verify`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream <type>/<issue>-<slug> --batch <<'EOF'
{"type":"flow-started","data":{"request":"<the change, one line>","branch":"<type>/<issue>-<slug>"}}
{"type":"review-verdict","data":{"verdict":"not-ready","findings":{"blocker":1,"high":0,"medium":2}}}
EOF
```

The verdict is `ready` or `not-ready`. Use those two spellings and no others, because the
publish gate below reads them.

A review run through the `Workflow` tool sets `review-verdict.data.workflow_run_id` to the
tool result's `runId`. Then the run's agent transcripts stay reachable from the record. Report
its `counts` (`found`, `deduped`, `candidates`, `refuters`, `unverified`, `survivors`,
`killed`) as the finding counts; don't recount by hand. A run that returned `aborted` earns no
verdict at all. Record the fallback `deviation` and review again.
`journal.py vocab --shape <type>` prints the payload for this and the next two events.

Then append `mr-opened` {ref, url} once the MR/PR exists. The event name is historical and
covers a PR just as well. Append `review-feedback` {ref, threads} each time comments arrive.
It holds counts and references only; the finding text and thread bodies stay in the request.

**Publishing follows the record, not the momentum.** The journal accepts `mr-opened` only when
the stream holds one of two events, appended after its last `task-done`: a `review-verdict`
with `verdict: ready`, or the user's own publish decision:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type gate-decision --actor user \
  --data '{"gate":"publish","question":"Open the MR/PR now?","decision":"publish",
           "mode":"ask","raised_by":"user"}'
```

All three of `gate: publish`, `raised_by: user` and `decision: publish` (that literal word)
are required. So a flow cannot authorize its own publish by raising the gate and answering it
itself. An instruction to start the next piece of work authorizes neither route.

A missing or unreadable database is an infrastructure failure, not a reason to skip the
append. Surface it loudly. Continue un-journaled only with the user's acknowledgement.
