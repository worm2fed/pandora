"""`digest`: the table the user reads before the publish question (ADR 0030, #25).

Four parts in a fixed order, each with a fixed slot: what changed (the worklog's
`## What changed` section), what the orchestrator decided alone (the PRD's open assumption
items and the executive gate decisions after the last `clarify-passed`), the deviations
after the last `design-committed`, and the first files of the newest risk ranking.
`build_digest` reads the journal, the worklog and the PRD; it runs no git and writes
nothing. `render_digest` prints one markdown table, the only text form. It caps each part
at its slot, and every cell value passes `_markdown_cell` or `_markdown_code`: one line,
printable, every markdown character of a fixed set escaped, clipped. So a payload can add
no line, no row, no column, no link that hides its target and no emphasis.
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


# The parts in print order: (DigestDoc key, name, slot). A new part (#26's Screens) is one
# entry here plus its items in `build_digest`; `max_lines` grows by its slot.
PARTS = (("what_changed", "What changed", 3), ("decided", "Decided alone", 2),
         ("deviations", "Deviations", 2))
# The "## What changed" section's own cap; the table shows the first slot of them.
WHAT_CHANGED_ITEMS = 5
LOOK_HERE_FILES = 3
# The characters a markdown renderer gives meaning to in a table cell: the cell and row
# delimiter, escapes and hard breaks, code, emphasis and strikethrough, links and images,
# HTML and autolinks, entities, math. Each one gets a backslash, in every cell value.
MARKDOWN_SPECIAL = "\\`*_[]<>|~&$"
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
    """The most lines the table prints without ``--all``: the header row, the separator,
    the slot of each part, and the Look first row."""
    return 2 + sum(slot for _, _, slot in PARTS) + 1


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
        if index == WHAT_CHANGED_ITEMS:
            raise SectionError(line, f"more than {WHAT_CHANGED_ITEMS} items")
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


def _flat(text: Any) -> str:
    """``text`` on one line with only printable characters: ``_one_line`` collapses
    whitespace, and every character that is still not printable is replaced, so a
    planted escape sequence cannot move the cursor or reorder the line."""
    return "".join(c if c.isprintable() else _REPLACEMENT for c in _one_line(text))


def _markdown_cell(text: Any, room: int) -> str:
    """``text`` as table-cell text of at most ``room`` characters.

    Each character of ``MARKDOWN_SPECIAL`` gets a backslash. A clipped value ends with
    "…" and never splits a backslash from its character, so no escape is left open.
    """
    tokens = ["\\" + c if c in MARKDOWN_SPECIAL else c for c in _flat(text)]
    if sum(len(token) for token in tokens) <= room:
        return "".join(tokens)
    kept: List[str] = []
    used = 0
    for token in tokens:
        if used + len(token) > room - 1:
            break
        kept.append(token)
        used += len(token)
    return "".join(kept) + "…"


def _markdown_code(text: Any, room: int) -> str:
    """``text`` as inline code when it holds no backtick, pipe or backslash and fits in
    ``room``; else as ``_markdown_cell`` text. Nothing inside a code span is markdown."""
    flat = _flat(text)
    if any(c in flat for c in "`|\\") or len(flat) + 2 > room:
        return _markdown_cell(flat, room)
    return f"`{flat}`"


def _row(first: str, value: str) -> str:
    """One table row. ``first`` is fixed text; ``value`` is already a safe cell."""
    return f"| {first} | {value} |"


def _room(first: str) -> int:
    """The characters left for the value cell of a row whose first cell is ``first``."""
    return BRIEF_LINE_CHARS - len(_row(first, ""))


def _part_rows(name: str, texts: List[str], show_all: bool, slot: int,
               error: Optional[str] = None) -> List[str]:
    """The rows of one part. The first cell names the part on its first row, with the
    full count when the slot cuts it; an error is one fixed line and takes a slot."""
    entries = ([error] if error else []) + texts
    if not entries:
        entries = ["none"]
    shown = entries if show_all else entries[:slot]
    first = f"**{name}**" + (f" ({len(texts)})" if len(shown) < len(entries) else "")
    rows = []
    for index, entry in enumerate(shown):
        cell = first if index == 0 else ""
        rows.append(_row(cell, _markdown_cell(entry, _room(cell))))
    return rows


def _look_first_row(look: DigestLookHere) -> str:
    first = "**Look first**"
    room = _room(first)
    files = look["files"]
    if files:
        codes = [_markdown_code(path, room) for path in files]
        value = " · ".join(codes)
        if len(value) > room or not all(c.startswith("`") for c in codes):
            value = _markdown_cell(" · ".join(files), room)
    elif look["unavailable"] is not None:
        value = _markdown_cell(
            f"— risk signals unavailable ({look['unavailable']})", room)
    else:
        value = "— no risk ranking recorded"
    return _row(first, value)


def render_digest(doc: DigestDoc, show_all: bool = False) -> str:
    """The digest as one markdown table: at most ``max_lines()`` lines, or every item
    with ``show_all``. Every line is printable, at most ``BRIEF_LINE_CHARS`` long, and
    every value from a journal row or a file is an inert cell."""
    verdict = doc["verdict"]
    state = ("verdict "
             + (f"{verdict['verdict']} (round {verdict['round']})" if verdict else "—")
             + f" · publish {doc['publish']}")
    stream = _markdown_code(doc["stream"], BRIEF_LINE_CHARS - len(_row("", state)))
    lines = [_row(stream, _markdown_cell(state, BRIEF_LINE_CHARS)), "|---|---|"]
    for key, name, slot in PARTS:
        part = doc[key]
        texts = [item if isinstance(item, str) else item["text"]
                 for item in part["items"]]
        lines += _part_rows(name, texts, show_all, slot, error=part.get("error"))
    lines.append(_look_first_row(doc["look_here"]))
    return "\n".join(lines)
