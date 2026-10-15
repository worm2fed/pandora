---
type: worklog
title: "Worklog: shipgate-hud slices 2 + 3 — publish gate, Review board, Design diagrams"
created: 2026-10-14
updated: 2026-10-14
tags:
  - worklog
  - shipgate-hud
status: implementing
prd: "./hud.md"
related:
  - "../adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
  - "../adr/0002-diagrams-drawn-by-the-hud.md"
---

# Worklog: shipgate-hud slices 2 + 3 — publish gate, Review board, Design diagrams

> Design + build plan companion to `./hud.md` (sections "Slice 2" and "Slice 3"). One
> branch, two versions: 0.3.0 lands when slice 2 is reviewed, 0.4.0 when slice 3 is.

---

# Design

## Approach

Pragmatic-balance, one philosophy: the slice 1 split (pure core, thin shell of hooks) is
kept. Each slice adds one pure module beside `position.ts` and a few hooks in
`register.tsx`. Every function that takes `$` stays in `register.tsx` (validate follows `$`
in one file only). No change under `shipgate/`.

## Architecture

```
shipgate-hud/
  hooks/register.tsx     + tool.check{Bash} (slice 2); + tool.call{Workflow},
                           prompt.submit (slice 3); the review atom; new actions
  hooks/position.ts      + publishAuthorization(events) → Position.publish (slice 2)
                         + parseCriteria(prd), prd ref from clarify-passed (slice 3)
  hooks/publish.ts       NEW pure (slice 2): publishCommandOf(command) → head | null
  hooks/review.ts        NEW pure (slice 3): parseTaskNotification, isReviewReturn,
                           toReviewBoard, shortPath, severity grouping
  hooks/diagram.ts       NEW pure (slice 3): splitFences, parseFlowchart, layoutFlowchart,
                           flowchartSvg, flowchartText
  hooks/views.tsx        + reviewTab, tab 4, band segment; designTab draws fences as
                           Svg / Code / text (slice 3)
  types/index.d.ts       + Position.publish, Position.criteria, ReviewState, Tab 'review'
  tests/publish.test.ts, tests/review.test.ts, tests/diagram.test.ts; register and
  views tests extended; fixtures gain a review notification and a diagram worklog
```

## Data flow

```mermaid
flowchart LR
  bash[Bash tool.check] --> head{publish command?}
  head -- no --> pass[next e]
  head -- yes --> refresh[refresh position]
  refresh --> auth{stream authorized?}
  auth -- yes / no stream --> pass
  auth -- no / error --> ask[ui.ask Refuse | Let it through once]
  ask -- once --> pass
  ask -- else --> deny[decision deny + reason]
```

### Slice 2 — the publish gate

- **`publish.ts`** — `publishCommandOf(command: string): string | null`, one quote-aware
  pass (round 1 rewrite). A `\` before a newline is whitespace. Outside quotes the line is cut
  at `&&`, `||`, `;`, `|`, `&`, newline, `$(`, backtick, `(` and `)`. A quoted run is one word
  and never a command (`grep "git push" f` publishes nothing). A heredoc body (`<<EOF` … `EOF`)
  is scanned as command lines only when the command it feeds is a shell (`bash`, `sh`, `zsh`,
  `dash`, `ksh`, `fish`, `source`, or `eval` anywhere in it). In each segment the words are
  split on whitespace; a leading run of assignments (`VAR=value`), redirections (`>out`,
  `2>/dev/null`), shell words (`if`, `then`, `else`, `elif`, `do`, `while`, `until`, `{`, `}`,
  `!`) and wrappers (`env`, `command`, `sudo`, `nohup`, `time`, `xargs`, `exec`, `builtin`,
  `timeout` + its duration, `nice`, `ionice`, `stdbuf`, `caffeinate`, `eval`, `doas`,
  `chronic`, with their value-taking options) is dropped; `command -v` / `-V` is a lookup and
  never a publish. The program is compared by basename with one leading backslash dropped
  (`/usr/bin/git`, `\git`). Then:
  - `git` → skip global options (`-C`, `-c`, `--git-dir`, `--work-tree`, `--namespace`,
    `--config-env`, `--super-prefix` take the next word unless written `=`) → `push`, or
    `subtree` … `push` → head `git push`. `git stash push` is not a publish.
  - `gh` → skip options (`-R` / `--repo` take the next word) → `pr` → skip options →
    `create` or `new` → head `gh pr create`.
  - `glab` → … `mr` … `create` or `new` → head `glab mr create`.
  Whole-word matching: `git pushd`, `gh pr list`, `git-push-helper` do not match. Returns the
  first head found. Known limits: `"$(git push)"` inside quotes, `cat <<EOF | bash`, and
  `sh -c '…'` are not held (deliberate spellings, outside the net).
- **`position.ts`** — `publishAuthorization(events): PublishAuthorization` =
  `{ authorized: boolean; by: 'review-verdict' | 'gate-decision' | null; at: string }`.
  Last `task-done` seq (0 when none); then, in seq order, a `review-verdict` with
  `data.verdict === 'ready'` or a `gate-decision` with `gate === 'publish'`,
  `raised_by === 'user'` and `String(decision).trim().toLowerCase() === 'publish'` whose seq
  is above it authorizes. Mirrors `journal.py` `_validate_mr_opened` / `_authorizes_publish`.
  `toPosition` sets `publish`.
- **`register.tsx`** — the hook:

  ```ts
  on('tool.check', { tool: 'Bash' }, async ($, e, next) => {
    const head = publishCommandOf(commandOf(e.input))
    if (head === null || !hasSurface) return next(e)
    if (!(await detect($))) return next(e)              // no sidecar
    await refresh($)                                    // one journal round trip
    const current = await read($, position)
    const error = await read($, lastError)
    if (current?.publish.authorized) return next(e)
    if (current === null && error === null) return next(e)   // no stream for this session
    const reason = holdReason(head, current, error)          // pure text
    let answer = REFUSE
    try { answer = await $.ui.ask(`${reason} Let it through?`, { options: [REFUSE, ONCE], header: 'publish' }) }
    catch { answer = REFUSE }                                // dismissed, -p, missing
    return answer === ONCE ? next(e) : { decision: 'deny', reason: denyReason(head, current, error) }
  }).catch(($, e, next) => (publishCommandOf(commandOf(e.input)) ? { decision: 'deny', reason: FAIL_CLOSED } : next(e)))
  ```

  `commandOf(input)` reads `input.command` when it is a string, else `''`. `REFUSE =
  'Refuse'`, `ONCE = 'Let it through once'`. The deny reason names the stream and says
  what it needs, and tells the model to record the review verdict or to stop and ask the
  user, whose decision is taken at the dialog; it never gives a recipe for a user-actored
  event (security review round 1). The pass needs `lastError === null` and
  `publish?.authorized === true`; `script === null` (journal.py not located) passes (FR-022).
  No `$.ui.log`, no journal write. `script === null` (journal.py not found) →
  `refreshOnce` sets `lastError` and position null → the hook asks (an error holds). The
  `.catch` carries a 1 s grace; it only runs the pure matcher.
- Budget: the hook's 10 s budget counts its own time only; the clock stops inside `next(e)`
  and every `$` call (`HookBudget`, "a `$.clock` wait excepted"). So the refresh (≈300 ms of
  `$.process.run`) and the dialog wait cost it nothing; only the pure parsing counts.

### Slice 3 — the Review board

- **Capture.** `tool.call { tool: 'Workflow' }`: after `next(e)`, when `e.script`,
  `e.scriptPath` or `e.name` contains `shipgate-review`, note `{ toolUseId: e.tool_use_id,
  runId }` with `runId` from `/Run ID: (wf_[\w-]+)/` on the result text (module map, bounded
  to the last 8). `prompt.submit`: when `e.origin.kind === 'task-notification'`,
  `parseTaskNotification(e.text)` reads `<tool-use-id>`, `<status>`, `<result>`; the result
  JSON is HTML-unescaped (`&lt; &gt; &amp; &quot; &#39;`) then parsed. Accept when the id is a
  noted launch, or `isReviewReturn(json)` (arrays `survivors`, `killed`, `belowFloor` and an
  object `counts`). Store `toReviewBoard(json, runId, stream, now)` in the `review` atom
  (`stream` = the current position's stream, or `null`). Always `return next(e)`; both hooks
  `.catch(($, e, next) => next(e))`.
- **`review.ts`** types (in `types/index.d.ts`):

  ```ts
  type ReviewFinding = { severity: 'BLOCKER'|'HIGH'|'MEDIUM'|'LOW'|string; confidence: number;
    file: string; line: number | null; summary: string; lenses: string[];
    verification: string; quorum: string; risk: string | null }
  type ReviewBoard = { stream: string | null; runId: string | null; at: string;
    counts: Record<string, number>; coverage: Record<string, unknown>;
    survivors: ReviewFinding[]; killed: ReviewFinding[]; belowFloor: ReviewFinding[]; lensesRun: string[] }
  type ReviewMark = 'accepted' | 'killed'
  type ReviewState = { board: ReviewBoard | null; marks: Record<string, ReviewMark>; ticks: string[] }
  ```

  `marks` is keyed by the survivor's index as a string; `ticks` holds SC ids. Survivors
  keep the return's order (severity, confidence, risk) and are grouped by severity in the
  view. `shortPath(file)` keeps the last three segments.
- **Criteria.** `artifactRefs` gains `prd`: the `clarify-passed` event's `data.prd` (safe
  ref rule). `refreshPosition` reads it; `parseCriteria(text)` takes `- **SC-NNN** — text`
  lines under `## Success criteria` (every such section, so a multi-slice PRD lists all).
  `Position.criteria: { id: string; text: string }[]`.
- **Views.** `Tab` gains `'review'`; `defaultTab('review') === 'review'`; tab 4 hotkey `4`.
  `reviewTab`: a counts line (`found · deduped · candidates · survivors · killed · below
  floor · refuters requested/reported · unverified`), then for each severity present a dim
  header and one card per survivor: line 1 `▎ SEVERITY  confidence%  verification quorum
  lenses`, line 2 `file:line` (short) + summary, with `Accept` / `Kill` buttons (keys
  `accept-<i>`, `kill-<i>`) or the mark when set. Then `KILLED` one-liners (`severity
  file:line summary · quorum`) and `BELOW FLOOR` one-liners. Then `SUCCESS CRITERIA`: one
  Button per criterion (`sc-<id>`), `☑`/`☐` + id + text, press toggles the tick. No board
  → `No review captured for <stream> yet (phase <phase>).`; a board for another stream is
  not drawn. Band: `review N open` while a board for the stream exists (N = survivors
  without a mark).
- **Prompts** (plain, no `asUser`): Accept → `The user pressed Accept on review finding N
  of M (SEVERITY, file:line, lens L) in the shipgate HUD for stream S: fix it in the
  implement round and record it under the worklog's review round.` Kill → `… pressed Kill
  … : treat it as rejected, ask the user for the reason, record it under the worklog's
  Rejected findings, and do not fix it.` Never the summary, why or fix text.
- `/clear` resets `$.state`, the `review` atom included (slice 1's `classic.SessionStart{clear}`
  hook exists for that); the next review run fills the board again. The view's stream check
  hides a board that belongs to another stream (round 2 correction).

### Slice 3 — Design diagrams (ADR 0002)

- **`diagram.ts`**: `splitFences(markdown)` → `({ kind: 'markdown'; text } | { kind:
  'fence'; lang: 'mermaid' | 'svg'; source })[]`, only `mermaid` and `svg` fences split
  out. `parseFlowchart(source)` → `{ direction: 'LR'|'TD'|'TB'|'RL'|'BT'; nodes: { id;
  label; shape }[]; edges: { from; to; label; style: 'solid'|'dotted'|'thick'|'open' }[] } |
  null` (null when the first line is not `flowchart`/`graph`, or nothing parses).
  `layoutFlowchart(g)` assigns each node a layer (longest path from a source; cycles broken
  by first-seen order) and an index in its layer. `flowchartSvg(g, layout)` → an `<svg>`
  string: rounded rects 120×36 (width grows with the label), 40 px gaps, lines with a
  marker arrowhead, edge labels at the midpoint, LR/TD orientation. `flowchartText(g,
  layout)` → one line per layer: nodes as `[label]`, joined with `   `, and between layers
  the edges as `[A] ──label──► [B]` lines (one per edge). Labels are drawn at most 24 cells.
- **`views.tsx`** `designTab`: each open section's markdown goes through `splitFences`;
  markdown chunks are `Markdown`, a fence is `diagramOf(ui, fence, title, columns)`: `svg`
  → `Svg` (`source`, `alt: title`, source capped at 131072 chars) when `ui.Svg` exists,
  else `Code` (`language: 'xml'`); `mermaid` → `parseFlowchart` ok → `Svg` from
  `flowchartSvg` when `ui.Svg` exists else `Text` lines from `flowchartText`; not a
  flowchart → `Code` (`language: 'mermaid'`). `Ui` gains `Code` and `Svg?`.

## Data model

See the types above; `Position` gains `publish: PublishAuthorization` and
`criteria: Criterion[]`; `PluginState['shipgate-hud']` gains `review: ReviewState`.

## Reference implementation

Slice 1's `register.tsx` (the guard order `hasSurface` → `detect` → `refresh`, the
`.catch` on every gating hook) and `position.ts` (pure parsing with `asRecord` /
`asString`); the test world in `tests/world.ts`. `$.ui.ask` under `claude plugin test`:
the test answers `on('tool.call', { tool: 'AskUserQuestion' }, () => ({ result: { answers:
{ [question]: label } } }))`; a `{ deny }` rejects as "dismissed" (probed 2026-10-14).
`$.tool.check({ tool: 'Bash', input: { command } })` drives the hook from a test.

## CLAUDE.md / impact-map compliance

- `shipgate/` untouched (review: `git diff --stat main -- shipgate/` empty).
- Hooks are security-sensitive: every new hook has `.catch`; the publish hook fails closed
  for a publish command; no new process or network call; the diagram renderer is pure.
- Public repo: fixtures use generic paths (`src/app.ts`), generic streams and summaries.
- Versions in lockstep with the marketplace entry; release notes in CHANGELOG only.

---

# Build Plan

Tasks are ordered by dependency. `[P]` = independent of its siblings (parallelizable).

## Slice 2 — publish gate (0.3.0)
- [x] T100 — `publish.ts`: `publishCommandOf` — file(s): `shipgate-hud/hooks/publish.ts` — done when: T101 passes
- [x] T101 — tests for T100: every spelling in FR-020 recognised; `ls`, `git pull`, `git pushd`, `gh pr list`, `gh pr view`, `glab mr list`, `echo pushed` not — file(s): `shipgate-hud/tests/publish.test.ts` — done when: tests fail first, then pass
- [x] T102 — `position.ts`: `publishAuthorization`, `Position.publish`; tests (ready verdict after task-done, before it, user publish decision, orchestrator publish decision, none) — file(s): `shipgate-hud/hooks/position.ts`, `shipgate-hud/types/index.d.ts`, `shipgate-hud/tests/position.test.ts` — done when: tests fail first, then pass
- [x] T103 — `register.tsx`: the `tool.check` hook with `.catch`; register tests per SC-011 — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts` — done when: `claude plugin validate` lists `tool.check{tool=Bash}` with `.catch`; tests fail first, then pass
- [x] T104 — docs + version 0.3.0: CHANGELOG entry, README feature paragraph (no release notes), `plugin.json` + marketplace entry — file(s): `shipgate-hud/CHANGELOG.md`, `shipgate-hud/README.md`, `shipgate-hud/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: `claude plugin validate` passes on both
- [x] T105 — full `/security-review` on the slice 2 diff; findings fixed or recorded — done when: SC-012
- [x] T106 — live check SC-013 in this repository — done when: observed and noted here

## Slice 3 — Review board (0.4.0)
- [x] T200 — `review.ts` + types: `parseTaskNotification`, `isReviewReturn`, `toReviewBoard`, `shortPath`; fixture notification; tests — file(s): `shipgate-hud/hooks/review.ts`, `shipgate-hud/types/index.d.ts`, `shipgate-hud/tests/review.test.ts`, `shipgate-hud/tests/fixtures.review.ts` — done when: tests fail first, then pass
- [x] T201 — `register.tsx`: `tool.call{Workflow}` launch note, `prompt.submit` capture, `review` atom, Accept / Kill / tick actions; register tests (capture by id, by shape, a non-review notification untouched, the prompt text and no `asUser`) — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts` — done when: validate lists both hooks with `.catch`; tests fail first, then pass
- [x] T202 — `position.ts`: `prd` ref from `clarify-passed`, `parseCriteria`, `Position.criteria`; tests — file(s): `shipgate-hud/hooks/position.ts`, `shipgate-hud/tests/position.test.ts` — done when: tests fail first, then pass
- [x] T203 — `views.tsx`: Review tab (groups, cards, buttons, killed, below floor, SC checklist), tab 4, default in `review`, band segment; views tests on terminal + desktop — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx` — done when: tests fail first, then pass

## Slice 3 — Design diagrams (0.4.0)
- [x] T210 [P] — `diagram.ts`: `splitFences`, `parseFlowchart`, `layoutFlowchart`, `flowchartSvg`, `flowchartText`; tests (subset, labels, shapes, subgraph, comments, a sequenceDiagram → null, a cycle) — file(s): `shipgate-hud/hooks/diagram.ts`, `shipgate-hud/tests/diagram.test.ts` — done when: tests fail first, then pass
- [x] T211 — `views.tsx` Design tab: fences as Svg / Code / text per surface; views tests (SC-021) — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx`, `shipgate-hud/tests/fixtures.ts` — done when: tests fail first, then pass
- [x] T220 — docs + version 0.4.0: CHANGELOG, README (Review tab, diagrams; no release notes), `plugin.json` + marketplace — file(s): `shipgate-hud/CHANGELOG.md`, `shipgate-hud/README.md`, `shipgate-hud/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — done when: validate passes on both
- [x] T221 — full `/security-review` on the slice 3 hook diff — done when: SC-023
- [x] T222 — live check SC-024 — done when: observed and noted here

## 0.4.1 — criteria and buttons (user feedback round, 2026-10-15)
- [x] T230 — Accept / Kill / tick buttons drawn like Veto (no `plain`); criterion text wrapped beside its tick — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx` — done when: tests fail first, then pass
- [x] T231 — `Position.criteriaStatus` from the stream's latest `review-verdict` `criteria` map; `☑` met, `☒` unmet, local press overrides — file(s): `shipgate-hud/hooks/position.ts`, `shipgate-hud/types/index.d.ts`, `shipgate-hud/hooks/views.tsx`, tests — done when: tests fail first, then pass
- [x] T233 — `Position.dispositions` from the latest `review-verdict` `dispositions` map; a card shows `fixed` / `rejected` instead of the buttons; `review N open` counts neither marked nor disposed — file(s): `shipgate-hud/hooks/position.ts`, `shipgate-hud/hooks/views.tsx`, `shipgate-hud/types/index.d.ts`, tests — done when: tests fail first, then pass
- [x] T234 — card header as three cells (severity fixed, meta truncating, buttons non-shrinking) so a long lens list never pushes the severity to the next line — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx` — done when: a 60-column pane keeps the severity on the first line
- [x] T235 — review rounds kept (up to 5 per stream), drawn as collapsible sections, newest open; marks per round; band and counts from the newest — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/hooks/review.ts`, `shipgate-hud/hooks/views.tsx`, `shipgate-hud/types/index.d.ts`, tests — done when: tests fail first, then pass
- [x] T236 — the open round's header is a button that folds it (all folded, criteria stay); a capture reopens the newest — file(s): `shipgate-hud/hooks/views.tsx`, `shipgate-hud/hooks/register.tsx`, tests — done when: tests fail first, then pass
- [x] T237 — a refresh aborted by the hook's own cancellation (the user denied or interrupted a Bash call) writes no error and keeps the position — file(s): `shipgate-hud/hooks/register.tsx`, `shipgate-hud/tests/register.test.ts` — done when: tests fail first, then pass
- [x] T238 — a disposition key matches by path suffix (the workflow reports absolute paths; the orchestrator writes repo-relative keys) — file(s): `shipgate-hud/hooks/views.tsx`, tests — done when: tests fail first, then pass
- [x] T239 — card body as full-width lines (location, then the wrapped summary); the counts line packed at its separators — file(s): `shipgate-hud/hooks/views.tsx`, tests — done when: a 60-column pane shows the full location and summary
- [x] T232 — docs + version 0.4.1: CHANGELOG, README, `plugin.json` + marketplace — done when: validate passes on both

## Traceability
- FR-020 → T100, T101
- FR-021, FR-022, FR-023, FR-024, FR-025 → T102, T103
- FR-026 → T104
- FR-030 → T200, T201
- FR-031, FR-032, FR-034 → T203, T201
- FR-033 → T202, T203
- FR-035, FR-036 → T210, T211
- FR-037 → T220
- SC-010, SC-011 → T103; SC-012 → T105; SC-013 → T106
- SC-020 → T200–T203; SC-021 → T210, T211; SC-022 → T201; SC-023 → T221; SC-024 → T222
- FR-031, FR-032, FR-033, FR-034 (0.4.1) → T230, T231, T233, T234, T235, T236, T237, T238, T239, T232

## Deviations & notes (filled during implementation)
- 2026-10-14 — T100–T104, T200 (pure part) and T210 built by three parallel Opus workers; the
  orchestrator reviewed the diffs, ran the verify gate (validate ×2, 152 tests, tsc, empty
  `shipgate/` diff) and recorded `task-done`. T200's types live in `review.ts` until T201 moves
  them to `types/index.d.ts` (another worker owned that file in the same round).
- 2026-10-14 — `publish.ts` parses quotes after all: a quoted run is one word (`git -C "my dir"
  push` matches) and its text is read as a line of its own (`sh -c 'git push'`, `echo "git
  push"` are held, FR-020). `)` is a separator too, so `$(git push)` matches. Observed live
  (SC-013): the gate held the worker's and the orchestrator's own Bash calls whose heredoc
  mentioned `git push` on a line of its own; the dialog opened, Refuse denied with the reason
  the model repeated. The false positive is kept as designed and flagged for veto.
- 2026-10-14 — no test of the `.catch` fail-closed path: `detect` and `refresh` swallow their
  own errors, so the hook cannot be made to throw from the test world. The handler runs only
  the pure matcher.

- 2026-10-15 — T201–T203 and T211 built by two parallel Opus workers on the shared working
  tree (targeted edits only on `views.tsx`, `views.test.tsx`, `fixtures.ts`); verify gate run by
  the orchestrator: 241 tests, validate, tsc, empty `shipgate/` diff.
- 2026-10-15 — `$.ui.resolve` completes the element table: the terminal hands out an `Svg`
  constructor that draws an empty fragment, so "when `ui.Svg` exists" is always true. The
  Design tab detects support by building one element and checking its `type` (`drawsSvg`).
- 2026-10-15 — T201–T203 tests were written after the code (the shared tree could not be
  stashed to show them fail); T211's four tests failed first.
- 2026-10-15 — `prompt.submit` takes a matcher on `origin.kind`, so the capture hook is
  `prompt.submit{origin has {kind=task-notification}}`; a composer prompt with the return
  shape is not captured (tested).

- 2026-10-15 — live check after the 0.4.0 commit: the Review tab stayed empty on this stream's
  own review run. The engine cuts a long `<result>` inside the task-notification text (8 KB of
  22 KB) and ends it with `… (truncated N chars, full result in <output-file>)`, so the JSON
  never parsed and `isReviewReturn` was false (verified by running the session's real
  notification through `review.ts`). The capture now reads the task's output file (guarded
  absolute `…/tasks/*.output` path, ≤ 4 MiB) and takes its `result`. The fixtures carried a
  complete `<result>`, which is why 261 tests did not catch it; a truncated fixture is added.

## Review round 1 — slice 2 (2026-10-14)

Three-lens review workflow (`wf_6649b8a8-956`, opus finders, high-only refuters): 40 raw → 28
deduped → 15 above the floor, 0 killed (the three HIGHs held 0/2), 13 below floor. Full
`/security-review` sub-task on the hooks diff: 2 MEDIUM (0.85, 0.75). The live gate held the
reviewers' own greps and probes three times in a row (the dialog opened on command lines that
only mentioned the verb), which the user raised. One fix round, all on the slice 2 worker:

- S1/S3 HIGH `publish.ts:141-142` + security 2 — the deny reason taught the model a
  `--actor user` recipe that does not even set `raised_by` (journal.py's `--actor` fills the
  actor column only), and a model can append the authorizing event itself → the recipe is
  gone; the deny text says: record the review verdict, or stop and ask the user, whose
  decision is taken at the dialog. The trust limit (journal.py has no actor authentication;
  the gate is a net for a forgetful model, not a boundary against a deliberate one) is in the
  PRD's slice 2 constraints.
- S2 HIGH `publish.ts:70` — `gh pr new` is an alias of `gh pr create` → accepted.
- S5/S6/S9 MEDIUM + security 1 — shell words and wrappers hide the command (`if …; then git
  push; fi`, `do git push`, `{ git push; }`, `! git push`, `timeout 60 git push`, `nice`,
  `eval`, `doas`, `stdbuf`, a leading redirection) → dropped at the start of a segment like
  the existing wrappers; `command -v` is a name lookup and never a publish.
- S7/S8 MEDIUM `publish.ts:62` — a program by path or escaped (`/usr/bin/git`, `\git`) →
  the basename is compared, one leading backslash stripped.
- S10 MEDIUM `publish.ts:14` — a `\` line continuation cut the command in two → joined as
  whitespace before the scan.
- S11/S14 LOW — `--config-env`, `--super-prefix` take a value, bare `--exec-path` does not;
  `env -C`, `env -S`, `exec -a` take a value; `git subtree push` is a publish.
- S4 MEDIUM `register.tsx:625` — journal.py not found asked instead of passing (FR-022) →
  passes when the script was not located; test added. Its also-reported stale-position
  risk → the pass needs `lastError === null` and `publish?.authorized === true`.
- S13 LOW — no test of the no-surface pass and the subagent hold → added.
- S12/S15 LOW — CHANGELOG claimed "any option in any position" and ran 60-word sentences
  → reworded (global options before the subcommand), split per STE-80.
- User-raised (recorded as a user gate-decision) — quoted text is one word and never a
  command; heredoc bodies count only when fed to a shell; `echo "git push"`, `sh -c '…'`,
  greps and doc-writing heredocs pass.

## Rejected findings — slice 2 round 1
- below-floor `register.tsx:618` (55) "a `$.tool.check` query from another plugin opens the
  dialog" — kept as a limit: `tool_use_id` is absent on a query, and the test driver's
  `$.tool.check` is a query too, so gating on it would make the hold untestable.
- below-floor `register.tsx:627` (50) "a subagent's call still asks" — FR-025 by design: a
  worker's push is the one the net is for; the question reaches the person's dialog.
- below-floor `register.tsx:630` (50) "asks before the verdict beneath; core may ask again"
  — by design: the hold is the gate's own question, the permission prompt is the engine's.
- below-floor `register.tsx:620` (50) "fails open with no surface" — PRD assumption, flagged
  for veto.
- below-floor `types/index.d.ts:46` (55) "`by` and `at` unread" — kept for the Review tab.
- below-floor `register.tsx:623` (45) "joining another hook's refresh counts against the
  budget" — a refresh is ≈300 ms against a 10 s budget.
- below-floor `register.tsx:466` (40) "`hasSurface` is false until session.start after a
  reload" — the engine runs session.start again after a reload.
- below-floor `publish.ts:130` (30) "stderr and the stream name reach the model" — the
  stream name is the journal's, the stderr is journal.py's; both are the HUD's own data.

## Review round 2 — slice 2 (2026-10-15)

Scoped re-review of the fix round, one reviewer (opus, all lenses), about 170 probe lines run
through a copy of the scanner: every F1–F9 fix CONFIRMED in the code with file:line; nothing
in the scanner throws on any input tried (empty, lone quote, lone `<<`, wrapper as the last
word, a 200 KB line in 23 ms). Suggested verdict: ready, with two MEDIUM scanner gaps to
close first. Final round, same worker:

- MEDIUM (95) `publish.ts:126` — an unquoted `$(…)` or backtick inside the command (`git -C
  $(pwd) push`) ended the segment, so `push` started a new one → the substitution is read to
  its matching close, appended to the word, and scanned on its own too.
- MEDIUM (95) `publish.ts:236` — a redirection touching the verb (`git push>/dev/null`) made
  the word `push>/dev/null` → an unquoted `<`/`>` ends the word and drops its target; a
  spaced `> out git push` is held too.
- MEDIUM (90) — `"$(git push)"` in double quotes and `eval "git push"` pass while the docs say
  "never a command" → listed as known limits in the CHANGELOG and README (the net, not a
  boundary); not scanned, because holding every quoted mention is the false positive the
  user vetoed.
- LOW — `function`/`coproc` as shell words; a `#` comment skipped; heredoc terminator compared
  exactly (tabs stripped for `<<-`); long wrapper options (`sudo --user`, `env --chdir`,
  `timeout --signal`, `xargs --max-args`); the heredoc test that passed for the wrong reason
  (quoted verb in the body) made unquoted; FR-020's "any options in any position" replaced
  and split per STE-80.

## Rejected findings — slice 2 round 2
- LOW (40) "`.catch` runs the beneath chain a second time" — speculative; the same `.catch`
  pattern is on every gating hook since slice 1 and the d.ts recommends it.
- LOW (30) "the dialog wait counts against the budget" — no: `HookBudget` stops the clock
  inside every `$` call (recorded in the Design section).
- LOW (35) "`hasSurface` resets on reload" — the engine runs `session.start` again after a
  reload (slice 1 note); kept as is.
- LOW (75) "`\`+newline join damages a `<<'EOF'` body" — rare, and the result is a missed
  hold on a line that fed a shell nothing; kept as a limit.
- LOW (90) `ssh host git push`, `find -exec git push`, `watch`, `parallel`, `echo … | bash` —
  known limits, listed in the docs.
- LOW (85) no test of a throw inside the hook (`FAIL_CLOSED`) and of the stale-position hold
  — the test world cannot make `detect`/`refresh` throw; `refreshPosition` never returns a
  position with an error; the guard is one boolean. Kept as a gap.

## Review round 1 — slice 3 (2026-10-15)

Three-lens review workflow (`wf_bec47d4a-89d`, opus finders): 44 raw → 33 deduped → 22 above
the floor, no BLOCKER or HIGH, 6 MEDIUM, 16 LOW, 11 below floor; no refuters spent. Full
`/security-review` on the two new hooks: nothing at or above its threshold; two optional
hardenings adopted. One fix round, split between the two slice 3 workers:

- S1/S5 MEDIUM `register.tsx:708` — an id-matched launch with no parsable return replaced
  the board with an empty one → a board is stored only when the result has the return shape
  and the status is not failed or killed; the launch only stamps the run id and the stream.
- S2/S21 MEDIUM `views.tsx:352` — an SVG over the element's limit was cut mid-markup → over
  the limit the non-picture form is drawn with a "too large" line; never sliced.
- S3 MEDIUM `review.ts:101` — an aborted run (`aborted` on the return) drew as a clean zero
  board → `aborted` carried, drawn as a warning, band says `review aborted`.
- S4/S20 MEDIUM `register.tsx:711` — ticks keyed by bare SC id carried across streams, and
  duplicate ids across PRD sections collided → ticks keyed `<stream>:<id>`, criteria deduped.
- S6 MEDIUM + security hardening `review.ts:151` — severity, file and lenses went into the
  Accept/Kill prompt as free text → severity bound to the four labels, file and lens
  whitelisted by pattern, control characters stripped.
- S18/S19 LOW — the board was filed under the stream current at return time and stamped with
  `Date` → the launch records the stream; `at` from `$.clock.now()`.
- S8/S9/S13 LOW — `shortLocation`, the JSON helpers and the cut helper each lived twice →
  one each (`review.ts`, new `hooks/json.ts`, `diagram.ts`).
- S12/S14/S17/S22 LOW `diagram.ts` — doubled shapes half-parsed, leftovers dropped edges,
  `end-user` skipped as the `end` keyword, a one-line `graph TD; A-->B` parsed to null →
  doubled shapes mapped, leftovers make the block fall back to Code, keyword needs a
  boundary, header-line statements parsed.
- S15, S16, S11, BF guards — criteria section always drawn; keyed rows for the text form;
  `launches` comment; `criteria ?? []` for an older stored Position; the capture hook passes
  through without a surface.
- S7 LOW — duplicate imports and a copied world in `views.test.tsx` → merged;
  `journaledWorld` takes the worklog text.
- Visible run id and time under the counts line (so the stamped data earns its place).

## Rejected findings — slice 3 round 1
- S10 LOW (85) "review fixtures in `fixtures.review.ts`, the plan named `fixtures.ts`" — kept:
  the file split let two workers write fixtures in parallel without conflicts; the T200 file
  list is corrected below.
- below-floor `register.tsx:580` (55) "Accept/Kill use the drawn board but mark the current
  atom" — the drawn board is the atom's board at render time; a new board resets marks.
- below-floor `views.tsx:58` (45) "a board captured with stream null is drawn under every
  stream" — by design until the next board; the launch now records the stream, so null is
  rare.
- below-floor `review.ts:166` (45) "`#` lines in a fenced block read as headings" — a PRD
  fence holding `## Success criteria` is not a real case.
- below-floor `diagram.ts:204` (40) "recursive layout on a very large chart" — the worklog's
  charts are tens of nodes; a cap is not worth its code.
- below-floor `diagram.ts:8` (30) "inline ```mermaid``` on one line opens a fence" — a fence
  opener is the whole line by the CommonMark rule the splitter follows.
- below-floor worklog prose (45) — the log entries were tightened in this round's notes.

## Review round 2 — slice 3 (2026-10-15)

Scoped re-review of the fix round, one reviewer (opus, all lenses): every F1–F12 and D1–D8
fix CONFIRMED with file:line; nothing throws before a `.catch`. Suggested verdict: not-ready
but close. Final round:

- MEDIUM (85) `diagram.ts:178` — a statement whose start the parser cannot read was still
  dropped with `continue` (the D2 hole) → null, so the block falls back to Code; test.
- MEDIUM (85) PRD FR-030 / FR-034 / FR-035 described the pre-fix capture rule, the SVG cap and
  `/clear` → amended (shape-only capture, launch stream, aborted, per-stream ticks, no cut).
- MEDIUM (50) "/clear keeps the board" vs register.tsx's "/clear resets $.state" → the code is
  right: slice 1 re-detects on `classic.SessionStart{clear}` because the state is reset. The
  CHANGELOG, README, PRD and this worklog now say the board is lost on `/clear`; the three
  tests that switched streams through `/clear` switch through a refresh instead.
- LOW — CHANGELOG review-module count 18 → 17; `toFinding` strips control characters and
  uppercases the severity; `SAFE_FILE` tested on the short path and widened to brackets,
  parentheses and Unicode letters; the stray module-state comment moved and made consistent
  with the slice 1 note; `fit` cuts through `cut` (no split surrogate); the "never cut" test
  asserts what it proves; CHANGELOG says "a `%%` comment line" and names the Code fallback.

## Rejected findings — slice 3 round 2
- LOW (55) "a hot reload resets `hasSurface` and turns the capture off" — a hot reload raises
  `session.start` again: the publish gate held commands in this session after its own hot
  reloads, which needs `hasSurface` true.
- LOW (80) "labels containing `;` and the `--o` / `--x` / `A@{…}` edge forms fall back to
  Code" — the fallback is the safe direction; outside the subset by design.
- LOW (70) "`cut` and `fit` do not count terminal cells (CJK two cells)" — `truncate-end` on
  the Text hides the overflow; a cell-width table is not worth its code here.

## Review round — 0.4.1 user-feedback slice (2026-10-15)

Live use of the Review tab on the probe run shaped this slice: buttons like Veto, wrapped
criteria, ticks and per-finding dispositions from the latest `review-verdict`, a three-cell
card header (the severity was pushed to the next line, then touched the percentage), and
rounds kept as collapsible sections. Scoped review, one reviewer (opus): every item in the
code; suggested ready after three fixes. Fixed in the final round:

- MEDIUM (85) `views.tsx:366` — dispositions matched the short `file:line` only, so a map
  keyed by a full path missed silently → full path looked up first, keys normalised.
- MEDIUM (80) `review.ts:249` — a `stream: null` board shared round numbers and `round-N`
  keys with the stream's own rounds → rounds identified by `<stream>:<round>`.
- MEDIUM (75) — a verdict's dispositions stamped a later round's finding at the same line →
  applied only to boards captured before the verdict.
- MEDIUM (85) docs — "the `open` count reads the newest round" was wrong: each round's counts
  line shows its own → reworded.
- LOW — a stale tick override hid a later verdict (overrides carry the verdict seq); marks
  and ticks of dropped rounds pruned; old single-board marks remapped; disposition text cut
  and stripped; "1 survivors"; the run line shown once; README truncation sentence and
  semicolon chains; "ticks from the journal" instead of "pre-ticks".

## Rejected findings — 0.4.1
- LOW (70) "no shipgate skill writes `criteria` or `dispositions`" — true and known: the
  ledger holds the shipgate follow-up; the orchestrator writes them by hand until then.
- LOW (75) "`open` is global across streams" — folded into the `<stream>:<round>` identity.
- LOW (80) "other streams' boards grow without limit" — five per stream; a session rarely
  drives more than a few streams; pruning of marks covers the rest.

## Review round 2 — 0.4.1 (2026-10-15)

Three-lens review workflow (`wf_130c2d46-e37`): 36 raw → 30 deduped → 13 above the floor,
1 HIGH held 0/2, 4 MEDIUM, 8 LOW, 18 below floor. The first return captured live by the
HUD on this stream (round 2 on the board, the probe folded behind it). Fixed:

- S1 HIGH `register.tsx:573` — an aborted refresh kept the old position with a null error, so
  the publish gate could pass a push on stale state → the gate learns whether the refresh
  completed and holds when it was cut.
- S2/S5 MEDIUM `register.tsx:397` — `isAborted` matched the word anywhere, including a
  `RunFailed` message carrying a stream name → engine shape only, never a `RunFailed`.
- S4 MEDIUM `views.tsx:469` — the button cell assumed `[Accept] [Kill]` (15) while non-plain
  buttons draw `[ Accept ] [ Kill ]` (19) → derived from the labels.
- S3 MEDIUM docs — PRD FR-031/FR-034 still described the run line under the counts and
  "counts from the newest" → reworded; FR-032's example fixed.
- LOW — stale JSDoc blocks, the `open` and `dispositions` docs, one verdict sort per
  refresh, `Object.hasOwn` on the colour table, a re-delivered return (same run id)
  replaces its round instead of adding one, CHANGELOG/README sentences.

## Rejected findings — 0.4.1 round 2
- below-floor (55) "older rounds show the latest verdict's dispositions" — by design for
  now: the map is keyed by location, and a later board ignores an earlier verdict.
- below-floor (55) "rounds do not fold like the Design tab (bracketed buttons vs plain)" —
  the user asked for Veto-style buttons here.
- below-floor (50) "`?` stream collides with a stream named `?`" — not a real stream name.
- below-floor (35) "a press after a refresh that brought a new verdict records an old seq" —
  the next press records the current one; one extra press at worst.
- below-floor (55) "the abort test proves the heuristic, not the engine's shape" — the
  engine's exact rejection text is not declared; the live message is the evidence.
