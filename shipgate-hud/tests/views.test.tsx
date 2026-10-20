import { describe, expect, test } from 'claude-code/testing'

import type { EngineInterface, On, ResolveInput } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { type PositionDoc, criterionId, decodePosition, eventSeq, isoTime, projectPath, streamName, taskId } from '../hooks/journal'
import { clock, parseAdr, toPosition } from '../hooks/position'
import { EMPTY_REVIEW, decodeReviewReturn, markSurvivor, roundId, toReviewBoard } from '../hooks/review'
import {
  type Actions,
  BAND_BUTTON_ROOM,
  DEFAULT_TAB,
  type PaneState,
  type Ui,
  TAB_VIEW,
  bandLines,
  bandOf,
  boardFor,
  openFindings,
  packSegments,
  paneOf,
  reviewCountSegments,
  reviewCounts,
  reviewSegment,
  summaryOf,
  summarySegments,
} from '../hooks/views'
import type { Decision, HudView, IsoTime, OpenRound, Phase, PhaseMark, Position, ReviewBoard, ReviewState, StreamName, Task } from '../types'
import { type Gen, bool, forAll, int, listOf, orNull, pick, stringOf } from './arbitrary'
import { ADR, WORKLOG, WORKLOG_WITH_DIAGRAMS } from './fixtures'
import { POSITION_GOLDEN } from './fixtures.journal'
import { PRD_WITH_CRITERIA, REVIEW_POSITION, REVIEW_RETURN, REVIEW_RETURN_ABORTED, REVIEW_STREAM, must, withVerdict } from './fixtures.review'
import { PANE } from './world'

// The band and the pane drawn by hooks of the test's own (the plugin under test answers only
// its own Pane id), from a view the test builds out of the golden `position` documents, with
// actions that record each press. A press changes nothing drawn: a test that needs the next
// state draws it.

/** Whose elements the test's own hooks draw, and the Pane instances its pane and band hooks answer. */
const OWN_HOOKS = 'test'
const PANE_DRAW = 'hud-pane'
const BAND_DRAW = 'hud-band'

/** What the band hook draws where the band draws nothing. */
const NO_BAND = 'no band drawn'

/** The test kit's element table for the surface: the declared cast boundary, as uiOf (register.tsx) narrows it. */
const uiOf = ($: EngineInterface, e: ResolveInput): Ui =>
  // cast: the test kit's element table for the surface, as uiOf (register.tsx) narrows it
  $.ui.resolve(e) as unknown as Ui

/** Actions that record each press, in order. */
const recording = (pressed: string[]): Actions => ({
  setTab: tab => pressed.push(`tab ${tab}`),
  openDesign: slug => pressed.push(`design ${slug}`),
  veto: decision => pressed.push(`veto ${decision.seq}`),
  refresh: () => pressed.push('refresh'),
  openPane: () => pressed.push('pane'),
  accept: (id, index) => pressed.push(`accept ${id} ${index}`),
  kill: (id, index) => pressed.push(`kill ${id} ${index}`),
  tick: id => pressed.push(`tick ${id}`),
  openRound: open => pressed.push(`open ${open.kind === 'round' ? open.id : open.kind}`),
})

/** The pane's state as the tests draw it: no tab picked, the first section open, no review; the width comes from the mount. */
type DrawnState = Omit<PaneState, 'columns'>
const FRESH: DrawnState = { tab: null, designOpen: null, review: EMPTY_REVIEW }

/** Draws `paneOf(view)` beneath the plugin; `pressed` records every action. */
const drawPane = (on: On, view: HudView, state: DrawnState, pressed: string[] = []): void => {
  on('ui.render', { component: 'Pane', requestId: PANE_DRAW }, async ($, e) => paneOf(uiOf($, e), view, { ...state, columns: e.props.bodyColumns }, recording(pressed)))
}

/** Draws `bandOf(view)` beneath the plugin, or NO_BAND where it draws nothing. */
const drawBand = (on: On, view: HudView, review: ReviewState = EMPTY_REVIEW, pressed: string[] = []): void => {
  on('ui.render', { component: 'Pane', requestId: BAND_DRAW }, async ($, e) => {
    const ui = uiOf($, e)
    return bandOf(ui, view, recording(pressed), e.props.bodyColumns, review) ?? ui.Text({ children: NO_BAND })
  })
}

const mountOwn = ($: Engine, requestId: string, surface: 'terminal' | 'desktop' = 'terminal', columns = 100) =>
  $.ui.mount({ plugin: OWN_HOOKS, surface, component: 'Pane', requestId, props: { ...PANE.props, bodyColumns: columns } })

/** A golden position decoded; a thrown error naming the path when it does not decode. */
const docOf = (raw: unknown): PositionDoc => {
  const decoded = decodePosition(raw)
  if (!decoded.ok) throw new Error(`fixture: position does not decode at ${decoded.error.path}`)
  return decoded.value
}

const pathOf = (raw: string) => must(projectPath(raw))

/** A golden stream's position with its artifacts read: the worklog text (when it has a worklog), the ADR fixture for each ADR it names, the PRD. */
const positionOf = (raw: unknown, worklog: string = WORKLOG): Position => {
  const doc = docOf(raw)
  return toPosition({
    doc,
    worklog: doc.artifacts.worklog === null ? null : { path: doc.artifacts.worklog.path, text: worklog },
    adrs: doc.artifacts.adrs.map(path => parseAdr(path, ADR)),
    prd: doc.artifacts.prd === null ? null : { path: doc.artifacts.prd, text: PRD_WITH_CRITERIA },
  })
}

const bound = (position: Position): HudView => ({ kind: 'Bound', via: 'Branch', position })

const FLOW = positionOf(POSITION_GOLDEN.flow)
const STARTED = positionOf(POSITION_GOLDEN.started)
const NAMED = positionOf(POSITION_GOLDEN.named)
const DONE = positionOf(POSITION_GOLDEN.done)
const DORMANT = positionOf(POSITION_GOLDEN.dormant)

const at = (iso: string): string => clock(must(isoTime(iso)))

describe('views: the band', () => {
  test('the summary: stream, phase, tasks, verify and the veto count', async () => {
    expect(summaryOf(FLOW)).toBe(`feature/golden-flow · implement · tasks 1/4 · verify fail ${at('2026-10-01T11:54:00+00:00')} · 1 to veto`)
    expect(summaryOf(NAMED)).toBe(`feature/golden-named · implement · tasks 0/1 · verify pass ${at('2026-10-01T11:38:00+00:00')}`)
    expect(summaryOf(DORMANT)).toBe('feature/golden-dormant · workspace · dormant · no plan · no verify')
  })

  test('the segments end with the open review findings of the stream\'s newest round; the one-line summary leaves them out', async () => {
    const decoded = decodeReviewReturn(REVIEW_RETURN)
    if (!decoded.ok) throw new Error('fixture: the review return does not decode')
    const board = { ...toReviewBoard(decoded.value, null, FLOW.stream, must(isoTime('2026-10-01T11:58:00+00:00'))), round: 1 }
    const review: ReviewState = { ...EMPTY_REVIEW, boards: [board] }
    expect(summarySegments(FLOW, review).at(-1)).toBe('review 4 open')
    expect(summarySegments(FLOW, EMPTY_REVIEW).at(-1)).toBe('1 to veto')
    expect(summaryOf(FLOW)).not.toContain('review')
  })

  test('segments pack into lines of the given width, never split, never cut unless alone too wide', async () => {
    const segments = ['feat/example-stream', 'implement', 'tasks 2/4', 'verify pass 09:20', '1 to veto']
    expect(packSegments(segments, 120)).toEqual(['feat/example-stream · implement · tasks 2/4 · verify pass 09:20 · 1 to veto'])
    expect(packSegments(segments, 40)).toEqual(['feat/example-stream · implement', 'tasks 2/4 · verify pass 09:20', '1 to veto'])
    expect(packSegments(segments, 10)).toEqual(['feat/exam…', 'implement', 'tasks 2/4', 'verify pa…', '1 to veto'])
    expect(packSegments([], 40)).toEqual([])
  })

  test('the band\'s rows leave the first row room for the hud button', async () => {
    const verify = `verify fail ${at('2026-10-01T11:54:00+00:00')}`
    expect(bandLines(FLOW, EMPTY_REVIEW, 52)).toEqual(['feature/golden-flow · implement', `tasks 1/4 · ${verify}`, '1 to veto'])
    expect(bandLines(FLOW, EMPTY_REVIEW, 120)).toEqual([`feature/golden-flow · implement · tasks 1/4 · ${verify} · 1 to veto`])
  })

  test('a narrow band wraps the summary onto more rows instead of cutting it; h opens the pane', async ($, on) => {
    const pressed: string[] = []
    drawBand(on, bound(FLOW), EMPTY_REVIEW, pressed)
    const ui = await mountOwn($, BAND_DRAW, 'terminal', 52)
    expect((await ui.find({ type: 'Text', text: /feature\/golden-flow/ }))?.text).toBe('feature/golden-flow · implement')
    expect(await ui.find({ type: 'Text', text: /^tasks 1\/4 · verify fail/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '1 to veto' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /…/ })).toBeUndefined()
    await ui.press({ key: 'open-hud' })
    expect(pressed).toEqual(['pane'])
    await ui.unmount()
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`${surface}: the band draws the bound stream's summary`, async ($, on) => {
      drawBand(on, bound(FLOW))
      const ui = await mountOwn($, BAND_DRAW, surface, 120)
      expect((await ui.find({ type: 'Text', text: /feature\/golden-flow/ }))?.text).toContain('tasks 1/4')
      expect(await ui.find({ key: 'open-hud' })).toBeDefined()
      await ui.unmount()
    })
  }

  const UNBOUND_VIEWS: readonly (readonly [string, HudView])[] = [
    ['Off', { kind: 'Off' }],
    ['NoJournalScript', { kind: 'NoJournalScript' }],
    ['Unbound', { kind: 'Unbound', nearby: [FLOW.stream] }],
    ['Failed with a stale position', { kind: 'Failed', failure: { kind: 'Truncated' }, stale: FLOW }],
  ]
  for (const [name, view] of UNBOUND_VIEWS) {
    test(`the band draws nothing for ${name}`, async ($, on) => {
      drawBand(on, view)
      const ui = await mountOwn($, BAND_DRAW)
      expect(await ui.find({ type: 'Text', text: NO_BAND })).toBeDefined()
      expect(await ui.find({ key: 'open-hud' })).toBeUndefined()
      await ui.unmount()
    })
  }
})

// T028: the band-width law over generated bound positions

const PHASE_LIST = ['workspace', 'route-and-map', 'explore', 'clarify', 'design', 'implement', 'review', 'capture'] as const
const GEN_AT = must(isoTime('2026-10-01T11:00:00+00:00'))
/** Stream and title text: ASCII, separators, a two-byte letter and a wide one. */
const TEXT_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789/-_. é語'
const ALL_TODO: Readonly<Record<Phase, PhaseMark>> = {
  workspace: 'todo',
  'route-and-map': 'todo',
  explore: 'todo',
  clarify: 'todo',
  design: 'todo',
  implement: 'todo',
  review: 'todo',
  capture: 'todo',
}

const decisionGen: Gen<Decision> = rng => ({
  seq: must(eventSeq(int(0, 99999)(rng))),
  gate: orNull(pick(['publish', 'clarify', 'design']))(rng),
  question: null,
  decision: null,
  raisedBy: pick(['user', 'orchestrator'] as const)(rng),
  mode: orNull(pick(['ask', 'executive'] as const))(rng),
  at: GEN_AT,
})

const taskGen: Gen<Task> = rng => {
  const line = { id: must(taskId(`T${int(1, 9999)(rng)}`)), title: orNull(stringOf(TEXT_CHARS, 1, 60))(rng), section: orNull(pick(['Setup', 'Bodies']))(rng) }
  return bool(rng)
    ? { ...line, state: 'failed', lastVerifyAt: GEN_AT }
    : { ...line, state: pick(['done', 'debt', 'open'] as const)(rng), lastVerifyAt: orNull((): IsoTime => GEN_AT)(rng) }
}

const positionGen: Gen<Position> = rng => ({
  stream: must(streamName(stringOf(TEXT_CHARS.replace(' ', ''), 1, 140)(rng))),
  version: int(0, 99999)(rng),
  lifecycle: pick(['live', 'dormant', 'terminal'] as const)(rng),
  current: orNull(rng2 => ({ phase: pick(PHASE_LIST)(rng2), enteredAt: GEN_AT, isImplied: bool(rng2) }))(rng),
  phases: ALL_TODO,
  decisions: listOf(decisionGen, 0, 40)(rng),
  plan: orNull(rng2 => ({ worklog: pathOf('docs/prd/x.worklog.md'), from: pick(['event', 'name'] as const)(rng2), tasks: listOf(taskGen, 0, 300)(rng2) }))(rng),
  lastVerify: orNull(rng2 => ({ outcome: pick(['pass', 'fail'] as const)(rng2), taskIds: [], at: GEN_AT }))(rng),
  design: { adrs: [], sections: [] },
  publish: { kind: 'held' },
  criteria: [],
  lastVerdict: null,
})

interface BandCase {
  readonly position: Position
  readonly review: ReviewState
  readonly columns: number
}

const REVIEWED = decodeReviewReturn(REVIEW_RETURN)

const bandCase: Gen<BandCase> = rng => {
  const position = positionGen(rng)
  const board = REVIEWED.ok && bool(rng) ? [{ ...toReviewBoard(REVIEWED.value, null, position.stream, GEN_AT), round: 1 }] : []
  return { position, review: { ...EMPTY_REVIEW, boards: board }, columns: int(1, 200)(rng) }
}

describe('views: the band-width law', () => {
  test('no band row is wider than the band; the first leaves the hud button its room', async () => {
    forAll(20261020, 500, bandCase, ({ position, review, columns }) => {
      const lines = bandLines(position, review, columns)
      expect(lines.length).toBeGreaterThan(0)
      lines.forEach(line => expect([...line].length).toBeLessThanOrEqual(columns))
      if (columns > BAND_BUTTON_ROOM) expect([...(lines[0] ?? '')].length).toBeLessThanOrEqual(columns - BAND_BUTTON_ROOM)
    })
  })
})

describe('views: the audit defects, drawn from golden documents', () => {
  // D7: a stream that entered no phase is never drawn as `workspace`
  test('D7: no phase entered: the band says so, the pane opens Flow and its header says so, no phase is current', async ($, on) => {
    expect(summaryOf(STARTED)).toBe('feature/golden-started · no phase entered · no plan · no verify')
    drawPane(on, bound(STARTED), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: ' 1 Flow ' }))?.props.inverse).toBe(true)
    expect(await ui.find({ type: 'Text', text: /^feature\/golden-started · v1 · \(no phase entered\)$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'WS ·' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /●/ })).toBeUndefined()
    await ui.unmount()
  })

  // D8: skipped phases are not drawn as done
  test('D8: the timeline marks skipped phases ↷ and a revisited one ↺, both quiet; done ✓ in success', async ($, on) => {
    drawPane(on, bound(FLOW), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    const done = await ui.find({ type: 'Text', text: 'WS ✓' })
    expect(done?.props.color).toBe('success')
    const skipped = await ui.find({ type: 'Text', text: 'MAP ↷' })
    expect(skipped?.props.dimColor).toBe(true)
    expect(skipped?.props.color).toBeUndefined()
    expect((await ui.find({ type: 'Text', text: 'REV ↺' }))?.props.dimColor).toBe(true)
    expect((await ui.find({ type: 'Text', text: ' IMP ● ' }))?.props.inverse).toBe(true)
    expect((await ui.find({ type: 'Text', text: 'CAP ·' }))?.props.dimColor).toBe(true)
    await ui.unmount()
  })

  test('D8: an implied jump: every phase before it skipped, none done', async ($, on) => {
    drawPane(on, bound(NAMED), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    for (const label of ['WS', 'MAP', 'EXP', 'CLR', 'DSN']) {
      expect(await ui.find({ type: 'Text', text: `${label} ↷` })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: `${label} ✓` })).toBeUndefined()
    }
    await ui.unmount()
  })

  // D9: the Plan tab lists the tasks exactly as the journal parsed them
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`D9 (${surface}): the Plan tab lists the journal's tasks, a \`*\` bullet among them, each with its state`, async ($, on) => {
      drawPane(on, bound(FLOW), FRESH)
      const ui = await mountOwn($, PANE_DRAW, surface)
      // implement opens on the Plan tab
      expect((await ui.find({ type: 'Text', text: ' 2 Plan ' }))?.props.inverse).toBe(true)
      expect(await ui.find({ type: 'Text', text: '1/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '✓ T001' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: `pass ${at('2026-10-01T11:50:00+00:00')}` })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '✗ T002' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: `fail ${at('2026-10-01T11:54:00+00:00')}` })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '◐ T003' })).toBeDefined()
      expect((await ui.find({ type: 'Text', text: 'a star bullet' }))?.props.wrap).toBe('wrap')
      expect(await ui.find({ type: 'Text', text: 'ticked, no task-done' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '○ T004' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '(no title)' })).toBeDefined()
      // the sections head their tasks, once each
      expect(await ui.find({ type: 'Text', text: '  DECLARATIONS' })).toBeDefined()
      expect((await ui.findAll({ type: 'Text', text: '  BODIES' })).length).toBe(1)
      // tasks the worklog text lists but the journal did not parse are not drawn
      expect(await ui.find({ type: 'Text', text: /T010/ })).toBeUndefined()
      await ui.unmount()
    })
  }

  // D10: a finished or dormant stream is never drawn as live
  test('D10: a terminal stream is marked terminal in the band and the pane; a dormant one dormant', async ($, on) => {
    expect(summarySegments(DONE, EMPTY_REVIEW)).toContain('terminal')
    expect(summaryOf(DONE)).toBe('feature/golden-done · workspace · terminal · no plan · no verify')
    expect(summaryOf(FLOW)).not.toMatch(/live|terminal|dormant/)
    drawPane(on, bound(DONE), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: /^terminal$/ }))?.props.color).toBe('warning')
    expect(await ui.find({ type: 'Text', text: /^feature\/golden-done · v3 · workspace since \d\d:\d\d · terminal$/ })).toBeDefined()
    await ui.unmount()
  })

  test('D10: a dormant stream is marked dormant in the pane', async ($, on) => {
    drawPane(on, bound(DORMANT), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: /^dormant$/ }))?.props.color).toBe('warning')
    await ui.unmount()
  })

  // D13: an ADR the journal classified from a custom home is listed
  test('D13: the Design tab lists an ADR from a custom home', async ($, on) => {
    const custom = 'notes/decisions/0003-golden-custom.md'
    const doc = docOf({ ...POSITION_GOLDEN.flow, artifacts: { ...POSITION_GOLDEN.flow.artifacts, adrs: [custom] } })
    const position = toPosition({ doc, worklog: null, adrs: [parseAdr(pathOf(custom), '---\ntitle: "0003. A custom home"\nstatus: proposed\n---\n')], prd: null })
    drawPane(on, bound(position), { ...FRESH, tab: 'design' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: /0003\. A custom home/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /proposed/ })).toBeDefined()
    await ui.unmount()
  })
})

describe('views: the pane, by view', () => {
  test('Off: no journal found', async ($, on) => {
    drawPane(on, { kind: 'Off' }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'No shipgate journal found in this project.' })).toBeDefined()
    expect(await ui.find({ key: 'tab-flow' })).toBeUndefined()
    await ui.unmount()
  })

  test('NoJournalScript: journal.py not found, naming the journalScript option', async ($, on) => {
    drawPane(on, { kind: 'NoJournalScript' }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'shipgate-hud: cannot find shipgate/scripts/journal.py — set the journalScript option.' })).toBeDefined()
    await ui.unmount()
  })

  test('Unbound: this session drives no stream, and the live streams nearby are named', async ($, on) => {
    const nearby = [must(streamName('fix/7-golden-nested')), must(streamName('feature/golden-flow'))]
    drawPane(on, { kind: 'Unbound', nearby }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'This session drives no stream.' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /2 live streams nearby/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '  fix/7-golden-nested' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '  feature/golden-flow' })).toBeDefined()
    expect(await ui.find({ key: 'tab-flow' })).toBeUndefined()
    await ui.unmount()
  })

  test('Unbound with no live stream nearby says that none is live', async ($, on) => {
    drawPane(on, { kind: 'Unbound', nearby: [] }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'This session drives no stream.' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'No live stream nearby.' })).toBeDefined()
    await ui.unmount()
  })

  test('Failed with nothing shown before: the failure, no tabs', async ($, on) => {
    drawPane(on, { kind: 'Failed', failure: { kind: 'Exited', exitCode: 1, stderr: 'boom\n' }, stale: null }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: 'shipgate-hud: refresh failed — journal.py exited 1: boom' }))?.props.color).toBe('warning')
    expect(await ui.find({ key: 'tab-flow' })).toBeUndefined()
    await ui.unmount()
  })

  test('Failed over a stale position: the failure above it, the stale position noted and still drawn', async ($, on) => {
    drawPane(on, { kind: 'Failed', failure: { kind: 'Unsupported', argument: 'position' }, stale: FLOW }, FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: /^shipgate-hud: refresh failed — journal\.py does not know position/ }))?.props.color).toBe('warning')
    expect(await ui.find({ type: 'Text', text: /last position read/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: ' IMP ● ' })).toBeDefined()
    expect(await ui.find({ key: 'tab-flow' })).toBeDefined()
    await ui.unmount()
  })
})

describe('views: the tabs', () => {
  test('the default tab follows the phase', async () => {
    expect(DEFAULT_TAB.implement).toBe('plan')
    expect(DEFAULT_TAB.design).toBe('design')
    expect(DEFAULT_TAB.review).toBe('review')
    expect(DEFAULT_TAB.clarify).toBe('flow')
  })

  test('the tab row: each tab from TAB_VIEW, the active one inverted, the others and Refresh pressable', async ($, on) => {
    const pressed: string[] = []
    drawPane(on, bound(FLOW), { ...FRESH, tab: 'design' }, pressed)
    const ui = await mountOwn($, PANE_DRAW)
    expect((await ui.find({ type: 'Text', text: ' 3 Design ' }))?.props.inverse).toBe(true)
    expect(await ui.find({ key: 'tab-design' })).toBeUndefined()
    for (const tab of ['flow', 'plan', 'review'] as const) {
      expect((await ui.find({ key: `tab-${tab}` }))?.props.label).toBe(TAB_VIEW[tab].label)
    }
    await ui.press({ key: 'tab-flow' })
    await ui.press({ key: 'refresh' })
    expect(pressed).toEqual(['tab flow', 'refresh'])
    await ui.unmount()
  })

  test('Flow tab: the header, then the decisions newest first, a Veto only on the orchestrator\'s executive one', async ($, on) => {
    const pressed: string[] = []
    drawPane(on, bound(FLOW), { ...FRESH, tab: 'flow' }, pressed)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: `feature/golden-flow · v17 · implement since ${at('2026-10-01T11:53:00+00:00')}` })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '2 gate decisions, newest first · 1 open to veto' })).toBeDefined()
    const decisions = await ui.findAll({ type: 'Text', text: /^▎ / })
    expect(decisions.map(d => d.text)).toEqual(['▎ publish', '▎ clarify'])
    expect(decisions.map(d => d.props.color)).toEqual(['warning', 'claude'])
    expect((await ui.find({ type: 'Text', text: 'open the MR before the second review?' }))?.props.wrap).toBe('wrap')
    // seq 13: the orchestrator in executive mode; seq 26: the user's own decision
    expect((await ui.find({ key: 'veto-13' }))?.props.plain).toBeUndefined()
    expect(await ui.find({ key: 'veto-26' })).toBeUndefined()
    await ui.press({ key: 'veto-13' })
    expect(pressed).toEqual(['veto 13'])
    await ui.unmount()
  })

  test('Flow tab: an implied phase says so; a decision with no gate, question or answer draws what it has', async ($, on) => {
    const seq = must(eventSeq(5))
    const bare: Decision = { seq, gate: null, question: null, decision: null, raisedBy: 'orchestrator', mode: null, at: must(isoTime('2026-10-01T11:36:00+00:00')) }
    drawPane(on, bound({ ...NAMED, decisions: [bare] }), { ...FRESH, tab: 'flow' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: /^feature\/golden-named · v3 · implement \(implied\) since \d\d:\d\d$/ })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: '▎ ?' }))?.props.color).toBe('text')
    expect(await ui.find({ type: 'Text', text: `${at('2026-10-01T11:36:00+00:00')} · orchestrator` })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '  Q' })).toBeUndefined()
    expect(await ui.find({ key: 'veto-5' })).toBeUndefined()
    await ui.unmount()
  })

  test('Flow tab: no decision yet says so', async ($, on) => {
    drawPane(on, bound(STARTED), FRESH)
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'No gate decisions recorded yet.' })).toBeDefined()
    await ui.unmount()
  })

  test('Plan tab: a stream with no worklog says so', async ($, on) => {
    drawPane(on, bound(DORMANT), { ...FRESH, tab: 'plan' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'No worklog found for this stream.' })).toBeDefined()
    await ui.unmount()
  })

  test('Plan tab: the worklog it reads, and how the journal found it', async ($, on) => {
    drawPane(on, bound(NAMED), { ...FRESH, tab: 'plan' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'docs/prd/golden-named.worklog.md · found by its name' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '0/1 done · 1 unrecorded' })).toBeDefined()
    await ui.unmount()
  })

  test('Plan tab: a Build Plan that lists no task', async ($, on) => {
    const plan = FLOW.plan === null ? null : { ...FLOW.plan, tasks: [] }
    drawPane(on, bound({ ...FLOW, plan }), { ...FRESH, tab: 'plan' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'No Build Plan found in the worklog.' })).toBeDefined()
    await ui.unmount()
  })

  test('Design tab: the ADRs with their status, then the Design sections, the first open, the others pressable', async ($, on) => {
    const pressed: string[] = []
    drawPane(on, bound(FLOW), { ...FRESH, tab: 'design' }, pressed)
    const ui = await mountOwn($, PANE_DRAW, 'desktop')
    // the flow stream names two ADRs; the fixture text gives both one title
    expect((await ui.findAll({ type: 'Text', text: /^◆ 0007\. Example decision · accepted$/ })).length).toBe(2)
    expect(await ui.find({ type: 'Text', text: /accepted/ })).toBeDefined()
    expect((await ui.find({ key: 'design-md-approach' }))?.text).toContain('Minimal change')
    expect(await ui.find({ key: 'design-md-architecture' })).toBeUndefined()
    await ui.press({ key: 'design-architecture' })
    expect(pressed).toEqual(['design architecture'])
    await ui.unmount()
  })

  test('Design tab: the section the state names is open', async ($, on) => {
    drawPane(on, bound(FLOW), { ...FRESH, tab: 'design', designOpen: 'architecture' })
    const ui = await mountOwn($, PANE_DRAW, 'desktop')
    expect((await ui.find({ key: 'design-md-architecture' }))?.text).toContain('- parser')
    expect(await ui.find({ key: 'design-md-approach' })).toBeUndefined()
    await ui.unmount()
  })

  test('Design tab: no ADR, no worklog', async ($, on) => {
    drawPane(on, bound(STARTED), { ...FRESH, tab: 'design' })
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'No ADR committed.' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'No worklog committed yet.' })).toBeDefined()
    await ui.unmount()
  })
})

const SVG_SOURCE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'

/** The flow stream with `worklog` as its worklog's text, drawn on the Design tab with `open` open. */
const drawDesign = (on: On, worklog: string, open: string | null = null): void =>
  drawPane(on, bound(positionOf(POSITION_GOLDEN.flow, worklog)), { ...FRESH, tab: 'design', designOpen: open })

describe('design diagrams', () => {
  test('terminal: a flowchart is a box-drawing picture, an svg block is xml Code, no Svg', async ($, on) => {
    drawDesign(on, WORKLOG_WITH_DIAGRAMS)
    const ui = await mountOwn($, PANE_DRAW)
    // the prose around the blocks stays Markdown
    expect((await ui.find({ key: 'design-md-data-flow' }))?.text).toContain('through a queue')
    expect(await ui.find({ type: 'Markdown', text: /only writer of record/ })).toBeDefined()
    // every label inside a box, every edge a line with a head, all on one row of a picture
    const middle = await ui.find({ type: 'Text', text: /│ api │/ })
    expect(middle?.text).toMatch(/^│ api │───enqueue──►│ queue │───drain──►│ worker │───write──►│ store │\s*$/)
    expect(await ui.find({ type: 'Text', text: /^┌─────┐ / })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /\[api\] ──enqueue──► \[queue\]/ })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /^diagram / })).toBeUndefined()
    expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    const code = await ui.find({ type: 'Code' })
    expect(code?.props.language).toBe('xml')
    expect(code?.props.source).toBe(SVG_SOURCE)
    await ui.unmount()
  })

  test('terminal: an LR picture wider than the pane is drawn top to bottom', async ($, on) => {
    drawDesign(on, WORKLOG_WITH_DIAGRAMS)
    const ui = await mountOwn($, PANE_DRAW, 'terminal', 40)
    expect(await ui.find({ type: 'Text', text: /^ │ api │/ })).toBeDefined()
    expect((await ui.findAll({ type: 'Text', text: /^\s*▼\s*$/ })).length).toBe(3)
    expect(await ui.find({ type: 'Text', text: /enqueue/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /►/ })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /^diagram / })).toBeUndefined()
    await ui.unmount()
  })

  test('terminal: a chart too wide either way is the text form under a note', async ($, on) => {
    // a chain is wide left to right; a fan of eight is wide top to bottom
    const chain = Array.from({ length: 6 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')
    const fan = '  n0 --> m1 & m2 & m3 & m4 & m5 & m6 & m7 & m8'
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n${fan}\n`))
    const ui = await mountOwn($, PANE_DRAW, 'terminal', 40)
    const note = await ui.find({ type: 'Text', text: /^diagram is \d+ columns wide; the pane has 40$/ })
    expect(note?.props.dimColor).toBe(true)
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
  })

  test('terminal: a chart over 60 nodes is the text form under a note', async ($, on) => {
    const chain = Array.from({ length: 60 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`))
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: 'diagram has 61 nodes; the pane draws up to 60' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    await ui.unmount()
  })

  test('terminal: an LR chart whose TD retry is over 200 rows is the text form under a rows note', async ($, on) => {
    // 46 boxes in a row: 447 columns left to right, 274 rows top to bottom
    const chain = Array.from({ length: 45 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`))
    const ui = await mountOwn($, PANE_DRAW)
    const note = await ui.find({ type: 'Text', text: 'diagram is 274 rows tall; the pane draws up to 200' })
    expect(note?.props.dimColor).toBe(true)
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
  })

  test('terminal: the grid fits the room under the indent, not the 40-column floor', async ($, on) => {
    // 39 columns left to right, 55 top to bottom; the section is indented by 2
    const chart = '  n0 --> m1 & m2 & m3 & m4 & m5 & m6 & m7 & m8\n  m1 --> z[zzzzzzzzzzzzzzz]'
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chart}\n`))
    // 40 columns leave a room of 38: the 39-column picture does not fit
    const ui = await mountOwn($, PANE_DRAW, 'terminal', 40)
    expect(await ui.find({ type: 'Text', text: 'diagram is 39 columns wide; the pane has 40' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[m1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
    // 41 columns leave a room of 39: the picture is drawn
    const ui2 = await mountOwn($, PANE_DRAW, 'terminal', 41)
    expect(await ui2.find({ type: 'Text', text: /│ n0 │/ })).toBeDefined()
    expect(await ui2.find({ type: 'Text', text: /^diagram / })).toBeUndefined()
    await ui2.unmount()
  })

  test('terminal: a back edge is listed under the picture in the one-line form', async ($, on) => {
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, 'flowchart LR\n  a --> b --> a\n'))
    const ui = await mountOwn($, PANE_DRAW)
    expect(await ui.find({ type: 'Text', text: /^│ a │──►│ b │/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '[b] ──► [a]' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '[a] ──► [b]' })).toBeUndefined()
    await ui.unmount()
  })

  test('desktop: a flowchart and an svg block are Svg with the section title as alt', async ($, on) => {
    drawDesign(on, WORKLOG_WITH_DIAGRAMS)
    const ui = await mountOwn($, PANE_DRAW, 'desktop')
    const drawings = await ui.findAll({ type: 'Svg' })
    expect(drawings.length).toBe(2)
    const [chart, block] = drawings
    expect(String(chart?.props.source).startsWith('<svg')).toBe(true)
    expect(chart?.props.source).toContain('queue')
    expect(chart?.props.alt).toBe('Data flow')
    expect(block?.props.source).toBe(SVG_SOURCE)
    expect(block?.props.alt).toBe('Data flow')
    expect(await ui.find({ type: 'Code' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /──►/ })).toBeUndefined()
    await ui.unmount()
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`${surface}: a sequenceDiagram is mermaid Code`, async ($, on) => {
      drawDesign(on, WORKLOG_WITH_DIAGRAMS, 'sequence')
      const ui = await mountOwn($, PANE_DRAW, surface)
      const code = await ui.find({ type: 'Code' })
      expect(code?.props.language).toBe('mermaid')
      expect(code?.props.source).toContain('sequenceDiagram')
      expect(await ui.find({ type: 'Svg' })).toBeUndefined()
      await ui.unmount()
    })
  }

  test('desktop: a drawing over the Svg limit is the text form or xml Code with a note; Code is passed whole, the engine cuts Code at 100000', async ($, on) => {
    // a 450-node chain lays out far past 131072 characters of SVG; the svg block is padded past it
    const chain = Array.from({ length: 450 }, (_, i) => `  n${i}[node ${i}] --> n${i + 1}`).join('\n')
    const bigSvg = SVG_SOURCE.replace('<rect width="10" height="10"/>', '<rect width="10" height="10"/>'.repeat(5000))
    drawDesign(on, WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`).replace(SVG_SOURCE, bigSvg))
    const ui = await mountOwn($, PANE_DRAW, 'desktop')
    expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    const notes = await ui.findAll({ type: 'Text', text: /^diagram too large to draw as a picture \(\d+ characters\)$/ })
    expect(notes.length).toBe(2)
    expect(notes[1]?.text).toBe(`diagram too large to draw as a picture (${bigSvg.length} characters)`)
    expect(await ui.find({ type: 'Text', text: /\[node 0\] ──► \[node 1\]/ })).toBeDefined()
    const code = await ui.find({ type: 'Code' })
    expect(code?.props.language).toBe('xml')
    const drawn = String(code?.props.source)
    const tail = /\n… (\d+) more characters, not drawn$/.exec(drawn)
    const kept = drawn.slice(0, tail?.index ?? drawn.length)
    // the engine cuts what one drawing shows at 100000 characters and reports the rest it got
    expect(tail).not.toBeNull()
    expect(bigSvg.startsWith(kept)).toBe(true)
    expect(kept.length + Number(tail?.[1])).toBe(bigSvg.length)
    await ui.unmount()
  })
})

// The review tab (T026): TAB_VIEW.review drawn by a Pane hook of the test's own (the plugin under
// test answers only its own Pane id), from a position and a review state the test builds, with
// actions that record each press. The test kit names the test's own hooks' elements `test`.

/** Whose elements the test's own hooks draw, and the Pane instance the review hook answers. */
const TEST_HOOKS = 'test'
const REVIEW_TAB_ID = 'review-tab'

/** The capture time of the fixture boards, and a verdict an hour before and an hour after it. */
const CAPTURED_AT = must(isoTime('2026-10-01T11:00:00+00:00'))
const VERDICT_BEFORE = '2026-10-01T10:00:00+00:00'
const VERDICT_AFTER = '2026-10-01T12:00:00+00:00'

const SC1 = must(criterionId('SC-001'))
const SC2 = must(criterionId('SC-002'))
const OTHER_STREAM = must(streamName('feat/other-stream'))

/** The fixture return captured under `stream` as round `round`, unmarked. */
const boardOf = (round = 1, stream: StreamName | null = REVIEW_STREAM, ret: unknown = REVIEW_RETURN, at: IsoTime = CAPTURED_AT): ReviewBoard => {
  const decoded = decodeReviewReturn(ret)
  if (!decoded.ok) throw new Error(`fixture: ${decoded.error.path}`)
  return { ...toReviewBoard(decoded.value, null, stream, at), round }
}

const stateOf = (boards: readonly ReviewBoard[], open: OpenRound = { kind: 'newest' }): ReviewState => ({ ...EMPTY_REVIEW, boards, open })

/** Draws the Review tab for `position` and `review` beneath the plugin; `pressed` records every action, in order. */
const drawReviewTab = (on: On, position: Position, review: ReviewState, pressed: string[]): void => {
  const actions: Actions = {
    setTab: tab => pressed.push(`tab ${tab}`),
    openDesign: slug => pressed.push(`design ${slug}`),
    veto: decision => pressed.push(`veto ${decision.seq}`),
    refresh: () => pressed.push('refresh'),
    openPane: () => pressed.push('pane'),
    accept: (id, index) => pressed.push(`accept ${id} ${index}`),
    kill: (id, index) => pressed.push(`kill ${id} ${index}`),
    tick: id => pressed.push(`tick ${id}`),
    openRound: open => pressed.push(`open ${open.kind === 'round' ? open.id : open.kind}`),
  }
  on('ui.render', { component: 'Pane', requestId: REVIEW_TAB_ID }, async ($, e) => {
    // cast: the test kit's element table for the surface, as uiOf (register.tsx) narrows it
    const ui = $.ui.resolve(e) as unknown as Ui
    return TAB_VIEW.review.body(ui, position, { tab: 'review', designOpen: null, columns: e.props.bodyColumns, review }, actions)
  })
}

/** A test of the Review tab drawn for `position` and `review`; the body gets `$` and the presses recorded so far. */
const reviewTest = (name: string, position: Position, review: ReviewState, body: ($: Engine, pressed: readonly string[]) => Promise<void>): void => {
  test(name, async ($, on) => {
    const pressed: string[] = []
    drawReviewTab(on, position, review, pressed)
    await body($, pressed)
  })
}

const mountReview = ($: Engine, surface: 'terminal' | 'desktop' = 'terminal', columns = 100) =>
  $.ui.mount({ plugin: TEST_HOOKS, surface, component: 'Pane', requestId: REVIEW_TAB_ID, props: { ...PANE.props, bodyColumns: columns } })

/** The counts' first line at 100 columns; `unverified 1 · open N` packs onto the next. */
const COUNTS = 'found 9 · deduped 7 · candidates 5 · survivors 4 · killed 1 · below floor 2 · refuters 6/5'

/** A return whose one survivor has a label outside the four and a confidence that is no number. */
const ODD_RETURN = { ...REVIEW_RETURN, survivors: [{ ...REVIEW_RETURN.survivors[0], severity: 'nit', confidence: 'high' }] }

/** The fixture return with the LOW finding's file reported absolute, as a workflow may. */
const ABSOLUTE_RETURN = {
  ...REVIEW_RETURN,
  survivors: REVIEW_RETURN.survivors.map(survivor => (survivor.file === 'src/util/format.ts' ? { ...survivor, file: '/abs/pkg/src/util/format.ts' } : survivor)),
}

describe('review tab', () => {
  test('the Review tab is labelled Review on hotkey 4', async () => {
    expect([TAB_VIEW.review.label, TAB_VIEW.review.hotkey]).toEqual(['Review', '4'])
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    reviewTest(`${surface}: the board's survivors grouped by severity, then killed and below floor, then the criteria`, REVIEW_POSITION, stateOf([boardOf()]), async $ => {
      const ui = await mountReview($, surface)
      expect(await ui.find({ type: 'Text', text: COUNTS })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'unverified 1 · open 4' })).toBeDefined()
      const headers = await ui.findAll({ type: 'Text', text: /^ {2}(BLOCKER|HIGH|MEDIUM|LOW) \(\d+\)$/ })
      expect(headers.map(h => h.text)).toEqual(['  BLOCKER (1)', '  HIGH (2)', '  LOW (1)'])
      const cards = await ui.findAll({ type: 'Text', text: /^▎ / })
      expect(cards.map(c => c.text)).toEqual(['▎ BLOCKER', '▎ HIGH', '▎ HIGH', '▎ LOW'])
      expect(cards.map(c => c.props.color)).toEqual(['error', 'error', 'error', 'text'])
      expect(await ui.find({ type: 'Text', text: '95% · held 0/2 · correctness' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '90% · refuters-died 1/2 · correctness+conventions+design' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '85% · unverified-cap 0/0 · correctness' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '70% · not-targeted 0/0 · simplicity+security+conventions+design' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'src/util/format.ts:?' })).toBeDefined()
      for (const index of [0, 1, 2, 3]) {
        expect(await ui.find({ key: `accept-${index}` })).toBeDefined()
        expect(await ui.find({ key: `kill-${index}` })).toBeDefined()
      }
      // killed and below-floor entries: a dim head, then the location and the summary as on a card
      expect(await ui.find({ type: 'Text', text: 'KILLED (1)' })).toBeDefined()
      expect((await ui.find({ type: 'Text', text: 'HIGH · q=2/2' }))?.props.dimColor).toBe(true)
      expect(await ui.find({ type: 'Text', text: 'src/parse.ts:10' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'BELOW FLOOR (2)' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'HIGH · 40%' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'src/cache/store.ts:77' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'The cache key ignores the locale.' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'SUCCESS CRITERIA' })).toBeDefined()
      expect(await ui.find({ key: 'sc-SC-002' })).toBeDefined()
      await ui.unmount()
    })
  }

  reviewTest('a label outside the four is drawn as given in the text colour; a confidence the return lacked is ?%', REVIEW_POSITION, stateOf([boardOf(1, REVIEW_STREAM, ODD_RETURN)]), async $ => {
    const ui = await mountReview($)
    expect(await ui.find({ type: 'Text', text: '  nit (1)' })).toBeDefined()
    expect((await ui.find({ type: 'Text', text: '▎ nit' }))?.props.color).toBe('text')
    expect(await ui.find({ type: 'Text', text: /^\?% · held 0\/2/ })).toBeDefined()
    await ui.unmount()
  })

  reviewTest('no board yet: the tab names the stream and the phase, then the criteria', REVIEW_POSITION, EMPTY_REVIEW, async $ => {
    const ui = await mountReview($)
    expect(await ui.find({ type: 'Text', text: 'No review captured for feat/example-stream yet (phase review).' })).toBeDefined()
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
    await ui.unmount()
  })

  reviewTest('no board and no phase yet: the tab says the stream has entered none', { ...REVIEW_POSITION, current: null }, EMPTY_REVIEW, async $ => {
    const ui = await mountReview($)
    expect(await ui.find({ type: 'Text', text: 'No review captured for feat/example-stream yet (no phase entered).' })).toBeDefined()
    await ui.unmount()
  })

  reviewTest('a board held for another stream is not drawn; the criteria still list', REVIEW_POSITION, stateOf([boardOf(1, OTHER_STREAM)]), async $ => {
    const ui = await mountReview($)
    expect(await ui.find({ type: 'Text', text: COUNTS })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /^No review captured for feat\/example-stream/ })).toBeDefined()
    expect(await ui.find({ key: 'sc-SC-001' })).toBeDefined()
    await ui.unmount()
  })

  reviewTest('a board captured with no stream is drawn for the stream shown', REVIEW_POSITION, stateOf([boardOf(1, null)]), async $ => {
    const ui = await mountReview($)
    expect(await ui.find({ type: 'Text', text: COUNTS })).toBeDefined()
    expect(await ui.find({ key: 'round-?:1' })).toBeDefined()
    await ui.unmount()
  })

  reviewTest(
    'criteria pre-ticked from the last verdict: met ☑, unmet ☒; the text wraps beside the bold id',
    withVerdict(REVIEW_POSITION, { seq: 51, at: VERDICT_BEFORE, criteria: { [SC1]: 'met', [SC2]: 'unmet' } }),
    EMPTY_REVIEW,
    async $ => {
      const ui = await mountReview($)
      expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      expect((await ui.find({ key: 'sc-SC-002' }))?.props.label).toBe('☒')
      expect((await ui.find({ key: 'sc-SC-001' }))?.props.plain).toBeFalsy()
      expect((await ui.find({ type: 'Text', text: 'SC-002' }))?.props.bold).toBe(true)
      const text = await ui.find({ type: 'Text', text: 'The parser keeps an empty field.' })
      expect(text?.text).toBe('The parser keeps an empty field.')
      expect(text?.props.wrap).toBe('wrap')
      await ui.unmount()
    },
  )

  reviewTest(
    'a tick made against the current verdict wins; one made against another verdict, or for another stream, does not',
    withVerdict(REVIEW_POSITION, { seq: 51, at: VERDICT_BEFORE, criteria: { [SC1]: 'unmet', [SC2]: 'unmet' } }),
    {
      ...EMPTY_REVIEW,
      ticks: [
        { stream: REVIEW_STREAM, criterion: SC1, override: { state: 'on', seq: must(eventSeq(51)) } },
        { stream: REVIEW_STREAM, criterion: SC2, override: { state: 'on', seq: must(eventSeq(40)) } },
        { stream: OTHER_STREAM, criterion: SC2, override: { state: 'on', seq: must(eventSeq(51)) } },
      ],
    },
    async $ => {
      const ui = await mountReview($)
      expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      expect((await ui.find({ key: 'sc-SC-002' }))?.props.label).toBe('☒')
      await ui.unmount()
    },
  )

  reviewTest('a press on a criterion asks for its tick', REVIEW_POSITION, EMPTY_REVIEW, async ($, pressed) => {
    const ui = await mountReview($)
    await ui.press({ key: 'sc-SC-002' })
    expect(pressed).toEqual(['tick SC-002'])
    await ui.unmount()
  })

  reviewTest('Accept and Kill name the round and the survivor; they are dim buttons, not plain', REVIEW_POSITION, stateOf([boardOf(2), boardOf(1)]), async ($, pressed) => {
    const ui = await mountReview($)
    for (const key of ['accept-0', 'kill-0']) {
      const button = await ui.find({ key })
      expect(button?.props.plain).toBeFalsy()
      expect(button?.props.dimColor).toBe(true)
    }
    await ui.press({ key: 'accept-0' })
    await ui.press({ key: 'kill-3' })
    expect(pressed).toEqual(['accept feat/example-stream:2 0', 'kill feat/example-stream:2 3'])
    await ui.unmount()
  })

  reviewTest(
    'a mark is drawn on its card in place of the buttons, and the card is no longer open',
    REVIEW_POSITION,
    stateOf([markSurvivor(markSurvivor(boardOf(), 0, 'accepted'), 1, 'killed')]),
    async $ => {
      const ui = await mountReview($)
      expect((await ui.find({ type: 'Text', text: '✓ accepted' }))?.props.color).toBe('success')
      expect((await ui.find({ type: 'Text', text: '✗ killed' }))?.props.color).toBe('error')
      expect(await ui.find({ key: 'accept-0' })).toBeUndefined()
      expect(await ui.find({ key: 'kill-1' })).toBeUndefined()
      expect(await ui.find({ key: 'accept-2' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'unverified 1 · open 2' })).toBeDefined()
      await ui.unmount()
    },
  )

  reviewTest(
    'a finding the last verdict disposed of shows the disposition, not the buttons, and is not open',
    withVerdict(REVIEW_POSITION, {
      seq: 52,
      at: VERDICT_AFTER,
      dispositions: { 'src/api/handler.ts:42': 'fixed', './pkg/src/util/format.ts:?': 'rejected', 'cache/index.ts:9': 'deferred' },
    }),
    stateOf([boardOf(1, REVIEW_STREAM, ABSOLUTE_RETURN)]),
    async $ => {
      const ui = await mountReview($)
      expect((await ui.find({ type: 'Text', text: 'fixed' }))?.props.color).toBe('success')
      expect((await ui.find({ type: 'Text', text: 'rejected' }))?.props.color).toBe('error')
      const deferred = await ui.find({ type: 'Text', text: 'deferred' })
      expect(deferred?.props.dimColor).toBe(true)
      expect(deferred?.props.color).toBeUndefined()
      expect(await ui.find({ key: 'accept-0' })).toBeUndefined()
      expect(await ui.find({ key: 'kill-2' })).toBeUndefined()
      expect(await ui.find({ key: 'kill-3' })).toBeUndefined()
      // the refuters-died HIGH has neither a mark nor a disposition: its buttons stay
      expect(await ui.find({ key: 'accept-1' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'unverified 1 · open 1' })).toBeDefined()
      await ui.unmount()
    },
  )

  reviewTest(
    'a board captured after the verdict ignores its dispositions',
    withVerdict(REVIEW_POSITION, { seq: 50, at: VERDICT_BEFORE, dispositions: { 'src/api/handler.ts:42': 'fixed' } }),
    stateOf([boardOf()]),
    async $ => {
      const ui = await mountReview($)
      expect(await ui.find({ type: 'Text', text: 'fixed' })).toBeUndefined()
      expect(await ui.find({ key: 'accept-0' })).toBeDefined()
      await ui.unmount()
    },
  )

  reviewTest('two rounds: the newest open, the older folded behind its summary; presses open and fold', REVIEW_POSITION, stateOf([boardOf(2), boardOf(1)]), async ($, pressed) => {
    const ui = await mountReview($)
    expect((await ui.find({ key: 'round-feat/example-stream:2' }))?.props.label).toMatch(/^▾ round 2 · run \? · \d\d:\d\d$/)
    expect((await ui.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · run \? · \d\d:\d\d · 4 survivors$/)
    expect((await ui.findAll({ type: 'Text', text: COUNTS })).length).toBe(1)
    expect((await ui.findAll({ type: 'Text', text: 'SUCCESS CRITERIA' })).length).toBe(1)
    await ui.press({ key: 'round-feat/example-stream:1' })
    await ui.press({ key: 'round-feat/example-stream:2' })
    expect(pressed).toEqual(['open feat/example-stream:1', 'open folded'])
    await ui.unmount()
  })

  reviewTest(
    'the open round follows `open`: the round it names is open, the newest folds',
    REVIEW_POSITION,
    stateOf([boardOf(2), boardOf(1)], { kind: 'round', id: roundId({ stream: REVIEW_STREAM, round: 1 }) }),
    async $ => {
      const ui = await mountReview($)
      expect((await ui.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▾ round 1 · /)
      expect((await ui.find({ key: 'round-feat/example-stream:2' }))?.props.label).toMatch(/^▸ round 2 · /)
      await ui.unmount()
    },
  )

  reviewTest('every round folded: no board body, the criteria stay', REVIEW_POSITION, stateOf([boardOf()], { kind: 'folded' }), async $ => {
    const ui = await mountReview($)
    expect((await ui.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · .* · 4 survivors$/)
    expect(await ui.find({ type: 'Text', text: COUNTS })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: '▎ BLOCKER' })).toBeUndefined()
    expect(await ui.find({ key: 'sc-SC-001' })).toBeDefined()
    await ui.unmount()
  })

  reviewTest('an aborted run: a warning under the counts', REVIEW_POSITION, stateOf([boardOf(1, REVIEW_STREAM, REVIEW_RETURN_ABORTED)]), async $ => {
    const ui = await mountReview($)
    expect((await ui.find({ type: 'Text', text: 'review aborted: no lens finder returned' }))?.props.color).toBe('warning')
    await ui.unmount()
  })

  reviewTest('at 60 columns a card body is two full-width lines, and the counts pack at their separators', REVIEW_POSITION, stateOf([boardOf()]), async $ => {
    const ui = await mountReview($, 'terminal', 60)
    expect((await ui.find({ type: 'Text', text: 'src/api/handler.ts:42' }))?.text).toBe('src/api/handler.ts:42')
    const summary = await ui.find({ type: 'Text', text: /^The handler writes/ })
    expect(summary?.text).toBe('The handler writes the record before the permission check runs.')
    expect(summary?.props.wrap).toBe('wrap')
    expect(await ui.find({ key: 'counts-0' })).toBeDefined()
    expect(await ui.find({ key: 'counts-1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^found 9 · deduped 7/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\s*·/ })).toBeUndefined()
    // the LOW finding has the longest lens list: its meta is cut, the severity cell is not
    const meta = await ui.find({ type: 'Text', text: /^70% · not-targeted/ })
    expect(meta?.text.endsWith('…')).toBe(true)
    expect(meta?.props.wrap).toBe('truncate-end')
    const cells = (await ui.findAll({ type: 'Box', text: /^▎ BLOCKER$/ })).filter(box => typeof box.props.width === 'number')
    expect(cells.length).toBe(1)
    expect(cells[0]?.props.width).toBeGreaterThan('▎ BLOCKER'.length)
    await ui.unmount()
  })

  reviewTest('at 40 columns the header row holds the severity and both bracketed buttons', REVIEW_POSITION, stateOf([boardOf()]), async $ => {
    const ui = await mountReview($, 'terminal', 40)
    expect(await ui.find({ type: 'Text', text: '▎ BLOCKER' })).toBeDefined()
    expect(await ui.find({ key: 'accept-0' })).toBeDefined()
    expect(await ui.find({ key: 'kill-0' })).toBeDefined()
    // 40 − severity 10 − `[ Accept ] [ Kill ]` 19 − 2 leaves 9 cells for the meta
    const meta = await ui.find({ type: 'Text', text: /^95% / })
    expect(meta?.text.length).toBeLessThanOrEqual(9)
    expect(meta?.text.endsWith('…')).toBe(true)
    await ui.unmount()
  })
})

describe('review: the band segment and the counts', () => {
  test('boardFor: the newest round of the stream shown; a stream-less round counts for any; another stream\'s never', async () => {
    expect(boardFor(REVIEW_POSITION, EMPTY_REVIEW)).toBeNull()
    expect(boardFor(REVIEW_POSITION, stateOf([boardOf(1, OTHER_STREAM)]))).toBeNull()
    expect(boardFor(REVIEW_POSITION, stateOf([boardOf(1, OTHER_STREAM), boardOf(3), boardOf(2)]))?.round).toBe(3)
    expect(boardFor(REVIEW_POSITION, stateOf([boardOf(1, null)]))?.stream).toBeNull()
  })

  test('reviewSegment: `review N open` for the newest round, `review aborted`, else null', async () => {
    expect(reviewSegment(REVIEW_POSITION, EMPTY_REVIEW)).toBeNull()
    expect(reviewSegment(REVIEW_POSITION, stateOf([boardOf()]))).toBe('review 4 open')
    expect(reviewSegment(REVIEW_POSITION, stateOf([markSurvivor(boardOf(2), 0, 'killed'), boardOf(1)]))).toBe('review 3 open')
    expect(reviewSegment(REVIEW_POSITION, stateOf([boardOf(1, REVIEW_STREAM, REVIEW_RETURN_ABORTED)]))).toBe('review aborted')
  })

  test('openFindings: neither the user\'s mark nor the orchestrator\'s disposition', async () => {
    const position = withVerdict(REVIEW_POSITION, { seq: 52, at: VERDICT_AFTER, dispositions: { 'src/app.ts:126': 'fixed' } })
    expect(openFindings(REVIEW_POSITION, boardOf())).toBe(4)
    expect(openFindings(position, markSurvivor(boardOf(), 0, 'accepted'))).toBe(2)
  })

  test('reviewCounts: the producer\'s counts in order, `?` for a count the return lacked, `open N` last when given', async () => {
    expect(reviewCounts(boardOf(), 4)).toBe(`${COUNTS} · unverified 1 · open 4`)
    expect(reviewCountSegments(boardOf(), null).at(-1)).toBe('unverified 1')
    const { found: _found, ...counts } = REVIEW_RETURN.counts
    const { coverage: _coverage, ...noCoverage } = { ...REVIEW_RETURN, counts }
    expect(reviewCountSegments(boardOf(1, REVIEW_STREAM, noCoverage), null)).toEqual([
      'found ?',
      'deduped 7',
      'candidates 5',
      'survivors 4',
      'killed 1',
      'below floor 2',
      'refuters ?/?',
      'unverified 1',
    ])
  })
})
