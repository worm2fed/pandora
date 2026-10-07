import { describe, expect, mock, test } from 'claude-code/testing'

import { FEATURE_PREFIXED, LOG, STATUS } from './fixtures'
import { BAND, PANE, START, bareWorld, engineWorld, journaledWorld, ok } from './world'
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
