#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: payload shapes.

Validation, location keys and terminal payloads. Split out of ``test_journal.py`` (#61),
which holds the helpers and fixtures.
"""

from __future__ import annotations

import json
import unittest

from test_journal import GATE, JournalTestCase, load_journal_module, OK


class TestShapeValidation(JournalTestCase):
    """Payloads are normalized before any gate runs, so gates read canonical keys."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def data_of(self, stream="feature/x"):
        return self.events(stream)[-1]["data"]

    def test_a_missing_required_key_is_a_gate_violation(self):
        proc = self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "decision": "d",
        }, rc=GATE)
        self.assertIn("mode", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_the_violation_prints_the_canonical_shape(self):
        proc = self.append_event("feature/x", "deviation", {}, rc=GATE)
        self.assertIn("vocab --shape deviation", proc.stderr)
        self.assertIn("note", proc.stderr)

    def test_a_value_outside_the_enum_is_a_gate_violation(self):
        proc = self.append_event("feature/x", "verify-run", {
            "outcome": "green", "task_ids": ["T001"],
        }, rc=GATE)
        self.assertIn("outcome", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_list_key_must_hold_a_list(self):
        proc = self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": "T001"}, rc=GATE
        )
        self.assertIn("task_ids", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_key_aliases_are_stored_canonically(self):
        self.append_event(
            "feature/x", "verify-run", {"result": "pass", "tasks": ["T001"]}
        )
        data = self.data_of()
        self.assertEqual(data["outcome"], "pass")
        self.assertEqual(data["task_ids"], ["T001"])
        self.assertNotIn("result", data)
        self.assertNotIn("tasks", data)

    def test_a_canonical_key_alone_is_left_untouched(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        data = self.data_of()
        self.assertEqual(data["outcome"], "pass")
        self.assertEqual(data["task_ids"], ["T001"])

    def test_a_key_and_its_alias_together_are_refused(self):
        """Which one did the caller mean? Resolving it would drop a real value."""
        proc = self.append_event(
            "feature/x", "verify-run",
            {"outcome": "pass", "result": "fail", "task_ids": ["T001"]},
            rc=GATE,
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("outcome", combined)
        self.assertIn("result", combined)
        self.assertEqual(self.events(), [])

    def test_two_aliases_of_one_key_are_refused(self):
        proc = self.append_event(
            "feature/x", "deviation", {"correction": "a", "what": "b"}, rc=GATE
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("correction", combined)
        self.assertIn("what", combined)
        self.assertEqual(self.events(), [])

    def test_gate_decision_aliases_are_stored_canonically(self):
        self.append_event("feature/x", "gate-decision", {
            "kind": "design", "question": "q", "chosen": "sqlite", "mode": "ask",
        })
        data = self.data_of()
        self.assertEqual(data["gate"], "design")
        self.assertEqual(data["decision"], "sqlite")
        self.assertNotIn("kind", data)
        self.assertNotIn("chosen", data)

    def test_value_aliases_are_stored_canonically(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "fail"})
        self.assertEqual(self.data_of()["verdict"], "not-ready")

    def test_defaults_are_filled_in(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "decision": "d", "mode": "executive",
        })
        self.assertEqual(self.data_of()["raised_by"], "orchestrator")

    def test_an_explicitly_given_default_is_kept(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "decision": "d", "mode": "ask",
            "raised_by": "user",
        })
        self.assertEqual(self.data_of()["raised_by"], "user")

    def test_force_does_not_waive_the_shape(self):
        """--force skips gate preconditions; it does not make a payload readable."""
        self.append_event("feature/x", "deviation", {}, "--force", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_list_valued_decision_is_refused(self):
        """Each reader stringified a list its own way, so one authorized a publish the
        other refused (audit D6)."""
        proc = self.append_event("feature/x", "gate-decision", {
            "gate": "publish", "question": "q", "decision": ["publish"],
            "mode": "ask", "raised_by": "user",
        }, rc=GATE)
        self.assertIn("data.decision must be a string", proc.stderr)
        self.assertIn("vocab --shape gate-decision", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_an_object_valued_decision_is_refused(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "decision": {"pick": "a"}, "mode": "ask",
        }, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_decision_given_under_its_alias_must_be_a_string_too(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "chosen": ["a"], "mode": "ask",
        }, rc=GATE)
        self.assertEqual(self.events(), [])

    # `review-verdict` closes its two maps' vocabularies (ADR 0009, T016).
    def verdict(self, rc=OK, **maps):
        return self.append_event("feature/x", "review-verdict",
                                 dict(maps, verdict="not-ready"), rc=rc)

    def test_the_verdict_maps_accept_their_vocabularies(self):
        self.verdict(
            criteria={"SC-001": "met", "SC-002": "unmet"},
            dispositions={"a.py:1": "fixed", "b.py:?": "rejected", "c.py:3": "deferred"},
        )
        self.assertEqual(self.data_of()["criteria"]["SC-002"], "unmet")

    def test_a_criterion_status_outside_the_vocabulary_is_refused(self):
        for status in ("Met", "partial", "", None, ["met"]):
            with self.subTest(status=status):
                proc = self.verdict(criteria={"SC-001": status}, rc=GATE)
                self.assertIn("data.criteria", proc.stderr)
                self.assertIn("met, unmet", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_disposition_outside_the_vocabulary_is_refused(self):
        proc = self.verdict(dispositions={"a.py:1": "fixed", "b.py:2": "wontfix"},
                            rc=GATE)
        self.assertIn("data.dispositions", proc.stderr)
        self.assertIn("fixed, rejected, deferred", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_verdict_map_must_be_an_object(self):
        self.verdict(criteria=["SC-001"], rc=GATE)
        self.verdict(dispositions="fixed", rc=GATE)
        self.assertEqual(self.events(), [])

    # `security_review` says which security review ran and what it read (#40).
    def test_a_verdict_records_the_security_review_that_ran(self):
        for review in (
            {"kind": "briefed", "files": 8},
            {"kind": "builtin", "files": 8, "ref": "0123abc"},
            {"kind": "none"},
            {"kind": "none", "files": 0},
        ):
            with self.subTest(review=review):
                self.verdict(security_review=review)
                self.assertEqual(self.data_of()["security_review"], review)

    def test_a_security_review_kind_outside_the_vocabulary_is_refused(self):
        for review in ({"kind": "full", "files": 3}, {"files": 3}, {"kind": ""}):
            with self.subTest(review=review):
                proc = self.verdict(security_review=review, rc=GATE)
                self.assertIn("data.security_review", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_security_review_must_be_an_object_with_an_integer_count(self):
        self.verdict(security_review="builtin", rc=GATE)
        for files in (-1, "8", True, 2.5):
            with self.subTest(files=files):
                proc = self.verdict(
                    security_review={"kind": "briefed", "files": files}, rc=GATE)
                self.assertIn("data.security_review.files", proc.stderr)
        self.verdict(security_review={"kind": "builtin", "files": 1, "ref": 7}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_security_review_that_read_no_file_is_refused(self):
        """An empty diff reviews nothing; its "no finding" is no review (#40)."""
        for review in (
            {"kind": "builtin", "files": 0},
            {"kind": "briefed", "files": 0},
            {"kind": "briefed"},
        ):
            with self.subTest(review=review):
                proc = self.verdict(security_review=review, rc=GATE)
                self.assertIn("read no file", proc.stderr)
                self.assertIn('"kind": "none"', proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_builtin_security_review_names_its_commit(self):
        for review in (
            {"kind": "builtin", "files": 8},
            {"kind": "builtin", "files": 8, "ref": "  "},
        ):
            with self.subTest(review=review):
                proc = self.verdict(security_review=review, rc=GATE)
                self.assertIn("data.security_review.ref", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_force_does_not_waive_the_security_review_count(self):
        self.append_event("feature/x", "review-verdict", {
            "verdict": "ready", "security_review": {"kind": "builtin", "files": 0},
        }, "--force", "--force-reason", "test", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_vocab_prints_the_security_review_shape(self):
        shape = json.loads(self.journal(
            "--db", self.db, "vocab", "--shape", "review-verdict", rc=OK).stdout)
        sub = shape["objects"]["security_review"]
        self.assertEqual(sub["required"], ["kind"])
        self.assertEqual(sub["enums"]["kind"], ["builtin", "briefed", "none"])
        self.assertEqual(sub["integers"], ["files"])
        self.assertEqual(sub["strings"], ["ref"])

    # `review-disposition` records a finding's state when it is decided (ADR 0014).
    def disposition(self, rc=OK, **data):
        data.setdefault("dispositions", {"src/a.py:12": "fixing"})
        data.setdefault("round", 1)
        return self.append_event("feature/x", "review-disposition", data, rc=rc)

    def test_a_review_disposition_accepts_its_four_states(self):
        self.disposition(dispositions={
            "src/a.py:12": "fixing", "src/b.py:?": "fixed", "c.py:3": "rejected",
            "d.py:4": "deferred",
        }, round=2)
        data = self.data_of()
        self.assertEqual(data["dispositions"]["src/a.py:12"], "fixing")
        self.assertEqual(data["round"], 2)
        self.assertNotIn("note", data)

    def test_a_review_disposition_takes_an_optional_note(self):
        self.disposition(note="the fix is dispatched", round=0)
        self.assertEqual(self.data_of()["note"], "the fix is dispatched")

    def test_a_review_disposition_state_outside_the_vocabulary_is_refused(self):
        for state in ("wontfix", "Fixing", "", None, ["fixed"]):
            with self.subTest(state=state):
                proc = self.disposition(dispositions={"a.py:1": state}, rc=GATE)
                self.assertIn("data.dispositions", proc.stderr)
                self.assertIn("fixing, fixed, rejected, deferred", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_review_disposition_without_a_round_is_refused(self):
        proc = self.append_event("feature/x", "review-disposition",
                                 {"dispositions": {"a.py:1": "fixing"}}, rc=GATE)
        self.assertIn("round", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_review_disposition_round_must_be_a_non_negative_integer(self):
        for value in ("1", 1.5, 1.0, True, False, -1, [1], {"n": 1}):
            with self.subTest(round=value):
                proc = self.disposition(round=value, rc=GATE)
                self.assertIn("data.round must be a non-negative integer",
                              proc.stderr)
                self.assertIn("vocab --shape review-disposition", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_review_disposition_map_must_be_an_object(self):
        self.disposition(dispositions="fixing", rc=GATE)
        self.disposition(dispositions=None, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_review_disposition_note_must_be_a_string(self):
        self.disposition(note=["a"], rc=GATE)
        self.assertEqual(self.events(), [])

    # `labels` carries a human name beside a finding key (ADR 0014, amended 0.22.0).
    def test_a_review_disposition_takes_optional_labels(self):
        self.disposition(labels={"src/a.py:12": "null-guard"})
        self.assertEqual(self.data_of()["labels"], {"src/a.py:12": "null-guard"})
        self.disposition()
        self.assertNotIn("labels", self.data_of())

    def test_review_disposition_labels_must_be_an_object(self):
        for value in (["null-guard"], "null-guard", 3, None):
            with self.subTest(labels=value):
                proc = self.disposition(labels=value, rc=GATE)
                self.assertIn("data.labels must be a JSON object", proc.stderr)
                self.assertIn("vocab --shape review-disposition", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_each_review_disposition_label_must_be_a_non_empty_string(self):
        for value in (3, None, ["x"], {"x": 1}, True, "", "   "):
            with self.subTest(label=value):
                proc = self.disposition(labels={"src/a.py:12": value}, rc=GATE)
                self.assertIn(
                    "each value of data.labels must be a non-empty string", proc.stderr)
                self.assertIn("vocab --shape review-disposition", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_vocab_prints_the_labels_rule(self):
        proc = self.journal("--db", self.db, "vocab", "--shape", "review-disposition",
                            rc=OK)
        self.assertEqual(json.loads(proc.stdout)["string_maps"], ["labels"])

    # `source` marks a decision written outside the model's tools (ADR 0015).
    def test_a_gate_decision_takes_a_source_marker(self):
        for source in ("dialog", "shell"):
            with self.subTest(source=source):
                self.append_event("feature/x", "gate-decision", {
                    "gate": "publish", "question": "q", "decision": "publish",
                    "mode": "ask", "raised_by": "user", "source": source,
                }, "--actor", "user")
                self.assertEqual(self.data_of()["source"], source)

    def test_a_source_outside_the_enum_is_refused(self):
        # `read` in any case has its own refusal (#52, TestReadGoIsRetired).
        for source in ("hud", "Dialog", "", None, ["dialog"], True):
            with self.subTest(source=source):
                proc = self.append_event("feature/x", "gate-decision", {
                    "gate": "publish", "question": "q", "decision": "publish",
                    "mode": "ask", "raised_by": "user", "source": source,
                }, "--actor", "user", rc=GATE)
                self.assertIn(
                    "data.source must be one of dialog, shell, question, prompt,",
                    proc.stderr,
                )
        self.assertEqual(self.events(), [])

    # ADR 0023: the recorder's two markers and their key.
    def test_the_recorders_markers_and_the_request_key_are_accepted(self):
        for source in ("question", "prompt"):
            with self.subTest(source=source):
                self.append_event("feature/x", "gate-decision", {
                    "gate": "commit", "question": "q", "decision": "commit",
                    "mode": "ask", "raised_by": "user", "source": source,
                    "request": 7,
                }, "--actor", "user")
                self.assertEqual(self.data_of()["source"], source)
                self.assertEqual(self.data_of()["request"], 7)

    def test_the_read_marker_is_not_in_the_shape(self):
        """#52, ADR 0023 amendment A3: `read` is no marker any more."""
        module = load_journal_module()
        self.assertEqual(module.get_args(module.DecisionSource),
                         ("dialog", "shell", "question", "prompt"))
        self.assertNotIn("witness", module.EVENT_SHAPES["gate-decision"]["integers"])
        self.assertNotIn("words", module.EVENT_SHAPES["gate-decision"]["strings"])

    def test_request_must_be_a_non_negative_integer(self):
        for value in ("3", -1, True, 1.5, None):
            with self.subTest(value=value):
                proc = self.append_event("feature/x", "gate-decision", {
                    "gate": "scope", "question": "q", "decision": "d",
                    "mode": "ask", "request": value,
                }, rc=GATE)
                self.assertIn("data.request must be a non-negative integer",
                              proc.stderr)
        self.assertEqual(self.events(), [])

    # Every key of a finding map is a location (ADR 0014, amended 0.23.0).
    FREE_LABELS = ("F21", "flush-older-sync")

    def finding_map_appends(self, key):
        """One append per map that is keyed by a finding, each naming ``key``."""
        return [
            ("review-disposition.dispositions", "review-disposition",
             {"dispositions": {key: "fixing"}, "round": 1}),
            ("review-disposition.labels", "review-disposition",
             {"dispositions": {"src/a.ts:3": "fixing"}, "round": 1,
              "labels": {key: "a name"}}),
            ("review-verdict.dispositions", "review-verdict",
             {"verdict": "not-ready", "dispositions": {key: "fixed"}}),
        ]

    def test_a_free_label_key_is_refused_in_every_finding_map(self):
        for label in self.FREE_LABELS:
            for where, etype, data in self.finding_map_appends(label):
                with self.subTest(map=where, key=label):
                    proc = self.append_event("feature/x", etype, data, rc=GATE)
                    field = where.split(".", 1)[1]
                    self.assertIn(f"data.{field} has 1 key(s) that are not a finding "
                                  f"location: \"{label}\"", proc.stderr)
                    self.assertIn("`<path>:<line|?>`", proc.stderr)
                    self.assertIn("labels", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_location_keys_are_accepted_in_every_finding_map(self):
        for key in ("./src/a.ts:3", "src/a.ts:?", "src/a.ts:12"):
            for where, etype, data in self.finding_map_appends(key):
                with self.subTest(map=where, key=key):
                    self.append_event("feature/x", etype, data)
                    self.assertEqual(self.events()[-1]["type"], etype)

    def test_force_does_not_waive_the_location_key(self):
        for where, etype, data in self.finding_map_appends("F21"):
            with self.subTest(map=where):
                self.append_event("feature/x", etype, data, "--force",
                                  "--force-reason", "testing", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_the_refusal_names_five_bad_keys_and_counts_the_rest(self):
        bad = {f"F{n}": "fixing" for n in range(1, 8)}
        bad["src/a.ts:3"] = "fixing"
        proc = self.disposition(dispositions=bad, rc=GATE)
        self.assertIn("data.dispositions has 7 key(s)", proc.stderr)
        self.assertIn('"F5" and 2 more', proc.stderr)
        self.assertNotIn('"F6"', proc.stderr)
        self.assertNotIn("src/a.ts:3", proc.stderr.split("`<path>")[0])

    def test_an_imported_free_label_key_is_not_checked_again(self):
        raw = self.root / "old.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/x", "version": 1, "type": "review-disposition",
            "data": {"dispositions": {"F21": "fixing"}, "round": 1},
            "ts": "2026-10-01T09:00:00+00:00", "actor": "orchestrator",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        self.assertEqual(self.data_of()["dispositions"], {"F21": "fixing"})

    def test_a_review_disposition_implies_no_phase(self):
        """`fixing` is appended in the fix round, back in implement: an implied review
        would move the phase on every dispatch (ADR 0014)."""
        self.append_event("feature/x", "flow-started", {"request": "build it"})
        self.disposition()
        self.assertIsNone(self.status_json()["features"][0]["current"])
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T001"]})
        self.disposition(dispositions={"src/a.py:12": "fixed"})
        current = self.status_json()["features"][0]["current"]
        self.assertEqual(current["phase"], "implement")
        self.assertEqual([e["type"] for e in self.events("feature/x")], [
            "flow-started", "review-disposition", "phase-entered", "verify-run",
            "review-disposition",
        ])

    def test_force_does_not_waive_the_string_rule(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "publish", "question": "q", "decision": ["publish"], "mode": "ask",
        }, "--force", "--force-reason", "testing", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_shapeless_type_accepts_any_payload(self):
        self.append_event("watch/group-project!42", "baseline", {"iid": 42})
        self.assertEqual(len(self.events("watch/group-project!42")), 1)

    def test_import_bypasses_the_shape(self):
        """History replay must not be re-judged by today's shapes."""
        raw = self.root / "raw.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/z", "version": 1, "type": "gate-decision",
            "data": {"chosen": "sqlite"}, "ts": "2026-08-20T10:00:00+00:00",
            "actor": "sess-9",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        events = self.events("feature/z")
        self.assertEqual(events[0]["data"], {"chosen": "sqlite"})
        self.assertEqual(events[0]["actor"], "sess-9")


class TestIsLocationKey(unittest.TestCase):
    """The HUD's `parseLocation` grammar (shipgate-hud hooks/review.ts), in Python."""

    def setUp(self):
        self.journal = load_journal_module()

    def test_locations(self):
        for key in ("src/a.ts:3", "src/a.ts:?", "./src/a.ts:3", "././a.py:0",
                    "a:1", "C:/x/a.ts:12", "src/a b.ts:7", "a.ts:3:4", "/abs/a.ts:?"):
            with self.subTest(key=key):
                self.assertTrue(self.journal.is_location_key(key))

    def test_not_locations(self):
        for key in ("F21", "flush-older-sync", "", ":3", "./:3", "././:?",
                    "src/a.ts", "src/a.ts:", "src/a.ts:3a", "src/a.ts:-1",
                    "src/a.ts:??", "src/a.ts: 3", "src/a.ts:3 ", "src/a.ts:3\n",
                    "src/a.ts:\u0663", "src/a.ts:3:x", None, 3):
            with self.subTest(key=key):
                self.assertFalse(self.journal.is_location_key(key))


class TestTerminalPayloads(JournalTestCase):
    """T003, FR-021: `flow-completed` and `flow-abandoned` take `reason`, `evidence` and
    `url`, none required, so an old append still works."""

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feature/x", "flow-started", {"request": "x"})

    def test_an_empty_payload_still_closes_a_stream(self):
        for etype in ("flow-completed", "flow-abandoned"):
            with self.subTest(etype=etype):
                self.append_event("feature/x", etype, {})

    def test_the_three_string_keys_are_kept(self):
        data = {"reason": "merged", "evidence": "forge gh: MERGED 1a2b3c4",
                "url": "https://forge.invalid/o/r/pull/7"}
        self.append_event("feature/x", "flow-completed", data)
        self.assertEqual(self.events("feature/x")[-1]["data"], data)

    def test_a_list_reason_is_refused(self):
        for etype in ("flow-completed", "flow-abandoned"):
            with self.subTest(etype=etype):
                proc = self.append_event("feature/x", etype, {"reason": ["merged"]},
                                         rc=GATE)
                self.assertIn("data.reason must be a string", proc.stderr)

    def test_vocab_prints_the_shape(self):
        out = self.journal("vocab", "--shape", "flow-completed", rc=OK).stdout
        self.assertEqual(json.loads(out)["strings"], ["reason", "evidence", "url"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
