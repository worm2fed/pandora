---
type: prd
title: "PRD: the approval path for commit and publish"
created: 2026-11-20
updated: 2026-11-20
tags:
  - prd
  - shipgate
  - hooks
  - journal
status: clarified
issue: "#22 (child of #37)"
worklog: "./approval-path.worklog.md"
related:
  - ../adr/0015-the-user-approves-a-publish-outside-the-model-tools.md
  - ../adr/0010-a-user-row-records-its-writing-session.md
  - ../adr/0023-the-users-go-is-recorded-where-the-user-answers.md
  - ../research/2026-11-15-agent-harness-audit.md
---

# PRD: the approval path for commit and publish

> The journal records the user's go where the user gives it: in a question answer, in a
> typed reply, or in the HUD dialog. A commit or a publish without that record is held. No
> forced event stands in for the go.

## Problem

Since 0.23.0 two paths record the user's publish approval: the shipgate-hud dialog and a
`!` shell command (ADR 0015). The user does not use them. The numbers come from seven flow
journals (9,449 events) and 148 main-session transcripts (research note, finding 3):

- The journals hold 3 dialog approvals and 0 shell approvals.
- The flow asked 152 commit or publish questions through `AskUserQuestion`. The user took
  the first option in 85% of them.
- The PreToolUse hook refused 21 appends that tried to record such an answer.
- 13 `mr-opened` events are forced. The usual reason is "the user approved in
  AskUserQuestion".
- A commit has no gate. "Don't commit unless the user asks" is prose in two skills. 6 of 40
  user interrupts came while the agent announced a commit, an amend or a push.

So the gate checks nothing: the forced path is the normal path. The real approval leaves no
record, and a commit that nobody approved meets no check.

Real use adds three facts that the paths of 0.23.0 do not cover:

- The user approves in three ways: a question answer, a typed reply, and the HUD dialog.
  The dialog is the rarest. A typed reply is often free language, such as "it can go".
- In a lead and teammate setup the user answers in the lead's session. The teammate's
  session never sees the answer. Both sessions write one journal.
- The user answers several steps with one reply.

## Terms

- **Gate**: `commit` or `publish`. `publish` covers a push and the creation of an MR/PR.
- **Go**: the user's approval of one gate on one stream.
- **Go request**: the record that the flow put one gate of one stream to the user.
- **Reply**: the user's answer. It is a question answer or a typed prompt.
- **Exact go**: a go that the reply states in a fixed form: the gate word as a question
  answer, a stream name as a selected label, or a typed reply from the word list.
- **Witness**: the record that the user replied to an open go request with a reply that is
  no exact go. Only the recorder writes it.
- **Read go**: a go that the model records after it read a witnessed reply.
- **Recorder**: the part of the harness that writes an exact go or a witness from a reply.
  It is not a model tool call.
- **Command gate**: the check that holds a commit command or a publish command.

## Goals & non-goals

**Goals**

- A go is recorded from each way the user approves, with no extra step for the user.
- A model's commit or publish on a journaled stream is held until the stream holds the go.
  A ready verdict alone opens no commit, no push and no MR/PR creation.
- A go given in one session authorizes the session that works on the stream.
- One reply answers several go requests.
- A go without a real reply of the user after the go request is impossible through a
  normal tool path.
- No forced event stands in for a go.
- The threat model of ADR 0015 stands: a net against a flow that forges the go through its
  tools. It is no defence against deliberate circumvention.

**Non-goals**

- No defence against a direct database write, a copied script, or text injected into the
  terminal on purpose.
- No check that the model read a witnessed reply correctly. The witness and the quoted
  words stay in the journal for an audit.
- No gate for a tag, a merge, an issue comment or an issue close. A project rule can still
  ask for the user's go there.
- No handling of "merged". That reply reports a fact after the publish. #31 owns the
  close-out.
- No change to what the publish question shows. #25 owns that.
- No change to shipgate-hud in this release. Its dialog keeps its meaning.
- No reading of free language by a hook or by the journal.

## Users & stories

- As the user, I answer "Commit" in a question, and the commit runs. I do nothing else.
- As the user, I type `commit` after the flow asked, and the commit runs.
- As the user, I type "it can go" or "commit and start the next batch", and the commit
  runs. I am not asked to confirm.
- As the user, I see a list of five steps from the lead, and I type `all`. Each stream gets
  its go.
- As the user, I find no commit and no push that I did not approve.
- As the user, I can count how many go records came from the model's reading.
- As a teammate session, I read the go from the journal. I do not need the user's words
  relayed to me.
- As a maintainer of an unattended project, I turn the command gate off in one place.

## Functional requirements

**The go request**

- **FR-001** — The flow records a go request before it asks. The request names the stream
  and the gate, and it keeps the question text.
- **FR-002** — A session can record a go request for any live stream, not only for its own.
- **FR-003** — A go request is open until a reply answers it. Only a reply in the session
  that recorded the request answers it.

**The reply**

- **FR-004** — A question answer is a reply. When the question carries the header of a
  gate, the gate word as the answer is an exact go for the open requests at that gate. A
  selected label that names a stream is an exact go for that stream.
- **FR-005** — A typed prompt is a reply. A whole-prompt match against a fixed word list is
  an exact go at once. A gate word is a go for the open requests at that gate. A general
  word such as `all` or `yes` is a go for every open request of the session.
- **FR-006** — One reply answers every open request of its session. Five open requests and
  the reply `all` give five go records.
- **FR-007** — For each open request that a reply does not match, the recorder writes a
  witness. The witness closes the request for every later reply. The recorder then tells
  the flow which witnesses exist.
- **FR-008** — A gate word with no open request is a go for the stream the session drives.
  Any other reply with no open request records nothing.
- **FR-009** — Input that is not the user's own typed prompt is no reply. This covers a
  subagent report, a message from another session, a scheduled task and a relayed text
  inside a wrapper tag. It records nothing, and it closes nothing.

**The read go**

- **FR-028** — The model reads a witnessed reply. When the reply approves the gate, the
  flow records the go with a pointer to the witness and with the user's approving words. It
  asks no confirming question.
- **FR-029** — The journal refuses a read go unless all of these hold: the witness exists
  on the same stream; the recorder wrote it; it answers a request at the same gate; it is
  later than the stream's last `task-done`; no other go names it; the session that records
  the go is the session that got the reply. `--force` does not waive this.
- **FR-030** — A read go carries its own marker. `stats` counts the go records by marker.
- **FR-031** — Only the recorder writes a witness. A model's Bash call that appends a
  witness is refused.

**The record**

- **FR-010** — The recorder writes an exact go as the user's decision, with a marker that
  names the way it came: the question answer or the typed prompt. The dialog and shell
  markers of ADR 0015 keep their meaning.
- **FR-011** — A go lasts until the stream's next `task-done`.
- **FR-012** — A publish go also satisfies the commit gate. A commit go does not satisfy
  the publish gate.
- **FR-013** — A go that a session records for another session's stream does not bind the
  recording session to that stream. Its status brief and its Stop gate do not change.
- **FR-014** — `status --json` and `position --json` print the user's go for each gate of a
  stream, beside its publish authorization.
- **FR-027** — The recorder never stores the text of a prompt. A read go holds the user's
  approving words as the model quotes them, in at most 200 characters.

**The command gate**

- **FR-015** — On a journaled project, a model's `git commit` is held when the branch's
  live stream holds no go for the commit gate. A `git push`, a `gh pr create` and a
  `glab mr create` are held when the stream holds no go for the publish gate. A ready
  verdict is no go.
- **FR-016** — The refusal names the stream, the gate and the ways forward: record a go
  request and ask, let the user type the gate word, or record the read go of a witness that
  waits.
- **FR-017** — A call from a subagent meets the same rule. Its refusal tells the subagent to
  hand the question back to the session that started it.
- **FR-018** — The command gate does nothing on a project with no journal, on a branch with
  no live stream, and on a project that turned the gate off.
- **FR-019** — The command gate is on by default. A project turns it off with one sidecar
  setting. The recorder stays on.

**The journal rules**

- **FR-020** — `mr-opened` keeps its rule: a ready verdict or the user's publish go, after
  the last `task-done`. The new markers count as the user's go.
- **FR-021** — `--force` does not waive the `mr-opened` rule. The refusal no longer offers
  it.
- **FR-033** — A forced ready verdict authorizes no publish: not for `mr-opened`, and not
  in `status --json` or `position --json`.
- **FR-022** — A model's Bash call that records a go as the user's is refused at the commit
  gate as it is at the publish gate. A call that writes any marker other than the read
  marker is refused, as today.

**The flow text**

- **FR-023** — The `review`, `feature`, `implement` and `model-tiers` skills name one
  question form for each gate, the go request that precedes it, and the read go. They no
  longer send the user to the dialog or to `!` as the only paths.
- **FR-024** — Every refusal text names the paths that exist in this release.

**Safety and cost of the hooks**

- **FR-025** — On a project with no journal, each new hook prints nothing, exits 0 and
  creates no file. For a command that is no commit and no publish, the command gate reads no
  file.
- **FR-026** — A crash in a new hook, or a journal that cannot be read, never blocks a
  command and never blocks a prompt.
- **FR-032** — On a journaled project, a prompt costs no journal run when the session has
  no open go request and the prompt is longer than 32 characters.

## Success criteria

- **SC-001** — A recorded probe payload of a question answer "Commit", fed to the recorder,
  gives one go on the stream with the question marker. The command gate refuses
  `git commit` before it and passes it after it.
- **SC-002** — With one open request, the typed prompts `commit`, `Commit.` and `publish`
  each give one go with the prompt marker. The prompts `it can go` and `no` each give one
  witness and no go.
- **SC-003** — Five open go requests and the prompt `all` give five go records in one run.
- **SC-004** — Each of these gives zero records and closes nothing: a subagent report, a
  relayed message inside a wrapper tag, a bash-mode line. The test uses the three shapes
  the probe recorded.
- **SC-005** — Session A records a go for the stream of session B. The command gate in
  session B passes. `status --session A` leads with the same stream as before.
- **SC-006** — `append --type mr-opened --force --force-reason x` on a stream with no ready
  verdict and no publish go exits 4.
- **SC-007** — On a project with no sidecar, the hooks give empty stdout, empty stderr and
  exit 0, and they create no file. The audit-hook test shows that the command gate opens no
  file for `ls -la`.
- **SC-008** — The suite of 0.26.0 passes with no test removed, apart from the tests that
  pin the old refusal texts and the forced `mr-opened`.
- **SC-009** — The model's append of `gate: commit` with `--actor user` is refused. The same
  append with `gate: scope` passes.
- **SC-010** — The changed skill text is judged on both session models in use. In each run
  the flow records a go request and asks with the gate header. After the reply "it can go"
  it records a read go and asks no confirming question.
- **SC-011** — One month after the release, the journals hold 0 forced `mr-opened` events
  (the retro of #37).
- **SC-012** — After the witness of `it can go`, a read go that names it is accepted, and
  the command gate passes `git commit`.
- **SC-013** — Each of these read-go appends exits 4, with `--force` too: no witness; a
  witness that another go already names; a witness on another stream; a witness that is
  older than the last `task-done`; a session other than the one that got the reply.
- **SC-014** — The PreToolUse hook refuses a model's append of a witness.
- **SC-015** — With no open request of the session, a prompt of 33 characters runs no
  journal process. The test counts the calls of a stub journal.
- **SC-016** — After a forced ready verdict, a plain `mr-opened` exits 4, and `publish` in
  `status --json` is `held`.
- **SC-017** — `stats --json` reports the count of go records for each marker.

## Constraints & assumptions

- Hooks run on every user's machine in every project. The no-op path is a correctness
  requirement, and the change takes the full security review.
- shipgate's scripts stay Python 3.9 compatible, with the standard library only.
- The facts below come from the hooks reference and from one interactive probe on Claude
  Code 2.1.329 in auto mode (37 hook records):
  - PostToolUse fires on `AskUserQuestion`. `tool_response.answers` maps the question text
    to the selected label. A multi-select joins the labels with `, `. A free-text answer
    arrives as the typed text in the same place.
  - UserPromptSubmit receives `prompt` and `prompt_id`. No field names the origin. It also
    fires for a subagent report, which arrives inside an `agent-message` tag. It did not
    fire for a bash-mode line.
  - A tool call from a subagent carries `agent_id` and `agent_type`. A main-thread call
    carries neither.
  - A PreToolUse `ask` decision shows the permission dialog in auto mode, even with an allow
    rule for the command.
  - The hook process carries the session id in its environment.
- A probe on a scratch journal of 0.26.0 shows the second bypass: a forced ready verdict
  exits 0, and the plain `mr-opened` after it exits 0.
- A text that another program pastes into the terminal reaches the hook as a prompt. A
  wrapper tag is the only sign. A raw paste of the bare word `commit` is deliberate
  circumvention, and it is out of scope.
- The release is 0.28.0. The ADR has the number 0023.
- The PRD, the ADR and the worklog are committed with the implementation, in one PR.

## Assumptions (executive)

- What is the unit of a go? → one gate on one stream — the journal already holds one stream
  per deliverable.
- Which gates exist? → `commit` and `publish` — the issue names these, and the HUD already
  treats push and MR/PR creation as publish.
- Does a publish go cover a commit? → yes — a publish of uncommitted work has no meaning.
- Where does the question text live? → in the go request — the go record then points at it,
  and the 1 KB cap holds.
- What happens to "merged"? → out of scope — it reports a fact, and #31 owns the close-out.
- Does a subagent get its own rule? → no, the same rule with its own message — a subagent
  cannot ask the user.
- Does a go bind the recording session to the stream? → no — a lead that records a go for
  five streams drives none of them.
- Does this release change shipgate-hud? → no — the HUD reads `publish` from the journal,
  and its dialog still records a go. A follow-up updates its refusal text.
- Do the three hook facts need a probe? → yes, one — the reference does not say whether
  PostToolUse fires on `AskUserQuestion`.
- Does the verdict branch of `mr-opened` go? → no, only a forced verdict stops to authorize
  — the command gate already asks for the go before a model's push, and a PR that the user
  opened by hand on a reviewed stream needs no second approval.
- What bounds a read go in time? → the last `task-done`, the single use of a witness and
  the session — a check against the prompt id of the turn would put policy into the hook.

## Rulings

The user ruled on 2026-11-20. The lead relayed the rulings. The first three are the user's
own choices. The lead presented the others as defaults, and the user did not object.

1. **A ready verdict and a model's push** — the user: "No, always my go". Commit, push and
   MR/PR creation each need a recorded go. A ready verdict alone opens none of them.
2. **A typed reply** — the user: "Word list, else model reads". A whole reply from the
   fixed list is a go at once. The model reads any other reply and records the go with a
   pointer to the witness. No confirming question follows. A go without a real witnessed
   reply after the request stays impossible. A read go carries its own marker, and `stats`
   counts it.
3. **The command gate at upgrade** — the user: "On by default", with the sidecar setting.
4. **The UserPromptSubmit hook** — in. It follows from ruling 2.
5. **With no go the command gate refuses.** It does not show the native permission dialog.
6. **The word list is built in.** The project config adds no words.
7. **`--force` does not open `mr-opened`.**
8. **A go lasts until the next `task-done`.**
9. **A gate word with no open request** is a go for the stream the session drives.
10. **A journal that cannot be read** passes the command.

Two more rulings came during the build, relayed by the lead:

11. **One go covers all** — the user: "One go covers all". One publish go covers the commit,
    the push and the MR/PR creation.
12. **A model's import** — the user: "Hook refuses a model's import". The PreToolUse hook
    refuses any `journal.py import` a model runs (ADR 0023 §20).
13. **A model's run of the recorder** — the user: "Hook refuses running the script". The
    PreToolUse hook refuses a command that runs `hooks/reply.py` (ADR 0023 §21).

Two points came from the lead:

- The per-prompt cost stays near zero when no request is open (FR-032).
- A forced ready verdict must not authorize a publish (FR-033).
