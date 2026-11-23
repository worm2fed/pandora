#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: ``position``.

Every fact the HUD draws for one stream. Split out of ``test_journal.py`` (#61), which holds
the helpers and fixtures.
"""

from __future__ import annotations

import json
import os
import unittest

from test_journal import INFRA, JournalTestCase, OK, USAGE, load_journal_module


# The keys `position --json` printed in shipgate 0.20.0. A later release adds keys and
# never renames or removes one of these (FR-007).
POSITION_KEYS_0_20_0 = {
    "stream", "version", "lifecycle", "current", "publish", "phases", "artifacts",
    "tasks", "last_verify", "decisions", "verdict",
}
POSITION_VERDICT_KEYS_0_20_0 = {"seq", "at", "verdict", "criteria", "dispositions"}
# 0.28.0 (ADR 0023) adds `go`.
POSITION_KEYS = POSITION_KEYS_0_20_0 | {"trace", "dispositions", "go"}

POSITION_WORKLOG = """# Worklog: demo

# Design

- [x] T900 — prose, not a task

# Build Plan

## Declarations
- [x] T001 — the types — file(s): `a.py` — done when: reviewed
- [ ] T002 [P] — the bodies

## Release
* [x] T003 — ship it
- [ ] T001 — a repeated id
- [ ] T004
"""


class TestPosition(JournalTestCase):
    """`position --stream <s> --json`: every fact the HUD draws (ADR 0009)."""

    S = "feature/demo"

    def setUp(self):
        super().setUp()
        self.init_db()

    def position(self, stream=S):
        proc = self.journal("--db", self.db, "position", "--stream", stream, "--json",
                            rc=OK)
        return json.loads(proc.stdout)

    def last(self, stream=S):
        return self.events(stream)[-1]

    def sidecar(self, **homes):
        claude = self.root / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "shipgate.json").write_text(
            json.dumps({"version": 1, "artifact_homes": homes}), encoding="utf-8"
        )

    def import_row(self, stream, etype, data, ts="2026-10-01T09:00:00+00:00"):
        """A row as an older journal.py wrote it: no shape, no gate."""
        raw = self.root / "row.jsonl"
        raw.write_text(json.dumps({
            "stream": stream, "version": len(self.events(stream)) + 1, "type": etype,
            "data": data, "ts": ts, "actor": "orchestrator",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)

    def design(self, stream=S, **data):
        data.setdefault("worklog", "docs/prd/demo.worklog.md")
        self.append_event(stream, "design-committed", data)

    def verify(self, outcome, *task_ids, stream=S):
        self.append_event(stream, "verify-run",
                          {"outcome": outcome, "task_ids": list(task_ids)})

    # -- the envelope -------------------------------------------------------

    def test_an_unknown_stream_exits_1_not_2(self):
        """R4: exit 2 means argparse's usage error, which the HUD reads as an older
        journal.py without `position`."""
        proc = self.journal("--db", self.db, "position", "--stream", "feature/nope",
                            "--json", rc=INFRA)
        self.assertIn("feature/nope", proc.stderr)

    def test_a_missing_stream_flag_is_a_usage_error(self):
        self.journal("--db", self.db, "position", "--json", rc=USAGE)

    def test_the_keys(self):
        self.append_event(self.S, "flow-started", {"request": "build it"})
        self.assertEqual(set(self.position()), POSITION_KEYS)

    def test_a_stream_with_only_flow_started(self):
        self.append_event(self.S, "flow-started", {"request": "build it"})
        position = self.position()
        self.assertEqual(position["stream"], self.S)
        self.assertEqual(position["version"], 1)
        self.assertEqual(position["lifecycle"], "live")
        self.assertIsNone(position["current"])
        self.assertEqual(set(position["phases"].values()), {"todo"})
        self.assertEqual(position["publish"], {"kind": "held"})
        self.assertEqual(position["artifacts"], {
            "worklog": None, "worklog_from": None, "prd": None, "adrs": [],
        })
        self.assertIsNone(position["tasks"])
        self.assertIsNone(position["last_verify"])
        self.assertEqual(position["decisions"], [])
        self.assertIsNone(position["verdict"])
        self.assertEqual(position["trace"], {
            "review_ranking": None, "design_ranking": None, "signals_missing": [],
        })
        self.assertEqual(position["dispositions"], {})

    def test_the_fold_fields_equal_the_status_brief(self):
        self.append_event(self.S, "flow-started", {"request": "build it"})
        self.design()
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {"verdict": "ready"})
        feature = self.status_json("--feature", self.S)["features"][0]
        position = self.position()
        for key in ("stream", "version", "lifecycle", "current", "publish"):
            self.assertEqual(position[key], feature[key], key)
        self.assertEqual(position["publish"]["by"], "review-verdict")

    def test_phases_mark_an_implied_jump_skipped(self):
        self.append_event(self.S, "flow-started", {"request": "build it"})
        self.design()
        self.assertEqual(self.position()["phases"], {
            "workspace": "skipped", "route-and-map": "skipped", "explore": "skipped",
            "clarify": "skipped", "design": "current", "implement": "todo",
            "review": "todo", "capture": "todo",
        })

    def test_a_terminal_stream_answers_too(self):
        self.append_event(self.S, "flow-started", {"request": "build it"})
        self.append_event(self.S, "flow-completed", {})
        self.assertEqual(self.position()["lifecycle"], "terminal")

    # -- artifacts ------------------------------------------------------------

    def test_the_worklog_and_adrs_come_from_the_committing_events(self):
        self.design(adrs=["docs/adr/0001-a.md", "docs/adr/0002-b.md#context"],
                    refs=["docs/adr/0001-a.md", "docs/prd/demo.md"])
        self.verify("pass", "T001", )
        self.append_event(self.S, "task-done", {
            "task_id": "T001", "refs": ["docs/adr/0003-c.md"],
        })
        self.assertEqual(self.position()["artifacts"], {
            "worklog": "docs/prd/demo.worklog.md", "worklog_from": "event", "prd": None,
            "adrs": ["docs/adr/0001-a.md", "docs/adr/0002-b.md", "docs/adr/0003-c.md"],
        })

    def test_context_refs_do_not_count(self):
        """A flow-started, phase-entered or deviation ref is often an older slice's."""
        self.append_event(self.S, "flow-started", {
            "request": "x", "refs": ["docs/prd/old.worklog.md", "docs/adr/0009-old.md"],
        })
        self.append_event(self.S, "deviation", {
            "note": "x", "worklog": "docs/prd/old.worklog.md",
        })
        artifacts = self.position()["artifacts"]
        self.assertIsNone(artifacts["worklog"])
        self.assertEqual(artifacts["adrs"], [])

    def test_the_last_worklog_ref_wins(self):
        self.design(worklog="docs/prd/first.worklog.md")
        self.design(worklog="docs/prd/second.worklog.md#build-plan")
        self.assertEqual(self.position()["artifacts"]["worklog"],
                         "docs/prd/second.worklog.md")

    def test_the_prd_is_the_last_clarify_passed_one(self):
        self.write("docs/prd/one.md", "# one\n")
        self.write("docs/prd/two.md", "# two\n")
        self.append_event(self.S, "clarify-passed", {"prd": "docs/prd/one.md"})
        self.append_event(self.S, "clarify-passed", {"prd": "docs/prd/two.md"})
        self.assertEqual(self.position()["artifacts"]["prd"], "docs/prd/two.md")

    def test_a_custom_adr_home_classifies_the_adrs(self):
        """audit D13: the HUD hardcoded `/adr/`."""
        self.sidecar(adr="design/decisions/*.md")
        self.design(adrs=["design/decisions/0001-a.md", "docs/adr/0002-b.md"])
        self.assertEqual(self.position()["artifacts"]["adrs"],
                         ["design/decisions/0001-a.md"])

    def test_unsafe_refs_are_dropped(self):
        """R5: absolute, `..`, drive and scheme refs never reach the HUD."""
        prd = self.write("docs/prd/demo.md", "# demo\n")
        self.append_event(self.S, "clarify-passed", {"prd": str(prd)})
        self.design(worklog="docs/prd/demo.worklog.md", adrs=[
            "/etc/adr/0001.md", "\\share\\docs\\adr\\0002.md", "docs/adr/../adr/0003.md",
            "C:/repo/docs/adr/0004.md", "file://host/docs/adr/0005.md",
            "docs/adr/0006-ok.md",
        ])
        self.design(worklog="../outside/docs/prd/demo.worklog.md")
        artifacts = self.position()["artifacts"]
        self.assertIsNone(artifacts["prd"])
        self.assertEqual(artifacts["adrs"], ["docs/adr/0006-ok.md"])
        self.assertEqual(artifacts["worklog"], "docs/prd/demo.worklog.md")

    # -- the worklog fallback --------------------------------------------------

    def touch(self, relpath, mtime):
        path = self.write(relpath, POSITION_WORKLOG)
        os.utime(path, (mtime, mtime))
        return path

    def test_with_no_worklog_ref_the_slug_named_worklog_is_used(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch("docs/prd/demo.worklog.md", 1_000)
        self.touch("docs/prd/demo-part-two.worklog.md", 2_000)
        self.touch("docs/prd/demonstration.worklog.md", 3_000)
        artifacts = self.position()["artifacts"]
        self.assertEqual(artifacts["worklog"], "docs/prd/demo-part-two.worklog.md")
        self.assertEqual(artifacts["worklog_from"], "name")

    def test_the_fallback_uses_the_last_path_segment_of_the_stream(self):
        """R7."""
        self.append_event("fix/1290-demo", "flow-started", {"request": "x"})
        self.touch("docs/prd/1290-demo.worklog.md", 1_000)
        self.assertEqual(self.position("fix/1290-demo")["artifacts"]["worklog"],
                         "docs/prd/1290-demo.worklog.md")

    def test_43_the_slug_without_its_issue_id_names_a_worklog(self):
        self.append_event("fix/1290-demo", "flow-started", {"request": "x"})
        self.touch("docs/prd/demo.worklog.md", 1_000)
        artifacts = self.position("fix/1290-demo")["artifacts"]
        self.assertEqual((artifacts["worklog"], artifacts["worklog_from"]),
                         ("docs/prd/demo.worklog.md", "name"))

    def test_43_the_full_slug_beats_the_slug_without_its_issue_id(self):
        self.append_event("fix/1290-demo", "flow-started", {"request": "x"})
        self.touch("docs/prd/1290-demo.worklog.md", 1_000)
        self.touch("docs/prd/demo.worklog.md", 2_000)  # newer, but the weaker name
        self.assertEqual(self.position("fix/1290-demo")["artifacts"]["worklog"],
                         "docs/prd/1290-demo.worklog.md")

    def test_43_the_slug_without_its_issue_id_skips_a_claimed_worklog(self):
        """Each slug keeps `position`'s rule: a worklog a live stream names is left to it."""
        self.append_event("fix/1290-demo", "flow-started", {"request": "x"})
        self.touch("docs/prd/demo.worklog.md", 1_000)
        self.design(stream="epic/demo", worklog="docs/prd/demo.worklog.md")
        self.assertIsNone(self.position("fix/1290-demo")["artifacts"]["worklog"])

    def test_43_only_one_leading_issue_id_of_ascii_digits_is_removed(self):
        self.touch("docs/prd/demo.worklog.md", 1_000)
        for stream in ("fix/1290", "fix/1290-", "fix/v2-demo", "fix/demo-1290",
                       "fix/12-34-demo"):
            with self.subTest(stream=stream):
                self.append_event(stream, "flow-started", {"request": "x"})
                self.assertIsNone(self.position(stream)["artifacts"]["worklog"])
        slugs = load_journal_module()._stream_slugs
        self.assertEqual(slugs("fix/1290-date-off-by-one"),
                         ["1290-date-off-by-one", "date-off-by-one"])
        self.assertEqual(slugs("fix/12-34-demo"), ["12-34-demo", "34-demo"])
        self.assertEqual(slugs("fix/\u0661\u0662-demo"), ["\u0661\u0662-demo"])
        self.assertEqual(slugs("fix/1290-"), ["1290-"])
        self.assertEqual(slugs("feat/demo"), ["demo"])
        self.assertEqual(slugs("fix/"), [])

    def test_a_worklog_another_live_stream_names_is_left_to_it(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch("docs/prd/demo.worklog.md", 2_000)
        self.touch("docs/prd/demo-old.worklog.md", 1_000)
        self.design(stream="epic/demo", worklog="docs/prd/demo.worklog.md")
        self.assertEqual(self.position()["artifacts"]["worklog"],
                         "docs/prd/demo-old.worklog.md")

    def test_a_claim_from_a_nested_repo_counts_by_its_tail(self):
        """A nested repo's stream names its worklog relative to that repo."""
        self.sidecar(worklog="*/docs/prd/*.worklog.md")
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch("svc/docs/prd/demo.worklog.md", 1_000)
        self.design(stream="epic/demo", worklog="docs/prd/demo.worklog.md")
        self.assertIsNone(self.position()["artifacts"]["worklog"])

    def test_a_finished_streams_claim_does_not_count(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch("docs/prd/demo.worklog.md", 1_000)
        self.design(stream="epic/demo", worklog="docs/prd/demo.worklog.md")
        self.append_event("epic/demo", "flow-completed", {})
        self.assertEqual(self.position()["artifacts"]["worklog"],
                         "docs/prd/demo.worklog.md")

    def test_the_fallback_reads_the_configured_worklog_home(self):
        self.sidecar(worklog=".notes/*.worklog.md")
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch(".notes/demo.worklog.md", 1_000)
        self.touch("docs/prd/demo.worklog.md", 2_000)
        self.assertEqual(self.position()["artifacts"]["worklog"],
                         ".notes/demo.worklog.md")

    def test_no_slug_named_worklog_is_no_worklog(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.touch("docs/prd/other.worklog.md", 1_000)
        artifacts = self.position()["artifacts"]
        self.assertIsNone(artifacts["worklog"])
        self.assertIsNone(artifacts["worklog_from"])

    # -- tasks -----------------------------------------------------------------

    def test_tasks_come_from_the_worklog_with_their_journal_state(self):
        self.write("docs/prd/demo.worklog.md", POSITION_WORKLOG)
        self.design()
        self.verify("pass", "T001")
        t001 = self.last()
        self.append_event(self.S, "task-done", {"task_id": "T001"})
        self.verify("pass", "T003")
        self.verify("fail", "T003")
        failed = self.last()
        tasks = self.position()["tasks"]
        self.assertEqual([t["id"] for t in tasks], ["T001", "T002", "T003", "T004"])
        by_id = {t["id"]: t for t in tasks}
        self.assertEqual(by_id["T001"], {
            "id": "T001", "title": "the types", "section": "Declarations",
            "ticked": True, "done": True,
            "last_verify": {"outcome": "pass", "at": t001["ts"]},
        })
        self.assertEqual(by_id["T002"]["title"], "the bodies")
        self.assertFalse(by_id["T002"]["done"])
        self.assertIsNone(by_id["T002"]["last_verify"])
        self.assertEqual(by_id["T003"]["section"], "Release")
        self.assertTrue(by_id["T003"]["ticked"])
        self.assertEqual(by_id["T003"]["last_verify"],
                         {"outcome": "fail", "at": failed["ts"]})
        self.assertIsNone(by_id["T004"]["title"])

    def test_a_repeated_task_id_keeps_its_first_line(self):
        """R6."""
        self.write("docs/prd/demo.worklog.md", POSITION_WORKLOG)
        self.design()
        tasks = [t for t in self.position()["tasks"] if t["id"] == "T001"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "the types")

    def test_tasks_from_a_nested_build_plan_heading(self):
        self.write("docs/prd/demo.worklog.md",
                   "# W\n\n## Build Plan\n- [ ] T001 — a\n### Sub\n* [x] T002 — b\n"
                   "## Notes\n- [ ] T003 — not a task\n")
        self.design()
        tasks = self.position()["tasks"]
        self.assertEqual([(t["id"], t["section"], t["ticked"]) for t in tasks],
                         [("T001", None, False), ("T002", "Sub", True)])

    def test_tasks_are_none_without_a_readable_worklog(self):
        self.design(worklog="docs/prd/missing.worklog.md")
        self.assertIsNone(self.position()["tasks"])

    def test_tasks_are_empty_when_the_build_plan_lists_none(self):
        self.write("docs/prd/demo.worklog.md", "# W\n\n# Build Plan\n\nnothing yet\n")
        self.design()
        self.assertEqual(self.position()["tasks"], [])

    # -- verify, decisions, verdict ---------------------------------------------

    def test_last_verify_is_the_last_run_that_passed_or_failed(self):
        """R1. A row whose outcome is outside the vocabulary is dropped."""
        self.verify("fail", "T001", "T002")
        failed = self.last()
        self.import_row(self.S, "verify-run", {"outcome": "green", "task_ids": ["T009"]})
        self.assertEqual(self.position()["last_verify"], {
            "outcome": "fail", "task_ids": ["T001", "T002"], "at": failed["ts"],
        })

    def test_decisions_are_oldest_first_with_their_real_seq(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.append_event(self.S, "gate-decision", {
            "gate": "clarify", "question": "q1", "decision": "a", "mode": "executive",
        })
        first = self.last()
        self.append_event(self.S, "gate-decision", {
            "gate": "publish", "question": "q2", "decision": "publish", "mode": "ask",
            "raised_by": "user", "rationale": "not printed",
        })
        second = self.last()
        self.assertEqual(self.position()["decisions"], [
            {"seq": first["seq"], "gate": "clarify", "question": "q1", "decision": "a",
             "raised_by": "orchestrator", "mode": "executive", "at": first["ts"]},
            {"seq": second["seq"], "gate": "publish", "question": "q2",
             "decision": "publish", "raised_by": "user", "mode": "ask",
             "at": second["ts"]},
        ])

    def test_an_old_decision_prints_null_for_what_it_lacks(self):
        self.import_row(self.S, "gate-decision", {
            "chosen": "sqlite", "decision": ["publish"], "mode": "sometimes",
            "raised_by": "someone",
        })
        decision = self.position()["decisions"][0]
        self.assertEqual(decision["gate"], None)
        self.assertEqual(decision["question"], None)
        self.assertEqual(decision["decision"], None)
        self.assertEqual(decision["mode"], None)
        self.assertEqual(decision["raised_by"], "orchestrator")

    def test_the_verdict_is_the_last_review_verdict(self):
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {"verdict": "not-ready"})
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {
            "verdict": "ready",
            "criteria": {"SC-001": "met", "SC-002": "unmet"},
            "dispositions": {"./src/a.py:12": "fixed", "src/b.py:?": "deferred"},
        })
        event = self.last()
        self.assertEqual(self.position()["verdict"], {
            "seq": event["seq"], "at": event["ts"], "verdict": "ready",
            "criteria": {"SC-001": "met", "SC-002": "unmet"},
            "dispositions": {"src/a.py:12": "fixed", "src/b.py:?": "deferred"},
            "note": None, "round": 2,
        })

    def test_verdict_values_outside_the_vocabularies_are_dropped(self):
        self.import_row(self.S, "review-verdict", {
            "verdict": "ready",
            "criteria": {"SC-001": "met", "SC-002": "Met", "SC-003": ["met"]},
            "dispositions": {"a.py:1": "fixed", "b.py:2": "wontfix"},
        })
        verdict = self.position()["verdict"]
        self.assertEqual(verdict["criteria"], {"SC-001": "met"})
        self.assertEqual(verdict["dispositions"], {"a.py:1": "fixed"})

    def test_a_verdict_with_no_maps_has_empty_ones(self):
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {"verdict": "ready"})
        verdict = self.position()["verdict"]
        self.assertEqual((verdict["criteria"], verdict["dispositions"]), ({}, {}))

    def test_the_human_form_names_the_stream(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        proc = self.journal("--db", self.db, "position", "--stream", self.S, rc=OK)
        self.assertIn(self.S, proc.stdout)

    # -- shipgate 0.21.0: verdict note and round, trace, dispositions (ADR 0014) ------

    def test_every_0_20_0_key_is_still_printed(self):
        """FR-007: the additions are new keys; none printed before is renamed or gone."""
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {"verdict": "ready"})
        position = self.position()
        self.assertLessEqual(POSITION_KEYS_0_20_0, set(position))
        self.assertLessEqual(POSITION_VERDICT_KEYS_0_20_0, set(position["verdict"]))

    def test_the_verdict_prints_its_note_and_round(self):
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {"verdict": "not-ready"})
        verdict = self.position()["verdict"]
        self.assertEqual((verdict["note"], verdict["round"]), (None, 1))
        self.append_event(self.S, "review-verdict",
                          {"verdict": "ready", "note": "round two closes it"})
        verdict = self.position()["verdict"]
        self.assertEqual((verdict["note"], verdict["round"]),
                         ("round two closes it", 2))

    def test_the_round_counts_only_verdicts_in_the_vocabulary(self):
        self.import_row(self.S, "review-verdict", {"verdict": "maybe"})
        self.import_row(self.S, "review-verdict", {"verdict": "ready", "note": ["x"]})
        verdict = self.position()["verdict"]
        self.assertEqual((verdict["note"], verdict["round"]), (None, 1))

    def test_the_trace_is_empty_without_rankings_or_deviations(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.append_event(self.S, "deviation", {"note": "a plain deviation"})
        self.assertEqual(self.position()["trace"], {
            "review_ranking": None, "design_ranking": None, "signals_missing": [],
        })

    def test_the_trace_names_the_signals_missing_deviation(self):
        self.append_event(self.S, "flow-started", {"request": "x"})
        self.append_event(self.S, "phase-entered",
                          {"phase": "route-and-map", "skipped": ["workspace"]})
        self.append_event(self.S, "deviation", {"note": "another", "kind": "style-missing"})
        deviation = [e for e in self.events(self.S) if e["type"] == "deviation"][0]
        self.assertEqual(deviation["data"]["kind"], "signals-missing")
        self.assertEqual(self.position()["trace"]["signals_missing"],
                         [{"seq": deviation["seq"], "at": deviation["ts"]}])

    def test_the_trace_takes_the_newest_ranking_carrier(self):
        """A later verdict without `ranking` does not hide an earlier one's."""
        first = {"source": "regex", "files": [{"path": "a.py", "fix": "top"}]}
        second = {"source": "graph", "files": [{"path": "b.py", "fan_in": "high"}]}
        design = {"source": "none", "unavailable": "shallow"}
        self.design(ranking=design)
        carrier_design = self.last()
        self.design()
        self.append_event(self.S, "review-verdict",
                          {"verdict": "not-ready", "ranking": first})
        self.append_event(self.S, "review-verdict",
                          {"verdict": "not-ready", "ranking": second})
        carrier_review = self.last()
        self.append_event(self.S, "review-verdict", {"verdict": "not-ready"})
        trace = self.position()["trace"]
        self.assertEqual(trace["review_ranking"], {
            "seq": carrier_review["seq"], "at": carrier_review["ts"], "ranking": second,
        })
        self.assertEqual(trace["design_ranking"], {
            "seq": carrier_design["seq"], "at": carrier_design["ts"], "ranking": design,
        })
        self.assertEqual(trace["signals_missing"], [])

    def disposition(self, dispositions, round_number=1, **extra):
        self.append_event(self.S, "review-disposition",
                          dict(extra, dispositions=dispositions, round=round_number))
        return self.last()

    def test_the_fold_lets_the_verdict_close_an_interim_state(self):
        """SC-003: two interim `fixing` entries, then a verdict that closes one."""
        first = self.disposition({"src/a.py:12": "fixing"})
        self.disposition({"./src/b.py:?": "fixing", "src/c.py:3": "deferred"},
                         note="interim")
        second = self.last()
        self.verify("pass", "T001")
        # Not ready: `src/b.py:?` stays at fixing, and `append` refuses a ready verdict
        # over it (shipgate 0.23.0).
        self.append_event(self.S, "review-verdict", {
            "verdict": "not-ready", "dispositions": {"./src/a.py:12": "fixed"},
        })
        verdict = self.last()
        self.assertEqual(self.position()["dispositions"], {
            "src/a.py:12": {"state": "fixed", "seq": verdict["seq"],
                            "at": verdict["ts"], "label": None},
            "src/b.py:?": {"state": "fixing", "seq": second["seq"],
                           "at": second["ts"], "label": None},
            "src/c.py:3": {"state": "deferred", "seq": second["seq"],
                           "at": second["ts"], "label": None},
        })
        self.assertEqual(first["data"]["round"], 1)

    def test_a_disposition_after_the_verdict_overrides_it(self):
        """A round-2 `fixing` on a finding round 1 deferred is the current state."""
        self.append_event(self.S, "review-verdict", {
            "verdict": "not-ready", "dispositions": {"src/a.py:12": "deferred"},
        })
        later = self.disposition({"src/a.py:12": "fixing"}, round_number=2)
        self.assertEqual(self.position()["dispositions"], {
            "src/a.py:12": {"state": "fixing", "seq": later["seq"],
                            "at": later["ts"], "label": None},
        })

    def test_an_older_verdicts_closure_holds_until_a_later_event_changes_it(self):
        self.append_event(self.S, "review-verdict", {
            "verdict": "not-ready",
            "dispositions": {"src/old.py:1": "rejected", "src/a.py:12": "deferred"},
        })
        older = self.last()
        self.append_event(self.S, "review-verdict", {
            "verdict": "not-ready", "dispositions": {"src/a.py:12": "fixed"},
        })
        newer = self.last()
        self.assertEqual(self.position()["dispositions"], {
            "src/old.py:1": {"state": "rejected", "seq": older["seq"],
                             "at": older["ts"], "label": None},
            "src/a.py:12": {"state": "fixed", "seq": newer["seq"],
                            "at": newer["ts"], "label": None},
        })

    def test_a_later_rounds_verdict_leaves_earlier_closures_in_place(self):
        """Round-1 `fixing` x2, the round-2 verdict closes both, the round-3 verdict names
        a third key only: the two stay closed, and nothing is open."""
        self.disposition({"src/a.py:1": "fixing", "src/b.py:2": "fixing"})
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {
            "verdict": "ready",
            "dispositions": {"src/a.py:1": "fixed", "src/b.py:2": "fixed"},
        })
        round_two = self.last()
        self.disposition({"src/c.py:3": "fixing"}, round_number=3)
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {
            "verdict": "ready", "dispositions": {"src/c.py:3": "fixed"},
        })
        round_three = self.last()
        dispositions = self.position()["dispositions"]
        self.assertEqual(dispositions, {
            "src/a.py:1": {"state": "fixed", "seq": round_two["seq"],
                           "at": round_two["ts"], "label": None},
            "src/b.py:2": {"state": "fixed", "seq": round_two["seq"],
                           "at": round_two["ts"], "label": None},
            "src/c.py:3": {"state": "fixed", "seq": round_three["seq"],
                           "at": round_three["ts"], "label": None},
        })
        self.assertEqual(
            sum(1 for entry in dispositions.values() if entry["state"] == "fixing"), 0)

    def test_the_fold_drops_values_outside_each_events_vocabulary(self):
        self.import_row(self.S, "review-disposition", {
            "dispositions": {"a.py:1": "fixing", "b.py:2": "wontfix"}, "round": 1,
        })
        self.import_row(self.S, "review-disposition",
                        {"dispositions": ["c.py:3"], "round": 1})
        # `fixing` is no verdict state: the verdict cannot reopen a finding.
        self.import_row(self.S, "review-verdict", {
            "verdict": "ready", "dispositions": {"a.py:1": "fixing", "d.py:4": "fixed"},
        })
        dispositions = self.position()["dispositions"]
        self.assertEqual({k: v["state"] for k, v in dispositions.items()},
                         {"a.py:1": "fixing", "d.py:4": "fixed"})

    # `label` (ADR 0014, amended 0.22.0): the newest label a `review-disposition` gave.
    def test_the_fold_prints_the_newest_label(self):
        self.disposition({"src/a.py:12": "fixing"},
                         labels={"src/a.py:12": "first-name"})
        self.disposition({"src/a.py:12": "fixed"}, round_number=2,
                         labels={"src/a.py:12": "second-name"})
        self.assertEqual(
            self.position()["dispositions"]["src/a.py:12"]["label"], "second-name")

    def test_a_later_event_without_a_label_keeps_the_earlier_one(self):
        self.disposition({"src/a.py:12": "fixing"},
                         labels={"src/a.py:12": "null-guard"})
        self.disposition({"src/a.py:12": "fixed", "src/b.py:3": "fixing"},
                         labels={"src/b.py:3": "retry-loop"})
        self.verify("pass", "T001")
        self.append_event(self.S, "review-verdict", {
            "verdict": "not-ready", "dispositions": {"src/a.py:12": "fixed"},
        })
        dispositions = self.position()["dispositions"]
        self.assertEqual(dispositions["src/a.py:12"]["label"], "null-guard")
        self.assertEqual(dispositions["src/a.py:12"]["state"], "fixed")
        self.assertEqual(dispositions["src/b.py:3"]["label"], "retry-loop")

    def test_a_label_key_drops_its_leading_dot_slash(self):
        self.disposition({"src/a.py:12": "fixing"},
                         labels={"./src/a.py:12": "null-guard"})
        self.disposition({"./src/b.py:?": "deferred"},
                         labels={"src/b.py:?": "flaky-wait"})
        dispositions = self.position()["dispositions"]
        self.assertEqual(dispositions["src/a.py:12"]["label"], "null-guard")
        self.assertEqual(dispositions["src/b.py:?"]["label"], "flaky-wait")

    def test_a_key_without_a_label_prints_null(self):
        self.disposition({"src/a.py:12": "fixing", "src/b.py:3": "rejected"},
                         labels={"src/a.py:12": "null-guard"})
        dispositions = self.position()["dispositions"]
        self.assertIsNone(dispositions["src/b.py:3"]["label"])
        self.assertEqual(set(dispositions["src/b.py:3"]), {"state", "seq", "at", "label"})

    def test_a_label_for_a_key_with_no_state_is_not_printed(self):
        self.disposition({"src/a.py:12": "fixing"},
                         labels={"src/a.py:12": "null-guard", "src/z.py:1": "orphan"})
        self.assertEqual(set(self.position()["dispositions"]), {"src/a.py:12"})

    def test_labels_come_from_review_disposition_only(self):
        """A verdict carries no `labels`; an imported one that does is not read."""
        self.disposition({"src/a.py:12": "fixing"},
                         labels={"src/a.py:12": "null-guard"})
        self.import_row(self.S, "review-verdict", {
            "verdict": "ready", "dispositions": {"src/a.py:12": "fixed"},
            "labels": {"src/a.py:12": "verdict-name"},
        })
        entry = self.position()["dispositions"]["src/a.py:12"]
        self.assertEqual((entry["state"], entry["label"]), ("fixed", "null-guard"))

    def test_the_fold_ignores_a_malformed_imported_label(self):
        self.import_row(self.S, "review-disposition", {
            "dispositions": {"a.py:1": "fixing", "b.py:2": "fixing"}, "round": 1,
            "labels": {"a.py:1": 3, "b.py:2": "  "},
        })
        self.import_row(self.S, "review-disposition", {
            "dispositions": {"c.py:3": "fixing"}, "round": 1, "labels": ["c.py:3"],
        })
        dispositions = self.position()["dispositions"]
        self.assertEqual({k: v["label"] for k, v in dispositions.items()},
                         {"a.py:1": None, "b.py:2": None, "c.py:3": None})

    def test_the_human_form_counts_the_open_dispositions(self):
        self.disposition({"src/a.py:12": "fixing", "src/b.py:3": "rejected"})
        proc = self.journal("--db", self.db, "position", "--stream", self.S, rc=OK)
        self.assertIn("dispositions : 2 (1 open)", proc.stdout)
        self.assertIn("signals-missing 0", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
