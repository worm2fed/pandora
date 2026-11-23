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
from unittest import mock
from datetime import datetime, timedelta, timezone
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


# The variable Claude Code sets in every shell it starts (journal.py SESSION_ENV). The
# suite runs inside such shells too, so a test sees it only when it sets it itself.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def run_journal(args, cwd=None, env=None):
    if env is None:
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
    return subprocess.run(
        [sys.executable, str(JOURNAL)] + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )



def insert_legacy_row(db, stream, etype, data, actor):
    """Write one row as an older release wrote it, past every append check: a read go
    that untagged 0.28.0 accepted (ADR 0023, amendment A4). Returns its seq."""
    conn = sqlite3.connect(str(db))
    try:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM events WHERE stream = ?", (stream,)
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO events (stream, version, type, data, ts, actor) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (stream, version, etype, json.dumps(data, sort_keys=True), _recent_ts(), actor),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def legacy_read_go(gate, witness):
    """The payload of a read go as 0.28.0 wrote it."""
    return {"gate": gate, "question": "q", "decision": gate, "mode": "ask",
            "raised_by": "user", "source": "read", "witness": witness,
            "words": "it can go"}


def _recent_ts() -> str:
    """An ISO timestamp one hour ago — for fixtures that must render as live, not dormant."""
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

class JournalTestCase(unittest.TestCase):
    """Base: a temp project directory with an initialized journal."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "shipgate.db"

    # -- helpers ---------------------------------------------------------

    def journal(self, *args, cwd=None, rc=None, session_env=None):
        env = None
        if session_env is not None:
            env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
            env[SESSION_ENV] = session_env
        proc = run_journal(args, cwd=cwd or self.root, env=env)
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

    def store_legacy_session(self, session_id):
        """The `meta.current_session` row that an older SessionStart hook left in a
        journal (ADR 0003). No append reads it (#46), and nothing writes it since #51."""
        conn = sqlite3.connect(str(self.db))
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) "
                    "VALUES ('current_session', ?)", (session_id,),
                )
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
        self.append_event("feature/x", "flow-suspended")
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
        self.append_event("feature/x", "flow-suspended", {"a": 1})
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
            self.append_event("feature/x", "flow-suspended")
        versions = [e["version"] for e in self.events("feature/x")]
        self.assertEqual(versions, [1, 2, 3])

    def test_versions_are_per_stream(self):
        self.append_event("feature/a", "flow-suspended")
        self.append_event("feature/b", "flow-suspended")
        self.append_event("feature/a", "flow-suspended")
        self.assertEqual([e["version"] for e in self.events("feature/a")], [1, 2])
        self.assertEqual([e["version"] for e in self.events("feature/b")], [1])

    def test_data_defaults_to_empty_object(self):
        self.append_event("feature/x", "flow-suspended")
        self.assertEqual(self.events("feature/x")[0]["data"], {})

    def test_ts_is_iso8601_utc(self):
        self.append_event("feature/x", "flow-suspended")
        ts = self.events("feature/x")[0]["ts"]
        parsed = datetime.fromisoformat(ts)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_actor_is_stored(self):
        self.append_event(
            "feature/x", "flow-suspended", None, "--actor", "worker@session-7"
        )
        self.assertEqual(self.events("feature/x")[0]["actor"], "worker@session-7")

    def test_json_output_reports_seq_and_version(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "flow-suspended", "--json", rc=OK
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["seq"], 1)
        self.assertEqual(payload["stream"], "feature/x")

    def test_json_output_reports_the_version_it_was_checked_against(self):
        """An implied phase-entered moves the version by two, so N+1 is a bad guess."""
        self.append_event("feature/x", "flow-suspended")
        proc = self.append(
            "--stream", "feature/x", "--type", "verify-run",
            "--data", json.dumps({"outcome": "pass", "task_ids": ["T001"]}),
            "--expect", "1", "--json", rc=OK,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["version_before"], 1)
        self.assertEqual(payload["version"], 3)

    def test_expect_help_warns_that_a_phase_owning_event_moves_two(self):
        proc = self.journal("--db", self.db, "append", "--help", rc=OK)
        # argparse may hyphen-wrap `phase-entered`, so assert on unbreakable phrases.
        helptext = " ".join(proc.stdout.split())
        self.assertIn("advance by two", helptext)
        self.assertIn("version_before", helptext)

    def test_human_output_reports_seq_and_version(self):
        proc = self.append("--stream", "feature/x", "--type", "flow-suspended", rc=OK)
        self.assertIn("seq", proc.stdout.lower())
        self.assertIn("version", proc.stdout.lower())

    def test_non_object_data_rejected(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "flow-suspended",
            "--data", "[1,2]", rc=USAGE,
        )
        self.assertIn("object", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_scalar_data_rejected(self):
        self.append(
            "--stream", "feature/x", "--type", "flow-suspended", "--data", "42",
            rc=USAGE,
        )
        self.assertEqual(self.events(), [])

    def test_invalid_json_data_rejected(self):
        self.append(
            "--stream", "feature/x", "--type", "flow-suspended",
            "--data", "{nope}", rc=USAGE,
        )
        self.assertEqual(self.events(), [])

    def test_a_nan_literal_in_data_is_a_usage_error(self):
        """Python's json reads NaN; nothing that later reads the row back does."""
        proc = self.append(
            "--stream", "feature/x", "--type", "deviation",
            "--data", '{"note":"x","n":NaN}', rc=USAGE,
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("NaN", combined)
        self.assertNotIn("Traceback", combined)
        self.assertEqual(self.events(), [])

    def test_an_infinity_literal_in_data_is_a_usage_error(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "deviation",
            "--data", '{"note":"x","n":-Infinity}', rc=USAGE,
        )
        self.assertIn("Infinity", proc.stdout + proc.stderr)
        self.assertEqual(self.events(), [])

    def test_data_too_deeply_nested_is_a_usage_error(self):
        """Unit-level: argv cannot carry a payload this big, but a file or a hook can."""
        module = load_journal_module()
        deep = "[" * 500_000 + "]" * 500_000
        with self.assertRaises(module.UsageError):
            module.parse_data_argument('{"note": %s}' % deep)

    def test_db_flag_accepted_after_subcommand(self):
        run_journal(
            ["append", "--db", self.db, "--stream", "feature/x",
             "--type", "flow-suspended"],
            cwd=self.root,
        )
        self.assertEqual(len(self.events("feature/x")), 1)

    # -- conditional append ---------------------------------------------

    def test_expect_matching_version_succeeds(self):
        self.append_event("feature/x", "flow-suspended")
        self.append(
            "--stream", "feature/x", "--type", "flow-suspended", "--expect", "1", rc=OK
        )
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_expect_zero_on_empty_stream(self):
        self.append(
            "--stream", "feature/x", "--type", "flow-suspended", "--expect", "0", rc=OK
        )
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_stale_expect_conflicts_and_writes_nothing(self):
        self.append_event("feature/x", "flow-suspended")
        self.append_event("feature/x", "flow-suspended")
        proc = self.append(
            "--stream", "feature/x", "--type", "flow-suspended",
            "--expect", "1", rc=CONFLICT,
        )
        self.assertIn("2", proc.stdout + proc.stderr)
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_stale_expect_json_reports_current_version(self):
        self.append_event("feature/x", "flow-suspended")
        proc = self.append(
            "--stream", "feature/x", "--type", "flow-suspended",
            "--expect", "0", "--json", rc=CONFLICT,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["current_version"], 1)
        self.assertEqual(payload["expected_version"], 0)


class TestActorCanon(JournalTestCase):
    """ADR 0003: `actor` is `role[@label]`, the label defaulting to the session."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def set_session(self, session_id):
        self.store_legacy_session(session_id)

    def actor_of(self, stream="feature/x"):
        return self.events(stream)[-1]["actor"]

    def test_the_default_actor_is_the_orchestrator(self):
        self.append_event("feature/x", "flow-suspended")
        self.assertEqual(self.actor_of(), "orchestrator")

    # Issue #46: `meta.current_session` names the session that started last, which need
    # not be the one appending. An append whose shell names no session records none.
    def test_the_stored_session_never_labels_an_append(self):
        self.set_session("S1")
        self.append_event("feature/x", "flow-suspended")
        self.assertEqual(self.actor_of(), "orchestrator")

    def test_a_bare_role_stays_bare_with_no_session_env(self):
        self.set_session("S1")
        self.append_event("feature/x", "flow-suspended", None, "--actor", "worker")
        self.assertEqual(self.actor_of(), "worker")

    def test_a_blank_session_env_is_no_session(self):
        self.set_session("S1")
        self.append_from_session("  ")
        self.assertEqual(self.actor_of(), "orchestrator")

    def test_the_implied_and_auto_rows_of_a_sessionless_append_are_bare(self):
        """The implied `phase-entered` and the auto deviation take the append's actor."""
        self.set_session("S1")
        self.append_event("feature/x", "phase-entered",
                          {"phase": "route-and-map", "skipped": ["workspace"]})
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001"]}, "--actor", "user")
        rows = self.events("feature/x")
        self.assertEqual([r["type"] for r in rows], [
            "phase-entered", "deviation", "phase-entered", "verify-run",
        ])
        self.assertEqual([r["actor"] for r in rows],
                         ["orchestrator", "orchestrator", "user", "user"])
        self.assertFalse([r for r in rows if "recorded_by" in r["data"]])

    def test_an_explicit_label_wins_over_the_current_session(self):
        self.set_session("S1")
        self.append_event(
            "feature/x", "flow-suspended", None, "--actor", "worker@sub-3"
        )
        self.assertEqual(self.actor_of(), "worker@sub-3")

    # Two sessions open on one project: an older hook stored the later starter in
    # meta.current_session, so the label comes from the appending shell's own
    # CLAUDE_CODE_SESSION_ID instead.
    def append_from_session(self, session_id, *args):
        self.journal("--db", self.db, "append", "--stream", "feature/x",
                     "--type", "flow-suspended", *args, rc=OK, session_env=session_id)

    def test_the_session_env_labels_the_actor_over_the_current_session(self):
        self.set_session("S2")
        self.append_from_session("S1")
        self.assertEqual(self.actor_of(), "orchestrator@S1")

    def test_concurrent_sessions_keep_their_own_labels(self):
        self.set_session("S2")  # S2 started last
        self.append_from_session("S1")
        self.append_from_session("S2", "--actor", "worker")
        self.append_from_session("S1")
        self.assertEqual([e["actor"] for e in self.events("feature/x")],
                         ["orchestrator@S1", "worker@S2", "orchestrator@S1"])

    def test_an_explicit_label_wins_over_the_session_env(self):
        self.append_from_session("S1", "--actor", "worker@sub-3")
        self.assertEqual(self.actor_of(), "worker@sub-3")

    def test_the_session_env_does_not_label_a_sessionless_role(self):
        self.append_from_session("S1", "--actor", "user")
        self.assertEqual(self.actor_of(), "user")

    def test_an_unknown_role_is_a_usage_error(self):
        proc = self.append_event(
            "feature/x", "flow-suspended", None, "--actor", "sess-1", rc=USAGE
        )
        self.assertIn("orchestrator", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_payload_session_keeps_the_role_unsuffixed(self):
        """Hooks pass `--actor hook` and the session in the payload."""
        self.set_session("S1")
        self.append_event(
            "shipgate", "artifact-written",
            {"path": "docs/prd/x.md", "session": "S9"}, "--actor", "hook",
        )
        self.assertEqual(self.actor_of("shipgate"), "hook")

    def test_the_watcher_never_borrows_a_session(self):
        """The MR watcher runs outside any session; the id would misattribute it."""
        self.set_session("S1")
        self.append_event(
            "watch/group-project!42", "baseline", {"iid": 42}, "--actor", "watcher"
        )
        self.assertEqual(self.actor_of("watch/group-project!42"), "watcher")

    def test_an_explicit_watcher_label_is_still_kept(self):
        self.set_session("S1")
        self.append_event(
            "watch/group-project!42", "baseline", {"iid": 42},
            "--actor", "watcher@babysit",
        )
        self.assertEqual(self.actor_of("watch/group-project!42"), "watcher@babysit")

    def test_a_bare_user_role_is_never_given_a_session(self):
        """`user@<session>` would claim a person is a session id (and `stats` drops it)."""
        self.set_session("S1")
        self.append_event("feature/x", "flow-suspended", None, "--actor", "user")
        self.assertEqual(self.actor_of(), "user")

    # Issue #9, ADR 0010: the actor stays `user`, and the payload names the session that
    # wrote the row, so `status --session`, `check` and `stats` can count it.
    def data_of(self, stream="feature/x"):
        return self.events(stream)[-1]["data"]

    def test_a_user_row_records_the_writing_session(self):
        self.append_from_session("S1", "--actor", "user")
        self.assertEqual(self.actor_of(), "user")
        self.assertEqual(self.data_of()["recorded_by"], "S1")

    def test_a_user_row_never_falls_back_to_the_stored_session(self):
        """Issue #46: the stored session started last; it did not write this row."""
        self.set_session("S1")
        self.append_event("feature/x", "flow-suspended", None, "--actor", "user")
        self.assertEqual(self.actor_of(), "user")
        self.assertNotIn("recorded_by", self.data_of())

    def test_a_labelled_user_row_still_records_the_writing_session(self):
        """The label names a person; the writing session is a separate fact."""
        self.append_from_session("S1", "--actor", "user@alice")
        self.assertEqual(self.actor_of(), "user@alice")
        self.assertEqual(self.data_of()["recorded_by"], "S1")

    def test_a_user_row_outside_any_session_records_nothing(self):
        self.append_event("feature/x", "flow-suspended", None, "--actor", "user")
        self.assertNotIn("recorded_by", self.data_of())

    def test_a_given_recorded_by_is_replaced_by_the_appending_session(self):
        """The journal owns the key, so a payload cannot name another session."""
        for given in ("S7", 5, "", None):
            with self.subTest(given=given):
                self.append_from_session(
                    "S1", "--actor", "user", "--data", json.dumps({"recorded_by": given})
                )
                self.assertEqual(self.data_of()["recorded_by"], "S1")

    def test_a_given_recorded_by_is_dropped_outside_any_session(self):
        for actor in ("user", "orchestrator", "watcher"):
            with self.subTest(actor=actor):
                self.append_event("feature/x", "flow-suspended", {"recorded_by": 5},
                                  "--actor", actor)
                self.assertNotIn("recorded_by", self.data_of())

    def test_only_a_user_row_records_the_writing_session(self):
        """The watcher stays sessionless; a machine role carries the label instead."""
        self.set_session("S1")
        self.append_event(
            "watch/group-project!42", "baseline", {"iid": 42}, "--actor", "watcher"
        )
        self.assertNotIn("recorded_by", self.data_of("watch/group-project!42"))
        for role in ("orchestrator", "worker"):
            with self.subTest(role=role):
                self.append_from_session("S1", "--actor", role)
                self.assertNotIn("recorded_by", self.data_of())

    def test_the_implied_phase_row_records_the_writing_session_too(self):
        self.journal(
            "--db", self.db, "append", "--stream", "feature/x", "--type", "verify-run",
            "--data", json.dumps({"outcome": "pass", "task_ids": ["T001"]}),
            "--actor", "user", rc=OK, session_env="S1",
        )
        rows = self.events("feature/x")
        self.assertEqual([r["type"] for r in rows], ["phase-entered", "verify-run"])
        self.assertEqual([r["data"].get("recorded_by") for r in rows], ["S1", "S1"])

    def event_of(self, actor, data):
        module = load_journal_module()
        event = module.Event(
            seq=1, stream="feature/x", version=1, type="gate-decision",
            data=data, ts="2026-09-02T10:00:00+00:00", actor=actor,
        )
        return module.event_session(event)

    def test_event_session_reads_recorded_by(self):
        self.assertEqual(self.event_of("user", {"recorded_by": "S1"}), "S1")
        self.assertEqual(self.event_of("user@alice", {"recorded_by": "S1"}), "S1")

    def test_event_session_never_reads_a_sessionless_label(self):
        """`user@alice` names a person and `watcher@babysit` a watcher, not a session."""
        self.assertIsNone(self.event_of("user@alice", {}))
        self.assertIsNone(self.event_of("watcher@babysit", {}))

    def test_event_session_reads_recorded_by_on_a_user_row_only(self):
        self.assertIsNone(self.event_of("watcher", {"recorded_by": "S1"}))
        self.assertEqual(
            self.event_of("orchestrator@S2", {"recorded_by": "S1"}), "S2"
        )

    # #51: no append reads the session that started last, so `session` is retired. It
    # stays one release as a no-op, so an old caller of `--set` or `--get` still exits 0.
    def test_session_is_a_retired_no_op(self):
        for argv in (["--set", "S1"], ["--set=S1"], ["--get"], ["--get", "--set=S1"], []):
            with self.subTest(argv=argv):
                proc = self.journal("--db", self.db, "session", *argv, rc=OK)
                self.assertIn("retired", proc.stdout)
                self.assertEqual(proc.stderr, "")
        self.assertEqual(
            self.sql("SELECT value FROM meta WHERE key = 'current_session'"), []
        )

    def test_session_get_reads_no_legacy_row(self):
        self.store_legacy_session("S1")
        out = self.journal("--db", self.db, "session", "--get", "--json", rc=OK).stdout
        self.assertEqual(json.loads(out), {"current_session": None, "retired": True})

    def test_session_opens_no_journal(self):
        absent = self.root / "absent.db"
        self.journal("--db", absent, "session", "--set", "S1", rc=OK)
        self.assertFalse(absent.exists())

    def test_session_reads_no_sidecar(self):
        """A corrupt sidecar fails every command that resolves a journal. The retired
        command resolves none, so it still exits 0."""
        self.write(".claude/shipgate.json", "{not json")
        proc = self.journal("session", "--set", "S1", rc=OK)
        self.assertIn("retired", proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_event_session_reads_the_actor_suffix(self):
        module = load_journal_module()
        event = module.Event(
            seq=1, stream="feature/x", version=1, type="flow-suspended",
            data={}, ts="2026-09-02T10:00:00+00:00", actor="orchestrator@S1",
        )
        self.assertEqual(module.event_session(event), "S1")

    def test_event_session_is_none_for_an_unlabelled_actor(self):
        module = load_journal_module()
        event = module.Event(
            seq=1, stream="feature/x", version=1, type="flow-suspended",
            data={}, ts="2026-09-02T10:00:00+00:00", actor="orchestrator",
        )
        self.assertIsNone(module.event_session(event))


class TestConcurrentAppend(JournalTestCase):
    """SC-002: two racing conditional appends -> exactly one winner."""

    def test_exactly_one_winner(self):
        self.init_db()
        argv = [
            sys.executable, str(JOURNAL), "--db", str(self.db), "append",
            "--stream", "feature/race", "--type", "flow-suspended", "--expect", "0",
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
            "--stream", "feature/race2", "--type", "flow-suspended",
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


class TestArtifactDedupe(JournalTestCase):
    """FR-011: two hooks see one write; the second observation is not new history."""

    MTIME = 1756800000.0

    def setUp(self):
        super().setUp()
        self.init_db()

    def artifact(self, path="docs/prd/demo.md", mtime=MTIME, stream="shipgate"):
        return self.append_event(stream, "artifact-written", {
            "path": path, "tool": "Write", "mtime": mtime,
        })

    def backdate(self, seconds):
        stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "UPDATE events SET ts = ? WHERE type = 'artifact-written'", (stale,)
            )
            conn.commit()
        finally:
            conn.close()

    def test_the_same_path_and_mtime_in_the_window_writes_nothing(self):
        self.artifact()
        proc = self.artifact()
        self.assertEqual(len(self.events("shipgate")), 1)
        self.assertIn("duplicate artifact-written", proc.stdout)
        self.assertIn("docs/prd/demo.md", proc.stdout)

    def test_the_duplicate_reports_the_existing_seq(self):
        self.artifact()
        seq = self.events("shipgate")[0]["seq"]
        self.assertIn(f"seq {seq}", self.artifact().stdout)

    def test_a_fresh_mtime_is_a_new_write(self):
        self.artifact()
        self.artifact(mtime=self.MTIME + 9)
        self.assertEqual(len(self.events("shipgate")), 2)

    def test_a_different_path_is_a_new_write(self):
        self.artifact()
        self.artifact(path="docs/prd/other.md")
        self.assertEqual(len(self.events("shipgate")), 2)

    def test_dedupe_does_not_reach_across_streams(self):
        self.artifact()
        self.artifact(stream="feature/x")
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_the_same_write_outside_the_window_is_recorded_again(self):
        self.artifact()
        self.backdate(30)
        self.artifact()
        self.assertEqual(len(self.events("shipgate")), 2)

    def test_a_second_path_in_between_does_not_end_the_window(self):
        """One tool call saving two files interleaves as a, b, a."""
        self.artifact()
        self.artifact(path="docs/prd/other.md")
        self.artifact()
        self.assertEqual(len(self.events("shipgate")), 2)

    def test_a_row_stamped_in_the_future_is_not_a_duplicate(self):
        """A clock that ran backwards must not swallow every write after it."""
        self.artifact()
        self.backdate(-60)
        self.artifact()
        self.assertEqual(len(self.events("shipgate")), 2)

    def test_json_marks_the_duplicate(self):
        self.artifact()
        proc = self.append(
            "--stream", "shipgate", "--type", "artifact-written",
            "--data", json.dumps({
                "path": "docs/prd/demo.md", "tool": "Write", "mtime": self.MTIME,
            }),
            "--json", rc=OK,
        )
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["duplicate"])
        self.assertEqual(payload["seq"], self.events("shipgate")[0]["seq"])

    def test_a_payload_without_a_path_is_never_deduped(self):
        for _ in range(2):
            self.append_event("shipgate", "artifact-written", {"tool": "Write"})
        self.assertEqual(len(self.events("shipgate")), 2)


# ---------------------------------------------------------------------------
# derived views
# ---------------------------------------------------------------------------


class TestAppendBatch(JournalTestCase):
    """FR-012: one Bash call per phase boundary instead of one per event."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def batch(self, lines, *args, rc=OK, stream="feature/x"):
        argv = [
            sys.executable, str(JOURNAL), "--db", str(self.db), "append",
            "--stream", stream, "--batch", *[str(a) for a in args],
        ]
        proc = subprocess.run(
            argv, input="".join(line + "\n" for line in lines),
            capture_output=True, text=True, cwd=str(self.root),
        )
        self.assertEqual(
            proc.returncode, rc,
            msg=f"expected rc={rc} got {proc.returncode}\n"
                f"stdout: {proc.stdout}\nstderr: {proc.stderr}",
        )
        return proc

    @staticmethod
    def line(etype, data=None, **extra):
        record = {"type": etype, "data": data or {}}
        record.update(extra)
        return json.dumps(record)

    def types(self, stream="feature/x"):
        return [e["type"] for e in self.events(stream)]

    def test_lines_are_appended_in_order(self):
        self.batch([
            self.line("phase-entered", {"phase": "workspace"}),
            self.line("flow-started", {"request": "build it"}),
            self.line("deviation", {"note": "took the long way"}),
        ])
        self.assertEqual(
            self.types(), ["phase-entered", "flow-started", "deviation"]
        )

    def test_versions_stay_contiguous(self):
        self.batch([
            self.line("flow-started", {"request": "build it"}),
            self.line("deviation", {"note": "a"}),
        ])
        self.assertEqual([e["version"] for e in self.events("feature/x")], [1, 2])

    def test_a_per_line_stream_overrides_the_default(self):
        self.batch([
            self.line("flow-started", {"request": "build it"}),
            self.line("setup-completed", {}, stream="shipgate"),
        ])
        self.assertEqual(self.types(), ["flow-started"])
        self.assertEqual(self.types("shipgate"), ["setup-completed"])

    def test_a_per_line_actor_is_honored(self):
        self.batch([self.line("deviation", {"note": "a"}, actor="user@alice")])
        self.assertEqual(self.events("feature/x")[0]["actor"], "user@alice")

    def test_blank_lines_are_skipped(self):
        self.batch(["", self.line("deviation", {"note": "a"}), "  "])
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_gates_still_apply_inside_a_batch(self):
        self.batch([self.line("task-done", {"task_id": "T001"})], rc=GATE)
        self.assertEqual(self.events("feature/x"), [])

    def test_a_failing_line_stops_the_batch(self):
        proc = self.batch([
            self.line("deviation", {"note": "first"}),
            self.line("task-done", {"task_id": "T001"}),
            self.line("deviation", {"note": "third"}),
        ], rc=GATE)
        self.assertIn("line 2:", proc.stderr)
        self.assertEqual(self.types(), ["deviation"])

    def test_a_malformed_line_names_the_line(self):
        proc = self.batch([
            self.line("deviation", {"note": "first"}),
            "{not json",
        ], rc=USAGE)
        self.assertIn("line 2", proc.stdout + proc.stderr)

    def test_a_byte_order_mark_on_stdin_is_not_part_of_the_json(self):
        self.batch(["﻿" + self.line("deviation", {"note": "a"})])
        self.assertEqual(self.types(), ["deviation"])

    def test_a_nan_literal_in_a_batch_line_is_a_usage_error(self):
        proc = self.batch(['{"type":"deviation","data":{"note":"x","n":NaN}}'], rc=USAGE)
        self.assertIn("NaN", proc.stdout + proc.stderr)
        self.assertEqual(self.events("feature/x"), [])

    def test_json_too_deeply_nested_is_a_usage_error_not_a_traceback(self):
        """The parser hits its recursion limit; the caller gets an exit code."""
        deep = "[" * 500_000 + "]" * 500_000
        proc = self.batch(
            ['{"type": "deviation", "data": {"note": %s}}' % deep], rc=USAGE
        )
        self.assertIn("line 1", proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_a_line_without_a_type_is_a_usage_error(self):
        self.batch([json.dumps({"data": {}})], rc=USAGE)

    def test_a_malformed_line_is_caught_before_anything_is_written(self):
        self.batch([
            self.line("deviation", {"note": "first"}),
            "{not json",
        ], rc=USAGE)
        self.assertEqual(self.events("feature/x"), [])

    def test_type_with_batch_is_a_usage_error(self):
        self.batch([self.line("deviation", {"note": "a"})],
                   "--type", "deviation", rc=USAGE)

    def test_data_with_batch_is_a_usage_error(self):
        self.batch([self.line("deviation", {"note": "a"})],
                   "--data", "{}", rc=USAGE)

    def test_expect_with_batch_is_a_usage_error(self):
        self.batch([self.line("deviation", {"note": "a"})], "--expect", 0, rc=USAGE)

    def test_an_empty_batch_is_a_usage_error(self):
        self.batch([""], rc=USAGE)

    def test_append_without_type_or_batch_is_a_usage_error(self):
        self.journal("--db", self.db, "append", "--stream", "feature/x", rc=USAGE)

    def test_human_output_names_every_event(self):
        proc = self.batch([
            self.line("flow-started", {"request": "build it"}),
            self.line("deviation", {"note": "a"}),
        ])
        self.assertIn("appended flow-started to feature/x", proc.stdout)
        self.assertIn("appended deviation to feature/x", proc.stdout)

    def test_json_lists_one_result_per_line(self):
        proc = self.batch([
            self.line("flow-started", {"request": "build it"}),
            self.line("deviation", {"note": "a"}),
        ], "--json")
        results = json.loads(proc.stdout)
        self.assertEqual([r["line"] for r in results], [1, 2])
        self.assertEqual([r["type"] for r in results],
                         ["flow-started", "deviation"])
        self.assertEqual([r["version"] for r in results], [1, 2])
        self.assertEqual(results[0]["stream"], "feature/x")

    def test_json_reports_an_implied_phase_per_line(self):
        proc = self.batch([
            self.line("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
        ], "--json")
        self.assertEqual(json.loads(proc.stdout)[0]["implied_phase"], "implement")

    def test_json_ends_with_the_failing_line_after_the_partial_list(self):
        proc = self.batch([
            self.line("deviation", {"note": "first"}),
            self.line("task-done", {"task_id": "T001"}),
        ], "--json", rc=GATE)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["type"], "deviation")
        self.assertEqual(results[1]["line"], 2)
        self.assertIn("verify-run", results[1]["error"])

    def test_help_says_the_batch_is_not_a_transaction(self):
        proc = self.journal("--db", self.db, "append", "--help", rc=OK)
        self.assertIn("not a transaction", " ".join(proc.stdout.split()))


class TestPayloadCap(JournalTestCase):
    """FR-013: the event is a pointer; the prose lives in the worklog."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def payload_of(self, size):
        """A deviation payload whose canonical JSON is exactly ``size`` bytes."""
        overhead = len(json.dumps({"note": ""}, sort_keys=True).encode())
        return {"note": "x" * (size - overhead)}

    def test_a_payload_at_the_cap_is_accepted(self):
        self.append_event("feature/x", "deviation", self.payload_of(1024))
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_a_payload_over_the_cap_is_refused(self):
        self.append_event("feature/x", "deviation", self.payload_of(1025), rc=GATE)
        self.assertEqual(self.events("feature/x"), [])

    def test_the_refusal_names_the_size_the_cap_and_the_way_out(self):
        proc = self.append_event(
            "feature/x", "deviation", self.payload_of(2000), rc=GATE
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("2000 bytes", combined)
        self.assertIn("cap 1024", combined)
        self.assertIn("refs", combined)
        self.assertIn("--force", combined)

    def test_recorded_by_does_not_push_a_payload_at_the_cap_over_it(self):
        """The key is the journal's own bookkeeping, not prose the caller wrote."""
        self.journal(
            "--db", self.db, "append", "--stream", "feature/x", "--type", "deviation",
            "--data", json.dumps(self.payload_of(1024)), "--actor", "user",
            rc=OK, session_env="S1",
        )
        self.assertEqual(self.events("feature/x")[-1]["data"]["recorded_by"], "S1")

    def test_force_waives_the_cap_and_stores_the_payload(self):
        note = self.payload_of(2000)["note"]
        self.append_event(
            "feature/x", "deviation", {"note": note},
            "--force", "--force-reason", "the note is the evidence",
        )
        stored = self.events("feature/x")[0]["data"]
        self.assertEqual(stored["note"], note)
        self.assertTrue(stored["forced"])

    def test_the_meta_stream_is_exempt(self):
        self.append_event("shipgate", "artifact-written", {
            "path": "docs/prd/demo.md", "tool": "Write", "blob": "x" * 2000,
        })
        self.assertEqual(len(self.events("shipgate")), 1)

    def test_watch_streams_are_exempt(self):
        self.append_event("watch/group-project!42", "baseline", {
            "iid": 42, "body": "x" * 2000,
        })
        self.assertEqual(len(self.events("watch/group-project!42")), 1)

    def test_force_over_the_cap_without_a_reason_is_a_usage_error(self):
        """Every brief from here on reprints those bytes — the waiver has to say why."""
        proc = self.append_event(
            "feature/x", "deviation", self.payload_of(2000), "--force", rc=USAGE
        )
        self.assertIn("--force-reason", proc.stdout + proc.stderr)
        self.assertEqual(self.events("feature/x"), [])

    def test_the_cap_is_the_documented_one(self):
        module = load_journal_module()
        self.assertEqual(module.PAYLOAD_CAP_BYTES, 1024)


class TestLogAndStreams(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        for i in range(5):
            self.append_event("feature/x", "flow-suspended", {"i": i})
        self.append_event("feature/y", "flow-suspended", {"i": 0})

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
        self.assertIn("flow-suspended", proc.stdout)

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


class TestSidecarVersion(JournalTestCase):
    """A sidecar from a newer shipgate: warn once, keep reading the keys it knows."""

    def write_sidecar(self, **extra):
        (self.root / ".claude").mkdir(exist_ok=True)
        config = {"db": ".claude/shipgate.db"}
        config.update(extra)
        (self.root / ".claude" / "shipgate.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

    def test_a_newer_version_warns_once_on_stderr_and_keeps_working(self):
        self.write_sidecar(version=2)
        proc = self.journal("init", rc=OK)
        self.assertEqual(proc.stderr.count("journal.py: "), 1, proc.stderr)
        self.assertIn("declares version 2", proc.stderr)
        self.assertIn("knows version 1", proc.stderr)
        self.assertTrue((self.root / ".claude" / "shipgate.db").exists())
        appended = self.journal("append", "--stream", "feature/x", "--type",
                                "flow-suspended", rc=OK)
        self.assertEqual(appended.stderr.count("declares version 2"), 1)

    def test_a_known_or_absent_version_is_silent(self):
        for extra in ({"version": 1}, {}, {"version": 0}, {"version": True},
                      {"version": "2"}):
            with self.subTest(sidecar=extra):
                self.write_sidecar(**extra)
                proc = self.journal("init", rc=OK)
                self.assertNotIn("declares version", proc.stderr)


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
        self.append_event(s, "task-done", {"task_id": "T001"}, "--actor", "worker@sess")
        self.append_event("shipgate", "setup-completed", {})
        self.dump = self.root / "dump.jsonl"

    def do_export(self, *args):
        proc = self.journal("--db", self.db, "export", *args, rc=OK)
        self.dump.write_text(proc.stdout, encoding="utf-8")
        return proc.stdout

    def test_export_is_one_object_per_line_in_seq_order(self):
        lines = [json.loads(l) for l in self.do_export().splitlines() if l.strip()]
        self.assertEqual([e["seq"] for e in lines], [1, 2, 3, 4, 5, 6])
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
        self.assertEqual(summary["imported"], 6)
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
        self.assertEqual(summary["skipped"], 6)
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

    A real bug flow named its stream after the branch — `fix/1290-date-off-by-one` — and the
    old `feature/` prefix filter hid all ten of its events from `status`, which reported
    "No feature streams recorded" while the journal was in fact full.
    """

    def setUp(self):
        super().setUp()
        self.init_db()

    def test_a_branch_named_stream_is_reported(self):
        self.append_event("fix/1290-date-off-by-one", "flow-started", {
            "request": "fix the date arithmetic", "branch": "fix/1290",
        })
        streams = [f["stream"] for f in self.status_json()["features"]]
        self.assertIn("fix/1290-date-off-by-one", streams)

    def test_the_meta_stream_is_not_reported_as_work(self):
        self.append_event("shipgate", "setup-completed", {"mode": "create"})
        self.assertEqual(self.status_json()["features"], [])

    def test_watch_streams_are_not_reported_as_work(self):
        self.append_event("watch/group-project!42", "baseline", {"iid": 42})
        self.assertEqual(self.status_json()["features"], [])

    def test_a_feature_stream_is_still_reported(self):
        self.append_event("feature/demo", "flow-started", {"request": "build it"})
        streams = [f["stream"] for f in self.status_json()["features"]]
        self.assertEqual(streams, ["feature/demo"])

    def test_filtering_matches_a_branch_named_stream(self):
        self.append_event("fix/1290-date-off-by-one", "flow-started",
                          {"request": "build it"})
        self.append_event("feature/other", "flow-started", {"request": "build it"})
        got = [f["stream"] for f in self.status_json("--feature", "1290")["features"]]
        self.assertEqual(got, ["fix/1290-date-off-by-one"])


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

    def test_completion_and_block_types_are_listed(self):
        out = self.journal("--db", self.db, "vocab", rc=OK).stdout
        self.assertIn("flow-completed", out)
        self.assertIn("gate-blocked", out)

    def test_shaped_types_are_marked_in_the_listing(self):
        out = self.journal("--db", self.db, "vocab", rc=OK).stdout
        marked = [
            line for line in out.splitlines()
            if line.strip().startswith("gate-decision")
        ]
        self.assertTrue(marked, "expected gate-decision on its own line")
        self.assertTrue(marked[0].rstrip().endswith("[shape]"), marked[0])

    def test_shape_of_one_type_is_printed_as_json(self):
        out = self.journal(
            "--db", self.db, "vocab", "--shape", "gate-decision", rc=OK
        ).stdout
        shape = json.loads(out)
        self.assertEqual(
            sorted(shape["required"]), ["decision", "gate", "mode", "question"]
        )
        self.assertEqual(shape["defaults"]["raised_by"], "orchestrator")
        self.assertEqual(shape["aliases"]["chosen"], "decision")
        # #52 retired the read go and its keys `witness` and `words`.
        self.assertEqual(shape["strings"], ["decision"])
        self.assertEqual(shape["integers"], ["request"])
        self.assertNotIn("max_chars", shape)

    def test_the_gate_decision_shape_names_its_source_marker(self):
        """ADR 0015: the HUD's dialog writes `dialog`, the user's `!` command `shell`;
        ADR 0023: the recorder writes `question` and `prompt` (#52: no `read`)."""
        out = self.journal(
            "--db", self.db, "vocab", "--shape", "gate-decision", rc=OK
        ).stdout
        self.assertEqual(json.loads(out)["enums"]["source"],
                         ["dialog", "shell", "question", "prompt"])

    def test_the_review_verdict_shape_names_its_map_vocabularies(self):
        out = self.journal(
            "--db", self.db, "vocab", "--shape", "review-verdict", rc=OK
        ).stdout
        self.assertEqual(json.loads(out)["map_enums"], {
            "criteria": ["met", "unmet"],
            "dispositions": ["fixed", "rejected", "deferred"],
        })

    def test_the_review_disposition_shape_names_its_rules(self):
        out = self.journal(
            "--db", self.db, "vocab", "--shape", "review-disposition", rc=OK
        ).stdout
        self.assertEqual(json.loads(out), {
            "required": ["dispositions", "round"],
            "map_enums": {"dispositions": ["fixing", "fixed", "rejected", "deferred"]},
            "integers": ["round"],
            "strings": ["note"],
            "string_maps": ["labels"],
        })

    def test_review_disposition_is_listed_with_its_shape(self):
        out = self.journal("--db", self.db, "vocab", rc=OK).stdout
        line = [l for l in out.splitlines() if l.strip().startswith("review-disposition")]
        self.assertTrue(line)
        self.assertTrue(line[0].rstrip().endswith("[shape]"), line[0])

    def test_review_disposition_implies_no_phase(self):
        self.assertNotIn("review-disposition", load_journal_module().PHASE_OF_EVENT)

    def test_shape_of_a_shapeless_type_is_empty(self):
        out = self.journal(
            "--db", self.db, "vocab", "--shape", "artifact-written", rc=OK
        ).stdout
        self.assertEqual(json.loads(out), {})

    def test_shape_of_an_unknown_type_is_a_usage_error(self):
        self.journal("--db", self.db, "vocab", "--shape", "verify-passed", rc=USAGE)

    def test_shape_without_a_type_prints_the_whole_table(self):
        table = json.loads(
            self.journal("--db", self.db, "vocab", "--shape", rc=OK).stdout
        )
        for expected in ("gate-decision", "verify-run", "review-verdict", "deviation"):
            self.assertIn(expected, table)

    def test_phase_owning_events_map_to_declared_phases(self):
        module = load_journal_module()
        for event_type, phase in module.PHASE_OF_EVENT.items():
            self.assertIn(event_type, module.EVENT_VOCABULARY)
            self.assertIn(phase, module.PHASE_ORDER)

    def test_shaped_and_terminal_types_are_in_the_vocabulary(self):
        module = load_journal_module()
        for name in list(module.EVENT_SHAPES) + list(module.TERMINAL_TYPES):
            self.assertIn(name, module.EVENT_VOCABULARY)


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
        self.journal("append", "--stream", "feature/x", "--type", "flow-suspended",
                     rc=OK)

    def test_sidecar_found_from_a_nested_directory(self):
        self.make_sidecar()
        self.journal("init", rc=OK)
        nested = self.root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        self.journal("append", "--stream", "feature/x", "--type", "flow-suspended",
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
                     "--type", "flow-suspended", rc=OK)
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


HANDOFF_WORKLOG = """# Worklog: demo

# Build Plan

- [x] T001 — the types — file(s): `a.py`
- [ ] T002 — the bodies
- [ ] T003 — the parser
- [ ] T004 — the renderer
- [ ] T005 — the tests
- [ ] T006 — the docs
- [ ] T007 — the version
- [ ] T008 — the full suite
"""

HANDOFF_CONFIG = """# shipgate configuration — demo

## Autonomy

<!-- a comment the brief must not print -->

- Mode: executive
- Extra escalations: publishing a release

## Security-sensitive areas

- **Anything under `hooks/`.** Hooks run on every machine in every project, so the
  no-op path is a correctness requirement.
- Anything that reads outside the plugin's own directory.
"""

ADR_PROPOSED = "---\ntype: adr\nstatus: proposed\n---\n\n# 0002. A hook change\n"
ADR_ACCEPTED = "---\ntype: adr\nstatus: accepted\n---\n\n# 0001. The brief\n"


# The bytes of 0.28.2's bound block and handoff, pinned before #31 adds its lines (T002,
# SC-003). A later change to either is a choice, never an accident.
PIN_NOW = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
PIN_STREAM = "feature/demo"


def _pin_rows():
    """One stream's rows with fixed timestamps: a request, a phase, six decisions, a
    verify, a task and a queued design."""
    rows = [
        ("flow-started", {"request": "#1234 build the demo",
                          "report_to": "lead t2 (send t2)"}),
        ("clarify-passed", {"prd": "docs/prd/demo.md"}),
        ("design-committed", {"worklog": "docs/prd/demo.worklog.md",
                              "adrs": ["docs/adr/0001-the-brief.md",
                                       "docs/adr/0002-a-hook-change.md"],
                              "open": ["docs/adr/0002-a-hook-change.md"]}),
    ]
    rows += [("gate-decision", {"gate": "design", "question": f"question {n}?",
                                "decision": f"answer {n}", "mode": "executive"})
             for n in range(6)]
    rows += [
        ("phase-entered", {"phase": "implement", "style": []}),
        ("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
        ("task-done", {"task_id": "T001"}),
        ("design-queued", {"issue": "#1235", "assumes": "the parser lands"}),
    ]
    return [
        {"stream": PIN_STREAM, "version": n, "type": etype, "data": data,
         "ts": f"2026-01-02T10:{n:02d}:00+00:00", "actor": "orchestrator@s1"}
        for n, (etype, data) in enumerate(rows, 1)
    ]


PIN_BLOCK = """\
feature/demo  (v13)
  phase        : implement  (entered 2026-01-02T10:10)
  last event   : design-queued at 2026-01-02T10:13
  tasks done   : 1  [T001]
  last verify  : pass — T001 (2026-01-02T10:11)
  gate decisions:
- [design] question 1? -> answer 1 (executive)
- [design] question 2? -> answer 2 (executive)
- [design] question 3? -> answer 3 (executive)
- [design] question 4? -> answer 4 (executive)
- [design] question 5? -> answer 5 (executive)
    … +1 earlier
  open designs:
- #1235 (assumes the parser lands)
"""

PIN_HANDOFF = """\
shipgate handoff — feature/demo  (v13)
Built from the flow journal, the artifacts its events name and the project config; nothing comes from the session that printed it.
Print it again with: journal.py handoff --stream=feature/demo

role         : the orchestrator of this shipgate flow. Run /shipgate to resume; it reads the journal and routes to the next phase.
request      : #1234 build the demo
phase        : implement (entered 2026-01-02T10:10) → next: implement (the next task)
report to    : lead t2 (send t2)
open first   :
  1. PRD      docs/prd/demo.md
  2. worklog  docs/prd/demo.worklog.md
  3. ADR      docs/adr/0001-the-brief.md
  4. ADR      docs/adr/0002-a-hook-change.md
tasks        : 1/8 done · next: T002 — the bodies
last verify  : pass (2026-01-02T10:11)
open gates   :
  - ADR docs/adr/0002-a-hook-change.md is still proposed: the tasks it governs wait for the user's answer
  - publish held: an MR/PR needs a ready review-verdict or the user's own approval
decisions    :
  - [design] question 1? -> answer 1 (executive)
  - [design] question 2? -> answer 2 (executive)
  - [design] question 3? -> answer 3 (executive)
  - [design] question 4? -> answer 4 (executive)
  - [design] question 5? -> answer 5 (executive)
  … +1 earlier
rules that bind:
  - The repo's CLAUDE.md files load at session start and stay binding; this brief does not copy them.
  - Commit only when the user asks, and stage only the files you changed (implement: Committing).
  Autonomy mode: executive (legacy .claude/shipgate.md ## Autonomy)
  Autonomy (.claude/shipgate.md):
    - Mode: executive
    - Extra escalations: publishing a release
  Security-sensitive areas (.claude/shipgate.md):
    - **Anything under `hooks/`.** Hooks run on every machine in every project, so the
      no-op path is a correctness requirement.
    - Anything that reads outside the plugin's own directory.
"""


class _PinStream:
    """The pinned stream of `_pin_rows`, imported, and its two renders."""

    def setUp(self):
        super().setUp()
        self.init_db()
        raw = self.root / "pin.jsonl"
        raw.write_text("".join(json.dumps(r) + "\n" for r in _pin_rows()),
                       encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        self.module = load_journal_module()
        self.conn = self.module.connect(self.db)
        self.addCleanup(self.conn.close)

    def block(self):
        status = self.module.build_status(self.conn, branch=PIN_STREAM, now=PIN_NOW)
        bound = [f for f in status["features"] if f["branch_match"]]
        return "\n".join(self.module._render_feature(bound[0]))

    def handoff(self):
        for rel, text in (("docs/prd/demo.md", "# PRD: demo\n"),
                          ("docs/prd/demo.worklog.md", HANDOFF_WORKLOG),
                          ("docs/adr/0001-the-brief.md", ADR_ACCEPTED),
                          ("docs/adr/0002-a-hook-change.md", ADR_PROPOSED),
                          (".claude/shipgate.md", HANDOFF_CONFIG)):
            self.write(rel, text)
        homes = {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                 "worklog": "docs/prd/*.worklog.md"}
        user_dir = self.root / "user-config"
        user_dir.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(user_dir)}):
            doc = self.module.build_handoff(self.conn, PIN_STREAM, self.root, homes,
                                            now=PIN_NOW, start=self.root)
        return self.module.render_handoff(doc)


class _StreamRows:
    """Helpers for tests that import rows with set timestamps (T005, T008)."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.module = load_journal_module()

    def load(self, rows):
        raw = self.root / "rows.jsonl"
        raw.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)

    def streams(self, count, days_ago=0, prefix="feat/", actor="orchestrator@s1",
                etype="flow-started", data=None):
        ts = (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)).isoformat()
        return [{"stream": f"{prefix}{n}-x", "version": 1, "type": etype,
                 "data": data or {"request": "x"}, "ts": ts, "actor": actor}
                for n in range(count)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
