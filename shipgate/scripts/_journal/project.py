"""Which project and journal a directory belongs to: sidecar, db path, config files."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from .vocab import (
    DEFAULT_ARTIFACT_HOMES, DEFAULT_LEDGER, InfraError, LEDGER_NUDGE_THRESHOLD,
)
from .plugin import (
    _config, _hooks_common, DEFAULT_DB_RELPATH, journaled_root, SIDECAR_RELPATH,
)


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
    """The nearest ``.claude/shipgate.json`` from start_dir up to the filesystem root.

    The walk is the hooks' own (``journaled_root``), so a session's hooks and this CLI
    always pick the same journal. A nested ``.git`` is no boundary: a linked worktree
    (``.git`` file) or an independent repo (``.git`` directory) inside a journaled
    project uses that project's journal, not a second one under its own directory.
    """
    root = journaled_root(str(start_dir))
    if root is None:
        return None
    project_dir = Path(root).resolve()
    return _load_sidecar(project_dir / SIDECAR_RELPATH, project_dir)


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
    _warn_sidecar_version(config)
    return Sidecar(path=path, project_dir=project_dir, config=config)


# Set once the newer-sidecar warning is printed: once per process is enough.
_sidecar_version_warned = False


def _warn_sidecar_version(config: Dict[str, Any]) -> None:
    """Say on stderr, once per run, that the sidecar is newer than this shipgate.

    The run goes on: the keys this shipgate knows are read as they are. The hooks'
    SessionStart line carries the same text (`_hooks_common.sidecar_version_note`).
    """
    global _sidecar_version_warned
    if _sidecar_version_warned:
        return
    note = _hooks_common.sidecar_version_note(config)
    if note:
        _sidecar_version_warned = True
        print(f"journal.py: {note}", file=sys.stderr)


def _resolve_against(base: Path, value: str) -> Path:
    # `base / absolute` yields the absolute path, so this handles both cases;
    # resolve() normalizes symlinked parents so db paths compare equal.
    return (base / Path(value).expanduser()).resolve()


def resolve_db(db_flag: Optional[str], cwd: Path) -> Resolution:
    """Work out which database to use.

    ``--db`` wins. Otherwise the sidecar's ``db`` key (default
    ``.claude/shipgate.db``), with relative values resolved against the sidecar's
    *project directory* (never the cwd, because hooks invoke this script from
    arbitrary directories), or against the main worktree when that directory is a
    linked worktree with a committed sidecar. With no sidecar, the default under
    the cwd.
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
        # The hooks' rule, so both reach one journal: a relative db (the default one
        # included) resolves against the sidecar's directory, or against the main
        # worktree in a linked worktree that carries a committed sidecar.
        declared = sidecar.config.get("db")
        return Resolution(
            db_path=Path(
                _hooks_common.sidecar_db_path(str(sidecar.project_dir), sidecar.config)
            ).resolve(),
            sidecar=sidecar,
            project_dir=project_dir,
            source="sidecar" if isinstance(declared, str) and declared else "default",
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
        return Path(
            _hooks_common.sidecar_db_path(str(sidecar.project_dir), sidecar.config)
        ).resolve()
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


def _config_label(config: Any, project_dir: Path) -> str:
    """``user file``, else the file's path relative to the journal's project root."""
    if config.role == _config.ROLE_USER:
        return "user file"
    try:
        return config.path.resolve().relative_to(project_dir.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        return config.path.name


def config_candidates(project_dir: Path,
                      start: Optional[Path] = None) -> List[Tuple[Path, str]]:
    """ADR 0018's layer list as journal.py sees it, nearest first, for
    ``_config.read_layers``: each ``.claude/shipgate.md`` from ``start`` up to the repo
    that holds it (role ``project``), then the repo's parent and the journal's project
    root (role ``umbrella``), the two umbrella files ``signals.py`` reads. A directory
    between those two is no layer. With no repo below the project root, every file from
    ``start`` up to the root is ``project``. A ``start`` outside the project root, or
    None, reads the root only. No subprocess: a repo is a directory with a ``.git``
    entry (a linked worktree's ``.git`` is a file, and counts).
    """
    root = project_dir.resolve()
    try:
        here = (start or root).resolve()
    except (OSError, RuntimeError):
        here = root
    if here != root and root not in here.parents:
        return [(root / _config.CONFIG_RELPATH, _config.ROLE_PROJECT)]
    chain = [here] + [parent for parent in here.parents if root in parent.parents]
    chain = chain + [root] if chain[-1] != root else chain
    repo = next((d for d in chain if os.path.lexists(str(d / ".git"))), None)
    if repo is None or repo == root:
        return [(directory / _config.CONFIG_RELPATH, _config.ROLE_PROJECT)
                for directory in chain]
    candidates = [(directory / _config.CONFIG_RELPATH, _config.ROLE_PROJECT)
                  for directory in chain[:chain.index(repo) + 1]]
    for directory in dict.fromkeys((repo.parent, root)):
        candidates.append((directory / _config.CONFIG_RELPATH, _config.ROLE_UMBRELLA))
    return candidates


def _config_files(project_dir: Path, start: Optional[Path]) -> List[Any]:
    return _config.read_layers(config_candidates(project_dir, start),
                               _config.user_config_path())
