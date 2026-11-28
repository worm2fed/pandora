"""Pins astrolabe's rule anchors and pointers.

These tests pin a rule's heading, the anchor phrase that names it, the pointers that reach
it, and the size of the always-on core. A rule with no heading of its own (a
non-negotiable, a paragraph) is pinned by the phrase that states it. Reword the rest
freely; move or drop a rule, or reword an anchor phrase, and a test names what broke.

Run from the repository root: python3 -m unittest discover -s astrolabe/tests
"""

import json
import os
import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
REPO = PLUGIN.parent
SKILL_DIR = PLUGIN / "skills" / "astrolabe"
CORE = SKILL_DIR / "SKILL.md"
REFS = SKILL_DIR / "references"
DOMAIN = REFS / "domain-modeling.md"
FP = REFS / "fp-functional.md"
ARCH = REFS / "architecture-and-testing.md"

# 0.4.0's core had 87 lines; 0.5.0 may add at most 15 (worklog T005).
CORE_MAX_LINES = 102

SHAPE_SECTIONS = (
    "The tells of an illegal state",
    "One owner per value",
    "One definition per concept",
    "Signatures",
)


def read(path):
    return path.read_text(encoding="utf-8")


def unfenced(text):
    """Blank every character inside fenced code blocks (newlines stay), so a `#` or `1.`
    line in an example is never taken for a heading or a list item. Offsets are kept."""
    return re.sub(r"^```.*?^```", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                  text, flags=re.MULTILINE | re.DOTALL)


def section(text, heading):
    """Return the section under `heading` (any level) up to the next heading of the
    same or a higher level. Fails the calling test when the heading is missing."""
    masked = unfenced(text)
    match = re.search(r"^(#+) " + re.escape(heading) + r"[ \t]*$", masked, re.MULTILINE)
    if match is None:
        raise AssertionError("no heading %r" % heading)
    level = len(match.group(1))
    end = re.compile(r"^#{1,%d} " % level, re.MULTILINE).search(masked, match.end())
    return text[match.end(): end.start() if end else len(text)]


def numbered_item(text, number):
    """Return item `number` of the first numbered list in `text`, up to the next item, a
    heading or the first paragraph after the list."""
    masked = unfenced(text)
    match = re.search(r"^%d\. " % number, masked, re.MULTILINE)
    if match is None:
        raise AssertionError("no item %d" % number)
    end = re.compile(r"^(?:\d+\. |#)|\n\n(?=\S)", re.MULTILINE).search(masked, match.end())
    return text[match.end(): end.start() if end else len(text)]


def item_count(text):
    """The number of the last item of the first numbered list in `text`."""
    return max(int(n) for n in re.findall(r"^(\d+)\. ", unfenced(text), re.MULTILINE))


def flat(text):
    """Collapse whitespace, so a phrase that wraps across lines still matches."""
    return " ".join(text.split())


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.core = read(CORE)
        self.nonneg = section(self.core, "Non-negotiables (always apply, no reference read needed)")

    def test_the_core_stays_short(self):
        lines = self.core.count("\n")
        self.assertLessEqual(lines, CORE_MAX_LINES,
                             "SKILL.md has %d lines; the cap is %d" % (lines, CORE_MAX_LINES))

    def test_non_negotiable_1_says_what_a_cast_comment_may_not_do(self):
        item = flat(numbered_item(self.nonneg, 1))
        self.assertIn("names its cause", item)
        self.assertIn("never stands in for the fix", item)
        self.assertIn("annotation on an untyped value", item)
        self.assertIn("may target only `unknown`, or a type that a parser then narrows", item)
        self.assertIn("untrusted input is parsed", item)

    def test_the_shape_group_carries_the_short_rules(self):
        item = flat(numbered_item(self.nonneg, 11))
        self.assertTrue(item.startswith("**Shape"), item[:60])
        for phrase in ("a closed set is a union", "one owner", "one definition",
                       "no more than its body uses", "return type", "parsed"):
            self.assertIn(phrase, item)
        self.assertIn("**Shape rules**", item)
        self.assertIn("references/domain-modeling.md", item)
        self.assertIn("references/architecture-and-testing.md", item)

    def test_a_signature_writer_is_routed_to_the_shape_rules(self):
        table = section(self.core, "Routing table")
        rows = [r for r in table.splitlines() if r.startswith("|") and "signature" in r]
        self.assertEqual(len(rows), 1, rows)
        cells = [c.strip() for c in rows[0].strip("|").split("|")]
        self.assertIn("shared value", cells[0])
        self.assertIn("**Shape rules**", cells[1])
        self.assertIn("references/domain-modeling.md", cells[1])


class PointerTest(unittest.TestCase):
    """Every pointer between astrolabe's files reaches a file and a heading that exist."""

    def test_every_reference_the_core_names_exists(self):
        names = set(re.findall(r"references/[\w-]+\.md", read(CORE)))
        self.assertTrue(names)
        for name in names:
            self.assertTrue((SKILL_DIR / name).is_file(), name)

    def test_every_bold_section_the_routing_table_names_exists(self):
        table = section(read(CORE), "Routing table")
        pairs = 0
        for row in table.splitlines():
            for bold, ref in re.findall(r"\*\*([^*]+)\*\*[^|]*?`(references/[\w-]+\.md)`", row):
                section(read(SKILL_DIR / ref), bold)
                pairs += 1
        self.assertGreaterEqual(pairs, 2)

    def test_the_cross_reference_pointers_reach_a_heading(self):
        domain = read(DOMAIN)
        section(domain, "One definition per concept")  # pointed to by fp-functional
        section(domain, "Signatures")                   # pointed to by architecture
        self.assertIn("One definition per concept", flat(read(FP)))
        self.assertIn("Signatures", flat(section(read(ARCH), "Persistence rules")))

    def test_every_numbered_pointer_reaches_its_item(self):
        """'non-negotiable N' and '#N' reach a non-negotiable; 'item N' and 'items N to M'
        in domain-modeling reach a checklist item. A renumbering breaks a pointer here."""
        core = read(CORE)
        nonneg = section(core, "Non-negotiables (always apply, no reference read needed)")
        checklist = section(read(DOMAIN), "Type review checklist")
        anchors = {1: "cast", 3: "precondition", 11: "Shape"}
        texts = [core] + [read(p) for p in sorted(REFS.glob("*.md"))]
        found = 0
        for text in texts:
            for n in re.findall(r"non-negotiable (\d+)|(?<![\w&#])#(\d+)\b", flat(text)):
                number = int(n[0] or n[1])
                self.assertLessEqual(number, item_count(nonneg), number)
                if number in anchors:
                    self.assertIn(anchors[number], flat(numbered_item(nonneg, number)))
                found += 1
        for first, last in re.findall(r"items? (\d+)(?: to (\d+))?", flat(read(DOMAIN))):
            self.assertLessEqual(int(last or first), item_count(checklist))
        self.assertGreaterEqual(found, 5)


class DomainModelingTest(unittest.TestCase):
    def setUp(self):
        self.text = read(DOMAIN)
        self.shape = section(self.text, "Shape rules")
        self.checklist = section(self.text, "Type review checklist")

    def test_each_shape_rule_has_a_section_with_a_typescript_example(self):
        for heading in SHAPE_SECTIONS:
            body = section(self.shape, heading)
            self.assertIn("```ts", body, heading)

    def test_the_tells_name_each_kind(self):
        tells = flat(section(self.shape, "The tells of an illegal state")).lower()
        for phrase in ("closed set", "optional", "sentinel", "two meanings", "return type"):
            self.assertIn(phrase, tells)

    def test_the_signature_section_holds_the_helper_argument_rule(self):
        self.assertIn("non-nullable", flat(section(self.shape, "Signatures")))


    def test_the_checklist_gains_its_items_in_order(self):
        items = [int(n) for n in re.findall(r"^(\d+)\. ", self.checklist, re.MULTILINE)]
        self.assertEqual(items, list(range(1, 11)))
        expected = {
            4: "tells",
            7: "one owner",
            8: "one definition",
            9: "no more than its body uses",
            10: "non-negotiable 1",
        }
        for number, phrase in expected.items():
            self.assertIn(phrase, flat(numbered_item(self.checklist, number)), number)
        self.assertIn("return type", flat(numbered_item(self.checklist, 9)))

    def test_the_cast_item_points_and_does_not_restate(self):
        item = flat(numbered_item(self.checklist, 10))
        self.assertNotIn("cause", item)

    def test_the_checklist_ends_with_the_self_check(self):
        blocks = [b for b in self.checklist.strip().split("\n\n") if b.strip()]
        self.assertTrue(blocks[-1].startswith("**Self-check"), blocks[-1][:60])


class FpFunctionalTest(unittest.TestCase):
    def test_when_not_to_abstract_guards_a_concept_spelled_twice(self):
        text = read(FP)
        start = text.index("**When NOT to abstract:**")
        block = flat(text[start: text.index("\n## ", start)])
        self.assertIn("spelled twice", block)
        self.assertIn("One definition per concept", block)


class ArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.text = read(ARCH)

    def test_the_helper_argument_rule_moved_and_a_pointer_stays(self):
        persistence = flat(section(self.text, "Persistence rules"))
        self.assertNotIn("Helpers require non-nullable arguments", persistence)
        self.assertIn("Signatures", persistence)

    def test_untrusted_input_is_parsed_and_an_annotation_is_a_cast(self):
        boundary = flat(section(self.text, "Validation at exactly two boundaries"))
        self.assertIn("parses the untrusted input it receives", boundary)
        self.assertIn("annotation on an untyped value", boundary)
        self.assertIn("non-negotiable 1", boundary)
        self.assertIn("```ts", boundary)


class ReleaseTest(unittest.TestCase):
    def test_the_plugin_and_the_marketplace_carry_one_version(self):
        plugin = json.loads(read(PLUGIN / ".claude-plugin" / "plugin.json"))
        market = json.loads(read(REPO / ".claude-plugin" / "marketplace.json"))
        entry = [p for p in market["plugins"] if p["name"] == "astrolabe"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["version"], plugin["version"])
        self.assertIn("v" + plugin["version"], read(PLUGIN / "README.md"))


# The repository is public. These forms never belong in astrolabe's files: a home
# directory path, an email address other than the published author's, a URL or a bare
# host name (a URL names a host; a public link needs a deliberate exception here), a
# tracker key (capitals, a hyphen, digits) or a merge-request reference (an exclamation
# mark and digits). A maintainer can add the names of private projects through
# PANDORA_PRIVATE_NAMES (comma-separated); the names themselves are never committed.
AUTHOR_EMAIL = json.loads(read(PLUGIN / ".claude-plugin" / "plugin.json"))["author"]["email"]
STANDARD_KEYS = ("UTF", "SHA", "ISO", "RFC", "ES", "ECMA")  # UTF-8, SHA-256, ISO-8601 ...
TEXT_SUFFIXES = (".md", ".json", ".py", ".txt", ".yml", ".yaml", ".toml", ".ts", ".js", ".sh")
PRIVATE_FORMS = {
    "home path": re.compile(r"(?:/(?:Users|home)/|~/|[A-Z]:\\Users\\)[A-Za-z.]"),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b"),
    "url": re.compile(r"https?://"),
    "host name": re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io|dev|ai|co|app)\b"),
    "tracker key": re.compile(r"\b([A-Z][0-9A-Z]{1,9})-[0-9]+\b"),
    "merge request": re.compile(r"(?<![\w!])![0-9]+\b"),
}


class PrivateNameTest(unittest.TestCase):
    def files(self):
        return [p for p in PLUGIN.rglob("*")
                if p.is_file() and p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts]

    def test_no_file_carries_a_private_form(self):
        hits = []
        for path in self.files():
            text = read(path).replace(AUTHOR_EMAIL, "")
            for kind, pattern in PRIVATE_FORMS.items():
                for match in pattern.finditer(text):
                    if kind == "tracker key" and match.group(1) in STANDARD_KEYS:
                        continue
                    hits.append("%s: %s %r" % (path.relative_to(REPO), kind, match.group(0)))
        self.assertEqual(hits, [])

    def test_the_forms_catch_what_they_name_and_pass_standard_terms(self):
        def kinds(text):
            return sorted(k for k, p in PRIVATE_FORMS.items()
                          if any(not (k == "tracker key" and m.group(1) in STANDARD_KEYS)
                                 for m in p.finditer(text)))
        self.assertEqual(kinds("see " + "ABC" + "-123"), ["tracker key"])
        self.assertEqual(kinds("UTF-8, SHA-256, ISO-8601, fp-ts@2.16.0"), [])
        self.assertEqual(kinds("~" + "/work/x"), ["home path"])
        self.assertEqual(kinds("deploy to shop" + ".example" + ".com"), ["host name"])
        self.assertEqual(kinds("C:" + "\\Users\\x"), ["home path"])
        self.assertEqual(kinds("mail dev" + "@" + "shop.example" + ".org"), ["email", "host name"])
        self.assertEqual(kinds("see " + "https" + "://x"), ["url"])
        self.assertEqual(kinds("see " + "!" + "42"), ["merge request"])

    def test_no_file_names_a_listed_private_project(self):
        names = [n.strip().lower() for n in os.environ.get("PANDORA_PRIVATE_NAMES", "").split(",")
                 if n.strip()]
        if not names:
            self.skipTest("PANDORA_PRIVATE_NAMES is not set")
        hits = []
        for path in self.files():
            text = read(path).lower()
            hits += ["%s: %s" % (path.relative_to(REPO), n) for n in names if n in text]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
