"""The settings as the journal shows them (ADR 0028): ``journal.py config``.

The resolver is ``_config.resolve_settings``; ``project.project_settings`` feeds it the
files of one project. This module only prints what it returns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .vocab import EXIT_OK, UsageError
from .plugin import _config
from .text import _one_line
from .project import find_sidecar, project_settings, setting_source


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
        "problems": [problem._asdict() for problem in resolved.problems],
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
