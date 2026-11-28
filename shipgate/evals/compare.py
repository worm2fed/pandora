#!/usr/bin/env python3
"""Compare eval results against the recorded baseline, and record new baselines.

    python3 shipgate/evals/compare.py <results-dir>...          # or the results/ root
    python3 shipgate/evals/compare.py --record <results-dir>...  # update baseline.json
    python3 shipgate/evals/compare.py --against <model> <results-dir>...

baseline.json holds one row per case and model: cases[<case>][<model>] (ADR 0034). The
model is the harness's --model value (suite.modelOverride). Rows written before the model
was recorded sit under the key "unrecorded". A row names its ablation mode, its scoring
rule, the plugin version the run tested (from the result), the harness and judge, the
runs, the results dir, the score per arm, the delta, and the mean cost and time of one run
per arm. Cost excludes the judge; the judge cost has its own field.

One table row per case and model: model, mode, with, without, delta, the baseline value
and the change against it (ΔΔ). A row whose |ΔΔ| exceeds the judge-noise floor (0.10) is
flagged ◀. For a one-arm mode (none or bare) the baseline value and ΔΔ read the score of
that arm. A row recorded under another harness or judge is marked `~`: the row may have
moved because the model or the judge moved. Re-run it on the unchanged tree before you
read the flag as a regression. A row is marked `$` when the with arm costs more than 1.5
times the bare arm per run and |delta| is within the noise floor: the plugin costs more
and changes nothing.

Modes. A with-without result takes its scores from the harness aggregates. An
`--ablation none` result is mode "none": its one arm is the with arm. A results dir with
bare.json is mode "bare": the harness's with arm is the bare arm (ADR 0035). A bare
result and a none result of one case and one model make one row of mode "bare+none".

Scoring rule. Every score uses the both-arm rule. It leaves out a with-only grader: a
grader with config arm "with-only", a tool_used grader for Skill without arm "both", or
a run grader flagged withOnly. A with-without result is already scored by this rule.
Compare scores a none or bare run again from its per-run grader results. A run with no
scoring grader scores 0.

Void batches. A run with an error (a usage limit, an interrupt, a scaffold failure) makes
its case's batch in that results dir void; the dir's other cases still count. A void batch
is never compared and never recorded. In a dir with a recorded model it is never a
refusal; a dir with no recorded model is refused as before. Each one is named in a
"skipped <dir>: void batch of <case> <model>" line with the first error; the line ends in
"(no valid dir: no row)" when no valid dir of that case and model is left, and in
"(valid dir refused: no row)" when the valid dir that is left is refused.

Refusals (exit 3). Compare never crosses a model, a mode or a rule:
- without --against, a result compares only with the row of its own model;
- --against <model> names the row to compare with; another model than the result's is
  refused;
- a row of another mode or rule is refused. With --record the new row replaces it, and
  the output says so.
Compare and --record also refuse a result with no recorded model, and a results dir whose
shadow.json says a run loaded another copy of the plugin (ADR 0036). A results dir with
no shadow.json was never checked for shadowing: compare gives a warning, and --record
refuses it. A dir with no shadow.json or a shadowed run is reported only when compare
would use it for its case and model, alone or in a pair. A dir with no recorded model is
refused unless it is older than the newest pick of its case, any model. A run with no
trace to check gives a warning only, and only when compare uses its dir. Every other dir
with no recorded model, no shadow.json or a shadowed run only counts in one "skipped N
older results dirs" line. --record skips every case and model that has a refusal in the
run, so a refused partner never turns a bare+none row into a half row. The output names
each skipped case and model.

Script graders (FR-015). When a results dir holds script-graders.json, a line under the
case row gives the pass rate of each script grader per arm. A run whose script crashed
(passed null) counts as not passed and as an error. --record stores the rates in the row
under "scripts". A rate lower than the row's rate by more than the noise floor is flagged.

When several results dirs hold the same case and model, the latest (by directory name)
that is not void wins, so a newer void dir never masks an older valid one. Exit codes:
0 ok; 1 no valid results found; 3 one or more refusals.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")
NOISE = 0.10
COST_RATIO = 1.5
RULE = "both-arm"
UNRECORDED = "unrecorded"
REFUSED = 3


def migrate(baseline):
    """Move each flat row (a case whose value holds "delta" or "with") under "unrecorded"."""
    cases = baseline.setdefault("cases", {})
    for name, value in list(cases.items()):
        if isinstance(value, dict) and ("delta" in value or "with" in value):
            cases[name] = {UNRECORDED: dict(value, mode="with-without", rule=RULE)}
    return baseline


def is_with_only(grader):
    config = grader.get("config") or {}
    if config.get("arm") == "with-only":
        return True
    return grader.get("type") == "tool_used" and config.get("tool") == "Skill" and config.get("arm") != "both"


def both_arm_score(run, graders):
    """The run's weighted mean of `passed` over the graders that score in both arms, else 0."""
    with_only = {g.get("name") for g in graders or [] if is_with_only(g)}
    total = got = 0.0
    for g in run.get("graders") or []:
        if g.get("withOnly") or g.get("name") in with_only or g.get("scored") is False:
            continue
        weight = float(g["weight"]) if g.get("weight") is not None else 1.0
        total += weight
        got += weight if g.get("passed") else 0.0
    return got / total if total else 0.0


def mean(values):
    return sum(values) / len(values) if values else None


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def result_files(paths):
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isfile(os.path.join(p, "aggregate-result.json")):
            files.append(os.path.join(p, "aggregate-result.json"))
        else:
            files.extend(sorted(glob.glob(os.path.join(p, "*", "aggregate-result.json"))))
    return sorted(files)


def script_rates(scripts, case):
    """{grader: {arm: [passed, runs, errors]}} for one case of script-graders.json."""
    out = {}
    for r in (scripts or {}).get("runs") or []:
        if r.get("case") != case or r.get("arm") not in ("with", "without"):
            continue
        counts = out.setdefault(r.get("grader") or "?", {}).setdefault(r["arm"], [0, 0, 0])
        counts[0] += r.get("passed") is True
        counts[1] += 1
        counts[2] += r.get("passed") is None
    return out


NO_MODEL = "the model was not recorded (the result has no suite.modelOverride)"
SHADOWED = "shadowed: shadow.json says a run loaded another copy of the plugin"
UNCHECKED = "not checked for shadowing: no shadow.json (run evalrun.py post-run on the dir)"


def load_results(paths, min_runs=1):
    """(entries, no_model, void) for each case per results dir with >= min_runs runs.

    An entry of a dir with no shadow.json or a shadowed run lists (dir, reason) in "flaws".
    An entry of a dir with a run that has no trace to check lists its warning in "notes".
    no_model holds (case, dir) for a dir with no recorded model. void holds (case, model,
    dir, error) for a case whose batch in a dir has a run with an error: it is no entry.
    choose() decides which of them are reported."""
    entries, no_model, void = [], [], []
    for f in result_files(paths):
        data = read_json(f)
        if not isinstance(data, dict):
            continue
        rdir = os.path.dirname(f)
        name = os.path.basename(rdir)
        suite = data.get("suite") or {}
        model = suite.get("modelOverride")
        bare = os.path.isfile(os.path.join(rdir, "bare.json"))
        shadow_file = os.path.join(rdir, "shadow.json")
        checked = os.path.isfile(shadow_file)
        shadow = read_json(shadow_file) or {}
        scripts = read_json(os.path.join(rdir, "script-graders.json"))
        plugins = suite.get("plugins") or [{}]
        shadowed = bool(model) and shadow.get("shadowed") is True
        unchecked = sum(1 for r in shadow.get("runs") or [] if r.get("shadowed") is None)
        notes = [f"warning: {name}: {unchecked} run(s) have no trace to check for shadowing"] if unchecked else []
        for case in data.get("cases", []):
            agg = case.get("aggregates") or {}
            cname = case.get("name")
            arms = case.get("arms") or {}
            with_runs, without_runs = arms.get("with") or [], arms.get("without") or []
            if not cname or "score" not in agg or len(with_runs) < min_runs:
                continue
            if not model:
                no_model.append((cname, name))
                continue
            error = next((str(r["error"]) for r in with_runs + without_runs if r.get("error")), None)
            if error:
                void.append((cname, model, name, " ".join(error.split())[:100]))
                continue
            graders = case.get("graders") or []
            if bare:
                mode, logical = "bare", {"without": with_runs}
                with_, without = None, mean([both_arm_score(r, graders) for r in with_runs])
            elif suite.get("ablation") == "none":
                mode, logical = "none", {"with": with_runs}
                with_, without = mean([both_arm_score(r, graders) for r in with_runs]), None
            else:
                mode, logical = "with-without", {"with": with_runs, "without": without_runs}
                with_ = float(agg["score"])
                without = agg.get("scoreWithout")
                without = float(without) if without is not None else mean([float(r.get("score") or 0) for r in without_runs])
            delta = agg.get("delta") if mode == "with-without" else None
            if delta is None and with_ is not None and without is not None:
                delta = with_ - without
            entries.append({
                "case": cname, "model": model, "mode": mode, "rule": RULE,
                "with": with_, "without": without, "delta": None if delta is None else float(delta),
                "runs": len(with_runs), "dir": name, "newest": name,
                "claude": data.get("claudeVersion"), "judge": suite.get("judgeModel"),
                "version": plugins[0].get("version") or "?",
                "cost": {arm: mean([float(r.get("costUsd") or 0) for r in runs]) for arm, runs in logical.items() if runs},
                "seconds": {arm: mean([float(r.get("durationSeconds") or 0) for r in runs]) for arm, runs in logical.items() if runs},
                "judge_costs": [float(r.get("judgeCostUsd") or 0) for runs in logical.values() for r in runs],
                "scripts": script_rates(scripts, cname),
                "flaws": [(name, SHADOWED)] if shadowed else [] if checked else [(name, UNCHECKED)],
                "notes": notes,
            })
    return entries, no_model, void


def pair(bare, none):
    """One bare+none entry: the with arm from the none result, the without arm from the bare result."""
    scripts = {}
    for src, arm in ((none, "with"), (bare, "without")):
        for grader, arms in src["scripts"].items():
            if arm in arms:
                scripts.setdefault(grader, {})[arm] = arms[arm]
    return dict(
        none, mode="bare+none", without=bare["without"], delta=none["with"] - bare["without"],
        runs=min(none["runs"], bare["runs"]), dir=f"{bare['dir']}+{none['dir']}",
        newest=max(bare["newest"], none["newest"]),
        cost=dict(bare["cost"], **none["cost"]), seconds=dict(bare["seconds"], **none["seconds"]),
        judge_costs=none["judge_costs"] + bare["judge_costs"], scripts=scripts,
        flaws=bare["flaws"] + none["flaws"], notes=bare["notes"] + none["notes"],
    )


def select(entries):
    """{(case, model): entry}: the latest result per mode, a bare and a none result paired, then the latest."""
    by_key = {}
    for e in sorted(entries, key=lambda e: e["dir"]):
        by_key.setdefault((e["case"], e["model"]), {})[e["mode"]] = e
    out = {}
    for key, modes in by_key.items():
        if "bare" in modes and "none" in modes:
            modes["bare+none"] = pair(modes.pop("bare"), modes.pop("none"))
        out[key] = max(modes.values(), key=lambda e: e["newest"])
    return out


def choose(entries, no_model, void, record):
    """(current, refusals, warnings, skipped, voided): the entries compare uses, and what it reports.

    A shadowed dir, a dir with no shadow.json and a dir with no recorded model are reported
    only when compare would use them. When select() picks a shadowed dir, alone or in a
    pair, it is refused. When it picks a dir with no shadow.json, that dir gives a warning,
    or a refusal with --record. A picked dir with a run that has no trace to check gives a
    warning. A dir with no model is refused unless it is older than the newest pick of its
    case, any model. Every other such dir only counts in skipped. Every void batch gets
    its own line in voided, which says when its case and model is left with no row."""
    picked = select(entries)
    current, refusals, warnings = {}, [], {}
    for key, e in picked.items():
        refused = [(d, r) for d, r in e["flaws"] if record or r == SHADOWED]
        if refused:
            refusals += [(key[0], key[1], r, d) for d, r in refused]
            continue
        for d, _ in e["flaws"]:
            warnings[f"warning: {d}: not checked for shadowing (no shadow.json)"] = True
        for note in e["notes"]:
            warnings[note] = True
        current[key] = e
    skipped = {d for e in entries for d, _ in e["flaws"]}
    for case, d in no_model:
        skipped.add(d)
        if not any(k[0] == case and e["newest"] > d for k, e in picked.items()):
            refusals.append((case, None, NO_MODEL, d))
    skipped -= {d for e in picked.values() for d, _ in e["flaws"]} | {r[3] for r in refusals}
    voided = [f"skipped {d}: void batch of {case} {model}, a run has an error: {error}"
              + ("" if (case, model) in current else " (valid dir refused: no row)"
                 if (case, model) in picked else " (no valid dir: no row)")
              for case, model, d, error in sorted(void, key=lambda v: (v[2], v[0]))]
    return current, refusals, list(warnings), len(skipped), voided


def load_baseline(path=BASELINE):
    data = read_json(path)
    return migrate(data if isinstance(data, dict) else {"cases": {}})


def harness_of(row):
    """'claude <ver> / judge <model>' for a result or baseline row; None when neither is recorded."""
    if not row or not (row.get("claude") or row.get("judge")):
        return None
    return f"claude {row.get('claude') or '?'} / judge {row.get('judge') or '?'}"


def score_key(mode):
    """The value that ΔΔ compares: the delta for a two-arm mode, else the score of the one arm."""
    return {"none": "with", "bare": "without"}.get(mode, "delta")


def r2(v):
    return None if v is None else round(v, 2)


def cell(v, width, signed=False):
    if v is None:
        return f"{'—':>{width}s}"
    return f"{v:+{width}.2f}" if signed else f"{v:{width}.2f}"


def rate(counts):
    return round(counts[0] / counts[1], 2) if counts[1] else None


def row_of(cur):
    row = {"model": cur["model"], "mode": cur["mode"], "rule": cur["rule"], "version": cur["version"],
           "runs": cur["runs"], "results": cur["dir"],
           "with": r2(cur["with"]), "without": r2(cur["without"]), "delta": r2(cur["delta"]),
           "cost": {arm: round(v, 4) for arm, v in cur["cost"].items()},
           "seconds": {arm: round(v, 1) for arm, v in cur["seconds"].items()},
           "judge_cost": round(mean(cur["judge_costs"]) or 0.0, 4)}
    for key in ("claude", "judge"):
        if cur.get(key):
            row[key] = cur[key]
    if cur["scripts"]:
        row["scripts"] = {g: {arm: rate(c) for arm, c in arms.items()} for g, arms in cur["scripts"].items()}
    return row


def costly(cur, noise):
    cost, delta = cur["cost"], cur["delta"]
    if "with" not in cost or not cost.get("without") or delta is None:
        return False
    return cost["with"] > COST_RATIO * cost["without"] and abs(round(delta, 2)) <= noise


def script_lines(cur, base, noise):
    """(lines, falls): one line per script grader, with a ◀ for each arm whose rate fell below the row's."""
    lines, falls = [], 0
    base_scripts = (base or {}).get("scripts") or {}
    for grader in sorted(cur["scripts"]):
        parts, marks = [], []
        errors = 0
        for arm in ("with", "without"):
            counts = cur["scripts"][grader].get(arm)
            if not counts:
                continue
            parts.append(f"{arm} {counts[0]}/{counts[1]}")
            errors += counts[2]
            was = (base_scripts.get(grader) or {}).get(arm)
            now = rate(counts)
            if was is not None and now is not None and round(was - now, 2) > noise:
                marks.append(f"{arm} fell {was:.2f}→{now:.2f}")
        falls += len(marks)
        line = f"  script {grader}: {' '.join(parts)}"
        if errors:
            line += f" ({errors} error{'s' if errors > 1 else ''})"
        if marks:
            line += " ◀ " + "; ".join(marks)
        lines.append(line)
    return lines, falls


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="results dirs, aggregate-result.json files, or the results/ root")
    ap.add_argument("--record", action="store_true", help="write these results into baseline.json, one row per case and model")
    ap.add_argument("--min-runs", type=int, default=1, help="ignore results with fewer runs per arm (use 3 to record a baseline)")
    ap.add_argument("--noise", type=float, default=NOISE, help=f"|delta change| above which a row is flagged (default {NOISE})")
    ap.add_argument("--baseline", default=BASELINE, help="baseline file to compare against / record into (default: evals/baseline.json)")
    ap.add_argument("--against", metavar="MODEL", help="the model whose rows to compare with; must be the result's model")
    args = ap.parse_args()

    entries, no_model, void = load_results(args.paths, args.min_runs)
    current, load_refusals, warnings, skipped, voided = choose(entries, no_model, void, args.record)
    refused_keys = {(case, model) for case, model, _, _ in load_refusals}
    if not current and not load_refusals:
        for line in voided:
            print(line)
        print("no valid aggregate-result.json: every batch found is void" if voided
              else "no aggregate-result.json with aggregates found", file=sys.stderr)
        return 1
    baseline = load_baseline(args.baseline)
    cases = baseline.setdefault("cases", {})

    print(f"{'case':34s} {'model':18s} {'mode':12s} {'with':>5s} {'w/out':>5s} {'Δ':>6s} │ "
          f"{'base Δ':>6s} {'ΔΔ':>6s}  recorded")
    flagged = moved = expensive = falls = 0
    refusals = []
    replaced = {}
    recordable = {}
    base_harnesses = {}
    for key in sorted(current):
        name, model = key
        cur = current[key]
        rows = cases.get(name) or {}
        lead = f"{name:34s} {model:18s} {cur['mode']:12s}"
        if args.against and args.against != model:
            refusals.append(f"{lead} refused: result model {model}, --against {args.against}")
            print(refusals[-1])
            continue
        base = rows.get(model)
        if base and (base.get("mode"), base.get("rule")) != (cur["mode"], cur["rule"]):
            if args.record:
                replaced[key] = f"{name} {model}: replaced a {base.get('mode')}/{base.get('rule')} row"
                base = None
            else:
                side = "mode" if base.get("mode") != cur["mode"] else "rule"
                refusals.append(f"{lead} refused: result {side} {cur[side]}, baseline row {side} {base.get(side)}")
                print(refusals[-1])
                continue
        recordable[key] = cur
        sk = score_key(cur["mode"])
        cur_value = cur[sk]
        base_value = base.get(sk) if base else None
        dd = None if base_value is None or cur_value is None else round(round(cur_value, 2) - base_value, 2)
        flag = " ◀" if dd is not None and abs(dd) > args.noise else ""
        flagged += bool(flag)
        cost_mark = " $" if costly(cur, args.noise) else ""
        expensive += bool(cost_mark)
        cur_h, base_h = harness_of(cur), harness_of(base)
        drift = "~" if base_h and cur_h and base_h != cur_h else ""
        moved += bool(drift)
        if base:
            base_harnesses[base_h or "unrecorded"] = base_harnesses.get(base_h or "unrecorded", 0) + 1
            recorded = f"{base.get('version', '—')} {base.get('results', '')[:10]}".rstrip()
        else:
            others = sorted(m for m in rows if m != model)
            recorded = f"— (rows for: {', '.join(others)})" if others else "—"
        print(f"{lead} {cell(r2(cur['with']), 5)} {cell(r2(cur['without']), 5)} {cell(r2(cur['delta']), 6, True)} │ "
              f"{cell(base_value, 6, sk == 'delta')} {cell(dd, 6, True)}  {recorded}{drift}{cost_mark}{flag}")
        lines, fell = script_lines(cur, base, args.noise)
        falls += fell
        for line in lines:
            print(line)
    by_reason = {}
    for name, _, reason, d in load_refusals:
        by_reason.setdefault((name, reason), []).append(d)
    for (name, reason), dirs in sorted(by_reason.items()):
        latest = max(dirs)
        more = f" (and {len(dirs) - 1} older dir(s))" if len(dirs) > 1 else ""
        refusals.append(f"{name:34s} refused: {latest}{more}: {reason}")
        print(refusals[-1])

    print(f"\n{len(recordable)} case(s); {flagged} with |ΔΔ| > {args.noise:.2f}")
    if expensive:
        print(f"$ {expensive} case(s) with the with-arm cost > {COST_RATIO}x the bare arm at |Δ| <= {args.noise:.2f}")
    if falls:
        print(f"◀ {falls} script grader rate(s) fell by more than {args.noise:.2f} against the baseline row")
    if recordable:
        this_h = harness_of(next(iter(recordable.values())))
        if this_h:
            under = ", ".join(f"{h} ({n})" for h, n in sorted(base_harnesses.items(), key=lambda kv: -kv[1]))
            print(f"harness: this run {this_h}; baseline rows recorded under {under or '—'}")
    if moved:
        print(f"~ {moved} row(s) recorded under a different harness: a flag there may be drift, not the plugin. "
              f"Re-run on the unchanged tree before reading it as a regression.")
    for line in warnings:
        print(line)
    for line in voided:
        print(line)
    if skipped:
        print(f"skipped {skipped} older results dirs (no recorded model, no shadow check, or shadowed)")
    if refusals:
        print(f"{len(refusals)} refusal(s): no compare across models, modes or rules, "
              f"no result with no model or a shadowed run, and no record of a run not checked for shadowing")

    if args.record:
        for name, model in sorted(refused_keys, key=lambda k: (k[0], k[1] or "")):
            print(f"not recorded: {name} {model or '(any model)'}: a results dir of it was refused in this run")
        to_record = {k: cur for k, cur in recordable.items()
                     if k not in refused_keys and (k[0], None) not in refused_keys}
        if to_record:
            for (name, model), cur in to_record.items():
                cases.setdefault(name, {})[model] = row_of(cur)
                if (name, model) in replaced:
                    print(replaced[(name, model)])
            baseline["updated"] = max(c["newest"] for c in to_record.values())[:10]
            with open(args.baseline, "w") as fh:
                json.dump(baseline, fh, indent=2, sort_keys=True)
            print(f"baseline.json updated for {len(to_record)} case(s)")
    return REFUSED if refusals else 0


if __name__ == "__main__":
    sys.exit(main())
