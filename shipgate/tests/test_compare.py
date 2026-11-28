"""Contract tests for evals/compare.py: baseline rows carry the harness and judge that
produced them, and a row recorded under a different harness is marked so a flagged delta
can be read as drift rather than as a plugin regression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
COMPARE = SHIPGATE / "evals" / "compare.py"


MODEL = "claude-fable-5-2"


def result_dir(root: Path, name: str, *, claude: str, judge: str, with_: float, without: float,
               model: str = MODEL) -> Path:
    d = root / name
    d.mkdir(parents=True)
    runs = [{"score": with_, "passed": with_ >= 1.0, "turns": 1, "costUsd": 0.1}] * 3
    data = {
        "schemaVersion": 1,
        "claudeVersion": claude,
        "suite": {"ablation": "with-without", "judgeModel": judge, "modelOverride": model,
                  "plugins": [{"name": "shipgate", "version": "0.36.0", "path": "/plugin"}]},
        "cases": [{
            "name": "01-case",
            "arms": {"with": runs, "without": runs},
            "aggregates": {"score": with_, "scoreWithout": without, "delta": round(with_ - without, 2)},
        }],
    }
    (d / "aggregate-result.json").write_text(json.dumps(data))
    (d / "shadow.json").write_text(json.dumps(clean_shadow()))
    return d


def clean_shadow(version="0.36.0"):
    """The shadow.json that `evalrun.py post-run` writes for a run with no shadowed run."""
    return {"plugin": "shipgate", "tree": "/plugin", "version": version, "shadowed": False, "runs": []}


def run(score=1.0, *, cost=0.1, secs=60, judge=0.01, graders=None, error=None):
    return {"score": score, "passed": score >= 1.0, "turns": 1, "costUsd": cost, "durationSeconds": secs,
            "judgeCostUsd": judge, "error": error, "tracePath": "", "graders": graders or []}


def grade(name, passed, *, weight=1, scored=True, with_only=False):
    return {"name": name, "passed": passed, "weight": weight, "scored": scored, "withOnly": with_only}


def write_result(root: Path, name: str, cases, *, ablation="with-without", model=MODEL, version="0.36.0",
                 claude="2.1.332", judge="sonnet", bare=False, shadow="clean", scripts=None) -> Path:
    """A results dir: aggregate-result.json plus the sidecar files run-case.sh writes.

    shadow: "clean" writes a clean shadow.json, None writes none, a dict is written as is."""
    d = root / name
    d.mkdir(parents=True)
    suite = {"ablation": ablation, "judgeModel": judge,
             "plugins": [{"name": "shipgate-bare" if bare else "shipgate", "version": version, "path": "/plugin"}]}
    if model:
        suite["modelOverride"] = model
    (d / "aggregate-result.json").write_text(json.dumps(
        {"schemaVersion": 1, "claudeVersion": claude, "suite": suite, "cases": cases}))
    if bare:
        (d / "bare.json").write_text(json.dumps(
            {"arm": "bare", "plugin": "shipgate", "stub": "shipgate-bare", "version": version}))
    if shadow == "clean":
        shadow = clean_shadow(version)
    if shadow is not None:
        (d / "shadow.json").write_text(json.dumps(shadow))
    if scripts is not None:
        (d / "script-graders.json").write_text(json.dumps({"runs": scripts}))
    return d


def ww_case(with_runs, without_runs, *, name="01-case", graders=None):
    """A with-without case; its aggregates are the plain means of run.score, as the harness writes them."""
    w = sum(r["score"] for r in with_runs) / len(with_runs)
    wo = sum(r["score"] for r in without_runs) / len(without_runs)
    return {"name": name, "graders": graders or [], "arms": {"with": with_runs, "without": without_runs},
            "aggregates": {"score": w, "scoreWithout": wo, "delta": round(w - wo, 2)}}


def one_arm_case(runs, *, name="01-case", graders=None):
    """A case of an `--ablation none` run: one `with` arm, no without keys in the aggregates."""
    return {"name": name, "graders": graders or [], "arms": {"with": runs},
            "aggregates": {"score": sum(r["score"] for r in runs) / len(runs), "passRate": 0}}


# Case 01's grader configs: `skill-fired` is with-only by the harness rule (tool_used Skill, no
# arm "both"), `extra` by its arm setting; `answer` and `file` score in both arms.
GRADERS = [
    {"name": "answer", "type": "llm", "weight": 1, "config": {"criteria": "x"}},
    {"name": "file", "type": "regex", "weight": 0.5, "config": {"pattern": "x"}},
    {"name": "skill-fired", "type": "tool_used", "weight": 1, "config": {"tool": "Skill", "input_match": "x"}},
    {"name": "extra", "type": "regex", "weight": 1, "config": {"pattern": "x", "arm": "with-only"}},
]


def none_runs(cost=0.16, secs=90):
    """Three runs that score 0.80, 1.00 and 0 (no grader ran) as the harness counts; 0.67, 1.00, 0 under both-arm.

    The third run carries no error: a run with an error voids its batch (T060)."""
    return [
        run(0.8, cost=cost, secs=secs, graders=[grade("answer", True), grade("file", False, weight=0.5),
                                                grade("skill-fired", True)]),
        run(1.0, cost=cost, secs=secs, graders=[grade("answer", True), grade("file", True, weight=0.5),
                                                grade("skill-fired", True), grade("extra", True)]),
        run(0.0, cost=0, secs=0, judge=0),
    ]


class CompareBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.baseline = self.tmp / "baseline.json"

    def tearDown(self):
        for p in sorted(self.tmp.rglob("*"), reverse=True):
            p.rmdir() if p.is_dir() else p.unlink()
        self.tmp.rmdir()

    def run_compare(self, *args):
        return subprocess.run(
            [sys.executable, str(COMPARE), "--baseline", str(self.baseline), *map(str, args)],
            capture_output=True, text=True, check=False,
        )

    def compare(self, *args):
        proc = self.run_compare(*args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def refused(self, *args):
        proc = self.run_compare(*args)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        return proc.stdout + proc.stderr

    def rows(self):
        return json.loads(self.baseline.read_text())["cases"]

    def row_cells(self, out):
        """(with, without, Δ, base Δ, ΔΔ, rest) of the 01-case row: the three cells left of │ and two right of it."""
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        left, right = row.split("│")
        lt, rt = left.split(), right.split()
        return lt[-3], lt[-2], lt[-1], rt[0], rt[1], row



class CompareTestCase(CompareBase):
    """Today's table: with, without, Δ, base Δ, ΔΔ, the ◀ flag and the ~ drift mark."""

    def test_a_delta_change_within_the_noise_floor_is_printed_and_not_flagged(self):
        old = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", old)
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.45)
        out = self.compare(new)
        w, wo, d, bd, dd, row = self.row_cells(out)
        self.assertEqual((w, wo, d, bd, dd), ("1.00", "0.45", "+0.55", "+0.50", "+0.05"), row)
        self.assertNotIn("◀", row)
        self.assertIn("1 case(s); 0 with |ΔΔ| > 0.10", out)

    def test_a_delta_change_of_exactly_the_noise_floor_is_not_flagged(self):
        old = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", old)
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.4)
        out = self.compare(new)
        *_, dd, row = self.row_cells(out)
        self.assertEqual(dd, "+0.10", row)
        self.assertNotIn("◀", row)

    def test_a_delta_change_above_the_noise_floor_is_flagged(self):
        old = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", old)
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=0.8, without=0.5)
        out = self.compare(new)
        w, wo, d, bd, dd, row = self.row_cells(out)
        self.assertEqual((w, wo, d, bd, dd), ("0.80", "0.50", "+0.30", "+0.50", "-0.20"), row)
        self.assertTrue(row.endswith("◀"), row)
        self.assertNotIn("~", row)
        self.assertIn("1 case(s); 1 with |ΔΔ| > 0.10", out)

    def test_record_stamps_the_harness_and_judge(self):
        d = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.280", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", d)
        row = json.loads(self.baseline.read_text())["cases"]["01-case"][MODEL]
        self.assertEqual(row["claude"], "2.1.280")
        self.assertEqual(row["judge"], "sonnet")
        self.assertEqual((row["with"], row["without"], row["delta"], row["runs"]), (1.0, 0.5, 0.5, 3))
        self.assertEqual(row["results"], "2026-10-06T10-00-00-000Z")

    def test_a_row_recorded_under_another_harness_is_marked(self):
        old = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.280", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", old)
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.8)
        out = self.compare(new)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertIn("2026-10-06~", row, row)
        self.assertIn("◀", row, row)
        self.assertIn("recorded under claude 2.1.280 / judge sonnet (1)", out)
        self.assertIn("1 row(s) recorded under a different harness", out)

    def test_a_row_recorded_under_the_same_harness_is_not_marked(self):
        old = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", old)
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.8)
        out = self.compare(new)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertNotIn("~", row, row)
        self.assertNotIn("different harness", out)

    def test_a_baseline_without_a_harness_is_not_marked(self):
        self.baseline.write_text(json.dumps({"cases": {"01-case": {MODEL: {
            "mode": "with-without", "rule": "both-arm",
            "with": 1.0, "without": 0.5, "delta": 0.5, "runs": 3, "version": "0.14.1", "results": "2026-10-06T10-00-00-000Z"}}}}))
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.8)
        out = self.compare(new)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertNotIn("~", row, row)
        self.assertIn("recorded under unrecorded (1)", out)



def flat_baseline(path: Path, **extra):
    row = {"with": 1.0, "without": 0.5, "delta": 0.5, "runs": 3, "version": "0.15.0",
           "results": "2026-10-06T10-00-00-000Z", "claude": "2.1.296", "judge": "sonnet"}
    row.update(extra)
    path.write_text(json.dumps({"cases": {"01-case": row}, "note": "n", "updated": "2026-10-06"}))
    return row


class BaselineRowTest(CompareBase):
    """ADR 0034: a row per case and model that names its mode and rule, with cost and time per arm."""

    def test_record_writes_a_row_under_the_case_and_the_model(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case(
            [run(1.0, cost=0.2, secs=100, judge=0.02), run(0.5, cost=0.4, secs=200, judge=0.04)],
            [run(0.5, cost=0.1, secs=50, judge=0.01), run(0.5, cost=0.1, secs=70, judge=0.01)])])
        self.compare("--record", d)
        self.assertEqual(self.rows()["01-case"][MODEL], {
            "model": MODEL, "mode": "with-without", "rule": "both-arm", "version": "0.36.0",
            "claude": "2.1.332", "judge": "sonnet", "runs": 2, "results": "2026-11-25T10-00-00-000Z",
            "with": 0.75, "without": 0.5, "delta": 0.25,
            "cost": {"with": 0.3, "without": 0.1}, "seconds": {"with": 150, "without": 60},
            "judge_cost": 0.02,
        })

    def test_the_recorded_version_is_the_tested_version_from_the_result(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run()])], version="0.9.1")
        self.compare("--record", d)
        self.assertEqual(self.rows()["01-case"][MODEL]["version"], "0.9.1")

    def test_record_keeps_the_rows_of_other_models(self):
        old = flat_baseline(self.baseline)
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run()])])
        self.compare("--record", d)
        rows = self.rows()["01-case"]
        self.assertEqual(sorted(rows), [MODEL, "unrecorded"])
        self.assertEqual(rows["unrecorded"], dict(old, mode="with-without", rule="both-arm"))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(COMPARE.parent))
        import compare
        self.compare = compare

    def tearDown(self):
        sys.path.remove(str(COMPARE.parent))

    def test_a_flat_row_moves_under_unrecorded_with_mode_and_rule_and_no_model(self):
        flat = {"with": 1.0, "without": 0.5, "delta": 0.5, "runs": 3, "version": "0.15.0"}
        base = {"cases": {"01-case": dict(flat)}, "note": "n", "updated": "u"}
        out = self.compare.migrate(base)
        self.assertEqual(out, {"cases": {"01-case": {"unrecorded": dict(flat, mode="with-without", rule="both-arm")}},
                               "note": "n", "updated": "u"})
        self.assertNotIn("model", out["cases"]["01-case"]["unrecorded"])

    def test_the_migration_is_idempotent(self):
        base = {"cases": {"01-case": {"with": 1.0, "delta": 0.5}, "02-case": {MODEL: {"with": 1.0, "delta": 0.0}}}}
        once = self.compare.migrate(json.loads(json.dumps(base)))
        self.assertEqual(self.compare.migrate(json.loads(json.dumps(once))), once)
        self.assertEqual(once["cases"]["02-case"], base["cases"]["02-case"])

    def test_the_both_arm_score_reads_the_with_only_rule_from_the_grader_configs(self):
        runs = none_runs()
        scores = [self.compare.both_arm_score(r, GRADERS) for r in runs]
        self.assertEqual([round(x, 2) for x in scores], [0.67, 1.0, 0.0])

    def test_an_errored_run_scores_from_its_graders_as_the_harness_does(self):
        r = run(0.5, error="max turns", graders=[grade("answer", True), grade("file", False)])
        self.assertEqual(self.compare.both_arm_score(r, GRADERS), 0.5)

    def test_an_errored_run_with_no_scoring_grader_scores_0(self):
        r = run(0.0, error="boom", graders=[grade("skill-fired", True)])
        self.assertEqual(self.compare.both_arm_score(r, GRADERS), 0.0)

    def test_a_run_grader_flagged_with_only_is_left_out(self):
        r = run(graders=[grade("answer", True), grade("other", False, with_only=True)])
        self.assertEqual(self.compare.both_arm_score(r, GRADERS), 1.0)

    def test_a_skill_grader_with_arm_both_scores_in_both_arms(self):
        graders = [{"name": "skill-fired", "type": "tool_used", "config": {"tool": "Skill", "arm": "both"}}]
        r = run(graders=[grade("answer", True), grade("skill-fired", False)])
        self.assertEqual(self.compare.both_arm_score(r, graders), 0.5)


class RefusalTest(CompareBase):
    """SC-002: no compare across models, modes or rules; FR-006 / SC-005: no model-less or shadowed run."""

    def write_row(self, **row):
        full = {"model": MODEL, "mode": "with-without", "rule": "both-arm", "with": 1.0, "without": 0.5,
                "delta": 0.5, "runs": 3, "version": "0.36.0", "results": "2026-11-20T10-00-00-000Z"}
        full.update(row)
        self.baseline.write_text(json.dumps({"cases": {"01-case": {MODEL: full}}}))

    def bare_and_none(self):
        bare = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(cost=0.1), graders=GRADERS)],
                            ablation="none", bare=True)
        none = write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                            ablation="none")
        return bare, none

    def test_a_mode_mismatch_is_refused_naming_both_modes(self):
        self.write_row(mode="with-without")
        out = self.refused(*self.bare_and_none())
        self.assertRegex(out, r"refused.*bare\+none.*with-without")

    def test_a_rule_mismatch_is_refused_naming_both_rules(self):
        self.write_row(rule="all")
        out = self.refused(write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])]))
        self.assertRegex(out, r"refused.*both-arm.*all")

    def test_against_another_model_is_refused_naming_both_models(self):
        flat_baseline(self.baseline)
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        out = self.refused("--against", "unrecorded", d)
        self.assertRegex(out, rf"refused.*{MODEL}.*unrecorded")

    def test_against_the_result_model_compares(self):
        self.write_row()
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        w, wo, d_, bd, dd, row = self.row_cells(self.compare("--against", MODEL, d))
        self.assertEqual((bd, dd), ("+0.50", "+0.00"), row)

    def test_a_missing_row_for_the_model_prints_a_dash_and_names_the_models_with_rows(self):
        flat_baseline(self.baseline)
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        out = self.compare(d)
        w, wo, d_, bd, dd, row = self.row_cells(out)
        self.assertEqual((bd, dd), ("—", "—"), row)
        self.assertIn("unrecorded", row)
        self.assertNotIn("refused", out)

    def test_record_replaces_a_row_of_another_mode_and_rule(self):
        self.write_row(mode="none", rule="all")
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        out = self.compare("--record", d)
        self.assertIn("replaced a none/all row", out)
        row = self.rows()["01-case"][MODEL]
        self.assertEqual((row["mode"], row["rule"], row["delta"]), ("with-without", "both-arm", 0.5))

    def test_a_result_with_no_model_is_refused_by_compare(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None)
        self.assertIn("model was not recorded", self.refused(d))

    def test_a_result_with_no_model_is_refused_by_record(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None)
        self.assertIn("model was not recorded", self.refused("--record", d))
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def shadowed(self, flag):
        shadow = {"plugin": "shipgate", "tree": "/plugin", "version": "0.36.0", "shadowed": flag,
                  "runs": [{"case": "01-case", "arm": "without", "run": 1, "shadowed": flag,
                            "reason": "r", "loaded": []}]}
        return write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])], shadow=shadow)

    def test_a_shadowed_result_is_shown_as_refused(self):
        out = self.refused(self.shadowed(True))
        self.assertRegex(out, r"refused.*shadowed")

    def test_a_shadowed_result_is_not_recorded(self):
        out = self.refused("--record", self.shadowed(True))
        self.assertIn("shadowed", out)
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def unchecked(self, **kw):
        return write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.5)])], shadow=None, **kw)

    def test_a_result_with_no_shadow_json_is_compared_with_a_warning(self):
        out = self.compare(self.unchecked())
        self.assertIn("warning: 2026-11-25T10-00-00-000Z: not checked for shadowing (no shadow.json)", out)
        self.assertNotIn("refused", out)

    def test_a_result_with_no_shadow_json_is_not_recorded(self):
        out = self.refused("--record", self.unchecked())
        self.assertRegex(out, r"01-case.*refused.*not checked for shadowing")
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def test_a_bare_result_with_no_shadow_json_is_not_recorded(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                         ablation="none", bare=True, shadow=None)
        self.assertIn("not checked for shadowing", self.refused("--record", d))
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def test_a_run_with_no_trace_to_check_only_warns(self):
        out = self.compare("--record", self.shadowed(None))
        self.assertIn("warning", out)
        self.assertIn(MODEL, self.rows()["01-case"])


class PartnerRefusalTest(CompareBase):
    """R2-2: --record skips a (case, model) with any refusal in the run, so a paired row never turns half."""

    def test_a_refused_partner_keeps_the_paired_row(self):
        partners = {
            "no shadow.json": None,
            "shadowed": {"plugin": "shipgate", "tree": "/plugin", "version": "0.36.0", "shadowed": True,
                         "runs": [{"case": "01-case", "arm": "with", "run": 1, "shadowed": True,
                                   "reason": "r", "loaded": []}]},
        }
        for what, shadow in partners.items():
            with self.subTest(what):
                root = self.tmp / what.replace(" ", "-")
                bare = write_result(root, "2026-11-20T10-00-00-000Z", [one_arm_case(none_runs(cost=0.1), graders=GRADERS)],
                                    ablation="none", bare=True)
                none = write_result(root, "2026-11-20T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                                    ablation="none")
                self.compare("--record", bare, none)
                before = self.rows()["01-case"][MODEL]
                self.assertEqual(before["mode"], "bare+none")
                new_bare = write_result(root, "2026-11-25T10-00-00-000Z", [one_arm_case(
                    [run(1.0, graders=[grade("answer", True)])] * 3, graders=GRADERS)], ablation="none", bare=True)
                new_none = write_result(root, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                                        ablation="none", shadow=shadow)
                out = self.refused("--record", new_bare, new_none)
                self.assertEqual(self.rows()["01-case"][MODEL], before)
                self.assertNotIn("replaced", out)
                self.assertIn(f"not recorded: 01-case {MODEL}: a results dir of it was refused in this run", out)
                self.baseline.unlink()

    def test_a_newer_partner_with_no_model_keeps_the_paired_row(self):
        bare = write_result(self.tmp, "2026-11-20T10-00-00-000Z", [one_arm_case(none_runs(cost=0.1), graders=GRADERS)],
                            ablation="none", bare=True)
        none = write_result(self.tmp, "2026-11-20T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                            ablation="none")
        self.compare("--record", bare, none)
        before = self.rows()["01-case"][MODEL]
        self.assertEqual(before["mode"], "bare+none")
        new_bare = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(
            [run(1.0, graders=[grade("answer", True)])] * 3, graders=GRADERS)], ablation="none", bare=True)
        new_none = write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                                ablation="none", model=None)
        out = self.refused("--record", new_bare, new_none)
        self.assertEqual(self.rows()["01-case"][MODEL], before)
        self.assertNotIn("replaced", out)
        self.assertIn("model was not recorded", out)
        self.assertIn("not recorded: 01-case (any model): a results dir of it was refused in this run", out)
        self.assertNotIn("baseline.json updated", out)


class OldDirsTest(CompareBase):
    """R2-14: a dir with no recorded model or no shadow.json is reported only when compare would use it."""

    def old_dirs(self):
        write_result(self.tmp, "2026-10-01T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None, shadow=None)
        write_result(self.tmp, "2026-10-02T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None, shadow=None)
        write_result(self.tmp, "2026-11-01T10-00-00-000Z", [ww_case([run()], [run(0.5)])], shadow=None)

    def test_older_dirs_beside_a_newer_accepted_result_are_counted(self):
        self.old_dirs()
        write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.25)])])
        for args in ((), ("--record",)):
            with self.subTest(args=args):
                out = self.compare(*args, self.tmp)
                self.assertNotIn("refused", out)
                self.assertNotIn("warning", out)
                self.assertEqual(out.count("skipped 3 older results dirs (no recorded model, no shadow check, or shadowed)"), 1, out)
        self.assertEqual(self.rows()["01-case"][MODEL]["results"], "2026-11-25T10-00-00-000Z")

    def test_a_dir_that_compare_would_use_is_reported(self):
        self.old_dirs()
        out = self.compare(self.tmp)
        self.assertIn("warning: 2026-11-01T10-00-00-000Z: not checked for shadowing (no shadow.json)", out)
        self.assertIn("skipped 2 older results dirs", out)
        out = self.refused("--record", self.tmp)
        self.assertRegex(out, r"01-case.*refused: 2026-11-01T10-00-00-000Z: not checked for shadowing")
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def shadowed_dir(self, name):
        shadow = {"plugin": "shipgate", "tree": "/plugin", "version": "0.36.0", "shadowed": True,
                  "runs": [{"case": "01-case", "arm": "without", "run": 1, "shadowed": True, "reason": "r", "loaded": []}]}
        return write_result(self.tmp, name, [ww_case([run()], [run(0.5)])], shadow=shadow)

    def test_an_older_shadowed_dir_beside_a_newer_clean_dir_is_counted(self):
        self.shadowed_dir("2026-11-20T10-00-00-000Z")
        write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.25)])])
        out = self.compare("--record", self.tmp)
        self.assertNotIn("refused", out)
        self.assertIn("skipped 1 older results dirs (no recorded model, no shadow check, or shadowed)", out)
        self.assertEqual(self.rows()["01-case"][MODEL]["results"], "2026-11-25T10-00-00-000Z")

    def test_a_shadowed_dir_that_is_the_newest_is_refused(self):
        write_result(self.tmp, "2026-11-20T10-00-00-000Z", [ww_case([run()], [run(0.25)])])
        self.shadowed_dir("2026-11-25T10-00-00-000Z")
        for args in ((), ("--record",)):
            with self.subTest(args=args):
                out = self.refused(*args, self.tmp)
                self.assertRegex(out, r"01-case.*refused: 2026-11-25T10-00-00-000Z: shadowed")
        self.assertFalse(self.baseline.exists() and self.rows().get("01-case"))

    def no_trace_dir(self, name):
        shadow = {"plugin": "shipgate", "tree": "/plugin", "version": "0.36.0", "shadowed": False,
                  "runs": [{"case": "01-case", "arm": "with", "run": 1, "shadowed": None, "reason": "trace gone",
                            "loaded": []}]}
        return write_result(self.tmp, name, [ww_case([run()], [run(0.5)])], shadow=shadow)

    def test_an_older_dir_with_no_trace_beside_a_newer_clean_dir_gives_no_warning(self):
        self.no_trace_dir("2026-11-20T10-00-00-000Z")
        write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case([run()], [run(0.25)])])
        out = self.compare(self.tmp)
        self.assertNotIn("no trace to check", out)
        self.assertNotIn("warning", out)

    def test_a_dir_with_no_trace_that_compare_uses_gives_the_warning(self):
        self.no_trace_dir("2026-11-20T10-00-00-000Z")
        out = self.compare(self.tmp)
        self.assertEqual(out.count("warning: 2026-11-20T10-00-00-000Z: 1 run(s) have no trace to check for shadowing"),
                         1, out)

    def test_only_dirs_with_no_model_exit_3(self):
        write_result(self.tmp, "2026-10-01T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None, shadow=None)
        write_result(self.tmp, "2026-10-02T10-00-00-000Z", [ww_case([run()], [run(0.5)])], model=None, shadow=None)
        out = self.refused(self.tmp)
        self.assertIn("refused: 2026-10-02T10-00-00-000Z (and 1 older dir(s)): the model was not recorded", out)
        self.assertNotIn("skipped", out)


LIMIT = "exit 1: You've hit your 5-hour limit"


class VoidBatchTest(CompareBase):
    """T060: a run with an error voids its case's batch in that dir; the newest valid dir per case and model counts."""

    def void_dir(self, name, *, model=MODEL, case="01-case"):
        return write_result(self.tmp, name, [ww_case([run(), run(0.0, cost=0, error=LIMIT)], [run(0.0)] * 2, name=case)],
                            model=model)

    def test_a_newer_void_dir_is_skipped_and_named_and_the_older_valid_dir_is_used(self):
        write_result(self.tmp, "2026-11-20T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        self.void_dir("2026-11-25T10-00-00-000Z")
        out = self.compare(self.tmp)
        w, wo, d, *_, row = self.row_cells(out)
        self.assertEqual((w, wo, d), ("1.00", "0.50", "+0.50"), row)
        self.assertEqual(out.count("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case "
                                   f"{MODEL}, a run has an error: {LIMIT}"), 1, out)
        self.assertNotIn("no valid dir", out)
        self.assertNotIn("refused", out)

    def test_record_never_writes_a_void_batch_and_records_the_older_valid_dir(self):
        write_result(self.tmp, "2026-11-20T10-00-00-000Z", [ww_case([run()], [run(0.5)])])
        self.void_dir("2026-11-25T10-00-00-000Z")
        out = self.compare("--record", self.tmp)
        self.assertIn("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case", out)
        rec = self.rows()["01-case"][MODEL]
        self.assertEqual((rec["results"], rec["without"], rec["delta"]), ("2026-11-20T10-00-00-000Z", 0.5, 0.5))

    def test_a_case_and_model_with_only_a_void_dir_has_no_row_and_the_skip_says_why(self):
        self.void_dir("2026-11-25T10-00-00-000Z")
        write_result(self.tmp, "2026-11-25T11-00-00-000Z", [ww_case([run()], [run(0.5)])], model="other-model")
        for args in ((), ("--record",)):
            with self.subTest(args=args):
                out = self.compare(*args, self.tmp)
                rows = [line for line in out.splitlines() if line.startswith("01-case")]
                self.assertEqual(len(rows), 1, out)
                self.assertIn("other-model", rows[0])
                self.assertIn("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case "
                              f"{MODEL}, a run has an error: {LIMIT} (no valid dir: no row)", out)
        self.assertEqual(list(self.rows()["01-case"]), ["other-model"])

    def test_a_void_line_says_when_the_older_valid_dir_is_refused(self):
        write_result(self.tmp, "2026-11-20T10-00-00-000Z", [ww_case([run()], [run(0.5)])], shadow=None)
        self.void_dir("2026-11-25T10-00-00-000Z")
        proc = self.run_compare("--record", self.tmp)
        self.assertIn("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case "
                      f"{MODEL}, a run has an error: {LIMIT} (valid dir refused: no row)", proc.stdout)
        self.assertNotIn("no valid dir", proc.stdout)

    def test_only_void_dirs_name_each_and_exit_1(self):
        self.void_dir("2026-11-24T10-00-00-000Z")
        self.void_dir("2026-11-25T10-00-00-000Z")
        proc = self.run_compare("--record", self.tmp)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        for d in ("2026-11-24T10-00-00-000Z", "2026-11-25T10-00-00-000Z"):
            self.assertIn(f"skipped {d}: void batch of 01-case", proc.stdout)
        self.assertFalse(self.baseline.exists())

    def test_a_void_case_leaves_the_other_cases_of_its_dir_valid(self):
        write_result(self.tmp, "2026-11-25T10-00-00-000Z", [
            ww_case([run(), run(0.0, error=LIMIT)], [run(0.5)] * 2),
            ww_case([run()], [run(0.5)], name="02-case"),
        ])
        out = self.compare("--record", self.tmp)
        self.assertIn("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case", out)
        self.assertNotIn("void batch of 02-case", out)
        self.assertEqual(sorted(self.rows()), ["02-case"])

    def test_a_void_newest_bare_dir_pairs_the_older_valid_bare_dir(self):
        bare_runs = [run(0.5, cost=0.1, secs=40, graders=[grade("answer", False), grade("file", True, weight=0.5)])] * 3
        write_result(self.tmp, "2026-11-20T10-00-00-000Z", [one_arm_case(bare_runs, graders=GRADERS)],
                     ablation="none", bare=True)
        write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(
            bare_runs[:2] + [run(0.0, cost=0, secs=0, judge=0, error=LIMIT)], graders=GRADERS)],
            ablation="none", bare=True)
        write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                     ablation="none")
        out = self.compare("--record", self.tmp)
        self.assertIn("skipped 2026-11-25T10-00-00-000Z: void batch of 01-case", out)
        rec = self.rows()["01-case"][MODEL]
        self.assertEqual((rec["mode"], rec["with"], rec["without"], rec["results"]),
                         ("bare+none", 0.56, 0.33, "2026-11-20T10-00-00-000Z+2026-11-25T11-00-00-000Z"))


class EfficiencyTest(CompareBase):
    """SC-003: flag a with arm above 1.5x the bare-arm cost when |Δ| is within the noise floor."""

    def flag_for(self, ratio, delta):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [ww_case(
            [run(1.0, cost=0.1 * ratio)] * 3, [run(round(1.0 - delta, 2), cost=0.1)] * 3)])
        out = self.compare(d)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        return "$" in row, out

    def test_a_ratio_of_1_6_at_delta_0_05_is_flagged(self):
        flagged, out = self.flag_for(1.6, 0.05)
        self.assertTrue(flagged, out)
        self.assertIn("1 case(s) with the with-arm cost > 1.5x the bare arm", out)

    def test_a_ratio_of_1_4_is_not_flagged(self):
        flagged, out = self.flag_for(1.4, 0.05)
        self.assertFalse(flagged, out)

    def test_a_ratio_of_1_6_at_delta_0_20_is_not_flagged(self):
        flagged, out = self.flag_for(1.6, 0.20)
        self.assertFalse(flagged, out)


class BothArmRuleTest(CompareBase):
    """FR-007: a `none` or `bare` result is scored from its per-run graders under the both-arm rule."""

    def test_a_none_result_shows_the_both_arm_score_not_the_harness_score(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                         ablation="none")
        out = self.compare("--record", d)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertIn(" none ", row)
        self.assertIn("0.56", row)
        self.assertNotIn("0.60", row)
        rec = self.rows()["01-case"][MODEL]
        self.assertEqual((rec["mode"], rec["rule"], rec["with"], rec["without"], rec["delta"]),
                         ("none", "both-arm", 0.56, None, None))
        self.assertEqual(rec["cost"], {"with": round(0.32 / 3, 4)})

    def test_a_bare_result_scores_the_without_arm(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(cost=0.1), graders=GRADERS)],
                         ablation="none", bare=True)
        self.compare("--record", d)
        rec = self.rows()["01-case"][MODEL]
        self.assertEqual((rec["mode"], rec["with"], rec["without"], rec["delta"]), ("bare", None, 0.56, None))
        self.assertEqual(rec["cost"], {"without": round(0.2 / 3, 4)})

    def test_a_bare_and_a_none_result_pair_into_one_row(self):
        bare = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(
            [run(0.5, cost=0.1, secs=40, graders=[grade("answer", False), grade("file", True, weight=0.5)])] * 3,
            graders=GRADERS)], ablation="none", bare=True)
        none = write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                            ablation="none")
        out = self.compare("--record", bare, none)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertIn("bare+none", row)
        rec = self.rows()["01-case"][MODEL]
        self.assertEqual((rec["mode"], rec["rule"], rec["with"], rec["without"], rec["delta"]),
                         ("bare+none", "both-arm", 0.56, 0.33, 0.22))
        self.assertEqual(rec["cost"], {"with": round(0.32 / 3, 4), "without": 0.1})
        self.assertEqual(rec["seconds"], {"with": 60, "without": 40})
        self.assertEqual(rec["results"], "2026-11-25T10-00-00-000Z+2026-11-25T11-00-00-000Z")

    def test_a_paired_row_flags_efficiency_from_the_per_arm_costs(self):
        graders = [grade("answer", True), grade("file", True, weight=0.5)]
        bare = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(
            [run(1.0, cost=0.1, graders=graders)] * 3, graders=GRADERS)], ablation="none", bare=True)
        none = write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(
            [run(1.0, cost=0.16, graders=graders)] * 3, graders=GRADERS)], ablation="none")
        out = self.compare(bare, none)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertIn("$", row)



def script_runs(arm, results, *, case="01-case", grader="g"):
    return [{"case": case, "arm": arm, "run": i + 1, "grader": grader, "passed": p, "reason": "r"}
            for i, p in enumerate(results)]


class ScriptGraderTest(CompareBase):
    """FR-015: script-grader pass rates per logical arm beside the score, stored by --record, a fall flagged."""

    def result(self, name, with_results, without_results, **kw):
        scripts = script_runs("with", with_results) + script_runs("without", without_results)
        scripts += script_runs("with", [False] * 3, case="02-other")
        return write_result(self.tmp, name, [ww_case([run()] * 3, [run(0.5)] * 3)], scripts=scripts, **kw)

    def script_line(self, out, grader="g"):
        return next(line for line in out.splitlines() if line.strip().startswith(f"script {grader}:"))

    def test_the_rates_are_shown_per_arm_under_the_case_row(self):
        out = self.compare(self.result("2026-11-25T10-00-00-000Z", [True, True, False], [False] * 3))
        lines = out.splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("01-case"))
        self.assertEqual(lines[i + 1].strip(), "script g: with 2/3 without 0/3")

    def test_a_crashed_script_counts_as_not_passed_and_as_an_error(self):
        out = self.compare(self.result("2026-11-25T10-00-00-000Z", [True, None, True], [False] * 3))
        self.assertEqual(self.script_line(out).strip(), "script g: with 2/3 without 0/3 (1 error)")

    def test_record_stores_the_rates_rounded(self):
        self.compare("--record", self.result("2026-11-25T10-00-00-000Z", [True, True, False], [False] * 3))
        self.assertEqual(self.rows()["01-case"][MODEL]["scripts"], {"g": {"with": 0.67, "without": 0.0}})

    def test_an_arm_with_no_script_runs_is_left_out(self):
        d = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                         ablation="none", scripts=script_runs("with", [True] * 3))
        out = self.compare("--record", d)
        self.assertEqual(self.script_line(out).strip(), "script g: with 3/3")
        self.assertEqual(self.rows()["01-case"][MODEL]["scripts"], {"g": {"with": 1.0}})

    def test_a_fall_against_the_row_is_flagged(self):
        self.compare("--record", self.result("2026-11-20T10-00-00-000Z", [True] * 3, [False] * 3))
        out = self.compare(self.result("2026-11-25T10-00-00-000Z", [True, True, False], [False] * 3))
        self.assertIn("◀", self.script_line(out))
        self.assertIn("with fell 1.00→0.67", self.script_line(out))
        self.assertIn("1 script grader rate(s) fell by more than 0.10", out)

    def test_a_rate_within_the_noise_floor_is_not_flagged(self):
        self.compare("--record", self.result("2026-11-20T10-00-00-000Z", [True] * 3, [False] * 3))
        out = self.compare(self.result("2026-11-25T10-00-00-000Z", [True] * 3, [True, False, False]))
        self.assertNotIn("◀", self.script_line(out))
        self.assertNotIn("fell", out)

    def test_a_paired_row_takes_each_arm_from_its_own_dir(self):
        bare = write_result(self.tmp, "2026-11-25T10-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                            ablation="none", bare=True, scripts=script_runs("without", [False, True, False]))
        none = write_result(self.tmp, "2026-11-25T11-00-00-000Z", [one_arm_case(none_runs(), graders=GRADERS)],
                            ablation="none", scripts=script_runs("with", [True] * 3))
        out = self.compare("--record", bare, none)
        self.assertEqual(self.script_line(out).strip(), "script g: with 3/3 without 1/3")
        self.assertEqual(self.rows()["01-case"][MODEL]["scripts"], {"g": {"with": 1.0, "without": 0.33}})


if __name__ == "__main__":
    unittest.main()
