#!/usr/bin/env python3
"""FileChanged hook — the capture path that cannot be dodged.

`PostToolUse` sees the tool calls: Write/Edit, and Bash only through the call's own
evidence. This one watches the disk, so a PRD rewritten by a Bash heredoc, `sed`, or an
external editor is recorded too — which is the whole reason the enforcement story holds
together.

What it records is an observation, never an author. Every session's watcher fires on the
same write, so the session in the payload is one that saw the change (`observed_by`);
the journal decides who wrote it from the tool hooks' claims (ADR 0008).

Two mechanics worth remembering when editing this file:

* It re-returns `watchPaths` on every fire. Each return *replaces* the dynamic watch
  list, and the list is literal absolute paths rather than globs, so re-expanding here
  is how a newly created artifact starts being watched.
* The journal database must never sit inside a watched path. Nothing is watched
  implicitly, and we never add the db, so the rewrite loop the harness docs warn about
  cannot start. Keep it that way.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    append_event,
    emit,
    find_project,
    likely_journaled,
    mtime_of,
    read_hook_input,
    safe_main,
    watch_paths,
)


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    project = find_project(payload.get("cwd"))
    if project is None or not project.enforces("auto_capture"):
        sys.exit(0)

    # Refresh the watch list even when this particular change isn't ours to record —
    # a sibling artifact may have appeared since the list was last built.
    refreshed = {
        "hookSpecificOutput": {
            "hookEventName": "FileChanged",
            "watchPaths": watch_paths(project),
        }
    }

    changed = payload.get("file_path")
    if not isinstance(changed, str) or not changed or not project.covers(changed):
        emit(refreshed)
        sys.exit(0)

    append_event(
        project,
        "shipgate",
        "artifact-written",
        {
            "path": project.relative(changed).replace(os.sep, "/"),
            "source": "disk",
            "change": payload.get("event") or "change",
            "mtime": mtime_of(changed),
            # Every session's watcher fires on one write, so this session saw the change
            # and may not have made it: an observer, never an author (ADR 0008).
            "observed_by": payload.get("session_id"),
        },
    )

    emit(refreshed)


safe_main(main)
