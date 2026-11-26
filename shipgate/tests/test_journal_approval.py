#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: the user's go.

Commit and publish authorization, the recorder's reply plan and ``authorize``. Split out of
``test_journal.py`` (#61), which holds the helpers and fixtures.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from test_journal import (
    CHECK, GATE, INFRA, insert_legacy_row, JOURNAL, JournalTestCase, legacy_read_go,
    load_journal_module, OK, SESSION_ENV, USAGE, WORKLOG_TEMPLATE,
)


class TestPublishAuthorization(unittest.TestCase):
    """The one publish rule that `mr-opened`, `status` and `position` read (ADR 0009)."""

    def setUp(self):
        self.journal = load_journal_module()

    def event(self, seq, etype, data=None, actor="orchestrator@s"):
        return self.journal.Event(
            seq=seq, stream="feature/x", version=seq, type=etype, data=data or {},
            ts=f"2026-10-01T09:{seq:02d}:00+00:00", actor=actor,
        )

    def task_done(self, seq):
        return self.event(seq, "task-done", {"task_id": "T001"})

    def verdict(self, seq, verdict="ready"):
        return self.event(seq, "review-verdict", {"verdict": verdict})

    def decision(self, seq, decision="publish", raised_by="user", gate="publish",
                 source="dialog", actor="user"):
        data = {
            "gate": gate, "question": "q", "decision": decision, "mode": "ask",
            "raised_by": raised_by,
        }
        if source is not None:
            data["source"] = source
        return self.event(seq, "gate-decision", data, actor=actor)

    def authorize(self, *events):
        return self.journal.publish_authorization(list(events))

    def authorized(self, by, seq):
        return {"kind": "authorized", "by": by, "seq": seq,
                "at": f"2026-10-01T09:{seq:02d}:00+00:00"}

    def test_no_events_is_held(self):
        self.assertEqual(self.authorize(), {"kind": "held"})

    def test_a_ready_verdict_names_its_seq_and_time(self):
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2)),
            self.authorized("review-verdict", 2),
        )

    def test_a_not_ready_verdict_is_held(self):
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2, "not-ready")),
            {"kind": "held"},
        )

    def test_with_no_task_done_any_authorizing_event_counts(self):
        self.assertEqual(self.authorize(self.decision(1)),
                         self.authorized("gate-decision", 1))

    def test_the_decision_is_trimmed_and_read_in_any_case(self):
        for value in ("publish", "  Publish ", "PUBLISH\n", "\tpublish"):
            with self.subTest(value=value):
                self.assertEqual(self.authorize(self.decision(1, value)),
                                 self.authorized("gate-decision", 1))

    def test_a_decision_that_says_more_than_publish_is_held(self):
        for value in ("publish it", "'publish'", "no", ""):
            with self.subTest(value=value):
                self.assertEqual(self.authorize(self.decision(1, value)),
                                 {"kind": "held"})

    def test_a_decision_that_is_not_a_string_never_authorizes(self):
        """Rows from before the string rule; Python's str() of a list is not JS's."""
        for value in (["publish"], {"publish": True}, None, 1):
            with self.subTest(value=value):
                self.assertEqual(self.authorize(self.decision(1, value)),
                                 {"kind": "held"})

    def test_a_decision_the_user_did_not_raise_or_at_another_gate_is_held(self):
        self.assertEqual(self.authorize(self.decision(1, raised_by="orchestrator")),
                         {"kind": "held"})
        self.assertEqual(self.authorize(self.decision(1, gate="design")),
                         {"kind": "held"})

    def test_a_decision_without_the_source_marker_is_held(self):
        """ADR 0015: an older unmarked decision no longer authorizes."""
        for source in (None, "hud", "", ["dialog"]):
            with self.subTest(source=source):
                self.assertEqual(self.authorize(self.decision(1, source=source)),
                                 {"kind": "held"})

    def test_both_markers_authorize(self):
        for source in ("dialog", "shell"):
            with self.subTest(source=source):
                self.assertEqual(self.authorize(self.decision(1, source=source)),
                                 self.authorized("gate-decision", 1))

    def test_a_marked_decision_needs_an_actor_of_role_user(self):
        for actor in ("orchestrator@s", "worker", "hook", None, "", "users@x"):
            with self.subTest(actor=actor):
                self.assertEqual(self.authorize(self.decision(1, actor=actor)),
                                 {"kind": "held"})
        for actor in ("user", "user@alice"):
            with self.subTest(actor=actor):
                self.assertEqual(self.authorize(self.decision(1, actor=actor)),
                                 self.authorized("gate-decision", 1))

    # #40: the newest verdict after the last task-done decides. The built-in
    # /security-review runs on the commit, after the briefed pass's ready verdict.
    def test_a_later_not_ready_verdict_holds_an_earlier_ready_one(self):
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2), self.verdict(3, "not-ready")),
            {"kind": "held"},
        )

    def test_a_ready_verdict_after_a_not_ready_one_authorizes(self):
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2, "not-ready"), self.verdict(3)),
            self.authorized("review-verdict", 3),
        )

    def test_the_newest_of_two_ready_verdicts_names_the_authorization(self):
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2), self.verdict(3)),
            self.authorized("review-verdict", 3),
        )

    def test_a_later_not_ready_verdict_is_read_in_seq_order(self):
        self.assertEqual(
            self.authorize(self.verdict(3, "not-ready"), self.verdict(2), self.task_done(1)),
            {"kind": "held"},
        )

    def test_the_events_are_read_in_seq_order_not_list_order(self):
        """A task-done with a higher seq makes an earlier verdict stale, wherever the
        list puts it."""
        self.assertEqual(self.authorize(self.verdict(5), self.task_done(7)),
                         {"kind": "held"})
        self.assertEqual(self.authorize(self.task_done(7), self.verdict(5)),
                         {"kind": "held"})

    def test_a_forced_ready_verdict_is_held(self):
        """ADR 0023 §17, FR-033."""
        forced = self.event(2, "review-verdict",
                            {"verdict": "ready", "forced": True, "force_reason": "x"})
        self.assertEqual(self.authorize(self.task_done(1), forced), {"kind": "held"})
        self.assertEqual(self.authorize(self.task_done(1), forced, self.verdict(3)),
                         self.authorized("review-verdict", 3))

    def test_the_newest_verdict_rule_skips_a_forced_ready_verdict(self):
        """ADR 0023 §17 skips a forced ready; #40's newest-verdict rule keeps that."""
        forced = self.event(3, "review-verdict",
                            {"verdict": "ready", "forced": True, "force_reason": "x"})
        self.assertEqual(self.authorize(self.task_done(1), self.verdict(2), forced),
                         self.authorized("review-verdict", 2))
        self.assertEqual(
            self.authorize(self.task_done(1), self.verdict(2), self.verdict(3, "not-ready"),
                           self.event(4, "review-verdict",
                                      {"verdict": "ready", "forced": True})),
            {"kind": "held"},
        )

    def test_the_first_authorizing_event_in_seq_order_is_named(self):
        self.assertEqual(
            self.authorize(self.decision(9), self.verdict(6), self.task_done(3)),
            self.authorized("review-verdict", 6),
        )


class TestUserGo(unittest.TestCase):
    """ADR 0023 §1, §2 and amendment A4: the user's go for a gate, as the command gate
    reads it."""

    def setUp(self):
        self.journal = load_journal_module()

    def event(self, seq, etype, data=None, actor="orchestrator@A"):
        return self.journal.Event(
            seq=seq, stream="feature/x", version=seq, type=etype, data=data or {},
            ts=f"2026-10-01T09:{seq:02d}:00+00:00", actor=actor,
        )

    def task_done(self, seq):
        return self.event(seq, "task-done", {"task_id": "T001"})

    def go(self, seq, gate="commit", source="question", actor="user", decision=None,
           raised_by="user", **extra):
        data = {"gate": gate, "question": "q", "decision": decision or gate,
                "mode": "ask", "raised_by": raised_by, **extra}
        if source is not None:
            data["source"] = source
        return self.event(seq, "gate-decision", data, actor=actor)

    def witness(self, seq, gate="commit", session="A", actor="hook", request=1):
        return self.event(seq, "reply-witnessed", {
            "request": request, "gate": gate, "via": "prompt", "session": session,
        }, actor=actor)

    def read_go(self, seq, witness, gate="commit", actor="orchestrator@A"):
        """A read go as untagged 0.28.0 wrote it."""
        return self.event(seq, "gate-decision", legacy_read_go(gate, witness), actor=actor)

    def answer(self, gate, *events):
        return self.journal.user_go(list(events), gate)

    def authorized(self, seq):
        return {"kind": "authorized", "by": "gate-decision", "seq": seq,
                "at": f"2026-10-01T09:{seq:02d}:00+00:00"}

    HELD = {"kind": "held"}

    def test_no_events_hold_both_gates(self):
        self.assertEqual(self.answer("commit"), self.HELD)
        self.assertEqual(self.answer("publish"), self.HELD)

    def test_each_marker_of_the_user_is_a_go(self):
        for source in ("dialog", "shell", "question", "prompt"):
            with self.subTest(source=source):
                self.assertEqual(self.answer("commit", self.go(1, source=source)),
                                 self.authorized(1))

    def test_a_publish_go_satisfies_the_commit_gate_and_not_the_reverse(self):
        self.assertEqual(self.answer("commit", self.go(1, gate="publish")),
                         self.authorized(1))
        self.assertEqual(self.answer("publish", self.go(1, gate="publish")),
                         self.authorized(1))
        self.assertEqual(self.answer("publish", self.go(1, gate="commit")), self.HELD)

    def test_a_go_lasts_until_the_next_task_done(self):
        self.assertEqual(self.answer("commit", self.go(1), self.task_done(2)), self.HELD)
        self.assertEqual(self.answer("commit", self.task_done(1), self.go(2)),
                         self.authorized(2))
        self.assertEqual(
            self.answer("commit", self.task_done(1), self.go(2), self.task_done(3)),
            self.HELD,
        )

    def test_a_row_that_is_no_go_holds(self):
        rows = {
            "no marker": self.go(1, source=None),
            "a marker outside the five": self.go(1, source="hud"),
            "an orchestrator actor": self.go(1, actor="orchestrator@A"),
            "raised by the orchestrator": self.go(1, raised_by="orchestrator"),
            "another decision": self.go(1, decision="hold"),
            "a decision that names the other gate": self.go(1, decision="publish"),
            "another gate": self.go(1, gate="scope", decision="scope"),
        }
        for name, row in rows.items():
            with self.subTest(row=name):
                self.assertEqual(self.answer("commit", row), self.HELD)

    def test_the_decision_is_trimmed_and_read_in_any_case(self):
        self.assertEqual(self.answer("commit", self.go(1, decision=" Commit ")),
                         self.authorized(1))

    def test_a_ready_verdict_is_no_go(self):
        verdict = self.event(1, "review-verdict", {"verdict": "ready"})
        self.assertEqual(self.answer("commit", verdict), self.HELD)
        self.assertEqual(self.answer("publish", verdict), self.HELD)

    def test_a_read_go_of_0_28_0_is_no_go(self):
        """#52, amendment A4: an old read row with a valid witness authorizes nothing,
        under any actor."""
        for actor in ("orchestrator@A", "user"):
            with self.subTest(actor=actor):
                for gate in ("commit", "publish"):
                    events = [self.witness(2, gate=gate),
                              self.read_go(3, 2, gate=gate, actor=actor)]
                    self.assertEqual(self.answer(gate, *events), self.HELD)
                    self.assertEqual(self.answer("commit", *events), self.HELD)

    def test_a_question_go_after_a_witness_is_a_go(self):
        """The confirming question's click: a question go after the witness."""
        self.assertEqual(
            self.answer("commit", self.witness(2), self.go(4, request=3)),
            self.authorized(4),
        )

    def test_commit_authorization_is_the_go_at_the_commit_gate(self):
        events = [self.task_done(1), self.go(2, gate="publish")]
        self.assertEqual(self.journal.commit_authorization(events), self.authorized(2))
        self.assertEqual(self.journal.commit_authorization([self.task_done(1)]), self.HELD)

    def test_publish_authorization_reads_the_new_markers(self):
        for go in (self.go(1, gate="publish", source="question"),
                   self.go(1, gate="publish", source="prompt")):
            with self.subTest(source=go.data["source"]):
                self.assertEqual(self.journal.publish_authorization([go]),
                                 self.authorized(1))
        read = [self.witness(1, gate="publish"), self.read_go(2, 1, gate="publish")]
        self.assertEqual(self.journal.publish_authorization(read), self.HELD)


class TestGoInStatusAndPosition(JournalTestCase):
    """FR-014: `status --json` and `position --json` print the go of each gate."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})

    def go_of(self):
        feature = next(f for f in self.status_json()["features"]
                       if f["stream"] == "feat/1-x")
        proc = self.journal("--db", self.db, "position", "--stream", "feat/1-x", "--json",
                            rc=OK)
        position = json.loads(proc.stdout)["go"]
        self.assertEqual(feature["go"], position)
        return position

    def test_both_gates_are_held_with_no_go(self):
        self.assertEqual(self.go_of(), {"commit": {"kind": "held"},
                                        "publish": {"kind": "held"}})

    def test_a_commit_go_authorizes_the_commit_gate_only(self):
        self.append_event("feat/1-x", "gate-decision", {
            "gate": "commit", "question": "q", "decision": "commit", "mode": "ask",
            "raised_by": "user", "source": "question",
        }, "--actor", "user")
        row = self.events("feat/1-x")[-1]
        self.assertEqual(self.go_of(), {
            "commit": {"kind": "authorized", "by": "gate-decision", "seq": row["seq"],
                       "at": row["ts"]},
            "publish": {"kind": "held"},
        })


class TestApprovalPathPins(JournalTestCase):
    """T001 of the approval path (ADR 0023): behaviour that the change must keep."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def test_an_unmarked_user_row_binds_its_recording_session(self):
        """ADR 0010: a `user` row with no `source` binds the session that wrote it."""
        self.append_event("epic-1", "flow-started", {"request": "x"},
                          "--actor", "orchestrator@A")
        decision = {"gate": "scope", "question": "q", "decision": "d",
                    "mode": "ask", "raised_by": "user"}
        proc = self.journal(
            "--db", self.db, "append", "--stream", "feat/1-x", "--type",
            "gate-decision", "--data", json.dumps(decision), "--actor", "user",
            session_env="A", rc=OK,
        )
        self.assertIn("gate-decision", proc.stdout)
        self.assertEqual(self.status_json("--session", "A")["session_match"], "feat/1-x")

    def test_publish_is_held_after_a_task_done_and_authorized_by_a_ready_verdict(self):
        self.append_event("feat/1-x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event("feat/1-x", "task-done", {"task_id": "T001"})

        def publish():
            features = self.status_json()["features"]
            return next(f for f in features if f["stream"] == "feat/1-x")["publish"]

        self.assertEqual(publish(), {"kind": "held"})
        self.append_event("feat/1-x", "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event("feat/1-x", "review-verdict", {"verdict": "ready"})
        verdict = self.events("feat/1-x")[-1]
        self.assertEqual(publish(), {"kind": "authorized", "by": "review-verdict",
                                     "seq": verdict["seq"], "at": verdict["ts"]})


class TestGoRequested(JournalTestCase):
    """ADR 0023 §3: a go request names one gate of one live stream and keeps the question."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})

    def request(self, data, *args, stream="feat/1-x", rc=OK):
        return self.append_event(stream, "go-requested", data, *args, rc=rc)

    def test_a_request_at_each_gate_is_recorded(self):
        for gate in ("commit", "publish"):
            with self.subTest(gate=gate):
                self.request({"gate": gate, "question": "Commit T003?"})
                last = self.events("feat/1-x")[-1]
                self.assertEqual(last["type"], "go-requested")
                self.assertEqual(last["data"], {"gate": gate, "question": "Commit T003?"})

    def test_the_shape_is_enforced(self):
        bad = {
            "no gate": {"question": "q"},
            "no question": {"gate": "commit"},
            "another gate": {"gate": "scope", "question": "q"},
            "a gate in capitals": {"gate": "Commit", "question": "q"},
            "a question that is no string": {"gate": "commit", "question": ["q"]},
        }
        for name, data in bad.items():
            with self.subTest(payload=name):
                proc = self.request(data, rc=GATE)
                self.assertIn("vocab --shape go-requested", proc.stderr)
        self.assertEqual(self.events("feat/1-x")[-1]["type"], "flow-started")

    def test_a_request_that_names_a_session_is_refused(self):
        """Review round 1, F7: `session` in the data would hide the appending session."""
        proc = self.request({"gate": "commit", "question": "q", "session": "A"}, rc=GATE)
        self.assertIn("data.session", proc.stderr)

    def test_a_request_implies_no_phase(self):
        self.request({"gate": "commit", "question": "q"})
        types = [e["type"] for e in self.events("feat/1-x")]
        self.assertEqual(types, ["flow-started", "go-requested"])

    def test_a_request_on_a_missing_stream_is_refused_with_and_without_force(self):
        for args in ((), ("--force", "--force-reason", "x")):
            with self.subTest(args=args):
                proc = self.request({"gate": "commit", "question": "q"}, *args,
                                    stream="feat/9-none", rc=GATE)
                self.assertIn("live stream", proc.stderr)
                self.assertEqual(self.events("feat/9-none"), [])

    def test_a_request_on_a_finished_stream_is_refused(self):
        self.append_event("feat/1-x", "flow-completed", {})
        for args in ((), ("--force", "--force-reason", "x")):
            with self.subTest(args=args):
                proc = self.request({"gate": "publish", "question": "q"}, *args,
                                    rc=GATE)
                self.assertIn("finished", proc.stderr)
        self.assertEqual(self.events("feat/1-x")[-1]["type"], "flow-completed")


class TestReplyWitnessed(JournalTestCase):
    """ADR 0023 §7: a witness names a request, its gate, the way the reply came and the
    session. It holds no text."""

    WITNESS = {"request": 3, "gate": "commit", "via": "prompt", "session": "A"}

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})

    def witness(self, data, rc=OK):
        return self.append_event("feat/1-x", "reply-witnessed", data, "--actor", "hook",
                                 rc=rc)

    def test_a_witness_is_recorded_with_its_optional_ids(self):
        data = {**self.WITNESS, "prompt_id": "p-1", "tool_use_id": "t-1"}
        self.witness(data)
        last = self.events("feat/1-x")[-1]
        self.assertEqual(last["type"], "reply-witnessed")
        self.assertEqual(last["data"], data)
        self.assertEqual(last["actor"], "hook")

    def test_the_shape_is_enforced(self):
        bad = {
            "no request": {k: v for k, v in self.WITNESS.items() if k != "request"},
            "no session": {k: v for k, v in self.WITNESS.items() if k != "session"},
            "a request that is text": {**self.WITNESS, "request": "3"},
            "a boolean request": {**self.WITNESS, "request": True},
            "another gate": {**self.WITNESS, "gate": "scope"},
            "another way": {**self.WITNESS, "via": "dialog"},
            "a prompt id that is no string": {**self.WITNESS, "prompt_id": 4},
        }
        for name, data in bad.items():
            with self.subTest(payload=name):
                proc = self.witness(data, rc=GATE)
                self.assertIn("vocab --shape reply-witnessed", proc.stderr)
        self.assertEqual(self.events("feat/1-x")[-1]["type"], "flow-started")

    def test_a_witness_implies_no_phase(self):
        self.witness(self.WITNESS)
        types = [e["type"] for e in self.events("feat/1-x")]
        self.assertEqual(types, ["flow-started", "reply-witnessed"])


class TestGoDoesNotBind(JournalTestCase):
    """ADR 0023 §13, SC-005: a session that records a go request, a go or a witness for
    another stream keeps its own position and its own Stop gate."""

    WORKLOG = "docs/prd/w.worklog.md"

    def setUp(self):
        super().setUp()
        self.init_db()
        # Session A drives feat/2-b. feat/1-a is another session's stream.
        for stream in ("feat/1-a", "feat/2-b"):
            self.append_event(stream, "flow-started", {"request": "x"},
                              "--actor", "orchestrator@" + ("A" if stream == "feat/2-b"
                                                            else "B"))
            self.append_event(stream, "design-committed", {"worklog": self.WORKLOG},
                              "--actor", "orchestrator@" + ("A" if stream == "feat/2-b"
                                                            else "B"))

    def as_session(self, *args, rc=OK):
        return self.journal("--db", self.db, "append", *args, session_env="A", rc=rc)

    def record_go_rows_for_the_other_stream(self):
        self.as_session("--stream", "feat/1-a", "--type", "go-requested",
                        "--data", json.dumps({"gate": "commit", "question": "q"}))
        request = self.events("feat/1-a")[-1]["seq"]
        self.as_session("--stream", "feat/1-a", "--type", "gate-decision", "--actor",
                        "user", "--data", json.dumps({
                            "gate": "commit", "question": "q", "decision": "commit",
                            "mode": "ask", "raised_by": "user", "source": "prompt",
                            "request": request}))
        self.as_session("--stream", "feat/1-a", "--type", "go-requested",
                        "--data", json.dumps({"gate": "publish", "question": "q"}))
        second = self.events("feat/1-a")[-1]["seq"]
        self.as_session("--stream", "feat/1-a", "--type", "reply-witnessed", "--actor",
                        "hook", "--data", json.dumps({
                            "request": second, "gate": "publish", "via": "prompt",
                            "session": "A"}))
        witness = self.events("feat/1-a")[-1]["seq"]
        # A read go that 0.28.0 wrote stays non-binding after #52 (amendment A4).
        insert_legacy_row(self.db, "feat/1-a", "gate-decision",
                          legacy_read_go("publish", witness), "orchestrator@A")
        types = [e["type"] for e in self.events("feat/1-a")][-5:]
        self.assertEqual(types, ["go-requested", "gate-decision", "go-requested",
                                 "reply-witnessed", "gate-decision"])

    def test_status_session_keeps_the_sessions_own_stream(self):
        self.assertEqual(self.status_json("--session", "A")["session_match"], "feat/2-b")
        self.record_go_rows_for_the_other_stream()
        payload = self.status_json("--session", "A")
        self.assertEqual(payload["session_match"], "feat/2-b")
        self.assertEqual(payload["features"][0]["stream"], "feat/2-b")

    def test_check_points_at_the_sessions_own_stream(self):
        """Both streams own the worklog. The finding goes to the stream the session
        drives, not to the first owner in name order."""
        self.write(self.WORKLOG, WORKLOG_TEMPLATE.format(tasks="- [x] T001 — first"))
        self.record_go_rows_for_the_other_stream()
        self.append_event("feat/2-b", "artifact-written", {
            "path": self.WORKLOG, "source": "tool", "tool": "Write", "session": "A",
        })
        proc = self.journal("--db", self.db, "check", "--session", "A", "--json",
                            rc=CHECK)
        findings = json.loads(proc.stdout)["findings"]
        self.assertEqual([(f["stream"], f["task_id"]) for f in findings],
                         [("feat/2-b", "T001")])

    def test_an_unmarked_user_row_still_binds(self):
        """ADR 0010 holds for every other row: the T001 pin, here beside the new rows."""
        self.record_go_rows_for_the_other_stream()
        self.as_session("--stream", "feat/1-a", "--type", "gate-decision", "--actor",
                        "user", "--data", json.dumps({
                            "gate": "scope", "question": "q", "decision": "d",
                            "mode": "ask", "raised_by": "user"}))
        self.assertEqual(self.status_json("--session", "A")["session_match"], "feat/1-a")

    def test_request_session_reads_the_writer_of_a_request(self):
        module = load_journal_module()
        self.record_go_rows_for_the_other_stream()
        rows = [module.Event(e["seq"], e["stream"], e["version"], e["type"], e["data"],
                             e["ts"], e["actor"]) for e in self.events("feat/1-a")]
        requests = [r for r in rows if r.type == "go-requested"]
        self.assertEqual([module.request_session(r) for r in requests], ["A", "A"])
        self.assertEqual(
            [module.event_session(r) for r in rows
             if r.type in ("go-requested", "reply-witnessed")
             or r.data.get("source") in ("prompt", "read")],
            [None] * 5,
        )


class TestReadGoIsRetired(JournalTestCase):
    """#52, ADR 0023 amendment A3, A4, SC-013: the journal refuses a read go, with
    `--force` too, and a journal that holds one from 0.28.0 opens and authorizes nothing."""

    STREAM = "feat/1-x"
    FORCE = ("--force", "--force-reason", "x")

    def setUp(self):
        super().setUp()
        self.init_db()
        # No session label: session A writes only rows that bind no session.
        self.append_event(self.STREAM, "flow-started", {"request": "x"})

    def witness(self, gate="commit", session="A"):
        self.journal("--db", self.db, "append", "--stream", self.STREAM, "--type",
                     "go-requested", "--data", json.dumps({"gate": gate, "question": "q"}),
                     session_env=session, rc=OK)
        request = self.events(self.STREAM)[-1]["seq"]
        self.append_event(self.STREAM, "reply-witnessed", {
            "request": request, "gate": gate, "via": "prompt", "session": session,
        }, "--actor", "hook")
        return self.events(self.STREAM)[-1]["seq"]

    def test_a_read_go_is_refused_with_force_too_and_names_the_confirming_question(self):
        witness = self.witness()
        before = len(self.events(self.STREAM))
        for source in ("read", "Read", " READ "):
            for actor in ((), ("--actor", "user"), ("--actor", "orchestrator")):
                for force in ((), self.FORCE):
                    with self.subTest(source=source, actor=actor, force=bool(force)):
                        data = {**legacy_read_go("commit", witness), "source": source}
                        proc = self.journal(
                            "--db", self.db, "append", "--stream", self.STREAM,
                            "--type", "gate-decision", "--data", json.dumps(data),
                            *actor, *force, session_env="A", rc=GATE)
                        self.assertIn("confirming question", proc.stderr)
                        self.assertIn("Commit", proc.stderr)
        self.assertEqual(len(self.events(self.STREAM)), before)

    def test_a_read_marker_in_a_batch_is_refused(self):
        witness = self.witness()
        line = json.dumps({"type": "gate-decision",
                           "data": legacy_read_go("publish", witness)})
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "app" "end", "--stream",
             self.STREAM, "--batch"],
            input=line + "\n", capture_output=True, text=True, cwd=str(self.root),
        )
        self.assertEqual(proc.returncode, GATE, proc.stderr)
        self.assertIn("confirming question", proc.stderr)

    def test_a_journal_with_a_read_go_of_0_28_0_opens_and_authorizes_nothing(self):
        witness = self.witness()
        legacy = insert_legacy_row(self.db, self.STREAM, "gate-decision",
                                   legacy_read_go("commit", witness), "orchestrator@A")
        self.assertEqual(self.events(self.STREAM)[-1]["seq"], legacy)
        feature = next(f for f in self.status_json()["features"]
                       if f["stream"] == self.STREAM)
        self.assertEqual(feature["go"]["commit"], {"kind": "held"})
        self.assertEqual(feature["publish"], {"kind": "held"})
        self.journal("--db", self.db, "status", rc=OK)
        stats = json.loads(self.journal("--db", self.db, "stats", "--json",
                                        rc=OK).stdout)
        self.assertEqual(sum(stats["totals"]["go"].values()), 0)
        self.assertNotIn("read", stats["totals"]["go"])
        answer = json.loads(self.journal("--db", self.db, "authorize", "--gate", "commit",
                                         "--branch", self.STREAM, "--json",
                                         rc=OK).stdout)
        self.assertEqual(answer["verdict"], "hold")
        # The old row still binds no session (ADR 0023 §13).
        self.assertIsNone(self.status_json("--session", "A")["session_match"])


class TestReplyPlan(JournalTestCase):
    """ADR 0023 §4-§10, SC-002, SC-003: `reply` plans the rows a reply gives, and writes
    nothing."""

    def setUp(self):
        super().setUp()
        self.init_db()
        for stream in ("feat/1-a", "feat/2-b", "feat/3-c", "feat/4-d", "feat/5-e"):
            self.append_event(stream, "flow-started", {"request": "x"},
                              "--actor", "orchestrator@B")

    def request(self, stream, gate="commit", session="A", question="Commit it?"):
        self.journal("--db", self.db, "append", "--stream", stream, "--type",
                     "go-requested", "--data",
                     json.dumps({"gate": gate, "question": question}),
                     session_env=session, rc=OK)
        return self.events(stream)[-1]["seq"]

    def reply(self, payload, session="A", rc=OK):
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "reply", "--session",
             session, "--json"],
            input=json.dumps(payload), capture_output=True, text=True,
            cwd=str(self.root), env=env,
        )
        self.assertEqual(proc.returncode, rc, msg=proc.stderr)
        return json.loads(proc.stdout) if rc == OK else proc

    def prompt(self, text, session="A"):
        return self.reply({"via": "prompt", "text": text, "prompt_id": "p-1"}, session)

    def write(self, plan, session="A"):
        lines = "\n".join(json.dumps({k: e[k] for k in ("stream", "type", "data", "actor")})
                          for e in plan["events"])
        env = {k: v for k, v in os.environ.items() if k != SESSION_ENV}
        env[SESSION_ENV] = session
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "append", "--batch",
             "--json", "--stream", plan["events"][0]["stream"]],
            input=lines + "\n", capture_output=True, text=True, cwd=str(self.root),
            env=env,
        )
        self.assertEqual(proc.returncode, OK, msg=proc.stderr)
        return json.loads(proc.stdout)

    def gos(self, plan):
        return [(e["stream"], e["data"]["gate"], e["data"]["source"], e["actor"])
                for e in plan["events"] if e["type"] == "gate-decision"]

    def witnesses(self, plan):
        return [(e["stream"], e["data"]["gate"], e["data"]["via"], e["actor"])
                for e in plan["events"] if e["type"] == "reply-witnessed"]

    def test_the_exact_words_of_sc_002_each_give_one_go(self):
        for text, gate in (("commit", "commit"), ("Commit.", "commit"),
                           ("  COMMIT! ", "commit"), ("publish", "publish"),
                           ("push", "publish")):
            with self.subTest(text=text):
                request = self.request("feat/1-a", gate=gate)
                plan = self.prompt(text)
                self.assertEqual(self.gos(plan), [("feat/1-a", gate, "prompt", "user")])
                self.assertEqual(plan["events"][0]["data"]["request"], request)
                self.assertEqual(plan["events"][0]["data"]["decision"], gate)
                self.assertEqual(plan["events"][0]["data"]["raised_by"], "user")
                self.assertEqual(plan["recorded"],
                                 [{"stream": "feat/1-a", "gate": gate, "request": request}])
                self.assertEqual(self.witnesses(plan), [])
                self.write(plan)

    def test_free_language_and_no_each_give_one_witness_and_no_go(self):
        for text in ("it can go", "no", None):
            with self.subTest(text=text):
                request = self.request("feat/1-a")
                plan = self.prompt(text)
                self.assertEqual(self.gos(plan), [])
                self.assertEqual(self.witnesses(plan),
                                 [("feat/1-a", "commit", "prompt", "hook")])
                data = plan["events"][0]["data"]
                self.assertEqual(data, {"request": request, "gate": "commit",
                                        "via": "prompt", "session": "A",
                                        "prompt_id": "p-1"})
                self.assertConfirmingQuestion(plan["context"], "commit", "feat/1-a")
                self.write(plan)

    def assertConfirmingQuestion(self, context, gate, stream):
        """SC-018: the line asks for a new go request and one confirming question with
        the gate header, and names no witness seq and no read go."""
        self.assertIn("one confirming question", context)
        self.assertIn(f"header `{gate.capitalize()}`", context)
        self.assertIn(f"`{gate.capitalize()}` as the first option", context)
        self.assertIn("go-requested", context)
        self.assertIn(stream, context)
        self.assertIn("did not confirm", context)
        self.assertNotIn("<seq:", context)
        self.assertNotRegex(context, r"\bread\b")

    def test_a_free_text_question_answer_asks_for_a_confirming_question(self):
        """SC-018, the question path: "it can go" typed into the gate question's free-text
        row arrives as the answer under the gate header."""
        for gate in ("commit", "publish"):
            with self.subTest(gate=gate):
                self.request("feat/1-a", gate=gate)
                plan = self.question([{"header": gate.capitalize(),
                                       "answer": "it can go"}])
                self.assertEqual(self.gos(plan), [])
                self.assertEqual(self.witnesses(plan),
                                 [("feat/1-a", gate, "question", "hook")])
                self.assertConfirmingQuestion(plan["context"], gate, "feat/1-a")
                self.write(plan)

    def test_all_answers_five_requests_in_one_run(self):
        """SC-003."""
        streams = ["feat/1-a", "feat/2-b", "feat/3-c", "feat/4-d", "feat/5-e"]
        for stream in streams:
            self.request(stream)
        plan = self.prompt("all")
        self.assertEqual(sorted(s for s, *_ in self.gos(plan)), streams)
        self.assertEqual(plan["open"], 0)
        results = self.write(plan)
        self.assertEqual(len(results), 5)
        for stream in streams:
            go = self.status_json()["features"]
            self.assertEqual(
                next(f for f in go if f["stream"] == stream)["go"]["commit"]["kind"],
                "authorized")

    def test_a_gate_word_answers_its_gate_and_witnesses_the_others(self):
        self.request("feat/1-a", gate="commit")
        self.request("feat/2-b", gate="publish")
        plan = self.prompt("commit")
        self.assertEqual(self.gos(plan), [("feat/1-a", "commit", "prompt", "user")])
        self.assertEqual(self.witnesses(plan), [("feat/2-b", "publish", "prompt", "hook")])

    def test_the_request_of_another_session_stays_open(self):
        self.request("feat/1-a", session="B")
        self.assertEqual(self.prompt("yes")["events"], [])
        self.assertEqual(self.prompt("it can go")["events"], [])
        plan = self.prompt("yes", session="B")
        self.assertEqual(self.gos(plan), [("feat/1-a", "commit", "prompt", "user")])

    def test_a_gate_word_with_no_request_goes_to_the_driven_stream(self):
        self.append_event("feat/3-c", "phase-entered", {"phase": "implement",
                          "skipped": ["workspace", "route-and-map", "explore", "clarify",
                                      "design"]}, "--actor", "orchestrator@A")
        plan = self.prompt("commit")
        self.assertEqual(self.gos(plan), [("feat/3-c", "commit", "prompt", "user")])
        self.assertNotIn("request", plan["events"][0]["data"])
        self.write(plan)
        commit = next(f for f in self.status_json()["features"]
                      if f["stream"] == "feat/3-c")["go"]["commit"]
        self.assertEqual(commit["kind"], "authorized")

    def test_other_text_with_no_request_plans_nothing(self):
        self.append_event("feat/3-c", "deviation", {"note": "n"}, "--actor",
                          "orchestrator@A")
        for text in ("yes", "all", "it can go", None, "ok"):
            with self.subTest(text=text):
                plan = self.prompt(text)
                self.assertEqual(plan["events"], [])
                self.assertIsNone(plan["context"])

    def test_a_gate_word_with_no_request_and_no_driven_stream_plans_nothing(self):
        self.assertEqual(self.prompt("commit")["events"], [])

    def test_a_witnessed_request_takes_no_later_yes(self):
        self.request("feat/1-a")
        self.write(self.prompt("it can go"))
        plan = self.prompt("yes")
        self.assertEqual(plan["events"], [])
        self.assertEqual(plan["open"], 0)

    def test_no_output_holds_the_prompt_text(self):
        self.request("feat/1-a")
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "reply", "--session",
             "A", "--json"],
            input=json.dumps({"via": "prompt", "text": "ship zebra-quartz now",
                              "prompt_id": "p"}),
            capture_output=True, text=True, cwd=str(self.root),
        )
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertNotIn("zebra", proc.stdout + proc.stderr)

    def test_reply_writes_nothing(self):
        self.request("feat/1-a")
        before = len(self.events())
        self.prompt("commit")
        self.prompt("it can go")
        self.assertEqual(len(self.events()), before)

    def question(self, answers, session="A"):
        return self.reply({"via": "question", "answers": answers, "tool_use_id": "t-1",
                           "prompt_id": "p-1"}, session)

    def test_a_stream_label_counts_only_in_a_multi_select(self):
        """ADR 0023 §5. Security review T021, finding 2: a single-select label or a typed
        answer that names a stream after a refusal is no go."""
        self.request("feat/1-a", gate="publish")
        for answers in ([{"header": "Publish", "answer": "Not yet, feat/1-a"}],
                        [{"header": "Publish", "answer": "no, feat/1-a",
                          "multi_select": False}],
                        [{"header": "Publish", "answer": "feat/1-a"}]):
            with self.subTest(answers=answers):
                plan = self.question(answers)
                self.assertEqual(self.gos(plan), [])
                self.assertEqual(self.witnesses(plan),
                                 [("feat/1-a", "publish", "question", "hook")])

    def test_a_question_answer_that_is_the_gate_word_is_a_go(self):
        request = self.request("feat/1-a")
        plan = self.question([{"header": "Commit", "answer": "Commit"}])
        self.assertEqual(self.gos(plan), [("feat/1-a", "commit", "question", "user")])
        self.assertEqual(plan["events"][0]["data"]["request"], request)

    def test_selected_stream_labels_are_a_go_for_those_streams(self):
        for stream in ("feat/1-a", "feat/2-b", "feat/3-c"):
            self.request(stream, gate="publish")
        plan = self.question([{"header": "Publish", "answer": "feat/1-a, feat/3-c",
                               "multi_select": True}])
        self.assertEqual(sorted(self.gos(plan)), [
            ("feat/1-a", "publish", "question", "user"),
            ("feat/3-c", "publish", "question", "user"),
        ])
        self.assertEqual(self.witnesses(plan),
                         [("feat/2-b", "publish", "question", "hook")])

    def test_any_other_answer_witnesses_every_open_request(self):
        self.request("feat/1-a")
        for answers in ([{"header": "Commit", "answer": "Not yet"}],
                        [{"header": "Design", "answer": "Option A"}],
                        [{"header": "Commit", "answer": None}],
                        [{"header": "Publish", "answer": "Commit"}]):
            with self.subTest(answers=answers):
                plan = self.question(answers)
                self.assertEqual(self.gos(plan), [])
                self.assertEqual(self.witnesses(plan),
                                 [("feat/1-a", "commit", "question", "hook")])
                self.assertEqual(plan["events"][0]["data"]["tool_use_id"], "t-1")

    def test_a_general_word_is_no_exact_go_in_a_question(self):
        self.request("feat/1-a")
        plan = self.question([{"header": "Commit", "answer": "yes"}])
        self.assertEqual(self.gos(plan), [])

    def test_the_confirming_question_records_the_click(self):
        """SC-012 at the journal: the witness of "it can go", the go request the context
        prints, then the click `Commit` under the header `Commit`: one question go that
        names the new request, and the commit gate opens."""
        import shlex
        self.request("feat/1-a", question="Commit T003? it's done")
        witnessed = self.prompt("it can go")
        self.write(witnessed)
        context = witnessed["context"]
        # The witness closed the first request: a later reply answers nothing.
        self.assertEqual(self.prompt("it can go")["events"], [])
        command = re.search(r"`(python3 [^`]+ append [^`]+)`", context).group(1)
        argv = shlex.split(command)
        self.assertEqual(Path(argv[1]).resolve(), JOURNAL.resolve())
        self.assertEqual(Path(argv[argv.index("--db") + 1]).resolve(), self.db.resolve())
        self.assertEqual(argv[argv.index("--type") + 1], "go-requested")
        data = json.loads(argv[argv.index("--data") + 1])
        self.assertEqual(data["gate"], "commit")
        data["question"] = "Commit T003 now?"
        argv[argv.index("--data") + 1] = json.dumps(data)
        self.journal(*argv[2:], session_env="A", rc=OK)
        confirming = self.events("feat/1-a")[-1]["seq"]
        click = self.question([{"header": "Commit", "answer": "Commit"}])
        self.assertEqual(self.gos(click), [("feat/1-a", "commit", "question", "user")])
        self.assertEqual(click["events"][0]["data"]["request"], confirming)
        self.write(click)
        commit = next(f for f in self.status_json()["features"]
                      if f["stream"] == "feat/1-a")["go"]["commit"]
        self.assertEqual(commit["seq"], self.events("feat/1-a")[-1]["seq"])

    def test_the_go_request_command_names_the_db_and_a_dash_leading_stream_safely(self):
        """Review round 1, F3: the command goes through `_suggest`."""
        self.journal("--db", self.db, "append", "--stream=-odd", "--type", "flow-started",
                     "--data", json.dumps({"request": "x"}), rc=OK)
        self.journal("--db", self.db, "append", "--stream=-odd", "--type", "go-requested",
                     "--data", json.dumps({"gate": "commit", "question": "q"}),
                     session_env="A", rc=OK)
        plan = self.prompt("it can go")
        self.assertIn("--db", plan["context"])
        self.assertIn(str(self.db), plan["context"])
        self.assertIn("--stream=-odd", plan["context"])
        self.assertIn("--type go-requested", plan["context"])

    def test_a_push_answer_under_the_publish_header_is_a_go(self):
        """Review round 1, F15: a question answer reads the gate words as a prompt does."""
        self.request("feat/1-a", gate="publish")
        plan = self.question([{"header": "Publish", "answer": "Push"}])
        self.assertEqual(self.gos(plan), [("feat/1-a", "publish", "question", "user")])

    def test_the_context_names_what_was_recorded(self):
        self.request("feat/1-a")
        plan = self.prompt("commit")
        self.assertIn("go recorded for commit on feat/1-a", plan["context"])

    def test_bad_input_is_a_usage_error(self):
        for payload in ([], {"via": "mail"}, {"via": "question", "answers": "x"}):
            with self.subTest(payload=payload):
                self.reply(payload, rc=USAGE)

    def test_a_finished_streams_request_is_not_open(self):
        self.request("feat/1-a")
        self.append_event("feat/1-a", "flow-completed", {})
        self.assertEqual(self.prompt("commit")["events"], [])


class TestAuthorize(JournalTestCase):
    """ADR 0023 §14-§16, FR-015-FR-017: the command gate's answer for a branch."""

    STREAM = "feat/1-x"

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event(self.STREAM, "flow-started", {"request": "x"},
                          "--actor", "orchestrator@A")
        self.append_event(self.STREAM, "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event(self.STREAM, "task-done", {"task_id": "T001"})

    def authorize(self, gate="commit", branch=None, *extra):
        proc = self.journal("--db", self.db, "authorize", "--gate", gate, "--branch",
                            branch or self.STREAM, "--json", *extra, rc=OK)
        return json.loads(proc.stdout)

    def go(self, gate="commit", source="question"):
        self.append_event(self.STREAM, "gate-decision", {
            "gate": gate, "question": "q", "decision": gate, "mode": "ask",
            "raised_by": "user", "source": source}, "--actor", "user")

    def witness(self, gate="commit", session="A"):
        self.journal("--db", self.db, "append", "--stream", self.STREAM, "--type",
                     "go-requested", "--data", json.dumps({"gate": gate, "question": "q"}),
                     session_env=session, rc=OK)
        request = self.events(self.STREAM)[-1]["seq"]
        self.append_event(self.STREAM, "reply-witnessed", {
            "request": request, "gate": gate, "via": "prompt", "session": session,
        }, "--actor", "hook")
        return self.events(self.STREAM)[-1]["seq"]

    def assertAnswer(self, answer, verdict, reason, gate="commit"):
        self.assertEqual((answer["verdict"], answer["reason"]), (verdict, reason))
        self.assertEqual(answer["gate"], gate)
        self.assertIsInstance(answer["message"], str)

    def test_a_branch_with_no_stream_passes(self):
        self.assertAnswer(self.authorize(branch="feat/9-other"), "pass", "no-stream")
        self.assertIsNone(self.authorize(branch="main")["stream"])

    def test_a_finished_stream_passes(self):
        self.append_event(self.STREAM, "flow-completed", {})
        answer = self.authorize()
        self.assertAnswer(answer, "pass", "not-live")
        self.assertEqual(answer["stream"], self.STREAM)

    def test_no_go_holds_and_names_the_ways_forward(self):
        for gate in ("commit", "publish"):
            with self.subTest(gate=gate):
                answer = self.authorize(gate)
                self.assertAnswer(answer, "hold", "no-go", gate)
                self.assertEqual(answer["stream"], self.STREAM)
                message = answer["message"]
                self.assertIn(self.STREAM, message)
                self.assertIn(gate, message)
                self.assertIn("go-requested", message)
                self.assertIn("type", message)
                self.assertNotIn("read go", message)

    def test_a_ready_verdict_alone_holds(self):
        self.append_event(self.STREAM, "verify-run",
                          {"commands": [{"cmd": "make test", "exit": 0}],
                           "outcome": "pass", "task_ids": ["T001"]})
        self.append_event(self.STREAM, "review-verdict", {"verdict": "ready"})
        self.assertAnswer(self.authorize("commit"), "hold", "no-go")
        self.assertAnswer(self.authorize("publish"), "hold", "no-go", "publish")

    def test_a_commit_go_authorizes_the_commit_only(self):
        self.go("commit")
        self.assertAnswer(self.authorize("commit"), "pass", "authorized")
        self.assertAnswer(self.authorize("publish"), "hold", "no-go", "publish")

    def test_a_publish_go_authorizes_both(self):
        self.go("publish", source="prompt")
        self.assertAnswer(self.authorize("commit"), "pass", "authorized")
        self.assertAnswer(self.authorize("publish"), "pass", "authorized", "publish")

    def test_a_waiting_witness_holds_and_asks_for_one_confirming_question(self):
        """#52, amendment A5."""
        self.witness()
        answer = self.authorize()
        self.assertAnswer(answer, "hold", "witness-waits")
        message = answer["message"]
        self.assertIn("no exact go", message)
        self.assertIn("one confirming question", message)
        self.assertIn("header `Commit`", message)
        self.assertIn("--type go-requested", message)
        self.assertIn("--db", message)
        self.assertNotIn('"source"', message)
        self.assertNotIn("read go", message)
        self.assertNotIn("witness seq", message)
        # Security recheck, finding 3: the message names no session id.
        self.assertNotIn("session A", answer["message"])
        self.assertNotIn("(session", answer["message"])

    def test_an_old_read_go_holds_and_the_confirming_click_authorizes(self):
        """#52: a read go of 0.28.0 opens nothing; the click on the confirming question
        does."""
        witness = self.witness()
        insert_legacy_row(self.db, self.STREAM, "gate-decision",
                          legacy_read_go("commit", witness), "orchestrator@A")
        self.assertAnswer(self.authorize(), "hold", "witness-waits")
        self.journal("--db", self.db, "append", "--stream", self.STREAM, "--type",
                     "go-requested", "--data",
                     json.dumps({"gate": "commit", "question": "Commit now?"}),
                     session_env="A", rc=OK)
        self.go("commit")
        self.assertAnswer(self.authorize(), "pass", "authorized")

    def test_the_branch_finds_its_stream_by_the_usual_candidates(self):
        self.append_event("feature/2-y", "flow-started", {"request": "y"})
        answer = self.authorize(branch="fix/2-y")
        self.assertAnswer(answer, "hold", "no-go")
        self.assertEqual(answer["stream"], "feature/2-y")

    def test_a_subagent_is_told_to_hand_the_question_back(self):
        answer = self.authorize("commit", None, "--subagent")
        self.assertAnswer(answer, "hold", "no-go")
        self.assertIn("subagent", answer["message"])
        self.assertIn("hand the question back", answer["message"])
        self.assertNotIn("hand the question back", self.authorize()["message"])

    def test_a_missing_journal_is_an_infrastructure_error(self):
        proc = self.journal("--db", self.root / "none.db", "authorize", "--gate",
                            "commit", "--branch", "x", "--json")
        self.assertEqual(proc.returncode, INFRA)


class TestStatsGoMarkers(JournalTestCase):
    """ADR 0023 §19, SC-017: `stats --json` counts the go records by marker."""

    MARKERS = ("dialog", "shell", "question", "prompt")

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})

    def go(self, source, gate="commit", decision=None, actor="user", **extra):
        self.journal("--db", self.db, "append", "--stream", "feat/1-x", "--type",
                     "gate-decision", "--actor", actor, "--data", json.dumps({
                         "gate": gate, "question": "q", "decision": decision or gate,
                         "mode": "ask", "raised_by": "user", "source": source,
                         **extra}),
                     session_env="A", rc=OK)

    def stats(self):
        return json.loads(self.journal("--db", self.db, "stats", "--json",
                                       rc=OK).stdout)

    def test_every_marker_is_counted(self):
        self.assertEqual(self.stats()["totals"]["go"], dict.fromkeys(self.MARKERS, 0))
        self.go("question")
        self.go("question", gate="publish")
        self.go("prompt")
        self.go("dialog", gate="publish")
        self.journal("--db", self.db, "app" "end", "--stream", "feat/1-x", "--type",
                     "go-requested", "--data",
                     json.dumps({"gate": "commit", "question": "q"}),
                     session_env="A", rc=OK)
        request = self.events("feat/1-x")[-1]["seq"]
        self.append_event("feat/1-x", "reply-witnessed", {
            "request": request, "gate": "commit", "via": "prompt", "session": "A",
        }, "--actor", "hook")
        # A read go of 0.28.0 is no go any more (#52), so it is not counted.
        insert_legacy_row(self.db, "feat/1-x", "gate-decision",
                          legacy_read_go("commit", self.events("feat/1-x")[-1]["seq"]),
                          "orchestrator@A")
        # A row at the gate that is no go is not counted.
        self.go("shell", decision="hold")
        stats = self.stats()
        expected = {"dialog": 1, "shell": 0, "question": 2, "prompt": 1}
        self.assertEqual(stats["totals"]["go"], expected)
        row = next(r for r in stats["streams"] if r["stream"] == "feat/1-x")
        self.assertEqual(row["go"], expected)


class TestRequestMarker(JournalTestCase):
    """ADR 0023 §12: a go request leaves an empty marker file for its session."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})
        self.markers = Path(str(self.db) + ".requests")

    def request(self, session=None, actor=None, rc=OK):
        args = ["--db", self.db, "append", "--stream", "feat/1-x", "--type",
                "go-requested", "--data", json.dumps({"gate": "commit", "question": "q"})]
        if actor:
            args += ["--actor", actor]
        return self.journal(*args, session_env=session, rc=rc)

    def test_the_appending_session_gets_an_empty_marker(self):
        self.request(session="sess-A_1")
        marker = self.markers / "sess-A_1"
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_bytes(), b"")

    def test_a_label_that_names_the_shells_session_is_that_session(self):
        self.request(session="B", actor="orchestrator@B")
        self.assertEqual(sorted(p.name for p in self.markers.iterdir()), ["B"])

    def test_a_session_id_outside_the_pattern_gets_no_file(self):
        for session in ("a/b", "..", "x y"):
            with self.subTest(session=session):
                self.request(session=session)
        self.assertFalse(self.markers.exists() and any(self.markers.iterdir()))
        self.assertFalse((self.root / "b").exists())

    def test_no_session_gets_no_file(self):
        self.request()
        self.assertFalse(self.markers.exists())

    def test_an_unwritable_marker_directory_warns_and_still_appends(self):
        self.markers.write_text("not a directory", encoding="utf-8")
        proc = self.request(session="A")
        self.assertEqual(self.events("feat/1-x")[-1]["type"], "go-requested")
        warnings = [line for line in proc.stderr.splitlines() if line.strip()]
        self.assertEqual(len(warnings), 1, proc.stderr)
        self.assertIn("marker", warnings[0])

    def test_reply_prints_the_open_count(self):
        self.request(session="A")
        proc = subprocess.run(
            [sys.executable, str(JOURNAL), "--db", str(self.db), "reply", "--session",
             "A", "--json"],
            input=json.dumps({"via": "prompt", "text": "commit"}),
            capture_output=True, text=True, cwd=str(self.root),
        )
        self.assertEqual(json.loads(proc.stdout)["open"], 0)


class TestApprovalRowsNameTheirOwnSession(JournalTestCase):
    """Security review T021, finding 3: a go request counts for the session that appends
    it, so an actor label that names another session is refused."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feat/1-x", "flow-started", {"request": "x"})

    def append_as(self, session, *args, rc=OK):
        return self.journal("--db", self.db, "append", "--stream", "feat/1-x", *args,
                            session_env=session, rc=rc)

    def test_a_label_with_no_session_in_the_shell_is_refused(self):
        """Review round 2, N2: with CLAUDE_CODE_SESSION_ID empty, a label names a session
        no one can check, so a go request may not carry one."""
        for force in ((), ("--force", "--force-reason", "x")):
            with self.subTest(force=bool(force)):
                proc = self.journal(
                    "--db", self.db, "append", "--stream", "feat/1-x", "--type",
                    "go-requested", "--actor", "orchestrator@A", "--data",
                    json.dumps({"gate": "commit", "question": "q"}), *force, rc=GATE)
                self.assertIn("CLAUDE_CODE_SESSION_ID", proc.stderr)
        self.journal("--db", self.db, "append", "--stream", "feat/1-x", "--type",
                     "go-requested", "--data",
                     json.dumps({"gate": "commit", "question": "q"}), rc=OK)

    def test_a_go_request_labelled_with_another_session_is_refused(self):
        for force in ((), ("--force", "--force-reason", "x")):
            with self.subTest(force=bool(force)):
                proc = self.append_as(
                    "B", "--type", "go-requested", "--actor", "orchestrator@A", "--data",
                    json.dumps({"gate": "commit", "question": "q"}), *force, rc=GATE)
                self.assertIn("another session", proc.stderr)
        self.append_as("A", "--type", "go-requested", "--actor", "orchestrator@A",
                       "--data", json.dumps({"gate": "commit", "question": "q"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
