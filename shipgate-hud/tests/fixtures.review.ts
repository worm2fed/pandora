// The review workflow's return as Claude Code delivers it: a `<task-notification>` user turn
// whose `<result>` holds the return JSON with `<`, `>` and `&` HTML-escaped. Generic paths,
// generic summaries.

const REVIEW_RETURN = {
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
      risk: 'high',
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
      lenses: ['correctness'],
      alsoReported: ['conventions+design'],
      risk: 'low',
      verification: 'held',
      quorum: '0/2',
      refuters: [{ reason: 'The loop has a cap.', evidence: 'src/app.ts:130 caps at 3 "tries".' }],
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
        severity: 'MEDIUM',
        confidence: 80,
        file: 'src/parse.ts',
        line: 10,
        summary: 'The parser drops a trailing empty field.',
        why: 'A row ending in a comma loses a column.',
        fix: 'Keep the empty field.',
        lenses: ['correctness'],
        alsoReported: [],
        risk: 'medium',
      },
      quorum: '2/2',
      reasons: [{ reason: 'The format forbids a trailing comma.', evidence: 'docs/format.md:12' }],
    },
  ],
  belowFloor: [
    {
      severity: 'HIGH',
      confidence: 40,
      file: 'src/cache/store.ts',
      line: 77,
      summary: 'The cache key ignores the locale.',
      risk: 'medium',
      why: 'Two locales can read the same entry.',
      fix: 'Add the locale to the key.',
    },
    { severity: 'LOW', confidence: 30, file: 'src/index.ts', line: 3, summary: 'An unused import.' },
  ],
  counts: { found: 9, deduped: 8, candidates: 5, refuters: 4, unverified: 1, survivors: 3, killed: 1 },
  coverage: { verify: 'high-only', refutersRequested: 4, refutersReported: 4, unverified: 2 },
  lensesRun: ['correctness', 'conventions+design', 'simplicity+security'],
}

const escapeHtml = (text: string): string => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export const REVIEW_NOTIFICATION = `<task-notification>
<task-id>a1b2c3d4e</task-id>
<tool-use-id>toolu_01AAAAAAAAAAAAAAAAAAAAAA</tool-use-id>
<output-file>/tmp/tasks/a1b2c3d4e.output</output-file>
<status>completed</status>
<summary>Dynamic workflow "Review a change through lens finders, then refute the top findings on evidence" completed</summary>
<result>${escapeHtml(JSON.stringify(REVIEW_RETURN))}</result>
</task-notification>`

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
