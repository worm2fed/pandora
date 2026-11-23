"""`export` and `import`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vocab import InfraError, UsageError
from .store import read_events, utc_now
from .append import _rollback_quietly


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
