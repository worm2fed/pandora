---
type: prd
title: "PRD: shipgate 0.25.0 — lean project configs"
created: 2026-11-08
updated: 2026-11-08
tags:
  - prd
  - shipgate
  - config
status: clarified
issue: "#15, #16, #17, #18 (shipgate)"
worklog: "./shipgate-0.25.0.worklog.md"
related:
  - ../adr/0004-code-signals-on-demand-stdlib-script.md
  - ../adr/0018-config-layers-resolve-per-section-nearest-first.md
  - ../adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md
---

# PRD: shipgate 0.25.0 — lean project configs

> A project config holds project facts only. Personal defaults move to one user-level file.
> Plugin rules move into the plugin. `setup` writes and maintains a lean file, and `doctor`
> says when the config and the sidecar disagree.

## Problem

1. **Personal preferences repeat in every project config (#15).** Over 8 project configs
   (about 1,020 lines), 7 set the same writing style, 5 the same library-docs line, 4 the
   same worker guardrail word for word, and 4 the same executive-contract paragraph. None of
   it is project configuration, and every machine-wide change touches every file.
2. **Plugin rules live in project files (#16).** `model-tiers`' built-in worker discipline
   says only "branch check, no commit or staging, evidence". So the git-index rule, the
   no-`--no-verify` rule, the no-repo-wide-formatter rule, the stop-and-report rule and the
   comments rule are pasted into configs (4 carry the index rule, 2 each the others). The
   executive contract, the plugin's own rule about what the orchestrator records and
   escalates, is pasted into every `executive` config, and the skills restate it in four
   different forms (`clarify` lists four cases, `design` three, `setup` three, the glossary
   four plus Extra escalations).
3. **Configs carry text that explains the plugin (#17).** The template's header paragraphs,
   each `<!-- Default when absent … -->` comment, the Journal section's prose, the
   Orchestration and Writing style explanations, and the executive-contract bullet are about
   a third of the lines of a written config, and they go stale with each release (a `v0.13+`
   tag is in a config today). `setup` writes them because Step 3 says "keep the section
   comments". Also, 3 of 7 sidecars disagree with their config's `Ledger:` line (the config
   names a ledger, the sidecar has no `ledger` key), so `status` never counts those ledgers
   and nothing says so.
4. **A nested config has no combination rule (#18).** A repo inside an umbrella gets both
   configs read. `signals.py` merges them per key, nearest first. The skills have no rule at
   all, so nested configs say "overrides the umbrella" in every section by hand.

## Goals & non-goals

**Goals**
- One layering rule, stated in one place and cited everywhere a config is read: nearest
  project config, then the umbrella's, then the user file, then the built-in default,
  resolved per section, a nearer section replacing the farther one whole.
- A user-level config that the skills and `signals.py` read under the project config.
- `model-tiers` carries the worker discipline. `feature` carries the executive contract.
  `knowledge-base`, `implement` and `structured-debug` carry two small defaults that were
  config lines before.
- `setup` writes a lean config and offers, once per machine, to write the user file. Its
  update mode strips the boilerplate it recognises, shows the diff, and applies only on a
  yes.
- `journal.py doctor` names each drift between the config's `Ledger:` line and PRD, ADR and
  worklog homes and the sidecar.
- `Inherit: none` under a nested config's title takes nothing from the umbrella.

**Non-goals**
- No change to the hooks under `hooks/`. They read the sidecar only.
- No eval run, and no edit to an eval fixture. The fixtures that carry the old
  executive-contract bullet keep working: the model reads the bullet as redundant text.
- No change to shipgate-hud. The doctor's new keys are additive, and the HUD does not read
  `doctor`.
- No reading of any config outside this repository during this change.
- No migration of an existing project config by this change, other than this repository's
  own `.claude/shipgate.md` as the worked example.

## Functional requirements

**The layering rule (#15, #18)**
- **FR-001** — The rule is stated in two places only: the config template's header and the
  README's Configuration section. The rule: a config is resolved per section; the nearest
  project config (the repo's, then the umbrella's) is read first, then the user file, then
  the built-in default; a section present in a nearer file replaces the farther one whole,
  and sections never merge line by line. Every skill that reads the config cites the rule
  and does not restate it.
- **FR-002** — A section counts as present when its heading exists and it holds at least one
  value that is not a placeholder. A section with placeholders only, or with no bullets, is
  absent, and the next layer shows through.
- **FR-003** — The user file is `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set
  and not empty, else `~/.claude/shipgate.md`. It uses the project file's section
  vocabulary. The template marks the sections that are usually personal: Writing style,
  Code tooling (Library docs), Autonomy, and the ledger's promotion target for preferences.
- **FR-004** — `signals.py` reads the user file as the last file of its chain, resolves
  `## Code signals` and `## Code tooling` per section under FR-002, and labels a value from
  the user file `user shipgate.md` in `config.source`. A value from a project or umbrella
  file keeps the label `shipgate.md`. `config` gains `files`: the config files read, in
  precedence order, each with its `role` (`project`, `umbrella`, `user`).
- **FR-005** — A line `Inherit: none` (bare or as a bullet, backticks optional, any case)
  before the first section heading of a config takes nothing from the umbrella's config.
  The user file and the defaults still apply. `signals.py` honours it, and `config` reports
  `inherit` as `umbrella` or `none`.
- **FR-006** — `feature`'s route step says which config file each section in play came from
  when more than one config file was read.

**Built-in worker discipline and the executive contract (#16)**
- **FR-007** — `model-tiers` carries a built-in worker discipline block that every worker
  brief pastes word for word. It holds the three rules it had (branch check, no commit and
  no staging, evidence in the report) and five more: the git index is the user's review
  record (never `git add`, `git reset`, `git stash`, `git restore --staged`,
  `git checkout -- <path>`; leave the index as found, even when the whole tree appears
  staged; stop and report if the index blocks you); never `--no-verify`, never kill a
  running pre-commit hook; never a repo-wide formatter or a linter with `--fix`, format
  only the paths you touched; stop and report when blocked or near a spend or time limit,
  leave finished work on disk, never improvise a different design; comments only for what
  the code cannot say and that is local to the file, no narration, decisions go to the
  worklog. The config's Worker guardrails section keeps repo-specific rules only, and the
  template's examples are repo-specific.
- **FR-008** — `feature` owns the executive contract: what the orchestrator records where
  (clarify answers in the PRD's "Assumptions (executive)" list, design choices in the ADR,
  small calls in the ledger, every decision as a `gate-decision`), and what it escalates
  (one-way doors, user-visible scope changes, Security-sensitive areas, true 50/50s, plus
  the config's Extra escalations). `clarify`, `design`, `setup` and the glossary point at
  `feature` and do not restate the list. The config's Autonomy section is `Mode` and `Extra
  escalations` only; the template drops the contract bullet.
- **FR-009** — `knowledge-base` carries the promotion defaults: personal workflow
  preferences go to the harness's memory; everything else is dropped; promoted and dropped
  entries are removed. A config's `Ledger:` line lists project targets only.
- **FR-010** — The library-docs step of `implement` and `structured-debug` says: when a
  context7-style MCP (resolve a library id, then query its docs) is present in the session,
  use it by default; the config's Library docs line is an override.

**A lean setup, and doctor checks the sidecar (#17)**
- **FR-011** — `setup` writes a lean file: a one-line title, the sections the interview
  filled, `- Key: value` bullets only, no template comments, the Journal section as
  `- Database: <path>` only, no prose that explains the plugin. The explanations keep one
  home each: the README and the template's comments.
- **FR-012** — On a machine with no user file, `setup` offers once, after the project
  interview, to write the user file with the answers that are personal (Writing style,
  Library docs, Autonomy mode and its Extra escalations, the promotion target for
  preferences). The user accepts or declines. `setup` never copies a user-file section into
  a project file. In update mode it offers to delete a project section that equals the user
  file's.
- **FR-013** — `setup` update mode recognises the boilerplate the template and earlier
  setups wrote: the template's header paragraphs, the setup-written header paragraph, every
  `<!-- Default when absent … -->` and `<!-- Only needed for … -->` comment, the
  `signals.py` comment paraphrase, the Journal section's prose blocks, the Code signals,
  Worker guardrails and Orchestration explanation paragraphs, the MR watcher explanation
  bullets, the Thinking lenses explanation, the `Executive contract` bullet, and any bullet
  whose value is still an angle-bracket placeholder. It shows the removal as a diff and
  applies only on a yes. A line it does not recognise stays. A partial or edited match is a
  keep. A `- Key: value` bullet with a real value is never removed.
- **FR-014** — `journal.py doctor` reads the project's own `.claude/shipgate.md` and compares
  the `## Knowledge base` section's `Ledger:`, `PRD home:`, `ADR home:` and `Worklog home:`
  values with the sidecar's `ledger` and `artifact_homes`. It names each drift in one line:
  a ledger the config names and the sidecar lacks, a ledger that differs, a home whose
  directory differs from the sidecar glob's directory. A home value that is not a directory
  path is reported as not compared. The report is additive: a new `config` key in `--json`
  and new lines in the text form. `setup` update mode fixes the sidecar from the report.

**Release**
- **FR-015** — This repository's `.claude/shipgate.md` is rewritten to the lean form, keeping
  its project content. shipgate is 0.25.0 in `plugin.json` and `marketplace.json`. The
  changelog entry names #15, #16, #17 and #18. shipgate-hud does not change.

## Success criteria

- **SC-001** — Tests prove `signals.py` reads the user file at `$CLAUDE_CONFIG_DIR/shipgate.md`
  and at `~/.claude/shipgate.md`, labels its values `user shipgate.md`, lets a project
  section replace a user section whole, and lets an umbrella section replace a user section.
- **SC-002** — Tests prove per-section resolution between a repo and its umbrella: a repo
  `## Code signals` with one value hides the umbrella's other values of that section; a repo
  section with placeholders only lets the umbrella's section through.
- **SC-003** — Tests prove `Inherit: none` drops the umbrella's sections and keeps the user
  file's, and that `config.inherit` and `config.files` report it.
- **SC-004** — Tests prove `doctor` reports: a ledger named in the config and absent from the
  sidecar; a ledger that differs; a home that differs; agreement; a home not compared. The
  text form carries one line per drift. Every existing doctor key is unchanged.
- **SC-005** — Tests prove the boilerplate recogniser strips every catalogued form from a
  config built from the current template and from this repository's own config as it stood
  before this change, keeps every hand-written line, keeps a bullet with a real value, is
  idempotent, and writes only with `--apply`.
- **SC-006** — Contract tests prove every config-reading skill cites the layering rule with
  one shared sentence, `model-tiers` holds the discipline block with the five rules, and
  `feature` holds the executive contract while `clarify` and `design` point at it.
- **SC-007** — No test reads a real user file: the test environment sets
  `CLAUDE_CONFIG_DIR` to a path that holds no `shipgate.md`.
- **SC-008** — Every check is green after the last edit: shipgate's unit tests,
  `claude plugin validate` for shipgate and shipgate-hud, the Python 3.9 syntax check on
  every changed script, and the private-data grep over the diff and the untracked files.

## Constraints & assumptions

- Public repo: nothing employer- or customer-specific (root `CLAUDE.md`). Evidence from
  private configs appears as counts only.
- Scripts stay Python 3.9 compatible and standard library only.
- `hooks/` is untouched. A shared config reader lives beside the scripts, loaded by path, as
  `_codegraph.py` is.
- The eval fixtures stay as they are; no eval runs.

## Assumptions (executive)

- Does per-section resolution apply to `signals.py` too, although three tests pin per-key
  mixing? → Yes; the brief states one rule for every reader, and the three tests change to
  the per-section outcome — one rule the script and the skills share is the point of #18.
- When is a section "present"? → Its heading exists and it holds one non-placeholder value;
  placeholders-only is absent — the skills already read a placeholder as absent, and a
  template copy must not blank an umbrella's section.
- `CLAUDE_CONFIG_DIR` set, file absent: fall back to `~/.claude/shipgate.md`? → No; the
  variable replaces the directory, as it does for the harness — one location per machine.
- Does `Inherit: none` also drop the user file? → No; the brief says it takes nothing from
  the umbrella, and the user file is not the umbrella.
- `source` label for a project or umbrella value? → Stays `shipgate.md`; `config.files`
  carries the paths and roles — the existing tests and ADR 0004's guard keep their literal.
- Where does the shared config reader live? → A private module `scripts/_config.py`, loaded
  by path from `signals.py` and `journal.py` — the `_codegraph.py` precedent; `journal.py`
  must not import `signals.py`, which loads codegraph at import.
- Is the boilerplate recogniser a script or a skill instruction? → A script,
  `scripts/lean_config.py`, with an anchor catalogue, a diff by default and `--apply` on a
  yes — a false removal is worse than a missed one, and only a script is testable against
  the catalogue (ADR 0019).
- Where does the doctor read the config from? → The sidecar's project directory only,
  `<project>/.claude/shipgate.md`; the comparison is config against its own sidecar, so the
  chain and the user file play no part.
- Home comparison rule? → The config value's first backticked span, placeholder segments
  (`<plugin>`) read as `*`, trailing slash dropped, compared with the directory of the
  sidecar glob; a value with no `/` is not compared.
- Design fan? → Inline, one architect's worth of design, because the brief fixes the shape
  of every item; the two real forks get ADRs 0018 and 0019.
- Does `signals.py` reading a file outside the plugin directory (a configured
  security-sensitive area here) need an escalation? → The brief names the location, so the
  user decided it; recorded as a user-raised decision.

## Open questions

None.
