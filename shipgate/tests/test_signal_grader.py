"""Contract tests for evals/signal_grader.py (ADR 0016): precision and recall of a
signals.py blast result against a case's expected.json, read from a saved result, a
run's trace.jsonl, a results dir, or the scaffolded fixture (regex arm only, so the tests
do not need codegraph)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
GRADER = SHIPGATE / "evals" / "signal_grader.py"
CASE_13 = SHIPGATE / "evals" / "13-blast-radius-explicit"

_spec = importlib.util.spec_from_file_location("shipgate_signal_grader", GRADER)
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)

EXPECTED = {
    "hub": "src/hub.ts",
    "importers": ["src/a.ts", "src/b.ts", "src/c.ts"],
    "tests": ["test/a.test.ts"],
}


def payload(files, tests=(), source="graph", truncated=False, size=None):
    return {
        "available": True,
        "blast": {"files": None if files is None else list(files),
                  "tests": None if tests is None else list(tests),
                  "truncated": truncated, "size": size if size is not None else len(files or [])},
        "structure": {"source": source},
        "version": 1,
    }


def bash_use(tool_id, command):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}}


def bash_result(tool_id, content):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content}]}}


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.expected = self.tmp / "expected.json"
        self.expected.write_text(json.dumps(EXPECTED))

    def write_trace(self, events, name="trace.jsonl"):
        path = self.tmp / name
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        return path

    def cli(self, *args, code=0):
        proc = subprocess.run([sys.executable, str(GRADER), *map(str, args)],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return proc


class TestMetric(unittest.TestCase):
    def test_counts_and_ratios(self):
        m = sg.metric(["a", "b", "x"], ["a", "b", "c", "d"])
        self.assertAlmostEqual(m["precision"], 2 / 3)
        self.assertAlmostEqual(m["recall"], 0.5)
        self.assertEqual((m["tp"], m["got"], m["truth"]), (2, 3, 4))
        self.assertEqual(m["missed"], ["c", "d"])
        self.assertEqual(m["extra"], ["x"])

    def test_empty_got_has_precision_one(self):
        m = sg.metric([], ["a"])
        self.assertEqual((m["precision"], m["recall"], m["got"]), (1.0, 0.0, 0))

    def test_null_got_has_precision_one_and_stays_null(self):
        m = sg.metric(None, ["a"])
        self.assertEqual((m["precision"], m["recall"]), (1.0, 0.0))
        self.assertIsNone(m["got"])

    def test_empty_truth_has_recall_one(self):
        self.assertEqual(sg.metric(["a"], [])["recall"], 1.0)
        self.assertEqual(sg.metric(None, [])["recall"], 1.0)
        self.assertEqual(sg.metric(["a"], [])["precision"], 0.0)

    def test_a_leading_dot_slash_is_dropped(self):
        m = sg.metric(["./src/a.ts", "src/b.ts"], ["src/a.ts", "./src/b.ts"])
        self.assertEqual((m["precision"], m["recall"]), (1.0, 1.0))

    def test_files_truth_is_importers_and_tests(self):
        truth = sg.load_truth(EXPECTED)
        self.assertEqual(truth["files"], ["src/a.ts", "src/b.ts", "src/c.ts", "test/a.test.ts"])
        self.assertEqual(truth["tests"], ["test/a.test.ts"])
        self.assertEqual(sg.load_truth({"importers": ["x"]})["tests"], [])


class TestScore(TmpCase):
    def test_score_payload(self):
        s = sg.score_payload(payload(["src/a.ts", "src/b.ts", "test/a.test.ts", "src/z.ts"],
                                     ["test/a.test.ts"]), EXPECTED)
        self.assertEqual(s["files"]["tp"], 3)
        self.assertAlmostEqual(s["files"]["precision"], 0.75)
        self.assertAlmostEqual(s["files"]["recall"], 0.75)
        self.assertEqual((s["tests"]["precision"], s["tests"]["recall"]), (1.0, 1.0))
        self.assertEqual(s["source"], "graph")
        self.assertFalse(s["truncated"])

    def test_hotspots_shape_reads_the_blast_object_not_the_rows(self):
        p = payload(["src/a.ts"], [], source="regex")
        p["files"] = [{"path": "src/zzz.ts"}]
        s = sg.score_payload(p, EXPECTED)
        self.assertEqual(s["files"]["extra"], [])
        self.assertEqual(s["source"], "regex")

    def test_a_payload_without_blast_is_an_input_error(self):
        with self.assertRaises(sg.GraderError):
            sg.score_payload({"files": []}, EXPECTED)

    def test_cli_score_reports_truncation(self):
        blast = self.tmp / "blast.json"
        blast.write_text(json.dumps(payload(["src/a.ts"], ["test/a.test.ts"], truncated=True, size=4)))
        out = self.cli("score", blast, self.expected).stdout
        self.assertIn("blast.files  precision 1.00  recall 0.25  (tp 1, got 1, truth 4)", out)
        self.assertIn("truncated", out)
        data = json.loads(self.cli("score", blast, self.expected, "--json").stdout)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["files"]["missed"], ["src/b.ts", "src/c.ts", "test/a.test.ts"])

    def test_cli_score_missing_file_exits_1(self):
        proc = self.cli("score", self.tmp / "nope.json", self.expected, code=1)
        self.assertIn("cannot read", proc.stderr)


class TestCommandMatch(unittest.TestCase):
    def test_matches(self):
        yes = [
            'python3 "/x/shipgate/scripts/signals.py" blast --diff HEAD~1 --json',
            "python3 signals.py hotspots --diff HEAD~1 --blast --json",
            "cat a; git show --stat HEAD; python3 /p/signals.py hotspots --blast --json 2>&1 | head -200",
            "cd app && python3 ../signals.py blast src/x.ts --json --limit 200",
        ]
        no = [
            "python3 signals.py hotspots --diff HEAD~1 --json",
            "python3 signals.py blast --diff HEAD~1",
            "python3 signals.py risk --json",
            "grep -n 'signals.py blast --json' notes.md",
            "git log --oneline",
        ]
        for c in yes:
            self.assertTrue(sg.is_signals_blast(c), c)
        for c in no:
            self.assertFalse(sg.is_signals_blast(c), c)

    def test_blast_objects_skip_surrounding_text(self):
        text = ("shipgate: codegraph not found; using the regex scanner\n"
                + json.dumps({"other": 1}) + "\n"
                + json.dumps(payload(["src/a.ts"]), indent=2)
                + "\nadvisory: install codegraph\n")
        found = sg.blast_objects(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["blast"]["files"], ["src/a.ts"])


class TestTrace(TmpCase):
    def test_the_last_signals_call_wins_and_other_bash_calls_are_ignored(self):
        first = json.dumps(payload(["src/a.ts"]), indent=2)
        last = json.dumps(payload(["src/a.ts", "src/b.ts", "src/c.ts", "test/a.test.ts"], ["test/a.test.ts"]), indent=2)
        trace = self.write_trace([
            {"type": "system", "subtype": "init"},
            bash_use("t1", "git show --stat HEAD"),
            bash_result("t1", "commit abc\n" + json.dumps({"blast": {"files": ["src/z.ts"]}})),
            bash_use("t2", "python3 /p/signals.py blast --diff HEAD~1 --json"),
            bash_result("t2", first),
            bash_use("t3", "python3 /p/signals.py hotspots --diff HEAD~1 --blast --json"),
            bash_result("t3", [{"type": "text", "text": last + "\nshipgate: one advisory line\n"}]),
            bash_use("t4", "ls"),
            bash_result("t4", "app\n"),
        ])
        s = sg.score_trace(str(trace), EXPECTED)
        self.assertEqual((s["files"]["precision"], s["files"]["recall"]), (1.0, 1.0))
        self.assertEqual((s["call"], s["calls"]), (2, 2))
        self.assertIn("hotspots", s["command"])
        out = self.cli("trace", trace, self.expected).stdout
        self.assertIn("recall 1.00", out)
        self.assertIn("from signals call 2 of 2", out)

    def test_an_unparsable_last_result_falls_back_to_the_previous_call(self):
        trace = self.write_trace([
            bash_use("t1", "python3 signals.py blast --diff HEAD~1 --json"),
            bash_result("t1", json.dumps(payload(["src/a.ts"]))),
            bash_use("t2", "python3 signals.py blast --diff HEAD~1 --json"),
            bash_result("t2", "Traceback (most recent call last):\n  boom\n"),
        ])
        s = sg.score_trace(str(trace), EXPECTED)
        self.assertEqual((s["call"], s["calls"]), (1, 2))
        self.assertEqual(s["files"]["tp"], 1)

    def test_a_last_result_with_null_files_falls_back_to_the_previous_call(self):
        trace = self.write_trace([
            bash_use("t1", "python3 signals.py blast --diff HEAD~1 --json"),
            bash_result("t1", json.dumps(payload(["src/a.ts", "src/b.ts"]))),
            bash_use("t2", "python3 signals.py blast --diff HEAD~1 --json"),
            bash_result("t2", json.dumps(payload(None))),
        ])
        s = sg.score_trace(str(trace), EXPECTED)
        self.assertEqual((s["call"], s["calls"]), (1, 2))
        self.assertEqual((s["files"]["tp"], s["files"]["got"]), (2, 2))
        self.assertEqual(s["files"]["recall"], 0.5)

    def test_no_signals_result_exits_3(self):
        trace = self.write_trace([bash_use("t1", "git log"), bash_result("t1", "x")])
        self.assertIsNone(sg.score_trace(str(trace), EXPECTED))
        proc = self.cli("trace", trace, self.expected, code=sg.EXIT_NO_RESULT)
        self.assertIn("no signals result in the trace", proc.stdout)
        proc = self.cli("trace", trace, self.expected, "--json", code=sg.EXIT_NO_RESULT)
        self.assertEqual(json.loads(proc.stdout)["note"], "no signals result in the trace")


class TestResults(TmpCase):
    def make_results(self):
        plugin = self.tmp / "plugin"
        case = plugin / "evals" / "99-blast"
        case.mkdir(parents=True)
        (case / "expected.json").write_text(json.dumps(EXPECTED))
        (plugin / "evals" / "98-other").mkdir()
        trace = self.write_trace([
            bash_use("t1", "python3 signals.py blast --diff HEAD~1 --json"),
            bash_result("t1", json.dumps(payload(["src/a.ts", "src/x.ts"], None, source="regex"))),
        ])
        empty = self.write_trace([bash_use("t1", "ls"), bash_result("t1", "")], name="empty.jsonl")
        d = self.tmp / "results" / "2026-11-06T10-00-00-000Z"
        d.mkdir(parents=True)
        data = {
            "suite": {"root": str(plugin)},
            "cases": [
                {"name": "98-other", "dir": "evals/98-other",
                 "arms": {"with": [{"tracePath": str(trace)}]}},
                {"name": "99-blast", "dir": "evals/99-blast",
                 "arms": {"with": [{"tracePath": str(trace)}, {"tracePath": str(self.tmp / "gone.jsonl")}],
                          "without": [{"tracePath": str(empty)}, {"tracePath": None}]}},
            ],
        }
        (d / "aggregate-result.json").write_text(json.dumps(data))
        return d

    def test_one_row_per_run_of_a_case_with_expected_json(self):
        d = self.make_results()
        rows = sg.results_rows(str(d.parent))
        self.assertEqual([(r["case"], r["arm"], r["run"]) for r in rows],
                         [("99-blast", "with", 1), ("99-blast", "with", 2),
                          ("99-blast", "without", 1), ("99-blast", "without", 2)])
        self.assertEqual(rows[0]["source"], "regex")
        self.assertAlmostEqual(rows[0]["files"]["precision"], 0.5)
        self.assertAlmostEqual(rows[0]["files"]["recall"], 0.25)
        self.assertIsNone(rows[0]["tests"]["got"])
        self.assertEqual(rows[1]["note"], "trace gone (run with --keep-temp)")
        self.assertEqual(rows[2]["note"], "no signals result in the trace")
        self.assertEqual(rows[3]["note"], "trace gone (run with --keep-temp)")

    def test_cli_results(self):
        d = self.make_results()
        out = self.cli("results", d).stdout
        self.assertIn("99-blast", out)
        self.assertNotIn("98-other", out)
        self.assertIn("0.50/0.25", out)
        self.assertIn("null/1", out)
        self.assertIn("trace gone (run with --keep-temp)", out)
        self.assertEqual(len(json.loads(self.cli("results", d, "--json").stdout)), 4)

    def test_cli_results_without_aggregate_exits_1(self):
        self.cli("results", self.tmp, code=1)


class TestFixture(TmpCase):
    def test_case_13_regex_arm(self):
        proc = self.cli("fixture", CASE_13, "--arm", "regex", "--json")
        s = json.loads(proc.stdout)
        self.assertEqual(s["source"], "regex")
        self.assertEqual((s["files"]["precision"], s["files"]["recall"]), (1.0, 1.0))
        self.assertEqual(s["files"]["truth"], 6)
        self.assertIsNone(s["tests"]["got"])

    def test_case_13_expected_matches_the_grader_rubric(self):
        expected = json.loads((CASE_13 / "expected.json").read_text())
        self.assertEqual(expected["hub"], "src/util/round.ts")
        self.assertEqual(set(expected["importers"]), {
            "src/util/currency.ts", "src/util/percent.ts", "src/billing/lineItem.ts",
            "src/billing/tax.ts", "src/billing/invoice.ts", "src/billing/pdfSummary.ts"})
        self.assertEqual(expected["tests"], [])
        self.assertFalse(set(expected["importers"]) & set(expected["distractors"]))

    def test_a_case_without_fixture_exits_1(self):
        case = self.tmp / "00-none"
        case.mkdir()
        (case / "expected.json").write_text(json.dumps(EXPECTED))
        proc = self.cli("fixture", case, "--arm", "regex", code=1)
        self.assertIn("no fixture.sh", proc.stderr)

    def test_a_failing_fixture_exits_1(self):
        case = self.tmp / "00-broken"
        case.mkdir()
        (case / "expected.json").write_text(json.dumps(EXPECTED))
        (case / "fixture.sh").write_text("exit 7\n")
        proc = self.cli("fixture", case, "--arm", "regex", code=1)
        self.assertIn("fixture.sh failed (exit 7)", proc.stderr)


if __name__ == "__main__":
    unittest.main()
