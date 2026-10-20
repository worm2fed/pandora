// The hooks and the side effects: locating journal.py, running it, reading the artifacts,
// the publish gate's reads. Decoding lives in journal.ts, position mapping in position.ts,
// the gate's decision in publish.ts and drawing in views.tsx; all are pure. Every function
// here that receives `$` lives in this file, because `claude plugin validate` follows `$`
// into functions of the same file only (declarations or consts), never across an import.
// The casts at the engine's boundaries (`$.ui.resolve`) and the try/catch around a rejected
// `$` call (`settle`, `settleSync`) live here and nowhere else; a run's stdout is parsed by
// `parseJson` and decoded, never cast.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, FsEntry, ProcessRunResult, Register, ResolveInput } from 'claude-code'

import type {
  Adr,
  BindingVia,
  BranchName,
  CriterionId,
  Decision,
  HudView,
  OpenRound,
  OutdatedSign,
  Position,
  ReadFailure,
  RefreshFailure,
  ReviewMark,
  ReviewState,
  RoundId,
  RunFailure,
  StreamName,
  Tab,
} from '../types'
import { type Result, absurd, err, ok, parseJson, recordOf, stringOf } from './json'
import {
  type BadShape,
  DEFAULT_HOMES,
  type DecodeFailure,
  type PositionDoc,
  type SidecarHomes,
  type StatusBrief,
  type StatusFeature,
  branchName,
  decodePosition,
  decodeSidecarHomes,
  decodeStatus,
  isoTime,
} from './journal'
import { type MarkdownFile, type PositionInputs, matchesHome, parseAdr, toPosition } from './position'
import {
  FAIL_CLOSED,
  type BoundStream,
  type CommandDir,
  type CommandScan,
  type GateInputs,
  type Holds,
  type PublishCommand,
  type PublishCommands,
  type PublishTarget,
  type TargetBinding,
  denyReason,
  gateVerdict,
  holdReason,
  publishCommandOf,
  scanCommand,
} from './publish'
import {
  EMPTY_REVIEW,
  type ReviewReturn,
  TASK_OUTPUT_LIMIT,
  boardsFor,
  decodeReviewReturn,
  decodeReviewState,
  findingPrompt,
  isReviewLaunch,
  isSafeTaskOutput,
  markSurvivor,
  nextTicks,
  parseTaskNotification,
  pushBoard,
  reviewReturnOfOutput,
  roundId,
  runIdOf,
  toReviewBoard,
} from './review'
import { PANE_ID, bandOf, paneOf } from './views'
import type { Actions, PaneState, Ui } from './views'

export const SIDECAR = '.claude/shipgate.json'

type Engine = EngineInterface

// ---------------------------------------------------------------------------------------
// The effect boundary: a `$` call's rejection and a journal run's failure as values
// ---------------------------------------------------------------------------------------

/** A journal run's value, or why there is none. */
export type Run<A> = Result<RunFailure, A>

/** Why a `$` call rejected: the person cut it, or it could not run. Only a journal run says more (`outcomeOf`). */
type Rejection = Extract<RunFailure, { readonly kind: 'Cut' | 'CannotStart' }>

/** A journal run's sign that journal.py is older than the shipgate this HUD needs. */
type Outdated = Extract<RunFailure, { readonly kind: 'Outdated' }>

/** The cut: the person denied or interrupted the call the hook runs in. */
const CUT_FAILURE: Rejection = { kind: 'Cut' }

/**
 * A `$` call's value, or why it rejected (`classifyRejection`). One of the two places a `try`
 * stands in the HUD's hooks, with `settleSync` (HUD ADR 0006): every other effect helper reads
 * a rejection through this one.
 */
async function settle<A>(call: () => Promise<A>): Promise<Result<Rejection, A>> {
  try {
    return ok(await call())
  } catch (error) {
    return err(classifyRejection(error))
  }
}

/** A synchronous call's value, or why it threw: `settle` for a call that returns no promise. */
function settleSync<A>(call: () => A): Result<Rejection, A> {
  try {
    return ok(call())
  } catch (error) {
    return err(classifyRejection(error))
  }
}

/** A `$` call's value; `fallback` when it rejects for any reason but a cut, which stays a `Cut` failure. */
async function attempt<A>(call: () => Promise<A>, fallback: A): Promise<Result<Rejection, A>> {
  const settled = await settle(call)
  return settled.ok || settled.error.kind === 'Cut' ? settled : ok(fallback)
}

/**
 * Why a `$` call rejected: `Cut` when the engine cut it because the person denied or
 * interrupted the call the hook runs in (an `AbortError`, or the engine's `) aborted` message);
 * `CannotStart` for anything else. Only the engine's own rejection counts as a cut.
 */
function classifyRejection(error: unknown): Extract<RunFailure, { readonly kind: 'Cut' | 'CannotStart' }> {
  if (!(error instanceof Error)) return { kind: 'CannotStart', message: String(error) }
  return error.name === 'AbortError' || /\) aborted$/.test(error.message) ? { kind: 'Cut' } : { kind: 'CannotStart', message: error.message }
}

/** journal.py's exit code for a usage error: an unknown flag or subcommand among them (EXIT_USAGE). */
const EXIT_USAGE = 2

/**
 * The argument an argparse usage error names: `<prog>: error: unrecognized arguments: <args>`
 * or `<prog>: error: argument <name>: invalid choice: '<choice>'`, after argparse's `usage:`
 * line. Null for any other text: python3 also exits 2 for a script file it cannot open (D1).
 */
function unknownArgumentOf(stderr: string): string | null {
  if (!/^usage: /m.test(stderr)) return null
  const unrecognized = /: error: unrecognized arguments: (.+)$/m.exec(stderr)?.[1]
  const choice = /: error: argument [^:\n]+: invalid choice: '([^'\n]*)'/m.exec(stderr)?.[1]
  const argument = unrecognized ?? choice
  return argument === undefined ? null : argument.trim()
}

/**
 * A finished journal.py run as a value: its decoded stdout, or why there is none. An argument
 * argparse refused is `Outdated` (`UnknownArgument`); the decoder says `Outdated`
 * (`MissingMarker`) or `BadShape` for the JSON, passed on as it is.
 */
function outcomeOf<A>(ran: ProcessRunResult, decode: (raw: unknown) => Result<DecodeFailure, A>): Run<A> {
  if (ran.exitCode !== 0) {
    const argument = ran.exitCode === EXIT_USAGE ? unknownArgumentOf(ran.stderr) : null
    return err(argument === null ? { kind: 'Exited', exitCode: ran.exitCode, stderr: ran.stderr } : { kind: 'Outdated', sign: { kind: 'UnknownArgument', argument } })
  }
  if (ran.isStdoutTruncated) return err({ kind: 'Truncated' })
  const parsed = parseJson(ran.stdout)
  if (!parsed.ok) return err({ kind: 'NotJson', message: parsed.error.message })
  return decode(parsed.value)
}

// ---------------------------------------------------------------------------------------
// The file system and the session
// ---------------------------------------------------------------------------------------

/** Does the path exist? Any rejection but a cut reads as no; a cut is a `Cut` failure (D3). */
const existsRun = ($: Engine, path: string): Promise<Result<Rejection, boolean>> => attempt(() => $.fs.exists(path), false)

/** A file's text; null when it cannot be read. */
const readText = async ($: Engine, path: string): Promise<string | null> => {
  const text = await settle(() => $.fs.read(path))
  return text.ok ? text.value : null
}

/** A file's text; null when it cannot be read for any reason but a cut, which is a `Cut` failure. */
const readRun = ($: Engine, path: string): Promise<Result<Rejection, string | null>> => attempt<string | null>(() => $.fs.read(path), null)

/** What a path leads to (a link followed); null when it cannot be stat'ed. */
const statOf = async ($: Engine, path: string): Promise<{ readonly kind: string; readonly size: number } | null> => {
  const stat = await settle(() => $.fs.stat(path))
  return stat.ok ? { kind: stat.value.kind, size: stat.value.size } : null
}

/** A directory's entries; [] when it cannot be listed for any reason but a cut, which is a `Cut` failure. */
const listRun = ($: Engine, path: string): Promise<Result<Rejection, readonly FsEntry[]>> => attempt<readonly FsEntry[]>(() => $.fs.list(path), [])

/**
 * The review return of a task whose notification text carries a cut result: read whole from the
 * task output file the notification names, and decoded. Only an absolute `…/tasks/<name>.output`
 * path (`isSafeTaskOutput`), only a regular file of at most TASK_OUTPUT_LIMIT bytes. Any failure
 * (stat, read, parse, decode) is null: no board, no error.
 */
async function reviewReturnFromOutput($: Engine, path: string | null): Promise<ReviewReturn | null> {
  if (path === null || !isSafeTaskOutput(path)) return null
  const stat = await statOf($, path)
  if (stat === null || stat.kind !== 'file' || stat.size > TASK_OUTPUT_LIMIT) return null
  const text = await readText($, path)
  if (text === null) return null
  const parsed = parseJson(text)
  if (!parsed.ok) return null
  const ret = reviewReturnOfOutput(parsed.value)
  return ret.ok ? ret.value : null
}

/**
 * The session's project root, no trailing slash: where the session started (or `/cd` took it).
 * Not `$.session.cwd()`, which follows the shell's `cd` — a turn that steps into a nested repo
 * must not move the HUD's journal, sidecar or branch along with it. The same anchor as
 * shipgate's hooks, which read the session's directory from their payload.
 */
const sessionRoot = async ($: Engine): Promise<string> => {
  const root = await settle(() => $.session.root())
  const dir = root.ok ? root.value : await $.session.cwd()
  return dir.replace(/\/+$/, '') || '/'
}

/** Where a relative path a tool was given resolves: the shell's directory, which `cd` moves. */
const shellDir = async ($: Engine): Promise<string> => (await $.session.cwd()).replace(/\/+$/, '') || '/'

/** This session's id, the label journal.py gives the events it appends; null when the engine cannot say. */
const sessionIdOf = async ($: Engine): Promise<string | null> => {
  const id = await settle(() => $.session.id())
  return id.ok && id.value.trim() !== '' ? id.value.trim() : null
}

/** `root` as the prefix an absolute path under it starts with (`/` is its own prefix). */
const prefixOf = (root: string): string => (root === '/' ? '/' : `${root}/`)

/**
 * `a/./b/../c` as `a/c`: segments resolved. An absolute path stops at `/`, as POSIX does
 * (`/a/../../x` is `/x`); a relative one that climbs above its start is `..`.
 */
const normalizePath = (path: string): string => {
  const isAbsolute = path.startsWith('/')
  // null: a relative path climbed above its start
  const segments = path.split('/').reduce<readonly string[] | null>((out, segment) => {
    if (out === null || segment === '' || segment === '.') return out
    if (segment !== '..') return [...out, segment]
    if (out.length > 0) return out.slice(0, -1)
    return isAbsolute ? out : null
  }, [])
  return segments === null ? '..' : `${isAbsolute ? '/' : ''}${segments.join('/')}`
}

/** `path` as an absolute path: as given when absolute, else resolved under `base`. */
const absoluteIn = (base: string, path: string): string => (path.startsWith('/') ? path : normalizePath(`${prefixOf(base)}${path}`))

/** A project-relative path made absolute under the located project root; unchanged (session-relative) without one. */
const inProject = (path: string): string => (path.startsWith('/') || projectRoot === null ? path : `${prefixOf(projectRoot)}${path}`)

/**
 * The directory the sidecar marks as the project: `dir`, or the nearest ancestor holding one —
 * a session opened inside a nested repo of an umbrella finds the umbrella's journal this way,
 * as shipgate's hooks do. Null when no ancestor has a sidecar; a cut is a `Cut` failure.
 */
async function sidecarAbove($: Engine, dir: string): Promise<Result<Rejection, string | null>> {
  const isHere = await existsRun($, `${dir === '/' ? '' : dir}/${SIDECAR}`)
  if (!isHere.ok) return isHere
  if (isHere.value) return ok(dir)
  if (dir === '/') return ok(null)
  const cut = dir.lastIndexOf('/')
  return sidecarAbove($, cut <= 0 ? '/' : dir.slice(0, cut))
}

/** The project the session is in: the sidecar at the session root or above it (`sidecarAbove`). */
const locateProject = async ($: Engine): Promise<Result<Rejection, string | null>> => sidecarAbove($, await sessionRoot($))

/** A written path relative to the project root; null when it lies outside it. */
async function projectRelative($: Engine, path: string): Promise<string | null> {
  const root = projectRoot ?? (await sessionRoot($))
  const absolute = normalizePath(path.startsWith('/') ? path : `${prefixOf(await shellDir($))}${path}`)
  const prefix = prefixOf(root)
  return absolute.startsWith(prefix) ? absolute.slice(prefix.length) : null
}

// ---------------------------------------------------------------------------------------
// journal.py: where it is, and one run of it
// ---------------------------------------------------------------------------------------

/** Newest-version-first: numeric versions by segment (`0.14.1` before `0.9.0`), then every other name. */
const byVersionDesc = (a: string, b: string): number => {
  const isVersion = (name: string) => /^\d+(\.\d+)*$/.test(name)
  const av = isVersion(a)
  const bv = isVersion(b)
  if (av !== bv) return av ? -1 : 1
  return b.localeCompare(a, undefined, { numeric: true })
}

/** One place journal.py may be: its path, null when it is not there, or a cut. */
type Search = () => Promise<Run<string | null>>

/** The first search, in order, that finds journal.py; a cut stops the searching as a cut. */
async function firstFound(searches: readonly Search[]): Promise<Run<string | null>> {
  const [search, ...rest] = searches
  if (search === undefined) return ok(null)
  const found = await search()
  return !found.ok || found.value !== null ? found : firstFound(rest)
}

/** The search for one file: its path when it exists. */
const fileAt =
  ($: Engine, path: string): Search =>
  async () => {
    const there = await existsRun($, path)
    return there.ok ? ok(there.value ? path : null) : there
  }

/** The child directories of `dir` by name; [] when it cannot be listed (a cut is a cut). */
async function dirNamesIn($: Engine, dir: string): Promise<Run<readonly string[]>> {
  const listed = await listRun($, dir)
  return listed.ok ? ok(listed.value.filter(entry => entry.kind === 'dir').map(entry => entry.name)) : listed
}

/** The plugin's folder and, when the folder is a symbolic link (a dev-mods link, `--plugin-dir` on a link), where it lands. */
async function pluginRoots($: Engine): Promise<Run<readonly string[]>> {
  const root = $.plugin.root
  const stat = await attempt<{ readonly realPath?: string } | null>(() => $.fs.stat(root, { resolve: true }), null)
  if (!stat.ok) return stat
  const real = stat.value?.realPath
  return ok(real !== undefined && real !== '' && real !== root ? [root, real] : [root])
}

/** `<dir>/<newest version>/scripts/journal.py` under a plugin-cache `shipgate` folder, or null. */
async function newestJournalUnder($: Engine, shipgateDir: string): Promise<Run<string | null>> {
  const versions = await dirNamesIn($, shipgateDir)
  if (!versions.ok) return versions
  return firstFound([...versions.value].sort(byVersionDesc).map(version => fileAt($, `${shipgateDir}/${version}/scripts/journal.py`)))
}

/** The Claude config directories whose plugin cache may hold an installed shipgate: `CLAUDE_CONFIG_DIR`, then `~/.claude`. */
async function configDirs($: Engine): Promise<Run<readonly string[]>> {
  const configured = await attempt<string | undefined>(() => $.env.get('CLAUDE_CONFIG_DIR'), undefined)
  if (!configured.ok) return configured
  const home = await attempt<string | undefined>(() => $.env.get('HOME'), undefined)
  if (!home.ok) return home
  const dirs = [
    ...(configured.value ? [configured.value.replace(/\/+$/, '')] : []),
    ...(home.value ? [`${home.value.replace(/\/+$/, '')}/.claude`] : []),
  ]
  return ok([...new Set(dirs)])
}

/** journal.py in the plugin cache of the Claude config directories, any marketplace. */
async function inConfigCaches($: Engine): Promise<Run<string | null>> {
  const dirs = await configDirs($)
  if (!dirs.ok) return dirs
  return firstFound(
    dirs.value.map(dir => async () => {
      const cache = `${dir}/plugins/cache`
      const markets = await dirNamesIn($, cache)
      return markets.ok ? firstFound(markets.value.map(market => () => newestJournalUnder($, `${cache}/${market}/shipgate`))) : markets
    }),
  )
}

/**
 * Where `journal.py` is, in order: the `journalScript` option; beside this plugin in a
 * marketplace checkout (`../shipgate/scripts/journal.py`, the plugin folder resolved through a
 * link); beside it in the plugin cache (`cache/<market>/<plugin>/<ver>/`); the plugin cache of the
 * Claude config directory (`CLAUDE_CONFIG_DIR`, then `~/.claude`), any marketplace. Never a path
 * taken from the project. A cut while searching is a `Cut` failure, never "not found" (D3).
 */
export async function locateJournal($: Engine, journalScript: string): Promise<Run<string | null>> {
  const option: readonly Search[] = journalScript ? [fileAt($, journalScript)] : []
  const besidePlugin: Search = async () => {
    const roots = await pluginRoots($)
    if (!roots.ok) return roots
    return firstFound(roots.value.flatMap(root => [fileAt($, `${root}/../shipgate/scripts/journal.py`), () => newestJournalUnder($, `${root}/../../shipgate`)]))
  }
  return firstFound([...option, besidePlugin, () => inConfigCaches($)])
}

/**
 * One journal.py run in the project root (`python3 <script> <args>`), its stdout parsed (the
 * declared cast boundary for process stdout) and decoded. Every failure is a value: a rejected
 * `$` call is classified by `classifyRejection`; exit 2 with argparse's text naming an argument
 * is `Outdated`; any other non-zero exit is `Exited`; a truncated stdout is `Truncated`; the
 * decoder's `Outdated` or `BadShape` is passed on.
 */
async function runJournal<A>($: Engine, script: string, args: readonly string[], decode: (raw: unknown) => Result<DecodeFailure, A>): Promise<Run<A>> {
  const ran = await settle(() => $.process.run(['python3', script, ...args], { timeoutMs: 10_000, ...(projectRoot === null ? {} : { cwd: projectRoot }) }))
  return ran.ok ? outcomeOf(ran.value, decode) : ran
}

/**
 * The branch checked out in `dir` (relative to the session root, or absolute; null: the root
 * itself); null when detached or not a repo (git exits non-zero). A run that could not start,
 * or a cut, is a failure.
 */
async function branchIn($: Engine, dir: string | null): Promise<Result<Rejection, BranchName | null>> {
  const argv = dir === null ? ['git', 'rev-parse', '--abbrev-ref', 'HEAD'] : ['git', '-C', dir, 'rev-parse', '--abbrev-ref', 'HEAD']
  const root = await sessionRoot($)
  const ran = await settle(() => $.process.run(argv, { timeoutMs: 5_000, cwd: root }))
  if (!ran.ok) return ran
  return ok(ran.value.exitCode === 0 ? branchName(ran.value.stdout.trim()) : null)
}

/** shipgate's defaults overlaid key by key with the sidecar's `artifact_homes` (`decodeSidecarHomes`); the defaults when the sidecar cannot be read or decoded. */
async function readHomes($: Engine): Promise<SidecarHomes> {
  const text = await readText($, inProject(SIDECAR))
  const parsed = text === null ? null : parseJson(text)
  const decoded = parsed === null || !parsed.ok ? null : decodeSidecarHomes(parsed.value)
  return decoded === null || !decoded.ok ? DEFAULT_HOMES : decoded.value
}

// ---------------------------------------------------------------------------------------
// The binding (HUD ADR 0004) and one refresh
// ---------------------------------------------------------------------------------------

/**
 * Where journal.py is, as far as this module knows: not searched yet (after a plugin reload),
 * found at `path`, or not found. A failed run with a found script searches again: a plugin
 * cache update may have moved it.
 */
export type ScriptLookup = { readonly kind: 'NotSearched' } | { readonly kind: 'Found'; readonly path: string } | { readonly kind: 'NotFound' }

/**
 * The coalescing refresh: idle, or one run in flight. A request during a run sets
 * `hasTrailing`: one more run follows, and every caller awaits the run that covers its request.
 */
export type RefreshSlot = { readonly kind: 'Idle' } | { readonly kind: 'Running'; readonly run: Promise<Refreshed>; readonly hasTrailing: boolean }

/**
 * The stream this session is bound to (HUD ADR 0004), as the status brief's top-level names
 * say; `feature` is the brief's entry for the stream named. `Session`: `sessionMatch`, the
 * live stream it last wrote to. `Branch`: `branchMatch`, the session root's branch names the
 * stream, or the nested repos' branches name exactly one live stream (`branch` is the one
 * that named it). `Unbound`: neither; `nearby` are the live streams the checkout's branches
 * name (`nestedMatches`).
 */
export type Binding =
  | { readonly kind: 'Session'; readonly feature: StatusFeature }
  | { readonly kind: 'Branch'; readonly branch: BranchName; readonly feature: StatusFeature }
  | { readonly kind: 'Unbound'; readonly nearby: readonly StreamName[] }

/**
 * One refresh's outcome. `NoProject`: no sidecar here or above. `NoJournalScript`: journal.py
 * was not found. `Outdated`: a journal run showed journal.py older than the shipgate this HUD
 * needs (`sign`: how); a known state, never a failure. `Cut`: the person cut the call the
 * refresh ran in; nothing is written. `Failed`: a journal run failed, never read as "no
 * stream". `Unbound` / `Bound`: as `Binding`, with the bound stream's position.
 */
export type Refreshed =
  | { readonly kind: 'NoProject' }
  | { readonly kind: 'NoJournalScript' }
  | { readonly kind: 'Outdated'; readonly sign: OutdatedSign }
  | { readonly kind: 'Cut' }
  | { readonly kind: 'Failed'; readonly failure: RefreshFailure }
  | { readonly kind: 'Unbound'; readonly nearby: readonly StreamName[] }
  | { readonly kind: 'Bound'; readonly via: BindingVia; readonly position: Position }

const NO_PROJECT: Refreshed = { kind: 'NoProject' }
const NO_JOURNAL_SCRIPT: Refreshed = { kind: 'NoJournalScript' }
const CUT: Refreshed = { kind: 'Cut' }

/** A failed run as a refresh's outcome: a cut writes nothing; an outdated journal.py is `Outdated`; any other failure is shown. */
function refreshedOf(failure: RunFailure): Refreshed {
  switch (failure.kind) {
    case 'Cut':
      return CUT
    case 'Outdated':
      return { kind: 'Outdated', sign: failure.sign }
    case 'CannotStart':
    case 'Exited':
    case 'Truncated':
    case 'NotJson':
    case 'BadShape':
      return { kind: 'Failed', failure }
    default:
      return absurd(failure)
  }
}

/** A brief whose top-level name points at no listed stream: the decoder refuses one, so this is a shape error, never "no stream". */
const unlisted = (stream: StreamName): BadShape => ({ kind: 'BadShape', error: { path: '$.features', expected: `the stream ${stream} the brief names` } })

/** The brief's entry for `stream`. */
const featureNamed = (brief: StatusBrief, stream: StreamName): Result<BadShape, StatusFeature> => {
  const feature = brief.features.find(listed => listed.stream === stream)
  return feature === undefined ? err(unlisted(stream)) : ok(feature)
}

/** `status --json` for the session and its root's branch: `--session` and `--branch` when known. */
const statusArgs = (session: string | null, branch: BranchName | null): readonly string[] => [
  'status',
  '--json',
  ...(session === null ? [] : [`--session=${session}`]),
  ...(branch === null ? [] : [`--branch=${branch}`]),
]

/** The binding the first brief gives: the session's own stream, else the root branch's; null when it names neither. */
function directBinding(brief: StatusBrief, own: BranchName | null): Run<Binding> | null {
  if (brief.sessionMatch !== null) {
    const feature = featureNamed(brief, brief.sessionMatch)
    return feature.ok ? ok({ kind: 'Session', feature: feature.value }) : feature
  }
  if (brief.branchMatch !== null && own !== null) {
    const feature = featureNamed(brief, brief.branchMatch)
    return feature.ok ? ok({ kind: 'Branch', branch: own, feature: feature.value }) : feature
  }
  return null
}

/**
 * The nested branch that names `stream`: the one spelled as the stream, else one ending in the
 * stream's last segment, else the first passed. Only drawn as the binding's evidence; which
 * stream binds is journal.py's word (`branchMatch`).
 */
const namingBranch = (branches: readonly [BranchName, ...BranchName[]], stream: StreamName): BranchName => {
  const name: string = stream
  const slug = name.split('/').pop() ?? name
  return branches.find(branch => branch === name) ?? branches.find(branch => branch.split('/').pop() === slug) ?? branches[0]
}

/** The binding the nested brief gives: the one live stream the nested branches name (journal.py's 1B rule), else Unbound with the live ones they name. */
function nestedBinding(brief: StatusBrief, branches: readonly [BranchName, ...BranchName[]]): Run<Binding> {
  if (brief.branchMatch === null) return ok({ kind: 'Unbound', nearby: brief.nestedMatches })
  const feature = featureNamed(brief, brief.branchMatch)
  return feature.ok ? ok({ kind: 'Branch', branch: namingBranch(branches, brief.branchMatch), feature: feature.value }) : feature
}

/** Where setup looks for an umbrella's nested repos: `<dir>/.git`, `source/<dir>/.git`, `packages/<dir>/.git`. */
const NESTED_REPO_PARENTS = ['', 'source', 'packages']
/** Where shipgate's workspace skill puts a git worktree: `.worktrees/<slug>`, beside the repos or inside one. */
const WORKTREES_DIR = '.worktrees'

/** The most nested repos and worktrees one refresh probes (each costs a git run); the hook keeps the same cap. */
const NESTED_REPO_LIMIT = 64

/** The child directories of `base` under the session root (the root itself when empty), as root-relative paths, sorted; dot-names, node_modules and links left out. A cut is a cut. */
async function childDirs($: Engine, base: string): Promise<Run<readonly string[]>> {
  const root = await sessionRoot($)
  const listed = await listRun($, base ? `${prefixOf(root)}${base}` : root)
  if (!listed.ok) return listed
  return ok(
    listed.value
      .filter(entry => entry.kind === 'dir' && !entry.isLink && !entry.name.startsWith('.') && entry.name !== 'node_modules')
      .map(entry => (base ? `${base}/${entry.name}` : entry.name))
      .sort(),
  )
}

/**
 * One step of the nested-repo walk. `repos`: list a parent's children, each a possible repo.
 * `repo`: a child taken when it is a repo, its own worktrees next. `worktrees`: list
 * `<base>/.worktrees`. `worktree`: an entry there, taken when it is a repo; never walked below.
 */
type WalkStep =
  | { readonly kind: 'repos'; readonly parent: string }
  | { readonly kind: 'repo'; readonly dir: string }
  | { readonly kind: 'worktrees'; readonly base: string }
  | { readonly kind: 'worktree'; readonly dir: string }

/** The walk's start: each parent's children, then the parent's own worktrees. */
const WALK_START: readonly WalkStep[] = NESTED_REPO_PARENTS.flatMap((parent): WalkStep[] => [
  { kind: 'repos', parent },
  { kind: 'worktrees', base: parent },
])

/**
 * The nested repos of an umbrella checkout, relative to the session root. An umbrella
 * is a plain folder or a repo of its own holding the real repos one level down; its own
 * branch (if any) carries no stream, the nested repos' branches do. A worktree sits in
 * `.worktrees/` beside the repos or inside one, so those are looked into as well: a repo,
 * then its own worktrees, then the parent's — each directory once, at most NESTED_REPO_LIMIT
 * in all, the walk stopping there too. Nothing below `.worktrees/<name>` is walked (HUD ADR
 * 0004): a session opened inside an issue worktree finds its repos as its own nested repos.
 * The same order and cap as shipgate's SessionStart hook. A cut is a cut.
 */
async function nestedRepos($: Engine): Promise<Run<readonly string[]>> {
  const prefix = prefixOf(await sessionRoot($))
  // root-relative paths, checked absolute: a relative one would resolve from the shell's directory
  const isRepo = (dir: string): Promise<Run<boolean>> => existsRun($, `${prefix}${dir}/.git`)
  const walk = async (found: readonly string[], steps: readonly WalkStep[]): Promise<Run<readonly string[]>> => {
    const [step, ...rest] = steps
    if (step === undefined || found.length >= NESTED_REPO_LIMIT) return ok(found)
    switch (step.kind) {
      case 'repos': {
        const repos = await childDirs($, step.parent)
        return repos.ok ? walk(found, [...repos.value.map((dir): WalkStep => ({ kind: 'repo', dir })), ...rest]) : repos
      }
      case 'worktrees': {
        const worktrees = await childDirs($, step.base ? `${step.base}/${WORKTREES_DIR}` : WORKTREES_DIR)
        return worktrees.ok ? walk(found, [...worktrees.value.map((dir): WalkStep => ({ kind: 'worktree', dir })), ...rest]) : worktrees
      }
      case 'repo':
      case 'worktree': {
        if (found.includes(step.dir)) return walk(found, rest)
        const repo = await isRepo(step.dir)
        if (!repo.ok) return repo
        if (!repo.value) return walk(found, rest)
        const next: readonly WalkStep[] = step.kind === 'repo' ? [{ kind: 'worktrees', base: step.dir }, ...rest] : rest
        return walk([...found, step.dir], next)
      }
      default:
        return absurd(step)
    }
  }
  return walk([], WALK_START)
}

/** The distinct branches checked out in `dirs`, in order, the root's own (`own`) left out; a failed git run is a failure (D1). */
async function nestedBranches($: Engine, dirs: readonly string[], own: BranchName | null): Promise<Run<readonly BranchName[]>> {
  return dirs.reduce<Promise<Run<readonly BranchName[]>>>(async (pending, dir) => {
    const found = await pending
    if (!found.ok) return found
    const branch = await branchIn($, dir)
    if (!branch.ok) return branch
    const name = branch.value
    return name === null || name === own || found.value.includes(name) ? found : ok([...found.value, name])
  }, Promise.resolve(ok([])))
}

/**
 * The session's binding: one `status --json --session --branch` call with the root's branch,
 * then, when it binds nothing, one call with every nested repo's branch (journal.py's 1B rule
 * binds only when they name exactly one live stream). A failed call is a failure, never
 * `Unbound` (D1).
 */
async function bindSession($: Engine, script: string): Promise<Run<Binding>> {
  const own = await branchIn($, null)
  if (!own.ok) return own
  const brief = await runJournal($, script, statusArgs(await sessionIdOf($), own.value), decodeStatus)
  if (!brief.ok) return brief
  const direct = directBinding(brief.value, own.value)
  if (direct !== null) return direct
  const repos = await nestedRepos($)
  if (!repos.ok) return repos
  const branches = await nestedBranches($, repos.value, own.value)
  if (!branches.ok) return branches
  const [first, ...more] = branches.value
  if (first === undefined) return ok({ kind: 'Unbound', nearby: [] })
  const nested = await runJournal($, script, ['status', '--json', ...branches.value.map(branch => `--nested-branch=${branch}`)], decodeStatus)
  return nested.ok ? nestedBinding(nested.value, [first, ...more]) : nested
}

/** A markdown artifact the position names, read under the project root; null when it cannot be read (a cut is a cut). */
async function markdownAt($: Engine, path: MarkdownFile['path']): Promise<Run<MarkdownFile | null>> {
  const text = await readRun($, inProject(path))
  return text.ok ? ok(text.value === null ? null : { path, text: text.value }) : text
}

/** The ADRs the position names that could be read, parsed, in its order (a cut is a cut). */
async function adrsAt($: Engine, paths: readonly MarkdownFile['path'][]): Promise<Run<readonly Adr[]>> {
  return paths.reduce<Promise<Run<readonly Adr[]>>>(async (pending, path) => {
    const read = await pending
    if (!read.ok) return read
    const file = await markdownAt($, path)
    if (!file.ok) return file
    return file.value === null ? read : ok([...read.value, parseAdr(file.value.path, file.value.text)])
  }, Promise.resolve(ok([])))
}

/** What `toPosition` maps: the decoded position and the worklog, ADRs and PRD it names, read. */
async function positionInputsOf($: Engine, doc: PositionDoc): Promise<Run<PositionInputs>> {
  const worklog = doc.artifacts.worklog === null ? ok(null) : await markdownAt($, doc.artifacts.worklog.path)
  if (!worklog.ok) return worklog
  const adrs = await adrsAt($, doc.artifacts.adrs)
  if (!adrs.ok) return adrs
  const prd = doc.artifacts.prd === null ? ok(null) : await markdownAt($, doc.artifacts.prd)
  if (!prd.ok) return prd
  return ok({ doc, worklog: worklog.value, adrs: adrs.value, prd: prd.value })
}

/** The bound stream's position: `position --stream <s> --json`, then the artifacts it names. */
async function boundRefresh($: Engine, script: string, via: BindingVia, stream: StreamName): Promise<Refreshed> {
  const doc = await runJournal($, script, ['position', '--stream', stream, '--json'], decodePosition)
  if (!doc.ok) return refreshedOf(doc.error)
  const inputs = await positionInputsOf($, doc.value)
  return inputs.ok ? { kind: 'Bound', via, position: toPosition(inputs.value) } : refreshedOf(inputs.error)
}

/**
 * One refresh with a found journal.py: the binding, then `position --stream <s> --json` for a
 * bound stream, then the worklog, ADRs and PRD it names, read.
 */
export async function refreshPosition($: Engine, script: string): Promise<Refreshed> {
  const binding = await bindSession($, script)
  if (!binding.ok) return refreshedOf(binding.error)
  const bound = binding.value
  switch (bound.kind) {
    case 'Unbound':
      return { kind: 'Unbound', nearby: bound.nearby }
    case 'Session':
    case 'Branch':
      return boundRefresh($, script, bound.kind, bound.feature.stream)
    default:
      return absurd(bound)
  }
}

/**
 * The stored view after a refresh. `Cut` keeps `before` as it was; `Failed` stores the failure
 * with `before`'s position (bound, or already stale) as stale; `Outdated` stores its sign and
 * no position; `NoJournalScript` and the others map to their own view; `NoProject` is `Off`.
 */
function viewAfter(refreshed: Refreshed, before: HudView): HudView {
  switch (refreshed.kind) {
    case 'Cut':
      return before
    case 'NoProject':
      return OFF
    case 'NoJournalScript':
      return { kind: 'NoJournalScript' }
    case 'Outdated':
      return { kind: 'Outdated', sign: refreshed.sign }
    case 'Failed':
      return { kind: 'Failed', failure: refreshed.failure, stale: shownPositionOf(before) }
    case 'Unbound':
      return { kind: 'Unbound', nearby: refreshed.nearby }
    case 'Bound':
      return { kind: 'Bound', via: refreshed.via, position: refreshed.position }
    default:
      return absurd(refreshed)
  }
}

/** The stream a view is bound to; null for any other view. */
const boundStreamOf = (shown: HudView): StreamName | null => (shown.kind === 'Bound' ? shown.position.stream : null)

/** The view before the first refresh, and after a project loses its sidecar. */
const OFF: HudView = { kind: 'Off' }

const view = atom({ plugin: 'shipgate-hud', key: 'view' } as const, OFF, { shape: 'shipgate-hud.view-v3' })
const tab = atom({ plugin: 'shipgate-hud', key: 'tab' } as const, null)
const designOpen = atom({ plugin: 'shipgate-hud', key: 'designOpen' } as const, null)
const review = atom({ plugin: 'shipgate-hud', key: 'review' } as const, EMPTY_REVIEW, { shape: 'shipgate-hud.review-v2' })

const JOURNAL_APPEND = /journal\.py\b[\s\S]*\bappend\b/

/** The publish hold's two choices; any other answer refuses. */
const REFUSE = 'Refuse'
const ONCE = 'Let it through once'

/** A Bash call's command line as `tool.check` carries it; null when the input has none. */
const commandOf = (input: unknown): string | null => stringOf(recordOf(input)?.['command'])

/** A tool call's argument read off the event as a string; undefined when absent or another type. */
const stringArg = (e: unknown, key: string): string | undefined => stringOf(recordOf(e)?.[key]) ?? undefined

/** A value's JSON text; null when it has none (a cycle, a bigint, nothing to print). */
const jsonTextOf = (value: unknown): string | null => {
  const text = settleSync(() => JSON.stringify(value))
  return text.ok ? stringOf(text.value) : null
}

/** The run id a Workflow result names: read from core's `text`, else the result as text, else the result's JSON. */
const runIdOfResult = (ran: { readonly result?: unknown; readonly text?: unknown }): string | null => {
  const text = stringOf(ran.text) ?? stringOf(ran.result) ?? jsonTextOf(ran.result)
  return text === null ? null : runIdOf(text)
}

/** A review workflow launch this session noted: the Workflow call's id, the run id its result named, and the stream shown when it launched. */
interface Launch {
  readonly toolUseId: string
  readonly runId: string | null
  readonly stream: StreamName | null
}

/** The most launches remembered; an older one's notification is still captured by its shape. */
const LAUNCH_LIMIT = 8

// The review launches noted this session. Lost on a plugin reload and never refilled: a lost
// launch's return is still captured by its shape, only without its run id and launch stream.
let launches: readonly Launch[] = []

const noteLaunch = (launch: Launch): void => {
  launches = [...launches, launch].slice(-LAUNCH_LIMIT)
}

const launchFor = (toolUseId: string | null): Launch | undefined =>
  toolUseId === null ? undefined : launches.find(launch => launch.toolUseId === toolUseId)

const IDLE: RefreshSlot = { kind: 'Idle' }
const NOT_SEARCHED: ScriptLookup = { kind: 'NotSearched' }
const NOT_FOUND: ScriptLookup = { kind: 'NotFound' }

// Module state: lost on a reload, which is fine: session.start runs again and refills it, and
// each hook that needs it locates the project and journal.py again when it is empty.
let journalScript = ''
let script: ScriptLookup = NOT_SEARCHED
let homes: SidecarHomes | null = null
let projectRoot: string | null = null
let slot: RefreshSlot = IDLE

/** Does the session draw anywhere? Read at each hook, never cached (D5): empty in a plain -p run. */
const isDrawing = async ($: Engine): Promise<boolean> => (await $.session.surfaces()).length > 0

/** The surface's element table: the declared cast boundary for `$.ui.resolve`. */
const uiOf = ($: Engine, e: ResolveInput): Ui =>
  // cast: the engine answers its own element table for the surface; views.tsx draws with the elements Ui names
  $.ui.resolve(e) as unknown as Ui

/** Is the project journaled? Read off the view: any view but `Off` is (no atom of its own). */
const isJournaled = async ($: Engine): Promise<boolean> => (await read($, view)).kind !== 'Off'

/** Locate the project again; a project with no sidecar turns the view `Off`. A cut writes nothing and is a `Cut` failure. */
async function detect($: Engine): Promise<Result<Rejection, boolean>> {
  const located = await locateProject($)
  if (!located.ok) return located
  projectRoot = located.value
  if (located.value !== null) return ok(true)
  homes = null
  await update($, view, () => OFF)
  return ok(false)
}

/**
 * journal.py's path: the one found before, else a search. A search that finds nothing is
 * searched again next time (shipgate may be installed meanwhile); a cut search is a cut and
 * leaves the lookup as it was.
 */
async function journalScriptOf($: Engine): Promise<Run<string | null>> {
  if (script.kind === 'Found') return ok(script.path)
  const found = await locateJournal($, journalScript)
  if (found.ok) script = found.value === null ? NOT_FOUND : { kind: 'Found', path: found.value }
  return found
}

/**
 * A refresh with `path`, searched again once when a run exited and the script is gone (a
 * plugin cache update moved it: python3 exits 2 for a file it cannot open). An `Outdated`
 * refresh clears the lookup: a newer journal.py may sit beside this one (a plugin cache update
 * keeps the old version), and the next refresh searches again. Only the next one: no refresh
 * searches twice.
 */
async function refreshWith($: Engine, path: string): Promise<Refreshed> {
  const refreshed = await refreshPosition($, path)
  if (refreshed.kind === 'Outdated') {
    script = NOT_SEARCHED
    return refreshed
  }
  if (refreshed.kind !== 'Failed' || refreshed.failure.kind !== 'Exited') return refreshed
  const isThere = await existsRun($, path)
  if (!isThere.ok) return CUT
  if (isThere.value) return refreshed
  script = NOT_SEARCHED
  const moved = await journalScriptOf($)
  if (!moved.ok) return refreshedOf(moved.error)
  return moved.value === null ? NO_JOURNAL_SCRIPT : refreshPosition($, moved.value)
}

/** One refresh's outcome, nothing written: the project (located again after a reload), journal.py, the homes, the position. */
async function readRefresh($: Engine): Promise<Refreshed> {
  if (projectRoot === null) {
    const located = await locateProject($)
    if (!located.ok) return refreshedOf(located.error)
    projectRoot = located.value
  }
  if (projectRoot === null) {
    homes = null
    return NO_PROJECT
  }
  const found = await journalScriptOf($)
  if (!found.ok) return refreshedOf(found.error)
  if (found.value === null) return NO_JOURNAL_SCRIPT
  homes = await readHomes($)
  return refreshWith($, found.value)
}

/** One refresh, its outcome written to the view in one write (a cut writes nothing). */
async function refreshOnce($: Engine): Promise<Refreshed> {
  const refreshed = await readRefresh($)
  if (refreshed.kind !== 'Cut') await update($, view, before => viewAfter(refreshed, before))
  return refreshed
}

/**
 * `refreshOnce` that never rejects: a rejection the module did not turn into a value (a state
 * write, the session's directory) is a cut, or a failure written to the view when it can be.
 */
async function refreshSettled($: Engine): Promise<Refreshed> {
  const settled = await settle(() => refreshOnce($))
  if (settled.ok) return settled.value
  const refreshed = refreshedOf(settled.error)
  if (refreshed.kind !== 'Cut') await settle(() => update($, view, before => viewAfter(refreshed, before)))
  return refreshed
}

/** Runs refreshes until no request is left waiting, then frees the slot: the value is the last run's. */
async function drain($: Engine): Promise<Refreshed> {
  const refreshed = await refreshSettled($)
  if (slot.kind === 'Running' && slot.hasTrailing) {
    slot = { ...slot, hasTrailing: false }
    return drain($)
  }
  slot = IDLE
  return refreshed
}

/**
 * Coalescing refresh through `slot`: a request during a run marks one trailing run, every
 * caller awaits the run that covers it, and a failure lands in the view instead of rejecting a
 * caller. Resolves with the outcome of the run that covered the request.
 */
async function refresh($: Engine): Promise<Refreshed> {
  switch (slot.kind) {
    case 'Running':
      slot = { ...slot, hasTrailing: true }
      return slot.run
    case 'Idle': {
      const run = drain($)
      slot = { kind: 'Running', run, hasTrailing: false }
      return run
    }
    default:
      return absurd(slot)
  }
}

/**
 * Does a written path land in a configured artifact home? shipgate's defaults apply before the
 * first refresh. A home whose glob no pattern can be built from (`isReadableGlob`) is skipped.
 */
async function isArtifactPath($: EngineInterface, path: string): Promise<boolean> {
  const relative = await projectRelative($, path)
  if (relative === null || relative.startsWith('..')) return false
  return (homes ?? DEFAULT_HOMES).globs.some(glob => isReadableGlob(glob) && matchesHome(relative, glob))
}

/**
 * Can `matchesHome` build a pattern from a sidecar glob? Its `[...]` classes become RegExp
 * classes, and a range whose ends are out of order (`[z-a]`) is a SyntaxError there. Every
 * other glob builds. A class is read as `globToRegExp` reads it: up to the next `]`, a leading
 * `!` the negation, each character (a backslash too) itself.
 */
function isReadableGlob(glob: string): boolean {
  const open = glob.indexOf('[')
  if (open < 0) return true
  const close = glob.indexOf(']', open + 1)
  if (close < 0) return true
  const body = glob.slice(open + 1, close).replace(/^!/, '')
  return hasOrderedRanges(body, 0) && isReadableGlob(glob.slice(close + 1))
}

/** Is every `a-b` range of a class body, from `at`, in order (code units, as a RegExp without the `u` flag reads them)? */
function hasOrderedRanges(body: string, at: number): boolean {
  if (at >= body.length) return true
  const isRange = body[at + 1] === '-' && at + 2 < body.length
  if (!isRange) return hasOrderedRanges(body, at + 1)
  return body.charCodeAt(at) <= body.charCodeAt(at + 2) && hasOrderedRanges(body, at + 3)
}

/** The veto prompt names the decision by stream, gate, its place among the decisions (newest first) and time; the model reads its text from the journal. */
function vetoText(position: Position, decision: Decision): string {
  const total = position.decisions.length
  const index = position.decisions.findIndex(drawn => drawn.seq === decision.seq)
  const place = index < 0 ? `gate decision seq ${decision.seq}` : `gate decision ${index + 1} of ${total} (newest first, seq ${decision.seq})`
  const gate = decision.gate === null ? 'no gate named' : `gate ${decision.gate}`
  return (
    `The user pressed Veto in the shipgate HUD on ${place} in stream ${position.stream} ` +
    `(${gate}, recorded ${decision.at}; raised by the orchestrator in executive mode). ` +
    `Read that decision from the journal (journal.py position --json lists the stream's decisions by seq), revisit it with the user — the alternatives and what ` +
    `changes — and record a deviation event once you agree.`
  )
}

/** The position a view draws: the bound stream's, or the stale one under a failure; null for any other view. */
const shownPositionOf = (shown: HudView): Position | null => {
  switch (shown.kind) {
    case 'Bound':
      return shown.position
    case 'Failed':
      return shown.stale
    case 'Off':
    case 'NoJournalScript':
    case 'Unbound':
    case 'Outdated':
      return null
    default:
      return absurd(shown)
  }
}

/** Accept or Kill on survivor `index` of the round `id` names, as drawn: the mark is kept on its board, and the plain prompt names it (never `asUser`). */
function markFinding($: Engine, shown: HudView, drawn: ReviewState, action: ReviewMark, id: RoundId, index: number): void {
  const position = shownPositionOf(shown)
  const board = boardsFor(drawn.boards, position === null ? null : position.stream).find(held => roundId(held) === id) ?? null
  if (board === null || board.survivors[index] === undefined) return
  void update($, review, stored => {
    const state = decodeReviewState(stored)
    return { ...state, boards: state.boards.map(held => (roundId(held) === id ? markSurvivor(held, index, action) : held)) }
  })
  void $.prompt.submit({ text: findingPrompt(action, index, board) })
}

/** The pane's controls bound to `$`, for the view and the review state as drawn. */
function actionsOf($: Engine, shown: HudView, drawn: ReviewState): Actions {
  const position = shownPositionOf(shown)
  return {
    setTab: (next: Tab) => {
      void update($, tab, () => next)
    },
    openDesign: (slug: string) => {
      void update($, designOpen, () => slug)
    },
    veto: (decision: Decision) => {
      if (position !== null) void $.prompt.submit({ text: vetoText(position, decision) })
    },
    refresh: () => {
      void refresh($)
    },
    openPane: () => {
      void $.ui.open({ id: PANE_ID, title: 'shipgate', focus: true })
    },
    accept: (id: RoundId, index: number) => {
      markFinding($, shown, drawn, 'accepted', id, index)
    },
    kill: (id: RoundId, index: number) => {
      markFinding($, shown, drawn, 'killed', id, index)
    },
    tick: (criterion: CriterionId) => {
      // a criterion is drawn only under a position: no position, no press
      if (position === null) return
      const verdict = position.lastVerdict
      const status = verdict === null ? null : (verdict.criteria[criterion] ?? null)
      const seq = verdict === null ? null : verdict.seq
      void update($, review, stored => {
        const state = decodeReviewState(stored)
        return { ...state, ticks: nextTicks(state.ticks, position.stream, criterion, status, seq) }
      })
    },
    openRound: (open: OpenRound) => {
      void update($, review, stored => ({ ...decodeReviewState(stored), open }))
    },
  }
}

/**
 * A decoded review return captured as its stream's next round: a noted launch stamps its run id
 * and launch stream, else the stream the view is bound to; the newest round opens; older rounds,
 * their marks and the ticks stay.
 */
async function captureBoard($: Engine, ret: ReviewReturn, toolUseId: string | null): Promise<void> {
  const launch = launchFor(toolUseId)
  const stream = launch?.stream ?? boundStreamOf(await read($, view))
  const now = new Date(await $.clock.now())
  const at = Number.isNaN(now.getTime()) ? null : isoTime(now.toISOString())
  if (at === null) return
  const board = toReviewBoard(ret, launch?.runId ?? null, stream, at)
  // the newest round opens; older rounds, their marks and the ticks stay
  await update($, review, (stored): ReviewState => {
    const state = decodeReviewState(stored)
    return { ...state, boards: pushBoard(state.boards, board), open: { kind: 'newest' } }
  })
}

// ---------------------------------------------------------------------------------------
// The publish gate (HUD ADR 0005)
// ---------------------------------------------------------------------------------------

/** A target or a bound stream the gate could not resolve: why, or the failure that kept it from reading. */
type Unbranched = Extract<TargetBinding, { readonly kind: 'Unresolved' | 'Unknown' }>

/** The branch checked out where a `Head` publish runs: `dir` resolved against the shell's directory. */
async function headBranchOf($: Engine, dir: CommandDir): Promise<Result<Unbranched, BranchName>> {
  switch (dir.kind) {
    case 'Unreadable':
      return err({ kind: 'Unresolved', why: dir.why })
    case 'Shell':
    case 'Path': {
      const shell = await shellDir($)
      const at = dir.kind === 'Shell' ? shell : absoluteIn(shell, dir.path)
      const head = await branchIn($, at)
      if (!head.ok) return err({ kind: 'Unknown', failure: head.error })
      return head.value === null ? err({ kind: 'Unresolved', why: `no branch is checked out in ${at} (a detached HEAD, or no repository)` }) : ok(head.value)
    }
    default:
      return absurd(dir)
  }
}

/** The one branch a publish command publishes, or why there is none. */
async function targetBranchOf($: Engine, command: PublishCommand): Promise<Result<Unbranched, BranchName>> {
  const ref = command.ref
  switch (ref.kind) {
    case 'Unresolved':
      return err({ kind: 'Unresolved', why: ref.why })
    case 'Branch': {
      const branch = branchName(ref.name)
      return branch === null ? err({ kind: 'Unresolved', why: `\`${ref.name}\` is no branch name` }) : ok(branch)
    }
    case 'Head':
      return headBranchOf($, command.dir)
    default:
      return absurd(ref)
  }
}

/** A branch whose stream the gate has read for an earlier command of the line, and what the read gave. */
interface BranchRead {
  readonly branch: BranchName
  readonly target: TargetBinding
}

/** A publish command's target, and the branches read once it is resolved. */
interface Resolution {
  readonly target: TargetBinding
  readonly read: readonly BranchRead[]
}

/** The stream of `branch` and its `publish`, from one `status --branch` call; `Outdated` when the read shows an older journal.py. */
async function branchTarget($: Engine, script: string, branch: BranchName): Promise<Result<Outdated, TargetBinding>> {
  const brief = await runJournal($, script, ['status', '--json', `--branch=${branch}`], decodeStatus)
  if (!brief.ok) {
    const failure = brief.error
    return failure.kind === 'Outdated' ? err(failure) : ok({ kind: 'Unknown', failure })
  }
  const stream = brief.value.branchMatch
  if (stream === null) return ok({ kind: 'NoStream', branch })
  const feature = featureNamed(brief.value, stream)
  return ok(feature.ok ? { kind: 'Stream', branch, stream, publish: feature.value.publish } : { kind: 'Unknown', failure: feature.error })
}

/**
 * The publish command's target (HUD ADR 0005), with its stream and `publish` from one
 * `status --branch` call; a branch in `read` (an earlier command's) is not read again.
 * `ref.Unresolved` gives `Unresolved{why}`. `ref.Branch` is that branch, and `dir` is not
 * needed. `ref.Head` in a `dir.Unreadable` gives `Unresolved{why}`. Otherwise it is the HEAD of
 * `dir`, resolved against the shell's directory. A read that shows an older journal.py is
 * `Outdated`, and no later command is read.
 */
async function resolveTarget($: Engine, script: string, command: PublishCommand, read: readonly BranchRead[]): Promise<Result<Outdated, Resolution>> {
  const branch = await targetBranchOf($, command)
  if (!branch.ok) return ok({ target: branch.error, read })
  const known = read.find(entry => entry.branch === branch.value)
  if (known !== undefined) return ok({ target: known.target, read })
  const target = await branchTarget($, script, branch.value)
  return target.ok ? ok({ target: target.value, read: [...read, { branch: branch.value, target: target.value }] }) : target
}

/**
 * The session's own stream as a refresh left it: bound with its `publish`, none, or unknown (a
 * failed or cut refresh never passes for none). An `Outdated` refresh has no bound stream: the
 * gate's inputs are `Outdated` before this is asked.
 */
function boundOf(refreshed: Exclude<Refreshed, { readonly kind: 'Outdated' }>): BoundStream {
  switch (refreshed.kind) {
    case 'Bound':
      return { kind: 'Stream', stream: refreshed.position.stream, publish: refreshed.position.publish }
    case 'Unbound':
    case 'NoProject':
    case 'NoJournalScript':
      return { kind: 'None' }
    case 'Failed':
      return { kind: 'Unknown', failure: refreshed.failure }
    case 'Cut':
      return { kind: 'Unknown', failure: CUT_FAILURE }
    default:
      return absurd(refreshed)
  }
}

/** A publish line whose targets and bound stream could not be read: each command held, naming `failure`. */
const unreadableTargets = (commands: PublishCommands, failure: ReadFailure): GateInputs => {
  const unknown = (command: PublishCommand): PublishTarget => ({ command, target: { kind: 'Unknown', failure } })
  const [first, ...rest] = commands
  return { kind: 'Target', targets: [unknown(first), ...rest.map(unknown)], bound: { kind: 'Unknown', failure } }
}

/**
 * Each publish command's target, in textual order (`resolveTarget`): one `status --branch` call
 * per distinct branch, `read` holding those made; `Outdated` at the first read that shows an
 * older journal.py.
 */
async function targetsOf(
  $: Engine,
  script: string,
  commands: PublishCommands,
  read: readonly BranchRead[],
): Promise<Result<Outdated, readonly [PublishTarget, ...PublishTarget[]]>> {
  const [command, ...rest] = commands
  const resolved = await resolveTarget($, script, command, read)
  if (!resolved.ok) return resolved
  const first: PublishTarget = { command, target: resolved.value.target }
  const [next, ...after] = rest
  if (next === undefined) return ok([first])
  const later = await targetsOf($, script, [next, ...after], resolved.value.read)
  return later.ok ? ok([first, ...later.value]) : later
}

/**
 * The gate's inputs for a line that publishes: the surfaces, the project, journal.py, then each
 * command's target and the bound stream. `Outdated` when the refresh or a target read shows an
 * older journal.py.
 */
async function publishInputsOf($: Engine, commands: PublishCommands): Promise<GateInputs> {
  if (!(await isDrawing($))) return { kind: 'NoSurface' }
  const project = await detect($)
  if (!project.ok) return unreadableTargets(commands, project.error)
  if (!project.value) return { kind: 'NoProject' }
  // the refresh this request covers: its value, never the atoms it wrote (D4)
  const refreshed = await refresh($)
  if (refreshed.kind === 'NoProject') return { kind: 'NoProject' }
  if (refreshed.kind === 'NoJournalScript') return { kind: 'NoJournalScript' }
  if (refreshed.kind === 'Outdated') return { kind: 'Outdated' }
  const bound = boundOf(refreshed)
  const found = script
  if (found.kind !== 'Found') return unreadableTargets(commands, bound.kind === 'Unknown' ? bound.failure : CUT_FAILURE)
  const targets = await targetsOf($, found.path, commands, [])
  if (!targets.ok) {
    // a newer journal.py may sit beside this one: the next refresh searches again
    script = NOT_SEARCHED
    return { kind: 'Outdated' }
  }
  return { kind: 'Target', targets: targets.value, bound }
}

/**
 * Everything the gate decides on, read fresh: the surfaces (`$.session.surfaces()`), the
 * project, journal.py, each publish command's target stream and the session's bound stream.
 */
async function gateInputsOf($: Engine, scan: CommandScan): Promise<GateInputs> {
  switch (scan.kind) {
    case 'clear':
    case 'opaque':
      return { kind: 'NotPublish' }
    case 'publishes':
      return publishInputsOf($, scan.commands)
    default:
      return absurd(scan)
  }
}

/**
 * Held means asked: the dialog shows `holdReason`, which names every held command of the line,
 * so one "Let it through once" lets the whole line through on informed consent; true only for
 * that answer. A dismissed dialog, a -p run or an engine with no dialog refuses.
 */
async function askToPass($: Engine, holds: Holds): Promise<boolean> {
  const answer = await settle(() => $.ui.ask(`${holdReason(holds)} Let it through?`, { options: [REFUSE, ONCE], header: 'publish' }))
  return answer.ok && answer.value === ONCE
}

/** The scan of a Bash call's input: a line with no command publishes nothing. */
const scanOf = (input: unknown): CommandScan => {
  const command = commandOf(input)
  return command === null ? { kind: 'clear' } : scanCommand(command)
}

/** Does a Bash call's input publish? The gate's fail-closed `.catch` asks (pure only). */
const isPublishInput = (input: unknown): boolean => {
  const command = commandOf(input)
  return command !== null && publishCommandOf(command) !== null
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
    const project = e.surface === null ? ok(false) : await detect($)
    if (project.ok && project.value) {
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
    if (await isDrawing($)) {
      const project = await detect($)
      if (project.ok && project.value) await refresh($)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'hud' }, async $ => {
    const project = await detect($)
    if (!project.ok) return {} // cut by the person: nothing to open
    if (!project.value) {
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
    if (ran.deny === undefined && JOURNAL_APPEND.test(e.command) && (await isJournaled($))) await refresh($)
    return ran
  }).catch(($, e, next) => next(e))

  // An artifact in a configured home was written: the plan or the design may have changed.
  on('tool.call', { tool: ['Write', 'Edit'] }, async ($, e, next) => {
    const ran = await next(e)
    const path = stringArg(e, 'file_path')
    if (ran.deny === undefined && path !== undefined && (await isJournaled($)) && (await isArtifactPath($, path))) await refresh($)
    return ran
  }).catch(($, e, next) => next(e))

  // The publish gate: `git push`, `gh pr create` and `glab mr create` wait for the evidence
  // journal.py demands before mr-opened, on the stream of the branch the command publishes
  // (HUD ADR 0005). Held means asked; any answer but "Let it through once" refuses. Nothing
  // is written and nothing remembered. A failure refuses a publish command (`.catch`, pure only).
  on('tool.check', { tool: 'Bash' }, async ($, e, next) => {
    const verdict = gateVerdict(await gateInputsOf($, scanOf(e.input)))
    if (verdict.kind === 'Pass') return next(e)
    return (await askToPass($, verdict.holds)) ? next(e) : { decision: 'deny' as const, reason: denyReason(verdict.holds) }
  }).catch(($, e, next) => (isPublishInput(e.input) ? { decision: 'deny' as const, reason: FAIL_CLOSED } : next(e)))

  // The review workflow launched: note its call id and run id, so its notification is known by id.
  on('tool.call', { tool: 'Workflow' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && isReviewLaunch([stringArg(e, 'script'), stringArg(e, 'scriptPath'), stringArg(e, 'name')])) {
      noteLaunch({ toolUseId: e.tool_use_id, runId: runIdOfResult(ran), stream: boundStreamOf(await read($, view)) })
    }
    return ran
  }).catch(($, e, next) => next(e))

  // A background task finished: when its result decodes as the review workflow's return, it
  // becomes the Review board. A noted launch only stamps the run id and the stream it launched
  // on; an id match alone never makes a board. The prompt always passes on unchanged; never dropped.
  on('prompt.submit', { origin: { kind: 'task-notification' } }, async ($, e, next) => {
    if (!(await isDrawing($))) return next(e) // nothing to draw (claude -p, the SDK)
    const note = parseTaskNotification(e.text)
    if (note === null || note.status === 'failed' || note.status === 'killed') return next(e)
    // the engine cuts a long result in the notification text: the output file holds it whole
    const inline = decodeReviewReturn(note.result)
    const ret = inline.ok ? inline.value : await reviewReturnFromOutput($, note.outputFile)
    if (ret !== null) await captureBoard($, ret, note.toolUseId)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const shown = await read($, view)
    const drawn = decodeReviewState(await read($, review))
    return bandOf(uiOf($, e), shown, actionsOf($, shown, drawn), e.props.bodyColumns, drawn) ?? next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE_ID }, async ($, e) => {
    const shown = await read($, view)
    const state: PaneState = {
      tab: await read($, tab),
      designOpen: await read($, designOpen),
      columns: e.props.bodyColumns,
      review: decodeReviewState(await read($, review)),
    }
    return paneOf(uiOf($, e), shown, state, actionsOf($, shown, state.review))
  })
}
