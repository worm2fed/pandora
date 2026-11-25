#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: ``assumptions`` (#24, option P).

The parser of a PRD's "Assumptions (executive)" lines: the tagged line format, the exit 2
on a bad line, and the ``--risky`` batch that clarify puts to the user. Helpers come from
``test_journal.py``.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_journal_assumptions.py'
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from test_journal import JournalTestCase, OK, USAGE, load_journal_module


J = load_journal_module()

# A well-formed section. The line numbers in the comments are the 1-based file lines.
WELL_FORMED = """\
# PRD: late fees

## Requirements

- [domain] [source: docs/x.md] a list item outside the section → ignored

## Assumptions (executive)



- [domain] [no source found in docs/finance/, the billing tests] When does a fee start? → After a 10-day grace period — the usual net terms
- [data] [blindspot] [source: docs/finance/late-fees.md] Which currency? → The invoice currency [kept by the user]
- [behaviour] [reference] [no source found in the invoice templates] Is the fee shown on the invoice? → Yes, as its own line — users dispute hidden fees
  and support asks for it [changed by the user, was: No]
* [technical] [source: billing/fees.py] Where does the rule live? → In the fee module [unconfirmed]

- [domain] [no source found in the tracker] Is the fee capped? → At 10% of the invoice

## Open questions

- [domain] text under the next heading is not parsed
"""

# The items WELL_FORMED gives, in order.
WELL_FORMED_ITEMS = [
    {"line": 11, "class": "domain", "kind": None, "source": None,
     "searched": "docs/finance/, the billing tests", "question": "When does a fee start?",
     "answer": "After a 10-day grace period", "rationale": "the usual net terms",
     "end": None, "was": None},
    {"line": 12, "class": "data", "kind": "blindspot",
     "source": "docs/finance/late-fees.md", "searched": None, "question": "Which currency?",
     "answer": "The invoice currency", "rationale": None, "end": "kept", "was": None},
    {"line": 13, "class": "behaviour", "kind": "reference", "source": None,
     "searched": "the invoice templates", "question": "Is the fee shown on the invoice?",
     "answer": "Yes, as its own line",
     "rationale": "users dispute hidden fees and support asks for it",
     "end": "changed", "was": "No"},
    {"line": 15, "class": "technical", "kind": None, "source": "billing/fees.py",
     "searched": None, "question": "Where does the rule live?",
     "answer": "In the fee module", "rationale": None, "end": "unconfirmed", "was": None},
    {"line": 17, "class": "domain", "kind": None, "source": None,
     "searched": "the tracker", "question": "Is the fee capped?",
     "answer": "At 10% of the invoice", "rationale": None, "end": None, "was": None},
]

ITEM_KEYS = {"line", "class", "kind", "source", "searched", "question", "answer",
             "rationale", "end", "was"}


def section(*items, lead="# PRD: late fees\n\n## Assumptions (executive)\n\n"):
    """A PRD whose section holds ``items``; the first item is on line 5."""
    return lead + "".join(item + "\n" for item in items)


def risky(n):
    """An unsourced domain item numbered ``n``."""
    return f"- [domain] [no source found in docs/] Question {n}? → Answer {n}"


class TestParse(unittest.TestCase):
    """`parse_assumptions(text)`: the line contract, in-process."""

    def test_a_well_formed_section_parses_every_field(self):
        self.assertEqual(J.parse_assumptions(WELL_FORMED), WELL_FORMED_ITEMS)

    def test_no_section_gives_an_empty_list(self):
        self.assertEqual(J.parse_assumptions("# PRD\n\n## Requirements\n\n- FR-001\n"), [])
        self.assertEqual(J.parse_assumptions(""), [])

    def test_blank_lines_are_ignored(self):
        items = J.parse_assumptions(section("", "", "- [data] [source: a.md] Q? → A", ""))
        self.assertEqual([(i["line"], i["question"]) for i in items], [(7, "Q?")])
        self.assertEqual(J.parse_assumptions(section("", "")), [])

    def test_any_other_line_is_a_bad_line(self):
        # The user's decision on R5-1 (round 5): the section holds blank lines, item lines
        # and their continuation lines, nothing else. No guessing about bullets: a wrong
        # bullet, a missing bullet and stray prose all fail the same way.
        reason = "only assumption lines belong in this section"
        for bad in ("_None._", "Some prose about the list.", "`a.md` is the source.",
                    "### Notes", "# a comment", "<!-- a comment -->",
                    "-[data] [source: a.md] Q? → A", "• [data] [source: a.md] Q? → A",
                    "– [data] [source: a.md] Q? → A", "-\t[data] [source: a.md] Q? → A",
                    "[data] [source: a.md] Q? → A", "1. [data] [source: a.md] Q? → A",
                    "12) [data] [source: a.md] Q? → A", "+ [data] [source: a.md] Q? → A",
                    "2026 is the year the fee starts."):
            with self.subTest(bad=bad):
                with self.assertRaises(J.AssumptionError) as ctx:
                    J.parse_assumptions(section("- [data] [source: a.md] Q? → A", "", bad))
                self.assertEqual((ctx.exception.line, ctx.exception.reason), (7, reason))

    def test_a_continuation_needs_an_open_item_and_two_spaces_or_a_tab(self):
        reason = "only assumption lines belong in this section"
        cases = {
            "indented first line": section("  continued? → A"),
            "indented after a blank line": section(
                "- [data] [source: a.md] Q? → A", "", "  continued"),
            "one space": section("- [data] [source: a.md] Q? → A", " continued"),
        }
        lines = {"indented first line": 5, "indented after a blank line": 7, "one space": 6}
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(J.AssumptionError) as ctx:
                    J.parse_assumptions(text)
                self.assertEqual((ctx.exception.line, ctx.exception.reason),
                                 (lines[label], reason))

    def test_an_item_line_keeps_its_own_error(self):
        # (b): a line that starts with the marker is an item; its form error is specific.
        for bad, reason in (("- Q? → A", "no class tag"),
                            ("- [legal] [source: a.md] Q? → A", "unknown class [legal]"),
                            ("* [domain] Q? → A", "no source tag")):
            with self.subTest(bad=bad):
                with self.assertRaises(J.AssumptionError) as ctx:
                    J.parse_assumptions(section(bad))
                self.assertEqual((ctx.exception.line, ctx.exception.reason), (5, reason))

    def test_text_after_the_next_heading_is_ignored(self):
        items = J.parse_assumptions(section(
            "- [data] [source: a.md] Q? → A", "## Notes", "- not an item at all"))
        self.assertEqual(len(items), 1)

    def test_a_code_fence_in_the_section_is_a_bad_line(self):
        for fence in ("```", "```markdown", "~~~", "~~~~ text", "  ```", "\t~~~",
                      "```x``` is a thing"):
            with self.subTest(fence=fence):
                with self.assertRaises(J.AssumptionError) as ctx:
                    J.parse_assumptions(section(
                        "- [data] [source: a.md] Q? → A", fence,
                        "- [domain] [source: a.md] R? → B"))
                self.assertEqual((ctx.exception.line, ctx.exception.reason),
                                 (6, "code block in the assumptions section"))

    def test_a_fence_outside_the_section_needs_no_handling(self):
        text = ("# PRD\n\n## Design notes\n\n```\n- [legal] not an item\n## not a heading\n"
                "```\n\n## Assumptions (executive)\n\n"
                "- [data] [source: a.md] Q? → A\n\n## Open questions\n\n"
                "~~~\n# open past the end\n- [legal] still not an item\n")
        items = J.parse_assumptions(text)
        self.assertEqual([i["line"] for i in items], [12])

    def test_a_second_heading_is_an_error_at_its_line(self):
        cases = {
            "after the section": section(
                "- [data] [source: a.md] Q? → A", "", "## Assumptions (executive)",
                "- [domain] [source: a.md] R? → B"),
            # A heading line inside a fence elsewhere still counts: no fence is read.
            "inside a fence before the section":
                "# PRD\n```\n## Assumptions (executive)\n```\n## Assumptions (executive)\n",
        }
        lines = {"after the section": 7, "inside a fence before the section": 5}
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(J.AssumptionError) as ctx:
                    J.parse_assumptions(text)
                self.assertEqual(
                    (ctx.exception.line, ctx.exception.reason),
                    (lines[label], 'a second "## Assumptions (executive)" heading'))

    def test_a_heading_that_is_not_a_line_of_its_own_is_no_section(self):
        for text in ("## Assumptions (executive) and more\n- [data] [source: a.md] Q? → A\n",
                     "  ## Assumptions (executive)\n- [data] [source: a.md] Q? → A\n",
                     "### Assumptions (executive)\n- [data] [source: a.md] Q? → A\n"):
            with self.subTest(text=text):
                self.assertEqual(J.parse_assumptions(text), [])

    def test_a_wrapped_item_is_joined_and_keeps_its_first_line(self):
        items = J.parse_assumptions(section(
            "- [domain] [no source found in docs/] Q", "  continued? → A",
            "    — because"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["line"], 5)
        self.assertEqual(items[0]["question"], "Q continued?")
        self.assertEqual(items[0]["rationale"], "because")

    def test_only_the_first_dash_after_the_arrow_splits_the_rationale(self):
        item = J.parse_assumptions(section(
            "- [data] [source: a.md] Q — still the question? → A — why — and more"))[0]
        self.assertEqual(item["question"], "Q — still the question?")
        self.assertEqual(item["answer"], "A")
        self.assertEqual(item["rationale"], "why — and more")

    def test_a_trailing_bracket_that_is_no_end_tag_stays_in_the_text(self):
        item = J.parse_assumptions(section(
            "- [data] [source: a.md] Q? → A — see [FR-003]"))[0]
        self.assertEqual(item["rationale"], "see [FR-003]")
        self.assertIsNone(item["end"])

    def test_a_tab_indented_line_continues_the_item(self):
        items = J.parse_assumptions(section(
            "- [domain] [no source found in docs/] Q", "\tcontinued? → A"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question"], "Q continued?")

    def test_a_trailing_bracket_with_end_like_words_can_be_text(self):
        item = J.parse_assumptions(section(
            "- [data] [source: a.md] Q? → A — rationale [Kept items list]"))[0]
        self.assertEqual(item["rationale"], "rationale [Kept items list]")
        self.assertIsNone(item["end"])
        item = J.parse_assumptions(section("- [data] [source: a.md] Q? → A [kept]"))[0]
        self.assertEqual((item["answer"], item["end"]), ("A [kept]", None))

    def test_an_unclosed_bracket_that_starts_the_question_stays_in_it(self):
        item = J.parse_assumptions(section(
            "- [domain] [no source found in docs/] [WIP Q? → A"))[0]
        self.assertEqual(item["question"], "[WIP Q?")
        self.assertEqual(item["searched"], "docs/")

    def test_a_leading_tag_matches_nested_brackets(self):
        items = J.parse_assumptions(section(
            "- [behaviour] [reference] [source: app/[id]/page.tsx] Which screen? → This one",
            "- [domain] [source: [ADR 12](docs/adr/0012.md)] Why? → Because"))
        self.assertEqual([i["source"] for i in items],
                         ["app/[id]/page.tsx", "[ADR 12](docs/adr/0012.md)"])
        self.assertEqual([i["question"] for i in items], ["Which screen?", "Why?"])

    def test_a_bad_item_raises_a_value_error_with_its_line(self):
        with self.assertRaises(ValueError) as ctx:
            J.parse_assumptions(section("- [data] [source: a.md] Q? → A",
                                        "- [data] Q? → A"))
        self.assertEqual(ctx.exception.line, 6)


class TestRiskyBatch(unittest.TestCase):
    """`risky_batch(items, cap)`: the filter, the order and the cap, in-process."""

    def test_the_cap_is_four(self):
        self.assertEqual(J.BATCH_CAP, 4)

    def test_only_unsourced_unanswered_non_technical_items_are_risky(self):
        batch, overflow = J.risky_batch(WELL_FORMED_ITEMS)
        self.assertEqual([i["line"] for i in batch], [11, 17])
        self.assertEqual(overflow, 0)

    def test_file_order_and_the_overflow(self):
        items = J.parse_assumptions(section(*(risky(n) for n in range(1, 7))))
        batch, overflow = J.risky_batch(items)
        self.assertEqual([i["question"] for i in batch],
                         ["Question 1?", "Question 2?", "Question 3?", "Question 4?"])
        self.assertEqual(overflow, 2)
        batch, overflow = J.risky_batch(items, cap=2)
        self.assertEqual((len(batch), overflow), (2, 4))

    def test_blindspot_and_reference_candidates_are_always_in_the_batch(self):
        items = J.parse_assumptions(section(
            "- [data] [source: a.md] Sourced, no kind? → A",
            "- [technical] [blindspot] [source: a.md] Sourced technical blindspot? → A",
            "- [behaviour] [reference] [source: app/screen.tsx] Sourced reference? → A",
            "- [technical] [reference] [no source found in app/] Unsourced reference? → A",
            "- [domain] [blindspot] [source: a.md] Answered? → A [kept by the user]",
            "- [technical] [no source found in docs/] Technical, no kind? → A"))
        batch, overflow = J.risky_batch(items)
        self.assertEqual([i["question"] for i in batch], [
            "Sourced technical blindspot?", "Sourced reference?", "Unsourced reference?"])
        self.assertEqual(overflow, 0)

    def test_candidates_count_toward_the_cap_in_file_order(self):
        items = J.parse_assumptions(section(
            risky(1), "- [technical] [reference] [source: a.tsx] Screen? → A", risky(2)))
        batch, overflow = J.risky_batch(items, cap=2)
        self.assertEqual([i["question"] for i in batch], ["Question 1?", "Screen?"])
        self.assertEqual(overflow, 1)


class TestAssumptionsCommand(JournalTestCase):
    """`journal.py assumptions <prd> [--risky] [--json]` as a subprocess."""

    def write(self, text, name="late-fees.md"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return name

    def run_json(self, *args):
        proc = self.journal("assumptions", *args, "--json", rc=OK)
        return json.loads(proc.stdout)

    def test_json_lists_every_item(self):
        prd = self.write(WELL_FORMED)
        self.assertEqual(self.run_json(prd), {
            "prd": prd, "section": True, "count": 5, "cap": None, "overflow": 0,
            "items": WELL_FORMED_ITEMS})

    def test_json_risky_shape(self):
        prd = self.write(WELL_FORMED)
        out = self.run_json(prd, "--risky")
        self.assertEqual(set(out), {"prd", "section", "count", "cap", "overflow", "items"})
        self.assertIs(out["section"], True)
        self.assertEqual(out["prd"], prd)
        self.assertEqual((out["count"], out["cap"], out["overflow"]), (2, 4, 0))
        self.assertEqual([set(i) for i in out["items"]], [ITEM_KEYS, ITEM_KEYS])
        self.assertEqual(out["items"], [WELL_FORMED_ITEMS[0], WELL_FORMED_ITEMS[4]])

    def test_risky_caps_six_at_four(self):
        prd = self.write(section(*(risky(n) for n in range(1, 7))))
        out = self.run_json(prd, "--risky")
        self.assertEqual((out["count"], out["cap"], out["overflow"]), (6, 4, 2))
        self.assertEqual([i["line"] for i in out["items"]], [5, 6, 7, 8])

    def test_risky_drops_sourced_technical_and_answered_items(self):
        prd = self.write(section(
            "- [domain] [source: docs/finance/late-fees.md] Sourced? → A",
            "- [technical] [no source found in docs/] Technical? → A",
            "- [data] [no source found in docs/] Kept? → A [kept by the user]",
            "- [behaviour] [no source found in docs/] Changed? → A [changed by the user, was: B]",
            "- [domain] [no source found in docs/] Unconfirmed? → A [unconfirmed]",
            "- [behaviour] [blindspot] [no source found in docs/] Risky? → A"))
        out = self.run_json(prd, "--risky")
        self.assertEqual([i["question"] for i in out["items"]], ["Risky?"])

    def test_text_lists_one_line_per_item(self):
        prd = self.write(WELL_FORMED)
        proc = self.journal("assumptions", prd, rc=OK)
        lines = proc.stdout.splitlines()
        self.assertIn("11 [domain] When does a fee start? → After a 10-day grace period",
                      lines)
        self.assertIn("15 [technical] Where does the rule live? → In the fee module", lines)
        self.assertIn("5 assumptions", lines)

    def test_text_risky_states_the_count_and_the_overflow(self):
        prd = self.write(section(*(risky(n) for n in range(1, 7))))
        proc = self.journal("assumptions", prd, "--risky", rc=OK)
        self.assertEqual(proc.stdout.splitlines(), [
            "5 [domain] Question 1? → Answer 1",
            "6 [domain] Question 2? → Answer 2",
            "7 [domain] Question 3? → Answer 3",
            "8 [domain] Question 4? → Answer 4",
            "6 to confirm, 2 over the cap of 4",
        ])

    def test_no_section_is_empty_and_ok(self):
        prd = self.write("# PRD: late fees\n\n## Requirements\n\n- FR-001 a fee\n")
        self.assertEqual(self.run_json(prd, "--risky"),
                         {"prd": prd, "section": False, "count": 0, "cap": 4,
                          "overflow": 0,
                          "items": []})
        self.assertEqual(self.run_json(prd),
                         {"prd": prd, "section": False, "count": 0, "cap": None,
                          "overflow": 0, "items": []})

    def test_each_malformed_item_exits_2_with_its_line(self):
        good = "- [data] [source: a.md] Fine? → Yes"
        cases = {
            "no class tag": "- [source: a.md] Q? → A",
            "no class tag, plain text": "- Q? → A",
            "unknown class": "- [legal] [source: a.md] Q? → A",
            "no source tag": "- [domain] Q? → A",
            "no source tag after a kind": "- [domain] [blindspot] Q? → A",
            "two source tags": "- [domain] [source: a.md] [no source found in b/] Q? → A",
            "empty ref": "- [domain] [source: ] Q? → A",
            "empty searched": "- [domain] [no source found in ] Q? → A",
            "no arrow": "- [domain] [source: a.md] Q? -> A",
            "empty question": "- [domain] [source: a.md] → A",
            "empty answer": "- [domain] [source: a.md] Q? →  — why",
            "broken kept": "- [domain] [source: a.md] Q? → A [kept by user]",
            "broken changed": "- [domain] [source: a.md] Q? → A [changed by the user]",
            "empty was": "- [domain] [source: a.md] Q? → A [changed by the user, was: ]",
            "broken unconfirmed": "- [domain] [source: a.md] Q? → A [unconfirmed by anyone]",
            "ordered list, dot": "1. [domain] [source: a.md] Q? → A",
            "ordered list, paren": "12) [domain] [source: a.md] Q? → A",
            "plus list": "+ [domain] [source: a.md] Q? → A",
            "indented dash item": "  - [domain] [source: a.md] Q? → A",
            "indented star item": "\t* [domain] [source: a.md] Q? → A",
            "end words in another case, kept": "- [domain] [source: a.md] Q? → A [Kept by the user]",
            "end words in another case, changed":
                "- [domain] [source: a.md] Q? → A [Changed by the user, was: B]",
            "end words in another case, unconfirmed": "- [domain] [source: a.md] Q? → A [UNCONFIRMED]",
            "a dot after the end tag": "- [domain] [source: a.md] Q? → A [kept by the user].",
            "a semicolon after the end tag": "- [domain] [source: a.md] Q? → A [unconfirmed] ;",
            "punctuation after a changed tag":
                "- [domain] [source: a.md] Q? → A [changed by the user, was: B]!",
            "unclosed leading tag": "- [domain] [source: app/[id/page.tsx Q? → A",
            "unclosed class tag": "- [domain Q? → A",
            "unclosed kind tag": "- [domain] [blindspot Q? → A",
            "a date after the end tag":
                "- [domain] [source: a.md] Q? → A [kept by the user] (2026-11-24)",
            "a rationale after the end tag":
                "- [domain] [source: a.md] Q? → A [kept by the user] — ok",
            "text after a changed tag":
                "- [domain] [source: a.md] Q? → A [changed by the user, was: B] and more",
            "text after an upper-case tag": "- [domain] [source: a.md] Q? → A [UNCONFIRMED] later",
            "an end tag inside the answer": "- [domain] [source: a.md] Q? → A [unconfirmed] B — why",
        }
        for label, bad in cases.items():
            with self.subTest(label):
                prd = self.write(section(good, "", bad, good, bad))
                proc = self.journal("assumptions", prd, "--risky", rc=USAGE)
                self.assertEqual(proc.stdout, "")
                self.assertIn(f"{prd}:7: ", proc.stderr)
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1)

    def test_the_message_names_the_problem(self):
        prd = self.write(section("- [domain] Q? → A"))
        proc = self.journal("assumptions", prd, rc=USAGE)
        self.assertEqual(proc.stderr, f"error: {prd}:5: no source tag\n")

    def test_a_wrapped_bad_item_names_its_first_line(self):
        prd = self.write(section("- [domain] [source: a.md] Q?", "  no arrow here"))
        proc = self.journal("assumptions", prd, rc=USAGE)
        self.assertIn(f"{prd}:5: ", proc.stderr)

    def test_the_new_errors_name_the_problem(self):
        cases = {
            "1. [domain] [source: a.md] Q? → A": "only assumption lines belong in this section",
            "+ [domain] [source: a.md] Q? → A": "only assumption lines belong in this section",
            "_None._": "only assumption lines belong in this section",
            "  - [domain] [source: a.md] Q? → A": "indented list item",
            "- [domain] [source: a.md] Q? → A [Kept by the user]":
                "broken end tag [Kept by the user]",
            "- [domain] [source: a.md] Q? → A [kept by the user].": "text after the end tag",
            "- [domain] [source: app/[id/page.tsx Q? → A": "unclosed [ in a tag",
            "- [data] [source: a.md] Q? → A [kept by the user] — ok": "text after the end tag",
            "```": "code block in the assumptions section",
            "~~~ example": "code block in the assumptions section",
        }
        for bad, reason in cases.items():
            with self.subTest(bad):
                prd = self.write(section(bad))
                proc = self.journal("assumptions", prd, rc=USAGE)
                self.assertEqual(proc.stderr, f"error: {prd}:5: {reason}\n")

    def test_a_second_heading_exits_2_with_its_line(self):
        prd = self.write(section(risky(1), "## Assumptions (executive)", risky(2)))
        proc = self.journal("assumptions", prd, "--risky", rc=USAGE)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr,
                         f'error: {prd}:6: a second "## Assumptions (executive)" heading\n')

    def test_json_says_whether_the_section_was_found(self):
        empty = self.write(section(""), name="empty.md")
        absent = self.write("# PRD\n\n## Requirements\n", name="absent.md")
        for flags in ((), ("--risky",)):
            with self.subTest(flags):
                self.assertIs(self.run_json(empty, *flags)["section"], True)
                self.assertIs(self.run_json(absent, *flags)["section"], False)

    def test_text_with_no_section_says_so(self):
        prd = self.write("# PRD\n\n## Requirements\n")
        heading = 'no "## Assumptions (executive)" section'
        proc = self.journal("assumptions", prd, rc=OK)
        self.assertEqual(proc.stdout.splitlines(), [heading, "0 assumptions"])
        proc = self.journal("assumptions", prd, "--risky", rc=OK)
        self.assertEqual(proc.stdout.splitlines(), [heading, "0 to confirm, 0 over the cap of 4"])
        proc = self.journal("assumptions", self.write(section(""), name="e.md"), rc=OK)
        self.assertEqual(proc.stdout.splitlines(), ["0 assumptions"])

    def test_cap_reduces_the_batch(self):
        prd = self.write(section(
            risky(1), "- [behaviour] [reference] [source: app/screen.tsx] Screen? → A",
            risky(2), risky(3)))
        out = self.run_json(prd, "--risky", "--cap", "2")
        self.assertEqual((out["count"], out["cap"], out["overflow"]), (4, 2, 2))
        self.assertEqual([i["question"] for i in out["items"]], ["Question 1?", "Screen?"])
        proc = self.journal("assumptions", prd, "--risky", "--cap", "2", rc=OK)
        self.assertEqual(proc.stdout.splitlines()[-1], "4 to confirm, 2 over the cap of 2")

    def test_cap_zero_and_four(self):
        prd = self.write(section(*(risky(n) for n in range(1, 6))))
        out = self.run_json(prd, "--risky", "--cap", "0")
        self.assertEqual((out["count"], out["cap"], out["overflow"], out["items"]),
                         (5, 0, 5, []))
        out = self.run_json(prd, "--risky", "--cap", "4")
        self.assertEqual((out["count"], out["cap"], out["overflow"]), (5, 4, 1))

    def test_a_bad_cap_exits_2(self):
        prd = self.write(section(risky(1)))
        for cap in ("5", "-1"):
            with self.subTest(cap):
                proc = self.journal("assumptions", prd, "--risky", "--cap", cap, rc=USAGE)
                self.assertEqual(proc.stdout, "")
                self.assertEqual(proc.stderr,
                                 "error: --cap takes an integer from 0 to 4, got " + cap + "\n")
        for cap in ("x", "2.5"):
            with self.subTest(cap):
                proc = self.journal("assumptions", prd, "--risky", "--cap", cap, rc=USAGE)
                self.assertEqual(proc.stdout, "")
                self.assertIn("argument --cap: invalid int value", proc.stderr)

    def test_cap_without_risky_exits_2(self):
        prd = self.write(section(risky(1)))
        proc = self.journal("assumptions", prd, "--cap", "2", rc=USAGE)
        self.assertEqual(proc.stdout, "")
        self.assertIn("--risky", proc.stderr)

    def test_a_missing_file_exits_2(self):
        proc = self.journal("assumptions", "docs/prd/absent.md", rc=USAGE)
        self.assertIn("docs/prd/absent.md", proc.stderr)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1)

    def test_it_needs_no_journal(self):
        """No `.claude/` at all, and a project whose settings declare no journal."""
        prd = self.write(WELL_FORMED)
        self.assertFalse((self.root / ".claude").exists())
        self.assertEqual(self.run_json(prd, "--risky")["count"], 2)
        claude = self.root / ".claude"
        claude.mkdir()
        (claude / "shipgate.json").write_text(
            json.dumps({"version": 2, "db": None}), encoding="utf-8")
        self.assertEqual(self.run_json(prd, "--risky")["count"], 2)
        self.assertFalse((claude / "shipgate.db").exists())
        self.assertFalse((self.root / "shipgate.db").exists())


class TestTemplateMatchesTheParser(unittest.TestCase):
    """The PRD template's section holds only a placeholder line, and it is a bad line, so
    a copied template exits 2 until clarify replaces it. The example lines live in
    clarify's SKILL.md, which the parser never reads; they parse and do not mirror eval
    cases 76 and 77 (review round 1, F1)."""

    CLARIFY = Path(__file__).resolve().parent.parent / "skills" / "clarify"
    ITEM = re.compile(r"^- \[(?:domain|data|behaviour|technical)\]")

    @classmethod
    def setUpClass(cls):
        cls.template = (cls.CLARIFY / "references" / "prd-template.md").read_text(
            encoding="utf-8")
        cls.skill = (cls.CLARIFY / "SKILL.md").read_text(encoding="utf-8")
        lines = cls.template.splitlines()
        start = lines.index("## Assumptions (executive)")
        end = next(n for n in range(start + 1, len(lines)) if lines[n].startswith("## "))
        cls.start, cls.section = start, lines[start:end]

    def test_the_template_section_holds_only_the_placeholder_line(self):
        # Round 5 (R5-1): the section of a fresh PRD holds the placeholder and blank lines,
        # nothing else; the explanation lives in clarify's SKILL.md.
        self.assertEqual(self.template.splitlines().count("## Assumptions (executive)"), 1)
        self.assertEqual([l for l in self.section[1:] if l.strip()],
                         ["- [<class>] [source: <ref>] <question> → <answer> — "
                          "<one-sentence rationale>"])
        self.assertEqual([l for l in self.template.splitlines() if self.ITEM.match(l)], [])

    def test_the_placeholder_is_a_bad_line(self):
        line = self.start + 1 + next(n for n, l in enumerate(self.section)
                                     if l.startswith("- [<class>]"))
        with self.assertRaises(J.AssumptionError) as ctx:
            J.parse_assumptions(self.template)
        self.assertEqual((ctx.exception.line, ctx.exception.reason),
                         (line, "unknown class [<class>]"))

    def test_the_skill_examples_parse(self):
        examples = [l for l in self.skill.splitlines() if self.ITEM.match(l)]
        self.assertEqual(len(examples), 3)
        items = J.parse_assumptions("## Assumptions (executive)\n\n" + "\n".join(examples))
        self.assertEqual([i["class"] for i in items], ["domain", "behaviour", "technical"])
        self.assertEqual([i["kind"] for i in items], [None, "reference", None])
        self.assertEqual([i["end"] for i in items], [None, "kept", None])
        self.assertEqual(len(J.risky_batch(items)[0]), 1)
        # Not the answers of case 76 (late fees on an invoice) or 77 (a date element).
        text = " ".join(examples).casefold()
        for word in ("fee", "invoice", "posting", "badge", "date", "pill"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
