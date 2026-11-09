#!/usr/bin/env python3
"""Contract tests for shipgate's ``scripts/lean_config.py`` (ADR 0019).

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_lean_config.py'

Every case runs the script through a subprocess on a copy in a temp directory. The
fixtures under ``fixtures/configs/`` are the 0.25.0 and the 0.24 template filled in, this
repository's own config as it stood before 0.25.0, a hand-written config, and two mixed
configs (a contract with project escalations, a setup header with project sentences).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The one placeholder rule's cases, shared with `_config.py`'s tests.
from test_config import PLACEHOLDER_CASES, REAL_VALUE_CASES

TESTS_DIR = Path(__file__).resolve().parent
LEAN = TESTS_DIR.parent / "scripts" / "lean_config.py"
TEMPLATE = TESTS_DIR.parent / "config-template.md"
FIXTURES = TESTS_DIR / "fixtures" / "configs"

OK = 0
INFRA = 1
USAGE = 2

TEMPLATE_FILLED_LEAN = """\
# shipgate configuration — template

## Journal

- Database: `.claude/shipgate.db`

## Forge & tracker

- Forge: GitHub — CLI: `gh`

## Branching

- Pattern: `<type>/<issue-id>-<slug>`

## Writing style

- Docs: `ste-80`

## Code signals

- Window: `18`

## Autonomy

- Mode: executive
"""

# The catalogued wordings of the `Executive contract` bullet: the 0.24 template's, this
# repo's config before 0.25.0, and the three eval-fixture paraphrases.
EXECUTIVE_CONTRACTS = [
    "- Executive contract (applies only when mode is `executive`): the orchestrator makes and\n"
    "  RECORDS routine decisions itself — clarify answers land in the PRD's \"Assumptions\n"
    "  (executive)\" list, design choices in the ADR, small calls in the ledger — and reports\n"
    "  them in each phase summary so the user can veto. It still escalates: one-way doors\n"
    "  (schema, public API, shared write paths, data migrations), user-visible scope changes,\n"
    "  anything in Security-sensitive areas, and genuine 50/50s where it cannot form a\n"
    "  recommendation.\n",
    "- Executive contract: the orchestrator makes and RECORDS routine decisions itself —\n"
    "  clarify answers land in the PRD's \"Assumptions (executive)\" list, design choices in the\n"
    "  ADR, small calls in the ledger — and reports them in each phase summary so they can be\n"
    "  vetoed. It still escalates: one-way doors, user-visible scope changes, anything in\n"
    "  Security-sensitive areas above, and genuine 50/50s where it cannot form a recommendation.\n",
    "- Executive contract: the orchestrator makes and RECORDS routine decisions itself — clarify\n"
    "  answers land in the PRD's \"Assumptions (executive)\" list — and reports them in each phase\n"
    "  summary so the user can veto. It still escalates one-way doors (schema, public API, shared\n"
    "  write paths, data migrations), user-visible scope changes, and genuine 50/50s.\n",
    "- Executive contract: the orchestrator makes and RECORDS routine decisions itself — design "
    "choices in the ADR — and reports them in the phase summary so the user can veto. It still "
    "escalates one-way doors (schema, public API, shared write paths, data migrations), "
    "user-visible scope changes, and genuine 50/50s.\n",
    "- Executive contract: the orchestrator makes and RECORDS routine decisions itself (clarify answers in the\n"
    "  PRD's \"Assumptions (executive)\" list, design choices in the ADR) and reports them so the user can veto. It\n"
    "  still escalates one-way doors (schema, public API, shared write paths, data migrations), user-visible\n"
    "  scope changes, and genuine 50/50s.\n",
]

# Contract bullets with a sentence the catalogue does not hold: each one stays, as mixed.
MIXED_CONTRACTS = [
    "- **Executive contract:** routine calls are made and written down by the orchestrator;\n"
    "  one-way doors still go to the user.\n",
    "* Executive Contract (executive mode only): decide routine questions, record each one,\n"
    "  escalate the rest.\n",
    "- Executive contract: the orchestrator makes and RECORDS routine decisions itself —\n"
    "  clarify answers land in the PRD's \"Assumptions (executive)\" list, design choices in the\n"
    "  ADR, small calls in the ledger — and reports them in each phase summary so they can be\n"
    "  vetoed. It still escalates: one-way doors, changes to system-wide settings, a new launch\n"
    "  agent, and any paid tool.\n",
]

STYLE_COMMENT = "<!-- Default when absent: match surrounding code; no extra skill invoked. -->"
ASK_COMMENT = ("<!-- Default when absent: `ask` — every gate question goes to the user, exactly "
               "the\n     skills' built-in behavior. -->")
SETUP_HEADER = (
    "Project configuration for the `shipgate` plugin. Skills read this at the start of a flow;\n"
    "it overrides their built-in defaults. Written by `/shipgate:setup` on 2026-08-20 —\n"
    "re-run it to change the journal or artifact homes rather than hand-editing those.\n"
)
HINT_PROSE = "move the project sentences to their own paragraph or section"
HINT_CONTRACT = "add the extra cases to an Extra escalations line, then delete this bullet"

REPO = TESTS_DIR.parent.parent
# Every committed version of the template before 0.25.0, newest first.
TEMPLATE_HISTORY = ("53458bf", "664bbac", "72ef5d1", "40ded8c", "e9abce6", "8717b4a",
                    "a7efcf0", "64bd3c9", "a3e13f5", "608d930", "43ba7e3", "7abcad9",
                    "bfade61")


def run_lean(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(LEAN)] + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=60,
    )


class LeanConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lean-config-"))

    def tearDown(self):
        for root, dirs, _files in os.walk(self.tmp):
            for name in dirs:
                os.chmod(os.path.join(root, name), 0o755)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self, text, name="shipgate.md"):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def fixture(self, name):
        path = self.tmp / name
        shutil.copyfile(str(FIXTURES / name), str(path))
        return path

    def lean_json(self, path, *extra):
        proc = run_lean([path, "--json"] + list(extra))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        return json.loads(proc.stdout)

    def apply(self, path, *extra):
        proc = run_lean([path, "--apply"] + list(extra))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        return proc, path.read_text(encoding="utf-8")

    def lean_text(self, text, *extra):
        """The file's content after `--apply`, for an inline config."""
        _proc, out = self.apply(self.config(text), *extra)
        return out

    def ranges(self, report):
        return [(r["start"], r["end"], r["kind"]) for r in report["removals"]]


# Both template generations: the current one (0.25.0) and the one before it (0.24).
TEMPLATE_FIXTURES = ("template-filled.md", "template-filled-0.24.md")

COMMON_ANCHORS = (
    "Copy this file into your project as",
    "Every section is **optional**",
    "Division of labor with `CLAUDE.md`",
    "rule",
    "Default when absent",
    "Only needed for umbrella",
    "When this section is present the project is **journaled**",
    "**Position is recorded, not guessed.**",
    "**Recording is enforced by the plugin's hooks**",
    "**The database is local, disposable state.**",
    "**The journal does not replace the ledger.**",
    "**Event names and payload shapes are a fixed vocabulary.**",
    "**One stream per issue, named for its branch**",
    "Dial enforcement down by setting",
    "If declared, two skills honor it",
    "The watcher is strictly read-only",
    "Optional, when a **Journal** is configured",
    "The one section a script reads rather than the model",
    "Hard rules for anyone editing this repo",
    "`workflow` runs that phase's fan-out",
    "Degradation is automatic and never blocks",
    "placeholder",
    "empty-section",
)


class TestFixtures(LeanConfigTestCase):
    def test_template_filled_leaves_the_title_and_the_filled_bullets(self):
        for name in TEMPLATE_FIXTURES:
            with self.subTest(fixture=name):
                _proc, out = self.apply(self.fixture(name))
                self.assertEqual(out, TEMPLATE_FILLED_LEAN)

    def test_template_filled_is_idempotent(self):
        for name in TEMPLATE_FIXTURES:
            with self.subTest(fixture=name):
                path = self.fixture(name)
                self.apply(path)
                report = self.lean_json(path)
                self.assertEqual(report["removals"], [])
                self.assertFalse(report["changed"])
                self.assertEqual(path.read_text(encoding="utf-8"), TEMPLATE_FILLED_LEAN)

    def test_template_0_24_removes_every_catalogued_form(self):
        report = self.lean_json(self.fixture("template-filled-0.24.md"))
        anchors = {r["anchor"] for r in report["removals"]}
        for expected in COMMON_ANCHORS + (
            "Subagents don't read this file themselves",
            "executive-contract",
        ):
            self.assertIn(expected, anchors)

    def test_template_0_25_removes_every_catalogued_form(self):
        report = self.lean_json(self.fixture("template-filled.md"))
        anchors = {r["anchor"] for r in report["removals"]}
        for expected in COMMON_ANCHORS + (
            "**How the config files layer.**",
            "1. the repo's `.claude/shipgate.md` files, from the working directory up to the "
            "repo root; 2. the umbrella's `.claude/shipgate.md`",
            "The config is resolved per section.",
            "A nested config can take nothing from the umbrella.",
            "The user file uses the same section vocabulary",
            "Subagents don't read these files themselves",
            "`setup` writes a lean file",
            "Usually personal: belongs in the user file",
        ):
            self.assertIn(expected, anchors)

    def test_the_current_template_unfilled_leans_to_its_title(self):
        path = self.tmp / "template.md"
        shutil.copyfile(str(TEMPLATE), str(path))
        _proc, out = self.apply(path)
        self.assertEqual(out, "# shipgate configuration — template\n")

    def test_no_line_of_the_current_template_header_starts_with_inherit(self):
        lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
        header = lines[:lines.index("---")]
        self.assertEqual(
            [line for line in header if line.lstrip().lower().startswith("inherit")], [])

    def test_before_0_25_0_removes_exactly_the_header_the_signals_comment_and_the_contract(self):
        path = self.fixture("before-0.25.0.md")
        original = path.read_text(encoding="utf-8").splitlines(keepends=True)
        report = self.lean_json(path)
        self.assertEqual(
            self.ranges(report),
            [(3, 5, "paragraph"), (62, 63, "comment"), (86, 90, "bullet")],
        )
        self.assertEqual(
            [r["anchor"] for r in report["removals"]],
            ["Project configuration for the `shipgate` plugin.",
             "Read by `shipgate/scripts/signals.py`",
             "executive-contract"],
        )
        _proc, out = self.apply(path)
        # Lines 6 and 64 are the second blank of the runs the removals leave.
        dropped = set(range(3, 7)) | {62, 63, 64} | set(range(86, 91))
        expected = "".join(line for n, line in enumerate(original, 1) if n not in dropped)
        self.assertEqual(out, expected)

    def test_before_0_25_0_is_idempotent(self):
        path = self.fixture("before-0.25.0.md")
        self.apply(path)
        once = path.read_bytes()
        report = self.lean_json(path)
        self.assertEqual(report["removals"], [])
        self.assertFalse(report["changed"])
        self.apply(path)
        self.assertEqual(path.read_bytes(), once)

    def test_hand_written_comes_back_byte_identical(self):
        path = self.fixture("hand-written.md")
        before = path.read_bytes()
        report = self.lean_json(path)
        self.assertEqual(report["removals"], [])
        self.assertFalse(report["changed"])
        self.assertEqual(report["diff"], "")
        proc, _out = self.apply(path)
        self.assertEqual(proc.stdout.strip(), "lean_config: 0 block(s) to remove")
        self.assertEqual(path.read_bytes(), before)


class TestCli(LeanConfigTestCase):
    TEXT = (
        "# shipgate — x\n"
        "\n"
        "## Branching\n"
        "\n"
        + STYLE_COMMENT + "\n"
        "\n"
        "- Pattern: `feature/x`\n"
        "- Examples: <two or three\n"
        "  examples>\n"
    )

    def test_json_shape_and_one_based_ranges(self):
        path = self.config(self.TEXT)
        proc = run_lean([path, "--json"])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(
            sorted(report),
            ["changed", "diff", "equal_sections", "mixed", "path", "removals",
             "shadowed_sections"])
        self.assertEqual(report["mixed"], [])
        self.assertEqual(report["path"], str(path))
        self.assertEqual(report["equal_sections"], [])
        self.assertEqual(report["shadowed_sections"], [])
        self.assertTrue(report["changed"])
        self.assertEqual(report["removals"], [
            {"start": 5, "end": 5, "kind": "comment", "anchor": "Default when absent"},
            {"start": 8, "end": 9, "kind": "bullet", "anchor": "placeholder"},
        ])
        self.assertEqual(json.dumps(report, sort_keys=True, indent=2) + "\n", proc.stdout)
        self.assertIn("--- a/" + str(path), report["diff"])
        self.assertIn("+++ b/" + str(path), report["diff"])
        self.assertIn("-- Examples: <two or three", report["diff"])

    def test_without_apply_the_file_is_untouched_and_the_diff_is_printed(self):
        path = self.config(self.TEXT)
        proc = run_lean(["shipgate.md"], cwd=self.tmp)
        self.assertEqual(proc.returncode, OK, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], "lean_config: 2 block(s) to remove")
        self.assertEqual(lines[1], "--- a/shipgate.md")
        self.assertEqual(lines[2], "+++ b/shipgate.md")
        self.assertEqual(path.read_text(encoding="utf-8"), self.TEXT)

    def test_apply_writes_and_prints_the_summary(self):
        path = self.config(self.TEXT)
        proc, out = self.apply(path)
        self.assertEqual(proc.stdout, "lean_config: 2 block(s) to remove\n")
        self.assertEqual(out, "# shipgate — x\n\n## Branching\n\n- Pattern: `feature/x`\n")

    def test_apply_on_an_unwritable_file_exits_1(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root writes through file modes")
        path = self.config(self.TEXT)
        os.chmod(str(path), 0o444)
        try:
            proc = run_lean([path, "--apply"])
        finally:
            os.chmod(str(path), 0o644)
        self.assertEqual(proc.returncode, INFRA, proc.stdout)
        self.assertIn("error:", proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), self.TEXT)

    def test_apply_in_an_unwritable_directory_exits_1(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root writes through file modes")
        directory = self.tmp / "locked"
        directory.mkdir()
        path = directory / "shipgate.md"
        path.write_text(self.TEXT, encoding="utf-8")
        os.chmod(str(directory), 0o555)
        try:
            proc = run_lean([path, "--apply"])
        finally:
            os.chmod(str(directory), 0o755)
        self.assertEqual(proc.returncode, INFRA, proc.stdout)
        self.assertIn("error:", proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), self.TEXT)
        self.assertEqual(sorted(os.listdir(str(directory))), ["shipgate.md"])

    def test_apply_keeps_the_file_mode(self):
        path = self.config(self.TEXT)
        os.chmod(str(path), 0o600)
        self.apply(path)
        self.assertEqual(stat.S_IMODE(os.stat(str(path)).st_mode), 0o600)
        self.assertEqual(sorted(os.listdir(str(self.tmp))), ["shipgate.md"])

    def test_crlf_input_keeps_crlf_and_the_diff_shows_only_the_removal(self):
        text = self.TEXT.replace("\n", "\r\n")
        path = self.tmp / "shipgate.md"
        path.write_bytes(text.encode("utf-8"))
        report = self.lean_json(path)
        changed = [line for line in report["diff"].splitlines()
                   if line[:1] in "+-" and not line.startswith(("---", "+++"))]
        self.assertEqual(changed, [
            "-" + STYLE_COMMENT,
            "-",
            "-- Examples: <two or three",
            "-  examples>",
        ])
        self.apply(path)
        self.assertEqual(
            path.read_bytes(),
            b"# shipgate \xe2\x80\x94 x\r\n\r\n## Branching\r\n\r\n- Pattern: `feature/x`\r\n")

    def test_a_kept_double_blank_far_from_a_removal_survives(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "This repo ships three services.\n"
            "\n"
            "\n"
            "Each one has its own release train.\n"
            "\n"
            "## Code signals\n"
            "\n"
            "- Window: `12`\n"
            "  <!-- a note with a gap\n"
            "\n"
            "\n"
            "       inside it -->\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
            "- Extra escalations: <if any>\n"
        )
        path = self.config(text)
        report = self.lean_json(path)
        self.assertEqual(len(re.findall(r"^@@ ", report["diff"], re.M)), 1, report["diff"])
        self.assertEqual(self.lean_text(text), text.replace("- Extra escalations: <if any>\n", ""))

    def test_usage_errors_exit_2(self):
        path = self.config(self.TEXT)
        cases = [
            [self.tmp / "missing.md"],
            [path, "--no-such-flag"],
            [path, "--drop-equal"],
            [path, "--user", self.tmp / "missing-user.md"],
            [path, "--user", path, "--umbrella", self.tmp / "missing-umbrella.md"],
            [],
        ]
        for args in cases:
            with self.subTest(args=args):
                proc = run_lean(args)
                self.assertEqual(proc.returncode, USAGE, proc.stdout + proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), self.TEXT)


class TestUserFile(LeanConfigTestCase):
    PROJECT = (
        "# shipgate — x\n"
        "\n"
        "## Writing style\n"
        "\n"
        "- Docs: `ste-80`\n"
        "  <!-- a project note the user file does not carry -->\n"
        "\n"
        "## Code tooling\n"
        "\n"
        "- Library docs: a context7-style MCP\n"
        "\n"
        "## Autonomy\n"
        "\n"
        "- Mode: executive\n"
    )
    USER = (
        "# shipgate — personal defaults\n"
        "\n"
        "## writing STYLE\n"
        "- Docs:   `ste-80`\n"
        "\n"
        "## Code tooling\n"
        "\n"
        "- Library docs: another docs server\n"
    )

    def test_user_reports_an_equal_section_and_keeps_it(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        report = self.lean_json(path, "--user", user)
        self.assertEqual(report["equal_sections"], ["Writing style"])
        self.assertEqual(report["removals"], [])
        self.assertFalse(report["changed"])
        proc, out = self.apply(path, "--user", user)
        self.assertEqual(
            proc.stdout, "lean_config: 0 block(s) to remove, 1 section(s) equal to the user file\n")
        self.assertEqual(out, self.PROJECT)

    def test_drop_equal_removes_the_equal_section_heading_included(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        report = self.lean_json(path, "--user", user, "--drop-equal")
        self.assertEqual(self.ranges(report), [(3, 6, "section")])
        self.assertEqual(report["removals"][0]["anchor"], "equal-to-user")
        _proc, out = self.apply(path, "--user", user, "--drop-equal")
        self.assertEqual(out, (
            "# shipgate — x\n"
            "\n"
            "## Code tooling\n"
            "\n"
            "- Library docs: a context7-style MCP\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: executive\n"
        ))


def load_lean_module():
    """Import lean_config.py directly, for the catalogue checks."""
    spec = importlib.util.spec_from_file_location("shipgate_lean_config", LEAN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestMixed(LeanConfigTestCase):
    def test_a_contract_with_project_escalations_stays_as_mixed(self):
        path = self.fixture("mixed-contract.md")
        report = self.lean_json(path)
        self.assertEqual(report["mixed"], [{
            "start": 15, "end": 19, "kind": "bullet", "anchor": "executive-contract",
            "hint": HINT_CONTRACT}])
        self.assertEqual(self.ranges(report),
                         [(5, 7, "comment"), (10, 10, "bullet"), (20, 20, "bullet")])
        proc = run_lean([path])
        self.assertEqual(proc.stdout.splitlines()[:2], [
            "lean_config: 3 block(s) to remove, 1 mixed block(s) kept",
            "mixed: lines 15-19 (executive-contract) — " + HINT_CONTRACT,
        ])
        original = (FIXTURES / "mixed-contract.md").read_text(encoding="utf-8").splitlines(True)
        _proc, out = self.apply(path)
        self.assertEqual(out, "".join(
            line for n, line in enumerate(original, 1) if n not in {5, 6, 7, 8, 10, 20}))

    def test_a_setup_header_with_project_sentences_stays_as_mixed(self):
        path = self.fixture("mixed-header.md")
        report = self.lean_json(path)
        self.assertEqual(report["mixed"], [{
            "start": 3, "end": 6, "kind": "paragraph",
            "anchor": "Project configuration for the `shipgate` plugin.", "hint": HINT_PROSE}])
        self.assertEqual(self.ranges(report), [(10, 11, "comment")])
        original = (FIXTURES / "mixed-header.md").read_text(encoding="utf-8").splitlines(True)
        _proc, out = self.apply(path)
        self.assertEqual(out, "".join(
            line for n, line in enumerate(original, 1) if n not in {10, 11, 12}))
        again = self.lean_json(path)
        self.assertEqual((again["removals"], len(again["mixed"])), ([], 1))

    def test_a_hand_written_line_under_an_anchored_line_makes_the_block_mixed(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Journal\n"
            "\n"
            "- Database: `.claude/shipgate.db`\n"
            "\n"
            "Dial enforcement down by setting `enforce.stop_gate` or `enforce.auto_capture` to false\n"
            "in the sidecar (both default true). Run `journal.py doctor` when anything looks stale.\n"
            "This team keeps the stop gate on for every service.\n"
            "\n"
            + STYLE_COMMENT + "\n"
            "We pin the formatter in `tools/fmt.toml`.\n"
        )
        report = self.lean_json(self.config(text))
        # The comment is a block of its own, wholly catalogued; the line under it stays.
        self.assertEqual(self.ranges(report), [(11, 11, "comment")])
        self.assertEqual([(m["start"], m["end"], m["kind"]) for m in report["mixed"]],
                         [(7, 9, "paragraph")])
        self.assertEqual(self.lean_text(text), text.replace(STYLE_COMMENT + "\n", ""))

    def test_an_uncatalogued_comment_paraphrase_stays_as_mixed(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Code signals\n"
            "\n"
            "<!-- Read by `scripts/signals.py` (v0.10+): backticked values only. -->\n"
            "<!-- Default when absent: twelve months. -->\n"
            "\n"
            "- Window: `12`\n"
        )
        report = self.lean_json(self.config(text))
        self.assertEqual([(m["start"], m["anchor"]) for m in report["mixed"]],
                         [(5, "Read by `scripts/signals.py`"), (6, "Default when absent")])
        self.assertEqual(self.lean_text(text), text)

    def test_apply_reports_mixed_blocks_at_their_written_lines(self):
        path = self.fixture("mixed-contract.md")
        proc = run_lean([path, "--apply", "--json"])
        self.assertEqual(proc.returncode, OK, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual([(m["start"], m["end"]) for m in report["mixed"]], [(10, 14)])
        written = path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(written[9].startswith("- Executive contract:"), written[9])
        self.assertTrue(written[13].endswith("a new launch agent, and any paid tool."), written[13])
        text_path = self.fixture("mixed-contract.md")
        proc = run_lean([text_path, "--apply"])
        self.assertEqual(proc.stdout.splitlines(), [
            "lean_config: 3 block(s) to remove, 1 mixed block(s) kept",
            "mixed: lines 10-14 (executive-contract) — " + HINT_CONTRACT,
        ])

    def test_a_mixed_block_inside_a_dropped_section_is_not_reported(self):
        section = (
            "## Journal\n"
            "\n"
            "Dial enforcement down by setting `enforce.stop_gate` or `enforce.auto_capture` to false\n"
            "in the sidecar (both default true). This team keeps the stop gate on.\n"
        )
        path = self.config("# shipgate — x\n\n" + section + "\n## Autonomy\n\n- Mode: ask\n")
        user = self.config("# me\n\n" + section, name="user.md")
        kept = self.lean_json(path, "--user", user)
        self.assertEqual([m["start"] for m in kept["mixed"]], [5])
        dropped = self.lean_json(path, "--user", user, "--drop-equal")
        self.assertEqual(self.ranges(dropped), [(3, 6, "section")])
        self.assertEqual(dropped["mixed"], [])

    def test_fixtures_without_project_prose_report_no_mixed_block(self):
        for name in ("hand-written.md", "before-0.25.0.md", "template-filled.md",
                     "template-filled-0.24.md"):
            with self.subTest(fixture=name):
                self.assertEqual(self.lean_json(self.fixture(name))["mixed"], [])
        self.assertEqual(self.lean_json(self.config(TEMPLATE.read_text(encoding="utf-8")))["mixed"], [])

    def test_only_equal_reports_no_mixed_block(self):
        path = self.fixture("mixed-contract.md")
        user = self.config("# me\n\n## Autonomy\n\n- Mode: ask\n", name="user.md")
        report = self.lean_json(path, "--user", user, "--only-equal")
        self.assertEqual((report["removals"], report["mixed"]), ([], []))


class TestHistory(LeanConfigTestCase):
    def test_every_historical_template_leans_to_its_title_with_no_mixed_block(self):
        for commit in TEMPLATE_HISTORY:
            with self.subTest(commit=commit):
                shown = subprocess.run(
                    ["git", "show", commit + ":shipgate/config-template.md"],
                    cwd=str(REPO), capture_output=True, text=True)
                if shown.returncode != 0:
                    self.skipTest("git show {} failed (a shallow clone?): {}".format(
                        commit, shown.stderr.strip()))
                path = self.config(shown.stdout, name="template-{}.md".format(commit))
                report = self.lean_json(path)
                self.assertEqual(report["mixed"], [])
                _proc, out = self.apply(path)
                self.assertEqual(out, shown.stdout.splitlines(True)[0])


class TestCatalogue(unittest.TestCase):
    def test_every_sentence_of_the_current_template_prose_is_catalogued(self):
        lean = load_lean_module()
        lines = [line.rstrip("\r\n") for line in
                 lean.split_lines(TEMPLATE.read_text(encoding="utf-8"))]
        checked = 0
        for block in lean.parse_blocks(lines):
            if block.kind in ("paragraph", "comment"):
                found = lean.sentences(block.body)
            elif block.kind == "bullet" and lean.select(block) is not None:
                found = lean.block_sentences(block, lean.select(block))
            else:
                continue
            for sentence in found:
                checked += 1
                with self.subTest(line=block.start + 1, sentence=sentence[:60]):
                    self.assertTrue(lean.is_catalogued(sentence))
        self.assertGreater(checked, 100)

    def test_the_sentence_split(self):
        lean = load_lean_module()
        self.assertEqual(lean.sentences(
            "**Position is recorded, not guessed.** Phase transitions are events. "
            "Run `a.b. C` now, e.g. Monday. See (below). 2 of them.\n"
            "1. the repo's file;\n2. the umbrella's file."), [
            "Position is recorded, not guessed", "Phase transitions are events",
            "Run `a.b. C` now, e.g. Monday", "See (below)", "2 of them",
            "the repo's file", "the umbrella's file"])

    def test_the_patterns_take_any_date_and_version(self):
        lean = load_lean_module()
        self.assertTrue(lean.is_catalogued(
            "Written by `/shipgate:setup` on 2031-01-02 — re-run it to change the journal or "
            "artifact homes rather than hand-editing those"))
        self.assertTrue(lean.is_catalogued(
            "Read by `shipgate/scripts/signals.py` itself (v1.2+): backticked values only, "
            "flags win"))
        self.assertFalse(lean.is_catalogued(
            "Written by `/shipgate:setup` on Monday — re-run it to change the journal or "
            "artifact homes rather than hand-editing those"))


class TestOnlyEqual(LeanConfigTestCase):
    PROJECT = (
        "# shipgate — x\n"
        "\n"
        "Every section is **optional**. Delete what you don't need.\n"
        "\n"
        "## Writing style\n"
        "\n"
        "- Docs: `ste-80`\n"
        "\n"
        "## Autonomy\n"
        "\n"
        + ASK_COMMENT + "\n"
        "\n"
        "- Mode: executive\n"
        "- Extra escalations: <if any>\n"
    )
    USER = "# me\n\n## Writing style\n\n- Docs: `ste-80`\n"

    def test_only_equal_removes_the_equal_section_and_keeps_every_boilerplate_block(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        args = ("--user", user, "--only-equal", "--drop-equal")
        report = self.lean_json(path, *args)
        self.assertEqual(self.ranges(report), [(5, 7, "section")])
        self.assertEqual(report["equal_sections"], ["Writing style"])
        proc = run_lean([path] + list(args))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[0],
                         "lean_config: 0 block(s) to remove, 1 section(s) equal to the user file")
        self.assertNotIn("Default when absent", "".join(
            line for line in proc.stdout.splitlines(True) if line.startswith("-")))
        _proc, out = self.apply(path, *args)
        self.assertEqual(out, self.PROJECT.replace("## Writing style\n\n- Docs: `ste-80`\n\n", ""))

    def test_only_equal_without_drop_equal_reports_and_changes_nothing(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        report = self.lean_json(path, "--user", user, "--only-equal")
        self.assertEqual(report["removals"], [])
        self.assertEqual(report["equal_sections"], ["Writing style"])
        self.assertFalse(report["changed"])

    def test_only_equal_without_user_exits_2(self):
        path = self.config(self.PROJECT)
        proc = run_lean([path, "--only-equal"])
        self.assertEqual(proc.returncode, USAGE, proc.stdout + proc.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), self.PROJECT)


class TestUmbrella(LeanConfigTestCase):
    PROJECT = TestUserFile.PROJECT
    USER = TestUserFile.USER
    UMBRELLA = (
        "# shipgate — the umbrella\n"
        "\n"
        "## Writing style\n"
        "\n"
        "- Docs: plain\n"
    )

    def test_an_equal_section_the_umbrella_holds_is_shadowed_not_dropped(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        umbrella = self.config(self.UMBRELLA, name="umbrella.md")
        args = ("--user", user, "--umbrella", umbrella, "--drop-equal")
        report = self.lean_json(path, *args)
        self.assertEqual(report["equal_sections"], ["Writing style"])
        self.assertEqual(report["shadowed_sections"], ["Writing style"])
        self.assertEqual(report["removals"], [])
        proc, out = self.apply(path, *args)
        self.assertEqual(proc.stdout, (
            "lean_config: 0 block(s) to remove, 1 section(s) equal to the user file, "
            "1 shadowed by the umbrella\n"))
        self.assertEqual(out, self.PROJECT)

    def test_inherit_none_in_the_project_file_ignores_the_umbrella(self):
        project = self.PROJECT.replace("# shipgate — x\n", "# shipgate — x\n\nInherit: none\n")
        path = self.config(project)
        user = self.config(self.USER, name="user.md")
        umbrella = self.config(self.UMBRELLA, name="umbrella.md")
        report = self.lean_json(path, "--user", user, "--umbrella", umbrella, "--drop-equal")
        self.assertEqual(report["shadowed_sections"], [])
        self.assertEqual(report["equal_sections"], ["Writing style"])
        self.assertEqual(self.ranges(report), [(5, 8, "section")])

    def test_an_umbrella_with_the_section_as_placeholders_only_does_not_shadow(self):
        path = self.config(self.PROJECT)
        user = self.config(self.USER, name="user.md")
        umbrella = self.config(
            "# u\n\n## Writing style\n\n- Docs: <plain | ste-80>\n", name="umbrella.md")
        other = self.config("# v\n\n## Autonomy\n\n- Mode: ask\n", name="other.md")
        report = self.lean_json(path, "--user", user, "--umbrella", umbrella,
                                "--umbrella", other, "--drop-equal")
        self.assertEqual(report["shadowed_sections"], [])
        self.assertEqual(self.ranges(report), [(3, 6, "section")])
        proc = run_lean([path, "--user", user, "--umbrella", umbrella])
        self.assertEqual(proc.stdout.splitlines()[0],
                         "lean_config: 0 block(s) to remove, 1 section(s) equal to the user file")


class TestPlaceholderRule(LeanConfigTestCase):
    BASE = "# shipgate — x\n\n## Notes\n\n- Keep: yes\n"

    def test_every_placeholder_case_is_removed(self):
        for value in PLACEHOLDER_CASES:
            with self.subTest(value=value):
                self.assertEqual(self.lean_text(self.BASE + "- Key: " + value + "\n"), self.BASE)

    def test_every_real_value_case_is_kept(self):
        cases = REAL_VALUE_CASES + ("<type>: <summary>", "<https://tracker.example/x>",
                                    "<@alice> and <@bob>")
        for value in cases:
            with self.subTest(value=value):
                text = self.BASE + "- Key: " + value + "\n"
                self.assertEqual(self.lean_text(text), text)

    def test_the_named_real_values_stay(self):
        text = (
            self.BASE
            + "- MR title: <type>: <summary>\n"
            + "- Issue tracker: <https://tracker.example/x>\n"
            + "- Reviewers: <@alice> and <@bob>\n"
        )
        self.assertEqual(self.lean_text(text), text)

    def test_a_placeholder_parent_with_a_real_nested_bullet_stays(self):
        for nested in ("  - MR title: <type>: <summary>\n", "  - Owner: <@alice>\n",
                       "  - Pattern: `feature/x`\n"):
            with self.subTest(nested=nested):
                text = self.BASE + "- Watcher: <the skill that watches MRs>\n" + nested
                self.assertEqual(self.lean_text(text), text)

    def test_a_placeholder_parent_with_placeholder_nested_bullets_goes(self):
        text = self.BASE + "- Watcher: <the skill>\n  - Command: <the command>\n"
        self.assertEqual(self.lean_text(text), self.BASE)

    def test_a_nested_bullet_after_a_blank_line_is_still_nested(self):
        text = self.BASE + "- Watcher: <the skill>\n\n  - Owner: `team-a`\n"
        self.assertEqual(self.lean_text(text), text)
        loose = self.BASE + "- Watcher: <the skill>\n\n  - Command: <the command>\n"
        self.assertEqual(self.lean_text(loose), self.BASE)

    def test_an_indented_paragraph_after_a_blank_line_stays_with_its_bullet(self):
        text = (self.BASE + "- Watcher: <the skill>\n\n  The watch list lives in `ops/watch.md`.\n"
                + "\n## Next\n\n- Mode: ask\n")
        self.assertEqual(self.lean_text(text), text)


class TestRecogniser(LeanConfigTestCase):
    def test_an_edited_anchor_is_kept(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "Every section is **required** here. Delete nothing; this repo reads them all.\n"
            "\n"
            "Copy this file into your repo as **`.claude/shipgate.md`** and fill in what applies.\n"
            "\n"
            "---\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        )
        path = self.config(text)
        self.assertEqual(self.lean_json(path)["removals"], [])
        self.assertEqual(self.lean_text(text), text)

    def test_a_comment_that_starts_with_other_text_is_kept(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Code signals\n"
            "\n"
            "<!-- We keep the Default when absent window on purpose: the repo is young. -->\n"
            "\n"
            "- Window: `12`\n"
            "  <!-- Read by humans only: the signals.py note above is ours. -->\n"
        )
        self.assertEqual(self.lean_text(text), text)

    def test_a_bullet_with_a_real_value_stays_whatever_its_key(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Autonomy\n"
            "\n"
            + ASK_COMMENT + "\n"
            "\n"
            "- Mode: executive\n"
            "- Extra escalations: any change to the billing export.\n"
            "- Integration branch: `main`.\n"
        )
        self.assertEqual(self.lean_text(text), (
            "# shipgate — x\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: executive\n"
            "- Extra escalations: any change to the billing export.\n"
            "- Integration branch: `main`.\n"
        ))

    def test_the_rule_stays_when_a_hand_written_paragraph_precedes_it(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "Every section is **optional**. Delete what you don't need.\n"
            "\n"
            "This repo is a monorepo; run the flow inside each service.\n"
            "\n"
            "---\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        )
        self.assertEqual(self.lean_text(text), (
            "# shipgate — x\n"
            "\n"
            "This repo is a monorepo; run the flow inside each service.\n"
            "\n"
            "---\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        ))

    def test_the_rule_goes_when_every_header_block_was_removed(self):
        text = (
            "# shipgate — x\n"
            "\n"
            + SETUP_HEADER
            + "\n"
            "---\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        )
        self.assertEqual(self.lean_text(text), "# shipgate — x\n\n## Autonomy\n\n- Mode: ask\n")

    def test_the_journal_keeps_its_database_and_loses_its_prose(self):
        template = (FIXTURES / "template-filled.md").read_text(encoding="utf-8")
        start = template.index("## Journal")
        end = template.index("## Forge & tracker")
        text = "# shipgate — x\n\n" + template[start:end].rstrip("\n") + "\n"
        self.assertEqual(
            self.lean_text(text),
            "# shipgate — x\n\n## Journal\n\n- Database: `.claude/shipgate.db`\n",
        )

    def test_earlier_template_wordings_are_removed(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Journal\n"
            "\n"
            "- Database: `.claude/shipgate.db`\n"
            "\n"
            "- **Capture is enforced by the plugin's hooks**, not by remembering: artifact writes are\n"
            "  recorded automatically, and a session cannot end while an expected event is missing.\n"
            "  The hooks read `.claude/shipgate.json` (a generated sidecar holding the database path,\n"
            "  the artifact-home globs, and the ledger path) — `setup` writes it; never hand-edit it,\n"
            "  re-run `setup` instead. If that sidecar is absent, every hook exits immediately and the project\n"
            "  behaves as un-journaled.\n"
            "\n"
            "**Event names are a fixed vocabulary.** `journal.py vocab` lists them and `append` refuses\n"
            "anything else, because an event named something plausible-but-unlisted is inert — it\n"
            "records, and no gate or report ever reads it, which looks like success. Pass `--new-type`\n"
            "to mint a genuinely new concept on purpose. Stream names are free: `feature/<slug>` or the\n"
            "branch (`fix/1290-date-off-by-one`) both work. `journal.py doctor` reports any off-vocabulary\n"
            "events already in a journal.\n"
            "\n"
            "## Code tooling\n"
            "\n"
            "<!-- Default when absent: no library-docs integration (training knowledge / WebFetch);\n"
            "     no LSP preference (grep/read). -->\n"
            "\n"
            "- Code graph: off\n"
            "\n"
            "## Code signals\n"
            "\n"
            "<!-- Read by `shipgate/scripts/signals.py` itself (v0.13+): backticked values only, flags\n"
            "     win. Defaults when absent: 12-month window, built-in fix pattern, built-in excludes. -->\n"
            "\n"
            "The one section a script reads rather than the model: `scripts/signals.py` takes these three\n"
            "bullets' backticked values (command-line flags still win), so the terminal and the flow\n"
            "compute the same numbers.\n"
            "\n"
            "- Window: `12`\n"
        )
        self.assertEqual(self.lean_text(text), (
            "# shipgate — x\n"
            "\n"
            "## Journal\n"
            "\n"
            "- Database: `.claude/shipgate.db`\n"
            "\n"
            "## Code tooling\n"
            "\n"
            "- Code graph: off\n"
            "\n"
            "## Code signals\n"
            "\n"
            "- Window: `12`\n"
        ))

    def test_every_executive_contract_paraphrase_is_removed(self):
        for bullet in EXECUTIVE_CONTRACTS:
            with self.subTest(bullet=bullet.splitlines()[0]):
                text = (
                    "# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n" + bullet
                    + "- Extra escalations: publishing a release.\n"
                )
                report = self.lean_json(self.config(text))
                self.assertEqual(
                    [(r["kind"], r["anchor"]) for r in report["removals"]],
                    [("bullet", "executive-contract")],
                )
                self.assertEqual(self.lean_text(text), (
                    "# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n"
                    "- Extra escalations: publishing a release.\n"
                ))

    def test_a_contract_with_a_placeholder_value_goes_as_a_placeholder(self):
        text = ("# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n"
                "- Executive contract: <the contract the `feature` skill holds>\n")
        report = self.lean_json(self.config(text))
        self.assertEqual([(r["start"], r["anchor"]) for r in report["removals"]],
                         [(6, "placeholder")])
        self.assertEqual(report["mixed"], [])

    def test_a_contract_key_with_a_colon_inside_its_parenthesis_reads_its_sentences(self):
        bullet = EXECUTIVE_CONTRACTS[1].replace(
            "- Executive contract:", "- Executive contract (see: the feature skill):", 1)
        text = "# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n" + bullet
        report = self.lean_json(self.config(text))
        self.assertEqual([(r["kind"], r["anchor"]) for r in report["removals"]],
                         [("bullet", "executive-contract")])
        self.assertEqual(self.lean_text(text), "# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n")

    def test_a_contract_with_an_uncatalogued_sentence_stays_as_mixed(self):
        for bullet in MIXED_CONTRACTS:
            with self.subTest(bullet=bullet.splitlines()[0]):
                text = (
                    "# shipgate — x\n\n## Autonomy\n\n- Mode: executive\n" + bullet
                    + "- Extra escalations: publishing a release.\n"
                )
                report = self.lean_json(self.config(text))
                self.assertEqual(report["removals"], [])
                self.assertEqual(report["mixed"], [{
                    "start": 6, "end": 5 + len(bullet.splitlines()), "kind": "bullet",
                    "anchor": "executive-contract", "hint": HINT_CONTRACT}])
                self.assertEqual(self.lean_text(text), text)

    def test_placeholders_are_whole_angle_bracket_values(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Forge & tracker\n"
            "\n"
            "- Forge: <GitHub | GitLab | …> — CLI: <gh | glab | …>\n"
            "- Issue tracker: GitHub issues — <the MCP/CLI to read them with>\n"
            "\n"
            "## Branching\n"
            "\n"
            "- Pattern: <type>/<slug>\n"
            "- Examples: `<type>/<issue-id>-<slug>`\n"
        )
        self.assertEqual(self.lean_text(text), (
            "# shipgate — x\n"
            "\n"
            "## Forge & tracker\n"
            "\n"
            "- Issue tracker: GitHub issues — <the MCP/CLI to read them with>\n"
            "\n"
            "## Branching\n"
            "\n"
            "- Pattern: <type>/<slug>\n"
            "- Examples: `<type>/<issue-id>-<slug>`\n"
        ))

    def test_a_section_empty_to_begin_with_stays(self):
        text = "# shipgate — x\n\n## Release train\n\n## Autonomy\n\n- Mode: ask\n"
        self.assertEqual(self.lean_text(text), text)

    def test_an_inherit_line_under_the_title_stays(self):
        header = (
            "Every section is **optional**. Delete what you don't need.\n"
        )
        for inherit in ("Inherit: none", "- Inherit: none", "- inherit: `none`", "`Inherit`: none"):
            with self.subTest(inherit=inherit):
                text = (
                    "# shipgate — x\n\n" + inherit + "\n\n" + header
                    + "\n## Autonomy\n\n- Mode: ask\n"
                )
                self.assertEqual(
                    self.lean_text(text),
                    "# shipgate — x\n\n" + inherit + "\n\n## Autonomy\n\n- Mode: ask\n",
                )

    def test_an_inherit_line_never_joins_a_removed_paragraph(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "Every section is **optional**. Delete what you don't need.\n"
            "Inherit: none\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        )
        self.assertEqual(
            self.lean_text(text),
            "# shipgate — x\n\nInherit: none\n\n## Autonomy\n\n- Mode: ask\n",
        )

    def test_a_hand_written_ordered_list_stays(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "1. the repo's `.claude/shipgate.md` wins for this service;\n"
            "2. nothing else is read.\n"
            "\n"
            "## Autonomy\n"
            "\n"
            "- Mode: ask\n"
        )
        self.assertEqual(self.lean_text(text), text)

    def test_a_comment_with_text_after_its_close_stays(self):
        for comment in ("<!-- Default when absent: 12 months. --> We use 6.\n",
                        "<!-- Default when absent: 12 months,\n     we use 6. --> see below\n"):
            with self.subTest(comment=comment):
                text = "# shipgate — x\n\n## Code signals\n\n" + comment + "\n- Window: `6`\n"
                self.assertEqual(self.lean_text(text), text)

    def test_an_info_string_line_does_not_close_a_fence(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Notes\n"
            "\n"
            "```markdown\n"
            "<!-- Default when absent: an example. -->\n"
            "```python\n"
            "<!-- Default when absent: still inside the fence. -->\n"
            "- Mode: <ask | executive>\n"
            "````\n"
            "\n"
            "- Keep: yes\n"
        )
        self.assertEqual(self.lean_text(text), text)

    def test_short_anchors_match_comments_only(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Code signals\n"
            "\n"
            "Default when absent the window is 12 months; this repo keeps it.\n"
            "\n"
            "Usually personal settings live in the user file; these are the team's.\n"
            "\n"
            "Read by `signals.py`: the two bullets below.\n"
            "\n"
            "Only needed for umbrella checkouts, which this repo is not.\n"
            "\n"
            "<!-- Usually personal, but the team agreed on it. -->\n"
            "\n"
            "Dial enforcement down only with the team's agreement.\n"
            "\n"
            "- Window: `12`\n"
        )
        self.assertEqual(self.lean_text(text), text)

    def test_two_paragraphs_around_a_removed_comment_stay_apart(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "Para one\n"
            + STYLE_COMMENT + "\n"
            "Para two\n"
        )
        path = self.config(text)
        _proc, out = self.apply(path)
        self.assertEqual(out, "# shipgate — x\n\nPara one\n\nPara two\n")
        self.assertEqual(self.lean_json(path)["removals"], [])

    def test_the_layer_list_goes_only_in_its_catalogued_wording(self):
        rest = (
            "2. the umbrella's `.claude/shipgate.md`, in an umbrella checkout;\n"
            "3. the user file: `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set and not empty,\n"
            "   else `~/.claude/shipgate.md`;\n"
            "4. the built-in defaults noted per section.\n"
            "\n## Autonomy\n\n- Mode: ask\n"
        )
        current = ("# shipgate — x\n\n1. the repo's `.claude/shipgate.md` files, from the working "
                   "directory up to the repo root;\n" + rest)
        self.assertEqual(self.lean_text(current), "# shipgate — x\n\n## Autonomy\n\n- Mode: ask\n")
        draft = "# shipgate — x\n\n1. the repo's `.claude/shipgate.md`;\n" + rest
        report = self.lean_json(self.config(draft))
        self.assertEqual(report["removals"], [])
        self.assertEqual([(m["start"], m["end"], m["hint"]) for m in report["mixed"]],
                         [(3, 7, HINT_PROSE)])

    def test_fenced_code_is_never_removed(self):
        text = (
            "# shipgate — x\n"
            "\n"
            "## Notes\n"
            "\n"
            "```\n"
            "<!-- Default when absent: an example. -->\n"
            "- Mode: <ask | executive>\n"
            "```\n"
        )
        self.assertEqual(self.lean_text(text), text)


if __name__ == "__main__":
    unittest.main()
