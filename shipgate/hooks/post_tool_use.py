#!/usr/bin/env python3
"""PostToolUse hook — record artifact writes made through Write/Edit.

This is the *fast* capture path, not the complete one: a file written by a Bash heredoc
or `sed` never reaches PostToolUse. `file_changed.py` watches the disk and catches those.

Nothing here can block — the tool has already run by the time this fires, which is
exactly right. Capture is a recording, never a veto.

This hook fires on every Write/Edit in every project, so the ordering below is
deliberate: gate on the sidecar before reading stdin, and return before importing
anything heavy when the project isn't journaled.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    append_event,
    find_project,
    likely_journaled,
    mtime_of,
    read_hook_input,
    safe_main,
)

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def changed_path(payload):
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    return raw if isinstance(raw, str) and raw else None


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    if payload.get("tool_name") not in WRITE_TOOLS:
        sys.exit(0)

    target = changed_path(payload)
    if target is None:
        sys.exit(0)

    project = find_project(payload.get("cwd"), os.path.dirname(target))
    if project is None or not project.enforces("auto_capture"):
        sys.exit(0)
    if not project.covers(target):
        sys.exit(0)

    append_event(
        project,
        "shipgate",
        "artifact-written",
        {
            "path": project.relative(target).replace(os.sep, "/"),
            "source": "tool",
            "tool": payload.get("tool_name"),
            "mtime": mtime_of(target),
            "session": payload.get("session_id"),
        },
    )


safe_main(main)
