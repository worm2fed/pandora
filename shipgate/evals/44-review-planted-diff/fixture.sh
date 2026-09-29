#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p docs/prd
cat > CLAUDE.md <<'EOF_F'
# billing — conventions

- SQL is always parameterised (`db.query(sql, *params)`); never interpolate values into SQL strings.
- Money is formatted only through `money.fmt()`; never format amounts inside other modules.
- No `print` for logging; use `log.info` / `log.debug` from `logging_.py`. Export paths log at DEBUG.
- Tests: `python3 -m unittest`.
- PRDs live in `docs/prd/<feature>.md`; the worklog beside it records design, build plan and deviations.
EOF_F
cat > db.py <<'EOF_F'
"""Tiny query layer over sqlite."""
import sqlite3


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE invoices (number TEXT, customer TEXT, total INTEGER, status TEXT)")
        self.conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?)", [
            ("INV-001", "Acme", 20000, "open"), ("INV-002", "Globex, Inc.", 11900, "paid"), ("INV-003", "Initech", 8050, "open")])

    def query(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()
EOF_F
cat > money.py <<'EOF_F'
def fmt(cents):
    return f"{cents // 100}.{cents % 100:02d}"
EOF_F
cat > logging_.py <<'EOF_F'
import logging

log = logging.getLogger("billing")
EOF_F
cat > test_db.py <<'EOF_F'
import unittest

from db import DB


class DBTest(unittest.TestCase):
    def test_seed(self):
        self.assertEqual(len(DB().query("SELECT * FROM invoices")), 3)
EOF_F
cat > docs/prd/csv-export.md <<'EOF_F'
---
type: prd
title: "PRD: Invoice CSV export"
status: clarified
issue: "#412"
---

# PRD: Invoice CSV export

## Functional requirements
- **FR-001** — Export invoices as CSV with a header row and one row per invoice: number, customer, total, status.
- **FR-002** — Customer names containing commas or quotes are quoted so the file opens correctly in a spreadsheet.
- **FR-003** — The export can be limited to invoices of one status (`open` or `paid`) or return all.

## Success criteria
- **SC-001** — For N invoices the export has exactly N + 1 lines and every line has exactly 4 columns.
- **SC-002** — `export(status="open")` contains only open invoices; `export()` contains all.
- **SC-003** — "Globex, Inc." occupies one column when the file is parsed by a CSV reader.
EOF_F
cat > docs/prd/csv-export.worklog.md <<'EOF_F'
# Worklog: Invoice CSV export

## Design
`export.py` exposes `export(status=None) -> str`. Rows come from `DB.query`; formatting goes through `money.fmt`.

## Build plan
- [x] T1 header + rows
- [x] T2 quoting (FR-002 / SC-003)
- [x] T3 status filter (FR-003 / SC-002)

## Deviations (authorised)
- 2026-09-20 — Export logs at INFO instead of DEBUG (CLAUDE.md says DEBUG): the ops team asked to see exports in the default log level for the first two weeks after launch. Authorised by the user; revisit 2026-10-05.
- 2026-09-20 — No CSV formula-injection guard (values starting with `=`, `+`, `-`, `@`) in v1: the file is consumed by finance's own sheet from CRM-sourced names, and the guard changes displayed values. Decided at Clarify; authorised by the user. Revisit if the export is ever exposed to customers.
EOF_F
c 2026-09-15 "feat: billing base; PRD + worklog for CSV export"
cat > export.py <<'EOF_F'
"""Invoice CSV export (FR-001..003)."""
from db import DB
from logging_ import log
from money import fmt

HEADER = "number,customer,total,status"


def _quote(value):
    value = str(value)
    if "," in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def csv_rows(records):
    rows = []
    for number, customer, total, status in records:
        line = f"{number},{customer},{fmt(total)},{status}"
        rows.append(",".join(_quote(v) for v in line.split(",")))
    return rows


def export(status=None, db=None):
    db = db or DB()
    if status:
        records = db.query(f"SELECT number, customer, total, status FROM invoices WHERE status = '{status}'")
    else:
        records = db.query("SELECT number, customer, total, status FROM invoices")
    log.info("export: %d invoices", len(records))
    return "\n".join([HEADER] + csv_rows(records))
EOF_F
cat > test_export.py <<'EOF_F'
import unittest

from export import export


class ExportTest(unittest.TestCase):
    def test_header(self):
        self.assertTrue(export().startswith("number,customer,total,status"))
EOF_F
c 2026-09-21 "feat(export): invoice CSV export (T1-T3)"
