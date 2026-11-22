#!/usr/bin/env python3
"""The recorder — write the user's go, or a witness, where the user answers (ADR 0023).

It runs on two events:

* UserPromptSubmit: the user's typed prompt is a reply;
* PostToolUse with the matcher `AskUserQuestion`: the user's answer to a question is a
  reply.

The hook is transport only. `journal.py reply` owns the word lists and the matching: it
reads the reply on stdin and prints the rows to write, writing nothing itself. The hook
writes those rows with the existing `append --batch`, removes the session's request
marker when no request is left open, and gives the model the context line. So the model
gets no new command that writes a go or a witness.

The transport facts this hook holds are four:

* a prompt that starts with `<` is no reply: a subagent report, a message from another
  session, or a relayed text in a wrapper tag. It records nothing and closes nothing;
* a typed text over 32 characters never leaves the hook: a prompt, or a question answer
  that is no option label, goes to the journal as `null`;
* with no request marker for the session, a prompt over 32 characters runs no journal
  (FR-032), and a question with no gate header runs none either;
* a header is a gate header when it reads `commit` or `publish` as the journal reads a
  reply (case, outer space and one closing `.` or `!` ignored); an answer under any other
  header goes as `null`, since it can only witness.

After a witness, the journal's context line asks the model for a new go request and one
confirming question with the gate header (ADR 0023, amendment A2); the hook passes it on
as the event's `additionalContext`.

This hook fires on every prompt in every project, so the order is deliberate: a `stat`
gate on the sidecar before stdin is read, and no heavy import before the project is
known to be journaled. It never blocks a prompt and never exits 2.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    SESSION_ENV,
    emit,
    likely_journaled,
    marker_path,
    read_hook_input,
    resolve_project,
    run_journal,
    safe_main,
)

# A typed text longer than this never leaves the hook (ADR 0023 §11, FR-032).
SHORT_REPLY_CHARS = 32
# The gate headers of a question (§5). An answer under another header only witnesses.
GATE_HEADERS = ("commit", "publish")
# Each journal run gets this long; two runs stay under the hook timeout of 10 seconds.
JOURNAL_RUN_SECONDS = 4
QUESTION_TOOL = "AskUserQuestion"


def session_of(payload):
    session = payload.get("session_id")
    if isinstance(session, str) and session:
        return session
    return os.environ.get(SESSION_ENV, "").strip() or None


def _folded(text):
    """A header as the journal's `reply_word` reads it."""
    word = text.strip()
    if word[-1:] in (".", "!"):
        word = word[:-1].rstrip()
    return word.casefold()


def _sent_answer(answer, labels):
    """The answer as it may leave the hook: whole when it is the selected option labels,
    or a typed text of at most 32 characters; else None."""
    if not isinstance(answer, str):
        return None
    if answer in labels or all(part.strip() in labels for part in answer.split(", ")):
        return answer
    return answer if len(answer.strip()) <= SHORT_REPLY_CHARS else None


def prompt_reply(payload, has_marker):
    """The journal's input for a typed prompt, or None when it is no reply to read."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return None
    if prompt.lstrip().startswith("<"):
        return None  # a subagent report, another session's message, a relayed text
    short = len(prompt.strip()) <= SHORT_REPLY_CHARS
    if not short and not has_marker:
        return None
    reply = {"via": "prompt", "text": prompt if short else None}
    if isinstance(payload.get("prompt_id"), str):
        reply["prompt_id"] = payload["prompt_id"]
    return reply


def question_reply(payload, has_marker):
    """The journal's input for an `AskUserQuestion` answer, or None.

    Only an answer under a gate header leaves the hook as text; any other answer goes as
    `null`, since it can only witness. With no marker and no gate header the journal is
    not run at all.
    """
    tool_input = payload.get("tool_input")
    response = payload.get("tool_response")
    if not isinstance(tool_input, dict) or not isinstance(response, dict):
        return None
    questions = tool_input.get("questions")
    answers = response.get("answers")
    if not isinstance(questions, list) or not isinstance(answers, dict):
        return None
    pairs = []
    gated = False
    for item in questions:
        if not isinstance(item, dict):
            continue
        header = item.get("header") if isinstance(item.get("header"), str) else None
        answer = answers.get(item.get("question"))
        is_gate = header is not None and _folded(header) in GATE_HEADERS
        gated = gated or is_gate
        options = item.get("options") if isinstance(item.get("options"), list) else []
        labels = {o.get("label") for o in options if isinstance(o, dict)}
        pairs.append({
            "header": header,
            "answer": _sent_answer(answer, labels) if is_gate else None,
            # A stream label counts as a go only in a multi-select (ADR 0023 §5).
            "multi_select": item.get("multiSelect") is True,
        })
    if not pairs or not (gated or has_marker):
        return None
    reply = {"via": "question", "answers": pairs}
    for key in ("tool_use_id", "prompt_id"):
        if isinstance(payload.get(key), str):
            reply[key] = payload[key]
    return reply


def _json(result):
    import json

    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def write_plan(project, session, plan):
    """Write the plan's rows in one batch. Returns (the seqs written, the rows planned)."""
    import json

    events = plan.get("events")
    if not isinstance(events, list) or not events:
        return [], 0
    lines = "".join(
        json.dumps({k: event.get(k) for k in ("stream", "type", "data", "actor")},
                   separators=(",", ":")) + "\n"
        for event in events if isinstance(event, dict)
    )
    first = events[0].get("stream") if isinstance(events[0], dict) else None
    if not isinstance(first, str) or not first:
        return [], len(events)
    result = run_journal(
        project, ["append", "--stream", first, "--batch", "--json"],
        stdin_text=lines, timeout=JOURNAL_RUN_SECONDS, session=session,
    )
    seqs = []
    if result is not None:
        try:
            rows = json.loads(result.stdout or "[]")
        except ValueError:
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get("seq"), int):
                seqs.append(row["seq"])
    return seqs, len(events)


def context_of(plan, seqs, planned):
    context = plan.get("context")
    if not isinstance(context, str) or not context:
        return None
    if len(seqs) < planned:
        # #55: the journal prints the commands with its own path, --db and stream.
        if not seqs:
            unwritten = plan.get("unwritten")
            if isinstance(unwritten, str) and unwritten:
                return unwritten
            return ("shipgate: the recorder could not write the user's reply to the "
                    "journal; nothing was recorded. Record a go-requested and ask again.")
        status = plan.get("status_command")
        if not isinstance(status, str) or not status:
            status = "journal.py status"
        return (f"shipgate: the recorder wrote only {len(seqs)} of {planned} rows for "
                f"the user's reply; run `{status}` before you rely on a go.")
    return context


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    event_name = payload.get("hook_event_name")
    is_question = payload.get("tool_name") == QUESTION_TOOL
    if not is_question and "prompt" not in payload:
        sys.exit(0)

    session = session_of(payload)
    project = resolve_project(payload)
    if project is None or session is None:
        sys.exit(0)
    marker = marker_path(project.db_path, session)
    if marker is None:
        sys.exit(0)
    has_marker = os.path.isfile(marker)

    reply = (question_reply if is_question else prompt_reply)(payload, has_marker)
    if reply is None:
        sys.exit(0)

    import json

    plan = _json(run_journal(
        project, ["reply", "--session", session, "--json"],
        stdin_text=json.dumps(reply), timeout=JOURNAL_RUN_SECONDS, session=session,
    ))
    if not isinstance(plan, dict):
        sys.exit(0)

    seqs, planned = write_plan(project, session, plan)
    if plan.get("open") == 0 and has_marker and len(seqs) == planned:
        try:
            os.remove(marker)
        except OSError:
            pass

    context = context_of(plan, seqs, planned)
    if context:
        emit({
            "hookSpecificOutput": {
                "hookEventName": event_name if isinstance(event_name, str) else (
                    "PostToolUse" if is_question else "UserPromptSubmit"
                ),
                "additionalContext": context,
            }
        })


if __name__ == "__main__":
    safe_main(main)
