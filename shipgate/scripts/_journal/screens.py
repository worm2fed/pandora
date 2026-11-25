"""The evidence store of UI tasks (ADR 0031): where the screenshots live, how a task's
files are registered and listed, and the capture commands the journal prints.

Layout: ``<root>/<12-hex project key>/<encoded stream>/T<n>-<w>[-<k>].png``, the root
under the Claude config directory. Every write works on directory file descriptors
opened under the resolved root, and reads each entry with ``lstat``: a symbolic link is
never followed. The journal never runs a command here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import (
    Callable, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple, TypedDict,
)
from urllib.parse import quote, unquote

from .vocab import (
    EVIDENCE_FILE_RE, EVIDENCE_KEEP_DAYS, EVIDENCE_PARTS, EVIDENCE_PROJECT_RE,
    EVIDENCE_TMP_RE, InfraError, SCREENS_WAIVED, TASK_ID_RE, UsageError,
)
from .plugin import _db_file, _ui
from .text import _one_line, _string_list, _waiver_reason
from .project import project_settings, require_setting
from .store import _parse_ts, Event, read_events
from .fold import fold_stream
from .artifacts import _resolve_artifact, ui_tasks


# --------------------------------------------------------------------------
# The root, the project key, the layout
# --------------------------------------------------------------------------

_SAFE = "-_."
# The one file Finder leaves in a directory the user opens (ADR 0031): part of the layout,
# so no stream directory may take its name.
FINDER_FILE = ".DS_Store"
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC
_TMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC
_NAME_MAX = 255
_SUFFIXES = 9


def evidence_root() -> Optional[str]:
    """``$CLAUDE_CONFIG_DIR/shipgate/evidence`` when the variable is set and not empty,
    else ``$HOME/.claude/shipgate/evidence``. None when neither variable is set, or when
    the chosen one is not an absolute path. Environment variables only (``Path.home``
    would fall back to the password database), and no file system call."""
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config:
        base = os.path.expanduser(config)
    else:
        home = os.environ.get("HOME", "")
        if not home:
            return None
        base = os.path.join(home, ".claude")
    if not os.path.isabs(base):
        return None
    return os.path.join(base, *EVIDENCE_PARTS)


def project_key(conn: sqlite3.Connection) -> Optional[str]:
    """The first 12 hex digits of the SHA-256 of the journal's file as SQLite names it.
    SQLite has already resolved that path, so a worktree whose ``.claude/shipgate.db``
    links to the main checkout's journal gets the main checkout's key, at no file system
    call. None for a database with no file."""
    db = _db_file(conn)
    if db is None:
        return None
    return hashlib.sha256(str(db).encode("utf-8", "surrogateescape")).hexdigest()[:12]


def stream_dir_name(stream: str) -> Optional[str]:
    """The stream's directory name: every byte but ASCII letters, digits, ``-``, ``_``,
    ``.`` (and ``~``, which ``quote`` keeps) percent-encoded, so no name holds a ``/``.
    None when the name would be ``""``, ``.``, ``..`` or ``FINDER_FILE``, or longer than a
    file name."""
    try:
        name = quote(stream, safe=_SAFE)
    except UnicodeEncodeError:
        return None
    if name in ("", ".", "..", FINDER_FILE) or len(name) > _NAME_MAX:
        return None
    return name


def valid_stream_dir(name: str) -> bool:
    """True when NAME is what ``stream_dir_name`` gives for some stream."""
    if name in ("", ".", "..", FINDER_FILE):
        return False
    try:
        return quote(unquote(name), safe=_SAFE) == name
    except UnicodeEncodeError:
        return False


def _as_line(text: str) -> str:
    """TEXT as it prints on one line: as it is, or its repr when it does not print."""
    return text if text.isprintable() else repr(text)


def _widths(widths: Sequence[int]) -> str:
    return ", ".join(str(w) for w in widths)


def _and(widths: Sequence[int]) -> str:
    words = [str(w) for w in widths]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _unique(widths: Sequence[int]) -> List[int]:
    return list(dict.fromkeys(widths))


# --------------------------------------------------------------------------
# The state of each UI task
# --------------------------------------------------------------------------

NOTE_NO_GLOBS = "ui.globs is empty"
NOTE_NO_DESIGN = "no design-committed names a worklog"


class ScreenTask(TypedDict):
    task_id: str
    present: List[int]  # set widths with a fresh file
    missing: List[int]  # set widths with none
    waived: Optional[str]  # the newest screens-waived reason naming the task
    files: List[str]  # the fresh files' absolute paths, in name order


class ScreenState(TypedDict):
    stream: str
    dir: Optional[str]  # the stream's evidence directory (it may not exist yet)
    widths: List[int]
    tasks: List[ScreenTask]  # the UI tasks, in plan order (first line of each id)
    note: Optional[str]  # why no task can be UI, or None


class _Plan(NamedTuple):
    ui: Dict[str, bool]  # per task id of the Build Plan, whether it is UI
    order: List[str]  # the UI task ids, in plan order
    since: Optional[float]  # a fresh file is newer; None: no design-committed
    note: Optional[str]


def _read_plan(events: Sequence[Event], project_dir: Path, globs: Sequence[str]) -> _Plan:
    """The UI tasks of the worklog the stream's newest ``design-committed`` names."""
    design = next((e for e in reversed(events) if e.type == "design-committed"
                   and isinstance(e.data.get("worklog"), str) and e.data["worklog"]), None)
    since: Optional[float] = None
    if design is not None:
        recorded = _parse_ts(design.ts)
        # A time no one can read: no file can be shown to be newer.
        since = recorded.timestamp() if recorded is not None else float("inf")
    if not globs:
        return _Plan({}, [], since, NOTE_NO_GLOBS)
    if design is None:
        return _Plan({}, [], None, NOTE_NO_DESIGN)
    path = _resolve_artifact(project_dir, design.data["worklog"])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):  # a NUL byte in the ref is a ValueError
        return _Plan({}, [], since, f"{_as_line(str(path))} cannot be read")
    ui = ui_tasks(text, globs)
    return _Plan(ui, [task for task, is_ui in ui.items() if is_ui], since, None)


def _stream_dir(conn: sqlite3.Connection, stream: str) -> Optional[str]:
    root, key, name = evidence_root(), project_key(conn), stream_dir_name(stream)
    if root is None or key is None or name is None:
        return None
    return os.path.join(os.path.realpath(root), key, name)


def _real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _fresh(directory: Optional[str], task_id: str, widths: Sequence[int],
           since: Optional[float]) -> Dict[int, List[str]]:
    """Per set width, the fresh files of TASK_ID in DIRECTORY, in name order: a regular
    file by ``lstat`` (a link never counts), named for the task and the width, newer
    than SINCE, whose PNG width is the set width at 1x, 2x or 3x."""
    found: Dict[int, List[str]] = {w: [] for w in widths}
    if (directory is None or not _real_dir(os.path.dirname(directory))
            or not _real_dir(directory)):
        return found
    try:
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries)
    except OSError:
        return found
    for name in names:
        match = EVIDENCE_FILE_RE.fullmatch(name)
        if match is None or match.group(1) != task_id:
            continue
        width = next((w for w in widths if match.group(2) == str(w)), None)
        if width is None:
            continue
        path = os.path.join(directory, name)
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or (since is not None
                                                and not st.st_mtime > since):
                continue
            if _ui.png_width(path) in (width, 2 * width, 3 * width):
                found[width].append(path)
        except (OSError, ValueError):
            continue
    return found


def _waived(events: Sequence[Event], task_id: str) -> Optional[str]:
    for event in reversed(events):
        if (event.type == "deviation" and event.data.get("kind") == SCREENS_WAIVED
                and task_id in _string_list(event.data.get("task_ids"))):
            reason = _waiver_reason(event.data)
            if reason is not None:
                return reason
    return None


def _task_state(events: Sequence[Event], task_id: str, widths: Sequence[int],
                directory: Optional[str], since: Optional[float]) -> ScreenTask:
    fresh = _fresh(directory, task_id, widths, since)
    return {
        "task_id": task_id,
        "present": [w for w in widths if fresh[w]],
        "missing": [w for w in widths if not fresh[w]],
        "waived": _waived(events, task_id),
        "files": sorted(path for w in widths for path in fresh[w]),
    }


def _screen_state(conn: sqlite3.Connection, stream: str, events: Sequence[Event],
                  project_dir: Path, globs: Sequence[str],
                  widths: Sequence[int]) -> ScreenState:
    widths = _unique(widths)
    plan = _read_plan(events, project_dir, globs)
    directory = _stream_dir(conn, stream)
    return {
        "stream": stream,
        "dir": directory,
        "widths": widths,
        "tasks": [_task_state(events, task, widths, directory, plan.since)
                  for task in plan.order],
        "note": plan.note,
    }


def screen_state(conn: sqlite3.Connection, stream: str, project_dir: Path) -> ScreenState:
    """Each UI task of the stream's worklog, in plan order: the set widths with a fresh
    file, the widths missing, and the waiver reason. The settings are read the hook-path
    way (a bad value gives the default). It creates and deletes nothing."""
    resolved = project_settings(project_dir)
    return _screen_state(conn, stream, read_events(conn, stream=stream), project_dir,
                         resolved.value("ui.globs"), resolved.value("ui.widths"))


def task_screen_state(conn: sqlite3.Connection, stream: str, task_id: str,
                      project_dir: Path, globs: Sequence[str],
                      widths: Sequence[int]) -> Optional[ScreenTask]:
    """One task's entry as ``screen_state`` lists it, or None when it is not UI here: no
    globs, no ``design-committed`` that names a worklog, a worklog that cannot be read,
    or no UI path on the task's line."""
    events = read_events(conn, stream=stream)
    plan = _read_plan(events, project_dir, globs)
    if not plan.ui.get(task_id):
        return None
    return _task_state(events, task_id, _unique(widths), _stream_dir(conn, stream),
                       plan.since)


def render_screen_state(state: ScreenState) -> List[str]:
    """``screens --list`` as text: the directory, then one line per UI task."""
    shown = _as_line(state["dir"]) if state["dir"] else "none (no evidence root)"
    lines = [f"evidence: {shown}"]
    if not state["tasks"]:
        note = state["note"] or "no Build Plan line names a path that matches ui.globs"
        return lines + [f"no UI task: {_one_line(note)}"]
    for task in state["tasks"]:
        if not task["missing"]:
            summary = _widths(task["present"])
        elif task["waived"] is not None:
            summary = "waived: " + _one_line(task["waived"])
        else:
            has = f" (has {_widths(task['present'])})" if task["present"] else ""
            summary = f"missing {_widths(task['missing'])}{has}"
        lines.append(f"{task['task_id']} — {summary}")
    return lines


# --------------------------------------------------------------------------
# The command: the checks of every form
# --------------------------------------------------------------------------


def _strict_settings(project_dir: Path) -> Tuple[List[str], List[int], Optional[str]]:
    """``ui.globs``, ``ui.widths`` and ``ui.capture``; a bad value exits 2."""
    resolved = project_settings(project_dir)
    return (list(require_setting(resolved, "ui.globs")),
            _unique(require_setting(resolved, "ui.widths")),
            require_setting(resolved, "ui.capture"))


def _stream_events(conn: sqlite3.Connection, stream: str, live: bool) -> List[Event]:
    events = read_events(conn, stream=stream)
    if not events:
        raise UsageError(f"screens: stream {stream!r} has no events")
    if live and fold_stream(events)["terminal"]:
        raise UsageError(f"screens: stream {stream!r} is finished")
    return events


def _check_task_id(task_id: str) -> None:
    if TASK_ID_RE.fullmatch(task_id) is None:
        raise UsageError(
            f"screens: the task id {task_id!r} is not T and digits, as in T003")


def _checked_name(stream: str) -> str:
    name = stream_dir_name(stream)
    if name is None:
        raise UsageError(
            f"screens: the stream name {stream!r} cannot name an evidence directory")
    return name


def _checked_root(conn: sqlite3.Connection) -> Tuple[str, str]:
    root = evidence_root()
    if root is None:
        raise UsageError("screens: no evidence root: set CLAUDE_CONFIG_DIR or HOME")
    key = project_key(conn)
    if key is None:
        raise UsageError("screens: the journal has no file, so it names no evidence "
                         "directory")
    return root, key


def _check_file(path: str, widths: Sequence[int],
                width: Optional[int]) -> Tuple[str, int, int]:
    """The source file, the set width it is stored under, and its pixel width."""
    shown = _as_line(path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise UsageError(f"screens: no file at {shown}") from None
    except OSError as error:
        raise UsageError(f"screens: cannot read {shown}: {error.strerror or error}") \
            from None
    if not stat.S_ISREG(st.st_mode):
        raise UsageError(f"screens: {shown} is not a regular file")
    try:
        px = _ui.png_width(path)
    except ValueError as error:
        raise UsageError(f"screens: {shown}: {error}") from None
    except OSError as error:
        raise UsageError(f"screens: cannot read {shown}: {error.strerror or error}") \
            from None
    matches = _ui.match_width(px, widths)
    if not matches:
        raise UsageError(f"screens: {shown} is {px} px wide, which is no set width "
                         f"({_widths(widths)}) at 1x, 2x or 3x")
    if width is not None:
        if width not in matches:
            raise UsageError(f"screens: {shown} is {px} px wide, which matches "
                             f"{_and(matches)}, not --width {width}")
        return path, width, px
    if len(matches) > 1:
        raise UsageError(f"screens: {shown} is {px} px wide, which matches "
                         f"{_and(matches)}; name one with --width")
    return path, matches[0], px


# --------------------------------------------------------------------------
# The command: the writes
# --------------------------------------------------------------------------


def _child_dir(parent_fd: int, name: str, path: str) -> int:
    """An fd for the directory NAME under PARENT_FD, made when it is missing; a link or
    a file in its place is refused."""
    try:
        st = os.lstat(name, dir_fd=parent_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    else:
        if stat.S_ISLNK(st.st_mode):
            raise InfraError(f"screens: refused {_as_line(path)}: a symbolic link; "
                             "nothing was written")
        if not stat.S_ISDIR(st.st_mode):
            raise InfraError(f"screens: refused {_as_line(path)}: not a directory; "
                             "nothing was written")
    return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)


def _open_stream_dir(root: str, key: str, name: str) -> Tuple[str, int]:
    """The stream's directory under the resolved root, and an fd for it."""
    os.makedirs(root, mode=0o700, exist_ok=True)
    real_root = os.path.realpath(root)
    root_fd = os.open(real_root, _DIR_FLAGS)
    try:
        key_fd = _child_dir(root_fd, key, os.path.join(real_root, key))
        try:
            stream_fd = _child_dir(key_fd, name, os.path.join(real_root, key, name))
        finally:
            os.close(key_fd)
    finally:
        os.close(root_fd)
    return os.path.join(real_root, key, name), stream_fd


def _next_free(stream_fd: int, task_id: str, width: int) -> Optional[str]:
    for k in range(1, _SUFFIXES + 1):
        name = f"{task_id}-{width}.png" if k == 1 else f"{task_id}-{width}-{k}.png"
        try:
            os.lstat(name, dir_fd=stream_fd)
        except FileNotFoundError:
            return name
    return None


def _full(task_id: str, width: int, stored: int) -> UsageError:
    tail = ""
    if stored:
        tail = (f"; the {stored} files stored above stay" if stored > 1
                else "; the 1 file stored above stays")
    return UsageError(f"screens: {task_id} has {_SUFFIXES} files at {width} already; "
                      f"no more fit{tail}")


def _copy(source: str, stream_fd: int, final: str) -> None:
    """Copy SOURCE to FINAL in the stream directory through a temporary file and a
    rename; the copy keeps its own mtime, the time of the copy."""
    tmp = f".{final}.{os.getpid()}.tmp"
    fd = os.open(tmp, _TMP_FLAGS, 0o600, dir_fd=stream_fd)
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, final, src_dir_fd=stream_fd, dst_dir_fd=stream_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=stream_fd)
        except OSError:
            pass
        raise


def register_files(conn: sqlite3.Connection, project_dir: Path, stream: str,
                   task_id: str, files: Sequence[str], width: Optional[int]) -> None:
    """``screens --file``: check every file, then store each one under its set width."""
    globs, widths, _ = _strict_settings(project_dir)
    events = _stream_events(conn, stream, live=True)
    _check_task_id(task_id)
    name = _checked_name(stream)
    root, key = _checked_root(conn)
    checked = [_check_file(path, widths, width) for path in files]
    _prune_before_writing(conn, root, key)
    directory, stream_fd = _open_stream_dir(root, key, name)
    stored = 0
    try:
        for source, set_width, px in checked:
            final = _next_free(stream_fd, task_id, set_width)
            if final is None:
                raise _full(task_id, set_width, stored)
            _copy(source, stream_fd, final)
            stored += 1
            print(f"stored {_as_line(os.path.join(directory, final))} — {set_width} "
                  f"({px} px)", flush=True)
    finally:
        os.close(stream_fd)
    plan = _read_plan(events, project_dir, globs)
    fresh = _fresh(directory, task_id, widths, plan.since)
    missing = [w for w in widths if not fresh[w]]
    print(f"{task_id} still misses: {_widths(missing)}" if missing
          else f"{task_id} has every width: {_widths(widths)}")
    if plan.note is not None:
        print(f"note: no task is UI here ({_one_line(plan.note)})")
    elif not plan.ui.get(task_id):
        print(f"note: {task_id} is not a UI task here (no path on its Build Plan line "
              "matches ui.globs), so task-done does not ask for these files")


_PLACEHOLDER_RE = re.compile(r"\{(url|width|out)\}")


def capture_command(template: str, url: str, width: int, out: str) -> str:
    """TEMPLATE with ``{url}``, ``{width}`` and ``{out}`` filled in one pass, the URL and
    the path quoted for a shell. Other braces stay as written, and a placeholder inside
    the URL is never filled."""
    values = {"url": shlex.quote(url), "width": str(width), "out": shlex.quote(out)}
    return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)


def print_capture_commands(conn: sqlite3.Connection, project_dir: Path, stream: str,
                           task_id: str, url: str) -> None:
    """``screens --url``: one ``ui.capture`` command per set width, the out path the
    next free name. It runs none of them."""
    _, widths, template = _strict_settings(project_dir)
    _stream_events(conn, stream, live=True)
    _check_task_id(task_id)
    name = _checked_name(stream)
    root, key = _checked_root(conn)
    if template is None:
        raise UsageError("screens: --url needs the ui.capture setting (a command with "
                         "{url}, {width} and {out})")
    if not url or not url.isprintable():
        raise UsageError("screens: --url needs a URL that prints on one line")
    _prune_before_writing(conn, root, key)
    directory, stream_fd = _open_stream_dir(root, key, name)
    lines = []
    try:
        for width in widths:
            final = _next_free(stream_fd, task_id, width)
            if final is None:
                raise _full(task_id, width, 0)
            line = capture_command(template, url, width, os.path.join(directory, final))
            if not line.isprintable():
                raise UsageError(f"screens: the capture command for {width} does not "
                                 "print on one line")
            lines.append(line)
    finally:
        os.close(stream_fd)
    for line in lines:
        print(line)
    print("run each command yourself; journal.py runs none. Then read the files and "
          "compare them with the PRD's reference.")


def list_screens(conn: sqlite3.Connection, project_dir: Path, stream: str,
                 as_json: bool) -> None:
    """``screens --list``: ``screen_state`` as text or JSON. Read-only."""
    globs, widths, _ = _strict_settings(project_dir)
    events = _stream_events(conn, stream, live=False)
    _checked_name(stream)
    state = _screen_state(conn, stream, events, project_dir, globs, widths)
    print(json.dumps(state, sort_keys=True) if as_json
          else "\n".join(render_screen_state(state)))


def prune_command(conn: sqlite3.Connection) -> None:
    """``screens --prune``: moments 2 and 3, what was removed or refused on stdout and
    each warning on stderr."""
    root = evidence_root()
    if root is None:
        print("evidence: no evidence root (no CLAUDE_CONFIG_DIR, no HOME)")
        return
    report = prune_evidence(root, project_key(conn), conn)
    lines, warnings = _removal_lines(report), _warning_lines(report)
    if lines or not warnings:
        print("\n".join(lines) if lines
              else f"evidence: nothing to prune in {_as_line(os.path.realpath(root))}")
    for warning in warnings:
        print(warning, file=sys.stderr)


def _prune_before_writing(conn: sqlite3.Connection, root: str, key: str) -> None:
    report = prune_evidence(root, key, conn, report_age_refusals=False)
    for line in render_prune(report):
        print(line, file=sys.stderr)


# --------------------------------------------------------------------------
# The layout: one classification for the prune and the survey
# --------------------------------------------------------------------------

REFUSED_LINK = "a symbolic link"
REFUSED_LAYOUT = "not in the evidence layout"

# Where an entry sits: the root holds project directories, a project directory holds
# stream directories, a stream directory holds screenshot files.
IN_ROOT, IN_PROJECT, IN_STREAM = "root", "project", "stream"


def finder_file(level: str, name: str, mode: int) -> bool:
    """True for the one layout entry that is no evidence: a regular file named exactly
    ``.DS_Store`` (the macOS Finder writes one into each directory it shows) in a
    project or a stream directory. It never counts as a screenshot, and the prune
    removes it only with its directory. One in the root stays refused: the root is
    never removed, so it blocks no cleanup there."""
    return (level in (IN_PROJECT, IN_STREAM) and name == FINDER_FILE
            and stat.S_ISREG(mode))


def layout_refusal(level: str, name: str, mode: int) -> Optional[str]:
    """None when the entry NAME, of ``lstat`` mode MODE, in a directory of LEVEL is the
    layout's: a 12-hex project directory in the root, a stream directory whose name
    round-trips the encoding in a project directory, a regular ``T<n>-<w>[-<k>].png``
    file or its ``.tmp`` form in a stream directory, or a ``finder_file`` in either.
    Else why the prune refuses it: ``REFUSED_LINK`` for a symbolic link at any level,
    ``REFUSED_LAYOUT`` for the rest."""
    if stat.S_ISLNK(mode):
        return REFUSED_LINK
    if finder_file(level, name, mode):
        return None
    if level == IN_ROOT:
        fits = stat.S_ISDIR(mode) and EVIDENCE_PROJECT_RE.fullmatch(name) is not None
    elif level == IN_PROJECT:
        fits = stat.S_ISDIR(mode) and valid_stream_dir(name)
    elif level == IN_STREAM:
        fits = stat.S_ISREG(mode) and (EVIDENCE_FILE_RE.fullmatch(name) is not None
                                       or EVIDENCE_TMP_RE.fullmatch(name) is not None)
    else:
        raise ValueError(f"no layout level {level!r}")
    return None if fits else REFUSED_LAYOUT


def _stream_ended(conn: sqlite3.Connection, name: str) -> bool:
    """True for a stream directory whose stream has no events or is finished; a name
    outside the encoding is True too, so the prune selects and refuses it."""
    if not valid_stream_dir(name):
        return True
    events = read_events(conn, stream=unquote(name))
    return not events or fold_stream(events)["terminal"]


def _keep_cutoff(now: Optional[float]) -> float:
    """The mtime under which a layout file is older than ``EVIDENCE_KEEP_DAYS``."""
    return (time.time() if now is None else now) - EVIDENCE_KEEP_DAYS * 86400


# --------------------------------------------------------------------------
# The prune (ADR 0031, the six delete rules)
# --------------------------------------------------------------------------


class PruneReport(TypedDict):
    removed_dirs: List[Tuple[str, int]]  # a removed directory and how many files it held
    removed_files: List[str]  # old files removed outside a removed directory
    refused: List[Tuple[str, str]]  # a path kept, and why
    warnings: List[str]  # an OSError per entry, as text


class _Pruner:
    """One prune under one resolved root. Every directory is opened with
    ``O_DIRECTORY | O_NOFOLLOW`` and a ``dir_fd``, every entry is classified with
    ``lstat`` before anything else, and only the layout is removed: one file at a time,
    then a directory once it is empty."""

    def __init__(self, conn: sqlite3.Connection, real_root: str,
                 cutoff: float) -> None:
        self.conn = conn
        self.real_root = real_root
        self.cutoff = cutoff
        self.report: PruneReport = {"removed_dirs": [], "removed_files": [],
                                    "refused": [], "warnings": []}
        self._refused_paths: Set[str] = set()
        # False keeps a refused entry without recording it (the automatic age pass).
        self.reporting = True

    def refuse(self, path: str, reason: str) -> None:
        if self.reporting and path not in self._refused_paths:
            self._refused_paths.add(path)
            self.report["refused"].append((path, reason))

    def warn(self, what: str, path: str, error: OSError) -> None:
        self.report["warnings"].append(f"{what} {path}: {error.strerror or error}")

    def classify(self, parent_fd: int, level: str, name: str,
                 path: str) -> Tuple[str, Optional[os.stat_result]]:
        """What NAME under PARENT_FD, a directory of LEVEL, is by ``lstat``,
        ``layout_refusal`` and ``finder_file``: ``layout``, ``finder``, ``refused``
        (recorded here), ``gone`` or ``error`` (warned)."""
        try:
            st = os.lstat(name, dir_fd=parent_fd)
        except FileNotFoundError:
            return "gone", None
        except OSError as error:
            self.warn("cannot read", path, error)
            return "error", None
        reason = layout_refusal(level, name, st.st_mode)
        if reason is not None:
            self.refuse(path, reason)
            return "refused", st
        if finder_file(level, name, st.st_mode):
            return "finder", st
        return "layout", st

    def open_dir(self, parent_fd: int, name: str, path: str) -> Optional[int]:
        try:
            return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except OSError as error:
            self.warn("cannot open", path, error)
            return None

    def names(self, fd: int, path: str) -> Optional[List[str]]:
        try:
            with os.scandir(fd) as entries:
                return sorted(entry.name for entry in entries)
        except OSError as error:
            self.warn("cannot list", path, error)
            return None

    def remove_dir(self, parent_fd: int, name: str, path: str, count: int) -> bool:
        try:
            os.rmdir(name, dir_fd=parent_fd)
        except OSError as error:
            self.warn("cannot remove", path, error)
            return False
        self.report["removed_dirs"].append((path, count))
        return True

    def unlink(self, fd: int, name: str, path: str) -> bool:
        try:
            os.unlink(name, dir_fd=fd)
        except OSError as error:
            self.warn("cannot remove", path, error)
            return False
        return True

    def clear_finder(self, fd: int, level: str, path: str) -> bool:
        """For a directory this prune is about to remove: when nothing is left in it but
        a ``finder_file``, unlink that after its ``lstat``. True when it is then empty.
        Any other entry keeps it, unrecorded: the prune did not target that entry."""
        names = self.names(fd, path)
        if names is None or any(name != FINDER_FILE for name in names):
            return False
        for name in names:
            child = os.path.join(path, name)
            try:
                st = os.lstat(name, dir_fd=fd)
            except FileNotFoundError:
                continue
            except OSError as error:
                self.warn("cannot read", child, error)
                return False
            if not finder_file(level, name, st.st_mode):
                return False
            if not self.unlink(fd, name, child):
                return False
        return True

    def clear_stream_dir(self, fd: int, path: str, old_only: bool) -> Tuple[int, bool]:
        """Remove the layout files of one stream directory. With OLD_ONLY, each one
        older than the cutoff. Without it, every one, but only when every entry is the
        layout's: one refused or unreadable entry keeps the whole directory. A Finder
        file goes last, uncounted, once the rest went (with OLD_ONLY, only when this
        prune removed a file here). The count removed, and whether the directory is
        now empty and may go."""
        names = self.names(fd, path)
        if names is None:
            return 0, False
        chosen: List[Tuple[str, str]] = []
        kept = False
        for name in names:
            child = os.path.join(path, name)
            kind, st = self.classify(fd, IN_STREAM, name, child)
            if kind in ("gone", "finder"):
                continue
            if kind != "layout" or st is None:
                kept = True
                continue
            if old_only and not st.st_mtime < self.cutoff:
                kept = True
                continue
            chosen.append((name, child))
        if kept and not old_only:
            return 0, False
        removed = [child for name, child in chosen if self.unlink(fd, name, child)]
        if old_only:
            self.report["removed_files"].extend(removed)
        if kept or len(removed) < len(chosen) or (old_only and not removed):
            return len(removed), False
        return len(removed), self.clear_finder(fd, IN_STREAM, path)

    def stream_dir(self, key_fd: int, name: str, path: str, old_only: bool) -> bool:
        """Prune one stream directory; True when it was removed. With OLD_ONLY it goes
        only when this prune removed a file from it and left it empty."""
        kind, _ = self.classify(key_fd, IN_PROJECT, name, path)
        if kind != "layout":
            return False
        fd = self.open_dir(key_fd, name, path)
        if fd is None:
            return False
        try:
            count, empty = self.clear_stream_dir(fd, path, old_only)
        finally:
            os.close(fd)
        if not empty or (old_only and count == 0):
            return False
        if not self.remove_dir(key_fd, name, path, count):
            return False
        if old_only:
            inside = path + os.sep
            self.report["removed_files"] = [
                f for f in self.report["removed_files"] if not f.startswith(inside)]
        return True

    def project_dir(self, root_fd: int, key: str, select: Callable[[str], bool],
                    old_only: bool) -> None:
        """Prune the stream directories SELECT names in one project directory, then
        the project directory when this prune removed one and left nothing in it but a
        Finder file, which goes first."""
        path = os.path.join(self.real_root, key)
        kind, _ = self.classify(root_fd, IN_ROOT, key, path)
        if kind != "layout":
            return
        fd = self.open_dir(root_fd, key, path)
        if fd is None:
            return
        removed_any = False
        empty = False
        try:
            for name in self.names(fd, path) or []:
                if select(name):
                    child = os.path.join(path, name)
                    removed_any = self.stream_dir(fd, name, child, old_only) or removed_any
            if removed_any:
                empty = self.clear_finder(fd, IN_PROJECT, path)
        finally:
            os.close(fd)
        if empty:
            self.remove_dir(root_fd, key, path, 0)

    def ended(self, name: str) -> bool:
        return _stream_ended(self.conn, name)


def prune_evidence(root: str, key: Optional[str], conn: sqlite3.Connection,
                   stream: Optional[str] = None, now: Optional[float] = None,
                   report_age_refusals: bool = True) -> PruneReport:
    """Remove what the evidence store no longer needs. It never raises.

    With STREAM, moment 1: that stream's directory in this project (KEY), whatever the
    stream's state. Without it, moment 2: this project's directories whose stream has no
    events or is finished; with no KEY either, no moment 2. Moments 1 and 2 remove a
    stream directory whole or not at all: one refused or unreadable entry in it keeps
    every file. Then, in every case, moment 3: every layout file in the whole root older
    than ``EVIDENCE_KEEP_DAYS``, and a directory this left empty. There is no timer: the
    limit applies when a stream starts or ends and when screens are registered.
    REPORT_AGE_REFUSALS False keeps out of the report what only moment 3 refuses (the
    automatic runs); what it refuses stays all the same.

    The delete rules (ADR 0031): (1) the root is resolved once and every call works on
    directory fds opened under it; (2) every entry is read with ``lstat`` first, and a
    link is refused, never followed and never removed; (3) only the layout is removed —
    a 12-hex project directory, a stream directory whose name round-trips the encoding,
    a regular ``T<n>-<w>[-<k>].png`` file or its ``.tmp`` form, and a regular
    ``.DS_Store`` in a project or a stream directory, which goes only with that
    directory — and any other entry is refused and kept with every directory above it;
    (4) files go one by one with ``unlink``, then a directory only once it is empty with
    ``rmdir``, never the root; (5) the report holds each removed directory with its count
    of evidence files, each old file removed outside a removed directory, and each
    refused entry; (6) an OSError is a warning for its entry and the prune goes on, and
    any other exception ends it as one warning.
    """
    pruner = _Pruner(conn, os.path.realpath(root) if root else "", _keep_cutoff(now))
    try:
        _prune(pruner, key, stream, report_age_refusals)
    except Exception as error:  # noqa: BLE001 — rule 6: the prune never raises
        pruner.report["warnings"].append(f"the prune stopped: {error}")
    return pruner.report


def _prune(pruner: _Pruner, key: Optional[str], stream: Optional[str],
           report_age_refusals: bool) -> None:
    if not pruner.real_root:
        return
    try:
        root_fd = os.open(pruner.real_root, _DIR_FLAGS)
    except FileNotFoundError:
        return
    except OSError as error:
        pruner.warn("cannot open", pruner.real_root, error)
        return
    try:
        if stream is not None:
            name = stream_dir_name(stream)
            if key is not None and name is not None:
                pruner.project_dir(root_fd, key, lambda n: n == name, old_only=False)
        elif key is not None:
            pruner.project_dir(root_fd, key, pruner.ended, old_only=False)
        pruner.reporting = report_age_refusals
        for project in pruner.names(root_fd, pruner.real_root) or []:
            pruner.project_dir(root_fd, project, lambda n: True, old_only=True)
    finally:
        os.close(root_fd)


def render_prune(report: PruneReport) -> List[str]:
    """The prune's lines: each removed directory with its count, each old file removed
    outside a removed directory, each refused entry, each warning."""
    return _removal_lines(report) + _warning_lines(report)


def _removal_lines(report: PruneReport) -> List[str]:
    lines = []
    for path, count in report["removed_dirs"]:
        files = "1 file" if count == 1 else f"{count} files"
        lines.append(f"evidence: removed {_as_line(path)} ({files})")
    for path in report["removed_files"]:
        lines.append(f"evidence: removed {_as_line(path)} (older than "
                     f"{EVIDENCE_KEEP_DAYS} days)")
    for path, reason in report["refused"]:
        lines.append(f"evidence: refused {_as_line(path)} ({reason})")
    return lines


def _warning_lines(report: PruneReport) -> List[str]:
    return [f"warning: evidence: {_one_line(warning)}" for warning in report["warnings"]]


def prune_ended_stream(conn: sqlite3.Connection, stream: str) -> None:
    """Moment 1, right after a terminal event committed: remove the stream's evidence
    directory, apply the 30-day limit to the whole root (there is no timer, so a stream
    that ends in any project sweeps it), and print the prune on stderr: what it removed
    and what it refused in the stream's directory, not what the age pass refused
    elsewhere. With no evidence root on disk it costs one ``lstat``. It never raises, so
    it never changes the exit code and never undoes the event."""
    try:
        root, key = evidence_root(), project_key(conn)
        if root is None or key is None:
            return
        try:
            os.lstat(root)
        except OSError:
            return
        report = prune_evidence(root, key, conn, stream=stream, report_age_refusals=False)
        for line in render_prune(report):
            print(line, file=sys.stderr)
    except Exception as error:  # noqa: BLE001 — the event has landed
        try:
            print(f"warning: the event landed, but its evidence directory was not "
                  f"pruned ({error})", file=sys.stderr)
        except Exception:  # noqa: BLE001 — stderr itself failed; the event has landed
            pass


def prune_old_evidence(conn: sqlite3.Connection) -> None:
    """Moment 3 alone, right after a ``flow-started`` committed: the 30-day limit over
    the whole root (there is no timer, so a stream that starts in any project sweeps it
    too), printed on stderr like the terminal prune, without what it refused. It removes
    no stream directory whole: that is moments 1 and 2. With no evidence root on disk it
    costs one ``lstat``. It never raises, so it never changes the exit code and never
    undoes the event."""
    try:
        root = evidence_root()
        if root is None:
            return
        try:
            os.lstat(root)
        except OSError:
            return
        report = prune_evidence(root, None, conn, report_age_refusals=False)
        for line in render_prune(report):
            print(line, file=sys.stderr)
    except Exception as error:  # noqa: BLE001 — the event has landed
        try:
            print(f"warning: the event landed, but the evidence root was not pruned "
                  f"({error})", file=sys.stderr)
        except Exception:  # noqa: BLE001 — stderr itself failed; the event has landed
            pass


# --------------------------------------------------------------------------
# The survey: what `doctor` reports, read-only
# --------------------------------------------------------------------------


class EvidenceProject(TypedDict):
    key: str
    streams: int  # its stream directories
    files: int  # the layout files in them
    bytes: int
    oldest_days: Optional[int]  # the oldest layout file's age in whole days; None: none


class EvidenceWhole(TypedDict):
    projects: int
    files: int
    bytes: int
    oldest_days: Optional[int]


class EvidencePrune(TypedDict):
    directories: int  # this project's stream directories moment 2 would remove
    files: int  # the layout files over EVIDENCE_KEEP_DAYS moment 3 would remove


class EvidenceRefused(TypedDict):
    count: int
    first: Optional[str]  # the first refused path in sorted order


class EvidenceSurvey(TypedDict):
    """``survey_evidence``. The parts are None when the root is not a directory, and
    ``project`` is None too when the journal names no project key."""

    root: Optional[str]  # the resolved root; None when there is no root
    exists: bool
    project: Optional[EvidenceProject]
    whole: Optional[EvidenceWhole]
    next_prune: Optional[EvidencePrune]
    refused: Optional[EvidenceRefused]


class _Tally:
    """The count, the bytes and the oldest mtime of some layout files."""

    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0
        self.oldest: Optional[float] = None

    def add(self, st: os.stat_result) -> None:
        self.files += 1
        self.bytes += st.st_size
        if self.oldest is None or st.st_mtime < self.oldest:
            self.oldest = st.st_mtime

    def days(self, clock: float) -> Optional[int]:
        if self.oldest is None:
            return None
        return max(0, int((clock - self.oldest) // 86400))


class _Surveyor:
    """One read-only walk under one resolved root, the way the prune walks it: each
    directory opened with ``O_DIRECTORY | O_NOFOLLOW`` under its parent's fd, each entry
    read with ``lstat`` and classified with ``layout_refusal`` before anything else, and
    no refused entry entered."""

    def __init__(self, conn: sqlite3.Connection, real_root: str, key: Optional[str],
                 cutoff: float) -> None:
        self.conn = conn
        self.real_root = real_root
        self.key = key
        self.cutoff = cutoff
        self.whole = _Tally()
        self.this = _Tally()
        self.projects = 0
        self.streams = 0
        self.prune_dirs = 0
        self.prune_files = 0
        self.refused: List[str] = []

    def layout(self, fd: int, level: str,
               path: str) -> Tuple[List[Tuple[str, os.stat_result]], bool]:
        """The layout entries of the directory FD (of LEVEL, at PATH) in name order,
        each with its ``lstat``, and whether the prune keeps the directory: it holds a
        refused entry (recorded here) or one that cannot be read, or it cannot be
        listed. A Finder file is left out: it is no stream, no file and no refusal."""
        try:
            with os.scandir(fd) as found:
                names = sorted(entry.name for entry in found)
        except OSError:
            return [], True
        entries: List[Tuple[str, os.stat_result]] = []
        kept = False
        for name in names:
            try:
                st = os.lstat(name, dir_fd=fd)
            except FileNotFoundError:
                continue
            except OSError:
                kept = True
                continue
            if layout_refusal(level, name, st.st_mode) is not None:
                self.refused.append(os.path.join(path, name))
                kept = True
                continue
            if finder_file(level, name, st.st_mode):
                continue
            entries.append((name, st))
        return entries, kept

    def root(self, root_fd: int) -> None:
        for key, _ in self.layout(root_fd, IN_ROOT, self.real_root)[0]:
            self.projects += 1
            fd = _open_child(root_fd, key)
            if fd is None:
                continue
            try:
                self.project(fd, key)
            finally:
                os.close(fd)

    def project(self, key_fd: int, key: str) -> None:
        """One project directory. Moment 2 runs on this project's only: a stream
        directory whose stream ended goes with every layout file when nothing else is in
        it. Moment 3 removes the old files of every stream directory moment 2 keeps."""
        path = os.path.join(self.real_root, key)
        here = key == self.key
        for name, _ in self.layout(key_fd, IN_PROJECT, path)[0]:
            if here:
                self.streams += 1
            ended = here and _stream_ended(self.conn, name)
            fd = _open_child(key_fd, name)
            if fd is None:
                continue
            try:
                files, kept = self.layout(fd, IN_STREAM, os.path.join(path, name))
            finally:
                os.close(fd)
            removed_whole = ended and not kept
            for _, st in files:
                self.whole.add(st)
                if here:
                    self.this.add(st)
                if not removed_whole and st.st_mtime < self.cutoff:
                    self.prune_files += 1
            if removed_whole:
                self.prune_dirs += 1


def _open_child(parent_fd: Optional[int], name: str) -> Optional[int]:
    """An fd for the directory NAME under PARENT_FD (NAME itself when None), or None."""
    try:
        return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError:
        return None


def survey_evidence(root: str, key: Optional[str], conn: sqlite3.Connection,
                    now: Optional[float] = None) -> EvidenceSurvey:
    """What the evidence root holds, for this project (KEY) and in all, and what the
    next prune (moments 2 and 3) would remove and refuse there. It walks with the
    prune's classification (``layout_refusal``, ``_stream_ended``, ``_keep_cutoff``)
    and only reads: it opens directories to list them, and removes, makes, renames and
    touches nothing. An entry it cannot read is left out of the counts."""
    real_root = os.path.realpath(root)
    survey: EvidenceSurvey = {
        "root": real_root, "exists": False, "project": None, "whole": None,
        "next_prune": None, "refused": None,
    }
    if not _real_dir(real_root):
        return survey
    clock = time.time() if now is None else now
    walk = _Surveyor(conn, real_root, key, _keep_cutoff(clock))
    root_fd = _open_child(None, real_root)
    if root_fd is not None:
        try:
            walk.root(root_fd)
        finally:
            os.close(root_fd)
    survey["exists"] = True
    if key is not None:
        survey["project"] = {"key": key, "streams": walk.streams,
                             "files": walk.this.files, "bytes": walk.this.bytes,
                             "oldest_days": walk.this.days(clock)}
    survey["whole"] = {"projects": walk.projects, "files": walk.whole.files,
                       "bytes": walk.whole.bytes, "oldest_days": walk.whole.days(clock)}
    survey["next_prune"] = {"directories": walk.prune_dirs, "files": walk.prune_files}
    survey["refused"] = {"count": len(walk.refused),
                         "first": min(walk.refused) if walk.refused else None}
    return survey
