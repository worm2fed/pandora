"""The recorder's reply plan and the command gate's `authorize` (ADR 0023)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple, get_args

from .vocab import DecisionSource, GoGate, UsageError
from .plugin import (
    _journal_command, _request_command, CONFIRMING_QUESTION_PLACEHOLDER,
    GATE_QUESTION_PLACEHOLDER,
)
from .text import _in_backticks
from .store import Event, list_streams, read_events
from .sessions import _actor_role, request_session
from .approval import commit_authorization, user_go
from .fold import branch_match, fold_stream, is_work_stream, session_stream


# --------------------------------------------------------------------------
# The reply (ADR 0023): which rows a user's reply gives. `reply` plans, never writes.
# --------------------------------------------------------------------------

# The exact go of a typed reply (§6): a whole reply from these lists, after case folding,
# with outer space and one closing `.` or `!` removed. Built in: no config adds words.
GATE_WORDS: Dict[str, str] = {"commit": "commit", "publish": "publish", "push": "publish"}
GENERAL_WORDS = frozenset({"all", "yes", "y", "ok", "go", "approve"})


def reply_word(text: Any) -> Optional[str]:
    """The reply as the word lists read it, or None for no text (§6)."""
    if not isinstance(text, str):
        return None
    word = text.strip()
    if word[-1:] in (".", "!"):
        word = word[:-1].rstrip()
    return word.casefold() or None


def _closes_request(event: Event, request: Event) -> bool:
    """A later row that answers a go request: a marked go row at its gate, or a witness
    that names it (the worklog's "open request")."""
    if event.seq <= request.seq:
        return False
    if event.type == "reply-witnessed":
        return event.data.get("request") == request.seq
    return (
        event.type == "gate-decision"
        and event.data.get("gate") == request.data.get("gate")
        and event.data.get("source") in get_args(DecisionSource)
    )


def open_requests(
    with_events: Sequence[Tuple[Dict[str, Any], Sequence[Event]]], session: str
) -> List[Event]:
    """The session's open go requests on live streams, in seq order (§3, §4)."""
    found: List[Event] = []
    for entry, events in with_events:
        if entry["terminal"]:
            continue
        for request in events:
            if request.type != "go-requested" or request_session(request) != session:
                continue
            if request.data.get("gate") not in get_args(GoGate):
                continue
            if not any(_closes_request(e, request) for e in events):
                found.append(request)
    return sorted(found, key=lambda event: event.seq)


def _fold_work_streams(
    conn: sqlite3.Connection,
) -> List[Tuple[Dict[str, Any], List[Event]]]:
    folded = []
    for stream in list_streams(conn):
        if not is_work_stream(stream):
            continue
        events = read_events(conn, stream=stream)
        if events:
            folded.append((fold_stream(events), events))
    return folded


class ReplyInput(NamedTuple):
    via: str
    text: Optional[str]
    # (header, answer, multi_select) per question.
    answers: List[Tuple[Optional[str], Optional[str], bool]]
    prompt_id: Optional[str]
    tool_use_id: Optional[str]


def parse_reply_input(raw: str) -> ReplyInput:
    """The recorder's stdin for `reply` (the worklog's API section), or UsageError."""
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise UsageError(f"reply reads one JSON object on stdin: {error}")
    if not isinstance(payload, dict):
        raise UsageError("reply reads one JSON object on stdin")

    def text_of(key: str) -> Optional[str]:
        value = payload.get(key)
        return value if isinstance(value, str) and value else None

    via = payload.get("via")
    if via == "prompt":
        return ReplyInput("prompt", text_of("text"), [], text_of("prompt_id"), None)
    if via == "question":
        answers = payload.get("answers")
        if not isinstance(answers, list):
            raise UsageError("a question reply carries `answers`, a list")
        pairs: List[Tuple[Optional[str], Optional[str], bool]] = []
        for item in answers:
            if not isinstance(item, dict):
                raise UsageError("each answer is an object {header, answer}")
            header, answer = item.get("header"), item.get("answer")
            pairs.append((
                header if isinstance(header, str) else None,
                answer if isinstance(answer, str) else None,
                item.get("multi_select") is True,
            ))
        return ReplyInput(
            "question", None, pairs, text_of("prompt_id"), text_of("tool_use_id")
        )
    raise UsageError("reply's `via` is `prompt` or `question`")


def _exact_go_row(
    stream: str, gate: str, source: str, request: Optional[Event]
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "gate": gate,
        "question": (
            request.data.get("question") if request is not None
            else f"the user typed `{gate}` with no open go request"
        ),
        "decision": gate,
        "mode": "ask",
        "raised_by": "user",
        "source": source,
    }
    if request is not None:
        data["request"] = request.seq
    return {"stream": stream, "type": "gate-decision", "data": data, "actor": "user"}


def _matched_requests(
    reply: ReplyInput, requests: Sequence[Event], live: Set[str]
) -> List[Event]:
    """The open requests the reply states an exact go for (§5, §6)."""
    if reply.via == "prompt":
        word = reply_word(reply.text)
        if word in GENERAL_WORDS:
            return list(requests)
        gate = GATE_WORDS.get(word or "")
        return [r for r in requests if r.data.get("gate") == gate] if gate else []
    matched: List[Event] = []
    for header, answer, multi_select in reply.answers:
        gate = reply_word(header)
        if gate not in get_args(GoGate) or answer is None:
            continue
        if GATE_WORDS.get(reply_word(answer) or "") == gate:
            matched.extend(r for r in requests if r.data.get("gate") == gate)
            continue
        if not multi_select:
            continue  # a stream label is a go only in a multi-select (§5)
        labels = {label.strip() for label in answer.split(", ")} & live
        matched.extend(
            r for r in requests
            if r.data.get("gate") == gate and r.stream in labels
        )
    return [r for r in requests if r in matched]


def _confirm_line(db_path: Path, stream: str, gate: str) -> str:
    """What the flow does after a reply that is no exact go (ADR 0023 amendment A2)."""
    word = gate.capitalize()
    command = _request_command(db_path, stream, gate)
    return (
        f"record a new go-requested for the {gate} gate of {stream}"
        + _in_backticks(command)
        + f", then ask one confirming question with the header `{word}` and `{word}` as "
        "the first option; the recorder records the click"
    )


def plan_reply(
    conn: sqlite3.Connection, session: str, reply: ReplyInput, db_path: Path
) -> Dict[str, Any]:
    """The rows a reply gives, and the context line (ADR 0023 §4-§9). Writes nothing.

    Every open request of the session gets one row: an exact go when the reply matches
    it, a witness otherwise. A witness's line asks for a new go request and one
    confirming question (amendment A2). With no open request, a gate word is a go for the
    stream the session drives, and any other reply plans nothing. No output holds the
    text.
    """
    with_events = _fold_work_streams(conn)
    requests = open_requests(with_events, session)
    live = {entry["stream"] for entry, _ in with_events if not entry["terminal"]}
    source = "prompt" if reply.via == "prompt" else "question"
    events: List[Dict[str, Any]] = []
    recorded: List[Dict[str, Any]] = []
    witnessed: List[Dict[str, Any]] = []
    lines: List[str] = []

    if not requests:
        gate = None
        if reply.via == "prompt":
            gate = GATE_WORDS.get(reply_word(reply.text) or "")
        else:
            for header, answer, _ in reply.answers:
                folded = reply_word(header)
                if folded in get_args(GoGate) and GATE_WORDS.get(
                    reply_word(answer) or ""
                ) == folded:
                    gate = folded
                    break
        driven = session_stream(with_events, session) if gate else None
        if gate and driven:
            events.append(_exact_go_row(driven, gate, source, None))
            recorded.append({"stream": driven, "gate": gate, "request": None})
            lines.append(f"go recorded for {gate} on {driven}")
    else:
        matched = _matched_requests(reply, requests, live)
        for request in requests:
            gate = request.data["gate"]
            if request in matched:
                events.append(_exact_go_row(request.stream, gate, source, request))
                recorded.append(
                    {"stream": request.stream, "gate": gate, "request": request.seq}
                )
                lines.append(f"go recorded for {gate} on {request.stream}")
                continue
            data: Dict[str, Any] = {
                "request": request.seq, "gate": gate, "via": reply.via,
                "session": session,
            }
            if reply.prompt_id:
                data["prompt_id"] = reply.prompt_id
            if reply.tool_use_id:
                data["tool_use_id"] = reply.tool_use_id
            events.append({
                "stream": request.stream, "type": "reply-witnessed", "data": data,
                "actor": "hook",
            })
            witnessed.append(
                {"stream": request.stream, "gate": gate, "request": request.seq}
            )
            lines.append(
                f"the user's reply to the {gate} request (seq {request.seq}) on "
                f"{request.stream} is no exact go, so nothing is recorded. Unless the "
                "reply refuses, "
                + _confirm_line(db_path, request.stream, gate)
                + ". If the reply refuses, or it answered your confirming question, the "
                "user did not confirm: record nothing and ask no more"
            )

    return {
        "events": events,
        "recorded": recorded,
        "witnessed": witnessed,
        # Every open request got a row, so none of the session's is left open.
        "open": 0,
        "context": ("shipgate: " + "; ".join(lines) + ".") if lines else None,
        **_reply_failure_lines(db_path, events),
    }


def _reply_failure_lines(
    db_path: Path, events: Sequence[Dict[str, Any]]
) -> Dict[str, Optional[str]]:
    """The recorder's context lines for a plan it could not write, or wrote in part (#55).

    ``unwritten`` asks for the go requests again, one printed command per gate of a
    stream the plan touched; ``status_command`` is the status command the line for a
    partial write prints. Both are None when the plan has no rows.
    """
    if not events:
        return {"unwritten": None, "status_command": None}
    pairs: List[Tuple[str, str]] = []
    for event in events:
        pair = (event["stream"], event["data"]["gate"])
        if pair not in pairs:
            pairs.append(pair)
    commands = [
        command for command in (
            _request_command(db_path, stream, gate, GATE_QUESTION_PLACEHOLDER)
            for stream, gate in pairs
        ) if command
    ]
    unwritten = (
        "shipgate: the recorder could not write the user's reply to the journal; "
        "nothing was recorded. Record a go-requested and ask again"
        + (": " + "; ".join(f"`{command}`" for command in commands) if commands else "")
        + "."
    )
    # `--all`: the brief prints only bound streams (ADR 0024), and a go row binds none.
    return {"unwritten": unwritten,
            "status_command": _journal_command(db_path, "status", "--all")}


def _waiting_witness(events: Sequence[Event], gate: str) -> Optional[Event]:
    """The newest witness of a reply that was no exact go at ``gate``, or None (A5).

    It is later than the last ``task-done``, written by the hook, at ``gate`` (or at the
    publish gate, whose go covers a commit). The caller asks only when no go holds.
    """
    last_task_done = max((e.seq for e in events if e.type == "task-done"), default=0)
    gates = ("commit", "publish") if gate == "commit" else (gate,)
    waiting = [
        e for e in events
        if e.type == "reply-witnessed" and e.seq > last_task_done
        and _actor_role(e) == "hook" and e.data.get("gate") in gates
    ]
    return waiting[-1] if waiting else None


AUTHORIZE_SUBAGENT = (
    " You are a subagent: you cannot ask the user. Stop, and hand the question back "
    "to the session that started you; it records the go request and asks."
)


def _hold_message(
    db_path: Path, stream: str, gate: str, witness: Optional[Event]
) -> str:
    word = gate
    if witness is not None:
        return (
            f"shipgate held this {gate}: stream {stream!r} holds no go for the {gate} "
            "gate since its last task-done. The user's reply to the go request was no "
            "exact go. Unless it refused, "
            + _confirm_line(db_path, stream, gate)
            + ". If the user refused or did not confirm, wait for the user. Never record "
            "the go on their behalf."
        )
    command = _request_command(db_path, stream, gate, GATE_QUESTION_PLACEHOLDER)
    request = (
        f"record a go request with `{command}`" if command else
        f"record a go-requested {{\"gate\": \"{gate}\", \"question\": \"...\"}} on the "
        "stream"
    )
    return (
        f"shipgate held this {gate}: stream {stream!r} holds no go for the {gate} gate "
        f"since its last task-done. A ready verdict is no go. Ways forward: {request}, "
        f"then ask with the header `{word.capitalize()}` and `{word.capitalize()}` as "
        f"the first option; or let the user type `{word}`. The user may also approve in "
        f"the shipgate-hud publish dialog or with their own `!` command. Never record "
        f"the go on their behalf."
    )


def authorize(
    conn: sqlite3.Connection, gate: str, branch: str, db_path: Path,
    subagent: bool = False,
) -> Dict[str, Any]:
    """The command gate's answer for a branch (ADR 0023 §14-§16).

    The branch names its stream as ``status`` matches one, live streams first. No stream
    passes (``no-stream``), and so does a finished one (``not-live``). Otherwise the
    user's go for ``gate`` (``user_go``) passes, and its absence holds: ``witness-waits``
    when the user's reply was no exact go and a confirming question is due (#52), ``no-go``
    otherwise. A ready verdict is no go.
    """
    with_events = _fold_work_streams(conn)
    live = [entry["stream"] for entry, _ in with_events if not entry["terminal"]]
    stream = branch_match(branch, live)
    reason = None
    if stream is None:
        stream = branch_match(branch, [entry["stream"] for entry, _ in with_events])
        reason = "not-live" if stream is not None else "no-stream"
    answer: Dict[str, Any] = {"gate": gate, "stream": stream}
    if reason is not None:
        answer.update({"verdict": "pass", "reason": reason, "message": ""})
        return answer
    events = next(e for entry, e in with_events if entry["stream"] == stream)
    go = commit_authorization(events) if gate == "commit" else user_go(events, gate)
    if go["kind"] == "authorized":
        answer.update({
            "verdict": "pass", "reason": "authorized",
            "message": f"the user's go for {gate} on {stream} is seq {go['seq']}",
        })
        return answer
    witness = _waiting_witness(events, gate)
    message = _hold_message(db_path, stream, gate, witness)
    if subagent:
        message += AUTHORIZE_SUBAGENT
    answer.update({
        "verdict": "hold",
        "reason": "witness-waits" if witness is not None else "no-go",
        "message": message,
        # The go request the message prints, or None (#55).
        "request_command": _request_command(
            db_path, stream, gate,
            CONFIRMING_QUESTION_PLACEHOLDER if witness is not None
            else GATE_QUESTION_PLACEHOLDER,
        ),
    })
    return answer
