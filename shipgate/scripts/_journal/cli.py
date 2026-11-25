"""The parser, one function per subcommand, `main`."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, get_args

from .vocab import (
    EVENT_SHAPES, EVENT_VOCABULARY, EXIT_CHECK, EXIT_CONFLICT, EXIT_GATE,
    EXIT_IMPORT_CONFLICT, EXIT_INFRA, EXIT_OK, GateViolation, GoGate, JournalError,
    SCHEMA_VERSION, SESSION_ENV, SIGNALS_MISSING_KIND, UsageError, VersionConflict,
)
from .text import _one_line
from .project import artifact_homes, ledger_summary, Resolution, resolve_db
from .settings import cmd_config, status_settings
from .store import apply_migrations, connect, read_events
from .fold import stream_lifecycle
from .append import append_event, AppendResult
from .status import build_status, render_status
from .reply import authorize, parse_reply_input, plan_reply
from .check import record_check, render_findings, render_skipped, run_check
from .position import _render_position, build_position
from .handoff import build_handoff, NUDGE_EVENTS, nudge_line, render_handoff
from .closeout import (
    apply_sweep, build_closeout, build_sweep, render_closeout, render_sweep,
)
from .stats import build_stats, render_stats
from .doctor import render_doctor, run_doctor
from .transfer import export_events, import_events
from .assumptions import (
    BATCH_CAP, AssumptionError, assumptions_report, render_assumptions,
)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EPILOG = """\
exit codes:
  0  ok
  1  infrastructure failure (database missing or unreadable, IO error,
     `position` on a stream with no events)
  2  usage error
  3  version conflict — a conditional append (--expect) found a different
     current version; nothing was written
  4  gate violation — an append's precondition is unmet; nothing was written
  5  check findings — `check` found missing semantic events
  6  import conflicts — some rows exist with different content and were kept

database resolution:
  --db PATH, else the `db` key of the nearest .claude/shipgate.json sidecar
  from the current directory up to the filesystem root, the walk the hooks
  make (a nested .git is no boundary; relative values resolve against the
  sidecar's project directory, or the main worktree's in a linked worktree
  that carries a committed sidecar), else
  .claude/shipgate.db under the current directory.
"""


def _add_db_flag(parser: argparse.ArgumentParser) -> None:
    """Accept --db after the subcommand too, without clobbering the global one."""
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="path to the journal database (also accepted before the subcommand)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="journal.py",
        description="shipgate flow journal — an append-only SQLite event log.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", metavar="PATH", default=None,
        help="path to the journal database (overrides the sidecar)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    p_init = subparsers.add_parser(
        "init", help="create the schema and stamp meta (idempotent)"
    )
    _add_db_flag(p_init)
    p_init.add_argument("--json", action="store_true", help="machine-readable output")

    p_append = subparsers.add_parser("append", help="append one event")
    _add_db_flag(p_append)
    p_append.add_argument(
        "--stream", required=True,
        help="stream name — the branch, e.g. fix/1290-date-off-by-one",
    )
    p_append.add_argument("--type", default=None, dest="event_type",
                          help="event type, e.g. phase-entered")
    p_append.add_argument("--data", default=None,
                          help="event payload as a JSON object")
    p_append.add_argument("--batch", action="store_true",
                          help="read the events as JSONL on stdin instead of from "
                               "--type/--data — one object per line, "
                               "{\"type\": ..., \"data\": {...}} plus optional "
                               "\"stream\" and \"actor\"; appended in order under one "
                               "connection, all gates applying. The first failure "
                               "stops the batch and the lines before it stay "
                               "written: this is not a transaction")
    p_append.add_argument("--expect", type=int, default=None, metavar="N",
                          help="conditional append: current version must equal N. A "
                               "phase-owning event may also write an implied "
                               "phase-entered, so the version can advance by two — "
                               "read the next expectation off the append's own "
                               "output (--json reports version and version_before) "
                               "rather than assuming N+1")
    p_append.add_argument("--actor", default=None,
                          help="free label: session id, agent, watcher")
    p_append.add_argument("--force", action="store_true",
                          help="skip gate validation (never the --expect check) and "
                               "stamp the event as forced")
    p_append.add_argument("--force-reason", default=None, dest="force_reason",
                          help="reason recorded alongside --force")
    p_append.add_argument("--new-type", action="store_true", dest="new_type",
                          help="mint an event type outside the vocabulary on purpose "
                               "(recorded as new_type; --force does NOT waive this)")
    p_append.add_argument("--json", action="store_true", help="machine-readable output")

    p_vocab = subparsers.add_parser(
        "vocab", help="list the canonical event types append will accept")
    _add_db_flag(p_vocab)
    p_vocab.add_argument("--json", action="store_true", help="machine-readable output")
    p_vocab.add_argument(
        "--shape", nargs="?", const="", default=None, metavar="TYPE",
        help="print one type's canonical payload shape as JSON, or every shape "
             "when given no type",
    )
    p_vocab.set_defaults(func=cmd_vocab)

    p_config = subparsers.add_parser(
        "config",
        help="each setting's resolved value and its source: the project settings file, "
             "the user settings file, a legacy shipgate.md line or the default "
             "(ADR 0028); needs no journal",
    )
    p_config.add_argument("keys", nargs="*", metavar="KEY",
                          help="a setting (orchestration.review) or a group "
                               "(orchestration); all when none")
    p_config.add_argument("--json", action="store_true", help="machine-readable output")
    p_config.add_argument("--start", default=None, metavar="DIR",
                          help="resolve as from DIR (default: the working directory)")
    p_config.set_defaults(func=cmd_config)

    p_assumptions = subparsers.add_parser(
        "assumptions",
        help="parse the tagged lines of a PRD's \"Assumptions (executive)\" section; "
             "--risky gives the batch clarify confirms; needs no journal",
        description="Parse the \"## Assumptions (executive)\" section of a PRD. Each "
                    "item: - [<class>] [blindspot|reference]? [source: <ref>] | "
                    "[no source found in <what>] <question> → <answer> — <rationale> "
                    "<end tag>?",
        epilog="classes: domain, data, behaviour, technical. End tags, exactly: "
               "[kept by the user], [changed by the user, was: <old answer>], "
               "[unconfirmed]. --risky keeps the items with no end tag that are "
               "unsourced domain, data or behaviour items, or [blindspot] or [reference] "
               "candidates whatever their class and source; in file order, at most "
               "--cap (default 4), the rest counted as overflow; the text footer reads "
               "'N to confirm, M over the cap of K'. The section runs from its heading "
               "line to the next '## ' line and holds only assumption lines: items, "
               "their indented continuation lines and blank lines. Exit 2 names "
               "<prd>:<line> of the first bad line: a malformed item, any other line in "
               "the section (prose, a heading, another bullet), an indented list item, a "
               "near-miss end tag, text after the end tag, an unclosed [ in a tag, a ``` "
               "or ~~~ line in the section, or a second section heading. A PRD with no "
               "section lists "
               "nothing and exits 0; the JSON \"section\" says whether the section was "
               "found.",
    )
    p_assumptions.add_argument("prd", metavar="PRD", help="path to the PRD markdown file")
    p_assumptions.add_argument("--risky", action="store_true",
                               help="only the batch to confirm, capped at --cap")
    p_assumptions.add_argument("--cap", type=int, default=None, metavar="N",
                               help="with --risky: the batch size, 0 to 4 (default 4); "
                                    "the dialog slots left after the run's escalations")
    p_assumptions.add_argument("--json", action="store_true",
                               help="machine-readable output")

    p_session = subparsers.add_parser(
        "session",
        help="retired: reads and writes nothing (append reads its session from "
             "CLAUDE_CODE_SESSION_ID only); a later release removes it",
    )
    _add_db_flag(p_session)
    p_session.add_argument("--set", dest="set_id", default=None, metavar="ID",
                           help="ignored (retired)")
    p_session.add_argument("--get", action="store_true", help="ignored (retired)")
    p_session.add_argument("--json", action="store_true",
                           help="machine-readable output")

    p_status = subparsers.add_parser("status", help="status brief per stream")
    _add_db_flag(p_status)
    p_status.add_argument("--feature", default=None, metavar="SLUG",
                          help="restrict to one stream, by slug")
    p_status.add_argument("--branch", default=None, metavar="NAME",
                          help="git branch of the current checkout; the stream it "
                               "names renders first and in full")
    p_status.add_argument("--nested-branch", action="append", default=None,
                          dest="nested_branches", metavar="NAME",
                          help="a branch checked out in a nested repo of an umbrella "
                               "checkout (repeatable); tried only when --branch names "
                               "no stream, and binds only when the nested branches "
                               "name exactly one live stream (nested_matches lists "
                               "the live ones)")
    p_status.add_argument("--session", default=None, metavar="ID",
                          help="a Claude Code session id; the live stream it last "
                               "wrote to itself renders first (session_match), ahead "
                               "of the branch's")
    p_status.add_argument("--all", action="store_true", dest="show_all",
                          help="include completed and abandoned streams")
    p_status.add_argument("--json", action="store_true", help="machine-readable output")

    p_position = subparsers.add_parser(
        "position",
        help="every fact the HUD draws for one stream: phase marks, artifacts, Build "
             "Plan tasks, decisions, verdict (--json is the contract)",
    )
    _add_db_flag(p_position)
    p_position.add_argument("--stream", required=True,
                            help="the exact stream name; one with no events exits 1")
    p_position.add_argument("--json", action="store_true",
                            help="machine-readable output")

    p_handoff = subparsers.add_parser(
        "handoff",
        help="the brief a fresh session continues one stream from: role, phase, "
             "artifacts, next task, open gates, decisions and the config rules that "
             "bind (ADR 0021)",
    )
    _add_db_flag(p_handoff)
    p_handoff.add_argument("--stream", required=True,
                           help="the exact stream name; one with no events exits 1")

    p_nudge = subparsers.add_parser(
        "nudge",
        help="the PostToolUse hook's context nudge: one line past the handoff "
             "threshold after a design-committed or a not-ready review-verdict, else "
             "nothing (ADR 0022)",
    )
    _add_db_flag(p_nudge)
    p_nudge.add_argument("--stream", required=True, help="the stream the append named")
    p_nudge.add_argument("--event", required=True, choices=NUDGE_EVENTS,
                         dest="event_type", help="the boundary event the append wrote")
    p_nudge.add_argument("--tokens", required=True, type=int,
                         help="the session's context size, from its transcript")
    p_nudge.add_argument("--seq", required=True, type=int,
                         help="the seq the append printed; it must be the stream's "
                              "newest event of that type")
    p_nudge.add_argument("--start", default=None, metavar="DIR",
                         help="the session's working directory, where the config "
                              "layers start (default: the current directory); one "
                              "outside the project root reads the root's file only")

    p_stats = subparsers.add_parser(
        "stats", help="per-stream counts: events by role, decisions by mode, sessions"
    )
    _add_db_flag(p_stats)
    p_stats.add_argument("--since", default=None, metavar="ISO",
                         help="only count events recorded at or after this timestamp")
    p_stats.add_argument("--stream", default=None,
                         help="restrict to one stream (the tool's own included)")
    p_stats.add_argument("--json", action="store_true",
                         help="machine-readable output")

    p_check = subparsers.add_parser(
        "check", help="Stop hook gate: find semantic events missing for a session"
    )
    _add_db_flag(p_check)
    p_check.add_argument("--session", required=True, metavar="ID",
                         help="session id (matched against data.session, a user row's "
                              "data.recorded_by, or a machine role's actor label)")
    p_check.add_argument("--json", action="store_true", help="machine-readable output")
    p_check.add_argument("--record", action="store_true",
                         help="stamp this run as the last check (one meta value, no "
                              "event); the Stop hook passes it, `doctor` prints it")

    p_reply = subparsers.add_parser(
        "reply",
        help="the recorder's plan: the go rows and witnesses a user's reply gives "
             "(reads JSON on stdin, writes nothing)",
    )
    _add_db_flag(p_reply)
    p_reply.add_argument("--session", required=True, metavar="ID",
                         help="the session the reply came in")
    p_reply.add_argument("--json", action="store_true", help="machine-readable output")

    p_authorize = subparsers.add_parser(
        "authorize",
        help="the command gate's answer: may a model commit or publish on a branch?",
    )
    _add_db_flag(p_authorize)
    p_authorize.add_argument("--gate", required=True, choices=list(get_args(GoGate)))
    p_authorize.add_argument("--branch", required=True, metavar="NAME",
                             help="the branch the command acts on")
    p_authorize.add_argument("--subagent", action="store_true",
                             help="the command comes from a subagent")
    p_authorize.add_argument("--json", action="store_true",
                             help="machine-readable output")

    p_log = subparsers.add_parser("log", help="raw events, newest last")
    _add_db_flag(p_log)
    p_log.add_argument("--stream", default=None, help="restrict to one stream")
    p_log.add_argument("--limit", type=int, default=None, metavar="N",
                       help="keep only the newest N events")
    p_log.add_argument("--json", action="store_true", help="machine-readable output")

    p_streams = subparsers.add_parser(
        "streams", help="stream names with event counts and max version"
    )
    _add_db_flag(p_streams)
    p_streams.add_argument("--json", action="store_true",
                           help="machine-readable output")
    which = p_streams.add_mutually_exclusive_group()
    which.add_argument("--open", action="store_true", dest="open_only",
                       help="one line per open stream: lifecycle, phase, last event, "
                            "idle days, PR, ownership mark (ADR 0024)")
    which.add_argument("--dormant", action="store_true",
                       help="as --open, the dormant streams only")

    p_closeout = subparsers.add_parser(
        "closeout",
        help="the close-out plan of a merged stream, from observed evidence; writes "
             "nothing (ADR 0025, ADR 0026)",
    )
    _add_db_flag(p_closeout)
    p_closeout.add_argument("--stream", required=True, help="the stream to close")
    p_closeout.add_argument("--observed", default=None, metavar="DIR",
                            help="the directory the observe script filled")

    p_sweep = subparsers.add_parser(
        "sweep",
        help="a disposition for each dormant stream, from observed evidence; --apply "
             "appends the terminal events (ADR 0025)",
    )
    _add_db_flag(p_sweep)
    p_sweep.add_argument("--observed", default=None, metavar="DIR",
                         help="the directory the observe script filled")
    p_sweep.add_argument("--apply", action="store_true",
                         help="append the proposed flow-completed and flow-abandoned")

    p_doctor = subparsers.add_parser("doctor", help="integrity and configuration report")
    _add_db_flag(p_doctor)
    p_doctor.add_argument("--json", action="store_true",
                          help="machine-readable output")

    p_export = subparsers.add_parser("export", help="dump events as JSONL on stdout")
    _add_db_flag(p_export)
    p_export.add_argument("--stream", default=None, help="restrict to one stream")

    p_import = subparsers.add_parser(
        "import", help="merge a JSONL dump by (stream, version); never overwrites"
    )
    _add_db_flag(p_import)
    p_import.add_argument("file", help="JSONL file to import")
    p_import.add_argument("--json", action="store_true",
                          help="machine-readable output")

    return parser


def _refuse_json_constant(literal: str) -> Any:
    """Reject Python's JSON extensions, which no other parser will read back."""
    raise UsageError(
        f"{literal} is not valid JSON — Python accepts the literal but SQLite would "
        "store a row nothing else can parse; send a number or a string"
    )


def parse_batch_records(raw: str) -> List[Tuple[int, Dict[str, Any]]]:
    """Parse ``--batch`` JSONL into ``(line number, record)`` pairs.

    Every line is parsed before any is appended, so a typo on the last line costs
    nothing. Gate refusals are a different matter — those are found one at a time,
    with the lines before them already written.
    """
    records: List[Tuple[int, Dict[str, Any]]] = []
    # An editor or a PowerShell redirect can put a UTF-8 BOM in front of the first
    # line; it belongs to the stream, not to that line's JSON.
    for lineno, line in enumerate(raw.lstrip("﻿").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_refuse_json_constant)
        # Nesting deep enough to exhaust the parser's stack is malformed input, not a
        # crash to hand the caller a traceback for.
        except (ValueError, RecursionError) as exc:
            raise UsageError(f"line {lineno}: not valid JSON ({exc})") from exc
        if not isinstance(record, dict):
            raise UsageError(f"line {lineno}: expected a JSON object")
        event_type = record.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise UsageError(f'line {lineno}: missing "type"')
        if not isinstance(record.get("data", {}), dict):
            raise UsageError(f'line {lineno}: "data" must be a JSON object')
        for key in ("stream", "actor"):
            value = record.get(key)
            if value is not None and not isinstance(value, str):
                raise UsageError(f'line {lineno}: "{key}" must be a string')
        records.append((lineno, record))
    if not records:
        raise UsageError("--batch read no events on stdin")
    return records


def parse_data_argument(raw: Optional[str]) -> Dict[str, Any]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw, parse_constant=_refuse_json_constant)
    except (ValueError, RecursionError) as exc:
        raise UsageError(f"--data is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise UsageError("--data must be a JSON object")
    return parsed


# -- command implementations ------------------------------------------------


def cmd_init(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path, create=True)
    try:
        applied = apply_migrations(conn)
    finally:
        conn.close()
    if getattr(args, "json", False):
        print(json.dumps({
            "db": str(resolution.db_path),
            "schema_version": SCHEMA_VERSION,
            "migrations_applied": applied,
        }, sort_keys=True))
    else:
        detail = (
            f"applied migrations {', '.join(str(a) for a in applied)}"
            if applied else "already up to date"
        )
        print(f"journal ready at {resolution.db_path} ({detail})")
    return EXIT_OK


def _append_summary(
    stream: str, event_type: str, data: Dict[str, Any], result: AppendResult
) -> str:
    if result.duplicate:
        return (f"duplicate {event_type} for {data.get('path')} skipped "
                f"(seq {result.seq})")
    transition = (
        f" (entered {result.implied_phase}, implied)" if result.implied_phase else ""
    )
    line = (f"appended {event_type} to {stream}: "
            f"seq {result.seq}, version {result.version}{transition}")
    if result.deviation_seq is not None:
        line += (f"\nrecorded deviation ({SIGNALS_MISSING_KIND}) to {stream}: "
                 f"seq {result.deviation_seq} — while the stream is still in route-and-map, "
                 "append the map again with `signals` (`signals.py hotspots ... --json`, "
                 "ADR 0011); after it, leave the deviation as the record")
    return line


def _append_payload(
    stream: str, event_type: str, result: AppendResult, line: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "seq": result.seq,
        "version": result.version,
        "version_before": result.version_before,
        "stream": stream,
        "type": event_type,
        "implied_phase": result.implied_phase,
        "duplicate": result.duplicate,
        "deviation_seq": result.deviation_seq,
    }
    if line is not None:
        payload["line"] = line
    return payload


def cmd_append(args, resolution: Resolution) -> int:
    if args.force_reason is not None and not args.force:
        raise UsageError("--force-reason requires --force")
    if args.batch:
        if args.event_type is not None or args.data is not None:
            raise UsageError(
                "--batch takes the events from stdin — drop --type and --data"
            )
        if args.expect is not None:
            raise UsageError(
                "--expect cannot hold across a batch (every line moves the version) "
                "— append that event on its own"
            )
        return _append_batch(args, resolution)
    if args.event_type is None:
        raise UsageError(
            "append needs --type, or --batch to read JSONL events from stdin"
        )
    return _append_one(args, resolution)


def _append_batch(args, resolution: Resolution) -> int:
    """Append a JSONL batch line by line through one connection (FR-012)."""
    records = parse_batch_records(sys.stdin.read())
    results: List[Dict[str, Any]] = []
    failure: Optional[Tuple[int, BaseException]] = None

    conn = connect(resolution.db_path)
    try:
        for lineno, record in records:
            stream = record.get("stream") or args.stream
            event_type = record["type"]
            data = record.get("data") or {}
            try:
                result = append_event(
                    conn,
                    stream=stream,
                    event_type=event_type,
                    data=data,
                    project_dir=resolution.project_dir,
                    actor=record.get("actor") or args.actor,
                    force=args.force,
                    force_reason=args.force_reason,
                    allow_new_type=args.new_type,
                )
            # Any failure, not just a gate refusal: a sqlite error mid-batch must
            # still let the caller see which lines did land, and on which one it
            # stopped, before the exit code says why.
            except Exception as error:
                failure = (lineno, error)
                break
            results.append(_append_payload(stream, event_type, result, line=lineno))
            if not args.json:
                print(_append_summary(stream, event_type, data, result))
    finally:
        conn.close()

    if args.json:
        payload: List[Dict[str, Any]] = list(results)
        if failure is not None:
            payload.append({"error": str(failure[1]), "line": failure[0]})
        print(json.dumps(payload, sort_keys=True))
    if failure is not None:
        print(f"line {failure[0]}: {failure[1]}", file=sys.stderr)
        return getattr(failure[1], "exit_code", EXIT_INFRA)
    return EXIT_OK


def _append_one(args, resolution: Resolution) -> int:
    data = parse_data_argument(args.data)

    conn = connect(resolution.db_path)
    try:
        try:
            result = append_event(
                conn,
                stream=args.stream,
                event_type=args.event_type,
                data=data,
                project_dir=resolution.project_dir,
                expect=args.expect,
                actor=args.actor,
                force=args.force,
                force_reason=args.force_reason,
                allow_new_type=args.new_type,
            )
        except VersionConflict as conflict:
            if args.json:
                print(json.dumps({
                    "error": "version-conflict",
                    "stream": conflict.stream,
                    "expected_version": conflict.expected,
                    "current_version": conflict.current,
                }, sort_keys=True))
            print(str(conflict), file=sys.stderr)
            return EXIT_CONFLICT
        except GateViolation as violation:
            if args.json:
                print(json.dumps({
                    "error": "gate-violation",
                    "stream": args.stream,
                    "type": args.event_type,
                    "reason": str(violation),
                }, sort_keys=True))
            print(f"gate violation: {violation}", file=sys.stderr)
            return EXIT_GATE
    finally:
        conn.close()

    if args.json:
        print(json.dumps(
            _append_payload(args.stream, args.event_type, result), sort_keys=True
        ))
    else:
        print(_append_summary(args.stream, args.event_type, data, result))
    return EXIT_OK


def cmd_vocab(args, resolution: Resolution) -> int:
    shape = getattr(args, "shape", None)
    if shape is not None:
        if shape == "":
            print(json.dumps(EVENT_SHAPES, sort_keys=True))
            return EXIT_OK
        if shape not in EVENT_VOCABULARY:
            raise UsageError(
                f"'{shape}' is not in the event vocabulary — run `journal.py vocab` "
                "for the canonical names"
            )
        print(json.dumps(EVENT_SHAPES.get(shape, {}), sort_keys=True))
        return EXIT_OK
    if args.json:
        print(json.dumps(EVENT_VOCABULARY, sort_keys=True))
        return EXIT_OK
    width = max(len(name) for name in EVENT_VOCABULARY)
    for name, purpose in EVENT_VOCABULARY.items():
        marker = "  [shape]" if name in EVENT_SHAPES else ""
        print(f"  {name:<{width}}  {purpose}{marker}")
    print()
    print("Anything else is refused by `append` — pass --new-type to mint one on purpose.")
    print("[shape] types have a required payload — `vocab --shape <type>` prints it.")
    return EXIT_OK


def cmd_assumptions(args, resolution: Resolution) -> int:
    """Read the PRD as UTF-8 and list its assumption items; reads no journal."""
    cap = BATCH_CAP if args.cap is None else args.cap
    if args.cap is not None and not args.risky:
        raise UsageError("--cap needs --risky")
    if not 0 <= cap <= BATCH_CAP:
        raise UsageError(f"--cap takes an integer from 0 to {BATCH_CAP}, got {cap}")
    try:
        text = Path(args.prd).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
        raise UsageError(f"cannot read {args.prd}: {reason}")
    try:
        report = assumptions_report(args.prd, text, args.risky, cap)
    except AssumptionError as exc:
        raise UsageError(f"{args.prd}:{exc.line}: {exc.reason}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(render_assumptions(report))
    return EXIT_OK


def cmd_session(args, resolution: Resolution) -> int:
    """Retired (#51, ADR 0005 amendment of 2026-11-23): one release of grace for an old
    caller of ``--set`` or ``--get``. It reads no sidecar (``main`` dispatches it before
    ``resolve_db``), opens no journal and writes nothing."""
    if args.json:
        print(json.dumps({"current_session": None, "retired": True}, sort_keys=True))
    else:
        print("journal.py session is retired: no append reads the session that started "
              "last, so this command reads and writes nothing")
    return EXIT_OK


def cmd_authorize(args, resolution: Resolution) -> int:
    """``authorize --gate G --branch B [--subagent] --json``: the command gate's answer.

    Exit 0 for a pass and for a hold; 1 for infrastructure (the hook then passes the
    command, ADR 0023 §15).
    """
    conn = connect(resolution.db_path)
    try:
        answer = authorize(conn, args.gate, args.branch, resolution.db_path,
                           subagent=args.subagent)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(answer, sort_keys=True))
    else:
        print(f"{answer['verdict']} ({answer['reason']})"
              + (f": {answer['message']}" if answer["message"] else ""))
    return EXIT_OK


def cmd_reply(args, resolution: Resolution) -> int:
    """``reply --session ID --json``: the rows a reply gives (ADR 0023 §11).

    Reads the recorder's JSON on stdin and prints the plan. It writes nothing: the
    recorder writes the plan with ``append --batch``. Exit 0, 1 for infrastructure, 2 for
    usage.
    """
    reply = parse_reply_input(sys.stdin.read())
    conn = connect(resolution.db_path)
    try:
        plan = plan_reply(conn, args.session, reply, resolution.db_path)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(plan, sort_keys=True))
    elif plan["context"]:
        print(plan["context"])
    return EXIT_OK


def cmd_status(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        status = build_status(
            conn, args.feature, branch=args.branch, show_all=args.show_all,
            nested_branches=args.nested_branches, session=args.session,
        )
    finally:
        conn.close()
    status["ledger"] = ledger_summary(resolution.project_dir, resolution.sidecar)
    # The settings lines (ADR 0028, M2), resolved from the project root. A value in a
    # settings file never fails this command, because SessionStart runs it; a missing
    # schema is an incomplete install and fails it, as the ledger line already did.
    status.update(status_settings(resolution.project_dir))
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(render_status(status, full=args.show_all or bool(args.feature)))
    return EXIT_OK


def cmd_position(args, resolution: Resolution) -> int:
    """``position --stream <s> [--json]``: ``build_position`` for one stream.

    ``--json`` prints the ``PositionDoc`` with sorted keys: the HUD's only input for the
    stream's position (ADR 0009). Without ``--json`` the output is for people and is no
    contract. A stream with no events exits 1 (``InfraError`` from ``build_position``),
    never 2: exit 2 stays reserved for argparse's usage errors.
    """
    conn = connect(resolution.db_path)
    try:
        position = build_position(
            conn, args.stream, resolution.project_dir,
            artifact_homes(resolution.sidecar),
        )
    finally:
        conn.close()
    if args.json:
        print(json.dumps(position, sort_keys=True))
    else:
        print(_render_position(position))
    return EXIT_OK


def cmd_handoff(args, resolution: Resolution) -> int:
    """``handoff --stream <s>``: ``build_handoff`` as text (ADR 0021). The output is for
    a model and is no contract. A stream with no events exits 1, as ``position``."""
    conn = connect(resolution.db_path)
    try:
        doc = build_handoff(
            conn, args.stream, resolution.project_dir,
            artifact_homes(resolution.sidecar), start=Path.cwd(),
        )
    finally:
        conn.close()
    print(render_handoff(doc))
    return EXIT_OK


def cmd_nudge(args, resolution: Resolution) -> int:
    """``nudge``: print ``nudge_line`` or nothing; exit 0 either way."""
    conn = connect(resolution.db_path)
    try:
        start = Path(args.start) if args.start else Path.cwd()
        line = nudge_line(conn, args.stream, args.event_type, args.tokens, args.seq,
                          resolution.project_dir, start)
    finally:
        conn.close()
    if line:
        print(line)
    return EXIT_OK


def cmd_stats(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        report = build_stats(conn, since=args.since, stream=args.stream,
                             project_dir=resolution.project_dir)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(render_stats(report))
    return EXIT_OK


def cmd_check(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        report = run_check(
            conn,
            session=args.session,
            db_path=resolution.db_path,
            project_dir=resolution.project_dir,
            homes=artifact_homes(resolution.sidecar),
        )
        if args.record:
            record_check(conn, args.session, report)
    finally:
        conn.close()

    findings = report["findings"]
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            render_findings(findings) if findings
            else "no missing semantic events for this session"
        )
        if report["skipped"]:
            print(render_skipped(report["skipped"]))
    return EXIT_CHECK if findings else EXIT_OK


def cmd_log(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        events = read_events(conn, stream=args.stream)
    finally:
        conn.close()
    if args.limit is not None:
        if args.limit < 0:
            raise UsageError("--limit must not be negative")
        events = events[-args.limit:] if args.limit else []
    if args.json:
        print(json.dumps({"events": [e.as_dict() for e in events]}, sort_keys=True))
    elif not events:
        print("no events")
    else:
        for event in events:
            print(f"{event.seq:>5}  {event.ts}  {event.stream} v{event.version}  "
                  f"{event.type}  {json.dumps(event.data, sort_keys=True)}")
    return EXIT_OK


def open_streams(conn: sqlite3.Connection, session: Optional[str],
                 dormant_only: bool = False,
                 now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Each open stream as ``streams --open`` lists it (FR-006), in the brief's order."""
    status = build_status(conn, session=session, now=now)
    rows = []
    for feature in status["features"]:
        lifecycle = stream_lifecycle(bool(feature["terminal"]), feature["age_days"])
        if lifecycle == "terminal" or (dormant_only and lifecycle != "dormant"):
            continue
        rows.append({
            "stream": feature["stream"], "lifecycle": lifecycle,
            "phase": feature["phase"], "last_event": feature["last_event"],
            "idle_days": feature["age_days"], "pull_request": feature["pull_request"],
            "other_session": feature["other_session"],
        })
    return rows


def render_open_stream(row: Dict[str, Any]) -> str:
    """One ``streams --open`` line. Each value is collapsed to one line, so a stream
    name cannot add a line."""
    last = row["last_event"] or {}
    pr = row["pull_request"] or {}
    other = row["other_session"]
    parts = [
        row["stream"], row["lifecycle"], f"phase {row['phase'] or '—'}",
        f"last {last.get('type', '—')} {str(last.get('ts', ''))[:10]}",
        f"idle {'?' if row['idle_days'] is None else row['idle_days']}d",
    ]
    if pr.get("url"):
        parts.append(f"pr {pr['url']}")
    if other:
        parts.append(f"· another session wrote this {other['minutes']}m ago")
    return "  ".join(_one_line(part) for part in parts)


def cmd_streams(args, resolution: Resolution) -> int:
    if args.open_only or args.dormant:
        conn = connect(resolution.db_path)
        try:
            rows = open_streams(conn, os.environ.get(SESSION_ENV) or None,
                                dormant_only=args.dormant)
        finally:
            conn.close()
        if args.json:
            print(json.dumps({"streams": rows}, sort_keys=True))
        elif not rows:
            print("no dormant streams" if args.dormant else "no open streams")
        else:
            for row in rows:
                print(render_open_stream(row))
        return EXIT_OK
    conn = connect(resolution.db_path)
    try:
        rows = conn.execute(
            "SELECT stream, COUNT(*) AS n, MAX(version) AS v FROM events "
            "GROUP BY stream ORDER BY stream"
        ).fetchall()
    finally:
        conn.close()
    streams = [
        {"stream": row["stream"], "events": row["n"], "max_version": row["v"]}
        for row in rows
    ]
    if args.json:
        print(json.dumps({"streams": streams}, sort_keys=True))
    elif not streams:
        print("no streams")
    else:
        for entry in streams:
            print(f"{entry['stream']}  events={entry['events']}  "
                  f"max_version={entry['max_version']}")
    return EXIT_OK


def cmd_closeout(args, resolution: Resolution) -> int:
    """``closeout --stream <s> [--observed <dir>]``: exit 0 for a ready plan or one that
    needs evidence, 4 when the PR/MR did not merge. It writes nothing."""
    conn = connect(resolution.db_path)
    try:
        plan = build_closeout(
            conn, args.stream, resolution.project_dir, resolution.db_path,
            ledger_summary(resolution.project_dir, resolution.sidecar),
            observed=Path(args.observed) if args.observed else None, start=Path.cwd(),
        )
    finally:
        conn.close()
    print(render_closeout(plan))
    return EXIT_GATE if plan["state"] == "not-merged" else EXIT_OK


def cmd_sweep(args, resolution: Resolution) -> int:
    """``sweep [--observed <dir>] [--apply]``: the proposals, or with ``--apply`` the
    appends. ``--apply`` needs ``--observed``."""
    if args.apply and not args.observed:
        raise UsageError("sweep --apply needs --observed <dir>: the evidence it applies")
    conn = connect(resolution.db_path)
    try:
        plan = build_sweep(conn, resolution.project_dir, resolution.db_path,
                           observed=Path(args.observed) if args.observed else None,
                           start=Path.cwd())
        if args.apply:
            print("\n".join(apply_sweep(conn, plan, resolution.project_dir)))
            return EXIT_OK
    finally:
        conn.close()
    print(render_sweep(plan))
    return EXIT_OK


def cmd_doctor(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        report = run_doctor(conn, resolution)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(render_doctor(report, resolution.project_dir))
    if report["integrity_check"] != "ok":
        print("integrity check failed — the database is corrupt", file=sys.stderr)
        return EXIT_INFRA
    return EXIT_OK


def cmd_export(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        export_events(conn, args.stream, sys.stdout)
    finally:
        conn.close()
    return EXIT_OK


def cmd_import(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        summary = import_events(conn, Path(args.file).expanduser())
    finally:
        conn.close()

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"imported {summary['imported']}, skipped {summary['skipped']}, "
              f"conflicts {summary['conflicts']}")
    for conflict in summary["conflict_details"]:
        print(
            f"conflict: {conflict['stream']} v{conflict['version']} "
            f"{conflict['reason']} — kept the existing row",
            file=sys.stderr,
        )
    return EXIT_IMPORT_CONFLICT if summary["conflicts"] else EXIT_OK


COMMANDS = {
    "init": cmd_init,
    "vocab": cmd_vocab,
    "config": cmd_config,
    "assumptions": cmd_assumptions,
    "append": cmd_append,
    "session": cmd_session,
    "status": cmd_status,
    "position": cmd_position,
    "handoff": cmd_handoff,
    "nudge": cmd_nudge,
    "stats": cmd_stats,
    "check": cmd_check,
    "reply": cmd_reply,
    "authorize": cmd_authorize,
    "log": cmd_log,
    "streams": cmd_streams,
    "closeout": cmd_closeout,
    "sweep": cmd_sweep,
    "doctor": cmd_doctor,
    "export": cmd_export,
    "import": cmd_import,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # `vocab` is static reference data — it must answer even where no journal
        # exists, since the likeliest moment to ask "what are the names?" is before
        # a project has one. The retired `session` reads nothing, not even a sidecar.
        # `config` reads the settings files and the config, never the journal.
        # `assumptions` reads one PRD file, never the journal.
        if args.command in ("vocab", "session", "config", "assumptions"):
            return COMMANDS[args.command](args, None)
        resolution = resolve_db(getattr(args, "db", None), Path.cwd())
        return COMMANDS[args.command](args, resolution)
    except JournalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except sqlite3.Error as exc:
        print(f"error: sqlite failure: {exc}", file=sys.stderr)
        return EXIT_INFRA
    except BrokenPipeError:
        return EXIT_OK
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INFRA
