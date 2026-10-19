"""shipgate code graph — the one place that knows the `codegraph` CLI.

Private to ``signals.py``, which loads it by path. Python 3 standard library only.
See ``shipgate/docs/prd/code-graph.md``, its worklog, and ADR 0007.

Every failure here raises ``GraphUnavailable(reason)``; ``select`` turns it into a
``Selection`` with ``source="regex"``. Nothing here exits the process.

Writes, all outside tracked files (ADR 0007 §7): the `/.codegraph/` line in the
repository's `info/exclude`, the build lock and the two advisory markers under
`<git-common-dir>/shipgate/`, and the index itself (written by codegraph). The
database is only ever opened read-only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import subprocess
import time
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional,
                    Sequence, Set, Tuple)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

MODES = ("auto", "off", "root")
MIN_VERSION = (1, 6, 0)
INDEX_DIR = ".codegraph"
DB_NAME = "codegraph.db"
EXCLUDE_LINE = "/.codegraph/"
TRACKED_OK = ".codegraph/.gitignore"  # codegraph's own file; tracking it is fine
STATE_DIR = "shipgate"  # under the git common dir
LOCK_NAME = "codegraph.lock"
MARKER_NAME = "codegraph-advised"
TOO_LARGE_MARKER = "codegraph-too-large"  # the too-large advisory, shown once too
MIN_SCHEMA = 11  # `schema_versions` of codegraph 1.6
# The columns the reader needs; anything else in codegraph's schema is ignored.
REQUIRED_COLUMNS = {
    "nodes": {"id", "kind", "name", "file_path", "start_line", "end_line"},
    "edges": {"source", "target", "kind"},
    "files": {"path", "language"},
}

INIT_TIMEOUT = 120.0
CALL_TIMEOUT = 30.0
MAX_FILES = 10_000

# Overrides, for tests: the binary, one timeout for every call, the file guard.
ENV_BIN = "SHIPGATE_CODEGRAPH_BIN"
ENV_TIMEOUT = "SHIPGATE_CODEGRAPH_TIMEOUT"
ENV_MAX_FILES = "SHIPGATE_CODEGRAPH_MAX_FILES"

# Added to every codegraph call (FR-016); the user's own environment is unchanged.
CALL_ENV = {"CODEGRAPH_TELEMETRY": "0", "CODEGRAPH_NO_DAEMON": "1"}
# Dropped from every codegraph call, as `signals._git_env` drops them for git.
DROPPED_ENV = ("GIT_DIR", "GIT_WORK_TREE")

# The `graph` subcommand's actions; the first five take `-j` (node and explore
# print text only). All of them take `-p <path>`.
GRAPH_ACTIONS = ("impact", "callers", "callees", "affected", "query", "node",
                 "explore")
GRAPH_JSON_ACTIONS = ("impact", "callers", "callees", "affected", "query")
# The first line codegraph prints, with exit 0, when it has no answer: `impact`,
# `callers`, `callees` ("ℹ Symbol …", even with -j), `node` and `explore`.
# "ℹ" (U+2139) is a letter to `\w`, so the prefix is spelled out.
NOT_FOUND_RE = re.compile(
    r'^\s*(?:\u2139\s*)?(?:Symbol "[^"]*" not found|No relevant code found)')


def not_found(text: str) -> bool:
    """TEXT is codegraph's "no answer" message (its first non-empty line)."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    return NOT_FOUND_RE.match(first) is not None

ADVISORY = ("code graph: install codegraph for symbol-level impact and the tests a "
            "diff reaches (https://github.com/colbymchenry/codegraph); shown once")
TOO_LARGE = ("code graph: this repository tracks {count} files, more than the "
             "{limit} that shipgate indexes for you. Run `codegraph init` in {repo} "
             "yourself to use the graph")

# Detection failures: codegraph counts as absent (FR-001), which earns the advisory.
ABSENT_REASONS = ("graph-not-installed", "graph-version")

GitRunner = Callable[..., "subprocess.CompletedProcess"]


# --------------------------------------------------------------------------
# Errors and the result
# --------------------------------------------------------------------------


class GraphUnavailable(Exception):
    """The graph cannot serve this call; a reason, never an exit."""

    def __init__(self, reason: str, advisory: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.advisory = advisory


class Selection(NamedTuple):
    available: bool
    source: str  # graph | regex
    state: str  # present | absent | off | failed
    reason: Optional[str]
    index_root: Optional[Path]  # the directory codegraph runs on (`-p`)
    sync: str  # daemon | sync | none
    built: Optional[Dict[str, Any]]  # {files, seconds, bytes}, only on the build call
    advisory: Optional[str]  # one line for the user, when due
    version: Optional[str]
    repo: Optional[Path] = None  # the repository; `index_root` is shown relative to it

    def to_json(self) -> Dict[str, Any]:
        """The `structure.graph` block (the envelope adds `source` itself).

        `index_root` is relative to the repository (`.`, or `..` in root mode),
        never an absolute machine path (FR-018)."""
        index_root = None
        if self.index_root is not None:
            index_root = Path(os.path.relpath(self.index_root, self.repo or
                                              self.index_root)).as_posix()
        return {
            "state": self.state,
            "reason": self.reason,
            "version": self.version,
            "index_root": index_root,
            "built": dict(self.built) if self.built else None,
            "sync": self.sync,
        }


def _regex(state: str, reason: str, advisory: Optional[str] = None,
           version: Optional[str] = None) -> Selection:
    return Selection(False, "regex", state, reason, None, "none", None, advisory,
                     version)


# --------------------------------------------------------------------------
# Running codegraph
# --------------------------------------------------------------------------


def _inside(path: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def _candidates() -> Iterator[Tuple[str, str]]:
    """Every (PATH entry, executable) for `codegraph`, in PATH order, as
    `shutil.which` searches. On Windows the working directory comes first, as the
    entry `.`, and only the PATHEXT names count (Python 3.12's `which`: a bare
    `codegraph` is not run there)."""
    entries = os.environ.get("PATH", os.defpath).split(os.pathsep)
    names = ["codegraph"]
    if os.name == "nt":
        entries = [os.curdir, *entries]
        names = [f"codegraph{ext}" for ext in
                 os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if ext]
    for entry in entries:
        for name in names:
            candidate = os.path.join(entry or os.curdir, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                yield entry, candidate


def _which() -> Optional[Tuple[str, str]]:
    """The first (PATH entry, executable), as `shutil.which` would answer."""
    return next(_candidates(), None)


def _umbrella_ships(root: Path, executable: Path, run_git: GitRunner) -> bool:
    """The umbrella at ROOT supplies EXECUTABLE: it lies in ROOT's `.git`, or git
    tracks it. A root that is no git tree tracks nothing."""
    try:
        rel = executable.relative_to(Path(root).resolve())
    except ValueError:
        return False
    if rel.parts and rel.parts[0] == ".git":
        return True
    try:
        proc = run_git(Path(root), "ls-files", "-z", "--", rel.as_posix())
    except OSError:
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip("\0"))


def _refused(entry: str, found: str, repo: Optional[Path],
             umbrella_roots: Sequence[Path], run_git: Optional[GitRunner]) -> bool:
    if not entry or not os.path.isabs(entry):
        return True  # the working directory
    where = Path(entry).resolve()
    if repo is not None and _inside(where, [repo]):
        return True
    for root in umbrella_roots:
        if _inside(where, [root]):
            if run_git is None or _umbrella_ships(
                    root, where / os.path.basename(found), run_git):
                return True
    return False


def binary(repo: Optional[Path] = None, umbrella_roots: Sequence[Path] = (),
           run_git: Optional[GitRunner] = None) -> Optional[str]:
    """The codegraph executable, or None.

    The PATH entry that finds it decides, not where a symlink points: a normal
    install links `~/.local/bin/codegraph` into `~/.codegraph/`. An entry is
    refused when it is empty, `.` or relative (the working directory, searched
    first on Windows), or when it lies inside REPO: such a binary ships with the
    code under analysis. Inside an umbrella root (a dotfiles work tree at `$HOME`
    holds `~/.local/bin`), it is refused only when the umbrella tracks the binary
    or holds it in its `.git`; without RUN_GIT, always. A refused entry does not
    stop the walk: the first entry that passes wins. The env override is trusted,
    as every environment variable is.
    """
    override = os.environ.get(ENV_BIN)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) \
            else None
    for entry, found in _candidates():
        if not _refused(entry, found, repo, umbrella_roots, run_git):
            return found
    return None


# The executable each preflight chose, by resolved index root: every later call in
# the process runs the same binary, whichever PATH entries the choice skipped.
_CHOSEN: Dict[str, str] = {}


def _timeout(default: float) -> float:
    try:
        return float(os.environ[ENV_TIMEOUT])
    except (KeyError, ValueError):
        return default


def run(args: Sequence[str], cwd: Path, reason: str,
        timeout: float = CALL_TIMEOUT, stdin: Optional[str] = None) -> str:
    """Run codegraph ARGS in CWD; stdout, or GraphUnavailable(reason).

    STDIN, when given, is the process's input. A timeout is `graph-timeout`
    whatever the step.
    """
    exe = _CHOSEN.get(str(Path(cwd).resolve())) or binary(Path(cwd))
    if exe is None:
        raise GraphUnavailable("graph-not-installed")
    env = dict(os.environ)
    env.update(CALL_ENV)
    for name in DROPPED_ENV:
        env.pop(name, None)
    feed: Dict[str, Any] = ({"stdin": subprocess.DEVNULL} if stdin is None
                            else {"input": stdin.encode("utf-8")})
    try:
        proc = subprocess.run([exe, *args], cwd=str(cwd), env=env, capture_output=True,
                              timeout=_timeout(timeout), **feed)
    except subprocess.TimeoutExpired as exc:
        raise GraphUnavailable("graph-timeout") from exc
    except OSError as exc:
        raise GraphUnavailable(reason) from exc
    if proc.returncode != 0:
        raise GraphUnavailable(reason)
    return proc.stdout.decode("utf-8", "replace")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def status(index_root: Path) -> Dict[str, Any]:
    """`status --json PATH`, parsed. Called only after this process built PATH's
    index: on a path with no index of its own, codegraph walks up to the nearest
    indexed ancestor and answers for it, slowly (an umbrella root: 11-60 s)."""
    # status, sync and init take the path positionally: codegraph 1.6 has no `-p`
    # on them (only the query commands take `-p <path>`).
    out = run(["status", "--json", str(index_root)], index_root, "graph-status")
    try:
        parsed = json.loads(out)
    except ValueError as exc:
        raise GraphUnavailable("graph-status") from exc
    if not isinstance(parsed, dict):
        raise GraphUnavailable("graph-status")
    return parsed


def detect(index_root: Path, repo: Optional[Path] = None,
           umbrella_roots: Sequence[Path] = (),
           run_git: Optional[GitRunner] = None) -> str:
    """FR-001: on PATH and `--version` >= MIN_VERSION. Returns the version.

    `--version` walks no path, so it is cheap anywhere. Whether `status` parses is
    checked after a build (`ensure_index`), never here: see `status`. A binary
    inside REPO or an umbrella root counts as not installed (see `binary`).
    """
    roots = {str(Path(r).resolve()) for r in (index_root, repo) if r is not None}
    for key in roots:
        _CHOSEN.pop(key, None)
    exe = binary(repo or index_root, umbrella_roots, run_git)
    if exe is None:
        raise GraphUnavailable("graph-not-installed")
    for key in roots:
        _CHOSEN[key] = exe
    out = run(["--version"], index_root, "graph-version")
    version = parse_version(out)
    if version is None or version < MIN_VERSION:
        raise GraphUnavailable("graph-version")
    return ".".join(map(str, version))


def has_index(index_root: Path) -> bool:
    """INDEX_ROOT holds its own index: the database file, not `status`, decides."""
    return (Path(index_root) / INDEX_DIR / DB_NAME).is_file()


def check_trusted(index_root: Path, run_git: GitRunner) -> None:
    """Refuse an index the repository itself supplies: `graph-index-untrusted`.

    `.codegraph`, its database or its `.gitignore` is a symlink, `.codegraph` is
    spelled in another case, `.codegraph` resolves outside INDEX_ROOT, or git
    tracks anything under it in any case except `.codegraph/.gitignore` as a
    regular file (git mode 120000 is a link). A build would write through the
    link, and a read would serve a graph someone committed.
    """
    root = Path(index_root).resolve()
    index = root / INDEX_DIR
    if any(os.path.islink(p) for p in (index, index / DB_NAME, index / ".gitignore")):
        raise GraphUnavailable("graph-index-untrusted")
    # A case-insensitive file system (macOS, Windows) answers `.codegraph` for a
    # `.CodeGraph` entry: only codegraph's own spelling is ours.
    try:
        spellings = [n for n in os.listdir(root) if n.lower() == INDEX_DIR]
    except OSError:
        spellings = []
    if any(name != INDEX_DIR for name in spellings):
        raise GraphUnavailable("graph-index-untrusted")
    if os.path.lexists(index) and index.resolve().parent != root:
        raise GraphUnavailable("graph-index-untrusted")
    try:
        proc = run_git(root, "ls-files", "-s", "-z", "--", f":(icase){INDEX_DIR}")
    except OSError:
        return  # no git: nothing can be tracked
    if proc.returncode != 0:
        return
    for record in (r for r in proc.stdout.split("\0") if r):
        meta, _, path = record.partition("\t")  # "<mode> <sha> <stage>\t<path>"
        lowered = path.lower()
        if path == TRACKED_OK and not meta.startswith("120000"):
            continue  # codegraph writes this one for committing; a link is not it
        if lowered == INDEX_DIR or lowered.startswith(INDEX_DIR + "/"):
            raise GraphUnavailable("graph-index-untrusted")


# --------------------------------------------------------------------------
# Git paths — the exclude file, the lock and the marker
# --------------------------------------------------------------------------


def _git_path(repo: Path, run_git: GitRunner, *args: str) -> Optional[Path]:
    """A path `git rev-parse ARGS` prints, absolute; None when git fails."""
    try:
        proc = run_git(repo, "rev-parse", *args)
    except OSError:
        return None
    out = proc.stdout.strip() if proc.returncode == 0 else ""
    if not out:
        return None
    path = Path(out)
    return (path if path.is_absolute() else repo / path).resolve()


def exclude_index_dir(repo: Path, run_git: GitRunner) -> Path:
    """FR-003: add `/.codegraph/` to the repository's `info/exclude`, once.

    `--git-path` resolves a linked worktree to the common `info/exclude`. A failure
    here stops the build: an index the user's `git status` shows is worse than none.
    """
    exclude = _git_path(repo, run_git, "--git-path", "info/exclude")
    if exclude is None:
        raise GraphUnavailable("graph-exclude")
    try:
        text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if EXCLUDE_LINE in (line.strip() for line in text.splitlines()):
            return exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if not text or text.endswith("\n") else "\n"
        with open(exclude, "a", encoding="utf-8") as handle:
            handle.write(f"{prefix}{EXCLUDE_LINE}\n")
    except OSError as exc:
        raise GraphUnavailable("graph-exclude") from exc
    return exclude


class _Lock:
    """An exclusive `flock` on `<git-common-dir>/shipgate/codegraph.lock`.

    Best effort: no `fcntl` (Windows) or no writable git dir means no lock.
    """

    def __init__(self, path: Optional[Path]) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "_Lock":
        try:
            import fcntl
        except ImportError:
            return self
        if self.path is None:
            return self
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(self.path, "a")
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            self._close()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._close()

    def _close(self) -> None:
        if self.handle is not None:
            self.handle.close()  # closing the file releases the flock
            self.handle = None


def _state_dir(repo: Path, run_git: GitRunner) -> Optional[Path]:
    common = _git_path(repo, run_git, "--git-common-dir")
    return common / STATE_DIR if common is not None else None


def marker_path(repo: Path, run_git: GitRunner, umbrella_roots: Sequence[Path],
                name: str = MARKER_NAME) -> Optional[Path]:
    """`<git-common-dir>/shipgate/<name>` of the outermost git tree: the outermost
    umbrella root that is a git toplevel, else the repository."""
    for root in reversed(list(umbrella_roots)):  # nearest first, so walk outward-in
        if _git_path(root, run_git, "--show-toplevel") == Path(root).resolve():
            return _with_name(_state_dir(Path(root), run_git), name)
    return _with_name(_state_dir(repo, run_git), name)


def _with_name(directory: Optional[Path], name: str) -> Optional[Path]:
    return directory / name if directory is not None else None


def advise_once(marker: Optional[Path], text: str = ADVISORY) -> Optional[str]:
    """FR-004: TEXT, unless the marker says it was shown. A marker that cannot be
    written is not an error: the text is still returned."""
    if marker is not None and marker.exists():
        return None
    if marker is not None:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(text + "\n", encoding="utf-8")
        except OSError:
            pass
    return text


# --------------------------------------------------------------------------
# Build and freshness
# --------------------------------------------------------------------------


def _max_files() -> int:
    try:
        return int(os.environ[ENV_MAX_FILES])
    except (KeyError, ValueError):
        return MAX_FILES


def _count_tracked(repo: Path, run_git: GitRunner) -> int:
    try:
        proc = run_git(repo, "ls-files", "-z")
    except OSError as exc:
        raise GraphUnavailable("graph-init") from exc
    if proc.returncode != 0:
        raise GraphUnavailable("graph-init")
    return len([p for p in proc.stdout.split("\0") if p])


def ensure_index(repo: Path, run_git: GitRunner, tracked_count: Optional[int] = None
                 ) -> Optional[Dict[str, Any]]:
    """FR-002: build the index for REPO, which has no database file. Returns
    `built` {files, seconds, bytes}, or None when another process built the index
    while this one waited for the lock.

    Order: the file guard, the exclude line, the lock, the database file again,
    `init -y REPO`, then `status --json REPO`. That status must parse and name
    REPO itself as its project; anything else is `graph-status` or `graph-init`.
    """
    count = tracked_count if tracked_count is not None else _count_tracked(repo, run_git)
    limit = _max_files()
    if count > limit:
        raise GraphUnavailable("graph-too-large", TOO_LARGE.format(
            count=count, limit=limit, repo=Path(repo).name))  # FR-018: no abs path
    exclude_index_dir(repo, run_git)
    with _Lock(_with_name(_state_dir(repo, run_git), LOCK_NAME)):
        if has_index(repo):
            return None
        started = time.monotonic()
        run(["init", "-y", str(repo)], repo, "graph-init", timeout=INIT_TIMEOUT)
        seconds = round(time.monotonic() - started, 2)
    if not has_index(repo):
        raise GraphUnavailable("graph-init")
    current = status(repo)
    project = current.get("projectPath")
    if not current.get("initialized") or not isinstance(project, str) \
            or Path(project).resolve() != Path(repo).resolve():
        raise GraphUnavailable("graph-init")
    return {"files": current.get("fileCount"), "seconds": seconds,
            "bytes": current.get("dbSizeBytes")}


def daemon_alive(index_root: Path) -> bool:
    """A codegraph daemon serves INDEX_ROOT: `daemon.pid` names a live process this
    user may signal, and its socket is a socket. The socket is the pid file's
    `socketPath` (codegraph binds in TMPDIR when the project path is long), else
    `.codegraph/daemon.sock`."""
    index = index_root / INDEX_DIR
    try:
        data = json.loads((index / "daemon.pid").read_text(encoding="utf-8"))
        pid = data["pid"]
        socket_path = data.get("socketPath")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:  # gone, or another user's process: not our daemon
        return False
    sock = index / "daemon.sock"
    if isinstance(socket_path, str) and socket_path:
        sock = index / socket_path  # an absolute socketPath replaces the base
    try:
        return stat.S_ISSOCK(os.stat(sock).st_mode)
    except OSError:
        return False


def freshen(index_root: Path) -> str:
    """FR-005: query now when a daemon keeps the index fresh, else `sync PATH` first.
    Returns `daemon` or `sync`.

    INDEX_ROOT must hold its own database: `sync` on a path without one walks up
    and syncs the indexed ancestor (an umbrella root), so that is `graph-init`.
    """
    if not has_index(index_root):
        raise GraphUnavailable("graph-init")
    if daemon_alive(index_root):
        return "daemon"
    run(["sync", str(index_root)], index_root, "graph-sync")
    return "sync"


# --------------------------------------------------------------------------
# The preflight
# --------------------------------------------------------------------------


def _root_index(umbrella_roots: Sequence[Path]) -> Optional[Path]:
    for root in umbrella_roots:  # nearest first
        if (Path(root) / INDEX_DIR / DB_NAME).is_file():
            return Path(root).resolve()
    return None


def select(repo: Path, mode: str, *, run_git: GitRunner,
           umbrella_roots: Sequence[Path] = (),
           tracked_count: Optional[int] = None) -> Selection:
    """Decide whether this call reads the graph, and get the index ready if so.

    REPO is the resolved repository (a git toplevel). MODE is auto, off or root.
    RUN_GIT is `signals.run_git`; UMBRELLA_ROOTS is `signals._umbrella_roots(repo)`,
    nearest first. TRACKED_COUNT skips a second `git ls-files` when the caller has it.
    """
    if mode not in MODES:
        raise ValueError(f"code graph mode must be one of {', '.join(MODES)}: {mode}")
    if mode == "off":
        return _regex("off", "graph-off")
    repo = Path(repo).resolve()
    index_root = repo
    if mode == "root":
        found = _root_index(umbrella_roots)
        if found is None:
            return _regex("absent", "graph-root-not-indexed")
        index_root = found
    # Order: the binary, `--version` (no path walk), then the database file decides
    # between a build and a sync. `status` runs only after a build (see `status`).
    version: Optional[str] = None
    try:
        try:
            version = detect(index_root, repo, umbrella_roots, run_git)
        except GraphUnavailable as exc:
            advisory = None
            if mode == "auto" and exc.reason in ABSENT_REASONS:
                advisory = advise_once(marker_path(repo, run_git, umbrella_roots))
            return _regex("absent", exc.reason, advisory)
        built = None
        sync = "none"
        check_trusted(index_root, run_git)
        if not has_index(index_root):
            if mode == "root":  # never build in root mode (FR-014)
                return _regex("absent", "graph-root-not-indexed", version=version)
            built = ensure_index(repo, run_git, tracked_count)
        if built is None:
            sync = freshen(index_root)
    except GraphUnavailable as exc:
        if exc.reason == "graph-too-large":  # once per repository: its own marker
            marker = _with_name(_state_dir(repo, run_git), TOO_LARGE_MARKER)
            advisory = advise_once(marker, exc.advisory or "")
            return _regex("absent", exc.reason, advisory, version)
        return _regex("failed", exc.reason, exc.advisory, version)
    return Selection(True, "graph", "present", None, index_root, sync, built, None,
                     version, repo)


# --------------------------------------------------------------------------
# Reading the index — file edges from the database, tests from the CLI
# --------------------------------------------------------------------------


class FileGraph(NamedTuple):
    """File-level edges in the repository's own paths; `signals.Graph` wraps it."""

    out: Dict[str, Set[str]]  # every kept file, importer -> imported
    inn: Dict[str, Set[str]]  # imported -> importers, only files with one
    files: List[str]  # the kept files: indexed and in `graph_files`
    languages: List[str]
    outside_repo: int  # root mode: edge files outside the repository


def _prefix(index_root: Path, repo_root: Path) -> str:
    """REPO_ROOT relative to INDEX_ROOT, POSIX; '' when they are the same."""
    try:
        rel = Path(repo_root).resolve().relative_to(Path(index_root).resolve())
    except ValueError as exc:
        raise GraphUnavailable("graph-root-not-indexed") from exc
    text = rel.as_posix()
    return "" if text == "." else text


def _rebase(path: str, prefix: str) -> Optional[str]:
    """An index path as a repository path; None when it lies outside."""
    if not prefix:
        return path
    if path.startswith(prefix + "/"):
        return path[len(prefix) + 1:]
    return None


def _open_ro(db: Path) -> sqlite3.Connection:
    """`mode=ro`, then `immutable=1` when ro cannot open (a WAL database with no
    `-shm` in a directory this user cannot write). Never read-write."""
    base = db.resolve().as_uri()
    try:
        conn = sqlite3.connect(base + "?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return sqlite3.connect(base + "?immutable=1", uri=True)
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()  # opens it
    except sqlite3.OperationalError:
        conn.close()
        return sqlite3.connect(base + "?immutable=1", uri=True)
    except BaseException:
        conn.close()
        raise
    return conn


def _probe_schema(conn: sqlite3.Connection) -> None:
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "schema_versions" not in tables:
        raise GraphUnavailable("graph-schema")
    version = conn.execute("SELECT max(version) FROM schema_versions").fetchone()[0]
    if not isinstance(version, int) or version < MIN_SCHEMA:
        raise GraphUnavailable("graph-schema")
    for table, needed in REQUIRED_COLUMNS.items():
        if table not in tables:
            raise GraphUnavailable("graph-schema")
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not needed <= columns:
            raise GraphUnavailable("graph-schema")


EDGE_QUERY = (
    "SELECT DISTINCT a.file_path, b.file_path FROM edges e "
    "JOIN nodes a ON a.id = e.source JOIN nodes b ON b.id = e.target "
    "WHERE a.file_path != b.file_path")


def read_file_graph(index_root: Path, repo_root: Path,
                    graph_files: Iterable[str]) -> FileGraph:
    """Cross-file edges of every kind, read-only, kept to GRAPH_FILES.

    Paths in the index are relative to INDEX_ROOT; in root mode they are rebased to
    REPO_ROOT. A schema this reader does not know is `graph-schema`; any other
    SQLite failure is `graph-db`.
    """
    db = Path(index_root) / INDEX_DIR / DB_NAME
    if not db.is_file():
        raise GraphUnavailable("graph-db")
    prefix = _prefix(index_root, repo_root)
    wanted = set(graph_files)
    try:
        conn = _open_ro(db)
        try:
            _probe_schema(conn)
            indexed = conn.execute("SELECT path, language FROM files").fetchall()
            if indexed and conn.execute("SELECT 1 FROM edges LIMIT 1").fetchone() is None:
                raise GraphUnavailable("graph-schema")  # broken, not "0 importers"
            pairs = conn.execute(EDGE_QUERY).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise GraphUnavailable("graph-db") from exc
    languages: Set[str] = set()
    out: Dict[str, Set[str]] = {}
    for path, language in indexed:
        rel = _rebase(str(path), prefix)
        if rel is not None and rel in wanted:
            out[rel] = set()
            if language:
                languages.add(str(language))
    inn: Dict[str, Set[str]] = {}
    outside: Set[str] = set()
    for source, target in pairs:
        a, b = _rebase(str(source), prefix), _rebase(str(target), prefix)
        outside |= {p for p, r in ((source, a), (target, b)) if r is None}
        if a in out and b in out:
            out[a].add(b)
            inn.setdefault(b, set()).add(a)
    return FileGraph(out, inn, sorted(out), sorted(languages), len(outside))


def tests_reached(index_root: Path, repo_root: Path, seeds: Sequence[str],
                  known: Iterable[str]) -> List[str]:
    """The test files `affected` finds for SEEDS (repository paths), as repository
    paths, kept to KNOWN. `graph-affected` when the call or its JSON fails;
    `graph-affected-seeds` when every seed holds a line break."""
    if not seeds:
        return []
    # One path per line on stdin: a path with a line break cannot be sent. When no
    # seed is left, "no tests" would be a false answer: a reason instead.
    seeds = [s for s in seeds if "\n" not in s and "\r" not in s]
    if not seeds:
        raise GraphUnavailable("graph-affected-seeds")
    prefix = _prefix(index_root, repo_root)
    files = "".join(f"{prefix}/{s}\n" if prefix else f"{s}\n" for s in seeds)
    # On stdin, so a path that starts with `-` cannot read as an option.
    out = run(["affected", "--stdin", "-j", "-p", str(index_root)], Path(index_root),
              "graph-affected", stdin=files)
    try:
        tests = json.loads(out)["affectedTests"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GraphUnavailable("graph-affected") from exc
    if not isinstance(tests, list):
        raise GraphUnavailable("graph-affected")
    keep = set(known)
    rebased = (_rebase(str(t), prefix) for t in tests)
    return sorted({t for t in rebased if t is not None and t in keep})
