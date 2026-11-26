---
type: worklog
title: "Worklog: verify-run records an observed run, not a claim"
created: 2026-11-25
updated: 2026-11-26
tags:
  - worklog
  - shipgate
  - verify
  - hooks
status: review
prd: "./observed-verify-run.md"
issue: "#27 (shipgate), child of #37"
related:
  - "../adr/0032-the-bash-hooks-log-each-observed-run-by-session.md"
  - "../adr/0033-a-verify-run-names-its-commands-and-the-journal-records-what-it-saw.md"
  - "../adr/0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "../adr/0023-the-users-go-is-recorded-where-the-user-answers.md"
---

# Worklog: verify-run records an observed run, not a claim

> Design + build plan companion to `./observed-verify-run.md`. Issue #27, child of #37.

---

# Design

## Approach

Designed inline, with no architect fan. The user settled the three forks in the clarify
dialog (hook contract, event shape, scope), and the code leaves one layout for the rest.
The core trade-off: a second writer in the PreToolUse hook buys a match that survives a
command rewrite, at a few milliseconds per Bash call in a journaled project.

ADR 0032 (hook contract) and ADR 0033 (event shape) hold the decisions. Each is a one-way
door. The user accepted both on 2026-11-25, in a question dialog relayed by the lead
("Accept and build"), so the build may start at T001.

## Architecture

```text
Bash call (main session or subagent)
  │
  ├─ PreToolUse ── pre_tool_use.py main()
  │                 └─ _observe_start(): walk up from payload cwd with isfile
  │                      └─ sidecar found → import _runs → record_start()
  │                           └─ <base>/shipgate/runs/<session>.jsonl  += {"i","h"}
  │
  ├─ (the command runs; another PreToolUse hook may have rewritten it)
  │
  ├─ PostToolUse ─────────┐
  └─ PostToolUseFailure ──┴─ post_tool_use.py main()
                              └─ likely_journaled() → find_project(payload cwd)
                                   └─ _runs.record_end() → += {"i","x"} when the exit is known

journal.py append --type verify-run   (CLAUDE_CODE_SESSION_ID = the session)
  └─ append_event()
       ├─ normalize_payload: commands[{cmd, exit}] required
       ├─ _settle_verify_outcome(): derive outcome / refuse a disagreement
       ├─ check_payload_size (1 KB)
       ├─ pop observed / contradicted; runs.observe(commands, session)
       │    └─ read <session>.jsonl.1 + <session>.jsonl, join i → h, newest run per hash
       └─ store observed (+ contradicted); notices → cli prints them

journal.py stats   → verify_observed / _unobserved / _contradicted / _unrecorded + share
journal.py doctor  → the runs store: files, size, next prune, refused names
flow-started / terminal append → runs.prune_old_runs() (7 days)
```

Components:

- `hooks/_common.py` (changed): `RUNS_PARTS = ("shipgate", "runs")`, `RUNS_FILE_BYTES =
  256 * 1024`, `runs_root()` and `run_fingerprint(command)`. The journal loads `_common` by
  path (`scripts/_journal/plugin.py:15-38`), so both sides share one definition.
  `run_fingerprint` imports `_blake2` lazily and falls back to `hashlib.blake2b`.
  Importing `_common` still loads neither `re` nor `hashlib`.
- `hooks/_runs.py` (new): the writer. `record_start(payload, command, root_dir)`,
  `record_end(payload, project)`, and a private `_append(session, row)` with the open,
  rotate and write rules of ADR 0032. It validates the session id and the `tool_use_id`
  with string methods, not `re`.
- `hooks/pre_tool_use.py` (changed): one call, `_observe_start(payload, command)`, at the
  top of `main()` after the command is read. About 15 lines: the inline walk, then a lazy
  import of `_runs`, all inside `try/except`. Nothing else in the file changes.
- `hooks/post_tool_use.py` (changed): `main()` reads `hook_event_name`. On
  PostToolUseFailure with `tool_name` Bash it calls `record_end` and exits. On PostToolUse
  for Bash it calls `record_end` before the existing claims and nudge. The project is
  loaded once per call and passed to both `record_end` and `record_bash_claims`.
- `hooks/core.json` (changed): a `PostToolUseFailure` entry, matcher `Bash`, the same
  `post_tool_use.py`, timeout 10.
- `scripts/_journal/runs.py` (new): `read_session_runs(session)`, `observe(commands,
  session) -> Observation`, `prune_old_runs()`, `survey_runs()`. No import of `hooks/` other
  than through `plugin._hooks_common`.
- `scripts/_journal/vocab.py` (changed): the `verify-run` shape of ADR 0033, and
  `RUNS_KEEP_DAYS = 7`, `RUNS_READ_BYTES = 1024 * 1024`.
- `scripts/_journal/append.py` (changed): `_settle_verify_outcome(payload)` after
  `normalize_payload`; the pop-and-set of `observed` / `contradicted` after the cap check,
  beside `recorded_by`; `prune_old_runs()` beside `prune_ended_stream` and
  `prune_old_evidence`; `AppendResult.notices: Tuple[str, ...] = ()`.
- `scripts/_journal/cli.py` (changed): prints each notice after its `appended` line, for a
  single append and for each line of `--batch`.
- `scripts/_journal/stats.py` (changed): four counts per stream, in `STATS_SUMS`, and the
  share; two text columns (`obs`, `ctr`) and one footer line with the share.
- `scripts/_journal/doctor.py` (changed): one block for the runs store.

## Data flow

1. PreToolUse receives the command as the model typed it. In a journaled project it
   appends `{"i": tool_use_id, "h": fingerprint}` to the session's file.
2. The command runs. A rewrite hook may change it; that does not touch the start row.
3. PostToolUse (exit 0, or an interpreted exit) or PostToolUseFailure (exit N) fires.
   The post hook appends `{"i": tool_use_id, "x": N}` when N is known (ADR 0032's table).
4. A subagent's run goes through 1 to 3 under the parent's session id.
5. The model appends `verify-run` with `commands`. The journal derives `outcome`, checks
   the cap, reads the session's file, and stores `observed` and maybe `contradicted`.
6. `stats` reads the stored keys. The gates read `outcome` only, as before.

Write path: the hooks write the run log; `append` writes the row. Read path: `append`
reads the run log once per `verify-run`; `stats` reads rows. Shared state: the run log
file, appended by parallel hook processes (whole lines by `O_APPEND`) and read by
`journal.py`.

## Data model / schema

No SQLite schema change. The `events` table keeps `data` as JSON.

- Run log row, start: `{"i": str, "h": str}`; end: `{"i": str, "x": int}`. File
  `<base>/shipgate/runs/<session>.jsonl`, at most 256 KB, plus `<session>.jsonl.1`.
- `verify-run` data: `commands` becomes required (list of objects, each with `cmd` str and
  `exit` int). `outcome` becomes optional on input and is always stored. New journal-owned
  keys: `observed` (bool, always on a new row) and `contradicted` (true, or absent).

Downstream data obligations: none. No migration: old rows stay as they are.

## API / contract changes

- **Hook contract (ADR 0032, one-way door):** PreToolUse writes a file in a journaled
  project; PostToolUseFailure is registered. Release check for a hook change and the full
  `/security-review` apply.
- **Event shape (ADR 0033, one-way door):** `verify-run` without `commands` is refused; an
  `outcome` that disagrees with the exits is refused; `observed` and `contradicted` are
  journal-owned. `vocab --shape verify-run` prints the new shape.
- **CLI output:** `append` may print `not observed: …` lines after `appended …`. A script
  that parses `append` output reads the first line; the notices come after it.
- **`stats --json`:** four new keys per stream and in the totals. Additive.
- Unchanged: `status --json`, `position --json` (the HUD contract), the digest, the
  handoff, the gates.

## Reference implementation

- Hook side: `hooks/_common.py`, the proven module (fix rate 0.11, age `top`, fan-in
  `high`): lazy imports, fail-open helpers, `marker_path`'s check of a session id before it
  names a file (ADR 0023 §12). `_runs.py` mirrors its style; `pre_tool_use.py`'s new call
  mirrors `command_gate`'s lazy `sys.path.insert` and import.
- Store outside the repository: `scripts/_journal/screens.py` (fix rate 0.0, fan-in
  `top`, reviewed in 0.36.0): `evidence_root()` (`:54-69`), the `O_DIRECTORY |
  O_NOFOLLOW` open with `dir_fd`, `prune_old_evidence()` (`:946-969`, never raises, one
  `lstat` with no root) and the doctor survey. `runs.py` mirrors it, much smaller: one flat
  directory, no project key, no stream directory.
- Journal-owned key: `recorded_by` in `append_event` (`append.py:172-178`, ADR 0010).
- Stats share: the existing `share()` use in `stats.py` (`:353`).

## Pre-mortem

Assume this shipped and caused an incident. The likeliest causes, and what the plan does:

1. **Tests write into the developer's real config directory.** `run_hook` does not set
   `CLAUDE_CONFIG_DIR` (`tests/test_hooks.py:48-68`), and many hook tests carry a session
   id. → T001 runs first and makes a temporary directory the default.
2. **The hook slows every Bash call.** → The write lives in `_runs.py` (cached bytecode),
   the PreToolUse walk is inline and reads no file, `re` and `hashlib` stay out of the
   path, and T002/T014 measure before and after against SC-002.
3. **A filesystem error surfaces in the session.** → Every write path sits in
   `try/except` and prints nothing; tests drive a link in place of the directory, a link
   in place of the file, and a read-only directory.
4. **Claude Code changes the `Exit code N` text.** → Failing runs stop being recorded and
   passes still match. A test pins the probe's literal strings, and the ADR names the
   dependency.
5. **Models paraphrase the command.** → The row is stored `observed: false` with a notice
   that says how to fix it; `stats` measures the share. No gate depends on it.

## Risk-ranked files

From `signals.py hotspots` over the files the plan changes (source `graph`):

- `top`: `hooks/pre_tool_use.py` (fix `top`), `hooks/_common.py` (fan-in `high`),
  `tests/test_hooks.py` (fix `top`), `README.md` (fix `high`), the verify, implement and
  model-tiers skills, `docs/glossary.md`.
- `high`: `hooks/core.json` (fix `high`), `hooks/post_tool_use.py`,
  `scripts/_journal/doctor.py`, `tests/test_journal_gates.py`.

Pins before change: T002 adds a test that lists `core.json`'s events and matchers, and a
test that a PreToolUse run in a directory with no settings file creates no `runs`
directory. The existing audit test (`tests/test_hooks.py:3539`) already pins the
PreToolUse fast path; it must pass unchanged after T012.

## Measurement

Bench (from the design session; recreate it in the build's scratchpad). It runs each hook
15 times on a plain Bash payload, in a directory with no settings file and in a journaled
temporary project, with a temporary `CLAUDE_CONFIG_DIR`, and prints the medians:

```python
import json, os, statistics, subprocess, sys, tempfile, time
WT = "<the worktree root>"
base = tempfile.mkdtemp(dir=sys.argv[1])
plain = os.path.join(base, "plain"); os.makedirs(plain)
proj = os.path.join(base, "proj"); os.makedirs(os.path.join(proj, ".claude"))
json.dump({"version": 2, "db": ".claude/shipgate.db",
           "artifact_homes": {"prd": "docs/prd/*.md"}},
          open(os.path.join(proj, ".claude", "shipgate.json"), "w"))
cfg = os.path.join(base, "cfg"); os.makedirs(cfg)
def run(hook, cwd, payload, n=15):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(CLAUDE_CONFIG_DIR=cfg, CLAUDE_PROJECT_DIR=cwd)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run([sys.executable, os.path.join(WT, "shipgate/hooks", hook)],
                       input=json.dumps(payload), text=True, capture_output=True,
                       cwd=cwd, env=env)
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)
for cwd, label in ((plain, "unjournaled"), (proj, "journaled")):
    p = {"session_id": "bench-session", "hook_event_name": "PreToolUse",
         "tool_name": "Bash", "tool_use_id": "toolu_bench", "cwd": cwd,
         "tool_input": {"command": "python3 -m unittest discover -s shipgate/tests"}}
    print(label, "pre ", round(run("pre_tool_use.py", cwd, p), 1))
    q = dict(p, hook_event_name="PostToolUse", duration_ms=1000,
             tool_response={"stdout": "ok", "stderr": "", "interrupted": False})
    print(label, "post", round(run("post_tool_use.py", cwd, q), 1))
```

Design-session numbers (Python 3.15.2, this machine), median ms:

| Hook | No settings file | Journaled |
| --- | --- | --- |
| `pre_tool_use.py` | 44.1 | 44.0 |
| `post_tool_use.py` | 28.0 | 37.2 |

A bare Python start is 24.3 ms. T002 re-measures the baseline on the unchanged tree; T014
measures after. SC-002: at most +1 ms with no settings file, at most +3 ms journaled.

Build baseline (T002, 2026-11-25): the unchanged hooks from `git archive HEAD shipgate`, two
runs of the bench, median ms. A worker ran tests on the same machine at the time, so T014
measures the base tree and the changed tree back to back under the same load.

| Hook | No settings file | Journaled |
| --- | --- | --- |
| `pre_tool_use.py` | 38.3 / 41.4 | 42.2 / 41.1 |
| `post_tool_use.py` | 27.3 / 27.1 | 37.2 / 36.9 |

A bare Python start was 23.9 / 24.0 ms.

After the change (T014, 2026-11-25): `bench2.py` in the scratchpad runs the base tree and
the changed tree in turn, 25 times each per case, so both see the same load. Two runs,
median ms, base → changed (delta):

| Hook | No settings file | Journaled |
| --- | --- | --- |
| `pre_tool_use.py` | 41.2 → 40.9 (−0.2); 40.0 → 38.9 (−1.1) | 40.4 → 41.9 (+1.5); 39.1 → 40.5 (+1.4) |
| `post_tool_use.py`, PostToolUse | 25.6 → 25.4 (−0.2); 27.3 → 27.3 (+0.0) | 35.4 → 34.8 (−0.7); 35.1 → 35.7 (+0.7) |
| `post_tool_use.py`, PostToolUseFailure | 26.3 → 26.4 (+0.1); 25.5 → 25.2 (−0.3) | 33.6 → 33.1 (−0.5); 35.1 → 34.1 (−1.0) |

SC-002 holds: at most +0.1 ms with no settings file, at most +1.5 ms journaled. The changed
journaled run wrote one start row and one end row per call. One cost is outside SC-002's
per-hook measure: before this change a failing Bash call started no post hook, because
PostToolUseFailure was not registered. Now it starts one, which costs about 25 ms with no
settings file (a Python start and the `likely_journaled()` check) and about 34 ms in a
journaled project. A passing call still starts one post hook, as before. This is the cost
of the registration that ADR 0032 decided.

## Executive decisions (design)

Recorded as `gate-decision` events with `gate: design`, `raised_by: orchestrator`.

- No architect fan: the clarify dialog settled the forks; one layout remains.
- The lead's point 1, a check that is no Bash command: an empty `commands` list with a
  required `outcome` and the check in `scope`, stored `observed: false` (ADR 0033).
- The lead's point 2: the verify skill says that a background run is never observed, so a
  run that must count runs in the foreground (T030).
- The lead's point 3: a Workflow agent's run and a run before a new session id count as
  not observed in `stats`; T033 probes a Workflow agent once.
- The lead's point 4: the write lives in `hooks/_runs.py`; `pre_tool_use.py` gets one
  inline walk and a lazy import; the hook is measured before and after (T002, T014).
- The shared path and hash live in `hooks/_common.py`, loaded by the journal by path.
- The append notices go to stdout after the `appended` line and change no exit code.
- The outcome rules are shape errors that `--force` does not waive.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/` only. No shipgate-hud file changes (Q3); capture files the
  HUD follow-up issue.
- Hooks are security-sensitive: the full `/security-review` and the release check for a
  hook change are tasks (T040). The no-op path is pinned by tests (T002, T012, T013).
- Public repo: no private name, path or id in any file, payload or commit; T040 greps the
  diff.
- Version: 0.37.0 in `shipgate/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`, in the same change. The tag `shipgate--v0.37.0` after
  the merge.
- Tests run with `python3 -m unittest discover -s shipgate/tests`; a test that runs a hook
  or `journal.py` gets a temporary `CLAUDE_CONFIG_DIR`. Python 3.9 compatible.
- Schema owner / feature flag: n/a.

## Handoff notes for the build session

The design session's context is not needed. This section holds what lived only there.

**Where things stand.** Clarify passed, design committed, both ADRs accepted (journal
stream `feat/27-observed-verify-run`). Nothing is committed. Start at T001.

**Who you report to.** This stream has a lead: `journal.py handoff` prints `report to`.
Send every question, fork and status report to the lead with `hc send`; do not ask the
user in this pane. A report whose text names the journal script, its `append` subcommand
and a user actor is refused by the forgery net: write it to a file in your scratchpad and
send `"$(cat <literal path>)"`. A pane on a permission prompt answers `blocked`: wait with
an `hc read` loop. Commit, push and PR only through the lead, with the user's go. A hook
change keeps a separate merge question and the release check (#37 plan).

**Which shipgate runs while you build.** The installed plugin points at the main
checkout, so the hooks and `journal.py` that record this flow are the main checkout's
code (0.36.0 on 2026-11-25), not this worktree's. The worktree's code runs only under the test suite and the bench. The
0.36.0 journal accepts a `verify-run` without `commands`; carry `commands` anyway.

**Journal appends.** Record `verify-run` and `task-done` in one `append --batch`. When a
helper script appends a batch file, call it with literal paths: the forgery net refuses a
call whose script or file path comes from an unquoted shell variable.

**Model tiers.** Workers on Opus write the hook and journal code (T010-T024). T022 is
mechanical and may go to a Sonnet sub-worker from its file list. Give each worker its own
copy of any scratchpad helper.

**Review.** `orchestration.review` is `workflow`. The full `/security-review` runs on the
working tree by the `review` skill's method, because the built-in command sees an empty
diff before the commit (T040).

**Probe payloads for the T011 and T013 tests.** Field sets and literal values from the
probe of 2026-11-25 (Claude Code 2.1.332). Every payload also holds `session_id`,
`transcript_path`, `cwd`, `permission_mode`, `prompt_id`, `effort`, `hook_event_name`,
`tool_name`, `tool_input`, `tool_use_id` and `duration_ms`; a subagent's adds `agent_id`
and `agent_type`.

| Case | Event | Fields that decide the row |
| --- | --- | --- |
| exit 0 | PostToolUse | `tool_response: {"stdout": "probe-pass", "stderr": "", "interrupted": false, "isImage": false, "noOutputExpected": false}` |
| exit 3 | PostToolUseFailure | `error: "Exit code 3\nprobe-out\nprobe-err"`, `is_interrupt: false`, no `tool_response` |
| timeout | PostToolUseFailure | `error: "Exit code 143\nCommand timed out after 2s"`, `is_interrupt: false` |
| exit 127 | PostToolUseFailure | `error: "Exit code 127\nzsh: command not found: no-such-command-xyz"` |
| grep, no match | PostToolUse | `tool_response.returnCodeInterpretation: "No matches found"` |
| diff, files differ | PostToolUse | `tool_response.returnCodeInterpretation: "Files differ"` |
| test, false | PostToolUse | `tool_response.returnCodeInterpretation: "Condition is false"` |
| background launch | PostToolUse | `tool_input.run_in_background: true`, `tool_response.backgroundTaskId: "b2soun51s"`, `duration_ms: 5` |
| subagent exit 5 | PostToolUseFailure | parent `session_id`, `agent_id: "ad189dd3d82fd5a69"`, `agent_type: "general-purpose"`, `error: "Exit code 5\nsub-out"` |
| rewritten command | PreToolUse sees `echo rewrite-me`; PostToolUse sees `tool_input.command: "echo rewritten-by-hook"` | the start row hashes the PreToolUse text |

A denied run fires no post event. An interrupted run was not probed: the tests use
`interrupted: true` (PostToolUse) and `is_interrupt: true` (PostToolUseFailure) as the
documented forms.

**Probe method for T033.** A scratch project in the scratchpad with `git init` and a
`.claude/settings.json` that registers one logging hook (a Python script that appends its
stdin JSON to a file) on PreToolUse, PostToolUse and PostToolUseFailure with matcher `*`,
and on SubagentStart, SubagentStop and Stop. Run `claude -p --model haiku
--setting-sources project --allowedTools Bash Agent --no-session-persistence
--max-budget-usd 0.30 --output-format json -- "<prompt>"` from that project, with every
`CLAUDE*` variable removed from the environment except `CLAUDE_CONFIG_DIR`, set to the
config directory the lead names for nested runs. An untrusted scratch project ignores
`permissions.allow` from its own settings, so pass `--allowedTools`. Build the hook's JSON
in Python, not inside `bash -c "…"`.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations

- [x] T001 — Hook tests never reach the real config directory: `run_hook` and every other helper in `tests/test_hooks.py` that starts a hook pass a temporary `CLAUDE_CONFIG_DIR` by default (a test may override it); extend the root `CLAUDE.md` rule ("A test that runs `journal.py`…") to hooks, since the hooks now write under the config directory — file(s): `shipgate/tests/test_hooks.py`, `CLAUDE.md` — done when: a test asserts that a hook started by `run_hook` sees a `CLAUDE_CONFIG_DIR` under the test's temporary directory, and the suite passes.
- [x] T002 — Baseline and pins before change: run the bench of **Measurement** on the unchanged tree and record the medians here; add a test that lists the events and matchers of `hooks/core.json` (fails at T013 by design, then updated), and a test that a PreToolUse run whose payload `cwd` has no settings file creates no `shipgate/runs` directory under `CLAUDE_CONFIG_DIR` — file(s): `shipgate/tests/test_hooks.py`, `shipgate/docs/prd/observed-verify-run.worklog.md` — done when: the numbers are in this worklog and both tests pass on the unchanged tree.

## Hook side

- [x] T010 — Shared path and hash in `_common`: `RUNS_PARTS`, `RUNS_FILE_BYTES`, `runs_root()` (the rule of `evidence_root()`), `run_fingerprint(command)` (BLAKE2b, 8-byte digest, hex, over `command.strip()` encoded UTF-8 with `surrogateescape`; `_blake2` first, `hashlib.blake2b` as fallback); tests first: `runs_root()` and `screens.evidence_root()` share one base for set, empty and unset `CLAUDE_CONFIG_DIR` and `HOME`; the two hash paths agree on samples (ASCII, non-ASCII, a lone surrogate, leading and trailing space); importing `_common` loads neither `re` nor `hashlib` — file(s): `shipgate/hooks/_common.py`, `shipgate/tests/test_hooks.py` — done when: the tests fail first, then pass.
- [x] T011 — The writer `hooks/_runs.py`: `record_start`, `record_end` and `_append` as ADR 0032 states (plain-token session id of at most 128 characters, `tool_use_id` a non-empty str of at most 128 characters, `runs` directory created 0700, opened `O_DIRECTORY|O_NOFOLLOW`, file opened by `dir_fd` with `O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW|O_CLOEXEC` and 0600, regular file only, rotation to `.jsonl.1` at `RUNS_FILE_BYTES`, one `write` per row, every error swallowed, no print); `record_end` applies ADR 0032's table with string methods only; `load_project` decides `db: null` and `enforce.auto_capture: false` — file(s): `shipgate/hooks/_runs.py`, `shipgate/tests/test_hooks.py` — done when: tests built from the probe payloads pass: exit 0 → `x: 0`; `Exit code 3` → 3; `Exit code 143` (timeout) → 143; `Exit code 127` → 127; `returnCodeInterpretation` (grep, diff, test) → no row; `backgroundTaskId` or `run_in_background` → no row; `interrupted` or `is_interrupt` true → no row; a subagent payload (`agent_id`) → a row under the parent `session_id`; `Exit code 256`, `Exit code ３` (non-ASCII digit) and an `error` with no prefix → no row; a link in place of `runs` or of the file → no write and no exception; a read-only `runs` directory → no exception; a file at the cap → rotated, one `.1` kept; two processes appending 500 rows each → 1,000 whole JSON lines.
- [x] T012 — PreToolUse start row: `_observe_start(payload, command)` at the top of `main()` in `pre_tool_use.py`, after the command is read: walk up from the payload `cwd` only, with `os.path.isfile(<dir>/.claude/shipgate.json)`, return at the root; on a hit, insert the hooks directory on `sys.path`, import `_runs`, call `record_start`; all inside `try/except Exception` — file(s): `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py` — done when: the audit test `test_the_fast_path_reads_no_file` passes unchanged; a journaled payload writes exactly one start row with the typed command's hash; a journaled `CLAUDE_PROJECT_DIR` with an unjournaled payload `cwd` writes nothing; `"db": null` and `enforce.auto_capture: false` write nothing; every existing PreToolUse test (net and command gate) passes.
- [x] T013 — Post hooks and registration: `core.json` registers `PostToolUseFailure` (matcher `Bash`, `post_tool_use.py`, timeout 10); `post_tool_use.py` dispatches on `hook_event_name`, writes the end row on both events for Bash, loads the project once and passes it to `record_end` and `record_bash_claims` — file(s): `shipgate/hooks/core.json`, `shipgate/hooks/post_tool_use.py`, `shipgate/tests/test_hooks.py` — done when: the T002 `core.json` test is updated to the new list and passes; a PostToolUseFailure payload writes `x: N` and no artifact claim; a PostToolUseFailure in a directory with no settings file exits 0 with no output and no `runs` directory; the existing claims and nudge tests pass.
- [x] T014 — Measure after: rerun the bench on the changed tree, record the medians beside T002's, and check SC-002 (at most +1 ms with no settings file, at most +3 ms journaled, per hook); over the limit, log a deviation with the cause before going on — file(s): `shipgate/docs/prd/observed-verify-run.worklog.md` — done when: both tables are here and SC-002 holds or a deviation names why not.

## Journal side

- [x] T020 — The reader `scripts/_journal/runs.py`: `read_session_runs(session)` (`.jsonl.1` then `.jsonl`, `O_NOFOLLOW`, regular file only, at most `RUNS_READ_BYTES` in total, a malformed line skipped, never raises) and `observe(commands, session)` → matched / unmatched / contradicted per command, newest end row per hash in file order — file(s): `shipgate/scripts/_journal/runs.py`, `shipgate/scripts/_journal/vocab.py`, `shipgate/tests/test_journal_runs.py` — done when: tests pass for: matched; no run → unmatched; newest run exited otherwise → contradicted; an older failing run then a newer passing one → matched; a start row whose hash is the typed command and no row for the rewritten text → matched (SC-003); no session id → unmatched; a link in place of the file → no log; a log over the read cap → read to the cap; rows split across `.1` and the current file → joined.
- [x] T021 — The shape and the append: the `verify-run` shape of ADR 0033 in `vocab.py`; `_settle_verify_outcome` (derive; refuse a disagreement; require `outcome` with an empty list; not waived by `--force`); pop-and-set `observed` / `contradicted` after the cap check; `AppendResult.notices` and the `not observed: …` lines printed by `cli.py` for single and batch appends — file(s): `shipgate/scripts/_journal/vocab.py`, `shipgate/scripts/_journal/shapes.py`, `shipgate/scripts/_journal/append.py`, `shipgate/scripts/_journal/cli.py`, `shipgate/tests/test_journal_shapes.py`, `shipgate/tests/test_journal_gates.py` — done when: tests pass for SC-004: no `commands` key → refused (exit 4); `cmd: ""` or a negative or boolean `exit` → refused; `outcome: pass` with an exit 1 → refused, also with `--force`; outcome absent → derived; empty list without `outcome` → refused; empty list with `outcome` → stored `observed: false`; a caller's `observed: true` → replaced; a contradicted pass → stored `observed: false, contradicted: true` and still satisfies `task-done`; a 1 KB payload still refused at the same size; `vocab --shape verify-run` prints the new shape.
- [x] T022 — Existing callers carry `commands`: every test and fixture that appends a bare `verify-run` (about 100 sites across `test_journal_gates.py`, `test_journal_check.py`, `test_journal.py`, `test_hooks.py`, `test_journal_shapes.py`, `test_journal_doctor.py`, `test_journal_status.py`, `test_journal_handoff.py`, `test_hud_contract.py`, `test_journal_approval.py`) gets one `commands` item; a shared helper constant where one already exists (`PASSING_VERIFY`). Mechanical: a Sonnet sub-worker may do it from this list. Check the eval fixtures (`shipgate/evals/fixtures/bigshop.py:830` and the cases that copy it) still append a valid row — file(s): `shipgate/tests/test_journal_gates.py`, `shipgate/tests/test_journal_check.py`, `shipgate/tests/test_journal.py`, `shipgate/tests/test_hooks.py`, `shipgate/tests/test_journal_shapes.py`, `shipgate/tests/test_journal_doctor.py`, `shipgate/tests/test_journal_status.py`, `shipgate/tests/test_journal_handoff.py`, `shipgate/tests/test_hud_contract.py`, `shipgate/tests/test_journal_approval.py` — done when: the full suite passes and the HUD contract test's golden output is unchanged.
- [x] T023 [P] — Prune and doctor: `prune_old_runs()` called after a `flow-started` and after a terminal append (beside the evidence prune), deleting `<plain token>.jsonl` and `.jsonl.1` regular files whose mtime is over `RUNS_KEEP_DAYS` old, one at a time, no link followed, never raising, one `lstat` with no root; the doctor block (root, files, bytes, next prune, refused names) — file(s): `shipgate/scripts/_journal/runs.py`, `shipgate/scripts/_journal/append.py`, `shipgate/scripts/_journal/doctor.py`, `shipgate/tests/test_journal_runs.py`, `shipgate/tests/test_journal_doctor.py` — done when: tests pass for SC-005: an 8-day-old file deleted, a fresh one kept, a foreign name and a link kept and reported, no root → nothing and no error; a failed delete is a warning and the event still lands.
- [x] T024 [P] — Stats: per stream and in total `verify_observed`, `verify_unobserved`, `verify_contradicted`, `verify_unrecorded` (in `STATS_SUMS`), the share over rows that carry `observed`, columns `obs` and `ctr`, one footer line — file(s): `shipgate/scripts/_journal/stats.py`, `shipgate/tests/test_journal.py` — done when: tests pass for SC-006 on a journal that mixes old rows, observed rows, unobserved rows and contradicted rows; a row with no `observed` key counts only as not recorded.

## Skills and docs

- [x] T030 — The verify skill's record section: the payload example keeps `commands`; the text says to cite each command exactly as typed (the same string, `cd` and pipes included), run in this session, in the foreground; a background run is never observed, so a run that must count runs in the foreground; `outcome` may be left out and is derived; a check that is no Bash command uses an empty `commands` list, `outcome` and `scope`; the journal owns `observed` and `contradicted`; a `not observed:` line means re-run in the foreground or fix the citation; "Record failures too" stays. Keep the added text short and literal, and read it once as each session model (Opus, Fable) would: no new eval case (PRD assumption) — file(s): `shipgate/skills/verify/SKILL.md`, `shipgate/tests/test_prose.py` — done when: prose tests pin each of those sentences and the existing pins still pass.
- [x] T031 — Worker evidence: `implement` and `model-tiers` say that a worker reports the exact command line it ran and its exit status, verbatim, and that the orchestrator cites them in its own `verify-run`; a subagent's run is in the session's log, so the orchestrator does not re-run it to cite it — file(s): `shipgate/skills/implement/SKILL.md`, `shipgate/skills/model-tiers/SKILL.md`, `shipgate/tests/test_prose.py` — done when: prose tests pin the worker-brief line and the orchestrator line.
- [x] T032 — README, glossary, changelog, version: README hooks section (PreToolUse also writes a start row in a journaled project; PostToolUse and PostToolUseFailure write the exit; what a row holds, where, how long, and that no text or output is kept), the `verify-run` and `stats` parts, and the not-observed cases (background, interpreted exit, new session id, Workflow agent per T033); glossary entries "observed run" and the PostToolUseFailure event; a `CHANGELOG.md` 0.37.0 entry; 0.37.0 in `shipgate/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` — file(s): `shipgate/README.md`, `shipgate/docs/glossary.md`, `shipgate/CHANGELOG.md`, `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: the version test passes and the README links to the changelog without copying it.
- [x] T033 [P] — Probe a Workflow agent once: a nested `claude -p` on Haiku in a scratch project with a logging hook (the design session's method: `--setting-sources project`, `--allowedTools Bash Agent`, `CLAUDE_CONFIG_DIR` set to the eval account), a prompt that asks for a one-agent workflow running one Bash command; record whether its PostToolUse payload carries the parent `session_id` and an `agent_id`; spend at most $0.30 — file(s): `shipgate/docs/prd/observed-verify-run.worklog.md` — done when: the result is a note here and T032's README wording matches it; no code branch depends on it.

## Review and release

- [x] T040 — Security and release checks: the full `/security-review` on the working tree by the `review` skill's method (hooks and a write outside the plugin directory), briefed with ADR 0032's threat cases (a forged row, a planted log, a link in place of the directory or the file, a secret in a command, growth); then, after the merge, the release check for a hook change (`git archive` of the merge commit into the scratchpad, run each changed hook with payloads in an empty directory and in a journaled temporary project with a temporary `CLAUDE_CONFIG_DIR`, confirm the no-op path and the rows); grep the diff for private names, tracker ids and paths — file(s): none — done when: no finding is open, the release check output is recorded here, and the grep finds nothing.

## Traceability

- FR-001 → T010, T011, T012, T013
- FR-002 → T011
- FR-003 → T011, T033
- FR-004 → T001, T002, T011, T012, T013
- FR-005 → T021, T022
- FR-006 → T021, T030
- FR-007 → T021
- FR-008 → T020, T021
- FR-009 → T021
- FR-010 → T020, T021, T024
- FR-011 → T023
- FR-012 → T024
- FR-013 → T030, T031
- FR-014 → T021, T024
- FR-015 → T020, T032, T033
- FR-016 → T032 (no HUD file in any task); capture files the HUD issue
- SC-001 → T011, T013
- SC-002 → T002, T012, T013, T014
- SC-003 → T020, T011
- SC-004 → T021
- SC-005 → T011, T023
- SC-006 → T024
- SC-007 → T030, T031, T032, T040

## Capture (after review)

- File the follow-up issue for shipgate-hud: show the observed share, decided with one
  month of data (Q3).
- Note for the December review with #42: `observed` and `contradicted` are on every new
  `verify-run`; a gate needs no new shape.
- Note for the December review with #42 (from the lead, 2026-11-26): a foreground Bash run
  that passes the tool's time limit (at most 10 minutes) moves to the background, and no
  hook sees its exit. The full suite of a large project may then never count as observed.
  The verify skill and the README name the case and its remedy (a longer timeout, or a
  narrower run in the foreground); no rule was added. This repository's own full suite
  takes about 15 minutes.

## Deviations & notes (filled during implementation)

- T033 probe, 2026-11-25 (Claude Code 2.1.332, nested `claude -p` on Haiku, the method of
  the handoff notes, cost 0.0088 USD). The main session launched one Workflow with one agent
  that ran `echo probe-workflow-agent`. The Workflow call returned `async_launched` at once.
  The agent's Bash run fired PreToolUse and PostToolUse with the parent's `session_id`, plus
  `agent_id` and `agent_type: "workflow-subagent"`. Its `tool_response` had the exit-0 form of
  the probe table. So a Workflow agent's foreground run is in the parent session's log, like a
  subagent's, and a citation of it counts as observed. The parent's Stop fired before the
  agent's PostToolUse: the run is in the log only once the agent has finished, which the
  workflow's task notification tells the main session. ADR 0033's Consequences line ("a run of
  a Workflow agent ... is tied to no appending session") predates the probe; it gets a dated
  correction note. No code branch depends on it (the PRD's FR-015 names an agent whose hooks
  carry another session id, which the probe did not find).

- Build decisions inside the design, 2026-11-25/26 (workers, accepted by the orchestrator):
  - T011: a row of 200 bytes or more is not written, so one `write` stays one whole line
    (an id that JSON escapes past it writes nothing). PostToolUse needs `interrupted` to be
    `false`; an absent key gives no row. Rotation renames the file only while the name still
    holds the full file (same device and inode), so two hooks at the cap rotate once.
    The file is also opened with `O_NONBLOCK`, which ADR 0032's flag list does not name, so
    a FIFO in its place fails the open and cannot hang the hook; the reader does the same.
  - T013: `post_tool_use.py` loads the project once per Bash call and passes it to
    `record_end` and `record_bash_claims`; a PostToolUseFailure exits after the end row.
  - T020: the reader takes only the exact two row forms, and its 1 MB cap reads the oldest
    bytes first (the hooks keep about 512 KB per session, so only a foreign file reaches it).
    `observe` counts a command that `run_fingerprint` cannot hash (U+D800) as unmatched.
  - T021: `append --json` carries `notices` in each result object. `outcome: null` is
    refused by the enum check; a `cmd` of only spaces passes the shape and stays unobserved.
  - T023: the runs prune prints only warnings; a successful delete prints nothing.
  - T024: the stats tests live in `test_journal_doctor.py` (they moved there in #61). For
    SC-006, the `obs` column shows observed of recorded per stream, and `--json` adds
    `verify_observed_share` (2 places, null with no recorded row) per stream and in total.
  - T014: a failing Bash call now starts the post hook (about 25 ms with no settings file),
    the cost of the PostToolUseFailure registration that ADR 0032 decided.

- T040 release check, 2026-11-26, run by the lead in its own session after the merge (PR #78,
  merge commit 70ae314): on the merge commit's archive and again on the updated install
  (0.37.0-717adb2), 26 of 26 checks pass. The three hook events stay silent and write no
  file in an empty directory; a scratch journaled project gets four rows that hold hashes
  and exit codes only, with modes 0600 and 0700. The tag `shipgate--v0.37.0` is on 717adb2.
  This tick stays in the worktree only: the branch was merged before it.

## What changed

- In a journaled project, the Bash hooks log each run's command hash and exit code per session, outside the repository.
- A `verify-run` must name its commands with their exit codes; the journal derives `outcome` and refuses one that disagrees.
- Each new `verify-run` stores whether the journal saw its commands run (`observed`, `contradicted`); no gate reads it yet.
- `journal.py stats` shows the observed share per stream and in total, and `doctor` shows the run log, pruned after 7 days.
- The verify, implement and model-tiers skills say how to cite a command, a worker's included, so that it counts.

## Review round 1

Workflow run `wf_25a6b349-ab5`: three lenses (correctness, conventions + design,
simplicity + security) on Opus. 27 findings, 23 after dedupe, 13 above the confidence
floor of 60, 0 refuters (no BLOCKER or HIGH), 10 below the floor. The briefed security
review read all 41 files and found nothing at confidence 8 or more.

- F1 MEDIUM `shipgate/scripts/_journal/stats.py:182` — stats reads `observed` and `contradicted` as literals, not through `OBSERVED_KEY` and `CONTRADICTED_KEY`.
- F2 MEDIUM `shipgate/README.md:128` — the `doctor` row of the command table does not name the new `runs` block.
- F3 MEDIUM `shipgate/skills/verify/SKILL.md:129` — a pipe such as `pytest | tail -5` exits 0 on failing tests, and the skill did not say so.
- F4 MEDIUM `shipgate/hooks/post_tool_use.py:338` — the end row also needs the post hook's `likely_journaled()` check, which the README did not say.
- F5 LOW `shipgate/docs/adr/0032-the-bash-hooks-log-each-observed-run-by-session.md:192` — the ADR said the journal hashes with `hashlib.blake2b`; it calls the shared `run_fingerprint`.
- F6 LOW `shipgate/tests/test_journal_runs.py:13` — the stdlib import block is out of order.
- F7 LOW `shipgate/hooks/_runs.py:142` — in a rotation race, the `os.stat` of a file another hook just renamed raises and the row is lost.
- F8 LOW `shipgate/hooks/_runs.py:34` — `O_NONBLOCK` was not in the worklog's notes.
- F9 LOW `shipgate/hooks/_runs.py:27` — the writer copies the session-token rule; no test pins it to `SESSION_ID_RE`.
- F10 LOW `shipgate/docs/prd/observed-verify-run.worklog.md:11` — the worklog status still said `designing`.
- F11 LOW `shipgate/hooks/_common.py:16` — rule 3 of the module docstring ("hold no policy") did not name the run log as its exception.
- F12 LOW `shipgate/README.md:171` — two new README lines broke the file's line width.

All twelve are fixed in this round: F1, F6, F7, F9 and F11 by the hook-side worker (F7 with a
test that failed first), the rest by the orchestrator. Final verify: the full suite, 2,485
tests, OK (2 skipped), exit 0. Verdict: ready. Still open by the flow: the built-in
`/security-review` on the commit before the push, and T040's release check for a hook change
after the merge and before the tag.

### Rejected findings

- `shipgate/hooks/_runs.py:131` (LOW 60): `makedirs` gives only the leaf `runs` mode 0700; the vetted evidence store does the same (`scripts/_journal/screens.py:412`), and the 0700 leaf and 0600 files protect the logs.
- `shipgate/hooks/core.json:53` (MEDIUM 45, below floor): PostToolUseFailure needs no file of its own like `filechanged.json`; it predates FileChanged (Claude Code had it by v2.1.119, and FileChanged came later), so a build that runs this plugin's other hooks knows it.
- Below the floor and not acted on, each by design or out of scope: `runs.py:372` and `:396` (survey code shape), `stats.py:365` (the footer states the share as a count of a total), `append.py:288` (an empty list or no session id counts as not observed, as FR-006 and FR-015 say), `transfer.py:97` (the import subcommand is user-run only and keeps an exported row as it was), `pre_tool_use.py:1814` (the inline walk avoids importing `_common` on the fast path, ADR 0032), `_common.py:638` (an unsalted hash is accepted in ADR 0032's threats), `runs.py:85` (a rotation between the reader's two opens is rare and costs one unmatched row).

## Rejected findings

- (see Review round 1)
