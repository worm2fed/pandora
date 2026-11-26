#!/usr/bin/env bash
# Run the cases of a named set one after another, one run-case.sh at a time in the
# foreground, under one cost ceiling. Costs real money (each case costs what its
# run-case.sh run costs).
#
#   run-set.sh [--config-dir DIR] [--sets FILE] [--shard K/N] --max-cost-usd C
#              (--ablation with-without|none | --bare) --model M <plugin-dir> <set>
#              [extra eval flags...]
#
#   run-set.sh --max-cost-usd 31 --bare --model claude-fable-5-2 shipgate ablation-32
#   run-set.sh --shard 2/3 --max-cost-usd 12 --ablation with-without --model M shipgate kept
#
# Sets: --sets FILE, else <plugin-dir>/evals/sets.json; each set lists case directory
# names (`evalrun.py set-cases`). The set "parked" never runs, and a set that holds a
# parked case is refused. Each case runs by its full dir name, so only the cases of the
# set run. Mode, model, --config-dir and the extra flags go to every run-case.sh.
# Shards: --shard K/N runs only the cases whose place in the set (1, 2, ...) is K modulo
# N. To run a set faster, start --shard 1/3, 2/3 and 3/3 side by side, one per terminal,
# each with its own ceiling.
# Ceiling: --max-cost-usd C is required and bounds this invocation. Before each case the
# script sums the agent and judge cost of the results dirs of this invocation so far
# (`evalrun.py spent`). It stops when that reaches C, and passes the case
# --max-cost-usd = what is left of C. A case that hits that ceiling (exit 2) stops the set.
# Stop: Ctrl-C reaches the running case and its claude child, which stop with it. A
# signal to this script's PID alone does not: signal the process group. A case
# that ends on a signal (exit above 128) stops the set with that status. A case that
# leaves no results dir stops the set too, because its spend cannot be counted.
# Exit status: 0 when every case of the shard ran (a case below --threshold still ran),
# 2 when the ceiling stopped the set, 1 when a case left no results dir or on an error,
# 64 on a usage error, above 128 when a case ended on a signal.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
. "$here/_common.sh"

pre_args=()
sets=""
shard_k=1
shard_n=1
cap=""
mode=""
model=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config-dir) [ $# -ge 2 ] || usage_exit "$0" "--config-dir needs a dir"; pre_args+=(--config-dir "$2"); shift 2 ;;
    --sets) [ $# -ge 2 ] || usage_exit "$0" "--sets needs a file"; sets=$2; shift 2 ;;
    --shard)
      printf '%s\n' "${2:-}" | grep -Eq '^[1-9][0-9]*/[1-9][0-9]*$' || usage_exit "$0" "--shard takes K/N, two whole numbers above 0"
      shard_k=${2%/*}; shard_n=${2#*/}
      [ "$shard_k" -le "$shard_n" ] || usage_exit "$0" "--shard K/N needs K <= N"
      shift 2 ;;
    --max-cost-usd)
      printf '%s\n' "${2:-}" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || usage_exit "$0" "--max-cost-usd takes a number of USD"
      cap=$2; shift 2 ;;
    --ablation)
      [ -z "$mode" ] || usage_exit "$0" "give one mode: --ablation or --bare, once"
      case "${2:-}" in with-without|none) ;; *) usage_exit "$0" "--ablation takes with-without or none" ;; esac
      mode=$2; pre_args+=(--ablation "$2"); shift 2 ;;
    --bare)
      [ -z "$mode" ] || usage_exit "$0" "give one mode: --ablation or --bare, once"
      mode=bare; pre_args+=(--bare); shift ;;
    --model) [ -n "${2:-}" ] || usage_exit "$0" "--model needs a model id"; model=$2; pre_args+=(--model "$2"); shift 2 ;;
    *) break ;;
  esac
done
[ -n "$cap" ] || usage_exit "$0" "no ceiling: pass --max-cost-usd C; every set runs under a ceiling"
[ -n "$mode" ] || usage_exit "$0" "no mode: pass --ablation with-without, --ablation none or --bare"
[ -n "$model" ] || usage_exit "$0" "no model: pass --model M"
[ $# -ge 2 ] || usage_exit "$0"
for a in "${@:3}"; do
  case "$a" in
    --ablation|--ablation=*|--bare|--model|--model=*|--shard|--shard=*|--sets|--sets=*)
      usage_exit "$0" "$a goes before <plugin-dir>, not among the extra eval flags" ;;
    --max-cost-usd|--max-cost-usd=*) usage_exit "$0" "give the ceiling once, before <plugin-dir>" ;;
  esac
done
[ -d "$1" ] || die "plugin dir not found: $1"
plugin=$(cd "$1" && pwd)
set_name=$2
shift 2

sets=${sets:-$plugin/evals/sets.json}
[ -f "$sets" ] || die "no sets file: $sets (pass --sets FILE)"
evalrun=$(evalrun_of "$plugin")
case_text=$(python3 "$evalrun" set-cases "$sets" "$set_name") || exit 1
todo=()
i=0
while IFS= read -r c; do
  [ -n "$c" ] || continue
  [ -f "$plugin/evals/$c/prompt.md" ] || [ -f "$plugin/evals/$c/case.yaml" ] \
    || die "set $set_name names $c, but $plugin/evals/$c is not an eval case"
  i=$((i + 1))
  [ $((i % shard_n)) -ne $((shard_k % shard_n)) ] || todo+=("$c")
done <<EOF
$case_text
EOF
printf 'run-evals: set %s, shard %s/%s: %s cases, mode=%s model=%s ceiling=%s USD\n' \
  "$set_name" "$shard_k" "$shard_n" "${#todo[@]}" "$mode" "$model" "$cap"
if [ ${#todo[@]} -eq 0 ]; then
  printf 'run-evals: no case in this shard\n'
  exit 0
fi
logdir=$(mktemp -d "${TMPDIR:-/tmp}/eval-set.XXXXXX")
printf 'run-evals: logs: %s\n' "$logdir"

dirs=()
n=0
for c in "${todo[@]}"; do
  spent=$(python3 "$evalrun" spent ${dirs[@]+"${dirs[@]}"}) || die "cannot sum the spend so far; the set stops"
  left=$(awk -v c="$cap" -v s="$spent" 'BEGIN { l = int((c - s) * 100) / 100; if (l < 0.01) print "none"; else printf "%.2f\n", l }')
  if [ "$left" = none ]; then
    printf 'run-evals: ceiling reached: spent %s of %s USD; not started: %s\n' "$spent" "$cap" "${todo[*]:$n}"
    exit 2
  fi
  n=$((n + 1))
  printf '\nrun-evals: case %s (%s of %s), ceiling %s USD\n' "$c" "$n" "${#todo[@]}" "$left"
  st=0
  bash "$here/run-case.sh" ${pre_args[@]+"${pre_args[@]}"} "$plugin" "$c" "$@" --max-cost-usd "$left" \
    | tee "$logdir/$c.log" || st=$?
  if [ "$st" -gt 128 ]; then
    printf 'run-evals: %s ended on a signal (exit %s); not started: %s\n' "$c" "$st" "${todo[*]:$n}" >&2
    exit "$st"
  fi
  d=$(sed -n 's/^run-evals: results dir: //p' "$logdir/$c.log" | tail -1)
  if [ -z "$d" ]; then
    printf 'run-evals: %s left no results dir (exit %s), so its spend is unknown; not started: %s\n' \
      "$c" "$st" "${todo[*]:$n}" >&2
    exit 1
  fi
  dirs+=("$d")
  if [ "$st" -eq 2 ]; then
    printf 'run-evals: ceiling reached in %s (exit 2); not started: %s\n' "$c" "${todo[*]:$n}"
    exit 2
  fi
done
total=$(python3 "$evalrun" spent "${dirs[@]}") || die "cannot sum the spend of the set"
printf '\nrun-evals: set %s, shard %s/%s: %s cases ran; spent %s USD (agent + judge)\n' \
  "$set_name" "$shard_k" "$shard_n" "$n" "$total"
exit 0
