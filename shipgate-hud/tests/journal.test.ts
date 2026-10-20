import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_HOMES,
  MIN_SHIPGATE_VERSION,
  type PositionDoc,
  type StatusBrief,
  decodePosition,
  decodeSidecarHomes,
  decodeStatus,
  failureText,
} from '../hooks/journal'
import type { RunFailure, ShapeError } from '../types'
import { SIDECAR } from './fixtures'
import { POSITION_GOLDEN, STATUS_GOLDEN } from './fixtures.journal'

/** A golden document decoded; a thrown error naming the path when it does not decode (the test fails there). */
const statusOf = (raw: unknown): StatusBrief => {
  const decoded = decodeStatus(raw)
  if (!decoded.ok) throw new Error(`status does not decode at ${decoded.error.path}: expected ${decoded.error.expected}`)
  return decoded.value
}

const positionOf = (raw: unknown): PositionDoc => {
  const decoded = decodePosition(raw)
  if (!decoded.ok) throw new Error(`position does not decode at ${decoded.error.path}: expected ${decoded.error.expected}`)
  return decoded.value
}

/** Where a document that must not decode stopped; null when it decoded. */
const statusError = (raw: unknown): ShapeError | null => {
  const decoded = decodeStatus(raw)
  return decoded.ok ? null : decoded.error
}

const positionError = (raw: unknown): ShapeError | null => {
  const decoded = decodePosition(raw)
  return decoded.ok ? null : decoded.error
}

const ALL = STATUS_GOLDEN.all
const FLOW = POSITION_GOLDEN.flow
/** The golden `all` brief with its first feature replaced. */
const withFirstFeature = (feature: Record<string, unknown>): Record<string, unknown> => ({ ...ALL, features: [feature, ...ALL.features.slice(1)] })
const FIRST = ALL.features[0]

describe('journal: decodeStatus', () => {
  for (const [scenario, raw] of Object.entries(STATUS_GOLDEN)) {
    test(`the golden ${scenario} brief decodes, its streams and its matches as journal.py printed them`, async () => {
      const brief = statusOf(raw)
      expect(brief.features.map(feature => feature.stream)).toEqual(raw.features.map(feature => feature.stream))
      expect(brief.sessionMatch).toBe(raw.session_match)
      expect(brief.branchMatch).toBe(raw.branch_match)
      expect(brief.nestedMatches).toEqual(raw.nested_matches)
      expect(brief.features.map(feature => feature.lifecycle)).toEqual(raw.features.map(feature => feature.lifecycle))
    })
  }

  test('each feature: lifecycle, current (null for a stream with no phase), the newest event time and publish', async () => {
    const byStream = new Map(statusOf(ALL).features.map(feature => [String(feature.stream), feature] as const))
    expect(byStream.get('feature/golden-flow')).toEqual({
      stream: 'feature/golden-flow',
      lifecycle: 'live',
      current: { phase: 'implement', enteredAt: '2026-10-01T11:53:00+00:00', isImplied: false },
      lastEventAt: '2026-10-01T11:55:00+00:00',
      publish: { kind: 'authorized', by: 'gate-decision', seq: 26, at: '2026-10-01T11:55:00+00:00' },
    })
    expect(byStream.get('feature/golden-started')?.current).toBeNull()
    expect(byStream.get('feature/golden-named')?.current?.isImplied).toBe(true)
    expect(byStream.get('feature/golden-done')?.lifecycle).toBe('terminal')
    expect(byStream.get('feature/golden-dormant')?.lifecycle).toBe('dormant')
    expect(byStream.get('epic-golden')?.publish).toEqual({ kind: 'held' })
    // H1: the per-stream match flags are not part of the decoded feature; the top-level names decide
    expect(Object.keys(byStream.get('epic-golden') ?? {}).sort()).toEqual(['current', 'lastEventAt', 'lifecycle', 'publish', 'stream'])
  })

  test('the top-level matches: the session, the branch, the one live nested stream, two nested streams binding none', async () => {
    expect(statusOf(STATUS_GOLDEN.session).sessionMatch).toBe('epic-golden')
    expect(statusOf(STATUS_GOLDEN.branch).branchMatch).toBe('feature/golden-flow')
    expect(statusOf(STATUS_GOLDEN.nested_one)).toMatchObject({ branchMatch: 'fix/7-golden-nested', nestedMatches: ['fix/7-golden-nested'] })
    expect(statusOf(STATUS_GOLDEN.nested_two)).toMatchObject({ branchMatch: null, nestedMatches: ['fix/7-golden-nested', 'feature/golden-flow'] })
  })

  test('a stream with no event has no newest event time', async () => {
    expect(statusOf(withFirstFeature({ ...FIRST, last_event: null })).features[0]?.lastEventAt).toBeNull()
  })

  // a missing or mistyped key is a shape error naming its path, never a default
  for (const [name, raw, path] of [
    ['not an object', [], '$'],
    ['null', null, '$'],
    ['features renamed', { ...ALL, features: undefined, streams: ALL.features }, '$.features'],
    ['a feature that is no object', { ...ALL, features: ['epic-golden'] }, '$.features[0]'],
    ['stream renamed', withFirstFeature({ ...FIRST, stream: undefined, name: FIRST.stream }), '$.features[0].stream'],
    ['an empty stream name', withFirstFeature({ ...FIRST, stream: '' }), '$.features[0].stream'],
    ['lifecycle renamed', withFirstFeature({ ...FIRST, lifecycle: undefined, life_cycle: 'live' }), '$.features[0].lifecycle'],
    ['a lifecycle outside the vocabulary', withFirstFeature({ ...FIRST, lifecycle: 'asleep' }), '$.features[0].lifecycle'],
    ['current missing', withFirstFeature({ ...FIRST, current: undefined }), '$.features[0].current'],
    ['current.implied of another type', withFirstFeature({ ...FIRST, current: { ...FIRST.current, implied: 'no' } }), '$.features[0].current.implied'],
    ['current.phase outside the phases', withFirstFeature({ ...FIRST, current: { ...FIRST.current, phase: 'deploy' } }), '$.features[0].current.phase'],
    ['current.entered_at no time', withFirstFeature({ ...FIRST, current: { ...FIRST.current, entered_at: 'soon' } }), '$.features[0].current.entered_at'],
    ['last_event missing', withFirstFeature({ ...FIRST, last_event: undefined }), '$.features[0].last_event'],
    ['last_event.ts missing', withFirstFeature({ ...FIRST, last_event: { seq: 30, type: 'phase-entered' } }), '$.features[0].last_event.ts'],
    ['publish missing', withFirstFeature({ ...FIRST, publish: undefined }), '$.features[0].publish'],
    ['publish of another kind', withFirstFeature({ ...FIRST, publish: { kind: 'maybe' } }), '$.features[0].publish.kind'],
    ['an authorization with no seq', withFirstFeature({ ...FIRST, publish: { kind: 'authorized', by: 'review-verdict', at: '2026-10-01T11:55:00+00:00' } }), '$.features[0].publish.seq'],
    ['an authorization by another event', withFirstFeature({ ...FIRST, publish: { kind: 'authorized', by: 'mr-opened', seq: 3, at: '2026-10-01T11:55:00+00:00' } }), '$.features[0].publish.by'],
    ['session_match missing', { ...ALL, session_match: undefined }, '$.session_match'],
    ['branch_match of another type', { ...ALL, branch_match: 7 }, '$.branch_match'],
    ['nested_matches missing (R3: always a list)', { ...ALL, nested_matches: undefined }, '$.nested_matches'],
    ['nested_matches null', { ...ALL, nested_matches: null }, '$.nested_matches'],
    ['a nested match that is no stream name', { ...ALL, nested_matches: [''] }, '$.nested_matches[0]'],
  ] as const) {
    test(`a shape error at ${path}: ${name}`, async () => {
      expect(statusError(raw)?.path).toBe(path)
    })
  }

  // H1: a top-level match must name a stream the brief lists
  test('a session or branch match naming a stream absent from features is a shape error at that key', async () => {
    expect(statusError({ ...ALL, session_match: 'feature/not-listed' })?.path).toBe('$.session_match')
    expect(statusError({ ...ALL, branch_match: 'feature/not-listed' })?.path).toBe('$.branch_match')
    expect(statusError({ ...STATUS_GOLDEN.branch, features: STATUS_GOLDEN.branch.features.slice(1) })?.path).toBe('$.branch_match')
  })

  test('a shape error says what was expected', async () => {
    expect(statusError(withFirstFeature({ ...FIRST, lifecycle: 'asleep' }))?.expected).toMatch(/live.*dormant.*terminal/)
  })
})

describe('journal: decodePosition', () => {
  for (const [stream, raw] of Object.entries(POSITION_GOLDEN)) {
    test(`the golden ${stream} position decodes`, async () => {
      const doc = positionOf(raw)
      expect(doc.stream).toBe(raw.stream)
      expect(doc.version).toBe(raw.version)
      expect(doc.lifecycle).toBe(raw.lifecycle)
      expect(doc.phases).toEqual(raw.phases)
      expect(doc.decisions.map(decision => decision.seq)).toEqual(raw.decisions.map(decision => decision.seq))
      expect(doc.tasks === null).toBe(raw.tasks === null)
    })
  }

  test('the flow position: every field as journal.py printed it, camelCase', async () => {
    const doc = positionOf(FLOW)
    expect(doc.current).toEqual({ phase: 'implement', enteredAt: '2026-10-01T11:53:00+00:00', isImplied: false })
    expect(doc.publish).toEqual({ kind: 'authorized', by: 'gate-decision', seq: 26, at: '2026-10-01T11:55:00+00:00' })
    expect(doc.phases['route-and-map']).toBe('skipped')
    expect(doc.phases.review).toBe('revisited')
    expect(doc.artifacts).toEqual({
      worklog: { path: 'docs/prd/golden-flow.worklog.md', from: 'event' },
      prd: 'docs/prd/golden-flow.md',
      adrs: ['docs/adr/0002-golden-other.md', 'docs/adr/0001-golden-choice.md'],
    })
    // D9: the tasks exactly as the journal parsed them: a `*` bullet (T003), a line with no title (T004, R2)
    expect(doc.tasks).toEqual([
      { id: 'T001', title: 'the declarations', section: 'Declarations', isTicked: true, isDone: true, lastVerify: { outcome: 'pass', at: '2026-10-01T11:50:00+00:00' } },
      { id: 'T002', title: 'the bodies', section: 'Bodies', isTicked: false, isDone: false, lastVerify: { outcome: 'fail', at: '2026-10-01T11:54:00+00:00' } },
      { id: 'T003', title: 'a star bullet', section: 'Bodies', isTicked: true, isDone: false, lastVerify: null },
      { id: 'T004', title: null, section: 'Bodies', isTicked: false, isDone: false, lastVerify: null },
    ])
    // oldest first, as printed, each with its real seq
    expect(doc.decisions).toEqual([
      { seq: 13, gate: 'clarify', question: 'one widget or two?', decision: 'two', raisedBy: 'orchestrator', mode: 'executive', at: '2026-10-01T11:42:00+00:00' },
      { seq: 26, gate: 'publish', question: 'open the MR before the second review?', decision: 'publish', raisedBy: 'user', mode: 'ask', at: '2026-10-01T11:55:00+00:00' },
    ])
    expect(doc.lastVerify).toEqual({ outcome: 'fail', taskIds: ['T002'], at: '2026-10-01T11:54:00+00:00' })
    expect(doc.verdict).toEqual({
      seq: 23,
      at: '2026-10-01T11:52:00+00:00',
      verdict: 'not-ready',
      criteria: { 'SC-001': 'met', 'SC-002': 'unmet' },
      dispositions: { 'src/golden.py:12': 'fixed', 'src/other.py:?': 'deferred' },
    })
  })

  test('the other streams: a worklog found by its name, no phase yet, no worklog', async () => {
    expect(positionOf(POSITION_GOLDEN.named).artifacts.worklog).toEqual({ path: 'docs/prd/golden-named.worklog.md', from: 'name' })
    expect(positionOf(POSITION_GOLDEN.named).tasks?.[0]?.section).toBeNull()
    expect(positionOf(POSITION_GOLDEN.started).current).toBeNull()
    expect(positionOf(POSITION_GOLDEN.started)).toMatchObject({ tasks: null, lastVerify: null, verdict: null, artifacts: { worklog: null, prd: null, adrs: [] } })
    expect(positionOf(POSITION_GOLDEN.done).lifecycle).toBe('terminal')
  })

  test('verdict map keys the HUD cannot draw are left out: a criteria key that is no SC id; dispositions keep any key', async () => {
    const verdict = { ...FLOW.verdict, criteria: { 'SC-001': 'met', 'acceptance': 'met' }, dispositions: { 'any text:1': 'rejected' } }
    expect(positionOf({ ...FLOW, verdict }).verdict).toMatchObject({ criteria: { 'SC-001': 'met' }, dispositions: { 'any text:1': 'rejected' } })
    // a verify-run's task id that is no task id cannot name a task: left out, the others kept
    const lastVerify = { ...FLOW.last_verify, task_ids: ['T002', 'all'] }
    expect(positionOf({ ...FLOW, last_verify: lastVerify }).lastVerify?.taskIds).toEqual(['T002'])
  })

  const artifacts = FLOW.artifacts
  const task = FLOW.tasks[0]
  const decision = FLOW.decisions[0]
  for (const [name, raw, path] of [
    ['not an object', 'flow', '$'],
    ['last_verify renamed', { ...FLOW, last_verify: undefined, lastVerify: FLOW.last_verify }, '$.last_verify'],
    ['version of another type', { ...FLOW, version: '17' }, '$.version'],
    ['a phase missing', { ...FLOW, phases: { ...FLOW.phases, review: undefined } }, '$.phases.review'],
    ['a mark outside the vocabulary', { ...FLOW, phases: { ...FLOW.phases, design: 'passed' } }, '$.phases.design'],
    ['tasks neither null nor a list', { ...FLOW, tasks: {} }, '$.tasks'],
    ['a task id outside the grammar', { ...FLOW, tasks: [{ ...task, id: 'T001a' }] }, '$.tasks[0].id'],
    ['an empty title (R2: null, never empty)', { ...FLOW, tasks: [{ ...task, title: '' }] }, '$.tasks[0].title'],
    ['a task flag renamed', { ...FLOW, tasks: [{ ...task, done: undefined, is_done: true }] }, '$.tasks[0].done'],
    ['a task verify outcome outside the vocabulary', { ...FLOW, tasks: [{ ...task, last_verify: { outcome: 'flaky', at: '2026-10-01T11:50:00+00:00' } }] }, '$.tasks[0].last_verify.outcome'],
    ['decisions missing', { ...FLOW, decisions: undefined }, '$.decisions'],
    ['a decision without a seq', { ...FLOW, decisions: [{ ...decision, seq: undefined }] }, '$.decisions[0].seq'],
    ['a decision raised by someone else', { ...FLOW, decisions: [{ ...decision, raised_by: 'bot' }] }, '$.decisions[0].raised_by'],
    ['a decision mode outside the vocabulary', { ...FLOW, decisions: [{ ...decision, mode: 'auto' }] }, '$.decisions[0].mode'],
    ['a decision text of another type (journal.py prints null)', { ...FLOW, decisions: [{ ...decision, decision: ['publish'] }] }, '$.decisions[0].decision'],
    ['a verdict outside the vocabulary', { ...FLOW, verdict: { ...FLOW.verdict, verdict: 'ok' } }, '$.verdict.verdict'],
    ['a disposition outside the vocabulary', { ...FLOW, verdict: { ...FLOW.verdict, dispositions: { 'a.ts:1': 'ignored' } } }, '$.verdict.dispositions["a.ts:1"]'],
    ['artifacts missing', { ...FLOW, artifacts: undefined }, '$.artifacts'],
    ['worklog_from missing beside a worklog', { ...FLOW, artifacts: { ...artifacts, worklog_from: null } }, '$.artifacts.worklog_from'],
    ['worklog_from beside no worklog', { ...FLOW, artifacts: { ...artifacts, worklog: null } }, '$.artifacts.worklog_from'],
    // R5: journal.py drops unsafe refs; one that gets through is a shape error, never read
    ['an absolute worklog', { ...FLOW, artifacts: { ...artifacts, worklog: '/etc/golden.worklog.md' } }, '$.artifacts.worklog'],
    ['a parent-traversal ADR', { ...FLOW, artifacts: { ...artifacts, adrs: ['docs/adr/0001-golden-choice.md', '../outside/adr/0003-x.md'] } }, '$.artifacts.adrs[1]'],
    ['a PRD behind a drive', { ...FLOW, artifacts: { ...artifacts, prd: 'C:/docs/prd/golden.md' } }, '$.artifacts.prd'],
    ['a PRD behind a scheme', { ...FLOW, artifacts: { ...artifacts, prd: 'file://docs/prd/golden.md' } }, '$.artifacts.prd'],
  ] as const) {
    test(`a shape error at ${path}: ${name}`, async () => {
      expect(positionError(raw)?.path).toBe(path)
    })
  }
})

describe('journal: decodeSidecarHomes', () => {
  test('the sidecar homes overlay the defaults key by key', async () => {
    const homes = decodeSidecarHomes(SIDECAR)
    expect(homes).toEqual({ ok: true, value: { globs: ['*/docs/prd/*.md', '*/docs/adr/*.md', '*/docs/prd/*.worklog.md'] } })
  })

  test('a sidecar with no artifact_homes object keeps the defaults, as journal.py does', async () => {
    expect(decodeSidecarHomes({ version: 1 })).toEqual({ ok: true, value: DEFAULT_HOMES })
    expect(decodeSidecarHomes({ version: 1, artifact_homes: 'docs/*.md' })).toEqual({ ok: true, value: DEFAULT_HOMES })
    expect(DEFAULT_HOMES.globs).toEqual(['docs/prd/*.md', 'docs/adr/*.md', 'docs/prd/*.worklog.md'])
  })

  test('a non-string home is skipped (the default stays); a home of another key joins', async () => {
    expect(decodeSidecarHomes({ artifact_homes: { adr: 7, notes: 'notes/*.md' } })).toEqual({
      ok: true,
      value: { globs: ['docs/prd/*.md', 'docs/adr/*.md', 'docs/prd/*.worklog.md', 'notes/*.md'] },
    })
  })

  test('a sidecar that is not an object is a shape error', async () => {
    for (const raw of [null, [], 'x', 3]) {
      const homes = decodeSidecarHomes(raw)
      expect(homes.ok ? null : homes.error.path).toBe('$')
    }
  })
})

describe('journal: failureText', () => {
  const failures: readonly (readonly [RunFailure, RegExp])[] = [
    [{ kind: 'Cut' }, /cut/],
    [{ kind: 'CannotStart', message: 'spawn python3 ENOENT' }, /did not start: spawn python3 ENOENT/],
    [{ kind: 'Exited', exitCode: 1, stderr: "Traceback (most recent call last):\n  File x\nInfraError: stream 'feature/x' has no events\n\n" }, /exited 1: InfraError: stream 'feature\/x' has no events$/],
    [{ kind: 'Exited', exitCode: 3, stderr: '' }, /exited 3$/],
    [{ kind: 'Unsupported', argument: 'position' }, /does not know position/],
    [{ kind: 'Truncated' }, /more output than/],
    [{ kind: 'NotJson', message: 'Unexpected token < in JSON' }, /no JSON: Unexpected token < in JSON/],
    [{ kind: 'BadShape', error: { path: '$.features[0].lifecycle', expected: 'live, dormant or terminal' } }, /\$\.features\[0\]\.lifecycle.*live, dormant or terminal/],
  ]

  for (const [failure, text] of failures) {
    test(`${failure.kind}: one line naming the cause`, async () => {
      const line = failureText(failure)
      expect(line).toMatch(text)
      expect(line).not.toMatch(/[\n\r\u0000-\u001f]/)
    })
  }

  test('an older shipgate is told the version this HUD needs', async () => {
    expect(failureText({ kind: 'Unsupported', argument: '--nested-branch' })).toContain(`shipgate ${MIN_SHIPGATE_VERSION}`)
    expect(failureText({ kind: 'BadShape', error: { path: '$', expected: 'an object' } })).toContain(`shipgate ${MIN_SHIPGATE_VERSION}`)
  })

  test('a long stderr line is cut, never a wall of text', async () => {
    expect(failureText({ kind: 'Exited', exitCode: 1, stderr: 'x'.repeat(5000) }).length).toBeLessThanOrEqual(240)
  })
})
