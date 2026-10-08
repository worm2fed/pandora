#!/usr/bin/env python3
"""shipgate flow journal — an append-only SQLite event log.

Python 3 standard library only, no dependencies. See
``shipgate/docs/prd/journal.md`` and ``journal.worklog.md`` for the design.

Exit codes (also printed by ``--help``):

    0  ok
    1  infrastructure failure (db missing/unreadable, IO error)
    2  usage error
    3  version conflict (conditional append lost the race)
    4  gate violation (an append's precondition is unmet)
    5  check findings (missing semantic events)
    6  import conflicts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (
    Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INFRA = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_GATE = 4
EXIT_CHECK = 5
EXIT_IMPORT_CONFLICT = 6

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

SIDECAR_RELPATH = os.path.join(".claude", "shipgate.json")
DEFAULT_DB_RELPATH = os.path.join(".claude", "shipgate.db")

PHASE_ORDER = [
    "workspace",
    "route-and-map",
    "explore",
    "clarify",
    "design",
    "implement",
    "review",
    "capture",
]

FEATURE_STREAM_PREFIX = "feature/"
NEEDS_CLARIFICATION = "[NEEDS CLARIFICATION]"

DEFAULT_ARTIFACT_HOMES = {
    "prd": "docs/prd/*.md",
    "adr": "docs/adr/*.md",
    "worklog": "docs/prd/*.worklog.md",
}

# The canonical event vocabulary — the single source of truth. Skills quote these names;
# the gates key off them exactly. An event whose type is not here is inert: it records
# something, but no gate, fold, or report will ever look at it, which is a worse outcome
# than not recording at all because it reads as success. So `append` refuses an unlisted
# type and points at the nearest candidates; `--new-type` mints one deliberately.
EVENT_VOCABULARY: Dict[str, str] = {
    # lifecycle of a piece of work
    "flow-started": "work began — request and branch",
    "phase-entered": "moved into a phase",
    "deviation": "diverged from the plan, or corrected an earlier record",
    "flow-suspended": "work parked",
    "flow-resumed": "work picked back up",
    "flow-completed": "work finished — capture done, stream leaves the brief",
    "flow-abandoned": "work dropped for good",
    # gates and decisions
    "gate-decision": "a decision taken at a gate (this is the one for 'decision')",
    "clarify-passed": "the clarify gate closed — PRD has no open questions",
    "design-committed": "design + build plan landed",
    "design-queued": "a design parked for a later child issue",
    "design-invalidated": "a queued design broken by what merged",
    # building
    "task-done": "a build-plan task completed",
    "verify-run": "evidence from a verification run (this is the one for 'verify-passed')",
    # debugging
    "bug-reproduced": "the defect was reproduced — expected vs actual",
    "debug-root-cause": "root cause established, with the evidence for it",
    # review and delivery
    "review-verdict": "review concluded",
    "mr-opened": "an MR/PR was opened",
    "review-feedback": "reviewer feedback arrived",
    "capture-done": "ledger triaged, learnings promoted or dropped",
    # written by hooks and setup, not by a skill
    "artifact-written": "an artifact file changed (hook-written)",
    "session-started": "a session began (hook-written)",
    "session-ended": "a session ended (hook-written)",
    "gate-blocked": "Stop hook blocked a session over missing events (hook-written)",
    "setup-completed": "setup created or updated this project",
    "schema-migrated": "the journal schema moved version",
    "imported": "events were imported from a JSONL export",
    # MR-watcher streams
    "baseline": "watcher's first observation of an MR",
    "pipeline-flip": "CI status changed",
    "comments-added": "new reviewer comments",
    "merge-status": "mergeability changed",
    "conflicts": "conflicts appeared",
    "approved": "the MR was approved",
    "merged": "the MR merged",
    "closed": "the MR closed unmerged",
}

# The payload shape each type must satisfy — the counterpart to the vocabulary above:
# the vocabulary makes an event *findable*, the shape makes it *readable*. A type absent
# here has no shape on purpose (hook and watcher payloads answer to their writer, not to
# a gate). Per type:
#   required      keys that must be present
#   enums         key -> the only values accepted for it
#   lists         keys whose value must be a JSON list
#   aliases       old key -> canonical key, renamed before validation
#   value_aliases key -> {old value: canonical value}
#   defaults      key -> value filled in when absent
EVENT_SHAPES: Dict[str, Dict[str, Any]] = {
    "flow-started": {"required": ["request"]},
    "phase-entered": {"required": ["phase"]},
    "deviation": {
        "required": ["note"],
        "aliases": {"correction": "note", "what": "note"},
    },
    "gate-decision": {
        "required": ["gate", "question", "decision", "mode"],
        "enums": {
            "mode": ["ask", "executive"],
            "raised_by": ["user", "orchestrator"],
        },
        "aliases": {"chosen": "decision", "kind": "gate"},
        "defaults": {"raised_by": "orchestrator"},
    },
    "clarify-passed": {"required": ["prd"]},
    "design-committed": {"required": ["worklog"]},
    "task-done": {"required": ["task_id"]},
    "verify-run": {
        "required": ["outcome", "task_ids"],
        "enums": {"outcome": ["pass", "fail"]},
        "lists": ["task_ids"],
        "aliases": {"result": "outcome", "tasks": "task_ids"},
    },
    "review-verdict": {
        "required": ["verdict"],
        "enums": {"verdict": ["ready", "not-ready"]},
        "value_aliases": {"verdict": {"pass": "ready", "fail": "not-ready"}},
    },
    "capture-done": {
        "required": ["promoted", "dropped"],
        "lists": ["promoted", "dropped"],
    },
}

# Events that can only happen inside one phase, so appending one *is* entering it.
# ADR 0002: `append` records the transition rather than refusing the event.
PHASE_OF_EVENT: Dict[str, str] = {
    "clarify-passed": "clarify",
    "design-committed": "design",
    "design-queued": "design",
    "verify-run": "implement",
    "task-done": "implement",
    "review-verdict": "review",
    "capture-done": "capture",
}

# `actor` is `role[@label]` (ADR 0003) — the role says who decided, the label which
# session or agent.
ACTOR_ROLES = ("orchestrator", "worker", "user", "hook", "watcher")

# Types after which a stream has nothing left to report.
TERMINAL_TYPES = ("flow-completed", "flow-abandoned")

# A finished stream reopens only on an event that says work restarted. A late
# `deviation`, or a hook's `artifact-written` on a file someone reread, leaves it
# finished — otherwise a stream could never leave the brief for good.
REVIVING_TYPES = frozenset(
    {"flow-started", "flow-resumed", "phase-entered", *PHASE_OF_EVENT}
)

# Roles whose label is never a session id. The watcher runs outside any Claude session,
# so `meta.current_session` would attribute its events to whoever started a session last;
# a `user` label names a person, which is why `stats` drops the role from its session
# count — defaulting a session id in would put it back and inflate that count.
SESSIONLESS_ROLES = frozenset({"watcher", "user"})

# Claude Code sets this in every shell it starts, subagents' included (they get the
# parent's id). It names the session that is appending, where `meta.current_session`
# names only the one that started last — two sessions open on one project would
# otherwise label each other's events.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

# A `capture-done` with nothing after it is a flow that ended without saying so; give
# it two days in case review feedback lands, then treat it as finished.
CAPTURE_TERMINAL_HOURS = 48
DORMANT_DAYS = 7
# The brief is injected into every session, so it pays for the last few decisions per
# stream, not for all of them, and never for a line that wraps a terminal three times.
# The stream matching the current branch is the work being resumed, so it gets the full
# five; the others are context and get three.
BRIEF_DECISION_LIMIT = 5
BRIEF_DECISION_LIMIT_OTHER = 3
BRIEF_TASK_IDS = 5
BRIEF_LINE_CHARS = 160

# The journal records state and evidence pointers; the worklog, PRD and ADRs hold the
# prose. A payload past this is a document being pasted into an event, at the writer's
# token expense on every brief that reprints it.
PAYLOAD_CAP_BYTES = 1024

# One file write reaches the journal twice — PostToolUse sees the tool call, FileChanged
# sees the same bytes land — so an `artifact-written` repeating a path at the same mtime
# this recently is the second hook, not a second write.
ARTIFACT_DEDUPE_SECONDS = 5.0

# Streams the tool owns. Everything else is a work stream — named for its branch
# (`fix/1290-…`) or its feature slug, both of which are legitimate.
META_STREAM = "shipgate"
WATCH_STREAM_PREFIX = "watch/"

DEFAULT_LEDGER = "docs/ledger.md"
# The knowledge-base skill's own threshold for nudging about an un-triaged ledger.
LEDGER_NUDGE_THRESHOLD = 15

_TICKED_TASK_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(T\d+)\b", re.MULTILINE)
_BUILD_PLAN_RE = re.compile(r"^(#+)\s*Build Plan\s*$", re.MULTILINE | re.IGNORECASE)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class JournalError(Exception):
    """Base error carrying the process exit code to use."""

    exit_code = EXIT_INFRA


class InfraError(JournalError):
    exit_code = EXIT_INFRA


class UsageError(JournalError):
    exit_code = EXIT_USAGE


class GateViolation(JournalError):
    exit_code = EXIT_GATE


class VersionConflict(JournalError):
    exit_code = EXIT_CONFLICT

    def __init__(self, stream: str, expected: int, current: int) -> None:
        super().__init__(
            f"version conflict on stream {stream!r}: expected version {expected}, "
            f"current version is {current}"
        )
        self.stream = stream
        self.expected = expected
        self.current = current


# --------------------------------------------------------------------------
# Database resolution
# --------------------------------------------------------------------------


class Sidecar(NamedTuple):
    path: Path
    project_dir: Path
    config: Dict[str, Any]


class Resolution(NamedTuple):
    db_path: Path
    sidecar: Optional[Sidecar]
    project_dir: Path
    source: str  # "flag" | "sidecar" | "default"


def find_sidecar(start_dir: Path) -> Optional[Sidecar]:
    """Look for ``.claude/shipgate.json`` in start_dir, then upward to the git root."""
    current = start_dir.resolve()
    while True:
        candidate = current / SIDECAR_RELPATH
        if candidate.is_file():
            return _load_sidecar(candidate, current)
        if (current / ".git").exists():
            return None
        if current.parent == current:
            return None
        current = current.parent


def _load_sidecar(path: Path, project_dir: Path) -> Sidecar:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InfraError(f"cannot read sidecar {path}: {exc}") from exc
    try:
        config = json.loads(raw)
    except ValueError as exc:
        raise InfraError(f"sidecar {path} is not valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise InfraError(f"sidecar {path} must contain a JSON object")
    return Sidecar(path=path, project_dir=project_dir, config=config)


def _resolve_against(base: Path, value: str) -> Path:
    # `base / absolute` yields the absolute path, so this handles both cases;
    # resolve() normalizes symlinked parents so db paths compare equal.
    return (base / Path(value).expanduser()).resolve()


def resolve_db(db_flag: Optional[str], cwd: Path) -> Resolution:
    """Work out which database to use.

    ``--db`` wins. Otherwise the sidecar's ``db`` key, with relative values
    resolved against the sidecar's *project directory* (never the cwd, because
    hooks invoke this script from arbitrary directories). Otherwise the default
    ``.claude/shipgate.db`` under the cwd.
    """
    sidecar = find_sidecar(cwd)
    project_dir = sidecar.project_dir if sidecar else cwd.resolve()

    if db_flag:
        # resolve() (not absolute()) so a path reached through a symlinked parent
        # — /tmp -> /private/tmp on macOS — still compares equal to the sidecar's.
        return Resolution(
            db_path=Path(db_flag).expanduser().resolve(),
            sidecar=sidecar,
            project_dir=project_dir,
            source="flag",
        )

    if sidecar is not None:
        declared = sidecar.config.get("db")
        if isinstance(declared, str) and declared:
            return Resolution(
                db_path=_resolve_against(sidecar.project_dir, declared),
                sidecar=sidecar,
                project_dir=project_dir,
                source="sidecar",
            )

    return Resolution(
        db_path=(cwd / DEFAULT_DB_RELPATH).resolve(),
        sidecar=sidecar,
        project_dir=project_dir,
        source="default",
    )


def sidecar_db_path(sidecar: Sidecar) -> Optional[Path]:
    declared = sidecar.config.get("db")
    if isinstance(declared, str) and declared:
        return _resolve_against(sidecar.project_dir, declared)
    return None


def ledger_summary(
    project_dir: Path, sidecar: Optional[Sidecar]
) -> Dict[str, Any]:
    """How many untriaged entries the ledger is holding.

    The ledger is a staging inbox the knowledge-base skill drains at triage, so a
    non-zero count is normal mid-flow and an empty ledger is the healthy end state —
    this is information, never a gate. It is surfaced because that skill asks for a
    nudge past ~15 unpromoted entries, and counting lines is a job for a script rather
    than for a model's attention.
    """
    declared = None
    if sidecar is not None:
        value = sidecar.config.get("ledger")
        if isinstance(value, str) and value:
            declared = value
    relative = declared or DEFAULT_LEDGER
    path = _resolve_against(project_dir, relative)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"path": relative, "exists": False, "entries": 0, "nudge": False}
    entries = count_ledger_entries(text)
    return {
        "path": relative,
        "exists": True,
        "entries": entries,
        "nudge": entries >= LEDGER_NUDGE_THRESHOLD,
    }


def count_ledger_entries(text: str) -> int:
    """Count markdown list items — the ledger's "one dated line per entry" shape."""
    return sum(
        1 for line in text.splitlines()
        if re.match(r"\s*[-*+]\s+\S", line)
    )


def artifact_homes(sidecar: Optional[Sidecar]) -> Dict[str, str]:
    if sidecar is None:
        return dict(DEFAULT_ARTIFACT_HOMES)
    homes = sidecar.config.get("artifact_homes")
    if not isinstance(homes, dict):
        return dict(DEFAULT_ARTIFACT_HOMES)
    merged = dict(DEFAULT_ARTIFACT_HOMES)
    for key, value in homes.items():
        if isinstance(value, str):
            merged[key] = value
    return merged


# --------------------------------------------------------------------------
# Connection + schema
# --------------------------------------------------------------------------


def connect(db_path: Path, create: bool = False) -> sqlite3.Connection:
    if not create and not db_path.exists():
        raise InfraError(
            f"journal database not found at {db_path}. "
            "Run `journal.py init` (or pass --db) to create it."
        )
    if create:
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InfraError(f"cannot create {db_path.parent}: {exc}") from exc
    try:
        # isolation_level=None -> autocommit; every write uses an explicit
        # BEGIN IMMEDIATE below.
        conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_MS / 1000.0,
                               isolation_level=None)
    except sqlite3.Error as exc:
        raise InfraError(f"cannot open {db_path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        # WAL needs working fcntl locks and shared memory, which a bind mount into a
        # container (Docker Desktop on macOS especially) does not provide — opening this
        # db from inside one fails immediately with "disk I/O error". WAL is a property
        # of the *file*, not of the connection, so that damage outlives the container:
        # recovery is `PRAGMA journal_mode=DELETE` from the host. Hence the rule that the
        # journal is host-local and never mounted in. `doctor` reports the current mode.
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error as exc:
        raise InfraError(f"cannot configure {db_path}: {exc}") from exc
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def read_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "meta"):
        return 0
    value = get_meta(conn, "schema_version")
    return int(value) if value else 0


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def current_session(conn: sqlite3.Connection) -> Optional[str]:
    """The session id the SessionStart hook stored, if any (ADR 0003)."""
    if not _table_exists(conn, "meta"):
        return None
    return get_meta(conn, "current_session") or None


def set_current_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Record the session id (ADR 0003). One statement, so no explicit transaction."""
    if not _table_exists(conn, "meta"):
        raise InfraError(
            "this journal has no meta table, so the session cannot be recorded — "
            "run `journal.py init`"
        )
    _set_meta(conn, "current_session", session_id)


def parse_actor(
    raw: Optional[str],
    conn: sqlite3.Connection,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """Canonicalize ``--actor`` to ``role[@label]`` (ADR 0003).

    An event that already names its session in the payload — every hook-written one —
    keeps the bare role, so the two never disagree about which session it was.
    """
    role, separator, label = (raw or "orchestrator").partition("@")
    if role not in ACTOR_ROLES:
        raise UsageError(
            f"actor role {role!r} is not one of {', '.join(ACTOR_ROLES)} — "
            "pass `role` or `role@label` (label = session id, agent, watcher)"
        )
    if separator and label:
        return f"{role}@{label}"
    if role in SESSIONLESS_ROLES:
        return role
    if isinstance(data, dict):
        session = data.get("session")
        if isinstance(session, str) and session:
            return role
    session_id = os.environ.get(SESSION_ENV, "").strip() or current_session(conn)
    return f"{role}@{session_id}" if session_id else role


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _migrate_to_1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          seq     INTEGER PRIMARY KEY AUTOINCREMENT,
          stream  TEXT    NOT NULL,
          version INTEGER NOT NULL,
          type    TEXT    NOT NULL,
          data    TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(data)),
          ts      TEXT    NOT NULL,
          actor   TEXT,
          UNIQUE (stream, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, seq)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    _set_meta(conn, "schema_version", "1")
    _set_meta(conn, "created_at", utc_now())
    _set_meta(conn, "plugin_version", plugin_version())


MIGRATIONS = [(1, _migrate_to_1)]


def pending_migrations(conn: sqlite3.Connection) -> List[int]:
    current = read_schema_version(conn)
    return [version for version, _ in MIGRATIONS if version > current]


def apply_migrations(conn: sqlite3.Connection) -> List[int]:
    """Bring the schema up to date. Idempotent; never destroys data."""
    applied: List[int] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = read_schema_version(conn)
        for version, migrate in MIGRATIONS:
            if version > current:
                migrate(conn)
                applied.append(version)
        if applied and applied != [1]:
            _set_meta(conn, "schema_version", str(max(applied)))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return applied


def plugin_version() -> str:
    manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    version = payload.get("version")
    return str(version) if version else "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Event reading
# --------------------------------------------------------------------------


class Event(NamedTuple):
    seq: int
    stream: str
    version: int
    type: str
    data: Dict[str, Any]
    ts: str
    actor: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "stream": self.stream,
            "version": self.version,
            "type": self.type,
            "data": self.data,
            "ts": self.ts,
            "actor": self.actor,
        }


def _row_to_event(row: sqlite3.Row) -> Event:
    try:
        data = json.loads(row["data"])
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return Event(
        seq=row["seq"],
        stream=row["stream"],
        version=row["version"],
        type=row["type"],
        data=data,
        ts=row["ts"],
        actor=row["actor"],
    )


def read_events(
    conn: sqlite3.Connection,
    stream: Optional[str] = None,
    types: Optional[Sequence[str]] = None,
) -> List[Event]:
    query = "SELECT seq, stream, version, type, data, ts, actor FROM events"
    clauses: List[str] = []
    params: List[Any] = []
    if stream is not None:
        clauses.append("stream = ?")
        params.append(stream)
    if types:
        clauses.append("type IN (%s)" % ",".join("?" for _ in types))
        params.extend(types)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY seq"
    return [_row_to_event(row) for row in conn.execute(query, params)]


def current_version(conn: sqlite3.Connection, stream: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS v FROM events WHERE stream = ?", (stream,)
    ).fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


def list_streams(conn: sqlite3.Connection) -> List[str]:
    return [
        row["stream"]
        for row in conn.execute("SELECT DISTINCT stream FROM events ORDER BY stream")
    ]


# --------------------------------------------------------------------------
# Gate validation (rules v1)
# --------------------------------------------------------------------------


def _resolve_artifact(project_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_dir / candidate


def _validate_clarify_passed(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any], project_dir: Path
) -> None:
    prd = data.get("prd")
    if not isinstance(prd, str) or not prd:
        raise GateViolation(
            "clarify-passed requires data.prd naming the PRD file that was cleared"
        )
    path = _resolve_artifact(project_dir, prd)
    if not path.is_file():
        raise GateViolation(f"clarify-passed: PRD not found at {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InfraError(f"cannot read PRD {path}: {exc}") from exc
    count = text.count(NEEDS_CLARIFICATION)
    if count:
        raise GateViolation(
            f"clarify-passed: {path} still contains {count} "
            f"{NEEDS_CLARIFICATION} marker(s)"
        )


def _passing_verify_runs(conn: sqlite3.Connection, stream: str) -> List[Event]:
    return [
        event
        for event in read_events(conn, stream=stream, types=("verify-run",))
        if event.data.get("outcome") == "pass"
    ]


def _validate_task_done(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise GateViolation("task-done requires data.task_id")
    for event in _passing_verify_runs(conn, stream):
        task_ids = event.data.get("task_ids")
        if isinstance(task_ids, list) and task_id in task_ids:
            return
    raise GateViolation(
        f"task-done {task_id}: no prior verify-run with outcome=pass in stream "
        f"{stream!r} names it in data.task_ids"
    )


def _validate_phase_entered(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    phase = data.get("phase")
    if not isinstance(phase, str) or not phase:
        raise GateViolation("phase-entered requires data.phase")
    if phase not in PHASE_ORDER:
        raise GateViolation(
            f"phase-entered: unknown phase {phase!r}; declared order is "
            + ", ".join(PHASE_ORDER)
        )
    target = PHASE_ORDER.index(phase)

    recorded = folded_phase(conn, stream)
    previous = PHASE_ORDER.index(recorded) if recorded is not None else -1

    # Backward and same-phase transitions are always legal (review -> implement
    # is a normal loop). So is a single step forward.
    if target - previous <= 1:
        return

    intervening = PHASE_ORDER[previous + 1: target]
    declared = data.get("skipped")
    declared_set = set(declared) if isinstance(declared, list) else set()
    unnamed = [name for name in intervening if name not in declared_set]
    if unnamed:
        # A stream whose only recorded phase is unusable folds to None, which reads as
        # "nothing recorded" and turns any append into a jump from the start. Say which
        # spelling was ignored, or the refusal looks like a bug in the caller.
        spelled = _last_phase_spelling(conn, stream) if recorded is None else None
        raise GateViolation(
            "phase-entered {target}: forward jump skips {n} phase(s); list them in "
            "data.skipped. Missing: {missing}{hint}".format(
                target=phase,
                n=len(intervening),
                missing=", ".join(unnamed),
                hint=(
                    f" (the last recorded phase-entered spelled it {spelled!r}, "
                    "which is not in the declared order)"
                ) if spelled is not None else "",
            )
        )


def _validate_review_verdict(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    if data.get("verdict") != "ready":
        return
    task_dones = read_events(conn, stream=stream, types=("task-done",))
    last_task_done_seq = max((e.seq for e in task_dones), default=0)
    for event in _passing_verify_runs(conn, stream):
        if event.seq > last_task_done_seq:
            return
    raise GateViolation(
        "review-verdict=ready requires a verify-run with outcome=pass recorded after "
        f"the last task-done in stream {stream!r}"
    )


def _authorizes_publish(data: Dict[str, Any]) -> bool:
    """Whether a ``gate-decision`` is the deliberate call to publish.

    All three conditions matter: the orchestrator can raise a publish gate and answer
    it itself, so a decision that only *sits at* the gate — or records "no" there —
    would otherwise let the flow authorize its own MR.
    """
    return (
        data.get("gate") == "publish"
        and data.get("raised_by") == "user"
        and str(data.get("decision")).strip().lower() == "publish"
    )


def _validate_mr_opened(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    task_dones = read_events(conn, stream=stream, types=("task-done",))
    last_task_done_seq = max((e.seq for e in task_dones), default=0)
    for event in read_events(
        conn, stream=stream, types=("review-verdict", "gate-decision")
    ):
        if event.seq <= last_task_done_seq:
            continue
        if event.type == "review-verdict" and event.data.get("verdict") == "ready":
            return
        if event.type == "gate-decision" and _authorizes_publish(event.data):
            return
    raise GateViolation(
        f"mr-opened in stream {stream!r} needs, recorded after the last task-done, "
        "either a review-verdict with verdict=ready, or a gate-decision with "
        "gate=publish, raised_by=user and decision=publish — record the review's "
        "outcome, take the publish decision with the user, or append with --force "
        "and a reason"
    )


def suggest_event_types(event_type: str) -> List[str]:
    """Candidate canonical names for an unrecognized type.

    Textual similarity alone is not enough: `decision` and `verify-passed` are near
    misses of real names, but `workspace-ready` shares no substring with
    `flow-started` even though it means it. So this offers word-overlap matches where
    they exist and falls back to naming the whole vocabulary — the point is to get the
    caller to the right name, not to be clever.
    """
    from difflib import get_close_matches

    known = list(EVENT_VOCABULARY)
    close = get_close_matches(event_type, known, n=3, cutoff=0.5)
    words = {w for w in re.split(r"[-_]", event_type.lower()) if w}
    for candidate in known:
        if candidate in close:
            continue
        if words & {w for w in candidate.split("-") if w}:
            close.append(candidate)
    return close[:4]


def normalize_payload(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a payload to its canonical shape, or refuse it.

    Aliases are renamed and defaults filled before anything is checked, so a caller
    using an older spelling is corrected rather than rejected. What is left must
    satisfy the required keys, the enums and the list types — a gate reading
    ``data.outcome`` cannot do its job on a payload that spells it ``result``.

    Two keys that mean the same thing are refused rather than resolved: silently
    dropping one of them would discard a value the caller meant to record, and there
    is no way to tell which of the two they meant.
    """
    shape = EVENT_SHAPES.get(event_type)
    if not shape:
        return dict(data)

    aliases = shape.get("aliases", {})
    payload: Dict[str, Any] = {}
    written_by: Dict[str, str] = {}
    for key, value in data.items():
        canonical = aliases.get(key, key)
        if canonical in written_by:
            raise GateViolation(
                f"{event_type}: data.{written_by[canonical]} and data.{key} both "
                f"mean {canonical!r} — send one of them"
                + _shape_hint(event_type)
            )
        written_by[canonical] = key
        payload[canonical] = value
    for key, mapping in shape.get("value_aliases", {}).items():
        value = payload.get(key)
        if isinstance(value, str) and value in mapping:
            payload[key] = mapping[value]
    for key, value in shape.get("defaults", {}).items():
        payload.setdefault(key, value)

    missing = [
        key for key in shape.get("required", []) if payload.get(key) in (None, "")
    ]
    if missing:
        raise GateViolation(
            f"{event_type} is missing required data key(s): {', '.join(missing)}"
            + _shape_hint(event_type)
        )
    for key in shape.get("lists", []):
        if key in payload and not isinstance(payload[key], list):
            raise GateViolation(
                f"{event_type}: data.{key} must be a list" + _shape_hint(event_type)
            )
    for key, allowed in shape.get("enums", {}).items():
        if key in payload and payload[key] not in allowed:
            raise GateViolation(
                f"{event_type}: data.{key} must be one of "
                f"{', '.join(str(a) for a in allowed)}, got {payload[key]!r}"
                + _shape_hint(event_type)
            )
    return payload


def _shape_hint(event_type: str) -> str:
    return (
        f" — canonical shape (`journal.py vocab --shape {event_type}`): "
        + json.dumps(EVENT_SHAPES[event_type], sort_keys=True)
    )


def check_payload_size(
    stream: str,
    payload: Dict[str, Any],
    force: bool = False,
    force_reason: Optional[str] = None,
) -> None:
    """Refuse a payload carrying prose rather than a pointer to it (FR-013).

    Hook and watcher streams are exempt: their payloads are machine-sized already and
    nobody reads them in the brief. ``--force`` waives the cap only with a reason —
    every brief from here on reprints those bytes, so the waiver has to say why.
    """
    if not is_work_stream(stream):
        return
    size = len(json.dumps(payload, sort_keys=True).encode())
    if size <= PAYLOAD_CAP_BYTES:
        return
    if not force:
        raise GateViolation(
            f"payload is {size} bytes (cap {PAYLOAD_CAP_BYTES}): the worklog/PRD/ADR "
            "holds the prose, the event holds `refs` and one sentence — or --force "
            "with a reason"
        )
    if not force_reason:
        raise UsageError(
            f"--force on a {size}-byte payload (cap {PAYLOAD_CAP_BYTES}) needs "
            "--force-reason saying why the prose belongs in the event"
        )


def validate_event_type(event_type: str, allow_new: bool) -> None:
    """Refuse a type outside the vocabulary unless it is being minted deliberately."""
    if allow_new or event_type in EVENT_VOCABULARY:
        return
    suggestions = suggest_event_types(event_type)
    hint = (
        "closest canonical names: " + ", ".join(suggestions)
        if suggestions
        else "see `journal.py vocab` for the full list"
    )
    raise GateViolation(
        f"'{event_type}' is not in the event vocabulary, so no gate or report would "
        f"ever read it — {hint}. Run `journal.py vocab` to see them all, or pass "
        f"--new-type to mint '{event_type}' on purpose."
    )


def validate_gate(
    conn: sqlite3.Connection,
    stream: str,
    event_type: str,
    data: Dict[str, Any],
    project_dir: Path,
) -> None:
    """Raise GateViolation when an append's precondition is unmet."""
    if event_type == "clarify-passed":
        _validate_clarify_passed(conn, stream, data, project_dir)
    elif event_type == "task-done":
        _validate_task_done(conn, stream, data)
    elif event_type == "phase-entered":
        _validate_phase_entered(conn, stream, data)
    elif event_type == "review-verdict":
        _validate_review_verdict(conn, stream, data)
    elif event_type == "mr-opened":
        _validate_mr_opened(conn, stream, data)


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


class AppendResult(NamedTuple):
    seq: int
    version: int
    implied_phase: Optional[str] = None
    duplicate: bool = False
    # The version `--expect` was compared against, so a caller that lost a race can
    # see what it was actually holding.
    version_before: int = 0


def _last_phase_spelling(conn: sqlite3.Connection, stream: str) -> Optional[str]:
    """The newest ``phase-entered``'s ``phase`` as written, in or out of the order."""
    for event in reversed(read_events(conn, stream=stream, types=("phase-entered",))):
        candidate = event.data.get("phase")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def folded_phase(conn: sqlite3.Connection, stream: str) -> Optional[str]:
    """The phase a stream's ``phase-entered`` history leaves it in."""
    phase: Optional[str] = None
    for event in read_events(conn, stream=stream, types=("phase-entered",)):
        candidate = event.data.get("phase")
        if candidate in PHASE_ORDER:
            phase = candidate
    return phase


def _parse_ts(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        recorded = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return recorded if recorded.tzinfo else recorded.replace(tzinfo=timezone.utc)


def _seconds_since(ts: str, now: Optional[datetime] = None) -> Optional[float]:
    recorded = _parse_ts(ts)
    if recorded is None:
        return None
    return ((now or datetime.now(timezone.utc)) - recorded).total_seconds()


def _recent_duplicate_artifact(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """The ``(seq, version)`` of the row this ``artifact-written`` merely repeats.

    The whole window is searched, not just the last row: two files saved in the same
    tool call interleave as ``a, b, a`` and the repeat of ``a`` is still the second
    hook seeing the first write. A row stamped in the future is never a duplicate —
    a clock that ran backwards would otherwise swallow every subsequent write.

    Accepted: `--force` does not bypass this, so two genuine writes of one path inside
    5 s that leave an identical mtime collapse into the first one's row.
    """
    path = data.get("path")
    if not isinstance(path, str) or not path:
        return None
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=ARTIFACT_DEDUPE_SECONDS)).isoformat()
    rows = conn.execute(
        "SELECT seq, stream, version, type, data, ts, actor FROM events "
        "WHERE stream = ? AND type = 'artifact-written' AND ts >= ? "
        "ORDER BY seq DESC LIMIT 50",
        (stream, cutoff),
    ).fetchall()
    for row in rows:
        previous = _row_to_event(row)
        if (
            previous.data.get("path") != path
            or previous.data.get("mtime") != data.get("mtime")
        ):
            continue
        elapsed = _seconds_since(previous.ts, now)
        if elapsed is None or not 0 <= elapsed <= ARTIFACT_DEDUPE_SECONDS:
            continue
        return previous.seq, previous.version
    return None


def _implied_phase_payload(
    previous: Optional[str], phase: str, event_type: str
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "phase": phase,
        "implied": True,
        "implied_by": event_type,
    }
    start = PHASE_ORDER.index(previous) + 1 if previous in PHASE_ORDER else 0
    skipped = PHASE_ORDER[start: PHASE_ORDER.index(phase)]
    if skipped:
        payload["skipped"] = skipped
    return payload


def append_event(
    conn: sqlite3.Connection,
    stream: str,
    event_type: str,
    data: Dict[str, Any],
    project_dir: Path,
    expect: Optional[int] = None,
    actor: Optional[str] = None,
    force: bool = False,
    force_reason: Optional[str] = None,
    allow_new_type: bool = False,
) -> AppendResult:
    """Append one event.

    ``UNIQUE(stream, version)`` is the real concurrency guard; ``BEGIN IMMEDIATE``
    serializes writers so the common path never collides. On the rare
    IntegrityError we recompute the version once — unless the caller asked for a
    conditional append, in which case the collision *is* the conflict.
    """
    # The vocabulary check is not a gate precondition — it is about whether this event
    # can ever be read — so `--force` does not waive it; `--new-type` does.
    validate_event_type(event_type, allow_new_type)
    canonical_actor = parse_actor(actor, conn, data)

    payload = dict(data)
    if force:
        payload["forced"] = True
        payload["force_reason"] = force_reason
    if allow_new_type and event_type not in EVENT_VOCABULARY:
        payload["new_type"] = True
    # Like the vocabulary check, this is about whether the event can be read at all,
    # so `--force` does not waive it.
    payload = normalize_payload(event_type, payload)
    check_payload_size(stream, payload, force, force_reason)

    for attempt in range(2):
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = current_version(conn, stream)
            if expect is not None and existing != expect:
                conn.execute("ROLLBACK")
                raise VersionConflict(stream, expect, existing)
            if event_type == "artifact-written":
                repeated = _recent_duplicate_artifact(conn, stream, payload)
                if repeated is not None:
                    conn.execute("ROLLBACK")
                    return AppendResult(
                        repeated[0], repeated[1], duplicate=True,
                        version_before=existing,
                    )
            if not force:
                validate_gate(conn, stream, event_type, payload, project_dir)

            version = existing + 1
            implied_phase = PHASE_OF_EVENT.get(event_type)
            if implied_phase is not None:
                previous = folded_phase(conn, stream)
                if previous == implied_phase:
                    implied_phase = None
                else:
                    _insert_event(
                        conn, stream, version, "phase-entered",
                        _implied_phase_payload(previous, implied_phase, event_type),
                        canonical_actor,
                    )
                    version += 1

            seq = _insert_event(
                conn, stream, version, event_type, payload, canonical_actor
            )
            conn.execute("COMMIT")
            return AppendResult(
                seq, version, implied_phase, version_before=existing
            )
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            if expect is not None:
                raise VersionConflict(stream, expect, current_version(conn, stream))
            if attempt == 0:
                continue
            raise
        except Exception:
            _rollback_quietly(conn)
            raise

    raise InfraError(f"could not append to stream {stream!r} after a retry")


def _insert_event(
    conn: sqlite3.Connection,
    stream: str,
    version: int,
    event_type: str,
    payload: Dict[str, Any],
    actor: Optional[str],
) -> int:
    cursor = conn.execute(
        "INSERT INTO events (stream, version, type, data, ts, actor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (stream, version, event_type, json.dumps(payload, sort_keys=True),
         utc_now(), actor),
    )
    return int(cursor.lastrowid)


def _rollback_quietly(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------
# Derived views
# --------------------------------------------------------------------------


def is_work_stream(stream: str) -> bool:
    """Every stream except the tool's own is work worth reporting.

    Defining this by exclusion rather than by a `feature/` prefix is deliberate: a
    session that names its stream after the branch (`fix/1290-date-off-by-one`) is doing
    something reasonable — arguably better, since it ties the journal to the branch —
    and a prefix allowlist silently hid whole flows from `status`.
    """
    return stream != META_STREAM and not stream.startswith(WATCH_STREAM_PREFIX)


def feature_slug(stream: str) -> str:
    return stream[len(FEATURE_STREAM_PREFIX):] if stream.startswith(
        FEATURE_STREAM_PREFIX
    ) else stream


def fold_stream(
    events: Sequence[Event], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Fold a stream's events into its entry in the status brief."""
    phase: Optional[str] = None
    phase_entered_at: Optional[str] = None
    phase_implied = False
    terminal = False
    gate_decisions: List[Dict[str, Any]] = []
    queued: Dict[str, Dict[str, Any]] = {}
    last_verify: Optional[Dict[str, Any]] = None
    task_ids: List[str] = []

    for event in events:
        if event.type in TERMINAL_TYPES:
            terminal = True
        elif event.type in REVIVING_TYPES:
            terminal = False

        if event.type == "phase-entered":
            # Same rule as `folded_phase`: a phase outside the declared order (an
            # imported row spelling it `Implement`) is not a position the brief or
            # the ordering gate can reason about, so neither of them adopts it.
            candidate = event.data.get("phase")
            if candidate in PHASE_ORDER:
                phase = candidate
                phase_entered_at = event.ts
                phase_implied = bool(event.data.get("implied"))
        elif event.type == "gate-decision":
            # Start from the event's own payload so a decision recorded under a
            # different shape keeps its content, then overlay the canonical keys.
            # Normalizing first would replace real detail with a row of nulls.
            folded = {k: v for k, v in event.data.items() if v is not None}
            for key in ("gate", "question", "decision", "mode", "rationale"):
                value = event.data.get(key)
                if value is not None:
                    folded[key] = value
            folded["ts"] = event.ts
            gate_decisions.append(folded)
        elif event.type == "design-queued":
            issue = event.data.get("issue")
            if issue is not None:
                queued[str(issue)] = {
                    "issue": issue,
                    "assumes": event.data.get("assumes"),
                    "ts": event.ts,
                }
        elif event.type in ("design-committed", "design-invalidated"):
            issue = event.data.get("issue")
            if issue is not None:
                queued.pop(str(issue), None)
        elif event.type == "verify-run":
            last_verify = {
                "outcome": event.data.get("outcome"),
                "scope": event.data.get("scope"),
                "task_ids": event.data.get("task_ids"),
                "ts": event.ts,
            }
        elif event.type == "task-done":
            task_id = event.data.get("task_id")
            if isinstance(task_id, str) and task_id not in task_ids:
                task_ids.append(task_id)

    last = events[-1] if events else None
    age = _seconds_since(last.ts, now) if last else None
    age_days = int(age // 86400) if age is not None else None
    if (
        not terminal
        and last is not None
        and last.type == "capture-done"
        and age is not None
        and age > CAPTURE_TERMINAL_HOURS * 3600
    ):
        terminal = True

    return {
        "stream": events[0].stream if events else None,
        "feature": feature_slug(events[0].stream) if events else None,
        "version": last.version if last else 0,
        "phase": phase,
        "phase_entered_at": phase_entered_at,
        "implied_phase": phase_implied,
        "last_event": (
            {"seq": last.seq, "type": last.type, "ts": last.ts} if last else None
        ),
        "age_days": age_days,
        "terminal": terminal,
        "dormant": bool(
            not terminal and age_days is not None and age_days >= DORMANT_DAYS
        ),
        "gate_decisions": gate_decisions,
        "gate_decision_count": len(gate_decisions),
        "open_designs": list(queued.values()),
        "last_verify": last_verify,
        "tasks_done": len(task_ids),
        "task_ids": task_ids,
    }


def branch_stream_candidates(branch: str) -> List[str]:
    """Stream names a git branch could plausibly be journaled under.

    The convention is stream name = branch name. Failing that, the branch's last path
    segment is tried with and without the `feature/` prefix, so branch
    `fix/1290-date-off-by-one` also finds streams `feature/1290-date-off-by-one` and
    `1290-date-off-by-one`. Most exact first.
    """
    slug = branch.rsplit("/", 1)[-1]
    candidates = [
        branch,
        FEATURE_STREAM_PREFIX + branch,
        FEATURE_STREAM_PREFIX + slug,
        feature_slug(branch),
        slug,
    ]
    unique: List[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def branch_match(branch: str, streams: Sequence[str]) -> Optional[str]:
    available = set(streams)
    for candidate in branch_stream_candidates(branch):
        if candidate in available:
            return candidate
    return None


def nested_branch_match(branches: Sequence[str],
                        folded: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The stream to put first when the checkout is an umbrella.

    `branches` are the branches checked out in the nested repos (the hook collects
    them; the session directory's own branch, if any, was tried first and named no
    stream). Several may name a stream — one live, the rest dormant — so the most
    recently active match wins; a tie keeps the given order.
    """
    streams = [f["stream"] for f in folded]
    last_at = {f["stream"]: (f.get("last_event") or {}).get("ts") or "" for f in folded}
    best: Optional[str] = None
    for branch in branches:
        matched = branch_match(branch, streams)
        if matched is not None and (best is None or last_at[matched] > last_at[best]):
            best = matched
    return best


def session_stream(folded: Sequence[Tuple[Dict[str, Any], Sequence[Event]]],
                   session: str) -> Optional[str]:
    """The live stream ``session`` last wrote to itself, or None.

    A session can drive a stream no checkout names — an epic's planning stream has no
    branch, and a stream opens before `workspace` makes its branch — and several sessions
    can run at once on different streams. What each one last appended is its position.
    Hook-written events do not count: a hook files an artifact write under the checked-out
    branch's stream, which says where the file landed, not what the session is driving. A
    finished stream releases the session to the branch fallback.
    """
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for entry, events in folded:
        for event in reversed(events):
            if _actor_role(event) != "hook" and event_session(event) == session:
                if best is None or event.seq > best[0]:
                    best = (event.seq, entry)
                break
    if best is None or best[1]["terminal"]:
        return None
    return best[1]["stream"]


def _brief_rank(feature: Dict[str, Any]) -> int:
    if feature.get("session_match"):
        return 0
    if feature.get("branch_match"):
        return 1
    if feature.get("terminal"):
        return 4
    return 3 if feature.get("dormant") else 2


def build_status(
    conn: sqlite3.Connection,
    feature: Optional[str] = None,
    branch: Optional[str] = None,
    show_all: bool = False,
    now: Optional[datetime] = None,
    nested_branches: Optional[Sequence[str]] = None,
    session: Optional[str] = None,
) -> Dict[str, Any]:
    if feature:
        # Accept a bare slug, a `feature/` stream, or any other work stream name
        # (a branch-shaped one such as `fix/1290-…`) — match whichever exists.
        existing = list_streams(conn)
        candidates = [feature, FEATURE_STREAM_PREFIX + feature]
        wanted = [s for s in candidates if s in existing]
        if not wanted:
            wanted = [s for s in existing if is_work_stream(s) and feature in s]
        if not wanted:
            wanted = [candidates[0]]
    else:
        wanted = [s for s in list_streams(conn) if is_work_stream(s)]

    folded = []
    with_events = []
    for stream in wanted:
        events = read_events(conn, stream=stream)
        if not events:
            continue
        entry = fold_stream(events, now=now)
        folded.append(entry)
        with_events.append((entry, events))

    matched = branch_match(branch, [f["stream"] for f in folded]) if branch else None
    if matched is None and nested_branches:
        matched = nested_branch_match(nested_branches, folded)
    driven = session_stream(with_events, session) if session else None
    # Hiding finished work is what keeps the brief small, but someone who names a
    # stream is asking about that stream — answering "nothing here" would be a lie.
    keep_terminal = show_all or bool(feature)
    features = []
    hidden_terminal = 0
    for entry in folded:
        entry["branch_match"] = entry["stream"] == matched
        entry["session_match"] = entry["stream"] == driven
        if entry["terminal"] and not keep_terminal and not entry["branch_match"]:
            hidden_terminal += 1
            continue
        features.append(entry)

    # Two stable sorts: recency inside each rank, then the ranks themselves.
    features.sort(key=lambda f: (f["last_event"] or {}).get("ts") or "", reverse=True)
    features.sort(key=_brief_rank)
    return {
        "features": features,
        "hidden_terminal": hidden_terminal,
        "branch_match": matched,
        "session_match": driven,
    }


def _render_decision(decision: Dict[str, Any]) -> str:
    """Render a gate decision from whatever keys it actually carries.

    Payload shapes drift — an event recorded before the canonical shape settled may
    carry `chosen` instead of `question`/`decision`. Printing "None -> None (None)"
    for those makes real history look like corruption, so show what is there and fall
    back to the raw payload rather than to placeholders.
    """
    gate = decision.get("gate")
    prefix = f"[{gate}] " if gate else ""
    question = decision.get("question")
    answer = decision.get("decision") or decision.get("chosen")
    mode = decision.get("mode")
    suffix = f" ({mode})" if mode else ""

    if question and answer:
        return f"{prefix}{question} -> {answer}{suffix}"
    if answer:
        return f"{prefix}{answer}{suffix}"
    if question:
        return f"{prefix}{question} -> (undecided){suffix}"
    body = ", ".join(
        f"{k}={v}" for k, v in decision.items()
        if k not in {"gate", "mode", "ts"} and v is not None
    )
    return f"{prefix}{body or '(no detail recorded)'}{suffix}"


def _render_ledger(status: Dict[str, Any]) -> List[str]:
    """One line, and only when the ledger is actually holding something.

    An empty ledger is the healthy state, so saying so every session would be noise.
    """
    ledger = status.get("ledger")
    if not isinstance(ledger, dict) or not ledger.get("entries"):
        return []
    entries = ledger["entries"]
    line = (
        f"ledger       : {entries} untriaged "
        f"{'entry' if entries == 1 else 'entries'} in {ledger['path']}"
    )
    if ledger.get("nudge"):
        line += "  — worth triaging (see knowledge-base)"
    return [line]


def _one_line(value: Any) -> str:
    """Collapse every run of whitespace, newlines included, to a single space.

    The brief is injected into the session prompt, so a payload that carries a
    newline would otherwise be able to add lines to it — a heading, a fake section
    divider — and the reader has no way to tell those from the journal's own.
    """
    return " ".join(str(value).split())


def _clip(line: str) -> str:
    flat = _one_line(line)
    if len(flat) <= BRIEF_LINE_CHARS:
        return flat
    return flat[: BRIEF_LINE_CHARS - 1] + "…"


def _short_ts(ts: Any) -> str:
    """Minute precision — the brief is read to orient, never to reconcile.

    Collapsed before it is cut: an imported row can carry anything in `ts`, and 16
    characters of a newline-bearing string would still reach the brief as two lines.
    """
    return _one_line(ts)[:16]


def _render_task_ids(feature: Dict[str, Any]) -> str:
    ids = feature["task_ids"]
    if not ids:
        return ""
    shown = ids[-BRIEF_TASK_IDS:]
    elided = "… " if len(ids) > len(shown) else ""
    return f"  [{elided}{', '.join(_one_line(i) for i in shown)}]"


def _render_dormant(feature: Dict[str, Any]) -> str:
    """One line for work nobody has touched in a week — name, position, age."""
    last = feature["last_event"] or {}
    return _one_line(
        f"{feature['stream']}  (v{feature['version']})  "
        f"phase {feature['phase'] or '—'} · "
        f"last {last.get('type', '—')} {str(last.get('ts', ''))[:10]}  "
        f"· dormant {feature['age_days']}d"
    )


def _render_feature(feature: Dict[str, Any]) -> List[str]:
    lines = [
        f"{_one_line(feature['stream'])}  (v{feature['version']})"
        + ("  · terminal" if feature.get("terminal") else "")
    ]
    lines.append(
        f"  phase        : {feature['phase'] or '—'}"
        + ("  (implied)" if feature.get("implied_phase") else "")
        + (f"  (entered {_short_ts(feature['phase_entered_at'])})"
           if feature["phase_entered_at"] else "")
    )
    last = feature["last_event"]
    lines.append(
        f"  last event   : {_one_line(last['type'])} at {_short_ts(last['ts'])}"
        if last else "  last event   : —"
    )
    lines.append(
        f"  tasks done   : {feature['tasks_done']}" + _render_task_ids(feature)
    )
    verify = feature["last_verify"]
    if verify:
        covered = verify.get("task_ids") or []
        lines.append(
            f"  last verify  : {_one_line(verify.get('outcome'))}"
            + (f" — {', '.join(_one_line(t) for t in covered)}" if covered else "")
            + f" ({_short_ts(verify.get('ts'))})"
        )
    else:
        lines.append("  last verify  : —")
    decisions = feature["gate_decisions"]
    if decisions:
        limit = (
            BRIEF_DECISION_LIMIT
            if feature.get("branch_match") or feature.get("session_match")
            else BRIEF_DECISION_LIMIT_OTHER
        )
        shown = decisions[-limit:]
        lines.append("  gate decisions:")
        for decision in shown:
            lines.append(_clip("    - " + _render_decision(decision)))
        earlier = feature.get("gate_decision_count", len(decisions)) - len(shown)
        if earlier > 0:
            lines.append(f"    … +{earlier} earlier")
    if feature["open_designs"]:
        lines.append("  open designs:")
        for design in feature["open_designs"]:
            assumes = design.get("assumes")
            lines.append(_clip(
                f"    - {_one_line(design.get('issue'))}"
                + (f" (assumes {_one_line(assumes)})" if assumes else "")
            ))
    lines.append("")
    return lines


def _render_hidden(status: Dict[str, Any]) -> List[str]:
    hidden = status.get("hidden_terminal") or 0
    if not hidden:
        return []
    return [f"{hidden} completed stream(s) hidden (--all shows them)"]


def render_status(status: Dict[str, Any]) -> str:
    features = status["features"]
    if not features:
        return "\n".join([
            "No work streams recorded.",
            *_render_hidden(status),
            *_render_ledger(status),
        ])
    lines: List[str] = []
    for feature in features:
        if feature.get("dormant") and not (
            feature.get("branch_match") or feature.get("session_match")
        ):
            lines.append(_render_dormant(feature))
        else:
            lines.extend(_render_feature(feature))
    lines.extend(_render_hidden(status))
    lines.extend(_render_ledger(status))
    return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------
# check — the Stop hook gate
# --------------------------------------------------------------------------


def parse_ticked_tasks(text: str) -> List[str]:
    """Return the task ids ticked in the Build Plan section, in document order.

    When no Build Plan heading exists the whole document is scanned, so a bare
    checklist still works.
    """
    match = _BUILD_PLAN_RE.search(text)
    if match:
        level = len(match.group(1))
        rest = text[match.end():]
        closing = re.search(r"^#{1,%d}\s+\S" % level, rest, re.MULTILINE)
        region = rest[: closing.start()] if closing else rest
    else:
        region = text
    seen: List[str] = []
    for task_id in _TICKED_TASK_RE.findall(region):
        if task_id not in seen:
            seen.append(task_id)
    return seen


def event_session(event: Event) -> Optional[str]:
    """Which session an event belongs to.

    Hook-written events carry ``data.session``; skill-written events carry it as the
    ``role@label`` suffix `append` fills in from ``meta.current_session``. Both are
    honored; an actor with no label belongs to no particular session.
    """
    session = event.data.get("session")
    if isinstance(session, str) and session:
        return session
    if event.actor and "@" in event.actor:
        return event.actor.split("@", 1)[1] or None
    return None


def _matches_glob(path: str, pattern: str) -> bool:
    from fnmatch import fnmatch

    normalized = path.replace(os.sep, "/")
    if fnmatch(normalized, pattern):
        return True
    # Allow a project-relative glob to match an absolute or deeper path.
    return fnmatch(normalized, "*/" + pattern.lstrip("./"))


def classify_artifact(path: str, homes: Dict[str, str]) -> Optional[str]:
    """Classify an artifact path most-specific-first.

    ``artifact_homes.prd`` is typically ``docs/prd/*.md``, which also matches
    ``docs/prd/<name>.worklog.md`` — so worklogs are tested first and a worklog
    is never mistaken for a PRD.
    """
    normalized = path.replace(os.sep, "/")
    if normalized.endswith(".worklog.md") or _matches_glob(
        normalized, homes.get("worklog", DEFAULT_ARTIFACT_HOMES["worklog"])
    ):
        return "worklog"
    if _matches_glob(normalized, homes.get("adr", DEFAULT_ARTIFACT_HOMES["adr"])):
        return "adr"
    if _matches_glob(normalized, homes.get("prd", DEFAULT_ARTIFACT_HOMES["prd"])):
        return "prd"
    return None


def _slug_from_artifact(path: str) -> str:
    name = os.path.basename(path.replace(os.sep, "/"))
    if name.endswith(".worklog.md"):
        return name[: -len(".worklog.md")]
    if name.endswith(".md"):
        return name[: -len(".md")]
    return name


def _suggest(db_path: Path, stream: str, event_type: str,
             data: Dict[str, Any]) -> str:
    from shlex import quote

    script = str(Path(__file__).resolve())
    return " ".join([
        "python3", quote(script),
        "--db", quote(str(db_path)),
        "append",
        "--stream", quote(stream),
        "--type", quote(event_type),
        "--data", quote(json.dumps(data, sort_keys=True)),
    ])


def run_check(
    conn: sqlite3.Connection,
    session: str,
    db_path: Path,
    project_dir: Path,
    homes: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Detect semantic events missing for ``session``. Returns findings."""
    all_events = read_events(conn)
    session_events = [e for e in all_events if event_session(e) == session]
    findings: List[Dict[str, Any]] = []

    # -- rule A: ticked build-plan boxes with no task-done ------------------
    worklog_paths: List[Tuple[str, str]] = []  # (path, stream)
    prd_paths: List[Tuple[str, str]] = []
    for event in session_events:
        if event.type != "artifact-written":
            continue
        path = event.data.get("path")
        if not isinstance(path, str) or not path:
            continue
        kind = classify_artifact(path, homes)
        if kind == "worklog" and (path, event.stream) not in worklog_paths:
            worklog_paths.append((path, event.stream))
        elif kind == "prd" and (path, event.stream) not in prd_paths:
            prd_paths.append((path, event.stream))

    for path, event_stream in worklog_paths:
        resolved = _resolve_artifact(project_dir, path)
        if not resolved.is_file():
            continue
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ticked = parse_ticked_tasks(text)
        if not ticked:
            continue
        target_stream = FEATURE_STREAM_PREFIX + _slug_from_artifact(path)
        candidate_streams = {event_stream, target_stream}

        # Only gate a flow the journal is actually tracking. A worklog can be written
        # without any flow behind it — a legacy artifact from before this journal
        # existed, or a vault sync pulling in someone else's edit — and blocking a
        # session over ticked boxes the user never touched would make the gate a
        # nuisance rather than a safeguard. `artifact-written` is excluded on purpose:
        # it is the capture hook's own footprint, so counting it would mark every
        # observed file as tracked and defeat the check.
        feature_streams = {s for s in candidate_streams if is_work_stream(s)}
        if not any(
            e.stream in feature_streams and e.type != "artifact-written"
            for e in all_events
        ):
            continue

        covered = {
            e.data.get("task_id")
            for e in all_events
            if e.type == "task-done" and e.stream in candidate_streams
        }
        for task_id in ticked:
            if task_id in covered:
                continue
            has_verify = any(
                e.type == "verify-run"
                and e.stream in candidate_streams
                and e.data.get("outcome") == "pass"
                and isinstance(e.data.get("task_ids"), list)
                and task_id in e.data["task_ids"]
                for e in all_events
            )
            detail = (
                f"{path}: Build Plan box {task_id} is ticked but no task-done event "
                f"records it"
            )
            if not has_verify:
                detail += (
                    f" — record a verify-run (outcome=pass) naming {task_id} first, "
                    "or append with --force and a reason"
                )
            findings.append({
                "missing": "task-done",
                "detail": detail,
                "suggested_command": _suggest(
                    db_path, target_stream, "task-done", {"task_id": task_id}
                ),
            })

    # -- rule B: PRD written at clarify with no gate-decision this session --
    session_has_gate_decision = any(
        e.type == "gate-decision" for e in session_events
    )
    for path, event_stream in prd_paths:
        if session_has_gate_decision:
            break
        target_stream = FEATURE_STREAM_PREFIX + _slug_from_artifact(path)
        phase = None
        for stream in (target_stream, event_stream):
            events = [e for e in all_events if e.stream == stream]
            if events:
                phase = fold_stream(events)["phase"]
                if phase is not None:
                    break
        if phase != "clarify":
            continue
        findings.append({
            "missing": "gate-decision",
            "detail": (
                f"{path} was written while {target_stream} is in the clarify phase, "
                "but this session recorded no gate-decision event"
            ),
            "suggested_command": _suggest(db_path, target_stream, "gate-decision", {
                "gate": "clarify",
                "question": "<what was decided>",
                "decision": "<the answer>",
                "mode": "executive",
                "rationale": "<why>",
            }),
        })

    # -- rule C: task-done this session with no preceding passing verify-run
    for event in session_events:
        if event.type != "task-done":
            continue
        task_id = event.data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        covered = any(
            e.type == "verify-run"
            and e.stream == event.stream
            and e.seq < event.seq
            and e.data.get("outcome") == "pass"
            and isinstance(e.data.get("task_ids"), list)
            and task_id in e.data["task_ids"]
            for e in all_events
        )
        if covered:
            continue
        findings.append({
            "missing": "verify-run",
            "detail": (
                f"{event.stream}: task-done {task_id} (seq {event.seq}) has no "
                "preceding verify-run with outcome=pass naming it"
            ),
            "suggested_command": _suggest(db_path, event.stream, "verify-run", {
                "scope": "<what was run>",
                "commands": [{"cmd": "<command>", "exit": 0}],
                "outcome": "pass",
                "task_ids": [task_id],
            }),
        })

    return findings


def render_findings(findings: Sequence[Dict[str, Any]]) -> str:
    lines = [
        f"{len(findings)} missing semantic event(s) for this session — "
        "append them, then stop again:"
    ]
    for finding in findings:
        lines.append(
            f"  • missing {finding['missing']}: {_one_line(finding['detail'])}"
        )
        lines.append(f"      {finding['suggested_command']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# stats
# --------------------------------------------------------------------------


def _merge_counts(dicts: Iterable[Dict[str, int]]) -> Dict[str, int]:
    merged: Dict[str, int] = {}
    for source in dicts:
        for key, value in source.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _actor_role(event: Event) -> str:
    return (event.actor or "").split("@", 1)[0] or "unattributed"


def _counted_sessions(events: Iterable[Event]) -> Set[str]:
    """The sessions that touched these events.

    Events actored `user@…` are excluded: that label is a person's name, not a session
    id (ADR 0003 only defaults the label to `meta.current_session` for machine roles),
    so counting them would inflate "sessions" by one per human who ever appeared.
    """
    return {
        session
        for session in (
            event_session(event) for event in events if _actor_role(event) != "user"
        )
        if session
    }


def _stream_stats(
    stream: str, events: Sequence[Event], now: Optional[datetime] = None
) -> Dict[str, Any]:
    by_role: Dict[str, int] = {}
    decisions: Dict[str, int] = {}
    verified: Dict[str, int] = {}
    task_ids: Set[str] = set()
    tallies = {
        "deviation": 0, "verify-run": 0, "task-done": 0,
        "review-verdict": 0, "review-feedback": 0,
    }
    implied = 0

    for event in events:
        role = _actor_role(event)
        by_role[role] = by_role.get(role, 0) + 1
        if event.type in tallies:
            tallies[event.type] += 1
        if event.type == "gate-decision":
            key = "{}/{}".format(
                event.data.get("mode") or "-", event.data.get("raised_by") or "-"
            )
            decisions[key] = decisions.get(key, 0) + 1
        elif event.type == "verify-run":
            # Per verify-run, not per mention: one run naming a task twice verified
            # it once.
            for task in set(str(t) for t in event.data.get("task_ids") or []):
                verified[task] = verified.get(task, 0) + 1
        elif event.type == "task-done":
            task_id = event.data.get("task_id")
            if isinstance(task_id, str) and task_id:
                task_ids.add(task_id)
        elif event.type == "phase-entered" and event.data.get("implied"):
            implied += 1

    rendered = render_status({"features": [fold_stream(events, now=now)]})
    return {
        "stream": stream,
        "events": len(events),
        "by_role": by_role,
        "decisions": decisions,
        "deviations": tallies["deviation"],
        "verify_runs": tallies["verify-run"],
        # Distinct ids, as the brief counts them — a task re-recorded after review
        # feedback is one task done, not two.
        "tasks_done": len(task_ids),
        "tasks_reverified": sum(1 for runs in verified.values() if runs > 1),
        "review_rounds": tallies["review-verdict"],
        "review_feedback": tallies["review-feedback"],
        "sessions": len(_counted_sessions(events)),
        "implied_phases": implied,
        "stream_render_bytes": len(rendered.encode()),
    }


STATS_SUMS = (
    "events", "deviations", "verify_runs", "tasks_done", "tasks_reverified",
    "review_rounds", "review_feedback", "implied_phases",
)


def build_stats(
    conn: sqlite3.Connection,
    since: Optional[str] = None,
    stream: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Per-stream counts for the numbers the process is tuned on (FR-014)."""
    cutoff = None
    if since:
        cutoff = _parse_ts(since)
        if cutoff is None:
            raise UsageError(
                f"--since {since!r} is not an ISO timestamp "
                "(2026-09-01, or 2026-09-01T12:00:00+00:00)"
            )

    grouped: Dict[str, List[Event]] = {}
    for event in read_events(conn, stream=stream):
        # An explicitly named stream is reported even when it is the tool's own.
        if stream is None and not is_work_stream(event.stream):
            continue
        if cutoff is not None:
            recorded = _parse_ts(event.ts)
            if recorded is None or recorded < cutoff:
                continue
        grouped.setdefault(event.stream, []).append(event)

    rows = [
        _stream_stats(name, events, now=now)
        for name, events in sorted(grouped.items())
    ]
    totals: Dict[str, Any] = {key: sum(row[key] for row in rows) for key in STATS_SUMS}
    totals["by_role"] = _merge_counts(row["by_role"] for row in rows)
    totals["decisions"] = _merge_counts(row["decisions"] for row in rows)
    totals["sessions"] = len(
        _counted_sessions(e for events in grouped.values() for e in events)
    )
    # The brief is not the sum of its streams — it hides terminal ones and collapses
    # dormant ones to a line — so the only honest total is the brief itself. It is a
    # whole-journal measurement: `--since` narrows the counts, never this.
    totals["brief_bytes"] = len(
        render_status(build_status(conn, feature=stream, now=now)).encode()
    )
    return {"since": since, "streams": rows, "totals": totals}


STATS_COLUMNS = (
    ("dec", lambda r: sum(r["decisions"].values())),
    ("dev", lambda r: r["deviations"]),
    ("vfy", lambda r: r["verify_runs"]),
    ("task", lambda r: r["tasks_done"]),
    ("rvfy", lambda r: r["tasks_reverified"]),
    ("rnd", lambda r: r["review_rounds"]),
    ("fb", lambda r: r["review_feedback"]),
    ("sess", lambda r: r["sessions"]),
    ("impl", lambda r: r["implied_phases"]),
    # Per stream this is that stream's own rendered block; on the TOTAL row it is the
    # whole brief, which is smaller than their sum.
    ("bytes", lambda r: r.get("stream_render_bytes", r.get("brief_bytes", 0))),
)


def render_stats(report: Dict[str, Any]) -> str:
    rows = report["streams"]
    since = report.get("since")
    scope = f" since {since}" if since else ""
    if not rows:
        return f"no work streams recorded{scope}"

    roles = sorted({role for row in rows for role in row["by_role"]})
    header = ["stream", "ev"] + [role[:4] for role in roles] + [
        name for name, _ in STATS_COLUMNS
    ]

    def cells(row: Dict[str, Any], label: str) -> List[str]:
        return (
            [label, str(row["events"])]
            + [str(row["by_role"].get(role, 0)) for role in roles]
            + [str(read(row)) for _, read in STATS_COLUMNS]
        )

    table = [header] + [cells(row, row["stream"]) for row in rows]
    table.append(cells(report["totals"], "TOTAL"))
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    lines = [
        "  ".join(
            cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i])
            for i, cell in enumerate(row)
        ).rstrip()
        for row in table
    ]

    lines.append("")
    lines.append("gate decisions (mode/raised_by):")
    decisions = report["totals"]["decisions"]
    if decisions:
        width = max(len(key) for key in decisions)
        for key in sorted(decisions):
            lines.append(f"  {key.ljust(width)}  {decisions[key]}")
    else:
        lines.append("  none recorded")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def run_doctor(conn: sqlite3.Connection, resolution: Resolution) -> Dict[str, Any]:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    schema_version = read_schema_version(conn)
    counts = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

    sidecar_report: Dict[str, Any] = {"found": False}
    if resolution.sidecar is not None:
        declared = sidecar_db_path(resolution.sidecar)
        sidecar_report = {
            "found": True,
            "path": str(resolution.sidecar.path),
            "db": str(declared) if declared else None,
            "agrees": bool(declared) and declared == resolution.db_path,
        }

    # Types already recorded that no gate or report can read. `append` refuses these
    # now, but a journal written before the vocabulary was enforced can still hold them,
    # and silently inert history is precisely what this is meant to expose.
    off_vocabulary = [
        {"type": row["type"], "count": row["n"]}
        for row in conn.execute(
            "SELECT type, COUNT(*) AS n FROM events GROUP BY type ORDER BY type"
        )
        if row["type"] not in EVENT_VOCABULARY
    ]

    return {
        "db": str(resolution.db_path),
        "db_source": resolution.source,
        "integrity_check": integrity,
        "off_vocabulary": off_vocabulary,
        "journal_mode": str(mode).lower(),
        "schema_version": schema_version,
        "pending_migrations": pending_migrations(conn),
        "events": counts,
        "sidecar": sidecar_report,
    }


def render_doctor(report: Dict[str, Any]) -> str:
    sidecar = report["sidecar"]
    if sidecar["found"]:
        agreement = "agrees" if sidecar["agrees"] else f"DISAGREES (declares {sidecar['db']})"
        sidecar_line = f"{sidecar['path']} — {agreement}"
    else:
        sidecar_line = "not found"
    pending = report["pending_migrations"]
    lines = [
        f"database        : {report['db']} (resolved from {report['db_source']})",
        f"integrity_check : {report['integrity_check']}",
        f"journal_mode    : {report['journal_mode']}",
        f"schema_version  : {report['schema_version']}",
        f"pending migr.   : {', '.join(str(p) for p in pending) if pending else 'none'}",
        f"events          : {report['events']}",
        f"sidecar         : {sidecar_line}",
    ]
    drift = report.get("off_vocabulary") or []
    if drift:
        summary = ", ".join(f"{d['type']} x{d['count']}" for d in drift)
        lines.append(f"off-vocabulary  : {summary}")
        lines.append(
            "                  these events are inert — no gate or report reads them. "
            "`journal.py vocab` lists the canonical names; re-record anything that "
            "still matters under the right one (the log is append-only, so annotate "
            "rather than rewrite)."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# export / import
# --------------------------------------------------------------------------


def export_events(conn: sqlite3.Connection, stream: Optional[str],
                  out) -> int:
    count = 0
    for event in read_events(conn, stream=stream):
        out.write(json.dumps(event.as_dict(), sort_keys=True) + "\n")
        count += 1
    return count


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def import_events(conn: sqlite3.Connection, path: Path) -> Dict[str, Any]:
    """Merge a JSONL dump by ``(stream, version)``. Never overwrites."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InfraError(f"cannot read {path}: {exc}") from exc

    records: List[Dict[str, Any]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise UsageError(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        if not isinstance(record, dict):
            raise UsageError(f"{path}:{lineno}: expected a JSON object")
        for key in ("stream", "version", "type"):
            if key not in record:
                raise UsageError(f"{path}:{lineno}: missing required key {key!r}")
        records.append(record)

    imported = 0
    skipped = 0
    conflicts: List[Dict[str, Any]] = []

    conn.execute("BEGIN IMMEDIATE")
    try:
        for record in records:
            stream = str(record["stream"])
            version = int(record["version"])
            event_type = str(record["type"])
            data = record.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except ValueError:
                    data = {}
            if not isinstance(data, dict):
                data = {}
            ts = str(record.get("ts") or utc_now())
            actor = record.get("actor")

            row = conn.execute(
                "SELECT type, data, ts, actor FROM events "
                "WHERE stream = ? AND version = ?",
                (stream, version),
            ).fetchone()
            if row is not None:
                same = (
                    row["type"] == event_type
                    and _canonical(json.loads(row["data"])) == _canonical(data)
                    and row["ts"] == ts
                    and row["actor"] == actor
                )
                if same:
                    skipped += 1
                else:
                    conflicts.append({
                        "stream": stream,
                        "version": version,
                        "reason": "already present with different content",
                    })
                continue

            conn.execute(
                "INSERT INTO events (stream, version, type, data, ts, actor) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (stream, version, event_type, json.dumps(data, sort_keys=True),
                 ts, actor),
            )
            imported += 1
        conn.execute("COMMIT")
    except Exception:
        _rollback_quietly(conn)
        raise

    return {
        "imported": imported,
        "skipped": skipped,
        "conflicts": len(conflicts),
        "conflict_details": conflicts,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EPILOG = """\
exit codes:
  0  ok
  1  infrastructure failure (database missing or unreadable, IO error)
  2  usage error
  3  version conflict — a conditional append (--expect) found a different
     current version; nothing was written
  4  gate violation — an append's precondition is unmet; nothing was written
  5  check findings — `check` found missing semantic events
  6  import conflicts — some rows exist with different content and were kept

database resolution:
  --db PATH, else the `db` key of the nearest .claude/shipgate.json sidecar
  (relative values resolve against the sidecar's project directory), else
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

    p_session = subparsers.add_parser(
        "session", help="read or set the session id append attributes events to"
    )
    _add_db_flag(p_session)
    p_session.add_argument("--set", dest="set_id", default=None, metavar="ID",
                           help="record ID as the current session")
    p_session.add_argument("--get", action="store_true",
                           help="print the current session id")
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
                               "no stream, the most recently active match first")
    p_status.add_argument("--session", default=None, metavar="ID",
                          help="a Claude Code session id; the live stream it last "
                               "wrote to itself renders first (session_match), ahead "
                               "of the branch's")
    p_status.add_argument("--all", action="store_true", dest="show_all",
                          help="include completed and abandoned streams")
    p_status.add_argument("--json", action="store_true", help="machine-readable output")

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
                         help="session id (matched against data.session or actor)")
    p_check.add_argument("--json", action="store_true", help="machine-readable output")

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
    return (f"appended {event_type} to {stream}: "
            f"seq {result.seq}, version {result.version}{transition}")


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


def cmd_session(args, resolution: Resolution) -> int:
    if bool(args.set_id) == bool(args.get):
        raise UsageError("session takes exactly one of --set ID or --get")
    conn = connect(resolution.db_path)
    try:
        if args.set_id:
            set_current_session(conn, args.set_id)
            session_id = args.set_id
        else:
            session_id = current_session(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps({"current_session": session_id}, sort_keys=True))
    elif args.set_id:
        print(f"current session set to {session_id}")
    elif session_id:
        print(session_id)
    else:
        print("no current session recorded")
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
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(render_status(status))
    return EXIT_OK


def cmd_stats(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        report = build_stats(conn, since=args.since, stream=args.stream)
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
        findings = run_check(
            conn,
            session=args.session,
            db_path=resolution.db_path,
            project_dir=resolution.project_dir,
            homes=artifact_homes(resolution.sidecar),
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps({"findings": findings}, sort_keys=True))
    elif findings:
        print(render_findings(findings))
    else:
        print("no missing semantic events for this session")
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


def cmd_streams(args, resolution: Resolution) -> int:
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


def cmd_doctor(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        report = run_doctor(conn, resolution)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(render_doctor(report))
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
    "append": cmd_append,
    "session": cmd_session,
    "status": cmd_status,
    "stats": cmd_stats,
    "check": cmd_check,
    "log": cmd_log,
    "streams": cmd_streams,
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
        # a project has one.
        if args.command == "vocab":
            return cmd_vocab(args, None)
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


if __name__ == "__main__":
    sys.exit(main())
