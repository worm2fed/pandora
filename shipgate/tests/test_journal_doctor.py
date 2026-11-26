#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: ``doctor`` and ``stats``.

Split out of ``test_journal.py`` (#61), which holds the helpers and fixtures.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_journal import (
    insert_legacy_row, JournalTestCase, load_journal_module, OK, run_journal, SESSION_ENV,
    USAGE,
)
from test_journal_screens import _ambient_root, _tree


# #26 T015 plants evidence files in temporary roots only: the real evidence root of the
# environment must not change.
_REAL = {}


def setUpModule():
    _REAL["root"] = _ambient_root()
    _REAL["tree"] = _tree(_REAL["root"])


def tearDownModule():
    if _tree(_REAL["root"]) != _REAL["tree"]:
        raise AssertionError(f"the real evidence root {_REAL['root']} changed in the tests")


# ---------------------------------------------------------------------------
# doctor / export / import
# ---------------------------------------------------------------------------


class TestDoctor(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feature/x", "flow-suspended")

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

    def write_sidecar(self, config):
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / "shipgate.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

    def test_reports_the_sidecar_version_and_stray_keys(self):
        self.write_sidecar({
            "version": 2, "db": str(self.db), "artifact_homes": {}, "enforce": {},
            "watch": True, "auto_merge": "yes",
        })
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        sidecar = json.loads(proc.stdout)["sidecar"]
        self.assertEqual(sidecar["version"], 2)
        self.assertEqual(sidecar["stray_keys"], ["auto_merge", "watch"])
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        self.assertIn("sidecar version : 2", text)
        self.assertIn("stray keys      : auto_merge, watch", text)

    def test_a_key_the_schema_names_is_no_stray_key(self):
        """ADR 0028: `stray_keys` are the keys `settings.schema.json` does not name."""
        self.write_sidecar({
            "version": 2, "db": str(self.db), "ledger": "docs/ledger.md",
            "artifact_homes": {}, "enforce": {}, "autonomy": "executive",
            "orchestration": {"review": "workflow"}, "writing_style": "ste-80",
            "code_graph": "auto", "code_signals": {"window_months": 12},
            "handoff": "500k", "forge": "github", "watch": True,
        })
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        self.assertEqual(json.loads(proc.stdout)["sidecar"]["stray_keys"], ["watch"])

    def test_a_missing_schema_leaves_the_report_standing(self):
        """`doctor` is the command for a broken install: with no `settings.schema.json` it
        still prints its report and its exit code, and says the stray keys are unknown."""
        import shutil

        plugin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(plugin), True)
        shipgate = Path(__file__).resolve().parent.parent
        for part in ("scripts", "hooks"):
            shutil.copytree(shipgate / part, plugin / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        self.write_sidecar({"version": 2, "db": str(self.db), "watch": True})
        journal = [sys.executable, str(plugin / "scripts" / "journal.py"), "--db",
                   str(self.db), "doctor"]
        proc = subprocess.run(journal + ["--json"], capture_output=True, text=True,
                              cwd=str(self.root), timeout=60)
        self.assertEqual(proc.returncode, OK, proc.stderr)
        sidecar = json.loads(proc.stdout)["sidecar"]
        self.assertTrue(sidecar["found"])
        self.assertIsNone(sidecar["stray_keys"])
        text = subprocess.run(journal, capture_output=True, text=True,
                              cwd=str(self.root), timeout=60)
        self.assertEqual(text.returncode, OK, text.stderr)
        self.assertIn("stray keys      : unknown (settings.schema.json unreadable)",
                      text.stdout)

    def test_a_ledger_key_is_no_stray_key(self):
        """`ledger` is read by `status` (the ledger count): update mode must keep it."""
        self.write_sidecar({
            "version": 1, "db": str(self.db), "ledger": "docs/ledger.md",
            "artifact_homes": {}, "enforce": {},
        })
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        self.assertEqual(json.loads(proc.stdout)["sidecar"]["stray_keys"], [])

    def test_a_sidecar_without_a_version_or_stray_keys(self):
        self.write_sidecar({"db": str(self.db)})
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        sidecar = json.loads(proc.stdout)["sidecar"]
        self.assertIsNone(sidecar["version"])
        self.assertEqual(sidecar["stray_keys"], [])
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        self.assertIn("sidecar version : —", text)
        self.assertIn("stray keys      : none", text)

    def test_the_raw_version_is_reported_as_it_is(self):
        self.write_sidecar({"version": "2", "db": str(self.db)})
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        self.assertEqual(json.loads(proc.stdout)["sidecar"]["version"], "2")

    # -- the settings report (#60, ADR 0028 D1; PRD FR-012) ---------------
    # The config-against-sidecar drift check is gone: with one home per setting there
    # is nothing to compare. The `settings` block names what `setup` must fix.

    def settings_report(self, *extra):
        proc = self.journal("--db", self.db, "doctor", "--json", *extra, rc=OK)
        return json.loads(proc.stdout)["settings"]

    def isolate_user_dir(self):
        from unittest import mock

        user = self.root / "user-config"
        user.mkdir(exist_ok=True)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(user)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return user

    def test_the_drift_block_is_gone(self):
        self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db)})
        self.write(".claude/shipgate.md",
                   "## Knowledge base\n\n- Ledger: `notes/ledger.md`\n")
        report = json.loads(
            self.journal("--db", self.db, "doctor", "--json", rc=OK).stdout)
        self.assertNotIn("config", report)
        self.assertEqual(set(report["settings"]),
                         {"problems", "legacy", "nested_files", "grace"})
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        self.assertNotIn("drift", text)
        self.assertNotIn("config          :", text)

    def test_each_problem_is_named(self):
        user = self.isolate_user_dir()
        self.write_sidecar({"version": 3, "db": str(self.db), "autonomy": "exec",
                            "publish_quiz": True})
        (user / "shipgate.settings.json").write_text(
            json.dumps({"forge": "github"}), encoding="utf-8")
        self.write(".claude/shipgate.md", "## Code tooling\n\n- Code graph: `fast`\n")
        problems = self.settings_report()["problems"]
        kinds = sorted((p["kind"], p["key"]) for p in problems)
        self.assertEqual(kinds, [
            ("bad-legacy", "code_graph"), ("bad-value", "autonomy"),
            ("scope", "forge"), ("unknown-key", "publish_quiz"), ("version", "version"),
        ])
        for problem in problems:
            self.assertEqual(set(problem), {"kind", "path", "key", "value", "message"})
        bad = next(p for p in problems if p["kind"] == "bad-value")
        self.assertIn('autonomy = "exec" is not one of: ask, executive', bad["message"])

    def test_an_unreadable_user_settings_file_is_a_problem(self):
        user = self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db)})
        (user / "shipgate.settings.json").write_text("{oops", encoding="utf-8")
        problems = self.settings_report()["problems"]
        self.assertEqual([p["kind"] for p in problems], ["not-json"])

    def test_each_legacy_line_is_listed(self):
        user = self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db)})
        self.write(".claude/shipgate.md",
                   "## Autonomy\n\n- Mode: executive\n- Extra escalations: none\n\n"
                   "## Orchestration\n\n- review: workflow\n")
        (user / "shipgate.md").write_text("## Writing style\n\n- Docs: ste-80\n",
                                          encoding="utf-8")
        nested = self.root / "svc"
        (nested / ".git").mkdir(parents=True)
        self.write("svc/.claude/shipgate.md", "## Code tooling\n\n- Code graph: `off`\n")
        legacy = self.settings_report()["legacy"]
        rows = sorted((Path(r["path"]).relative_to(self.root.resolve()).as_posix()
                       if r["path"].startswith(str(self.root.resolve())) else "user",
                       r["section"], r["bullet"], r["key"], r["value"]) for r in legacy)
        self.assertEqual(rows, [
            (".claude/shipgate.md", "Autonomy", "Mode", "autonomy", "executive"),
            (".claude/shipgate.md", "Orchestration", "review", "orchestration.review",
             "workflow"),
            ("svc/.claude/shipgate.md", "Code tooling", "Code graph", "code_graph",
             "`off`"),
            ("user", "Writing style", "Docs", "writing_style", "ste-80"),
        ])

    def test_a_settings_file_below_the_project_root_is_named(self):
        self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db)})
        nested = self.root / "packages" / "web"
        (nested / ".git").mkdir(parents=True)
        self.write("packages/web/.claude/shipgate.json", json.dumps({"version": 2}))
        self.assertEqual(self.settings_report()["nested_files"],
                         [str(self.root.resolve() / "packages/web/.claude/shipgate.json")])

    def test_the_grace_date(self):
        self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db)})
        schema = json.loads((Path(__file__).resolve().parent.parent
                             / "settings.schema.json").read_text(encoding="utf-8"))
        grace = self.settings_report()["grace"]
        self.assertEqual(grace["until"], schema["x-legacy-until"])
        self.assertIsInstance(grace["ended"], bool)

    def test_the_text_form(self):
        user = self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db), "autonomy": "exec"})
        self.write(".claude/shipgate.md", "## Orchestration\n\n- review: workflow\n")
        (user / "shipgate.md").write_text("## Writing style\n\n- Docs: ste-80\n",
                                          encoding="utf-8")
        lines = self.journal("--db", self.db, "doctor", rc=OK).stdout.splitlines()
        head = [line for line in lines if line.startswith("settings        :")]
        self.assertEqual(len(head), 1, lines)
        self.assertIn("1 problem, 2 legacy lines, 0 nested settings files", head[0])
        problem = [line for line in lines if line.startswith("problem         :")]
        self.assertEqual(len(problem), 1)
        self.assertIn('autonomy = "exec"', problem[0])
        legacy = [line for line in lines if line.startswith("legacy line     :")]
        self.assertEqual(len(legacy), 2)
        self.assertIn(".claude/shipgate.md ## Orchestration review: workflow",
                      "\n".join(legacy))

    def test_the_text_form_shows_no_character_that_does_not_print(self):
        """A checkout writes the legacy values and the keys: each `doctor` line stays one
        line, and an escape or a line break from the file shows as `?` or a space."""
        self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db),
                            "artifact_homes": {"evil" + chr(27) + "[31m": 3},
                            "x" + chr(7) + chr(27) + "[31m": True})
        self.write(".claude/shipgate.md",
                   "## Orchestration\n\n- review: `workflow`" + chr(27) + "[2J\n")
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        self.assertNotIn(chr(27), text)
        self.assertNotIn(chr(7), text)
        for line in text.splitlines():
            if line.startswith(("problem", "legacy line", "stray keys", "sidecar")):
                self.assertTrue(line.isprintable(), repr(line))

    def test_settings_problems_leave_the_exit_code_alone(self):
        self.isolate_user_dir()
        self.write_sidecar({"version": 2, "db": str(self.db), "autonomy": "exec"})
        self.journal("--db", self.db, "doctor", rc=OK)
        self.journal("--db", self.db, "doctor", "--json", rc=OK)

    def test_a_missing_schema_leaves_the_settings_block_empty(self):
        import shutil

        plugin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(plugin), True)
        shipgate = Path(__file__).resolve().parent.parent
        for part in ("scripts", "hooks"):
            shutil.copytree(shipgate / part, plugin / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        self.write_sidecar({"version": 2, "db": str(self.db)})
        proc = subprocess.run(
            [sys.executable, str(plugin / "scripts" / "journal.py"), "--db",
             str(self.db), "doctor", "--json"],
            capture_output=True, text=True, cwd=str(self.root), timeout=60)
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertIsNone(json.loads(proc.stdout)["settings"])

    def test_the_json_keeps_every_existing_key(self):
        self.isolate_user_dir()
        self.write_sidecar({"version": 1, "db": str(self.db)})
        report = json.loads(
            self.journal("--db", self.db, "doctor", "--json", rc=OK).stdout
        )
        for key in (
            "db", "db_source", "integrity_check", "off_vocabulary", "journal_mode",
            "schema_version", "pending_migrations", "events", "sidecar", "settings",
        ):
            self.assertIn(key, report)
        self.assertEqual(
            set(report["sidecar"]),
            {"found", "path", "db", "agrees", "version", "stray_keys"},
        )


class TestAnUnreadableSettingsFile(JournalTestCase):
    """T053 points the user at `journal.py doctor` for a settings file the hooks cannot
    read. Each form exits 1 with a one-line error that names the file; none prints a
    traceback."""

    FORMS = {
        "not JSON": b"{not json",
        "not an object": b"[1]",
        "not UTF-8": b'{"db": "x\xff"}',
        "a byte order mark": b'\xef\xbb\xbf{"db": ".claude/shipgate.db"}',
    }

    def test_each_form_is_one_error_line(self):
        (self.root / ".claude").mkdir()
        path = self.root / ".claude" / "shipgate.json"
        for label, raw in self.FORMS.items():
            with self.subTest(form=label):
                path.write_bytes(raw)
                proc = self.journal("doctor", rc=1)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1, proc.stderr)
                self.assertIn("shipgate.json", proc.stderr)

# ---------------------------------------------------------------------------
# ledger visibility
# ---------------------------------------------------------------------------


class TestStats(JournalTestCase):
    """FR-014: the numbers that make process tuning evidence-based."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def stats(self, *args):
        proc = self.journal("--db", self.db, "stats", "--json", *args, rc=OK)
        return json.loads(proc.stdout)

    def row(self, stream="feature/x", *args):
        rows = [r for r in self.stats(*args)["streams"] if r["stream"] == stream]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def decide(self, mode="executive", raised_by="orchestrator", stream="feature/x"):
        self.append_event(stream, "gate-decision", {
            "gate": "design", "question": "cascade or throw", "decision": "cascade",
            "mode": mode, "raised_by": raised_by,
        })

    def backdate(self, **delta):
        stale = (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute("UPDATE events SET ts = ?", (stale,))
            conn.commit()
        finally:
            conn.close()

    def test_counts_events_per_stream(self):
        self.append_event("feature/x", "flow-started", {"request": "build it"})
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.append_event("feature/y", "flow-started", {"request": "build it"})
        self.assertEqual(self.row("feature/x")["events"], 2)
        self.assertEqual(self.row("feature/y")["events"], 1)

    def test_events_are_counted_by_actor_role(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.append_event("feature/x", "deviation", {"note": "b"},
                          "--actor", "user@alice")
        self.append_event("feature/x", "deviation", {"note": "c"},
                          "--actor", "worker@opus")
        self.assertEqual(
            self.row()["by_role"],
            {"orchestrator": 1, "user": 1, "worker": 1},
        )

    def test_decisions_are_counted_by_mode_and_raiser(self):
        self.decide(mode="ask", raised_by="user")
        self.decide(mode="ask", raised_by="user")
        self.decide(mode="executive", raised_by="orchestrator")
        self.assertEqual(
            self.row()["decisions"],
            {"ask/user": 2, "executive/orchestrator": 1},
        )

    def test_counts_deviations_verify_runs_and_tasks(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001", "T002"]})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        row = self.row()
        self.assertEqual(row["deviations"], 1)
        self.assertEqual(row["verify_runs"], 1)
        self.assertEqual(row["tasks_done"], 1)

    def test_a_task_re_recorded_after_review_is_one_task_done(self):
        """`tasks_done` counts distinct ids, as the brief does."""
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.assertEqual(self.row()["tasks_done"], 1)

    def test_a_task_verified_twice_is_counted_once(self):
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001", "T002"]})
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 1}],
                           "outcome": "fail", "task_ids": ["T001"]})
        self.assertEqual(self.row()["tasks_reverified"], 1)

    def test_a_task_listed_twice_in_one_run_is_not_reverified(self):
        """One run naming a task twice verified it once — that is not a second round."""
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001", "T001"]})
        self.assertEqual(self.row()["tasks_reverified"], 0)

    def test_review_rounds_and_feedback(self):
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event("feature/x", "review-verdict", {"verdict": "not-ready"})
        self.append_event("feature/x", "review-feedback", {"refs": ["!1#note_1"]})
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        row = self.row()
        self.assertEqual(row["review_rounds"], 2)
        self.assertEqual(row["review_feedback"], 1)

    def deviate_in(self, session, note, *args):
        """A deviation appended from a shell whose CLAUDE_CODE_SESSION_ID is `session`."""
        self.journal("--db", self.db, "append", "--stream", "feature/x",
                     "--type", "deviation", "--data", json.dumps({"note": note}), *args,
                     rc=OK, session_env=session)

    def test_sessions_touching_the_stream_are_counted(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.assertEqual(self.row()["sessions"], 0)
        self.deviate_in("session-1", "b")
        self.deviate_in("session-1", "c")
        self.deviate_in("session-2", "d")
        self.assertEqual(self.row()["sessions"], 2)

    def test_the_stored_session_is_not_counted(self):
        """Issue #46: a sessionless append does not borrow the stored session."""
        self.store_legacy_session("session-1")
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.append_event("feature/x", "deviation", {"note": "b"}, "--actor", "user")
        self.assertEqual(self.row()["sessions"], 0)

    def test_a_user_label_is_a_name_not_a_session(self):
        """`user@alice` names a person; counting it would inflate the session count."""
        self.deviate_in("session-1", "a")
        self.append_event("feature/x", "deviation", {"note": "b"},
                          "--actor", "user@alice")
        self.assertEqual(self.row()["sessions"], 1)
        self.assertEqual(self.stats()["totals"]["sessions"], 1)

    def test_a_bare_user_actor_is_not_a_session(self):
        """A `user` role takes no session label, so it cannot land in this count."""
        self.deviate_in("session-1", "a")
        self.append_event("feature/x", "deviation", {"note": "b"},
                          "--actor", "user")
        self.append_event("feature/x", "deviation", {"note": "c"},
                          "--actor", "worker")
        self.assertEqual(self.row()["sessions"], 1)
        self.assertEqual(self.stats()["totals"]["sessions"], 1)

    def test_a_watcher_label_is_not_a_session(self):
        self.append_event("feature/x", "deviation", {"note": "a"},
                          "--actor", "watcher@babysit")
        self.assertEqual(self.row()["sessions"], 0)

    def test_a_session_that_wrote_only_user_rows_is_counted(self):
        """Issue #9: `recorded_by` is a session id, unlike the `user@` label."""
        self.journal(
            "--db", self.db, "append", "--stream", "feature/x", "--type", "deviation",
            "--data", json.dumps({"note": "a"}), "--actor", "user@alice",
            rc=OK, session_env="session-9",
        )
        self.assertEqual(self.row()["sessions"], 1)
        self.assertEqual(self.stats()["totals"]["sessions"], 1)

    def test_implied_phase_transitions_are_counted(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.assertEqual(self.row()["implied_phases"], 1)

    def test_the_totals_brief_bytes_is_the_real_brief(self):
        """Not the sum of the streams: the brief hides and collapses some of them."""
        self.append_event("feature/x", "flow-started", {"request": "build it"})
        self.decide()
        self.append_event("feature/y", "flow-started", {"request": "and this"})
        self.append_event("feature/y", "flow-completed", {})
        rendered = self.journal("--db", self.db, "status", rc=OK).stdout
        totals = self.stats()["totals"]
        self.assertEqual(totals["brief_bytes"], len(rendered.rstrip("\n").encode()))
        self.assertLess(
            totals["brief_bytes"],
            sum(r["stream_render_bytes"] for r in self.stats()["streams"]),
        )

    def test_the_per_stream_number_is_that_streams_own_block(self):
        self.append_event("feature/x", "flow-started", {"request": "build it"})
        self.decide()
        # `--all`: plain `status` prints no unbound stream since #31 (ADR 0024).
        rendered = self.journal("--db", self.db, "status", "--all", rc=OK).stdout
        # The settings lines (#60) belong to the brief, not to the stream's block.
        block = "\n".join(line for line in rendered.rstrip("\n").splitlines()
                          if not line.startswith("settings:")).rstrip("\n")
        row = self.row()
        self.assertEqual(row["stream_render_bytes"], len(block.encode()))
        self.assertNotIn("brief_bytes", row)

    def test_stats_runs_without_the_schema(self):
        """An incomplete install: `stats` printed its counts before the settings lines
        joined the brief, and still does; `brief_bytes` then leaves them out."""
        import shutil

        plugin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(plugin), True)
        shipgate = Path(__file__).resolve().parent.parent
        for part in ("scripts", "hooks"):
            shutil.copytree(shipgate / part, plugin / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        self.append_event("feature/x", "flow-started", {"request": "build it"})
        proc = subprocess.run(
            [sys.executable, str(plugin / "scripts" / "journal.py"), "--db", str(self.db),
             "stats", "--json"],
            capture_output=True, text=True, cwd=str(self.root), timeout=60)
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertIn("brief_bytes", json.loads(proc.stdout)["totals"])

    def test_since_drops_older_events(self):
        self.append_event("feature/x", "deviation", {"note": "old"})
        self.backdate(days=2)
        self.append_event("feature/x", "deviation", {"note": "new"})
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(self.row("feature/x", "--since", cutoff)["events"], 1)

    def test_since_must_be_a_timestamp(self):
        self.journal("--db", self.db, "stats", "--since", "yesterday", rc=USAGE)

    def test_the_stream_filter_narrows_the_report(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.append_event("feature/y", "deviation", {"note": "b"})
        streams = [r["stream"] for r in self.stats("--stream", "feature/y")["streams"]]
        self.assertEqual(streams, ["feature/y"])

    def test_totals_sum_the_streams(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.decide(mode="ask", raised_by="user")
        self.append_event("feature/y", "deviation", {"note": "b"})
        self.decide(mode="ask", raised_by="user", stream="feature/y")
        totals = self.stats()["totals"]
        self.assertEqual(totals["events"], 4)
        self.assertEqual(totals["deviations"], 2)
        self.assertEqual(totals["decisions"], {"ask/user": 2})

    def test_tool_streams_are_not_reported(self):
        self.append_event("shipgate", "setup-completed", {"mode": "create"})
        self.append_event("watch/group-project!42", "baseline", {"iid": 42})
        self.assertEqual(self.stats()["streams"], [])
        self.assertEqual(self.stats()["totals"]["events"], 0)

    def test_human_output_is_a_table_with_a_totals_row(self):
        self.append_event("feature/x", "deviation", {"note": "a"})
        self.decide(mode="ask", raised_by="user")
        proc = self.journal("--db", self.db, "stats", rc=OK)
        self.assertIn("feature/x", proc.stdout)
        self.assertIn("TOTAL", proc.stdout)
        self.assertIn("ask/user", proc.stdout)

    def test_an_empty_journal_says_so(self):
        proc = self.journal("--db", self.db, "stats", rc=OK)
        self.assertIn("no work streams", proc.stdout)




class TestStatsObserved(JournalTestCase):
    """#27 T024 (SC-006): per stream and in total, the `verify-run` rows the journal
    stored as observed, as not observed, the contradicted ones among those, and the
    rows with no `observed` key, which count only as not recorded (FR-014)."""

    def setUp(self):
        super().setUp()
        self.init_db()
        # Inserted past the append, so the rows keep the marks as written: the journal
        # owns `observed` and `contradicted` at append (ADR 0033).
        for stream, marks in (
                ("feature/x", {}),
                ("feature/x", {}),
                ("feature/x", {"observed": True}),
                ("feature/x", {"observed": True}),
                ("feature/x", {"observed": False}),
                ("feature/x", {"observed": False, "contradicted": True}),
                ("feature/y", {"observed": False, "contradicted": True}),
                ("feature/y", {}),
                # A value an older journal let a model type: no mark of this journal.
                ("feature/y", {"observed": "yes"}),
                # Never stored by this journal: observed, and not counted contradicted.
                ("feature/y", {"observed": True, "contradicted": True})):
            insert_legacy_row(self.db, stream, "verify-run",
                              {"outcome": "pass", "task_ids": ["T001"], **marks},
                              "orchestrator")
        insert_legacy_row(self.db, "feature/y", "deviation",
                          {"note": "n", "observed": True}, "orchestrator")

    def stats(self):
        return json.loads(self.journal("--db", self.db, "stats", "--json", rc=OK).stdout)

    def test_the_counts_per_stream_and_in_total(self):
        report = self.stats()
        rows = {row["stream"]: row for row in report["streams"]}
        keys = ("verify_observed", "verify_unobserved", "verify_contradicted",
                "verify_unrecorded")
        self.assertEqual([rows["feature/x"][k] for k in keys], [2, 2, 1, 2])
        self.assertEqual([rows["feature/y"][k] for k in keys], [1, 1, 1, 2])
        self.assertEqual([report["totals"][k] for k in keys], [3, 3, 2, 4])

    def test_each_row_counts_once(self):
        """Observed, not observed and not recorded split the verify runs; the
        contradicted rows are among the not observed."""
        report = self.stats()
        for row in report["streams"] + [report["totals"]]:
            with self.subTest(stream=row.get("stream", "TOTAL")):
                self.assertEqual(row["verify_observed"] + row["verify_unobserved"]
                                 + row["verify_unrecorded"], row["verify_runs"])
                self.assertLessEqual(row["verify_contradicted"], row["verify_unobserved"])

    def test_a_journal_with_old_rows_only(self):
        """Rows from before the mark are not recorded, never not observed."""
        old = self.root / "old.db"
        self.journal("--db", old, "init", rc=OK)
        for _ in range(3):
            insert_legacy_row(old, "feature/z", "verify-run",
                              {"outcome": "pass", "task_ids": ["T001"]}, "orchestrator")
        report = json.loads(self.journal("--db", old, "stats", "--json", rc=OK).stdout)
        totals = report["totals"]
        self.assertEqual([totals["verify_observed"], totals["verify_unobserved"],
                          totals["verify_contradicted"], totals["verify_unrecorded"]],
                         [0, 0, 0, 3])
        text = self.journal("--db", old, "stats", rc=OK).stdout
        self.assertEqual(text.splitlines()[-1],
                         "observed verify runs: 0 of 0 recorded · 0 contradicted · "
                         "3 not recorded")

    def test_the_observed_share_per_stream_and_in_total(self):
        """SC-006: observed over recorded, rounded to two places, null with no row
        that records it; the total from the summed counts, not a sum of shares."""
        db = self.root / "share.db"
        self.journal("--db", db, "init", rc=OK)
        for stream, marks in (("feature/a", {"observed": True}),
                              ("feature/a", {"observed": True}),
                              ("feature/a", {"observed": False}),
                              ("feature/a", {}),
                              ("feature/b", {"observed": False, "contradicted": True}),
                              ("feature/c", {})):
            insert_legacy_row(db, stream, "verify-run",
                              {"outcome": "pass", "task_ids": ["T001"], **marks},
                              "orchestrator")
        report = json.loads(self.journal("--db", db, "stats", "--json", rc=OK).stdout)
        shares = {row["stream"]: row["verify_observed_share"] for row in report["streams"]}
        self.assertEqual(shares, {"feature/a": 0.67, "feature/b": 0.0, "feature/c": None})
        self.assertEqual(report["totals"]["verify_observed_share"], 0.5)
        lines = self.journal("--db", db, "stats", rc=OK).stdout.splitlines()
        at = lines[0].split().index("obs")
        self.assertEqual({line.split()[0]: line.split()[at] for line in lines[1:5]},
                         {"feature/a": "2/3", "feature/b": "0/1", "feature/c": "0/0",
                          "TOTAL": "2/4"})
        empty = self.root / "empty.db"
        self.journal("--db", empty, "init", rc=OK)
        report = json.loads(self.journal("--db", empty, "stats", "--json", rc=OK).stdout)
        self.assertIsNone(report["totals"]["verify_observed_share"])

    def test_the_text_columns_and_the_footer(self):
        lines = self.journal("--db", self.db, "stats", rc=OK).stdout.splitlines()
        header = lines[0].split()
        at = header.index("vfy")
        self.assertEqual(header[at:at + 3], ["vfy", "obs", "ctr"])
        cells = {line.split()[0]: line.split() for line in lines[1:4]}
        # `obs` is observed / recorded (observed and not observed), so each stream's
        # share reads off its row (SC-006).
        self.assertEqual(cells["feature/x"][at:at + 3], ["6", "2/4", "1"])
        self.assertEqual(cells["feature/y"][at:at + 3], ["4", "1/2", "1"])
        self.assertEqual(cells["TOTAL"][at:at + 3], ["10", "3/6", "2"])
        self.assertEqual(lines[-1], "observed verify runs: 3 of 6 recorded · "
                                    "2 contradicted · 4 not recorded")


# The labels of the doctor report of 0.35.0, in order, for a project with a sidecar and
# no Stop gate record (#26 T002). A later block comes after them.
DOCTOR_LABELS_0_35 = [
    "database", "integrity_check", "journal_mode", "schema_version", "pending migr.",
    "events", "sidecar", "sidecar version", "stray keys", "settings", "stop gate", "",
]


class TestPinDoctorReport(JournalTestCase):
    """#26 T002: the report's lines of 0.35.0 stay first and in order."""

    def test_the_lines_of_today_come_first(self):
        self.init_db()
        claude = self.root / ".claude"
        claude.mkdir()
        (claude / "shipgate.json").write_text(
            json.dumps({"version": 1, "db": str(self.db)}), encoding="utf-8")
        proc = self.journal("--db", self.db, "doctor", rc=OK)
        lines = proc.stdout.splitlines()
        labels = [line.split(" : ", 1)[0].strip() if " : " in line else line.strip()
                  for line in lines]
        self.assertEqual(labels[:len(DOCTOR_LABELS_0_35)][:-1], DOCTOR_LABELS_0_35[:-1])
        self.assertTrue(lines[len(DOCTOR_LABELS_0_35) - 1].startswith(
            "                  last block: "))


# ---------------------------------------------------------------------------
# #26 T015: the evidence block (FR-016, SC-005)
# ---------------------------------------------------------------------------

J = load_journal_module()
OLD = time.time() - 40 * 86400
OTHER_KEY = "0123456789ab"
NOTE = ("  note          : another Claude config directory or another machine keeps its "
        "own evidence root, which this report does not read")


def _snapshot(root):
    """Every entry under ROOT with its mode, size and mtime, and the bytes of a file or
    the target of a link. A link is listed, never followed."""
    out = []
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(directory, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                body = os.readlink(path)
            elif stat.S_ISREG(st.st_mode):
                body = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            else:
                body = None
            out.append((path, st.st_mode, st.st_size, st.st_mtime_ns, body))
    return sorted(out)


def runs_block_at(lines):
    """The index of the runs block's first line in a doctor report."""
    return next(i for i, line in enumerate(lines) if line.startswith("runs root"))


class TestDoctorEvidence(JournalTestCase):
    """#26 T015: after its other lines, `doctor` reports the evidence root of this Claude
    config directory: this project and the whole root, what the next prune would remove
    and refuse, and that another root goes unread. It deletes nothing."""

    LIVE = "feature/live"
    DONE = "feature/done"

    def setUp(self):
        super().setUp()
        self.config = self.root / "config"
        self.config.mkdir()
        self.evidence = self.config / "shipgate" / "evidence"
        self.key = hashlib.sha256(
            os.path.realpath(self.db).encode("utf-8")).hexdigest()[:12]
        self.run_j("init")
        for stream, etype, data in ((self.LIVE, "flow-started", {"request": "r"}),
                                    (self.DONE, "flow-started", {"request": "r"}),
                                    (self.DONE, "flow-completed", {"reason": "merged"})):
            self.run_j("append", "--stream=" + stream, "--type", etype,
                       "--data", json.dumps(data))

    # -- helpers ---------------------------------------------------------

    def env(self):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        return env

    def run_j(self, *args, env=None):
        proc = run_journal(["--db", self.db, *args], cwd=self.root,
                           env=env or self.env())
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        return proc.stdout

    def doctor(self, env=None):
        """The report's lines up to the runs block (#27 T023), which TestDoctorRuns
        pins."""
        lines = self.run_j("doctor", env=env).splitlines()
        return lines[:runs_block_at(lines)]

    def doctor_json(self, env=None):
        return json.loads(self.run_j("doctor", "--json", env=env))["evidence"]

    def plant(self, *parts, size=100, old=False):
        path = self.evidence.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        if old:
            os.utime(path, (OLD, OLD))
        return path

    def real(self, *parts):
        return os.path.join(os.path.realpath(self.evidence), *parts)

    def plant_tree(self):
        """This project: a live stream with a new and an old file, the finished stream
        and an unknown stream; another project with an old file; a note in the root."""
        self.plant(self.key, "feature%2Flive", "T001-390.png", size=1000)
        self.plant(self.key, "feature%2Flive", "T001-1280.png", size=2000, old=True)
        self.plant(self.key, "feature%2Fdone", "T002-390.png", size=500)
        self.plant(self.key, "feature%2Fgone", "T003-390.png", size=548)
        self.plant(OTHER_KEY, "feat%2Fx", "T001-390.png", size=2000, old=True)
        self.plant("notes.txt", size=1)

    # -- the text ----------------------------------------------------------

    def test_a_root_with_files(self):
        self.plant_tree()
        lines = self.doctor()
        self.assertEqual(lines[-6:], [
            f"evidence root   : {self.real()} (this Claude config directory)",
            f"  this project  : {self.key} · 3 streams · 4 files · 4.0 KB · oldest 40 days",
            "  whole root    : 2 projects · 5 files · 5.9 KB · oldest 40 days",
            "  next prune    : 2 directories of finished or unknown streams · 2 files "
            "over 30 days",
            f"  refused       : 1 entry outside the layout (first: {self.real('notes.txt')})",
            NOTE,
        ])
        self.assertTrue(lines[-7].startswith("                  last block: "), lines)

    def test_the_block_follows_the_off_vocabulary_lines(self):
        insert_legacy_row(self.db, self.LIVE, "no-such-event", {}, "orchestrator")
        self.plant(self.key, "feature%2Flive", "T001-390.png")
        lines = self.doctor()
        at = next(i for i, line in enumerate(lines) if line.startswith("evidence root"))
        self.assertTrue(lines[at - 2].startswith("off-vocabulary  : no-such-event x1"))
        self.assertTrue(lines[at - 1].startswith("                  these events are inert"))
        self.assertEqual(lines[at + 1:], [
            f"  this project  : {self.key} · 1 stream · 1 file · 100 B · oldest 0 days",
            "  whole root    : 1 project · 1 file · 100 B · oldest 0 days",
            "  next prune    : 0 directories of finished or unknown streams · 0 files "
            "over 30 days",
            NOTE,
        ])

    def test_an_empty_root(self):
        self.evidence.mkdir(parents=True)
        self.assertEqual(self.doctor()[-5:], [
            f"evidence root   : {self.real()} (this Claude config directory)",
            f"  this project  : {self.key} · 0 streams · no files",
            "  whole root    : 0 projects · no files",
            "  next prune    : 0 directories of finished or unknown streams · 0 files "
            "over 30 days",
            NOTE,
        ])

    def test_a_missing_root(self):
        lines = self.doctor()
        self.assertEqual(lines[-2:], [f"evidence root   : {self.real()} (none yet)", NOTE])
        self.assertTrue(lines[-3].startswith("                  last block: "), lines)
        self.assertFalse(os.path.lexists(self.config / "shipgate"))

    def test_no_config_directory_and_no_home(self):
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        lines = self.doctor(env=env)
        self.assertEqual(lines[-1], "evidence root   : none (no CLAUDE_CONFIG_DIR, no HOME)")
        self.assertTrue(lines[-2].startswith("                  last block: "), lines)
        self.assertEqual(self.doctor_json(env=env), {
            "root": None, "exists": False, "project": None, "whole": None,
            "next_prune": None, "refused": None})

    def test_the_sizes(self):
        for size, text in ((0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"),
                           (12595, "12.3 KB"), (4 * 1024 * 1024, "4.0 MB"),
                           (1024 * 1024 - 1, "1.0 MB"), (3 * 1024 ** 3, "3.0 GB")):
            with self.subTest(size=size):
                self.assertEqual(J._evidence_size(size), text)

    def test_refused_entries_and_links(self):
        """Every entry the prune would refuse is counted once: a link at each level,
        a file of another name, a directory of another name, and a directory where a
        file belongs; the first in sorted order is named."""
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "T001-390.png").write_bytes(b"x")
        live = self.plant(self.key, "feature%2Flive", "T001-390.png").parent
        os.symlink(outside / "T001-390.png", live / "T001-1280.png")
        os.symlink(outside, self.evidence / "fedcba987654")
        os.symlink(outside, self.evidence / self.key / "feature%2Flinked")
        (live / "T002-390.png").mkdir()
        self.plant(self.key, "stray.png")
        self.plant("random", "T001-390.png")
        refused = sorted([
            self.real(self.key, "feature%2Flive", "T001-1280.png"),
            self.real("fedcba987654"), self.real(self.key, "feature%2Flinked"),
            self.real(self.key, "feature%2Flive", "T002-390.png"),
            self.real(self.key, "stray.png"), self.real("random")])
        self.assertEqual(self.doctor()[-2], f"  refused       : 6 entries outside the "
                                            f"layout (first: {refused[0]})")
        self.assertEqual(self.doctor_json()["refused"], {"count": 6, "first": refused[0]})
        self.assertEqual(os.listdir(outside), ["T001-390.png"])

    # -- the JSON -------------------------------------------------------------

    def test_the_json_of_a_root_with_files(self):
        self.plant_tree()
        self.assertEqual(self.doctor_json(), {
            "root": self.real(), "exists": True,
            "project": {"key": self.key, "streams": 3, "files": 4, "bytes": 4048,
                        "oldest_days": 40},
            "whole": {"projects": 2, "files": 5, "bytes": 6048, "oldest_days": 40},
            "next_prune": {"directories": 2, "files": 2},
            "refused": {"count": 1, "first": self.real("notes.txt")},
        })

    def test_the_json_of_an_empty_and_a_missing_root(self):
        self.assertEqual(self.doctor_json(), {
            "root": self.real(), "exists": False, "project": None, "whole": None,
            "next_prune": None, "refused": None})
        self.evidence.mkdir(parents=True)
        self.assertEqual(self.doctor_json(), {
            "root": self.real(), "exists": True,
            "project": {"key": self.key, "streams": 0, "files": 0, "bytes": 0,
                        "oldest_days": None},
            "whole": {"projects": 0, "files": 0, "bytes": 0, "oldest_days": None},
            "next_prune": {"directories": 0, "files": 0},
            "refused": {"count": 0, "first": None}})

    # -- read-only ------------------------------------------------------------

    def test_the_doctor_changes_nothing_on_disk(self):
        """A root with old files, a finished stream's directory and links: every entry
        keeps its bytes, size and mtime, and so does the target of each link."""
        self.plant_tree()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "T009-390.png").write_bytes(b"y")
        os.utime(outside / "T009-390.png", (OLD, OLD))
        os.symlink(outside / "T009-390.png",
                   self.evidence / self.key / "feature%2Fdone" / "T009-390.png")
        os.symlink(outside, self.evidence / "fedcba987654")
        before = (_snapshot(str(self.config)), _snapshot(str(outside)))
        self.doctor()
        self.doctor_json()
        self.assertEqual((_snapshot(str(self.config)), _snapshot(str(outside))), before)

    def test_the_doctor_calls_no_write(self):
        """In process, with every call that removes, makes, renames or touches an entry
        patched to fail the test."""
        self.plant_tree()
        os.symlink(self.root, self.evidence / "fedcba987654")

        def forbidden(*args, **kwargs):
            raise AssertionError(f"the doctor wrote to the disk: {args!r}")

        out = io.StringIO()
        cwd = os.getcwd()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}))
            stack.callback(os.chdir, cwd)
            os.chdir(str(self.root))
            for name in ("unlink", "remove", "rmdir", "removedirs", "mkdir", "makedirs",
                         "replace", "rename", "utime"):
                stack.enter_context(mock.patch.object(os, name, side_effect=forbidden))
            stack.enter_context(contextlib.redirect_stdout(out))
            rc = J.main(["--db", str(self.db), "doctor"])
        self.assertEqual(rc, OK)
        self.assertIn(f"evidence root   : {self.real()} (this Claude config directory)",
                      out.getvalue().splitlines())

    def test_the_survey_and_the_prune_agree(self):
        """What the doctor says the next prune removes and refuses is what it removes
        and refuses. A finished stream's directory that holds a link stays with its new
        file, and only its old file goes, as in a live directory."""
        self.plant_tree()
        self.plant(self.key, "feature%2Flive", "T005-390.png", old=True)
        self.plant(OTHER_KEY, "feat%2Fx", "T002-390.png")
        done = self.evidence / self.key / "feature%2Fdone"
        os.symlink(self.root, done / "T002-1280.png")
        self.plant(self.key, "feature%2Fdone", "T004-390.png", old=True)
        conn = J.connect(self.db)
        try:
            survey = J.survey_evidence(str(self.evidence), self.key, conn)
            self.assertEqual(survey["next_prune"], {"directories": 1, "files": 4})
            report = J.prune_evidence(str(self.evidence), self.key, conn)
            self.assertEqual(report["warnings"], [])
            self.assertEqual(len(report["removed_dirs"]),
                             survey["next_prune"]["directories"])
            self.assertEqual(len(report["removed_files"]), survey["next_prune"]["files"])
            refused = sorted(path for path, _ in report["refused"])
            self.assertEqual(survey["refused"],
                             {"count": len(refused), "first": refused[0]})
            after = J.survey_evidence(str(self.evidence), self.key, conn)
        finally:
            conn.close()
        self.assertEqual(after["next_prune"], {"directories": 0, "files": 0})
        self.assertEqual(after["refused"], survey["refused"])
        self.assertEqual(sorted(os.listdir(done)), ["T002-1280.png", "T002-390.png"])

    def test_the_survey_and_the_prune_agree_on_a_directory_they_keep(self):
        """A finished stream's directory with a `Thumbs.db` beside a new file: the
        survey predicts no removal, and the prune removes nothing from it."""
        gone = self.plant(self.key, "feature%2Fgone", "T003-390.png").parent
        self.plant(self.key, "feature%2Fgone", "Thumbs.db")
        conn = J.connect(self.db)
        try:
            survey = J.survey_evidence(str(self.evidence), self.key, conn)
            self.assertEqual(survey["next_prune"], {"directories": 0, "files": 0})
            self.assertEqual(survey["refused"],
                             {"count": 1, "first": self.real(self.key, "feature%2Fgone",
                                                             "Thumbs.db")})
            report = J.prune_evidence(str(self.evidence), self.key, conn)
        finally:
            conn.close()
        self.assertEqual(report, {
            "removed_dirs": [], "removed_files": [], "warnings": [],
            "refused": [(self.real(self.key, "feature%2Fgone", "Thumbs.db"),
                         "not in the evidence layout")]})
        self.assertEqual(sorted(os.listdir(gone)), ["T003-390.png", "Thumbs.db"])

    # -- the Finder file (T023) ---------------------------------------------------

    def plant_finder_files(self):
        """A `.DS_Store` in this project's directory, in each of its stream directories,
        in the other project's directory and in its stream directory."""
        for parts in ((self.key,), (self.key, "feature%2Flive"),
                      (self.key, "feature%2Fdone"), (self.key, "feature%2Fgone"),
                      (OTHER_KEY,), (OTHER_KEY, "feat%2Fx")):
            self.plant(*parts, ".DS_Store", size=6148)

    def test_a_finder_file_is_no_refusal_no_stream_and_no_evidence(self):
        """A `.DS_Store` in a project or a stream directory changes no count: it is no
        refused entry, no stream, no evidence file and no byte of evidence. One in the
        root is refused."""
        self.plant_tree()
        self.plant_finder_files()
        lines = self.doctor()
        self.assertEqual(lines[-6:], [
            f"evidence root   : {self.real()} (this Claude config directory)",
            f"  this project  : {self.key} · 3 streams · 4 files · 4.0 KB · oldest 40 days",
            "  whole root    : 2 projects · 5 files · 5.9 KB · oldest 40 days",
            "  next prune    : 2 directories of finished or unknown streams · 2 files "
            "over 30 days",
            f"  refused       : 1 entry outside the layout (first: {self.real('notes.txt')})",
            NOTE,
        ])
        self.plant(".DS_Store", size=6148)
        self.assertEqual(self.doctor_json()["refused"],
                         {"count": 2, "first": self.real(".DS_Store")})

    def test_the_survey_and_the_prune_agree_with_finder_files(self):
        """A `.DS_Store` beside the files of a finished and of an unknown stream does
        not keep their directories; the survey predicts what the prune removes, and the
        live stream's directory keeps its own."""
        self.plant_tree()
        self.plant(OTHER_KEY, "feat%2Fx", "T002-390.png")
        self.plant_finder_files()
        conn = J.connect(self.db)
        try:
            survey = J.survey_evidence(str(self.evidence), self.key, conn)
            self.assertEqual(survey["next_prune"], {"directories": 2, "files": 2})
            report = J.prune_evidence(str(self.evidence), self.key, conn)
            self.assertEqual(report["warnings"], [])
            self.assertEqual(sorted(path for path, _ in report["removed_dirs"]), [
                self.real(self.key, "feature%2Fdone"),
                self.real(self.key, "feature%2Fgone")])
            self.assertEqual(len(report["removed_files"]), survey["next_prune"]["files"])
            self.assertEqual(report["refused"],
                             [(self.real("notes.txt"), "not in the evidence layout")])
            self.assertEqual(survey["refused"],
                             {"count": 1, "first": self.real("notes.txt")})
            after = J.survey_evidence(str(self.evidence), self.key, conn)
        finally:
            conn.close()
        self.assertEqual(after["next_prune"], {"directories": 0, "files": 0})
        self.assertEqual(sorted(os.listdir(self.evidence / self.key)),
                         [".DS_Store", "feature%2Flive"])
        self.assertEqual(sorted(os.listdir(self.evidence / self.key / "feature%2Flive")),
                         [".DS_Store", "T001-390.png"])


# ---------------------------------------------------------------------------
# #27 T023: the runs block (FR-011, SC-005)
# ---------------------------------------------------------------------------

RUNS_OLD = time.time() - 8 * 86400 - 3600


class TestDoctorRuns(JournalTestCase):
    """#27 T023: after the evidence block, `doctor` reports the run log of the Bash
    hooks in this Claude config directory: the files, their size, what the next prune
    deletes and the names it refuses. It deletes nothing."""

    def setUp(self):
        super().setUp()
        self.config = self.root / "config"
        self.config.mkdir()
        self.runs = self.config / "shipgate" / "runs"
        self.shown = os.path.join(os.path.realpath(self.runs.parent), "runs")
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "s9.jsonl").write_bytes(b"x" * 7)
        self.run_j("init")

    def env(self):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        return env

    def run_j(self, *args, env=None):
        proc = run_journal(["--db", self.db, *args], cwd=self.root,
                           env=env or self.env())
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        return proc.stdout

    def doctor(self, env=None):
        return self.run_j("doctor", env=env).splitlines()

    def doctor_json(self, env=None):
        return json.loads(self.run_j("doctor", "--json", env=env))["runs"]

    def plant(self, name, size, old=False):
        self.runs.mkdir(parents=True, exist_ok=True)
        path = self.runs / name
        path.write_bytes(b"x" * size)
        if old:
            os.utime(path, (RUNS_OLD, RUNS_OLD))
        return path

    def plant_store(self):
        """A fresh log and two old ones, a foreign name and a link."""
        self.plant("s1.jsonl", 100)
        self.plant("s1.jsonl.1", 200, old=True)
        self.plant("s2.jsonl", 300, old=True)
        self.plant("notes.txt", 1, old=True)
        os.symlink(self.outside / "s9.jsonl", self.runs / "s3.jsonl")

    def test_a_root_with_files(self):
        self.plant_store()
        lines = self.doctor()
        self.assertEqual(lines[-4:], [
            f"runs root       : {self.shown} (this Claude config directory)",
            "  run logs      : 3 files · 600 B · oldest 8 days",
            "  next prune    : 2 files over 7 days",
            f"  refused       : 2 entries outside the layout (first: "
            f"{os.path.join(self.shown, 'notes.txt')})",
        ])
        self.assertEqual(lines[-5], NOTE)

    def test_the_json_of_a_root_with_files(self):
        self.plant_store()
        self.assertEqual(self.doctor_json(), {
            "root": self.shown, "exists": True,
            "logs": {"files": 3, "bytes": 600, "oldest_days": 8},
            "next_prune": {"files": 2},
            "refused": {"count": 2, "first": os.path.join(self.shown, "notes.txt")},
        })

    def test_an_empty_root(self):
        self.runs.mkdir(parents=True)
        self.assertEqual(self.doctor()[-3:], [
            f"runs root       : {self.shown} (this Claude config directory)",
            "  run logs      : no files",
            "  next prune    : 0 files over 7 days",
        ])
        self.assertEqual(self.doctor_json(), {
            "root": self.shown, "exists": True,
            "logs": {"files": 0, "bytes": 0, "oldest_days": None},
            "next_prune": {"files": 0}, "refused": {"count": 0, "first": None}})

    def test_a_missing_root(self):
        lines = self.doctor()
        self.assertEqual(lines[-1], f"runs root       : {self.shown} (none yet)")
        self.assertEqual(lines[-2], NOTE)
        self.assertEqual(self.doctor_json(), {
            "root": self.shown, "exists": False, "logs": None, "next_prune": None,
            "refused": None})
        self.assertFalse(os.path.lexists(self.config / "shipgate"))

    def test_no_config_directory_and_no_home(self):
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        lines = self.doctor(env=env)
        self.assertEqual(lines[-1], "runs root       : none (no CLAUDE_CONFIG_DIR, no HOME)")
        self.assertEqual(lines[-2], "evidence root   : none (no CLAUDE_CONFIG_DIR, no HOME)")
        self.assertEqual(self.doctor_json(env=env), {
            "root": None, "exists": False, "logs": None, "next_prune": None,
            "refused": None})

    def test_a_link_in_place_of_the_root(self):
        """The journal never reads or prunes through it, and says so."""
        self.runs.parent.mkdir(parents=True)
        os.symlink(self.outside, self.runs)
        self.assertEqual(self.doctor()[-1],
                         f"runs root       : {self.shown} (not a directory: the journal "
                         "reads and prunes nothing there)")
        self.assertEqual(self.doctor_json(), {
            "root": self.shown, "exists": False, "logs": None, "next_prune": None,
            "refused": {"count": 1, "first": self.shown}})

    def test_the_doctor_changes_nothing_on_disk(self):
        self.plant_store()
        before = (_snapshot(str(self.config)), _snapshot(str(self.outside)))
        self.doctor()
        self.doctor_json()
        self.assertEqual((_snapshot(str(self.config)), _snapshot(str(self.outside))),
                         before)

    def test_the_doctor_calls_no_write(self):
        self.plant_store()

        def forbidden(*args, **kwargs):
            raise AssertionError(f"the doctor wrote to the disk: {args!r}")

        out = io.StringIO()
        cwd = os.getcwd()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(
                os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)}))
            stack.callback(os.chdir, cwd)
            os.chdir(str(self.root))
            for name in ("unlink", "remove", "rmdir", "removedirs", "mkdir", "makedirs",
                         "replace", "rename", "utime"):
                stack.enter_context(mock.patch.object(os, name, side_effect=forbidden))
            stack.enter_context(contextlib.redirect_stdout(out))
            rc = J.main(["--db", str(self.db), "doctor"])
        self.assertEqual(rc, OK)
        self.assertIn("  next prune    : 2 files over 7 days", out.getvalue().splitlines())

    def test_the_survey_and_the_prune_agree(self):
        """What the doctor says the next prune deletes and refuses is what it deletes
        and keeps."""
        self.plant_store()
        (self.runs / "d.jsonl").mkdir()
        survey = J.survey_runs(str(self.runs))
        self.assertEqual(survey["next_prune"], {"files": 2})
        self.assertEqual(survey["refused"]["count"], 3)
        report = J.prune_runs(str(self.runs))
        self.assertEqual(report["warnings"], [])
        self.assertEqual(len(report["removed"]), survey["next_prune"]["files"])
        after = J.survey_runs(str(self.runs))
        self.assertEqual(after["next_prune"], {"files": 0})
        self.assertEqual(after["refused"], survey["refused"])
        self.assertEqual(after["logs"]["files"], 1)
        self.assertEqual(sorted(os.listdir(self.runs)),
                         ["d.jsonl", "notes.txt", "s1.jsonl", "s3.jsonl"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
