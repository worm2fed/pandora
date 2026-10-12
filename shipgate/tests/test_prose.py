"""Contract tests for the prose the model reads.

The "Writing for people" rule (ADR 0006) is one blockquote repeated verbatim in every skill
and agent that prescribes a report for a person, so the copies must stay identical and every
listed surface must carry one. The config template must declare the `Writing style` section
the artifact-writing skills read.
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


if __name__ == "__main__":
    unittest.main()
