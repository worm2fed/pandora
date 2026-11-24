#!/usr/bin/env python3
"""Tests of the settings files (ADR 0028): the schema, the resolver in
``scripts/_config.py`` and ``journal.py config``.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_settings.py'

Every file lives in a temp directory. Every test that resolves the user files sets
``CLAUDE_CONFIG_DIR`` to a temp directory, so the maintainer's real files never reach a
test (ADR 0018's isolation rule).
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN = TESTS_DIR.parent
SCHEMA = PLUGIN / "settings.schema.json"
CONFIG = PLUGIN / "scripts" / "_config.py"


def load_config_module():
    spec = importlib.util.spec_from_file_location("shipgate_config_settings", CONFIG)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def flat_defaults(schema):
    """Each leaf key of the schema with its default, `group.leaf` for an object."""
    out = {}
    for key, node in schema["properties"].items():
        if node.get("type") == "object" and "properties" in node:
            for leaf, sub in node["properties"].items():
                out[f"{key}.{leaf}"] = sub.get("default")
        else:
            out[key] = node.get("default")
    return out


# The leaf keys the Data model table of the worklog names, in table order.
TABLE_KEYS = (
    "version", "db", "ledger",
    "artifact_homes.prd", "artifact_homes.adr", "artifact_homes.worklog",
    "enforce.stop_gate", "enforce.auto_capture", "enforce.command_gate",
    "autonomy", "orchestration.review", "orchestration.explore", "writing_style",
    "code_graph", "code_signals.window_months", "code_signals.fix_pattern",
    "code_signals.exclude", "code_signals.ranking_exclude", "handoff", "forge",
)

# Key → the legacy (section, bullet) the table names.
TABLE_LEGACY = {
    "autonomy": ("Autonomy", "Mode"),
    "orchestration.review": ("Orchestration", "review"),
    "orchestration.explore": ("Orchestration", "explore"),
    "writing_style": ("Writing style", "Docs"),
    "code_graph": ("Code tooling", "Code graph"),
    "code_signals.window_months": ("Code signals", "Window"),
    "code_signals.fix_pattern": ("Code signals", "Fix pattern"),
    "code_signals.exclude": ("Code signals", "Exclude"),
    "code_signals.ranking_exclude": ("Code signals", "Ranking exclude"),
    "handoff": ("Session", "Handoff"),
    "forge": ("Forge & tracker", "Forge"),
    "ledger": ("Knowledge base", "Ledger"),
    "artifact_homes.prd": ("Knowledge base", "PRD home"),
    "artifact_homes.adr": ("Knowledge base", "ADR home"),
    "artifact_homes.worklog": ("Knowledge base", "Worklog home"),
}

PROJECT_SCOPE = ("version", "db", "ledger", "artifact_homes", "enforce", "code_signals",
                 "forge")


class TestSchema(unittest.TestCase):
    """T002: `settings.schema.json` holds the Data model table, and its defaults equal
    the copies the readers keep."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_version_and_grace(self):
        """The migration release (0.33.0) set the grace date: release day plus 60 days
        (ADR 0028, item 8). The README names the same date."""
        self.assertEqual(self.schema["x-version"], 2)
        until = self.schema["x-legacy-until"]
        self.assertIsInstance(until, str)
        self.assertGreaterEqual(date.fromisoformat(until), date(2027, 1, 23))
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.assertIn(until, readme)

    def test_every_table_key_and_no_other(self):
        self.assertEqual(sorted(flat_defaults(self.schema)), sorted(TABLE_KEYS))

    def test_each_key_has_scope_and_since(self):
        for key, node in self.schema["properties"].items():
            with self.subTest(key=key):
                expected = "project" if key in PROJECT_SCOPE else "any"
                self.assertEqual(node.get("x-scope"), expected)
                self.assertRegex(node.get("x-since", ""), r"^\d+\.\d+\.\d+$")

    def test_each_leaf_has_a_type_or_a_set(self):
        for key, node in self.schema["properties"].items():
            leaves = (node["properties"].items()
                      if node.get("type") == "object" and "properties" in node
                      else [(key, node)])
            for leaf, sub in leaves:
                with self.subTest(key=key, leaf=leaf):
                    self.assertTrue({"type", "enum", "anyOf"} & set(sub))
                    self.assertIn("default", sub)

    def test_legacy_sources(self):
        found = {}
        for key, node in self.schema["properties"].items():
            if "x-legacy" in node:
                found[key] = (node["x-legacy"]["section"], node["x-legacy"]["key"])
            for leaf, sub in node.get("properties", {}).items():
                if "x-legacy" in sub:
                    found[f"{key}.{leaf}"] = (sub["x-legacy"]["section"],
                                              sub["x-legacy"]["key"])
        self.assertEqual(found, TABLE_LEGACY)

    def test_defaults_equal_the_readers_copies(self):
        from test_journal import load_journal_module
        from test_signals import load_signals_module

        journal = load_journal_module()
        signals = load_signals_module()
        defaults = flat_defaults(self.schema)
        homes = {k.split(".", 1)[1]: v for k, v in defaults.items()
                 if k.startswith("artifact_homes.")}
        self.assertEqual(homes, journal.DEFAULT_ARTIFACT_HOMES)
        self.assertEqual(defaults["ledger"], journal.DEFAULT_LEDGER)
        self.assertEqual(defaults["db"], journal.DEFAULT_DB_RELPATH)
        self.assertEqual(defaults["handoff"], "500k")
        self.assertEqual(journal.parse_handoff_threshold(defaults["handoff"]),
                         journal.DEFAULT_HANDOFF_TOKENS)
        graph = self.schema["properties"]["code_graph"]
        self.assertEqual(tuple(graph["enum"]), signals.GRAPH_MODES)
        self.assertEqual(graph["default"], signals.DEFAULT_GRAPH_MODE)
        window = self.schema["properties"]["code_signals"]["properties"]["window_months"]
        self.assertEqual(window["maximum"], signals.MAX_WINDOW_MONTHS)
        self.assertEqual(window["default"], signals.DEFAULT_WINDOW_MONTHS)


class SettingsCase(unittest.TestCase):
    """A temp project root with a repo, a user directory and helpers to resolve."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "project"
        (self.root / ".git").mkdir(parents=True)
        self.user = self.base / "user"
        self.user.mkdir()
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.user)})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = load_config_module()

    def project_json(self, data, raw=None):
        path = self.root / ".claude" / "shipgate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return path

    def user_json(self, data, raw=None):
        path = self.user / "shipgate.settings.json"
        path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return path

    def project_md(self, text, directory=None):
        path = (directory or self.root) / ".claude" / "shipgate.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def user_md(self, text):
        path = self.user / "shipgate.md"
        path.write_text(text, encoding="utf-8")
        return path

    def resolve(self, candidates=None, today=None):
        candidates = candidates if candidates is not None else [
            (self.root / ".claude" / "shipgate.md", self.cfg.ROLE_PROJECT)]
        files = self.cfg.read_layers(candidates, self.cfg.user_config_path())
        project = self.root / ".claude" / "shipgate.json"
        return self.cfg.resolve_settings(
            project if project.is_file() else None, files,
            self.cfg.user_settings_path(), today=today)

    def kinds(self, resolved):
        return sorted((p.kind, p.key) for p in resolved.problems)


class TestUserSettingsPath(unittest.TestCase):
    """`user_settings_path`: the rule of `user_config_path`, another name."""

    def setUp(self):
        self.cfg = load_config_module()

    def test_set(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/cfg/dir"}):
            self.assertEqual(self.cfg.user_settings_path(),
                             Path("/cfg/dir/shipgate.settings.json"))

    def test_unset_and_empty_use_the_home_directory(self):
        for value in (None, ""):
            with self.subTest(value=value):
                env = {"HOME": "/home/alice"}
                if value is not None:
                    env["CLAUDE_CONFIG_DIR"] = value
                with mock.patch.dict(os.environ, env):
                    if value is None:
                        os.environ.pop("CLAUDE_CONFIG_DIR", None)
                    self.assertEqual(
                        self.cfg.user_settings_path(),
                        Path("/home/alice/.claude/shipgate.settings.json"))

    def test_no_walk_finds_the_name(self):
        self.assertNotEqual(self.cfg.USER_SETTINGS_NAME, "shipgate.json")


class TestResolveOrder(SettingsCase):
    """Per key, nearest first: project file, project legacy, user file, user legacy,
    default (L1), each with its source (SC-002)."""

    def test_defaults_with_no_file(self):
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "ask")
        self.assertEqual(resolved.get("autonomy").source, "default")
        self.assertEqual(resolved.value("orchestration.review"), "agents")
        self.assertEqual(resolved.value("code_graph"), "auto")
        self.assertEqual(resolved.value("handoff"), "500k")
        self.assertIsNone(resolved.value("forge"))
        self.assertEqual(resolved.value("db"), ".claude/shipgate.db")
        self.assertEqual(resolved.value("enforce.command_gate"), True)
        self.assertEqual(resolved.problems, [])
        self.assertEqual(resolved.legacy, [])

    def test_each_layer_in_turn(self):
        self.user_md("## Autonomy\n\n- Mode: ask\n")
        resolved = self.resolve()
        self.assertEqual(resolved.get("autonomy").source, "legacy")
        self.assertEqual(resolved.get("autonomy").path, str(self.user / "shipgate.md"))
        self.assertEqual(resolved.get("autonomy").section, "Autonomy")

        self.user_json({"autonomy": "executive"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(resolved.get("autonomy").source, "user")
        self.assertEqual(resolved.get("autonomy").path,
                         str(self.user / "shipgate.settings.json"))

        self.project_md("## Autonomy\n\n- Mode: ask\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "ask")
        self.assertEqual(resolved.get("autonomy").source, "legacy")
        self.assertEqual(resolved.get("autonomy").path,
                         str(self.root / ".claude" / "shipgate.md"))

        self.project_json({"version": 2, "autonomy": "executive"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(resolved.get("autonomy").source, "project")
        self.assertEqual(resolved.get("autonomy").path,
                         str(self.root / ".claude" / "shipgate.json"))

    def test_every_legacy_key_reads(self):
        self.project_md(
            "## Autonomy\n\n- Mode: executive\n\n"
            "## Orchestration\n\n- review: workflow\n- explore: `workflow`\n\n"
            "## Writing style\n\n- Docs: `ste-80`\n\n"
            "## Code tooling\n\n- Code graph: `off`\n\n"
            "## Code signals\n\n- Window: `18`\n- Fix pattern: `^hotfix`\n"
            "- Exclude: `vendor/`, `gen/`\n- Ranking exclude: ``\n\n"
            "## Session\n\n- Handoff: `1m`\n\n"
            "## Forge & tracker\n\n- Forge: GitLab — CLI: `glab`\n")
        resolved = self.resolve()
        expected = {
            "autonomy": "executive", "orchestration.review": "workflow",
            "orchestration.explore": "workflow", "writing_style": "ste-80",
            "code_graph": "off", "code_signals.window_months": 18,
            "code_signals.fix_pattern": "^hotfix",
            "code_signals.exclude": ["vendor/", "gen/"],
            "code_signals.ranking_exclude": [], "handoff": "1m", "forge": "gitlab",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(resolved.value(key), value)
                self.assertEqual(resolved.get(key).source, "legacy")
        self.assertEqual(resolved.problems, [])
        self.assertEqual(len(resolved.legacy), len(expected))

    def test_forge_prose_without_cli(self):
        self.project_md("## Forge & tracker\n\n- Forge: GitHub, pull requests\n")
        self.assertEqual(self.resolve().value("forge"), "github")

    def test_settings_file_beats_legacy_at_the_same_layer(self):
        self.project_md("## Code tooling\n\n- Code graph: `off`\n")
        self.project_json({"code_graph": "root"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("code_graph"), "root")
        self.assertEqual(resolved.get("code_graph").source, "project")
        # The legacy line still counts as one.
        self.assertEqual([line.key for line in resolved.legacy], ["code_graph"])

    def test_project_legacy_beats_user_file(self):
        self.project_md("## Writing style\n\n- Docs: `plain`\n")
        self.user_json({"writing_style": "ste-80"})
        self.assertEqual(self.resolve().value("writing_style"), "plain")

    def test_null_db_is_none_from_the_project(self):
        self.project_json({"db": None})
        resolved = self.resolve()
        self.assertIsNone(resolved.value("db"))
        self.assertEqual(resolved.get("db").source, "project")
        self.assertEqual(resolved.problems, [])


class TestObjects(SettingsCase):
    """Objects merge per leaf key across layers."""

    def test_per_leaf_merge(self):
        self.project_json({"orchestration": {"review": "workflow"}})
        self.user_json({"orchestration": {"review": "agents", "explore": "workflow"}})
        resolved = self.resolve()
        self.assertEqual(resolved.value("orchestration.review"), "workflow")
        self.assertEqual(resolved.get("orchestration.review").source, "project")
        self.assertEqual(resolved.value("orchestration.explore"), "workflow")
        self.assertEqual(resolved.get("orchestration.explore").source, "user")

    def test_group_value(self):
        self.project_json({"enforce": {"stop_gate": False}})
        resolved = self.resolve()
        self.assertEqual(resolved.value("enforce"),
                         {"stop_gate": False, "auto_capture": True, "command_gate": True})

    def test_artifact_homes_keep_an_extra_kind(self):
        self.project_json({"artifact_homes": {"prd": "*/docs/prd/*.md",
                                              "design": "docs/design/*.md"}})
        homes = self.resolve().value("artifact_homes")
        self.assertEqual(homes["prd"], "*/docs/prd/*.md")
        self.assertEqual(homes["adr"], "docs/adr/*.md")
        self.assertEqual(homes["design"], "docs/design/*.md")

    def test_group_that_is_not_an_object(self):
        self.project_json({"orchestration": "workflow"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("orchestration.review"), "agents")
        self.assertEqual(self.kinds(resolved), [("bad-value", "orchestration")])
        with self.assertRaises(self.cfg.SettingsError):
            resolved.require("orchestration.review")

    def test_unknown_leaf(self):
        self.project_json({"enforce": {"stop_gate": True, "push_gate": False}})
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("unknown-key", "enforce.push_gate")])


class TestScope(SettingsCase):
    """A `project`-scope key in the user settings file is ignored and reported."""

    def test_project_key_in_user_file(self):
        self.user_json({"version": 2, "enforce": {"command_gate": False},
                        "db": "/shared/journal.db", "autonomy": "executive"})
        resolved = self.resolve()
        self.assertIs(resolved.value("enforce.command_gate"), True)
        self.assertEqual(resolved.get("enforce.command_gate").source, "default")
        self.assertEqual(resolved.value("db"), ".claude/shipgate.db")
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(self.kinds(resolved), [("scope", "db"), ("scope", "enforce")])
        # The version of the user file is its format, never a scope problem.
        self.assertEqual(resolved.value("version"), 2)
        self.assertEqual(resolved.get("version").source, "default")

    def test_user_legacy_line_has_no_scope_rule(self):
        self.user_md("## Code signals\n\n- Window: `24`\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("code_signals.window_months"), 24)
        self.assertEqual(resolved.get("code_signals.window_months").source, "legacy")


class TestLegacyOwner(SettingsCase):
    """A legacy line resolves by ADR 0018's per-section owner, then its bullet."""

    def setUp(self):
        super().setUp()
        self.repo = self.root / "svc"
        (self.repo / ".git").mkdir(parents=True)

    def candidates(self):
        return [(self.repo / ".claude" / "shipgate.md", self.cfg.ROLE_PROJECT),
                (self.root / ".claude" / "shipgate.md", self.cfg.ROLE_UMBRELLA)]

    def test_umbrella_line_reaches_a_nested_repo(self):
        self.project_md("## Orchestration\n\n- review: workflow\n")
        self.project_md("# repo\n", directory=self.repo)
        resolved = self.resolve(self.candidates())
        self.assertEqual(resolved.value("orchestration.review"), "workflow")
        self.assertEqual(resolved.get("orchestration.review").path,
                         str(self.root / ".claude" / "shipgate.md"))

    def test_nearer_section_hides_a_farther_bullet(self):
        self.project_md("## Orchestration\n\n- review: workflow\n- explore: workflow\n")
        self.project_md("## Orchestration\n\n- review: agents\n", directory=self.repo)
        resolved = self.resolve(self.candidates())
        self.assertEqual(resolved.value("orchestration.review"), "agents")
        # The repo's section owns Orchestration whole: explore is not inherited.
        self.assertEqual(resolved.value("orchestration.explore"), "agents")
        self.assertEqual(resolved.get("orchestration.explore").source, "default")

    def test_project_section_hides_the_user_line(self):
        self.project_md("## Autonomy\n\n- Extra escalations: publishing\n")
        self.user_md("## Autonomy\n\n- Mode: executive\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "ask")
        self.assertEqual(resolved.get("autonomy").source, "default")

    def test_inherit_none_drops_the_umbrella(self):
        self.project_md("## Orchestration\n\n- review: workflow\n")
        self.project_md("# repo\n\nInherit: none\n", directory=self.repo)
        resolved = self.resolve(self.candidates())
        self.assertEqual(resolved.value("orchestration.review"), "agents")

    def test_placeholder_is_no_line(self):
        self.project_md("## Autonomy\n\n- Mode: <ask | executive>\n")
        self.user_md("## Autonomy\n\n- Mode: executive\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(resolved.problems, [])


class TestKnowledgeBaseLegacy(SettingsCase):
    """T055 (the user's Q1, option B): the homes and the ledger have a legacy read for
    repo paths until the grace date, by the section owner of `## Knowledge base`."""

    def test_the_section_owner_gives_the_homes_and_the_ledger(self):
        self.project_md("## Knowledge base\n\n- PRD home: `docs/specs/`\n"
                        "- Ledger: `notes/ledger.md`\n- Stores: the repo docs.\n")
        self.user_md("## Knowledge base\n\n- ADR home: `mine/adr/`\n")
        resolved = self.resolve()
        self.assertEqual(resolved.problems, [])
        prd = resolved.get("artifact_homes.prd")
        self.assertEqual((prd.value, prd.source, prd.path, prd.section),
                         ("docs/specs/*.md", "legacy", str(self.root / ".claude" / "shipgate.md"),
                          "Knowledge base"))
        self.assertEqual(resolved.value("ledger"), "notes/ledger.md")
        # The project's section owns Knowledge base whole: the user's ADR home is hidden.
        adr = resolved.get("artifact_homes.adr")
        self.assertEqual((adr.value, adr.source), ("docs/adr/*.md", "default"))
        # Every file's lines count, owners aside (`legacy_lines`).
        project, user = str(self.root / ".claude" / "shipgate.md"), str(self.user / "shipgate.md")
        self.assertEqual(sorted((line.path, line.key) for line in resolved.legacy), sorted([
            (project, "artifact_homes.prd"), (project, "ledger"), (user, "artifact_homes.adr")]))

    def test_the_settings_file_wins_over_the_bullet(self):
        self.project_json({"artifact_homes": {"prd": "docs/prd/*.md"}})
        self.project_md("## Knowledge base\n\n- PRD home: `docs/specs/`\n")
        setting = self.resolve().get("artifact_homes.prd")
        self.assertEqual((setting.value, setting.source), ("docs/prd/*.md", "project"))

    def test_beside_the_prd_derives_the_worklog_from_the_prd_home(self):
        self.project_md("## Knowledge base\n\n- PRD home: `<plugin>/docs/prd/`\n"
                        "- Worklog home: beside the PRD as `<name>.worklog.md`.\n")
        resolved = self.resolve()
        worklog = resolved.get("artifact_homes.worklog")
        self.assertEqual((worklog.value, worklog.source), ("*/docs/prd/*.worklog.md", "legacy"))
        self.assertEqual(sorted(line.key for line in resolved.legacy),
                         ["artifact_homes.prd", "artifact_homes.worklog"])

    def test_beside_the_prd_with_no_prd_home_takes_the_default_prd(self):
        self.project_md("## Knowledge base\n\n"
                        "- Worklog home: beside the PRD as `<name>.worklog.md`\n")
        resolved = self.resolve()
        worklog = resolved.get("artifact_homes.worklog")
        self.assertEqual((worklog.value, worklog.source), ("docs/prd/*.worklog.md", "legacy"))
        self.assertEqual(resolved.problems, [])
        self.assertEqual([line.key for line in resolved.legacy], ["artifact_homes.worklog"])

    def test_beside_the_prd_follows_the_resolved_prd_home(self):
        """Review round 3, R1: the worklog sits beside the PRD that applies, whatever layer
        gives it, not beside the PRD bullet of its own file."""
        self.project_json({"artifact_homes": {"prd": "x/*.md"}})
        self.project_md("## Knowledge base\n\n- PRD home: `docs/specs/`\n"
                        "- Worklog home: beside the PRD as `<name>.worklog.md`\n")
        worklog = self.resolve().get("artifact_homes.worklog")
        self.assertEqual((worklog.value, worklog.source), ("x/*.worklog.md", "legacy"))

    def test_legacy_home_reads_the_common_forms(self):
        """Review round 3, R2: a `<name>` inside a segment, and a bare value with words after
        it."""
        for kind, raw, expected in (
                ("prd", "`docs/specs/<name>.md`", "docs/specs/*.md"),
                ("worklog", "`design/<name>.worklog.md`", "design/*.worklog.md"),
                ("prd", "docs/specs/ (repo root)", "docs/specs/*.md"),
                ("prd", "docs/prd/ — artifacts live with the plugin they describe",
                 "docs/prd/*.md"),
                ("adr", "docs/adr/)", "docs/adr/*.md"),
                ("ledger", "docs/ledger.md.", "docs/ledger.md"),
                ("ledger", "notes/ledger.md, shared across plugins", "notes/ledger.md"),
                ("prd", "`docs/sp" + chr(0xE9) + "c/`", "docs/sp" + chr(0xE9) + "c/*.md"),
                ("prd", "the team wiki", None),
                ("ledger", "the ledger page of the wiki", None)):
            with self.subTest(kind=kind, raw=raw):
                self.assertEqual(self.cfg.legacy_home(kind, raw), expected)

    def test_legacy_home_takes_only_path_characters(self):
        """Review round 3, R6: after the `<...>` mapping, only `[\\w.*/-]` passes."""
        for raw in ("`docs/$HOME/`", "`docs/{a,b}/`", "`docs/(x)/`", "`docs/a;b/`",
                    "`docs/a|b/`", "`docs/a&b/`", "`docs/a,b/`", "docs/a,b/",
                    "`docs" + chr(0xFF0F) + "prd/`", "`docs/a<b/`", "`docs/a'b/`"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.cfg.legacy_home("prd", raw))

    def test_a_wiki_home_gives_no_value_and_no_legacy_line(self):
        self.project_md("## Knowledge base\n\n- PRD home: `https://wiki.example.com/specs`\n"
                        "- ADR home: the team wiki, Decisions space\n"
                        "- Ledger: the ledger page of the wiki\n")
        self.user_md("## Knowledge base\n\n- PRD home: `mine/prd/`\n")
        resolved = self.resolve()
        self.assertEqual(resolved.problems, [])
        # The project's section owns Knowledge base, so the user's home stays hidden; it
        # is still a legacy line of the user file, and the wiki homes are none.
        self.assertEqual([(line.path, line.key) for line in resolved.legacy],
                         [(str(self.user / "shipgate.md"), "artifact_homes.prd")])
        for key, default in (("artifact_homes.prd", "docs/prd/*.md"),
                             ("artifact_homes.adr", "docs/adr/*.md"),
                             ("ledger", "docs/ledger.md")):
            setting = resolved.get(key)
            self.assertEqual((setting.value, setting.source), (default, "default"))

    def test_a_hostile_value_stays_none(self):
        for raw in ("`../outside/`", "`docs/../../outside/`", "`/etc/`", "`~/notes/`",
                    "`C:/docs/`", "`docs\\..\\x/`", "`docs/a b/`",
                    "`docs/pr" + chr(27) + "d/`", "`docs/pr" + chr(0) + "d/`",
                    "`docs/pr" + chr(10) + "d/`", "`.//etc/`", "`./~/notes/`"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.cfg.legacy_home("prd", raw))
        for raw in ("`.//etc/notes.md`", "`./../ledger.md`", "`~/ledger.md`"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.cfg.legacy_home("ledger", raw))

    def test_the_parse_is_bounded(self):
        import time

        for raw in ("`" + "a/" * 200000 + "`", "`" + "<" * 200000 + "`",
                    "beside the PRD " * 50000, "`" + "a" * 400000):
            started = time.monotonic()
            self.cfg.legacy_home("worklog", raw)
            self.assertLess(time.monotonic() - started, 1.0)
        text = ("## Knowledge base\n\n- PRD home: `" + "d/" * 100000 + "`\n"
                "- Worklog home: beside the PRD as `<name>.worklog.md`\n")
        self.project_md(text)
        started = time.monotonic()
        self.resolve()
        self.assertLess(time.monotonic() - started, 2.0)


class TestBadValues(SettingsCase):
    """S1: a bad value in a settings file is the default plus a `bad-value` problem, and
    `require` raises; a bad legacy value is ignored and the next layer applies."""

    def test_bad_value_in_project_file(self):
        path = self.project_json({"autonomy": "exec"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "ask")
        self.assertEqual(resolved.get("autonomy").source, "default")
        self.assertEqual(self.kinds(resolved), [("bad-value", "autonomy")])
        problem = resolved.problems[0]
        self.assertEqual(problem.path, str(path))
        self.assertIn('autonomy = "exec"', problem.message)
        self.assertIn("ask, executive", problem.message)
        self.assertIn(str(path), problem.message)
        with self.assertRaises(self.cfg.SettingsError) as raised:
            resolved.require("autonomy")
        self.assertEqual(raised.exception.exit_code, 2)
        self.assertEqual(str(raised.exception), problem.message)
        # Another key still resolves.
        self.assertEqual(resolved.require("code_graph"), "auto")

    def test_bad_project_value_is_the_default_not_the_next_layer(self):
        # The design's rule (worklog, Data flow; PRD FR-006): the default, never a
        # farther layer, so a hook and a command read the same value.
        self.project_json({"orchestration": {"review": "fan"}})
        self.user_json({"orchestration": {"review": "workflow"}})
        resolved = self.resolve()
        self.assertEqual(resolved.value("orchestration.review"), "agents")
        self.assertEqual(resolved.get("orchestration.review").source, "default")
        with self.assertRaises(self.cfg.SettingsError):
            resolved.require("orchestration.review")
        with self.assertRaises(self.cfg.SettingsError):
            resolved.require("orchestration")

    def test_each_type_check(self):
        cases = (
            {"code_signals": {"window_months": 0}},
            {"code_signals": {"window_months": 1201}},
            {"code_signals": {"window_months": True}},
            {"code_signals": {"window_months": "12"}},
            {"code_signals": {"fix_pattern": "(unclosed"}},
            {"code_signals": {"exclude": "vendor/"}},
            {"code_signals": {"exclude": ["vendor/", 3]}},
            {"enforce": {"stop_gate": "no"}},
            {"handoff": "lots"},
            {"handoff": 0},
            {"ledger": ""},
            {"db": 3},
            {"forge": "bitbucket"},
            {"artifact_homes": {"prd": 7}},
        )
        for data in cases:
            with self.subTest(data=data):
                self.project_json(data)
                resolved = self.resolve()
                self.assertEqual([p.kind for p in resolved.problems], ["bad-value"])
        for data in ({"handoff": "off"}, {"handoff": "1.5m"}, {"handoff": 300000},
                     {"code_signals": {"ranking_exclude": []}}):
            with self.subTest(data=data):
                self.project_json(data)
                self.assertEqual(self.resolve().problems, [])

    def test_bad_legacy_value(self):
        self.project_md("## Code tooling\n\n- Code graph: `sometimes`\n")
        self.user_json({"code_graph": "root"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("code_graph"), "root")
        self.assertEqual(self.kinds(resolved), [("bad-legacy", "code_graph")])
        self.assertEqual(resolved.require("code_graph"), "root")
        self.assertIn("sometimes", resolved.problems[0].message)
        self.assertIn("## Code tooling", resolved.problems[0].message)

    def test_bad_legacy_handoff_falls_to_the_default(self):
        self.project_md("## Session\n\n- Handoff: `soon`\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("handoff"), "500k")
        self.assertEqual(self.kinds(resolved), [("bad-legacy", "handoff")])

    def test_bad_legacy_window_is_named(self):
        self.project_md("## Code signals\n\n- Window: `soon`\n- Exclude: `gen/`\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("code_signals.window_months"), 12)
        self.assertEqual(resolved.value("code_signals.exclude"), ["gen/"])
        self.assertEqual(self.kinds(resolved),
                         [("bad-legacy", "code_signals.window_months")])


class TestFileProblems(SettingsCase):

    def test_unknown_key_is_a_warning(self):
        self.project_json({"version": 2, "publish_quiz": True})
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("unknown-key", "publish_quiz")])
        self.assertEqual(resolved.require("autonomy"), "ask")

    def test_newer_version_is_a_warning(self):
        self.project_json({"version": 3, "autonomy": "executive"})
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("version", "version")])
        self.assertEqual(resolved.require("autonomy"), "executive")
        self.assertEqual(resolved.value("version"), 3)

    def test_not_json(self):
        path = self.project_json(None, raw="{not json")
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("not-json", None)])
        self.assertEqual(resolved.value("autonomy"), "ask")
        with self.assertRaises(self.cfg.SettingsError) as raised:
            resolved.require("autonomy")
        self.assertEqual(raised.exception.exit_code, 1)
        self.assertIn(str(path), str(raised.exception))

    def test_not_an_object(self):
        self.user_json(None, raw="[1, 2]")
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("not-json", None)])



class TestReviewRound1(SettingsCase):
    """Review round 1 of #60 PR 1: the per-layer walk, the handoff grammar of the old
    reader, and files that cannot be read."""

    def test_a_bad_user_value_never_beats_a_nearer_layer(self):
        self.project_json({"autonomy": "executive"})
        self.user_json({"autonomy": "bogus"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(resolved.get("autonomy").source, "project")
        self.assertEqual(resolved.require("autonomy"), "executive")
        self.assertEqual(self.kinds(resolved), [("bad-value", "autonomy")])

    def test_a_bad_user_value_never_beats_a_project_legacy_line(self):
        self.project_md("## Autonomy\n\n- Mode: executive\n")
        self.user_json({"autonomy": "bogus"})
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "executive")
        self.assertEqual(resolved.require("autonomy"), "executive")

    def test_a_bad_user_value_that_decides_is_the_default_and_refused(self):
        self.user_json({"autonomy": "bogus"})
        self.user_md("## Autonomy\n\n- Mode: executive\n")
        resolved = self.resolve()
        self.assertEqual(resolved.value("autonomy"), "ask")
        self.assertEqual(resolved.get("autonomy").source, "default")
        with self.assertRaises(self.cfg.SettingsError) as raised:
            resolved.require("autonomy")
        self.assertEqual(raised.exception.exit_code, 2)

    def test_a_legacy_handoff_keeps_the_old_grammar(self):
        # The old reader: `^(\d+(?:\.\d+)?)\s*([km]?)$` over the lower-cased value.
        for raw, value in (("300 k", "300 k"), ("`1.5 m`", "1.5 m"), ("1.5 M", "1.5 m"),
                           ("OFF", "off"), ("`300000`", "300000")):
            with self.subTest(raw=raw):
                self.project_md(f"## Session\n\n- Handoff: {raw}\n")
                resolved = self.resolve()
                self.assertEqual(resolved.value("handoff"), value)
                self.assertEqual(resolved.problems, [])

    def test_a_pattern_end_is_the_end_of_the_value(self):
        self.project_json({"handoff": "off\n"})
        self.assertEqual(self.kinds(self.resolve()), [("bad-value", "handoff")])

    def test_a_file_that_is_not_utf8_is_not_json(self):
        path = self.user_json(None, raw="{}")
        path.write_bytes(b'{"autonomy": "\xff"}')
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("not-json", None)])
        self.assertIn(str(path), resolved.problems[0].message)

    def test_a_broken_user_file_refuses_only_the_keys_it_could_set(self):
        self.user_json(None, raw="{oops")
        self.project_json({"orchestration": {"review": "workflow"}})
        resolved = self.resolve()
        # A project key: the user file can never set it.
        self.assertIsNone(resolved.require("forge"))
        # Set nearer: the broken file is never reached.
        self.assertEqual(resolved.require("orchestration.review"), "workflow")
        # Reached: the value is unknown, so a strict reader stops (exit 1).
        with self.assertRaises(self.cfg.SettingsError) as raised:
            resolved.require("autonomy")
        self.assertEqual(raised.exception.exit_code, 1)
        # The hook path skips the broken file.
        self.assertEqual(resolved.value("autonomy"), "ask")

    def test_a_broken_user_file_lets_a_user_legacy_line_apply(self):
        self.user_json(None, raw="{oops")
        self.user_md("## Writing style\n\n- Docs: `ste-80`\n")
        self.assertEqual(self.resolve().value("writing_style"), "ste-80")

    def test_a_bad_extra_artifact_kind_is_refused(self):
        self.project_json({"artifact_homes": {"design": 5}})
        resolved = self.resolve()
        self.assertNotIn("design", resolved.value("artifact_homes"))
        with self.assertRaises(self.cfg.SettingsError):
            resolved.require("artifact_homes")

    def test_a_bad_value_wins_over_a_broken_file_in_a_group(self):
        self.project_json(None, raw="{oops")
        self.user_json({"code_graph": "sometimes"})
        resolved = self.resolve()
        with self.assertRaises(self.cfg.SettingsError) as raised:
            resolved.require("code_graph")
        self.assertEqual(raised.exception.exit_code, 2)

    def test_a_kind_name_from_the_file_stays_on_one_line(self):
        self.project_json({"artifact_homes": {"x\njournal.py: forged": 5}})
        problem = self.resolve().problems[0]
        self.assertEqual(problem.kind, "bad-value")
        self.assertNotIn("\n", problem.message)
        self.assertIn('artifact_homes.x\\njournal.py: forged', problem.message)

    def test_a_deeply_nested_file_is_not_json(self):
        self.user_json(None, raw="[" * 200000)
        resolved = self.resolve()
        self.assertEqual(self.kinds(resolved), [("not-json", None)])
        self.assertEqual(resolved.value("autonomy"), "ask")

    def test_the_settings_path_is_the_hooks_sidecar_path(self):
        spec = importlib.util.spec_from_file_location(
            "shipgate_hooks_common_settings", PLUGIN / "hooks" / "_common.py")
        hooks = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(hooks)
        self.assertEqual(self.cfg.SETTINGS_RELPATH, hooks.SIDECAR_RELPATH)

    def test_the_schema_is_read_once(self):
        self.cfg.load_schema()
        with mock.patch("builtins.open", side_effect=AssertionError("re-read")):
            self.cfg.load_schema()



# A valid settings-file value per leaf key that differs from the default (SC-002).
SAMPLE_VALUES = {
    "version": 2, "db": "var/journal.db", "ledger": "notes/ledger.md",
    "artifact_homes.prd": "specs/*.md", "artifact_homes.adr": "decisions/*.md",
    "artifact_homes.worklog": "specs/*.log.md",
    "enforce.stop_gate": False, "enforce.auto_capture": False,
    "enforce.command_gate": False, "autonomy": "executive",
    "orchestration.review": "workflow", "orchestration.explore": "workflow",
    "writing_style": "ste-80", "code_graph": "root",
    "code_signals.window_months": 24, "code_signals.fix_pattern": "^hotfix",
    "code_signals.exclude": ["vendor/"], "code_signals.ranking_exclude": [],
    "handoff": "1m", "forge": "gitlab",
}

# The legacy line per legacy key, and the value it gives (SC-002).
SAMPLE_LEGACY = {
    "autonomy": ("Autonomy", "- Mode: executive", "executive"),
    "orchestration.review": ("Orchestration", "- review: workflow", "workflow"),
    "orchestration.explore": ("Orchestration", "- explore: workflow", "workflow"),
    "writing_style": ("Writing style", "- Docs: `ste-80`", "ste-80"),
    "code_graph": ("Code tooling", "- Code graph: `root`", "root"),
    "code_signals.window_months": ("Code signals", "- Window: `24`", 24),
    "code_signals.fix_pattern": ("Code signals", "- Fix pattern: `^hotfix`", "^hotfix"),
    "code_signals.exclude": ("Code signals", "- Exclude: `vendor/`", ["vendor/"]),
    "code_signals.ranking_exclude": ("Code signals", "- Ranking exclude: ``", []),
    "handoff": ("Session", "- Handoff: `1m`", "1m"),
    "forge": ("Forge & tracker", "- Forge: GitLab", "gitlab"),
    "ledger": ("Knowledge base", "- Ledger: `notes/ledger.md`", "notes/ledger.md"),
    "artifact_homes.prd": ("Knowledge base", "- PRD home: `docs/specs/`", "docs/specs/*.md"),
    "artifact_homes.adr": ("Knowledge base", "- ADR home: `docs/decisions/`",
                           "docs/decisions/*.md"),
    "artifact_homes.worklog": ("Knowledge base", "- Worklog home: `docs/specs/`",
                               "docs/specs/*.worklog.md"),
}


def nested(key, value):
    """`{"group": {"leaf": value}}` for `group.leaf`, else `{key: value}`."""
    if "." in key:
        group, leaf = key.split(".", 1)
        return {group: {leaf: value}}
    return {key: value}


class TestEveryKeyFromEveryLayer(SettingsCase):
    """SC-002: each schema key resolves from each layer that may set it and from the
    default, and names its source."""

    def setUp(self):
        super().setUp()
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.scope = {k: n["x-scope"] for k, n in self.schema["properties"].items()}

    def clear(self):
        for path in (self.root / ".claude" / "shipgate.json",
                     self.root / ".claude" / "shipgate.md",
                     self.user / "shipgate.settings.json", self.user / "shipgate.md"):
            if path.exists():
                path.unlink()

    def test_the_samples_cover_every_key(self):
        self.assertEqual(sorted(SAMPLE_VALUES), sorted(TABLE_KEYS))
        self.assertEqual(sorted(SAMPLE_LEGACY), sorted(TABLE_LEGACY))

    def test_each_key_from_each_layer(self):
        defaults = flat_defaults(self.schema)
        for key in TABLE_KEYS:
            user_may = self.scope[key.split(".", 1)[0]] == "any" and key != "version"
            with self.subTest(key=key, layer="default"):
                self.clear()
                setting = self.resolve().get(key)
                self.assertEqual((setting.value, setting.source),
                                 (defaults[key], "default"))
            with self.subTest(key=key, layer="project"):
                self.clear()
                self.project_json(nested(key, SAMPLE_VALUES[key]))
                resolved = self.resolve()
                self.assertEqual(resolved.problems, [])
                self.assertEqual((resolved.value(key), resolved.get(key).source),
                                 (SAMPLE_VALUES[key], "project"))
            with self.subTest(key=key, layer="user"):
                self.clear()
                self.user_json(nested(key, SAMPLE_VALUES[key]))
                setting = self.resolve().get(key)
                expected = ((SAMPLE_VALUES[key], "user") if user_may
                            else (defaults[key], "default"))
                self.assertEqual((setting.value, setting.source), expected)
            if key not in SAMPLE_LEGACY:
                continue
            section, line, value = SAMPLE_LEGACY[key]
            for layer, write in (("project legacy", self.project_md),
                                 ("user legacy", self.user_md)):
                with self.subTest(key=key, layer=layer):
                    self.clear()
                    write(f"## {section}\n\n{line}\n")
                    resolved = self.resolve()
                    self.assertEqual(resolved.problems, [])
                    setting = resolved.get(key)
                    self.assertEqual((setting.value, setting.source, setting.section),
                                     (value, "legacy", section))


class TestLegacyGrace(SettingsCase):
    """`legacy_until` comes from the schema; `ended` follows the clock."""

    def test_until_comes_from_the_schema(self):
        until = json.loads(SCHEMA.read_text(encoding="utf-8"))["x-legacy-until"]
        last = date.fromisoformat(until)
        resolved = self.resolve(today=last)
        self.assertEqual(resolved.legacy_until, until)
        self.assertFalse(resolved.legacy_ended)
        self.assertTrue(self.resolve(today=date.fromordinal(last.toordinal() + 1))
                        .legacy_ended)

    def test_ended_by_the_clock(self):
        schema = self.cfg.load_schema()
        schema = dict(schema, **{"x-legacy-until": "2027-01-24"})
        files = self.cfg.read_layers([], None)
        before = self.cfg.resolve_settings(None, files, None, schema=schema,
                                           today=date(2027, 1, 24))
        after = self.cfg.resolve_settings(None, files, None, schema=schema,
                                          today=date(2027, 1, 25))
        self.assertEqual(before.legacy_until, "2027-01-24")
        self.assertFalse(before.legacy_ended)
        self.assertTrue(after.legacy_ended)




class StatusSettingsCase(SettingsCase):
    """The status brief's settings lines (T040, T041, T054): `status_settings` builds
    the `settings` and `legacy` keys of `status --json` from the project root, and
    `settings_lines` renders them."""

    UNTIL = "2027-01-23"

    def setUp(self):
        super().setUp()
        from test_journal import load_journal_module

        self.jm = load_journal_module()
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def doc(self, until=None, today=None):
        schema = dict(self.schema, **{"x-legacy-until": until})
        return self.jm.status_settings(self.root, today=today, schema=schema)

    def lines(self, until=None, today=None):
        return self.jm.settings_lines(self.doc(until, today))


class TestStatusSettingsLine(StatusSettingsCase):
    def test_the_line_names_each_key_with_its_source(self):
        self.project_json({"version": 2, "orchestration": {"review": "workflow"}})
        self.user_json({"autonomy": "executive"})
        self.project_md("## Writing style\n\n- Docs: `ste-80`\n")
        self.assertEqual(self.lines(), [
            "settings: autonomy=executive (user) · orchestration.review=workflow (project) "
            "· orchestration.explore=agents (default) · writing_style=ste-80 (legacy) "
            "· code_graph=auto (default)",
        ])

    def test_no_settings_file_gives_the_defaults(self):
        self.assertEqual(self.lines(), [
            "settings: autonomy=ask (default) · orchestration.review=agents (default) "
            "· orchestration.explore=agents (default) · writing_style=plain (default) "
            "· code_graph=auto (default)",
        ])

    def test_the_json_keys(self):
        self.project_json({"code_graph": "off"})
        self.project_md("## Autonomy\n\n- Mode: executive\n")
        doc = self.doc()
        self.assertEqual(set(doc), {"settings", "legacy"})
        self.assertEqual(list(doc["settings"]), [
            "autonomy", "orchestration.review", "orchestration.explore", "writing_style",
            "code_graph"])
        self.assertEqual(doc["settings"]["code_graph"],
                         {"value": "off", "source": "project",
                          "path": ".claude/shipgate.json"})
        self.assertEqual(doc["settings"]["autonomy"],
                         {"value": "executive", "source": "legacy",
                          "path": ".claude/shipgate.md", "section": "Autonomy"})
        self.assertEqual(doc["legacy"], {"count": 1, "until": None, "ended": False})

    def test_a_bad_value_shows_the_default_and_one_line_names_it(self):
        self.project_json({"autonomy": "exec"})
        lines = self.lines()
        self.assertIn("autonomy=ask (default)", lines[0])
        self.assertEqual(lines[1:], [
            'settings: bad value, so the default applies: autonomy = "exec" '
            "(.claude/shipgate.json)",
        ])
        entry = self.doc()["settings"]["autonomy"]
        self.assertEqual(entry["problem"], {"kind": "bad-value", "key": "autonomy",
                                            "path": ".claude/shipgate.json",
                                            "value": "exec"})


class TestStatusEveryBadKey(StatusSettingsCase):
    """T054, FR-006: every key with a value outside its set in a settings file is named
    once, the keys the hooks read too. The value used is the default."""

    def test_the_hook_keys_are_named_once_each(self):
        self.project_json({"db": 5, "autonomy": "exec",
                           "enforce": {"stop_gate": "no", "command_gate": 0},
                           "artifact_homes": {"prd": 3}})
        lines = self.lines()
        bad = [line for line in lines if line.startswith("settings: bad value")]
        for key, shown in (("autonomy", '"exec"'), ("db", "5"),
                           ("enforce.stop_gate", '"no"'), ("enforce.command_gate", "0"),
                           ("artifact_homes.prd", "3")):
            with self.subTest(key=key):
                named = [line for line in lines if f" {key} = " in line]
                self.assertEqual(len(named), 1, lines)
                self.assertIn(f"{key} = {shown} (.claude/shipgate.json)", named[0])
        self.assertEqual(len(bad), 5)
        settings = self.doc()["settings"]
        self.assertEqual(settings["db"]["value"], ".claude/shipgate.db")
        self.assertIs(settings["enforce.stop_gate"]["value"], True)
        self.assertIs(settings["enforce.command_gate"]["value"], True)
        self.assertEqual(settings["artifact_homes.prd"]["value"], "docs/prd/*.md")

    def test_a_bad_group_and_a_bad_user_value(self):
        self.project_json({"enforce": "off", "artifact_homes": "docs"})
        self.user_json({"writing_style": "fancy"})
        lines = self.lines()
        self.assertIn('settings: bad value, so the default applies: enforce = "off" '
                      "(.claude/shipgate.json)", lines)
        self.assertIn('settings: bad value, so the default applies: artifact_homes = '
                      '"docs" (.claude/shipgate.json)', lines)
        user = [line for line in lines if "writing_style = " in line]
        self.assertEqual(len(user), 1)
        self.assertIn('"fancy"', user[0])
        self.assertIn("shipgate.settings.json", user[0])

    def test_the_count_of_lines_is_bounded(self):
        kinds = {f"kind{n:02d}": n for n in range(30)}
        self.project_json({"artifact_homes": kinds})
        lines = self.lines()
        bad = [line for line in lines if line.startswith("settings: bad value")]
        self.assertEqual(len(bad), self.jm.MAX_BAD_SETTING_LINES)
        more = 30 - self.jm.MAX_BAD_SETTING_LINES
        self.assertEqual(lines[-1], f"settings: {more} more bad values — "
                                    "journal.py config names them")

    def test_hostile_keys_and_values_stay_on_one_clipped_line(self):
        escape = chr(27)
        breakers = "\n\r" + chr(0x0b) + chr(0x0c) + chr(0x85) + chr(0x2028) + chr(0x2029)
        self.project_json({"artifact_homes": {
            f"evil{breakers}FORGED line{escape}[31m": 1,
            "x" * 5000: 2,
        }, "autonomy": "y" * 5000 + "\nFORGED"})
        lines = self.lines()
        text = "\n".join(lines)
        self.assertFalse(any(line.startswith("FORGED") for line in text.splitlines()))
        # The settings line holds only values from the schema's sets and source words,
        # so its length is bounded by construction; every other line is clipped.
        self.assertIn("autonomy=ask (default)", lines[0])
        for line in lines:
            with self.subTest(line=line[:40]):
                if line is not lines[0]:
                    self.assertLessEqual(len(line), self.jm.BRIEF_LINE_CHARS)
                self.assertTrue(line.isprintable(), repr(line))
                self.assertNotIn(escape, line)
        self.assertEqual(len([line for line in lines if "bad value" in line]), 3)

    def test_an_unreadable_user_settings_file_is_one_line(self):
        self.user_json(None, raw="{not json")
        self.user_md("## Autonomy\n\n- Mode: executive\n")
        lines = self.lines()
        self.assertIn("autonomy=executive (legacy)", lines[0])
        named = [line for line in lines if "shipgate.settings.json" in line]
        self.assertEqual(len(named), 1, lines)
        self.assertIn("cannot be read, so its settings are skipped", named[0])
        self.assertNotIn("not json", "\n".join(lines))


class TestStatusLegacyGrace(StatusSettingsCase):
    """FR-011, SC-008: the legacy line names the count and the date; after the date it
    says the grace has ended; no value changes on a calendar day."""

    def setUp(self):
        super().setUp()
        self.project_md("## Autonomy\n\n- Mode: executive\n\n"
                        "## Orchestration\n\n- review: workflow\n")
        self.user_md("## Writing style\n\n- Docs: ste-80\n")

    def test_no_legacy_line_while_the_date_is_null(self):
        self.assertEqual(len(self.lines(until=None)), 1)
        self.assertEqual(self.doc(until=None)["legacy"],
                         {"count": 3, "until": None, "ended": False})

    def test_the_line_before_and_on_the_date(self):
        for today in (date(2026, 12, 1), date(2027, 1, 23)):
            with self.subTest(today=today):
                self.assertEqual(self.lines(self.UNTIL, today)[-1], (
                    "settings: 3 legacy lines in shipgate.md are still read until "
                    "2027-01-23 — /shipgate:setup moves them"))

    def test_the_line_after_the_date(self):
        self.assertEqual(self.lines(self.UNTIL, date(2027, 1, 24))[-1], (
            "settings: 3 legacy lines in shipgate.md: the grace ended 2027-01-23, and "
            "the next shipgate release stops reading them — /shipgate:setup moves them"))
        self.assertEqual(self.doc(self.UNTIL, date(2027, 1, 24))["legacy"],
                         {"count": 3, "until": "2027-01-23", "ended": True})

    def test_one_line_is_singular(self):
        self.project_md("## Autonomy\n\n- Mode: executive\n")
        (self.user / "shipgate.md").unlink()
        self.assertEqual(self.lines(self.UNTIL, date(2027, 1, 1))[-1], (
            "settings: 1 legacy line in shipgate.md is still read until 2027-01-23 "
            "— /shipgate:setup moves it"))

    def test_the_values_are_the_same_on_both_sides_of_the_date(self):
        before = self.doc(self.UNTIL, date(2027, 1, 23))["settings"]
        after = self.doc(self.UNTIL, date(2027, 1, 24))["settings"]
        self.assertEqual(before, after)
        self.assertEqual(after["autonomy"]["value"], "executive")
        self.assertEqual(after["orchestration.review"]["value"], "workflow")
        self.assertEqual(after["writing_style"]["value"], "ste-80")

    def test_the_lines_resolve_from_the_project_root(self):
        nested = self.root / "svc"
        (nested / ".git").mkdir(parents=True)
        self.project_md("## Code tooling\n\n- Code graph: `off`\n", directory=nested)
        self.assertEqual(self.doc()["settings"]["code_graph"]["value"], "auto")


class TestConfigCommand(unittest.TestCase):
    """T005: `journal.py config [KEY ...] [--json] [--start DIR]` (FR-007, SC-002,
    SC-004). It needs no journal database."""

    def setUp(self):
        from test_journal import run_journal

        self.run_journal = run_journal
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "project"
        (self.root / ".git").mkdir(parents=True)
        self.user = self.base / "user"
        self.user.mkdir()

    def write(self, rel, text, base=None):
        path = (base or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def sidecar(self, data):
        return self.write(".claude/shipgate.json", json.dumps(data))

    def config(self, *args, rc=0, cwd=None):
        from test_journal import SESSION_ENV

        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env["CLAUDE_CONFIG_DIR"] = str(self.user)
        proc = self.run_journal(["config", *args], cwd=cwd or self.root, env=env)
        self.assertEqual(proc.returncode, rc, msg=proc.stdout + proc.stderr)
        return proc

    def test_no_journal_and_no_settings_file_prints_the_defaults(self):
        proc = self.config()
        lines = proc.stdout.splitlines()
        self.assertIn("autonomy = ask  (default)", lines)
        self.assertIn("orchestration.review = agents  (default)", lines)
        self.assertIn("code_signals.exclude = []  (default)", lines)
        self.assertIn("forge = null  (default)", lines)
        self.assertEqual(len(lines), len(TABLE_KEYS))
        self.assertEqual(proc.stderr, "")
        self.assertFalse((self.root / ".claude" / "shipgate.db").exists())

    def test_text_form_names_each_source(self):
        self.sidecar({"version": 1, "db": ".claude/shipgate.db",
                      "orchestration": {"review": "workflow"}})
        self.write(".claude/shipgate.md",
                   "## Orchestration\n\n- explore: `workflow`\n")
        self.write("shipgate.settings.json", json.dumps({"autonomy": "executive"}),
                   base=self.user)
        lines = self.config().stdout.splitlines()
        self.assertIn(
            "orchestration.review = workflow  (project .claude/shipgate.json)", lines)
        self.assertIn("orchestration.explore = workflow  "
                      "(legacy .claude/shipgate.md ## Orchestration)", lines)
        user_file = str(self.user / "shipgate.settings.json")
        self.assertIn(f"autonomy = executive  (user {user_file})", lines)
        self.assertIn("db = .claude/shipgate.db  (project .claude/shipgate.json)", lines)

    def test_keys_and_a_group(self):
        proc = self.config("orchestration", "autonomy")
        self.assertEqual(proc.stdout.splitlines(), [
            "orchestration.review = agents  (default)",
            "orchestration.explore = agents  (default)",
            "autonomy = ask  (default)",
        ])

    def test_json_form(self):
        self.sidecar({"code_graph": "off"})
        self.write(".claude/shipgate.md", "## Autonomy\n\n- Mode: executive\n")
        doc = json.loads(self.config("--json").stdout)
        self.assertEqual(set(doc), {"settings", "problems", "legacy"})
        self.assertEqual(doc["settings"]["code_graph"], {
            "value": "off", "source": "project",
            "path": str(self.root / ".claude" / "shipgate.json")})
        self.assertEqual(doc["settings"]["autonomy"]["source"], "legacy")
        self.assertEqual(doc["settings"]["autonomy"]["section"], "Autonomy")
        self.assertEqual(doc["settings"]["handoff"],
                         {"value": "500k", "source": "default", "path": None})
        self.assertEqual(doc["problems"], [])
        until = json.loads(SCHEMA.read_text(encoding="utf-8"))["x-legacy-until"]
        self.assertEqual(doc["legacy"], {
            "count": 1, "until": until,
            "ended": date.today() > date.fromisoformat(until)})
        one = json.loads(self.config("code_graph", "--json").stdout)
        self.assertEqual(list(one["settings"]), ["code_graph"])

    def test_unknown_key_exits_2(self):
        proc = self.config("autonomyy", rc=2)
        self.assertIn("autonomyy", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_bad_value_exits_2_and_names_it(self):
        path = self.sidecar({"autonomy": "exec"})
        proc = self.config(rc=2)
        self.assertIn(f'journal.py: {path}: autonomy = "exec" is not one of: '
                      "ask, executive", proc.stderr)
        self.assertIn("autonomy = ask  (default)", proc.stdout.splitlines())
        # A key that is not printed: a warning, exit 0.
        proc = self.config("code_graph", rc=0)
        self.assertIn("autonomy", proc.stderr)

    def test_warning_keeps_exit_0(self):
        self.sidecar({"publish_quiz": True})
        self.write("shipgate.settings.json", json.dumps({"enforce": {"stop_gate": False}}),
                   base=self.user)
        proc = self.config("autonomy", rc=0)
        self.assertIn("publish_quiz", proc.stderr)
        self.assertIn("enforce", proc.stderr)
        self.assertEqual(proc.stdout, "autonomy = ask  (default)\n")

    def test_not_json_exits_1(self):
        self.write("shipgate.settings.json", "{oops", base=self.user)
        proc = self.config(rc=1)
        self.assertIn("shipgate.settings.json", proc.stderr)

    def test_start_inside_a_nested_repo(self):
        self.sidecar({"version": 1})
        self.write(".claude/shipgate.md", "## Orchestration\n\n- review: workflow\n")
        nested = self.root / "svc"
        (nested / ".git").mkdir(parents=True)
        self.write(".claude/shipgate.md", "## Code tooling\n\n- Code graph: `off`\n",
                   base=nested)
        lines = self.config("--start", str(nested), "orchestration.review",
                            "code_graph").stdout.splitlines()
        self.assertEqual(lines, [
            "orchestration.review = workflow  "
            "(legacy .claude/shipgate.md ## Orchestration)",
            "code_graph = off  (legacy svc/.claude/shipgate.md ## Code tooling)",
        ])
        # From the root, the nested repo's line is not read.
        self.assertEqual(self.config("code_graph").stdout,
                         "code_graph = auto  (default)\n")


if __name__ == "__main__":
    unittest.main()
