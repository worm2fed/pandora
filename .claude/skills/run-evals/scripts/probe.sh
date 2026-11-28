#!/usr/bin/env bash
# Cheap triggering probe: does the plugin's skill fire on a case's prompt, and does the
# run stay clear of the calls the case names? No graders, no ablation, about $0.15 a run
# on Opus and $0.30 on Fable (measured 2026-11-27). It measures TRIGGERING ONLY, not answer
# quality (ADR 0036).
#
#   probe.sh [--config-dir DIR] --model M <plugin-dir> <NN|probes> [runs=3] [max-turns=4]
#               (the flags may come in any position)
#
#   --model M   required; passed to `claude -p --model M` and saved with the result
#   NN          one probe case: <plugin-dir>/evals/NN-*/ with probe.md (the prompt) and
#               probe.json (the expectation). A case with prompt.md and no probe.json
#               runs count-only.
#   probes      every case in the "probes" list of <plugin-dir>/evals/sets.json, read by
#               `evalrun.py set-cases` (it refuses a parked, empty or repeated case)
#   runs, max-turns  whole numbers above 0
#
# Refuses to start (exit 1) when evals/evalrun.py config-check finds a plugin of the same
# name in the paying config dir or enabled in the managed settings. probe.py judges the
# runs; one result file per case goes to
# <plugin-dir>/evals/results/probes/<stamp>/<case>.json. Prints one line per run:
#   11-neg-one-line-change run1: PASS skill=[] bash{signals\.py}=0 agent=0 turns=3 cost=$0.08 12s
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
. "$here/_common.sh"

usage() { usage_exit "$0" "$@"; }

cfg_flag="" model="" args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --config-dir) [ $# -ge 2 ] || usage; cfg_flag=$2; shift 2 ;;
    --model) [ $# -ge 2 ] || usage; model=$2; shift 2 ;;
    -h|--help) usage ;;
    --*) usage "unknown flag: $1" ;;
    *) args+=("$1"); shift ;;
  esac
done
[ -n "$model" ] || usage "--model is required"
[ ${#args[@]} -ge 2 ] || usage
set -- "${args[@]}"
[ -d "$1" ] || die "plugin dir not found: $1"
plugin=$(cd "$1" && pwd); shift
target=$1; shift
runs=${1:-3}
max_turns=${2:-4}
case "$runs" in ''|0*|*[!0-9]*) usage "runs takes a whole number above 0, got: $runs" ;; esac
case "$max_turns" in ''|0*|*[!0-9]*) usage "max-turns takes a whole number above 0, got: $max_turns" ;; esac

evals="$plugin/evals"
probe_py="$evals/probe.py"
[ -f "$probe_py" ] || die "no $probe_py"
evalrun_py=$(evalrun_of "$plugin")

if [ "$target" = probes ]; then
  sets="$evals/sets.json"
  [ -f "$sets" ] || die "no sets file $sets: the probes set needs a \"probes\" list there"
  names=$(python3 "$evalrun_py" set-cases "$sets" probes) || exit 1
  case_dirs=()
  while IFS= read -r name; do case_dirs+=("$evals/$name"); done <<EOF
$names
EOF
else
  matches=( "$evals/$target"-*/ )
  [ ${#matches[@]} -eq 1 ] && [ -d "${matches[0]}" ] || die "expected exactly one case matching $evals/$target-*/, got: ${matches[*]}"
  case_dirs=( "${matches[0]%/}" )
fi

for case_dir in "${case_dirs[@]}"; do
  [ -d "$case_dir" ] || die "no case dir $case_dir"
  if [ -f "$case_dir/probe.md" ]; then
    [ -f "$case_dir/probe.json" ] || die "probe.md without probe.json in $case_dir"
    python3 "$probe_py" check "$case_dir/probe.json" || exit 1
  elif [ ! -f "$case_dir/prompt.md" ]; then
    die "no probe.md (or prompt.md) in $case_dir"
  fi
done

cfg=$(resolve_config_dir "$cfg_flag")
python3 "$evalrun_py" config-check --config-dir "$cfg" --plugin-dir "$plugin" || exit 1
check_git
home=$(make_scratch_home)
trap 'rm -rf "$home"' EXIT
stamp=$(date -u +%Y-%m-%dT%H-%M-%SZ)
results="$evals/results/probes/$stamp"
out=$(mktemp -d "${TMPDIR:-/tmp}/eval-probe.XXXXXX")
tools="Bash Read Grep Glob Skill Edit Write"

printf 'run-evals: probe %s x%s (max-turns %s) model=%s config-dir=%s\n' \
  "$target" "$runs" "$max_turns" "$model" "$cfg" >&2

for case_dir in "${case_dirs[@]}"; do
  case_name=$(basename "$case_dir")
  expect=()
  if [ -f "$case_dir/probe.md" ]; then
    prompt_file="$case_dir/probe.md"
    expect=(--expect "$case_dir/probe.json")
  else
    prompt_file="$case_dir/prompt.md"
    printf 'run-evals: %s has no probe.json; counting only\n' "$case_name" >&2
  fi
  # Strip the YAML frontmatter block (--- ... ---); claude -p must not see it.
  prompt=$(awk 'NR==1 && $0=="---" {fm=1; next} fm && $0=="---" {fm=0; next} !fm' "$prompt_file")
  [ -n "$prompt" ] || die "empty prompt after stripping frontmatter: $prompt_file"

  logs=()
  for ((k = 1; k <= runs; k++)); do
    work="$out/$case_name/run$k"
    mkdir -p "$work"
    if [ -f "$case_dir/fixture.sh" ]; then
      (cd "$work" && bash "$case_dir/fixture.sh" > "$out/$case_name/run$k.fixture.log" 2>&1) \
        || die "fixture.sh failed for $case_name (see $out/$case_name/run$k.fixture.log)"
    fi
    log="$out/$case_name/run$k.jsonl"
    printf 'run-evals: %s run %s/%s\n' "$case_name" "$k" "$runs" >&2
    (cd "$work" && env -u CLAUDECODE HOME="$home" CLAUDE_CONFIG_DIR="$cfg" \
      claude -p "$prompt" --model "$model" --plugin-dir "$plugin" --setting-sources "" --strict-mcp-config \
        --allowedTools "$tools" --max-turns "$max_turns" \
        --output-format stream-json --verbose) > "$log" 2> "$out/$case_name/run$k.stderr" || true
    logs+=("$log")
  done

  python3 "$probe_py" judge --case "$case_name" --model "$model" --plugin-dir "$plugin" \
    ${expect[@]+"${expect[@]}"} --out "$results/$case_name.json" "${logs[@]}"
  printf 'result: %s\n' "$results/$case_name.json"
done
printf 'run-evals: stream logs kept in %s\n' "$out" >&2
