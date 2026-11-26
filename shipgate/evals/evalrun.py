#!/usr/bin/env python3
"""Checks that the run scripts make before and after a harness run (ADR 0035, ADR 0036).

    python3 shipgate/evals/evalrun.py config-check --config-dir DIR --plugin-dir PLUGIN
    python3 shipgate/evals/evalrun.py post-run <results-dir> --plugin-dir PLUGIN [--bare] [--clean]
    python3 shipgate/evals/evalrun.py bare-stub PLUGIN OUT
    python3 shipgate/evals/evalrun.py set-cases <sets.json> <set>

The plugin name and version come from PLUGIN/.claude-plugin/plugin.json.

- `config-check` reads the paying config dir and never writes it. It refuses when
  DIR/plugins/installed_plugins.json holds an install of the plugin in any scope, or when
  DIR/settings.json enables the plugin in `enabledPlugins`. A key matches when its part
  before "@" is the plugin name. A missing file is clean.
- `post-run` reads the results dir's aggregate-result.json and each run's kept trace.
  It writes shadow.json: a run is shadowed when the trace's init record shows that the
  wrong plugin loaded. In a with run, every loaded plugin of the name must be the tree
  under test (same real path, same version or no version), and at least one must load.
  In a without run, or in any run of a bare results dir (--bare), no plugin of the name
  may load. A run with no trace or no init record gets `shadowed: null`.
  Then it runs each case's script graders, PLUGIN/evals/<case>/script-graders/*.py, as
  `python3 <script> <trace>` per run. Exit 0 is a pass. Exit 1 with a line on stdout is
  a fail, whether the script crashed or not: Python flushes stdout at exit, after the
  traceback, so a printed line survives (a hard kill or os._exit loses it). Exit 1 with
  an empty stdout is an error, and so is any other exit, a timeout
  or a missing trace. An error has `passed: null`. The reason of a pass or a fail is the
  first line of stdout. The reason of an error is the last line of stderr, or "exited N"
  when stderr is empty. Advice: print a line on stdout only when the script decides to
  fail, or just before exit 0. The results go into script-graders.json, only when a case
  has a script grader.
  With --bare it writes bare.json first, so a bare dir that has shadow.json always has
  bare.json. With --clean it then removes each run's kept
  sandbox: the directory two levels above a trace path that ends in out/trace.jsonl,
  only when its name starts with "e-" and its parent is a temp root. It leaves anything
  else and says so.
- `bare-stub` writes a stub plugin into OUT: a plugin.json named <name>-bare with the
  version of PLUGIN and no component, and `evals`, a symbolic link to PLUGIN's evals.
- `set-cases` prints the case names of a named set, one per line. It refuses the set
  `parked`, a set that holds a parked case, an empty set, a set that lists a case twice
  and an unknown set. The error for an unknown set lists the sets.

The arm in shadow.json and script-graders.json is the logical arm: "with" means the
plugin should load, "without" means it should not.

post-run never changes the harness status. A shadowed run prints a SHADOWED line on
stderr and still exits 0.

Exit codes:

    0  done (config-check: the config dir is clean)
    1  config-check: the plugin is installed or enabled in the config dir;
       other commands: an input error
    2  usage error, or config-check cannot read its inputs
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

EXIT_INPUT = 1
EXIT_USAGE = 2
SCRIPT_TIMEOUT = 60
TRACE_TAIL = os.path.join("out", "trace.jsonl")


class InputError(Exception):
    """An input the command cannot use."""


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as e:
        raise InputError(f"cannot read {what} {path}: {e.strerror or e}")
    except ValueError as e:
        raise InputError(f"{what} {path} is not JSON: {e}")


def plugin_meta(plugin_dir):
    data = read_json(os.path.join(plugin_dir, ".claude-plugin", "plugin.json"), "plugin manifest")
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        raise InputError(f"the plugin manifest of {plugin_dir} has no name")
    return name, data.get("version")


def key_names(key, name):
    return isinstance(key, str) and key.split("@", 1)[0] == name


# --------------------------------------------------------------------------
# config-check


def config_findings(config_dir, name):
    """Lines that describe each install or enable of `name` in the config dir."""
    found = []
    installed = os.path.join(config_dir, "plugins", "installed_plugins.json")
    if os.path.exists(installed):
        data = read_json(installed, "installed plugins")
        plugins = data.get("plugins") if isinstance(data, dict) else None
        for key, entries in sorted((plugins or {}).items()):
            if not key_names(key, name):
                continue
            if isinstance(entries, dict):
                entries = [entries]
            parts = []
            for e in entries or []:
                e = e if isinstance(e, dict) else {}
                parts.append(f"scope {e.get('scope') or '?'}, version {e.get('version') or '?'}")
            found.append(f"{key} is installed in {installed} ({'; '.join(parts) or 'no entry'})")
    settings = os.path.join(config_dir, "settings.json")
    if os.path.exists(settings):
        data = read_json(settings, "settings")
        enabled = data.get("enabledPlugins") if isinstance(data, dict) else None
        for key, on in sorted((enabled if isinstance(enabled, dict) else {}).items()):
            if key_names(key, name) and on is True:
                found.append(f"{key} is enabled in {settings} (enabledPlugins)")
    return found


def config_check(config_dir, plugin_dir):
    try:
        if not os.path.isdir(config_dir):
            raise InputError(f"config dir does not exist: {config_dir}")
        name, _ = plugin_meta(plugin_dir)
        found = config_findings(config_dir, name)
    except InputError as e:
        print(f"evalrun: config-check: {e}", file=sys.stderr)
        return EXIT_USAGE
    if not found:
        return 0
    print(f"evalrun: config-check: the config dir {config_dir} has a plugin named {name}.", file=sys.stderr)
    print("It can load in place of the tree under test and shadow the run (#49).", file=sys.stderr)
    for line in found:
        print(f"  {line}", file=sys.stderr)
    print("Fix: run with a config dir that has no such plugin (--config-dir DIR or EVAL_CONFIG_DIR),", file=sys.stderr)
    print("or uninstall or disable the plugin in that config dir yourself. This check never changes it.", file=sys.stderr)
    return EXIT_INPUT


# --------------------------------------------------------------------------
# post-run


def init_plugins(trace):
    """The plugin list of the trace's init record, or None when there is no init record."""
    with open(trace, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("type") == "system" and rec.get("subtype") == "init":
                plugins = rec.get("plugins")
                return [p for p in plugins if isinstance(p, dict)] if isinstance(plugins, list) else []
    return None


def same_tree(path, tree):
    return isinstance(path, str) and bool(path) and os.path.realpath(path) == tree


def shadow_row(trace, arm, name, tree, version):
    """(shadowed, reason, loaded) for one run."""
    if not trace or not os.path.isfile(trace):
        return None, "trace gone (the run did not keep it)", []
    try:
        plugins = init_plugins(trace)
    except OSError as e:
        return None, f"cannot read the trace: {e.strerror or e}", []
    if plugins is None:
        return None, "no init record in the trace", []
    mine = [p for p in plugins if p.get("name") == name]
    loaded = [{"path": p.get("path"), "version": p.get("version")} for p in mine]
    if arm == "without":
        if mine:
            where = ", ".join(f"{p['path']} {p['version'] or ''}".strip() for p in loaded)
            return True, f"{name} loaded in a run without it: {where}", loaded
        return False, f"no plugin named {name} loaded", loaded
    if not mine:
        return True, f"no plugin named {name} loaded", loaded
    for p in loaded:
        if not same_tree(p["path"], tree):
            return True, f"{name} loaded from {p['path']}, not from the tree under test", loaded
        if p["version"] is not None and p["version"] != version:
            return True, f"{name} {p['version']} loaded, the tree under test is {version}", loaded
    return False, "the tree under test loaded", loaded


def runs_of(result, bare):
    """(case name, logical arm, 1-based run, run dict) for every run of the result."""
    for case in result.get("cases") or []:
        name = case.get("name") or os.path.basename(case.get("dir") or "")
        for harness_arm, runs in sorted((case.get("arms") or {}).items()):
            arm = "without" if bare or harness_arm == "without" else "with"
            for n, run in enumerate(runs or [], 1):
                yield name, arm, n, run if isinstance(run, dict) else {}


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def last_line(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run_script(script, trace, timeout):
    if not trace or not os.path.isfile(trace):
        return None, "trace gone (the run did not keep it)"
    try:
        p = subprocess.run([sys.executable, script, trace], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s"
    except OSError as e:
        return None, f"cannot run the script: {e.strerror or e}"
    reason = first_line(p.stdout)
    if p.returncode == 0:
        return True, reason
    if p.returncode == 1 and reason:
        return False, reason
    return None, last_line(p.stderr) or f"exited {p.returncode}"


def script_rows(result, plugin_dir, bare, timeout):
    """script-graders.json rows, or None when no case of the result has a script grader."""
    rows, any_script = [], False
    scripts_by_case = {}
    for case, arm, n, run in runs_of(result, bare):
        if case not in scripts_by_case:
            scripts_by_case[case] = sorted(glob.glob(os.path.join(plugin_dir, "evals", case, "script-graders", "*.py")))
        for script in scripts_by_case[case]:
            any_script = True
            passed, reason = run_script(script, run.get("tracePath"), timeout)
            rows.append({"case": case, "arm": arm, "run": n,
                         "grader": os.path.splitext(os.path.basename(script))[0],
                         "passed": passed, "reason": reason})
    return rows if any_script else None


def temp_roots():
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp"}
    if os.environ.get("TMPDIR"):
        roots.add(os.environ["TMPDIR"])
    return {os.path.realpath(r) for r in roots}


def sandbox_of(trace):
    """The kept sandbox dir of a trace path, or None when the path is not a harness sandbox."""
    if not isinstance(trace, str) or not trace.endswith(os.sep + TRACE_TAIL):
        return None
    sandbox = os.path.dirname(os.path.dirname(trace))
    if not os.path.basename(sandbox).startswith("e-"):
        return None
    if os.path.realpath(os.path.dirname(sandbox)) not in temp_roots():
        return None
    return sandbox


def clean(result, bare):
    removed, kept = 0, []
    seen = set()
    for _, _, _, run in runs_of(result, bare):
        trace = run.get("tracePath")
        if not trace or trace in seen:
            continue
        seen.add(trace)
        sandbox = sandbox_of(trace)
        if sandbox is None:
            if os.path.exists(trace):
                kept.append(trace)
            continue
        if os.path.islink(sandbox) or not os.path.isdir(sandbox):
            continue
        shutil.rmtree(sandbox, ignore_errors=True)
        removed += 1
    return removed, kept


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")


def post_run(results_dir, plugin_dir, bare=False, do_clean=False, timeout=SCRIPT_TIMEOUT):
    result = read_json(os.path.join(results_dir, "aggregate-result.json"), "aggregate result")
    name, version = plugin_meta(plugin_dir)
    tree = os.path.realpath(plugin_dir)
    if bare:
        write_json(os.path.join(results_dir, "bare.json"),
                   {"arm": "bare", "plugin": name, "stub": f"{name}-bare", "version": version})
        print("evalrun: bare.json written")
    rows = []
    for case, arm, n, run in runs_of(result, bare):
        shadowed, reason, loaded = shadow_row(run.get("tracePath"), arm, name, tree, version)
        rows.append({"case": case, "arm": arm, "run": n, "shadowed": shadowed, "reason": reason, "loaded": loaded})
        if shadowed:
            print(f"evalrun: SHADOWED {case} {arm} run {n}: {reason}", file=sys.stderr)
    any_shadow = any(r["shadowed"] is True for r in rows)
    write_json(os.path.join(results_dir, "shadow.json"),
               {"plugin": name, "tree": tree, "version": version, "shadowed": any_shadow, "runs": rows})
    unknown = sum(1 for r in rows if r["shadowed"] is None)
    print(f"evalrun: shadow.json: {len(rows)} runs, {sum(1 for r in rows if r['shadowed'])} shadowed, {unknown} not checked (no trace)")
    graded = script_rows(result, plugin_dir, bare, timeout)
    if graded is not None:
        write_json(os.path.join(results_dir, "script-graders.json"), {"runs": graded})
        fails = sum(1 for r in graded if r["passed"] is False)
        errors = sum(1 for r in graded if r["passed"] is None)
        print(f"evalrun: script-graders.json: {len(graded)} results, {fails} failed, {errors} errors")
    if do_clean:
        removed, kept = clean(result, bare)
        print(f"evalrun: removed {removed} kept sandboxes")
        for trace in kept:
            print(f"evalrun: left {trace}: not a harness sandbox under a temp root", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# bare-stub, set-cases


def bare_stub(plugin_dir, out):
    name, version = plugin_meta(plugin_dir)
    evals = os.path.join(plugin_dir, "evals")
    if not os.path.isdir(evals):
        raise InputError(f"the plugin has no evals dir: {evals}")
    if os.path.lexists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise InputError(f"the stub dir exists and is not empty: {out}")
    os.makedirs(os.path.join(out, ".claude-plugin"), exist_ok=True)
    write_json(os.path.join(out, ".claude-plugin", "plugin.json"), {
        "name": f"{name}-bare",
        "version": version,
        "description": f"Empty stub of {name} for a bare eval run (ADR 0035): no skill, agent, hook, command or MCP server.",
    })
    os.symlink(os.path.realpath(evals), os.path.join(out, "evals"))
    print(os.path.abspath(out))
    return 0


PARKED = "parked"


def set_cases(sets_file, name):
    data = read_json(sets_file, "sets file")
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise InputError(f"{sets_file} is not an object of lists")
    if name == PARKED:
        raise InputError(f"the set {PARKED!r} never runs")
    if name not in data:
        raise InputError(f"no set {name!r} in {sets_file}; the sets: {', '.join(sorted(data))}")
    cases = data[name]
    if not cases or not all(isinstance(c, str) and c for c in cases):
        raise InputError(f"the set {name!r} is empty or holds a value that is not a case name")
    twice = sorted({c for c in cases if cases.count(c) > 1})
    if twice:
        raise InputError(f"the set {name!r} lists a case twice: {', '.join(twice)}")
    parked = [c for c in cases if c in (data.get(PARKED) or [])]
    if parked:
        raise InputError(f"the set {name!r} holds a parked case: {', '.join(parked)}")
    return cases


# --------------------------------------------------------------------------
# CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("config-check", help="refuse a same-name plugin in the paying config dir")
    p.add_argument("--config-dir", required=True)
    p.add_argument("--plugin-dir", required=True)
    p = sub.add_parser("post-run", help="shadow check, script graders and clean-up of a results dir")
    p.add_argument("results_dir")
    p.add_argument("--plugin-dir", required=True)
    p.add_argument("--bare", action="store_true", help="the results dir is a bare run (ADR 0035)")
    p.add_argument("--clean", action="store_true", help="remove the kept sandboxes after the checks")
    p.add_argument("--script-timeout", type=int, default=SCRIPT_TIMEOUT, help=f"seconds per script grader (default {SCRIPT_TIMEOUT})")
    p = sub.add_parser("bare-stub", help="build the stub plugin of a bare run")
    p.add_argument("plugin_dir")
    p.add_argument("out")
    p = sub.add_parser("set-cases", help="print the cases of a named set")
    p.add_argument("sets_file")
    p.add_argument("set")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return EXIT_USAGE
    if args.cmd == "config-check":
        return config_check(args.config_dir, args.plugin_dir)
    try:
        if args.cmd == "post-run":
            return post_run(args.results_dir, args.plugin_dir, args.bare, args.clean, args.script_timeout)
        if args.cmd == "bare-stub":
            return bare_stub(args.plugin_dir, args.out)
        if args.cmd == "set-cases":
            print("\n".join(set_cases(args.sets_file, args.set)))
            return 0
    except InputError as e:
        print(f"evalrun: {args.cmd}: {e}", file=sys.stderr)
        return EXIT_INPUT
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
