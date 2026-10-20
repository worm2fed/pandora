// The publish gate's pure core: what a shell line publishes, and the verdict on it once the
// target branch's stream and the session's own are known. register.tsx resolves those (they
// need `$`) and builds one GateInputs value; `gateVerdict` decides. No `$` here, so the tests
// run it without an engine.

import type { BranchName, PublishAuthorization, ReadFailure, StreamName } from '../types'
import { failureText } from './journal'
import { absurd } from './json'

/** A publish command's head as the hold names it. */
export type PublishHead = 'git push' | 'gh pr create' | 'glab mr create'

/**
 * Where a publish command runs. `Shell`: the shell's directory. `Path`: a literal path from
 * `git -C` or a leading `cd`, relative ones composed in order (register.tsx resolves it
 * against the shell's directory). `Unreadable`: a directory the scan cannot read (`cd -`,
 * `cd $X`, `-C "$(…)"`, a `cd` that may not have run); `why` names it.
 */
export type CommandDir =
  | { readonly kind: 'Shell' }
  | { readonly kind: 'Path'; readonly path: string }
  | { readonly kind: 'Unreadable'; readonly why: string }

/**
 * What a publish command publishes. `Head`: the HEAD of `dir`. `Branch`: one named branch,
 * normalized from a refspec (`+src:dst` gives `src`, `refs/heads/x` gives `x`), from
 * `gh pr create --head` (`owner:branch` gives `branch`) or `glab mr create --source-branch`.
 * `Unresolved`: no one branch (several refspecs, `--all`, `--branches`, `--mirror`, `--tags`,
 * a deletion, an argument the scan cannot read); `why` names it.
 */
export type PublishedRef =
  | { readonly kind: 'Head' }
  | { readonly kind: 'Branch'; readonly name: string }
  | { readonly kind: 'Unresolved'; readonly why: string }

/** One publish command as the scan reads it: its head, where it runs, what it publishes (HUD ADR 0005). */
export interface PublishCommand {
  readonly head: PublishHead
  readonly dir: CommandDir
  readonly ref: PublishedRef
}

/** A line's publish commands: at least one, in textual order (`CommandScan`). */
export type PublishCommands = readonly [PublishCommand, ...PublishCommand[]]

/**
 * What a shell line does, as far as the gate can tell: it `publishes` (every publish command
 * in it, in textual order; a literal string fed to a shell adds its own where it stands), it is
 * `clear` (publishes nothing), or it is `opaque` (it runs text the scan cannot read,
 * `… | bash` or `sh -c "$X"`; `why` names it). Textual order is the order the scan reads, not
 * the order the shell runs: a heredoc body's publishes are listed where the body is read, after
 * the rest of its owner line (`bash <<EOF && git push origin b` lists `b` before the body's). A
 * publish anywhere in the line wins over an opaque part. An opaque line is a documented limit
 * and passes (HUD ADR 0005).
 */
export type CommandScan =
  | { readonly kind: 'publishes'; readonly commands: PublishCommands }
  | { readonly kind: 'clear' }
  | { readonly kind: 'opaque'; readonly why: string }

/**
 * The stream of the branch a publish command publishes. `Stream`: the branch has one, with its
 * publish authorization. `NoStream`: the branch was resolved, and no stream carries it.
 * `Unresolved`: no one branch could be named (several refspecs, `--all`, `--mirror`, a
 * deletion, a detached HEAD); `why` says which. `Unknown`: reading it failed. A read that
 * shows an outdated journal.py is no target: the whole line's inputs are `Outdated`.
 */
export type TargetBinding =
  | { readonly kind: 'Stream'; readonly branch: BranchName; readonly stream: StreamName; readonly publish: PublishAuthorization }
  | { readonly kind: 'NoStream'; readonly branch: BranchName }
  | { readonly kind: 'Unresolved'; readonly why: string }
  | { readonly kind: 'Unknown'; readonly failure: ReadFailure }

/**
 * The session's own stream at the gate, read fresh: the fallback for a target with no stream.
 * `Stream`: the session is bound. `None`: it drives no stream. `Unknown`: reading it failed. A
 * refresh that shows an outdated journal.py is no bound stream: the inputs are `Outdated`.
 */
export type BoundStream =
  | { readonly kind: 'Stream'; readonly stream: StreamName; readonly publish: PublishAuthorization }
  | { readonly kind: 'None' }
  | { readonly kind: 'Unknown'; readonly failure: ReadFailure }

/** One publish command of a line, and the stream of the branch it publishes. */
export interface PublishTarget {
  readonly command: PublishCommand
  readonly target: TargetBinding
}

/**
 * Everything the gate decides on, built once per checked line. The first five pass with
 * nothing to check: the line publishes nothing (or is opaque), the session draws no surface,
 * the project has no sidecar, journal.py was not found, or journal.py is older than the
 * shipgate this HUD needs (`Outdated`: the gate's refresh or one of its target reads showed
 * it). The gate is a net for a forgetful model, not a boundary: during a known version skew
 * it is off, and the pane and the band say so. `Target`: the line's publishes to check, one
 * entry per publish command in textual order, and the session's bound stream.
 */
export type GateInputs =
  | { readonly kind: 'NotPublish' }
  | { readonly kind: 'NoSurface' }
  | { readonly kind: 'NoProject' }
  | { readonly kind: 'NoJournalScript' }
  | { readonly kind: 'Outdated' }
  | { readonly kind: 'Target'; readonly targets: readonly [PublishTarget, ...PublishTarget[]]; readonly bound: BoundStream }

/** Why a publish is held: its stream lacks the evidence `mr-opened` demands, or the journal could not be read. */
export type Hold =
  | { readonly kind: 'Unreviewed'; readonly head: PublishHead; readonly stream: StreamName }
  | { readonly kind: 'Unreadable'; readonly head: PublishHead; readonly failure: ReadFailure }

/** Why a command passes. `Outdated`: journal.py is older than the shipgate this HUD needs, so the gate is off. */
export type PassReason = 'NotPublish' | 'NoSurface' | 'NoProject' | 'NoJournalScript' | 'Outdated' | 'Authorized' | 'NoStream'

/** Every hold on a checked line, in textual order: at least one. */
export type Holds = readonly [Hold, ...Hold[]]

/** The gate's decision on one checked line: a pass, or a hold that names every publish command that holds. */
export type GateVerdict = { readonly kind: 'Pass'; readonly why: PassReason } | { readonly kind: 'Hold'; readonly holds: Holds }

/**
 * Every publish command in a shell line (`git push`, `gh pr create` or `gh pr new`,
 * `glab mr create` or `glab mr new`), in textual order (a heredoc body's after the rest of its
 * owner line), each with the directory it runs in and the ref it publishes; `clear` when the
 * line publishes nothing; `opaque` when it feeds text the scan cannot read to a shell and
 * publishes nothing the scan can read.
 *
 * One quote-aware pass (`scanFrom`) over the whole line. Outside quotes, `&&`, `||`, `;`, `|`, `&`, a newline,
 * `(` and `)` end a command. Inside single or double quotes nothing does: the quoted run is one
 * word and never a command, so `grep "git push" f` publishes nothing. An unquoted `$(…)`,
 * backtick or `<(…)` run stays part of its word and is read as a command line of its own. A
 * redirection ends a word, and it and its target are dropped (`git push>/dev/null`). A `#`
 * that starts a word comments out the rest of the line. A backslash before a newline continues
 * the line. A heredoc body (`<<EOF` up to the line `EOF`) is a command line only when the
 * command it is fed to is a shell (`bash <<EOF`). A literal string fed to a shell (`sh -c '…'`,
 * `eval '…'`, `bash <<< '…'`) is a command line too; text the scan cannot read fed to a shell
 * (`… | bash`, `sh -c "$X"`, `bash <(…)`) is opaque. Matching is on whole words, so
 * `git pushd`, `gh pr list` and `git stash push` do not match.
 *
 * The directory follows the shell: a `cd` that surely ran before the command (joined by `&&`,
 * `;` or a newline, not in a subshell, a pipeline, a background list or a compound command)
 * enters its directory, relative ones composed in order and an absolute one resetting; `git -C`
 * enters after it. A `cd` the scan cannot read, or one that may not have run, makes it
 * `Unreadable`.
 */
export function scanCommand(command: string): CommandScan {
  return scanFrom(command, SHELL_DIR)
}

/**
 * The gate's decision, total over GateInputs. Each publish command is judged on its own: its
 * target's stream decides (authorized passes, held holds `Unreviewed`, a failed read holds
 * `Unreadable`); a target with no stream (`NoStream`) or no resolvable branch (`Unresolved`)
 * falls back to `bound` the same way, and no bound stream passes (`NoStream`). The line holds
 * when any command holds, and the hold names every command that holds, in textual order (one "Let
 * it through once" covers the line, so the person is asked about all of them); it passes only
 * when every command passes, `Authorized` when any was checked against a stream. A failed read
 * never passes; an outdated journal.py (`Outdated`) passes with nothing checked, as a missing
 * one does.
 */
export function gateVerdict(inputs: GateInputs): GateVerdict {
  switch (inputs.kind) {
    case 'NotPublish':
    case 'NoSurface':
    case 'NoProject':
    case 'NoJournalScript':
    case 'Outdated':
      return { kind: 'Pass', why: inputs.kind }
    case 'Target': {
      const [first, ...rest] = inputs.targets
      const judge = (publish: PublishTarget): PublishVerdict => targetVerdict(publish.command.head, publish.target, inputs.bound)
      return rest.reduce((line, publish) => lineVerdict(line, judge(publish)), judge(first))
    }
    default:
      return absurd(inputs)
  }
}

/** The verdict on publish commands checked so far: a pass on an authorized stream or on no stream, or every hold, in textual order. */
type PublishVerdict = { readonly kind: 'Pass'; readonly why: Extract<PassReason, 'Authorized' | 'NoStream'> } | { readonly kind: 'Hold'; readonly holds: Holds }

/** The line's verdict so far, with the next command's: the holds of both, in order; else an authorized pass; else no stream. */
function lineVerdict(line: PublishVerdict, next: PublishVerdict): PublishVerdict {
  if (line.kind === 'Hold') return next.kind === 'Hold' ? { kind: 'Hold', holds: [...line.holds, ...next.holds] } : line
  if (next.kind === 'Hold') return next
  return line.why === 'Authorized' ? line : next
}

/** One held command as a verdict. */
const holding = (hold: Hold): PublishVerdict => ({ kind: 'Hold', holds: [hold] })

/** The verdict on the target's stream; a target with no stream or no one branch defers to the bound stream. */
function targetVerdict(head: PublishHead, target: TargetBinding, bound: BoundStream): PublishVerdict {
  switch (target.kind) {
    case 'Stream':
      return streamVerdict(head, target.stream, target.publish)
    case 'Unknown':
      return holding({ kind: 'Unreadable', head, failure: target.failure })
    case 'NoStream':
    case 'Unresolved':
      return boundVerdict(head, bound)
    default:
      return absurd(target)
  }
}

/** The verdict on the session's own stream: none passes, a failed read holds. */
function boundVerdict(head: PublishHead, bound: BoundStream): PublishVerdict {
  switch (bound.kind) {
    case 'Stream':
      return streamVerdict(head, bound.stream, bound.publish)
    case 'None':
      return { kind: 'Pass', why: 'NoStream' }
    case 'Unknown':
      return holding({ kind: 'Unreadable', head, failure: bound.failure })
    default:
      return absurd(bound)
  }
}

/** An authorized stream passes; a held one holds `Unreviewed`. */
function streamVerdict(head: PublishHead, stream: StreamName, publish: PublishAuthorization): PublishVerdict {
  switch (publish.kind) {
    case 'authorized':
      return { kind: 'Pass', why: 'Authorized' }
    case 'held':
      return holding({ kind: 'Unreviewed', head, stream })
    default:
      return absurd(publish)
  }
}

// ---------------------------------------------------------------------------------------
// The scan: words and dirs
// ---------------------------------------------------------------------------------------

/**
 * One word as the shell reads it: its text with quotes removed. `isLiteral`: nothing in it
 * expands (no `$`, backtick, leading `~` or glob outside single quotes), so the text is what
 * the command gets. `isProcess`: it holds a process substitution, `<(…)` or `>(…)`.
 */
interface Word {
  readonly text: string
  readonly isLiteral: boolean
  readonly isProcess: boolean
}

/** The dir at a point of a line; null where no run gets (a `cd` is taken to succeed, so its failure branch is null). */
type Reach = CommandDir | null

/** The shell's own directory, the HEAD of a dir, a line that publishes nothing: the values with no payload. */
const SHELL_DIR: CommandDir = { kind: 'Shell' }
const HEAD: PublishedRef = { kind: 'Head' }
const CLEAR: CommandScan = { kind: 'clear' }

/** A dir, a ref or a line the scan cannot read, and why. */
const unreadable = (why: string): CommandDir => ({ kind: 'Unreadable', why })
const unresolved = (why: string): PublishedRef => ({ kind: 'Unresolved', why })
const opaque = (why: string): CommandScan => ({ kind: 'opaque', why })

/** Why a dir is unreadable when a `cd` before the command may or may not have entered it. */
const MAY_NOT_RUN = 'a `cd` before the command may not have run'
const RUNS_ON_FAILURE = 'the command runs only when a `cd` before it fails'
const IN_COMPOUND = 'a `cd` inside a compound command or a function may not run'
const PIPELINE_CD = 'a `cd` at the end of a pipeline runs in the shell or in a subshell, by shell'

/** Do two dirs name the same place? */
function isSameDir(a: CommandDir, b: CommandDir): boolean {
  switch (a.kind) {
    case 'Shell':
      return b.kind === 'Shell'
    case 'Path':
      return b.kind === 'Path' && b.path === a.path
    case 'Unreadable':
      return b.kind === 'Unreadable'
    default:
      return absurd(a)
  }
}

/** The dir a point is reached with by two runs: the one dir when they agree, else `Unreadable`. */
function joinDirs(a: Reach, b: Reach): Reach {
  if (a === null) return b
  if (b === null || isSameDir(a, b)) return a
  if (a.kind === 'Unreadable') return a
  return b.kind === 'Unreadable' ? b : unreadable(MAY_NOT_RUN)
}

/** `dir` after entering the literal `path`: an absolute path replaces it, a relative one joins it, an empty one leaves it. */
function enter(dir: CommandDir, path: string): CommandDir {
  if (path === '') return dir
  if (path.startsWith('/')) return { kind: 'Path', path }
  switch (dir.kind) {
    case 'Shell':
      return { kind: 'Path', path }
    case 'Path':
      return { kind: 'Path', path: `${dir.path.replace(/\/+$/, '')}/${path}` }
    case 'Unreadable':
      return dir
    default:
      return absurd(dir)
  }
}

/** The words after a command's options: those starting with `-` dropped, up to and with `--`; a lone `-` is an operand. */
function operandsOf(args: readonly Word[]): readonly Word[] {
  const end = args.findIndex(w => w.text === '--' || w.text === '-' || !w.text.startsWith('-'))
  if (end < 0) return []
  return args[end]?.text === '--' ? args.slice(end + 1) : args.slice(end)
}

/** The dir a `cd`, `pushd` or `popd` leaves, entered from `dir`; null when the command is none of them. */
function cdTo(command: readonly Word[], dir: CommandDir): CommandDir | null {
  const name = command[0]?.text.replace(/^\\/, '')
  if (name === 'popd') return unreadable('`popd` returns to a directory the scan cannot read')
  if (name !== 'cd' && name !== 'pushd') return null
  const operands = operandsOf(command.slice(1))
  const target = operands[0]
  if (target === undefined) return unreadable(`\`${name}\` with no directory goes to one the scan cannot read`)
  if (operands.length > 1) return unreadable(`\`${name}\` with two arguments`)
  if (target.text === '-') return unreadable('`cd -` returns to the previous directory')
  if (!target.isLiteral || target.text === '' || (name === 'pushd' && /^\+\d+$/.test(target.text))) {
    return unreadable(`\`${name}\` to a directory the scan cannot read`)
  }
  return enter(dir, target.text)
}

/** Words that move the command after them to another directory or repository: a wrapper's `-C` / `--chdir`, `GIT_DIR=`. */
const MOVES_DIR = /^(GIT_DIR=|GIT_WORK_TREE=|-C|-D|--chdir)/

/** The dir `git`'s global options leave, from `dir`: each `-C` entered in order; `--git-dir` or `--work-tree` name another repository. */
function gitDir(command: readonly Word[], dir: CommandDir): CommandDir {
  const options = command.slice(1, skipOptions(command.map(w => w.text), 1, GIT_VALUE_OPTIONS))
  if (options.some(w => /^--(git-dir|work-tree)(=|$)/.test(w.text))) return unreadable('`--git-dir` or `--work-tree` names another repository')
  return options.reduce<CommandDir>((at, word, index) => (word.text === '-C' ? enterWord(at, options[index + 1]) : at), dir)
}

/** `dir` after `git -C <word>`: a word the scan cannot read makes it `Unreadable`. */
function enterWord(dir: CommandDir, word: Word | undefined): CommandDir {
  if (word === undefined) return dir
  return word.isLiteral ? enter(dir, word.text) : unreadable('`git -C` names a directory the scan cannot read')
}

// ---------------------------------------------------------------------------------------
// The scan: what one command publishes
// ---------------------------------------------------------------------------------------

/** `git push` options that take the next word as their value, unless written `--opt=value`. */
const PUSH_VALUE_OPTIONS = new Set(['--repo', '-o', '--push-option', '--receive-pack', '--exec'])

/** `git push` options that push no one branch, and why. */
const PUSH_UNRESOLVED = new Map([
  ['--all', '`--all` pushes every branch'],
  ['--branches', '`--branches` pushes every branch'],
  ['--mirror', '`--mirror` pushes every ref'],
  ['--tags', '`--tags` pushes every tag'],
  ['--delete', '`--delete` is a deletion'],
  ['--prune', '`--prune` deletes remote branches'],
])

/** `git push`'s arguments as read so far: the operands (remote, refspecs), or why no one branch is pushed. */
interface PushArgs {
  readonly operands: readonly Word[]
  readonly why: string | null
}

/** Reads `git push`'s arguments from `at`. Options may follow operands (`git push origin --tags`) until `--`. */
function pushArgs(args: readonly Word[], at: number, isInOptions: boolean, read: PushArgs): PushArgs {
  const word = args[at]
  if (word === undefined || read.why !== null) return read
  const text = word.text
  if (!isInOptions || !text.startsWith('-') || text === '-') {
    return pushArgs(args, at + 1, isInOptions, { ...read, operands: [...read.operands, word] })
  }
  if (text === '--') return pushArgs(args, at + 1, false, read)
  if (text.startsWith('--')) {
    const why = PUSH_UNRESOLVED.get(text.split('=')[0] ?? text)
    if (why !== undefined) return { ...read, why }
    return pushArgs(args, at + (PUSH_VALUE_OPTIONS.has(text) ? 2 : 1), true, read)
  }
  // a cluster of short options (`-fu`): `-d` deletes; `-o` takes the rest, or the next word
  const letters = text.slice(1)
  const deletes = letters.indexOf('d')
  const option = letters.indexOf('o')
  if (deletes >= 0 && (option < 0 || deletes < option)) return { ...read, why: '`-d` is a deletion' }
  return pushArgs(args, at + (option === letters.length - 1 ? 2 : 1), true, read)
}

/** The ref one literal refspec publishes: its source branch (`+src:dst` gives `src`, `refs/heads/x` gives `x`). */
function refspecRef(refspec: string): PublishedRef {
  const spec = refspec.replace(/^\+/, '')
  if (spec === ':') return unresolved('`:` pushes every matching branch')
  const source = spec.split(':')[0] ?? ''
  if (source === '') return unresolved('an empty source deletes the remote branch: a deletion')
  if (source.includes('*')) return unresolved('a refspec pattern pushes every matching branch')
  // a revision suffix (`x~2`, `HEAD^`, `@{u}`) names a commit of the branch it starts from
  const revision = source.replace(/(~|\^|@\{).*$/, '')
  if (revision === '' || revision === 'HEAD' || revision === '@') return HEAD
  const name = revision.replace(/^refs\/heads\//, '')
  return name === '' ? unresolved('a refspec with an empty branch name') : { kind: 'Branch', name }
}

/** The ref `git push <args>` publishes: the HEAD with no refspec, one refspec's source branch, else Unresolved. */
function pushRef(args: readonly Word[]): PublishedRef {
  const read = pushArgs(args, 0, true, { operands: [], why: null })
  if (read.why !== null) return unresolved(read.why)
  // an unquoted `$X` may split into several words, flags among them
  if (read.operands.some(w => !w.isLiteral)) return unresolved('a `git push` argument the scan cannot read')
  if (read.operands.length > 2) return unresolved('several refspecs push several branches')
  const refspec = read.operands[1]
  return refspec === undefined ? HEAD : refspecRef(refspec.text)
}

/** The option of `gh pr create` / `glab mr create` that names the branch, the options that take a value, and the branch in its value. */
interface BranchOption {
  readonly short: string
  readonly long: string
  readonly valueOptions: ReadonlySet<string>
  readonly branchOf: (value: string) => string
}

/** `gh pr create --head <branch>` or `--head <owner>:<branch>`. */
const GH_HEAD: BranchOption = {
  short: '-H',
  long: '--head',
  valueOptions: new Set([
    ...['-a', '--assignee', '-B', '--base', '-b', '--body', '-F', '--body-file', '-l', '--label', '-m', '--milestone'],
    ...['-p', '--project', '-r', '--reviewer', '-T', '--template', '-t', '--title', '-R', '--repo', '--recover'],
  ]),
  branchOf: value => value.slice(value.indexOf(':') + 1),
}

/** `glab mr create --source-branch <branch>`. */
const GLAB_SOURCE: BranchOption = {
  short: '-s',
  long: '--source-branch',
  valueOptions: new Set([
    ...['-a', '--assignee', '-d', '--description', '-H', '--head', '-i', '--related-issue', '-l', '--label'],
    ...['-m', '--milestone', '--reviewer', '-b', '--target-branch', '--target-project', '-t', '--title', '-R', '--repo'],
  ]),
  branchOf: value => value,
}

/** The value of the last `option` from `at` (`-H x`, `--head x`, `--head=x`, `-Hx`); other options' values are skipped. */
function optionValue(args: readonly Word[], option: BranchOption, at: number, found: Word | null): Word | null {
  const word = args[at]
  if (word === undefined) return found
  const text = word.text
  if (text === option.short || text === option.long) return optionValue(args, option, at + 2, args[at + 1] ?? found)
  if (text.startsWith(`${option.long}=`)) return optionValue(args, option, at + 1, { ...word, text: text.slice(option.long.length + 1) })
  if (text.startsWith(option.short) && !text.startsWith('--')) {
    return optionValue(args, option, at + 1, { ...word, text: text.slice(option.short.length) })
  }
  return optionValue(args, option, at + (option.valueOptions.has(text) ? 2 : 1), found)
}

/** The ref `gh pr create` / `glab mr create` publishes: the named branch, else the HEAD. */
function optionRef(args: readonly Word[], option: BranchOption): PublishedRef {
  const value = optionValue(args, option, 0, null)
  if (value === null || value.text === '') return HEAD
  if (!value.isLiteral) return unresolved(`\`${option.long}\` names a branch the scan cannot read`)
  return { kind: 'Branch', name: option.branchOf(value.text) }
}

/** A publish command's head and the ref it publishes. */
interface Published {
  readonly head: PublishHead
  readonly ref: PublishedRef
}

/** The publish one command's words (wrappers dropped) start, or null. */
function publishOf(command: readonly Word[]): Published | null {
  const words = command.map(w => w.text)
  const program = nameOf(words[0] ?? '')
  if (program === 'git') {
    const verb = skipOptions(words, 1, GIT_VALUE_OPTIONS)
    if (words[verb] === 'push') return { head: 'git push', ref: pushRef(command.slice(verb + 1)) }
    // `git subtree push` publishes a split of HEAD; `git stash push` does not publish
    if (words[verb] === 'subtree' && words[skipOptions(words, verb + 1, GIT_VALUE_OPTIONS)] === 'push') return { head: 'git push', ref: HEAD }
    return null
  }
  if (program === 'gh' || program === 'glab') {
    const noun = skipOptions(words, 1, REPO_OPTIONS)
    if (words[noun] !== (program === 'gh' ? 'pr' : 'mr')) return null
    const verb = skipOptions(words, noun + 1, REPO_OPTIONS)
    if (words[verb] !== 'create' && words[verb] !== 'new') return null
    const args = command.slice(verb + 1)
    return program === 'gh' ? { head: 'gh pr create', ref: optionRef(args, GH_HEAD) } : { head: 'glab mr create', ref: optionRef(args, GLAB_SOURCE) }
  }
  return null
}

/** How a shell reads its arguments: `-c` runs a string, `-s` reads stdin; the first operand is the string, or else a script file. */
interface ShellArgs {
  readonly isString: boolean
  readonly readsStdin: boolean
  readonly operand: Word | null
}

/** Shell options that take the next word as their value. */
const SHELL_VALUE_OPTIONS = new Set(['-o', '+o', '-O', '+O', '--rcfile', '--init-file'])

/** Reads a shell's arguments from `at`. */
function shellArgs(args: readonly Word[], at: number, isString: boolean, readsStdin: boolean): ShellArgs {
  const word = args[at]
  if (word === undefined) return { isString, readsStdin, operand: null }
  const text = word.text
  if (text === '--' || text === '-') return { isString, readsStdin, operand: args[at + 1] ?? null }
  if (text === '--command') return { isString: true, readsStdin, operand: args[at + 1] ?? null }
  if (text.startsWith('--command=')) return { isString: true, readsStdin, operand: { ...word, text: text.slice('--command='.length) } }
  if (SHELL_VALUE_OPTIONS.has(text)) return shellArgs(args, at + 2, isString, readsStdin)
  if (text.startsWith('--')) return shellArgs(args, at + 1, isString, readsStdin)
  if (/^[-+][A-Za-z]+$/.test(text)) {
    // a cluster of short options (`-lc`, `-eo pipefail`): `-c` runs a string, `-s` reads stdin, `o` takes a value
    const letters = text.slice(1)
    const isSet = text.startsWith('-')
    const next = at + (/[oO]/.test(letters) ? 2 : 1)
    return shellArgs(args, next, isString || (isSet && letters.includes('c')), readsStdin || (isSet && letters.includes('s')))
  }
  return { isString, readsStdin, operand: word }
}

/** Text fed to a shell, read as a line of its own: what it publishes, else clear when literal, else opaque. */
function fedScan(name: string, text: Word, dir: CommandDir): CommandScan {
  const inner = scanFrom(text.text, dir)
  if (inner.kind !== 'clear') return inner
  return text.isLiteral ? CLEAR : opaque(`\`${name}\` runs text the scan cannot read`)
}

/** What a shell (or `source`) runs: its `-c` string, its here-string, a process substitution, or text piped to it. */
function shellScan(program: string, args: readonly Word[], hereStrings: readonly Word[], isFed: boolean, dir: CommandDir): CommandScan {
  const read = shellArgs(args, 0, false, false)
  if (read.isString) return read.operand === null ? CLEAR : fedScan(`${program} -c`, read.operand, dir)
  const hereString = hereStrings[0]
  if (hereString !== undefined) return fedScan(program, hereString, dir)
  if (read.operand?.isProcess === true) return opaque(`\`${program}\` runs a process substitution`)
  const isStdin = read.readsStdin || read.operand === null || read.operand.text === '/dev/stdin'
  return isStdin && isFed ? opaque(`text fed to \`${program}\` on stdin`) : CLEAR
}

/** One command's words: the leading assignments, shell words and wrappers, and the command they run. */
interface SplitCommand {
  readonly prefix: readonly Word[]
  readonly command: readonly Word[]
}

/** Splits one command's words where `unwrap` finds the command. */
function splitCommand(words: readonly Word[]): SplitCommand {
  const start = words.length - unwrap(words.map(w => w.text)).length
  return { prefix: words.slice(0, start), command: words.slice(start) }
}

/** What one command does: it publishes (with its dir), it runs text fed to a shell, or it is clear. */
function commandScan(words: readonly Word[], hereStrings: readonly Word[], isFed: boolean, dir: CommandDir): CommandScan {
  const { prefix, command } = splitCommand(words)
  const published = publishOf(command)
  if (published !== null) {
    const moved = prefix.some(w => MOVES_DIR.test(w.text))
    const at = moved ? unreadable('a wrapper or an assignment moves the command to another directory or repository') : dir
    return { kind: 'publishes', commands: [{ head: published.head, dir: published.head === 'git push' ? gitDir(command, at) : at, ref: published.ref }] }
  }
  const program = nameOf(command[0]?.text ?? '')
  if (SHELLS.has(program) || program === 'source' || program === '.') return shellScan(program, command.slice(1), hereStrings, isFed, dir)
  if (program === 'eval') {
    const args = command.slice(1)
    return fedScan('eval', { text: args.map(w => w.text).join(' '), isLiteral: args.every(w => w.isLiteral), isProcess: false }, dir)
  }
  return CLEAR
}

/** Keywords that open a compound command whose body may not run, and those that close one. */
const OPENS = new Set(['if', 'while', 'until', 'for', 'case', 'select'])
const CLOSES = new Set(['fi', 'done', 'esac'])
const LEADING_KEYWORDS = new Set([...OPENS, ...CLOSES, 'then', 'elif', 'else', 'do', 'function', 'time', 'coproc', '!', '{', '}'])

/** The compound commands a segment's leading keywords open and close, and whether it defines a function. */
interface Keywords {
  readonly opens: number
  readonly closes: number
  readonly hasFunction: boolean
}

/** The keywords a segment starts with. */
function keywordsOf(words: readonly Word[]): Keywords {
  const end = words.findIndex(w => !LEADING_KEYWORDS.has(w.text))
  const lead = end < 0 ? words : words.slice(0, end)
  return {
    opens: lead.filter(w => OPENS.has(w.text)).length,
    closes: lead.filter(w => CLOSES.has(w.text)).length,
    hasFunction: lead.some(w => w.text === 'function'),
  }
}

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

/** Shells: they run a `-c` string, a script file, or the text on their stdin. */
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'fish'])

/** Commands that run the text fed to them: their heredoc bodies are command lines too. */
const TEXT_RUNNERS = new Set([...SHELLS, 'eval', 'source', '.'])

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
  return TEXT_RUNNERS.has(nameOf(unwrap(owner)[0] ?? ''))
}

/** The index of the first non-option word from `start`; `valueOptions` also skip their value. */
function skipOptions(words: readonly string[], start: number, valueOptions: ReadonlySet<string>): number {
  let i = start
  while (i < words.length && (words[i] ?? '').startsWith('-')) {
    i += valueOptions.has(words[i] ?? '') ? 2 : 1
  }
  return i
}

/** A separator as the dir state reads it; `end` is the line's end. */
type Separator = '&&' | '||' | '|' | ';' | '&' | '\n' | '(' | ')' | 'end'

/** Where one command ends and the next begins, outside quotes, and the separator it is (`|&` pipes). Longest first. */
const SEPARATORS: readonly (readonly [string, Separator])[] = [
  ['&&', '&&'],
  ['||', '||'],
  ['|&', '|'],
  [';', ';'],
  ['|', '|'],
  ['&', '&'],
  ['\n', '\n'],
  ['(', '('],
  [')', ')'],
]

/** How the next element joins the one before: it starts an and-or list, follows `&&` or `||`, or is piped into. */
type Join = 'list' | 'and' | 'or' | 'pipe'

/** The join a separator leaves for the element after it. */
const JOIN_AFTER: Readonly<Record<Separator, Join>> = {
  '&&': 'and',
  '||': 'or',
  '|': 'pipe',
  ';': 'list',
  '&': 'list',
  '\n': 'list',
  '(': 'list',
  ')': 'list',
  end: 'list',
}

/**
 * One list level of `scanFrom`'s pass (the line, or a `( … )` subshell) and the dir state the
 * and-or rules thread through it. Mutable: part of the pass's documented state.
 */
interface Frame {
  /** The dir the current and-or list started in: where a `… &` leaves the shell. */
  entry: Reach
  /** The dir after the last pipeline when it succeeded, and when it failed. */
  ok: Reach
  fail: Reach
  /** `ok` and `fail` before the current pipeline, which its `&&` or `||` combines with. */
  priorOk: Reach
  priorFail: Reach
  /** How the current pipeline joined its and-or list. */
  chain: 'list' | 'and' | 'or'
  /** The dir the current pipeline started in, and how many of its elements have closed. */
  pipeIn: Reach
  pipeLength: number
  /** How the next element joins. */
  join: Join
  /** A `( … )` element that closed and waits for its separator. */
  hasOpenGroup: boolean
}

const newFrame = (start: CommandDir): Frame => ({
  entry: start,
  ok: start,
  fail: null,
  priorOk: start,
  priorFail: null,
  chain: 'list',
  pipeIn: start,
  pipeLength: 0,
  join: 'list',
  hasOpenGroup: false,
})

/** Starts the frame's next pipeline from `input`, joined by `chain`. Part of `scanFrom`'s pass: mutates the frame. */
function startPipeline(frame: Frame, chain: Frame['chain'], input: Reach): Reach {
  frame.priorOk = frame.ok
  frame.priorFail = frame.fail
  frame.chain = chain
  frame.pipeIn = input
  frame.pipeLength = 0
  return input
}

/** Opens the frame's next element: the dir it starts in, by the join before it. Part of `scanFrom`'s pass: mutates the frame. */
function openElement(frame: Frame): Reach {
  switch (frame.join) {
    case 'pipe':
      return frame.pipeIn
    case 'list':
      frame.entry = joinDirs(frame.ok, frame.fail)
      return startPipeline(frame, 'list', frame.entry)
    case 'and':
      return startPipeline(frame, 'and', frame.ok)
    case 'or':
      return startPipeline(frame, 'or', frame.fail)
    default:
      return absurd(frame.join)
  }
}

/**
 * The dirs a pipeline leaves on success and on failure. A lone `cd` enters its dir and is taken
 * to succeed; a `cd` at a pipeline's end may run in the shell (zsh) or in a subshell (bash);
 * anything else leaves the dir it started in.
 */
function pipelineEnd(input: Reach, length: number, cd: CommandDir | null): readonly [Reach, Reach] {
  if (input === null) return [null, null]
  if (cd === null) return [input, input]
  if (length === 1) return [cd, null]
  const lost = unreadable(PIPELINE_CD)
  return [lost, lost]
}

/**
 * Closes the frame's open element at `separator`: `cd` is the dir it enters, if it is a `cd`.
 * `|` continues the pipeline; else the pipeline ends and joins its and-or list, and `&` sends
 * the list to the background, leaving the dir it started in. Part of `scanFrom`'s pass: mutates
 * the frame.
 */
function closeElement(frame: Frame, cd: CommandDir | null, separator: Separator): void {
  frame.hasOpenGroup = false
  frame.pipeLength += 1
  frame.join = JOIN_AFTER[separator]
  if (separator === '|') return
  const [ok, fail] = pipelineEnd(frame.pipeIn, frame.pipeLength, cd)
  frame.ok = frame.chain === 'or' ? joinDirs(frame.priorOk, ok) : ok
  frame.fail = frame.chain === 'and' ? joinDirs(frame.priorFail, fail) : fail
  if (separator === '&') {
    frame.ok = frame.entry
    frame.fail = null
  }
}

/** A segment while the pass reads it. Mutable: part of `scanFrom`'s pass. */
interface SegmentDraft {
  readonly words: Word[]
  readonly substitutions: string[]
  readonly hereStrings: Word[]
  /** A process substitution is its stdin (`bash < <(…)`). */
  isFedProcess: boolean
  /** The dir it runs in, set when it ends: a heredoc fed to it runs there too. */
  dir: CommandDir
}

const draftSegment = (dir: CommandDir): SegmentDraft => ({ words: [], substitutions: [], hereStrings: [], isFedProcess: false, dir })

/** A heredoc waiting for its body: the terminator, `<<-` (leading tabs stripped), the segment it feeds. */
interface Heredoc {
  readonly terminator: string
  readonly stripsTabs: boolean
  readonly owner: SegmentDraft
}

/** What the next word is: an argument, a redirection's target (an input one may be a process substitution), or a here-string. */
type WordRole = 'argument' | 'target' | 'input' | 'hereString'

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
 * The scan of `command` run from `start`: `scanCommand`'s pass (its doc says what it reads),
 * also run on the text a line feeds to a shell or a substitution, from the dir that text runs in.
 *
 * STATEFUL EXCEPTION (HUD ADR 0006): a tokenizer. It reads the line one character at a time and
 * keeps the word, the segment, the heredocs waiting for their bodies, the dir frames, and the
 * publish commands and opaque parts read so far, in local mutable state (`startPipeline`,
 * `openElement` and `closeElement` mutate a frame of it). Nothing outside the pass sees that
 * state; every helper it calls on a finished word or segment is pure.
 */
function scanFrom(command: string, start: CommandDir): CommandScan {
  const line = command.replace(/\\\r?\n/g, ' ')
  let text: string | null = null
  let isLiteral = true
  let isProcess = false
  let role: WordRole = 'argument'
  let segment = draftSegment(start)
  let heredocs: Heredoc[] = []
  let frame = newFrame(start)
  const outer: Frame[] = []
  let compoundDepth = 0
  let hasFunction = false
  const opaques: string[] = []
  const published: PublishCommand[] = []

  /** A scan of a part of the line: its publish commands join the line's, in order; an opaque part is remembered. */
  const note = (scan: CommandScan): void => {
    switch (scan.kind) {
      case 'publishes':
        published.push(...scan.commands)
        return
      case 'opaque':
        opaques.push(scan.why)
        return
      case 'clear':
        return
      default:
        return absurd(scan)
    }
  }

  const endWord = (): void => {
    if (text === null) return
    const word: Word = { text, isLiteral, isProcess }
    if (role === 'argument') segment.words.push(word)
    else if (role === 'hereString') segment.hereStrings.push(word)
    else if (role === 'input' && isProcess) segment.isFedProcess = true
    role = 'argument'
    text = null
    isLiteral = true
    isProcess = false
  }

  /** Ends the segment at `separator`: notes what it publishes, then moves the dir state past it. */
  const endSegment = (separator: Separator): void => {
    endWord()
    role = 'argument'
    const built = segment
    segment = draftSegment(start)
    const isEmpty = built.words.length === 0 && built.substitutions.length === 0 && built.hereStrings.length === 0
    if (frame.hasOpenGroup) {
      // a `( … )` element ends here; words after it (a syntax error) count as a command of their own
      closeElement(frame, null, isEmpty ? separator : ';')
    }
    if (isEmpty) return
    const isPiped = frame.join === 'pipe'
    const dir = openElement(frame) ?? unreadable(RUNS_ON_FAILURE)
    built.dir = dir
    // a substitution runs before the segment's command, in the segment's dir
    for (const inner of built.substitutions) note(scanFrom(inner, dir))
    const keywords = keywordsOf(built.words)
    compoundDepth = Math.max(0, compoundDepth + keywords.opens - keywords.closes)
    hasFunction = hasFunction || keywords.hasFunction
    note(commandScan(built.words, built.hereStrings, isPiped || built.isFedProcess, dir))
    const entered = cdTo(splitCommand(built.words).command, dir)
    closeElement(frame, entered !== null && (compoundDepth > 0 || hasFunction) ? unreadable(IN_COMPOUND) : entered, separator)
  }

  let i = 0
  while (i < line.length) {
    const ch = line[i] ?? ''
    if (ch === "'" || ch === '"') {
      // a quoted run: one word (joined with what touches it), never cut, never a command; in
      // double quotes an unescaped `$` or backtick still expands
      let j = i + 1
      let quoted = ''
      while (j < line.length && line[j] !== ch) {
        if (ch === '"' && line[j] === '\\' && j + 1 < line.length) j += 1
        else if (ch === '"' && (line[j] === '$' || line[j] === '`')) isLiteral = false
        quoted += line[j] ?? ''
        j += 1
      }
      text = (text ?? '') + quoted
      i = j + 1
      continue
    }
    if (ch === '\\') {
      text = (text ?? '') + (line[i + 1] ?? '')
      i += 2
      continue
    }
    if (line.startsWith('<<<', i)) {
      endWord()
      role = 'hereString'
      i += 3
      continue
    }
    if (line.startsWith('<<', i)) {
      endWord()
      const dash = line[i + 2] === '-' ? 1 : 0
      const { word: terminator, end } = terminatorAt(line, i + 2 + dash)
      if (terminator) heredocs.push({ terminator, stripsTabs: dash === 1, owner: segment })
      i = end
      continue
    }
    if (ch === '#' && text === null) {
      // a comment: the rest of the line, up to (not past) the newline
      const cut = line.indexOf('\n', i)
      i = cut < 0 ? line.length : cut
      continue
    }
    if (line.startsWith('$(', i) || ch === '`' || ((ch === '<' || ch === '>') && line[i + 1] === '(')) {
      // a command or process substitution: part of its word, its text a command line read
      // when the segment ends (it runs in the segment's dir, before the segment's command)
      const isBacktick = ch === '`'
      const open = isBacktick ? 1 : 2
      const close = substitutionEnd(line, i + open, isBacktick)
      segment.substitutions.push(line.slice(i + open, close))
      isProcess = isProcess || (ch !== '$' && !isBacktick)
      text = (text ?? '') + line.slice(i, close + 1)
      isLiteral = false
      i = close + 1
      continue
    }
    if (ch === '<' || ch === '>' || line.startsWith('&>', i)) {
      // a redirection: a digit run before it (`2>`) is its fd, not a word; the operator and
      // its target are dropped (`>`, `>>`, `>&2`, `<in`, `<>`, `>|`, `&>log`)
      if (text !== null && /^\d+$/.test(text)) text = null
      endWord()
      i += 1
      while (i < line.length && /[<>&|]/.test(line[i] ?? '')) i += 1
      role = ch === '<' ? 'input' : 'target'
      continue
    }
    const separator = SEPARATORS.find(([mark]) => line.startsWith(mark, i))
    if (separator !== undefined) {
      const [mark, op] = separator
      if (op === '(' && /^\(\s*\)/.test(line.slice(i))) {
        // `f()`: a function definition; its body runs when called, if ever
        endSegment(';')
        hasFunction = true
        i = line.indexOf(')', i) + 1
        continue
      }
      endSegment(op)
      if (op === '(') {
        // a subshell: an element of the list around it, with a list of its own inside
        const input = openElement(frame) ?? unreadable(RUNS_ON_FAILURE)
        frame.hasOpenGroup = true
        outer.push(frame)
        frame = newFrame(input)
      }
      if (op === ')') frame = outer.pop() ?? frame
      i += mark.length
      if (op === '\n' && heredocs.length > 0) {
        for (const heredoc of heredocs) {
          const body: string[] = []
          while (i <= line.length) {
            const cut = line.indexOf('\n', i)
            const next = cut < 0 ? line.length : cut
            const bodyLine = line.slice(i, next)
            i = next + 1
            if ((heredoc.stripsTabs ? bodyLine.replace(/^\t+/, '') : bodyLine) === heredoc.terminator) break
            body.push(bodyLine)
            if (cut < 0) break
          }
          if (feedsShell(heredoc.owner.words.map(w => w.text))) note(scanFrom(body.join('\n'), heredoc.owner.dir))
        }
        heredocs = []
      }
      continue
    }
    if (/\s/.test(ch)) endWord()
    else {
      // an unquoted `$`, glob, brace or leading `~` expands: the word is not literal
      if (ch === '$' || /[*?[{}]/.test(ch) || (ch === '~' && text === null)) isLiteral = false
      text = (text ?? '') + ch
    }
    i += 1
  }
  endSegment('end')
  // a publish anywhere wins over an opaque part
  const [first, ...rest] = published
  if (first !== undefined) return { kind: 'publishes', commands: [first, ...rest] }
  return opaques[0] !== undefined ? opaque(opaques[0]) : CLEAR
}

/** The head of the first publish command in a shell line (`scanCommand`), or null: the gate's fail-closed `.catch` reads it. */
export function publishCommandOf(command: string): PublishHead | null {
  const scan = scanCommand(command)
  return scan.kind === 'publishes' ? scan.commands[0].head : null
}

const MISSING =
  'a `review-verdict` with `verdict: ready`, or a `gate-decision` with `gate: publish`, `raised_by: user` and ' +
  '`decision: publish`, recorded after the last `task-done`'

/** Where the user's word on a held publish is taken: the gate's own dialog, never a record the model writes. */
const USER_DECIDES =
  'or stop and ask the user: their decision is taken at the dialog this gate shows ("Let it through once"), never recorded on their behalf. Then run the command again.'

/** What a hold is about: the stream that lacks the evidence, or the failure that kept the journal from being read (D14: never a stale stream). */
function subjectOf(hold: Hold): string {
  switch (hold.kind) {
    case 'Unreviewed':
      return `stream ${hold.stream}`
    case 'Unreadable':
      return `the stream of the branch it publishes: the journal could not be read (${failureText(hold.failure)})`
    default:
      return absurd(hold)
  }
}

/** One held command as the texts name it: its head, and its stream or the failure. */
const heldCommand = (hold: Hold): string => `\`${hold.head}\` for ${subjectOf(hold)}`

/** `a`, `a and b`, `a, b and c`. */
const andList = (items: readonly [string, ...string[]]): string => {
  const last = items[items.length - 1] ?? items[0]
  return items.length === 1 ? items[0] : `${items.slice(0, -1).join(', ')} and ${last}`
}

/**
 * What the gate did to a line, and what publishing needs. One hold keeps the one-command
 * wording (`holds \`git push\` for stream a`); several are listed in textual order, each held
 * command with its stream or its failure (`holds this line: \`git push\` for stream a;
 * \`git push\` for stream b`).
 */
function heldText(verb: 'holds' | 'refused', holds: Holds): string {
  const [first, ...rest] = holds
  if (rest.length === 0) return `shipgate-hud ${verb} ${heldCommand(first)}. Publishing needs ${MISSING}.`
  return `shipgate-hud ${verb} this line: ${holds.map(heldCommand).join('; ')}. Publishing needs ${MISSING}, on each stream.`
}

/**
 * What the dialog shows the person: the plugin, each held command with its stream (or why the
 * journal could not be read), what is missing. One "Let it through once" covers the whole
 * line, so every held command is named.
 */
export function holdReason(holds: Holds): string {
  return heldText('holds', holds)
}

/** What the model may do about a held stream: the one record it may write itself. */
const REVIEW_STEP = 'finish the review and record its verdict with `journal.py append --type review-verdict` (`verdict: ready`)'

/** What the model may do about a journal it could not read: never a verdict for a stream nobody read (D14). */
const READ_STEP = 'find out why the journal could not be read and fix that'

/** The streams held for want of a review, each once, in textual order. */
const unreviewedStreams = (holds: Holds): readonly StreamName[] => [...new Set(holds.flatMap(hold => (hold.kind === 'Unreviewed' ? [hold.stream] : [])))]

/** What the model may do about one held command. */
function stepOf(hold: Hold): string {
  switch (hold.kind) {
    case 'Unreviewed':
      return REVIEW_STEP
    case 'Unreadable':
      return READ_STEP
    default:
      return absurd(hold)
  }
}

/** What the model may do about a line of holds: the review of each held stream, named; the read, once, when one failed. */
function lineSteps(holds: Holds): readonly string[] {
  const [stream, ...others] = unreviewedStreams(holds).map(name => `stream ${name}`)
  const review = stream === undefined ? [] : [`for ${others.length === 0 ? '' : 'each of '}${andList([stream, ...others])}, ${REVIEW_STEP}`]
  return holds.some(hold => hold.kind === 'Unreadable') ? [...review, READ_STEP] : review
}

/** What the model may do, as one clause: one hold's step as before, or the line's steps. */
function stepsOf(holds: Holds): string {
  const [first, ...rest] = holds
  const steps = (rest.length === 0 ? [stepOf(first)] : lineSteps(holds)).join('; ')
  return `${steps.charAt(0).toUpperCase()}${steps.slice(1)}`
}

/**
 * What the model reads on a deny: each held command with what its stream lacks (or why the
 * journal could not be read), and the one record it may write itself. The user's decision is
 * taken at the gate's dialog, never recorded on their behalf. An unreadable journal sends the
 * model to the read, never to a verdict for a stream nobody read (D14).
 */
export function denyReason(holds: Holds): string {
  return `${heldText('refused', holds)} ${stepsOf(holds)}, ${USER_DECIDES}`
}

/** The deny reason when the hook itself failed: a publish command is refused, never let through. */
export const FAIL_CLOSED =
  'shipgate-hud refused this publish command: its publish gate failed before it could check the journal. ' +
  'Run the command again; if it keeps failing, ask the user.'
