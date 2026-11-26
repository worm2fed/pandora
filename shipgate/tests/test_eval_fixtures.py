#!/usr/bin/env python3
"""Offline checks of the eval fixtures (#28, PR 2 of eval-measurement).

A fixture is the ``fixture.sh`` of a case directory under ``shipgate/evals/`` (and the shared
generators under ``shipgate/evals/fixtures/``). The harness runs it as ``bash fixture.sh``
inside an empty working directory before the agent starts. These tests read the fixture
text, or scaffold the fixture the same way into a temporary directory, at 0 USD: no
``claude`` call, no eval run.

``scaffold`` gives git a clean environment (a temporary ``HOME``, no system or global git
config, no inherited ``GIT_*`` variables) and a temporary ``CLAUDE_CONFIG_DIR``, so the
developer's own git identity cannot hide a fixture that sets none, and nothing reaches the
developer's real Claude config directory.

One class per claim:

- ``TestNoLiteralDeadlineDate`` (FR-023, SC-009): no fixture holds a deadline date literal;
  every fixture's revisit date is computed 30 days ahead at scaffold time.
- ``TestClarifyGitIdentity`` (FR-024): every graded clarify case sets a repo-local git
  identity.
- ``TestCase73NoGiveaway`` (FR-026): case 73's tree and commit subjects never name the retry
  idea.
- ``TestMovedSignalClaims`` (FR-020, T022): the rankings of 08 and 10 and the blast radius
  of 72, which left the eval set, hold on the scaffolded fixtures.
- ``TestProbeCases`` (FR-016 to FR-018, T026): the 19 probe cases and their probe.json.
- ``TestFixtureCases`` (FR-019, T027): 13 and 72 are fixture-only; 12, 14 and 75 are gone.
- ``TestSets`` (FR-028, SC-007, T035): sets.json covers the harness's 42 cases once each.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_eval_fixtures.py'
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals"


def case_dir(prefix: str) -> Path:
    """The case directory whose name starts with ``prefix`` (e.g. ``"58-"``)."""
    found = sorted(EVALS.glob(prefix + "*"))
    if len(found) != 1:
        raise AssertionError(f"expected one case dir {prefix}*, found {found}")
    return found[0]


def fixture_files() -> list:
    """Every case fixture.sh and every shared generator under evals/fixtures/."""
    files = sorted(EVALS.glob("*/fixture.sh"))
    shared = EVALS / "fixtures"
    if shared.is_dir():
        files += sorted(p for p in shared.iterdir() if p.is_file())
    return files


def clean_env(tmp: Path) -> dict:
    """The environment of a scaffold: no user git config, no Claude config of the user's."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "EMAIL"}
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(home / "absent.gitconfig"),
        CLAUDE_CONFIG_DIR=str(tmp / "claude-config"),
    )
    return env


def scaffold(case: Path, tmp: Path, timeout: int = 300) -> tuple:
    """Run ``bash <case>/fixture.sh`` in a new empty dir under ``tmp``: (work dir, env)."""
    work = tmp / "work"
    work.mkdir()
    env = clean_env(tmp)
    proc = subprocess.run(["bash", str(case / "fixture.sh")], cwd=work, env=env,
                          capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"{case.name}/fixture.sh failed (exit {proc.returncode}):\n"
                             f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
    return work, env


def repo_roots(work: Path) -> list:
    """Every directory under ``work`` (itself included) that holds a ``.git``."""
    roots = []
    for dirpath, dirnames, _ in os.walk(work):
        if ".git" in dirnames:
            roots.append(Path(dirpath))
            dirnames.remove(".git")
    return sorted(roots)


def tree_files(work: Path) -> list:
    """Every file under ``work``, the ``.git`` directories left out."""
    files = []
    for dirpath, dirnames, filenames in os.walk(work):
        if ".git" in dirnames:
            dirnames.remove(".git")
        files += [Path(dirpath) / name for name in filenames]
    return sorted(files)


def git(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True,
                          check=False)


class ScaffoldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eval-fixture-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


# A deadline word, then within a short stretch of the same clause, an ISO date. A period or
# a quote ends the stretch, so a dated history line ("- 2026-08-12 — ...") or an ADR row
# ("... deferred until a second deployable needs it.", "accepted", "2026-03-18") is no hit;
# "expired" and "revisited" tell of the past and are no deadline words.
DEADLINE = re.compile(r"\b(revisit|until|expires|deadline)\b[^.\"\n]{0,24}?\b\d{4}-\d{2}-\d{2}\b",
                      re.I)


def deadline_hits(path: Path) -> list:
    text = path.read_text(encoding="utf-8")
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        m = DEADLINE.search(line)
        if m:
            hits.append(f"{path.relative_to(EVALS)}:{n}: {m.group(0)}")
    return hits


class TestNoLiteralDeadlineDate(ScaffoldCase):
    """FR-023 / SC-009: a date a model reads as a deadline expires; every model then flags
    the expired deviation (case 46 met it on 2026-10-06). A fixture computes such a date at
    scaffold time instead."""

    def test_the_pattern_tells_a_deadline_from_a_dated_history_line(self):
        hits = [
            "- 2026-08-12 — Export logs at INFO. Authorised by the user; revisit 2026-10-05.",
            "The legacy lines are read until 2027-01-23.",
            "token expires on 2026-12-01",
            "Deadline: 2026-12-24",
        ]
        misses = [
            '("0002-x", "Bus", "a broker is deferred until a second deployable needs it.", '
            '"accepted", "2026-03-18"),',
            "- 2026-09-20 — No CSV guard in v1. Revisit if the export is ever exposed.",
            "- 2026-08-14 — gotcha: unittest from a service dir finds nothing.",
            "revisit REVISIT_DATE.",
            "# every model flags the deviation as expired (case 46 met this on 2026-10-06).",
        ]
        for line in hits:
            self.assertRegex(line, DEADLINE)
        for line in misses:
            self.assertNotRegex(line, DEADLINE)

    def test_no_fixture_holds_a_literal_deadline_date(self):
        files = fixture_files()
        self.assertGreater(len(files), 10, "no fixture found: is EVALS right?")
        hits = [h for f in files for h in deadline_hits(f)]
        self.assertEqual(hits, [], "literal deadline dates:\n" + "\n".join(hits))

    def test_every_revisit_date_is_30_days_ahead_at_scaffold_time(self):
        cases = sorted(f.parent for f in EVALS.glob("*/fixture.sh")
                       if "REVISIT_DATE" in f.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 9, [c.name for c in cases])
        for case in cases:
            with self.subTest(case=case.name):
                tmp = self.tmp / case.name
                tmp.mkdir()
                before = datetime.date.today()
                work, env = scaffold(case, tmp)
                after = datetime.date.today()
                left, found = [], []
                for path in tree_files(work):
                    text = path.read_bytes().decode("utf-8", "replace")
                    if "REVISIT_DATE" in text:
                        left.append(str(path.relative_to(work)))
                    found += re.findall(r"revisit (\d{4}-\d{2}-\d{2})", text)
                self.assertEqual(left, [], "REVISIT_DATE is still in the tree")
                self.assertTrue(found, "no revisit date in the tree")
                expected = {(d + datetime.timedelta(days=30)).isoformat() for d in (before, after)}
                self.assertLessEqual(set(found), expected)
                for root in repo_roots(work):
                    status = git(root, env, "status", "--porcelain")
                    self.assertEqual((status.returncode, status.stdout), (0, ""),
                                     f"{root.relative_to(work)}: the date is not committed")


def clarify_cases() -> list:
    """The graded clarify cases: ``clarify`` in the name, a fixture.sh and a prompt.md, and
    not a negative (``-neg-``), which becomes a trigger probe (T026) where no clarify pass
    runs."""
    return sorted(d for d in EVALS.iterdir()
                  if d.is_dir() and "clarify" in d.name and "-neg-" not in d.name
                  and (d / "fixture.sh").is_file() and (d / "prompt.md").is_file())


class TestClarifyGitIdentity(ScaffoldCase):
    """FR-024: a clarify fixture with no repo-local identity lets the blindspot pass run, as
    it did in 15, 17, 18 and 19, which passed the identity with ``git -c`` only."""

    def test_the_covered_cases(self):
        names = [d.name[:3] for d in clarify_cases()]
        for want in ("15-", "16-", "17-", "18-", "19-", "76-", "77-", "78-"):
            self.assertIn(want, names)

    def test_every_clarify_fixture_sets_a_repo_local_identity(self):
        for case in clarify_cases():
            with self.subTest(case=case.name):
                tmp = self.tmp / case.name
                tmp.mkdir()
                work, env = scaffold(case, tmp)
                roots = repo_roots(work)
                self.assertTrue(roots, f"{case.name}: the fixture builds no git repo")
                for root in roots:
                    for key in ("user.name", "user.email"):
                        got = git(root, env, "config", "--local", key)
                        self.assertTrue(got.stdout.strip(),
                                        f"{case.name}: {root.relative_to(work)} has no local {key}")


class TestCase73NoGiveaway(ScaffoldCase):
    """FR-026: the helper is found by reading its body, not by a name, a comment, a commit
    subject or an existing caller that says what it is for."""

    GIVEAWAY = re.compile(r"retry|back-?off|exponential|attempt|flak|5xx", re.I)

    def test_tree_and_commit_subjects_never_name_the_idea(self):
        work, env = scaffold(case_dir("73-"), self.tmp)
        repo = work / "app"
        hits = []
        for dirpath, dirnames, filenames in os.walk(repo):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for name in filenames:
                path = Path(dirpath) / name
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if self.GIVEAWAY.search(line):
                        hits.append(f"{path.relative_to(repo)}:{n}: {line.strip()}")
        log = git(repo, env, "log", "--format=%s")
        self.assertEqual(log.returncode, 0, log.stderr)
        hits += [f"commit subject: {s}" for s in log.stdout.splitlines() if self.GIVEAWAY.search(s)]
        self.assertEqual(hits, [], "giveaways:\n" + "\n".join(hits))

    def test_the_helper_is_still_there_and_has_no_caller(self):
        work, env = scaffold(case_dir("73-"), self.tmp)
        repo = work / "app"
        policy = (repo / "packages/platform/src/net/resilience/policy.ts").read_text(encoding="utf-8")
        self.assertIn("export async function withPolicy", policy)
        self.assertIn("wait *= 2", policy)
        self.assertIn("keepGoing", policy)
        users = git(repo, env, "grep", "-l", "withPolicy")
        self.assertEqual(users.stdout.split(), ["packages/platform/src/net/resilience/policy.ts"])


SIGNALS = EVALS.parent / "scripts" / "signals.py"
SIGNAL_GRADER = EVALS / "signal_grader.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMovedSignalClaims(ScaffoldCase):
    """FR-020: the ranking claims of 08 (and 12), 10 (and 14) and the blast radius of 72 left
    the eval set; these tests hold them at 0 USD. The rankings run with ``--graph off``: the
    regex scanner gives the same order as codegraph on both fixtures, and needs no codegraph."""

    def signals_json(self, repo: Path, env: dict, *args: str) -> dict:
        proc = subprocess.run([sys.executable, str(SIGNALS), *args, "--json", "--graph", "off",
                               "--repo", str(repo)],
                              env=env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        return json.loads(proc.stdout)

    def test_08_suspects_rank_month_range_first(self):
        work, env = scaffold(case_dir("08-"), self.tmp)
        data = self.signals_json(work / "app", env, "suspects", "src/reports/exportReport.ts")
        paths = [s["path"] for s in data["suspects"]]
        self.assertEqual(paths[0], "src/dates/monthRange.ts", paths)

    def test_10_hotspots_rank_promo_then_calendar(self):
        work, env = scaffold(case_dir("10-"), self.tmp)
        data = self.signals_json(work / "app", env, "hotspots", "--diff", "HEAD~1")
        paths = [f["path"] for f in data["files"]]
        self.assertEqual(paths[:2], ["src/checkout/promo.ts", "src/shared/calendar.ts"], paths)

    @unittest.skipUnless(shutil.which("codegraph"), "codegraph is not on PATH")
    def test_72_graph_arm_gives_59_of_59(self):
        env = clean_env(self.tmp)
        proc = subprocess.run([sys.executable, str(SIGNAL_GRADER), "fixture",
                               str(case_dir("72-")), "--arm", "graph", "--json"],
                              env=env, capture_output=True, text=True, timeout=600, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        s = json.loads(proc.stdout)
        self.assertEqual(s["source"], "graph")
        files = s["files"]
        self.assertEqual((files["tp"], files["got"], files["truth"]), (59, 59, 59))
        self.assertEqual((files["precision"], files["recall"]), (1.0, 1.0))
        self.assertFalse(s["truncated"])


# The probe cases (decision D3): the skill that must or must not fire, and the calls that
# must stay at 0. An empty list counts every call of that tool; `agent: True` counts Agent.
PROBES = {
    "06-neg-feature-request": {"skill": "structured-debug", "fires": False},
    "07-neg-explain-code": {"skill": "structured-debug", "fires": False},
    "08-bug-localization-history": {"skill": "structured-debug", "fires": True},
    "09-blast-radius-diff": {"skill": "route-and-map", "fires": True},
    "10-risk-ranked-review": {"skill": "review", "fires": True},
    "11-neg-one-line-change": {"skill": "route-and-map", "fires": False,
                               "zero": {"bash": [r"signals\.py", "codegraph"]}},
    "20-neg-clarify-one-line-fix": {"skill": "clarify", "fires": False,
                                    "zero": {"write": ["app/docs/prd/"]}},
    "21-neg-clarify-explain-code": {"skill": "clarify", "fires": False,
                                    "zero": {"write": ["app/docs/prd/"]}},
    "27-neg-verify-explain": {"skill": "verify", "fires": False, "zero": {"bash": []}},
    "28-neg-verify-run-once": {"skill": "verify", "fires": False},
    "34-neg-route-one-line": {"skill": "route-and-map", "fires": False,
                              "zero": {"bash": [r"signals\.py"]}},
    "35-neg-route-explain": {"skill": "route-and-map", "fires": False, "zero": {"edit": []}},
    "41-neg-kb-personal-pref": {"skill": "knowledge-base", "fires": False,
                                "zero": {"edit": ["app/docs/", r"app/CLAUDE\.md"],
                                         "write": ["app/docs/", r"app/CLAUDE\.md"]}},
    "42-neg-kb-code-question": {"skill": "knowledge-base", "fires": False,
                                "zero": {"edit": [], "write": []}},
    "49-neg-review-explain-diff": {"skill": "review", "fires": False, "zero": {"agent": True}},
    "50-neg-review-trivial": {"skill": "review", "fires": False, "zero": {"agent": True}},
    "56-neg-design-already-designed": {"skill": "design", "fires": False,
                                       "zero": {"write": ["app/docs/adr/"]}},
    "57-neg-design-adr-question": {"skill": "design", "fires": False,
                                   "zero": {"edit": [], "write": ["app/docs/"]}},
    "67-big-neg-one-line": {"skill": "route-and-map", "fires": False,
                            "zero": {"bash": [r"journal\.py"]}},
}

HARNESS_FILES = ("prompt.md", "case.yaml", "graders")
PROBE_FILES = ("fixture.sh", "probe.md", "probe.json")


def numbered_dirs() -> list:
    return sorted(d for d in EVALS.iterdir() if d.is_dir() and re.match(r"\d+-", d.name))


def is_harness_case(d: Path) -> bool:
    """What the harness discovers: ``case.yaml``, or ``prompt.md`` with ``graders/*.md``."""
    return (d / "case.yaml").is_file() or (
        (d / "prompt.md").is_file() and any((d / "graders").glob("*.md")))


class TestProbeCases(unittest.TestCase):
    """FR-016 to FR-018 (T026): a probe case keeps its fixture, holds the prompt as probe.md
    and the expectation as probe.json, and holds nothing the harness would run (ADR 0036)."""

    def test_the_table_holds_19_cases(self):
        self.assertEqual(len(PROBES), 19)

    def test_each_probe_case_has_the_probe_files_and_no_harness_files(self):
        for name in PROBES:
            with self.subTest(case=name):
                d = EVALS / name
                for f in PROBE_FILES:
                    self.assertTrue((d / f).is_file(), f"{name}: no {f}")
                for f in HARNESS_FILES:
                    self.assertFalse((d / f).exists(), f"{name}: {f} is still there")
                self.assertFalse(is_harness_case(d), name)

    def test_probe_md_is_a_prompt_without_front_matter(self):
        for name in PROBES:
            with self.subTest(case=name):
                text = (EVALS / name / "probe.md").read_text(encoding="utf-8")
                self.assertTrue(text.strip(), f"{name}: probe.md is empty")
                self.assertNotEqual(text.lstrip().splitlines()[0].strip(), "---",
                                    f"{name}: probe.md starts with front matter")

    def test_probe_json_equals_the_table(self):
        for name, want in PROBES.items():
            with self.subTest(case=name):
                got = json.loads((EVALS / name / "probe.json").read_text(encoding="utf-8"))
                self.assertEqual(got, want)

    def test_probe_py_accepts_every_probe_json(self):
        probe = load_module("shipgate_probe_fixtures", EVALS / "probe.py")
        for name in PROBES:
            with self.subTest(case=name):
                expect = probe.read_json(str(EVALS / name / "probe.json"), "probe.json")
                probe.check_expect(expect)

    def test_no_other_case_has_a_probe_json(self):
        others = [d.name for d in EVALS.iterdir()
                  if d.is_dir() and (d / "probe.json").exists() and d.name not in PROBES]
        self.assertEqual(others, [])


class TestFixtureCases(unittest.TestCase):
    """FR-019 (T027): 13 and 72 are fixture cases for ``signal_grader.py fixture``; the cases
    12, 14 and 75 are gone (their claims moved to TestMovedSignalClaims and the signals
    tests)."""

    def test_13_and_72_hold_the_fixture_and_expected_json_only(self):
        for prefix in ("13-", "72-"):
            d = case_dir(prefix)
            with self.subTest(case=d.name):
                self.assertEqual(sorted(p.name for p in d.iterdir()), ["expected.json", "fixture.sh"])

    def test_12_14_and_75_are_deleted(self):
        for prefix in ("12-", "14-", "75-"):
            self.assertEqual(sorted(EVALS.glob(prefix + "*")), [], prefix)


SETS = EVALS / "sets.json"
EVAL_SETS = ("kept", "guards", "ablation-32", "parked")


class TestSets(unittest.TestCase):
    """SC-007, FR-028 (T035): the eval sets cover exactly the harness's 42 cases, no case is
    in two sets, the probe set is exactly the probe cases, and case 78 is parked."""

    @classmethod
    def setUpClass(cls):
        cls.sets = json.loads(SETS.read_text(encoding="utf-8"))

    def test_the_set_sizes(self):
        sizes = {k: len(v) for k, v in self.sets.items()}
        self.assertEqual(sizes, {"kept": 22, "guards": 2, "ablation-32": 17, "probes": 19,
                                 "parked": 1})

    def test_the_eval_sets_are_exactly_the_harness_case_list(self):
        harness = sorted(d.name for d in EVALS.iterdir() if d.is_dir() and is_harness_case(d))
        self.assertEqual(len(harness), 42, harness)
        named = sorted(c for s in EVAL_SETS for c in self.sets[s])
        self.assertEqual(named, harness)

    def test_no_case_is_in_two_sets(self):
        seen = {}
        for name, cases in self.sets.items():
            for c in cases:
                seen.setdefault(c, []).append(name)
        twice = {c: names for c, names in seen.items() if len(names) > 1}
        self.assertEqual(twice, {})

    def test_probes_is_exactly_the_dirs_with_probe_json(self):
        with_probe = sorted(d.name for d in EVALS.iterdir() if (d / "probe.json").is_file())
        self.assertEqual(sorted(self.sets["probes"]), with_probe)

    def test_every_name_is_an_existing_dir(self):
        missing = [c for cases in self.sets.values() for c in cases if not (EVALS / c).is_dir()]
        self.assertEqual(missing, [])

    def test_every_numbered_dir_is_exactly_one_form(self):
        probe_like = ("probe.md", "probe.json")
        for d in numbered_dirs():
            with self.subTest(case=d.name):
                names = {p.name for p in d.iterdir()}
                harness = is_harness_case(d) and not names & {*probe_like, "expected.json"}
                probe = (set(PROBE_FILES) <= names and not names & set(HARNESS_FILES)
                         and "expected.json" not in names)
                fixture = (names == {"fixture.sh", "expected.json"})
                self.assertEqual([harness, probe, fixture].count(True), 1,
                                 f"{d.name}: {sorted(names)}")

    def test_set_cases_accepts_the_run_sets_and_refuses_parked(self):
        evalrun = load_module("shipgate_evalrun_fixtures", EVALS / "evalrun.py")
        for name in ("kept", "guards", "ablation-32", "probes"):
            self.assertEqual(evalrun.set_cases(str(SETS), name), self.sets[name])
        with self.assertRaises(evalrun.InputError):
            evalrun.set_cases(str(SETS), "parked")

    def test_78_is_in_parked_only(self):
        holding = [name for name, cases in self.sets.items()
                   if "78-clarify-exec-fully-specified" in cases]
        self.assertEqual(holding, ["parked"])


if __name__ == "__main__":
    unittest.main()
