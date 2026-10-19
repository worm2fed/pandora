#!/usr/bin/env python3
"""A fake `codegraph` for shipgate's tests: replays the recorded 1.6.2 fixtures.

`make_codegraph_shim(bin_dir, mode)` in `test_signals.py` writes an executable named
`codegraph` that execs this script with `SHIM_MODE` set. Every invocation first appends
one JSON line to `$SHIM_LOG` (when set): `argv`, `cwd`, `mode` and the two
`CODEGRAPH_*` environment values.

Modes:

    ok               replay the fixtures; `init` writes a small index
    uninit           `status` always says not initialized; `init` fails
    old-version      `--version` prints 1.5.0
    garbage          `status` prints text that is not JSON
    kill             `init`, `sync` and the queries kill themselves (SIGKILL)
    hang             `init`, `sync` and the queries sleep 60 s
    corrupt-db       `init` writes random bytes as the database
    schema-mismatch  `init` writes a database at schema version 10 whose `edges`
                     table has no `kind` column

`--version` and `status` behave as in `ok` for kill, hang, corrupt-db and
schema-mismatch, so those modes fail after detection.

The argv contract is the real 1.6.2 CLI's, so a wrong call fails here as it would
for real. `status`, `sync` and `init` take the project path positionally; `-p` on
them exits 1 with `error: unknown option '-p'`. The query commands (`query`,
`explore`, `node`, `files`, `callers`, `callees`, `impact`, `affected`) take
`-p <path>`, and the shim requires it: a missing `-p`, or one that does not name
an existing directory, exits 1 (stricter than codegraph, which falls back to the
working directory).

`status PATH` walks up like the real one: it answers for the nearest ancestor of
PATH (PATH included) that holds `.codegraph/codegraph.db`, with that ancestor as
`projectPath` and `initialized: true`. So an unindexed child under an indexed
umbrella root reads as the root. `init PATH` builds exactly PATH.

`affected --stdin` reads the file list from stdin, one per line; the log records
it as `stdin`. `impact`, `callers` and `callees` on a symbol that starts with
`no_such_` print `ℹ Symbol "<name>" not found` and exit 0, as codegraph does even
with `-j`; `node` prints `Symbol "<name>" not found in the codebase` and `explore`
starts with `No relevant code found for "<name>"`, both with exit 0. The log also records `GIT_DIR` and `GIT_WORK_TREE`. `init` builds one `file` node
and one `function` node per tracked file; `$SHIM_EDGES` (a JSON list of
`[from, to]` or `[from, to, kind]` repo-relative paths) adds file-to-file edges.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

FIXTURES = Path(__file__).resolve().parent / "codegraph"
MODE = os.environ.get("SHIM_MODE", "ok")
INDEX_DIR = ".codegraph"
DB_NAME = "codegraph.db"
GITIGNORE = (
    "# CodeGraph data files — local to each machine, not for committing.\n"
    "*\n"
    "!.gitignore\n"
)
QUERY_FIXTURES = {
    "affected": "affected.json",
    "impact": "impact.json",
    "callers": "callers.json",
    "callees": "callees.json",
    "query": "query.json",
    "files": "files.json",
    "explore": "explore.txt",
}


def log(argv: List[str], stdin: Optional[str] = None) -> None:
    path = os.environ.get("SHIM_LOG")
    if not path:
        return
    entry = {
        "argv": argv,
        "cwd": os.getcwd(),
        "mode": MODE,
        "stdin": stdin,
        "CODEGRAPH_TELEMETRY": os.environ.get("CODEGRAPH_TELEMETRY"),
        "CODEGRAPH_NO_DAEMON": os.environ.get("CODEGRAPH_NO_DAEMON"),
        "GIT_DIR": os.environ.get("GIT_DIR"),
        "GIT_WORK_TREE": os.environ.get("GIT_WORK_TREE"),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def option(argv: List[str], flag: str) -> Optional[str]:
    if flag in argv:
        at = argv.index(flag)
        if at + 1 < len(argv):
            return argv[at + 1]
    return None


LIFECYCLE = ("status", "sync", "init")


def project(argv: List[str]) -> Path:
    """The lifecycle commands' positional path, else the working directory."""
    positional = [a for a in argv[1:] if not a.startswith("-")]
    return Path(positional[-1] if positional else os.getcwd())


def indexed_ancestor(path: Path) -> Optional[Path]:
    """The real walk-up: the nearest ancestor of PATH, PATH included, that holds
    `.codegraph/codegraph.db`."""
    for candidate in (path, *path.parents):
        if (candidate / INDEX_DIR / DB_NAME).is_file():
            return candidate
    return None


def check_argv(argv: List[str]) -> Optional[int]:
    """The real CLI's argv contract; an exit code when ARGV breaks it."""
    command = argv[0]
    if command in LIFECYCLE and "-p" in argv:
        print("error: unknown option '-p'", file=sys.stderr)
        return 1
    if command in QUERY_FIXTURES or command == "node":
        value = option(argv, "-p")
        if value is None or not Path(value).is_dir():
            print(f"✗ CodeGraph not initialized in {value or os.getcwd()}",
                  file=sys.stderr)
            return 1
    return None


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The index `init` writes
# --------------------------------------------------------------------------


def schema_statements() -> List[str]:
    """The recorded `.schema`, split into statements; FTS, triggers and the
    tables SQLite reserves are left out (a minimal schema, not a full one)."""
    statements: List[str] = []
    buffer = ""
    for line in fixture("schema.sql").splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    skip = ("VIRTUAL TABLE", "TRIGGER", "sqlite_", "nodes_fts")
    return [s for s in statements if not any(word in s for word in skip)]


def tracked(root: Path) -> List[str]:
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return sorted(p for p in proc.stdout.split("\0") if p)[:500]


def write_db(db: Path, root: Path, version: int = 11, edge_kind: bool = True) -> None:
    conn = sqlite3.connect(str(db))
    try:
        for statement in schema_statements():
            if not edge_kind and statement.startswith("CREATE TABLE edges"):
                statement = statement.replace("    kind TEXT NOT NULL,\n", "")
            try:
                conn.execute(statement)
            except sqlite3.Error:
                pass  # an index this SQLite build cannot create
        conn.executemany(
            "INSERT INTO schema_versions (version, applied_at, description) "
            "VALUES (?, 0, ?)",
            [(1, "Initial schema"), (version, "Initial schema includes all migrations")])
        files = tracked(root)
        for path in files:
            for kind, name in (("file", Path(path).name), ("function", "main")):
                conn.execute(
                    "INSERT INTO nodes (id, kind, name, qualified_name, file_path, "
                    "language, start_line, end_line, start_column, end_column, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, 'python', 1, 1, 0, 0, 0)",
                    (f"{kind}:{path}", kind, name, path, path))
            conn.execute(
                "INSERT INTO files (path, content_hash, language, size, modified_at, "
                "indexed_at, node_count) VALUES (?, '', 'python', 0, 0, 0, 2)", (path,))
            if edge_kind:
                conn.execute("INSERT INTO edges (source, target, kind) "
                             "VALUES (?, ?, 'contains')",
                             (f"file:{path}", f"function:{path}"))
        for edge in json.loads(os.environ.get("SHIM_EDGES") or "[]"):
            kind = edge[2] if len(edge) > 2 else "imports"
            if edge_kind:
                conn.execute("INSERT INTO edges (source, target, kind) VALUES (?, ?, ?)",
                             (f"file:{edge[0]}", f"file:{edge[1]}", kind))
            else:
                conn.execute("INSERT INTO edges (source, target) VALUES (?, ?)",
                             (f"file:{edge[0]}", f"file:{edge[1]}"))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_status(argv: List[str]) -> int:
    if MODE == "garbage":
        print("codegraph: something went sideways <not json>")
        return 0
    root = project(argv)
    found = indexed_ancestor(root)
    if MODE != "uninit" and found is not None:
        root = found  # an unindexed child answers for the indexed root above it
        status = json.loads(fixture("status-indexed.json"))
        status["dbSizeBytes"] = (root / INDEX_DIR / DB_NAME).stat().st_size
    else:
        status = json.loads(fixture("status-uninit.json"))
    status["projectPath"] = str(root)
    status["indexPath"] = str(root / INDEX_DIR)
    print(json.dumps(status))
    return 0


def cmd_init(argv: List[str]) -> int:
    if MODE == "uninit":
        print("error: init failed", file=sys.stderr)
        return 1
    root = project(argv)
    index = root / INDEX_DIR
    index.mkdir(parents=True, exist_ok=True)
    (index / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    db = index / DB_NAME
    if db.exists():
        db.unlink()
    if MODE == "corrupt-db":
        db.write_bytes(os.urandom(4096))
    elif MODE == "schema-mismatch":
        write_db(db, root, version=10, edge_kind=False)
    else:
        write_db(db, root)
    print(f"Indexed {len(tracked(root))} files")
    return 0


UNKNOWN_PREFIX = "no_such_"  # a symbol the index does not hold


def cmd_query(argv: List[str]) -> int:
    command = argv[0]
    symbol = next((a for a in argv[1:] if not a.startswith("-")), "")
    if command in ("impact", "callers", "callees") and symbol.startswith(UNKNOWN_PREFIX):
        # codegraph 1.6.2 prints this text and exits 0, even with `-j`.
        print(f'\u2139 Symbol "{symbol}" not found')
        return 0
    if command == "node" and symbol.startswith(UNKNOWN_PREFIX):
        print(f'Symbol "{symbol}" not found in the codebase')
        return 0
    if command == "explore" and symbol.startswith(UNKNOWN_PREFIX):
        print(f'No relevant code found for "{symbol}"\n\n'
              "Explore matches symbol/file names and indexed code words lexically.")
        return 0
    if command == "node":
        target = next((a for a in argv[1:] if not a.startswith("-")), "")
        name = "node-file.txt" if "/" in target or "." in target else "node-symbol.txt"
    else:
        name = QUERY_FIXTURES[command]
    sys.stdout.write(fixture(name))
    return 0


def main(argv: List[str]) -> int:
    log(argv, sys.stdin.read() if "--stdin" in argv else None)
    if not argv:
        print("usage: codegraph <command>", file=sys.stderr)
        return 2
    command = argv[0]
    if command in ("--version", "-V", "version"):
        print("1.5.0" if MODE == "old-version" else fixture("version.txt").strip())
        return 0
    broken = check_argv(argv)
    if broken is not None:
        return broken
    if command == "status":
        return cmd_status(argv)
    if MODE == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    if MODE == "hang":
        time.sleep(60)
    if command == "init":
        return cmd_init(argv)
    if command == "sync":
        print("Synced 0 files")
        return 0
    if command in QUERY_FIXTURES or command == "node":
        return cmd_query(argv)
    print(f"error: unknown command {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
