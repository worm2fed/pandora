// Pure drawing: (the surface's elements, a Position, the UI state, the actions) → a tree.
// No `$` here. Built to be scanned, not read: one truncated line per item, fixed columns,
// the active tab inverted, long prose collapsed behind a heading.

import type { BoxProps, ButtonProps, ElementConstructor, MarkdownProps, TextProps } from 'claude-code'

import type { Decision, Phase, Position, Tab, Task } from '../types'
import { PHASES, PHASE_SHORT, clock, isVetoable } from './position'

export type Ui = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Button: ElementConstructor<ButtonProps>
  Markdown: ElementConstructor<MarkdownProps>
}

export type Actions = {
  setTab: (tab: Tab) => void
  openDesign: (slug: string) => void
  veto: (decision: Decision) => void
  refresh: () => void
  openPane: () => void
}

export type PaneState = { tab: Tab | null; designOpen: string | null; lastError: string | null; columns: number }

export const PANE_ID = 'shipgate-hud'

const MIN_COLUMNS = 40

/** `text` cut to `width` cells with an ellipsis; untouched when it fits. */
export function fit(text: string, width: number): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (width <= 1) return clean.slice(0, Math.max(0, width))
  return clean.length > width ? `${clean.slice(0, width - 1)}…` : clean
}

/** The tab a phase opens on when the user has not picked one. */
export function defaultTab(phase: string): Tab {
  if (phase === 'implement') return 'plan'
  if (phase === 'design') return 'design'
  return 'flow'
}

/** The one-line summary the band shows. */
export function summaryOf(position: Position): string {
  const done = position.tasks.filter(t => t.doneInJournal).length
  const tasks = position.tasks.length > 0 ? `tasks ${done}/${position.tasks.length}` : 'no plan'
  const verify = position.lastVerify ? `verify ${position.lastVerify.outcome} ${clock(position.lastVerify.at)}` : 'no verify'
  const toVeto = position.decisions.filter(isVetoable).length
  const veto = toVeto > 0 ? `${toVeto} to veto` : null
  return [position.stream, position.phase, tasks, verify, veto].filter(Boolean).join(' · ')
}

/** `████████░░` over `width` cells. */
export function progressBar(done: number, total: number, width: number): string {
  if (total <= 0 || width <= 0) return ''
  const filled = Math.round((done / total) * width)
  return '█'.repeat(filled) + '░'.repeat(Math.max(0, width - filled))
}

export function bandOf(ui: Ui, position: Position, actions: Actions, columns: number): ReturnType<Ui['Box']> {
  const { Box, Text, Button } = ui
  const summary = summaryOf(position)
  const room = Math.max(10, columns - 12)
  return (
    <Box flexDirection="row" columnGap={2}>
      <Text wrap="truncate-end" dimColor>
        {fit(summary, room)}
      </Text>
      <Button key="open-hud" label="hud" plain hotkey="h" dimColor onPress={() => actions.openPane()} />
    </Box>
  )
}

function timelineOf(ui: Ui, position: Position): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const currentIndex = PHASES.indexOf(position.phase as Phase)
  return (
    <Box flexDirection="row" columnGap={2}>
      {PHASES.map((phase: Phase, index) => {
        const mark = position.phases[phase]
        const glyph = mark === 'done' ? '✓' : mark === 'current' ? '●' : '·'
        // a phase entered before but later in flow order than the current one: visited, drawn quiet
        const isVisited = mark === 'done' && index > currentIndex
        return (
          <Text
            bold={mark === 'current'}
            inverse={mark === 'current'}
            dimColor={mark === 'todo' || isVisited}
            color={mark === 'done' ? 'success' : mark === 'current' ? 'claude' : undefined}
          >
            {mark === 'current' ? ` ${PHASE_SHORT[phase]} ${glyph} ` : `${PHASE_SHORT[phase]} ${glyph}`}
          </Text>
        )
      })}
    </Box>
  )
}

function tabsOf(ui: Ui, active: Tab, actions: Actions, columns: number): ReturnType<Ui['Box']> {
  const { Box, Button, Text } = ui
  const tab = (id: Tab, label: string, hotkey: string) =>
    active === id ? (
      <Text bold inverse>
        {` ${hotkey} ${label} `}
      </Text>
    ) : (
      <Button key={`tab-${id}`} label={label} hotkey={hotkey} plain dimColor onPress={() => actions.setTab(id)} />
    )
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" columnGap={3}>
        {tab('flow', 'Flow', '1')}
        {tab('plan', 'Plan', '2')}
        {tab('design', 'Design', '3')}
        <Button key="refresh" label="Refresh" hotkey="r" plain dimColor onPress={() => actions.refresh()} />
      </Box>
      <Text dimColor>{'─'.repeat(Math.max(MIN_COLUMNS, columns))}</Text>
    </Box>
  )
}

const GATE_COLOR: Record<string, string> = {
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

function decisionOf(ui: Ui, decision: Decision, actions: Actions): ReturnType<Ui['Box']> {
  const { Box, Text, Button } = ui
  const who = decision.mode ? `${decision.raisedBy} · ${decision.mode}` : decision.raisedBy
  return (
    <Box key={`decision-${decision.seq}`} flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text bold color={GATE_COLOR[decision.gate] ?? 'text'}>
          {`▎ ${decision.gate}`}
        </Text>
        <Text dimColor>{`${clock(decision.at)} · ${who}`}</Text>
        {isVetoable(decision) ? (
          <Button key={`veto-${decision.seq}`} label="Veto" dimColor onPress={() => actions.veto(decision)} />
        ) : null}
      </Box>
      {labelled(ui, '  Q', decision.question, false)}
      {labelled(ui, '  A', decision.decision, true)}
    </Box>
  )
}

function flowTab(ui: Ui, position: Position, actions: Actions): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const since = position.phaseEnteredAt ? ` since ${clock(position.phaseEnteredAt)}` : ''
  const toVeto = position.decisions.filter(isVetoable).length
  return (
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">
        <Text>
          <Text bold>{position.stream}</Text>
          <Text dimColor>{` · v${position.version} · ${position.phase}${since}`}</Text>
        </Text>
        <Text dimColor>
          {position.decisions.length === 0
            ? 'No gate decisions recorded yet.'
            : `${position.decisions.length} gate decisions, newest first${toVeto ? ` · ${toVeto} open to veto` : ''}`}
        </Text>
      </Box>
      {position.decisions.map(decision => decisionOf(ui, decision, actions))}
    </Box>
  )
}

function taskOf(ui: Ui, task: Task): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const isDebt = task.tickedInWorklog && !task.doneInJournal
  const isFailed = task.lastVerify !== null && task.lastVerify.outcome !== 'pass'
  const glyph = isFailed ? '✗' : task.doneInJournal ? '✓' : isDebt ? '◐' : '○'
  const color = isFailed ? 'error' : task.doneInJournal ? 'success' : isDebt ? 'warning' : undefined
  const dim = !task.doneInJournal && !isDebt && !isFailed
  const tail = task.lastVerify ? `${task.lastVerify.outcome} ${clock(task.lastVerify.at)}` : isDebt ? 'ticked, no task-done' : ''
  return (
    <Box key={`task-${task.id}`} flexDirection="row" columnGap={1}>
      <Box width={7} flexShrink={0}>
        <Text color={color} dimColor={dim}>
          {`${glyph} ${task.id}`}
        </Text>
      </Box>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="wrap" color={color} dimColor={dim}>
          {task.title}
        </Text>
      </Box>
      {tail ? (
        <Box flexShrink={0}>
          <Text color={color} dimColor>
            {tail}
          </Text>
        </Box>
      ) : null}
    </Box>
  )
}

function planTab(ui: Ui, position: Position, columns: number): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const total = position.tasks.length
  const done = position.tasks.filter(t => t.doneInJournal).length
  const debt = position.tasks.filter(t => t.tickedInWorklog && !t.doneInJournal).length
  const failed = position.tasks.filter(t => t.lastVerify !== null && t.lastVerify.outcome !== 'pass').length
  const summary = total === 0 ? 'No Build Plan found in the worklog.' : `${done}/${total} done${debt > 0 ? ` · ${debt} unrecorded` : ''}${failed > 0 ? ` · ${failed} failing` : ''}`
  const verify = position.lastVerify
    ? `last verify ${position.lastVerify.outcome} · ${position.lastVerify.taskIds.join(', ') || '—'} · ${clock(position.lastVerify.at)}`
    : 'no verify-run recorded'
  const rows: ReturnType<Ui['Box']>[] = []
  let section: string | null = null
  for (const task of position.tasks) {
    if (task.section !== section) {
      section = task.section
      if (section) rows.push(<Text dimColor>{`  ${section.toUpperCase()}`}</Text>)
    }
    rows.push(taskOf(ui, task))
  }
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text color="success">{progressBar(done, total, 20)}</Text>
        <Text bold>{summary}</Text>
      </Box>
      <Text dimColor>{fit(verify, Math.max(MIN_COLUMNS, columns))}</Text>
      <Text> </Text>
      {rows}
    </Box>
  )
}

function designTab(ui: Ui, position: Position, open: string | null, actions: Actions, columns: number): ReturnType<Ui['Box']> {
  const { Box, Text, Button, Markdown } = ui
  const sections = position.design.sections
  const openSlug = open && sections.some(s => s.slug === open) ? open : (sections[0]?.slug ?? null)
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
            <Text dimColor>{` · ${adr.status}`}</Text>
          </Text>
        ))
      )}
      <Text> </Text>
      {sections.length === 0 ? (
        <Text dimColor>{position.worklogPath ? 'The worklog has no Design section yet.' : 'No worklog committed yet.'}</Text>
      ) : (
        sections.map(section =>
          section.slug === openSlug ? (
            <Box key={`design-${section.slug}`} flexDirection="column" marginBottom={1}>
              <Text bold>{`▾ ${section.title}`}</Text>
              <Box paddingLeft={2}>
                <Markdown key={`design-md-${section.slug}`} text={section.markdown || '_empty_'} />
              </Box>
            </Box>
          ) : (
            <Button
              key={`design-${section.slug}`}
              label={`▸ ${section.title}`}
              plain
              dimColor
              onPress={() => actions.openDesign(section.slug)}
            />
          ),
        )
      )}
    </Box>
  )
}

export function paneOf(ui: Ui, position: Position | null, state: PaneState, actions: Actions): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  if (position === null) {
    return (
      <Box flexDirection="column">
        <Text dimColor>{state.lastError ?? 'No shipgate stream on this branch.'}</Text>
      </Box>
    )
  }
  const active = state.tab ?? defaultTab(position.phase)
  const body =
    active === 'plan'
      ? planTab(ui, position, state.columns)
      : active === 'design'
        ? designTab(ui, position, state.designOpen, actions, state.columns)
        : flowTab(ui, position, actions)
  return (
    <Box flexDirection="column" rowGap={1}>
      {timelineOf(ui, position)}
      {tabsOf(ui, active, actions, state.columns)}
      {state.lastError ? <Text color="warning">{fit(state.lastError, state.columns)}</Text> : null}
      {body}
    </Box>
  )
}
