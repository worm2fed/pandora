"""Shared helpers for shipgate's hooks.

Every hook here obeys three rules, and they are the whole reason this module exists:

1. **Never break the user's session.** A hook that raises, or that exits non-zero for
   anything other than a deliberate policy block, degrades the harness for work that has
   nothing to do with shipgate. `safe_main` turns every unexpected failure into exit 0.
2. **Cost nothing on projects that aren't journaled.** Plugin hooks installed at user
   scope fire in *every* project the user opens, and `PostToolUse`/`FileChanged` fire on
   every single edit. So the fast path is ordered cheapest-first: locate the sidecar with
   a few `stat` calls before parsing stdin, and import nothing heavy until we know the
   project is journaled. `subprocess` (~10ms) and `pathlib` (~7ms) dominate this script's
   startup, so both are imported lazily — measured, not guessed.
3. **Hold no policy.** Hooks locate the journal and shell out; every rule about what is
   valid lives in `scripts/journal.py`, so the event taxonomy can grow without touching
   a single hook.
"""

from __future__ import annotations

import os
import sys

SIDECAR_RELPATH = os.path.join(".claude", "shipgate.json")
DEFAULT_DB_RELPATH = os.path.join(".claude", "shipgate.db")
JOURNAL_TIMEOUT_SECONDS = 15
MAX_WATCH_PATHS = 500


def _ancestors(start):
    """Yield `start` and each parent directory, up to the filesystem root."""
    current = os.path.abspath(start)
    while True:
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def journaled_root(*candidates):
    """Return the nearest ancestor directory holding a sidecar, or None.

    This is the fast path's gate. It runs before stdin is read and before any heavy
    import, because on an un-journaled project it is the only work the hook should do.
    """
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        for directory in _ancestors(candidate):
            if directory in seen:
                break
            seen.add(directory)
            if os.path.isfile(os.path.join(directory, SIDECAR_RELPATH)):
                return directory
    return None


def likely_journaled():
    """Cheapest possible pre-check, using only the ambient environment."""
    return journaled_root(os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd())


class Project:
    """A journaled project: where it lives, its sidecar, and how to reach the journal."""

    def __init__(self, root, sidecar):
        self.root = root
        self.sidecar = sidecar

    @property
    def db_path(self):
        raw = self.sidecar.get("db") or DEFAULT_DB_RELPATH
        path = os.path.expanduser(raw)
        return path if os.path.isabs(path) else os.path.join(self.root, path)

    @property
    def artifact_globs(self):
        homes = self.sidecar.get("artifact_homes") or {}
        return [pattern for pattern in homes.values() if isinstance(pattern, str)]

    def enforces(self, knob):
        """Enforcement knobs default ON; only an explicit `false` turns one off."""
        enforce = self.sidecar.get("enforce")
        if not isinstance(enforce, dict):
            return True
        return enforce.get(knob) is not False

    def relative(self, path):
        try:
            return os.path.relpath(os.path.realpath(path), os.path.realpath(self.root))
        except (ValueError, OSError):
            return path

    def covers(self, path):
        """True when `path` sits under one of the configured artifact homes."""
        from fnmatch import fnmatch

        relative = self.relative(path).replace(os.sep, "/")
        if relative.startswith(".."):
            return False
        return any(fnmatch(relative, pattern) for pattern in self.artifact_globs)


def load_project(root):
    """Parse the sidecar at `root`. Returns None if it is unreadable or malformed."""
    import json

    try:
        with open(os.path.join(root, SIDECAR_RELPATH), encoding="utf-8") as handle:
            sidecar = json.load(handle)
    except (OSError, ValueError):
        return None  # A corrupt sidecar disables hooks; it never crashes a session.
    if not isinstance(sidecar, dict):
        return None
    return Project(root=root, sidecar=sidecar)


def find_project(*candidates):
    root = journaled_root(*candidates)
    return load_project(root) if root else None


def watch_paths(project):
    """Absolute paths of the artifact files to watch this session.

    `watchPaths` takes literal absolute paths — it is not glob-aware — so the globs in
    the sidecar have to be expanded here, and the list is only ever as current as the
    moment it was built. Two things keep that from rotting: `file_changed.py` returns a
    freshly expanded list every time it fires, and `post_tool_use.py` independently
    catches files created through Write/Edit. The residual gap is a brand-new artifact
    created by a Bash heredoc in a session where nothing else changed — it goes
    unwatched until the next expansion.
    """
    from glob import glob

    found = []
    seen = set()
    for pattern in project.artifact_globs:
        try:
            matches = glob(os.path.join(project.root, pattern), recursive=True)
        except (ValueError, OSError):
            continue
        for match in matches:
            resolved = os.path.abspath(match)
            if resolved in seen or not os.path.isfile(resolved):
                continue
            seen.add(resolved)
            found.append(resolved)
            if len(found) >= MAX_WATCH_PATHS:
                return found
    return found


def journal_script():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
        "journal.py",
    )


def run_journal(project, args):
    """Invoke the journal CLI. Returns None when it could not be run at all."""
    import subprocess

    script = journal_script()
    if not os.path.isfile(script):
        return None
    command = [sys.executable, script, "--db", project.db_path, *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=JOURNAL_TIMEOUT_SECONDS,
            cwd=project.root,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def append_event(project, stream, event_type, data):
    """Append an event, ignoring failure — capture must never block the harness."""
    import json

    run_journal(
        project,
        [
            "append",
            "--stream",
            stream,
            "--type",
            event_type,
            "--data",
            json.dumps(data, separators=(",", ":")),
            "--actor",
            "hook",
        ],
    )


def read_hook_input():
    import json

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def emit(payload):
    """Write a hook JSON response.

    Anything on stdout that isn't valid JSON is silently treated as plain text by the
    harness, so this is the only place a hook prints.
    """
    import json

    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def mtime_of(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def safe_main(main):
    """Run `main`, converting any unexpected failure into a clean exit 0.

    A hook that exits 1 is reported to the user as a hook error while the action
    proceeds anyway — noise with no benefit. Deliberate blocks call `sys.exit(2)` (or
    emit block JSON) themselves, and SystemExit passes straight through.
    """
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — a hook must never surface a traceback
        sys.exit(0)
