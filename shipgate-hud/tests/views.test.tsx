import { describe, expect, test } from 'claude-code/testing'

import { clock, parseAdr, toPosition } from '../hooks/position'
import { defaultTab, packSegments, summaryOf } from '../hooks/views'
import { ADR, FEATURE, LOG, WORKLOG } from './fixtures'
import { BAND, PANE, START, engineWorld, journaledWorld } from './world'

const POSITION = toPosition({
  feature: FEATURE,
  events: LOG.events,
  worklog: { path: 'docs/prd/example.worklog.md', text: WORKLOG },
  adrs: [parseAdr('docs/adr/0007-example-decision.md', ADR)],
})

describe('views', () => {
  test('default tab follows the phase', async () => {
    expect(defaultTab('implement')).toBe('plan')
    expect(defaultTab('design')).toBe('design')
    expect(defaultTab('clarify')).toBe('flow')
  })

  test('summary line carries stream, phase, tasks, verify and the veto count', async () => {
    const at = clock('2026-10-01T09:20:00+00:00')
    expect(summaryOf(POSITION)).toBe(`feat/example-stream · implement · tasks 2/4 · verify pass ${at} · 1 to veto`)
  })

  test('segments pack into lines of the given width, never split, never cut unless alone too wide', async () => {
    const segments = ['feat/example-stream', 'implement', 'tasks 2/4', 'verify pass 09:20', '1 to veto']
    expect(packSegments(segments, 120)).toEqual(['feat/example-stream · implement · tasks 2/4 · verify pass 09:20 · 1 to veto'])
    expect(packSegments(segments, 40)).toEqual(['feat/example-stream · implement', 'tasks 2/4 · verify pass 09:20', '1 to veto'])
    expect(packSegments(segments, 10)).toEqual(['feat/exam…', 'implement', 'tasks 2/4', 'verify pa…', '1 to veto'])
    expect(packSegments([], 40)).toEqual([])
  })

  test('a narrow band wraps the summary onto more rows instead of cutting it', async ($, on) => {
    engineWorld(on)
    journaledWorld(on)
    await $.session.start(START)
    const narrow = { ...BAND, props: { ...BAND.props, bodyColumns: 52 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    const first = await ui.find({ type: 'Text', text: /feat\/example-stream/ })
    expect(first?.text).toBe('feat/example-stream · implement')
    expect(await ui.find({ type: 'Text', text: /^tasks 2\/4 · verify pass/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /1 to veto/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /…/ })).toBeUndefined()
    expect(await ui.find({ key: 'open-hud' })).toBeDefined()
    await ui.unmount()
  })

  test('band draws the summary on terminal and desktop once a position is known', async ($, on) => {
    engineWorld(on)
    journaledWorld(on)
    await $.session.start(START)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface, ...BAND })
      const summary = await ui.find({ type: 'Text', text: /feat\/example-stream/ })
      expect(summary?.text).toContain('tasks 2/4')
      expect(await ui.find({ key: 'open-hud' })).toBeDefined()
      await ui.unmount()
    }
  })

  test('pane opens on the Plan tab in implement, with the debt task flagged', async ($, on) => {
    engineWorld(on)
    journaledWorld(on)
    await $.session.start(START)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface, ...PANE })
      expect(await ui.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
      // one row per task: a fixed glyph+id cell, the title wrapping beside it, the verify tail at the end
      expect(await ui.find({ type: 'Text', text: '◐ T011' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'ticked, no task-done' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '✓ T001' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: `pass ${clock('2026-10-01T09:20:00+00:00')}` })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '✗ T010' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: `fail ${clock('2026-10-01T09:40:00+00:00')}` })).toBeDefined()
      expect((await ui.find({ type: 'Text', text: 'add the widget' }))?.props.wrap).toBe('wrap')
      // Build Plan sections head their tasks; the active tab and the current phase are inverted
      expect(await ui.find({ type: 'Text', text: 'SETUP' })).toBeDefined()
      expect((await ui.find({ type: 'Text', text: /IMP ●/ }))?.props.inverse).toBe(true)
      expect(await ui.find({ type: 'Text', text: 'DSN ✓' })).toBeDefined()
      expect((await ui.find({ type: 'Text', text: ' 2 Plan ' }))?.props.inverse).toBe(true)
      expect(await ui.find({ key: 'tab-plan' })).toBeUndefined()
      expect(await ui.find({ key: 'tab-flow' })).toBeDefined()
      await ui.unmount()
    }
  })

  test('Flow tab lists decisions newest first with a Veto only for the orchestrator', async ($, on) => {
    const { submitted } = engineWorld(on)
    journaledWorld(on)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-flow' })
    const decisions = await ui.findAll({ type: 'Text', text: /^▎ (publish|clarify)/ })
    expect(decisions.map(d => d.text)).toEqual(['▎ publish', '▎ clarify', '▎ clarify'])
    // the question wraps beside a fixed label instead of being cut; the Veto is a bracketed, dim button
    expect((await ui.find({ type: 'Text', text: 'PRD for a prose-only fix?' }))?.props.wrap).toBe('wrap')
    expect((await ui.find({ key: 'veto-0' }))?.props.plain).toBeUndefined()
    // seq 0: orchestrator in executive mode (vetoable); seq 1: orchestrator in ask mode (the user
    // answered it); seq 2: the user's own publish decision
    expect(await ui.find({ key: 'veto-0' })).toBeDefined()
    expect(await ui.find({ key: 'veto-1' })).toBeUndefined()
    expect(await ui.find({ key: 'veto-2' })).toBeUndefined()
    await ui.press({ key: 'veto-0' })
    expect(submitted.length).toBe(1)
    // the prompt names the decision; it never carries the journal's question or decision text
    expect(submitted[0]).toContain('gate decision 3 of 3 in stream feat/example-stream')
    expect(submitted[0]).toContain('gate clarify, recorded 2026-10-01T08:00:00+00:00')
    expect(submitted[0]).not.toContain('PRD for a prose-only fix?')
    expect(submitted[0]).not.toContain('executive assumptions in the worklog')
    await ui.unmount()
  })

  test('Design tab shows the ADR and the worklog Design section', async ($, on) => {
    engineWorld(on)
    journaledWorld(on)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'desktop', ...PANE })
    await ui.press({ key: 'tab-design' })
    expect(await ui.find({ type: 'Text', text: /0007\. Example decision/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /accepted/ })).toBeDefined()
    // the first section is open, the others fold behind a button
    expect((await ui.find({ key: 'design-md-approach' }))?.text).toContain('Minimal change')
    expect(await ui.find({ key: 'design-md-architecture' })).toBeUndefined()
    await ui.press({ key: 'design-architecture' })
    expect((await ui.find({ key: 'design-md-architecture' }))?.text).toContain('- parser')
    expect(await ui.find({ key: 'design-md-approach' })).toBeUndefined()
    await ui.unmount()
  })

  test('pane with no position says so', async $ => {
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await ui.find({ type: 'Text', text: /No shipgate stream/ })).toBeDefined()
    await ui.unmount()
  })
})
