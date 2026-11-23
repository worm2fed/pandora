"""The plugin's own files (`hooks/_common.py`, `_config.py`, `plugin.json`) and the journal
commands the output prints.
"""

from __future__ import annotations

import json
import shlex
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_hooks_common():
    """The hooks' shared module, loaded by path: `hooks/` is not a package.

    The plugin always ships `hooks/` beside `scripts/`; without it this script cannot
    know which project a directory belongs to, so it stops with an infrastructure error
    (exit 1). The same loader sits in `signals.py`: keep the two in step.
    """
    import importlib.util

    path = Path(__file__).resolve().parent.parent.parent / "hooks" / "_common.py"
    try:
        spec = importlib.util.spec_from_file_location("shipgate_hooks_common", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        sys.exit(f"error: cannot load {path} (shipgate install incomplete): {exc}")
    return module


# The hooks' sidecar walk, the only one: hooks and scripts must name the same project.
_hooks_common = _load_hooks_common()
journaled_root = _hooks_common.journaled_root
SIDECAR_RELPATH = _hooks_common.SIDECAR_RELPATH
DEFAULT_DB_RELPATH = _hooks_common.DEFAULT_DB_RELPATH


def _load_config_module():
    """The config reader shared with `signals.py`, loaded by path: `scripts/` is not a
    package. Without it the doctor cannot read `.claude/shipgate.md`, so it stops with an
    infrastructure error (exit 1), as `_load_hooks_common` does.
    """
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "_config.py"
    try:
        spec = importlib.util.spec_from_file_location("shipgate_config", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        sys.exit(f"error: cannot load {path} (shipgate install incomplete): {exc}")
    return module


_config = _load_config_module()


def plugin_version() -> str:
    manifest = Path(__file__).resolve().parent.parent.parent / ".claude-plugin" / "plugin.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    version = payload.get("version")
    return str(version) if version else "unknown"


# The question text a printed go request leaves to the flow to write. `append` takes
# either as it stands, so a printed request runs as printed (#55).
CONFIRMING_QUESTION_PLACEHOLDER = "<the confirming question>"
GATE_QUESTION_PLACEHOLDER = "<the gate question>"


def _request_command(
    db_path: Path, stream: str, gate: str,
    question: str = CONFIRMING_QUESTION_PLACEHOLDER,
) -> Optional[str]:
    """The go request for ``gate`` of ``stream``, through `_suggest` (the interpreter,
    this script's absolute quoted path, ``--db``, ``--stream=``), or None when
    `_suggest` cannot print it (#52, #55)."""
    return _suggest(db_path, stream, "go-requested",
                    {"gate": gate, "question": question})


def _db_file(conn: sqlite3.Connection) -> Optional[Path]:
    """The file of the database ``conn`` opened, or None for one with no file."""
    for _, name, file in conn.execute("PRAGMA database_list"):
        if name == "main":
            return Path(file) if file else None
    return None


def closeout_command(stream: str) -> str:
    """``journal.py closeout --stream=<s>``, quoted, or ``NO_COMMAND`` for a name that
    does not print on one line (``_suggest``'s rule)."""
    command = "journal.py closeout --stream=" + shlex.quote(stream)
    return command if command.isprintable() else NO_COMMAND


def _suggest(db_path: Path, stream: str, event_type: str,
             data: Dict[str, Any]) -> Optional[str]:
    """A ready `append` for ``stream``, or None when its name cannot be printed.

    The command reaches the session inside the Stop block text. A stream name comes from
    the journal, so two shapes need care. A name that starts with ``-`` goes as
    ``--stream=<name>``: as a separate token argparse would read it as a flag and the
    command would fail. A name that holds a line break, or any other character that
    does not print on one line (``str.isprintable``), gets no command: collapsing a line
    break would address another stream, and printing it would add lines to the block
    text. The same holds for the whole command, whose db path comes from the sidecar.
    """
    from shlex import quote

    command = " ".join([
        *_journal_prefix(db_path),
        "append",
        "--stream=" + quote(stream),
        "--type", quote(event_type),
        "--data", quote(json.dumps(data, sort_keys=True)),
    ])
    return command if command.isprintable() else None


def _journal_prefix(db_path: Path) -> List[str]:
    """The quoted words that run this script on ``db_path``: the interpreter, this
    script's absolute path and ``--db`` (#55)."""
    from shlex import quote

    return ["python3", quote(str(Path(__file__).resolve().parent.parent / "journal.py")), "--db", quote(str(db_path))]


def _journal_command(db_path: Path, *args: str) -> Optional[str]:
    """A ready command of this script on ``db_path``, or None when it does not print on
    one line (see `_suggest`)."""
    from shlex import quote

    command = " ".join([*_journal_prefix(db_path), *(quote(arg) for arg in args)])
    return command if command.isprintable() else None


# What stands in for a command `_suggest` would not print.
NO_COMMAND = "(no command: a name in it holds a character that does not print on one line)"
