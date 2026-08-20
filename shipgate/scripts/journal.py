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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

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
    "flow-abandoned": "work dropped for good",
    # gates and decisions
    "gate-decision": "a decision taken at a gate (this is the one for 'decision')",
    "clarify-passed": "the clarify gate closed — PRD has no open questions",
    "design-committed": "design + build plan landed",
    "design-queued": "a design parked for a later epic child",
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

# Streams the tool owns. Everything else is a work stream — named for its branch
# (`fix/8744-…`) or its feature slug, both of which are legitimate.
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

    history = read_events(conn, stream=stream, types=("phase-entered",))
    previous = -1
    for event in history:
        recorded = event.data.get("phase")
        if recorded in PHASE_ORDER:
            previous = PHASE_ORDER.index(recorded)

    # Backward and same-phase transitions are always legal (review -> implement
    # is a normal loop). So is a single step forward.
    if target - previous <= 1:
        return

    intervening = PHASE_ORDER[previous + 1: target]
    declared = data.get("skipped")
    declared_set = set(declared) if isinstance(declared, list) else set()
    unnamed = [name for name in intervening if name not in declared_set]
    if unnamed:
        raise GateViolation(
            "phase-entered {target}: forward jump skips {n} phase(s); list them in "
            "data.skipped. Missing: {missing}".format(
                target=phase, n=len(intervening), missing=", ".join(unnamed)
            )
        )


def _validate_review_verdict(
    conn: sqlite3.Connection, stream: str, data: Dict[str, Any]
) -> None:
    if data.get("verdict") != "pass":
        return
    task_dones = read_events(conn, stream=stream, types=("task-done",))
    last_task_done_seq = max((e.seq for e in task_dones), default=0)
    for event in _passing_verify_runs(conn, stream):
        if event.seq > last_task_done_seq:
            return
    raise GateViolation(
        "review-verdict=pass requires a verify-run with outcome=pass recorded after "
        f"the last task-done in stream {stream!r}"
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


# --------------------------------------------------------------------------
# Append
# --------------------------------------------------------------------------


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
) -> Tuple[int, int]:
    """Append one event. Returns ``(seq, version)``.

    ``UNIQUE(stream, version)`` is the real concurrency guard; ``BEGIN IMMEDIATE``
    serializes writers so the common path never collides. On the rare
    IntegrityError we recompute the version once — unless the caller asked for a
    conditional append, in which case the collision *is* the conflict.
    """
    # The vocabulary check is not a gate precondition — it is about whether this event
    # can ever be read — so `--force` does not waive it; `--new-type` does.
    validate_event_type(event_type, allow_new_type)

    payload = dict(data)
    if force:
        payload["forced"] = True
        payload["force_reason"] = force_reason
    if allow_new_type and event_type not in EVENT_VOCABULARY:
        payload["new_type"] = True

    for attempt in range(2):
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = current_version(conn, stream)
            if expect is not None and existing != expect:
                conn.execute("ROLLBACK")
                raise VersionConflict(stream, expect, existing)
            if not force:
                validate_gate(conn, stream, event_type, payload, project_dir)
            version = existing + 1
            cursor = conn.execute(
                "INSERT INTO events (stream, version, type, data, ts, actor) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    stream,
                    version,
                    event_type,
                    json.dumps(payload, sort_keys=True),
                    utc_now(),
                    actor,
                ),
            )
            seq = int(cursor.lastrowid)
            conn.execute("COMMIT")
            return seq, version
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            if expect is not None:
                raise VersionConflict(stream, expect, current_version(conn, stream))
            if attempt == 0:
                continue
            raise
        except JournalError:
            _rollback_quietly(conn)
            raise
        except Exception:
            _rollback_quietly(conn)
            raise

    raise InfraError(f"could not append to stream {stream!r} after a retry")


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
    session that names its stream after the branch (`fix/8744-vessel-rate`) is doing
    something reasonable — arguably better, since it ties the journal to the branch —
    and a prefix allowlist silently hid whole flows from `status`.
    """
    return stream != META_STREAM and not stream.startswith(WATCH_STREAM_PREFIX)


def feature_slug(stream: str) -> str:
    return stream[len(FEATURE_STREAM_PREFIX):] if stream.startswith(
        FEATURE_STREAM_PREFIX
    ) else stream


def fold_stream(events: Sequence[Event]) -> Dict[str, Any]:
    """Fold a stream's events into the resume brief for one feature."""
    phase: Optional[str] = None
    phase_entered_at: Optional[str] = None
    gate_decisions: List[Dict[str, Any]] = []
    queued: Dict[str, Dict[str, Any]] = {}
    last_verify: Optional[Dict[str, Any]] = None
    task_ids: List[str] = []

    for event in events:
        if event.type == "phase-entered":
            candidate = event.data.get("phase")
            if isinstance(candidate, str):
                phase = candidate
                phase_entered_at = event.ts
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
    return {
        "stream": events[0].stream if events else None,
        "feature": feature_slug(events[0].stream) if events else None,
        "version": last.version if last else 0,
        "phase": phase,
        "phase_entered_at": phase_entered_at,
        "last_event": (
            {"seq": last.seq, "type": last.type, "ts": last.ts} if last else None
        ),
        "gate_decisions": gate_decisions,
        "open_designs": list(queued.values()),
        "last_verify": last_verify,
        "tasks_done": len(task_ids),
        "task_ids": task_ids,
    }


def build_status(
    conn: sqlite3.Connection, feature: Optional[str] = None
) -> Dict[str, Any]:
    if feature:
        # Accept a bare slug, a `feature/` stream, or any other work stream name
        # (a branch-shaped one such as `fix/8744-…`) — match whichever exists.
        existing = list_streams(conn)
        candidates = [feature, FEATURE_STREAM_PREFIX + feature]
        wanted = [s for s in candidates if s in existing]
        if not wanted:
            wanted = [s for s in existing if is_work_stream(s) and feature in s]
        if not wanted:
            wanted = [candidates[0]]
    else:
        wanted = [s for s in list_streams(conn) if is_work_stream(s)]

    features = []
    for stream in wanted:
        events = read_events(conn, stream=stream)
        if not events:
            continue
        features.append(fold_stream(events))
    return {"features": features}


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


def render_status(status: Dict[str, Any]) -> str:
    features = status["features"]
    if not features:
        return "\n".join(["No feature streams recorded.", *_render_ledger(status)])
    lines: List[str] = []
    for feature in features:
        lines.append(f"{feature['stream']}  (v{feature['version']})")
        lines.append(
            f"  phase        : {feature['phase'] or '—'}"
            + (f"  (entered {feature['phase_entered_at']})"
               if feature["phase_entered_at"] else "")
        )
        last = feature["last_event"]
        lines.append(
            f"  last event   : {last['type']} at {last['ts']}" if last
            else "  last event   : —"
        )
        lines.append(
            f"  tasks done   : {feature['tasks_done']}"
            + (f"  [{', '.join(feature['task_ids'])}]" if feature["task_ids"] else "")
        )
        verify = feature["last_verify"]
        if verify:
            covered = verify.get("task_ids") or []
            lines.append(
                f"  last verify  : {verify.get('outcome')}"
                + (f" — {', '.join(str(t) for t in covered)}" if covered else "")
                + f" ({verify.get('ts')})"
            )
        else:
            lines.append("  last verify  : —")
        if feature["gate_decisions"]:
            lines.append("  gate decisions:")
            for decision in feature["gate_decisions"]:
                lines.append("    - " + _render_decision(decision))
        if feature["open_designs"]:
            lines.append("  open designs:")
            for design in feature["open_designs"]:
                assumes = design.get("assumes")
                lines.append(
                    f"    - {design.get('issue')}"
                    + (f" (assumes {assumes})" if assumes else "")
                )
        lines.append("")
    lines.extend(_render_ledger(status))
    return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------
# check — the Stop-hook gate
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

    Hook-written events carry ``data.session``; skill-written events label the
    session through ``--actor``. Both are honored.
    """
    session = event.data.get("session")
    if isinstance(session, str) and session:
        return session
    return event.actor


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
        lines.append(f"  • missing {finding['missing']}: {finding['detail']}")
        lines.append(f"      {finding['suggested_command']}")
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
    p_append.add_argument("--stream", required=True, help="stream name, e.g. feature/x")
    p_append.add_argument("--type", required=True, dest="event_type",
                          help="event type, e.g. phase-entered")
    p_append.add_argument("--data", default=None,
                          help="event payload as a JSON object")
    p_append.add_argument("--expect", type=int, default=None, metavar="N",
                          help="conditional append: current version must equal N")
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
    p_vocab.set_defaults(func=cmd_vocab)

    p_status = subparsers.add_parser("status", help="resume brief per feature stream")
    _add_db_flag(p_status)
    p_status.add_argument("--feature", default=None, metavar="SLUG",
                          help="restrict to one feature stream")
    p_status.add_argument("--json", action="store_true", help="machine-readable output")

    p_check = subparsers.add_parser(
        "check", help="Stop-hook gate: find semantic events missing for a session"
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


def parse_data_argument(raw: Optional[str]) -> Dict[str, Any]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
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


def cmd_append(args, resolution: Resolution) -> int:
    if args.force_reason is not None and not args.force:
        raise UsageError("--force-reason requires --force")
    data = parse_data_argument(args.data)

    conn = connect(resolution.db_path)
    try:
        try:
            seq, version = append_event(
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
        print(json.dumps({
            "seq": seq, "version": version,
            "stream": args.stream, "type": args.event_type,
        }, sort_keys=True))
    else:
        print(f"appended {args.event_type} to {args.stream}: "
              f"seq {seq}, version {version}")
    return EXIT_OK


def cmd_vocab(args, resolution: Resolution) -> int:
    if args.json:
        print(json.dumps(EVENT_VOCABULARY, sort_keys=True))
        return EXIT_OK
    width = max(len(name) for name in EVENT_VOCABULARY)
    for name, purpose in EVENT_VOCABULARY.items():
        print(f"  {name:<{width}}  {purpose}")
    print()
    print("Anything else is refused by `append` — pass --new-type to mint one on purpose.")
    return EXIT_OK


def cmd_status(args, resolution: Resolution) -> int:
    conn = connect(resolution.db_path)
    try:
        status = build_status(conn, args.feature)
    finally:
        conn.close()
    status["ledger"] = ledger_summary(resolution.project_dir, resolution.sidecar)
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(render_status(status))
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
    "status": cmd_status,
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
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INFRA
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
