#!/usr/bin/env python3
"""Compare eval results against the recorded baseline, and record new baselines.

    python3 shipgate/evals/compare.py <results-dir>...          # or the results/ root
    python3 shipgate/evals/compare.py --record <results-dir>...  # update baseline.json

One row per case: with, without, delta, the baseline's values, and the change in delta
(ΔΔ). Rows whose |ΔΔ| exceeds the judge-noise floor (0.10) are flagged — those are the
ones to read before believing a plugin change helped or hurt. The baseline is stamped
with the plugin version from .claude-plugin/plugin.json, so a regression can be tied to
the version that introduced it, and with the harness (`claudeVersion`) and judge model the
run used, so a flagged row recorded under a different harness is marked `~`: that row may
have moved because the model or the judge moved, not because the plugin did. Re-run it on
the unchanged tree before reading the flag as a regression.

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
    """{case: {'with', 'without', 'delta', 'runs', 'dir', 'claude', 'judge'}} — latest dir per case with >= min_runs runs."""
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
        harness = data.get("claudeVersion")
        judge = (data.get("suite") or {}).get("judgeModel")
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
                "claude": harness,
                "judge": judge,
            }
    return out


def load_baseline(path=BASELINE):
    try:
        return json.load(open(path))
    except OSError:
        return {"cases": {}}


def harness_of(row):
    """'claude <ver> / judge <model>' for a result or baseline row; None when neither is recorded."""
    if not row or not (row.get("claude") or row.get("judge")):
        return None
    return f"claude {row.get('claude') or '?'} / judge {row.get('judge') or '?'}"


def fmt(v):
    return "  —  " if v is None else f"{v:+.2f}" if isinstance(v, float) and v < 0 else f"{v:.2f}" if isinstance(v, float) else str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="results dirs, aggregate-result.json files, or the results/ root")
    ap.add_argument("--record", action="store_true", help="write these results into baseline.json (stamped with the plugin version)")
    ap.add_argument("--min-runs", type=int, default=1, help="ignore results with fewer runs per arm (use 3 to record a baseline)")
    ap.add_argument("--noise", type=float, default=NOISE, help=f"|delta change| above which a row is flagged (default {NOISE})")
    ap.add_argument("--baseline", default=BASELINE, help="baseline file to compare against / record into (default: evals/baseline.json)")
    args = ap.parse_args()

    current = load_results(args.paths, args.min_runs)
    if not current:
        print("no aggregate-result.json with aggregates found", file=sys.stderr)
        return 1
    baseline = load_baseline(args.baseline)
    cases = baseline.setdefault("cases", {})

    print(f"{'case':34s} {'with':>5s} {'w/out':>5s} {'Δ':>6s} │ {'base Δ':>6s} {'ΔΔ':>6s}  recorded")
    flagged = 0
    moved = 0
    base_harnesses = {}
    for name in sorted(current):
        cur = current[name]
        base = cases.get(name)
        base_delta = base["delta"] if base else None
        dd = None if base_delta is None else round(cur["delta"] - base_delta, 2)
        flag = " ◀" if dd is not None and abs(dd) > args.noise else ""
        flagged += bool(flag)
        cur_h, base_h = harness_of(cur), harness_of(base)
        drift = "~" if base_h and cur_h and base_h != cur_h else ""
        moved += bool(drift)
        if base:
            base_harnesses[base_h or "unrecorded"] = base_harnesses.get(base_h or "unrecorded", 0) + 1
        recorded = f"{base.get('version', '—')} {base.get('results', '')[:10]}".rstrip() if base else "—"
        print(f"{name:34s} {cur['with']:5.2f} {cur['without']:5.2f} {cur['delta']:+6.2f} │ "
              f"{(f'{base_delta:+6.2f}' if base_delta is not None else '     —'):>6s} "
              f"{(f'{dd:+6.2f}' if dd is not None else '     —'):>6s}  {recorded}{drift}{flag}")
    print(f"\n{len(current)} case(s); {flagged} with |ΔΔ| > {args.noise:.2f}")
    this_h = harness_of(next(iter(current.values())))
    if this_h:
        under = ", ".join(f"{h} ({n})" for h, n in sorted(base_harnesses.items(), key=lambda kv: -kv[1]))
        print(f"harness: this run {this_h}; baseline rows recorded under {under or '—'}")
    if moved:
        print(f"~ {moved} row(s) recorded under a different harness: a flag there may be drift, not the plugin. "
              f"Re-run on the unchanged tree before reading it as a regression.")

    if args.record:
        version = plugin_version()
        for name, cur in current.items():
            row = {"with": cur["with"], "without": cur["without"], "delta": cur["delta"],
                   "runs": cur["runs"], "version": version, "results": cur["dir"]}
            if cur.get("claude"):
                row["claude"] = cur["claude"]
            if cur.get("judge"):
                row["judge"] = cur["judge"]
            cases[name] = row
        baseline["updated"] = max(c["dir"] for c in current.values())[:10]
        json.dump(baseline, open(args.baseline, "w"), indent=2, sort_keys=True)
        print(f"baseline.json updated for {len(current)} case(s) at plugin {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
