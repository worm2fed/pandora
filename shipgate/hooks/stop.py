#!/usr/bin/env python3
"""Stop hook — refuse to let a session end with its bookkeeping unrecorded.

Contract details that are easy to get wrong, and are deliberate here:

* `decision` is **top level**. Nesting it under `hookSpecificOutput` (right for
  PreToolUse) is silently ignored for Stop — a no-op that looks like working code.
* Omitting `decision` entirely is how you allow the stop. There is no "allow" value.
* Exit 1 does not block; it is reported as a hook error while the session ends anyway.
  So this hook only ever exits 0 (with or without block JSON).
* `stop_hook_active` means the session is already continuing because we blocked it
  once. Standing down then is what keeps this from looping — and the harness hard-
  overrides a Stop hook after 8 consecutive blocks regardless, which is why `check`
  must report every finding at once rather than trickling them out one per round.
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
)

CHECK_FINDINGS_EXIT = 5
META_STREAM = "shipgate"


def format_reason(findings: list) -> str:
    lines = [
        "shipgate: this session changed flow artifacts without recording the matching "
        "journal events. Append them, then finish.",
        "",
    ]
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        missing = finding.get("missing") or "event"
        detail = finding.get("detail") or ""
        lines.append(f"- missing `{missing}` — {detail}".rstrip(" —"))
        command = finding.get("suggested_command")
        if command:
            lines.append(f"      {command}")
    lines.append("")
    lines.append(
        "If one of these is genuinely not warranted, record why instead of skipping it: "
        "append a `deviation` event saying so."
    )
    return "\n".join(lines)


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()

    # Already re-entrant from our own earlier block: stand down.
    if payload.get("stop_hook_active") is True:
        sys.exit(0)

    project = resolve_project(payload)
    if project is None or not project.enforces("stop_gate"):
        sys.exit(0)

    session_id = payload.get("session_id") or "unknown"
    result = run_journal(project, ["check", "--session", session_id, "--json"])

    # Unreachable journal must not trap the user in an unendable session.
    if result is None or result.returncode != CHECK_FINDINGS_EXIT:
        sys.exit(0)

    import json

    try:
        findings = (json.loads(result.stdout or "{}") or {}).get("findings") or []
    except ValueError:
        findings = []
    if not findings:
        sys.exit(0)

    append_event(
        project,
        META_STREAM,
        "gate-blocked",
        {"session": session_id, "findings": len(findings)},
    )
    emit({"decision": "block", "reason": format_reason(findings)})


safe_main(main)
