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
   startup, so both are imported lazily — measured, not guessed. A hook script runs as
   `__main__`, so Python compiles its whole source on every run, with no `.pyc`: code that
   only a rare path needs lives in a module imported on that path (`_nudge.py`, ADR 0022).
3. **Hold no policy.** Hooks locate the journal and shell out; every rule about what is
   valid lives in `scripts/journal.py`, so the event taxonomy can grow without touching
   a single hook. The run log (ADR 0032) is the one exception: `_runs.py` writes its
   rows itself, because a `journal.py` process on every Bash call costs tens of
   milliseconds, and it holds only the exit-status table of ADR 0032.
"""

from __future__ import annotations

import os
import sys

SIDECAR_RELPATH = os.path.join(".claude", "shipgate.json")
DEFAULT_DB_RELPATH = os.path.join(".claude", "shipgate.db")
JOURNAL_TIMEOUT_SECONDS = 15
GIT_TIMEOUT_SECONDS = 2
MAX_BRANCH_LENGTH = 255
MAX_WATCH_PATHS = 500
MAX_GIT_POINTER_BYTES = 4096
# ADR 0023 §12: a session's request marker is a file named by its session id. Only a
# plain token is a file name here: no `/`, no `.`, no empty name, at most 128 characters.
# `\A`/`\Z`, not `^`/`$`: `$` also matches before a trailing newline.
# The variable Claude Code sets to the session id in every hook and shell it starts.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
SESSION_ID_PATTERN = r"\A[A-Za-z0-9_-]{1,128}\Z"
REQUESTS_SUFFIX = ".requests"
_SESSION_ID_RE = None
# The settings file format this shipgate writes and reads: `x-version` of
# `settings.schema.json`, which names every key (ADR 0028; a test pins the two). The hooks
# read `db`, `artifact_homes` and `enforce`. A newer shipgate may write a higher version:
# this one warns and reads only the keys it knows.
SIDECAR_VERSION = 2
# ADR 0032: the Bash hooks log each observed run in `runs_root()/<session_id>.jsonl`, and
# rotate the file to `.jsonl.1` at RUNS_FILE_BYTES. The journal loads this module by path
# and reads the log with the same root and the same `run_fingerprint`.
RUNS_PARTS = ("shipgate", "runs")
RUNS_FILE_BYTES = 256 * 1024


def _session_id_re():
    """The compiled SESSION_ID_PATTERN, built on first use (rule 2: `re` costs ms)."""
    global _SESSION_ID_RE
    if _SESSION_ID_RE is None:
        import re

        _SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)
    return _SESSION_ID_RE


def __getattr__(name):
    """`SESSION_ID_RE` is compiled when a reader first asks for it, not at import."""
    if name == "SESSION_ID_RE":
        return _session_id_re()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def marker_path(db_path, session_id):
    """The request marker of `session_id`: `<db_path>.requests/<session_id>`, or None.

    None when the session id is not a str or is no plain token (SESSION_ID_PATTERN): it
    becomes a file name, so `/`, `..` and an empty name must never reach the path. The db
    path is resolved first, so the journal and the recorder name one marker for one db
    file whichever path to it they hold (a linked worktree's symlink). It creates
    nothing. journal.py writes the file at a `go-requested` append,
    and the recorder reads and removes it.
    """
    if not isinstance(session_id, str) or not _session_id_re().match(session_id):
        return None
    return os.path.join(os.path.realpath(str(db_path)) + REQUESTS_SUFFIX, session_id)


def runs_root():
    """`$CLAUDE_CONFIG_DIR/shipgate/runs` when the variable is set and not empty, else
    `$HOME/.claude/shipgate/runs`. None when neither variable is set, or when the chosen
    one is not an absolute path. The rule of the journal's `evidence_root()` (ADR 0031),
    and a test pins the two to one base: environment variables only, no file created."""
    config = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config:
        base = os.path.expanduser(config)
    else:
        home = os.environ.get("HOME", "")
        if not home:
            return None
        base = os.path.join(home, ".claude")
    if not os.path.isabs(base):
        return None
    return os.path.join(base, *RUNS_PARTS)


def run_fingerprint(command):
    """The run log's key of `command`, a str: the 8-byte BLAKE2b digest of the stripped
    text encoded UTF-8 with `surrogateescape`, as 16 hex digits (ADR 0032).

    `_blake2` first, because importing `hashlib` loads OpenSSL (rule 2). A Python built
    without `_blake2` gets `hashlib.blake2b`, which gives the same digest. A surrogate
    that `surrogateescape` cannot encode raises UnicodeEncodeError.
    """
    try:
        from _blake2 import blake2b
    except ImportError:
        from hashlib import blake2b
    data = command.strip().encode("utf-8", "surrogateescape")
    return blake2b(data, digest_size=8).hexdigest()


def sidecar_version_note(sidecar):
    """A one-line warning when the sidecar declares a newer format, else None.

    Only an integer `version` above SIDECAR_VERSION warns. A boolean is no version, and
    an absent, lower or non-integer value says nothing either: the keys known here are
    still read as they are.
    """
    if not isinstance(sidecar, dict):
        return None
    version = sidecar.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    if version <= SIDECAR_VERSION:
        return None
    return (
        f".claude/shipgate.json declares version {version}; this shipgate knows "
        f"version {SIDECAR_VERSION} and reads only the keys it knows. Update shipgate."
    )


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
        if not isinstance(candidate, str) or not candidate:
            continue
        for directory in _ancestors(candidate):
            if directory in seen:
                break
            seen.add(directory)
            if os.path.isfile(os.path.join(directory, SIDECAR_RELPATH)):
                return directory
    return None


def likely_journaled():
    """Cheapest possible pre-check, using only the ambient environment.

    Deliberately blind to the payload's cwd, which is only readable after stdin —
    the cost of rule 2: a session whose cwd alone is journaled gets no brief.
    """
    return journaled_root(os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd())


def _read_pointer(path):
    """The first line of a small regular file, or None — never blocks, never reads much.

    The files read here (`.git`, `gitdir`, `commondir`) sit in a checkout, which is
    untrusted content: `path` may be a FIFO or a device, and a plain `open()` would hang
    the hook on it.
    """
    import stat

    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        raw = os.read(fd, MAX_GIT_POINTER_BYTES)
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    line = raw.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    return line or None


def main_worktree(directory):
    """The main worktree of the linked worktree at `directory`, or None.

    A linked worktree's `.git` is a file, `gitdir: <common>/worktrees/<name>`, and that
    directory holds `commondir` (the shared git dir, relative to it) and `gitdir` (the
    path back to the worktree's `.git`). Only that exact shape counts: the git dir sits
    outside the worktree, directly under `<common>/worktrees/`, and its back-link names
    this worktree. A submodule's `.git` file has no `commondir`, and a bare repository
    has no main worktree. A `.git` file written into a checkout cannot borrow another
    checkout's journal: the files it would need sit in that other repository's own git
    dir, which the checkout does not hold. No subprocess: this runs inside the hooks.
    """
    real_directory = os.path.realpath(directory)
    git_entry = os.path.join(directory, ".git")
    if os.path.islink(git_entry):
        return None
    line = _read_pointer(git_entry)
    if not line or not line.startswith("gitdir:"):
        return None
    git_dir = os.path.realpath(os.path.join(directory, line[len("gitdir:"):].strip()))
    if git_dir.startswith(real_directory.rstrip(os.sep) + os.sep):
        return None  # git keeps a worktree's git dir outside it; this one is planted
    common = _read_pointer(os.path.join(git_dir, "commondir"))
    back = _read_pointer(os.path.join(git_dir, "gitdir"))
    if not common or not back:
        return None
    if os.path.realpath(os.path.join(git_dir, back)) != os.path.realpath(git_entry):
        return None
    common = os.path.realpath(os.path.join(git_dir, common))
    if os.path.dirname(git_dir) != os.path.join(common, "worktrees"):
        return None
    if os.path.basename(common) != ".git":
        return None  # a bare repository: no main worktree holds a journal
    main = os.path.dirname(common)
    if main == real_directory:
        return None
    return main


def current_branch(cwd):
    """The branch checked out in `cwd`, or None when there is no name worth passing.

    A detached HEAD answers with the literal `HEAD`, which is not a branch and matches
    no stream. No git, no repository and a hung git all land here as None as well: the
    branch is evidence the journal matches a stream on, and failing to read it loses that
    evidence, never the hook's answer. The SessionStart brief and the command gate read
    the branch here.
    """
    import subprocess

    if not isinstance(cwd, str):
        return None
    # `GIT_DIR`/`GIT_WORK_TREE` inherited from the session point git at whatever
    # repository set them, not at `cwd`; drop the whole family rather than guess.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return branch_name((result.stdout or "").strip())


def branch_name(text):
    """`text` as a branch name worth passing on, else None.

    The name travels as one argv token: a NUL would make `subprocess` refuse the whole
    call, a control character has no business in a branch. Over-long names are noise.
    """
    if not text or len(text) > MAX_BRANCH_LENGTH or text == "HEAD":
        return None
    if "\0" in text or not text.isprintable():
        return None
    return text


def _declared_db(sidecar):
    """The sidecar's `db`, `~` expanded, or the default; relative values stay relative."""
    raw = sidecar.get("db") if isinstance(sidecar.get("db"), str) else None
    return os.path.expanduser(raw or DEFAULT_DB_RELPATH)


def _own_db_path(root, sidecar):
    """A sidecar's `db` against its own directory: absolute values as given."""
    path = _declared_db(sidecar)
    return path if os.path.isabs(path) else os.path.join(root, path)


def sidecar_db_path(root, sidecar):
    """The journal a sidecar at `root` names, as a path; absolute `db` values as given.

    A relative `db` (the default one included) resolves against the sidecar's directory,
    except in a linked worktree of a repository that commits its sidecar: there it
    resolves against the main worktree, when that holds a sidecar too, so every worktree
    shares the main checkout's journal instead of starting an empty one of its own. The
    main checkout's file gives the place only: whether this project has a journal at all
    is its own file's word (`load_project`), so a main `db` of null reads as the default.
    """
    if os.path.isabs(_declared_db(sidecar)):
        return _declared_db(sidecar)
    main = main_worktree(root)
    # isfile first, as journaled_root does: read_sidecar's open() would block on a FIFO.
    if main is not None and os.path.isfile(os.path.join(main, SIDECAR_RELPATH)):
        main_sidecar = read_sidecar(main)
        if main_sidecar is not None:
            # The main checkout's own setting, never followed further: one hop at most.
            return _own_db_path(main, main_sidecar)
    return _own_db_path(root, sidecar)


class Project:
    """A journaled project: where it lives, its sidecar, and how to reach the journal."""

    def __init__(self, root, sidecar):
        self.root = root
        self.sidecar = sidecar
        self._db_path = None

    @property
    def db_path(self):
        if self._db_path is None:
            self._db_path = sidecar_db_path(self.root, self.sidecar)
        return self._db_path

    @property
    def journal_paths(self):
        """The journal db and its SQLite siblings — never artifacts, whatever globs say.

        The db sits under `.claude/`, so an artifact glob can match it; capturing writes
        to the journal as journal events would feed it its own noise.
        """
        db = os.path.realpath(self.db_path)
        return frozenset({db, db + "-wal", db + "-shm"})

    @property
    def artifact_globs(self):
        """The glob of each artifact home; none when `artifact_homes` is no object."""
        homes = self.sidecar.get("artifact_homes")
        if not isinstance(homes, dict):
            return []
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

        if os.path.realpath(path) in self.journal_paths:
            return False
        relative = self.relative(path).replace(os.sep, "/")
        if relative.startswith(".."):
            return False
        return any(fnmatch(relative, pattern) for pattern in self.artifact_globs)


def parse_sidecar(text):
    """The settings file's text as JSON: `(value, strict)`. ValueError when it is no JSON.

    `strict` is False when the text holds `NaN`, `Infinity` or `-Infinity`: Python's json
    reads them, and JavaScript's JSON.parse, which shipgate-hud reads the file with,
    refuses them. journal.py parses the file here too, so the three readers share one rule.
    """
    import json

    constants = []

    def constant(name):
        constants.append(name)
        return float(name)

    return json.loads(text, parse_constant=constant), not constants


def _settings_at(root):
    """The settings file at `root`: `(dict, strict)`, or `(None, True)` when it is
    unreadable or no object."""
    try:
        with open(os.path.join(root, SIDECAR_RELPATH), encoding="utf-8") as handle:
            sidecar, strict = parse_sidecar(handle.read())
    except (OSError, ValueError, RecursionError):
        # A corrupt file disables the hooks; it never crashes a session. RecursionError:
        # nesting deeper than this Python's json reads.
        return None, True
    return (sidecar, strict) if isinstance(sidecar, dict) else (None, True)


def read_sidecar(root):
    """The settings file at `root` as a dict, or None when it is unreadable or no object."""
    return _settings_at(root)[0]


def declares_no_journal(sidecar, strict):
    """True when the settings file says `"db": null` (ADR 0028, J2).

    Only a `db` key whose value is JSON null declares no journal, and only in a file
    that is strict JSON (`parse_sidecar`): the HUD cannot read a file with `NaN` or
    `Infinity`, so such a file keeps its journal, and the hooks, journal.py and the HUD
    agree. A missing `db` keeps the default journal, and a `db` of any other type is a
    bad value that also keeps it: a malformed value never turns a gate off.
    """
    return (strict and isinstance(sidecar, dict) and "db" in sidecar
            and sidecar["db"] is None)


def _project_at(root):
    """`(project, unreadable)` for the settings file at `root`: the journaled project,
    else None; and the file's path when the hooks cannot read it as a JSON object."""
    sidecar, strict = _settings_at(root)
    if sidecar is None:
        return None, os.path.join(root, SIDECAR_RELPATH)
    if declares_no_journal(sidecar, strict):
        return None, None
    return Project(root=root, sidecar=sidecar), None


def load_project(root):
    """The journaled project whose settings file sits at `root`, or None.

    None when the file is unreadable or malformed, and when it declares no journal
    (`"db": null`): the file still marks the project root, so the walk stops here, and
    every hook acts as in a project with no settings file.
    """
    return _project_at(root)[0]


def find_project(*candidates):
    root = journaled_root(*candidates)
    return load_project(root) if root else None


def _payload_root(payload):
    """The project root of a hook payload: the walk from its cwd, else (a malformed
    payload) from the ambient directories. `resolve_project` says why."""
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(cwd, str) and cwd:
        return journaled_root(cwd)
    return journaled_root(os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd())


def resolve_project(payload):
    """The journaled project a hook payload belongs to, or None.

    The payload's cwd is the session's own directory, so when it is there it is the
    only candidate considered: falling through to the ambient dirs after it would let
    a session in an un-journaled directory write into whichever journaled project
    happens to be an ancestor of the hook process. Only a missing or non-string cwd
    falls back — that is a malformed payload, not a session saying "not here".
    """
    return resolve_project_or_unreadable(payload)[0]


def resolve_project_or_unreadable(payload):
    """`(project, unreadable)`: `resolve_project`'s project, and, when there is none
    because the hooks cannot read the settings file at the root as a JSON object, that
    file's path (the hooks fail open, so every gate is off). One read of the file."""
    root = _payload_root(payload)
    if root is None:
        return None, None
    return _project_at(root)


def watch_paths(project):
    """Absolute paths of the artifact files to watch this session.

    `watchPaths` takes literal absolute paths — it is not glob-aware — so the globs in
    the sidecar have to be expanded here, and the list is only ever as current as the
    moment it was built. Two things keep that from rotting: `file_changed.py` returns a
    freshly expanded list every time it fires, and `post_tool_use.py` independently
    catches files created through Write/Edit, and through a Bash call whose own evidence
    names them. The residual gap is a brand-new artifact created by a Bash call that
    claims nothing (a background command, a name the command text never spells out) in
    a session where nothing else changed — it goes unwatched until the next expansion.
    """
    from glob import glob

    found = []
    seen = set()
    excluded = project.journal_paths
    for pattern in project.artifact_globs:
        try:
            matches = glob(os.path.join(project.root, pattern), recursive=True)
        except (ValueError, OSError):
            continue
        for match in matches:
            resolved = os.path.abspath(match)
            if resolved in seen or not os.path.isfile(resolved):
                continue
            if os.path.realpath(match) in excluded:
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


def run_journal(project, args, stdin_text=None, *, timeout=None, session=None):
    """Invoke the journal CLI. Returns None when it could not be run at all.

    `stdin_text` feeds `append --batch`; without it the child's stdin is closed, so a
    journal that ever tried to read it could not hang the hook. `timeout` is in seconds,
    JOURNAL_TIMEOUT_SECONDS when not given. `session` sets the child's
    `CLAUDE_CODE_SESSION_ID`, the id journal.py labels and scopes its work by; without it
    the child inherits the hook's environment unchanged.
    """
    import subprocess

    script = journal_script()
    if not os.path.isfile(script):
        return None
    command = [sys.executable, script, "--db", project.db_path, *args]
    options = (
        {"stdin": subprocess.DEVNULL} if stdin_text is None else {"input": stdin_text}
    )
    if session is not None:
        options["env"] = {**os.environ, SESSION_ENV: session}
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=JOURNAL_TIMEOUT_SECONDS if timeout is None else timeout,
            cwd=project.root,
            **options,
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


def append_events(project, stream, event_type, payloads):
    """Append several events of one type in a single journal run, ignoring failure.

    One `append --batch` instead of one process per event: a Bash call can change many
    artifacts at once, and the hook's own timeout is shorter than that many spawns.
    """
    import json

    lines = [
        json.dumps({"type": event_type, "data": data}, separators=(",", ":"))
        for data in payloads
    ]
    if not lines:
        return
    run_journal(
        project,
        ["append", "--stream", stream, "--batch", "--actor", "hook"],
        stdin_text="\n".join(lines) + "\n",
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
