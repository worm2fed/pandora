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
  reflowMarkdown,
  streamSlug,
  toPosition,
} from '../hooks/position'
import { ADR, FEATURE, LOG, WORKLOG } from './fixtures'

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

  test('toPosition: no worklog and no events still yields a position', async () => {
    const position = toPosition({ feature: FEATURE, events: [], worklog: null, adrs: [] })
    expect(position.tasks).toEqual([])
    expect(position.design.sections).toEqual([])
    expect(position.phases.implement).toBe('current')
  })
})
