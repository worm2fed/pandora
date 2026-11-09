"""Contract tests for the prose the model reads.

The "Writing for people" rule (ADR 0006) is one blockquote repeated verbatim in every skill
and agent that prescribes a report for a person, so the copies must stay identical and every
listed surface must carry one. The config template must declare the `Writing style` section
the artifact-writing skills read.

The config layering rule (ADR 0018) has two homes, the template's header and the README's
Configuration section; every skill that reads the config cites them with one shared callout.
`model-tiers` holds the built-in worker discipline, and `feature` holds the executive
contract that `clarify`, `design`, `setup` and the glossary cite.
"""

from __future__ import annotations

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
READ_STEM = "The config's **Writing style** section (`Docs: ste-80`) applies the Writing for people rule to"
READ_SENTENCE = re.compile(
    re.escape(READ_STEM) + r"[^\n]*(?:\n[^\n]+)*?absent,\s+a placeholder,\s+or `plain`,\s+write (?:it|them) as\s+before\."
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


class TestWritingStyleConfigSection(unittest.TestCase):
    def test_config_template_declares_the_section_with_its_default(self):
        text = (SHIPGATE / "config-template.md").read_text()
        self.assertIn("## Writing style", text)
        section = text.split("## Writing style", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- Docs:", section)
        self.assertIn("plain", section)
        self.assertIn("ste-80", section)
        self.assertIn("Default when absent: plain", section)

    def test_readme_table_lists_the_section(self):
        text = (SHIPGATE / "README.md").read_text()
        self.assertRegex(text, re.compile(r"^\| Writing style \|", re.M), "README config table row")


CONFIG_CALLOUT = (
    "> **Config:** `.claude/shipgate.md` (the repo's, then the umbrella's) and the user file\n"
    "> `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`) override the defaults\n"
    "> below. They layer per section by the rule in `config-template.md`'s header and the\n"
    "> README's Configuration section; read them first if present."
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
OLD_CONFIG_CALLOUT = "**Project config:**"
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
                self.assertFalse(OLD_CONFIG_CALLOUT in text, "the old project-config callout")
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
        for heading in ("## Writing style", "## Code tooling", "## Autonomy"):
            with self.subTest(section=heading):
                self.assertIn(USUALLY_PERSONAL, section(text, heading))
        self.assertEqual(text.count(USUALLY_PERSONAL), 3)


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
            "clarify": section((SHIPGATE / "skills/clarify/SKILL.md").read_text(), "### Executive mode (config Autonomy: `executive`)"),
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

    def test_template_autonomy_is_mode_and_extra_escalations_only(self):
        body = section((SHIPGATE / "config-template.md").read_text(), "## Autonomy")
        bullets = re.findall(r"^- ([^:]+):", body, re.M)
        self.assertEqual(bullets, ["Mode", "Extra escalations"])
        self.assertNotIn("Executive contract", body)
        self.assertIn("`feature`", body)


if __name__ == "__main__":
    unittest.main()
