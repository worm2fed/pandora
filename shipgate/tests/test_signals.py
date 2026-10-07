#!/usr/bin/env python3
"""Contract + unit tests for shipgate's ``scripts/signals.py``.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_signals.py'

Every fixture is a synthetic git repository built here in a temp directory, with
fixed 2020 commit dates so the numbers are exact.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SIGNALS = TESTS_DIR.parent / "scripts" / "signals.py"

# Exit-code contract (mirrors signals.py --help).
OK = 0
INFRA = 1
USAGE = 2

AUTHOR = ("Fixture Author", "fixture@example.test")
ALICE = ("Alice Fixture", "user@alice")


def load_signals_module():
    """Import signals.py directly, for unit tests of its helpers."""
    spec = importlib.util.spec_from_file_location("shipgate_signals", SIGNALS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_signals(args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(SIGNALS)] + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )


def ts(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second,
                        tzinfo=timezone.utc).timestamp())


class FixtureRepo:
    """A synthetic git repository with deterministic commit dates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, when=None, author=AUTHOR):
        env = dict(os.environ)
        env.pop("GIT_DIR", None)
        env.pop("GIT_WORK_TREE", None)
        if when is not None:
            env["GIT_AUTHOR_DATE"] = f"@{when} +0000"
            env["GIT_COMMITTER_DATE"] = f"@{when} +0000"
        command = [
            "git",
            "-c", f"user.name={author[0]}",
            "-c", f"user.email={author[1]}",
            "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null",
            *args,
        ]
        try:
            result = subprocess.run(command, cwd=str(self.path), env=env,
                                    capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f"git unavailable: {error}") from error
        if result.returncode != 0:
            raise unittest.SkipTest(f"git {args[0]} failed: {result.stderr}")
        return result.stdout

    def write(self, relpath, text):
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message, when, writes=None, removes=(), moves=(), author=AUTHOR):
        for src, dst in moves:
            self.git("mv", src, dst)
        for relpath in removes:
            self.git("rm", "-q", relpath)
        for relpath, text in (writes or {}).items():
            self.write(relpath, text)
            self.git("add", relpath)
        self.git("commit", "-q", "--allow-empty", "-m", message,
                 when=when, author=author)


def build_standard(path: Path) -> FixtureRepo:
    """The shared fixture; the numbers in the tests below are derived by hand from it.

    Population (after default excludes): docs/{a,b,c}.md, src/{hot,new_name,one_fix,
    stable}.py. HEAD is 2020-12-01T00:00Z.
    """
    repo = FixtureRepo(path)
    body = "line\n" * 20
    repo.commit("initial import", ts(2020, 1, 1), writes={
        "src/stable.py": "stable\n",
        "src/hot.py": "hot 1\n",
        "src/old_name.py": body,
        "src/gone.py": "gone\n",
        "docs/a.md": "a\n",
        "docs/b.md": "b\n",
        "docs/c.md": "c 1\n",
        "vendor/x.js": "x 1\n",
        "yarn.lock": "lock 1\n",
    })
    repo.commit("fix: handle empty input", ts(2020, 2, 1), writes={
        "src/hot.py": "hot 2\n", "src/old_name.py": body + "more\n"})
    repo.commit("fix(parser): off by one", ts(2020, 3, 1),
                writes={"src/hot.py": "hot 3\n"}, author=ALICE)
    repo.commit("hotfix for crash", ts(2020, 4, 1), writes={
        "src/hot.py": "hot 4\n", "vendor/x.js": "x 2\n", "yarn.lock": "lock 2\n"})
    repo.commit("move old_name to new_name", ts(2020, 5, 1),
                moves=[("src/old_name.py", "src/new_name.py")])
    repo.commit("feat: extend new_name", ts(2020, 6, 1),
                writes={"src/new_name.py": body + "more\nextended\n"})
    repo.commit("chore: remove gone", ts(2020, 7, 1), removes=["src/gone.py"])
    repo.commit("fix: add one_fix", ts(2020, 8, 1), writes={"src/one_fix.py": "one\n"})
    repo.commit("docs: c", ts(2020, 9, 1), writes={"docs/c.md": "c 2\n"})
    repo.commit("feat: more", ts(2020, 10, 1), writes={
        "docs/c.md": "c 3\n", "src/hot.py": "hot 5\n"})
    repo.commit("docs: c again", ts(2020, 12, 1), writes={"docs/c.md": "c 4\n"})
    # An untracked config whose section holds only placeholders: all defaults apply,
    # and the no-write snapshot covers `.claude/`.
    repo.write(".claude/shipgate.md",
               "# cfg\n\n## Code signals\n\n- Window: `<months>`\n"
               "- Fix pattern: `<regex>`\n- Exclude: `<globs>`\n")
    return repo


class SignalsCase(unittest.TestCase):
    def signals(self, *args, cwd=None, env=None, rc=OK):
        proc = run_signals(args, cwd=cwd, env=env)
        if rc is not None:
            self.assertEqual(
                proc.returncode, rc,
                msg=f"rc={proc.returncode} args={args!r}\nstdout: {proc.stdout}\n"
                    f"stderr: {proc.stderr}")
        return proc

    def signals_json(self, *args, cwd=None, env=None):
        proc = self.signals(*args, "--json", cwd=cwd, env=env)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout)


class StandardRepoCase(SignalsCase):
    """One standard fixture per class, built once."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        cls.repo = build_standard(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def hotspots(self, *args):
        return self.signals_json("hotspots", "--repo", self.root, *args)

    def rows(self, *args):
        return {f["path"]: f for f in self.hotspots(*args)["files"]}


# ---------------------------------------------------------------------------
# T003 — degradation, exit codes, config
# ---------------------------------------------------------------------------


class TestDegradation(SignalsCase):
    """FR-015 / SC-002: every unavailable case is exit 0, silent on stderr."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def assert_unavailable(self, repo, reason, env=None, commands=("hotspots",)):
        for command in commands:
            extra = ["x.py"] if command in ("blast", "suspects") else []
            proc = self.signals(command, *extra, "--repo", repo, "--json",
                                env=env, rc=OK)
            self.assertEqual(proc.stderr, "", msg=command)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["version"], 1)
            self.assertIs(payload["available"], False, msg=command)
            self.assertEqual(payload["reason"], reason, msg=command)
            table = self.signals(command, *extra, "--repo", repo, env=env, rc=OK)
            self.assertEqual(table.stderr, "", msg=command)
            self.assertEqual(table.stdout, f"signals unavailable: {reason}\n",
                             msg=command)

    def test_a_directory_without_git_is_unavailable_no_git(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        (plain / "a.py").write_text("x\n")
        self.assert_unavailable(plain, "no-git",
                                commands=("hotspots", "blast", "suspects"))

    def test_an_empty_repository_is_unavailable_empty_history(self):
        FixtureRepo(self.tmp / "empty")
        self.assert_unavailable(self.tmp / "empty", "empty-history",
                                commands=("hotspots", "blast", "suspects"))

    def test_a_shallow_clone_has_no_trajectory(self):
        source = FixtureRepo(self.tmp / "src")
        source.commit("one", ts(2020, 1, 1), writes={"a.txt": "1\n"})
        source.commit("two", ts(2020, 2, 1), writes={"a.txt": "2\n"})
        dst = self.tmp / "shallow"
        result = subprocess.run(
            ["git", "clone", "-q", "--depth", "1", f"file://{source.path}", str(dst)],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise unittest.SkipTest(f"shallow clone failed: {result.stderr}")
        self.assert_unavailable(dst, "shallow")
        payload = self.signals_json("hotspots", "--repo", dst)
        self.assertIs(payload["trajectory"]["available"], False)
        self.assertEqual(payload["trajectory"]["reason"], "shallow")

    def test_git_missing_from_path_is_unavailable_no_git(self):
        source = FixtureRepo(self.tmp / "src")
        source.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        empty_bin = self.tmp / "bin"
        empty_bin.mkdir()
        env = dict(os.environ, PATH=str(empty_bin))
        self.assert_unavailable(source.path, "no-git", env=env,
                                commands=("hotspots", "blast", "suspects"))

    def test_usage_errors_exit_2(self):
        FixtureRepo(self.tmp / "r").commit("one", ts(2020, 1, 1),
                                           writes={"a.py": "1\n"})
        repo = self.tmp / "r"
        self.signals("hotspots", "--repo", repo, "--window", "0", rc=USAGE)
        self.signals("hotspots", "--repo", repo, "--fix-pattern", "(", rc=USAGE)
        self.signals("hotspots", "--repo", repo, "--by-dir", "0", rc=USAGE)
        self.signals("hotspots", "--repo", repo, "--top", "-1", rc=USAGE)
        self.signals("suspects", "--repo", repo, rc=USAGE)  # FILE is required
        self.signals("hotspots", "--repo", self.tmp / "missing", rc=USAGE)
        self.signals("nonsense", rc=USAGE)

    def test_blast_without_any_adapter_file_is_unavailable_no_adapter(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={"a.rb": "1\n"})
        payload = self.signals_json("blast", "a.rb", "--repo", repo.path)
        self.assertIs(payload["available"], False)
        self.assertEqual(payload["reason"], "no-adapter")
        self.assertEqual(payload["structure"]["reason"], "no-adapter")
        table = self.signals("blast", "a.rb", "--repo", repo.path)
        self.assertEqual(table.stdout, "signals unavailable: no-adapter\n")
        # hotspots still has trajectory, so it is available with unknown structure
        payload = self.signals_json("hotspots", "--repo", repo.path)
        self.assertIs(payload["available"], True)
        self.assertEqual(payload["files"][0]["structure"], "unknown")


class TestConfig(SignalsCase):
    """FR-002 / FR-008: `## Code signals` in .claude/shipgate.md, flags win."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.umbrella = Path(tmp.name) / "umbrella"
        FixtureRepo(self.umbrella)  # an umbrella is itself a git work tree
        self.repo = FixtureRepo(self.umbrella / "repo")
        self.repo.commit("one", ts(2020, 1, 1), writes={
            "a.py": "1\n", "generated/g.py": "g\n", "b.snap": "s\n"})

    def config(self, *args):
        return self.signals_json("hotspots", "--repo", self.repo.path, *args)["config"]

    def write_config(self, where: Path, body: str):
        target = where / ".claude" / "shipgate.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    def test_defaults_when_no_config_file(self):
        mod = load_signals_module()
        cfg = self.config()
        self.assertEqual(cfg["window_months"], 12)
        self.assertEqual(cfg["fix_pattern"], mod.DEFAULT_FIX_PATTERN)
        self.assertEqual(cfg["exclude"], list(mod.DEFAULT_EXCLUDES))
        self.assertEqual(cfg["source"], {"window_months": "default",
                                         "fix_pattern": "default",
                                         "exclude": "default"})

    def test_file_values_are_read_from_the_code_signals_section(self):
        self.write_config(self.repo.path, (
            "# Project\n\n## Other\n\n- Window: `99`\n\n"
            "## Code signals\n\n<!-- Default when absent: ... -->\n\n"
            "- Window: `18`\n- Fix pattern: `^(fix|bug)`\n"
            "- Exclude: `generated/`, `*.snap`\n\n## After\n\n- Window: `77`\n"))
        cfg = self.config()
        self.assertEqual(cfg["window_months"], 18)
        self.assertEqual(cfg["fix_pattern"], "^(fix|bug)")
        self.assertEqual(cfg["exclude"][-2:], ["generated/", "*.snap"])
        self.assertEqual(cfg["source"], {"window_months": "shipgate.md",
                                         "fix_pattern": "shipgate.md",
                                         "exclude": "shipgate.md"})
        paths = [f["path"] for f in self.signals_json(
            "hotspots", "--repo", self.repo.path)["files"]]
        self.assertEqual(paths, ["a.py"])

    def test_flags_override_the_file(self):
        self.write_config(self.repo.path, "## Code signals\n- Window: `18`\n"
                                          "- Fix pattern: `^(fix|bug)`\n")
        cfg = self.config("--window", "6", "--exclude", "*.py")
        self.assertEqual(cfg["window_months"], 6)
        self.assertEqual(cfg["source"]["window_months"], "flag")
        self.assertEqual(cfg["fix_pattern"], "^(fix|bug)")
        self.assertEqual(cfg["source"]["fix_pattern"], "shipgate.md")
        self.assertEqual(cfg["exclude"][-1], "*.py")
        self.assertEqual(cfg["source"]["exclude"], "flag")
        cfg = self.config("--fix-pattern", "^oops")
        self.assertEqual(cfg["fix_pattern"], "^oops")
        self.assertEqual(cfg["source"]["fix_pattern"], "flag")

    def test_placeholders_and_unbackticked_values_count_as_absent(self):
        self.write_config(self.repo.path, (
            "## Code signals\n- Window: 18\n- Fix pattern: `<regex>`\n"
            "- Exclude: <globs>\n"))
        cfg = self.config()
        self.assertEqual(cfg["window_months"], 12)
        self.assertEqual(cfg["source"], {"window_months": "default",
                                         "fix_pattern": "default",
                                         "exclude": "default"})

    def test_an_umbrella_config_applies_when_the_repo_has_none(self):
        self.write_config(self.umbrella, "## Code signals\n- Window: `9`\n")
        cfg = self.config()
        self.assertEqual(cfg["window_months"], 9)
        self.assertEqual(cfg["source"]["window_months"], "shipgate.md")

    def test_a_sidecar_marks_a_plain_parent_as_the_umbrella(self):
        """An umbrella bootstrapped by setup is not always a git work tree: the sidecar
        it wrote is the marker, and the nested repo reads the umbrella's config."""
        root = Path(self.umbrella.parent) / "plain-umbrella"
        repo = FixtureRepo(root / "repo")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        sidecar = root / ".claude" / "shipgate.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text('{"version": 1, "db": ".claude/shipgate.db"}', encoding="utf-8")
        self.write_config(root, "## Code signals\n- Window: `9`\n- Exclude: `gen/`\n")
        cfg = self.signals_json("hotspots", "--repo", repo.path)["config"]
        self.assertEqual(cfg["window_months"], 9)
        self.assertIn("gen/", cfg["exclude"])  # the file's excludes add to the defaults
        self.assertEqual(cfg["source"], {"window_months": "shipgate.md",
                                         "fix_pattern": "default",
                                         "exclude": "shipgate.md"})

    def test_a_sidecar_below_a_git_umbrella_adds_a_config_without_dropping_the_umbrellas(self):
        """A sidecar between the repo and the umbrella's git toplevel: both configs
        apply, the nearer one first per key."""
        repo = FixtureRepo(self.umbrella / "source" / "repo")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        sidecar = self.umbrella / "source" / ".claude" / "shipgate.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("{}", encoding="utf-8")
        self.write_config(self.umbrella / "source", "## Code signals\n- Window: `5`\n")
        self.write_config(self.umbrella, "## Code signals\n- Window: `9`\n"
                                         "- Fix pattern: `^umbrella`\n")
        cfg = self.signals_json("hotspots", "--repo", repo.path)["config"]
        self.assertEqual((cfg["window_months"], cfg["fix_pattern"]), (5, "^umbrella"))

    def test_the_sidecar_is_found_above_a_nested_parent_directory(self):
        """`source/<service>` layouts: the sidecar sits two levels up, not in the parent."""
        root = Path(self.umbrella.parent) / "plain-umbrella"
        repo = FixtureRepo(root / "source" / "repo")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        sidecar = root / ".claude" / "shipgate.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("{}", encoding="utf-8")
        self.write_config(root, "## Code signals\n- Window: `7`\n")
        cfg = self.signals_json("hotspots", "--repo", repo.path)["config"]
        self.assertEqual(cfg["window_months"], 7)

    def test_the_repo_config_wins_over_the_umbrella(self):
        self.write_config(self.umbrella, "## Code signals\n- Window: `9`\n"
                                         "- Fix pattern: `^umbrella`\n")
        self.write_config(self.repo.path, "## Code signals\n- Window: `3`\n")
        cfg = self.config()
        self.assertEqual(cfg["window_months"], 3)
        self.assertEqual(cfg["fix_pattern"], "^umbrella")

    def test_load_config_returns_values_and_sources(self):
        mod = load_signals_module()
        self.write_config(self.repo.path, "## Code signals\n- Exclude: `x/`,\n  `y/`\n")
        cfg, source = mod.load_config(self.repo.path)
        self.assertEqual(cfg.get("exclude"), ["x/", "y/"])
        self.assertNotIn("window_months", cfg)
        self.assertEqual(source["exclude"], "shipgate.md")
        self.write_config(self.repo.path, "## Code signals\n- Exclude: `a/, *.b`\n")
        self.assertEqual(mod.load_config(self.repo.path)[0]["exclude"], ["a/", "*.b"])

    def test_the_config_template_section_is_all_placeholders(self):
        mod = load_signals_module()
        template = (TESTS_DIR.parent / "config-template.md").read_text(encoding="utf-8")
        self.assertIn("## Code signals", template)
        self.assertEqual(mod.parse_code_signals(template), {})

    def test_a_filled_in_template_section_round_trips_through_load_config(self):
        """T013: the template's three bullets, values filled in, reach load_config."""
        mod = load_signals_module()
        template = (TESTS_DIR.parent / "config-template.md").read_text(encoding="utf-8")
        section = template[template.index("## Code signals"):]
        nxt = re.search(r"^## ", section[3:], re.MULTILINE)
        section = section[: nxt.start() + 3] if nxt else section
        values = {"Window": "`18`", "Fix pattern": "`^(fix|bug)`",
                  "Exclude": "`generated/`, `*.snap`"}
        lines = []
        for line in section.splitlines():
            for key, value in values.items():
                if line.startswith(f"- {key}:"):
                    line = f"- {key}: {value}"
            lines.append(line)
        self.write_config(self.repo.path, "# Project\n\n" + "\n".join(lines) + "\n")
        cfg, source = mod.load_config(self.repo.path)
        self.assertEqual(cfg, {"window_months": 18, "fix_pattern": "^(fix|bug)",
                               "exclude": ["generated/", "*.snap"]})
        self.assertEqual(set(source.values()), {"shipgate.md"})


# ---------------------------------------------------------------------------
# T005 — trajectory + labels
# ---------------------------------------------------------------------------


class TestFixPattern(unittest.TestCase):
    """FR-001 / FR-002: the default fix pattern, subject line only."""

    @classmethod
    def setUpClass(cls):
        mod = load_signals_module()
        cls.regex = re.compile(mod.DEFAULT_FIX_PATTERN, re.IGNORECASE)

    def test_positives(self):
        for subject in ("fix(x): guard nulls", "fix!: drop legacy", "fix: typo",
                        'Revert "feat: add x"', "revert: bad change",
                        "bug in parser", "hotfix", "Fixes the loader",
                        "fixed the build", "regression in export", "HOTFIX now",
                        "bugfix: null deref", "bugfixes for the loader",
                        "bugs in export", "hotfixes rolled up", "hot fix for x",
                        "fixing the parser"):
            self.assertRegex(subject, self.regex)

    def test_negatives(self):
        for subject in ("prefix the thing", "bugle call", "suffix handling",
                        "debug logging", "feat: fixture helpers",
                        "affix labels", "reverted? no: reverting",
                        "fixup! feat: x", "fixtures only", "rename fix_parser",
                        "debugs the loader"):
            self.assertIsNone(self.regex.search(subject), msg=subject)


class TestLabels(unittest.TestCase):
    """FR-003: nearest-rank quartiles, ties stable."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_signals_module()

    def test_quartiles_over_a_known_population(self):
        self.assertEqual(self.mod.quartile_labels([1, 1, 1, 1, 4, 4, 5]),
                         ["low", "low", "low", "low", "high", "high", "top"])

    def test_equal_values_get_equal_labels(self):
        labels = self.mod.quartile_labels([3, 7, 3, 9, 7, 1, 3, 7])
        by_value = {}
        for value, label in zip([3, 7, 3, 9, 7, 1, 3, 7], labels):
            by_value.setdefault(value, set()).add(label)
        self.assertTrue(all(len(s) == 1 for s in by_value.values()), by_value)

    def test_all_equal_is_all_low_and_none_passes_through(self):
        # no spread among the non-zero values (q1 == q3): `mid`, like the few-values rule
        self.assertEqual(self.mod.quartile_labels([2, 2, 2, 2]), ["mid"] * 4)
        self.assertEqual(self.mod.quartile_labels([0, 2, 2, 2, 2]), ["low"] + ["mid"] * 4)
        # ... but a value above that plateau still ranks `top`
        self.assertEqual(self.mod.quartile_labels([1] * 8 + [9]), ["mid"] * 8 + ["top"])
        self.assertEqual(self.mod.quartile_labels([2, 2, 2]), ["mid"] * 3)  # < 4 non-zero
        self.assertEqual(self.mod.quartile_labels([None, 1, 2, 3, 4]),
                         [None, "low", "mid", "high", "top"])
        self.assertEqual(self.mod.quartile_labels([]), [])

    def test_zeros_are_low_and_quartiles_run_over_the_non_zero_values(self):
        values = [0] * 30 + [1, 2, 3, 9]
        labels = self.mod.quartile_labels(values)
        self.assertEqual(labels[:30], ["low"] * 30)
        self.assertEqual(labels[30:], ["low", "mid", "high", "top"])

    def test_fewer_than_four_non_zero_values_are_mid_never_top(self):
        self.assertEqual(self.mod.quartile_labels([0] * 50 + [1]), ["low"] * 50 + ["mid"])
        self.assertEqual(self.mod.quartile_labels([0, 0, 5, 1, None]),
                         ["low", "low", "mid", "mid", None])


class TestTrajectory(StandardRepoCase):
    """FR-001 / FR-003 / FR-007 / FR-008 on the standard fixture."""

    def test_population_excludes_vendored_lockfiles_and_deleted_and_renamed_away(self):
        paths = set(self.rows())
        self.assertEqual(paths, {"docs/a.md", "docs/b.md", "docs/c.md", "src/hot.py",
                                 "src/new_name.py", "src/one_fix.py", "src/stable.py"})

    def test_counts_are_exact(self):
        rows = self.rows()
        hot = rows["src/hot.py"]
        self.assertEqual((hot["commits"], hot["fixes"], hot["fix_rate"]), (5, 3, 0.6))
        self.assertEqual((hot["authors"], hot["top_share"]), (2, 0.8))
        self.assertEqual((hot["age_days"], hot["stale_days"]), (335, 61))
        stable = rows["src/stable.py"]
        self.assertEqual((stable["age_days"], stable["stale_days"]), (335, 335))
        self.assertEqual((stable["commits"], stable["authors"], stable["top_share"]),
                         (1, 1, 1.0))
        self.assertEqual(rows["docs/c.md"]["stale_days"], 0)
        self.assertEqual(rows["src/one_fix.py"]["age_days"], 122)

    def test_rename_history_lands_on_the_new_path(self):
        new = self.rows()["src/new_name.py"]
        self.assertEqual((new["commits"], new["fixes"]), (4, 1))
        self.assertEqual((new["age_days"], new["stale_days"]), (335, 183))

    def test_labels_and_risk(self):
        rows = self.rows()
        self.assertEqual(rows["src/hot.py"]["labels"]["commits"], "top")
        # three non-zero fix rates (< 4): all `mid`, never `top`
        self.assertEqual(rows["src/hot.py"]["labels"]["fix_rate"], "mid")
        self.assertEqual(rows["src/hot.py"]["risk"], "top")
        self.assertEqual(rows["src/new_name.py"]["risk"], "high")
        self.assertEqual(rows["docs/c.md"]["risk"], "high")
        self.assertEqual(rows["docs/a.md"]["labels"],
                         rows["docs/b.md"]["labels"])  # ties
        self.assertEqual(rows["docs/a.md"]["labels"]["stale_days"], "high")
        self.assertIsNone(rows["docs/a.md"]["labels"]["fan_in"])
        self.assertIsNone(rows["docs/a.md"]["fan_in"])
        self.assertEqual(rows["docs/a.md"]["structure"], "unknown")

    def test_few_commits_force_fix_rate_low(self):
        one = self.rows()["src/one_fix.py"]
        self.assertEqual((one["commits"], one["fix_rate"]), (1, 1.0))
        self.assertEqual(one["labels"]["fix_rate"], "low")
        self.assertEqual(one["risk"], "low")

    def test_sort_order(self):
        paths = [f["path"] for f in self.hotspots()["files"]]
        self.assertEqual(paths, ["src/hot.py", "src/new_name.py", "docs/c.md",
                                 "src/one_fix.py", "docs/a.md", "docs/b.md",
                                 "src/stable.py"])

    def test_top_truncates(self):
        paths = [f["path"] for f in self.hotspots("--top", "2")["files"]]
        self.assertEqual(paths, ["src/hot.py", "src/new_name.py"])

    def test_positional_paths_filter_rows_not_labels(self):
        full = self.rows()
        filtered = self.rows("src/hot.py", "docs")
        self.assertEqual(set(filtered), {"src/hot.py", "docs/a.md", "docs/b.md",
                                         "docs/c.md"})
        for path, row in filtered.items():
            self.assertEqual(row, full[path], msg=path)

    def test_scope_changes_the_population(self):
        scoped = self.rows("--scope", "docs")
        self.assertEqual(set(scoped), {"docs/a.md", "docs/b.md", "docs/c.md"})
        self.assertEqual(scoped["docs/a.md"]["labels"]["stale_days"], "mid")
        self.assertNotEqual(scoped["docs/a.md"]["labels"],
                            self.rows()["docs/a.md"]["labels"])

    def test_diff_filters_to_changed_and_uncommitted_files(self):
        paths = {f["path"] for f in self.hotspots("--diff", "HEAD~2")["files"]}
        self.assertEqual(paths, {"docs/c.md", "src/hot.py"})
        target = self.root / "src" / "stable.py"
        original = target.read_text()
        target.write_text("changed\n")
        try:
            paths = {f["path"] for f in self.hotspots("--diff", "HEAD~1")["files"]}
        finally:
            target.write_text(original)
        self.assertEqual(paths, {"docs/c.md", "src/stable.py"})
        self.signals("hotspots", "--repo", self.root, "--diff", "no-such-rev",
                     rc=USAGE)

    def test_json_shape(self):
        payload = self.hotspots()
        self.assertEqual(payload["version"], 1)
        self.assertIs(payload["available"], True)
        self.assertEqual(payload["head"], self.repo.git("rev-parse", "HEAD").strip())
        self.assertEqual(payload["trajectory"],
                         {"available": True, "reason": None, "commits_scanned": 11})
        self.assertEqual(payload["structure"], {
            "available": True, "reason": None, "languages": ["python"],
            "files_scanned": 4})
        self.assertEqual(set(payload["files"][0]), {
            "path", "commits", "fixes", "fix_rate", "age_days", "stale_days",
            "authors", "top_share", "fan_in", "fan_out", "unresolved", "structure",
            "labels", "risk"})
        self.assertEqual(set(payload["files"][0]["labels"]), {
            "commits", "fix_rate", "age_days", "stale_days", "authors", "top_share",
            "fan_in", "fan_out"})

    def test_table(self):
        proc = self.signals("hotspots", "--repo", self.root)
        self.assertEqual(proc.stderr, "")
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0].split(), ["path", "commits", "fix%", "age", "stale",
                                            "auth", "top%", "in", "out", "risk"])
        self.assertEqual(lines[1].split(),
                         ["src/hot.py", "5", "60", "335", "61", "2", "80", "0", "0",
                          "top"])
        docs_a = next(line for line in lines if line.startswith("docs/a.md"))
        self.assertEqual(docs_a.split()[-3:], ["-", "-", "low"])  # no adapter

        self.assertEqual(len(lines), 8)

    def test_default_repo_is_the_cwd_toplevel(self):
        proc = self.signals("hotspots", "--json", cwd=self.root / "src")
        self.assertEqual(len(json.loads(proc.stdout)["files"]), 7)


class TestWindow(SignalsCase):
    """The window edge is inclusive; 'now' is HEAD's committer time."""

    def test_window_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = FixtureRepo(Path(tmp) / "r")
            repo.commit("fix: old", ts(2019, 12, 31, 23, 59, 59), writes={"b.txt": "b"})
            repo.commit("fix: edge", ts(2020, 1, 1), writes={"a.txt": "a"})
            repo.commit("head", ts(2020, 7, 1), writes={"c.txt": "c"})
            rows = {f["path"]: f for f in self.signals_json(
                "hotspots", "--repo", repo.path, "--window", "6")["files"]}
            self.assertEqual((rows["a.txt"]["commits"], rows["a.txt"]["fixes"]), (1, 1))
            self.assertEqual((rows["b.txt"]["commits"], rows["b.txt"]["fixes"]), (0, 0))
            self.assertEqual(rows["b.txt"]["age_days"], 182)
            self.assertEqual(rows["b.txt"]["authors"], 0)
            rows = {f["path"]: f for f in self.signals_json(
                "hotspots", "--repo", repo.path, "--window", "7")["files"]}
            self.assertEqual(rows["b.txt"]["commits"], 1)


# ---------------------------------------------------------------------------
# T007 — structure: adapters, graph, blast
# ---------------------------------------------------------------------------

TSCONFIG = """{
  // project config: comments and trailing commas are legal here
  "compilerOptions": {
    "baseUrl": ".",
    /* aliases */
    "paths": { "@lib/*": ["web/lib/*"], },
  },
}
"""

STRUCTURE_FILES = {
    # TS / JS
    "tsconfig.json": TSCONFIG,
    "web/lib/util.ts": "export const u = 1;\n",
    "web/lib/index.ts": "export * from './util';\n",
    "web/lib/aliased.ts": "export const only = 'reached through the alias only';\n",
    "web/app.ts": (
        "import { u } from './lib';\n"
        "import x from './helper.js';\n"
        "import '@lib/aliased';\n"
        "import React from 'react';\n"
        "// import y from './commented';\n"
        "const z = require('./legacy');\n"
        "const lazy = () => import('./lazy');\n"
        "import {\n  a,\n  b,\n} from './lib/util';\n"
    ),
    "web/helper.ts": "export default 1;\n",
    "web/legacy.js": "module.exports = {};\n",
    "web/lazy.tsx": "export const L = 1;\n",
    "web/broken.ts": "import a from './missing';\n",
    "cyc/x.ts": "import { y } from './y';\n",
    "cyc/y.ts": "import { x } from './x';\n",
    # Python
    "src/pkg/__init__.py": "from .core import run\n",
    "src/pkg/core.py": "import os\nfrom . import helpers\n",
    "src/pkg/helpers.py": "# import pkg.core\nX = 1\n",
    "tools/cli.py": "import pkg\nfrom pkg.core import run\n",
    "tools/bad.py": "from .missing import x\n",
    "lib/shared.py": "from pkg import helpers\n",
    "top.py": "import tools.cli\n",
    "chain/a.py": "A = 1\n",
    "chain/b.py": "from . import a\n",
    "chain/c.py": "from . import b\n",
    # Go
    "go.mod": "module example.com/svc\n\ngo 1.22\n",
    "cmd/main.go": (
        "package main\n\nimport (\n\t\"fmt\"\n\t\"example.com/svc/internal/store\"\n"
        "\talias \"example.com/svc/internal/util\"\n)\n"
    ),
    "cmd/other.go": "package main\n\nimport \"example.com/svc/internal/missing\"\n",
    "internal/store/store.go": "package store\n",
    "internal/store/db.go": "package store\n",
    "internal/store/store_test.go": "package store\n",
    "internal/util/util.go": "package util\n\nimport \"example.com/svc/internal/store\"\n",
    # no adapter
    "app/model.rb": "require 'thing'\n",
}


class TestStructure(SignalsCase):
    """FR-004: adapters, fan-in/out, partial/unknown, blast."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        cls.repo = FixtureRepo(cls.root)
        cls.repo.commit("initial import", ts(2020, 1, 1), writes=STRUCTURE_FILES)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def rows(self, *args):
        payload = self.signals_json("hotspots", "--repo", self.root, "--top", "100",
                                    *args)
        return {f["path"]: f for f in payload["files"]}

    def blast(self, *args):
        return self.signals_json("blast", "--repo", self.root, *args)

    def test_structure_summary(self):
        payload = self.signals_json("hotspots", "--repo", self.root)
        structure = payload["structure"]
        self.assertIs(structure["available"], True)
        self.assertEqual(structure["languages"], ["go", "python", "ts-js"])
        self.assertEqual(structure["files_scanned"], 26)

    def test_ts_js_resolution(self):
        rows = self.rows()
        # index, helper, aliased (tsconfig alias), legacy, lazy, util (multi-line import)
        self.assertEqual(rows["web/app.ts"]["fan_out"], 6)
        self.assertEqual(rows["web/app.ts"]["structure"], "ok")
        self.assertEqual(rows["web/lib/util.ts"]["fan_in"], 2)  # index.ts + app.ts
        self.assertEqual(rows["web/lib/index.ts"]["fan_in"], 1)
        self.assertEqual(rows["web/lib/aliased.ts"]["fan_in"], 1)  # commented tsconfig
        self.assertEqual(rows["web/helper.ts"]["fan_in"], 1)  # './helper.js' -> .ts
        self.assertEqual(rows["web/legacy.js"]["fan_in"], 1)  # require()
        self.assertEqual(rows["web/lazy.tsx"]["fan_in"], 1)  # import()

    def test_unresolved_relative_import_is_partial(self):
        broken = self.rows()["web/broken.ts"]
        self.assertEqual((broken["structure"], broken["unresolved"], broken["fan_out"]),
                         ("partial", 1, 0))
        self.assertEqual(self.rows()["tools/bad.py"]["structure"], "partial")
        self.assertEqual(self.rows()["cmd/other.go"]["unresolved"], 1)

    def test_tsconfig_that_does_not_parse_skips_aliases_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = FixtureRepo(Path(tmp) / "r")
            repo.commit("one", ts(2020, 1, 1), writes={
                "tsconfig.json": "{ this is not json",
                "a.ts": "import '@lib/b';\nimport './b';\n", "b.ts": "export {};\n"})
            proc = self.signals("hotspots", "--repo", repo.path, "--json")
            self.assertEqual(proc.stderr, "")
            rows = {f["path"]: f for f in json.loads(proc.stdout)["files"]}
            self.assertEqual((rows["a.ts"]["fan_out"], rows["a.ts"]["structure"]),
                             (1, "ok"))

    def test_python_resolution(self):
        rows = self.rows()
        self.assertEqual(rows["src/pkg/core.py"]["fan_in"], 2)  # __init__ + tools/cli
        self.assertEqual(rows["src/pkg/helpers.py"]["fan_in"], 2)  # core + lib/shared
        self.assertEqual(rows["src/pkg/__init__.py"]["fan_in"], 1)  # `import pkg`
        self.assertEqual(rows["tools/cli.py"]["fan_in"], 1)  # top.py, repo root
        self.assertEqual(rows["tools/cli.py"]["fan_out"], 2)
        self.assertEqual(rows["src/pkg/core.py"]["fan_out"], 1)  # os is external

    def test_go_resolution(self):
        rows = self.rows()
        self.assertEqual(rows["cmd/main.go"]["fan_out"], 3)  # store.go, db.go, util.go
        self.assertEqual(rows["internal/store/store.go"]["fan_in"], 2)
        self.assertEqual(rows["internal/store/db.go"]["fan_in"], 2)
        self.assertEqual(rows["internal/store/store_test.go"]["fan_in"], 0)

    def test_no_adapter_is_unknown_with_null_counts(self):
        model = self.rows()["app/model.rb"]
        self.assertEqual(model["structure"], "unknown")
        self.assertEqual((model["fan_in"], model["fan_out"], model["unresolved"]),
                         (None, None, None))
        self.assertIsNone(model["labels"]["fan_in"])

    def test_fan_labels_are_populated(self):
        rows = self.rows()
        # non-zero fan-ins are 1s and 2s: the 2s are the top quarter's value, so `high`
        self.assertEqual(rows["web/lib/util.ts"]["labels"]["fan_in"], "high")
        self.assertEqual(rows["web/app.ts"]["labels"]["fan_out"], "top")
        self.assertEqual(rows["chain/c.py"]["labels"]["fan_in"], "low")

    def test_blast_follows_the_chain_and_excludes_seeds(self):
        blast = self.blast("chain/a.py")["blast"]
        self.assertEqual(blast, {"size": 2, "files": ["chain/b.py", "chain/c.py"],
                                 "truncated": False, "by_dir": {"chain": 2},
                                 "unknown_seeds": []})

    def test_blast_terminates_on_a_cycle(self):
        blast = self.blast("cyc/x.ts")["blast"]
        self.assertEqual((blast["size"], blast["files"]), (1, ["cyc/y.ts"]))

    def test_blast_limit_truncates(self):
        blast = self.blast("chain/a.py", "--limit", "1")["blast"]
        self.assertEqual((blast["size"], blast["files"], blast["truncated"]),
                         (2, ["chain/b.py"], True))

    def test_blast_reports_unknown_seeds(self):
        blast = self.blast("app/model.rb", "nope/missing.py", "chain/a.py")["blast"]
        self.assertEqual(blast["unknown_seeds"], ["app/model.rb", "nope/missing.py"])
        self.assertEqual(blast["size"], 2)

    def test_blast_table(self):
        proc = self.signals("blast", "chain/a.py", "--repo", self.root)
        self.assertEqual(proc.stderr, "")
        self.assertIn("blast radius: 2 files", proc.stdout)
        self.assertIn("chain/c.py", proc.stdout)

    def test_hotspots_blast_attaches_the_radius_of_the_selected_rows(self):
        payload = self.signals_json("hotspots", "--repo", self.root, "chain/a.py",
                                    "--blast")
        self.assertEqual(payload["blast"]["files"], ["chain/b.py", "chain/c.py"])
        table = self.signals("hotspots", "--repo", self.root, "chain/a.py", "--blast")
        self.assertIn("blast radius: 2 files", table.stdout)

    def test_structure_works_on_a_shallow_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "shallow"
            result = subprocess.run(
                ["git", "clone", "-q", "--depth", "1", f"file://{self.root}", str(dst)],
                capture_output=True, text=True)
            if result.returncode != 0:
                raise unittest.SkipTest(f"shallow clone failed: {result.stderr}")
            payload = self.signals_json("hotspots", "--repo", dst, "chain")
            self.assertIs(payload["available"], True)
            self.assertEqual(payload["trajectory"]["reason"], "shallow")
            rows = {f["path"]: f for f in payload["files"]}
            self.assertEqual(rows["chain/a.py"]["fan_in"], 1)
            self.assertIsNone(rows["chain/a.py"]["commits"])
            self.assertIsNone(rows["chain/a.py"]["risk"])
            self.assertEqual(self.blast_at(dst)["blast"]["size"], 2)

    def blast_at(self, repo):
        return self.signals_json("blast", "chain/a.py", "--repo", repo)


# ---------------------------------------------------------------------------
# T008 — --by-dir, suspects
# ---------------------------------------------------------------------------


class TestByDir(SignalsCase):
    """FR-005: directories union distinct commits; labels are the max."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        repo = cls.repo = FixtureRepo(cls.root)
        repo.commit("fix: five files at once", ts(2020, 1, 1), writes={
            "d1/a.py": "A = 1\n", "d1/b.py": "from . import a\n", "d1/c.py": "C\n",
            "d1/d.py": "D\n", "d1/e.py": "E\n", "README.md": "r\n"})
        repo.commit("feat: a", ts(2020, 2, 1), writes={"d1/a.py": "A = 2\n"})
        repo.commit("fix: x", ts(2020, 3, 1), writes={
            "d2/x.py": "X\n", "d2/y.py": "from d1 import a\n"})
        repo.commit("docs", ts(2020, 4, 1), writes={"deep/er/z.py": "Z\n"})

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def dirs(self, *args):
        payload = self.signals_json("hotspots", "--repo", self.root, *args)
        self.assertEqual(payload["files"], [])
        return {d["dir"]: d for d in payload["dirs"]}

    def test_a_multi_file_commit_counts_once(self):
        d1 = self.dirs("--by-dir", "1")["d1"]
        self.assertEqual((d1["files"], d1["commits"], d1["fixes"], d1["fix_rate"]),
                         (5, 2, 1, 0.5))

    def test_fan_in_is_the_importer_union_minus_own_files(self):
        dirs = self.dirs("--by-dir", "1")
        self.assertEqual(dirs["d1"]["fan_in"], 1)  # d2/y.py; d1/b.py is internal
        self.assertEqual(dirs["d2"]["fan_in"], 0)
        self.assertIsNone(dirs["."]["fan_in"])  # README.md only: no adapter

    def test_labels_are_the_max_over_member_files(self):
        files = self.signals_json("hotspots", "--repo", self.root)["files"]
        dirs = self.dirs("--by-dir", "1")
        rank = {"low": 0, "mid": 1, "high": 2, "top": 3}
        for name in ("commits", "fix_rate", "stale_days"):
            members = [f["labels"][name] for f in files if f["path"].startswith("d1/")]
            self.assertEqual(dirs["d1"]["labels"][name],
                             max(members, key=rank.get), msg=name)
        self.assertEqual(dirs["d1"]["risk"],
                         max((f["risk"] for f in files if f["path"].startswith("d1/")),
                             key=rank.get))

    def test_depth_and_root_files(self):
        self.assertIn("deep", self.dirs("--by-dir", "1"))
        dirs = self.dirs("--by-dir", "2")
        self.assertIn("deep/er", dirs)
        self.assertIn(".", dirs)
        self.assertEqual(dirs["d1"]["files"], 5)

    def test_by_dir_respects_the_row_filter_and_top(self):
        self.assertEqual(set(self.dirs("--by-dir", "1", "d2")), {"d2"})
        self.assertEqual(len(self.dirs("--by-dir", "1", "--top", "1")), 1)

    def test_by_dir_table(self):
        proc = self.signals("hotspots", "--repo", self.root, "--by-dir", "1")
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0].split(), ["dir", "files", "commits", "fix%", "in",
                                            "risk"])
        self.assertTrue(any(line.split()[:3] == ["d1", "5", "2"] for line in lines))


class TestSuspects(SignalsCase):
    """FR-011: fix_rate x min(1, commits/3) x recency x proximity."""

    HEAD = ts(2020, 12, 1)

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        repo = cls.repo = FixtureRepo(cls.root)
        sib_last = cls.HEAD - 200 * 86400
        for i in range(4):  # 4 fixes, last one 200 days before HEAD
            repo.commit(f"fix: sib {i}", sib_last - (3 - i) * 86400,
                        writes={"svc/sib.py": f"S = {i}\n"})
        for i in range(5):  # unrelated and hot: must not be a candidate
            repo.commit(f"fix: far {i}", sib_last + i, writes={"far/far.py": f"{i}\n"})
        repo.commit("feat: nbr", cls.HEAD - 3000, writes={
            "other/nbr.py": "from svc import core\n"})
        repo.commit("feat: nbr 2", cls.HEAD - 2000, writes={
            "other/nbr.py": "from svc import core\nN = 2\n"})
        for i in range(3):  # 3 fixes, fresh
            repo.commit(f"fix: core {i}", cls.HEAD - 1000 + i,
                        writes={"svc/core.py": f"C = {i}\n"})
        repo.commit("fix: nbr", cls.HEAD, writes={
            "other/nbr.py": "from svc import core\nN = 3\n"})

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def suspects(self, *args):
        payload = self.signals_json("suspects", "svc/core.py", "--repo", self.root,
                                    *args)
        self.assertIs(payload["available"], True)
        return payload["suspects"]

    def test_order_and_scores(self):
        suspects = self.suspects()
        self.assertEqual([s["path"] for s in suspects],
                         ["svc/core.py", "other/nbr.py", "svc/sib.py"])
        self.assertEqual([s["score"] for s in suspects], [1.0, 0.25, 0.16])
        self.assertEqual([s["proximity"] for s in suspects], [1.0, 0.75, 0.5])
        self.assertEqual(set(suspects[0]), {"path", "score", "proximity", "fix_rate",
                                            "commits", "stale_days", "fan_in"})
        self.assertEqual(suspects[0]["fan_in"], 1)
        self.assertEqual(suspects[2]["stale_days"], 200)

    def test_top(self):
        self.assertEqual([s["path"] for s in self.suspects("--top", "1")],
                         ["svc/core.py"])

    def test_table(self):
        proc = self.signals("suspects", "svc/core.py", "--repo", self.root)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0].split(), ["path", "score", "prox", "fix%", "commits",
                                            "stale", "in"])
        self.assertEqual(lines[1].split()[:2], ["svc/core.py", "1.00"])

    def test_suspects_need_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "shallow"
            result = subprocess.run(
                ["git", "clone", "-q", "--depth", "1", f"file://{self.root}", str(dst)],
                capture_output=True, text=True)
            if result.returncode != 0:
                raise unittest.SkipTest(f"shallow clone failed: {result.stderr}")
            payload = self.signals_json("suspects", "svc/core.py", "--repo", dst)
            self.assertEqual((payload["available"], payload["reason"]),
                             (False, "shallow"))


# ---------------------------------------------------------------------------
# T012 — skill-prose drift guard
# ---------------------------------------------------------------------------

SKILLS_DIR = TESTS_DIR.parent / "skills"
_PLACEHOLDER_VALUES = {"<repo>": ".", "<base>": "HEAD~1"}


def prose_invocations():
    """(skill, line, argv) for every `scripts/signals.py` invocation in a SKILL.md."""
    import shlex

    found = []
    for skill in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for number, line in enumerate(skill.read_text(encoding="utf-8").splitlines(), 1):
            if "scripts/signals.py" not in line:
                continue
            marker = 'signals.py"'
            if marker not in line:
                continue
            tail = line.split(marker, 1)[1].split("`", 1)[0]
            argv = [_PLACEHOLDER_VALUES.get(tok, "x") if re.fullmatch(r"<[^>]+>", tok)
                    else tok for tok in shlex.split(tail)]
            found.append((f"{skill.parent.name}/SKILL.md:{number}", argv))
    return found


class TestProseDrift(unittest.TestCase):
    """FR-014 / SC-002: every invocation the skills quote parses with build_parser()."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_signals_module()

    def parses(self, argv):
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            try:
                self.mod.build_parser().parse_args(argv)
            except SystemExit:
                return False
        return True

    def test_the_guard_rejects_a_broken_flag(self):
        self.assertFalse(self.parses(["hotspots", "--by-dirr", "2", "--json"]))
        self.assertFalse(self.parses(["suspects", "--json"]))
        self.assertFalse(self.parses(["hotspots", "--by", "2"]))  # no abbreviations
        self.assertTrue(self.parses(["hotspots", "--repo", ".", "x", "--by-dir", "2",
                                     "--blast", "--json"]))

    def test_every_skill_invocation_parses(self):
        invocations = prose_invocations()
        self.assertGreaterEqual(len(invocations), 5, invocations)
        for where, argv in invocations:
            with self.subTest(where=where, argv=argv):
                self.assertTrue(self.parses(argv), f"{where}: {argv}")


# ---------------------------------------------------------------------------
# T014 / T015 — privacy, reproducibility, no-write
# ---------------------------------------------------------------------------


class TestCrossCutting(StandardRepoCase):
    def all_outputs(self):
        outputs = []
        for argv in (["hotspots"], ["blast", "src/hot.py"], ["suspects", "src/hot.py"]):
            for mode in ([], ["--json"]):
                proc = self.signals(*argv, "--repo", self.root, *mode)
                outputs.append(proc.stdout + proc.stderr)
        return outputs

    def test_privacy_no_author_identity_in_any_output(self):
        for output in self.all_outputs():
            for needle in ("Fixture Author", "fixture@example.test", "example.test",
                           "Alice", "alice"):
                self.assertNotIn(needle, output)

    def test_reproducible_across_runs_and_mtime_changes(self):
        first = self.signals("hotspots", "--repo", self.root, "--json").stdout
        second = self.signals("hotspots", "--repo", self.root, "--json").stdout
        self.assertEqual(first, second)
        later = datetime.now().timestamp() + 1000
        for dirpath, _, filenames in os.walk(self.root):
            if ".git" in Path(dirpath).parts:
                continue
            for name in filenames:
                os.utime(os.path.join(dirpath, name), (later, later))
        third = self.signals("hotspots", "--repo", self.root, "--json").stdout
        self.assertEqual(first, third)

    def test_writes_nothing(self):
        def snapshot():
            state = {}
            for dirpath, dirnames, filenames in os.walk(self.root):
                for name in dirnames + filenames:
                    full = os.path.join(dirpath, name)
                    state[full] = os.lstat(full).st_mtime_ns
            return state

        before = snapshot()
        self.assertIn(str(self.root / ".claude" / "shipgate.md"), before)
        self.all_outputs()
        self.signals("hotspots", "--repo", self.root, "--diff", "HEAD~1", "--json")
        self.assertEqual(snapshot(), before)


# ---------------------------------------------------------------------------
# Review round 1 — hardening
# ---------------------------------------------------------------------------


def shallow_clone(source: Path, dst: Path, *extra):
    result = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", *extra, f"file://{source}", str(dst)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise unittest.SkipTest(f"shallow clone failed: {result.stderr}")
    return dst


class TestReviewRound1(SignalsCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def rows(self, repo, *args):
        payload = self.signals_json("hotspots", "--repo", repo, "--top", "100", *args)
        return {f["path"]: f for f in payload["files"]}

    # H1 — never read a symlink, device or FIFO
    def test_symlinks_devices_and_fifos_are_never_read(self):
        if not hasattr(os, "mkfifo") or not os.path.exists("/dev/zero"):
            raise unittest.SkipTest("needs POSIX /dev/zero and mkfifo")
        repo = FixtureRepo(self.tmp / "r")
        os.symlink("/dev/zero", repo.path / "evil.ts")
        repo.git("add", "evil.ts")
        repo.commit("one", ts(2020, 1, 1), writes={
            "pipe.ts": "export {};\n", "ok.ts": "import './pipe';\n"})
        (repo.path / "pipe.ts").unlink()
        os.mkfifo(repo.path / "pipe.ts")
        proc = subprocess.run(
            [sys.executable, str(SIGNALS), "hotspots", "--repo", str(repo.path),
             "--json"], capture_output=True, text=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stderr), (OK, ""))
        rows = {f["path"]: f for f in json.loads(proc.stdout)["files"]}
        for path in ("evil.ts", "pipe.ts"):
            self.assertEqual(rows[path]["structure"], "unknown", msg=path)
            self.assertIsNone(rows[path]["unresolved"], msg=path)
        self.assertEqual(rows["ok.ts"]["structure"], "ok")

    def test_read_text_caps_the_bytes_read(self):
        mod = load_signals_module()
        (self.tmp / "big.ts").write_bytes(b"x" * (mod.MAX_SCAN_BYTES + 1))
        (self.tmp / "small.ts").write_bytes(b"ok \xff\n")
        self.assertIsNone(mod._read_text(self.tmp, "big.ts"))
        self.assertEqual(mod._read_text(self.tmp, "small.ts"), "ok �\n")

    # H2 — exact tsconfig aliases and the catch-all
    def test_an_exact_alias_does_not_match_by_prefix(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={
            "tsconfig.json": '{"compilerOptions": {"paths": '
                             '{"config": ["src/config/index.ts"]}}}',
            "src/config/index.ts": "export {};\n",
            "a.ts": "import x from 'config-lib';\n",
            "b.ts": "import c from 'config';\n"})
        rows = self.rows(repo.path)
        self.assertEqual((rows["a.ts"]["fan_out"], rows["a.ts"]["structure"]), (0, "ok"))
        self.assertEqual((rows["b.ts"]["fan_out"], rows["b.ts"]["structure"]), (1, "ok"))

    def test_an_unresolved_catch_all_alias_is_external(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={
            "tsconfig.json": '{"compilerOptions": {"paths": {"*": ["types/*"]}}}',
            "types/shared.ts": "export {};\n",
            "a.ts": "import React from 'react';\nimport s from 'shared';\n"})
        a = self.rows(repo.path)["a.ts"]
        self.assertEqual((a["structure"], a["unresolved"], a["fan_out"]), ("ok", 0, 1))

    # H3 — --diff on a shallow clone
    def diverged_source(self):
        source = FixtureRepo(self.tmp / "src")
        source.commit("one", ts(2020, 1, 1), writes={"a.py": "A = 1\n", "b.py": "B\n"})
        source.git("checkout", "-q", "-b", "other")
        source.commit("other", ts(2020, 2, 1), writes={"b.py": "B = 2\n"})
        source.git("checkout", "-q", "main")
        source.commit("two", ts(2020, 3, 1), writes={"a.py": "A = 2\n"})
        return source

    def test_diff_on_a_shallow_clone_falls_back_to_two_dot(self):
        source = self.diverged_source()
        dst = shallow_clone(source.path, self.tmp / "shallow", "--no-single-branch")
        proc = self.signals("hotspots", "--repo", dst, "--diff", "origin/other",
                            "--json")
        self.assertEqual(proc.stderr, "")
        paths = {f["path"] for f in json.loads(proc.stdout)["files"]}
        self.assertEqual(paths, {"a.py", "b.py"})
        self.signals("hotspots", "--repo", dst, "--diff", "no-such-rev", rc=USAGE)
        self.signals("hotspots", "--repo", dst, "--diff", "--output=x", rc=USAGE)
        self.assertFalse((dst / "x").exists())

    # H4 — --top does not truncate a --diff
    def test_diff_shows_every_changed_file_unless_top_is_given(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={"base.txt": "b\n"})
        repo.commit("many", ts(2020, 2, 1),
                    writes={f"f{i:02d}.txt": f"{i}\n" for i in range(25)})
        self.assertEqual(len(self.signals_json(
            "hotspots", "--repo", repo.path, "--diff", "HEAD~1")["files"]), 25)
        self.assertEqual(len(self.signals_json(
            "hotspots", "--repo", repo.path, "--diff", "HEAD~1", "--top", "5")["files"]),
            5)
        self.assertEqual(len(self.signals_json(
            "hotspots", "--repo", repo.path)["files"]), 20)

    # H6 — a leading `./` is a prefix, not a character set
    def test_exclude_strips_only_a_leading_dot_slash(self):
        mod = load_signals_module()
        self.assertTrue(mod.is_excluded(".github/x.py", [".github/"]))
        self.assertTrue(mod.is_excluded("a/.github/x.py", [".github/"]))
        self.assertFalse(mod.is_excluded("github/x.py", [".github/"]))
        self.assertFalse(mod.is_excluded("src/github/x.py", [".github/"]))
        self.assertFalse(mod.is_excluded("cfg/env", [".env"]))
        self.assertTrue(mod.is_excluded("cfg/.env", [".env"]))
        self.assertTrue(mod.is_excluded("src/gen/x.py", ["./gen/"]))

    # H7 — out-of-range windows
    def test_an_out_of_range_window_flag_is_a_usage_error(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        for value in ("1201", "99999999"):
            proc = self.signals("hotspots", "--repo", repo.path, "--window", value,
                                rc=USAGE)
            self.assertNotIn("Traceback", proc.stderr)
        self.signals_json("hotspots", "--repo", repo.path, "--window", "1200")

    def test_an_out_of_range_window_in_the_file_falls_back_to_the_default(self):
        mod = load_signals_module()
        self.assertEqual(mod.parse_code_signals("## Code signals\n- Window: `99999999`\n"),
                         {})
        self.assertEqual(mod.parse_code_signals("## Code signals\n- Window: `1200`\n"),
                         {"window_months": 1200})

    # H8 — config.source comes from load_config's source map
    def test_effective_config_takes_the_source_from_load_config(self):
        mod = load_signals_module()
        args = mod.build_parser().parse_args(["hotspots"])
        cfg = mod.effective_config({"window_months": 3}, {"window_months": "shipgate.md"},
                                   args)
        self.assertEqual(cfg.source["window_months"], "shipgate.md")
        self.assertEqual(cfg.source["fix_pattern"], "default")

    # H9 — CR in a subject or a path
    def test_carriage_returns_do_not_split_log_or_path_streams(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "A = 1\n"})
        repo.write("a.py", "A = 2\n")
        repo.git("add", "a.py")
        message = self.tmp / "msg"
        message.write_bytes(b"chore: tidy\rfix the crash\n")
        repo.git("commit", "-q", "--cleanup=verbatim", "-F", str(message),
                 when=ts(2020, 2, 1))
        cr_name = "cr\rname.py"
        try:
            (repo.path / cr_name).write_text("C = 1\n")
        except OSError:
            cr_name = None
        if cr_name is not None:
            repo.git("add", cr_name)
            repo.commit("add cr", ts(2020, 3, 1))
        payload = self.signals_json("hotspots", "--repo", repo.path)
        expected = 3 if cr_name else 2
        self.assertEqual(payload["trajectory"]["commits_scanned"], expected)
        rows = {f["path"]: f for f in payload["files"]}
        self.assertEqual((rows["a.py"]["commits"], rows["a.py"]["fixes"]), (2, 1))
        if cr_name is not None:
            self.assertEqual(rows[cr_name]["commits"], 1)

    # H10 — fenced code blocks inside the config section
    def test_a_heading_inside_a_fence_does_not_end_the_section(self):
        mod = load_signals_module()
        text = ("## Code signals\n\n```sh\n# not a heading\n- Window: `99`\n```\n\n"
                "~~~\n## nor this\n~~~\n- Window: `18`\n\n## Next\n- Exclude: `x/`\n")
        self.assertEqual(mod.parse_code_signals(text), {"window_months": 18})

    # H12 — table mode says which half is missing
    def test_table_notes_a_missing_half(self):
        source = FixtureRepo(self.tmp / "src")
        source.commit("one", ts(2020, 1, 1), writes={"a.py": "A = 1\n"})
        source.commit("two", ts(2020, 2, 1), writes={"a.py": "A = 2\n"})
        dst = shallow_clone(source.path, self.tmp / "shallow")
        lines = self.signals("hotspots", "--repo", dst).stdout.splitlines()
        self.assertEqual(lines[0], "trajectory unavailable: shallow")
        self.assertEqual(lines[1].split()[0], "path")
        docs = FixtureRepo(self.tmp / "docs")
        docs.commit("one", ts(2020, 1, 1), writes={"a.md": "a\n"})
        lines = self.signals("hotspots", "--repo", docs.path).stdout.splitlines()
        self.assertEqual(lines[0], "structure unavailable: no-adapter")
        self.assertEqual(lines[1].split()[0], "path")

    # H13 — a plain parent directory is not an umbrella
    def test_a_parent_that_is_not_a_git_tree_is_not_read(self):
        parent = self.tmp / "home"
        repo = FixtureRepo(parent / "repo")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "1\n"})
        target = parent / ".claude" / "shipgate.md"
        target.parent.mkdir(parents=True)
        target.write_text("## Code signals\n- Window: `9`\n", encoding="utf-8")
        cfg = self.signals_json("hotspots", "--repo", repo.path)["config"]
        self.assertEqual((cfg["window_months"], cfg["source"]["window_months"]),
                         (12, "default"))

    # R1 — a tsconfig target outside the repo maps to nothing, never the root
    def test_an_alias_target_outside_the_repo_is_external(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={
            "tsconfig.json": '{"compilerOptions": {"paths": '
                             '{"@shared/*": ["../shared/*"], "@abs/*": ["/opt/x/*"]}}}',
            "index.ts": "export {};\n",
            "a.ts": "import x from '@shared/x';\nimport y from '@abs/y';\n"})
        rows = self.rows(repo.path)
        a = rows["a.ts"]
        self.assertEqual((a["structure"], a["unresolved"], a["fan_out"]), ("ok", 0, 0))
        self.assertEqual(rows["index.ts"]["fan_in"], 0)

    # R2 / R4 — fences: inline triple backticks, indented fences in the section
    def test_an_inline_triple_backtick_line_is_not_a_fence(self):
        mod = load_signals_module()
        text = "# P\n\n```code``` inline\n\n## Code signals\n- Window: `18`\n"
        self.assertEqual(mod.parse_code_signals(text), {"window_months": 18})

    def test_an_indented_fence_inside_the_section_is_inert(self):
        mod = load_signals_module()
        text = ("## Code signals\n- Exclude: `a/`\n\n    ```md\n    - Window: `3`\n"
                "    ```\n- Fix pattern: `^oops`\n")
        self.assertEqual(mod.parse_code_signals(text),
                         {"exclude": ["a/"], "fix_pattern": "^oops"})

    # R6 — --diff on an unborn HEAD
    def test_diff_on_an_unborn_head_uses_the_status_entries(self):
        repo = FixtureRepo(self.tmp / "r")
        repo.commit("one", ts(2020, 1, 1), writes={"a.py": "A = 1\n", "b.py": "B\n"})
        repo.git("checkout", "-q", "--orphan", "x")
        proc = self.signals("hotspots", "--repo", repo.path, "--diff", "main", "--json")
        self.assertEqual(proc.stderr, "")
        paths = {f["path"] for f in json.loads(proc.stdout)["files"]}
        self.assertEqual(paths, {"a.py", "b.py"})  # staged on the orphan branch

    # H14 — sub-reasons are reported independently
    def test_sub_reasons_on_a_shallow_clone_without_adapter_files(self):
        source = FixtureRepo(self.tmp / "src")
        source.commit("one", ts(2020, 1, 1), writes={"a.txt": "1\n"})
        source.commit("two", ts(2020, 2, 1), writes={"a.txt": "2\n"})
        dst = shallow_clone(source.path, self.tmp / "shallow")
        for argv in (["hotspots"], ["blast", "a.txt"], ["suspects", "a.txt"]):
            payload = self.signals_json(*argv, "--repo", dst)
            self.assertEqual(payload["structure"]["reason"], "no-adapter", msg=argv)
            self.assertEqual(payload["trajectory"]["reason"], "shallow", msg=argv)


# ---------------------------------------------------------------------------
# T016 — performance (SC-001)
# ---------------------------------------------------------------------------

PERF_END = ts(2025, 6, 1)
PERF_SPAN = 730 * 86400  # 24 months of history ending at PERF_END
PERF_AUTHORS = (("Dev A", "dev-a@example.test"), ("Dev B", "dev-b@example.test"),
                ("Dev C", "dev-c@example.test"))
PERF_HUBS = 5


def _fi_data(payload: bytes) -> bytes:
    return b"data %d\n%s\n" % (len(payload), payload)


def _perf_body(path, imports, lines):
    """Final content of a generated TS module: relative imports, then filler."""
    import posixpath

    head = []
    for target in imports:
        rel = posixpath.relpath(target, posixpath.dirname(path))[: -len(".ts")]
        if not rel.startswith("."):
            rel = "./" + rel
        head.append(f"import {{ v0 as m{len(head)} }} from '{rel}';")
    body = [f"export const v{j} = {j} * {len(imports) + 1}; // generated line"
            for j in range(max(1, lines - len(head)))]
    return ("\n".join(head + body) + "\n").encode()


def build_perf_repo(path: Path, commits: int, files: int, lines: int, seed: int = 16):
    """A synthetic TS repository written as one `git fast-import` stream.

    `files` modules in directories of ~20 plus PERF_HUBS hub modules under
    src/core/; `commits` change commits (1-3 files each, ~15% `fix(...)` subjects,
    ~5% carrying an exact rename) after the adding commits, then one commit that
    writes every file's final content (~`lines` lines, 2-4 relative imports to the
    same or a sibling directory, ~30% also importing a hub). Returns
    (hub path, commit count). Deterministic for a given seed.
    """
    repo = FixtureRepo(path)  # SkipTest when git is missing
    rng = random.Random(seed)
    hubs = [f"src/core/hub{k}.ts" for k in range(PERF_HUBS)]
    dirs = max(1, files // 20)
    current = hubs + [f"src/mod{i % dirs:03d}/f{i:05d}.ts" for i in range(files)]
    ident = list(range(len(current)))  # module id -> index into `current`
    chunks = []
    count = 0
    total = commits + (len(current) + 49) // 50 + 1

    def commit(subject, ops):
        nonlocal count
        name, email = PERF_AUTHORS[rng.randrange(len(PERF_AUTHORS))]
        when = PERF_END - PERF_SPAN + (PERF_SPAN * count) // max(1, total - 1)
        chunks.append(b"commit refs/heads/main\n")
        for role in (b"author", b"committer"):
            chunks.append(b"%s %s <%s> %d +0000\n" % (
                role, name.encode(), email.encode(), when))
        chunks.append(_fi_data(subject.encode()))
        chunks.extend(ops)
        chunks.append(b"\n")
        count += 1

    def modify(p, payload):
        return b"M 100644 inline %s\n%s" % (p.encode(), _fi_data(payload))

    for start in range(0, len(current), 50):
        commit(f"feat: add modules {start}", [
            modify(p, b"// new\n") for p in current[start:start + 50]])
    renamed = 0
    for c in range(commits):
        touched = rng.sample(range(len(current)), rng.randint(1, 3))
        ops = [modify(current[m], b"// rev %d\n" % c) for m in touched]
        if rng.random() < 0.05:
            m = rng.randrange(PERF_HUBS, len(current))
            old = current[m]
            new = f"src/mod{rng.randrange(dirs):03d}/r{renamed:05d}.ts"
            renamed += 1
            ops.append(b"R %s %s\n" % (old.encode(), new.encode()))
            current[m] = new
        scope = current[touched[0]].split("/")[1]
        kind = "fix" if rng.random() < 0.15 else rng.choice(("feat", "chore", "perf"))
        commit(f"{kind}({scope}): change {c}", ops)
    by_dir = {}
    for p in current[PERF_HUBS:]:
        by_dir.setdefault(int(p.split("/")[1][3:]), []).append(p)
    final = []
    for m, p in enumerate(current):
        imports = []
        if m >= PERF_HUBS:
            d = int(p.split("/")[1][3:])
            pool = [q for q in by_dir.get(d, []) + by_dir.get((d + 1) % dirs, [])
                    if q != p]
            imports = rng.sample(pool, min(len(pool), rng.randint(2, 4)))
            if rng.random() < 0.3:
                imports.append(hubs[rng.randrange(PERF_HUBS)])
        final.append(modify(p, _perf_body(p, imports, lines)))
    commit("chore: regenerate modules", final)
    stream = tempfile.NamedTemporaryFile(delete=False, dir=path.parent,
                                         suffix=".fi")
    with stream:
        stream.write(b"".join(chunks))
    with open(stream.name, "rb") as handle:
        result = subprocess.run(["git", "-C", str(path), "fast-import", "--quiet"],
                                stdin=handle, capture_output=True)
    os.unlink(stream.name)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    repo.git("reset", "-q", "--hard", "main")
    return hubs[0], count


class TestPerf(SignalsCase):
    """SC-001: one streamed log pass and one file scan — linear in history and tree.

    The always-on bounds are loose (a CI box never flakes on them) but a quadratic
    regression — a `git log` per file, or re-walking history per rename — blows
    them. The SC-001 bound itself runs with SHIPGATE_PERF=1.
    """

    def timed(self, *args):
        started = time.monotonic()
        payload = self.signals_json(*args)
        return payload, time.monotonic() - started

    def measure(self, commits, files, lines):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        hub, total = build_perf_repo(root, commits, files, lines)
        hot, hot_s = self.timed("hotspots", "--repo", root)
        blast, blast_s = self.timed("blast", "--repo", root, hub)
        self.assertEqual(hot["trajectory"]["commits_scanned"], total)
        self.assertGreater(blast["blast"]["size"], 0)
        return hot, hot_s, blast, blast_s

    def test_small_repo_stays_linear(self):
        hot, hot_s, blast, blast_s = self.measure(2000, 300, 20)
        self.assertGreaterEqual(hot["trajectory"]["commits_scanned"], 2000)
        self.assertGreaterEqual(hot["structure"]["files_scanned"], 300)
        self.assertLess(hot_s, 5.0)
        self.assertLess(blast_s, 3.0)

    @unittest.skipUnless(os.environ.get("SHIPGATE_PERF") == "1",
                         "set SHIPGATE_PERF=1 to run the SC-001 bound (~20k commits)")
    def test_large_repo_meets_sc_001(self):
        hot, hot_s, blast, blast_s = self.measure(20000, 3000, 100)
        self.assertGreaterEqual(hot["trajectory"]["commits_scanned"], 20000)
        self.assertGreaterEqual(hot["structure"]["files_scanned"], 3000)
        sys.stderr.write(f"\nSC-001: hotspots {hot_s:.2f}s (trajectory + structure), "
                         f"blast {blast_s:.2f}s (structure)\n")
        self.assertLess(hot_s, 15.0)
        self.assertLess(blast_s, 10.0)


if __name__ == "__main__":
    unittest.main()
