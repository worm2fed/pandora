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


def result_dir(root: Path, name: str, *, claude: str, judge: str, with_: float, without: float) -> Path:
    d = root / name
    d.mkdir(parents=True)
    runs = [{"score": with_, "passed": with_ >= 1.0, "turns": 1, "costUsd": 0.1}] * 3
    data = {
        "schemaVersion": 1,
        "claudeVersion": claude,
        "suite": {"ablation": "with-without", "judgeModel": judge},
        "cases": [{
            "name": "01-case",
            "arms": {"with": runs, "without": runs},
            "aggregates": {"score": with_, "scoreWithout": without, "delta": round(with_ - without, 2)},
        }],
    }
    (d / "aggregate-result.json").write_text(json.dumps(data))
    return d


class CompareTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.baseline = self.tmp / "baseline.json"

    def tearDown(self):
        for p in sorted(self.tmp.rglob("*"), reverse=True):
            p.rmdir() if p.is_dir() else p.unlink()
        self.tmp.rmdir()

    def compare(self, *args):
        proc = subprocess.run(
            [sys.executable, str(COMPARE), "--baseline", str(self.baseline), *map(str, args)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_record_stamps_the_harness_and_judge(self):
        d = result_dir(self.tmp, "2026-10-06T10-00-00-000Z", claude="2.1.280", judge="sonnet", with_=1.0, without=0.5)
        self.compare("--record", d)
        row = json.loads(self.baseline.read_text())["cases"]["01-case"]
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
        self.baseline.write_text(json.dumps({"cases": {"01-case": {
            "with": 1.0, "without": 0.5, "delta": 0.5, "runs": 3, "version": "0.14.1", "results": "2026-10-06T10-00-00-000Z"}}}))
        new = result_dir(self.tmp, "2026-10-12T10-00-00-000Z", claude="2.1.296", judge="sonnet", with_=1.0, without=0.8)
        out = self.compare(new)
        row = next(line for line in out.splitlines() if line.startswith("01-case"))
        self.assertNotIn("~", row, row)
        self.assertIn("recorded under unrecorded (1)", out)


if __name__ == "__main__":
    unittest.main()
