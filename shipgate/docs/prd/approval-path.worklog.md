---
type: worklog
title: "Worklog: the approval path for commit and publish"
created: 2026-11-20
updated: 2026-11-20
tags:
  - worklog
  - shipgate
  - hooks
  - journal
status: review
prd: "./approval-path.md"
issue: "#22 (child of #37)"
related:
  - ../adr/0023-the-users-go-is-recorded-where-the-user-answers.md
  - ../adr/0015-the-user-approves-a-publish-outside-the-model-tools.md
  - ../adr/0010-a-user-row-records-its-writing-session.md
---

# Worklog: the approval path for commit and publish

> Design + build plan companion to `./approval-path.md`. Target release: shipgate 0.28.0.

---

# Design

## Approach

The pragmatic-balance blueprint won. It puts every rule in `journal.py`, adds one hook
script, and gives the model no new command that writes a go. Three architects designed in
parallel, one per philosophy:

- **minimal-change** adds one hook file and lets a `reply` subcommand write the rows. The
  forgery lexer then needs a new rule to refuse a model's call of `reply`.
- **clean-architecture** moves the shell lexer into its own module, adds a pure grammar
  module and five more files. Each rule gets one home. The move changes about 1,100 lines
  of the hook with the highest fix rate.
- **pragmatic-balance** makes `reply` plan the rows and lets the hook write them through
  the existing `append`. The command gate goes into `pre_tool_use.py` behind a second
  substring test.

The core trade-off: two journal runs for a recorded reply (plan, then write) against no
new write path. A recorded reply is rare, and the write path is the security surface, so
the second run is the cheaper cost.

Two points come from the other blueprints. From minimal-change: an answer to any question
is a reply. From clean-architecture: a reply answers every open request of the session,
matched or not, so no request waits for a later `yes`.

The user's rulings of 2026-11-20 changed the first design in four places (PRD, "Rulings"):

- A reply that is no exact go is not closed as held. The recorder writes a witness, and
  the model records a read go that points to it. No confirming question follows.
- The read go has its own marker, `read`, and `stats` counts the go records by marker.
- A marker file keeps the prompt path at no journal run when the session has no open
  request.
- A forced ready verdict authorizes no publish. A probe on a scratch journal of 0.26.0
  showed that path: the forced verdict exits 0, and the plain `mr-opened` after it exits 0.

ADR 0023 is `accepted`.

## Architecture

| Part | Home | Responsibility |
| --- | --- | --- |
| The go rule | `scripts/journal.py`: `user_go`, `commit_authorization`, `publish_authorization` | Reads one stream's events. Says whether a gate holds a go after the last `task-done`. Counts a read go only with its witness |
| The read-go check | `scripts/journal.py`: `_validate_read_go`, called by `append_event` with and without force | Refuses a read go whose witness is missing, used, on another stream, at another gate, older than the last `task-done`, or of another session |
| The reply grammar | `scripts/journal.py`: `reply` subcommand | Reads a reply on stdin. Finds the session's open requests. Prints the rows to write (exact go rows and witnesses) and the context line. Writes nothing |
| The gate answer | `scripts/journal.py`: `authorize` subcommand | Maps a branch to its live stream. Prints `pass` or `hold` and the refusal text |
| The request marker | `scripts/journal.py` writes it; `hooks/reply.py` reads and removes it | An empty file per session beside the journal database. It says that the session may hold an open request |
| The recorder | `hooks/reply.py` (new) | Transport only: filters what is no reply, checks the marker, calls `reply`, writes the plan with `append --batch`, emits the context |
| The command gate | `hooks/pre_tool_use.py`: `gated_commands`, `command_gate` | Finds the four commands in the lexed line. Resolves the directory and its branch. Calls `authorize`. Denies on `hold` |
| The forgery net | `hooks/pre_tool_use.py`: `judge_event` and the type check before it | Refuses a model's append of a user decision at the commit gate, and of a witness. Lets a `source: read` go through to the journal's check |
| Branch reading | `hooks/_common.py`: `current_branch` (moved from `session_start.py`) | One helper for the SessionStart brief and the command gate |

The hooks keep the rule of `_common.py`: they locate the journal and shell out, and they
hold no policy. The transport facts they hold are four: a prompt that starts with `<` is
no reply; a payload with `agent_id` is a subagent's call; a typed text over 32 characters
is sent as `null`; with no marker file, a prompt over 32 characters runs no journal.

Files with a `top` or `high` risk label in the signals ranking: `scripts/journal.py`
(churn top, fix high), `tests/test_hooks.py` (churn top, fix top), `README.md` (churn top,
fix high), `skills/feature/SKILL.md` (churn top, fix high), `skills/review/SKILL.md` (churn
top). `hooks/pre_tool_use.py` is 12 days old with a fix rate of 1.0. T001 pins the current
behaviour of the journal rule and of the hook before any task changes them.

## Data flow

**A question answer that is an exact go.**

1. The flow appends `go-requested {gate: commit, question}` on the stream. The journal
   creates the marker file of the session.
2. The flow asks with `AskUserQuestion`, header `Commit`, first option `Commit`.
3. PostToolUse runs `reply.py`. It sends `{via: question, answers: [{header, answer}],
   tool_use_id, prompt_id}` to `journal.py reply --session ID --json`.
4. `reply` finds the session's open requests. The answer `Commit` matches the commit
   requests. It prints one `gate-decision` per request, with `decision: commit`, `source:
   question`, `request: <seq>` and the actor `user`.
5. `reply.py` writes the rows with `append --batch`. It removes the marker file, and it
   emits the context line "go recorded for commit on <stream>".

**A typed `all` with five open requests.** UserPromptSubmit runs `reply.py`. The marker
file exists. The text does not start with `<` and has 3 characters, so it goes to `reply`.
`all` is a general word. The plan holds five go rows, one per request, each on its own
stream. One batch writes them.

**A typed reply in free language.**

1. The user types `it can go, and start the next batch`. The marker file exists, so
   `reply.py` runs `reply`. The text is longer than 32 characters, so it goes as `null`.
2. `reply` plans one `reply-witnessed {request, gate, via: prompt, session, prompt_id}` per
   open request, with the actor `hook`. It holds no text.
3. `reply.py` writes the witnesses and removes the marker file. Its context line names each
   witness: the seq, the stream, the gate, and the form of the read go.
4. The model reads the user's prompt in its own context. The prompt approves the commit.
   The model appends `gate-decision {gate: commit, decision: commit, raised_by: user,
   mode: ask, source: read, witness: <seq>, words: "it can go"}` on the stream.
5. The PreToolUse hook lets this one marker through. The journal checks the witness and
   accepts the row. The model asks no confirming question.
6. When the reply does not approve, the model appends nothing. The request stays closed,
   and a new question needs a new go request.

**A prompt with no open request.** The marker file is absent. A prompt over 32 characters
ends in the hook with no journal run. A shorter prompt runs `reply` once: a gate word is a
go for the stream the session drives, and any other text plans nothing.

**A lead and a teammate.** The teammate's session works on stream S and meets a refusal.
It reports to the lead. The lead's session appends `go-requested` on S and asks the user.
The reply in the lead's session writes the go or the witness on S, and the lead's model
records a read go when it applies. None of these rows binds the lead to S. The teammate
retries `git commit`. Its command gate reads S from its branch, and `authorize` answers
`pass`.

**A held `git commit`, then a passed one.**

1. The fast path finds `commit` in the command text. Without such a word the hook exits
   and reads no file.
2. `gated_commands` lexes the line and finds `git commit`. A line such as
   `git log --grep commit` ends here, with no file read.
3. The hook finds the project from the payload's `cwd`. No sidecar ends here.
4. It checks `enforce.command_gate`. It reads the branch of the command's directory: the
   `-C` path, else the `cwd`.
5. It runs `journal.py authorize --gate commit --branch B --json`. The answer is `hold`, so
   the hook returns `deny` with the journal's message.
6. The go lands. The same call now gets `pass`, and the hook prints nothing.

Write path to read path: the recorder, the HUD dialog and the model's read go write
`gate-decision` rows. The command gate, `mr-opened`, `status --json` and `position --json`
read them through `user_go`.

## Data model / schema

No table changes and no migration. The changes are in the event vocabulary:

- **New event `go-requested`.** Shape: required `gate` (enum `commit`, `publish`) and
  `question` (string). It implies no phase. `append` refuses it on a stream that does not
  exist or that is finished.
- **New event `reply-witnessed`.** Shape: required `request` (integer, the seq of the go
  request), `gate` (enum), `via` (enum `prompt`, `question`) and `session` (string);
  optional `prompt_id` and `tool_use_id` (strings). The actor is `hook`. It implies no
  phase and holds no text.
- **`gate-decision`.** `source` takes `question`, `prompt` and `read` beside `dialog` and
  `shell`. New optional keys: `request` (integer), `witness` (integer) and `words`
  (string, at most 200 characters).
- **An exact go row:** `{gate, question, decision: <gate>, mode: ask, raised_by: user,
  source: question|prompt, request?}`, actor `user`.
- **A read go row:** `{gate, question, decision: <gate>, mode: ask, raised_by: user,
  source: read, witness, words}`, with the actor of the appending session.
- **An open request:** a `go-requested` row with no later row on its stream that is either
  a `gate-decision` at the same gate with a marker, or a `reply-witnessed` that names it.
- **A valid read go:** its witness is on the same stream, has the actor role `hook`, has
  the same gate, is later than the last `task-done`, is named by no earlier go, and has the
  session of the appending session.
- **Session binding.** `event_session` returns no session for a `go-requested` row and for
  a `gate-decision` with the marker `question`, `prompt` or `read`. A witness is a hook
  row, which never binds. So `session_stream`, `check` and `stats` ignore these rows with
  one change. A new `request_session` reads the actor label of a request, so `reply` still
  knows who asked.
- **The marker file.** `<journal database path>.requests/<session id>`, an empty file. The
  project's ignore rule for the database (`shipgate.db*`) covers it. A session id that does
  not match the session-id pattern gets no file.

## API / contract changes

- **`journal.py reply --session ID --json`.** Stdin: `{"via":"prompt","text":str|null,
  "prompt_id":str}` or `{"via":"question","answers":[{"header":str,"answer":str}],
  "tool_use_id":str,"prompt_id":str}`. Stdout: `{"events":[{stream,type,data,actor}],
  "recorded":[{stream,gate,request}],"witnessed":[{stream,gate,request}],"open":int,
  "context":str|null}`. `open` is the count of the session's open requests after the plan.
  Exit 0, 1 for infrastructure, 2 for usage. It writes nothing.
- **`journal.py authorize --gate commit|publish --branch NAME [--subagent] --json`.**
  Stdout: `{"verdict":"pass"|"hold","reason":"authorized"|"no-go"|"witness-waits"|
  "no-stream"|"not-live","stream","gate","message"}`. Exit 0 for a pass and for a hold, 1
  for infrastructure. With `witness-waits` the message names the witness and the form of
  the read go.
- **`append` of a read go.** A `gate-decision` with `source: read` passes the journal only
  as a valid read go. The refusal exits 4, and `--force` does not waive it.
- **`status --json` and `position --json`.** Each stream gains `go: {commit, publish}`,
  the user-only answer in the shape of `publish`. `publish` keeps its meaning, except that
  a forced ready verdict no longer authorizes.
- **`stats --json`.** A new `go` section counts the go records by marker.
- **`mr-opened`.** Force no longer waives the publish rule, and a forced ready verdict no
  longer satisfies it. The refusal names the five markers and offers no force. This breaks
  a caller that forced either event: the CHANGELOG says so.
- **Word lists.** Gate words: `commit`; `publish` and `push` for the publish gate. General
  words: `all`, `yes`, `y`, `ok`, `go`, `approve`. The match is the whole reply after case
  folding, with outer space and one closing `.` or `!` removed. The list is built in.
- **Hook contract.** `core.json` gains two entries, each with timeout 10:
  - `UserPromptSubmit`, no matcher, `hooks/reply.py`;
  - `PostToolUse`, matcher `AskUserQuestion`, `hooks/reply.py`.

  The PreToolUse entry does not change, but the hook can now deny `git commit`, `git push`,
  `gh pr create` and `glab mr create`. It also refuses a model's append of a
  `reply-witnessed` event.
- **Sidecar.** `enforce.command_gate`, default on. `false` turns the command gate off. The
  recorder has no knob.
- **shipgate-hud.** No change. Its contract test gains the `go` key as an additive field.

Failure policy:

- The command gate passes the command on an exception, a timeout, a non-zero exit, output
  that is no JSON, no branch, or any verdict other than `hold`.
- The forgery net keeps the crash policy of ADR 0015: a crash refuses only a command that
  names `journal.py`, `append` and `publish`.
- The recorder runs under `safe_main`. It never blocks a prompt and never exits 2. When
  the write of a plan fails, its context line says that nothing was recorded.
- A marker file that cannot be written does not fail the `go-requested` append. The
  journal prints one warning line on stderr.
- Timeouts: the recorder gives each journal run 5 seconds, and the command gate gives
  `git` 2 seconds and `authorize` 5 seconds. Each sum stays under the hook timeout of 10.

One point to confirm from the hooks reference in T015: that a PostToolUse hook's
`additionalContext` reaches the model. If it does not, the question path tells the model
through the `authorize` message at the next held command.

## Reference implementation

- **The recorder mirrors `hooks/post_tool_use.py`.** Its `main` runs the `stat`-only gate
  before it reads stdin, dispatches on the payload, shells out through `_common`, and
  never blocks. The signals favour it over the two other candidates: fix rate 0.0 over 2
  commits and 91 days, against 0.33 for `stop.py` and 1.0 for `pre_tool_use.py`.
- **The mapping of a journal answer to a hook answer mirrors `hooks/stop.py`.** It runs
  one `--json` subcommand and turns the result into the hook's output.
- **The command scan mirrors `publishOf` in `shipgate-hud/hooks/publish.ts`** for what
  counts as a publish command, and `append_args` in `pre_tool_use.py` for the walk over
  options before a subcommand.
- **The go rule mirrors `publish_authorization` in `scripts/journal.py`**: one helper that
  the gate, `status` and `position` all read (ADR 0009).
- **The read-go check mirrors `_validate_waiver`**: a check that `append_event` runs on
  the forced path too.

`pre_tool_use.py` is the hook that changes, and it is not a reference: it is the newest
and most-fixed hook. Its lexer is reused as it is. No task changes the lexer.

## CLAUDE.md / impact-map compliance

- Primary home: `shipgate/`. shipgate-hud is not changed.
- The change bumps `shipgate/.claude-plugin/plugin.json` and the matching entry in
  `.claude-plugin/marketplace.json` to 0.28.0, in the same change.
- Release notes go to `shipgate/CHANGELOG.md` only. The README links to it.
- Hooks are a security-sensitive area. T021 briefs a reviewer on the working-tree diff
  with the criteria of the built-in security review, because that command reads only a
  committed diff (#40).
- Public repo: no private name in any file, fixture or journal note. T022 greps the diff.
- Scripts stay Python 3.9 compatible, with the standard library only.
- The PRD, ADR 0023 and this worklog are not committed alone. They go into the
  implementation's PR.
- The release gets the tag `shipgate--v0.28.0` once its commit is on `main`. The tag, the
  commit and the PR each need the user's go.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).
Tests are tasks, not a separate phase. Tick boxes as you go; log deviations inline.

## Setup / foundations

- [x] T001 — Pin the current behaviour before the change — file(s):
  `shipgate/tests/test_journal.py`, `shipgate/tests/test_hooks.py` — done when: three
  tests pass on the unchanged code. One: an unmarked user row binds its recording session
  in `status --session` (ADR 0010). Two: `git commit -m x` on a journaled project passes
  the PreToolUse hook with no output. Three: `publish` in `status --json` is `held` after a
  `task-done` and `authorized` after a plain ready verdict.

## Journal

- [x] T002 — Vocabulary and shapes: `go-requested`, `reply-witnessed`, the markers
  `question`, `prompt` and `read`, the keys `request`, `witness` and `words`, the refusal
  of a request on a missing or finished stream — file(s): `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py` — done when: `TestGoRequested`, `TestReplyWitnessed`
  and the extended `TestShapeValidation` fail first, then pass.
- [x] T003 — `user_go`, `commit_authorization`, and `go` in `fold_stream` and
  `build_position`; `publish_authorization` reuses `user_go`; a read go counts only with
  its witness — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py`,
  `shipgate/tests/test_hud_contract.py` — done when: `TestUserGo` proves the lifetime, the
  publish-covers-commit rule, the five markers and a read go with and without its witness,
  and the T001 pin for `publish` still passes. Depends on T002.
- [x] T004 — The rows that do not bind a session: `event_session` and the new
  `request_session` — file(s): `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py` — done when: `TestGoDoesNotBind` proves SC-005 for
  `status --session` and for `check`, for a go request, an exact go and a read go, and the
  T001 pin for an unmarked row still passes. Depends on T002.
- [x] T005 — The read-go check at `append`, on the forced path too — file(s):
  `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when:
  `TestReadGo` proves SC-012 and each refusal of SC-013 with exit 4, with and without
  `--force`. Depends on T002 and T003.
- [x] T006 [P] — No forced event opens a publish: force never waives the `mr-opened` rule,
  a forced ready verdict does not authorize, the refusal names the five markers and offers
  no force — file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` —
  done when: the SC-006 and SC-016 tests fail first, then pass, and
  `test_force_waives_the_gate` is replaced by them. Depends on T003.
- [x] T007 — The `reply` subcommand: the word lists, the reading of a question answer, the
  open requests of a session, the plan of go rows and witnesses, the context line —
  file(s): `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when:
  `TestReplyPlan` proves SC-002 and SC-003, the request of another session stays open, a
  gate word with no request goes to the driven stream, any other text with no request
  plans nothing, a witnessed request takes no later `yes`, and no output holds a prompt
  text. Depends on T003 and T004.
- [x] T008 — The marker file: the journal creates it at a `go-requested` append, and
  `reply` prints `open` — file(s): `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py` — done when: a test proves the file for the appending
  session, no file for a session id outside the pattern, and an append that still exits 0
  when the directory cannot be written. Depends on T002.
- [x] T009 [P] — The `authorize` subcommand and its messages — file(s):
  `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when:
  `TestAuthorize` passes as a table: no stream, a finished stream, held, a waiting
  witness, authorized by a commit go, by a publish go and by a read go, a ready verdict
  alone is `hold`, the subagent text. Depends on T003.
- [x] T010 [P] — `stats` counts the go records by marker — file(s):
  `shipgate/scripts/journal.py`, `shipgate/tests/test_journal.py` — done when: the SC-017
  test fails first, then passes. Depends on T002.

## Hooks

- [x] T011 [P] — Move `current_branch` and `_branch_name` into `_common.py`; `run_journal`
  takes a timeout and a session id for the child's environment; a helper gives the marker
  path — file(s): `shipgate/hooks/_common.py`, `shipgate/hooks/session_start.py` — done
  when: the SessionStart tests pass with no change.
- [x] T012 [P] — The forgery net: the commit gate, the refusal of a `reply-witnessed`
  append, the pass of a `source: read` go with an actor that is not `user`; `TAIL` and the
  messages name the paths of this release — file(s): `shipgate/hooks/pre_tool_use.py`,
  `shipgate/tests/test_hooks.py` — done when: SC-009 and SC-014 fail first, then pass, a
  `source: read` append with `--actor user` is refused, an opaque `--type` is still
  refused, and the text pins are updated.
- [x] T013 — `gated_commands`: find `git commit`, `git push`, `git subtree push`,
  `gh pr create|new` and `glab mr create|new` in the lexed commands, with git's global
  options, the `-C` directory, wrappers, `sh -c` and `eval` — file(s):
  `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py` — done when:
  `TestGatedCommands` passes as a table. `echo git commit`, `git commit-tree`,
  `git stash push` and `git log --grep commit` do not match. The lexer is not changed.
- [x] T014 — The command gate in `main`: the second fast path, the project, the knob, the
  branch, `authorize`, the deny, the subagent flag, the failure policy — file(s):
  `shipgate/hooks/pre_tool_use.py`, `shipgate/tests/test_hooks.py` — done when:
  `TestCommandGate` proves a hold and then a pass for each of the four commands, the knob,
  a branch with no stream and the subagent text; `TestCommandGateFailurePolicy` proves a
  pass on a failing journal and on output that is no JSON; the audit-hook test proves no
  file read for `ls -la` and for `echo commit` (SC-007). Depends on T009, T011 and T013.
- [x] T015 — The recorder and its wiring — file(s): `shipgate/hooks/reply.py` (new),
  `shipgate/hooks/core.json`, `shipgate/tests/test_hooks.py` — done when: `TestReplyHook`
  proves SC-001 and SC-002 against a real journal with the probe payloads, SC-004 with the
  three shapes that are no reply, SC-015 with a stub journal, the removal of the marker
  file, and a context line on a failed write; `TestHookWiring` pins the two new entries;
  `TestUnjournaledProjectIsInert` covers the recorder on both events. The task also
  confirms from the hooks reference that PostToolUse `additionalContext` reaches the
  model. Depends on T007, T008 and T011.
- [x] T016 — End to end — file(s): `shipgate/tests/test_hooks.py` — done when: one test
  runs the recorder as session A and the command gate as session B on one journal and
  proves SC-005; one test proves SC-001 from the question answer to the passed
  `git commit`; one test proves SC-012 from the typed `it can go` through the witness and
  the read go to the passed `git commit`. Depends on T005, T012, T014 and T015.
- [x] T017 — Measure the cost — file(s): this worklog — done when: the median and the
  worst of 20 runs are written here for four cases: the recorder off a journaled project;
  the recorder with no marker and a long prompt; the recorder with a marker; the command
  gate on a held commit. The budgets are a median of 60 ms for the first two cases, 200 ms
  for the third and 300 ms for the fourth. A miss goes to the user as a decision before
  the release.

## Flow text and docs

- [x] T018 [P] — The skills name one form: record `go-requested`, then ask with the gate
  header and the gate word as the first option; several streams take a multi-select whose
  labels are the stream names; after a context line that names a witness, read the reply
  and record the read go with the witness and the user's words, or record nothing; never
  ask a confirming question after a clear approval; a session that asks for another
  session's stream records the request itself; a worker hands the question back — file(s):
  `shipgate/skills/review/SKILL.md`, `shipgate/skills/feature/SKILL.md`,
  `shipgate/skills/implement/SKILL.md`, `shipgate/skills/model-tiers/SKILL.md` — done
  when: no skill names the dialog and `!` as the only paths, and the prose audit finds one
  term for each concept of the PRD's Terms.
- [x] T019 [P] — The knob and the docs — file(s): `shipgate/config-template.md`,
  `shipgate/scripts/lean_config.py`, `shipgate/skills/setup/SKILL.md`,
  `shipgate/README.md`, `shipgate/docs/glossary.md`, `shipgate/CHANGELOG.md`,
  `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, the config
  fixtures under `shipgate/tests/fixtures/configs/` — done when: `setup` writes
  `enforce.command_gate`, the README section on the user's approval describes this
  release, the CHANGELOG has the 0.28.0 entry with the breaking notes on forced
  `mr-opened` and on a forced ready verdict, both version files say 0.28.0, and
  `test_lean_config` passes.

## Verification

- [ ] T020 — Judge the changed skill text on both session models — file(s):
  `shipgate/evals/` (one new case), the eval baseline — done when: the case runs through
  the `run-evals` project skill on both models, and each run meets SC-010. The eval
  fixtures set `enforce.command_gate` as each case needs.
- [x] T021 — Security review of the working-tree diff — file(s): none — done when: a
  reviewer briefed with the criteria of the built-in security review has read the diff of
  `shipgate/hooks/` and `shipgate/scripts/journal.py`, and every finding has a
  disposition.
- [x] T022 — Full suite and the public-repo check — file(s): none — done when:
  `python3 -m unittest discover -s shipgate/tests` exits 0 from the worktree root, and a
  grep of the diff for private names, tracker ids and paths finds nothing.

## Traceability

- FR-001, FR-002 → T002, T008
- FR-003 → T007
- FR-004, FR-005, FR-006, FR-007, FR-008 → T007, T015
- FR-009 → T015
- FR-010 → T002, T015
- FR-011, FR-012 → T003
- FR-013 → T004, T016
- FR-014 → T003
- FR-015, FR-016 → T009, T013, T014
- FR-017 → T009, T014
- FR-018, FR-019 → T014, T019
- FR-020 → T003
- FR-021 → T006
- FR-022 → T012
- FR-023 → T018
- FR-024 → T006, T009, T012
- FR-025, FR-026 → T014, T015
- FR-027 → T002, T007, T015
- FR-028 → T005, T016, T018
- FR-029 → T003, T005
- FR-030 → T002, T010
- FR-031 → T012
- FR-032 → T008, T015, T017
- FR-033 → T006
- SC-001 → T015, T016
- SC-002, SC-003 → T007, T015
- SC-004 → T015
- SC-005 → T004, T016
- SC-006 → T006
- SC-007 → T014, T015
- SC-008 → T022
- SC-009 → T012
- SC-010 → T020, judged after the merge and before the tag (the user's ruling)
- SC-011 → the retro of #37, one month after the release
- SC-012 → T005, T016
- SC-013 → T005
- SC-014 → T012
- SC-015 → T015
- SC-016 → T006
- SC-017 → T010

## Follow-ups (not in this plan)

- SC-010 is judged after the merge and before the tag (the user's ruling of
  2026-11-20): fast-forward the main checkout so the installed shipgate is 0.28.0, run
  `shipgate/evals/two-turn/two_turn.py` on Opus and on Fable (about $2), and tag only
  when both pass. A fail gets a fix PR before any tag. Then tick T020.
- File with the PR (the user's go): a follow-up issue to start the journal as a cached
  module from every hook (label enhancement; refs #22, #37). The T017 numbers show the
  compile of `journal.py` costs about 30 ms per hook run.
- File with the PR, at home in #28: the eval harness has no `AskUserQuestion` tool, and an
  eval session (and a `--plugin-dir` session) loads an installed plugin of the same name
  over the plugin under test.

- shipgate-hud: its refusal text names the dialog and `!` only. A separate issue updates
  it for the five markers.
- The root `CLAUDE.md` says that shipgate-hud declares `shipgate >=0.18.0`. The plugin
  file declares `>=0.23.0`.

## Deviations & notes (filled during implementation)

- 2026-11-20 — Design only in this session. The explore fan ran as the config's Workflow
  (3 lenses). The hook facts came from the hooks reference and one interactive probe:
  1 nested session, 37 hook records.
- 2026-11-20 — The design was revised after the user's rulings: the witness and the read
  go replace the held closure and the confirming question; the marker file and the rule on
  a forced ready verdict are new. The plan grew from 19 tasks to 22, and the task ids
  changed. No task was done before the change.
- 2026-11-20 — T003: the `go` key changes the HUD's golden file
  `shipgate-hud/tests/fixtures.journal.ts`. It was regenerated with
  `SHIPGATE_REGEN_GOLDEN=1`: 562 lines added, 0 removed. This is a test fixture, not a
  HUD behaviour change. The 0.23.0 release did the same. The HUD's decoders read each
  field by name, so the extra key is additive.
- 2026-11-20 — T006: the golden script forces one ready verdict (the stale-`fixing`
  stream). Its `publish` changes from authorized to `held`, as FR-033 requires. The
  golden was regenerated again (569 added, 28 removed in total), and
  `test_the_position_runs_cover_the_dispositions` pins the held value.
- 2026-11-20 — T007: `reply` plans before the rows exist, so the context line cannot
  name a witness seq. It writes `<seq:N>` instead, N the index of the row in `events`.
  The recorder replaces it with the seq that `append --batch --json` prints for that
  line. This is transport, not policy. A multi-select label counts only for an open
  request of the session at the header's gate. A question answer is never matched
  against the general words (ADR 0023 §5).
- 2026-11-20 — T009: `authorize` matches the branch against unfinished streams first,
  with the same candidates as `status`. A dormant stream is still gated: only a
  finished one passes as `not-live`. `witness-waits` counts a publish witness for the
  commit gate too, because a publish go covers a commit.
- 2026-11-20 — T020, the user's ruling: "After merge, before the tag". No more evals in
  this branch. Harness case 76 left the change (it could never pass). The two-turn driver
  and its fixture stay, in `shipgate/evals/two-turn/` with a run note; the fixture now
  sets a repo-local git identity, which the first run lacked under a scratch HOME.
- 2026-11-20 — T020, first runs: no valid result. On the account the user chose, the
  harness case ran 3 runs per arm on each model ($1.08 Opus, $2.41 Fable); every grader
  failed in both arms. Two causes, from the trace: the "with" arm loaded the installed
  `shipgate@pandora` (0.26.0, from the main checkout), which shadows the plugin under
  test by name; and an eval session has no `AskUserQuestion` tool. The two-turn pty
  session hit the same shadowing: with `--plugin-dir` and `--setting-sources ""` the
  session still loads the installed plugin (a $0.003 check confirms it), so the model's
  `git commit` met no command gate. A scratch config dir is not logged in. Options went
  to the lead; the harness case cannot pass and leaves the change.
- 2026-11-20 — T021, the security review. A reviewer (Opus) read the working-tree
  diff of `shipgate/hooks/` and `scripts/journal.py`, briefed with the criteria of the
  built-in security review, because that command reads only a committed diff (#40).
  Four findings, each confirmed by a probe:
  1. `journal.py import` writes a user go and a witness with no check, and no hook
     covers it (medium, 90). Pre-existing, but the release removes `--force` from
     `mr-opened`, so it is the next escape. **Fixed by the user's ruling** ("Hook refuses
     a model's import"): the forgery net refuses any `journal.py import` a model runs
     (ADR 0023 §20), with tests in `TestPreToolUseRefusesAnImport`.
  2. A stream label counted as a go under any gate header, not only in a multi-select:
     "Not yet, feat/x" recorded a publish go (medium-low, 85). **Fixed:** the recorder
     passes `multi_select`, and `reply` reads a label only there (§5).
  3. A model could label a go request or a read go with another session's id (low,
     80). **Fixed:** `append` refuses such a row when the label names a session other
     than `CLAUDE_CODE_SESSION_ID`, with or without `--force`.
  4. The command gate followed a `cd` inside `( )` or `$( )`, and a NUL byte in `-C`
     raised in `current_branch` (low, 90). **Fixed:** a line with a `cd` also asks for
     the cwd's branch and holds when either holds; a NUL path reads as the cwd, and
     `current_branch` catches `ValueError`. The cost: `cd other-repo && git commit` from
     a stream's checkout now asks for that stream's go too.
  A second reviewer pass (Opus) rechecked the fixes on the working-tree diff after the
  rebase. Fixed: 2 and 4. Partly fixed, then closed: 1 (`runs_import` now walks the
  words as `append_args` does, so `--db="$DB"`, `"${CLAUDE_PLUGIN_ROOT}/…/journal.py"`
  and `"$J"` are refused) and 3 (the hook refuses a journal write whose line sets or
  clears `CLAUDE_CODE_SESSION_ID`, `env -i` included, and `authorize` no longer prints
  the witness's session id). New and fixed: N1, a non-literal assignment before the
  command (`X="$Y" git commit`) hid it from the gate; N2, `-C` with `--git-dir` or
  `GIT_DIR` sent the gate to the `-C` directory (both now read the cwd). The reviewer's
  own probes, rerun on the fixed code, are refused by the hook in every bypass form;
  `'imp''ort'` and an `xargs`-supplied subcommand still pass, as the same spellings do
  for `append` (ADR 0015's accepted limits). Not done: refusing a read go or a go request
  when the session variable is empty in the journal itself; it would refuse every such
  append outside a Claude Code shell, and the hook now refuses the spellings that clear it.
  The reviewer's note below its threshold: the recorder does not check whether a
  question was answered at all (`annotations.unanswered`, an away timeout). Not
  confirmed; left as is.
- 2026-11-20 — T020 deviation, reported to the lead before any run: `claude plugin
  eval` runs one prompt, so one harness case judges only the first half of SC-010 (the
  go request and the gate question). The second half (the reply "it can go", the read go,
  no confirming question) runs as a scripted two-turn session under a pty, one run per
  model. Planned spend about $5 to $6. Waiting for the go.
- 2026-11-20 — T017, the cost of the hooks. 20 runs per case, wall time of the hook
  process, Python 3.15.2 on the build machine. A bare `python3 -c pass` takes 26 ms.

  | Case | Median | Worst | Budget (median) | Result |
  | --- | --- | --- | --- | --- |
  | Recorder, project with no sidecar | 29 ms | 45 ms | 60 ms | met |
  | Recorder, journaled, no marker, long prompt | 39 ms | 42 ms | 60 ms | met |
  | Recorder, marker and an open request (`reply`, then `append --batch`) | 252 ms | 279 ms | 200 ms | **missed** |
  | Command gate, held `git commit` | 168 ms | 173 ms | 300 ms | met |

  The third case runs the journal twice. Each run costs about 98 ms before it does any
  work: `reply` itself adds 9 ms and the one-row write 5 ms, also on a copy of a real
  journal (43 streams, 1,746 events). Of the 98 ms, 30 ms is the compile of
  `journal.py`: Python never caches the bytecode of a script it runs as `__main__`. A
  probe that imports `journal` as a module (cached bytecode) takes 75 ms per run, so the
  case would take about 208 ms: still above the budget. The miss goes to the user as a
  decision before the release.
- 2026-11-20 — T015: the hooks reference (code.claude.com/docs/en/hooks) says that
  `additionalContext` reaches the model for PostToolUse ("added to Claude's context
  alongside the tool result") and for UserPromptSubmit. The probe showed that
  PostToolUse fires on `AskUserQuestion`. So the fallback is not needed. Each journal
  run of the recorder gets 4 seconds, not 5: two runs then stay under the hook timeout
  of 10. Only an answer under a gate header leaves the hook as text; any other answer
  goes as `null`, since it can only witness. `reply.py` was written before its tests;
  the tests then failed with the file moved aside (21 failures) and pass with it.
- 2026-11-20 — T011–T013 ran as one worker (Opus) in parallel with the journal tasks.
  T011: the session-id pattern is `\A[A-Za-z0-9_-]{1,128}\Z` (`$` would accept a
  trailing newline), compiled on first use so that `_common` does not import `re`.
  T012: an append whose `--type` the hook cannot read is now refused whatever its
  payload, because it may be a witness. No caller in shipgate or shipgate-hud passes a
  variable `--type`. T013: `gated_commands` reads git's `-C` only; a `cd`, `--git-dir`,
  `--work-tree` and `GIT_DIR=` read as the command's cwd (T014 decides the `cd` case).
- 2026-11-20 — T014: a literal `cd` or `pushd` earlier in the line moves the directory
  whose branch the gate reads, and git's `-C` enters from there. A `cd` the hook cannot
  read falls back to the cwd. The gate asks once per directory, for the strongest gate:
  a line that commits and pushes asks for the publish gate only. A line that acts on two
  directories asks twice, so its worst case (2 x (2 s git + 5 s journal)) can pass the
  hook timeout of 10 s; the harness then runs the command, which is the failure policy.
- 2026-11-20 — T002: a new shape rule kind, `max_chars`, carries the 200-character limit
  of `words`. `--force` does not waive it, like every shape rule.

## Security review of the build commit

The built-in `/security-review` on commit `e1f15cf` (finder, then a false-positive filter
per finding) kept one finding, and the push stopped there:

- S1 MEDIUM `hooks/reply.py:201` — a model could run the recorder script from its own Bash call with a forged payload, and its child journal runs wrote the user's go past PreToolUse (filter 8/10). The user ruled "Hook refuses running the script" (ADR 0023 §21): the forgery net refuses a command that runs `reply.py` as the program, as a Python's script word, or through an unreadable script word on a line that names it. A Python's arguments are no longer lexed again as a shell line, since `python3 -c` is out of scope (ADR 0015). Tests: `TestPreToolUseRefusesTheRecorder`, 9 refused forms and 7 allowed reads, failed first.

By the lead's decision, the fix amends `e1f15cf`: the release tag goes on the one commit
that bumps the version. The full suite then passed: 1495 tests, OK (skipped=2), exit 0.

## Rebase onto 0.27.1 (#46)

The user ruled that #46 ships first as 0.27.1, and then "Rebase and force-push with lease".
The rebase onto `0997406` kept one commit; conflicts in the version files (0.28.0 kept),
the CHANGELOG (0.28.0 above 0.27.1), the README command table and `test_journal.py` (both
new classes kept). New in this round: `TestReadGo.test_a_read_go_from_a_sessionless_shell_is_refused`,
the interplay test from #46's worklog (it passes on 0.27.1 by design, for the default actor
and `--actor user`); and the lead's hardening from the security review of `274c99a`
(filtered at 3/10): the runner modules `cProfile`, `profile`, `trace`, `pdb` and the
wrappers `arch`, `xcrun` now count as running the recorder, the docstring is corrected,
and ADR 0023 lists split-quote spellings of the command gate's fast path as an accepted
limit. Tests: six new refused forms and two new allowed reads, failed first.

A reviewer (Opus) checked the delta since `274c99a`: the conflict resolutions lost nothing
(CHANGELOG, README, version files, both test classes), and the change agrees with 0.27.1's
`appending_session`. Three LOW findings:

- D1 LOW `hooks/pre_tool_use.py:1259` — `-m` glued to its module (`-mcProfile`) or inside a flag cluster (`-um`, `-Im`) slipped past the runner check, and `-mpy_compile` was refused; fixed: a short-option cluster is parsed (`-c`/`-m` take the rest or the next word).
- D2 LOW `hooks/pre_tool_use.py:163` — `xcrun -sdk NAME` and `-toolchain NAME` hid the program; fixed: both single-dash options take a value.
- D3 LOW `scripts/journal.py:1949` — since 0.27.1 a `go-requested` from a shell with no session id lands with no session and no marker, so no reply can answer it; deferred: it happens only outside a Claude Code shell, and a refusal would change the journal's behaviour; the flow then records the request again from its own shell.

## Review round 1

The review Workflow (run `wf_de1992ca-4ae`), lenses correctness and conventions +
design, Opus finders; the security lens is the two passes of T021. Counts: 31 found, 30
after dedupe, 21 above the floor of 60, 0 refuters (no BLOCKER or HIGH), 9 below the floor.

- F1 MEDIUM `shipgate/README.md:185` — the journal command table lacks `reply`, `authorize`, the `go` key and the go counts of `stats`.
- F2 MEDIUM `hooks/pre_tool_use.py:1236` — the session-override check skips nested scripts and text-only commands such as `printf -v`.
- F3 MEDIUM `scripts/journal.py:2864` — the read-go command and the hold message build their own append and skip `_suggest` (no `--db`, no dash-leading stream).
- F4 MEDIUM `hooks/reply.py:104` — the hook reads a gate header without dropping a closing `.` or `!`, unlike the journal.
- F5 MEDIUM `scripts/journal.py:1320` — the witness rule has three separate implementations.
- F6 LOW `skills/review/SKILL.md:595` — the skill's and the README's word lists omit `y`.
- F7 LOW `scripts/journal.py:884` — a go request whose data holds `session` is accepted but never opens.
- F8 LOW `scripts/journal.py:1272` — `USER_MARKERS` is unused and `commit_authorization` has no caller.
- F9 LOW `hooks/pre_tool_use.py:1657` — the crash refusal for `import` is not in the docstring or the ADR.
- F10 LOW `hooks/pre_tool_use.py:1624` — `deny_with` repeats the body of `deny`.
- F11 LOW `hooks/_common.py:427` — the session variable name is written in three places.
- F12 LOW `hooks/pre_tool_use.py:1375` — `git commit --dry-run` and `git push --dry-run` are held.
- F13 LOW `hooks/pre_tool_use.py:1564` — the hook's `GATE_WORDS` names a different concept than the journal's.
- F14 LOW `prd/approval-path.worklog.md:11` — the worklog's status still says designing.
- F15 LOW `scripts/journal.py:2851` — a `Push` answer under the Publish header is only a witness.
- F16 LOW `hooks/reply.py:108` — a typed answer under a gate header leaves the hook at any length.
- F17 LOW `skills/review/SKILL.md:610` — the skill no longer shows the user's `!` command.
- F18 LOW `shipgate/README.md:284` — the README and the hook docstring say "no live stream" where a dormant stream is gated.
- F19 LOW `hooks/session_start.py:25` — `session_start.py` imports the private `_branch_name`.
- F20 LOW `skills/feature/SKILL.md:358` — the feature skill says every user event binds its session.
- F21 LOW `hooks/pre_tool_use.py:168` — `REASON_PRIORITY` is one 107-character line.
- F22 LOW `scripts/journal.py:2252` — the journal and the recorder can name the marker by different db paths when the db is a symlink (below the floor, 55; confirmed by reading the code).
- F23 LOW `hooks/pre_tool_use.py:1619` — the hook's fallback hold text names no way forward (below the floor, 55).
- F24 LOW `hooks/reply.py:16` — the docstring's transport facts differ from the hook's (below the floor, 55).
- F25 LOW `evals/README.md:3` — the evals README does not name the `two-turn/` folder (below the floor, 55).
- F26 LOW `scripts/journal.py:2233` — a non-OSError in the marker write would report a landed append as failed (below the floor, 35).

### Rejected findings

- `hooks/pre_tool_use.py:1598` (LOW 50): the gate asks once per directory for the strongest gate; asking per gate costs one more journal run per line, and the worklog notes the rule (T014).
- `scripts/journal.py:2958` (LOW 45): `open: 0` is correct by construction: every open request of the session gets a go or a witness row in the plan.
- `hooks/pre_tool_use.py:1329` (LOW 40): a git alias, `xargs git commit` and `find -exec` are ADR 0023's accepted limits.
- `hooks/pre_tool_use.py:1273` (LOW 40): deferred, not rejected: the compile cost of the hook file on every Bash call goes to the follow-up that starts the journal and the hooks from cached modules.

## Review round 2

One Opus reviewer re-checked the fix diff for both questions of the review skill and, as
the lead asked, for security on the forgery-net and command-gate delta. F1-F26: 25 fixed
on evidence (the line or the pinning test); F13 was half fixed (the docstring still said
"gate words") and is closed with N4. Four new findings, all fixed with a test that failed
first; the reviewer's own probes, rerun on the fixed code, confirm each:

- N1 MEDIUM `hooks/pre_tool_use.py:1390` — the F12 dry-run exemption let a real commit or push through (`--dry-run --no-dry-run`, `-m --dry-run`, `push -o -n`); every dry run is held again, and F12 is rejected as an accepted false hold.
- N2 MEDIUM `hooks/pre_tool_use.py:1247` — `env -uNAME`, `env --unset=NAME`, `env -iv`, `env -v -i` and `env -u X -i` cleared the session id past the hook; the hook reads them, and the journal now refuses a go request or a read go that carries a session label while `CLAUDE_CODE_SESSION_ID` is empty, which closes every clearing spelling.
- N3 LOW `hooks/pre_tool_use.py:1250` — a read-only `grep` or `rg` that named the variable was refused; a text-only command now counts only for `printf -v`.
- N4 LOW `hooks/pre_tool_use.py:80` — the docstring called the command hints "gate words".

Still passing the hook, and refused by the journal instead: `exec -c`, `unset "$N"`. A
label filled from `meta.current_session` with the variable empty needs `journal.py session
--set`, a plumbing command; it stays a deliberate-circumvention limit.

### Rejected findings

- `hooks/pre_tool_use.py:1375` (LOW 75): F12, a held dry run; the exemption could not be read safely from the words (N1), so the false hold stays.
