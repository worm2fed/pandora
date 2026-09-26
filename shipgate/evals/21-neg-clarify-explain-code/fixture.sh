#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p docs/prd
cat > README.md <<'MD'
# billing

Small invoicing service: customers, invoices, payment terms, receipts.

- `customers.py`, `invoices.py` — in-memory records (the SQLite schema in `schema.sql` is what
  production runs on; the in-memory store mirrors it).
- `payments.py` — payments received against invoices (amount, date).
- `terms.py` — payment terms: due dates and days-until-due for an invoice.
- `overdue.py` — decides whether an invoice is overdue.
- `mailer.py` — **email delivery** over SMTP. Used today for receipts; this is the only outbound
  channel the service has.
- `api.py` — the JSON API (`GET /customers`, `GET /invoices`), documented in `docs/api.md`.
- `errors.py` — user-facing error messages.

Tests: `python3 -m unittest`. PRDs live in `docs/prd/` (see `docs/prd/receipt-emails.md`).
MD
cat > CLAUDE.md <<'MD'
# billing — conventions

- Standard library only; no third-party packages.
- Tests: `python3 -m unittest`.
- Product docs: PRDs in `docs/prd/<feature-kebab>.md`, ADRs in `docs/adr/`.
- `docs/api.md` is the public API contract; the mobile app and the finance export consume it.
MD
cat > customers.py <<'PY'
from dataclasses import dataclass


@dataclass
class Customer:
    id: int
    name: str
    email: str


CUSTOMERS = [
    Customer(1, "Acme", "billing@acme.example"),
    Customer(2, "Globex, Inc.", "ap@globex.example"),
]


def list_customers():
    return list(CUSTOMERS)
PY
cat > invoices.py <<'PY'
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class Invoice:
    number: str
    customer_id: int
    issued: date
    net_days: int
    total: Decimal
    status: str  # "open" | "paid"


INVOICES = [
    Invoice("INV-001", 1, date(2026, 9, 1), 30, Decimal("200.00"), "open"),
    Invoice("INV-002", 2, date(2026, 8, 20), 14, Decimal("119.00"), "paid"),
    Invoice("INV-003", 2, date(2026, 8, 25), 14, Decimal("80.50"), "open"),
]


def list_invoices(status=None):
    return [i for i in INVOICES if status in (None, "all", i.status)]
PY
cat > payments.py <<'PY'
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class Payment:
    invoice_number: str
    amount: Decimal
    received: date


PAYMENTS = [
    Payment("INV-002", Decimal("119.00"), date(2026, 9, 2)),
]


def list_payments(customer_id=None):
    from invoices import INVOICES
    numbers = {i.number for i in INVOICES if customer_id in (None, i.customer_id)}
    return [p for p in PAYMENTS if p.invoice_number in numbers]
PY
cat > terms.py <<'PY'
"""Payment terms: when an invoice is due and how far away that is."""
from datetime import timedelta


def due_date(invoice):
    """Issued date + net days; a due date on a weekend moves to the following Monday."""
    d = invoice.issued + timedelta(days=invoice.net_days)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def days_until_due(invoice, today):
    """Whole days from `today` to the due date; negative once it is past."""
    return (due_date(invoice) - today).days
PY
cat > overdue.py <<'PY'
from datetime import timedelta

from terms import due_date

GRACE_DAYS = 3


def is_overdue(invoice, today):
    """Open invoices become overdue once `today` is more than GRACE_DAYS past the due date."""
    if invoice.status == "paid":
        return False
    return today > due_date(invoice) + timedelta(days=GRACE_DAYS)
PY
cat > mailer.py <<'PY'
import smtplib
from email.message import EmailMessage

SMTP_HOST = "localhost"


def send_email(to, subject, body):
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST) as s:
        s.send_message(msg)
PY
cat > errors.py <<'PY'
UNKNOWN_INVOICE = "Payment recieved for an unknown invoice: {number}"
CUSTOMER_NOT_FOUND = "Customer {id} not found"
PY
cat > api.py <<'PY'
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer

from customers import list_customers
from invoices import list_invoices


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/customers":
            body = [asdict(c) for c in list_customers()]
        elif self.path.startswith("/invoices"):
            body = [{**asdict(i), "issued": i.issued.isoformat(), "total": str(i.total)} for i in list_invoices()]
        else:
            self.send_response(404); self.end_headers(); return
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("", 8080), Handler).serve_forever()
PY
cat > schema.sql <<'SQL'
CREATE TABLE customers (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL,
  email TEXT NOT NULL
);

CREATE TABLE invoices (
  number      TEXT PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  issued      DATE NOT NULL,
  net_days    INTEGER NOT NULL,
  total       NUMERIC(12, 2) NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open', 'paid'))
);

CREATE TABLE payments (
  id             INTEGER PRIMARY KEY,
  invoice_number TEXT NOT NULL REFERENCES invoices(number),
  amount         NUMERIC(12, 2) NOT NULL,
  received       DATE NOT NULL
);
SQL
cat > docs/api.md <<'MD'
# Public JSON API

Consumed by the mobile app and by the finance export job. Field names and their meaning are a
contract: removing or repurposing a field is a breaking change for both consumers.

## GET /customers

Returns every customer: `[{"id": 1, "name": "Acme", "email": "billing@acme.example"}, ...]`

## GET /invoices

Returns every invoice: `number, customer_id, issued (ISO date), net_days, total (string), status`.
MD
cat > docs/prd/receipt-emails.md <<'MD'
---
type: prd
title: "PRD: Receipt emails"
status: done
issue: "#388"
---

# PRD: Receipt emails

> Email a receipt when an invoice is marked paid.

## Functional requirements

- **FR-001** — When an invoice changes to `paid`, an email is sent to the customer's address.
- **FR-002** — The receipt states the invoice number, the amount, and the payment date.

## Success criteria

- **SC-001** — 100% of paid invoices in a day have a matching sent receipt in the mail log.
MD
cat > test_terms.py <<'PY'
import unittest
from datetime import date
from decimal import Decimal

from invoices import Invoice
from overdue import is_overdue
from terms import days_until_due, due_date


class TermsTest(unittest.TestCase):
    def test_due_date_skips_weekend(self):
        inv = Invoice("X", 1, date(2026, 9, 4), 1, Decimal("1"), "open")  # Fri + 1 = Sat -> Mon
        self.assertEqual(due_date(inv), date(2026, 9, 7))

    def test_days_until_due(self):
        inv = Invoice("X", 1, date(2026, 9, 1), 30, Decimal("1"), "open")
        self.assertEqual(days_until_due(inv, date(2026, 9, 21)), 10)

    def test_overdue_after_grace(self):
        inv = Invoice("X", 1, date(2026, 9, 1), 30, Decimal("1"), "open")
        self.assertFalse(is_overdue(inv, date(2026, 10, 4)))
        self.assertTrue(is_overdue(inv, date(2026, 10, 5)))

    def test_paid_never_overdue(self):
        inv = Invoice("X", 1, date(2026, 1, 1), 1, Decimal("1"), "paid")
        self.assertFalse(is_overdue(inv, date(2026, 9, 1)))


if __name__ == "__main__":
    unittest.main()
PY
c 2026-09-01 "feat: billing service — customers, invoices, terms, receipts"
