"""The status brief: bound streams and the count line (ADR 0024)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, TypedDict

from .vocab import (
    BRIEF_DECISION_LIMIT, BRIEF_DECISION_LIMIT_OTHER, BRIEF_TASK_IDS, FEATURE_STREAM_PREFIX,
    OWNERSHIP_MINUTES,
)
from .plugin import closeout_command
from .text import _clip, _one_line, _short_ts
from .settings import settings_lines
from .store import list_streams, read_events
from .fold import (
    branch_match, fold_stream, is_work_stream, nested_branch_match, nested_live_matches,
    other_session, session_stream, stream_lifecycle,
)


def _brief_rank(feature: Dict[str, Any]) -> int:
    if feature.get("session_match"):
        return 0
    if feature.get("branch_match"):
        return 1
    if feature.get("terminal"):
        return 4
    return 3 if feature.get("dormant") else 2


class StatusBriefAdditions(TypedDict):
    """The key the top level of ``status --json`` gains (T012).

    ``nested_matches`` is ``nested_live_matches`` over the nested branches. The key is
    always printed: ``[]`` when no nested branch was passed or none named a live stream.
    """

    nested_matches: List[str]


def build_status(
    conn: sqlite3.Connection,
    feature: Optional[str] = None,
    branch: Optional[str] = None,
    show_all: bool = False,
    now: Optional[datetime] = None,
    nested_branches: Optional[Sequence[str]] = None,
    session: Optional[str] = None,
) -> Dict[str, Any]:
    if feature:
        # Accept a bare slug, a `feature/` stream, or any other work stream name
        # (a branch-shaped one such as `fix/1290-…`) — match whichever exists.
        existing = list_streams(conn)
        candidates = [feature, FEATURE_STREAM_PREFIX + feature]
        wanted = [s for s in candidates if s in existing]
        if not wanted:
            wanted = [s for s in existing if is_work_stream(s) and feature in s]
        if not wanted:
            wanted = [candidates[0]]
    else:
        wanted = [s for s in list_streams(conn) if is_work_stream(s)]

    folded = []
    with_events = []
    for stream in wanted:
        events = read_events(conn, stream=stream)
        if not events:
            continue
        entry = fold_stream(events, now=now)
        folded.append(entry)
        with_events.append((entry, events))

    matched = branch_match(branch, [f["stream"] for f in folded]) if branch else None
    nested_matches = (
        nested_live_matches(nested_branches, folded) if nested_branches else []
    )
    if matched is None and nested_branches:
        matched = nested_branch_match(nested_branches, folded)
    driven = session_stream(with_events, session) if session else None
    # Hiding finished work is what keeps the brief small, but someone who names a
    # stream is asking about that stream — answering "nothing here" would be a lie.
    keep_terminal = show_all or bool(feature)
    features = []
    hidden_terminal = 0
    for entry in folded:
        entry["branch_match"] = entry["stream"] == matched
        entry["session_match"] = entry["stream"] == driven
        entry["other_session"] = other_session(entry, session, now)
        if entry["terminal"] and not keep_terminal and not entry["branch_match"]:
            hidden_terminal += 1
            continue
        features.append(entry)

    # Two stable sorts: recency inside each rank, then the ranks themselves.
    features.sort(key=lambda f: (f["last_event"] or {}).get("ts") or "", reverse=True)
    features.sort(key=_brief_rank)
    return {
        "features": features,
        "hidden_terminal": hidden_terminal,
        "branch_match": matched,
        "session_match": driven,
        "nested_matches": nested_matches,
    }


def _render_decision(decision: Dict[str, Any]) -> str:
    """Render a gate decision from whatever keys it actually carries.

    Payload shapes drift — an event recorded before the canonical shape settled may
    carry `chosen` instead of `question`/`decision`. Printing "None -> None (None)"
    for those makes real history look like corruption, so show what is there and fall
    back to the raw payload rather than to placeholders.
    """
    gate = decision.get("gate")
    prefix = f"[{gate}] " if gate else ""
    question = decision.get("question")
    answer = decision.get("decision") or decision.get("chosen")
    mode = decision.get("mode")
    suffix = f" ({mode})" if mode else ""

    if question and answer:
        return f"{prefix}{question} -> {answer}{suffix}"
    if answer:
        return f"{prefix}{answer}{suffix}"
    if question:
        return f"{prefix}{question} -> (undecided){suffix}"
    body = ", ".join(
        f"{k}={v}" for k, v in decision.items()
        if k not in {"gate", "mode", "ts"} and v is not None
    )
    return f"{prefix}{body or '(no detail recorded)'}{suffix}"


def _render_ledger(status: Dict[str, Any]) -> List[str]:
    """One line, and only when the ledger is actually holding something.

    An empty ledger is the healthy state, so saying so every session would be noise.
    """
    ledger = status.get("ledger")
    if not isinstance(ledger, dict) or not ledger.get("entries"):
        return []
    entries = ledger["entries"]
    line = (
        f"ledger       : {entries} untriaged "
        f"{'entry' if entries == 1 else 'entries'} in {_clip(ledger['path'])}"
    )
    if ledger.get("nudge"):
        line += "  — worth triaging (see knowledge-base)"
    return [line]


def _render_task_ids(feature: Dict[str, Any]) -> str:
    ids = feature["task_ids"]
    if not ids:
        return ""
    shown = ids[-BRIEF_TASK_IDS:]
    elided = "… " if len(ids) > len(shown) else ""
    return f"  [{elided}{', '.join(_one_line(i) for i in shown)}]"


def _render_dormant(feature: Dict[str, Any]) -> str:
    """One line for work nobody has touched in a week — name, position, age."""
    last = feature["last_event"] or {}
    return _one_line(
        f"{feature['stream']}  (v{feature['version']})  "
        f"phase {feature['phase'] or '—'} · "
        f"last {last.get('type', '—')} {str(last.get('ts', ''))[:10]}  "
        f"· dormant {feature['age_days']}d"
    )


def _render_feature(feature: Dict[str, Any]) -> List[str]:
    lines = [
        f"{_clip(feature['stream'])}  (v{feature['version']})"
        + ("  · this session" if feature.get("session_match") else "")
        + ("  · terminal" if feature.get("terminal") else "")
    ]
    other = feature.get("other_session")
    if other:
        lines.append(
            f"  ownership    : another session wrote this {other['minutes']}m ago"
        )
    lines.append(
        f"  phase        : {feature['phase'] or '—'}"
        + ("  (implied)" if feature.get("implied_phase") else "")
        + (f"  (entered {_short_ts(feature['phase_entered_at'])})"
           if feature["phase_entered_at"] else "")
    )
    last = feature["last_event"]
    lines.append(
        f"  last event   : {_one_line(last['type'])} at {_short_ts(last['ts'])}"
        if last else "  last event   : —"
    )
    lines.append(
        f"  tasks done   : {feature['tasks_done']}" + _render_task_ids(feature)
    )
    verify = feature["last_verify"]
    if verify:
        covered = verify.get("task_ids") or []
        lines.append(
            f"  last verify  : {_one_line(verify.get('outcome'))}"
            + (f" — {', '.join(_one_line(t) for t in covered)}" if covered else "")
            + f" ({_short_ts(verify.get('ts'))})"
        )
    else:
        lines.append("  last verify  : —")
    decisions = feature["gate_decisions"]
    if decisions:
        limit = (
            BRIEF_DECISION_LIMIT
            if feature.get("branch_match") or feature.get("session_match")
            else BRIEF_DECISION_LIMIT_OTHER
        )
        shown = decisions[-limit:]
        lines.append("  gate decisions:")
        for decision in shown:
            lines.append(_clip("    - " + _render_decision(decision)))
        earlier = feature.get("gate_decision_count", len(decisions)) - len(shown)
        if earlier > 0:
            lines.append(f"    … +{earlier} earlier")
    if feature["open_designs"]:
        lines.append("  open designs:")
        for design in feature["open_designs"]:
            assumes = design.get("assumes")
            lines.append(_clip(
                f"    - {_one_line(design.get('issue'))}"
                + (f" (assumes {_one_line(assumes)})" if assumes else "")
            ))
    if feature.get("pull_request") and not feature.get("terminal"):
        lines.append(
            "  close-out    : after the merge, run " + closeout_command(feature["stream"])
        )
    lines.append("")
    return lines


def _render_hidden(status: Dict[str, Any]) -> List[str]:
    hidden = status.get("hidden_terminal") or 0
    if not hidden:
        return []
    return [f"{hidden} completed stream(s) hidden (--all shows them)"]


def _is_bound(feature: Dict[str, Any]) -> bool:
    """This session drives the stream, or the checkout names it (ADR 0024)."""
    return bool(feature.get("session_match") or feature.get("branch_match"))


def brief_counts(status: Dict[str, Any]) -> Dict[str, int]:
    """The streams the brief does not print, by lifecycle, and how many of the open ones
    another session wrote lately (FR-003, FR-007)."""
    counts = {"live": 0, "dormant": 0,
              "finished": status.get("hidden_terminal") or 0, "other_session": 0}
    for feature in status["features"]:
        if _is_bound(feature):
            continue
        lifecycle = stream_lifecycle(bool(feature.get("terminal")),
                                     feature.get("age_days"))
        counts["finished" if lifecycle == "terminal" else lifecycle] += 1
        if lifecycle != "terminal" and feature.get("other_session"):
            counts["other_session"] += 1
    return counts


def _render_count_line(counts: Dict[str, int]) -> List[str]:
    """One line for every stream the brief leaves out; a zero count is left out, and
    with nothing to count there is no line (FR-003)."""
    parts = []
    if counts["live"]:
        parts.append(f"{counts['live']} live")
    if counts["other_session"]:
        parts.append(
            f"({counts['other_session']} written by another session in the last "
            f"{OWNERSHIP_MINUTES} min)"
        )
    if counts["dormant"]:
        parts.append(f"{counts['dormant']} dormant")
    if counts["finished"]:
        parts.append(f"{counts['finished']} finished")
    if not parts:
        return []
    shown = ", ".join(parts).replace(" live, (", " live (")
    if counts["live"] or counts["dormant"]:
        commands = "list: journal.py streams --open"
        if counts["dormant"]:
            commands += " · close dormant: journal.py sweep"
    else:
        commands = "journal.py status --all shows them"
    return [f"not shown: {shown} — {commands}"]


def _with_settings(text: str, status: Dict[str, Any]) -> str:
    """TEXT, then the settings lines (ADR 0028) right after its last line: the text
    before them stays what it was without them."""
    settings = settings_lines(status)
    if not settings:
        return text
    return "\n".join(([text] if text else []) + settings)


def render_status(status: Dict[str, Any], full: bool = False) -> str:
    """The status text. ``full`` is the render of ``--all`` and ``--feature``: every
    selected stream, dormant ones as one line. Without it, the brief (ADR 0024): the
    bound streams in full, then one count line for the rest."""
    features = status["features"]
    if not full and (features or status.get("hidden_terminal")):
        lines = []
        for feature in features:
            if _is_bound(feature):
                lines.extend(_render_feature(feature))
        lines.extend(_render_count_line(brief_counts(status)))
        lines.extend(_render_ledger(status))
        return _with_settings("\n".join(lines).rstrip(), status)
    if not features:
        return "\n".join([
            "No work streams recorded.",
            *_render_hidden(status),
            *_render_ledger(status),
            *settings_lines(status),
        ])
    lines: List[str] = []
    for feature in features:
        if feature.get("dormant") and not (
            feature.get("branch_match") or feature.get("session_match")
        ):
            lines.append(_render_dormant(feature))
        else:
            lines.extend(_render_feature(feature))
    lines.extend(_render_hidden(status))
    lines.extend(_render_ledger(status))
    return _with_settings("\n".join(lines).rstrip(), status)
