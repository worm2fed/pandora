#!/usr/bin/env python3
"""Score a `signals.py` blast result against a case's expected.json (ADR 0016).

    python3 shipgate/evals/signal_grader.py score   <blast.json> <expected.json>
    python3 shipgate/evals/signal_grader.py trace   <trace.jsonl> <expected.json>
    python3 shipgate/evals/signal_grader.py fixture <case-dir> --arm graph|regex
    python3 shipgate/evals/signal_grader.py results <results-dir>

Every subcommand takes --json for machine output.

The harness grades the agent's answer. This script grades the signal the agent read:
the `blast` object of `signals.py blast --json` or `signals.py hotspots --blast --json`.

- `blast.files` is scored against the case's importers and tests together.
- `blast.tests` is scored against the case's tests.

For each list: precision = |got & truth| / |got| (1.0 when got is empty or null) and
recall = |got & truth| / |truth| (1.0 when truth is empty). Paths are compared after a
leading `./` is dropped. `blast.truncated: true` means `--limit` cut the list, so the
recall is a lower bound; the output says so.

Sources:

- `score` reads a saved signals.py JSON output.
- `trace` reads a run's trace.jsonl (kept with --keep-temp). It takes the last Bash call
  that runs `signals.py blast ... --json` or `signals.py hotspots --blast ... --json` and
  whose result holds a JSON object with a `blast` key whose `files` is a list. A call
  whose `blast.files` is null, absent or not a list is skipped, and the grader takes the
  call before it.
- `fixture` scaffolds the case's fixture.sh into a fresh temp dir and runs
  `signals.py blast --diff HEAD~1 --json` in `app/`, with `--graph auto` (graph arm) or
  `--graph off` (regex arm). The prompts of cases 13 and 72 ask about "the change at
  HEAD", so the seeds are the files that HEAD changed, as an agent would pass them.
- `results` runs `trace` for every run of every case that has an expected.json, in every
  aggregate-result.json under the dir.

The script adds nothing to the harness score or to baseline.json.

Exit codes:

    0  scored (results: the dir was read)
    1  input error (missing or unreadable file, a failed scaffold or signals run)
    2  usage error
    3  no signals result in the trace
"""
import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNALS = os.path.normpath(os.path.join(HERE, "..", "scripts", "signals.py"))
EXIT_INPUT = 1
EXIT_NO_RESULT = 3
FIXTURE_LIMIT = 100000
LIST_CAP = 10


class GraderError(Exception):
    """An input the grader cannot use; exits with EXIT_INPUT."""


# --------------------------------------------------------------------------
# Metrics


def norm(path):
    path = str(path).strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def metric(got, truth):
    """Precision and recall of one list. `got` may be None (the list was not computed)."""
    got_set = {norm(p) for p in got or []}
    truth_set = {norm(p) for p in truth or []}
    tp = got_set & truth_set
    return {
        "precision": len(tp) / len(got_set) if got_set else 1.0,
        "recall": len(tp) / len(truth_set) if truth_set else 1.0,
        "tp": len(tp),
        "got": None if got is None else len(got_set),
        "truth": len(truth_set),
        "missed": sorted(truth_set - got_set),
        "extra": sorted(got_set - truth_set),
    }


def load_truth(expected):
    importers = expected.get("importers") or []
    tests = expected.get("tests") or []
    return {"files": sorted({norm(p) for p in importers} | {norm(p) for p in tests}),
            "tests": sorted({norm(p) for p in tests})}


def score_payload(payload, expected):
    """Score a signals.py JSON payload (a dict with a `blast` object)."""
    blast = payload.get("blast") if isinstance(payload, dict) else None
    if not isinstance(blast, dict):
        raise GraderError("the signals result has no `blast` object (did the call pass --blast or use `blast`?)")
    truth = load_truth(expected)
    structure = payload.get("structure") if isinstance(payload.get("structure"), dict) else {}
    return {
        "files": metric(blast.get("files"), truth["files"]),
        "tests": metric(blast.get("tests"), truth["tests"]),
        "source": structure.get("source"),
        "truncated": bool(blast.get("truncated")),
        "size": blast.get("size"),
        "tests_reason": blast.get("tests_reason"),
    }


# --------------------------------------------------------------------------
# Reading inputs


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as e:
        raise GraderError(f"cannot read {what} {path}: {e.strerror or e}")
    except ValueError as e:
        raise GraderError(f"{what} {path} is not JSON: {e}")


def blast_objects(text):
    """Every top-level JSON object in `text` that holds a `blast` key, in order.

    A tool result mixes the JSON with other output (stderr advisories, chained commands),
    so the scan tries to decode an object at each line that starts with `{`.
    """
    decoder = json.JSONDecoder()
    found = []
    pos = 0
    while True:
        start = text.find("{", pos)
        if start < 0:
            break
        if start > 0 and text[start - 1] != "\n":
            pos = start + 1
            continue
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        if isinstance(obj, dict) and "blast" in obj:
            found.append(obj)
        pos = end
    return found


_SEGMENT = re.compile(r"&&|\|\||[;|\n]")


def is_signals_blast(command):
    """True when a shell command runs signals.py blast/hotspots --blast with --json."""
    for segment in _SEGMENT.split(command or ""):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        for i, w in enumerate(words):
            if not w.endswith("signals.py"):
                continue
            rest = words[i + 1:]
            if "--json" not in rest:
                continue
            if "blast" in rest or ("hotspots" in rest and "--blast" in rest):
                return True
    return False


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def signals_calls(trace_path):
    """[(command, result text or None)] for each signals blast call in the trace, in order."""
    calls = []
    by_id = {}
    try:
        fh = open(trace_path, encoding="utf-8")
    except OSError as e:
        raise GraderError(f"cannot read trace {trace_path}: {e.strerror or e}")
    with fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("type") not in ("assistant", "user"):
                continue
            blocks = (event.get("message") or {}).get("content")
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") == "Bash":
                    command = (b.get("input") or {}).get("command") or ""
                    if is_signals_blast(command):
                        call = [command, None]
                        calls.append(call)
                        by_id[b.get("id")] = call
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                    by_id[b["tool_use_id"]][1] = result_text(b.get("content"))
    return [tuple(c) for c in calls]


def _has_files_list(obj):
    blast = obj.get("blast")
    return isinstance(blast, dict) and isinstance(blast.get("files"), list)


def score_trace(trace_path, expected):
    """Score the last signals blast result in a trace whose `blast.files` is a list.

    A call whose `blast.files` is null, absent or not a list is skipped. None when no call
    qualifies.
    """
    calls = signals_calls(trace_path)
    for index in range(len(calls) - 1, -1, -1):
        command, text = calls[index]
        objects = [o for o in blast_objects(text or "") if _has_files_list(o)]
        if objects:
            out = score_payload(objects[-1], expected)
            out["command"] = command
            out["calls"] = len(calls)
            out["call"] = index + 1
            return out
    return None


# --------------------------------------------------------------------------
# Fixture arm


def run_fixture(case_dir, arm, limit=FIXTURE_LIMIT):
    """Scaffold the case in a temp dir and return signals.py's blast JSON for the given arm."""
    script = os.path.join(case_dir, "fixture.sh")
    if not os.path.isfile(script):
        raise GraderError(f"no fixture.sh in {case_dir}")
    tmp = tempfile.mkdtemp(prefix="signal-grader-")
    try:
        proc = subprocess.run(["bash", script], cwd=tmp, capture_output=True, text=True, check=False)
        app = os.path.join(tmp, "app")
        if proc.returncode != 0 or not os.path.isdir(app):
            raise GraderError(f"fixture.sh failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
        cmd = [sys.executable, SIGNALS, "blast", "--diff", "HEAD~1", "--json", "--limit", str(limit),
               "--graph", "auto" if arm == "graph" else "off"]
        proc = subprocess.run(cmd, cwd=app, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise GraderError(f"signals.py exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
        objects = blast_objects(proc.stdout)
        if not objects:
            raise GraderError("signals.py printed no JSON with a `blast` object")
        return objects[-1]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Results dir


def aggregate_files(path):
    if os.path.isfile(path):
        return [path]
    direct = os.path.join(path, "aggregate-result.json")
    if os.path.isfile(direct):
        return [direct]
    return sorted(glob.glob(os.path.join(path, "*", "aggregate-result.json")))


def case_dir_for(case, suite_root):
    """The case's directory: the suite root + the case's `dir`, else this evals dir + its name."""
    candidates = []
    if suite_root and case.get("dir"):
        candidates.append(os.path.join(suite_root, case["dir"]))
    name = case.get("name") or os.path.basename(case.get("dir") or "")
    if name:
        candidates.append(os.path.join(HERE, name))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "expected.json")):
            return c
    return None


def results_rows(path):
    rows = []
    for f in aggregate_files(path):
        data = read_json(f, "aggregate result")
        root = (data.get("suite") or {}).get("root")
        for case in data.get("cases") or []:
            cdir = case_dir_for(case, root)
            if not cdir:
                continue
            expected = read_json(os.path.join(cdir, "expected.json"), "expected")
            for arm, runs in sorted((case.get("arms") or {}).items()):
                for n, run in enumerate(runs or [], 1):
                    row = {"case": case.get("name"), "arm": arm, "run": n, "trace": run.get("tracePath")}
                    trace = run.get("tracePath")
                    if not trace or not os.path.isfile(trace):
                        row["note"] = "trace gone (run with --keep-temp)"
                    else:
                        try:
                            scored = score_trace(trace, expected)
                        except GraderError as e:
                            scored, row["note"] = None, str(e)
                        if scored is None:
                            row.setdefault("note", "no signals result in the trace")
                        else:
                            row.update(scored)
                    rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Output


def pr(m):
    return f"{m['precision']:.2f}/{m['recall']:.2f}"


def counts(m):
    got = "null" if m["got"] is None else m["got"]
    return f"tp {m['tp']}, got {got}, truth {m['truth']}"


def print_score(s):
    for key in ("files", "tests"):
        m = s[key]
        print(f"blast.{key:<5}  precision {m['precision']:.2f}  recall {m['recall']:.2f}  ({counts(m)})")
        for label in ("missed", "extra"):
            items = m[label]
            if items:
                more = f" … +{len(items) - LIST_CAP}" if len(items) > LIST_CAP else ""
                print(f"  {label}: {', '.join(items[:LIST_CAP])}{more}")
    print(f"source {s.get('source') or '?'}")
    if s.get("truncated"):
        print(f"truncated: --limit cut blast.files (size {s.get('size')}); its recall is a lower bound")
    if s.get("command"):
        print(f"from signals call {s['call']} of {s['calls']}: {s['command']}")


def print_rows(rows):
    print(f"{'case':<32} {'arm':<8} {'run':>3}  {'files P/R':<9} {'got/truth':<9}  {'tests P/R':<9} {'got/truth':<9}  {'source':<6}  note")
    for r in rows:
        if "files" in r:
            f, t = r["files"], r["tests"]
            ft = f"{f['got'] if f['got'] is not None else 'null'}/{f['truth']}"
            tt = f"{t['got'] if t['got'] is not None else 'null'}/{t['truth']}"
            note = "truncated by --limit" if r.get("truncated") else ""
            print(f"{r['case']:<32} {r['arm']:<8} {r['run']:>3}  {pr(f):<9} {ft:<9}  {pr(t):<9} {tt:<9}  {r.get('source') or '?':<6}  {note}")
        else:
            print(f"{r['case']:<32} {r['arm']:<8} {r['run']:>3}  {'-':<9} {'-':<9}  {'-':<9} {'-':<9}  {'-':<6}  {r.get('note', '')}")
    if not rows:
        print("no run of a case with an expected.json")


def emit(obj, as_json, printer):
    if as_json:
        print(json.dumps(obj, indent=2, sort_keys=True))
    else:
        printer(obj)


# --------------------------------------------------------------------------
# CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("score", help="score a saved signals.py JSON output")
    p.add_argument("blast_json")
    p.add_argument("expected")
    p = sub.add_parser("trace", help="score the last signals blast result in a trace.jsonl")
    p.add_argument("trace")
    p.add_argument("expected")
    p = sub.add_parser("fixture", help="scaffold the case and score signals.py on it")
    p.add_argument("case_dir")
    p.add_argument("--arm", choices=("graph", "regex"), required=True)
    p.add_argument("--limit", type=int, default=FIXTURE_LIMIT, help=f"signals.py --limit (default {FIXTURE_LIMIT})")
    p = sub.add_parser("results", help="score every kept trace of a results dir")
    p.add_argument("results_dir")
    for p in sub.choices.values():
        p.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        if args.cmd == "score":
            s = score_payload(read_json(args.blast_json, "signals result"), read_json(args.expected, "expected"))
            emit(s, args.json, print_score)
        elif args.cmd == "trace":
            expected = read_json(args.expected, "expected")
            s = score_trace(args.trace, expected)
            if s is None:
                if args.json:
                    print(json.dumps({"note": "no signals result in the trace"}))
                else:
                    print("no signals result in the trace")
                return EXIT_NO_RESULT
            emit(s, args.json, print_score)
        elif args.cmd == "fixture":
            expected = read_json(os.path.join(args.case_dir, "expected.json"), "expected")
            payload = run_fixture(args.case_dir, args.arm, args.limit)
            s = score_payload(payload, expected)
            s["arm"] = args.arm
            if args.arm == "graph" and s.get("source") != "graph":
                print(f"signal_grader: graph arm asked, signals.py used {s.get('source')} (is codegraph on PATH?)", file=sys.stderr)
            emit(s, args.json, print_score)
        elif args.cmd == "results":
            if not aggregate_files(args.results_dir):
                raise GraderError(f"no aggregate-result.json under {args.results_dir}")
            emit(results_rows(args.results_dir), args.json, print_rows)
    except GraderError as e:
        print(f"signal_grader: {e}", file=sys.stderr)
        return EXIT_INPUT
    return 0


if __name__ == "__main__":
    sys.exit(main())
