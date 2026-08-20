"""End-to-end tests for the hook layer (T033).

`test_journal.py` proves the CLI's contract. This file proves the thing the CLI cannot:
that the hooks actually wire that contract into a session — capture happens without the
model's cooperation, the Stop gate refuses an unrecorded session, and a project that
never ran setup pays nothing at all.

The hooks are invoked exactly as the harness invokes them: a JSON payload on stdin, the
response read back off stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
HOOKS = SHIPGATE / "hooks"
JOURNAL = SHIPGATE / "scripts" / "journal.py"

SESSION = "sess-integration-1"
SLUG = "feat"
STREAM = f"feature/{SLUG}"

WORKLOG_UNTICKED = """# Worklog: feat

# Build Plan
- [ ] T001 — first task — done when: it works
- [ ] T002 — second task — done when: it works
"""

WORKLOG_ONE_TICKED = WORKLOG_UNTICKED.replace("- [ ] T001", "- [x] T001")
WORKLOG_TWO_TICKED = WORKLOG_ONE_TICKED.replace("- [ ] T002", "- [x] T002")


def run_hook(name: str, payload: dict, cwd: Path, project_dir: Path | None = None):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir else cwd)
    return subprocess.run(
        [sys.executable, str(HOOKS / f"{name}.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=60,
    )


def journal(db: Path, *args: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(JOURNAL), "--db", str(db), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=60,
    )


class HookTestCase(unittest.TestCase):
    """A journaled fixture project, built the way `setup` would build one."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / ".claude").mkdir()
        (self.root / "docs" / "prd").mkdir(parents=True)

        self.db = self.root / ".claude" / "shipgate.db"
        self.prd = self.root / "docs" / "prd" / f"{SLUG}.md"
        self.worklog = self.root / "docs" / "prd" / f"{SLUG}.worklog.md"

        self.prd.write_text("# PRD: feat\n\nAll clear.\n", encoding="utf-8")
        self.worklog.write_text(WORKLOG_UNTICKED, encoding="utf-8")

        (self.root / ".claude" / "shipgate.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "db": ".claude/shipgate.db",
                    "artifact_homes": {
                        "worklog": "docs/prd/*.worklog.md",
                        "prd": "docs/prd/*.md",
                        "adr": "docs/adr/*.md",
                    },
                    "enforce": {"stop_gate": True, "auto_capture": True},
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(journal(self.db, "init").returncode, 0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def events(self, *, event_type: str | None = None):
        result = journal(self.db, "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if event_type:
            rows = [r for r in rows if r["type"] == event_type]
        return rows

    def stop(self, *, active: bool = False):
        return run_hook(
            "stop",
            {"session_id": SESSION, "cwd": str(self.root), "stop_hook_active": active},
            self.root,
        )


class TestCapture(HookTestCase):
    def test_post_tool_use_records_a_tool_write(self):
        result = run_hook(
            "post_tool_use",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.worklog)},
            },
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.events(event_type="artifact-written")
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["data"]["path"], f"docs/prd/{SLUG}.worklog.md")
        self.assertEqual(written[0]["data"]["source"], "tool")

    def test_file_changed_records_a_write_post_tool_use_cannot_see(self):
        """The Bash-heredoc blind spot — the reason FileChanged exists at all."""
        subprocess.run(
            ["sh", "-c", f"cat > {self.worklog} <<'EOF'\n{WORKLOG_ONE_TICKED}EOF"],
            check=True,
            cwd=str(self.root),
        )
        result = run_hook(
            "file_changed",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "file_path": str(self.worklog),
                "event": "change",
            },
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.events(event_type="artifact-written")
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["data"]["source"], "disk")

    def test_file_changed_returns_a_refreshed_watch_list(self):
        result = run_hook(
            "file_changed",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "file_path": str(self.worklog),
                "event": "change",
            },
            self.root,
        )
        payload = json.loads(result.stdout)
        watched = payload["hookSpecificOutput"]["watchPaths"]
        self.assertIn(str(self.worklog), watched)
        self.assertIn(str(self.prd), watched)
        self.assertTrue(all(os.path.isabs(p) for p in watched))
        self.assertNotIn(str(self.db), watched, "the db must never be watched")

    def test_writes_outside_the_artifact_homes_are_ignored(self):
        stray = self.root / "src" / "main.py"
        stray.parent.mkdir()
        stray.write_text("x = 1\n", encoding="utf-8")
        run_hook(
            "post_tool_use",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": str(stray)},
            },
            self.root,
        )
        self.assertEqual(self.events(event_type="artifact-written"), [])

    def test_auto_capture_can_be_switched_off(self):
        sidecar = self.root / ".claude" / "shipgate.json"
        config = json.loads(sidecar.read_text())
        config["enforce"]["auto_capture"] = False
        sidecar.write_text(json.dumps(config), encoding="utf-8")
        run_hook(
            "post_tool_use",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.worklog)},
            },
            self.root,
        )
        self.assertEqual(self.events(event_type="artifact-written"), [])


class TestSessionStart(HookTestCase):
    def test_injects_the_brief_and_arms_the_watcher(self):
        result = run_hook(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.root), "source": "startup"},
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        specific = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        self.assertIn(str(self.worklog), specific["watchPaths"])
        self.assertIn("journal", specific["additionalContext"].lower())
        self.assertEqual(len(self.events(event_type="session-started")), 1)


class TestStopGate(HookTestCase):
    """The gate itself: block when bookkeeping is missing, pass once it isn't."""

    def setUp(self) -> None:
        super().setUp()
        # The gate only applies to a flow the journal is tracking — a bare worklog with
        # no flow behind it (a legacy artifact, or one a vault sync touched) is
        # deliberately ignored. So establish a real flow first, as a session would.
        started = journal(
            self.db, "append", "--stream", STREAM, "--type", "phase-entered",
            "--data", json.dumps({"phase": "workspace"}),
        )
        self.assertEqual(started.returncode, 0, started.stderr)

    def tick_and_capture(self, contents: str) -> None:
        self.worklog.write_text(contents, encoding="utf-8")
        run_hook(
            "file_changed",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "file_path": str(self.worklog),
                "event": "change",
            },
            self.root,
        )

    def test_clean_session_is_allowed_to_stop(self):
        result = self.stop()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "", "a clean stop must emit no decision")

    def test_ticked_box_without_task_done_blocks_the_stop(self):
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        result = self.stop()
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block", "decision must be top level")
        self.assertNotIn("hookSpecificOutput", payload)
        self.assertIn("T001", payload["reason"])
        self.assertIn("task-done", payload["reason"])

    def test_reentrant_stop_stands_down(self):
        """Loop protection — the harness hard-overrides after 8 blocks regardless."""
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        self.assertEqual(json.loads(self.stop().stdout)["decision"], "block")
        again = self.stop(active=True)
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout.strip(), "")

    def test_every_finding_is_reported_in_one_round(self):
        """Findings must be satisfiable in a single round, never trickled out."""
        self.tick_and_capture(WORKLOG_TWO_TICKED)
        reason = json.loads(self.stop().stdout)["reason"]
        self.assertIn("T001", reason)
        self.assertIn("T002", reason)

    def test_recording_the_events_unblocks_the_stop(self):
        """The full cycle: capture → block → append → clean stop."""
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        self.assertEqual(json.loads(self.stop().stdout)["decision"], "block")

        verify = journal(
            self.db, "append", "--stream", STREAM, "--type", "verify-run",
            "--data", json.dumps(
                {"scope": "T001", "outcome": "pass", "task_ids": ["T001"],
                 "commands": [{"cmd": "pytest", "exit": 0, "head": "", "tail": "ok"}]}
            ),
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)

        done = journal(
            self.db, "append", "--stream", STREAM, "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}),
        )
        self.assertEqual(done.returncode, 0, done.stderr)

        final = self.stop()
        self.assertEqual(final.returncode, 0)
        self.assertEqual(final.stdout.strip(), "", "gate should now be satisfied")

    def test_a_synced_legacy_worklog_does_not_block(self):
        """The Voyager case: a Drive bisync touches an old finished worklog.

        Its boxes are ticked and no journal event has ever named it, because the work
        predates the journal. Capturing the change is right; blocking the session over
        it is not.
        """
        legacy = self.root / "docs" / "prd" / "legacy.worklog.md"
        legacy.write_text(WORKLOG_TWO_TICKED, encoding="utf-8")
        run_hook(
            "file_changed",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "file_path": str(legacy),
                "event": "change",
            },
            self.root,
        )
        captured = [
            e for e in self.events(event_type="artifact-written")
            if e["data"]["path"].endswith("legacy.worklog.md")
        ]
        self.assertEqual(len(captured), 1, "the change should still be recorded")

        result = self.stop()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "", "an untracked worklog must not gate")

    def test_stop_gate_can_be_switched_off(self):
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        sidecar = self.root / ".claude" / "shipgate.json"
        config = json.loads(sidecar.read_text())
        config["enforce"]["stop_gate"] = False
        sidecar.write_text(json.dumps(config), encoding="utf-8")
        result = self.stop()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_an_unreachable_journal_never_traps_the_session(self):
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        self.db.unlink()
        result = self.stop()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "", "infra failure must not block a stop")


class TestUnjournaledProjectIsInert(unittest.TestCase):
    """SC-004: a project that never ran setup must pay nothing, anywhere."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "docs").mkdir()
        self.file = self.root / "docs" / "notes.md"
        self.file.write_text("- [x] T001 done\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_every_hook_is_silent_and_successful(self):
        payloads = {
            "session_start": {"source": "startup"},
            "post_tool_use": {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.file)},
            },
            "stop": {"stop_hook_active": False},
            "file_changed": {"file_path": str(self.file), "event": "change"},
        }
        for hook, extra in payloads.items():
            with self.subTest(hook=hook):
                result = run_hook(
                    hook, {"session_id": "s", "cwd": str(self.root), **extra}, self.root
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")

    def test_no_state_is_created_anywhere(self):
        run_hook(
            "post_tool_use",
            {
                "session_id": "s",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.file)},
            },
            self.root,
        )
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual(list(self.root.rglob("*.db")), [])

    def test_malformed_input_is_survived_quietly(self):
        for hook in ("session_start", "post_tool_use", "stop", "file_changed"):
            for raw in ("", "not json", "[]", "null"):
                with self.subTest(hook=hook, raw=raw):
                    result = subprocess.run(
                        [sys.executable, str(HOOKS / f"{hook}.py")],
                        input=raw,
                        capture_output=True,
                        text=True,
                        cwd=str(self.root),
                        env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)},
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
