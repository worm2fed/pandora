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
  test('terminal: a flowchart is a box-drawing picture, an svg block is xml Code, no Svg', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, WORKLOG_WITH_DIAGRAMS)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-design' })
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
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, WORKLOG_WITH_DIAGRAMS)
    await $.session.start(START)
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 40 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    await ui.press({ key: 'tab-design' })
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
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n${fan}\n`)
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 40 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    await ui.press({ key: 'tab-design' })
    const note = await ui.find({ type: 'Text', text: /^diagram is \d+ columns wide; the pane has 40$/ })
    expect(note?.props.dimColor).toBe(true)
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
  })

  test('terminal: a chart over 60 nodes is the text form under a note', async ($, on) => {
    const chain = Array.from({ length: 60 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`)
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-design' })
    expect(await ui.find({ type: 'Text', text: 'diagram has 61 nodes; the pane draws up to 60' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    await ui.unmount()
  })

  test('terminal: an LR chart whose TD retry is over 200 rows is the text form under a rows note', async ($, on) => {
    // 46 boxes in a row: 447 columns left to right, 274 rows top to bottom
    const chain = Array.from({ length: 45 }, (_, i) => `  n${i} --> n${i + 1}`).join('\n')
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chain}\n`)
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-design' })
    const note = await ui.find({ type: 'Text', text: 'diagram is 274 rows tall; the pane draws up to 200' })
    expect(note?.props.dimColor).toBe(true)
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[n1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
  })

  test('terminal: the grid fits the room under the indent, not the 40-column floor', async ($, on) => {
    // 39 columns left to right, 55 top to bottom; the section is indented by 2
    const chart = '  n0 --> m1 & m2 & m3 & m4 & m5 & m6 & m7 & m8\n  m1 --> z[zzzzzzzzzzzzzzz]'
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, `flowchart LR\n${chart}\n`)
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    // 40 columns leave a room of 38: the 39-column picture does not fit
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 40 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    await ui.press({ key: 'tab-design' })
    expect(await ui.find({ type: 'Text', text: 'diagram is 39 columns wide; the pane has 40' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\[n0\] ──► \[m1\]/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /│ n0 │/ })).toBeUndefined()
    await ui.unmount()
    // 41 columns leave a room of 39: the picture is drawn
    const wider = { ...PANE, props: { ...PANE.props, bodyColumns: 41 } }
    // the pane keeps the Design tab open across mounts
    const ui2 = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...wider })
    expect(await ui2.find({ type: 'Text', text: /│ n0 │/ })).toBeDefined()
    expect(await ui2.find({ type: 'Text', text: /^diagram / })).toBeUndefined()
    await ui2.unmount()
  })

  test('terminal: a back edge is listed under the picture in the one-line form', async ($, on) => {
    const worklog = WORKLOG_WITH_DIAGRAMS.replace(/flowchart LR\n[^`]*/, 'flowchart LR\n  a --> b --> a\n')
    engineWorld(on)
    journaledWorld(on, STATUS, LOG, worklog)
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    await ui.press({ key: 'tab-design' })
    expect(await ui.find({ type: 'Text', text: /^│ a │──►│ b │/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '[b] ──► [a]' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '[a] ──► [b]' })).toBeUndefined()
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
      expect(await ui.find({ type: 'Text', text: 'src/util/format.ts:?' })).toBeDefined()
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
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
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

  /** The stream's events with a last review-verdict that records `criteria`. */
  const verdictLog = (criteria: Record<string, string>) => ({
    events: [
      ...LOG.events,
      { seq: 50, type: 'review-verdict', ts: '2026-10-01T10:00:00+00:00', data: { verdict: 'not-ready', criteria: { 'SC-001': 'unmet' } } },
      { seq: 51, type: 'review-verdict', ts: '2026-10-01T10:30:00+00:00', data: { verdict: 'ready', criteria } },
    ],
  })

  test('criteria pre-ticked from the last verdict: met ☑, unmet ☒; the text wraps beside the id', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW, verdictLog({ 'SC-001': 'met', 'SC-002': 'unmet' }))
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
    expect((await ui.find({ key: 'sc-SC-002' }))?.props.label).toBe('☒')
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.plain).toBeFalsy()
    expect((await ui.find({ type: 'Text', text: 'SC-002' }))?.props.bold).toBe(true)
    // the whole text, never cut, in a Text that wraps to the pane
    const text = await ui.find({ type: 'Text', text: 'The parser keeps an empty field.' })
    expect(text?.text).toBe('The parser keeps an empty field.')
    expect(text?.props.wrap).toBe('wrap')
    await ui.unmount()
  })

  test('a status other than met or unmet is ☐; a press on an unmet row ticks it, a second press goes back', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW, verdictLog({ 'SC-001': 'partial', 'SC-002': 'unmet' }))
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
    await ui.press({ key: 'sc-SC-002' })
    expect((await ui.find({ key: 'sc-SC-002' }))?.props.label).toBe('☑')
    await ui.press({ key: 'sc-SC-002' })
    expect((await ui.find({ key: 'sc-SC-002' }))?.props.label).toBe('☒')
    await ui.unmount()
  })

  test('a press on a journal-met row unticks it locally; a second press shows the journal again', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW, verdictLog({ 'SC-001': 'met' }))
    await $.session.start(START)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
    await ui.press({ key: 'sc-SC-001' })
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
    await ui.press({ key: 'sc-SC-001' })
    expect((await ui.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
    await ui.unmount()
  })

  test('a disposition keyed by the full path (with ./) matches a five-segment file', async ($, on) => {
    engineWorld(on)
    const at = '2999-01-01T00:00:00+00:00' // a verdict after the capture
    const log = { events: [...LOG.events, { seq: 50, type: 'review-verdict', ts: at, data: { verdict: 'ready', dispositions: { './pkg/core/src/api/handler.ts:42': 'deferred-to-a-later-slice' } } }] }
    journaledWorld(on, IN_REVIEW, log)
    await $.session.start(START)
    await $.prompt.submit({ text: REVIEW_NOTIFICATION.replace('src/api/handler.ts', 'pkg/core/src/api/handler.ts'), origin: { kind: 'task-notification' } } as never)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    // drawn at most 12 cells
    expect((await ui.find({ type: 'Text', text: 'deferred-to…' }))?.props.dimColor).toBe(true)
    expect(await ui.find({ key: 'accept-0' })).toBeUndefined()
    await ui.unmount()
  })

  test('a board captured after the verdict ignores its dispositions', async ($, on) => {
    engineWorld(on)
    // the test clock starts at the epoch: a verdict the day before is older than the capture
    const log = { events: [...LOG.events, { seq: 50, type: 'review-verdict', ts: '1969-12-31T00:00:00+00:00', data: { verdict: 'ready', dispositions: { 'src/api/handler.ts:42': 'fixed' } } }] }
    journaledWorld(on, IN_REVIEW, log)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await ui.find({ type: 'Text', text: 'fixed' })).toBeUndefined()
    expect(await ui.find({ key: 'accept-0' })).toBeDefined()
    await ui.unmount()
  })

  test('a finding the last verdict disposed of shows the disposition, not the buttons, and is not open', async ($, on) => {
    engineWorld(on)
    const log = {
      events: [
        ...LOG.events,
        { seq: 50, type: 'review-verdict', ts: 't', data: { verdict: 'ready', dispositions: { 'src/api/handler.ts:42': 'fixed', 'src/util/format.ts:?': 'deferred' } } },
      ],
    }
    journaledWorld(on, IN_REVIEW, log)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect((await ui.find({ type: 'Text', text: 'fixed' }))?.props.color).toBe('success')
    expect((await ui.find({ type: 'Text', text: 'deferred' }))?.props.dimColor).toBe(true)
    expect(await ui.find({ key: 'accept-0' })).toBeUndefined()
    expect(await ui.find({ key: 'kill-2' })).toBeUndefined()
    // the HIGH finding has neither a mark nor a disposition: its buttons stay
    expect(await ui.find({ key: 'accept-1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^unverified 1 · open 1$/ })).toBeDefined()
    await ui.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Text', text: /review 1 open/ })).toBeDefined()
    await band.unmount()
  })

  test('at 60 columns a card body is two full-width lines, and the counts pack at their separators', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 60 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    expect((await ui.find({ type: 'Text', text: 'src/api/handler.ts:42' }))?.text).toBe('src/api/handler.ts:42')
    const summary = await ui.find({ type: 'Text', text: /^The handler writes/ })
    expect(summary?.text).toBe('The handler writes the record before the permission check runs.')
    expect(summary?.props.wrap).toBe('wrap')
    // the counts: two or more lines, none starting with the separator
    expect(await ui.find({ key: 'counts-0' })).toBeDefined()
    expect(await ui.find({ key: 'counts-1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^found 9 · deduped 8/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\s*·/ })).toBeUndefined()
    await ui.unmount()
  })

  test('at 40 columns the header row holds the severity and both bracketed buttons', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 40 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    expect(await ui.find({ type: 'Text', text: '▎ BLOCKER' })).toBeDefined()
    expect(await ui.find({ key: 'accept-0' })).toBeDefined()
    expect(await ui.find({ key: 'kill-0' })).toBeDefined()
    // 40 − severity 10 − `[ Accept ] [ Kill ]` 19 − 2 leaves 9 cells for the meta
    const meta = await ui.find({ type: 'Text', text: /^95% / })
    expect(meta?.text.length).toBeLessThanOrEqual(9)
    expect(meta?.text.endsWith('…')).toBe(true)
    await ui.unmount()
  })

  test('a disposition named like an Object method is drawn dim, not coloured', async ($, on) => {
    engineWorld(on)
    const log = { events: [...LOG.events, { seq: 50, type: 'review-verdict', ts: 't', data: { verdict: 'ready', dispositions: { 'src/api/handler.ts:42': 'constructor' } } }] }
    journaledWorld(on, IN_REVIEW, log)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    const text = await ui.find({ type: 'Text', text: 'constructor' })
    expect(text?.props.dimColor).toBe(true)
    expect(text?.props.color).toBeUndefined()
    await ui.unmount()
  })

  test('a narrow pane: the card header keeps the severity and cuts the meta', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const narrow = { ...PANE, props: { ...PANE.props, bodyColumns: 60 } }
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...narrow })
    // the LOW finding has the longest lens list
    expect(await ui.find({ type: 'Text', text: '▎ LOW' })).toBeDefined()
    const meta = await ui.find({ type: 'Text', text: /^70% · not-targeted/ })
    expect(meta?.text.endsWith('…')).toBe(true)
    expect(meta?.props.wrap).toBe('truncate-end')
    expect(await ui.find({ key: 'accept-2' })).toBeDefined()
    // the severity cell is wider than its longest label, so `▎ BLOCKER` keeps a gap before its percentage
    const cells = (await ui.findAll({ type: 'Box', text: /^▎ BLOCKER$/ })).filter(box => typeof box.props.width === 'number')
    expect(cells.length).toBe(1)
    expect(cells[0]?.props.width).toBeGreaterThan('▎ BLOCKER'.length)
    await ui.unmount()
  })

  test('Accept and Kill are drawn like Veto: dim buttons, not plain', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, IN_REVIEW)
    await $.session.start(START)
    await $.prompt.submit(notification)
    const ui = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    for (const key of ['accept-0', 'kill-0']) {
      const button = await ui.find({ key })
      expect(button).toBeDefined()
      expect(button?.props.plain).toBeFalsy()
      expect(button?.props.dimColor).toBe(true)
    }
    await ui.unmount()
  })
})
