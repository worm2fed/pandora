#!/usr/bin/env python3
"""Unit tests for shipgate's ``scripts/_config.py``, the shared config reader (ADR 0018).

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_config.py'

In-process tests; every file lives in a temp directory, and every test that resolves
the user file patches ``CLAUDE_CONFIG_DIR`` or ``HOME``.
"""

from __future__ import annotations

import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
CONFIG = TESTS_DIR.parent / "scripts" / "_config.py"
TEMPLATE = TESTS_DIR.parent / "config-template.md"

# Whole-value placeholders from the config template that hold backticks inside.
TEMPLATE_PRD_HOME = "<path, e.g. `docs/prd/` or a wiki path>"
TEMPLATE_WORKLOG_HOME = "<path — usually beside the PRD as `<name>.worklog.md`>"


def template_placeholder_values():
    """The value of every template bullet that opens with `<` (backticked or not),
    wrapped lines joined until its angle brackets balance."""
    text = re.sub(r"<!--.*?-->", "", TEMPLATE.read_text(encoding="utf-8"), flags=re.S)
    values, current, depth = [], None, 0
    for line in text.splitlines():
        if current is None:
            bullet = re.match(r"^\s*[-*+]\s+[^:]+?:\s*(`?<.*)$", line)
            if not bullet:
                continue
            current = bullet.group(1).rstrip()
        else:
            current += " " + line.strip()
        depth = current.count("<") - current.count(">")
        if depth <= 0:
            values.append(current)
            current = None
    return tuple(values)


# The one placeholder rule (`_config.is_placeholder_value`), shared with the
# boilerplate recogniser's tests: `from test_config import PLACEHOLDER_CASES, ...`.
PLACEHOLDER_CASES = (
    "<a> <b>",
    "<months, e.g. 18>",
    "`<regex over the commit subject>`",
    "  <path>  ",
    "<a>, <b>",
    "<a> | <b>",
    "<GitHub | GitLab | …> — CLI: <gh | glab | …>",
    TEMPLATE_PRD_HOME,
    TEMPLATE_WORKLOG_HOME,
    "<e.g.: x>",
    "<path: e.g. docs/prd>",
) + template_placeholder_values()

REAL_VALUE_CASES = (
    "plain",
    "12",
    "``",
    "",
    "<type>/<slug>",
    "`<type>/<issue-id>-<slug>`",
    "<type>/<issue-id>-<slug>",
    "<type>: <summary>",
    "<https://tracker.example/x>",
    "<ops@example.test>",
    "<mailto:ops@example.test>",
    "<@alice> and <@bob>",
    "<a><b>",
    "<a> and <b>",
    "<a",
    "a>",
    "<a>>",
    "<a> b",
)


def load_config_module():
    """Import _config.py directly: `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("shipgate_config", CONFIG)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cfg = load_config_module()


class TestConstants(unittest.TestCase):
    def test_the_names_other_scripts_load(self):
        self.assertEqual(cfg.CONFIG_RELPATH, os.path.join(".claude", "shipgate.md"))
        self.assertEqual(cfg.USER_CONFIG_NAME, "shipgate.md")
        self.assertEqual(cfg.KNOWLEDGE_SECTION, "knowledge base")
        self.assertIs(cfg.BACKTICK_RE, cfg._BACKTICK_RE)
        self.assertEqual(cfg.BACKTICK_RE.findall("`a` b `c`"), ["a", "c"])
        self.assertEqual((cfg.ROLE_PROJECT, cfg.ROLE_UMBRELLA, cfg.ROLE_USER),
                         ("project", "umbrella", "user"))


class TestSectionBullets(unittest.TestCase):
    def test_reads_one_section_and_joins_a_wrapped_line(self):
        text = ("# T\n\n## Code signals\n<!-- - Window: `1` -->\n- Window: `3`\n"
                "- Exclude: `a/`,\n  `b/`\n## Next\n- Window: `9`\n")
        self.assertEqual(cfg.section_bullets(text, "code signals"),
                         [("window", "`3`"), ("exclude", "`a/`, `b/`")])

    def test_a_fenced_heading_does_not_end_the_section(self):
        text = "## Code signals\n```\n## no\n- Window: `1`\n```\n- Window: `2`\n"
        self.assertEqual(cfg.section_bullets(text, "code signals"), [("window", "`2`")])


class TestTitleBullets(unittest.TestCase):
    def test_stops_at_the_first_level_two_heading(self):
        text = "# Title\n\n- Inherit: none\n- Owner: `x`\n\n## Section\n- Inherit: other\n"
        self.assertEqual(cfg.title_bullets(text),
                         [("inherit", "none"), ("owner", "`x`")])

    def test_a_deeper_heading_also_ends_the_title_block(self):
        self.assertEqual(cfg.title_bullets("# T\n### Deep\n- Inherit: none\n"), [])

    def test_a_bare_key_line_counts(self):
        self.assertEqual(cfg.title_bullets("# T\n\nInherit: none\n"),
                         [("inherit", "none")])

    def test_comments_and_fenced_code_are_inert(self):
        text = ("# T\n<!-- - Inherit: none -->\n<!--\nInherit: none\n-->\n"
                "```\n- Inherit: none\n## not a heading\n```\n"
                "  ~~~\n  Inherit: none\n  ~~~\n- Mode: `x`\n## S\n")
        self.assertEqual(cfg.title_bullets(text), [("mode", "`x`")])

    def test_text_before_any_title_counts_too(self):
        self.assertEqual(cfg.title_bullets("- Inherit: none\n# T\n"),
                         [("inherit", "none")])

    def test_the_template_header_holds_no_inherit_line(self):
        """The header explains `Inherit: none`; it must not read as one."""
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("inherit", [key for key, _ in cfg.title_bullets(text)])
        self.assertEqual(cfg.inherit_mode(text), "umbrella")

    def test_prose_and_quotes_are_not_bullets(self):
        text = "# T\n\n> Note: this is a quote\nSome prose, with: a colon later.\n"
        keys = [key for key, _ in cfg.title_bullets(text)]
        self.assertNotIn("inherit", keys)
        self.assertNotIn("> note", keys)


class TestInheritMode(unittest.TestCase):
    def test_none_forms(self):
        for line in ("Inherit: none", "- Inherit: none", "- Inherit: `none`",
                     "Inherit: `NONE`", "* inherit:   None  ", "INHERIT: none"):
            with self.subTest(line=line):
                self.assertEqual(cfg.inherit_mode(f"# Repo\n\n{line}\n\n## S\n"), "none")

    def test_the_first_word_of_the_value_decides(self):
        for value, mode in (("none — see the umbrella", "none"), ("`none`, for now", "none"),
                            ("None.", "none"), ("umbrella — the default", "umbrella"),
                            ("**none**", "none"), ("_none_", "none"),
                            ("*`none`*, for now", "none")):
            with self.subTest(value=value):
                self.assertEqual(cfg.inherit_mode(f"# Repo\nInherit: {value}\n"), mode)

    def test_everything_else_is_umbrella(self):
        for text in ("# Repo\n", "# Repo\n- Inherit: umbrella\n",
                     "# Repo\n- Inherit: <none | umbrella>\n",
                     "# Repo\n- Inherit: nonesuch\n",
                     "# Repo\n## Section\n- Inherit: none\n",
                     "# Repo\n<!-- Inherit: none -->\n", ""):
            with self.subTest(text=text):
                self.assertEqual(cfg.inherit_mode(text), "umbrella")


class TestSectionPresent(unittest.TestCase):
    def present(self, body):
        return cfg.section_present(f"# T\n## Code signals\n{body}## Next\n- X: `1`\n",
                                   "code signals")

    def test_a_real_value_makes_the_section_present(self):
        for body in ("- Window: `3`\n", "- Window: 3\n",
                     "- Window: `<n>`\n- Exclude: `a/`\n",
                     "- Exclude: `<globs>`, `a/`\n"):
            with self.subTest(body=body):
                self.assertTrue(self.present(body))

    def test_placeholders_only_or_no_bullets_is_absent(self):
        for body in ("", "Prose only.\n", "- Window: `<months>`\n",
                     "- Window: <months>\n- Fix pattern:\n",
                     "- Exclude: `<a>`, `<b>`\n", "<!-- - Window: `3` -->\n"):
            with self.subTest(body=body):
                self.assertFalse(self.present(body))

    def test_a_whole_value_placeholder_with_backticks_inside_is_absent(self):
        for value in (TEMPLATE_PRD_HOME, TEMPLATE_WORKLOG_HOME,
                      "<path of the inbox.\n  Default when absent: `docs/ledger.md`>"):
            with self.subTest(value=value):
                self.assertFalse(self.present(f"- Home: {value}\n"))

    def test_the_unfilled_template_has_no_section_present(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        for section in ("knowledge base", "code tooling", "code signals"):
            with self.subTest(section=section):
                self.assertFalse(cfg.section_present(text, section))

    def test_an_empty_backticked_value_is_a_value(self):
        """`Ranking exclude: ``` turns the built-in list off: it is a real value."""
        self.assertTrue(self.present("- Ranking exclude: ``\n"))

    def test_a_missing_heading_is_absent(self):
        self.assertFalse(cfg.section_present("# T\n- Window: `3`\n", "code signals"))


class TestBulletValue(unittest.TestCase):
    def test_first_backticked_span_else_the_bare_value(self):
        self.assertEqual(cfg.bullet_value("`docs/ledger.md` (the ledger)"),
                         "docs/ledger.md")
        self.assertEqual(cfg.bullet_value("`a`, `b`"), "a")
        self.assertEqual(cfg.bullet_value("  docs/ledger.md  "), "docs/ledger.md")

    def test_a_placeholder_is_none(self):
        for value in ("`<path>`", "<path>", "", "   ", "``", TEMPLATE_PRD_HOME,
                      TEMPLATE_WORKLOG_HOME, "  " + TEMPLATE_PRD_HOME + "  "):
            with self.subTest(value=value):
                self.assertIsNone(cfg.bullet_value(value))


class TestIsPlaceholder(unittest.TestCase):
    def test_forms(self):
        self.assertTrue(cfg.is_placeholder(""))
        self.assertTrue(cfg.is_placeholder("  <x | y>  "))
        self.assertFalse(cfg.is_placeholder("x"))
        self.assertFalse(cfg.is_placeholder("<x> y"))

    def test_every_placeholder_case_is_a_placeholder(self):
        for value in PLACEHOLDER_CASES:
            with self.subTest(value=value):
                self.assertTrue(cfg.is_placeholder_value(value))
                self.assertTrue(cfg.is_placeholder(value))

    def test_every_real_value_case_is_not_a_placeholder(self):
        for value in REAL_VALUE_CASES:
            with self.subTest(value=value):
                self.assertFalse(cfg.is_placeholder_value(value))
        self.assertTrue(cfg.is_placeholder(""))  # empty is a placeholder for a bullet

    def test_the_template_yields_its_placeholder_lines(self):
        values = template_placeholder_values()
        self.assertGreaterEqual(len(values), 30)
        self.assertIn(TEMPLATE_PRD_HOME, values)
        self.assertIn("<GitHub | GitLab | …> — CLI: <gh | glab | …>", values)

    def test_a_real_value_with_angle_brackets_makes_a_section_present(self):
        for value in ("`<type>/<issue-id>-<slug>`", "<type>: <summary>"):
            with self.subTest(value=value):
                self.assertTrue(cfg.section_present(f"## Branching\n- Pattern: {value}\n",
                                                    "branching"))
                self.assertIsNotNone(cfg.bullet_value(value))


class TestUserConfigPath(unittest.TestCase):
    def test_the_variable_names_the_directory(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/cfg/dir"}):
            self.assertEqual(cfg.user_config_path(), Path("/cfg/dir") / "shipgate.md")

    def test_a_tilde_in_the_variable_expands(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "~/alt",
                                          "HOME": "/home/alice"}):
            self.assertEqual(cfg.user_config_path(),
                             Path("/home/alice") / "alt" / "shipgate.md")

    def test_unset_or_empty_falls_back_to_the_home_directory(self):
        for value in (None, ""):
            with self.subTest(value=value):
                env = {"HOME": "/home/alice"}
                if value is not None:
                    env["CLAUDE_CONFIG_DIR"] = value
                with mock.patch.dict(os.environ, env):
                    if value is None:
                        os.environ.pop("CLAUDE_CONFIG_DIR", None)
                    self.assertEqual(cfg.user_config_path(),
                                     Path("/home/alice") / ".claude" / "shipgate.md")

    def test_no_home_directory_is_none(self):
        with mock.patch.dict(os.environ, {}), \
                mock.patch.object(cfg.Path, "home", side_effect=RuntimeError("no home")):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertIsNone(cfg.user_config_path())


class LayersCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def file(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestReadLayers(LayersCase):
    def test_reads_existing_files_in_order_and_appends_the_user_file(self):
        near = self.file("repo/sub/.claude/shipgate.md", "near")
        repo = self.tmp / "repo/.claude/shipgate.md"  # missing: skipped
        umbrella = self.file("u/.claude/shipgate.md", "umbrella")
        user = self.file("cfg/shipgate.md", "user")
        files = cfg.read_layers([(near, "project"), (repo, "project"),
                                 (umbrella, "umbrella")], user)
        self.assertEqual([(f.path, f.role, f.text) for f in files],
                         [(near, "project", "near"), (umbrella, "umbrella", "umbrella"),
                          (user, "user", "user")])

    def test_a_missing_user_file_or_none_adds_nothing(self):
        repo = self.file("repo/.claude/shipgate.md", "repo")
        for user in (None, self.tmp / "cfg" / "shipgate.md"):
            with self.subTest(user=user):
                files = cfg.read_layers([(repo, "project")], user)
                self.assertEqual([f.role for f in files], ["project"])

    def test_a_directory_in_place_of_a_file_is_skipped(self):
        (self.tmp / "repo/.claude/shipgate.md").mkdir(parents=True)
        self.assertEqual(cfg.read_layers(
            [(self.tmp / "repo/.claude/shipgate.md", "project")], None), [])

    def test_dedupe_by_resolved_path_keeps_the_first_occurrence(self):
        home = self.file("home/.claude/shipgate.md", "home")
        (self.tmp / "link").symlink_to(self.tmp / "home", target_is_directory=True)
        alias = self.tmp / "link" / ".claude" / "shipgate.md"
        files = cfg.read_layers([(home, "umbrella"), (alias, "umbrella")], home)
        self.assertEqual([(f.path, f.role) for f in files], [(home, "umbrella")])

    def test_inherit_none_in_the_nearest_project_file_drops_every_umbrella_file(self):
        repo = self.file("repo/.claude/shipgate.md", "# Repo\n\nInherit: none\n")
        mid = self.file("u/.claude/shipgate.md", "## Code signals\n- Window: `9`\n")
        far = self.file("v/.claude/shipgate.md", "## Code signals\n- Window: `8`\n")
        user = self.file("cfg/shipgate.md", "## Code signals\n- Window: `7`\n")
        files = cfg.read_layers([(repo, "project"), (mid, "umbrella"),
                                 (far, "umbrella")], user)
        self.assertEqual([f.role for f in files], ["project", "user"])

    def test_only_the_nearest_project_file_decides(self):
        near = self.file("repo/sub/.claude/shipgate.md", "# Sub\n")
        repo = self.file("repo/.claude/shipgate.md", "# Repo\n- Inherit: none\n")
        umbrella = self.file("u/.claude/shipgate.md", "# U\n")
        files = cfg.read_layers([(near, "project"), (repo, "project"),
                                 (umbrella, "umbrella")], None)
        self.assertEqual([f.role for f in files], ["project", "project", "umbrella"])

    def test_without_a_project_file_the_nearest_umbrella_file_decides(self):
        """It keeps itself and drops the farther umbrella files."""
        mid = self.file("u/.claude/shipgate.md", "# U\nInherit: none\n")
        far = self.file("v/.claude/shipgate.md", "# V\n")
        files = cfg.read_layers([(self.tmp / "repo/.claude/shipgate.md", "project"),
                                 (mid, "umbrella"), (far, "umbrella")], None)
        self.assertEqual([f.path for f in files], [mid])

    def test_inherit_none_drops_a_home_file_read_as_an_umbrella(self):
        """ADR 0018: when $HOME is a git work tree, ~/.claude/shipgate.md is first an
        umbrella candidate; the dedupe keeps that role, and Inherit: none drops it."""
        repo = self.file("home/repo/.claude/shipgate.md", "# Repo\nInherit: none\n")
        home = self.file("home/.claude/shipgate.md", "# Home\n")
        files = cfg.read_layers([(repo, "project"), (home, "umbrella")], home)
        self.assertEqual([f.path for f in files], [repo])


class TestSectionOwner(LayersCase):
    def test_the_first_file_with_the_section_present_owns_it(self):
        files = [cfg.ConfigFile(Path("a"), "project", "## Code signals\n- Window: `<n>`\n"),
                 cfg.ConfigFile(Path("b"), "umbrella", "## Code tooling\n- Code graph: off\n"),
                 cfg.ConfigFile(Path("c"), "user", "## Code signals\n- Window: `4`\n")]
        self.assertEqual(cfg.section_owner(files, "code signals").path, Path("c"))
        self.assertEqual(cfg.section_owner(files, "code tooling").path, Path("b"))
        self.assertIsNone(cfg.section_owner(files, "knowledge base"))
        self.assertIsNone(cfg.section_owner([], "code signals"))

    def test_a_present_predicate_replaces_the_general_rule(self):
        files = [cfg.ConfigFile(Path("a"), "project", "## Code signals\n- Window: 18\n"),
                 cfg.ConfigFile(Path("b"), "umbrella", "## Code signals\n- Window: `9`\n")]
        self.assertEqual(cfg.section_owner(files, "code signals").path, Path("a"))
        owner = cfg.section_owner(files, "code signals",
                                  lambda text: "`" in text)
        self.assertEqual(owner.path, Path("b"))


if __name__ == "__main__":
    unittest.main()
