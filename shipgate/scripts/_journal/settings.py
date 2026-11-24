"""The settings as the journal shows them (ADR 0028): ``journal.py config`` and the
settings lines of the status brief.

The resolver is ``_config.resolve_settings``; ``project.project_settings`` feeds it the
files of one project. This module only prints what it returns.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .vocab import EXIT_OK, UsageError
from .plugin import _config
from .text import _clip, _one_line
from .project import _display_path, find_sidecar, project_settings, setting_source


def _json_safe(value: Any) -> Any:
    """VALUE when it is strict JSON, else its JSON text as a string. Python's json reads
    `NaN` and `Infinity` from a settings file; shipgate-hud's `JSON.parse` refuses them, so
    a value echoed into `--json` output must not carry one."""
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        try:
            return json.dumps(value, sort_keys=True)
        except (ValueError, TypeError, RecursionError):
            return "?"
    return value


def _shown(value: Any) -> str:
    """A value as the text form prints it: a string bare on one line, anything else as
    JSON. A checkout writes these files, so no value adds a line to the output."""
    if isinstance(value, str):
        return _one_line(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def config_doc(resolved: Any, keys: Sequence[str]) -> Dict[str, Any]:
    """The ``--json`` form: ``{settings: {key: {value, source, path[, section]}},
    problems: [...], legacy: {count, until, ended}}``. KEYS are leaf keys."""
    settings: Dict[str, Any] = {}
    for key in keys:
        setting = resolved.get(key)
        entry = {"value": setting.value, "source": setting.source, "path": setting.path}
        if setting.section is not None:
            entry["section"] = setting.section
        settings[key] = entry
    return {
        "settings": settings,
        "problems": [dict(problem._asdict(), value=_json_safe(problem.value))
                     for problem in resolved.problems],
        "legacy": {"count": len(resolved.legacy), "until": resolved.legacy_until,
                   "ended": resolved.legacy_ended},
    }


def cmd_config(args, resolution: Optional[Any] = None) -> int:
    """``config [KEY ...] [--json] [--start DIR]``: each setting's resolved value and
    its source. It opens no journal database.

    Exit 0; 2 when a printed key holds a value outside its set in a settings file, or
    a KEY is unknown; 1 when a printed key's walk reached a settings file that is not a
    JSON object. Every problem goes to stderr as one ``journal.py: <message>`` line;
    only those stop the command. The values print either way.
    """
    start = Path(args.start).resolve() if args.start else Path.cwd().resolve()
    sidecar = find_sidecar(start)  # InfraError (exit 1) for a broken project file
    project_dir = sidecar.project_dir if sidecar is not None else start
    resolved = project_settings(project_dir, start)

    keys: List[str] = []
    for key in args.keys or list(resolved.settings):
        try:
            keys.extend(k for k in resolved.keys(key) if k not in keys)
        except KeyError:
            known = sorted({k.split(".", 1)[0] for k in resolved.settings})
            raise UsageError(
                f"{key} is no setting; the settings are: {', '.join(known)}"
            ) from None

    for problem in resolved.problems:
        print(f"journal.py: {problem.message}", file=sys.stderr)
    refusals: List[int] = []
    for key in keys:
        try:
            resolved.require(key)
        except _config.SettingsError as exc:
            refusals.append(exc.exit_code)

    if args.json:
        print(json.dumps(config_doc(resolved, keys), sort_keys=True))
    else:
        for key in keys:
            setting = resolved.get(key)
            print(f"{_one_line(key)} = {_shown(setting.value)}  "
                  f"({_one_line(setting_source(setting, project_dir))})")
    # A file that cannot be read (1) outranks a value outside its set (2).
    return min(refusals) if refusals else EXIT_OK


# --------------------------------------------------------------------------
# The status brief's settings lines (ADR 0028, M2; PRD FR-006, FR-007, FR-011)
# --------------------------------------------------------------------------

# The settings that skills read, in the order the settings line prints them.
STATUS_KEYS = ("autonomy", "orchestration.review", "orchestration.explore",
               "writing_style", "code_graph")
# At most this many lines name a bad value; one more line counts the rest. A settings
# file is untrusted content, and the brief goes into the session prompt.
MAX_BAD_SETTING_LINES = 10
_KEY_CHARS = 48
_VALUE_CHARS = 40
_PATH_CHARS = 64
_PLAIN_KEY = re.compile(r"[A-Za-z0-9_.-]+")
_DOCTOR_CHARS = 400


def _part(text: str, limit: int, tail: bool = False) -> str:
    """One untrusted piece of a brief line: one line, each character that does not
    print shown as `?`, at most LIMIT characters. TAIL keeps the end (a path's file
    name) in place of the start."""
    flat = "".join(c if c.isprintable() else "?" for c in _one_line(text))
    if len(flat) <= limit:
        return flat
    return "…" + flat[-(limit - 1):] if tail else flat[:limit - 1] + "…"


def _key_text(key: str) -> str:
    """A key as the brief names it: bare when it is a plain name, else JSON-encoded."""
    shown = key if _PLAIN_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=True)
    return _part(shown, _KEY_CHARS)


def _value_text(value: Any) -> str:
    try:
        shown = json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        shown = "?"
    return _part(shown, _VALUE_CHARS)


def _entry(setting: Any, project_dir: Path) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "value": setting.value, "source": setting.source,
        "path": (None if setting.path is None
                 else _display_path(setting.path, project_dir)),
    }
    if setting.section is not None:
        entry["section"] = setting.section
    if setting.problem is not None:
        entry["problem"] = _problem_doc(setting.problem, project_dir)
    return entry


def _problem_doc(problem: Any, project_dir: Path) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"kind": problem.kind, "key": problem.key,
                           "path": _display_path(problem.path, project_dir)}
    if problem.kind == _config.BAD_VALUE:
        doc["value"] = _json_safe(problem.value)
    return doc


def status_settings(project_dir: Path, schema: Optional[Dict[str, Any]] = None,
                    today: Optional[date] = None) -> Dict[str, Any]:
    """The ``settings`` and ``legacy`` keys of ``status --json``, resolved from the
    project root (the config layers of the root only, never a nested repo's).

    ``settings`` holds the keys of the settings line, then each other leaf with a
    problem, then each kind of a group that a settings file names with a value outside
    its set and that is no leaf: ``{value, source, path[, section][, problem]}``. The
    value is the one every reader uses: on a bad value, the default (None for a kind
    that is no leaf). ``problem`` is ``{kind, key, path[, value]}``: ``bad-value`` with
    the key and the value as the file writes them (a group's key when the whole group
    is bad), or ``not-json`` for a settings file the walk skipped. A path is relative
    to the project root, or starts with ``~``. ``legacy`` is ``{count, until, ended}``.
    """
    resolved = project_settings(project_dir, schema=schema, today=today)
    settings: Dict[str, Any] = {
        key: _entry(resolved.get(key), project_dir) for key in STATUS_KEYS
    }
    for key, setting in resolved.settings.items():
        if setting.problem is not None and key not in settings:
            settings[key] = _entry(setting, project_dir)
    covered = {(entry["problem"]["path"], entry["problem"]["key"])
               for entry in settings.values() if "problem" in entry}
    for problem in resolved.problems:
        if problem.kind != _config.BAD_VALUE or problem.key is None:
            continue
        doc = _problem_doc(problem, project_dir)
        if (doc["path"], doc["key"]) in covered or problem.key in settings:
            continue
        covered.add((doc["path"], doc["key"]))
        settings[problem.key] = {"value": None, "source": _config.SOURCE_DEFAULT,
                                 "path": None, "problem": doc}
    return {
        "settings": settings,
        "legacy": {"count": len(resolved.legacy), "until": resolved.legacy_until,
                   "ended": resolved.legacy_ended},
    }


def settings_lines(status: Dict[str, Any]) -> List[str]:
    """The settings lines of the status brief, from the ``settings`` and ``legacy``
    keys of ``status_settings``; [] when the status has none.

    The first line names each key of the settings line with its value and source. Then
    one line per key that a settings file sets to a value outside its set (at most
    MAX_BAD_SETTING_LINES, then one line with the count of the rest), one line per
    settings file that cannot be read, and, once the schema names a grace date and
    legacy lines exist, the legacy line. Every piece that a file supplies is one line
    and clipped: the brief goes into the session prompt.
    """
    settings = status.get("settings")
    if not isinstance(settings, dict):
        return []
    parts = []
    for key in STATUS_KEYS:
        entry = settings.get(key)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        shown = value if isinstance(value, str) else _value_text(value)
        parts.append(f"{key}={_part(shown, _VALUE_CHARS)} "
                     f"({_part(str(entry.get('source')), _VALUE_CHARS)})")
    lines = ["settings: " + " · ".join(parts)] if parts else []

    bad: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    seen = set()
    for entry in settings.values():
        problem = entry.get("problem") if isinstance(entry, dict) else None
        if not isinstance(problem, dict):
            continue
        if problem.get("kind") == _config.BAD_VALUE:
            mark = (problem.get("path"), problem.get("key"))
            if mark not in seen:
                seen.add(mark)
                bad.append(problem)
        elif problem.get("kind") == _config.NOT_JSON:
            path = str(problem.get("path"))
            if path not in unreadable:
                unreadable.append(path)
    for problem in bad[:MAX_BAD_SETTING_LINES]:
        lines.append(_clip(
            f"settings: bad value, so the default applies: "
            f"{_key_text(str(problem.get('key')))} = {_value_text(problem.get('value'))} "
            f"({_part(str(problem.get('path')), _PATH_CHARS, tail=True)})"))
    if len(bad) > MAX_BAD_SETTING_LINES:
        lines.append(f"settings: {len(bad) - MAX_BAD_SETTING_LINES} more bad values — "
                     "journal.py config names them")
    for path in unreadable:
        lines.append(_clip(
            f"settings: {_part(path, _PATH_CHARS, tail=True)} cannot be read, so its "
            "settings are skipped — journal.py config names the fault"))

    legacy = status.get("legacy")
    if isinstance(legacy, dict) and legacy.get("until") and legacy.get("count"):
        count = int(legacy["count"])
        until = _part(str(legacy["until"]), 10)
        noun = "line" if count == 1 else "lines"
        them = "it" if count == 1 else "them"
        if legacy.get("ended"):
            lines.append(
                f"settings: {count} legacy {noun} in shipgate.md: the grace ended "
                f"{until}, and the next shipgate release stops reading {them} — "
                f"/shipgate:setup moves {them}")
        else:
            verb = "is" if count == 1 else "are"
            lines.append(
                f"settings: {count} legacy {noun} in shipgate.md {verb} still read until "
                f"{until} — /shipgate:setup moves {them}")
    return lines


# --------------------------------------------------------------------------
# `doctor`'s settings report (ADR 0028, D1; PRD FR-012)
# --------------------------------------------------------------------------


def settings_report(project_dir: Path) -> Optional[Dict[str, Any]]:
    """``doctor``'s ``settings`` block: ``{problems, legacy, nested_files, grace}``, or
    None when the schema cannot be read (an incomplete install; the rest of the report
    still stands).

    ``problems``: each problem the resolver finds from the project root, as ``{kind,
    path, key, value, message}`` (a value outside its set, a bad legacy line, an unknown
    key, a ``project`` key in the user settings file, a newer version, a file that is
    no JSON object). ``legacy``: each legacy line of the root's config layers, the user
    config and each nested repo's config, as ``{path, section, bullet, key, value}``.
    ``nested_files``: each ``.claude/shipgate.json`` of a nested repo, which marks a
    second project root inside this one. ``grace``: ``{until, ended}``. The paths are
    absolute. Nothing here changes the exit code.
    """
    try:
        schema = _config.load_schema()
    except OSError:
        return None
    resolved = project_settings(project_dir, schema=schema)
    nested = _config.nested_repo_dirs(project_dir)
    nested_configs = _config.read_layers(
        [(repo / _config.CONFIG_RELPATH, _config.ROLE_PROJECT) for repo in nested], None)
    legacy = list(resolved.legacy) + _config.legacy_lines(nested_configs, schema)
    nested_files = [str(repo / _config.SETTINGS_RELPATH) for repo in nested
                    if (repo / _config.SETTINGS_RELPATH).is_file()]
    return {
        "problems": [
            {"kind": p.kind, "path": p.path, "key": p.key, "value": _json_safe(p.value),
             "message": p.message}
            for p in resolved.problems
        ],
        "legacy": [line._asdict() for line in legacy],
        "nested_files": nested_files,
        "grace": {"until": resolved.legacy_until, "ended": resolved.legacy_ended},
    }


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def render_settings_report(report: Optional[Dict[str, Any]],
                           project_dir: Path) -> List[str]:
    """The text lines of ``doctor``'s settings block."""
    if report is None:
        return ["settings        : unknown (settings.schema.json unreadable)"]
    grace = report["grace"]
    if grace["until"] is None:
        when = "no grace date set"
    elif grace["ended"]:
        when = f"the grace ended {_one_line(grace['until'])}"
    else:
        when = f"legacy lines are read until {_one_line(grace['until'])}"
    lines = [
        "settings        : "
        + ", ".join((_count(len(report["problems"]), "problem"),
                     _count(len(report["legacy"]), "legacy line"),
                     _count(len(report["nested_files"]), "nested settings file")))
        + f"; {when}"
    ]
    # A checkout writes these values: each piece is one line, and a character that does
    # not print shows as `?` (the brief's rule; `doctor` output reaches the model too).
    lines.extend(f"problem         : {_part(p['message'], _DOCTOR_CHARS)}"
                 for p in report["problems"])
    for line in report["legacy"]:
        lines.append(
            "legacy line     : "
            + _part(f"{_display_path(line['path'], project_dir)} ## {line['section']} "
                    f"{line['bullet']}: {line['value']}", _DOCTOR_CHARS))
    for path in report["nested_files"]:
        lines.append(
            "nested settings : "
            + _part(_display_path(path, project_dir), _DOCTOR_CHARS)
            + " — a second project root inside this one; move its settings into the "
              "project settings file and delete it (/shipgate:setup)")
    return lines
