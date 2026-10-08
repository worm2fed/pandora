# Changelog

All notable changes to the **shipgate** plugin, newest first.

v0.14.7 — the session-start brief leads with the stream this session drives. The SessionStart
hook asked `status` by branch only, so after a compaction or a resume a session driving a
stream with no branch (an epic's planning stream) got the checkout's stream first, and in an
umbrella possibly another session's. The hook now also passes `--session=<session_id>` from its
payload (0.14.5's flag) — one token, and only for a plain id (letters, digits, `.`, `_`, `-`, at
most 128), so an absent or odd id costs the ordering hint, never the brief. The brief marks that
stream `· this session`. A session that has written nothing yet (a fresh start, `/clear`) gets
the branch ordering as before. Four tests.

v0.14.6 — an explorer can read a ref that is not checked out. `code-explorer` had Glob, Grep
and Read only, so a lens that had to read `origin/<integration>` — a staleness check of a
dormant design against what merged since — or a file's history could not, and the explore
workflow (which dispatches `shipgate:code-explorer`) had to be re-run by hand with other agents.
The agent now has `Bash`, limited by its prompt to read-only git (`git show <ref>:<path>`,
`log`, `diff`, `grep`, `blame`, `ls-tree`): never fetch, checkout, switch, reset, stash, commit
or a worktree, and a ref that does not resolve is reported, not fetched. The `feature` skill
tells the orchestrator to fetch before dispatch and to name the ref in the lens prompt — the
same tool set `code-reviewer` already has. One contract test pins it.

v0.14.5 — parallel sessions keep their own events, and status knows each session's stream.
`append` labelled an unlabelled actor with `meta.current_session`, which every session start
overwrites, so with two sessions open on one project the later starter's id labelled the
other's events. The label now comes from `CLAUDE_CODE_SESSION_ID` in the appending shell (a
subagent's carries its parent's), with `meta.current_session` as the fallback (ADR 0005,
amending 0003). `status --session ID` marks the live stream that session last wrote to itself
(`session_match`; hook-written events do not count, a finished stream releases it) and renders
it first, in full, ahead of the branch's — the call shipgate-hud 0.2.4 makes. The test helpers
drop the variable from the environment they hand to journal.py and the hooks, so the suite
gives the same result inside and outside a Claude Code shell. Prompted by a session planning
an epic (a stream with no branch) whose HUD showed another session's stream instead.

v0.14.4 — a stream checked out in a git worktree is found. The SessionStart hook's nested-repo
scan (0.14.3) skipped dot-directories and looked one level down only, so a branch checked out
in a worktree under `.worktrees/` — where the `workspace` skill puts one, beside the repos or
inside one — never reached `--nested-branch`, and the brief lost its ordering for exactly the
work in progress. The scan now looks into each parent's and each nested repo's `.worktrees/`
(a repo, then its own worktrees, then the parent's); a directory's worktrees are read only
when it is a repo itself. Same caps and reads as before. One test extended. The `workspace`
skill now says where a worktree goes (`.worktrees/<slug>` inside the target repo, the command
run from there — where the hook and the HUD look), that started work is never
moved into or out of a worktree without the same confirmation a new branch gets and a
`deviation` event naming the new path, and that the `phase-entered workspace` note carries the
worktree path in `refs`. Prompted by a session that moved an issue's branch into a worktree late
in the flow, unrecorded, leaving the HUD and the brief with no position for the live work.

v0.14.3 — the status brief keeps its checked-out-first ordering in an umbrella. The
SessionStart hook took the branch from `git rev-parse` in the session directory only, so in
an umbrella checkout (a plain folder, or a repo of its own on an integration branch, with
the real repos one level down) it passed no branch, or one that names no stream, and the
brief listed every stream unsorted. The hook now also collects the branch of each nested
repo (`*/`, `source/*`, `packages/*`; dot-directories, `node_modules` and symlinked entries
skipped, at most 64 repos) by reading its `.git/HEAD` — a `gitdir:` file is followed once
and only within the session directory, a detached HEAD names nothing, no subprocess per
repo — and passes them as `--nested-branch=<name>`. A checkout is untrusted content, so the
read is non-blocking and refuses anything but a regular file (a FIFO at `HEAD` cannot hang
the session), and a name with a NUL or a control character is dropped rather than aborting
the hook and losing the brief.
`journal.py status` gained that repeatable flag: tried only when `--branch` names no
stream, and among the matches the most recently active stream wins, so a dormant stream
on another nested repo's branch cannot shadow the live one. Hooks hold no policy: which
branch orders the brief stays the journal's call. Ten tests added.

v0.14.2 — umbrella roots that are not git repos. An umbrella is a scaffolding directory with
the real repos nested beneath it; `setup` writes the config, sidecar and journal at its root,
and that root is often a plain folder, not a repo of its own. Three places assumed a git repo:
`signals.py` read the umbrella's `## Code signals` only when the parent was a git work tree,
so a plain-folder umbrella's `Exclude` had no effect inside a nested repo — it now also treats
a parent (or an ancestor up to the parent's own git toplevel, for `source/<service>` layouts)
holding the setup sidecar `.claude/shipgate.json` as the umbrella; a plain parent with neither
is still not read. `setup`'s Step 1 told the model to stop when the directory is not a git
repo, which contradicted its own umbrella bullet — it now checks for nested repos first and
stops only when there are none. `workspace` described an umbrella as always being a git repo
of its own; it now says either form, detected by the nested repos. Two tests added.

v0.14.1 — one term per concept. A terminology audit of every file the model reads (skills,
agents, the command, README, config template, the user-facing strings of the hooks and scripts)
found the same concept under several names — "working doc" beside "worklog", "coordinator" and
"master session" beside "orchestrator", "legacy mode" beside "un-journaled", "session brief"
and "position brief" for the `status` output — and a few words carrying two concepts
("capture" for both the phase and the hooks' artifact recording, "brief" for both the status
brief and a subagent's instructions, "lens" unqualified). Prose now uses one canonical term per
concept, preferring the contract name where one exists (`worklog`, actor roles `orchestrator`
and `worker`, hook event names), and the new `docs/glossary.md` records each term, its
definition and what it is not to be confused with. Contract names — journal events and fields,
CLI flags, config keys, sidecar fields, file names — are unchanged. Four printed strings
changed wording only (`status` with no streams, two `--help` lines, the `vocab` line for
`design-queued`); the hooks were audited and left unchanged. No behaviour change. The full
69-case eval suite re-run at 3 runs per arm: mean with-arm score 0.976 vs 0.972 at baseline, mean delta
+0.095 vs +0.080; no case lost more than judge noise except 46, whose fixture carries a "revisit
2026-10-05" date and now fails identically in both arms (a dated fixture, logged for repair).

v0.14.0 — thinking lenses inlined into the phase skills. A standalone thinking-skills plugin lists
39 skills; the session's skill listing has a budget of roughly 1% of context, so most of those
descriptions are truncated and the skills never fire (in the maintainer's usage, only the 4 whose
descriptions survived ever triggered). shipgate already carried the lenses that matter inline —
design: reversibility, pre-mortem; structured-debug: occam's-razor, kepner-tregoe, five-whys-plus;
code-reviewer: red-team / inversion; clarify: jobs-to-be-done via the config's **Thinking lenses**
hook — where they fire deterministically at the right phase and cost nothing in the listing. This
release absorbs the remaining engineering-flow lenses the same way, each as a bullet or short
paragraph in the existing voice with the condition under which it applies, condensed from the
original `SKILL.md` texts of
[cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills) (MIT, © 2025 TJ Boudreaux
— credited in the new `NOTICE` and in the README): `design` gains steel-manning (the runner-up
blueprint's strongest case before the recommendation — doubly when the runner-up is the user's own
preference), second-order ("and then what?" at the next request / next deploy / 10× horizons,
stopping at the first effect that changes the decision), via-negativa (does the problem go away by
removing something, asked of every blueprint), TRIZ (two requirements that seem mutually exclusive
are separated in time, space, condition or level rather than compromised) and margin-of-safety (a
timeout, limit or capacity is sized to the cost of being wrong, after measuring);
`structured-debug` gains map-territory (behaviour contradicts a doc, test or comment → read and
run the path that actually runs; the territory wins), OODA (an incident under time pressure →
propose a reversible stabilizing move at ~70% confidence for the go-ahead, re-observe, then root
cause) and systems (a fix here breaks something there → map components, feedback loops and
delays); `feature` scales ceremony by Cynefin as well as size (clear / complicated / complex →
spike before the PRD / chaotic → stabilize first); `clarify` runs first-principles on constraints
stated as fixed (physics, cost, regulation — or convention?); `implement`'s stop rules gain
sunk-cost (from the debiasing skill's self-check: the same approach failed twice → stop, re-plan)
and bounded-rationality (an open-ended search gets a stated "good enough" — never a correctness
gate); `review` steel-mans a disputed finding before holding or conceding; `knowledge-base`
reports an empty recall as empty instead of filling the gap (circle of competence). via-negativa
and first-principles already sit in `code-architect` as per-philosophy lenses; the
coordinator-level via-negativa line stays because the coordinator, not one architect, commits
across all three blueprints, and first-principles lands in clarify where constraints are decided.
Out of scope, by design: regret-minimization, effectuation, archetypes, leverage-points,
feedback-loops, lindy, fermi, probabilistic, opportunity-cost, thought-experiment and the
model-router / selection / combination skills — not engineering-flow lenses. **Body-only**: no
skill's frontmatter changed (verified byte-for-byte against the previous release — descriptions
are the triggering surface the evals measure). File size deltas: design +1,678 B (+15.5%),
structured-debug +1,045 (+7.2%), feature +667 (+3.5%), implement +621 (+6.2%), review +467
(+1.8%), clarify +321 (+3.9%), knowledge-base +302 (+2.7%); 5,101 B in total. Two eval cases cover
the lenses most likely to change behaviour: **68-design-steel-man** (the clarified billing PRD
from 51–57, with the user arriving set on synchronous in-request rendering; pass = the answer
builds and answers the strongest case for the queue / stored-file alternative rather than agreeing
by reflex) and **69-debug-map-territory** (README, docstring and a green test all describe
discount-before-tax and are right about `pricing.quote()`, which the live `checkout.charge_total`
stopped calling in a "one pass" perf commit that re-implements the arithmetic inline and scales
the discount back out of the taxed gross, so only the pre-tax 10.00 comes off the taxed 120.00 —
110.00 instead of 108.00 (order alone would not matter; the scale-back line is the defect); pass =
the answer names the live path, says what the green test does and does not cover, shows a repro
and names the perf commit). On the harness (3 runs, with/without, Opus, judged by Sonnet): 68
scores 0.67 with / 0.44 without (+0.22), the skill firing 3/3 and all three with-arm transcripts
building the alternative's case explicitly ("I looked for the strongest argument for a worker",
"the best argument for a worker plus stored files") and answering it point by point, against none
of the three bare-model runs; the `strongest-case-stated` regex grader splits 2/3 vs 0/3 (the miss
says "best argument", which the regex does not list — left as is rather than widened to the
transcript), while the five-claim Sonnet rubric passed only 1 of the 3 with-runs and is read as
the noisier of the two. 69 is a ceiling case like 01 — 1.00 / 1.00, both arms find the live path,
the skill firing 3/3 and taking 7–8 turns to the bare model's 4 for the same verdict; it stays as
regression coverage for the lens. Case 68's first rubric failed the two with-runs that visibly
steel-manned because two claims demanded the steel-man precede the words "I agree"; both ordering
nits were dropped (grade presence and engagement, not sentence order) and the case re-run; case
69's first rubric misdescribed its own defect as "wrong order" (percentage tax and discount
commute — the scale-back line is the bug) and was corrected and re-run before recording. The
`thinking-skills` row leaves the README's integrations table: recommending a 39-skill plugin
pushes a user's skill listing past its budget, which is what truncated the descriptions in the
first place. The **Thinking lenses** config section stays as the generic override hook — map a
phase to a lens *skill* when one is worth its listing space — and its docs name cc-thinking-skills
once as an example source.

v0.13.6 — phase skills record their journal events. The large journaled fixture (evals 58–67:
a monorepo with 44 commits, 12 ADRs, a config with a Journal section, sidecar and a database
seeded with three streams) showed the skills firing on 8 of 9 fire cases while appending a phase
event in 2 — `review-verdict` on the re-review and `clarify-passed` — and nothing from
`structured-debug` (58, 59), `route-and-map` (60, 61), `review` (62) or `design` (66), the same
shape the production journal has worn for weeks (a handful of `debug-root-cause` rows across
dozens of bug fixes, phases "done inline", capture from memory). Every skill carried a *Record …
(journaled projects)* section with the exact command, so the traces were read rather than the
sections rewritten blind, and they named a different defect from the one assumed: the agent did
not forget the append, it **declined it for want of a stream**. Each fixture checks out the
integration branch and seeds streams only for earlier issues, which is also how real work
arrives — a bug reported on `main`, a routing question before any branch, a commit at HEAD
reviewed before the PR — and the three misses said so in their answers ("there's no branch or
issue for this work yet", "no journal stream for #455, so I didn't record a verdict rather than
make up a stream name"); the fourth deferred `design-committed` until the user approved an
escalated migration. The two runs that did append had a pre-seeded stream for their issue. Two
mechanical faults sat underneath: `route-and-map`'s quoted `phase-entered` is refused on any
stream that never entered `workspace` (`append` rejects a forward jump without `skipped`, and
`workspace` appended only `flow-started`, which sets no phase), and the orchestrator promised the
Stop hook would catch a missing semantic event when `journal.py check` gates only `task-done`,
`verify-run` and clarify's `gate-decision` — none of the phase events. Fixes, all in skill
bodies: each phase skill (`structured-debug`, `route-and-map`, `review`, `design`, `clarify`)
opens with a *journaled project — name the stream before you start* pre-flight (the stream is the
branch the work takes per the config's Branching pattern, whether or not that branch exists;
the integration branch is never a stream; no stream in the brief → open it with `flow-started` in
the same append as the first event; the event the phase owes, and the step that writes it); the
append moves into the workflow step where the fact exists — `bug-reproduced` at reproduce,
`debug-root-cause` at root cause before the ledger jot, `phase-entered` as the map is emitted
rather than after the user confirms it, `review-verdict` as the verdict is stated and before the
MR/PR question, `design-committed` as the worklog lands with an `open` list for ADRs still
awaiting the user — and the record sections become the reference form plus the `--batch` that
opens a stream and records into it in one call; `route-and-map`'s example carries
`"skipped":["workspace"]` and says why, its standalone blast-radius note no longer says "do not
journal" (that answer starts no flow; the routing ask for new work does); `workspace` records
`flow-started` and `phase-entered workspace` as one batch and continues on a stream a phase
skill opened earlier instead of starting a second; the orchestrator gains the stream rule and
states what the Stop hook actually checks. On the harness (3 runs, with/without, Opus, judged by
Sonnet): `journal-phase-event-appended` passes 3/3 with-runs on 58, 60, 62 and 66 (was 0/1 in the
pilot on each), no invented type names, every with-run opening a pattern-named stream
(`fix/<slug>`, `feat/<slug>`, `feat/455-cancel-order`); with-arm scores 0.93 / 1.00 / 1.00 / 1.00
against baselines of 0.83 / 0.90 / 0.90 / 0.92 (58's one miss is a judge FAIL on an answer that
names the commit, the line and the rounding-mode change and ends with a proposal); 67 (a one-line
config change) still makes no journal write, 3/3 both arms, 1.00. No script or hook changed; the
Stop-hook gap on phase events is recorded here as a known limit, not papered over in the prose.

v0.13.5 — `review` on the re-review after a round of fixes. Eval 47 (the review suite's
after-fixes case: a worklog whose *Review round 1* section lists F1 and F2 as fixed at HEAD, a fix
commit that closes both and quietly drops the export's header row, and the ask "I've addressed
the round-1 review findings F1 and F2 (see the worklog); the fix is the commit at HEAD. Good to
push?") showed the skill never firing — 0 of 3 with-arm runs, against 9 of 9 on "Review the
change at HEAD before I open the PR" (44–46) — and the traces show why: the model reads the
two-file fix diff itself from the first turn, the ask being one it believes it can answer
unaided. The description's triggers ("review a change before an MR/PR or push", the risk
ranking, "implementation is complete") never named this shape, which is the one that bites on
real work: the fixes land, the new diff gets no pass, and that is where the next finding lives.
The description now carries the re-review from the user's side ("I've addressed the review
findings F1 and F2 — good to push?", "round 2", "re-review the fix", "the follow-up commit", a
worklog listing findings as fixed at HEAD), says the size of the fix diff does not matter, and
promises the two things a glance at the worklog cannot settle — whether each listed finding is
actually fixed in the code, and what the fixes broke; its negative trigger now also names a
docstring or comment edit and explaining what a diff does. The body gains a *Re-review after a
round of fixes* section beside the standalone-asks note: scope the pass to the fix diff (HEAD
against the base the previous round reviewed), scale it to that diff (one reviewer carrying all
lenses, or the coordinator alone for a couple of files — never the three-lens fan), confirm
each finding on evidence, then hunt the regressions the fixes introduced through the FR/SC the
fixed code serves, append *Review round N+1* to the worklog, and give the Step 6 verdict — a new
regression is Not ready however many findings closed; one `review-verdict` per round, counted
toward the two-round cap. On the harness (3 runs, with/without, Opus): 47 fires 3/3 (was 0/3) with
no reviewer agent dispatched in any run (the coordinator reviews the two-file fix diff itself and
says so), scoring 0.90 and 1.00 over two trees (the one with-arm miss is a judge FAIL on an answer that confirms F1 and F2, names the dropped header at a file:line and says Not ready — within the judge's noise); 44 and 46 fire 3/3 and score 1.00 / 1.00 (baseline 0.90 / ~1.0); the
negatives 49 and 50 stay silent 0/3 with zero Agent calls and score 1.00. The with-arm cost of a
47 run is about 1.8× the bare model's and ~15 s longer, the price of the worklog round entry and
the scoped verify, not of a fan. No script or hook changed.

v0.13.4 — mid-flow ledger jots. Eval 43 (the knowledge-base suite's implicit-jot case: a
failing test whose cause is SQLite's off-by-default foreign-key enforcement, the user's go-ahead
to fix, and a `docs/ledger.md` already in the repo) showed the plugin writing the dated ledger
line in 1 of 3 runs, the bare model in 0 of 3 — the same shape the flow journal shows on a
production project, where Capture keeps finding an empty ledger and promoting "learnings" from
end-of-flow memory. The flow that runs is `structured-debug`, and its only ledger instruction was
one sentence at the end of the Validate section, after the fix, with no trigger moment, no format
and no command; `implement` (step 7) and `review` carried the same aside. Each now has the jot as
a positioned step with the append inline, so it costs one tool call and no skill load:
`structured-debug` step 5, between the confirmed root cause and the fix plan — if the cause is a
reusable trap (a default that silently disables a feature, a command or log line that lies, a
test that passes vacuously) append one dated line now; `implement` at the task tick; `review`
while ranking findings. `knowledge-base`'s ledger section names those moments and the line
format. Two rules came out of the measurement rather than the design. The jot goes only into a
ledger the project already has (the config-declared path, or an existing `docs/ledger.md`): the
first draft created the file when absent, and on the structured-debug fixtures, which have none,
the announced new file cost the "proposal, not an applied fix" judge claim (01 → 0.89, 03 →
0.71). And the `knowledge-base` description is unchanged, because skill selection happens when
the ask arrives and a confirmed root cause is not an ask. On the harness (3 runs, with/without;
two trees for 43 on the final wording): 43 jots 5/6 (was 1/3) with the fix applied 6/6 and
`CLAUDE.md` clean 6/6; 38 1.00; 41 and 42 1.00 and silent with no files written; structured-debug
01 1.00, 02 0.78 / 0.89 (baseline 0.89 / 1.00 — the misses are the credit-note coverage claim,
no ledger involved), 03 0.90 (baseline 1.00). No script or hook changed.

v0.13.3 — `verify` on natural completion asks. Evals 22–28 (the verify suite) showed the skill
never fired: 0 of 15 with-arm runs on ordinary asks that end in a status the user acts on ("fix
whatever fails and confirm we're good to go", "rename X and tell me when it's done", "confirm the
suite still passes", "get lint and tests green, then tell me"). The description was phrased from
the model's side ("use whenever about to claim success") and never matched the moment — skill
selection happens when the ask arrives, not when the claim is being written. It is rewritten the
way the phase skills that do fire are, and trigger-first: it opens with the asks themselves, from
the user's side (a task ending in done / fixed / green / good to go / confirm); names a pasted
test run or CI result in the ask as a trigger on its own, since that output describes the code
before the edit; says outright that the size of the change does not matter (a one-line edit plus
"confirm the tests still pass" is the canonical case); then lists what the skill adds — the
checklist of ways a green report lies (proving run before the last edit, 0 tests discovered,
stale pasted output, several claims in one report, hedged wording) and the gate; and carries
negative triggers for explaining code, a one-shot "run X and tell me the result", and
re-verifying a claim already settled in the same state. The body's "evidence, not repetition"
rule now also says a green proving run is followed by the report, not by ad-hoc spot checks.
On the harness (3 runs, with/without, Opus): the skill fires 3/3 on cases 22, 23, 25 and 26 and 4/6 on 24 (two trees), from 0/15 at baseline; the negatives stay silent with their command counts unchanged (27 runs no command, 28 runs the suite exactly once in 6/6); with-arm scores are 0.90 / 1.00 / 1.00 / 0.92 / 0.90 for 22–26 against a baseline of 1.00 / 0.94 / 1.00 / 1.00 / 0.90, and 22's ordering check (last suite run after the last edit) holds 3/3. The one with-arm outcome miss on 22 is an honest "not good to go yet" that stops to ask which rounding rule is intended, not an unverified claim. No script or hook changed.

v0.13.2 — `structured-debug` on two more bug-report shapes. Evals 01–07 (the structured-debug
suite) showed the skill never fired on a bug report that ends in an instruction to fix ("X is off
by one for some users. Just fix it." — the fix was applied unreviewed in 6/6 baseline runs) nor
on a pasted production stack trace with no repo access ("what's going on?"). The description now
names both: a report with an instruction attached is still a bug report, and pasted evidence is
answered with competing hypotheses and the evidence that decides them; it also carries negative
triggers for a feature request and an "explain this code" ask. Firing alone was not enough for
the first shape — the skill loaded and the model still patched, reading "just fix it" as the
approval — so the body's approval rule now says explicitly that a fix instruction *in the report*
is not approval of a fix plan; approval is a yes to the plan after it is presented, and step 5
ends the turn on the proposal. On the harness (3 runs, with/without): case 05 goes 0.33 → 1.00
with the fix held back 3/3, case 04 fires 3/3 at 1.00, the two negative cases stay silent at
1.00, and 01–03 are unchanged or better (03 now fires 3/3, was 1/3). No script or hook changed.

v0.13.1 — skill triggering on natural prompts. The v0.13.0 signals only reached users who
typed `/shipgate`: on naturally phrased asks ("which file most likely has the defect?", "what
could the change at HEAD affect?", "rank the changed files by regression risk") no shipgate
skill fired in any of ~60 eval runs, because each description said where the skill sits in the
flow ("first step of any feature", "final pre-push review", "agree a fix before changing code")
rather than what a user asks for, and none named the capability a plain read cannot give. The
`structured-debug`, `route-and-map` and `review` descriptions are rewritten around the asks
and the computed signals, with a negative trigger for trivial one-line edits; each skill body
gains a short **Standalone asks** note so an invoked skill answers the question and stops (no
branch, no fix plan, no reviewer fan); `feature`'s description sends standalone questions to the
phase skill instead of the orchestrator. Evals 08–11 are the regression test; no script or hook
changed.

v0.13.0 — code signals. The flow's intelligence was all *declared* (CLAUDE.md, ADRs, the
journal); nothing computed what the code and its history say. **Signals**: a second bundled
stdlib script, `scripts/signals.py` (`hotspots`, `blast`, `suspects`), computes per-file git
trajectory (commits, fix-rate, age, staleness, author count and top share) and, for TS/JS,
Python and Go, import-graph fan-in/out and blast radius, each labelled by quartile over the
whole repository so `top` means top *here*; "now" is HEAD's commit time, so two runs on one
state are byte-identical, and nothing persists (ADR 0004). A new `## Code signals` config
section (window, fix pattern, extra excludes) is the first one a script reads itself, so the
terminal and the flow compute the same numbers. **Wiring**: `route-and-map`'s impact map
gains a **Risk signals** block and the journal entry its labels and sizes; `review` briefs
carry the diff's risk table, and `review-workflow.js` takes an optional `fileRisk` that
tie-breaks ranking after severity and confidence and spends the refuter budget severity →
risk → confidence — risk never overrides severity, and absent it the output is byte-identical;
`structured-debug` starts hypotheses from a ranked suspect list; `implement` and `design`
prefer the precedent with the lower fix-rate, greater age and higher fan-in; explorer and
worker briefs may carry the table. No git, a shallow clone, an empty history or no adapter
degrades to one line and the phase as before. **Honesty**: fan-in is a lower bound in
alias-heavy or dynamically-imported code (the output marks `partial` / `unresolved`; risk is
a tie-break within a severity band only, so an undercount can cost a file its refuter slot in
that band but never changes a severity or drops a finding); granularity is the file, not the method,
and the semantic axis (embeddings, BM25, a glossary) is out of scope by decision. An indexed
retrieval layer (TeaRAGs-style: daemon, embedding runtime, ~1 GB per repo) was evaluated and
rejected as a dependency — see `docs/research/2026-09-25-tearags-vs-shipgate.md`. Evals
08–11 (bug localization from history, blast radius of a diff, risk-ranked review, a negative
one-line change) cover the new behaviour under `--ablation with-without`.

v0.12.1 — hooks file cleanup. `hooks/filechanged.json` carried its explanatory note under a
`_comment` key, which Claude Code's hooks loader reports at every session start as
`hooks.json: unknown key "_comment" ignored`. The note now lives under `description`, the
documented top-level field for a plugin hooks file. No behaviour change.

v0.12.0 — orchestration by workflow, config-selected. A new `## Orchestration` config
section (`review: agents | workflow`, `explore: agents | workflow`, default `agents`) lets
a project run the Review fan and the Explore fan as `Workflow` scripts bundled with the
skills instead of hand-driven `Agent` fans. **Review**: `review-workflow.js` runs the lens
finders (`shipgate:code-reviewer`, schema-typed findings, do-not-flag and pre-rulings
passed as `args`), dedupes across lenses in script, then spends a capped refuter budget
(`verify: none | high-only | all`, defaulting to `high-only` with `maxRefuters: 6`) on the
BLOCKER/HIGH candidates: a refutation counts only when it cites the `file:line` that
disproves the finding, and a finding dies only on a full quorum — every requested refuter
reported and every one of them refuted with evidence — so an uncertain, uncited or dead
refuter leaves it standing. The return is compact — ranked survivors carrying `verification`
and `quorum`, the killed list with its evidence, one-line below-floor entries, counts and
run-level `coverage` — so the coordinator's filtering pass starts from data, the raw
reviewer reports never enter its context, and the run id lands in
`review-verdict.data.workflow_run_id`. **Explore**: `explore-workflow.js` runs the lenses
as `shipgate:code-explorer` agents and merges their essential files, capped at 25; the
orchestrator still reads those files itself. Scripts always receive an explicit `model`
(one tier below the session — the tool would otherwise inherit the session model), and the
bundled-file references in `clarify`, `design`, `review` and `feature` now go through
`${CLAUDE_PLUGIN_ROOT}` so they resolve after a marketplace install. The cost is honest:
the finders cost what the `Agent` fan costs, so the gain is structure, dedupe and context
hygiene rather than fewer tokens, and full verification (`verify: all`) is worth it only on
high-stakes diffs. Implement stays on `Agent` workers (mid-flight `SendMessage`, warm reuse,
environment repair and the shared working tree have no workflow equivalent). A host without
the tool keeps the `agents` path and records a `deviation`.

v0.11.0 — the flow journal made cheap and trustworthy, from two weeks of its own data.
**Cost**: the session brief drops finished work (a stream now ends with `flow-completed`, and a
`capture-done` left alone for 48 h reads terminal; `--all` still shows everything), collapses
streams dormant over a week to one line, caps each stream at its last three gate decisions
(five on the checked-out branch's stream), and puts the checked-out branch's stream first
(`status --branch`, passed by the SessionStart hook); semantic events go up as one `append
--batch` per phase boundary, and a payload over 1 KB is refused so the prose stays in the
worklog and the event carries `refs`. **Position reliability**: a phase-owning event records
the `phase-entered` it implies instead of leaving the brief's headline field to memory (ADR
0002), `append` validates each type's payload against a canonical shape and normalizes the
aliases that had been drifting silently past the gates (`chosen→decision`, `kind→gate`,
`result→outcome`, `tasks→task_ids`, verdict `pass→ready`), and `actor` becomes `role[@label]`
over a closed set of roles, labelled by default from the session id the SessionStart hook
records (ADR 0003) — so who decided, and whether they were asked or were correcting
(`gate-decision.raised_by`), is finally queryable, via the new `stats`. **New gates**:
`mr-opened` is refused unless a `ready` verdict or the user's own `gate=publish` /
`decision=publish` call stands after the last `task-done` — "start the next item" cannot
publish; duplicate `artifact-written` rows (same path, same mtime, under 5 s apart) collapse;
and the Stop hook records its own blocks as `gate-blocked`. **Process**: the config template
gains a `## Worker guardrails` section that `model-tiers` requires pasted word-for-word into
every worker brief (every worker incident so far started as a compressed brief), and streams
are one per issue, named for the branch.

v0.10.0 — gates learned from a colleague's fleet-orchestration process. **Types round**:
design plans a declarations-only task for any slice introducing domain shapes; implement
delivers types with `unimplemented` bodies, gates on a test-inclusive type-check, reviews
the declarations alone, and freezes reviewed signatures (changes escalate + land as
`deviation`). **Parity gate** for ports/migrations: design declares pre-authorized deltas;
review adds a fresh adversarial pass hunting unauthorized behavioral differences across the
whole source artifact. **Review arbitration**: reviewer briefs carry do-not-flag lists and
pre-rulings, killed findings are recorded so they aren't re-litigated, trivial diffs may be
coordinator-gated (recorded as `gate-decision`), and the internal not-ready→fix loop caps
at two rounds before surfacing. **Worker discipline** (model-tiers): self-sufficient
follow-up dispatches, amnesia symptoms → cold-spawn, environment repair is orchestrator
work, briefs point at source artifacts (the artifact outranks the digest) and name a vetted
reference implementation, validation via workspace-level scripts with a baseline run on
shared code. All new gates reuse the existing journal vocabulary — no new event types.

v0.9.0 — config-declared tooling: new **Code tooling** section (a library-docs
tool/MCP for dependency APIs + an LSP tool for symbol navigation — wired into implement's
reuse step, structured-debug's evidence sources, and worker briefs) and new **Thinking
lenses** section (map phases to lens skills to actually invoke; default remains
apply-the-idea-inline). Hardcoded `thinking-skills` plugin references removed — the two
review/design agents can't invoke skills, so their lens guidance is now inline; main-session
lens invocation is config-routed.

v0.8.0 — project bootstrap: the `setup` skill (interview → writes `.claude/shipgate.md`,
a generated `.claude/shipgate.json` sidecar, and initializes the flow journal) and the
flow journal itself — the authoritative per-branch position (phase, tasks, verifies, gate
decisions) that the orchestrator routes from instead of rescanning worklogs.

v0.7.1 — implement's reuse-before-writing step now also checks the dependency's own API
surface and same-module siblings before hand-rolling integration plumbing (pairs with
astrolabe v0.3.0's reuse ladder).

v0.7.0 — orchestration throughput: **design-ahead pipelining** (while workers implement
issue N, the orchestrator specs N+1 with the user — epic mode's stop now gates merge+build,
not design; queued designs are re-validated against what actually merged); **executive
autonomy mode** (config-declared, default `ask` — in `executive` the orchestrator makes and
records routine gate decisions, escalating only one-way doors, scope changes,
security-sensitive areas, and true 50/50s); **the ledger** (a project-wide, append-cheap
staging inbox for mid-flow learnings, triaged at Capture into config-declared promotion
targets — wiki pages, skills, CLAUDE.md, ADRs, personal memory — or dropped; Capture now
fires when review passes, never waiting on the merge); and **worker lifecycle** (reuse warm
workers via SendMessage for same-context follow-ups, spawn cold for different context,
retire degraded workers ~400k tokens / 4-6 rounds in and brief a fresh finisher off the
worktree state).

v0.6.0 — bug provenance: `structured-debug` gains a "trace the provenance" step — find
the commit that introduced the defect (`log -S` / `blame` / `bisect run` with the repro),
prove it counterfactually (repro fails at the commit, passes at its parent), name why it
slipped through, and report all of it in a comment on the tracker issue. New optional
**Bug provenance** line in the config's Forge & tracker section says where those comments
go (default: the bug's issue, via the forge CLI).

v0.5.0 — re-tuned for current-generation models (per Anthropic's Opus 5 prompting
guidance): review is coverage-first (reviewers report every finding scored with
confidence + severity; a separate coordinator pass filters — generation-time severity
floors made models silently drop real bugs); the verify gate is scoped to evidence, not
repetition (fresh command output per claim stays, re-check choreography goes — independent
fresh-context review remains a distinct, kept discipline); delegation is disciplined (one
agent when one suffices, fan-outs scale to the task, tiers phrased relative to the
orchestrator's model instead of hardcoding "opus = mid"); `effort` added as the second
cost lever (agent frontmatter + Workflow `opts.effort`, mechanical work at `low`); and
written deliverables (PRD/ADR/worklog/MR body) carry explicit length calibration.

v0.4.1 — docs/wording only, no behavior change: the review-feedback cycle is now defined
(in `review` — a loop between Review and Implement), the MR watcher is called an
integration rather than a hook (no Claude Code hook is involved), and the project-config
preamble duplicated across skills was slimmed to one canonical form.

v0.4.0 — optional **MR watcher** integration: a project-declared skill watches open MRs/PRs;
`review` registers blockers/follow-ups with it, and its events resume the flow at the
phase they unlock (comments → review-feedback, merge → capture, blocker merged → held work).

v0.3.0 — merged the work-fork's evolution back (model-tiers, richer workspace/epic/review
discipline) and made every project specific a `.claude/shipgate.md` config concern.
