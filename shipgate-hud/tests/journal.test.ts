import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_HOMES,
  EMPTY_TRACE,
  MIN_SHIPGATE_VERSION,
  type PositionDoc,
  type StatusBrief,
  decodePosition,
  decodeSidecarHomes,
  decodeStatus,
  failureText,
  hasPositionMarker,
  hasStatusMarker,
  outdatedText,
  rankingOf,
} from '../hooks/journal'
import type { ReadFailure, ShapeError } from '../types'
import { SIDECAR, olderStatus } from './fixtures'
import { POSITION_GOLDEN, STATUS_GOLDEN } from './fixtures.journal'

/** A golden document decoded; a thrown error naming the path when it does not decode (the test fails there). */
const statusOf = (raw: unknown): StatusBrief => {
  const decoded = decodeStatus(raw)
  if (!decoded.ok) throw new Error(`status does not decode: ${JSON.stringify(decoded.error)}`)
  return decoded.value
}

const positionOf = (raw: unknown): PositionDoc => {
  const decoded = decodePosition(raw)
  if (!decoded.ok) throw new Error(`position does not decode: ${JSON.stringify(decoded.error)}`)
  return decoded.value
}

/** Where a document that must not decode stopped (a `BadShape`'s error); null when it decoded or was read as `Outdated`. */
const statusError = (raw: unknown): ShapeError | null => {
  const decoded = decodeStatus(raw)
  return decoded.ok || decoded.error.kind !== 'BadShape' ? null : decoded.error.error
}

const positionError = (raw: unknown): ShapeError | null => {
  const decoded = decodePosition(raw)
  return decoded.ok || decoded.error.kind !== 'BadShape' ? null : decoded.error.error
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
      publish: { kind: 'authorized', by: 'gate-decision', seq: 42, at: '2026-10-01T11:55:00+00:00' },
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
    // shipgate 0.19.0: a session whose only write is a `--actor user` row binds through its `recorded_by`
    expect(statusOf(STATUS_GOLDEN.session_user)).toMatchObject({ sessionMatch: 'feature/golden-user', branchMatch: null })
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

describe('journal: the 0.18 marker', () => {
  /** The sign `decodeStatus` reads from a brief; null when it decoded or failed another way. */
  const signOf = (raw: unknown) => {
    const decoded = decodeStatus(raw)
    return decoded.ok || decoded.error.kind !== 'Outdated' ? null : decoded.error.sign
  }

  test('a brief with nested_matches carries the marker, whatever its value; one without it does not', async () => {
    expect(hasStatusMarker(ALL)).toBe(true)
    expect(hasStatusMarker({ ...ALL, nested_matches: null })).toBe(true)
    expect(hasStatusMarker({ ...ALL, nested_matches: 'x' })).toBe(true)
    expect(hasStatusMarker({ features: ALL.features, session_match: null, branch_match: null })).toBe(false)
    expect(hasStatusMarker({})).toBe(false)
  })

  test('JSON that is no object says nothing about the version: it carries no missing marker', async () => {
    for (const raw of [null, [], 'x', 3]) expect(hasStatusMarker(raw)).toBe(true)
  })

  test('R3: a brief with no nested_matches key is Outdated (MissingMarker), never a shape error', async () => {
    const { nested_matches: _gone, ...older } = ALL
    expect(signOf(older)).toEqual({ kind: 'MissingMarker' })
    expect(statusError(older)).toBeNull()
  })

  test('a brief as an older journal.py prints it is Outdated, though its features lack publish and lifecycle too', async () => {
    for (const raw of Object.values(STATUS_GOLDEN)) expect(signOf(olderStatus(raw))).toEqual({ kind: 'MissingMarker' })
  })

  test('nested_matches present but null is a BadShape at that key, not Outdated', async () => {
    expect(signOf({ ...ALL, nested_matches: null })).toBeNull()
    expect(statusError({ ...ALL, nested_matches: null })?.path).toBe('$.nested_matches')
  })

  test('JSON that is no object is a BadShape at $, not Outdated', async () => {
    for (const raw of [null, [], 'x', 3]) {
      expect(signOf(raw)).toBeNull()
      expect(statusError(raw)?.path).toBe('$')
    }
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
    expect(doc.publish).toEqual({ kind: 'authorized', by: 'gate-decision', seq: 42, at: '2026-10-01T11:55:00+00:00' })
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
      { seq: 29, gate: 'clarify', question: 'one widget or two?', decision: 'two', raisedBy: 'orchestrator', mode: 'executive', at: '2026-10-01T11:42:00+00:00' },
      { seq: 42, gate: 'publish', question: 'open the MR before the second review?', decision: 'publish', raisedBy: 'user', mode: 'ask', at: '2026-10-01T11:55:00+00:00' },
    ])
    expect(doc.lastVerify).toEqual({ outcome: 'fail', taskIds: ['T002'], at: '2026-10-01T11:54:00+00:00' })
    expect(doc.verdict).toEqual({
      seq: 39,
      at: '2026-10-01T11:52:00+00:00',
      verdict: 'not-ready',
      criteria: { 'SC-001': 'met', 'SC-002': 'unmet' },
      dispositions: { 'src/golden.py:12': 'fixed', 'src/other.py:?': 'deferred' },
      note: null,
      round: 1,
    })
  })

  test('the signals position: the trace as journal.py picked it, both rankings decoded, one signals gap', async () => {
    const raw = POSITION_GOLDEN.signals
    const doc = positionOf(raw)
    expect(doc.trace.signalsGaps).toEqual([{ seq: raw.trace.signals_missing[0]?.seq, at: raw.trace.signals_missing[0]?.at }])
    expect(doc.trace.designRanking).toEqual({
      seq: raw.trace.design_ranking.seq,
      at: raw.trace.design_ranking.at,
      ranking: {
        kind: 'Ranked',
        source: 'regex',
        files: [
          { path: 'src/golden.py', fix: 'top', churn: 'high', fanIn: null },
          { path: 'src/other.py', fix: 'low', churn: 'low', fanIn: 'mid' },
        ],
      },
    })
    expect(doc.trace.reviewRanking).toEqual({
      seq: raw.trace.review_ranking.seq,
      at: raw.trace.review_ranking.at,
      ranking: { kind: 'Ranked', source: 'graph', files: [{ path: 'src/golden.py', fix: 'top', churn: 'high', fanIn: 'top' }] },
    })
    // the review ranking rides on the verdict position names
    expect(doc.trace.reviewRanking?.seq).toBe(doc.verdict?.seq)
    expect(doc.dispositions).toEqual({})
  })

  test('a stream that records no trace value: the empty trace', async () => {
    expect(positionOf(FLOW).trace).toEqual(EMPTY_TRACE)
    expect(positionOf(POSITION_GOLDEN.started).trace).toEqual(EMPTY_TRACE)
  })

  test('the dispositions position: the fold per key, the verdict\'s note and round', async () => {
    const doc = positionOf(POSITION_GOLDEN.dispositions)
    expect(doc.dispositions).toEqual({
      'src/golden.py:12': { state: 'fixed', seq: 7, at: '2026-10-01T11:20:00+00:00' },
      'src/golden.py:30': { state: 'deferred', seq: 3, at: '2026-10-01T11:16:00+00:00' },
      'src/other.py:?': { state: 'fixing', seq: 3, at: '2026-10-01T11:16:00+00:00' },
    })
    expect(Object.keys(doc.dispositions)).toHaveLength(3)
    expect(doc.verdict).toMatchObject({ verdict: 'ready', note: 'the round closes', round: 1, dispositions: { 'src/golden.py:12': 'fixed' } })
  })

  test('a ranking that breaks the contract is Unreadable inside a strict envelope, never a failure', async () => {
    const trace = { ...FLOW.trace, review_ranking: { seq: 4, at: '2026-10-01T11:00:00+00:00', ranking: { source: 'graph', files: { 'a.py': {} } } } }
    expect(positionOf({ ...FLOW, trace }).trace.reviewRanking).toEqual({ seq: 4, at: '2026-10-01T11:00:00+00:00', ranking: { kind: 'Unreadable' } })
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

  test('0.21 marker: a position with no trace key is Outdated (MissingTrace), never a BadShape', async () => {
    const { trace: _trace, ...older } = FLOW
    const decoded = decodePosition(older)
    expect(decoded.ok ? null : decoded.error).toEqual({ kind: 'Outdated', sign: { kind: 'MissingTrace' } })
    // looked for first: a 0.20 position also lacks dispositions and the verdict's round
    const { trace: _t, dispositions: _d, ...older020 } = POSITION_GOLDEN.dispositions
    const verdict020 = { ...older020.verdict, note: undefined, round: undefined }
    const decoded020 = decodePosition({ ...older020, verdict: verdict020 })
    expect(decoded020.ok ? null : decoded020.error).toEqual({ kind: 'Outdated', sign: { kind: 'MissingTrace' } })
    expect(hasPositionMarker(older)).toBe(false)
    // a present key with a wrong value is no sign of an older journal.py: a BadShape
    expect(hasPositionMarker({ ...FLOW, trace: null })).toBe(true)
    expect(positionError({ ...FLOW, trace: null })?.path).toBe('$.trace')
    // not an object: no answer about the version, so a BadShape at `$`
    expect(hasPositionMarker('flow')).toBe(true)
  })

  const artifacts = FLOW.artifacts
  const task = FLOW.tasks[0]
  const decision = FLOW.decisions[0]
  const ranked = { seq: 4, at: '2026-10-01T11:00:00+00:00', ranking: { source: 'graph', files: [] } }
  const folded = { state: 'fixing', seq: 9, at: '2026-10-01T11:00:00+00:00' }
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
    // `fixing` is a folded state only: a verdict's own map keeps its three closed states
    ['fixing in the verdict\'s own map', { ...FLOW, verdict: { ...FLOW.verdict, dispositions: { 'a.ts:1': 'fixing' } } }, '$.verdict.dispositions["a.ts:1"]'],
    ['a verdict with no note key (absent is not null)', { ...FLOW, verdict: { ...FLOW.verdict, note: undefined } }, '$.verdict.note'],
    ['a verdict note of another type', { ...FLOW, verdict: { ...FLOW.verdict, note: 3 } }, '$.verdict.note'],
    ['a verdict with no round', { ...FLOW, verdict: { ...FLOW.verdict, round: undefined } }, '$.verdict.round'],
    ['a non-integer round', { ...FLOW, verdict: { ...FLOW.verdict, round: 1.5 } }, '$.verdict.round'],
    ['a round of zero (a verdict counts itself)', { ...FLOW, verdict: { ...FLOW.verdict, round: 0 } }, '$.verdict.round'],
    ['a round as text', { ...FLOW, verdict: { ...FLOW.verdict, round: '2' } }, '$.verdict.round'],
    ['a round as a boolean', { ...FLOW, verdict: { ...FLOW.verdict, round: true } }, '$.verdict.round'],
    ['dispositions missing', { ...FLOW, dispositions: undefined }, '$.dispositions'],
    ['dispositions as a list', { ...FLOW, dispositions: [] }, '$.dispositions'],
    ['a folded state outside the four', { ...FLOW, dispositions: { 'a.ts:1': { ...folded, state: 'done' } } }, '$.dispositions["a.ts:1"].state'],
    ['a folded disposition with no seq', { ...FLOW, dispositions: { 'a.ts:1': { ...folded, seq: undefined } } }, '$.dispositions["a.ts:1"].seq'],
    ['a folded disposition with a bad time', { ...FLOW, dispositions: { 'a.ts:1': { ...folded, at: 'yesterday' } } }, '$.dispositions["a.ts:1"].at'],
    ['a folded disposition as bare text', { ...FLOW, dispositions: { 'a.ts:1': 'fixing' } }, '$.dispositions["a.ts:1"]'],
    ['trace not an object', { ...FLOW, trace: [] }, '$.trace'],
    ['a trace with no review_ranking key', { ...FLOW, trace: { ...FLOW.trace, review_ranking: undefined } }, '$.trace.review_ranking'],
    ['a trace with no design_ranking key', { ...FLOW, trace: { ...FLOW.trace, design_ranking: undefined } }, '$.trace.design_ranking'],
    ['a trace with no signals_missing list', { ...FLOW, trace: { ...FLOW.trace, signals_missing: null } }, '$.trace.signals_missing'],
    ['a recorded ranking with no seq', { ...FLOW, trace: { ...FLOW.trace, review_ranking: { ...ranked, seq: undefined } } }, '$.trace.review_ranking.seq'],
    ['a recorded ranking with a bad time', { ...FLOW, trace: { ...FLOW.trace, design_ranking: { ...ranked, at: 'later' } } }, '$.trace.design_ranking.at'],
    ['a recorded ranking with no ranking key', { ...FLOW, trace: { ...FLOW.trace, review_ranking: { ...ranked, ranking: undefined } } }, '$.trace.review_ranking.ranking'],
    ['a signals gap with no seq', { ...FLOW, trace: { ...FLOW.trace, signals_missing: [{ at: '2026-10-01T11:00:00+00:00' }] } }, '$.trace.signals_missing[0].seq'],
    ['a signals gap with no time', { ...FLOW, trace: { ...FLOW.trace, signals_missing: [{ seq: 3 }] } }, '$.trace.signals_missing[0].at'],
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
  const failures: readonly (readonly [ReadFailure, RegExp])[] = [
    [{ kind: 'Cut' }, /cut/],
    [{ kind: 'CannotStart', message: 'spawn python3 ENOENT' }, /did not start: spawn python3 ENOENT/],
    [{ kind: 'Exited', exitCode: 1, stderr: "Traceback (most recent call last):\n  File x\nInfraError: stream 'feature/x' has no events\n\n" }, /exited 1: InfraError: stream 'feature\/x' has no events$/],
    [{ kind: 'Exited', exitCode: 3, stderr: '' }, /exited 3$/],
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

  test('a BadShape is a contract mismatch, not a known old version: the path and what was expected, no version', async () => {
    const line = failureText({ kind: 'BadShape', error: { path: '$.features[0].publish', expected: 'an object' } })
    expect(line).toBe('journal.py printed a shape this HUD does not read at $.features[0].publish (expected an object)')
    expect(line).not.toContain(MIN_SHIPGATE_VERSION)
  })

  test('a long stderr line is cut, never a wall of text', async () => {
    expect(failureText({ kind: 'Exited', exitCode: 1, stderr: 'x'.repeat(5000) }).length).toBeLessThanOrEqual(240)
  })
})

describe('journal: outdatedText', () => {
  test('an argument argparse refused is named', async () => {
    expect(outdatedText({ kind: 'UnknownArgument', argument: 'position' })).toBe('journal.py does not know position')
  })

  test('a missing marker names the key status --json did not print', async () => {
    expect(outdatedText({ kind: 'MissingMarker' })).toBe('journal.py status --json printed no nested_matches key')
  })

  test('a missing trace names the key position --json did not print', async () => {
    expect(outdatedText({ kind: 'MissingTrace' })).toBe('journal.py position --json printed no trace key')
  })

  test('the read floor is 0.21.0: the first journal.py whose position prints the trace', async () => {
    expect(MIN_SHIPGATE_VERSION).toBe('0.21.0')
  })

  test('a refused argument is one line, cut, never a wall of text', async () => {
    const line = outdatedText({ kind: 'UnknownArgument', argument: `x\n\u0007${'y'.repeat(5000)}` })
    expect(line).not.toMatch(/[\n\r\u0000-\u001f]/)
    expect(line.length).toBeLessThanOrEqual(240)
  })
})

describe('journal: rankingOf (HUD ADR 0007)', () => {
  test('rankingOf decodes to journal.py\'s contract: source required, unavailable a reason, files and labels optional', async () => {
    expect(rankingOf({ source: 'none', unavailable: 'shallow' })).toEqual({ kind: 'Unavailable', reason: 'shallow' })
    expect(rankingOf({ source: 'none', files: [] })).toEqual({ kind: 'Ranked', source: 'none', files: [] })
    // journal.py accepts these: `files` and each label are optional, and checked only when present
    expect(rankingOf({ source: 'graph' })).toEqual({ kind: 'Ranked', source: 'graph', files: [] })
    expect(rankingOf({ source: 'graph', files: [{ path: 'a.py', fix: 'top' }] })).toEqual({ kind: 'Ranked', source: 'graph', files: [{ path: 'a.py', fix: 'top', churn: null, fanIn: null }] })
    for (const [label, value] of [
      ['an object keyed by path (a row from before 0.20.0)', { source: 'graph', files: { 'a.py': { fix: 'top' } } }],
      ['an unknown source', { source: 'codegraph', files: [] }],
      ['no source', { files: [] }],
      ['unavailable with no source', { unavailable: 'shallow' }],
      ['a label outside the four', { source: 'graph', files: [{ path: 'a.py', fix: 'hot', churn: null, fan_in: null }] }],
      ['a file with no path', { source: 'graph', files: [{ fix: 'top', churn: null, fan_in: null }] }],
      ['an unavailable reason that is no text', { source: 'none', unavailable: ['shallow'] }],
      ['not an object', 'graph'],
      ['null', null],
    ] as const) {
      expect([label, rankingOf(value)]).toEqual([label, { kind: 'Unreadable' }])
    }
  })
})
