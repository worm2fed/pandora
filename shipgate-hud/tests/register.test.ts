import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { ADR, FEATURE_PREFIXED, LOG, SIDECAR, STATUS } from './fixtures'
import { BAND, PANE, SESSION_ID, START, bareWorld, engineWorld, journaledWorld, ok } from './world'
import { WORKLOG } from './fixtures'
import { REVIEW_LAUNCH_RESULT, REVIEW_NOTIFICATION, REVIEW_NOTIFICATION_TRUNCATED, REVIEW_OUTPUT_FILE, REVIEW_OUTPUT_PATH } from './fixtures.review'
import { findingPrompt, parseTaskNotification, toReviewBoard } from '../hooks/review'
import type { ReviewState } from '../types'

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
    const answer = await $.command.run({ command: 'hud', args: '', origin: { kind: 'person' } as never, presentation: {} as never })
    expect(JSON.stringify(answer)).toContain('/shipgate:setup')
  })

  test('with the sidecar: session.start runs status once and log once, opens the pane, draws the stream', async ($, on) => {
    const { opened } = engineWorld(on)
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    const statusRuns = runs.filter(argv => argv.includes('status'))
    const logRuns = runs.filter(argv => argv.includes('log'))
    expect(statusRuns.length).toBe(1)
    expect(statusRuns[0]).toContain('--branch=feat/example-stream')
    expect(logRuns.length).toBe(1)
    expect(logRuns[0]).toContain('feat/example-stream')
    expect(opened).toEqual(['shipgate-hud'])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('implement')
    await band.unmount()
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
  })

  test('a Bash call that appends to the journal triggers a refresh; another Bash call does not', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: 'Bash' }, async () => ({ result: { stdout: 'appended', stderr: '' } }))
    await $.session.start(START)
    const count = () => runs.filter(argv => argv.includes('status')).length
    const before = count()
    await $.tool.call({ tool: 'Bash', tool_use_id: 't1', command: 'ls -la' } as never)
    expect(count()).toBe(before)
    await $.tool.call({
      tool: 'Bash',
      tool_use_id: 't2',
      command: 'python3 shipgate/scripts/journal.py append --stream s --type task-done --data "{}"',
    } as never)
    expect(count()).toBe(before + 1)
  })

  test('log --stream gets the stream name, not the folded feature slug', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, { ...STATUS, features: [FEATURE_PREFIXED] })
    await $.session.start(START)
    const logRun = runs.find(argv => argv.includes('log'))
    expect(logRun).toContain('feature/example-stream')
    expect(logRun).not.toContain('example-stream')
  })

  test('no stream matches the branch: no position, no fallback to another stream', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, { ...STATUS, features: [{ ...FEATURE_PREFIXED, branch_match: false }] })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /No shipgate stream/ })).toBeDefined()
    await pane.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ key: 'open-hud' })).toBeUndefined()
    await band.unmount()
  })

  // A session drives the stream it writes to, which need not be the checkout's: an epic's
  // planning stream has no branch, and parallel sessions on one project drive different streams.
  const drivenBy = (stream: string) => ({ ...FEATURE_PREFIXED, stream, feature: stream, branch_match: false, session_match: true, phase: 'clarify' })
  const checkedOut = { ...STATUS.features[0], session_match: false }

  test('the stream this session drives wins over the checked-out branch, in one status call', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, (argv: string[]) => ({
      ...STATUS,
      features: argv.includes(`--session=${SESSION_ID}`) ? [drivenBy('epic-example'), checkedOut] : [checkedOut],
    }))
    await $.session.start(START)
    const statusRuns = runs.filter(argv => argv.includes('status'))
    expect(statusRuns.length).toBe(1)
    expect(statusRuns[0]).toContain(`--session=${SESSION_ID}`)
    expect(statusRuns[0]).toContain('--branch=feat/example-stream')
    expect(runs.find(argv => argv.includes('log'))).toContain('epic-example')
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Text', text: /epic-example/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /feat\/example-stream/ })).toBeUndefined()
    await band.unmount()
  })

  for (const [session, stream] of [['session-a', 'epic-example'], ['session-b', 'feat/other-stream']] as const) {
    test(`parallel sessions on one checkout: ${session} sees the stream it drives`, async ($, on) => {
      engineWorld(on, START.cwd, START.cwd, session)
      // one journal, two sessions writing to different streams; status answers per --session
      const drives: Record<string, string> = { 'session-a': 'epic-example', 'session-b': 'feat/other-stream' }
      const { runs } = journaledWorld(on, (argv: string[]) => {
        const asked = argv.find(a => a.startsWith('--session='))?.slice('--session='.length)
        const driven = asked ? drives[asked] : undefined
        return { ...STATUS, features: driven ? [drivenBy(driven), checkedOut] : [checkedOut] }
      })
      await $.session.start(START)
      expect(runs.find(argv => argv.includes('log'))).toContain(stream)
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: new RegExp(stream.replace('/', '\\/')) })).toBeDefined()
      await band.unmount()
    })
  }

  test('a journal.py older than --session: the HUD asks by branch alone and shows no error', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, (argv: string[]) =>
      argv.some(a => a.startsWith('--session='))
        ? { value: { exitCode: 2, stdout: '', stderr: 'journal.py: error: unrecognized arguments: --session=x', isStdoutTruncated: false, isStderrTruncated: false } }
        : STATUS,
    )
    await $.session.start(START)
    expect(runs.filter(argv => argv.includes('status')).length).toBe(2)
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Text', text: /feat\/example-stream/ })).toBeDefined()
    await band.unmount()
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /unrecognized/ })).toBeUndefined()
    await pane.unmount()
  })

  test('a --session call that fails for another reason shows the error, not the branch fallback', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on, () => ({
      value: { exitCode: 1, stdout: '', stderr: 'journal database not found', isStdoutTruncated: false, isStderrTruncated: false },
    }))
    await $.session.start(START)
    expect(runs.filter(argv => argv.includes('status')).length).toBe(1)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /journal database not found/ })).toBeDefined()
    await pane.unmount()
  })

  test('a shell cd into a nested repo does not move the HUD: sidecar, journal, branch and writes stay anchored on the session root', async ($, on) => {
    const { opened } = engineWorld(on, START.cwd, `${START.cwd}/source/svc`) // the shell stepped into a nested repo
    const existsAsked: string[] = []
    on('fs.list', async (_$, e) => {
      if (e.path === START.cwd) return { value: [{ name: 'svc-a', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
      return { deny: `no such directory: ${e.path}` }
    })
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } as never }))
    const runs: { argv: string[]; cwd: string | undefined }[] = []
    const asked: string[] = []
    on('fs.exists', async (_$, e) => {
      asked.push(e.path)
      existsAsked.push(e.path)
      return { value: e.path === `${START.cwd}/.claude/shipgate.json` || e.path === `${START.cwd}/svc-a/.git` || e.path.endsWith('/shipgate/scripts/journal.py') }
    })
    on('fs.read', async (_$, e) => {
      if (e.path === `${START.cwd}/.claude/shipgate.json`) return { value: JSON.stringify(SIDECAR) }
      if (e.path === `${START.cwd}/docs/prd/example.worklog.md`) return { value: WORKLOG }
      return { deny: `no such fixture: ${e.path}` }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push({ argv, cwd: e.init?.cwd })
      // the root is an umbrella on a branch with no stream; the nested repo carries it
      if (argv[0] === 'git') return ok(argv[1] === '-C' ? 'feat/example-stream\n' : 'main\n')
      if (argv.includes('status')) return ok(JSON.stringify(argv.includes('--branch=main') ? { ...STATUS, features: [], branch_match: null } : STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start(START)
    expect(opened).toEqual(['shipgate-hud'])
    // the sidecar was looked for from the root, never from the shell's directory
    expect(asked.filter(p => p.endsWith('/.claude/shipgate.json'))).toEqual([`${START.cwd}/.claude/shipgate.json`])
    // the nested repo was found by an absolute check under the root, and probed from the root
    expect(existsAsked).toContain(`${START.cwd}/svc-a/.git`)
    expect(runs.find(r => r.argv[1] === '-C')?.argv[2]).toBe('svc-a')
    // every git and journal.py run happened in the root
    expect(runs.every(r => r.cwd === START.cwd)).toBe(true)
    expect(runs.find(r => r.argv.includes('log'))).toBeDefined()
    // a relative write path resolves where the tool resolves it (the shell's directory) and is matched against the root
    // one refresh = one log fetch (the status probes per branch vary with the checkout)
    const refreshes = () => runs.filter(r => r.argv.includes('log')).length
    const before = refreshes()
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-cd', file_path: '../../plugin/docs/prd/example-stream.worklog.md', content: '' } as never)
    expect(refreshes()).toBe(before + 1)
  })

  test('a session inside a nested repo of an umbrella: the sidecar above is found, the journal runs there, artifacts read from there', async ($, on) => {
    const nested = `${START.cwd}/source/svc`
    engineWorld(on, nested)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } as never }))
    const runs: { argv: string[]; cwd: string | undefined }[] = []
    const reads: string[] = []
    const asked: string[] = []
    on('fs.exists', async (_$, e) => {
      asked.push(e.path)
      return { value: e.path === `${START.cwd}/.claude/shipgate.json` || e.path.endsWith('/shipgate/scripts/journal.py') }
    })
    on('fs.read', async (_$, e) => {
      reads.push(e.path)
      if (e.path === `${START.cwd}/.claude/shipgate.json`) return { value: JSON.stringify(SIDECAR) }
      if (e.path === `${START.cwd}/docs/prd/example.worklog.md`) return { value: WORKLOG }
      if (e.path === `${START.cwd}/docs/adr/0007-example-decision.md`) return { value: ADR }
      return { deny: `no such fixture: ${e.path}` }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push({ argv, cwd: e.init?.cwd })
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start({ ...START, cwd: nested })
    // the sidecar was looked for in the session directory first, then upward
    expect(asked.filter(p => p.endsWith('/.claude/shipgate.json'))).toEqual([`${nested}/.claude/shipgate.json`, `${START.cwd}/source/.claude/shipgate.json`, `${START.cwd}/.claude/shipgate.json`])
    // journal.py ran in the project root, git in the session root (here the nested repo)
    expect(runs.filter(r => r.argv[0] === 'python3').map(r => r.cwd)).toEqual([START.cwd, START.cwd])
    expect(runs.find(r => r.argv[0] === 'git')?.cwd).toBe(nested)
    // every artifact was read under the project root, none under the nested repo
    expect(reads.every(p => p.startsWith(`${START.cwd}/`) && !p.startsWith(`${nested}/`))).toBe(true)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
    // a write into the umbrella's artifact home triggers a refresh; one into the nested repo's own tree does not
    const statusRuns = () => runs.filter(r => r.argv.includes('status')).length
    const before = statusRuns()
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-nested-1', file_path: 'src/app.ts', content: '' } as never)
    expect(statusRuns()).toBe(before)
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-nested-2', file_path: `${START.cwd}/plugin/docs/prd/example.worklog.md`, content: '' } as never)
    expect(statusRuns()).toBe(before + 1)
  })

  test('a nested session: the worklog fallback scans the umbrella root, and a ../ write path is normalised', async ($, on) => {
    const nested = `${START.cwd}/source/svc`
    engineWorld(on, nested)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } as never }))
    const noRefs = { events: LOG.events.filter(e => e.type !== 'design-committed') }
    const runs: string[][] = []
    const listed: string[] = []
    on('fs.exists', async (_$, e) => ({
      value: e.path === `${START.cwd}/.claude/shipgate.json` || e.path.endsWith('/shipgate/scripts/journal.py'),
    }))
    on('fs.read', async (_$, e) => {
      if (e.path === `${START.cwd}/.claude/shipgate.json`) return { value: JSON.stringify({ artifact_homes: { worklog: '*/docs/prd/*.worklog.md' } }) }
      if (e.path === `${START.cwd}/plugin/docs/prd/example-stream.worklog.md`) return { value: WORKLOG }
      return { deny: `no such fixture: ${e.path}` }
    })
    on('fs.list', async (_$, e) => {
      listed.push(e.path ?? '')
      if (e.path === `${START.cwd}/plugin/docs/prd`) {
        return { value: [{ name: 'example-stream.worklog.md', kind: 'file' as const, size: 1, mtimeMs: 1, isLink: false }] }
      }
      if (e.path === START.cwd) return { value: [{ name: 'plugin', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
      return { deny: `unexpected listing: ${e.path}` }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(noRefs))
      return ok('')
    })
    await $.session.start({ ...START, cwd: nested })
    // the top-level scan and the worklog home were listed under the umbrella root, never under the nested repo
    expect(listed).toEqual([START.cwd, `${START.cwd}/plugin/docs/prd`])
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
    // a write given relative to the nested session dir with ../ reaches the umbrella's artifact home
    const before = runs.filter(argv => argv.includes('status')).length
    await $.tool.call({ tool: 'Write', tool_use_id: 'w-up', file_path: '../../plugin/docs/prd/example-stream.worklog.md', content: '' } as never)
    expect(runs.filter(argv => argv.includes('status')).length).toBe(before + 1)
  })

  test('an umbrella: the session directory is no git repo, the stream is found through a nested repo', async ($, on) => {
    engineWorld(on)
    const runs: string[][] = []
    const listed: string[] = []
    // a second nested repo on a branch whose stream went quiet a day earlier
    const DORMANT = {
      ...FEATURE_PREFIXED,
      feature: 'feat/older-stream',
      stream: 'feat/older-stream',
      last_event: { seq: 7, ts: '2026-09-30T09:30:00+00:00', type: 'phase-entered' },
    }
    on('fs.exists', async (_$, e) => ({
      value:
        e.path.endsWith('.claude/shipgate.json') ||
        e.path.endsWith('/shipgate/scripts/journal.py') ||
        e.path.endsWith('/service/.git') ||
        e.path.endsWith('/older/.git') ||
        e.path.endsWith('/service/.worktrees/wt-inside/.git') ||
        e.path.endsWith('/.worktrees/wt-beside/.git'),
    }))
    on('fs.read', async (_$, e) => {
      if (e.path.endsWith('.claude/shipgate.json')) return { value: JSON.stringify(SIDECAR) }
      if (e.path.endsWith('example.worklog.md')) return { value: WORKLOG }
      return { deny: `no such fixture: ${e.path}` }
    })
    // the umbrella root: two nested repos (the dormant one listed first), a plain folder, a
    // dot-directory, a worktree inside `service` and one beside the repos, and no `source/` or
    // `packages/` (the engine may pass paths relative or absolute)
    on('fs.list', async (_$, e) => {
      listed.push(e.path ?? '')
      const path = e.path ?? ''
      if (/(^|\/)(source|packages)(\/\.worktrees)?$/.test(path)) return { deny: 'no such directory' }
      if (/(^|\/)service\/\.worktrees$/.test(path)) return { value: [{ name: 'wt-inside', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
      if (/(^|\/)(older|notes)\/\.worktrees$/.test(path)) return { deny: 'no such directory' }
      if (/(^|\/)\.worktrees$/.test(path)) return { value: [{ name: 'wt-beside', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
      return {
        value: [
          { name: 'older', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          { name: 'service', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          { name: 'notes', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          { name: '.claude', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          { name: 'README.md', kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false },
        ],
      }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git' && argv[1] === '-C') {
        const branch = { service: 'feat/example-stream', older: 'feat/older-stream', 'service/.worktrees/wt-inside': 'feat/wt-inside', '.worktrees/wt-beside': 'feat/wt-beside' }[argv[2] ?? '']
        return ok(branch ? `${branch}\n` : '')
      }
      if (argv[0] === 'git') return { value: { exitCode: 128, stdout: '', stderr: 'fatal: not a git repository', isStdoutTruncated: false, isStderrTruncated: false } }
      if (argv.includes('status')) {
        if (argv.includes('--branch=feat/example-stream')) return ok(JSON.stringify(STATUS))
        if (argv.includes('--branch=feat/older-stream')) return ok(JSON.stringify({ ...STATUS, features: [DORMANT], branch_match: 'feat/older-stream' }))
        return ok(JSON.stringify({ ...STATUS, features: [], branch_match: null }))
      }
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start(START)
    // the root and the two setup globs were listed, plus the `.worktrees` of each repo and parent
    expect(listed.map(p => p.split('/').pop())).toEqual(expect.arrayContaining(['source', 'packages', '.worktrees']))
    // every nested repo's branch was asked for — a repo, its worktrees, then the parent's — never the plain folder or the dot-directory
    expect(runs.filter(argv => argv[0] === 'git' && argv[1] === '-C').map(argv => argv[2])).toEqual(['older', 'service', 'service/.worktrees/wt-inside', '.worktrees/wt-beside'])
    // the session is asked first (it drives no stream here), then each nested branch once
    expect(runs.filter(argv => argv.includes('status')).map(argv => argv.at(-1))).toEqual([`--session=${SESSION_ID}`, '--branch=feat/older-stream', '--branch=feat/example-stream', '--branch=feat/wt-inside', '--branch=feat/wt-beside'])
    // the live stream wins over the dormant one, whatever the directory order
    expect(runs.find(argv => argv.includes('log'))).toContain('feat/example-stream')
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('implement')
    await band.unmount()
  })

  test('a Write into a configured artifact home triggers a refresh; one elsewhere does not', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: ['Write', 'Edit'] }, async () => ({ result: { filePath: 'x', content: '' } as never }))
    await $.session.start(START)
    const count = () => runs.filter(argv => argv.includes('status')).length
    const before = count()
    await $.tool.call({ tool: 'Write', tool_use_id: 'w1', file_path: 'src/app.ts', content: '' } as never)
    expect(count()).toBe(before)
    // the sidecar's homes are `*/docs/prd/*.md`, merged over shipgate's defaults: a plugin-scoped PRD matches …
    await $.tool.call({ tool: 'Write', tool_use_id: 'w2', file_path: 'plugin/docs/prd/example.worklog.md', content: '' } as never)
    expect(count()).toBe(before + 1)
    // … an absolute path is made relative to the session directory first …
    await $.tool.call({ tool: 'Write', tool_use_id: 'w3', file_path: `${START.cwd}/plugin/docs/adr/0002-x.md`, content: '' } as never)
    expect(count()).toBe(before + 2)
    // … and a path outside the project never matches, however it ends
    await $.tool.call({ tool: 'Write', tool_use_id: 'w4', file_path: '/elsewhere/plugin/docs/prd/x.md', content: '' } as never)
    expect(count()).toBe(before + 2)
  })

  test('refresh requests during a refresh coalesce into one trailing run', async ($, on) => {
    engineWorld(on)
    let release: () => void = () => {}
    const held = new Promise<void>(resolve => {
      release = resolve
    })
    // the hooks environment has no DOM lib: reach the runtime timer through globalThis
    const timer = globalThis as unknown as { setTimeout: (fn: () => void, ms: number) => void }
    const runs: string[][] = []
    on('fs.exists', async (_$, e) => ({
      value: e.path.endsWith('.claude/shipgate.json') || e.path.endsWith('/shipgate/scripts/journal.py'),
    }))
    on('fs.read', async () => ({ deny: 'none' }))
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) {
        if (runs.filter(a => a.includes('status')).length > 1) await held
        return ok(JSON.stringify(STATUS))
      }
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    on('tool.call', { tool: 'Bash' }, async () => ({ result: { stdout: '', stderr: '' } }))
    await $.session.start(START)
    const before = runs.filter(a => a.includes('status')).length
    const append = (id: string) =>
      $.tool.call({ tool: 'Bash', tool_use_id: id, command: 'python3 x/journal.py append --stream s --type deviation' } as never)
    // three appends while the first refresh is held on its status run
    const calls = [append('a1'), append('a2'), append('a3')]
    await new Promise<void>(resolve => timer.setTimeout(resolve, 20))
    release()
    await Promise.all(calls)
    // one run for the first request, one trailing run for the two that arrived meanwhile
    expect(runs.filter(a => a.includes('status')).length).toBe(before + 2)
  })

  test('worklog fallback: the stream-named worklog in the configured home, never another feature\'s', async ($, on) => {
    engineWorld(on)
    const noRefs = { events: LOG.events.filter(e => e.type !== 'design-committed') }
    const runs: string[][] = []
    on('fs.exists', async (_$, e) => ({
      value: e.path.endsWith('.claude/shipgate.json') || e.path.endsWith('/shipgate/scripts/journal.py'),
    }))
    on('fs.read', async (_$, e) => {
      if (e.path.endsWith('.claude/shipgate.json')) return { value: JSON.stringify({ artifact_homes: { worklog: '*/docs/prd/*.worklog.md' } }) }
      if (e.path.endsWith('example-stream.worklog.md')) return { value: WORKLOG }
      return { deny: `no such fixture: ${e.path}` }
    })
    // the engine hands the hook an absolute path, so match on the tail
    on('fs.list', async (_$, e) => {
      if (e.path?.endsWith('plugin/docs/prd')) {
        return {
          value: [
            { name: 'other-feature.worklog.md', kind: 'file' as const, size: 1, mtimeMs: 9_000, isLink: false },
            { name: 'example-stream.worklog.md', kind: 'file' as const, size: 1, mtimeMs: 1_000, isLink: false },
            { name: 'stream.worklog.md', kind: 'file' as const, size: 1, mtimeMs: 8_000, isLink: false },
          ],
        }
      }
      // the session directory itself: one child directory
      return { value: [{ name: 'plugin', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(noRefs))
      return ok('')
    })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    // the Plan tab shows the worklog named for the slug, not the newer `other-feature` one
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
  })

  // Two streams may share a slug by accident: an epic stream `epic/x` and the worklog `x.worklog.md`
  // that one of its children named in its events. The fallback is for a stream whose events name
  // no worklog yet, so a worklog another live stream's events name is that stream's, not a match.
  const OTHER_STREAM = {
    ...FEATURE_PREFIXED,
    feature: 'feat/other-stream',
    stream: 'feat/other-stream',
    branch_match: false,
    session_match: false,
    last_event: { seq: 50, ts: '2026-10-01T10:00:00+00:00', type: 'task-done' },
  }
  const CLAIMING_LOG = {
    events: [
      { seq: 45, type: 'design-committed', ts: '2026-10-01T09:00:00+00:00', data: { worklog: 'plugin/docs/prd/example-stream.worklog.md' } },
      { seq: 50, type: 'task-done', ts: '2026-10-01T10:00:00+00:00', data: { task_ids: ['T001'] } },
    ],
  }

  /** The own stream's events with the worklog ref gone: what makes the HUD fall back to the slug scan. */
  const NO_REFS = { events: LOG.events.filter(e => e.type !== 'design-committed') }

  /**
   * The fallback world: a worklog home listing `files` (a slug-named worklog by default), the own
   * stream's events naming none. A `logs` entry is the `log --json` answer for that stream, or a
   * whole process result (`{ value }`, a run that fails) or a refusal (`{ deny }`, a cut run).
   */
  function fallbackWorld(on: On, status: unknown, logs: Record<string, unknown>, files: string[] = ['example-stream.worklog.md']): string[][] {
    const runs: string[][] = []
    on('fs.exists', async (_$, e) => ({
      value: e.path.endsWith('.claude/shipgate.json') || e.path.endsWith('/shipgate/scripts/journal.py'),
    }))
    on('fs.read', async (_$, e) => {
      if (e.path.endsWith('.claude/shipgate.json')) return { value: JSON.stringify({ artifact_homes: { worklog: '*/docs/prd/*.worklog.md' } }) }
      if (e.path.endsWith('example-stream.worklog.md')) return { value: WORKLOG }
      return { deny: `no such fixture: ${e.path}` }
    })
    on('fs.list', async (_$, e) => {
      if (e.path?.endsWith('plugin/docs/prd')) {
        return { value: files.map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 1_000, isLink: false })) }
      }
      return { value: [{ name: 'plugin', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }] }
    })
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(status))
      if (argv.includes('log')) {
        const stream = argv[argv.indexOf('--stream') + 1] ?? ''
        const answer = logs[stream] ?? NO_REFS
        if (answer && typeof answer === 'object' && ('value' in answer || 'deny' in answer)) return answer as never
        return ok(JSON.stringify(answer))
      }
      return ok('')
    })
    return runs
  }

  const logFor = (runs: string[][], stream: string) => runs.filter(argv => argv.includes('log') && argv.includes(stream))

  test('worklog fallback: a slug-named worklog another live stream\'s events name is left alone', async ($, on) => {
    engineWorld(on)
    const runs = fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': CLAIMING_LOG })
    await $.session.start(START)
    // the other stream's log was read to learn what it claims
    expect(logFor(runs, 'feat/other-stream').length).toBe(1)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeUndefined()
    await pane.unmount()
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('no plan')
    await band.unmount()
  })

  test('worklog fallback: a sibling stream naming a different worklog does not block the slug match', async ($, on) => {
    engineWorld(on)
    const elsewhere = { events: [{ seq: 45, type: 'design-committed', ts: '2026-10-01T09:00:00+00:00', data: { worklog: 'plugin/docs/prd/other.worklog.md' } }] }
    fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': elsewhere })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
  })

  test('worklog fallback: the sibling logs are read only when a slug-named worklog was found', async ($, on) => {
    engineWorld(on)
    // the own stream's events name the worklog: no fallback, so no sibling log
    const { runs } = journaledWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] })
    await $.session.start(START)
    expect(logFor(runs, 'feat/other-stream')).toEqual([])
    expect(logFor(runs, 'feat/example-stream').length).toBe(1)
  })

  test('worklog fallback: no slug-named worklog in the home: no sibling log is read, no plan', async ($, on) => {
    engineWorld(on)
    const runs = fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': CLAIMING_LOG }, ['unrelated.worklog.md'])
    await $.session.start(START)
    expect(logFor(runs, 'feat/other-stream')).toEqual([])
    const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
    expect((await band.find({ type: 'Text', text: /feat\/example-stream/ }))?.text).toContain('no plan')
    await band.unmount()
  })

  test('worklog fallback: a sibling in a nested repo names its worklog relative to that repo, and still claims it', async ($, on) => {
    engineWorld(on)
    const nestedRef = { events: [{ seq: 45, type: 'design-committed', ts: '2026-10-01T09:00:00+00:00', data: { worklog: 'docs/prd/example-stream.worklog.md' } }] }
    fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': nestedRef })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeUndefined()
    await pane.unmount()
  })

  test('worklog fallback: a sibling ref that only shares a tail of the name claims nothing', async ($, on) => {
    engineWorld(on)
    // `prd/xexample-stream.worklog.md` is no path suffix of `plugin/docs/prd/example-stream.worklog.md`
    const nearMiss = { events: [{ seq: 45, type: 'design-committed', ts: '2026-10-01T09:00:00+00:00', data: { worklog: 'prd/xexample-stream.worklog.md' } }] }
    fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': nearMiss })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
  })

  test('worklog fallback: a sibling log that fails is skipped, not shown as the HUD\'s error', async ($, on) => {
    engineWorld(on)
    const failed = { value: { exitCode: 1, stdout: '', stderr: 'database locked', isStdoutTruncated: false, isStderrTruncated: false } }
    const runs = fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': failed })
    await $.session.start(START)
    // the sibling log ran and failed; the failure was swallowed
    expect(logFor(runs, 'feat/other-stream').length).toBe(1)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    // the unclaimable sibling is treated as claiming nothing: the slug match stands, no error
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    expect(await pane.find({ type: 'Text', text: /database locked/ })).toBeUndefined()
    await pane.unmount()
  })

  test('worklog fallback: a sibling log the person cut is a cut refresh, not a sibling that claims nothing', async ($, on) => {
    engineWorld(on)
    const cut = { deny: '$.process.run(python3) aborted' }
    fallbackWorld(on, { ...STATUS, features: [STATUS.features[0], OTHER_STREAM] }, { 'feat/other-stream': cut })
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    // no position was stored and no error shown: the refresh was cut before it could answer
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeUndefined()
    expect(await pane.find({ type: 'Text', text: /shipgate-hud:/ })).toBeUndefined()
    await pane.unmount()
  })

  test('a resume in a session that never had a surface runs nothing', async ($, on) => {
    engineWorld(on)
    on('classic.SessionStart', async () => ({}))
    const { runs } = journaledWorld(on)
    await $.session.start({ ...START, surface: null })
    await $.classic.SessionStart({ source: 'resume' })
    expect(runs).toEqual([])
  })

  test('a session with no surface runs nothing', async ($, on) => {
    engineWorld(on)
    const { runs } = journaledWorld(on)
    await $.session.start({ ...START, surface: null })
    expect(runs).toEqual([])
  })

  test('after /clear the position is detected and refreshed again', async ($, on) => {
    engineWorld(on)
    on('classic.SessionStart', async () => ({}))
    const { runs } = journaledWorld(on)
    await $.session.start(START)
    const before = runs.filter(argv => argv.includes('status')).length
    await $.classic.SessionStart({ source: 'clear' })
    expect(runs.filter(argv => argv.includes('status')).length).toBe(before + 1)
  })

  test('journal.py found in the plugin cache: newest version wins', async ($, on) => {
    engineWorld(on)
    const runs: string[][] = []
    on('fs.exists', async (_$, e) => ({
      value: e.path.endsWith('.claude/shipgate.json') || e.path.endsWith('/shipgate/0.14.1/scripts/journal.py'),
    }))
    on('fs.list', async (_$, e) => {
      if (e.path?.endsWith('/shipgate')) {
        return {
          value: [
            { name: '0.9.0', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
            { name: '0.14.1', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
            { name: '0.13.6', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          ],
        }
      }
      return { deny: 'no such directory' }
    })
    on('fs.read', async () => ({ deny: 'none' }))
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start(START)
    const status = runs.find(argv => argv.includes('status'))
    expect(status?.[1]).toMatch(/\/shipgate\/0\.14\.1\/scripts\/journal\.py$/)
  })

  test('a linked plugin folder: journal.py is found beside where the link lands', async ($, on) => {
    engineWorld(on)
    const runs: string[][] = []
    on('fs.stat', async (_$, e) => {
      if (e.path.endsWith('/shipgate-hud')) {
        return { value: { kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: true, realPath: '/real/pandora/shipgate-hud' } }
      }
      return { deny: 'ENOENT' }
    })
    on('fs.exists', async (_$, e) => ({
      // the engine may hand the hook the path normalized (`..` folded) or as the plugin spelled it
      value: e.path.endsWith('.claude/shipgate.json') || /^\/real\/pandora\/(shipgate-hud\/\.\.\/)?shipgate\/scripts\/journal\.py$/.test(e.path),
    }))
    on('fs.list', async () => ({ deny: 'no such directory' }))
    on('fs.read', async () => ({ deny: 'none' }))
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start(START)
    expect(runs.find(argv => argv.includes('status'))?.[1]).toBe('/real/pandora/shipgate-hud/../shipgate/scripts/journal.py')
  })

  test('nothing beside the plugin: journal.py is found in the config directory\'s plugin cache', async ($, on) => {
    engineWorld(on)
    mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/someone' })
    const runs: string[][] = []
    on('fs.stat', async () => ({ deny: 'ENOENT' }))
    on('fs.exists', async (_$, e) => ({
      value: e.path.endsWith('.claude/shipgate.json') || e.path === '/cfg/plugins/cache/pandora/shipgate/0.14.1/scripts/journal.py',
    }))
    on('fs.list', async (_$, e) => {
      if (e.path === '/cfg/plugins/cache') {
        return {
          value: [
            { name: 'other-market', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
            { name: 'pandora', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          ],
        }
      }
      if (e.path === '/cfg/plugins/cache/pandora/shipgate') {
        return {
          value: [
            { name: '0.13.6', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
            { name: '0.14.1', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false },
          ],
        }
      }
      return { deny: 'no such directory' }
    })
    on('fs.read', async () => ({ deny: 'none' }))
    on('process.run', async (_$, e) => {
      const argv = [...e.argv]
      runs.push(argv)
      if (argv[0] === 'git') return ok('feat/example-stream\n')
      if (argv.includes('status')) return ok(JSON.stringify(STATUS))
      if (argv.includes('log')) return ok(JSON.stringify(LOG))
      return ok('')
    })
    await $.session.start(START)
    expect(runs.find(argv => argv.includes('status'))?.[1]).toBe('/cfg/plugins/cache/pandora/shipgate/0.14.1/scripts/journal.py')
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
      return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
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

  test('a journal.py run that exits non-zero is an error even when its message ends in aborted', async ($, on) => {
    engineWorld(on)
    journaledWorld(on, () => ({
      value: { exitCode: 1, stdout: '', stderr: 'stream fix/aborted-run: journal (fix/aborted-run) aborted', isStdoutTruncated: false, isStderrTruncated: false },
    }))
    await $.session.start(START)
    const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /shipgate-hud: .*\(fix\/aborted-run\) aborted/ })).toBeDefined()
    await pane.unmount()
  })

  test('a refresh the person cut (an aborted process run) shows no error and keeps the position', async ($, on) => {
    engineWorld(on)
    // a journal.py run that fails on demand, registered above the journaled world's answers
    let failure: string | null = null
    on('process.run', { argv: ['python3'] }, async (_$, e, next) => {
      // a refusal beneath rejects the plugin's call with this text, as the engine's abort does
      if (failure !== null) return { deny: failure }
      return next(e)
    })
    const { runs } = journaledWorld(on)
    on('tool.call', { tool: 'Bash' }, async () => ({ result: { stdout: 'appended', stderr: '' } }))
    await $.session.start(START)
    const append = (id: string) =>
      $.tool.call({ tool: 'Bash', tool_use_id: id, command: 'python3 shipgate/scripts/journal.py append --stream s --type deviation' } as never)
    failure = '$.process.run(python3) aborted'
    await append('cut-1')
    let pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /shipgate-hud:/ })).toBeUndefined()
    expect(await pane.find({ type: 'Text', text: '2/4 done · 1 unrecorded · 1 failing' })).toBeDefined()
    await pane.unmount()
    // any other failure still shows
    failure = 'journal database is locked'
    await append('cut-2')
    pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
    expect(await pane.find({ type: 'Text', text: /journal database is locked/ })).toBeDefined()
    await pane.unmount()
    expect(runs.length).toBeGreaterThan(0)
  })

  describe('publish gate', () => {
    const BENEATH = { decision: 'allow' as const, reason: 'beneath' }
    const REFUSE = 'Refuse'
    const ONCE = 'Let it through once'
    const questionOf = (e: unknown): string => (e as { questions?: { question?: string }[] }).questions?.[0]?.question ?? ''
    type Answer = { label: string } | 'dismiss'

    /** The engine's verdict beneath the plugin, and the dialog answered with `answer`; the questions asked are recorded. */
    const gateWorld = (on: Parameters<typeof engineWorld>[0], answer: Answer = { label: REFUSE }): { asked: string[] } => {
      const asked: string[] = []
      on('tool.check', { tool: 'Bash' }, async () => BENEATH)
      on('tool.call', { tool: 'AskUserQuestion' }, async (_$, e) => {
        const question = questionOf(e)
        asked.push(question)
        return (answer === 'dismiss' ? { deny: 'dismissed' } : { result: { answers: { [question]: answer.label } } }) as never
      })
      return { asked }
    }

    const check = ($: { tool: { check: (input: { tool: string; input: unknown }) => Promise<unknown> } }, command: string) =>
      $.tool.check({ tool: 'Bash', input: { command } }) as Promise<{ decision: string; reason?: string }>

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
      const before = runs.filter(argv => argv.includes('status')).length
      const verdict = await check($, 'cd x && git push -u origin feature/x')
      expect(runs.filter(argv => argv.includes('status')).length).toBe(before + 1) // refreshed before deciding
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
      journaledWorld(on, STATUS, { events: [...LOG.events, { seq: 50, type: 'review-verdict', ts: '2026-10-01T10:00:00+00:00', data: { verdict: 'ready' } }] })
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
      journaledWorld(on, () => ({
        value: { exitCode: 1, stdout: '', stderr: 'journal database not found', isStdoutTruncated: false, isStderrTruncated: false },
      }))
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

    test('a session with no surface: the push passes, no process runs, nobody is asked', async ($, on) => {
      engineWorld(on)
      const { runs } = journaledWorld(on)
      const { asked } = gateWorld(on)
      await $.session.start({ ...START, surface: null } as never)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(runs).toEqual([])
      expect(asked).toEqual([])
    })

    test('a worker subagent\'s push is held like the main loop\'s (FR-025)', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const agents: unknown[] = []
      on('tool.check', { tool: 'Bash' }, async (_$, e) => {
        agents.push((e as { agentId?: unknown }).agentId)
        return BENEATH
      })
      const { asked } = gateWorld(on, { label: ONCE })
      await $.session.start(START)
      const verdict = await $.tool.check({ tool: 'Bash', input: { command: 'git push' }, agentId: 'worker-1' } as never)
      expect(asked.length).toBe(1) // the person is asked in the main dialog
      expect(verdict).toMatchObject(BENEATH) // let through once
      expect(agents).toEqual(['worker-1']) // the call carried the worker's loop to the end
    })

    test('a reviewed stream whose refresh is cut: the push is held, never passed on the old position', async ($, on) => {
      engineWorld(on)
      let failure: string | null = null
      on('process.run', { argv: ['python3'] }, async (_$, e, next) => (failure !== null ? { deny: failure } : next(e)))
      journaledWorld(on, STATUS, { events: [...LOG.events, { seq: 50, type: 'review-verdict', ts: '2026-10-01T10:00:00+00:00', data: { verdict: 'ready' } }] })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH) // reviewed: passes while the journal answers
      failure = '$.process.run(python3) aborted'
      const verdict = await check($, 'git push')
      expect(asked.length).toBe(1)
      expect(asked[0]).toContain('The refresh was cut')
      expect(verdict.decision).toBe('deny')
      expect(verdict.reason).toContain('The refresh was cut')
    })

    test('no stream for this session: the push passes to the verdict beneath without a dialog', async ($, on) => {
      engineWorld(on)
      journaledWorld(on, { ...STATUS, features: [{ ...FEATURE_PREFIXED, branch_match: false }] })
      const { asked } = gateWorld(on)
      await $.session.start(START)
      expect(await check($, 'git push')).toMatchObject(BENEATH)
      expect(asked).toEqual([])
    })
  })

  describe('review board', () => {
    const LAUNCH_ID = 'toolu_01AAAAAAAAAAAAAAAAAAAAAA'
    // the counts' first line at the pane's 100 columns; `unverified 1 · open N` packs onto the next
    const COUNTS = 'found 9 · deduped 8 · candidates 5 · survivors 3 · killed 1 · below floor 2 · refuters 4/4'
    const OTHER_NOTIFICATION = '<task-notification>\n<task-id>b2</task-id>\n<tool-use-id>toolu_other</tool-use-id>\n<status>completed</status>\n<result>{"ok":true}</result>\n</task-notification>'
    const notify = (text: string) => ({ text, origin: { kind: 'task-notification' } }) as never

    /**
     * The task output file beneath the plugin: `fs.stat` and `fs.read` of any `.output` path are
     * recorded and answered here (the file for a path ending `/tasks/wabc.output`, else ENOENT).
     * Register it before `journaledWorld`, whose catch-all `fs.read` would answer first otherwise.
     */
    const outputWorld = (on: Parameters<typeof engineWorld>[0], text: string = REVIEW_OUTPUT_FILE, size: number = text.length) => {
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

    /** The Bash tool beneath the plugin, so a journal append can run and refresh the position. */
    const appendWorld = (on: Parameters<typeof engineWorld>[0]): void => {
      on('tool.call', { tool: 'Bash' }, async () => ({ result: { stdout: 'appended', stderr: '' } }))
    }

    /** The orchestrator appends to the journal: the HUD refreshes, and the shown stream may move. */
    const refreshByAppend = ($: { tool: { call: (input: never) => Promise<unknown> } }) =>
      $.tool.call({ tool: 'Bash', tool_use_id: 'append-1', command: 'python3 shipgate/scripts/journal.py append --stream s --type deviation' } as never)

    /** The Workflow tool beneath the plugin: it launches in the background and names the run. */
    const workflowWorld = (on: Parameters<typeof engineWorld>[0]): void => {
      on('tool.call', { tool: 'Workflow' }, async () => ({ result: REVIEW_LAUNCH_RESULT }) as never)
    }

    /**
     * Every value the plugin writes to its `review` atom, recorded beneath it (the test `$` has no
     * state reader); `rewrite` changes what is stored. `last()` is the atom as it now stands.
     */
    const reviewWatch = (on: Parameters<typeof engineWorld>[0], rewrite: (value: ReviewState) => ReviewState = v => v) => {
      const values: ReviewState[] = []
      on('state.set', async (_$, e, next) => {
        if (e.plugin !== 'shipgate-hud' || e.key !== 'review') return next(e)
        const value = rewrite(e.value as ReviewState)
        values.push(value)
        return next({ ...e, value } as never)
      })
      return { last: (): ReviewState | undefined => values.at(-1) }
    }

    const launchReview = ($: { tool: { call: (input: never) => Promise<unknown> } }, id: string = LAUNCH_ID) =>
      $.tool.call({ tool: 'Workflow', tool_use_id: id, script: "export const meta = { name: 'shipgate-review' }" } as never)

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
      expect(state?.boards[0]?.survivors.length).toBe(3)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ type: 'Text', text: ' 4 Review ' }))?.props.inverse).toBe(true)
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: '▎ BLOCKER' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: '95% · held 0/2 · correctness' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/api/handler.ts:42' })).toBeDefined()
      expect(await pane.find({ key: 'accept-0' })).toBeDefined()
      expect(await pane.find({ key: 'kill-2' })).toBeDefined()
      // killed and below-floor entries: a dim head, then the location and the summary as on a card
      expect(await pane.find({ type: 'Text', text: 'MEDIUM · q=2/2' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/parse.ts:10' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'HIGH · 40%' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'src/cache/store.ts:77' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: 'The cache key ignores the locale.' })).toBeDefined()
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review 3 open/ })).toBeDefined()
      await band.unmount()
    })

    test('an id match alone never makes or replaces a board: the result must be the return', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      workflowWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const held = watch.last()
      expect(held?.boards[0]?.survivors.length).toBe(3)
      await launchReview($, 'toolu_other')
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      expect(watch.last()).toBe(held) // no write: the old board stands unchanged
    })

    test('a return cut in the notification is read whole from the task output file', async ($, on) => {
      const { submitted } = engineWorld(on)
      const { stats, reads } = outputWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(submitted).toEqual([REVIEW_NOTIFICATION_TRUNCATED]) // passed on unchanged
      expect(stats).toEqual([REVIEW_OUTPUT_PATH])
      expect(reads).toEqual([REVIEW_OUTPUT_PATH])
      expect(watch.last()?.boards[0]?.survivors.length).toBe(3)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: '▎ BLOCKER' })).toBeDefined()
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      await pane.unmount()
    })

    for (const [name, path] of [
      ['a .. segment', '/tmp/project/.claude/tasks/../wabc.output'],
      ['no /tasks/ segment', '/tmp/project/.claude/wabc.output'],
      ['a relative path', 'tasks/wabc.output'],
    ] as const) {
      test(`an output-file path with ${name} is neither stat'ed nor read`, async ($, on) => {
        engineWorld(on)
        const { stats, reads } = outputWorld(on)
        journaledWorld(on)
        const watch = reviewWatch(on)
        await $.session.start(START)
        await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED.replace(`<output-file>${REVIEW_OUTPUT_PATH}</output-file>`, `<output-file>${path}</output-file>`)))
        expect(stats).toEqual([])
        expect(reads).toEqual([])
        expect(watch.last()?.boards[0] ?? null).toBeNull()
      })
    }

    test('an output file whose JSON lacks the return shape makes no board', async ($, on) => {
      engineWorld(on)
      const { reads } = outputWorld(on, JSON.stringify({ summary: 'x', result: { ok: true } }))
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(reads).toEqual([REVIEW_OUTPUT_PATH])
      expect(watch.last()?.boards[0] ?? null).toBeNull()
    })

    test('an output file that does not parse makes no board and shows no error', async ($, on) => {
      engineWorld(on)
      outputWorld(on, '{"result": {"survivors": [')
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(watch.last()?.boards[0] ?? null).toBeNull()
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect(await pane.find({ type: 'Text', text: /shipgate-hud:/ })).toBeUndefined()
      await pane.unmount()
    })

    test('an output file over 4 MiB per stat is not read', async ($, on) => {
      engineWorld(on)
      const { stats, reads } = outputWorld(on, REVIEW_OUTPUT_FILE, 4 * 1024 * 1024 + 1)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION_TRUNCATED))
      expect(stats).toEqual([REVIEW_OUTPUT_PATH])
      expect(reads).toEqual([])
      expect(watch.last()?.boards[0] ?? null).toBeNull()
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
      expect((await pane.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · run \? · \d\d:\d\d · 3 survivors$/)
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
      expect(watch.last()?.open).toBe('none')
      expect((await pane.find({ key: 'round-feat/example-stream:1' }))?.props.label).toMatch(/^▸ round 1 · .* · 3 survivors$/)
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: '▎ BLOCKER' })).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: 'SUCCESS CRITERIA' })).toBeDefined()
      expect(await pane.find({ key: 'sc-SC-001' })).toBeDefined()
      await pane.press({ key: 'round-feat/example-stream:1' })
      expect(await pane.find({ type: 'Text', text: COUNTS })).toBeDefined()
      await pane.unmount()
      // a new return opens the newest round again
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.open).toBeNull()
    })

    test('a mark stays with its round, and the prompt names the round', async ($, on) => {
      const { prompts } = engineWorld(on)
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'accept-0' })
      expect(prompts.at(-1)?.text).toContain('finding 1 of 3 in review round 1 (')
      expect(await pane.find({ type: 'Text', text: '✓ accepted' })).toBeDefined()
      await pane.unmount()
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      // round 2 opens with its own buttons; round 1's mark is not drawn on it
      expect(await again.find({ type: 'Text', text: '✓ accepted' })).toBeUndefined()
      expect(await again.find({ key: 'accept-0' })).toBeDefined()
      await again.press({ key: 'kill-1' })
      expect(prompts.at(-1)?.text).toContain('finding 2 of 3 in review round 2 (')
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
      expect(await before.find({ type: 'Text', text: /review 1 open/ })).toBeDefined()
      await before.unmount()
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const after = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await after.find({ type: 'Text', text: /review 3 open/ })).toBeDefined()
      await after.unmount()
    })

    test('a round with no stream and a stream\'s round 1 get distinct keys and open on their own', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let shown: unknown = { ...STATUS.features[0], branch_match: false } // no stream for this session yet
      journaledWorld(on, () => ({ ...STATUS, features: [shown] }))
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION)) // round 1 of no stream
      shown = STATUS.features[0]
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
      expect(watch.last()?.marks).toEqual({ 'feat/example-stream:1:0': 'accepted' })
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
      expect(watch.last()?.marks).toEqual({ 'feat/example-stream:1:0': 'accepted' })
      for (let i = 0; i < 5; i += 1) await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.round)).toEqual([6, 5, 4, 3, 2])
      expect(watch.last()?.marks).toEqual({})
    })

    test('a tick made before a newer verdict no longer hides that verdict\'s unmet', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      const log = { events: [...LOG.events] as unknown[] }
      journaledWorld(on, STATUS, log)
      await $.session.start(START)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await pane.unmount()
      log.events.push({ seq: 60, type: 'review-verdict', ts: '2026-10-01T11:00:00+00:00', data: { verdict: 'not-ready', criteria: { 'SC-001': 'unmet' } } })
      await refreshByAppend($)
      const again = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect((await again.find({ key: 'sc-SC-001' }))?.props.label).toBe('☒')
      // a press now is made against the new verdict
      await again.press({ key: 'sc-SC-001' })
      expect((await again.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await again.unmount()
    })

    test('a sixth return drops the stream\'s oldest round', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      for (let i = 0; i < 6; i += 1) await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards.map(board => board.round)).toEqual([6, 5, 4, 3, 2])
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ key: 'round-feat/example-stream:1' })).toBeUndefined()
      expect(await pane.find({ key: 'round-feat/example-stream:2' })).toBeDefined()
      expect(await pane.find({ type: 'Button', text: /^▾ round 6 · / })).toBeDefined()
      await pane.unmount()
    })

    test('a killed review run is not captured', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION.replace('<status>completed</status>', '<status>killed</status>')))
      expect(watch.last()?.boards[0] ?? null).toBeNull()
    })

    test('a session with no surface captures nothing and passes the prompt on', async ($, on) => {
      const { submitted } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start({ ...START, surface: null } as never)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(submitted).toEqual([REVIEW_NOTIFICATION])
      expect(watch.last()?.boards[0] ?? null).toBeNull()
    })

    test('an aborted run: a warning under the counts, and the band says review aborted', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION.replace('"lensesRun"', '"aborted":"the refuter budget ran out","lensesRun"')))
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect((await pane.find({ type: 'Text', text: 'review aborted: the refuter budget ran out' }))?.props.color).toBe('warning')
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
      let shown: unknown = STATUS.features[0]
      journaledWorld(on, () => ({ ...STATUS, features: [shown] }))
      const watch = reviewWatch(on)
      workflowWorld(on)
      await $.session.start(START)
      await launchReview($) // on feat/example-stream
      shown = FEATURE_PREFIXED // the session moves to feature/example-stream
      await refreshByAppend($) // a journal append refreshes the position; $.state is kept
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards[0]?.stream).toBe('feat/example-stream')
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      expect(await pane.find({ type: 'Text', text: 'No review captured for feature/example-stream yet (phase implement).' })).toBeDefined()
      await pane.unmount()
    })

    test('a launch that is not the review workflow is not noted', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      workflowWorld(on)
      await $.session.start(START)
      await $.tool.call({ tool: 'Workflow', tool_use_id: 'toolu_other', script: "export const meta = { name: 'something-else' }" } as never)
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      expect(watch.last()?.boards[0] ?? null).toBeNull()
    })

    test('the review return with no noted launch is captured by its shape', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      const state = watch.last()
      expect(state?.boards[0]?.runId).toBeNull()
      expect(state?.boards[0]?.survivors.map((f: { severity: string }) => f.severity)).toEqual(['BLOCKER', 'HIGH', 'LOW'])
    })

    test('a failed review run is not captured', async ($, on) => {
      engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION.replace('<status>completed</status>', '<status>failed</status>')))
      expect(watch.last()?.boards[0] ?? null).toBeNull()
    })

    test('a notification that is no review return passes untouched and leaves the board empty', async ($, on) => {
      const { submitted, prompts } = engineWorld(on)
      journaledWorld(on)
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(OTHER_NOTIFICATION))
      expect(submitted).toEqual([OTHER_NOTIFICATION])
      expect((prompts[0]?.origin as { kind?: string } | undefined)?.kind).toBe('task-notification')
      expect(watch.last()?.boards[0] ?? null).toBeNull()
      // the review shape typed by the person is not a notification: not captured either
      await $.prompt.submit({ text: REVIEW_NOTIFICATION, origin: { kind: 'composer' } } as never)
      expect(watch.last()?.boards[0] ?? null).toBeNull()
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
      const board = toReviewBoard(parseTaskNotification(REVIEW_NOTIFICATION)?.result, null, 'feat/example-stream', 'now')
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      const before = prompts.length
      await pane.press({ key: 'accept-0' })
      expect(prompts.length).toBe(before + 1)
      const accepted = prompts[before]
      expect(accepted?.text).toBe(findingPrompt('accepted', 0, board))
      expect(accepted?.asUser).toBeUndefined()
      expect(accepted?.text).toContain('finding 1 of 3 in review round 1 (BLOCKER, src/api/handler.ts:42, lens correctness)')
      expect(accepted?.text).not.toContain('permission check')
      expect(await pane.find({ type: 'Text', text: '✓ accepted' })).toBeDefined()
      expect(await pane.find({ key: 'accept-0' })).toBeUndefined()
      await pane.press({ key: 'kill-1' })
      const killed = prompts[before + 1]
      expect(killed?.text).toBe(findingPrompt('killed', 1, board))
      expect(killed?.asUser).toBeUndefined()
      expect(await pane.find({ type: 'Text', text: '✗ killed' })).toBeDefined()
      expect(watch.last()?.marks).toEqual({ 'feat/example-stream:1:0': 'accepted', 'feat/example-stream:1:1': 'killed' })
      await pane.unmount()
      const band = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...BAND })
      expect(await band.find({ type: 'Text', text: /review 1 open/ })).toBeDefined()
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
      expect(watch.last()?.ticks).toEqual({ 'feat/example-stream:SC-001': { state: 'on', seq: null } })
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
      await pane.unmount()
    })

    test('a tick holds for its stream only', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let shown: unknown = STATUS.features[0]
      journaledWorld(on, () => ({ ...STATUS, features: [shown] }))
      await $.session.start(START)
      const pane = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      await pane.press({ key: 'tab-review' })
      await pane.press({ key: 'sc-SC-001' })
      expect((await pane.find({ key: 'sc-SC-001' }))?.props.label).toBe('☑')
      await pane.unmount()
      shown = FEATURE_PREFIXED // another stream, the same PRD
      await refreshByAppend($) // a journal append refreshes the position; $.state is kept
      const other = await $.ui.mount({ plugin: 'shipgate-hud', surface: 'terminal', ...PANE })
      expect((await other.find({ key: 'sc-SC-001' }))?.props.label).toBe('☐')
      await other.unmount()
    })

    test('a board captured before any stream was known is drawn for the stream shown', async ($, on) => {
      engineWorld(on)
      appendWorld(on)
      let shown: unknown = { ...STATUS.features[0], branch_match: false } // no stream for this session yet
      journaledWorld(on, () => ({ ...STATUS, features: [shown] }))
      const watch = reviewWatch(on)
      await $.session.start(START)
      await $.prompt.submit(notify(REVIEW_NOTIFICATION))
      expect(watch.last()?.boards[0]?.stream).toBeNull()
      shown = STATUS.features[0]
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
      reviewWatch(on, value => ({ ...value, boards: value.boards.map(board => ({ ...board, stream: 'feat/other-stream' })) }))
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
