---
type: adr
title: "0023. The user's go is recorded where the user answers, and a commit waits for it"
created: 2026-11-20
updated: 2026-11-21
tags:
  - adr
  - shipgate
  - hooks
status: accepted
date: 2026-11-20
issue: "#22, amended by #52 (children of #37)"
related:
  - "0015-the-user-approves-a-publish-outside-the-model-tools.md"
  - "0010-a-user-row-records-its-writing-session.md"
  - "0009-the-journal-computes-the-hud-position.md"
  - "../prd/approval-path.md"
  - "../prd/approval-path.worklog.md"
  - "../../../shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md"
---

# 0023. The user's go is recorded where the user answers, and a commit waits for it

> A recorder hook writes the user's go from a question answer and from a typed reply. When
> the reply is free language, the hook writes a witness, and the flow asks one confirming
> question with the gate header. The hook records the click (the amendment of #52 at the
> end). A command gate holds a model's commit, push and MR/PR creation until the stream
> holds a go. No forced event opens a publish. This ADR extends ADR 0015. It replaces items
> 1, 4 and 8 of that ADR where they name two markers and the publish gate only.

Status note: the user ruled on the open points on 2026-11-20, and the lead relayed the
rulings. The user chose three of them: "No, always my go", "Word list, else model reads"
and "On by default". The others are the orchestrator's recommendations. The lead presented
them as defaults, and the user did not object. The PRD lists all ten under "Rulings".
During the build the user ruled on two more points: one publish go covers the commit, the
push and the MR/PR creation ("One go covers all"), and the hook refuses a model's
`journal.py import` ("Hook refuses a model's import", decision 20).

## Context

ADR 0015 let two paths record the user's publish approval: the HUD dialog (`source:
dialog`) and the user's `!` command (`source: shell`). Real use went another way (#22):

- Seven journals hold 3 dialog approvals and 0 shell approvals.
- The flow asked 152 commit or publish questions through `AskUserQuestion`.
- The PreToolUse hook refused 21 appends that tried to record such an answer.
- 13 `mr-opened` events are forced, mostly with the reason "the user approved in
  AskUserQuestion".
- A commit has no gate. 6 of 40 user interrupts hit a commit, an amend or a push.

The approval is real, but it happens where no recorder listens. So the model forces the
event, and a forced path that is the normal path checks nothing.

Three facts about the harness decide what a recorder can do. They come from the hooks
reference and from one interactive probe (Claude Code 2.1.329, auto mode, 37 hook records):

- **PostToolUse fires on `AskUserQuestion`.** `tool_response.answers` maps each question
  text to the selected label. A multi-select joins the labels with `, `. A free-text answer
  arrives as the typed text in the same place.
- **UserPromptSubmit receives `prompt` and no origin field.** It also fires for a subagent
  report, a message from another session and a scheduled task. A subagent report arrives
  inside an `agent-message` tag. A bash-mode line does not fire it. A text that another
  program pastes into the terminal is a prompt, and only a wrapper tag in the text shows it.
- **A subagent's tool call carries `agent_id` and `agent_type`.** A main-thread call carries
  neither.

Two more facts come from the same probe. A PreToolUse `ask` decision shows the permission
dialog in auto mode. The hook process carries the session id in its environment.

A probe on a scratch journal of 0.26.0 shows a second way around the publish rule. A
forced `review-verdict` with `verdict: ready` exits 0. A plain `mr-opened` after it exits
0, and `status --json` prints `publish` as authorized by that verdict.

Real use adds three constraints:

- The user approves by a question answer, by a typed reply, and by the HUD dialog. A typed
  reply is often free language: "it can go", "commit and start the next batch".
- In a lead and teammate setup, the user answers in the lead's session. The teammate's
  session never sees the answer. Both sessions write one journal.
- The user answers several steps with one reply.

The threat model of ADR 0015 stands. The goal is a net against a flow that forges the go
through its tools. It is no defence against deliberate circumvention.

## Decision

1. **The go.** A go is the user's approval of one gate on one stream. The gates are
   `commit` and `publish`. A go is a `gate-decision` with `gate: <gate>`, `decision:
   <gate>`, `raised_by: user` and a `source` marker. A publish go also satisfies the commit
   gate. A go lasts until the stream's next `task-done`.
2. **Five markers** (four since the amendment, which retires `read`). `source` is one of
   `dialog`, `shell`, `question`, `prompt` and `read`. `question` marks an exact go from a
   question answer. `prompt` marks an exact go from a typed reply. `read` marks a go that
   the model recorded after it read a witnessed reply. The first four rows have the actor
   `user`. A `read` row has the actor of the session that read the reply. The meaning of
   `dialog` and `shell` does not change.
3. **The go request.** A new event, `go-requested`, records that a session put one gate of
   one stream to the user. It keeps the question text. The model writes it with a normal
   `append`, because a request authorizes nothing. Any session can write it for any live
   stream. A request is open until a marked user decision at that gate or a witness of the
   request lands on the stream.
4. **A reply answers every open request of its own session.** A reply is a question answer
   or a typed prompt. For each open request the reply is an exact go or it is not. The
   recorder writes an exact go for each request the reply matches. It writes a witness for
   every other open request of the session. So no request waits for a later `yes`.
5. **The exact go of a question answer.** A question is a gate question when its header is
   `commit` or `publish`, in any case. An answer that equals the gate word is a go for the
   open requests at that gate. In a multi-select, each selected label that names a live
   stream is a go for that stream. No other answer is an exact go.
6. **The exact go of a typed reply.** Only a whole-prompt match against a built-in word
   list is an exact go. The match ignores case, outer space and one closing period or
   exclamation mark. A gate word (`commit`, `publish`, `push`) is a go for the open
   requests at that gate. A general word (`all`, `yes`, `y`, `ok`, `go`, `approve`) is a go
   for every open request of the session. Neither the hook nor the journal reads free
   language.
7. **The witness.** A new event, `reply-witnessed`, records that the user replied to one
   open request with a reply that is no exact go. It names the request, the gate, the
   session and the way the reply came. It holds no text. Only the recorder writes it. The
   recorder tells the model which witnesses the reply left.
8. **The read go** (the amendment replaces it with the confirming question). The model
   reads the witnessed reply. When the reply approves the gate, the model appends a go with
   `source: read`, `witness: <seq>` and `words`, the user's approving words in at most 200
   characters. It asks no confirming question. The journal refuses the append unless all of
   these hold: the witness is on the same stream; its actor is the hook; its gate is the
   gate of the go; it is later than the stream's last `task-done`; no other go names it;
   the appending session is the witness's session. `--force` never waives this check. The
   go rule checks the witness again when it reads the stream. So a go without a real reply
   of the user after the request stays impossible through a normal tool path.
9. **A gate word with no open request** is a go for the stream the session drives: the
   live stream that the session last wrote to. Any other reply with no open request records
   nothing, and nothing witnesses it.
10. **What is no reply.** A prompt that starts with a tag is no reply: a subagent report, a
    message from another session, a relayed text in a wrapper. It records nothing, and it
    closes nothing.
11. **Who writes the record.** One hook script, the recorder, runs on UserPromptSubmit and
    on PostToolUse with the matcher `AskUserQuestion`. It passes the reply to the journal
    subcommand `reply` on stdin. `reply` only plans: it prints the rows and writes nothing.
    The recorder then writes the rows with the existing `append`. So the journal owns the
    word list and the matching, and the model gets no new command that writes a go or a
    witness. A typed text longer than 32 characters never leaves the hook. No row of the
    recorder holds the text of a prompt.
12. **A marker file keeps the prompt path cheap.** When the journal appends a
    `go-requested`, it creates an empty file for the appending session beside the journal
    database. The recorder runs the journal for a prompt only when that file exists, or
    when the prompt has at most 32 characters. It removes the file when the session has no
    open request left. The file is a hint and never a rule: a stale file costs one journal
    run, and a lost file costs one more go request.
13. **These rows do not bind a session.** A `go-requested` row, a witness and a
    `gate-decision` with the marker `question`, `prompt` or `read` do not count when the
    journal decides which stream a session drives. So a lead that records a go for five
    streams keeps its own position, and its Stop gate does not change. This narrows ADR
    0010 for these rows only.
14. **The command gate.** The PreToolUse hook on Bash holds four commands of the model:
    `git commit` needs a go for the commit gate, and `git push`, `gh pr create` and
    `glab mr create` need a go for the publish gate. The hook resolves the branch of the
    directory the command acts on, and the journal subcommand `authorize` answers for that
    branch's live stream. With no go the hook returns `deny`. The reason names the stream,
    the gate and the ways forward. A subagent's call meets the same rule, and its reason
    tells it to hand the question back.
15. **Where the command gate does nothing.** A project with no sidecar. A branch with no
    live stream. A project whose sidecar sets `enforce.command_gate` to false: the gate is
    on by default. A command that is none of the four: the hook then reads no file. A hook
    crash, a timeout or a journal that cannot be read passes the command.
16. **The command gate asks for the user.** A ready verdict opens no commit, no push and
    no MR/PR creation. `mr-opened`, `status --json` and the HUD keep the rule of ADR 0015:
    a ready verdict or the user's publish go. `status --json` and `position --json` add
    `go`, the user-only answer for each gate.
17. **No forced event opens a publish.** `--force` does not waive the `mr-opened` rule,
    and the refusal no longer offers it. A forced ready verdict does not authorize a
    publish: the publish rule skips a `review-verdict` that carries `forced`. An MR/PR that
    the user opened by hand on an unreviewed stream takes a go, as any publish does.
18. **The forgery net grows with the gates** (the amendment removes the exception). The
    PreToolUse hook refuses a model's append of a user decision at the commit gate, as it
    does at the publish gate. It refuses a model's append of a `reply-witnessed` event. It
    still refuses a `source` marker at any gate, with one exception: a `gate-decision` with
    `source: read` and an actor that is not `user` passes the hook, and the journal checks
    its witness.
19. **`stats` counts the go records by marker.** So the share of read go records is
    visible, and a retro can audit them against their witnesses. (Since the amendment a
    read row is no go, so `stats` does not count it.)
20. **A model's `journal.py import` is refused.** `import` writes the rows of a file with
    no shape, gate, read-go or actor check, so a model could write the user's go with its
    Write tool and one import (the security review of the build, finding 1). The
    PreToolUse hook refuses any `journal.py import` a model runs, whatever the file. The
    refusal says that the user runs the import with `!` when moving a journal between
    machines. The user ruled for this on 2026-11-20: "Hook refuses a model's import".
    A crash of the forgery net on a line that names `journal.py` and `import` refuses it,
    as a crash on a publish append does (ADR 0015).
21. **A model's command that runs the recorder script is refused** (the amendment keeps
    "a line that names the script" as it is; A6). The recorder,
    `hooks/reply.py`, is a script. A model could run it from its own Bash call with a
    forged payload (`{"prompt": "publish"}`), and its child journal runs would write the
    user's go, since PreToolUse never sees them (the built-in security review of the
    build commit, MEDIUM). The PreToolUse hook refuses a command that runs it: as the
    program, as a Python's script word, or through a script word it cannot read on a line
    that names the script. A crash of the forgery net on a line that names the script
    refuses it too. A runner module that runs the path after it (`python3 -m cProfile`,
    `profile`, `trace`, `pdb`) counts, and so do the wrappers `arch` and `xcrun` (the
    security review of the amended commit). It stays a net, as ADR 0015 accepts. Accepted
    limits: a copy of the
    script, a script of the model's own that drives the journal, and a nested `claude`
    session that resumes the parent session and fires its real hooks (not probed). The
    user ruled for this on 2026-11-21: "Hook refuses running the script". This qualifies
    decision 11: the model gets no new command that writes a go or a witness, because the
    hook refuses the one script that does.

## Alternatives considered

- **A fixed word list only, and a confirming question for any other reply.** This was the
  first design. It keeps the model out of the decision. But the user approves in free
  language, and a second question for "it can go" is the friction this issue removes. The
  user ruled for the read go. (The amendment returns to this design.)
- **The model reads every reply, and no word list exists.** The common short replies would
  then also rest on the model's reading. The word list keeps them deterministic, and a test
  pins it.
- **A read go with no witness.** The model would then record the go on its own word, which
  is the forged path of #22 under a new name. The witness ties each read go to one real
  reply after one recorded request.
- **A check of the turn's prompt id in the PreToolUse hook.** The hook could let a read go
  through only in the turn that the witnessed reply started. This bounds a late reading.
  But it puts a journal query and a rule into the hook. The last `task-done`, the single
  use and the session bound the read go without it.
- **The native permission dialog instead of a refusal.** A PreToolUse `ask` shows the
  dialog in auto mode, and the model cannot answer it. But it asks the user a second time
  after a typed `commit`. It appears in a teammate's pane, where the user does not look.
  And it leaves no record for `mr-opened`.
- **Question answers only, with no UserPromptSubmit hook.** This adds no hook event. But a
  typed reply is a main way the user approves, and it would then meet a refusal.
- **No go request: the reply names its streams.** A question can carry the stream in its
  text. A typed `all` cannot. And a lead's session drives another stream than the one the
  user approves. The request is the one record that gives a short reply its meaning.
- **A `reply` subcommand that writes the rows itself.** It saves one process per recorded
  reply. But the model could then call it with a forged prompt, and the lexer of ADR 0015
  would need a new rule to refuse that call.
- **One journal run for every prompt, with no marker file.** It needs no second place for
  state. But it costs a process on every prompt of a journaled project, and most prompts
  answer no request.
- **Drop the verdict branch of the publish rule.** `mr-opened` and the HUD would then ask
  for the user's go only. This is one rule for every publish. But it changes what the HUD
  holds, and a PR that the user opened by hand on a reviewed stream would need a second
  approval. The command gate already asks for the go before a model's push.
- **Keep force with a reason.** The reason was free text, and 13 forced events used it as
  the normal path.
- **Read the transcript at the commit.** The PreToolUse hook could look for the user's last
  message there. The transcript format is no contract, and the file is large.
- **Move the shell lexer into its own module first.** The command gate and the forgery net
  share the lexer, so one module each would be cleaner. But the move changes about 1,100
  lines in the hook with the highest fix rate, in the same release as two new rules.

## Consequences

- The plugin gains one hook event, UserPromptSubmit, and one PostToolUse matcher. Both run
  in every project. Off a journaled project each does a few `stat` calls and exits.
- On a journaled project a prompt costs a journal run only when the session has an open
  request or the prompt is short. The build measures both cases against a budget.
- A project with a running flow meets the command gate at upgrade. Its next commit needs a
  go.
- An unattended run has no user, so it gets no go. Such a project turns the command gate
  off in its sidecar.
- The model decides what a free-language reply means. The journal holds the witness, the
  quoted words and the marker, so a wrong reading is visible after the fact. It is not
  prevented. (The amendment removes this: the user's click decides.)
- A caller that forced `mr-opened` or forced a ready verdict to publish now meets a
  refusal. The CHANGELOG says so.
- The flow text changes: the skills record a go request, ask with the gate header, and
  record a read go from a witness. A session that asks for another session's stream records
  the request itself. The change is judged on both session models in use.
- shipgate-hud needs no change to work. Its refusal text still names the dialog and `!`
  only, so a follow-up updates it.
- Known limits, accepted:
  - A commit that another command makes is not held: `git merge`, `git rebase`,
    `git cherry-pick`, `git revert`, an alias, a script. Opaque text such as `sh -c "$X"`
    passes, as in the HUD's scan.
  - The command gate's fast path reads the raw command text, so a spelling with split
    quotes (`git c''ommit`, `gh pr cr""eate`) passes unread: the same class as the raw-text
    fast path of ADR 0015's forgery net.
  - A push is judged against the branch of its directory, not against its refspec.
  - A program that pastes a bare word into a session's terminal forges a reply. A relay
    inside a wrapper tag does not.
  - A free-language reply that comes before the go request leaves no witness. The flow
    then records the request and asks again.
  - A session that asks two things in one message can read a `yes` as the go. The go
    request and its question text stay in the journal for an audit.
  - The shape of a scheduled task's prompt is not probed. A scheduled prompt that is a bare
    gate word records a go.
  - A ready verdict still authorizes `mr-opened` and the HUD's gate. The verdict rests on
    `verify-run`, which is a claim until #27.

## Amendment (2026-11-21, #52): a confirming question replaces the read go

Status: accepted. The user ruled on #52, and the lead relayed the ruling. The release is
0.28.1. 0.28.0 is on `main` and gets no tag.

### Context

The two-turn check of SC-010 ran after the merge of 0.28.0 and before any tag, on both
session models. Both runs recorded the go request, asked with the header `Commit` and got
the recorder's witness of "it can go". Both runs then failed the read go and the commit.
Claude Code's auto permission mode refused the model's `append` of the read go: its
classifier read the call as the model recording its own approval. The hook payloads show
`permission_mode: auto`. The plugin's own hooks did not refuse the append, and neither
model tried to get around the block.

So the read go cannot work where the user runs the flow. A go that the model writes is the
pattern that auto mode stops, under any marker.

The same release check found a false refusal of decision 21. A Bash call wrote a text file
through a heredoc whose text named the recorder's path. The same call ran `python3` on
another script through a quoted variable path. The hook refused the call as a run of the
recorder, because "the line names the script" read the raw line, heredoc text included.
Only a session that writes text naming the recorder script meets this refusal, which in
practice means shipgate's own development.

### Decision

A1. **An exact go stays a go at once.** Decisions 5 and 6 do not change.

A2. **After any other reply the flow asks one confirming question.** The recorder still
    writes a witness for each open request that the reply does not match. The witness
    still closes that request (decision 4). The recorder's context line tells the model to
    record a new go request, then ask one confirming question with the gate header and the
    gate word as the first option. The line carries the command of the go request. The
    click on the gate word is a question answer, so the recorder records it as an exact go
    with the marker `question` (decision 5). When the answer to the confirming question is
    no go either, the user did not confirm. The flow then records nothing and asks no more.

A3. **The `read` marker is retired.** The journal refuses a `gate-decision` whose `source`
    folds to `read`, with or without `--force`. The PreToolUse hook refuses every `source`
    marker in a model's append, so decision 18 loses its exception. The model writes no go
    row in any form. This replaces decision 8 and the `read` part of decision 2.

A4. **A read row from 0.28.0 is inert.** It stays in the journal, and the journal opens. It
    is no go for any gate, so it authorizes no commit and no publish. `stats` does not
    count it as a go. It still binds no session (decision 13), so a lead's position does
    not change at the upgrade. No migration runs. A go lasts only until the next
    `task-done`, so the worst case is one held commit and one confirming question.

A5. **The hold of the command gate names the confirming question.** A witness of the
    stream at the gate, newer than the last `task-done`, means that the user's reply was no
    exact go. The hold then asks for a new go request and one confirming question. The
    `authorize` reason stays `witness-waits`.

A6. **A note that names the recorder still counts, and the exemption is rejected.**
    The false refusal of decision 21 stays: the line names the script wherever its raw text
    holds the name, as in 0.28.0. The refusal text adds one sentence: a command that only
    writes text naming the script should write the file with the Write tool. An exemption
    for such a note was built and reviewed in four rounds, and each round found a bypass
    that 0.28.0 refuses. Round 1 forged a `prompt` go end to end through
    `echo "${R:=…/hooks/reply.py}"; python3 "$R"`, and found `read R < <(echo …)` too.
    Round 2 let a note reach a variable through a coprocess, a captured function body, a
    builtin's unquoted heredoc and a misread `$[1<<2]`. Round 3, the built-in security
    review of the commit, found a pipe that ends the line, a `case` pattern inside `$(`
    and a zsh `foreach … end | read`. Round 4 found that the fix for the line-ending pipe
    let a forged `--batch` append through `| 2>/dev/null`. The benefit is small: only a
    session that writes text naming the recorder script meets the refusal. So the hook's
    run detection for the recorder is the rule of 0.28.0, with none of the lexer additions
    the exemption needed. A skip of a command's own program word in the wrapped-line
    scan, meant to stop a second false refusal (an escaped `\|` in a search pattern behind
    an unknown runner), was dropped too. It trusted the wrapper scan to find the program,
    and that scan misreads an option cluster such as `env -vS '<line>'`, whose value
    `env` runs as a command line: the review forged a go through it. Both false refusals
    stay, and #54 holds them.

### Alternatives considered

- **Keep the read go, and ask the user to allow it in auto mode.** Every user of auto mode
  would meet the refusal first. An allow rule for the model's own approval is the bypass
  that the classifier stops.
- **The witness keeps its request open, so the click answers the first request.** Then
  every later reply of the session writes another witness until a go lands, and a later
  `yes` to another question is a go. Decision 4 closes requests for this reason.
- **The recorder records the new go request itself.** The model then needs no extra
  append. But the hook would write a row whose question only the flow knows.
- **A go request key that names the witness it confirms.** The journal could then tell a
  confirming question from a first one and print "the user did not confirm". It adds a key
  to the contract for a case that the flow knows from its own turn.
- **Honour an old read row.** It keeps the removed code path alive for rows that only an
  untagged release wrote.
- **Drop the unread-word rule of decision 21.** It closes the false refusal, and it opens
  `R=hooks/reply.py; python3 "$R"` again.
- **Exempt a note from "the line names the script".** Tried in four review rounds of #52
  and rejected (A6): each round found a bypass that 0.28.0 refuses.

### Consequences

- A free-language approval costs the user one click. An exact word costs nothing more.
- The model records no go in any form. Only the recorder, the HUD dialog and the user's
  `!` command write a go.
- The context line names no witness seq. The `<seq:N>` placeholder of the recorder is gone.
- `gate-decision` loses the keys `witness` and `words`. A row that holds them still reads.
- Known limits, accepted:
  - A command that names the recorder's path in data (a heredoc note, an `echo`, a search
    pattern) and also runs Python through an unread script path is refused (A6). Such a
    command writes its file with the Write tool instead.
  - A text-only command that can also run a program (a git alias with `!`, `rg --pre`) is
    read as text, as before. So are `source <(…)`, `bash <(…)` and a name split by quotes
    (`rep''ly.py`). The lexer also does not read a `$( )` inside an unquoted heredoc body,
    a heredoc opened inside `$(` on its operator line, or `$[1<<2]`; a run of the
    recorder hidden there passes. Each passes on 0.28.0 too; a follow-up can close them.
  - A runner that the wrapper table does not know, whose literal argument lexes to a path
    that ends in the script's name, is still read as the recorder. The hook cannot tell it
    from `ssh host 'hooks/reply.py'`.
  - A Python program on stdin (`python3 - <<'EOF'`) is still lexed as a shell script for
    events. A shell example in its text that runs the recorder through a variable is still
    refused.
