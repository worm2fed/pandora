"""The run log of the Bash hooks (ADR 0032), as the journal reads it at a ``verify-run``
append (ADR 0033), prunes it after a ``flow-started`` or a terminal append, and surveys it
for ``doctor``.

Layout: one flat directory, ``runs_root()`` of ``hooks/_common.py``, that holds
``<session>.jsonl`` and at most one older ``<session>.jsonl.1`` per session. The hooks
append the rows; the journal only reads and deletes. The directory is opened with
``O_DIRECTORY | O_NOFOLLOW`` and each entry is reached under its fd without following a
link, so a link in place of the directory or of a file is never followed.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, TypedDict

from .vocab import RUNS_KEEP_DAYS, RUNS_READ_BYTES
from .plugin import _hooks_common
from .text import _one_line
from .settings import _part


_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC
# Non-blocking: a FIFO in place of a log must not hang the append.
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | _CLOEXEC | os.O_NONBLOCK
LOG_SUFFIX = ".jsonl"
OLDER_SUFFIX = ".jsonl.1"
_START_KEYS = frozenset(("i", "h"))
_END_KEYS = frozenset(("i", "x"))

MATCHED = "matched"
UNMATCHED = "unmatched"
CONTRADICTED = "contradicted"
# Why no command can match (ADR 0033, amended by #81): the shell has no plain-token
# session id, or the session has no log under the runs root.
NO_SESSION = "no-session"
NO_LOG = "no-log"


def _plain_session(session: Any) -> bool:
    """True when SESSION may name a file: a plain token (``SESSION_ID_PATTERN``)."""
    return (isinstance(session, str)
            and _hooks_common.SESSION_ID_RE.match(session) is not None)


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------


class SessionRuns(NamedTuple):
    """The rows of one session's log: each start row's hash by its ``tool_use_id``,
    and the end rows as ``(tool_use_id, exit)`` in file order, the older file first."""

    starts: Dict[str, str]
    ends: List[Tuple[str, int]]


def read_session_runs(session: Any) -> Optional[SessionRuns]:
    """The run log of SESSION, or None when there is none to read: no plain-token
    session id, no root, no ``runs`` directory (a link in its place included), or no
    regular file of the session in it. It reads ``<session>.jsonl.1``, then
    ``<session>.jsonl``, at most ``RUNS_READ_BYTES`` of the two together, and skips a
    line that is no row. It never raises."""
    try:
        return _read_session_runs(session)
    except Exception:  # noqa: BLE001 — a log that cannot be read is no log
        return None


def _read_session_runs(session: Any) -> Optional[SessionRuns]:
    if not _plain_session(session):
        return None
    root = _hooks_common.runs_root()
    if root is None:
        return None
    try:
        dir_fd = os.open(root, _DIR_FLAGS)
    except OSError:
        return None
    chunks: List[bytes] = []
    try:
        budget = RUNS_READ_BYTES
        for name in (session + OLDER_SUFFIX, session + LOG_SUFFIX):
            data = _read_log_file(dir_fd, name, budget)
            if data is not None:
                chunks.append(data)
                budget -= len(data)
    finally:
        os.close(dir_fd)
    if not chunks:
        return None
    runs = SessionRuns({}, [])
    for data in chunks:
        for line in data.split(b"\n"):
            _add_row(runs, line)
    return runs


def _read_log_file(dir_fd: int, name: str, budget: int) -> Optional[bytes]:
    """The first BUDGET bytes of the regular file NAME under DIR_FD, or None."""
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        parts: List[bytes] = []
        while budget > 0:
            part = os.read(fd, min(budget, 64 * 1024))
            if not part:
                break
            parts.append(part)
            budget -= len(part)
        return b"".join(parts)
    except OSError:
        return None
    finally:
        os.close(fd)


def _add_row(runs: SessionRuns, line: bytes) -> None:
    """Add LINE to RUNS when it is one of ADR 0032's two row forms, exactly:
    ``{"i": <id>, "h": <hash>}`` or ``{"i": <id>, "x": <int exit>}``."""
    try:
        row = json.loads(line)
    except Exception:  # noqa: BLE001 — ValueError, and RecursionError on deep nesting
        return
    if not isinstance(row, dict):
        return
    tool_use = row.get("i")
    if not isinstance(tool_use, str) or not tool_use:
        return
    keys = row.keys()
    if keys == _START_KEYS and isinstance(row["h"], str):
        runs.starts[tool_use] = row["h"]
    elif (keys == _END_KEYS and isinstance(row["x"], int)
          and not isinstance(row["x"], bool)):
        runs.ends.append((tool_use, row["x"]))


# --------------------------------------------------------------------------
# The observation
# --------------------------------------------------------------------------


class CommandRun(NamedTuple):
    """One cited command: its ``cmd`` and ``exit`` as the payload holds them, its state
    (``MATCHED``, ``UNMATCHED`` or ``CONTRADICTED``), and the exit of its newest run
    (None when it has none)."""

    cmd: Any
    exit: Any
    state: str
    newest_exit: Optional[int]


class Observation(NamedTuple):
    """The cited commands, why none could match (``NO_SESSION``, ``NO_LOG``, or None when
    the session's log was read), and the runs root the journal looked under."""

    commands: Tuple[CommandRun, ...]
    cause: Optional[str] = None
    root: Optional[str] = None

    @property
    def observed(self) -> bool:
        """True when there is a command and every command is matched."""
        return bool(self.commands) and all(run.state == MATCHED for run in self.commands)

    @property
    def contradicted(self) -> bool:
        return any(run.state == CONTRADICTED for run in self.commands)


def observe(commands: Any, session: Any) -> Observation:
    """What the run log of SESSION says of each item of COMMANDS (``{"cmd", "exit"}``).
    A command's runs are the end rows whose start row holds ``run_fingerprint(cmd)``;
    the newest is the last of them in file order. Matched: the newest run's exit is
    ``exit``. Contradicted: it is another. Unmatched: no run, no session id, no log, or
    an item the shape check would refuse. It never raises."""
    try:
        items = list(commands) if isinstance(commands, (list, tuple)) else []
        if _plain_session(session):
            runs = read_session_runs(session)
            cause = None if runs is not None else NO_LOG
        else:
            runs, cause = None, NO_SESSION
        newest = _newest_exits(runs)
        return Observation(tuple(_observe_one(item, newest) for item in items), cause,
                           _hooks_common.runs_root())
    except Exception:  # noqa: BLE001 — an observation never blocks an append
        return Observation(())


NOTICE_CMD_CHARS = 60


NOTICE_ROOT_CHARS = 200


def not_observed_lines(observation: Observation) -> Tuple[str, ...]:
    """One line per command that is not matched, as ``append`` prints it after its
    ``appended`` line (ADR 0033, amended by #81): the line names why. The command is
    shown on one line, each character that does not print as ``?``, clipped to
    ``NOTICE_CMD_CHARS``; the root likewise, its end kept."""
    lines = []
    for run in observation.commands:
        if run.state == MATCHED:
            continue
        shown = _part(run.cmd if isinstance(run.cmd, str) else str(run.cmd),
                      NOTICE_CMD_CHARS)
        if run.state == CONTRADICTED:
            why = (f"its newest run in this session exited {run.newest_exit}, not "
                   f"{run.exit} (stored as contradicted)")
        elif observation.cause == NO_SESSION:
            why = ("this shell has no valid CLAUDE_CODE_SESSION_ID, so no run can be tied "
                   "to a session")
        elif observation.cause == NO_LOG and observation.root is None:
            why = "no run log for this session: HOME is unset or not an absolute path"
        elif observation.cause == NO_LOG:
            why = ("no run log for this session under "
                   + _part(observation.root, NOTICE_ROOT_CHARS, tail=True))
        else:
            why = ("no foreground run of this exact command in this session's log; a run "
                   "past the Bash time limit moves to the background and is never seen; "
                   "run it in the foreground here and cite it as typed")
        lines.append(f"not observed: `{shown}` — {why}")
    return tuple(lines)


def _newest_exits(runs: Optional[SessionRuns]) -> Dict[str, int]:
    """Per command hash, the exit of its last end row in file order."""
    newest: Dict[str, int] = {}
    if runs is None:
        return newest
    for tool_use, code in runs.ends:
        digest = runs.starts.get(tool_use)
        if digest is not None:
            newest[digest] = code
    return newest


def _observe_one(item: Any, newest: Dict[str, int]) -> CommandRun:
    cmd = item.get("cmd") if isinstance(item, dict) else None
    code = item.get("exit") if isinstance(item, dict) else None
    if not isinstance(cmd, str) or not isinstance(code, int) or isinstance(code, bool):
        return CommandRun(cmd, code, UNMATCHED, None)
    try:
        digest = _hooks_common.run_fingerprint(cmd)
    except Exception:  # noqa: BLE001 — a lone surrogate, or a Python with no BLAKE2:
        # this command is unmatched, the others still count
        return CommandRun(cmd, code, UNMATCHED, None)
    last = newest.get(digest)
    if last is None:
        return CommandRun(cmd, code, UNMATCHED, None)
    return CommandRun(cmd, code, MATCHED if last == code else CONTRADICTED, last)


# --------------------------------------------------------------------------
# The prune and the survey
# --------------------------------------------------------------------------


def is_run_log(name: str, mode: int) -> bool:
    """True for an entry the prune may delete: a regular file (by ``lstat`` MODE) named
    ``<plain token>.jsonl`` or ``<plain token>.jsonl.1``. The prune refuses and keeps
    every other entry, a link included."""
    if not stat.S_ISREG(mode):
        return False
    for suffix in (OLDER_SUFFIX, LOG_SUFFIX):
        if name.endswith(suffix):
            return _plain_session(name[:-len(suffix)])
    return False


def _runs_cutoff(now: Optional[float]) -> float:
    """The mtime under which a run log is older than ``RUNS_KEEP_DAYS``."""
    return (time.time() if now is None else now) - RUNS_KEEP_DAYS * 86400


class RunsPruneReport(TypedDict):
    removed: List[str]  # the deleted files, in name order
    warnings: List[str]  # an OSError per entry, as text


def prune_runs(root: str, now: Optional[float] = None) -> RunsPruneReport:
    """Delete each run log in the directory ROOT whose mtime is over ``RUNS_KEEP_DAYS``
    old (ADR 0032): one file at a time with ``unlink`` under the directory's fd, after
    its ``lstat`` says ``is_run_log``. A link, in place of ROOT or of an entry, is never
    followed. An OSError is a warning for its entry and the prune goes on; any other
    exception ends it as one warning. It never raises."""
    report: RunsPruneReport = {"removed": [], "warnings": []}
    try:
        _prune_runs(root, _runs_cutoff(now), report)
    except Exception as error:  # noqa: BLE001 — the prune never raises
        report["warnings"].append(f"the prune stopped: {error}")
    return report


def _warn(report: RunsPruneReport, what: str, path: str, error: OSError) -> None:
    report["warnings"].append(f"{what} {path}: {error.strerror or error}")


def _prune_runs(root: str, cutoff: float, report: RunsPruneReport) -> None:
    try:
        dir_fd = os.open(root, _DIR_FLAGS)
    except FileNotFoundError:
        return
    except OSError as error:
        _warn(report, "cannot open", root, error)
        return
    try:
        try:
            with os.scandir(dir_fd) as found:
                names = sorted(entry.name for entry in found)
        except OSError as error:
            _warn(report, "cannot list", root, error)
            return
        for name in names:
            path = os.path.join(root, name)
            try:
                st = os.lstat(name, dir_fd=dir_fd)
            except FileNotFoundError:
                continue
            except OSError as error:
                _warn(report, "cannot read", path, error)
                continue
            if not is_run_log(name, st.st_mode) or not st.st_mtime < cutoff:
                continue
            try:
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                continue
            except OSError as error:
                _warn(report, "cannot remove", path, error)
                continue
            report["removed"].append(path)
    finally:
        os.close(dir_fd)


def prune_old_runs(now: Optional[float] = None) -> None:
    """Right after a ``flow-started`` or a terminal event committed, in any project:
    ``prune_runs`` over the runs root (there is no timer, so a stream that starts or
    ends anywhere sweeps it). It prints only its warnings, on stderr. With no ``runs``
    directory on disk, or a link in its place, it costs one ``lstat``. It never raises,
    so it never changes the exit code and never undoes the event."""
    try:
        root = _hooks_common.runs_root()
        if root is None:
            return
        try:
            if not stat.S_ISDIR(os.lstat(root).st_mode):
                return
        except OSError:
            return
        for warning in prune_runs(root, now)["warnings"]:
            print(f"warning: runs: {_one_line(warning)}", file=sys.stderr)
    except Exception as error:  # noqa: BLE001 — the event has landed
        try:
            print(f"warning: the event landed, but the run log was not pruned "
                  f"({error})", file=sys.stderr)
        except Exception:  # noqa: BLE001 — stderr itself failed; the event has landed
            pass


class RunsLogs(TypedDict):
    files: int
    bytes: int
    oldest_days: Optional[int]  # the oldest run log's age in whole days; None: none


class RunsNextPrune(TypedDict):
    files: int  # the run logs over RUNS_KEEP_DAYS the next prune deletes


class RunsRefused(TypedDict):
    count: int
    first: Optional[str]  # the first refused path in sorted order


class RunsSurvey(TypedDict):
    """``survey_runs``. The parts are None when the root is no directory; ``refused``
    names the root itself when something else, a link included, is in its place."""

    root: Optional[str]  # the root, its parent resolved; None when there is no root
    exists: bool
    logs: Optional[RunsLogs]
    next_prune: Optional[RunsNextPrune]
    refused: Optional[RunsRefused]


def survey_runs(root: Optional[str], now: Optional[float] = None) -> RunsSurvey:
    """What the runs root holds, and what the next prune deletes and refuses there. It
    classifies each entry with ``is_run_log`` and ``_runs_cutoff``, as the prune does,
    and only reads: it opens the directory to list it, and removes, makes, renames and
    touches nothing. An entry it cannot read is left out of the counts."""
    survey: RunsSurvey = {"root": None, "exists": False, "logs": None,
                          "next_prune": None, "refused": None}
    if root is None:
        return survey
    # The parent resolved, the last part as it is: a link in place of `runs` stays one.
    shown = os.path.join(os.path.realpath(os.path.dirname(root)), os.path.basename(root))
    survey["root"] = shown
    try:
        mode = os.lstat(root).st_mode
    except OSError:
        return survey
    if not stat.S_ISDIR(mode):
        survey["refused"] = {"count": 1, "first": shown}
        return survey
    clock = time.time() if now is None else now
    cutoff = _runs_cutoff(clock)
    files = size = old = 0
    oldest: Optional[float] = None
    refused: List[str] = []
    try:
        dir_fd = os.open(root, _DIR_FLAGS)
    except OSError:
        dir_fd = None
    if dir_fd is not None:
        try:
            with os.scandir(dir_fd) as found:
                names = sorted(entry.name for entry in found)
            for name in names:
                try:
                    st = os.lstat(name, dir_fd=dir_fd)
                except OSError:
                    continue
                if not is_run_log(name, st.st_mode):
                    refused.append(os.path.join(shown, name))
                    continue
                files += 1
                size += st.st_size
                oldest = st.st_mtime if oldest is None else min(oldest, st.st_mtime)
                if st.st_mtime < cutoff:
                    old += 1
        except OSError:
            pass
        finally:
            os.close(dir_fd)
    survey["exists"] = True
    survey["logs"] = {"files": files, "bytes": size,
                      "oldest_days": (None if oldest is None
                                      else max(0, int((clock - oldest) // 86400)))}
    survey["next_prune"] = {"files": old}
    survey["refused"] = {"count": len(refused), "first": refused[0] if refused else None}
    return survey
