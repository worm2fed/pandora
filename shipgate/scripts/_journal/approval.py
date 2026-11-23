"""The user's go: commit and publish authorization read from rows."""

from __future__ import annotations

from typing import (
    Any, Dict, List, Literal, Optional, Sequence, Tuple, TypedDict, Union, get_args,
)

from .vocab import DecisionSource, GoGate, ReviewVerdict
from .store import Event
from .sessions import _actor_role, USER_MARKERS


def _go_gate(data: Dict[str, Any]) -> Optional[str]:
    """The gate a ``gate-decision`` payload is a go for, or None (ADR 0023 §1).

    The gate is ``commit`` or ``publish``, the user raised it, the ``decision`` names
    the gate (trimmed, any case) and ``source`` is one of the four markers. Every
    condition matters: the orchestrator can raise a gate and answer it itself, so a row
    that only *sits at* the gate, or records "no" there, would otherwise let the flow
    authorize itself. A ``decision`` that is not a string (a row from before the
    ``strings`` rule) is no go (audit D6); an unmarked row, older rows included, is none
    either (ADR 0015), and neither is a read go of 0.28.0 (#52). The actor is
    ``_user_go_events``'s to check.
    """
    gate = data.get("gate")
    decision = data.get("decision")
    if gate not in get_args(GoGate) or data.get("raised_by") != "user":
        return None
    if not isinstance(decision, str) or decision.strip().lower() != gate:
        return None
    if data.get("source") not in get_args(DecisionSource):
        return None
    return gate


def _user_go_events(events: Sequence[Event]) -> List[Tuple[Event, str]]:
    """Each go after the stream's last ``task-done``, with its gate, in seq order.

    A go is a row with a user marker and the actor role ``user``. A read go of 0.28.0
    is none, whatever its witness (#52, ADR 0023 amendment A4).
    """
    ordered = sorted(events, key=lambda event: event.seq)
    last_task_done_seq = max(
        (event.seq for event in ordered if event.type == "task-done"), default=0
    )
    found: List[Tuple[Event, str]] = []
    for event in ordered:
        if event.type != "gate-decision" or event.seq <= last_task_done_seq:
            continue
        gate = _go_gate(event.data)
        if gate is None:
            continue
        if event.data.get("source") in USER_MARKERS and _actor_role(event) == "user":
            found.append((event, gate))
    return found


PublishBy = Literal["review-verdict", "gate-decision"]


class PublishHeld(TypedDict):
    """Nothing after the stream's last ``task-done`` authorizes publishing."""

    kind: Literal["held"]


class PublishAuthorized(TypedDict):
    """The event that authorizes publishing: its type, ``seq`` and ``ts``."""

    kind: Literal["authorized"]
    by: PublishBy
    seq: int
    at: str


# May the stream publish? The `mr-opened` gate, `status --json` and `position` all read
# this one value, from one helper (ADR 0009).
PublishAuthorization = Union[PublishHeld, PublishAuthorized]


class GoAnswer(TypedDict):
    """``go`` in ``status --json`` and ``position --json`` (ADR 0023 §16): the user's
    go for each gate, in the shape of ``publish``. ``by`` is always ``gate-decision``."""

    commit: PublishAuthorization
    publish: PublishAuthorization


def user_go(events: Sequence[Event], gate: str) -> PublishAuthorization:
    """The user's go for ``gate`` on one stream, and the row that gives it (ADR 0023).

    ``events`` are one stream's, in any order. The first go after the last
    ``task-done`` at ``gate`` gives ``{kind: authorized, by: gate-decision, seq, at}``;
    a publish go also satisfies the commit gate. A ready verdict is no go. None gives
    ``{kind: held}``. The command gate (``authorize``), ``status`` and ``position`` read
    this one helper, and ``publish_authorization`` reads it for its go branch.
    """
    for event, go_gate in _user_go_events(events):
        if go_gate == gate or (gate == "commit" and go_gate == "publish"):
            return {
                "kind": "authorized", "by": "gate-decision",
                "seq": event.seq, "at": event.ts,
            }
    return {"kind": "held"}


def commit_authorization(events: Sequence[Event]) -> PublishAuthorization:
    """May a model commit on this stream? Only with the user's go (ADR 0023 §14)."""
    return user_go(events, "commit")


def go_answer(events: Sequence[Event]) -> GoAnswer:
    return {"commit": user_go(events, "commit"), "publish": user_go(events, "publish")}


def publish_authorization(events: Sequence[Event]) -> PublishAuthorization:
    """Whether one stream's events authorize publishing, and which event did.

    ``events`` are one stream's, in any order; the rule reads them in seq order. After
    the last ``task-done`` (seq 0 when there is none), the first event that is either
    the newest ``review-verdict`` that is not a forced ready (ADR 0023 §17 skips one),
    when it says ``verdict: ready``, or the user's publish go (``user_go``) gives
    ``{kind: authorized, by: <its type>, seq, at: <its ts>}``. No such event gives
    ``{kind: held}``.

    The newest verdict decides (#40): a ``not-ready`` verdict after a ready one takes
    the ready one back, as when the built-in ``/security-review`` finds something on
    the commit after the briefed pass said ready. It does not take back the user's
    publish go, which the command gate reads the same way.

    ``_validate_mr_opened`` raises when this is held, ``fold_stream`` prints it as
    ``publish`` and ``build_position`` copies it, so the gate and the HUD cannot
    disagree.
    """
    ordered = sorted(events, key=lambda event: event.seq)
    last_task_done_seq = max(
        (event.seq for event in ordered if event.type == "task-done"), default=0
    )
    # A forced ready is skipped (ADR 0023 §17); a not-ready holds, forced or not.
    newest = next(
        (
            event for event in reversed(ordered)
            if event.seq > last_task_done_seq
            and event.type == "review-verdict"
            and event.data.get("verdict") in get_args(ReviewVerdict)
            and not (event.data.get("verdict") == "ready" and event.data.get("forced"))
        ),
        None,
    )
    verdict = (
        newest if newest is not None and newest.data.get("verdict") == "ready" else None
    )
    go = user_go(ordered, "publish")
    if go["kind"] == "authorized" and (verdict is None or go["seq"] < verdict.seq):
        return go
    if verdict is not None:
        return {
            "kind": "authorized", "by": "review-verdict",
            "seq": verdict.seq, "at": verdict.ts,
        }
    return {"kind": "held"}
