#!/usr/bin/env python3
"""Tests for shipgate's codegraph integration: the hermetic harness, the shim, the
`Code graph` config, and the preflight in ``scripts/_codegraph.py``.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_codegraph.py'

Every codegraph call goes to the shim in ``fixtures/codegraph_shim.py``; the real
binary never runs here.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_signals
from test_signals import (
    USAGE,
    TESTS_DIR,
    FixtureRepo,
    SignalsCase,
    hermetic_env,
    load_signals_module,
    make_codegraph_shim,
    ts,
)

FIXTURES = TESTS_DIR / "fixtures" / "codegraph"


def read_log(path: Path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def commands(log):
    return [entry["argv"][0] for entry in log]


def make_socket(path: Path) -> None:
    """A real unix socket file at PATH. Bound by its relative name from inside its
    directory: macOS caps a socket path at about 104 bytes."""
    import socket

    sock = socket.socket(socket.AF_UNIX)
    here = os.getcwd()
    os.chdir(str(path.parent))
    try:
        sock.bind(path.name)
    finally:
        os.chdir(here)
        sock.close()


def fake_daemon(index: Path, pid=None) -> None:
    """`daemon.pid` naming PID (default: this process) and a `daemon.sock` socket."""
    (index / "daemon.pid").write_text(json.dumps({"pid": pid or os.getpid()}))
    make_socket(index / "daemon.sock")


# ---------------------------------------------------------------------------
# T02 — hermetic harness
# ---------------------------------------------------------------------------


class TestHermeticHarness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name).resolve() / "bin"
        make_codegraph_shim(self.bin, "ok")
        path = str(self.bin) + os.pathsep + os.environ.get("PATH", "")
        patcher = mock.patch.dict(os.environ, {"PATH": path,
                                               "SHIPGATE_CODEGRAPH_BIN": "x"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_hermetic_env_strips_every_path_entry_holding_codegraph(self):
        env = hermetic_env()
        entries = env["PATH"].split(os.pathsep)
        self.assertNotIn(str(self.bin), entries)
        for entry in entries:
            self.assertFalse(os.access(os.path.join(entry or ".", "codegraph"), os.X_OK),
                             entry)
        self.assertNotIn("SHIPGATE_CODEGRAPH_BIN", env)

    def test_run_signals_uses_the_hermetic_env_unless_a_test_passes_its_own(self):
        seen = []

        def fake_run(argv, **kwargs):
            seen.append(kwargs["env"])
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(test_signals.subprocess, "run", fake_run):
            test_signals.run_signals(["hotspots"])
            test_signals.run_signals(["hotspots"], env={"PATH": str(self.bin)})
        self.assertNotIn(str(self.bin), seen[0]["PATH"].split(os.pathsep))
        self.assertEqual(seen[1], {"PATH": str(self.bin)})


# ---------------------------------------------------------------------------
# T03 — the codegraph shim
# ---------------------------------------------------------------------------


class ShimCase(unittest.TestCase):
    mode = "ok"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.log = self.tmp / "shim.jsonl"
        self.shim = make_codegraph_shim(self.tmp / "bin", self.mode)
        self.repo = FixtureRepo(self.tmp / "repo")
        self.repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n", "b.py": "2\n"})

    def shim_run(self, *args, mode=None, timeout=30, extra_env=None):
        if mode is not None:
            make_codegraph_shim(self.tmp / "bin", mode)
        env = dict(hermetic_env(), SHIM_LOG=str(self.log), **(extra_env or {}))
        return subprocess.run([str(self.shim), *args], cwd=str(self.repo.path),
                              env=env, capture_output=True, text=True, timeout=timeout)


class TestShim(ShimCase):
    def test_ok_replays_version_status_and_queries(self):
        self.assertEqual(self.shim_run("--version").stdout.strip(), "1.6.2")
        status = json.loads(self.shim_run("status", "--json",
                                          str(self.repo.path)).stdout)
        self.assertIs(status["initialized"], False)
        self.assertEqual(status["projectPath"], str(self.repo.path))
        for command, name in (("affected", "affected.json"), ("impact", "impact.json"),
                              ("callers", "callers.json"), ("callees", "callees.json"),
                              ("query", "query.json"), ("files", "files.json"),
                              ("explore", "explore.txt")):
            proc = self.shim_run(command, "x", "-p", str(self.repo.path))
            self.assertEqual(proc.returncode, 0, command)
            self.assertEqual(proc.stdout, (FIXTURES / name).read_text(encoding="utf-8"))
        root = ("-p", str(self.repo.path))
        self.assertEqual(self.shim_run("node", "a/b.py", *root).stdout,
                         (FIXTURES / "node-file.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.shim_run("node", "resolve_db", *root).stdout,
                         (FIXTURES / "node-symbol.txt").read_text(encoding="utf-8"))

    def test_init_writes_the_index_and_its_gitignore(self):
        proc = self.shim_run("init", "-y", str(self.repo.path),
                             extra_env={"SHIM_EDGES": '[["a.py", "b.py"]]'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        index = self.repo.path / ".codegraph"
        self.assertEqual((index / ".gitignore").read_text(encoding="utf-8").splitlines()[1:],
                         ["*", "!.gitignore"])
        conn = sqlite3.connect(str(index / "codegraph.db"))
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT max(version) FROM schema_versions")
                         .fetchone()[0], 11)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
        self.assertTrue({"source", "target", "kind"} <= columns)
        files = {row[0] for row in conn.execute("SELECT DISTINCT file_path FROM nodes")}
        self.assertEqual(files, {"a.py", "b.py"})
        cross = conn.execute(
            "SELECT s.file_path, t.file_path, e.kind FROM edges e "
            "JOIN nodes s ON s.id = e.source JOIN nodes t ON t.id = e.target "
            "WHERE s.file_path != t.file_path").fetchall()
        self.assertEqual(cross, [("a.py", "b.py", "imports")])
        status = json.loads(self.shim_run("status", "--json",
                                          str(self.repo.path)).stdout)
        self.assertIs(status["initialized"], True)
        self.assertEqual(status["fileCount"], 104)
        self.assertEqual(status["dbSizeBytes"], (index / "codegraph.db").stat().st_size)

    def test_every_call_is_logged_with_argv_cwd_and_the_codegraph_env(self):
        self.shim_run("--version")
        self.shim_run("sync", str(self.repo.path),
                      extra_env={"CODEGRAPH_TELEMETRY": "0", "CODEGRAPH_NO_DAEMON": "1"})
        log = read_log(self.log)
        self.assertEqual([e["argv"] for e in log],
                         [["--version"], ["sync", str(self.repo.path)]])
        self.assertEqual(log[0]["cwd"], str(self.repo.path))
        self.assertEqual((log[0]["CODEGRAPH_TELEMETRY"], log[1]["CODEGRAPH_TELEMETRY"]),
                         (None, "0"))
        self.assertEqual(log[1]["CODEGRAPH_NO_DAEMON"], "1")

    def test_failure_modes(self):
        self.assertEqual(self.shim_run("--version", mode="old-version").stdout.strip(),
                         "1.5.0")
        garbage = self.shim_run("status", "--json", mode="garbage").stdout
        with self.assertRaises(ValueError):
            json.loads(garbage)
        uninit = self.shim_run("init", "-y", str(self.repo.path), mode="uninit")
        self.assertNotEqual(uninit.returncode, 0)
        self.assertFalse((self.repo.path / ".codegraph" / "codegraph.db").exists())
        self.assertEqual(self.shim_run("sync", mode="kill").returncode, -9)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.shim_run("sync", mode="hang", timeout=1)

    def test_lifecycle_commands_reject_p_like_the_real_cli(self):
        # codegraph 1.6.2: status, sync and init take the path positionally only.
        repo = str(self.repo.path)
        for argv in (["status", "--json", "-p", repo], ["sync", "-p", repo],
                     ["init", "-y", "-p", repo]):
            with self.subTest(argv=argv):
                proc = self.shim_run(*argv)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("error: unknown option '-p'", proc.stderr)
        self.assertFalse((self.repo.path / ".codegraph").exists())

    def test_queries_need_p_and_an_existing_directory(self):
        missing = str(self.tmp / "missing")
        for command in ("query", "affected", "node", "explore", "impact", "callers",
                        "callees", "files"):
            with self.subTest(command=command):
                self.assertNotEqual(self.shim_run(command, "x").returncode, 0)
                self.assertNotEqual(self.shim_run(command, "x", "-p").returncode, 0)
                self.assertNotEqual(
                    self.shim_run(command, "x", "-p", missing).returncode, 0)

    def test_corrupt_and_mismatched_databases(self):
        db = self.repo.path / ".codegraph" / "codegraph.db"
        self.shim_run("init", "-y", str(self.repo.path), mode="corrupt-db")
        self.assertNotEqual(db.read_bytes()[:16], b"SQLite format 3\0")
        self.shim_run("init", "-y", str(self.repo.path), mode="schema-mismatch")
        conn = sqlite3.connect(str(db))
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT max(version) FROM schema_versions")
                         .fetchone()[0], 10)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
        self.assertNotIn("kind", columns)


# ---------------------------------------------------------------------------
# T04 — the `Code graph` bullet and the --graph flag
# ---------------------------------------------------------------------------


class TestCodeGraphConfig(SignalsCase):
    """FR-015: one optional bullet under `## Code tooling`; --graph overrides it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.umbrella = Path(tmp.name).resolve() / "umbrella"
        FixtureRepo(self.umbrella)
        self.repo = FixtureRepo(self.umbrella / "repo")
        self.repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})

    def write_config(self, where: Path, body: str):
        target = where / ".claude" / "shipgate.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def graph(self, *args):
        cfg = self.signals_json("hotspots", "--repo", self.repo.path, *args)["config"]
        return cfg["code_graph"], cfg["source"]["code_graph"]

    def test_default_is_auto(self):
        self.assertEqual(self.graph(), ("auto", "default"))

    def test_backticked_and_bare_values(self):
        for value, expected in (("`off`", "off"), ("root", "root"), ("`auto`", "auto"),
                                (" `ROOT` ", "root")):
            with self.subTest(value=value):
                self.write_config(self.repo.path,
                                  f"## Code tooling\n\n- Code graph: {value}\n")
                self.assertEqual(self.graph(), (expected, "shipgate.md"))

    def test_the_bullet_outside_code_tooling_is_ignored(self):
        self.write_config(self.repo.path, "## Code signals\n- Code graph: `off`\n")
        self.assertEqual(self.graph(), ("auto", "default"))

    def test_a_placeholder_counts_as_absent(self):
        for value in ("<auto | off | root>", "`<auto|off|root>`", ""):
            with self.subTest(value=value):
                self.write_config(self.repo.path,
                                  f"## Code tooling\n- Code graph: {value}\n")
                self.assertEqual(self.graph(), ("auto", "default"))

    def test_an_invalid_value_is_a_usage_error(self):
        self.write_config(self.repo.path, "## Code tooling\n- Code graph: `sometimes`\n")
        proc = self.signals("hotspots", "--repo", self.repo.path, "--json", rc=USAGE)
        self.assertIn("Code graph", proc.stderr)
        self.assertIn("sometimes", proc.stderr)
        self.assertIn("auto, off or root", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_the_repo_config_beats_the_umbrella_config(self):
        self.write_config(self.umbrella, "## Code tooling\n- Code graph: `root`\n")
        self.assertEqual(self.graph(), ("root", "shipgate.md"))
        self.write_config(self.repo.path, "## Code tooling\n- Code graph: `off`\n")
        self.assertEqual(self.graph(), ("off", "shipgate.md"))

    def test_the_flag_overrides_the_file(self):
        self.write_config(self.repo.path, "## Code tooling\n- Code graph: `off`\n")
        self.assertEqual(self.graph("--graph", "root"), ("root", "flag"))
        self.signals("hotspots", "--repo", self.repo.path, "--graph", "never", rc=USAGE)

    def test_every_subcommand_takes_the_flag(self):
        for argv in (["hotspots"], ["blast", "a.py"], ["suspects", "a.py"]):
            with self.subTest(argv=argv):
                payload = self.signals_json(*argv, "--repo", self.repo.path,
                                            "--graph", "off")
                self.assertEqual(payload["config"]["code_graph"], "off")

    def test_the_template_bullet_is_a_placeholder(self):
        mod = load_signals_module()
        template = (TESTS_DIR.parent / "config-template.md").read_text(encoding="utf-8")
        bullets = dict(mod.section_bullets(template, "code tooling"))
        self.assertIn("code graph", bullets)
        self.assertEqual(mod.parse_code_graph(template), {})
        self.write_config(self.repo.path, template)
        self.assertEqual(self.graph(), ("auto", "default"))

    def test_section_bullets_is_the_one_walk(self):
        mod = load_signals_module()
        text = ("## Code tooling\n- Code graph: `off`\n```\n- Code graph: `root`\n```\n"
                "## Code signals\n- Window: `3`\n")
        self.assertEqual(mod.section_bullets(text, "code tooling"),
                         [("code graph", "`off`")])
        self.assertEqual(mod.parse_code_signals(text), {"window_months": 3})


# ---------------------------------------------------------------------------
# T05 — detect, exclude, init, lock, freshen, env
# ---------------------------------------------------------------------------


class GraphCase(unittest.TestCase):
    """In-process calls of `signals.graph_select`; codegraph is the shim."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_signals_module()
        cls.cg = cls.mod._codegraph

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.log = self.tmp / "shim.jsonl"
        self.bin = self.tmp / "bin"
        self.shim = make_codegraph_shim(self.bin, "ok")
        env = dict(hermetic_env(), SHIM_LOG=str(self.log),
                   SHIPGATE_CODEGRAPH_BIN=str(self.shim))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.make_repo(self.tmp / "repo")

    def make_repo(self, path: Path) -> FixtureRepo:
        repo = FixtureRepo(path)
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n", "b.py": "2\n"})
        return repo

    def mode(self, mode):
        make_codegraph_shim(self.bin, mode)

    def select(self, repo=None, mode="auto"):
        return self.mod.graph_select((repo or self.repo).path, mode)

    def calls(self):
        return read_log(self.log)

    def porcelain(self, repo):
        return repo.git("status", "--porcelain", "--untracked-files=all")

    def common_dir(self, repo) -> Path:
        out = repo.git("rev-parse", "--git-common-dir").strip()
        return (repo.path / out).resolve()


class TestDetect(GraphCase):
    """FR-001: present = on PATH, version >= 1.6.0, `status --json` parses."""

    def assert_absent(self, reason):
        with self.assertRaises(self.cg.GraphUnavailable) as caught:
            self.cg.detect(self.repo.path)
        self.assertEqual(caught.exception.reason, reason)
        result = self.select()
        self.assertEqual((result.available, result.source, result.state, result.reason),
                         (False, "regex", "absent", reason))
        self.assertIsNone(result.built)

    def test_not_installed(self):
        os.environ["SHIPGATE_CODEGRAPH_BIN"] = str(self.tmp / "missing" / "codegraph")
        self.assert_absent("graph-not-installed")

    def test_not_installed_on_path(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        self.assert_absent("graph-not-installed")
        self.assertEqual(self.calls(), [])

    def test_found_on_path(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        os.environ["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.assertTrue(self.select().available)

    def test_old_version(self):
        self.mode("old-version")
        self.assert_absent("graph-version")

    def test_a_garbage_status_after_a_build_is_a_failure_not_absent(self):
        # Detection runs no `status`: it walks up and can take a minute. A status
        # that does not parse shows up after the build, as a failed graph.
        self.mode("garbage")
        self.assertEqual(self.cg.detect(self.repo.path), "1.6.2")
        result = self.select()
        self.assertEqual((result.available, result.state, result.reason),
                         (False, "failed", "graph-status"))
        self.assertIsNone(result.advisory)
        self.assertEqual(commands(self.calls()), ["--version", "--version", "init",
                                                  "status"])

    def test_present(self):
        self.assertEqual(self.cg.detect(self.repo.path), "1.6.2")
        self.assertEqual(commands(self.calls()), ["--version"])

    def test_version_floor(self):
        parse = self.cg.parse_version
        self.assertEqual(parse("codegraph 1.6.0\n"), (1, 6, 0))
        self.assertIsNone(parse("v1.6"))
        self.assertTrue(parse("1.10.0") >= self.cg.MIN_VERSION)
        self.assertFalse(parse("1.5.9") >= self.cg.MIN_VERSION)


class TestBuild(GraphCase):
    """FR-002 / FR-003 / SC-005: exclude first, `init -y` once, `built` once."""

    def test_init_runs_once_and_built_is_reported_once(self):
        first = self.select()
        self.assertEqual((first.available, first.source, first.state, first.reason),
                         (True, "graph", "present", None))
        self.assertEqual(first.version, "1.6.2")
        self.assertEqual(first.index_root, self.repo.path)
        self.assertEqual(first.sync, "none")  # a fresh build needs no sync
        db = self.repo.path / ".codegraph" / "codegraph.db"
        self.assertEqual(first.built["files"], 104)
        self.assertEqual(first.built["bytes"], db.stat().st_size)
        self.assertIsInstance(first.built["seconds"], float)
        second = self.select()
        self.assertTrue(second.available)
        self.assertIsNone(second.built)
        inits = [e["argv"] for e in self.calls() if e["argv"][0] == "init"]
        self.assertEqual(inits, [["init", "-y", str(self.repo.path)]])
        json.dumps(first.to_json())  # the envelope block serialises

    def test_git_status_is_clean_after_a_build_and_the_exclude_is_written_once(self):
        exclude = self.common_dir(self.repo) / "info" / "exclude"
        self.select()
        self.assertEqual(self.porcelain(self.repo), "")
        # Force a second build: the line is still there once.
        import shutil

        shutil.rmtree(self.repo.path / ".codegraph")
        self.select()
        self.assertEqual(self.porcelain(self.repo), "")
        lines = exclude.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count("/.codegraph/"), 1)
        self.assertEqual(commands(self.calls()).count("init"), 2)

    def test_the_exclude_line_is_written_before_init(self):
        self.mode("uninit")  # init fails: the exclude line must already be there
        result = self.select()
        self.assertEqual((result.available, result.reason), (False, "graph-init"))
        exclude = self.common_dir(self.repo) / "info" / "exclude"
        self.assertIn("/.codegraph/", exclude.read_text(encoding="utf-8").splitlines())

    def test_an_exclude_file_without_a_final_newline_keeps_its_last_line(self):
        exclude = self.common_dir(self.repo) / "info" / "exclude"
        exclude.write_text("# mine\n*.log", encoding="utf-8")
        self.select()
        self.assertEqual(exclude.read_text(encoding="utf-8").splitlines(),
                         ["# mine", "*.log", "/.codegraph/"])

    def test_a_missing_info_dir_is_created(self):
        import shutil

        shutil.rmtree(self.common_dir(self.repo) / "info")
        self.assertTrue(self.select().available)
        self.assertEqual(self.porcelain(self.repo), "")

    def test_a_linked_worktree_writes_the_common_exclude(self):
        worktree = self.tmp / "wt"
        self.repo.git("worktree", "add", "-q", "-b", "feature/x", str(worktree))
        result = self.mod.graph_select(worktree, "auto")
        self.assertTrue(result.available, result.reason)
        self.assertEqual(result.index_root, worktree)
        exclude = self.common_dir(self.repo) / "info" / "exclude"
        self.assertIn("/.codegraph/", exclude.read_text(encoding="utf-8").splitlines())
        status = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain",
                                 "--untracked-files=all"],
                                capture_output=True, text=True)
        self.assertEqual(status.stdout, "")
        self.assertIn(["init", "-y", str(worktree)], [e["argv"] for e in self.calls()])

    def test_the_lock_lives_in_the_git_common_dir(self):
        self.select()
        self.assertTrue((self.common_dir(self.repo) / "shipgate" / "codegraph.lock")
                        .is_file())

    def test_the_file_guard_skips_the_build_with_an_advisory(self):
        os.environ["SHIPGATE_CODEGRAPH_MAX_FILES"] = "1"  # the repo tracks 2 files
        result = self.select()
        self.assertEqual((result.available, result.state, result.reason),
                         (False, "absent", "graph-too-large"))
        self.assertIn("codegraph init", result.advisory)
        # FR-018: the repository by its directory name, never its absolute path.
        self.assertIn("Run `codegraph init` in repo yourself", result.advisory)
        self.assertNotIn(str(self.repo.path), result.advisory)
        self.assertNotIn("init", commands(self.calls()))
        self.assertFalse((self.repo.path / ".codegraph").exists())
        exclude = self.common_dir(self.repo) / "info" / "exclude"
        self.assertNotIn("/.codegraph/", exclude.read_text(encoding="utf-8"))
        # The count passed in wins over git's.
        os.environ["SHIPGATE_CODEGRAPH_MAX_FILES"] = "10"
        result = self.mod.graph_select(self.repo.path, "auto", tracked_count=11)
        self.assertEqual(result.reason, "graph-too-large")

    def test_a_hung_init_times_out(self):
        self.mode("hang")
        os.environ["SHIPGATE_CODEGRAPH_TIMEOUT"] = "1"
        result = self.select()
        self.assertEqual((result.available, result.state, result.reason),
                         (False, "failed", "graph-timeout"))


class TestFreshen(GraphCase):
    """FR-005: a live daemon means query now; otherwise `sync -p` first."""

    def setUp(self):
        super().setUp()
        self.select()  # build
        self.log.unlink()
        self.index = self.repo.path / ".codegraph"

    def test_a_live_pid_and_socket_skip_sync(self):
        fake_daemon(self.index)
        result = self.select()
        self.assertEqual(result.sync, "daemon")
        self.assertNotIn("sync", commands(self.calls()))

    def test_a_dead_pid_runs_sync(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        fake_daemon(self.index, proc.pid)
        result = self.select()
        self.assertEqual(result.sync, "sync")
        self.assertIn(["sync", str(self.repo.path)],
                      [e["argv"] for e in self.calls()])

    def test_a_live_pid_without_a_socket_runs_sync(self):
        (self.index / "daemon.pid").write_text(json.dumps({"pid": os.getpid()}))
        self.assertEqual(self.select().sync, "sync")

    def test_an_unreadable_pid_file_runs_sync(self):
        (self.index / "daemon.pid").write_text("not json")
        make_socket(self.index / "daemon.sock")
        self.assertEqual(self.select().sync, "sync")

    def test_r2_4_the_socket_path_comes_from_the_pid_file(self):
        short = Path(tempfile.mkdtemp(prefix="cg", dir="/tmp")).resolve()
        self.addCleanup(shutil.rmtree, str(short), True)
        make_socket(short / "d.sock")
        (self.index / "daemon.pid").write_text(json.dumps(
            {"pid": os.getpid(), "socketPath": str(short / "d.sock")}))
        self.assertFalse((self.index / "daemon.sock").exists())
        result = self.select()
        self.assertEqual(result.sync, "daemon")
        self.assertNotIn("sync", commands(self.calls()))

    def test_r2_4_a_socket_path_that_is_not_a_socket_runs_sync(self):
        make_socket(self.index / "daemon.sock")  # the fallback would pass
        (self.index / "daemon.pid").write_text(json.dumps(
            {"pid": os.getpid(), "socketPath": str(self.index / "daemon.pid")}))
        self.assertEqual(self.select().sync, "sync")

    def test_r2_7_a_seed_with_a_line_break_is_skipped(self):
        tests = self.cg.tests_reached(self.repo.path, self.repo.path,
                                      ["a.py", "bad\nname.py", "cr\rname.py"],
                                      ["a.py", "b.py"])
        self.assertEqual(tests, [])
        stdin = [e["stdin"] for e in self.calls() if e["argv"][0] == "affected"]
        self.assertEqual(stdin, ["a.py\n"])

    def test_r3_4_only_unsendable_seeds_is_a_reason_not_no_tests(self):
        with self.assertRaises(self.cg.GraphUnavailable) as caught:
            self.cg.tests_reached(self.repo.path, self.repo.path,
                                  ["bad\nname.py", "cr\rname.py"], ["a.py", "b.py"])
        self.assertEqual(caught.exception.reason, "graph-affected-seeds")
        self.assertNotIn("affected", commands(self.calls()))
        self.assertEqual(self.cg.tests_reached(self.repo.path, self.repo.path, [],
                                               ["a.py"]), [])

    def test_a_regular_file_is_not_a_socket(self):
        # F4: `daemon.sock` must be a socket, not any file of that name.
        (self.index / "daemon.pid").write_text(json.dumps({"pid": os.getpid()}))
        (self.index / "daemon.sock").write_text("")
        self.assertEqual(self.select().sync, "sync")

    def test_a_pid_we_may_not_signal_is_not_alive(self):
        # F4: a PermissionError from kill(pid, 0) is another user's process.
        fake_daemon(self.index)
        with mock.patch.object(self.cg.os, "kill", side_effect=PermissionError):
            self.assertEqual(self.select().sync, "sync")

    def test_a_failed_sync_is_a_reason(self):
        self.mode("kill")
        result = self.select()
        self.assertEqual((result.available, result.state, result.reason),
                         (False, "failed", "graph-sync"))


class TestEnvironment(GraphCase):
    """FR-016: every call runs with telemetry and the daemon off, in the repo."""

    def test_every_call_carries_the_codegraph_env(self):
        self.select()
        self.select()
        log = self.calls()
        self.assertEqual(set(commands(log)), {"--version", "status", "init", "sync"})
        for entry in log:
            self.assertEqual(entry["CODEGRAPH_TELEMETRY"], "0", entry)
            self.assertEqual(entry["CODEGRAPH_NO_DAEMON"], "1", entry)
            self.assertEqual(entry["cwd"], str(self.repo.path), entry)

    def test_lifecycle_commands_take_the_path_positionally(self):
        self.select()  # build: status, init, status
        self.select()  # fresh: status, sync
        lifecycle = [e["argv"] for e in self.calls()
                     if e["argv"][0] in ("status", "sync", "init")]
        self.assertEqual({argv[0] for argv in lifecycle}, {"status", "sync", "init"})
        for argv in lifecycle:
            self.assertNotIn("-p", argv)
            self.assertEqual(argv[-1], str(self.repo.path), argv)

    def test_the_users_own_env_is_untouched(self):
        self.select()
        self.assertNotIn("CODEGRAPH_TELEMETRY", os.environ)


class TestUmbrella(GraphCase):
    """FR-013 / FR-014 / SC-006: the child repo owns its index; `root` is opt-in."""

    def setUp(self):
        super().setUp()
        self.umbrella = FixtureRepo(self.tmp / "umbrella")
        self.umbrella.commit("ignore the child", ts(2020, 1, 1),
                             writes={".gitignore": "child/\n"})
        self.child = self.make_repo(self.tmp / "umbrella" / "child")

    def test_every_call_targets_the_child(self):
        result = self.select(self.child)
        self.assertTrue(result.available, result.reason)
        self.assertEqual(result.index_root, self.child.path)
        child = str(self.child.path)
        for entry in self.calls():
            argv = entry["argv"]
            if argv == ["--version"]:
                continue
            lifecycle = argv[0] in ("status", "sync", "init")
            self.assertEqual(argv[-1] if lifecycle else argv[argv.index("-p") + 1],
                             child, argv)
            self.assertEqual(entry["cwd"], child)
        self.assertFalse((self.umbrella.path / ".codegraph").exists())
        self.assertEqual(self.porcelain(self.child), "")
        self.assertEqual(self.porcelain(self.umbrella), "")

    def test_root_without_an_umbrella_index_never_builds(self):
        result = self.select(self.child, "root")
        self.assertEqual((result.available, result.reason),
                         (False, "graph-root-not-indexed"))
        self.assertIsNone(result.advisory)
        self.assertNotIn("init", commands(self.calls()))
        self.assertFalse((self.child.path / ".codegraph").exists())

    def test_root_uses_the_umbrella_index(self):
        subprocess.run([str(self.shim), "init", "-y", str(self.umbrella.path)],
                       check=True, capture_output=True)
        self.log.unlink()
        result = self.select(self.child, "root")
        self.assertTrue(result.available, result.reason)
        self.assertEqual(result.index_root, self.umbrella.path)
        self.assertEqual(result.to_json()["index_root"], "..")  # F9
        self.assertNotIn("init", commands(self.calls()))
        for entry in self.calls():
            if entry["argv"] != ["--version"]:
                self.assertIn(str(self.umbrella.path), entry["argv"])

    def test_the_advisory_marker_is_in_the_umbrellas_git_dir(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        self.assertIsNotNone(self.select(self.child).advisory)
        marker = self.common_dir(self.umbrella) / "shipgate" / "codegraph-advised"
        self.assertTrue(marker.is_file())
        self.assertFalse((self.common_dir(self.child) / "shipgate").exists())
        self.assertIsNone(self.select(self.child).advisory)


class TestAdvisoryAndOff(GraphCase):
    """FR-004 / SC-003 (memory part): advise once when absent; `off` calls nothing."""

    def test_the_advisory_appears_once(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        first = self.select()
        self.assertEqual(first.advisory, self.cg.ADVISORY)
        self.assertNotIn("\n", first.advisory)
        self.assertIn("https://github.com/colbymchenry/codegraph", first.advisory)
        self.assertTrue((self.common_dir(self.repo) / "shipgate" / "codegraph-advised")
                        .is_file())
        self.assertIsNone(self.select().advisory)

    def test_an_old_version_is_absent_too(self):
        self.mode("old-version")
        self.assertEqual(self.select().advisory, self.cg.ADVISORY)

    def test_no_advisory_when_present(self):
        self.assertIsNone(self.select().advisory)

    def test_no_advisory_in_root_mode(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        self.assertIsNone(self.select(mode="root").advisory)

    def test_a_marker_that_cannot_be_written_is_not_an_error(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        (self.common_dir(self.repo) / "shipgate").write_text("a file, not a dir")
        self.assertEqual(self.select().advisory, self.cg.ADVISORY)

    def test_off_makes_no_call_and_no_advisory(self):
        del os.environ["SHIPGATE_CODEGRAPH_BIN"]
        result = self.select(mode="off")
        self.assertEqual((result.available, result.source, result.state),
                         (False, "regex", "off"))
        self.assertIsNone(result.advisory)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.common_dir(self.repo) / "shipgate").exists())
        os.environ["SHIPGATE_CODEGRAPH_BIN"] = str(self.shim)
        self.select(mode="off")
        self.assertEqual(self.calls(), [])

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.select(mode="sometimes")


# ---------------------------------------------------------------------------
# T06 — the database reader and the provider swap
# ---------------------------------------------------------------------------

# SC-002: a module the tests load by path. The regex scanner sees no import; the
# graph (modelled with SHIM_EDGES) sees both test files. `affected.json` names the
# same two test files.
SC002_FILES = {
    "shipgate/hooks/_common.py": "def journaled_root():\n    return None\n",
    "shipgate/tests/test_hooks.py": (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('c', 'hooks/_common.py')\n"),
    "shipgate/tests/test_journal.py": (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('c', 'hooks/_common.py')\n"),
    "shipgate/scripts/other.py": "X = 1\n",
}
SC002_EDGES = [["shipgate/tests/test_hooks.py", "shipgate/hooks/_common.py"],
               ["shipgate/tests/test_journal.py", "shipgate/hooks/_common.py", "calls"]]
SC002_TESTS = ["shipgate/tests/test_hooks.py", "shipgate/tests/test_journal.py"]


class TestReadFileGraph(GraphCase):
    """The read-only database reader: edges, filter, probe, open order, root mode."""

    def build(self, repo=None, edges=None):
        repo = repo or self.repo
        if edges is not None:
            os.environ["SHIM_EDGES"] = json.dumps(edges)
        result = self.mod.graph_select(repo.path, "auto")
        self.assertTrue(result.available, result.reason)
        return result

    def read(self, index_root=None, repo_root=None, files=("a.py", "b.py")):
        return self.cg.read_file_graph(index_root or self.repo.path,
                                       repo_root or self.repo.path, list(files))

    def db(self, root=None) -> Path:
        return (root or self.repo.path) / ".codegraph" / "codegraph.db"

    def assert_reason(self, reason, **kwargs):
        with self.assertRaises(self.cg.GraphUnavailable) as caught:
            self.read(**kwargs)
        self.assertEqual(caught.exception.reason, reason)

    def test_cross_file_edges_of_every_kind(self):
        self.build(edges=[["a.py", "b.py"], ["b.py", "a.py", "calls"]])
        graph = self.read()
        self.assertEqual(graph.out, {"a.py": {"b.py"}, "b.py": {"a.py"}})
        self.assertEqual(graph.inn, {"a.py": {"b.py"}, "b.py": {"a.py"}})
        self.assertEqual(graph.files, ["a.py", "b.py"])
        self.assertEqual(graph.languages, ["python"])
        self.assertEqual(graph.outside_repo, 0)

    def test_only_graph_files_are_nodes(self):
        self.build(edges=[["a.py", "b.py"]])
        graph = self.read(files=["a.py"])  # b.py excluded, as the regex scan does
        self.assertEqual(graph.out, {"a.py": set()})
        self.assertEqual(graph.inn, {})
        self.assertEqual(graph.files, ["a.py"])

    def test_no_cross_file_edge_is_zero_importers(self):
        self.build()  # the shim writes `contains` edges inside each file only
        graph = self.read()
        self.assertEqual(graph.out, {"a.py": set(), "b.py": set()})

    def test_an_index_with_files_and_no_edges_is_graph_schema(self):
        self.build()
        conn = sqlite3.connect(str(self.db()))
        conn.execute("DELETE FROM edges")
        conn.commit()
        conn.close()
        self.assert_reason("graph-schema")

    def test_an_old_schema_is_graph_schema(self):
        self.build()
        conn = sqlite3.connect(str(self.db()))
        conn.execute("DELETE FROM schema_versions WHERE version >= 11")
        conn.commit()
        conn.close()
        self.assert_reason("graph-schema")

    def test_a_missing_column_is_graph_schema(self):
        self.mode("schema-mismatch")
        self.mod.graph_select(self.repo.path, "auto")
        self.assert_reason("graph-schema")

    def test_a_missing_table_is_graph_schema(self):
        self.build()
        conn = sqlite3.connect(str(self.db()))
        conn.execute("DROP TABLE files")
        conn.commit()
        conn.close()
        self.assert_reason("graph-schema")

    def test_a_corrupt_file_is_graph_db(self):
        self.mode("corrupt-db")
        self.mod.graph_select(self.repo.path, "auto")
        self.assert_reason("graph-db")

    def test_a_missing_database_is_graph_db(self):
        self.assert_reason("graph-db")

    def test_the_reader_never_writes(self):
        self.build(edges=[["a.py", "b.py"]])
        index = self.db().parent
        before = {p.name: p.stat().st_mtime_ns for p in index.iterdir()}
        self.read()
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in index.iterdir()},
                         before)

    def test_open_order_is_ro_then_immutable(self):
        self.build(edges=[["a.py", "b.py"]])
        real = sqlite3.connect
        seen = []

        def connect(database, *args, **kwargs):
            seen.append(database)
            self.assertIs(kwargs.get("uri"), True)
            if database.endswith("?mode=ro"):
                raise sqlite3.OperationalError("unable to open database file")
            return real(database, *args, **kwargs)

        with mock.patch.object(self.cg.sqlite3, "connect", connect):
            graph = self.read()
        self.assertEqual(graph.out["a.py"], {"b.py"})
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[0].startswith("file:") and seen[0].endswith("?mode=ro"))
        self.assertTrue(seen[1].endswith("?immutable=1"))
        self.assertNotIn("rw", "".join(seen))

    def test_a_wal_database_without_shm_in_a_read_only_dir_opens_immutable(self):
        self.build(edges=[["a.py", "b.py"]])
        conn = sqlite3.connect(str(self.db()))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()
        index = self.db().parent
        for name in ("codegraph.db-shm", "codegraph.db-wal"):
            if (index / name).exists():
                (index / name).unlink()
        index.chmod(0o555)
        self.addCleanup(index.chmod, 0o755)
        if os.access(str(index), os.W_OK):
            self.skipTest("running as a user that ignores directory permissions")
        graph = self.read()
        self.assertEqual(graph.out["a.py"], {"b.py"})
        self.assertFalse((index / "codegraph.db-shm").exists())

    def test_root_mode_rebases_paths_and_counts_files_outside_the_repo(self):
        umbrella = FixtureRepo(self.tmp / "umbrella")
        umbrella.commit("one", ts(2020, 1, 1), writes={
            "child/a.py": "1\n", "child/b.py": "2\n", "other/c.py": "3\n"})
        os.environ["SHIM_EDGES"] = json.dumps([
            ["child/a.py", "child/b.py"], ["other/c.py", "child/a.py"]])
        subprocess.run([str(self.shim), "init", "-y", str(umbrella.path)], check=True,
                       capture_output=True, env=os.environ)
        graph = self.cg.read_file_graph(umbrella.path, umbrella.path / "child",
                                        ["a.py", "b.py"])
        self.assertEqual(graph.out, {"a.py": {"b.py"}, "b.py": set()})
        self.assertEqual(graph.inn, {"b.py": {"a.py"}})
        self.assertEqual(graph.outside_repo, 1)  # other/c.py


class ShimSignalsCase(SignalsCase):
    """`signals.py` as a subprocess, with the shim as codegraph."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.log = self.tmp / "shim.jsonl"
        self.bin = self.tmp / "bin"
        self.shim = make_codegraph_shim(self.bin, "ok")

    def env(self, mode="ok", **extra):
        make_codegraph_shim(self.bin, mode)
        env = dict(hermetic_env(), SHIM_LOG=str(self.log),
                   SHIPGATE_CODEGRAPH_BIN=str(self.shim))
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def absent_env(self):
        return dict(hermetic_env(), SHIM_LOG=str(self.log))

    def make(self, name="repo", files=None) -> FixtureRepo:
        files = files or {"a.py": "1\n", "b.py": "import a\n"}
        repo = FixtureRepo(self.tmp / name)
        repo.commit("one", ts(2020, 1, 1), writes=files)
        first = sorted(files)[0]
        repo.commit("fix: two", ts(2020, 2, 1), writes={first: files[first] + "# 2\n"})
        return repo

    def calls(self):
        return read_log(self.log)

    def common_dir(self, repo) -> Path:
        out = repo.git("rev-parse", "--git-common-dir").strip()
        return (repo.path / out).resolve()


class TestProviderSwap(ShimSignalsCase):
    """FR-007 / SC-002: the graph replaces the regex scan; FR-006: history does not
    change."""

    def setUp(self):
        super().setUp()
        self.repo = self.make(files=SC002_FILES)
        self.graph_env = self.env(SHIM_EDGES=json.dumps(SC002_EDGES))

    def run_json(self, *args, env=None):
        return self.signals_json(*args, "--repo", self.repo.path,
                                 env=env or self.graph_env)

    def test_sc002_blast_reaches_the_tests_that_load_a_module_by_path(self):
        regex = self.run_json("blast", "shipgate/hooks/_common.py", "--graph", "off")
        self.assertEqual(regex["structure"]["source"], "regex")
        self.assertEqual(regex["blast"]["files"], [])
        self.assertIsNone(regex["blast"]["tests"])
        graph = self.run_json("blast", "shipgate/hooks/_common.py")
        self.assertEqual(graph["structure"]["source"], "graph")
        self.assertGreaterEqual(len(graph["blast"]["files"]), 2)
        self.assertEqual(graph["blast"]["files"], SC002_TESTS)
        self.assertGreaterEqual(len(graph["blast"]["tests"]), 2)
        self.assertEqual(graph["blast"]["tests"], SC002_TESTS)
        self.assertIsNone(graph["blast"]["tests_reason"])
        affected = [e for e in self.calls() if e["argv"][0] == "affected"]
        self.assertEqual([e["argv"] for e in affected],
                         [["affected", "--stdin", "-j", "-p", str(self.repo.path)]])
        self.assertEqual(affected[0]["stdin"], "shipgate/hooks/_common.py\n")

    def test_hotspots_blast_carries_the_tests_too(self):
        payload = self.run_json("hotspots", "shipgate/hooks/_common.py", "--blast")
        self.assertEqual(payload["blast"]["tests"], SC002_TESTS)
        table = self.signals("hotspots", "shipgate/hooks/_common.py", "--blast",
                             "--repo", self.repo.path, env=self.graph_env).stdout
        self.assertIn("tests reached: 2 files", table)

    def test_tests_outside_the_graph_files_are_dropped(self):
        payload = self.run_json("blast", "shipgate/hooks/_common.py",
                                "--exclude", "shipgate/tests/")
        self.assertEqual(payload["blast"]["tests"], [])
        self.assertEqual(payload["blast"]["files"], [])

    def test_the_structure_block_names_its_source(self):
        graph = self.run_json("hotspots")["structure"]
        self.assertEqual(graph["source"], "graph")
        self.assertEqual(graph["graph"]["state"], "present")
        self.assertEqual(graph["graph"]["version"], "1.6.2")
        self.assertEqual(graph["graph"]["index_root"], ".")  # F9: never absolute
        self.assertEqual(graph["graph"]["outside_repo"], 0)
        self.assertEqual((graph["available"], graph["languages"], graph["files_scanned"]),
                         (True, ["python"], 4))
        regex = self.run_json("hotspots", "--graph", "off")["structure"]
        self.assertEqual(regex["source"], "regex")
        self.assertEqual(regex["graph"], {
            "state": "off", "reason": "graph-off", "version": None, "index_root": None,
            "built": None, "sync": "none", "outside_repo": None})

    def test_the_first_graph_run_reports_the_build(self):
        payload = self.run_json("hotspots")
        built = payload["structure"]["graph"]["built"]
        self.assertEqual(set(built), {"files", "seconds", "bytes"})
        lines = self.signals("hotspots", "--repo", self.repo.path,
                             env=self.graph_env).stdout.splitlines()
        self.assertFalse(any(line.startswith("code graph: indexed") for line in lines))
        fresh = self.make("fresh", files=SC002_FILES)
        lines = self.signals("hotspots", "--repo", fresh.path,
                             env=self.graph_env).stdout.splitlines()
        self.assertRegex(lines[0], r"^code graph: indexed 104 files in [0-9.]+ s, "
                                   r"[0-9.]+ MB$")

    def test_fan_in_comes_from_the_graph(self):
        rows = {r["path"]: r for r in self.run_json("hotspots")["files"]}
        self.assertEqual(rows["shipgate/hooks/_common.py"]["fan_in"], 2)
        self.assertEqual(rows["shipgate/hooks/_common.py"]["structure"], "ok")
        regex = {r["path"]: r for r in self.run_json("hotspots", "--graph", "off")["files"]}
        self.assertEqual(regex["shipgate/hooks/_common.py"]["fan_in"], 0)

    def test_fr006_trajectory_is_byte_identical(self):
        history = ("path", "commits", "fixes", "fix_rate", "age_days", "stale_days",
                   "authors", "top_share", "risk")
        labels = ("commits", "fix_rate", "age_days", "stale_days", "authors",
                  "top_share")

        def trajectory(payload):
            rows = sorted(payload["files"], key=lambda r: r["path"])
            return (json.dumps(payload["trajectory"], sort_keys=True),
                    json.dumps([{k: r[k] for k in history} for r in rows]),
                    json.dumps([{k: r["labels"][k] for k in labels} for r in rows]))

        off = self.run_json("hotspots", "--graph", "off")
        graph = self.run_json("hotspots")
        self.assertEqual(graph["structure"]["source"], "graph")
        self.assertEqual(trajectory(graph), trajectory(off))
        suspects_off = self.run_json("suspects", "shipgate/scripts/other.py",
                                     "--graph", "off")
        suspects = self.run_json("suspects", "shipgate/scripts/other.py")
        self.assertEqual(suspects["trajectory"], suspects_off["trajectory"])

    def test_a_language_without_a_regex_adapter_has_a_graph(self):
        ruby = self.make("ruby", files={"a.rb": "1\n", "b.rb": "require 'a'\n"})
        env = self.env(SHIM_EDGES=json.dumps([["b.rb", "a.rb"]]))
        off = self.signals_json("blast", "a.rb", "--repo", ruby.path, "--graph", "off",
                                env=env)
        self.assertEqual(off["reason"], "no-adapter")
        payload = self.signals_json("blast", "a.rb", "--repo", ruby.path, env=env)
        self.assertIs(payload["available"], True)
        self.assertEqual(payload["blast"]["files"], ["b.rb"])

    def test_a_failed_tests_call_is_a_note_not_an_exit(self):
        self.run_json("hotspots")  # build
        fake_daemon(self.repo.path / ".codegraph")
        env = self.env("kill")  # --version works; `affected` dies
        payload = self.run_json("blast", "shipgate/hooks/_common.py", env=env)
        self.assertEqual(payload["structure"]["source"], "graph")
        self.assertIsNone(payload["blast"]["tests"])
        self.assertEqual(payload["blast"]["tests_reason"], "graph-affected")
        self.assertEqual(payload["blast"]["files"], SC002_TESTS)
        table = self.signals("blast", "shipgate/hooks/_common.py", "--repo",
                             self.repo.path, env=env)
        self.assertEqual(table.stderr, "")
        self.assertIn("tests reached: unavailable (graph-affected)", table.stdout)


# ---------------------------------------------------------------------------
# T07 — fallback paths (SC-009)
# ---------------------------------------------------------------------------


class TestFallback(ShimSignalsCase):
    """Every graph failure gives the regex rows, one reason line and exit 0."""

    CASES = (
        ("kill", {}, "failed", "graph-init"),
        ("garbage", {}, "failed", "graph-status"),
        ("hang", {"SHIPGATE_CODEGRAPH_TIMEOUT": "1"}, "failed", "graph-timeout"),
        ("corrupt-db", {}, "failed", "graph-db"),
        ("schema-mismatch", {}, "failed", "graph-schema"),
    )

    def test_each_failure_falls_back_to_the_regex_rows(self):
        for mode, extra, state, reason in self.CASES:
            with self.subTest(mode=mode):
                # One fresh repository per check: a garbage status fails only the
                # run that builds; the next run finds the database and works.
                repo = self.make(mode)
                table_repo = self.make(mode + "-table")
                blast_repo = self.make(mode + "-blast")
                off_env = self.env("ok")
                off = self.signals_json("hotspots", "--repo", repo.path, "--graph",
                                        "off", env=off_env)
                off_table = self.signals("hotspots", "--repo", table_repo.path,
                                         "--graph", "off", env=off_env
                                         ).stdout.splitlines()
                env = self.env(mode, **extra)
                first = self.signals_json("hotspots", "--repo", repo.path, env=env)
                structure = first["structure"]
                self.assertEqual(structure["source"], "regex")
                self.assertEqual((structure["graph"]["state"],
                                  structure["graph"]["reason"]), (state, reason))
                self.assertEqual(first["files"], off["files"])
                self.assertEqual({k: v for k, v in structure.items()
                                  if k not in ("source", "graph")},
                                 {k: v for k, v in off["structure"].items()
                                  if k not in ("source", "graph")})
                table = self.signals("hotspots", "--repo", table_repo.path, env=env)
                self.assertEqual(table.stderr, "")
                self.assertEqual(table.stdout.splitlines(),
                                 [f"structure: regex ({reason})"] + off_table)
                blast = self.signals_json("blast", "a.py", "--repo", blast_repo.path,
                                          env=env)
                self.assertEqual(blast["blast"]["files"], ["b.py"])
                self.assertIsNone(blast["blast"]["tests"])


# ---------------------------------------------------------------------------
# T08 — the advisory, once (SC-003)
# ---------------------------------------------------------------------------


class TestAdvisoryOnce(ShimSignalsCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make()

    def payload(self, *args, env=None, repo=None):
        return self.signals_json("hotspots", "--repo", (repo or self.repo).path, *args,
                                 env=env or self.absent_env())

    def table(self, *args, env=None, repo=None):
        proc = self.signals("hotspots", "--repo", (repo or self.repo).path, *args,
                            env=env or self.absent_env())
        self.assertEqual(proc.stderr, "")
        return proc.stdout.splitlines()

    def test_the_first_absent_run_carries_the_advisory_and_the_second_does_not(self):
        cg = load_signals_module()._codegraph
        first = self.payload()
        self.assertEqual(first["advisory"], cg.ADVISORY)
        self.assertEqual(first["structure"]["graph"]["state"], "absent")
        self.assertNotIn("advisory", self.payload())
        self.assertEqual(self.calls(), [])  # nothing on PATH, nothing called

    def test_off_carries_none_and_calls_nothing(self):
        payload = self.payload("--graph", "off", env=self.env("ok"))
        self.assertNotIn("advisory", payload)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.common_dir(self.repo) / "shipgate").exists())

    def test_table_output_is_the_off_output_plus_one_line_once(self):
        off = self.table("--graph", "off")
        first = self.table()
        self.assertEqual(len(first), len(off) + 1)
        self.assertTrue(first[0].startswith("code graph: install codegraph"), first[0])
        self.assertEqual(first[1:], off)
        self.assertEqual(self.table(), off)

    def test_every_command_prints_it_once(self):
        lines = self.signals("blast", "a.py", "--repo", self.repo.path,
                             env=self.absent_env()).stdout.splitlines()
        self.assertTrue(lines[0].startswith("code graph: install codegraph"))
        again = self.signals("blast", "a.py", "--repo", self.repo.path,
                             env=self.absent_env()).stdout.splitlines()
        self.assertEqual(again, lines[1:])

    def test_too_large_is_shown_once_with_its_own_marker(self):
        env = self.env("ok", SHIPGATE_CODEGRAPH_MAX_FILES=1)
        first = self.payload(env=env)
        self.assertIn("codegraph init", first["advisory"])
        self.assertEqual(first["structure"]["graph"]["reason"], "graph-too-large")
        state = self.common_dir(self.repo) / "shipgate"
        self.assertTrue((state / "codegraph-too-large").is_file())
        self.assertFalse((state / "codegraph-advised").exists())
        second = self.payload(env=env)
        self.assertNotIn("advisory", second)
        self.assertEqual(second["structure"]["graph"]["reason"], "graph-too-large")
        # The absent advisory keeps its own marker.
        self.assertIn("advisory", self.payload())

    def test_a_read_only_state_dir_is_not_an_error(self):
        state = self.common_dir(self.repo) / "shipgate"
        state.mkdir()
        state.chmod(0o500)
        self.addCleanup(state.chmod, 0o700)
        if os.access(str(state), os.W_OK):
            self.skipTest("running as a user that ignores directory permissions")
        payload = self.payload()
        self.assertIn("advisory", payload)
        self.assertEqual(list(state.iterdir()), [])

    def test_a_second_clone_advises_again(self):
        self.assertIn("advisory", self.payload())
        clone = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(self.repo.path), str(clone)],
                       check=True, capture_output=True)
        self.assertIn("advisory", self.signals_json("hotspots", "--repo", clone,
                                                    env=self.absent_env()))
        self.assertNotIn("advisory", self.payload())


# ---------------------------------------------------------------------------
# T10 — the `graph` subcommand
# ---------------------------------------------------------------------------

JSON_ACTIONS = {"impact": "impact.json", "callers": "callers.json",
                "callees": "callees.json", "affected": "affected.json",
                "query": "query.json"}
TEXT_ACTIONS = {"node": ("shipgate/scripts/signals.py", "node-file.txt"),
                "explore": ("blast radius", "explore.txt")}


class TestGraphCommand(ShimSignalsCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make()
        self.graph_env = self.env("ok")
        self.signals("graph", "--repo", self.repo.path, "--json", "query", "x",
                     env=self.graph_env)  # build the index once
        self.log.unlink()

    def graph(self, *argv, env=None, rc=0):
        return self.signals("graph", "--repo", self.repo.path, *argv,
                            env=env or self.graph_env, rc=rc)

    def last_call(self):
        calls = [e["argv"] for e in self.calls()
                 if e["argv"][0] not in ("--version", "status", "sync")]
        self.assertEqual(len(calls), 1, calls)
        return calls[0]

    def test_json_actions_pass_argv_through_with_p_and_j(self):
        for action, fixture in JSON_ACTIONS.items():
            with self.subTest(action=action):
                self.log.unlink(missing_ok=True)
                proc = self.graph("--json", action, "resolve_db", "-d", "2")
                self.assertEqual(proc.stderr, "")
                self.assertEqual(self.last_call(), [action, "resolve_db", "-d", "2",
                                                    "-p", str(self.repo.path), "-j"])
                payload = json.loads(proc.stdout)
                self.assertEqual(set(payload), {"version", "available", "source",
                                                "command", "args", "graph", "result",
                                                "result_text", "not_found"})
                self.assertEqual((payload["result_text"], payload["not_found"]),
                                 (None, False))
                self.assertEqual((payload["version"], payload["available"],
                                  payload["source"], payload["command"],
                                  payload["args"]),
                                 (1, True, "graph", action, ["resolve_db", "-d", "2"]))
                self.assertEqual(payload["graph"]["state"], "present")
                self.assertEqual(payload["result"], json.loads(
                    (FIXTURES / fixture).read_text(encoding="utf-8")))
                table = self.graph(action, "resolve_db")
                self.assertEqual(json.loads(table.stdout), payload["result"])

    def test_text_actions_print_verbatim(self):
        for action, (arg, fixture) in TEXT_ACTIONS.items():
            with self.subTest(action=action):
                self.log.unlink(missing_ok=True)
                text = (FIXTURES / fixture).read_text(encoding="utf-8")
                table = self.graph(action, arg)
                self.assertEqual(table.stderr, "")
                self.assertEqual(table.stdout, text)
                self.assertEqual(self.last_call(), [action, arg, "-p",
                                                    str(self.repo.path)])
                payload = json.loads(self.graph("--json", action, arg).stdout)
                self.assertEqual(payload["result"], text)

    def test_unavailable_makes_no_codegraph_call(self):
        for args, env, reason in ((["--graph", "off"], self.graph_env, "graph-off"),
                                  ([], self.absent_env(), "graph-not-installed")):
            with self.subTest(reason=reason):
                self.log.unlink(missing_ok=True)
                payload = json.loads(self.graph(*args, "--json", "impact", "x",
                                                 env=env).stdout)
                self.assertEqual({k: payload[k] for k in ("version", "available",
                                                          "reason", "source")},
                                 {"version": 1, "available": False, "reason": reason,
                                  "source": "regex"})
                self.assertNotIn("result", payload)
                table = self.graph(*args, "impact", "x", env=env)
                self.assertEqual(table.stdout.splitlines()[0],
                                 f"graph unavailable: {reason}")
                self.assertEqual(self.calls(), [])

    def test_outside_git_is_unavailable(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        proc = self.signals("graph", "--repo", plain, "--json", "query", "x",
                            env=self.graph_env)
        self.assertEqual(json.loads(proc.stdout), {
            "version": 1, "available": False, "reason": "no-git", "source": "regex"})

    def test_a_failing_action_is_a_reason_not_an_exit(self):
        env = self.env("kill")
        fake_daemon(self.repo.path / ".codegraph")
        payload = json.loads(self.graph("--json", "callers", "x", env=env).stdout)
        self.assertEqual((payload["available"], payload["reason"]),
                         (False, "graph-callers"))

    def test_an_unknown_action_is_a_usage_error(self):
        self.graph("blame", "x", rc=USAGE)
        self.graph(rc=USAGE)

    def test_fr018_no_author_field_in_any_fixture_or_wrapper(self):
        outputs = [(FIXTURES / name).read_text(encoding="utf-8")
                   for name in os.listdir(FIXTURES)]
        for action in JSON_ACTIONS:
            outputs.append(self.graph("--json", action, "x").stdout)
        for action, (arg, _) in TEXT_ACTIONS.items():
            outputs.append(self.graph("--json", action, arg).stdout)
        outputs.append(self.graph("--json", "--graph", "off", "query", "x").stdout)
        for text in outputs:
            lowered = text.lower()
            self.assertNotIn('"author', lowered)
            self.assertNotIn("email", lowered)
            self.assertNotIn("fixture author", lowered)

    def test_the_parser_takes_the_common_flags_before_the_action(self):
        mod = load_signals_module()
        args = mod.build_parser().parse_args(
            ["graph", "--repo", ".", "--json", "impact", "x", "-f", "a.py"])
        self.assertEqual((args.action, args.args, args.json),
                         ("impact", ["x", "-f", "a.py"], True))


class TestUnindexedChildUnderAnIndexedRoot(ShimSignalsCase):
    """The real `status <child>` walks up to the umbrella root's index and answers
    for the root (slowly, and `initialized: true`). "Initialized" is therefore the
    child's own database file, never `status`."""

    def setUp(self):
        super().setUp()
        self.umbrella = FixtureRepo(self.tmp / "umbrella")
        self.umbrella.commit("ignore the child", ts(2020, 1, 1),
                             writes={".gitignore": "child/\n", "root.py": "R = 1\n"})
        self.child = self.make("umbrella/child")
        subprocess.run([str(self.shim), "init", "-y", str(self.umbrella.path)],
                       check=True, capture_output=True, env=self.env())
        self.assertTrue((self.umbrella.path / ".codegraph" / "codegraph.db").is_file())
        self.log.unlink()

    def test_the_shim_walks_up_like_the_real_status(self):
        proc = subprocess.run([str(self.shim), "status", "--json", str(self.child.path)],
                              capture_output=True, text=True, env=self.env())
        status = json.loads(proc.stdout)
        self.assertEqual((status["initialized"], status["projectPath"]),
                         (True, str(self.umbrella.path)))

    def test_the_child_gets_its_own_index(self):
        payload = self.signals_json("blast", "a.py", "--repo", self.child.path,
                                    env=self.env())
        graph = payload["structure"]["graph"]
        self.assertEqual((payload["structure"]["source"], graph["state"]),
                         ("graph", "present"), graph)
        self.assertEqual(graph["index_root"], ".")
        self.assertTrue((self.child.path / ".codegraph" / "codegraph.db").is_file())
        argvs = [e["argv"] for e in self.calls()]
        child, root = str(self.child.path), str(self.umbrella.path)
        first = next(i for i, a in enumerate(argvs) if a[0] != "--version")
        self.assertEqual(argvs[first], ["init", "-y", child], argvs)
        for argv in argvs:
            self.assertNotIn(root, argv)
            if argv[0] in ("status", "sync", "init"):
                self.assertEqual(argv[-1], child, argv)
            elif argv[0] != "--version":
                self.assertEqual(argv[argv.index("-p") + 1], child, argv)
        self.assertIn("affected", [a[0] for a in argvs])
        # The next run finds the child's database: no status, one sync of the child.
        self.log.unlink()
        self.signals_json("blast", "a.py", "--repo", self.child.path, env=self.env())
        self.assertEqual([e["argv"] for e in self.calls()],
                         [["--version"], ["sync", child],
                          ["affected", "--stdin", "-j", "-p", child]])
        self.assertEqual(self.calls()[-1]["stdin"], "a.py\n")

    def test_the_file_guard_runs_before_any_path_call(self):
        env = self.env(SHIPGATE_CODEGRAPH_MAX_FILES=1)
        payload = self.signals_json("hotspots", "--repo", self.child.path, env=env)
        graph = payload["structure"]["graph"]
        self.assertEqual((graph["state"], graph["reason"]), ("absent", "graph-too-large"))
        self.assertIn("codegraph init", payload["advisory"])
        self.assertEqual([e["argv"] for e in self.calls()], [["--version"]])
        self.assertFalse((self.child.path / ".codegraph").exists())


# ---------------------------------------------------------------------------
# Review round 1 — F1 to F9
# ---------------------------------------------------------------------------


class TestIndexTrust(GraphCase):
    """F2: a `.codegraph` the repository ships is not ours to build into or read."""

    def assert_untrusted(self, result):
        self.assertEqual((result.available, result.state, result.reason),
                         (False, "failed", "graph-index-untrusted"))
        self.assertIsNone(result.advisory)
        self.assertEqual(set(commands(self.calls())), {"--version"})

    def commit_gitignore_link(self):
        outside = self.tmp / "outside-gitignore"
        index = self.repo.path / ".codegraph"
        index.mkdir()
        os.symlink(str(outside), str(index / ".gitignore"))
        self.repo.git("add", ".codegraph/.gitignore")
        self.repo.git("commit", "-q", "-m", "ship a linked gitignore")
        return outside

    def test_r3_1_a_symlinked_gitignore_is_refused(self):
        outside = self.commit_gitignore_link()
        self.assert_untrusted(self.select())
        self.assertFalse(os.path.lexists(str(outside)))  # init never wrote through it

    def test_r3_1_a_gitignore_tracked_as_a_symlink_is_refused(self):
        self.commit_gitignore_link()
        link = self.repo.path / ".codegraph" / ".gitignore"
        link.unlink()
        link.write_text("*\n")  # a regular file on disk; git still records 120000
        self.assert_untrusted(self.select())

    def test_a_symlinked_index_dir_is_refused(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        os.symlink(str(outside), str(self.repo.path / ".codegraph"))
        self.assert_untrusted(self.select())
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_symlinked_database_is_refused(self):
        (self.repo.path / ".codegraph").mkdir()
        target = self.tmp / "other.db"
        target.write_bytes(b"")
        os.symlink(str(target), str(self.repo.path / ".codegraph" / "codegraph.db"))
        self.assert_untrusted(self.select())

    def test_a_committed_index_is_refused(self):
        self.repo.commit("ship an index", ts(2020, 2, 1),
                         writes={".codegraph/codegraph.db": "not ours\n"})
        self.assert_untrusted(self.select())

    def test_r2_1_a_committed_gitignore_alone_is_codegraphs_own_file(self):
        self.repo.commit("ship the index's gitignore", ts(2020, 2, 1), writes={
            ".codegraph/.gitignore": "# CodeGraph data files — local to each "
                                     "machine, not for committing.\n*\n!.gitignore\n"})
        result = self.select()
        self.assertTrue(result.available, result.reason)

    def case_insensitive_fs(self) -> bool:
        probe = self.tmp / "CaseProbe"
        probe.mkdir()
        return (self.tmp / "caseprobe").exists()

    def test_r2_2_a_committed_index_in_another_case_is_refused(self):
        if not self.case_insensitive_fs():
            self.skipTest("the file system is case-sensitive")
        self.repo.commit("ship an index", ts(2020, 2, 1),
                         writes={".CodeGraph/codegraph.db": "not ours\n"})
        self.assert_untrusted(self.select())

    def test_r2_2_an_index_dir_in_another_case_is_refused(self):
        if not self.case_insensitive_fs():
            self.skipTest("the file system is case-sensitive")
        (self.repo.path / ".CodeGraph").mkdir()  # untracked, but not codegraph's name
        (self.repo.path / ".CodeGraph" / "codegraph.db").write_text("x")
        self.assert_untrusted(self.select())

    def test_root_mode_checks_the_umbrella_index_too(self):
        umbrella = FixtureRepo(self.tmp / "umbrella")
        umbrella.commit("ship an index", ts(2020, 1, 1), writes={
            ".gitignore": "child/\n", ".codegraph/codegraph.db": "not ours\n"})
        child = self.make_repo(self.tmp / "umbrella" / "child")
        self.assert_untrusted(self.select(child, "root"))


class TestGitEnv(GraphCase):
    """F8: codegraph never inherits the caller's GIT_DIR or GIT_WORK_TREE."""

    def test_git_dir_and_work_tree_are_dropped(self):
        os.environ["GIT_DIR"] = str(self.tmp / "nowhere" / ".git")
        os.environ["GIT_WORK_TREE"] = str(self.tmp / "nowhere")
        self.assertTrue(self.select().available)
        self.select()
        self.assertTrue(self.calls())
        for entry in self.calls():
            self.assertEqual((entry["GIT_DIR"], entry["GIT_WORK_TREE"]), (None, None),
                             entry["argv"])
        self.assertEqual(os.environ["GIT_DIR"], str(self.tmp / "nowhere" / ".git"))


class TestReviewRound1(ShimSignalsCase):
    def test_f1_each_child_of_an_umbrella_gets_its_own_too_large_advisory(self):
        umbrella = FixtureRepo(self.tmp / "umbrella")
        umbrella.commit("ignore the children", ts(2020, 1, 1),
                        writes={".gitignore": "c1/\nc2/\n"})
        env = self.env(SHIPGATE_CODEGRAPH_MAX_FILES=1)
        for name in ("c1", "c2"):
            with self.subTest(child=name):
                child = self.make("umbrella/" + name)
                first = self.signals_json("hotspots", "--repo", child.path, env=env)
                self.assertIn("codegraph init", first.get("advisory", ""))
                second = self.signals_json("hotspots", "--repo", child.path, env=env)
                self.assertNotIn("advisory", second)
                self.assertTrue((self.common_dir(child) / "shipgate" /
                                 "codegraph-too-large").is_file())
        self.assertFalse((self.common_dir(umbrella) / "shipgate" /
                          "codegraph-too-large").exists())

    def test_f3_a_codegraph_inside_the_repo_umbrella_or_cwd_is_not_used(self):
        umbrella = FixtureRepo(self.tmp / "umbrella")
        umbrella.commit("ignore the child", ts(2020, 1, 1),
                        writes={".gitignore": "child/\n"})
        child = self.make("umbrella/child")
        elsewhere = self.tmp / "work"
        elsewhere.mkdir()
        # (where the binary sits, the PATH entry that finds it, the working dir).
        # An empty, `.` or relative entry is the working directory: refused.
        for where, entry, cwd in ((child.path, str(child.path), None),
                                  (umbrella.path, str(umbrella.path), None),
                                  (elsewhere, ".", elsewhere),
                                  (elsewhere, "", elsewhere),
                                  (elsewhere, "work", self.tmp)):
            with self.subTest(where=where.name, entry=entry):
                self.log.unlink(missing_ok=True)
                planted = make_codegraph_shim(where, "ok")
                if where == umbrella.path:  # R3-2: refused because it is tracked
                    umbrella.git("add", "-f", "codegraph")
                    umbrella.git("commit", "-q", "-m", "ship a codegraph")
                env = dict(hermetic_env(), SHIM_LOG=str(self.log))
                env["PATH"] = entry + os.pathsep + env["PATH"]
                payload = self.signals_json("hotspots", "--repo", child.path,
                                            cwd=cwd, env=env)
                self.assertEqual(payload["structure"]["graph"]["reason"],
                                 "graph-not-installed")
                self.assertEqual(self.calls(), [])
                planted.unlink()

    def home_umbrella(self):
        """A dotfiles work tree at a fake HOME, holding a child repository and an
        installed codegraph at `.local/bin/codegraph` (untracked)."""
        home = FixtureRepo(self.tmp / "home")
        home.commit("dotfiles", ts(2020, 1, 1),
                    writes={".gitignore": "work/\n", ".zshrc": "# rc\n"})
        child = self.make("home/work/child")
        bin_dir = home.path / ".local" / "bin"
        make_codegraph_shim(bin_dir, "ok")
        env = dict(hermetic_env(), SHIM_LOG=str(self.log))
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        return home, child, env

    def test_r3_2_an_untracked_install_in_a_home_umbrella_is_used(self):
        home, child, env = self.home_umbrella()
        payload = self.signals_json("hotspots", "--repo", child.path, env=env)
        self.assertEqual(payload["structure"]["source"], "graph",
                         payload["structure"]["graph"])

    def test_r3_2_a_codegraph_the_umbrella_tracks_is_refused(self):
        home, child, env = self.home_umbrella()
        home.git("add", "-f", ".local/bin/codegraph")
        home.git("commit", "-q", "-m", "track a codegraph")
        payload = self.signals_json("hotspots", "--repo", child.path, env=env)
        self.assertEqual(payload["structure"]["graph"]["reason"], "graph-not-installed")
        self.assertEqual(self.calls(), [])

    def test_r3_3_a_refused_entry_does_not_hide_a_later_install(self):
        repo = self.make()
        planted = repo.path / "bin" / "codegraph"
        planted.parent.mkdir()
        ran = self.tmp / "planted-ran"
        planted.write_text(f"#!/bin/sh\ntouch {ran}\nexit 1\n")
        planted.chmod(0o755)
        installed = self.tmp / "inst"
        make_codegraph_shim(installed, "ok")
        env = dict(hermetic_env(), SHIM_LOG=str(self.log))
        env["PATH"] = os.pathsep.join([str(planted.parent), str(installed),
                                       env["PATH"]])
        payload = self.signals_json("blast", "a.py", "--repo", repo.path, env=env)
        self.assertEqual(payload["structure"]["source"], "graph",
                         payload["structure"]["graph"])
        self.assertIsNotNone(payload["blast"]["tests"])  # `affected` ran too
        self.assertFalse(ran.exists())

    def test_r3_5_windows_needs_an_extension(self):
        cg = load_signals_module()._codegraph
        entry = self.tmp / "winbin"
        make_codegraph_shim(entry, "ok")  # `codegraph`, no extension
        with mock.patch.dict(os.environ, {"PATH": str(entry), "PATHEXT": ".EXE;.CMD"}), \
                mock.patch.object(cg.os, "name", "nt"):
            self.assertIsNone(cg._which())
            exe = entry / "codegraph.EXE"
            exe.write_text("")
            exe.chmod(0o755)
            self.assertEqual(cg._which(), (str(entry), str(exe)))

    def test_r2_3_an_installed_codegraph_is_used_from_home_and_from_root(self):
        # ~/.local/bin/codegraph -> ~/.codegraph/versions/v1/bin/codegraph: the
        # symlink target sits under the working directory, the PATH entry does not
        # sit in the repository. Accepted.
        home = self.tmp / "home"
        target = home / ".codegraph" / "versions" / "v1" / "bin"
        make_codegraph_shim(target, "ok")
        link_dir = home / ".local" / "bin"
        link_dir.mkdir(parents=True)
        os.symlink(str(target / "codegraph"), str(link_dir / "codegraph"))
        repo = self.make()
        env = dict(hermetic_env(), SHIM_LOG=str(self.log))
        env["PATH"] = str(link_dir) + os.pathsep + env["PATH"]
        for cwd in (home, Path("/")):
            with self.subTest(cwd=str(cwd)):
                payload = self.signals_json("hotspots", "--repo", repo.path, cwd=cwd,
                                            env=env)
                self.assertEqual(payload["structure"]["source"], "graph",
                                 payload["structure"]["graph"])

    def test_r2_6_text_actions_report_not_found_too(self):
        repo = self.make()
        env = self.env("ok")
        for action, text in (("node", 'Symbol "no_such_x" not found in the codebase'),
                             ("explore", 'No relevant code found for "no_such_x"')):
            with self.subTest(action=action):
                payload = json.loads(self.signals(
                    "graph", "--repo", repo.path, "--json", action, "no_such_x",
                    env=env).stdout)
                self.assertTrue(payload["result"].startswith(text), payload["result"])
                self.assertEqual((payload["available"], payload["result_text"],
                                  payload["not_found"]), (True, None, True))
        found = json.loads(self.signals("graph", "--repo", repo.path, "--json", "node",
                                        "resolve_db", env=env).stdout)
        self.assertIs(found["not_found"], False)

    def test_f5_an_unknown_symbol_is_an_answer_not_unavailable(self):
        repo = self.make()
        env = self.env("ok")
        proc = self.signals("graph", "--repo", repo.path, "--json", "callers",
                            "no_such_symbol", env=env)
        payload = json.loads(proc.stdout)
        self.assertEqual((payload["available"], payload["source"], payload["result"],
                          payload["not_found"]), (True, "graph", None, True))
        self.assertEqual(payload["result_text"], '\u2139 Symbol "no_such_symbol" not found\n')
        table = self.signals("graph", "--repo", repo.path, "impact", "no_such_symbol",
                             env=env)
        self.assertEqual(table.stdout, '\u2139 Symbol "no_such_symbol" not found\n')

    def test_f6_a_graph_without_the_wanted_files_falls_back_to_regex(self):
        repo = self.make()
        env = self.env("ok")
        self.signals_json("hotspots", "--repo", repo.path, env=env)  # index a.py, b.py
        repo.commit("add ts", ts(2020, 3, 1), writes={
            "x/c.ts": "import { d } from './d';\n", "x/d.ts": "export const d = 1;\n"})
        payload = self.signals_json("hotspots", "--repo", repo.path, "--exclude", "*.py",
                                    env=env)
        structure = payload["structure"]
        self.assertEqual((structure["source"], structure["graph"]["state"],
                          structure["graph"]["reason"]),
                         ("regex", "failed", "graph-empty"))
        rows = {r["path"]: r for r in payload["files"]}
        self.assertEqual(rows["x/d.ts"]["fan_in"], 1)

    def test_f7_seeds_go_to_affected_on_stdin(self):
        repo = self.make(files={"./-d.py": "X = 1\n", "b.py": "Y = 2\n"})
        env = self.env("ok")
        payload = self.signals_json("blast", "./-d.py", "b.py", "--repo", repo.path,
                                    env=env)
        self.assertEqual(payload["structure"]["source"], "graph")
        affected = [e for e in self.calls() if e["argv"][0] == "affected"]
        self.assertEqual([e["argv"] for e in affected],
                         [["affected", "--stdin", "-j", "-p", str(repo.path)]])
        self.assertEqual(affected[0]["stdin"], "-d.py\nb.py\n")


# ---------------------------------------------------------------------------
# Live — the real codegraph on this repository (opt-in)
# ---------------------------------------------------------------------------


@unittest.skipUnless(os.environ.get("SHIPGATE_LIVE_CODEGRAPH") == "1"
                     and shutil.which("codegraph"),
                     "set SHIPGATE_LIVE_CODEGRAPH=1 with codegraph on PATH")
class TestLiveCodegraph(SignalsCase):
    """SC-002 against the real binary: the shim mirrors its argv contract, and this
    catches what the shim cannot. It builds or syncs `.codegraph/` in this repo."""

    def test_sc002_blast_on_the_hooks_shared_module(self):
        root = TESTS_DIR.parent.parent
        proc = test_signals.run_signals(
            ["blast", "shipgate/hooks/_common.py", "--json"], cwd=root,
            env=dict(os.environ))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["structure"]["source"], "graph",
                         payload["structure"]["graph"])
        self.assertGreaterEqual(len(payload["blast"]["tests"]), 2, payload["blast"])
        self.assertGreaterEqual(len(payload["blast"]["files"]), 2, payload["blast"])


if __name__ == "__main__":
    unittest.main()
