#!/usr/bin/env python3
"""Compare eval results against the recorded baseline, and record new baselines.

    python3 shipgate/evals/compare.py <results-dir>...          # or the results/ root
    python3 shipgate/evals/compare.py --record <results-dir>...  # update baseline.json

One row per case: with, without, delta, the baseline's values, and the change in delta
(ΔΔ). Rows whose |ΔΔ| exceeds the judge-noise floor (0.10) are flagged — those are the
ones to read before believing a plugin change helped or hurt. The baseline is stamped
with the plugin version from .claude-plugin/plugin.json, so a regression can be tied to
the version that introduced it.

Scores are taken from each run's `aggregates` (with / without / delta). When several
results dirs hold the same case, the latest (by directory name) wins.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")
NOISE = 0.10


def plugin_version():
    try:
        with open(os.path.join(HERE, "..", ".claude-plugin", "plugin.json")) as fh:
            return json.load(fh).get("version", "?")
    except OSError:
        return "?"


def load_results(paths, min_runs=1):
    """{case: {'with', 'without', 'delta', 'runs', 'dir'}} — latest dir per case with >= min_runs runs."""
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isfile(os.path.join(p, "aggregate-result.json")):
            files.append(os.path.join(p, "aggregate-result.json"))
        else:
            files.extend(sorted(glob.glob(os.path.join(p, "*", "aggregate-result.json"))))
    out = {}
    for f in sorted(files):
        try:
            data = json.load(open(f))
        except (OSError, ValueError):
            continue
        for case in data.get("cases", []):
            agg = case.get("aggregates") or {}
            name = case.get("name")
            if not name or "score" not in agg:
                continue
            runs = len((case.get("arms") or {}).get("with") or [])
            if runs < min_runs:
                continue
            out[name] = {
                "with": round(float(agg.get("score", 0)), 2),
                "without": round(float(agg.get("scoreWithout", 0)), 2),
                "delta": round(float(agg.get("delta", 0)), 2),
                "runs": runs,
                "dir": os.path.basename(os.path.dirname(f)),
            }
    return out


def load_baseline():
    try:
        return json.load(open(BASELINE))
    except OSError:
        return {"cases": {}}


def fmt(v):
    return "  —  " if v is None else f"{v:+.2f}" if isinstance(v, float) and v < 0 else f"{v:.2f}" if isinstance(v, float) else str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="results dirs, aggregate-result.json files, or the results/ root")
    ap.add_argument("--record", action="store_true", help="write these results into baseline.json (stamped with the plugin version)")
    ap.add_argument("--min-runs", type=int, default=1, help="ignore results with fewer runs per arm (use 3 to record a baseline)")
    ap.add_argument("--noise", type=float, default=NOISE, help=f"|delta change| above which a row is flagged (default {NOISE})")
    args = ap.parse_args()

    current = load_results(args.paths, args.min_runs)
    if not current:
        print("no aggregate-result.json with aggregates found", file=sys.stderr)
        return 1
    baseline = load_baseline()
    cases = baseline.setdefault("cases", {})

    print(f"{'case':34s} {'with':>5s} {'w/out':>5s} {'Δ':>6s} │ {'base Δ':>6s} {'ΔΔ':>6s}  version")
    flagged = 0
    for name in sorted(current):
        cur = current[name]
        base = cases.get(name)
        base_delta = base["delta"] if base else None
        dd = None if base_delta is None else round(cur["delta"] - base_delta, 2)
        flag = " ◀" if dd is not None and abs(dd) > args.noise else ""
        flagged += bool(flag)
        print(f"{name:34s} {cur['with']:5.2f} {cur['without']:5.2f} {cur['delta']:+6.2f} │ "
              f"{(f'{base_delta:+6.2f}' if base_delta is not None else '     —'):>6s} "
              f"{(f'{dd:+6.2f}' if dd is not None else '     —'):>6s}  {(base or {}).get('version', '—')}{flag}")
    print(f"\n{len(current)} case(s); {flagged} with |ΔΔ| > {args.noise:.2f}")

    if args.record:
        version = plugin_version()
        for name, cur in current.items():
            cases[name] = {"with": cur["with"], "without": cur["without"], "delta": cur["delta"],
                           "runs": cur["runs"], "version": version, "results": cur["dir"]}
        baseline["updated"] = max(c["dir"] for c in current.values())[:10]
        json.dump(baseline, open(BASELINE, "w"), indent=2, sort_keys=True)
        print(f"baseline.json updated for {len(current)} case(s) at plugin {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
