import { describe, expect, test } from 'claude-code/testing'

import {
  artifactRefs,
  globToRegExp,
  isSafeRef,
  isVetoable,
  matchesHome,
  parseAdr,
  parseBuildPlan,
  parseDesignSection,
  parseDesignSections,
  phaseMarks,
  publishAuthorization,
  reflowMarkdown,
  streamSlug,
  toPosition,
} from '../hooks/position'
import { ADR, FEATURE, LOG, WORKLOG } from './fixtures'
import { PRD_WITH_CRITERIA } from './fixtures.review'

describe('position', () => {
  test('phase marks: phases before the current are done, the current is current', async () => {
    const marks = phaseMarks('implement', [])
    expect(marks.workspace).toBe('done')
    expect(marks.design).toBe('done')
    expect(marks.implement).toBe('current')
    expect(marks.review).toBe('todo')
    expect(marks.capture).toBe('todo')
  })

  test('phase marks: a later phase entered earlier (backward transition) stays done', async () => {
    const marks = phaseMarks('implement', ['workspace', 'implement', 'review', 'implement'])
    expect(marks.review).toBe('done')
    expect(marks.implement).toBe('current')
  })

  test('build plan: tasks in worklog order with their tick state', async () => {
    const tasks = parseBuildPlan(WORKLOG)
    expect(tasks.map(t => t.id)).toEqual(['T001', 'T002', 'T010', 'T011'])
    expect(tasks[0]).toMatchObject({ id: 'T001', title: 'add the widget', section: 'Setup', tickedInWorklog: true })
    expect(tasks[1]).toMatchObject({ id: 'T002', title: 'wire the widget', tickedInWorklog: false })
    expect(tasks[2]).toMatchObject({ id: 'T010', title: 'parse the input', section: 'Feature' })
  })

  test('design section: everything between # Design and # Build Plan', async () => {
    const md = parseDesignSection(WORKLOG)
    expect(md).toContain('## Approach')
    expect(md).toContain('Minimal change')
    expect(md).not.toContain('Build Plan')
    expect(md).not.toContain('T001')
  })

  test('reflow: hard-wrapped prose joins into one line per paragraph, blocks keep their lines', async () => {
    const md = ['The quick brown', 'fox jumps.', '', '- item one', '  continues here', '- item two', '', '```', 'code line', 'kept', '```', '', '## Heading', 'para'].join('\n')
    const out = reflowMarkdown(md).split('\n')
    expect(out[0]).toBe('The quick brown fox jumps.')
    expect(out[2]).toBe('- item one continues here')
    expect(out[3]).toBe('- item two')
    expect(out.slice(5, 9)).toEqual(['```', 'code line', 'kept', '```'])
    expect(out[10]).toBe('## Heading')
    expect(out[11]).toBe('para')
  })

  test('design sections: one per ## heading, bodies reflowed', async () => {
    const sections = parseDesignSections(WORKLOG)
    expect(sections.map(s => s.title)).toEqual(['Approach', 'Architecture'])
    expect(sections[0]?.markdown).toBe('Minimal change: one module, one test.')
    expect(sections[1]?.markdown).toBe('- parser\n- view')
  })

  test('adr: title and status from the frontmatter', async () => {
    expect(parseAdr('docs/adr/0007-example-decision.md', ADR)).toEqual({
      path: 'docs/adr/0007-example-decision.md',
      title: '0007. Example decision',
      status: 'accepted',
    })
  })

  test('toPosition: decisions newest first, tasks cross-checked against the journal', async () => {
    const position = toPosition({
      feature: FEATURE,
      events: LOG.events,
      worklog: { path: 'docs/prd/example.worklog.md', text: WORKLOG },
      adrs: [parseAdr('docs/adr/0007-example-decision.md', ADR)],
    })
    expect(position.stream).toBe('feat/example-stream')
    expect(position.phase).toBe('implement')
    expect(position.version).toBe(12)
    expect(position.decisions.map(d => d.gate)).toEqual(['publish', 'clarify', 'clarify'])
    expect(position.decisions[2]).toMatchObject({ raisedBy: 'orchestrator', mode: 'executive' })
    expect(position.decisions.map(isVetoable)).toEqual([false, false, true])
    const byId = Object.fromEntries(position.tasks.map(t => [t.id, t]))
    expect(byId.T001).toMatchObject({ tickedInWorklog: true, doneInJournal: true, lastVerify: { outcome: 'pass', at: '2026-10-01T09:20:00+00:00' } })
    // the later failing verify-run wins over the earlier pass
    expect(byId.T010?.lastVerify).toEqual({ outcome: 'fail', at: '2026-10-01T09:40:00+00:00' })
    expect(byId.T002).toMatchObject({ tickedInWorklog: false, doneInJournal: false, lastVerify: null })
    // ticked in the worklog, never recorded in the journal: the debt the Stop hook would flag
    expect(byId.T011).toMatchObject({ tickedInWorklog: true, doneInJournal: false })
    expect(position.lastVerify).toEqual({ outcome: 'pass', taskIds: ['T001', 'T010'], at: '2026-10-01T09:20:00+00:00' })
    expect(position.design.adrs[0]?.title).toBe('0007. Example decision')
    expect(position.design.sections.map(s => s.slug)).toEqual(['approach', 'architecture'])
    expect(position.design.sections[0]?.markdown).toContain('Minimal change')
    expect(position.worklogPath).toBe('docs/prd/example.worklog.md')
  })

  test('artifact refs: a context ref on flow-started or phase-entered is not the stream\'s worklog', async () => {
    const context = [
      { seq: 1, type: 'flow-started', ts: 't', data: { request: 'slice 2', refs: ['docs/prd/older.md', 'docs/prd/older.worklog.md'] } },
      { seq: 2, type: 'phase-entered', ts: 't', data: { phase: 'workspace', refs: ['docs/adr/0001-older.md'] } },
      { seq: 3, type: 'deviation', ts: 't', data: { refs: ['docs/prd/older.worklog.md#deviations'] } },
    ]
    expect(artifactRefs(context)).toEqual({ worklog: null, adrs: [], prd: null })
    const committed = [...context, { seq: 4, type: 'design-committed', ts: 't', data: { worklog: 'docs/prd/new.worklog.md', adrs: ['docs/adr/0002-new.md'] } }]
    expect(artifactRefs(committed)).toEqual({ worklog: 'docs/prd/new.worklog.md', adrs: ['docs/adr/0002-new.md'], prd: null })
  })

  test('artifact refs: only safe relative paths are kept', async () => {
    const refs = artifactRefs(LOG.events)
    expect(refs.worklog).toBe('docs/prd/example.worklog.md')
    expect(refs.adrs).toEqual(['docs/adr/0007-example-decision.md'])
    expect(isSafeRef('/etc/x.worklog.md')).toBe(false)
    expect(isSafeRef('../x/adr/0001.md')).toBe(false)
    expect(isSafeRef('C:/x/adr/0001.md')).toBe(false)
    expect(isSafeRef('plugin/docs/adr/0001.md')).toBe(true)
  })

  test('stream slug and sidecar globs', async () => {
    expect(streamSlug('feat/example-stream')).toBe('example-stream')
    expect(streamSlug('feature/example-stream')).toBe('example-stream')
    expect(streamSlug('feat/group/example-stream')).toBe('example-stream')
    expect(streamSlug('example')).toBe('example')
    // fnmatch rules, as shipgate applies them: `*` crosses `/`, `?` is one character, anchored
    const re = globToRegExp('*/docs/prd/*.worklog.md')
    expect(re.test('plugin/docs/prd/example.worklog.md')).toBe(true)
    expect(re.test('a/b/docs/prd/example.worklog.md')).toBe(true)
    expect(re.test('docs/prd/example.worklog.md')).toBe(false)
    expect(globToRegExp('docs/adr/*.md').test('docs/adr/deep/0001-x.md')).toBe(true)
    expect(globToRegExp('docs/?.md').test('docs/a.md')).toBe(true)
    expect(globToRegExp('docs/?.md').test('docs/ab.md')).toBe(false)
    expect(globToRegExp('docs/[ab].md').test('docs/b.md')).toBe(true)
    expect(globToRegExp('a+b(c).md').test('a+b(c).md')).toBe(true)
    // matchesHome adds shipgate's second try: the glob under one more `*` segment
    expect(matchesHome('plugin/docs/prd/x.md', 'docs/prd/*.md')).toBe(true)
    expect(matchesHome('docs/prd/x.md', '*/docs/prd/*.md')).toBe(false)
    expect(matchesHome('plugin/docs/prd/x.md', '*/docs/prd/*.md')).toBe(true)
  })

  test('publish: a ready verdict after the last task-done authorizes, as journal.py checks mr-opened', async () => {
    const ready = { seq: 50, type: 'review-verdict', ts: '2026-10-01T10:00:00+00:00', data: { verdict: 'ready' } }
    expect(publishAuthorization([...LOG.events, ready])).toEqual({ authorized: true, by: 'review-verdict', at: '2026-10-01T10:00:00+00:00' })
    // order by seq, not by array position
    expect(publishAuthorization([ready, ...LOG.events]).authorized).toBe(true)
  })

  test('publish: a ready verdict before a later task-done does not authorize', async () => {
    const early = { seq: 39, type: 'review-verdict', ts: 't', data: { verdict: 'ready' } }
    expect(publishAuthorization([...LOG.events, early])).toEqual({ authorized: false, by: null, at: '' })
    const later = [{ seq: 1, type: 'review-verdict', ts: 't', data: { verdict: 'ready' } }, { seq: 2, type: 'task-done', ts: 't', data: { task_id: 'T1' } }]
    expect(publishAuthorization([...later].reverse()).authorized).toBe(false)
  })

  test('publish: a not-ready verdict does not authorize', async () => {
    expect(publishAuthorization([...LOG.events, { seq: 50, type: 'review-verdict', ts: 't', data: { verdict: 'not-ready' } }]).authorized).toBe(false)
  })

  test('publish: only the user\'s own decision to publish authorizes', async () => {
    const decision = (data: Record<string, unknown>) => [...LOG.events, { seq: 50, type: 'gate-decision', ts: 'at-50', data }]
    expect(publishAuthorization(decision({ gate: 'publish', raised_by: 'user', decision: ' Publish ' }))).toEqual({ authorized: true, by: 'gate-decision', at: 'at-50' })
    expect(publishAuthorization(decision({ gate: 'publish', raised_by: 'orchestrator', decision: 'publish' })).authorized).toBe(false)
    expect(publishAuthorization(decision({ gate: 'publish', raised_by: 'user', decision: 'no' })).authorized).toBe(false)
    expect(publishAuthorization(decision({ gate: 'clarify', raised_by: 'user', decision: 'publish' })).authorized).toBe(false)
  })

  test('publish: no events, no task-done — nothing authorizes until a verdict is recorded', async () => {
    expect(publishAuthorization([])).toEqual({ authorized: false, by: null, at: '' })
    expect(publishAuthorization([{ seq: 3, type: 'review-verdict', ts: 't', data: { verdict: 'ready' } }]).authorized).toBe(true)
  })

  test('toPosition sets publish from the events', async () => {
    expect(toPosition({ feature: FEATURE, events: LOG.events, worklog: null, adrs: [] }).publish.authorized).toBe(false)
    const ready = { seq: 50, type: 'review-verdict', ts: 't', data: { verdict: 'ready' } }
    expect(toPosition({ feature: FEATURE, events: [...LOG.events, ready], worklog: null, adrs: [] }).publish).toEqual({ authorized: true, by: 'review-verdict', at: 't' })
  })

  test('criteria: the clarify-passed event names the PRD, the last one wins', async () => {
    expect(artifactRefs(LOG.events).prd).toBe('docs/prd/example.md')
    const later = { seq: 50, type: 'clarify-passed', ts: 't', data: { prd: 'docs/prd/second.md#success-criteria' } }
    expect(artifactRefs([...LOG.events, later]).prd).toBe('docs/prd/second.md')
    // a PRD ref on another event type is context, never the stream's PRD
    expect(artifactRefs([{ seq: 1, type: 'flow-started', ts: 't', data: { prd: 'docs/prd/older.md' } }]).prd).toBeNull()
  })

  test('criteria: an absolute, a parent-traversal or a non-Markdown PRD ref is not read', async () => {
    const passed = (prd: unknown) => [{ seq: 1, type: 'clarify-passed', ts: 't', data: { prd } }]
    expect(artifactRefs(passed('/etc/prd.md')).prd).toBeNull()
    expect(artifactRefs(passed('../outside/prd.md')).prd).toBeNull()
    expect(artifactRefs(passed('docs/../../prd.md')).prd).toBeNull()
    expect(artifactRefs(passed('docs/prd/example.txt')).prd).toBeNull()
    expect(artifactRefs(passed(42)).prd).toBeNull()
    // a later unsafe ref does not erase an earlier safe one
    expect(artifactRefs([...passed('docs/prd/a.md'), ...passed('/etc/b.md')]).prd).toBe('docs/prd/a.md')
  })

  test('criteria: toPosition parses the PRD\'s success criteria; none without a PRD', async () => {
    const position = toPosition({ feature: FEATURE, events: LOG.events, worklog: null, adrs: [], prd: { path: 'docs/prd/example.md', text: PRD_WITH_CRITERIA } })
    expect(position.criteria.map(c => c.id)).toEqual(['SC-001', 'SC-002', 'SC-003', 'SC-004', 'SC-010'])
    expect(position.criteria[1]).toEqual({ id: 'SC-002', text: 'The pane lists the Build Plan, wrapped onto a second line.' })
    expect(toPosition({ feature: FEATURE, events: LOG.events, worklog: null, adrs: [] }).criteria).toEqual([])
    expect(toPosition({ feature: FEATURE, events: LOG.events, worklog: null, adrs: [], prd: null }).criteria).toEqual([])
  })

  test('toPosition: no worklog and no events still yields a position', async () => {
    const position = toPosition({ feature: FEATURE, events: [], worklog: null, adrs: [] })
    expect(position.tasks).toEqual([])
    expect(position.design.sections).toEqual([])
    expect(position.phases.implement).toBe('current')
  })
})
