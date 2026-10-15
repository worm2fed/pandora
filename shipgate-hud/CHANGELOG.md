# Changelog

All notable changes to the **shipgate-hud** plugin, newest first.

v0.3.0 — the publish gate. shipgate lets an MR/PR go up only after a `review-verdict` of
`ready`, or after the user's own publish `gate-decision`. That record must come after the last
`task-done`. journal.py checks this rule on the `mr-opened` event. That event is written after
the command ran, so nothing stopped `git push` itself.

A new `tool.check` hook on `Bash` now holds `git push`, `git subtree push`, `gh pr create`,
`gh pr new`, `glab mr create` and `glab mr new`. It accepts git's, gh's and glab's global
options before the subcommand. It accepts a program named by its path (`/usr/bin/git`). The
hook reads the line in one quote-aware pass. Outside quotes, a command starts after `&&`, `||`,
`;`, `|`, `&`, a newline, `(` or `)`. An unquoted `$(…)` or backtick run is read as a
command line too. A redirection ends a word, so `git push>/dev/null` is held. A command may
sit behind a `VAR=value` or a redirection. It may sit behind the shell words `if`, `then`,
`do`, `while`, `{`, `!`, `coproc`, `function <name>` and their kin. It may sit behind wrappers such as `env`, `sudo`, `timeout`, `nice`,
`xargs` or `eval`. Quoted text is one word and never a command. So a `grep` for the verb, or a
commit message that names it, is not held. A heredoc body counts only when it is fed to a
shell such as `bash` or `sh`. `command -v` only looks a name up and is not held.

The hook refreshes the position once. Then it applies journal.py's rule to the stream's
events. A reviewed stream passes. These cases pass too: a project without the sidecar, no
`journal.py` found, a session with no stream, and a session with no surface. An unreviewed
stream opens the engine's dialog with two choices: **Refuse** and **Let it through once**. A
journal that cannot be read opens the same dialog. A stored position does not pass while the
last refresh failed. Any other answer refuses the call. A dismissed dialog or a failed ask also
refuses it. The deny reason tells the model to record the review verdict, or to stop and ask
the user. It never tells the model to record the user's decision itself. The user decides at
the dialog. "Let it through once" covers that one call only. A worker subagent's publish
command is held in the same way. The hook writes nothing to the journal or the transcript. A
failure in the hook refuses a publish command through `.catch`. A failure passes any other
command.

The gate trusts the journal. journal.py has no actor authentication. So a verdict or a user
decision that the model appends itself still authorizes a publish. The gate is a net for a
forgetful model. It is not a boundary against a deliberate one.

Known limits: the gate does not hold `"$(…)"` inside double quotes, `sh -c '…'`, `eval "…"`,
`… | bash`, `ssh host git push` or `find -exec`.

Tests cover the command matcher on each spelling that must match. They also cover spellings
that must not match: `git pull`, `git pushd`, `gh pr list`, `gh pr view`, `glab mr list`,
`git stash push`, `command -v`, quoted text and a heredoc fed to `cat`. They cover the
authorization rule in the order journal.py applies it. They cover the hook with each answer, a
reviewed stream, no sidecar, no `journal.py`, no surface, a worker's call, no stream and a
failing journal.

v0.2.5 — a context ref is not the stream's worklog. A `flow-started` (or `phase-entered`,
`deviation`) event often cites an older slice's PRD and worklog as context; the HUD took any
`.worklog.md` ref from any event as this stream's worklog, so a new stream showed the previous
slice's Build Plan with every task unrecorded. Refs now count only from the events that commit
or work the artifact: `design-committed`, `design-queued`, `task-done`, `verify-run`,
`review-verdict`, `gate-decision`. A stream with no committed worklog shows no plan until
its design lands.

v0.2.4 — the HUD shows the stream this session drives, per session. It showed only the stream of
the checked-out branch, so a session driving a stream with no branch (an epic's planning stream)
saw whatever stream the checkout carried — in an umbrella, another session's work at another
phase. The status call now carries `--session=<$.session.id()>` and the HUD takes the stream
journal.py marks `session_match` (shipgate 0.14.5: the live stream this session last wrote to
itself), then the branch's as before; parallel sessions on one project each see their own. Still
one status call for a single repo. A `journal.py` older than `--session` refuses the flag as a
usage error (exit 2) and the HUD then asks by branch alone; any other failure is shown, not
papered over. Five tests; the umbrella test expects the session probe first.

v0.2.3 — anchored on the session root. The HUD took the session's directory from
`$.session.cwd()`, which follows the shell's `cd`: a turn that stepped into a nested repo moved
the sidecar lookup, the journal run and the branch along with it, and the pane then reported
"journal database not found" under that repo. Everything now hangs off `$.session.root()` —
where the session started, unmoved by a shell `cd` — the same anchor shipgate's hooks use;
only a relative path a tool was given still resolves where the tool resolved it. A refresh
with no project located yet (module state is empty after a plugin reload, while the stored
position and error survive it) now locates the project again and clears a stale error instead
of leaving an older module's message on screen. One test.

v0.2.2 — a stream checked out in a git worktree is found. The umbrella scan (0.2.0) skipped
dot-directories, so a branch checked out in a worktree under `.worktrees/` — where shipgate's
`workspace` skill puts one, beside the repos or inside one — was never probed and the pane said
there was no stream for exactly the work in progress. The scan now looks into each parent's and
each nested repo's `.worktrees/` (a repo, then its own worktrees, then the parent's). One test
extended.

v0.2.1 — a session opened inside a nested repo of an umbrella. The HUD looked for the
`.claude/shipgate.json` sidecar in the session directory only, so a session started in one
of an umbrella's service repos got the status brief from shipgate's hooks (which walk up to
the umbrella root) but a HUD that said there was no journal. The HUD now finds the sidecar
the way the hooks do — the session directory, then each directory above it — runs
`journal.py` in that project root (where it finds the sidecar and the database by itself),
reads the worklog and ADRs under it, and matches artifact writes against it (a path written
relative to the nested session directory, `../` included, is normalised first). In a plain
project nothing changes. Two tests.

v0.2.0 — umbrella checkouts. The branch came from `git rev-parse` in the session directory
only, so in an umbrella — a plain folder or a repo of its own with the real repos one level
down — the HUD found no branch (or the umbrella's own, which carries no stream) and drew
nothing. Now, when the session directory's branch matches no stream, the refresh asks each
nested repo (`*/.git`, `source/*/.git`, `packages/*/.git`, where setup looks; dot-directories
and `node_modules` skipped) for its branch, probes each distinct branch once, and shows the
most recently active stream among the matches — several nested repos may sit on branches
with streams, one live and the rest dormant. A single repo on a branch with a stream still
costs one status call. Also: the band's summary was cut with an ellipsis once it outgrew
the band's width, which on a normal terminal lost the verify time and the veto count; it
now wraps onto further rows at its ` · ` separators, no segment split, the `h: hud` button
staying on the first row.

v0.1.0 — first slice. A Claude Code mod (function hooks) that draws a shipgate flow's
position: a band above the prompt with stream, phase, tasks done, last verify and the count
of orchestrator decisions open to veto; a pane (`/hud`, or opened at session start) with the
phase timeline and three tabs — Flow (gate decisions, newest first, one-press Veto on the
orchestrator's), Plan (the worklog's Build Plan cross-checked against `task-done` and
`verify-run` events, unrecorded ticks flagged), Design (committed ADRs, the worklog's Design
section as Markdown). Reads the position through `journal.py status/log --json` and the
artifact files; writes nothing. Refreshes on journal appends, artifact writes, `/clear`
and `/resume`, and once a minute. Shows only the checked-out branch's stream; artifact homes
come from the sidecar. No-op in a project without `.claude/shipgate.json` and in a session
with no surface.
