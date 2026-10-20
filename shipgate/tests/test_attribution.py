#!/usr/bin/env python3
"""Artifact authorship, resolved when the journal is read (ADR 0008).

Hooks record claims about who wrote an artifact: `tool` and `bash` rows name a
session, `disk` rows name only the watcher that saw the write. These tests pin the
three places that decide what those claims mean:

- `append`: which repeat of a write is dropped (the dedupe by source and session);
- `claim_of` / `artifact_authors`: the read-time fold (precedence, ties, legacy rows);
- `check --session` and `stats`: the readers that take authors from the fold only.

Run from the repo root:

    python3 -m unittest discover -s shipgate/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

JOURNAL = Path(__file__).resolve().parent.parent / "scripts" / "journal.py"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

OK = 0
CHECK = 5

MTIME = 1756800000.0
PRD = "docs/prd/demo.md"
WORKLOG = "docs/prd/demo.worklog.md"
WRITER = "sess-writer"
OBSERVER = "sess-observer"


def load_journal_module():
    spec = importlib.util.spec_from_file_location("shipgate_journal_attr", JOURNAL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


J = load_journal_module()


def tool(session=WRITER, path=PRD, mtime=MTIME):
    return {"path": path, "source": "tool", "tool": "Write", "mtime": mtime,
            "session": session}


def bash(evidence, session=WRITER, path=PRD, mtime=MTIME):
    return {"path": path, "source": "bash", "evidence": evidence, "mtime": mtime,
            "session": session}


def disk(observer=OBSERVER, path=PRD, mtime=MTIME):
    return {"path": path, "source": "disk", "change": "change", "mtime": mtime,
            "observed_by": observer}


def legacy_disk(session=OBSERVER, path=PRD, mtime=MTIME):
    """A FileChanged row from before ADR 0008: the observer recorded as `session`."""
    return {"path": path, "source": "disk", "change": "change", "mtime": mtime,
            "session": session}


def event(data, seq=1, event_type="artifact-written", actor="hook"):
    return J.Event(seq=seq, stream="shipgate", version=seq, type=event_type,
                   data=data, ts="2026-10-20T00:00:00+00:00", actor=actor)


def events(*payloads):
    return [event(data, seq=index) for index, data in enumerate(payloads, start=1)]


class TestClaimOf(unittest.TestCase):
    def test_a_tool_row_claims_for_its_session(self):
        self.assertEqual(
            J.claim_of(event(tool())),
            {"source": "tool", "session": WRITER, "evidence": None},
        )

    def test_a_bash_row_carries_its_evidence(self):
        for evidence in ("diff", "window"):
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    J.claim_of(event(bash(evidence))),
                    {"source": "bash", "session": WRITER, "evidence": evidence},
                )

    def test_bash_evidence_outside_the_vocabulary_makes_no_claim(self):
        for evidence in (None, "guess", 3):
            with self.subTest(evidence=evidence):
                self.assertIsNone(J.claim_of(event(bash(evidence))))

    def test_a_disk_row_never_names_a_session(self):
        self.assertEqual(
            J.claim_of(event(disk())),
            {"source": "disk", "session": None, "evidence": None},
        )

    def test_a_legacy_disk_row_with_a_session_counts_as_observed(self):
        self.assertEqual(J.claim_of(event(legacy_disk()))["session"], None)

    def test_an_authored_row_without_a_session_claims_with_none(self):
        for data in ({**tool(), "session": None}, {**bash("diff"), "session": ""}):
            with self.subTest(data=data):
                self.assertIsNone(J.claim_of(event(data))["session"])

    def test_rows_that_make_no_claim(self):
        cases = {
            "another event type": event(tool(), event_type="deviation"),
            "no path": event({k: v for k, v in tool().items() if k != "path"}),
            "a non-string path": event({**tool(), "path": 7}),
            "no source": event({k: v for k, v in tool().items() if k != "source"}),
            "an unknown source": event({**tool(), "source": "sync"}),
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                self.assertIsNone(J.claim_of(case))


class TestArtifactAuthors(unittest.TestCase):
    KEY = (PRD, MTIME)

    def test_the_writer_is_the_author_whatever_the_observer_saw(self):
        authors = J.artifact_authors(events(disk(), tool()))
        self.assertEqual(authors, {self.KEY: WRITER})

    def test_tool_beats_bash_diff_beats_bash_window(self):
        cases = [
            (tool("A"), bash("diff", "B")),
            (bash("diff", "A"), bash("window", "B")),
            (tool("A"), bash("window", "B")),
        ]
        for stronger, weaker in cases:
            for order in ((stronger, weaker), (weaker, stronger)):
                with self.subTest(order=order):
                    self.assertEqual(J.artifact_authors(events(*order)), {self.KEY: "A"})

    def test_two_sessions_at_the_best_evidence_name_no_author(self):
        for make in (tool, lambda s: bash("diff", s), lambda s: bash("window", s)):
            with self.subTest(claim=make("X")["source"]):
                self.assertEqual(
                    J.artifact_authors(events(make("A"), make("B"))), {self.KEY: None}
                )

    def test_a_weaker_claim_does_not_break_a_tie(self):
        authors = J.artifact_authors(
            events(bash("window", "A"), bash("window", "B"), bash("window", "A"))
        )
        self.assertEqual(authors, {self.KEY: None})

    def test_one_session_claiming_twice_is_still_one_author(self):
        authors = J.artifact_authors(events(tool("A"), tool("A"), bash("window", "A")))
        self.assertEqual(authors, {self.KEY: "A"})

    def test_observed_only_writes_have_no_author(self):
        authors = J.artifact_authors(events(disk(), legacy_disk(), legacy_disk("Z")))
        self.assertEqual(authors, {self.KEY: None})

    def test_a_claim_without_a_session_never_ranks(self):
        authors = J.artifact_authors(
            events({**tool(), "session": None}, bash("window", "A"))
        )
        self.assertEqual(authors, {self.KEY: "A"})

    def test_writes_are_keyed_by_path_and_mtime(self):
        authors = J.artifact_authors(events(
            tool("A"), tool("B", mtime=MTIME + 1), tool("C", path=WORKLOG),
            {**tool("D"), "mtime": None},
        ))
        self.assertEqual(authors, {
            (PRD, MTIME): "A", (PRD, MTIME + 1): "B", (WORKLOG, MTIME): "C",
            (PRD, None): "D",
        })

    def test_rows_that_make_no_claim_add_no_key(self):
        authors = J.artifact_authors(events(
            {k: v for k, v in tool().items() if k != "source"}, bash("guess"),
        ) + [event(tool(), event_type="deviation")])
        self.assertEqual(authors, {})


class TestParseActorForAnObservation(unittest.TestCase):
    """An observation keeps the bare `hook` role: the hook's environment names the
    observing session, which must not become the row's label again."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self._saved = os.environ.get(SESSION_ENV)
        os.environ[SESSION_ENV] = OBSERVER
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop(SESSION_ENV, None)
        else:
            os.environ[SESSION_ENV] = self._saved

    def test_observed_by_keeps_the_bare_role(self):
        self.assertEqual(J.parse_actor("hook", self.conn, disk()), "hook")

    def test_a_null_observed_by_still_keeps_the_bare_role(self):
        self.assertEqual(J.parse_actor("hook", self.conn, disk(observer=None)), "hook")

    def test_without_either_key_the_environment_still_labels(self):
        self.assertEqual(J.parse_actor("hook", self.conn, {"path": PRD}),
                         f"hook@{OBSERVER}")


class JournalCase(unittest.TestCase):
    """A temp project with an initialized journal, driven through the CLI."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "shipgate.db"
        self.journal("init", rc=OK)

    def journal(self, *args, rc=None, session_env=None):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        if session_env is not None:
            env[SESSION_ENV] = session_env
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), *map(str, args)],
            cwd=str(self.root), env=env, capture_output=True, text=True, timeout=60,
        )
        if rc is not None:
            self.assertEqual(proc.returncode, rc, f"{args}\n{proc.stdout}\n{proc.stderr}")
        return proc

    def append(self, data, stream="shipgate", event_type="artifact-written",
               actor="hook", session_env=None):
        return self.journal(
            "append", "--stream", stream, "--type", event_type,
            "--data", json.dumps(data), "--actor", actor, "--json",
            rc=OK, session_env=session_env,
        )

    def rows(self, stream="shipgate"):
        proc = self.journal("log", "--json", "--stream", stream, rc=OK)
        return [e for e in json.loads(proc.stdout)["events"]
                if e["type"] == "artifact-written"]

    def backdate(self, seconds):
        stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        conn = sqlite3.connect(str(self.db))
        try:
            conn.execute(
                "UPDATE events SET ts = ? WHERE type = 'artifact-written'", (stale,)
            )
            conn.commit()
        finally:
            conn.close()

    def write(self, relpath, text):
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class TestAppendDedupeBySourceAndSession(JournalCase):
    def sources(self):
        return [(r["data"]["source"], r["data"].get("session"),
                 r["data"].get("evidence")) for r in self.rows()]

    def test_an_observer_landing_first_cannot_swallow_the_writers_claim(self):
        self.append(disk())
        self.append(tool())
        self.assertEqual(self.sources(), [("disk", None, None), ("tool", WRITER, None)])

    def test_an_observation_after_the_writer_is_dropped(self):
        self.append(tool())
        self.assertTrue(json.loads(self.append(disk()).stdout)["duplicate"])
        self.assertEqual(self.sources(), [("tool", WRITER, None)])

    def test_two_observations_of_one_write_keep_one_row(self):
        self.append(disk())
        self.append(disk("another-observer"))
        self.assertEqual(len(self.rows()), 1)

    def test_an_observation_outside_five_seconds_is_recorded_again(self):
        self.append(tool())
        self.backdate(30)
        self.append(disk())
        self.assertEqual(len(self.rows()), 2)

    def test_two_sessions_claiming_one_write_are_both_kept(self):
        self.append(bash("window", "A"))
        self.append(bash("window", "B"))
        self.assertEqual(self.sources(),
                         [("bash", "A", "window"), ("bash", "B", "window")])

    def test_the_same_session_claiming_again_is_dropped(self):
        self.append(tool())
        self.assertTrue(json.loads(self.append(tool()).stdout)["duplicate"])
        self.assertEqual(len(self.rows()), 1)

    def test_the_lookback_covers_a_long_bash_call(self):
        """The Write's claim lands when it ran; a Bash call naming the same write
        reports when it ends, up to Claude Code's 10-minute Bash timeout later."""
        self.append(tool())
        self.backdate(9 * 60)
        self.assertTrue(json.loads(self.append(bash("window")).stdout)["duplicate"])
        self.assertEqual(len(self.rows()), 1)

    def test_past_the_lookback_the_same_claim_is_recorded_again(self):
        self.append(tool())
        self.backdate(20 * 60)
        self.append(tool())
        self.assertEqual(len(self.rows()), 2)

    def test_stronger_evidence_from_the_same_session_is_kept(self):
        """A weaker claim landing first must not hide the session's stronger one."""
        self.append(bash("window"))
        self.append(bash("diff"))
        self.append(tool())
        self.assertEqual(self.sources(), [
            ("bash", WRITER, "window"), ("bash", WRITER, "diff"), ("tool", WRITER, None),
        ])

    def test_weaker_evidence_from_the_same_session_is_dropped(self):
        self.append(tool())
        self.append(bash("diff"))
        self.append(bash("window"))
        self.assertEqual(self.sources(), [("tool", WRITER, None)])

    def test_a_claim_on_another_mtime_is_a_new_write(self):
        self.append(tool())
        self.append(tool(mtime=MTIME + 2))
        self.assertEqual(len(self.rows()), 2)

    def test_an_observation_row_is_stored_with_the_bare_hook_role(self):
        """`CLAUDE_CODE_SESSION_ID` in the hook's environment names the observer."""
        self.append(disk(), session_env=OBSERVER)
        row = self.rows()[0]
        self.assertEqual(row["actor"], "hook")
        self.assertNotIn("session", row["data"])


WORKLOG_ONE_TICKED = """# Worklog: demo

# Build Plan
- [x] T001 — first
- [ ] T002 — second
"""


class TestCheckReadsTheFold(JournalCase):
    """Rules A and B of the Stop gate follow the fold's author, never the raw rows."""

    def setUp(self):
        super().setUp()
        self.write(WORKLOG, WORKLOG_ONE_TICKED)
        self.write(PRD, "# PRD\n")
        self.append({"phase": "workspace"}, stream="feature/demo",
                     event_type="phase-entered", actor="orchestrator")

    def check(self, session):
        return self.journal("check", "--session", session, "--json")

    def missing(self, session):
        proc = self.check(session)
        self.assertIn(proc.returncode, (OK, CHECK), proc.stderr)
        return sorted(f["missing"] for f in json.loads(proc.stdout)["findings"])

    def test_the_writer_is_gated_and_the_observer_is_not(self):
        self.append(disk(path=WORKLOG))
        self.append(tool(path=WORKLOG))
        self.assertEqual(self.missing(WRITER), ["task-done"])
        self.assertEqual(self.missing(OBSERVER), [])

    def test_a_legacy_observation_gates_nobody(self):
        self.append(legacy_disk(path=WORKLOG))
        self.assertEqual(self.missing(OBSERVER), [])

    def test_a_bash_claim_gates_its_session(self):
        self.append(bash("window", path=WORKLOG))
        self.assertEqual(self.missing(WRITER), ["task-done"])

    def test_a_tie_gates_neither_session(self):
        self.append(bash("window", "A", path=WORKLOG))
        self.append(bash("window", "B", path=WORKLOG))
        self.assertEqual(self.missing("A"), [])
        self.assertEqual(self.missing("B"), [])

    def test_the_better_claim_decides_whom_rule_b_gates(self):
        self.append({"phase": "clarify", "skipped": ["route-and-map", "explore"]},
                    stream="feature/demo", event_type="phase-entered",
                    actor="orchestrator")
        self.append(bash("window", OBSERVER))
        self.append(bash("diff", WRITER))
        self.assertEqual(self.missing(WRITER), ["gate-decision"])
        self.assertEqual(self.missing(OBSERVER), [])

    def test_a_row_that_makes_no_claim_gates_nobody(self):
        self.append({"path": WORKLOG, "tool": "Write", "session": WRITER})
        self.assertEqual(self.missing(WRITER), [])


class TestStatsCountsAuthorsFromTheFold(JournalCase):
    STREAM = "feature/x"

    def sessions(self):
        proc = self.journal("stats", "--stream", self.STREAM, "--json", rc=OK)
        report = json.loads(proc.stdout)
        return report["streams"][0]["sessions"], report["totals"]["sessions"]

    def test_only_authors_count_as_sessions(self):
        self.append(legacy_disk("observer-legacy"), stream=self.STREAM)
        self.append(disk("observer-new", mtime=MTIME + 1), stream=self.STREAM)
        self.append(tool("writer", mtime=MTIME + 2), stream=self.STREAM)
        self.append(bash("window", "tie-a", mtime=MTIME + 3), stream=self.STREAM)
        self.append(bash("window", "tie-b", mtime=MTIME + 3), stream=self.STREAM)
        self.append({"note": "n"}, stream=self.STREAM, event_type="deviation",
                    actor="orchestrator@driver")
        self.assertEqual(self.sessions(), (2, 2))  # writer, driver


if __name__ == "__main__":
    unittest.main()
