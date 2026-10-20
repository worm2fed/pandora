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
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent
HOOKS = SHIPGATE / "hooks"
JOURNAL = SHIPGATE / "scripts" / "journal.py"

sys.path.insert(0, str(HOOKS))

from _common import find_project, load_project  # noqa: E402

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
    # Claude Code's session id would label the hooks' appends; a test sets it when it means to.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
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

    def test_file_changed_names_only_the_observer(self):
        """ADR 0008: every session's watcher fires on a write, so the payload's session
        saw the change and may not have made it. Its own id in the hook's environment
        must not label the row either."""
        result = run_hook(
            "file_changed",
            {
                "session_id": SESSION,
                "cwd": str(self.root),
                "file_path": str(self.worklog),
                "event": "change",
            },
            self.root,
            env_extra={"CLAUDE_CODE_SESSION_ID": SESSION},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.events(event_type="artifact-written")[0]
        self.assertEqual(row["data"]["observed_by"], SESSION)
        self.assertNotIn("session", row["data"])
        self.assertEqual(row["actor"], "hook")

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
        """The branch hints `status` got; the session flag is asserted on its own."""
        return [a for a in self.journal_args("status") if not a.startswith("--session=")]

    def session_args(self) -> list[str]:
        return [a for a in self.journal_args("status") if a.startswith("--session=")]

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

    # The session's own stream (the one it last wrote to) leads the brief — what a resumed
    # or compacted session was driving, which need not be any checkout's branch.
    def test_the_session_id_goes_to_status_as_a_single_token(self):
        self.run_session_start()
        self.assertEqual(self.session_args(), [f"--session={SESSION}"])

    def test_a_missing_session_id_passes_no_session(self):
        self.run_session_start({"cwd": str(self.root), "source": "startup"})
        self.assertEqual(self.session_args(), [])

    def test_a_malformed_session_id_passes_no_session(self):
        for odd in ("", "a b", "x\ny", "-" * 3 + "all", "s" * 200, 42):
            with self.subTest(session_id=odd):
                (self.plugin / "calls.log").unlink(missing_ok=True)
                self.run_session_start(
                    {"session_id": odd, "cwd": str(self.root), "source": "startup"}
                )
                self.assertEqual(self.session_args(), [])

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

    # Umbrella checkouts: the real repos sit one level down (`*/`, `source/*`,
    # `packages/*`), the session directory is a plain folder or a repo of its own.
    def test_a_plain_folder_umbrella_passes_the_nested_repos_branches(self):
        for relative, branch in (
            ("svc-a", "feat/a"),
            ("svc-c", "feat/a"),  # a second repo on the same branch: passed once
            ("source/svc-b", "feat/b"),
            (".hidden", "feat/hidden"),  # dot-directories are not looked into
            ("node_modules/dep", "feat/dep"),  # nor node_modules
        ):
            (self.root / relative).mkdir(parents=True)
            init_git_checkout(self.root / relative, branch)
        (self.root / "notes").mkdir()  # a plain folder is not a repo
        # worktrees where `workspace` puts them: inside a repo, and beside the repos
        for repo, target, branch in (
            ("svc-a", self.root / "svc-a" / ".worktrees" / "x", "feat/wt-inside"),
            ("source/svc-b", self.root / "source" / ".worktrees" / "svc-b-1", "feat/wt-beside"),
        ):
            added = subprocess.run(
                ["git", "worktree", "add", "-q", "-b", branch, str(target)],
                cwd=str(self.root / repo), capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(added.returncode, 0, added.stderr)
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        # a repo, then its own worktrees; a parent's `.worktrees/` after that parent's repos
        self.assertEqual(self.status_args(), [
            "status", "--nested-branch=feat/a", "--nested-branch=feat/wt-inside",
            "--nested-branch=feat/b", "--nested-branch=feat/wt-beside",
        ])

    def test_a_git_umbrella_passes_its_own_branch_and_the_nested_ones(self):
        init_git_checkout(self.root, "main")
        (self.root / "packages" / "svc").mkdir(parents=True)
        init_git_checkout(self.root / "packages" / "svc", "feat/a")
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), [
            "status", "--branch=main", "--nested-branch=feat/a",
        ])

    def test_a_nested_worktree_is_read_through_its_gitdir_file_and_a_detached_one_skipped(self):
        (self.root / "svc-a").mkdir()
        init_git_checkout(self.root / "svc-a", "feat/a")
        added = subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "feat/wt", str(self.root / "wt")],
            cwd=str(self.root / "svc-a"), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue((self.root / "wt" / ".git").is_file())  # `gitdir: …`, not a dir
        (self.root / "loose").mkdir()
        init_git_checkout(self.root / "loose", "feat/loose")
        subprocess.run(
            ["git", "checkout", "-q", "--detach"], cwd=str(self.root / "loose"),
            check=True, capture_output=True,
        )
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), [
            "status", "--nested-branch=feat/a", "--nested-branch=feat/wt",
        ])

    # A checkout is untrusted content: nothing in a nested `.git` may hang the hook,
    # abort it, or point it at files outside the session directory.
    def test_a_fifo_or_a_nul_byte_in_a_nested_head_costs_that_hint_only(self):
        (self.root / "ok").mkdir()
        init_git_checkout(self.root / "ok", "feat/ok")
        fifo = self.root / "fifo" / ".git"
        fifo.mkdir(parents=True)
        os.mkfifo(fifo / "HEAD")  # a plain open() would block until a writer appears
        nul = self.root / "nul" / ".git"
        nul.mkdir(parents=True)
        (nul / "HEAD").write_bytes(b"ref: refs/heads/x\0y\n")
        ctrl = self.root / "ctrl" / ".git"
        ctrl.mkdir(parents=True)
        (ctrl / "HEAD").write_bytes(b"ref: refs/heads/x\x1b[31my\n")
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status", "--nested-branch=feat/ok"])
        self.assertIn("stub brief", result.stdout)

    def test_a_gitdir_file_pointing_outside_the_session_directory_is_not_followed(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        other = Path(elsewhere.name).resolve()
        init_git_checkout(other, "feat/elsewhere")
        (self.root / "ptr").mkdir()
        (self.root / "ptr" / ".git").write_text(
            f"gitdir: {other / '.git'}\n", encoding="utf-8"
        )
        (self.root / "rel").mkdir()
        (self.root / "rel" / ".git").write_text(
            "gitdir: ../../" + other.name + "/.git\n", encoding="utf-8"
        )
        result = self.run_session_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.status_args(), ["status"])

    def test_a_symlinked_nested_directory_is_not_looked_into(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        other = Path(elsewhere.name).resolve()
        init_git_checkout(other, "feat/elsewhere")
        os.symlink(other, self.root / "link")
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


class TestHooksAndJournalAgreeOnTheDb(HookTestCase):
    """A session nested inside a journaled project uses that project's journal.

    The hooks take the nearest sidecar up to the filesystem root. journal.py, run from the
    same directory without `--db` (the way a skill runs it), must land on the same db: a
    nested `.git`, file or directory, is no boundary. A split here gives the session a
    second, silent journal under its own directory.
    """

    def assert_same_db(self, cwd: Path) -> None:
        project = find_project(str(cwd))
        self.assertIsNotNone(project, "the hooks found no sidecar")
        hooks_db = os.path.realpath(project.db_path)
        self.assertEqual(hooks_db, str(self.db))  # the sidecar's relative db, at the root
        result = subprocess.run(
            [sys.executable, str(JOURNAL), "doctor", "--json"],
            capture_output=True, text=True, cwd=str(cwd), timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.path.realpath(json.loads(result.stdout)["db"]), hooks_db)
        self.assertFalse((cwd / ".claude" / "shipgate.db").exists())

    def test_a_linked_worktree_inside_the_project(self):
        init_git_checkout(self.root, "main")
        worktree = self.root / ".worktrees" / "x"
        added = subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "feature/x", str(worktree)],
            cwd=str(self.root), capture_output=True, text=True, timeout=30,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_CONFIG_SYSTEM": os.devnull},
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue((worktree / ".git").is_file())  # `gitdir: …`, not a dir
        self.assert_same_db(worktree)

    def test_an_independent_repo_nested_in_the_project(self):
        nested = self.root / "sub"
        nested.mkdir()
        init_git_checkout(nested, "main")
        self.assertTrue((nested / ".git").is_dir())
        self.assert_same_db(nested)


class TestASidecarWithoutADbKey(HookTestCase):
    """No `db` key means the default db at the sidecar's directory, for the hooks and
    journal.py alike — never the default under journal.py's own cwd."""

    def test_both_resolve_the_default_db_at_the_sidecar(self):
        sidecar = self.root / ".claude" / "shipgate.json"
        config = json.loads(sidecar.read_text(encoding="utf-8"))
        del config["db"]
        sidecar.write_text(json.dumps(config), encoding="utf-8")
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(os.path.realpath(find_project(str(nested)).db_path), str(self.db))
        result = subprocess.run(
            [sys.executable, str(JOURNAL), "doctor", "--json"],
            capture_output=True, text=True, cwd=str(nested), timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.path.realpath(json.loads(result.stdout)["db"]), str(self.db))


class TestALinkedWorktreeUsesTheMainJournal(HookTestCase):
    """A repo that commits its sidecar gives every linked worktree a copy of it.

    The copy is the nearest sidecar for a session in the worktree, and its relative `db`
    names a file inside the worktree: one empty journal per worktree. The journal is the
    main worktree's, wherever the linked worktree sits; the hooks and journal.py agree.
    """

    GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def git(self, *args: str, cwd: Path) -> None:
        result = subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
            cwd=str(cwd), capture_output=True, text=True, timeout=30,
            env={**os.environ, **self.GIT_ENV},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self) -> None:
        super().setUp()
        init_git_checkout(self.root, "main")
        self.git("add", ".claude/shipgate.json", cwd=self.root)
        self.git("commit", "-q", "-m", "sidecar", cwd=self.root)

    def add_worktree(self, path: Path) -> Path:
        self.git("worktree", "add", "-q", "-b", f"feature/{path.name}", str(path),
                 cwd=self.root)
        self.assertTrue((path / ".claude" / "shipgate.json").is_file())
        return path

    def assert_main_journal(self, cwd: Path) -> None:
        project = find_project(str(cwd))
        self.assertIsNotNone(project, "the hooks found no sidecar")
        self.assertEqual(os.path.realpath(project.db_path), str(self.db))
        result = subprocess.run(
            [sys.executable, str(JOURNAL), "doctor", "--json"],
            capture_output=True, text=True, cwd=str(cwd), timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.path.realpath(json.loads(result.stdout)["db"]), str(self.db))
        self.assertFalse((cwd / ".claude" / "shipgate.db").exists())

    def test_a_worktree_nested_in_the_main_checkout(self):
        self.assert_main_journal(self.add_worktree(self.root / ".worktrees" / "x"))

    def test_a_worktree_beside_the_main_checkout(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.assert_main_journal(self.add_worktree(Path(elsewhere.name).resolve() / "y"))

    def test_a_forged_git_file_cannot_borrow_another_checkouts_journal(self):
        """A `.git` file names a real worktree's git dir, but git's back-link names that
        worktree, not this directory: no redirect, the sidecar's own journal."""
        real = self.add_worktree(self.root / ".worktrees" / "real")
        forged = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(forged, ignore_errors=True))
        (forged / ".claude").mkdir()
        (forged / ".claude" / "shipgate.json").write_bytes(
            (real / ".claude" / "shipgate.json").read_bytes())
        git_dir = (self.root / ".git" / "worktrees" / "real").resolve()
        self.assertTrue(git_dir.is_dir())
        (forged / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
        project = find_project(str(forged))
        self.assertEqual(project.db_path, str(forged / ".claude" / "shipgate.db"))

    def test_a_git_dir_planted_inside_the_checkout_is_not_followed(self):
        """Every pointer file sits in the checkout, back-link included, and commondir
        names the main checkout's git dir: still no redirect."""
        planted = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(planted, ignore_errors=True))
        (planted / ".claude").mkdir()
        (planted / ".claude" / "shipgate.json").write_text("{}", encoding="utf-8")
        fake = planted / "fake" / "wt"
        fake.mkdir(parents=True)
        (planted / ".git").write_text("gitdir: fake/wt\n", encoding="utf-8")
        (fake / "gitdir").write_text("../../.git\n", encoding="utf-8")
        (fake / "commondir").write_text(f"{self.root / '.git'}\n", encoding="utf-8")
        project = find_project(str(planted))
        self.assertEqual(project.db_path, str(planted / ".claude" / "shipgate.db"))

    def test_without_a_sidecar_in_the_main_checkout_the_worktree_keeps_its_own(self):
        worktree = self.add_worktree(self.root / ".worktrees" / "solo")
        (self.root / ".claude" / "shipgate.json").unlink()
        project = find_project(str(worktree))
        self.assertEqual(project.db_path, str(worktree / ".claude" / "shipgate.db"))

    def test_artifacts_stay_the_worktrees_own(self):
        worktree = self.add_worktree(self.root / ".worktrees" / "z")
        project = find_project(str(worktree))
        self.assertEqual(os.path.realpath(project.root), str(worktree))
        self.assertTrue(project.covers(str(worktree / "docs" / "prd" / "a.md")))


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


class TestSessionStartSessionOrdering(HookTestCase):
    def test_the_sessions_stream_leads_the_brief_over_the_branch(self):
        """A resumed or compacted session driving a stream with no branch (an epic's
        planning stream) gets that stream first, marked as its own."""
        init_git_checkout(self.root, STREAM)
        for stream, actor in (("epic-x", f"orchestrator@{SESSION}"), (STREAM, "orchestrator@other")):
            appended = journal(
                self.db, "append", "--stream", stream, "--type", "phase-entered",
                "--actor", actor, "--data", json.dumps({"phase": "workspace"}),
            )
            self.assertEqual(appended.returncode, 0, appended.stderr)

        result = run_hook(
            "session_start",
            {"session_id": SESSION, "cwd": str(self.root), "source": "compact"},
            self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(STREAM, context, f"no brief was rendered: {context}")
        self.assertLess(context.index("epic-x"), context.index(STREAM))
        self.assertIn("epic-x  (v1)  · this session", context)


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
        """The session ticks the box with its own Edit. A FileChanged row alone names
        only an observer, and an observation gates nobody (ADR 0008)."""
        self.worklog.write_text(contents, encoding="utf-8")
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


def load_journal_module():
    """journal.py as a module, for the read-time fold over exported rows."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("shipgate_journal_hooks", JOURNAL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTwoSessionsWatchOneArtifact(HookTestCase):
    """Two sessions watch one PRD, and only one of them writes it (ADR 0008).

    Every session arms FileChanged on the same artifact homes, and a FileChanged payload names
    the session whose hook ran, not the one that wrote. So that row names only an observer,
    the writer's own claim survives whichever hook lands first, and the read-time fold makes
    the writer the author in both orders: the writer is gated at Stop, the observer is not.
    """

    WRITER = "sess-writer"
    OBSERVER = "sess-observer"

    @classmethod
    def setUpClass(cls) -> None:
        cls.J = load_journal_module()

    def setUp(self) -> None:
        super().setUp()
        # the PRD's stream sits in clarify, so rule B of the Stop gate applies to its writes
        started = journal(
            self.db, "append", "--stream", STREAM, "--type", "phase-entered",
            "--data", json.dumps(
                {"phase": "clarify", "skipped": ["workspace", "route-and-map", "explore"]}
            ),
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        self.prd.write_text("# PRD: feat\n\nRewritten by the writer.\n", encoding="utf-8")

    def hook_as(self, session: str, name: str, payload: dict):
        """Claude Code puts the session's own id in every hook's environment."""
        result = run_hook(
            name,
            {"session_id": session, "cwd": str(self.root), **payload},
            self.root,
            env_extra={"CLAUDE_CODE_SESSION_ID": session},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def written_by_the_tool(self):
        return self.hook_as(self.WRITER, "post_tool_use", {
            "tool_name": "Write", "tool_input": {"file_path": str(self.prd)},
        })

    def written_by_bash(self):
        return self.hook_as(self.WRITER, "post_tool_use", {
            "tool_name": "Bash",
            "tool_input": {"command": "cat > docs/prd/feat.md <<'EOF'\n...\nEOF"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
            "duration_ms": 1500,
        })

    def seen_on_disk(self, session: str):
        return self.hook_as(session, "file_changed", {
            "file_path": str(self.prd), "event": "change",
        })

    def stop_as(self, session: str):
        return self.hook_as(session, "stop", {"stop_hook_active": False})

    def rows(self):
        return [
            (r["data"]["source"], r["data"].get("session"), r["data"].get("observed_by"),
             r["actor"])
            for r in self.events(event_type="artifact-written")
        ]

    def assert_the_writer_is_the_author(self):
        rows = [self.J.Event(**row) for row in self.events()]
        key = (f"docs/prd/{SLUG}.md", os.stat(self.prd).st_mtime)
        self.assertEqual(self.J.artifact_authors(rows), {key: self.WRITER})

        self.assertEqual(self.stop_as(self.OBSERVER).stdout.strip(), "")
        writer = json.loads(self.stop_as(self.WRITER).stdout)
        self.assertEqual(writer["decision"], "block")
        self.assertIn("gate-decision", writer["reason"])

    def test_the_observer_lands_first(self):
        self.seen_on_disk(self.OBSERVER)
        self.written_by_the_tool()
        self.seen_on_disk(self.WRITER)

        self.assertEqual(self.rows(), [
            ("disk", None, self.OBSERVER, "hook"),
            ("tool", self.WRITER, None, "hook"),
        ])
        self.assert_the_writer_is_the_author()

    def test_the_writer_lands_first(self):
        self.written_by_the_tool()
        self.seen_on_disk(self.OBSERVER)

        self.assertEqual(self.rows(), [("tool", self.WRITER, None, "hook")])
        self.assert_the_writer_is_the_author()

    def test_a_bash_heredoc_is_attributed_to_its_session(self):
        """The write no file-tool hook sees: the writer's Bash call claims it."""
        self.seen_on_disk(self.OBSERVER)
        self.written_by_bash()
        self.seen_on_disk(self.WRITER)

        self.assertEqual(self.rows(), [
            ("disk", None, self.OBSERVER, "hook"),
            ("bash", self.WRITER, None, "hook"),
        ])
        self.assert_the_writer_is_the_author()


class TestBashClaims(HookTestCase):
    """PostToolUse on Bash: a Bash call's own evidence that it wrote an artifact."""

    def setUp(self) -> None:
        super().setUp()
        self.prd.write_text("# PRD: feat\n\nWritten by a Bash call.\n", encoding="utf-8")

    def bash(self, command: str, *, duration_ms=1500, diff=None, background=False,
             tool_response=None):
        tool_input = {"command": command, "description": "a test command"}
        if background:
            tool_input["run_in_background"] = True
        response = {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}
        if diff is not None:
            response["bashEditDiff"] = diff
        payload = {
            "session_id": SESSION,
            "cwd": str(self.root),
            "tool_name": "Bash",
            "tool_input": tool_input,
            "tool_response": response if tool_response is None else tool_response,
            "tool_use_id": "toolu_test",
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        result = run_hook("post_tool_use", payload, self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        return result

    def claims(self):
        return [
            (r["data"]["path"], r["data"]["source"], r["data"].get("evidence"),
             r["data"].get("session"))
            for r in self.events(event_type="artifact-written")
        ]

    def test_a_listed_artifact_is_a_diff_claim(self):
        stray = self.root / "src" / "gen.py"
        stray.parent.mkdir()
        stray.write_text("x = 1\n", encoding="utf-8")
        self.bash("python3 tools/regen.py", diff={
            "changedFiles": [str(self.prd), str(stray)], "files": [], "moreFiles": 2,
        })
        self.assertEqual(self.claims(), [(f"docs/prd/{SLUG}.md", "bash", "diff", SESSION)])
        row = self.events(event_type="artifact-written")[0]
        self.assertEqual(row["data"]["mtime"], os.stat(self.prd).st_mtime)
        self.assertEqual(row["data"]["tool_use_id"], "toolu_test")
        self.assertEqual(row["actor"], "hook")

    def test_an_artifact_the_diff_does_not_list_is_left_to_the_window(self):
        """The diff never lists a file git ignores or a file in a submodule, so a
        usable diff does not end the search: the unlisted artifacts get the window."""
        self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF", diff={
            "changedFiles": [], "files": [], "moreFiles": 0,
        })
        self.assertEqual(self.claims(), [(f"docs/prd/{SLUG}.md", "bash", "window", SESSION)])

    def test_an_unlisted_artifact_outside_the_window_is_not_claimed(self):
        an_hour_ago = os.stat(self.prd).st_mtime - 3600
        os.utime(self.prd, (an_hour_ago, an_hour_ago))
        self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF", diff={
            "changedFiles": [], "files": [], "moreFiles": 0,
        })
        self.assertEqual(self.claims(), [])

    def test_a_diff_claim_and_a_window_claim_on_two_artifacts(self):
        self.worklog.write_text(WORKLOG_ONE_TICKED, encoding="utf-8")
        self.bash(
            f"python3 tools/regen.py docs/prd/{SLUG}.md"
            f" && sed -i.bak 's/a/b/' docs/prd/{SLUG}.worklog.md",
            diff={"changedFiles": [str(self.prd)], "files": [], "moreFiles": 1},
        )
        self.assertEqual(self.claims(), [
            (f"docs/prd/{SLUG}.md", "bash", "diff", SESSION),
            (f"docs/prd/{SLUG}.worklog.md", "bash", "window", SESSION),
        ])

    def test_a_named_artifact_written_during_the_call_is_a_window_claim(self):
        self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF")
        self.assertEqual(self.claims(), [(f"docs/prd/{SLUG}.md", "bash", "window", SESSION)])

    def test_an_artifact_the_command_does_not_name_is_not_claimed(self):
        self.bash("make docs")
        self.assertEqual(self.claims(), [])

    def test_a_name_inside_a_longer_name_is_not_a_mention(self):
        self.bash("echo x > docs/prd/defeat.md && cp /tmp/draft.md docs/prd/feat.md.bak")
        self.assertEqual(self.claims(), [])

    def test_a_write_before_the_window_is_not_claimed(self):
        an_hour_ago = os.stat(self.prd).st_mtime - 3600
        os.utime(self.prd, (an_hour_ago, an_hour_ago))
        self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF")
        self.assertEqual(self.claims(), [])

    # R1-F2: naming the file is not enough. The window claims only a write shape, so a
    # session reading an artifact never claims an external editor's concurrent write.
    READS = (
        "cat docs/prd/feat.md",
        "grep -n Goal docs/prd/feat.md",
        "wc -l docs/prd/feat.md",
        "python3 tools/check.py docs/prd/feat.md",
        "pytest -q tests/ -k 'not slow' --maxfail=1 && cat docs/prd/feat.md",
        "sed -n 1,5p docs/prd/feat.md",
        "cp docs/prd/feat.md /tmp/copy.md",
        "diff docs/prd/feat.md docs/prd/feat.worklog.md > /tmp/out.diff",
        "cat > /tmp/notes.md <<'EOF'\nsee docs/prd/feat.md\n> docs/prd/feat.md is the PRD\n"
        "EOF",
        # R2-N2: a copy elsewhere that keeps the file name writes another file
        "cp docs/prd/feat.md /tmp/feat.md",
        "cp docs/prd/feat.md ~/backup/feat.md",
        "cat docs/prd/feat.md > /tmp/feat.md",
        "git show HEAD:docs/prd/feat.md > /tmp/old/feat.md",
    )

    WRITES = (
        "cat > docs/prd/feat.md <<'EOF'\nx\nEOF",
        "echo x >> docs/prd/feat.md",
        "echo x >| docs/prd/feat.md",
        "make docs 2> docs/prd/feat.md",
        "make docs &> docs/prd/feat.md",
        "echo x >docs/prd/feat.md",
        "echo x > 'docs/prd/feat.md'",
        "cd docs/prd && echo x > feat.md",
        "echo x | tee docs/prd/feat.md",
        "echo x | tee -a docs/prd/feat.md > /dev/null",
        "sed -i '' 's/a/b/' docs/prd/feat.md",
        "sed -i.bak -e 's/a/b/' docs/prd/feat.md",
        "sed --in-place 's/a/b/' docs/prd/feat.md",
        "perl -i -pe 's/a/b/' docs/prd/feat.md",
        "perl -pi -e 's/a/b/' docs/prd/feat.md",
        "mv /tmp/draft.md docs/prd/feat.md",
        "cp -f /tmp/draft.md ./docs/prd/feat.md 2>/dev/null",
        "install -m 644 /tmp/draft.md docs/prd/feat.md",
        "cp /tmp/draft.md \\\n  docs/prd/feat.md",
        # the target as a `/`-boundary suffix of the project-relative path
        "cd docs && echo x > prd/feat.md",
        # R2-N3: prefixes and variants the scan skips or accepts
        "env A=1 sed -i s/a/b/ docs/prd/feat.md",
        "env -i -u HOME A=1 cp /tmp/x docs/prd/feat.md",
        "command cp /tmp/x docs/prd/feat.md",
        "\\cp /tmp/x docs/prd/feat.md",
        "sudo -u builder tee docs/prd/feat.md < /tmp/x",
        "perl -wpi -e 's/a/b/' docs/prd/feat.md",
        "perl -Wi -pe 's/a/b/' docs/prd/feat.md",
        "git mv old.md docs/prd/feat.md",
        "git mv -f old.md docs/prd/feat.md",
        "gsed -i s/a/b/ docs/prd/feat.md",
    )

    def claims_on_a_fresh_write(self, command, diff=None):
        """The evidence of every claim on the PRD after `command`, with the PRD stamped
        now: a fresh mtime per command, so no claim repeats an earlier one, and the
        write always falls inside the window."""
        os.utime(self.prd)
        mtime = os.stat(self.prd).st_mtime
        self.bash(command, diff=diff)
        return [
            r["data"]["evidence"] for r in self.events(event_type="artifact-written")
            if r["data"]["path"] == f"docs/prd/{SLUG}.md" and r["data"]["mtime"] == mtime
        ]

    def test_a_read_never_claims(self):
        usable_empty_diff = {"changedFiles": [], "files": [], "moreFiles": 0}
        for command in self.READS:
            for diff in (None, usable_empty_diff):
                with self.subTest(command=command, diff=diff):
                    self.assertEqual(self.claims_on_a_fresh_write(command, diff), [])

    def test_each_write_shape_is_a_window_claim(self):
        for command in self.WRITES:
            with self.subTest(command=command):
                self.assertEqual(self.claims_on_a_fresh_write(command), ["window"])

    def test_an_absolute_target_matches_only_the_artifact_itself(self):
        """R2-N2: an absolute target counts only when it is the artifact's own path."""
        self.assertEqual(self.claims_on_a_fresh_write(f"echo x > {self.prd}"), ["window"])
        self.assertEqual(
            self.claims_on_a_fresh_write(f"cp /tmp/x {self.root}/docs/../docs/prd/feat.md"),
            ["window"],
        )
        elsewhere = self.root.parent / "elsewhere" / "docs" / "prd" / "feat.md"
        self.assertEqual(self.claims_on_a_fresh_write(f"echo x > {elsewhere}"), [])

    def test_without_a_usable_duration_there_is_no_window(self):
        for duration in (None, "1500", True, -5, float("inf"), float("nan")):
            with self.subTest(duration=duration):
                self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF", duration_ms=duration)
        self.assertEqual(self.claims(), [])

    def test_an_unusable_diff_falls_back_to_the_window(self):
        unusable = (
            {"unavailable": True, "changedFiles": [str(self.prd)]},
            {"skipped": True, "changedFiles": [str(self.prd)]},
            {"files": [], "moreFiles": 0},
        )
        for diff in unusable:
            with self.subTest(diff=diff):
                self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF", diff=diff)
        # one write, one session: the repeats of the window claim are duplicates
        self.assertEqual(self.claims(), [(f"docs/prd/{SLUG}.md", "bash", "window", SESSION)])

    def test_a_malformed_diff_is_no_diff(self):
        malformed = (
            "oops",
            ["a"],
            {"changedFiles": str(self.prd)},
            {"changedFiles": [str(self.prd), 7]},
            {"changedFiles": [f"docs/prd/{SLUG}.md"]},
            {"changedFiles": [str(self.prd)], "unavailable": "yes"},
            {"changedFiles": [str(self.prd)], "skipped": None},
        )
        for diff in malformed:
            with self.subTest(diff=diff):
                self.bash("python3 tools/regen.py", diff=diff, duration_ms=None)
        for response in ("not an object", None, ["x"]):
            with self.subTest(tool_response=response):
                self.bash("python3 tools/regen.py", duration_ms=None,
                          tool_response=response)
        self.assertEqual(self.claims(), [])

    def test_a_background_command_claims_nothing(self):
        self.bash(
            "cat > docs/prd/feat.md <<'EOF'\n...\nEOF", background=True,
            diff={"changedFiles": [str(self.prd)], "files": [], "moreFiles": 1},
        )
        self.assertEqual(self.claims(), [])

    def test_auto_capture_off_claims_nothing(self):
        sidecar = self.root / ".claude" / "shipgate.json"
        config = json.loads(sidecar.read_text())
        config["enforce"]["auto_capture"] = False
        sidecar.write_text(json.dumps(config), encoding="utf-8")
        self.bash("cat > docs/prd/feat.md <<'EOF'\n...\nEOF")
        self.assertEqual(self.claims(), [])

    def test_a_malformed_tool_input_is_survived(self):
        for tool_input in ("cat docs/prd/feat.md", None, ["x"]):
            with self.subTest(tool_input=tool_input):
                result = run_hook("post_tool_use", {
                    "session_id": SESSION, "cwd": str(self.root), "tool_name": "Bash",
                    "tool_input": tool_input, "duration_ms": 1500,
                }, self.root)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
        self.assertEqual(self.claims(), [])


class TestBashHookRunsTheJournalOnlyForAClaim(StubJournalMixin, HookTestCase):
    """Every Bash call in every project starts this hook; almost all of them claim nothing."""

    # The default stub, plus a copy of what `append --batch` reads on stdin.
    STUB = """#!/usr/bin/env python3
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "calls.log"), "a", encoding="utf-8") as handle:
    handle.write("\\t".join(sys.argv[1:]) + "\\n")
if "--batch" in sys.argv[1:]:
    with open(os.path.join(root, "batch.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(sys.stdin.read())
"""

    def batch(self) -> list[tuple[str, str]]:
        lines = (self.plugin / "batch.jsonl").read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return [(r["data"]["path"], r["data"]["evidence"]) for r in records]

    def setUp(self) -> None:
        super().setUp()
        self._elsewhere = tempfile.TemporaryDirectory()
        self.elsewhere = Path(self._elsewhere.name).resolve()
        self.addCleanup(self._elsewhere.cleanup)

    def run_bash(self, cwd: Path, command: str, diff=None):
        response = {"stdout": "", "stderr": "", "interrupted": False}
        if diff is not None:
            response["bashEditDiff"] = diff
        return run_hook(
            "post_tool_use",
            {
                "session_id": SESSION,
                "cwd": str(cwd),
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "tool_response": response,
                "duration_ms": 1500,
            },
            cwd,
            hooks_dir=self.plugin / "hooks",
        )

    def test_an_unjournaled_project_never_runs_the_journal(self):
        notes = self.elsewhere / "docs" / "prd" / "feat.md"
        notes.parent.mkdir(parents=True)
        notes.write_text("# x\n", encoding="utf-8")
        result = self.run_bash(
            self.elsewhere, "cat > docs/prd/feat.md <<'EOF'\nx\nEOF",
            diff={"changedFiles": [str(notes)], "files": [], "moreFiles": 1},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.plugin / "calls.log").exists())
        self.assertFalse((self.elsewhere / ".claude").exists())

    def test_a_call_with_no_claim_never_runs_the_journal(self):
        result = self.run_bash(self.root, "ls -la")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.plugin / "calls.log").exists())

    def test_every_claim_goes_in_one_journal_run(self):
        self.prd.write_text("# PRD v2\n", encoding="utf-8")
        self.worklog.write_text(WORKLOG_ONE_TICKED, encoding="utf-8")
        result = self.run_bash(self.root, "python3 tools/regen.py", diff={
            "changedFiles": [str(self.prd), str(self.worklog)],
            "files": [], "moreFiles": 2,
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(
            self.journal_args("append"),
            ["append", "--stream", "shipgate", "--batch", "--actor", "hook"],
        )
        self.assertEqual(self.batch(), [
            (f"docs/prd/{SLUG}.md", "diff"), (f"docs/prd/{SLUG}.worklog.md", "diff"),
        ])

    def test_diff_and_window_claims_share_one_journal_run(self):
        """A listed artifact is claimed once, by the diff; the window covers the rest."""
        self.prd.write_text("# PRD v2\n", encoding="utf-8")
        self.worklog.write_text(WORKLOG_ONE_TICKED, encoding="utf-8")
        result = self.run_bash(
            self.root,
            f"python3 tools/regen.py > docs/prd/{SLUG}.md"
            f" && sed -i.bak 's/a/b/' docs/prd/{SLUG}.worklog.md",
            diff={"changedFiles": [str(self.prd)], "files": [], "moreFiles": 1},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.batch(), [
            (f"docs/prd/{SLUG}.md", "diff"), (f"docs/prd/{SLUG}.worklog.md", "window"),
        ])


class TestHookWiring(unittest.TestCase):
    def test_post_tool_use_fires_on_the_file_tools_and_bash(self):
        config = json.loads((HOOKS / "core.json").read_text(encoding="utf-8"))
        matchers = [entry["matcher"] for entry in config["hooks"]["PostToolUse"]]
        self.assertEqual(matchers, ["Write|Edit|NotebookEdit|Bash"])


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

    def test_a_bash_call_is_silent_and_creates_nothing(self):
        result = run_hook(
            "post_tool_use",
            {
                "session_id": "s",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "cat > docs/notes.md <<'EOF'\nx\nEOF"},
                "tool_response": {"bashEditDiff": {"changedFiles": [str(self.file)]}},
                "duration_ms": 1500,
            },
            self.root,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual(list(self.root.rglob("*.db")), [])

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


# SC-008: hooks run on every user's machine in every project, so the code graph stays out of
# them. A hook never names codegraph and never loads the signals script (which can call it).
_HOOK_FORBIDDEN = (
    ("names codegraph", re.compile(r"codegraph", re.I)),
    ("loads signals.py", re.compile(r"signals\.py|\bimport\s+signals\b|\bfrom\s+signals\b"
                                    r"|[\"']signals[\"']")),
)


def hook_violations(hooks_dir: Path) -> list[str]:
    """`<file>: <rule>` for every hook source file that breaks an SC-008 rule."""
    found = []
    for path in sorted(hooks_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for rule, pattern in _HOOK_FORBIDDEN:
            if pattern.search(text):
                found.append(f"{path.relative_to(hooks_dir).as_posix()}: {rule}")
    return found


class TestHooksStayOffTheCodeGraph(unittest.TestCase):
    def test_no_hook_names_codegraph_or_loads_signals(self):
        self.assertEqual(hook_violations(HOOKS), [])

    def test_the_guard_catches_each_rule(self):
        planted = {
            "a.py": "import subprocess\nsubprocess.run(['CodeGraph', 'sync'])\n",
            "b.py": "spec = importlib.util.spec_from_file_location('s', 'scripts/signals.py')\n",
            "c.py": "import signals\n",
            "d.py": "from signals import analyse\n",
            "e.json": '{"command": "python3 x/codegraph_probe.py"}\n',
            "ok.py": "import json  # signal handling, no graph\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, text in planted.items():
                (root / name).write_text(text, encoding="utf-8")
            self.assertEqual(hook_violations(root), [
                "a.py: names codegraph",
                "b.py: loads signals.py",
                "c.py: loads signals.py",
                "d.py: loads signals.py",
                "e.json: names codegraph",
            ])


if __name__ == "__main__":
    unittest.main()
