"""The style canon and the code graph leave a trace in the journal (issues #11, #10).

- `phase-entered` validates `style` and `signals`; `design-committed` and `review-verdict`
  validate `ranking` (T001).
- A `route-and-map` entry without `signals` records its own deviation (T002, ADR 0011).
- `stats` reports, per stream and in total, whether the style skill was named and whether
  the graph fed design and review (T003).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from test_journal import GATE, JOURNAL, OK, JournalTestCase

STREAM = "feat/x"
PHASES = ["workspace", "route-and-map", "explore", "clarify", "design", "implement",
          "review", "capture"]

RANKING = {
    "source": "graph",
    "files": [
        {"path": "scripts/journal.py", "fix": "top", "churn": "top", "fan_in": "low"},
        {"path": "review/SKILL.md", "fix": "mid", "churn": "top", "fan_in": None},
    ],
}


class TraceCase(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def enter(self, phase, stream=STREAM, rc=OK, **data):
        """Enter PHASE; on a fresh stream the phases before it count as skipped."""
        if "skipped" not in data and not self.events(stream):
            data["skipped"] = PHASES[:PHASES.index(phase)]
        return self.append_event(stream, "phase-entered", dict(data, phase=phase), rc=rc)

    def types(self, stream=STREAM):
        return [e["type"] for e in self.events(stream)]


class TestStyleShape(TraceCase):
    def test_style_is_a_list_of_skill_names(self):
        self.enter("implement", style=["astrolabe"])
        self.assertEqual(self.events(STREAM)[-1]["data"]["style"], ["astrolabe"])

    def test_an_empty_style_list_is_accepted(self):
        self.enter("implement", style=[])
        self.assertEqual(self.events(STREAM)[-1]["data"]["style"], [])

    def test_a_style_string_is_refused(self):
        proc = self.enter("implement", style="astrolabe", rc=GATE)
        self.assertIn("data.style must be a list of non-empty strings", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_style_items_must_be_non_empty_strings(self):
        for style in ([None], [3], [""], ["  "], ["astrolabe", 1]):
            with self.subTest(style=style):
                proc = self.enter("implement", style=style, rc=GATE)
                self.assertIn("data.style must be a list of non-empty strings", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_verdict_style_is_checked_too(self):
        proc = self.append_event(STREAM, "review-verdict",
                                 {"verdict": "not-ready", "style": [None]}, rc=GATE)
        self.assertIn("data.style", proc.stderr)


class TestSignalsShape(TraceCase):
    def test_each_source_is_accepted(self):
        for source in ("graph", "regex", "none"):
            with self.subTest(source=source):
                self.enter("route-and-map", stream=f"feat/{source}",
                           signals={"source": source, "blast": 3})
                self.assertEqual(self.types(f"feat/{source}"), ["phase-entered"])

    def test_an_unknown_source_is_refused(self):
        proc = self.enter("route-and-map", signals={"source": "maybe"}, rc=GATE)
        self.assertIn("data.signals.source", proc.stderr)
        self.assertIn("graph, regex, none", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_signals_without_a_source_are_refused(self):
        proc = self.enter("route-and-map", signals={"blast": 3}, rc=GATE)
        self.assertIn("signals", proc.stderr)
        self.assertIn("source", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_umbrella_repos_take_the_source_vocabulary(self):
        self.enter("route-and-map", signals={"source": "regex",
                                             "repos": {"api": "graph", "web": "regex"}})
        proc = self.enter("route-and-map", stream="feat/y", rc=GATE,
                          signals={"source": "regex", "repos": {"api": "codegraph"}})
        self.assertIn("data.signals.repos", proc.stderr)

    def test_the_unavailable_reason_is_a_string(self):
        proc = self.enter("route-and-map", rc=GATE,
                          signals={"source": "none", "unavailable": ["shallow"]})
        self.assertIn("data.signals.unavailable must be a string", proc.stderr)

    def test_signals_must_be_an_object(self):
        proc = self.enter("route-and-map", signals="graph", rc=GATE)
        self.assertIn("data.signals must be a JSON object", proc.stderr)

    def test_unavailable_signals_name_source_none(self):
        self.enter("route-and-map", signals={"source": "none", "unavailable": "shallow"})
        self.assertEqual(self.types(), ["phase-entered"])

    def test_vocab_prints_the_nested_rules(self):
        proc = self.journal("--db", self.db, "vocab", "--shape", "phase-entered", rc=OK)
        shape = json.loads(proc.stdout)
        self.assertEqual(shape["string_lists"], ["style"])
        signals = shape["objects"]["signals"]
        self.assertEqual(signals["strings"], ["unavailable"])
        self.assertEqual(signals["map_enums"]["repos"], ["graph", "regex", "none"])
        self.assertEqual(shape["objects"]["signals"]["enums"]["source"],
                         ["graph", "regex", "none"])


class TestRankingShape(TraceCase):
    def test_design_committed_carries_a_ranking(self):
        self.append_event(STREAM, "design-committed",
                          {"worklog": "docs/prd/x.worklog.md", "ranking": RANKING})
        self.assertEqual(self.events(STREAM)[-1]["data"]["ranking"], RANKING)

    def test_review_verdict_carries_a_ranking(self):
        self.append_event(STREAM, "review-verdict", {"verdict": "not-ready", "ranking": RANKING})
        self.assertEqual(self.events(STREAM)[-1]["data"]["ranking"]["source"], "graph")

    def test_an_unavailable_ranking_needs_no_files(self):
        self.append_event(STREAM, "review-verdict", {
            "verdict": "not-ready", "ranking": {"source": "none", "unavailable": "no-git"},
        })

    def test_a_label_outside_the_buckets_is_refused(self):
        bad = {"source": "graph", "files": [{"path": "a.py", "fix": "hot", "churn": "top"}]}
        proc = self.append_event(STREAM, "review-verdict",
                                 {"verdict": "not-ready", "ranking": bad}, rc=GATE)
        self.assertIn("data.ranking.files[0].fix must be one of low, mid, high, top, null, "
                      "got 'hot'", proc.stderr)
        self.assertNotIn("None", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_non_string_label_is_shown_as_json(self):
        bad = {"source": "graph", "files": [{"path": "a.py", "fix": ["top"]}]}
        proc = self.append_event(STREAM, "review-verdict",
                                 {"verdict": "not-ready", "ranking": bad}, rc=GATE)
        self.assertIn('got ["top"]', proc.stderr)

    def test_the_unavailable_reason_is_shown_in_vocab(self):
        proc = self.journal("--db", self.db, "vocab", "--shape", "review-verdict", rc=OK)
        self.assertEqual(json.loads(proc.stdout)["objects"]["ranking"]["strings"],
                         ["unavailable"])

    def test_a_file_entry_must_be_an_object(self):
        bad = {"source": "graph", "files": ["a.py"]}
        proc = self.append_event(STREAM, "design-committed",
                                 {"worklog": "w.md", "ranking": bad}, rc=GATE)
        self.assertIn("data.ranking.files[0]", proc.stderr)
        self.assertIn("JSON object", proc.stderr)

    def test_files_must_be_a_list(self):
        bad = {"source": "graph", "files": {"a.py": {"fix": "top"}}}
        proc = self.append_event(STREAM, "design-committed",
                                 {"worklog": "w.md", "ranking": bad}, rc=GATE)
        self.assertIn("data.ranking.files must be a list", proc.stderr)

    def test_a_file_entry_names_its_path(self):
        bad = {"source": "graph", "files": [{"fix": "top"}]}
        proc = self.append_event(STREAM, "design-committed",
                                 {"worklog": "w.md", "ranking": bad}, rc=GATE)
        self.assertIn("data.ranking.files[0] is missing required key(s): path",
                      proc.stderr)

    def test_the_file_order_is_kept(self):
        self.append_event(STREAM, "design-committed",
                          {"worklog": "w.md", "ranking": RANKING})
        files = self.events(STREAM)[-1]["data"]["ranking"]["files"]
        self.assertEqual([f["path"] for f in files],
                         ["scripts/journal.py", "review/SKILL.md"])

    def test_a_ranking_without_a_source_is_refused(self):
        proc = self.append_event(STREAM, "design-committed",
                                 {"worklog": "w.md", "ranking": {"files": {}}}, rc=GATE)
        self.assertIn("ranking", proc.stderr)
        self.assertIn("source", proc.stderr)

    def test_vocab_prints_the_ranking_rules(self):
        for event_type in ("design-committed", "review-verdict"):
            with self.subTest(event_type=event_type):
                proc = self.journal("--db", self.db, "vocab", "--shape", event_type, rc=OK)
                ranking = json.loads(proc.stdout)["objects"]["ranking"]
                self.assertEqual(ranking["required"], ["source"])
                files = ranking["list_objects"]["files"]
                self.assertEqual(files["enums"]["fix"], ["low", "mid", "high", "top", None])


class TestDeviationShape(TraceCase):
    def test_kind_is_a_string(self):
        proc = self.append_event(STREAM, "deviation", {"note": "n", "kind": 3}, rc=GATE)
        self.assertIn("data.kind must be a string", proc.stderr)

    def test_vocab_prints_kind(self):
        proc = self.journal("--db", self.db, "vocab", "--shape", "deviation", rc=OK)
        self.assertEqual(json.loads(proc.stdout)["strings"], ["kind"])


class TestSignalsMissingDeviation(TraceCase):
    def test_a_map_without_signals_records_a_deviation(self):
        proc = self.enter("route-and-map", primary_home="api", skipped=["workspace"])
        events = self.events(STREAM)
        self.assertEqual([e["type"] for e in events], ["phase-entered", "deviation"])
        deviation = events[1]
        self.assertEqual(deviation["data"]["kind"], "signals-missing")
        self.assertTrue(deviation["data"]["auto"])
        self.assertIn("signals", deviation["data"]["note"])
        self.assertEqual(deviation["actor"], events[0]["actor"])
        self.assertEqual(deviation["version"], events[0]["version"] + 1)
        self.assertIn("deviation", proc.stdout)
        self.assertIn("signals-missing", proc.stdout)
        self.assertIn("while the stream is still in route-and-map", proc.stdout)

    def test_a_map_with_signals_records_no_deviation(self):
        self.enter("route-and-map", signals={"source": "graph"}, skipped=["workspace"])
        self.assertEqual(self.types(), ["phase-entered"])

    def test_another_phase_without_signals_records_no_deviation(self):
        self.enter("workspace")
        self.enter("explore", skipped=["route-and-map"])
        self.assertEqual(self.types(), ["phase-entered", "phase-entered"])

    def test_the_json_output_names_the_deviation_seq(self):
        proc = self.append("--stream", STREAM, "--type", "phase-entered", "--json",
                           "--data", json.dumps({"phase": "route-and-map", "skipped": ["workspace"]}))
        payload = json.loads(proc.stdout)
        deviation = [e for e in self.events(STREAM) if e["type"] == "deviation"][0]
        self.assertEqual(payload["deviation_seq"], deviation["seq"])
        self.assertEqual(payload["version"], deviation["version"])

    def test_a_batch_records_it_too(self):
        lines = "\n".join(json.dumps(r) for r in (
            {"type": "flow-started", "data": {"request": "r", "branch": STREAM}},
            {"type": "phase-entered", "data": {"phase": "route-and-map",
                                               "skipped": ["workspace"]}},
            {"type": "phase-entered", "data": {"phase": "explore"}},
        ))
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "append",
             "--stream", STREAM, "--batch"],
            input=lines + "\n", capture_output=True, text=True, cwd=str(self.root),
        )
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.types(), ["flow-started", "phase-entered", "deviation",
                                        "phase-entered"])
        self.assertIn("signals-missing", proc.stdout)

    def test_a_user_actor_deviation_records_its_session(self):
        self.append("--stream", STREAM, "--type", "phase-entered", "--actor", "user",
                    "--data", json.dumps({"phase": "route-and-map", "skipped": ["workspace"]}))
        entered, deviation = self.events(STREAM)
        self.assertEqual(deviation["actor"], "user")
        self.assertEqual(deviation["data"].get("recorded_by"),
                         entered["data"].get("recorded_by"))


class TestStatsTrace(TraceCase):
    def stats(self, *args):
        proc = self.journal("--db", self.db, "stats", "--json", *args, rc=OK)
        return json.loads(proc.stdout)

    def trace(self, stream=STREAM):
        rows = [r for r in self.stats()["streams"] if r["stream"] == stream]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]["trace"]

    def full_flow(self, stream, style, ranking, signals=True):
        route = {"phase": "route-and-map", "skipped": ["workspace"]}
        if signals:
            route["signals"] = {"source": ranking["source"] if ranking else "regex"}
        self.append_event(stream, "phase-entered", route)
        design = {"worklog": "w.md"}
        if ranking:
            design["ranking"] = ranking
        self.append_event(stream, "design-committed", design)
        implement = {"phase": "implement"}
        if style is not None:
            implement["style"] = style
        self.append_event(stream, "phase-entered", implement)
        review = {"phase": "review"}
        if style is not None:
            review["style"] = style
        self.append_event(stream, "phase-entered", review)
        verdict = {"verdict": "not-ready"}
        if ranking:
            verdict["ranking"] = ranking
        self.append_event(stream, "review-verdict", verdict)

    def test_a_stream_that_named_the_style_and_used_the_graph(self):
        self.full_flow(STREAM, ["astrolabe"], RANKING)
        self.assertEqual(self.trace(), {
            "style": {"implement": "named", "review": "named"},
            "graph": {"route": "graph", "design": "graph", "review": "graph"},
        })

    def test_an_empty_style_list_is_none(self):
        self.full_flow(STREAM, [], RANKING)
        self.assertEqual(self.trace()["style"], {"implement": "none", "review": "none"})

    def test_a_phase_entered_without_style_is_missing(self):
        self.full_flow(STREAM, None, None, signals=False)
        trace = self.trace()
        self.assertEqual(trace["style"], {"implement": "missing", "review": "missing"})
        self.assertEqual(trace["graph"],
                         {"route": "missing", "design": "missing", "review": "missing"})

    def test_an_implied_review_counts_the_verdict_style(self):
        """A review entered only through its verdict still says what it named."""
        self.append_event(STREAM, "review-verdict",
                          {"verdict": "not-ready", "style": ["astrolabe"]})
        self.assertEqual(self.trace()["style"]["review"], "named")

    def test_a_phase_never_reached_is_null(self):
        self.append_event(STREAM, "flow-started", {"request": "r"})
        self.assertEqual(self.trace(), {
            "style": {"implement": None, "review": None},
            "graph": {"route": None, "design": None, "review": None},
        })

    def test_the_last_ranking_wins(self):
        self.append_event(STREAM, "review-verdict",
                          {"verdict": "not-ready", "ranking": {"source": "regex"}})
        self.append_event(STREAM, "review-verdict",
                          {"verdict": "not-ready", "ranking": RANKING})
        self.assertEqual(self.trace()["graph"]["review"], "graph")

    def test_a_fix_round_verdict_without_ranking_keeps_the_first_rounds_source(self):
        self.append_event(STREAM, "review-verdict",
                          {"verdict": "not-ready", "ranking": RANKING})
        self.append_event(STREAM, "review-verdict", {"verdict": "not-ready"})
        self.assertEqual(self.trace()["graph"]["review"], "graph")

    def test_deviations_are_counted_by_kind(self):
        self.enter("route-and-map", skipped=["workspace"])
        self.append_event(STREAM, "deviation", {"note": "brief", "kind": "style-missing"})
        self.append_event(STREAM, "deviation", {"note": "plain"})
        row = [r for r in self.stats()["streams"] if r["stream"] == STREAM][0]
        self.assertEqual(row["deviation_kinds"],
                         {"signals-missing": 1, "style-missing": 1, "-": 1})
        self.assertEqual(row["deviations"], 3)

    def test_totals_answer_how_often_the_graph_fed_design_and_review(self):
        self.full_flow("feat/a", ["astrolabe"], RANKING)
        self.full_flow("feat/b", [], {"source": "regex"})
        self.full_flow("feat/c", None, None, signals=False)
        self.append_event("feat/d", "flow-started", {"request": "r"})
        trace = self.stats()["totals"]["trace"]
        self.assertEqual(trace["graph"]["design"],
                         {"graph": 1, "regex": 1, "missing": 1})
        self.assertEqual(trace["graph"]["review"],
                         {"graph": 1, "regex": 1, "missing": 1})
        self.assertEqual(trace["graph"]["route"],
                         {"graph": 1, "regex": 1, "missing": 1})
        self.assertEqual(trace["style"]["implement"],
                         {"named": 1, "none": 1, "missing": 1})
        self.assertEqual(self.stats()["totals"]["deviation_kinds"],
                         {"signals-missing": 1})

    def test_the_text_report_has_a_trace_section(self):
        self.full_flow("feat/a", ["astrolabe"], RANKING)
        self.full_flow("feat/c", None, None, signals=False)
        out = self.journal("--db", self.db, "stats", rc=OK).stdout
        self.assertIn("style and code graph per stream", out)
        self.assertRegex(out, r"feat/a\s+style impl named, review named"
                              r"\s+· graph route graph, design graph, review graph")
        self.assertIn("graph fed design: 1 of 2 designed streams", out)
        self.assertIn("graph fed review: 1 of 2 reviewed streams", out)
        self.assertIn("style named at implement: 1 of 2", out)
        self.assertIn("deviations by kind: signals-missing 1", out)


if __name__ == "__main__":
    unittest.main()
