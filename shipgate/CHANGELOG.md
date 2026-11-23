# Changelog

All notable changes to the **shipgate** plugin, newest first.

v0.30.2 — three follow-ups: an index sync has its own 90 s timeout, a slug that starts with an issue id names a worklog too, and `feature` tells a teammate to record its lead.

**A catch-up sync of the code graph never finished (#19).** `codegraph sync` ran under the
30 s limit of a query. After many changes, for example a branch switch or a rebase, a sync
took 20 s on a repository of about 850 files and 36 s on one of about 1,900. The limit
killed it, its work was lost, and the next run started the same catch-up. So the repository
stayed on the regex scanner.
- The sync now runs under `SYNC_TIMEOUT`, 90 s. A query keeps 30 s, and a build 120 s.
  The sync limit stays under the Bash tool's default of 120 s, which caps the whole
  `signals.py` call, so a slow sync still ends in the regex fallback.
- A sync that times out gives the reason `graph-sync-timeout`, not `graph-timeout`, so a
  slow catch-up reads apart from a hung query. Its note says to run `codegraph sync` once by
  hand. `SHIPGATE_CODEGRAPH_TIMEOUT` still sets one timeout for every call, the sync
  included.

**A slug with an issue id named no worklog (#43, ADR 0020 amendment).** The slug of
`fix/1290-date-off-by-one` is `1290-date-off-by-one`, and it does not name
`date-off-by-one.worklog.md`. Until an event named the worklog, `position` showed none and the
Stop gate skipped its ticks as `no-stream`.
- When the slug starts with an issue id of ASCII digits and a dash, the slug without that id
  names a worklog too. `position` reads it only when the full slug leaves no free worklog.
- The most exact binding still wins. Among names, `<slug>.worklog.md` beats a prefix match,
  the longer slug beats the shorter, and the full slug beats the slug without its issue id.
  So `feat/demo` keeps `demo.worklog.md` when `fix/1290-demo` is live too.
- This widens what the Stop gate can block. No file under `hooks/` changed: the hook runs
  `journal.py check`, and `check` and `position` share the new rule.

**A teammate's stream did not record its lead (#45).** `flow-started` and `deviation` take
`report_to` since 0.27.0, and `handoff` prints it, but no skill said to write it. The
`feature` skill now says it: a session that a lead's brief started puts the lead and the
command to reach it in `flow-started`'s `report_to`. After a `/clear`, `handoff` still prints
`report to` with that lead.

v0.30.1 — `journal.py` is an entry point over the package `scripts/_journal/`: the code moved, unedited, into 22 modules, and a journal run starts about 34 ms faster where Python caches bytecode.

**One file of 7,826 lines held the whole journal (#61, ADR 0027).** A session that read it
spent tens of thousands of tokens. Every branch rebased over it, and a reviewer could not
scope a change to one concern. Python also compiled all of it at every start, because it
never caches the bytecode of a script it runs as `__main__`. Refs #48.

- **22 modules in a fixed layer order.** Each module owns one concern, for example `store`,
  `fold`, `reply`, `position` or `cli`, and imports only the modules above it, so there is
  no import cycle. ADR 0027 lists the modules and what each owns. Every top-level statement
  moved with its text unchanged. The only edited lines are the four that read `__file__`.
  Three gained one `.parent`. The fourth now names `journal.py` beside the package, so the
  printed path of `journal.py` is the same.
- **`journal.py` keeps its path, its commands, its options, its exit codes and every output
  byte.** It loads the package by path under a name of its own, so it runs under `-I`,
  `-P` and `PYTHONSAFEPATH`, and two copies of the plugin in one process each print their
  own path. A copy that lacks `_journal/` exits 1 with `error: cannot load <dir> (shipgate
  install incomplete): …`. No file under `hooks/` changed, and the hook contract is the
  same.
- **The start, median of 20 runs** (Python 3.15.2, a warm bytecode cache): `journal.py
  vocab` 107.1 → 72.7 ms; the recorder with an open request, which runs the journal twice,
  268.1 → 195.4 ms against its 200 ms budget; the command gate holding a `git commit` 173.5
  → 137.9 ms. The recorder and the gate with no journal run change by less than 1 ms.
- **The cost without a bytecode cache.** Where Python cannot write bytecode (a read-only
  install, or `PYTHONDONTWRITEBYTECODE=1`), it compiles 23 files instead of one, and a
  journal run takes about 5 ms more than before (`vocab` 108.1 → 113.1 ms). Set
  `PYTHONPYCACHEPREFIX` to a writable directory to get the cache back. The plugin cache
  that Claude Code writes is writable, so a default install gets the cache.
- `test_journal.py` is split along the same lines into nine files, and
  `test_journal_layout.py` checks the layer order of the package.

v0.30.0 — a smaller status brief and the close-out of a merged stream: the brief prints the bound streams and one count line, `journal.py closeout` plans the close-out from forge and git evidence, and `journal.py sweep` proposes an end for each dormant stream.

**The brief cost about 7,400 characters at every session start (#31, ADR 0024).** It
printed every open stream, and a stream stayed open after its PR merged. On a copy of a
production journal (26 open streams: 6 live, 20 dormant; 69 finished), the six live streams
the session did not drive took 72% of it.
- **Plain `status` prints only the bound streams in full**: the one this session drives and
  the one the checkout names. Every other stream goes into one count line, for example
  `not shown: 4 live, 20 dormant, 67 finished — list: journal.py streams --open · close
  dormant: journal.py sweep`. A zero count is left out. On that copy, with the hook's
  header: 7,392 → 266 characters on the integration branch, and 7,714 → 1,372 in a
  worktree that binds the newest live stream. The size no longer grows with the number of
  streams. `--all`, `--feature` and `--json` print what they printed before; `--json` gains
  `last_writer`, `pull_request` and `other_session` per stream.
- **The ownership mark.** A bound stream that another session wrote within 30 minutes
  prints `ownership : another session wrote this 12m ago`. Hook rows and the rows of the
  approval path do not count; the count line says how many of the others carry it.
- **`journal.py streams --open | --dormant [--json]`** lists the streams the brief counts:
  lifecycle, phase, last event, idle days, the PR/MR URL and the ownership mark.
- `feature` runs `streams --open` before it opens a new stream or says nothing is in flight
  when no stream is bound, then `handoff` for the one to resume.
- After `mr-opened`, the bound block and `handoff` print `close-out : after the merge, run
  journal.py closeout --stream=<s>`.
- The recorder's line after a partial write now prints `status --all`, because plain
  `status` no longer shows an unbound stream.

**After a merge, nothing in the plugin acted (#31, ADR 0025, ADR 0026).** A lead closed each
stream by hand: tag the release, update `main`, tick the tracking issue, append
`flow-completed`, remove the worktree, delete the branch.
- **`journal.py closeout --stream <s>`** prints an observe script; the flow runs it, and it
  writes the forge's PR/MR state (`gh` or `glab`), the integration branch git names
  (`origin/HEAD`), the refs, the refs merged into it, its first-parent line, `git worktree
  list` and the stream worktree's `git status --porcelain --ignored
  --untracked-files=normal` into a fresh directory. The rerun with `--observed <dir>`
  decides from that evidence: the forge first, git ancestry as the fallback; the user's word
  is never evidence. A stream with no PR/MR on a forge that answered is never merged. With
  no forge evidence, git calls a branch merged only when a merge commit took its tip off the
  integration branch's first-parent line, so a branch cut from it with no commit of its own
  never reads as merged. The close-out acts only on the branch named exactly as the stream,
  and on the recorded PR/MR or one whose head is the stream; any other stream exits 4 and
  names `journal.py sweep`. A PR/MR that did not merge exits 4 with no step. A merged one
  gets the steps in order, each `[run]`, `[ask]` or `[skip]` (done already, so a rerun
  resumes): capture, `flow-completed` with its evidence, the update of the integration
  branch on a clean tree, the project's own steps, the report, and last, in one Bash call,
  the worktree removal and `git branch -d`. `journal.py` still runs no subprocess.
- **The built-in local steps run with no question; the project's own steps wait for one.**
  So does the worktree removal when the worktree holds an ignored or untracked path, or its
  files were not observed: git deletes ignored files with the worktree, so the step lists
  the count and the first paths, and an unchosen removal keeps the worktree and its branch.
  The flow asks one `AskUserQuestion` with the header `Close-out`, each option with its
  command beside its label, records the answer as the user's `gate-decision` at gate
  `close-out`, and runs only the chosen steps. No step takes `--force`, `-f` or `-D`; a step
  git refuses stops.
- **A squash-merged branch.** `git branch -d` refuses it, so its deletion is an `[ask]`
  step: `git update-ref -d refs/heads/<b> <oid>`, guarded by the commit the forge merged.
  It runs in the last Bash call after the worktree removal, because git refuses to remove a
  worktree whose branch ref is gone (ADR 0026 amendment).
- **A new optional config section, `## Close-out`**, declares the project's own post-merge
  steps: `- <Label>: <action>`. Each one is an arbitrary command, so each waits for the
  one close-out question. This repo's config names the tag and the tick in the tracking
  issue.
- **`journal.py sweep`** proposes `flow-completed` (merged), `flow-abandoned` (closed
  unmerged), `unknown` or keep for each dormant stream, from one forge list query, each
  with its source. It guesses nothing: it reads the branch and the PR/MR head of the
  stream's exact name, and the recorded PR/MR. With none of them the proposal is
  `unknown`, the user decides, and the line shows what the sweep looked for. `sweep
  --observed <dir> --apply` appends the terminal ones after one confirmation, appends
  nothing for `unknown` or keep, and skips and names a stream that moved after the evidence
  was observed.
- `flow-completed` and `flow-abandoned` take optional `reason`, `evidence` and `url`.
- `feature` routes the user's "merged" and a watcher's `merged` event to a new
  **Close-out** section; `review` and `knowledge-base` point at it. No hook reads the word.
- No hook file and no hook contract changes.

v0.29.0 — the security review sees the change: a briefed reviewer reads the working tree before the commit, the built-in `/security-review` runs on the commit before the push, and the verdict names the review and the files it read.

**The built-in `/security-review` reviewed an empty diff (#40).** `feature` and `review`
fire the built-in command for a change in a security-sensitive area. Review runs before the
commit, and the command takes its diff from the branch's commits against `origin/HEAD`. So
its diff was empty, and it reported no finding on no code. In four flows the capture was
empty each time. Each flow then briefed one reviewer on the working tree, and reran the
command on the commit; twice that rerun found something the briefed reviewer had not.
- `review` has a new **The security review** section. Before the commit, one reviewer gets
  the command's criteria and reads `git diff <base>` plus each untracked file in full. The
  pass leaves the index and the other worktrees as they are: no `git add -N`, no detached
  worktree, no commit for the review. The orchestrator checks that the reviewer read every
  changed file that still exists. After the commit and before the push, the built-in
  command runs on the commit. A finding there is a `not-ready` verdict and a fix round; the
  fix lands as a new commit, and the command runs again on it before the push.
- `review-verdict` takes an optional `security_review` object: `kind` (`builtin`, `briefed`
  or `none`), `files` (the number of files it read) and `ref` (the commit the command
  read). `append` refuses `builtin` or `briefed` with no file read, and `builtin` with no
  `ref`, even with `--force`. The built-in run on the commit is a second verdict that
  copies the first one's `criteria`, `dispositions` and `ranking`; it counts as a review
  round. Rows written before this release stay valid.
- **The publish gate reads the newest verdict.** `mr-opened`, `status --json` and
  `position` took the first ready `review-verdict` after the last `task-done`. So a
  `not-ready` verdict from the built-in run on the commit left the earlier ready verdict
  authorizing the publish, and the HUD showed publishing as allowed. Now the newest verdict
  after the last `task-done` decides: a later `not-ready` holds publishing until a newer
  ready verdict. A forced ready verdict is still skipped (ADR 0023 §17), so it neither
  authorizes nor takes back an earlier ready one. The user's publish go is unchanged: a go
  on record after the last `task-done` still authorizes, so `review` now asks the publish
  go only after the built-in run on the commit.
- `verify` lists a review or scan whose input was empty as one more way a report lies.
  `feature` points at the two passes.
- No hook or hook contract changes: nothing holds a push until the built-in run is on
  record. The publish gate change is in `journal.py` only.

v0.28.2 — the command gate's refusal prints the full go-request command, so a session with no skill loaded can follow it.

**A refusal named no journal command (#55, ADR 0023 amendment A7).** The release check of
0.28.1 ran four times. In one run the model had loaded no skill. The command gate held its
commit and said to record a `go-requested`, but named no script. The model searched the
disk, found an older cached copy of the plugin, and that copy's `append` refused the event
type. 0.28.0 and 0.28.1 have no tag; 0.28.2 is the release.

- **The hold prints the command.** The command gate's `no-go` hold now prints one command
  that runs as it stands: `python3`, the absolute quoted path of the `journal.py` that
  answered, `--db`, `append --stream=<stream> --type go-requested` and a payload with the
  gate and a placeholder question. `authorize --json` carries it as `request_command`.
- **The other texts that ask for a go request print it too.** The `mr-opened` refusal
  (publish gate), the refusal of 0.28.0's read go (its gate), and the recorder's line when
  it could write none of the user's reply. The recorder's line for a partial write prints
  the full `status` command. The `witness-waits` hold and the recorder's witness line
  already printed the command and are unchanged. A refusal on a stream with no events or
  a finished one prints no command, because `append` refuses a go request there.
- **The forgery net's text.** The PreToolUse refusal of a forged go reads no branch and
  runs no journal, so it prints no command. It now says that the command gate's hold and
  the recorder's line print the `go-requested` command, and it names the hook's own
  plugin journal script.
- Nothing that the gate or the net refuses or allows has changed.

v0.28.1 — a free-language approval gets one confirming question, and the hook records the click: the model-read go of 0.28.0 is removed, and the refusal of a command that names the recorder script points to the Write tool.

**Auto mode refused the read go (#52, ADR 0023 amended).** The two-turn check of SC-010 ran
after the merge of 0.28.0 and before any tag, on both session models. Both runs recorded the
go request, asked with the header `Commit` and got the recorder's witness of "it can go".
Then Claude Code's auto permission mode refused the model's `append` of the read go as the
model recording its own approval, so the go was never written and the commit stayed held.
0.28.0 has no tag; 0.28.1 is the release.

- **One confirming question.** An exact word from the list stays a go at once. After any
  other reply the recorder still writes a witness, and its context line now tells the model
  to record a new `go-requested` (the line prints the command) and ask one confirming
  question with the header `Commit` or `Publish` and the gate word as the first option. The
  recorder records the click as a go with the marker `question`. When the answer to the
  confirming question is no go either, the flow records nothing and asks no more. The line
  reaches the model on a typed prompt and on a free-text answer to the gate question.
- **The `read` marker is retired.** `append` refuses a `gate-decision` whose `source` folds
  to `read`, with `--force` too, and the refusal names the confirming question. The
  PreToolUse hook refuses every `source` marker in a model's append; the read go no longer
  passes. `gate-decision` loses the keys `witness` and `words`, and `stats` counts four
  markers.
- **Old rows.** A read go that 0.28.0 wrote stays in the journal, and the journal opens. It
  is no go for any gate, `stats` does not count it, and it still binds no session. A go
  lasts only until the next `task-done`, so the worst case is one held commit and one
  confirming question.
- **The hold.** When the user's reply was no exact go, the command gate's hold (reason
  `witness-waits`) asks for a new go request and one confirming question.
- **A note that names the recorder stays refused (ADR 0023 §21, amendment A6).** The hook
  refuses a command that writes a note naming `hooks/reply.py` and also runs `python3`
  through a variable path, as 0.28.0 does. Its refusal now says to write such a file with
  the Write tool. An exemption for the note was tried and rejected: four review rounds each
  found a bypass that 0.28.0 refuses. The recorder rule of the hook is the rule of 0.28.0.
- **The flow text.** `review` (**The user's go**) and `feature` describe the confirming
  question. The two-turn driver's pass is now: go request, the gate question, the reply,
  one confirming question with the header `Commit`, a click on `Commit`, a `question` go and
  the commit.

v0.28.0 — the user's go is recorded where the user answers, and a commit waits for it: a recorder hook writes the go from a question answer or a typed reply, a command gate holds a model's commit, push and MR/PR creation, and no forced event opens a publish.

**The approval checked nothing (#22, ADR 0023).** Since 0.23.0 the user approved a publish
in the shipgate-hud dialog or with a `!` command. Seven journals held 3 dialog approvals and
0 shell approvals. The flow asked 152 commit or publish questions through `AskUserQuestion`,
the PreToolUse hook refused 21 appends that tried to record such an answer, and 13
`mr-opened` events were forced. A commit had no gate: 6 of 40 user interrupts came while the
agent announced a commit, an amend or a push.

- **The go.** A go is the user's approval of one gate (`commit` or `publish`) on one stream:
  a `gate-decision` with `decision` equal to the gate, `raised_by: user` and a `source`
  marker. A publish go also satisfies the commit gate, and one publish go covers the push,
  the MR/PR creation and the commit. A go lasts until the stream's next `task-done`. The
  markers are `question` and `prompt` (the recorder), `read` (the model, from a witness),
  and `dialog` and `shell` as before.
- **The go request.** A new event, `go-requested {gate, question}`, records that the flow
  put a gate of a live stream to the user. `append` refuses it on a missing or finished
  stream, with `--force` too, and leaves an empty marker file for the session at
  `<journal db>.requests/<session id>`.
- **The recorder** (`hooks/reply.py`, new) runs on UserPromptSubmit and on PostToolUse for
  `AskUserQuestion`. `journal.py reply` (new) plans the rows; the hook writes them with
  `append --batch`. An exact go: the gate word as the answer to a question with the header
  `Commit` or `Publish`, a stream name selected in a multi-select, or a typed reply from a
  built-in list (`commit`; `publish`, `push`; `all`, `yes`, `y`, `ok`, `go`, `approve`),
  case and one closing `.` or `!` ignored. Any other reply to an open request leaves a
  `reply-witnessed` row, which holds no text. A reply answers every open request of its
  own session. A prompt that starts with a tag (a subagent report, a relayed message)
  is no reply. A gate word with no open request is a go for the stream the session drives.
  With no marker file, a prompt over 32 characters runs no journal.
- **The read go.** After a witness, the model reads the reply and, when it approves,
  appends a `gate-decision` with `source: read`, `witness: <seq>` and the user's `words`
  (at most 200 characters). It asks no confirming question. `append` accepts it only with
  a witness of the same stream, gate and session, written by the hook, newer than the last
  `task-done` and named by no other go. `--force` does not waive this.
- **The command gate.** The PreToolUse hook holds a model's `git commit` until the stream of
  the branch holds a commit go, and `git push`, `git subtree push`, `gh pr create` and
  `glab mr create` until it holds a publish go. It reads the branch of the command's
  directory (git's `-C`, a `cd` in the line, the cwd) and asks `journal.py authorize`
  (new). A ready verdict is no go. A subagent is told to hand the question back. The gate
  does nothing on a project with no sidecar, on a branch with no stream or a finished
  one, or with `enforce.command_gate: false` in the sidecar. A dry run is held like any
  commit or push. A failure of git or the journal passes the command.
- **The forgery net grows.** The PreToolUse hook now also refuses a model's append of a
  user decision at the commit gate, any append of a `reply-witnessed` row, an append
  whose `--type` it cannot read, any `journal.py import` (ADR 0023 §20): `import`
  writes rows with no check, so a model could write the user's go with it, a journal
  write whose line sets or clears `CLAUDE_CODE_SESSION_ID`, and a command that runs the
  recorder script `hooks/reply.py` (ADR 0023 §21), which would write the go from a forged
  payload. A read go passes the hook unless its actor is `user`.
- **These rows bind no session.** A go request, a witness and a go with the marker
  `question`, `prompt` or `read` do not move the session's position, its Stop gate or its
  `stats` sessions. A go request or a read go whose actor label names another session than
  the appending one is refused, and so is one that carries a label at all when
  `CLAUDE_CODE_SESSION_ID` is empty.
- **`status --json` and `position --json`** gain `go: {commit, publish}`, the user's go per
  gate in the shape of `publish`. **`stats --json`** counts the go records by marker.
- `setup` writes `enforce.command_gate: true`. The config template and the glossary name
  the knob and the new terms.

**Breaking.**
- `--force` no longer waives the `mr-opened` rule, and the refusal no longer offers it.
- A forced `review-verdict` with `verdict: ready` no longer authorizes a publish, in
  `mr-opened`, `status --json` or `position --json`. A caller that forced either event to
  publish now meets a refusal.
- A project with a running flow meets the command gate at upgrade: its next commit needs a
  go. An unattended project turns the gate off with `enforce.command_gate: false`.
- A model's `journal.py import` is refused. The user runs an import with `!` when moving a
  journal between machines.
- A model's command that runs `hooks/reply.py` is refused.

**Cost.** Measured over 20 runs per case: the recorder off a journaled project, median
29 ms; on a journaled project with no open request and a long prompt, 39 ms; with an open
request (a `reply` run and a one-row write), 252 ms, above the budget of 200 ms, which the
user accepted; the command gate on a held commit, 168 ms. A follow-up starts the journal as
a cached module from every hook.

**Known limits** (ADR 0023): a commit that another command makes (`git merge`, an alias, a
script) is not held; a push is judged against the branch of its directory, not its refspec;
a program that pastes a bare word into the terminal forges a reply; the model's reading of a
free-language reply is audited after the fact, not prevented. A line with a `cd` asks for
the cwd's branch as well, so `cd other-repo && git commit` from a stream's checkout needs
that stream's go too.

Tests: the go rule, the read-go check with each refusal and `--force`, the reply plan
(each word, five requests and `all`, another session's request, no request, a witnessed
request, no prompt text in any output), `authorize` as a table, the marker file, `stats`,
the forgery net (commit gate, witness, read go), `gated_commands` as a table, the command
gate per command with its knob, failure policy and no-file-read path, the recorder against
a real journal with synthetic payloads in the probe's shapes, and three end-to-end runs. The
security review's findings on the working-tree diff are fixed or listed in the worklog.

v0.27.1 — an append from a shell with no session id records no session, so it no longer binds another session to its stream.

**An append borrowed the id of the session that started last (#46, ADR 0005 amended).**
`append` took the session from `CLAUDE_CODE_SESSION_ID`, else from `meta.current_session`.
That key is one row per journal, and every SessionStart hook overwrites it, on `/clear` and
on a compaction too. So with two sessions on one journal, a shell with no variable labelled
its row with the other session's id. That session's next status brief then led with a
stream it never worked on, and its Stop gate could block on the row. In a scratch journal,
sessions A and B started in that order: A's sessionless `gate-decision` got the actor
`orchestrator@B`, a sessionless `user` row got `recorded_by` B, and `status --session B` put
B on A's stream. The fallback came in with ADR 0003 (046c758); ADR 0005 (36dcec1) made it
bind a stream.
- `append` reads the session from `CLAUDE_CODE_SESSION_ID` only. A blank variable is none.
  With none, a machine role stays bare (`orchestrator`, `worker`) and a `user` row gets no
  `recorded_by`; the implied `phase-entered` and the automatic `deviation` follow. The row
  binds no stream, and `status --session`, `check` and `stats` count it for no session. The
  append is not refused.
- Which shells have no variable, probed on Claude Code 2.1.329: a mod's `$.process.run`
  child (shipgate-hud's "Approve publishing" append ran there), a client older than
  2.1.132, and a shell outside Claude Code. A mod's child that inherits a parent session's
  id, in a session started from that session's shell, carries the wrong id instead; the HUD
  now sets its own. The Bash tool, nested and background shells, subagents, hooks and `!`
  lines all carry the session's own id. ADR 0005's amendment holds the table.
- `meta.current_session` stays: the SessionStart hook writes it and `session --get` prints
  it, as a diagnostic of the session that started last. No append reads it. A later release
  retires it.
- Rows written before this release keep their labels. No event repairs them: nothing marks
  a borrowed label, and a session's binding moves back at its next own append.
- shipgate-hud 0.11.1 passes its session id to the approval append, so a dialog approval
  still records the session that approved. An older HUD's approval now records no session,
  or a parent session's id when the HUD's session was started from that session's shell.
- No hook, schema or output shape changes.

v0.27.0 — hand off to a fresh session at a phase gate: `journal.py handoff` prints the brief, `design` and `review` recommend `/clear`, and a hook says when the context is past a threshold.

**Phases share one session (#23, ADRs 0021 and 0022).** A flow usually ran clarify, design,
implement and review in one session. Session cost tracks the maximum context size
(Spearman 0.97). 22 sessions that ran three or more phases carried about 41% of the cost,
at a median maximum context of 702k tokens. Only 6 of 36 streams moved to a new session
between `design-committed` and the first `task-done`. When a session did move, the agent
wrote the brief from its memory of the conversation.

- **`journal.py handoff --stream S`** prints the brief a fresh session continues from: its
  role, the request, the phase and the next one, where to report, the artifacts in reading
  order (PRD, worklog, ADRs), the next Build Plan task, the open gates, the last five gate
  decisions, and the rules that still bind. The open gates are an ADR still `proposed`, a
  `not-ready` verdict, findings still `fixing`, ticked tasks with no `task-done`, a failed
  verify, and the publish gate. An ADR counts as open unless its status (front matter, a
  `Status:` line or a `## Status` heading) says accepted, superseded, rejected or
  deprecated. The rules are the config's **Autonomy** and **Security-sensitive areas**
  sections through the config layers (the repo's files, then the umbrella's, then the user
  file), a line that the repo's
  `CLAUDE.md` files stay binding, and the rule to commit only when the user asks. The
  brief comes from the journal, the files its events name and the config, never from the
  session, so the new session builds the same one. It is at most 60 lines on a typical
  stream. A zero-context `claude -p` run on Sonnet, given only a fixture brief, named the
  next task, the first file, a binding rule, the report target and what not to do yet.
- **Where to report.** `flow-started` and `deviation` take an optional string
  `report_to`. The brief prints the newest one, else "the user". A teammate that a lead
  dispatched records the lead here.
- **The skills hand off.** `design` (new Step 5) prints the brief once `design-committed`
  lands and recommends `/clear`, then `/shipgate`. `review` does the same before a fix
  round when the session also ran design or implement, or when the nudge fired. `feature`
  runs `handoff` when a fresh session finds the stream in implement or later.

**Changed behaviour: the PostToolUse hook can print a line (ADR 0022).** After a Bash call
that appended `design-committed`, or a `review-verdict` that is `not-ready`, the hook reads
the session's context size from the tail of its transcript. Past the threshold it prints
one line, as a `systemMessage` for the user and as context for the model, that recommends
a fresh session from `journal.py handoff`. A `ready` verdict does not fire it. The hook
reads the append's own output, with the row's `seq`, and `journal.py nudge` checks that the
seq is the stream's newest event of that type. So a refused append and a quoted old append
line say nothing. The line is advice: the hook never blocks.

- **The threshold** is the config's new **Session** section, `- Handoff: <tokens | off>`:
  `500k` by default, `off` to turn it off. It is usually personal, so the user file can set
  it once for every project. `journal.py nudge` reads it through the config layers, from
  the session's directory up, and decides; the hook only measures (hooks hold no policy).
- **What the hook reads.** The last 256 KB of `transcript_path`, and the last 4 MB only
  when a large record follows the last usage. The path must be absolute and the file a
  regular file, opened non-blocking. Context tokens are the input, cache-creation and
  cache-read tokens of the last main-thread assistant record; sidechain and synthetic
  records are skipped.
- **Cost.** Any other Bash call pays two substring checks on its stdout: 1.6 µs on 2 KB, 89
  µs on 200 KB. The nudge's code sits in `hooks/_nudge.py` and is imported only after a
  match, so the hook process costs what it did in 0.26.0. A boundary call takes about
  234 ms, two to four times per flow.
- `_config.section_lines` reads a config section as written, so a section of prose
  bullets (Security-sensitive areas) is quoted whole. It and `section_bullets` share one
  walk over the section (`_walk_section`), so both read fences alike. `section_bullets`
  reads every config the same as before.
- `setup` offers the Session section's Handoff threshold for the user file, beside the
  other personal answers.

Tests: `handoff` against each brief item, the 60-line cap, two identical runs, a payload
that tries to add lines and unsafe refs; `nudge` against the default, the Session section,
`off`, the user file, a ready and a not-ready verdict and a stream without the event; the
hook against both append output forms, below the threshold, other Bash calls, sidechain and
synthetic records, a usage record behind a large tail, a FIFO, a directory, a relative or
missing transcript, a malformed payload and an unjournaled project; the skill text.

v0.26.0 — the Stop gate can block: it finds a worklog's stream the way `position` does, a waiver clears a finding, and `doctor` shows the last check.

**The Stop gate never blocked (#21, ADR 0020).** The Stop hook runs `journal.py check`, which
should block a session that ticked Build Plan boxes and recorded no `task-done`. In real use
it never did: 0 `gate-blocked` rows in 9,449 events of seven journals, across 3,171 hook
runs. `check` looked for the flow on a stream named `feature/<worklog file name>`. Since
v0.11 a stream is named for its branch, so the lookup never matched and the rule skipped
with no finding. The hook tests used the one stream name that works.

**Changed behaviour: a session can now be blocked at Stop.** After the update, a session
that writes a worklog is blocked while a ticked box of that worklog has no `task-done` on
the stream that owns it. This includes boxes ticked in earlier sessions. The exits are the
`task-done` rows, or one waiver (below).

- **One binding for the gate and the HUD.** A stream owns a worklog when its events name it:
  the last worklog ref of `design-committed`, `design-queued`, `task-done`, `verify-run`,
  `review-verdict` and `gate-decision`, as `position` reads them. A stream with no worklog
  ref owns the worklog its slug names, the one `position` shows for it. The stream name
  `feature/<worklog file name>` still binds, for a journal from before v0.11. The most
  exact binding wins: an event ref beats a name, even from a finished stream, and
  `<slug>.worklog.md` beats a prefix match. So a parent stream does not take a child's
  worklog.
- **No block without an owner.** A worklog that no stream owns is not judged, and neither
  is one that only a finished stream owns. `check --json` lists each under `skipped` with
  its reason: `no-stream`, `finished` or `not-found`. The text output prints the same. A
  rule that cannot fire is now visible.
- **A waiver clears a finding.** A `deviation` with `kind: gate-waived`, `task_ids` and a
  reason in `note`, on the owning stream, clears those task ids. `check --json` carries
  `waivers`: one command per stream. The block text prints it. The command holds a
  placeholder note. `append` refuses a waiver with no task ids, with an empty note or
  with a `<...>` placeholder note, with `--force` too, and `check` reads such a waiver
  as none. Before, the block text said to record a `deviation`, `check` read none, and
  the same block came back on the next turn. The `deviation` shape gains the list
  `task_ids`.
- **A printed command survives an odd stream name.** The commands use `--stream=<name>`, so
  a name that starts with `-` still runs. A stream name that holds a line break, or
  another character that does not print on one line, gets no command. The block text
  keeps each finding on one line.
- **The forced-`task-done` rule can be cleared.** `append` refuses a `task-done` with no
  passing `verify-run`, so only a forced one reaches this rule. A passing `verify-run`
  that names the task now counts wherever it sits in the stream. Before, only an earlier
  one counted, so the command the finding suggested could not clear it.
- **Retired: the PRD rule.** `check` no longer reports a PRD written in clarify with no
  `gate-decision`. No event names a PRD before `clarify-passed`, so the binding cannot
  reach it, and the old lookup never matched. Nothing in the Stop hook checks
  `gate-decision` now; `clarify` writes it in its own step.
- **`check --record`, and `doctor` shows the gate.** The Stop hook passes `--record`. It
  overwrites one `meta` value with the time, the session, the finding count and the skip
  count. No event row is written per stop. `doctor` prints that value and the last
  `gate-blocked` row, and `doctor --json` carries both under `stop_gate`. Plain `check`
  stays read-only.
- Each finding in `check --json` also carries `stream` and `task_id`.

Tests: end-to-end probes with SessionStart, the capture hook and the Stop hook on streams
named `feat/<slug>` and `fix/<id>-<slug>`: each rule blocks, the suggested events unblock,
a worklog with no owner and a finished stream are skipped and reported, the waiver command
clears the block, and `doctor` reports the last check and the last block.

v0.25.1 — the status brief returns after `/clear` and after a compaction.

**The SessionStart hook runs on every source (#20).** `hooks/core.json` registered the hook
with the matcher `startup|resume|fork`. Claude Code names five sources for the event:
`startup`, `resume`, `clear`, `compact` and `fork`. The matcher is an exact-match list, so
the hook never ran after `/clear` or after a compaction, and the session lost the status
brief exactly when its context was dropped. The matcher is now
`startup|resume|clear|compact|fork`.
- After `/clear` and after an automatic or manual compaction, the session gets the status
  brief and the artifact watch list again. The hook passes on the session id it receives.
  A session that keeps its id still gets the brief led by the stream it drives
  (`· this session`).
- The hook passes the session id to `journal.py session --set` on every source. `append`
  reads that value only when its shell has no `CLAUDE_CODE_SESSION_ID` (ADR 0005). In
  such a shell, an append after a `/clear` that changed the id now carries the new id.
  Before, it kept the id of the cleared session. With two sessions open on one project, a
  `/clear` or a compaction in one of them also moves that stored id to it, as a startup
  or a resume always did. Only a shell without the variable reads the stored id.
- One session can now hold several `session-started` rows, one per source that fired. This
  changes no result: `check` selects a session's rows by their session id, not by their
  position after a `session-started` row, and `stats` counts sessions as a set and skips
  the tool's own stream unless `--stream shipgate` names it.
- The hook's code is unchanged. It runs more often: once more per `/clear` and per
  compaction. A project with no journal still pays nothing on any source.

Tests: one row per source with the brief and the watch list, attribution after `/clear`, a
write made before a compaction still blocks the stop, `stats` equal before and after the
extra rows, the hook silent on every source in a project with no journal, and a wiring test
that pins the matcher to the five documented sources.

v0.25.0 — lean project configs: a user file under the project config, the plugin owns its own rules, and `setup` writes and maintains a lean file.

**The layering rule, and a user-level config (#15, #18, ADR 0018).** A config is now a stack
of files, read nearest first: the repo's `.claude/shipgate.md`, the umbrella's, the user file
at `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`), then the built-in
defaults. The stack resolves **per section**: the nearest file that holds a `##` section with
one value that is not a placeholder supplies the whole section, and sections never merge
line by line. The rule has two homes, the template's header and the README's Configuration
section; every config-reading skill cites it with one shared callout and does not restate
it. The user file uses the project file's section vocabulary; the template marks the
sections that are usually personal.
- `Inherit: none` under a nested config's title (bare or a bullet, backticks optional, any
  case) takes nothing from the umbrella's config. The user file and the defaults still apply.
- `scripts/_config.py` is the one reader, loaded by path from `signals.py`, `journal.py`
  and `lean_config.py` (the `_codegraph.py` precedent). It also holds the one placeholder
  rule: a balanced `<…>` group, or several joined by whitespace with an optional separator
  or `Label:`; `<type>/<slug>`, an autolink and a mention are real values. `signals.py` reads the user file as its last layer and
  resolves `## Code signals` and `## Code tooling` per section. **Changed rule:** a repo
  section that sets only `Window` no longer takes `Fix pattern` from the umbrella's section.
  `config.source` labels a value from the user file `user shipgate.md`; a project or
  umbrella value keeps `shipgate.md`. `config` gains `files` (the files read, in precedence
  order, each with its `role`: `project`, `umbrella`, `user`) and `inherit` (`umbrella` or
  `none`).
- `feature`'s route step says which file each section came from when more than one config
  file was read.

**Built-in worker discipline, and a plugin-owned executive contract (#16).**
- `model-tiers` carries a **Built-in worker discipline** block that every worker brief
  pastes word for word, before the config's Worker guardrails. It holds the three rules it
  had (branch check, no commit and no staging, evidence) and five more: the git index is the
  user's review record (never `git add`, `git reset`, `git stash`, `git restore --staged`,
  `git checkout -- <path>`; leave the index as found; stop and report if it blocks you);
  never `--no-verify`, never kill a running pre-commit hook; never a repo-wide formatter or
  a linter with `--fix`; stop and report when blocked or near a spend or time limit, never
  improvise a different design; comments only for what the code cannot say, decisions go to
  the worklog. The config's Worker guardrails section keeps repo-specific rules only.
- `feature` owns **The executive contract**: what the orchestrator records where, and what it
  escalates (one-way doors, user-visible scope changes, Security-sensitive areas, true
  50/50s, the config's Extra escalations). `clarify`, `design`, `setup` and the glossary
  point at it. The config's Autonomy section is `Mode` and `Extra escalations` only; the
  template drops the contract bullet. A config that still carries it is read as redundant
  text.
- `knowledge-base` carries the promotion defaults: a personal workflow preference goes to
  the harness's built-in memory, everything else is dropped, promoted and dropped entries
  are removed. A config's `Ledger:` line lists project targets only.
- `implement` and `structured-debug` use a context7-style MCP for library docs by default
  when the session has one; the config's Library docs line is an override.

**A lean setup, and `doctor` checks the config against the sidecar (#17, ADR 0019).**
- `setup` writes a lean file: a one-line title, the sections the interview filled,
  `- Key: value` bullets only, the Journal section as `- Database: <path>`, no template
  comments and no prose that explains the plugin. On a machine with no user file it offers
  once to write one with the personal answers, and never copies a user-file section into a
  project file.
- `scripts/lean_config.py <path> [--apply] [--user <path>] [--umbrella <path>]…
  [--drop-equal] [--only-equal] [--json]` strips the boilerplate the template and earlier
  setups wrote: the header paragraphs of both template generations, the
  `<!-- Default when absent … -->` and `<!-- Usually personal … -->` comments, the Journal
  prose, the Code signals, Worker guardrails and Orchestration explanations, the MR watcher
  bullets, the `Executive contract` bullet, and placeholder bullets. It matches whole
  blocks by anchor and removes a block only when every sentence in it is catalogued
  boilerplate (the template's prose in each of its versions, the header `setup` wrote, the
  `Executive contract` bullet in its known wordings); a block with any other sentence stays
  whole and is listed as `mixed` with a hint, so a contract bullet that names
  project-specific escalations is never removed. It prints a unified diff, keeps each
  line's own ending, and writes only with `--apply`, through a temporary file and
  `os.replace`. A block it does not recognise stays; a bullet with a real value is never
  removed. With `--user` it
  reports the sections equal to the user file's; `--drop-equal` removes them, `--only-equal`
  touches nothing else, and `--umbrella` keeps a section an umbrella config also holds
  (dropping it would hand the section to the umbrella). `setup`'s update mode runs it,
  shows each diff and applies on a yes.
- `journal.py doctor` gains a `config` block: the project's `.claude/shipgate.md` `Ledger:`,
  `PRD home:`, `ADR home:` and `Worklog home:` against the sidecar's `ledger` and
  `artifact_homes`, one line per drift (a ledger the config names and the sidecar lacks is
  the common case). `section` says whether the project file holds the section; when
  another layer owns it, nothing is compared. The text form prints `config` and `drift`
  lines. Every existing key is unchanged, and the exit code does not change on drift.
  `setup` update mode fixes the sidecar from the report.
- This repository's own config is the worked example: `lean_config.py` removed its setup
  header, a stale `signals.py` comment and the executive-contract bullet; two hand edits
  dropped a generic Orchestration comment and the built-in promotion targets from the
  `Ledger:` line.

**Tests.** `test_config.py` (the reader), `test_lean_config.py` (the recogniser on the
template filled in, on this repository's earlier config, and on a hand-written config that
comes back byte-identical), the user file at both locations, per-section replacement,
`Inherit: none`, the doctor drift cases, and contract tests that pin the shared config
callout, the discipline block and `feature`'s contract. The test environment points
`CLAUDE_CONFIG_DIR` at an empty directory, so no test reads a real user file.

shipgate-hud does not change: the doctor's new keys are additive and the HUD does not read
`doctor`.

v0.24.0 — the graph reaches a file behind two barrel re-exports, and the grader scores the last call that listed files.

**Re-export edges beside the graph (#7, ADR 0017).** codegraph 1.6.2 records no edge for
`export * from "<spec>"`: in the case 72 index, 12 files hold such a line and none has a
cross-file out edge, and a barrel file holds one `file` node and nothing else. A bare
workspace-package import (`import { x } from "@app/notify"`) gets an edge to the symbol's
file and none to the package entry. So a file reachable only through two barrels was lost.
- On the graph arm, `signals.py` now scans every TypeScript and JavaScript file the graph
  kept, once, and adds two kinds of edge: `file -> target` for each `export * from`,
  `export * as x from`, `export { … } from`, `export type { … } from`, `export type * from`
  and `export type * as x from` whose specifier resolves to a file in the graph (the regex scanner's relative-path rules: extensions,
  `.js` to `.ts`, `index` files); and `file -> entry` for each `import … from "<name>"` or
  `require("<name>")` whose `<name>` is the bare name of a workspace package (the root
  `package.json` `workspaces`, each package's `name`, its entry from `exports["."]`, else
  `main`, else `index`). A subpath import adds nothing: codegraph resolves it.
- Bounds: each file is read once; a file over 1 MiB, a symlink or a special file adds no
  edge; nothing outside the repository is read. The pass lives in `signals.py` beside the
  regex scanner; `_codegraph.py` and the regex arm are unchanged.
- `structure.source` stays `graph`. The `structure.graph` block gains one additive key,
  `reexport_edges`: the number of edges the pass added (`null` on the regex arm). No note
  is printed.
- Offline on case 72 (`signal_grader.py fixture --arm graph`, codegraph 1.6.2):
  `blast.files` precision 1.00 and recall 0.95 (56 of 59) before, 1.00 and 1.00 (59 of 59)
  after. The regex arm stays at 0.03.
- The worklog holds the index evidence and a three-file repro of the missing edge for the
  maintainer to report upstream.

**The grader's last-call rule (ADR 0016).** `signal_grader.py trace` and `results` score the
last `signals.py` call whose result holds a `blast` object with a `files` list. A call
whose `blast.files` is `null` is skipped, and the walk continues to the earlier call. One
live run scored 0.00 because the agent's last call carried no `files` list.

**Tests.** The shim fixture gains a two-hop barrel chain with a workspace: the file behind
both barrels and the barrels themselves reach `blast.files` on the graph arm, the regex
arm is unchanged, a barrel over 1 MiB adds no edge, and every re-export form counts. The
grader: a trailing call with `blast.files: null` is skipped.

v0.23.0 — only the user approves a publish, a `ready` verdict closes every finding in a fix, and a script grades the blast-radius signal.

**The user's publish approval (#1, ADR 0015).** Before this release, `--actor user` and
`raised_by: user` were text the model could write. So a flow could record a publish
decision "by the user" and satisfy `mr-opened` and shipgate-hud's publish gate.
- `gate-decision` takes an optional `source`, one of `dialog` or `shell`. `vocab --shape
  gate-decision` prints it. shipgate-hud's publish dialog writes `dialog`. Your own `!`
  command writes `shell`.
- **Changed rule.** A `gate-decision` authorizes a publish only with `gate: publish`,
  `decision: publish`, `raised_by: user`, an actor of role `user` and a `source` marker.
  `mr-opened`, `status --json` and `position --json` read this one rule, and the HUD reads
  its result.
- **Older journals.** A user publish decision recorded before 0.23.0 has no marker and no
  longer authorizes. The gate asks again: approve in the HUD's dialog, or run the append with
  `!`.
- `mr-opened`'s refusal now sends the model to the user. It no longer suggests recording the
  user's decision.
- **A new PreToolUse hook on Bash** (`hooks/pre_tool_use.py`). It refuses a command that
  appends a `gate-decision` with a `source` marker, at any gate. It also refuses a publish
  `gate-decision` that names the user: `--actor user`, `user@…`, a JSONL `actor` of that
  role, or `raised_by: user`. `gate` and its alias `kind` are compared trimmed and case
  folded. Decisions at other gates pass with every actor.
- The hook lexes the shell line itself. It reads quotes, escapes, `$'…'`, operators,
  heredocs (quoted and unquoted delimiters, `<<-`), here-strings and redirections. It reads
  `--data`, `--data=`, `--batch`, `--type`, `--actor` and their unique abbreviations, as
  argparse does. Stdin can come from a heredoc, a here-string, or a pipe from `echo`,
  `printf` or `cat`. `journal.py` can sit at any path or behind a variable. A literal line
  given to `sh -c`, `bash -c`, `zsh -c` or `eval`, a `$(…)` body and a shell that reads a
  literal script on stdin are lexed again. A table of wrappers (`timeout`, `nice`, `sudo`,
  `env`, `stdbuf`, `nohup`, `time` and others), with the options that take a value, finds
  the program behind them, so `timeout 60 bash <<'EOF'` is read too. A literal word that
  holds `journal.py`, `append` and a word break is lexed again, whatever program takes it
  (`ssh host '…'`). So is such a literal stdin of a program the hook does not know; there
  only a marker or a user claim refuses. The arguments
  of a journal append itself and of a program that only prints or stores text (`git`, `gh`,
  `glab`, `echo`, `printf`, `grep`, `rg`, `jq`, `cat`, `head`, `tail`, `tee`) are not lexed
  again, so a commit message that names an append passes, behind a wrapper too.
- **It fails closed** on a payload it cannot read in full, when the append can be a
  `gate-decision`: a variable, a command substitution, a redirected file, a pipe from
  another command, `xargs`. An unquoted expansion in the append's words (`--stream $S`) can
  split into more options, and a subcommand can come from a variable (`journal.py $SUB`);
  both are refused too, with a message that asks to quote the expansion. A double-quoted
  `"$B"` is one word, and so is `--db="$DB"`. An append whose literal `--type` names another
  type, after any such word, passes. A shell whose script comes from a stdin the hook cannot
  read (a group, a subshell, a file) is refused when the line names `journal.py` and
  `append`.
- **The no-op path.** A tool other than Bash, or a command without the words `journal.py`
  and `append`, prints nothing and exits 0. It reads no file; a test proves it with an
  audit hook. A crash exits 0, except on a command that names `journal.py`, `append` and
  `publish`: that one is refused.
- The refusal says only the user approves a publish: "Approve publishing" in the HUD's
  dialog, or the user's own `!` command with `"source": "shell"`.
- This is a net against a flow that forges approval through its tools. It is no defence
  against deliberate circumvention: a direct SQLite write, `python3 -c`, a copy of the
  script. The README says so, and ADR 0015 lists the known limits.

**A finding key is a location (#14, ADR 0014 amended).** On a production project's journal
(counts only), 5 of 10 streams that used `review-disposition` ended with keys at `fixing`:
37 of about 200 keys. One cause was key drift: `fixing` under `<path>:<line>`, the closure
under a free label such as `F21`.
- **Changed rule.** Every key of `review-disposition.dispositions`,
  `review-disposition.labels` and `review-verdict.dispositions` must be a location
  `<path>:<line|?>`, read as the HUD's `parseLocation` reads it: split at the last `:`, a
  non-empty path after `./` is dropped, a line of ASCII digits or `?`. `append` refuses
  another key and names up to 5 of them. The hint says to put a name in `labels`.
  `--force` does not waive it. `import` does not check old rows again.

**A `ready` verdict closes every finding in a fix (#14, ADR 0014 amended).** The other cause:
a fix round appended `fixing`, and the `ready` verdict carried an empty map.
- **Changed rule.** `append` refuses a `ready` verdict while the fold holds a `fixing` key
  that the verdict's own map does not close. The existing verify check runs first. The
  message lists up to 10 keys and prints the `review-disposition` row that closes them, with
  the round of the events that opened them.
- `--force` overrides it only with `--force-reason`, as the payload cap does.

**Skills.** `review`: the fix round closes every `fixing` key (`fixed`, `rejected` or
`deferred`) before the verdict. "Keep the keys compact" now says to close about 20
findings with `review-disposition` rows before the verdict, because a verdict that closes
them all breaks the 1 KB cap. That line leaves `docs/ledger.md`. The publish section and
`feature`'s epic bullet say the user approves in the HUD dialog or with `!`; the model never
records that decision.

**A signal grader for the evals (#6, ADR 0016).** `evals/signal_grader.py` scores a
`signals.py blast --json` or `hotspots --blast --json` result against a case's
`expected.json`. It prints precision and recall for `blast.files` (truth: importers and
tests) and for `blast.tests`. It reads the result from a run's trace (`trace`, `results`),
or runs `signals.py` in the scaffolded fixture (`fixture --arm graph|regex`). Case 13 gets
an `expected.json`. `run-case.sh` runs the grader after a case that has one, in both arms;
the trace exists only with `--keep-temp`. It adds no grader to the harness score or to
`baseline.json`. Offline, case 72 gives `blast.files` recall 0.95 on the graph arm and
0.03 on the regex arm; case 13 gives 1.00 on both.

**Golden contract.** The publish decision of the `feature/golden-flow` stream carries
`source: dialog`, so `status --json` prints it there. The `dispositions` stream's `ready`
verdict is appended with `--force` and a reason. It keeps the stale `fixing` case the HUD
draws.

**Tests.** The hook: every forged spelling, every opaque payload, the allowed decisions,
the no-op path and the failure policy. The journal: the `source` enum, the publish rule
with and without the marker, actor and `raised_by`, and `status`, `position` and the gate
agreeing. Also location keys in all three maps (with `--force`), the `ready` refusal and
its override. The grader: the metrics, `score`, `trace`, `results` and a regex-arm fixture.

v0.22.0 — a finding keeps its location as its key, release files leave the ranking, and a newer sidecar is named.

**`labels` on `review-disposition` (ADR 0014, amended).** Orchestrators gave findings
invented names as keys. Such a key matched no card and no worklog line, so the HUD showed
no state for it.
- `review-disposition` takes an optional `labels`: a map from a finding key to a short
  name. `append` refuses a value that is not a JSON object. It also refuses an entry that
  is not a string, or that is empty or blank.
- A new shape rule kind, `string_maps`, checks it: the value is a JSON object, and each of
  its values is a non-empty string. `vocab --shape review-disposition` prints it.
- `position --json` adds `label` to each `dispositions` entry. The value is the newest
  label that a `review-disposition` gave that key, or null. A leading `./` is dropped from
  a label key, as from a state key. A later event without a label for the key keeps the
  earlier label. Labels come from `review-disposition` only. A label for a key with no
  state is not printed. No key that 0.21.0 printed is renamed or removed.

**The `review` skill: the key is the location.** A disposition key is the finding's
`<path>:<line|?>`, never an invented label. The skill says why: a free label matches no
card and no worklog line. `labels` carries a human name beside the key. The skill's
`review-disposition` example shows it. Names stay short, because `labels` counts toward
the 1 KB cap. The skill also states the worklog grammar the HUD parses: a `Review round N`
heading, a `Rejected findings` heading inside it, and one list item per finding with its
backticked location and one sentence.

**The review Workflow folds path case (#13).** Two lenses can spell one file in two cases,
such as `Widget.test.ts` and `widget.test.ts`. Before this release they gave two cards.
- `review-workflow.js` adds `pathKey(file)`: the normalized path, lower-cased. The dedupe
  maps, the `fileRisk` map and the risk lookup use it.
- A merge never rewrites `file`, so a card keeps the first finder's spelling.
- A `fileRisk` key that differs from a finding's path in case only now labels that
  finding.

**Release files leave the ranking (ADR 0013, amended).** Every release changes the
changelog and the plugin manifests. So they ranked `top` and pushed product code out of
the ranking.
- `signals.py hotspots` leaves out files that match `DEFAULT_RANKING_EXCLUDES` before
  `ranking` takes its 5 rows. The patterns are `**/CHANGELOG.md`,
  `**/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
- A pattern is read as an `Exclude` glob is, and a leading `**/` is dropped first.
- The table, `files`, `dirs` and `blast` keep every file.
- A new `Ranking exclude:` bullet in `## Code signals` replaces the built-in patterns with
  its backticked globs. It does not add to them. An empty backticked value turns them off.
  A `<placeholder>` counts as absent. No flag sets it.
- `config.ranking_exclude` prints the patterns in force, and `config.source` names where
  they came from. The config template, the README and the `--help` text describe the
  bullet.

**A newer sidecar is named.** A sidecar from a newer shipgate could hold keys this one does
not know, and nothing said so.
- `hooks/_common.py` adds `SIDECAR_VERSION = 1`, `SIDECAR_KEYS` and
  `sidecar_version_note(sidecar)`. `SIDECAR_KEYS` names every key a shipgate reader uses:
  `version`, `db`, `ledger`, `artifact_homes` and `enforce`. The note is one line. It is given only when `version`
  is an integer higher than 1. A boolean, a string or an absent value gives no note.
- The SessionStart hook adds the note to the context it emits, once per session. When
  `status` fails, the hook drops journal.py's copy of the note from the failure detail, so
  the note appears once. The no-sidecar path does no extra work.
- `journal.py` prints the note on stderr, once per run, and keeps working with the keys it
  knows.
- `doctor` reports the sidecar's raw `version` (null when absent) and `stray_keys`: the
  sorted keys outside `SIDECAR_KEYS`. The text form prints both.
- `signals.py` reads no sidecar key, so it has no version check.
- The `setup` skill's sidecar shape names `ledger` as an optional key. Its update mode
  reads both facts from `doctor --json`. It stops on a
  newer version and tells the user to update shipgate. It never rewrites a newer sidecar
  down. It drops stray keys when it regenerates the sidecar, and it names the keys it
  dropped.

**Golden contract.** The second interim `review-disposition` row of the `dispositions`
stream gains `labels`. The regenerated `shipgate-hud/tests/fixtures.journal.ts` carries a
`label` on every folded entry: one name and the rest null. A test checks both.

**Tests.** `labels` is accepted with and without a value, and refused as a non-object, as a
non-string value and as an empty or blank string. `vocab` prints the rule. The fold tests
cover the newest label, the earlier label kept, the `./` drop, null with no label, no
label without a state and no label from a verdict. Other tests cover the stderr note once
for `version` 2 and none for 1, absent, a string or a boolean, and the SessionStart note.
`doctor` tests cover the version and the stray keys. The Workflow tests cover a case pair
merged by summary and by line, and a `fileRisk` key in another case. The signals tests
cover release files out of `ranking` and in `files`, a replacing value, the empty value and
`config.ranking_exclude`.

v0.21.0 — a finding's disposition is recorded when it is decided, and `position` prints the trace.

**`review-disposition` (ADR 0014).** Before this release, `review-verdict.dispositions` was
the only record of a finding's state. The orchestrator wrote it once, at the end of a round.
So mid-round the HUD showed no state, and a finding in a fix looked like one nobody read.
- A new event type, `review-disposition`, takes `dispositions` (a map from
  `<path>:<line|?>` to `fixing`, `fixed`, `rejected` or `deferred`), `round` (a
  non-negative integer) and an optional `note`. `append` refuses another state, a missing
  key and a `round` that is not a non-negative integer (a string, `1.5`, `true`, `-1`).
- `fixing` exists only on this event. `review-verdict.dispositions` keeps its three closed
  states.
- The event implies no phase: it is not in `PHASE_OF_EVENT`. The orchestrator appends
  `fixing` in the fix round, back in `implement`, so an implied `review` would move the
  phase on every dispatch.
- A new shape rule kind, `integers`: a key whose value must be a non-negative JSON
  integer, with a boolean refused. `vocab --shape review-disposition` prints it.

**`position --json` prints the trace, the folded dispositions and more of the verdict.**
Every addition is a new key. No key that 0.20.0 printed is renamed or removed.
- `trace`: `review_ranking` and `design_ranking` are the newest `review-verdict` and
  `design-committed` that carry `ranking`, each as `{seq, at, ranking}` with the ranking
  verbatim, or null. A later event without `ranking` does not hide an earlier one's.
  `signals_missing` lists every `deviation` of kind `signals-missing` as `{seq, at}`, oldest
  first.
- `dispositions`: per finding key, `{state, seq, at}`. The fold reads every
  `review-disposition` and every verdict's `dispositions`, in seq order, and the latest
  event wins per key. A later round's verdict that names only its own findings leaves the
  earlier closures in place, and a later `fixing` still reopens a key. A leading `./` is
  dropped from a key, and a state outside the event's vocabulary is dropped. `{}` when there
  is none.
- `verdict.note` is the verdict's `note` text, or null. `verdict.round` counts the verdicts
  in the vocabulary up to and including the last one, from 1.
- The text form adds a `dispositions` line (the count, and how many are `fixing`) and a
  `trace` line.

**The `review` skill records each disposition.** Step 2 appends `review-disposition` when a
finding is killed or deferred. The fix round appends `fixing` when it dispatches a fix and
the closed state when the re-review confirms it. The verdict's `dispositions` stays the
final word for the round. The skill shows one append and names
`journal.py vocab --shape review-disposition`.

**Golden contract.** The scripted journal gains a `dispositions` stream at its top: two
interim `review-disposition` rows, a passing `verify-run` and a `ready` verdict that closes
one finding. It is also the HUD's verdict-only round: a verdict and no review board. Every
later event's `seq` moves up; no event time moves. The `log` runs are gone: the fixture
`shipgate-hud/tests/fixtures.journal.ts` no longer exports `LOG_GOLDEN`, and a test checks
that the `signals` position's `trace` holds both rankings and the deviation.

**Tests.** `review-disposition` accepts the four states with or without a note, refuses
another state, a missing or non-integer `round`, a non-object map and a non-string note,
and moves no phase. `position` tests cover the newest ranking carrier, the
`signals-missing` deviation, the verdict's note and round, the fold (a verdict closes one
interim `fixing` and leaves the other, a later disposition overrides the verdict, an older
verdict's closure holds until a later event changes it, a round-3 verdict that names only
its own key leaves the round-2 closures in place, `./` is dropped) and every 0.20.0 key.

**For shipgate-hud.** shipgate-hud 0.8.0 reads `trace`, `dispositions`, `verdict.note` and
`verdict.round` from `position` and runs no `log` (HUD ADR 0008, and the HUD ADR 0007
amendment).

v0.20.0 — the style canon and the code graph leave a trace.

**The style skill is recorded and reviewed against (#11, ADR 0012).** A config can name
style skills in its Style section. Before this release, no event said whether the flow
named them, and the review had no lens that held the canon. A reviewer without the canon
treated its rules as taste, so the user found canon violations after a `ready` verdict.
- The `implement` and `review` phase entries carry `style`: the style skills the config
  names, or `[]` when it names none. `append` refuses a `style` that is not a list of
  non-empty strings.
  `implement` and `review` append the entry explicitly, because an entry implied by
  `verify-run` or `review-verdict` carries no `style`.
- The `model-tiers` worker brief has a required ninth item, the **Style** line. It names
  the skills, or says that the config names none. A brief dispatched without it is a
  `deviation` with `kind: style-missing`.
- The review adds a **canon lens** when the config names a style skill: one more
  `code-reviewer` that loads the skills with the `Skill` tool before it reads the diff. It
  scores a finding on whether the code breaks a canon rule, never on taste, and a broken
  rule in changed code is at least MEDIUM. Its findings take dispositions like any other.
  The re-review after fixes carries the canon lens too.
- The review Workflow script accepts the `canon` lens and a new `styleSkills` argument. It
  throws on a `canon` lens without `styleSkills`, and it logs `styleSkills` given without
  the lens. A refuter of a finding the canon lens reported loads the same skills, and "a
  matter of taste" does not count as a refutation.
- The `code-reviewer` agent gets the `Skill` tool and a `canon` row in its lens table.

**The risk ranking travels past route-and-map (#10, ADRs 0011 and 0013).** The code signals
were computed at route-and-map and dropped. Nothing showed whether a `blast` came from the
graph or the regex scanner, and a repository with no graph index got one advisory line per
project and then nothing.
- `signals.py hotspots --json` prints `ranking`: the structure `source` and the top 5 files
  in the JSON's own order, each with its `fix`, `churn` and `fan_in` labels and its path cut
  to the last 3 segments; a second file with the same tail keeps its full path. `files` is
  a list, because the JSON is printed with sorted keys.
  Unavailable signals give `{"source": "none", "unavailable": <reason>}`.
- Every JSON call that wanted the code graph and did not get it carries `graph_note`: one
  line that says why and how to build an index. `off` gets no note. The table output does
  not print it, so a person still sees the advisory once.
- `route-and-map` always records `signals` with `source` set to `graph`, `regex` or `none`,
  and relays `graph_note` in the map. `append` refuses a `signals` block without a valid
  `source`.
- A `route-and-map` entry without `signals` is no longer a silent pass. `append` writes a
  `deviation` with `kind: signals-missing` and `auto: true` after it, in the same
  transaction and under the same actor (ADR 0011). The append prints one more line, and
  `--json` adds `deviation_seq`. `version` is then the stream head, the deviation's version,
  so a batch or `--expect` chain moves by one more.
- `design` ranks the files its build plan changes and copies `ranking` into
  `design-committed`. `review` opens every reviewer brief with the ranking's files in risk
  order and copies `ranking` into `review-verdict`. To fit the 1 KB cap, the verdict drops
  `findings` counts first, then cuts `ranking.files` to 3, and never drops `ranking`.

**`stats` reports the trace.** Each stream row gains `trace` and `deviation_kinds`:
- `trace.style.implement` and `trace.style.review`: `named`, `none` (an empty list),
  `missing` (the phase was entered and no event said), or null (never entered). The review
  reads its phase entries and its verdicts.
- `trace.graph.route`, `.design` and `.review`: the source of the last route-and-map entry,
  `design-committed` or `review-verdict` that carries `signals` or `ranking`; `missing` when
  none of them carries one; null when there is no such event. A fix-round verdict without
  `ranking` does not hide the first round.
- `deviation_kinds` counts deviations by `kind`; a deviation without one counts as `-`.
- The totals count streams per state, and the text report adds a section: one line per
  stream, then "graph fed design: N of M designed streams", the same for route-and-map and
  review, and the style counts.

**Payload rules.** Three new shape rule kinds: `objects` (a JSON object that passes a
sub-shape), `list_objects` (a list whose items pass it) and `string_lists` (a list of
non-empty strings). `vocab --shape` prints them for `phase-entered` (`style`, `signals` with
`source`, `unavailable` and the umbrella's `repos`), `design-committed` (`ranking`),
`review-verdict` (`style`, `ranking`) and `deviation` (`kind`). An enum refusal now shows a
null value as `null` and a non-string value as JSON. All keys are new and optional, except that a
`signals` or `ranking` block, once present, must name its `source`.

**Evals.** Case 74 reviews a diff with two canon violations under a config whose Style
section names a project skill; it passes when the review names both before its verdict.
Case 75 reviews a journaled change on the graph arm; it passes when the verdict carries a
`ranking` with `source: graph` and the hot file first. Neither case has been run yet, and
neither has a baseline row.

**For shipgate-hud.** `status` and `position` do not change. shipgate-hud 0.7.0 draws the
review and design rankings, the canon tag and the `signals-missing` line, read from
`log --stream <s> --json` (HUD ADR 0007), and its golden fixture gains `LOG_GOLDEN`. A later
shipgate may print those values in `position --json`, so the HUD can drop the `log` call.

v0.19.0 — a user decision binds its session, bold task ids, and a complete review verdict.

**A session whose writes are all `--actor user` binds to its stream (#9, ADR 0010).** The
`feature` skill records the user's decisions with `--actor user`. `user` is a sessionless
role, so those rows named no session. In an umbrella whose nested branches name two live
streams, the branch rule binds nothing, and the session's own writes are the last signal. A
session that had written only user decisions had none, so the HUD said "This session drives
no stream". The Stop gate had the same gap: a session that wrote a PRD and recorded only
user gate decisions was blocked for "no gate-decision this session".
- `append` keeps the actor `user` and writes the appending session into the payload as
  `data.recorded_by`. The source is `CLAUDE_CODE_SESSION_ID`, else `meta.current_session`,
  as for a machine label. The journal owns the key: `append` drops any value the caller
  passed, so a payload cannot name another session. An append with no session writes no
  key. The implied `phase-entered` row gets the same value.
- The key is added after the 1 KB check, so it never refuses a payload inside the cap.
- `event_session` reads `data.session`, then `data.recorded_by` on a `user` row, then the
  label of a machine role. So `status --session` (`session_match`), `check --session` and
  `stats` count the session that recorded a user decision.
- `event_session` never reads the label of a `user` or `watcher` actor. A `user@` or
  `watcher@` label no longer binds a session in `status --session`, and `stats` no longer
  counts a `watcher@` label as a session.
- The Stop gate reads the session's `user` rows too. Rule B accepts a user gate decision
  the session recorded. Rule C checks a `task-done` the session recorded for the user: a
  forced one with no passing `verify-run` before it blocks the stop.
- `watcher` stays sessionless and gets no key.
- Rows written before 0.19.0 carry no key and stay sessionless.
- The `feature` skill no longer says that `append` labels every role. It names the two
  sessionless roles and says what a `user` event records instead.

**For shipgate-hud.** No HUD change is needed for the binding. The HUD already passes
`--session` to `status --json` and binds on `session_match`, which journal.py now computes
with `recorded_by`. The binding works only against shipgate 0.19.0 or later. The HUD may
raise its `shipgate` range to `>=0.19.0` in a follow-up, so that a HUD user gets the fix
with it. A HUD view that prints raw event `data` now shows `recorded_by` on `user` rows.
The golden contract does not yet cover either new behaviour. A HUD change that regenerates
`fixtures.journal.ts` can add a bold task id to the golden worklog and a `--actor user` row
written from the golden session.

**Bold task ids in the Build Plan (#4).** The task-line grammar accepted only a bare id:
`- [x] T1 - title`. A worklog that bolded the id (`- [x] **T1** title`, or
`- [x] **T001**: title`) showed "No Build Plan found" in the HUD's Plan tab. The grammar
now accepts an optional `**` around the id (`**T001**`, or `**T001:**` with the colon
inside), and a colon as well as a dash after it. The closing `**` must follow the digits
or that colon, so `**T001a**` is still not a task. A `[P]` marker after the dash or the
colon no longer stays in the title. `position` (the
Plan tab) and `check` (the Stop gate's rule A) share this one grammar. So the Stop gate now
also sees a ticked bold task: a ticked `**T001**` with no `task-done` blocks a stop, as a
ticked `T001` always did. The worklog template and the `design` and `implement` skills
name the accepted forms.

**The review skill writes `criteria` and `dispositions` (#2).** 0.18.0 added both keys to
the `review-verdict` shape. The `review` skill now writes them in **Record the outcome**:
`criteria` maps each PRD success criterion (`SC-001`) to `met` or `unmet`, and is left
out when the issue has no PRD, because the HUD draws only `SC-` ids. `dispositions` maps
each finding (`<path>:<line>`, or `<path>:?`) to `fixed`, `rejected` or `deferred`. The
path is the reported path's last segments, at most three, which the HUD matches against
the full path. The keys stay compact, and the whole payload stays under the 1 KB cap.
Without them, the HUD's Review tab shows every criterion unticked and every finding open.

v0.18.0 — who wrote an artifact, and the facts the HUD draws.

**Attribution (ADR 0008).** Every session's FileChanged hook fires on the same write. The hook
recorded the observing session as `session`. The 5 s dedupe compared only path and mtime, so
the first hook to land owned the row, and the writer's own record was dropped. With parallel
sessions on one journal, a session that only saw a PRD change could be blocked at Stop, and
the session that wrote it went free.

Now each hook records a claim, and `journal.py` decides the author when it reads the claims:
- **FileChanged** records `observed_by`. It is an observer, never an author.
- **PostToolUse on Write, Edit and NotebookEdit** claims the file for its session.
- **PostToolUse on Bash (new matcher)** claims an artifact with `evidence: diff` when Claude
  Code's diff of the call lists it. It claims with `evidence: window` when the file's mtime
  falls inside the call's `duration_ms` and the command writes to the file: a redirect into
  it, `tee`, `sed -i`, `perl -i`, or the destination of `mv`, `cp` or `install`. The target
  must be the artifact itself, by its project path, so a copy to a file of the same name
  elsewhere claims nothing. A command that only reads the file claims nothing. The window also
  covers artifacts the diff cannot list, such as gitignored files and submodules.
- **A background Bash command** claims nothing. The hook runs `journal.py` only when it has
  a claim, and an un-journaled project costs a stat walk, as before.
- **The dedupe:** a claim is dropped only when the same session already claimed that write
  with evidence at least as strong. An observation keeps the 5 s rule.
- **The author:** the best evidence wins, in the order `tool`, `diff`, `window`. A tie
  between sessions names no author. `check` (the Stop gate) and `stats` read authors only.
  A legacy row that carries `session` with `source: disk` counts as observed.

**The journal computes the HUD's facts (ADR 0009).**
- `status --json` gains, per stream, `publish` (held, or authorized by which event, with its
  `seq` and time; the same helper as `mr-opened`), `lifecycle` and `current`. The top level
  always carries `nested_matches`.
- A new `position --stream S [--json]` prints:
  - phase marks: an earlier phase never entered is `skipped`, and a later phase entered
    before a move back is `revisited`;
  - the artifacts, classified with the configured homes, with unsafe refs dropped;
  - the worklog fallback by name;
  - the Build Plan tasks, parsed with `check`'s grammar;
  - gate decisions with their real `seq`, the last verify, and the last verdict.
- An unknown stream exits 1.

**The nested-branch rule (HUD ADR 0004).** In an umbrella, nested branches are matched against
live streams only. They bind a stream only when they name exactly one. Before, the most recently
active match won, so a session at an umbrella root was shown another session's work.

**Payload rules.**
- A `gate-decision`'s `decision` must be a string. A list once authorized a publish in the
  HUD's copy of the rule, while `mr-opened` refused it.
- A `review-verdict` declares `criteria` (`met`, `unmet`) and `dispositions` (`fixed`,
  `rejected`, `deferred`).
- `vocab --shape` prints both rule kinds (`strings`, `map_enums`).

**Fixes.**
- `_matches_glob` stripped any run of `.` and `/` characters from a home glob. It now
  strips only a leading `./`.

**A golden contract.** A test generates `shipgate-hud/tests/fixtures.journal.ts` from a
scripted journal, and the HUD decodes that file. Renaming a key fails the build on both sides.

v0.17.0 — the code graph. When the codegraph CLI is on `PATH`, `signals.py` takes the
structure half from codegraph's index instead of the regex scanner. Nothing needs to be
configured. The first call on a repository with no index builds it, up to 10,000 tracked
files. Before a query, shipgate syncs the index, unless a codegraph MCP server already watches
it. File edges come from a read-only read of `.codegraph/codegraph.db`. The tests a diff
reaches come from `codegraph affected`. A module loaded by path, which the regex scanner
cannot see, now shows its 2 test files in `blast`. A new `graph` subcommand runs one
codegraph query through the same checks: `impact`, `callers`, `callees`, `affected`, `query`,
`node` or `explore`. The shipgate flags go before the action, and shipgate adds `-p` and `-j`
itself. Its JSON wraps the answer as `{version, available, source, command, args, graph,
result, result_text, not_found}`. For `impact`, `callers`, `callees`, `affected` and
`query`, an exit-0 answer that is not JSON, such as a symbol that is not found, is
`available: true` with `result` null, the text in `result_text`, and `not_found: true`. For
`node` and `explore`, the text is always in `result`, and `not_found` says whether it reports
a miss. When the graph is unavailable, the answer is `available: false` with a
reason, exit 0, and no codegraph call. The JSON gains only new keys, and `OUTPUT_VERSION`
stays 1: `structure.source` (`graph` or `regex`), `structure.graph` (state, reason, version,
index root, build, sync), `blast.tests` with `blast.tests_reason` (`graph-affected-seeds` there means every seed path holds a line break), a top-level `advisory`, and
`config.code_graph`. `structure.graph.index_root` is relative to the repository: `.`, or `..`
in root mode. Two new reasons send a call to the regex scanner. `graph-index-untrusted` means
shipgate refused an index that the repository itself supplies. `.codegraph`,
`.codegraph/codegraph.db` or `.codegraph/.gitignore` is a symlink, `.codegraph` resolves
outside the repository, git tracks a file under it other than codegraph's own
`.codegraph/.gitignore`, or a directory spelled like `.codegraph` in another case exists,
tracked or not. `graph-empty` means the index holds none of the files the call asks about,
after `--scope` and `--exclude`. A new `--graph auto|off|root` flag and an optional `Code graph` bullet under
`## Code tooling` select the mode; `auto` is the default. Eight skills use the code
graph: `route-and-map` reports the tests the diff reaches and the impact of each changed
exported symbol; `review` lists those tests under the risk table, and the verify gate runs
them; `structured-debug` cites callers and callees as `[graph]` evidence; `implement` searches
the graph before it writes new code; `design` may check who calls each precedent; the explorer
brief in `feature` and the worker brief in `model-tiers` name `explore`, `node` and `callers`
as the first move; `workspace` seeds a new worktree's index with a copy of the source
checkout's index, which the next query syncs. With codegraph absent,
every phase runs as before, plus one advisory line, once per project. A codegraph call that
fails gives the regex result and one reason line. `signals.py` now writes, never into tracked
files: `.codegraph/` (by codegraph, when shipgate builds the index), one `/.codegraph/` line
in `.git/info/exclude` for an index it built, and a lock and advisory markers under
`.git/shipgate/`. It never installs codegraph, never writes MCP configuration and never edits
`CLAUDE.md`. Every codegraph call runs with telemetry off. No hook calls codegraph, and a test
in `tests/test_hooks.py` keeps it so. ADR 0007 records the design, and amends ADR 0004.

v0.16.2 — a linked worktree uses the main checkout's journal. A repository that commits
`.claude/shipgate.json` gives every linked worktree a copy of it. For a session in the
worktree that copy is the nearest sidecar, and its relative `db` named a file inside the
worktree. So each worktree started its own empty journal, and the hooks and `journal.py` both
used it. Only a hand-made symlink to the main journal kept the flow on one journal. Now a
relative `db` resolves against the main worktree when two things hold: git's back-link
(`<git-common-dir>/worktrees/<name>/gitdir`) names this worktree, and the main worktree holds
a sidecar too. The worktree stays its own project, so artifact capture and PRD paths do not
change. The git dir must sit directly under `<git-common-dir>/worktrees/`, outside the
worktree, so a checkout that plants its own `.git` pointer files cannot borrow another
checkout's journal. The redirect follows one hop at most. A submodule or a bare repository
keeps its own journal, and so does a worktree of a submodule or of a repository made
with `--separate-git-dir`: only the standard layout, where the main worktree holds `.git`, is
recognized. The rule is one function in `hooks/_common.py` (`sidecar_db_path`), and
`journal.py` calls it. The hooks read three small files and start no subprocess. One more
split is closed: a sidecar without a `db` key sent the hooks to the default db at the
sidecar's directory but sent `journal.py` to the default under its working directory. Both
now use the sidecar's directory. An existing worktree symlink to the main journal still
works; it now names the same file the rule picks.

v0.16.1 — the hooks and `journal.py` pick the same journal. The hooks took the nearest
`.claude/shipgate.json` from the session's directory up to the filesystem root. `journal.py`
stopped its walk at the first `.git`, a directory or a file. A session in a linked worktree
(`<root>/.worktrees/x`) or in an independent repo nested in a journaled project
(`<root>/sub`) therefore had two journals: the hooks wrote to `<root>`'s, and every skill's
`journal.py` call fell back to `<cwd>/.claude/shipgate.db`. That call failed with "journal
database not found", unless someone had run `init` there. After an `init` the split was silent:
the skills read and wrote a second journal that the hooks never saw.
`journal.py` now uses the hooks' own walk (`hooks/_common.journaled_root`), so a nested
`.git` is no boundary. `--db` still wins, and a relative sidecar `db` still resolves against
the sidecar's directory. The hook code does not change. `signals.py` finds an umbrella's
sidecar with the same walk, so its `## Code signals` config comes from the journal's
project, also when that sidecar sits above a git umbrella's toplevel. `signals.py` keeps
`git rev-parse --show-toplevel` for the repository it reads, because history, `ls-files`
and the import graph belong to one git repository. The shipgate-hud already walked like
the hooks and ran `journal.py` in the project root, so it does not change. Regression
tests pin both nested cases: the hooks and `journal.py` must resolve the same db path.

v0.16.0 — workers never run below Opus. `model-tiers` sent coding workers one tier below
the session, so a session on Opus dispatched Sonnet workers for all product code. On a
production project that put a change to a money type on Sonnet, and the user had to step in.
Sonnet is now the mechanic tier only: the worker tier is one tier below the session but
never below Opus, so a session on Opus dispatches same-tier Opus workers. A new definition
says what "very mechanical" means: the brief fixes the exact edit and leaves no call to make.
Work that touches a type, a data encoding, a business rule or money is never mechanical. A
third invariant states the rule: judgment work never runs below Opus. The review fan follows
it too: the review Workflow script's `model` is the worker tier, and the `code-reviewer`
agent's default moves from `sonnet` to `opus`. The explore fan keeps one tier below the
session with no floor, because explorers only locate code and the orchestrator reads the
flagged files itself. `implement`, `feature`, `review` and the glossary carry the same rule.
The cost is honest: an Opus session's workers and reviewers now cost Opus tokens.
The README's `Status` section no longer copies release notes. It had drifted to v0.13.0, so
it now points at this file and at `plugin.json`, the single home for each.

v0.15.0 — writing for people, scoped by audience. Karpathy's advice is to ask a model for
prose about 80% of the way to ASD-STE100 (Simplified Technical English): short sentences,
common words, one term per concept, one action per instruction. The plugin adopts the
principles, not the specification, and only where each audience gains. **Reports a person
reads** (review findings, verify results, debug hypotheses, gate summaries, the orchestrator's
phase summaries) follow a "Writing for people" rule by default: sentences of about 20 words
with one idea each, one term per concept, the same term every time, active voice, and the
guard that matters, since strict STE prompting is known to drop facts: shorter sentences,
never fewer facts; every file:line, severity, confidence, failure scenario, command, exit
code, count and verdict stays. The rule is one blockquote repeated verbatim in the three
agents and the nine skills that prescribe a report or hand the rule on (ADR 0006), pinned by
`tests/test_prose.py`. **Documents written into a repo or forge** (PRD, ADR, worklog, ledger
lines, MR/PR body, tracker comments) keep their style unless the project opts in: a new `##
Writing style` config section, `Docs: plain | ste-80`, default `plain`, read by `clarify`,
`design`, `implement`, `knowledge-base`, `review` and `structured-debug` where they write,
carried into worker briefs by `model-tiers`, offered by `setup`. **The prose the model reads**
(12 skills, 3 agents, the command) was rewritten body-only after a second terminology pass
against the glossary: mean sentence length fell from 15–29 words to 8–16 per file, with every
fenced block, backticked token and number present before present after (one example string
inside a fenced block changed, MR to MR/PR), and every frontmatter `description:`
byte-identical, since those are the triggering surface. A new eval,
`70-review-fact-retention`, plants three findings of different severity in three files and
grades each fact: with the plugin every fact grader passes 3/3 (0.96 with, 0.69 without; the
readability rubric is paired with a hedge-word regex and weighted low, because style rubrics
are the noisier signal). The 23 affected cases re-run before and after the rewrite on the same
day: no case lost more than 0.07 in the with arm, two gained, every negative case stayed at
zero skill-fired. Baseline re-recorded for those 24 cases at 0.15.0. `review` briefs reviewers with the working-tree diff and commits after the verdict (ledger,
2026-10-08). Glossary gains `report`,
`Writing for people`, `escalation contract` and `reference implementation`. No hook, script or
Workflow change.

v0.14.7 — the session-start brief leads with the stream this session drives. The SessionStart
hook asked `status` by branch only, so after a compaction or a resume a session driving a
stream with no branch (an epic's planning stream) got the checkout's stream first, and in an
umbrella possibly another session's. The hook now also passes `--session=<session_id>` from its
payload (0.14.5's flag) — one token, and only for a plain id (letters, digits, `.`, `_`, `-`, at
most 128), so an absent or odd id costs the ordering hint, never the brief. The brief marks that
stream `· this session`. A session that has written nothing yet (a fresh start, `/clear`) gets
the branch ordering as before. Four tests.

v0.14.6 — an explorer can read a ref that is not checked out. `code-explorer` had Glob, Grep
and Read only, so a lens that had to read `origin/<integration>` — a staleness check of a
dormant design against what merged since — or a file's history could not, and the explore
workflow (which dispatches `shipgate:code-explorer`) had to be re-run by hand with other agents.
The agent now has `Bash`, limited by its prompt to read-only git (`git show <ref>:<path>`,
`log`, `diff`, `grep`, `blame`, `ls-tree`): never fetch, checkout, switch, reset, stash, commit
or a worktree, and a ref that does not resolve is reported, not fetched. The `feature` skill
tells the orchestrator to fetch before dispatch and to name the ref in the lens prompt — the
same tool set `code-reviewer` already has. One contract test pins it.

v0.14.5 — parallel sessions keep their own events, and status knows each session's stream.
`append` labelled an unlabelled actor with `meta.current_session`, which every session start
overwrites, so with two sessions open on one project the later starter's id labelled the
other's events. The label now comes from `CLAUDE_CODE_SESSION_ID` in the appending shell (a
subagent's carries its parent's), with `meta.current_session` as the fallback (ADR 0005,
amending 0003). `status --session ID` marks the live stream that session last wrote to itself
(`session_match`; hook-written events do not count, a finished stream releases it) and renders
it first, in full, ahead of the branch's — the call shipgate-hud 0.2.4 makes. The test helpers
drop the variable from the environment they hand to journal.py and the hooks, so the suite
gives the same result inside and outside a Claude Code shell. Prompted by a session planning
an epic (a stream with no branch) whose HUD showed another session's stream instead.

v0.14.4 — a stream checked out in a git worktree is found. The SessionStart hook's nested-repo
scan (0.14.3) skipped dot-directories and looked one level down only, so a branch checked out
in a worktree under `.worktrees/` — where the `workspace` skill puts one, beside the repos or
inside one — never reached `--nested-branch`, and the brief lost its ordering for exactly the
work in progress. The scan now looks into each parent's and each nested repo's `.worktrees/`
(a repo, then its own worktrees, then the parent's); a directory's worktrees are read only
when it is a repo itself. Same caps and reads as before. One test extended. The `workspace`
skill now says where a worktree goes (`.worktrees/<slug>` inside the target repo, the command
run from there — where the hook and the HUD look), that started work is never
moved into or out of a worktree without the same confirmation a new branch gets and a
`deviation` event naming the new path, and that the `phase-entered workspace` note carries the
worktree path in `refs`. Prompted by a session that moved an issue's branch into a worktree late
in the flow, unrecorded, leaving the HUD and the brief with no position for the live work.

v0.14.3 — the status brief keeps its checked-out-first ordering in an umbrella. The
SessionStart hook took the branch from `git rev-parse` in the session directory only, so in
an umbrella checkout (a plain folder, or a repo of its own on an integration branch, with
the real repos one level down) it passed no branch, or one that names no stream, and the
brief listed every stream unsorted. The hook now also collects the branch of each nested
repo (`*/`, `source/*`, `packages/*`; dot-directories, `node_modules` and symlinked entries
skipped, at most 64 repos) by reading its `.git/HEAD` — a `gitdir:` file is followed once
and only within the session directory, a detached HEAD names nothing, no subprocess per
repo — and passes them as `--nested-branch=<name>`. A checkout is untrusted content, so the
read is non-blocking and refuses anything but a regular file (a FIFO at `HEAD` cannot hang
the session), and a name with a NUL or a control character is dropped rather than aborting
the hook and losing the brief.
`journal.py status` gained that repeatable flag: tried only when `--branch` names no
stream, and among the matches the most recently active stream wins, so a dormant stream
on another nested repo's branch cannot shadow the live one. Hooks hold no policy: which
branch orders the brief stays the journal's call. Ten tests added.

v0.14.2 — umbrella roots that are not git repos. An umbrella is a scaffolding directory with
the real repos nested beneath it; `setup` writes the config, sidecar and journal at its root,
and that root is often a plain folder, not a repo of its own. Three places assumed a git repo:
`signals.py` read the umbrella's `## Code signals` only when the parent was a git work tree,
so a plain-folder umbrella's `Exclude` had no effect inside a nested repo — it now also treats
a parent (or an ancestor up to the parent's own git toplevel, for `source/<service>` layouts)
holding the setup sidecar `.claude/shipgate.json` as the umbrella; a plain parent with neither
is still not read. `setup`'s Step 1 told the model to stop when the directory is not a git
repo, which contradicted its own umbrella bullet — it now checks for nested repos first and
stops only when there are none. `workspace` described an umbrella as always being a git repo
of its own; it now says either form, detected by the nested repos. Two tests added.

v0.14.1 — one term per concept. A terminology audit of every file the model reads (skills,
agents, the command, README, config template, the user-facing strings of the hooks and scripts)
found the same concept under several names — "working doc" beside "worklog", "coordinator" and
"master session" beside "orchestrator", "legacy mode" beside "un-journaled", "session brief"
and "position brief" for the `status` output — and a few words carrying two concepts
("capture" for both the phase and the hooks' artifact recording, "brief" for both the status
brief and a subagent's instructions, "lens" unqualified). Prose now uses one canonical term per
concept, preferring the contract name where one exists (`worklog`, actor roles `orchestrator`
and `worker`, hook event names), and the new `docs/glossary.md` records each term, its
definition and what it is not to be confused with. Contract names — journal events and fields,
CLI flags, config keys, sidecar fields, file names — are unchanged. Four printed strings
changed wording only (`status` with no streams, two `--help` lines, the `vocab` line for
`design-queued`); the hooks were audited and left unchanged. No behaviour change. The full
69-case eval suite re-run at 3 runs per arm: mean with-arm score 0.976 vs 0.972 at baseline, mean delta
+0.095 vs +0.080; no case lost more than judge noise except 46, whose fixture carries a "revisit
2026-10-05" date and now fails identically in both arms (a dated fixture, logged for repair).

v0.14.0 — thinking lenses inlined into the phase skills. A standalone thinking-skills plugin lists
39 skills; the session's skill listing has a budget of roughly 1% of context, so most of those
descriptions are truncated and the skills never fire (in the maintainer's usage, only the 4 whose
descriptions survived ever triggered). shipgate already carried the lenses that matter inline —
design: reversibility, pre-mortem; structured-debug: occam's-razor, kepner-tregoe, five-whys-plus;
code-reviewer: red-team / inversion; clarify: jobs-to-be-done via the config's **Thinking lenses**
hook — where they fire deterministically at the right phase and cost nothing in the listing. This
release absorbs the remaining engineering-flow lenses the same way, each as a bullet or short
paragraph in the existing voice with the condition under which it applies, condensed from the
original `SKILL.md` texts of
[cc-thinking-skills](https://github.com/tjboudreaux/cc-thinking-skills) (MIT, © 2025 TJ Boudreaux
— credited in the new `NOTICE` and in the README): `design` gains steel-manning (the runner-up
blueprint's strongest case before the recommendation — doubly when the runner-up is the user's own
preference), second-order ("and then what?" at the next request / next deploy / 10× horizons,
stopping at the first effect that changes the decision), via-negativa (does the problem go away by
removing something, asked of every blueprint), TRIZ (two requirements that seem mutually exclusive
are separated in time, space, condition or level rather than compromised) and margin-of-safety (a
timeout, limit or capacity is sized to the cost of being wrong, after measuring);
`structured-debug` gains map-territory (behaviour contradicts a doc, test or comment → read and
run the path that actually runs; the territory wins), OODA (an incident under time pressure →
propose a reversible stabilizing move at ~70% confidence for the go-ahead, re-observe, then root
cause) and systems (a fix here breaks something there → map components, feedback loops and
delays); `feature` scales ceremony by Cynefin as well as size (clear / complicated / complex →
spike before the PRD / chaotic → stabilize first); `clarify` runs first-principles on constraints
stated as fixed (physics, cost, regulation — or convention?); `implement`'s stop rules gain
sunk-cost (from the debiasing skill's self-check: the same approach failed twice → stop, re-plan)
and bounded-rationality (an open-ended search gets a stated "good enough" — never a correctness
gate); `review` steel-mans a disputed finding before holding or conceding; `knowledge-base`
reports an empty recall as empty instead of filling the gap (circle of competence). via-negativa
and first-principles already sit in `code-architect` as per-philosophy lenses; the
coordinator-level via-negativa line stays because the coordinator, not one architect, commits
across all three blueprints, and first-principles lands in clarify where constraints are decided.
Out of scope, by design: regret-minimization, effectuation, archetypes, leverage-points,
feedback-loops, lindy, fermi, probabilistic, opportunity-cost, thought-experiment and the
model-router / selection / combination skills — not engineering-flow lenses. **Body-only**: no
skill's frontmatter changed (verified byte-for-byte against the previous release — descriptions
are the triggering surface the evals measure). File size deltas: design +1,678 B (+15.5%),
structured-debug +1,045 (+7.2%), feature +667 (+3.5%), implement +621 (+6.2%), review +467
(+1.8%), clarify +321 (+3.9%), knowledge-base +302 (+2.7%); 5,101 B in total. Two eval cases cover
the lenses most likely to change behaviour: **68-design-steel-man** (the clarified billing PRD
from 51–57, with the user arriving set on synchronous in-request rendering; pass = the answer
builds and answers the strongest case for the queue / stored-file alternative rather than agreeing
by reflex) and **69-debug-map-territory** (README, docstring and a green test all describe
discount-before-tax and are right about `pricing.quote()`, which the live `checkout.charge_total`
stopped calling in a "one pass" perf commit that re-implements the arithmetic inline and scales
the discount back out of the taxed gross, so only the pre-tax 10.00 comes off the taxed 120.00 —
110.00 instead of 108.00 (order alone would not matter; the scale-back line is the defect); pass =
the answer names the live path, says what the green test does and does not cover, shows a repro
and names the perf commit). On the harness (3 runs, with/without, Opus, judged by Sonnet): 68
scores 0.67 with / 0.44 without (+0.22), the skill firing 3/3 and all three with-arm transcripts
building the alternative's case explicitly ("I looked for the strongest argument for a worker",
"the best argument for a worker plus stored files") and answering it point by point, against none
of the three bare-model runs; the `strongest-case-stated` regex grader splits 2/3 vs 0/3 (the miss
says "best argument", which the regex does not list — left as is rather than widened to the
transcript), while the five-claim Sonnet rubric passed only 1 of the 3 with-runs and is read as
the noisier of the two. 69 is a ceiling case like 01 — 1.00 / 1.00, both arms find the live path,
the skill firing 3/3 and taking 7–8 turns to the bare model's 4 for the same verdict; it stays as
regression coverage for the lens. Case 68's first rubric failed the two with-runs that visibly
steel-manned because two claims demanded the steel-man precede the words "I agree"; both ordering
nits were dropped (grade presence and engagement, not sentence order) and the case re-run; case
69's first rubric misdescribed its own defect as "wrong order" (percentage tax and discount
commute — the scale-back line is the bug) and was corrected and re-run before recording. The
`thinking-skills` row leaves the README's integrations table: recommending a 39-skill plugin
pushes a user's skill listing past its budget, which is what truncated the descriptions in the
first place. The **Thinking lenses** config section stays as the generic override hook — map a
phase to a lens *skill* when one is worth its listing space — and its docs name cc-thinking-skills
once as an example source.

v0.13.6 — phase skills record their journal events. The large journaled fixture (evals 58–67:
a monorepo with 44 commits, 12 ADRs, a config with a Journal section, sidecar and a database
seeded with three streams) showed the skills firing on 8 of 9 fire cases while appending a phase
event in 2 — `review-verdict` on the re-review and `clarify-passed` — and nothing from
`structured-debug` (58, 59), `route-and-map` (60, 61), `review` (62) or `design` (66), the same
shape the production journal has worn for weeks (a handful of `debug-root-cause` rows across
dozens of bug fixes, phases "done inline", capture from memory). Every skill carried a *Record …
(journaled projects)* section with the exact command, so the traces were read rather than the
sections rewritten blind, and they named a different defect from the one assumed: the agent did
not forget the append, it **declined it for want of a stream**. Each fixture checks out the
integration branch and seeds streams only for earlier issues, which is also how real work
arrives — a bug reported on `main`, a routing question before any branch, a commit at HEAD
reviewed before the PR — and the three misses said so in their answers ("there's no branch or
issue for this work yet", "no journal stream for #455, so I didn't record a verdict rather than
make up a stream name"); the fourth deferred `design-committed` until the user approved an
escalated migration. The two runs that did append had a pre-seeded stream for their issue. Two
mechanical faults sat underneath: `route-and-map`'s quoted `phase-entered` is refused on any
stream that never entered `workspace` (`append` rejects a forward jump without `skipped`, and
`workspace` appended only `flow-started`, which sets no phase), and the orchestrator promised the
Stop hook would catch a missing semantic event when `journal.py check` gates only `task-done`,
`verify-run` and clarify's `gate-decision` — none of the phase events. Fixes, all in skill
bodies: each phase skill (`structured-debug`, `route-and-map`, `review`, `design`, `clarify`)
opens with a *journaled project — name the stream before you start* pre-flight (the stream is the
branch the work takes per the config's Branching pattern, whether or not that branch exists;
the integration branch is never a stream; no stream in the brief → open it with `flow-started` in
the same append as the first event; the event the phase owes, and the step that writes it); the
append moves into the workflow step where the fact exists — `bug-reproduced` at reproduce,
`debug-root-cause` at root cause before the ledger jot, `phase-entered` as the map is emitted
rather than after the user confirms it, `review-verdict` as the verdict is stated and before the
MR/PR question, `design-committed` as the worklog lands with an `open` list for ADRs still
awaiting the user — and the record sections become the reference form plus the `--batch` that
opens a stream and records into it in one call; `route-and-map`'s example carries
`"skipped":["workspace"]` and says why, its standalone blast-radius note no longer says "do not
journal" (that answer starts no flow; the routing ask for new work does); `workspace` records
`flow-started` and `phase-entered workspace` as one batch and continues on a stream a phase
skill opened earlier instead of starting a second; the orchestrator gains the stream rule and
states what the Stop hook actually checks. On the harness (3 runs, with/without, Opus, judged by
Sonnet): `journal-phase-event-appended` passes 3/3 with-runs on 58, 60, 62 and 66 (was 0/1 in the
pilot on each), no invented type names, every with-run opening a pattern-named stream
(`fix/<slug>`, `feat/<slug>`, `feat/455-cancel-order`); with-arm scores 0.93 / 1.00 / 1.00 / 1.00
against baselines of 0.83 / 0.90 / 0.90 / 0.92 (58's one miss is a judge FAIL on an answer that
names the commit, the line and the rounding-mode change and ends with a proposal); 67 (a one-line
config change) still makes no journal write, 3/3 both arms, 1.00. No script or hook changed; the
Stop-hook gap on phase events is recorded here as a known limit, not papered over in the prose.

v0.13.5 — `review` on the re-review after a round of fixes. Eval 47 (the review suite's
after-fixes case: a worklog whose *Review round 1* section lists F1 and F2 as fixed at HEAD, a fix
commit that closes both and quietly drops the export's header row, and the ask "I've addressed
the round-1 review findings F1 and F2 (see the worklog); the fix is the commit at HEAD. Good to
push?") showed the skill never firing — 0 of 3 with-arm runs, against 9 of 9 on "Review the
change at HEAD before I open the PR" (44–46) — and the traces show why: the model reads the
two-file fix diff itself from the first turn, the ask being one it believes it can answer
unaided. The description's triggers ("review a change before an MR/PR or push", the risk
ranking, "implementation is complete") never named this shape, which is the one that bites on
real work: the fixes land, the new diff gets no pass, and that is where the next finding lives.
The description now carries the re-review from the user's side ("I've addressed the review
findings F1 and F2 — good to push?", "round 2", "re-review the fix", "the follow-up commit", a
worklog listing findings as fixed at HEAD), says the size of the fix diff does not matter, and
promises the two things a glance at the worklog cannot settle — whether each listed finding is
actually fixed in the code, and what the fixes broke; its negative trigger now also names a
docstring or comment edit and explaining what a diff does. The body gains a *Re-review after a
round of fixes* section beside the standalone-asks note: scope the pass to the fix diff (HEAD
against the base the previous round reviewed), scale it to that diff (one reviewer carrying all
lenses, or the coordinator alone for a couple of files — never the three-lens fan), confirm
each finding on evidence, then hunt the regressions the fixes introduced through the FR/SC the
fixed code serves, append *Review round N+1* to the worklog, and give the Step 6 verdict — a new
regression is Not ready however many findings closed; one `review-verdict` per round, counted
toward the two-round cap. On the harness (3 runs, with/without, Opus): 47 fires 3/3 (was 0/3) with
no reviewer agent dispatched in any run (the coordinator reviews the two-file fix diff itself and
says so), scoring 0.90 and 1.00 over two trees (the one with-arm miss is a judge FAIL on an answer that confirms F1 and F2, names the dropped header at a file:line and says Not ready — within the judge's noise); 44 and 46 fire 3/3 and score 1.00 / 1.00 (baseline 0.90 / ~1.0); the
negatives 49 and 50 stay silent 0/3 with zero Agent calls and score 1.00. The with-arm cost of a
47 run is about 1.8× the bare model's and ~15 s longer, the price of the worklog round entry and
the scoped verify, not of a fan. No script or hook changed.

v0.13.4 — mid-flow ledger jots. Eval 43 (the knowledge-base suite's implicit-jot case: a
failing test whose cause is SQLite's off-by-default foreign-key enforcement, the user's go-ahead
to fix, and a `docs/ledger.md` already in the repo) showed the plugin writing the dated ledger
line in 1 of 3 runs, the bare model in 0 of 3 — the same shape the flow journal shows on a
production project, where Capture keeps finding an empty ledger and promoting "learnings" from
end-of-flow memory. The flow that runs is `structured-debug`, and its only ledger instruction was
one sentence at the end of the Validate section, after the fix, with no trigger moment, no format
and no command; `implement` (step 7) and `review` carried the same aside. Each now has the jot as
a positioned step with the append inline, so it costs one tool call and no skill load:
`structured-debug` step 5, between the confirmed root cause and the fix plan — if the cause is a
reusable trap (a default that silently disables a feature, a command or log line that lies, a
test that passes vacuously) append one dated line now; `implement` at the task tick; `review`
while ranking findings. `knowledge-base`'s ledger section names those moments and the line
format. Two rules came out of the measurement rather than the design. The jot goes only into a
ledger the project already has (the config-declared path, or an existing `docs/ledger.md`): the
first draft created the file when absent, and on the structured-debug fixtures, which have none,
the announced new file cost the "proposal, not an applied fix" judge claim (01 → 0.89, 03 →
0.71). And the `knowledge-base` description is unchanged, because skill selection happens when
the ask arrives and a confirmed root cause is not an ask. On the harness (3 runs, with/without;
two trees for 43 on the final wording): 43 jots 5/6 (was 1/3) with the fix applied 6/6 and
`CLAUDE.md` clean 6/6; 38 1.00; 41 and 42 1.00 and silent with no files written; structured-debug
01 1.00, 02 0.78 / 0.89 (baseline 0.89 / 1.00 — the misses are the credit-note coverage claim,
no ledger involved), 03 0.90 (baseline 1.00). No script or hook changed.

v0.13.3 — `verify` on natural completion asks. Evals 22–28 (the verify suite) showed the skill
never fired: 0 of 15 with-arm runs on ordinary asks that end in a status the user acts on ("fix
whatever fails and confirm we're good to go", "rename X and tell me when it's done", "confirm the
suite still passes", "get lint and tests green, then tell me"). The description was phrased from
the model's side ("use whenever about to claim success") and never matched the moment — skill
selection happens when the ask arrives, not when the claim is being written. It is rewritten the
way the phase skills that do fire are, and trigger-first: it opens with the asks themselves, from
the user's side (a task ending in done / fixed / green / good to go / confirm); names a pasted
test run or CI result in the ask as a trigger on its own, since that output describes the code
before the edit; says outright that the size of the change does not matter (a one-line edit plus
"confirm the tests still pass" is the canonical case); then lists what the skill adds — the
checklist of ways a green report lies (proving run before the last edit, 0 tests discovered,
stale pasted output, several claims in one report, hedged wording) and the gate; and carries
negative triggers for explaining code, a one-shot "run X and tell me the result", and
re-verifying a claim already settled in the same state. The body's "evidence, not repetition"
rule now also says a green proving run is followed by the report, not by ad-hoc spot checks.
On the harness (3 runs, with/without, Opus): the skill fires 3/3 on cases 22, 23, 25 and 26 and 4/6 on 24 (two trees), from 0/15 at baseline; the negatives stay silent with their command counts unchanged (27 runs no command, 28 runs the suite exactly once in 6/6); with-arm scores are 0.90 / 1.00 / 1.00 / 0.92 / 0.90 for 22–26 against a baseline of 1.00 / 0.94 / 1.00 / 1.00 / 0.90, and 22's ordering check (last suite run after the last edit) holds 3/3. The one with-arm outcome miss on 22 is an honest "not good to go yet" that stops to ask which rounding rule is intended, not an unverified claim. No script or hook changed.

v0.13.2 — `structured-debug` on two more bug-report shapes. Evals 01–07 (the structured-debug
suite) showed the skill never fired on a bug report that ends in an instruction to fix ("X is off
by one for some users. Just fix it." — the fix was applied unreviewed in 6/6 baseline runs) nor
on a pasted production stack trace with no repo access ("what's going on?"). The description now
names both: a report with an instruction attached is still a bug report, and pasted evidence is
answered with competing hypotheses and the evidence that decides them; it also carries negative
triggers for a feature request and an "explain this code" ask. Firing alone was not enough for
the first shape — the skill loaded and the model still patched, reading "just fix it" as the
approval — so the body's approval rule now says explicitly that a fix instruction *in the report*
is not approval of a fix plan; approval is a yes to the plan after it is presented, and step 5
ends the turn on the proposal. On the harness (3 runs, with/without): case 05 goes 0.33 → 1.00
with the fix held back 3/3, case 04 fires 3/3 at 1.00, the two negative cases stay silent at
1.00, and 01–03 are unchanged or better (03 now fires 3/3, was 1/3). No script or hook changed.

v0.13.1 — skill triggering on natural prompts. The v0.13.0 signals only reached users who
typed `/shipgate`: on naturally phrased asks ("which file most likely has the defect?", "what
could the change at HEAD affect?", "rank the changed files by regression risk") no shipgate
skill fired in any of ~60 eval runs, because each description said where the skill sits in the
flow ("first step of any feature", "final pre-push review", "agree a fix before changing code")
rather than what a user asks for, and none named the capability a plain read cannot give. The
`structured-debug`, `route-and-map` and `review` descriptions are rewritten around the asks
and the computed signals, with a negative trigger for trivial one-line edits; each skill body
gains a short **Standalone asks** note so an invoked skill answers the question and stops (no
branch, no fix plan, no reviewer fan); `feature`'s description sends standalone questions to the
phase skill instead of the orchestrator. Evals 08–11 are the regression test; no script or hook
changed.

v0.13.0 — code signals. The flow's intelligence was all *declared* (CLAUDE.md, ADRs, the
journal); nothing computed what the code and its history say. **Signals**: a second bundled
stdlib script, `scripts/signals.py` (`hotspots`, `blast`, `suspects`), computes per-file git
trajectory (commits, fix-rate, age, staleness, author count and top share) and, for TS/JS,
Python and Go, import-graph fan-in/out and blast radius, each labelled by quartile over the
whole repository so `top` means top *here*; "now" is HEAD's commit time, so two runs on one
state are byte-identical, and nothing persists (ADR 0004). A new `## Code signals` config
section (window, fix pattern, extra excludes) is the first one a script reads itself, so the
terminal and the flow compute the same numbers. **Wiring**: `route-and-map`'s impact map
gains a **Risk signals** block and the journal entry its labels and sizes; `review` briefs
carry the diff's risk table, and `review-workflow.js` takes an optional `fileRisk` that
tie-breaks ranking after severity and confidence and spends the refuter budget severity →
risk → confidence — risk never overrides severity, and absent it the output is byte-identical;
`structured-debug` starts hypotheses from a ranked suspect list; `implement` and `design`
prefer the precedent with the lower fix-rate, greater age and higher fan-in; explorer and
worker briefs may carry the table. No git, a shallow clone, an empty history or no adapter
degrades to one line and the phase as before. **Honesty**: fan-in is a lower bound in
alias-heavy or dynamically-imported code (the output marks `partial` / `unresolved`; risk is
a tie-break within a severity band only, so an undercount can cost a file its refuter slot in
that band but never changes a severity or drops a finding); granularity is the file, not the method,
and the semantic axis (embeddings, BM25, a glossary) is out of scope by decision. An indexed
retrieval layer (TeaRAGs-style: daemon, embedding runtime, ~1 GB per repo) was evaluated and
rejected as a dependency — see `docs/research/2026-09-25-tearags-vs-shipgate.md`. Evals
08–11 (bug localization from history, blast radius of a diff, risk-ranked review, a negative
one-line change) cover the new behaviour under `--ablation with-without`.

v0.12.1 — hooks file cleanup. `hooks/filechanged.json` carried its explanatory note under a
`_comment` key, which Claude Code's hooks loader reports at every session start as
`hooks.json: unknown key "_comment" ignored`. The note now lives under `description`, the
documented top-level field for a plugin hooks file. No behaviour change.

v0.12.0 — orchestration by workflow, config-selected. A new `## Orchestration` config
section (`review: agents | workflow`, `explore: agents | workflow`, default `agents`) lets
a project run the Review fan and the Explore fan as `Workflow` scripts bundled with the
skills instead of hand-driven `Agent` fans. **Review**: `review-workflow.js` runs the lens
finders (`shipgate:code-reviewer`, schema-typed findings, do-not-flag and pre-rulings
passed as `args`), dedupes across lenses in script, then spends a capped refuter budget
(`verify: none | high-only | all`, defaulting to `high-only` with `maxRefuters: 6`) on the
BLOCKER/HIGH candidates: a refutation counts only when it cites the `file:line` that
disproves the finding, and a finding dies only on a full quorum — every requested refuter
reported and every one of them refuted with evidence — so an uncertain, uncited or dead
refuter leaves it standing. The return is compact — ranked survivors carrying `verification`
and `quorum`, the killed list with its evidence, one-line below-floor entries, counts and
run-level `coverage` — so the coordinator's filtering pass starts from data, the raw
reviewer reports never enter its context, and the run id lands in
`review-verdict.data.workflow_run_id`. **Explore**: `explore-workflow.js` runs the lenses
as `shipgate:code-explorer` agents and merges their essential files, capped at 25; the
orchestrator still reads those files itself. Scripts always receive an explicit `model`
(one tier below the session — the tool would otherwise inherit the session model), and the
bundled-file references in `clarify`, `design`, `review` and `feature` now go through
`${CLAUDE_PLUGIN_ROOT}` so they resolve after a marketplace install. The cost is honest:
the finders cost what the `Agent` fan costs, so the gain is structure, dedupe and context
hygiene rather than fewer tokens, and full verification (`verify: all`) is worth it only on
high-stakes diffs. Implement stays on `Agent` workers (mid-flight `SendMessage`, warm reuse,
environment repair and the shared working tree have no workflow equivalent). A host without
the tool keeps the `agents` path and records a `deviation`.

v0.11.0 — the flow journal made cheap and trustworthy, from two weeks of its own data.
**Cost**: the session brief drops finished work (a stream now ends with `flow-completed`, and a
`capture-done` left alone for 48 h reads terminal; `--all` still shows everything), collapses
streams dormant over a week to one line, caps each stream at its last three gate decisions
(five on the checked-out branch's stream), and puts the checked-out branch's stream first
(`status --branch`, passed by the SessionStart hook); semantic events go up as one `append
--batch` per phase boundary, and a payload over 1 KB is refused so the prose stays in the
worklog and the event carries `refs`. **Position reliability**: a phase-owning event records
the `phase-entered` it implies instead of leaving the brief's headline field to memory (ADR
0002), `append` validates each type's payload against a canonical shape and normalizes the
aliases that had been drifting silently past the gates (`chosen→decision`, `kind→gate`,
`result→outcome`, `tasks→task_ids`, verdict `pass→ready`), and `actor` becomes `role[@label]`
over a closed set of roles, labelled by default from the session id the SessionStart hook
records (ADR 0003) — so who decided, and whether they were asked or were correcting
(`gate-decision.raised_by`), is finally queryable, via the new `stats`. **New gates**:
`mr-opened` is refused unless a `ready` verdict or the user's own `gate=publish` /
`decision=publish` call stands after the last `task-done` — "start the next item" cannot
publish; duplicate `artifact-written` rows (same path, same mtime, under 5 s apart) collapse;
and the Stop hook records its own blocks as `gate-blocked`. **Process**: the config template
gains a `## Worker guardrails` section that `model-tiers` requires pasted word-for-word into
every worker brief (every worker incident so far started as a compressed brief), and streams
are one per issue, named for the branch.

v0.10.0 — gates learned from a colleague's fleet-orchestration process. **Types round**:
design plans a declarations-only task for any slice introducing domain shapes; implement
delivers types with `unimplemented` bodies, gates on a test-inclusive type-check, reviews
the declarations alone, and freezes reviewed signatures (changes escalate + land as
`deviation`). **Parity gate** for ports/migrations: design declares pre-authorized deltas;
review adds a fresh adversarial pass hunting unauthorized behavioral differences across the
whole source artifact. **Review arbitration**: reviewer briefs carry do-not-flag lists and
pre-rulings, killed findings are recorded so they aren't re-litigated, trivial diffs may be
coordinator-gated (recorded as `gate-decision`), and the internal not-ready→fix loop caps
at two rounds before surfacing. **Worker discipline** (model-tiers): self-sufficient
follow-up dispatches, amnesia symptoms → cold-spawn, environment repair is orchestrator
work, briefs point at source artifacts (the artifact outranks the digest) and name a vetted
reference implementation, validation via workspace-level scripts with a baseline run on
shared code. All new gates reuse the existing journal vocabulary — no new event types.

v0.9.0 — config-declared tooling: new **Code tooling** section (a library-docs
tool/MCP for dependency APIs + an LSP tool for symbol navigation — wired into implement's
reuse step, structured-debug's evidence sources, and worker briefs) and new **Thinking
lenses** section (map phases to lens skills to actually invoke; default remains
apply-the-idea-inline). Hardcoded `thinking-skills` plugin references removed — the two
review/design agents can't invoke skills, so their lens guidance is now inline; main-session
lens invocation is config-routed.

v0.8.0 — project bootstrap: the `setup` skill (interview → writes `.claude/shipgate.md`,
a generated `.claude/shipgate.json` sidecar, and initializes the flow journal) and the
flow journal itself — the authoritative per-branch position (phase, tasks, verifies, gate
decisions) that the orchestrator routes from instead of rescanning worklogs.

v0.7.1 — implement's reuse-before-writing step now also checks the dependency's own API
surface and same-module siblings before hand-rolling integration plumbing (pairs with
astrolabe v0.3.0's reuse ladder).

v0.7.0 — orchestration throughput: **design-ahead pipelining** (while workers implement
issue N, the orchestrator specs N+1 with the user — epic mode's stop now gates merge+build,
not design; queued designs are re-validated against what actually merged); **executive
autonomy mode** (config-declared, default `ask` — in `executive` the orchestrator makes and
records routine gate decisions, escalating only one-way doors, scope changes,
security-sensitive areas, and true 50/50s); **the ledger** (a project-wide, append-cheap
staging inbox for mid-flow learnings, triaged at Capture into config-declared promotion
targets — wiki pages, skills, CLAUDE.md, ADRs, personal memory — or dropped; Capture now
fires when review passes, never waiting on the merge); and **worker lifecycle** (reuse warm
workers via SendMessage for same-context follow-ups, spawn cold for different context,
retire degraded workers ~400k tokens / 4-6 rounds in and brief a fresh finisher off the
worktree state).

v0.6.0 — bug provenance: `structured-debug` gains a "trace the provenance" step — find
the commit that introduced the defect (`log -S` / `blame` / `bisect run` with the repro),
prove it counterfactually (repro fails at the commit, passes at its parent), name why it
slipped through, and report all of it in a comment on the tracker issue. New optional
**Bug provenance** line in the config's Forge & tracker section says where those comments
go (default: the bug's issue, via the forge CLI).

v0.5.0 — re-tuned for current-generation models (per Anthropic's Opus 5 prompting
guidance): review is coverage-first (reviewers report every finding scored with
confidence + severity; a separate coordinator pass filters — generation-time severity
floors made models silently drop real bugs); the verify gate is scoped to evidence, not
repetition (fresh command output per claim stays, re-check choreography goes — independent
fresh-context review remains a distinct, kept discipline); delegation is disciplined (one
agent when one suffices, fan-outs scale to the task, tiers phrased relative to the
orchestrator's model instead of hardcoding "opus = mid"); `effort` added as the second
cost lever (agent frontmatter + Workflow `opts.effort`, mechanical work at `low`); and
written deliverables (PRD/ADR/worklog/MR body) carry explicit length calibration.

v0.4.1 — docs/wording only, no behavior change: the review-feedback cycle is now defined
(in `review` — a loop between Review and Implement), the MR watcher is called an
integration rather than a hook (no Claude Code hook is involved), and the project-config
preamble duplicated across skills was slimmed to one canonical form.

v0.4.0 — optional **MR watcher** integration: a project-declared skill watches open MRs/PRs;
`review` registers blockers/follow-ups with it, and its events resume the flow at the
phase they unlock (comments → review-feedback, merge → capture, blocker merged → held work).

v0.3.0 — merged the work-fork's evolution back (model-tiers, richer workspace/epic/review
discipline) and made every project specific a `.claude/shipgate.md` config concern.
