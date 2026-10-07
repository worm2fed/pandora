// The pure core: shipgate's shapes (the `status --json` feature record, the `log --json`
// events, a worklog's Build Plan and Design section, an ADR's frontmatter) in, a Position
// out. No `$` here, so the tests run it without a process or a file system.

import type { Adr, Decision, DesignSection, Phase, PhaseMark, Position, Task, TaskVerify, Verify } from '../types'

export const PHASES: readonly Phase[] = [
  'workspace',
  'route-and-map',
  'explore',
  'clarify',
  'design',
  'implement',
  'review',
  'capture',
]

export const PHASE_SHORT: Record<Phase, string> = {
  workspace: 'WS',
  'route-and-map': 'MAP',
  explore: 'EXP',
  clarify: 'CLR',
  design: 'DSN',
  implement: 'IMP',
  review: 'REV',
  capture: 'CAP',
}

type JsonRecord = Record<string, unknown>

const asRecord = (value: unknown): JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as JsonRecord) : {}

const asString = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback)

const asStringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []

const isPhase = (value: unknown): value is Phase => typeof value === 'string' && (PHASES as readonly string[]).includes(value)

/** Every phase before the current one is done, the current is current, the rest to do;
 *  a phase the journal entered at any point is done as well (backward transitions). */
export function phaseMarks(current: string, entered: readonly string[]): Record<Phase, PhaseMark> {
  const index = PHASES.indexOf(current as Phase)
  const marks = {} as Record<Phase, PhaseMark>
  for (const [i, phase] of PHASES.entries()) {
    if (phase === current) marks[phase] = 'current'
    else if ((index >= 0 && i < index) || entered.includes(phase)) marks[phase] = 'done'
    else marks[phase] = 'todo'
  }
  return marks
}

const TASK_LINE = /^\s*-\s*\[( |x|X)\]\s*(T\d+[a-z]?)\s*(?:\[P\]\s*)?[—–-]+\s*(.*?)\s*(?:[—–]\s*file\(s\):.*)?$/

/** The worklog's Build Plan lines, in order, each under its `##` section: `- [ ] T001 — title — file(s): …`. */
export function parseBuildPlan(worklog: string): Task[] {
  const start = worklog.search(/^#\s*Build Plan\s*$/m)
  const body = start >= 0 ? worklog.slice(start) : worklog
  const tasks: Task[] = []
  let section = ''
  for (const line of body.split('\n')) {
    const heading = /^##\s+(.*?)\s*$/.exec(line)
    if (heading) {
      section = heading[1] ?? ''
      continue
    }
    const match = TASK_LINE.exec(line)
    if (!match) continue
    const [, tick, id, rawTitle] = match
    const title = ((rawTitle ?? '').split(/\s+[—–]\s+/)[0] ?? '').replace(/`/g, '').trim()
    tasks.push({
      id: id ?? '',
      title,
      section,
      tickedInWorklog: tick !== ' ',
      doneInJournal: false,
      lastVerify: null,
    })
  }
  return tasks
}

const slugify = (title: string): string =>
  title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

/**
 * Hard-wrapped prose re-joined into one line per paragraph, so the pane wraps it to its own
 * width. Fenced code, tables, headings and list markers keep their lines; a list item's
 * indented continuation lines join the item.
 */
export function reflowMarkdown(markdown: string): string {
  const out: string[] = []
  let inFence = false
  let open = false
  const isBlock = (line: string) => /^(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>|```|~~~|    |\t)/.test(line)
  for (const line of markdown.split('\n')) {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence
      out.push(line)
      open = false
      continue
    }
    if (inFence) {
      out.push(line)
      continue
    }
    if (line.trim() === '') {
      out.push('')
      open = false
      continue
    }
    const continuation = open && !isBlock(line)
    if (continuation) out[out.length - 1] = `${out[out.length - 1]} ${line.trim()}`
    else out.push(line.replace(/\s+$/, ''))
    open = !/^(```|~~~|\||    |\t|#{1,6}\s)/.test(line)
  }
  return out.join('\n').trim()
}

/** The worklog's Design section split at its `##` headings, each body reflowed; the lead-in (if any) first. */
export function parseDesignSections(worklog: string): DesignSection[] {
  const whole = parseDesignSection(worklog)
  if (!whole) return []
  const sections: DesignSection[] = []
  let title = ''
  let buffer: string[] = []
  const flush = () => {
    const markdown = reflowMarkdown(buffer.join('\n'))
    if (markdown || title) sections.push({ slug: slugify(title) || 'lead', title: title || 'Design', markdown })
    buffer = []
  }
  for (const line of whole.split('\n')) {
    const heading = /^##\s+(.*?)\s*$/.exec(line)
    if (heading) {
      if (buffer.some(l => l.trim()) || title) flush()
      title = heading[1] ?? ''
      continue
    }
    buffer.push(line)
  }
  flush()
  return sections
}

/** Everything between the worklog's `# Design` heading and its `# Build Plan` heading. */
export function parseDesignSection(worklog: string): string {
  const start = worklog.search(/^#\s*Design\s*$/m)
  if (start < 0) return ''
  const rest = worklog.slice(start)
  const end = rest.search(/^#\s*Build Plan\s*$/m)
  const section = end >= 0 ? rest.slice(0, end) : rest
  return section.replace(/^#\s*Design\s*\n/, '').replace(/\n-{3,}\s*$/, '').trim()
}

/** An ADR's title and status from its frontmatter; the filename stands in for a missing title. */
export function parseAdr(path: string, text: string): Adr {
  const front = /^---\n([\s\S]*?)\n---/.exec(text)?.[1] ?? ''
  const field = (name: string) => {
    const m = new RegExp(`^${name}:\\s*(.*)$`, 'm').exec(front)
    return m?.[1]?.trim().replace(/^"(.*)"$/, '$1') ?? ''
  }
  const fileTitle = path.split('/').pop()?.replace(/\.md$/, '') ?? path
  return { path, title: field('title') || fileTitle, status: field('status') || 'unknown' }
}

export type PositionInputs = {
  feature: unknown
  events: readonly unknown[]
  worklog: { path: string; text: string } | null
  adrs: readonly Adr[]
}

/** A ref the HUD will read: relative, inside the project, no `..` segment, no drive or scheme. */
export function isSafeRef(path: string): boolean {
  if (!path || path.startsWith('/') || path.startsWith('\\')) return false
  if (/^[A-Za-z]:/.test(path) || /^[a-z]+:\/\//i.test(path)) return false
  return !path.split(/[\\/]/).some(segment => segment === '..')
}

/** The paths the stream's events point at: the worklog and the ADRs the design committed to. */
export function artifactRefs(events: readonly unknown[]): { worklog: string | null; adrs: string[] } {
  let worklog: string | null = null
  const adrs: string[] = []
  for (const raw of events) {
    const event = asRecord(raw)
    const data = asRecord(event.data)
    const candidates = [asString(data.worklog), ...asStringList(data.refs), ...asStringList(data.adrs)]
    for (const ref of candidates) {
      const path = ref.split('#')[0] ?? ''
      if (!path || !isSafeRef(path)) continue
      if (path.endsWith('.worklog.md')) worklog = path
      else if (/\/adr\/.+\.md$/.test(path) && !adrs.includes(path)) adrs.push(path)
    }
  }
  return { worklog, adrs }
}

export function toPosition({ feature, events, worklog, adrs }: PositionInputs): Position {
  const record = asRecord(feature)
  const phase = asString(record.phase, 'workspace')

  const entered: string[] = []
  const verifies = new Map<string, TaskVerify>()
  const doneIds = new Set<string>(asStringList(record.task_ids))
  for (const raw of events) {
    const event = asRecord(raw)
    const data = asRecord(event.data)
    const type = asString(event.type)
    const ts = asString(event.ts)
    if (type === 'phase-entered' && isPhase(data.phase)) entered.push(data.phase)
    if (type === 'verify-run') {
      // The last verify-run that covered a task wins, pass or fail.
      const outcome = asString(data.outcome, '?')
      for (const id of asStringList(data.task_ids)) verifies.set(id, { outcome, at: ts })
    }
    if (type === 'task-done') {
      const id = asString(data.task_id)
      if (id) doneIds.add(id)
    }
  }

  const decisions: Decision[] = (Array.isArray(record.gate_decisions) ? record.gate_decisions : [])
    .map((raw, i) => {
      const d = asRecord(raw)
      return {
        seq: i,
        gate: asString(d.gate, '?'),
        question: asString(d.question),
        decision: asString(d.decision),
        raisedBy: asString(d.raised_by, 'orchestrator'),
        mode: typeof d.mode === 'string' ? d.mode : null,
        at: asString(d.ts),
      }
    })
    .reverse()

  const tasks: Task[] = (worklog ? parseBuildPlan(worklog.text) : []).map(task => ({
    ...task,
    doneInJournal: doneIds.has(task.id),
    lastVerify: verifies.get(task.id) ?? null,
  }))

  const verify = asRecord(record.last_verify)
  const lastVerify: Verify | null =
    record.last_verify && typeof record.last_verify === 'object'
      ? { outcome: asString(verify.outcome, '?'), taskIds: asStringList(verify.task_ids), at: asString(verify.ts) }
      : null

  return {
    stream: asString(record.stream) || asString(record.feature, '?'),
    phase,
    phaseEnteredAt: typeof record.phase_entered_at === 'string' ? record.phase_entered_at : null,
    version: typeof record.version === 'number' ? record.version : 0,
    phases: phaseMarks(phase, entered),
    decisions,
    tasks,
    lastVerify,
    design: { adrs: [...adrs], sections: worklog ? parseDesignSections(worklog.text) : [] },
    worklogPath: worklog?.path ?? null,
  }
}

/** The slug a stream carries after its last `/`: `feat/x-y` → `x-y`; a bare name is its own slug. */
export function streamSlug(stream: string): string {
  const cut = stream.lastIndexOf('/')
  return cut >= 0 ? stream.slice(cut + 1) : stream
}

/**
 * A sidecar glob as shipgate matches it (Python `fnmatch`): `*` matches any run of characters,
 * `/` included; `?` one character; `[...]` a class; anchored at both ends.
 */
export function globToRegExp(glob: string): RegExp {
  let out = ''
  for (let i = 0; i < glob.length; i += 1) {
    const ch = glob[i] ?? ''
    if (ch === '*') out += '.*'
    else if (ch === '?') out += '.'
    else if (ch === '[') {
      const close = glob.indexOf(']', i + 1)
      if (close < 0) out += '\\['
      else {
        out += `[${glob.slice(i + 1, close).replace(/^!/, '^').replace(/\\/g, '\\\\')}]`
        i = close
      }
    } else out += ch.replace(/[.+^${}()|\\]/g, '\\$&')
  }
  return new RegExp(`^${out}$`)
}

/** Does a project-relative path sit in a home? shipgate's rule: the glob as written, else the glob under one more `*` segment. */
export function matchesHome(path: string, glob: string): boolean {
  const normalized = path.replace(/\\/g, '/')
  if (globToRegExp(glob).test(normalized)) return true
  return globToRegExp(`*/${glob.replace(/^\.?\/+/, '')}`).test(normalized)
}

/** Can a decision be vetoed from the pane? Only one the orchestrator took on its own, in executive mode. */
export function isVetoable(decision: Decision): boolean {
  return decision.raisedBy === 'orchestrator' && decision.mode === 'executive'
}

/** `HH:MM` of an ISO timestamp, in the local zone; the raw text when it does not parse. */
export function clock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}
