"""The run log of the Bash hooks (ADR 0032).

PreToolUse appends a start row, `{"i": <tool_use_id>, "h": <fingerprint>}`, where the
fingerprint is `run_fingerprint` of the command the model typed. PostToolUse and
PostToolUseFailure append an end row, `{"i": <tool_use_id>, "x": <exit>}`, only when the
payload shows the exit status. The rows go to `runs_root()/<session_id>.jsonl`, and the
journal joins them when a `verify-run` is appended (ADR 0033). No row holds command
text, output, a time, a directory or an agent id.

The hooks import this module only in a journaled project, so its code is compiled once
and cached; `pre_tool_use.py` is compiled on every run (#48). Every error here is
swallowed: the writer never prints, never raises and never blocks.
"""

from __future__ import annotations

import json
import os
import stat

from _common import RUNS_FILE_BYTES, load_project, run_fingerprint, runs_root

MAX_ID_LENGTH = 128
# One `write` per row, so parallel hooks append whole lines. Every row with ASCII ids
# is far below this; an id that JSON escapes past it writes nothing.
MAX_ROW_BYTES = 200
_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_EXIT_PREFIX = "Exit code "
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC
# O_NONBLOCK: a FIFO in the file's place fails the open instead of hanging the hook.
_FILE_FLAGS = (os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
               | _CLOEXEC)


def _session(payload):
    """The payload's session id when it is a plain token (ADR 0023 §12), else None."""
    session = payload.get("session_id")
    if (isinstance(session, str) and 0 < len(session) <= MAX_ID_LENGTH
            and all(char in _TOKEN_CHARS for char in session)):
        return session
    return None


def _tool_use_id(payload):
    tool_use_id = payload.get("tool_use_id")
    if isinstance(tool_use_id, str) and 0 < len(tool_use_id) <= MAX_ID_LENGTH:
        return tool_use_id
    return None


def record_start(payload, command, root):
    """Append the start row of the Bash call in `payload`, whose project's settings file
    sits at `root`. `command` is the text PreToolUse received."""
    try:
        session, tool_use_id = _session(payload), _tool_use_id(payload)
        if session is None or tool_use_id is None:
            return
        project = load_project(root)
        if project is None or not project.enforces("auto_capture"):
            return
        _append(session, {"i": tool_use_id, "h": run_fingerprint(command)})
    except Exception:  # noqa: BLE001 — the run log never surfaces in a session
        pass


def record_end(payload, project):
    """Append the end row of the Bash call in `payload` when it shows the exit status.
    `project` is the hook's journaled project, or None."""
    try:
        if project is None or not project.enforces("auto_capture"):
            return
        if payload.get("tool_name") != "Bash":
            return
        session, tool_use_id = _session(payload), _tool_use_id(payload)
        if session is None or tool_use_id is None:
            return
        status = exit_status(payload)
        if status is not None:
            _append(session, {"i": tool_use_id, "x": status})
    except Exception:  # noqa: BLE001 — the run log never surfaces in a session
        pass


def exit_status(payload):
    """The exit status a post event shows (ADR 0032's table), or None when it shows none.

    PostToolUse fires on exit 0, but also on an exit that Claude Code interprets (`grep`
    with no match, a false `test`) and at a background launch: only a plain foreground
    pass is 0. PostToolUseFailure's `error` starts with `Exit code N`, and the rest of
    it is the run's output, which is never read.
    """
    event = payload.get("hook_event_name")
    if event == "PostToolUse":
        response, tool_input = payload.get("tool_response"), payload.get("tool_input")
        if not isinstance(response, dict) or not isinstance(tool_input, dict):
            return None
        if "returnCodeInterpretation" in response or "backgroundTaskId" in response:
            return None
        if response.get("interrupted") is not False:
            return None
        if tool_input.get("run_in_background") not in (None, False):
            return None
        return 0
    if event == "PostToolUseFailure":
        if payload.get("is_interrupt") not in (None, False):
            return None
        error = payload.get("error")
        if not isinstance(error, str) or not error.startswith(_EXIT_PREFIX):
            return None
        digits = error.partition("\n")[0][len(_EXIT_PREFIX):]
        if not (0 < len(digits) <= 3 and digits.isascii() and digits.isdigit()):
            return None
        status = int(digits)
        return status if status <= 255 else None
    return None


def _append(session, row):
    """Append `row` as one line of the session's file, which is rotated to `.jsonl.1`
    at RUNS_FILE_BYTES. Raises OSError; the callers swallow it."""
    data = (json.dumps(row, separators=(",", ":")) + "\n").encode("ascii")
    root = runs_root()
    if len(data) >= MAX_ROW_BYTES or root is None:
        return
    try:
        dir_fd = os.open(root, _DIR_FLAGS)
    except FileNotFoundError:
        os.makedirs(root, mode=0o700, exist_ok=True)
        dir_fd = os.open(root, _DIR_FLAGS)
    try:
        name = session + ".jsonl"
        fd, st = _open_file(name, dir_fd)
        if fd is None:
            return
        try:
            if st.st_size >= RUNS_FILE_BYTES:
                os.close(fd)
                fd = None
                # Another hook may have rotated the file since: rotate only the one
                # that is full, never the new one, and write to whatever file is there.
                try:
                    now = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                except FileNotFoundError:
                    now = None
                if now is not None and (now.st_dev, now.st_ino) == (st.st_dev, st.st_ino):
                    os.replace(name, name + ".1", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                fd, st = _open_file(name, dir_fd)
                if fd is None:
                    return
            os.write(fd, data)
        finally:
            if fd is not None:
                os.close(fd)
    finally:
        os.close(dir_fd)


def _open_file(name, dir_fd):
    """`(fd, stat)` of the regular file `name` in `dir_fd`, made 0600 when missing, or
    `(None, None)`. A link, a FIFO or a directory in its place fails the open or the
    check."""
    fd = os.open(name, _FILE_FLAGS, 0o600, dir_fd=dir_fd)
    st = os.fstat(fd)
    if stat.S_ISREG(st.st_mode):
        return fd, st
    os.close(fd)
    return None, None
