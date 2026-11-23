"""The Stop gate (ADR 0020)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import (
    Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple, TypedDict,
)

from .vocab import GATE_WAIVED
from .plugin import _suggest, NO_COMMAND
from .text import _one_line, _string_list, _string_or_none
from .store import _set_meta, _table_exists, Event, get_meta, read_events, utc_now
from .sessions import _actor_role, event_session
from .fold import is_work_stream
from .artifacts import (
    _artifact_key, _resolve_artifact, artifact_authors, claim_of, classify_artifact,
    parse_ticked_tasks, worklog_owners,
)
from .gates import _waiver_reason


LAST_CHECK_KEY = "last_check"
# The note a printed waiver command carries. `append` refuses it: a waiver records a
# reason, and the session writes one before the command runs.
WAIVER_NOTE_PLACEHOLDER = "<why these tasks need no task-done or verify-run>"


# Why `check` did not judge a worklog the session wrote: the file is gone, no stream
# owns it, or only finished streams do.
SkipReason = Literal["not-found", "no-stream", "finished"]


class CheckSkip(TypedDict):
    path: str
    reason: SkipReason
    detail: str


class CheckWaiver(TypedDict):
    """One ready `deviation` append that waives every finding on ``stream``; ``command``
    is None when ``_suggest`` would not print one."""

    stream: str
    task_ids: List[str]
    command: Optional[str]


class CheckReport(TypedDict):
    """``check --json``. Every finding carries ``missing``, ``detail``,
    ``suggested_command`` (or None, see ``_suggest``), ``stream`` and ``task_id``."""

    findings: List[Dict[str, Any]]
    skipped: List[CheckSkip]
    waivers: List[CheckWaiver]


def _waived_task_ids(events: Iterable[Event]) -> Set[str]:
    """The task ids a `deviation` of kind ``gate-waived`` names (ADR 0020). A waiver
    that gives no reason waives nothing, however the row got into the journal."""
    waived: Set[str] = set()
    for event in events:
        if (event.type == "deviation" and event.data.get("kind") == GATE_WAIVED
                and _waiver_reason(event.data) is not None):
            waived.update(_string_list(event.data.get("task_ids")))
    return waived


def _passed_task_ids(events: Iterable[Event]) -> Set[str]:
    """The task ids a passing `verify-run` names."""
    passed: Set[str] = set()
    for event in events:
        if event.type == "verify-run" and event.data.get("outcome") == "pass":
            passed.update(_string_list(event.data.get("task_ids")))
    return passed


def run_check(
    conn: sqlite3.Connection,
    session: str,
    db_path: Path,
    project_dir: Path,
    homes: Dict[str, str],
) -> CheckReport:
    """Detect semantic events missing for ``session`` (the Stop gate, ADR 0020).

    Two rules. Rule A: a Build Plan box is ticked in a worklog this session wrote, and
    no stream that owns the worklog holds its `task-done`. Rule C: this session recorded
    a `task-done` that no passing `verify-run` in its stream names. A `deviation` of kind
    ``gate-waived`` on the stream clears the task ids it names, for both rules.

    ``skipped`` lists each worklog the session wrote that rule A did not judge, with the
    reason, so a rule that cannot fire is visible. ``waivers`` holds one ready append per
    stream that would clear every finding there.
    """
    all_events = read_events(conn)
    session_events = [e for e in all_events if event_session(e) == session]
    by_stream: Dict[str, List[Event]] = {}
    for event in all_events:
        if is_work_stream(event.stream):
            by_stream.setdefault(event.stream, []).append(event)
    # The work streams this session itself appended to: where a finding's command points
    # when several streams own one worklog.
    driven = {
        e.stream for e in session_events
        if _actor_role(e) != "hook" and is_work_stream(e.stream)
    }
    findings: List[Dict[str, Any]] = []
    skipped: List[CheckSkip] = []

    # -- rule A: ticked build-plan boxes with no task-done ------------------
    # The artifacts this session wrote, as the fold decides it (ADR 0008): a row's own
    # `session` may name a session that only saw the write.
    authors = artifact_authors(all_events)
    worklog_paths: List[str] = []
    for event in all_events:
        if claim_of(event) is None:
            continue
        if authors.get(_artifact_key(event.data)) != session:
            continue
        path = event.data["path"]
        if (path and classify_artifact(path, homes) == "worklog"
                and path not in worklog_paths):
            worklog_paths.append(path)

    for path in worklog_paths:
        resolved = _resolve_artifact(project_dir, path)
        text = None
        if resolved.is_file():
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None
        if text is None:
            skipped.append({
                "path": path, "reason": "not-found",
                "detail": "the file is not readable under the project directory",
            })
            continue
        ticked = parse_ticked_tasks(text)
        if not ticked:
            continue

        # Only gate a flow the journal is actually tracking. A worklog can be written
        # without any flow behind it — a legacy artifact from before this journal
        # existed, or a vault sync pulling in someone else's edit — and blocking a
        # session over ticked boxes the user never touched would make the gate a
        # nuisance rather than a safeguard. So there is no fallback to "the stream this
        # session drives", and a finished flow's worklog stays closed.
        owners, finished = worklog_owners(conn, by_stream, path, project_dir, homes)
        if not owners:
            skipped.append({
                "path": path,
                "reason": "finished" if finished else "no-stream",
                "detail": (
                    "owned only by finished stream(s): " + ", ".join(finished)
                    if finished else
                    "no stream names this worklog in its events, and it is not the "
                    "newest worklog that a stream's slug names"
                ),
            })
            continue

        owned = [e for stream in owners + finished for e in by_stream[stream]]
        covered = {
            e.data.get("task_id") for e in owned if e.type == "task-done"
        } | _waived_task_ids(owned)
        target_stream = next((s for s in owners if s in driven), owners[0])
        # `append` looks for the passing verify-run on the stream it appends to, so the
        # hint reads that stream only.
        verified = _passed_task_ids(by_stream[target_stream])
        for task_id in ticked:
            if task_id in covered:
                continue
            detail = (
                f"{path}: Build Plan box {task_id} is ticked but no task-done event "
                f"records it"
            )
            if task_id not in verified:
                detail += (
                    f" — record a verify-run (outcome=pass) naming {task_id} first, "
                    "or append with --force and a reason"
                )
            findings.append({
                "missing": "task-done",
                "detail": detail,
                "stream": target_stream,
                "task_id": task_id,
                "suggested_command": _suggest(
                    db_path, target_stream, "task-done", {"task_id": task_id}
                ),
            })

    # -- rule C: task-done this session with no passing verify-run naming it
    # `append` refuses such a task-done, so only a forced one gets here. A verify-run
    # recorded afterwards counts: the command this finding suggests must clear it.
    judged: Set[Tuple[str, str]] = set()
    for event in session_events:
        if event.type != "task-done":
            continue
        task_id = event.data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        if (event.stream, task_id) in judged:
            continue
        judged.add((event.stream, task_id))
        stream_events = [e for e in all_events if e.stream == event.stream]
        if task_id in _passed_task_ids(stream_events) | _waived_task_ids(stream_events):
            continue
        findings.append({
            "missing": "verify-run",
            "detail": (
                f"{event.stream}: task-done {task_id} (seq {event.seq}) has no "
                "verify-run with outcome=pass naming it"
            ),
            "stream": event.stream,
            "task_id": task_id,
            "suggested_command": _suggest(db_path, event.stream, "verify-run", {
                "scope": "<what was run>",
                "commands": [{"cmd": "<command>", "exit": 0}],
                "outcome": "pass",
                "task_ids": [task_id],
            }),
        })

    per_stream: Dict[str, List[str]] = {}
    for finding in findings:
        ids = per_stream.setdefault(finding["stream"], [])
        if finding["task_id"] not in ids:
            ids.append(finding["task_id"])
    waivers: List[CheckWaiver] = [
        {
            "stream": stream,
            "task_ids": ids,
            "command": _suggest(db_path, stream, "deviation", {
                "kind": GATE_WAIVED,
                "task_ids": ids,
                "note": WAIVER_NOTE_PLACEHOLDER,
            }),
        }
        for stream, ids in per_stream.items()
    ]
    return {"findings": findings, "skipped": skipped, "waivers": waivers}


def record_check(conn: sqlite3.Connection, session: str, report: CheckReport) -> None:
    """Overwrite the one `meta` value that says when the gate last ran (ADR 0020).

    The Stop hook asks for it, so `doctor` can tell a gate that runs and finds nothing
    from one that never runs. A failed write is ignored: the result does not depend on it.
    """
    try:
        if not _table_exists(conn, "meta"):
            return
        _set_meta(conn, LAST_CHECK_KEY, json.dumps({
            "at": utc_now(),
            "session": session,
            "findings": len(report["findings"]),
            "skipped": len(report["skipped"]),
        }, sort_keys=True))
    except sqlite3.Error:
        return


def stop_gate_trace(conn: sqlite3.Connection) -> Dict[str, Any]:
    """``doctor``'s view of the Stop gate: the last recorded check and the last block."""
    last_check = None
    if _table_exists(conn, "meta"):
        try:
            stored = json.loads(get_meta(conn, LAST_CHECK_KEY) or "null")
        except ValueError:
            stored = None
        # A value this code did not write reads as "no check recorded".
        if (isinstance(stored, dict)
                and isinstance(stored.get("at"), str)
                and isinstance(stored.get("session"), str)
                and _is_count(stored.get("findings"))
                and _is_count(stored.get("skipped"))):
            last_check = {key: stored[key] for key in
                          ("at", "session", "findings", "skipped")}
    last_block = None
    row = conn.execute(
        "SELECT ts, data FROM events WHERE type = 'gate-blocked' "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is not None:
        try:
            data = json.loads(row["data"] or "{}")
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        last_block = {
            "at": row["ts"],
            "session": _string_or_none(data.get("session")),
            "findings": data.get("findings") if _is_count(data.get("findings")) else None,
        }
    return {"last_check": last_check, "last_block": last_block}


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def render_skipped(skipped: Sequence[CheckSkip]) -> str:
    lines = [f"{len(skipped)} worklog(s) this session wrote were not judged:"]
    for skip in skipped:
        reason = skip["reason"].replace("-", " ")
        lines.append(
            f"  • {_one_line(skip['path'])}: {reason} — {_one_line(skip['detail'])}"
        )
    return "\n".join(lines)


def render_findings(findings: Sequence[Dict[str, Any]]) -> str:
    lines = [
        f"{len(findings)} missing semantic event(s) for this session — "
        "append them, then stop again:"
    ]
    for finding in findings:
        lines.append(
            f"  • missing {finding['missing']}: {_one_line(finding['detail'])}"
        )
        lines.append(f"      {finding['suggested_command'] or NO_COMMAND}")
    return "\n".join(lines)
