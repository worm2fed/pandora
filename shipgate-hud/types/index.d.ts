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
}

export type Tab = 'flow' | 'plan' | 'design'

declare module 'claude-code' {
  interface PluginState {
    'shipgate-hud': {
      position: Position | null
      tab: Tab | null
      /** The Design section open in the pane; null means the first one. */
      designOpen: string | null
      lastError: string | null
      isJournaled: boolean
    }
  }
}
