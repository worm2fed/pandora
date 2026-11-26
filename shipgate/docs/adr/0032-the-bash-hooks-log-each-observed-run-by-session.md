---
type: adr
title: "0032. The Bash hooks log each observed run by session"
created: 2026-11-25
updated: 2026-11-25
tags:
  - adr
  - shipgate
  - hooks
  - verify
status: accepted
date: 2026-11-25
issue: "#27 (shipgate), child of #37"
related:
  - "../prd/observed-verify-run.md"
  - "../prd/observed-verify-run.worklog.md"
  - "./0033-a-verify-run-names-its-commands-and-the-journal-records-what-it-saw.md"
  - "./0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "./0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "./0022-the-context-nudge-rides-the-posttooluse-bash-hook.md"
---

# 0032. The Bash hooks log each observed run by session

> In a journaled project, the PreToolUse hook writes one start row per Bash call: the
> call's `tool_use_id` and a 64-bit hash of the command the model typed. PostToolUse and a
> newly registered PostToolUseFailure write one end row: the `tool_use_id` and the exit
> status, when the status is known. The rows go to one file per session under the Claude
> config directory, outside every repository. The journal joins them when a `verify-run`
> is appended (ADR 0033). The hook contract changes, a one-way door: the user accepted
> this ADR on 2026-11-25, in a question dialog relayed by the lead.

## Context

Issue #27: the model types every `verify-run`, and no hook sees the test run. The user
chose the log of this ADR in the clarify dialog of 2026-11-25 (Q1, relayed by the lead).

A probe on 2026-11-25 (Claude Code 2.1.332, nested `claude -p` on Haiku, scratch logging
hooks) set the facts:

- **Exit 0** fires PostToolUse. `tool_response` holds `stdout`, `stderr`, `interrupted`,
  `isImage` and `noOutputExpected`, and no exit code.
- **Exit N** fires PostToolUseFailure, not PostToolUse. There is no `tool_response`. The
  `error` field is `Exit code N`, a newline, then the output. A timeout gives
  `Exit code 143`. Exit 127 has the same form.
- **An interpreted exit** fires PostToolUse with `returnCodeInterpretation` and no code:
  `grep` with no match ("No matches found"), `diff` of two different files ("Files
  differ"), a false `test` ("Condition is false"). The real status is 1. So PostToolUse
  does not mean exit 0.
- **A background run** fires PostToolUse at launch, with `backgroundTaskId` and a duration
  of 5 ms. Its exit status reaches only the model, through the task notification. No hook
  fires when it ends.
- **A subagent's run** fires its hooks in the parent's process, with the parent's
  `session_id` in the payload and in `CLAUDE_CODE_SESSION_ID`, plus `agent_id` and
  `agent_type`.
- **A denied run** fires neither PostToolUse nor PostToolUseFailure.
- **A rewritten command.** When a PreToolUse hook returns `updatedInput`, PostToolUse sees
  the rewritten command. A PreToolUse hook that runs beside the rewriter sees the command
  the model typed. A token-saving CLI proxy in use on the maintainer's machine rewrites 41
  of the 420 commands cited in this repository's journal, and most test runners of other
  languages (`pytest`, `cargo test`, `go test`, `make test`, `vitest`, `jest`, `rspec`,
  `gradlew test`).

The hot path sets the other limits:

- The Bash hooks run on every Bash call in every project of every user. Today, median of
  15 runs on a plain call: PreToolUse 44 ms, PostToolUse 28 ms without a journal and 37 ms
  with one, a bare Python start 24 ms.
- `pre_tool_use.py` is compiled on every run, because it runs as `__main__` (issue #48).
  Its fast path reads no file, and `tests/test_hooks.py:3539` pins that.
- Importing `hashlib` costs 5.2 ms, because it loads OpenSSL. Importing `_blake2` alone
  costs 1.0 ms. `_common` must not load `re` at import (`tests/test_hooks.py:585`).
- ADR 0023 §12 names a file by a session id after it checks the id against
  `SESSION_ID_PATTERN`. ADR 0031 keeps evidence under the config directory, outside every
  repository, and the journal prunes it at moments it already has.

## Decision

**What is written.** Two rows per observed run, as JSON lines:

- start, from PreToolUse: `{"i": "<tool_use_id>", "h": "<16 hex digits>"}`. The hash is
  BLAKE2b with an 8-byte digest over the stripped command text, encoded as UTF-8 with
  `surrogateescape`. The command is `tool_input.command` as PreToolUse receives it, which
  is the text the model typed.
- end, from PostToolUse or PostToolUseFailure: `{"i": "<tool_use_id>", "x": <exit>}`.

No row holds command text, output, a time, a working directory or an agent id. The join
needs none of them. The end row is written only when the exit status is known:

| Payload | End row |
| --- | --- |
| PostToolUse, no `returnCodeInterpretation`, `interrupted` false, no background flag or `backgroundTaskId` | `x: 0` |
| PostToolUseFailure, `is_interrupt` not true, `error` whose first line is `Exit code N`, N of 1 to 3 ASCII digits and at most 255 | `x: N` |
| anything else: an interpreted exit, a background launch, an interrupt, another `error` form | none |

The `error` text holds the run's output, so the hook reads its first line and drops the
rest. The parse uses string methods, not `re`.

**Where.** `<base>/shipgate/runs/<session_id>.jsonl`. `<base>` is `$CLAUDE_CONFIG_DIR`
when it is set and not empty, else `$HOME/.claude`, by the rule of ADR 0031's evidence
root: environment variables only, and no write when the base is not absolute. The session
id is the payload's `session_id`. It must be a plain token of at most 128 characters from
`[A-Za-z0-9_-]`, checked with string methods; any other id writes nothing.

**One definition.** `hooks/_common.py` holds `runs_root()`, `run_fingerprint()` and the
size bound. The journal loads `_common` by path already (`scripts/_journal/plugin.py`), so
hooks and journal compute one path and one hash. A test pins `runs_root()` and
`evidence_root()` to the same base.

**Who writes, and when.**

- `pre_tool_use.py` gets one call at the top of `main()`, after it reads the command and
  before the forgery net. The call walks up from the payload's `cwd` with `os.path.isfile`
  and returns at the root when no `.claude/shipgate.json` exists. Only then does it import
  the writer module `hooks/_runs.py`. So a project with no settings file costs a few `stat`
  calls and opens no file, and the audit test stays as it is. The write code lives in a
  module with cached bytecode, not in the file that #48 compiles on every call.
- The walk uses the payload's `cwd` only, never `CLAUDE_PROJECT_DIR` or the process
  directory. A test run inside a Claude Code session in a journaled checkout then cannot
  write rows for that checkout.
- `_runs.py` loads the project with `_common.load_project`. A settings file that declares
  `"db": null` writes nothing, and so does `enforce.auto_capture: false`. No new setting.
- `post_tool_use.py` writes the end row for Bash on PostToolUse and on PostToolUseFailure,
  after its existing `likely_journaled()` gate and with one project load per call.
  `hooks/core.json` registers PostToolUseFailure with matcher `Bash` and the same script.
  A failing Bash call fires PostToolUseFailure in place of PostToolUse, so each Bash call
  still starts one post hook process.
- Every error in the writer is swallowed. The writer never prints and never blocks.

**How it is written.**

- The hook creates `<base>/shipgate/runs` with mode 0700 when it is missing. It opens that
  directory with `O_DIRECTORY | O_NOFOLLOW`, so a symbolic link in its place writes
  nothing. The config directory itself may be a link, as ADR 0031 allows.
- It opens the file relative to that directory with `O_WRONLY | O_APPEND | O_CREAT |
  O_NOFOLLOW | O_CLOEXEC`, mode 0600, and writes only to a regular file. One row is one
  `write` of under 200 bytes, so parallel hooks append whole lines.
- When the file has reached 256 KB, the hook renames it to `<session_id>.jsonl.1`, which
  replaces an older one, and starts a new file. A session keeps at most about 512 KB.

**Pruning.** The journal deletes the record of a session 7 days after its last write, at
the moments ADR 0031 prunes: after a `flow-started` and after a terminal append, in any
project. It deletes only regular files named `<plain token>.jsonl` or `.jsonl.1`, one at a
time, without following a link, and never raises. With no `runs` directory on disk the
prune costs one `lstat`. `doctor` reports the directory, its file count and size, what the
next prune deletes, and the names it refuses.

**Threats.**

- **A forged row.** The model has a shell and can write this file, like any file the
  hooks write. No gate reads `observed` (ADR 0033), so a forged row buys a false count in
  `stats` and nothing else. A forgery is a deliberate Bash write into the config
  directory, visible in the transcript. The forgery net is parked until the review of
  about 2026-12-22 (#37), with #42 and #54; this ADR adds no rule to it.
- **A planted log.** The file lives under the config directory, which no repository can
  write to. A cloned repository's own `.claude/` holds nothing the hooks read for this. A
  session id must be a plain token before it names a file. A link in place of the `runs`
  directory or a session file writes nothing, and the journal reads neither through a
  link. A planted `.claude/shipgate.json` makes a repository journaled, so its sessions
  get a log of hashes and exit statuses in the user's own config directory, which harms
  nobody.
- **A secret in a command.** A command may carry a token (`API_KEY=… pytest`). The log
  holds a 64-bit hash, never the text. The output in `error` is dropped. A hash lets
  someone confirm a guessed command but not recover a long random secret. The transcripts
  in the same config directory already hold every command and its output in clear text,
  so the log adds no exposure. A config directory inside a repository (a dotfiles
  checkout) puts this log there too, as it already does with transcripts and ADR 0031's
  evidence.
- **Growth.** 512 KB per session at most, deleted after 7 days.

## Alternatives considered

- **A PostToolUse-only log** (no PreToolUse change). One writer, and the pre hook keeps a
  fast path that reads no file. Rejected by the user (Q1): PostToolUse sees the rewritten
  command, so every rewritten test command would stay unobserved, and most test runners
  are rewritten on the maintainer's machine.
- **A row in the journal database**, appended by the hook through `journal.py`. One store,
  and the journal's own checks. Rejected: a `journal.py` process costs tens of
  milliseconds on every Bash call, and the hooks hold no policy.
- **A file beside the journal**, as `<db>.runs/<session_id>` like ADR 0023's markers.
  Scoped per project, and gitignored by the `.claude/shipgate.db*` glob. Rejected: a
  repository could ship a link in that place, and ADR 0031 already keeps a store outside
  every repository with pruning in place.
- **Command text in the log**, so that the model could pick a run from a list. Rejected by
  the user (Q4): the issue rules out text, and a hash of the typed command is enough to
  match a citation.
- **The original command from the transcript**, read by the post hook or by the journal.
  One writer and no hash in PreToolUse. Rejected: the transcript format is internal, a
  subagent's calls sit in another file, and a transcript can be large.
- **`hashlib.sha256`** for the fingerprint. Rejected for cost: 5.2 ms of import on every
  Bash call. `_blake2` gives the same family of digest for 1.0 ms. The hook falls back to
  `hashlib.blake2b` when `_blake2` is missing, and the journal uses `hashlib.blake2b`; both
  give the same digest. (Correction, 2026-11-26, from the review: the journal calls the
  same `run_fingerprint` of `hooks/_common.py`, as the Decision's "One definition" says.)
- **The working directory in the hash.** It would show where a command ran. Rejected: a
  `cd` inside the command is part of the text already, and a stricter key adds one more
  silent mismatch.

## Consequences

- A `verify-run` can cite a run, a worker's run included, by the command's exact text
  (ADR 0033). A rewrite hook does not break the match.
- A journaled project pays an inline walk, one import of `_runs` and one append in
  PreToolUse, and one append in PostToolUse. The build measures both hooks before and
  after the change; the target is at most 3 ms more per hook in a journaled project and
  at most 1 ms more in a project with no settings file.
- `tests/test_hooks.py` must give every hook a temporary `CLAUDE_CONFIG_DIR`, as the
  journal tests already do. The root `CLAUDE.md` says so.
- The parse of `error` depends on Claude Code's `Exit code N` text, which no document
  promises. If the text changes, failing runs stop being recorded: a pass still matches,
  and a contradiction goes unseen. A test pins the probe's strings.
- The probe did not cover Workflow agents or a session that resumes. A run whose hooks
  carry another session id is never tied to the appending session, so its citation
  counts as not observed. The build probes a Workflow agent once. (Result, 2026-11-25,
  T033: a Workflow agent's Bash hooks carry the parent's `session_id`, plus `agent_id` and
  `agent_type: "workflow-subagent"`, so its runs are logged under the parent session.)
- The hook contract changes: PreToolUse writes a file in a journaled project, and a new
  event is registered. The release check for a hook change and the full `/security-review`
  apply.
