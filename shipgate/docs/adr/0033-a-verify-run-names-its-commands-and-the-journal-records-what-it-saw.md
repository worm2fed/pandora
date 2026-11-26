---
type: adr
title: "0033. A verify-run names its commands, and the journal records what it saw"
created: 2026-11-25
updated: 2026-11-25
tags:
  - adr
  - shipgate
  - journal
  - verify
status: accepted
date: 2026-11-25
issue: "#27 (shipgate), child of #37"
related:
  - "../prd/observed-verify-run.md"
  - "../prd/observed-verify-run.worklog.md"
  - "./0032-the-bash-hooks-log-each-observed-run-by-session.md"
  - "./0031-a-ui-task-is-done-with-screenshots-on-disk.md"
  - "./0020-the-stop-gate-binds-a-worklog-the-way-position-does.md"
  - "./0010-a-user-row-records-its-writing-session.md"
---

# 0033. A verify-run names its commands, and the journal records what it saw

> A `verify-run` must carry `commands`, each item with `cmd` and `exit`. The journal
> derives `outcome` from the exit statuses and refuses an `outcome` that disagrees with
> them. At append it looks up each command in the session's run log (ADR 0032) and stores
> `observed: true` or `false`, and `contradicted: true` when a command's newest run ended
> with another exit status. No gate reads the new keys. The event shape changes, a one-way
> door: the user accepted this ADR on 2026-11-25, in a question dialog relayed by the lead.

## Context

Issue #27: 935 of 944 `verify-run` rows in seven journals pass, and every one of 1,320
`task-done` ids has a passing row. The row is a key to the gate, not evidence. Today the
shape requires only `outcome` and `task_ids` (`scripts/_journal/vocab.py:293-298`), and
`_passing_verify_runs` reads only `outcome` (`scripts/_journal/gates.py:57-62`).

The user decided the shape in the clarify dialog of 2026-11-25, relayed by the lead:

- Q2, alternative A: `commands` with `cmd` and `exit` is required. `outcome` is derived
  from the exit statuses, and an `outcome` that disagrees with its own payload is
  refused. A pass that the newest observed run contradicts is stored `observed: false`,
  marked so `stats` can count it, and measured for one month. A gate waits for the
  December review with #42. The reason: a refusal is a new gate, and it misfires after a
  failed run, a fix and a background re-run, because no hook sees a background run end.
- Q4: a row cites a run by the exact command text the model typed plus its exit status.

The code and the data set the rest:

- `list_objects` already validates a list of objects with required keys
  (`scripts/_journal/shapes.py:274-284`). `required` counts only `None` and `""` as
  missing, so an empty list passes. `integers` refuses a negative value and a boolean.
- The 1 KB cap measures the normalized payload of a work stream before the journal adds
  its own keys (`scripts/_journal/append.py:169-178`). `recorded_by` is the precedent for
  a key the journal owns: popped from the caller's payload after the cap check, then set
  (ADR 0010).
- This repository's journal: 263 cited command strings have a median of 46 characters
  and a maximum of 257. Payloads have a median of 273 bytes and a maximum of 807.
- `append` learns the session only from `CLAUDE_CODE_SESSION_ID`
  (`scripts/_journal/sessions.py:46-57`). A subagent's shell gets the parent's id.
- Some checks are no Bash command: a manual UI check, an MCP tool, a read of a file. The
  lead asked for a named way out for them.

## Decision

**The shape.**

```python
"verify-run": {
    "required": ["task_ids", "commands"],
    "enums": {"outcome": ["pass", "fail"]},
    "lists": ["task_ids", "commands"],
    "aliases": {"result": "outcome", "tasks": "task_ids"},
    "list_objects": {
        "commands": {"required": ["cmd", "exit"], "strings": ["cmd"], "integers": ["exit"]},
    },
}
```

An item may carry other keys (`tail`, `ran`), as items do today.

**The outcome.** After the shape check and before the cap check:

- With items in `commands`, the derived outcome is `pass` when every `exit` is 0, else
  `fail`. An absent `outcome` is set to it. A present `outcome` that differs is refused
  as a shape error (`GateViolation`, exit 4), and the message names the exit statuses.
- With an empty `commands` list, `outcome` is required. This is the way out for a check
  that is no Bash command: the row names the check in `scope` and is stored
  `observed: false`.
- `--force` waives neither rule. Like the shape check, they decide whether the row can be
  read at all.

**What the journal records.** After the cap check, as with `recorded_by`, the journal
pops any `observed` or `contradicted` the caller sent. It reads the run log of the session
in `CLAUDE_CODE_SESSION_ID` through `runs_root()` of `hooks/_common.py`: the file
`<session>.jsonl.1`, then `<session>.jsonl`, each opened without following a link, as a
regular file, and read to at most 1 MB in total. It skips a line that is not a JSON object
of the row forms in ADR 0032. It keeps the start rows as a map from `i` to `h`, and the
end rows in file order. For each command:

- The command's hash is `run_fingerprint(cmd)`. Its runs are the end rows whose `i` maps
  to that hash. The newest run is the last of them in file order.
- **matched**: the newest run's exit status equals `exit`.
- **contradicted**: the newest run's exit status differs from `exit`.
- **unmatched**: the command has no run in the log, or there is no session id, or no log.

The row stores `observed: true` when it has at least one command and every command is
matched, else `observed: false`. It stores `contradicted: true` when any command is
contradicted, and leaves the key out otherwise. A forced row is checked the same way.

**What the append prints.** One line per command that is not matched, after the
`appended` line, on stdout:

```text
not observed: `pytest -q` — no foreground run of this exact command in this session; run it in the foreground here and cite it as typed
not observed: `pytest -q` — its newest run in this session exited 1, not 0 (stored as contradicted)
```

The command is shown clipped to 60 characters. The notices change no exit code.

**What reads it.** No gate. `task-done` and the ready verdict keep reading `outcome`, so a
contradicted pass still satisfies them until the December review. `journal.py stats`
counts, per stream and in total: `verify_observed`, `verify_unobserved`,
`verify_contradicted` (a subset of the unobserved) and `verify_unrecorded` (rows with no
`observed` key: before this release, or from an older `journal.py`). It prints the
observed share over the rows that carry the key. The status brief, the position JSON, the
digest and the HUD do not change.

## Alternatives considered

- **Refuse a contradicted pass** (the recommendation sent to the user). It stops a stale
  pass at once. Rejected by the user (Q2): it is a new gate, it misfires after a failed
  run, a fix and a background re-run, and #37 holds gate changes until the December
  review. The mark keeps the data that review needs.
- **`commands` stays optional**, and a row without it is stored `observed: false`. No
  break for any caller. Rejected by the user (Q2): the model would leave the list out,
  and the issue asks for required fields.
- **A refusal for an empty `commands` list.** It forces a command on every row. Rejected:
  a manual UI check, an MCP tool or a read has no command, and a fake command would be
  worse than an honest empty list that `stats` counts as not observed.
- **Refuse a caller's `observed`** in place of replacing it. It tells the model at once.
  Rejected: the `recorded_by` precedent replaces the key silently, and a row from an
  older plugin's skill text must not fail for a key it was never told about.
- **A run id in the payload.** Rejected by the user (Q4): a `tool_use_id` never reaches
  the model as text.
- **A key per command (`commands[].observed`).** Finer detail. Rejected: the append
  notice names the commands at the moment it matters, and `stats` needs one key per row.

## Consequences

- A `verify-run` with no `commands` key is refused from this release. The verify skill's
  example already carries the list, and so does the Stop gate's suggested command
  (`scripts/_journal/check.py:219-224`). About 100 test call sites must add it.
- Rows in journals today stay valid. No reader treats a missing `observed` as false.
  Older plugin versions keep writing the old shape through their own `journal.py`, and
  `stats` counts those rows as not recorded.
- A row from an older `journal.py` can carry an `observed` value that its model typed. The
  new journal cannot tell it from a computed one. No skill tells a model to type it, and
  `stats` counts such a row like any other.
- `observed` proves that the session ran the exact command with the named exit status. It
  does not prove where the command ran, what its exit status means (`pytest | tail`), or
  that the run came after the last edit.
- A run before a new session id is tied to no appending session in the log, so its
  citation counts as not observed. (Correction, 2026-11-25, from the build's probe, T033:
  a Workflow agent's Bash hooks carry the parent's `session_id`, as a subagent's do, so its
  foreground run is in the parent session's log and a citation of it counts as observed.)
- The December review with #42 can decide a gate from `observed` and `contradicted`
  without a new event shape.

## Notes for the December gate review

Added 2026-11-26, at the Capture of #27. Read these before a gate reads `observed` or
`contradicted`.

- **A run past the Bash tool's time limit is never observed.** A foreground Bash run that
  passes the tool's limit (at most 10 minutes) moves to the background, and no hook sees
  its exit code. So the full suite of a large project may never count as observed: the
  suite of this repository takes about 15 minutes, and its runs in the build of #27 moved
  to the background. The verify skill and the README name the case and its remedy (a
  longer timeout, or a narrower run in the foreground); no rule enforces it. Before a gate
  refuses an unobserved pass, count how many unobserved rows cite such a long command.
- **A contradicted row is not always a stale pass.** The user chose to store a
  contradicted pass, not to refuse it, because a refusal misfires after a failed run, a
  fix and a re-run that no hook sees end (a background run, or one past the time limit):
  the newest observed run is then the old failure. Before a gate refuses a contradicted
  row, sample the contradicted rows of the month and sort them into a stale claim and such
  a re-run. A pipe hides a failure the other way (`pytest | tail -5` exits 0 on failing
  tests, so the row is observed and proves nothing); the verify skill now says so.
