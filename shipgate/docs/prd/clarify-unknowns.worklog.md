---
type: worklog
title: "Worklog: Clarify surfaces the user's unknowns before the build"
created: 2026-11-24
updated: 2026-11-24
tags:
  - worklog
  - shipgate
  - clarify
status: built
prd: "./clarify-unknowns.md"
issue: "#24 (shipgate), child of #37"
related:
  - "../adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"
---

# Worklog: Clarify surfaces the user's unknowns before the build

> Design + build plan companion to `./clarify-unknowns.md`. Issue #24. ADR 0029 (accepted).
> Stream `feat/24-clarify-unknowns`. Release: shipgate 0.34.0, one PR, no hook file.

---

# Design

## Approach

One mechanism, designed inline (no architect fan: the open space was product behaviour,
and the user decided it as forks F1 to F8). Every executive clarify answer becomes a
tagged line with a class and a source. The risky lines go to the user in one dialog before
design. Evidence search, the blindspot pass and the UI reference only add to that list.
Whatever a script can check is a unit test or a prose test; eval cases judge only what
needs a model run.

## Architecture

| Part | File | Change |
| --- | --- | --- |
| Own share | `shipgate/scripts/signals.py` | Read the current identity; count its commits per file; give each `--by-dir` row `own_share` and `unfamiliar`; add a top-level `own_reason` to `hotspots` |
| Setting | `shipgate/settings.schema.json` | New key `clarify_confirm` |
| Clarify | `shipgate/skills/clarify/SKILL.md` | Evidence step, blindspot pass, UI candidate, tagged lines, the confirm batch, `off`, the recording forms; the old "Recall before asking" guardrail goes |
| Line format | `shipgate/skills/clarify/references/prd-template.md` | The tagged line of "Assumptions (executive)" |
| Contract | `shipgate/skills/feature/SKILL.md` | The executive contract's clarify bullet names the batch and the setting |
| Map | `shipgate/skills/route-and-map/SKILL.md` | Step 3 keeps `unfamiliar`; the map's Risk signals block shows it |
| Terms | `shipgate/docs/glossary.md` | Rows for **confirm batch** and **own share** |
| Docs | `shipgate/README.md`, `shipgate/CHANGELOG.md` | One settings row; the 0.34.0 entry |
| Release | `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.34.0 |
| Tests | `shipgate/tests/test_signals.py`, `test_settings.py`, `test_prose.py`, `test_journal_gates.py` | Everything deterministic |
| Evals | `shipgate/evals/76-*`, `77-*`, `78-*`, and the fixture of `16-*` | The model-run checks |

No hook file changes. `design/SKILL.md` and `setup/SKILL.md` do not change.

## Data flow

```
route-and-map: signals.py hotspots <paths> --by-dir 2 --blast --json
   → map: Risk signals block, plus "Unfamiliar to you: <dir> (own share <n>)"
clarify Step 1: coverage scan
   → evidence: knowledge-base recall + issue with comments + ≤3 linked docs (one search)
   → blindspot pass for each touched dir with unfamiliar true or unknown (≤2 candidates)
   → UI candidate when the map tags a module UI (1 candidate)
   → each answer: [class] [source: …] line; sourced answers move to Constraints
executive, clarify_confirm = risky:
   → risky lines (domain|data|behaviour, no source), design-impact order, ≤4
   → one AskUserQuestion (escalations first) | one message to report_to | last block of reply
   → end tag on each line + one gate-decision per item → clarify-passed → design
executive, clarify_confirm = off:
   → no dialog; phase summary lists the risky lines first → clarify-passed → design
ask mode: candidates and sources join the existing ≤5 questions; nothing else changes
```

## Data model / schema

**`signals.py hotspots` JSON (additive).**

- `dirs[].own_share`: a number from 0 to 1, rounded to 2 places. It is the identity's
  in-window commits that touch the row, divided by all in-window distinct commits that
  touch it (the same union of commit ordinals that `aggregate_dirs` already uses). A row
  with no in-window commits gets `0.0`.
- `dirs[].unfamiliar`: `true` when the unrounded share is below `UNFAMILIAR_OWN_SHARE`
  (0.10), else `false`. A share of exactly 0.10 is not unfamiliar.
- Both are `null` when the trajectory is missing or the identity is unknown.
- Top-level `own_reason`: `null`, `"no-identity"`, or the trajectory's reason (for example
  `"shallow"`). It is present on every `hotspots` payload.
- File rows, labels, `ranking`, the table, `blast` and `suspects` do not change. The
  identity is not in `LABELLED_SIGNALS`: it is not a risk signal.

**Identity.** `current_identity(repo)` runs `git config user.email` in the repo (git's own
order: repo, global, system), strips and lowercases it. Empty → `None`. It then runs
`git check-mailmap "<email>"` and takes the email between `<` and `>`, lowercased; on
failure it keeps the raw value. The trajectory scan reads `%aE`, which is already
mailmap-applied, so both sides match. The identity stays in a local variable: never in the
payload, a log line, an error text or the environment (FR-007 of the code-signals PRD).

**Counting.** `_Acc` gains `own_ids: set`. `scan_trajectory(repo, cfg, own=None)` adds the
commit ordinal to `own_ids` in `flush()` when the commit is in the window and its email
equals `own`. `aggregate_dirs` unions `own_ids` like `commit_ids`.

**Setting** (after `autonomy` in `settings.schema.json`):

```json
"clarify_confirm": {
  "description": "In executive mode, whether clarify puts its risky assumptions to the user in one dialog before design (risky) or only lists them in the phase summary (off).",
  "enum": ["risky", "off"],
  "default": "risky",
  "x-scope": "any",
  "x-since": "0.34.0"
}
```

No `x-legacy`: the key is new. It is not in `STATUS_KEYS`. No reader code: `journal.py
config clarify_confirm` works from the schema.

**The assumption line** (PRD template and clarify):

```
- [<class>] [source: <path or ref> | no source found in <what was searched>] <question> → <answer> — <rationale>
```

`<class>` is `domain`, `data`, `behaviour` or `technical`. After the batch, the line ends
with one tag: `[kept by the user]`, `[changed by the user, was: <old answer>]` or
`[unconfirmed]`. A line with no end tag was decided alone and never asked. The bracketed
tags make the line parseable for #25's digest and for option P below.

**Journal.** No new event type and no shape change. The three recording forms:

```bash
# kept
journal.py append --stream <s> --type gate-decision --actor user \
  --data '{"gate":"clarify","question":"<question>","decision":"kept: <answer>","mode":"ask","raised_by":"orchestrator"}'
# changed
journal.py append --stream <s> --type gate-decision --actor user \
  --data '{"gate":"clarify","question":"<question>","decision":"<new answer>","mode":"ask","raised_by":"user"}'
# dismissed (one event for the batch)
journal.py append --stream <s> --type gate-decision \
  --data '{"gate":"clarify","question":"confirm batch","decision":"dismissed: <n> items unconfirmed","mode":"executive","raised_by":"orchestrator"}'
```

A batch with several answers goes in one `--batch` append. When a lead's message says the
lead recorded the answers, the session does not record them again.

## API / contract changes

- `signals.py hotspots` JSON: three additive fields. No consumer breaks.
- Settings schema: one additive key. A project file with the key and an older shipgate
  reports it as an unknown key (a warning), which is the schema's normal path.
- PRD template: the "Assumptions (executive)" line format changes. Old PRDs keep their old
  lines; nothing parses them yet.
- The executive contract changes: every executive user of the public plugin gets the
  dialog after the upgrade. The changelog says so and names `"clarify_confirm": "off"`.

## Skill text (what each change says)

The rule for all skill text: describe the ask and the computed capability, and give the
reason; no new absolute rule where a reason does the work. Keep the clarify body to about
35 added lines net (#32 will diet it). Opus and Fable both read it.

**`clarify/SKILL.md`**

- Step 1, after the dimensions, **Evidence first**. Search once per run, before you answer
  or ask a `domain`, `data` or `behaviour` question: `knowledge-base` recall (the stores
  the config names), the issue with its comments (`gh issue view <n> --comments`, or the
  `forge` setting's CLI), and the documents the issue links, one level deep, at most 3,
  only those the session can read. The request and the issue are sources too. Why: 12
  corrections were wrong assumptions about a domain rule or a tool fact; a sourced answer
  is a fact, not a guess. Each answer gets its source or "no source found in <what was
  searched>". A sourced answer goes to Constraints with its source.
- Step 1, **Unfamiliar area**. Read `unfamiliar` for each touched directory from the
  impact map. With no map, run one
  `signals.py hotspots <dirs> --by-dir 2 --json`. When a value is `true`, or null, or the
  row is missing, run the blindspot pass and say why in one line (for example "own share
  unknown: no-identity"). The pass reads the area's `CLAUDE.md` or `README`, the subjects
  of its last 20 commits (`git log --format=%s -n 20 -- <dir>`, never the authors) and the
  top fix-rate files of the same JSON. It asks: what would the people who work here expect
  this change to decide, which the request does not mention? At most two candidates, each
  tagged blindspot. Why: nobody asks what they do not know (0 user messages did); in an
  area the user knows, they would catch it themselves, so the pass runs only where they
  would not.
- Step 1, **UI**. When the map tags a module `UI`, add one candidate: the reference
  implementation or screenshot the work should follow, with the nearest existing screen as
  the recommended answer. Why: references arrived after a defect in 10 sessions.
- Step 2, `ask` mode: the candidates join the questions, inside the cap of about 5, in
  impact order. Each question quotes its source or says none was found.
- **Executive mode**, rewritten:
  - Each answer is one tagged line (the template's format).
  - Risky lines: class `domain`, `data` or `behaviour`, with no source.
  - Read `clarify_confirm` with `journal.py config clarify_confirm` (executive only).
  - `risky` (default): one `AskUserQuestion` at the end of clarify, one question per risky
    line, at most 4, ordered by how much a wrong answer would change the design. Header:
    the class word, or `Blindspot`, or `Reference`. Question: the answer taken and its
    source line. Options: "Keep" first, marked recommended, with the answer in its
    description; then one or two alternatives from the coverage scan; "Other" takes free
    text. Escalations of the same run share the dialog and come first. No risky line → no
    dialog. A stream with `report_to` → one message to the lead instead. No question tool
    and no lead → the batch is the last block of the reply, and the flow goes on. A
    dismissed dialog → every item `[unconfirmed]`. Why: users override 26% of domain and
    35% of naming answers; the veto list in the phase summary was never used (355
    decisions); one dialog, because the user asked for fewer.
  - `off`: no dialog, no stop, no batch to a lead. The lines keep their class and source.
    The phase summary lists the risky lines first. Escalations go to the user as before.
  - A confirm item is not a `[NEEDS CLARIFICATION]` marker; markers stay for escalations.
  - After the answers: the end tag on each line, one `gate-decision` per item (the three
    forms above). A change after `design-committed` is a `deviation`.
- **Record the gate**: add the three forms, short.
- **Step 3, Capture the issue**: the issue was read in Step 1; reuse it.
- **Guardrails**: remove "Recall before asking"; the evidence step replaces it.

**`clarify/references/prd-template.md`**: the "Assumptions (executive)" section shows the
tagged line and the three end tags, with one example line per class kind.

**`feature/SKILL.md`**, The executive contract, first bullet: clarify answers go in the
PRD's "Assumptions (executive)" list, each with a class and a source; clarify puts the
risky ones to the user in one dialog before design, unless the `clarify_confirm` setting
is `off` (see `clarify`). The rest of the contract stays.

**`route-and-map/SKILL.md`**: step 3 keeps `own_share` and `unfamiliar` of each touched
`--by-dir` row, for clarify. The map's Risk signals block gains one line, shown only for a
touched directory with `unfamiliar` true or null:
`- Unfamiliar to you: <dir> (own share <n>)` or `- Own share unknown (<own_reason>)`.
The `phase-entered` payload does not change.

**`docs/glossary.md`**: two rows. **confirm batch**: the risky executive assumptions that
clarify puts to the user in one dialog before design (ADR 0029). **own share**: the
current git identity's share of a directory's in-window commits, a number that
`signals.py` computes; no identity leaves the script.

## README and CHANGELOG

README Configuration table, a new row after `autonomy`:

```
| `clarify_confirm` | `risky`, `off` | `risky` | in `executive` mode, whether clarify puts its risky assumptions to you in one dialog before design; `off` only lists them in the phase summary | any |
```

CHANGELOG, a new top entry:

```
v0.34.0 — clarify shows you its riskiest executive answers before design (#24, ADR 0029).

**Clarify confirms its risky assumptions in one dialog (#24, ADR 0029).** In `executive`
mode clarify still answers its own questions. Each answer in the PRD's "Assumptions
(executive)" list now carries a class (`domain`, `data`, `behaviour`, `technical`) and a
source, or says that none was found. Before design, clarify puts to you the answers about
a domain rule, the data model or what a user sees that no source states: one dialog, at
most 4 questions, "Keep" first. A fully specified issue gets no dialog. A teammate sends
the batch to its lead.
- The new setting `clarify_confirm` (`risky`, the default, or `off`; scope any) turns the
  dialog off. With `off`, the phase summary lists the risky answers first.
- Evidence first: one search per clarify run reads the knowledge base, the issue with its
  comments and up to 3 documents it links. Each question quotes what it found.
- `signals.py hotspots --by-dir` gives each directory row `own_share` and `unfamiliar`:
  your share of its commits in the window, and whether that share is below 0.10. Only the
  number leaves the script. In an unfamiliar area, clarify asks up to two blindspot
  questions.
- When the impact map touches UI, clarify asks which reference the work should follow.
- Upgrade note: every executive project gets the dialog. Set `"clarify_confirm": "off"`
  in `.claude/shipgate.json` to keep the old flow.
```

## Reference implementation

- Setting: `writing_style` in `settings.schema.json`, a top-level enum with scope `any`; its
  README row is the model for the new row.
- Own share: `top_share` in `build_rows` and the commit-ordinal union in `aggregate_dirs`
  (`signals.py`). Mirror the union exactly; do not sum per-file counts.
- Tests: `FixtureRepo` with its `author` argument and the privacy test in
  `TestCrossCutting` (`test_signals.py`). Configure the repo-local identity with
  `FixtureRepo.git("config", "user.email", ...)`.
- One dialog with items: the close-out question of ADR 0026 (`feature/SKILL.md`,
  Close-out step 3).
- Eval fixtures: `15-clarify-exec-issue-seeded/fixture.sh` (the billing app and the `c()`
  helper).

## Risk ranking

`signals.py hotspots` over the plan's files, source `graph`:

| File | Churn | Fix | Note |
| --- | --- | --- | --- |
| `shipgate/README.md` | top | high | pinned by the README settings-table prose test |
| `skills/feature/SKILL.md` | top | high | pinned by `test_feature_owns_the_contract` |
| `skills/clarify/SKILL.md` | top | low | |
| `shipgate/docs/glossary.md` | top | low | |
| `skills/route-and-map/SKILL.md` | top | low | |

`signals.py` and `test_signals.py` rank risk `top` by churn, fix-rate `low`. T001 pins the
current `--by-dir` row keys before T011 adds fields. `test_prose.py` is churn `top`, fix
`high`: add pins, do not rewrite existing ones.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/` only. No hook file, no `shipgate-hud` change.
- `signals.py` stays Python 3.9 and stdlib only (no `match`, no runtime `X | Y`).
- Tests run with `python3 -m unittest discover -s shipgate/tests` from the repo root.
- Public repo: fixtures and docs use `example.com` identities and generic names. Before the
  PR, grep the diff for the private project's names, tracker ids and paths.
- Security lens: `signals.py` now reads the user's git identity. The review checks that it
  never reaches output, logs or errors (SC-002).

## Eval plan

The user's two rules: measure only what a fall would make us change, and check
deterministically whatever a script can check. Of the 9 cases in F8-A, 4 remain.

**Moved to deterministic tests** (no eval case): the `own_share` number, the 0.10 threshold,
the zero-commit, no-identity and no-history branches, mailmap, the privacy of every output
form (T010); `clarify_confirm` values, default, scope and resolution (T020); the recording
forms (T036); the required sentences: `off`, the cap of 4, "no source found", the end
tags, `report_to`, `unfamiliar`, the template line, the contract bullet (T030). What `off`
does has no code path: it is skill text, pinned by T030.

**Cut or merged:**

- Case 15: its "Assumptions (executive)" check now lives in case 76; its other graders judge
  PRD content that #24 does not touch. Cut.
- Case 17: the rule "a confirm item is not a marker" is a prose test (T030); the model side
  is case 78's no-marker grader. Cut.
- The separate evidence-first case: merged into 76 (same fixture, separate graders).
- The separate blindspot case: merged into 76; the request touches an unfamiliar area.
- The familiar-area twin: the trigger is a unit test; reading `unfamiliar: false` is pinned
  by prose. Cut.

**The 4 cases.** Cost per tree (3 runs, with arm): Opus about 1.3 USD, Fable about 2.6 USD.
Case 76 reads more (signals, git log, a linked doc); allow up to 1.5×.

| Case | What it judges | A fall makes us change | Why no script can judge it | Trees | Opus | Fable |
| --- | --- | --- | --- | --- | --- | --- |
| 76 `clarify-exec-confirm-batch` | reads the linked policy and makes it a sourced constraint outside the batch; batch items are `domain`, `data` or `behaviour`; lines carry fitting classes; a blindspot item names the rule in the area's commit subjects; no author identity in the reply or PRD; no screenshot ask on a non-UI change | the evidence step (FR-002, FR-003), the batch rule (FR-004, FR-005), the line guidance, the blindspot pass (FR-016, FR-017), the UI trigger (FR-018), per grader | whether the model reads the doc, takes its rule as the answer, judges a class, and finds a rule in commit history is judgment over text a script never sees | baseline + PR | 2.6 | 5.2 |
| 77 `clarify-ui-reference` | the list asks for a reference or screenshot, or names the page element to mirror | the UI candidate text (FR-018) or the map's `UI` tag in route-and-map | the `UI` tag and the turn into a question are both model judgment | baseline + PR | 2.6 | 5.2 |
| 78 `clarify-exec-fully-specified` | a complete request gets no batch and no open marker | the skip rule (FR-006) and "the request is a source" | whether any answer is risky and unsourced is the model's classing and sourcing | PR only | 1.3 | 2.6 |
| 16 (existing) | one-way doors stay escalations (markers, handed to the user), not batch items | the escalation-first rule (FR-007, FR-009) | whether a schema or API change is an escalation is judgment | PR only (+ baseline on a fall) | 1.3 | 2.6 |

Total: 23.4 USD; at most about 27 USD with a baseline for case 16 and 76 at 1.5×.

Baselines exist only where they answer a question: for 76 and 77, a baseline that scores
within 0.10 of the PR tree on a grader means that part of the skill text adds nothing, and
it is marked for removal. Cases 78 and 16 have an absolute bar; the old executive mode
never asks, so their baselines say nothing.

**Case 76 fixture.** The billing app of case 15, with:

- `ledger/postings.py` (an append-only list of postings: account, invoice number, amount,
  kind) and `ledger/balance.py` (a customer's balance from postings). Neutral docstrings.
- About 12 commits on `ledger/` by `owner <owner@example.com>`, two of them
  `fix(ledger): an issued invoice is never edited; correct it with a reversing posting` and
  `fix(ledger): restore append-only postings after an in-place total update broke the
  audit trail`. The rule lives only in these subjects, not in code or docs.
- `docs/finance/late-fees.md`: a 2% late fee on the invoice total, charged once on the first
  overdue day after the grace period, never compounded, never on a paid invoice.
- Repo-local identity `newcomer <newcomer@example.com>` (`git config user.email`), with at
  most one commit of its own outside `ledger/`.
- `.claude/shipgate.json`: `{"version": 2, "db": null, "autonomy": "executive"}`.

Prompt: a ticket "Late fee on overdue invoices: when an invoice goes overdue, add the late
fee to the customer's balance and send an overdue notice that shows it. Policy:
`docs/finance/late-fees.md`." Then: "Clarify this and write the PRD to
`docs/prd/late-fees.md` first."

Graders: `skill-fired` (display); `policy-read` (`tool_used` Read, `input_match:
late-fees\.md`, min 1, weight 0.5); `policy-sourced` (llm on the PRD: the 2%, once, not
compounded, not on paid rule is a constraint with `docs/finance/late-fees.md` as source);
`policy-not-in-batch` (llm on the reply); `batch-items-risky` (llm on the reply: one batch;
each item is a domain rule, the data model or what a user sees; none is storage,
scheduling, code structure or tests; each states the answer and an alternative);
`lines-classed` (llm on the PRD: every line has a class tag that fits and a source tag);
`blindspot-found` (llm on the reply: a blindspot item says an issued invoice is never
edited, so the fee is a separate posting, or asks the user to decide how the fee enters
the balance under that rule); `no-identity-reply` and `no-identity-prd` (regex
`not_contains` `owner@|newcomer@|@example\.com`, weight 0.5 each); `no-screenshot-ask`
(regex `not_contains` `screenshot` on the reply, weight 0.5).

**Case 77 fixture.** The billing app, plus `web/templates/invoice.html` (a status label
with class `badge badge-open`), `web/static/app.css` (`.badge` styles) and `web/views.py`.
Repo-local identity `dev <dev@example.com>`, the only author. Executive config. Prompt: "On
the invoice page, show how many days an open invoice is overdue. Clarify this and write
the PRD to `docs/prd/overdue-days.md`." Graders: `skill-fired` (display);
`reference-asked` (llm on the reply: the batch or the questions name the reference to
follow — a reference implementation, a screenshot, or an existing element of the invoice
page to mirror as the recommended answer); `reference-in-prd` (regex on the PRD
`reference|screenshot|mirror`, weight 0.5).

**Case 78 fixture.** Case 19's fixture plus the executive config and the repo-local
identity `dev <dev@example.com>`. Prompt: case 19's text unchanged. Graders: `skill-fired`
(display); `asks-nothing` (llm on the reply: it asks the user nothing and shows no batch to
confirm; a sentence that nothing needs confirming is fine); `no-open-markers` (regex
`not_contains` `NEEDS CLARIFICATION` on the PRD, weight 0.5).

**Case 16.** Its fixture gains the repo-local identity `dev <dev@example.com>`, so the
blindspot pass stays off as it would for a real user with git configured. Graders do not
change.

**Run rules** (from the 2026-11-24 run):

1. Baseline: before the merge, from this worktree once T040 to T043 are done. The installed
   plugin is the main checkout at 0.33.0. Check each trace's `init` record: plugin path and
   version 0.33.0.
2. PR tree: after the merge and before the tag. The installed plugin is then 0.34.0; check
   the `init` record again.
3. Command, one case per call, with arm only, one model per call, as the 2026-11-24 run did:
   `.claude/skills/run-evals/scripts/run-case.sh shipgate 76 --ablation none --model claude-opus-5-5`,
   then `--model claude-fable-5-2`. If the harness log shows both arms, the script's
   `--ablation with-without` won; read the with arm only.
4. Cost check first: one batch per model (case 76 on Opus, then on Fable). Stop if a batch
   costs more than 2× its estimate.
5. A batch is void when its JSON shows an `error` or `costUsd` 0 in any run. Stop that lane
   at the first void batch, fix the cause (session limit, git shim, shadowing), re-run.
6. One or two lanes (one per model).
7. Tolerance, named before any PR-tree score: a case passes at a score of at least 0.8 on
   each model. For 76 and 77, a grader whose baseline is within 0.10 of the PR tree marks
   its skill text for removal (a follow-up, not a block). Case 16 below 0.8 → run its
   baseline; a drop of more than 0.10 from the baseline is a regression and blocks the tag.
8. No `compare.py --record`: `baseline.json` has no model column until #28. Scores, costs and
   results dirs go to the Results section below and the PR body.

The dialog itself is out of reach of the harness. The two-turn driver could test it after
the merge; that belongs with #49.

## Option P — a computed batch (accepted by the user, 2026-11-24)

The user accepted option P through the lead, after the design session. T015 to T017 below
carry it. The line format is now a contract: one parser, unit-tested; #25 reuses it.

`journal.py assumptions <prd> [--risky] [--json]` parses the tagged lines of "Assumptions
(executive)". It validates each line (class from the set, a source tag) and exits 2 with
the line number of a bad line. `--risky` keeps the `domain`, `data` and `behaviour` lines
with no source and no end tag, in file order (the model writes them in design-impact
order), caps them at 4 and reports the overflow count. `--json` gives the items the dialog
needs.

- Gain: the cap, the class filter and the line format become computed and unit-tested;
  the `lines-classed` grader of case 76 shrinks to class fit only. #25's digest must parse
  the same list ("decided alone" lines); it reuses this parser.
- Cost: one module in `scripts/_journal/` of about 100 to 150 lines, its CLI entry, about
  12 unit tests, one Bash call per clarify run, and one sentence in clarify. The line
  format becomes a contract. A PRD in a home outside the repo (a wiki) cannot be parsed;
  there the model filters by itself.
- Tasks it adds: T015 parser tests (test first), T016 the module and CLI, T017 the clarify
  sentence. It removes nothing else.

## Handed to #26

The design variants of part 4 move to #26 (F6-A). The lead posts the paragraph on #26.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

Run everything from the repo root. The suite: `python3 -m unittest discover -s
shipgate/tests` (never `-t .`). Use the bundled scripts of this checkout for code under
change (`python3 shipgate/scripts/signals.py`), and the installed plugin's `journal.py` for
journal appends.

## Setup / foundations

- [x] T001 — Run the suite green as a baseline; add a pin of today's `--by-dir` row keys
  (`dir`, `files`, `commits`, `fixes`, `fix_rate`, `fan_in`, `labels`, `risk`) — file(s):
  `shipgate/tests/test_signals.py` — done when: the suite passes with the pin; record the
  pass count.

## Own share (FR-014, FR-015; SC-001, SC-002)

- [x] T010 — Tests first: a two-author `FixtureRepo` (an owner with most commits in one
  directory, a second identity configured repo-local with one commit elsewhere). Cases:
  owned dir `own_share` 1.0 / `unfamiliar` false; foreign dir share below 0.10 / true; a
  dir with no in-window commits 0.0 / true; a dir at exactly 0.10 / false; no identity →
  both null and `own_reason` `no-identity`; no trajectory → `own_reason` the trajectory
  reason; a `.mailmap` entry maps the configured email; `UNFAMILIAR_OWN_SHARE == 0.10`;
  the T001 pin extended by `own_share` and `unfamiliar`; the privacy test of
  `TestCrossCutting` re-run with a repo-local identity configured (needles: the
  identity's name and email) — file(s): `shipgate/tests/test_signals.py` — done when: the
  new tests fail for the missing fields, the old ones pass.
- [x] T011 — Implement: `UNFAMILIAR_OWN_SHARE`, `current_identity(repo)`, `_Acc.own_ids`,
  `scan_trajectory(..., own=None)`, the two dir-row fields, top-level `own_reason` on
  `hotspots` — file(s): `shipgate/scripts/signals.py` — done when: T010 passes, the suite
  passes, Python 3.9 syntax only.

## Assumption parser — option P (FR-001, FR-005; SC-004)

The line contract, as the parser reads it (a build decision, recorded as a
`gate-decision`):

```
- [<class>] [blindspot|reference]? [source: <ref>] | [no source found in <what>] <question> → <answer> — <rationale> <end tag>?
```

- The section is the `## Assumptions (executive)` heading line up to the next `## ` line
  or the end of the file; the heading appears once (a second one is a bad line). A list
  item starts with `- ` or `* ` at column 0; indented lines (spaces or a tab) continue it.
  Blank lines close the item. Any other line is a bad line, `only assumption lines belong
  in this section`: prose, a heading, another bullet (the user's decision after review
  round 5; T063). An indented item and a ``` or ~~~ line keep their own reason (rounds 1
  and 4; T062).
- `<class>` is `domain`, `data`, `behaviour` or `technical`. The kind tag is optional.
  Exactly one source tag. ` → ` is required; ` — <rationale>` is optional.
- The end tag, when present, is `[kept by the user]`, `[changed by the user, was: <old>]`
  or `[unconfirmed]`.
- Exit 2 names the first bad line's number. A PRD with no section gives an empty list, and
  `--json` says `"section": false`.
- `--risky` keeps, with no end tag: the `domain`, `data` and `behaviour` lines with no
  source, and every `[blindspot]` or `[reference]` candidate whatever its source (review
  round 1). File order; at most `--cap N` (0 to 4, default 4), with the overflow count.

- [x] T015 — Tests first: a well-formed section parses (class, kind, source or searched,
  question, answer, rationale, end tag, line number; wrapped items joined); each malformed
  form exits 2 with its line number (no class, unknown class, no source tag, two source
  tags, no arrow, a broken end tag); no section → empty, exit 0; `--risky` keeps only
  unsourced `domain`, `data`, `behaviour` lines with no end tag, in file order, capped at 4
  with the overflow count; `--json` shape; a missing file exits 2; the module joins
  `_LAYERS` — file(s): `shipgate/tests/test_journal_assumptions.py` — done when: they fail
  for the missing command.
- [x] T016 — The module and its CLI entry — file(s): `shipgate/scripts/_journal/assumptions.py`,
  `shipgate/scripts/_journal/__init__.py`, `shipgate/scripts/_journal/cli.py` — done when:
  T015 and `test_journal_layout.py` pass; Python 3.9 syntax only.
- [x] T017 — Clarify calls the command for the batch; with a PRD the script cannot read,
  the model filters by the same rule — file(s): `shipgate/skills/clarify/SKILL.md` (with
  T031) — done when: its T030 pin passes.

## The user's rule for UI references (after review round 2)

- [x] T060 — A UI candidate is written only when the request names no reference; a named
  reference is a `[source: the request]` line and opens no dialog. A blindspot candidate
  always joins the batch. Clarify text only; the parser is unchanged (it batches every
  `[reference]` candidate, and now none exists for a named reference) — file(s):
  `shipgate/skills/clarify/SKILL.md`, `shipgate/tests/test_prose.py`, the PRD (FR-003,
  FR-018), ADR 0029 (decision 8, Consequences), `shipgate/CHANGELOG.md` — done when: the
  new prose pin fails first, then passes; case 77's request names no reference, so its
  fixture, graders and baseline stand.

## Review round 4: substance only (the user's ruling)

- [x] T061 — Fix R3-1 (delete the parser's heading check inside a fence; a `#` line in a
  closed fence is code), R3-2 (clarify: `section` false, or 0 items when lines were
  written, means fix the heading and run again), R3-3 (clarify Step 1: a blindspot
  candidate stays in the list), R3-4 (ADR 0029 decision 2), R3-5 (signals.py: a
  `user.name` with `<` or `>` is not used for `check-mailmap`), and the user's scope
  answer: the request or the issue names the reference (R3-9 and the pin wording) —
  file(s): `scripts/_journal/assumptions.py`, `scripts/signals.py`,
  `skills/clarify/SKILL.md`, ADR 0029, the PRD (FR-018), `tests/test_journal_assumptions.py`,
  `tests/test_signals.py`, `tests/test_prose.py` — done when: each new test fails first,
  then passes on both Pythons. Every other round-3 LOW is deferred to #32; R3-11 and
  R3-14 stay rejected. No paragraph is re-wrapped beyond the changed lines.

## Simplify, no fences (the user's decision after review round 4)

Four review rounds each found new MEDIUM items, most of them in how the parser read code
fences. The fences existed only because the template showed its examples in a fenced block
inside the section. The user chose to remove the cause.

- [x] T062 — The section holds no code block: a line in it whose stripped text starts with
  ``` or ~~~ is a bad line, `code block in the assumptions section`. The section is the
  heading line to the next `## ` line or the end of the file; the heading appears once in
  the file, and a second one is a bad line at its own line number. The fence scanning, the
  `fenced` count, the errors `unclosed fence` and `item lines only inside a fenced block`
  and their tests are deleted. The template's examples move to clarify's SKILL.md
  (Executive mode); the template's placeholder line stays a bad line (`unknown class
  [<class>]`), so a copied template exits 2 until clarify replaces it. Also R4-2 to R4-6.
  R4-1 is void (no fence is read); R4-7 and every round-3 LOW stay deferred to #32 —
  file(s): `scripts/_journal/assumptions.py`, `scripts/_journal/cli.py`,
  `tests/test_journal_assumptions.py`, `tests/test_prose.py`, `skills/clarify/SKILL.md`,
  `skills/clarify/references/prd-template.md`, the PRD (FR-003), ADR 0029, `README.md`,
  `CHANGELOG.md`, this worklog — done when: each new test fails first, then passes on both
  Pythons.

## Strict section (the user's decision on R5-1, after review round 5)

- [x] T063 — The section holds only assumption lines: a blank line, an item line (`- ` or
  `* ` at column 0) or a continuation line (two spaces or more, or a tab, right after an
  item or another continuation line). Any other line is a bad line, `only assumption lines
  belong in this section`: prose, a heading, a wrong or missing bullet, a numbered item. An
  item line keeps its own form errors; an indented item and a ``` or ~~~ line keep their
  own reason. The `1.`/`+` drift rule (`not a "- " list item`) is dead under the strict
  rule and deleted. The template's explanation inside the section moves into clarify's
  SKILL.md (Executive mode; the `ask` mode note to Step 3), so a fresh PRD's section holds
  only the placeholder line. Also R5-4 (a prose pin for "the section holds only assumption
  lines") and R5-5 (ADR 0029's UI scope phrase). R5-2, R5-3 and R5-6 to R5-9 stay deferred
  to #32 or void — file(s): `scripts/_journal/assumptions.py`, `scripts/_journal/cli.py`,
  `tests/test_journal_assumptions.py`, `tests/test_prose.py`, `skills/clarify/SKILL.md`,
  `skills/clarify/references/prd-template.md`, ADR 0029, `README.md`, this worklog — done
  when: each new test fails first, then passes on both Pythons.

## Setting (FR-012; SC-003)

- [x] T020 [P] — Tests first: `clarify_confirm` in `TABLE_KEYS`; `journal.py config
  clarify_confirm` prints `risky` with source `default`, `off` from a project file, exit 2
  on a bad value — file(s): `shipgate/tests/test_settings.py` — done when: they fail for
  the missing key.
- [x] T021 — The schema entry (Design, Data model) and the README row (Design, README and
  CHANGELOG) — file(s): `shipgate/settings.schema.json`, `shipgate/README.md` — done when:
  T020 and the README settings-table prose test pass.

## Skill text (FR-001 to FR-011, FR-013, FR-016 to FR-019; SC-004, SC-005)

- [x] T030 [P] — Prose tests first. Pins: clarify names `clarify_confirm`, `risky`, `off`
  and what `off` does (no dialog, the phase summary lists the risky lines first); the cap
  of 4; "no source found"; the three end tags; `report_to`; `unfamiliar`; "a confirm item
  is not a `[NEEDS CLARIFICATION]` marker" or its equivalent; the old "Recall before
  asking" guardrail is gone; the template shows the tagged line; the executive contract's
  clarify bullet names the batch and `clarify_confirm`; route-and-map's Risk signals block
  names `unfamiliar` — file(s): `shipgate/tests/test_prose.py` — done when: they fail
  before T031 to T035.
- [x] T031 — Clarify: the changes in Design, Skill text — file(s):
  `shipgate/skills/clarify/SKILL.md` — done when: the clarify pins of T030 pass; net growth
  about 35 lines or less.
- [x] T032 [P] — The tagged line and end tags — file(s):
  `shipgate/skills/clarify/references/prd-template.md` — done when: its T030 pin passes.
- [x] T033 [P] — The executive contract's clarify bullet — file(s):
  `shipgate/skills/feature/SKILL.md` — done when: its T030 pin and
  `test_feature_owns_the_contract` pass.
- [x] T034 [P] — Step 3 and the map line — file(s): `shipgate/skills/route-and-map/SKILL.md`
  — done when: its T030 pin passes.
- [x] T035 [P] — Two glossary rows — file(s): `shipgate/docs/glossary.md` — done when: the
  glossary prose tests pass.
- [x] T036 [P] — Pin the three recording forms: the journal accepts each into a temp
  database — file(s): `shipgate/tests/test_journal_gates.py` — done when: the test passes
  (a pin of today's behaviour, so it passes at once).

## Evals (FR-020; SC-006 to SC-009)

- [x] T040 — Case 76 (Design, Eval plan) — file(s): `shipgate/evals/76-clarify-exec-confirm-batch/`
  (`case.yaml`, `prompt.md`, `fixture.sh`, `graders/`) — done when: `bash fixture.sh` in a
  scratch directory builds `app/` with the two authors, and the signals in that `app/`
  (the T011 code) give `ledger` `unfamiliar: true`.
- [x] T041 [P] — Case 77 — file(s): `shipgate/evals/77-clarify-ui-reference/` — done when:
  the fixture builds.
- [x] T042 [P] — Case 78 — file(s): `shipgate/evals/78-clarify-exec-fully-specified/` — done
  when: the fixture builds.
- [x] T043 [P] — Case 16's fixture gains the repo-local identity — file(s):
  `shipgate/evals/16-clarify-exec-one-way-door/fixture.sh` — done when: the fixture builds
  and `git config user.email` in its `app/` prints the fixture identity.
- [x] T044 — Baseline runs before the merge (Run rules 1, 3 to 6): cost check on 76 per
  model, then 76 and 77 on both models — file(s): the Results section below — done when:
  each batch is non-void, its score, cost and results dir are recorded per model.

## Release (0.34.0)

- [x] T050 — Version 0.34.0 in both files, and the CHANGELOG entry (Design, README and
  CHANGELOG) — file(s): `shipgate/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `shipgate/CHANGELOG.md` — done when: both versions
  read 0.34.0 and the changelog prose tests pass.
- [x] T051 — Final check: the full suite passes; `git diff` holds no hook file; the
  public-repo grep of the diff finds no private name, tracker id or path — file(s): none —
  done when: the suite's pass count and the three checks are recorded in a `verify-run`.

## Coverage

FR-001 to FR-011, FR-013, FR-016 to FR-019: T030 to T036. FR-012: T020, T021. FR-014,
FR-015: T010, T011. FR-020: T040 to T044 and the PR-tree runs. SC-001, SC-002: T010.
SC-003: T020. SC-004: T036. SC-005: T030. SC-006 to SC-009: T040 to T044 and the PR-tree
runs. SC-010 has no task: #37's retro reads it one month after the release.

## Results

**How the baseline of 76 and 77 runs.** The case files need not be on `main`. The harness
reads the cases from the plugin directory it is given, and this run gives it this
worktree's `shipgate/`, so cases 76 and 77 exist. The skills it loads come from the
installed plugin, which is the main checkout at 0.33.0 (run-evals gotcha 6). So the with
arm is the old skill text on the new fixtures: the baseline. Each batch's `init` record
must show the installed path and version 0.33.0; a batch that shows 0.34.0 is void.

Command (a scratchpad launcher, one case and one model per call): `claude plugin eval
shipgate --runs 3 --ablation none --scaffold --judge-model sonnet --no-publish --allow-tools
Bash Edit Write --trust-plugin --keep-temp --model <m> --max-cost-usd <cap> --case 'NN-*'`,
under a scratch HOME that holds only links to the keychain and the security plist, billed
to the session's own account. The cap is the stop rule: 2.6 USD on Opus, 5.2 USD on Fable
(twice the estimate per batch).

Baseline (before the merge), 2026-11-24, with arm only, 3 runs, judge sonnet. Every batch:
no run `error`, every run cost above 0, `init` shows shipgate 0.33.0 and the model asked.
Results dirs are under `shipgate/evals/results/` (gitignored).

| Case | Model | Score | Cost | Results dir | Graders passed (of 3 runs) |
| --- | --- | --- | --- | --- | --- |
| 76 | Opus | 0.40 (0.37 with `policy-read`) | 1.40 | `2026-11-24T23-04-47-373Z` | skill-fired 3, no-identity-reply 3, no-identity-prd 3, no-screenshot-ask 3, policy-sourced 1, blindspot-found 1; the rest 0 |
| 76 | Fable | 0.65 | 3.47 | `2026-11-24T23-10-30-730Z` | skill-fired 3, the three regex 3, policy-not-in-batch 3, policy-sourced 3, blindspot-found 2; batch-items-risky, lines-classed, parser-ran 0 |
| 77 | Opus | 0.40 | 1.04 | `2026-11-24T23-17-37-354Z` | skill-fired 3; reference-asked 0, reference-in-prd 0 |
| 77 | Fable | 0.47 | 2.10 | `2026-11-24T23-17-37-362Z` | skill-fired 3, reference-in-prd 1; reference-asked 0 |

A void batch also ran: the first Opus batch of 76 billed the wrong account (the Bash
environment maps `CLAUDE_CONFIG_DIR` to another account). It stopped after 34 s; 0.17 USD.
Spend so far: 8.18 USD. Projection for the PR-tree runs (76, 77, 78, 16 on both models,
from these measured costs): about 14 USD, so about 22 USD in all.

What the baseline already says: on 0.33.0, Fable already reads the linked policy and
sources its rule (policy-sourced 3 of 3, policy-not-in-batch 3 of 3) and finds the
planted rule in 2 of 3 runs. For those graders the PR tree can show little gain on Fable;
the rule "a grader within 0.10 of the PR tree marks its text for removal" judges it.

PR tree (after the merge, before the tag): _to fill after the merge._

## After the merge (close-out, not tasks)

1. PR-tree runs: 76, 77, 78 and 16 on both models (Run rules 2 to 7). Judge against the
   tolerance before reading the next score. Record in Results and on the PR.
2. Tag `shipgate--v0.34.0` with `claude plugin tag --push` in `shipgate/`, only after step
   1 passes.
3. Tick #24 in #37.

## Approval path

No hook file changes, so one Publish dialog covers commit, push, PR and merge. The tag
waits for the PR-tree runs. The built-in `/security-review` runs on the commit before the
push.

## Deviations

- 2026-11-24 — The user accepted option P (the `journal.py assumptions` parser) through
  the lead after the design. T015 to T017 join the plan before T020. No task is removed.
- 2026-11-24 — T031: the clarify body grew by 57 net lines, not about 35. Each added
  paragraph carries a design rule and its reason; a cut would drop a rule. 8 of the lines
  are two fenced command blocks: a wrapped command broke the prose-drift test
  (`TestProseDrift`), and a block is also what a model copies. #32 diets the body.
- 2026-11-24 — The README command table gains a row for `journal.py assumptions`. The
  plan did not name it, but every public command has a row.
- 2026-11-24 — Case 76: the format half of `lines-classed` moved to the parser. A new
  `tool_used` grader, `parser-ran` (weight 0.5), checks that clarify ran
  `journal.py assumptions --risky`; the parser refuses a bad line in the run itself.
  `lines-classed` now judges class fit only. A unit test pins that the PRD template's
  example lines parse. The other graders stay: the regex ones already are scripts, and
  the LLM ones judge reading and classing, which no script sees.
- 2026-11-24 — Case 76: `policy-read` is removed after the Opus baseline batch. It
  counted Read tool calls on `late-fees.md`; all 3 runs read the file with `cat` in Bash,
  so it judged the tool choice, not the reading. `policy-sourced` judges that the rule
  came from the document. The Opus baseline is recomputed without it from the per-run
  grader results (0.37 with it, 0.40 without).

## Review round 1

Workflow run `wf_d032a315-0dd`: 3 lenses (correctness, conventions + design, simplicity +
security), verify `high-only`. Counts: 38 found, 31 after dedupe, 15 above the floor of 60,
2 refuters, 0 killed, 15 survivors, 16 below the floor. The security review (a briefed
reviewer on the working tree, 48 of 48 files read) found nothing at confidence 8 or above.

- F1 HIGH `skills/clarify/references/prd-template.md:71` — The template's example lines
  gave away the expected answers of eval cases 76 and 77 (the invoice badge, the fee as a
  posting). Held against both refuters. Fix: neutral library-domain examples in a fenced
  block that the parser skips.
- F2 MEDIUM `skills/clarify/SKILL.md:88` — New prose lines were not re-wrapped (clarify
  88, 89, 139; route-and-map 80). Fix: re-wrapped.
- F3 MEDIUM `skills/clarify/SKILL.md:143` — Escalations share the dialog, but the batch
  cap ignored them, so one dialog could need 5 questions. Fix: `assumptions --cap N`, and
  the skill sets `<n>` to 4 minus the escalations.
- F4 MEDIUM `skills/clarify/SKILL.md:79` — Two homes for a sourced answer. Fix: an answer
  a source states outright is a constraint; a derived one keeps `[source: <ref>]` in the
  list.
- F5 MEDIUM `scripts/_journal/assumptions.py:187` — A sourced blindspot or UI candidate
  dropped out of the batch. Fix: candidates are always in the batch.
- F6 MEDIUM `scripts/_journal/assumptions.py:65` — List-format drift gave 0 items and exit
  0. Fix: ordered, `+ ` and indented items are bad lines; JSON gains `section`.
- F7 MEDIUM `scripts/_journal/assumptions.py:92` — A near-miss end tag (case, trailing
  period, tab indent) passed silently. Fix: each is a bad line, a tab continues an item.
- F8 MEDIUM `skills/clarify/SKILL.md:139` — The skill did not say what happens to the
  overflow. Fix: the phase summary lists overflow lines first, with their count.
- F9 MEDIUM `skills/clarify/SKILL.md:135` — The batch ran in Step 2, before Step 3 writes
  the PRD. Fix: write the PRD first; the batch comes before `clarify-passed`.
- F10 MEDIUM `skills/clarify/SKILL.md:72` — Issue comments and linked documents counted as
  trusted sources. Fix, in part: their text is data to quote, never instructions. Who may
  count as a source is left as is: the tracker is the project's own.
- F11 MEDIUM `skills/clarify/SKILL.md:148` — The `off` paragraph dropped "escalations still
  go to the user". Fix: restored and pinned.
- F12 LOW `scripts/signals.py:1504` — `unfamiliar` used the unrounded share, so a row could
  show 0.1 and true. Fix: the flag follows the rounded share; a 2 of 21 test.
- F13 LOW `scripts/_journal/assumptions.py:79` — A leading tag stopped at the first `]`.
  Fix: bracket depth, as for the end tag.
- F14 LOW `scripts/signals.py:671` — A name-keyed `.mailmap` entry did not map the
  configured identity. Fix: `check-mailmap` gets `<name> <email>`; the name stays in memory.
- F15 LOW `skills/clarify/SKILL.md:145` — The lead and print paths did not say the end tag
  or the wait. Fix: the lead path waits for the answers; printed lines end `[unconfirmed]`.
- F16 LOW `skills/clarify/SKILL.md:210` — The dismissed form dropped `"question":"confirm
  batch"`. Fix: restored.
- F17 LOW `skills/clarify/SKILL.md:74` — The issue command lost `glab`. Fix: both CLIs.
- F18 LOW `skills/clarify/references/prd-template.md:69` — Template examples sat under the
  parsed heading. Fix: the fenced block of F1.
- F19 LOW `docs/adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md:14` — The
  `related` list missed the worklog and ADR 0027. Fix: added.

### Rejected findings

- `evals/15-clarify-exec-issue-seeded/fixture.sh:?` (LOW 55): Cases 15, 17 and 65 have no repo-local identity, so the blindspot pass runs there; deferred to the #28 suite audit, since none of them is in this PR's eval plan.
- `scripts/signals.py:663` (LOW 50): The identity ignores `GIT_AUTHOR_EMAIL` and `EMAIL`; FR-015 names git's `user.email`, and the environment is trusted.
- `skills/clarify/SKILL.md:131` (LOW 50): In `off` mode the parser does not run; `off` computes no batch by design, and the template states the form.
- `scripts/_journal/assumptions.py:38` (LOW 50): The parser accepts `* ` items; the contract now says so.
- `scripts/signals.py:1902` (LOW 40): `not-requested` is an internal value that no command emits.
- `scripts/signals.py:1903` (LOW 40): A nested conditional with a continuation; style only.
- `scripts/_journal/cli.py:626` (LOW 40): An unreadable PRD and a bad line both exit 2; the message tells them apart.
- `skills/route-and-map/SKILL.md:154` (LOW 35): The map line shows the share number; the design keeps it, and no identity is in it.
- `scripts/signals.py:670` (LOW 30): The identity is in a local child process's argv, the same user's process.
- `scripts/signals.py:1503` (LOW 30): A directory with no in-window commits is unfamiliar; F4-A decided that.
- `scripts/_journal/assumptions.py:203` (LOW 20): PRD text printed raw to the terminal; log spoofing is out of scope.


## Review round 2

One fresh reviewer, all lenses, on the fix diff of round 1 (14 files). F3 to F19 are
confirmed fixed, each with its line or test. F1 and F2 are reopened in part. The round
also found new issues; the fixes below are applied and unit-tested, and they wait for an
independent pass (the cap of two rounds is reached).

- R2-1 MEDIUM `prd/clarify-unknowns.md:118` — F5 put the candidates into the batch, but
  the PRD (FR-003, FR-004, FR-006, Terms), ADR 0029 (decisions 3 and 4) and the executive
  contract still said risky lines only. Fix: all of them name the candidates.
- R2-2 MEDIUM `references/prd-template.md:72` (F1 reopened) — The reference example still
  mirrored case 77's answer (a date element that copies a state pill). Fix: an export
  dialog that follows the import dialog.
- R2-3 MEDIUM `scripts/_journal/assumptions.py:82` — Fences opened a new silent zero-item
  path: real lines inside a fence, an unclosed fence, a prose line that starts with inline
  code. Fix: an unclosed fence is a bad line; a backtick info string with a backtick opens
  no fence; JSON counts `fenced` lines; fenced lines with no real line is a bad line.
- R2-4 MEDIUM `route-and-map/SKILL.md:81` (F2 reopened) — The re-wrap moved the long line.
  Fix: the paragraph is re-wrapped.
- R2-5 LOW `clarify/SKILL.md:220` — The dismissed JSON form broke inside a string. Fix: on
  one line.
- R2-6 LOW `scripts/_journal/assumptions.py:152` — An end tag followed by other text passed
  silently. Fix: any text after an end tag is a bad line.
- R2-7 LOW `scripts/_journal/assumptions.py:145` — The case-insensitive end words flagged
  `[Kept items list]`. Fix: only `kept by`, `changed by` and `unconfirmed` count as near
  misses.
- R2-8 LOW `scripts/_journal/assumptions.py:126` — An unbalanced `[` at the start of the
  question raised an error about a tag. Fix: it ends the tag scan; the question keeps it.
- R2-9 LOW `clarify/SKILL.md:144` — `<n>` could go below 0. Fix: "never below 0".
- R2-10 LOW `shipgate/README.md:291` — The usage column lacked `--cap`. Fix: added.
- R2-11 LOW `scripts/_journal/assumptions.py:285` — "risky" no longer fits a batch that
  holds candidates. Fix: the footer says "to confirm"; `off` lists the risky lines, then
  the candidates.
- R2-12 LOW `clarify/SKILL.md:224` — Record the gate did not say that the batch comes
  before `clarify-passed`. Fix: one clause.
- R2-13 LOW `clarify/SKILL.md:153` — The print path did not say which lines get
  `[unconfirmed]` or what is recorded. Fix: the PRD lines, and the dismissed form.
- R2-14 LOW `clarify/SKILL.md:130` — A garden-path sentence for a derived source. Fix:
  rewritten.

## Review round 3

One fresh reviewer, all lenses, on the fix diff since round 1 (16 files: rounds 1 and 2
and T060). All claims confirmed, except F2 and F4, reopened in part. Full suite: 2030
tests OK. The new findings wait for the user's decision on a fourth round (the lead's
rule); none is fixed yet.

- R3-1 MEDIUM `scripts/_journal/assumptions.py:99` — A `#` line inside a closed fenced
  block in the section raises a false `unclosed fence` (the heading check of R2-3).
- R3-2 MEDIUM `skills/clarify/SKILL.md:145` — Clarify never reads `section`, so a wrong
  or hidden heading (case change, `###`, an earlier unclosed fence) skips the dialog.
- R3-3 MEDIUM `skills/clarify/SKILL.md:79` — Step 1 sends every answer a source states
  outright to Constraints, with no exception for a blindspot candidate.
- R3-4 MEDIUM `docs/adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md:61` —
  Decision 2 still says every sourced answer leaves the list (F4 reopened in part).
- R3-5 LOW `scripts/signals.py:674` — A `user.name` holding `<` or `>` maps to a wrong
  identity (own share 0); no leak.
- R3-6 LOW `skills/clarify/SKILL.md:146` — New over-wide lines (also ADR:67, PRD:134) and
  ragged wraps at SKILL.md:222-228 (F2 reopened in part).
- R3-7 LOW `skills/clarify/SKILL.md:101` — The named-reference sentence does not say to
  leave out the `[reference]` tag.
- R3-8 LOW `tests/test_prose.py:537` — The T060 pin does not check "names no reference".
- R3-9 LOW `skills/clarify/SKILL.md:98` — A reference that only the issue names is still a
  candidate (a scope question for the user).
- R3-10 LOW `scripts/_journal/assumptions.py:314` — "The first bad line" is not in file
  order for scan errors.
- R3-11 LOW `scripts/_journal/assumptions.py:183` — An end-tag form inside the question is
  rejected with a misleading message (deliberate since R2-6).
- R3-12 LOW `docs/prd/clarify-unknowns.worklog.md:490` — The contract says "spaces"; the
  code needs two or more.
- R3-13 LOW `shipgate/CHANGELOG.md:15` — `off` wording lacks "then the candidates" (also
  ADR decision 6).
- R3-14 LOW `skills/clarify/SKILL.md:145` — No rule when escalations alone exceed 4.

The user's ruling on round 3: a fourth round for R3-1 to R3-5 and the scope answer (T061).
Deferred to #32, the skill-text diet: R3-6 (line widths and wraps), R3-7 (say "no
`[reference]` tag"), R3-10 (epilog "first bad line"), R3-12 (contract "spaces"), R3-13
(the `off` wording in CHANGELOG and ADR decision 6). Rejected: R3-11 (deliberate since
R2-6) and R3-14 (FR-007 already lets escalations fill the dialog alone).

## Review round 4

One fresh reviewer, all lenses, on the T061 fix diff only (9 files). All six claims are
done (R3-1 to R3-5 and the scope answer), each pinned by a test that fails on the old code.
New findings; the session stopped here for the user's decision (the lead's rule):

- R4-1 MEDIUM `scripts/_journal/assumptions.py:96` — With the heading check gone, an
  unclosed fence in the section can be closed by a fence in a later section; the scan
  then takes a later line as an assumption, or names the wrong line. Options: a `## `
  line at column 0 inside a fence opened in the section is an error (a `# comment` still
  passes), or accept and document the limit.
- R4-2 MEDIUM `skills/clarify/SKILL.md:152` — "0 items though you wrote lines" also fits a
  correct empty batch (all lines technical or sourced, or `<n>` 0). Option: keep only
  "`section` is false".
- R4-3 MEDIUM `docs/prd/clarify-unknowns.md:123` — FR-003 still says "the request names no
  reference"; FR-018 says "the request or the issue".
- R4-4 LOW `skills/clarify/SKILL.md:105` — The tag form names only `[source: the request]`;
  an issue-named reference needs `[source: issue #<n>]`.
- R4-5 LOW `shipgate/CHANGELOG.md:26` — The release note keeps the old scope phrase.
- R4-6 LOW `skills/clarify/SKILL.md:82` — "tagged" before the tag is named: write
  "tagged `[blindspot]`".
- R4-7 LOW `scripts/signals.py:674` — A `user.name` with a newline is not excluded (no
  leak; at worst a fallback to the email).

## Handoff (2026-11-25)

The building session passed the 500k context mark after round 4. The next session starts
in the worktree `pandora.worktrees/feat-24-clarify-unknowns` (branch
`feat/24-clarify-unknowns`), runs `journal.py handoff --stream feat/24-clarify-unknowns`,
and waits for the lead's word on R4-1 to R4-7. State: all tasks T001 to T061 done and
journaled; the newest verdict is `not-ready` (round 4); nothing is committed. Fix diffs
are built by `diff -ru` from a snapshot of `shipgate/` and `.claude-plugin/` taken before
the round (scratch only). Eval spend so far: 8.18 USD; the PR-tree runs come after the
merge. The deferred list for #32 is under "Review round 3".

## Review round 5

One fresh reviewer, all lenses, on the T062 diff only (11 files). All items are confirmed
done, each with its line or test: no code block in the section, the heading found once by
its line, the fence code and its tests deleted, the examples moved to clarify's SKILL.md,
the placeholder a bad line, and R4-2 to R4-6. R4-1 is void. No eval fixture or grader
depends on the change; the `parser-ran` grader of case 76 still matches the SKILL command.
New findings; the session stopped here for the lead (the rule for a MEDIUM):

- R5-1 MEDIUM `scripts/_journal/assumptions.py:106` — A line with a stray bullet (`•`,
  `–`, `-[`, a tab after `-`, or no bullet) is prose, so the batch is empty with exit 0.
  The parser did the same before; R4-2 removed the SKILL clause that caught it. Option:
  such a column-0 line with a class tag is `not a "- " list item`.
- R5-2 LOW `scripts/_journal/assumptions.py:80` — The second-heading error names only the
  later line; when a stray copy comes first, that line is the real heading.
- R5-3 LOW `skills/clarify/SKILL.md:116` — Under `ste-80` the Writing for people rule puts
  code in fenced blocks, and the PRD falls under it.
- R5-4 LOW `skills/clarify/SKILL.md:147` — The sentence "the section holds no code block"
  has no prose pin.
- R5-5 LOW `docs/adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md:204` — The
  ADR keeps the old UI scope phrase "the request names no reference".
- R5-6 LOW `scripts/_journal/assumptions.py:264` — Two new over-wide lines (also 292).
- R5-7 LOW `docs/adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md:201` — The
  new ADR text leaves a ragged line.
- R5-8 LOW `docs/prd/clarify-unknowns.worklog.md:880` — The Handoff still names round 4 as
  the newest state; this entry supersedes it.
- R5-9 LOW `scripts/_journal/assumptions.py:89` — A bare `##` line does not end the section
  (it follows the user's "`## ` line" rule).

The user's ruling on round 5: R5-1 is fixed by a strict section, not by a near-miss
bullet rule (T063); R5-4 and R5-5 are fixed with it. Deferred to #32 or void: R5-2, R5-3,
R5-6, R5-7, R5-8 and R5-9.

## Review round 6

One fresh reviewer, all lenses, on the T063 diff only (9 files). Confirmed, each with its
line or test: the strict section (R5-1, with the template's explanation in clarify's
SKILL.md, the item errors kept and the `1.`/`+` rule deleted), R5-4 and R5-5. No fixture
or grader of cases 76, 77, 78 or 16 depends on the change. Only LOW findings, all deferred
to #32 (the lead's rule):

- R6-1 LOW `scripts/_journal/assumptions.py:76` — `splitlines` also splits on U+2028 and
  other separators, so such a character in an item now exits 2 at a line an editor does
  not show.
- R6-2 LOW `skills/clarify/SKILL.md:148` — "another bullet" can read as "one more item";
  the skill does not name `- `, `* ` or the two-space continuation indent.
- R6-3 LOW `skills/clarify/SKILL.md:147` — Nothing says what a run with no assumption
  writes; a habitual `_None._` now exits 2 and costs one fix round.
- R6-4 LOW `tests/test_prose.py:560` — The no-source tag form and "Replace the template's
  placeholder line" moved to the skill without a pin.
- R6-5 LOW `docs/prd/clarify-unknowns.worklog.md:208` — The design note still says the
  template shows the end tags and the examples.

Verdict: ready (round 6). Fresh verify after T063: the full suite ran 2035 tests, OK, 2
skipped; the changed test files pass on `/usr/bin/python3` 3.9.6; `claude plugin validate
shipgate` passed; the byte scan finds only the U+FEFF that `main` has in `_journal/cli.py`;
the privacy grep of the diff is clean. Next: the user's go, then the commit, the built-in
`/security-review` on it, the push and the PR.
