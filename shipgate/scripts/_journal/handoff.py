"""The handoff brief (ADR 0021) and the context nudge."""

from __future__ import annotations

import os
import re
import shlex
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TypedDict

from .vocab import BRIEF_DECISION_LIMIT, PHASE_ORDER
from .plugin import _config, closeout_command
from .text import _clip, _one_line, _short_ts, _string_list, _string_or_none
from .project import (
    _config_files, _config_label, project_settings, require_setting, setting_source,
)
from .store import Event, read_events
from .fold import _newest_string, pull_request
from .artifacts import _safe_ref
from .status import _render_decision
from .position import build_position, PositionDoc, PositionTask


# --------------------------------------------------------------------------
# handoff — the brief a fresh session continues from (ADR 0021)
# --------------------------------------------------------------------------

# The config sections whose rules still bind the next session, in print order.
HANDOFF_SECTIONS = ("Autonomy", "Security-sensitive areas")
HANDOFF_SECTION_LINES = 10
HANDOFF_FINDINGS_SHOWN = 5
# An ADR's status: a `status:` line (front matter or body, any case), or a `Status`
# heading followed by its value on the next non-blank line (the Nygard and MADR forms).
_ADR_STATUS_RE = re.compile(
    # Blank space is `[ \t]`, never `\s`, and every line break is explicit: a `\s` that
    # can cross a line lets the blank-line run split many ways, and a miss then takes
    # exponential time.
    r"^[ \t]*(?:[-*+][ \t]+)?\**status\**[ \t]*:[ \t]*(?:\*+[ \t]*)?['\"]?([A-Za-z][A-Za-z-]*)"
    r"|^#{1,6}[ \t]*status[ \t]*:[ \t]*\**['\"]?([A-Za-z][A-Za-z-]*)"
    r"|^#{1,6}[ \t]*status[ \t]*(?:#+[ \t]*)?\r?\n(?:[ \t]*\r?\n)*[ \t]*(?:[-*+][ \t]+)?\**"
    r"['\"]?([A-Za-z][A-Za-z-]*)",
    re.IGNORECASE | re.MULTILINE,
)
ADR_STATUS_BYTES = 4096
ADR_CLOSED = ("accepted", "superseded", "rejected", "deprecated")


class HandoffRule(TypedDict):
    """One config section as the brief quotes it: its lines, the file that supplied
    it (``source``, None when no file holds it) and the lines cut by the cap."""

    section: str
    source: Optional[str]
    lines: List[str]
    more: int


class HandoffSetting(TypedDict):
    """One resolved setting as the brief prints it: its value and where it came from
    (``setting_source``)."""

    value: str
    source: str


class HandoffDoc(TypedDict):
    """What ``handoff`` prints: the position plus what a fresh session needs."""

    position: PositionDoc
    request: Optional[str]
    report_to: Optional[str]
    next_phase: Optional[str]
    next_task: Optional[PositionTask]
    open_gates: List[str]
    decisions: List[str]
    decisions_earlier: int
    rules: List[HandoffRule]
    # The resolved `autonomy` setting (ADR 0028), printed above the Autonomy section.
    autonomy: HandoffSetting
    # FR-017: the newest `mr-opened`, which makes `render_handoff` name the close-out.
    pull_request: Optional[Dict[str, Optional[str]]]


def _next_phase(position: PositionDoc) -> Optional[str]:
    """The phase the next session works in.

    In ``implement`` with a task left, the work stays there (``implement (the next
    task)``); in ``review`` after a ``not-ready`` verdict it returns to ``implement (fix
    round)``. Otherwise the phase after the current
    one in ``PHASE_ORDER``; None after ``capture`` or on a terminal stream.
    """
    if position["lifecycle"] == "terminal":
        return None
    current = position["current"]
    if current is None:
        return PHASE_ORDER[0]
    phase = current["phase"]
    tasks = position["tasks"] or []
    verdict = position["verdict"]
    if phase == "implement" and any(not task["done"] for task in tasks):
        return "implement (the next task)"
    if phase == "review" and verdict is not None and verdict["verdict"] == "not-ready":
        return "implement (fix round)"
    index = PHASE_ORDER.index(phase)
    return PHASE_ORDER[index + 1] if index + 1 < len(PHASE_ORDER) else None


def _adr_status(project_dir: Path, ref: str) -> Optional[str]:
    """The status an ADR file declares, lower-cased; None when it cannot be read or names
    none. Only the first ``ADR_STATUS_BYTES`` of a regular file are read, opened
    non-blocking: a ref is checkout content, and a FIFO must not hang the command."""
    import stat

    fd = None
    try:
        fd = os.open(str(project_dir / ref), os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        text = os.read(fd, ADR_STATUS_BYTES).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    match = _ADR_STATUS_RE.search(text)
    if match is None:
        return None
    return next(group for group in match.groups() if group).lower()


def _open_gates(events: Sequence[Event], position: PositionDoc,
                project_dir: Path) -> List[str]:
    """What still stands between the stream and its next gate, each from a fact."""
    gates: List[str] = []
    committed = [e for e in events if e.type == "design-committed"]
    open_adrs = _string_list(committed[-1].data.get("open")) if committed else []
    for ref in dict.fromkeys(filter(None, map(_safe_ref, open_adrs))):
        status = _adr_status(project_dir, ref)
        if status in ADR_CLOSED:
            continue
        gates.append(
            f"ADR {ref} is still {status}: the tasks it governs wait for the user's answer"
            if status else
            f"ADR {ref} was left open at design; its status could not be read, so check "
            "it before the tasks it governs"
        )
    verdict = position["verdict"]
    if verdict is not None and verdict["verdict"] == "not-ready":
        gates.append(
            f"the last review verdict is not-ready (round {verdict['round']}): fix the "
            "blockers, then review again"
        )
    fixing = sorted(
        key for key, entry in position["dispositions"].items()
        if entry["state"] == "fixing"
    )
    if fixing:
        shown = ", ".join(fixing[:HANDOFF_FINDINGS_SHOWN])
        more = len(fixing) - HANDOFF_FINDINGS_SHOWN
        gates.append(
            f"{len(fixing)} review finding(s) still fixing: {shown}"
            + (f" and {more} more" if more > 0 else "")
        )
    ticked = [t["id"] for t in position["tasks"] or [] if t["ticked"] and not t["done"]]
    if ticked:
        gates.append(
            f"ticked in the worklog with no task-done: {', '.join(ticked)} — record "
            "verify-run and task-done, or the Stop gate blocks"
        )
    verify = position["last_verify"]
    if verify is not None and verify["outcome"] == "fail":
        gates.append(f"last verify failed ({_short_ts(verify['at'])})")
    publish = position["publish"]
    if publish["kind"] == "authorized":
        gates.append(f"publish authorized by {publish['by']} (seq {publish['seq']})")
    else:
        gates.append(
            "publish held: an MR/PR needs a ready review-verdict or the user's own "
            "approval"
        )
    return gates


def handoff_rules(project_dir: Path, start: Optional[Path] = None) -> List[HandoffRule]:
    """The ``HANDOFF_SECTIONS`` from the nearest config file that holds each, through the
    layers of ``config_candidates`` and the user file (ADR 0018).

    A section is present when it holds a line that is not a placeholder
    (``_config.section_lines``). That is looser than ``section_present``, which counts
    only ``Key: value`` bullets, because a prose section (Security-sensitive areas)
    holds none.
    """
    files = _config_files(project_dir, start)
    rules: List[HandoffRule] = []
    for section in HANDOFF_SECTIONS:
        name = section.lower()
        owner = _config.section_owner(
            files, name, present=lambda text, n=name: bool(_config.section_lines(text, n))
        )
        lines = _config.section_lines(owner.text, name) if owner is not None else []
        rules.append({
            "section": section,
            "source": _config_label(owner, project_dir) if owner is not None else None,
            "lines": lines[:HANDOFF_SECTION_LINES],
            "more": max(0, len(lines) - HANDOFF_SECTION_LINES),
        })
    return rules


def build_handoff(
    conn: sqlite3.Connection,
    stream: str,
    project_dir: Path,
    homes: Dict[str, str],
    now: Optional[datetime] = None,
    start: Optional[Path] = None,
) -> HandoffDoc:
    """The handoff brief for ``stream`` (ADR 0021): ``build_position`` plus the request,
    the reporting target, the next phase and task, the open gates, the latest decisions
    and the config rules. It reads the journal, the files the events name, the config
    files and the settings files; nothing from the session that runs it. A stream with
    no events raises ``InfraError``, as ``position`` does. An ``autonomy`` value outside
    its set in a settings file raises ``UsageError`` (``require_setting``).
    """
    position = build_position(conn, stream, project_dir, homes, now=now)
    resolved = project_settings(project_dir, start)
    autonomy = require_setting(resolved, "autonomy")
    events = read_events(conn, stream=stream)
    tasks = position["tasks"] or []
    decisions = [
        _render_decision(e.data) for e in events if e.type == "gate-decision"
    ]
    shown = decisions[-BRIEF_DECISION_LIMIT:]
    started = [e for e in events if e.type == "flow-started"]
    return {
        "position": position,
        "request": _string_or_none(started[0].data.get("request")) if started else None,
        "report_to": _newest_string(events, "report_to"),
        "next_phase": _next_phase(position),
        "next_task": next((t for t in tasks if not t["done"]), None),
        "open_gates": _open_gates(events, position, project_dir),
        "decisions": shown,
        "decisions_earlier": len(decisions) - len(shown),
        "rules": handoff_rules(project_dir, start),
        "autonomy": {
            "value": str(autonomy),
            "source": setting_source(resolved.get("autonomy"), project_dir),
        },
        "pull_request": pull_request(events),
    }


def _indented(line: str, base: int) -> str:
    """``line`` clipped to one line, at ``base`` spaces plus its own indent (at most 4)."""
    indent = min(len(line) - len(line.lstrip(" ")), 4)
    return " " * (base + indent) + _clip(line)


def render_handoff(doc: HandoffDoc) -> str:
    """The brief as text for a model. Every value is collapsed to one line, so a payload
    cannot add a line, a heading or a section of its own."""
    position = doc["position"]
    stream = _one_line(position["stream"])
    current = position["current"]
    artifacts = position["artifacts"]
    tasks = position["tasks"]
    lines = [
        f"shipgate handoff — {stream}  (v{position['version']})",
        "Built from the flow journal, the artifacts its events name and the project "
        "config; nothing comes from the session that printed it.",
        f"Print it again with: journal.py handoff --stream={shlex.quote(position['stream'])}",
        "",
        "role         : the orchestrator of this shipgate flow. Run /shipgate to resume; "
        "it reads the journal and routes to the next phase.",
        "request      : " + (_clip(doc["request"]) if doc["request"] else "—"),
        "phase        : "
        + (_one_line(current["phase"]) + f" (entered {_short_ts(current['entered_at'])})"
           if current else "—")
        + (f" → next: {doc['next_phase']}" if doc["next_phase"] else ""),
        "report to    : " + (
            _clip(doc["report_to"]) if doc["report_to"] else "the user"
        ),
    ]
    if doc.get("pull_request") and position["lifecycle"] != "terminal":
        lines.append(
            "close-out    : after the merge, run " + closeout_command(position["stream"])
        )
    reading = [("PRD", artifacts["prd"]), ("worklog", artifacts["worklog"])]
    reading += [("ADR", ref) for ref in artifacts["adrs"]]
    reading = [(kind, ref) for kind, ref in reading if ref]
    lines.append("open first   :" + ("" if reading else " —"))
    for index, (kind, ref) in enumerate(reading, 1):
        lines.append(f"  {index}. {kind:<8} " + _clip(ref))
    if tasks is None:
        lines.append("tasks        : — (no worklog, or it cannot be read)")
    else:
        done = sum(1 for task in tasks if task["done"])
        task = doc["next_task"]
        lines.append(
            f"tasks        : {done}/{len(tasks)} done · next: "
            + (_clip(f"{task['id']} — {task['title'] or ''}".rstrip(" —"))
               if task else "none, the Build Plan is done")
        )
    verify = position["last_verify"]
    lines.append(
        "last verify  : "
        + (f"{verify['outcome']} ({_short_ts(verify['at'])})" if verify else "—")
    )
    lines.append("open gates   :")
    lines.extend("  - " + _clip(gate) for gate in doc["open_gates"])
    lines.append("decisions    :" + ("" if doc["decisions"] else " —"))
    lines.extend("  - " + _clip(decision) for decision in doc["decisions"])
    if doc["decisions_earlier"] > 0:
        lines.append(f"  … +{doc['decisions_earlier']} earlier")
    lines.append("rules that bind:")
    lines.append(
        "  - The repo's CLAUDE.md files load at session start and stay binding; this "
        "brief does not copy them."
    )
    lines.append(
        "  - Commit only when the user asks, and stage only the files you changed "
        "(implement: Committing)."
    )
    for rule in doc["rules"]:
        if rule["section"] == "Autonomy":
            autonomy = doc["autonomy"]
            lines.append(f"  Autonomy mode: {_one_line(autonomy['value'])} "
                         f"({_one_line(autonomy['source'])})")
        if rule["source"] is None:
            lines.append(f"  {rule['section']}: none configured")
            continue
        lines.append(f"  {rule['section']} ({_one_line(rule['source'])}):")
        lines.extend(_indented(line, 4) for line in rule["lines"])
        if rule["more"]:
            lines.append(
                f"    … {rule['more']} more lines in {_one_line(rule['source'])}"
            )
    return "\n".join(lines)


# The context nudge (ADR 0022): the line the PostToolUse hook adds after a phase
# boundary, past the handoff threshold. The hook measures; this decides.
NUDGE_EVENTS = ("design-committed", "review-verdict")
DEFAULT_HANDOFF_TOKENS = 500_000
_THRESHOLD_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([km]?)$")


def parse_handoff_threshold(value: Optional[str]) -> Optional[int]:
    """The handoff threshold a `handoff` value names, in tokens; None for `off`.

    `500k`, `1m`, `1.5m` and `250000` read as written, backticks and case ignored. An
    empty, zero, negative or unreadable value falls back to the default: a nudge too
    many costs a line, a nudge lost costs the context it was meant to save.
    """
    text = (value or "").strip().strip("`").strip().lower()
    if text == "off":
        return None
    match = _THRESHOLD_RE.match(text)
    if match is None:
        return DEFAULT_HANDOFF_TOKENS
    scale = {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2)]
    tokens = int(float(match.group(1)) * scale)
    return tokens if tokens > 0 else DEFAULT_HANDOFF_TOKENS


def handoff_threshold(project_dir: Path, start: Optional[Path] = None) -> Optional[int]:
    """The resolved ``handoff`` setting in tokens (ADR 0028); None when it says `off`.

    The nudge runs from a hook, so this never refuses: a value outside its set gives
    the default. A settings file may hold an integer (``300000``) or a string
    (``"500k"``); a legacy ``## Session`` `Handoff:` line still counts.
    """
    value = project_settings(project_dir, start).value("handoff")
    return parse_handoff_threshold(None if value is None else str(value))


def _tokens_label(tokens: int) -> str:
    """`612k` under a million, `1m` or `1.2m` from there (rounded first, so 999,600 is
    `1m`, not `1000k`)."""
    thousands = round(tokens / 1000)
    if thousands >= 1000:
        return f"{round(tokens / 1_000_000, 1):g}m"
    return f"{thousands}k"


def nudge_line(conn: sqlite3.Connection, stream: str, event_type: str, tokens: int,
               seq: int, project_dir: Path, start: Optional[Path] = None) -> Optional[str]:
    """The nudge, or None. It speaks only when the stream's newest ``event_type`` is the
    row ``seq`` (so a quoted old append line says nothing), a verdict says ``not-ready``,
    and ``tokens`` reaches the threshold."""
    threshold = handoff_threshold(project_dir, start)
    if threshold is None or tokens < threshold:
        return None
    events = [e for e in read_events(conn, stream=stream) if e.type == event_type]
    if not events or events[-1].seq != seq:
        return None
    if event_type == "review-verdict" and events[-1].data.get("verdict") != "not-ready":
        return None
    return _one_line(
        f"shipgate: this session's context is about {_tokens_label(tokens)} tokens, past "
        f"the handoff threshold ({_tokens_label(threshold)}). A fresh session is cheaper "
        f"from here: print the brief with `journal.py handoff "
        f"--stream={shlex.quote(stream)}`, then "
        "run /clear and /shipgate."
    )
