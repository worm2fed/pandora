// The Review board's pure core: the review workflow's return, as Claude Code delivers it in a
// `<task-notification>` user turn, in; a decoded return, the stored board, its grouping and the
// Accept / Kill prompt text out. No `$` here, so the tests run it without a session.

import type {
  BelowFloorFinding,
  BoardSurvivor,
  Criterion,
  CriterionId,
  CriterionStatus,
  Disposition,
  EventSeq,
  FindingCore,
  FindingSeverity,
  IsoTime,
  KilledFinding,
  Quorum,
  ReviewBoard,
  ReviewCounts,
  ReviewCoverage,
  ReviewMark,
  ReviewState,
  RiskLabel,
  RoundId,
  Severity,
  ShapeError,
  StreamName,
  SurvivorFinding,
  TaskNotification,
  TickEntry,
  TickOverride,
  Verification,
} from '../types'
import { type Decoded, type JsonRecord, type Result, decodeList, decodeMember, decodeRecord, fail, listOf, numberOf, ok, parseJson, recordOf, stringListOf, stringOf } from './json'
import { criterionId, eventSeq, isoTime, streamName } from './journal'

export const SEVERITIES: readonly Severity[] = ['BLOCKER', 'HIGH', 'MEDIUM', 'LOW']

const HTML_ENTITIES: Readonly<Record<string, string>> = { '&lt;': '<', '&gt;': '>', '&amp;': '&', '&quot;': '"', '&#39;': "'" }

/** One pass, so `&amp;lt;` becomes `&lt;` and not `<`. */
const unescapeHtml = (text: string): string => text.replace(/&(?:lt|gt|amp|quot|#39);/g, (entity) => HTML_ENTITIES[entity] ?? entity)

const tagOf = (text: string, tag: string): string | null => {
  const match = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`).exec(text)
  return match ? (match[1] ?? '').trim() : null
}

/** The tags of a `<task-notification>` prompt; `result` is the parsed, HTML-unescaped JSON (null when absent or unparsable). Null when the text holds no `<task-notification>`. */
export function parseTaskNotification(text: string): TaskNotification | null {
  if (!text.includes('<task-notification>')) return null
  const raw = tagOf(text, 'result')
  const parsed = raw === null ? null : parseJson(unescapeHtml(raw))
  return {
    toolUseId: tagOf(text, 'tool-use-id'),
    taskId: tagOf(text, 'task-id'),
    status: tagOf(text, 'status'),
    summary: tagOf(text, 'summary'),
    outputFile: tagOf(text, 'output-file'),
    result: parsed !== null && parsed.ok ? parsed.value : null,
  }
}

/** The most bytes of a task output file the HUD reads. */
export const TASK_OUTPUT_LIMIT = 4 * 1024 * 1024

/**
 * May the HUD read this task output file? An absolute path of at most 1024 characters, with a
 * `/tasks/` segment, ending in `.output`, with no `..` segment and no control character
 * (a newline included). The engine names it; the check keeps a forged tag from reaching elsewhere.
 */
export function isSafeTaskOutput(path: string): boolean {
  if (path.length === 0 || path.length > 1024 || !path.startsWith('/')) return false
  if (/[\u0000-\u001f\u007f-\u009f]/.test(path)) return false
  if (path.split('/').some(segment => segment === '..')) return false
  return path.includes('/tasks/') && path.endsWith('.output')
}

/** Where a value is not the review workflow's return, or a return with a junk field: a value of another shape is an error, never a default. */
export type ReviewDecodeError = ShapeError

/**
 * A refuter's vote as review-workflow.js compacts it. This and the `Workflow*` types below are
 * the producer's JSON, the decoder's input expectations: `?:` marks a key the producer leaves
 * out (never `null`). Tests type their returns against them with `satisfies`.
 */
export interface WorkflowVote {
  readonly reason: string
  readonly evidence: string
}

/** A finding as the workflow prints it (`oneLine`; `risk` only when `fileRisk` labels the file; `why` and `fix` on a below-floor BLOCKER or HIGH). */
export interface WorkflowFinding {
  readonly severity: string
  readonly confidence: number
  readonly file: string
  readonly line: number | null
  readonly summary: string
  readonly risk?: RiskLabel
  readonly why?: string
  readonly fix?: string
}

/** A deduplicated finding (`compact`): every lens that reported it, and the other lenses' wording. */
export interface WorkflowCompactFinding extends WorkflowFinding {
  readonly lenses: readonly string[]
  readonly alsoReported: readonly { readonly lens: string; readonly summary: string }[]
}

/** A survivor (`survivor`): how it was checked, the vote as `<refuting>/<asked>`, the counted votes. */
export interface WorkflowSurvivor extends WorkflowCompactFinding {
  readonly verification: Verification
  readonly quorum: string
  readonly refuters: readonly WorkflowVote[]
}

/** A killed entry: the finding, the full quorum that killed it, the counted votes. */
export interface WorkflowKilled {
  readonly finding: WorkflowCompactFinding
  readonly quorum: string
  readonly reasons: readonly WorkflowVote[]
}

/** The workflow's return: a finished run, or an aborted one (`aborted` set, everything else empty). */
export interface WorkflowReturn {
  readonly survivors: readonly WorkflowSurvivor[]
  readonly killed: readonly WorkflowKilled[]
  readonly belowFloor: readonly WorkflowFinding[]
  readonly counts: { readonly [K in keyof ReviewCounts]: number }
  readonly coverage: {
    readonly verify: string
    readonly refutersRequested: number
    readonly refutersReported: number
    readonly unverified: number
    readonly riskOrdered?: true
  }
  readonly lensesRun: readonly string[]
  readonly aborted?: string
}

/** The review workflow's return (review-workflow.js), decoded: every finding checked, counts and coverage with the producer's keys. */
export interface ReviewReturn {
  readonly survivors: readonly SurvivorFinding[]
  readonly killed: readonly KilledFinding[]
  readonly belowFloor: readonly BelowFloorFinding[]
  readonly counts: ReviewCounts
  readonly coverage: ReviewCoverage
  readonly lensesRun: readonly string[]
  /** The return's `aborted` reason when the run stopped early; null otherwise. */
  readonly aborted: string | null
}

// ---------------------------------------------------------------------------------------
// The decoding kernel: the workflow's JSON and the stored state read through one set of
// field decoders, each failing with the path it stopped at
// ---------------------------------------------------------------------------------------

/** The value as a member of the table's union, null for null or no key, or the failure at `path`. */
const decodeOptionalMember = <K extends string>(table: Readonly<Record<K, true>>, value: unknown, path: string, expected: string): Decoded<K | null> =>
  value === undefined || value === null ? ok(null) : decodeMember(table, value, path, expected)

/** The entries of a list that decode, the others dropped; none for a value that is no list. */
const keepDecoded = <A>(value: unknown, path: string, decode: (value: unknown, path: string) => Decoded<A>): readonly A[] =>
  (listOf(value) ?? []).flatMap((item, index) => {
    const one = decode(item, `${path}[${index}]`)
    return one.ok ? [one.value] : []
  })

/** Text with its control characters out. */
const decodeText = (value: unknown, path: string): Decoded<string> => {
  const text = stringOf(value)
  return text === null ? fail(path, 'text') : ok(stripControl(text))
}

/** Text, null for null or no key, or the failure at `path`. */
const decodeOptionalText = (value: unknown, path: string): Decoded<string | null> =>
  value === undefined || value === null ? ok(null) : decodeText(value, path)

const decodeFile = (value: unknown, path: string): Decoded<string> => {
  const file = decodeText(value, path)
  return file.ok && file.value.trim() === '' ? fail(path, 'a non-empty file path') : file
}

/** A line number, null for null or no key (the finding names no line). */
const decodeLine = (value: unknown, path: string): Decoded<number | null> => {
  if (value === undefined || value === null) return ok(null)
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? ok(value) : fail(path, 'a line number or null')
}

const decodeLenses = (value: unknown, path: string): Decoded<readonly string[]> => {
  const lenses = stringListOf(value)
  return lenses === null ? fail(path, 'a list of lens names') : ok(lenses.map(stripControl))
}

const decodeCount = (value: unknown, path: string): Decoded<number> => {
  const count = numberOf(value)
  return count !== null && count >= 0 ? ok(count) : fail(path, 'a count')
}

/** A severity label with its control characters out, trimmed: the known four in any case, else the label as given; null when nothing is left. */
const severityOf = (label: string): FindingSeverity | null => {
  const clean = stripControl(label).trim()
  if (clean === '') return null
  const upper = clean.toUpperCase()
  const known = SEVERITIES.find(severity => severity === upper)
  return known === undefined ? { kind: 'other', label: clean } : { kind: 'known', severity: known }
}

/** `<refuting>/<asked>` as the workflow writes a quorum; null for any other text or more refuting than asked. */
const quorumOf = (text: string): Quorum | null => {
  const match = /^(\d+)\/(\d+)$/.exec(text)
  if (match === null) return null
  const refuting = Number(match[1])
  const asked = Number(match[2])
  return Number.isSafeInteger(asked) && refuting <= asked ? { refuting, asked } : null
}

const RISK_LABELS: Readonly<Record<RiskLabel, true>> = { top: true, high: true, mid: true, low: true }
const VERIFICATIONS: Readonly<Record<Verification, true>> = { held: true, 'refuters-died': true, 'unverified-cap': true, 'not-targeted': true }
const SEVERITY_SET: Readonly<Record<Severity, true>> = { BLOCKER: true, HIGH: true, MEDIUM: true, LOW: true }
const MARKS: Readonly<Record<ReviewMark, true>> = { accepted: true, killed: true }
const TICK_STATES: Readonly<Record<TickOverride['state'], true>> = { on: true, off: true }

/** Where a finding comes from: the workflow's return (its JSON as the producer writes it) or the stored state (this module's own shape). */
type FindingSource = 'workflow' | 'stored'

/** How one source spells the fields that differ between the two. */
interface FindingCodec {
  readonly severity: (value: unknown, path: string) => Decoded<FindingSeverity>
  readonly confidence: (value: unknown, path: string) => Decoded<number | null>
  readonly quorum: (value: unknown, path: string) => Decoded<Quorum>
  /** Does a finding carry its variant's `kind`? */
  readonly isTagged: boolean
  /** May a count or a coverage field be left out (read as null)? */
  readonly isCountOptional: boolean
}

const FINDING_CODEC: Readonly<Record<FindingSource, FindingCodec>> = {
  workflow: {
    severity: (value, path) => {
      const text = stringOf(value)
      const severity = text === null ? null : severityOf(text)
      return severity === null ? fail(path, 'a severity label') : ok(severity)
    },
    // the producer's confidence is an integer 0-100; anything else is drawn as unknown, never as 0
    confidence: value => ok(numberOf(value)),
    quorum: (value, path) => {
      const text = stringOf(value)
      const quorum = text === null ? null : quorumOf(text)
      return quorum === null ? fail(path, 'a quorum <refuting>/<asked>') : ok(quorum)
    },
    isTagged: false,
    isCountOptional: true,
  },
  stored: {
    severity: (value, path) => {
      const record = recordOf(value)
      if (record === null) return fail(path, 'a stored severity')
      if (record.kind === 'known') return decodeKnown(record.severity, path)
      const label = stringOf(record.label)
      return record.kind === 'other' && label !== null && label.trim() !== '' ? ok({ kind: 'other', label }) : fail(path, 'a stored severity')
    },
    confidence: (value, path) => {
      if (value === null) return ok(null)
      const confidence = numberOf(value)
      return confidence === null ? fail(path, 'a confidence or null') : ok(confidence)
    },
    quorum: (value, path) => {
      const record = recordOf(value)
      const refuting = numberOf(record?.refuting)
      const asked = numberOf(record?.asked)
      return refuting !== null && asked !== null && Number.isSafeInteger(refuting) && Number.isSafeInteger(asked) && refuting >= 0 && refuting <= asked
        ? ok({ refuting, asked })
        : fail(path, 'a stored quorum')
    },
    isTagged: true,
    isCountOptional: false,
  },
}

/** A stored `known` severity: the severity checked against the four. */
const decodeKnown = (value: unknown, path: string): Decoded<FindingSeverity> => {
  const severity = decodeMember(SEVERITY_SET, value, `${path}.severity`, 'a known severity')
  return severity.ok ? ok({ kind: 'known', severity: severity.value }) : severity
}

/** The fields every finding carries, read off a record of `source`. */
const decodeCoreOf = (raw: JsonRecord, path: string, source: FindingSource): Decoded<FindingCore> => {
  const codec = FINDING_CODEC[source]
  const severity = codec.severity(raw.severity, `${path}.severity`)
  if (!severity.ok) return severity
  const confidence = codec.confidence(raw.confidence, `${path}.confidence`)
  if (!confidence.ok) return confidence
  const file = decodeFile(raw.file, `${path}.file`)
  if (!file.ok) return file
  const line = decodeLine(raw.line, `${path}.line`)
  if (!line.ok) return line
  const summary = decodeText(raw.summary, `${path}.summary`)
  if (!summary.ok) return summary
  const risk = decodeOptionalMember(RISK_LABELS, raw.risk, `${path}.risk`, 'a risk label (top, high, mid, low) or none')
  if (!risk.ok) return risk
  return ok({ severity: severity.value, confidence: confidence.value, file: file.value, line: line.value, summary: summary.value, risk: risk.value })
}

/** The record at `path`, its variant's `kind` checked when the source tags it. */
const decodeTagged = (value: unknown, path: string, source: FindingSource, kind: string): Decoded<JsonRecord> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  return FINDING_CODEC[source].isTagged && raw.value.kind !== kind ? fail(`${path}.kind`, `'${kind}'`) : raw
}

const decodeSurvivorOf =
  (source: FindingSource) =>
  (value: unknown, path: string): Decoded<SurvivorFinding> => {
    const raw = decodeTagged(value, path, source, 'survivor')
    if (!raw.ok) return raw
    const core = decodeCoreOf(raw.value, path, source)
    if (!core.ok) return core
    const lenses = decodeLenses(raw.value.lenses, `${path}.lenses`)
    if (!lenses.ok) return lenses
    const verification = decodeMember(VERIFICATIONS, raw.value.verification, `${path}.verification`, 'a verification')
    if (!verification.ok) return verification
    const quorum = FINDING_CODEC[source].quorum(raw.value.quorum, `${path}.quorum`)
    if (!quorum.ok) return quorum
    return ok({ kind: 'survivor', ...core.value, lenses: lenses.value, verification: verification.value, quorum: quorum.value })
  }

/** A killed entry of the return: its `finding` lifted, with the entry's `quorum`. */
const decodeWorkflowKilled = (value: unknown, path: string): Decoded<KilledFinding> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const finding = decodeRecord(raw.value.finding, `${path}.finding`)
  if (!finding.ok) return finding
  const core = decodeCoreOf(finding.value, `${path}.finding`, 'workflow')
  if (!core.ok) return core
  const lenses = decodeLenses(finding.value.lenses, `${path}.finding.lenses`)
  if (!lenses.ok) return lenses
  const quorum = FINDING_CODEC.workflow.quorum(raw.value.quorum, `${path}.quorum`)
  if (!quorum.ok) return quorum
  return ok({ kind: 'killed', ...core.value, lenses: lenses.value, quorum: quorum.value })
}

const decodeStoredKilled = (value: unknown, path: string): Decoded<KilledFinding> => {
  const raw = decodeTagged(value, path, 'stored', 'killed')
  if (!raw.ok) return raw
  const core = decodeCoreOf(raw.value, path, 'stored')
  if (!core.ok) return core
  const lenses = decodeLenses(raw.value.lenses, `${path}.lenses`)
  if (!lenses.ok) return lenses
  const quorum = FINDING_CODEC.stored.quorum(raw.value.quorum, `${path}.quorum`)
  if (!quorum.ok) return quorum
  return ok({ kind: 'killed', ...core.value, lenses: lenses.value, quorum: quorum.value })
}

const decodeBelowFloorOf =
  (source: FindingSource) =>
  (value: unknown, path: string): Decoded<BelowFloorFinding> => {
    const raw = decodeTagged(value, path, source, 'below-floor')
    if (!raw.ok) return raw
    const core = decodeCoreOf(raw.value, path, source)
    return core.ok ? ok({ kind: 'below-floor', ...core.value }) : core
  }

/** A count field: a count; null for null; a field left out is null only where the source may leave it out. */
const decodeCountField = (value: unknown, path: string, source: FindingSource): Decoded<number | null> => {
  if (value === null || (value === undefined && FINDING_CODEC[source].isCountOptional)) return ok(null)
  return decodeCount(value, path)
}

/** The value of a field whose failure was already returned. */
const valueOf = (field: Decoded<number | null>): number | null => (field.ok ? field.value : null)

const decodeCounts = (value: unknown, path: string, source: FindingSource): Decoded<ReviewCounts> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const at = (key: keyof ReviewCounts): Decoded<number | null> => decodeCountField(raw.value[key], `${path}.${key}`, source)
  const found = at('found')
  const deduped = at('deduped')
  const candidates = at('candidates')
  const refuters = at('refuters')
  const unverified = at('unverified')
  const survivors = at('survivors')
  const killed = at('killed')
  const failed = [found, deduped, candidates, refuters, unverified, survivors, killed].find(field => !field.ok)
  if (failed !== undefined && !failed.ok) return failed
  return ok({
    found: valueOf(found),
    deduped: valueOf(deduped),
    candidates: valueOf(candidates),
    refuters: valueOf(refuters),
    unverified: valueOf(unverified),
    survivors: valueOf(survivors),
    killed: valueOf(killed),
  })
}

/** The coverage the board draws; a return that carries none has every field null. */
const decodeCoverage = (value: unknown, path: string, source: FindingSource): Decoded<ReviewCoverage> => {
  if (value === undefined && FINDING_CODEC[source].isCountOptional) return ok({ refutersRequested: null, refutersReported: null, unverified: null })
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const at = (key: keyof ReviewCoverage): Decoded<number | null> => decodeCountField(raw.value[key], `${path}.${key}`, source)
  const refutersRequested = at('refutersRequested')
  const refutersReported = at('refutersReported')
  const unverified = at('unverified')
  const failed = [refutersRequested, refutersReported, unverified].find(field => !field.ok)
  if (failed !== undefined && !failed.ok) return failed
  return ok({ refutersRequested: valueOf(refutersRequested), refutersReported: valueOf(refutersReported), unverified: valueOf(unverified) })
}

/** The return's `aborted` reason, control characters out; null when none (an empty reason is none). */
const decodeAborted = (value: unknown, path: string): Decoded<string | null> => {
  const reason = decodeOptionalText(value, path)
  return reason.ok && reason.value !== null && reason.value.trim() === '' ? ok(null) : reason
}

/**
 * The review workflow's return, decoded: arrays `survivors`, `killed`, `belowFloor` whose
 * entries are each a finding of their variant, an object `counts`. A junk entry fails the whole
 * return, so no card stands for a finding that does not exist (D12).
 */
export function decodeReviewReturn(value: unknown): Result<ReviewDecodeError, ReviewReturn> {
  const raw = decodeRecord(value, '$')
  if (!raw.ok) return raw
  const survivors = decodeList(raw.value.survivors, '$.survivors', decodeSurvivorOf('workflow'))
  if (!survivors.ok) return survivors
  const killed = decodeList(raw.value.killed, '$.killed', decodeWorkflowKilled)
  if (!killed.ok) return killed
  const belowFloor = decodeList(raw.value.belowFloor, '$.belowFloor', decodeBelowFloorOf('workflow'))
  if (!belowFloor.ok) return belowFloor
  const counts = decodeCounts(raw.value.counts, '$.counts', 'workflow')
  if (!counts.ok) return counts
  const coverage = decodeCoverage(raw.value.coverage, '$.coverage', 'workflow')
  if (!coverage.ok) return coverage
  const lensesRun = decodeLenses(raw.value.lensesRun, '$.lensesRun')
  if (!lensesRun.ok) return lensesRun
  const aborted = decodeAborted(raw.value.aborted, '$.aborted')
  if (!aborted.ok) return aborted
  return ok({
    survivors: survivors.value,
    killed: killed.value,
    belowFloor: belowFloor.value,
    counts: counts.value,
    coverage: coverage.value,
    lensesRun: lensesRun.value,
    aborted: aborted.value,
  })
}

/** The review return inside a task output file's JSON: its `result` when that decodes, else the object itself. */
export function reviewReturnOfOutput(parsed: unknown): Result<ReviewDecodeError, ReviewReturn> {
  const record = recordOf(parsed)
  const inner = record !== null && record.result !== undefined ? decodeReviewReturn(record.result) : null
  return inner !== null && inner.ok ? inner : decodeReviewReturn(parsed)
}

/** The run id in a Workflow tool result text (`Run ID: wf_…`), or null. */
export function runIdOf(text: string): string | null {
  const match = /Run ID: (wf_[\w-]+)/.exec(text)
  return match ? (match[1] ?? null) : null
}

/** Does a Workflow call launch the shipgate review workflow? Any of the strings naming `shipgate-review`. */
export function isReviewLaunch(parts: readonly (string | undefined)[]): boolean {
  return parts.some((part) => typeof part === 'string' && part.includes('shipgate-review'))
}

/** Control characters (C0, DEL, C1) out of text from the return, so the card, the group header and the prompt agree. */
export const stripControl = (text: string): string => text.replace(/[\u0000-\u001f\u007f-\u009f]/g, '')

/** A board as captured, before `pushBoard` numbers its round. */
export type CapturedBoard = Omit<ReviewBoard, 'round'>

/** The decoded return as a board: survivors in the return's order, each unmarked; stamped with the run id, the stream and the capture time. */
export function toReviewBoard(ret: ReviewReturn, runId: string | null, stream: StreamName | null, at: IsoTime): CapturedBoard {
  return {
    stream,
    runId,
    at,
    counts: ret.counts,
    coverage: ret.coverage,
    survivors: ret.survivors.map(finding => ({ finding, mark: null })),
    killed: ret.killed,
    belowFloor: ret.belowFloor,
    lensesRun: ret.lensesRun,
    aborted: ret.aborted,
  }
}

/** The last three path segments: `a/b/c/d/e.ts` → `c/d/e.ts`; shorter paths unchanged. */
export function shortPath(file: string): string {
  const segments = file.split('/')
  return segments.length <= 3 ? file : segments.slice(-3).join('/')
}

/** `file:line`, `file:?` when the line is null. */
export function locationOf(finding: Pick<FindingCore, 'file' | 'line'>): string {
  return `${finding.file}:${finding.line === null ? '?' : String(finding.line)}`
}

/** `file:line` with the path cut to its last three segments. */
export function shortLocation(finding: Pick<FindingCore, 'file' | 'line'>): string {
  return locationOf({ ...finding, file: shortPath(finding.file) })
}

/** A severity as a card and a group header name it: the known severity, or the other label. */
export const severityLabel = (severity: FindingSeverity): string => (severity.kind === 'known' ? severity.severity : severity.label)

/** A path a prompt may carry, after the cut to three segments: letters, digits and path punctuation; no whitespace, no control characters. */
const SAFE_FILE = /^[\p{L}\p{N}_./@+\-[\]()~,=]{1,200}$/u
const SAFE_LENS = /^[\w+-]{1,40}$/

/** A finding's fields as a prompt may carry them: a known severity, a path-shaped file and lens names, else `?`; never free text. */
const promptFields = (finding: SurvivorFinding | null): { readonly severity: string; readonly location: string; readonly lenses: string } => {
  if (finding === null) return { severity: '?', location: '?', lenses: '?' }
  const file = shortPath(stripControl(finding.file))
  const lenses = finding.lenses.map(stripControl).filter(lens => SAFE_LENS.test(lens))
  return {
    // an other label is free text: never in a prompt
    severity: finding.severity.kind === 'known' ? finding.severity.severity : '?',
    location: locationOf({ file: SAFE_FILE.test(file) ? file : '?', line: finding.line }),
    lenses: lenses.length > 0 ? lenses.join('+') : '?',
  }
}

/** A severity group of the board's survivors: its severity and its survivors' indexes in `survivors`. */
export interface SeverityGroup {
  readonly severity: FindingSeverity
  readonly indexes: readonly number[]
}

/** Survivors grouped by severity in SEVERITIES order, then each other label in first-seen order; empty groups left out. */
export function groupBySeverity(survivors: readonly BoardSurvivor[]): readonly SeverityGroup[] {
  const indexesOf = (isIn: (severity: FindingSeverity) => boolean): readonly number[] =>
    survivors.flatMap((survivor, index) => (isIn(survivor.finding.severity) ? [index] : []))
  const known = SEVERITIES.map((severity): SeverityGroup => ({
    severity: { kind: 'known', severity },
    indexes: indexesOf(s => s.kind === 'known' && s.severity === severity),
  }))
  const labels = survivors.reduce<readonly string[]>((seen, { finding }) => {
    const severity = finding.severity
    return severity.kind === 'other' && !seen.includes(severity.label) ? [...seen, severity.label] : seen
  }, [])
  const others = labels.map((label): SeverityGroup => ({ severity: { kind: 'other', label }, indexes: indexesOf(s => s.kind === 'other' && s.label === label) }))
  return [...known, ...others].filter(group => group.indexes.length > 0)
}

/** What a mark's prompt says: the button the user pressed, and what the model is asked to do. */
interface MarkPrompt {
  readonly press: string
  readonly ask: string
}

/** Each mark's prompt. */
const MARK_PROMPT: Readonly<Record<ReviewMark, MarkPrompt>> = {
  accepted: { press: 'Accept', ask: "fix it in the implement round and record it under the worklog's review round." },
  killed: { press: 'Kill', ask: "treat it as rejected, ask the user for the reason, record it under the worklog's Rejected findings, and do not fix it." },
}

/** The Accept / Kill prompt text (plain, FR-032): names the finding by its 1-based position among the survivors, the total, severity, short file:line and lenses, and the stream; never the summary, why or fix. */
export function findingPrompt(action: ReviewMark, index: number, board: ReviewBoard): string {
  const { severity, location, lenses } = promptFields(board.survivors[index]?.finding ?? null)
  const stream = board.stream === null ? 'the current stream' : `stream ${stripControl(board.stream)}`
  const { press, ask } = MARK_PROMPT[action]
  return `The user pressed ${press} on review finding ${index + 1} of ${board.survivors.length} in review round ${board.round} (${severity}, ${location}, lens ${lenses}) in the shipgate HUD for ${stream}: ${ask}`
}

/** The user's tick override on `criterion` for `stream`, so a tick holds for one stream only; null when none. */
export function tickOf(ticks: readonly TickEntry[], stream: StreamName | null, criterion: CriterionId): TickOverride | null {
  return ticks.find(tick => tick.stream === stream && tick.criterion === criterion)?.override ?? null
}

/** The most review rounds kept per stream; a newer return drops the stream's oldest. */
export const ROUNDS_PER_STREAM = 5

/** Does a board belong to the stream shown? A board captured with no stream is drawn for any. */
const isBoardOf = (board: ReviewBoard, stream: StreamName | null): boolean => board.stream === null || board.stream === stream

const stripDotSlash = (path: string): string => path.replace(/^(\.\/)+/, '')

/** The map's own value at `key`; null when it has none (a key named like an Object method included). */
const ownDisposition = (map: Readonly<Record<string, Disposition>>, key: string): Disposition | null => (Object.hasOwn(map, key) ? (map[key] ?? null) : null)

/**
 * The orchestrator's disposition of a finding in a verdict's map; null when none. Exact keys
 * first: the full `file:line`, then the short one. Then by path suffix: a key `<path>:<line>`
 * matches when the line is the finding's and the finding's file is `<path>` or ends with
 * `/<path>` (a workflow reports absolute paths, an orchestrator writes repo-relative ones).
 * The longest matching path wins. A leading `./` is dropped on both sides.
 */
export function dispositionIn(map: Readonly<Record<string, Disposition>>, finding: Pick<FindingCore, 'file' | 'line'>): Disposition | null {
  const file = stripDotSlash(finding.file)
  const line = finding.line === null ? '?' : String(finding.line)
  const exact = ownDisposition(map, `${file}:${line}`) ?? ownDisposition(map, shortLocation(finding))
  if (exact !== null) return exact
  const best = Object.entries(map).reduce<{ readonly length: number; readonly disposition: Disposition } | null>((held, [key, disposition]) => {
    const cut = key.lastIndexOf(':')
    if (cut <= 0 || key.slice(cut + 1) !== line) return held
    const path = stripDotSlash(key.slice(0, cut))
    if (path === '' || !(file === path || file.endsWith(`/${path}`))) return held
    return held === null || path.length > held.length ? { length: path.length, disposition } : held
  }, null)
  return best === null ? null : best.disposition
}

/** A round's identity across streams: `<stream or ?>:<round>`. The fold, `OpenRound` and the Accept / Kill actions use it. */
export function roundId(board: Pick<ReviewBoard, 'stream' | 'round'>): RoundId {
  // cast: the one way to a RoundId, built from the board's own stream and round
  return `${board.stream ?? '?'}:${board.round}` as RoundId
}

/** The rounds of the stream shown, newest first. */
export function boardsFor(boards: readonly ReviewBoard[], stream: StreamName | null): readonly ReviewBoard[] {
  return boards.filter(board => isBoardOf(board, stream))
}

/** One finding in two deliveries of a return: the same place and the same words. */
const isSameFinding = (a: SurvivorFinding, b: SurvivorFinding): boolean => a.file === b.file && a.line === b.line && a.summary === b.summary

/**
 * A captured board pushed at the front as its stream's next round (one more than the stream's
 * highest, so a number is never reused after the oldest is dropped); the stream keeps its
 * newest ROUNDS_PER_STREAM rounds, other streams' rounds are kept as they are. A return
 * delivered again (the same stream and the same non-null run id) replaces its round in place,
 * keeping the round number and the marks of the survivors it still holds.
 */
export function pushBoard(boards: readonly ReviewBoard[], board: CapturedBoard): readonly ReviewBoard[] {
  const again = board.runId === null ? -1 : boards.findIndex(held => held.stream === board.stream && held.runId === board.runId)
  if (again >= 0) {
    return boards.map((held, index): ReviewBoard => {
      if (index !== again) return held
      const survivors = board.survivors.map((survivor, at) => {
        const before = held.survivors[at]
        return before !== undefined && isSameFinding(before.finding, survivor.finding) ? { ...survivor, mark: before.mark } : survivor
      })
      return { ...board, round: held.round, survivors }
    })
  }
  const round = 1 + Math.max(0, ...boards.filter(held => held.stream === board.stream).map(held => held.round))
  const next: readonly ReviewBoard[] = [{ ...board, round }, ...boards]
  // a board of the stream stays while fewer than ROUNDS_PER_STREAM of the stream's boards come before it
  return next.filter((held, index) => held.stream !== board.stream || next.slice(0, index).filter(newer => newer.stream === board.stream).length < ROUNDS_PER_STREAM)
}

/** The board with the survivor at `index` marked; unchanged when there is none. */
export function markSurvivor(board: ReviewBoard, index: number, mark: ReviewMark): ReviewBoard {
  if (board.survivors[index] === undefined) return board
  return { ...board, survivors: board.survivors.map((survivor, at) => (at === index ? { ...survivor, mark } : survivor)) }
}

/** The empty review state: no round, no tick, the newest round open. */
export const EMPTY_REVIEW: ReviewState = { boards: [], ticks: [], open: { kind: 'newest' } }

/** A stored survivor and the user's mark on it. */
const decodeStoredSurvivor = (value: unknown, path: string): Decoded<BoardSurvivor> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const finding = decodeSurvivorOf('stored')(raw.value.finding, `${path}.finding`)
  if (!finding.ok) return finding
  const mark = raw.value.mark === null ? ok(null) : decodeMember(MARKS, raw.value.mark, `${path}.mark`, 'a mark or null')
  return mark.ok ? ok({ finding: finding.value, mark: mark.value }) : mark
}

/** A stored stream: a stream name, or null for a board captured with none. */
const decodeStoredStream = (value: unknown, path: string): Decoded<StreamName | null> => {
  if (value === null) return ok(null)
  const text = stringOf(value)
  const stream = text === null ? null : streamName(text)
  return stream === null ? fail(path, 'a stream name or null') : ok(stream)
}

/** One stored round: every field and every finding decoded, or the failure (the board is then dropped, D11). */
const decodeStoredBoard = (value: unknown, path: string): Decoded<ReviewBoard> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const board = raw.value
  const stream = decodeStoredStream(board.stream, `${path}.stream`)
  if (!stream.ok) return stream
  const round = numberOf(board.round)
  if (round === null || !Number.isSafeInteger(round) || round < 1) return fail(`${path}.round`, 'a round number')
  const runId = board.runId === null ? ok(null) : decodeText(board.runId, `${path}.runId`)
  if (!runId.ok) return runId
  const atText = stringOf(board.at)
  const at = atText === null ? null : isoTime(atText)
  if (at === null) return fail(`${path}.at`, 'an ISO time')
  const counts = decodeCounts(board.counts, `${path}.counts`, 'stored')
  if (!counts.ok) return counts
  const coverage = decodeCoverage(board.coverage, `${path}.coverage`, 'stored')
  if (!coverage.ok) return coverage
  const survivors = decodeList(board.survivors, `${path}.survivors`, decodeStoredSurvivor)
  if (!survivors.ok) return survivors
  const killed = decodeList(board.killed, `${path}.killed`, decodeStoredKilled)
  if (!killed.ok) return killed
  const belowFloor = decodeList(board.belowFloor, `${path}.belowFloor`, decodeBelowFloorOf('stored'))
  if (!belowFloor.ok) return belowFloor
  const lensesRun = decodeLenses(board.lensesRun, `${path}.lensesRun`)
  if (!lensesRun.ok) return lensesRun
  const aborted = board.aborted === null ? ok(null) : decodeText(board.aborted, `${path}.aborted`)
  if (!aborted.ok) return aborted
  return ok({
    stream: stream.value,
    round,
    runId: runId.value,
    at,
    counts: counts.value,
    coverage: coverage.value,
    survivors: survivors.value,
    killed: killed.value,
    belowFloor: belowFloor.value,
    lensesRun: lensesRun.value,
    aborted: aborted.value,
  })
}

/** One stored tick: the stream (null: none), the criterion id, the override and the verdict seq it was made against. */
const decodeTickEntry = (value: unknown, path: string): Decoded<TickEntry> => {
  const raw = decodeRecord(value, path)
  if (!raw.ok) return raw
  const stream = decodeStoredStream(raw.value.stream, `${path}.stream`)
  if (!stream.ok) return stream
  const idText = stringOf(raw.value.criterion)
  const criterion = idText === null ? null : criterionId(idText)
  if (criterion === null) return fail(`${path}.criterion`, 'a criterion id')
  const override = decodeRecord(raw.value.override, `${path}.override`)
  if (!override.ok) return override
  const state = decodeMember(TICK_STATES, override.value.state, `${path}.override.state`, "'on' or 'off'")
  if (!state.ok) return state
  const seq = decodeStoredSeq(override.value.seq, `${path}.override.seq`)
  if (!seq.ok) return seq
  return ok({ stream: stream.value, criterion, override: { state: state.value, seq: seq.value } })
}

/** The verdict seq a tick was made against: an event seq, or null for none. */
const decodeStoredSeq = (value: unknown, path: string): Decoded<EventSeq | null> => {
  if (value === null) return ok(null)
  const number = numberOf(value)
  const seq = number === null ? null : eventSeq(number)
  return seq === null ? fail(path, 'an event seq or null') : ok(seq)
}

/** The open round as stored; a round that names no stored board, or a value of another shape, reads as the newest. */
const decodeOpenRound = (value: unknown, boards: readonly ReviewBoard[]): ReviewState['open'] => {
  const raw = recordOf(value)
  if (raw?.kind === 'folded') return { kind: 'folded' }
  if (raw?.kind !== 'round') return { kind: 'newest' }
  // the id is matched against the boards, so the RoundId comes from its one constructor
  const open = boards.find(board => roundId(board) === raw.id)
  return open === undefined ? { kind: 'newest' } : { kind: 'round', id: roundId(open) }
}

/**
 * A stored review state, decoded at the read: a board or a tick entry of another shape is
 * dropped, never cast (D11). An older build's value is under another shape tag and reads as
 * absent.
 */
export function decodeReviewState(raw: unknown): ReviewState {
  const state = recordOf(raw)
  if (state === null) return EMPTY_REVIEW
  const boards = keepDecoded(state.boards, '$.boards', decodeStoredBoard)
  const decodedTicks = keepDecoded(state.ticks, '$.ticks', decodeTickEntry)
  // at most one entry per stream and criterion: the first stands
  const ticks = decodedTicks.filter(
    (tick, index) => decodedTicks.findIndex(other => other.stream === tick.stream && other.criterion === tick.criterion) === index,
  )
  return { boards, ticks, open: decodeOpenRound(state.open, boards) }
}

/** A criterion's tick as the Review tab draws it. */
export type CriterionGlyph = '☑' | '☒' | '☐'

/** An override's glyph. */
const OVERRIDE_GLYPH: Readonly<Record<TickOverride['state'], CriterionGlyph>> = { on: '☑', off: '☐' }

/** The journal's status as a glyph. */
const STATUS_GLYPH: Readonly<Record<CriterionStatus, CriterionGlyph>> = { met: '☑', unmet: '☒' }

/**
 * A criterion's glyph: the user's override wins (`on` ☑, `off` ☐) while it was made against the
 * current verdict (`seq`); else the journal's status (`met` ☑, `unmet` ☒), else ☐.
 */
export function criterionGlyph(override: TickOverride | null, status: CriterionStatus | null, seq: EventSeq | null): CriterionGlyph {
  if (override !== null && override.seq === seq) return OVERRIDE_GLYPH[override.state]
  return status === null ? '☐' : STATUS_GLYPH[status]
}

/**
 * The overrides after a press on `criterion` of `stream`: a ticked row unticks, any other row
 * ticks, so every press changes the glyph. An override equal to what the journal shows is
 * dropped (back to the journal); a kept one records the verdict `seq` it was made against.
 * At most one entry per stream and criterion.
 */
export function nextTicks(
  ticks: readonly TickEntry[],
  stream: StreamName | null,
  criterion: CriterionId,
  status: CriterionStatus | null,
  seq: EventSeq | null,
): readonly TickEntry[] {
  const rest = ticks.filter(tick => !(tick.stream === stream && tick.criterion === criterion))
  const entry = (state: TickOverride['state']): TickEntry => ({ stream, criterion, override: { state, seq } })
  const isTicked = criterionGlyph(tickOf(ticks, stream, criterion), status, seq) === '☑'
  // the journal draws ☑ only for met: there an untick is kept as `off`, a tick is the journal's own
  const isMet = status === 'met'
  if (isTicked) return isMet ? [...rest, entry('off')] : rest
  return isMet ? rest : [...rest, entry('on')]
}

const CRITERION_LINE = /^\s*-\s*\*\*(SC-\d+)\*\*\s*[—–-]+\s*(.*?)\s*$/
const HEADING = /^(#{1,6})\s+(.*?)\s*$/
const CONTINUATION = /^\s+\S/

/**
 * Where the criteria fold stands: outside a Success criteria section; inside it with no
 * criterion taking continuation lines (`between`); right after a criterion, whose text an
 * indented line continues (`open`); or after a duplicate id, whose continuation is dropped.
 */
type CriteriaScan = 'outside' | 'between' | 'open' | 'skipping'

interface CriteriaFold {
  readonly criteria: readonly Criterion[]
  readonly scan: CriteriaScan
}

/** One line folded into the criteria. */
const foldCriterionLine = (fold: CriteriaFold, line: string): CriteriaFold => {
  const heading = HEADING.exec(line)
  if (heading !== null) {
    const level = (heading[1] ?? '').length
    // a deeper heading closes the open criterion, not the section
    if (level > 2) return fold.scan === 'outside' ? fold : { ...fold, scan: 'between' }
    return { ...fold, scan: level === 2 && /^success criteria$/i.test(heading[2] ?? '') ? 'between' : 'outside' }
  }
  if (fold.scan === 'outside') return fold
  const match = CRITERION_LINE.exec(line)
  const id = match === null ? null : criterionId(match[1] ?? '')
  if (match !== null && id !== null) {
    if (fold.criteria.some(criterion => criterion.id === id)) return { ...fold, scan: 'skipping' }
    return { criteria: [...fold.criteria, { id, text: match[2] ?? '' }], scan: 'open' }
  }
  if (CONTINUATION.test(line) && fold.scan === 'skipping') return fold
  const last = fold.criteria[fold.criteria.length - 1]
  if (CONTINUATION.test(line) && fold.scan === 'open' && last !== undefined) {
    return { ...fold, criteria: [...fold.criteria.slice(0, -1), { ...last, text: `${last.text} ${line.trim()}`.trim() }] }
  }
  return { ...fold, scan: 'between' }
}

/** The `- **SC-NNN** — text` lines under every `## Success criteria` heading of a PRD. An
 *  indented line that follows a criterion continues its text (PRDs wrap long lines). An id
 *  seen before is skipped (the first wins), so a tick names one criterion. A fold, no
 *  mutation of a pushed criterion. */
export function parseCriteria(prd: string): readonly Criterion[] {
  return prd.split('\n').reduce<CriteriaFold>(foldCriterionLine, { criteria: [], scan: 'outside' }).criteria
}
