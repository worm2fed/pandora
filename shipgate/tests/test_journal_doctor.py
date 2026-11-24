#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: ``doctor`` and ``stats``.

Split out of ``test_journal.py`` (#61), which holds the helpers and fixtures.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_journal import JournalTestCase, OK, USAGE


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
                          {"outcome": "pass", "task_ids": ["T001", "T002"]})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        row = self.row()
        self.assertEqual(row["deviations"], 1)
        self.assertEqual(row["verify_runs"], 1)
        self.assertEqual(row["tasks_done"], 1)

    def test_a_task_re_recorded_after_review_is_one_task_done(self):
        """`tasks_done` counts distinct ids, as the brief does."""
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001"]})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.assertEqual(self.row()["tasks_done"], 1)

    def test_a_task_verified_twice_is_counted_once(self):
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001", "T002"]})
        self.append_event("feature/x", "verify-run",
                          {"outcome": "fail", "task_ids": ["T001"]})
        self.assertEqual(self.row()["tasks_reverified"], 1)

    def test_a_task_listed_twice_in_one_run_is_not_reverified(self):
        """One run naming a task twice verified it once — that is not a second round."""
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001", "T001"]})
        self.assertEqual(self.row()["tasks_reverified"], 0)

    def test_review_rounds_and_feedback(self):
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001"]})
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
                          {"outcome": "pass", "task_ids": ["T001"]})
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
