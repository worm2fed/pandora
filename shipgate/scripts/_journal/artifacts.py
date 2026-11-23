"""Authorship claims, classification by home, build-plan parsing, worklog binding."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import (
    Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple, TypedDict,
)

from .vocab import (
    _BUILD_PLAN_RE, _PLAN_HEADING_RE, _PLAN_TASK_RE, DEFAULT_ARTIFACT_HOMES,
    FEATURE_STREAM_PREFIX,
)
from .text import _normalized_ref
from .store import Event, list_streams, read_events
from .fold import fold_stream, is_work_stream


# --------------------------------------------------------------------------
# Gate validation (rules v1)
# --------------------------------------------------------------------------


def _resolve_artifact(project_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_dir / candidate


# --------------------------------------------------------------------------
# check — the Stop hook gate
# --------------------------------------------------------------------------


def parse_ticked_tasks(text: str) -> List[str]:
    """Return the task ids ticked in the Build Plan section, in document order.

    When no Build Plan heading exists the whole document is scanned, so a bare
    checklist still works. The grammar is ``parse_build_plan``'s, so the Stop gate and
    the HUD read one list.
    """
    seen: List[str] = []
    for task in parse_build_plan(text):
        if task["ticked"] and task["id"] not in seen:
            seen.append(task["id"])
    return seen


def _build_plan_region(text: str) -> str:
    """The text after the Build Plan heading, up to the next heading of its level or a
    higher one; the whole text when there is no such heading."""
    match = _BUILD_PLAN_RE.search(text)
    if not match:
        return text
    level = len(match.group(1))
    rest = text[match.end():]
    closing = re.search(r"^#{1,%d}\s+\S" % level, rest, re.MULTILINE)
    return rest[: closing.start()] if closing else rest


def _plan_task_title(rest: str) -> Optional[str]:
    """The title in what follows a task id: past a dash or a colon and a ``[P]`` marker on
    either side of it, up to the next spaced em or en dash. None when nothing is left."""
    lead = re.sub(r"^\[P\]\s*", "", rest.strip())
    lead = re.sub(r"^(?:[—–-]+|:)\s*", "", lead)
    lead = re.sub(r"^\[P\]\s*", "", lead)
    title = re.split(r"\s+[—–](?:\s+|$)", lead, maxsplit=1)[0].strip()
    return title or None


class PlanTask(TypedDict):
    """One task line of a worklog's Build Plan: ``- [x] T013 — title — file(s): ...``,
    or with a bold id and a colon, ``- [x] **T013**: title``."""

    id: str
    title: Optional[str]
    section: Optional[str]
    ticked: bool


def parse_build_plan(text: str) -> List[PlanTask]:
    """Every task line of the Build Plan section, in document order.

    The grammar is ``parse_ticked_tasks``', the Stop gate's rule A, and stays one
    grammar: once this lands, ``parse_ticked_tasks`` returns the ticked ids of this
    list, the first occurrence of each (audit D9).
    - The region starts after a ``Build Plan`` heading of any level, in any case, and
      ends at the next heading of the same or a higher level. With no such heading the
      whole document is the region.
    - A task line is a ``-`` or ``*`` bullet, a ``[ ]``, ``[x]`` or ``[X]`` box, then an
      id: ``T`` and digits, ending at a word boundary (``T001``, never ``T001a``). The id
      may be bold, ``**T001**`` or ``**T001:**``; the closing ``**`` must follow the
      digits or that colon. ``ticked`` is the box's state. So ``- [x] T1 - title``,
      ``- [x] **T1** title``, ``- [x] **T001**: title`` and ``- [x] **T001:** title`` are
      all task lines.
    - ``title`` is the text after the id, an optional ``[P]`` marker and the dash or the
      colon after them, up to the next spaced em or en dash (`` — file(s): ...``). It is
      kept as written, backticks included: display work stays in the HUD. None when the
      line has no title, never ''.
    - ``section`` is the nearest heading above the line inside the region; None when
      there is none.
    A repeated id gives one entry per line, so ``parse_ticked_tasks`` keeps its current
    result: the first *ticked* line of each id. ``build_position`` keeps the first line
    of each id.
    """
    region = _build_plan_region(text)
    headings = [(m.start(), m.group(1)) for m in _PLAN_HEADING_RE.finditer(region)]
    tasks: List[PlanTask] = []
    for match in _PLAN_TASK_RE.finditer(region):
        section: Optional[str] = None
        for start, heading in headings:
            if start >= match.start():
                break
            section = heading
        tasks.append({
            "id": match.group(2) or match.group(3),
            "title": _plan_task_title(match.group(4)),
            "section": section,
            "ticked": match.group(1) in ("x", "X"),
        })
    return tasks


ClaimSource = Literal["tool", "bash", "disk"]
ClaimEvidence = Literal["diff", "window"]
# One artifact write, as the hooks identify it: the path and the file's mtime (None when
# the hook could not stat the file).
ArtifactKey = Tuple[str, Optional[float]]


class Claim(TypedDict):
    """What one ``artifact-written`` row says about who wrote the file (ADR 0008).

    ``session`` is the author the row claims. It is never set for ``disk``: a watcher's
    ``observed_by`` names who saw the write, not who made it. ``evidence`` is set only
    for ``bash``.
    """

    source: ClaimSource
    session: Optional[str]
    evidence: Optional[ClaimEvidence]


def claim_of(event: Event) -> Optional[Claim]:
    """The claim one event makes, or None when it makes none.

    Only an ``artifact-written`` event with a string ``data.path`` claims, and its
    ``data.source`` decides the rest:
    - ``tool``: ``session`` is ``data.session``;
    - ``bash``: ``session`` is ``data.session`` and ``evidence`` is ``data.evidence``;
      evidence other than ``diff`` or ``window`` makes no claim;
    - ``disk``: ``session`` is None whatever the row carries, so a legacy row with
      ``session`` in place of ``observed_by`` counts as observed;
    - any other source makes no claim.
    A ``tool`` or ``bash`` row without a session string claims with ``session`` None.
    """
    if event.type != "artifact-written" or not isinstance(event.data.get("path"), str):
        return None
    source = event.data.get("source")
    session = event.data.get("session")
    author = session if isinstance(session, str) and session else None
    if source == "tool":
        return Claim(source="tool", session=author, evidence=None)
    if source == "bash":
        evidence = event.data.get("evidence")
        if evidence == "diff":
            return Claim(source="bash", session=author, evidence="diff")
        if evidence == "window":
            return Claim(source="bash", session=author, evidence="window")
        return None
    if source == "disk":
        return Claim(source="disk", session=None, evidence=None)
    return None


# How strong each claim's evidence is; 0 never ranks (ADR 0008).
_CLAIM_RANKS: Dict[Tuple[str, Optional[str]], int] = {
    ("tool", None): 3,
    ("bash", "diff"): 2,
    ("bash", "window"): 1,
}


def _claim_rank(claim: Claim) -> int:
    if claim["session"] is None:
        return 0
    return _CLAIM_RANKS.get((claim["source"], claim["evidence"]), 0)


def _artifact_key(data: Dict[str, Any]) -> ArtifactKey:
    """The write a claiming row names. A non-numeric mtime is no mtime at all."""
    mtime = data.get("mtime")
    if isinstance(mtime, bool) or not isinstance(mtime, (int, float)):
        return data["path"], None
    return data["path"], float(mtime)


def artifact_authors(events: Iterable[Event]) -> Dict[ArtifactKey, Optional[str]]:
    """Who wrote each artifact write, decided when the journal is read (ADR 0008).

    Claims are grouped by ``(data.path, data.mtime)``; claims without a session are
    left out of the ranking. ``tool`` beats ``bash`` with ``diff`` evidence, which beats
    ``bash`` with ``window`` evidence. The session at the best rank is the author when
    it is one session; two different sessions there give None, and so does a group with
    no ranked claim (``disk`` only). Every key a claim names is in the result. The Stop
    gate's rule A and ``stats`` read authors from this, never from raw rows.
    """
    best: Dict[ArtifactKey, Tuple[int, Set[str]]] = {}
    for event in events:
        claim = claim_of(event)
        if claim is None:
            continue
        key = _artifact_key(event.data)
        rank, sessions = best.setdefault(key, (0, set()))
        claimed = _claim_rank(claim)
        if claimed == 0 or claimed < rank or claim["session"] is None:
            continue
        if claimed > rank:
            best[key] = (claimed, {claim["session"]})
        else:
            sessions.add(claim["session"])
    return {
        key: next(iter(sessions)) if len(sessions) == 1 else None
        for key, (_, sessions) in best.items()
    }


def _matches_glob(path: str, pattern: str) -> bool:
    from fnmatch import fnmatch

    normalized = path.replace(os.sep, "/")
    if fnmatch(normalized, pattern):
        return True
    # Allow a project-relative glob to match an absolute or deeper path. Only a leading
    # `./` goes: `lstrip("./")` stripped a character set, so `.notes/` lost its dot.
    return fnmatch(normalized, "*/" + pattern.removeprefix("./"))


def classify_artifact(path: str, homes: Dict[str, str]) -> Optional[str]:
    """Classify an artifact path most-specific-first.

    ``artifact_homes.prd`` is typically ``docs/prd/*.md``, which also matches
    ``docs/prd/<name>.worklog.md`` — so worklogs are tested first and a worklog
    is never mistaken for a PRD.
    """
    normalized = path.replace(os.sep, "/")
    if normalized.endswith(".worklog.md") or _matches_glob(
        normalized, homes.get("worklog", DEFAULT_ARTIFACT_HOMES["worklog"])
    ):
        return "worklog"
    if _matches_glob(normalized, homes.get("adr", DEFAULT_ARTIFACT_HOMES["adr"])):
        return "adr"
    if _matches_glob(normalized, homes.get("prd", DEFAULT_ARTIFACT_HOMES["prd"])):
        return "prd"
    return None


def _slug_from_artifact(path: str) -> str:
    name = os.path.basename(path.replace(os.sep, "/"))
    if name.endswith(".worklog.md"):
        return name[: -len(".worklog.md")]
    if name.endswith(".md"):
        return name[: -len(".md")]
    return name


def _names_artifact(path: str, ref: str) -> bool:
    """True when an event's ``ref`` names the artifact a hook recorded at ``path``.

    The hook's path is relative to the project. A nested repo's stream names its worklog
    relative to that repo, so the ref may be a tail of the path (the rule
    ``_free_slug_named_worklog`` applies to a claim).
    """
    path, ref = _normalized_ref(path), _normalized_ref(ref)
    return bool(ref) and (path == ref or path.endswith("/" + ref))


# A leading issue id in a slug: ASCII digits and a dash, with a name after them.
_ISSUE_ID_RE = re.compile(r"[0-9]+-(.+)")


def _stream_slugs(stream: str) -> List[str]:
    """The slugs that name a stream's worklog, most exact first: the stream's last path
    segment, then that segment without one leading issue id (#43). The stream
    ``fix/1290-date-off-by-one`` gives ``1290-date-off-by-one``, then ``date-off-by-one``.
    """
    slug = stream.rsplit("/", 1)[-1]
    if not slug:
        return []
    match = _ISSUE_ID_RE.fullmatch(slug)
    return [slug, match.group(1)] if match else [slug]


def _slug_names_file(slug: str, name: str) -> bool:
    """``<slug>.worklog.md``, or a name that starts with ``<slug>-`` or ``<slug>.``: a
    substring match would let a short slug take another feature's worklog."""
    return bool(slug) and (
        name == f"{slug}.worklog.md"
        or name.startswith(f"{slug}-")
        or name.startswith(f"{slug}.")
    )


def _has_flow_event(events: Sequence[Event]) -> bool:
    """`artifact-written` is the capture hook's own footprint, so it never makes a
    stream a tracked flow: counting it would mark every observed file as tracked."""
    return any(e.type != "artifact-written" for e in events)


def worklog_owners(
    conn: sqlite3.Connection,
    by_stream: Dict[str, List[Event]],
    path: str,
    project_dir: Path,
    homes: Dict[str, str],
) -> Tuple[List[str], List[str]]:
    """The work streams that own the worklog at ``path``: (live or dormant, finished).

    A stream owns a worklog the way ``position`` shows one (ADR 0020):
    - ``event``: its last worklog ref names the path;
    - ``name``: it has no worklog ref, and the path is the slug-named worklog
      ``position`` would pick for it (``_stream_slugs``: the slug, then the slug without
      its issue id);
    - ``legacy``: it has no worklog ref and is named ``feature/<worklog file name>``
      (journals from before v0.11).
    The most exact binding wins. A stream whose events name the worklog, live or
    finished, leaves nothing to a name. Among names, ``<slug>.worklog.md`` beats a
    prefix, then the longer slug, then the full slug beats one without its issue id: a
    parent stream ``epic/auth`` does not take the child's ``auth-login.worklog.md``, and
    ``feat/demo`` takes ``demo.worklog.md`` from ``fix/1290-demo``. A stream's first slug
    that names the file is its best one. A stream with no flow event owns nothing.
    Streams come back in name order.
    """
    relative = path
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(project_dir).as_posix()
        except ValueError:
            relative = path
    name = relative.replace(os.sep, "/").rsplit("/", 1)[-1]
    legacy = FEATURE_STREAM_PREFIX + _slug_from_artifact(path)

    by_event: List[str] = []
    by_name: List[Tuple[Tuple[bool, int, bool], str]] = []
    for stream in sorted(by_stream):
        events = by_stream[stream]
        if not _has_flow_event(events):
            continue
        bound = _event_bound_worklog(events, homes)
        if bound is not None:
            if _names_artifact(relative, bound):
                by_event.append(stream)
            continue
        slugs = _stream_slugs(stream)
        slug = next((s for s in slugs if _slug_names_file(s, name)), None)
        if slug is None:
            continue
        owns = stream == legacy
        if not owns:
            found = _free_slug_named_worklog(conn, stream, project_dir, homes, None)
            owns = found is not None and _normalized_ref(found) == _normalized_ref(
                relative
            )
        if owns:
            by_name.append((
                (name == f"{slug}.worklog.md", len(slug), slug == slugs[0]), stream
            ))

    owning = by_event
    if not owning and by_name:
        best = max(rank for rank, _ in by_name)
        owning = [stream for rank, stream in by_name if rank == best]
    owners: List[str] = []
    finished: List[str] = []
    for stream in owning:
        (finished if fold_stream(by_stream[stream])["terminal"] else owners).append(stream)
    return owners, finished


# The event types whose refs commit a stream to an artifact: the design landing, work on
# its tasks, its review and its decisions. A `flow-started`, `phase-entered` or
# `deviation` ref is context, often an older slice's artifact, and never counts.
POSITION_ARTIFACT_EVENTS = (
    "design-committed", "design-queued", "task-done", "verify-run",
    "review-verdict", "gate-decision",
)


def _is_safe_ref(path: str) -> bool:
    """A ref the HUD may read: relative, no ``..`` segment, no drive or scheme."""
    if not path or path[0] in "/\\":
        return False
    if re.match(r"[A-Za-z]:", path) or re.match(r"[A-Za-z]+://", path):
        return False
    return ".." not in re.split(r"[\\/]", path)


def _safe_ref(value: Any) -> Optional[str]:
    """``value`` as a ref to print: a string, its ``#fragment`` dropped, and safe."""
    if not isinstance(value, str):
        return None
    path = value.split("#", 1)[0]
    return path if _is_safe_ref(path) else None


def _committed_refs(events: Sequence[Event]) -> List[str]:
    """The safe refs of the events that commit or work an artifact, in event order:
    each event's ``data.worklog``, then ``data.refs``, then ``data.adrs``."""
    refs: List[str] = []
    for event in events:
        if event.type not in POSITION_ARTIFACT_EVENTS:
            continue
        values: List[Any] = [event.data.get("worklog")]
        for key in ("refs", "adrs"):
            listed = event.data.get(key)
            if isinstance(listed, list):
                values.extend(listed)
        refs.extend(ref for ref in map(_safe_ref, values) if ref is not None)
    return refs


def _event_bound_worklog(events: Sequence[Event], homes: Dict[str, str]) -> Optional[str]:
    """The last worklog a stream's committing events name, or None: the worklog
    ``position`` shows as ``worklog_from: event`` and the Stop gate judges (ADR 0020)."""
    worklog: Optional[str] = None
    for ref in _committed_refs(events):
        if classify_artifact(ref, homes) == "worklog":
            worklog = ref
    return worklog


_GLOB_MAGIC_RE = re.compile(r"[*?[]")


def _worklog_home_dirs(project_dir: Path, home: str) -> List[Tuple[str, str]]:
    """The directories a worklog home names, each with the file pattern for it.

    A literal directory, or ``*`` as the first segment for each visible child directory
    of the project. Deeper wildcards are not walked: this feeds a fallback, which is not
    worth a walk of the whole project.
    """
    home = home.replace(os.sep, "/").removeprefix("./")
    if not _is_safe_ref(home):
        return []
    directory, _, pattern = home.rpartition("/")
    if not pattern:
        return []
    if not _GLOB_MAGIC_RE.search(directory):
        return [(directory, pattern)]
    head, _, rest = directory.partition("/")
    if head != "*" or _GLOB_MAGIC_RE.search(rest):
        return []
    try:
        children = sorted(
            entry.name for entry in os.scandir(project_dir)
            if entry.is_dir() and not entry.name.startswith(".")
        )
    except OSError:
        return []
    return [(f"{child}/{rest}" if rest else child, pattern) for child in children]


def _free_slug_named_worklog(
    conn: sqlite3.Connection,
    stream: str,
    project_dir: Path,
    homes: Dict[str, str],
    now: Optional[datetime],
) -> Optional[str]:
    """The newest free worklog in the worklog home that the stream's slug names, or None.

    A worklog is free when no other live stream's events name it. ``_stream_slugs``
    gives the slugs, most exact first: the last path segment, then that segment without
    its issue id (#43). A weaker slug counts only when the stronger one names no free
    worklog.

    A name counts when it is ``<slug>.worklog.md`` or starts with ``<slug>-`` or
    ``<slug>.``: a substring match would let a short slug take another feature's
    worklog. Two streams can share a slug (``epic/x`` and a child whose worklog is
    ``x.worklog.md``), so a worklog another live stream names is left to it. A nested
    repo's stream names its worklog relative to that repo, so a claim also covers a
    path that ends in it. The other streams are read only once a candidate exists.
    """
    from fnmatch import fnmatch

    slugs = _stream_slugs(stream)
    if not slugs:
        return None
    home = homes.get("worklog", DEFAULT_ARTIFACT_HOMES["worklog"])
    # One list per slug: a file goes to the first slug that names it.
    found_by_slug: List[List[Tuple[str, float]]] = [[] for _ in slugs]
    for directory, pattern in _worklog_home_dirs(project_dir, home):
        try:
            entries = list(os.scandir(project_dir / directory))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            index = next(
                (i for i, slug in enumerate(slugs) if _slug_names_file(slug, name)), None
            )
            if index is None or not fnmatch(name, pattern):
                continue
            try:
                if not entry.is_file():
                    continue
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            found_by_slug[index].append(
                (f"{directory}/{name}" if directory else name, mtime)
            )
    if not any(found_by_slug):
        return None

    claimed: List[str] = []
    for other in list_streams(conn):
        if other == stream or not is_work_stream(other):
            continue
        events = read_events(conn, stream=other)
        if not events or fold_stream(events, now=now)["lifecycle"] != "live":
            continue
        claimed.extend(
            _normalized_ref(ref) for ref in _committed_refs(events)
            if classify_artifact(ref, homes) == "worklog"
        )
    for found in found_by_slug:
        free = [
            (path, mtime) for path, mtime in sorted(found)
            if not any(
                own and (_normalized_ref(path) == own
                         or _normalized_ref(path).endswith("/" + own))
                for own in claimed
            )
        ]
        if free:
            # `max` keeps the first of equal mtimes, and `free` is in path order.
            return max(free, key=lambda item: item[1])[0]
    return None
