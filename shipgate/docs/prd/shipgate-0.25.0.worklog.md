---
type: worklog
title: "Worklog: shipgate 0.25.0 — lean project configs"
created: 2026-11-08
updated: 2026-11-08
tags:
  - worklog
  - shipgate
  - config
status: reviewed
prd: "./shipgate-0.25.0.md"
issue: "#15, #16, #17, #18"
related:
  - ../adr/0018-config-layers-resolve-per-section-nearest-first.md
  - ../adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md
---

# Worklog: shipgate 0.25.0 — lean project configs

> Design + build plan companion to `./shipgate-0.25.0.md`.

---

# Design

## Approach

Minimal change, designed inline: the brief fixes the shape of every item, and the two real
forks are recorded in ADR 0018 (the layering rule, `Inherit: none`, and the shared reader)
and ADR 0019 (the boilerplate recogniser as a script). Three code tracks and one prose track
run in parallel; the contracts between them are fixed here so no track waits on another.

## Architecture

- **`scripts/_config.py`** (new, stdlib, Python 3.9). The one config reader:
  - `CONFIG_RELPATH = ".claude/shipgate.md"`, `USER_CONFIG_NAME = "shipgate.md"`,
    `KNOWLEDGE_SECTION = "knowledge base"`, the roles `project | umbrella | user`.
  - `is_placeholder(value)`, `section_bullets(text, section)` (moved from `signals.py`,
    same behaviour, same regexes), `title_bullets(text)` (the bullets before the first
    heading of level 2 or deeper, same comment and fence handling), `inherit_mode(text)`
    (`none` when a title bullet `inherit` has the value `none`, backticks stripped, any
    case; else `umbrella`), `section_present(text, section)` (any bullet of the section
    whose value, or one of whose backticked spans, is not a placeholder),
    `bullet_value(value)` (the first backticked span, else the bare value; a placeholder
    gives `None`).
  - `user_config_path()`: `Path(CLAUDE_CONFIG_DIR) / "shipgate.md"` when the variable is set
    and not empty, else `Path.home() / ".claude" / "shipgate.md"`; `None` when the home
    directory cannot be found.
  - `ConfigFile(path, role, text)` and `read_layers(candidates, user_path)`: `candidates`
    is a list of `(Path, role)` nearest first; read each file that exists (`errors=
    "replace"`; an `OSError` skips the file); apply `Inherit: none` from the nearest
    project-side file that exists by dropping every `umbrella` entry; append the user file
    with role `user`; dedupe by resolved path, first occurrence wins.
  - `section_owner(files, section)`: the first `ConfigFile` with `section_present`, else
    `None`.
- **`scripts/signals.py`.** Loads `_config` by path (`_load_config_module`, the
  `_load_codegraph` shape) and binds `section_bullets = _config.section_bullets`,
  `_is_placeholder = _config.is_placeholder`. `_config_candidates` returns `(Path, role)`
  pairs: `project` for the start-to-repo-root walk, `umbrella` for `repo.parent` and the
  umbrella roots. `load_config(repo, start)` keeps its `(values, source)` return; a new
  `load_config_layers(repo, start)` returns `LoadedConfig(values, source, files, inherit)`,
  and `load_config` is its first two members. Resolution: `owner = section_owner(files,
  "code signals")` gives `parse_code_signals(owner.text)`; `owner = section_owner(files,
  "code tooling")` gives `parse_code_graph(owner.text)`; each value's source label is
  `user shipgate.md` for role `user`, else `shipgate.md`. `Config` gains `files:
  List[Dict[str, str]]` (`{"path", "role"}`) and `inherit: str`; `to_json` emits both;
  `effective_config(file_cfg, file_source, args, files=(), inherit="umbrella")`. The three
  call sites pass the layers. The `--help` epilog describes the order.
- **`scripts/journal.py`.** Loads `_config` by path (`_load_config_module`). `run_doctor`
  adds a top-level `config` key beside `sidecar`, from `config_report(resolution)`:
  - `path`: `resolution.project_dir / .claude/shipgate.md`; `found`.
  - `inherit`: `_config.inherit_mode(text)`.
  - `ledger`: `{"config": <bullet_value of Ledger:>, "sidecar": <sidecar ledger or null>,
    "drift": <line or null>}`. Drift lines: ``config names ledger `X`; the sidecar has no
    ledger key``; ``ledger differs: config `X`, sidecar `Y` ``; ``sidecar names ledger `Y`;
    the config names none (default docs/ledger.md)`` (only when `Y` differs from the
    default).
  - `homes`: for `prd`, `adr`, `worklog`, from `PRD home:`, `ADR home:`, `Worklog home:`:
    `{"config", "sidecar", "compared", "drift"}`. The config directory: trailing `/`
    dropped, every `<...>` segment read as `*`; compared only when the value holds a `/`
    and its last segment holds no `.`. The sidecar directory: the POSIX dirname of the
    sidecar glob (the default glob when the key is absent). Drift line: ``<key> home
    differs: config `docs/prd/`, sidecar glob `src/docs/prd/*.md` ``. A config value that is
    not compared has `compared: false` and no drift. An absent config value is not compared.
  - `drift`: the list of drift lines, in the order ledger, prd, adr, worklog.
  - No sidecar: `config` still reports `found`, `path`, `inherit` and the config values,
    with `sidecar: null` everywhere and `drift: []`.
  - `render_doctor` adds `config          : <path> — agrees | DRIFT (n) | not found` after the
    sidecar lines, then one `drift           : <line>` per drift. Labels keep the 16-column
    padding. Exit code unchanged.
- **`scripts/lean_config.py`** (new). The recogniser of ADR 0019. CLI:
  `lean_config.py <path> [--apply] [--user <path>] [--drop-equal] [--json]`. Default output:
  one summary line (`lean_config: N block(s) to remove, M section(s) equal to the user
  file`) then the unified diff (`difflib.unified_diff`, `a/<path>` and `b/<path>`), or the
  summary alone when nothing changes. `--json`: `{"path", "removals": [{"start", "end",
  "kind", "anchor"}], "equal_sections": [...], "changed": bool, "diff": "..."}` (1-based
  inclusive lines). `--apply` writes the result and prints the summary. Blocks and anchors
  as ADR 0019 §1–3. Fenced code is never removed. The title line (the first `#` heading) is
  never removed.
- **Skills and docs.** The shared config callout (pinned by a contract test) replaces the
  eleven `> **Project config:** …` blockquotes and the `/shipgate` command's sentence:

  > **Config:** `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file
  > `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`) override the defaults
  > below. They layer per section by the rule in `config-template.md`'s header and the
  > README's Configuration section; read them first if present.

  `implement`'s callout keeps its Style tail after the shared text. `feature` gains a
  section **The executive contract** (what is recorded where; what is escalated: one-way
  doors, user-visible scope changes, Security-sensitive areas, true 50/50s, the config's
  Extra escalations), and its route step names the file each section came from when more
  than one config file was read. `clarify`, `design`, `setup` and the glossary point at
  `feature`'s section. `model-tiers` gains the blockquote **Built-in worker discipline**
  with eight rules (the three it had, then the five of FR-007), pasted into every brief
  word for word, before the config's Worker guardrails. `knowledge-base` carries the
  promotion defaults (FR-009). `implement` and `structured-debug` carry the context7
  default (FR-010). `setup` Step 2 adds the user-file offer, Step 3 writes the lean form,
  Step 4 runs `lean_config.py` (diff, ask, `--apply`), reads `doctor --json`'s `config`
  block and regenerates the sidecar from it, and offers `--drop-equal` for sections equal
  to the user file's. The template's header states the layering rule, `Inherit: none` and
  the user file; sections that are usually personal carry `<!-- Usually personal … -->`;
  the Autonomy section is `Mode` and `Extra escalations`; the Worker guardrails comment
  points at `model-tiers` and its examples are repo-specific; the Ledger comment names the
  built-in promotion defaults; the Library docs line notes the context7 default. The
  README's Configuration section states the rule, the user file, `Inherit: none`, the lean
  setup, and updates the Autonomy, Worker guardrails, Knowledge base and Code tooling rows,
  the `doctor` row and the scripts list. `docs/glossary.md`: `config` covers the project and
  user files; `escalation contract` points at `feature`.
- **Tests.** `tests/test_config.py` (new): `_config.py` units. `tests/test_lean_config.py`
  (new): `lean_config.py` through subprocess, fixtures under `tests/fixtures/configs/` (the
  template filled in, this repository's config before this change as `before-0.25.0.md`, a
  hand-written config).
  `test_signals.py`: `hermetic_env` sets `CLAUDE_CONFIG_DIR` to a fresh empty temp dir; the
  three per-key tests move to the per-section outcome; new user-file, `Inherit: none`,
  `files` and `inherit` tests; in-process `load_config` tests patch the environment.
  `test_codegraph.py`: its env helpers isolate `CLAUDE_CONFIG_DIR` the same way.
  `test_journal.py`: `TestDoctor` gains the config drift cases of SC-004. `test_prose.py`:
  the shared callout in eleven skills and the command (identical copies), the discipline
  block in `model-tiers` with the five rules, `feature` owns the contract and `clarify`
  and `design` cite it, the template header and the README state the rule.

## Data flow

`signals.py` → `_config_candidates` (paths with roles) + `user_config_path` →
`_config.read_layers` (read, `Inherit`, dedupe) → `section_owner` per section →
`parse_code_signals` / `parse_code_graph` on the owner → `effective_config` (flags win) →
`config` in the JSON with `source`, `files`, `inherit`.

`journal.py doctor` → `resolution.project_dir/.claude/shipgate.md` → `_config.section_bullets`
on `knowledge base` → compare with `sidecar.config` → `config` block + text lines.

`setup` update mode → `lean_config.py <config>` (diff) → user's yes → `--apply` →
`doctor --json` → `config.drift` → regenerate the sidecar → `setup-completed`.

## Reference implementation

- `_config.py` and `lean_config.py` mirror `_codegraph.py` for the module shape (a private
  module beside the scripts, loaded by path, a module docstring that states the contract)
  and `signals.py`'s `section_bullets` for the walker. `lean_config.py` mirrors
  `journal.py`'s CLI shape (argparse, exit codes 0/1/2, `--json`).
- The doctor block mirrors the existing `sidecar` block in `run_doctor` and the
  off-vocabulary lines in `render_doctor`.
- The contract tests mirror `test_prose.py`'s `READERS` / `READ_STEM` shape.

## Risk ranking (design)

`hotspots` over the plan's files, source `graph`: `shipgate/README.md` (churn top · fix
high), `skills/review/SKILL.md` (top · mid), `skills/feature/SKILL.md` (top · mid),
`skills/structured-debug/SKILL.md` (top · high), `shipgate/scripts/journal.py` (top · high ·
fan-in low). `journal.py`'s doctor is pinned by `TestDoctor` before the change; the new
config block is additive and every existing key keeps its test. `signals.py`'s config chain
is pinned by `TestConfig` and `TestCodeGraphConfig`; three tests change on purpose, as the
behaviour changes (ADR 0018). The prose files are pinned by `test_prose.py`, which gains the
new contract tests before the prose changes.

## CLAUDE.md / impact-map compliance

- Public repo: generic names only; counts from private configs only; the diff and the
  untracked files are grepped before review.
- `hooks/` untouched. `_config.py` is loaded by the scripts only.
- Python 3.9 syntax in every script; standard library only.
- shipgate 0.25.0 in `plugin.json` and `marketplace.json`; release notes only in
  `CHANGELOG.md`. shipgate-hud unchanged.
- The eval fixtures and `baseline.json` untouched; no eval run.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).

## Code

- [x] T001 [P] — `_config.py` and the `signals.py` chain: the shared reader, `(path, role)`
  candidates, `read_layers` with `Inherit: none`, per-section owners, `user shipgate.md`
  labels, `files` and `inherit` in `config`, the `--help` order; `hermetic_env` isolates
  `CLAUDE_CONFIG_DIR`; the three per-key tests move to per-section; new tests for the user
  file (both locations), per-section replacement, placeholders-only, `Inherit: none`,
  `files`, `inherit`; `_config.py` unit tests. — files: `shipgate/scripts/_config.py`,
  `shipgate/scripts/signals.py`, `shipgate/tests/test_signals.py`,
  `shipgate/tests/test_codegraph.py`, `shipgate/tests/test_config.py` — done when: the new
  tests fail before the change and pass after; `test_signals.py`, `test_codegraph.py`,
  `test_signals_trace.py` and `test_config.py` are green.
- [x] T002 [P] — `journal.py doctor`'s `config` block and text lines (the contract above);
  tests for a ledger absent from the sidecar, a ledger that differs, a home that differs,
  agreement, a not-compared home, no config file, no sidecar; every existing doctor key
  unchanged. — files: `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` —
  done when: the new tests fail before and pass after; `test_journal.py`, `test_hooks.py`
  and `test_hud_contract.py` are green.
- [x] T003 [P] — `lean_config.py` and its tests: blocks, the anchor catalogue, placeholder
  bullets, the `Executive contract` bullet, residue rules, `--apply`, `--user` and
  `--drop-equal`, `--json`, idempotence; fixtures: the template filled in, this repository's
  config before the change, a hand-written config that comes back unchanged. — files:
  `shipgate/scripts/lean_config.py`, `shipgate/tests/test_lean_config.py`,
  `shipgate/tests/fixtures/configs/*.md` — done when: the tests fail before and pass after;
  `lean_config.py` on the current `.claude/shipgate.md` removes exactly the setup header,
  the Code signals comment and the `Executive contract` bullet.

## Prose

- [x] T004 [P] — the skills, template, README, glossary and command: the shared callout in
  eleven skills and `commands/shipgate.md`; `feature`'s executive contract and route-step
  line; `clarify`, `design`, `setup` point at it; `model-tiers`' discipline block;
  `knowledge-base`'s promotion defaults; `implement` and `structured-debug`'s context7
  default; `setup`'s Steps 2–4 and Output; the template's header, personal markers,
  Autonomy, Worker guardrails, Ledger and Library docs lines; the README's Configuration
  section, table rows, `doctor` row and scripts list; the glossary; `test_prose.py`'s
  contract tests. — files: `shipgate/skills/*/SKILL.md`, `shipgate/commands/shipgate.md`,
  `shipgate/config-template.md`, `shipgate/README.md`, `shipgate/docs/glossary.md`,
  `shipgate/tests/test_prose.py` — done when: the new contract tests fail before and pass
  after; `test_prose.py`, `test_signals.py`'s and `test_codegraph.py`'s template tests are
  green.

## Release

- [x] T005 — this repository's `.claude/shipgate.md` in the lean form (through
  `lean_config.py`, then by hand for what it does not catch), CHANGELOG 0.25.0 naming #15,
  #16, #17 and #18, `plugin.json` and `marketplace.json` at 0.25.0. — files:
  `.claude/shipgate.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json` — done when: `claude plugin validate shipgate` passes
  and the private-data grep is clean.

## Traceability
- FR-001 → T004; FR-002, FR-003, FR-004, FR-005 → T001; FR-006 → T004
- FR-007, FR-008, FR-009, FR-010, FR-011, FR-012 → T004
- FR-013 → T003, T004; FR-014 → T002, T004; FR-015 → T005
- SC-001, SC-002, SC-003, SC-007 → T001; SC-004 → T002; SC-005 → T003; SC-006 → T004;
  SC-008 → review

## Deviations & notes (filled during implementation)

- 2026-11-08 — T001: in `section_present`, an empty backticked span (`` `` ``) counts as a
  value, not a placeholder: `Ranking exclude: ``` turns the built-in list off, and the
  brief's `is_placeholder` rule would have made that section absent. Only `<…>` spans are
  placeholders for presence. Impact: none on the PRD; FR-002 reads "angle-bracket
  placeholder".
- 2026-11-08 — T001: `read_layers` dedupes by resolved path before it applies
  `Inherit: none`, so a home file that is also an umbrella candidate reads as an umbrella
  file and `Inherit: none` drops it, as ADR 0018's Consequences say. When `Inherit: none`
  sits in an umbrella file (no project file exists), that file keeps itself and drops the
  other umbrella files. `title_bullets` also reads a bare `Key: value` line at column 0
  (the key starts with a letter, at most four words), which FR-005's bare form needs.
- 2026-11-08 — T002: the sidecar side of a home comparison also drops a `./` prefix and a
  trailing `/`; a path segment reads as `*` only when it is a non-empty `<…>`; a config file
  that exists but cannot be read reports `found: false`.
- 2026-11-08 — T003: the `before-0.25.0.md` fixture replaces the maintainer's handle in the
  tracker line with `owner/pandora` (root CLAUDE.md: no handles in fixtures); line numbers
  are unchanged. A placeholder value is one balanced `<…>` group, or several joined by text
  with whitespace, optionally in backticks, so `- Pattern: <type>/<slug>` stays. The
  `Executive contract` key match drops a trailing `(…)` and backticks. Blank lines collapse
  only when a block was removed, never inside a fence. The script has its own parser and
  does not load `_config.py`.
- 2026-11-08 — T004: the knowledge-base promotion defaults apply to an entry that neither
  the type routing nor a config target gives a home, so engineering learnings still route
  to the repo. The executive-contract contract test checks `design`'s Executive mode
  paragraph only, because the reversibility lens still says "one-way door" on purpose.
- 2026-11-08 — T005: the changelog, `plugin.json` and `marketplace.json` were edited by the
  orchestrator (release notes, not product code); the config rewrite ran through
  `lean_config.py --apply` and two hand edits (a generic Orchestration comment, the built-in
  promotion targets on the `Ledger:` line).
- 2026-11-08 — review round 1: `lean_config.py`'s summary line carries the equal-sections
  clause only with `--user`, and a shadowed clause only with `--umbrella` (the contract
  above said always). `_config.is_placeholder` now strips one pair of backticks before the
  test, so `` `<x>` `` is a placeholder for it too; `parse_code_graph` is unchanged in
  effect. `_config.py`'s `section_bullets` joins indented prose lines under a bullet into
  that bullet's value, as `signals.py` did before; the doctor does not read `Database:`,
  and a lean config holds no such prose. The doctor's `config` block gained `section`
  (`present` or `absent`); an absent section compares nothing and the text line says so.

## Rejected findings

See each review round below.

# Review

## Review round 1

Review Workflow run `wf_6486fd98-713`: three lenses (correctness, conventions+design,
simplicity+security), Opus finders, `verify: high-only`, risk-ordered. Counts: 39 found, 33
after dedupe, 25 candidates over the floor of 60, 6 refuters on the 3 HIGH candidates, 24
survivors (2 HIGH held 0/2, 9 MEDIUM, 13 LOW), 1 killed, 8 below the floor. The
orchestrator read every survivor and the below-floor list. Taken as fixes: F1, F3 to F8,
F10 to F14, F16 to F21, F23, F24, and four below-floor notes (the `Inherit: none` value
with trailing text, `CONFIG_RELPATH`'s own copy in `signals.py`, the `--help` wording on
which file `Inherit` is read from, the changelog's line on the config rewrite). Verdict: not
ready.

- F1 HIGH `shipgate/scripts/lean_config.py:256` — a bullet whose value is a placeholder swallows its indented sub-bullets, so real nested values go with it.
- F2 HIGH `shipgate/scripts/lean_config.py:291` — a prefix anchor removes the whole paragraph, including a sentence a user appended to a boilerplate paragraph. Rejected below.
- F3 MEDIUM `shipgate/scripts/lean_config.py:274` — a real value shaped `<type>: <summary>` reads as a placeholder, because any whitespace may join two `<…>` groups.
- F4 MEDIUM `shipgate/scripts/lean_config.py:249` — an autolink or a mention (`<https://…>`, `<ops@x>`, `<@alice>`) reads as a placeholder in both scripts.
- F5 MEDIUM `shipgate/scripts/_config.py:51` — two placeholder definitions: `_config` calls `<type>/<slug>` a placeholder, `lean_config` a real value.
- F6 MEDIUM `shipgate/scripts/lean_config.py:400` — `--drop-equal` ignores the umbrella layer, so dropping a project section can hand the section to the umbrella, not the user file.
- F7 MEDIUM `shipgate/scripts/journal.py:4042` — the doctor reports drift against a Knowledge base the project file does not hold, when another layer owns the section.
- F8 MEDIUM `shipgate/skills/clarify/SKILL.md:97` — the skills say "executive contract", the glossary has only "escalation contract".
- F9 MEDIUM `shipgate/scripts/lean_config.py:231` — a hand-written line directly under an anchored line, with no blank between, joins the paragraph and goes with it. Rejected below, with F2.
- F10 MEDIUM `shipgate/skills/setup/SKILL.md:182` — update mode does not actively offer `--drop-equal` (FR-012).
- F11 MEDIUM `shipgate/scripts/signals.py:338` — a `## Code signals` section with bare values only counts as present and contributes nothing, so it hides the umbrella's and the user's section.
- F12 LOW `shipgate/scripts/lean_config.py:488` — `--apply` rewrites CRLF to LF and writes in place without an atomic replace.
- F13 LOW `shipgate/scripts/_config.py:3` — the docstring says `lean_config.py` loads the module; it did not. True after F5.
- F14 LOW `shipgate/README.md:47` — "reads up to three files" undercounts the start-to-root walk.
- F15 LOW `shipgate/scripts/journal.py:78` — `_load_config_module` is duplicated in both scripts. Rejected below.
- F16 LOW `shipgate/scripts/signals.py:360` — `signals.py` reaches into `_config`'s private regex and keeps its own `CONFIG_RELPATH`; the `load_config` wrapper is kept on purpose (see below).
- F17 LOW `shipgate/scripts/lean_config.py:209` — text after `-->` on a comment's last line is removed with the comment.
- F18 LOW `shipgate/scripts/lean_config.py:436` — the summary line shows the equal-sections clause only with `--user`; the worklog contract said always. Recorded as a deviation.
- F19 LOW `shipgate/scripts/journal.py:4046` — the not-found `config` block lacks the path and the stable `ledger`/`homes` keys.
- F20 LOW `shipgate/scripts/lean_config.py:193` — a fence closes on a marker with an info string, so anchored text inside a fence can be removed.
- F21 LOW `shipgate/scripts/journal.py:4083` — a recursive sidecar glob (`docs/prd/**/*.md`) reports false drift.
- F22 LOW `shipgate/scripts/signals.py:436` — `effective_config` grew two pass-through parameters. Rejected below.
- F23 LOW `shipgate/scripts/lean_config.py:355` — blank-line runs collapse everywhere once anything is removed, so the diff shows unrelated edits.
- F24 LOW `shipgate/docs/adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md:52` — the ADR's catalogue lags the shipped anchors; `Usually personal` is short enough to match a hand-written comment.

### Rejected findings

- `shipgate/scripts/lean_config.py:291` (HIGH 90, F2) and `shipgate/scripts/lean_config.py:231` (MEDIUM 70, F9): rejected in round 1 as ADR 0019's stated limit (anchors over full-text equality; the diff-and-yes gate as the safeguard). **Overruled by the team lead after round 3**: on seven real configs the anchor-prefix rule removed project content in two (a setup header paragraph followed by project sentences; an `Executive contract` bullet whose escalation list named project cases). Reopened as round 4 and fixed: a block goes only when every sentence in it is catalogued boilerplate, else it stays whole and is listed as mixed. The short anchors stay comment-only or lengthened (F24).
- `shipgate/scripts/journal.py:78` (LOW 75, F15): the duplicated loader is the repository's pattern; `_load_hooks_common` already sits in both scripts with a "keep the two in step" note, and a shared helper would put a scripts' concern into the hooks' module.
- `shipgate/scripts/signals.py:436` (LOW 60, F22): two pass-through fields on `effective_config` are smaller than a second construction path through `_replace`.
- `shipgate/scripts/signals.py:360` (LOW 70, the `load_config` half of F16): the wrapper is the documented entry the tests and ADR 0004 use; it stays. The private-regex reach is fixed.
- Below the floor, not taken: `bullet_value` takes the first backticked span (LOW 55; the path is the first span by the template's form); "offer once per machine" has no memory (LOW 45; the existence check is the memory: a declined offer leaves no file, and the next `setup` run offers again; the skill says so now); `journal.py:4051` as above.

## Review round 2

One `code-reviewer` (Opus) with all lenses on the fix scope. It confirmed F1, F3 to F8, F10
to F14, F16, F17, F19 to F21, F23, F24 and the below-floor notes fixed, each on a `file:line`
or a test name, ran `test_config.py` (40, OK), `test_lean_config.py` (44, OK),
`test_signals.py` (115, OK, 1 skipped), `test_prose.py` (19, OK) and `TestDoctor` (25, OK),
and probed the scripts on scratch files. Eleven new findings, one HIGH. Verdict: not ready.

- N1 HIGH `shipgate/skills/setup/SKILL.md:187` — the `--drop-equal --apply` command also removes every boilerplate block, so a user who declined the strip gets it anyway, with no diff shown; `lean_config.py` has no mode that drops the equal sections alone.
- N2 LOW `shipgate/skills/setup/SKILL.md:178` — the first run never passes `--umbrella`, so the equal-sections count includes shadowed ones, and the skill does not say where the umbrella paths come from.
- N3 LOW `shipgate/scripts/lean_config.py:284` — a nested bullet after a blank line (a loose list) is not counted as nested, so a placeholder parent goes and the child is orphaned.
- N4 LOW `shipgate/config-template.md:16` — the template's layer list says "the repo's `.claude/shipgate.md`" where the README now says the files from the working directory up to the repo root; the two homes disagree.
- N5 LOW `shipgate/CHANGELOG.md:?` — the changelog's `lean_config.py` usage lacks `--umbrella`, the doctor bullet lacks `section`, the `_config.py` bullet names two loaders; ADR 0019 §1 omits exit 1.
- N6 LOW `shipgate/scripts/lean_config.py:464` — a section is reported shadowed although the project file says `Inherit: none`.
- N7 LOW `shipgate/scripts/journal.py:4140` — the doctor text says `agrees` when there is no sidecar to compare against.
- N8 LOW `shipgate/scripts/lean_config.py:412` — removing a comment that sits between two prose lines joins them into one paragraph.
- N9 LOW `shipgate/scripts/_config.py:197` — `Inherit: **none**` reads as `umbrella`.
- N10 LOW `shipgate/scripts/_config.py:55` — any `word:` at the start of a `<…>` group reads as a URI scheme, so `<e.g.: x>` is a real value.
- N11 LOW `shipgate/scripts/lean_config.py:543` — `write_atomic` changes the owner of a file owned by someone else and splits a hard link. Taken as a docstring note.

## Review round 3

The orchestrator gated the N1 to N11 fix diff itself, the two-round cap being reached and
the diff being small: `--only-equal` marks nothing but the equal sections (N1, pinned by
`TestOnlyEqual`, three tests); `setup` previews the drop on its own diff with `--only-equal`
and passes `--umbrella` on both runs, naming where the paths come from (N1, N2); a bullet
block runs across blank lines while the next line is indented (N3); the template's layer
line and the README agree, with a second anchor for the new wording (N4); the changelog and
ADR 0019 §1 name `--umbrella`, `--only-equal`, `section` and exit 1 (N5); the shadow check
skips a file that says `Inherit: none` (N6); the doctor says `no sidecar to compare` (N7);
one blank line is kept between two paragraphs around a removed comment (N8);
`inherit_mode` strips Markdown emphasis (N9); a URI needs `://` or `mailto:` (N10); the
`write_atomic` docstring names the owner and hard-link effects (N11). One note, not taken:
a removed comment between a bullet and a column-0 paragraph adds no blank line, so the
paragraph reads as a lazy continuation of the bullet; the readers' values do not change.
Fresh runs after the last edit: the full suite `Ran 1183 tests in 427s, OK (skipped=2)`,
exit 0; `claude plugin validate shipgate` and `shipgate-hud` pass; the Python 3.9 syntax
check over the ten changed Python files exits 0; the private-data grep over `git diff main`
and the untracked files hits only the marketplace owner fields already on `main`; `hooks/`,
`evals/` and `shipgate-hud/` have no change; `lean_config.py` on this repository's config
reports 0 blocks. Verdict: ready.

## Review round 4

The team lead ran `lean_config.py` (no `--apply`) on seven real configs: two lost project
content, so the round-1 rejection of F2 and F9 was overruled and the stream reopened
(`flow-resumed`, a user `gate-decision`). The rule became: an anchor selects a block, and the
block goes only when every sentence in it is catalogued boilerplate; otherwise it stays whole
and is listed as mixed with a hint; the `Executive contract` bullet goes only with a
catalogued escalation list. `lean_config.py` holds a 154-sentence catalogue (the 13 template
versions in git history, the setup-written header, five contract wordings) and four patterns
for sentences with a variable part (a date, a version tag, an example issue number, an
example branch), so no example id from the history enters the repo. Fixtures
`mixed-contract.md` and `mixed-header.md`. The README, `setup` Step 4 and ADR 0019 §2 state
the rule and the "handle the mixed blocks" step. One Opus reviewer on the fix diff confirmed
F2 and F9 fixed on evidence (probes on an appended sentence, a header with project
sentences, a contract with a project case, a line under an anchored line, every fixture
invariant) and reported eight new items, all taken:

- M1 MEDIUM `shipgate/scripts/lean_config.py:162` — two historical sentences were left out of the catalogue (they held example ids), so 4 of 13 template versions showed false mixed blocks. Fixed with two generalised patterns and a test over every version.
- L1 LOW `shipgate/scripts/lean_config.py:852` — after `--apply`, the `mixed:` lines gave the old file's line numbers. Fixed: the written file's numbers.
- L2 LOW `shipgate/scripts/lean_config.py:803` — a mixed block inside a section `--drop-equal` removed was still reported as kept. Fixed.
- L3 LOW `shipgate/scripts/lean_config.py:157` — the contract hint named an `Extra escalations` line the same run may remove. Reworded: add the cases to an `Extra escalations` line, then delete the bullet.
- L4 LOW `shipgate/scripts/lean_config.py:638` — a placeholder contract value was kept as mixed. Fixed: removed as a placeholder.
- L5 LOW `shipgate/skills/setup/SKILL.md:198` — the "run the script again" step did not repeat the diff-and-yes gate. Fixed.
- L6 LOW `shipgate/docs/adr/0019-the-boilerplate-recogniser-is-a-script-with-an-anchor-catalogue.md:86` — "every consecutive non-blank line" omitted the lines that start a block of their own. Fixed.
- L7 LOW `shipgate/scripts/lean_config.py:631` — a contract key with a colon inside its parenthesis split at the wrong place. Fixed: the sentences start after the matched key.

The orchestrator gated the eight small fixes itself. Fresh runs after the last edit are in
the `verify-run` event and the report. Verdict: ready.
