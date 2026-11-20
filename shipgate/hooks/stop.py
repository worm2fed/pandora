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


NO_COMMAND = "(no command: a name in it holds a character that does not print on one line)"


def single_line_command(command) -> str:
    """A command as `check` printed it, or the stand-in. `check` prints none for a stream
    name it cannot put on one line; anything else that is not one line is refused here
    too, because collapsing a command would change what it does."""
    if isinstance(command, str) and command and command.isprintable():
        return command
    return NO_COMMAND


def one_line(value) -> str:
    """The reason reaches the session as prose. A path or a stream name comes from the
    journal, so a line break in one must not add lines to the block text."""
    return " ".join(str(value).split())


def format_reason(findings: list, waivers: list) -> str:
    lines = [
        "shipgate: this session changed flow artifacts without recording the matching "
        "journal events. Append them, then finish.",
        "",
    ]
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        missing = one_line(finding.get("missing") or "event")
        detail = one_line(finding.get("detail") or "")
        lines.append(f"- missing `{missing}` — {detail}".rstrip(" —"))
        lines.append(f"      {single_line_command(finding.get('suggested_command'))}")
    commands = [
        single_line_command(waiver.get("command")) for waiver in waivers
        if isinstance(waiver, dict)
    ]
    if commands:
        # `check` reads this waiver (ADR 0020). A `deviation` of any other kind clears
        # nothing, and the same block would come back on the next turn.
        lines.append("")
        lines.append(
            "If one of these is genuinely not warranted, record a waiver instead of "
            "skipping it: a `deviation` of kind `gate-waived` that names the task ids. "
            "Write the reason in `note` first: `append` refuses the placeholder, "
            "with `--force` too."
        )
        lines.extend(f"      {command}" for command in commands)
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
    # `--record` stamps the run, so `journal.py doctor` can tell a gate that runs and
    # finds nothing from one that never runs.
    result = run_journal(
        project, ["check", "--session", session_id, "--json", "--record"]
    )

    # Unreachable journal must not trap the user in an unendable session.
    if result is None or result.returncode != CHECK_FINDINGS_EXIT:
        sys.exit(0)

    import json

    try:
        report = json.loads(result.stdout or "{}") or {}
    except ValueError:
        report = {}
    if not isinstance(report, dict):
        report = {}
    findings = report.get("findings")
    # Only a finding the reason can print blocks: a block with no text helps nobody.
    findings = [
        finding for finding in (findings if isinstance(findings, list) else [])
        if isinstance(finding, dict)
    ]
    if not findings:
        sys.exit(0)
    waivers = report.get("waivers")
    waivers = waivers if isinstance(waivers, list) else []

    append_event(
        project,
        META_STREAM,
        "gate-blocked",
        {"session": session_id, "findings": len(findings)},
    )
    emit({"decision": "block", "reason": format_reason(findings, waivers)})


safe_main(main)
