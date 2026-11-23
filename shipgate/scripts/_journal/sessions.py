"""Who wrote a row: actor labels, the appending session, which session a row binds."""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Optional

from .vocab import (
    ACTOR_ROLES, InfraError, RECORDED_BY_KEY, RECORDED_BY_ROLES, SESSION_ENV,
    SESSIONLESS_ROLES, UsageError,
)
from .store import _set_meta, _table_exists, Event, get_meta


def current_session(conn: sqlite3.Connection) -> Optional[str]:
    """The session id the SessionStart hook stored last, if any (ADR 0003).

    Diagnostic only, for `session --get`: the session that started last. Since #46 no
    append reads it as its own session (ADR 0005, amendment 2026-11-20).
    """
    if not _table_exists(conn, "meta"):
        return None
    return get_meta(conn, "current_session") or None


def set_current_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Record the session id (ADR 0003). One statement, so no explicit transaction."""
    if not _table_exists(conn, "meta"):
        raise InfraError(
            "this journal has no meta table, so the session cannot be recorded — "
            "run `journal.py init`"
        )
    _set_meta(conn, "current_session", session_id)


def parse_actor(
    raw: Optional[str],
    conn: sqlite3.Connection,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """Canonicalize ``--actor`` to ``role[@label]`` (ADR 0003).

    An event that already names its session in the payload — every hook-written one —
    keeps the bare role, so the two never disagree about which session it was. So does
    an observation (``observed_by`` in the payload, ADR 0008): the hook's environment
    names the session that saw the write, and labelling the row with it would make the
    observer its author again.
    """
    role, separator, label = (raw or "orchestrator").partition("@")
    if role not in ACTOR_ROLES:
        raise UsageError(
            f"actor role {role!r} is not one of {', '.join(ACTOR_ROLES)} — "
            "pass `role` or `role@label` (label = session id, agent, watcher)"
        )
    if separator and label:
        return f"{role}@{label}"
    if role in SESSIONLESS_ROLES:
        return role
    if isinstance(data, dict):
        session = data.get("session")
        if isinstance(session, str) and session:
            return role
        if "observed_by" in data:
            return role
    session_id = appending_session(conn)
    return f"{role}@{session_id}" if session_id else role


def appending_session(conn: sqlite3.Connection) -> Optional[str]:
    """The session running this append (ADR 0005): the shell's ``CLAUDE_CODE_SESSION_ID``,
    else None.

    Never ``meta.current_session``: that names the session that started last, which need
    not be the one appending (#46). A shell with no variable — a mod's process run, a client
    older than 2.1.132, a terminal outside Claude Code — records no session, so its row
    binds and counts for none. ``conn`` stays in the signature for its callers.
    """
    return os.environ.get(SESSION_ENV, "").strip() or None


def recorded_by_for(conn: sqlite3.Connection, actor: str) -> Optional[str]:
    """The session to record under ``recorded_by`` for this append, or None (ADR 0010).

    Only a ``user`` row gets one, whatever its label: the label names a person, and the
    writing session is a separate fact. The journal owns the key: ``append_event`` drops
    any value the caller passed, so a payload cannot name another session.
    """
    if actor.partition("@")[0] not in RECORDED_BY_ROLES:
        return None
    return appending_session(conn)


# The markers of a go the user's own row carries (actor role `user`, ADR 0023 §2).
USER_MARKERS = ("dialog", "shell", "question", "prompt")
# The marker of 0.28.0's read go, retired by #52 (ADR 0023 amendment A3, A4): `append`
# refuses it, a row that holds it is no go, and such a row still binds no session.
RETIRED_READ_MARKER = "read"


def _is_seq(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def writer_session(event: Event) -> Optional[str]:
    """The session that appended a row, whether or not the row binds it to its stream.

    A ``user`` row names it under ``recorded_by`` (ADR 0010); a machine role's row in
    its actor label. A ``watcher`` row and an unlabelled actor name none. A go request
    is read this way (ADR 0023 §13), never by ``event_session``.
    """
    role = _actor_role(event)
    if role in RECORDED_BY_ROLES:
        recorded_by = event.data.get(RECORDED_BY_KEY)
        return recorded_by if isinstance(recorded_by, str) and recorded_by else None
    if role in SESSIONLESS_ROLES:
        return None
    if event.actor and "@" in event.actor:
        return event.actor.split("@", 1)[1] or None
    return None


def _actor_session(conn: sqlite3.Connection, actor: str) -> Optional[str]:
    """The session an append runs in, as its canonical actor says (``writer_session``)."""
    role, _, label = actor.partition("@")
    if role in RECORDED_BY_ROLES:
        return appending_session(conn)
    if role in SESSIONLESS_ROLES:
        return None
    return label or None


NON_BINDING_TYPES = frozenset({"go-requested", "reply-witnessed"})
# A read go of 0.28.0 stays non-binding, so a lead's position does not move at the
# upgrade (#52, amendment A4).
NON_BINDING_MARKERS = frozenset({"question", "prompt", RETIRED_READ_MARKER})


def binds_session(event: Event) -> bool:
    """False for a row of the approval path, which binds no session (ADR 0023 §13)."""
    if event.type in NON_BINDING_TYPES:
        return False
    return not (
        event.type == "gate-decision"
        and event.data.get("source") in NON_BINDING_MARKERS
    )


def request_session(event: Event) -> Optional[str]:
    """The session that recorded a go request: the one whose reply answers it (§4)."""
    return writer_session(event)


def event_session(event: Event) -> Optional[str]:
    """Which session an event belongs to.

    Hook-written events carry ``data.session``; a ``user`` row carries
    ``data.recorded_by`` (ADR 0010); a machine role's row carries it as the ``role@label``
    suffix `append` fills in from the appending session. They are read in that order. The
    label of a sessionless role (``user``, ``watcher``) names a person or a watcher, never
    a session, so it is not read; an actor with no label belongs to no particular session.

    Who wrote an artifact is a different question: an ``artifact-written`` row may name
    only the session that saw the write, so its author comes from ``artifact_authors``.

    The rows of the approval path belong to no session here (ADR 0023 §13): a
    ``go-requested``, a ``reply-witnessed`` and a ``gate-decision`` with the marker
    ``question``, ``prompt`` or 0.28.0's ``read``. A lead that asks the user about five
    streams drives none of them, so ``session_stream``, ``check`` and ``stats`` skip these
    rows. ``request_session`` and ``writer_session`` still read who wrote them.
    """
    if not binds_session(event):
        return None
    session = event.data.get("session")
    if isinstance(session, str) and session:
        return session
    role = _actor_role(event)
    if role in RECORDED_BY_ROLES:
        recorded_by = event.data.get(RECORDED_BY_KEY)
        if isinstance(recorded_by, str) and recorded_by:
            return recorded_by
    if role in SESSIONLESS_ROLES:
        return None
    if event.actor and "@" in event.actor:
        return event.actor.split("@", 1)[1] or None
    return None


def _actor_role(event: Event) -> str:
    return (event.actor or "").split("@", 1)[0] or "unattributed"
