"""Duplicate detection, implied phases, automatic deviations, the insert."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Tuple

from .vocab import (
    ARTIFACT_CLAIM_DEDUPE_SECONDS, ARTIFACT_DEDUPE_SECONDS, EVENT_VOCABULARY, InfraError,
    PHASE_OF_EVENT, PHASE_ORDER, RECORDED_BY_KEY, SIGNALS_MISSING_KIND,
    SIGNALS_MISSING_NOTE, VersionConflict,
)
from .plugin import _hooks_common
from .store import _row_to_event, _seconds_since, current_version, Event, utc_now
from .sessions import _actor_session, parse_actor, recorded_by_for
from .fold import folded_phase
from .artifacts import _artifact_key, _claim_rank, claim_of
from .shapes import check_payload_size, normalize_payload, validate_event_type
from .gates import (
    _refuse_closeout_placeholders, _refuse_read_go, _require_closure_reason,
    _validate_go_request, _validate_mr_opened, _validate_own_session, _validate_waiver,
    validate_gate,
)


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


class AppendResult(NamedTuple):
    seq: int
    version: int
    implied_phase: Optional[str] = None
    duplicate: bool = False
    # The version `--expect` was compared against, so a caller that lost a race can
    # see what it was actually holding.
    version_before: int = 0
    # The `deviation` the append recorded for its own event (ADR 0011), when it did.
    # `version` is then the stream head, the deviation's version, one past the event's
    # own: a caller chaining `--expect` needs the head, which is what it always was.
    deviation_seq: Optional[int] = None


def _recent_duplicate_artifact(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """The ``(seq, version)`` of the row this ``artifact-written`` merely repeats.

    What counts as a repeat depends on what the new row claims (ADR 0008):
    - an authored claim (``tool`` or ``bash`` naming a session) repeats a row only when
      the same session already claimed the same path and mtime, with evidence at least
      as strong, within ``ARTIFACT_CLAIM_DEDUPE_SECONDS``. An observation or another
      session's claim never swallows it: the read-time fold needs every author's claim,
      and a weaker claim landing first must not hide a stronger one;
    - anything else (a ``disk`` observation, a row that names no author) repeats any
      row for the same path and mtime within ``ARTIFACT_DEDUPE_SECONDS``.

    Every earlier row of the path inside the window is searched, not just the last
    row. A row stamped in the future is never a duplicate — a clock that ran
    backwards would otherwise swallow every subsequent write.

    Accepted: `--force` does not bypass this, so two genuine writes of one path inside
    the window that leave an identical mtime collapse into the first one's row.
    """
    path = data.get("path")
    if not isinstance(path, str) or not path:
        return None
    claim = claim_of(Event(0, stream, 0, "artifact-written", data, "", None))
    authored = (
        claim is not None and claim["source"] != "disk" and claim["session"] is not None
    )
    window = ARTIFACT_CLAIM_DEDUPE_SECONDS if authored else ARTIFACT_DEDUPE_SECONDS
    key = _artifact_key(data)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=window)).isoformat()
    rows = conn.execute(
        "SELECT seq, stream, version, type, data, ts, actor FROM events "
        "WHERE stream = ? AND type = 'artifact-written' AND ts >= ? "
        "AND json_extract(data, '$.path') = ? "
        "ORDER BY seq DESC LIMIT 50",
        (stream, cutoff, path),
    ).fetchall()
    for row in rows:
        previous = _row_to_event(row)
        if previous.data.get("path") != path or _artifact_key(previous.data) != key:
            continue
        elapsed = _seconds_since(previous.ts, now)
        if elapsed is None or not 0 <= elapsed <= window:
            continue
        if authored:
            earlier = claim_of(previous)
            if (
                earlier is None
                or earlier["session"] != claim["session"]
                or _claim_rank(earlier) < _claim_rank(claim)
            ):
                continue
        return previous.seq, previous.version
    return None


def _implied_phase_payload(
    previous: Optional[str], phase: str, event_type: str
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "phase": phase,
        "implied": True,
        "implied_by": event_type,
    }
    start = PHASE_ORDER.index(previous) + 1 if previous in PHASE_ORDER else 0
    skipped = PHASE_ORDER[start: PHASE_ORDER.index(phase)]
    if skipped:
        payload["skipped"] = skipped
    return payload


def _auto_deviation(event_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The deviation this event records about itself, if any (ADR 0011)."""
    if (
        event_type == "phase-entered"
        and payload.get("phase") == "route-and-map"
        and "signals" not in payload
    ):
        return {"note": SIGNALS_MISSING_NOTE, "kind": SIGNALS_MISSING_KIND, "auto": True}
    return None


def append_event(
    conn: sqlite3.Connection,
    stream: str,
    event_type: str,
    data: Dict[str, Any],
    project_dir: Path,
    expect: Optional[int] = None,
    actor: Optional[str] = None,
    force: bool = False,
    force_reason: Optional[str] = None,
    allow_new_type: bool = False,
) -> AppendResult:
    """Append one event.

    ``UNIQUE(stream, version)`` is the real concurrency guard; ``BEGIN IMMEDIATE``
    serializes writers so the common path never collides. On the rare
    IntegrityError we recompute the version once — unless the caller asked for a
    conditional append, in which case the collision *is* the conflict.
    """
    # The vocabulary check is not a gate precondition — it is about whether this event
    # can ever be read — so `--force` does not waive it; `--new-type` does.
    validate_event_type(event_type, allow_new_type)
    canonical_actor = parse_actor(actor, conn, data)

    # Before the shape check and on the forced path too (#52).
    _refuse_read_go(conn, stream, event_type, data)
    payload = dict(data)
    if force:
        payload["forced"] = True
        payload["force_reason"] = force_reason
    if allow_new_type and event_type not in EVENT_VOCABULARY:
        payload["new_type"] = True
    # Like the vocabulary check, this is about whether the event can be read at all,
    # so `--force` does not waive it.
    payload = normalize_payload(event_type, payload)
    _refuse_closeout_placeholders(event_type, payload)
    check_payload_size(stream, payload, force, force_reason)
    # After the cap check: the key is the journal's bookkeeping, not prose the caller
    # wrote, so it must not refuse a payload the caller kept inside the cap. The journal
    # owns it, so a caller's own value never survives (ADR 0010).
    payload.pop(RECORDED_BY_KEY, None)
    recorded_by = recorded_by_for(conn, canonical_actor)
    if recorded_by:
        payload[RECORDED_BY_KEY] = recorded_by

    for attempt in range(2):
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = current_version(conn, stream)
            if expect is not None and existing != expect:
                conn.execute("ROLLBACK")
                raise VersionConflict(stream, expect, existing)
            if event_type == "artifact-written":
                repeated = _recent_duplicate_artifact(conn, stream, payload)
                if repeated is not None:
                    conn.execute("ROLLBACK")
                    return AppendResult(
                        repeated[0], repeated[1], duplicate=True,
                        version_before=existing,
                    )
            _validate_own_session(conn, event_type, payload, canonical_actor, actor)
            if not force:
                validate_gate(conn, stream, event_type, payload, project_dir)
            else:
                _require_closure_reason(
                    conn, stream, event_type, payload, force_reason
                )
                if event_type == "deviation":
                    _validate_waiver(payload)
                elif event_type == "go-requested":
                    _validate_go_request(conn, stream)
                elif event_type == "mr-opened":
                    # No forced event opens a publish (ADR 0023 §17).
                    _validate_mr_opened(conn, stream, payload)

            version = existing + 1
            implied_phase = PHASE_OF_EVENT.get(event_type)
            if implied_phase is not None:
                previous = folded_phase(conn, stream)
                if previous == implied_phase:
                    implied_phase = None
                else:
                    implied = _implied_phase_payload(
                        previous, implied_phase, event_type
                    )
                    if recorded_by:
                        implied[RECORDED_BY_KEY] = recorded_by
                    _insert_event(
                        conn, stream, version, "phase-entered", implied,
                        canonical_actor,
                    )
                    version += 1

            seq = _insert_event(
                conn, stream, version, event_type, payload, canonical_actor
            )
            deviation_seq = None
            deviation = _auto_deviation(event_type, payload)
            if deviation is not None:
                if recorded_by:
                    deviation[RECORDED_BY_KEY] = recorded_by
                version += 1
                deviation_seq = _insert_event(
                    conn, stream, version, "deviation", deviation, canonical_actor
                )
            conn.execute("COMMIT")
            if event_type == "go-requested":
                _touch_request_marker(conn, canonical_actor)
            return AppendResult(
                seq, version, implied_phase, version_before=existing,
                deviation_seq=deviation_seq,
            )
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            if expect is not None:
                raise VersionConflict(stream, expect, current_version(conn, stream))
            if attempt == 0:
                continue
            raise
        except Exception:
            _rollback_quietly(conn)
            raise

    raise InfraError(f"could not append to stream {stream!r} after a retry")


def _touch_request_marker(conn: sqlite3.Connection, actor: str) -> None:
    """Leave the empty marker file of the session that recorded a go request (§12).

    The recorder runs the journal for a long prompt only when its session's marker
    exists. The file is a hint, never a rule: a write that fails costs one warning line,
    and the append it follows has already landed.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    db_file = row[2] if row is not None else None
    session = _actor_session(conn, actor)
    path = _hooks_common.marker_path(db_file, session) if db_file else None
    if path is None:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
    except Exception as error:  # noqa: BLE001 — a hint never fails a landed append
        print(f"warning: the go request landed, but its marker file could not be "
              f"written ({error}); the recorder then reads only short prompts",
              file=sys.stderr)


def _insert_event(
    conn: sqlite3.Connection,
    stream: str,
    version: int,
    event_type: str,
    payload: Dict[str, Any],
    actor: Optional[str],
) -> int:
    cursor = conn.execute(
        "INSERT INTO events (stream, version, type, data, ts, actor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (stream, version, event_type, json.dumps(payload, sort_keys=True),
         utc_now(), actor),
    )
    return int(cursor.lastrowid)


def _rollback_quietly(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass
