"""signals.py emits what the journal carries past route-and-map (#10, ADR 0013).

- `hotspots --json` carries `ranking`: the structure source and the top files with their
  `fix`, `churn` and `fan_in` labels, in the shape `journal.py` validates.
- Every JSON call that wanted the graph and did not get it carries `graph_note`: why,
  and how to build an index. The table output keeps the advisory-once rule.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from test_codegraph import SC002_EDGES, SC002_FILES, ShimSignalsCase
from test_signals import StandardRepoCase, load_signals_module

BUCKETS = {"low", "mid", "high", "top", None}


class TestRanking(StandardRepoCase):
    def test_the_ranking_is_the_top_rows_in_the_json_order(self):
        payload = self.hotspots("--graph", "off")
        ranking = payload["ranking"]
        self.assertEqual(ranking["source"], "regex")
        self.assertLessEqual(len(ranking["files"]), 5)
        expected = [row["path"] for row in payload["files"]][:5]
        self.assertEqual([f["path"] for f in ranking["files"]], expected)
        for entry in ranking["files"]:
            row = next(r for r in payload["files"] if r["path"] == entry["path"])
            self.assertEqual(entry, {"path": row["path"],
                                     "fix": row["labels"]["fix_rate"],
                                     "churn": row["labels"]["commits"],
                                     "fan_in": row["labels"]["fan_in"]})
            self.assertTrue({entry["fix"], entry["churn"], entry["fan_in"]} <= BUCKETS)

    def test_the_ranking_ignores_the_display_cap(self):
        """`--top 1` trims the table, not what the phase records."""
        full = self.hotspots("--graph", "off")["ranking"]
        self.assertEqual(self.hotspots("--graph", "off", "--top", "1")["ranking"], full)

    def test_the_dir_view_still_ranks_files(self):
        payload = self.hotspots("--graph", "off", "--by-dir", "1")
        self.assertEqual(payload["files"], [])
        self.assertIn("src/hot.py", [f["path"] for f in payload["ranking"]["files"]])

    def test_the_ranking_fits_the_journal_shape(self):
        journal = _load_journal()
        ranking = self.hotspots("--graph", "off")["ranking"]
        payload = journal.normalize_payload(
            "review-verdict", {"verdict": "not-ready", "ranking": ranking})
        self.assertEqual(payload["ranking"], ranking)

    def test_unavailable_signals_give_an_unavailable_ranking(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.signals_json("hotspots", "--repo", tmp)
        self.assertEqual(payload["ranking"], {"source": "none", "unavailable": "no-git"})


class TestRankingPaths(unittest.TestCase):
    def setUp(self):
        self.signals = load_signals_module()

    def row(self, path, fix="top"):
        return {"path": path, "labels": {"fix_rate": fix, "commits": "high",
                                         "fan_in": None}}

    def test_paths_keep_their_last_three_segments(self):
        ranking = self.signals.ranking(
            [self.row("a/b/c/d/e.py")], {"available": True, "source": "graph"})
        self.assertEqual([f["path"] for f in ranking["files"]], ["c/d/e.py"])

    def test_a_tail_seen_twice_keeps_both_files(self):
        ranking = self.signals.ranking(
            [self.row("apps/web/src/lib/index.ts", "top"),
             self.row("apps/api/src/lib/index.ts", "low")],
            {"available": True, "source": "graph"})
        self.assertEqual([f["path"] for f in ranking["files"]],
                         ["src/lib/index.ts", "apps/api/src/lib/index.ts"])

    def test_at_most_five_files(self):
        rows = [self.row(f"f{i}.py") for i in range(9)]
        ranking = self.signals.ranking(rows, {"available": True, "source": "regex"})
        self.assertEqual(len(ranking["files"]), 5)

    def test_no_structure_means_source_none(self):
        ranking = self.signals.ranking([self.row("a.py")],
                                       {"available": False, "reason": "no-adapter"})
        self.assertEqual(ranking["source"], "none")


class TestGraphNote(ShimSignalsCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make(files=SC002_FILES)

    def hotspots(self, *args, env):
        return self.signals_json("hotspots", "--repo", self.repo.path, *args, env=env)

    def test_an_absent_graph_gives_a_note_on_every_call(self):
        first = self.hotspots(env=self.absent_env())
        second = self.hotspots(env=self.absent_env())
        self.assertIn("advisory", first)
        self.assertNotIn("advisory", second)
        for payload in (first, second):
            note = payload["graph_note"]
            self.assertIn("codegraph is not installed", note)
            self.assertIn("next signals call builds the index", note)
            self.assertNotIn("\n", note)
            self.assertNotIn(str(self.repo.path), note)
        self.assertEqual(first["ranking"]["source"], "regex")

    def test_off_gives_no_note(self):
        payload = self.hotspots("--graph", "off", env=self.env("ok"))
        self.assertNotIn("graph_note", payload)

    def test_a_present_graph_gives_no_note_and_a_graph_ranking(self):
        payload = self.hotspots(env=self.env(SHIM_EDGES=json.dumps(SC002_EDGES)))
        self.assertEqual(payload["structure"]["source"], "graph")
        self.assertNotIn("graph_note", payload)
        self.assertEqual(payload["ranking"]["source"], "graph")

    def test_a_failed_graph_names_its_reason(self):
        payload = self.hotspots(env=self.env("kill"))
        self.assertIn("(graph-init)", payload["graph_note"])

    def test_the_table_does_not_repeat_it(self):
        self.hotspots(env=self.absent_env())  # spends the advisory
        table = self.signals("hotspots", "--repo", self.repo.path,
                             env=self.absent_env()).stdout
        self.assertNotIn("code graph:", table)

    def test_the_graph_passthrough_carries_it(self):
        proc = self.signals("graph", "--repo", self.repo.path, "--json", "explore", "x",
                            env=self.absent_env())
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["available"])
        self.assertIn("codegraph is not installed", payload["graph_note"])


class TestGraphNoteText(unittest.TestCase):
    def setUp(self):
        self.cg = load_signals_module()._codegraph

    def test_no_note_without_a_graph_reason(self):
        for reason in (None, "", "graph-off", "no-git", "shallow"):
            with self.subTest(reason=reason):
                self.assertIsNone(self.cg.graph_note(reason))

    def test_each_known_reason_says_how_to_get_an_index(self):
        for reason, text in self.cg.GRAPH_NOTES.items():
            with self.subTest(reason=reason):
                self.assertEqual(self.cg.graph_note(reason), text)
                self.assertTrue(text.startswith("code graph: "))
                self.assertIn("regex scanner", text)

    def test_an_unknown_reason_still_gets_a_note(self):
        self.assertIn("(graph-sync)", self.cg.graph_note("graph-sync"))


def _load_journal():
    from test_journal import load_journal_module
    return load_journal_module()


if __name__ == "__main__":
    unittest.main()
