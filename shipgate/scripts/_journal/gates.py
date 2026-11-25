"""Each event type's precondition on the journal (rules v1)."""

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, get_args

from .vocab import (
    CLOSEOUT_CHOSEN_PLACEHOLDER, CLOSEOUT_QUESTION_PLACEHOLDER, Disposition, GATE_WAIVED,
    GateViolation, GoGate, InfraError, NEEDS_CLARIFICATION, PHASE_ORDER, ReviewVerdict,
    SCREENS_WAIVED, SESSION_ENV, TASK_ID_RE, UsageError,
)
from .plugin import (
    _db_file, _journal_command, _request_command, _suggest,
    CONFIRMING_QUESTION_PLACEHOLDER, GATE_QUESTION_PLACEHOLDER, NO_COMMAND,
)
from .text import _in_backticks, _vocabulary_map, _waiver_reason
from .store import Event, read_events
from .sessions import _actor_session, RETIRED_READ_MARKER
from .approval import publish_authorization
from .fold import (
    _finding_key, _last_phase_spelling, _position_dispositions, fold_stream, folded_phase,
)
from .artifacts import _resolve_artifact, plan_paths
from .project import project_settings, require_setting
from .screens import evidence_root, project_key, stream_dir_name, task_screen_state


def _validate_clarify_passed(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any], project_dir: Path
) -> None:
    prd = data.get("prd")
    if not isinstance(prd, str) or not prd:
        raise GateViolation(
            "clarify-passed requires data.prd naming the PRD file that was cleared"
        )
    path = _resolve_artifact(project_dir, prd)
    if not path.is_file():
        raise GateViolation(f"clarify-passed: PRD not found at {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InfraError(f"cannot read PRD {path}: {exc}") from exc
    count = text.count(NEEDS_CLARIFICATION)
    if count:
        raise GateViolation(
            f"clarify-passed: {path} still contains {count} "
            f"{NEEDS_CLARIFICATION} marker(s)"
        )


def _passing_verify_runs(conn: sqlite3.Connection, stream: str) -> List[Event]:
    return [
        event
        for event in read_events(conn, stream=stream, types=("verify-run",))
        if event.data.get("outcome") == "pass"
    ]


def _validate_task_done(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any], project_dir: Path
) -> None:
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise GateViolation("task-done requires data.task_id")
    if not any(
        isinstance(event.data.get("task_ids"), list) and task_id in event.data["task_ids"]
        for event in _passing_verify_runs(conn, stream)
    ):
        raise GateViolation(
            f"task-done {task_id}: no prior verify-run with outcome=pass in stream "
            f"{stream!r} names it in data.task_ids"
        )
    _validate_screens(conn, stream, task_id, project_dir)


SCREENS_NOTE_PLACEHOLDER = "<why no screenshot can be taken>"


def _validate_screens(
    conn: sqlite3.Connection, stream: str, task_id: str, project_dir: Path
) -> None:
    """ADR 0031: with ``ui.globs`` set, a UI task is done with a registered screenshot
    newer than the stream's ``design-committed`` at every set width, or with a
    ``screens-waived`` deviation that names it. A task that is not UI passes. A ``ui``
    value outside its set refuses the append (exit 2), whatever the task."""
    resolved = project_settings(project_dir)
    globs = require_setting(resolved, "ui.globs")
    if not globs:
        return
    widths = require_setting(resolved, "ui.widths")
    capture = require_setting(resolved, "ui.capture")
    entry = task_screen_state(conn, stream, task_id, project_dir, globs, widths)
    if entry is None or entry["waived"] is not None or not entry["missing"]:
        return
    raise GateViolation(_screens_refusal(conn, stream, task_id, entry["missing"],
                                         capture is not None))


def _screens_refusal(conn: sqlite3.Connection, stream: str, task_id: str,
                     missing: List[int], capture: bool) -> str:
    db = _db_file(conn)

    def command(*args: str) -> str:
        line = _journal_command(db, *args) if db is not None else None
        return line or NO_COMMAND

    head = (f"task-done {task_id}: {task_id} is a UI task (a path on its Build Plan "
            "line matches ui.globs) and ")
    if evidence_root() is None:
        lines = [head + "there is no evidence root (set CLAUDE_CONFIG_DIR or HOME)."]
    elif stream_dir_name(stream) is None:
        lines = [head + "no evidence directory can exist for this stream (the stream "
                 "name cannot name one)."]
    elif project_key(conn) is None:
        lines = [head + "no evidence directory can exist for this stream (the journal "
                 "has no file)."]
    else:
        lines = [
            head + "misses a screenshot newer than its design-committed at "
            + ", ".join(str(width) for width in missing) + ".",
            "Take each missing width with the browser tool you have, read the files and "
            "compare them with the PRD's reference, then register them:",
            "  " + command("screens", "--stream=" + stream, "--task", task_id,
                           "--file", "<png>"),
        ]
        if capture:
            lines.append("  " + command("screens", "--stream=" + stream, "--task",
                                        task_id, "--url", "<url>"))
    waiver = _suggest(db, stream, "deviation", {
        "kind": SCREENS_WAIVED, "task_ids": [task_id], "note": SCREENS_NOTE_PLACEHOLDER,
    }) if db is not None else None
    lines += ["If no screenshot can be taken, record why (the user reads the reason in "
              "the publish digest):", "  " + (waiver or NO_COMMAND)]
    return "\n".join(lines)


# How many Build Plan lines a design-committed refusal lists.
_PLAN_ERRORS_SHOWN = 10


def _validate_design_committed(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any], project_dir: Path
) -> None:
    """ADR 0031: with ``ui.globs`` set, each Build Plan task line names its paths in
    backticks after ``file(s):``, or says ``file(s): none``, because the task-done gate
    computes a UI task from them, and each task id is ``T`` and ASCII digits, the ids
    ``screens --task`` takes. A worklog that cannot be read passes with a warning: no
    task of it is UI. A ``ui.globs`` outside its set refuses the append (exit 2)."""
    if not require_setting(project_settings(project_dir), "ui.globs"):
        return
    ref = data.get("worklog")
    if not isinstance(ref, str) or not ref:
        return
    path = _resolve_artifact(project_dir, ref)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):  # a NUL byte in the ref is a ValueError
        shown = str(path) if str(path).isprintable() else repr(str(path))
        print(f"warning: design-committed: {shown} cannot be read, so no task is UI",
              file=sys.stderr)
        return
    bad: List[str] = []
    for item in plan_paths(text):
        where = f"{ref}:{item['line']}: {item['id']}"
        if TASK_ID_RE.fullmatch(item["id"]) is None:
            bad.append(f"{where} is not T and ASCII digits")
        if item["error"]:
            bad.append(f"{where} {item['error']}")
    if not bad:
        return
    lines = ["design-committed: the Build Plan names each task's paths when ui.globs "
             "is set:"]
    lines += bad[:_PLAN_ERRORS_SHOWN]
    if len(bad) > _PLAN_ERRORS_SHOWN:
        lines.append(f"and {len(bad) - _PLAN_ERRORS_SHOWN} more")
    raise GateViolation("\n".join(lines))


def _validate_phase_entered(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    phase = data.get("phase")
    if not isinstance(phase, str) or not phase:
        raise GateViolation("phase-entered requires data.phase")
    if phase not in PHASE_ORDER:
        raise GateViolation(
            f"phase-entered: unknown phase {phase!r}; declared order is "
            + ", ".join(PHASE_ORDER)
        )
    target = PHASE_ORDER.index(phase)

    recorded = folded_phase(conn, stream)
    previous = PHASE_ORDER.index(recorded) if recorded is not None else -1

    # Backward and same-phase transitions are always legal (review -> implement
    # is a normal loop). So is a single step forward.
    if target - previous <= 1:
        return

    intervening = PHASE_ORDER[previous + 1: target]
    declared = data.get("skipped")
    declared_set = set(declared) if isinstance(declared, list) else set()
    unnamed = [name for name in intervening if name not in declared_set]
    if unnamed:
        # A stream whose only recorded phase is unusable folds to None, which reads as
        # "nothing recorded" and turns any append into a jump from the start. Say which
        # spelling was ignored, or the refusal looks like a bug in the caller.
        spelled = _last_phase_spelling(conn, stream) if recorded is None else None
        raise GateViolation(
            "phase-entered {target}: forward jump skips {n} phase(s); list them in "
            "data.skipped. Missing: {missing}{hint}".format(
                target=phase,
                n=len(intervening),
                missing=", ".join(unnamed),
                hint=(
                    f" (the last recorded phase-entered spelled it {spelled!r}, "
                    "which is not in the declared order)"
                ) if spelled is not None else "",
            )
        )


def _validate_review_verdict(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    """A ``ready`` verdict needs fresh verify evidence, then no open ``fixing`` key.

    The evidence check comes first: a verdict without it is refused whatever its
    findings. ``--force`` skips both; ``append_event`` asks a reason for skipping the
    second (``_require_closure_reason``).
    """
    if data.get("verdict") != "ready":
        return
    task_dones = read_events(conn, stream=stream, types=("task-done",))
    last_task_done_seq = max((e.seq for e in task_dones), default=0)
    if not any(
        event.seq > last_task_done_seq for event in _passing_verify_runs(conn, stream)
    ):
        raise GateViolation(
            "review-verdict=ready requires a verify-run with outcome=pass recorded "
            f"after the last task-done in stream {stream!r}"
        )
    open_keys, round_number = open_fixing_keys(conn, stream, data)
    if open_keys:
        raise GateViolation(
            _open_fixing_message(stream, open_keys, round_number)
            + " — or append the verdict with --force and a --force-reason"
        )


# How many open keys a refusal lists, and puts in its closing row.
_OPEN_KEYS_SHOWN = 10


def open_fixing_keys(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> Tuple[List[str], int]:
    """The keys a verdict with payload ``data`` would leave at ``fixing``, and a round.

    The fold is ``position``'s (``_position_dispositions`` over the stream's events and
    its verdicts in the vocabulary); this verdict's own ``dispositions`` then apply on
    top, each key as ``_finding_key`` leaves it. The keys come in fold order. The round
    is the highest ``round`` of the ``review-disposition`` events that set the first
    ``_OPEN_KEYS_SHOWN`` of them to ``fixing``, or 1 when none of those carries one.
    """
    events = read_events(conn, stream=stream)
    verdicts = [
        e for e in events
        if e.type == "review-verdict"
        and e.data.get("verdict") in get_args(ReviewVerdict)
    ]
    folded = _position_dispositions(events, verdicts)
    states = {key: entry["state"] for key, entry in folded.items()}
    own = _vocabulary_map(data.get("dispositions"), get_args(Disposition))
    for key, state in own.items():
        states[_finding_key(key)] = state
    open_keys = [key for key, state in states.items() if state == "fixing"]
    setters = {folded[key]["seq"] for key in open_keys[:_OPEN_KEYS_SHOWN]}
    rounds = [
        e.data["round"] for e in events
        if e.seq in setters
        and isinstance(e.data.get("round"), int)
        and not isinstance(e.data.get("round"), bool)
    ]
    return open_keys, max(rounds, default=1)


def _open_fixing_message(stream: str, open_keys: List[str], round_number: int) -> str:
    """The refusal's body: the open keys and the ``review-disposition`` that closes them."""
    shown = open_keys[:_OPEN_KEYS_SHOWN]
    more = len(open_keys) - len(shown)
    closing = json.dumps(
        {"round": round_number, "dispositions": {key: "fixed" for key in shown}}
    )
    return (
        f"review-verdict=ready in stream {stream!r} leaves {len(open_keys)} finding(s) "
        "at fixing: " + ", ".join(shown) + (f" and {more} more" if more > 0 else "")
        + ". Close each one (fixed, rejected or deferred) before the verdict, or in the "
        "verdict's own dispositions map: `journal.py append --stream "
        f"{shlex.quote(stream)} --type review-disposition --data {shlex.quote(closing)}`"
        " (write rejected or deferred where that is the state)"
    )


def _require_closure_reason(
    conn: sqlite3.Connection,
    stream: str,
    event_type: str,
    data: Dict[str, Any],
    force_reason: Optional[str],
) -> None:
    """Refuse ``--force`` without a reason on a ``ready`` verdict over open ``fixing``.

    ``--force`` skips ``validate_gate``, so this is the one check left on that path
    (ADR 0014, amended 0.23.0), the same pattern as ``check_payload_size``.
    """
    if force_reason or event_type != "review-verdict" or data.get("verdict") != "ready":
        return
    open_keys, round_number = open_fixing_keys(conn, stream, data)
    if open_keys:
        raise UsageError(
            "--force on " + _open_fixing_message(stream, open_keys, round_number)
            + " — --force needs --force-reason saying why the verdict leaves them open"
        )


MR_OPENED_REFUSAL = (
    "mr-opened in stream {stream} needs, recorded after the last task-done, either the "
    "newest review-verdict, with verdict=ready and not forced, or the user's publish "
    "go: a gate-decision with gate=publish, raised_by=user and decision=publish, marked "
    "with source question|prompt|dialog|shell. The recorder writes `question` when the "
    "user answers the publish question and `prompt` when the user types `publish`; the "
    "HUD's publish dialog writes `dialog`; the user's own `!` command writes `shell`. "
    "Record the review's outcome, or record a go-requested{request} and ask the user. "
    "When the user's reply was no exact go, record a new go-requested the same way and "
    "ask one confirming question with the header `Publish`. --force does not waive this."
)


def _validate_mr_opened(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    events = read_events(
        conn, stream=stream, types=("task-done", "review-verdict", "gate-decision"),
    )
    if publish_authorization(events)["kind"] == "authorized":
        return
    raise GateViolation(MR_OPENED_REFUSAL.format(
        stream=repr(stream),
        request=_in_backticks(_request_command_of(
            conn, stream, "publish", GATE_QUESTION_PLACEHOLDER
        )),
    ))


def _validate_waiver(data: Dict[str, Any]) -> None:
    """A `deviation` of kind ``gate-waived`` clears Stop gate findings (ADR 0020), and
    one of kind ``screens-waived`` stands in for a UI task's screenshots (ADR 0031), so
    each names the tasks it waives and gives a reason. Any other deviation passes.
    `--force` does not skip this: a waiver with no reason is not a waiver, and its
    readers take it as none."""
    kind = data.get("kind")
    if kind not in (GATE_WAIVED, SCREENS_WAIVED):
        return
    task_ids = data.get("task_ids")
    if (not isinstance(task_ids, list) or not task_ids
            or not all(isinstance(t, str) and t for t in task_ids)):
        raise GateViolation(
            f"a {kind} deviation names the tasks it waives: data.task_ids is a "
            "non-empty list of task ids"
        )
    if _waiver_reason(data) is None:
        raise GateViolation(
            f"a {kind} deviation says why: write the reason in data.note, in place "
            "of an empty note or a <...> placeholder"
        )


# What `append` says to a read go: the flow asks one confirming question instead (#52).
READ_GO_REFUSAL = (
    "gate-decision: the marker `read` is retired (ADR 0023, amendment). The model records "
    "no go in any form. When the user's reply was no exact go, record a new go-requested "
    "for the gate{request}, then ask one confirming question with the header `Commit` or "
    "`Publish` and the gate word as the first option: the recorder hook records the "
    "click. --force does not waive this."
)


def _refuse_read_go(
    conn: sqlite3.Connection, stream: str, event_type: str, data: Dict[str, Any]
) -> None:
    """Refuse 0.28.0's read go, on the forced path too (#52, ADR 0023 amendment A3).

    It runs before the shape check, so the refusal names the confirming question and not
    only the closed list of markers. ``source`` is read trimmed and in any case. When the
    row names a commit or publish gate (``gate``, or its alias ``kind``), the refusal
    prints the go request for it (#55).
    """
    source = data.get("source")
    if (
        event_type == "gate-decision"
        and isinstance(source, str)
        and source.strip().casefold() == RETIRED_READ_MARKER
    ):
        gate = data.get("gate") or data.get("kind")
        gate = gate.strip().casefold() if isinstance(gate, str) else ""
        command = (
            _request_command_of(conn, stream, gate)
            if gate in get_args(GoGate) else None
        )
        raise GateViolation(READ_GO_REFUSAL.format(request=_in_backticks(command)))


def _refuse_closeout_placeholders(event_type: str, data: Dict[str, Any]) -> None:
    """Refuse the close-out record as ``closeout`` printed it: a placeholder is no
    decision of the user's. On the forced path too."""
    if event_type != "gate-decision":
        return
    held = [key for key, placeholder in (("question", CLOSEOUT_QUESTION_PLACEHOLDER),
                                         ("decision", CLOSEOUT_CHOSEN_PLACEHOLDER))
            if isinstance(data.get(key), str) and data[key].strip() == placeholder]
    if held:
        raise GateViolation(
            f"gate-decision: {' and '.join(held)} still "
            f"{'holds' if len(held) == 1 else 'hold'} the close-out placeholder. "
            "Put the question you asked and the steps the user chose in their place"
        )


def _validate_own_session(
    conn: sqlite3.Connection, event_type: str, data: Dict[str, Any], actor: str,
    raw_actor: Optional[str] = None,
) -> None:
    """A go request counts for the session that appends it (§4).

    Its actor label says which session that is. When the shell names the appending
    session (``CLAUDE_CODE_SESSION_ID``), a label that names another session is refused,
    with or without ``--force``: it would let one session ask in another's name, and
    that session's next reply would answer it.
    """
    if event_type != "go-requested":
        return
    if "session" in data:
        raise GateViolation(
            f"{event_type}: data.session is not taken; the journal records the session "
            "that appends the row"
        )
    running = os.environ.get(SESSION_ENV, "").strip()
    if not running:
        if raw_actor and "@" in raw_actor and raw_actor.partition("@")[2]:
            raise GateViolation(
                f"{event_type}: the actor label names a session, but "
                f"{SESSION_ENV} is empty, so no one can check it. Append it from the "
                "session's own shell, with no label"
            )
        return
    named = _actor_session(conn, actor)
    if named is not None and named != running:
        raise GateViolation(
            f"{event_type}: the actor label names another session ({named}) than the "
            f"one appending ({running}); a session asks only in its own name — drop the "
            "label"
        )


def _validate_go_request(conn: sqlite3.Connection, stream: str) -> None:
    """A go request puts a gate of a live stream to the user (ADR 0023 §3). A stream
    with no events, or a finished one, has nothing to commit or publish. `--force` does
    not skip this: a request on no stream would wait for a reply that answers nothing."""
    events = read_events(conn, stream=stream)
    if not events:
        raise GateViolation(
            f"go-requested needs a live stream: {stream!r} has no events. Record the "
            "request on the stream whose work the user approves"
        )
    if fold_stream(events)["terminal"]:
        raise GateViolation(
            f"go-requested needs a live stream: {stream!r} is finished"
        )


def validate_gate(
    conn: sqlite3.Connection,
    stream: str,
    event_type: str,
    data: Dict[str, Any],
    project_dir: Path,
) -> None:
    """Raise GateViolation when an append's precondition is unmet."""
    if event_type == "go-requested":
        _validate_go_request(conn, stream)
    if event_type == "clarify-passed":
        _validate_clarify_passed(conn, stream, data, project_dir)
    elif event_type == "task-done":
        _validate_task_done(conn, stream, data, project_dir)
    elif event_type == "design-committed":
        _validate_design_committed(conn, stream, data, project_dir)
    elif event_type == "phase-entered":
        _validate_phase_entered(conn, stream, data)
    elif event_type == "review-verdict":
        _validate_review_verdict(conn, stream, data)
    elif event_type == "mr-opened":
        _validate_mr_opened(conn, stream, data)
    elif event_type == "deviation":
        _validate_waiver(data)


def _request_command_of(
    conn: sqlite3.Connection, stream: str, gate: str,
    question: str = CONFIRMING_QUESTION_PLACEHOLDER,
) -> Optional[str]:
    """`_request_command` for the journal ``conn`` opened: an `append` refusal has the
    connection, not the db path (#55). None when the stream is not live, because
    `append` refuses a go request there (`_validate_go_request`)."""
    db_path = _db_file(conn)
    if db_path is None:
        return None
    events = read_events(conn, stream=stream)
    if not events or fold_stream(events)["terminal"]:
        return None
    return _request_command(db_path, stream, gate, question)
