// The review workflow's return as Claude Code delivers it: a `<task-notification>` user turn
// whose `<result>` holds the return JSON with `<`, `>` and `&` HTML-escaped. Generic paths,
// generic summaries. Every return is typed against the producer's shape (`Workflow*`, beside
// the decoder in review.ts), so a fixture cannot invent a key or a label the workflow never emits.

import type { WorkflowReturn } from '../hooks/review'
import { criterionId, eventSeq, isoTime, streamName } from '../hooks/journal'
import type { Phase, PhaseMark, Position, Verdict } from '../types'

/**
 * A finished run in `high-only` mode, internally consistent as review-workflow.js computes it
 * (maxRefuters 6, refutersForHigh 2): the BLOCKER held its two refuters; the first HIGH lost a
 * refuter (`refuters-died`, one counted vote of two); the HIGH on parse.ts was killed by a full
 * quorum; the HIGH on cache/index.ts was over the refuter cap (`unverified-cap`); the LOW was not
 * a target (`not-targeted`). Two findings sit under the floor, one of them a HIGH that keeps its
 * why and fix. Every risk label appears: top, high, mid, low; the LOW's file has none.
 */
export const REVIEW_RETURN = {
  survivors: [
    {
      severity: 'BLOCKER',
      confidence: 95,
      file: 'src/api/handler.ts',
      line: 42,
      summary: 'The handler writes the record before the permission check runs.',
      why: 'A caller without the role can still create a record.',
      fix: 'Move the permission check above the write.',
      lenses: ['correctness'],
      alsoReported: [],
      risk: 'mid',
      verification: 'held',
      quorum: '0/2',
      refuters: [],
    },
    {
      severity: 'HIGH',
      confidence: 90,
      file: 'src/app.ts',
      line: 126,
      summary: 'The retry loop never stops when the queue is empty & the timer fires.',
      why: 'The guard compares the count with <that> value, which is never reached.',
      fix: 'Stop the loop when the queue is empty.',
      lenses: ['correctness', 'conventions+design'],
      alsoReported: [{ lens: 'conventions+design', summary: 'The loop has no exit on an empty queue.' }],
      risk: 'top',
      verification: 'refuters-died',
      quorum: '1/2',
      refuters: [{ reason: 'The loop has a cap.', evidence: 'src/app.ts:130 caps at 3 "tries".' }],
    },
    {
      severity: 'HIGH',
      confidence: 85,
      file: 'src/cache/index.ts',
      line: 9,
      summary: 'The cache is read before it is filled.',
      why: 'The first request after a restart sees an empty cache.',
      fix: 'Fill the cache before the server listens.',
      lenses: ['correctness'],
      alsoReported: [],
      risk: 'low',
      verification: 'unverified-cap',
      quorum: '0/0',
      refuters: [],
    },
    {
      severity: 'LOW',
      confidence: 70,
      file: 'src/util/format.ts',
      line: null,
      summary: 'The helper duplicates an existing formatter.',
      why: 'Two formatters drift apart.',
      fix: 'Reuse the existing formatter.',
      lenses: ['simplicity+security', 'conventions+design'],
      alsoReported: [],
      verification: 'not-targeted',
      quorum: '0/0',
      refuters: [],
    },
  ],
  killed: [
    {
      finding: {
        severity: 'HIGH',
        confidence: 80,
        file: 'src/parse.ts',
        line: 10,
        summary: 'The parser drops a trailing empty field.',
        why: 'A row ending in a comma loses a column.',
        fix: 'Keep the empty field.',
        lenses: ['correctness'],
        alsoReported: [],
        risk: 'high',
      },
      quorum: '2/2',
      reasons: [
        { reason: 'The format forbids a trailing comma.', evidence: 'docs/format.md:12' },
        { reason: 'The reader rejects such rows first.', evidence: 'src/read.ts:4' },
      ],
    },
  ],
  belowFloor: [
    {
      severity: 'HIGH',
      confidence: 40,
      file: 'src/cache/store.ts',
      line: 77,
      summary: 'The cache key ignores the locale.',
      risk: 'mid',
      why: 'Two locales can read the same entry.',
      fix: 'Add the locale to the key.',
    },
    { severity: 'LOW', confidence: 30, file: 'src/index.ts', line: 3, summary: 'An unused import.' },
  ],
  counts: { found: 9, deduped: 7, candidates: 5, refuters: 6, unverified: 1, survivors: 4, killed: 1 },
  coverage: { verify: 'high-only', refutersRequested: 6, refutersReported: 5, unverified: 3, riskOrdered: true },
  lensesRun: ['correctness', 'conventions+design', 'simplicity+security'],
} satisfies WorkflowReturn

/** The return of a run whose every lens finder died, exactly as review-workflow.js builds it. */
export const REVIEW_RETURN_ABORTED = {
  survivors: [],
  killed: [],
  belowFloor: [],
  counts: { found: 0, deduped: 0, candidates: 0, refuters: 0, unverified: 0, survivors: 0, killed: 0 },
  coverage: { verify: 'high-only', refutersRequested: 0, refutersReported: 0, unverified: 0 },
  lensesRun: [],
  aborted: 'no lens finder returned',
} satisfies WorkflowReturn

const escapeHtml = (text: string): string => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** A completed task's notification carrying `result` as its JSON. */
export const notificationOf = (result: unknown, toolUseId = 'toolu_01AAAAAAAAAAAAAAAAAAAAAA'): string => `<task-notification>
<task-id>a1b2c3d4e</task-id>
<tool-use-id>${toolUseId}</tool-use-id>
<output-file>/tmp/tasks/a1b2c3d4e.output</output-file>
<status>completed</status>
<summary>Dynamic workflow "Review a change through lens finders, then refute the top findings on evidence" completed</summary>
<result>${escapeHtml(JSON.stringify(result))}</result>
</task-notification>`

export const REVIEW_NOTIFICATION = notificationOf(REVIEW_RETURN)

/** Where the engine keeps the task's whole output; the truncated notification below names it. */
export const REVIEW_OUTPUT_PATH = '/tmp/project/.claude/tasks/wabc.output'

/** The same run as the engine delivers a long return: the result cut mid-JSON, then the engine's tail naming the output file. */
export const REVIEW_NOTIFICATION_TRUNCATED = `<task-notification>
<task-id>wabc</task-id>
<tool-use-id>toolu_01AAAAAAAAAAAAAAAAAAAAAA</tool-use-id>
<output-file>${REVIEW_OUTPUT_PATH}</output-file>
<status>completed</status>
<summary>Dynamic workflow "Review a change through lens finders, then refute the top findings on evidence" completed</summary>
<result>${escapeHtml(JSON.stringify(REVIEW_RETURN).slice(0, 400))}
... (truncated 14694 chars, full result in ${REVIEW_OUTPUT_PATH})</result>
</task-notification>`

/** The task output file: the workflow run's record, its return under `result`. */
export const REVIEW_OUTPUT_FILE = JSON.stringify({
  summary: 'x',
  agentCount: 3,
  logs: [],
  result: REVIEW_RETURN,
  workflowProgress: {},
  totalTokens: 1,
  totalToolCalls: 1,
})

export const REVIEW_LAUNCH_RESULT = `Workflow launched in background.
Run ID: wf_0123abcd-ef0
Task ID: a1b2c3d4e
You will be notified when it completes.`

export const PRD_WITH_CRITERIA = `# PRD: a feature

## Slice 1

### Success criteria (draft, not a match)

- **SC-900** — not under a matching heading.

## Success criteria

- **SC-001** — The band shows the stream and the phase.
- **SC-002** — The pane lists the Build Plan, wrapped onto
  a second line.

## Out of scope

- **SC-901** — not under a matching heading either.

## Success criteria

- **SC-003** — A publish command asks when the stream is not authorized.
- **SC-004** — A ready verdict lets the push through.
- **SC-010** — The review board groups survivors by severity.
`

/** The value, or a thrown error for a fixture whose smart constructor refused it. */
export const must = <A>(value: A | null): A => {
  if (value === null) throw new Error('fixture: a smart constructor refused the value')
  return value
}

/** The stream every review fixture is captured under. */
export const REVIEW_STREAM = must(streamName('feat/example-stream'))

const PHASE_MARKS: Readonly<Record<Phase, PhaseMark>> = {
  workspace: 'done',
  'route-and-map': 'done',
  explore: 'done',
  clarify: 'done',
  design: 'done',
  implement: 'done',
  review: 'current',
  capture: 'todo',
}

/** A stream in review with two PRD criteria and no verdict yet: the Review tab's position. */
export const REVIEW_POSITION: Position = {
  stream: REVIEW_STREAM,
  version: 3,
  lifecycle: 'live',
  current: { phase: 'review', enteredAt: must(isoTime('2026-10-01T10:00:00+00:00')), isImplied: false },
  phases: PHASE_MARKS,
  decisions: [],
  plan: null,
  lastVerify: null,
  design: { adrs: [], sections: [] },
  publish: { kind: 'held' },
  criteria: [
    { id: must(criterionId('SC-001')), text: 'The band shows the stream and the phase.' },
    { id: must(criterionId('SC-002')), text: 'The parser keeps an empty field.' },
  ],
  lastVerdict: null,
}

/** The review position with a last verdict: `seq`, its time, and its criteria and dispositions. */
export const withVerdict = (
  position: Position,
  verdict: { readonly seq: number; readonly at: string; readonly criteria?: Verdict['criteria']; readonly dispositions?: Verdict['dispositions'] },
): Position => ({
  ...position,
  lastVerdict: {
    seq: must(eventSeq(verdict.seq)),
    at: must(isoTime(verdict.at)),
    verdict: 'ready',
    criteria: verdict.criteria ?? {},
    dispositions: verdict.dispositions ?? {},
  },
})
