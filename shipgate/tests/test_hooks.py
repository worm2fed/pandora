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

sys.path.insert(0, str(HOOKS))

from _common import load_project  # noqa: E402

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


def run_hook(
    name: str,
    payload: dict,
    cwd: Path,
    project_dir: Path | None = None,
    hooks_dir: Path | None = None,
    env_extra: dict | None = None,
):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir else cwd)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str((hooks_dir or HOOKS) / f"{name}.py")],
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


def init_git_checkout(path: Path, branch: str) -> None:
    """A one-commit repo on `branch` — `rev-parse` needs a born HEAD to name it."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    commands = [
        ["git", "init", "-q"],
        ["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command, cwd=str(path), capture_output=True, text=True, timeout=30,
                env=env,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f"git unavailable: {error}") from error
        if result.returncode != 0:
            raise unittest.SkipTest(f"git {command[1]} failed: {result.stderr}")


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

    def test_records_the_session_id_for_later_appends(self):
        """ADR 0003: skill appends inherit this id as their actor label."""
        run_hook(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.root), "source": "startup"},
            self.root,
        )
        result = journal(self.db, "session", "--get")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), SESSION)


class StubJournalMixin:
    """Stands a stub in for the journal CLI, in a throwaway copy of the plugin tree.

    `journal_script()` resolves relative to the hooks directory, so copying the hooks
    next to a stub `scripts/journal.py` is what makes the hook's argv observable.
    """

    STUB = """#!/usr/bin/env python3
import os
import sys

log = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calls.log"
)
with open(log, "a", encoding="utf-8") as handle:
    handle.write("\\t".join(sys.argv[1:]) + "\\n")
if "status" in sys.argv[1:]:
    print("stub brief")
"""

    def setUp(self) -> None:
        super().setUp()
        import shutil

        self._plugin_tmp = tempfile.TemporaryDirectory()
        self.plugin = Path(self._plugin_tmp.name).resolve()
        shutil.copytree(
            HOOKS, self.plugin / "hooks", ignore=shutil.ignore_patterns("__pycache__")
        )
        (self.plugin / "scripts").mkdir()
        (self.plugin / "scripts" / "journal.py").write_text(self.STUB, encoding="utf-8")

    def tearDown(self) -> None:
        self._plugin_tmp.cleanup()
        super().tearDown()

    def calls(self) -> list[list[str]]:
        log = self.plugin / "calls.log"
        self.assertTrue(log.is_file(), "the hook never invoked the journal")
        lines = log.read_text(encoding="utf-8").splitlines()
        return [line.split("\t") for line in lines]

    def journal_args(self, subcommand: str) -> list[str]:
        """The argv the hook handed `journal.py <subcommand>`, flags only."""
        for args in self.calls():
            if subcommand in args:
                return args[args.index(subcommand):]
        self.fail(f"the hook never invoked `journal.py {subcommand}`")

    def status_args(self) -> list[str]:
        return self.journal_args("status")

    def run_session_start(
        self, payload: dict | None = None, env_extra: dict | None = None
    ):
        return run_hook(
            "session_start",
            payload
            or {"session_id": SESSION, "cwd": str(self.root), "source": "startup"},
            self.root,
            hooks_dir=self.plugin / "hooks",
            env_extra=env_extra,
        )


class TestSessionStartBranch(StubJournalMixin, HookTestCase):
    """What the hook asks the journal for, argv by argv.

    The branch flag is the hook's whole contribution to FR-004; asserting it here keeps
    that independent of how `status` chooses to order streams.
    """

    def test_a_git_checkout_asks_for_the_branch_stream_first(self):
        init_git_checkout(self.root, "feature/x")
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status", "--branch=feature/x"])

    def test_a_dash_leading_branch_name_is_a_value_not_a_flag(self):
        """A repo can carry a branch literally named `--all`; two tokens broke here."""
        init_git_checkout(self.root, "feature/x")
        for command in (
            ["git", "update-ref", "refs/heads/--all", "HEAD"],
            ["git", "symbolic-ref", "HEAD", "refs/heads/--all"],
        ):
            renamed = subprocess.run(
                command, cwd=str(self.root), capture_output=True, text=True, timeout=30
            )
            self.assertEqual(renamed.returncode, 0, renamed.stderr)
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status", "--branch=--all"])

    def test_the_session_id_is_passed_as_a_single_token(self):
        self.run_session_start()
        self.assertEqual(self.journal_args("session"), ["session", f"--set={SESSION}"])

    def test_a_non_string_cwd_costs_the_branch_hint_not_the_brief(self):
        init_git_checkout(self.root, "feature/x")
        result = self.run_session_start(
            {"session_id": SESSION, "cwd": 42, "source": "startup"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status"])
        self.assertIn("stub brief", result.stdout)

    def test_an_inherited_git_dir_never_answers_for_another_repo(self):
        """`GIT_DIR` in the session env would otherwise name a foreign repo's branch."""
        init_git_checkout(self.root, "feature/x")
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        other = Path(elsewhere.name).resolve()
        init_git_checkout(other, "not-my-branch")
        result = self.run_session_start(env_extra={"GIT_DIR": str(other / ".git")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status", "--branch=feature/x"])

    def test_outside_a_git_checkout_the_branch_is_omitted(self):
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status"])

    def test_a_detached_head_is_not_a_branch_name(self):
        init_git_checkout(self.root, "feature/x")
        subprocess.run(
            ["git", "checkout", "-q", "--detach"], cwd=str(self.root), check=True,
            capture_output=True,
        )
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status"])


class TestSessionAttributionFailure(StubJournalMixin, HookTestCase):
    """The brief survives a journal that cannot record the session id."""

    STUB = """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if "session" in args:
    sys.stderr.write("session store unavailable\\n")
    sys.exit(1)
if "status" in args:
    print("stub brief")
"""

    def test_the_brief_is_prefixed_with_an_attribution_warning(self):
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(
            context.startswith("shipgate: session attribution unavailable"),
            f"the warning must lead the context: {context[:120]}",
        )
        self.assertIn("session --set failed", context)
        self.assertIn("stub brief", context)


class TestSessionAttributionWithAnEmptyBrief(StubJournalMixin, HookTestCase):
    """A fresh journal renders no brief; the warning must still reach the session."""

    STUB = """#!/usr/bin/env python3
import sys

if "session" in sys.argv[1:]:
    sys.exit(1)
"""

    def test_the_notice_is_emitted_on_its_own(self):
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        specific = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(
            specific["additionalContext"].splitlines()[0],
            "shipgate: session attribution unavailable (journal.py session --set "
            "failed) — skill appends this session will carry no session label.",
        )
        self.assertNotIn("flow journal —", specific["additionalContext"])

    def test_a_working_session_set_with_no_brief_emits_no_context(self):
        (self.plugin / "scripts" / "journal.py").write_text(
            "#!/usr/bin/env python3\n", encoding="utf-8"
        )
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        specific = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertNotIn("additionalContext", specific)


class TestProjectResolution(StubJournalMixin, HookTestCase):
    """A hook belongs to the session's own directory, not to the process's.

    `CLAUDE_PROJECT_DIR` can name a journaled project while the session sits in an
    un-journaled one; writing that session's events into the ambient project is the
    failure this pins down.
    """

    def setUp(self) -> None:
        super().setUp()
        self._elsewhere = tempfile.TemporaryDirectory()
        self.elsewhere = Path(self._elsewhere.name).resolve()
        self.addCleanup(self._elsewhere.cleanup)

    def run_hook_from_elsewhere(self, name, payload):
        return run_hook(
            name,
            payload,
            self.elsewhere,
            project_dir=self.root,
            hooks_dir=self.plugin / "hooks",
        )

    def test_session_start_ignores_the_ambient_project_when_cwd_is_not_journaled(self):
        result = self.run_hook_from_elsewhere(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.elsewhere), "source": "startup"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(
            (self.plugin / "calls.log").exists(),
            "the hook reached the ambient project's journal",
        )

    def test_session_start_falls_back_to_the_ambient_project_without_a_cwd(self):
        result = self.run_hook_from_elsewhere(
            "session_start", {"session_id": SESSION, "source": "startup"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stub brief", result.stdout)

    def test_stop_ignores_the_ambient_project_when_cwd_is_not_journaled(self):
        result = self.run_hook_from_elsewhere(
            "stop",
            {"session_id": SESSION, "cwd": str(self.elsewhere),
             "stop_hook_active": False},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.plugin / "calls.log").exists())

    def test_stop_falls_back_to_the_ambient_project_without_a_cwd(self):
        result = self.run_hook_from_elsewhere(
            "stop", {"session_id": SESSION, "stop_hook_active": False}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.journal_args("check"),
            ["check", "--session", SESSION, "--json"],
        )


class TestJournalDbIsNeverAnArtifact(HookTestCase):
    """A glob wide enough to match the db must not make the db an artifact."""

    def setUp(self) -> None:
        super().setUp()
        self.sidecar = self.root / ".claude" / "shipgate.json"
        config = json.loads(self.sidecar.read_text())
        config["artifact_homes"] = {"x": ".claude/*"}
        self.sidecar.write_text(json.dumps(config), encoding="utf-8")
        self.wal = Path(str(self.db) + "-wal")
        self.wal.write_text("", encoding="utf-8")

    def test_the_db_is_neither_watched_nor_covered(self):
        result = run_hook(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.root), "source": "startup"},
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        watched = json.loads(result.stdout)["hookSpecificOutput"]["watchPaths"]
        self.assertIn(str(self.sidecar), watched, "the glob should still match")
        self.assertNotIn(str(self.db), watched)
        self.assertNotIn(str(self.wal), watched)

        project = load_project(str(self.root))
        self.assertTrue(project.covers(str(self.sidecar)))
        self.assertFalse(project.covers(str(self.db)))
        self.assertFalse(project.covers(str(self.wal)))


class TestSessionStartBranchOrdering(HookTestCase):
    def test_the_branch_stream_leads_the_brief(self):
        init_git_checkout(self.root, STREAM)
        for stream in ("aaa-other", STREAM):
            appended = journal(
                self.db, "append", "--stream", stream, "--type", "phase-entered",
                "--data", json.dumps({"phase": "workspace"}),
            )
            self.assertEqual(appended.returncode, 0, appended.stderr)

        result = run_hook(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.root), "source": "startup"},
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("aaa-other", context, f"no brief was rendered: {context}")
        self.assertLess(
            context.index(STREAM), context.index("aaa-other"),
            "the stream named after the branch must render first",
        )


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

    def test_a_block_is_recorded_with_its_finding_count(self):
        self.tick_and_capture(WORKLOG_TWO_TICKED)
        self.assertEqual(json.loads(self.stop().stdout)["decision"], "block")
        blocked = self.events(event_type="gate-blocked")
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["stream"], "shipgate")
        self.assertEqual(blocked[0]["data"]["session"], SESSION)
        self.assertEqual(blocked[0]["data"]["findings"], 2)

    def test_a_clean_stop_records_no_block(self):
        self.assertEqual(self.stop().stdout.strip(), "")
        self.assertEqual(self.events(event_type="gate-blocked"), [])

    def test_reentrant_stop_stands_down(self):
        """Loop protection — the harness hard-overrides after 8 blocks regardless."""
        self.tick_and_capture(WORKLOG_ONE_TICKED)
        self.assertEqual(json.loads(self.stop().stdout)["decision"], "block")
        again = self.stop(active=True)
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout.strip(), "")
        self.assertEqual(
            len(self.events(event_type="gate-blocked")),
            1,
            "standing down must not record a second block",
        )

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
        """The bisynced-vault case: a Drive bisync touches an old finished worklog.

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

    def test_a_stop_touches_nothing(self):
        result = run_hook(
            "stop",
            {"session_id": "s", "cwd": str(self.root), "stop_hook_active": False},
            self.root,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
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
