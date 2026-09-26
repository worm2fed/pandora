#!/usr/bin/env bash
# Run one eval case of a plugin through `claude plugin eval` with this machine's
# workarounds applied. Costs real money (about $1 per case per with+without tree).
#
#   run-case.sh [--config-dir DIR] <plugin-dir> <NN> [extra eval flags...]
#
#   run-case.sh shipgate 05
#   run-case.sh shipgate 10 --runs 1 -j 3 --keep-temp --max-cost-usd 2
#   run-case.sh --config-dir ~/.claude shipgate 11     # bill a specific account
#
# Config dir: --config-dir, else $EVAL_CONFIG_DIR, else $CLAUDE_CONFIG_DIR, else
# ~/.claude. Runs under a scratch HOME (credential-store symlink check), refuses
# the Xcode git shim, and drops CLAUDECODE so the nested claude starts clean.
# Exit status is the harness's: 1 means some case scored below --threshold
# (default 1.0, so 1 is normal), 2 means --max-cost-usd was hit.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
. "$here/_common.sh"

cfg_flag=""
if [ "${1:-}" = "--config-dir" ]; then cfg_flag="${2:-}"; shift 2; fi
if [ $# -lt 2 ]; then sed -n '2,15p' "$0" >&2; exit 64; fi
[ -d "$1" ] || die "plugin dir not found: $1"
plugin=$(cd "$1" && pwd); shift
nn=$1; shift
case "$nn" in *\**) glob="$nn" ;; *) glob="${nn}-*" ;; esac

cfg=$(resolve_config_dir "$cfg_flag")
check_git
home=$(make_scratch_home)
trap 'rm -rf "$home"' EXIT
results_root="$plugin/evals/results"
before=$(ls -d "$results_root"/*/ 2>/dev/null | sort || true)

printf 'run-evals: plugin=%s case=%s config-dir=%s\n' "$plugin" "$glob" "$cfg" >&2
printf 'run-evals: claude plugin eval %s --runs 3 --ablation with-without --scaffold --judge-model sonnet --no-publish --allow-tools Bash Edit Write --case %q %s\n' "$plugin" "$glob" "$*" >&2

status=0
harness_log=$(mktemp "${TMPDIR:-/tmp}/eval-run.XXXXXX")
trap 'rm -rf "$home" "$harness_log"' EXIT
env -u CLAUDECODE HOME="$home" CLAUDE_CONFIG_DIR="$cfg" \
  claude plugin eval "$plugin" \
    --runs 3 --ablation with-without --scaffold --judge-model sonnet --no-publish \
    --allow-tools Bash Edit Write \
    --case "$glob" "$@" 2>&1 | tee "$harness_log" || status=$?

# The harness prints its own results dir ("Report: <dir>/report.html"); trust that first,
# because a before/after listing picks up dirs written by other cases running in parallel.
new=$(grep -oE 'Report: .*/report\.html' "$harness_log" | tail -1 | sed -e 's/^Report: //' -e 's|/report\.html$||')
if [ -z "$new" ]; then
  after=$(ls -d "$results_root"/*/ 2>/dev/null | sort || true)
  new=$(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | tail -1)
fi
if [ -n "$new" ]; then
  printf '\nrun-evals: results dir: %s\n' "${new%/}"
  printf 'run-evals: summarize:   python3 %s/summarize.py %s\n' "$here" "${new%/}"
else
  printf '\nrun-evals: no new dir under %s (did you pass --output-dir/--eval-dir, or did the run abort?)\n' "$results_root" >&2
fi
printf 'run-evals: harness exit status %s (1 = below --threshold, 2 = cost ceiling hit)\n' "$status" >&2
exit "$status"
