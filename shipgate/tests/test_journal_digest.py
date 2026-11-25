#!/usr/bin/env python3
"""Tests of ``scripts/journal.py digest``: the block the user reads at the publish
question (#25, ADR 0030).

The parser rules of the "What changed" section run in process through
``load_journal_module``; the command runs as a subprocess, as the other journal tests do.
"""

from __future__ import annotations

import json
import os
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

    def part(self, out, heading):
        """The heading line that starts with ``heading`` and the item lines under it."""
        lines = out.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(heading):
                items = []
                for item in lines[index + 1:]:
                    if not item.startswith("  - "):
                        break
                    items.append(item[4:])
                return line, items
        self.fail(f"no line starts with {heading!r} in:\n{out}")


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
        for words in ("what changed", "decided alone", "deviations", "look here first",
                      "--all", "--json", "exits 1"):
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

    def test_max_lines_is_16(self):
        self.assertEqual(J.max_lines(), 16)
        self.assertEqual(J.LIST_PARTS,
                         (("decided", "decided alone", 4), ("deviations", "deviations", 3)))

    def test_the_digest_writes_nothing(self):
        self.designed()
        before = len(self.events(S))
        mtime = (self.root / WORKLOG).stat().st_mtime_ns
        self.digest()
        self.assertEqual(len(self.events(S)), before)
        self.assertEqual((self.root / WORKLOG).stat().st_mtime_ns, mtime)


# --------------------------------------------------------------------------
# FR-002: the first line
# --------------------------------------------------------------------------


class TestFirstLine(DigestCase):

    def test_no_verdict_and_publish_held(self):
        self.designed()
        first = self.lines()[0]
        self.assertEqual(
            first, f"{S} — verdict — · publish held. What changed:")

    def test_a_ready_verdict_is_no_publish_go(self):
        """The digest is shown at the publish question, after a ready verdict: the state
        it names is the user's publish go, which the ready verdict does not give."""
        self.designed()
        self.batch([("review-verdict", {"verdict": "not-ready"}),
                    ("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
                    ("review-verdict", {"verdict": "ready"})])
        first = self.lines()[0]
        self.assertEqual(
            first, f"{S} — verdict ready (round 2) · publish held. What changed:")
        doc = self.doc()
        self.assertEqual(doc["verdict"], {"verdict": "ready", "round": 2})
        self.assertEqual(doc["publish"], "held")

    def test_the_users_publish_go_authorizes(self):
        self.designed()
        insert_legacy_row(self.db, S, "gate-decision", {
            "gate": "publish", "question": "Open the PR?", "decision": "publish",
            "mode": "ask", "raised_by": "user", "source": "shell"}, "user")
        self.assertIn("· publish authorized. What changed:", self.lines()[0])
        self.assertEqual(self.doc()["publish"], "authorized")
        # A go lasts until the stream's next task-done.
        self.batch([("verify-run", {"outcome": "pass", "task_ids": ["T001"]}),
                    ("task-done", {"task_id": "T001"})])
        self.assertIn("· publish held. What changed:", self.lines()[0])
        self.assertEqual(self.doc()["publish"], "held")

    def test_a_not_ready_verdict_holds_publish(self):
        self.designed()
        self.batch([("review-verdict", {"verdict": "not-ready"})])
        self.assertIn("verdict not-ready (round 1) · publish held.", self.lines()[0])


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

    def test_the_items_print_under_the_first_line(self):
        self.designed()
        lines = self.lines()
        self.assertEqual(lines[1:3], ["  - The digest prints.", "  - It fits."])
        self.assertEqual(self.doc()["what_changed"],
                         {"items": ["The digest prints.", "It fits."], "error": None})

    def test_five_items_print(self):
        self.write(WORKLOG, worklog_text(
            "## What changed\n" + "".join(f"- item {n}\n" for n in range(1, 6)) + "\n"))
        self.designed()
        self.assertEqual(self.lines()[1:6], [f"  - item {n}" for n in range(1, 6)])

    def assert_error(self, error, designed=True):
        if designed:
            self.designed()
        lines = self.lines()
        self.assertTrue(lines[0].endswith(f"What changed: — {error}"), lines[0])
        self.assertFalse(lines[1].startswith("  - "), lines[1])
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

    def test_the_heading_over_the_slot_names_the_count_and_the_flag(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"), self.decision("two?"),
                    ("design-committed", {"worklog": WORKLOG})])
        heading, items = self.part(self.digest(), "decided alone")
        self.assertEqual(heading, "decided alone (6, 4 shown; --all prints every one):")
        self.assertEqual(items, [
            "[domain] Risky one? → answer one",
            "[data] Second risky? → answer three",
            "[technical] Blind one? → answer four",
            "[design] one? -> yes (executive)",
        ])
        heading, items = self.part(self.digest("--all"), "decided alone")
        self.assertEqual(heading, "decided alone (6):")
        self.assertEqual(len(items), 6)

    def test_within_the_slot_the_heading_names_the_count(self):
        self.write(PRD, "# PRD\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"),
                    ("design-committed", {"worklog": WORKLOG})])
        heading, items = self.part(self.digest(), "decided alone")
        self.assertEqual(heading, "decided alone (1):")
        self.assertEqual(items, ["[design] one? -> yes (executive)"])

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
        self.assertIn("decided alone: none", self.lines())

    def test_a_prd_in_the_form_before_24_gives_one_error_line_and_exit_0(self):
        self.write(PRD, OLD_PRD_TEXT)
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    self.decision("one?"),
                    ("design-committed", {"worklog": WORKLOG})])
        error = f"{PRD}:5: no class tag — the PRD's assumptions were not read"
        self.assertEqual(self.doc()["decided"]["error"], error)
        heading, items = self.part(self.digest(), "decided alone")
        self.assertEqual(heading, "decided alone (1):")
        self.assertEqual(items, [error, "[design] one? -> yes (executive)"])

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
        heading, items = self.part(self.digest(), "decided alone")
        self.assertEqual(heading, "decided alone (4, 3 shown; --all prints every one):")
        self.assertEqual(len(items), 4)
        self.assertTrue(items[0].startswith(f"{PRD}:5: "))


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
        heading, shown = self.part(self.digest(), "deviations")
        self.assertEqual(
            heading,
            f"deviations (6, 3 shown; --all prints every one; notes in {WORKLOG}):")
        self.assertEqual(shown, ["after the design", "a kind of its own", "an old row"])
        heading, shown = self.part(self.digest("--all"), "deviations")
        self.assertEqual(heading, f"deviations (6; notes in {WORKLOG}):")
        self.assertEqual(len(shown), 6)

    def test_no_design_committed_counts_every_deviation(self):
        (self.root / WORKLOG).unlink()
        self.batch([("flow-started", {"request": "#1234"}),
                    ("deviation", {"note": "one"})])
        heading, shown = self.part(self.digest(), "deviations")
        self.assertEqual(heading, "deviations (1):")
        self.assertEqual(shown, ["one"])

    def test_none(self):
        self.designed()
        self.assertIn("deviations: none", self.lines())


# --------------------------------------------------------------------------
# FR-006: look here first
# --------------------------------------------------------------------------


def ranking(*paths):
    return {"source": "graph", "files": [{"path": p, "fix": "top"} for p in paths]}


class TestLookHere(DigestCase):

    def test_the_verdict_ranking_wins(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("d.py")}),
                    ("review-verdict", {"verdict": "not-ready",
                                        "ranking": ranking("a.py", "b.py", "c.py",
                                                           "e.py")})])
        self.assertEqual(self.lines()[-1], "look here first: a.py · b.py · c.py")
        self.assertEqual(self.doc()["look_here"],
                         {"files": ["a.py", "b.py", "c.py"], "from": "review-verdict",
                          "unavailable": None})

    def test_the_design_ranking_is_the_fallback(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("d.py")}),
                    ("review-verdict", {"verdict": "not-ready"})])
        self.assertEqual(self.lines()[-1], "look here first: d.py")
        self.assertEqual(self.doc()["look_here"]["from"], "design-committed")

    def test_source_none(self):
        self.batch([("flow-started", {"request": "#1234"}),
                    ("design-committed", {"worklog": WORKLOG, "ranking": {
                        "source": "none", "unavailable": "not a git repository"}})])
        self.assertEqual(self.lines()[-1],
                         "look here first: — risk signals unavailable "
                         "(not a git repository)")
        self.assertEqual(self.doc()["look_here"],
                         {"files": [], "from": "design-committed",
                          "unavailable": "not a git repository"})

    def test_no_ranking(self):
        self.designed()
        self.assertEqual(self.lines()[-1], "look here first: — no risk ranking recorded")
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
        self.assertEqual(self.lines()[-1], "look here first: ok.py")

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
        self.assertTrue(self.lines()[0].endswith("What changed: — " + self.UNUSABLE))
        self.assertNotIn("my notes", self.digest())

    def test_a_ranking_that_is_no_object(self):
        self.designed()
        self.legacy("review-verdict", {"verdict": "not-ready", "ranking": ["a.py"]})
        self.assertEqual(self.lines()[-1], "look here first: — no risk ranking recorded")


# --------------------------------------------------------------------------
# FR-007, SC-001: the slots and the line cap
# --------------------------------------------------------------------------


class TestSlots(DigestCase):

    def test_a_full_stream_prints_16_lines(self):
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
        self.assertEqual(len(lines), 16, "\n".join(lines))
        self.assertEqual(len(lines), J.max_lines())
        self.assertIn("decided alone (10, 4 shown; --all prints every one):", lines)
        self.assertIn(
            f"deviations (7, 3 shown; --all prints every one; notes in {WORKLOG}):", lines)
        self.assertEqual(len(self.lines("--all")), 1 + 5 + 1 + 10 + 1 + 7 + 1)

    def test_the_layout_of_an_empty_stream(self):
        self.write(PRD, "# PRD\n")
        self.designed()
        self.assertEqual(self.lines(), [
            f"{S} — verdict — · publish held. What changed:",
            "  - The digest prints.",
            "  - It fits.",
            "decided alone: none",
            "deviations: none",
            "look here first: — no risk ranking recorded",
        ])


# --------------------------------------------------------------------------
# FR-008, SC-007: hostile payloads
# --------------------------------------------------------------------------


class TestHostilePayloads(DigestCase):

    def test_every_line_is_one_line_of_at_most_160_characters(self):
        esc = chr(27)
        long_text = "x" * 1000
        planted = f"line one\nfake heading:\r\n  - forged item {esc}[2K{esc}[1A"
        self.write(WORKLOG, worklog_text(
            f"## What changed\n- {long_text}\n- {planted.splitlines()[0]} "
            f"{esc}[31mred{chr(0x202E)}\n\n"))
        self.write(PRD, "# PRD\n")
        self.batch([("flow-started", {"request": "#1234"}),
                    ("clarify-passed", {"prd": PRD}),
                    ("gate-decision", {"gate": "design", "question": planted,
                                       "decision": "y" * 600, "mode": "executive"}),
                    ("design-committed", {"worklog": WORKLOG,
                                          "ranking": ranking("a" * 300 + ".py")})])
        self.legacy("deviation", {"note": planted + long_text})
        for flags in ((), ("--all",)):
            with self.subTest(flags=flags):
                out = self.digest(*flags)
                lines = out.splitlines()
                self.assertEqual(len(lines), 1 + 2 + 2 + 2 + 1, out)
                for line in lines:
                    self.assertLessEqual(len(line), 160, line)
                    self.assertTrue(line.isprintable(), repr(line))
                self.assertNotIn(esc, out)
                self.assertFalse(any(l.startswith("fake heading") for l in lines))

    def test_a_hostile_stream_name_stays_on_the_first_line(self):
        stream = "feature/" + "s" * 300
        self.batch([("flow-started", {"request": "#1234"})], stream=stream)
        lines = self.lines(stream=stream)
        self.assertLessEqual(len(lines[0]), 160)
        self.assertTrue(lines[0].endswith("…"))


if __name__ == "__main__":
    unittest.main()
