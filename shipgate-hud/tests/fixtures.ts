// Generic fixtures: a public repository, so stream names, task titles and questions are
// invented, never copied from a private project. The journal's JSON is journal.py's own (the
// golden file, fixtures.journal.ts) or a variant of it typed against the raw shapes below: a
// variant cannot drop a key the decoders read, nor give it a value of another type.

import type { AuthorizedBy, GateMode, Lifecycle, Phase, PhaseMark, RaisedBy, VerdictValue, VerifyOutcome, WorklogFrom } from '../types'
import { POSITION_GOLDEN, STATUS_GOLDEN } from './fixtures.journal'

// ---------------------------------------------------------------------------------------
// The raw shapes: the keys of journal.py's JSON the decoders read (journal.py prints more)
// ---------------------------------------------------------------------------------------

/** `current` as journal.py prints it. */
export interface CurrentJson {
  readonly phase: Phase
  readonly entered_at: string
  readonly implied: boolean
}

/** `publish` as journal.py prints it. */
export type PublishJson =
  | { readonly kind: 'held' }
  | { readonly kind: 'authorized'; readonly by: AuthorizedBy; readonly seq: number; readonly at: string }

/** One stream of `status --json`. */
export interface FeatureJson {
  readonly stream: string
  readonly lifecycle: Lifecycle
  readonly current: CurrentJson | null
  readonly last_event: { readonly ts: string } | null
  readonly publish: PublishJson
}

/** `status --json`. */
export interface StatusJson {
  readonly features: readonly FeatureJson[]
  readonly session_match: string | null
  readonly branch_match: string | null
  readonly nested_matches: readonly string[]
}

/** One task of `position --json`. */
export interface TaskJson {
  readonly id: string
  readonly title: string | null
  readonly section: string | null
  readonly ticked: boolean
  readonly done: boolean
  readonly last_verify: { readonly outcome: VerifyOutcome; readonly at: string } | null
}

/** One gate decision of `position --json`. */
export interface DecisionJson {
  readonly seq: number
  readonly gate: string | null
  readonly question: string | null
  readonly decision: string | null
  readonly raised_by: RaisedBy
  readonly mode: GateMode | null
  readonly at: string
}

/** `position --stream <s> --json`. */
export interface PositionJson {
  readonly stream: string
  readonly version: number
  readonly lifecycle: Lifecycle
  readonly current: CurrentJson | null
  readonly publish: PublishJson
  readonly phases: Readonly<Record<Phase, PhaseMark>>
  readonly artifacts: {
    readonly worklog: string | null
    readonly worklog_from: WorklogFrom | null
    readonly prd: string | null
    readonly adrs: readonly string[]
  }
  readonly tasks: readonly TaskJson[] | null
  readonly decisions: readonly DecisionJson[]
  readonly last_verify: { readonly outcome: VerifyOutcome; readonly task_ids: readonly string[]; readonly at: string } | null
  readonly verdict: {
    readonly seq: number
    readonly at: string
    readonly verdict: VerdictValue
    readonly criteria: Readonly<Record<string, string>>
    readonly dispositions: Readonly<Record<string, string>>
  } | null
}

/** journal.py's own output has the raw shapes: a key the golden file renames or drops is a compile error here. */
export const GOLDEN_STATUS: readonly StatusJson[] = Object.values(STATUS_GOLDEN)
export const GOLDEN_POSITIONS: readonly PositionJson[] = Object.values(POSITION_GOLDEN)

// ---------------------------------------------------------------------------------------
// The example stream: the golden `flow` stream renamed, held, with no verdict yet, and
// naming the example artifacts below
// ---------------------------------------------------------------------------------------

/** The stream the example checkout's branch names. */
export const EXAMPLE_STREAM = 'feat/example-stream'

/**
 * The example stream's position: the golden `flow` position (four tasks: T001 done, T002
 * failing, T003 ticked and unrecorded, T004 open; an executive decision to veto and the user's
 * publish decision), held, with no verdict, its worklog, ADR and PRD the fixtures below.
 */
export const EXAMPLE_POSITION = {
  ...POSITION_GOLDEN.flow,
  stream: EXAMPLE_STREAM,
  publish: { kind: 'held' },
  verdict: null,
  artifacts: {
    worklog: 'docs/prd/example.worklog.md',
    worklog_from: 'event',
    prd: 'docs/prd/example.md',
    adrs: ['docs/adr/0007-example-decision.md'],
  },
} satisfies PositionJson

/** A stream's status entry: the golden `branch` brief's first stream, renamed and held. */
export const featureOf = (stream: string, publish: PublishJson = { kind: 'held' }): FeatureJson => ({
  ...STATUS_GOLDEN.branch.features[0],
  stream,
  publish,
})

/** The example stream's status entry. */
export const EXAMPLE_FEATURE: FeatureJson = featureOf(EXAMPLE_STREAM)

/** The publish authorization a `review-verdict` with `verdict: ready` gives. */
export const AUTHORIZED: PublishJson = { kind: 'authorized', by: 'review-verdict', seq: 50, at: '2026-10-01T10:00:00+00:00' }

export const SIDECAR = {
  version: 1,
  db: '.claude/shipgate.db',
  ledger: 'docs/ledger.md',
  artifact_homes: {
    worklog: '*/docs/prd/*.worklog.md',
    prd: '*/docs/prd/*.md',
    adr: '*/docs/adr/*.md',
  },
}

export const WORKLOG = `---
type: worklog
title: "Worklog: Example"
status: implementing
---

# Worklog: Example

# Design

## Approach

Minimal change: one module, one test.

## Architecture

- parser
- view

# Build Plan

## Setup
- [x] T001 — add the widget — file(s): \`src/widget.ts\` — done when: compiles
- [ ] T002 — wire the widget — file(s): \`src/app.ts\` — done when: used

## Feature
- [x] T010 [P] — parse the input — file(s): \`src/parse.ts\` — done when: T011 passes
- [x] T011 — tests for T010 — file(s): \`tests/parse.test.ts\` — done when: fails first, then passes

## Traceability
- FR-001 → T010
`

export const ADR = `---
type: adr
title: "0007. Example decision"
status: accepted
---

# 0007. Example decision

> One line.
`

/** A worklog whose Design draws: a mermaid flowchart and an svg block in one section, a sequence diagram in another. */
export const WORKLOG_WITH_DIAGRAMS = `---
type: worklog
title: "Worklog: Example"
status: implementing
---

# Worklog: Example

# Design

## Data flow

Requests go through a queue before they reach the store.

\`\`\`mermaid
flowchart LR
  A[api] -->|enqueue| B[queue]
  B -->|drain| C[worker]
  C -->|write| D[store]
\`\`\`

The store is the only writer of record.

\`\`\`svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>
\`\`\`

## Sequence

\`\`\`mermaid
sequenceDiagram
  api->>queue: enqueue
  queue->>store: write
\`\`\`

# Build Plan

## Feature
- [ ] T001 — draw the diagrams — file(s): \`src/draw.ts\` — done when: tested
`

/** The PRD the LOG's clarify-passed event names (`docs/prd/example.md`): two success criteria. */
export const PRD = `# PRD: Example

## Success criteria

- **SC-001** — The widget draws the input.
- **SC-002** — The parser keeps an empty field.
`
