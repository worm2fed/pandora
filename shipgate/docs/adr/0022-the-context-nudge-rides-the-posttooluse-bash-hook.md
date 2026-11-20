---
type: adr
title: "0022. The context nudge rides the PostToolUse Bash hook"
created: 2026-11-20
updated: 2026-11-20
tags:
  - adr
  - shipgate
  - hooks
status: accepted
date: 2026-11-20
issue: "#23"
related:
  - "0021-the-handoff-brief-is-computed-not-written.md"
  - "../prd/phase-handoff.md"
  - "../prd/phase-handoff.worklog.md"
---

# 0022. The context nudge rides the PostToolUse Bash hook

> After a Bash call that appended `design-committed`, or a `review-verdict` that is
> `not-ready`, the PostToolUse hook reads the session's last context size from the
> transcript. Past the configured threshold (default 500k) it prints one line for the user
> and the model that recommends the handoff. It never blocks.

## Context

FR-014 asks for a measured nudge at a phase boundary. A skill cannot see its own context
size. The hook payload carries `transcript_path`, and each main-thread assistant record in
the transcript carries `message.usage`. Context tokens are `input_tokens +
cache_read_input_tokens + cache_creation_input_tokens` of the last such record.

Phase boundaries reach the harness as Bash calls that run `journal.py append`. The append
prints `appended <type> to <stream>: …`, or a JSON line with `"type"` and `"stream"` under
`--json`. A refused append prints to stderr only.

The hooks run in every project on every user's machine, and PostToolUse fires on every
Bash call. The config marks hooks and reads outside the plugin directory as
security-sensitive, and a change to the hook contract is the user's decision.

## Decision

The user decided the three choices most likely to change (2026-11-20, relayed by the lead;
journal `gate-decision` rows with `raised_by: user`). The rest is as proposed.

- **What fires:** the PostToolUse hook already registered for `Bash`. No new event and no
  change to `hooks/core.json`.
- **When (user):** after an append of `design-committed`, and after an append of a
  `review-verdict` that is `not-ready`. A `ready` verdict does not fire it. The hook finds
  the append's own output in the call's stdout: the `--json` object or array, or the text
  summary, each with the row's `seq`. `journal.py nudge` checks that this seq is the
  stream's newest event of that type and reads the verdict. So a refused `--json` append
  (an `error` object with no `seq`) and a quoted old append line print nothing. When one
  call appended several, the newest `design-committed` wins over a verdict.
  Every other Bash call returns after two substring checks and never imports the nudge's
  code (`hooks/_nudge.py`).
- **What it reads:** the last 256 KB of `transcript_path`, and the last 4 MB only when a
  large record sits after the last usage. The path must be absolute; the file is opened
  non-blocking and read only when it is a regular file. It skips sidechain and synthetic
  records and takes the last assistant `usage`. Only that number leaves the hook.
- **Threshold (user):** the config key `Handoff: <tokens | off>` in a new `## Session`
  section, default 500k. `journal.py` reads it through the config layers (ADR 0018: the
  repo's files from the session's directory up, then the umbrella's, then the user file),
  so the user file can set it once for every project. The hook passes the session's `cwd`
  as `--start`, because `journal.py` itself runs at the project root. An unreadable value
  falls back to the default.
- **What it prints (user):** one line, as a `systemMessage` the user sees and as
  `additionalContext` for the model, for example `shipgate: this session's context is about
  612k tokens, past the handoff threshold (500k). A fresh session is cheaper from here:
  print the brief with journal.py handoff --stream=feat/x, then run /clear and /shipgate.`
  The stream is shell-quoted in the command.
- **Cost (measured):** a non-boundary Bash call adds two substring checks on stdout (1.6 µs
  on 2 KB, 89 µs on 200 KB); the hook process is unchanged against 0.26.0 (median 54.6 ms
  against 56.9 ms, interleaved). A boundary call takes about 234 ms in all, with one
  `journal.py` process, two to four times per flow.
- **Never blocks:** no exit 2, no `decision` key. Any failure prints nothing.

## Alternatives considered

- **No hook: the skills always recommend the handoff.** Cheapest and no hook change. It
  loses the measurement, so a short session gets the same advice as a 700k one.
- **The Stop hook.** It already runs every turn, but it can add text to the session only by
  blocking, which is the wrong tool for advice.
- **A UserPromptSubmit hook.** It sees every prompt, but it adds a new hook event and runs
  on every prompt, not at a boundary.
- **The hook reads the threshold itself.** Saves the 80 ms process, but puts a config read
  and a rule in a hook. The hooks hold no policy (`hooks/_common.py`).

## Consequences

- **Positive:** the advice comes only when it pays, and the number is measured, not
  guessed.
- **Negative:** a phase event appended in a way that prints neither form (a helper that
  swallows stdout) gets no nudge. The skill text still recommends the handoff.
- **Follow-ups:** shipgate-hud shows the same number against the same threshold (#23, HUD
  part).
