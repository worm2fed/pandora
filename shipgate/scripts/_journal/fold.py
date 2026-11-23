"""A stream folded into its state: lifecycle, phase, marks, dispositions, branch binding."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, TypedDict, get_args

from .vocab import (
    CAPTURE_TERMINAL_HOURS, Disposition, DORMANT_DAYS, FEATURE_STREAM_PREFIX, FindingState,
    META_STREAM, OWNERSHIP_MINUTES, Phase, PHASE_ORDER, REVIVING_TYPES, TERMINAL_TYPES,
    WATCH_STREAM_PREFIX,
)
from .text import _string_or_none, _vocabulary_map
from .store import _seconds_since, Event, read_events
from .sessions import _actor_role, event_session
from .approval import go_answer, GoAnswer, publish_authorization, PublishAuthorization


def _last_phase_spelling(conn: sqlite3.Connection, stream: str) -> Optional[str]:
    """The newest ``phase-entered``'s ``phase`` as written, in or out of the order."""
    for event in reversed(read_events(conn, stream=stream, types=("phase-entered",))):
        candidate = event.data.get("phase")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def folded_phase(conn: sqlite3.Connection, stream: str) -> Optional[str]:
    """The phase a stream's ``phase-entered`` history leaves it in."""
    phase: Optional[str] = None
    for event in read_events(conn, stream=stream, types=("phase-entered",)):
        candidate = event.data.get("phase")
        if candidate in PHASE_ORDER:
            phase = candidate
    return phase


# --------------------------------------------------------------------------
# Derived views
# --------------------------------------------------------------------------


def is_work_stream(stream: str) -> bool:
    """Every stream except the tool's own is work worth reporting.

    Defining this by exclusion rather than by a `feature/` prefix is deliberate: a
    session that names its stream after the branch (`fix/1290-date-off-by-one`) is doing
    something reasonable — arguably better, since it ties the journal to the branch —
    and a prefix allowlist silently hid whole flows from `status`.
    """
    return stream != META_STREAM and not stream.startswith(WATCH_STREAM_PREFIX)


def feature_slug(stream: str) -> str:
    return stream[len(FEATURE_STREAM_PREFIX):] if stream.startswith(
        FEATURE_STREAM_PREFIX
    ) else stream


Lifecycle = Literal["live", "dormant", "terminal"]
PhaseMark = Literal["done", "skipped", "current", "revisited", "todo"]


class CurrentPhase(TypedDict):
    """The phase a stream is in: its last ``phase-entered`` whose phase is in the order."""

    phase: Phase
    entered_at: str
    implied: bool


class StatusFeatureAdditions(TypedDict):
    """The keys each ``fold_stream`` entry gains in ``status --json`` (ADR 0009).

    ``fold_stream`` still returns a plain dict and keeps every key it prints today
    (``phase``, ``phase_entered_at``, ``implied_phase``, ``terminal``, ``dormant``, ...),
    so an older reader keeps working; these three join them. ``lifecycle`` restates
    ``terminal`` and ``dormant`` as one closed value; ``current`` restates the three
    phase keys and is null exactly when ``phase`` is (audit D7); ``publish`` is
    ``publish_authorization`` over the stream's events. Bodies: T010 (``publish``),
    T011 (``lifecycle``, ``current``). ``go`` is ``go_answer``: the user's go for each
    gate, which the command gate reads (ADR 0023).
    """

    publish: PublishAuthorization
    go: GoAnswer
    lifecycle: Lifecycle
    current: Optional[CurrentPhase]


def stream_lifecycle(terminal: bool, age_days: Optional[int]) -> Lifecycle:
    """The fold's ``terminal`` and ``dormant`` flags as one closed value.

    The arguments are what ``fold_stream`` computes: ``terminal`` (a ``TERMINAL_TYPES``
    event no ``REVIVING_TYPES`` event followed, or a ``capture-done`` older than
    ``CAPTURE_TERMINAL_HOURS``) and ``age_days`` (whole days since the last event, None
    with no events). ``terminal`` gives ``terminal``; else an age of ``DORMANT_DAYS`` or
    more gives ``dormant``; else ``live``. That is the split the ``dormant`` key makes,
    so the two never disagree.
    """
    if terminal:
        return "terminal"
    if age_days is not None and age_days >= DORMANT_DAYS:
        return "dormant"
    return "live"


def current_phase(
    phase: Optional[str], entered_at: Optional[str], implied: bool
) -> Optional[CurrentPhase]:
    """The fold's three phase keys as one value, or None when no phase was entered.

    The arguments are what ``fold_stream`` tracks: the phase of the last
    ``phase-entered`` whose phase is in ``PHASE_ORDER``, that event's ``ts``, and its
    ``implied`` flag. A stream with only ``flow-started`` has no phase and gives None,
    never ``workspace`` (audit D7).
    """
    if phase not in PHASE_ORDER or entered_at is None:
        return None
    return {"phase": phase, "entered_at": entered_at, "implied": implied}


def phase_marks(events: Sequence[Event]) -> Dict[Phase, PhaseMark]:
    """A mark for every phase in ``PHASE_ORDER``, from one stream's events.

    Only ``phase-entered`` events count, and only phases in ``PHASE_ORDER``: the rule
    ``fold_stream`` uses. A phase is *entered* when such an event names it in ``phase``.
    - The phase the stream is in is ``current``.
    - A phase before it is ``done`` when the stream entered it and left it, else
      ``skipped``: never entered is skipped, whether or not an event lists it in
      ``skipped`` (audit D8).
    - A phase after it is ``revisited`` when the stream entered it before moving back
      past it (review, then implement again, leaves review ``revisited``), else ``todo``.
    - With no phase entered, every phase is ``todo``.
    Every phase in ``PHASE_ORDER`` has a key.
    """
    entered: List[str] = []
    for event in sorted(events, key=lambda e: e.seq):
        if event.type == "phase-entered" and event.data.get("phase") in PHASE_ORDER:
            entered.append(event.data["phase"])
    marks: Dict[Phase, PhaseMark] = {}
    current = PHASE_ORDER.index(entered[-1]) if entered else None
    for index, phase in enumerate(get_args(Phase)):
        if current is None:
            marks[phase] = "todo"
        elif index == current:
            marks[phase] = "current"
        elif index < current:
            marks[phase] = "done" if phase in entered else "skipped"
        else:
            marks[phase] = "revisited" if phase in entered else "todo"
    return marks


def fold_stream(
    events: Sequence[Event], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Fold a stream's events into its entry in the status brief."""
    phase: Optional[str] = None
    phase_entered_at: Optional[str] = None
    phase_implied = False
    terminal = False
    gate_decisions: List[Dict[str, Any]] = []
    queued: Dict[str, Dict[str, Any]] = {}
    last_verify: Optional[Dict[str, Any]] = None
    task_ids: List[str] = []

    for event in events:
        if event.type in TERMINAL_TYPES:
            terminal = True
        elif event.type in REVIVING_TYPES:
            terminal = False

        if event.type == "phase-entered":
            # Same rule as `folded_phase`: a phase outside the declared order (an
            # imported row spelling it `Implement`) is not a position the brief or
            # the ordering gate can reason about, so neither of them adopts it.
            candidate = event.data.get("phase")
            if candidate in PHASE_ORDER:
                phase = candidate
                phase_entered_at = event.ts
                phase_implied = bool(event.data.get("implied"))
        elif event.type == "gate-decision":
            # Start from the event's own payload so a decision recorded under a
            # different shape keeps its content, then overlay the canonical keys.
            # Normalizing first would replace real detail with a row of nulls.
            folded = {k: v for k, v in event.data.items() if v is not None}
            for key in ("gate", "question", "decision", "mode", "rationale"):
                value = event.data.get(key)
                if value is not None:
                    folded[key] = value
            folded["ts"] = event.ts
            gate_decisions.append(folded)
        elif event.type == "design-queued":
            issue = event.data.get("issue")
            if issue is not None:
                queued[str(issue)] = {
                    "issue": issue,
                    "assumes": event.data.get("assumes"),
                    "ts": event.ts,
                }
        elif event.type in ("design-committed", "design-invalidated"):
            issue = event.data.get("issue")
            if issue is not None:
                queued.pop(str(issue), None)
        elif event.type == "verify-run":
            last_verify = {
                "outcome": event.data.get("outcome"),
                "scope": event.data.get("scope"),
                "task_ids": event.data.get("task_ids"),
                "ts": event.ts,
            }
        elif event.type == "task-done":
            task_id = event.data.get("task_id")
            if isinstance(task_id, str) and task_id not in task_ids:
                task_ids.append(task_id)

    last = events[-1] if events else None
    age = _seconds_since(last.ts, now) if last else None
    age_days = int(age // 86400) if age is not None else None
    if (
        not terminal
        and last is not None
        and last.type == "capture-done"
        and age is not None
        and age > CAPTURE_TERMINAL_HOURS * 3600
    ):
        terminal = True

    return {
        "stream": events[0].stream if events else None,
        "feature": feature_slug(events[0].stream) if events else None,
        "version": last.version if last else 0,
        "phase": phase,
        "phase_entered_at": phase_entered_at,
        "implied_phase": phase_implied,
        "last_event": (
            {"seq": last.seq, "type": last.type, "ts": last.ts} if last else None
        ),
        "age_days": age_days,
        "terminal": terminal,
        "dormant": bool(
            not terminal and age_days is not None and age_days >= DORMANT_DAYS
        ),
        "gate_decisions": gate_decisions,
        "gate_decision_count": len(gate_decisions),
        "open_designs": list(queued.values()),
        "last_verify": last_verify,
        "tasks_done": len(task_ids),
        "task_ids": task_ids,
        "publish": publish_authorization(events),
        "go": go_answer(events),
        "lifecycle": stream_lifecycle(terminal, age_days),
        "current": current_phase(phase, phase_entered_at, phase_implied),
        "last_writer": last_writer(events),
        "pull_request": pull_request(events),
    }


def pull_request(events: Sequence[Event]) -> Optional[Dict[str, Optional[str]]]:
    """``{url, ref, ts}`` of the newest ``mr-opened``, or None (ADR 0024). A value that
    is not a string is None."""
    opened = [e for e in events if e.type == "mr-opened"]
    if not opened:
        return None
    data = opened[-1].data
    return {"url": _string_or_none(data.get("url")),
            "ref": _string_or_none(data.get("ref")), "ts": opened[-1].ts}


def last_writer(events: Sequence[Event]) -> Optional[Dict[str, str]]:
    """``{session, ts}`` of the newest row that binds a session and no hook wrote, or
    None (ADR 0024). The rule is ``session_stream``'s: a hook files a write under the
    checked-out branch, and a row of the approval path binds no session
    (``event_session``)."""
    for event in reversed(events):
        session = event_session(event)
        if session is not None and _actor_role(event) != "hook":
            return {"session": session, "ts": event.ts}
    return None


def other_session(entry: Dict[str, Any], session: Optional[str],
                  now: Optional[datetime] = None) -> Optional[Dict[str, int]]:
    """``{minutes}`` when another session than ``session`` wrote the stream within
    ``OWNERSHIP_MINUTES``, else None; always None with no ``session`` (FR-007)."""
    writer = entry.get("last_writer")
    if not session or not writer or writer["session"] == session:
        return None
    age = _seconds_since(writer["ts"], now)
    if age is None or age > OWNERSHIP_MINUTES * 60:
        return None
    return {"minutes": max(0, int(age // 60))}


def branch_stream_candidates(branch: str) -> List[str]:
    """Stream names a git branch could plausibly be journaled under.

    The convention is stream name = branch name. Failing that, the branch's last path
    segment is tried with and without the `feature/` prefix, so branch
    `fix/1290-date-off-by-one` also finds streams `feature/1290-date-off-by-one` and
    `1290-date-off-by-one`. Most exact first.
    """
    slug = branch.rsplit("/", 1)[-1]
    candidates = [
        branch,
        FEATURE_STREAM_PREFIX + branch,
        FEATURE_STREAM_PREFIX + slug,
        feature_slug(branch),
        slug,
    ]
    unique: List[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def branch_match(branch: str, streams: Sequence[str]) -> Optional[str]:
    available = set(streams)
    for candidate in branch_stream_candidates(branch):
        if candidate in available:
            return candidate
    return None


def nested_branch_match(branches: Sequence[str],
                        folded: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The stream to put first when the checkout is an umbrella, or None (the 1B rule).

    `branches` are the branches checked out in the nested repos (the hook collects
    them; the session directory's own branch, if any, was tried first and named no
    stream). Other sessions drive those checkouts too, so a stream binds only when the
    branches name exactly one live stream (``nested_live_matches``). Two or more live
    matches bind none, and dormant and finished streams never count.
    """
    matches = nested_live_matches(branches, folded)
    return matches[0] if len(matches) == 1 else None


def nested_live_matches(branches: Sequence[str],
                        folded: Sequence[Dict[str, Any]]) -> List[str]:
    """The live streams the nested repos' branches name, newest first (the 1B rule).

    Dormant and terminal streams are left out before any matching. Each branch then
    names the stream ``branch_match`` picks for it from the live streams of ``folded``
    only, so a dormant exact name never hides a live candidate. Each stream appears
    once, ordered by its last event's ``ts``, newest first; a tie keeps the order of
    ``branches``. ``nested_branch_match`` binds a stream only when this list holds
    exactly one, and ``build_status`` prints the list as ``nested_matches``.
    """
    live = [
        f for f in folded
        if stream_lifecycle(bool(f.get("terminal")), f.get("age_days")) == "live"
    ]
    streams = [f["stream"] for f in live]
    last_at = {f["stream"]: (f.get("last_event") or {}).get("ts") or "" for f in live}
    matches: List[str] = []
    for branch in branches:
        matched = branch_match(branch, streams)
        if matched is not None and matched not in matches:
            matches.append(matched)
    # A stable sort, so a tie keeps the order of `branches`.
    matches.sort(key=lambda stream: last_at[stream], reverse=True)
    return matches


def session_stream(folded: Sequence[Tuple[Dict[str, Any], Sequence[Event]]],
                   session: str) -> Optional[str]:
    """The live stream ``session`` last wrote to itself, or None.

    A session can drive a stream no checkout names — an epic's planning stream has no
    branch, and a stream opens before `workspace` makes its branch — and several sessions
    can run at once on different streams. What each one last appended is its position.
    Hook-written events do not count: a hook files an artifact write under the checked-out
    branch's stream, which says where the file landed, not what the session is driving. A
    finished stream releases the session to the branch fallback.
    """
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for entry, events in folded:
        for event in reversed(events):
            if _actor_role(event) != "hook" and event_session(event) == session:
                if best is None or event.seq > best[0]:
                    best = (event.seq, entry)
                break
    if best is None or best[1]["terminal"]:
        return None
    return best[1]["stream"]


class PositionDisposition(TypedDict):
    """A review finding's current state and the event that decided it (ADR 0014).

    ``label`` is the newest name a ``review-disposition``'s ``labels`` gave the key, or
    None when none did (ADR 0014, amended 0.22.0). A later event that names no label for
    the key keeps the earlier one, and ``seq``/``at`` stay the state's event.
    """

    state: FindingState
    seq: int
    at: str
    label: Optional[str]


def _finding_key(key: str) -> str:
    """A finding key (``<path>:<line or ?>``) without a leading ``./``."""
    return re.sub(r"^(?:\./)+", "", key)


def _position_dispositions(
    events: Sequence[Event], verdicts: Sequence[Event]
) -> Dict[str, PositionDisposition]:
    """Each finding's current state: every ``review-disposition`` and every verdict's map
    (``verdicts``: the verdicts in the vocabulary), folded in seq order, the latest event
    winning per key (ADR 0014). A later round's verdict that names only its own findings
    leaves the earlier closures in place; a later ``fixing`` still reopens a key.

    Each entry's ``label`` is the newest non-empty name a ``review-disposition``'s
    ``labels`` gave its key, or None. A verdict carries no labels. A label for a key that
    has no state is not printed."""
    verdict_seqs = {verdict.seq for verdict in verdicts}
    folded: Dict[str, PositionDisposition] = {}
    labels: Dict[str, str] = {}
    for event in events:
        if event.type == "review-disposition":
            allowed: Sequence[str] = get_args(FindingState)
            labels.update(_disposition_labels(event.data.get("labels")))
        elif event.seq in verdict_seqs:
            allowed = get_args(Disposition)
        else:
            continue
        states = _vocabulary_map(event.data.get("dispositions"), allowed)
        for key, state in states.items():
            folded[_finding_key(key)] = {
                "state": state, "seq": event.seq, "at": event.ts, "label": None,
            }
    for key, entry in folded.items():
        entry["label"] = labels.get(key)
    return folded


def _disposition_labels(value: Any) -> Dict[str, str]:
    """A ``labels`` map with each key as ``_finding_key`` leaves it; {} for a non-object.

    An imported row was never checked, so a value that is not a non-empty string is
    dropped here, as ``_vocabulary_map`` drops a state outside the vocabulary.
    """
    if not isinstance(value, dict):
        return {}
    return {
        _finding_key(key): item for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item.strip()
    }


def _newest_string(events: Sequence[Event], key: str) -> Optional[str]:
    """The newest non-empty string ``data[key]`` among ``events``, of any type by design:
    a ``deviation`` can move ``report_to`` as well as ``flow-started`` can set it."""
    for event in reversed(events):
        value = event.data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
