#!/usr/bin/env python3
"""SessionStart hook — hand the session its position before it thinks to ask.

Injects the journal's resume brief as context, and opens the session's event window by
recording `session-started`. That window is what `journal.py check` measures against at
Stop time: everything appended after this event belongs to this session.

The session id is also handed to `journal.py session --set`, because a skill's shell
cannot see it and `append` needs it to attribute skill-written events (ADR 0003).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    append_event,
    emit,
    likely_journaled,
    read_hook_input,
    resolve_project,
    run_journal,
    safe_main,
    watch_paths,
)

META_STREAM = "shipgate"
GIT_TIMEOUT_SECONDS = 2


def current_branch(cwd):
    """The branch checked out in `cwd`, or None when there is no name worth passing.

    A detached HEAD answers with the literal `HEAD`, which is not a branch and matches
    no stream. No git, no repository and a hung git all land here as None as well: the
    branch is an ordering hint for the brief, never a reason to degrade it.
    """
    import subprocess

    if not isinstance(cwd, str):
        return None
    # `GIT_DIR`/`GIT_WORK_TREE` inherited from the session point git at whatever
    # repository set them, not at `cwd`; drop the whole family rather than guess.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = (result.stdout or "").strip()
    return branch if branch and branch != "HEAD" else None


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    project = resolve_project(payload)
    if project is None:
        sys.exit(0)

    session_id = payload.get("session_id") or "unknown"
    append_event(
        project,
        META_STREAM,
        "session-started",
        {"session": session_id, "source": payload.get("source") or "startup"},
    )
    attributed = run_journal(project, ["session", f"--set={session_id}"])
    notice = (
        ""
        if attributed is not None and attributed.returncode == 0
        else (
            "shipgate: session attribution unavailable (journal.py session --set "
            "failed) — skill appends this session will carry no session label.\n\n"
        )
    )

    watched = watch_paths(project)

    branch = current_branch(payload.get("cwd"))
    # `--branch=<name>`, never two tokens: a branch may be literally named `--all`,
    # and argparse would read the second token as a flag.
    result = run_journal(
        project, ["status", f"--branch={branch}"] if branch else ["status"]
    )
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
        specific = {"hookEventName": "SessionStart", "watchPaths": watched}
        if notice:
            specific["additionalContext"] = notice.strip()
        emit({"hookSpecificOutput": specific})
        sys.exit(0)

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "watchPaths": watched,
                "additionalContext": notice
                + (
                    "shipgate flow journal — this is the authoritative position for "
                    "work in this project. Route from it; do not re-derive phase by "
                    "scanning worklog checkboxes.\n\n" + brief
                ),
            }
        }
    )


safe_main(main)
