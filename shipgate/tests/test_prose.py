"""Contract tests for the prose the model reads.

The "Writing for people" rule (ADR 0006) is one blockquote repeated verbatim in every skill
and agent that prescribes a report for a person, so the copies must stay identical and every
listed surface must carry one. The artifact-writing skills read the `writing_style` setting.

The config layering rule (ADR 0018) has two homes, the template's header and the README's
Configuration section; every skill that reads the config cites them with one shared callout.
That callout also says where a setting comes from (ADR 0028): the status brief's `settings:`
line or `journal.py config`, never `shipgate.md` (PRD SC-001).
`model-tiers` holds the built-in worker discipline, and `feature` holds the executive
contract that `clarify`, `design`, `setup` and the glossary cite.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

SHIPGATE = Path(__file__).resolve().parent.parent

SURFACES = [
    "agents/code-reviewer.md",
    "agents/code-explorer.md",
    "agents/code-architect.md",
    "skills/review/SKILL.md",
    "skills/verify/SKILL.md",
    "skills/structured-debug/SKILL.md",
    "skills/clarify/SKILL.md",
    "skills/design/SKILL.md",
    "skills/implement/SKILL.md",
    "skills/feature/SKILL.md",
    "skills/knowledge-base/SKILL.md",
    "skills/model-tiers/SKILL.md",
]

READERS = {
    "skills/clarify/SKILL.md": 1,
    "skills/design/SKILL.md": 2,
    "skills/implement/SKILL.md": 1,
    "skills/knowledge-base/SKILL.md": 2,
    "skills/review/SKILL.md": 1,
    "skills/structured-debug/SKILL.md": 1,
}
READ_STEM = "When the `writing_style` setting is `ste-80`, the Writing for people rule applies to"
READ_SENTENCE = re.compile(
    re.escape(READ_STEM)
    + r"[^\n]*(?:\n[^\n]+)*?When\s+it\s+is\s+`plain`,\s+the\s+default,\s+write\s+(?:it|them)\s+as\s+before\."
)
LEDGER_READERS = ("skills/implement/SKILL.md", "skills/review/SKILL.md", "skills/structured-debug/SKILL.md", "skills/knowledge-base/SKILL.md")

CALLOUT = re.compile(r"^> \*\*Writing for people\.\*\*.*?(?=\n(?!> ))", re.S | re.M)


def callouts(text: str) -> list[str]:
    return CALLOUT.findall(text)


class TestWritingForPeopleCallout(unittest.TestCase):
    def test_every_surface_carries_exactly_one_copy(self):
        for rel in SURFACES:
            with self.subTest(surface=rel):
                found = callouts((SHIPGATE / rel).read_text())
                self.assertEqual(len(found), 1, f"{rel}: {len(found)} copies of the callout")

    def test_all_copies_are_identical(self):
        copies = {rel: callouts((SHIPGATE / rel).read_text()) for rel in SURFACES}
        texts = {rel: c[0] for rel, c in copies.items() if c}
        reference_rel = SURFACES[0]
        reference = texts[reference_rel]
        for rel, text in texts.items():
            with self.subTest(surface=rel):
                self.assertEqual(text, reference, f"{rel} drifted from {reference_rel}")

    def test_the_rule_states_its_guard(self):
        text = callouts((SHIPGATE / SURFACES[0]).read_text())[0]
        self.assertIn("not fewer facts", text)
        for fact in ("file:line", "severity", "confidence", "failure", "exit code", "verdict"):
            self.assertIn(fact, text)

    def test_no_other_file_carries_a_copy(self):
        others = [p for p in SHIPGATE.rglob("*.md") if p.relative_to(SHIPGATE).as_posix() not in SURFACES]
        for p in others:
            if "evals/results" in p.as_posix() or p.parent.name == "prd":
                continue
            with self.subTest(file=p.relative_to(SHIPGATE).as_posix()):
                self.assertEqual(callouts(p.read_text()), [], "the callout belongs to the listed surfaces only")


class TestWritingStyleReaders(unittest.TestCase):
    def test_every_artifact_writing_skill_reads_the_key_and_states_the_default(self):
        for rel, count in READERS.items():
            with self.subTest(skill=rel):
                text = (SHIPGATE / rel).read_text()
                self.assertEqual(text.count(READ_STEM), count, f"{rel}: reading sentences")
                spans = [m.group(0) for m in READ_SENTENCE.finditer(text)]
                self.assertEqual(len(spans), count, f"{rel}: each sentence states the default in the same paragraph")
                if rel in LEDGER_READERS:
                    self.assertTrue(any("ledger" in s for s in spans), f"{rel}: names the ledger lines it writes")

    def test_model_tiers_passes_the_setting_to_workers(self):
        text = flat((SHIPGATE / "skills/model-tiers/SKILL.md").read_text())
        self.assertIn("Item 8 pastes this callout into the brief when the `writing_style` setting is `ste-80`", text)
        self.assertIn("give the `writing_style` setting: `plain` (the default) or `ste-80`", text)
        self.assertIn("`journal.py config writing_style`", text)


class TestWritingStyleSetting(unittest.TestCase):
    def test_the_schema_declares_the_setting_with_its_default(self):
        prop = json.loads((SHIPGATE / "settings.schema.json").read_text())["properties"]["writing_style"]
        self.assertEqual(prop["enum"], ["plain", "ste-80"])
        self.assertEqual(prop["default"], "plain")

    def test_the_template_has_no_writing_style_section(self):
        text = (SHIPGATE / "config-template.md").read_text()
        self.assertNotIn("## Writing style", text)
        self.assertNotIn("- Docs:", text)

    def test_readme_settings_table_lists_the_setting(self):
        text = section((SHIPGATE / "README.md").read_text(), "## Configuration")
        self.assertRegex(text, re.compile(r"^\| `writing_style` \| `plain`, `ste-80` \| `plain` \|", re.M),
                         "README settings table row")


CONFIG_CALLOUT = (
    "> **Config:** Read each setting from the `settings:` line of the status brief. For a key that\n"
    "> line does not show, or with no brief, run\n"
    "> `python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/journal.py\" config <key>`. Exit 2 from it means a\n"
    "> settings file holds a bad value: show its message and stop. With no `python3`, read\n"
    "> `.claude/shipgate.json`, then `$CLAUDE_CONFIG_DIR/shipgate.settings.json` (else\n"
    "> `~/.claude/shipgate.settings.json`); the first file that sets a key wins. Behaviour in words\n"
    "> comes from `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file\n"
    "> `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`). They layer per section by\n"
    "> the rule in `config-template.md`'s header and the README's Configuration section; read them\n"
    "> first if present."
)
CONFIG_READERS = (
    "commands/shipgate.md",
    "skills/clarify/SKILL.md",
    "skills/design/SKILL.md",
    "skills/feature/SKILL.md",
    "skills/implement/SKILL.md",
    "skills/knowledge-base/SKILL.md",
    "skills/model-tiers/SKILL.md",
    "skills/review/SKILL.md",
    "skills/route-and-map/SKILL.md",
    "skills/structured-debug/SKILL.md",
    "skills/workspace/SKILL.md",
)
OLD_CONFIG_CALLOUTS = (
    "**Project config:**",
    "> **Config:** `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file",
)
BLOCKQUOTE = re.compile(r"^> .*?(?=\n(?!>)|\Z)", re.S | re.M)
DISCIPLINE_LEAD = "> **Built-in worker discipline.**"
USUALLY_PERSONAL = "<!-- Usually personal: belongs in the user file. -->"


def blockquotes(text: str, lead: str) -> list[str]:
    return [b for b in BLOCKQUOTE.findall(text) if b.startswith(lead)]


def flat(text: str) -> str:
    """Whitespace-collapsed text with blockquote markers removed, so a wrapped phrase matches."""
    return " ".join(re.sub(r"^>\s?", "", text, flags=re.M).split())


def section(text: str, heading: str) -> str:
    """The body under `heading` up to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n") + len(heading) + 1
    nxt = re.compile(r"^#{1,%d} " % level, re.M).search(text, start)
    return text[start : nxt.start() if nxt else len(text)]


def paragraph(text: str, lead: str) -> str:
    start = text.index(lead)
    end = text.find("\n\n", start)
    return text[start : end if end != -1 else len(text)]


def template_header(text: str) -> str:
    return text.split("\n---\n", 1)[0]


class TestConfigCallout(unittest.TestCase):
    def test_every_config_reader_carries_exactly_one_callout(self):
        for rel in CONFIG_READERS:
            with self.subTest(surface=rel):
                found = blockquotes((SHIPGATE / rel).read_text(), "> **Config:**")
                self.assertEqual(len(found), 1, f"{rel}: {len(found)} config callouts")
                self.assertTrue(found[0].startswith(CONFIG_CALLOUT), f"{rel}: the callout drifted")

    def test_no_file_keeps_the_old_callout_and_no_other_file_carries_the_new_one(self):
        for p in SHIPGATE.rglob("*.md"):
            rel = p.relative_to(SHIPGATE).as_posix()
            if "evals/results" in rel or rel.startswith("docs/prd/"):
                continue
            text = p.read_text()
            with self.subTest(file=rel):
                for old in OLD_CONFIG_CALLOUTS:
                    self.assertFalse(old in text, f"an old config callout: {old}")
                if rel not in CONFIG_READERS:
                    self.assertEqual(blockquotes(text, "> **Config:**"), [], "the callout belongs to the config readers")

    def test_the_rule_has_two_homes_that_state_it(self):
        header = flat(template_header((SHIPGATE / "config-template.md").read_text()))
        readme = flat(section((SHIPGATE / "README.md").read_text(), "## Configuration"))
        for name, text in (("config-template.md header", header), ("README Configuration", readme)):
            with self.subTest(home=name):
                self.assertIn("Inherit: none", text)
                self.assertIn("per section", text)
                self.assertIn("$CLAUDE_CONFIG_DIR/shipgate.md", text)
                self.assertIn("~/.claude/shipgate.md", text)
                self.assertIn("1. the repo's `.claude/shipgate.md` files, from the working directory up to the repo root;", text)

    def test_setup_and_the_readme_say_a_mixed_block_stays(self):
        readme = flat(section((SHIPGATE / "README.md").read_text(), "## Configuration"))
        setup = flat((SHIPGATE / "skills/setup/SKILL.md").read_text())
        for name, text in (("README Configuration", readme), ("setup", setup)):
            with self.subTest(surface=name):
                self.assertTrue("`mixed`" in text, f"{name}: names the mixed report")
                self.assertTrue("every sentence in it is boilerplate it knows" in text, f"{name}: states the rule")
                self.assertFalse("goes with the paragraph" in text, f"{name}: the overruled limit is gone")
        self.assertTrue("Extra escalations" in setup and "mixed `Executive contract` bullet" in setup)

    def test_the_template_marks_the_usually_personal_sections(self):
        text = (SHIPGATE / "config-template.md").read_text()
        for heading in ("## Code tooling", "## Autonomy"):
            with self.subTest(section=heading):
                self.assertIn(USUALLY_PERSONAL, section(text, heading))
        self.assertEqual(text.count(USUALLY_PERSONAL), 2)

    def test_the_callout_tells_a_setting_from_the_config(self):
        text = flat(CONFIG_CALLOUT)
        for phrase in ("`settings:` line of the status brief", "config <key>`", "Exit 2",
                       "show its message and stop", "With no `python3`",
                       "$CLAUDE_CONFIG_DIR/shipgate.settings.json", "the first file that sets a key wins",
                       "Behaviour in words comes from `.claude/shipgate.md`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class TestBuiltInWorkerDiscipline(unittest.TestCase):
    def test_model_tiers_holds_the_block_with_its_eight_rules(self):
        found = blockquotes((SHIPGATE / "skills/model-tiers/SKILL.md").read_text(), DISCIPLINE_LEAD)
        self.assertEqual(len(found), 1, "one discipline block")
        numbers = re.findall(r"^> (\d+)\. ", found[0], re.M)
        self.assertEqual(numbers, [str(n) for n in range(1, 9)])
        text = flat(found[0])
        for phrase in ("git add", "git stash", "--no-verify", "--fix", "spend or time limit", "Decisions go to the worklog", "evidence"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_brief_pastes_it_before_the_config_guardrails(self):
        text = flat((SHIPGATE / "skills/model-tiers/SKILL.md").read_text())
        self.assertIn("the built-in worker discipline above, then the config's Worker guardrails section, word for word", text)

    def test_no_other_file_carries_the_block(self):
        for p in SHIPGATE.rglob("*.md"):
            rel = p.relative_to(SHIPGATE).as_posix()
            if rel == "skills/model-tiers/SKILL.md" or "evals/results" in rel or rel.startswith("docs/prd/"):
                continue
            with self.subTest(file=rel):
                self.assertEqual(blockquotes(p.read_text(), DISCIPLINE_LEAD), [])


class TestExecutiveContract(unittest.TestCase):
    CITE = "`feature`'s executive contract"

    def test_feature_owns_the_contract(self):
        body = flat(section((SHIPGATE / "skills/feature/SKILL.md").read_text(), "## The executive contract"))
        for phrase in ("one-way door", "scope", "Security-sensitive", "50/50", "Extra escalations",
                       "Assumptions (executive)", "gate-decision", "raised_by: orchestrator"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_clarify_and_design_cite_feature_instead_of_listing_the_cases(self):
        parts = {
            "clarify": section((SHIPGATE / "skills/clarify/SKILL.md").read_text(), "### Executive mode (the `autonomy` setting is `executive`)"),
            "design": paragraph((SHIPGATE / "skills/design/SKILL.md").read_text(), "**Executive mode**"),
        }
        for name, body in parts.items():
            with self.subTest(skill=name):
                text = flat(body)
                self.assertIn(self.CITE, text)
                self.assertNotIn("one-way door", text)
                self.assertNotIn("50/50", text)

    def test_setup_and_the_glossary_cite_feature(self):
        setup = flat((SHIPGATE / "skills/setup/SKILL.md").read_text())
        self.assertTrue(self.CITE in setup, "setup cites feature's executive contract")
        self.assertFalse("one-way door" in setup, "setup does not restate the escalation list")
        row = next(l for l in (SHIPGATE / "docs/glossary.md").read_text().splitlines() if l.startswith("| **escalation contract**"))
        self.assertIn("`feature`", row)
        self.assertIn("Extra escalations", row)
        self.assertNotIn("one-way door", row)

    def test_the_glossary_defines_both_terms_and_points_at_feature(self):
        rows = {l.split("|")[1].strip(): l for l in (SHIPGATE / "docs/glossary.md").read_text().splitlines()
                if l.startswith("| **")}
        for term in ("**executive contract**", "**escalation contract**"):
            with self.subTest(term=term):
                self.assertIn(term, rows)
                self.assertIn("`feature`", rows[term])
                self.assertIn("**The executive contract**", rows[term])

    def test_template_autonomy_is_extra_escalations_only(self):
        body = section((SHIPGATE / "config-template.md").read_text(), "## Autonomy")
        bullets = re.findall(r"^- ([^:]+):", body, re.M)
        self.assertEqual(bullets, ["Extra escalations"])
        self.assertIn("`autonomy` setting", body)
        self.assertNotIn("Executive contract", body)
        self.assertIn("`feature`", body)


class TestHandoffText(unittest.TestCase):
    """#23 / ADR 0021: the skills print the handoff brief and recommend a fresh session
    (FR-011 to FR-013)."""

    COMMAND = 'journal.py" handoff --stream'

    def test_design_prints_the_brief_once_the_design_lands(self):
        body = flat(section((SHIPGATE / "skills/design/SKILL.md").read_text(),
                            "## Step 5 — Hand off to a fresh session"))
        self.assertIn(self.COMMAND, body)
        self.assertIn("`design-committed`", body)
        self.assertIn("`/clear`, then `/shipgate`", body)

    def test_review_prints_it_before_a_fix_round(self):
        body = flat(paragraph((SHIPGATE / "skills/review/SKILL.md").read_text(),
                              "**Before a fix round, offer a fresh session.**"))
        self.assertIn(self.COMMAND, body)
        self.assertIn("`not-ready`", body)
        self.assertIn("`/clear`, then `/shipgate`", body)

    def test_feature_routes_a_fresh_session_from_the_brief(self):
        body = flat(paragraph((SHIPGATE / "skills/feature/SKILL.md").read_text(),
                              "**A fresh session past design starts from the handoff "
                              "brief.**"))
        self.assertIn(self.COMMAND, body)

    def test_45_feature_records_the_lead_that_a_brief_names(self):
        """#45: a teammate records its lead in the journal, so `handoff` keeps the target
        after a `/clear`."""
        body = flat(section((SHIPGATE / "skills/feature/SKILL.md").read_text(),
                            "## Always-on disciplines"))
        for phrase in ("a lead's brief started", "`flow-started`'s `report_to`",
                       "the command the brief gives to reach it",
                       "a `deviation` with `report_to`", "`report to`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)


# PRD SC-001: no skill, agent or command reads a moved setting from the config. Each pattern
# is a form the text used before ADR 0028 moved the value into the settings files.
MOVED_SETTING_READS = (
    ("Autonomy `Mode` bullet", re.compile(r"\bMode:\s*`?(?:ask|executive)\b")),
    ("the Autonomy section as the mode", re.compile(r"config(?:'s)? \**Autonomy\**(?: section)?\s*(?::|says|declares)")),
    ("an Orchestration line", re.compile(r"\b(?:review|explore):\s*`?workflow\b")),
    ("the Orchestration section", re.compile(r"\*\*Orchestration\*\* section")),
    ("a Writing style `Docs` bullet", re.compile(r"\bDocs:\s*`?(?:plain|ste-80)\b")),
    ("the Writing style section", re.compile(r"\*\*Writing style\*\* section")),
    ("a `Code graph` bullet", re.compile(r"\bCode graph:")),
    ("the Code signals section", re.compile(r"## Code signals|\*\*Code signals\*\* section|\bWindow:\s")),
    ("the Journal section", re.compile(r"## Journal\b|declares a \*\*Journal\*\*|\bJournal section\b|\bno Journal\b")),
    ("a `Handoff` bullet", re.compile(r"\bHandoff:")),
    ("an artifact home bullet", re.compile(r"\b(?:PRD|ADR|Worklog) home:|configured (?:PRD|ADR|worklog) home")),
    ("a `Ledger` bullet", re.compile(r"\bLedger:|config-declared|the path the config declares|the one the config declares")),
    ("a `Forge` bullet", re.compile(r"\bForge:\s|config declares a forge")),
    # `sidecar.version`: the key of `doctor --json` that still bears the old name.
    ("the sidecar", re.compile(r"\bsidecar\b(?!\.)")),
)
MOVED_SETTING_SKIP: tuple = ()

JOURNALED_TEST = ("the status brief is present, or `.claude/shipgate.json` exists and "
                  "`journal.py config db` prints a `db` that is not null")
JOURNALED_READERS = {
    "commands/shipgate.md": 1,
    "skills/clarify/SKILL.md": 2,
    "skills/design/SKILL.md": 1,
    "skills/feature/SKILL.md": 1,
    "skills/implement/SKILL.md": 1,
    "skills/knowledge-base/SKILL.md": 1,
    "skills/review/SKILL.md": 2,
    "skills/route-and-map/SKILL.md": 1,
    "skills/structured-debug/SKILL.md": 1,
    "skills/verify/SKILL.md": 1,
    "skills/workspace/SKILL.md": 1,
}


def model_surfaces():
    files = sorted(SHIPGATE.glob("skills/**/*.md")) + sorted(SHIPGATE.glob("agents/*.md")) \
        + sorted(SHIPGATE.glob("commands/*.md"))
    return [p for p in files if not p.relative_to(SHIPGATE).as_posix().startswith(MOVED_SETTING_SKIP)]


def schema_leaves():
    """Each leaf key of the settings schema, dotted, with its property."""
    props = json.loads((SHIPGATE / "settings.schema.json").read_text())["properties"]
    for key, prop in props.items():
        if prop.get("type") == "object" and "properties" in prop:
            for leaf, sub in prop["properties"].items():
                yield f"{key}.{leaf}", sub, prop["x-scope"]
        else:
            yield key, prop, prop["x-scope"]


class TestSettingsAreNotReadFromTheConfig(unittest.TestCase):
    def test_no_model_surface_reads_a_moved_setting_from_the_config(self):
        surfaces = model_surfaces()
        self.assertGreater(len(surfaces), 15)
        for p in surfaces:
            rel = p.relative_to(SHIPGATE).as_posix()
            text = flat(p.read_text())
            for name, pattern in MOVED_SETTING_READS:
                with self.subTest(file=rel, form=name):
                    self.assertIsNone(pattern.search(text), f"{rel}: reads {name}")

    def test_every_journaled_test_reads_the_brief_or_the_db_setting(self):
        for rel, count in JOURNALED_READERS.items():
            with self.subTest(file=rel):
                self.assertEqual(flat((SHIPGATE / rel).read_text()).count(JOURNALED_TEST), count)

    def test_the_template_holds_no_setting(self):
        text = (SHIPGATE / "config-template.md").read_text()
        for heading in ("## Journal", "## Orchestration", "## Writing style", "## Code signals", "## Session"):
            with self.subTest(heading=heading):
                self.assertNotRegex(text, re.compile("^" + re.escape(heading) + "$", re.M))
        for key in ("Database", "Mode", "review", "explore", "Docs", "Code graph", "Window",
                    "Handoff", "Forge", "Ledger", "PRD home", "ADR home", "Worklog home"):
            with self.subTest(bullet=key):
                self.assertNotRegex(text, re.compile(r"^- " + re.escape(key) + ":", re.M))
        header = flat(template_header(text))
        for phrase in ("`.claude/shipgate.json`", "$CLAUDE_CONFIG_DIR/shipgate.settings.json",
                       "`journal.py config`", "behaviour in words"):
            with self.subTest(header=phrase):
                self.assertIn(phrase, header)

    def test_the_template_keeps_the_prose_bullets(self):
        text = (SHIPGATE / "config-template.md").read_text()
        for heading, keys in (("## Knowledge base", ["Stores", "Page conventions", "Store-specific skills", "Promotion targets"]),
                              ("## Code tooling", ["Library docs", "Code navigation"]),
                              ("## Forge & tracker", ["Issue tracker", "MR/PR template", "Issue-link form",
                                                      "Title/body rules", "Acceptance criteria source", "Bug provenance"])):
            with self.subTest(section=heading):
                self.assertEqual(re.findall(r"^- ([^:<]+):", section(text, heading), re.M), keys)

    def test_the_readme_lists_every_setting_with_its_default_and_scope(self):
        body = section((SHIPGATE / "README.md").read_text(), "## Configuration")
        rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `([a-z_.]+)` \|.*$", body, re.M)}
        for key, prop, scope in schema_leaves():
            with self.subTest(key=key):
                self.assertIn(key, rows)
                self.assertTrue(rows[key].rstrip().endswith(f"| {scope} |"), rows[key])

    def test_the_readme_states_the_layers_the_scope_and_the_command(self):
        body = flat(section((SHIPGATE / "README.md").read_text(), "## Configuration"))
        for phrase in ("$CLAUDE_CONFIG_DIR/shipgate.settings.json", "~/.claude/shipgate.settings.json",
                       "journal.py config [KEY ...] [--json]", "legacy line", "/shipgate:setup",
                       "settings file"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)
        self.assertNotIn("sidecar", body)

    def test_the_glossary_defines_the_settings_terms(self):
        rows = {l.split("|")[1].strip(): l for l in (SHIPGATE / "docs/glossary.md").read_text().splitlines()
                if l.startswith("| **")}
        for term in ("**setting**", "**settings file**", "**legacy line**", "**grace date**"):
            with self.subTest(term=term):
                self.assertIn(term, rows)
        for term in ("**sidecar**", "**switch**"):
            with self.subTest(dropped=term):
                self.assertNotIn(term, rows)


if __name__ == "__main__":
    unittest.main()
