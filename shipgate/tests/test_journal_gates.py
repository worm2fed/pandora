#!/usr/bin/env python3
"""Tests of ``scripts/journal.py``: the gates of rules v1.

Each event type's precondition, and the implied phases. Split out of ``test_journal.py``
(#61), which holds the helpers and fixtures.
"""

from __future__ import annotations

import json
import unittest

from test_journal import CONFLICT, GATE, JournalTestCase, load_journal_module, OK, USAGE


# ---------------------------------------------------------------------------
# gate validation
# ---------------------------------------------------------------------------


class TestGateClarifyPassed(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_prd_key_is_violation(self):
        proc = self.append_event("feature/x", "clarify-passed", {}, rc=GATE)
        self.assertIn("prd", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_missing_prd_file_is_violation(self):
        self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/nope.md"}, rc=GATE
        )
        self.assertEqual(self.events(), [])

    def test_needs_clarification_marker_is_violation(self):
        """SC-008."""
        self.write("docs/prd/demo.md", "# PRD\n\n- FR-001 [NEEDS CLARIFICATION] which?\n")
        proc = self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/demo.md"}, rc=GATE
        )
        self.assertIn("NEEDS CLARIFICATION", proc.stdout + proc.stderr)
        self.assertEqual(self.events(), [])

    def test_clean_prd_passes(self):
        self.write("docs/prd/demo.md", "# PRD\n\n- FR-001 all settled\n")
        self.append_event(
            "feature/x", "clarify-passed", {"prd": "docs/prd/demo.md", "fr_count": 1}
        )
        self.assertEqual(
            [e["type"] for e in self.events()], ["phase-entered", "clarify-passed"]
        )

    def test_json_gate_violation_payload(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "clarify-passed", "--json", rc=GATE
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["error"], "gate-violation")
        self.assertTrue(payload["reason"])


class TestGateTaskDone(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_task_id_is_violation(self):
        self.append_event("feature/x", "task-done", {}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_without_verify_run_is_violation(self):
        proc = self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertIn("verify-run", (proc.stdout + proc.stderr).lower())
        self.assertEqual(self.events(), [])

    def test_failing_verify_run_is_violation(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "fail", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(len(self.events()), 2)

    def test_verify_run_for_other_task_is_violation(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T002"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(len(self.events()), 2)

    def test_verify_run_in_other_stream_is_violation(self):
        self.append_event(
            "feature/y", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(self.events("feature/x"), [])

    def test_passing_verify_run_unblocks(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001", "T002"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"})
        self.assertEqual(len(self.events("feature/x")), 3)


class TestGatePhaseEntered(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_missing_phase_is_violation(self):
        self.append_event("feature/x", "phase-entered", {}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_unknown_phase_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "vibes"}, rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_phase_outside_the_order_is_no_position_at_all(self):
        """An imported row can spell it `Implement`; brief and gate agree to ignore it."""
        raw = self.root / "raw.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/x", "version": 1, "type": "phase-entered",
            "data": {"phase": "Implement"}, "ts": "2026-08-20T10:00:00+00:00",
            "actor": "orchestrator",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        self.assertIsNone(self.status_json()["features"][0]["phase"])
        # …so the ordering gate still reads the stream as before workspace.
        self.append_event("feature/x", "phase-entered", {"phase": "review"}, rc=GATE)

    def test_first_phase_workspace_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})

    def test_single_step_forward_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/x", "phase-entered", {"phase": "route-and-map"})

    def test_same_phase_reentry_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})

    def test_backward_transition_allowed(self):
        for phase in ("workspace", "route-and-map", "explore", "clarify",
                      "design", "implement", "review"):
            self.append_event("feature/x", "phase-entered", {"phase": phase})
        self.append_event("feature/x", "phase-entered", {"phase": "implement"})

    def test_forward_jump_without_skipped_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        proc = self.append_event(
            "feature/x", "phase-entered", {"phase": "design"}, rc=GATE
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("skipped", combined.lower())
        self.assertIn("explore", combined)
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_a_jump_from_an_unusable_phase_names_the_spelling(self):
        """Otherwise "skips 5 phases" on a stream that recorded one reads as a bug."""
        raw = self.root / "raw.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/x", "version": 1, "type": "phase-entered",
            "data": {"phase": "Implement"}, "ts": "2026-08-20T10:00:00+00:00",
            "actor": "orchestrator",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        proc = self.append_event(
            "feature/x", "phase-entered", {"phase": "review"}, rc=GATE
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("spelled it 'Implement'", combined)
        self.assertIn("not in the declared order", combined)

    def test_a_jump_from_a_recorded_phase_names_no_spelling(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        proc = self.append_event(
            "feature/x", "phase-entered", {"phase": "design"}, rc=GATE
        )
        self.assertNotIn("spelled it", proc.stdout + proc.stderr)

    def test_forward_jump_with_skipped_allowed(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event(
            "feature/x",
            "phase-entered",
            {"phase": "design", "skipped": ["route-and-map", "explore", "clarify"]},
        )
        self.assertEqual(len(self.events("feature/x")), 2)

    def test_incomplete_skipped_list_is_violation(self):
        self.append_event("feature/x", "phase-entered", {"phase": "workspace"})
        self.append_event(
            "feature/x",
            "phase-entered",
            {"phase": "design", "skipped": ["explore"]},
            rc=GATE,
        )
        self.assertEqual(len(self.events("feature/x")), 1)


class TestImpliedPhase(JournalTestCase):
    """ADR 0002: a phase-owning event enters its phase, and `append` records it."""

    PASSING_VERIFY = {"outcome": "pass", "task_ids": ["T001"]}

    def setUp(self):
        super().setUp()
        self.init_db()

    def walk_to(self, phase, stream="feature/x"):
        module = load_journal_module()
        for name in module.PHASE_ORDER:
            self.append_event(stream, "phase-entered", {"phase": name})
            if name == phase:
                return
        raise AssertionError(f"{phase!r} is not a declared phase")

    def phase_rows(self, stream="feature/x"):
        return [e for e in self.events(stream) if e["type"] == "phase-entered"]

    def test_a_phase_owning_event_writes_the_transition_before_itself(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        events = self.events("feature/x")
        self.assertEqual([e["type"] for e in events],
                         ["phase-entered", "verify-run"])
        self.assertEqual([e["version"] for e in events], [1, 2])
        implied = events[0]["data"]
        self.assertEqual(implied["phase"], "implement")
        self.assertTrue(implied["implied"])
        self.assertEqual(implied["implied_by"], "verify-run")

    def test_a_forward_jump_names_the_phases_it_skipped(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.assertEqual(
            self.phase_rows()[0]["data"]["skipped"],
            ["workspace", "route-and-map", "explore", "clarify", "design"],
        )

    def test_nothing_is_implied_when_the_phase_already_matches(self):
        self.walk_to("implement")
        before = len(self.events("feature/x"))
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        events = self.events("feature/x")
        self.assertEqual(len(events), before + 1)
        self.assertEqual(events[-1]["type"], "verify-run")

    def test_a_backward_move_is_recorded_and_skips_nothing(self):
        self.walk_to("review")
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        implied = self.phase_rows()[-1]["data"]
        self.assertEqual(implied["phase"], "implement")
        self.assertTrue(implied["implied"])
        self.assertNotIn("skipped", implied)

    def test_a_not_ready_verdict_enters_review(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "not-ready"})
        self.assertEqual(self.phase_rows()[0]["data"]["phase"], "review")

    def test_capture_done_enters_capture(self):
        self.append_event("feature/x", "capture-done",
                          {"promoted": ["gotcha"], "dropped": []})
        self.assertEqual(self.phase_rows()[0]["data"]["phase"], "capture")

    def test_the_implied_row_inherits_the_events_actor(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY,
                          "--actor", "worker@S1")
        self.assertEqual(self.phase_rows()[0]["actor"], "worker@S1")

    def test_mr_opened_implies_no_phase(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "publish", "question": "ship it?", "decision": "publish",
            "mode": "ask", "raised_by": "user", "source": "dialog",
        }, "--actor", "user")
        self.append_event("feature/x", "mr-opened", {"url": "https://host.invalid/1"})
        self.assertEqual(self.phase_rows(), [])

    def test_stdout_names_the_transition(self):
        proc = self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.assertIn("entered implement, implied", proc.stdout)

    def test_json_reports_the_implied_phase(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "verify-run",
            "--data", json.dumps(self.PASSING_VERIFY), "--json", rc=OK,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["implied_phase"], "implement")
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["seq"], 2)

    def test_json_reports_null_when_nothing_was_implied(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "flow-suspended", "--json", rc=OK
        )
        self.assertIsNone(json.loads(proc.stdout)["implied_phase"])

    def test_expect_still_reads_the_version_before_the_implied_row(self):
        self.append(
            "--stream", "feature/x", "--type", "verify-run",
            "--data", json.dumps(self.PASSING_VERIFY), "--expect", "0", rc=OK,
        )
        self.assertEqual([e["version"] for e in self.events("feature/x")], [1, 2])

    def test_a_refused_event_implies_nothing(self):
        self.append_event("feature/x", "task-done", {"task_id": "T001"}, rc=GATE)
        self.assertEqual(self.events("feature/x"), [])


class TestGateReviewVerdict(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "task-done", {"task_id": "T001"})

    def test_ready_without_verify_after_last_task_done_is_violation(self):
        proc = self.append_event(
            "feature/x", "review-verdict", {"verdict": "ready"}, rc=GATE
        )
        self.assertIn("verify-run", (proc.stdout + proc.stderr).lower())
        self.assertEqual(len(self.events("feature/x")), 3)

    def test_the_pass_alias_is_gated_like_ready(self):
        """The skills wrote `pass` for years; the gate must not go inert on it."""
        self.append_event("feature/x", "review-verdict", {"verdict": "pass"}, rc=GATE)
        self.assertEqual(len(self.events("feature/x")), 3)

    def test_not_ready_is_always_allowed(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "not-ready"})

    def test_the_fail_alias_is_always_allowed(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "fail"})

    def test_ready_after_fresh_verify_run_allowed(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        self.assertEqual(len(self.events("feature/x")), 6)

    # A ready verdict closes every `fixing` key first (ADR 0014, amended 0.23.0).
    def fresh_verify(self):
        self.append_event(
            "feature/x", "verify-run", {"outcome": "pass", "task_ids": ["T001"]}
        )

    def disposition(self, dispositions, round_number=1):
        self.append_event("feature/x", "review-disposition",
                          {"dispositions": dispositions, "round": round_number})

    def ready(self, *args, rc=OK, **data):
        return self.append_event("feature/x", "review-verdict",
                                 dict(data, verdict="ready"), *args, rc=rc)

    def test_ready_over_an_open_fixing_is_refused(self):
        self.disposition({"src/a.ts:3": "fixing", "src/b.ts:?": "fixing"})
        self.disposition({"./src/b.ts:?": "fixed", "src/c.ts:9": "fixing"},
                         round_number=2)
        self.fresh_verify()
        before = len(self.events("feature/x"))
        proc = self.ready(rc=GATE)
        self.assertIn("leaves 2 finding(s) at fixing: src/a.ts:3, src/c.ts:9",
                      proc.stderr)
        self.assertIn(
            "journal.py append --stream feature/x --type review-disposition --data "
            '\'{"round": 2, "dispositions": {"src/a.ts:3": "fixed", '
            '"src/c.ts:9": "fixed"}}\'', proc.stderr)
        self.assertIn("--force and a --force-reason", proc.stderr)
        self.assertEqual(len(self.events("feature/x")), before)

    def test_the_pass_alias_is_refused_over_an_open_fixing_too(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.fresh_verify()
        self.append_event("feature/x", "review-verdict", {"verdict": "pass"}, rc=GATE)

    def test_the_closing_row_lists_ten_keys_and_counts_the_rest(self):
        keys = {f"src/f{n:02d}.ts:{n}": "fixing" for n in range(1, 13)}
        self.disposition(keys, round_number=4)
        self.fresh_verify()
        proc = self.ready(rc=GATE)
        self.assertIn("leaves 12 finding(s)", proc.stderr)
        self.assertIn("src/f10.ts:10 and 2 more", proc.stderr)
        self.assertNotIn("src/f11.ts:11", proc.stderr)
        self.assertIn('{"round": 4, "dispositions": {"src/f01.ts:1": "fixed"',
                      proc.stderr)

    def test_the_verify_refusal_comes_first(self):
        self.disposition({"src/a.ts:3": "fixing"})
        proc = self.ready(rc=GATE)
        self.assertIn("verify-run", proc.stderr)
        self.assertNotIn("at fixing", proc.stderr)

    def test_ready_is_accepted_when_its_own_map_closes_the_key(self):
        self.disposition({"src/a.ts:3": "fixing", "src/b.ts:?": "fixing"})
        self.fresh_verify()
        self.ready(dispositions={"./src/a.ts:3": "fixed", "src/b.ts:?": "deferred"})
        self.assertEqual(self.events("feature/x")[-1]["type"], "review-verdict")

    def test_ready_is_accepted_after_a_review_disposition_closes_the_key(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.disposition({"src/a.ts:3": "rejected"}, round_number=2)
        self.fresh_verify()
        self.ready()
        self.assertEqual(self.events("feature/x")[-1]["type"], "review-verdict")

    def test_a_key_an_earlier_verdict_closed_stays_closed(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.append_event("feature/x", "review-verdict", {
            "verdict": "not-ready", "dispositions": {"src/a.ts:3": "fixed"},
        })
        self.fresh_verify()
        self.ready()

    def test_a_not_ready_verdict_over_an_open_fixing_is_allowed(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.append_event("feature/x", "review-verdict", {"verdict": "not-ready"})
        self.assertEqual(self.events("feature/x")[-1]["type"], "review-verdict")

    def test_force_without_a_reason_is_refused_over_an_open_fixing(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.fresh_verify()
        before = len(self.events("feature/x"))
        proc = self.ready("--force", rc=USAGE)
        self.assertIn("--force-reason", proc.stderr)
        self.assertIn("src/a.ts:3", proc.stderr)
        self.assertIn("--type review-disposition", proc.stderr)
        self.assertEqual(len(self.events("feature/x")), before)

    def test_force_with_a_reason_overrides_an_open_fixing(self):
        self.disposition({"src/a.ts:3": "fixing"})
        self.ready("--force", "--force-reason", "the fix ships in a follow-up MR")
        data = self.events("feature/x")[-1]["data"]
        self.assertEqual((data["verdict"], data["forced"]), ("ready", True))

    def test_force_without_a_reason_is_fine_when_nothing_is_open(self):
        self.disposition({"src/a.ts:3": "fixed"})
        self.ready("--force")
        self.assertEqual(self.events("feature/x")[-1]["type"], "review-verdict")


class TestGateMrOpened(JournalTestCase):
    """FR-009: an MR is opened on the review's word, or on a deliberate publish call."""

    PASSING_VERIFY = {"outcome": "pass", "task_ids": ["T001"]}

    def setUp(self):
        super().setUp()
        self.init_db()
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "task-done", {"task_id": "T001"})

    def mr_opened(self, *args, rc=OK):
        return self.append_event(
            "feature/x", "mr-opened", {"url": "https://host.invalid/1"}, *args, rc=rc
        )

    def last_type(self):
        return self.events("feature/x")[-1]["type"]

    def publish_decision(self, decision="publish", raised_by="user", source="dialog",
                         actor="user"):
        """A publish decision, marked as the HUD's dialog writes it unless told not to
        (ADR 0015). ``source=None`` leaves the marker out; ``actor=None`` the flag."""
        data = {
            "gate": "publish", "question": "open it before the second review?",
            "decision": decision, "mode": "ask", "raised_by": raised_by,
        }
        if source is not None:
            data["source"] = source
        args = ("--actor", actor) if actor is not None else ()
        self.append_event("feature/x", "gate-decision", data, *args)

    def test_without_a_verdict_or_a_publish_decision_is_a_violation(self):
        proc = self.mr_opened(rc=GATE)
        combined = proc.stdout + proc.stderr
        self.assertIn("review-verdict", combined)
        self.assertIn("publish", combined)
        self.assertEqual(self.last_type(), "task-done")

    def test_the_refusal_names_all_three_conditions_on_the_decision(self):
        proc = self.mr_opened(rc=GATE)
        combined = proc.stdout + proc.stderr
        self.assertIn("gate=publish", combined)
        self.assertIn("raised_by=user", combined)
        self.assertIn("decision=publish", combined)

    def test_a_ready_verdict_after_the_last_task_done_unblocks(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        self.mr_opened()
        self.assertEqual(self.last_type(), "mr-opened")

    def test_a_not_ready_verdict_does_not_unblock(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "not-ready"})
        self.mr_opened(rc=GATE)

    def test_a_later_not_ready_verdict_takes_back_the_ready_one(self):
        """#40: the built-in run on the commit found something after a ready verdict."""
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        self.append_event("feature/x", "review-verdict", {
            "verdict": "not-ready",
            "security_review": {"kind": "builtin", "files": 3, "ref": "0123abc"},
        })
        self.mr_opened(rc=GATE)
        self.assertEqual(self.last_type(), "review-verdict")

    def test_a_user_raised_publish_decision_unblocks(self):
        self.publish_decision()
        self.mr_opened()
        self.assertEqual(self.last_type(), "mr-opened")

    def test_the_decision_is_read_case_and_space_insensitively(self):
        self.publish_decision(decision="  Publish ")
        self.mr_opened()
        self.assertEqual(self.last_type(), "mr-opened")

    def test_a_publish_gate_answered_no_does_not_unblock(self):
        """Sitting at the gate is not passing it."""
        self.publish_decision(decision="no")
        self.mr_opened(rc=GATE)
        self.assertEqual(self.last_type(), "gate-decision")

    def test_an_orchestrator_raised_publish_decision_does_not_unblock(self):
        """Otherwise the flow authorizes its own MR by asking itself."""
        self.publish_decision(raised_by="orchestrator")
        self.mr_opened(rc=GATE)
        self.assertEqual(self.last_type(), "gate-decision")

    # ADR 0015: a user's publish decision authorizes only with its marker and actor.
    def test_a_decision_marked_by_the_dialog_unblocks(self):
        self.publish_decision(source="dialog")
        self.mr_opened()
        self.assertEqual(self.last_type(), "mr-opened")

    def test_a_decision_marked_by_the_users_shell_unblocks(self):
        self.publish_decision(source="shell", actor="user@alice")
        self.mr_opened()
        self.assertEqual(self.last_type(), "mr-opened")

    def test_an_unmarked_user_publish_decision_does_not_unblock(self):
        """An older row, or one the model wrote as the user's: the gate asks again."""
        self.publish_decision(source=None)
        self.mr_opened(rc=GATE)
        self.assertEqual(self.last_type(), "gate-decision")

    def test_a_marked_decision_by_the_orchestrator_does_not_unblock(self):
        for actor in ("orchestrator", None, "worker@w1"):
            with self.subTest(actor=actor):
                self.publish_decision(actor=actor)
                self.mr_opened(rc=GATE)
                self.assertEqual(self.last_type(), "gate-decision")

    def test_a_marked_decision_the_orchestrator_raised_does_not_unblock(self):
        self.publish_decision(raised_by="orchestrator", source="dialog", actor="user")
        self.mr_opened(rc=GATE)
        self.assertEqual(self.last_type(), "gate-decision")

    def test_the_refusal_sends_the_model_to_the_user(self):
        """ADR 0023 §17: the refusal names the four markers and offers no force (#52: the
        read go is gone)."""
        proc = self.mr_opened(rc=GATE)
        combined = proc.stdout + proc.stderr
        self.assertIn("publish dialog", combined)
        self.assertIn("`!`", combined)
        self.assertIn("source question|prompt|dialog|shell", combined)
        self.assertIn("confirming question", combined)
        self.assertNotRegex(combined, r"\bread\b")
        self.assertIn("go-requested", combined)
        self.assertIn("--force does not waive", combined)
        self.assertNotIn("--force and a reason", combined)
        self.assertNotIn("take the publish decision with the user", combined)

    def test_a_decision_at_another_gate_does_not_unblock(self):
        self.append_event("feature/x", "gate-decision", {
            "gate": "design", "question": "q", "decision": "d", "mode": "ask",
        })
        self.mr_opened(rc=GATE)

    def test_a_verdict_from_before_the_last_task_done_is_stale(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        self.append_event("feature/x", "verify-run",
                          {"outcome": "pass", "task_ids": ["T002"]})
        self.append_event("feature/x", "task-done", {"task_id": "T002"})
        self.mr_opened(rc=GATE)

    def test_a_verdict_in_another_stream_does_not_unblock(self):
        self.append_event("feature/y", "review-verdict", {"verdict": "not-ready"})
        self.mr_opened(rc=GATE)

    # ADR 0023 §17: no forced event opens a publish.
    def test_force_does_not_waive_the_gate(self):
        """SC-006."""
        proc = self.append(
            "--stream", "feature/x", "--type", "mr-opened",
            "--data", json.dumps({"url": "https://host.invalid/1"}),
            "--force", "--force-reason", "x", rc=GATE,
        )
        self.assertIn("--force does not waive", proc.stderr)
        self.assertEqual(self.last_type(), "task-done")

    def test_a_forced_ready_verdict_does_not_authorize(self):
        """SC-016: the forced verdict lands, and authorizes nothing."""
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"},
                          "--force", "--force-reason", "x")
        self.assertEqual(self.last_type(), "review-verdict")
        self.mr_opened(rc=GATE)
        self.assertEqual(self.publish_of(), {"kind": "held"})
        self.assertEqual(self.position_publish(), {"kind": "held"})

    def test_a_plain_ready_verdict_after_a_forced_one_authorizes(self):
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"},
                          "--force", "--force-reason", "x")
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        verdict = self.events("feature/x")[-1]
        self.assertEqual(self.publish_of()["seq"], verdict["seq"])
        self.mr_opened()

    def test_a_publish_go_still_opens_with_force(self):
        self.publish_decision()
        self.mr_opened("--force", "--force-reason", "x")
        self.assertEqual(self.last_type(), "mr-opened")

    # `status --json` prints the same rule per stream, so the HUD reads the gate's own
    # answer instead of re-deriving it (ADR 0009).
    def publish_of(self):
        features = self.status_json()["features"]
        return next(f for f in features if f["stream"] == "feature/x")["publish"]

    def test_status_prints_held_until_something_authorizes(self):
        self.assertEqual(self.publish_of(), {"kind": "held"})

    def test_status_names_the_authorizing_decision(self):
        self.publish_decision()
        event = self.events("feature/x")[-1]
        self.assertEqual(self.publish_of(), {
            "kind": "authorized", "by": "gate-decision",
            "seq": event["seq"], "at": event["ts"],
        })

    def test_status_names_the_authorizing_verdict(self):
        self.append_event("feature/x", "verify-run", self.PASSING_VERIFY)
        self.append_event("feature/x", "review-verdict", {"verdict": "ready"})
        event = self.events("feature/x")[-1]
        self.assertEqual(self.publish_of(), {
            "kind": "authorized", "by": "review-verdict",
            "seq": event["seq"], "at": event["ts"],
        })

    def test_status_and_the_gate_agree_on_a_stale_verdict(self):
        self.test_a_verdict_from_before_the_last_task_done_is_stale()
        self.assertEqual(self.publish_of(), {"kind": "held"})

    def position_publish(self):
        proc = self.journal("--db", self.db, "position", "--stream", "feature/x",
                            "--json", rc=OK)
        return json.loads(proc.stdout)["publish"]

    def test_status_position_and_the_gate_agree_on_the_marker(self):
        """ADR 0015: the one rule, read by the gate, `status` and `position`."""
        self.publish_decision(source=None)
        self.publish_decision(actor="orchestrator")
        self.assertEqual(self.publish_of(), {"kind": "held"})
        self.assertEqual(self.position_publish(), {"kind": "held"})
        self.publish_decision()
        event = self.events("feature/x")[-1]
        expected = {"kind": "authorized", "by": "gate-decision",
                    "seq": event["seq"], "at": event["ts"]}
        self.assertEqual(self.publish_of(), expected)
        self.assertEqual(self.position_publish(), expected)
        self.mr_opened()

    def test_an_old_row_with_a_list_decision_never_authorizes(self):
        """A row from before the string rule (here imported) can still hold a list;
        neither the gate nor status reads it as a publish (audit D6)."""
        raw = self.root / "old.jsonl"
        raw.write_text(json.dumps({
            "stream": "feature/x", "version": len(self.events("feature/x")) + 1,
            "type": "gate-decision",
            "data": {"gate": "publish", "question": "q", "decision": ["publish"],
                     "mode": "ask", "raised_by": "user"},
            "ts": "2026-10-01T09:00:00+00:00", "actor": "user",
        }) + "\n", encoding="utf-8")
        self.journal("--db", self.db, "import", raw, rc=OK)
        self.assertEqual(self.publish_of(), {"kind": "held"})
        self.mr_opened(rc=GATE)


class TestGateMisc(JournalTestCase):
    def setUp(self):
        super().setUp()
        self.init_db()

    def test_unknown_event_type_is_refused(self):
        """An unlisted type is inert — no gate or report would ever read it."""
        proc = self.append_event(
            "feature/x", "totally-new-thing", {"whatever": True}, rc=GATE
        )
        self.assertIn("vocabulary", proc.stderr)
        self.assertEqual(self.events(), [])

    def test_a_new_type_can_be_minted_deliberately(self):
        self.append_event(
            "feature/x", "totally-new-thing", {"whatever": True}, "--new-type", rc=OK
        )
        event = self.events()[0]
        self.assertEqual(event["type"], "totally-new-thing")
        self.assertTrue(event["data"]["new_type"], "extensions must be visible as such")

    def test_force_does_not_waive_the_vocabulary(self):
        """--force skips gate preconditions; it does not make an inert event readable."""
        self.append_event("feature/x", "decisionn", None, "--force", rc=GATE)
        self.assertEqual(self.events(), [])

    def test_a_near_miss_names_the_canonical_type(self):
        proc = self.append_event("feature/x", "decision", None, rc=GATE)
        self.assertIn("gate-decision", proc.stderr)

    def test_a_semantic_miss_still_points_at_the_vocabulary(self):
        """`workspace-ready` shares no substring with `flow-started` — the real case
        that string-similarity matching alone would have missed."""
        proc = self.append_event("feature/x", "workspace-ready", None, rc=GATE)
        self.assertIn("vocab", proc.stderr)

    def test_force_writes_despite_violation_and_stamps_audit(self):
        proc = self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}),
            "--force", "--force-reason", "hotfix, verify ran offline",
            rc=OK,
        )
        self.assertIn("seq", proc.stdout.lower())
        data = self.events("feature/x")[-1]["data"]
        self.assertTrue(data["forced"])
        self.assertEqual(data["force_reason"], "hotfix, verify ran offline")
        self.assertEqual(data["task_id"], "T001")

    def test_force_without_reason_stamps_null(self):
        self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}), "--force", rc=OK,
        )
        data = self.events("feature/x")[-1]["data"]
        self.assertTrue(data["forced"])
        self.assertIsNone(data["force_reason"])

    def test_force_does_not_bypass_expect(self):
        self.append_event("feature/x", "flow-suspended")
        self.append(
            "--stream", "feature/x", "--type", "task-done",
            "--data", json.dumps({"task_id": "T001"}),
            "--force", "--expect", "0", rc=CONFLICT,
        )
        self.assertEqual(len(self.events("feature/x")), 1)

    def test_force_reason_without_force_is_usage_error(self):
        self.append(
            "--stream", "feature/x", "--type", "flow-suspended",
            "--force-reason", "because", rc=USAGE,
        )
        self.assertEqual(self.events(), [])


class TestClarifyConfirmRecordingForms(JournalTestCase):
    """#24 FR-010 / SC-004: the journal accepts the three forms clarify records a confirm
    batch with: kept and changed as the user's, a dismissed dialog as the
    orchestrator's. A pin of today's behaviour: no new event type, no new shape."""

    def setUp(self):
        super().setUp()
        self.init_db()

    def test_kept_changed_and_dismissed_are_accepted(self):
        q = "Is the fee its own posting?"
        self.append_event("feature/x", "gate-decision", {
            "gate": "clarify", "question": q, "decision": "kept: yes, a fee posting",
            "mode": "ask", "raised_by": "orchestrator"}, "--actor", "user")
        self.append_event("feature/x", "gate-decision", {
            "gate": "clarify", "question": "Does the notice show the fee?",
            "decision": "yes, as its own line", "mode": "ask", "raised_by": "user"},
            "--actor", "user")
        self.append_event("feature/x", "gate-decision", {
            "gate": "clarify", "question": "confirm batch",
            "decision": "dismissed: 2 items unconfirmed", "mode": "executive",
            "raised_by": "orchestrator"})
        events = [e for e in self.events("feature/x") if e["type"] == "gate-decision"]
        self.assertEqual(len(events), 3)
        self.assertEqual([e["data"]["mode"] for e in events], ["ask", "ask", "executive"])
        self.assertEqual([e["data"]["raised_by"] for e in events],
                         ["orchestrator", "user", "orchestrator"])
        self.assertEqual([e["actor"].split("@")[0] for e in events],
                         ["user", "user", "orchestrator"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
