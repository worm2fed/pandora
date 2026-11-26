#!/usr/bin/env python3
"""Tests of the run log as the journal reads and prunes it (#27, ADR 0032 and ADR 0033):
``_journal/runs.py``.

Every log is written under a temporary ``HOME`` (ADR 0032, amended by #81), and an
in-process call reads it under ``mock.patch.dict(os.environ)``. ``CLAUDE_CONFIG_DIR`` names
another temporary directory, as a shell profile may set it in the Bash shell, so every test
also shows that the journal does not read it. A ``journal.py`` subprocess gets the same
two directories. The module checks at its end that no old file of the real runs root of the
environment went away.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import sqlite3
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from test_journal import load_journal_module, OK, run_journal, SESSION_ENV

J = None
_REAL = {}
KEEP_DAYS = 7


def _ambient_runs_root() -> str:
    """The real runs root of the environment the suite runs in."""
    return os.path.join(os.environ.get("HOME", ""), ".claude", "shipgate", "runs")


def _old_files(root: str):
    """The names of the files in ROOT older than the keep limit. The session's own hooks
    may append to the real root while the suite runs, so only a deletion is checked."""
    cutoff = time.time() - KEEP_DAYS * 86400
    try:
        names = os.listdir(root)
    except OSError:
        return set()
    old = set()
    for name in names:
        try:
            if os.lstat(os.path.join(root, name)).st_mtime < cutoff:
                old.add(name)
        except OSError:
            pass
    return old


def setUpModule():
    global J
    J = load_journal_module()
    _REAL["root"] = _ambient_runs_root()
    _REAL["old"] = _old_files(_REAL["root"])


def tearDownModule():
    gone = _REAL["old"] - set(os.listdir(_REAL["root"]) if os.path.isdir(_REAL["root"])
                              else ())
    if gone:
        raise AssertionError(f"the tests deleted {sorted(gone)} from the real runs root "
                             f"{_REAL['root']}")


def fingerprint(command: str) -> str:
    """ADR 0032's key of a command with no leading `cd <word> && ` step, computed here
    without the plugin's code."""
    data = command.strip().encode("utf-8", "surrogateescape")
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def start(tool_use: str, command: str) -> dict:
    return {"i": tool_use, "h": fingerprint(command)}


def end(tool_use: str, code: int) -> dict:
    return {"i": tool_use, "x": code}


S = "session-1"
TESTS = "python3 -m unittest discover -s tests"
LINT = "ruff check ."


class RunsCase(unittest.TestCase):
    """A home of its own, and a Claude config directory elsewhere, set in this process's
    environment: the run log lives under the home whatever CLAUDE_CONFIG_DIR says (#81)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.config = self.home / ".claude"
        self.shell_config = self.tmp / "shell-config"
        self.runs = self.config / "shipgate" / "runs"
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home),
                                               "CLAUDE_CONFIG_DIR": str(self.shell_config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def log(self, rows, session=S, suffix=".jsonl", directory=None):
        """Append ROWS to the log file of SESSION: a dict as a JSON line, bytes as they
        are, a str as a line."""
        directory = directory or self.runs
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (session + suffix)
        with open(path, "ab") as handle:
            for row in rows:
                if isinstance(row, dict):
                    handle.write(json.dumps(row).encode("utf-8") + b"\n")
                elif isinstance(row, bytes):
                    handle.write(row)
                else:
                    handle.write(row.encode("utf-8") + b"\n")
        return path

    def run_of(self, tool_use, command, code, **kwargs):
        return self.log([start(tool_use, command), end(tool_use, code)], **kwargs)

    def observe(self, *pairs, session=S):
        return J.observe([{"cmd": cmd, "exit": code} for cmd, code in pairs], session)

    def states(self, *pairs, session=S):
        return [run.state for run in self.observe(*pairs, session=session).commands]


class TestReadSessionRuns(RunsCase):
    """`read_session_runs`: the start rows as a map, the end rows in file order, the
    older file first; None when there is no log to read; never an exception."""

    def test_the_rows_in_file_order(self):
        self.log([start("a", TESTS), end("a", 1)], suffix=".jsonl.1")
        self.log([start("b", TESTS), end("b", 0), end("c", 2), start("d", LINT)])
        runs = J.read_session_runs(S)
        self.assertEqual(runs.starts, {"a": fingerprint(TESTS), "b": fingerprint(TESTS),
                                       "d": fingerprint(LINT)})
        self.assertEqual(runs.ends, [("a", 1), ("b", 0), ("c", 2)])

    def test_one_file_alone_is_read(self):
        self.run_of("a", TESTS, 0, suffix=".jsonl.1")
        self.assertEqual(J.read_session_runs(S).ends, [("a", 0)])
        self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_an_empty_file_is_a_log_with_no_rows(self):
        self.log([])
        runs = J.read_session_runs(S)
        self.assertEqual((runs.starts, runs.ends), ({}, []))

    def test_a_line_that_is_no_row_is_skipped(self):
        self.log([
            "not json",
            "[1, 2]",
            '"a string"',
            "",
            {"i": "", "x": 0},
            {"i": 5, "x": 0},
            {"x": 0},
            {"i": "q", "x": True},
            {"i": "q", "x": "0"},
            {"i": "q", "x": 1.0},
            {"i": "q", "x": None},
            {"i": "q", "h": 7},
            {"i": "q", "h": fingerprint(TESTS), "x": 0},
            {"i": "q", "x": 0, "t": 1},
            {"i": "q", "h": fingerprint(TESTS), "cwd": "/x"},
            b'{"i": "q", "x": 0\n',
            b"\xff\xfe{}\n",
            b"[" * 100000 + b"\n",
            "9" * 5000,
            start("a", TESTS),
            end("a", 0),
        ])
        runs = J.read_session_runs(S)
        self.assertEqual(runs.starts, {"a": fingerprint(TESTS)})
        self.assertEqual(runs.ends, [("a", 0)])
        self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_no_plain_session_id_is_no_log(self):
        """The session id names a file only when it is a plain token: a log planted
        where `../x` would point is never read."""
        self.run_of("a", TESTS, 0, session="x", directory=self.config / "shipgate")
        self.run_of("a", TESTS, 0)
        for session in (None, "", "../x", "a/b", "a.b", "x" * 129, "sé", "s\n",
                        5, b"session-1"):
            with self.subTest(session=session):
                self.assertIsNone(J.read_session_runs(session))
        self.assertIsNotNone(J.read_session_runs(S))
        self.run_of("a", TESTS, 0, session="x" * 128)
        self.assertIsNotNone(J.read_session_runs("x" * 128))

    def test_no_root_and_no_directory_is_no_log(self):
        self.assertIsNone(J.read_session_runs(S))
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CONFIG_DIR", "HOME")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(J.read_session_runs(S))
        with mock.patch.dict(os.environ, {"HOME": "relative/home"}):
            self.assertIsNone(J.read_session_runs(S))

    def test_a_link_in_place_of_the_file_is_no_log(self):
        outside = self.run_of("a", TESTS, 0, directory=self.tmp / "outside")
        self.runs.mkdir(parents=True)
        os.symlink(outside, self.runs / (S + ".jsonl"))
        os.symlink(outside, self.runs / (S + ".jsonl.1"))
        self.assertIsNone(J.read_session_runs(S))
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])

    def test_a_link_in_place_of_the_directory_is_no_log(self):
        outside = self.tmp / "outside"
        self.run_of("a", TESTS, 0, directory=outside)
        self.runs.parent.mkdir(parents=True)
        os.symlink(outside, self.runs)
        self.assertIsNone(J.read_session_runs(S))
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])

    def test_a_linked_claude_directory_is_followed(self):
        """`~/.claude` may be a link (a dotfiles checkout); only the `runs` directory and
        the files are opened without following one."""
        self.run_of("a", TESTS, 0)
        linked = self.tmp / "linked-home"
        linked.mkdir()
        os.symlink(self.config, linked / ".claude")
        with mock.patch.dict(os.environ, {"HOME": str(linked)}):
            self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_a_fifo_or_a_directory_in_place_of_the_file_is_no_log(self):
        """A FIFO must not hang the read: the file is opened non-blocking and read only
        when `fstat` says it is a regular file."""
        self.runs.mkdir(parents=True)
        os.mkfifo(self.runs / (S + ".jsonl"))
        (self.runs / (S + ".jsonl.1")).mkdir()

        hung = []

        def timeout(signum, frame):
            hung.append(True)
            raise InterruptedError("the read hung on a FIFO")

        previous = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(5)
        try:
            self.assertIsNone(J.read_session_runs(S))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        self.assertEqual(hung, [])

    def test_a_log_over_the_read_cap_is_read_to_the_cap(self):
        """RUNS_READ_BYTES (1 MB) counts both files together: a run past the cap is
        not seen, a run before it is."""
        self.assertEqual(J.RUNS_READ_BYTES, 1024 * 1024)
        pad = (json.dumps(end("pad", 0)) + "\n").encode("utf-8")
        half = pad * (600 * 1024 // len(pad))
        self.log([half], suffix=".jsonl.1")
        self.log([start("a", TESTS), end("a", 0), half, start("b", LINT), end("b", 0)])
        self.assertGreater(sum(p.stat().st_size for p in self.runs.iterdir()),
                           1024 * 1024)
        runs = J.read_session_runs(S)
        self.assertEqual(runs.starts, {"a": fingerprint(TESTS)})
        self.assertLessEqual(len(runs.ends) * len(pad), 1024 * 1024)
        self.assertEqual(self.states((TESTS, 0), (LINT, 0)), ["matched", "unmatched"])

    def test_it_never_raises(self):
        self.run_of("a", TESTS, 0)
        for target, error in (("open", RuntimeError("boom")),
                              ("read", OSError(5, "Input/output error")),
                              ("fstat", RuntimeError("boom"))):
            with self.subTest(target=target):
                with mock.patch.object(J._package.runs.os, target, side_effect=error):
                    self.assertIsNone(J.read_session_runs(S))
                    self.assertEqual(self.states((TESTS, 0)), ["unmatched"])


class TestObserve(RunsCase):
    """`observe`: per command, the newest run of its hash in file order decides."""

    def test_matched(self):
        self.run_of("a", TESTS, 0)
        observation = self.observe((TESTS, 0))
        self.assertEqual(observation.commands[0].state, "matched")
        self.assertEqual(observation.commands[0].newest_exit, 0)
        self.assertTrue(observation.observed)
        self.assertFalse(observation.contradicted)

    def test_a_failing_run_cited_as_failing_is_matched(self):
        self.run_of("a", TESTS, 3)
        self.assertEqual(self.states((TESTS, 3)), ["matched"])

    def test_no_run_is_unmatched(self):
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])
        self.run_of("a", LINT, 0)
        observation = self.observe((TESTS, 0))
        self.assertEqual(observation.commands[0].state, "unmatched")
        self.assertIsNone(observation.commands[0].newest_exit)
        self.assertFalse(observation.observed)
        self.assertFalse(observation.contradicted)

    def test_the_newest_run_exited_otherwise_is_contradicted(self):
        self.run_of("a", TESTS, 0)
        self.run_of("b", TESTS, 1)
        observation = self.observe((TESTS, 0))
        self.assertEqual(observation.commands[0].state, "contradicted")
        self.assertEqual(observation.commands[0].newest_exit, 1)
        self.assertFalse(observation.observed)
        self.assertTrue(observation.contradicted)

    def test_an_older_failing_run_then_a_newer_passing_one_is_matched(self):
        self.run_of("a", TESTS, 1)
        self.run_of("b", TESTS, 0)
        self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_the_newest_run_is_the_last_end_row_in_file_order(self):
        """Two runs in parallel: the one that ended last decides, whatever order they
        started in, and the current file comes after the older one."""
        self.log([start("a", TESTS), start("b", TESTS), end("b", 1), end("a", 0)])
        self.assertEqual(self.states((TESTS, 0)), ["matched"])
        self.log([start("c", TESTS), end("c", 0)], suffix=".jsonl.1")
        self.log([start("d", TESTS), end("d", 2)])
        self.assertEqual(self.states((TESTS, 0)), ["contradicted"])

    def test_rows_split_across_the_two_files_are_joined(self):
        self.log([start("a", TESTS)], suffix=".jsonl.1")
        self.log([end("a", 0)])
        self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_the_typed_command_matches_and_the_rewritten_text_does_not(self):
        """SC-003: the start row hashes the command as the model typed it; a rewrite
        hook changed what ran, and no row holds the rewritten text."""
        typed = "pytest -q tests/unit"
        rewritten = "proxy pytest -q tests/unit"
        self.log([start("a", typed), end("a", 0)])
        self.assertEqual(self.states((typed, 0)), ["matched"])
        self.assertEqual(self.states((rewritten, 0)), ["unmatched"])

    def test_the_command_is_cited_by_its_exact_text(self):
        """Exact text, except each leading `cd <word> && ` (#81): Claude Code removes one
        `cd <cwd> && ` before the hook sees the command."""
        self.run_of("a", TESTS, 0)
        self.assertEqual(self.states(("  " + TESTS + "\n", 0)), ["matched"])
        self.assertEqual(self.states((TESTS.replace(" -s", "  -s"), 0)), ["unmatched"])
        self.assertEqual(self.states(("cd x && " + TESTS, 0)), ["matched"])
        self.assertEqual(self.states(("cd x && cd y && " + TESTS, 0)), ["matched"])
        self.assertEqual(self.states(("cd x; " + TESTS, 0)), ["unmatched"])
        self.assertEqual(self.states(("cd 'x y' && " + TESTS, 0)), ["unmatched"])

    def test_the_observation_names_why_nothing_matched(self):
        """#81: the notice names the cause, so the observation carries it and the root."""
        root = str(self.runs)
        self.assertEqual(J.observe([{"cmd": TESTS, "exit": 0}], S)[1:],
                         (J._package.runs.NO_LOG, root))
        for session in (None, "", "a/b"):
            with self.subTest(session=session):
                self.assertEqual(J.observe([{"cmd": TESTS, "exit": 0}], session)[1:],
                                 (J._package.runs.NO_SESSION, root))
        self.run_of("a", LINT, 0)
        self.assertEqual(J.observe([{"cmd": TESTS, "exit": 0}], S)[1:], (None, root))
        with mock.patch.dict(os.environ, {"HOME": "relative/home"}):
            self.assertEqual(J.observe([{"cmd": TESTS, "exit": 0}], S)[1:],
                             (J._package.runs.NO_LOG, None))

    def test_no_session_id_is_unmatched(self):
        self.run_of("a", TESTS, 0)
        for session in (None, ""):
            with self.subTest(session=session):
                self.assertEqual(self.states((TESTS, 0), session=session), ["unmatched"])

    def test_another_sessions_run_is_unmatched(self):
        self.run_of("a", TESTS, 0, session="session-2")
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])
        self.assertEqual(self.states((TESTS, 0), session="session-2"), ["matched"])

    def test_a_start_row_with_no_end_row_matches_nothing(self):
        """A background launch, an interrupt or an interpreted exit leaves a start row
        alone: its exit is unknown, and the newest run with a known exit decides."""
        self.log([start("a", TESTS)])
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])
        self.assertEqual(self.states((TESTS, 1)), ["unmatched"])
        self.run_of("b", TESTS, 0)
        self.log([start("c", TESTS)])
        self.assertEqual(self.states((TESTS, 0)), ["matched"])

    def test_an_end_row_with_no_start_row_matches_nothing(self):
        self.log([end("a", 0)])
        self.assertEqual(self.states((TESTS, 0)), ["unmatched"])

    def test_observed_needs_one_command_and_every_command_matched(self):
        self.run_of("a", TESTS, 0)
        self.run_of("b", LINT, 1)
        both = self.observe((TESTS, 0), (LINT, 1))
        self.assertEqual([run.state for run in both.commands], ["matched", "matched"])
        self.assertTrue(both.observed)
        one = self.observe((TESTS, 0), ("make docs", 0))
        self.assertEqual([run.state for run in one.commands], ["matched", "unmatched"])
        self.assertFalse(one.observed)
        self.assertFalse(one.contradicted)
        mixed = self.observe((TESTS, 0), (LINT, 0))
        self.assertEqual([run.state for run in mixed.commands],
                         ["matched", "contradicted"])
        self.assertFalse(mixed.observed)
        self.assertTrue(mixed.contradicted)
        empty = J.observe([], S)
        self.assertEqual(empty.commands, ())
        self.assertFalse(empty.observed)
        self.assertFalse(empty.contradicted)

    def test_each_command_keeps_its_text_and_exit(self):
        self.run_of("a", TESTS, 0)
        run = self.observe((TESTS, 0)).commands[0]
        self.assertEqual((run.cmd, run.exit), (TESTS, 0))

    def test_a_command_that_cannot_be_hashed_is_unmatched(self):
        """A lone surrogate that `surrogateescape` cannot encode (a JSON `\\ud800` in
        `--data` carries one), and a Python with no BLAKE2: that command is unmatched,
        the others are still observed, and nothing raises."""
        self.run_of("a", TESTS, 0)
        self.assertEqual(self.states(("echo \ud800", 0), (TESTS, 0)),
                         ["unmatched", "matched"])
        common = J._package.plugin._hooks_common
        with mock.patch.object(common, "run_fingerprint",
                               side_effect=ImportError("blake2")):
            self.assertEqual(self.states((TESTS, 0)), ["unmatched"])

    def test_an_item_of_another_form_is_unmatched(self):
        """`observe` never raises on what the shape check would refuse: a bool exit
        never matches exit 1, and an item that is no object matches nothing."""
        self.run_of("a", TESTS, 1)
        observation = J.observe([{"cmd": TESTS, "exit": True}, {"cmd": 5, "exit": 1},
                                 {"cmd": TESTS}, "pytest", None], S)
        self.assertEqual([run.state for run in observation.commands], ["unmatched"] * 5)
        for commands in (None, 5, object()):
            with self.subTest(commands=commands):
                self.assertEqual(J.observe(commands, S).commands, ())


# ---------------------------------------------------------------------------
# T023: the prune (SC-005)
# ---------------------------------------------------------------------------

OLD = time.time() - 8 * 86400
NEARLY = time.time() - 6 * 86400


class PruneCase(RunsCase):
    def plant(self, name, size=10, mtime=None, directory=None):
        directory = directory or self.runs
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(b"x" * size)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def link(self, name, target, mtime=None):
        self.runs.mkdir(parents=True, exist_ok=True)
        path = self.runs / name
        os.symlink(target, path)
        if mtime is not None:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        return path

    def plant_store(self):
        """Two old logs of one session, a fresh log, a log 6 days old, and an old
        entry of each kind the prune refuses: foreign names, a directory, a link."""
        self.outside = self.plant("target.jsonl", mtime=OLD, directory=self.tmp / "out")
        self.plant("s1.jsonl", mtime=OLD)
        self.plant("s1.jsonl.1", mtime=OLD)
        self.plant("s2.jsonl")
        self.plant("s3.jsonl.1", mtime=NEARLY)
        kept = ["notes.txt", "a.b.jsonl", "s4.jsonl.2", ".jsonl", "s5.jsonl.1.tmp",
                ".DS_Store", "x" * 129 + ".jsonl", "s\u00e9.jsonl"]
        for name in kept:
            self.plant(name, mtime=OLD)
        (self.runs / "d.jsonl").mkdir()
        os.utime(self.runs / "d.jsonl", (OLD, OLD))
        self.link("s6.jsonl", self.outside, mtime=OLD)
        self.link("s7.jsonl.1", self.tmp / "out", mtime=OLD)
        return sorted(kept + ["d.jsonl", "s2.jsonl", "s3.jsonl.1", "s6.jsonl",
                              "s7.jsonl.1"])


class TestPruneRuns(PruneCase):
    """`prune_runs` and `prune_old_runs`: only an old regular `<token>.jsonl` or
    `<token>.jsonl.1` goes, one at a time, no link followed, and nothing raises."""

    def test_an_old_log_goes_and_the_rest_stays(self):
        kept = self.plant_store()
        report = J.prune_runs(str(self.runs))
        self.assertEqual(report, {"removed": [str(self.runs / "s1.jsonl"),
                                              str(self.runs / "s1.jsonl.1")],
                                  "warnings": []})
        self.assertEqual(sorted(os.listdir(self.runs)), kept)
        self.assertTrue(self.outside.is_file())
        self.assertEqual(sorted(os.listdir(self.tmp / "out")), ["target.jsonl"])

    def test_the_run_log_names(self):
        regular = stat.S_IFREG | 0o600
        for name, mode, expected in (
                ("s1.jsonl", regular, True), ("s1.jsonl.1", regular, True),
                ("A-z_0.jsonl", regular, True), ("x" * 128 + ".jsonl.1", regular, True),
                ("x" * 129 + ".jsonl", regular, False), (".jsonl", regular, False),
                (".jsonl.1", regular, False), ("a.b.jsonl", regular, False),
                ("s.jsonl.2", regular, False), ("s.json", regular, False),
                ("s.jsonl", stat.S_IFLNK | 0o777, False),
                ("s.jsonl", stat.S_IFDIR | 0o700, False),
                ("s.jsonl", stat.S_IFIFO | 0o600, False)):
            with self.subTest(name=name[:20], mode=oct(mode)):
                self.assertIs(J.is_run_log(name, mode), expected)

    def test_the_prune_of_an_append_prints_nothing_when_all_goes_well(self):
        self.plant_store()
        err = io.StringIO()
        with redirect_stderr(err):
            J.prune_old_runs()
        self.assertEqual(err.getvalue(), "")
        self.assertFalse((self.runs / "s1.jsonl").exists())

    def test_no_runs_directory_costs_one_lstat(self):
        with mock.patch.object(J._package.runs.os, "lstat", wraps=os.lstat) as lstat, \
                mock.patch.object(J._package.runs.os, "open") as opened, \
                mock.patch.object(J._package.runs.os, "scandir") as listed:
            J.prune_old_runs()
        self.assertEqual(lstat.call_count, 1)
        self.assertEqual(lstat.call_args[0][0], str(self.runs))
        opened.assert_not_called()
        listed.assert_not_called()

    def test_no_root_is_nothing_and_no_error(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CONFIG_DIR", "HOME")}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stderr(err), \
                mock.patch.object(J._package.runs.os, "lstat") as lstat:
            J.prune_old_runs()
        lstat.assert_not_called()
        self.assertEqual(err.getvalue(), "")

    def test_a_link_in_place_of_the_directory_is_left_alone(self):
        outside = self.tmp / "out"
        old = self.plant("s1.jsonl", mtime=OLD, directory=outside)
        self.runs.parent.mkdir(parents=True)
        os.symlink(outside, self.runs)
        err = io.StringIO()
        with redirect_stderr(err):
            J.prune_old_runs()
        self.assertEqual(err.getvalue(), "")
        self.assertTrue(old.is_file())
        report = J.prune_runs(str(self.runs))
        self.assertEqual(report["removed"], [])
        self.assertEqual(len(report["warnings"]), 1)
        self.assertTrue(report["warnings"][0].startswith(f"cannot open {self.runs}: "))
        self.assertTrue(old.is_file())

    def test_a_failed_delete_is_a_warning_and_the_prune_goes_on(self):
        self.plant("s1.jsonl", mtime=OLD)
        self.plant("s1.jsonl.1", mtime=OLD)
        real_unlink = os.unlink
        calls = []

        def unlink(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "Permission denied")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(J._package.runs.os, "unlink", side_effect=unlink):
            report = J.prune_runs(str(self.runs))
        self.assertEqual(report, {
            "removed": [str(self.runs / "s1.jsonl.1")],
            "warnings": [f"cannot remove {self.runs / 's1.jsonl'}: Permission denied"]})
        self.assertEqual(sorted(os.listdir(self.runs)), ["s1.jsonl"])
        calls.clear()
        err = io.StringIO()
        with mock.patch.object(J._package.runs.os, "unlink", side_effect=unlink), \
                redirect_stderr(err):
            J.prune_old_runs()
        self.assertEqual(err.getvalue(), f"warning: runs: cannot remove "
                                         f"{self.runs / 's1.jsonl'}: Permission denied\n")

    def test_it_never_raises(self):
        self.plant("s1.jsonl", mtime=OLD)
        with mock.patch.object(J._package.runs.os, "scandir",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(J.prune_runs(str(self.runs)),
                             {"removed": [], "warnings": ["the prune stopped: boom"]})
        common = J._package.plugin._hooks_common
        err = io.StringIO()
        with mock.patch.object(common, "runs_root", side_effect=RuntimeError("boom")), \
                redirect_stderr(err):
            J.prune_old_runs()
        self.assertEqual(err.getvalue(),
                         "warning: the event landed, but the run log was not pruned "
                         "(boom)\n")
        self.assertTrue((self.runs / "s1.jsonl").is_file())


class TestPruneAtAppend(PruneCase):
    """SC-005: the prune runs after a `flow-started` and after a terminal append, in a
    project with no settings file too, and a failure never undoes the event."""

    def setUp(self):
        super().setUp()
        self.db = self.tmp / "shipgate.db"
        self.journal("init")

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["HOME"], env["CLAUDE_CONFIG_DIR"] = str(self.home), str(self.shell_config)
        env.update(extra)
        return env

    def journal(self, *args, env=None):
        proc = run_journal(["--db", self.db, *args], cwd=self.tmp, env=env or self.env())
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        return proc

    def append(self, stream, etype, data, env=None):
        return self.journal("append", "--stream=" + stream, "--type", etype,
                            "--data", json.dumps(data), env=env)

    def stream_types(self, stream):
        conn = sqlite3.connect(str(self.db))
        try:
            return [row[0] for row in conn.execute(
                "SELECT type FROM events WHERE stream = ? ORDER BY seq", (stream,))]
        finally:
            conn.close()

    def test_a_flow_started_prunes(self):
        kept = self.plant_store()
        proc = self.append("feature/a", "flow-started", {"request": "r"})
        self.assertEqual(proc.stderr, "")
        self.assertEqual(sorted(os.listdir(self.runs)), kept)
        self.assertTrue(self.outside.is_file())

    def test_a_terminal_append_prunes(self):
        self.append("feature/a", "flow-started", {"request": "r"})
        kept = self.plant_store()
        proc = self.append("feature/a", "flow-completed", {"reason": "merged"})
        self.assertEqual(proc.stderr, "")
        self.assertEqual(sorted(os.listdir(self.runs)), kept)

    def test_another_append_prunes_nothing(self):
        self.append("feature/a", "flow-started", {"request": "r"})
        self.plant("s1.jsonl", mtime=OLD)
        self.append("feature/a", "deviation", {"note": "n"})
        self.assertTrue((self.runs / "s1.jsonl").is_file())

    def test_no_root_is_nothing_and_no_error(self):
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        proc = self.append("feature/a", "flow-started", {"request": "r"}, env=env)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(self.stream_types("feature/a"), ["flow-started"])

    @unittest.skipIf(os.geteuid() == 0, "root deletes in a read-only directory")
    def test_a_failed_delete_is_a_warning_and_the_event_lands(self):
        old = self.plant("s1.jsonl", mtime=OLD)
        os.chmod(self.runs, 0o500)
        self.addCleanup(os.chmod, self.runs, 0o700)
        proc = self.append("feature/a", "flow-started", {"request": "r"})
        self.assertIn(f"warning: runs: cannot remove {old}: Permission denied",
                      proc.stderr)
        self.assertEqual(self.stream_types("feature/a"), ["flow-started"])
        self.assertTrue(old.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
