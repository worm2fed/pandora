import { describe, expect, test } from 'claude-code/testing'

import { denyReason, holdReason, publishCommandOf } from '../hooks/publish'

describe('publish', () => {
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
  ]
  for (const command of pushes) {
    test(`held: ${JSON.stringify(command)}`, async () => {
      expect(publishCommandOf(command)).toBe('git push')
    })
  }

  const prs: [string, string][] = [
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
  ]
  for (const [command, head] of prs) {
    test(`held: ${JSON.stringify(command)}`, async () => {
      expect(publishCommandOf(command)).toBe(head)
    })
  }

  test('the first head found wins', async () => {
    expect(publishCommandOf('gh pr create && git push')).toBe('gh pr create')
  })

  test('a command after a heredoc body is still read', async () => {
    expect(publishCommandOf("cat <<'EOF' > f\nx\nEOF\ngit push")).toBe('git push')
  })

  const passes = [
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
    "sh -c 'git push'",
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
  ]
  for (const command of passes) {
    test(`passes: ${JSON.stringify(command)}`, async () => {
      expect(publishCommandOf(command)).toBeNull()
    })
  }

  test('reasons name the plugin, the command, the stream and what is missing', async () => {
    const hold = holdReason('git push', { stream: 'feat/x' }, null)
    expect(hold).toContain('shipgate-hud')
    expect(hold).toContain('git push')
    expect(hold).toContain('feat/x')
    expect(hold).toContain('review-verdict')
    expect(hold).toContain('task-done')
    const deny = denyReason('git push', { stream: 'feat/x' }, null)
    expect(deny).toContain('feat/x')
    expect(deny).toContain('journal.py append --type review-verdict')
    expect(deny).toContain('ask the user')
    expect(deny).toContain('Let it through once')
    // never a recipe for the model to record the user's decision itself
    expect(deny).not.toContain('--actor user')
    expect(deny).not.toContain('--type gate-decision')
    const broken = denyReason('gh pr create', null, 'shipgate-hud: journal database not found')
    expect(broken).toContain('the journal could not be read: shipgate-hud: journal database not found')
    expect(broken).toContain('gh pr create')
  })
})
