"""The health and settings report."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vocab import EVENT_VOCABULARY, EVIDENCE_KEEP_DAYS
from .plugin import _config
from .text import _one_line
from .project import Resolution, sidecar_db_path
from .settings import _part, render_settings_report, settings_report
from .store import pending_migrations, read_schema_version
from .screens import (
    _as_line, evidence_root, EvidenceSurvey, project_key, survey_evidence,
)
from .check import stop_gate_trace


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
        try:
            schema_keys: Optional[Any] = _config.load_schema()["properties"]
        except OSError:
            schema_keys = None  # an incomplete install: the report still stands
        declared = sidecar_db_path(resolution.sidecar)
        config = resolution.sidecar.config
        sidecar_report = {
            "found": True,
            "path": str(resolution.sidecar.path),
            "db": str(declared) if declared else None,
            "agrees": bool(declared) and declared == resolution.db_path,
            # The raw `version`, or None: a newer one means a newer shipgate wrote it.
            "version": config.get("version"),
            # Keys the settings schema does not name (ADR 0028); `setup`'s update mode
            # drops them. None when the schema cannot be read.
            "stray_keys": None if schema_keys is None else sorted(
                key for key in config if key not in schema_keys
            ),
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
        "stop_gate": stop_gate_trace(conn),
        "journal_mode": str(mode).lower(),
        "schema_version": schema_version,
        "pending_migrations": pending_migrations(conn),
        "events": counts,
        "sidecar": sidecar_report,
        "settings": settings_report(resolution.project_dir),
        "evidence": doctor_evidence(conn),
    }


def doctor_evidence(conn: sqlite3.Connection) -> EvidenceSurvey:
    """The evidence root of this Claude config directory (ADR 0031), surveyed without a
    write; every part null when there is no root."""
    root = evidence_root()
    if root is None:
        return {"root": None, "exists": False, "project": None, "whole": None,
                "next_prune": None, "refused": None}
    return survey_evidence(root, project_key(conn), conn)


def render_doctor(report: Dict[str, Any],
                  project_dir: Optional[Path] = None) -> str:
    sidecar = report["sidecar"]
    if sidecar["found"]:
        agreement = ("agrees" if sidecar["agrees"]
                     else f"DISAGREES (declares {_part(str(sidecar['db']), 400)})")
        sidecar_line = f"{sidecar['path']} — {agreement}"
    else:
        sidecar_line = "not found"
    sidecar_lines = []
    if sidecar["found"]:
        version = sidecar.get("version")
        stray = sidecar.get("stray_keys")
        if stray is None:
            stray_text = "unknown (settings.schema.json unreadable)"
        else:
            # A checkout writes these keys: one line, no character that does not print.
            stray_text = _part(", ".join(stray), 400) if stray else "none"
        sidecar_lines = [
            "sidecar version : "
            + ("—" if version is None else json.dumps(version, sort_keys=True)),
            f"stray keys      : {stray_text}",
        ]
    pending = report["pending_migrations"]
    lines = [
        f"database        : {report['db']} (resolved from {report['db_source']})",
        f"integrity_check : {report['integrity_check']}",
        f"journal_mode    : {report['journal_mode']}",
        f"schema_version  : {report['schema_version']}",
        f"pending migr.   : {', '.join(str(p) for p in pending) if pending else 'none'}",
        f"events          : {report['events']}",
        f"sidecar         : {sidecar_line}",
        *sidecar_lines,
    ]
    if "settings" in report:
        lines.extend(render_settings_report(report["settings"], project_dir or Path.cwd()))
    gate = report.get("stop_gate")
    if gate is not None:
        check, block = gate.get("last_check"), gate.get("last_block")
        def shown(value: Any) -> str:
            return "?" if value is None else _one_line(value)

        lines.append(
            "stop gate       : last check: "
            + (
                f"{shown(check['at'])} — session {shown(check['session'])}, "
                f"{check['findings']} finding(s), {check['skipped']} skipped"
                if check else "never recorded"
            )
        )
        lines.append(
            "                  last block: "
            + (
                f"{shown(block['at'])} — session {shown(block['session'])}, "
                f"{shown(block['findings'])} finding(s)"
                if block else "never"
            )
        )
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
    if "evidence" in report:
        lines.extend(_render_evidence(report["evidence"]))
    return "\n".join(lines)


EVIDENCE_NOTE = ("  note          : another Claude config directory or another machine keeps "
                 "its own evidence root, which this report does not read")


def _counted(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def _evidence_size(size: int) -> str:
    """SIZE in bytes as people read it: base 1024, one decimal from KB on."""
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    units = ["KB", "MB", "GB", "TB"]
    while round(value, 1) >= 1024 and len(units) > 1:
        value /= 1024
        units.pop(0)
    return f"{value:.1f} {units[0]}"


def _evidence_files(part: Dict[str, Any]) -> str:
    if not part["files"]:
        return "no files"
    return (f"{_counted(part['files'], 'file', 'files')} · {_evidence_size(part['bytes'])}"
            f" · oldest {_counted(part['oldest_days'], 'day', 'days')}")


def _render_evidence(evidence: EvidenceSurvey) -> List[str]:
    """The evidence block (FR-016): the root, this project, the whole root, the next
    prune, the refused entries, and the root this report does not read."""
    root = evidence["root"]
    if root is None:
        return ["evidence root   : none (no CLAUDE_CONFIG_DIR, no HOME)"]
    if not evidence["exists"]:
        return [f"evidence root   : {_as_line(root)} (none yet)", EVIDENCE_NOTE]
    lines = [f"evidence root   : {_as_line(root)} (this Claude config directory)"]
    project = evidence["project"]
    if project is not None:
        lines.append(f"  this project  : {project['key']} · "
                     f"{_counted(project['streams'], 'stream', 'streams')} · "
                     + _evidence_files(project))
    whole = evidence["whole"]
    if whole is not None:
        lines.append(f"  whole root    : "
                     f"{_counted(whole['projects'], 'project', 'projects')} · "
                     + _evidence_files(whole))
    prune = evidence["next_prune"]
    if prune is not None:
        lines.append(
            f"  next prune    : {_counted(prune['directories'], 'directory', 'directories')}"
            f" of finished or unknown streams · {_counted(prune['files'], 'file', 'files')}"
            f" over {EVIDENCE_KEEP_DAYS} days")
    refused = evidence["refused"]
    if refused is not None and refused["count"]:
        lines.append(f"  refused       : {_counted(refused['count'], 'entry', 'entries')} "
                     f"outside the layout (first: {_as_line(refused['first'] or '')})")
    lines.append(EVIDENCE_NOTE)
    return lines
