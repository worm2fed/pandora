"""The health and config report."""

from __future__ import annotations

import json
import posixpath
import sqlite3
from typing import Any, Dict, Optional

from .vocab import DEFAULT_ARTIFACT_HOMES, DEFAULT_LEDGER, EVENT_VOCABULARY
from .plugin import _config, _hooks_common
from .text import _one_line
from .project import Resolution, sidecar_db_path
from .store import pending_migrations, read_schema_version
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
        declared = sidecar_db_path(resolution.sidecar)
        config = resolution.sidecar.config
        sidecar_report = {
            "found": True,
            "path": str(resolution.sidecar.path),
            "db": str(declared) if declared else None,
            "agrees": bool(declared) and declared == resolution.db_path,
            # The raw `version`, or None: a newer one means a newer shipgate wrote it.
            "version": config.get("version"),
            # Keys no shipgate template names; `setup`'s update mode drops them.
            "stray_keys": sorted(
                key for key in config if key not in _hooks_common.SIDECAR_KEYS
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
        "config": config_report(resolution),
    }


# The Knowledge base bullets the doctor compares with the sidecar's `artifact_homes`.
_CONFIG_HOME_KEYS = (("prd", "prd home"), ("adr", "adr home"), ("worklog", "worklog home"))


def _strip_path(value: str) -> str:
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _config_home_dir(value: str) -> Optional[str]:
    """The directory a config home names, `<...>` segments read as `*`; None when the
    value does not read as a directory (no `/`, or a last segment with a `.`).
    """
    if "/" not in value:
        return None
    segments = _strip_path(value).split("/")
    if "." in segments[-1]:
        return None
    return "/".join(
        "*" if len(segment) > 2 and segment[0] == "<" and segment[-1] == ">" else segment
        for segment in segments
    )


def _sidecar_home_dir(glob: str) -> str:
    """The directory a sidecar glob covers; trailing `**` segments are a deliberate
    recursive glob under it, not a different home."""
    segments = _strip_path(posixpath.dirname(glob)).split("/")
    while len(segments) > 1 and segments[-1] == "**":
        segments.pop()
    return "/".join(segments)


def _ledger_drift(config_value: Optional[str], sidecar_value: Optional[str]) -> Optional[str]:
    if config_value is not None and sidecar_value is None:
        return f"config names ledger `{config_value}`; the sidecar has no ledger key"
    if config_value is not None and sidecar_value is not None:
        if _strip_path(config_value) != _strip_path(sidecar_value):
            return f"ledger differs: config `{config_value}`, sidecar `{sidecar_value}`"
        return None
    if sidecar_value is not None and _strip_path(sidecar_value) != DEFAULT_LEDGER:
        return (
            f"sidecar names ledger `{sidecar_value}`; the config names none "
            f"(default {DEFAULT_LEDGER})"
        )
    return None


def config_report(resolution: Resolution) -> Dict[str, Any]:
    """The project's `.claude/shipgate.md` Knowledge base against its sidecar.

    `setup` writes both; a hand edit to one leaves the other behind, and the hooks and
    `status` read only the sidecar. Drift is information for `setup`'s update mode: it
    never changes the exit code.
    """
    path = resolution.project_dir / _config.CONFIG_RELPATH
    try:
        text: Optional[str] = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = None
    if text is None:
        return {
            "found": False,
            "path": str(path),
            "inherit": None,
            "section": "absent",
            "ledger": {"config": None, "sidecar": None, "drift": None},
            "homes": {
                key: {"config": None, "sidecar": None, "compared": False, "drift": None}
                for key, _ in _CONFIG_HOME_KEYS
            },
            "drift": [],
        }

    # ADR 0018: with no section here, an umbrella or user file owns it and the sidecar
    # mirrors that file, so nothing in this file can disagree with it.
    present = _config.section_present(text, _config.KNOWLEDGE_SECTION)
    values: Dict[str, Optional[str]] = {}
    if present:
        for key, value in _config.section_bullets(text, _config.KNOWLEDGE_SECTION):
            if key not in values:
                values[key] = _config.bullet_value(value)

    sidecar = resolution.sidecar
    compare = sidecar is not None and present
    sidecar_ledger = None
    sidecar_homes: Dict[str, Any] = {}
    if sidecar is not None:
        declared = sidecar.config.get("ledger")
        if isinstance(declared, str) and declared:
            sidecar_ledger = declared
        homes = sidecar.config.get("artifact_homes")
        if isinstance(homes, dict):
            sidecar_homes = homes

    config_ledger = values.get("ledger")
    ledger = {
        "config": config_ledger,
        "sidecar": sidecar_ledger,
        "drift": _ledger_drift(config_ledger, sidecar_ledger) if compare else None,
    }
    drift = [ledger["drift"]] if ledger["drift"] else []

    home_reports: Dict[str, Dict[str, Any]] = {}
    for key, bullet in _CONFIG_HOME_KEYS:
        config_value = values.get(bullet)
        declared = sidecar_homes.get(key)
        sidecar_glob = declared if isinstance(declared, str) else None
        config_dir = _config_home_dir(config_value) if config_value is not None else None
        compared = compare and config_dir is not None
        home_drift = None
        if compared:
            glob = sidecar_glob if sidecar_glob is not None else DEFAULT_ARTIFACT_HOMES[key]
            if config_dir != _sidecar_home_dir(glob):
                home_drift = (
                    f"{key} home differs: config `{config_value}`, sidecar glob `{glob}`"
                )
                drift.append(home_drift)
        home_reports[key] = {
            "config": config_value,
            "sidecar": sidecar_glob,
            "compared": compared,
            "drift": home_drift,
        }

    return {
        "found": True,
        "path": str(path),
        "inherit": _config.inherit_mode(text),
        "section": "present" if present else "absent",
        "ledger": ledger,
        "homes": home_reports,
        "drift": drift,
    }


def render_doctor(report: Dict[str, Any]) -> str:
    sidecar = report["sidecar"]
    if sidecar["found"]:
        agreement = "agrees" if sidecar["agrees"] else f"DISAGREES (declares {sidecar['db']})"
        sidecar_line = f"{sidecar['path']} — {agreement}"
    else:
        sidecar_line = "not found"
    sidecar_lines = []
    if sidecar["found"]:
        version = sidecar.get("version")
        stray = sidecar.get("stray_keys") or []
        sidecar_lines = [
            "sidecar version : "
            + ("—" if version is None else json.dumps(version, sort_keys=True)),
            f"stray keys      : {', '.join(stray) if stray else 'none'}",
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
    config = report.get("config")
    if config is not None:
        if not config["found"]:
            lines.append(f"config          : {config['path']} — not found")
        else:
            config_drift = config.get("drift") or []
            if config_drift:
                state = f"DRIFT ({len(config_drift)})"
            elif config.get("section") == "absent":
                state = "no Knowledge base section"
            elif not sidecar["found"]:
                state = "no sidecar to compare"
            else:
                state = "agrees"
            lines.append(f"config          : {config['path']} — {state}")
            lines.extend(f"drift           : {line}" for line in config_drift)
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
    return "\n".join(lines)
