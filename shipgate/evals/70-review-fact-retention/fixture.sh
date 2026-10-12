#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
# HEAD plants three findings, one per file: SQL interpolation in db.py (blocker), CSV quoting
# lost in export.py (high), money formatted outside money.fmt() in report.py (medium).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p docs/prd
cat > CLAUDE.md <<'EOF_F'
# billing — conventions

- SQL is always parameterised (`db.query(sql, *params)`); never interpolate values into SQL strings.
- Money is formatted only through `money.fmt()`; never format amounts inside other modules.
- No `print` for logging; use `log.info` / `log.debug` from `logging_.py`.
- Tests: `python3 -m unittest`.
- PRDs live in `docs/prd/<feature>.md`; the worklog beside it records design and build plan.
EOF_F
cat > db.py <<'EOF_F'
"""Tiny query layer over sqlite."""
import sqlite3


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE invoices (number TEXT, customer TEXT, total INTEGER, status TEXT)")
        self.conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?)", [
            ("INV-001", "Acme", 20000, "open"), ("INV-002", "Globex, Inc.", 11900, "paid"), ("INV-003", "Initech", 2500, "open")])

    def query(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()
EOF_F
cat > money.py <<'EOF_F'
"""The one place amounts become text."""
from decimal import ROUND_HALF_UP, Decimal


def fmt(cents):
    """Format an amount in cents (int or Decimal) as units.cents, rounding half up to the cent."""
    cents = Decimal(cents).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{cents // 100}.{cents % 100:02}"
EOF_F
cat > logging_.py <<'EOF_F'
import logging

log = logging.getLogger("billing")
EOF_F
cat > export.py <<'EOF_F'
"""Invoice CSV export."""
import csv
import io

from db import DB
from money import fmt

HEADER = ["number", "customer", "total", "status"]


def export(db=None):
    db = db or DB()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for number, customer, total, status in db.query("SELECT number, customer, total, status FROM invoices"):
        writer.writerow([number, customer, fmt(total), status])
    return out.getvalue().rstrip("\n")
EOF_F
cat > test_db.py <<'EOF_F'
import unittest

from db import DB


class DBTest(unittest.TestCase):
    def test_seed(self):
        self.assertEqual(len(DB().query("SELECT * FROM invoices")), 3)
EOF_F
cat > test_money.py <<'EOF_F'
import unittest
from decimal import Decimal

from money import fmt


class MoneyTest(unittest.TestCase):
    def test_whole_cents(self):
        self.assertEqual(fmt(11900), "119.00")

    def test_half_cent_rounds_up(self):
        self.assertEqual(fmt(Decimal("12.5")), "0.13")
EOF_F
cat > test_export.py <<'EOF_F'
import unittest

from export import export


class ExportTest(unittest.TestCase):
    def test_header(self):
        self.assertTrue(export().startswith("number,customer,total,status"))

    def test_one_row_per_invoice(self):
        self.assertEqual(len(export().splitlines()), 4)
EOF_F
c 2026-09-10 "feat: billing base with invoice CSV export"
cat > docs/prd/customer-statements.md <<'EOF_F'
---
type: prd
title: "PRD: Customer statements"
status: clarified
issue: "#418"
---

# PRD: Customer statements

## Functional requirements
- **FR-001** — A statement for one customer lists that customer's invoices and the amount due (sum of open invoices).
- **FR-002** — The statement adds a late fee of 0.5% of the amount due, rounded half up to the cent.
- **FR-003** — The invoice CSV export can be limited to one customer; every row keeps exactly 4 columns.
- **FR-004** — The customer name comes from the account-manager search box in the admin UI.

## Success criteria
- **SC-001** — `statement("Initech")` shows amount due 25.00 and late fee 0.13 (0.5% of 2500 cents is 12.5 cents, rounded half up).
- **SC-002** — `export(customer="Globex, Inc.")` has a header and one row, and each line parses to 4 columns with a CSV reader.
- **SC-003** — A customer name with a quote or comma never changes which invoices are returned.
EOF_F
cat > docs/prd/customer-statements.worklog.md <<'EOF_F'
# Worklog: Customer statements

## Design
- `db.py` gains `invoices_for(customer)`, used by both the statement and the export.
- `report.py` (new) exposes `statement(customer) -> str`: one line per invoice, then amount due and late fee.
- `export.py` gains a `customer=` filter; rows are built inline.
- All amounts go through `money.fmt` (CLAUDE.md).

## Build plan
- [x] T1 `DB.invoices_for` (FR-001, FR-004)
- [x] T2 `report.statement` with late fee (FR-001, FR-002 / SC-001)
- [x] T3 export customer filter (FR-003 / SC-002)
EOF_F
c 2026-09-18 "docs: PRD + worklog for customer statements"
cat > db.py <<'EOF_F'
"""Tiny query layer over sqlite."""
import sqlite3


class DB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE invoices (number TEXT, customer TEXT, total INTEGER, status TEXT)")
        self.conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?)", [
            ("INV-001", "Acme", 20000, "open"), ("INV-002", "Globex, Inc.", 11900, "paid"), ("INV-003", "Initech", 2500, "open")])

    def query(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()

    def invoices_for(self, customer):
        """Invoices of one customer, as (number, customer, total, status) rows."""
        return self.query(
            f"SELECT number, customer, total, status FROM invoices WHERE customer = '{customer}' ORDER BY number")
EOF_F
cat > export.py <<'EOF_F'
"""Invoice CSV export."""
from db import DB
from money import fmt

HEADER = "number,customer,total,status"


def export(customer=None, db=None):
    db = db or DB()
    if customer:
        records = db.invoices_for(customer)
    else:
        records = db.query("SELECT number, customer, total, status FROM invoices")
    lines = [HEADER]
    for number, name, total, status in records:
        lines.append(f"{number},{name},{fmt(total)},{status}")
    return "\n".join(lines)
EOF_F
cat > report.py <<'EOF_F'
"""Customer statement (FR-001, FR-002)."""
from decimal import Decimal

from db import DB
from money import fmt

LATE_FEE_RATE = Decimal("0.005")


def statement(customer, db=None):
    db = db or DB()
    rows = db.invoices_for(customer)
    lines = [f"Statement for {customer}"]
    for number, _, total, status in rows:
        lines.append(f"{number}  {fmt(total)}  {status}")
    due = sum(total for _, _, total, status in rows if status == "open")
    fee = Decimal(due) * LATE_FEE_RATE
    lines.append(f"Amount due: {fmt(due)}")
    lines.append(f"Late fee: {fee / 100:.2f}")
    return "\n".join(lines)
EOF_F
cat > test_report.py <<'EOF_F'
import unittest

from report import statement


class StatementTest(unittest.TestCase):
    def test_acme(self):
        text = statement("Acme")
        self.assertIn("INV-001", text)
        self.assertIn("Amount due: 200.00", text)
        self.assertIn("Late fee: 1.00", text)
EOF_F
cat > test_export.py <<'EOF_F'
import unittest

from export import export


class ExportTest(unittest.TestCase):
    def test_header(self):
        self.assertTrue(export().startswith("number,customer,total,status"))

    def test_one_row_per_invoice(self):
        self.assertEqual(len(export().splitlines()), 4)

    def test_customer_filter(self):
        self.assertEqual(len(export(customer="Acme").splitlines()), 2)
EOF_F
c 2026-09-24 "feat(statements): customer statement and per-customer export (T1-T3)"
