#!/usr/bin/env python3
"""Contract + unit tests for shipgate's ``scripts/journal.py``.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests

or directly:

    python3 shipgate/tests/test_journal.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
JOURNAL = TESTS_DIR.parent / "scripts" / "journal.py"

# Exit-code contract (mirrors journal.py --help).
OK = 0
INFRA = 1
USAGE = 2
CONFLICT = 3
GATE = 4
CHECK = 5
IMPORT_CONFLICT = 6


def load_journal_module():
    """Import journal.py directly, for unit tests of its helpers."""
    spec = importlib.util.spec_from_file_location("shipgate_journal", JOURNAL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_journal(args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(JOURNAL)] + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )


class JournalTestCase(unittest.TestCase):
    """Base: a temp project directory with an initialized journal."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".git").mkdir()  # stop sidecar search inside the fixture
        self.db = self.root / "shipgate.db"

    # -- helpers ---------------------------------------------------------

    def journal(self, *args, cwd=None, rc=None):
        proc = run_journal(args, cwd=cwd or self.root)
        if rc is not None:
            self.assertEqual(
                proc.returncode,
                rc,
                msg=(
                    f"expected rc={rc} got {proc.returncode} for args={args!r}\n"
                    f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
                ),
            )
        return proc

    def init_db(self):
        self.journal("--db", self.db, "init", rc=OK)

    def append(self, *args, rc=OK):
        return self.journal("--db", self.db, "append", *args, rc=rc)

    def append_event(self, stream, etype, data=None, *args, rc=OK):
        argv = ["--stream", stream, "--type", etype]
        if data is not None:
            argv += ["--data", json.dumps(data)]
        return self.append(*argv, *args, rc=rc)

    def events(self, stream=None):
        argv = ["--db", self.db, "log", "--json"]
        if stream:
            argv += ["--stream", stream]
        proc = self.journal(*argv, rc=OK)
        return json.loads(proc.stdout)["events"]

    def status_json(self, *args):
        proc = self.journal("--db", self.db, "status", "--json", *args, rc=OK)
        return json.loads(proc.stdout)

    def write(self, relpath, text):
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def sql(self, query, params=()):
        conn = sqlite3.connect(str(self.db))
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# init / schema
# ---------------------------------------------------------------------------


class TestInit(JournalTestCase):
    def test_init_creates_database(self):
        self.journal("--db", self.db, "init", rc=OK)
        self.assertTrue(self.db.exists())

    def test_schema_tables_and_index(self):
        self.init_db()
        names = {r[0] for r in self.sql("SELECT name FROM sqlite_master")}
        self.assertIn("events", names)
        self.assertIn("meta", names)
        self.assertIn("idx_events_stream", names)

    def test_meta_stamps(self):
        self.init_db()
        meta = dict(self.sql("SELECT key, value FROM meta"))
        self.assertEqual(meta["schema_version"], "1")
        self.assertIn("created_at", meta)
        self.assertIn("plugin_version", meta)

    def test_wal_mode_is_set(self):
        self.init_db()
        mode = self.sql("PRAGMA journal_mode")[0][0]
        self.assertEqual(mode.lower(), "wal")

    def test_unique_stream_version(self):
        self.init_db()
        self.append_event("feature/x", "deviation")
        conn = sqlite3.connect(str(self.db))
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO events (stream, version, type, data, ts)"
                    " VALUES ('feature/x', 1, 'note', '{}', 'now')"
                )
                conn.commit()
        finally:
            conn.close()

    def test_data_must_be_valid_json(self):
        self.init_db()
        conn = sqlite3.connect(str(self.db))
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO events (stream, version, type, data, ts)"
                    " VALUES ('feature/x', 1, 'note', 'not json', 'now')"
                )
                conn.commit()
        finally:
            conn.close()

    def test_init_is_idempotent(self):
        self.init_db()
        self.append_event("feature/x", "deviation", {"a": 1})
        self.journal("--db", self.db, "init", rc=OK)
        events = self.events("feature/x")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"], {"a": 1})

    def test_help_documents_exit_codes(self):
        proc = run_journal(["--help"])
        self.assertEqual(proc.returncode, OK)
        for code in ("0", "1", "2", "3", "4", "5", "6"):
            self.assertIn(code, proc.stdout)
        self.assertIn("gate violation", proc.stdout.lower())
        self.assertIn("version conflict", proc.stdout.lower())


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


class TestAppend(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_versions_increment_contiguously(self):
        for _ in range(3):
            self.append_event("feature/x", "deviation")
        versions = [e["version"] for e in self.events("feature/x")]
        self.assertEqual(versions, [1, 2, 3])

    def test_versions_are_per_stream(self):
        self.append_event("feature/a", "deviation")
        self.append_event("feature/b", "deviation")
        self.append_event("feature/a", "deviation")
        self.assertEqual([e["version"] for e in self.events("feature/a")], [1, 2])
        self.assertEqual([e["version"] for e in self.events("feature/b")], [1])

    def test_data_defaults_to_empty_object(self):
        self.append_event("feature/x", "deviation")
        self.assertEqual(self.events("feature/x")[0]["data"], {})

    def test_ts_is_iso8601_utc(self):
        self.append_event("feature/x", "deviation")
        ts = self.events("feature/x")[0]["ts"]
        parsed = datetime.fromisoformat(ts)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_actor_is_stored(self):
        self.append_event("feature/x", "deviation", None, "--actor", "session-7")
        self.assertEqual(self.events("feature/x")[0]["actor"], "session-7")

    def test_json_output_reports_seq_and_version(self):
        proc = self.append("--stream", "feature/x", "--type", "deviation", "--json", rc=OK)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(payload["stream"], "feature/x")

    def test_human_output_reports_seq_and_version(self):
        proc = self.append("--stream", "feature/x", "--type", "deviation", rc=OK)
        self.assertIn("seq", proc.stdout.lower())
        self.assertIn("version", proc.stdout.lower())

    def test_non_object_data_rejected(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "deviation", "--data", "[1,2]", rc=USAGE
        )
        self.assertIn("object", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_scalar_data_rejected(self):
        self.append("--stream", "feature/x", "--type", "deviation", "--data", "42", rc=USAGE)
        self.assertEqual(self.events(), [])

    def test_invalid_json_data_rejected(self):
        self.append(
            "--stream", "feature/x", "--type", "deviation", "--data", "{nope}", rc=USAGE
        )
        self.assertEqual(self.events(), [])

    def test_db_flag_accepted_after_subcommand(self):
        run_journal(
            ["append", "--db", self.db, "--stream", "feature/x", "--type", "deviation"],
            cwd=self.root,
        )
        self.assertEqual(len(self.events("feature/x")), 1)

    # -- conditional append ---------------------------------------------

    def test_expect_matching_version_succeeds(self):
        self.append_event("feature/x", "deviation")
        self.append("--stream", "feature/x", "--type", "deviation", "--expect", "1", rc=OK)
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_expect_zero_on_empty_stream(self):
        self.append("--stream", "feature/x", "--type", "deviation", "--expect", "0", rc=OK)
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_stale_expect_conflicts_and_writes_nothing(self):
        self.append_event("feature/x", "deviation")
        self.append_event("feature/x", "deviation")
        proc = self.append(
            "--stream", "feature/x", "--type", "deviation", "--expect", "1", rc=CONFLICT
        )
        self.assertIn("2", proc.stdout + proc.stderr)
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_stale_expect_json_reports_current_version(self):
        self.append_event("feature/x", "deviation")
        proc = self.append(
            "--stream", "feature/x", "--type", "deviation",
            "--expect", "0", "--json", rc=CONFLICT,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["current_version"], 1)
        self.assertEqual(payload["expected_version"], 0)


class TestConcurrentAppend(JournalTestCase):
    """SC-002: two racing conditional appends -> exactly one winner."""

    def test_exactly_one_winner(self):
        self.init_db()
        argv = [
            sys.executable, str(JOURNAL), "--db", str(self.db), "append",
            "--stream", "feature/race", "--type", "deviation", "--expect", "0",
        ]
        procs = [
            subprocess.Popen(argv + ["--data", json.dumps({"who": who})],
                             cwd=str(self.root), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
            for who in ("a", "b")
        ]
        results = [p.communicate() for p in procs]
        codes = sorted(p.returncode for p in procs)
        self.assertEqual(
            codes, [OK, CONFLICT],
            msg=f"codes={codes} outputs={results}",
        )
        events = self.events("feature/race")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["version"], 1)

    def test_unconditional_concurrent_appends_both_land(self):
        self.init_db()
        argv = [
            sys.executable, str(JOURNAL), "--db", str(self.db), "append",
            "--stream", "feature/race2", "--type", "deviation",
        ]
        procs = [
            subprocess.Popen(argv, cwd=str(self.root), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        outputs = [p.communicate() for p in procs]
        for proc, out in zip(procs, outputs):
            self.assertEqual(proc.returncode, OK, msg=str(out))
        self.assertEqual([e["version"] for e in self.events("feature/race2")], [1, 2])


# ---------------------------------------------------------------------------
# gate validation
# ---------------------------------------------------------------------------


class TestGateClarifyPassed(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_prd_key_is_violation(self):
        proc = self.append_event("feature/x", "clarify-passed", {}, rc=GATE)
        self.assertIn("prd", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_missing_prd_file_is_violation(self):
        self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/nope.md"}, rc=GATE
        )
        self.assertEqual(self.events(), [])

    def test_needs_clarification_marker_is_violation(self):
        """SC-008."""
        self.write("docs/prd/demo.md", "# PRD\n\n- FR-001 [NEEDS CLARIFICATION] which?\n")
        proc = self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/demo.md"}, rc=GATE
        )
        self.assertIn("NEEDS CLARIFICATION", proc.stdout + proc.stderr)
        self.assertEqual(self.events(), [])

    def test_clean_prd_passes(self):
        self.write("docs/prd/demo.md", "# PRD\n\n- FR-001 all settled\n")
        self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/demo.md", "fr_count": 1}
        )
        self.assertEqual(len(self.events()), 1)

    def test_json_gate_violation_payload(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "clarify-passed", "--json", rc=GATE
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"], "gate-violation")
        self.assertTrue(payload["reason"])


class TestGateTaskDone(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_task_id_is_violation(self):
        self.append_event("feature/x", "task-done", {}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_without_verify_run_is_violation(self):
        proc = self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertIn("verify-run", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_failing_verify_run_is_violation(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "fail", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(len(self.events()), 1)

    def test_verify_run_for_other_task_is_violation(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T002"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(len(self.events()), 1)

    def test_verify_run_in_other_stream_is_violation(self):
        self.append_event(
            "feature/y", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(self.events("feature/x"), [])

    def test_passing_verify_run_unblocks(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001", "T002"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.assertEqual(len(self.events("feature/x")), 2)


class TestGatePhaseEntered(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_phase_is_violation(self):
        self.append_event("feature/x", "phase-entered", {}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_unknown_phase_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "vibes"}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_first_phase_workspace_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})

    def test_single_step_forward_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/x", "phase-entered", {"phase": "route-and-map"})

    def test_same_phase_reentry_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})

    def test_backward_transition_allowed(self):
        for phase in ("workspace", "route-and-map", "explore", "clarify",
                      "design", "implement", "review"):
            self.append_event("feature/x", "phase-entered", {"phase": phase})
        self.append_event("feature/x", "phase-entered", {"phase": "implement"})

    def test_forward_jump_without_skipped_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        proc = self.append_event(
            "feature/x", "phase-entered", {"phase": "design"}, rc=GATE
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("skipped", combined.lower())
        self.assertIn("explore", combined)
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_forward_jump_with_skipped_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event(
            "feature/x",
            "phase-entered",
            {"phase": "design", "skipped": ["route-and-map", "explore", "clarify"]},
        )
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_incomplete_skipped_list_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event(
            "feature/x",
            "phase-entered",
            {"phase": "design", "skipped": ["explore"]},
            rc=GATE,
        )
        self.assertEqual(len(self.events("feature/x")), 1)


class TestGateReviewVerdict(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"})

    def test_pass_without_verify_after_last_task_done_is_violation(self):
        proc = self.append_event(
            "feature/x", "review-verdict", {"verdict": "pass"}, rc=GATE
        )
        self.assertIn("verify-run", (proc.stdout + proc.stderr).lower())
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_failing_verdict_is_always_allowed(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "fail"})

    def test_pass_after_fresh_verify_run_allowed(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "review-verdict", {"verdict": "pass"})
        self.assertEqual(len(self.events("feature/x")), 4)


class TestGateMisc(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_unknown_event_type_is_refused(self):
        """An unlisted type is inert — no gate or report would ever read it."""
        proc = self.append_event(
            "feature/x", "totally-new-thing", {"whatever": True}, rc=GATE
        )
        self.assertIn("vocabulary", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_new_type_can_be_minted_deliberately(self):
        self.append_event(
            "feature/x", "totally-new-thing", {"whatever": True}, "--new-type", rc=OK
        )
        event = self.events()[0]
        self.assertEqual(event["type"], "totally-new-thing")
        self.assertTrue(event["data"]["new_type"], "extensions must be visible as such")

    def test_force_does_not_waive_the_vocabulary(self):
        """--force skips gate preconditions; it does not make an inert event readable."""
        self.append_event("feature/x", "decisionn", None, "--force", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_near_miss_names_the_canonical_type(self):
        proc = self.append_event("feature/x", "decision", None, rc=GATE)
        self.assertIn("gate-decision", proc.stderr)

    def test_a_semantic_miss_still_points_at_the_vocabulary(self):
        """`workspace-ready` shares no substring with `flow-started` — the real case
        that string-similarity matching alone would have missed."""
        proc = self.append_event("feature/x", "workspace-ready", None, rc=GATE)
        self.assertIn("vocab", proc.stderr)

    def test_force_writes_despite_violation_and_stamps_audit(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}),
            "--force", "--force-reason", "hotfix, verify ran offline",
            rc=OK,
        )
        self.assertIn("seq", proc.stdout.lower())
        data = self.events("feature/x")[0]["data"]
        self.assertTrue(data["forced"])
        self.assertEqual(data["force_reason"], "hotfix, verify ran offline")
        self.assertEqual(data["task_id"], "T001")

    def test_force_without_reason_stamps_null(self):
        self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}), "--force", rc=OK,
        )
        data = self.events("feature/x")[0]["data"]
        self.assertTrue(data["forced"])
        self.assertIsNone(data["force_reason"])

    def test_force_does_not_bypass_expect(self):
        self.append_event("feature/x", "deviation")
        self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}),
            "--force", "--expect", "0", rc=CONFLICT,
        )
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_force_reason_without_force_is_usage_error(self):
        self.append(
            "--stream", "feature/x", "--type", "deviation",
            "--force-reason", "because", rc=USAGE,
        )
        self.assertEqual(self.events(), [])


# ---------------------------------------------------------------------------
# derived views
# ---------------------------------------------------------------------------


class TestStatus(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.write("docs/prd/demo.md", "# PRD demo\n\nAll settled.\n")
        self.seed()

    def seed(self):
        s = "feature/demo"
        self.append_event(s, "flow-started", {"request": "build it", "branch": "feat/demo"})
        for phase in ("workspace", "route-and-map", "explore", "clarify"):
            self.append_event(s, "phase-entered", {"phase": phase})
        self.append_event(s, "gate-decision", {
            "gate": "clarify", "question": "storage engine", "decision": "sqlite",
            "mode": "executive", "rationale": "no server dependency",
        })
        self.append_event(s, "clarify-passed", {"prd": "docs/prd/demo.md", "fr_count": 15})
        self.append_event(s, "phase-entered", {"phase": "design"})
        self.append_event(s, "design-queued", {"issue": "#8311", "assumes": "schema v1"})
        self.append_event(s, "verify-run", {
            "outcome": "pass", "scope": "unit", "task_ids": ["T001"],
            "commands": [{"cmd": "pytest", "exit": 0}],
        })
        self.append_event(s, "task-done", {"task_id": "T001"})

    def test_current_phase(self):
        feature = self.status_json()["features"][0]
        self.assertEqual(feature["stream"], "feature/demo")
        self.assertEqual(feature["phase"], "design")
        self.assertIsNotNone(feature["phase_entered_at"])

    def test_last_event_and_version(self):
        feature = self.status_json()["features"][0]
        self.assertEqual(feature["last_event"]["type"], "task-done")
        self.assertEqual(feature["version"], 11)

    def test_gate_decisions_recorded(self):
        feature = self.status_json()["features"][0]
        self.assertEqual(len(feature["gate_decisions"]), 1)
        self.assertEqual(feature["gate_decisions"][0]["decision"], "sqlite")
        self.assertEqual(feature["gate_decisions"][0]["mode"], "executive")

    def test_open_designs(self):
        feature = self.status_json()["features"][0]
        self.assertEqual([d["issue"] for d in feature["open_designs"]], ["#8311"])

    def test_committed_design_closes_the_queue_entry(self):
        self.append_event("feature/demo", "design-committed", {
            "issue": "#8311", "worklog": "docs/prd/demo.worklog.md", "adrs": [],
        })
        feature = self.status_json()["features"][0]
        self.assertEqual(feature["open_designs"], [])

    def test_invalidated_design_closes_the_queue_entry(self):
        self.append_event("feature/demo", "design-invalidated", {"issue": "#8311"})
        self.assertEqual(self.status_json()["features"][0]["open_designs"], [])

    def test_verify_and_tasks(self):
        feature = self.status_json()["features"][0]
        self.assertEqual(feature["last_verify"]["outcome"], "pass")
        self.assertEqual(feature["tasks_done"], 1)
        self.assertEqual(feature["task_ids"], ["T001"])

    def test_feature_filter(self):
        self.append_event("feature/other", "phase-entered", {"phase": "workspace"})
        payload = self.status_json("--feature", "demo")
        self.assertEqual(len(payload["features"]), 1)
        self.assertEqual(payload["features"][0]["stream"], "feature/demo")

    def test_non_feature_streams_are_excluded(self):
        self.append_event("shipgate", "setup-completed", {})
        streams = [f["stream"] for f in self.status_json()["features"]]
        self.assertEqual(streams, ["feature/demo"])

    def test_human_render(self):
        proc = self.journal("--db", self.db, "status", rc=OK)
        self.assertIn("feature/demo", proc.stdout)
        self.assertIn("design", proc.stdout)
        self.assertIn("#8311", proc.stdout)


class TestLogAndStreams(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        for i in range(5):
            self.append_event("feature/x", "deviation", {"i": i})
        self.append_event("feature/y", "deviation", {"i": 0})

    def test_log_is_newest_last(self):
        events = self.events("feature/x")
        self.assertEqual([e["data"]["i"] for e in events], [0, 1, 2, 3, 4])

    def test_log_limit_keeps_the_newest(self):
        proc = self.journal(
            "--db", self.db, "log", "--stream", "feature/x", "--limit", "2", "--json",
            rc=OK,
        )
        events = json.loads(proc.stdout)["events"]
        self.assertEqual([e["data"]["i"] for e in events], [3, 4])

    def test_log_human_render(self):
        proc = self.journal("--db", self.db, "log", "--stream", "feature/y", rc=OK)
        self.assertIn("deviation", proc.stdout)

    def test_streams_counts_and_max_version(self):
        proc = self.journal("--db", self.db, "streams", "--json", rc=OK)
        streams = {s["stream"]: s for s in json.loads(proc.stdout)["streams"]}
        self.assertEqual(streams["feature/x"]["events"], 5)
        self.assertEqual(streams["feature/x"]["max_version"], 5)
        self.assertEqual(streams["feature/y"]["events"], 1)


# ---------------------------------------------------------------------------
# check (Stop-hook gate)
# ---------------------------------------------------------------------------


WORKLOG_TEMPLATE = """---
type: worklog
---

# Worklog: demo

# Design

Prose that mentions - [x] T999 outside the build plan.

# Build Plan

{tasks}

## Deviations
- none
"""


class TestCheck(JournalTestCase):
    SESSION = "sess-1"

    def setUp(self):
        super().setUp()
        self.init_db()

    def worklog(self, tasks):
        return self.write(
            "docs/prd/demo.worklog.md", WORKLOG_TEMPLATE.format(tasks=tasks)
        )

    def artifact_written(self, path, stream="feature/demo", session=None):
        self.append_event(stream, "artifact-written", {
            "path": path, "tool": "Write", "session": session or self.SESSION,
        })

    def check(self, rc=None, session=None):
        proc = self.journal(
            "--db", self.db, "check", "--session", session or self.SESSION, "--json",
            rc=rc,
        )
        return proc

    def test_ticked_task_without_task_done_blocks(self):
        """SC-007."""
        self.worklog("- [x] T001 — first\n- [ ] T002 — second")
        self.append_event("feature/demo", "verify-run", {
            "outcome": "pass", "task_ids": ["T001"],
        })
        self.artifact_written("docs/prd/demo.worklog.md")
        proc = self.check(rc=CHECK)
        findings = json.loads(proc.stdout)["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["missing"], "task-done")
        self.assertIn("T001", findings[0]["detail"])
        self.assertIn("T001", findings[0]["suggested_command"])

    def test_suggested_command_resolves_the_finding(self):
        self.worklog("- [x] T001 — first")
        self.append_event("feature/demo", "verify-run", {
            "outcome": "pass", "task_ids": ["T001"],
        })
        self.artifact_written("docs/prd/demo.worklog.md")
        finding = json.loads(self.check(rc=CHECK).stdout)["findings"][0]

        fixed = subprocess.run(
            finding["suggested_command"], shell=True, cwd=str(self.root),
            capture_output=True, text=True,
        )
        self.assertEqual(fixed.returncode, OK, msg=fixed.stderr)
        self.check(rc=OK)

    def test_clean_session_passes(self):
        self.worklog("- [x] T001 — first")
        self.append_event("feature/demo", "verify-run", {
            "outcome": "pass", "task_ids": ["T001"],
        })
        self.append_event("feature/demo", "task-done", {"task_id": "T001"},
                          "--actor", self.SESSION)
        self.artifact_written("docs/prd/demo.worklog.md")
        self.check(rc=OK)

    def test_worklog_from_an_untracked_flow_is_not_gated(self):
        """A worklog the journal has never tracked must not block a stop.

        The realistic trigger is a synced or legacy artifact: a vault bisync touches an
        old finished worklog whose ticked boxes predate the journal entirely. Gating on
        it would block a session over work the user never did here.
        """
        self.worklog("- [x] T001 — first\n- [x] T002 — second")
        # Exactly what the hooks record: capture on the meta stream, nothing else.
        self.artifact_written("docs/prd/demo.worklog.md", stream="shipgate")
        self.check(rc=OK)

    def test_capture_alone_does_not_make_a_flow_tracked(self):
        """artifact-written is the hook's own footprint, not evidence of a flow."""
        self.worklog("- [x] T001 — first")
        self.artifact_written("docs/prd/demo.worklog.md", stream="feature/demo")
        self.check(rc=OK)

    def test_a_tracked_flow_is_still_gated(self):
        """The fix must not blunt the gate where it matters — one real event is enough."""
        self.worklog("- [x] T001 — first")
        # `workspace` is the first declared phase, so it needs no skip declaration.
        self.append_event("feature/demo", "phase-entered", {"phase": "workspace"})
        self.artifact_written("docs/prd/demo.worklog.md", stream="shipgate")
        findings = json.loads(self.check(rc=CHECK).stdout)["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["missing"], "task-done")

    def test_unticked_boxes_are_not_findings(self):
        self.worklog("- [ ] T001 — first\n- [ ] T002 — second")
        self.artifact_written("docs/prd/demo.worklog.md")
        self.check(rc=OK)

    def test_ticks_outside_build_plan_are_ignored(self):
        self.worklog("- [ ] T001 — first")
        self.artifact_written("docs/prd/demo.worklog.md")
        proc = self.check(rc=OK)
        self.assertNotIn("T999", proc.stdout)

    def test_session_with_no_artifacts_passes(self):
        self.check(rc=OK, session="nothing-happened")

    def test_prd_written_at_clarify_without_gate_decision_blocks(self):
        self.write("docs/prd/demo.md", "# PRD\n")
        self.append_event("feature/demo", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/demo", "phase-entered", {
            "phase": "clarify", "skipped": ["route-and-map", "explore"],
        })
        self.artifact_written("docs/prd/demo.md")
        findings = json.loads(self.check(rc=CHECK).stdout)["findings"]
        self.assertEqual([f["missing"] for f in findings], ["gate-decision"])
        self.assertIn("gate-decision", findings[0]["suggested_command"])

    def test_prd_with_gate_decision_in_session_passes(self):
        self.write("docs/prd/demo.md", "# PRD\n")
        self.append_event("feature/demo", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/demo", "phase-entered", {
            "phase": "clarify", "skipped": ["route-and-map", "explore"],
        })
        self.append_event("feature/demo", "gate-decision", {
            "gate": "clarify", "question": "q", "decision": "d", "mode": "ask",
        }, "--actor", self.SESSION)
        self.artifact_written("docs/prd/demo.md")
        self.check(rc=OK)

    def test_task_done_without_verify_run_blocks(self):
        self.append_event("feature/demo", "task-done", {"task_id": "T001"},
                          "--force", "--actor", self.SESSION)
        findings = json.loads(self.check(rc=CHECK).stdout)["findings"]
        self.assertEqual([f["missing"] for f in findings], ["verify-run"])
        self.assertIn("T001", findings[0]["detail"])
        self.assertIn("verify-run", findings[0]["suggested_command"])

    def test_all_findings_reported_in_one_round(self):
        # feature/demo: T001 forced task-done (no verify-run), T002 ticked with no
        # task-done. feature/other: PRD written at clarify with no gate-decision.
        self.worklog("- [x] T001 — first\n- [x] T002 — second\n- [ ] T003 — third")
        self.append_event("feature/demo", "task-done", {"task_id": "T001"},
                          "--force", "--actor", self.SESSION)
        self.artifact_written("docs/prd/demo.worklog.md")

        self.write("docs/prd/other.md", "# PRD other\n")
        self.append_event("feature/other", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/other", "phase-entered", {
            "phase": "clarify", "skipped": ["route-and-map", "explore"],
        })
        self.artifact_written("docs/prd/other.md", stream="feature/other")

        findings = json.loads(self.check(rc=CHECK).stdout)["findings"]
        missing = sorted(f["missing"] for f in findings)
        self.assertEqual(missing, ["gate-decision", "task-done", "verify-run"])
        detail_blob = " ".join(f["detail"] for f in findings)
        self.assertIn("T002", detail_blob)
        self.assertIn("T001", detail_blob)

    def test_human_output_lists_findings(self):
        self.worklog("- [x] T001 — first")
        # A real flow event is what makes this stream tracked; capture alone no longer
        # is, so the gate would otherwise (correctly) stay silent here.
        self.append_event("feature/demo", "phase-entered", {"phase": "workspace"})
        self.artifact_written("docs/prd/demo.worklog.md")
        proc = self.journal(
            "--db", self.db, "check", "--session", self.SESSION, rc=CHECK
        )
        self.assertIn("T001", proc.stdout + proc.stderr)


class TestParseTickedTasks(unittest.TestCase):
    """Unit test of the worklog parser, no subprocess needed."""

    def setUp(self):
        self.journal = load_journal_module()

    def test_only_build_plan_ticks(self):
        text = WORKLOG_TEMPLATE.format(
            tasks="- [x] T001 — a\n- [ ] T002 — b\n- [X] T010 — c"
        )
        self.assertEqual(
            self.journal.parse_ticked_tasks(text), ["T001", "T010"]
        )

    def test_no_build_plan_section_scans_whole_file(self):
        self.assertEqual(
            self.journal.parse_ticked_tasks("- [x] T001 — a\n"), ["T001"]
        )

    def test_phase_order_is_the_declared_one(self):
        self.assertEqual(
            self.journal.PHASE_ORDER,
            ["workspace", "route-and-map", "explore", "clarify",
             "design", "implement", "review", "capture"],
        )


# ---------------------------------------------------------------------------
# doctor / export / import
# ---------------------------------------------------------------------------


class TestDoctor(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feature/x", "deviation")

    def test_healthy_db_passes(self):
        proc = self.journal("--db", self.db, "doctor", rc=OK)
        out = proc.stdout.lower()
        self.assertIn("ok", out)
        self.assertIn("wal", out)

    def test_json_report(self):
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        report = json.loads(proc.stdout)
        self.assertEqual(report["integrity_check"], "ok")
        self.assertEqual(report["journal_mode"], "wal")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["pending_migrations"], [])
        self.assertFalse(report["sidecar"]["found"])

    def test_reports_sidecar_agreement_through_symlinked_parents(self):
        link = Path(tempfile.mkdtemp()) / "link"
        self.addCleanup(lambda: link.parent.exists() and os.rmdir(link.parent))
        os.symlink(str(self.root), str(link))
        self.addCleanup(lambda: os.unlink(str(link)))
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "shipgate.json").write_text(
            json.dumps({"version": 1, "db": str(self.db)}), encoding="utf-8"
        )
        proc = self.journal("--db", link / "shipgate.db", "doctor", "--json", rc=OK)
        report = json.loads(proc.stdout)
        self.assertTrue(report["sidecar"]["found"])
        self.assertTrue(report["sidecar"]["agrees"], msg=report)

    def test_reports_sidecar_disagreement(self):
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "shipgate.json").write_text(
            json.dumps({"version": 1, "db": ".claude/elsewhere.db"}), encoding="utf-8"
        )
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        report = json.loads(proc.stdout)
        self.assertTrue(report["sidecar"]["found"])
        self.assertFalse(report["sidecar"]["agrees"])


class TestExportImport(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.write("docs/prd/demo.md", "# PRD demo\n")
        s = "feature/demo"
        self.append_event(s, "phase-entered", {"phase": "workspace"})
        self.append_event(s, "gate-decision", {
            "gate": "clarify", "question": "q", "decision": "d", "mode": "ask",
        })
        self.append_event(s, "verify-run", {"outcome": "pass", "task_ids": ["T001"]})
        self.append_event(s, "task-done", {"task_id": "T001"}, "--actor", "sess")
        self.append_event("shipgate", "setup-completed", {})
        self.dump = self.root / "dump.jsonl"

    def do_export(self, *args):
        proc = self.journal("--db", self.db, "export", *args, rc=OK)
        self.dump.write_text(proc.stdout, encoding="utf-8")
        return proc.stdout

    def test_export_is_one_object_per_line_in_seq_order(self):
        lines = [json.loads(l) for l in self.do_export().splitlines() if l.strip()]
        self.assertEqual([e["seq"] for e in lines], [1, 2, 3, 4, 5])
        self.assertEqual(lines[0]["data"], {"phase": "workspace"})

    def test_export_stream_filter(self):
        out = self.do_export("--stream", "shipgate")
        lines = [json.loads(l) for l in out.splitlines() if l.strip()]
        self.assertEqual([e["type"] for e in lines], ["setup-completed"])

    def test_roundtrip_reproduces_status(self):
        """SC-006."""
        self.do_export()
        other = self.root / "other.db"
        self.journal("--db", other, "init", rc=OK)
        self.journal("--db", other, "import", self.dump, rc=OK)

        before = self.journal("--db", self.db, "status", "--json", rc=OK).stdout
        after = self.journal("--db", other, "status", "--json", rc=OK).stdout
        self.assertEqual(json.loads(before), json.loads(after))

    def test_import_reports_counts(self):
        self.do_export()
        other = self.root / "other.db"
        self.journal("--db", other, "init", rc=OK)
        proc = self.journal("--db", other, "import", self.dump, "--json", rc=OK)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["imported"], 5)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["conflicts"], 0)

    def test_reimport_is_a_noop(self):
        self.do_export()
        other = self.root / "other.db"
        self.journal("--db", other, "init", rc=OK)
        self.journal("--db", other, "import", self.dump, rc=OK)
        first = self.journal("--db", other, "log", "--json", rc=OK).stdout

        proc = self.journal("--db", other, "import", self.dump, "--json", rc=OK)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["imported"], 0)
        self.assertEqual(summary["skipped"], 5)
        second = self.journal("--db", other, "log", "--json", rc=OK).stdout
        self.assertEqual(json.loads(first), json.loads(second))

    def test_conflicting_row_is_reported_and_not_overwritten(self):
        self.do_export()
        other = self.root / "other.db"
        self.journal("--db", other, "init", rc=OK)
        self.journal("--db", other, "import", self.dump, rc=OK)

        lines = [json.loads(l) for l in self.dump.read_text().splitlines() if l.strip()]
        lines[0]["data"] = {"phase": "capture"}
        conflicted = self.root / "conflicted.jsonl"
        conflicted.write_text(
            "\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8"
        )

        proc = self.journal("--db", other, "import", conflicted, "--json",
                            rc=IMPORT_CONFLICT)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["conflicts"], 1)
        self.assertEqual(summary["imported"], 0)

        events = json.loads(
            self.journal("--db", other, "log", "--stream", "feature/demo", "--json",
                         rc=OK).stdout
        )["events"]
        self.assertEqual(events[0]["data"], {"phase": "workspace"})

    def test_import_does_not_run_gate_validation(self):
        """History replay must not be re-judged by today's gates."""
        raw = self.root / "raw.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/z", "version": 1, "type": "task-done",
            "data": {"task_id": "T001"}, "ts": "2026-08-20T10:00:00+00:00",
            "actor": None,
        }) + "\n", encoding="utf-8")
        other = self.root / "other.db"
        self.journal("--db", other, "init", rc=OK)
        self.journal("--db", other, "import", raw, rc=OK)
        events = json.loads(
            self.journal("--db", other, "log", "--json", rc=OK).stdout
        )["events"]
        self.assertEqual(len(events), 1)

    def test_import_rejects_malformed_line(self):
        raw = self.root / "raw.jsonl"
        raw.write_text("{not json}\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=USAGE)

    def test_import_missing_file_is_infra_error(self):
        self.journal("--db", self.db, "import", self.root / "nope.jsonl", rc=INFRA)


# ---------------------------------------------------------------------------
# work streams
# ---------------------------------------------------------------------------


class TestWorkStreamRecognition(JournalTestCase):
    """Any stream that isn't the tool's own is work worth reporting.

    A real bug flow named its stream after the branch — `fix/8744-vessel-rate` — and the
    old `feature/` prefix filter hid all ten of its events from `status`, which reported
    "No feature streams recorded" while the journal was in fact full.
    """

    def setUp(self):
        super().setUp()
        self.init_db()

    def test_a_branch_named_stream_is_reported(self):
        self.append_event("fix/8744-vessel-rate", "flow-started", {"branch": "fix/8744"})
        streams = [f["stream"] for f in self.status_json()["features"]]
        self.assertIn("fix/8744-vessel-rate", streams)

    def test_the_meta_stream_is_not_reported_as_work(self):
        self.append_event("shipgate", "setup-completed", {"mode": "create"})
        self.assertEqual(self.status_json()["features"], [])

    def test_watch_streams_are_not_reported_as_work(self):
        self.append_event("watch/group-project!42", "baseline", {"iid": 42})
        self.assertEqual(self.status_json()["features"], [])

    def test_a_feature_stream_is_still_reported(self):
        self.append_event("feature/demo", "flow-started", {})
        streams = [f["stream"] for f in self.status_json()["features"]]
        self.assertEqual(streams, ["feature/demo"])

    def test_filtering_matches_a_branch_named_stream(self):
        self.append_event("fix/8744-vessel-rate", "flow-started", {})
        self.append_event("feature/other", "flow-started", {})
        got = [f["stream"] for f in self.status_json("--feature", "8744")["features"]]
        self.assertEqual(got, ["fix/8744-vessel-rate"])


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------


class TestDecisionRendering(JournalTestCase):
    """Real history carries drifted payload shapes; it must still read as history."""

    def setUp(self):
        super().setUp()
        self.module = load_journal_module()

    def test_canonical_shape(self):
        rendered = self.module._render_decision({
            "gate": "design", "question": "Cascade or throw?",
            "decision": "Cascade", "mode": "executive",
        })
        self.assertEqual(rendered, "[design] Cascade or throw? -> Cascade (executive)")

    def test_answer_only_payload_is_not_rendered_as_none(self):
        rendered = self.module._render_decision({"gate": "design", "chosen": "Cascade"})
        self.assertEqual(rendered, "[design] Cascade")
        self.assertNotIn("None", rendered)

    def test_unrecognized_payload_falls_back_to_its_contents(self):
        rendered = self.module._render_decision({"why": "it was cheaper"})
        self.assertIn("it was cheaper", rendered)
        self.assertNotIn("None", rendered)

    def test_empty_payload_says_so_plainly(self):
        self.assertNotIn("None", self.module._render_decision({}))


class TestVocabCommand(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_lists_the_canonical_types(self):
        out = self.journal("--db", self.db, "vocab", rc=OK).stdout
        for expected in ("gate-decision", "verify-run", "debug-root-cause", "task-done"):
            self.assertIn(expected, out)

    def test_json_form_is_a_name_to_purpose_map(self):
        data = json.loads(self.journal("--db", self.db, "vocab", "--json", rc=OK).stdout)
        self.assertIn("gate-decision", data)
        self.assertIsInstance(data["gate-decision"], str)

    def test_every_type_the_skills_document_is_in_the_vocabulary(self):
        """Guards the drift that caused this: prose names must be appendable."""
        module = load_journal_module()
        skills = TESTS_DIR.parent / "skills"
        documented = set()
        for skill in skills.rglob("SKILL.md"):
            for line in skill.read_text(encoding="utf-8").splitlines():
                if "--type" in line:
                    parts = line.split("--type")[1].split()
                    if parts:
                        documented.add(parts[0].strip("\\ '\"`"))
        self.assertTrue(documented, "expected the skills to document some event types")
        unknown = sorted(t for t in documented if t not in module.EVENT_VOCABULARY)
        self.assertEqual(unknown, [], f"skills document types append would refuse: {unknown}")


# ---------------------------------------------------------------------------
# ledger visibility
# ---------------------------------------------------------------------------


class TestLedgerInStatus(JournalTestCase):
    """`status` surfaces untriaged ledger entries.

    The knowledge-base skill already asks the model to nudge at ~15+ unpromoted
    entries — a count a script gets right every time and a model notices erratically.
    Since the session-start hook injects `status`, putting the count there is what makes
    that documented behaviour mechanical.
    """

    def make_sidecar(self, ledger=None):
        claude = self.root / ".claude"
        claude.mkdir(exist_ok=True)
        config = {
            "version": 1,
            "db": ".claude/shipgate.db",
            "artifact_homes": {
                "prd": "docs/prd/*.md",
                "adr": "docs/adr/*.md",
                "worklog": "docs/prd/*.worklog.md",
            },
            "enforce": {"stop_gate": True, "auto_capture": True},
        }
        if ledger is not None:
            config["ledger"] = ledger
        (claude / "shipgate.json").write_text(json.dumps(config), encoding="utf-8")

    def status(self):
        self.journal("init", rc=OK)
        return json.loads(self.journal("status", "--json", rc=OK).stdout)

    def test_counts_untriaged_entries(self):
        self.make_sidecar(ledger="docs/ledger.md")
        self.write("docs/ledger.md", (
            "# Ledger\n\n"
            "- 2026-08-20 gotcha: the dump script rewrites the whole file\n"
            "- 2026-08-20 style: prefer the repo helper over a raw cast\n"
            "* 2026-08-19 decision: date-keyed ADRs, not sequential\n"
        ))
        ledger = self.status()["ledger"]
        self.assertEqual(ledger["entries"], 3)
        self.assertEqual(ledger["path"], "docs/ledger.md")
        self.assertFalse(ledger["nudge"])

    def test_headings_and_blank_lines_are_not_entries(self):
        self.make_sidecar(ledger="docs/ledger.md")
        self.write("docs/ledger.md", "# Ledger\n\nSome preamble prose.\n\n")
        self.assertEqual(self.status()["ledger"]["entries"], 0)

    def test_an_empty_ledger_is_the_healthy_state(self):
        self.make_sidecar(ledger="docs/ledger.md")
        self.write("docs/ledger.md", "")
        ledger = self.status()["ledger"]
        self.assertEqual(ledger["entries"], 0)
        self.assertFalse(ledger["nudge"])

    def test_nudges_past_the_documented_threshold(self):
        self.make_sidecar(ledger="docs/ledger.md")
        self.write("docs/ledger.md", "".join(
            f"- 2026-08-20 entry {i}\n" for i in range(15)
        ))
        ledger = self.status()["ledger"]
        self.assertEqual(ledger["entries"], 15)
        self.assertTrue(ledger["nudge"], "15+ is the skill's documented nudge threshold")

    def test_defaults_when_the_sidecar_omits_it(self):
        self.make_sidecar()
        self.write("docs/ledger.md", "- 2026-08-20 one entry\n")
        self.assertEqual(self.status()["ledger"]["entries"], 1)

    def test_a_missing_ledger_file_is_not_an_error(self):
        self.make_sidecar(ledger="docs/ledger.md")
        ledger = self.status()["ledger"]
        self.assertEqual(ledger["entries"], 0)
        self.assertFalse(ledger["exists"])

    def test_human_output_mentions_the_ledger_only_when_it_has_entries(self):
        self.make_sidecar(ledger="docs/ledger.md")
        self.write("docs/ledger.md", "- 2026-08-20 something worth keeping\n")
        self.journal("init", rc=OK)
        with_entries = self.journal("status", rc=OK).stdout
        self.assertIn("ledger", with_entries.lower())

        self.write("docs/ledger.md", "")
        self.assertNotIn("ledger", self.journal("status", rc=OK).stdout.lower())


# ---------------------------------------------------------------------------
# db resolution
# ---------------------------------------------------------------------------


class TestDbResolution(JournalTestCase):
    def make_sidecar(self, db_rel=".claude/shipgate.db"):
        claude = self.root / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "shipgate.json").write_text(json.dumps({
            "version": 1,
            "db": db_rel,
            "artifact_homes": {
                "prd": "docs/prd/*.md",
                "adr": "docs/adr/*.md",
                "worklog": "docs/prd/*.worklog.md",
            },
            "enforce": {"stop_gate": True, "auto_capture": True},
        }), encoding="utf-8")
        return claude / "shipgate.json"

    def test_sidecar_is_honored(self):
        self.make_sidecar()
        self.journal("init", rc=OK)
        self.assertTrue((self.root / ".claude" / "shipgate.db").exists())
        self.journal("append", "--stream", "feature/x", "--type", "deviation", rc=OK)

    def test_sidecar_found_from_a_nested_directory(self):
        self.make_sidecar()
        self.journal("init", rc=OK)
        nested = self.root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        self.journal("append", "--stream", "feature/x", "--type", "deviation",
                     cwd=nested, rc=OK)
        proc = self.journal("log", "--json", cwd=nested, rc=OK)
        self.assertEqual(len(json.loads(proc.stdout)["events"]), 1)

    def test_sidecar_relative_path_resolves_against_project_dir(self):
        self.make_sidecar("journals/flow.db")
        self.journal("init", rc=OK)
        self.assertTrue((self.root / "journals" / "flow.db").exists())

    def test_explicit_db_flag_wins_over_sidecar(self):
        self.make_sidecar()
        self.journal("init", rc=OK)
        self.journal("--db", self.db, "init", rc=OK)
        self.journal("--db", self.db, "append", "--stream", "feature/x",
                     "--type", "deviation", rc=OK)
        sidecar_db = self.root / ".claude" / "shipgate.db"
        conn = sqlite3.connect(str(sidecar_db))
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
        finally:
            conn.close()

    def test_missing_db_is_infra_error(self):
        proc = self.journal("log", rc=INFRA)
        self.assertIn("not found", (proc.stdout + proc.stderr).lower())

    def test_explicit_missing_db_is_infra_error(self):
        self.journal("--db", self.root / "nope.db", "status", rc=INFRA)

    def test_malformed_sidecar_is_infra_error(self):
        claude = self.root / ".claude"
        claude.mkdir()
        (claude / "shipgate.json").write_text("{ nope", encoding="utf-8")
        proc = self.journal("status", rc=INFRA)
        self.assertIn("sidecar", (proc.stdout + proc.stderr).lower())

    def test_default_db_path_when_no_sidecar(self):
        self.journal("init", rc=OK)
        self.assertTrue((self.root / ".claude" / "shipgate.db").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
