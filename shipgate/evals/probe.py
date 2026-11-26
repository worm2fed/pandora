#!/usr/bin/env python3
"""Judge trigger-probe runs against a case's probe.json (ADR 0036, FR-016 to FR-018).

    python3 shipgate/evals/probe.py judge --case NAME --model M --plugin-dir P \\
        [--expect probe.json] --out FILE [--json] <run1.jsonl> [<run2.jsonl> ...]
    python3 shipgate/evals/probe.py check <probe.json>...

Each run file is the stream-json output of one `claude -p ... --output-format stream-json
--verbose` call. Per run the script reads:

- the skills that fired: the `skill` input of every Skill tool_use, in order;
- the Bash calls whose `command` matches each regex in `zero.bash`;
- the Agent calls (the legacy tool name `Task` counts too);
- the Edit and Write calls whose `file_path` matches each regex in `zero.edit` / `zero.write`;
- the turns, the cost and the time (`duration_ms` / 1000) of the result record.

An empty or absent pattern list counts every call of that tool (shown as `*`).

probe.json:

    {"skill": "structured-debug", "fires": false,
     "zero": {"bash": ["signals\\\\.py"], "agent": true, "edit": ["docs/"], "write": []}}

A fired skill matches when its name is `<plugin>:<skill>` or `<skill>`. With `fires: true`
a run passes only when the skill fired; with `fires: false`, only when it did not. Every
count named in `zero` must be 0 (`agent: true` checks the Agent count; an absent key is
not checked). A run with an error fails: a non-JSON line in the stream (a usage-limit
message), a result record with `is_error`, or no result record. The case passes only when
every run passes. Without --expect the script counts and judges nothing.

The result file holds the case, the model, the plugin name and version, the expectation,
every run (skills, counts, turns, cost, seconds, passed, failures, error), the case verdict
and the summed cost.

`check` validates probe.json files before a probe spends anything.

Exit codes:

    0  the runs were read and the result file was written (check: every file is valid)
    1  input error (a missing run file, an unreadable probe.json or plugin.json)
    2  usage error
"""
import argparse
import json
import os
import re
import sys

EXIT_INPUT = 1
TOOLS = ("bash", "agent", "edit", "write")
PATTERN_TOOLS = {"bash": ("Bash", "command"), "edit": ("Edit", "file_path"), "write": ("Write", "file_path")}
AGENT_NAMES = ("Agent", "Task")
EVERY = "*"


class ProbeError(Exception):
    """An input the probe cannot use; exits with EXIT_INPUT."""


# --------------------------------------------------------------------------
# Reading inputs


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as e:
        raise ProbeError(f"cannot read {what} {path}: {e.strerror or e}")
    except ValueError as e:
        raise ProbeError(f"{what} {path} is not JSON: {e}")


def check_expect(expect):
    """Raise ProbeError unless `expect` has the probe.json shape."""
    if not isinstance(expect, dict):
        raise ProbeError("probe.json must be an object")
    if not isinstance(expect.get("skill"), str) or not expect["skill"]:
        raise ProbeError("probe.json needs a non-empty string `skill`")
    if not isinstance(expect.get("fires"), bool):
        raise ProbeError("probe.json needs a boolean `fires`")
    zero = expect.get("zero", {})
    if not isinstance(zero, dict):
        raise ProbeError("probe.json `zero` must be an object")
    for key, value in zero.items():
        if key not in TOOLS:
            raise ProbeError(f"probe.json `zero` has an unknown key {key!r} (known: {', '.join(TOOLS)})")
        if key == "agent":
            if not isinstance(value, bool):
                raise ProbeError("probe.json `zero.agent` must be a boolean")
            continue
        if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
            raise ProbeError(f"probe.json `zero.{key}` must be a list of regex strings")
        for p in value:
            try:
                re.compile(p)
            except re.error as e:
                raise ProbeError(f"probe.json `zero.{key}` has a bad regex {p!r}: {e}")
    return expect


def plugin_meta(plugin_dir):
    meta = read_json(os.path.join(plugin_dir, ".claude-plugin", "plugin.json"), "plugin.json")
    name = meta.get("name") if isinstance(meta, dict) else None
    if not isinstance(name, str) or not name:
        raise ProbeError(f"plugin.json in {plugin_dir} has no `name`")
    return name, meta.get("version")


def read_stream(path):
    """{skills, calls, turns, cost, seconds, error} of one stream-json run file."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        raise ProbeError(f"cannot read run {path}: {e.strerror or e}")
    skills, calls, raw, record = [], [], [], None
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                raw.append(line)
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "result":
                record = event
                continue
            if event.get("type") != "assistant":
                continue
            blocks = (event.get("message") or {}).get("content")
            for b in blocks if isinstance(blocks, list) else []:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                calls.append((b.get("name"), inp))
                if b.get("name") == "Skill":
                    skills.append(str(inp.get("skill", "?")))
    errors = []
    if raw:
        errors.append("non-JSON output: " + " | ".join(raw[:3]))
    run = {"skills": skills, "calls": calls, "turns": None, "cost": None, "seconds": None}
    if record is None:
        errors.append("no result record in the stream")
    else:
        run["turns"] = record.get("num_turns")
        run["cost"] = record.get("total_cost_usd")
        ms = record.get("duration_ms")
        run["seconds"] = ms / 1000 if isinstance(ms, (int, float)) else None
        if record.get("is_error"):
            errors.append(f"result is_error: {record.get('result') or record.get('subtype') or '?'}")
    run["error"] = "; ".join(errors) or None
    return run


# --------------------------------------------------------------------------
# Counting and judging


def count_calls(calls, zero):
    """Counts per tool. Pattern tools map each regex (or `*` for every call) to a count."""
    zero = zero or {}
    counts = {"agent": sum(1 for name, _ in calls if name in AGENT_NAMES)}
    for key, (tool, field) in PATTERN_TOOLS.items():
        values = [str(inp.get(field, "")) for name, inp in calls if name == tool]
        patterns = zero.get(key) or []
        if not patterns:
            counts[key] = {EVERY: len(values)}
        else:
            counts[key] = {p: sum(1 for v in values if re.search(p, v)) for p in patterns}
    return counts


def skill_fired(skills, skill, plugin):
    return any(s in (skill, f"{plugin}:{skill}") for s in skills)


def checked_counts(counts, zero):
    """[(label, count)] of the counts the expectation names, in TOOLS order."""
    out = []
    for key in TOOLS:
        if key not in zero:
            continue
        if key == "agent":
            if zero["agent"]:
                out.append(("agent", counts["agent"]))
            continue
        for pattern, n in counts[key].items():
            out.append((key if pattern == EVERY else f"{key}{{{pattern}}}", n))
    return out


def judge_run(run, expect, plugin):
    """{counts, passed, failures} of one run; passed is None without an expectation."""
    zero = (expect or {}).get("zero") or {}
    counts = count_calls(run["calls"], zero)
    if expect is None:
        return {"counts": counts, "passed": None, "failures": []}
    failures = []
    if run["error"]:
        failures.append(f"error: {run['error']}")
    fired = skill_fired(run["skills"], expect["skill"], plugin)
    if expect["fires"] and not fired:
        failures.append(f"skill {expect['skill']} did not fire")
    if not expect["fires"] and fired:
        failures.append(f"skill {expect['skill']} fired")
    for label, n in checked_counts(counts, zero):
        if n:
            failures.append(f"{label}={n}, want 0")
    return {"counts": counts, "passed": not failures, "failures": failures}


def judge_case(case, model, plugin, version, expect, run_paths):
    runs = []
    for k, path in enumerate(run_paths, 1):
        run = read_stream(path)
        verdict = judge_run(run, expect, plugin)
        runs.append({"run": k, "skills": run["skills"], "counts": verdict["counts"],
                     "turns": run["turns"], "cost": run["cost"], "seconds": run["seconds"],
                     "passed": verdict["passed"], "failures": verdict["failures"],
                     "error": run["error"]})
    passed = None if expect is None else bool(runs) and all(r["passed"] for r in runs)
    cost = round(sum(r["cost"] for r in runs if isinstance(r["cost"], (int, float))), 6)
    return {"case": case, "model": model, "plugin": plugin, "version": version,
            "expect": expect, "runs": runs, "passed": passed, "cost": cost}


# --------------------------------------------------------------------------
# Output


def run_line(case, run, expect):
    zero = (expect or {}).get("zero") or {}
    if expect is None:
        shown = [(key, run["counts"]["agent"] if key == "agent" else sum(run["counts"][key].values()))
                 for key in TOOLS]
        verdict = ""
    else:
        shown = checked_counts(run["counts"], zero)
        verdict = "PASS " if run["passed"] else "FAIL "
    counts = "".join(f" {label}={n}" for label, n in shown)
    turns = "?" if run["turns"] is None else str(run["turns"])
    cost = "?" if run["cost"] is None else f"{run['cost']:.2f}"
    secs = "?s" if run["seconds"] is None else f"{run['seconds']:.0f}s"
    head = (f"{case} run{run['run']}: {verdict}skill=[{', '.join(run['skills'])}]{counts}"
            f" turns={turns} cost=${cost} {secs}")
    lines = [head]
    if expect is None:
        if run["error"]:
            lines.append(f"  error: {run['error']}")
    else:
        lines.extend(f"  {f}" for f in run["failures"])
    return lines


def print_case(result):
    for run in result["runs"]:
        for line in run_line(result["case"], run, result["expect"]):
            print(line)
    if result["passed"] is not None:
        ok = sum(1 for r in result["runs"] if r["passed"])
        word = "PASS" if result["passed"] else "FAIL"
        print(f"{result['case']}: {word} {ok}/{len(result['runs'])} runs, cost ${result['cost']:.2f}")


def write_result(path, result):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("judge", help="judge the runs of one probe case and save the result")
    p.add_argument("--case", required=True, help="the case directory name")
    p.add_argument("--model", required=True, help="the --model value the runs used")
    p.add_argument("--plugin-dir", required=True, help="the plugin under test (reads its plugin.json)")
    p.add_argument("--expect", help="the case's probe.json; without it the runs are only counted")
    p.add_argument("--out", required=True, help="the result file to write")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("runs", nargs="+", help="stream-json run files, in run order")
    p = sub.add_parser("check", help="validate probe.json files")
    p.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    if args.cmd == "check":
        try:
            for f in args.files:
                check_expect(read_json(f, "probe.json"))
        except ProbeError as e:
            print(f"probe: {f}: {e}", file=sys.stderr)
            return EXIT_INPUT
        return 0
    try:
        plugin, version = plugin_meta(args.plugin_dir)
        expect = check_expect(read_json(args.expect, "probe.json")) if args.expect else None
        result = judge_case(args.case, args.model, plugin, version, expect, args.runs)
        write_result(args.out, result)
    except ProbeError as e:
        print(f"probe: {e}", file=sys.stderr)
        return EXIT_INPUT
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_case(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
