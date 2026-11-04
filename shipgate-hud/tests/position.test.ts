import { describe, expect, test } from 'claude-code/testing'

import { type PositionDoc, type PositionTask, decodePosition, isoTime, projectPath, taskId } from '../hooks/journal'
import {
  type PositionInputs,
  clock,
  globToRegExp,
  isSafeRef,
  isVetoable,
  matchesHome,
  parseAdr,
  parseDesignSection,
  parseDesignSections,
  parseReviewNotes,
  reflowMarkdown,
  toPosition,
} from '../hooks/position'
import type { Phase, PhaseMark, ProjectPath } from '../types'
import { type Gen, bool, forAll, int, orNull, pick } from './arbitrary'
import { ADR, WORKLOG } from './fixtures'
import { POSITION_GOLDEN } from './fixtures.journal'
import { PRD_WITH_CRITERIA, REVIEW_WORKLOG, must } from './fixtures.review'

/** A golden position decoded; a thrown error naming the path when it does not decode. */
const docOf = (raw: unknown): PositionDoc => {
  const decoded = decodePosition(raw)
  if (!decoded.ok) throw new Error(`fixture: position does not decode: ${decoded.error.kind === 'BadShape' ? decoded.error.error.path : decoded.error.kind}`)
  return decoded.value
}

const pathOf = (raw: string): ProjectPath => must(projectPath(raw))

const FLOW_DOC = docOf(POSITION_GOLDEN.flow)

/** The flow stream with every artifact it names read: the worklog (the generic fixture text), one ADR, the PRD. */
const FLOW_INPUTS: PositionInputs = {
  doc: FLOW_DOC,
  worklog: { path: pathOf('docs/prd/golden-flow.worklog.md'), text: WORKLOG },
  adrs: [parseAdr(pathOf('docs/adr/0001-golden-choice.md'), ADR)],
  prd: { path: pathOf('docs/prd/golden-flow.md'), text: PRD_WITH_CRITERIA },
}

/** A golden stream with nothing read beside its document. */
const bare = (doc: PositionDoc): PositionInputs => ({ doc, worklog: null, adrs: [], prd: null })

const ALL_MARKS = (mark: PhaseMark): Readonly<Record<Phase, PhaseMark>> => ({
  workspace: mark,
  'route-and-map': mark,
  explore: mark,
  clarify: mark,
  design: mark,
  implement: mark,
  review: mark,
  capture: mark,
})

describe('position: toPosition', () => {
  test('the journal\'s facts as the document gives them; decisions newest first with their real seq', async () => {
    const position = toPosition(FLOW_INPUTS)
    expect(position.stream).toBe('feature/golden-flow')
    expect(position.version).toBe(17)
    expect(position.lifecycle).toBe('live')
    expect(position.current).toEqual(FLOW_DOC.current)
    expect(position.phases).toEqual(FLOW_DOC.phases)
    expect(position.decisions.map(decision => decision.seq)).toEqual([42, 29])
    expect(position.decisions.map(isVetoable)).toEqual([false, true])
    expect(position.lastVerify).toEqual({ outcome: 'fail', taskIds: ['T002'], at: '2026-10-01T11:54:00+00:00' })
    expect(position.lastVerdict).toEqual(FLOW_DOC.verdict)
  })

  test('the trace and the folded dispositions are the document\'s, read from position, no other run', async () => {
    const signals = docOf(POSITION_GOLDEN.signals)
    expect(toPosition(bare(signals)).trace).toEqual(signals.trace)
    const dispositions = docOf(POSITION_GOLDEN.dispositions)
    expect(toPosition(bare(dispositions)).dispositions).toEqual(dispositions.dispositions)
    expect(Object.keys(toPosition(bare(dispositions)).dispositions)).toEqual(['src/golden.py:12', 'src/golden.py:30', 'src/other.py:?'])
  })

  test('the review notes come from the worklog the document names; none without a worklog', async () => {
    expect(toPosition(bare(FLOW_DOC)).reviewNotes).toEqual([])
    expect(toPosition(FLOW_INPUTS).reviewNotes).toEqual(parseReviewNotes(WORKLOG))
    const withReview = toPosition({ ...FLOW_INPUTS, worklog: { path: pathOf('docs/prd/golden-flow.worklog.md'), text: REVIEW_WORKLOG } })
    expect(withReview.reviewNotes).toEqual(parseReviewNotes(REVIEW_WORKLOG))
    expect(withReview.reviewNotes.length).toBeGreaterThan(0)
  })

  // D6: the publish rule is the journal's, never re-derived from events
  test('D6: publish is the document\'s, the authorizing event named by its seq', async () => {
    expect(toPosition(FLOW_INPUTS).publish).toEqual({ kind: 'authorized', by: 'gate-decision', seq: 42, at: '2026-10-01T11:55:00+00:00' })
    expect(toPosition(bare(docOf(POSITION_GOLDEN.named))).publish).toEqual({ kind: 'held' })
  })

  test('the plan: the worklog, how the journal found it, and each task\'s state, first match wins', async () => {
    expect(toPosition(FLOW_INPUTS).plan).toEqual({
      worklog: 'docs/prd/golden-flow.worklog.md',
      from: 'event',
      tasks: [
        { id: 'T001', title: 'the declarations', section: 'Declarations', state: 'done', lastVerifyAt: '2026-10-01T11:50:00+00:00' },
        { id: 'T002', title: 'the bodies', section: 'Bodies', state: 'failed', lastVerifyAt: '2026-10-01T11:54:00+00:00' },
        { id: 'T003', title: 'a star bullet', section: 'Bodies', state: 'debt', lastVerifyAt: null },
        { id: 'T004', title: null, section: 'Bodies', state: 'open', lastVerifyAt: null },
      ],
    })
    const named = docOf(POSITION_GOLDEN.named)
    const plan = toPosition({ ...bare(named), worklog: { path: pathOf('docs/prd/golden-named.worklog.md'), text: WORKLOG } }).plan
    expect(plan?.from).toBe('name')
    // ticked, no task-done, a passing verify: debt, its last verify kept; a bold id (`**T002**:`, issue #4) is a task too
    expect(plan?.tasks).toEqual([
      { id: 'T001', title: 'found by its name, not by an event', section: null, state: 'debt', lastVerifyAt: '2026-10-01T11:38:00+00:00' },
      { id: 'T002', title: 'a bold id', section: null, state: 'debt', lastVerifyAt: null },
    ])
  })

  // D9: the Build Plan grammar is the journal's (check's), not a TypeScript copy
  test('D9: the tasks are the journal\'s, including a `*` bullet, whatever the worklog text the HUD read lists', async () => {
    // the worklog text read lists T001, T002, T010 and T011; the journal parsed T001 to T004
    const tasks = toPosition(FLOW_INPUTS).plan?.tasks ?? []
    expect(tasks.map(task => task.id)).toEqual(['T001', 'T002', 'T003', 'T004'])
    expect(tasks[2]).toMatchObject({ id: 'T003', title: 'a star bullet', state: 'debt' })
  })

  test('no plan: no worklog in the document, a worklog the HUD could not read, or one the journal could not read', async () => {
    expect(toPosition(bare(docOf(POSITION_GOLDEN.epic))).plan).toBeNull()
    expect(toPosition({ ...FLOW_INPUTS, worklog: null }).plan).toBeNull()
    expect(toPosition({ ...FLOW_INPUTS, doc: { ...FLOW_DOC, tasks: null } }).plan).toBeNull()
    // a Build Plan with no task line is a plan with no task
    expect(toPosition({ ...FLOW_INPUTS, doc: { ...FLOW_DOC, tasks: [] } }).plan?.tasks).toEqual([])
  })

  // D7: no phase entered is null, never `workspace`
  test('D7: a stream that entered no phase has no current phase, and every phase is to do', async () => {
    const position = toPosition(bare(docOf(POSITION_GOLDEN.started)))
    expect(position.current).toBeNull()
    expect(position.phases).toEqual(ALL_MARKS('todo'))
  })

  // D8: skipped and implied phases are not done
  test('D8: phases the stream jumped past are skipped, not done; one it came back from is revisited', async () => {
    const named = toPosition(bare(docOf(POSITION_GOLDEN.named)))
    expect(named.current?.isImplied).toBe(true)
    expect([named.phases.workspace, named.phases['route-and-map'], named.phases.explore, named.phases.clarify, named.phases.design]).toEqual(['skipped', 'skipped', 'skipped', 'skipped', 'skipped'])
    const flow = toPosition(FLOW_INPUTS)
    expect([flow.phases.workspace, flow.phases['route-and-map'], flow.phases.review]).toEqual(['done', 'skipped', 'revisited'])
  })

  // D10: the lifecycle is kept, never dropped
  test('D10: a terminal stream stays terminal; a dormant one dormant', async () => {
    expect(toPosition(bare(docOf(POSITION_GOLDEN.done))).lifecycle).toBe('terminal')
    expect(toPosition(bare(docOf(POSITION_GOLDEN.dormant))).lifecycle).toBe('dormant')
  })

  // D13: the journal classifies the ADRs with the configured homes; the HUD lists what it names
  test('D13: an ADR from a custom home is listed', async () => {
    const custom = 'notes/decisions/0003-golden-custom.md'
    const doc = docOf({ ...POSITION_GOLDEN.flow, artifacts: { ...POSITION_GOLDEN.flow.artifacts, adrs: [custom] } })
    expect(doc.artifacts.adrs).toEqual([custom])
    const position = toPosition({ ...FLOW_INPUTS, doc, adrs: [parseAdr(pathOf(custom), ADR)] })
    expect(position.design.adrs).toEqual([{ path: custom, title: '0007. Example decision', status: 'accepted' }])
  })

  test('the design: the ADRs read, the worklog\'s Design sections; the criteria from the PRD', async () => {
    const position = toPosition(FLOW_INPUTS)
    expect(position.design.adrs.map(adr => adr.title)).toEqual(['0007. Example decision'])
    expect(position.design.sections.map(section => section.slug)).toEqual(['approach', 'architecture'])
    expect(position.criteria.map(criterion => criterion.id)).toEqual(['SC-001', 'SC-002', 'SC-003', 'SC-004', 'SC-010'])
    expect(position.criteria[1]).toEqual({ id: 'SC-002', text: 'The pane lists the Build Plan, wrapped onto a second line.' })
  })

  test('nothing read: no sections, no criteria', async () => {
    const position = toPosition(bare(FLOW_DOC))
    expect(position.design).toEqual({ adrs: [], sections: [] })
    expect(position.criteria).toEqual([])
    expect(position.plan).toBeNull()
  })

  const AT = must(isoTime('2026-10-01T11:00:00+00:00'))
  const taskGen: Gen<PositionTask> = rng => ({
    id: must(taskId(`T${int(1, 999)(rng)}`)),
    title: orNull(pick(['a title', 'another one']))(rng),
    section: orNull(pick(['Setup', 'Bodies']))(rng),
    isTicked: bool(rng),
    isDone: bool(rng),
    lastVerify: orNull(rng2 => ({ outcome: pick(['pass', 'fail'] as const)(rng2), at: AT }), 3)(rng),
  })

  test('task state law: failed when its last verify failed, else done, else debt when ticked, else open; the line and the verify time kept', async () => {
    forAll(20261020, 500, taskGen, task => {
      const [mapped] = toPosition({ ...FLOW_INPUTS, doc: { ...FLOW_DOC, tasks: [task] } }).plan?.tasks ?? []
      const state = task.lastVerify?.outcome === 'fail' ? 'failed' : task.isDone ? 'done' : task.isTicked ? 'debt' : 'open'
      expect(mapped).toEqual({ id: task.id, title: task.title, section: task.section, state, lastVerifyAt: task.lastVerify?.at ?? null })
    })
  })
})

describe('position: markdown for display', () => {
  test('design section: everything between # Design and # Build Plan; null without a Design heading', async () => {
    const md = parseDesignSection(WORKLOG)
    expect(md).toContain('## Approach')
    expect(md).toContain('Minimal change')
    expect(md).not.toContain('Build Plan')
    expect(md).not.toContain('T001')
    expect(parseDesignSection('# Worklog\n\n# Build Plan\n- [ ] T001 — x\n')).toBeNull()
    expect(parseDesignSections('# Worklog\n')).toEqual([])
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

  test('adr: title and status from the frontmatter; the file name for a missing title; null for a missing status', async () => {
    expect(parseAdr(pathOf('docs/adr/0007-example-decision.md'), ADR)).toEqual({
      path: 'docs/adr/0007-example-decision.md',
      title: '0007. Example decision',
      status: 'accepted',
    })
    expect(parseAdr(pathOf('notes/decisions/0003-golden-custom.md'), '# 0003. No frontmatter\n')).toEqual({
      path: 'notes/decisions/0003-golden-custom.md',
      title: '0003-golden-custom',
      status: null,
    })
    expect(parseAdr(pathOf('docs/adr/0004-x.md'), '---\ntitle: "0004. Quoted"\nstatus:\n---\n')).toEqual({ path: 'docs/adr/0004-x.md', title: '0004. Quoted', status: null })
  })

  test('only safe relative paths are refs the HUD reads', async () => {
    expect(isSafeRef('/etc/x.worklog.md')).toBe(false)
    expect(isSafeRef('../x/adr/0001.md')).toBe(false)
    expect(isSafeRef('C:/x/adr/0001.md')).toBe(false)
    expect(isSafeRef('plugin/docs/adr/0001.md')).toBe(true)
  })

  test('sidecar globs, as the refresh trigger matches a written path', async () => {
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

  // R1-F6: the trigger stripped any run of `.` and `/` from a glob's front, and read a class's
  // leading `^` as a negation; journal.py's `_matches_glob` strips exactly `./`, and fnmatch
  // reads `^` there as itself (only `!` negates). Each row is what `_matches_glob` answers.
  const fnmatchRows: readonly (readonly [string, string, boolean])[] = [
    // one leading `./` goes, and only that
    ['plugin/docs/prd/x.md', './docs/prd/*.md', true],
    ['docs/prd/x.md', './docs/prd/*.md', false],
    ['./docs/prd/x.md', './docs/prd/*.md', true],
    ['a/.notes/x.md', '.notes/*.md', true],
    // a leading `/` is no `./`: it stays, so the second try needs `//`
    ['plugin/docs/prd/x.md', '/docs/prd/*.md', false],
    ['docs/prd/x.md', '/docs/prd/*.md', false],
    ['/docs/prd/x.md', '/docs/prd/*.md', true],
    // `.//` loses its `./` only
    ['a/docs/x.md', './/docs/*.md', false],
    ['a//docs/x.md', './/docs/*.md', true],
    // `^` first in a class is itself; `!` negates
    ['docs/b.md', 'docs/[^a].md', false],
    ['docs/^.md', 'docs/[^a].md', true],
    ['docs/a.md', 'docs/[^a].md', true],
    ['docs/b.md', 'docs/[!a].md', true],
    ['docs/a.md', 'docs/[!a].md', false],
    ['docs/!.md', 'docs/[!a].md', true],
    ['docs/^.md', 'docs/[!^].md', false],
    ['docs/b.md', 'docs/[!^].md', true],
    ['docs/_.md', 'docs/[^-a].md', true], // `^-a` is a range, `^` its first end
  ]
  for (const [path, glob, expected] of fnmatchRows) {
    test(`R1-F6: matchesHome(${JSON.stringify(path)}, ${JSON.stringify(glob)}) is ${expected}, as journal.py's _matches_glob`, async () => {
      expect(matchesHome(path, glob)).toBe(expected)
    })
  }

  test('clock: HH:MM in the local zone', async () => {
    expect(clock(must(isoTime('2026-10-01T11:42:00+00:00')))).toMatch(/^\d\d:\d\d$/)
  })
})

describe('position: parseReviewNotes (HUD ADR 0009)', () => {
  test('every item under a review heading, in worklog order: its location, its first sentence after the location, its whole text', async () => {
    expect(parseReviewNotes(REVIEW_WORKLOG)).toEqual([
      {
        location: { path: 'src/widget/widget.test.ts', line: null },
        sentence: 'the widget test misses the empty case.',
        body: 'F1 MEDIUM `src/widget/widget.test.ts:?` — the widget test misses the empty case. It passes on any input.',
      },
      {
        location: { path: 'src/api/handler.ts', line: 42 },
        sentence: 'the handler writes before the check.',
        body: '`src/api/handler.ts:42` (HIGH 80): the handler writes before the check. The check now runs first.',
      },
      {
        location: null,
        sentence: 'The sync flush drops older rows when flush-older-sync runs twice.',
        body: 'The sync flush drops older rows when flush-older-sync runs twice. A guard keeps them. It also logs the drop.',
      },
      {
        location: { path: 'src/cache.ts', line: 7 },
        sentence: 'the cache is read before it is filled!',
        body: '`./src/cache.ts:7` — the cache is read before it is filled! A second sentence.',
      },
      {
        location: { path: 'src/report.ts', line: null },
        sentence: 'stale-report: the report reads an old snapshot.',
        body: '`src/report.ts:?` — stale-report: the report reads an old snapshot.',
      },
      {
        location: { path: 'src/deep.ts', line: 3 },
        sentence: 'a deeper heading stays inside the section.',
        body: 'F2 `src/deep.ts:3` — a deeper heading stays inside the section.',
      },
      {
        location: { path: 'src/util/format.ts', line: 12 },
        sentence: 'the helper duplicates fmt.ts.',
        body: '`src/util/format.ts:12`: the helper duplicates `fmt.ts`. Rejected: it is the formatter.',
      },
      { location: null, sentence: 'No location here, just text?', body: 'No location here, just text? Yes.' },
    ])
  })

  test('no review heading, no notes: the Design and Build Plan lists are not review items', async () => {
    expect(parseReviewNotes(WORKLOG)).toEqual([])
    expect(parseReviewNotes('')).toEqual([])
    expect(parseReviewNotes('# Reviewer notes\n\n- `src/a.ts:1` — not a round.\n')).toEqual([])
  })

  test('a review heading at any level opens the section; a heading at the same or a higher level closes it; a deeper one stays inside', async () => {
    const worklog = [
      '# Build Plan',
      '- [ ] T001 — `src/plan.ts:1` — a task.',
      '## review round 2',
      '- `src/a.ts:1` — inside.',
      '### Notes',
      '- `src/b.ts:2` — still inside.',
      '## Deviations',
      '- `src/c.ts:3` — outside again.',
      '### Rejected Findings',
      '- `src/d.ts:4` — a rejected one, any case.',
      '# Next',
      '- `src/e.ts:5` — outside.',
    ].join('\n')
    expect(parseReviewNotes(worklog).map(note => note.location?.path)).toEqual(['src/a.ts', 'src/b.ts', 'src/d.ts'])
  })

  test('a fence is inert, with either marker; a blank line or an unindented line ends an item; a nested item is an item of its own', async () => {
    const worklog = [
      '# Review round 1',
      '~~~',
      '- `src/fenced.ts:1` — inert.',
      '# Capture',
      '~~~',
      '- `src/a.ts:1` — one.',
      '',
      '  not joined after a blank line.',
      '- `src/b.ts:2` — two.',
      'A paragraph line.',
      '  - `src/c.ts:3` — nested.',
      '    joined to the nested one.',
    ].join('\n')
    expect(parseReviewNotes(worklog).map(note => note.body)).toEqual([
      '`src/a.ts:1` — one.',
      '`src/b.ts:2` — two.',
      '`src/c.ts:3` — nested. joined to the nested one.',
    ])
  })

  test('the location is the first backtick span that reads `<path>:<line|?>`; the sentence starts after it', async () => {
    const [note] = parseReviewNotes('# Review round 1\n- The `flush` helper in `./src/sync.ts:9` loses rows. More.\n')
    expect(note).toEqual({ location: { path: 'src/sync.ts', line: 9 }, sentence: 'loses rows.', body: 'The `flush` helper in `./src/sync.ts:9` loses rows. More.' })
    const [plain] = parseReviewNotes('# Review round 1\n- No span, `x:y` is no location, and no stop\n')
    expect(plain).toEqual({ location: null, sentence: 'No span, x:y is no location, and no stop', body: 'No span, `x:y` is no location, and no stop' })
  })

  test('a sentence stops at a stop outside backticks that is followed by space or the end; leading separators and a parenthetical go', async () => {
    const notes = parseReviewNotes(
      [
        '# Review round 1',
        '- `src/a.ts:?` — `a.b`. c',
        '- `src/b.ts:2` (LOW 10) – - : v1.2 is kept whole. Next.',
        '- `src/c.ts:3`',
      ].join('\n'),
    )
    expect(notes.map(note => note.sentence)).toEqual(['a.b.', 'v1.2 is kept whole.', ''])
  })
})

describe('position: parseReviewNotes, round 1 fixes', () => {
  test('F6/F11: control characters leave the item before the whitespace collapse: body and sentence carry none', async () => {
    const [note] = parseReviewNotes('# Review round 1\n- `src/a.ts:1` — the \u001b[31mred\u001b[0m text\u0007 stays. Next.\n')
    expect(note?.body).toBe('`src/a.ts:1` — the [31mred[0m text stays. Next.')
    expect(note?.sentence).toBe('the [31mred[0m text stays.')
    expect(/[\u0000-\u001f\u007f-\u009f]/.test(`${note?.body}${note?.sentence}`)).toBe(false)
  })

  test('F7: a review heading inside an open review section keeps the outer level, so a later sibling stays inside', async () => {
    const worklog = ['# Review round 1', '- `src/a.ts:1` — one.', '## Rejected findings', '- `src/b.ts:2` — two.', '## Fixed', '- `src/c.ts:3` — three.', '# Capture', '- `src/d.ts:4` — outside.'].join('\n')
    expect(parseReviewNotes(worklog).map(note => note.location?.path)).toEqual(['src/a.ts', 'src/b.ts', 'src/c.ts'])
  })

  test('F9: a fence closes only on its own marker character, at least as long as the opener', async () => {
    const worklog = [
      '# Review round 1',
      '```',
      '~~~',
      '- `src/fenced.ts:1` — still in the backtick fence.',
      '``',
      '- `src/fenced.ts:2` — a shorter run closes nothing.',
      '````',
      '- `src/a.ts:1` — after the fence.',
      '~~~~',
      '~~~',
      '- `src/fenced.ts:3` — inside the tilde fence.',
      '~~~~~',
      '- `src/b.ts:2` — after it.',
    ].join('\n')
    expect(parseReviewNotes(worklog).map(note => note.location?.path)).toEqual(['src/a.ts', 'src/b.ts'])
  })

  test('F14: leading commas, semicolons and periods go with the separators; a sentence with no letter or digit is empty', async () => {
    const notes = parseReviewNotes(
      ['# Review round 1', '- Deferred: `views.tsx:1056` (LOW 35), control characters in a note are drawn raw.', '- `src/c.ts:3`.', '- `src/d.ts:4`; — ...', '- `src/e.ts:5` — `?`'].join('\n'),
    )
    expect(notes.map(note => note.sentence)).toEqual(['control characters in a note are drawn raw.', '', '', ''])
    expect(notes[0]?.location).toEqual({ path: 'views.tsx', line: 1056 })
  })
})
