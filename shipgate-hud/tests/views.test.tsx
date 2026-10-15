import { describe, expect, test } from 'claude-code/testing'

import { clock, parseAdr, toPosition } from '../hooks/position'
import { defaultTab, packSegments, summaryOf } from '../hooks/views'
import { ADR, FEATURE, LOG, STATUS, WORKLOG, WORKLOG_WITH_DIAGRAMS } from './fixtures'
import { BAND, PANE, START, engineWorld, journaledWorld } from './world'
import { REVIEW_NOTIFICATION } from './fixtures.review'

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

const SVG_SOURCE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'

describe('design diagrams', () => {
  test('terminal: a flowchart is box-and-arrow text, an svg block is xml Code, no Svg', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, WORKLOG_WITH_DIAGRAMS)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-design' })
    // the prose around the blocks stays Markdown
    expect((await ui.find({ key: 'design-md-data-flow' }))?.text).toContain('through a queue')
    expect(await ui.find({ type: 'Markdown', text: /only writer of record/ })).toBeDefined()
    const arrow = await ui.find({ type: 'Text', text: /\[api\] ──enqueue──► \[queue\]/ })
    expect(arrow).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /\[worker\] ──write──► \[store\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Svg' })).toBeUndefined()
    const code = await ui.find({ type: 'Code' })
    expect(code?.props.language).toBe('xml')
    expect(code?.props.source).toBe(SVG_SOURCE)
    await ui.unmount()
  })

  test('desktop: a flowchart and an svg block are Svg with the section title as alt', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, WORKLOG_WITH_DIAGRAMS)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'desktop', ...PANE })
    await ui.press({ key: 'tab-design' })
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
      engineWorld(on)
      journaledWorld(on, STATUS, LOG, WORKLOG_WITH_DIAGRAMS)
      await $.session.start(START)
      const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface, ...PANE })
      await ui.press({ key: 'tab-design' })
      await ui.press({ key: 'design-sequence' })
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
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`).replace(SVG_SOURCE, bigSvg)
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'desktop', ...PANE })
    await ui.press({ key: 'tab-design' })
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

describe('review tab', () => {
  const IN_REVIEW = { ...STATUS, features: [{ ...FEATURE, phase: 'review', phase_entered_at: '2026-10-01T10:00:00+00:00' }] }
  const notification = { text: REVIEW_NOTIFICATION, origin: { kind: 'task-notification' } } as never

  test('the Review tab opens by default in the review phase', async () => {
    expect(defaultTab('review')).toBe('review')
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`${surface}: in review the pane opens on the board, survivors grouped by severity`, async ($, on) => {
      engineWorld(on)
      journaledWorld(on, IN_REVIEW)
      await $.session.start(START)
      await $.prompt.submit(notification)
      const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface, ...PANE })
      expect((await ui.find({ type: 'Text', text: ' 4 Review ' }))?.props.inverse).toBe(true)
      expect(await ui.find({ key: 'tab-review' })).toBeUndefined()
      expect(await ui.find({ type: 'Text', text: /^found 9 · deduped 8 · candidates 5 · survivors 3/ })).toBeDefined()
      const headers = await ui.findAll({ type: 'Text', text: /^ {2}(BLOCKER|HIGH|MEDIUM|LOW) \(\d+\)$/ })
      expect(headers.map(h => h.text)).toEqual(['  BLOCKER (1)', '  HIGH (1)', '  LOW (1)'])
      const cards = await ui.findAll({ type: 'Text', text: /^▎ / })
      expect(cards.map(c => c.text)).toEqual(['▎ BLOCKER', '▎ HIGH', '▎ LOW'])
      expect((await ui.find({ type: 'Text', text: '▎ BLOCKER' }))?.props.color).toBe('error')
      expect(await ui.find({ type: 'Text', text: '70% · not-targeted 0/0 · simplicity+security+conventions+design' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  src/util/format.ts:?' })).toBeDefined()
      expect(await ui.find({ key: 'accept-2' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'KILLED (1)' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'BELOW FLOOR (2)' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'SUCCESS CRITERIA' })).toBeDefined()
      expect(await ui.find({ key: 'sc-SC-002' })).toBeDefined()
      await ui.unmount()
    })
  }

  test('no board yet: the tab names the stream and the phase, then the criteria', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await ui.find({ type: 'Text', text: 'No review captured for feat/example-stream yet (phase review).' })).toBeDefined()
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐ SC-001 The widget draws the input.')
    await ui.unmount()
  })

  test('the band counts the open findings while a board for the stream is held', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    const before = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await before.find({ type: 'Text', text: /review \d+ open/ })).toBeUndefined()
    await before.unmount()
    await $.prompt.submit(notification)
    const after = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await after.find({ type: 'Text', text: /review 3 open/ })).toBeDefined()
    await after.unmount()
  })
})
