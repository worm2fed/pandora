// The hooks and the side effects: locating journal.py, running it, reading the artifacts.
// Position parsing lives in position.ts and drawing in views.tsx; both are pure. Every
// function here that receives `$` lives in this file, because `claude plugin validate`
// follows `$` into functions of the same file only (declarations or consts), never across
// an import.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Adr, Decision, Position, Tab } from '../types'
import { artifactRefs, matchesHome, parseAdr, streamSlug, toPosition } from './position'
import { PANE_ID, bandOf, paneOf } from './views'
import type { Actions, Ui } from './views'

export const SIDECAR = '.claude/shipgate.json'

/** shipgate's own defaults (journal.py DEFAULT_ARTIFACT_HOMES); a sidecar overrides them key by key. */
const DEFAULT_ARTIFACT_HOMES: Record<string, string> = {
  prd: 'docs/prd/*.md',
  adr: 'docs/adr/*.md',
  worklog: 'docs/prd/*.worklog.md',
}

type Engine = EngineInterface

/** What the sidecar tells the HUD: where worklogs live, and which paths count as artifacts. */
type Homes = { worklogGlob: string; artifactGlobs: string[] }

const homesOf = (merged: Record<string, string>): Homes => ({
  worklogGlob: merged.worklog ?? DEFAULT_ARTIFACT_HOMES.worklog ?? 'docs/prd/*.worklog.md',
  artifactGlobs: Object.values(merged),
})

const DEFAULT_HOMES: Homes = homesOf(DEFAULT_ARTIFACT_HOMES)

const exists = async ($: Engine, path: string): Promise<boolean> => {
  try {
    return await $.fs.exists(path)
  } catch {
    return false
  }
}

const readText = async ($: Engine, path: string): Promise<string | null> => {
  try {
    const text = await $.fs.read(path)
    return typeof text === 'string' ? text : null
  } catch {
    return null
  }
}

/** Newest-version-first: numeric versions by segment (`0.14.1` before `0.9.0`), then every other name. */
const byVersionDesc = (a: string, b: string): number => {
  const isVersion = (name: string) => /^\d+(\.\d+)*$/.test(name)
  const av = isVersion(a)
  const bv = isVersion(b)
  if (av !== bv) return av ? -1 : 1
  return b.localeCompare(a, undefined, { numeric: true })
}

/** The plugin's folder and, when the folder is a symbolic link (a dev-mods link, `--plugin-dir` on a link), where it lands. */
async function pluginRoots($: Engine): Promise<string[]> {
  const root = $.plugin.root
  try {
    const stat = await $.fs.stat(root, { resolve: true })
    if (stat.realPath && stat.realPath !== root) return [root, stat.realPath]
  } catch {
    // unresolvable: the folder as named
  }
  return [root]
}

/** `<dir>/<newest version>/scripts/journal.py` under a plugin-cache `shipgate` folder, or null. */
async function newestJournalUnder($: Engine, shipgateDir: string): Promise<string | null> {
  try {
    const versions = (await $.fs.list(shipgateDir)).filter(e => e.kind === 'dir').map(e => e.name)
    for (const version of versions.sort(byVersionDesc)) {
      const candidate = `${shipgateDir}/${version}/scripts/journal.py`
      if (await exists($, candidate)) return candidate
    }
  } catch {
    // no such folder
  }
  return null
}

/** The Claude config directories whose plugin cache may hold an installed shipgate. */
async function configDirs($: Engine): Promise<string[]> {
  const dirs: string[] = []
  const configured = await $.env.get('CLAUDE_CONFIG_DIR')
  if (configured) dirs.push(configured.replace(/\/+$/, ''))
  const home = await $.env.get('HOME')
  if (home) dirs.push(`${home.replace(/\/+$/, '')}/.claude`)
  return [...new Set(dirs)]
}

/**
 * Where `journal.py` is, in order: the `journalScript` option; beside this plugin in a
 * marketplace checkout (`../shipgate/scripts/journal.py`, the plugin folder resolved through a
 * link); beside it in the plugin cache (`cache/<market>/<plugin>/<ver>/`); the plugin cache of the
 * Claude config directory (`CLAUDE_CONFIG_DIR`, then `~/.claude`), any marketplace. Never a path
 * taken from the project.
 */
export async function locateJournal($: Engine, journalScript: string): Promise<string | null> {
  if (journalScript && (await exists($, journalScript))) return journalScript
  for (const root of await pluginRoots($)) {
    const checkout = `${root}/../shipgate/scripts/journal.py`
    if (await exists($, checkout)) return checkout
    const cached = await newestJournalUnder($, `${root}/../../shipgate`)
    if (cached) return cached
  }
  for (const dir of await configDirs($)) {
    const cache = `${dir}/plugins/cache`
    try {
      for (const market of (await $.fs.list(cache)).filter(e => e.kind === 'dir')) {
        const found = await newestJournalUnder($, `${cache}/${market.name}/shipgate`)
        if (found) return found
      }
    } catch {
      // no plugin cache there
    }
  }
  return null
}

/**
 * The session's project root, no trailing slash: where the session started (or `/cd` took it).
 * Not `$.session.cwd()`, which follows the shell's `cd` — a turn that steps into a nested repo
 * must not move the HUD's journal, sidecar or branch along with it. The same anchor as
 * shipgate's hooks, which read the session's directory from their payload.
 */
const sessionRoot = async ($: Engine): Promise<string> => {
  let dir: string
  try {
    dir = await $.session.root()
  } catch {
    dir = await $.session.cwd()
  }
  return dir.replace(/\/+$/, '') || '/'
}

/** Where a relative path a tool was given resolves: the shell's directory, which `cd` moves. */
const shellDir = async ($: Engine): Promise<string> => (await $.session.cwd()).replace(/\/+$/, '') || '/'

/**
 * The directory the sidecar marks as the project: the session's own, or the nearest ancestor
 * holding one — a session opened inside a nested repo of an umbrella finds the umbrella's
 * journal this way, as shipgate's hooks do. Null when no ancestor has a sidecar.
 */
async function locateProject($: Engine): Promise<string | null> {
  let dir = await sessionRoot($)
  for (;;) {
    if (await exists($, `${dir}/${SIDECAR}`)) return dir
    const cut = dir.lastIndexOf('/')
    if (cut <= 0) return (await exists($, `/${SIDECAR}`)) ? '/' : null
    dir = dir.slice(0, cut)
  }
}

/** `root` as the prefix an absolute path under it starts with (`/` is its own prefix). */
const prefixOf = (root: string): string => (root === '/' ? '/' : `${root}/`)

/** `a/./b/../c` as `a/c`: segments resolved, nothing above the start. */
const normalizePath = (path: string): string => {
  const out: string[] = []
  for (const segment of path.split('/')) {
    if (segment === '' || segment === '.') continue
    if (segment === '..') {
      if (out.length === 0) return '..'
      out.pop()
    } else out.push(segment)
  }
  return (path.startsWith('/') ? '/' : '') + out.join('/')
}

/** A project-relative path made absolute under the located project root; unchanged (session-relative) without one. */
const inProject = (path: string): string => (path.startsWith('/') || projectRoot === null ? path : `${prefixOf(projectRoot)}${path}`)

/** shipgate's defaults overlaid key by key with the sidecar's `artifact_homes`, as journal.py merges them. */
async function readHomes($: Engine): Promise<Homes> {
  const merged: Record<string, string> = { ...DEFAULT_ARTIFACT_HOMES }
  const text = await readText($, inProject(SIDECAR))
  if (text !== null) {
    try {
      const homes = (JSON.parse(text) as { artifact_homes?: unknown }).artifact_homes
      if (homes && typeof homes === 'object' && !Array.isArray(homes)) {
        for (const [key, value] of Object.entries(homes as Record<string, unknown>)) {
          if (typeof value === 'string') merged[key] = value
        }
      }
    } catch {
      // a sidecar that does not parse keeps the defaults
    }
  }
  return homesOf(merged)
}

/** A written path relative to the project root; null when it lies outside it. */
async function projectRelative($: Engine, path: string): Promise<string | null> {
  const root = projectRoot ?? (await sessionRoot($))
  const absolute = normalizePath(path.startsWith('/') ? path : `${prefixOf(await shellDir($))}${path}`)
  const prefix = prefixOf(root)
  return absolute.startsWith(prefix) ? absolute.slice(prefix.length) : null
}

/** journal.py's exit code for a usage error — an unknown flag among them (EXIT_USAGE). */
const EXIT_USAGE = 2

/** A journal.py run that exited non-zero, with its exit code. */
class RunFailed extends Error {
  constructor(
    message: string,
    readonly exitCode: number | null,
  ) {
    super(message)
  }
}

/** journal.py runs in the project root: there it finds the sidecar and the database by itself. */
const runJson = async ($: Engine, argv: readonly string[]): Promise<unknown> => {
  const ran = await $.process.run(argv, { timeoutMs: 10_000, ...(projectRoot ? { cwd: projectRoot } : {}) })
  if (ran.exitCode !== 0) throw new RunFailed(`${argv.slice(-2).join(' ')} failed: ${(ran.stderr || ran.stdout).trim().slice(0, 160)}`, ran.exitCode)
  if (ran.isStdoutTruncated) throw new Error(`${argv.slice(-2).join(' ')}: output over 4 MiB, not parsed`)
  return JSON.parse(ran.stdout) as unknown
}

/** The branch checked out in `dir`, relative to the session root (the root itself when absent); null when detached or not a repo. */
const branchIn = async ($: Engine, dir?: string): Promise<string | null> => {
  const argv = dir ? ['git', '-C', dir, 'rev-parse', '--abbrev-ref', 'HEAD'] : ['git', 'rev-parse', '--abbrev-ref', 'HEAD']
  try {
    const ran = await $.process.run(argv, { timeoutMs: 5_000, cwd: await sessionRoot($) })
    const name = ran.stdout.trim()
    return ran.exitCode === 0 && name && name !== 'HEAD' ? name : null
  } catch {
    return null
  }
}

/** Where setup looks for an umbrella's nested repos: `<dir>/.git`, `source/<dir>/.git`, `packages/<dir>/.git`. */
const NESTED_REPO_PARENTS = ['', 'source', 'packages']
/** Where shipgate's workspace skill puts a git worktree: `.worktrees/<slug>`, beside the repos or inside one. */
const WORKTREES_DIR = '.worktrees'

/** The most nested repos and worktrees one refresh probes (each costs a git run); the hook keeps the same cap. */
const NESTED_REPO_LIMIT = 64

/** The child directories of `base` under the session root (the root itself when empty), as root-relative paths, sorted; dot-names, node_modules and links left out. */
async function childDirs($: Engine, base: string): Promise<string[]> {
  try {
    const root = await sessionRoot($)
    const entries = await $.fs.list(base ? `${prefixOf(root)}${base}` : root)
    return entries
      .filter(e => e.kind === 'dir' && !e.isLink && !e.name.startsWith('.') && e.name !== 'node_modules')
      .map(e => (base ? `${base}/${e.name}` : e.name))
      .sort()
  } catch {
    return []
  }
}

/**
 * The nested repos of an umbrella checkout, relative to the session root. An umbrella
 * is a plain folder or a repo of its own holding the real repos one level down; its own
 * branch (if any) carries no stream, the nested repos' branches do. A worktree sits in
 * `.worktrees/` beside the repos or inside one, so those are looked into as well: a repo,
 * then its own worktrees, then the parent's — each directory once, at most NESTED_REPO_LIMIT
 * in all, the scan stopping there too. The same order and cap as shipgate's SessionStart hook.
 */
async function nestedRepos($: Engine): Promise<string[]> {
  const found: string[] = []
  const prefix = prefixOf(await sessionRoot($))
  // root-relative paths, checked absolute: a relative one would resolve from the shell's directory
  const isRepo = (dir: string) => exists($, `${prefix}${dir}/.git`)
  const take = async (dir: string): Promise<boolean> => {
    if (found.length >= NESTED_REPO_LIMIT) return false
    if (!found.includes(dir) && (await isRepo(dir))) found.push(dir)
    return true
  }
  for (const parent of NESTED_REPO_PARENTS) {
    for (const repo of await childDirs($, parent)) {
      if (!(await isRepo(repo))) continue
      if (!(await take(repo))) return found
      for (const worktree of await childDirs($, `${repo}/${WORKTREES_DIR}`)) {
        if (!(await take(worktree))) return found
      }
    }
    for (const worktree of await childDirs($, parent ? `${parent}/${WORKTREES_DIR}` : WORKTREES_DIR)) {
      if (!(await take(worktree))) return found
    }
  }
  return found
}

type Feature = { feature?: unknown; stream?: unknown; branch_match?: unknown; session_match?: unknown }

/** The stream status marked with `flag`, and nothing else: an unmarked stream is not this position. */
const pickFeature = (status: unknown, flag: 'session_match' | 'branch_match'): Feature | null => {
  const features = (status as { features?: unknown })?.features
  if (!Array.isArray(features)) return null
  return features.find((f: Feature) => f?.[flag] === true) ?? null
}

/** This session's id, the label journal.py gives the events it appends; null when the engine cannot say. */
const sessionIdOf = async ($: Engine): Promise<string | null> => {
  try {
    const id = (await $.session.id()).trim()
    return id || null
  } catch {
    return null
  }
}

/**
 * The directories a worklog glob names, for the fallback scan: a literal directory, or `*` as its
 * first segment standing for each child directory. Deeper wildcards are not walked (the scan is a
 * fallback; the primary path is the worklog the journal events name).
 */
async function worklogDirs($: Engine, glob: string): Promise<{ dir: string; file: string }[]> {
  const cut = glob.lastIndexOf('/')
  const dirGlob = cut >= 0 ? glob.slice(0, cut) : '.'
  const file = glob.slice(cut + 1)
  if (!dirGlob.startsWith('*/')) return [{ dir: dirGlob, file }]
  const rest = dirGlob.slice(2)
  try {
    const top = await $.fs.list(projectRoot ?? undefined)
    return top.filter(e => e.kind === 'dir' && !e.name.startsWith('.')).map(e => ({ dir: `${e.name}/${rest}`, file }))
  } catch {
    return []
  }
}

/**
 * The newest worklog in the configured worklog home named for the stream's slug — `<slug>.worklog.md`,
 * or a name that starts with `<slug>-` or `<slug>.` — else null. A substring match would let a short
 * slug claim another feature's worklog.
 */
export async function worklogForStream($: Engine, stream: string, homes: Homes): Promise<string | null> {
  const slug = streamSlug(stream)
  if (!slug) return null
  const named = (name: string) => name === `${slug}.worklog.md` || name.startsWith(`${slug}-`) || name.startsWith(`${slug}.`)
  let best: { path: string; mtimeMs: number } | null = null
  for (const { dir, file } of await worklogDirs($, homes.worklogGlob)) {
    try {
      for (const entry of await $.fs.list(inProject(dir))) {
        if (entry.kind !== 'file' || !matchesHome(entry.name, file) || !named(entry.name)) continue
        if (!best || entry.mtimeMs > best.mtimeMs) best = { path: `${dir}/${entry.name}`, mtimeMs: entry.mtimeMs }
      }
    } catch {
      // no such home
    }
  }
  return best?.path ?? null
}

export type Refreshed = { position: Position | null; error: string | null }

const lastEventAt = (feature: Feature): string => {
  const last = (feature as { last_event?: { ts?: unknown } }).last_event
  return typeof last?.ts === 'string' ? last.ts : ''
}

/**
 * The stream this session is driving, else the stream of the checked-out branch. The session
 * comes first: the live stream it last wrote to itself (`status --session`, journal.py's call),
 * which may have no branch at all (an epic's planning stream) and differs per session when
 * several run on one project — each HUD asks with its own id. A session that has written to no
 * live stream gets the checkout's: the session directory's branch first; when it has none or no
 * stream carries it, the branch of each nested repo (an umbrella checkout: the real repos one
 * level down), each distinct branch probed once. Several nested repos may sit on branches with
 * streams of their own (a dormant one beside the live one), so among the matches the most
 * recently active stream wins, not the first directory. The session and the own branch share
 * one status call.
 */
async function streamOfCheckout($: Engine, script: string): Promise<Feature | null> {
  const status = (branch: string | null, session: string | null) =>
    runJson($, ['python3', script, 'status', '--json', ...(session ? [`--session=${session}`] : []), ...(branch ? [`--branch=${branch}`] : [])])
  const probe = async (branch: string) => pickFeature(await status(branch, null), 'branch_match')
  const own = await branchIn($)
  const session = await sessionIdOf($)
  let first: unknown = null
  if (session !== null) {
    try {
      first = await status(own, session)
    } catch (error) {
      // a journal.py older than --session refuses the flag as a usage error: ask by branch alone.
      // Any other failure (no database, a broken journal) is the HUD's error to show.
      if (!(error instanceof RunFailed && error.exitCode === EXIT_USAGE)) throw error
      first = null
    }
  }
  if (first === null && own !== null) first = await status(own, null)
  const found = pickFeature(first, 'session_match') ?? pickFeature(first, 'branch_match')
  if (found) return found
  const tried = new Set(own === null ? [] : [own])
  let best: Feature | null = null
  for (const dir of await nestedRepos($)) {
    const branch = await branchIn($, dir)
    if (branch === null || tried.has(branch)) continue
    tried.add(branch)
    let feature: Feature | null
    try {
      feature = await probe(branch)
    } catch {
      continue // one nested repo's failed probe must not discard another's match
    }
    if (feature && (best === null || lastEventAt(feature) > lastEventAt(best))) best = feature
  }
  return best
}

/** One refresh: git branch, status, the stream's log, then the artifacts those events point at. */
export async function refreshPosition($: Engine, script: string, homes: Homes): Promise<Refreshed> {
  try {
    const feature = await streamOfCheckout($, script)
    const stream = typeof feature?.stream === 'string' ? feature.stream : typeof feature?.feature === 'string' ? feature.feature : null
    if (!feature || stream === null) return { position: null, error: null }
    const log = (await runJson($, ['python3', script, 'log', '--stream', stream, '--json'])) as { events?: unknown[] }
    const events = Array.isArray(log?.events) ? log.events : []
    const refs = artifactRefs(events)
    const worklogPath = refs.worklog ?? (await worklogForStream($, stream, homes))
    const worklogText = worklogPath ? await readText($, inProject(worklogPath)) : null
    const adrs: Adr[] = []
    for (const path of refs.adrs) {
      const text = await readText($, inProject(path))
      if (text !== null) adrs.push(parseAdr(path, text))
    }
    const position = toPosition({
      feature,
      events,
      worklog: worklogPath && worklogText !== null ? { path: worklogPath, text: worklogText } : null,
      adrs,
    })
    return { position, error: null }
  } catch (error) {
    return { position: null, error: `shipgate-hud: ${error instanceof Error ? error.message : String(error)}` }
  }
}

const position = atom({ plugin: 'shipgate-hud', key: 'position' } as const, null as Position | null)
const tab = atom({ plugin: 'shipgate-hud', key: 'tab' } as const, null as Tab | null)
const designOpen = atom({ plugin: 'shipgate-hud', key: 'designOpen' } as const, null as string | null)
const lastError = atom({ plugin: 'shipgate-hud', key: 'lastError' } as const, null as string | null)
const isJournaled = atom({ plugin: 'shipgate-hud', key: 'isJournaled' } as const, false)

const JOURNAL_APPEND = /journal\.py\b[\s\S]*\bappend\b/

// Module state: lost on a reload, which is fine — session.start runs again and refills it.
let journalScript = ''
let script: string | null = null
let homes: Homes | null = null
let projectRoot: string | null = null
let inFlight: Promise<void> | null = null
let isPending = false
let hasSurface = false

async function detect($: EngineInterface): Promise<boolean> {
  projectRoot = await locateProject($)
  const present = projectRoot !== null
  await update($, isJournaled, () => present)
  if (!present) homes = null
  return present
}

async function refreshOnce($: EngineInterface): Promise<void> {
  // Module state is empty after a plugin reload while $.state (the position, the last error)
  // survives it: locate the project again rather than show what an older module left behind.
  if (projectRoot === null && !(await detect($))) {
    await update($, position, () => null)
    await update($, lastError, () => null)
    return
  }
  if (script === null) script = await locateJournal($, journalScript)
  if (script === null) {
    await update($, lastError, () => 'shipgate-hud: cannot find shipgate/scripts/journal.py — set the journalScript option.')
    await update($, position, () => null)
    return
  }
  homes = await readHomes($)
  const refreshed = await refreshPosition($, script, homes)
  await update($, position, () => refreshed.position)
  await update($, lastError, () => refreshed.error)
}

/**
 * Coalescing refresh: a request during a run marks one trailing run, every caller awaits the run
 * that covers it, and a failure lands in `lastError` instead of rejecting a caller.
 */
async function refresh($: EngineInterface): Promise<void> {
  if (inFlight) {
    isPending = true
    await inFlight
    return
  }
  inFlight = (async () => {
    try {
      do {
        isPending = false
        try {
          await refreshOnce($)
        } catch (error) {
          await update($, lastError, () => `shipgate-hud: refresh failed — ${error instanceof Error ? error.message : String(error)}`)
        }
      } while (isPending)
    } finally {
      inFlight = null
    }
  })()
  await inFlight
}

/** Does a written path land in a configured artifact home? shipgate's defaults apply before the first refresh. */
async function isArtifactPath($: EngineInterface, path: string): Promise<boolean> {
  const relative = await projectRelative($, path)
  if (relative === null || relative.startsWith('..')) return false
  return (homes ?? DEFAULT_HOMES).artifactGlobs.some(glob => matchesHome(relative, glob))
}

/** The veto prompt names the decision by stream, gate, position and time; the model reads its text from the journal. */
function vetoText(stream: string, total: number, decision: Decision): string {
  const nth = total - decision.seq
  const when = decision.at ? `, recorded ${decision.at}` : ''
  return (
    `The user pressed Veto in the shipgate HUD on gate decision ${nth} of ${total} in stream ${stream} ` +
    `(gate ${decision.gate}${when}; raised by the orchestrator in executive mode). ` +
    `Read that decision from the journal (journal.py status --json / log), revisit it with the user — the alternatives and what ` +
    `changes — and record a deviation event once you agree.`
  )
}

function actionsOf($: EngineInterface, current: Position | null): Actions {
  return {
    setTab: (next: Tab) => {
      void update($, tab, () => next)
    },
    openDesign: (slug: string) => {
      void update($, designOpen, () => slug)
    },
    veto: (decision: Decision) => {
      void $.prompt.submit({ text: vetoText(current?.stream ?? '?', current?.decisions.length ?? 0, decision) })
    },
    refresh: () => {
      void refresh($)
    },
    openPane: () => {
      void $.ui.open({ id: PANE_ID, title: 'shipgate', focus: true })
    },
  }
}

export const register: Register = (on, options) => {
  journalScript = typeof options.journalScript === 'string' ? options.journalScript : ''

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'hud',
      description: 'Open the shipgate HUD pane: flow position, gate decisions, Build Plan, design',
      immediate: true,
    })
    // A session with no surface (claude -p, the SDK) draws nothing: run nothing either.
    hasSurface = e.surface !== null
    if (hasSurface && (await detect($))) {
      await refresh($)
      void $.ui.open({ id: PANE_ID, title: 'shipgate' })
      $.clock.every(60_000, () => {
        void refresh($)
      })
    }
    return next(e)
  })

  // /clear, /resume and /branch reset $.state and fire no session.start: detect again.
  on('classic.SessionStart', { source: ['clear', 'resume', 'fork'] }, async ($, e, next) => {
    if (hasSurface && (await detect($))) await refresh($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'hud' }, async $ => {
    if (!(await detect($))) {
      return { text: `shipgate-hud: no ${SIDECAR} in this project or any directory above it — run /shipgate:setup to create a flow journal.` }
    }
    await $.ui.open({ id: PANE_ID, title: 'shipgate', focus: true, closeOnEscape: true })
    await refresh($)
    return {}
  })

  // The orchestrator appended to the journal: the position moved. Awaited, so the tool
  // result lands after the pane does; the process time is not counted against the hook.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && JOURNAL_APPEND.test(e.command) && (await read($, isJournaled))) await refresh($)
    return ran
  }).catch(($, e, next) => next(e))

  // An artifact in a configured home was written: the plan or the design may have changed.
  on('tool.call', { tool: ['Write', 'Edit'] }, async ($, e, next) => {
    const ran = await next(e)
    const path = 'file_path' in e && typeof e.file_path === 'string' ? e.file_path : ''
    if (ran.deny === undefined && (await read($, isJournaled)) && (await isArtifactPath($, path))) await refresh($)
    return ran
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, position)
    if (e.props.hasSurvey || current === null || !(await read($, isJournaled))) return next(e)
    const ui = $.ui.resolve(e) as unknown as Ui
    return bandOf(ui, current, actionsOf($, current), e.props.bodyColumns)
  })

  on('ui.render', { component: 'Pane', requestId: PANE_ID }, async ($, e) => {
    const ui = $.ui.resolve(e) as unknown as Ui
    const current = await read($, position)
    const state = {
      tab: await read($, tab),
      designOpen: await read($, designOpen),
      lastError: await read($, lastError),
      columns: e.props.bodyColumns,
    }
    return paneOf(ui, current, state, actionsOf($, current))
  })
}
