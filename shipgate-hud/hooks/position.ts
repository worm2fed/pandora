// The pure core of the Position: journal.py's decoded `position --json` and the artifacts it
// names in, the stored Position out. journal.py computes every fact the HUD draws (shipgate
// ADR 0009); this module keeps only the markdown parsing for display (an ADR's title and
// status, the worklog's Design sections) and the refresh trigger's glob. No `$` here, so the
// tests run it without a process or a file system.

import type { Adr, Decision, DesignSection, IsoTime, Phase, Plan, Position, ProjectPath, Task, TaskLine } from '../types'
import type { PositionDoc, PositionTask } from './journal'
import { parseCriteria } from './review'

/** A ref the HUD will read: kept beside `projectPath` in journal.ts, where the boundary checks it. */
export { isSafeRef } from './journal'

/** The phases in flow order: the timeline's columns. */
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

/** A phase's short label on the timeline. */
export const PHASE_SHORT: Readonly<Record<Phase, string>> = {
  workspace: 'WS',
  'route-and-map': 'MAP',
  explore: 'EXP',
  clarify: 'CLR',
  design: 'DSN',
  implement: 'IMP',
  review: 'REV',
  capture: 'CAP',
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
export function parseDesignSections(worklog: string): readonly DesignSection[] {
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

/** Everything between the worklog's `# Design` heading and its `# Build Plan` heading, trimmed; null when the worklog has no Design heading. */
export function parseDesignSection(worklog: string): string | null {
  const start = worklog.search(/^#\s*Design\s*$/m)
  if (start < 0) return null
  const rest = worklog.slice(start)
  const end = rest.search(/^#\s*Build Plan\s*$/m)
  const section = end >= 0 ? rest.slice(0, end) : rest
  return section.replace(/^#\s*Design\s*\n?/, '').replace(/\n-{3,}\s*$/, '').trim()
}

/** A frontmatter field's value, unquoted; null when the field is absent or empty. */
const frontmatterField = (front: string, name: string): string | null => {
  const line = new RegExp(`^${name}:[ \\t]*(.*)$`, 'm').exec(front)
  const value = (line?.[1] ?? '').trim().replace(/^"(.*)"$/, '$1').trim()
  return value === '' ? null : value
}

/** An ADR's title and status from its frontmatter: the file name stands in for a missing title; a missing status is null. */
export function parseAdr(path: ProjectPath, text: string): Adr {
  const front = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text)?.[1] ?? ''
  const fileTitle = (path.split('/').pop() ?? path).replace(/\.md$/, '')
  return { path, title: frontmatterField(front, 'title') ?? fileTitle, status: frontmatterField(front, 'status') }
}

/** A markdown artifact the refresh read: its path and its text. */
export interface MarkdownFile {
  readonly path: ProjectPath
  readonly text: string
}

/** What `toPosition` maps: the decoded `position --json` and the artifacts it names, read (null: absent or unreadable). */
export interface PositionInputs {
  readonly doc: PositionDoc
  readonly worklog: MarkdownFile | null
  /** The ADRs `doc.artifacts.adrs` names that could be read, parsed. */
  readonly adrs: readonly Adr[]
  readonly prd: MarkdownFile | null
}

/**
 * The stored Position: the journal's facts as `doc` gives them; the plan (null when `doc` has
 * no worklog or the worklog could not be read) with each task's state from its tick,
 * `task-done` and last verify; the Design sections and criteria parsed from the worklog and
 * the PRD.
 */
export function toPosition(inputs: PositionInputs): Position {
  const { doc, worklog, adrs, prd } = inputs
  return {
    stream: doc.stream,
    version: doc.version,
    lifecycle: doc.lifecycle,
    current: doc.current,
    phases: doc.phases,
    decisions: newestFirst(doc.decisions),
    plan: planOf(doc, worklog),
    lastVerify: doc.lastVerify,
    design: { adrs, sections: worklog === null ? [] : parseDesignSections(worklog.text) },
    publish: doc.publish,
    criteria: prd === null ? [] : parseCriteria(prd.text),
    lastVerdict: doc.verdict,
  }
}

/** The decisions newest first: by seq, the highest first (journal.py prints them oldest first). */
const newestFirst = (decisions: readonly Decision[]): readonly Decision[] => [...decisions].sort((a, b) => b.seq - a.seq)

/**
 * The plan: the worklog the journal names, how it found it, and its tasks; null when the
 * journal names none, could not read it (`tasks` null), or the HUD could not read it.
 */
const planOf = (doc: PositionDoc, worklog: MarkdownFile | null): Plan | null => {
  const ref = doc.artifacts.worklog
  if (ref === null || doc.tasks === null || worklog === null) return null
  return { worklog: ref.path, from: ref.from, tasks: doc.tasks.map(taskOf) }
}

/** A task's state, first match wins: failed (its last verify failed), done (a task-done), debt (ticked, no task-done), open. */
const taskOf = (task: PositionTask): Task => {
  const line: TaskLine = { id: task.id, title: task.title, section: task.section }
  const verify = task.lastVerify
  if (verify !== null && verify.outcome === 'fail') return { ...line, state: 'failed', lastVerifyAt: verify.at }
  return { ...line, state: task.isDone ? 'done' : task.isTicked ? 'debt' : 'open', lastVerifyAt: verify === null ? null : verify.at }
}

/**
 * A sidecar glob as shipgate matches it (Python `fnmatch`): `*` matches any run of characters,
 * `/` included; `?` one character; `[...]` a class (`classBody`); anchored at both ends.
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
        out += `[${classBody(glob.slice(i + 1, close))}]`
        i = close
      }
    } else out += ch.replace(/[.+^${}()|\\]/g, '\\$&')
  }
  return new RegExp(`^${out}$`)
}

/**
 * A glob class's body as a RegExp class's, as fnmatch reads it: a leading `!` negates; a
 * leading `^` is itself (fnmatch escapes it, so `[^a]` matches `^` or `a`); a backslash is
 * itself.
 */
const classBody = (body: string): string => {
  const escaped = body.replace(/\\/g, '\\\\')
  if (escaped.startsWith('!')) return `^${escaped.slice(1)}`
  return escaped.startsWith('^') ? `\\${escaped}` : escaped
}

/**
 * Does a project-relative path sit in a home? shipgate's rule (journal.py's `_matches_glob`):
 * the glob as written, else the glob under one more `*` segment, with one leading `./` (and
 * nothing else) dropped. Only the refresh trigger asks: does a Write need a refresh? It is not
 * a fact the HUD draws, and a false match costs one extra refresh.
 */
export function matchesHome(path: string, glob: string): boolean {
  const normalized = path.replace(/\\/g, '/')
  if (globToRegExp(glob).test(normalized)) return true
  return globToRegExp(`*/${glob.startsWith('./') ? glob.slice(2) : glob}`).test(normalized)
}

/** Can a decision be vetoed from the pane? Only one the orchestrator took on its own, in executive mode. */
export function isVetoable(decision: Decision): boolean {
  return decision.raisedBy === 'orchestrator' && decision.mode === 'executive'
}

/** `HH:MM` of an ISO timestamp, in the local zone; the raw text when it does not parse. */
export function clock(iso: IsoTime): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}
