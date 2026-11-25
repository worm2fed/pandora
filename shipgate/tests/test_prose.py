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


class TestClarifyConfirmBatch(unittest.TestCase):
    """#24, ADR 0029 (SC-005): the sentences the confirm batch rests on. What `off` does
    has no code path, so these pins are its test."""

    END_TAGS = ("[kept by the user]", "[changed by the user, was: ", "[unconfirmed]")

    @classmethod
    def setUpClass(cls):
        cls.clarify = flat((SHIPGATE / "skills/clarify/SKILL.md").read_text())
        cls.executive = flat(section((SHIPGATE / "skills/clarify/SKILL.md").read_text(),
                                     "### Executive mode (the `autonomy` setting is `executive`)"))

    def test_clarify_reads_the_setting_and_says_what_off_does(self):
        for phrase in ('journal.py" config clarify_confirm', "`risky`", "`off`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.executive)
        off = self.executive[self.executive.index("`off`"):]
        self.assertRegex(off, r"no (confirm )?dialog")
        self.assertIn("escalations still go to the user", off)
        self.assertRegex(off, r"phase summary lists the risky lines first")

    def test_the_batch_is_one_dialog_of_at_most_4(self):
        self.assertRegex(self.executive, r"at most 4")
        # Escalations take dialog slots first; the script caps the rest.
        self.assertIn("--cap <n>", self.executive)
        self.assertIn("overflow", self.executive)
        self.assertIn("AskUserQuestion", self.executive)
        self.assertIn("Keep", self.executive)

    def test_clarify_computes_the_batch_with_the_parser(self):
        self.assertIn('journal.py" assumptions', self.executive)
        self.assertIn("--risky", self.executive)
        # A PRD the script cannot read (a home outside the repo): the same rule by hand.
        self.assertRegex(self.executive, r"cannot read")

    def test_lines_carry_a_class_and_a_source_or_say_none_was_found(self):
        for phrase in ("`domain`", "`data`", "`behaviour`", "`technical`", "no source found"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.clarify)

    def test_the_three_end_tags(self):
        for tag in self.END_TAGS:
            with self.subTest(tag=tag):
                self.assertIn(tag, self.executive)

    def test_a_lead_gets_the_batch_in_one_message(self):
        self.assertIn("report_to", self.executive)

    def test_the_lead_message_and_the_printed_batch_give_an_alternative(self):
        # 0.34.1: the PR-tree run of case 76 printed items with no alternative. Off the
        # dialog, each item still states the answer taken, its source and an alternative.
        para = self.executive[self.executive.index("A stream with a lead"):]
        para = para[:para.index("With `off`")]
        self.assertIn("each item states the answer taken, its source and at least one real "
                      "alternative", para)

    def test_a_confirm_item_is_not_a_marker(self):
        self.assertRegex(self.executive,
                         r"confirm item is not a `\[NEEDS CLARIFICATION\]` marker")

    def test_the_unfamiliar_area_runs_the_blindspot_pass(self):
        self.assertIn("`unfamiliar`", self.clarify)
        # 0.34.1 (review R1-7): a point a linked document answers is a sourced line.
        area = self.clarify[self.clarify.index("**Unfamiliar area.**"):]
        area = area[:area.index("**UI.**")]
        # Round 2 (R2-1): the boundary is named; the exception line above stays as it is.
        self.assertIn("A point that a document the request or the issue links answers is no "
                      "blindspot candidate, even when the area's files also state it: it is a "
                      "sourced line.", area)
        self.assertIn("blindspot", self.clarify)
        self.assertIn("--format=%s", self.clarify)  # subjects only, never the authors

    def test_a_named_reference_is_a_sourced_line_not_a_candidate(self):
        # The user's rule (#24, after review round 2): a UI reference candidate exists only
        # when the request names none; a named reference opens no dialog.
        ui = self.clarify[self.clarify.index("**UI.**"):]
        ui = ui[:ui.index("## Step 2")]
        # The user's scope answer (round 4): the request OR the issue names it.
        self.assertIn("the request or the issue names no reference", ui)
        self.assertIn("When the request or the issue names the reference", ui)
        self.assertIn("no candidate", ui)
        self.assertIn("[source: the request]", ui)
        self.assertIn("[source: issue #<n>]", ui)  # round 4, R4-4

    def test_clarify_reads_section_and_keeps_blindspots_in_the_list(self):
        # Round 4: a wrong or hidden heading must not skip the dialog silently (R3-2),
        # and a sourced blindspot candidate stays in the list (R3-3).
        # R4-2: only a false `section` means a wrong heading; a correct batch can be empty.
        self.assertIn("When `section` is false, the heading is wrong or hidden", self.executive)
        self.assertNotIn("0 items", self.executive)
        evidence = self.clarify[self.clarify.index("**Evidence first.**"):]
        evidence = evidence[:evidence.index("**Unfamiliar area.**")]
        self.assertIn("A blindspot candidate is the exception", evidence)
        self.assertIn("tagged `[blindspot]`", evidence)  # R4-6

    def test_the_section_holds_only_assumption_lines(self):
        # Round 5 (R5-1, R5-4): the strict section, said where the model writes the lines.
        self.assertIn("the section holds only assumption lines", self.executive)
        self.assertIn("[blindspot]` or `[reference]` after the class", self.executive)
        step3 = flat(section((SHIPGATE / "skills/clarify/SKILL.md").read_text(),
                             "## Step 3 — Write the PRD"))
        self.assertIn("In `ask` mode, leave out its \"Assumptions (executive)\" section", step3)

    def test_the_prd_and_the_changelog_name_the_request_or_the_issue(self):
        # R4-3 and R4-5: the UI rule's scope is the request or the issue, everywhere.
        for path in ("docs/prd/clarify-unknowns.md", "CHANGELOG.md",
                     "docs/adr/0029-clarify-confirms-its-risky-assumptions-in-one-batch.md"):
            with self.subTest(path=path):
                text = flat((SHIPGATE / path).read_text())
                self.assertNotIn("the request names no reference", text)
                self.assertIn("the request or the issue names no reference", text)

    def test_evidence_first_replaces_recall_before_asking(self):
        self.assertNotIn("Recall before asking", self.clarify)
        self.assertIn("Evidence first", self.clarify)
        self.assertIn("--comments", self.clarify)

    def test_the_template_shows_the_tagged_line(self):
        # The end tags are pinned in the skill (test_the_three_end_tags); round 5 moved the
        # template's explanation there, so the section holds the placeholder alone.
        body = flat(section((SHIPGATE / "skills/clarify/references/prd-template.md").read_text(),
                            "## Assumptions (executive)"))
        self.assertRegex(body, r"- \[<class>\] \[source: <ref>\] <question> → <answer>")

    def test_the_contract_names_the_batch_and_the_setting(self):
        body = flat(section((SHIPGATE / "skills/feature/SKILL.md").read_text(),
                            "## The executive contract"))
        bullet = body[body.index("Clarify answers go"):body.index("Design choices go")]
        self.assertIn("one dialog", bullet)
        self.assertIn("`clarify_confirm`", bullet)

    def test_route_and_map_keeps_the_own_share_for_clarify(self):
        text = (SHIPGATE / "skills/route-and-map/SKILL.md").read_text()
        self.assertIn("`unfamiliar`", flat(text))
        block = section(text, "### Risk signals")
        self.assertIn("Unfamiliar to you:", block)
        self.assertIn("Own share unknown", block)

    def test_the_glossary_defines_the_two_terms(self):
        rows = {l.split("|")[1].strip(): l for l in (SHIPGATE / "docs/glossary.md").read_text().splitlines()
                if l.startswith("| **")}
        for term in ("**confirm batch**", "**own share**"):
            with self.subTest(term=term):
                self.assertIn(term, rows)
        self.assertIn("ADR 0029", rows["**confirm batch**"])


class TestReviewGoPins(unittest.TestCase):
    """#25 T002: the review text the digest change edits around. Steps 1 to 4 of the
    user's go and the MR/PR body bullets keep their substance through the edit."""

    @classmethod
    def setUpClass(cls):
        text = (SHIPGATE / "skills/review/SKILL.md").read_text()
        cls.go = flat(section(text, "### The user's go (commit and publish)"))
        cls.mr = flat(section(text, "## Opening the MR/PR (on the user's publish go)"))

    def test_step_1_records_the_go_request_first(self):
        self.assertIn("1. **Record the go request** on the stream whose work the user "
                      "approves, then ask:", self.go)
        self.assertIn("--type go-requested", self.go)

    def test_step_2_asks_with_the_gate_as_header_and_first_option(self):
        self.assertIn("2. **Ask with `AskUserQuestion`.** The header is the gate: `Commit` "
                      "or `Publish`. The first option is the gate word: `Commit` or "
                      "`Publish`. For several streams, ask one multi-select question whose "
                      "option labels are the stream names, and record one go request per "
                      "stream first.", self.go)

    def test_step_3_the_recorder_records_the_answer(self):
        self.assertIn("3. **The recorder records the answer.**", self.go)
        self.assertIn("You record nothing.", self.go)

    def test_step_4_any_other_reply_gets_one_confirming_question(self):
        self.assertIn("4. **Any other reply gets one confirming question.**", self.go)
        self.assertIn("Every new question needs a new go request.", self.go)

    def test_the_body_bullets_stay(self):
        self.assertRegex(self.mr, r"- \*\*Summary\*\* ← ")
        self.assertIn("- **Trade-offs / risks** ← the impact map", self.mr)
        self.assertIn("- **Verification** ← the `verify`-gate evidence.", self.mr)


class TestPublishDigestText(unittest.TestCase):
    """#25, ADR 0030 (SC-004): the review writes the What changed section, prints the
    digest with a ready verdict and as a message right before the publish question."""

    COMMAND = 'journal.py" digest --stream'

    @classmethod
    def setUpClass(cls):
        cls.text = (SHIPGATE / "skills/review/SKILL.md").read_text()
        cls.step6 = section(cls.text, "## Step 6 — Verify, then verdict")
        cls.go = flat(section(cls.text, "### The user's go (commit and publish)"))

    def test_a_the_review_writes_the_what_changed_section(self):
        body = flat(paragraph(self.step6, "**Before a ready verdict, write what changed.**"))
        self.assertIn("`## What changed`", body)
        self.assertIn("1 to 5 list items, one line each", body)
        self.assertIn("After a fix round that changes what the change does, rewrite the "
                      "section.", body)
        self.assertIn("`journal.py digest` accepts only this form", body)

    def test_b_the_digest_prints_with_a_ready_verdict(self):
        body = flat(paragraph(self.step6,
                              "**Journaled: show the digest with a ready verdict.**"))
        self.assertIn(self.COMMAND + " <branch>", body)
        self.assertIn("under the verdict", body)
        self.assertIn("`<file>:<line>`", body)
        self.assertIn("Print the output as its own message, not inside a code block, so its "
                      "table renders.", body)

    def test_c_the_digest_is_a_message_right_before_the_publish_question(self):
        """The user's decision after the first dialog (ADR 0030, amendment): a chat
        message reads better than an option preview, so the preview is gone."""
        self.assertIn("run the digest of each stream you ask about just before you ask, and "
                      "print its output, as printed, as a message right before the question.",
                      self.go)
        self.assertIn("When the ready verdict comes right before the question, the digest "
                      "under it is that message.", self.go)
        self.assertIn("the option carries no preview", self.go)
        self.assertNotIn("`preview`", self.go)
        self.assertNotIn("multi-select question has no preview", self.go)

    def test_d_a_teammate_sends_its_stream_and_worktree(self):
        body = flat(paragraph(self.text, "A session that asks the user about another "
                                         "session's stream"))
        self.assertIn("cd <worktree> && python3", body)
        self.assertIn(self.COMMAND + " <stream>", body)
        self.assertIn("its stream name and its worktree path, not the digest text", body)
        self.assertIn("It prints that output as its own message, then asks.", body)

    def test_e_the_summary_starts_from_what_changed(self):
        mr = flat(section(self.text, "## Opening the MR/PR (on the user's publish go)"))
        self.assertIn("- **Summary** ← the worklog's What changed section, then the PRD for "
                      "the why.", mr)


def between(text: str, start: str, end: str) -> str:
    """The flat text from START up to END, both matched on the flat text."""
    body = flat(text)
    body = body[body.index(start):]
    return body[:body.index(end)]


UI_EVIDENCE_SURFACES = (
    "skills/verify/SKILL.md", "skills/implement/SKILL.md", "skills/design/SKILL.md",
    "skills/design/references/worklog-template.md", "skills/model-tiers/SKILL.md",
    "skills/route-and-map/SKILL.md", "skills/clarify/SKILL.md", "skills/setup/SKILL.md",
)


class TestUiEvidencePins(unittest.TestCase):
    """#26 T019: the sentences around the UI task edits, pinned before and after them."""

    @classmethod
    def setUpClass(cls):
        cls.read = {rel: (SHIPGATE / rel).read_text() for rel in UI_EVIDENCE_SURFACES}

    def test_verify_keeps_its_table_and_its_record_section(self):
        text = self.read["skills/verify/SKILL.md"]
        table = section(text, "## Claim → evidence")
        self.assertIn("| Claim | What proves it |\n|-------|----------------|\n", table)
        self.assertIn('| Feature works | An end-to-end run or a concrete manual walkthrough, '
                      'not "the code looks right" |\n', table)
        self.assertRegex(table, r"\n\| No regressions in shared code \| ")
        record = flat(section(text, "## Record the evidence (journaled projects)"))
        self.assertIn("The two land together, so send them as one `append --batch` (JSONL on "
                      "stdin) rather than two calls:", record)
        self.assertIn('Record failures too, with `"outcome":"fail"`.', record)

    def test_implement_keeps_step_6_and_step_7(self):
        text = self.read["skills/implement/SKILL.md"]
        step6 = flat(paragraph(text, "6. **Verify before you check the box.**"))
        self.assertTrue(step6.startswith(
            '6. **Verify before you check the box.** Invoke the `verify` skill. Run the actual '
            'command (test, build, lint) for this task. Read the output. Confirm that it '
            'proves the task\'s "done when" criterion. No "should work."'), step6)
        self.assertIn("7. **Update the worklog — and the ledger.** Tick the task.", flat(text))

    def test_design_keeps_its_build_plan_rule(self):
        rule = between(self.read["skills/design/SKILL.md"], "- **Build Plan** —",
                       "Order the build plan")
        self.assertIn('Each task names the file(s) it touches and what "done" means. Write each '
                      "task line as the worklog template's Build Plan rule says: a bullet, a "
                      "box, then the id `T` and digits, bare or bold (`- [ ] T001 — title`, "
                      "`- [ ] **T001**: title`). The journal skips a line in any other form.",
                      rule)
        self.assertIn("This section is *living*: implementation ticks the boxes and logs "
                      "deviations here.", rule)

    def test_the_worklog_template_keeps_its_build_plan_paragraph(self):
        body = section(self.read["skills/design/references/worklog-template.md"], "# Build Plan")
        text = flat(body)
        self.assertIn("A task line is a `-` or `*` bullet, a box, then the id: `T` and digits, "
                      "bare (`T001`) or bold (`**T001**` or `**T001:**`).", text)
        self.assertIn("A line in any other form is not a task, so the HUD's Plan tab and the "
                      "Stop gate both skip it.", text)
        self.assertIn("- [ ] T001 — <task> — file(s): `...` — done when: <...>\n", body)

    def test_model_tiers_keeps_item_4(self):
        item = between(self.read["skills/model-tiers/SKILL.md"], "4. **Validation commands**",
                       "5. **No commit, no staging**")
        self.assertTrue(item.startswith(
            "4. **Validation commands** — the exact lint/test/build commands that prove the "
            "task done, and the instruction to run them and read the output."), item)
        self.assertIn("When the code graph is absent, say nothing about codegraph.", item)

    def test_route_and_map_keeps_its_map_and_its_record(self):
        text = self.read["skills/route-and-map/SKILL.md"]
        self.assertIn("### Modules/services touched\n- <module> — read | write | schema", text)
        self.assertIn('"touched":["api","web"],"schema":false,"flag":"export-filters"', text)
        self.assertIn("**`signals` is owed on every map, and its `source` is always set.**", text)

    def test_clarify_keeps_the_other_sentences_of_its_ui_paragraph(self):
        ui = between(self.read["skills/clarify/SKILL.md"], "**UI.**", "## Step 2")
        self.assertIn("and the request or the issue names no reference, add one candidate: the "
                      "reference implementation or screenshot the work should follow, with the "
                      "nearest existing screen as the recommended answer.", ui)
        self.assertIn("Without it, the reference tends to arrive after a defect.", ui)
        self.assertIn("When the request or the issue names the reference, write no candidate: "
                      "the reference is an answer with `[source: the request]` or "
                      "`[source: issue #<n>]`, and nothing about it needs asking.", ui)

    def test_setup_keeps_its_interview_list(self):
        text = self.read["skills/setup/SKILL.md"]
        interview = section(text, "## Step 2 — Interview")
        leads = re.findall(r"^- \*\*([^*]+)\*\*", interview, re.M)
        kept = ["Artifact homes", "Journal", "Autonomy", "Worker guardrails", "Orchestration",
                "Writing style", "Anything detection flagged as ambiguous"]
        self.assertEqual([lead for lead in leads if lead in kept], kept)
        self.assertIn("The user settings file never sets a `project`-scope key (`db`, `ledger`, "
                      "`artifact_homes`, `enforce`, `code_signals`, `forge`", flat(text))


class TestUiEvidenceText(unittest.TestCase):
    """#26, ADR 0031 (FR-011, FR-017, SC-009): the skills carry the UI task rule, its reason
    and its commands. The journal computes which task is UI and checks the screenshots; the
    text tells the model to take, register and read them."""

    SCREENS = 'journal.py" screens'

    @classmethod
    def setUpClass(cls):
        cls.read = {rel: (SHIPGATE / rel).read_text() for rel in UI_EVIDENCE_SURFACES}

    def test_verify_has_the_ui_row(self):
        table = section(self.read["skills/verify/SKILL.md"], "## Claim → evidence")
        self.assertIn("\n| UI task done (the project sets `ui.globs`) | A registered screenshot "
                      "for every width in `ui.widths` (`journal.py screens --list`), read by the "
                      "one who took it, or a `screens-waived` deviation with the reason |\n",
                      table)

    def test_verify_records_the_screenshots_of_a_ui_task(self):
        record = flat(section(self.read["skills/verify/SKILL.md"],
                              "## Record the evidence (journaled projects)"))
        lead = "**A UI task also needs its screenshots.**"
        self.assertIn(lead, record)
        ui = record[record.index(lead):]
        for phrase in ("`[UI]`", "--list",
                       "A UI task's command can pass while its screen is wrong.",
                       "each width of `ui.widths`", self.SCREENS,
                       "--stream <branch> --task T010 --file <png>", "evidence root",
                       "compare it with the reference that the PRD names",
                       "`verify-run` and `task-done` batch",
                       "--url <url>` prints one capture command per width",
                       "the `task-done` refusal prints the waiver command",
                       "because the user reads it at the publish gate"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, ui)
        # Read before the batch: the one who took them looks first (FR-011).
        self.assertLess(ui.index("Read each screenshot"), ui.index("`verify-run` and `task-done`"))

    def test_implement_step_6_sends_a_ui_task_to_verify(self):
        step6 = flat(paragraph(self.read["skills/implement/SKILL.md"],
                               "6. **Verify before you check the box.**"))
        self.assertIn("For a task that the handoff marks `[UI]`, the gate also includes its "
                      "screenshots", step6)
        self.assertIn("a UI task's tests can pass while its screen is wrong", step6)
        self.assertIn("`verify` gives the steps", step6)

    def test_design_asks_for_the_paths_of_each_task(self):
        rule = between(self.read["skills/design/SKILL.md"], "- **Build Plan** —",
                       "Order the build plan")
        for phrase in ("When the project sets `ui.globs`", "in backticks after `file(s):`",
                       "`file(s): none`", "The journal marks a UI task from those paths",
                       "`design-committed` refuses a task line with neither form"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, rule)

    def test_the_worklog_template_states_the_same_rule(self):
        text = flat(section(self.read["skills/design/references/worklog-template.md"],
                            "# Build Plan"))
        self.assertIn("With `ui.globs` set, a task line names its files in backticks after "
                      "`file(s):`, or says `file(s): none`, because the journal marks a UI task "
                      "from those paths.", text)

    def test_model_tiers_briefs_a_ui_task(self):
        item = between(self.read["skills/model-tiers/SKILL.md"], "4. **Validation commands**",
                       "5. **No commit, no staging**")
        for phrase in ("For a UI task (the handoff marks it `[UI]`)", "`ui.widths`",
                       "the register command with the stream and the task filled in",
                       "read each screenshot and compare it with the PRD's reference before "
                       "the report", "Its report lists the registered files"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, item)

    def test_route_and_map_records_the_computed_ui_flag(self):
        text = self.read["skills/route-and-map/SKILL.md"]
        self.assertIn("\n- <module> — read | write | schema — what changes\n", text)
        self.assertNotIn("| UI —", text)
        self.assertIn("\n- UI: <n> touched files match `ui.globs`", text)
        self.assertIn('"flag":"export-filters","ui":true,', text)
        body = flat(text)
        self.assertIn("The JSON's top-level `ui` is null when the project sets no `ui.globs`.",
                      body)
        self.assertIn("`ui` is `true` when the JSON's `ui.files` is above 0, and `false` when "
                      "it is 0.", body)
        self.assertIn("Leave the key out when the JSON's `ui` is null or absent", body)

    def test_clarify_reads_the_computed_flag(self):
        body = flat(self.read["skills/clarify/SKILL.md"])
        self.assertIn("**UI.** When the impact map's `ui` is true (computed from the `ui.globs` "
                      "setting) and the request or the issue names no reference", body)
        self.assertNotIn("When the map tags a touched module `UI`", body)

    def test_setup_offers_the_globs_for_a_web_frontend(self):
        text = self.read["skills/setup/SKILL.md"]
        interview = section(text, "## Step 2 — Interview")
        lead = "- **UI files** (`ui.globs`)"
        self.assertIn(lead, interview)
        bullet = flat(paragraph(interview, lead))
        for phrase in ("only when the project has a web frontend", "HTML templates",
                       "style sheets", "component framework", "Recommend globs for the "
                       "directories that hold those files",
                       "its tests can pass while its screen is wrong",
                       "A project with no web frontend gets no question"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet)
        self.assertIn("`code_signals`, `forge`, `ui`)", flat(text))


if __name__ == "__main__":
    unittest.main()
