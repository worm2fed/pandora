#!/usr/bin/env bash
# Run one eval case of a plugin through `claude plugin eval` with this machine's
# workarounds applied. Costs real money (about $1 per case per with+without tree).
#
#   run-case.sh [--config-dir DIR] [--no-codegraph] (--ablation with-without|none | --bare)
#               --model M <plugin-dir> <NN> [extra eval flags...]
#
#   <NN> is a two-digit prefix (the case filter is 'NN-*') or the full name of an eval
#   case: a dir <plugin-dir>/evals/<name> that holds prompt.md or case.yaml (the filter is
#   that name alone). A dir there that holds neither (a probe, a fixture case, results) is
#   refused as not an eval case.
#
#   run-case.sh --ablation with-without --model M shipgate 05
#   run-case.sh --bare --model claude-fable-5-2 shipgate 24       # bare arm alone (ADR 0035)
#   run-case.sh --ablation none --model M shipgate 10 --runs 1 -j 3 --max-cost-usd 2
#   run-case.sh --config-dir ~/.claude --ablation with-without --model M shipgate 11
#   run-case.sh --no-codegraph --ablation with-without --model M shipgate 13
#
# A mode and a model are required; there is no default. --bare runs the case on a stub
# plugin with no component (`evalrun.py bare-stub`) under --ablation none, and writes
# bare.json. The mode and model flags go before <plugin-dir>, never among the extras.
# Config dir: --config-dir, else $EVAL_CONFIG_DIR, else $CLAUDE_CONFIG_DIR, else
# ~/.claude. The run refuses to start when that dir has a plugin of the same name
# installed or enabled (`evalrun.py config-check`). It runs under a scratch HOME
# (credential-store symlink check), refuses the Xcode git shim, and drops CLAUDECODE so
# the nested claude starts clean. The harness always gets --keep-temp; after the run,
# `evalrun.py post-run` writes shadow.json (and script-graders.json), then removes the
# kept sandboxes unless you passed --keep-temp yourself. The script sets the results dir:
# a new dir under <plugin-dir>/evals/results, passed as --output-dir, so it refuses a
# caller's --output-dir among the extras (exit 64). A run that leaves no
# aggregate-result.json there has no result, and no post-run step runs.
# Exit status is the harness's: 1 means some case scored below --threshold (default 1.0,
# so 1 is normal), 2 means --max-cost-usd was hit. 64 is a usage error; 1 before the run
# is a refusal.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
. "$here/_common.sh"

cfg_flag=""
no_codegraph=""
mode=""
ablation=""
model=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config-dir) [ $# -ge 2 ] || usage_exit "$0" "--config-dir needs a dir"; cfg_flag=$2; shift 2 ;;
    --no-codegraph) no_codegraph=1; shift ;;
    --ablation)
      [ -z "$mode" ] || usage_exit "$0" "give one mode: --ablation or --bare, once"
      case "${2:-}" in with-without|none) ;; *) usage_exit "$0" "--ablation takes with-without or none" ;; esac
      mode=$2; ablation=$2; shift 2 ;;
    --bare)
      [ -z "$mode" ] || usage_exit "$0" "give one mode: --ablation or --bare, once"
      mode=bare; ablation=none; shift ;;
    --model) [ -n "${2:-}" ] || usage_exit "$0" "--model needs a model id"; model=$2; shift 2 ;;
    *) break ;;
  esac
done
[ -n "$mode" ] || usage_exit "$0" "no mode: pass --ablation with-without, --ablation none or --bare"
[ -n "$model" ] || usage_exit "$0" "no model: pass --model M"
[ $# -ge 2 ] || usage_exit "$0"
keep_asked=""
for a in "${@:3}"; do
  case "$a" in
    --ablation|--ablation=*|--bare|--model|--model=*) usage_exit "$0" "$a goes before <plugin-dir>, not among the extra eval flags" ;;
    --keep-temp) keep_asked=1 ;;
    --output-dir|--output-dir=*) usage_exit "$0" "$a: run-case.sh sets the results dir itself, a new dir under <plugin-dir>/evals/results" ;;
  esac
done
[ -d "$1" ] || die "plugin dir not found: $1"
plugin=$(cd "$1" && pwd); shift
nn=$1; shift
[ -n "$nn" ] || usage_exit "$0" "<NN> is empty: pass a two-digit prefix or a full case name"
glob=""
case "$nn" in
  */*) ;;
  .|..) usage_exit "$0" "$nn is not an eval case" ;;
  *)
    if [ -d "$plugin/evals/$nn" ]; then
      [ -f "$plugin/evals/$nn/prompt.md" ] || [ -f "$plugin/evals/$nn/case.yaml" ] \
        || usage_exit "$0" "$plugin/evals/$nn is not an eval case: it has no prompt.md or case.yaml"
      glob=$nn
    fi ;;
esac
[ -n "$glob" ] || case "$nn" in *\**) glob="$nn" ;; *) glob="${nn}-*" ;; esac

cfg=$(resolve_config_dir "$cfg_flag")
evalrun=$(evalrun_of "$plugin")
python3 "$evalrun" config-check --config-dir "$cfg" --plugin-dir "$plugin" || exit 1
check_git
claude_bin=$(command -v claude) || die "claude not found on PATH"
run_path=$PATH
if [ -n "$no_codegraph" ]; then
  run_path=$(path_without_codegraph)
  ! PATH="$run_path" command -v codegraph >/dev/null || die "codegraph still on PATH after the filter"
  printf 'run-evals: --no-codegraph: codegraph removed from the agent PATH\n' >&2
fi
home=$(make_scratch_home)
stub_root=""
trap 'rm -rf "$home" ${stub_root:+"$stub_root"}' EXIT
target=$plugin
if [ "$mode" = bare ]; then
  stub_root=$(mktemp -d "${TMPDIR:-/tmp}/eval-bare.XXXXXX")
  target=$(python3 "$evalrun" bare-stub "$plugin" "$stub_root/plugin") || die "cannot build the bare stub"
fi

# The results dir is this script's own: a name like the harness's default dirs (a UTC
# stamp with milliseconds, so compare.py's by-name order holds) plus this script's pid, so
# two runs side by side never share it. mkdir fails on an existing name. The harness
# writes into a dir given with --output-dir whether or not it exists.
results_root="$plugin/evals/results"
mkdir -p "$results_root" || die "cannot make the results root $results_root"
stamp=$(python3 -c 'import datetime as d; t = d.datetime.now(d.timezone.utc); print(t.strftime("%Y-%m-%dT%H-%M-%S-") + "%03dZ" % (t.microsecond // 1000))') \
  || die "cannot make the results dir name"
out="$results_root/$stamp-$$"
mkdir "$out" || die "cannot make the results dir $out"

eval_args=(plugin eval "$target" --runs 3 --ablation "$ablation" --scaffold --judge-model sonnet --no-publish
  --allow-tools Bash Edit Write --model "$model")
[ -n "$keep_asked" ] || eval_args+=(--keep-temp)
eval_args+=(--output-dir "$out" --case "$glob")

printf 'run-evals: plugin=%s case=%s mode=%s model=%s config-dir=%s\n' "$plugin" "$glob" "$mode" "$model" "$cfg" >&2
[ "$mode" != bare ] || printf 'run-evals: bare stub: %s (no component; evals -> %s/evals)\n' "$target" "$plugin" >&2
printf 'run-evals: claude%s\n' "$(printf ' %q' "${eval_args[@]}" "$@")" >&2

status=0
env -u CLAUDECODE HOME="$home" CLAUDE_CONFIG_DIR="$cfg" PATH="$run_path" \
  "$claude_bin" "${eval_args[@]}" "$@" 2>&1 || status=$?

if [ -f "$out/aggregate-result.json" ]; then
  new=$out
  printf '\nrun-evals: results dir: %s\n' "$new"
  printf 'run-evals: summarize:   python3%s\n' "$(printf ' %q' "$here/summarize.py" "$new")"
  # A case with an expected.json gets the signal grader (ADR 0016): precision and recall
  # of the signals.py blast result the agent read. It never changes this script's status.
  grader="$plugin/evals/signal_grader.py"
  for d in "$plugin"/evals/$glob/; do
    if [ -f "$grader" ] && [ -f "${d}expected.json" ]; then
      printf '\nrun-evals: signal grader (reads the kept trace.jsonl): python3%s\n' "$(printf ' %q' "$grader" results "$new")"
      python3 "$grader" results "$new" || printf 'run-evals: signal grader exited %s; the harness status stands\n' "$?" >&2
      break
    fi
  done
  # Shadow check, script graders and clean-up (ADR 0036). Never changes this script's status.
  post_args=(post-run "$new" --plugin-dir "$plugin")
  [ "$mode" != bare ] || post_args+=(--bare)
  [ -n "$keep_asked" ] || post_args+=(--clean)
  printf '\nrun-evals: post-run: python3%s\n' "$(printf ' %q' "$evalrun" "${post_args[@]}")"
  python3 "$evalrun" "${post_args[@]}" || printf 'run-evals: post-run exited %s; the harness status stands\n' "$?" >&2
else
  printf '\nrun-evals: no aggregate-result.json in %s, so this run has no result; no post-run check, grade or clean-up ran\n' "$out" >&2
  rmdir "$out" 2>/dev/null || printf 'run-evals: %s stays: it holds files but no aggregate-result.json\n' "$out" >&2
  printf 'run-evals: any kept sandboxes of its runs stay on disk; the harness printed their paths above\n' >&2
fi
printf 'run-evals: harness exit status %s (1 = below --threshold, 2 = cost ceiling hit)\n' "$status" >&2
exit "$status"
