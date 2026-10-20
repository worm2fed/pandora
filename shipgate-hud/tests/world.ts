// The world beneath the plugin, answered from memory: a journaled project whose journal.py
// answers `status` and `position` from the raw shapes in fixtures.ts. `claude plugin test`
// runs with no fs, process or network, so a test that drives session.start hooks these calls
// itself. Generic names only — public repository.

import { mock } from 'claude-code/testing'
import type { On, ProcessRunResult, RenderSurface } from 'claude-code'

import { ADR, EXAMPLE_FEATURE, EXAMPLE_POSITION, EXAMPLE_STREAM, PRD, SIDECAR, WORKLOG } from './fixtures'
import type { FeatureJson, PositionJson, StatusJson } from './fixtures'

export const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 9 }, view: {} },
}

export const PANE = {
  component: 'Pane' as const,
  requestId: 'shipgate-hud',
  props: { title: 'shipgate', isFocused: false, bodyColumns: 100, placement: 'dock' as const, scroll: { offset: 0, bodyRows: 40 }, view: {} },
}

/** This session's id, as the engine answers `$.session.id()`. */
export const SESSION_ID = 'session-a'

export const START = { cwd: '/tmp/project', surface: 'terminal' as const, isInteractive: true }

/** A process that exited 0 having printed `stdout`. */
export const ok = (stdout: string): { readonly value: ProcessRunResult } => ({
  value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

/** A process that exited `exitCode` having printed `stderr`. */
export const exited = (exitCode: number, stderr: string): ProcessRunResult => ({ exitCode, stdout: '', stderr, isStdoutTruncated: false, isStderrTruncated: false })

/** What the engine rejects a `$.process.run` the person cut with: its own `) aborted` text. */
export const CUT_RUN = '$.process.run(python3) aborted'

/** argparse's usage error, as an older journal.py prints it for a flag or a subcommand it does not know. */
export const usageError = (line: string): ProcessRunResult =>
  exited(2, `usage: journal.py [-h] [--db PATH] COMMAND ...\njournal.py: error: ${line}\n`)

/** The session as the engine answers it beneath the plugin. */
export interface EngineWorld {
  /** The session root (`$.session.root()`). */
  readonly root: string
  /** Where the shell's `cd` has taken the session (`$.session.cwd()`). */
  readonly shell: string
  /** `$.session.id()`. */
  readonly sessionId: string
  /** `$.session.surfaces()`: where the session draws (none in a `-p` run). */
  readonly surfaces: readonly RenderSurface[]
}

/**
 * What every session needs answered beneath the plugin, journaled or not. The root is
 * START's, the shell is the root, the id is SESSION_ID and the session draws on the
 * terminal, unless `given` says otherwise.
 */
export function engineWorld(
  on: On,
  given: Partial<EngineWorld> = {},
): { commands: string[]; opened: string[]; submitted: string[]; prompts: Record<string, unknown>[] } {
  const root = given.root ?? START.cwd
  const world: EngineWorld = { root, shell: given.shell ?? root, sessionId: given.sessionId ?? SESSION_ID, surfaces: given.surfaces ?? ['terminal'] }
  const commands: string[] = []
  const opened: string[] = []
  const submitted: string[] = []
  // every prompt.submit event that reached the engine, whole (origin, asUser, …)
  const prompts: Record<string, unknown>[] = []
  mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }))
  on('session.cwd', async () => ({ value: world.shell }))
  on('session.root', async () => ({ value: world.root }))
  on('session.id', async () => ({ value: world.sessionId }))
  on('session.surfaces', async () => ({ value: world.surfaces }))
  // The engine draws nothing of its own in the band: an empty box stands for that here.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)
    return Box({ children: [] })
  })
  on('command.register', async (_$, e) => {
    commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.open', async (_$, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true as const } }
  })
  on('prompt.submit', async (_$, e) => {
    submitted.push(e.text)
    prompts.push({ ...e })
    return { text: e.text }
  })
  return { commands, opened, submitted, prompts }
}

/** A project with no sidecar: every path is missing, every process run is recorded. */
export function bareWorld(on: On): { runs: string[][] } {
  const runs: string[][] = []
  on('fs.exists', async () => ({ value: false }))
  on('process.run', async (_$, e) => {
    runs.push([...e.argv])
    return ok('')
  })
  return { runs }
}

/** The value of the `--<name>=<value>` flags in an argv, in order. */
export const flagValues = (argv: readonly string[], name: string): readonly string[] =>
  argv.filter(arg => arg.startsWith(`--${name}=`)).map(arg => arg.slice(name.length + 3))

/**
 * `status --json` as journal.py answers it over `features`, for the flags of each run: the
 * session's stream from `drives` (session id → the stream it last wrote to), the stream the
 * `--branch` names (a stream named as the branch), and else journal.py's nested rule (1B):
 * the live streams the `--nested-branch`es name, newest first, bind only when they are one.
 */
export const statusOver =
  (features: readonly FeatureJson[], drives: Readonly<Record<string, string>> = {}) =>
  (argv: readonly string[]): StatusJson => {
    const listed = (name: string | undefined): string | null => (name !== undefined && features.some(f => f.stream === name) ? name : null)
    const session = flagValues(argv, 'session')[0]
    const own = listed(flagValues(argv, 'branch')[0])
    const lastAt = (stream: string): string => features.find(f => f.stream === stream)?.last_event?.ts ?? ''
    const nested = [...new Set(flagValues(argv, 'nested-branch'))]
      .filter(branch => features.some(f => f.stream === branch && f.lifecycle === 'live'))
      .sort((a, b) => lastAt(b).localeCompare(lastAt(a)))
    const branchMatch = own ?? (nested.length === 1 ? (nested[0] ?? null) : null)
    return {
      features,
      session_match: session === undefined ? null : listed(drives[session]),
      branch_match: branchMatch,
      nested_matches: nested,
    }
  }

/** The journal a journaled world answers from. */
export interface JournalWorld {
  /** `status --json`'s answer to a run with this argv. */
  readonly status: (argv: readonly string[]) => StatusJson
  /** `position --stream <s> --json`'s answer; null: journal.py has no such stream (exit 1). */
  readonly position: (stream: string) => PositionJson | null
  /** The branch `git rev-parse --abbrev-ref HEAD` prints in `dir` (`git -C <dir>`; null: the session root); `HEAD` when detached. */
  readonly branch: (dir: string | null) => string
  /** The text the example worklog reads as. */
  readonly worklog: string
  /** The directory holding the sidecar; null: every directory holds one, so the session finds it at its own root. */
  readonly sidecarDir: string | null
}

/** The example checkout: one stream, named by the branch every checkout is on. */
export const EXAMPLE_JOURNAL: JournalWorld = {
  status: statusOver([EXAMPLE_FEATURE]),
  position: stream => ({ ...EXAMPLE_POSITION, stream }),
  branch: () => EXAMPLE_STREAM,
  worklog: WORKLOG,
  sidecarDir: null,
}

/** What a journaled world recorded: each process run's argv and the directory it ran in (same index), each path read, each path asked for. */
export interface JournalRecord {
  readonly runs: string[][]
  readonly cwds: (string | undefined)[]
  readonly reads: string[]
  readonly asked: string[]
}

/**
 * A journaled project: the sidecar and journal.py exist, journal.py answers `status` and
 * `position` from `given` over EXAMPLE_JOURNAL, git answers the branch, and the example
 * artifacts read as the fixtures. Every process run, read and existence check that reaches
 * the world is recorded (a hook registered above it may answer first).
 */
export function journaledWorld(on: On, given: Partial<JournalWorld> = {}): JournalRecord {
  const journal: JournalWorld = { ...EXAMPLE_JOURNAL, ...given }
  const record: JournalRecord = { runs: [], cwds: [], reads: [], asked: [] }
  const { runs, cwds, reads, asked } = record
  const isSidecar = (path: string): boolean =>
    journal.sidecarDir === null ? path.endsWith('/.claude/shipgate.json') : path === `${journal.sidecarDir}/.claude/shipgate.json`
  on('fs.exists', async (_$, e) => {
    asked.push(e.path)
    return { value: isSidecar(e.path) || e.path.endsWith('/shipgate/scripts/journal.py') }
  })
  on('fs.read', async (_$, e) => {
    reads.push(e.path)
    if (e.path.endsWith('.claude/shipgate.json')) return { value: JSON.stringify(SIDECAR) }
    if (e.path.endsWith('example.worklog.md')) return { value: journal.worklog }
    if (e.path.endsWith('0007-example-decision.md')) return { value: ADR }
    if (e.path.endsWith('/docs/prd/example.md')) return { value: PRD }
    return { deny: `no such fixture: ${e.path}` }
  })
  on('process.run', async (_$, e) => {
    const argv = [...e.argv]
    runs.push(argv)
    cwds.push(e.init?.cwd)
    if (argv[0] === 'git') return ok(`${journal.branch(argv[1] === '-C' ? (argv[2] ?? null) : null)}\n`)
    if (argv.includes('status')) return ok(JSON.stringify(journal.status(argv)))
    if (argv.includes('position')) {
      const doc = journal.position(argv[argv.indexOf('--stream') + 1] ?? '')
      return doc === null ? { value: exited(1, 'error: no such stream') } : ok(JSON.stringify(doc))
    }
    return ok('')
  })
  return record
}

/** How a journal.py run fails above the world: a whole process result, or the engine's rejection with this text. */
export type RunFault = { readonly kind: 'exits'; readonly ran: ProcessRunResult } | { readonly kind: 'rejects'; readonly text: string }

/**
 * journal.py runs answered by `fault` first, registered above the world (so call it before
 * `journaledWorld`): a fault for the argv, or null to pass the run on to the world. The runs
 * it answered are recorded (`faulted`); the world records only those it answers itself.
 */
export function journalFaults(on: On, fault: (argv: readonly string[]) => RunFault | null): { faulted: string[][] } {
  const faulted: string[][] = []
  on('process.run', { argv: ['python3'] }, async (_$, e, next) => {
    const found = fault(e.argv)
    if (found === null) return next(e)
    faulted.push([...e.argv])
    return found.kind === 'exits' ? { value: found.ran } : { deny: found.text }
  })
  return { faulted }
}

/** A run that exits with `ran`. */
export const exits = (ran: ProcessRunResult): RunFault => ({ kind: 'exits', ran })

/** A run the engine rejects with `text` (the person's cut: CUT_RUN). */
export const rejects = (text: string): RunFault => ({ kind: 'rejects', text })
