#!/usr/bin/env bash
# Fixture for the two-turn check of SC-010 (ADR 0023): builds a small journaled Python repo
# in the CURRENT directory. Synthetic throughout.
#
# The stream `feat/12-csv-export` is in implement, T001 is verified and done, and its
# change sits uncommitted in the working tree. The user asks for the commit. The command
# gate holds `git commit` until the stream holds the user's go, so the flow should record
# a `go-requested` at the commit gate and ask with the header `Commit`. The driver
# (two_turn.py) then gives the reply "it can go"; the flow should read it, record a read
# go that names the recorder's witness, ask no confirming question, and commit.
#
# Event times are minutes before the fixture runs, so the stream is live, not dormant. The
# repo carries its own git identity, so a commit works under a scratch HOME.
set -e
python3 - <<'PYGEN'
import json
import os
import sqlite3
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone

ENV = dict(os.environ, GIT_AUTHOR_NAME="dev", GIT_AUTHOR_EMAIL="dev@example.com",
           GIT_COMMITTER_NAME="dev", GIT_COMMITTER_EMAIL="dev@example.com")
STREAM = "feat/12-csv-export"
NOW = datetime.now(timezone.utc)


def sh(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)


def write(path, body):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))


def commit(msg):
    sh("git", "add", "-A")
    sh("git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qm", msg)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.name", "dev")
sh("git", "config", "user.email", "dev@example.com")
sh("git", "config", "commit.gpgsign", "false")
write(".gitignore", "__pycache__/\n.claude/shipgate.db*\n")
write("README.md", "# orders — order history service\n\nPython 3. `python3 -m unittest` runs the tests.\n")
write("CLAUDE.md", """
    # orders — conventions

    - Money is integer cents.
    - Tests sit in `tests/`, one module per source module.
""")
write(".claude/shipgate.md", """
    # shipgate — project config

    ## Knowledge base
    - PRD home: `docs/prd/`
    - ADR home: `docs/adr/`

    ## Journal
    - Database: `.claude/shipgate.db`

    ## Branching
    - Pattern: `<type>/<issue-id>-<slug>`

    ## Autonomy
    - Mode: executive
""")
write(".claude/shipgate.json", json.dumps({
    "version": 1, "db": ".claude/shipgate.db",
    "artifact_homes": {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md", "worklog": "docs/prd/*.worklog.md"},
    "enforce": {"stop_gate": True, "auto_capture": True, "command_gate": True},
}, indent=2) + "\n")
write("orders/__init__.py", "")
write("orders/history.py", """
    def rows(orders):
        \"\"\"One row per order: id, date, total in cents.\"\"\"
        return [(o["id"], o["date"], o["total"]) for o in orders]
""")
write("tests/__init__.py", "")
write("tests/test_history.py", """
    import unittest

    from orders.history import rows


    class TestRows(unittest.TestCase):
        def test_one_row_per_order(self):
            self.assertEqual(rows([{"id": 1, "date": "2026-01-02", "total": 450}]),
                             [(1, "2026-01-02", 450)])
""")
commit("feat: order history rows")
sh("git", "checkout", "-q", "-b", STREAM)
write("docs/prd/csv-export.md", """
    ---
    type: prd
    title: "PRD: CSV export of the order history"
    status: clarified
    ---

    # PRD: CSV export of the order history

    - **FR-001** — `to_csv(orders)` returns the history as CSV with a header line.
    - **FR-002** — the total prints in euros with two decimals.
""")
write("docs/prd/csv-export.worklog.md", """
    # Worklog: CSV export

    # Build Plan

    - [x] T001 — `to_csv` with a header line — file(s): `orders/export.py`,
      `tests/test_export.py` — done when: the test passes.
    - [ ] T002 — totals in euros with two decimals — done when: the test passes.
""")
commit("docs: CSV export PRD and worklog")
# T001's change: verified, recorded as done, not committed.
write("orders/export.py", """
    import csv
    import io

    from orders.history import rows


    def to_csv(orders):
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\\n")
        writer.writerow(["id", "date", "total"])
        writer.writerows(rows(orders))
        return out.getvalue()
""")
write("tests/test_export.py", """
    import unittest

    from orders.export import to_csv


    class TestToCsv(unittest.TestCase):
        def test_a_header_then_one_line_per_order(self):
            self.assertEqual(to_csv([{"id": 1, "date": "2026-01-02", "total": 450}]),
                             "id,date,total\\n1,2026-01-02,450\\n")
""")

EVENTS = [
    (ago(90), "flow-started", {"request": "CSV export of the order history (#12)", "branch": STREAM}),
    (ago(89), "phase-entered", {"phase": "workspace"}),
    (ago(80), "phase-entered", {"phase": "clarify", "skipped": ["route-and-map", "explore"], "implied": True, "implied_by": "clarify-passed"}),
    (ago(80), "clarify-passed", {"prd": "docs/prd/csv-export.md"}),
    (ago(60), "phase-entered", {"phase": "design", "implied": True, "implied_by": "design-committed"}),
    (ago(60), "design-committed", {"worklog": "docs/prd/csv-export.worklog.md"}),
    (ago(30), "phase-entered", {"phase": "implement", "style": []}),
    (ago(6), "verify-run", {"outcome": "pass", "task_ids": ["T001"], "commands": [{"cmd": "python3 -m unittest", "exit": 0}]}),
    (ago(5), "task-done", {"task_id": "T001"}),
]
os.makedirs(".claude", exist_ok=True)
conn = sqlite3.connect(".claude/shipgate.db")
conn.executescript("""
    CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL, version INTEGER NOT NULL,
      type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)), ts TEXT NOT NULL, actor TEXT,
      UNIQUE (stream, version));
    CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, seq);
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""")
for key, value in (("schema_version", "1"), ("created_at", ago(90))):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
for version, (ts, kind, data) in enumerate(EVENTS, 1):
    conn.execute("INSERT INTO events (stream, version, type, data, ts, actor) VALUES (?, ?, ?, ?, ?, ?)",
                 (STREAM, version, kind, json.dumps(data, sort_keys=True), ts, "orchestrator"))
conn.commit()
conn.close()
PYGEN
