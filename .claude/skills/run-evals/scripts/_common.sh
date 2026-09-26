#!/usr/bin/env bash
# Shared helpers for run-case.sh and probe.sh. Sourced, never executed.
#
# Nothing account- or machine-specific lives here: the Claude config dir that
# eval runs are billed to is discovered at runtime (resolve_config_dir).

die() { printf 'run-evals: %s\n' "$*" >&2; exit 1; }

# Print the Claude config dir to bill eval runs to. Resolution order:
#   1. --config-dir DIR (passed in as $1)
#   2. $EVAL_CONFIG_DIR   — set this in your shell profile to the account that should pay
#   3. $CLAUDE_CONFIG_DIR — whatever the current shell has set
#   4. ~/.claude
resolve_config_dir() {
  local dir="${1:-${EVAL_CONFIG_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}}"
  [ -n "$dir" ] || die "cannot resolve a Claude config dir: pass --config-dir DIR or set EVAL_CONFIG_DIR"
  dir="${dir/#\~/$HOME}"
  dir="${dir/#\$HOME/$HOME}"
  dir="${dir/#\$\{HOME\}/$HOME}"
  [ -d "$dir" ] || die "config dir does not exist: $dir"
  printf '%s\n' "$dir"
}

# Refuse to run while the Xcode git shim would be the git the agent sandbox sees.
check_git() {
  [ "${EVAL_SKIP_GIT_CHECK:-}" = 1 ] && return 0
  local first
  first=$(command -v git || true)
  [ -n "$first" ] || die "git not found on PATH"
  case "$first" in
    /usr/bin/git) die "first git on PATH is the Xcode shim ($first), which the agent sandbox blocks; brew install git and put /opt/homebrew/bin first on PATH (EVAL_SKIP_GIT_CHECK=1 overrides)" ;;
    /opt/homebrew/bin/git|/usr/local/bin/git) ;;
    *) printf 'run-evals: warning: first git on PATH is %s, not Homebrew git\n' "$first" >&2 ;;
  esac
}

# An empty scratch HOME: the harness scans $HOME for credential stores that
# contain symlinks (Docker Desktop's ~/.docker does) and refuses Bash-granting
# runs when it finds one. An empty HOME has nothing to scan.
make_scratch_home() {
  mktemp -d "${TMPDIR:-/tmp}/eval-home.XXXXXX"
}
