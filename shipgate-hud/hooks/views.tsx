// Pure drawing: (the surface's elements, the HUD view, the UI state, the actions) → a tree.
// No `$` here. Built to be scanned, not read: one truncated line per item, fixed columns,
// the active tab inverted, long prose collapsed behind a heading. Every closed vocabulary is
// drawn through a total table, so a member added to a union is a compile error here.

import type { BoxProps, ButtonProps, CodeProps, ElementConstructor, MarkdownProps, SvgProps, TextProps, ThemeKey } from 'claude-code'

import type {
  BoardSurvivor,
  CriterionId,
  CriterionStatus,
  Decision,
  Disposition,
  FindingCore,
  FindingSeverity,
  HudView,
  Lifecycle,
  OpenRound,
  Phase,
  PhaseMark,
  Position,
  ReviewBoard,
  ReviewMark,
  ReviewState,
  RoundId,
  Severity,
  StreamName,
  Tab,
  Task,
  TaskState,
  TickEntry,
  WorklogFrom,
} from '../types'
import {
  type Fence,
  type FlowGrid,
  type Flowchart,
  GRID_CELL_LIMIT,
  GRID_LEG_LIMIT,
  GRID_NODE_LIMIT,
  GRID_ROW_LIMIT,
  type GridResult,
  type GridSkip,
  cut,
  edgeLine,
  flowchartGrid,
  flowchartSvg,
  flowchartText,
  parseFlowchart,
  splitFences,
} from './diagram'
import { absurd } from './json'
import { failureText } from './journal'
import { PHASES, PHASE_SHORT, clock, isVetoable } from './position'
import { boardsFor, criterionGlyph, dispositionIn, groupBySeverity, roundId, severityLabel, shortLocation, tickOf } from './review'

/** The surface's element table, as `uiOf` (register.tsx) narrows `$.ui.resolve(e)`. */
export interface Ui {
  readonly Box: ElementConstructor<BoxProps>
  readonly Text: ElementConstructor<TextProps>
  readonly Button: ElementConstructor<ButtonProps>
  readonly Markdown: ElementConstructor<MarkdownProps>
  readonly Code: ElementConstructor<CodeProps>
  /**
   * Optional at the engine-table boundary: the engine completes a table to every element name
   * today, but a surface whose table leaves `Svg` out must still draw, so `drawsSvg` checks it
   * before a diagram uses it and the terminal falls back to text or Code.
   */
  readonly Svg?: ElementConstructor<SvgProps>
}

/** One drawn element. */
type El = ReturnType<Ui['Box']>

/** What the pane's controls do; register.tsx binds them to `$`. */
export interface Actions {
  readonly setTab: (tab: Tab) => void
  readonly openDesign: (slug: string) => void
  readonly veto: (decision: Decision) => void
  readonly refresh: () => void
  readonly openPane: () => void
  /** Accept / Kill on the survivor at `index` of the round `id` names. */
  readonly accept: (id: RoundId, index: number) => void
  readonly kill: (id: RoundId, index: number) => void
  /** Toggles a success criterion's tick. */
  readonly tick: (id: CriterionId) => void
  /** Opens a round, the newest, or folds them all. */
  readonly openRound: (open: OpenRound) => void
}

/** The pane's own state: the tab the user picked (null: the phase's default), the open Design section, the width, the review rounds. */
export interface PaneState {
  readonly tab: Tab | null
  readonly designOpen: string | null
  readonly columns: number
  readonly review: ReviewState
}

export const PANE_ID = 'shipgate-hud'

const MIN_COLUMNS = 40

/** `text` cut to `width` cells with an ellipsis; untouched when it fits. */
export function fit(text: string, width: number): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  // code points, so a surrogate pair is never split
  if (width <= 1) return [...clean].slice(0, Math.max(0, width)).join('')
  return cut(clean, width)
}

/** The tab a phase opens on when the user has not picked one; `flow` while the stream has entered no phase. */
export const DEFAULT_TAB: Readonly<Record<Phase, Tab>> = {
  workspace: 'flow',
  'route-and-map': 'flow',
  explore: 'flow',
  clarify: 'flow',
  design: 'design',
  implement: 'plan',
  review: 'review',
  capture: 'flow',
}

/** The newest review round held for this position's stream; null when none (a board of another stream is never drawn). */
export function boardFor(position: Position, review: ReviewState): ReviewBoard | null {
  return boardsFor(review.boards, position.stream)[0] ?? null
}

/** `review N open` (N = survivors of the newest round with neither a mark nor a disposition) while a board for the stream is held; else null. */
export function reviewSegment(position: Position, review: ReviewState): string | null {
  const board = boardFor(position, review)
  if (board === null) return null
  return board.aborted !== null ? 'review aborted' : `review ${openFindings(position, board)} open`
}

/**
 * The orchestrator's disposition of a finding: the last verdict's map looked up by the full
 * `file:line`, then the short one; null when none. A board captured after that verdict ignores
 * the map: the verdict judged an earlier round.
 */
function dispositionOf(position: Position, board: ReviewBoard, finding: FindingCore): Disposition | null {
  const verdict = position.lastVerdict
  if (verdict === null || Date.parse(board.at) > Date.parse(verdict.at)) return null
  return dispositionIn(verdict.dispositions, finding)
}

/** Survivors still open: neither the user's mark nor the orchestrator's disposition. */
export function openFindings(position: Position, board: ReviewBoard): number {
  return board.survivors.filter(survivor => survivor.mark === null && dispositionOf(position, board, survivor.finding) === null).length
}

/** A lifecycle's mark: its word and colour where the band and the pane name it. */
export interface LifecycleView {
  readonly text: string
  readonly color: ThemeKey
}

/** Each lifecycle's mark; null: a live stream is not marked. */
export const LIFECYCLE_VIEW: Readonly<Record<Lifecycle, LifecycleView | null>> = {
  live: null,
  dormant: { text: 'dormant', color: 'warning' },
  terminal: { text: 'terminal', color: 'warning' },
}

/** The phase where the band names it: the current one, or that the stream entered none. */
const phaseOf = (position: Position): string => (position.current === null ? 'no phase entered' : position.current.phase)

/** How many of the tasks are in `state`. */
const countState = (tasks: readonly Task[], state: TaskState): number => tasks.filter(task => task.state === state).length

/** The segments the position alone gives: stream, phase (or none entered), lifecycle when not live, tasks, verify, veto count. */
function positionSegments(position: Position): readonly string[] {
  const { plan, lastVerify } = position
  const lifecycle = LIFECYCLE_VIEW[position.lifecycle]
  const tasks = plan === null || plan.tasks.length === 0 ? 'no plan' : `tasks ${countState(plan.tasks, 'done')}/${plan.tasks.length}`
  const verify = lastVerify === null ? 'no verify' : `verify ${lastVerify.outcome} ${clock(lastVerify.at)}`
  const toVeto = position.decisions.filter(isVetoable).length
  return [
    position.stream,
    phaseOf(position),
    ...(lifecycle === null ? [] : [lifecycle.text]),
    tasks,
    verify,
    ...(toVeto > 0 ? [`${toVeto} to veto`] : []),
  ]
}

/** The summary the band shows, as its ` · `-separated segments: stream, phase (or none yet), lifecycle when not live, tasks, verify, veto count, open review findings. */
export function summarySegments(position: Position, review: ReviewState): readonly string[] {
  const open = reviewSegment(position, review)
  return [...positionSegments(position), ...(open === null ? [] : [open])]
}

/** The summary as one line (the prompt-context form), without the review segment. */
export function summaryOf(position: Position): string {
  return positionSegments(position).join(' · ')
}

/**
 * Segments packed into lines of at most `width` cells, joined by ` · `, a segment never split
 * across lines: a band narrower than the summary gets more rows, not an ellipsis. Only a lone
 * segment wider than the whole line is cut.
 */
export function packSegments(segments: readonly string[], width: number): string[] {
  const lines: string[] = []
  let line = ''
  for (const segment of segments.filter(Boolean)) {
    const joined = line ? `${line} · ${segment}` : segment
    if (line && joined.length > width) {
      lines.push(line)
      line = segment
    } else {
      line = joined
    }
  }
  if (line) lines.push(line)
  return lines.map(l => fit(l, width))
}

/** `████████░░` over `width` cells. */
export function progressBar(done: number, total: number, width: number): string {
  if (total <= 0 || width <= 0) return ''
  const filled = Math.round((done / total) * width)
  return '█'.repeat(filled) + '░'.repeat(Math.max(0, width - filled))
}

/** The cells the band's first row leaves for the `h hud` button and the gap before it. */
export const BAND_BUTTON_ROOM = 12

/**
 * The band's rows: the summary packed into lines of the room the first row leaves beside the
 * hud button (`BAND_BUTTON_ROOM`); every row is at most `columns` cells, however narrow.
 */
export function bandLines(position: Position, review: ReviewState, columns: number): readonly string[] {
  return packSegments(summarySegments(position, review), Math.max(1, columns - BAND_BUTTON_ROOM))
}

/** The band above the prompt: the bound stream's summary packed into rows; null for any other view (nothing drawn there). */
export function bandOf(ui: Ui, view: HudView, actions: Actions, columns: number, review: ReviewState): El | null {
  switch (view.kind) {
    case 'Bound':
      return boundBandOf(ui, view.position, actions, columns, review)
    case 'Off':
    case 'NoJournalScript':
    case 'Unbound':
    case 'Failed':
      return null
    default:
      return absurd(view)
  }
}

/** The bound stream's band: the first row beside the `h hud` button, the rest below it. */
function boundBandOf(ui: Ui, position: Position, actions: Actions, columns: number, review: ReviewState): El {
  const { Box, Text, Button } = ui
  const [first = '', ...rest] = bandLines(position, review, columns)
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text wrap="truncate-end" dimColor>
          {first}
        </Text>
        <Button key="open-hud" label="hud" plain hotkey="h" dimColor onPress={() => actions.openPane()} />
      </Box>
      {rest.map((line, index) => (
        // a keyed Box per row: Text takes no key, and a list without keys re-mounts on every resize
        <Box key={`row-${index}`}>
          <Text wrap="truncate-end" dimColor>
            {line}
          </Text>
        </Box>
      ))}
    </Box>
  )
}

/** A phase's glyph on the timeline, for each mark journal.py computes: `↷` jumped past, `↺` entered before the stream moved back. */
export const PHASE_GLYPH: Readonly<Record<PhaseMark, string>> = {
  done: '✓',
  skipped: '↷',
  current: '●',
  revisited: '↺',
  todo: '·',
}

/** A mark's colour on the timeline; null: drawn quiet (dim). */
const PHASE_MARK_COLOR: Readonly<Record<PhaseMark, ThemeKey | null>> = {
  done: 'success',
  skipped: null,
  current: 'claude',
  revisited: null,
  todo: null,
}

/** The timeline: each phase's short label and glyph; the current one inverted; skipped, revisited and todo drawn quiet; the lifecycle last when not live. */
function timelineOf(ui: Ui, position: Position): El {
  const { Box, Text } = ui
  const lifecycle = LIFECYCLE_VIEW[position.lifecycle]
  return (
    <Box flexDirection="row" columnGap={2}>
      {PHASES.map(phase => {
        const mark = position.phases[phase]
        const color = PHASE_MARK_COLOR[mark]
        const tone = color === null ? { dimColor: true } : { color }
        const label = `${PHASE_SHORT[phase]} ${PHASE_GLYPH[mark]}`
        return mark === 'current' ? (
          <Text bold inverse {...tone}>
            {` ${label} `}
          </Text>
        ) : (
          <Text {...tone}>{label}</Text>
        )
      })}
      {lifecycle === null ? null : <Text color={lifecycle.color}>{lifecycle.text}</Text>}
    </Box>
  )
}

/** The pane's tabs, in the order the tab row draws them. */
const TABS: readonly Tab[] = ['flow', 'plan', 'design', 'review']

/** The tab row from TAB_VIEW: the active tab inverted, the others and Refresh pressable; a rule under it. */
function tabsOf(ui: Ui, active: Tab, actions: Actions, columns: number): ReturnType<Ui['Box']> {
  const { Box, Button, Text } = ui
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" columnGap={3}>
        {TABS.map(id => {
          const { label, hotkey } = TAB_VIEW[id]
          return active === id ? (
            <Text bold inverse>
              {` ${hotkey} ${label} `}
            </Text>
          ) : (
            <Button key={`tab-${id}`} label={label} hotkey={hotkey} plain dimColor onPress={() => actions.setTab(id)} />
          )
        })}
        <Button key="refresh" label="Refresh" hotkey="r" plain dimColor onPress={() => actions.refresh()} />
      </Box>
      <Text dimColor>{'─'.repeat(Math.max(MIN_COLUMNS, columns))}</Text>
    </Box>
  )
}

/** A gate's colour in the Flow tab; a gate not listed (gates are an open vocabulary) is drawn in `text`. */
const GATE_COLOR: Readonly<Record<string, ThemeKey>> = {
  publish: 'warning',
  'security-review': 'error',
  review: 'permission',
  design: 'suggestion',
  clarify: 'claude',
}

/** A label in a fixed cell and text that wraps beside it, so continuation lines hang under the text. */
function labelled(ui: Ui, label: string, text: string, dim: boolean): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  return (
    <Box flexDirection="row">
      <Box width={5} flexShrink={0}>
        <Text dimColor>{label}</Text>
      </Box>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="wrap" dimColor={dim}>
          {text.replace(/\s+/g, ' ').trim()}
        </Text>
      </Box>
    </Box>
  )
}

/** A gate's colour: the table's for a listed gate (own keys only), `text` for any other or none. */
const gateColor = (gate: string | null): ThemeKey => (gate !== null && Object.hasOwn(GATE_COLOR, gate) ? (GATE_COLOR[gate] ?? 'text') : 'text')

/** One gate decision: gate, time, who and how; the question and the answer when recorded; Veto when vetoable. */
function decisionOf(ui: Ui, decision: Decision, actions: Actions): El {
  const { Box, Text, Button } = ui
  const who = decision.mode === null ? decision.raisedBy : `${decision.raisedBy} · ${decision.mode}`
  return (
    <Box key={`decision-${decision.seq}`} flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text bold color={gateColor(decision.gate)}>
          {`▎ ${decision.gate ?? '?'}`}
        </Text>
        <Text dimColor>{`${clock(decision.at)} · ${who}`}</Text>
        {isVetoable(decision) ? <Button key={`veto-${decision.seq}`} label="Veto" dimColor onPress={() => actions.veto(decision)} /> : null}
      </Box>
      {decision.question === null ? null : labelled(ui, '  Q', decision.question, false)}
      {decision.decision === null ? null : labelled(ui, '  A', decision.decision, true)}
    </Box>
  )
}

/** The Flow tab header's phase: the phase, `(implied)` when a jump put it there, and since when; or that none was entered. */
const phaseLineOf = (position: Position): string => {
  const current = position.current
  if (current === null) return '(no phase entered)'
  return `${current.phase}${current.isImplied ? ' (implied)' : ''} since ${clock(current.enteredAt)}`
}

/** The Flow tab: the stream, its version, phase (or none yet) and lifecycle, then its gate decisions, newest first. */
function flowTab(ui: Ui, position: Position, actions: Actions): El {
  const { Box, Text } = ui
  const lifecycle = LIFECYCLE_VIEW[position.lifecycle]
  const count = position.decisions.length
  const toVeto = position.decisions.filter(isVetoable).length
  return (
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">
        <Text>
          <Text bold>{position.stream}</Text>
          <Text dimColor>{` · v${position.version} · ${phaseLineOf(position)}${lifecycle === null ? '' : ` · ${lifecycle.text}`}`}</Text>
        </Text>
        <Text dimColor>
          {count === 0
            ? 'No gate decisions recorded yet.'
            : `${count} gate ${count === 1 ? 'decision' : 'decisions'}, newest first${toVeto > 0 ? ` · ${toVeto} open to veto` : ''}`}
        </Text>
      </Box>
      {position.decisions.map(decision => decisionOf(ui, decision, actions))}
    </Box>
  )
}

/** A task's glyph and colour (null: drawn dim), for each state. */
export interface TaskView {
  readonly glyph: string
  readonly color: ThemeKey | null
}

/** Each task state's glyph and colour. */
export const TASK_VIEW: Readonly<Record<TaskState, TaskView>> = {
  failed: { glyph: '✗', color: 'error' },
  done: { glyph: '✓', color: 'success' },
  debt: { glyph: '◐', color: 'warning' },
  open: { glyph: '○', color: null },
}

/** A task's tail: its failing verify, else its passing one, else the debt for a ticked task; null when none. */
const taskTail = (task: Task): string | null => {
  if (task.state === 'failed') return `fail ${clock(task.lastVerifyAt)}`
  if (task.lastVerifyAt !== null) return `pass ${clock(task.lastVerifyAt)}`
  return task.state === 'debt' ? 'ticked, no task-done' : null
}

/** One Build Plan task: glyph and id in a fixed cell, the title wrapping beside it, the last verify (or the debt) at the end. */
function taskOf(ui: Ui, task: Task): El {
  const { Box, Text } = ui
  const view = TASK_VIEW[task.state]
  const tone = view.color === null ? { dimColor: true } : { color: view.color }
  const tail = taskTail(task)
  return (
    <Box key={`task-${task.id}`} flexDirection="row" columnGap={1}>
      <Box width={7} flexShrink={0}>
        <Text {...tone}>{`${view.glyph} ${task.id}`}</Text>
      </Box>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="wrap" {...tone}>
          {task.title ?? '(no title)'}
        </Text>
      </Box>
      {tail === null ? null : (
        <Box flexShrink={0}>
          <Text {...tone} dimColor>
            {tail}
          </Text>
        </Box>
      )}
    </Box>
  )
}

/** The tasks as rows, each run of tasks under one section headed by it. */
const taskRowsOf = (ui: Ui, tasks: readonly Task[]): readonly El[] =>
  tasks.flatMap((task, index) => {
    const { Box, Text } = ui
    const section = task.section
    const previous = tasks[index - 1]
    const row = taskOf(ui, task)
    if (section === null || (previous !== undefined && previous.section === section)) return [row]
    return [
      // a keyed Box per heading: Text takes no key
      <Box key={`section-${index}`}>
        <Text dimColor>{`  ${section.toUpperCase()}`}</Text>
      </Box>,
      row,
    ]
  })

/** How the journal found the worklog, as the Plan tab says it. */
const WORKLOG_FROM_TEXT: Readonly<Record<WorklogFrom, string>> = { event: 'named by an event', name: 'found by its name' }

/** The Plan tab: progress, the last verify-run, then the tasks under their sections; says so when the stream has no plan (no worklog) or its Build Plan lists no task. */
function planTab(ui: Ui, position: Position, columns: number): El {
  const { Box, Text } = ui
  const { plan, lastVerify } = position
  if (plan === null) {
    return (
      <Box flexDirection="column">
        <Text dimColor>No worklog found for this stream.</Text>
      </Box>
    )
  }
  const width = Math.max(MIN_COLUMNS, columns)
  const total = plan.tasks.length
  const done = countState(plan.tasks, 'done')
  const debt = countState(plan.tasks, 'debt')
  const failed = countState(plan.tasks, 'failed')
  const summary =
    total === 0 ? 'No Build Plan found in the worklog.' : `${done}/${total} done${debt > 0 ? ` · ${debt} unrecorded` : ''}${failed > 0 ? ` · ${failed} failing` : ''}`
  const verify = lastVerify === null ? 'no verify-run recorded' : `last verify ${lastVerify.outcome} · ${lastVerify.taskIds.join(', ') || '—'} · ${clock(lastVerify.at)}`
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text color="success">{progressBar(done, total, 20)}</Text>
        <Text bold>{summary}</Text>
      </Box>
      <Text dimColor>{fit(verify, width)}</Text>
      <Text dimColor>{fit(`${plan.worklog} · ${WORKLOG_FROM_TEXT[plan.from]}`, width)}</Text>
      <Text> </Text>
      {taskRowsOf(ui, plan.tasks)}
    </Box>
  )
}

/** The Svg element's limit on its `source`. */
const SVG_LIMIT = 131072

/**
 * Whether the surface draws `Svg`. The engine completes every table to every element name, a
 * missing one drawing a fragment, so the terminal's table has an `Svg` too; only what it
 * builds tells the two apart.
 */
const drawsSvg = (ui: Ui): boolean => ui.Svg !== undefined && ui.Svg({ source: '<svg/>', alt: '' }).type === 'Svg'

/**
 * A `mermaid` or `svg` fence drawn for the surface (ADR 0002): `Svg` where the table has it,
 * else an svg block as xml `Code` and a flowchart as its box-drawing picture; a mermaid block
 * that is no flowchart is mermaid `Code` everywhere. A drawing over the Svg limit is never cut
 * (a cut SVG is broken markup): an svg block takes the xml `Code` form and a flowchart takes the
 * one-line-per-edge text form under a dim note.
 */
export function diagramOf(ui: Ui, fence: Extract<Fence, { kind: 'fence' }>, title: string, columns: number, key: string): ReturnType<Ui['Box']> {
  const { Box, Text, Code } = ui
  const Svg = drawsSvg(ui) ? ui.Svg : undefined
  const tooLarge = (source: string, fallback: ReturnType<Ui['Box']>): ReturnType<Ui['Box']> => (
    <Box key={key} flexDirection="column">
      <Text dimColor>{`diagram too large to draw as a picture (${source.length} characters)`}</Text>
      {fallback}
    </Box>
  )
  if (fence.lang === 'svg') {
    const code = <Code key={`${key}-code`} source={fence.source} language="xml" />
    if (!Svg) return <Code key={key} source={fence.source} language="xml" />
    return fence.source.length > SVG_LIMIT ? tooLarge(fence.source, code) : <Svg key={key} source={fence.source} alt={title} />
  }
  const chart = parseFlowchart(fence.source)
  if (chart === null) return <Code key={key} source={fence.source} language="mermaid" />
  const width = Math.max(MIN_COLUMNS, columns)
  const rowsOf = (rowKey: string, lines: string[]): ReturnType<Ui['Box']>[] =>
    lines.map((line, i) => (
      // a keyed Box per row: Text takes no key
      <Box key={`${rowKey}-line-${i}`}>
        <Text wrap="truncate-end">{cut(line, width)}</Text>
      </Box>
    ))
  const textForm = (rowKey: string): ReturnType<Ui['Box']> => (
    <Box key={rowKey} flexDirection="column">
      {rowsOf(rowKey, flowchartText(chart).split('\n'))}
    </Box>
  )
  // the grid must fit the real room; the 40-column floor only sets the cut and the note
  if (!Svg) return terminalDiagram(ui, chart, Math.max(1, columns), width, key, rowsOf, textForm)
  const svg = flowchartSvg(chart)
  return svg.length > SVG_LIMIT ? tooLarge(svg, textForm(`${key}-text`)) : <Svg key={key} source={svg} alt={title} />
}

/**
 * A flowchart in the terminal (ADR 0003): the box-drawing grid in the chart's direction; an
 * LR / RL chart whose grid does not fit (too wide, too tall, skipped past a leg or cell limit,
 * or a broken invariant) retried top to bottom; back edges listed under the picture one per
 * row. A grid fits when it is at most `room` columns wide and `GRID_ROW_LIMIT` rows tall. No
 * grid that fits: the text form under a dim note that names the reason.
 */
function terminalDiagram(
  ui: Ui,
  chart: Flowchart,
  room: number,
  width: number,
  key: string,
  rowsOf: (rowKey: string, lines: string[]) => ReturnType<Ui['Box']>[],
  textForm: (rowKey: string) => ReturnType<Ui['Box']>,
): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const gridsOf = (results: readonly GridResult[]): readonly FlowGrid[] => results.flatMap(result => (result.kind === 'grid' ? [result.grid] : []))
  const fits = (grid: FlowGrid): boolean => grid.width <= room && grid.rows.length <= GRID_ROW_LIMIT
  const first = flowchartGrid(chart, chart.direction)
  const sideways = chart.direction === 'LR' || chart.direction === 'RL'
  // a node count over the limit skips every direction alike
  const isFirstFit = first.kind === 'grid' && fits(first.grid)
  const retry = !isFirstFit && sideways && !(first.kind === 'skip' && first.reason.kind === 'nodes') ? flowchartGrid(chart, 'TD') : null
  const attempts: readonly GridResult[] = retry ? [first, retry] : [first]
  const grid = gridsOf(attempts).find(fits)
  const skipNote = (skip: GridSkip): string => {
    switch (skip.kind) {
      case 'nodes':
        return `diagram has ${skip.nodes} nodes; the pane draws up to ${GRID_NODE_LIMIT}`
      case 'legs':
        return `diagram has ${skip.legs} edge legs; the pane draws up to ${GRID_LEG_LIMIT}`
      case 'size':
        return `diagram is ${skip.width} by ${skip.height} cells; the pane draws up to ${GRID_CELL_LIMIT}`
      case 'overlap':
        // a broken invariant in the router draws the text form, never a broken pane
        return 'diagram could not be drawn as a picture'
      default:
        return absurd(skip)
    }
  }
  const noteOf = (): string => {
    const grids = gridsOf(attempts)
    if (grids.length > 0 && grids.every(g => g.width > room))
      return `diagram is ${Math.min(...grids.map(g => g.width))} columns wide; the pane has ${width}`
    const tall = grids.filter(g => g.rows.length > GRID_ROW_LIMIT).map(g => g.rows.length)
    if (tall.length > 0) return `diagram is ${Math.min(...tall)} rows tall; the pane draws up to ${GRID_ROW_LIMIT}`
    const skip = attempts.flatMap(result => (result.kind === 'skip' ? [result.reason] : []))[0]
    return skip === undefined ? 'diagram could not be drawn as a picture' : skipNote(skip)
  }
  if (!grid) {
    const note = noteOf()
    return (
      <Box key={key} flexDirection="column">
        <Text dimColor>{note}</Text>
        {textForm(`${key}-text`)}
      </Box>
    )
  }
  return (
    <Box key={key} flexDirection="column">
      {rowsOf(key, [...grid.rows, ...grid.backEdges.map(e => edgeLine(chart, e))])}
    </Box>
  )
}

/** An open Design section: prose as Markdown, its `mermaid` / `svg` fences as diagrams, in order. */
function sectionChunksOf(ui: Ui, slug: string, title: string, markdown: string, columns: number): ReturnType<Ui['Box']>[] {
  const { Markdown } = ui
  const chunks = splitFences(markdown)
  if (chunks.length === 0) return [<Markdown key={`design-md-${slug}`} text={markdown || '_empty_'} />]
  return chunks.map((chunk, index) => {
    // prose that opens the section keeps the section's Markdown key; every other chunk is keyed by position
    const key = index === 0 && chunk.kind === 'markdown' ? `design-md-${slug}` : `design-${slug}-${index}`
    return chunk.kind === 'markdown' ? <Markdown key={key} text={chunk.text} /> : diagramOf(ui, chunk, title, columns, key)
  })
}

/** The Design tab: the committed ADRs with their status, then the Design sections folded, one open. */
function designTab(ui: Ui, position: Position, open: string | null, actions: Actions, columns: number): El {
  const { Box, Text, Button } = ui
  const sections = position.design.sections
  const openSlug = open !== null && sections.some(section => section.slug === open) ? open : (sections[0]?.slug ?? null)
  const width = Math.max(MIN_COLUMNS, columns)
  return (
    <Box flexDirection="column">
      {position.design.adrs.length === 0 ? (
        <Text dimColor>No ADR committed.</Text>
      ) : (
        position.design.adrs.map(adr => (
          <Text wrap="truncate-end">
            <Text color="suggestion">◆ </Text>
            <Text bold>{fit(adr.title, width - 16)}</Text>
            {adr.status === null ? null : <Text dimColor>{` · ${adr.status}`}</Text>}
          </Text>
        ))
      )}
      <Text> </Text>
      {sections.length === 0 ? (
        <Text dimColor>{position.plan === null ? 'No worklog committed yet.' : 'The worklog has no Design section yet.'}</Text>
      ) : (
        sections.map(section =>
          section.slug === openSlug ? (
            <Box key={`design-${section.slug}`} flexDirection="column" marginBottom={1}>
              <Text bold>{`▾ ${section.title}`}</Text>
              <Box paddingLeft={2} flexDirection="column">
                {sectionChunksOf(ui, section.slug, section.title, section.markdown, width - 2)}
              </Box>
            </Box>
          ) : (
            <Button key={`design-${section.slug}`} label={`▸ ${section.title}`} plain dimColor onPress={() => actions.openDesign(section.slug)} />
          ),
        )
      )}
    </Box>
  )
}

/** A known severity's colour; another label is drawn in `text`. */
export const SEVERITY_COLOR: Readonly<Record<Severity, ThemeKey>> = { BLOCKER: 'error', HIGH: 'error', MEDIUM: 'warning', LOW: 'text' }

/** A count as drawn: the number, or `?` when the return did not carry it. */
const countText = (value: unknown): string => (typeof value === 'number' && Number.isFinite(value) ? String(value) : '?')

/** The board's counts line: found · deduped · candidates · survivors · killed · below floor · refuters requested/reported · unverified; `open N` last when given. */
export function reviewCounts(board: ReviewBoard, open: number | null): string {
  return reviewCountSegments(board, open).join(' · ')
}

/** The counts line's segments, in order; `open N` last when given. */
export function reviewCountSegments(board: ReviewBoard, open: number | null): readonly string[] {
  const { counts, coverage } = board
  return [
    `found ${countText(counts.found)}`,
    `deduped ${countText(counts.deduped)}`,
    `candidates ${countText(counts.candidates)}`,
    `survivors ${countText(counts.survivors ?? board.survivors.length)}`,
    `killed ${countText(counts.killed ?? board.killed.length)}`,
    // the return counts no below-floor findings: the list is the count
    `below floor ${board.belowFloor.length}`,
    `refuters ${countText(coverage.refutersRequested)}/${countText(coverage.refutersReported)}`,
    `unverified ${countText(counts.unverified ?? coverage.unverified)}`,
    ...(open === null ? [] : [`open ${open}`]),
  ]
}

/** The severity cell's width: `▎ BLOCKER` (9 cells, the longest label) and a one-cell gap before the meta. */
const SEVERITY_CELL = 10

/** The chrome a non-plain Button draws around its label in the terminal: `[ ` and ` ]`. */
const BUTTON_CHROME = 4

/** The terminal width of `[ Accept ] [ Kill ]`, the state cell of a card with no mark and no disposition: both buttons and the gap between them. */
const BUTTONS_WIDTH = 'Accept'.length + BUTTON_CHROME + 1 + 'Kill'.length + BUTTON_CHROME

/** A finding's severity colour: a known severity's, `text` for another label. */
const severityColor = (severity: FindingSeverity): ThemeKey => (severity.kind === 'known' ? SEVERITY_COLOR[severity.severity] : 'text')

/** A finding's vote as drawn: `<refuting>/<asked>`. */
const quorumText = (finding: { readonly quorum: { readonly refuting: number; readonly asked: number } }): string => `${finding.quorum.refuting}/${finding.quorum.asked}`

/** A finding's confidence as drawn: the number, `?` when the return carried none. */
const confidenceText = (finding: FindingCore): string => `${finding.confidence === null ? '?' : String(finding.confidence)}%`

/** A disposition's colour; null: drawn dim. */
const DISPOSITION_COLOR: Readonly<Record<Disposition, ThemeKey | null>> = { fixed: 'success', rejected: 'error', deferred: null }

/** A mark's text and colour in a card's state cell. */
export interface MarkView {
  readonly text: string
  readonly color: ThemeKey
}

/** Each mark as a card draws it. */
export const MARK_VIEW: Readonly<Record<ReviewMark, MarkView>> = {
  accepted: { text: '✓ accepted', color: 'success' },
  killed: { text: '✗ killed', color: 'error' },
}

/**
 * One survivor. Header, one line, three cells: the severity in a fixed cell, the meta (confidence,
 * verification and quorum, lenses) truncated to the room left, then the state: the user's mark,
 * else the orchestrator's disposition, else Accept / Kill. Then `file:line` beside the wrapped summary.
 */
function findingCardOf(ui: Ui, survivor: BoardSurvivor, id: RoundId, index: number, disposition: Disposition | null, actions: Actions, width: number): El {
  const { Box, Text, Button } = ui
  const { finding, mark } = survivor
  const meta = `${confidenceText(finding)} · ${finding.verification} ${quorumText(finding)} · ${finding.lenses.join('+') || '?'}`
  const shown = disposition === null ? '' : fit(disposition, 12)
  const dispositionColor = disposition === null ? null : DISPOSITION_COLOR[disposition]
  const state =
    mark !== null ? (
      <Text color={MARK_VIEW[mark].color}>{MARK_VIEW[mark].text}</Text>
    ) : disposition === null ? (
      <Box flexDirection="row" columnGap={1}>
        <Button key={`accept-${index}`} label="Accept" dimColor onPress={() => actions.accept(id, index)} />
        <Button key={`kill-${index}`} label="Kill" dimColor onPress={() => actions.kill(id, index)} />
      </Box>
    ) : dispositionColor === null ? (
      <Text dimColor>{shown}</Text>
    ) : (
      <Text color={dispositionColor}>{shown}</Text>
    )
  const stateWidth = mark !== null ? MARK_VIEW[mark].text.length : disposition === null ? BUTTONS_WIDTH : shown.length
  // the meta gives way: cut to what the row leaves, so the severity and the state stay on one line
  const metaRoom = Math.max(4, width - SEVERITY_CELL - stateWidth - 2)
  return (
    <Box key={`finding-${index}`} flexDirection="column">
      <Box flexDirection="row">
        <Box width={SEVERITY_CELL} flexShrink={0}>
          <Text bold wrap="truncate-end" color={severityColor(finding.severity)}>
            {`▎ ${severityLabel(finding.severity)}`}
          </Text>
        </Box>
        <Box flexGrow={1} flexShrink={1}>
          <Text wrap="truncate-end" dimColor>
            {fit(meta, metaRoom)}
          </Text>
        </Box>
        <Box flexShrink={0} paddingLeft={1}>
          {state}
        </Box>
      </Box>
      {locationAndSummaryOf(ui, shortLocation(finding), finding.summary, width)}
    </Box>
  )
}

/** Two full-width lines under a finding's head: the short `file:line`, dim, cut only when wider than the pane; the summary wrapped, indented 2. */
function locationAndSummaryOf(ui: Ui, location: string, summary: string, width: number): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  return (
    <Box flexDirection="column" paddingLeft={2}>
      <Text wrap="truncate-end" dimColor>
        {fit(location, width - 2)}
      </Text>
      <Text wrap="wrap">{summary.replace(/\s+/g, ' ').trim()}</Text>
    </Box>
  )
}

/** The PRD's success criteria as toggles; one line saying so when the PRD names none. */
function criteriaOf(ui: Ui, position: Position, ticks: readonly TickEntry[], actions: Actions): El {
  const { Box, Text, Button } = ui
  const verdict = position.lastVerdict
  const statusOf = (id: CriterionId): CriterionStatus | null => (verdict === null ? null : (verdict.criteria[id] ?? null))
  return (
    <Box flexDirection="column">
      <Text dimColor>SUCCESS CRITERIA</Text>
      {position.criteria.length === 0 ? (
        <Text dimColor>No PRD criteria found.</Text>
      ) : (
        position.criteria.map(criterion => (
          // the tick in a fixed cell, the id and the text wrapping beside it (continuation lines hang under the text)
          <Box key={`criterion-${criterion.id}`} flexDirection="row" columnGap={1}>
            <Box width={5} flexShrink={0}>
              <Button
                key={`sc-${criterion.id}`}
                label={criterionGlyph(tickOf(ticks, position.stream, criterion.id), statusOf(criterion.id), verdict === null ? null : verdict.seq)}
                dimColor
                onPress={() => actions.tick(criterion.id)}
              />
            </Box>
            <Box flexShrink={0}>
              <Text bold>{criterion.id}</Text>
            </Box>
            <Box flexGrow={1} flexShrink={1}>
              <Text wrap="wrap">{criterion.text.replace(/\s+/g, ' ').trim()}</Text>
            </Box>
          </Box>
        ))
      )}
    </Box>
  )
}

/** One round's board in full: counts, the aborted line, run and time, cards by severity, killed and below floor. */
function boardBodyOf(ui: Ui, position: Position, board: ReviewBoard, actions: Actions, width: number): El {
  const { Box, Text } = ui
  const id = roundId(board)
  // a killed or below-floor finding: its head on one dim line, then the location and the summary as on a card
  const entry = (key: string, head: string, finding: FindingCore): El => (
    // a keyed Box per entry: Text takes no key
    <Box key={key} flexDirection="column">
      <Text wrap="truncate-end" dimColor>
        {fit(head, width)}
      </Text>
      {locationAndSummaryOf(ui, shortLocation(finding), finding.summary, width)}
    </Box>
  )
  // the counts packed into lines at the ` · ` separators, so no line starts with one
  const countLines = packSegments(reviewCountSegments(board, openFindings(position, board)), width)
  return (
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">
        {countLines.map((text, index) => (
          <Box key={`counts-${index}`}>
            <Text bold>{text}</Text>
          </Box>
        ))}
        {board.aborted === null ? null : <Text color="warning">{fit(`review aborted: ${board.aborted}`, width)}</Text>}
      </Box>
      {groupBySeverity(board.survivors).map(group => (
        <Box key={`severity-${severityLabel(group.severity)}`} flexDirection="column">
          <Text dimColor>{`  ${severityLabel(group.severity)} (${group.indexes.length})`}</Text>
          {group.indexes.map(index => {
            const survivor = board.survivors[index]
            return survivor === undefined ? null : findingCardOf(ui, survivor, id, index, dispositionOf(position, board, survivor.finding), actions, width)
          })}
        </Box>
      ))}
      {board.killed.length > 0 ? (
        <Box flexDirection="column">
          <Text dimColor>{`KILLED (${board.killed.length})`}</Text>
          {board.killed.map((finding, index) => entry(`killed-${index}`, `${severityLabel(finding.severity)} · q=${quorumText(finding)}`, finding))}
        </Box>
      ) : null}
      {board.belowFloor.length > 0 ? (
        <Box flexDirection="column">
          <Text dimColor>{`BELOW FLOOR (${board.belowFloor.length})`}</Text>
          {board.belowFloor.map((finding, index) => entry(`below-${index}`, `${severityLabel(finding.severity)} · ${confidenceText(finding)}`, finding))}
        </Box>
      ) : null}
    </Box>
  )
}

/** The round `open` names among the stream's rounds: the newest, none (all folded), or the named one (the newest when it names none of them). */
function openBoardOf(rounds: readonly ReviewBoard[], open: OpenRound): ReviewBoard | null {
  switch (open.kind) {
    case 'newest':
      return rounds[0] ?? null
    case 'folded':
      return null
    case 'round':
      return rounds.find(board => roundId(board) === open.id) ?? rounds[0] ?? null
    default:
      return absurd(open)
  }
}

/**
 * The Review tab: each review round of this stream, newest first, folded as the Design tab folds
 * its sections (one open at a time, as `review.open` says), then the PRD's SC checklist once.
 */
function reviewTab(ui: Ui, position: Position, review: ReviewState, actions: Actions, columns: number): El {
  const { Box, Text, Button } = ui
  const width = Math.max(MIN_COLUMNS, columns)
  const rounds = boardsFor(review.boards, position.stream)
  if (rounds.length === 0) {
    const phase = position.current === null ? 'no phase entered' : `phase ${position.current.phase}`
    return (
      <Box flexDirection="column" rowGap={1}>
        <Text dimColor>{`No review captured for ${position.stream} yet (${phase}).`}</Text>
        {criteriaOf(ui, position, review.ticks, actions)}
      </Box>
    )
  }
  const open = openBoardOf(rounds, review.open)
  const title = (board: ReviewBoard): string => `round ${board.round} · run ${board.runId ?? '?'} · ${clock(board.at)}`
  return (
    <Box flexDirection="column" rowGap={1}>
      {rounds.map(board =>
        board === open ? (
          <Box key={`round-open-${roundId(board)}`} flexDirection="column">
            <Button key={`round-${roundId(board)}`} label={fit(`▾ ${title(board)}`, width - BUTTON_CHROME)} dimColor onPress={() => actions.openRound({ kind: 'folded' })} />
            {boardBodyOf(ui, position, board, actions, width)}
          </Box>
        ) : (
          <Button
            key={`round-${roundId(board)}`}
            label={fit(`▸ ${title(board)} · ${board.survivors.length} ${board.survivors.length === 1 ? 'survivor' : 'survivors'}`, width - BUTTON_CHROME)}
            dimColor
            onPress={() => actions.openRound({ kind: 'round', id: roundId(board) })}
          />
        ),
      )}
      {criteriaOf(ui, position, review.ticks, actions)}
    </Box>
  )
}

/** A pane tab: its label and hotkey on the tab row, and how it draws its body. */
export interface TabView {
  readonly label: string
  readonly hotkey: string
  readonly body: (ui: Ui, position: Position, state: PaneState, actions: Actions) => El
}

/** Each tab's label, hotkey and body. */
export const TAB_VIEW: Readonly<Record<Tab, TabView>> = {
  flow: { label: 'Flow', hotkey: '1', body: (ui, position, _state, actions) => flowTab(ui, position, actions) },
  plan: { label: 'Plan', hotkey: '2', body: (ui, position, state) => planTab(ui, position, state.columns) },
  design: { label: 'Design', hotkey: '3', body: (ui, position, state, actions) => designTab(ui, position, state.designOpen, actions, state.columns) },
  review: { label: 'Review', hotkey: '4', body: (ui, position, state, actions) => reviewTab(ui, position, state.review, actions, state.columns) },
}

/**
 * The pane, by view: `Off` says no journal was found; `NoJournalScript` says journal.py was
 * not found and names the `journalScript` option; `Unbound` names the nearby live streams and
 * says this session drives none; `Bound` draws the timeline, the tabs and the active tab;
 * `Failed` shows `failureText(failure)` above the stale position (when one exists).
 */
export function paneOf(ui: Ui, view: HudView, state: PaneState, actions: Actions): El {
  switch (view.kind) {
    case 'Off':
      return noteOf(ui, 'No shipgate journal found in this project.')
    case 'NoJournalScript':
      return noteOf(ui, 'shipgate-hud: cannot find shipgate/scripts/journal.py — set the journalScript option.')
    case 'Unbound':
      return unboundOf(ui, view.nearby)
    case 'Bound':
      return positionPaneOf(ui, view.position, state, actions, null)
    case 'Failed': {
      const failure = `shipgate-hud: refresh failed — ${failureText(view.failure)}`
      return view.stale === null ? warningOf(ui, failure) : positionPaneOf(ui, view.stale, state, actions, failure)
    }
    default:
      return absurd(view)
  }
}

/** A pane of one dim line. */
function noteOf(ui: Ui, text: string): El {
  const { Box, Text } = ui
  return (
    <Box flexDirection="column">
      <Text dimColor>{text}</Text>
    </Box>
  )
}

/** A pane of one warning, wrapped: a failure's text is never cut. */
function warningOf(ui: Ui, text: string): El {
  const { Box, Text } = ui
  return (
    <Box flexDirection="column">
      <Text color="warning" wrap="wrap">
        {text}
      </Text>
    </Box>
  )
}

/** The pane when the session drives no stream: it says so, and names the live streams nearby, or that none is live. */
function unboundOf(ui: Ui, nearby: readonly StreamName[]): El {
  const { Box, Text } = ui
  return (
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">
        <Text>This session drives no stream.</Text>
        <Text dimColor wrap="wrap">
          It binds to one once it writes to it, or when its branch names it.
        </Text>
      </Box>
      {nearby.length === 0 ? (
        <Text dimColor>No live stream nearby.</Text>
      ) : (
        <Box flexDirection="column">
          <Text dimColor>{`${nearby.length} live ${nearby.length === 1 ? 'stream' : 'streams'} nearby, named by this checkout:`}</Text>
          {nearby.map(stream => (
            // a keyed Box per row: Text takes no key
            <Box key={`nearby-${stream}`}>
              <Text wrap="truncate-end">{`  ${stream}`}</Text>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  )
}

/**
 * A stream's pane: the timeline, the tab row, then the active tab (the user's pick, else the
 * current phase's default, Flow while no phase is entered). Under a failed refresh, the
 * failure and a note sit between the tab row and the stale position's tab.
 */
function positionPaneOf(ui: Ui, position: Position, state: PaneState, actions: Actions, failure: string | null): El {
  const { Box, Text } = ui
  const active = state.tab ?? (position.current === null ? 'flow' : DEFAULT_TAB[position.current.phase])
  return (
    <Box flexDirection="column" rowGap={1}>
      {timelineOf(ui, position)}
      {tabsOf(ui, active, actions, state.columns)}
      {failure === null ? null : (
        <Box flexDirection="column">
          <Text color="warning" wrap="wrap">
            {failure}
          </Text>
          <Text dimColor>Showing the last position read, from before the refresh failed.</Text>
        </Box>
      )}
      {TAB_VIEW[active].body(ui, position, state, actions)}
    </Box>
  )
}
