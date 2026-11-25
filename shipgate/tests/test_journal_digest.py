#!/usr/bin/env python3
"""Tests of ``scripts/journal.py digest``: the markdown table the user reads before the
publish question (#25, ADR 0030 and its amendments).

The parser rules of the "What changed" section run in process through
``load_journal_module``; the command runs as a subprocess, as the other journal tests do.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

from test_journal import (
    INFRA, JOURNAL, JournalTestCase, load_journal_module, OK, insert_legacy_row,
    run_journal, SESSION_ENV,
)

J = load_journal_module()

S = "feature/demo"
PRD = "docs/prd/demo.md"
WORKLOG = "docs/prd/demo.worklog.md"

# A PRD in the line form of #24. Lines 5 to 10 are the items.
PRD_TEXT = """\
# PRD: demo

## Assumptions (executive)

- [technical] [source: a.py] Kept one? → yes [kept by the user]
- [domain] [no source found in the docs] Risky one? → answer one — a reason
- [technical] [source: b.py] Plain one? → answer two
- [behaviour] [source: c.py] Changed one? → new [changed by the user, was: old]
- [data] [no source found in the schema] Second risky? → answer three [unconfirmed]
- [technical] [blindspot] [source: d.py] Blind one? → answer four

## Next section
"""

# The same section as a PRD wrote it before #24: the parser refuses it at line 5.
OLD_PRD_TEXT = """\
# PRD: demo

## Assumptions (executive)

- Which ranking feeds it? → the newest one — the reviewers read it
"""


def worklog_text(section: str) -> str:
    """A worklog with a Build Plan, and ``section`` placed before its last heading."""
    return (
        "# Worklog: demo\n"
        "\n"
        "## Build Plan\n"
        "\n"
        "- [ ] T001 — build it\n"
        "\n"
        + section
        + "## Deviations & notes\n"
    )


WHAT_CHANGED = "## What changed\n\n- The digest prints.\n- It fits.\n\n"


class DigestCase(JournalTestCase):
    """A temp project with a sidecar, the PRD and the worklog on disk."""

    def setUp(self):
        super().setUp()
        self.init_db()
        claude = self.root / ".claude"
        claude.mkdir()
        (claude / "shipgate.json").write_text(json.dumps({
            "version": 1, "db": str(self.db),
            "artifact_homes": {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md",
                               "worklog": "docs/prd/*.worklog.md"},
        }), encoding="utf-8")
        self.write(PRD, PRD_TEXT)
        self.write(WORKLOG, worklog_text(WHAT_CHANGED))

    def batch(self, rows, stream=S):
        """Append ``rows`` ((type, data) pairs) in one ``append --batch``."""
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        lines = "".join(json.dumps({"type": t, "data": d}) + "\n" for t, d in rows)
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "append",
             "--stream", stream, "--batch"],
            cwd=str(self.root), env=env, input=lines, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, OK, msg=proc.stdout + proc.stderr)

    def legacy(self, etype, data, stream=S):
        return insert_legacy_row(self.db, stream, etype, data, "orchestrator")

    def designed(self, stream=S):
        self.batch([
            ("flow-started", {"request": "#1234 build the demo"}),
            ("clarify-passed", {"prd": PRD}),
            ("design-committed", {"worklog": WORKLOG}),
        ], stream=stream)

    def run_digest(self, *flags, stream=S, rc=OK):
        proc = run_journal(["digest", "--stream", stream, *flags], cwd=self.root)
        self.assertEqual(proc.returncode, rc, msg=proc.stdout + proc.stderr)
        return proc

    def digest(self, *flags, stream=S):
        return self.run_digest(*flags, stream=stream).stdout

    def doc(self, stream=S):
        return json.loads(self.digest("--json", stream=stream))

    def lines(self, *flags, stream=S):
        return self.digest(*flags, stream=stream).splitlines()

    def table(self, *flags, stream=S):
        """(the header cells, the body rows) of the digest's one markdown table."""
        lines = self.lines(*flags, stream=stream)
        self.assertEqual(lines[1], "|---|---|", "\n".join(lines))
        return split_row(lines[0]), [split_row(line) for line in lines[2:]]

    def part(self, name, *flags, stream=S):
        """The first cell of the part's first row, and the value cells of its rows."""
        _, rows = self.table(*flags, stream=stream)
        for index, (first, value) in enumerate(rows):
            if first.startswith(f"**{name}**"):
                values = [value]
                for later_first, later in rows[index + 1:]:
                    if later_first:
                        break
                    values.append(later)
                return first, values
        self.fail(f"no row of part {name!r} in {rows}")


# Every character the digest escapes in a cell, and the forms a cell may take.
SPECIAL = "\\`*_[]<>|~&$"
FIRST_CELL = re.compile(
    r"^(|\*\*(What changed|Decided alone|Deviations|Look first)\*\*( \(\d+\))?)$")
CODE_CELL = re.compile(r"^`[^`|\\]+`( · `[^`|\\]+`)*$")


def split_row(line):
    """The two cells of one table row: split at the pipes no backslash escapes."""
    assert line.startswith("| ") and line.endswith(" |"), line
    cells = re.split(r"(?<!\\)\|", line)[1:-1]
    assert len(cells) == 2, (line, cells)
    return [cell.strip() for cell in cells]


def unescape(cell):
    return re.sub(r"\\(.)", r"\1", cell)


def assert_inert(case, cell):
    """``cell`` is inline code with no backtick, pipe or backslash inside, or text in
    which every markdown character carries its backslash."""
    if CODE_CELL.match(cell):
        return
    bare = re.sub(r"\\.", "", cell)
    for char in SPECIAL:
        case.assertNotIn(char, bare, cell)


# --------------------------------------------------------------------------
# The command's envelope
# --------------------------------------------------------------------------


class TestDigestCommand(DigestCase):

    def test_a_stream_with_no_events_exits_1(self):
        proc = self.run_digest(stream="feature/nope", rc=INFRA)
        self.assertIn("feature/nope", proc.stderr)

    def test_help_names_the_command_its_parts_and_exit_codes(self):
        top = run_journal(["--help"]).stdout
        self.assertRegex(top, r"(?m)^    digest\b")
        own = run_journal(["digest", "--help"]).stdout
        flat = " ".join(own.split())
        for words in ("markdown table", "what changed", "decided alone", "deviations",
                      "look first", "--all", "--json", "exits 1"):
            with self.subTest(words=words):
                self.assertIn(words, flat)

    def test_json_keys(self):
        self.designed()
        doc = self.doc()
        self.assertEqual(sorted(doc), [
            "decided", "deviations", "look_here", "prd", "publish", "stream", "verdict",
            "what_changed", "worklog",
        ])
        self.assertEqual(doc["stream"], S)
        self.assertEqual(doc["worklog"], WORKLOG)
        self.assertEqual(doc["prd"], PRD)
        self.assertEqual(sorted(doc["what_changed"]), ["error", "items"])
        self.assertEqual(sorted(doc["decided"]), ["error", "items"])
        self.assertEqual(sorted(doc["deviations"]), ["items"])
        self.assertEqual(sorted(doc["look_here"]), ["files", "from", "unavailable"])
        self.assertEqual(sorted(doc["decided"]["items"][0]),
                         ["line", "risky", "seq", "source", "text"])

    def test_the_row_cap_is_computed_from_the_slots(self):
        self.assertEqual(J.PARTS, (("what_changed", "What changed", 3),
                                   ("decided", "Decided alone", 2),
                                   ("deviations", "Deviations", 2)))
        # The header row, the separator, the slots, the Look first row.
        self.assertEqual(J.max_lines(), 10)
        self.assertEqual(J.MARKDOWN_SPECIAL, SPECIAL)

    def test_the_digest_writes_nothing(self):
        self.designed()
        before = len(self.events(S))
        mtime = (self.root / WORKLOG).stat().st_mtime_ns
        self.digest()
        self.assertEqual(len(self.events(S)), before)
        self.assertEqual((self.root / WORKLOG).stat().st_mtime_ns, mtime)


# --------------------------------------------------------------------------
# FR-002: the header row
# --------------------------------------------------------------------------


class TestHeader(DigestCase):

    def test_no_verdict_and_publish_held(self):
        self.designed()
        header, _ = self.table()
        self.assertEqual(header, [f"`{S}`", "verdict — · publish held"])

    def test_a_ready_verdict_is_no_publish_go(self):
        """The digest is shown at the publish question, after a ready verdict: the state
        it names is the user's publish go, which the ready verdict does not give."""
        self.designed()
        self.batch([("review-verdict", {"verdict": "not-ready"}),
                    ("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
                    ("review-verdict", {"verdict": "ready"})])
        header, _ = self.table()
        self.assertEqual(header[1], "verdict ready (round 2) · publish held")
        doc = self.doc()
        self.assertEqual(doc["verdict"], {"verdict": "ready", "round": 2})
        self.assertEqual(doc["publish"], "held")

    def test_the_users_publish_go_authorizes(self):
        self.designed()
        insert_legacy_row(self.db, S, "gate-decision", {
            "gate": "publish", "question": "Open the PR?", "decision": "publish",
            "mode": "ask", "raised_by": "user", "source": "shell"}, "user")
        self.assertEqual(self.table()[0][1], "verdict — · publish authorized")
        self.assertEqual(self.doc()["publish"], "authorized")
        # A go lasts until the stream's next task-done.
        self.batch([("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
                    ("task-done", {"task_id": "T001"})])
        self.assertEqual(self.table()[0][1], "verdict — · publish held")
        self.assertEqual(self.doc()["publish"], "held")

    def test_a_not_ready_verdict_holds_publish(self):
        self.designed()
        self.batch([("review-verdict", {"verdict": "not-ready"})])
        self.assertEqual(self.table()[0][1], "verdict not-ready (round 1) · publish held")


# --------------------------------------------------------------------------
# FR-003: What changed
# --------------------------------------------------------------------------


class TestWhatChangedParser(unittest.TestCase):
    """``parse_what_changed``: one exact form, a refusal at its line for the rest."""

    def parse(self, text):
        return J.parse_what_changed(text)

    def refused(self, text, line, reason):
        with self.assertRaises(J.SectionError) as caught:
            self.parse(text)
        self.assertEqual((caught.exception.line, caught.exception.reason), (line, reason))

    def test_one_item(self):
        self.assertEqual(self.parse("## What changed\n\n- one\n"), ["one"])

    def test_five_items_with_both_bullets_and_a_continuation(self):
        text = "## What changed\n- a\n* b\n- c\n  more of c\n- d\n- e\n\n## Next\n"
        self.assertEqual(self.parse(text), ["a", "b", "c more of c", "d", "e"])

    def test_no_section_is_none(self):
        self.assertIsNone(self.parse("# Worklog\n\n## Other\n- a\n"))

    def test_a_sixth_item_is_refused_at_its_line(self):
        text = "## What changed\n" + "".join(f"- item {n}\n" for n in range(1, 7))
        self.refused(text, 7, "more than 5 items")

    def test_an_empty_section_is_refused_at_the_heading(self):
        self.refused("# W\n\n## What changed\n\n## Next\n", 3, "no item in the section")

    def test_an_empty_item_is_refused_at_its_line(self):
        self.refused("## What changed\n- a\n- \n", 3, "empty item")

    def test_an_empty_bullet_line_with_a_continuation_is_refused(self):
        self.refused("## What changed\n- a\n-\x20\n  real text\n", 3, "empty item")

    def test_a_prose_line_is_refused(self):
        self.refused("## What changed\n\nSome prose.\n- a\n", 3,
                     "only one-line list items belong in this section")

    def test_a_code_fence_is_refused(self):
        self.refused("## What changed\n- a\n```\n- b\n```\n", 3,
                     "code block in the what changed section")

    def test_a_second_heading_is_refused(self):
        self.refused("## What changed\n- a\n\n## Other\n\n## What changed\n- b\n", 6,
                     'a second "## What changed" heading')

    def test_an_indented_item_is_refused(self):
        self.refused("## What changed\n- a\n  - [b]\n", 3, "indented list item")

    def test_a_level_one_heading_inside_is_refused(self):
        self.refused("## What changed\n- a\n\n---\n\n# Build Plan\n", 4,
                     "only one-line list items belong in this section")


class TestWhatChanged(DigestCase):

    def test_the_items_are_the_first_rows(self):
        self.designed()
        _, rows = self.table()
        self.assertEqual(rows[:2], [["**What changed**", "The digest prints."],
                                    ["", "It fits."]])
        self.assertEqual(self.doc()["what_changed"],
                         {"items": ["The digest prints.", "It fits."], "error": None})

    def test_five_items_show_three_and_the_count(self):
        self.write(WORKLOG, worklog_text(
            "## What changed\n" + "".join(f"- item {n}\n" for n in range(1, 6)) + "\n"))
        self.designed()
        self.assertEqual(self.part("What changed"),
                         ("**What changed** (5)", ["item 1", "item 2", "item 3"]))
        self.assertEqual(self.part("What changed", "--all"),
                         ("**What changed**", [f"item {n}" for n in range(1, 6)]))

    def assert_error(self, error, designed=True):
        if designed:
            self.designed()
        first, values = self.part("What changed")
        self.assertEqual(first, "**What changed**")
        self.assertEqual([unescape(v) for v in values], [error])
        self.assertEqual(self.doc()["what_changed"], {"items": [], "error": error})

    def test_a_sixth_item(self):
        self.write(WORKLOG, worklog_text(
            "## What changed\n" + "".join(f"- item {n}\n" for n in range(1, 7)) + "\n"))
        # The section starts at line 7; the sixth item is on line 13.
        self.assert_error(f"{WORKLOG}:13: more than 5 items")

    def test_an_empty_section(self):
        self.write(WORKLOG, worklog_text("## What changed\n\n"))
        self.assert_error(f"{WORKLOG}:7: no item in the section")

    def test_a_prose_line(self):
        self.write(WORKLOG, worklog_text("## What changed\n\nWe built it.\n\n"))
        self.assert_error(f"{WORKLOG}:9: only one-line list items belong in this section")

    def test_a_code_fence(self):
        self.write(WORKLOG, worklog_text("## What changed\n```\n- a\n```\n"))
        self.assert_error(f"{WORKLOG}:8: code block in the what changed section")

    def test_a_second_heading(self):
        self.write(WORKLOG, worklog_text(
            "## What changed\n- a\n\n## What changed\n- b\n\n"))
        self.assert_error(f'{WORKLOG}:10: a second "## What changed" heading')

    def test_no_section(self):
        self.write(WORKLOG, worklog_text(""))
        self.assert_error(f'no "## What changed" section in {WORKLOG}')

    def test_no_worklog(self):
        (self.root / WORKLOG).unlink()
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD})])
        self.assert_error("no worklog recorded for this stream", designed=False)

    def test_an_unreadable_worklog(self):
        (self.root / WORKLOG).unlink()
        (self.root / WORKLOG).mkdir()
        self.assert_error(f"{WORKLOG}: cannot be read")


# --------------------------------------------------------------------------
# FR-004: decided alone
# --------------------------------------------------------------------------


class TestDecidedAlone(DigestCase):

    def decision(self, question, **extra):
        data = {"gate": "design", "question": question, "decision": "yes",
                "mode": "executive"}
        data.update(extra)
        return ("gate-decision", data)

    def test_the_prd_items_risky_first_then_the_journal_then_the_rest(self):
        self.batch([
            ("flow-started", {"request": "#1234"}),
            self.decision("before clarify?"),
            ("clarify-passed", {"prd": PRD}),
            self.decision("after clarify?"),
            self.decision("asked?", mode="ask"),
            self.decision("raised by the user?", raised_by="user"),
            ("design-committed", {"worklog": WORKLOG}),
        ])
        items = self.doc()["decided"]["items"]
        self.assertEqual([i["text"] for i in items], [
            "[domain] Risky one? → answer one",
            "[data] Second risky? → answer three",
            "[technical] Blind one? → answer four",
            "[design] after clarify? -> yes (executive)",
            "[technical] Plain one? → answer two",
        ])
        self.assertEqual([i["source"] for i in items],
                         ["prd", "prd", "prd", "journal", "prd"])
        self.assertEqual([i["risky"] for i in items], [True, True, True, False, False])
        self.assertEqual([i["line"] for i in items], [6, 9, 10, None, 7])
        self.assertIsNone(items[0]["seq"])
        self.assertIsInstance(items[3]["seq"], int)
        self.assertIsNone(self.doc()["decided"]["error"])

    def test_over_the_slot_the_first_cell_names_the_full_count(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"), self.decision("two?"),
                    ("design-committed", {"worklog": WORKLOG})])
        first, values = self.part("Decided alone")
        self.assertEqual(first, "**Decided alone** (6)")
        self.assertEqual(values, ["\\[domain\\] Risky one? → answer one",
                                  "\\[data\\] Second risky? → answer three"])
        first, values = self.part("Decided alone", "--all")
        self.assertEqual(first, "**Decided alone**")
        self.assertEqual(len(values), 6)

    def test_within_the_slot_the_first_cell_has_no_count(self):
        self.write(PRD, "# PRD\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"),
                    ("design-committed", {"worklog": WORKLOG})])
        first, values = self.part("Decided alone")
        self.assertEqual(first, "**Decided alone**")
        self.assertEqual([unescape(v) for v in values], ["[design] one? -> yes (executive)"])

    def test_the_window_starts_after_the_last_clarify_passed(self):
        self.write(PRD, "# PRD\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("between?"),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("after?")])
        texts = [i["text"] for i in self.doc()["decided"]["items"]]
        self.assertEqual(texts, ["[design] after? -> yes (executive)"])

    def test_no_clarify_passed_gives_every_executive_decision_and_no_prd_half(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    self.decision("one?"), self.decision("two?", mode="ask"),
                    ("design-committed", {"worklog": WORKLOG})])
        decided = self.doc()["decided"]
        self.assertEqual([i["text"] for i in decided["items"]],
                         ["[design] one? -> yes (executive)"])
        self.assertIsNone(decided["error"])

    def test_none(self):
        self.write(PRD, "# PRD\n")
        self.designed()
        self.assertEqual(self.part("Decided alone"), ("**Decided alone**", ["none"]))

    def test_a_prd_in_the_form_before_24_gives_one_error_row_and_exit_0(self):
        self.write(PRD, OLD_PRD_TEXT)
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"),
                    ("design-committed", {"worklog": WORKLOG})])
        error = f"{PRD}:5: no class tag — the PRD's assumptions were not read"
        self.assertEqual(self.doc()["decided"]["error"], error)
        first, values = self.part("Decided alone")
        self.assertEqual(first, "**Decided alone**")
        self.assertEqual([unescape(v) for v in values],
                         [error, "[design] one? -> yes (executive)"])

    def test_a_clarify_passed_with_no_usable_prd_ref_says_so(self):
        self.batch([("flow-started", {"request": "#1234"})])
        self.legacy("clarify-passed", {"prd": "/abs/docs/prd/demo.md"})
        doc = self.doc()
        self.assertIsNone(doc["prd"])
        self.assertEqual(doc["decided"]["error"],
                         "the last clarify-passed names no usable PRD ref — the PRD's "
                         "assumptions were not read")
        self.assertNotIn("/abs/", self.digest())

    def test_an_unreadable_prd(self):
        self.designed()
        (self.root / PRD).unlink()
        self.assertEqual(self.doc()["decided"]["error"], f"{PRD}: cannot be read")

    def test_the_error_takes_a_slot(self):
        self.write(PRD, OLD_PRD_TEXT)
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD})]
                   + [self.decision(f"q{n}?") for n in range(4)])
        first, values = self.part("Decided alone")
        self.assertEqual(first, "**Decided alone** (4)")
        self.assertEqual(len(values), 2)
        self.assertTrue(unescape(values[0]).startswith(f"{PRD}:5: "))
        self.assertEqual(unescape(values[1]), "[design] q0? -> yes (executive)")


# --------------------------------------------------------------------------
# FR-005: deviations
# --------------------------------------------------------------------------


class TestDeviations(DigestCase):

    def test_the_window_the_bookkeeping_rows_and_the_aliases(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("deviation", {"note": "before the design"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": WORKLOG}),
                    ("deviation", {"note": "after the design"}),
                    ("deviation", {"note": "no signals", "kind": "signals-missing"}),
                    ("deviation", {"note": "no style", "kind": "style-missing"}),
                    ("deviation", {"note": "waived", "kind": "gate-waived",
                                   "task_ids": ["T001"]}),
                    ("deviation", {"note": "the lead moved", "report_to": "t9"}),
                    ("deviation", {"note": "a kind of its own", "kind": "scope"})])
        self.legacy("deviation", {"what": "an old row"})
        self.legacy("deviation", {"correction": 5, "what": "the string wins"})
        self.legacy("deviation", {"kind": "plain"})
        self.legacy("deviation", {"note": "  ", "what": "a blank note falls through"})
        items = self.doc()["deviations"]["items"]
        self.assertEqual([i["text"] for i in items], [
            "after the design", "a kind of its own", "an old row", "the string wins",
            "(no note)", "a blank note falls through",
        ])
        self.assertTrue(all(isinstance(i["seq"], int) for i in items))
        self.assertEqual([i["seq"] for i in items], sorted(i["seq"] for i in items))
        self.assertEqual(self.part("Deviations"),
                         ("**Deviations** (6)", ["after the design", "a kind of its own"]))
        first, values = self.part("Deviations", "--all")
        self.assertEqual(first, "**Deviations**")
        self.assertEqual(len(values), 6)

    def test_no_design_committed_counts_every_deviation(self):
        (self.root / WORKLOG).unlink()
        self.batch([("flow-started", {"request": "#1234"}),
                    ("deviation", {"note": "one"})])
        self.assertEqual(self.part("Deviations"), ("**Deviations**", ["one"]))

    def test_none(self):
        self.designed()
        self.assertEqual(self.part("Deviations"), ("**Deviations**", ["none"]))


# --------------------------------------------------------------------------
# FR-006: look first
# --------------------------------------------------------------------------


def ranking(*paths):
    return {"source": "graph", "files": [{"path": p, "fix": "top"} for p in paths]}


class TestLookFirst(DigestCase):

    def test_the_verdict_ranking_wins(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("d.py")}),
                    ("review-verdict", {"verdict": "not-ready",
                                        "ranking": ranking("a.py", "b.py", "c.py",
                                                           "e.py")})])
        self.assertEqual(self.lines()[-1], "| **Look first** | `a.py` · `b.py` · `c.py` |")
        self.assertEqual(self.doc()["look_here"],
                         {"files": ["a.py", "b.py", "c.py"], "from": "review-verdict",
                          "unavailable": None})

    def test_the_design_ranking_is_the_fallback(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("d.py")}),
                    ("review-verdict", {"verdict": "not-ready"})])
        self.assertEqual(self.part("Look first"), ("**Look first**", ["`d.py`"]))
        self.assertEqual(self.doc()["look_here"]["from"], "design-committed")

    def test_source_none(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("design-committed", {"worklog": WORKLOG, "ranking": {
                        "source": "none", "unavailable": "not a git repository"}})])
        self.assertEqual(self.part("Look first"),
                         ("**Look first**",
                          ["— risk signals unavailable (not a git repository)"]))
        self.assertEqual(self.doc()["look_here"],
                         {"files": [], "from": "design-committed",
                          "unavailable": "not a git repository"})

    def test_no_ranking(self):
        self.designed()
        self.assertEqual(self.part("Look first"),
                         ("**Look first**", ["— no risk ranking recorded"]))
        self.assertEqual(self.doc()["look_here"],
                         {"files": [], "from": None, "unavailable": None})

    def test_an_unsafe_path_is_dropped(self):
        self.designed()
        self.legacy("review-verdict", {"verdict": "not-ready", "ranking": {
            "source": "graph", "files": [
                {"path": "/etc/passwd"}, {"path": "../up.py"}, {"path": "a/../b.py"},
                {"path": "C:/x.py"}, {"path": 7}, "bare", {"path": " /home/alice/x.py"},
                {"path": "\t/etc/hosts"}, {"path": "a.py · /home/alice/s.py"},
                {"path": "bad" + chr(27) + ".py"}, {"path": "ok.py"}]}})
        self.assertEqual(self.part("Look first"), ("**Look first**", ["`ok.py`"]))

    UNUSABLE = ("the worklog ref is not usable (whitespace or a control character) — its "
                "sections were not read")

    def test_a_worklog_ref_with_whitespace_is_not_read_and_says_so(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD})])
        (self.root / WORKLOG).unlink()
        self.legacy("design-committed", {"worklog": " /etc/demo.worklog.md"})
        doc = self.doc()
        self.assertIsNone(doc["worklog"])
        self.assertEqual(doc["what_changed"]["error"], self.UNUSABLE)
        self.assertNotIn("/etc/", self.digest())

    def test_a_real_worklog_with_a_space_in_its_path_is_not_read_and_says_so(self):
        spaced = "docs/my notes/demo.worklog.md"
        self.write(spaced, worklog_text(WHAT_CHANGED))
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": spaced})])
        doc = self.doc()
        self.assertIsNone(doc["worklog"])
        self.assertEqual(doc["what_changed"], {"items": [], "error": self.UNUSABLE})
        first, values = self.part("What changed")
        self.assertEqual([unescape(v) for v in values], [self.UNUSABLE])
        self.assertNotIn("my notes", self.digest())

    def test_a_ranking_that_is_no_object(self):
        self.designed()
        self.legacy("review-verdict", {"verdict": "not-ready", "ranking": ["a.py"]})
        self.assertEqual(self.part("Look first"),
                         ("**Look first**", ["— no risk ranking recorded"]))


# --------------------------------------------------------------------------
# FR-007, SC-001: the slots and the row cap
# --------------------------------------------------------------------------


class TestSlots(DigestCase):

    def test_a_full_stream_prints_10_lines(self):
        self.write(WORKLOG, worklog_text(
            "## What changed\n" + "".join(f"- item {n}\n" for n in range(1, 6)) + "\n"))
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD})]
                   + [("gate-decision", {"gate": "design", "question": f"q{n}?",
                                         "decision": "yes", "mode": "executive"})
                      for n in range(6)]
                   + [("design-committed", {"worklog": WORKLOG,
                                            "ranking": ranking("a.py", "b.py", "c.py")})]
                   + [("deviation", {"note": f"note {n}"}) for n in range(7)])
        lines = self.lines()
        self.assertEqual(len(lines), 10, "\n".join(lines))
        self.assertEqual(len(lines), J.max_lines())
        firsts = [row[0] for row in self.table()[1] if row[0]]
        self.assertEqual(firsts, ["**What changed** (5)", "**Decided alone** (10)",
                                  "**Deviations** (7)", "**Look first**"])
        self.assertEqual(len(self.lines("--all")), 2 + 5 + 10 + 7 + 1)

    def test_the_layout_of_a_short_stream(self):
        self.write(PRD, "# PRD\n")
        self.designed()
        self.assertEqual(self.lines(), [
            f"| `{S}` | verdict — · publish held |",
            "|---|---|",
            "| **What changed** | The digest prints. |",
            "|  | It fits. |",
            "| **Decided alone** | none |",
            "| **Deviations** | none |",
            "| **Look first** | — no risk ranking recorded |",
        ])


# --------------------------------------------------------------------------
# FR-008, SC-007: untrusted text in a terminal and in markdown
# --------------------------------------------------------------------------


# One value that tries every markdown form a cell must not take: a new column, a new row,
# code, a link, an image, an autolink, HTML, a line break, emphasis, strikethrough, an
# entity, math, and a backslash that would escape the cell's closing pipe.
HOSTILE = ("a | b `code` [link](https://x.example) ![img](y.png) <https://z.example> "
           "<br> <b>x</b> *em* _em_ **strong** ~~del~~ &#124; $x$ end\\")


class TestHostilePayloads(DigestCase):

    def assert_safe(self, out, rows):
        lines = out.splitlines()
        self.assertEqual(len(lines), rows, out)
        for line in lines:
            with self.subTest(line=line):
                self.assertLessEqual(len(line), 160)
                self.assertTrue(line.isprintable(), repr(line))
                if line == "|---|---|":
                    continue
                first, value = split_row(line)
                if line is lines[0]:
                    assert_inert(self, first)
                else:
                    self.assertRegex(first, FIRST_CELL)
                assert_inert(self, value)

    def test_markdown_in_every_part_is_escaped(self):
        self.write(WORKLOG, worklog_text(f"## What changed\n- {HOSTILE}\n\n"))
        self.write(PRD, "# PRD\n\n## Assumptions (executive)\n\n"
                        "- [domain] [no source found in x] Q | `x` <br>? → [a](b) *c*\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("gate-decision", {"gate": "design", "question": HOSTILE + "\nrow",
                                       "decision": "_y_", "mode": "executive"}),
                    ("design-committed", {"worklog": WORKLOG, "ranking": {
                        "source": "graph", "files": [{"path": "a|b`c*.py"},
                                                     {"path": "ok.py"}]}}),
                    ("deviation", {"note": HOSTILE})])
        for flags in ((), ("--all",)):
            with self.subTest(flags=flags):
                out = self.digest(*flags)
                self.assert_safe(out, 2 + 1 + 2 + 1 + 1)
        _, values = self.part("What changed")
        shown = unescape(values[0]).rstrip("…")
        self.assertGreater(len(shown), 50)
        self.assertTrue(HOSTILE.startswith(shown), shown)
        # One path that cannot be inline code makes the whole cell escaped text.
        self.assertEqual(self.part("Look first")[1], ["a\\|b\\`c\\*.py · ok.py"])

    def test_a_long_value_is_clipped_between_escapes(self):
        self.write(WORKLOG, worklog_text("## What changed\n- " + "|" * 300 + "\n\n"))
        self.designed()
        out = self.digest()
        self.assert_safe(out, 7)
        _, values = self.part("What changed")
        self.assertTrue(values[0].endswith("\\|…"), values[0])

    def test_terminal_sequences_and_line_breaks_stay_out(self):
        esc = chr(27)
        planted = f"line one\nfake row |\r\n| **Look first** | `x` | {esc}[2K{esc}[1A"
        self.write(WORKLOG, worklog_text(
            f"## What changed\n- {'x' * 1000}\n- red {esc}[31m{chr(0x202E)} end\n\n"))
        self.write(PRD, "# PRD\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("gate-decision", {"gate": "design", "question": planted,
                                       "decision": "y" * 600, "mode": "executive"}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("a" * 300 + ".py")})])
        self.legacy("deviation", {"note": planted + "x" * 1000})
        for flags in ((), ("--all",)):
            with self.subTest(flags=flags):
                out = self.digest(*flags)
                self.assert_safe(out, 2 + 2 + 1 + 1 + 1)
                self.assertNotIn(esc, out)
                self.assertEqual(sum(l.startswith("| **Look first**")
                                     for l in out.splitlines()), 1)

    def test_a_hostile_stream_name_stays_in_the_header(self):
        for stream in ("feature/" + "s" * 300, "feature/a|b`c`_d_*e*"):
            with self.subTest(stream=stream):
                self.legacy("flow-started", {"request": "#1234"}, stream=stream)
                out = self.digest(stream=stream)
                self.assert_safe(out, 6)
        header = split_row(self.lines(stream="feature/a|b`c`_d_*e*")[0])
        self.assertEqual(unescape(header[0]), "feature/a|b`c`_d_*e*")


class TestMarkdownCell(unittest.TestCase):
    """The escape itself: a fixed set, each character with its backslash."""

    def test_each_special_character_gets_a_backslash(self):
        self.assertEqual(J._markdown_cell(SPECIAL, 100),
                         "".join("\\" + c for c in SPECIAL))
        self.assertEqual(J._markdown_cell("plain text, (parens) #1234 a.py", 100),
                         "plain text, (parens) #1234 a.py")

    def test_the_clip_never_splits_an_escape(self):
        self.assertEqual(J._markdown_cell("|" * 10, 6), "\\|\\|…")
        self.assertEqual(J._markdown_cell("ab|", 4), "ab\\|")
        self.assertEqual(J._markdown_cell("abc|", 4), "abc…")

    def test_inline_code_only_for_a_value_with_no_backtick_pipe_or_backslash(self):
        self.assertEqual(J._markdown_code("shipgate/README.md", 100), "`shipgate/README.md`")
        self.assertEqual(J._markdown_code("a`b", 100), "a\\`b")
        self.assertEqual(J._markdown_code("a|b", 100), "a\\|b")
        self.assertEqual(J._markdown_code("a\\b", 100), "a\\\\b")


if __name__ == "__main__":
    unittest.main()
