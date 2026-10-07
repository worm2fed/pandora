// The world beneath the plugin, answered from memory: a journaled project with one
// stream. `claude plugin test` runs with no fs, process or network, so a test that drives
// session.start hooks these calls itself. Generic names only — public repository.

import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

import { ADR, LOG, SIDECAR, STATUS, WORKLOG } from './fixtures'

export const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 9 }, view: {} },
}

export const PANE = {
  component: 'Pane' as const,
  requestId: 'shipgate-hud',
  props: { title: 'shipgate', isFocused: false, bodyColumns: 100, placement: 'dock' as const, scroll: { offset: 0, bodyRows: 40 }, view: {} },
}

export const START = { cwd: '/tmp/project', surface: 'terminal' as const, isInteractive: true }

export const ok = (stdout: string) => ({
  value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

/** What every session needs answered beneath the plugin, journaled or not. */
export function engineWorld(on: On, cwd: string = START.cwd): { commands: string[]; opened: string[]; submitted: string[] } {
  const commands: string[] = []
  const opened: string[] = []
  const submitted: string[] = []
  mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }))
  on('session.cwd', async () => ({ value: cwd }))
  // The engine draws nothing of its own in the band: an empty box stands for that here.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)
    return Box({ children: [] })
  })
  on('command.register', async (_$, e) => {
    commands.push(e.name)
    return { value: { name: e.name, description: e.description } as never }
  })
  on('ui.open', async (_$, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true as const } }
  })
  on('prompt.submit', async (_$, e) => {
    submitted.push(e.text)
    return { text: e.text }
  })
  return { commands, opened, submitted }
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

/** A journaled project: the sidecar and journal.py exist, status and log answer the fixtures. */
export function journaledWorld(on: On, status: unknown = STATUS): { runs: string[][]; reads: string[] } {
  const runs: string[][] = []
  const reads: string[] = []
  on('fs.exists', async (_$, e) => ({
    value: e.path.endsWith('.claude/shipgate.json') || e.path.endsWith('/shipgate/scripts/journal.py'),
  }))
  on('fs.read', async (_$, e) => {
    reads.push(e.path)
    if (e.path.endsWith('.claude/shipgate.json')) return { value: JSON.stringify(SIDECAR) }
    if (e.path.endsWith('example.worklog.md')) return { value: WORKLOG }
    if (e.path.endsWith('0007-example-decision.md')) return { value: ADR }
    return { deny: `no such fixture: ${e.path}` }
  })
  on('process.run', async (_$, e) => {
    const argv = [...e.argv]
    runs.push(argv)
    if (argv[0] === 'git') return ok('feat/example-stream\n')
    if (argv.includes('status')) return ok(JSON.stringify(status))
    if (argv.includes('log')) return ok(JSON.stringify(LOG))
    return ok('')
  })
  return { runs, reads }
}
