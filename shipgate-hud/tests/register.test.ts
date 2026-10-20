import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { CommandRunInput, On, PromptSubmitInput, RenderSurface } from 'claude-code'

import { AUTHORIZED, EXAMPLE_FEATURE, EXAMPLE_POSITION, EXAMPLE_STREAM, SIDECAR, featureOf } from './fixtures'
import type { FeatureJson, PositionJson } from './fixtures'
import {
  BAND,
  CUT_RUN,
  PANE,
  SESSION_ID,
  START,
  bareWorld,
  engineWorld,
  exited,
  exits,
  flagValues,
  journalFaults,
  journaledWorld,
  ok,
  rejects,
  statusOver,
  usageError,
} from './world'
import {
  REVIEW_LAUNCH_RESULT,
  REVIEW_NOTIFICATION,
  REVIEW_NOTIFICATION_TRUNCATED,
  REVIEW_OUTPUT_FILE,
  REVIEW_OUTPUT_PATH,
  REVIEW_RETURN,
  REVIEW_RETURN_ABORTED,
  notificationOf,
} from './fixtures.review'
import { listOf, recordOf } from '../hooks/json'
import { MIN_SHIPGATE_VERSION } from '../hooks/journal'
import { decodeReviewState, findingPrompt } from '../hooks/review'
import type { ReviewState } from '../types'

/** `/hud` typed by the person. */
const HUD_COMMAND: CommandRunInput = { command: 'hud', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } }

/** The orchestrator appends to the journal: a Bash call the HUD refreshes after. */
const APPEND = 'python3 shipgate/scripts/journal.py append --stream s --type deviation --data "{}"'

/** journal.py's `status` runs among the recorded runs. */
const statusRuns = (runs: readonly string[][]): string[][] => runs.filter(argv => argv[0] === 'python3' && argv.includes('status'))

/** journal.py's `position` runs among the recorded runs. */
const positionRuns = (runs: readonly string[][]): string[][] => runs.filter(argv => argv[0] === 'python3' && argv.includes('position'))

/** The stream a `position` run asked for. */
const streamAsked = (argv: readonly string[]): string | undefined => argv[argv.indexOf('--stream') + 1]

/** The git runs into a directory (`git -C <dir>`), by directory. */
const gitDirs = (runs: readonly string[][]): (string | undefined)[] => runs.filter(argv => argv[0] === 'git' && argv[1] === '-C').map(argv => argv[2])

/** A directory entry, as `fs.list` answers it. */
const dir = (name: string) => ({ name, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })

/** The text the pane shows for the example stream's plan: T001 done, T002 failing, T003 ticked and unrecorded, T004 open. */
const EXAMPLE_PLAN = '1/4 done · 1 unrecorded · 1 failing'

/** A world's own Bash tool, so a journal append can run and refresh the position. */
const appendWorld = (on: On): void => {
  on('tool.call', { tool: 'Bash' }, async () => ({ result: { stdout: 'appended', stderr: '' } }))
}

/** The orchestrator appends to the journal: the HUD refreshes, and the shown stream may move. */
const refreshByAppend = ($: Engine, id = 'append-1') => $.tool.call({ tool: 'Bash', tool_use_id: id, command: APPEND })

/** The hooks environment has no DOM lib: the runtime timer, reached through globalThis. */
const sleep = (ms: number): Promise<void> =>
  new Promise<void>(resolve => {
    // cast: the test runtime has setTimeout; the hooks' lib (es2023, no DOM) does not declare it
    const timer = globalThis as unknown as { setTimeout: (fn: () => void, ms: number) => void }
    timer.setTimeout(resolve, ms)
  })

/**
 * A checkout of repos under `root` (root-relative path → the branch git prints there, `HEAD`
 * when detached), and nothing else: a directory lists the next segments of the repo paths
 * under it, and `.git` exists in each repo. Register it before `journaledWorld`; pass its
 * `branch` to it (absolute directories, the gate's, are read relative to `root` too).
 */
const checkoutWorld = (on: On, root: string, repos: Readonly<Record<string, string>>, own = 'main'): { branch: (dir: string | null) => string; asked: string[] } => {
  const asked: string[] = []
  const relative = (path: string): string | null => (path === root ? '' : path.startsWith(`${root}/`) ? path.slice(root.length + 1) : null)
  const children = (at: string): string[] => [
    ...new Set(
      Object.keys(repos)
        .filter(path => at === '' || path.startsWith(`${at}/`))
        .map(path => (at === '' ? path : path.slice(at.length + 1)).split('/')[0] ?? '')
        .filter(name => name !== ''),
    ),
  ]
  on('fs.exists', { path: /\/\.git$/ }, async (_$, e) => {
    asked.push(e.path)
    const repo = relative(e.path.slice(0, -'/.git'.length))
    return { value: repo !== null && repo in repos }
  })
  on('fs.list', async (_$, e) => {
    const at = relative(e.path ?? root)
    const names = at === null ? [] : children(at)
    return names.length === 0 ? { deny: `no such directory: ${e.path ?? root}` } : { value: names.map(dir) }
  })
  return {
    asked,
    branch: path => {
      const at = path === null ? '' : (relative(path) ?? path)
      return at === '' ? own : (repos[at] ?? '')
    },
  }
}

describe('register', () => {
  test('without the sidecar: no process runs, no pane, the band passes through, /hud explains', async ($, on) => {
    const { commands, opened } = engineWorld(on)
    const { runs } = bareWorld(on)
    await $.session.start(START)
    expect(commands).toEqual(['hud'])
    expect(runs).toEqual([])
    expect(opened).toEqual([])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ key: 'open-hud' })).toBeUndefined()
    await band.unmount()
    const answer = await $.command.run(HUD_COMMAND)
    expect(JSON.stringify(answer)).toContain('/shipgate:setup')
  })

  test('with the sidecar: session.start runs status once and position once, opens the pane, draws the stream', async ($, on) => {
    const { opened } = engineWorld(on)
    const { runs, reads } = journaledWorld(on)
    await $.session.start(START)
    expect(statusRuns(runs).map(argv => argv.slice(2))).toEqual([['status', '--json', `--session=${SESSION_ID}`, `--branch=${EXAMPLE_STREAM}`]])
    expect(positionRuns(runs).map(streamAsked)).toEqual([EXAMPLE_STREAM])
    // the artifacts the position names were read under the project root, and nothing the journal did not name
    expect(reads.filter(path => !path.endsWith('.claude/shipgate.json'))).toEqual([
      `${START.cwd}/docs/prd/example.worklog.md`,
      `${START.cwd}/docs/adr/0007-example-decision.md`,
      `${START.cwd}/docs/prd/example.md`,
    ])
    expect(opened).toEqual(['shipgate-hud'])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('implement')
    await band.unmount()
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
    await pane.unmount()
  })

  test('a Bash call that appends to the journal triggers a refresh; another Bash call does not', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    appendWorld(on)
    await $.session.start(START)
    const before = statusRuns(runs).length
    await $.tool.call({ tool: 'Bash', tool_use_id: 't1', command: 'ls -la' })
    expect(statusRuns(runs).length).toBe(before)
    await refreshByAppend($, 't2')
    expect(statusRuns(runs).length).toBe(before + 1)
  })

  test('position --stream gets the stream the brief names, not the branch', async ($, on) => {
    engineWorld(on)
    // journal.py names a `feature/`-prefixed stream for the branch: the HUD asks for that stream
    const { runs } = journaledWorld(on, {
      status: argv => ({ ...statusOver([featureOf('feature/example-stream')])(argv), branch_match: 'feature/example-stream' }),
    })
    await $.session.start(START)
    expect(positionRuns(runs).map(streamAsked)).toEqual(['feature/example-stream'])
  })

  test('no stream matches the branch: the pane says this session drives none, no band, no position run', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, { status: statusOver([featureOf('feature/other-stream')]) })
    await $.session.start(START)
    expect(positionRuns(runs)).toEqual([])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: 'This session drives no stream.' })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: 'No live stream nearby.' })).toBeDefined()
    await pane.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ key: 'open-hud' })).toBeUndefined()
    await band.unmount()
  })

  // A session drives the stream it writes to, which need not be the checkout's: an epic's
  // planning stream has no branch, and parallel sessions on one project drive different streams.
  test('the stream this session drives wins over the checked-out branch, in one status call', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, { status: statusOver([featureOf('epic-example'), EXAMPLE_FEATURE], { [SESSION_ID]: 'epic-example' }) })
    await $.session.start(START)
    expect(statusRuns(runs).length).toBe(1)
    expect(statusRuns(runs)[0]).toContain(`--session=${SESSION_ID}`)
    expect(statusRuns(runs)[0]).toContain(`--branch=${EXAMPLE_STREAM}`)
    expect(positionRuns(runs).map(streamAsked)).toEqual(['epic-example'])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Text', text: /epic-example/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /feat\/example-stream/ })).toBeUndefined()
    await band.unmount()
  })

  for (const [session, stream] of [['session-a', 'epic-example'], ['session-b', 'feat/other-stream']] as const) {
    test(`parallel sessions on one checkout: ${session} sees the stream it drives`, async ($, on) => {
      engineWorld(on, { sessionId: session })
      // one journal, two sessions writing to different streams; status answers per --session
      const features = [featureOf('epic-example'), featureOf('feat/other-stream'), EXAMPLE_FEATURE]
      const { runs } = journaledWorld(on, { status: statusOver(features, { 'session-a': 'epic-example', 'session-b': 'feat/other-stream' }) })
      await $.session.start(START)
      expect(positionRuns(runs).map(streamAsked)).toEqual([stream])
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: new RegExp(stream.replace('/', '\\/')) })).toBeDefined()
      await band.unmount()
    })
  }

  test('a journal.py older than this HUD: the pane names the minimum shipgate version, never a guessed stream', async ($, on) => {
    engineWorld(on)
    const { faulted } = journalFaults(on, argv => (argv.includes('position') ? exits(usageError("argument COMMAND: invalid choice: 'position' (choose from 'init', 'append', 'status')")) : null))
    journaledWorld(on)
    await $.session.start(START)
    expect(positionRuns(faulted).length).toBe(1)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: new RegExp(`does not know position: this HUD needs shipgate ${MIN_SHIPGATE_VERSION.replace(/\./g, '\\.')} or later`) })).toBeDefined()
    await pane.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ key: 'open-hud' })).toBeUndefined()
    await band.unmount()
  })

  test('a journal.py that refuses --session asks nothing more: the version message, not a branch fallback', async ($, on) => {
    engineWorld(on)
    const { faulted } = journalFaults(on, argv => (flagValues(argv, 'session').length > 0 ? exits(usageError('unrecognized arguments: --session=session-a')) : null))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    // the one status call was refused, and nothing was asked after it
    expect(statusRuns(faulted).length).toBe(1)
    expect(statusRuns(runs)).toEqual([])
    expect(positionRuns(runs)).toEqual([])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /does not know --session=session-a: this HUD needs shipgate/ })).toBeDefined()
    await pane.unmount()
  })

  test('a status call that fails for another reason shows the error, not a fallback', async ($, on) => {
    engineWorld(on)
    const { faulted } = journalFaults(on, argv => (argv.includes('status') ? exits(exited(1, 'journal database not found')) : null))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    expect(statusRuns(faulted).length).toBe(1)
    expect(runs.filter(argv => argv[0] === 'python3')).toEqual([])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /journal database not found/ })).toBeDefined()
    await pane.unmount()
  })

  // D1: python3 exits 2 for a script file it cannot open, as argparse does for an unknown flag;
  // only argparse's usage text makes an exit 2 a version mismatch.
  test('D1: an exit 2 without argparse\'s usage text is a failed run, not an older journal.py', async ($, on) => {
    engineWorld(on)
    journalFaults(on, () => exits(exited(2, "python3: can't open file '/x/shipgate/scripts/journal.py': [Errno 2] No such file or directory\n")))
    journaledWorld(on)
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /journal\.py exited 2: python3: can't open file/ })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: /this HUD needs shipgate/ })).toBeUndefined()
    await pane.unmount()
  })

  test('journal.py moved by a plugin update: a run that exits with the script gone searches again and runs the new one', async ($, on) => {
    engineWorld(on)
    mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg' })
    const NEW = '/cfg/plugins/cache/market/shipgate/0.18.0/scripts/journal.py'
    let isMoved = false
    on('fs.exists', { path: /journal\.py$/ }, async (_$, e) => ({ value: isMoved ? e.path === NEW : !e.path.startsWith('/cfg/') }))
    on('fs.list', async (_$, e) => {
      if (e.path === '/cfg/plugins/cache') return { value: [dir('market')] }
      if (e.path === '/cfg/plugins/cache/market/shipgate') return { value: [dir('0.18.0')] }
      return { deny: 'no such directory' }
    })
    const { faulted } = journalFaults(on, argv => (isMoved && argv[1] !== NEW ? exits(exited(2, `python3: can't open file '${argv[1] ?? ''}': [Errno 2] No such file or directory`)) : null))
    const { runs } = journaledWorld(on)
    appendWorld(on)
    await $.session.start(START)
    const before = statusRuns(runs)[0]?.[1]
    expect(before).toMatch(/shipgate-hud\/\.\.\/shipgate\/scripts\/journal\.py$/)
    isMoved = true
    await refreshByAppend($)
    // the old path exited (python3 could not open it); the search found the new one, and the refresh ran it
    expect(statusRuns(faulted).map(argv => argv[1])).toEqual([before])
    expect(statusRuns(runs).map(argv => argv[1])).toEqual([before, NEW])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Text', text: /feat\/example-stream/ })).toBeDefined()
    await band.unmount()
  })

  test('a shell cd into a nested repo does not move the HUD: sidecar, journal, branch and writes stay anchored on the session root', async ($, on) => {
    const { opened } = engineWorld(on, { shell: `${START.cwd}/source/svc` }) // the shell stepped into a nested repo
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } }))
    // the root is an umbrella on a branch with no stream; the nested repo carries it
    const checkout = checkoutWorld(on, START.cwd, { 'svc-a': EXAMPLE_STREAM })
    const { runs, cwds, asked } = journaledWorld(on, { branch: checkout.branch })
    await $.session.start(START)
    expect(opened).toEqual(['shipgate-hud'])
    // the sidecar was looked for from the root, never from the shell's directory
    expect(asked.filter(p => p.endsWith('/.claude/shipgate.json'))).toEqual([`${START.cwd}/.claude/shipgate.json`])
    // the nested repo was found by an absolute check under the root, and probed from the root
    expect(checkout.asked).toContain(`${START.cwd}/svc-a/.git`)
    expect(gitDirs(runs)).toEqual(['svc-a'])
    // every git and journal.py run happened in the root
    expect(cwds.every(cwd => cwd === START.cwd)).toBe(true)
    // the root's branch named nothing; the one nested branch named one live stream
    expect(statusRuns(runs).map(argv => argv.slice(2))).toEqual([
      ['status', '--json', `--session=${SESSION_ID}`, '--branch=main'],
      ['status', '--json', `--nested-branch=${EXAMPLE_STREAM}`],
    ])
    // a relative write path resolves where the tool resolves it (the shell's directory) and is matched against the root
    const refreshes = () => positionRuns(runs).length
    const before = refreshes()
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-cd', file_path: '../../plugin/docs/prd/example-stream.worklog.md', content: '' })
    expect(refreshes()).toBe(before + 1)
  })

  test('a session inside a nested repo of an umbrella: the sidecar above is found, the journal runs there, artifacts read from there', async ($, on) => {
    const nested = `${START.cwd}/source/svc`
    engineWorld(on, { root: nested })
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } }))
    const { runs, cwds, reads, asked } = journaledWorld(on, { sidecarDir: START.cwd })
    const ran = (): { argv: string[]; cwd: string | undefined }[] => runs.map((argv, index) => ({ argv, cwd: cwds[index] }))
    await $.session.start({ ...START, cwd: nested })
    // the sidecar was looked for in the session directory first, then upward
    expect(asked.filter(p => p.endsWith('/.claude/shipgate.json'))).toEqual([`${nested}/.claude/shipgate.json`, `${START.cwd}/source/.claude/shipgate.json`, `${START.cwd}/.claude/shipgate.json`])
    // journal.py ran in the project root, git in the session root (here the nested repo)
    expect(ran().filter(r => r.argv[0] === 'python3').map(r => r.cwd)).toEqual([START.cwd, START.cwd])
    expect(ran().find(r => r.argv[0] === 'git')?.cwd).toBe(nested)
    // every artifact was read under the project root, none under the nested repo
    expect(reads.every(p => p.startsWith(`${START.cwd}/`) && !p.startsWith(`${nested}/`))).toBe(true)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
    await pane.unmount()
    // a write into the umbrella's artifact home triggers a refresh; one into the nested repo's own tree does not
    const before = statusRuns(runs).length
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-nested-1', file_path: 'src/app.ts', content: '' })
    expect(statusRuns(runs).length).toBe(before)
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-nested-2', file_path: `${START.cwd}/plugin/docs/prd/example.worklog.md`, content: '' })
    expect(statusRuns(runs).length).toBe(before + 1)
    // a write given relative to the nested session dir with ../ reaches the umbrella's artifact home
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-up', file_path: '../../plugin/docs/prd/example-stream.worklog.md', content: '' })
    expect(statusRuns(runs).length).toBe(before + 2)
  })

  test('a worklog the journal found by its name is read and drawn as found by its name', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, { position: stream => ({ ...EXAMPLE_POSITION, stream, artifacts: { ...EXAMPLE_POSITION.artifacts, worklog_from: 'name' } }) })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: 'docs/prd/example.worklog.md · found by its name' })).toBeDefined()
    await pane.unmount()
  })

  test('an umbrella: the session directory is no git repo, one live stream among the nested branches binds, a dormant one does not count', async ($, on) => {
    engineWorld(on)
    // a repo, one beside it on a dormant stream, a worktree inside the first and one beside the
    // repos (each on a branch of no stream); no `source/` or `packages/`
    const checkout = checkoutWorld(on, START.cwd, {
      older: 'feat/older-stream',
      service: EXAMPLE_STREAM,
      'service/.worktrees/wt-inside': 'feat/wt-inside',
      '.worktrees/wt-beside': 'feat/wt-beside',
    })
    const dormant: FeatureJson = { ...featureOf('feat/older-stream'), lifecycle: 'dormant', last_event: { ts: '2026-09-01T09:30:00+00:00' } }
    const { runs } = journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, dormant]), branch: path => (path === null ? 'HEAD' : checkout.branch(path)) })
    await $.session.start(START)
    // every nested repo's branch was asked for — a repo, its worktrees, then the parent's
    expect(gitDirs(runs)).toEqual(['older', 'service', 'service/.worktrees/wt-inside', '.worktrees/wt-beside'])
    // the session is asked first (the root has no branch), then every nested branch in one call
    expect(statusRuns(runs).map(argv => argv.slice(2))).toEqual([
      ['status', '--json', `--session=${SESSION_ID}`],
      ['status', '--json', '--nested-branch=feat/older-stream', `--nested-branch=${EXAMPLE_STREAM}`, '--nested-branch=feat/wt-inside', '--nested-branch=feat/wt-beside'],
    ])
    expect(positionRuns(runs).map(streamAsked)).toEqual([EXAMPLE_STREAM])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('implement')
    await band.unmount()
  })

  // The repros of problems 1 and 2, inverted: a session at an umbrella root that wrote to no
  // stream. The umbrella root is a repo on `main` (no stream). Four nested checkouts sit on
  // branches with live streams. An issue worktree of the umbrella (`.worktrees/<name>`,
  // detached) holds a fifth repo on the newest stream.
  describe('repro: an umbrella session that drives no stream', () => {
    const STREAMS: Readonly<Record<string, string>> = {
      'feat/stream-a': '2026-10-01T15:27:00+00:00',
      'feat/stream-b': '2026-10-01T13:36:00+00:00',
      'feat/stream-c': '2026-10-01T12:32:00+00:00',
      'feat/stream-d': '2026-10-01T11:37:00+00:00',
      'feat/stream-e': '2026-10-01T22:10:00+00:00', // the newest, in the issue worktree only
    }
    // the branch each checkout answers `git -C <dir> rev-parse` with; HEAD is a detached checkout
    const REPOS: Readonly<Record<string, string>> = {
      '.worktrees/issue-e': 'HEAD',
      '.worktrees/issue-e/source/svc-a': 'feat/stream-e',
      'source/svc-a': 'feat/stream-a',
      'source/svc-b': 'main',
      'source/svc-b/.worktrees/b-wt': 'feat/stream-b',
      'source/svc-c': 'feat/stream-c',
      'source/svc-d': 'feat/stream-d',
    }

    /** The live streams as journal.py lists them, read on every status run (so a test can move one); `authorized` publish. */
    const featuresOf = (streams: Readonly<Record<string, string>>, authorized: readonly string[] = []): FeatureJson[] =>
      Object.entries(streams).map(([stream, ts]) => ({ ...featureOf(stream, authorized.includes(stream) ? AUTHORIZED : { kind: 'held' }), last_event: { ts } }))

    /** The umbrella world; `streams` is read on every status run, so a test can move a stream. */
    const umbrellaWorld = (on: On, streams: Record<string, string>, authorized: readonly string[] = [], root = START.cwd) => {
      const checkout = checkoutWorld(on, root, root === START.cwd ? REPOS : { 'source/svc-a': 'feat/stream-e' }, root === START.cwd ? 'main' : 'HEAD')
      return journaledWorld(on, {
        // journal.py marks no stream for this session: it wrote to none
        status: argv => statusOver(featuresOf(streams, authorized))(argv),
        position: stream => ({ ...EXAMPLE_POSITION, stream, publish: authorized.includes(stream) ? AUTHORIZED : { kind: 'held' } }),
        branch: checkout.branch,
      })
    }

    test('problem 1: the session binds nothing, the pane names the nearby live streams, and a moving stream changes nothing', async ($, on) => {
      engineWorld(on)
      const streams = { ...STREAMS }
      const { runs } = umbrellaWorld(on, streams)
      appendWorld(on)
      await $.session.start(START)
      // the session call came first, with the root's own branch, and marked nothing; then one call with every nested branch
      expect(statusRuns(runs).map(argv => argv.slice(2))).toEqual([
        ['status', '--json', `--session=${SESSION_ID}`, '--branch=main'],
        ['status', '--json', '--nested-branch=feat/stream-a', '--nested-branch=feat/stream-b', '--nested-branch=feat/stream-c', '--nested-branch=feat/stream-d'],
      ])
      // the issue worktree is detached and is not walked below: its repo is not this session's
      expect(gitDirs(runs)).toContain('.worktrees/issue-e')
      expect(gitDirs(runs)).not.toContain('.worktrees/issue-e/source/svc-a')
      // four live matches bind nothing: no position, no band
      expect(positionRuns(runs)).toEqual([])
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ key: 'open-hud' })).toBeUndefined()
      await band.unmount()
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await pane.find({ type: 'Text', text: 'This session drives no stream.' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: '4 live streams nearby, named by this checkout:' })).toBeDefined()
      for (const stream of ['feat/stream-a', 'feat/stream-b', 'feat/stream-c', 'feat/stream-d']) expect(await pane.find({ type: 'Text', text: `  ${stream}` })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: /feat\/stream-e/ })).toBeUndefined()
      await pane.unmount()
      // another session moves stream B; the next refresh still binds nothing
      streams['feat/stream-b'] = '2026-10-01T15:40:00+00:00'
      await refreshByAppend($, 'other-moved')
      expect(positionRuns(runs)).toEqual([])
      const after = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await after.find({ key: 'open-hud' })).toBeUndefined()
      await after.unmount()
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await again.find({ type: 'Text', text: 'This session drives no stream.' })).toBeDefined()
      await again.unmount()
    })

    const gateWorld = (on: On, answer = 'Refuse'): { asked: string[] } => {
      const asked: string[] = []
      on('tool.check', { tool: 'Bash' }, async () => ({ decision: 'allow' as const, reason: 'beneath' }))
      on('tool.call', { tool: 'AskUserQuestion' }, async (_$, e) => {
        const question = String(listOf(recordOf(e)?.['questions'])?.map(recordOf)[0]?.['question'] ?? '')
        asked.push(question)
        return { result: { answers: { [question]: answer } } }
      })
      return { asked }
    }

    test('problem 2: a push from a nested repo is held against the stream of the branch it publishes', async ($, on) => {
      engineWorld(on)
      const { runs } = umbrellaWorld(on, { ...STREAMS })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const verdict = await $.tool.check({ tool: 'Bash', input: { command: 'git -C source/svc-d push' } })
      // the HEAD of the directory the command runs in, resolved against the shell's directory
      expect(gitDirs(runs).at(-1)).toBe(`${START.cwd}/source/svc-d`)
      expect(statusRuns(runs).at(-1)?.slice(2)).toEqual(['status', '--json', '--branch=feat/stream-d'])
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('feat/stream-d')
      expect(asked[0]).not.toContain('feat/stream-a')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('feat/stream-d')
    })

    test('problem 2: a push from a nested repo whose stream is authorized passes, whatever the other streams say', async ($, on) => {
      engineWorld(on)
      umbrellaWorld(on, { ...STREAMS }, ['feat/stream-d'])
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await $.tool.check({ tool: 'Bash', input: { command: 'cd source/svc-d && git push' } })).toMatchObject({ decision: 'allow', reason: 'beneath' })
      expect(asked).toEqual([])
    })

    test('an issue-worktree session: its nested repos sit on one branch, so it binds that stream before its first write', async ($, on) => {
      const root = `${START.cwd}/.worktrees/issue-e`
      engineWorld(on, { root })
      const { runs } = umbrellaWorld(on, { ...STREAMS }, [], root)
      await $.session.start({ ...START, cwd: root })
      // the worktree is detached (no --branch); its one nested branch names one live stream
      expect(statusRuns(runs).map(argv => argv.slice(2))).toEqual([
        ['status', '--json', `--session=${SESSION_ID}`],
        ['status', '--json', '--nested-branch=feat/stream-e'],
      ])
      expect(positionRuns(runs).map(streamAsked)).toEqual(['feat/stream-e'])
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /feat\/stream-e/ })).toBeDefined()
      await band.unmount()
    })

    // D1: a failed nested probe was skipped, and the session read as driving no stream; the gate then passed.
    test('D1: a nested status call that fails is a failed refresh, not an unbound session, and the gate holds', async ($, on) => {
      engineWorld(on)
      journalFaults(on, argv => (flagValues(argv, 'nested-branch').length > 0 ? exits(exited(1, 'sqlite3.OperationalError: database is locked')) : null))
      umbrellaWorld(on, { ...STREAMS })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await pane.find({ type: 'Text', text: /refresh failed — journal\.py exited 1: sqlite3\.OperationalError: database is locked/ })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'This session drives no stream.' })).toBeUndefined()
      await pane.unmount()
      // the push publishes `main`, which has no stream: the bound stream decides, and it could not be read
      const verdict = await $.tool.check({ tool: 'Bash', input: { command: 'git push' } })
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('database is locked')
      expect(verdict.decision).toBe('deny')
    })
  })

  test('a Write into a configured artifact home triggers a refresh; one elsewhere does not', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } }))
    await $.session.start(START)
    const count = () => statusRuns(runs).length
    const before = count()
    await $.tool.call({ tool: 'Write', tool_use_id: 'w1', file_path: 'src/app.ts', content: '' })
    expect(count()).toBe(before)
    // the sidecar's homes are `*/docs/prd/*.md`, merged over shipgate's defaults: a plugin-scoped PRD matches …
    await $.tool.call({ tool: 'Write', tool_use_id: 'w2', file_path: 'plugin/docs/prd/example.worklog.md', content: '' })
    expect(count()).toBe(before + 1)
    // … an absolute path is made relative to the session directory first …
    await $.tool.call({ tool: 'Write', tool_use_id: 'w3', file_path: `${START.cwd}/plugin/docs/adr/0002-x.md`, content: '' })
    expect(count()).toBe(before + 2)
    // … and a path outside the project never matches, however it ends
    await $.tool.call({ tool: 'Write', tool_use_id: 'w4', file_path: '/elsewhere/plugin/docs/prd/x.md', content: '' })
    expect(count()).toBe(before + 2)
  })

  // R1-F4: an absolute path that climbed above `/` normalized to `..`, never to a path under the project.
  test('R1-F4: a written absolute path that climbs above / stops at /, as POSIX does', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } }))
    await $.session.start(START)
    const before = statusRuns(runs).length
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-root', file_path: `/../..${START.cwd}/plugin/docs/prd/example.md`, content: '' })
    expect(statusRuns(runs).length).toBe(before + 1)
  })

  test('a sidecar home whose class cannot be built is skipped: the homes after it still trigger, and the hook does not fail', async ($, on) => {
    engineWorld(on)
    // `[z-a]` is a range out of order: no RegExp can be built from it, nor from `[^z-a]`, whose
    // `^` is itself (R1-F6); `later` is a home after them
    const homes = { ...SIDECAR.artifact_homes, notes: 'notes/[z-a]*.md', caret: 'caret/[^z-a]*.md', later: 'later/*.md' }
    on('fs.read', { path: /\.claude\/shipgate\.json$/ }, async () => ({ value: JSON.stringify({ ...SIDECAR, artifact_homes: homes }) }))
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: 'written' } }))
    await $.session.start(START)
    const before = statusRuns(runs).length
    // a path only the bad home could name: the write lands, no refresh
    const written = await $.tool.call({ tool: 'Write', tool_use_id: 'w-bad', file_path: 'notes/b.md', content: '' })
    expect(written).toMatchObject({ result: { filePath: 'x', content: 'written' } })
    expect(statusRuns(runs).length).toBe(before)
    const caret = await $.tool.call({ tool: 'Write', tool_use_id: 'w-caret', file_path: 'caret/b.md', content: '' })
    expect(caret).toMatchObject({ result: { filePath: 'x', content: 'written' } })
    expect(statusRuns(runs).length).toBe(before)
    // a path in the home after it: the bad home is skipped, not thrown on, so this one is reached
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-later', file_path: 'later/x.md', content: '' })
    expect(statusRuns(runs).length).toBe(before + 1)
  })

  test('refresh requests during a refresh coalesce into one trailing run', async ($, on) => {
    engineWorld(on)
    let release: () => void = () => {}
    const held = new Promise<void>(resolve => {
      release = resolve
    })
    let isHolding = false
    on('process.run', { argv: ['python3'] }, async (_$, e, next) => {
      if (isHolding && e.argv.includes('status')) {
        isHolding = false
        await held
      }
      return next(e)
    })
    const { runs } = journaledWorld(on)
    appendWorld(on)
    await $.session.start(START)
    const before = statusRuns(runs).length
    isHolding = true
    // three appends while the first refresh is held on its status run
    const calls = [refreshByAppend($, 'a1'), refreshByAppend($, 'a2'), refreshByAppend($, 'a3')]
    await sleep(20)
    release()
    await Promise.all(calls)
    // one run for the first request, one trailing run for the two that arrived meanwhile
    expect(statusRuns(runs).length).toBe(before + 2)
  })

  test('a resume in a session that never had a surface runs nothing', async ($, on) => {
    engineWorld(on, { surfaces: [] })
    on('classic.SessionStart', async () => ({}))
    const { runs } = journaledWorld(on)
    await $.session.start({ ...START, surface: null })
    await $.classic.SessionStart({ source: 'resume' })
    expect(runs).toEqual([])
  })

  test('a session with no surface runs nothing', async ($, on) => {
    engineWorld(on, { surfaces: [] })
    const { runs } = journaledWorld(on)
    await $.session.start({ ...START, surface: null })
    expect(runs).toEqual([])
  })

  test('after /clear the position is detected and refreshed again', async ($, on) => {
    engineWorld(on)
    on('classic.SessionStart', async () => ({}))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    const before = statusRuns(runs).length
    await $.classic.SessionStart({ source: 'clear' })
    expect(statusRuns(runs).length).toBe(before + 1)
  })

  test('journal.py found in the plugin cache: newest version wins', async ($, on) => {
    engineWorld(on)
    on('fs.exists', { path: /journal\.py$/ }, async (_$, e) => ({ value: e.path.endsWith('/shipgate/0.14.1/scripts/journal.py') }))
    on('fs.list', async (_$, e) => {
      if (e.path?.endsWith('/shipgate')) return { value: [dir('0.9.0'), dir('0.14.1'), dir('0.13.6')] }
      return { deny: 'no such directory' }
    })
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    expect(statusRuns(runs)[0]?.[1]).toMatch(/\/shipgate\/0\.14\.1\/scripts\/journal\.py$/)
  })

  test('a linked plugin folder: journal.py is found beside where the link lands', async ($, on) => {
    engineWorld(on)
    on('fs.stat', async (_$, e) => {
      if (e.path.endsWith('/shipgate-hud')) return { value: { kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: true, realPath: '/real/pandora/shipgate-hud' } }
      return { deny: 'ENOENT' }
    })
    // the engine may hand the hook the path normalized (`..` folded) or as the plugin spelled it
    on('fs.exists', { path: /journal\.py$/ }, async (_$, e) => ({ value: /^\/real\/pandora\/(shipgate-hud\/\.\.\/)?shipgate\/scripts\/journal\.py$/.test(e.path) }))
    on('fs.list', async () => ({ deny: 'no such directory' }))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    expect(statusRuns(runs)[0]?.[1]).toBe('/real/pandora/shipgate-hud/../shipgate/scripts/journal.py')
  })

  test('nothing beside the plugin: journal.py is found in the config directory\'s plugin cache', async ($, on) => {
    engineWorld(on)
    mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/someone' })
    on('fs.stat', async () => ({ deny: 'ENOENT' }))
    on('fs.exists', { path: /journal\.py$/ }, async (_$, e) => ({ value: e.path === '/cfg/plugins/cache/pandora/shipgate/0.14.1/scripts/journal.py' }))
    on('fs.list', async (_$, e) => {
      if (e.path === '/cfg/plugins/cache') return { value: [dir('other-market'), dir('pandora')] }
      if (e.path === '/cfg/plugins/cache/pandora/shipgate') return { value: [dir('0.13.6'), dir('0.14.1')] }
      return { deny: 'no such directory' }
    })
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    expect(statusRuns(runs)[0]?.[1]).toBe('/cfg/plugins/cache/pandora/shipgate/0.14.1/scripts/journal.py')
  })

  test('journal.py missing everywhere: the pane says so and the band stays empty', async ($, on) => {
    engineWorld(on)
    const runs: string[][] = []
    on('fs.exists', async (_$, e) => ({ value: e.path.endsWith('.claude/shipgate.json') }))
    on('fs.stat', async () => ({ deny: 'ENOENT' }))
    mock.env(on, {})
    on('fs.list', async () => ({ deny: 'no such directory' }))
    on('process.run', async (_$, e) => {
      runs.push([...e.argv])
      return ok('')
    })
    await $.session.start(START)
    expect(runs).toEqual([])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /cannot find/ })).toBeDefined()
    await pane.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ key: 'open-hud' })).toBeUndefined()
    await band.unmount()
  })

  // D3: a cut while looking for journal.py read as "not found", and the gate passed.
  test('D3: a search for journal.py the person cut is a cut, not "journal.py not found"', async ($, on) => {
    engineWorld(on)
    on('fs.exists', { path: /\/shipgate\/scripts\/journal\.py$/ }, async () => ({ deny: '$.fs.exists(journal.py) aborted' }))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    expect(runs).toEqual([])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /cannot find/ })).toBeUndefined()
    await pane.unmount()
  })

  test('a journal.py run that exits non-zero is an error even when its message ends in aborted', async ($, on) => {
    engineWorld(on)
    journalFaults(on, () => exits(exited(1, 'stream fix/aborted-run: journal (fix/aborted-run) aborted')))
    journaledWorld(on)
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /shipgate-hud: .*\(fix\/aborted-run\) aborted/ })).toBeDefined()
    await pane.unmount()
  })

  test('a refresh the person cut (an aborted process run) shows no error and keeps the position', async ($, on) => {
    engineWorld(on)
    // a journal.py run that fails on demand, registered above the journaled world's answers
    let failure: string | null = null
    journalFaults(on, () => (failure === null ? null : rejects(failure)))
    const { runs } = journaledWorld(on)
    appendWorld(on)
    await $.session.start(START)
    failure = CUT_RUN
    await refreshByAppend($, 'cut-1')
    let pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /shipgate-hud:/ })).toBeUndefined()
    expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
    await pane.unmount()
    // any other failure still shows, above the position read before it
    failure = 'journal database is locked'
    await refreshByAppend($, 'cut-2')
    pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /journal database is locked/ })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
    await pane.unmount()
    expect(runs.length).toBeGreaterThan(0)
  })

  describe('publish gate', () => {
    const BENEATH = { decision: 'allow' as const, reason: 'beneath' }
    const REFUSE = 'Refuse'
    const ONCE = 'Let it through once'
    type Answer = { label: string } | 'dismiss'

    /** The question an AskUserQuestion call carries. */
    const questionOf = (e: unknown): string => String(listOf(recordOf(e)?.['questions'])?.map(recordOf)[0]?.['question'] ?? '')

    /** The engine's verdict beneath the plugin, and the dialog answered with `answer`; the questions asked are recorded. */
    const gateWorld = (on: On, answer: Answer = { label: REFUSE }): { asked: string[] } => {
      const asked: string[] = []
      on('tool.check', { tool: 'Bash' }, async () => BENEATH)
      on('tool.call', { tool: 'AskUserQuestion' }, async (_$, e) => {
        const question = questionOf(e)
        asked.push(question)
        return answer === 'dismiss' ? { deny: 'dismissed' } : { result: { answers: { [question]: answer.label } } }
      })
      return { asked }
    }

    const check = ($: Engine, command: string) => $.tool.check({ tool: 'Bash', input: { command } })

    /** A journal whose example stream is reviewed: the status brief and the position both say authorized. */
    const REVIEWED = {
      status: statusOver([featureOf(EXAMPLE_STREAM, AUTHORIZED)]),
      position: (stream: string): PositionJson => ({ ...EXAMPLE_POSITION, stream, publish: AUTHORIZED }),
    }

    test('no sidecar: a push passes to the verdict beneath, no process runs, nobody is asked', async ($, on) => {
      engineWorld(on)
      const { runs } = bareWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(runs).toEqual([])
      expect(asked).toEqual([])
    })

    test('an unreviewed stream: the push is held and the dialog names the stream and the command', async ($, on) => {
      engineWorld(on)
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const before = statusRuns(runs).length
      const verdict = await check($, 'cd x && git push -u origin feature/x')
      // a refresh for the session's own stream, then one status call for the branch the command publishes
      expect(statusRuns(runs).length).toBe(before + 2)
      expect(statusRuns(runs).at(-1)?.slice(2)).toEqual(['status', '--json', '--branch=feature/x'])
      // `feature/x` has no stream: the session's own decides
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('feat/example-stream')
      expect(asked[0]).toContain('git push')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('feat/example-stream')
      expect(verdict.reason).toContain('journal.py append --type review-verdict')
    })

    for (const [name, answer, decision] of [
      ['Refuse', { label: REFUSE }, 'deny'],
      ['free text', { label: 'Other text' }, 'deny'],
      ['a dismissed dialog', 'dismiss', 'deny'],
      ['Let it through once', { label: ONCE }, 'allow'],
    ] as const) {
      test(`an unreviewed stream, answered with ${name}: ${decision}`, async ($, on) => {
        engineWorld(on)
        journaledWorld(on)
        const { asked } = gateWorld(on, answer)
        await $.session.start(START)
        const verdict = await check($, 'gh pr create --fill')
        expect(asked.length).toBe(1)
        if (decision === 'allow') expect(verdict).toMatchObject(BENEATH)
        else expect(verdict.decision).toBe('deny')
      })
    }

    test('let through once is not remembered: the next push asks again', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const { asked } = gateWorld(on, { label: ONCE })
      await $.session.start(START)
      await check($, 'git push')
      await check($, 'git push')
      expect(asked.length).toBe(2)
    })

    test('a reviewed stream: the push passes to the verdict beneath without a dialog', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, REVIEWED)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
    })

    test('a command that publishes nothing: no refresh, no dialog', async ($, on) => {
      engineWorld(on)
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const before = runs.length
      expect(await check($, 'git pull')).toMatchObject(BENEATH)
      expect(await check($, 'gh pr list')).toMatchObject(BENEATH)
      expect(runs.length).toBe(before)
      expect(asked).toEqual([])
    })

    test('a journal that cannot be read: the push is held, the reason carries the error', async ($, on) => {
      engineWorld(on)
      journalFaults(on, () => exits(exited(1, 'journal database not found')))
      journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const verdict = await check($, 'git push')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('journal database not found')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('journal database not found')
    })

    test('no journal.py found: the push passes to the verdict beneath without a dialog', async ($, on) => {
      engineWorld(on)
      const runs: string[][] = []
      on('fs.exists', async (_$, e) => ({ value: e.path.endsWith('.claude/shipgate.json') }))
      on('fs.stat', async () => ({ deny: 'ENOENT' }))
      mock.env(on, {})
      on('fs.list', async () => ({ deny: 'no such directory' }))
      on('process.run', async (_$, e) => {
        runs.push([...e.argv])
        return ok('')
      })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
      expect(runs).toEqual([])
    })

    test('a session that draws nowhere: the push passes, no process runs, nobody is asked', async ($, on) => {
      engineWorld(on, { surfaces: [] })
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start({ ...START, surface: null })
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(runs).toEqual([])
      expect(asked).toEqual([])
    })

    // D5: the surface was a boolean only session.start set, so after a plugin reload (module
    // state empty, no session.start) the gate stayed open.
    test('D5: with no session.start since the module loaded, a session that draws still has its push held', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const { asked } = gateWorld(on)
      const verdict = await check($, 'git push')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('feat/example-stream')
      expect(verdict.decision).toBe('deny')
    })

    test('a worker subagent\'s push is held like the main loop\'s (FR-025)', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const agents: (string | undefined)[] = []
      on('tool.check', { tool: 'Bash' }, async (_$, e) => {
        agents.push(e.agentId)
        return BENEATH
      })
      const { asked } = gateWorld(on, { label: ONCE })
      await $.session.start(START)
      const verdict = await $.tool.check({ tool: 'Bash', input: { command: 'git push' }, agentId: 'worker-1' })
      expect(asked.length).toBe(1) // the person is asked in the main dialog
      expect(verdict).toMatchObject(BENEATH) // let through once
      expect(agents).toEqual(['worker-1']) // the call carried the worker's loop to the end
    })

    test('a reviewed stream whose refresh is cut: the push is held, never passed on the old position', async ($, on) => {
      engineWorld(on)
      let failure: string | null = null
      journalFaults(on, () => (failure === null ? null : rejects(failure)))
      journaledWorld(on, REVIEWED)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH) // reviewed: passes while the journal answers
      failure = CUT_RUN
      const verdict = await check($, 'git push')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('the journal read was cut before it finished')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('the journal read was cut before it finished')
    })

    test('D3: a search for journal.py the person cut holds the push, never passes it as "no journal.py"', async ($, on) => {
      engineWorld(on)
      on('fs.exists', { path: /\/shipgate\/scripts\/journal\.py$/ }, async () => ({ deny: '$.fs.exists(journal.py) aborted' }))
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      const verdict = await check($, 'git push')
      expect(runs).toEqual([])
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('the journal read was cut before it finished')
      expect(verdict.decision).toBe('deny')
    })

    test('no stream for this session and none for the branch: the push passes to the verdict beneath without a dialog', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, { status: statusOver([featureOf('feature/other-stream')]) })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
    })

    // D2: the gate read the band's stream, whatever branch the command published.
    test('D2: a bound session that publishes another branch is held against that branch\'s stream', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, featureOf('feat/other-stream')]) })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const verdict = await check($, 'git push origin feat/other-stream')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('stream feat/other-stream')
      expect(asked[0]).not.toContain('feat/example-stream')
      expect(verdict.reason).toContain('feat/other-stream')
    })

    test('D2: a held session that publishes a branch whose stream is authorized passes', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, featureOf('feat/other-stream', AUTHORIZED)]) })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push origin +refs/heads/feat/other-stream:feat/other-stream')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
    })

    /** The branches the gate read a target's stream for, in order: `status --branch` runs with no session and no nested branch. */
    const targetBranches = (runs: readonly string[][]): string[] =>
      statusRuns(runs)
        .filter(argv => flagValues(argv, 'session').length === 0 && flagValues(argv, 'nested-branch').length === 0)
        .flatMap(argv => [...flagValues(argv, 'branch')])

    /** Two streams beside the session's own: `feat/a-stream` authorized, `feat/b-stream` held. */
    const TWO_STREAMS = { status: statusOver([EXAMPLE_FEATURE, featureOf('feat/a-stream', AUTHORIZED), featureOf('feat/b-stream')]) }

    // R1-F1: the scan stopped at the first publish command, so the gate checked `a` and `b` published unchecked.
    for (const command of ['git push origin feat/a-stream && git push origin feat/b-stream', 'git push origin feat/a-stream; gh pr create --head feat/b-stream']) {
      test(`R1-F1: ${JSON.stringify(command)} is held, and the dialog names the second command's stream`, async ($, on) => {
        engineWorld(on)
        const { runs } = journaledWorld(on, TWO_STREAMS)
        const { asked } = gateWorld(on)
        await $.session.start(START)
        const before = runs.length
        const verdict = await check($, command)
        // one status call per branch the line publishes, in line order
        expect(targetBranches(runs.slice(before))).toEqual(['feat/a-stream', 'feat/b-stream'])
        expect(asked.length).toBe(1)
        expect(asked[0]).toContain('stream feat/b-stream')
        expect(asked[0]).not.toContain('feat/a-stream')
        expect(asked[0]).not.toContain('feat/example-stream')
        expect(verdict.decision).toBe('deny')
        expect(verdict.reason).toContain('feat/b-stream')
      })
    }

    // R2-N1: one "Let it through once" passes the whole line, but the dialog named the first held stream only.
    const TWO_HELD = { status: statusOver([EXAMPLE_FEATURE, featureOf('feat/a-stream'), featureOf('feat/b-stream')]) }
    const TWO_PUSHES = 'git push origin feat/a-stream && git push origin feat/b-stream'

    test('R2-N1: a line with two unreviewed streams: the dialog and the deny name both', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, TWO_HELD)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const verdict = await check($, TWO_PUSHES)
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('`git push` for stream feat/a-stream')
      expect(asked[0]).toContain('`git push` for stream feat/b-stream')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('stream feat/a-stream')
      expect(verdict.reason).toContain('stream feat/b-stream')
      expect(verdict.reason).not.toContain('--type gate-decision')
    })

    test('R2-N1: one "Let it through once", asked over both streams, lets the line through', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, TWO_HELD)
      const { asked } = gateWorld(on, { label: ONCE })
      await $.session.start(START)
      expect(await check($, TWO_PUSHES)).toMatchObject(BENEATH)
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('stream feat/a-stream')
      expect(asked[0]).toContain('stream feat/b-stream')
    })

    test('R1-F1: a line whose every publish is authorized passes without a dialog', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, featureOf('feat/a-stream', AUTHORIZED), featureOf('feat/b-stream', AUTHORIZED)]) })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push origin feat/a-stream && git push origin feat/b-stream')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
    })

    test('R1-F1: a branch two publishes name is read once', async ($, on) => {
      engineWorld(on)
      // every checkout is on feat/example-stream: the bare push publishes it too
      const { runs } = journaledWorld(on, REVIEWED)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const before = runs.length
      expect(await check($, 'git push && git push origin feat/example-stream && git push -u origin feat/example-stream && gh pr create --fill')).toMatchObject(BENEATH)
      expect(targetBranches(runs.slice(before))).toEqual(['feat/example-stream'])
      expect(asked).toEqual([])
    })

    // R1-F4: a path that climbed above `/` normalized to `..`, so `git -C ..` read the session root's parent.
    test('R1-F4: a `git -C` path that climbs above / stops at /, as POSIX does', async ($, on) => {
      engineWorld(on)
      const { runs } = journaledWorld(on)
      gateWorld(on)
      await $.session.start(START)
      await check($, 'git -C ../../../../x push')
      expect(gitDirs(runs).at(-1)).toBe('/x')
    })

    test('a target the gate cannot resolve falls back to the session\'s stream', async ($, on) => {
      engineWorld(on)
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      const before = statusRuns(runs).length
      await check($, 'git push --all')
      // the refresh only: `--all` names no one branch, so no status call for a target
      expect(statusRuns(runs).length).toBe(before + 1)
      expect(asked[0]).toContain('stream feat/example-stream')
    })

    // D4: the gate read two atoms in two awaits, and a parallel refresh could write between them.
    // It now decides from the value of the refresh that covers its own request.
    test('D4: a check during a refresh decides on the trailing refresh that covers it, never the one already running', async ($, on) => {
      engineWorld(on)
      let release: () => void = () => {}
      const held = new Promise<void>(resolve => {
        release = resolve
      })
      let isHolding = false
      // the position run of the refresh in flight reads the journal, then waits
      on('process.run', { argv: ['python3'] }, async (_$, e, next) => {
        if (!isHolding || !e.argv.includes('position')) return next(e)
        isHolding = false
        const answer = await next(e)
        await held
        return answer
      })
      let publish = AUTHORIZED
      journaledWorld(on, { position: stream => ({ ...EXAMPLE_POSITION, stream, publish }) })
      appendWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      isHolding = true
      const appended = refreshByAppend($) // reads the stream as authorized, then waits
      await sleep(20)
      publish = { kind: 'held' } // the journal moves on: the stream is held now
      // `--all` names no one branch: the session's own stream decides
      const verdict = check($, 'git push --all')
      await sleep(20)
      release()
      await appended
      expect((await verdict).decision).toBe('deny')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('stream feat/example-stream')
    })

    // D14: the hold named the stale stream when the refresh had failed, and told the model to record a verdict.
    test('D14: a stale position under a failed refresh: the hold names the failure, never the stale stream', async ($, on) => {
      engineWorld(on)
      let failure: string | null = null
      journalFaults(on, () => (failure === null ? null : exits(exited(1, failure))))
      journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start(START)
      failure = 'sqlite3.OperationalError: database is locked'
      // `--all` names no one branch: the session's own stream decides, and its refresh failed
      const verdict = await check($, 'git push --all')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('database is locked')
      expect(asked[0]).not.toContain('feat/example-stream')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('database is locked')
      expect(verdict.reason).not.toContain('append --type review-verdict')
      // the pane still draws the stale position, under the failure
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await pane.find({ type: 'Text', text: /database is locked/ })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: EXAMPLE_PLAN })).toBeDefined()
      await pane.unmount()
    })
  })

  describe('review board', () => {
    const LAUNCH_ID = 'toolu_01AAAAAAAAAAAAAAAAAAAAAA'
    // the counts' first line at the pane's 100 columns; `unverified 1 · open N` packs onto the next
    const COUNTS = 'found 9 · deduped 7 · candidates 5 · survivors 4 · killed 1 · below floor 2 · refuters 6/5'
    const OTHER_NOTIFICATION = '<task-notification>\n<task-id>b2</task-id>\n<tool-use-id>toolu_other</tool-use-id>\n<status>completed</status>\n<result>{"ok":true}</result>\n</task-notification>'
    const notify = (text: string): PromptSubmitInput => ({ text, origin: { kind: 'task-notification' }, wait: false })

    /** The review atom's shape tag: a stored value is `{ shape, value }`. */
    const REVIEW_SHAPE = 'shipgate-hud.review-v2'

    /**
     * What a capture needs beneath the plugin and nothing more: the surfaces the session draws
     * on, the clock, and the engine's answer to a prompt (each recorded). No session.start: the
     * view stays `Off`, so a return is captured under no stream.
     */
    const captureWorld = (on: On, surfaces: readonly RenderSurface[] = ['terminal']): { submitted: string[] } => {
      const submitted: string[] = []
      mock.clock(on)
      on('session.surfaces', async () => ({ value: surfaces }))
      on('prompt.submit', async (_$, e) => {
        submitted.push(e.text)
        return { text: e.text }
      })
      return { submitted }
    }

    /**
     * The task output file beneath the plugin: `fs.stat` and `fs.read` of any `.output` path are
     * recorded and answered here (the file for a path ending `/tasks/wabc.output`, else ENOENT).
     * Register it before `journaledWorld`, whose catch-all `fs.read` would answer first otherwise.
     */
    const outputWorld = (on: On, text: string = REVIEW_OUTPUT_FILE, size: number = text.length) => {
      const stats: string[] = []
      const reads: string[] = []
      on('fs.stat', { path: /\.output$/ }, async (_$, e) => {
        stats.push(e.path)
        return e.path.endsWith('/tasks/wabc.output') ? { value: { kind: 'file' as const, size, mtimeMs: 0, isLink: false } } : { deny: 'ENOENT' }
      })
      on('fs.read', { path: /\.output$/ }, async (_$, e) => {
        reads.push(e.path)
        return e.path.endsWith('/tasks/wabc.output') ? { value: text } : { deny: 'ENOENT' }
      })
      return { stats, reads }
    }

    /** The Workflow tool beneath the plugin: it launches in the background and names the run. */
    const workflowWorld = (on: On): void => {
      on('tool.call', { tool: 'Workflow' }, async () => ({ result: REVIEW_LAUNCH_RESULT }))
    }

    /**
     * Every value the plugin writes to its `review` atom, recorded beneath it and read through the
     * decoder (the test `$` has no state reader; a write is `{ shape, value }`); `rewrite` changes
     * the raw state that is stored. `last()` is the atom as it now stands; `writes()` counts them.
     */
    const reviewWatch = (on: On, rewrite: (value: unknown) => unknown = v => v) => {
      const values: ReviewState[] = []
      on('state.set', async (_$, e, next) => {
        const stored = e.plugin === 'shipgate-hud' && e.key === 'review' ? recordOf(e.value) : null
        const value = stored !== null && stored.shape === REVIEW_SHAPE ? rewrite(stored.value) : null
        if (value !== null) values.push(decodeReviewState(value))
        // cast: a test-kit event passed on, its review value rewritten; the engine's declared event type
        // re-maps the contract's branded numbers, so even the event as received does not type as `next`'s input
        return next((value === null ? e : { ...e, value: { shape: REVIEW_SHAPE, value } }) as never)
      })
      return { last: (): ReviewState | undefined => values.at(-1), writes: (): number => values.length }
    }

    const launchReview = ($: Engine, id: string = LAUNCH_ID, script = "export const meta = { name: 'shipgate-review' }") =>
      $.tool.call({ tool: 'Workflow', tool_use_id: id, script })

    // ── The capture path: a notification in, a stored round out. No bound stream needed. ──

    test('a review return becomes round 1, every survivor unmarked, the newest round open; the prompt passes on unchanged', async ($, on) => {
      const { submitted } = captureWorld(on)
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(submitted).toEqual([REVIEW_NOTIFICATION])
      const state = watch.last()
      expect(state?.boards.map(board => `${board.stream ?? '?'}:${board.round}`)).toEqual(['?:1'])
      expect(state?.boards[0]?.runId).toBeNull()
      expect(state?.boards[0]?.survivors.map(s => s.mark)).toEqual([null, null, null, null])
      expect(state?.boards[0]?.survivors.map(s => s.finding.verification)).toEqual(['held', 'refuters-died', 'unverified-cap', 'not-targeted'])
      expect(state?.open).toEqual({ kind: 'newest' })
    })

    test('D12: a return with a junk survivor makes no board, and the prompt passes on unchanged', async ($, on) => {
      const { submitted } = captureWorld(on)
      const watch = reviewWatch(on)
      const junk = notificationOf({ ...REVIEW_RETURN, survivors: [...REVIEW_RETURN.survivors, { severity: 'HIGH' }] })
      await $.prompt.submit(notify(junk))
      expect(submitted).toEqual([junk])
      expect(watch.writes()).toBe(0)
    })

    test('D11: a stored board of another shape is dropped at the read, and the next capture writes only what decodes', async ($, on) => {
      captureWorld(on)
      // the first write lands with its finding in an older build's shape: no `kind`, a text quorum
      let isFirst = true
      const watch = reviewWatch(on, value => {
        if (!isFirst) return value
        isFirst = false
        const state = recordOf(value)
        const board = recordOf(listOf(state?.boards)?.[0])
        const survivor = recordOf(listOf(board?.survivors)?.[0])
        return { ...state, boards: [{ ...board, survivors: [{ ...survivor, finding: { ...recordOf(survivor?.finding), kind: undefined, quorum: '0/2' } }] }] }
      })
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards).toEqual([])
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.survivors.length)).toEqual([4])
    })

    test('a noted launch stamps its run id; the same return delivered again replaces its round', async ($, on) => {
      captureWorld(on)
      workflowWorld(on)
      const watch = reviewWatch(on)
      await launchReview($)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => `${board.runId}:${board.round}`)).toEqual(['wf_0123abcd-ef0:1'])
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => `${board.runId}:${board.round}`)).toEqual(['wf_0123abcd-ef0:1'])
    })

    test('a launch that is not the review workflow is not noted: its return carries no run id', async ($, on) => {
      captureWorld(on)
      workflowWorld(on)
      const watch = reviewWatch(on)
      await launchReview($, LAUNCH_ID, "export const meta = { name: 'something-else' }")
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards[0]?.runId).toBeNull()
    })

    test('an id match alone never makes or replaces a board: the result must be the return', async ($, on) => {
      captureWorld(on)
      workflowWorld(on)
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.writes()).toBe(1)
      await launchReview($, 'toolu_other')
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      expect(watch.writes()).toBe(1) // no write: the old board stands unchanged
    })

    test('a sixth return drops the stream\'s oldest round, and a dropped number is never reused', async ($, on) => {
      captureWorld(on)
      const watch = reviewWatch(on)
      for (let i = 0; i < 6; i += 1) await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.round)).toEqual([6, 5, 4, 3, 2])
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.round)).toEqual([7, 6, 5, 4, 3])
    })

    test('a return cut in the notification is read whole from the task output file', async ($, on) => {
      const { submitted } = captureWorld(on)
      const { stats, reads } = outputWorld(on)
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(submitted).toEqual([REVIEW_NOTIFICATION_TRUNCATED]) // passed on unchanged
      expect(stats).toEqual([REVIEW_OUTPUT_PATH])
      expect(reads).toEqual([REVIEW_OUTPUT_PATH])
      expect(watch.last()?.boards[0]?.survivors.length).toBe(4)
    })

    for (const [name, path] of [
      ['a .. segment', '/tmp/project/.claude/tasks/../wabc.output'],
      ['no /tasks/ segment', '/tmp/project/.claude/wabc.output'],
      ['a relative path', 'tasks/wabc.output'],
    ] as const) {
      test(`an output-file path with ${name} is neither stat'ed nor read`, async ($, on) => {
        captureWorld(on)
        const { stats, reads } = outputWorld(on)
        const watch = reviewWatch(on)
        await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED.replace(`<output-file>${REVIEW_OUTPUT_PATH}</output-file>`, `<output-file>${path}</output-file>`)))
        expect(stats).toEqual([])
        expect(reads).toEqual([])
        expect(watch.writes()).toBe(0)
      })
    }

    test('an output file whose JSON lacks the return shape makes no board', async ($, on) => {
      captureWorld(on)
      const { reads } = outputWorld(on, JSON.stringify({ summary: 'x', result: { ok: true } }))
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(reads).toEqual([REVIEW_OUTPUT_PATH])
      expect(watch.writes()).toBe(0)
    })

    test('an output file that does not parse makes no board, and the prompt passes on', async ($, on) => {
      const { submitted } = captureWorld(on)
      outputWorld(on, '{"result": {"survivors": [')
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(submitted).toEqual([REVIEW_NOTIFICATION_TRUNCATED])
      expect(watch.writes()).toBe(0)
    })

    test('an output file over 4 MiB per stat is not read', async ($, on) => {
      captureWorld(on)
      const { stats, reads } = outputWorld(on, REVIEW_OUTPUT_FILE, 4 * 1024 * 1024 + 1)
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(stats).toEqual([REVIEW_OUTPUT_PATH])
      expect(reads).toEqual([])
      expect(watch.writes()).toBe(0)
    })

    for (const status of ['killed', 'failed'] as const) {
      test(`a ${status} review run is not captured`, async ($, on) => {
        const { submitted } = captureWorld(on)
        const watch = reviewWatch(on)
        const text = REVIEW_NOTIFICATION.replace('<status>completed</status>', `<status>${status}</status>`)
        await $.prompt.submit(notify(text))
        expect(submitted).toEqual([text])
        expect(watch.writes()).toBe(0)
      })
    }

    test('a session that draws nowhere captures nothing and passes the prompt on', async ($, on) => {
      const { submitted } = captureWorld(on, [])
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(submitted).toEqual([REVIEW_NOTIFICATION])
      expect(watch.writes()).toBe(0)
    })

    test('a notification that is no review return passes untouched; the return typed by the person is no notification', async ($, on) => {
      const { submitted } = captureWorld(on)
      const watch = reviewWatch(on)
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      await $.prompt.submit({ text: REVIEW_NOTIFICATION, origin: { kind: 'composer' }, wait: false })
      expect(submitted).toEqual([OTHER_NOTIFICATION, REVIEW_NOTIFICATION])
      expect(watch.writes()).toBe(0)
    })

    // ── The pane and the band over a bound stream (the journal world of T021–T023). ──

    test('a review launch and its notification fill the board, under the stream and the run', async ($, on) => {
      const { submitted } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      workflowWorld(on)
      await $.session.start(START)
      await launchReview($)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(submitted).toEqual([REVIEW_NOTIFICATION]) // passed on unchanged
      const state = watch.last()
      expect(state?.boards[0]?.stream).toBe('feat/example-stream')
      expect(state?.boards[0]?.runId).toBe('wf_0123abcd-ef0')
      expect(state?.boards[0]?.survivors.length).toBe(4)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ type: 'Text', text: ' 4 Review ' }))?.props.inverse).toBe(true)
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: '▎ BLOCKER' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: '95% · held 0/2 · correctness' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/api/handler.ts:42' })).toBeDefined()
      expect(await pane.find({ key: 'accept-0' })).toBeDefined()
      expect(await pane.find({ key: 'kill-3' })).toBeDefined()
      // killed and below-floor entries: a dim head, then the location and the summary as on a card
      expect(await pane.find({ type: 'Text', text: 'HIGH · q=2/2' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/parse.ts:10' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'HIGH · 40%' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/cache/store.ts:77' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'The cache key ignores the locale.' })).toBeDefined()
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review 4 open/ })).toBeDefined()
      await band.unmount()
    })

    test('an output file that does not parse shows no error in the pane', async ($, on) => {
      engineWorld(on)
      outputWorld(on, '{"result": {"survivors": [')
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await pane.find({ type: 'Text', text: /shipgate-hud:/ })).toBeUndefined()
      await pane.unmount()
    })

    test('two returns are two rounds: the newest open, the older folded behind its summary; a press swaps them', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Button', text: /^▾ round 2 · run \? · \d\d:\d\d$/ })).toBeDefined()
      expect((await pane.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · run \? · \d\d:\d\d · 4 survivors$/)
      // the open round's header is a button too, with the open chevron
      expect((await pane.find({ key: 'round-feat/example-stream:2' }))?.props.label).toMatch(/^▾ round 2 · /)
      await pane.press({ key: 'round-feat/example-stream:1' })
      expect(await pane.find({ type: 'Button', text: /^▾ round 1 · / })).toBeDefined()
      expect((await pane.find({ key: 'round-feat/example-stream:2' }))?.props.label).toMatch(/^▸ round 2 · /)
      // one board drawn, and the criteria once, after the rounds
      expect((await pane.findAll({ type: 'Text', text: COUNTS })).length).toBe(1)
      expect((await pane.findAll({ type: 'Text', text: 'SUCCESS CRITERIA' })).length).toBe(1)
      await pane.unmount()
    })

    test('the open round\'s header folds it: the body goes, the criteria stay; a second press opens it', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      const header = await pane.find({ key: 'round-feat/example-stream:1' })
      expect(header?.props.label).toMatch(/^▾ round 1 · /)
      expect(header?.props.plain).toBeFalsy()
      await pane.press({ key: 'round-feat/example-stream:1' })
      expect(watch.last()?.open).toEqual({ kind: 'folded' })
      expect((await pane.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · .* · 4 survivors$/)
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: '▎ BLOCKER' })).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: 'SUCCESS CRITERIA' })).toBeDefined()
      expect(await pane.find({ key: 'sc-SC-001' })).toBeDefined()
      await pane.press({ key: 'round-feat/example-stream:1' })
      expect(watch.last()?.open).toEqual({ kind: 'round', id: 'feat/example-stream:1' })
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      await pane.unmount()
      // a new return opens the newest round again
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.open).toEqual({ kind: 'newest' })
    })

    test('a mark stays on its round\'s board, and the prompt names the round', async ($, on) => {
      const { prompts } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'accept-0' })
      expect(prompts.at(-1)?.text).toContain('finding 1 of 4 in review round 1 (')
      expect(await pane.find({ type: 'Text', text: '✓ accepted' })).toBeDefined()
      await pane.unmount()
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      // round 2 opens with its own buttons; round 1's mark is not drawn on it
      expect(await again.find({ type: 'Text', text: '✓ accepted' })).toBeUndefined()
      expect(await again.find({ key: 'accept-0' })).toBeDefined()
      await again.press({ key: 'kill-1' })
      expect(prompts.at(-1)?.text).toContain('finding 2 of 4 in review round 2 (')
      expect(watch.last()?.boards.map(board => board.survivors.map(s => s.mark))).toEqual([
        [null, 'killed', null, null],
        ['accepted', null, null, null],
      ])
      await again.press({ key: 'round-feat/example-stream:1' })
      expect(await again.find({ type: 'Text', text: '✓ accepted' })).toBeDefined()
      expect(await again.find({ type: 'Text', text: '✗ killed' })).toBeUndefined()
      await again.unmount()
    })

    test('the band counts the newest round only', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'accept-0' })
      await pane.press({ key: 'kill-1' })
      await pane.unmount()
      const before = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await before.find({ type: 'Text', text: /review 2 open/ })).toBeDefined()
      await before.unmount()
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const after = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await after.find({ type: 'Text', text: /review 4 open/ })).toBeDefined()
      await after.unmount()
    })

    test('a round with no stream and a stream\'s round 1 get distinct keys and open on their own', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let branch = 'main' // no stream for this session yet
      journaledWorld(on, { branch: () => branch })
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION)) // round 1 of no stream
      branch = EXAMPLE_STREAM
      await refreshByAppend($)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION)) // round 1 of feat/example-stream
      expect(watch.last()?.boards.map(board => `${board.stream ?? '?'}:${board.round}`)).toEqual(['feat/example-stream:1', '?:1'])
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ key: 'round-?:1' }))?.props.label).toMatch(/^▸ round 1 · /)
      await pane.press({ key: 'accept-0' }) // on the open round: the stream's
      await pane.press({ key: 'round-?:1' })
      expect((await pane.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · /)
      // the stream round's mark is not drawn on the stream-less round 1
      expect(await pane.find({ type: 'Text', text: '✓ accepted' })).toBeUndefined()
      expect(watch.last()?.boards.map(board => board.survivors[0]?.mark)).toEqual(['accepted', null])
      await pane.unmount()
    })

    test('a dropped round takes its marks with it', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'accept-0' })
      await pane.unmount()
      expect(watch.last()?.boards[0]?.survivors[0]?.mark).toBe('accepted')
      for (let i = 0; i < 5; i += 1) await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.round)).toEqual([6, 5, 4, 3, 2])
      expect(watch.last()?.boards.flatMap(board => board.survivors.map(s => s.mark)).filter(mark => mark !== null)).toEqual([])
    })

    test('a tick made before a newer verdict no longer hides that verdict\'s unmet', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let verdict: PositionJson['verdict'] = null
      journaledWorld(on, { position: stream => ({ ...EXAMPLE_POSITION, stream, verdict }) })
      await $.session.start(START)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await pane.unmount()
      // the journal records a newer verdict: `position --json` names it
      verdict = { seq: 60, at: '2026-10-01T11:00:00+00:00', verdict: 'not-ready', criteria: { 'SC-001': 'unmet' }, dispositions: {} }
      await refreshByAppend($)
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect((await again.find({ key: 'sc-SC-001' }))?.props.label).toBe('☒')
      // a press now is made against the new verdict
      await again.press({ key: 'sc-SC-001' })
      expect((await again.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await again.unmount()
    })

    test('an aborted run: a warning under the counts, and the band says review aborted', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(notificationOf(REVIEW_RETURN_ABORTED)))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ type: 'Text', text: 'review aborted: no lens finder returned' }))?.props.color).toBe('warning')
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review aborted/ })).toBeDefined()
      expect(await band.find({ type: 'Text', text: /review \d+ open/ })).toBeUndefined()
      await band.unmount()
    })

    test('the board draws its run id and capture time; run ? without a noted launch', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      workflowWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Button', text: /^▾ round 1 · run \? · \d\d:\d\d$/ })).toBeDefined()
      await pane.unmount()
      await launchReview($)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      // the tab chosen stays chosen
      expect(await again.find({ type: 'Button', text: /^▾ round 2 · run wf_0123abcd-ef0 · \d\d:\d\d$/ })).toBeDefined()
      await again.unmount()
    })

    test('a return lands under the stream its launch ran on, not the one shown when it arrives', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let branch = EXAMPLE_STREAM
      journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, featureOf('feature/example-stream')]), branch: () => branch })
      const watch = reviewWatch(on)
      workflowWorld(on)
      await $.session.start(START)
      await launchReview($) // on feat/example-stream
      branch = 'feature/example-stream' // the session moves to feature/example-stream
      await refreshByAppend($) // a journal append refreshes the position; $.state is kept
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards[0]?.stream).toBe('feat/example-stream')
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: 'No review captured for feature/example-stream yet (phase implement).' })).toBeDefined()
      await pane.unmount()
    })

    test('a notification that is no review return leaves the board empty and the tab says so', async ($, on) => {
      const { submitted, prompts } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      expect(submitted).toEqual([OTHER_NOTIFICATION])
      expect(recordOf(prompts[0]?.['origin'])?.['kind']).toBe('task-notification')
      expect(watch.writes()).toBe(0)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: 'No review captured for feat/example-stream yet (phase implement).' })).toBeDefined()
      await pane.unmount()
    })

    test('Accept and Kill submit the named plain prompt, without asUser, and mark the card', async ($, on) => {
      const { prompts } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const board = watch.last()?.boards[0]
      if (board === undefined) throw new Error('no board captured')
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      const before = prompts.length
      await pane.press({ key: 'accept-0' })
      expect(prompts.length).toBe(before + 1)
      const accepted = prompts[before]
      expect(accepted?.text).toBe(findingPrompt('accepted', 0, board))
      expect(accepted?.asUser).toBeUndefined()
      expect(accepted?.text).toContain('finding 1 of 4 in review round 1 (BLOCKER, src/api/handler.ts:42, lens correctness)')
      expect(accepted?.text).not.toContain('permission check')
      expect(await pane.find({ type: 'Text', text: '✓ accepted' })).toBeDefined()
      expect(await pane.find({ key: 'accept-0' })).toBeUndefined()
      await pane.press({ key: 'kill-1' })
      const killed = prompts[before + 1]
      expect(killed?.text).toBe(findingPrompt('killed', 1, board))
      expect(killed?.asUser).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: '✗ killed' })).toBeDefined()
      expect(watch.last()?.boards[0]?.survivors.map(s => s.mark)).toEqual(['accepted', 'killed', null, null])
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review 2 open/ })).toBeDefined()
      await band.unmount()
    })

    test('the PRD criteria list as toggles; a press ticks and unticks', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
      expect((await pane.find({ key: 'sc-SC-002' }))?.props.label).toBe('☐')
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      expect(watch.last()?.ticks).toEqual([{ stream: 'feat/example-stream', criterion: 'SC-001', override: { state: 'on', seq: null } }])
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
      expect(watch.last()?.ticks).toEqual([])
      await pane.unmount()
    })

    test('a tick holds for its stream only', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let branch = EXAMPLE_STREAM
      journaledWorld(on, { status: statusOver([EXAMPLE_FEATURE, featureOf('feature/example-stream')]), branch: () => branch })
      await $.session.start(START)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await pane.unmount()
      branch = 'feature/example-stream' // another stream, the same PRD
      await refreshByAppend($) // a journal append refreshes the position; $.state is kept
      const other = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect((await other.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
      await other.unmount()
    })

    test('a board captured before any stream was known is drawn for the stream shown', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let branch = 'main' // no stream for this session yet
      journaledWorld(on, { branch: () => branch })
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards[0]?.stream).toBeNull()
      branch = EXAMPLE_STREAM
      await refreshByAppend($) // a journal append refreshes the position; $.state is kept
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      await pane.unmount()
    })

    test('a board held for another stream is not drawn, and the band counts nothing', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      // the board lands as if another stream had been current when it was captured
      reviewWatch(on, value => {
        const state = recordOf(value)
        return { ...state, boards: (listOf(state?.boards) ?? []).map(board => ({ ...recordOf(board), stream: 'feat/other-stream' })) }
      })
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: 'No review captured for feat/example-stream yet (phase implement).' })).toBeDefined()
      // the PRD's criteria still list beneath the line
      expect(await pane.find({ key: 'sc-SC-001' })).toBeDefined()
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review \d+ open/ })).toBeUndefined()
      await band.unmount()
    })
  })
})
