// The publish gate's pure core: which shell lines publish a branch, and the text the hold
// shows the person and the model. No `$` here, so the tests run it without an engine.

import type { Position } from '../types'

/** A publish command's head as the hold names it. */
export type PublishHead = 'git push' | 'gh pr create' | 'glab mr create'

/** Shell words that open a command without being it: dropped from the front of a segment. */
const SHELL_WORDS = new Set(['if', 'then', 'else', 'elif', 'do', 'while', 'until', '{', '}', '!', 'coproc'])

/** Words that run the command after them: dropped from the front of a segment, with their options. */
const WRAPPERS = new Set([
  'env',
  'command',
  'sudo',
  'nohup',
  'time',
  'xargs',
  'exec',
  'builtin',
  'timeout',
  'nice',
  'ionice',
  'stdbuf',
  'caffeinate',
  'eval',
  'doas',
  'chronic',
])

/** A wrapper's options that take the next word as their value. */
const WRAPPER_VALUE_OPTIONS: Record<string, readonly string[]> = {
  sudo: ['-u', '-g', '-D', '-h', '-p', '-U', '-r', '-t', '-C', '--user', '--group'],
  env: ['-u', '-C', '-S', '-P', '--chdir', '--unset'],
  exec: ['-a'],
  doas: ['-u', '-C'],
  xargs: ['-I', '-n', '-L', '-P', '-d', '-E', '-s', '-a', '--max-args', '--max-procs'],
  timeout: ['-k', '-s', '--signal', '--kill-after'],
  nice: ['-n', '--adjustment'],
  ionice: ['-c', '-n', '-p', '-t'],
  stdbuf: ['-i', '-o', '-e'],
  caffeinate: ['-t', '-w'],
}

/** A wrapper's positional words after its options, before the command (`timeout 60 git push`). */
const WRAPPER_ARGUMENTS: Record<string, number> = { timeout: 1 }

/** Commands that run the text fed to them: their heredoc bodies are command lines too. */
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'fish', 'eval', 'source'])

const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/

/** A redirection at the front of a segment (`>out`, `2>/dev/null`, `<in`, `&>log`). */
const REDIRECTION = /^\d*[<>&]+/

/** A redirection operator standing alone (`>`, `2>`, `>&`): its target is the next word. */
const REDIRECTION_OPERATOR = /^\d*[<>]+&?$/

/** A program as named: its basename, one leading backslash dropped (`/usr/bin/git`, `\git` → `git`). */
const nameOf = (word: string): string => word.replace(/^\\/, '').split('/').pop() ?? ''

/** git's global options that take the next word as their value, unless written `--opt=value`. */
const GIT_VALUE_OPTIONS = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix'])
const REPO_OPTIONS = new Set(['-R', '--repo'])

/**
 * The words of a segment with its leading assignments, redirections, shell words and wrappers
 * (and their options) dropped. `command -v` / `command -V` looks a name up and runs nothing:
 * no words.
 */
function unwrap(words: readonly string[]): string[] {
  let i = 0
  while (i < words.length) {
    const raw = words[i] ?? ''
    if (REDIRECTION_OPERATOR.test(raw) || raw === 'function') {
      i += 2 // the operator and its target; `function` and the function's name
      continue
    }
    if (ASSIGNMENT.test(raw) || REDIRECTION.test(raw) || SHELL_WORDS.has(raw)) {
      i += 1
      continue
    }
    const word = nameOf(raw)
    if (!WRAPPERS.has(word)) break
    if (word === 'command' && (words[i + 1] === '-v' || words[i + 1] === '-V')) return []
    const takesValue = WRAPPER_VALUE_OPTIONS[word] ?? []
    i += 1
    while (i < words.length && (words[i] ?? '').startsWith('-')) {
      i += takesValue.includes(words[i] ?? '') ? 2 : 1
    }
    i += WRAPPER_ARGUMENTS[word] ?? 0
  }
  return words.slice(i)
}

/** Does a heredoc's command run its body: a shell, or `eval`, after the leading words? */
function feedsShell(owner: readonly string[]): boolean {
  if (owner.some(w => nameOf(w) === 'eval')) return true
  return SHELLS.has(nameOf(unwrap(owner)[0] ?? ''))
}

/** The index of the first non-option word from `start`; `valueOptions` also skip their value. */
function skipOptions(words: readonly string[], start: number, valueOptions: ReadonlySet<string>): number {
  let i = start
  while (i < words.length && (words[i] ?? '').startsWith('-')) {
    i += valueOptions.has(words[i] ?? '') ? 2 : 1
  }
  return i
}

/** The publish head one command's words start with, or null. */
function headOf(words: readonly string[]): PublishHead | null {
  const program = nameOf(words[0] ?? '')
  if (program === 'git') {
    const verb = skipOptions(words, 1, GIT_VALUE_OPTIONS)
    if (words[verb] === 'push') return 'git push'
    // `git subtree push` publishes; `git stash push` does not
    if (words[verb] === 'subtree' && words[skipOptions(words, verb + 1, GIT_VALUE_OPTIONS)] === 'push') return 'git push'
    return null
  }
  if (program === 'gh' || program === 'glab') {
    const noun = skipOptions(words, 1, REPO_OPTIONS)
    if (words[noun] !== (program === 'gh' ? 'pr' : 'mr')) return null
    const verb = words[skipOptions(words, noun + 1, REPO_OPTIONS)]
    if (verb !== 'create' && verb !== 'new') return null
    return program === 'gh' ? 'gh pr create' : 'glab mr create'
  }
  return null
}

/** Where one command ends and the next begins, outside quotes. Longest first. */
const SEPARATORS = ['&&', '||', ';', '|', '&', '\n', '(', ')'] as const

/** A heredoc waiting for its body: the terminator, `<<-` (leading tabs stripped), the command it feeds. */
type Heredoc = { terminator: string; stripsTabs: boolean; owner: string[] }

/**
 * The end of a command substitution opened at `start` (just past `$(` or a backtick): the
 * index of its closing `)` (depth counted, quoted text skipped) or backtick; the line's end
 * when unclosed.
 */
function substitutionEnd(line: string, start: number, backtick: boolean): number {
  let depth = 1
  let quote: string | null = null
  for (let i = start; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '\\') {
      i += 1
      continue
    }
    if (backtick) {
      if (ch === '`') return i
      continue
    }
    if (quote !== null) {
      if (ch === quote) quote = null
    } else if (ch === '"' || ch === "'") quote = ch
    else if (ch === '(') depth += 1
    else if (ch === ')') {
      depth -= 1
      if (depth === 0) return i
    }
  }
  return line.length
}

/** The heredoc terminator word at `i` (after `<<` / `<<-` and blanks), quotes and backslashes dropped, and where it ends. */
function terminatorAt(line: string, start: number): { word: string; end: number } {
  let i = start
  while (line[i] === ' ' || line[i] === '\t') i += 1
  let word = ''
  let quote: string | null = null
  for (; i < line.length; i += 1) {
    const ch = line[i] ?? ''
    if (quote !== null) {
      if (ch === quote) quote = null
      else word += ch
    } else if (ch === '"' || ch === "'") quote = ch
    else if (ch === '\\') continue
    else if (/[\s;&|()<>`]/.test(ch)) break
    else word += ch
  }
  return { word, end: i }
}

/**
 * The first publish command in a shell line (`git push`, `gh pr create` or `gh pr new`,
 * `glab mr create` or `glab mr new`), as its head; null when the line publishes nothing.
 *
 * One quote-aware pass. Outside quotes, `&&`, `||`, `;`, `|`, `&`, a newline, `(` and `)`
 * end a command. Inside single or double quotes nothing does: the quoted run is one word and
 * never a command, so `grep "git push" f` publishes nothing. An unquoted `$(…)` or backtick
 * run stays part of its word (`git -C $(pwd) push`) and is read as a command line of its own.
 * A redirection ends a word, and it and its target are dropped (`git push>/dev/null`). A `#`
 * that starts a word comments out the rest of the line. A backslash before a newline
 * continues the line. A heredoc body (`<<EOF` up to the line `EOF`) is a command line only
 * when the command it is fed to is a shell (`bash <<EOF`).
 * Matching is on whole words, so `git pushd`, `gh pr list` and `git stash push` do not match.
 */
export function publishCommandOf(command: string): PublishHead | null {
  const line = command.replace(/\\\r?\n/g, ' ')
  let words: string[] = []
  let word: string | null = null
  let pending: Heredoc[] = []
  let isTarget = false // the next word is a redirection's target: dropped
  const endWord = () => {
    if (word !== null && !isTarget) words.push(word)
    if (word !== null) isTarget = false
    word = null
  }
  const endSegment = (): PublishHead | null => {
    endWord()
    isTarget = false
    const head = headOf(unwrap(words))
    words = []
    return head
  }

  let i = 0
  while (i < line.length) {
    const ch = line[i] ?? ''
    if (ch === "'" || ch === '"') {
      // a quoted run: one word (joined with what touches it), never cut, never a command
      let j = i + 1
      let text = ''
      while (j < line.length && line[j] !== ch) {
        if (ch === '"' && line[j] === '\\' && j + 1 < line.length) j += 1
        text += line[j] ?? ''
        j += 1
      }
      word = (word ?? '') + text
      i = j + 1
      continue
    }
    if (ch === '\\') {
      word = (word ?? '') + (line[i + 1] ?? '')
      i += 2
      continue
    }
    if (line.startsWith('<<<', i)) {
      endWord()
      i += 3
      continue
    }
    if (line.startsWith('<<', i)) {
      endWord()
      const dash = line[i + 2] === '-' ? 1 : 0
      const { word: terminator, end } = terminatorAt(line, i + 2 + dash)
      if (terminator) pending.push({ terminator, stripsTabs: dash === 1, owner: words })
      i = end
      continue
    }
    if (ch === '#' && word === null) {
      // a comment: the rest of the line, up to (not past) the newline
      const cut = line.indexOf('\n', i)
      i = cut < 0 ? line.length : cut
      continue
    }
    if (line.startsWith('$(', i) || ch === '`') {
      const backtick = ch === '`'
      const open = backtick ? 1 : 2
      const close = substitutionEnd(line, i + open, backtick)
      const inner = publishCommandOf(line.slice(i + open, close))
      if (inner !== null) return inner
      word = (word ?? '') + line.slice(i, close + 1)
      i = close + 1
      continue
    }
    if (ch === '<' || ch === '>') {
      // a redirection: a digit run before it (`2>`) is its fd, not a word; the operator and
      // its target are dropped (`>`, `>>`, `>&2`, `<in`, `<>`, `>|`)
      if (word !== null && /^\d+$/.test(word)) word = null
      endWord()
      i += 1
      while (i < line.length && /[<>&|]/.test(line[i] ?? '')) i += 1
      isTarget = true
      continue
    }
    const separator = SEPARATORS.find(s => line.startsWith(s, i))
    if (separator !== undefined) {
      const head = endSegment()
      if (head !== null) return head
      i += separator.length
      if (separator === '\n' && pending.length > 0) {
        for (const heredoc of pending) {
          const body: string[] = []
          while (i <= line.length) {
            const cut = line.indexOf('\n', i)
            const next = cut < 0 ? line.length : cut
            const text = line.slice(i, next)
            i = next + 1
            if ((heredoc.stripsTabs ? text.replace(/^\t+/, '') : text) === heredoc.terminator) break
            body.push(text)
            if (cut < 0) break
          }
          if (feedsShell(heredoc.owner)) {
            const inner = publishCommandOf(body.join('\n'))
            if (inner !== null) return inner
          }
        }
        pending = []
      }
      continue
    }
    if (/\s/.test(ch)) endWord()
    else word = (word ?? '') + ch
    i += 1
  }
  return endSegment()
}

const MISSING =
  'a `review-verdict` with `verdict: ready`, or a `gate-decision` with `gate: publish`, `raised_by: user` and ' +
  '`decision: publish`, recorded after the last `task-done`'

const subjectOf = (current: Pick<Position, 'stream'> | null, error: string | null): string =>
  current !== null ? `stream ${current.stream}` : `the stream: the journal could not be read: ${error ?? 'unknown error'}`

/** What the dialog shows the person: the plugin, the command, the stream (or the error), what is missing. */
export function holdReason(head: string, current: Pick<Position, 'stream'> | null, error: string | null): string {
  return `shipgate-hud holds \`${head}\` for ${subjectOf(current, error)}. Publishing needs ${MISSING}.`
}

/**
 * What the model reads on a deny: what the stream lacks, and the one record it may write
 * itself. The user's decision is taken at the gate's dialog, never recorded on their behalf.
 */
export function denyReason(head: string, current: Pick<Position, 'stream'> | null, error: string | null): string {
  return (
    `shipgate-hud refused \`${head}\` for ${subjectOf(current, error)}. Publishing needs ${MISSING}. ` +
    'Finish the review and record its verdict with `journal.py append --type review-verdict` (`verdict: ready`), ' +
    'or stop and ask the user: their decision is taken at the dialog this gate shows ("Let it through once"), ' +
    'never recorded on their behalf. Then run the command again.'
  )
}

/** The deny reason when the hook itself failed: a publish command is refused, never let through. */
export const FAIL_CLOSED =
  'shipgate-hud refused this publish command: its publish gate failed before it could check the journal. ' +
  'Run the command again; if it keeps failing, ask the user.'
