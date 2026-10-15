// Pure drawing: (the surface's elements, a Position, the UI state, the actions) → a tree.
// No `$` here. Built to be scanned, not read: one truncated line per item, fixed columns,
// the active tab inverted, long prose collapsed behind a heading.

import type { BoxProps, ButtonProps, CodeProps, ElementConstructor, MarkdownProps, SvgProps, TextProps } from 'claude-code'

import type { Decision, Phase, Position, ReviewBoard, ReviewFinding, ReviewState, Tab, Task } from '../types'
import { type Fence, cut, flowchartSvg, flowchartText, parseFlowchart, splitFences } from './diagram'
import { PHASES, PHASE_SHORT, clock, isVetoable } from './position'
import { groupBySeverity, shortLocation, tickKey } from './review'

export type Ui = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Button: ElementConstructor<ButtonProps>
  Markdown: ElementConstructor<MarkdownProps>
  Code: ElementConstructor<CodeProps>
  // the terminal's table has no Svg: a diagram falls back to text or Code there
  Svg?: ElementConstructor<SvgProps>
}

export type Actions = {
  setTab: (tab: Tab) => void
  openDesign: (slug: string) => void
  veto: (decision: Decision) => void
  refresh: () => void
  openPane: () => void
  /** Accept / Kill on the review survivor at `index`; tick toggles a success criterion by id. */
  accept: (index: number) => void
  kill: (index: number) => void
  tick: (id: string) => void
}

export type PaneState = { tab: Tab | null; designOpen: string | null; lastError: string | null; columns: number; review?: ReviewState }

export const PANE_ID = 'shipgate-hud'

const MIN_COLUMNS = 40

/** `text` cut to `width` cells with an ellipsis; untouched when it fits. */
export function fit(text: string, width: number): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  // code points, so a surrogate pair is never split
  if (width <= 1) return [...clean].slice(0, Math.max(0, width)).join('')
  return cut(clean, width)
}

/** The tab a phase opens on when the user has not picked one. */
export function defaultTab(phase: string): Tab {
  if (phase === 'implement') return 'plan'
  if (phase === 'design') return 'design'
  if (phase === 'review') return 'review'
  return 'flow'
}

/** The review board held for this position's stream; null when none, or when it belongs to another stream. */
export function boardFor(position: Position, review: ReviewState | undefined): ReviewBoard | null {
  const board = review?.board ?? null
  if (board === null || (board.stream !== null && board.stream !== position.stream)) return null
  return board
}

/** `review N open` (N = survivors the user has not marked) while a board for the stream is held; else null. */
export function reviewSegment(position: Position, review: ReviewState | undefined): string | null {
  const board = boardFor(position, review)
  if (board === null || review === undefined) return null
  if (board.aborted) return 'review aborted'
  const open = board.survivors.filter((_, index) => review.marks[String(index)] === undefined).length
  return `review ${open} open`
}

/** The summary the band shows, as its ` · `-separated segments: stream, phase, tasks, verify, veto count, open review findings. */
export function summarySegments(position: Position, review?: ReviewState): string[] {
  const done = position.tasks.filter(t => t.doneInJournal).length
  const tasks = position.tasks.length > 0 ? `tasks ${done}/${position.tasks.length}` : 'no plan'
  const verify = position.lastVerify ? `verify ${position.lastVerify.outcome} ${clock(position.lastVerify.at)}` : 'no verify'
  const toVeto = position.decisions.filter(isVetoable).length
  const veto = toVeto > 0 ? `${toVeto} to veto` : null
  return [position.stream, position.phase, tasks, verify, veto, reviewSegment(position, review)].filter((s): s is string => Boolean(s))
}

/** The summary as one line (the prompt-context form). */
export function summaryOf(position: Position): string {
  return summarySegments(position).join(' · ')
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

export function bandOf(ui: Ui, position: Position, actions: Actions, columns: number, review?: ReviewState): ReturnType<Ui['Box']> {
  const { Box, Text, Button } = ui
  // the first row shares its width with the `h: hud` button; the rest have the band to themselves
  const room = Math.max(10, columns - 12)
  const [first = '', ...rest] = packSegments(summarySegments(position, review), room)
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
        {tab('review', 'Review', '4')}
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
 * else an svg block as xml `Code` and a flowchart as its box-and-arrow text; a mermaid block
 * that is no flowchart is mermaid `Code` everywhere. A drawing over the Svg limit is never cut
 * (a cut SVG is broken markup): it takes the non-Svg form under a dim note.
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
  const textForm = (rowKey: string): ReturnType<Ui['Box']> => (
    <Box key={rowKey} flexDirection="column">
      {flowchartText(chart)
        .split('\n')
        .map((line, i) => (
          // a keyed Box per row: Text takes no key
          <Box key={`${rowKey}-line-${i}`}>
            <Text wrap="truncate-end">{cut(line, Math.max(MIN_COLUMNS, columns))}</Text>
          </Box>
        ))}
    </Box>
  )
  if (!Svg) return textForm(key)
  const svg = flowchartSvg(chart)
  return svg.length > SVG_LIMIT ? tooLarge(svg, textForm(`${key}-text`)) : <Svg key={key} source={svg} alt={title} />
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
              <Box paddingLeft={2} flexDirection="column">
                {sectionChunksOf(ui, section.slug, section.title, section.markdown, width - 2)}
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

const SEVERITY_COLOR: Record<string, string> = { BLOCKER: 'error', HIGH: 'error', MEDIUM: 'warning', LOW: 'text' }

/** A count as drawn: the number, or `?` when the return did not carry it. */
const countText = (value: unknown): string => (typeof value === 'number' && Number.isFinite(value) ? String(value) : '?')

/** The board's counts line: found · deduped · candidates · survivors · killed · below floor · refuters requested/reported · unverified. */
export function reviewCounts(board: ReviewBoard): string {
  const { counts, coverage } = board
  return [
    `found ${countText(counts.found)}`,
    `deduped ${countText(counts.deduped)}`,
    `candidates ${countText(counts.candidates)}`,
    `survivors ${countText(counts.survivors ?? board.survivors.length)}`,
    `killed ${countText(counts.killed ?? board.killed.length)}`,
    `below floor ${countText(counts.belowFloor ?? board.belowFloor.length)}`,
    `refuters ${countText(coverage.refutersRequested)}/${countText(coverage.refutersReported)}`,
    `unverified ${countText(counts.unverified ?? coverage.unverified)}`,
  ].join(' · ')
}

/** One survivor: severity, confidence, verification and quorum, lenses, then Accept / Kill or the mark; `file:line` beside the wrapped summary. */
function findingCardOf(ui: Ui, finding: ReviewFinding, index: number, mark: string | undefined, actions: Actions, width: number): ReturnType<Ui['Box']> {
  const { Box, Text, Button } = ui
  const meta = `${finding.confidence}% · ${finding.verification || '?'} ${finding.quorum || '?'} · ${finding.lenses.join('+') || '?'}`
  const location = shortLocation(finding)
  return (
    <Box key={`finding-${index}`} flexDirection="column">
      <Box flexDirection="row" columnGap={2}>
        <Text bold color={SEVERITY_COLOR[finding.severity] ?? 'text'}>
          {`▎ ${finding.severity}`}
        </Text>
        <Text dimColor>{meta}</Text>
        {mark === 'accepted' ? <Text color="success">✓ accepted</Text> : null}
        {mark === 'killed' ? <Text color="error">✗ killed</Text> : null}
        {mark === undefined ? <Button key={`accept-${index}`} label="Accept" plain dimColor onPress={() => actions.accept(index)} /> : null}
        {mark === undefined ? <Button key={`kill-${index}`} label="Kill" plain dimColor onPress={() => actions.kill(index)} /> : null}
      </Box>
      <Box flexDirection="row">
        <Box width={Math.min(location.length + 4, Math.max(12, Math.floor(width / 2)))} flexShrink={0}>
          <Text wrap="truncate-end" dimColor>{`  ${location}`}</Text>
        </Box>
        <Box flexGrow={1} flexShrink={1}>
          <Text wrap="wrap">{finding.summary.replace(/\s+/g, ' ').trim()}</Text>
        </Box>
      </Box>
    </Box>
  )
}

/** The PRD's success criteria as toggles; one line saying so when the PRD names none. */
function criteriaOf(ui: Ui, position: Position, ticks: readonly string[], actions: Actions, width: number): ReturnType<Ui['Box']> {
  const { Box, Text, Button } = ui
  // a Position stored by an older module build has no criteria
  const criteria = position.criteria ?? []
  return (
    <Box flexDirection="column">
      <Text dimColor>SUCCESS CRITERIA</Text>
      {criteria.length === 0 ? (
        <Text dimColor>No PRD criteria found.</Text>
      ) : (
        criteria.map(criterion => (
          <Button
            key={`sc-${criterion.id}`}
            label={fit(`${ticks.includes(tickKey(position.stream, criterion.id)) ? '☑' : '☐'} ${criterion.id} ${criterion.text}`, width)}
            plain
            onPress={() => actions.tick(criterion.id)}
          />
        ))
      )}
    </Box>
  )
}

/** The Review tab: the review workflow's return for this stream as a board, then the PRD's SC checklist. */
function reviewTab(ui: Ui, position: Position, review: ReviewState | undefined, actions: Actions, columns: number): ReturnType<Ui['Box']> {
  const { Box, Text } = ui
  const width = Math.max(MIN_COLUMNS, columns)
  const board = boardFor(position, review)
  const ticks = review?.ticks ?? []
  if (board === null) {
    return (
      <Box flexDirection="column" rowGap={1}>
        <Text dimColor>{`No review captured for ${position.stream} yet (phase ${position.phase}).`}</Text>
        {criteriaOf(ui, position, ticks, actions, width)}
      </Box>
    )
  }
  const marks = review?.marks ?? {}
  const line = (key: string, text: string) => (
    // a keyed Box per row: Text takes no key
    <Box key={key}>
      <Text wrap="truncate-end" dimColor>
        {fit(text, width)}
      </Text>
    </Box>
  )
  return (
    <Box flexDirection="column" rowGap={1}>
      <Box flexDirection="column">
        <Text bold wrap="wrap">
          {reviewCounts(board)}
        </Text>
        {board.aborted ? <Text color="warning">{fit(`review aborted: ${board.aborted}`, width)}</Text> : null}
        <Text dimColor>{`run ${board.runId ?? '?'} · ${clock(board.at)}`}</Text>
      </Box>
      {groupBySeverity(board.survivors).map(group => (
        <Box key={`severity-${group.severity}`} flexDirection="column">
          <Text dimColor>{`  ${group.severity} (${group.indexes.length})`}</Text>
          {group.indexes.map(index => {
            const finding = board.survivors[index]
            return finding ? findingCardOf(ui, finding, index, marks[String(index)], actions, width) : null
          })}
        </Box>
      ))}
      {board.killed.length > 0 ? (
        <Box flexDirection="column">
          <Text dimColor>{`KILLED (${board.killed.length})`}</Text>
          {board.killed.map((finding, index) =>
            line(`killed-${index}`, `${finding.severity} · ${shortLocation(finding)} · ${finding.summary} · q=${finding.quorum || '?'}`),
          )}
        </Box>
      ) : null}
      {board.belowFloor.length > 0 ? (
        <Box flexDirection="column">
          <Text dimColor>{`BELOW FLOOR (${board.belowFloor.length})`}</Text>
          {board.belowFloor.map((finding, index) =>
            line(`below-${index}`, `${finding.severity} ${finding.confidence}% ${shortLocation(finding)} ${finding.summary}`),
          )}
        </Box>
      ) : null}
      {criteriaOf(ui, position, ticks, actions, width)}
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
        : active === 'review'
          ? reviewTab(ui, position, state.review, actions, state.columns)
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
