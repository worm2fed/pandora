#!/usr/bin/env python3
"""Tests of the deterministic eval graders of #24 (shipgate 0.34.1).

A regex grader replaces an LLM judge where a script can decide: case 78's ``no-batch-lines``
mirrors the parser's batch rule, and case 16's ``api-escalated`` checks that the public API
decision sits under a ``NEEDS CLARIFICATION`` marker. The harness evaluates the pattern;
these tests run the same pattern with Python's ``re``. The patterns use only constructs
both engines read alike (classes, alternation, lazy repeats, a negative lookahead).

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_eval_graders.py'
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_journal import load_journal_module


J = load_journal_module()
EVALS = Path(__file__).resolve().parent.parent / "evals"
FLAGS = {"i": re.I, "m": re.M, "s": re.S}


def grader(case: str, name: str):
    """(front matter as a dict of raw strings, the compiled pattern) of a regex grader."""
    text = (EVALS / case / "graders" / f"{name}.md").read_text(encoding="utf-8")
    _, head, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in head.strip().splitlines())
    flags = 0
    for letter in meta.get("flags", ""):
        flags |= FLAGS[letter]
    return meta, re.compile(body.strip(), flags)


def section(*items: str) -> str:
    return "# PRD\n\n## Assumptions (executive)\n\n" + "".join(i + "\n" for i in items)


class TestCase78NoBatchLines(unittest.TestCase):
    """The grader fails on any line the batch rule picks, whatever its end tag: in the
    harness there is no dialog, so a batch line ends `[unconfirmed]` and the parser no
    longer counts it, but a batch was still formed."""

    CASE = "78-clarify-exec-fully-specified"
    LINES = [
        "- [domain] [no source found in docs/] Q? → A",
        "- [data] [no source found in schema.sql] Q? → A",
        "- [behaviour] [no source found in the request] Q? → A",
        "- [domain] [source: docs/finance/statements.md] Q? → A",
        "- [technical] [no source found in the tests] Q? → A",
        "- [technical] [blindspot] [source: README.md] Q? → A",
        "- [behaviour] [reference] [source: web/page.html] Q? → A",
        "- [data] [blindspot] [no source found in docs/] Q? → A",
        "* [behaviour] [no source found in docs/] Q? → A",
    ]
    END_TAGS = ("", " [unconfirmed]", " [kept by the user]")

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.pattern = grader(cls.CASE, "no-batch-lines")

    def test_it_is_a_not_contains_regex_on_the_prd(self):
        self.assertEqual(self.meta["type"], "regex")
        self.assertEqual(self.meta["match"], "not_contains")
        self.assertEqual(self.meta["target"],
                         "{source: file, path: app/docs/prd/monthly-statement-pdf.md}")

    def test_it_flags_exactly_the_lines_the_batch_rule_picks(self):
        for line in self.LINES:
            item = J.parse_assumptions(section(line))[0]
            expected = bool(J.risky_batch([item])[0])
            for end in self.END_TAGS:
                with self.subTest(line=line, end=end):
                    found = bool(self.pattern.search(section(line + end)))
                    self.assertEqual(found, expected)

    def test_a_fully_sourced_section_passes(self):
        text = section(self.LINES[3], self.LINES[4],
                       "- [behaviour] [source: the request] Q? → A",
                       "  continued [no source found in docs/] in the text")
        self.assertIsNone(self.pattern.search(text))

    def test_a_grader_checks_that_the_prd_exists(self):
        # Review R1-6: the not_contains graders must not pass on a missing PRD.
        text = (EVALS / self.CASE / "graders" / "prd-written.md").read_text(encoding="utf-8")
        self.assertIn("type: file_exists", text)
        self.assertIn("app/docs/prd/monthly-statement-pdf.md", text)

    def test_the_request_links_the_document_the_fixture_writes(self):
        prompt = (EVALS / self.CASE / "prompt.md").read_text(encoding="utf-8")
        fixture = (EVALS / self.CASE / "fixture.sh").read_text(encoding="utf-8")
        self.assertIn("docs/finance/statements.md", prompt)
        self.assertIn("cat > docs/finance/statements.md", fixture)


class TestCase16ApiEscalated(unittest.TestCase):
    """The grader passes when a `NEEDS CLARIFICATION` marker and the public API decision
    (`GET /customers`) sit in the same item."""

    CASE = "16-clarify-exec-one-way-door"
    ESCALATED = {
        "marker first": "- `[NEEDS CLARIFICATION]` **Public API contract for `GET /customers`.**",
        "marker first, numbered": "1. `[NEEDS CLARIFICATION]` **Public API: does `GET /customers`"
                                  " hide deleted customers?**",
        "api on the continuation line": "- `[NEEDS CLARIFICATION]` **Q1 — public API contract"
                                        " (one-way door).** Does the public\n  `GET /customers`"
                                        " response change?",
        "api first, same line": "  The effect on the public `GET /customers` response is"
                                " `[NEEDS CLARIFICATION]` — see Q1.",
        "colon form": "- [NEEDS CLARIFICATION: does GET /customers omit deleted customers?]",
        # Review R1-5: an indented option list stays inside the marker's item.
        "indented option list": "- `[NEEDS CLARIFICATION]` **Q1 — public response**\n"
                                "  1. omit deleted customers from `GET /customers`\n"
                                "  2. flag them",
    }
    NOT_ESCALATED = {
        "api decided, marker on another item": (
            "- [behaviour] [source: docs/api.md] Does `GET /customers` omit deleted"
            " customers? → yes\n\n- `[NEEDS CLARIFICATION]` **Who is an admin, and are"
            " delete and restore part of the public API?**\n"),
        "marker item ends before the api item": (
            "- `[NEEDS CLARIFICATION]` **Who is an admin?** The service has no roles.\n"
            "- The public `GET /customers` response omits deleted customers.\n"),
        "no marker": "- `GET /customers` omits deleted customers (FR-004).\n",
        # Review R1-2: "API contract" in a marker item about another point is no escalation.
        "api contract on another question": (
            "- [behaviour] [source: docs/api.md] Does `GET /customers` omit deleted"
            " customers? → yes\n\n- `[NEEDS CLARIFICATION]` **Who is an admin?** Not part"
            " of the API contract.\n"),
        # Review R1-3: prose in lower case is no marker.
        "prose, lower case": "- [behaviour] [source: docs/api.md] Does GET /customers omit"
                             " deleted customers? → yes — nothing here needs clarification\n",
    }

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.pattern = grader(cls.CASE, "api-escalated")

    def test_it_replaces_the_llm_judge(self):
        self.assertFalse((EVALS / self.CASE / "graders" / "one-way-doors-escalated.md").exists())
        self.assertEqual(self.meta["type"], "regex")
        self.assertEqual(self.meta["target"],
                         "{source: file, path: app/docs/prd/customer-soft-delete.md}")
        self.assertNotIn("match", self.meta)  # contains, the default
        self.assertNotIn("flags", self.meta)  # R1-3: the marker is upper case

    def test_an_escalated_api_matches(self):
        for label, text in self.ESCALATED.items():
            with self.subTest(label):
                self.assertIsNotNone(self.pattern.search(text))

    def test_a_decided_or_unmarked_api_does_not_match(self):
        for label, text in self.NOT_ESCALATED.items():
            with self.subTest(label):
                self.assertIsNone(self.pattern.search(text))


if __name__ == "__main__":
    unittest.main()
