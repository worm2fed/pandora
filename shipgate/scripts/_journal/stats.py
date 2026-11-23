"""Counts over the journal."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, get_args

from .vocab import DecisionSource, UsageError
from .store import _parse_ts, Event, read_events
from .sessions import _actor_role, event_session
from .approval import _go_gate
from .fold import fold_stream, is_work_stream
from .artifacts import artifact_authors
from .status import build_status, render_status


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------


def _merge_counts(dicts: Iterable[Dict[str, int]]) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for source in dicts:
        for key, value in source.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _counted_sessions(events: Iterable[Event]) -> Set[str]:
    """The sessions that touched these events.

    The label of an event actored `user@…` or `watcher@…` is not counted: it names a
    person or a watcher, not a session (ADR 0003 only defaults the label to
    the appending session for machine roles), so counting it would inflate "sessions" by
    one per human who ever appeared. `event_session` already skips those labels, and it
    counts the session that recorded a `user` row (`recorded_by`, ADR 0010).
    An artifact write counts only its author from the fold (ADR 0008): a session that
    merely saw the file change did not touch the stream.
    """
    events = list(events)
    counted = {
        author for author in artifact_authors(events).values() if author is not None
    }
    counted.update(
        session
        for session in (
            event_session(event)
            for event in events
            if event.type != "artifact-written"
        )
        if session
    )
    return counted


# The trace of #10 and #11: did the flow name the style skills, and which signals fed
# each phase? A state is null when the stream never reached the phase.
TRACE_STYLE_PHASES = ("implement", "review")
TRACE_GRAPH_PHASES = ("route", "design", "review")


def _style_state(events: Sequence[Event], phase: str) -> Optional[str]:
    """`named`, `none` (an empty list: the config names no style skill), `missing`
    (the phase was entered and no event said), or null (never entered)."""
    reached = False
    styles: List[Any] = []
    for event in events:
        own = (
            event.type == "phase-entered" and event.data.get("phase") == phase
        ) or (phase == "review" and event.type == "review-verdict")
        if not own:
            continue
        reached = True
        if "style" in event.data:
            styles.append(event.data["style"])
    if any(isinstance(style, list) and any(isinstance(i, str) and i for i in style)
           for style in styles):
        return "named"
    if any(style == [] for style in styles):
        return "none"
    return "missing" if reached else None


def _source_of(block: Any) -> str:
    if isinstance(block, dict) and isinstance(block.get("source"), str):
        return block["source"]
    return "missing"


def _graph_state(events: Sequence[Event], phase: str) -> Optional[str]:
    """The source the phase's last event WITH the block recorded: `graph`, `regex`,
    `none`; `missing` when none of its events carries one; null when it has no event.

    The last carrier, not the last event: a fix-round verdict that does not rerun the
    signals must not hide that the graph fed the first round. Style reads the same way:
    any phase event that named a skill counts."""
    if phase == "route":
        own = [
            e for e in events
            if e.type == "phase-entered" and e.data.get("phase") == "route-and-map"
        ]
        key = "signals"
    else:
        wanted = "design-committed" if phase == "design" else "review-verdict"
        own = [e for e in events if e.type == wanted]
        key = "ranking"
    if not own:
        return None
    carriers = [e for e in own if key in e.data]
    return _source_of(carriers[-1].data.get(key)) if carriers else "missing"


def _trace(events: Sequence[Event]) -> Dict[str, Dict[str, Optional[str]]]:
    return {
        "style": {phase: _style_state(events, phase) for phase in TRACE_STYLE_PHASES},
        "graph": {phase: _graph_state(events, phase) for phase in TRACE_GRAPH_PHASES},
    }


def _trace_totals(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Per phase, how many streams ended in each state; streams that never reached
    the phase are not counted."""
    totals: Dict[str, Dict[str, Dict[str, int]]] = {}
    for group, phases in (("style", TRACE_STYLE_PHASES), ("graph", TRACE_GRAPH_PHASES)):
        totals[group] = {}
        for phase in phases:
            counts: Dict[str, int] = {}
            for row in rows:
                state = row["trace"][group][phase]
                if state is not None:
                    counts[state] = counts.get(state, 0) + 1
            totals[group][phase] = counts
    return totals


def _stream_stats(
    stream: str, events: Sequence[Event], now: Optional[datetime] = None
) -> Dict[str, Any]:
    by_role: Dict[str, int] = {}
    decisions: Dict[str, int] = {}
    verified: Dict[str, int] = {}
    task_ids: Set[str] = set()
    tallies = {
        "deviation": 0, "verify-run": 0, "task-done": 0,
        "review-verdict": 0, "review-feedback": 0,
    }
    implied = 0
    deviation_kinds: Dict[str, int] = {}
    # The go records by marker (ADR 0023 §19).
    go: Dict[str, int] = dict.fromkeys(get_args(DecisionSource), 0)

    for event in events:
        role = _actor_role(event)
        by_role[role] = by_role.get(role, 0) + 1
        if event.type in tallies:
            tallies[event.type] += 1
        if event.type == "deviation":
            kind = event.data.get("kind")
            kind = kind if isinstance(kind, str) and kind else "-"
            deviation_kinds[kind] = deviation_kinds.get(kind, 0) + 1
        if event.type == "gate-decision" and _go_gate(event.data) is not None:
            go[event.data["source"]] += 1
        if event.type == "gate-decision":
            key = "{}/{}".format(
                event.data.get("mode") or "-", event.data.get("raised_by") or "-"
            )
            decisions[key] = decisions.get(key, 0) + 1
        elif event.type == "verify-run":
            # Per verify-run, not per mention: one run naming a task twice verified
            # it once.
            for task in set(str(t) for t in event.data.get("task_ids") or []):
                verified[task] = verified.get(task, 0) + 1
        elif event.type == "task-done":
            task_id = event.data.get("task_id")
            if isinstance(task_id, str) and task_id:
                task_ids.add(task_id)
        elif event.type == "phase-entered" and event.data.get("implied"):
            implied += 1

    rendered = render_status({"features": [fold_stream(events, now=now)]}, full=True)
    return {
        "stream": stream,
        "events": len(events),
        "by_role": by_role,
        "decisions": decisions,
        "deviations": tallies["deviation"],
        "verify_runs": tallies["verify-run"],
        # Distinct ids, as the brief counts them — a task re-recorded after review
        # feedback is one task done, not two.
        "tasks_done": len(task_ids),
        "tasks_reverified": sum(1 for runs in verified.values() if runs > 1),
        "review_rounds": tallies["review-verdict"],
        "review_feedback": tallies["review-feedback"],
        "sessions": len(_counted_sessions(events)),
        "implied_phases": implied,
        "stream_render_bytes": len(rendered.encode()),
        "deviation_kinds": deviation_kinds,
        "go": go,
        "trace": _trace(events),
    }


STATS_SUMS = (
    "events", "deviations", "verify_runs", "tasks_done", "tasks_reverified",
    "review_rounds", "review_feedback", "implied_phases",
)


def build_stats(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
    stream: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Per-stream counts for the numbers the process is tuned on (FR-014)."""
    cutoff = None
    if since:
        cutoff = _parse_ts(since)
        if cutoff is None:
            raise UsageError(
                f"--since {since!r} is not an ISO timestamp "
                "(2026-09-01, or 2026-09-01T12:00:00+00:00)"
            )

    grouped: Dict[str, List[Event]] = {}
    for event in read_events(conn, stream=stream):
        # An explicitly named stream is reported even when it is the tool's own.
        if stream is None and not is_work_stream(event.stream):
            continue
        if cutoff is not None:
            recorded = _parse_ts(event.ts)
            if recorded is None or recorded < cutoff:
                continue
        grouped.setdefault(event.stream, []).append(event)

    rows = [
        _stream_stats(name, events, now=now)
        for name, events in sorted(grouped.items())
    ]
    totals: Dict[str, Any] = {key: sum(row[key] for row in rows) for key in STATS_SUMS}
    totals["by_role"] = _merge_counts(row["by_role"] for row in rows)
    totals["decisions"] = _merge_counts(row["decisions"] for row in rows)
    totals["deviation_kinds"] = _merge_counts(row["deviation_kinds"] for row in rows)
    totals["go"] = {
        **dict.fromkeys(get_args(DecisionSource), 0),
        **_merge_counts(row["go"] for row in rows),
    }
    totals["trace"] = _trace_totals(rows)
    totals["sessions"] = len(
        _counted_sessions(e for events in grouped.values() for e in events)
    )
    # The brief is not the sum of its streams: it prints the bound streams in full and
    # counts the rest in one line (ADR 0024), so the only honest total is the brief
    # itself. With no stream named, it measures the brief of a session that drives
    # nothing on the integration branch: the count line alone. `--since` narrows the
    # counts, never this.
    totals["brief_bytes"] = len(
        render_status(build_status(conn, feature=stream, now=now),
                      full=bool(stream)).encode()
    )
    return {"since": since, "streams": rows, "totals": totals}


STATS_COLUMNS = (
    ("dec", lambda r: sum(r["decisions"].values())),
    ("dev", lambda r: r["deviations"]),
    ("vfy", lambda r: r["verify_runs"]),
    ("task", lambda r: r["tasks_done"]),
    ("rvfy", lambda r: r["tasks_reverified"]),
    ("rnd", lambda r: r["review_rounds"]),
    ("fb", lambda r: r["review_feedback"]),
    ("sess", lambda r: r["sessions"]),
    ("impl", lambda r: r["implied_phases"]),
    # Per stream this is that stream's own rendered block; on the TOTAL row it is the
    # whole brief, which is smaller than their sum.
    ("bytes", lambda r: r.get("stream_render_bytes", r.get("brief_bytes", 0))),
)


def render_stats(report: Dict[str, Any]) -> str:
    rows = report["streams"]
    since = report.get("since")
    scope = f" since {since}" if since else ""
    if not rows:
        return f"no work streams recorded{scope}"

    roles = sorted({role for row in rows for role in row["by_role"]})
    header = ["stream", "ev"] + [role[:4] for role in roles] + [
        name for name, _ in STATS_COLUMNS
    ]

    def cells(row: Dict[str, Any], label: str) -> List[str]:
        return (
            [label, str(row["events"])]
            + [str(row["by_role"].get(role, 0)) for role in roles]
            + [str(read(row)) for _, read in STATS_COLUMNS]
        )

    table = [header] + [cells(row, row["stream"]) for row in rows]
    table.append(cells(report["totals"], "TOTAL"))
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    lines = [
        "  ".join(
            cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i])
            for i, cell in enumerate(row)
        ).rstrip()
        for row in table
    ]

    lines.append("")
    lines.append("gate decisions (mode/raised_by):")
    decisions = report["totals"]["decisions"]
    if decisions:
        width = max(len(key) for key in decisions)
        for key in sorted(decisions):
            lines.append(f"  {key.ljust(width)}  {decisions[key]}")
    else:
        lines.append("  none recorded")
    lines.append("")
    lines.extend(_render_trace(report))
    return "\n".join(lines)


def _render_trace(report: Dict[str, Any]) -> List[str]:
    """The #10/#11 section: per stream, then how often across them."""
    rows = report["streams"]
    width = max(len(row["stream"]) for row in rows)

    def cell(state: Optional[str]) -> str:
        return state if state is not None else "-"

    lines = ["style and code graph per stream:"]
    for row in rows:
        style, graph = row["trace"]["style"], row["trace"]["graph"]
        lines.append(
            f"  {row['stream'].ljust(width)}  "
            f"style impl {cell(style['implement'])}, review {cell(style['review'])}  "
            f"· graph route {cell(graph['route'])}, design {cell(graph['design'])}, "
            f"review {cell(graph['review'])}"
        )

    totals = report["totals"]["trace"]

    def share(counts: Dict[str, int], hit: str) -> str:
        return f"{counts.get(hit, 0)} of {sum(counts.values())}"

    graph, style = totals["graph"], totals["style"]
    lines.extend([
        f"  graph at route-and-map: {share(graph['route'], 'graph')} mapped streams",
        f"  graph fed design: {share(graph['design'], 'graph')} designed streams",
        f"  graph fed review: {share(graph['review'], 'graph')} reviewed streams",
        f"  style named at implement: {share(style['implement'], 'named')}",
        f"  style named at review: {share(style['review'], 'named')}",
    ])
    kinds = report["totals"]["deviation_kinds"]
    named = [f"{kind} {kinds[kind]}" for kind in sorted(kinds) if kind != "-"]
    if "-" in kinds:
        named.append(f"no kind {kinds['-']}")
    lines.append("deviations by kind: " + (", ".join(named) or "none recorded"))
    return lines
