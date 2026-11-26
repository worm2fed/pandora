#!/usr/bin/env python3
"""Tests of the deterministic eval graders (#24, #28).

A regex grader replaces an LLM judge where a script can decide: case 78's ``no-batch-lines``
mirrors the parser's batch rule, and case 16's ``api-escalated`` checks that the public API
decision sits under a ``NEEDS CLARIFICATION`` marker. The harness evaluates the pattern;
these tests run the same pattern with Python's ``re``. The patterns use only constructs
both engines read alike (classes, alternation, lazy repeats, lookahead).

#28 adds the journal graders of 58 and 74 (checked against the journal their fixture
seeds), the regex graders that replace case 15's ``exec-hygiene`` and claim 3 of case
70's ``readable``, the split of case 76's ``batch-items-risky``, and the script graders
of cases 22 and 70 (ADR 0036), which run here on canned traces.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests -p 'test_eval_graders.py'
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_eval_fixtures import scaffold
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


# ----------------------------------------------------------------------------- #28 helpers
def append_event(db: Path, event_type: str, payload: dict) -> None:
    """Add a row as journal.py's append writes it (``_journal/append.py``: the payload as
    sorted-key JSON, the type in the column before it)."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("INSERT INTO events (stream, version, type, data, ts, actor) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     ("fix/1-new-flow", 1, event_type, json.dumps(payload, sort_keys=True),
                      "2026-11-26T10:00:00+00:00", "orchestrator"))
        conn.commit()
    finally:
        conn.close()


def file_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", "replace")


class JournalGrader:
    """A with-only regex grader on the journal file, against the journal that the case's
    own fixture seeds."""

    CASE = ""
    NAME = ""

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.pattern = grader(cls.CASE, cls.NAME)
        cls.tmp = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        work, _ = scaffold(EVALS / cls.CASE, cls.tmp)
        cls.seeded = work / ".claude" / "shipgate.db"

    def with_event(self, event_type: str, payload: dict) -> str:
        db = self.tmp / f"{event_type}.db"
        shutil.copyfile(self.seeded, db)
        append_event(db, event_type, payload)
        return file_text(db)

    def check_front_matter(self):
        self.assertEqual(self.meta["type"], "regex")
        self.assertEqual(self.meta["target"], "{source: file, path: .claude/shipgate.db}")
        self.assertEqual(self.meta["arm"], "with-only")
        self.assertNotIn("match", self.meta)

    def check_seed_does_not_match(self):
        self.assertTrue(self.seeded.is_file())
        self.assertIsNone(self.pattern.search(file_text(self.seeded)))


class TestCase58JournalPhaseEvent(JournalGrader, unittest.TestCase):
    """FR-021: 58 keeps one journal grader, date-free and with-only. Its seed (bigshop)
    holds no debug event, so the event type alone tells an appended row."""

    CASE = "58-big-debug-regression"
    NAME = "journal-phase-event-appended"

    def test_front_matter(self):
        self.check_front_matter()

    def test_it_holds_no_date(self):
        self.assertNotRegex(self.pattern.pattern, r"20\d\d|\\d\\d")

    def test_the_two_broken_graders_are_gone(self):
        for name in ("journal-any-event-appended", "journal-no-invented-types"):
            with self.subTest(name):
                self.assertFalse((EVALS / self.CASE / "graders" / f"{name}.md").exists())

    def test_the_seeded_journal_does_not_match(self):
        self.check_seed_does_not_match()

    def test_an_appended_debug_event_matches(self):
        for event_type in ("debug-root-cause", "bug-reproduced"):
            with self.subTest(event_type):
                text = self.with_event(event_type, {"summary": "ROUND_DOWN in apply_discount"})
                self.assertIsNotNone(self.pattern.search(text))

    def test_another_appended_event_does_not_match(self):
        self.assertIsNone(self.pattern.search(self.with_event("phase-entered",
                                                              {"phase": "debug"})))


class TestCase74JournalVerdict(JournalGrader, unittest.TestCase):
    """FR-021: 74's verdict grader is with-only. Its seed stops at task-done and holds no
    review-verdict row, so a match is the run's own verdict."""

    CASE = "74-review-canon-lens"
    NAME = "journal-verdict-appended"

    def test_front_matter(self):
        self.check_front_matter()

    def test_the_seeded_journal_does_not_match(self):
        self.check_seed_does_not_match()

    def test_an_appended_verdict_matches(self):
        for verdict in ("not-ready", "ready"):
            with self.subTest(verdict):
                text = self.with_event("review-verdict", {
                    "verdict": verdict, "findings": {"blocker": 2, "should_fix": 0, "nit": 0},
                    "style": ["typed-canon"]})
                self.assertIsNotNone(self.pattern.search(text))

    def test_a_verdict_in_another_event_does_not_match(self):
        self.assertIsNone(self.pattern.search(self.with_event("phase-entered", {
            "phase": "review", "verdict": "not-ready"})))


class TestCase15ExecHygiene(unittest.TestCase):
    """Two regex graders replace the LLM judge ``exec-hygiene``: an answered and reasoned
    item in the "Assumptions (executive)" section, and a non-empty non-goals list."""

    CASE = "15-clarify-exec-issue-seeded"
    TARGET = "{source: file, path: app/docs/prd/invoice-csv-export.md}"
    # Each item alone; the parser decides whether it has an answer and a rationale.
    ITEMS = [
        "- [domain] [source: docs/finance.md] Which invoices count as open? → unpaid ones"
        " — the ledger's own word",
        "* [behaviour] [blindspot] [no source found in docs/] Name column? → the legal name"
        " — finance matches on it [kept by the user]",
        "- [data] [no source found in schema.sql] Date format? → ISO 8601 —\n"
        "  spreadsheets read it in every locale",
        "- [technical] [source: tests/] Where do the tests live?\n  → beside the API tests"
        " — one place to look",
        "- [domain] [source: docs/finance.md] Which invoices count as open? → unpaid ones",
        "- [domain] [source: docs/finance.md] Open? → unpaid — [unconfirmed]",
        "- [domain] [source: docs/finance.md] Open? → unpaid — [kept by the user]",
        "- [domain] [source: docs/finance.md] Open? → unpaid - a hyphen is no rationale",
    ]
    NO_SECTION = {
        "no section": "# PRD\n\n## Goals\n\n- [domain] [source: x] Q? → A — r\n",
        "empty section, item in the next one": "# PRD\n\n## Assumptions (executive)\n\n"
                                               "## Open questions\n\n"
                                               "- [domain] [source: x] Q? → A — r\n",
        "heading at the end": "# PRD\n\n## Assumptions (executive)\n",
        "wrong heading level": "# PRD\n\n### Assumptions (executive)\n\n"
                               "- [domain] [source: x] Q? → A — r\n",
    }
    TEMPLATE = ("# PRD\n\n## Goals & non-goals\n\n**Goals**\n- Finance pulls invoices into"
                " a spreadsheet.\n\n**Non-goals** (explicitly out of scope)\n{}\n"
                "## Users & stories\n\n- As finance, I want a file.\n")
    NON_GOALS = {
        "template, filled": TEMPLATE.format("- Importing CSV files.\n"),
        "heading and list": "## Non-goals\n\n- Importing CSV files.\n\n## FR\n",
        "heading, other level and case": "### Non-Goals\n- PDF export\n",
        "heading, no hyphen": "## Non goals\nNo PDF export.\n",
        "bold label, inline": "**Non-goals:** PDF export.\n\n## FR\n",
    }
    NO_NON_GOALS = {
        "template, empty": TEMPLATE.format(""),
        "heading, empty section": "## Non-goals\n\n## Functional requirements\n\n- x\n",
        "heading at the end": "# PRD\n\n## Non-goals\n\n",
        "heading, only a label under it": "## Non-goals\n\n**Later**\n\n## FR\n",
        "bold label, only its note": "**Non-goals** (explicitly out of scope)\n\n## FR\n",
        "the word in prose": "## Scope\n\n- The non-goals are in the ticket.\n",
    }

    @classmethod
    def setUpClass(cls):
        cls.answered_meta, cls.answered = grader(cls.CASE, "assumptions-answered")
        cls.non_goals_meta, cls.non_goals = grader(cls.CASE, "non-goals-listed")

    def test_they_replace_the_llm_judge(self):
        self.assertFalse((EVALS / self.CASE / "graders" / "exec-hygiene.md").exists())
        for meta in (self.answered_meta, self.non_goals_meta):
            with self.subTest(meta=meta):
                self.assertEqual(meta["type"], "regex")
                self.assertEqual(meta["target"], self.TARGET)
                self.assertNotIn("match", meta)

    def test_an_item_matches_when_the_parser_reads_an_answer_and_a_rationale(self):
        for item in self.ITEMS:
            with self.subTest(item=item):
                parsed = J.parse_assumptions(section(item))
                self.assertEqual(len(parsed), 1)
                expected = parsed[0]["rationale"] is not None
                self.assertEqual(bool(self.answered.search(section(item))), expected)

    def test_one_reasoned_item_is_enough(self):
        self.assertIsNotNone(self.answered.search(section(self.ITEMS[4], self.ITEMS[0])))

    def test_an_arrow_outside_the_section_does_not_count(self):
        for label, text in self.NO_SECTION.items():
            with self.subTest(label):
                self.assertEqual(J.parse_assumptions(text), [])
                self.assertIsNone(self.answered.search(text))

    def test_a_listed_non_goal_matches(self):
        for label, text in self.NON_GOALS.items():
            with self.subTest(label):
                self.assertIsNotNone(self.non_goals.search(text))

    def test_an_empty_or_missing_non_goals_list_does_not_match(self):
        for label, text in self.NO_NON_GOALS.items():
            with self.subTest(label):
                self.assertIsNone(self.non_goals.search(text))


class TestCase76BatchClaims(unittest.TestCase):
    """FR-027: one judge per claim of ``batch-items-risky``, without "at most 4 items"
    (``test_the_cap_is_four`` in test_journal_assumptions.py pins the cap)."""

    CASE = "76-clarify-exec-confirm-batch"
    NAMES = ("batch-put-to-user", "batch-items-user-facing", "batch-items-alternative")

    def test_one_judge_per_claim_replaces_the_old_one(self):
        graders = EVALS / self.CASE / "graders"
        self.assertFalse((graders / "batch-items-risky.md").exists())
        for name in self.NAMES:
            with self.subTest(name):
                text = (graders / f"{name}.md").read_text(encoding="utf-8")
                _, head, body = text.split("---\n", 2)
                self.assertIn("type: llm", head)
                self.assertIn("focus: last_message", head)
                claims = [line for line in body.splitlines() if line.startswith("- ")]
                self.assertEqual(len(claims), 1)
                self.assertNotRegex(body, r"at most|\b4\b|four")


class TestCase70InlineCode(unittest.TestCase):
    """A regex replaces claim 3 of the LLM judge ``readable``: the three planted files
    appear in inline code. The pattern counts backticks from the start of each line, so a
    file name between two code spans is still bare."""

    CASE = "70-review-fact-retention"
    GOOD = ("Verdict: not ready.\n\n- F1 HIGH `db.py:18` — SQL built with an f-string.\n"
            "- F2 HIGH `app/export.py:18` — no CSV quoting.\n"
            "- F3 MEDIUM `report.py:19` — fee printed with `:.2f`.\n")
    IN_CODE = {
        "one span per finding": GOOD,
        "a later span on the line": "- see `x` then `db.py:18`\n- `export.py` and `report.py`\n",
        "one span names all three": "Files: `db.py, export.py, report.py`.\n",
    }
    BARE = {
        "one bare name": GOOD.replace("`report.py:19`", "report.py:19"),
        "a bare name after a span": "- `x` and db.py:18\n- `export.py` `report.py`\n",
        "a bare name between spans": "- `x` db.py `y`\n- `export.py` `report.py`\n",
        "names only in a fenced block": "```\ndb.py:18\nexport.py:18\nreport.py:19\n```\n",
        "no names": "Not ready: three findings.\n",
    }

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.pattern = grader(cls.CASE, "locations-inline-code")

    def test_it_replaces_the_llm_judge(self):
        self.assertFalse((EVALS / self.CASE / "graders" / "readable.md").exists())
        self.assertEqual(self.meta["type"], "regex")
        self.assertEqual(self.meta["target"], "last_message")
        self.assertEqual(self.meta["flags"], "m")
        self.assertNotIn("match", self.meta)

    def test_names_in_inline_code_match(self):
        for label, text in self.IN_CODE.items():
            with self.subTest(label):
                self.assertIsNotNone(self.pattern.search(text))

    def test_a_bare_or_missing_name_does_not_match(self):
        for label, text in self.BARE.items():
            with self.subTest(label):
                self.assertIsNone(self.pattern.search(text))


# ----------------------------------------------------------------------------- script graders
def tool_use(tool_id: str, name: str, **args) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": args}]}}


def tool_result(tool_id: str, content: str = "", is_error: bool = False) -> dict:
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content,
         "is_error": is_error}]}}


def assistant_text(text: str, parent=None) -> dict:
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "text", "text": text}]}}


def result_record(text: str) -> dict:
    return {"type": "result", "subtype": "success", "result": text}


class ScriptGrader:
    """A script grader run as the post-run step runs it: ``python3 <script> <trace>``."""

    SCRIPT = Path()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_on(self, records) -> subprocess.CompletedProcess:
        trace = self.tmp / "trace.jsonl"
        trace.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return subprocess.run([sys.executable, str(self.SCRIPT), str(trace)],
                              capture_output=True, text=True, timeout=60, check=False)

    def assert_verdict(self, records, passed: bool) -> str:
        proc = self.run_on(records)
        self.assertEqual(proc.returncode, 0 if passed else 1, proc.stdout + proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        return lines[0]

    def test_an_unreadable_trace_is_an_error(self):
        proc = subprocess.run([sys.executable, str(self.SCRIPT), str(self.tmp / "absent.jsonl")],
                              capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("cannot read trace", proc.stderr)


TEST_RUN = "cd app && python3 -m unittest -v"
EDIT = {"file_path": "/tmp/e-x/app/pricing.py", "old_string": "a", "new_string": "b"}


class TestCase22LastTestAfterLastEdit(ScriptGrader, unittest.TestCase):
    """The script grader of case 22 replaces the trace judge
    ``fresh-evidence-after-last-edit``: the last test run comes after the last edit of
    pricing.py."""

    SCRIPT = EVALS / "22-verify-stale-after-fix" / "script-graders" / "last-test-after-last-edit.py"
    WRITES = [
        ("Edit", EDIT),
        ("Write", {"file_path": "app/pricing.py", "content": "x"}),
        ("MultiEdit", {"file_path": "/tmp/e-x/app/pricing.py",
                       "edits": [{"old_string": "a", "new_string": "b"}]}),
        ("NotebookEdit", {"notebook_path": "app/pricing.py", "new_source": "x"}),
    ]
    RUNS = [
        TEST_RUN,
        "python3 -m unittest",
        "python -m unittest test_pricing",
        "python3 -m unittest discover -v 2>&1 | tail -5",
        "cd app; python3.9 -m unittest test_pricing",
    ]
    NOT_RUNS = [
        "grep -n unittest README.md",
    ]

    def test_the_trace_judge_is_gone(self):
        self.assertFalse((EVALS / "22-verify-stale-after-fix" / "graders"
                          / "fresh-evidence-after-last-edit.md").exists())

    def test_a_run_after_the_edit_passes(self):
        reason = self.assert_verdict([
            tool_use("t1", "Bash", command=TEST_RUN), tool_result("t1", "FAILED", True),
            tool_use("t2", "Edit", **EDIT), tool_result("t2", "ok"),
            tool_use("t3", "Bash", command=TEST_RUN), tool_result("t3", "OK"),
            result_record("All 3 tests pass.")], True)
        self.assertIn("Bash call 3", reason)

    def test_an_edit_after_the_last_run_fails(self):
        reason = self.assert_verdict([
            tool_use("t1", "Bash", command=TEST_RUN), tool_result("t1", "FAILED", True),
            tool_use("t2", "Edit", **EDIT), tool_result("t2", "ok"),
            tool_use("t3", "Bash", command=TEST_RUN), tool_result("t3", "OK"),
            tool_use("t4", "Write", file_path="app/pricing.py", content="x"),
            tool_result("t4", "ok")], False)
        self.assertIn("Write call 4", reason)

    def test_each_tool_edit_after_the_last_run_fails(self):
        for name, args in self.WRITES:
            with self.subTest(tool=name):
                reason = self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN),
                                              tool_use("t2", name, **args)], False)
                self.assertIn(f"{name} call 2", reason)

    def test_a_bash_write_is_not_an_edit(self):
        # Pins the documented limit: an edit made through a shell command is out of scope.
        self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN),
                             tool_use("t2", "Bash", command="sed -i 's/a/b/' pricing.py")],
                            True)

    def test_an_edit_of_another_file_passes(self):
        self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN),
                             tool_use("t2", "Edit", file_path="app/test_pricing.py",
                                      old_string="a", new_string="b")], True)

    def test_a_failed_edit_is_no_edit(self):
        self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN),
                             tool_use("t2", "Edit", **EDIT),
                             tool_result("t2", "String to replace not found", True)], True)

    def test_a_runner_invocation_counts_as_a_run(self):
        for command in self.RUNS:
            with self.subTest(command=command):
                self.assert_verdict([tool_use("t1", "Edit", **EDIT),
                                     tool_use("t2", "Bash", command=command)], True)

    def test_a_command_that_only_names_a_runner_is_no_run(self):
        for command in self.NOT_RUNS:
            with self.subTest(command=command):
                reason = self.assert_verdict([tool_use("t1", "Bash", command=command)], False)
                self.assertIn("no test run", reason)

    def test_no_test_run_fails(self):
        reason = self.assert_verdict([tool_use("t1", "Edit", **EDIT),
                                      tool_use("t2", "Bash", command='python3 -c "import pricing"')],
                                     False)
        self.assertIn("no test run", reason)

    def test_only_the_fixture_command_counts(self):
        # Pins the rule: only the fixture's one test command, `python3 -m unittest`, counts.
        for command in ("pytest -q", "python3 test_pricing.py"):
            with self.subTest(command=command):
                self.assertIn("no test run", self.assert_verdict(
                    [tool_use("t1", "Bash", command=command)], False))

    def test_a_run_and_no_edit_passes(self):
        reason = self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN)], True)
        self.assertIn("not edited", reason)

    def test_a_subagent_edit_counts(self):
        edit = tool_use("t2", "Edit", **EDIT)
        edit["parent_tool_use_id"] = "agent-1"
        self.assert_verdict([tool_use("t1", "Bash", command=TEST_RUN), edit], False)


def words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


class TestCase70NoSentenceOver40Words(ScriptGrader, unittest.TestCase):
    """The script grader of case 70 replaces claim 1 of the LLM judge ``readable``."""

    SCRIPT = EVALS / "70-review-fact-retention" / "script-graders" / "no-sentence-over-40-words.py"

    def answer(self, text: str, passed: bool) -> str:
        return self.assert_verdict([assistant_text("working"), result_record(text)], passed)

    def test_short_sentences_pass(self):
        reason = self.answer("Not ready. `db.py:18` builds SQL with an f-string. Fix it.", True)
        self.assertIn("6 words", reason)

    def test_40_words_pass_and_41_fail(self):
        self.answer(f"Short one. {words(40)}. Short two.", True)
        reason = self.answer(f"Short one. {words(41)}. Short two.", False)
        self.assertIn("41 words", reason)

    def test_a_fenced_block_is_not_prose(self):
        self.answer(f"Run this:\n\n```\n{words(60)}\n```\n\nThen stop.", True)
        self.answer(f"Run this:\n\n~~~ sh\n{words(60)}\n", True)

    def test_an_inline_span_is_one_word(self):
        self.answer(f"{words(39)} `{words(20)}`.", True)
        self.answer(f"{words(40)} `a. b. c`.", False)

    def test_list_items_headings_and_table_cells_are_blocks(self):
        self.answer(f"## {words(30)}\n{words(30)}", True)
        self.answer(f"- {words(30)}\n- {words(30)}\n1. {words(30)}\n2) {words(30)}", True)
        self.answer(f"| {words(30)} | {words(30)} |\n|---|---|", True)

    def test_paragraph_lines_join(self):
        self.answer(f"{words(25)}\n{words(25)}.", False)
        self.answer(f"- {words(25)}\n  {words(25)}.", False)

    def test_a_sentence_ends_before_closing_marks(self):
        for close in ("**", ")", "\"", "'", "*", "_", "]", "\u2019", "\u201d", "`"):
            with self.subTest(close=close):
                self.answer(f"{words(20)}.{close} {words(25)}.", True)

    def test_a_bold_verdict_line_ends_its_sentence(self):
        self.answer(f"**Verdict: not ready.**\n{words(25)}.", True)
        self.answer(f"**Verdict: not ready.** {words(38)}.", True)
        self.answer(f"{words(10)} (see the worklog.) {words(38)}.", True)
        self.answer(f"{words(10)} \"done.\" {words(38)}.", True)

    def test_marks_are_no_words(self):
        self.answer(f"{words(38)} — → | {words(2)}.", True)

    def test_the_last_assistant_text_without_a_result_record(self):
        self.assert_verdict([assistant_text(words(50) + "."), assistant_text("Not ready.")], True)
        self.assert_verdict([assistant_text("Not ready."), assistant_text(words(50) + ".")], False)

    def test_a_subagent_text_is_not_the_answer(self):
        self.assert_verdict([assistant_text("Not ready."),
                             assistant_text(words(50) + ".", parent="agent-1")], True)

    def test_no_answer_fails(self):
        reason = self.assert_verdict([tool_use("t1", "Bash", command="ls")], False)
        self.assertIn("no final answer", reason)


if __name__ == "__main__":
    unittest.main()
