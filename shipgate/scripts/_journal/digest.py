"""`digest`: the block the user reads at the publish question (ADR 0030, #25).

Four parts in a fixed order, each with a fixed slot: what changed (the worklog's
`## What changed` section), what the orchestrator decided alone (the PRD's open assumption
items and the executive gate decisions after the last `clarify-passed`), the deviations
after the last `design-committed`, and the first files of the newest risk ranking.
`build_digest` reads the journal, the worklog and the PRD; it runs no git and writes
nothing. `render_digest` caps each part at its slot and passes every value through
`_line`, so a payload can add no line and no control character.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from .vocab import BRIEF_LINE_CHARS, GATE_WAIVED, SIGNALS_MISSING_KIND
from .text import _one_line
from .store import Event, read_events
from .artifacts import _safe_ref
from .status import _render_decision
from .position import build_position, PositionDoc
from .assumptions import is_risky, parse_assumptions, scan_section, SectionError


# The list parts in print order: (DigestDoc key, heading, slot). A new part (#26) is one
# entry here plus its items in `build_digest`; `max_lines` grows by 1 + its slot.
LIST_PARTS = (("decided", "decided alone", 4), ("deviations", "deviations", 3))
WHAT_CHANGED_SLOT = 5
LOOK_HERE_FILES = 3
# Deviations that record bookkeeping, not a divergence from the design.
BOOKKEEPING_KINDS = (SIGNALS_MISSING_KIND, "style-missing", GATE_WAIVED)

_WHAT_CHANGED_HEADING = re.compile(r"^## What changed\s*$")
# A character that is no printable text, after `_one_line`: a control character (ESC
# starts a terminal sequence), a format character (a bidi override reorders the line).
_REPLACEMENT = chr(0xFFFD)


class DigestVerdict(TypedDict):
    verdict: str
    round: int


class DigestWhatChanged(TypedDict):
    items: List[str]
    error: Optional[str]


class DigestDecided(TypedDict):
    """``source`` is ``prd`` (``line`` set) or ``journal`` (``seq`` set)."""

    source: str
    text: str
    risky: bool
    line: Optional[int]
    seq: Optional[int]


class DigestDecidedPart(TypedDict):
    items: List[DigestDecided]
    error: Optional[str]


class DigestDeviation(TypedDict):
    seq: int
    text: str


class DigestDeviationsPart(TypedDict):
    items: List[DigestDeviation]


# ``from`` names the event that carried the ranking; None with no usable one. The key is
# a Python keyword, so the type takes the functional form.
DigestLookHere = TypedDict("DigestLookHere", {
    "files": List[str], "from": Optional[str], "unavailable": Optional[str],
})


class DigestDoc(TypedDict):
    """``digest --stream <s> --json``. The lists are uncapped; only the text caps."""

    stream: str
    verdict: Optional[DigestVerdict]
    publish: str
    worklog: Optional[str]
    prd: Optional[str]
    what_changed: DigestWhatChanged
    decided: DigestDecidedPart
    deviations: DigestDeviationsPart
    look_here: DigestLookHere


def max_lines() -> int:
    """The most lines the text prints without ``--all``: the first line, the what
    changed slot, a heading and a slot per list part, and the look-here line."""
    return 1 + WHAT_CHANGED_SLOT + sum(1 + slot for _, _, slot in LIST_PARTS) + 1


def parse_what_changed(text: str) -> Optional[List[str]]:
    """The items of the worklog's `## What changed` section; None with no section.

    The section has the strict line rules of the assumptions section (`scan_section`):
    items `- ` or `* ` at column 0, indented continuation lines joined with a space,
    blank lines, and nothing else. On top: no item is refused at the heading's line, an
    item whose bullet line is empty and a sixth item at their own line. Raises
    `SectionError`.
    """
    heading, items = scan_section(
        text, _WHAT_CHANGED_HEADING, "## What changed", "what changed",
        "one-line list items",
    )
    if heading is None:
        return None
    if not items:
        raise SectionError(heading, "no item in the section")
    lines = text.splitlines()
    for index, (line, body) in enumerate(items):
        if not lines[line - 1][2:].strip():
            raise SectionError(line, "empty item")
        if index == WHAT_CHANGED_SLOT:
            raise SectionError(line, f"more than {WHAT_CHANGED_SLOT} items")
    return [body for _, body in items]


def _plain_ref(value: Any) -> Optional[str]:
    """``value`` when it is a safe ref (``_safe_ref``) with no whitespace and only
    printable characters; else None. ``_safe_ref`` looks at the first character, so
    `` /home/x`` would pass it and then print as an absolute path once collapsed, and one
    ref that holds `` · `` would print as several."""
    ref = _safe_ref(value)
    if ref is None or ref != value or not ref.isprintable() \
            or any(char.isspace() for char in ref):
        return None
    return ref


def _read(project_dir: Path, ref: str) -> Optional[str]:
    """The file's text, undecodable bytes replaced (as `build_position` reads the
    worklog); None when it cannot be read."""
    try:
        return (project_dir / ref).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _what_changed(project_dir: Path, worklog: Optional[str],
                  unusable: bool) -> DigestWhatChanged:
    """The section's items, or why there are none. ``unusable``: the stream has a
    worklog ref that ``_plain_ref`` refused; the line never prints that ref."""
    if unusable:
        return {"items": [], "error": "the worklog ref is not usable (whitespace or a "
                                      "control character) — its sections were not read"}
    if worklog is None:
        return {"items": [], "error": "no worklog recorded for this stream"}
    text = _read(project_dir, worklog)
    if text is None:
        return {"items": [], "error": f"{worklog}: cannot be read"}
    try:
        items = parse_what_changed(text)
    except SectionError as exc:
        return {"items": [], "error": f"{worklog}:{exc.line}: {exc.reason}"}
    if items is None:
        return {"items": [], "error": f'no "## What changed" section in {worklog}'}
    return {"items": items, "error": None}


def _last_seq(events: List[Event], event_type: str) -> int:
    """The seq of the stream's last ``event_type``, or 0 with none."""
    return max((e.seq for e in events if e.type == event_type), default=0)


def _decided(project_dir: Path, prd: Optional[str],
             events: List[Event]) -> DigestDecidedPart:
    """The open PRD items (risky first) around the executive gate decisions."""
    error: Optional[str] = None
    prd_items: List[Dict[str, Any]] = []
    since = _last_seq(events, "clarify-passed")
    if prd is None and since:
        error = ("the last clarify-passed names no usable PRD ref — the PRD's "
                 "assumptions were not read")
    if prd is not None:
        text = _read(project_dir, prd)
        if text is None:
            error = f"{prd}: cannot be read"
        else:
            try:
                prd_items = [i for i in parse_assumptions(text)
                             if i["end"] in (None, "unconfirmed")]
            except SectionError as exc:
                error = (f"{prd}:{exc.line}: {exc.reason} — the PRD's assumptions were "
                         "not read")

    def from_prd(item: Dict[str, Any]) -> DigestDecided:
        return {"source": "prd", "risky": is_risky(item), "line": item["line"],
                "seq": None,
                "text": f"[{item['class']}] {item['question']} → {item['answer']}"}

    journal: List[DigestDecided] = [
        {"source": "journal", "text": _render_decision(e.data), "risky": False,
         "line": None, "seq": e.seq}
        for e in events
        if e.type == "gate-decision" and e.seq > since
        and e.data.get("mode") == "executive"
        and e.data.get("raised_by", "orchestrator") == "orchestrator"
    ]
    risky = [from_prd(i) for i in prd_items if is_risky(i)]
    rest = [from_prd(i) for i in prd_items if not is_risky(i)]
    return {"items": risky + journal + rest, "error": error}


def _note(data: Dict[str, Any]) -> str:
    """A deviation's note; the shape's aliases for an old row; else ``(no note)``. A
    blank string counts as none."""
    for key in ("note", "correction", "what"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "(no note)"


def _deviations(events: List[Event]) -> DigestDeviationsPart:
    since = _last_seq(events, "design-committed")
    return {"items": [
        {"seq": e.seq, "text": _note(e.data)} for e in events
        if e.type == "deviation" and e.seq > since
        and e.data.get("kind") not in BOOKKEEPING_KINDS and "report_to" not in e.data
    ]}


def _look_here(position: PositionDoc) -> DigestLookHere:
    """The first files of the newest recorded ranking, or why there are none."""
    trace = position["trace"]
    for key, origin in (("review_ranking", "review-verdict"),
                        ("design_ranking", "design-committed")):
        carrier = trace[key]
        if carrier is None:
            continue
        ranking = carrier["ranking"]
        if not isinstance(ranking, dict):
            break
        if ranking.get("source") == "none":
            reason = ranking.get("unavailable")
            return {"files": [], "from": origin,
                    "unavailable": reason if isinstance(reason, str) else "none"}
        listed = ranking.get("files")
        paths = [_plain_ref(f.get("path")) for f in listed if isinstance(f, dict)] \
            if isinstance(listed, list) else []
        files = [p for p in paths if p is not None][:LOOK_HERE_FILES]
        if files:
            return {"files": files, "from": origin, "unavailable": None}
        break
    return {"files": [], "from": None, "unavailable": None}


def build_digest(conn: sqlite3.Connection, stream: str, project_dir: Path,
                 homes: Dict[str, str]) -> DigestDoc:
    """The digest of ``stream``: ``build_position``, the stream's events, the worklog
    and the PRD. A stream with no events raises ``InfraError``, as ``position`` does."""
    position = build_position(conn, stream, project_dir, homes)
    events = read_events(conn, stream=stream)
    recorded = position["artifacts"]["worklog"]
    worklog = _plain_ref(recorded)
    prd = _plain_ref(position["artifacts"]["prd"])
    verdict = position["verdict"]
    return {
        "stream": stream,
        "verdict": ({"verdict": verdict["verdict"], "round": verdict["round"]}
                    if verdict else None),
        # The user's publish go, not `publish`: a ready verdict opens the journal's
        # publish gate, but the digest is shown at the question that asks for the go.
        "publish": position["go"]["publish"]["kind"],
        "worklog": worklog,
        "prd": prd,
        "what_changed": _what_changed(project_dir, worklog,
                                      recorded is not None and worklog is None),
        "decided": _decided(project_dir, prd, events),
        "deviations": _deviations(events),
        "look_here": _look_here(position),
    }


def _line(text: Any, prefix: str = "") -> str:
    """``prefix`` and ``text`` as one printable line of at most ``BRIEF_LINE_CHARS``.

    ``_one_line`` collapses whitespace; every character that is still not printable is
    replaced, so a planted escape sequence cannot move the cursor or reorder the line.
    """
    flat = "".join(c if c.isprintable() else _REPLACEMENT for c in _one_line(text))
    room = BRIEF_LINE_CHARS - len(prefix)
    if len(flat) > room:
        flat = flat[: room - 1] + "…"
    return prefix + flat


def _list_part(heading: str, texts: List[str], show_all: bool, slot: int,
               note: str = "", error: Optional[str] = None) -> List[str]:
    """A heading line and the item lines; an error is the first item and takes a slot."""
    entries = ([error] if error else []) + texts
    if not entries:
        return [_line(f"{heading}: none")]
    shown = entries if show_all else entries[:slot]
    count = len(texts)
    if len(shown) < len(entries):
        kept = len(shown) - (1 if error else 0)
        head = f"{heading} ({count}, {kept} shown; --all prints every one{note}):"
    else:
        head = f"{heading} ({count}{note}):"
    return [_line(head)] + [_line(entry, "  - ") for entry in shown]


def render_digest(doc: DigestDoc, show_all: bool = False) -> str:
    """The digest as text: at most ``max_lines()`` lines, or every item with
    ``show_all``. Every line is printable and at most ``BRIEF_LINE_CHARS`` long."""
    verdict = doc["verdict"]
    what = doc["what_changed"]
    first = (f"{doc['stream']} — verdict "
             + (f"{verdict['verdict']} (round {verdict['round']})" if verdict else "—")
             + f" · publish {doc['publish']}. What changed:"
             + (f" — {what['error']}" if what["error"] else ""))
    lines = [_line(first)]
    lines += [_line(item, "  - ") for item in what["items"][:WHAT_CHANGED_SLOT]]
    note = f"; notes in {doc['worklog']}" if doc["worklog"] else ""
    for key, heading, slot in LIST_PARTS:
        part = doc[key]
        lines += _list_part(
            heading, [item["text"] for item in part["items"]], show_all, slot,
            note=note if key == "deviations" else "", error=part.get("error"),
        )
    look = doc["look_here"]
    if look["files"]:
        lines.append(_line("look here first: " + " · ".join(look["files"])))
    elif look["unavailable"] is not None:
        lines.append(_line(
            f"look here first: — risk signals unavailable ({look['unavailable']})"))
    else:
        lines.append(_line("look here first: — no risk ranking recorded"))
    return "\n".join(lines)
