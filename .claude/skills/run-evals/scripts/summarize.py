#!/usr/bin/env python3
"""Summarize `claude plugin eval` results, one row per case.

    summarize.py <results-dir-or-aggregate.json>...

A results dir is <plugin>/evals/results/<timestamp>/ (holding aggregate-result.json)
or the results/ root itself (every timestamp dir under it is summarized).

Per results dir: the model (`suite.modelOverride`, or "not recorded") and the mode
("bare" when bare.json is there, else `suite.ablation`). In a bare dir the harness's
`with` arm is the bare arm and is labelled so.

Columns: with score, without score (n/a when the run had no ablation arm), delta,
per-run turns for each arm, and how many with-arm runs invoked the Skill tool.
Skill firing is read from the run's `tool_used: Skill` grader when the case declares
one (a grader with `max: 0` is a not-fired check and is inverted); otherwise from the
run's trace.jsonl when it still exists (--keep-temp); otherwise n/a.

Under each case row: the mean agent cost and time per run of each arm and the case's
judge cost total; the shadow mark from shadow.json ("SHADOWED 1/3 with, 2/3 without",
"shadow: clean", or "shadow: unchecked" with no shadow.json); and the pass rate of each
script grader per arm from script-graders.json (a run whose script did not run counts
as an error).
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


def read_sidecar(results_dir, name):
    path = os.path.join(results_dir, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def arm_label(arm, bare):
    """The display name of a LOGICAL arm of shadow.json / script-graders.json."""
    return "bare" if bare and arm == "without" else arm


def logical_arms(runs, case, bare):
    """[(label, [rows])] of the sidecar rows for `case`, in with/without order."""
    out = []
    for arm in ("with", "without"):
        rows = [r for r in runs if r.get("case") == case and r.get("arm") == arm]
        if rows:
            out.append((arm_label(arm, bare), rows))
    return out


def mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def fmt_arm_cost(label, runs):
    cost = mean(r.get("costUsd") for r in runs)
    secs = mean(r.get("durationSeconds") for r in runs)
    cost_s = "$?" if cost is None else f"${cost:.2f}"
    secs_s = "?s" if secs is None else f"{secs:.0f}s"
    return f"{label} {cost_s}/run {secs_s}/run"


def shadow_mark(shadow, case, bare):
    if shadow is None:
        return "shadow: unchecked"
    arms = logical_arms(shadow.get("runs") or [], case, bare)
    if not arms:
        return "shadow: unchecked"
    hit = [(label, sum(1 for r in rows if r.get("shadowed") is True), len(rows)) for label, rows in arms]
    if any(n for _, n, _ in hit):
        return "SHADOWED " + ", ".join(f"{n}/{total} {label}" for label, n, total in hit if n)
    unchecked = sum(1 for _, rows in arms for r in rows if r.get("shadowed") is None)
    if unchecked == sum(len(rows) for _, rows in arms):
        return "shadow: unchecked"
    return "shadow: clean" + (f" ({unchecked} unchecked)" if unchecked else "")


def script_grader_line(graders, case, bare):
    if graders is None:
        return None
    rows = [r for r in graders.get("runs") or [] if r.get("case") == case]
    names = sorted({r.get("grader") for r in rows if r.get("grader")})
    if not names:
        return None
    parts = []
    for name in names:
        arms = []
        for label, arm_rows in logical_arms([r for r in rows if r.get("grader") == name], case, bare):
            ok = sum(1 for r in arm_rows if r.get("passed") is True)
            errs = sum(1 for r in arm_rows if r.get("passed") is None)
            arms.append(f"{label} {ok}/{len(arm_rows)}" + (f" ({errs} error)" if errs else ""))
        parts.append(f"{name} " + ", ".join(arms))
    return "script graders: " + "; ".join(parts)


def fmt_score(v):
    return "  n/a" if v is None else f"{v:5.2f}"


def fmt_turns(runs):
    if not runs:
        return "-"
    return ",".join("err" if r.get("error") else str(r.get("turns", "?")) for r in runs)


def summarize(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    results_dir = os.path.dirname(os.path.abspath(path))
    bare = os.path.isfile(os.path.join(results_dir, "bare.json"))
    shadow = read_sidecar(results_dir, "shadow.json")
    script_graders = read_sidecar(results_dir, "script-graders.json")
    suite = data.get("suite") or {}
    first = "bare" if bare else "with"
    judge_total = sum(r.get("judgeCostUsd") or 0 for c in data.get("cases") or []
                      for runs in (c.get("arms") or {}).values() for r in runs or [])
    print(f"{path}")
    print(f"  claude {data.get('claudeVersion', '?')}  cost ${data.get('costUsd', 0):.2f}"
          f"  {data.get('durationSeconds', 0):.0f}s  judge ${judge_total:.2f}"
          f"{'  PARTIAL' if data.get('partial') else ''}")
    print(f"  model {suite.get('modelOverride') or 'not recorded'}"
          f"  mode {'bare' if bare else suite.get('ablation') or '?'}")
    print(f"  {'case':<34} {first:>5} {'w/out':>5} {'delta':>6}  {'turns ' + first:<14} {'turns w/out':<14} skill-fired({first})")
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
        name = case.get("name", "?")
        costs = [fmt_arm_cost(first, with_runs)]
        if without_runs:
            costs.append(fmt_arm_cost("without", without_runs))
        judge = sum(r.get("judgeCostUsd") or 0 for r in with_runs + without_runs)
        print(f"      {'  '.join(costs)}  judge ${judge:.2f}")
        print(f"      {shadow_mark(shadow, name, bare)}")
        line = script_grader_line(script_graders, name, bare)
        if line:
            print(f"      {line}")


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
