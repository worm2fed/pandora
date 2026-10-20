// The one boundary for journal.py's JSON: the decoded shapes of `status --json` and
// `position --stream <s> --json`, the sidecar's homes, the smart constructors of the brands,
// and the text of a journal run's failure (RunFailure itself is in the contract, because
// HudView stores it). journal.py prints snake_case keys; the decoded shapes are camelCase. Pure: no `$` here, so the decoders run in tests on the golden file.
// Never stored in $.state: register.tsx maps a decoded value into the stored view.

import type {
  AuthorizedBy,
  BranchName,
  CriterionId,
  CriterionStatus,
  CurrentPhase,
  Decision,
  Disposition,
  EventSeq,
  GateMode,
  IsoTime,
  Lifecycle,
  Phase,
  PhaseMark,
  ProjectPath,
  PublishAuthorization,
  RaisedBy,
  RunFailure,
  ShapeError,
  StreamName,
  TaskId,
  Verdict,
  VerdictValue,
  Verify,
  VerifyOutcome,
  WorklogFrom,
} from '../types'
import {
  type Decoded,
  type Decoder,
  type JsonRecord,
  type Result,
  absurd,
  booleanOf,
  decodeList,
  decodeMember,
  decodeRecord,
  fail,
  numberOf,
  ok,
  recordOf,
  stringOf,
} from './json'

// ---------------------------------------------------------------------------------------
// Smart constructors: one per brand, each holding the brand's one cast
// ---------------------------------------------------------------------------------------

/** A stream name: non-empty, no control character; null otherwise. */
export const streamName = (raw: string): StreamName | null =>
  // cast: the one way to a StreamName, after the check
  raw !== '' && !/[\u0000-\u001f\u007f-\u009f]/.test(raw) ? (raw as StreamName) : null

/** A branch name: non-empty, not a detached `HEAD`, no whitespace or control character; null otherwise. */
export const branchName = (raw: string): BranchName | null =>
  // cast: the one way to a BranchName, after the check
  raw !== '' && raw !== 'HEAD' && !/[\s\u0000-\u001f\u007f-\u009f]/.test(raw) ? (raw as BranchName) : null

/** An event seq: a non-negative safe integer; null otherwise. */
export const eventSeq = (raw: number): EventSeq | null =>
  // cast: the one way to an EventSeq, after the check
  Number.isSafeInteger(raw) && raw >= 0 ? (raw as EventSeq) : null

/** An ISO timestamp: text `Date.parse` reads; null otherwise. */
export const isoTime = (raw: string): IsoTime | null =>
  // cast: the one way to an IsoTime, after the check
  raw !== '' && !Number.isNaN(Date.parse(raw)) ? (raw as IsoTime) : null

/** A Build Plan task id (`T002`), as `check`'s grammar reads it; null otherwise. */
export const taskId = (raw: string): TaskId | null =>
  // cast: the one way to a TaskId, after the check
  /^T\d+$/.test(raw) ? (raw as TaskId) : null

/** A success criterion id (`SC-001`); null otherwise. */
export const criterionId = (raw: string): CriterionId | null =>
  // cast: the one way to a CriterionId, after the check
  /^SC-\d+$/.test(raw) ? (raw as CriterionId) : null

/** A ref the HUD will read: relative, inside the project, no `..` segment, no drive or scheme (journal.py `_is_safe_ref`). */
export function isSafeRef(path: string): boolean {
  if (!path || path.startsWith('/') || path.startsWith('\\')) return false
  if (/^[A-Za-z]:/.test(path) || /^[a-z]+:\/\//i.test(path)) return false
  return !path.split(/[\\/]/).some(segment => segment === '..')
}

/** A project-relative path the HUD may read (`isSafeRef`), `#fragment` dropped; null otherwise. */
export const projectPath = (raw: string): ProjectPath | null => {
  const path = raw.split('#')[0] ?? ''
  // cast: the one way to a ProjectPath, after the check
  return isSafeRef(path) ? (path as ProjectPath) : null
}

// ---------------------------------------------------------------------------------------
// The vocabularies the decoders accept: total tables, so a member added to a union in
// types/index.d.ts is a compile error here until the decoder knows it
// ---------------------------------------------------------------------------------------

/** Every stream lifecycle journal.py prints. */
export const LIFECYCLES: Readonly<Record<Lifecycle, true>> = { live: true, dormant: true, terminal: true }

/** Every phase mark journal.py prints. */
export const PHASE_MARKS: Readonly<Record<PhaseMark, true>> = { done: true, skipped: true, current: true, revisited: true, todo: true }

/** Every worklog source journal.py prints. */
export const WORKLOG_FROM: Readonly<Record<WorklogFrom, true>> = { event: true, name: true }

// ---------------------------------------------------------------------------------------
// `status --json`
// ---------------------------------------------------------------------------------------

/** One stream of the status brief. Which stream the session or the branch names is the brief's own word (`sessionMatch`, `branchMatch`). */
export interface StatusFeature {
  readonly stream: StreamName
  readonly lifecycle: Lifecycle
  /** Null when the stream has entered no phase yet. */
  readonly current: CurrentPhase | null
  /** The newest event's time; null for a stream with no event. */
  readonly lastEventAt: IsoTime | null
  /** Computed by journal.py, the same helper `mr-opened` uses. */
  readonly publish: PublishAuthorization
}

/**
 * The status brief: its streams, and which of them the session and the branch name. These
 * top-level names decide the binding; the decoder refuses a brief whose `sessionMatch` or
 * `branchMatch` names a stream absent from `features`.
 */
export interface StatusBrief {
  readonly features: readonly StatusFeature[]
  /** The live stream this session last wrote to; null when none. */
  readonly sessionMatch: StreamName | null
  /** The stream the branch names (the nested-branch rule applied when nested branches were passed); null when none. */
  readonly branchMatch: StreamName | null
  /** The live streams the nested branches name, newest first; [] when none was passed or none names a live stream. */
  readonly nestedMatches: readonly StreamName[]
}

// ---------------------------------------------------------------------------------------
// `position --stream <s> --json`
// ---------------------------------------------------------------------------------------

/** The stream's worklog and how `position` found it: journal.py's `worklog` and `worklog_from`, grouped (both null, or both set). */
export interface WorklogRef {
  readonly path: ProjectPath
  readonly from: WorklogFrom
}

/** The artifacts `position` classified with the configured homes, from the events that commit or work them. */
export interface PositionArtifacts {
  /** Null when no event names a worklog and no free slug-named one exists. */
  readonly worklog: WorklogRef | null
  /** The PRD the last `clarify-passed` names; null when none. */
  readonly prd: ProjectPath | null
  readonly adrs: readonly ProjectPath[]
}

/** The last verify-run that covered a task: its outcome and when it ran. */
export interface TaskVerify {
  readonly outcome: VerifyOutcome
  readonly at: IsoTime
}

/** One Build Plan task, parsed by journal.py with `check`'s grammar, with its journal state. */
export interface PositionTask {
  readonly id: TaskId
  /** The text after the id, up to the spaced dash before `file(s):`; null when the line has none (journal.py's grammar). */
  readonly title: string | null
  /** The nearest heading above the task inside the Build Plan; null when none. */
  readonly section: string | null
  readonly isTicked: boolean
  /** A `task-done` in this stream names the task. */
  readonly isDone: boolean
  /** The last verify-run that covered the task, pass or fail; null when none did. */
  readonly lastVerify: TaskVerify | null
}

/** Every fact the HUD draws for one stream, computed by journal.py (shipgate ADR 0009). */
export interface PositionDoc {
  readonly stream: StreamName
  readonly version: number
  readonly lifecycle: Lifecycle
  /** Null when the stream has entered no phase yet. */
  readonly current: CurrentPhase | null
  readonly publish: PublishAuthorization
  readonly phases: Readonly<Record<Phase, PhaseMark>>
  readonly artifacts: PositionArtifacts
  /** Null when the stream has no worklog; [] when its worklog lists no task. */
  readonly tasks: readonly PositionTask[] | null
  /** Every gate decision, in seq order (oldest first), each with its real `seq`. */
  readonly decisions: readonly Decision[]
  /** The stream's last verify-run (`last_verify`, the fold's value); null when none. */
  readonly lastVerify: Verify | null
  /** The stream's last review verdict; null when none. */
  readonly verdict: Verdict | null
}

// ---------------------------------------------------------------------------------------
// The sidecar's homes
// ---------------------------------------------------------------------------------------

/**
 * The artifact homes: shipgate's defaults overlaid key by key with the sidecar's
 * `artifact_homes`, as journal.py merges them. Only the refresh trigger reads them: does a
 * Write land in a home? The journal classifies the artifacts itself.
 */
export interface SidecarHomes {
  readonly globs: readonly string[]
}

/** shipgate's homes by kind (journal.py DEFAULT_ARTIFACT_HOMES), the table a sidecar overlays key by key. */
const DEFAULT_ARTIFACT_HOMES: Readonly<Record<string, string>> = { prd: 'docs/prd/*.md', adr: 'docs/adr/*.md', worklog: 'docs/prd/*.worklog.md' }

/** shipgate's own defaults (journal.py DEFAULT_ARTIFACT_HOMES): the homes before the sidecar is read. */
export const DEFAULT_HOMES: SidecarHomes = { globs: Object.values(DEFAULT_ARTIFACT_HOMES) }

// ---------------------------------------------------------------------------------------
// Decoders and run failures
// ---------------------------------------------------------------------------------------

/** Where journal.py's JSON did not have the shape this HUD expects: a version mismatch, never a default. */
export type JournalShapeError = ShapeError

/** The oldest shipgate whose journal.py prints what this HUD decodes (`position`, `nested_matches`, `publish`, `lifecycle`, `current`). */
export const MIN_SHIPGATE_VERSION = '0.18.0'

/** The most characters of a journal run's own text (stderr, a parser message) one failure line carries. */
const FAILURE_DETAIL_LIMIT = 200

/** Text as one line: control characters and runs of whitespace as one space, trimmed, cut to the detail limit. */
const oneLine = (text: string): string => {
  const line = text.replace(/[\s\u0000-\u001f\u007f-\u009f]+/g, ' ').trim()
  const chars = [...line]
  return chars.length <= FAILURE_DETAIL_LIMIT ? line : `${chars.slice(0, FAILURE_DETAIL_LIMIT - 1).join('')}…`
}

/** The last non-blank line of a process's stderr, as one line: a Python error ends with its cause. */
const lastLine = (stderr: string): string => oneLine(stderr.split(/\r?\n/).filter(line => line.trim() !== '').at(-1) ?? '')

/** What a journal.py that does not print this HUD's shape should be: the version, as the pane and the hold text name it. */
const UPGRADE = `this HUD needs shipgate ${MIN_SHIPGATE_VERSION} or later`

/** A run failure as one line the pane (from a stored `HudView.Failed`) and the hold text show, built when drawn. */
export function failureText(failure: RunFailure): string {
  switch (failure.kind) {
    case 'Cut':
      return 'the journal read was cut before it finished'
    case 'CannotStart':
      return `journal.py did not start: ${oneLine(failure.message)}`
    case 'Exited': {
      const cause = lastLine(failure.stderr)
      return cause === '' ? `journal.py exited ${failure.exitCode}` : `journal.py exited ${failure.exitCode}: ${cause}`
    }
    case 'Unsupported':
      return `journal.py does not know ${oneLine(failure.argument)}: ${UPGRADE}`
    case 'Truncated':
      return 'journal.py printed more output than the HUD reads'
    case 'NotJson':
      return `journal.py printed no JSON: ${oneLine(failure.message)}`
    case 'BadShape':
      return `journal.py printed another shape at ${oneLine(failure.error.path)} (expected ${oneLine(failure.error.expected)}): ${UPGRADE}`
    default:
      return absurd(failure)
  }
}

// ---------------------------------------------------------------------------------------
// The field decoders: each fails with the path it stopped at
// ---------------------------------------------------------------------------------------

/** Every phase, in the vocabulary journal.py prints (PHASES). */
const PHASE_NAMES: Readonly<Record<Phase, true>> = {
  workspace: true,
  'route-and-map': true,
  explore: true,
  clarify: true,
  design: true,
  implement: true,
  review: true,
  capture: true,
}

const PUBLISH_KINDS: Readonly<Record<PublishAuthorization['kind'], true>> = { held: true, authorized: true }
const AUTHORIZED_BY: Readonly<Record<AuthorizedBy, true>> = { 'review-verdict': true, 'gate-decision': true }
const RAISED_BY: Readonly<Record<RaisedBy, true>> = { user: true, orchestrator: true }
const GATE_MODES: Readonly<Record<GateMode, true>> = { ask: true, executive: true }
const VERIFY_OUTCOMES: Readonly<Record<VerifyOutcome, true>> = { pass: true, fail: true }
const VERDICT_VALUES: Readonly<Record<VerdictValue, true>> = { ready: true, 'not-ready': true }
const CRITERION_STATUSES: Readonly<Record<CriterionStatus, true>> = { met: true, unmet: true }
const DISPOSITIONS: Readonly<Record<Disposition, true>> = { fixed: true, rejected: true, deferred: true }

/** The path of `key` under `path`: `.key` for a plain name, `["key"]` for any other text. */
const keyPath = (path: string, key: string): string => (/^[A-Za-z_][A-Za-z0-9_-]*$/.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`)

/** The record's own value at `key`: undefined when absent (never one of Object's own members). */
const field = (raw: JsonRecord, key: string): unknown => (Object.hasOwn(raw, key) ? raw[key] : undefined)

/** The record's value at `key` decoded, its failure at `<path>.<key>`. */
const fieldOf = <A>(raw: JsonRecord, path: string, key: string, decode: Decoder<A>): Decoded<A> => decode(field(raw, key), keyPath(path, key))

/** A decoder that also takes null. A missing key is still the inner decoder's failure: absent is not null. */
const nullable =
  <A>(decode: Decoder<A>): Decoder<A | null> =>
  (value, path) => {
    if (value === null) return ok(null)
    const one = decode(value, path)
    return one.ok || one.error.path !== path ? one : fail(path, `${one.error.expected} or null`)
  }

/** A member of a closed vocabulary. */
const member =
  <K extends string>(table: Readonly<Record<K, true>>, expected: string): Decoder<K> =>
  (value, path) =>
    decodeMember(table, value, path, expected)

/** Text through a smart constructor: its brand, or the failure. */
const branded =
  <A>(make: (raw: string) => A | null, expected: string): Decoder<A> =>
  (value, path) => {
    const text = stringOf(value)
    const made = text === null ? null : make(text)
    return made === null ? fail(path, expected) : ok(made)
  }

/** A list of `decode`'s values. */
const listing =
  <A>(decode: Decoder<A>): Decoder<readonly A[]> =>
  (value, path) =>
    decodeList(value, path, decode)

const decodeText: Decoder<string> = (value, path) => {
  const text = stringOf(value)
  return text === null ? fail(path, 'text') : ok(text)
}

const decodeBoolean: Decoder<boolean> = (value, path) => {
  const flag = booleanOf(value)
  return flag === null ? fail(path, 'true or false') : ok(flag)
}

const decodeSeq: Decoder<EventSeq> = (value, path) => {
  const number = numberOf(value)
  const seq = number === null ? null : eventSeq(number)
  return seq === null ? fail(path, 'an event seq') : ok(seq)
}

const decodeVersion: Decoder<number> = (value, path) => {
  const version = numberOf(value)
  return version !== null && Number.isSafeInteger(version) && version >= 0 ? ok(version) : fail(path, 'a stream version')
}

const decodeStream = branded(streamName, 'a stream name')
const decodeTime = branded(isoTime, 'an ISO time')
/** R5: journal.py drops an unsafe ref; one that gets through is a shape error, never read. */
const decodeRef = branded(projectPath, 'a safe project-relative path')
const decodeLifecycle = member(LIFECYCLES, 'live, dormant or terminal')

/** R2: a task line with no title prints null, never empty text. */
const decodeTitle: Decoder<string> = (value, path) => {
  const title = stringOf(value)
  return title === null || title === '' ? fail(path, 'a title') : ok(title)
}

const decodeCurrent: Decoder<CurrentPhase> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const phase = fieldOf(raw.value, path, 'phase', member(PHASE_NAMES, 'a phase'))
  if (!phase.ok) return phase
  const enteredAt = fieldOf(raw.value, path, 'entered_at', decodeTime)
  if (!enteredAt.ok) return enteredAt
  const isImplied = fieldOf(raw.value, path, 'implied', decodeBoolean)
  if (!isImplied.ok) return isImplied
  return ok({ phase: phase.value, enteredAt: enteredAt.value, isImplied: isImplied.value })
}

const decodePublish: Decoder<PublishAuthorization> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const kind = fieldOf(raw.value, path, 'kind', member(PUBLISH_KINDS, "'held' or 'authorized'"))
  if (!kind.ok) return kind
  switch (kind.value) {
    case 'held':
      return ok({ kind: 'held' })
    case 'authorized': {
      const by = fieldOf(raw.value, path, 'by', member(AUTHORIZED_BY, "'review-verdict' or 'gate-decision'"))
      if (!by.ok) return by
      const seq = fieldOf(raw.value, path, 'seq', decodeSeq)
      if (!seq.ok) return seq
      const at = fieldOf(raw.value, path, 'at', decodeTime)
      if (!at.ok) return at
      return ok({ kind: 'authorized', by: by.value, seq: seq.value, at: at.value })
    }
    default:
      return absurd(kind.value)
  }
}

// ---------------------------------------------------------------------------------------
// `status --json`
// ---------------------------------------------------------------------------------------

/** The time of the newest event (`last_event.ts`). */
const decodeLastEvent: Decoder<IsoTime> = (value, path) => {
  const raw = decodeRecord(value, path)
  return raw.ok ? fieldOf(raw.value, path, 'ts', decodeTime) : raw
}

const decodeFeature: Decoder<StatusFeature> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const stream = fieldOf(raw.value, path, 'stream', decodeStream)
  if (!stream.ok) return stream
  const lifecycle = fieldOf(raw.value, path, 'lifecycle', decodeLifecycle)
  if (!lifecycle.ok) return lifecycle
  const current = fieldOf(raw.value, path, 'current', nullable(decodeCurrent))
  if (!current.ok) return current
  const lastEventAt = fieldOf(raw.value, path, 'last_event', nullable(decodeLastEvent))
  if (!lastEventAt.ok) return lastEventAt
  const publish = fieldOf(raw.value, path, 'publish', decodePublish)
  if (!publish.ok) return publish
  return ok({ stream: stream.value, lifecycle: lifecycle.value, current: current.value, lastEventAt: lastEventAt.value, publish: publish.value })
}

/** H1: a top-level match is a stream the brief lists, or null. */
const listedIn =
  (features: readonly StatusFeature[]): Decoder<StreamName | null> =>
  (value, path) => {
    const named = nullable(decodeStream)(value, path)
    if (!named.ok || named.value === null) return named
    const stream = named.value
    return features.some(feature => feature.stream === stream) ? named : fail(path, 'a stream listed in $.features, or null')
  }

/** The status brief from `status --json`; a missing or mistyped key is an error, never a default. */
export function decodeStatus(raw: unknown): Result<JournalShapeError, StatusBrief> {
  const brief = decodeRecord(raw, '$')
  if (!brief.ok) return brief
  const features = fieldOf(brief.value, '$', 'features', listing(decodeFeature))
  if (!features.ok) return features
  const sessionMatch = fieldOf(brief.value, '$', 'session_match', listedIn(features.value))
  if (!sessionMatch.ok) return sessionMatch
  const branchMatch = fieldOf(brief.value, '$', 'branch_match', listedIn(features.value))
  if (!branchMatch.ok) return branchMatch
  // R3: always a list
  const nestedMatches = fieldOf(brief.value, '$', 'nested_matches', listing(decodeStream))
  if (!nestedMatches.ok) return nestedMatches
  return ok({ features: features.value, sessionMatch: sessionMatch.value, branchMatch: branchMatch.value, nestedMatches: nestedMatches.value })
}

// ---------------------------------------------------------------------------------------
// `position --stream <s> --json`
// ---------------------------------------------------------------------------------------

/** Every phase's mark: all eight present, each in the vocabulary. */
const decodePhases: Decoder<Readonly<Record<Phase, PhaseMark>>> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const mark = (phase: Phase): Decoded<PhaseMark> => fieldOf(raw.value, path, phase, member(PHASE_MARKS, 'done, skipped, current, revisited or todo'))
  const workspace = mark('workspace')
  if (!workspace.ok) return workspace
  const routeAndMap = mark('route-and-map')
  if (!routeAndMap.ok) return routeAndMap
  const explore = mark('explore')
  if (!explore.ok) return explore
  const clarify = mark('clarify')
  if (!clarify.ok) return clarify
  const design = mark('design')
  if (!design.ok) return design
  const implement = mark('implement')
  if (!implement.ok) return implement
  const review = mark('review')
  if (!review.ok) return review
  const capture = mark('capture')
  if (!capture.ok) return capture
  return ok({
    workspace: workspace.value,
    'route-and-map': routeAndMap.value,
    explore: explore.value,
    clarify: clarify.value,
    design: design.value,
    implement: implement.value,
    review: review.value,
    capture: capture.value,
  })
}

/** The worklog and how it was found: both null, or both set. */
const worklogRefOf = (path: string, worklog: ProjectPath | null, from: WorklogFrom | null): Decoded<WorklogRef | null> => {
  const fromPath = keyPath(path, 'worklog_from')
  if (worklog === null) return from === null ? ok(null) : fail(fromPath, 'null beside no worklog')
  return from === null ? fail(fromPath, "'event' or 'name' beside a worklog") : ok({ path: worklog, from })
}

const decodeArtifacts: Decoder<PositionArtifacts> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const worklogPath = fieldOf(raw.value, path, 'worklog', nullable(decodeRef))
  if (!worklogPath.ok) return worklogPath
  const from = fieldOf(raw.value, path, 'worklog_from', nullable(member(WORKLOG_FROM, "'event' or 'name'")))
  if (!from.ok) return from
  const worklog = worklogRefOf(path, worklogPath.value, from.value)
  if (!worklog.ok) return worklog
  const prd = fieldOf(raw.value, path, 'prd', nullable(decodeRef))
  if (!prd.ok) return prd
  const adrs = fieldOf(raw.value, path, 'adrs', listing(decodeRef))
  if (!adrs.ok) return adrs
  return ok({ worklog: worklog.value, prd: prd.value, adrs: adrs.value })
}

const decodeTaskVerify: Decoder<TaskVerify> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const outcome = fieldOf(raw.value, path, 'outcome', member(VERIFY_OUTCOMES, "'pass' or 'fail'"))
  if (!outcome.ok) return outcome
  const at = fieldOf(raw.value, path, 'at', decodeTime)
  if (!at.ok) return at
  return ok({ outcome: outcome.value, at: at.value })
}

const decodeTask: Decoder<PositionTask> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const id = fieldOf(raw.value, path, 'id', branded(taskId, 'a task id (T and digits)'))
  if (!id.ok) return id
  const title = fieldOf(raw.value, path, 'title', nullable(decodeTitle))
  if (!title.ok) return title
  const section = fieldOf(raw.value, path, 'section', nullable(decodeText))
  if (!section.ok) return section
  const isTicked = fieldOf(raw.value, path, 'ticked', decodeBoolean)
  if (!isTicked.ok) return isTicked
  const isDone = fieldOf(raw.value, path, 'done', decodeBoolean)
  if (!isDone.ok) return isDone
  const lastVerify = fieldOf(raw.value, path, 'last_verify', nullable(decodeTaskVerify))
  if (!lastVerify.ok) return lastVerify
  return ok({ id: id.value, title: title.value, section: section.value, isTicked: isTicked.value, isDone: isDone.value, lastVerify: lastVerify.value })
}

const decodeDecision: Decoder<Decision> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const seq = fieldOf(raw.value, path, 'seq', decodeSeq)
  if (!seq.ok) return seq
  const gate = fieldOf(raw.value, path, 'gate', nullable(decodeText))
  if (!gate.ok) return gate
  const question = fieldOf(raw.value, path, 'question', nullable(decodeText))
  if (!question.ok) return question
  const decision = fieldOf(raw.value, path, 'decision', nullable(decodeText))
  if (!decision.ok) return decision
  const raisedBy = fieldOf(raw.value, path, 'raised_by', member(RAISED_BY, "'user' or 'orchestrator'"))
  if (!raisedBy.ok) return raisedBy
  const mode = fieldOf(raw.value, path, 'mode', nullable(member(GATE_MODES, "'ask' or 'executive'")))
  if (!mode.ok) return mode
  const at = fieldOf(raw.value, path, 'at', decodeTime)
  if (!at.ok) return at
  return ok({ seq: seq.value, gate: gate.value, question: question.value, decision: decision.value, raisedBy: raisedBy.value, mode: mode.value, at: at.value })
}

/** The ids a verify-run names that are task ids: journal.py keeps every string entry, and one that is no task id names no task. */
const taskIdsOf = (ids: readonly string[]): readonly TaskId[] =>
  ids.flatMap(raw => {
    const id = taskId(raw)
    return id === null ? [] : [id]
  })

const decodeVerify: Decoder<Verify> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const outcome = fieldOf(raw.value, path, 'outcome', member(VERIFY_OUTCOMES, "'pass' or 'fail'"))
  if (!outcome.ok) return outcome
  const ids = fieldOf(raw.value, path, 'task_ids', listing(decodeText))
  if (!ids.ok) return ids
  const at = fieldOf(raw.value, path, 'at', decodeTime)
  if (!at.ok) return at
  return ok({ outcome: outcome.value, taskIds: taskIdsOf(ids.value), at: at.value })
}

/** One key and its decoded value. */
type Entry<V> = readonly [string, V]

/** An object's entries, each value decoded, in order; the failure at the first value that does not decode. */
const decodeEntries = <V>(value: unknown, path: string, decode: Decoder<V>): Decoded<readonly Entry<V>[]> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  return Object.entries(raw.value).reduce<Decoded<readonly Entry<V>[]>>((done, [key, item]) => {
    if (!done.ok) return done
    const one = decode(item, keyPath(path, key))
    if (!one.ok) return one
    const entry: Entry<V> = [key, one.value]
    return ok([...done.value, entry])
  }, ok([]))
}

/**
 * A verdict's criteria: each status in the vocabulary. journal.py keeps any key; one that is
 * no SC id names no criterion the PRD lists, so it is left out.
 */
const decodeCriteria: Decoder<Readonly<Partial<Record<CriterionId, CriterionStatus>>>> = (value, path) => {
  const entries = decodeEntries(value, path, member(CRITERION_STATUSES, "'met' or 'unmet'"))
  if (!entries.ok) return entries
  return ok(
    entries.value.reduce<Readonly<Partial<Record<CriterionId, CriterionStatus>>>>((criteria, [key, status]) => {
      const id = criterionId(key)
      return id === null ? criteria : { ...criteria, [id]: status }
    }, {}),
  )
}

/** A verdict's dispositions: any key (`<path>:<line or ?>`), each disposition in the vocabulary. */
const decodeDispositions: Decoder<Readonly<Record<string, Disposition>>> = (value, path) => {
  const entries = decodeEntries(value, path, member(DISPOSITIONS, "'fixed', 'rejected' or 'deferred'"))
  return entries.ok ? ok(Object.fromEntries(entries.value)) : entries
}

const decodeVerdict: Decoder<Verdict> = (value, path) => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const seq = fieldOf(raw.value, path, 'seq', decodeSeq)
  if (!seq.ok) return seq
  const at = fieldOf(raw.value, path, 'at', decodeTime)
  if (!at.ok) return at
  const verdict = fieldOf(raw.value, path, 'verdict', member(VERDICT_VALUES, "'ready' or 'not-ready'"))
  if (!verdict.ok) return verdict
  const criteria = fieldOf(raw.value, path, 'criteria', decodeCriteria)
  if (!criteria.ok) return criteria
  const dispositions = fieldOf(raw.value, path, 'dispositions', decodeDispositions)
  if (!dispositions.ok) return dispositions
  return ok({ seq: seq.value, at: at.value, verdict: verdict.value, criteria: criteria.value, dispositions: dispositions.value })
}

/**
 * The stream's position from `position --stream <s> --json`; a missing or mistyped key is an
 * error, never a default. journal.py drops unsafe refs; one that gets through anyway (an
 * artifact path `projectPath` refuses) is a shape error too.
 */
export function decodePosition(raw: unknown): Result<JournalShapeError, PositionDoc> {
  const doc = decodeRecord(raw, '$')
  if (!doc.ok) return doc
  const stream = fieldOf(doc.value, '$', 'stream', decodeStream)
  if (!stream.ok) return stream
  const version = fieldOf(doc.value, '$', 'version', decodeVersion)
  if (!version.ok) return version
  const lifecycle = fieldOf(doc.value, '$', 'lifecycle', decodeLifecycle)
  if (!lifecycle.ok) return lifecycle
  const current = fieldOf(doc.value, '$', 'current', nullable(decodeCurrent))
  if (!current.ok) return current
  const publish = fieldOf(doc.value, '$', 'publish', decodePublish)
  if (!publish.ok) return publish
  const phases = fieldOf(doc.value, '$', 'phases', decodePhases)
  if (!phases.ok) return phases
  const artifacts = fieldOf(doc.value, '$', 'artifacts', decodeArtifacts)
  if (!artifacts.ok) return artifacts
  const tasks = fieldOf(doc.value, '$', 'tasks', nullable(listing(decodeTask)))
  if (!tasks.ok) return tasks
  const decisions = fieldOf(doc.value, '$', 'decisions', listing(decodeDecision))
  if (!decisions.ok) return decisions
  const lastVerify = fieldOf(doc.value, '$', 'last_verify', nullable(decodeVerify))
  if (!lastVerify.ok) return lastVerify
  const verdict = fieldOf(doc.value, '$', 'verdict', nullable(decodeVerdict))
  if (!verdict.ok) return verdict
  return ok({
    stream: stream.value,
    version: version.value,
    lifecycle: lifecycle.value,
    current: current.value,
    publish: publish.value,
    phases: phases.value,
    artifacts: artifacts.value,
    tasks: tasks.value,
    decisions: decisions.value,
    lastVerify: lastVerify.value,
    verdict: verdict.value,
  })
}

/**
 * The homes from the sidecar's JSON, over DEFAULT_HOMES: a sidecar with no `artifact_homes`
 * object keeps the defaults (as journal.py does); a non-string home is skipped; a sidecar
 * that is not an object is an error.
 */
export function decodeSidecarHomes(raw: unknown): Result<JournalShapeError, SidecarHomes> {
  const sidecar = decodeRecord(raw, '$')
  if (!sidecar.ok) return sidecar
  const homes = recordOf(field(sidecar.value, 'artifact_homes'))
  if (homes === null) return ok(DEFAULT_HOMES)
  const merged = Object.entries(homes).reduce<Readonly<Record<string, string>>>(
    (byKind, [kind, glob]) => (typeof glob === 'string' ? { ...byKind, [kind]: glob } : byKind),
    DEFAULT_ARTIFACT_HOMES,
  )
  return ok({ globs: Object.values(merged) })
}
