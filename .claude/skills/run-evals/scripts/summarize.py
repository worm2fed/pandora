#!/usr/bin/env python3
"""Summarize `claude plugin eval` results, one row per case.

    summarize.py <results-dir-or-aggregate.json>...

A results dir is <plugin>/evals/results/<timestamp>/ (holding aggregate-result.json)
or the results/ root itself (every timestamp dir under it is summarized).

Columns: with score, without score (n/a when the run had no ablation arm), delta,
per-run turns for each arm, and how many with-arm runs invoked the Skill tool.
Skill firing is read from the run's `tool_used: Skill` grader when the case declares
one (a grader with `max: 0` is a not-fired check and is inverted); otherwise from the
run's trace.jsonl when it still exists (--keep-temp); otherwise n/a.
"""
import glob
import json
import os
import sys


def files_for(path):
    if os.path.isfile(path):
        return [path]
    direct = os.path.join(path, "aggregate-result.json")
    if os.path.isfile(direct):
        return [direct]
    nested = sorted(glob.glob(os.path.join(path, "*", "aggregate-result.json")))
    if nested:
        return nested
    sys.exit(f"summarize: no aggregate-result.json under {path}")


def skill_graders(case):
    """{name: fired_means_passed} for the case's `tool_used: Skill` graders."""
    out = {}
    for g in case.get("graders") or []:
        cfg = g.get("config") or {}
        if g.get("type") == "tool_used" and cfg.get("tool") == "Skill":
            out[g["name"]] = cfg.get("max") != 0
    return out


def fired_from_graders(run, graders):
    verdicts = [g for g in run.get("graders") or [] if g.get("name") in graders]
    if not verdicts:
        return None
    return any(g.get("passed") is graders[g["name"]] for g in verdicts)


def fired_from_trace(run):
    path = run.get("tracePath")
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "assistant":
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                    return True
    return False


def fmt_score(v):
    return "  n/a" if v is None else f"{v:5.2f}"


def fmt_turns(runs):
    if not runs:
        return "-"
    return ",".join("err" if r.get("error") else str(r.get("turns", "?")) for r in runs)


def summarize(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    print(f"{path}")
    print(f"  claude {data.get('claudeVersion', '?')}  cost ${data.get('costUsd', 0):.2f}"
          f"  {data.get('durationSeconds', 0):.0f}s{'  PARTIAL' if data.get('partial') else ''}")
    print(f"  {'case':<34} {'with':>5} {'w/out':>5} {'delta':>6}  {'turns with':<14} {'turns w/out':<14} skill-fired(with)")
    for case in data.get("cases") or []:
        agg = case.get("aggregates") or {}
        arms = case.get("arms") or {}
        with_runs, without_runs = arms.get("with") or [], arms.get("without") or []
        graders = skill_graders(case)
        fired, known = 0, 0
        for run in with_runs:
            v = fired_from_graders(run, graders) if graders else None
            if v is None:
                v = fired_from_trace(run)
            if v is not None:
                known += 1
                fired += int(v)
        fired_s = f"{fired}/{known}" if known else "n/a"
        delta = agg.get("delta")
        delta_s = "   n/a" if delta is None else f"{delta:+6.2f}"
        errs = sum(1 for r in with_runs + without_runs if r.get("error"))
        err_s = f"  errors={errs}" if errs else ""
        print(f"  {case.get('name', '?'):<34} {fmt_score(agg.get('score'))} {fmt_score(agg.get('scoreWithout'))} {delta_s}"
              f"  {fmt_turns(with_runs):<14} {fmt_turns(without_runs):<14} {fired_s}{err_s}")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 64
    for arg in argv[1:]:
        for f in files_for(arg):
            summarize(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
