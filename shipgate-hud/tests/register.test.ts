import { describe, expect, mock, test } from 'claude-code/testing'

import { ADR, FEATURE_PREFIXED, LOG, SIDECAR, STATUS } from './fixtures'
import { BAND, PANE, SESSION_ID, START, bareWorld, engineWorld, journaledWorld, ok } from './world'
import { WORKLOG } from './fixtures'

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
})
