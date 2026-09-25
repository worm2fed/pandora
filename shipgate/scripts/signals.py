#!/usr/bin/env python3
"""shipgate code signals — per-file risk from git history and import structure.

Python 3 standard library only, no dependencies. Recomputes on demand and writes
nothing. See ``shipgate/docs/prd/code-signals.md``, its worklog, and ADR 0004.

Exit codes (also printed by ``--help``):

    0  ok — including "signals unavailable" (no git, shallow clone, empty history)
    1  infrastructure failure (git failed unexpectedly)
    2  usage error
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Constants / defaults
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INFRA = 1
EXIT_USAGE = 2

OUTPUT_VERSION = 1

CONFIG_RELPATH = os.path.join(".claude", "shipgate.md")
CONFIG_SECTION = "code signals"

DEFAULT_WINDOW_MONTHS = 12
MAX_WINDOW_MONTHS = 1200  # 100 years; beyond it date arithmetic overflows
DEFAULT_FIX_PATTERN = (
    r"^(fix|hotfix|revert)(\(.+\))?!?:|^revert\b"
    r"|\b(bug(fix(es)?|s)?|hot ?fix(es)?|fix(e[sd]|ing)?|regression)\b"
)
DEFAULT_EXCLUDES: Tuple[str, ...] = (
    "vendor/",
    "node_modules/",
    "third_party/",
    "dist/",
    "build/",
    "*.min.*",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.sum",
    "*.pb.go",
    "*_generated.*",
    "*.snap",
)

LABEL_RANK = {"low": 0, "mid": 1, "high": 2, "top": 3}
LABELLED_SIGNALS = (
    "commits", "fix_rate", "age_days", "stale_days", "authors", "top_share",
    "fan_in", "fan_out",
)
# A file needs this many in-window commits before its fix rate may rank above `low`.
MIN_COMMITS_FOR_FIX_RATE = 3

SECONDS_PER_DAY = 86400

# Never let git prompt, colour, sign, or opportunistically refresh the index.
GIT_CONFIG = (
    "-c", "core.quotepath=off",
    "-c", "color.ui=never",
    "-c", "log.showSignature=false",
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class SignalsError(Exception):
    """Base error carrying the process exit code to use."""

    exit_code = EXIT_INFRA


class InfraError(SignalsError):
    exit_code = EXIT_INFRA


class UsageError(SignalsError):
    exit_code = EXIT_USAGE


class Unavailable(Exception):
    """Signals cannot be computed here; a reason, not an error (exit 0)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------
# Config — the `## Code signals` section of .claude/shipgate.md
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+([^:]+?)\s*:\s*(.*)$")
_BACKTICK_RE = re.compile(r"`([^`]*)`")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# CommonMark: a backtick fence's info string holds no backtick (else it is inline
# code); a closing fence is the bare marker. Indentation is checked by the caller.
_FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}(?!.*`)|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*$")
_CONFIG_KEYS = {"window": "window_months", "fix pattern": "fix_pattern",
                "exclude": "exclude"}


def _is_placeholder(value: str) -> bool:
    value = value.strip()
    return not value or (value.startswith("<") and value.endswith(">"))


def parse_code_signals(text: str) -> Dict[str, Any]:
    """Parse the `## Code signals` section; only backticked values count.

    Returns only the keys that carry a usable value — a `<placeholder>`, a
    non-backticked value, a non-integer window or an invalid regex is absent.
    """
    text = _COMMENT_RE.sub("", text)
    in_section = False
    section_level = 0
    bullets: List[Tuple[str, str]] = []
    fence: Optional[str] = None  # the open fence's marker; its lines are inert
    for raw in text.splitlines():
        # Inside the section any indentation counts (a fence nested in a bullet).
        indent_ok = (lambda m: in_section or len(m.group(1)) <= 3)
        if fence is not None:
            close = _FENCE_CLOSE_RE.match(raw)
            if close and indent_ok(close) and close.group(2)[0] == fence[0] and \
                    len(close.group(2)) >= len(fence):
                fence = None
            continue
        opening = _FENCE_OPEN_RE.match(raw)
        if opening and indent_ok(opening):
            fence = opening.group(2)
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            level = len(heading.group(1))
            if in_section and level <= section_level:
                break
            if heading.group(2).strip().lower() == CONFIG_SECTION:
                in_section = True
                section_level = level
            continue
        if not in_section:
            continue
        bullet = _BULLET_RE.match(raw)
        if bullet:
            bullets.append((bullet.group(1).strip().lower(), bullet.group(2)))
        elif bullets and raw[:1].isspace() and raw.strip():
            key, value = bullets[-1]
            bullets[-1] = (key, value + " " + raw.strip())  # wrapped continuation
    out: Dict[str, Any] = {}
    for key, value in bullets:
        name = _CONFIG_KEYS.get(key)
        if name is None or name in out:
            continue
        spans = [s.strip() for s in _BACKTICK_RE.findall(value)]
        spans = [s for s in spans if not _is_placeholder(s)]
        if not spans:
            continue
        if name == "window_months":
            try:
                months = int(spans[0])
            except ValueError:
                continue
            if 1 <= months <= MAX_WINDOW_MONTHS:
                out[name] = months
        elif name == "fix_pattern":
            try:
                re.compile(spans[0])
            except re.error:
                continue
            out[name] = spans[0]
        else:
            # Separate spans or one comma-separated span: both are a list of globs.
            globs = [g.strip() for span in spans for g in span.split(",")]
            out[name] = [g for g in globs if g]
    return out


def _config_candidates(repo: Path, start: Optional[Path]) -> List[Path]:
    """`.claude/shipgate.md` from start up to the repo root, then the umbrella's."""
    repo = repo.resolve()
    candidates: List[Path] = []
    current = (start or repo).resolve()
    while True:
        candidates.append(current / CONFIG_RELPATH)
        if current == repo or current.parent == current:
            break
        current = current.parent
    # An umbrella is itself a git work tree; a plain parent (say, $HOME) is not read.
    parent = repo.parent
    umbrella = _git_toplevel(parent) if parent != repo else None
    if umbrella is not None and umbrella != repo:
        candidates.append(parent / CONFIG_RELPATH)
        candidates.append(umbrella / CONFIG_RELPATH)
    seen = set()
    unique = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def load_config(repo: Path, start: Optional[Path] = None
                ) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Read the file-level config. Returns (values, source) — values holds only the
    keys some shipgate.md set; the nearest file wins per key (repo before umbrella)."""
    cfg: Dict[str, Any] = {}
    source: Dict[str, str] = {}
    for path in _config_candidates(Path(repo), start):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, value in parse_code_signals(text).items():
            if key not in cfg:
                cfg[key] = value
                source[key] = "shipgate.md"
    return cfg, source


class Config(NamedTuple):
    window_months: int
    fix_pattern: str
    fix_regex: "re.Pattern[str]"
    exclude: List[str]
    source: Dict[str, str]

    def to_json(self) -> Dict[str, Any]:
        return {
            "window_months": self.window_months,
            "fix_pattern": self.fix_pattern,
            "exclude": list(self.exclude),
            "source": dict(self.source),
        }


def effective_config(file_cfg: Dict[str, Any], file_source: Dict[str, str],
                     args: argparse.Namespace) -> Config:
    """Flags override the file, the file overrides the defaults. Excludes are
    additive: defaults + file + flags."""
    source = {"window_months": "default", "fix_pattern": "default",
              "exclude": "default"}
    window = DEFAULT_WINDOW_MONTHS
    if "window_months" in file_cfg:
        window = file_cfg["window_months"]
        source["window_months"] = file_source.get("window_months", "shipgate.md")
    if args.window is not None:
        if not 1 <= args.window <= MAX_WINDOW_MONTHS:
            raise UsageError(f"--window must be 1 to {MAX_WINDOW_MONTHS} months")
        window, source["window_months"] = args.window, "flag"

    pattern = DEFAULT_FIX_PATTERN
    if "fix_pattern" in file_cfg:
        pattern = file_cfg["fix_pattern"]
        source["fix_pattern"] = file_source.get("fix_pattern", "shipgate.md")
    if args.fix_pattern is not None:
        pattern, source["fix_pattern"] = args.fix_pattern, "flag"
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise UsageError(f"--fix-pattern is not a valid regex: {exc}") from exc

    exclude = list(DEFAULT_EXCLUDES)
    if file_cfg.get("exclude"):
        exclude += file_cfg["exclude"]
        source["exclude"] = file_source.get("exclude", "shipgate.md")
    if args.exclude:
        exclude += args.exclude
        source["exclude"] = "flag"
    return Config(window, pattern, regex, exclude, source)


def _matches_glob(path: str, pattern: str) -> bool:
    # Copied from journal.py — scripts stay standalone.
    from fnmatch import fnmatch

    normalized = path.replace(os.sep, "/")
    if fnmatch(normalized, pattern):
        return True
    # Allow a project-relative glob to match an absolute or deeper path.
    return fnmatch(normalized, "*/" + pattern.removeprefix("./"))


def is_excluded(path: str, patterns: Iterable[str]) -> bool:
    """A trailing-slash pattern names a directory at any depth; others are globs."""
    parts = path.split("/")
    for pattern in patterns:
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            if not directory:
                continue
            for i in range(1, len(parts)):
                if _matches_glob("/".join(parts[:i]), directory):
                    return True
        elif _matches_glob(path, pattern):
            return True
    return False


# --------------------------------------------------------------------------
# Git helpers
# --------------------------------------------------------------------------


def _git_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only: no opportunistic index writes
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git_argv(repo: Path, args: Sequence[str]) -> List[str]:
    return ["git", "-C", str(repo), *GIT_CONFIG, *args]


def _decode(data: bytes) -> str:
    # Decoded by hand: text mode's universal newlines would turn a CR inside a `-z`
    # path or a commit subject into a line break.
    return data.decode("utf-8", "surrogateescape")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git; FileNotFoundError when git itself is missing."""
    proc = subprocess.run(
        _git_argv(repo, args), capture_output=True, env=_git_env(),
        stdin=subprocess.DEVNULL,
    )
    return subprocess.CompletedProcess(proc.args, proc.returncode,
                                       _decode(proc.stdout), _decode(proc.stderr))


def git_out(repo: Path, *args: str) -> str:
    """Run git and return stdout; a failure here is unexpected (infra, exit 1)."""
    try:
        proc = run_git(repo, *args)
    except OSError as exc:
        raise InfraError(f"git {args[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        raise InfraError(f"git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def _git_toplevel(directory: Path) -> Optional[Path]:
    try:
        proc = run_git(directory, "rev-parse", "--show-toplevel")
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def _unquote(path: str) -> str:
    """Undo git's C-style quoting (kept even with core.quotepath=off for tabs etc)."""
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        body = path[1:-1].encode("utf-8", "surrogateescape")
        import codecs

        return codecs.escape_decode(body)[0].decode("utf-8", "replace")
    return path


class Repo(NamedTuple):
    root: Path
    head: Optional[str]  # None: no commits yet (empty-history)
    now: Optional[int]  # HEAD's committer time — the reference clock (SC-007)
    shallow: bool


def probe(start: Path) -> Repo:
    """Locate the repository or raise Unavailable(no-git).

    An empty history is not fatal here: structure only needs `ls-files`.
    """
    try:
        top = run_git(start, "rev-parse", "--show-toplevel")
    except OSError:
        raise Unavailable("no-git")
    if top.returncode != 0 or not top.stdout.strip():
        raise Unavailable("no-git")
    root = Path(top.stdout.strip()).resolve()
    head = run_git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if head.returncode != 0 or not head.stdout.strip():
        return Repo(root, None, None, False)
    shallow = git_out(root, "rev-parse", "--is-shallow-repository").strip() == "true"
    now = int(git_out(root, "log", "-1", "--format=%ct", "HEAD").strip())
    return Repo(root, head.stdout.strip(), now, shallow)


def tracked_files(repo: Repo) -> List[str]:
    out = git_out(repo.root, "ls-files", "-z")
    return sorted({p for p in out.split("\0") if p})


def diff_files(repo: Repo, rev: str) -> set:
    """Files changed on REV...HEAD plus uncommitted (staged or not) changes.

    Plumbing plus `status` under GIT_OPTIONAL_LOCKS=0: porcelain `git diff HEAD`
    refreshes and rewrites .git/index when stat info is stale (FR-016).
    """
    known = run_git(repo.root, "rev-parse", "--verify", "-q", "--end-of-options",
                    f"{rev}^{{commit}}")
    if known.returncode != 0 or not known.stdout.strip():
        raise UsageError(f"--diff {rev}: bad revision")
    commit = known.stdout.strip()
    changed: set = set()
    if repo.head is not None:  # an unborn HEAD has no commits: status alone
        base = run_git(repo.root, "merge-base", "--end-of-options", commit, "HEAD")
        # No merge base (a shallow clone cut it off): fall back to a two-dot diff.
        start = base.stdout.strip() if base.returncode == 0 and base.stdout.strip() \
            else commit
        out = git_out(repo.root, "diff-tree", "-r", "--no-commit-id", "--name-only",
                      "-z", "--no-renames", "--end-of-options", start, "HEAD", "--")
        changed = {p for p in out.split("\0") if p}
    local = git_out(repo.root, "status", "--porcelain", "-z", "--no-renames",
                    "--untracked-files=no")
    changed |= {entry[3:] for entry in local.split("\0") if len(entry) > 3}
    return changed


# --------------------------------------------------------------------------
# Trajectory — one streamed `git log` pass
# --------------------------------------------------------------------------


class _Acc:
    __slots__ = ("first", "last", "commits", "fixes", "authors", "commit_ids",
                 "fix_ids")

    def __init__(self) -> None:
        self.first: Optional[int] = None
        self.last: Optional[int] = None
        self.commits = 0
        self.fixes = 0
        self.authors: Counter = Counter()  # in memory only — never emitted (FR-007)
        # In-window commit ordinals, so `--by-dir` can union instead of summing.
        self.commit_ids: set = set()
        self.fix_ids: set = set()


def months_before(epoch: int, months: int) -> int:
    """Calendar months back from `epoch`, in UTC, day clamped to the month's end."""
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    years, month0 = divmod(dt.month - 1 - months, 12)
    year = dt.year + years
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return int(dt.replace(year=year, month=month, day=day).timestamp())


class Trajectory(NamedTuple):
    stats: Dict[str, _Acc]
    commits_scanned: int


def scan_trajectory(repo: Repo, cfg: Config) -> Trajectory:
    assert repo.now is not None
    cutoff = months_before(repo.now, cfg.window_months)
    argv = _git_argv(repo.root, [
        "log", "--no-merges", "-M", "--name-status",
        "--format=%x00%H%x1f%ct%x1f%aE%x1f%s", "HEAD",
    ])
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, env=_git_env(),
        )
    except OSError as exc:
        raise InfraError(f"git log failed: {exc}") from exc

    stats: Dict[str, _Acc] = {}
    alias: Dict[str, str] = {}
    scanned = 0
    ct = 0
    in_window = False
    is_fix = False
    email = ""
    touched: set = set()

    def flush() -> None:
        for path in touched:
            acc = stats.get(path)
            if acc is None:
                acc = stats[path] = _Acc()
            if acc.first is None or ct < acc.first:
                acc.first = ct
            if acc.last is None or ct > acc.last:
                acc.last = ct
            if in_window:
                acc.commits += 1
                acc.authors[email] += 1
                acc.commit_ids.add(scanned)
                if is_fix:
                    acc.fixes += 1
                    acc.fix_ids.add(scanned)
        touched.clear()

    assert proc.stdout is not None
    for raw in proc.stdout:  # bytes: split on LF only, never on a CR
        line = _decode(raw.rstrip(b"\n"))
        if line.startswith("\0"):
            flush()
            fields = line[1:].split("\x1f", 3)
            while len(fields) < 4:
                fields.append("")
            _, ct_text, email, subject = fields
            try:
                ct = int(ct_text)
            except ValueError:
                ct = 0
            email = email.lower()
            in_window = ct >= cutoff
            is_fix = bool(cfg.fix_regex.search(subject))
            scanned += 1
            continue
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status[:1] in ("R", "C") and len(parts) >= 3:
            old, new = _unquote(parts[1]), _unquote(parts[2])
            target = alias.get(new, new)
            if status[0] == "R":
                alias[old] = target  # older history of `old` lands on the current path
            touched.add(target)
        elif len(parts) >= 2:
            path = _unquote(parts[1])
            touched.add(alias.get(path, path))
    flush()
    err = _decode(proc.stderr.read()) if proc.stderr else ""
    if proc.wait() != 0:
        raise InfraError(f"git log failed: {err.strip()}")
    return Trajectory(stats, scanned)


# --------------------------------------------------------------------------
# Labels — nearest-rank quartiles over the population
# --------------------------------------------------------------------------


def _nearest_rank(ordered: List[float], p: float) -> float:
    rank = max(1, -(-int(p * 100 * len(ordered)) // 100))  # ceil(p * n) without floats
    return ordered[rank - 1]


def quartile_labels(values: Sequence[Optional[float]]) -> List[Optional[str]]:
    """low|mid|high|top per value; equal values get equal labels; None stays None.

    Zero is always `low`, and the quartiles run over the non-zero values only — in a
    zero-heavy population (a dormant repo) one commit must not rank `top`. With fewer
    than four non-zero values, or no spread among them (q1 == q3), there are no
    quartiles to speak of: they are `mid` (a value above a flat q3 is still `top`).
    """
    nonzero = sorted(v for v in values if v is not None and v != 0)
    few = len(nonzero) < 4
    flat = False
    if not few:
        q1 = _nearest_rank(nonzero, 0.25)
        q2 = _nearest_rank(nonzero, 0.50)
        q3 = _nearest_rank(nonzero, 0.75)
        flat = q1 == q3  # no spread: the plateau is `mid`, as with few values
    out: List[Optional[str]] = []
    for v in values:
        if v is None:
            out.append(None)
        elif v == 0:
            out.append("low")
        elif few or (flat and v <= q3):
            out.append("mid")
        elif v > q3:
            out.append("top")
        elif v > q2:
            out.append("high")
        elif v > q1:
            out.append("mid")
        else:
            out.append("low")
    return out


def max_label(*labels: Optional[str]) -> Optional[str]:
    present = [label for label in labels if label is not None]
    if not present:
        return None
    return max(present, key=lambda label: LABEL_RANK[label])




# --------------------------------------------------------------------------
# Structure — adapter table, index, graph
# --------------------------------------------------------------------------

MAX_SCAN_BYTES = 1024 * 1024  # larger files are not scanned: structure unknown

TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
# `.js` written in a TS import usually names a `.ts` source (ESM-style specifiers).
TS_SWAPS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",),
            ".cjs": (".cts",)}
PY_ROOTS = ("", "src/", "lib/")

_TS_PATTERNS = (
    re.compile(r"""(?:^|[\s;}])from\s*['"]([^'"]+)['"]"""),  # import/export … from
    re.compile(r"""^\s*import\s*['"]([^'"]+)['"]"""),  # bare import 'x'
    re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)
_PY_IMPORT_RE = re.compile(r"^\s*import\s+(.+)$")
_PY_FROM_RE = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(.+)$")
_GO_SINGLE_RE = re.compile(r'^import\s+(?:[\w.]+\s+)?"([^"]+)"')
_GO_BLOCK_START_RE = re.compile(r"^import\s*\(\s*$")
_GO_BLOCK_LINE_RE = re.compile(r'^(?:[\w.]+\s+)?"([^"]+)"')
_GO_MODULE_RE = re.compile(r"^\s*module\s+\"?([^\s\"]+)\"?")


def _lines(text: str, comment: Tuple[str, ...]) -> Iterable[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(comment):
            yield line


def _extract_ts(text: str) -> List[Any]:
    specs: List[str] = []
    for line in _lines(text, ("//", "/*", "*")):
        for pattern in _TS_PATTERNS:
            specs.extend(pattern.findall(line))
    return list(dict.fromkeys(specs))


def _py_names(chunk: str) -> List[str]:
    chunk = chunk.split("#", 1)[0].strip().strip("()\\").strip()
    names = []
    for part in chunk.split(","):
        name = part.strip().split(" as ", 1)[0].strip().strip("()")
        if name:
            names.append(name)
    return names


def _extract_py(text: str) -> List[Any]:
    specs: List[Tuple[int, str, Tuple[str, ...]]] = []
    for line in _lines(text, ("#",)):
        m = _PY_FROM_RE.match(line)
        if m:
            specs.append((len(m.group(1)), m.group(2),
                          tuple(n for n in _py_names(m.group(3)) if n != "*")))
            continue
        m = _PY_IMPORT_RE.match(line)
        if m:
            for name in _py_names(m.group(1)):
                specs.append((0, name, ()))
    return list(dict.fromkeys(specs))


def _extract_go(text: str) -> List[Any]:
    specs: List[str] = []
    in_block = False
    for line in _lines(text, ("//",)):
        stripped = line.strip()
        if in_block:
            if stripped.startswith(")"):
                in_block = False
                continue
            m = _GO_BLOCK_LINE_RE.match(stripped)
            if m:
                specs.append(m.group(1))
        elif _GO_BLOCK_START_RE.match(stripped):
            in_block = True
        else:
            m = _GO_SINGLE_RE.match(stripped)
            if m:
                specs.append(m.group(1))
    return list(dict.fromkeys(specs))


class GraphContext(NamedTuple):
    files: frozenset  # every tracked path (resolution targets)
    # (prefix, suffix, targets, wildcard); exact patterns first, then longest prefix
    ts_aliases: List[Tuple[str, str, List[str], bool]]
    py_index: Dict[str, str]  # dotted module -> path
    go_modules: List[Tuple[str, str]]  # (module path, dir), longest first
    go_packages: Dict[str, List[str]]  # dir -> non-test .go files


# A resolution outcome: a set of target paths, EXTERNAL (no edge, not counted),
# or UNRESOLVED (project-internal but not found -> `partial`).
EXTERNAL = "external"
UNRESOLVED = "unresolved"


def _join(base: str, spec: str) -> Optional[str]:
    import posixpath

    joined = posixpath.normpath(posixpath.join(base, spec)) if base else \
        posixpath.normpath(spec)
    if joined == ".." or joined.startswith("../") or joined.startswith("/"):
        return None
    return "" if joined == "." else joined


def _probe_ts(ctx: GraphContext, base: Optional[str]) -> Optional[str]:
    if base is None:
        return None
    candidates = [base] + [base + ext for ext in TS_EXTS]
    for ext, swaps in TS_SWAPS.items():
        if base.endswith(ext):
            candidates += [base[: -len(ext)] + swap for swap in swaps]
    prefix = base + "/" if base else ""
    candidates += [prefix + "index" + ext for ext in TS_EXTS]
    for candidate in candidates:
        if candidate in ctx.files:
            return candidate
    return None


def _resolve_ts(spec: Any, importer: str, ctx: GraphContext) -> Any:
    import posixpath

    if spec.startswith("./") or spec.startswith("../") or spec in (".", ".."):
        hit = _probe_ts(ctx, _join(posixpath.dirname(importer), spec))
        return {hit} if hit else UNRESOLVED
    for prefix, suffix, targets, wildcard in ctx.ts_aliases:
        if not wildcard:
            if spec != prefix:
                continue
            middle = ""
        elif spec.startswith(prefix) and spec.endswith(suffix) and \
                len(spec) >= len(prefix) + len(suffix):
            middle = spec[len(prefix): len(spec) - len(suffix)]
        else:
            continue
        if not targets:
            return EXTERNAL  # every target is outside the repository
        for target in targets:
            hit = _probe_ts(ctx, _join("", target.replace("*", middle, 1)))
            if hit:
                return {hit}
        if wildcard and not prefix:
            return EXTERNAL  # a catch-all `*` that names nothing: a bare package
        return UNRESOLVED  # a project alias that names nothing
    return EXTERNAL


def _py_module_path(ctx: GraphContext, dotted: str) -> Optional[str]:
    return ctx.py_index.get(dotted)


def _py_path_candidates(ctx: GraphContext, stem: str) -> Optional[str]:
    """`stem.py`, else the package `stem/__init__.py`."""
    candidates = [stem + ".py", stem + "/__init__.py"] if stem else ["__init__.py"]
    for candidate in candidates:
        if candidate in ctx.files:
            return candidate
    return None


def _resolve_py(spec: Any, importer: str, ctx: GraphContext) -> Any:
    import posixpath

    level, module, names = spec
    if level == 0:
        hits = set()
        if names:  # `from a.b import c`: a.b.c (a submodule) per name, else a.b
            for name in names:
                hit = _py_module_path(ctx, module + "." + name)
                if hit:
                    hits.add(hit)
            if len(hits) < len(names):
                hit = _py_module_path(ctx, module)
                if hit:
                    hits.add(hit)
        else:  # `import a.b.c`: the module, else its nearest indexed parent package
            parts = module.split(".")
            for i in range(len(parts), 0, -1):
                hit = _py_module_path(ctx, ".".join(parts[:i]))
                if hit:
                    hits.add(hit)
                    break
        return hits or EXTERNAL
    base: Optional[str] = posixpath.dirname(importer)
    for _ in range(level - 1):
        if not base:
            return UNRESOLVED
        base = posixpath.dirname(base)
    stem = "/".join(p for p in [base or ""] + module.split(".") if p)
    hits = set()
    for name in names:
        hit = _py_path_candidates(ctx, "/".join(p for p in (stem, name) if p))
        if hit:
            hits.add(hit)
    if not hits or len(hits) < len(names):
        hit = _py_path_candidates(ctx, stem)
        if hit:
            hits.add(hit)
    return hits or UNRESOLVED


def _resolve_go(spec: Any, importer: str, ctx: GraphContext) -> Any:
    for module, directory in ctx.go_modules:
        if spec == module or spec.startswith(module + "/"):
            rest = spec[len(module):].lstrip("/")
            pkg_dir = "/".join(p for p in (directory, rest) if p)
            members = ctx.go_packages.get(pkg_dir)
            return set(members) if members else UNRESOLVED
    return EXTERNAL


# name -> (extensions, extract(text) -> specs, resolve(spec, importer, ctx))
ADAPTERS: Dict[str, Tuple[Tuple[str, ...], Any, Any]] = {
    "ts-js": (TS_EXTS, _extract_ts, _resolve_ts),
    "python": ((".py",), _extract_py, _resolve_py),
    "go": ((".go",), _extract_go, _resolve_go),
}


def adapter_for(path: str) -> Optional[str]:
    for name, (exts, _, _) in ADAPTERS.items():
        if path.endswith(exts):
            return name
    return None


def _strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments outside strings, then trailing commas."""
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _read_text(root: Path, path: str) -> Optional[str]:
    """A regular file's text, or None: never follows a symlink or opens a device,
    FIFO or socket (a tracked `x.ts -> /dev/zero` must not hang the scan)."""
    full = root / path
    try:
        if not stat.S_ISREG(os.lstat(full).st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(full, flags)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None  # swapped between the lstat and the open
            data = handle.read(MAX_SCAN_BYTES + 1)  # a size lie cannot matter
    except OSError:
        return None
    if len(data) > MAX_SCAN_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _ts_aliases(root: Path, files: frozenset
                ) -> List[Tuple[str, str, List[str], bool]]:
    for name in ("tsconfig.json", "jsconfig.json"):
        if name not in files:
            continue
        text = _read_text(root, name)
        try:
            config = json.loads(_strip_jsonc(text or ""))
            options = config.get("compilerOptions") or {}
            base_url = options.get("baseUrl") or "."
            paths = options.get("paths") or {}
            aliases = []
            for pattern, targets in paths.items():
                if not isinstance(targets, list):
                    continue
                wildcard = "*" in pattern
                prefix, _, suffix = pattern.partition("*")
                # A target outside the repo (`../x/*`, an absolute target or baseUrl)
                # maps to nothing — never to "" (the root), which hits a root index.ts.
                joined = [j for j in (_join("", f"{base_url}/{t}") for t in targets
                                      if isinstance(t, str) and not t.startswith("/"))
                          if j is not None]
                aliases.append((prefix, suffix, joined, wildcard))
            aliases.sort(key=lambda a: (a[3], -len(a[0])))
            return aliases
        except (ValueError, AttributeError, TypeError):
            return []  # an unparseable config skips aliases silently
    return []


def _py_index(files: Iterable[str]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for root in PY_ROOTS:
        for path in files:
            if not path.endswith(".py") or not path.startswith(root):
                continue
            rel = path[len(root):-3]
            if rel.endswith("/__init__"):
                rel = rel[: -len("/__init__")]
            elif rel == "__init__":
                continue
            dotted = rel.replace("/", ".")
            if all(part.isidentifier() for part in dotted.split(".")):
                index.setdefault(dotted, path)
    return index


def _go_context(root: Path, files: Iterable[str]
                ) -> Tuple[List[Tuple[str, str]], Dict[str, List[str]]]:
    import posixpath

    modules = []
    packages: Dict[str, List[str]] = {}
    for path in files:
        if posixpath.basename(path) == "go.mod":
            for line in (_read_text(root, path) or "").splitlines():
                m = _GO_MODULE_RE.match(line)
                if m:
                    modules.append((m.group(1), posixpath.dirname(path)))
                    break
        elif path.endswith(".go") and not path.endswith("_test.go"):
            packages.setdefault(posixpath.dirname(path), []).append(path)
    modules.sort(key=lambda m: -len(m[0]))
    return modules, packages


class Graph(NamedTuple):
    available: bool
    reason: Optional[str]
    languages: List[str]
    files_scanned: int
    out: Dict[str, set]
    inn: Dict[str, set]
    status: Dict[str, str]  # ok | partial (files with no entry: unknown)
    unresolved: Dict[str, int]

    def summary(self) -> Dict[str, Any]:
        return {"available": self.available, "reason": self.reason,
                "languages": self.languages, "files_scanned": self.files_scanned}


def scan_structure(root: Path, tracked: List[str], graph_files: List[str]) -> Graph:
    """Import graph over `graph_files` (tracked minus excludes)."""
    all_files = frozenset(tracked)
    nodes = set(graph_files)
    go_modules, go_packages = _go_context(root, tracked)
    ctx = GraphContext(all_files, _ts_aliases(root, all_files), _py_index(tracked),
                       go_modules, go_packages)
    out: Dict[str, set] = {}
    inn: Dict[str, set] = {}
    status: Dict[str, str] = {}
    unresolved: Dict[str, int] = {}
    languages = set()
    scanned = 0
    for path in graph_files:
        name = adapter_for(path)
        if name is None:
            continue
        text = _read_text(root, path)
        if text is None:
            continue  # too large or unreadable: structure unknown
        _, extract, resolve = ADAPTERS[name]
        languages.add(name)
        scanned += 1
        targets: set = set()
        missing = 0
        for spec in extract(text):
            result = resolve(spec, path, ctx)
            if result == UNRESOLVED:
                missing += 1
            elif result != EXTERNAL:
                targets |= {t for t in result if t != path and t in nodes}
        out[path] = targets
        for target in targets:
            inn.setdefault(target, set()).add(path)
        status[path] = "partial" if missing else "ok"
        unresolved[path] = missing
    if not scanned:
        return Graph(False, "no-adapter", [], 0, {}, {}, {}, {})
    return Graph(True, None, sorted(languages), scanned, out, inn, status, unresolved)


def structure_unavailable(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason, "languages": [], "files_scanned": 0}


def blast_radius(graph: Graph, seeds: Sequence[str], limit: int) -> Dict[str, Any]:
    """Reverse-adjacency BFS from the seeds; cycle-safe; seeds excluded."""
    import posixpath
    from collections import deque

    seen = set(seeds)
    queue = deque(sorted(seen))
    reached: set = set()
    while queue:
        current = queue.popleft()
        for importer in graph.inn.get(current, ()):
            if importer not in seen:
                seen.add(importer)
                reached.add(importer)
                queue.append(importer)
    files = sorted(reached)
    by_dir = Counter(posixpath.dirname(f) or "." for f in files)
    return {
        "size": len(files),
        "files": files[:limit],
        "truncated": len(files) > limit,
        "by_dir": dict(sorted(by_dir.items())),
        "unknown_seeds": sorted(s for s in set(seeds) if s not in graph.status),
    }


# --------------------------------------------------------------------------
# Aggregate — file rows and `--by-dir`
# --------------------------------------------------------------------------


def _days(now: Optional[int], then: Optional[int]) -> Optional[int]:
    if then is None or now is None:
        return None
    return max(0, (now - then) // SECONDS_PER_DAY)


def build_rows(repo: Repo, population: List[str], traj: Optional[Trajectory],
               graph: Optional[Graph]) -> List[Dict[str, Any]]:
    """One row per population file, labelled over the whole population."""
    rows: List[Dict[str, Any]] = []
    for path in population:
        row: Dict[str, Any] = {"path": path}
        if traj is not None:
            acc = traj.stats.get(path) or _Acc()
            commits = acc.commits
            top = max(acc.authors.values()) if acc.authors else 0
            row.update({
                "commits": commits,
                "fixes": acc.fixes,
                "fix_rate": round(acc.fixes / commits, 2) if commits else 0.0,
                "age_days": _days(repo.now, acc.first),
                "stale_days": _days(repo.now, acc.last),
                "authors": len(acc.authors),
                "top_share": round(top / commits, 2) if commits else 0.0,
            })
        else:
            row.update({k: None for k in ("commits", "fixes", "fix_rate", "age_days",
                                          "stale_days", "authors", "top_share")})
        known = graph is not None and path in graph.status
        row.update({
            "fan_in": len(graph.inn.get(path, ())) if known else None,
            "fan_out": len(graph.out.get(path, ())) if known else None,
            "unresolved": graph.unresolved[path] if known else None,
            "structure": graph.status[path] if known else "unknown",
        })
        rows.append(row)
    columns = {name: quartile_labels([r[name] for r in rows])
               for name in LABELLED_SIGNALS}
    for i, row in enumerate(rows):
        labels = {name: columns[name][i] for name in LABELLED_SIGNALS}
        if row["commits"] is not None and row["commits"] < MIN_COMMITS_FOR_FIX_RATE:
            labels["fix_rate"] = "low"
        row["labels"] = labels
        row["risk"] = max_label(labels["commits"], labels["fix_rate"])
    return rows


def _risk_rank(label: Optional[str]) -> int:
    return LABEL_RANK[label] if label is not None else -1


def sort_rows(rows: List[Dict[str, Any]], key: str = "path") -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (-_risk_rank(r["risk"]), -(r["fixes"] or 0),
                                       -(r["commits"] or 0), r[key]))


def dir_of(path: str, depth: int) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) or "."


def aggregate_dirs(rows: List[Dict[str, Any]], depth: int, traj: Optional[Trajectory],
                   graph: Optional[Graph]) -> List[Dict[str, Any]]:
    """Directory rows over the population rows: distinct commits (a multi-file
    commit is one commit), max labels, importer union minus the dir's own files."""
    members: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        members.setdefault(dir_of(row["path"], depth), []).append(row)
    out = []
    for directory, group in members.items():
        own = {r["path"] for r in group}
        entry: Dict[str, Any] = {"dir": directory, "files": len(group)}
        if traj is not None:
            commit_ids: set = set()
            fix_ids: set = set()
            for path in own:
                acc = traj.stats.get(path)
                if acc is not None:
                    commit_ids |= acc.commit_ids
                    fix_ids |= acc.fix_ids
            commits = len(commit_ids)
            entry.update({"commits": commits, "fixes": len(fix_ids),
                          "fix_rate": round(len(fix_ids) / commits, 2)
                          if commits else 0.0})
        else:
            entry.update({"commits": None, "fixes": None, "fix_rate": None})
        known = [p for p in own if graph is not None and p in graph.status]
        if known:
            importers: set = set()
            for path in known:
                importers |= graph.inn.get(path, set())  # type: ignore[union-attr]
            entry["fan_in"] = len(importers - own)
        else:
            entry["fan_in"] = None
        entry["labels"] = {name: max_label(*(r["labels"][name] for r in group))
                           for name in LABELLED_SIGNALS}
        entry["risk"] = max_label(*(r["risk"] for r in group))
        out.append(entry)
    return out


# --------------------------------------------------------------------------
# Suspects
# --------------------------------------------------------------------------

PROXIMITY_SELF = 1.0
PROXIMITY_IMPORT = 0.75
PROXIMITY_SAME_DIR = 0.5
STALENESS_SCALE_DAYS = 90


def rank_suspects(rows: List[Dict[str, Any]], traj: Trajectory,
                  graph: Optional[Graph], symptoms: Sequence[str]
                  ) -> List[Dict[str, Any]]:
    """score = fix_rate × min(1, commits/3) × 1/(1 + stale/90) × proximity."""
    import posixpath

    by_path = {r["path"]: r for r in rows}
    proximity: Dict[str, float] = {}

    def offer(path: str, value: float) -> None:
        if path in by_path and proximity.get(path, 0.0) < value:
            proximity[path] = value

    for symptom in symptoms:
        offer(symptom, PROXIMITY_SELF)
        if graph is not None:
            for neighbour in graph.inn.get(symptom, set()) | graph.out.get(symptom, set()):
                offer(neighbour, PROXIMITY_IMPORT)
        parent = posixpath.dirname(symptom)
        for path in by_path:
            if posixpath.dirname(path) == parent:
                offer(path, PROXIMITY_SAME_DIR)
    out = []
    for path, prox in proximity.items():
        row = by_path[path]
        acc = traj.stats.get(path)
        commits = acc.commits if acc else 0
        fix_rate = acc.fixes / commits if acc and commits else 0.0
        stale = row["stale_days"]
        recency = 1.0 / (1.0 + stale / STALENESS_SCALE_DAYS) if stale is not None else 0.0
        score = fix_rate * min(1.0, commits / MIN_COMMITS_FOR_FIX_RATE) * recency * prox
        out.append({"path": path, "score": round(score, 2), "proximity": prox,
                    "fix_rate": row["fix_rate"], "commits": row["commits"],
                    "stale_days": stale, "fan_in": row["fan_in"]})
    out.sort(key=lambda s: (-s["score"], s["path"]))
    return out


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

TABLE_COLUMNS = ("path", "commits", "fix%", "age", "stale", "auth", "top%", "in",
                 "out", "risk")
DIR_COLUMNS = ("dir", "files", "commits", "fix%", "in", "risk")
SUSPECT_COLUMNS = ("path", "score", "prox", "fix%", "commits", "stale", "in")


def _cell(value: Any, percent: bool = False) -> str:
    if value is None:
        return "-"
    if percent:
        return str(int(round(value * 100)))
    return str(value)


def _grid(header: Sequence[str], body: List[Sequence[str]]) -> List[str]:
    """First column left-aligned, the last left-aligned, the rest right-aligned."""
    table = [tuple(header)] + [tuple(line) for line in body]
    widths = [max(len(line[i]) for line in table) for i in range(len(header))]
    lines = []
    for line in table:
        cells = [line[0].ljust(widths[0])]
        cells += [cell.rjust(widths[i + 1]) for i, cell in enumerate(line[1:-1])]
        cells.append(line[-1])
        lines.append("  ".join(cells).rstrip())
    if not body:
        lines.append("(no rows)")
    return lines


def render_files(rows: List[Dict[str, Any]]) -> List[str]:
    return _grid(TABLE_COLUMNS, [(
        r["path"], _cell(r["commits"]), _cell(r["fix_rate"], True),
        _cell(r["age_days"]), _cell(r["stale_days"]), _cell(r["authors"]),
        _cell(r["top_share"], True), _cell(r["fan_in"]), _cell(r["fan_out"]),
        _cell(r["risk"]),
    ) for r in rows])


def render_dirs(dirs: List[Dict[str, Any]]) -> List[str]:
    return _grid(DIR_COLUMNS, [(
        d["dir"], _cell(d["files"]), _cell(d["commits"]), _cell(d["fix_rate"], True),
        _cell(d["fan_in"]), _cell(d["risk"]),
    ) for d in dirs])


def render_blast(blast: Optional[Dict[str, Any]]) -> List[str]:
    if blast is None:
        return ["blast radius: unavailable (no import structure)"]
    more = f" (showing {len(blast['files'])})" if blast["truncated"] else ""
    lines = [f"blast radius: {blast['size']} files{more}"]
    lines += [f"  {path}" for path in blast["files"]]
    if blast["by_dir"]:
        lines.append("by dir: " + ", ".join(f"{d} {n}" for d, n in
                                           blast["by_dir"].items()))
    unknown = blast["unknown_seeds"]
    if unknown:
        more = f" (+{len(unknown) - 10} more)" if len(unknown) > 10 else ""
        lines.append(f"unknown seeds: {', '.join(unknown[:10])}{more}")
    return lines


def render_suspects(suspects: List[Dict[str, Any]]) -> List[str]:
    return _grid(SUSPECT_COLUMNS, [(
        s["path"], f"{s['score']:.2f}", f"{s['proximity']:.2f}",
        _cell(s["fix_rate"], True), _cell(s["commits"]), _cell(s["stale_days"]),
        _cell(s["fan_in"]),
    ) for s in suspects])


def emit(payload: Dict[str, Any], as_json: bool, lines: Sequence[str] = ()) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    elif not payload["available"]:
        sys.stdout.write(f"signals unavailable: {payload['reason']}\n")
    else:
        sys.stdout.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EPILOG = """\
exit codes:
  0  ok — including "signals unavailable": outside a git repository or with
     git missing (no-git), no commits yet (empty-history), a shallow clone
     (shallow: no trajectory), or no file any adapter reads (no-adapter: no
     structure). Table mode then prints one line
     `signals unavailable: <reason>`; --json reports available:false and the
     reason. Nothing is printed on stderr. When only one half is missing,
     table mode prints `trajectory unavailable: <reason>` (or `structure
     unavailable: <reason>`) above the table.
  1  infrastructure failure (git failed unexpectedly)
  2  usage error

configuration:
  the `## Code signals` section of .claude/shipgate.md (the repository's, then
  an umbrella parent's when the parent is itself a git work tree) — backticked
  values on the `Window`, `Fix pattern` and `Exclude` bullets. Flags override
  the file; --exclude adds to the defaults.
  Labels are quartiles over the whole repository (or --scope); zero is always
  `low` and the quartiles run over the non-zero values (fewer than four, or no
  spread: `mid`). Positional paths and --diff only filter the rows shown;
  --diff shows every changed file unless --top is given. "Now" is HEAD's commit time.

structure:
  TS/JS, Python and Go imports, by regex. Other files report structure
  `unknown` with null fan-in/out; an unresolved relative import marks a file
  `partial`. Files over 1 MB, symlinks and special files are not scanned.
"""


def _common_flags() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--repo", metavar="DIR", default=None,
                        help="repository to analyse (default: the git toplevel of "
                             "the current directory)")
    common.add_argument("--scope", metavar="PATH", default=None,
                        help="restrict the label population (and the rows) to this "
                             "repo-relative directory or file")
    common.add_argument("--window", metavar="MONTHS", type=int, default=None,
                        help=f"trajectory window in months, 1 to "
                             f"{MAX_WINDOW_MONTHS} (default {DEFAULT_WINDOW_MONTHS})")
    common.add_argument("--fix-pattern", metavar="RE", default=None,
                        help="regex (case-insensitive) a commit subject must match "
                             "to count as a fix")
    common.add_argument("--exclude", metavar="GLOB", action="append", default=None,
                        help="extra path glob to skip (repeatable; adds to the "
                             "defaults; a trailing / names a directory)")
    common.add_argument("--json", action="store_true",
                        help="machine-readable output")
    return common


DEFAULT_TOP = 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signals.py",
        description="shipgate code signals — per-file risk from git history and "
                    "import structure.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Exact flags only: skill prose is checked against this parser, and an
        # abbreviation would let a renamed flag keep "parsing".
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True
    common = _common_flags()

    p_hot = subparsers.add_parser(
        "hotspots", parents=[common], allow_abbrev=False,
        help="per-file trajectory and structure signals, ranked by risk")
    p_hot.add_argument("paths", nargs="*", metavar="PATH",
                       help="only show rows under these repo-relative paths")
    p_hot.add_argument("--diff", metavar="REV", default=None,
                       help="only show files changed on REV...HEAD or uncommitted")
    p_hot.add_argument("--by-dir", metavar="DEPTH", type=int, default=None,
                       help="aggregate to directories DEPTH levels deep")
    p_hot.add_argument("--blast", action="store_true",
                       help="add the blast radius of the selected files")
    p_hot.add_argument("--top", metavar="N", type=int, default=None,
                       help=f"show at most N rows (default {DEFAULT_TOP}; every "
                            f"selected row with --diff)")

    p_blast = subparsers.add_parser(
        "blast", parents=[common], allow_abbrev=False,
        help="transitive importers (blast radius) of a file set")
    p_blast.add_argument("files", nargs="*", metavar="FILE",
                         help="seed files (repo-relative)")
    p_blast.add_argument("--diff", metavar="REV", default=None,
                         help="add files changed on REV...HEAD or uncommitted")
    p_blast.add_argument("--limit", metavar="N", type=int, default=50,
                         help="list at most N importers (default 50)")

    p_sus = subparsers.add_parser(
        "suspects", parents=[common], allow_abbrev=False,
        help="ranked suspect files near a symptom, for debugging")
    p_sus.add_argument("files", nargs="+", metavar="FILE",
                       help="the symptom's files (repo-relative)")
    p_sus.add_argument("--top", metavar="N", type=int, default=10,
                       help="show at most N suspects (default 10)")
    return parser


def _norm_rel(root: Path, value: str) -> str:
    """A repo-relative POSIX path; '' means the whole repository."""
    p = Path(value)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root)
        except ValueError as exc:
            raise UsageError(f"{value} is outside the repository {root}") from exc
    text = p.as_posix()
    while text.startswith("./"):
        text = text[2:]
    text = text.rstrip("/")
    return "" if text == "." else text


def _under(path: str, prefix: str) -> bool:
    return not prefix or path == prefix or path.startswith(prefix + "/")


def _start_dir(args: argparse.Namespace) -> Path:
    start = Path(args.repo).expanduser() if args.repo else Path.cwd()
    if not start.is_dir():
        raise UsageError(f"--repo {start}: not a directory")
    return start.resolve()


def _check_counts(args: argparse.Namespace) -> None:
    for name in ("top", "limit"):
        value = getattr(args, name, None)
        if value is not None and value < 0:
            raise UsageError(f"--{name} must be zero or more")
    by_dir = getattr(args, "by_dir", None)
    if by_dir is not None and by_dir < 1:
        raise UsageError("--by-dir must be 1 or more")


class Analysis(NamedTuple):
    repo: Optional[Repo]
    cfg: Config
    reason: Optional[str]  # repo-level: no-git | empty-history | shallow | None
    population: List[str]
    traj: Optional[Trajectory]
    traj_info: Dict[str, Any]
    graph: Optional[Graph]


def analyse(args: argparse.Namespace, want_traj: bool, want_struct: bool) -> Analysis:
    start = _start_dir(args)
    try:
        repo = probe(start)
    except Unavailable as exc:
        cfg = effective_config(*load_config(start), args)
        return Analysis(None, cfg, exc.reason, [], None,
                        _unavailable_trajectory(exc.reason), None)
    cfg = effective_config(*load_config(repo.root, start), args)
    reason = "empty-history" if repo.head is None else (
        "shallow" if repo.shallow else None)
    tracked = tracked_files(repo)
    graph_files = [p for p in tracked if not is_excluded(p, cfg.exclude)]
    scope = _norm_rel(repo.root, args.scope) if args.scope else ""
    population = [p for p in graph_files if _under(p, scope)]
    traj = None
    traj_info = _unavailable_trajectory(reason or "not-requested")
    if want_traj and reason is None:
        traj = scan_trajectory(repo, cfg)
        traj_info = {"available": True, "reason": None,
                     "commits_scanned": traj.commits_scanned}
    graph = scan_structure(repo.root, tracked, graph_files) if want_struct else None
    return Analysis(repo, cfg, reason, population, traj, traj_info, graph)


def _envelope(a: Analysis, reason: Optional[str]) -> Dict[str, Any]:
    payload = {
        "version": OUTPUT_VERSION,
        "available": reason is None,
        "reason": reason,
        "head": a.repo.head if a.repo else None,
        "config": a.cfg.to_json(),
    }
    if a.graph is not None:
        payload["structure"] = a.graph.summary()
    else:
        payload["structure"] = structure_unavailable(a.reason or "not-requested")
    return payload


def _unavailable_trajectory(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason, "commits_scanned": 0}


def _graph(a: Analysis) -> Optional[Graph]:
    return a.graph if a.graph is not None and a.graph.available else None


def _half_notes(trajectory: Dict[str, Any], structure: Dict[str, Any]) -> List[str]:
    """Table mode: one line per missing half, so a column of dashes is explained."""
    lines = []
    if not trajectory["available"]:
        lines.append(f"trajectory unavailable: {trajectory['reason']}")
    if not structure["available"]:
        lines.append(f"structure unavailable: {structure['reason']}")
    return lines


def cmd_hotspots(args: argparse.Namespace) -> int:
    _check_counts(args)
    a = analyse(args, want_traj=True, want_struct=True)
    graph = _graph(a)
    reason = None
    if a.repo is None:
        reason = a.reason
    elif a.traj is None and graph is None:
        reason = a.reason or (a.graph.reason if a.graph else None)
    payload = _envelope(a, reason)
    payload["trajectory"] = a.traj_info
    if reason is not None:
        payload["files"] = []
        emit(payload, args.json)
        return EXIT_OK
    assert a.repo is not None
    filters = [_norm_rel(a.repo.root, p) for p in args.paths]
    changed = diff_files(a.repo, args.diff) if args.diff else None
    # A review needs every changed file, so --diff is not truncated unless asked.
    top = args.top if args.top is not None else (None if args.diff else DEFAULT_TOP)

    rows = build_rows(a.repo, a.population, a.traj, graph)
    selected = rows
    if filters:
        selected = [r for r in selected if any(_under(r["path"], f) for f in filters)]
    if changed is not None:
        selected = [r for r in selected if r["path"] in changed]

    lines: List[str] = _half_notes(a.traj_info, payload["structure"])
    if args.by_dir is not None:
        wanted = {dir_of(r["path"], args.by_dir) for r in selected}
        dirs = [d for d in aggregate_dirs(rows, args.by_dir, a.traj, graph)
                if d["dir"] in wanted]
        dirs = sort_rows(dirs, key="dir")[:top]
        payload["files"] = []
        payload["dirs"] = dirs
        lines += render_dirs(dirs)
    else:
        shown = sort_rows(selected)[:top]
        payload["files"] = shown
        lines += render_files(shown)
    if args.blast:
        seeds = [r["path"] for r in selected]
        payload["blast"] = blast_radius(graph, seeds, 50) if graph else None
        lines += [""] + render_blast(payload["blast"])
    emit(payload, args.json, lines)
    return EXIT_OK


def cmd_blast(args: argparse.Namespace) -> int:
    _check_counts(args)
    a = analyse(args, want_traj=False, want_struct=True)
    graph = _graph(a)
    reason = None
    if a.repo is None:
        reason = a.reason
    elif graph is None:
        reason = "empty-history" if a.reason == "empty-history" else (
            a.graph.reason if a.graph else "no-adapter")
    payload = _envelope(a, reason)
    payload["trajectory"] = a.traj_info  # not computed by blast; the reason says why
    if reason is not None:
        payload["blast"] = None
        emit(payload, args.json)
        return EXIT_OK
    assert a.repo is not None and graph is not None
    seeds = [_norm_rel(a.repo.root, f) for f in args.files]
    if args.diff:
        seeds += sorted(diff_files(a.repo, args.diff))
    if not seeds:
        raise UsageError("blast needs FILE arguments or --diff")
    payload["blast"] = blast_radius(graph, sorted(set(seeds)), args.limit)
    emit(payload, args.json, render_blast(payload["blast"]))
    return EXIT_OK


def cmd_suspects(args: argparse.Namespace) -> int:
    _check_counts(args)
    a = analyse(args, want_traj=True, want_struct=True)
    reason = a.reason if a.traj is None else None
    payload = _envelope(a, reason)
    payload["trajectory"] = a.traj_info
    if reason is not None or a.traj is None:
        payload["suspects"] = []
        emit(payload, args.json)
        return EXIT_OK
    assert a.repo is not None
    graph = _graph(a)
    rows = build_rows(a.repo, a.population, a.traj, graph)
    symptoms = [_norm_rel(a.repo.root, f) for f in args.files]
    suspects = rank_suspects(rows, a.traj, graph, symptoms)[: args.top]
    payload["suspects"] = suspects
    emit(payload, args.json,
         _half_notes(a.traj_info, payload["structure"]) + render_suspects(suspects))
    return EXIT_OK


COMMANDS = {
    "hotspots": cmd_hotspots,
    "blast": cmd_blast,
    "suspects": cmd_suspects,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except SignalsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return EXIT_OK
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
