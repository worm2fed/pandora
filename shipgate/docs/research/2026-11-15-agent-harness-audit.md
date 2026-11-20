---
title: agent harness audit — three articles, official guidance and usage data
date: 2026-11-15
status: research note — informs the issues it lists, decides nothing by itself
sources:
  - "Finding your unknowns" — an Anthropic engineer's guide to working with the Fable model (x.com/trq212)
  - "Every Agentic Engineering Hack I Know" — a practitioner's list of 22 habits, June 2026
  - "Understanding Harness Engineering" — a reference handbook for agent harnesses, October 2026
  - https://code.claude.com/docs/en/best-practices
  - https://code.claude.com/docs/en/skills
  - https://code.claude.com/docs/en/hooks
  - https://code.claude.com/docs/en/sub-agents
  - https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
  - https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2
  - https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5
  - https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - https://www.anthropic.com/engineering/harness-design-long-running-apps
  - https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - https://www.anthropic.com/engineering/writing-tools-for-agents
  - https://www.anthropic.com/engineering/how-we-contain-claude
  - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
  - https://www.anthropic.com/engineering/april-23-postmortem
  - https://www.anthropic.com/engineering/multi-agent-research-system
---

# Agent harness audit

## Why this note

shipgate 0.25.0 is a harness around a coding agent: skills, subagents, hooks, Workflow
scripts and a flow journal. Three articles and the official guidance say what a good
harness does and how a person should work with one. This spike compared them with the
plugin text and with the data of real flows. The tracking issue is #37.

## Method

Five lenses ran in parallel. Each lens reported numbers with their denominators.

| Lens | Input | Size |
| --- | --- | --- |
| Official guidance | Claude Code and platform docs, engineering posts | 24 pages fetched |
| Journals | flow journals of real projects, read-only | 7 journals, 9,449 events, 2026-08-20 to 2026-11-15 |
| Harness metrics | session transcripts, aggregated by script | 148 main sessions, 50,738 Bash calls |
| User behaviour | the person's own typed messages in those transcripts | 119 sessions, 1,237 messages |
| Plugin audit | the plugin's skills, agents, hooks, scripts and evals | 12 skills, 3 agents, 75 eval cases |

Limits of the data:

- All numbers are counts and shares. No content of a private project is in this note.
- The cost shares come from token counts, not from invoices.
- The phase of a message is inferred from the last phase skill loaded before it.
- The correction counts come from a manual read of 136 candidates and one recall sample.
- Main sessions ran on two model tiers: 108 on Opus and 46 on Fable. No result below is
  split by model yet. Issue #28 adds that split to the evals.

## What the three articles say

**Finding your unknowns.** The quality of the work is limited by how well the person
clears their own unknowns. There are four kinds: what the prompt says, open questions the
person knows about, things the person would recognise on sight but never wrote down, and
things the person never thought of. The guide gives a technique for each stage:

- Before: a blindspot pass, cheap prototypes in several variants, an interview that leads
  with the answers that could change the architecture, a reference implementation, and a
  plan that leads with the decisions the person will most likely change.
- During: a notes file with a Deviations section. On an edge case the agent takes the
  conservative option, records it and continues.
- After: one explainer built from the artifacts, and a quiz the person passes before the
  merge.

**Every Agentic Engineering Hack I Know.** A plan file exists for the agent: it is the
checkpoint that survives context loss, and it keeps the agent from stopping early. The
person supplies direction and taste, not typing. Anything done more than twice becomes a
skill.

**Understanding Harness Engineering.** The claims that matter most here:

- Every harness component is a hypothesis about a current model limit. It must earn its
  quality gain and its cost again when the model changes.
- A skill can harm. One 2026 study confirmed 307 skill-induced failures: 125 functional
  and 182 efficiency regressions.
- A completion claim is not verification. A mechanism beats a prose rule.
- Stop states differ: done, budget exhausted, blocked.
- Subagents need an argument from how the task decomposes. A subagent's report is
  untrusted input.
- Compaction loses information, so the work state lives in artifacts.

## What already matches

Keep these. The data or the guidance supports each one.

- Reviewers report everything, and a separate pass filters. Review precision is 73%.
- The review Workflow separates `aborted`, `unverified-cap` and `refuters-died`.
- The journal and the worklog hold the state outside the context. 43% of sessions start
  from an agent-written brief and resume from those artifacts.
- The Workflow fan is cheap: a reviewer costs 1.3M tokens there against 3.6M when
  dispatched by hand.
- The plugin's own text is a small cost: about 6% of the main thread's cache reads.
- The PreToolUse publish guard works as built: 32 refusals, all intended.
- The evals have negative cases and a with/without baseline.

## Findings

Ranked by expected benefit against cost. Each has its issue.

| # | Finding | Evidence | Issue |
| --- | --- | --- | --- |
| 1 | The status brief does not return after `/compact` or `/clear` | The SessionStart matcher is `startup\|resume\|fork`; 25 compactions and 10 clears got no brief | #20 |
| 2 | The Stop gate never blocked | 0 `gate-blocked` in 9,449 events; 3,171 hook runs; one known session met rule A's condition with no block | #21 |
| 3 | Approval for commit and publish happens outside the recorded path | 13 forced `mr-opened`; 3 dialog approvals and 0 shell approvals ever; 6 of 40 interrupts hit a commit step | #22 |
| 4 | Phases share one session | Cost tracks context size (0.97); 22 sessions with 3 or more phases carry about 41% of the cost; median compaction at about 850k tokens | #23 |
| 5 | The user's unknowns surface late | 52% of user decisions arrive in implement or later; 26% of domain questions are overridden; 355 executive decisions taken alone | #24 |
| 6 | Nobody shows the user what changed | 0 of 190 post-task messages ask for a summary; 18 design issues found late | #25 |
| 7 | UI defects pass verify | 30% of corrections are defects, mostly UI; 25 user screenshots | #26 |
| 8 | `verify-run` is a claim | 591 of 602 rows pass; 30 carry an exit code; the shape needs only `outcome` and `task_ids` | #27 |
| 9 | The evals are stale and ignore cost | 63 of 75 rows date from 0.15.0; no model recorded; median cost ratio 1.51; 40 cases cost more at zero delta | #28 |
| 10 | Workers carry the subagent cost | 466 workers hold 74% of subagent tokens; 536 of 686 dispatches are Opus, often the session's own tier | #29 |
| 11 | Worker git rules are prose | Two data-loss incidents; about 300 lines wiped by one checkout | #30 |
| 12 | The brief is large and streams stay open | 107 lines per start; 22 streams idle 38 to 87 days; "merged" typed in 39 messages | #31 |
| 13 | Skills and descriptions are heavy | `review` has 587 lines; only 5,000 tokens of a skill survive compaction; descriptions total about 12,000 characters | #32 |
| 14 | The review loop has no budget and no memory | 6 of 98 streams passed the two-round cap; 16 of 54 ready streams got human feedback later | #33 |
| 15 | The journal is hard to write to | 5.1% of appends fail; a failed batch does not say what landed; 292 of 350 deviations have no cause | #34 |
| 16 | Repeats are never read back | Five repeated asks with no skill, 15 to 59 messages each | #35 |
| 17 | The explore Workflow assumes code lenses | 2 of 5 explorers refused a scripted lens; truncation is reported through `log()` only | #36 |

### Notes on single findings

**Finding 2.** Zero blocks cannot tell full compliance from a dead check. The one known
case points at a dead check, so this is a bug until a probe test proves otherwise.

**Finding 3.** When the forced path is the normal path, the gate checks nothing. The fix
moves the record to where the user already answers.

**Finding 5.** The orchestrator in `executive` mode can answer the questions it can see.
It cannot know what the user would recognise on sight. The override rates say where to
ask: domain rules (26%) and naming (35%), not tests (10%).

**Finding 9.** Cases with zero score delta per skill: knowledge-base 7 of 9,
route-and-map 10 of 14, design 6 of 9, review 7 of 13. This is the efficiency-regression
class from the handbook. No skill text is cut before an ablation on both session models.

**Finding 10.** On a session that runs on Opus, a worker "one tier below, never below
Opus" is the same tier. Dispatch then buys parallelism and isolation only. The handbook
reports losses of 39 to 70 percent for multi-agent setups on sequential tasks.

## Habits, and the mechanism that replaces each

A habit a person must remember is a prose rule for a human. The same principle applies:
a mechanism beats a prose rule. Each habit below gets a gate, a default or a report.

| Habit | Evidence | Mechanism | Issue |
| --- | --- | --- | --- |
| End the session at a phase gate | 41% of cost in multi-phase sessions | The flow prints a handoff brief at `design-committed`; a hook adds one line past a context threshold | #23 |
| Read what was decided alone before a publish | 0 of 190 asks | The publish gate prints the digest; an optional quiz | #25 |
| Ask what you are missing | 0 asks; 12 wrong assumptions | A blindspot pass when the author share in the touched area is low | #24 |
| Give the reference up front for UI work | References arrive after a defect in 10 sessions | Clarify asks for one when the impact map touches UI | #24, #26 |
| Close finished streams | 22 streams idle for over a month | `sweep`, and close-out on merge | #31 |
| Turn a repeat into a skill or a rule | 5 repeated asks; one rule repeated in 8 sessions | A weekly retro proposes the skill, the rule or the hook | #35 |
| Do not commit before review | 6 interrupts, 2 corrections | A hook refuses the commit without the recorded go | #22 |
| Keep parallel work within review attention | 6 sessions per active day at the median, 10 at p90 | The retro reports streams in review against decisions pending | #35 |

Two habits sit outside the plugin, in the person's own setup:

- A Bash hook that rewrites the command after the auto-mode review caused 408 "no
  verdict" refusals, 16% of all tool errors. The fix belongs to that hook.
- Secrets typed into chat belong in a local env file. A UserPromptSubmit hook can check
  for them.

## Not measured

- Results per session model.
- Real parallelism: resumed sessions span days, so overlap is not concurrency.
- Skill-induced, coordination and provenance failures: the transcripts give no direct
  signal.
- How often the review refuters kill a finding in real use.
- Hook latency on a journaled project.
- Questions that `executive` mode answered without asking: they leave no question record.

## What this note decides

Nothing. #37 tracks the 17 issues and their order. Each issue is a separate deliverable
with its own flow.
