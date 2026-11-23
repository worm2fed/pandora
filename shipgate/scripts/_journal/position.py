"""Every fact the HUD draws for one stream (ADR 0009)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, TypedDict, get_args

from .vocab import (
    CriterionStatus, Disposition, EVENT_SHAPES, GateMode, InfraError, Phase, RaisedBy,
    ReviewVerdict, SIGNALS_MISSING_KIND, VerifyOutcome,
)
from .text import _one_line, _short_ts, _string_list, _string_or_none, _vocabulary_map
from .store import Event, read_events
from .approval import PublishAuthorization
from .fold import (
    _finding_key, _position_dispositions, CurrentPhase, fold_stream, Lifecycle, phase_marks,
    PhaseMark, PositionDisposition,
)
from .artifacts import (
    _committed_refs, _event_bound_worklog, _free_slug_named_worklog, _safe_ref,
    classify_artifact, parse_build_plan, PlanTask,
)


# --------------------------------------------------------------------------
# position — every fact the HUD draws for one stream (ADR 0009)
# --------------------------------------------------------------------------

WorklogFrom = Literal["event", "name"]


class PositionArtifacts(TypedDict):
    """The artifacts a stream works on, classified with the configured homes.

    ``worklog_from`` says how ``worklog`` was found: ``event`` (a ref in the stream's
    events) or ``name`` (the slug-named fallback); None when there is no worklog.

    An unsafe ref is dropped, never printed: an absolute path (``/`` or ``\\`` first),
    a path with a ``..`` segment, or one that starts with a drive (``C:``) or a scheme
    (``x://``). The rule applies to every ref, ``prd`` included.
    """

    worklog: Optional[str]
    worklog_from: Optional[WorklogFrom]
    prd: Optional[str]
    adrs: List[str]


class PositionTaskVerify(TypedDict):
    """The last ``verify-run`` in the stream that named a task, pass or fail."""

    outcome: VerifyOutcome
    at: str


class PositionLastVerify(TypedDict):
    """The stream's last ``verify-run``: the fold's ``last_verify``, ``ts`` as ``at``.

    A run whose ``outcome`` is outside ``VerifyOutcome`` is dropped, so this is the last
    run that passed or failed. ``task_ids`` keeps the run's string entries.
    """

    outcome: VerifyOutcome
    task_ids: List[str]
    at: str


class PositionTask(TypedDict):
    """A Build Plan task (``PlanTask``) with its journal state."""

    id: str
    title: Optional[str]
    section: Optional[str]
    ticked: bool
    done: bool
    last_verify: Optional[PositionTaskVerify]


class PositionDecision(TypedDict):
    """One ``gate-decision`` with its real ``seq`` (the HUD numbered them by index).

    ``gate``, ``question`` and ``decision`` are None when a row from before the
    canonical shape lacks the key or holds a non-string. ``raised_by`` falls back to the
    shape's default; ``mode`` is None when absent or outside ``GateMode``.
    """

    seq: int
    gate: Optional[str]
    question: Optional[str]
    decision: Optional[str]
    raised_by: RaisedBy
    mode: Optional[GateMode]
    at: str


class PositionVerdict(TypedDict):
    """The stream's last ``review-verdict``: when, which, its two maps, its note and
    its round.

    ``note`` is the verdict's ``data.note`` when it is a string, else None. ``round``
    counts the verdicts in the vocabulary up to and including this one, from 1
    (ADR 0014).
    """

    seq: int
    at: str
    verdict: ReviewVerdict
    criteria: Dict[str, CriterionStatus]
    dispositions: Dict[str, Disposition]
    note: Optional[str]
    round: int


class PositionRanking(TypedDict):
    """A recorded risk ranking (ADR 0013) and the event that carried it.

    ``ranking`` is the event's ``data.ranking`` verbatim: ``RankingPayload`` when
    ``append`` checked it, and not validated again here.
    """

    seq: int
    at: str
    ranking: Any


class PositionDeviation(TypedDict):
    """A ``deviation`` the trace names: where it sits in the stream, and when."""

    seq: int
    at: str


class PositionTrace(TypedDict):
    """What the signals left in the stream (ADR 0014; the HUD read it from ``log``).

    ``review_ranking`` and ``design_ranking`` are the newest ``review-verdict`` and
    ``design-committed`` whose payload carries ``ranking``, or None: a later event
    without one does not hide an earlier one's. ``signals_missing`` is every
    ``deviation`` of kind ``signals-missing`` (ADR 0011), oldest first.
    """

    review_ranking: Optional[PositionRanking]
    design_ranking: Optional[PositionRanking]
    signals_missing: List[PositionDeviation]


class PositionDoc(TypedDict):
    """``position --stream <s> --json``: every fact the HUD draws for one stream."""

    stream: str
    version: int
    lifecycle: Lifecycle
    current: Optional[CurrentPhase]
    publish: PublishAuthorization
    go: "GoAnswer"
    phases: Dict[Phase, PhaseMark]
    artifacts: PositionArtifacts
    tasks: Optional[List[PositionTask]]
    last_verify: Optional[PositionLastVerify]
    decisions: List[PositionDecision]
    verdict: Optional[PositionVerdict]
    trace: PositionTrace
    dispositions: Dict[str, PositionDisposition]


def build_position(
    conn: sqlite3.Connection,
    stream: str,
    project_dir: Path,
    homes: Dict[str, str],
    now: Optional[datetime] = None,
) -> PositionDoc:
    """Every fact the HUD draws for ``stream``, from its events and its artifacts.

    ``stream`` is an exact stream name. A stream with no events raises ``InfraError``,
    so ``position`` exits 1: exit 2 stays reserved for argparse's usage errors, which
    the HUD reads as an unknown flag.
    - ``version``, ``lifecycle``, ``current``, ``publish`` and ``go`` are
      ``fold_stream``'s for the stream, with ``now`` as there. ``phases`` is
      ``phase_marks``.
    - ``artifacts``: the refs are ``data.worklog``, ``data.refs`` and ``data.adrs`` of
      the ``POSITION_ARTIFACT_EVENTS`` events, a ``#fragment`` dropped, unsafe refs
      dropped (see ``PositionArtifacts``), classified by ``classify_artifact`` with
      ``homes``. The last worklog ref is ``worklog`` (``worklog_from: event``); the ADR
      refs are ``adrs``, each once, first seen first. With no worklog ref, ``worklog`` is
      the newest file (by mtime) in the worklog home named for the stream's last path
      segment ``<slug>`` (``<slug>.worklog.md``, or a name that starts with ``<slug>-``
      or ``<slug>.``) that no other live stream's events name (``worklog_from: name``).
      When there is none and the slug starts with an issue id (``1290-demo``), the slug
      without it (``demo``) gets the same lookup (#43).
      ``prd`` is the ``data.prd`` of the last ``clarify-passed``.
    - ``tasks``: ``parse_build_plan`` over the worklog, each task id once (its first
      line wins), each with ``done`` (a ``task-done`` in this stream names it) and
      ``last_verify`` (the last ``verify-run`` here naming it). None when there is no
      worklog or it cannot be read; [] when its Build Plan has no task line.
    - ``last_verify``: the stream's last ``verify-run`` (``PositionLastVerify``), or
      None.
    - ``decisions``: every ``gate-decision``, oldest first; a field that is not a string
      prints null.
    - ``verdict``: the last ``review-verdict``, or None. A disposition key loses a
      leading ``./``. ``note`` is its text or None; ``round`` is how many verdicts the
      stream holds up to and including it.
    - ``trace``: the newest ``review-verdict`` and ``design-committed`` that carry
      ``ranking`` (``PositionRanking``, the ranking verbatim), or None each, and every
      ``signals-missing`` deviation, oldest first (``PositionTrace``).
    - ``dispositions``: per finding key, its current state (``PositionDisposition``).
      The fold reads every ``review-disposition`` and every verdict's
      ``dispositions`` in seq order, and the latest event wins per key. A key loses a
      leading ``./``.
    A value outside its vocabulary is dropped wherever it appears: a verdict map entry,
    a ``review-disposition`` state outside ``FindingState``, or a ``verify-run`` whose
    outcome is not ``pass`` or ``fail``. Every addition since 0.20.0 is a new key; no
    earlier key was renamed or removed. Paths are printed as the events wrote them,
    relative to ``project_dir``.
    """
    events = read_events(conn, stream=stream)
    if not events:
        raise InfraError(
            f"stream {stream!r} has no events — `journal.py streams` lists the streams"
        )
    folded = fold_stream(events, now=now)

    worklog = _event_bound_worklog(events, homes)
    adrs: List[str] = []
    for ref in _committed_refs(events):
        if classify_artifact(ref, homes) == "adr" and ref not in adrs:
            adrs.append(ref)
    worklog_from: Optional[WorklogFrom] = "event" if worklog is not None else None
    if worklog is None:
        worklog = _free_slug_named_worklog(conn, stream, project_dir, homes, now)
        worklog_from = "name" if worklog is not None else None
    clarified = [e for e in events if e.type == "clarify-passed"]
    prd = _safe_ref(clarified[-1].data.get("prd")) if clarified else None

    tasks: Optional[List[PositionTask]] = None
    if worklog is not None:
        try:
            text = (project_dir / worklog).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            text = None
        if text is not None:
            tasks = _position_tasks(parse_build_plan(text), events)

    runs = _verify_runs(events)
    last_verify: Optional[PositionLastVerify] = None
    if runs:
        last_verify = {
            "outcome": runs[-1].data["outcome"],
            "task_ids": _string_list(runs[-1].data.get("task_ids")),
            "at": runs[-1].ts,
        }
    # A verdict outside the vocabulary (an old row) is dropped like any other value, so
    # this is the last verdict that said ready or not-ready.
    verdicts = [
        e for e in events
        if e.type == "review-verdict"
        and e.data.get("verdict") in get_args(ReviewVerdict)
    ]
    return {
        "stream": stream,
        "version": folded["version"],
        "lifecycle": folded["lifecycle"],
        "current": folded["current"],
        "publish": folded["publish"],
        "go": folded["go"],
        "phases": phase_marks(events),
        "artifacts": {
            "worklog": worklog, "worklog_from": worklog_from, "prd": prd, "adrs": adrs,
        },
        "tasks": tasks,
        "last_verify": last_verify,
        "decisions": [
            _position_decision(e) for e in events if e.type == "gate-decision"
        ],
        "verdict": (
            _position_verdict(verdicts[-1], len(verdicts)) if verdicts else None
        ),
        "trace": _position_trace(events),
        "dispositions": _position_dispositions(events, verdicts),
    }


def _verify_runs(events: Sequence[Event]) -> List[Event]:
    """The ``verify-run`` events whose outcome is in the vocabulary, in order."""
    return [
        e for e in events
        if e.type == "verify-run" and e.data.get("outcome") in get_args(VerifyOutcome)
    ]


def _position_tasks(
    plan: Sequence[PlanTask], events: Sequence[Event]
) -> List[PositionTask]:
    done = {
        e.data.get("task_id") for e in events
        if e.type == "task-done" and isinstance(e.data.get("task_id"), str)
    }
    verified: Dict[str, PositionTaskVerify] = {}
    for run in _verify_runs(events):
        for task_id in _string_list(run.data.get("task_ids")):
            verified[task_id] = {"outcome": run.data["outcome"], "at": run.ts}
    tasks: List[PositionTask] = []
    seen: Set[str] = set()
    for task in plan:
        if task["id"] in seen:
            continue
        seen.add(task["id"])
        tasks.append({
            "id": task["id"],
            "title": task["title"],
            "section": task["section"],
            "ticked": task["ticked"],
            "done": task["id"] in done,
            "last_verify": verified.get(task["id"]),
        })
    return tasks


def _position_decision(event: Event) -> PositionDecision:
    data = event.data
    raised_by = data.get("raised_by")
    if raised_by not in get_args(RaisedBy):
        raised_by = EVENT_SHAPES["gate-decision"]["defaults"]["raised_by"]
    mode = data.get("mode")
    return {
        "seq": event.seq,
        "gate": _string_or_none(data.get("gate")),
        "question": _string_or_none(data.get("question")),
        "decision": _string_or_none(data.get("decision")),
        "raised_by": raised_by,
        "mode": mode if mode in get_args(GateMode) else None,
        "at": event.ts,
    }


def _position_verdict(event: Event, round_number: int) -> PositionVerdict:
    criteria = _vocabulary_map(event.data.get("criteria"), get_args(CriterionStatus))
    dispositions = _vocabulary_map(event.data.get("dispositions"), get_args(Disposition))
    return {
        "seq": event.seq,
        "at": event.ts,
        "verdict": event.data["verdict"],
        "criteria": criteria,
        "dispositions": {
            _finding_key(key): item for key, item in dispositions.items()
        },
        "note": _string_or_none(event.data.get("note")),
        "round": round_number,
    }


def _last_ranking(events: Sequence[Event], event_type: str) -> Optional[PositionRanking]:
    """The newest ``event_type`` whose payload carries ``ranking``, or None."""
    carriers = [e for e in events if e.type == event_type and "ranking" in e.data]
    if not carriers:
        return None
    last = carriers[-1]
    return {"seq": last.seq, "at": last.ts, "ranking": last.data["ranking"]}


def _position_trace(events: Sequence[Event]) -> PositionTrace:
    return {
        "review_ranking": _last_ranking(events, "review-verdict"),
        "design_ranking": _last_ranking(events, "design-committed"),
        "signals_missing": [
            {"seq": e.seq, "at": e.ts} for e in events
            if e.type == "deviation" and e.data.get("kind") == SIGNALS_MISSING_KIND
        ],
    }


def _render_position(position: PositionDoc) -> str:
    """The position for people; ``--json`` is the contract."""
    current = position["current"]
    publish = position["publish"]
    artifacts = position["artifacts"]
    tasks = position["tasks"]
    verify = position["last_verify"]
    verdict = position["verdict"]
    trace = position["trace"]
    dispositions = position["dispositions"]
    open_findings = sum(1 for d in dispositions.values() if d["state"] == "fixing")
    phase = "—"
    if current is not None:
        phase = current["phase"] + ("  (implied)" if current["implied"] else "")
    lines = [
        f"{_one_line(position['stream'])}  (v{position['version']})  "
        f"{position['lifecycle']}",
        f"  phase        : {phase}",
        "  phases       : " + " ".join(
            f"{name}={mark}" for name, mark in position["phases"].items()
        ),
        "  publish      : " + (
            f"authorized by {publish['by']} (seq {publish['seq']})"
            if publish["kind"] == "authorized" else "held"
        ),
        "  worklog      : " + (
            f"{_one_line(artifacts['worklog'])} (from {artifacts['worklog_from']})"
            if artifacts["worklog"] else "—"
        ),
        "  prd          : " + (
            _one_line(artifacts["prd"]) if artifacts["prd"] else "—"
        ),
        "  adrs         : " + (
            ", ".join(_one_line(a) for a in artifacts["adrs"]) or "—"
        ),
        "  tasks        : " + (
            "—" if tasks is None
            else f"{sum(1 for t in tasks if t['done'])}/{len(tasks)} done"
        ),
        "  last verify  : " + (
            f"{verify['outcome']} ({_short_ts(verify['at'])})" if verify else "—"
        ),
        f"  decisions    : {len(position['decisions'])}",
        "  verdict      : " + (
            f"{verdict['verdict']} (seq {verdict['seq']}, round {verdict['round']})"
            if verdict else "—"
        ),
        f"  dispositions : {len(dispositions)} ({open_findings} open)",
        "  trace        : " + ", ".join([
            "review ranking " + (
                f"seq {trace['review_ranking']['seq']}"
                if trace["review_ranking"] else "—"
            ),
            "design ranking " + (
                f"seq {trace['design_ranking']['seq']}"
                if trace["design_ranking"] else "—"
            ),
            f"signals-missing {len(trace['signals_missing'])}",
        ]),
    ]
    return "\n".join(lines)
