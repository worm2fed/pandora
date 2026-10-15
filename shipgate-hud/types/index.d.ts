// The $.state contract of shipgate-hud: every value the module keeps in $.state,
// declared under the plugin's name. `claude plugin validate` holds each atom to it.

export type Phase =
  | 'workspace'
  | 'route-and-map'
  | 'explore'
  | 'clarify'
  | 'design'
  | 'implement'
  | 'review'
  | 'capture'

export type PhaseMark = 'done' | 'current' | 'todo'

export type Decision = {
  seq: number
  gate: string
  question: string
  decision: string
  raisedBy: string
  mode: string | null
  at: string
}

export type TaskVerify = { outcome: string; at: string }

export type Task = {
  id: string
  title: string
  /** The Build Plan `##` section the task sits under, '' when none. */
  section: string
  tickedInWorklog: boolean
  doneInJournal: boolean
  /** The last verify-run that covered this task, pass or fail; null when none did. */
  lastVerify: TaskVerify | null
}

export type Adr = { path: string; title: string; status: string }

export type Verify = { outcome: string; taskIds: string[]; at: string }

export type DesignSection = { slug: string; title: string; markdown: string }

/** May the stream publish? journal.py's mr-opened rule, computed from the stream's events. */
export type PublishAuthorization = {
  authorized: boolean
  /** The event type that authorized it; null when nothing did. */
  by: 'review-verdict' | 'gate-decision' | null
  /** When that event was recorded; '' when nothing authorized. */
  at: string
}

export type Position = {
  stream: string
  phase: Phase | string
  phaseEnteredAt: string | null
  version: number
  phases: Record<Phase, PhaseMark>
  decisions: Decision[]
  tasks: Task[]
  lastVerify: Verify | null
  design: { adrs: Adr[]; sections: DesignSection[] }
  worklogPath: string | null
  publish: PublishAuthorization
  /** The SC-### lines of the PRD the stream's clarify-passed event names; [] when none. */
  criteria: Criterion[]
  /** The last review-verdict's `data.criteria`: SC id → status (`met`, `unmet`, …); {} when none. */
  criteriaStatus: Record<string, string>
  /** The last review-verdict's `data.dispositions`: `<path>:<line or ?>` (full or short, no leading `./`) → `fixed`, `rejected`, …; {} when none. */
  dispositions: Record<string, string>
  /** When the verdict holding `dispositions` was recorded (ISO); null when none. A board captured later ignores them. */
  dispositionsAt: string | null
  /** The `seq` of the last review-verdict; null when none. A tick override made against another verdict is ignored. */
  criteriaSeq: number | null
}

/** One `- **SC-NNN** — text` line of a PRD's Success criteria section. */
export type Criterion = { id: string; text: string }

export type Severity = 'BLOCKER' | 'HIGH' | 'MEDIUM' | 'LOW'

/** One finding of the review workflow's return, normalised. */
export type ReviewFinding = {
  severity: Severity | string
  confidence: number
  file: string
  line: number | null
  summary: string
  lenses: string[]
  verification: string
  quorum: string
  risk: string | null
}

/** The review workflow's return as the Review tab draws it, stamped with the stream it was captured under. */
export type ReviewBoard = {
  stream: string | null
  /** The review round within its stream: 1 for the first return captured for it, then one more each time. */
  round: number
  runId: string | null
  at: string
  counts: Record<string, number>
  coverage: Record<string, unknown>
  survivors: ReviewFinding[]
  killed: ReviewFinding[]
  belowFloor: ReviewFinding[]
  lensesRun: string[]
  /** The return's `aborted` reason when the run stopped early; null otherwise. */
  aborted: string | null
}

export type ReviewMark = 'accepted' | 'killed'

/** The user's own word on a criterion, over the journal's: ticked (`on`) or unticked (`off`), made against the verdict `seq` (null: no verdict). */
export type TickOverride = { state: 'on' | 'off'; seq: number | null }

/**
 * The captured review rounds, newest first, at most five per stream; the user's marks keyed
 * `<stream>:<round>:<survivor index>` (`?` for no stream); the tick overrides keyed
 * `<stream>:<SC id>` (a criterion with no entry shows the journal's status); and `open`: the
 * roundId of the open round, `'none'` when every round is folded, null for the newest.
 */
export type ReviewState = {
  boards: ReviewBoard[]
  marks: Record<string, ReviewMark>
  ticks: Record<string, TickOverride>
  open: string | null
}

/** The tags of a `<task-notification>` user turn; `result` is the parsed JSON, null when absent or unparsable. */
export type TaskNotification = {
  toolUseId: string | null
  taskId: string | null
  status: string | null
  summary: string | null
  /** The `<output-file>` the engine names: the task's full output, where a long result is kept whole. */
  outputFile: string | null
  result: unknown
}

export type Tab = 'flow' | 'plan' | 'design' | 'review'

declare module 'claude-code' {
  interface PluginState {
    'shipgate-hud': {
      position: Position | null
      tab: Tab | null
      /** The Design section open in the pane; null means the first one. */
      designOpen: string | null
      lastError: string | null
      isJournaled: boolean
      /** The last review workflow return captured this session, with the user's marks and ticks. */
      review: ReviewState
    }
  }
}
