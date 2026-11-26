#!/usr/bin/env python3
"""Tests of the evidence store of UI tasks (ADR 0031): ``journal.py screens`` and
``_journal/screens.py`` (the root, the project key, the layout, register, print, list,
and the prune).

Every subprocess gets its own temporary ``CLAUDE_CONFIG_DIR``, and the module checks at
its end that the real evidence root of the environment did not change. Every PNG is
built in code; no fixture holds a real screen.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from test_journal import (
    INFRA, JOURNAL, OK, SESSION_ENV, USAGE, isolated_env, load_journal_module,
)
from test_ui import png_bytes


def png(width: int) -> bytes:
    return png_bytes(width)


def _ambient_root() -> str:
    """The real evidence root of the environment the suite runs in."""
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    base = (os.path.expanduser(config) if config
            else os.path.join(os.environ.get("HOME", ""), ".claude"))
    return os.path.join(base, "shipgate", "evidence")


def _tree(root: str):
    """Every entry under ROOT with its mode and mtime, or None when ROOT is absent."""
    if not os.path.lexists(root):
        return None
    out = []
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(directory, name)
            st = os.lstat(path)
            out.append((path, st.st_mode, st.st_mtime_ns))
    return sorted(out)


_REAL = {}
J = None


def setUpModule():
    global J
    J = load_journal_module()
    _REAL["root"] = _ambient_root()
    _REAL["tree"] = _tree(_REAL["root"])


def tearDownModule():
    after = _tree(_REAL["root"])
    if after != _REAL["tree"]:
        raise AssertionError(f"the real evidence root {_REAL['root']} changed in the tests")


def key_of(db: Path) -> str:
    return hashlib.sha256(str(os.path.realpath(db)).encode("utf-8")).hexdigest()[:12]


WORKLOG = """# Worklog: demo

# Build Plan

- [ ] T001 — the core — file(s): `lib/core.py` — done when: it runs
- [ ] T003 — the page — file(s): `web/page.html` — done when: it shows
- [ ] T004 — the form — file(s): `web/form.html`
- [ ] T005 — the list — file(s): `web/list.html`
"""


class ScreensCase(unittest.TestCase):
    """A journaled project whose settings set `ui.globs`, with one live stream that
    committed a design, and a Claude config directory of its own."""

    S = "feat/7-ui"
    UI = {"globs": ["web/*"]}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".claude").mkdir()
        self.db = self.root / ".claude" / "shipgate.db"
        self.config = self.root / "config"
        self.config.mkdir()
        self.evidence = self.config / "shipgate" / "evidence"
        self.key = key_of(self.db)
        self.settings(self.UI)
        (self.root / "docs" / "prd").mkdir(parents=True)
        (self.root / "docs" / "prd" / "demo.worklog.md").write_text(WORKLOG,
                                                                   encoding="utf-8")
        (self.root / "shots").mkdir()
        self.run_j("init", rc=OK)
        self.append(self.S, "flow-started", {"request": "r"})
        self.append(self.S, "design-committed", {"worklog": "docs/prd/demo.worklog.md"})

    # -- helpers ---------------------------------------------------------

    def settings(self, ui):
        data = {"version": 1, "db": ".claude/shipgate.db"}
        if ui is not None:
            data["ui"] = ui
        (self.root / ".claude" / "shipgate.json").write_text(json.dumps(data),
                                                             encoding="utf-8")

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        env.update(extra)
        return isolated_env(env)  # HOME too (#81: the run log)

    def run_j(self, *args, rc=None, env=None):
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), *map(str, args)],
            cwd=str(self.root), env=env or self.env(), capture_output=True, text=True)
        if rc is not None:
            self.assertEqual(proc.returncode, rc,
                             f"args={args!r}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
        return proc

    def append(self, stream, etype, data, rc=OK):
        return self.run_j("append", "--stream=" + stream, "--type", etype,
                          "--data", json.dumps(data), rc=rc)

    def shot(self, name, width):
        path = self.root / "shots" / name
        path.write_bytes(png(width))
        return path

    def screens(self, *args, rc=OK, env=None):
        return self.run_j("screens", *args, rc=rc, env=env)

    def stream_dir(self, stream=None):
        return self.evidence / self.key / J.stream_dir_name(stream or self.S)

    def files(self):
        """Every file under the evidence root, relative to it."""
        if not self.evidence.exists():
            return []
        return sorted(str(p.relative_to(self.evidence))
                      for p in self.evidence.rglob("*") if not p.is_dir())

    def assert_no_tmp(self):
        self.assertEqual([f for f in self.files() if f.endswith(".tmp")], [])

    def assert_refused(self, proc, line):
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, f"error: {line}\n")


# ---------------------------------------------------------------------------
# T007: the root, the key, the layout
# ---------------------------------------------------------------------------


class TestEvidenceRoot(unittest.TestCase):
    """`evidence_root`: environment variables only, an absolute path or None."""

    def root(self, env):
        with mock.patch.dict(os.environ, env, clear=True):
            return J.evidence_root()

    def test_the_config_directory_wins(self):
        self.assertEqual(self.root({"CLAUDE_CONFIG_DIR": "/c", "HOME": "/h"}),
                         "/c/shipgate/evidence")

    def test_home_when_the_config_directory_is_unset_or_empty(self):
        self.assertEqual(self.root({"HOME": "/h"}), "/h/.claude/shipgate/evidence")
        self.assertEqual(self.root({"CLAUDE_CONFIG_DIR": "", "HOME": "/h"}),
                         "/h/.claude/shipgate/evidence")

    def test_a_tilde_in_the_config_directory_expands(self):
        self.assertEqual(self.root({"CLAUDE_CONFIG_DIR": "~/c", "HOME": "/h"}),
                         "/h/c/shipgate/evidence")

    def test_neither_gives_none(self):
        self.assertIsNone(self.root({}))
        self.assertIsNone(self.root({"CLAUDE_CONFIG_DIR": "", "HOME": ""}))

    def test_a_relative_value_gives_none(self):
        self.assertIsNone(self.root({"CLAUDE_CONFIG_DIR": "rel/c", "HOME": "/h"}))
        self.assertIsNone(self.root({"HOME": "rel/h"}))


class TestProjectKey(unittest.TestCase):
    def test_a_linked_database_gives_the_key_of_the_real_file(self):
        """A worktree whose `.claude/shipgate.db` links to the main checkout's journal
        shares the main checkout's key."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            (base / "main" / ".claude").mkdir(parents=True)
            (base / "tree" / ".claude").mkdir(parents=True)
            real = base / "main" / ".claude" / "shipgate.db"
            link = base / "tree" / ".claude" / "shipgate.db"
            J.connect(real, create=True).close()
            os.symlink(real, link)
            keys = []
            for path in (real, link):
                conn = J.connect(path)
                try:
                    keys.append(J.project_key(conn))
                finally:
                    conn.close()
            self.assertEqual(keys, [key_of(real), key_of(real)])
            self.assertRegex(keys[0], r"^[0-9a-f]{12}$")

    def test_a_database_with_no_file_has_no_key(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        try:
            self.assertIsNone(J.project_key(conn))
        finally:
            conn.close()


class TestStreamDirectoryName(unittest.TestCase):
    def test_the_encoding(self):
        self.assertEqual(J.stream_dir_name("feat/7-ui"), "feat%2F7-ui")
        self.assertEqual(J.stream_dir_name("fix_1.x"), "fix_1.x")
        self.assertEqual(J.stream_dir_name("a b"), "a%20b")
        self.assertEqual(J.stream_dir_name("%2E%2E"), "%252E%252E")
        self.assertEqual(J.stream_dir_name("../x"), "..%2Fx")

    def test_a_name_that_names_no_directory(self):
        # `.DS_Store` is the Finder file of the layout, so no stream directory takes its
        # name: a directory named so is refused wherever it sits.
        for stream in ("", ".", "..", ".DS_Store", "x" * 256, "/" * 86):
            with self.subTest(stream=stream[:20]):
                self.assertIsNone(J.stream_dir_name(stream))
        self.assertEqual(J.stream_dir_name("x" * 255), "x" * 255)

    def test_the_round_trip(self):
        for stream in ("feat/7-ui", "a b", "%2E%2E", "ü/ß", "..x", "../x"):
            with self.subTest(stream=stream):
                self.assertTrue(J.valid_stream_dir(J.stream_dir_name(stream)))

    def test_a_name_outside_the_encoding_is_refused(self):
        for name in ("", ".", "..", ".DS_Store", "%2E%2E", "%2e%2e", "%2f", "feat%2f7", "a b",
                     "x%", "%zz", "%FF"):
            with self.subTest(name=name):
                self.assertFalse(J.valid_stream_dir(name))


# ---------------------------------------------------------------------------
# T007: --file
# ---------------------------------------------------------------------------


class TestRegisterFiles(ScreensCase):
    def test_a_780_px_png_is_stored_under_390(self):
        shot = self.shot("a.png", 780)
        proc = self.screens("--stream", self.S, "--task", "T003", "--file", shot)
        d = os.path.realpath(self.stream_dir())
        self.assertEqual(proc.stdout,
                         f"stored {d}/T003-390.png — 390 (780 px)\n"
                         "T003 still misses: 1280\n")
        self.assertEqual((Path(d) / "T003-390.png").read_bytes(), png(780))
        self.assertEqual(self.files(), [f"{self.key}/feat%2F7-ui/T003-390.png"])
        st = os.stat(Path(d) / "T003-390.png")
        self.assertEqual(st.st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)

    def test_every_width(self):
        self.screens("--stream", self.S, "--task", "T003", "--file", self.shot("a.png", 390))
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("b.png", 2560))
        d = os.path.realpath(self.stream_dir())
        self.assertEqual(proc.stdout,
                         f"stored {d}/T003-1280.png — 1280 (2560 px)\n"
                         "T003 has every width: 390, 1280\n")

    def test_the_copy_has_its_own_mtime(self):
        shot = self.shot("a.png", 780)
        os.utime(shot, (1_000_000_000, 1_000_000_000))
        before = time.time() - 5
        self.screens("--stream", self.S, "--task", "T003", "--file", shot)
        self.assertGreater(os.stat(self.stream_dir() / "T003-390.png").st_mtime, before)

    def test_a_second_file_takes_a_suffix_and_the_tenth_is_refused(self):
        shot = self.shot("a.png", 780)
        self.screens("--stream", self.S, "--task", "T003", "--file", shot)
        self.screens("--stream", self.S, "--task", "T003", "--file", shot)
        self.assertEqual(self.files(), [f"{self.key}/feat%2F7-ui/T003-390-2.png",
                                        f"{self.key}/feat%2F7-ui/T003-390.png"])
        proc = self.screens("--stream", self.S, "--task", "T003",
                            *(["--file", shot] * 8), rc=USAGE)
        self.assertEqual(proc.stdout.count("stored "), 7)
        self.assertEqual(proc.stderr, "error: screens: T003 has 9 files at 390 already; "
                                      "no more fit; the 7 files stored above stay\n")
        proc = self.screens("--stream", self.S, "--task", "T003", "--file", shot,
                            rc=USAGE)
        self.assert_refused(proc, "screens: T003 has 9 files at 390 already; no more fit")
        self.assertEqual(len(self.files()), 9)
        self.assert_no_tmp()

    def test_a_note_for_a_task_that_is_not_ui(self):
        proc = self.screens("--stream", self.S, "--task", "T001",
                            "--file", self.shot("a.png", 1280))
        self.assertEqual(proc.stdout.splitlines()[1:], [
            "T001 still misses: 390",
            "note: T001 is not a UI task here (no path on its Build Plan line matches "
            "ui.globs), so task-done does not ask for these files"])

    def test_a_note_when_no_task_is_ui(self):
        self.settings(None)
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 1280))
        self.assertEqual(proc.stdout.splitlines()[-1],
                         "note: no task is UI here (ui.globs is empty)")
        (self.root / "docs" / "prd" / "demo.worklog.md").unlink()
        self.settings(self.UI)
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("b.png", 1280))
        self.assertEqual(
            proc.stdout.splitlines()[-1],
            f"note: no task is UI here ({self.root}/docs/prd/demo.worklog.md cannot be "
            "read)")
        self.append("feat/8-other", "flow-started", {"request": "r"})
        proc = self.screens("--stream", "feat/8-other", "--task", "T003",
                            "--file", self.shot("c.png", 1280))
        self.assertEqual(proc.stdout.splitlines()[-1],
                         "note: no task is UI here (no design-committed names a worklog)")

    def test_two_set_widths_and_width_settles_it(self):
        self.settings({"globs": ["web/*"], "widths": [390, 780]})
        shot = self.shot("a.png", 780)
        proc = self.screens("--stream", self.S, "--task", "T003", "--file", shot,
                            rc=USAGE)
        self.assert_refused(proc, f"screens: {shot} is 780 px wide, which matches 390 "
                                  "and 780; name one with --width")
        proc = self.screens("--stream", self.S, "--task", "T003", "--file", shot,
                            "--width", "1280", rc=USAGE)
        self.assert_refused(proc, f"screens: {shot} is 780 px wide, which matches 390 "
                                  "and 780, not --width 1280")
        self.screens("--stream", self.S, "--task", "T003", "--file", shot,
                     "--width", "780")
        self.assertEqual(self.files(), [f"{self.key}/feat%2F7-ui/T003-780.png"])

    def test_each_refusal(self):
        good = self.shot("good.png", 780)
        jpeg = self.root / "shots" / "x.jpg"
        jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 40)
        short = self.root / "shots" / "short.png"
        short.write_bytes(png(780)[:20])
        wide = self.shot("wide.png", 1000)
        missing = self.root / "shots" / "none.png"
        self.append("feat/9-done", "flow-started", {"request": "r"})
        self.append("feat/9-done", "flow-completed", {"reason": "merged"})
        long_name = "x" * 300
        self.append(long_name, "flow-started", {"request": "r"})
        cases = [
            (("--stream", "feat/none", "--task", "T003", "--file", good),
             "screens: stream 'feat/none' has no events"),
            (("--stream", "feat/9-done", "--task", "T003", "--file", good),
             "screens: stream 'feat/9-done' is finished"),
            (("--stream", self.S, "--task", "t3", "--file", good),
             "screens: the task id 't3' is not T and digits, as in T003"),
            (("--stream", self.S, "--task", "T٣", "--file", good),
             "screens: the task id 'T٣' is not T and digits, as in T003"),
            (("--stream=" + long_name, "--task", "T003", "--file", good),
             f"screens: the stream name {long_name!r} cannot name an evidence directory"),
            (("--stream", self.S, "--task", "T003", "--file", missing),
             f"screens: no file at {missing}"),
            (("--stream", self.S, "--task", "T003", "--file", self.root / "shots"),
             f"screens: {self.root / 'shots'} is not a regular file"),
            (("--stream", self.S, "--task", "T003", "--file", jpeg),
             f"screens: {jpeg}: not a PNG: no PNG signature"),
            (("--stream", self.S, "--task", "T003", "--file", short),
             f"screens: {short}: truncated: 20 bytes, a PNG header needs 24"),
            (("--stream", self.S, "--task", "T003", "--file", wide),
             f"screens: {wide} is 1000 px wide, which is no set width (390, 1280) at "
             "1x, 2x or 3x"),
        ]
        for args, line in cases:
            with self.subTest(line=line[:60]):
                self.assert_refused(self.screens(*args, rc=USAGE), line)
        self.assertEqual(self.files(), [])
        self.assertFalse(self.evidence.exists())

    def test_no_root(self):
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780), rc=USAGE, env=env)
        self.assert_refused(proc, "screens: no evidence root: set CLAUDE_CONFIG_DIR or HOME")

    def test_a_bad_setting_exits_2_naming_the_key(self):
        shot = self.shot("a.png", 780)
        for ui, key in (({"globs": ["web/*"], "widths": [100]}, "ui.widths"),
                        ({"globs": ["web/*"], "widths": []}, "ui.widths"),
                        ({"globs": ["web/*"], "capture": "shot {url} {width}"},
                         "ui.capture"),
                        ({"globs": "web/*"}, "ui.globs")):
            with self.subTest(ui=ui):
                self.settings(ui)
                for args in (("--task", "T003", "--file", shot), ("--list",)):
                    proc = self.screens("--stream", self.S, *args, rc=USAGE)
                    self.assertIn(key, proc.stderr)
                    self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
        self.assertFalse(self.evidence.exists())

    def test_one_bad_file_writes_nothing(self):
        good = self.shot("good.png", 780)
        wide = self.shot("wide.png", 1000)
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", good, "--file", wide, rc=USAGE)
        self.assertIn("1000 px wide", proc.stderr)
        self.assertEqual(self.files(), [])
        self.assert_no_tmp()

    def test_a_link_in_the_layout_is_refused_and_nothing_is_written(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.evidence).mkdir(parents=True)
        os.symlink(outside, self.evidence / self.key)
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780), rc=INFRA)
        self.assertEqual(
            proc.stderr.splitlines()[-1],
            f"error: screens: refused {os.path.realpath(self.evidence)}/{self.key}: a "
            "symbolic link; nothing was written")
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_file_in_place_of_the_stream_directory_is_refused(self):
        (self.evidence / self.key).mkdir(parents=True)
        (self.evidence / self.key / "feat%2F7-ui").write_text("x", encoding="utf-8")
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780), rc=INFRA)
        self.assertTrue(proc.stderr.splitlines()[-1].endswith(
            "/feat%2F7-ui: not a directory; nothing was written"), proc.stderr)

    def test_a_hostile_stream_stays_in_its_own_directory(self):
        for stream in ("../x", "/abs", "a/../../b", "-dash"):
            with self.subTest(stream=stream):
                self.append(stream, "flow-started", {"request": "r"})
                self.screens("--stream=" + stream, "--task", "T003",
                             "--file", self.shot("a.png", 780))
                self.assertTrue((self.evidence / self.key / J.stream_dir_name(stream)
                                 / "T003-390.png").is_file())
        self.assertEqual(sorted(os.listdir(self.evidence)), [self.key])
        self.assertEqual(sorted(os.listdir(self.evidence / self.key)),
                         ["%2Fabs", "-dash", "..%2Fx", "a%2F..%2F..%2Fb"])


# ---------------------------------------------------------------------------
# T007: --url
# ---------------------------------------------------------------------------


class TestCaptureCommands(ScreensCase):
    CAPTURE = "shot --url {url} --w {width} --out {out} --keep {other} && touch {out}"

    def test_one_command_per_width_and_nothing_runs(self):
        self.settings({"globs": ["web/*"], "capture": self.CAPTURE})
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--url", "http://localhost:8000/a b?x=1&y=2")
        d = os.path.realpath(self.stream_dir())
        out390, out1280 = (shlex.quote(f"{d}/T003-{w}.png") for w in (390, 1280))
        self.assertEqual(proc.stdout.splitlines(), [
            f"shot --url 'http://localhost:8000/a b?x=1&y=2' --w 390 --out "
            f"{out390} --keep {{other}} && touch {out390}",
            f"shot --url 'http://localhost:8000/a b?x=1&y=2' --w 1280 --out "
            f"{out1280} --keep {{other}} && touch {out1280}",
            "run each command yourself; journal.py runs none. Then read the files and "
            "compare them with the PRD's reference.",
        ])
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(self.files(), [])

    def test_the_out_path_is_the_next_free_name(self):
        self.settings({"globs": ["web/*"], "capture": "c {url} {width} {out}"})
        self.screens("--stream", self.S, "--task", "T003", "--file", self.shot("a.png", 390))
        proc = self.screens("--stream", self.S, "--task", "T003", "--url", "u")
        d = os.path.realpath(self.stream_dir())
        self.assertEqual(proc.stdout.splitlines()[:2],
                         [f"c u 390 {shlex.quote(f'{d}/T003-390-2.png')}",
                          f"c u 1280 {shlex.quote(f'{d}/T003-1280.png')}"])

    def test_a_placeholder_in_the_url_is_not_filled(self):
        self.settings({"globs": ["web/*"], "capture": "c {url} {width} {out}"})
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--url", "http://h/{out}/{width}")
        self.assertTrue(proc.stdout.startswith("c 'http://h/{out}/{width}' 390 "),
                        proc.stdout)

    def test_a_capture_with_a_quote_a_backtick_or_a_backslash_exits_2(self):
        """The URL is filled in quoted for a shell; a template that quotes `{url}` again
        would let `$(...)` in the URL run, so the setting refuses those characters."""
        for template in ('c "{url}" {width} {out}', "c '{url}' {width} {out}",
                         "c `{url}` {width} {out}", "c {url} {width} " + chr(92) + "{out}"):
            with self.subTest(template=template):
                self.settings({"globs": ["web/*"], "capture": template})
                proc = self.screens("--stream", self.S, "--task", "T003",
                                    "--url", "http://h/$(touch pwned)", rc=USAGE)
                self.assertEqual(proc.stdout, "")
                self.assertIn("ui.capture", proc.stderr)
                self.assertIn("no quote, backtick or backslash", proc.stderr)
                self.assertEqual(len(proc.stderr.splitlines()), 1, proc.stderr)
        self.assertFalse(self.evidence.exists())

    def test_without_the_capture_setting(self):
        proc = self.screens("--stream", self.S, "--task", "T003", "--url", "u", rc=USAGE)
        self.assert_refused(proc, "screens: --url needs the ui.capture setting (a command "
                                  "with {url}, {width} and {out})")
        self.assertFalse(self.evidence.exists())


# ---------------------------------------------------------------------------
# T007: --list
# ---------------------------------------------------------------------------


class TestList(ScreensCase):
    def state(self, *args):
        return json.loads(self.screens("--stream", self.S, "--list", "--json", *args).stdout)

    def test_present_waived_and_missing(self):
        self.screens("--stream", self.S, "--task", "T003",
                     "--file", self.shot("a.png", 390), "--file", self.shot("b.png", 2560))
        self.screens("--stream", self.S, "--task", "T005", "--file", self.shot("c.png", 780))
        self.append(self.S, "deviation", {"kind": "screens-waived", "task_ids": ["T004"],
                                          "note": "no browser tool in the worker"})
        d = os.path.realpath(self.stream_dir())
        self.assertEqual(self.state(), {
            "stream": self.S, "dir": d, "widths": [390, 1280], "note": None,
            "tasks": [
                {"task_id": "T003", "present": [390, 1280], "missing": [],
                 "waived": None, "files": [f"{d}/T003-1280.png", f"{d}/T003-390.png"]},
                {"task_id": "T004", "present": [], "missing": [390, 1280],
                 "waived": "no browser tool in the worker", "files": []},
                {"task_id": "T005", "present": [390], "missing": [1280],
                 "waived": None, "files": [f"{d}/T005-390.png"]},
            ]})
        text = self.screens("--stream", self.S, "--list").stdout
        self.assertEqual(text.splitlines(), [
            f"evidence: {d}",
            "T003 — 390, 1280",
            "T004 — waived: no browser tool in the worker",
            "T005 — missing 1280 (has 390)",
        ])

    def test_a_file_older_than_the_design_and_a_link_do_not_count(self):
        self.screens("--stream", self.S, "--task", "T003", "--file", self.shot("a.png", 390))
        d = self.stream_dir()
        ts = next(e for e in json.loads(self.run_j("log", "--json").stdout)["events"]
                  if e["type"] == "design-committed")["ts"]
        old = datetime.fromisoformat(ts).timestamp() - 60
        os.utime(d / "T003-390.png", (old, old))
        outside = self.shot("outside.png", 1280)
        os.symlink(outside, d / "T003-1280.png")
        task = self.state()["tasks"][0]
        self.assertEqual((task["present"], task["missing"], task["files"]),
                         ([], [390, 1280], []))

    def test_a_png_of_the_wrong_width_does_not_count(self):
        d = self.stream_dir()
        d.mkdir(parents=True)
        (d / "T003-390.png").write_bytes(png(1280))
        (d / "T003-1280.png").write_bytes(b"not a png at all, but long enough")
        self.assertEqual(self.state()["tasks"][0]["missing"], [390, 1280])

    def test_no_ui_task(self):
        self.settings(None)
        state = self.state()
        self.assertEqual((state["tasks"], state["note"]), ([], "ui.globs is empty"))
        self.assertEqual(self.screens("--stream", self.S, "--list").stdout.splitlines(), [
            f"evidence: {os.path.realpath(self.stream_dir())}",
            "no UI task: ui.globs is empty"])
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        self.assertEqual(
            self.screens("--stream", self.S, "--list", env=env).stdout.splitlines()[0],
            "evidence: none (no evidence root)")

    def test_the_list_creates_nothing(self):
        self.state()
        self.assertFalse(self.evidence.exists())

    def test_a_stream_with_no_events(self):
        self.assert_refused(self.screens("--stream", "feat/none", "--list", rc=USAGE),
                            "screens: stream 'feat/none' has no events")


# ---------------------------------------------------------------------------
# T009: the prune and its six delete rules
# ---------------------------------------------------------------------------

OLD = time.time() - 40 * 86400
OTHER_KEY = "0123456789ab"


class PruneCase(ScreensCase):
    DONE = "feat/9-done"

    def setUp(self):
        super().setUp()
        self.real = Path(os.path.realpath(self.evidence))

    def plant(self, *parts, data=None, old=False):
        """A file at ``<evidence>/<parts>``, its directories made; a PNG by default."""
        path = self.evidence.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png(390) if data is None else data)
        if old:
            os.utime(path, (OLD, OLD))
        return path

    def finished(self, stream=None):
        self.append(stream or self.DONE, "flow-started", {"request": "r"})
        self.append(stream or self.DONE, "flow-completed", {"reason": "merged"})

    def prune(self, rc=OK):
        return self.screens("--prune", rc=rc).stdout.splitlines()

    def prune_in_process(self, stream=None, root=None):
        conn = J.connect(self.db)
        try:
            return J.prune_evidence(str(root or self.evidence), self.key, conn,
                                    stream=stream)
        finally:
            conn.close()

    def r(self, *parts):
        return str(self.real.joinpath(*parts))


class TestPrune(PruneCase):
    def test_finished_and_unknown_streams_go_and_a_live_one_stays(self):
        """Moment 2 and rules 3, 4 and 5: this project's directories of a finished and
        of an unknown stream go with every file, each line with its count; a live
        stream's directory and another project's directories stay; the root stays."""
        self.finished()
        live = self.plant(self.key, "feat%2F7-ui", "T003-390.png")
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        self.plant(self.key, "feat%2F9-done", "T003-1280-2.png")
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        self.plant(self.key, "feat%2Funknown", ".T001-390.png.4242.tmp")
        self.plant(self.key, "feat%2Funknown", "T001-390-9.png")
        other = self.plant(OTHER_KEY, "feat%2F9-done", "T003-390.png")
        self.assertEqual(self.prune(), [
            f"evidence: removed {self.r(self.key, 'feat%2F9-done')} (2 files)",
            f"evidence: removed {self.r(self.key, 'feat%2Funknown')} (3 files)",
        ])
        self.assertTrue(live.is_file())
        self.assertTrue(other.is_file())
        self.assertEqual(sorted(os.listdir(self.evidence / self.key)), ["feat%2F7-ui"])
        self.assertEqual(self.prune(), [f"evidence: nothing to prune in {self.real}"])

    def test_a_project_directory_the_prune_left_empty_goes(self):
        """Rule 4: the project directory goes once its last stream directory went."""
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        self.assertEqual(self.prune(), [
            f"evidence: removed {self.r(self.key, 'feat%2Funknown')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)",
        ])
        self.assertEqual(os.listdir(self.evidence), [])

    def test_moment_1_prunes_the_one_stream(self):
        """With a stream, only that stream's directory goes, finished or not."""
        self.finished()
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        unknown = self.plant(self.key, "feat%2Funknown", "T001-390.png")
        report = self.prune_in_process(stream=self.S)
        self.assertEqual(report["removed_dirs"], [])
        self.plant(self.key, "feat%2F7-ui", "T003-390.png")
        report = self.prune_in_process(stream=self.S)
        self.assertEqual(report, {
            "removed_dirs": [(self.r(self.key, "feat%2F7-ui"), 1)], "removed_files": [],
            "refused": [], "warnings": []})
        self.assertTrue(unknown.is_file())
        self.assertTrue((self.evidence / self.key / "feat%2F9-done").is_dir())

    def test_old_files_anywhere_go_then_their_emptied_directories(self):
        """Moment 3 and rule 5: a file older than 30 days anywhere in the root goes; a
        directory goes only when this prune emptied it. A live stream's directory with a
        new file stays, and so does its empty directory with no old file."""
        self.append("feat/8-empty", "flow-started", {"request": "r"})
        self.plant(OTHER_KEY, "feat%2Fx", "T001-390.png", old=True)
        old_here = self.plant(self.key, "feat%2F7-ui", "T003-390.png", old=True)
        new_here = self.plant(self.key, "feat%2F7-ui", "T003-1280.png")
        (self.evidence / self.key / "feat%2F8-empty").mkdir()
        other_new = self.plant("abcdefabcdef", "feat%2Fy", "T002-390.png")
        self.assertEqual(sorted(self.prune()), sorted([
            f"evidence: removed {self.r(OTHER_KEY, 'feat%2Fx')} (1 file)",
            f"evidence: removed {self.r(OTHER_KEY)} (0 files)",
            f"evidence: removed {self.r(self.key, 'feat%2F7-ui', 'T003-390.png')} "
            "(older than 30 days)",
        ]))
        self.assertFalse(old_here.exists())
        self.assertTrue(new_here.is_file())
        self.assertTrue((self.evidence / self.key / "feat%2F8-empty").is_dir())
        self.assertTrue(other_new.is_file())
        self.assertTrue(self.evidence.is_dir())

    def test_links_are_refused_never_followed_and_kept(self):
        """Rule 2: a link to a file, a link to a directory outside the root (holding an
        old layout-named file), a stream directory that is a link and a project
        directory that is a link are refused and kept; their parents stay, and so does
        every file beside them; nothing outside the root changes."""
        self.finished()
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / "T001-390.png"
        target.write_bytes(png(390))
        os.utime(target, (OLD, OLD))
        os.utime(outside, (OLD, OLD))
        loose = self.root / "loose.png"
        loose.write_bytes(png(390))
        os.utime(loose, (OLD, OLD))
        done = self.evidence / self.key / "feat%2F9-done"
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        os.symlink(loose, done / "T003-1280.png")
        os.symlink(outside, self.evidence / self.key / "feat%2Funknown")
        os.symlink(outside, self.evidence / "fedcba987654")
        live = self.evidence / self.key / "feat%2F7-ui"
        live.mkdir()
        os.symlink(outside, live / "T003-390-2.png")
        before = (_tree(str(outside)), os.lstat(loose).st_mtime_ns)
        lines = sorted(self.prune())
        self.assertEqual(lines, sorted([
            f"evidence: refused {self.r(self.key, 'feat%2F9-done', 'T003-1280.png')} "
            "(a symbolic link)",
            f"evidence: refused {self.r(self.key, 'feat%2Funknown')} (a symbolic link)",
            f"evidence: refused {self.r('fedcba987654')} (a symbolic link)",
            f"evidence: refused {self.r(self.key, 'feat%2F7-ui', 'T003-390-2.png')} "
            "(a symbolic link)",
        ]))
        self.assertEqual((_tree(str(outside)), os.lstat(loose).st_mtime_ns), before)
        for link in (done / "T003-1280.png", self.evidence / self.key / "feat%2Funknown",
                     self.evidence / "fedcba987654", live / "T003-390-2.png"):
            self.assertTrue(link.is_symlink(), link)
        self.assertTrue((done / "T003-390.png").is_file())
        self.assertTrue(done.is_dir())

    def test_a_link_in_place_of_a_directory_in_moment_1(self):
        """Rule 2 for one stream: its directory, or the project directory, as a link is
        refused and kept, and the target is not touched."""
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "T001-390.png").write_bytes(png(390))
        (self.evidence / self.key).mkdir(parents=True)
        os.symlink(outside, self.evidence / self.key / "feat%2F7-ui")
        report = self.prune_in_process(stream=self.S)
        self.assertEqual(report["refused"],
                         [(self.r(self.key, "feat%2F7-ui"), "a symbolic link")])
        os.unlink(self.evidence / self.key / "feat%2F7-ui")
        os.rmdir(self.evidence / self.key)
        os.symlink(outside, self.evidence / self.key)
        report = self.prune_in_process(stream=self.S)
        self.assertEqual(report["refused"], [(self.r(self.key), "a symbolic link")])
        self.assertEqual(os.listdir(outside), ["T001-390.png"])

    def test_other_entries_are_refused_and_kept(self):
        """Rule 3: a file of another name, a directory of another name, a directory in a
        stream directory (even one named like a screenshot) and a fifo are refused and
        kept, with every directory above them and every file beside them; a directory
        outside the layout is never entered."""
        self.finished()
        done = self.evidence / self.key / "feat%2F9-done"
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        self.plant(self.key, "feat%2F9-done", "notes.txt", data=b"n")
        (done / "T003-1280.png").mkdir()
        os.mkfifo(done / "T003-390-2.png")
        random_old = self.plant("random", "T001-390.png", old=True)
        self.plant("notes.txt", data=b"n")
        dots_old = self.plant(self.key, "%2E%2E", "T001-390.png", old=True)
        self.plant(self.key, "stray.png")
        self.plant(self.key, "feat%2F7-ui", "sub", "T003-390.png", old=True)
        lines = sorted(self.prune())
        layout = "(not in the evidence layout)"
        self.assertEqual(lines, sorted([
            f"evidence: refused {self.r(self.key, 'feat%2F9-done', 'notes.txt')} {layout}",
            f"evidence: refused {self.r(self.key, 'feat%2F9-done', 'T003-1280.png')} "
            f"{layout}",
            f"evidence: refused {self.r(self.key, 'feat%2F9-done', 'T003-390-2.png')} "
            f"{layout}",
            f"evidence: refused {self.r('random')} {layout}",
            f"evidence: refused {self.r('notes.txt')} {layout}",
            f"evidence: refused {self.r(self.key, '%2E%2E')} {layout}",
            f"evidence: refused {self.r(self.key, 'stray.png')} {layout}",
            f"evidence: refused {self.r(self.key, 'feat%2F7-ui', 'sub')} {layout}",
        ]))
        self.assertTrue((done / "T003-390.png").is_file())
        for kept in (done / "notes.txt", done / "T003-1280.png", done / "T003-390-2.png",
                     random_old, dots_old, self.evidence / self.key / "stray.png"):
            self.assertTrue(os.path.lexists(kept), kept)

    def test_a_stream_directory_with_a_refused_entry_keeps_every_file(self):
        """Moments 1 and 2 remove a stream directory whole or not at all: one entry
        outside the layout (a `Thumbs.db`) keeps every file in it, and the prune says
        which entry it refused."""
        self.finished()
        done = self.plant(self.key, "feat%2F9-done", "T001-390.png").parent
        (done / "Thumbs.db").write_bytes(b"thumbs")
        refused = "evidence: refused {} (not in the evidence layout)"
        # Moment 2, by `screens --prune`.
        self.assertEqual(self.prune(),
                         [refused.format(self.r(self.key, "feat%2F9-done", "Thumbs.db"))])
        # Moment 2, before a register writes.
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780))
        self.assertEqual(proc.stderr, refused.format(
            self.r(self.key, "feat%2F9-done", "Thumbs.db")) + "\n")
        self.assertEqual(sorted(os.listdir(done)), ["T001-390.png", "Thumbs.db"])
        # Moment 1, after a terminal append. The age pass keeps the other directory's
        # entry and does not name it.
        mine = self.stream_dir()
        (mine / "Thumbs.db").write_bytes(b"thumbs")
        proc = self.append(self.S, "flow-completed", {"reason": "merged"})
        self.assertEqual(proc.stderr, refused.format(
            self.r(self.key, "feat%2F7-ui", "Thumbs.db")) + "\n")
        self.assertEqual(sorted(os.listdir(mine)), ["T003-390.png", "Thumbs.db"])
        self.assertEqual(sorted(os.listdir(done)), ["T001-390.png", "Thumbs.db"])

    def test_the_age_pass_still_removes_an_old_file_beside_a_refused_entry(self):
        """Moment 3 goes file by file: an old file in a kept directory goes, and the
        prune names it."""
        self.finished()
        done = self.plant(self.key, "feat%2F9-done", "T001-390.png", old=True).parent
        (done / "Thumbs.db").write_bytes(b"x")
        fresh = self.plant(self.key, "feat%2F9-done", "T002-390.png")
        self.assertEqual(sorted(self.prune()), sorted([
            f"evidence: removed {self.r(self.key, 'feat%2F9-done', 'T001-390.png')} "
            "(older than 30 days)",
            f"evidence: refused {self.r(self.key, 'feat%2F9-done', 'Thumbs.db')} "
            "(not in the evidence layout)"]))
        self.assertEqual(sorted(os.listdir(done)), [fresh.name, "Thumbs.db"])

    def test_prune_reports_a_refused_entry_of_the_whole_root(self):
        """`screens --prune` names what its age pass refuses anywhere in the root; the
        automatic runs do not (`TestHostileStreams`)."""
        self.plant("notes.txt", data=b"n")
        os.symlink(self.root, self.evidence / "fedcba987654")
        self.plant(OTHER_KEY, "feat%2Fz", "Thumbs.db", data=b"n")
        self.assertEqual(sorted(self.prune()), sorted([
            f"evidence: refused {self.r('notes.txt')} (not in the evidence layout)",
            f"evidence: refused {self.r('fedcba987654')} (a symbolic link)",
            f"evidence: refused {self.r(OTHER_KEY, 'feat%2Fz', 'Thumbs.db')} "
            "(not in the evidence layout)"]))

    def test_prune_prints_its_warnings_on_stderr(self):
        """Rule 6: a warning goes to stderr, the removed and refused lines to stdout,
        and the exit code stays 0."""
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        self.plant("notes.txt", data=b"n")
        blocked = self.plant(OTHER_KEY, "feat%2Fz", "T001-390.png", old=True).parent
        os.chmod(blocked, 0o500)
        self.addCleanup(os.chmod, blocked, 0o700)
        proc = self.screens("--prune")
        self.assertEqual(sorted(proc.stdout.splitlines()), sorted([
            f"evidence: removed {self.r(self.key, 'feat%2Funknown')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)",
            f"evidence: refused {self.r('notes.txt')} (not in the evidence layout)"]))
        self.assertEqual(proc.stderr,
                         f"warning: evidence: cannot remove "
                         f"{self.r(OTHER_KEY, 'feat%2Fz', 'T001-390.png')}: Permission "
                         "denied\n")

    def test_a_root_that_is_a_link_is_resolved_once(self):
        """Rule 1: the prune works under the resolved root; a sibling of it holding
        layout-shaped names does not change, and the link stays."""
        real = self.root / "real-evidence"
        sibling = self.root / "sibling"
        (self.config / "shipgate").mkdir()
        real.mkdir()
        os.symlink(real, self.evidence)
        (real / self.key / "feat%2Funknown").mkdir(parents=True)
        (real / self.key / "feat%2Funknown" / "T001-390.png").write_bytes(png(390))
        for base in (real, sibling):
            (base / OTHER_KEY / "feat%2Fx").mkdir(parents=True)
            (base / OTHER_KEY / "feat%2Fx" / "T001-390.png").write_bytes(png(390))
            os.utime(base / OTHER_KEY / "feat%2Fx" / "T001-390.png", (OLD, OLD))
        before = _tree(str(sibling))
        self.assertEqual(sorted(self.prune()), sorted([
            f"evidence: removed {real / self.key / 'feat%2Funknown'} (1 file)",
            f"evidence: removed {real / self.key} (0 files)",
            f"evidence: removed {real / OTHER_KEY / 'feat%2Fx'} (1 file)",
            f"evidence: removed {real / OTHER_KEY} (0 files)",
        ]))
        self.assertEqual(_tree(str(sibling)), before)
        self.assertTrue(self.evidence.is_symlink())
        self.assertEqual(os.listdir(real), [])

    def test_an_oserror_on_unlink_warns_and_the_prune_goes_on(self):
        """Rule 6: an OSError on one entry is one warning; the prune goes on, keeps the
        directory that still holds a file, and returns."""
        self.finished()
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        self.plant(self.key, "feat%2F9-done", "T004-390.png")
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        real_unlink = os.unlink
        calls = []

        def unlink(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "Permission denied")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(J._package.screens.os, "unlink", side_effect=unlink):
            report = self.prune_in_process()
        done = self.r(self.key, "feat%2F9-done")
        self.assertEqual(report["warnings"],
                         [f"cannot remove {done}/T003-390.png: Permission denied"])
        self.assertEqual(report["removed_dirs"],
                         [(self.r(self.key, "feat%2Funknown"), 1)])
        self.assertEqual(os.listdir(done), ["T003-390.png"])
        self.assertEqual(J.render_prune(report)[-1],
                         f"warning: evidence: cannot remove {done}/T003-390.png: "
                         "Permission denied")

    def test_the_prune_never_raises(self):
        """Rule 6: any other exception becomes one warning."""
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        with mock.patch.object(J._package.screens.os, "scandir",
                               side_effect=RuntimeError("boom")):
            report = self.prune_in_process()
        self.assertEqual(report["warnings"], ["the prune stopped: boom"])

    def test_a_missing_root_and_no_root(self):
        """Rule 1: a missing root is an empty report."""
        self.assertEqual(self.prune_in_process(),
                         {"removed_dirs": [], "removed_files": [], "refused": [],
                          "warnings": []})
        self.assertEqual(self.prune(), [f"evidence: nothing to prune in {self.real}"])
        env = {k: v for k, v in os.environ.items()
               if k not in (SESSION_ENV, "CLAUDE_CONFIG_DIR", "HOME")}
        self.assertEqual(self.screens("--prune", env=env).stdout,
                         "evidence: no evidence root (no CLAUDE_CONFIG_DIR, no HOME)\n")

    def test_render_prune(self):
        """Rule 5: one line per removed directory with its count, per old file outside
        a removed directory, per refused entry, per warning."""
        self.assertEqual(J.render_prune({
            "removed_dirs": [("/r/k/a", 1), ("/r/k/b", 3)],
            "removed_files": ["/r/k/c/T1-390.png"],
            "refused": [("/r/x", "a symbolic link"), ("/r/k/a\nb", "not in the evidence "
                                                                  "layout")],
            "warnings": ["cannot remove /r/k/d: Permission denied"],
        }), [
            "evidence: removed /r/k/a (1 file)",
            "evidence: removed /r/k/b (3 files)",
            "evidence: removed /r/k/c/T1-390.png (older than 30 days)",
            "evidence: refused /r/x (a symbolic link)",
            "evidence: refused '/r/k/a\\nb' (not in the evidence layout)",
            "warning: evidence: cannot remove /r/k/d: Permission denied",
        ])


class TestHostileStreams(PruneCase):
    """A terminal append on a hostile stream name removes nothing outside
    `<root>/<key>/<its own encoded directory>`. Its age pass over the whole root (no
    timer: it runs when a stream ends) keeps each planted entry that is not in the
    layout without naming it, and removes no fresh file."""

    def test_each_hostile_name(self):
        streams = ["..", "../x", "/abs", "%2E%2E", "a/../../b", "x" * 300]
        for stream in streams:
            self.append(stream, "flow-started", {"request": "r"})
        planted = [
            self.plant(OTHER_KEY, "feat%2Fz", "T001-390.png"),
            self.plant("x", "T001-390.png"),
            self.plant(self.key, "abs", "T001-390.png"),
            self.plant(self.key, "%2E%2E", "T001-390.png"),
            self.plant("b", "T001-390.png"),
            self.plant(self.key, "x" * 255, "T001-390.png"),
            self.plant(self.key, "feat%2F7-ui", "T003-390.png"),
        ]
        own = {}
        for stream in streams:
            name = J.stream_dir_name(stream)
            if name is not None:
                own[stream] = self.plant(self.key, name, "T001-390.png").parent
        self.assertEqual(sorted(p.name for p in own.values()),
                         ["%252E%252E", "%2Fabs", "..%2Fx", "a%2F..%2F..%2Fb"])
        for stream in streams:
            with self.subTest(stream=stream[:20]):
                proc = self.append(stream, "flow-completed", {"reason": "merged"})
                expected = (f"evidence: removed {os.path.realpath(own[stream])} (1 file)\n"
                            if stream in own else "")
                self.assertEqual(proc.stderr, expected)
                if stream in own:
                    self.assertFalse(own[stream].exists())
        for path in planted:
            self.assertTrue(path.is_file(), path)


class TestRegisterPrunes(PruneCase):
    def test_file_prunes_after_its_checks_and_before_its_writes(self):
        """(deviation from the worklog) A refused call deletes nothing; a call that
        writes prunes first and prints the prune on stderr."""
        self.finished()
        done = self.plant(self.key, "feat%2F9-done", "T003-390.png").parent
        self.screens("--stream", self.S, "--task", "T003",
                     "--file", self.shot("wide.png", 1000), rc=USAGE)
        self.assertTrue(done.is_dir())
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780))
        self.assertEqual(proc.stderr.splitlines(), [
            f"evidence: removed {self.r(self.key, 'feat%2F9-done')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)"])
        self.assertFalse(done.exists())
        self.assertTrue(proc.stdout.startswith("stored "))

    def test_url_prunes_too(self):
        self.settings({"globs": ["web/*"], "capture": "c {url} {width} {out}"})
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        proc = self.screens("--stream", self.S, "--task", "T003", "--url", "u")
        self.assertEqual(proc.stderr.splitlines(), [
            f"evidence: removed {self.r(self.key, 'feat%2Funknown')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)"])

    def test_list_prunes_nothing(self):
        self.plant(self.key, "feat%2Funknown", "T001-390.png")
        proc = self.screens("--stream", self.S, "--list")
        self.assertEqual(proc.stderr, "")
        self.assertTrue((self.evidence / self.key / "feat%2Funknown").is_dir())


FINDER = b"\x00\x00\x00\x01Bud1"


class TestFinderFile(PruneCase):
    """T023: a regular file named `.DS_Store` in a project or a stream directory is in
    the layout. It never counts as a screenshot and goes only with its directory, after
    every other file and before the `rmdir`. Every other form of the name, and one in
    the root, is refused and kept, with its directory."""

    def finder(self, *parts):
        return self.plant(*parts, ".DS_Store", data=FINDER)

    def test_moment_1_removes_it_with_the_stream_and_the_project_directory(self):
        self.plant(self.key, "feat%2F7-ui", "T003-390.png")
        self.finder(self.key, "feat%2F7-ui")
        self.finder(self.key)
        proc = self.append(self.S, "flow-completed", {"reason": "merged"})
        self.assertEqual(proc.stderr.splitlines(), [
            f"evidence: removed {self.r(self.key, 'feat%2F7-ui')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)"])
        self.assertEqual(os.listdir(self.evidence), [])

    def test_moment_2_removes_it_with_the_stream_and_the_project_directory(self):
        """`screens --prune`: a finished stream's directory and an unknown stream's
        that holds only a `.DS_Store` go whole; then the project directory."""
        self.finished()
        self.plant(self.key, "feat%2F9-done", "T003-390.png")
        self.plant(self.key, "feat%2F9-done", "T003-1280.png")
        self.finder(self.key, "feat%2F9-done")
        self.finder(self.key, "feat%2Funknown")
        self.finder(self.key)
        self.assertEqual(self.prune(), [
            f"evidence: removed {self.r(self.key, 'feat%2F9-done')} (2 files)",
            f"evidence: removed {self.r(self.key, 'feat%2Funknown')} (0 files)",
            f"evidence: removed {self.r(self.key)} (0 files)"])
        self.assertEqual(os.listdir(self.evidence), [])

    def test_a_register_removes_it_with_a_finished_stream_directory(self):
        """Moment 2 before a write: the finished stream's directory goes with its
        `.DS_Store`; the live stream's directory keeps its own, and so the project
        directory stays."""
        self.finished()
        done = self.plant(self.key, "feat%2F9-done", "T003-390.png").parent
        self.finder(self.key, "feat%2F9-done")
        live = self.finder(self.key, "feat%2F7-ui").parent
        project = self.finder(self.key)
        proc = self.screens("--stream", self.S, "--task", "T003",
                            "--file", self.shot("a.png", 780))
        self.assertEqual(proc.stderr.splitlines(), [
            f"evidence: removed {self.r(self.key, 'feat%2F9-done')} (1 file)"])
        self.assertFalse(done.exists())
        self.assertEqual(sorted(os.listdir(live)), [".DS_Store", "T003-390.png"])
        self.assertTrue(project.is_file())

    def test_the_age_pass_removes_it_with_a_directory_it_emptied(self):
        """Moment 3: a stream directory that lost its last old file goes when only a
        `.DS_Store` is left, then the project directory that lost it."""
        self.plant(OTHER_KEY, "feat%2Fx", "T001-390.png", old=True)
        self.finder(OTHER_KEY, "feat%2Fx")
        self.finder(OTHER_KEY)
        self.assertEqual(self.prune(), [
            f"evidence: removed {self.r(OTHER_KEY, 'feat%2Fx')} (1 file)",
            f"evidence: removed {self.r(OTHER_KEY)} (0 files)"])
        self.assertEqual(os.listdir(self.evidence), [])

    def test_a_directory_that_lost_no_directory_or_no_file_keeps_it(self):
        """A stream or project directory that holds only a `.DS_Store` and lost
        nothing in this prune stays, and so does one that keeps a fresh file; a live
        stream's directory is never removed because of a `.DS_Store`."""
        alone = self.finder(OTHER_KEY, "feat%2Fx")
        fresh = self.plant(OTHER_KEY, "feat%2Fy", "T001-390.png")
        old = self.plant(OTHER_KEY, "feat%2Fy", "T002-390.png", old=True)
        beside = self.finder(OTHER_KEY, "feat%2Fy")
        other_project = self.finder(OTHER_KEY)
        live = self.finder(self.key, "feat%2F7-ui")
        project = self.finder(self.key)
        self.assertEqual(self.prune(), [
            f"evidence: removed {self.r(OTHER_KEY, 'feat%2Fy', 'T002-390.png')} "
            "(older than 30 days)"])
        self.assertFalse(old.exists())
        for kept in (alone, fresh, beside, other_project, live, project):
            self.assertTrue(kept.is_file(), kept)
        proc = self.append("feat/8-other", "flow-started", {"request": "r"})
        self.assertEqual(proc.stderr, "")
        for kept in (alone, fresh, beside, other_project, live, project):
            self.assertTrue(kept.is_file(), kept)

    def test_every_other_form_of_the_name_is_refused_and_keeps_its_directory(self):
        """A link, a directory and a fifo named `.DS_Store`, an AppleDouble `._` file,
        a case variant and a name with a prefix or a suffix: each is refused, kept, and
        keeps its directory and every file beside it. The link's target outside the
        root and a file inside the directory are not touched. A directory named
        `.DS_Store` in a project directory is the directory of a stream of that name,
        so the project level leaves that form out."""
        outside = self.root / "outside.bin"
        outside.write_bytes(FINDER)
        os.utime(outside, (OLD, OLD))
        before = (outside.read_bytes(), os.lstat(outside).st_mtime_ns)

        def form(directory, kind, name):
            path = directory / name
            if kind == "link":
                os.symlink(outside, path)
            elif kind == "dir":
                path.mkdir()
                (path / "T001-390.png").write_bytes(png(390))
                os.utime(path / "T001-390.png", (OLD, OLD))
            elif kind == "fifo":
                os.mkfifo(path)
            else:
                path.write_bytes(FINDER)
            return path

        forms = [("link", ".DS_Store"), ("dir", ".DS_Store"), ("fifo", ".DS_Store"),
                 ("file", "._T001-390.png"), ("file", ".ds_store"),
                 ("file", ".DS_STORE"), ("file", ".DS_Store.bak"),
                 ("file", "x.DS_Store"), ("file", "._.DS_Store")]
        layout, link = "(not in the evidence layout)", "(a symbolic link)"
        expected, kept_streams, kept_projects = [], [], []
        for i, (kind, name) in enumerate(forms):
            # The stream level: an unknown stream's directory, which moment 2 selects.
            stream = self.plant(self.key, f"feat%2Fh{i}", "T001-390.png").parent
            entry = form(stream, kind, name)
            kept_streams.append((stream, entry))
            expected.append(f"evidence: refused {self.r(self.key, f'feat%2Fh{i}', name)} "
                            f"{link if kind == 'link' else layout}")
            if kind == "dir":
                continue
            # The project level: another project whose only stream directory the age
            # pass empties.
            key = f"aaaaaaaaaa{i:02x}"
            self.plant(key, "feat%2Fx", "T001-390.png", old=True)
            entry = form(self.evidence / key, kind, name)
            kept_projects.append((self.evidence / key, entry))
            expected += [
                f"evidence: removed {self.r(key, 'feat%2Fx')} (1 file)",
                f"evidence: refused {self.r(key, name)} "
                f"{link if kind == 'link' else layout}"]
        self.assertEqual(sorted(self.prune()), sorted(expected))
        for stream, entry in kept_streams:
            self.assertTrue(os.path.lexists(entry), entry)
            self.assertTrue((stream / "T001-390.png").is_file(), stream)
        for project, entry in kept_projects:
            self.assertEqual(os.listdir(project), [entry.name])
        self.assertTrue((self.evidence / self.key / "feat%2Fh1" / ".DS_Store"
                         / "T001-390.png").is_file())
        self.assertEqual((outside.read_bytes(), os.lstat(outside).st_mtime_ns), before)

    def test_one_in_the_root_is_refused_and_never_removed(self):
        """The root is never removed, so a `.DS_Store` there blocks no cleanup: it
        stays refused. `screens --prune` names it; the automatic prunes keep it
        without naming it."""
        in_root = self.finder()
        self.plant(OTHER_KEY, "feat%2Fx", "T001-390.png", old=True)
        self.assertEqual(sorted(self.prune()), sorted([
            f"evidence: removed {self.r(OTHER_KEY, 'feat%2Fx')} (1 file)",
            f"evidence: removed {self.r(OTHER_KEY)} (0 files)",
            f"evidence: refused {self.r('.DS_Store')} (not in the evidence layout)"]))
        self.assertTrue(in_root.is_file())
        self.plant(self.key, "feat%2F7-ui", "T003-390.png")
        proc = self.append(self.S, "flow-completed", {"reason": "merged"})
        self.assertEqual(proc.stderr.splitlines(), [
            f"evidence: removed {self.r(self.key, 'feat%2F7-ui')} (1 file)",
            f"evidence: removed {self.r(self.key)} (0 files)"])
        self.assertEqual(os.listdir(self.evidence), [".DS_Store"])
        self.assertEqual(in_root.read_bytes(), FINDER)

    def test_the_list_and_the_next_name_do_not_see_it(self):
        """It never counts as evidence: `--list` and the next free name read only
        `T<n>-<w>[-<k>].png` names."""
        self.screens("--stream", self.S, "--task", "T003", "--file", self.shot("a.png", 390))
        self.finder(self.key, "feat%2F7-ui")
        d = os.path.realpath(self.stream_dir())
        task = json.loads(self.screens("--stream", self.S, "--list",
                                       "--json").stdout)["tasks"][0]
        self.assertEqual((task["present"], task["missing"], task["files"]),
                         ([390], [1280], [f"{d}/T003-390.png"]))
        self.settings({"globs": ["web/*"], "capture": "c {url} {width} {out}"})
        proc = self.screens("--stream", self.S, "--task", "T003", "--url", "u")
        self.assertEqual(proc.stdout.splitlines()[:2],
                         [f"c u 390 {shlex.quote(f'{d}/T003-390-2.png')}",
                          f"c u 1280 {shlex.quote(f'{d}/T003-1280.png')}"])


class TestScreensUsage(ScreensCase):
    def test_each_misuse_exits_2_with_one_line(self):
        f = self.shot("a.png", 780)
        cases = [
            (("--prune", "--stream", self.S), "screens: --prune takes no --stream"),
            (("--task", "T003", "--file", f), "screens: --file needs --stream"),
            (("--task", "T003", "--url", "u"), "screens: --url needs --stream"),
            (("--list",), "screens: --list needs --stream"),
            (("--stream", self.S, "--file", f), "screens: --file needs --task"),
            (("--stream", self.S, "--url", "u"), "screens: --url needs --task"),
            (("--stream", self.S, "--list", "--task", "T003"),
             "screens: --task goes with --file or --url only"),
            (("--stream", self.S, "--task", "T003", "--url", "u", "--width", "390"),
             "screens: --width goes with --file only"),
            (("--stream", self.S, "--task", "T003", "--file", f, "--json"),
             "screens: --json goes with --list only"),
        ]
        for args, line in cases:
            with self.subTest(args=args):
                self.assert_refused(self.screens(*args, rc=USAGE), line)

    def test_two_forms_or_none_is_an_argparse_error(self):
        for args in ((), ("--stream", self.S, "--list", "--prune")):
            with self.subTest(args=args):
                self.assertEqual(self.screens(*args, rc=USAGE).stdout, "")

    def test_the_help_names_the_forms_and_the_root(self):
        text = " ".join(self.run_j("screens", "--help", rc=OK).stdout.split()).lower()
        for part in ("--file", "--url", "--list", "--prune", "claude_config_dir",
                     "it never runs a command"):
            self.assertIn(part, text)
        self.assertIn("never runs a command", self.run_j("--help", rc=OK).stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
