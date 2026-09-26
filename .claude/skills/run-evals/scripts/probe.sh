#!/usr/bin/env bash
# Cheap triggering probe: does the plugin's skill fire on a case's prompt?
# No graders, no ablation, about $0.10 per run. It measures TRIGGERING ONLY,
# not answer quality; the harness (run-case.sh) is the gate. Use it to iterate
# on a skill description before paying for a full tree.
#
#   probe.sh [--config-dir DIR] <plugin-dir> <NN> [runs=1] [max-turns=4]
#
# Prints one line per run:
#   05-fix-it-wording run1: skill=[shipgate:structured-debug] turns=3 cost=$0.08
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source-path=SCRIPTDIR
. "$here/_common.sh"

cfg_flag=""
if [ "${1:-}" = "--config-dir" ]; then cfg_flag="${2:-}"; shift 2; fi
if [ $# -lt 2 ]; then sed -n '2,11p' "$0" >&2; exit 64; fi
[ -d "$1" ] || die "plugin dir not found: $1"
plugin=$(cd "$1" && pwd); shift
nn=$1; shift
runs=${1:-1}
max_turns=${2:-4}

matches=( "$plugin/evals/$nn"-*/ )
[ ${#matches[@]} -eq 1 ] && [ -d "${matches[0]}" ] || die "expected exactly one case matching $plugin/evals/$nn-*/, got: ${matches[*]}"
case_dir=${matches[0]%/}
case_name=$(basename "$case_dir")
[ -f "$case_dir/prompt.md" ] || die "no prompt.md in $case_dir"

# Strip the YAML frontmatter block (--- ... ---) the harness reads; claude -p must not see it.
prompt=$(awk 'NR==1 && $0=="---" {fm=1; next} fm && $0=="---" {fm=0; next} !fm' "$case_dir/prompt.md")
[ -n "$prompt" ] || die "empty prompt after stripping frontmatter: $case_dir/prompt.md"

cfg=$(resolve_config_dir "$cfg_flag")
check_git
home=$(make_scratch_home)
trap 'rm -rf "$home"' EXIT
out=$(mktemp -d "${TMPDIR:-/tmp}/eval-probe.$case_name.XXXXXX")
tools="Bash Read Grep Glob Skill Edit Write"

printf 'run-evals: probe %s x%s (max-turns %s) config-dir=%s\n' "$case_name" "$runs" "$max_turns" "$cfg" >&2

for ((k = 1; k <= runs; k++)); do
  work="$out/run$k"
  mkdir -p "$work"
  if [ -f "$case_dir/fixture.sh" ]; then
    (cd "$work" && bash "$case_dir/fixture.sh" > "$out/run$k.fixture.log" 2>&1) \
      || die "fixture.sh failed for $case_name (see $out/run$k.fixture.log)"
  fi
  log="$out/run$k.jsonl"
  (cd "$work" && env -u CLAUDECODE HOME="$home" CLAUDE_CONFIG_DIR="$cfg" \
    claude -p "$prompt" --plugin-dir "$plugin" --setting-sources "" --strict-mcp-config \
      --allowedTools "$tools" --max-turns "$max_turns" \
      --output-format stream-json --verbose) > "$log" 2> "$out/run$k.stderr" || true

  python3 - "$case_name" "$k" "$log" "$out/run$k.stderr" <<'PY'
import json, sys
case, k, log, errlog = sys.argv[1:5]
skills, turns, cost, err, raw = [], None, None, None, []
with open(log, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            raw.append(line)          # e.g. "You've hit your weekly limit"
            continue
        t = e.get("type")
        if t == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                    skills.append(str((b.get("input") or {}).get("skill", "?")))
        elif t == "result":
            turns, cost = e.get("num_turns"), e.get("total_cost_usd")
            if e.get("is_error"):
                err = e.get("result") or e.get("subtype")
turns_s = "?" if turns is None else str(turns)
cost_s = "?" if cost is None else f"{cost:.2f}"
print(f"{case} run{k}: skill=[{', '.join(skills)}] turns={turns_s} cost=${cost_s}")
if err:
    print(f"  error: {err}")
for r in raw[:3]:
    print(f"  stdout: {r}")
if turns is None and not raw:
    tail = open(errlog, encoding="utf-8", errors="replace").read().strip().splitlines()[-3:]
    for r in tail:
        print(f"  stderr: {r}")
PY
done
printf 'run-evals: stream logs kept in %s\n' "$out" >&2
