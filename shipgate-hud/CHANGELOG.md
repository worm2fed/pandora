# Changelog

All notable changes to the **shipgate-hud** plugin, newest first.

v0.11.0 — the review board comes back after `/clear`, `/resume` and `/branch`.

**The board is kept in the store (HUD ADR 0011).** Before, the Review tab's board lived in
`$.state` only. `/clear`, `/resume`, `/branch` and a new process reset `$.state`, so the
user saw the verdict-only round instead of the board with its cards and Accept / Kill
buttons, although the stream was the same.
- On each capture and on each Accept or Kill, the HUD saves the stream's rounds, marks
  included, in the engine's store (`$.store`): a JSON file of the HUD's own under the
  user's Claude Code configuration directory. One key per project root and stream,
  `review-board:<root>:<stream>`; the value carries the shape tag
  `shipgate-hud.review-board-v1` and a save time. A board captured under no stream is not
  saved.
- The HUD keeps the newest 20 saved streams by save time and deletes the rest. Twenty
  streams of five rounds stay near 1 MiB of the store's 4 MiB.
- On the re-detection after `/clear`, `/resume` and `/branch` (the `classic.SessionStart`
  path and the lazy path) and at session start, a bound stream's saved rounds are loaded
  into the `review` atom when it holds none of that stream, and the newest round opens.
  A saved board of another stream is never loaded. A saved board of a stream whose flow is
  completed (`lifecycle: terminal`) is deleted and not restored; a dormant stream's is
  restored.
- A store call that fails, or a value of a shape the HUD does not know, is ignored: the HUD
  draws as before. Such a value is never deleted.
- The success-criteria ticks stay in `$.state` only.
- HUD ADR 0009 §3 ("the board stays in `$.state`") is superseded. The README's Review tab
  section and its "writes" paragraph say what the HUD saves and where.

**The dependency.** `plugin.json` declares shipgate `>=0.23.0`, as before. The golden
contract with journal.py does not change.

**Tests.** The store: a save on capture and on a mark, the restore after a `$.state` reset
and `session.start` for the same stream (the reload test now pins the restore instead of
the loss), the `classic.SessionStart` path after `/clear`, no restore for another stream, a
delete and no restore for a completed stream, the newest-20 cut, and an unreadable store
that draws the verdict-only round. The codec: a round trip, another shape tag refused, a
junk board dropped.

v0.10.0 — the publish dialog records your approval, and a stale `fixing` is no longer drawn as live.

**Approve publishing (#1, HUD ADR 0010).** shipgate 0.23.0 counts a user publish decision
only with the marker `source: dialog` or `source: shell`, and its PreToolUse hook refuses the
marker from the model (shipgate ADR 0015). Before, the dialog recorded nothing, so after
"Let it through once" the flow's `mr-opened` was still refused.
- The dialog has three answers: **Refuse**, **Let it through once** and **Approve
  publishing**. The third appears only when at least one hold is `Unreviewed`. An
  unreadable journal has no stream to record on, so it keeps the first two. A dismissed
  dialog, free text, or the approve label when it was not offered refuses.
- The question says what each passing answer records: "Approve publishing" records your
  approval on the named streams, and "Let it through once" records nothing.
- **Approve publishing** runs, for each distinct `Unreviewed` stream in textual order,
  `journal.py append --stream <s> --type gate-decision --actor user` with `gate: publish`,
  `decision: publish`, `raised_by: user`, `mode: ask`, `source: dialog` and a `question`
  that names the held commands. It runs through `$.process.run` in the project root, so no
  PreToolUse hook sees it. Then the line passes. A failed append still passes, as the user
  approved. After an append that succeeds, the HUD refreshes once.
- The approval lasts until the stream's next `task-done`, as every publish authorization
  does. So a later push of the same stream passes, and `mr-opened` is accepted.
- **Let it through once** records nothing, as before.
- The texts the model reads say only the user approves: "Approve publishing" in this
  dialog, or the user's own `!` command with `source: shell`. They never tell the model to
  record the approval.
- `REFUSE` and `ONCE` move from `register.tsx` to `publish.ts`, beside `APPROVE`.

**The HUD now writes one event.** The approval above is the only thing it writes. The README
says so, and it shows the `!` command for an approval from the prompt.

**Older journals.** A user publish decision recorded before shipgate 0.23.0 has no marker.
journal.py no longer counts it, so the gate holds that stream and asks again.

**A stale `fixing` (#14, HUD ADR 0008 amended).** On a production project's journal, 5 of 10
streams ended with findings at `fixing` after a `ready` verdict. The fix was never closed in
the journal.
- A folded `fixing` is stale when the newest verdict is `ready` and the entry's seq is below
  it. A new pure predicate, `isStaleFixing`, decides it.
- A card and the verdict-only round draw a stale entry dim as `fixing?`, never in the
  warning colour. The state cell takes its width from the drawn text.
- No count treats a stale entry as open: not the band's `review N open`, not a board's open
  count.
- **Changed behaviour.** A `fixing` recorded before a `not-ready` verdict now counts as
  open, because a fix round follows that verdict. Before, the band counted only a `fixing`
  after the last verdict of any kind.
- shipgate 0.23.0 refuses a `ready` verdict over an open `fixing`, so only older journals
  hold a stale one.

**README.** "After a shipgate release": the first `/reload-plugins` can load the HUD before
the new shipgate, and the dependency check then fails. A second reload loads it. The
Publish gate section describes the three answers and the boundary: a net against a flow
that forges approval through its tools, not a defence against deliberate circumvention.

**The dependency and the read floor.** `plugin.json` declares shipgate `>=0.23.0`, the first
version that checks the marker. The read floor stays 0.21.0: `MIN_SHIPGATE_VERSION` does not
change. With an older journal.py, the dialog's record carries a key that journal.py does not
check, and the old rule counts it.

**Tests.** The dialog: one stream, two streams in order, one stream held twice, an
unreadable journal with two answers, a failing or rejected append that still passes, and
"Let it through once" and a dismissed dialog that record nothing. The views: the predicate,
the band, a board's open count, a card and the verdict-only round with a stale and a live
entry, the `not-ready` case, and the state-cell widths. The golden journal is regenerated
from shipgate 0.23.0.

v0.9.0 — a round without a board tells what each finding was, keys carry labels, one finding in two cases is one finding, and a newer sidecar shows a warning.

**Finding text in a round without a board (#12, HUD ADR 0009).** Before, a round without a
board drew `<key>  <state>` lines and nothing else. The reader could not tell what a finding
was. The journal holds keys and states only, by design. The text is in the worklog's review
section. Now the HUD parses that section in `position.ts` (`parseReviewNotes`). The section
is every list item under a heading that starts with `Review round` or is `Rejected findings`,
at any level. It ends at the next heading at the same or a higher level that is no review
heading. A deeper heading stays inside it. A review heading inside the section keeps the
section at its first level, so a later sibling heading stays inside too. Fenced code is
inert. A fence closes only on its own marker character, in a run at least as long as the
one that opened it, as CommonMark reads it. An indented line continues its item. The HUD
removes control characters from each item before it collapses the whitespace. Each item
gives its first backticked `<path>:<line|?>` location (or none), its first sentence after
that location, and its whole text. Before the sentence, the HUD drops a parenthetical and
the separators `—`, `–`, `-`, `:`, `,`, `;` and `.`. A sentence with no letter or digit is
empty. `review.ts` now exports `parseLocation`, the one reader of the `<path>:<line|?>`
grammar, and the finding keys and the notes both use it. `Position` holds the notes as
`reviewNotes`. A new pure function in `review.ts`, `noteFor`, matches a key to an item in
three steps: the exact location (`./` dropped); a path tail on the same line, case folded;
then the label as a whole word of the item's text, in any case. A key that is no location
is its own label. In each step the first item in worklog order wins. The round then draws
one dim line under each matched key: the item's first sentence, indented by 2 and cut to the
pane's width. A key with no match stays bare. The match is display only. It changes no state
and no count.

**Labels.** shipgate 0.22.0 records an optional short label per finding key, and
`position --json` prints it on each folded entry. `FoldedDisposition` gains `label` (text or
null). The decoder reads an absent `label` key as null, because a 0.21.0 `journal.py` prints
none. This is the one exception to the rule that a missing key is an error. A label of
another type is still a `BadShape`, and the decoder removes control characters from a label.
The round draws the label dim after its key: `<key> · <label>`. The key keeps its room
first. The label gets only the room that the key and the state leave, and the HUD drops it
when fewer than 4 cells remain. The state is never cut. The drawn key has its control
characters removed. The match uses the key without them too, as the notes hold none. The
lookup in the folded map uses the raw key.

**The board across a reload (#12).** The issue reported a board that was gone after a plugin
reload. The board is in the `$.state` atom `shipgate-hud.review-v2` since 0.6.0, and the
engine keeps `$.state` across `/reload-plugins`. So the HUD changes nothing here. A new
register test pins it: it captures a board, keeps `$.state`, runs `session.start` again and
finds the board's card text. The test kit cannot load the module again or run `register`
again, and the test says so. The same test resets `$.state`, as `/clear` does, and finds the
board gone. The HUD does not copy the board into `$.store`. That would write a file under the
user's Claude configuration directory, kept across sessions, and the HUD writes nothing
today. A board from another session would also need its own staleness rule.

**One finding in two cases (#13, HUD ADR 0008 amended).** Two lenses that spell one path in
two cases gave two cards, and a disposition reached only one of them. Now pass 1 of
`dispositionsFor` has a case-folded step after the exact and short-location steps. A key
labels every card whose path and line match it in any case. The same-line path-tail step of
pass 1 and the line-agnostic step of pass 2 also compare paths case folded. The longest path
still wins. Pass 2 still gives each key to one card only.

**A newer sidecar.** The HUD now reads the sidecar's `version`. A new pure function in
`journal.ts`, `sidecarVersionOf`, gives that version when it is a safe integer higher than
`KNOWN_SIDECAR_VERSION` (1), else null. A new plain atom, `sidecarVersion`, keeps it. Each
refresh writes it from its one read of the sidecar, and only when it changed. The refresh
reads the sidecar as soon as it knows the project, before it looks for `journal.py`. So the
warning is current also when `journal.py` is not found. With no project it is null. While it is set, the pane draws one warning line above every view but
`Off`: `.claude/shipgate.json declares version 2; this HUD knows version 1 and reads only the
keys it knows`. The refresh still runs with the keys the HUD knows. It is never a failed
read. `PaneState` carries the version.

**The stored view.** The view's shape tag moves to `shipgate-hud.view-v6`, because
`Position` gains `reviewNotes` and a folded entry gains `label`. A stored v5 view reads as
absent, and the next refresh derives it again.

**The dependency and the read floor.** `plugin.json` declares shipgate `>=0.22.0`, the first
version that prints the label. The read floor stays 0.21.0: `MIN_SHIPGATE_VERSION` does not
change. With a 0.21.0 `journal.py`, the keys draw with no label. The README now says what
happens in a session that you opened before a shipgate release. That session keeps the old
shipgate in memory, so the dependency range refuses to load the HUD. An
organization-managed PreModelSwitch check can also block `/model` until `/reload-plugins`.

**Fix: a review launched by `scriptPath` carries its run id.** The review skill can launch
the workflow with a `scriptPath` alone: the skill's own file, or a repo-local copy. Before,
the HUD looked only for `shipgate-review` in the script, the script path and the name. Such a
launch held none, so the HUD did not note it. The board was still captured by its shape, but
its header read `run ?`. Now `isReviewLaunch` also takes a `scriptPath` whose last segment is
`review-workflow.js`. Another file name, such as `x-review-workflow.js`, does not count.
`isReviewLaunch` now takes the call's `script`, `scriptPath` and `name` by name.

**One helper for control characters.** `stripControl` moves from `review.ts` to `json.ts`.
The decoder of `journal.ts`, the review board, the review notes and the drawn keys all use
it.

**Tests.** The decoder tests cover the label as absent, null, text and text with control
characters, two `BadShape` labels, the golden labels, and `sidecarVersionOf` for higher,
known, lower, absent and non-integer versions. The position tests cover the review section's
grammar: the headings and their levels, a deeper heading, both fence markers, continuation
lines, nested items, the first location span, the parenthetical and the separators, and the
sentence stop outside backticks. They also cover control characters in an item, a review
heading inside an open section, a `~~~` line inside a backtick fence, leading commas and
periods, and an item that ends right after its location. The review tests cover each `noteFor` step, the order of the
steps, a hyphenated label, an empty label, and the #13 board with relative and absolute card
paths, a folded tail on the same line and the one-card pass-2 fallback. The view tests draw
SC-001: an exact key, a tail in another case, a free label, a labelled key and a key with no
match, at 100 and 40 columns, then a dropped label, a key with control characters and the
sidecar warning over each view. The review tests also cover `parseLocation`.
The register tests cover the sidecar warning through a refresh, the warning with no
`journal.py` found, SC-002, the board across a reload, and a `scriptPath` launch whose
board carries the result's run id. The review tests cover the `review-workflow.js` file
name. The test world can now change the sidecar it answers.

v0.8.0 — position carries the trace, finding states are live, a review without a board draws a round, and the HUD recovers after `/clear` without `classic.*` hooks.

**Detection after a session change (#8).** `/clear`, `/resume` and `/branch` move the session
to a new id and reset `$.state`. Before, only the `classic.SessionStart` handler detected the
project again. An organization-managed session skips `classic.*` hooks for user mods, so the
band and the pane stayed stale or empty until `/hud`. Now the HUD keeps the session id of its
last detection, and whether that detection found a project. On each clock tick, tool call
and prompt, it compares that id with the current one first. When they are equal and the last
detection found nothing (a project with no journal), it does nothing more: one
`$.session.id()` call, no process, no directory walk, no state write. When they are equal,
the last detection found a project, no refresh is running and the view now reads `Off`, the
state was reset under the same id: the HUD detects the project again, once. When the id
changed but the view is not `Off`
(the state was not reset), it notes the new id and does nothing else. When the id changed
and the view is `Off`, in a session that draws, it notes the id and detects the project
again; when it finds one, it refreshes. On a tool call or a prompt that detection runs off
the event's path (`$.clock.after(0, …)`): the event passes on at once, unchanged, and never
waits for a directory walk or a journal.py run. A session with no surface does nothing. A session whose id the engine cannot give is detected
once per module load. In a project with no sidecar, the detection is one directory walk per
session id and runs no process. The 60 s clock starts once per module load, by the first
detection that finds the project (session start, `/hud`, the publish gate or the lazy
check). The `classic.SessionStart` handler stays as the fast path. The new `tool.call` and
`prompt.submit` listeners always pass the event on, and a failure never blocks a tool call
or a prompt.

**The trace comes from `position` (HUD ADR 0007, amended).** shipgate 0.21.0 prints `trace`
in `position --json`: the newest verdict ranking, the newest design ranking (each with its
seq and time, the ranking verbatim) and the `signals-missing` deviations. The HUD decodes
them from there and runs no `log` command. A bound refresh now runs `status` and `position`
only. `decodeLog`, `traceOf`, `LogEvent`, the cut-log trace and the "trace not read" lines
are gone, and `Trace` loses `isLogCut`. A ranking that breaks journal.py's contract is still
drawn as "ranking unreadable".

**Live finding states (HUD ADR 0008).** shipgate 0.21.0 records a finding's state with a
`review-disposition` event as soon as the review decides it, and `position --json` prints
the fold per finding key as `dispositions`. A card now reads that fold, not the last
verdict's own map. It shows `fixing` (warning colour), `fixed`, `rejected` or `deferred` in
place of Accept and Kill. Your own mark still comes first. A state recorded before the board
was captured is not drawn on that board. The band counts a `fixing` finding as open.

**A tolerant key match.** The match now runs over the whole board, in two passes. Pass 1
gives each card the first of: the exact `file:line`, the short `file:line`, then a path tail
on the same line (the longest path wins). A `file:?` key matches in pass 1 only a card with
no line. Pass 2 is line-agnostic: a card with no state yet takes a path tail of its file on
any line, from the keys pass 1 left free. The longest path wins, then the nearest line (a
`?` key is the farthest, so the last choice), then the first key in map order. So a fix that
moved the line still reaches its card. A key that named one card exactly never labels
another card of the same file, and a pass-2 key labels one card only. `dispositionIn` is
replaced by `dispositionsFor`.

**A review round without a board (#5).** A project with `review: agents` never produces a
board, so the Review tab said "No review captured" after a `ready` verdict. Now, with no
board for the stream and a verdict or a folded state, the tab draws the round from the
journal: READ FIRST as before, then `round N · verdict <ready|not-ready> · <time>` (or
`round 1 · in progress` with no verdict yet), the verdict's note, one line per folded key
in key order with its state, then the success criteria. A key is cut to the pane's width;
its state is never cut. A board, when held, wins. With no board, the band shows
`review N open` only while N folded findings are `fixing` and were recorded after the last
verdict (all of them before the first verdict); otherwise it shows no review segment. A
`fixing` the newest verdict did not close is stale: the verdict is the round's final word.
The round's lines still show every folded key as it is.

**Ranking lines are never cut.** In a real pane, READ FIRST lines were too wide: the path
and three spelled-out labels did not fit, and the terminal cut the last label, which is the
one the line exists to show. Now the head line says the legend once
(`READ FIRST · graph · seq N · fix · churn · fan-in`, and the same for
`RISK RANKING · <source> · seq N · fix · churn · fan-in`). A suffix such as
`· from an earlier verdict` comes after it. The unavailable and unreadable head lines carry
no legend. Each file line holds the path, two spaces and the three labels as bare words:
`1. shipgate-hud/hooks/register.tsx  top · top · low`. When the line is too wide, the HUD
cuts the head of the path first (`1. …/hooks/register.tsx  top · top · low`), with a new
pure helper, `cutHead`. When even `…/` and the file name do not fit, the labels go on a
second, indented line. A head line that is too wide breaks at its ` · ` separators. The
labels are never cut. The same rule applies to a round without a board: a key loses its
head first, and its state is never cut. A card's state cell keeps its whole word at the
narrowest pane width (40 columns), and the meta text gives way. Tests draw each block at
40 and 120 columns.

**The dependency and the read floor.** `plugin.json` declares shipgate `>=0.21.0`. **The
read floor moves to 0.21.0.** The HUD no longer runs `log`, so an older `journal.py` cannot
give the trace. A `position --json` with no top-level `trace` key is `Outdated` with a new
sign, `MissingTrace` (`journal.py position --json printed no trace key`). The marker is
looked for before any other key, so the keys an older `position` lacks never read as a
`BadShape`. As for the status marker, the pane names the floor (0.21.0), the publish gate
is off, and the next refresh searches for `journal.py` again. The decoder also reads the
verdict's `note` (text or null) and `round` (an integer, 1 or more), and the folded
`dispositions` (a state outside the four is a `BadShape`).

**The stored view.** The view's shape tag moves to `shipgate-hud.view-v5`, because
`Position` gains `dispositions` and `Trace` loses `isLogCut`. A stored v4 view reads as
absent, and the next refresh derives it again.

**The golden contract.** shipgate's contract test regenerates `tests/fixtures.journal.ts`
for 0.21.0. `POSITION_GOLDEN` gains a `dispositions` scenario (a verdict, no board, three
folded keys, one of them `fixing`), and the `signals` scenario now carries its trace in
`position`. `LOG_GOLDEN` is gone. The new rows come first in the script, so every seq after
them moves up by seven.

**Tests.** The decoder tests cover every golden position, the `signals` trace, the
`dispositions` fold, the verdict's note and round, the `MissingTrace` sign, and the new
`BadShape` cases. The register tests cover a bound refresh with no `log` run, the trace
reaching the pane, a pre-0.21 `position`, and the session change with no
`classic.SessionStart`: through a tool call, a prompt and the clock tick, the tool's result
before the detection's status run, nothing more on the same id, no process for an id that
moves with the view still bound, no process in a project with no sidecar, nothing with no
surface, and one detection for an unknown id. The test world answers `$.state` from memory so a test can
reset it, and can move the session id. The review tests cover each match rule, the
line-agnostic fallback, a key taken by one card, a `file:?` key that labels one card only,
the nearest line and own-property keys. The view tests cover each card state, a state
recorded before the capture, the band count with `fixing` (a stale one left out with no
board), and the round without a board.

v0.7.0 — draws what shipgate 0.20.0 records: the risk ranking, the canon lens and a skipped signals block.

**The trace is read from the event log (ADR 0007).** shipgate 0.20.0 records a risk ranking on
`design-committed` and `review-verdict`, and writes a `deviation` with `kind: signals-missing`
beside a route-and-map entry that carried no signals. `position --json` prints none of these.
So a bound refresh now runs one more journal command, `log --stream <s> --json`, after
`position`. The HUD decodes the envelope strictly and picks three recorded values, verbatim:
- the newest `review-verdict` that carries `ranking`;
- the newest `design-committed` that carries `ranking`;
- every `deviation` of kind `signals-missing`.

A `ranking` is decoded to journal.py's contract: `source` required, `files` and each label
optional. One that breaks the contract (a row written before shipgate validated it) is drawn
as "ranking unreadable", never as a failed refresh. When the engine cuts the log's output (a
long stream), the position is still drawn, and the Flow and Review tabs say that the trace
was not read. Any other failed `log` run, or an envelope with another shape, is a failed
refresh the pane shows, as for any other run. The follow-up is in
ADR 0007: once `position` prints these values, the `log` call goes.

**Review tab.**
- A **READ FIRST** block comes before the rounds, and before "No review captured" when there
  is no board. Its head line names the source and the verdict's seq
  (`READ FIRST · graph · seq N`). Then each file comes in risk order:
  `1. src/golden.py · fix top · churn high · fan-in top`. A label with no value is `-`.
  Unavailable signals read `READ FIRST · signals unavailable (shallow) · seq N`. A ranking
  from a verdict older than the last one (a fix round that copied none) ends with
  `· from an earlier verdict`.
- A finding the **canon lens** reported carries a `canon` tag after its severity. The tag
  says the finding breaks a rule of the style canon, which is why it is held at MEDIUM or
  above (shipgate ADR 0012). A killed canon finding says `canon` in its head line. A round
  with no board has no lens information, so nothing is tagged there.

**Design tab.** The design's ranking is drawn the same way under the ADRs, as
`RISK RANKING · <source> · seq N`.

**Flow tab.** A route-and-map entry without signals shows one warning line under the header:
`route-and-map: no risk signals recorded · signals-missing deviation seq N`.

**The dependency.** `plugin.json` declares shipgate `>=0.20.0`. **The read floor stays
0.18.0.** A 0.18.0 or 0.19.0 `journal.py` prints the same `log` envelope, and its events
carry no ranking and no such deviation, so the new blocks stay empty.

**The stored view.** The view's shape tag moves to `shipgate-hud.view-v4`, because `Position`
gains `trace`. A stored v3 view reads as absent, and the next refresh derives it again.

**The golden contract.** shipgate's contract test adds a stream, `feature/golden-signals`,
at the top of the script: a route-and-map entry without signals (so `append` writes the
deviation), a `design-committed` with a regex ranking, and a `review-verdict` with a graph
ranking. The test also prints `log --stream <s> --json` for that stream and for
`feature/golden-flow`, as `LOG_GOLDEN` in `tests/fixtures.journal.ts`. The new rows come
first, so no event time moves; every seq after them moves up by seven.

**Tests.** There are new decoder tests for `decodeLog`, `traceOf` and `rankingOf`, including
the pre-0.20.0 object shape. The register tests cover the `log` run order, the trace reaching
the pane, and a failed or malformed `log` read. The view tests cover READ FIRST (ranked,
unavailable, unreadable, absent), the canon tag at 100 and at 40 columns, the Design ranking
and the Flow line. A hand-written review return with a canon lens, `REVIEW_RETURN_CANON`,
joins `tests/fixtures.review.ts`.

v0.6.2 — needs shipgate 0.19.0, and the golden contract covers what 0.19.0 changed.
- **The dependency.** `plugin.json` declares shipgate `>=0.19.0`. shipgate 0.19.0 binds a
  session whose only writes are the user's own decisions (`--actor user`): such a row records
  the writing session as `data.recorded_by`, and `status --session` counts it (shipgate ADR
  0010). Before, the pane said "This session drives no stream" for that session. Installing
  or updating the HUD now brings that shipgate.
- **The read floor stays 0.18.0.** 0.19.0 prints no new key, so the HUD cannot tell it from
  0.18.0. A lagging 0.18.0 `journal.py` is still read in full, without the new binding. The
  Outdated notice still names 0.18.0, the oldest `journal.py` the HUD can read.
- **The golden contract.** shipgate's contract test adds two scenarios to
  `tests/fixtures.journal.ts`:
  - a stream, `feature/golden-user`, whose session wrote only one `--actor user` gate
    decision. Its `status --session` answer binds through `recorded_by`;
  - a Build Plan task with a bold id, `- [x] **T002**: a bold id`, in the golden worklog
    found by name (shipgate issue #4).

  The new rows come first in the script, so no event time moves. Every seq after them moves
  up by two.
- **New tests.** No HUD code changed: journal.py computes the binding, and the contract test
  proves it. The register suite draws journal.py's golden answer for a session whose only
  write is the user row, asked with that session's id, and binds the stream it names. The
  Plan tab lists the bold task with its title. The decoder test reads the new status answer.

v0.6.1 — an older shipgate is a known state, not a read failure. 0.6.0 reads its facts from
shipgate 0.18.0. Beside an older shipgate (a project install that lags behind), the publish
gate read the mismatch as an unreadable journal and held every push. Now:
- **The dependency.** `plugin.json` declares shipgate `>=0.18.0`. Installing or updating the
  HUD brings a matching shipgate, and a shipgate outside the range keeps the HUD disabled.
- **The detection.** A `journal.py` older than 0.18.0 is detected for certain: argparse
  refuses `position`, or `status --json` lacks the `nested_matches` key that 0.18.0 always
  prints. The band then shows a one-line notice. The pane names the minimum version and
  says the publish gate is off, and the gate lets publishes through until shipgate is
  updated, as it does when `journal.py` is not found. The next refresh searches for
  `journal.py` again, so an update is picked up without a reload.
- **Failures still hold.** Any other failed read (a locked database, a crash, a contract
  mismatch) still holds the gate.

v0.6.0 — the right stream for each session, the right stream at the gate, and a typed core.
Needs shipgate 0.18.0 or newer.

**Binding (ADR 0004).** For a session that wrote to no stream, the HUD probed every nested repo
of an umbrella and showed the most recently active stream among them. Those checkouts are
shared with other sessions. So an idle session at an umbrella root showed another session's
work, and the label moved whenever an unrelated stream moved. Now:
- **The rule.** The nested branches go to journal.py in one `status` call. They bind only
  when they name exactly one live stream.
- **Unbound.** An unbound session shows no band. Its pane names the nearby live streams.
- **Issue worktrees.** A session opened inside an issue worktree still binds its one stream
  before its first write.
- **Failures.** A failed probe is a failure the pane shows. It never reads as "no stream".

**The publish gate (ADR 0005).** The gate held `git push` against whatever stream the band
showed, whatever repo the command targeted. Now:
- **Which branch.** The gate reads which branch the command publishes. It uses `git -C`, an
  earlier `cd`, a refspec, `gh pr create --head` or `glab mr create --source-branch`, or else
  the HEAD of the command's directory.
- **Which stream.** It checks that branch's stream. When the branch has no stream, or no
  single branch is named, it checks the session's own stream instead.
- **Every publish in the line.** It checks every publish command in a line, and holds the
  line when any of them holds. The dialog names every held command, because one "Let it
  through once" covers the whole line.
- **Literal strings.** A literal `sh -c`, `bash -c` or `eval` string is read.
- **Five ways a publish passed:**
  - a failed nested probe;
  - an exit 2 from a script file that went missing;
  - a cut search for `journal.py`;
  - a refresh that wrote between two reads;
  - the gate staying open after a plugin reload, until the next session start.

  Each of these now holds. The surface is read when the gate runs, and the gate decides from
  the value its own refresh returns.

**The journal computes the facts (shipgate ADR 0009).** The HUD kept TypeScript copies of
journal rules, and several copies disagreed with journal.py:
- the publish rule (a list-valued `decision` authorized here and was refused by `mr-opened`);
- the phase when none was entered (drawn as `workspace`);
- skipped phases (drawn as done);
- the Build Plan grammar (a `* [x]` task was missing here, while the Stop gate blocked on it);
- ADRs in a custom home (dropped);
- finished streams (drawn as live).

The HUD now reads `journal.py position` and draws the result:
- skipped phases as `↷`, and a phase entered again as `↺`;
- "no phase entered" when none was;
- a dormant or finished stream marked as such;
- the plan exactly as the Stop gate reads it.

The worklog fallback by name moved into journal.py, so the HUD no longer reads every
sibling stream's log.

**A typed core (ADR 0006, astrolabe adapted to a mod).**
- **One boundary.** journal.py's JSON is decoded in one place, strictly. A renamed key is an
  error, not a default. A golden file that shipgate's tests generate pins the contract on
  both sides.
- **Unions for states.** The view, the binding, refresh results, run failures, the publish
  command and the gate's verdict are closed unions.
- **Stored values.** They are decoded on read and versioned by shape tags, so this upgrade
  drops the v0.5 values and re-derives them.
- **The review board.**
  - Its findings come in three typed variants.
  - A junk entry in a review return no longer becomes a clickable card.
  - A stored board that does not decode is dropped. Before, it could break the band.
- **Exhaustive drawing.** Tabs, marks, severities and phase glyphs are drawn through total
  tables.
- **Property tests.** They cover the band width, the diagram grid, the review rounds, tick
  presses and the command scan. The band-width law found that band lines overflowed below 10
  columns, which is now fixed.

v0.5.1 — the worklog fallback leaves another stream's worklog alone. When a stream's events
name no worklog, the HUD scans the worklog home for one named for the stream's slug. Two
streams can share a slug: an epic stream `epic/x` beside a child whose worklog is
`x.worklog.md`. The epic's HUD then drew the child's Build Plan with none of its tasks done
(`0/12 done`), because the child's `task-done` events sit on the child's stream. The fallback
now skips a worklog that another live stream's events name. It reads each sibling stream's
log for that, and only after a slug-named worklog was found; a sibling whose log cannot be
read claims nothing. A completed stream is not in the status brief, so its worklog is not
protected.

v0.5.0 — diagrams drawn in the terminal. The Design tab drew a flowchart in the terminal as a
list: one line per layer, one line per edge. It now draws the chart as a picture made of
box-drawing characters (ADR 0003). Each node is a box with its label inside: square corners
for a rectangle, rounded for a round node or a circle, slanted for a diamond. Each edge is a
line from its source box to its target box with an arrowhead at the target: `─` for a solid
edge, `┄` for a dotted one, `═` for a thick one, no head for an open one. The edge label sits
on the line. The layers run left to right for `LR` (`RL` mirrored) and top to bottom for `TD`
(`BT` mirrored). An edge that spans more than one layer passes between the boxes of the layers
in between. Two lines that cross draw `┼`. A back edge that closes a cycle is not routed; it is
listed under the picture as `[b] ──► [a]`. A picture wider than the pane is drawn top to bottom
instead. When that is wider too, or the chart has more than 60 nodes, the old text form is
drawn under a dim note. The HUD also draws the text form when the picture is taller than 200
rows, has more than 200 edge legs, or has more than 40,000 cells; the note names the reason.
Desktop, mobile and vscode still get the SVG.

v0.4.1 — the Review board reads the verdict. **Accept** and **Kill** are now dim bracketed
buttons, like **Veto**. The card header is one line of three cells. The severity sits in a
fixed cell, one cell wider than `▎ BLOCKER`, so a gap always follows it. The meta text is cut
to the room left. The state comes last: the user's mark, the orchestrator's disposition, or
the two buttons. Under the header, the card has two full-width lines. The short `file:line`
comes first, dim, cut only when wider than the pane. The summary follows, wrapped. Killed and
below-floor findings use the same two lines under a dim head. The counts line packs at its
` · ` separators, so no line starts with one.

The tab keeps review rounds. Each captured return is a new round of its stream, numbered from
1. A stream keeps its five newest rounds. The rounds fold like the Design tab's sections. The
newest is open: a `▾ round N · run … · HH:MM` header over the full board. An older round is
one line, `▸ round N · run … · HH:MM · N survivors`. A press opens it and folds the other.
The open round's header is a button too. A press on it folds every round, and the criteria
stay. The next captured return opens the newest round again.
A round is known by its stream and its number, so a round with no stream never shares a key
with a stream's round. A mark stays with its round. A dropped round takes its marks with it.
The Accept and Kill prompt names the round. The band reads the newest round. Each round's
counts line ends with its own `open N`. The criteria follow once, after the rounds. Marks
stored by 0.4.0 are remapped onto the round that held them. Ticks set by 0.4.0 are not kept.
A return delivered again, with the same stream and run id, replaces its round in place and
keeps its marks.

Each success criterion is now a row. A tick button sits in a fixed cell. The bold id and the
whole text follow, and the text wraps to the pane width. Nothing cuts it.

The last `review-verdict` of the stream may record the criteria and the findings. The
orchestrator writes them as
`journal.py append --type review-verdict --data '{"verdict":"ready","criteria":{"SC-001":"met"},"dispositions":{"src/a.ts:42":"fixed"}}'`.
A `met` criterion shows `☑`. An `unmet` one shows `☒`. Any other status shows `☐`. A press
toggles the user's own tick over the journal's status. Each press changes the glyph. A press
that lands on the journal's status drops the override. A tick holds against the verdict it
was made on. A newer verdict shows its own status again. A disposition is keyed by the
finding's full or short `file:line`; a leading `./` is dropped. A key also matches by path
suffix on the same line: `hooks/register.tsx:573` matches a finding the workflow reports at
`/abs/root/shipgate-hud/hooks/register.tsx:573`. The card shows `fixed` in
green, `rejected` in red and any other value dim, in place of the buttons. The value is drawn
at most 12 cells wide. A board captured after the verdict ignores its dispositions. A finding
with a mark or a disposition is not open.

Tests cover the criteria status and the dispositions from the last verdict, the tick
overrides, the glyphs and the press on each status. They cover the wrapped text, the button
style, a disposed card and the cut header on a narrow pane. They cover the rounds: the fold,
a mark per round, the cap of five, the band and the round in the prompt. They cover the
round keys, the pruned marks, the remapped old marks, a stale tick and a late board. They
cover the folded header and a cut refresh.

A refresh that the person cut is no error now. A denied or interrupted Bash call can cut the
journal run that the HUD makes inside it. The pane showed `$.process.run(python3) aborted`
until the next refresh. Now the HUD keeps the position and shows nothing. Only the engine's
own rejection counts as cut: an `AbortError`, or a message that ends in `) aborted`. A
journal.py run that exits non-zero is always an error, whatever its message says. The publish
gate never passes on a position that a cut refresh left behind. It asks, and the dialog says
the refresh was cut. Any other failure still shows.

v0.4.0 — the Review board and the Design diagrams. The review workflow's return arrived once
in the transcript and then scrolled away. The worklog's diagrams showed as grey code.

The pane has a new **Review** tab. Hotkey `4` opens it. It is the default tab in the `review`
phase. A `tool.call` hook on `Workflow` notes each launch of the shipgate review workflow. It
keeps the call's tool-use id, the run id from the result and the stream shown at launch. A
`prompt.submit` hook reads each task-notification prompt. It takes the notification's
tool-use id, status, result and output file. A long return is cut in the notification text.
The HUD then reads the task's output file that the notification names. That must be an
absolute `…/tasks/*.output` path, at most 4 MiB. A failed stat, read or parse stores nothing
and shows no error. Only a result with the return's shape becomes the board. A
failed or killed run is not stored. When the tool-use id matches a noted launch, the board
gets that launch's run id and stream. Otherwise it goes under the current stream. The hook
never drops the prompt and never changes it. Any other notification passes untouched. A
session with no surface stores nothing.

The board starts with a counts line: found, deduped, candidates, survivors, killed, below
floor, refuters requested and reported, and unverified. The survivors follow, grouped by
severity: BLOCKER, HIGH, MEDIUM, LOW. Each survivor is one card. The card shows the severity,
the confidence, the verification and quorum, and the lenses. It shows `file:line`, with the
path cut to its last three segments, beside the summary. Each card has **Accept** and
**Kill** buttons. A press submits a plain prompt, not as the user. The prompt names the
finding by its position, severity, `file:line` and lens. It never carries the finding's text.
Accept asks the orchestrator to fix the finding. Kill asks it to record the finding as
rejected, with the user's reason. The card then shows the mark. Killed findings and findings
below the confidence floor follow, one line each. A dim line under the counts shows the run
id and the capture time. A return that names an `aborted` reason shows it as a warning there.

The tab ends with the PRD's success criteria as a checklist. The PRD is the one the stream's
`clarify-passed` event names. The ref must be relative and inside the project, with no `..`.
A press ticks or unticks a criterion. A tick holds for its stream only. The ticks and the
marks stay in the session only. `/clear` resets the pane state, the board included; the next
review run fills it again. A board stored for another stream is not drawn. The band adds
`review N open` while a board for the stream is held. N counts the survivors with no mark.
For an aborted run the band says `review aborted`.

The Design tab now draws diagrams (ADR 0002). A fenced `svg` block is drawn as `Svg` where
the surface draws one: desktop, mobile and vscode. The terminal shows it as `xml` code. The
HUD parses a fenced `mermaid` flowchart itself. The subset is `flowchart` or `graph` with a
direction and the node shapes `[ ]`, `( )`, `{ }` and `(( ))`. Edges are `-->`, `---`,
`-.->` and `==>`, with `|label|` or `-- label -->`. A `subgraph` is flattened. A `%%` comment
line is skipped. A doubled shape such as `[[ ]]` or `{{ }}` maps to the nearest supported
shape. A statement the HUD cannot read makes the whole block fall back to `mermaid` code. On
those surfaces the HUD lays the chart out into an SVG. In the terminal it
draws the chart as box-and-arrow text, one line per layer. Other Mermaid kinds show as
`mermaid` code. The prose around a block stays Markdown. The HUD starts no renderer process
and makes no network call.

Tests cover the review module (22), the capture hooks and the buttons (23) and the Review tab
on terminal and desktop (5). They cover the PRD criteria (3), the diagram module (20) and the
Design tab's diagrams on both surfaces (5).

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
