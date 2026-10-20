import { describe, expect, test } from 'claude-code/testing'

import {
  denyReason,
  gateVerdict,
  holdReason,
  publishCommandOf,
  scanCommand,
  type CommandDir,
  type CommandScan,
  type BoundStream,
  type GateInputs,
  type GateVerdict,
  type Hold,
  type PassReason,
  type PublishCommand,
  type PublishHead,
  type PublishedRef,
  type TargetBinding,
} from '../hooks/publish'
import { branchName, eventSeq, failureText, isoTime, streamName } from '../hooks/journal'
import type { PublishAuthorization, ReadFailure, RunFailure, StreamName } from '../types'
import { bool, forAll, listOf, pick, type Gen } from './arbitrary'

/** A fixture value from a smart constructor: a null is a broken fixture, not a case. */
const must = <A>(value: A | null): A => {
  if (value === null) throw new Error('publish.test: a fixture failed its smart constructor')
  return value
}

const dirText = (dir: CommandDir): string => (dir.kind === 'Path' ? `Path ${dir.path}` : dir.kind)
const refText = (ref: PublishedRef): string => (ref.kind === 'Branch' ? `Branch ${ref.name}` : ref.kind)

/** One publish command as a table row names it: `git push · Path a/b · Branch x`. */
const commandText = (command: PublishCommand): string => `${command.head} · ${dirText(command.dir)} · ${refText(command.ref)}`

/** A scan as one line a table row can name: its first publish command, `clear`, `opaque`. */
const summary = (scan: CommandScan): string => (scan.kind === 'publishes' ? commandText(scan.commands[0]) : scan.kind)

/** The head of the first publish command a scan lists, or null. */
const headOfScan = (scan: CommandScan): PublishHead | null => (scan.kind === 'publishes' ? scan.commands[0].head : null)

describe('scanCommand: what a line publishes', () => {
  // Every line here publishes `git push` (the head only; the dir and ref tables are below).
  const pushes = [
    'git push',
    'git push --dry-run',
    'git push -f',
    'git push --force',
    'git push --force-with-lease origin x',
    'git push -u origin feature/x',
    'git -C sub push',
    'git --git-dir=.git push',
    'git --exec-path push',
    'git --config-env core.x=V push',
    '/usr/bin/git push',
    '\\git push',
    'git subtree push --prefix lib origin x',
    'env -C sub git push',
    "env -S 'A=1' git push",
    'exec -a name git push',
    'eval git push',
    'doas -u me git push',
    'chronic git push',
    '>out git push',
    '2>/dev/null git push',
    '<in git push',
    'git -C $(git rev-parse --show-toplevel) push',
    'git -C $(pwd) push',
    'git --work-tree `pwd` push',
    'git -c user.name=$(whoami) push',
    '(cd x && git push)',
    'git push>/dev/null',
    'git push>&2',
    'git push<in',
    'git push 2>&1 | tee log',
    '> out git push',
    '2> /dev/null git push',
    'function f { git push; }',
    'coproc git push',
    'git push # comment',
    'timeout --signal KILL 60 git push',
    'sudo --user me git push',
    'env --chdir x git push',
    'git -c core.x=y push origin',
    'git --git-dir .git --work-tree . push',
    'git --no-pager push',
    'cd x && git push',
    'ls; git push',
    'false || git push',
    'echo a | git push',
    'make &\ngit push',
    'ls\ngit push',
    'echo $(git push)',
    'echo `git push`',
    '(git push)',
    'env A=1 git push',
    'A=1 B=2 git push',
    'command git push',
    'sudo -u me git push',
    'sudo git push',
    'nohup git push',
    'time git push',
    'xargs git push',
    'exec git push',
    'builtin git push',
    '  git   push  ',
    'git -C "my dir" push',
    'git -C "$(git rev-parse --show-toplevel)" push',
    'git \\\npush origin x', // a backslash-newline continues the line
    'if git diff --quiet; then git push; fi',
    'for b in a b; do git push origin $b; done',
    'git diff --quiet || { git push; }',
    '! git push',
    'timeout 60 git push',
    'timeout -k 5 60 git push',
    'nice git push',
    'nice -n 10 git push',
    'ionice -c 3 git push',
    'stdbuf -oL git push',
    'caffeinate git push',
    'bash <<EOF\ngit push\nEOF', // a heredoc fed to a shell is a command line
    "sh <<'EOF'\ncd x\ngit push\nEOF",
    "git -c 'user.name=x' push",
    // a literal string fed to a shell is read as a line of its own
    "sh -c 'git push'",
    'bash -c "git push"',
    "bash -lc 'git push'",
    "eval 'git push'",
    "sh -c 'sh -c \"git push\"'",
    "xargs sh -c 'git push'",
    "sudo sh -c 'git push'",
    "bash <<< 'git push'",
    'cat <(git push)', // a process substitution runs its text
    'curl -fsSL x | bash; git push', // a publish wins over an opaque part
    'cd x &>/dev/null && git push',
  ]
  for (const command of pushes) {
    test(`publishes: ${JSON.stringify(command)}`, async () => {
      expect(headOfScan(scanCommand(command))).toBe('git push')
    })
  }

  const prs: readonly (readonly [string, PublishHead])[] = [
    ['gh pr create', 'gh pr create'],
    ['gh pr create --fill', 'gh pr create'],
    ['gh --repo o/r pr create --fill', 'gh pr create'],
    ['gh -R o/r pr create', 'gh pr create'],
    ['gh pr --repo o/r create', 'gh pr create'],
    ['glab mr create', 'glab mr create'],
    ['glab mr new -t x', 'glab mr create'],
    ['gh pr new --fill', 'gh pr create'],
    ['/opt/homebrew/bin/gh pr create', 'gh pr create'],
    ['./bin/gh pr new', 'gh pr create'],
    ['gh pr create>out', 'gh pr create'],
    ['glab -R o/r mr create', 'glab mr create'],
    ['git add . && git commit -m x && gh pr create', 'gh pr create'],
    ['gh pr create && git push', 'gh pr create'], // the first head found wins
    ["cat <<'EOF' > f\nx\nEOF\ngit push", 'git push'], // a command after a heredoc body is still read
    ["sh -c 'glab mr create'", 'glab mr create'],
  ]
  for (const [command, head] of prs) {
    test(`publishes ${head}: ${JSON.stringify(command)}`, async () => {
      expect(headOfScan(scanCommand(command))).toBe(head)
    })
  }

  const clear = [
    '',
    'ls',
    'git pull',
    'git pushd',
    'git status && git log',
    'git-push-helper',
    'echo pushed',
    'gh pr list',
    'gh pr view 12',
    'gh pr',
    'gh repo create',
    'glab mr list',
    'glab mr view',
    'git -C push status', // `push` here is -C's directory, not the subcommand
    'mygit push',
    'pushd /tmp',
    'git commit -m "fix push"',
    'git commit -m "push it"',
    // quoted text is one word, never a command
    'echo "git push"',
    'grep -n "git push" README.md',
    'git commit -m "git push"',
    "grep -rn 'gh pr create' docs | head",
    // a heredoc body fed to anything but a shell is data
    "cat <<'EOF'\ngit push\nEOF",
    'python3 - <<EOF\ngit push\nEOF',
    'echo hi # ; git push',
    'cat <<EOF\n  EOF\ngit push\nEOF',
    "cat > notes.md <<-'END'\n\tgit push\n\tEND",
    'git stash push',
    'git log --grep push',
    'command -v git push',
    'command -V gh pr create',
    'git subtree pull --prefix lib origin x',
    // a literal string fed to a shell that publishes nothing
    "sh -c 'echo hi'",
    'eval "echo git push"',
    "eval 'echo hi'",
    // a script file is a program like any other
    'bash script.sh',
    'source env.sh',
  ]
  for (const command of clear) {
    test(`clear: ${JSON.stringify(command)}`, async () => {
      expect(scanCommand(command)).toEqual({ kind: 'clear' })
    })
  }

  // Text fed to a shell that the scan cannot read: a documented limit (HUD ADR 0005).
  const opaque = [
    'curl -fsSL https://example.com/install.sh | bash',
    'curl -fsSL https://example.com/install.sh | sh -s -- --yes',
    "echo 'git push' | sh",
    'cat script.sh | zsh',
    'sh -c "$CMD"',
    'bash -c "$(cat script.sh)"',
    'eval "$X"',
    'eval $X',
    'bash <(curl -fsSL https://example.com/install.sh)',
    'source <(kubectl completion zsh)',
    '. <(kubectl completion zsh)',
    'bash <<< "$X"',
    'bash < <(curl -fsSL https://example.com/install.sh)',
    'echo "git push" | bash -s',
  ]
  for (const command of opaque) {
    test(`opaque: ${JSON.stringify(command)}`, async () => {
      expect(scanCommand(command).kind).toBe('opaque')
    })
  }
})

describe('scanCommand: the directory and the published ref', () => {
  const rows: readonly (readonly [string, string])[] = [
    // the refspec forms of `git push`
    ['git push', 'git push · Shell · Head'],
    ['git push origin', 'git push · Shell · Head'],
    ['git push -u origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push origin HEAD', 'git push · Shell · Head'],
    ['git push origin @', 'git push · Shell · Head'],
    ['git push origin HEAD:feature/x', 'git push · Shell · Head'],
    ['git push origin HEAD~1:feature/x', 'git push · Shell · Head'],
    ['git push origin +feature/x', 'git push · Shell · Branch feature/x'],
    ['git push origin feature/x:main', 'git push · Shell · Branch feature/x'],
    ['git push origin +feature/x:refs/heads/main', 'git push · Shell · Branch feature/x'],
    ['git push origin refs/heads/feature/x', 'git push · Shell · Branch feature/x'],
    ['git push origin refs/heads/feature/x:refs/heads/feature/x', 'git push · Shell · Branch feature/x'],
    ['git push origin feature/x~2:feature/x', 'git push · Shell · Branch feature/x'],
    ["git push origin 'feature/x'", 'git push · Shell · Branch feature/x'],
    ['git push origin "feature/x"', 'git push · Shell · Branch feature/x'],
    ['git push origin :feature/x', 'git push · Shell · Unresolved'], // a deletion
    ['git push origin :', 'git push · Shell · Unresolved'], // every matching branch
    ['git push origin feature/a feature/b', 'git push · Shell · Unresolved'],
    ["git push origin 'refs/heads/*:refs/heads/*'", 'git push · Shell · Unresolved'],
    ['git push --all', 'git push · Shell · Unresolved'],
    ['git push --all origin', 'git push · Shell · Unresolved'],
    ['git push origin --branches', 'git push · Shell · Unresolved'],
    ['git push --mirror origin', 'git push · Shell · Unresolved'],
    ['git push --tags', 'git push · Shell · Unresolved'],
    ['git push origin --tags', 'git push · Shell · Unresolved'],
    ['git push --delete origin feature/x', 'git push · Shell · Unresolved'],
    ['git push -d origin feature/x', 'git push · Shell · Unresolved'],
    ['git push origin -d feature/x', 'git push · Shell · Unresolved'],
    ['git push -fd origin feature/x', 'git push · Shell · Unresolved'],
    ['git push --prune origin', 'git push · Shell · Unresolved'],
    ['git push origin "$BRANCH"', 'git push · Shell · Unresolved'],
    ['git push origin $b', 'git push · Shell · Unresolved'],
    ['git push $REMOTE', 'git push · Shell · Unresolved'],
    ['git push --repo origin upstream feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --repo=origin upstream feature/x', 'git push · Shell · Branch feature/x'],
    ['git push -o ci.skip origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --push-option ci.skip origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --push-option=ci.skip origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --receive-pack git-receive-pack origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --exec git-receive-pack origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --force-with-lease=feature/x:abc123 origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push --recurse-submodules=check origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git push -- origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git subtree push --prefix lib origin x', 'git push · Shell · Head'], // the split is made from HEAD
    // `git -C`, repeatable and composing
    ['git -C sub push', 'git push · Path sub · Head'],
    ['git -C a -C b push', 'git push · Path a/b · Head'],
    ['git -C a -C /srv/repo push', 'git push · Path /srv/repo · Head'],
    ['git -C /srv/repo -C b push', 'git push · Path /srv/repo/b · Head'],
    ['git -C a/ -C b push', 'git push · Path a/b · Head'],
    ['git -C "" push', 'git push · Shell · Head'], // an empty -C leaves the directory as it is
    ['git -C "my dir" push', 'git push · Path my dir · Head'],
    ["git -C '~/repo' push", 'git push · Path ~/repo · Head'], // quoted: a directory named ~
    ['git -C sub push origin feature/x', 'git push · Path sub · Branch feature/x'],
    ['git -C $(git rev-parse --show-toplevel) push', 'git push · Unreadable · Head'],
    ['git -C "$D" push', 'git push · Unreadable · Head'],
    ['git -C ~/repo push', 'git push · Unreadable · Head'],
    ['git --git-dir=.git push', 'git push · Unreadable · Head'],
    ['git --work-tree . push', 'git push · Unreadable · Head'],
    ['GIT_DIR=other/.git git push', 'git push · Unreadable · Head'],
    ['env -C sub git push', 'git push · Unreadable · Head'],
    // a leading `cd`
    ['cd x && git push', 'git push · Path x · Head'],
    ['cd x; git push', 'git push · Path x · Head'],
    ['cd x\ngit push', 'git push · Path x · Head'],
    ['cd a && cd b && git push', 'git push · Path a/b · Head'],
    ['cd a; cd b; git push origin feature/x', 'git push · Path a/b · Branch feature/x'],
    ['cd a && cd /srv/repo && git push', 'git push · Path /srv/repo · Head'],
    ['cd /srv/repo && cd b && git push', 'git push · Path /srv/repo/b · Head'],
    ['cd a/ && cd b && git push', 'git push · Path a/b · Head'],
    ['cd a && git -C b push', 'git push · Path a/b · Head'],
    ['cd a && git -C /srv/repo push', 'git push · Path /srv/repo · Head'],
    ['cd -P x && git push', 'git push · Path x · Head'],
    ['cd -- x && git push', 'git push · Path x · Head'],
    ['pushd x && git push', 'git push · Path x · Head'],
    ['cd x 2>/dev/null && git push', 'git push · Path x · Head'],
    ['cd x &>/dev/null && git push', 'git push · Path x · Head'],
    ['cd x || exit 1; git push', 'git push · Path x · Head'],
    ['(cd x && git push)', 'git push · Path x · Head'],
    ['cd a && (cd b && git push)', 'git push · Path a/b · Head'],
    ['(cd x); git push', 'git push · Shell · Head'], // a subshell's cd ends with it
    ['echo $(cd x && pwd) && git push', 'git push · Shell · Head'], // so does a substitution's
    ['{ cd x; } && git push', 'git push · Path x · Head'], // a brace group runs in the shell
    ['sudo -D /srv/repo git push', 'git push · Unreadable · Head'],
    ['cd x & git push', 'git push · Shell · Head'], // a background cd runs in a subshell
    ['cd x | git push', 'git push · Shell · Head'],
    ['cd x && echo $(git push)', 'git push · Path x · Head'],
    ["cd x && sh -c 'git push'", 'git push · Path x · Head'],
    ["sh -c 'cd x && git push'", 'git push · Path x · Head'],
    ['cd x && bash <<EOF\ngit push\nEOF', 'git push · Path x · Head'],
    ['cd x && gh pr create', 'gh pr create · Path x · Head'],
    // a directory the scan cannot read
    ['cd && git push', 'git push · Unreadable · Head'],
    ['cd - && git push', 'git push · Unreadable · Head'],
    ['cd ~/x && git push', 'git push · Unreadable · Head'],
    ['cd $X && git push', 'git push · Unreadable · Head'],
    ['cd "$X" && git push', 'git push · Unreadable · Head'],
    ['cd a b && git push', 'git push · Unreadable · Head'],
    ['popd && git push', 'git push · Unreadable · Head'],
    ['cd $X && git push origin feature/x', 'git push · Unreadable · Branch feature/x'],
    ['cd $X && cd /srv/repo && git push', 'git push · Path /srv/repo · Head'], // an absolute cd resets
    ['cd $X && git -C /srv/repo push', 'git push · Path /srv/repo · Head'],
    // a `cd` that may not have run
    ['test -d x && cd x; git push', 'git push · Unreadable · Head'],
    ['false || cd x && git push', 'git push · Unreadable · Head'],
    ['cd x || git push', 'git push · Unreadable · Head'],
    ['if true; then cd x; fi; git push', 'git push · Unreadable · Head'],
    ['f() { cd x; }; git push', 'git push · Unreadable · Head'],
    ['ls | cd x; git push', 'git push · Unreadable · Head'],
    // `gh pr create --head` and `glab mr create --source-branch`
    ['gh pr create', 'gh pr create · Shell · Head'],
    ['gh pr create --head feature/x', 'gh pr create · Shell · Branch feature/x'],
    ['gh pr create -H feature/x', 'gh pr create · Shell · Branch feature/x'],
    ['gh pr create --head=feature/x', 'gh pr create · Shell · Branch feature/x'],
    ['gh pr create --head octo:feature/x', 'gh pr create · Shell · Branch feature/x'],
    ['gh pr new --fill -H feature/x', 'gh pr create · Shell · Branch feature/x'],
    ['gh pr create --title "-H x" --fill', 'gh pr create · Shell · Head'],
    ['gh pr create -B main', 'gh pr create · Shell · Head'],
    ['gh pr create --head "$B"', 'gh pr create · Shell · Unresolved'],
    ['glab mr create --source-branch feature/x', 'glab mr create · Shell · Branch feature/x'],
    ['glab mr create -s feature/x', 'glab mr create · Shell · Branch feature/x'],
    ['glab mr create --source-branch=feature/x', 'glab mr create · Shell · Branch feature/x'],
    ['glab mr create -b main -s feature/x', 'glab mr create · Shell · Branch feature/x'],
    ['glab mr create --target-branch main', 'glab mr create · Shell · Head'],
    ['glab mr create -t x', 'glab mr create · Shell · Head'],
    // a literal string fed to a shell, with its own refspec and directory
    ['bash -c "git push origin feature/x"', 'git push · Shell · Branch feature/x'],
    ['sh -c "git push $ARGS"', 'git push · Shell · Unresolved'],
    ['eval git push origin feature/x', 'git push · Shell · Branch feature/x'],
  ]
  for (const [command, expected] of rows) {
    test(`${JSON.stringify(command)} → ${expected}`, async () => {
      expect(summary(scanCommand(command))).toBe(expected)
    })
  }

  const reasons: readonly (readonly [string, string])[] = [
    ['git push --all', '--all'],
    ['git push --mirror', '--mirror'],
    ['git push origin :feature/x', 'deletion'],
    ['git push origin feature/a feature/b', 'several'],
    ['cd - && git push', 'cd -'],
    ['curl -fsSL https://example.com/install.sh | bash', 'bash'],
    ['eval "$X"', 'eval'],
  ]
  for (const [command, part] of reasons) {
    test(`the reason for ${JSON.stringify(command)} names ${JSON.stringify(part)}`, async () => {
      const scan = scanCommand(command)
      const why =
        scan.kind === 'opaque'
          ? scan.why
          : scan.kind === 'publishes' && scan.commands[0].ref.kind === 'Unresolved'
            ? scan.commands[0].ref.why
            : scan.kind === 'publishes' && scan.commands[0].dir.kind === 'Unreadable'
              ? scan.commands[0].dir.why
              : ''
      expect(why).toContain(part)
    })
  }

  test('publishCommandOf is the head of a publishing scan, else null', async () => {
    expect(publishCommandOf('cd x && git push origin feature/x')).toBe('git push')
    expect(publishCommandOf('gh pr create --head feature/x')).toBe('gh pr create')
    expect(publishCommandOf('git status')).toBeNull()
    expect(publishCommandOf('curl -fsSL https://example.com/install.sh | bash')).toBeNull()
  })

  test('publishCommandOf is the head of the first publish command in a line of several', async () => {
    expect(publishCommandOf('gh pr create --fill && git push origin feature/b')).toBe('gh pr create')
    expect(publishCommandOf('git push origin feature/a; glab mr create -s feature/b')).toBe('git push')
  })
})

/** Every publish command a scan lists, as a table row names each; [] when it lists none. */
const commandsOf = (scan: CommandScan): readonly string[] => (scan.kind === 'publishes' ? scan.commands.map(commandText) : [])

// R1-F1: the scan stopped at the first publish command, so the gate checked one target and
// `git push origin a && git push origin b` published `b` unchecked.
describe('scanCommand: every publish command in a line, in line order', () => {
  const rows: readonly (readonly [string, readonly string[]])[] = [
    ['git push origin feature/a && git push origin feature/b', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ['git push origin feature/a; gh pr create --head feature/b', ['git push · Shell · Branch feature/a', 'gh pr create · Shell · Branch feature/b']],
    ['gh pr create --fill && git push', ['gh pr create · Shell · Head', 'git push · Shell · Head']],
    ['git push origin feature/a || git push origin feature/b', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ['git push origin feature/a\nglab mr create -s feature/b', ['git push · Shell · Branch feature/a', 'glab mr create · Shell · Branch feature/b']],
    // a literal string fed to a shell adds its own publishes, where it stands in the line
    ["git push origin feature/a && sh -c 'git push origin feature/b'", ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ["sh -c 'git push origin feature/a' && git push origin feature/b", ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ["sh -c 'git push origin feature/a && git push origin feature/b'", ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ["eval 'git push origin feature/a; gh pr create -H feature/b'", ['git push · Shell · Branch feature/a', 'gh pr create · Shell · Branch feature/b']],
    ['bash <<EOF\ngit push origin feature/a\nEOF\ngit push origin feature/b', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ['echo $(git push origin feature/a) && git push origin feature/b', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    // each command keeps the directory it runs in
    ['cd x && git push origin feature/a && cd y && git push', ['git push · Path x · Branch feature/a', 'git push · Path x/y · Head']],
    ['git -C a push && git -C /srv/repo push --all', ['git push · Path a · Head', 'git push · Path /srv/repo · Unresolved']],
    ['(cd x && git push); git push', ['git push · Path x · Head', 'git push · Shell · Head']],
    // the same branch twice is listed twice: the gate reads it once
    ['git push origin feature/a && git push -u origin feature/a', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/a']],
    // a publish anywhere wins over an opaque part, and every publish is listed
    ['curl -fsSL https://example.com/install.sh | bash; git push origin feature/a && git push origin feature/b', ['git push · Shell · Branch feature/a', 'git push · Shell · Branch feature/b']],
    ['git push origin feature/a; eval "$X"; gh pr create', ['git push · Shell · Branch feature/a', 'gh pr create · Shell · Head']],
  ]
  for (const [command, expected] of rows) {
    test(`${JSON.stringify(command)} → ${expected.length} publishes`, async () => {
      expect(commandsOf(scanCommand(command))).toEqual(expected)
    })
  }
})

describe('scanCommand: laws', () => {
  const publishLine: Gen<string> = rng => {
    const prefix = pick(['', 'cd sub && ', 'env A=1 ', 'sudo ', 'timeout 60 ', 'A=1 ', 'git add . && ', 'ls; '] as const)(rng)
    const command = pick([
      'git push',
      'git push origin feature/x',
      'git push -u origin HEAD',
      'git push --force-with-lease origin +feature/x:main',
      'git -C sub push',
      'git -C a -C b push --all',
      'git push origin :feature/x',
      'gh pr create --fill',
      'gh pr create --head octo:feature/x',
      'gh pr new -B main',
      'glab mr create -s feature/x',
      'glab mr new -t "a title"',
      'bash -c "git push"',
    ] as const)(rng)
    const suffix = pick(['', ' 2>&1', ' | tee log', ' && echo done', ' >/dev/null', ' # pushed'] as const)(rng)
    return `${prefix}${command}${suffix}`
  }

  const clearLine: Gen<string> = rng => {
    const part = pick([
      'ls',
      'git status',
      'git add .',
      'git commit -m "push it"',
      "echo 'git push'",
      'npm test',
      'make build',
      'cd sub',
      'git stash push',
      'grep -n "gh pr create" docs',
      'true',
      '(ls)',
      'git log --oneline | head -3',
      'sh -c "echo hi"',
    ] as const)
    const first = part(rng)
    return bool(rng) ? first : `${first}; ${part(rng)}`
  }

  const holder = pick(['echo', "printf '%s\\n'", 'grep -F', 'git commit -m', 'git log --grep'] as const)

  test('a publish line in single quotes, as an argument to a non-shell command, never publishes', async () => {
    forAll(
      20261020,
      500,
      rng => ({ line: publishLine(rng), command: holder(rng) }),
      ({ line, command }) => scanCommand(line).kind === 'publishes' && scanCommand(`${command} '${line}'`).kind !== 'publishes',
    )
  })

  test('a clear line joined with && before a publish line publishes that line’s head', async () => {
    forAll(
      20261021,
      500,
      rng => ({ clear: clearLine(rng), line: publishLine(rng) }),
      ({ clear, line }) => {
        const head = headOfScan(scanCommand(line))
        return scanCommand(clear).kind === 'clear' && head !== null && headOfScan(scanCommand(`${clear} && ${line}`)) === head
      },
    )
  })

  /** A segment of a line, and the row the scan lists it as: null for a clear one. No `cd`, so every dir is fixed. */
  type Segment = readonly [string, string | null]
  const SEGMENTS: readonly [Segment, ...Segment[]] = [
    ['ls', null],
    ['git status', null],
    ['git add .', null],
    ['git commit -m "push it"', null],
    ["echo 'git push'", null],
    ['git stash push', null],
    ['grep -n "gh pr create" docs', null],
    ['(ls)', null],
    ['git log --oneline | head -3', null],
    ['sh -c "echo hi"', null],
    ['git push', 'git push · Shell · Head'],
    ['git push origin feature/x', 'git push · Shell · Branch feature/x'],
    ['git -C sub push -u origin HEAD', 'git push · Path sub · Head'],
    ['git push --all', 'git push · Shell · Unresolved'],
    ['env A=1 git push origin +feature/y:main', 'git push · Shell · Branch feature/y'],
    ['gh pr create --head octo:feature/z', 'gh pr create · Shell · Branch feature/z'],
    ['glab mr create -s feature/w', 'glab mr create · Shell · Branch feature/w'],
    ["bash -c 'git push origin feature/v'", 'git push · Shell · Branch feature/v'],
    ['git push origin feature/u 2>&1 | tee log', 'git push · Shell · Branch feature/u'],
  ]
  const segment: Gen<Segment> = pick(SEGMENTS)
  const joiner = pick([' && ', '; ', '\n'] as const)

  test('a line of clear and publishing segments lists exactly the publishing ones, in order', async () => {
    forAll(
      20261022,
      500,
      rng => {
        const segments = listOf(segment, 1, 6)(rng)
        return { line: segments.map(([text], index) => (index === 0 ? text : `${joiner(rng)}${text}`)).join(''), expected: segments.flatMap(([, row]) => (row === null ? [] : [row])) }
      },
      ({ line, expected }) => {
        const scan = scanCommand(line)
        expect(commandsOf(scan)).toEqual(expected)
        return expected.length > 0 || scan.kind === 'clear'
      },
    )
  })
})

describe('gateVerdict', () => {
  const TARGET = must(streamName('feature/target'))
  const BOUND = must(streamName('feature/bound'))
  const BRANCH = must(branchName('feature/target'))
  const AUTHORIZED: PublishAuthorization = {
    kind: 'authorized',
    by: 'review-verdict',
    seq: must(eventSeq(12)),
    at: must(isoTime('2026-10-20T10:00:00Z')),
  }
  const HELD: PublishAuthorization = { kind: 'held' }
  const TARGET_FAILED: RunFailure = { kind: 'Exited', exitCode: 1, stderr: 'database is locked' }
  const BOUND_FAILED: RunFailure = { kind: 'CannotStart', message: 'python3 not found' }

  const pass = (why: PassReason): GateVerdict => ({ kind: 'Pass', why })
  const unreviewed = (head: PublishHead, stream: StreamName): GateVerdict => ({ kind: 'Hold', holds: [{ kind: 'Unreviewed', head, stream }] })
  const unreadable = (head: PublishHead, failure: ReadFailure): GateVerdict => ({ kind: 'Hold', holds: [{ kind: 'Unreadable', head, failure }] })

  const nothingToCheck: readonly (readonly [GateInputs, PassReason])[] = [
    [{ kind: 'NotPublish' }, 'NotPublish'],
    [{ kind: 'NoSurface' }, 'NoSurface'],
    [{ kind: 'NoProject' }, 'NoProject'],
    [{ kind: 'NoJournalScript' }, 'NoJournalScript'],
    [{ kind: 'Outdated' }, 'Outdated'],
  ]
  for (const [inputs, why] of nothingToCheck) {
    test(`${inputs.kind} passes with ${why}`, async () => {
      expect(gateVerdict(inputs)).toEqual(pass(why))
    })
  }

  type TargetCase = 'target authorized' | 'target held' | 'target has no stream' | 'target unresolved' | 'target unreadable'
  type BoundCase = 'bound authorized' | 'bound held' | 'unbound' | 'bound unreadable'

  const targets: Readonly<Record<TargetCase, TargetBinding>> = {
    'target authorized': { kind: 'Stream', branch: BRANCH, stream: TARGET, publish: AUTHORIZED },
    'target held': { kind: 'Stream', branch: BRANCH, stream: TARGET, publish: HELD },
    'target has no stream': { kind: 'NoStream', branch: BRANCH },
    'target unresolved': { kind: 'Unresolved', why: '`--all` pushes every branch' },
    'target unreadable': { kind: 'Unknown', failure: TARGET_FAILED },
  }
  const bounds: Readonly<Record<BoundCase, BoundStream>> = {
    'bound authorized': { kind: 'Stream', stream: BOUND, publish: AUTHORIZED },
    'bound held': { kind: 'Stream', stream: BOUND, publish: HELD },
    unbound: { kind: 'None' },
    'bound unreadable': { kind: 'Unknown', failure: BOUND_FAILED },
  }

  /** The spec, one row per target × bound: what the gate decides for a command with `head`. */
  const verdicts = (head: PublishHead): readonly (readonly [TargetCase, BoundCase, GateVerdict])[] => [
    ['target authorized', 'bound authorized', pass('Authorized')],
    ['target authorized', 'bound held', pass('Authorized')],
    ['target authorized', 'unbound', pass('Authorized')],
    ['target authorized', 'bound unreadable', pass('Authorized')],
    ['target held', 'bound authorized', unreviewed(head, TARGET)],
    ['target held', 'bound held', unreviewed(head, TARGET)],
    ['target held', 'unbound', unreviewed(head, TARGET)],
    ['target held', 'bound unreadable', unreviewed(head, TARGET)],
    ['target has no stream', 'bound authorized', pass('Authorized')],
    ['target has no stream', 'bound held', unreviewed(head, BOUND)],
    ['target has no stream', 'unbound', pass('NoStream')],
    ['target has no stream', 'bound unreadable', unreadable(head, BOUND_FAILED)],
    ['target unresolved', 'bound authorized', pass('Authorized')],
    ['target unresolved', 'bound held', unreviewed(head, BOUND)],
    ['target unresolved', 'unbound', pass('NoStream')],
    ['target unresolved', 'bound unreadable', unreadable(head, BOUND_FAILED)],
    ['target unreadable', 'bound authorized', unreadable(head, TARGET_FAILED)],
    ['target unreadable', 'bound held', unreadable(head, TARGET_FAILED)],
    ['target unreadable', 'unbound', unreadable(head, TARGET_FAILED)],
    ['target unreadable', 'bound unreadable', unreadable(head, TARGET_FAILED)],
  ]

  const heads: readonly PublishHead[] = ['git push', 'gh pr create', 'glab mr create']
  for (const head of heads) {
    const command: PublishCommand = { head, dir: { kind: 'Shell' }, ref: { kind: 'Head' } }
    for (const [targetCase, boundCase, expected] of verdicts(head)) {
      const shown = expected.kind === 'Pass' ? `Pass ${expected.why}` : `Hold ${expected.holds.map(hold => hold.kind).join(', ')}`
      test(`${head}: ${targetCase}, ${boundCase} → ${shown}`, async () => {
        expect(gateVerdict({ kind: 'Target', targets: [{ command, target: targets[targetCase] }], bound: bounds[boundCase] })).toEqual(expected)
      })
    }
  }

  // R1-F1: a line of several publish commands. Each is judged as one command alone; the line
  // holds when any command holds, naming the first that holds, and passes only when all pass.
  const OTHER = must(streamName('feature/other'))
  const OTHER_BRANCH = must(branchName('feature/other'))
  const push: PublishCommand = { head: 'git push', dir: { kind: 'Shell' }, ref: { kind: 'Branch', name: 'feature/target' } }
  const pr: PublishCommand = { head: 'gh pr create', dir: { kind: 'Shell' }, ref: { kind: 'Branch', name: 'feature/other' } }
  const other = (publish: PublishAuthorization): TargetBinding => ({ kind: 'Stream', branch: OTHER_BRANCH, stream: OTHER, publish })
  const OTHER_FAILED: RunFailure = { kind: 'Exited', exitCode: 1, stderr: 'disk I/O error' }
  /** A line held on several commands: every hold, in line order (R2-N1). */
  const held = (first: Hold, ...rest: readonly Hold[]): GateVerdict => ({ kind: 'Hold', holds: [first, ...rest] })

  const lines: readonly (readonly [string, GateInputs, GateVerdict])[] = [
    [
      'first authorized, second unreviewed → hold naming the second',
      { kind: 'Target', targets: [{ command: push, target: targets['target authorized'] }, { command: pr, target: other(HELD) }], bound: bounds.unbound },
      unreviewed('gh pr create', OTHER),
    ],
    [
      'first unreviewed, second authorized → hold naming the first',
      { kind: 'Target', targets: [{ command: push, target: targets['target held'] }, { command: pr, target: other(AUTHORIZED) }], bound: bounds['bound authorized'] },
      unreviewed('git push', TARGET),
    ],
    [
      'both unreviewed → hold naming both, in line order',
      { kind: 'Target', targets: [{ command: push, target: targets['target held'] }, { command: pr, target: other(HELD) }], bound: bounds.unbound },
      held({ kind: 'Unreviewed', head: 'git push', stream: TARGET }, { kind: 'Unreviewed', head: 'gh pr create', stream: OTHER }),
    ],
    [
      'both unreviewed, in the other order → hold naming both, in line order',
      { kind: 'Target', targets: [{ command: pr, target: other(HELD) }, { command: push, target: targets['target held'] }], bound: bounds.unbound },
      held({ kind: 'Unreviewed', head: 'gh pr create', stream: OTHER }, { kind: 'Unreviewed', head: 'git push', stream: TARGET }),
    ],
    [
      'first unreviewed, second unreadable → hold naming both',
      { kind: 'Target', targets: [{ command: push, target: targets['target held'] }, { command: pr, target: { kind: 'Unknown', failure: OTHER_FAILED } }], bound: bounds.unbound },
      held({ kind: 'Unreviewed', head: 'git push', stream: TARGET }, { kind: 'Unreadable', head: 'gh pr create', failure: OTHER_FAILED }),
    ],
    [
      'both fall back to a held bound stream → hold naming each command on the bound stream',
      { kind: 'Target', targets: [{ command: push, target: targets['target has no stream'] }, { command: pr, target: targets['target unresolved'] }], bound: bounds['bound held'] },
      held({ kind: 'Unreviewed', head: 'git push', stream: BOUND }, { kind: 'Unreviewed', head: 'gh pr create', stream: BOUND }),
    ],
    [
      'three commands, the first and third held → hold naming those two, in line order',
      {
        kind: 'Target',
        targets: [
          { command: push, target: targets['target held'] },
          { command: pr, target: other(AUTHORIZED) },
          { command: { ...push, head: 'glab mr create' }, target: other(HELD) },
        ],
        bound: bounds.unbound,
      },
      held({ kind: 'Unreviewed', head: 'git push', stream: TARGET }, { kind: 'Unreviewed', head: 'glab mr create', stream: OTHER }),
    ],
    [
      'both authorized → pass',
      { kind: 'Target', targets: [{ command: push, target: targets['target authorized'] }, { command: pr, target: other(AUTHORIZED) }], bound: bounds['bound held'] },
      pass('Authorized'),
    ],
    [
      'first authorized, second unreadable → Unreadable hold naming the second',
      { kind: 'Target', targets: [{ command: push, target: targets['target authorized'] }, { command: pr, target: { kind: 'Unknown', failure: OTHER_FAILED } }], bound: bounds.unbound },
      unreadable('gh pr create', OTHER_FAILED),
    ],
    [
      'first unreadable, second unreviewed → hold naming both, the failure first',
      { kind: 'Target', targets: [{ command: push, target: targets['target unreadable'] }, { command: pr, target: other(HELD) }], bound: bounds.unbound },
      held({ kind: 'Unreadable', head: 'git push', failure: TARGET_FAILED }, { kind: 'Unreviewed', head: 'gh pr create', stream: OTHER }),
    ],
    [
      'first has no stream and falls back to a held bound stream, second authorized → hold naming the bound stream',
      { kind: 'Target', targets: [{ command: push, target: targets['target has no stream'] }, { command: pr, target: other(AUTHORIZED) }], bound: bounds['bound held'] },
      unreviewed('git push', BOUND),
    ],
    [
      'first authorized, second unresolved and falls back to an unreadable bound stream → Unreadable hold naming the second',
      { kind: 'Target', targets: [{ command: push, target: targets['target authorized'] }, { command: pr, target: targets['target unresolved'] }], bound: bounds['bound unreadable'] },
      unreadable('gh pr create', BOUND_FAILED),
    ],
    [
      'first has no stream and no bound stream, second authorized → pass, authorized',
      { kind: 'Target', targets: [{ command: push, target: targets['target has no stream'] }, { command: pr, target: other(AUTHORIZED) }], bound: bounds.unbound },
      pass('Authorized'),
    ],
    [
      'first unresolved, second has no stream, no bound stream → pass, no stream',
      { kind: 'Target', targets: [{ command: push, target: targets['target unresolved'] }, { command: pr, target: { kind: 'NoStream', branch: OTHER_BRANCH } }], bound: bounds.unbound },
      pass('NoStream'),
    ],
    [
      'both fall back to an authorized bound stream → pass',
      { kind: 'Target', targets: [{ command: push, target: targets['target has no stream'] }, { command: pr, target: targets['target unresolved'] }], bound: bounds['bound authorized'] },
      pass('Authorized'),
    ],
    [
      'three commands, the third unreviewed → hold naming the third',
      {
        kind: 'Target',
        targets: [
          { command: push, target: targets['target authorized'] },
          { command: pr, target: other(AUTHORIZED) },
          { command: { ...push, head: 'glab mr create' }, target: other(HELD) },
        ],
        bound: bounds.unbound,
      },
      unreviewed('glab mr create', OTHER),
    ],
  ]
  for (const [name, inputs, expected] of lines) {
    test(`a line of several publishes: ${name}`, async () => {
      expect(gateVerdict(inputs)).toEqual(expected)
    })
  }
})

describe('holdReason and denyReason', () => {
  const STREAM = must(streamName('feature/held-stream'))
  const UNREVIEWED: Hold = { kind: 'Unreviewed', head: 'git push', stream: STREAM }
  const FAILURE: RunFailure = { kind: 'Exited', exitCode: 1, stderr: 'Traceback …\nsqlite3.OperationalError: database is locked\n' }
  const UNREADABLE: Hold = { kind: 'Unreadable', head: 'gh pr create', failure: FAILURE }
  /** What `mr-opened` demands, as both texts name it. */
  const DEMANDS = ['`review-verdict` with `verdict: ready`', '`gate-decision` with `gate: publish`, `raised_by: user`']

  test('the hold names the plugin, the command, the stream and what mr-opened demands', async () => {
    const text = holdReason([UNREVIEWED])
    expect(text).toContain('shipgate-hud')
    expect(text).toContain('`git push`')
    expect(text).toContain('stream feature/held-stream')
    for (const demand of DEMANDS) expect(text).toContain(demand)
  })

  test('the deny on an unreviewed stream names the stream and the one record the model may write; never the user\'s decision', async () => {
    const text = denyReason([UNREVIEWED])
    expect(text).toContain('`git push`')
    expect(text).toContain('stream feature/held-stream')
    for (const demand of DEMANDS) expect(text).toContain(demand)
    expect(text).toContain('journal.py append --type review-verdict')
    expect(text).toContain('never recorded on their behalf')
    expect(text).not.toContain('--type gate-decision')
  })

  // D14: an unreadable journal is the cause; a stale stream is never named, and the model is
  // never sent to record a verdict for a stream nobody read.
  test('D14: the hold on an unreadable journal names the failure, no stream', async () => {
    const text = holdReason([UNREADABLE])
    expect(text).toContain('`gh pr create`')
    expect(text).toContain(failureText(FAILURE))
    expect(text).toContain('database is locked')
    expect(text).not.toContain('stream feature/')
  })

  test('D14: the deny on an unreadable journal names the failure and sends the model to the read, not to a verdict', async () => {
    const text = denyReason([UNREADABLE])
    expect(text).toContain('`gh pr create`')
    expect(text).toContain(failureText(FAILURE))
    expect(text).not.toContain('append --type review-verdict')
    expect(text).not.toContain('--type gate-decision')
    expect(text).toContain('never recorded on their behalf')
  })

  test('a cut read is named as one', async () => {
    expect(holdReason([{ kind: 'Unreadable', head: 'git push', failure: { kind: 'Cut' } }])).toContain(failureText({ kind: 'Cut' }))
  })

  // R2-N1: one "Let it through once" passes the whole line, so the dialog and the deny name every held command.
  const NEEDS =
    'Publishing needs a `review-verdict` with `verdict: ready`, or a `gate-decision` with `gate: publish`, `raised_by: user` and `decision: publish`, recorded after the last `task-done`.'
  const ASK_USER =
    'or stop and ask the user: their decision is taken at the dialog this gate shows ("Let it through once"), never recorded on their behalf. Then run the command again.'

  test('R2-N1: a line with one hold keeps the one-command wording', async () => {
    expect(holdReason([UNREVIEWED])).toBe(`shipgate-hud holds \`git push\` for stream feature/held-stream. ${NEEDS}`)
    expect(denyReason([UNREVIEWED])).toBe(
      `shipgate-hud refused \`git push\` for stream feature/held-stream. ${NEEDS} Finish the review and record its verdict with \`journal.py append --type review-verdict\` (\`verdict: ready\`), ${ASK_USER}`,
    )
    expect(denyReason([UNREADABLE])).toBe(
      `shipgate-hud refused \`gh pr create\` for the stream of the branch it publishes: the journal could not be read (${failureText(FAILURE)}). ${NEEDS} Find out why the journal could not be read and fix that, ${ASK_USER}`,
    )
  })

  const SECOND = must(streamName('feature/second-stream'))
  const SECOND_HOLD: Hold = { kind: 'Unreviewed', head: 'gh pr create', stream: SECOND }

  test('R2-N1: two holds: the dialog names each held command with its stream, in line order', async () => {
    const text = holdReason([UNREVIEWED, SECOND_HOLD])
    expect(text).toContain('shipgate-hud holds this line:')
    const first = text.indexOf('`git push` for stream feature/held-stream')
    const second = text.indexOf('`gh pr create` for stream feature/second-stream')
    expect(first).toBeGreaterThan(-1)
    expect(second).toBeGreaterThan(first)
    for (const demand of DEMANDS) expect(text).toContain(demand)
    // the order is the line's
    const swapped = holdReason([SECOND_HOLD, UNREVIEWED])
    expect(swapped.indexOf('feature/second-stream')).toBeLessThan(swapped.indexOf('feature/held-stream'))
  })

  test('R2-N1: two holds: the deny names both streams and what each still needs; never the user\'s decision', async () => {
    const text = denyReason([UNREVIEWED, SECOND_HOLD])
    expect(text).toContain('shipgate-hud refused this line:')
    expect(text).toContain('`git push` for stream feature/held-stream')
    expect(text).toContain('`gh pr create` for stream feature/second-stream')
    expect(text).toContain('stream feature/held-stream and stream feature/second-stream')
    expect(text).toContain('journal.py append --type review-verdict')
    expect(text).toContain('never recorded on their behalf')
    expect(text).not.toContain('--type gate-decision')
    expect(text).not.toContain('could not be read')
  })

  test('R2-N1: a hold and an unreadable journal: both are named, and the deny sends the model to the review and to the read', async () => {
    const hold = holdReason([UNREVIEWED, UNREADABLE])
    expect(hold).toContain('`git push` for stream feature/held-stream')
    expect(hold).toContain(`\`gh pr create\` for the stream of the branch it publishes: the journal could not be read (${failureText(FAILURE)})`)
    expect(hold.indexOf('`git push`')).toBeLessThan(hold.indexOf('`gh pr create`'))
    const deny = denyReason([UNREVIEWED, UNREADABLE])
    expect(deny).toContain('`git push` for stream feature/held-stream')
    expect(deny).toContain(failureText(FAILURE))
    expect(deny).toContain('journal.py append --type review-verdict')
    expect(deny).toContain('find out why the journal could not be read and fix that')
    expect(deny).toContain('never recorded on their behalf')
    expect(deny).not.toContain('--type gate-decision')
  })

  test('R2-N1: only unreadable holds: the deny sends the model to the read, not to a verdict', async () => {
    const deny = denyReason([UNREADABLE, { kind: 'Unreadable', head: 'git push', failure: { kind: 'Cut' } }])
    expect(deny).toContain(failureText(FAILURE))
    expect(deny).toContain(failureText({ kind: 'Cut' }))
    expect(deny).not.toContain('append --type review-verdict')
    expect(deny).toContain('Find out why the journal could not be read and fix that')
  })
})
