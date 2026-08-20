#!/usr/bin/env python3
"""SessionStart hook — hand the session its position before it thinks to ask.

Injects the journal's resume brief as context, and opens the session's event window by
recording `session-started`. That window is what `journal.py check` measures against at
Stop time: everything appended after this event belongs to this session.
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
    read_hook_input,
    run_journal,
    safe_main,
    watch_paths,
)

META_STREAM = "shipgate"


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    project = find_project(payload.get("cwd"))
    if project is None:
        sys.exit(0)

    session_id = payload.get("session_id") or "unknown"
    append_event(
        project,
        META_STREAM,
        "session-started",
        {"session": session_id, "source": payload.get("source") or "startup"},
    )

    watched = watch_paths(project)

    result = run_journal(project, ["status"])
    if result is None or result.returncode != 0:
        # The journal is configured but unreachable. Say so rather than starting the
        # session silently blind — the orchestrator treats this as an infrastructure
        # problem needing acknowledgement, not as an un-journaled project.
        detail = (result.stderr or "").strip() if result else "journal CLI unavailable"
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "watchPaths": watched,
                    "additionalContext": (
                        "shipgate: this project declares a flow journal, but reading it "
                        f"failed ({detail or 'unknown error'}). Do NOT silently fall back "
                        "to inferring phase from artifacts — surface this, suggest "
                        "`journal.py doctor`, and continue only with the user's "
                        "acknowledgement."
                    ),
                }
            }
        )
        sys.exit(0)

    brief = (result.stdout or "").strip()
    if not brief:
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "watchPaths": watched,
                }
            }
        )
        sys.exit(0)

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "watchPaths": watched,
                "additionalContext": (
                    "shipgate flow journal — this is the authoritative position for work "
                    "in this project. Route from it; do not re-derive phase by scanning "
                    "worklog checkboxes.\n\n" + brief
                ),
            }
        }
    )


safe_main(main)
