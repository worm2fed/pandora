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

    # -- the config's Knowledge base against the sidecar (FR-014) ---------

    def write_config(self, *bullets):
        text = "# shipgate configuration\n\n## Knowledge base\n\n"
        text += "".join(f"- {bullet}\n" for bullet in bullets)
        text += "\n## Journal\n\n- Database: `.claude/shipgate.db`\n"
        self.write(".claude/shipgate.md", text)

    def doctor_config(self):
        proc = self.journal("--db", self.db, "doctor", "--json", rc=OK)
        return json.loads(proc.stdout)["config"]

    def test_a_ledger_the_config_names_and_the_sidecar_lacks_is_drift(self):
        """The case seen in 3 of 7 sidecars: `status` then counts the default ledger."""
        self.write_sidecar({"version": 1, "db": str(self.db)})
        self.write_config("Ledger: `notes/ledger.md` (repo root). Promotion targets: drop.")
        config = self.doctor_config()
        self.assertTrue(config["found"])
        self.assertEqual(
            config["path"], str(self.root.resolve() / ".claude" / "shipgate.md")
        )
        self.assertEqual(config["ledger"], {
            "config": "notes/ledger.md",
            "sidecar": None,
            "drift": "config names ledger `notes/ledger.md`; the sidecar has no ledger key",
        })
        self.assertEqual(config["drift"], [config["ledger"]["drift"]])

    def test_a_ledger_that_differs_is_drift(self):
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "docs/ledger.md"})
        self.write_config("Ledger: `notes/ledger.md`")
        ledger = self.doctor_config()["ledger"]
        self.assertEqual(ledger["sidecar"], "docs/ledger.md")
        self.assertEqual(
            ledger["drift"],
            "ledger differs: config `notes/ledger.md`, sidecar `docs/ledger.md`",
        )

    def test_a_ledger_that_differs_only_by_a_dot_slash_agrees(self):
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "docs/ledger.md"})
        self.write_config("Ledger: `./docs/ledger.md`")
        config = self.doctor_config()
        self.assertIsNone(config["ledger"]["drift"])
        self.assertEqual(config["drift"], [])

    def test_a_sidecar_ledger_the_config_does_not_name_is_drift(self):
        """Only off the default: a sidecar naming `docs/ledger.md` says what absence says."""
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "notes/ledger.md"})
        self.write_config("PRD home: `docs/prd/`")
        config = self.doctor_config()
        self.assertEqual(config["section"], "present")
        ledger = config["ledger"]
        self.assertIsNone(ledger["config"])
        self.assertEqual(
            ledger["drift"],
            "sidecar names ledger `notes/ledger.md`; the config names none "
            "(default docs/ledger.md)",
        )
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "docs/ledger.md"})
        self.assertIsNone(self.doctor_config()["ledger"]["drift"])

    def test_a_home_whose_directory_differs_is_drift(self):
        self.write_sidecar({
            "version": 1, "db": str(self.db),
            "artifact_homes": {"prd": "src/docs/prd/*.md"},
        })
        self.write_config("PRD home: `docs/prd/`", "ADR home: `design/adr/`")
        config = self.doctor_config()
        self.assertEqual(config["homes"]["prd"], {
            "config": "docs/prd/",
            "sidecar": "src/docs/prd/*.md",
            "compared": True,
            "drift": "prd home differs: config `docs/prd/`, sidecar glob `src/docs/prd/*.md`",
        })
        # A home the sidecar does not name is compared with the default glob.
        self.assertEqual(config["homes"]["adr"]["sidecar"], None)
        self.assertEqual(
            config["homes"]["adr"]["drift"],
            "adr home differs: config `design/adr/`, sidecar glob `docs/adr/*.md`",
        )
        self.assertEqual(config["drift"], [
            config["homes"]["prd"]["drift"], config["homes"]["adr"]["drift"],
        ])

    def test_a_config_and_sidecar_that_agree_have_no_drift(self):
        """A `<plugin>` segment reads as the glob's `*`; a trailing `/` is no difference."""
        self.write_sidecar({
            "version": 1, "db": str(self.db), "ledger": "docs/ledger.md",
            "artifact_homes": {
                "prd": "*/docs/prd/*.md", "adr": "docs/adr/*.md",
                "worklog": "*/docs/prd/*.worklog.md",
            },
        })
        self.write_config(
            "PRD home: `<plugin>/docs/prd/` — artifacts live with the plugin.",
            "ADR home: `docs/adr/` — sequential `NNNN-<title>.md`.",
            "Worklog home: `<plugin>/docs/prd`",
            "Ledger: `docs/ledger.md` (repo root, shared across plugins).",
        )
        config = self.doctor_config()
        self.assertEqual(config["drift"], [])
        self.assertIsNone(config["ledger"]["drift"])
        for key in ("prd", "adr", "worklog"):
            self.assertTrue(config["homes"][key]["compared"], msg=key)
            self.assertIsNone(config["homes"][key]["drift"], msg=key)
        self.assertEqual(config["homes"]["prd"]["config"], "<plugin>/docs/prd/")

    def test_a_home_written_as_prose_is_not_compared(self):
        """`<name>.worklog.md` names a file pattern, not a directory: nothing to compare."""
        self.write_sidecar({
            "version": 1, "db": str(self.db),
            "artifact_homes": {"worklog": "src/docs/prd/*.worklog.md"},
        })
        self.write_config("Worklog home: beside the PRD as `<name>.worklog.md`.")
        config = self.doctor_config()
        worklog = config["homes"]["worklog"]
        self.assertFalse(worklog["compared"])
        self.assertIsNone(worklog["drift"])
        self.assertEqual(worklog["sidecar"], "src/docs/prd/*.worklog.md")
        # An absent value is not compared either.
        self.assertFalse(config["homes"]["prd"]["compared"])
        self.assertIsNone(config["homes"]["prd"]["config"])
        self.assertEqual(config["drift"], [])

    def test_a_missing_config_file_is_reported_as_not_found(self):
        """The block keeps one shape whether the file exists or not."""
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "notes/ledger.md"})
        config = self.doctor_config()
        path = self.root.resolve() / ".claude" / "shipgate.md"
        empty_home = {"config": None, "sidecar": None, "compared": False, "drift": None}
        self.assertEqual(config, {
            "found": False,
            "path": str(path),
            "inherit": None,
            "section": "absent",
            "ledger": {"config": None, "sidecar": None, "drift": None},
            "homes": {"prd": empty_home, "adr": empty_home, "worklog": empty_home},
            "drift": [],
        })
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        self.assertIn(f"config          : {path} — not found", text.splitlines())
        self.assertNotIn("drift           :", text)

    def test_a_knowledge_base_another_layer_owns_is_no_drift(self):
        """ADR 0018: with no `## Knowledge base` in the project file, the umbrella's or
        the user's file supplies it, and the sidecar mirrors that value."""
        self.write_sidecar({
            "version": 1, "db": str(self.db), "ledger": "notes/ledger.md",
            "artifact_homes": {"prd": "src/docs/prd/*.md"},
        })
        self.write(
            ".claude/shipgate.md",
            "# shipgate configuration\n\n## Journal\n\n- Database: `.claude/shipgate.db`\n",
        )
        config = self.doctor_config()
        self.assertTrue(config["found"])
        self.assertEqual(config["section"], "absent")
        self.assertEqual(config["ledger"], {
            "config": None, "sidecar": "notes/ledger.md", "drift": None,
        })
        self.assertEqual(config["homes"]["prd"], {
            "config": None, "sidecar": "src/docs/prd/*.md", "compared": False, "drift": None,
        })
        self.assertEqual(config["drift"], [])
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        path = self.root.resolve() / ".claude" / "shipgate.md"
        self.assertIn(
            f"config          : {path} — no Knowledge base section", text.splitlines()
        )
        self.assertNotIn(f"config          : {path} — agrees", text.splitlines())

    def test_a_knowledge_base_of_placeholders_only_is_absent(self):
        """A section copied from the template and left unfilled names nothing."""
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "notes/ledger.md"})
        self.write_config("PRD home: <path, e.g. `docs/prd/`>", "Ledger: <path>")
        config = self.doctor_config()
        self.assertEqual(config["section"], "absent")
        self.assertIsNone(config["ledger"]["config"])
        self.assertFalse(config["homes"]["prd"]["compared"])
        self.assertEqual(config["drift"], [])

    def test_a_recursive_sidecar_glob_compares_as_its_root_directory(self):
        """`docs/prd/**/*.md` is a deliberate glob over subfolders, not a different home."""
        self.write_sidecar({
            "version": 1, "db": str(self.db),
            "artifact_homes": {
                "prd": "docs/prd/**/*.md", "adr": "*/docs/adr/**/**/*.md",
            },
        })
        self.write_config("PRD home: `docs/prd/`", "ADR home: `<plugin>/docs/adr/`")
        config = self.doctor_config()
        for key in ("prd", "adr"):
            self.assertTrue(config["homes"][key]["compared"], msg=key)
            self.assertIsNone(config["homes"][key]["drift"], msg=key)
        self.assertEqual(config["drift"], [])

    def test_without_a_sidecar_the_config_values_are_reported_without_drift(self):
        self.write_config("Ledger: `notes/ledger.md`", "PRD home: `src/docs/prd/`")
        config = self.doctor_config()
        self.assertTrue(config["found"])
        self.assertEqual(config["inherit"], "umbrella")
        self.assertEqual(config["ledger"], {
            "config": "notes/ledger.md", "sidecar": None, "drift": None,
        })
        self.assertEqual(config["homes"]["prd"], {
            "config": "src/docs/prd/", "sidecar": None, "compared": False, "drift": None,
        })
        for key in ("adr", "worklog"):
            self.assertIsNone(config["homes"][key]["sidecar"], msg=key)
            self.assertFalse(config["homes"][key]["compared"], msg=key)
        self.assertEqual(config["drift"], [])
        text = self.journal("--db", self.db, "doctor", rc=OK).stdout
        path = self.root.resolve() / ".claude" / "shipgate.md"
        self.assertIn(f"config          : {path} — no sidecar to compare", text.splitlines())
        self.assertNotIn(f"config          : {path} — agrees", text.splitlines())

    def test_the_inherit_mode_is_reported(self):
        self.write_sidecar({"version": 1, "db": str(self.db)})
        self.write(
            ".claude/shipgate.md",
            "# shipgate configuration\n\n- Inherit: `none`\n\n## Knowledge base\n\n",
        )
        self.assertEqual(self.doctor_config()["inherit"], "none")
        self.write(".claude/shipgate.md", "# shipgate configuration\n")
        self.assertEqual(self.doctor_config()["inherit"], "umbrella")

    def test_the_text_form_carries_one_line_per_drift(self):
        self.write_sidecar({
            "version": 1, "db": str(self.db),
            "artifact_homes": {"prd": "src/docs/prd/*.md"},
        })
        self.write_config("Ledger: `notes/ledger.md`", "PRD home: `docs/prd/`")
        proc = self.journal("--db", self.db, "doctor", rc=OK)
        path = self.root.resolve() / ".claude" / "shipgate.md"
        lines = proc.stdout.splitlines()
        self.assertIn(f"config          : {path} — DRIFT (2)", lines)
        self.assertEqual(
            [line for line in lines if line.startswith("drift           : ")],
            [
                "drift           : config names ledger `notes/ledger.md`; "
                "the sidecar has no ledger key",
                "drift           : prd home differs: config `docs/prd/`, "
                "sidecar glob `src/docs/prd/*.md`",
            ],
        )
        # The config line follows the sidecar lines.
        self.assertGreater(
            lines.index(f"config          : {path} — DRIFT (2)"),
            next(i for i, line in enumerate(lines) if line.startswith("stray keys      :")),
        )

    def test_the_text_form_says_agrees_without_drift(self):
        self.write_sidecar({"version": 1, "db": str(self.db), "ledger": "docs/ledger.md"})
        self.write_config("Ledger: `docs/ledger.md`", "PRD home: `docs/prd/`")
        proc = self.journal("--db", self.db, "doctor", rc=OK)
        path = self.root.resolve() / ".claude" / "shipgate.md"
        self.assertIn(f"config          : {path} — agrees", proc.stdout.splitlines())
        self.assertNotIn("drift           :", proc.stdout)

    def test_drift_leaves_the_exit_code_alone(self):
        """Drift is information for `setup`'s update mode, not a doctor failure."""
        self.write_sidecar({"version": 1, "db": str(self.db)})
        self.write_config("Ledger: `notes/ledger.md`")
        self.journal("--db", self.db, "doctor", rc=OK)
        self.journal("--db", self.db, "doctor", "--json", rc=OK)

    def test_the_json_keeps_every_existing_key(self):
        self.write_sidecar({"version": 1, "db": str(self.db)})
        self.write_config("Ledger: `notes/ledger.md`")
        report = json.loads(
            self.journal("--db", self.db, "doctor", "--json", rc=OK).stdout
        )
        for key in (
            "db", "db_source", "integrity_check", "off_vocabulary", "journal_mode",
            "schema_version", "pending_migrations", "events", "sidecar",
        ):
            self.assertIn(key, report)
        self.assertEqual(
            set(report["sidecar"]),
            {"found", "path", "db", "agrees", "version", "stray_keys"},
        )
        self.assertIn("config", report)


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
        row = self.row()
        self.assertEqual(
            row["stream_render_bytes"], len(rendered.rstrip("\n").encode())
        )
        self.assertNotIn("brief_bytes", row)

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
