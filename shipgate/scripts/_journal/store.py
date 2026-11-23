"""SQLite: connection, schema and migrations, meta, events, timestamps."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from .vocab import BUSY_TIMEOUT_MS, InfraError
from .plugin import plugin_version


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
