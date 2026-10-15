// The Review board's pure core: the review workflow's return, as Claude Code delivers it in a
// `<task-notification>` user turn, in; a normalised board, its grouping and the Accept / Kill
// prompt text out. No `$` here, so the tests run it without a session.

import type { Criterion, ReviewBoard, ReviewFinding, ReviewMark, Severity, TaskNotification } from '../types'
import { asRecord, asString, asStringList, isRecord } from './json'

export const SEVERITIES: readonly Severity[] = ['BLOCKER', 'HIGH', 'MEDIUM', 'LOW']

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])

const asFiniteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const HTML_ENTITIES: Record<string, string> = { '&lt;': '<', '&gt;': '>', '&amp;': '&', '&quot;': '"', '&#39;': "'" }

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
  let result: unknown = null
  if (raw !== null) {
    try {
      result = JSON.parse(unescapeHtml(raw))
    } catch {
      result = null
    }
  }
  return {
    toolUseId: tagOf(text, 'tool-use-id'),
    taskId: tagOf(text, 'task-id'),
    status: tagOf(text, 'status'),
    summary: tagOf(text, 'summary'),
    outputFile: tagOf(text, 'output-file'),
    result,
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

/** The review return inside a task output file's JSON: its `result` when that has the shape, else the object itself when it has, else null. */
export function reviewReturnOfOutput(parsed: unknown): unknown {
  if (isRecord(parsed) && isReviewReturn(parsed.result)) return parsed.result
  return isReviewReturn(parsed) ? parsed : null
}

/** Does a parsed result look like the review workflow's return: arrays `survivors`, `killed`, `belowFloor` and an object `counts`? */
export function isReviewReturn(value: unknown): boolean {
  if (!isRecord(value)) return false
  return Array.isArray(value.survivors) && Array.isArray(value.killed) && Array.isArray(value.belowFloor) && isRecord(value.counts)
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
const stripControl = (text: string): string => text.replace(/[\u0000-\u001f\u007f-\u009f]/g, '')

/** A known severity in capitals (`high` → `HIGH`); any other label as given, control characters out. */
const toSeverity = (value: unknown): string => {
  const label = stripControl(asString(value, '?')).trim()
  const upper = label.toUpperCase()
  return (SEVERITIES as readonly string[]).includes(upper) ? upper : label || '?'
}

const toFinding = (value: unknown, quorum?: unknown): ReviewFinding => {
  const record = asRecord(value)
  const line = asFiniteNumber(record.line)
  const risk = record.risk
  const text = (field: unknown): string => stripControl(asString(field))
  return {
    severity: toSeverity(record.severity),
    confidence: asFiniteNumber(record.confidence) ?? 0,
    file: text(record.file),
    line,
    summary: text(record.summary),
    lenses: asStringList(record.lenses).map(stripControl),
    verification: text(record.verification),
    quorum: text(quorum === undefined ? record.quorum : quorum),
    risk: typeof risk === 'string' ? stripControl(risk) : null,
  }
}

const toCounts = (value: unknown): Record<string, number> => {
  const counts: Record<string, number> = {}
  for (const [key, count] of Object.entries(asRecord(value))) {
    const number = asFiniteNumber(count)
    if (number !== null) counts[key] = number
  }
  return counts
}

/** The return normalised into a board: survivors in the return's order, killed entries lifted from `finding` with their `quorum`, below-floor entries as they are; a non-numeric `confidence` → 0; missing arrays → []. */
export function toReviewBoard(value: unknown, runId: string | null, stream: string | null, at: string): ReviewBoard {
  const record = asRecord(value)
  return {
    stream,
    runId,
    at,
    counts: toCounts(record.counts),
    coverage: { ...asRecord(record.coverage) },
    survivors: asArray(record.survivors).map((entry) => toFinding(entry)),
    killed: asArray(record.killed).map((entry) => {
      const killed = asRecord(entry)
      return toFinding(killed.finding, killed.quorum)
    }),
    belowFloor: asArray(record.belowFloor).map((entry) => toFinding(entry)),
    lensesRun: asStringList(record.lensesRun),
    aborted: typeof record.aborted === 'string' && record.aborted.trim() !== '' ? record.aborted : null,
  }
}

/** The last three path segments: `a/b/c/d/e.ts` → `c/d/e.ts`; shorter paths unchanged. */
export function shortPath(file: string): string {
  const segments = file.split('/')
  return segments.length <= 3 ? file : segments.slice(-3).join('/')
}

/** `file:line`, `file:?` when the line is null. */
export function locationOf(finding: ReviewFinding): string {
  return `${finding.file}:${finding.line === null ? '?' : String(finding.line)}`
}

/** `file:line` with the path cut to its last three segments. */
export function shortLocation(finding: ReviewFinding): string {
  return locationOf({ ...finding, file: shortPath(finding.file) })
}

/** A path a prompt may carry, after the cut to three segments: letters, digits and path punctuation; no whitespace, no control characters. */
const SAFE_FILE = /^[\p{L}\p{N}_./@+\-[\]()~,=]{1,200}$/u
const SAFE_LENS = /^[\w+-]{1,40}$/

/** A finding's fields as a prompt may carry them: a known severity, a path-shaped file and lens names, else `?`; never free text. */
const promptFields = (finding: ReviewFinding | undefined): { severity: string; location: string; lenses: string } => {
  if (finding === undefined) return { severity: '?', location: '?', lenses: '?' }
  const severity = stripControl(finding.severity)
  const file = shortPath(stripControl(finding.file))
  const lenses = finding.lenses.map(stripControl).filter(lens => SAFE_LENS.test(lens))
  return {
    severity: (SEVERITIES as readonly string[]).includes(severity) ? severity : '?',
    location: locationOf({ ...finding, file: SAFE_FILE.test(file) ? file : '?' }),
    lenses: lenses.length > 0 ? lenses.join('+') : '?',
  }
}

/** Survivors grouped by severity in SEVERITIES order, then any other severity label, each group with its findings' indexes in the survivors array. */
export function groupBySeverity(findings: readonly ReviewFinding[]): { severity: string; indexes: number[] }[] {
  const groups = new Map<string, number[]>()
  for (const severity of SEVERITIES) groups.set(severity, [])
  for (const [index, finding] of findings.entries()) {
    const group = groups.get(finding.severity)
    if (group) group.push(index)
    else groups.set(finding.severity, [index])
  }
  return [...groups.entries()]
    .filter(([, indexes]) => indexes.length > 0)
    .map(([severity, indexes]) => ({ severity, indexes }))
}

/** The Accept / Kill prompt text (plain, FR-032): names the finding by its 1-based position among the survivors, the total, severity, short file:line and lenses, and the stream; never the summary, why or fix. */
export function findingPrompt(action: ReviewMark, index: number, board: ReviewBoard): string {
  const { severity, location, lenses } = promptFields(board.survivors[index])
  const stream = board.stream === null ? 'the current stream' : `stream ${stripControl(board.stream)}`
  const head = `The user pressed ${action === 'accepted' ? 'Accept' : 'Kill'} on review finding ${index + 1} of ${board.survivors.length} (${severity}, ${location}, lens ${lenses}) in the shipgate HUD for ${stream}`
  return action === 'accepted'
    ? `${head}: fix it in the implement round and record it under the worklog's review round.`
    : `${head}: treat it as rejected, ask the user for the reason, record it under the worklog's Rejected findings, and do not fix it.`
}

/** A tick's key in `ReviewState.ticks`: the stream and the criterion id, so a tick holds for one stream only. */
export function tickKey(stream: string | null, id: string): string {
  return `${stream ?? '?'}:${id}`
}

const CRITERION_LINE = /^\s*-\s*\*\*(SC-\d+)\*\*\s*[—–-]+\s*(.*?)\s*$/

/** The `- **SC-NNN** — text` lines under every `## Success criteria` heading of a PRD. An
 *  indented line that follows a criterion continues its text (PRDs wrap long lines). An id
 *  seen before is skipped (the first wins), so a tick names one criterion. */
export function parseCriteria(prd: string): Criterion[] {
  const criteria: Criterion[] = []
  let inSection = false
  let current: Criterion | null = null
  let skipping = false
  for (const line of prd.split('\n')) {
    const heading = /^(#{1,6})\s+(.*?)\s*$/.exec(line)
    if (heading) {
      if ((heading[1] ?? '').length <= 2) inSection = (heading[1] ?? '') === '##' && /^success criteria$/i.test(heading[2] ?? '')
      current = null
      skipping = false
      continue
    }
    if (!inSection) continue
    const match = CRITERION_LINE.exec(line)
    if (match) {
      const id = match[1] ?? ''
      if (criteria.some(criterion => criterion.id === id)) {
        current = null // a duplicate id, and its continuation lines, are dropped
        skipping = true
        continue
      }
      current = { id, text: match[2] ?? '' }
      skipping = false
      criteria.push(current)
      continue
    }
    if (skipping && /^\s+\S/.test(line)) continue
    if (current !== null && /^\s+\S/.test(line)) {
      current.text = `${current.text} ${line.trim()}`.trim()
      continue
    }
    current = null
    skipping = false
  }
  return criteria
}
