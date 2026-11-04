// The pure core of the Position: journal.py's decoded `position --json` and the artifacts it
// names in, the stored Position out. journal.py computes every fact the HUD draws (shipgate
// ADR 0009); this module keeps only the markdown parsing for display (an ADR's title and
// status, the worklog's Design sections and its review section, HUD ADR 0009) and the refresh
// trigger's glob. No `$` here, so the tests run it without a process or a file system.

import type { Adr, Decision, DesignSection, IsoTime, Phase, Plan, Position, ProjectPath, ReviewNote, Task, TaskLine } from '../types'
import type { PositionDoc, PositionTask } from './journal'
import { stripControl } from './json'
import { parseCriteria, parseLocation } from './review'

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

const HEADING = /^(#{1,6})\s+(.*?)\s*$/
/** A fence opener: three or more backticks (no backtick after them, as CommonMark reads it) or three or more tildes. */
const FENCE_OPEN = /^\s*(`{3,}(?!.*`)|~{3,})/
/** A fence closer: a run of one marker character and nothing but whitespace after it. */
const FENCE_CLOSE = /^\s*(`{3,}|~{3,})\s*$/
const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/
const CONTINUATION = /^\s+\S/

/** Does a heading's text open a review section: `Review round …` or `Rejected findings`, any case? */
const isReviewHeading = (text: string): boolean => /^review round\b/i.test(text) || /^rejected findings$/i.test(text)

/**
 * Where the review-notes fold stands: the items read so far (raw text, in worklog order),
 * whether the last one takes continuation lines, the level of the open review section (null:
 * outside one), and the marker of the open fenced block (null: none).
 */
interface NotesFold {
  readonly items: readonly string[]
  readonly isOpen: boolean
  readonly section: number | null
  readonly fence: string | null
}

/**
 * A heading folded in. A review heading opens the section at its level; inside an open
 * section it keeps the outer level, so a later sibling heading stays inside. Another heading
 * at the same or a higher level closes the section; a deeper one stays inside. Any heading
 * ends the open item.
 */
const foldHeading = (fold: NotesFold, level: number, text: string): NotesFold => {
  if (isReviewHeading(text)) return { ...fold, isOpen: false, section: fold.section === null ? level : Math.min(fold.section, level) }
  const isClosing = fold.section !== null && level <= fold.section
  return { ...fold, isOpen: false, section: isClosing ? null : fold.section }
}

/** Does `line` close the fence `opener` opened: the same marker character, a run at least as long, nothing after it? */
const closesFence = (opener: string, line: string): boolean => {
  const run = FENCE_CLOSE.exec(line)?.[1] ?? ''
  return run !== '' && run[0] === opener[0] && run.length >= opener.length
}

/** One worklog line folded into the review items. Inside a fence, only its closer counts. */
const foldNoteLine = (fold: NotesFold, line: string): NotesFold => {
  if (fold.fence !== null) return closesFence(fold.fence, line) ? { ...fold, fence: null } : fold
  const opener = FENCE_OPEN.exec(line)?.[1]
  if (opener !== undefined) return { ...fold, isOpen: false, fence: opener }
  const heading = HEADING.exec(line)
  if (heading !== null) return foldHeading(fold, (heading[1] ?? '').length, heading[2] ?? '')
  if (fold.section === null) return fold
  const item = LIST_ITEM.exec(line)
  if (item !== null) return { ...fold, items: [...fold.items, item[1] ?? ''], isOpen: true }
  const last = fold.items[fold.items.length - 1]
  if (fold.isOpen && last !== undefined && CONTINUATION.test(line)) return { ...fold, items: [...fold.items.slice(0, -1), `${last} ${line.trim()}`] }
  return { ...fold, isOpen: false }
}

/** The first sentence of `text`: up to and including the first `.`, `!` or `?` outside backticks that is followed by whitespace or the end; the whole text when none is. */
const firstSentence = (text: string): string => {
  const chars = [...text]
  const end = chars.reduce<{ readonly inCode: boolean; readonly end: number | null }>(
    (scan, ch, i) => {
      if (scan.end !== null) return scan
      if (ch === '`') return { ...scan, inCode: !scan.inCode }
      const isStop = !scan.inCode && (ch === '.' || ch === '!' || ch === '?') && (i + 1 === chars.length || /\s/.test(chars[i + 1] ?? ''))
      return isStop ? { ...scan, end: i + 1 } : scan
    },
    { inCode: false, end: null },
  ).end
  return chars.slice(0, end ?? chars.length).join('')
}

/**
 * One review item as a note: the whole text, its control characters out (`stripControl`) and
 * then its whitespace collapsed; the first backtick span that reads as a location
 * (`parseLocation`); and the first sentence of what follows that span, a leading
 * parenthetical and leading separators (`—`, `–`, `-`, `:`, `,`, `;`, `.`) dropped, backticks
 * out (the whole text stands in when there is no location). A sentence with no letter or
 * digit is empty, so no note line is drawn for it.
 */
const noteOf = (raw: string): ReviewNote => {
  const body = stripControl(raw).replace(/\s+/g, ' ').trim()
  const span = [...body.matchAll(/`([^`]*)`/g)]
    .map(match => ({ match, location: parseLocation(match[1] ?? '') }))
    .find(found => found.location !== null)
  const rest = span === undefined ? body : body.slice((span.match.index ?? 0) + span.match[0].length).replace(/^\s*\([^)]*\)/, '').replace(/^[\s—–:,;.-]+/, '')
  const sentence = firstSentence(rest).replace(/`/g, '').replace(/\s+/g, ' ').trim()
  return { location: span?.location ?? null, sentence: /[\p{L}\p{N}]/u.test(sentence) ? sentence : '', body }
}

/**
 * The worklog's review section as notes, in worklog order (HUD ADR 0009), for display only:
 * every list item under a heading whose text starts with `Review round` or is `Rejected
 * findings` (any level, any case), up to the next heading at the same or a higher level than
 * the section's that is no review heading. A deeper heading, and a review heading inside the
 * section, stay inside. Fenced code is inert: a fence closes only on its own marker character,
 * in a run at least as long as the opener. An indented line that is no new item continues the
 * item above it; a blank or an unindented line ends it.
 */
export function parseReviewNotes(worklog: string): readonly ReviewNote[] {
  return worklog.split('\n').reduce<NotesFold>(foldNoteLine, { items: [], isOpen: false, section: null, fence: null }).items.map(noteOf)
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
 * The stored Position: the journal's facts as `doc` gives them (its trace and folded
 * dispositions included); the plan (null when `doc` has
 * no worklog or the worklog could not be read) with each task's state from its tick,
 * `task-done` and last verify; the Design sections, the review notes and the criteria parsed
 * from the worklog and the PRD.
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
    dispositions: doc.dispositions,
    trace: doc.trace,
    reviewNotes: worklog === null ? [] : parseReviewNotes(worklog.text),
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
