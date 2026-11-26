"""Contract tests for the run-evals skill's summarize.py (ADR 0034 to 0036): per results
dir it prints the model and the mode, and per case the score, the mean cost and time per
run of each arm, the judge cost, the shadow mark and the script-grader pass rates, beside
today's turns and skill-fired columns. The results dirs are canned; nothing runs a model."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SUMMARIZE = REPO / ".claude" / "skills" / "run-evals" / "scripts" / "summarize.py"

SKILL_GRADER = {"name": "fires", "type": "tool_used", "weight": 1,
                "config": {"tool": "Skill", "min": 1}}
ANSWER_GRADER = {"name": "names-the-file", "type": "regex", "weight": 1, "config": {}}


def run(score, turns, cost, seconds, judge=0.01, fired=None, error=None):
    graders = [{"name": "names-the-file", "passed": score == 1.0, "scored": True,
                "withOnly": False, "weight": 1}]
    if fired is not None:
        graders.append({"name": "fires", "passed": fired, "scored": False, "withOnly": True,
                        "weight": 1})
    return {"score": score, "passed": score == 1.0, "turns": turns, "costUsd": cost,
            "judgeCostUsd": judge, "durationSeconds": seconds, "error": error,
            "graders": graders}


def aggregate(suite, cases):
    return {"schemaVersion": 1, "claudeVersion": "2.1.300", "costUsd": 1.5,
            "durationSeconds": 300, "partial": False, "suite": suite, "cases": cases}


WITH_WITHOUT = aggregate(
    {"ablation": "with-without", "judgeModel": "sonnet", "modelOverride": "claude-fable-5-2",
     "plugins": [{"name": "shipgate", "path": "/p", "version": "0.36.0"}]},
    [{"name": "02-selective-bug", "dir": "02-selective-bug",
      "graders": [ANSWER_GRADER, SKILL_GRADER],
      "arms": {"with": [run(1.0, 5, 0.30, 40, fired=True), run(1.0, 6, 0.20, 50, fired=True),
                        run(1.0, 7, 0.40, 60, fired=False)],
               "without": [run(1.0, 4, 0.10, 20), run(0.0, 4, 0.20, 30),
                           run(0.5, 5, 0.30, 40)]},
      "aggregates": {"score": 1.0, "passRate": 1.0, "scoreWithout": 0.5,
                     "passRateWithout": 0.33, "delta": 0.5}}])

SHADOW = {"plugin": "shipgate", "tree": "/tree", "version": "0.36.0", "shadowed": True,
          "runs": [{"case": "02-selective-bug", "arm": "with", "run": 1, "shadowed": True,
                    "reason": "loaded /cache", "loaded": []},
                   {"case": "02-selective-bug", "arm": "with", "run": 2, "shadowed": False,
                    "reason": "", "loaded": []},
                   {"case": "02-selective-bug", "arm": "with", "run": 3, "shadowed": False,
                    "reason": "", "loaded": []},
                   {"case": "02-selective-bug", "arm": "without", "run": 1, "shadowed": True,
                    "reason": "", "loaded": []},
                   {"case": "02-selective-bug", "arm": "without", "run": 2, "shadowed": True,
                    "reason": "", "loaded": []},
                   {"case": "02-selective-bug", "arm": "without", "run": 3, "shadowed": False,
                    "reason": "", "loaded": []}]}


def script_rows(case, arm, results, grader="no-edit"):
    return [{"case": case, "arm": arm, "run": k, "grader": grader, "passed": p, "reason": "r"}
            for k, p in enumerate(results, 1)]


SCRIPT_GRADERS = {"runs": script_rows("02-selective-bug", "with", [True, True, True])
                  + script_rows("02-selective-bug", "without", [True, False, None])}

BARE = aggregate(
    {"ablation": "none", "judgeModel": "sonnet",
     "plugins": [{"name": "shipgate-bare", "path": "/stub", "version": "0.0.0"}]},
    [{"name": "24-verify-pasted-evidence", "dir": "24-verify-pasted-evidence",
      "graders": [ANSWER_GRADER],
      "arms": {"with": [run(1.0, 3, 0.10, 20, judge=0.02), run(1.0, 3, 0.10, 20, judge=0.02),
                        run(0.0, 4, 0.10, 20, judge=0.02)]},
      "aggregates": {"score": 0.67, "passRate": 0.67}}])


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def results_dir(self, name, data, **sidecars):
        d = self.tmp / name
        d.mkdir()
        (d / "aggregate-result.json").write_text(json.dumps(data))
        for key, value in sidecars.items():
            (d / f"{key.replace('_', '-')}.json").write_text(json.dumps(value))
        return d

    def summarize(self, *paths):
        proc = subprocess.run([sys.executable, str(SUMMARIZE), *map(str, paths)],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_with_without_dir(self):
        d = self.results_dir("2026-11-25T10-00-00-000Z", WITH_WITHOUT, shadow=SHADOW,
                             script_graders=SCRIPT_GRADERS)
        out = self.summarize(d)
        self.assertIn("model claude-fable-5-2  mode with-without", out)
        row = next(line for line in out.splitlines() if "02-selective-bug" in line)
        self.assertRegex(row, r"02-selective-bug\s+1\.00\s+0\.50\s+\+0\.50\s+5,6,7\s+4,4,5\s+2/3")
        self.assertIn("with $0.30/run 50s/run", out)
        self.assertIn("without $0.20/run 30s/run", out)
        self.assertIn("judge $0.06", out)
        self.assertIn("SHADOWED 1/3 with, 2/3 without", out)
        self.assertIn("script graders: no-edit with 3/3, without 1/3 (1 error)", out)

    def test_no_shadow_file_is_unchecked(self):
        d = self.results_dir("r", WITH_WITHOUT)
        out = self.summarize(d)
        self.assertIn("shadow: unchecked", out)
        self.assertNotIn("script graders", out)

    def test_clean_shadow(self):
        clean = dict(SHADOW, shadowed=False,
                     runs=[dict(r, shadowed=False) for r in SHADOW["runs"]])
        out = self.summarize(self.results_dir("r", WITH_WITHOUT, shadow=clean))
        self.assertIn("shadow: clean", out)

    def test_bare_dir(self):
        shadow = {"plugin": "shipgate", "tree": "/tree", "version": "0.36.0", "shadowed": False,
                  "runs": [{"case": "24-verify-pasted-evidence", "arm": "without", "run": k,
                            "shadowed": False, "reason": "", "loaded": []} for k in (1, 2, 3)]}
        d = self.results_dir("b", BARE, bare={"arm": "bare", "plugin": "shipgate",
                                              "stub": "shipgate-bare", "version": "0.36.0"},
                             shadow=shadow,
                             script_graders={"runs": script_rows("24-verify-pasted-evidence",
                                                                 "without", [True, False, True])})
        out = self.summarize(d)
        self.assertIn("model not recorded  mode bare", out)
        header = next(line for line in out.splitlines() if line.strip().startswith("case"))
        self.assertRegex(header, r"case\s+bare\s+w/out")
        row = next(line for line in out.splitlines() if "24-verify-pasted-evidence" in line)
        self.assertRegex(row, r"24-verify-pasted-evidence\s+0\.67\s+n/a\s+n/a\s+3,3,4\s+-")
        self.assertIn("bare $0.10/run 20s/run", out)
        self.assertIn("judge $0.06", out)
        self.assertIn("shadow: clean", out)
        self.assertIn("script graders: no-edit bare 2/3", out)

    def test_results_root_summarizes_every_dir(self):
        self.results_dir("a", WITH_WITHOUT)
        self.results_dir("b", BARE, bare={"arm": "bare", "plugin": "shipgate",
                                          "stub": "shipgate-bare", "version": "0.36.0"})
        out = self.summarize(self.tmp)
        self.assertIn("mode with-without", out)
        self.assertIn("mode bare", out)


if __name__ == "__main__":
    unittest.main()
